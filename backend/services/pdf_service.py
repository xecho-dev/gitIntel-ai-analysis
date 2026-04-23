"""
GitIntel PDF Report Service
使用 reportlab 将分析结果渲染为 PDF（纯 Python，无系统依赖）
支持通义千问 AI 生图美化

中文：标签与段落使用 STSong-Light（Adobe-GB1 CID）。KPI 中的纯英文/数字使用「整段
Helvetica-Bold」独立样式，禁止嵌在 STSong 的 mini-HTML 里，否则字宽按中文字体计算
会导致字母挤在一起。勿用 &nbsp; 等实体，在 CID 字体下可能被画成错误符号。
"""

import io
import os
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.fonts import addMapping
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

# AI 生图服务（可选，同步版本）
try:
    from .image_generation import (
        get_cached_image_sync,
        _get_prompt_for_cover,
        _get_prompt_for_architecture,
        _get_prompt_for_quality,
        _get_prompt_for_dependency,
        _get_prompt_for_optimization,
    )
    AI_IMAGE_AVAILABLE = True
except ImportError:
    AI_IMAGE_AVAILABLE = False


# ── 颜色与排版常量（低饱和、统一在 slate / indigo 系）────────────────

ACCENT_ARCH    = colors.HexColor("#4f46e5")
ACCENT_QUALITY = colors.HexColor("#0d9488")
ACCENT_DEP     = colors.HexColor("#e11d48")
ACCENT_OPT     = colors.HexColor("#7c3aed")
BRAND          = colors.HexColor("#4f46e5")

WHITE       = colors.white
PAGE_BG     = colors.HexColor("#ffffff")
SECTION_BG  = colors.HexColor("#fafafa")
HEADER_ROW  = colors.HexColor("#f1f5f9")
BORDER      = colors.HexColor("#e2e8f0")
BORDER_STR  = colors.HexColor("#cbd5e1")
TEXT        = colors.HexColor("#0f172a")
TEXT_SEC    = colors.HexColor("#334155")
MUTED       = colors.HexColor("#64748b")

RISK_H = colors.HexColor("#be123c")
RISK_M = colors.HexColor("#b45309")
RISK_L = colors.HexColor("#047857")

# Paragraph <font color="#..."> 用字符串（Helvetica 片段）
HEX_TEXT = "#0f172a"
HEX_MUTED = "#64748b"
HEX_RISK_H = "#be123c"
HEX_RISK_M = "#b45309"
HEX_RISK_L = "#047857"

_PDF_FONT_READY = False
# 英文 KPI 独立 ParagraphStyle（按颜色缓存，避免重复注册同名样式）
_EN_METRIC_STYLE_CACHE: dict[tuple[str, int], ParagraphStyle] = {}
_CN_METRIC_STYLE_CACHE: dict[tuple[str, int], ParagraphStyle] = {}


def _ensure_pdf_cjk_font() -> str:
    """注册 STSong-Light 并配置粗体映射，供 Paragraph / Table 使用。"""
    global _PDF_FONT_READY
    name = "STSong-Light"
    if _PDF_FONT_READY:
        return name
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(name))
        addMapping(name, 0, 0, name)
        addMapping(name, 1, 0, name)
    _PDF_FONT_READY = True
    return name


# ── 样式 ─────────────────────────────────────────────────────────

