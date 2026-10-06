"""以 ReportLab 產生精確毫米尺寸 PDF，並供預覽載入。"""

from __future__ import annotations

import base64
import io
import math
import os
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

from . import core

FONT_NAME = "JiYaCJK"
_FONT_READY = False


def _ensure_font():
    global _FONT_READY
    if not _FONT_READY:
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(core.resources() / "CJK.ttf")))
        _FONT_READY = True


def _image_bytes(project, card, element):
    f = element["field"]
    if f == "store_logo":
        return (core.resources() / "logos" / "store.png").read_bytes()
    if f == "asset_image":
        item = project.get("assets", {}).get(element.get("asset_key", ""))
        return base64.b64decode(item["data"]) if item else None
    if f == "brand_logo":
        p = card["product"]
        if p.get("brand_mode", "logo") != "logo": return None
        custom = p.get("custom_logo", "")
        if custom and custom in project.get("assets", {}):
            return base64.b64decode(project["assets"][custom]["data"])
        filename = core.BRAND_ASSETS.get(p.get("brand", ""))
        if filename: return (core.resources() / "logos" / filename).read_bytes()
    return None


def _wrap(text, width_pt, font_size):
    lines = []
    for paragraph in text.replace("\r", "").split("\n"):
        if not paragraph:
            lines.append("")
            continue
        line = ""
        for char in paragraph:
            if line and pdfmetrics.stringWidth(line + char, FONT_NAME, font_size) > width_pt:
                lines.append(line.rstrip())
                line = char.lstrip()
            else:line += char
        lines.append(line)
    return lines


def draw_card(c, card, project, origin_x=0.0, origin_y=0.0):
    """Draws a card at the lower-left PDF origin without scaling; returns issues."""
    _ensure_font()
    w, h = float(card["width_mm"]), float(card["height_mm"])
    if not (40 <= w <= 420 and 30 <= h <= 420):
        raise ValueError("成品尺寸須介於 40 × 30 與 420 × 420 mm 之間")
    factor = core.PT_PER_MM
    c.saveState()
    c.translate(origin_x, origin_y)
    clip = c.beginPath();clip.rect(0, 0, w * factor, h * factor)
    c.clipPath(clip, stroke=0, fill=0)
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, w * factor, h * factor, stroke=0, fill=1)
    c.setStrokeColorRGB(.83, .83, .83)
    c.setLineWidth(.08 * factor)
    c.rect(.25 * factor, .25 * factor, (w - .5) * factor, (h - .5) * factor, stroke=1, fill=0)
    warnings = []
    for element in card.get("elements", []):
        if not element.get("visible", True): continue
        x, y, ew, eh = map(float, element["rect"])
        label = element.get("label") or core.FIELD_LABELS.get(element.get("field", ""), "方塊")
        if x < 0 or y < 0 or x + ew > w + .0001 or y + eh > h + .0001:
            warnings.append(f"{label}超出成品邊界")
        if ew <= 0 or eh <= 0:
            warnings.append(f"{label}尺寸無效")
            continue
        left = x * factor
        bottom = (h - y - eh) * factor
        rw, rh = ew * factor, eh * factor
        if element.get("kind") == "stripes":
            try: color = core._rgb(element.get("color", core.COLORS["store"]))
            except ValueError: color = core._rgb(core.COLORS["store"])
            stroke = min(eh / 5, max(.2, eh * .08)) * factor
            c.setStrokeColorRGB(*color)
            c.setLineWidth(stroke)
            for i in range(5):
                yy = bottom + stroke / 2 + i * (rh - stroke) / 4
                c.line(left, yy, left + rw, yy)
            continue
        if element.get("kind") in ("rectangle", "line"):
            try: color = core._rgb(element.get("color", core.COLORS["store"]))
            except ValueError: color = core._rgb(core.COLORS["store"])
            c.setStrokeColorRGB(*color)
            c.setLineWidth(max(.1, float(element.get("stroke_mm", .25))) * factor)
            if element["kind"] == "line":c.line(left, bottom + rh, left + rw, bottom)
            else:
                fill = element.get("fill")
                if fill:
                    try:c.setFillColorRGB(*core._rgb(fill))
                    except ValueError:c.setFillColorRGB(1, 1, 1)
                c.rect(left, bottom, rw, rh, stroke=1, fill=int(bool(fill)))
            continue
        text = ""
        if element.get("kind") == "image":
            if element["field"] == "brand_logo":
                p = card["product"]
                mode = p.get("brand_mode", "logo")
                if mode == "hidden": continue
                if mode == "text":text = p.get("brand_text") or p.get("brand", "")
            img = _image_bytes(project, card, element)
            if img:
                try:
                    c.drawImage(ImageReader(io.BytesIO(img)), left, bottom, rw, rh,
                                preserveAspectRatio=element.get("image_fit") != "stretch",
                                anchor="c", mask="auto")
                except Exception:
                    warnings.append(f"{label}圖片無法載入")
                continue
            if element["field"] == "asset_image":
                warnings.append("自訂圖片遺失")
                continue
            if element["field"] == "brand_logo" and mode == "logo" and p.get("brand"):
                warnings.append("找不到指定品牌 Logo，改以文字顯示")
                text = p.get("brand", "")
        else:text = core._field_text(card, element)
        if element.get("kind") == "text" and element.get("fill"):
            try:
                c.setFillColorRGB(*core._rgb(element["fill"]))
                c.rect(left, bottom, rw, rh, stroke=0, fill=1)
            except ValueError:
                warnings.append(f"{label}背景色格式不正確")
        if not text: continue
        size = float(element.get("size", 10))
        if not 4 <= size <= 100:
            warnings.append(f"{label}字級不在 4–100 pt 範圍")
            continue
        try:color = core._rgb(element.get("color", core.COLORS["text"]))
        except ValueError:
            warnings.append(f"{label}顏色格式不正確")
            color = core._rgb(core.COLORS["text"])
        c.setFillColorRGB(*color)
        c.setFont(FONT_NAME, size)
        lines = _wrap(text, rw, size)
        leading = size * 1.17
        required = size * 1.04 + (len(lines) - 1) * leading
        if required > rh + 1:
            warnings.append(f"{label}文字溢出（需要約 {required / factor:.1f} mm，方塊高 {eh:g} mm）")
        for i, line in enumerate(lines):
            if not line: continue
            length = pdfmetrics.stringWidth(line, FONT_NAME, size)
            align = element.get("align", "left")
            tx = left if align == "left" else left + rw - length if align == "right" else left + (rw - length) / 2
            ty = (h - y) * factor - size * .94 - i * leading
            if element.get("bold", False):
                c.saveState()
                c.setStrokeColorRGB(*color)
                c.setLineWidth(max(.12, size * .025))
                text_object = c.beginText(tx, ty)
                text_object.setFont(FONT_NAME, size)
                text_object.setTextRenderMode(2)
                text_object.textOut(line)
                c.drawText(text_object)
                c.restoreState()
            else:
                c.drawString(tx, ty, line)
    c.restoreState()
    return list(dict.fromkeys(warnings))


