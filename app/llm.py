"""DeepSeek integration with temporary redaction and a deterministic fallback."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .scanner import Finding, ScanResult

try:
    from dotenv import dotenv_values
except ImportError:
    # The app still works with process-level environment variables when the
    # optional convenience package is unavailable.
    dotenv_values = None


def _config() -> dict:
    file_values = {}
    if dotenv_values is not None:
        env_path = Path(__file__).resolve().parents[1] / ".env"
        if env_path.exists():
            file_values = dotenv_values(env_path)

    def value(name: str, default: str = "") -> str:
        return (os.getenv(name) or file_values.get(name) or default).strip()

    return {
        "api_key": value("DEEPSEEK_API_KEY"),
        "base_url": value("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        "model": value("DEEPSEEK_MODEL", "deepseek-chat") or "deepseek-chat",
    }


def provider_status() -> dict:
    cfg = _config()
    return {"configured": bool(cfg["api_key"]), "model": cfg["model"], "base_url": cfg["base_url"]}


def _fallback(finding: Finding) -> dict:
    return {
        "source": "内置建议",
        "title": f"{finding.category}修复建议",
        "advice": finding.recommendation,
        "example": finding.example_code,
        "privacy_note": "本次未调用 DeepSeek，原始源码没有离开本机。",
    }


def _masked_context(finding: Finding) -> str:
    return (
        f"文件：{finding.file_name}\n"
        f"行号：{finding.line_number}\n"
        f"风险类型：{finding.category}\n"
        f"代码（敏感值已临时脱敏）：{finding.masked_line}\n"
    )


def _post_chat(cfg: dict, payload: dict) -> dict:
    """POST to DeepSeek, using Windows curl when Python TLS is unreliable."""

    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    curl_path = shutil.which("curl.exe") or shutil.which("curl")
    if os.name == "nt" and curl_path:
        payload_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as payload_file:
                payload_file.write(encoded)
                payload_path = payload_file.name.replace("\\", "/")
            parsed_url = urlparse(cfg["base_url"])
            host = parsed_url.hostname or "api.deepseek.com"
            port = parsed_url.port or 443
            try:
                addresses = list(dict.fromkeys(
                    item[4][0]
                    for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                    if ":" not in item[4][0]
                ))
            except OSError:
                addresses = []
            attempts = [None] + addresses[:6]
            last_detail = "未知网络错误"
            for address in attempts:
                config = (
                    f'url = "{cfg["base_url"]}/chat/completions"\n'
                    'request = "POST"\n'
                    f'header = "Authorization: Bearer {cfg["api_key"]}"\n'
                    'header = "Content-Type: application/json"\n'
                    f'data-binary = "@{payload_path}"\n'
                )
                curl_args = [curl_path, "--silent", "--show-error", "--fail-with-body", "--connect-timeout", "8", "--max-time", "20"]
                if address:
                    curl_args.extend(["--resolve", f"{host}:{port}:{address}"])
                curl_args.extend(["--config", "-"])
                completed = subprocess.run(
                    curl_args,
                    input=config,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=25,
                    check=False,
                )
                if completed.returncode == 0:
                    return json.loads(completed.stdout)
                body = (completed.stdout or "").strip()
                last_detail = (completed.stderr or body or "未知网络错误").strip()[:180]
                # An HTTP response means the address is reachable. Do not
                # retry an authentication, quota, or model error on other IPs.
                if body.startswith("{") or body.startswith("["):
                    break
            raise RuntimeError(f"curl 请求失败：{last_detail}")
        finally:
            if payload_path:
                try:
                    os.unlink(payload_path)
                except OSError:
                    pass

    request = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=encoded,
        headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def ask_deepseek(finding: Finding) -> dict:
    cfg = _config()
    if not cfg["api_key"]:
        return _fallback(finding)
    prompt = (
        "你是一名面向大学生的代码安全教师。请根据下面已经由本地扫描器识别的风险，输出简洁的中文修复建议。"
        "不要要求用户把真实密钥发给你，不要声称已经修改源码。只返回 JSON，字段为 advice 和 example。\n\n"
        + _masked_context(finding)
    )
    try:
        body = _post_chat(cfg, {
            "model": cfg["model"],
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": "你提供教育性代码安全建议，不能执行或修改用户代码。"},
                {"role": "user", "content": prompt},
            ],
        })
        content = body["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.strip("`").replace("json", "", 1).strip()
        parsed = json.loads(content)
        return {
            "source": "DeepSeek",
            "title": f"{finding.category}修复建议",
            "advice": str(parsed.get("advice") or finding.recommendation),
            "example": str(parsed.get("example") or finding.example_code),
            "privacy_note": "发送给 DeepSeek 的临时上下文已脱敏，原始源码未被修改。",
        }
    except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        fallback = _fallback(finding)
        fallback["privacy_note"] = f"DeepSeek 暂时不可用，已使用内置建议（{type(exc).__name__}）。"
        return fallback


def _local_plan(result: ScanResult) -> dict:
    ordered = sorted(result.findings, key=lambda item: item.score, reverse=True)
    if not ordered:
        advice = "当前没有发现风险线索。建议继续保留扫描记录，并在提交前核查依赖、日志和配置文件。"
    else:
        top = "；".join(f"{item.category}（{item.severity}）" for item in ordered[:4])
        advice = f"先处理高风险和严重风险，再轮换可能暴露的凭据，最后复核误报与测试数据。当前优先项：{top}。"
    return {
        "source": "内置整改计划",
        "title": "项目级整改计划",
        "advice": advice,
        "example": "1. 轮换已暴露凭据\n2. 使用环境变量或密钥管理服务\n3. 重新扫描并将结果标记为已修复\n4. 保留审计报告和复核记录",
        "privacy_note": "本次未调用 DeepSeek，原始源码没有离开本机。",
    }


def ask_deepseek_plan(result: ScanResult) -> dict:
    """Generate one project-level plan from masked findings only."""

    cfg = _config()
    if not cfg["api_key"]:
        return _local_plan(result)
    lines = []
    for finding in sorted(result.findings, key=lambda item: item.score, reverse=True)[:12]:
        lines.append(
            f"- {finding.severity}风险｜{finding.category}｜{finding.file_name}:{finding.line_number}｜{finding.masked_line}"
        )
    context = "\n".join(lines) or "未发现风险线索"
    prompt = (
        "你是一名面向大学生项目团队的代码安全教师。请根据脱敏后的项目风险清单，"
        "输出简洁、可执行的中文项目整改计划。不要要求真实密钥，不要声称已经修改源码。"
        "只返回 JSON，字段为 advice 和 example。advice 写分优先级的整改顺序，example 写 4 条以内的复核清单。\n\n"
        + context
    )
    try:
        body = _post_chat(cfg, {
            "model": cfg["model"],
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": "你提供教育性代码安全整改建议，不能执行或修改用户代码。"},
                {"role": "user", "content": prompt},
            ],
        })
        content = body["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.strip("`").replace("json", "", 1).strip()
        parsed = json.loads(content)
        return {
            "source": "DeepSeek",
            "title": "项目级整改计划",
            "advice": str(parsed.get("advice") or _local_plan(result)["advice"]),
            "example": str(parsed.get("example") or _local_plan(result)["example"]),
            "privacy_note": "发送给 DeepSeek 的内容只有已脱敏的风险摘要，原始源码没有被修改。",
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        fallback = _local_plan(result)
        fallback["privacy_note"] = f"DeepSeek 暂时不可用，已使用内置整改计划（{type(exc).__name__}）。"
        return fallback