def _make_styles() -> dict[str, ParagraphStyle]:
    fn = _ensure_pdf_cjk_font()
    s: dict[str, ParagraphStyle] = {}

    s["logo"] = ParagraphStyle("logo", fontSize=24, textColor=BRAND,
                                fontName=fn, alignment=1, spaceAfter=2, leading=28)
    s["cover_title"] = ParagraphStyle("cover_title", fontSize=17, textColor=TEXT,
                                      fontName=fn, alignment=1, spaceAfter=10, leading=22)
    s["cover_meta"] = ParagraphStyle("cover_meta", fontSize=9, textColor=MUTED,
                                     fontName=fn, alignment=1, spaceAfter=4, leading=12)
    s["cover_url"] = ParagraphStyle("cover_url", fontSize=8.5, textColor=BRAND,
                                    fontName=fn, alignment=1, spaceAfter=2, leading=11)

    s["sec_title_bar"] = ParagraphStyle(
        "sec_title_bar",
        fontSize=12,
        textColor=TEXT,
        fontName=fn,
        leading=16,
        spaceAfter=0,
        alignment=TA_CENTER,
    )
    s["sec_title_p"]  = ParagraphStyle("sec_title_p",  fontSize=13, textColor=WHITE,
                                       fontName=fn, spaceAfter=2)
    s["sec_title_c"]  = ParagraphStyle("sec_title_c",  fontSize=13, textColor=WHITE,
                                       fontName=fn, spaceAfter=2)
    s["sec_title_r"]  = ParagraphStyle("sec_title_r",  fontSize=13, textColor=WHITE,
                                       fontName=fn, spaceAfter=2)
    s["sec_title_u"]  = ParagraphStyle("sec_title_u",  fontSize=13, textColor=WHITE,
                                       fontName=fn, spaceAfter=2)

    s["kpi_label"] = ParagraphStyle("kpi_label", fontSize=8, textColor=MUTED,
                                    fontName=fn, alignment=1, leading=11)
    s["kpi_value"] = ParagraphStyle("kpi_value", fontSize=15, textColor=TEXT,
                                    fontName=fn, alignment=1, leading=18)
    s["kpi_val_h"] = ParagraphStyle("kpi_val_h", fontSize=15, textColor=RISK_H,
                                     fontName=fn, alignment=1, leading=18)
    s["kpi_val_m"] = ParagraphStyle("kpi_val_m", fontSize=15, textColor=RISK_M,
                                     fontName=fn, alignment=1, leading=18)
    s["kpi_val_l"] = ParagraphStyle("kpi_val_l", fontSize=15, textColor=RISK_L,
                                     fontName=fn, alignment=1, leading=18)

    s["tag"] = ParagraphStyle("tag", fontSize=8, textColor=BRAND,
                              fontName=fn, spaceAfter=0)

    s["item_title_h"] = ParagraphStyle("item_title_h", fontSize=10, textColor=RISK_H,
                                        fontName=fn, spaceAfter=2, leading=13)
    s["item_title_m"] = ParagraphStyle("item_title_m", fontSize=10, textColor=RISK_M,
                                        fontName=fn, spaceAfter=2, leading=13)
    s["item_title_l"] = ParagraphStyle("item_title_l", fontSize=10, textColor=RISK_L,
                                        fontName=fn, spaceAfter=2, leading=13)
    s["item_title"]   = ParagraphStyle("item_title",   fontSize=10, textColor=TEXT,
                                        fontName=fn, spaceAfter=1)
    s["item_desc"] = ParagraphStyle("item_desc", fontSize=9, textColor=MUTED,
                                    fontName=fn, spaceAfter=2)
    s["badge_h"] = ParagraphStyle("badge_h", fontSize=7, textColor=RISK_H,
                                   fontName=fn, alignment=1)
    s["badge_m"] = ParagraphStyle("badge_m", fontSize=7, textColor=RISK_M,
                                   fontName=fn, alignment=1)
    s["badge_l"] = ParagraphStyle("badge_l", fontSize=7, textColor=RISK_L,
                                   fontName=fn, alignment=1)

    s["summary"] = ParagraphStyle("summary", fontSize=9.5, textColor=TEXT_SEC,
                                  fontName=fn, leading=15, spaceAfter=2, alignment=TA_CENTER)

    s["footer"] = ParagraphStyle("footer", fontSize=7.5, textColor=MUTED,
                                  fontName=fn, alignment=TA_CENTER, leading=11)

    s["hotspot"] = ParagraphStyle("hotspot", fontSize=9, textColor=RISK_H,
                                  fontName=fn, spaceAfter=5, leading=13, alignment=TA_CENTER)
    s["hotspot_en"] = ParagraphStyle(
        "hotspot_en",
        fontName="Helvetica",
        fontSize=9,
        textColor=RISK_H,
        spaceAfter=5,
        leading=13,
        alignment=TA_CENTER,
    )
    s["insight"] = ParagraphStyle("insight", fontSize=9.5, textColor=TEXT_SEC,
                                  fontName=fn, leading=14, alignment=TA_CENTER)
    s["insight_en"] = ParagraphStyle(
        "insight_en",
        fontName="Helvetica",
        fontSize=9.5,
        textColor=TEXT_SEC,
        leading=14,
        alignment=TA_CENTER,
    )
    # 长名别名（兼容 .lower() 后的 lookup）
    s["kpi_val_high"]   = s["kpi_val_h"]
    s["kpi_val_medium"] = s["kpi_val_m"]
    s["kpi_val_low"]    = s["kpi_val_l"]
    return s


