"""
GitIntel PDF Report Service
使用 reportlab 将分析结果渲染为 PDF（纯 Python，无系统依赖）
"""

import io
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepInFrame,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import HRFlowable


# ── 颜色常量 ────────────────────────────────────────────────────

PURPLE   = colors.HexColor("#4f46e5")
CYAN     = colors.HexColor("#0891b2")
RED      = colors.HexColor("#dc2626")
GREEN    = colors.HexColor("#059669")
YELLOW   = colors.HexColor("#d97706")
PURPLE2  = colors.HexColor("#7c3aed")
DARK_BG  = colors.HexColor("#0f172a")
LIGHT_BG = colors.HexColor("#f8fafc")
BORDER   = colors.HexColor("#e2e8f0")
TEXT     = colors.HexColor("#1e293b")
MUTED    = colors.HexColor("#64748b")
WHITE    = colors.white


# ── 样式 ─────────────────────────────────────────────────────────

def _make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    s = {}

    s["logo"] = ParagraphStyle("logo", fontSize=22, textColor=PURPLE,
                                fontName="Helvetica-Bold", alignment=1, spaceAfter=4)
    s["cover_title"] = ParagraphStyle("cover_title", fontSize=16, textColor=TEXT,
                                      fontName="Helvetica-Bold", alignment=1, spaceAfter=6)
    s["cover_meta"] = ParagraphStyle("cover_meta", fontSize=9, textColor=MUTED,
                                     alignment=1, spaceAfter=3)
    s["cover_url"] = ParagraphStyle("cover_url", fontSize=9, textColor=PURPLE,
                                    alignment=1, spaceAfter=3)

    s["sec_title_p"]  = ParagraphStyle("sec_title_p",  fontSize=13, textColor=WHITE,
                                       fontName="Helvetica-Bold", spaceAfter=2)
    s["sec_title_c"]  = ParagraphStyle("sec_title_c",  fontSize=13, textColor=WHITE,
                                       fontName="Helvetica-Bold", spaceAfter=2)
    s["sec_title_r"]  = ParagraphStyle("sec_title_r",  fontSize=13, textColor=WHITE,
                                       fontName="Helvetica-Bold", spaceAfter=2)
    s["sec_title_u"]  = ParagraphStyle("sec_title_u",  fontSize=13, textColor=WHITE,
                                       fontName="Helvetica-Bold", spaceAfter=2)

    s["kpi_label"] = ParagraphStyle("kpi_label", fontSize=7, textColor=MUTED,
                                    fontName="Helvetica", alignment=1)
    s["kpi_value"] = ParagraphStyle("kpi_value", fontSize=15, textColor=TEXT,
                                    fontName="Helvetica-Bold", alignment=1)
    s["kpi_val_h"] = ParagraphStyle("kpi_val_h", fontSize=15, textColor=RED,
                                     fontName="Helvetica-Bold", alignment=1)
    s["kpi_val_m"] = ParagraphStyle("kpi_val_m", fontSize=15, textColor=YELLOW,
                                     fontName="Helvetica-Bold", alignment=1)
    s["kpi_val_l"] = ParagraphStyle("kpi_val_l", fontSize=15, textColor=GREEN,
                                     fontName="Helvetica-Bold", alignment=1)

    s["tag"] = ParagraphStyle("tag", fontSize=8, textColor=PURPLE,
                              fontName="Helvetica", spaceAfter=0)

    s["item_title_h"] = ParagraphStyle("item_title_h", fontSize=10, textColor=RED,
                                        fontName="Helvetica-Bold", spaceAfter=1)
    s["item_title_m"] = ParagraphStyle("item_title_m", fontSize=10, textColor=YELLOW,
                                        fontName="Helvetica-Bold", spaceAfter=1)
    s["item_title_l"] = ParagraphStyle("item_title_l", fontSize=10, textColor=GREEN,
                                        fontName="Helvetica-Bold", spaceAfter=1)
    s["item_title"]   = ParagraphStyle("item_title",   fontSize=10, textColor=TEXT,
                                        fontName="Helvetica-Bold", spaceAfter=1)
    s["item_desc"] = ParagraphStyle("item_desc", fontSize=9, textColor=MUTED, spaceAfter=2)
    s["badge_h"] = ParagraphStyle("badge_h", fontSize=7, textColor=RED,
                                   fontName="Helvetica-Bold", alignment=1)
    s["badge_m"] = ParagraphStyle("badge_m", fontSize=7, textColor=YELLOW,
                                   fontName="Helvetica-Bold", alignment=1)
    s["badge_l"] = ParagraphStyle("badge_l", fontSize=7, textColor=GREEN,
                                   fontName="Helvetica-Bold", alignment=1)

    s["summary"] = ParagraphStyle("summary", fontSize=9, textColor=colors.HexColor("#4c1d95"),
                                  fontName="Helvetica", leading=14, spaceAfter=4)

    s["footer"] = ParagraphStyle("footer", fontSize=8, textColor=MUTED,
                                  alignment=1)

    s["hotspot"] = ParagraphStyle("hotspot", fontSize=9, textColor=RED, spaceAfter=2)
    s["insight"] = ParagraphStyle("insight", fontSize=9, textColor=TEXT,
                                  fontName="Helvetica", leading=13)
    # 长名别名（兼容 .lower() 后的 lookup）
    s["kpi_val_high"]   = s["kpi_val_h"]
    s["kpi_val_medium"] = s["kpi_val_m"]
    s["kpi_val_low"]    = s["kpi_val_l"]
    return s


