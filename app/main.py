"""Flask web application for CodeGuard."""

from __future__ import annotations

import io
import os
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath

from flask import Flask, jsonify, render_template, request, send_file

from .llm import ask_deepseek, ask_deepseek_plan, provider_status
from .insights import analyze_dependencies, analyze_git_archive, local_git_evidence
from .reports import build_pdf
from .scanner import ScanResult, deserialise_result, scan_files, serialise_result


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
CURRENT: ScanResult | None = None
SCAN_HISTORY: list[dict] = []


def _zip_files(blob: bytes) -> list[tuple[str, str]]:
    if len(blob) > 20 * 1024 * 1024:
        raise ValueError("ZIP 文件不能超过 20 MB")
    files: list[tuple[str, str]] = []
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        if len(entries) > 500:
            raise ValueError("ZIP 文件最多支持 500 个文件")
        for item in entries:
            name = PurePosixPath(item.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts:
                continue
            if item.file_size > 2 * 1024 * 1024:
                continue
            try:
                text = archive.read(item).decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = archive.read(item).decode("gb18030")
                except UnicodeDecodeError:
                    continue
            files.append((str(name), text))
    return files


def _run_scan(files: list[tuple[str, str]], source_name: str, archive_blob: bytes | None = None) -> dict:
    global CURRENT
    CURRENT = scan_files(files, uuid.uuid4().hex[:12], source_name=source_name)
    CURRENT.dependencies = analyze_dependencies(files)
    CURRENT.git_evidence = analyze_git_archive(archive_blob) if archive_blob else {}
    payload = serialise_result(CURRENT)
    payload["created_at"] = datetime.now().isoformat(timespec="seconds")
    SCAN_HISTORY.insert(0, payload)
    del SCAN_HISTORY[12:]
    return payload


def _compare_payloads(left: dict, right: dict) -> dict:
    left_findings = left.get("findings", [])
    right_findings = right.get("findings", [])
    left_keys = {(item.get("file_name"), item.get("category"), item.get("line_number")) for item in left_findings}
    right_keys = {(item.get("file_name"), item.get("category"), item.get("line_number")) for item in right_findings}
    return {
        "from": {"scan_id": left.get("scan_id"), "source_name": left.get("source_name"), "summary": left.get("summary", {})},
        "to": {"scan_id": right.get("scan_id"), "source_name": right.get("source_name"), "summary": right.get("summary", {})},
        "score_delta": right.get("summary", {}).get("score", 0) - left.get("summary", {}).get("score", 0),
        "finding_delta": len(right_findings) - len(left_findings),
        "resolved_count": len(left_keys - right_keys),
        "new_count": len(right_keys - left_keys),
        "same_count": len(left_keys & right_keys),
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    return jsonify({"ok": True, "provider": provider_status(), "scan": serialise_result(CURRENT) if CURRENT else None})


@app.post("/api/scan/text")
def scan_text():
    payload = request.get_json(silent=True) or {}
    file_name = (payload.get("file_name") or "pasted_code.py").strip() or "pasted_code.py"
    content = payload.get("content") or ""
    if not content.strip():
        return jsonify({"error": "请先粘贴代码"}), 400
    return jsonify(_run_scan([(file_name, content)], "文本粘贴"))


@app.post("/api/scan/zip")
def scan_zip():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "请选择 ZIP 文件"}), 400
    if not upload.filename.lower().endswith(".zip"):
        return jsonify({"error": "只支持 ZIP 压缩包"}), 400
    blob = upload.read()
    try:
        files = _zip_files(blob)
    except (ValueError, zipfile.BadZipFile) as exc:
        return jsonify({"error": str(exc)}), 400
    if not files:
        return jsonify({"error": "ZIP 中没有可扫描的文本代码文件"}), 400
    return jsonify(_run_scan(files, upload.filename, archive_blob=blob))


@app.get("/api/history")
def history():
    return jsonify([
        {
            "scan_id": item.get("scan_id"),
            "source_name": item.get("source_name"),
            "created_at": item.get("created_at"),
            "summary": item.get("summary", {}),
        }
        for item in SCAN_HISTORY
    ])


@app.get("/api/history/compare")
def history_compare():
    left_id = request.args.get("from", "")
    right_id = request.args.get("to", "")
    left = next((item for item in SCAN_HISTORY if item.get("scan_id") == left_id), None)
    right = next((item for item in SCAN_HISTORY if item.get("scan_id") == right_id), None)
    if not left or not right:
        return jsonify({"error": "找不到需要对比的扫描记录"}), 404
    return jsonify(_compare_payloads(left, right))


@app.get("/api/project/evidence")
def project_evidence():
    project_root = Path(__file__).resolve().parents[1]
    return jsonify(local_git_evidence(project_root))


@app.post("/api/findings/<finding_id>/status")
def update_status(finding_id: str):
    if CURRENT is None:
        return jsonify({"error": "当前没有扫描结果"}), 404
    payload = request.get_json(silent=True) or {}
    status_value = payload.get("status")
    allowed = {"待确认", "已确认", "误报", "已修复", "忽略本次"}
    if status_value not in allowed:
        return jsonify({"error": "无效状态"}), 400
    for finding in CURRENT.findings:
        if finding.id == finding_id:
            finding.status = status_value
            return jsonify(serialise_result(CURRENT))
    return jsonify({"error": "未找到问题"}), 404


@app.post("/api/findings/<finding_id>/advice")
def advice(finding_id: str):
    if CURRENT is None:
        return jsonify({"error": "当前没有扫描结果"}), 404
    for finding in CURRENT.findings:
        if finding.id == finding_id:
            return jsonify(ask_deepseek(finding))
    return jsonify({"error": "未找到问题"}), 404


@app.post("/api/project/remediation-plan")
def remediation_plan():
    if CURRENT is None:
        return jsonify({"error": "请先完成一次扫描"}), 404
    return jsonify(ask_deepseek_plan(CURRENT))


@app.get("/api/report.pdf")
def report_pdf():
    if CURRENT is None:
        return jsonify({"error": "请先完成一次扫描"}), 404
    data = build_pdf(CURRENT)
    return send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=True, download_name="代码安全审计报告.pdf")


if __name__ == "__main__":
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")), debug=True)