def _para_metric_value(val: Any, hex_color: str, align: int = TA_CENTER) -> Paragraph:
    """KPI 数值：纯 ASCII 用整段 Helvetica-Bold；含非 ASCII 则用 STSong。禁止套在 STSong 的 <font> 里。"""
    raw = val if val is not None else ""
    s = str(raw).strip() or "—"
    key_en = (hex_color, align)
    if s.isascii():
        if key_en not in _EN_METRIC_STYLE_CACHE:
            _EN_METRIC_STYLE_CACHE[key_en] = ParagraphStyle(
                f"pdf_en_metric_{len(_EN_METRIC_STYLE_CACHE)}",
                fontName="Helvetica-Bold",
                fontSize=15,
                textColor=colors.HexColor(hex_color),
                alignment=align,
                leading=19,
            )
        return Paragraph(escape(s), _EN_METRIC_STYLE_CACHE[key_en])
    key_cn = (hex_color, align)
    if key_cn not in _CN_METRIC_STYLE_CACHE:
        _CN_METRIC_STYLE_CACHE[key_cn] = ParagraphStyle(
            f"pdf_cn_metric_{len(_CN_METRIC_STYLE_CACHE)}",
            fontName=_ensure_pdf_cjk_font(),
            fontSize=15,
            textColor=colors.HexColor(hex_color),
            alignment=align,
            leading=19,
        )
    return Paragraph(escape(s), _CN_METRIC_STYLE_CACHE[key_cn])


def _hex_for_kpi_style_key(style_key: str) -> str:
    sk = style_key.lower()
    if "val_high" in sk or sk.endswith("_h"):
        return HEX_RISK_H
    if "val_medium" in sk or sk.endswith("_m"):
        return HEX_RISK_M
    if "val_low" in sk or sk.endswith("_l"):
        return HEX_RISK_L
    return HEX_TEXT


def _grade_style_key(grade_display: str) -> str:
    """按评级首字母映射 KPI 颜色档位（支持 A+、B 等）。"""
    g = (grade_display or "").strip()
    if not g:
        return "m"
    letter = g[0].upper()
    return {"A": "l", "B": "l", "C": "m", "D": "m", "F": "h"}.get(letter, "m")


# ── 封面 ─────────────────────────────────────────────────────────