# ── 封面 ─────────────────────────────────────────────────────────

def _build_cover(data: dict[str, Any], styles: dict[str, ParagraphStyle]) -> list:
    repo_url = data.get("repo_url", "Unknown")
    branch   = data.get("branch", "main")
    ts       = datetime.now().strftime("%Y-%m-%d %H:%M")
    story: list = []

    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph("⚡ GitIntel", styles["logo"]))
    story.append(Paragraph("仓库智能分析报告", styles["cover_title"]))
    story.append(HRFlowable(width="100%", thickness=2, color=PURPLE, spaceAfter=6))
    story.append(Paragraph(f"分支 · {branch}  &nbsp;|&nbsp;  生成时间 · {ts}", styles["cover_meta"]))
    story.append(Paragraph(repo_url, styles["cover_url"]))
    story.append(Spacer(1, 8 * mm))
    story.append(NextPageTemplate("normal"))
    return story


# ── 工具函数 ─────────────────────────────────────────────────────

def _kpi_table(rows: list[list[Any]], col_widths: list[float]) -> Table:
    """N行 x N列 KPI 表格，自动行高"""
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), LIGHT_BG),
        ("BOX",         (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",   (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING",  (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _section_header(title: str, bg: colors.Color) -> Table:
    t = Table([[Paragraph(title, ParagraphStyle("h", fontSize=13, textColor=WHITE,
                                                fontName="Helvetica-Bold", leading=16))]],
              colWidths=[172 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("TOPPADDING",   (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    return t


def _section_body(elements: list) -> Table:
    kif = KeepInFrame(172 * mm, 200 * mm, elements, mode="shrink")
    t = Table([[kif]], colWidths=[172 * mm])
    t.setStyle(TableStyle([
        ("BOX",          (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _spacer(h: float = 4) -> Spacer:
    return Spacer(1, h)


def _item_row(title: str, desc: str, level: str) -> Table:
    styles = _make_styles()
    badge_text = level.upper()
    badge_style = {
        "h": styles["badge_h"],
        "high": styles["badge_h"],
        "medium": styles["badge_m"],
        "m": styles["badge_m"],
        "low": styles["badge_l"],
        "l": styles["badge_l"],
    }.get(level.lower(), styles["badge_h"])

    title_style = {
        "h": styles["item_title_h"],
        "high": styles["item_title_h"],
        "medium": styles["item_title_m"],
        "m": styles["item_title_m"],
        "low": styles["item_title_l"],
        "l": styles["item_title_l"],
    }.get(level.lower(), styles["item_title"])

    bg = {
        "h": colors.HexColor("#fef2f2"),
        "high": colors.HexColor("#fef2f2"),
        "medium": colors.HexColor("#fffbeb"),
        "m": colors.HexColor("#fffbeb"),
        "low": colors.HexColor("#f0fdf4"),
        "l": colors.HexColor("#f0fdf4"),
    }.get(level.lower(), WHITE)

    border_color = {
        "h": RED,
        "high": RED,
        "medium": YELLOW,
        "m": YELLOW,
        "low": GREEN,
        "l": GREEN,
    }.get(level.lower(), BORDER)

    row = [[
        Paragraph(f"{title} <b>[{badge_text}]</b>", title_style),
        Paragraph(desc, styles["item_desc"]),
    ]]
    t = Table(row, colWidths=[75 * mm, 92 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("LINEBEFORE",   (0, 0), (0, -1), 4, border_color),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
    ]))
    return t


# ── 各模块渲染 ──────────────────────────────────────────────────

def _render_architecture(arch: dict[str, Any]) -> list:
    if not arch:
        return []
    styles = _make_styles()
    elements: list = []

    # 4 列 KPI：标签行 + 值行
    complexity_key = f"kpi_val_{arch.get('complexity', '').lower()}"
    kpi_data = [
        [
            Paragraph("复杂度",      styles["kpi_label"]),
            Paragraph("组件数",      styles["kpi_label"]),
            Paragraph("可维护性",    styles["kpi_label"]),
            Paragraph("架构风格",    styles["kpi_label"]),
        ],
        [
            Paragraph(arch.get("complexity", "—"),        styles.get(complexity_key, styles["kpi_value"])),
            Paragraph(str(arch.get("components", "—")),    styles["kpi_value"]),
            Paragraph(str(arch.get("maintainability", "—")), styles["kpi_value"]),
            Paragraph(str(arch.get("architectureStyle", "—")), styles["kpi_value"]),
        ],
    ]
    elements.append(_kpi_table(kpi_data, [43 * mm] * 4))
    elements.append(_spacer(6))

    # 技术栈标签
    tech = arch.get("techStack") or []
    if tech:
        tags = " ".join(f"· {t}" for t in tech[:8])
        elements.append(Paragraph(f"<b>技术栈</b>  {tags}", styles["insight"]))
        elements.append(_spacer(4))

    # 设计模式
    patterns = arch.get("keyPatterns") or []
    if patterns:
        elements.append(Paragraph("<b>设计模式</b>  " + "  ".join(f"· {p}" for p in patterns[:4]),
                                  styles["insight"]))
        elements.append(_spacer(4))

    # 热点
    hotspots = arch.get("hotSpots") or []
    if hotspots:
        for h in hotspots[:4]:
            elements.append(Paragraph(f"⚠  {h}", styles["hotspot"]))

    # 摘要
    summary = arch.get("summary", "")
    if summary:
        elements.append(_spacer(4))
        elements.append(Paragraph(summary, styles["summary"]))

    header = _section_header("🏗  架构分析", PURPLE)
    body = _section_body(elements)
    return [header, body, _spacer(8)]


def _render_quality(quality: dict[str, Any]) -> list:
    if not quality:
        return []
    styles = _make_styles()
    elements: list = []

    score  = str(quality.get("health_score", "—"))
    grade  = quality.get("grade", "")
    issues = quality.get("issues") or []

    grade_cls = {"A": "l", "B": "l", "C": "m", "D": "m", "F": "h"}.get(grade, "m")
    kpi_data = [
        [Paragraph("综合评分", styles["kpi_label"]),
         Paragraph("评级", styles["kpi_label"])],
        [Paragraph(score, styles["kpi_value"]),
         Paragraph(grade, styles[f"kpi_val_{grade_cls}"])],
    ]
    elements.append(_kpi_table(kpi_data, [86 * mm] * 2))
    elements.append(_spacer(6))

    for iss in issues[:8]:
        level = iss.get("severity", "m")
        title = iss.get("title", "未知问题")
        desc  = iss.get("description", "")
        elements.append(_item_row(title, desc, level))
        elements.append(_spacer(3))

    header = _section_header("🔍  代码质量", CYAN)
    body   = _section_body(elements)
    return [header, body, _spacer(8)]


def _render_dependency(dep: dict[str, Any]) -> list:
    if not dep:
        return []
    styles = _make_styles()
    elements: list = []

    total  = dep.get("total", 0)
    high   = dep.get("high", 0)
    medium = dep.get("medium", 0)
    low    = dep.get("low", 0)
    summary = dep.get("summary") or []

    risk = "h" if high > 0 else "m" if medium > 0 else "l"
    kpi_data = [
        [Paragraph("总依赖", styles["kpi_label"]),
         Paragraph("高危", styles["kpi_label"]),
         Paragraph("中危", styles["kpi_label"]),
         Paragraph("低危", styles["kpi_label"])],
        [Paragraph(str(total), styles["kpi_value"]),
         Paragraph(str(high), styles["kpi_val_h"]),
         Paragraph(str(medium), styles["kpi_val_m"]),
         Paragraph(str(low), styles["kpi_val_l"])],
    ]
    elements.append(_kpi_table(kpi_data, [43 * mm] * 4))
    elements.append(_spacer(6))

    if summary:
        elements.append(Paragraph("<br>".join(f"• {s}" for s in summary[:5]), styles["summary"]))

    risk_label = {"h": "高风险", "m": "中风险", "l": "低风险"}.get(risk, "")
    header = _section_header(f"📦  依赖分析  ·  {risk_label}", RED)
    body   = _section_body(elements)
    return [header, body, _spacer(8)]


def _render_optimization(opt: dict[str, Any]) -> list:
    if not opt:
        return []
    styles = _make_styles()
    elements: list = []

    high_p   = opt.get("high_priority", 0)
    medium_p = opt.get("medium_priority", 0)
    low_p    = opt.get("low_priority", 0)
    suggestions = opt.get("suggestions") or []

    kpi_data = [
        [Paragraph("高优先级", styles["kpi_label"]),
         Paragraph("中优先级", styles["kpi_label"]),
         Paragraph("低优先级", styles["kpi_label"])],
        [Paragraph(str(high_p), styles["kpi_val_h"]),
         Paragraph(str(medium_p), styles["kpi_val_m"]),
         Paragraph(str(low_p), styles["kpi_val_l"])],
    ]
    elements.append(_kpi_table(kpi_data, [57 * mm] * 3))
    elements.append(_spacer(6))

    for s in suggestions[:8]:
        priority = s.get("priority", "m")
        title = s.get("title", "建议")
        desc  = s.get("description", "")
        stype = s.get("type", "优化")
        elements.append(_item_row(f"[{stype}] {title}", desc, priority))
        elements.append(_spacer(3))

    header = _section_header("⚡  优化建议", PURPLE2)
    body   = _section_body(elements)
    return [header, body, _spacer(8)]


# ── 主构建函数 ───────────────────────────────────────────────────

def build_pdf_bytes(data: dict[str, Any]) -> bytes:
    """
    将分析结果字典转为 PDF 字节流。
    data 格式：
      {
        "repo_url": "...",
        "branch": "main",
        "architecture": { ... },
        "quality": { ... },
        "dependency": { ... },
        "optimization": { ... },
      }
    """
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    normal_frame = Frame(0, 0, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="normal", frames=[normal_frame])])

    styles = _make_styles()
    story: list = []

    # 封面
    story.extend(_build_cover(data, styles))

    # 四个模块
    story.extend(_render_architecture(data.get("architecture", {})))
    story.extend(_render_quality(data.get("quality", {})))
    story.extend(_render_dependency(data.get("dependency", {})))
    story.extend(_render_optimization(data.get("optimization", {})))

    # 页脚
    story.append(_spacer(6))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    story.append(_spacer(3))
    story.append(Paragraph(
        "由 GitIntel AI 分析引擎生成  ·  仅供参考，请以实际代码为准",
        styles["footer"],
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()