def render_card_pdf(card, project):
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=(card["width_mm"] * core.PT_PER_MM,
                                         card["height_mm"] * core.PT_PER_MM), pageCompression=1)
    issues = draw_card(c, card, project)
    c.showPage();c.save()
    return output.getvalue(), issues


def export_single(path: os.PathLike, card, project):
    blob, issues = render_card_pdf(card, project)
    Path(path).write_bytes(blob)
    return issues


def _crop_marks(c, x, y, w, h):
    length = .7 * core.PT_PER_MM
    c.setStrokeColorRGB(.55, .55, .55)
    c.setLineWidth(.25)
    for xx in (x, x + w):
        for yy in (y, y + h):
            a = -1 if xx == x else 1
            b = -1 if yy == y else 1
            c.line(xx + a * .15 * core.PT_PER_MM, yy, xx + a * length, yy)
            c.line(xx, yy + b * .15 * core.PT_PER_MM, xx, yy + b * length)


def export_sheet(path: os.PathLike, project, queue=None, paper=None, orientation=None,
                 margin_mm=None, gap_mm=None, crop_marks=None):
    settings = project["print"]
    paper = paper or settings["paper"]
    orientation = orientation or settings["orientation"]
    margin = float(settings["margin_mm"] if margin_mm is None else margin_mm)
    gap = float(settings["gap_mm"] if gap_mm is None else gap_mm)
    marks = settings["crop_marks"] if crop_marks is None else crop_marks
    items = queue if queue is not None else project.get("queue", [])
    lookup = {card["id"]: card for card in project["cards"]}
    expanded = []
    for item in items:
        card = lookup.get(item["card_id"])
        if card and 1 <= int(item["qty"]) <= 1000:
            expanded.extend([card] * int(item["qty"]))
    if not expanded:raise ValueError("列印清單沒有價格牌，請先加入")
    if len(expanded) > 1000:raise ValueError("每次最多輸出 1000 張價格牌")
    groups = []
    for card in expanded:
        dims = (float(card["width_mm"]), float(card["height_mm"]))
        if not groups or groups[-1][0] != dims:groups.append((dims, []))
        groups[-1][1].append(card)
    c = canvas.Canvas(str(path), pageCompression=1)
    pages = 0;warnings = []
    for (w, h), cards in groups:
        layout = core.layout_for(w, h, paper, orientation, margin, gap)
        ncol, capacity = layout["cols"], layout["capacity"]
        pw, ph = layout["paper_width"], layout["paper_height"]
        for start in range(0, len(cards), capacity):
            c.setPageSize((pw * core.PT_PER_MM, ph * core.PT_PER_MM))
            for slot, card in enumerate(cards[start:start + capacity]):
                x = (margin + (slot % ncol) * (w + gap)) * core.PT_PER_MM
                y = (ph - margin - h - (slot // ncol) * (h + gap)) * core.PT_PER_MM
                warnings.extend(draw_card(c, card, project, x, y))
                if marks:_crop_marks(c, x, y, w * core.PT_PER_MM, h * core.PT_PER_MM)
            c.showPage();pages += 1
    c.save()
    return pages, list(dict.fromkeys(warnings))
