"""Original hybrid secret-leak scanner.

The detector intentionally combines signal families rather than relying on one
large regular-expression list. Each finding keeps its source location, a
confidence score, a severity level, and an educational remediation message.
"""

from __future__ import annotations

import base64
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Iterable


SUPPORTED_SUFFIXES = {
    ".py", ".java", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".js", ".jsx",
    ".ts", ".tsx", ".json", ".yaml", ".yml", ".xml", ".env", ".properties",
    ".ini", ".conf", ".config", ".txt",
}
IGNORED_PARTS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}


@dataclass
class Finding:
    id: str
    file_name: str
    line_number: int
    column: int
    code_line: str
    category: str
    rule_name: str
    severity: str
    score: int
    confidence: int
    status: str = "待确认"
    evidence: str = ""
    recommendation: str = ""
    example_code: str = ""
    masked_line: str = ""
    start: int = 0
    end: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScanResult:
    scan_id: str
    files: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    source_name: str = ""
    dependencies: dict = field(default_factory=dict)
    git_evidence: dict = field(default_factory=dict)

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def line_count(self) -> int:
        return sum(item["line_count"] for item in self.files)

    def summary(self) -> dict:
        levels = {"严重": 0, "高": 0, "中": 0, "低": 0}
        categories: dict[str, int] = {}
        statuses: dict[str, int] = {}
        for finding in self.findings:
            levels[finding.severity] = levels.get(finding.severity, 0) + 1
            categories[finding.category] = categories.get(finding.category, 0) + 1
            statuses[finding.status] = statuses.get(finding.status, 0) + 1
        penalty = sum({"严重": 18, "高": 10, "中": 4, "低": 1}.get(f.severity, 0) for f in self.findings)
        score = max(0, min(100, 100 - penalty))
        return {
            "files": self.file_count,
            "lines": self.line_count,
            "findings": len(self.findings),
            "score": score,
            "levels": levels,
            "categories": categories,
            "statuses": statuses,
            "dependencies": self.dependencies.get("dependency_count", 0),
            "git_commits": self.git_evidence.get("commit_count", 0),
        }


@dataclass(frozen=True)
class Rule:
    key: str
    category: str
    name: str
    base_score: int
    regex: re.Pattern[str]
    recommendation: str
    example_code: str


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


RULES = [
    Rule(
        "api-key-assignment", "API Key", "API 密钥赋值", 78,
        _compile(r"\b(?:api[_-]?key|apikey|client[_-]?secret|access[_-]?token)\b\s*[:=]\s*[\"']?([A-Za-z0-9_\-]{12,})"),
        "将密钥移出源码，放入环境变量或密钥管理服务，并在部署时注入。提交代码前同步清理历史提交中的旧密钥。",
        'api_key = os.environ["SERVICE_API_KEY"]',
    ),
    Rule(
        "access-secret-pair", "Access Key / Secret Key", "访问密钥对", 88,
        _compile(r"\b(?:access[_-]?key|secret[_-]?key|aws_access_key_id|aws_secret_access_key)\b\s*[:=]\s*[\"']?([A-Za-z0-9_\-/+=]{12,})"),
        "不要在代码仓库中保存访问密钥或私钥。立即轮换可能已经暴露的凭证，并使用环境变量或云端密钥管理服务。",
        'access_key = os.getenv("CLOUD_ACCESS_KEY")\nsecret_key = os.getenv("CLOUD_SECRET_KEY")',
    ),
    Rule(
        "database-credential", "数据库账号密码", "数据库凭据", 84,
        _compile(r"\b(?:password|passwd|pwd|db_password|database_password)\b\s*[:=]\s*[\"']([^\"']{4,})[\"']|(?:mysql|postgres(?:ql)?|mongodb(?:\+srv)?)://[^\s\"']+:[^\s\"']+@"),
        "把数据库密码放进环境变量或密钥服务，连接串中不要嵌入真实密码。为不同环境使用独立账号，并限制账号权限。",
        'db_password = os.getenv("DATABASE_PASSWORD")\nurl = f"postgresql://app_user:{db_password}@db.example/app"',
    ),
    Rule(
        "jwt-token", "JWT Token", "JWT 令牌", 76,
        _compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        "不要把 JWT 写入源码、日志或截图。使用短时效令牌，并通过安全的运行时配置或登录流程获取。",
        'token = request.headers.get("Authorization")\nif token and token.startswith("Bearer "):\n    token = token[7:]',
    ),
    Rule(
        "email-address", "邮箱", "邮箱地址", 32,
        _compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b"),
        "确认邮箱是否属于业务必须信息。公开代码中使用示例地址或脱敏数据，避免将真实个人信息提交到仓库。",
        'contact_email = "student@example.com"  # 示例数据',
    ),
    Rule(
        "mobile-number", "手机号", "手机号", 36,
        _compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)"),
        "测试代码使用虚构号码或哈希后的测试标识，真实手机号应放在受控数据源中，并限制访问和导出。",
        'phone = os.getenv("TEST_PHONE", "13800000000")  # 仅用于本地演示',
    ),
]

PLACEHOLDER_WORDS = {
    "example", "sample", "dummy", "changeme", "change-me", "your_key", "your-key",
    "replace", "test", "testing", "fake", "placeholder", "todo", "xxx", "none", "null",
}
CONTEXT_BOOST_WORDS = {"prod", "production", "credential", "password", "secret", "private", "db"}


def _is_ignored_path(file_name: str) -> bool:
    path = PurePosixPath(file_name.replace("\\", "/"))
    return any(part in IGNORED_PARTS for part in path.parts)