def _build_cover(
    data: dict[str, Any],
    styles: dict[str, ParagraphStyle],
    cover_image: bytes | None = None,
) -> list:
    repo_url = data.get("repo_url", "Unknown")
    branch   = data.get("branch", "main")
    ts       = datetime.now().strftime("%Y-%m-%d %H:%M")
    story: list = []

    # AI 生成封面图
    if cover_image:
        try:
            img_buf = io.BytesIO(cover_image)
            img = Image(img_buf, width=150, height=150)
            logo_table = Table(
                [[img, Paragraph("GitIntel", styles["logo"])]],
                colWidths=[60, 90],
            )
            logo_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (1, 0), (1, 0), 10),
            ]))
            story.append(Spacer(1, 10 * mm))
            story.append(logo_table)
        except Exception:
            story.append(Spacer(1, 14 * mm))
            story.append(Paragraph("GitIntel", styles["logo"]))
    else:
        story.append(Spacer(1, 14 * mm))
        story.append(Paragraph("GitIntel", styles["logo"]))

    story.append(Paragraph("仓库智能分析报告", styles["cover_title"]))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER_STR, spaceAfter=10))
    story.append(Paragraph(
        f"分支 <font color='{HEX_MUTED}'> | </font> {escape(str(branch))}"
        f"    生成时间 <font color='{HEX_MUTED}'> | </font> {escape(ts)}",
        styles["cover_meta"],
    ))
    story.append(Paragraph(escape(str(repo_url)), styles["cover_url"]))
    story.append(Spacer(1, 10 * mm))
    story.append(NextPageTemplate("normal"))
    return story


# ── 工具函数 ─────────────────────────────────────────────────────

def _kpi_table(rows: list[list[Any]], col_widths: list[float]) -> Table:
    """KPI 表：首行标签区与数值区分色，避免「多出一行空白」的错觉。"""
    t = Table(rows, colWidths=col_widths)
    last = len(rows) - 1
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_ROW),
        ("BACKGROUND", (0, 1), (-1, last), WHITE),
        ("BOX", (0, 0), (-1, -1), 0.75, BORDER_STR),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    t.setStyle(TableStyle(ts))
    return t


def _section_header(
    title: str,
    accent: colors.Color,
    styles: dict[str, ParagraphStyle],
    content_w: float,
) -> Table:
    t = Table([[Paragraph(escape(title), styles["sec_title_bar"])]],
              colWidths=[content_w])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HEADER_ROW),
        ("LINEBEFORE", (0, 0), (0, -1), 5, accent),
        ("TOPPADDING", (0, 0), (-1, -1), 13),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
    ]))
    return t


def _section_body(elements: list, content_w: float) -> tuple[list, float]:
    """返回 (元素列表, 容器宽度)。调用方自行用 Table 包裹，避免嵌套导致的边距叠加。"""
    if not elements:
        return ([Spacer(1, 2)], content_w)
    return (elements, content_w)


def _spacer(h: float = 4) -> Spacer:
    return Spacer(1, h)


def _item_row(title: str, desc: str, level: str, content_w: float) -> Table:
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
        "h": RISK_H,
        "high": RISK_H,
        "medium": RISK_M,
        "m": RISK_M,
        "low": RISK_L,
        "l": RISK_L,
    }.get(level.lower(), BORDER_STR)

    row = [[
        Paragraph(f"{escape(title)} <b>[{escape(badge_text)}]</b>", title_style),
        Paragraph(escape(desc), styles["item_desc"]),
    ]]
    w_left = content_w * 0.44
    w_right = content_w - w_left
    t = Table(row, colWidths=[w_left, w_right])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("LINEBEFORE",   (0, 0), (0, -1), 3, border_color),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
    ]))
    return t


# ── 各模块渲染 ──────────────────────────────────────────────────

def _add_ai_image(
    elements: list,
    prompt_fn,
    cache_key: str,
    image_bytes: bytes | None,
    width: float = 200,
) -> list:
    """添加 AI 生成图片到元素列表"""
    if not image_bytes:
        return elements

    try:
        img_buf = io.BytesIO(image_bytes)
        img = Image(img_buf, width=width, height=width)
        elements.insert(0, img)
        elements.insert(1, _spacer(6))
    except Exception:
        pass
    return elements


