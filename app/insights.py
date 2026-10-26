"""Project-level insights used by the AI Web workbench.

The module deliberately keeps network-free checks local: dependency manifests
are inspected without claiming to be a CVE database, and Git evidence is read
from a submitted archive only when the archive contains a real ``.git``
directory.  This makes the results suitable for teaching and repeatable demos.
"""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


DEPENDENCY_NAMES = {
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "pom.xml",
    "build.gradle",
    "package-lock.json",
}


def _is_unpinned(version: str) -> bool:
    value = (version or "").strip().lower()
    return not value or value in {"*", "latest", "any"} or value.startswith((">", "<", "~", "^"))


def _add_dependency(items: list[dict], manifest: str, name: str, version: str, group: str = "") -> None:
    version = str(version or "").strip()
    items.append({
        "manifest": manifest,
        "name": f"{group}:{name}" if group else name,
        "version": version or "未声明",
        "status": "版本范围较宽" if _is_unpinned(version) else "已声明版本",
        "recommendation": "提交前锁定依赖版本，并在升级前核查官方安全公告。" if _is_unpinned(version) else "保留依赖清单，定期核查版本安全公告。",
    })


def analyze_dependencies(files: Iterable[tuple[str, str]]) -> dict:
    """Extract dependency inventory and lightweight hygiene signals.

    This is intentionally not presented as a vulnerability database lookup.
    It gives the reviewer a reproducible dependency inventory and points out
    unpinned or missing versions that deserve manual review.
    """

    items: list[dict] = []
    manifests: list[str] = []
    for file_name, text in files:
        base_name = PurePosixPath(file_name.replace("\\", "/")).name.lower()
        if base_name not in DEPENDENCY_NAMES:
            continue
        manifests.append(file_name)
        if base_name == "requirements.txt":
            for raw in text.splitlines():
                line = raw.strip()
                if not line or line.startswith(("#", "-")):
                    continue
                match = __import__("re").match(r"([A-Za-z0-9_.-]+)\s*([<>=!~].*)?$", line)
                if match:
                    _add_dependency(items, file_name, match.group(1), match.group(2) or "")
        elif base_name in {"package.json", "package-lock.json"}:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            for section in ("dependencies", "devDependencies", "optionalDependencies"):
                for name, version in (payload.get(section) or {}).items():
                    _add_dependency(items, file_name, name, str(version))
        elif base_name == "pom.xml":
            import xml.etree.ElementTree as ET

            try:
                root = ET.fromstring(text)
            except ET.ParseError:
                continue
            for dependency in root.findall(".//{*}dependency"):
                group = dependency.findtext("{*}groupId", default="")
                name = dependency.findtext("{*}artifactId", default="")
                version = dependency.findtext("{*}version", default="")
                if name:
                    _add_dependency(items, file_name, name, version, group)
        else:
            # Keep unsupported manifest formats visible without pretending we
            # parsed every build system.
            items.append({
                "manifest": file_name,
                "name": "待人工核查",
                "version": "未解析",
                "status": "需要人工核查",
                "recommendation": "确认依赖名称、版本和锁定文件是否完整。",
            })
    return {
        "manifest_count": len(manifests),
        "dependency_count": len(items),
        "unpinned_count": sum(item["status"] == "版本范围较宽" for item in items),
        "manifests": manifests,
        "items": items,
        "note": "依赖检查只做清单与版本卫生提示，不替代专业漏洞数据库扫描。",
    }


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    total_size = 0
    for info in archive.infolist():
        name = PurePosixPath(info.filename.replace("\\", "/"))
        if name.is_absolute() or ".." in name.parts:
            continue
        if info.is_dir():
            continue
        if info.file_size > 10 * 1024 * 1024:
            continue
        total_size += info.file_size
        if total_size > 80 * 1024 * 1024:
            break
        target = destination.joinpath(*name.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(info))


def analyze_git_archive(blob: bytes) -> dict:
    """Read development-history evidence when an uploaded ZIP includes Git."""

    result = {
        "included": False,
        "commit_count": 0,
        "author_count": 0,
        "authors": [],
        "first_commit": "",
        "last_commit": "",
        "recent_commits": [],
        "warning": "压缩包未包含 .git 历史，无法从本次上传核验开发过程。",
    }
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            names = [PurePosixPath(item.filename.replace("\\", "/")) for item in archive.infolist()]
            git_heads = [path for path in names if ".git" in path.parts and path.name == "HEAD"]
            if not git_heads:
                return result
            with tempfile.TemporaryDirectory(prefix="zhian-git-") as temp_dir:
                root = Path(temp_dir)
                _safe_extract(archive, root)
                candidate_roots = []
                for head in git_heads:
                    git_index = head.parts.index(".git")
                    candidate_roots.append(root.joinpath(*head.parts[:git_index]))
                repo_root = next((path for path in candidate_roots if (path / ".git").exists()), None)
                if repo_root is None:
                    return result
                completed = subprocess.run(
                    ["git", "-C", str(repo_root), "log", "--all", "--format=%H%x09%aI%x09%an%x09%s"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    check=False,
                )
                if completed.returncode != 0:
                    result["warning"] = "发现 .git，但读取提交记录失败，请确认仓库结构完整。"
                    return result
                lines = [line for line in completed.stdout.splitlines() if line.strip()]
                parsed = []
                for line in lines:
                    parts = line.split("\t", 3)
                    if len(parts) == 4:
                        parsed.append({"hash": parts[0][:10], "time": parts[1], "author": parts[2], "message": parts[3]})
                authors = sorted({item["author"] for item in parsed})
                result.update({
                    "included": True,
                    "commit_count": len(parsed),
                    "author_count": len(authors),
                    "authors": authors[:10],
                    "first_commit": parsed[-1]["time"] if parsed else "",
                    "last_commit": parsed[0]["time"] if parsed else "",
                    "recent_commits": parsed[:8],
                    "warning": "已读取 Git 提交历史；提交记录只能证明开发过程，不能替代原创性声明。",
                })
                return result
    except (OSError, zipfile.BadZipFile, subprocess.SubprocessError):
        result["warning"] = "读取 Git 历史时发生异常，请保留本地仓库作为评审证据。"
        return result


def local_git_evidence(project_path: str | Path) -> dict:
    """Summarise the repository that owns the running application."""

    path = Path(project_path)
    result = {"repository": path.name, "initialized": False, "commit_count": 0, "authors": [], "recent_commits": [], "warning": "尚未初始化 Git。"}
    if not (path / ".git").exists():
        return result
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "log", "--format=%H%x09%aI%x09%an%x09%s"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        parsed = []
        for line in lines:
            parts = line.split("\t", 3)
            if len(parts) == 4:
                parsed.append({"hash": parts[0][:10], "time": parts[1], "author": parts[2], "message": parts[3]})
        result.update({
            "initialized": True,
            "commit_count": len(parsed),
            "authors": sorted({item["author"] for item in parsed}),
            "recent_commits": parsed[:8],
            "warning": "Git 开发记录已建立，请继续按功能提交，不要一次性上传全部代码。",
        })
        return result
    except (OSError, subprocess.SubprocessError):
        result["warning"] = "Git 已存在，但读取记录失败。"
        return result
