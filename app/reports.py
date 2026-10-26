"""PDF audit report generation."""

from __future__ import annotations

import io
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

from .scanner import ScanResult


def _escape(value: str) -> str:
    return (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_pdf(result: ScanResult) -> bytes:
    font_name = "STSong-Light"
    # Prefer a real system CJK font so Latin identifiers in code examples keep
    # their normal spacing. Fall back to ReportLab's built-in CID font on other
    # machines.
    for candidate in (
        r"C:\Windows\Fonts\Noto Sans SC (TrueType).otf",
        r"C:\Windows\Fonts\simhei.ttf",
    ):
        if os.path.exists(candidate):
            try:
                pdfmetrics.registerFont(TTFont("CodeGuardCN", candidate))
                font_name = "CodeGuardCN"
                break
            except Exception:
                continue
    if font_name == "STSong-Light":
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="智安工坊代码安全审计报告", author="智安工坊（CodeGuard）",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CNTitle", parent=styles["Title"], fontName=font_name, fontSize=22, leading=30, alignment=TA_CENTER, textColor=colors.HexColor("#123B61"), spaceAfter=14))
    styles.add(ParagraphStyle(name="CNHeading", parent=styles["Heading2"], fontName=font_name, fontSize=14, leading=20, textColor=colors.HexColor("#123B61"), spaceBefore=8, spaceAfter=6))
    styles.add(ParagraphStyle(name="CNBody", parent=styles["BodyText"], fontName=font_name, fontSize=9.5, leading=15, alignment=TA_LEFT, spaceAfter=5))
    styles.add(ParagraphStyle(name="CNSmall", parent=styles["BodyText"], fontName=font_name, fontSize=8, leading=12, textColor=colors.HexColor("#4E5B66")))
    story = []
    summary = result.summary()
    story.append(Paragraph("代码安全审计报告", styles["CNTitle"]))
    story.append(Paragraph("敏感信息泄露风险检测与修复建议", styles["CNBody"]))
    story.append(Spacer(1, 5 * mm))
    metadata = [
        [Paragraph("扫描来源", styles["CNBody"]), Paragraph(_escape(result.source_name or "代码片段"), styles["CNBody"])],
        [Paragraph("扫描时间", styles["CNBody"]), Paragraph(datetime.now().strftime("%Y-%m-%d %H:%M"), styles["CNBody"])],
        [Paragraph("文件数量", styles["CNBody"]), Paragraph(str(summary["files"]), styles["CNBody"])],
        [Paragraph("代码行数", styles["CNBody"]), Paragraph(str(summary["lines"]), styles["CNBody"])],
        [Paragraph("安全评分", styles["CNBody"]), Paragraph(f"{summary['score']} / 100", styles["CNBody"])],
        [Paragraph("依赖清单", styles["CNBody"]), Paragraph(str(summary.get("dependencies", 0)), styles["CNBody"])],
        [Paragraph("Git 提交证据", styles["CNBody"]), Paragraph(str(summary.get("git_commits", 0)), styles["CNBody"])],
    ]
    table = Table(metadata, colWidths=[32 * mm, 125 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF2F8")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D3DD")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("一 风险概览", styles["CNHeading"]))
    level_data = [[Paragraph("等级", styles["CNBody"]), Paragraph("严重", styles["CNBody"]), Paragraph("高", styles["CNBody"]), Paragraph("中", styles["CNBody"]), Paragraph("低", styles["CNBody"]), Paragraph("合计", styles["CNBody"])],
                  [Paragraph("数量", styles["CNBody"]), Paragraph(str(summary["levels"]["严重"]), styles["CNBody"]), Paragraph(str(summary["levels"]["高"]), styles["CNBody"]), Paragraph(str(summary["levels"]["中"]), styles["CNBody"]), Paragraph(str(summary["levels"]["低"]), styles["CNBody"]), Paragraph(str(summary["findings"]), styles["CNBody"])]]
    level_table = Table(level_data, colWidths=[28 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm])
    level_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123B61")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D3DD")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(level_table)
    story.append(Paragraph("风险等级由规则信号、代码上下文、文件类型和疑似凭据特征综合计算。检测结果需要人工确认，不能替代正式安全评估。", styles["CNSmall"]))
    story.append(Paragraph("二 检测结果", styles["CNHeading"]))
    if not result.findings:
        story.append(Paragraph("本次扫描未发现符合当前检测策略的敏感信息泄露风险。建议继续使用人工复核和密钥轮换流程。", styles["CNBody"]))
    for index, finding in enumerate(result.findings, start=1):
        story.append(Paragraph(f"{index}. {finding.severity}风险  {finding.category}  {finding.file_name}:{finding.line_number}", styles["CNBody"]))
        story.append(Paragraph(f"风险说明：{_escape(finding.evidence)}", styles["CNBody"]))
        story.append(Paragraph(f"代码行：{_escape(finding.masked_line)}", styles["CNSmall"]))
        story.append(Paragraph(f"修复建议：{_escape(finding.recommendation)}", styles["CNBody"]))
        story.append(Paragraph(f"示例：<br/>{_escape(finding.example_code).replace(chr(10), '<br/>')}", styles["CNSmall"]))
        story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("三 项目洞察", styles["CNHeading"]))
    dependency = result.dependencies or {}
    story.append(Paragraph(
        f"依赖清单：{dependency.get('dependency_count', 0)} 项；版本范围较宽：{dependency.get('unpinned_count', 0)} 项。"
        "该检查用于建立可复核的依赖清单，不替代专业漏洞数据库。",
        styles["CNBody"],
    ))
    git_info = result.git_evidence or {}
    if git_info.get("included"):
        story.append(Paragraph(
            f"上传包包含 Git 历史，共读取 {git_info.get('commit_count', 0)} 次提交，"
            f"涉及 {git_info.get('author_count', 0)} 位作者。",
            styles["CNBody"],
        ))
    else:
        story.append(Paragraph("本次上传未包含 .git 历史，无法从压缩包核验开发过程；请保留项目仓库作为原创性证据。", styles["CNBody"]))
    story.append(PageBreak())
    story.append(Paragraph("四 整改记录", styles["CNHeading"]))
    story.append(Paragraph("系统支持将问题标记为已确认、误报、已修复或忽略本次。正式提交报告前，请由项目成员完成人工复核，并在源代码仓库中完成密钥轮换。", styles["CNBody"]))
    rows = [[Paragraph("编号", styles["CNBody"]), Paragraph("文件与行号", styles["CNBody"]), Paragraph("风险类型", styles["CNBody"]), Paragraph("当前状态", styles["CNBody"])]]
    for finding in result.findings:
        rows.append([Paragraph(finding.id, styles["CNSmall"]), Paragraph(f"{_escape(finding.file_name)}:{finding.line_number}", styles["CNSmall"]), Paragraph(_escape(finding.category), styles["CNSmall"]), Paragraph(_escape(finding.status), styles["CNSmall"])])
    table = Table(rows, colWidths=[22 * mm, 55 * mm, 45 * mm, 35 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123B61")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D3DD")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("五 使用说明", styles["CNHeading"]))
    story.append(Paragraph("本报告由智安工坊（CodeGuard）代码安全审计平台生成。平台只提供风险发现和教育性修复建议，不会自动修改用户源代码。建议将本报告与代码整改记录一并归档。", styles["CNBody"]))
    doc.build(story)
    return buffer.getvalue()