def _render_architecture(
    arch: dict[str, Any],
    content_w: float,
    ai_image: bytes | None = None,
) -> list:
    if not arch:
        return []
    styles = _make_styles()
    elements: list = []

    # AI 生成章节配图
    elements = _add_ai_image(
        elements, None, None, ai_image, width=content_w * 0.4
    )

    # 4 列 KPI：标签行 + 值行
    complexity_key = f"kpi_val_{arch.get('complexity', '').lower()}"
    cx_hex = _hex_for_kpi_style_key(complexity_key)
    col = content_w / 4.0
    kpi_data = [
        [
            Paragraph("复杂度", styles["kpi_label"]),
            Paragraph("组件数", styles["kpi_label"]),
            Paragraph("可维护性", styles["kpi_label"]),
            Paragraph("架构风格", styles["kpi_label"]),
        ],
        [
            _para_metric_value(arch.get("complexity", "—"), cx_hex),
            _para_metric_value(arch.get("components", "—"), HEX_TEXT),
            _para_metric_value(arch.get("maintainability", "—"), HEX_TEXT),
            _para_metric_value(arch.get("architectureStyle", "—"), HEX_TEXT),
        ],
    ]
    elements.append(_kpi_table(kpi_data, [col] * 4))
    elements.append(_spacer(6))

    # 技术栈标签
    tech = arch.get("techStack") or []
    if tech:
        tags_plain = "  /  ".join(str(t) for t in tech[:8])
        elements.append(Paragraph("<b>技术栈</b>", styles["insight"]))
        if tags_plain.isascii():
            elements.append(Paragraph(escape(tags_plain), styles["insight_en"]))
        else:
            elements.append(Paragraph(escape(tags_plain), styles["insight"]))
        elements.append(_spacer(5))

    # 设计模式
    patterns = arch.get("keyPatterns") or []
    if patterns:
        joined_plain = "  /  ".join(str(p) for p in patterns[:4])
        elements.append(Paragraph("<b>设计模式</b>", styles["insight"]))
        if joined_plain.isascii():
            elements.append(Paragraph(escape(joined_plain), styles["insight_en"]))
        else:
            elements.append(Paragraph(escape(joined_plain), styles["insight"]))
        elements.append(_spacer(5))

    # 热点（英文描述用 Helvetica，避免 STSong 排拉丁挤字）
    hotspots = arch.get("hotSpots") or []
    if hotspots:
        for h in hotspots[:4]:
            hs = str(h)
            if hs.isascii():
                elements.append(Paragraph(f"热点：{escape(hs)}", styles["hotspot_en"]))
            else:
                elements.append(Paragraph(f"热点：{escape(hs)}", styles["hotspot"]))

    # 摘要
    summary = arch.get("summary", "")
    if summary:
        elements.append(_spacer(6))
        elements.append(Paragraph(escape(str(summary)), styles["summary"]))

    header = _section_header("架构分析", ACCENT_ARCH, styles, content_w)
    body, _ = _section_body(elements, content_w)
    return [header, *body, _spacer(10)]


def _render_quality(
    quality: dict[str, Any],
    content_w: float,
    ai_image: bytes | None = None,
) -> list:
    if not quality:
        return []
    styles = _make_styles()
    elements: list = []

    # AI 生成章节配图
    elements = _add_ai_image(
        elements, None, None, ai_image, width=content_w * 0.4
    )

    score = quality.get("health_score", "—")
    raw_grade = quality.get("grade")
    if raw_grade is None or (isinstance(raw_grade, str) and not str(raw_grade).strip()):
        raw_grade = quality.get("qualityMaintainability")
    grade_str = str(raw_grade).strip() if raw_grade is not None else ""
    issues = quality.get("issues") or []

    score_para = _para_metric_value(score, HEX_TEXT)
    if not grade_str:
        grade_para = Paragraph("—", styles["kpi_value"])
    else:
        gk = _grade_style_key(grade_str)
        g_style_key = f"kpi_val_{gk}"
        grade_para = _para_metric_value(grade_str, _hex_for_kpi_style_key(g_style_key))

    half = content_w / 2.0
    kpi_data = [
        [Paragraph("综合评分", styles["kpi_label"]),
         Paragraph("评级", styles["kpi_label"])],
        [score_para, grade_para],
    ]
    elements.append(_kpi_table(kpi_data, [half, half]))
    elements.append(_spacer(8))

    for iss in issues[:8]:
        level = iss.get("severity", "m")
        title = iss.get("title", "未知问题")
        desc  = iss.get("description", "")
        elements.append(_item_row(title, desc, level, content_w))
        elements.append(_spacer(3))

    header = _section_header("代码质量", ACCENT_QUALITY, styles, content_w)
    body, _ = _section_body(elements, content_w)
    return [header, *body, _spacer(10)]