def is_supported_file(file_name: str) -> bool:
    if _is_ignored_path(file_name):
        return False
    suffix = PurePosixPath(file_name).suffix.lower()
    return suffix in SUPPORTED_SUFFIXES or PurePosixPath(file_name).name in {".env", "Dockerfile"}


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {char: value.count(char) for char in set(value)}
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _looks_like_placeholder(value: str, line: str) -> bool:
    lower = value.lower()
    if any(word in lower for word in PLACEHOLDER_WORDS):
        return True
    return any(word in line.lower() for word in {"example", "demo", "mock", "dummy", "test"})


def _level(score: int) -> str:
    if score >= 90:
        return "严重"
    if score >= 70:
        return "高"
    if score >= 45:
        return "中"
    return "低"


def _mask(value: str, category: str) -> str:
    if len(value) <= 6:
        masked = "*" * len(value)
    else:
        masked = value[:3] + "*" * min(12, len(value) - 6) + value[-3:]
    return f"[{category}已脱敏:{masked}]"


def _score(rule: Rule, value: str, line: str, file_name: str) -> tuple[int, int]:
    score = rule.base_score
    context = line.lower()
    if any(word in context for word in CONTEXT_BOOST_WORDS):
        score += 8
    if "=" in line or ":" in line:
        score += 3
    if file_name.lower().endswith((".env", ".yml", ".yaml", ".json", ".properties", ".ini")):
        score += 3
    if _looks_like_placeholder(value, line):
        score -= 28
    confidence = max(35, min(99, score + (8 if len(value) >= 20 else 0)))
    return max(8, min(100, score)), confidence


def _add_finding(findings: list[Finding], rule: Rule, file_name: str, line_number: int, line: str, match: re.Match[str], scan_index: int) -> None:
    groups = match.groups()
    value = next((item for item in groups if item), match.group(0))
    score, confidence = _score(rule, value, line, file_name)
    start, end = match.span()
    masked_line = line[:start] + _mask(value, rule.category) + line[end:]
    finding = Finding(
        id=f"F-{scan_index:04d}",
        file_name=file_name,
        line_number=line_number,
        column=start + 1,
        code_line=line.rstrip("\r\n"),
        category=rule.category,
        rule_name=rule.name,
        severity=_level(score),
        score=score,
        confidence=confidence,
        evidence=f"命中 {rule.name} 特征，结合上下文得到风险分 {score}/100。",
        recommendation=rule.recommendation,
        example_code=rule.example_code,
        masked_line=masked_line.rstrip("\r\n"),
        start=start,
        end=end,
    )
    findings.append(finding)


def _scan_high_entropy(findings: list[Finding], file_name: str, line_number: int, line: str, scan_index: int) -> None:
    literal_pattern = re.compile(r"[\"']([A-Za-z0-9_\-/+=]{20,})[\"']")
    for match in literal_pattern.finditer(line):
        value = match.group(1)
        if _looks_like_placeholder(value, line) or _entropy(value) < 3.2:
            continue
        if value.startswith(("http://", "https://")):
            continue
        rule = Rule(
            "high-entropy-literal", "疑似高熵凭据", "高熵字符串", 54,
            literal_pattern,
            "确认这段字符串是否为凭据。若是，请改用环境变量或密钥管理服务；若只是测试数据，请标注为非敏感样例或加入项目白名单。",
            'secret_value = os.getenv("SERVICE_SECRET")',
        )
        _add_finding(findings, rule, file_name, line_number, line, match, scan_index + len(findings))


def scan_files(files: Iterable[tuple[str, str]], scan_id: str, source_name: str = "") -> ScanResult:
    findings: list[Finding] = []
    file_records: list[dict] = []
    for file_name, text in files:
        if not is_supported_file(file_name):
            continue
        lines = text.splitlines() or [""]
        file_records.append({"name": file_name, "line_count": len(lines), "size": len(text.encode("utf-8", "ignore"))})
        for line_number, line in enumerate(lines, start=1):
            for rule in RULES:
                for match in rule.regex.finditer(line):
                    _add_finding(findings, rule, file_name, line_number, line, match, len(findings) + 1)
            _scan_high_entropy(findings, file_name, line_number, line, len(findings) + 1)
    # De-duplicate same line/category overlaps while preserving the most severe signal.
    unique: dict[tuple[str, int, str], Finding] = {}
    for finding in findings:
        key = (finding.file_name, finding.line_number, finding.category)
        old = unique.get(key)
        if old is None or finding.score > old.score:
            unique[key] = finding
    final_findings = list(unique.values())
    for index, finding in enumerate(final_findings, start=1):
        finding.id = f"F-{index:04d}"
    return ScanResult(scan_id=scan_id, files=file_records, findings=final_findings, source_name=source_name)


def serialise_result(result: ScanResult) -> dict:
    return {
        "scan_id": result.scan_id,
        "source_name": result.source_name,
        "files": result.files,
        "findings": [finding.to_dict() for finding in result.findings],
        "dependencies": result.dependencies,
        "git_evidence": result.git_evidence,
        "summary": result.summary(),
    }


def deserialise_result(payload: dict) -> ScanResult:
    result = ScanResult(
        scan_id=payload["scan_id"],
        files=payload.get("files", []),
        source_name=payload.get("source_name", ""),
        dependencies=payload.get("dependencies", {}),
        git_evidence=payload.get("git_evidence", {}),
    )
    result.findings = [Finding(**item) for item in payload.get("findings", [])]
    return result