def _render_dependency(
    dep: dict[str, Any],
    content_w: float,
    ai_image: bytes | None = None,
) -> list:
    if not dep:
        return []
    styles = _make_styles()
    elements: list = []

    # AI 生成章节配图
    elements = _add_ai_image(
        elements, None, None, ai_image, width=content_w * 0.4
    )

    total  = dep.get("total", 0)
    high   = dep.get("high", 0)
    medium = dep.get("medium", 0)
    low    = dep.get("low", 0)
    summary = dep.get("summary") or []

    risk = "h" if high > 0 else "m" if medium > 0 else "l"
    col = content_w / 4.0
    kpi_data = [
        [Paragraph("总依赖", styles["kpi_label"]),
         Paragraph("高危", styles["kpi_label"]),
         Paragraph("中危", styles["kpi_label"]),
         Paragraph("低危", styles["kpi_label"])],
        [
            _para_metric_value(total, HEX_TEXT),
            _para_metric_value(high, HEX_RISK_H),
            _para_metric_value(medium, HEX_RISK_M),
            _para_metric_value(low, HEX_RISK_L),
        ],
    ]
    elements.append(_kpi_table(kpi_data, [col] * 4))
    elements.append(_spacer(8))

    if summary:
        lines = "<br/>".join(f"- {escape(str(s))}" for s in summary[:5])
        elements.append(Paragraph(lines, styles["summary"]))

    risk_label = {"h": "高风险", "m": "中风险", "l": "低风险"}.get(risk, "")
    header = _section_header(f"依赖分析  |  {risk_label}", ACCENT_DEP, styles, content_w)
    body, _ = _section_body(elements, content_w)
    return [header, *body, _spacer(10)]


def _render_optimization(
    opt: dict[str, Any],
    content_w: float,
    ai_image: bytes | None = None,
) -> list:
    if not opt:
        return []
    styles = _make_styles()
    elements: list = []

    # AI 生成章节配图
    elements = _add_ai_image(
        elements, None, None, ai_image, width=content_w * 0.4
    )

    high_p   = opt.get("high_priority", 0)
    medium_p = opt.get("medium_priority", 0)
    low_p    = opt.get("low_priority", 0)
    suggestions = opt.get("suggestions") or []

    col = content_w / 3.0
    kpi_data = [
        [Paragraph("高优先级", styles["kpi_label"]),
         Paragraph("中优先级", styles["kpi_label"]),
         Paragraph("低优先级", styles["kpi_label"])],
        [
            _para_metric_value(high_p, HEX_RISK_H),
            _para_metric_value(medium_p, HEX_RISK_M),
            _para_metric_value(low_p, HEX_RISK_L),
        ],
    ]
    elements.append(_kpi_table(kpi_data, [col] * 3))
    elements.append(_spacer(8))

    for s in suggestions[:8]:
        priority = s.get("priority", "m")
        title = s.get("title", "建议")
        desc  = s.get("description", "")
        stype = s.get("type", "优化")
        elements.append(_item_row(f"[{stype}] {title}", desc, priority, content_w))
        elements.append(_spacer(3))

    header = _section_header("优化建议", ACCENT_OPT, styles, content_w)
    body, _ = _section_body(elements, content_w)
    return [header, *body, _spacer(10)]


# ── 主构建函数 ───────────────────────────────────────────────────

def _pre_generate_ai_images(
    data: dict[str, Any],
    enable_ai_image: bool,
) -> dict[str, bytes | None]:
    """预生成所有 AI 图片，返回图片字节字典"""
    images: dict[str, bytes | None] = {
        "cover": None,
        "architecture": None,
        "quality": None,
        "dependency": None,
        "optimization": None,
    }

    if not enable_ai_image or not AI_IMAGE_AVAILABLE:
        return images

    try:
        # 封面图
        repo_name = data.get("repo_url", "Unknown").split("/")[-1] or "project"
        tech_stack = data.get("architecture", {}).get("techStack", [])
        images["cover"] = get_cached_image_sync(
            f"cover_{repo_name}", _get_prompt_for_cover(repo_name, tech_stack)
        )

        # 架构分析图
        arch = data.get("architecture", {})
        images["architecture"] = get_cached_image_sync(
            f"arch_{arch.get('architectureStyle', 'layered')}",
            _get_prompt_for_architecture(
                arch.get("architectureStyle", "layered"),
                arch.get("complexity", "medium"),
            ),
        )

        # 代码质量图
        quality = data.get("quality", {})
        images["quality"] = get_cached_image_sync(
            f"quality_{quality.get('grade', 'B')}",
            _get_prompt_for_quality(
                quality.get("grade", "B"),
                str(quality.get("health_score", "—")),
            ),
        )

        # 依赖分析图
        dep = data.get("dependency", {})
        risk = "h" if dep.get("high", 0) > 0 else "m" if dep.get("medium", 0) > 0 else "l"
        images["dependency"] = get_cached_image_sync(
            f"dep_{risk}",
            _get_prompt_for_dependency(risk),
        )

        # 优化建议图
        images["optimization"] = get_cached_image_sync(
            "optimization", _get_prompt_for_optimization()
        )

    except Exception as e:
        import logging
        logging.getLogger("pdf_service").warning(f"AI 图片生成失败: {e}")

    return images


def build_pdf_bytes(
    data: dict[str, Any],
    enable_ai_image: bool = False,
) -> bytes:
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
    enable_ai_image: 是否启用通义千问 AI 生图（需要 OPENAI_API_KEY 环境变量）
    """
    # 预生成 AI 图片
    ai_images = _pre_generate_ai_images(data, enable_ai_image)

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

    content_w = doc.width
    styles = _make_styles()
    story: list = []

    # 封面
    story.extend(_build_cover(data, styles, cover_image=ai_images["cover"]))

    # 四个模块：每个模块 = 标题 + 内容 Table（内容无边框，仅整体外框）
    module_images = {
        "architecture": ai_images.get("architecture"),
        "quality": ai_images.get("quality"),
        "dependency": ai_images.get("dependency"),
        "optimization": ai_images.get("optimization"),
    }

    for module_data, render_fn, img_key in [
        (data.get("architecture", {}), _render_architecture, "architecture"),
        (data.get("quality", {}), _render_quality, "quality"),
        (data.get("dependency", {}), _render_dependency, "dependency"),
        (data.get("optimization", {}), _render_optimization, "optimization"),
    ]:
        result = render_fn(module_data, content_w, ai_image=module_images.get(img_key))
        if not result:  # 模块数据为空时跳过
            continue
        header, *body_parts, end_spacer = result
        story.append(header)
        if body_parts:
            body_table = Table([[p] for p in body_parts], colWidths=[content_w])
            body_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), SECTION_BG),
                ("BOX", (0, 0), (-1, -1), 0.75, BORDER_STR),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(body_table)
        story.append(end_spacer)

    # 页脚
    story.append(_spacer(6))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    story.append(_spacer(3))
    story.append(Paragraph(
        f"由 GitIntel AI 分析引擎生成 <font color='{HEX_MUTED}'>|</font> "
        f"仅供参考，请以实际代码为准",
        styles["footer"],
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()
