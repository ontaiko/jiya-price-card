"""尺寸、版型、專案與實際尺寸 PDF 的共同核心。"""

from __future__ import annotations

import base64
import copy
import json
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any

from PIL import Image
from io import BytesIO

PT_PER_MM = 72 / 25.4
PAPER = {"A4": (210.0, 297.0), "A3": (297.0, 420.0)}
COLORS = {"store": "#B70031", "price": "#FF0000", "text": "#121212", "secondary": "#595959"}
BRAND_ASSETS = {
    "LG": "lg.png", "SONY": "sony.png", "SAMSUNG": "samsung.png",
    "CHIMEI": "chimei.png", "PHILIPS": "philips.png", "SteamOne": "steamone.png",
    "WINIX": "winix.png", "Wharfedale": "wharfedale.png", "cado": "cado.png",
    "Whirlpool": "whirlpool.png", "YAMAHA": "yamaha.png",
}
FIELD_LABELS = {
    "store_logo": "集雅社標誌", "brand_logo": "廠牌標誌／文字", "name": "商品名稱",
    "model": "型號", "specifications": "重點與尺寸", "features": "商品說明",
    "dimensions": "尺寸說明", "price_label": "價格標籤", "price_value": "售價",
    "old_price": "原價", "components": "組合內容", "variant_1_model": "型號一",
    "variant_1_desc": "型號一說明", "variant_1_price": "型號一價格",
    "variant_2_model": "型號二", "variant_2_desc": "型號二說明",
    "variant_2_price": "型號二價格", "custom_text": "自訂文字",
}


def resources() -> Path:
    return Path(__file__).resolve().parent / "resources"


def builtin_specs() -> list[dict]:
    return json.loads((resources() / "templates.json").read_text(encoding="utf-8"))["templates"]


def new_product() -> dict:
    return {
        "brand": "", "brand_mode": "logo", "brand_text": "", "custom_logo": "",
        "name": "", "model": "", "features": "", "dimensions": "", "price": "",
        "old_price": "", "price_label": "特價",
        "variants": [{"model": "", "description": "", "price": ""} for _ in range(2)],
        "components": "", "custom": {}, "sku": "", "location": "", "notes": "",
    }


def _elt(field: str, rect: list[float], size: float, color: str = "text", align: str = "left", kind: str = "text") -> dict:
    return {"id": field, "kind": kind, "field": field, "rect": [round(float(v), 2) for v in rect],
            "size": float(size), "color": COLORS.get(color, color), "align": align,
            "visible": True, "locked": field == "store_logo"}


def template_from_spec(s: dict) -> dict:
    w, h = float(s["width_mm"]), float(s["height_mm"])
    margin = float(s["safe_margin_mm"])
    brand_w = 22 if w <= 60 else 28 if w <= 90 else 34 if w <= 115 else 50
    store_w = 21 if w <= 60 else 25 if w <= 90 else 28 if w <= 115 else 45
    logo_h = 8 if w < 150 else 15
    elements = [
        _elt("store_logo", [margin, 3, store_w, logo_h], 10, kind="image"),
        _elt("brand_logo", [w - margin - brand_w, 3, brand_w, logo_h], 10, kind="image"),
    ]
    fieldrect = {f["name"]: f["rect_mm"] for f in s["fields"]}
    for key, field in [("name", "name"), ("model", "model"),
                       ("specifications", "specifications"), ("features", "features"),
                       ("dimensions", "dimensions"), ("components", "components")]:
        if key in fieldrect:
            size = s["title_pt"] if key == "name" else s["model_pt"] if key == "model" else s["body_pt"]
            elements.append(_elt(field, fieldrect[key], size, "secondary" if key == "dimensions" else "text"))
    if "price" in fieldrect:
        x, y, rw, rh = map(float, fieldrect["price"])
        label_w = min(24, rw * .42)
        value_x = x + label_w
        elements.append(_elt("price_label", [x, y + max(0, rh * .27), label_w, min(rh * .56, 6)],
                             max(8, s["body_pt"] - 1), "secondary"))
        elements.append(_elt("price_value", [value_x, y, rw - label_w, rh], s["price_pt"], "price", "right"))
        old_x = margin if w > 100 else x
        old_w = min(45, value_x - old_x) if w > 100 else label_w + 5
        elements.append(_elt("old_price", [old_x, y - (5.2 if w > 100 else 4.5), old_w, 4.5], 8.5, "secondary"))
    for n in (1, 2):
        key = f"variant_{n}"
        if key in fieldrect:
            x, y, rw, rh = map(float, fieldrect[key])
            elements.extend([
                _elt(f"variant_{n}_model", [x, y, rw * .58, 5.1], s["model_pt"]),
                _elt(f"variant_{n}_desc", [x, y + 6.2, rw * .66, 5], s["body_pt"], "secondary"),
                _elt(f"variant_{n}_price", [x + rw * .61, y + 1.5, rw * .39, 8.5], s["price_pt"], "price", "right"),
            ])
    return {"id": s["id"], "name": s["name"], "width_mm": w, "height_mm": h,
            "mode": s["mode"], "safe_margin_mm": margin, "elements": elements, "builtin": True}


def default_templates() -> dict[str, dict]:
    return {t["id"]: t for t in map(template_from_spec, builtin_specs())}


def new_card(template: dict) -> dict:
    return {"id": uuid.uuid4().hex[:12], "template_id": template["id"], "name": "未命名價格牌",
            "width_mm": template["width_mm"], "height_mm": template["height_mm"],
            "mode": template["mode"], "safe_margin_mm": template["safe_margin_mm"],
            "product": new_product(), "elements": copy.deepcopy(template["elements"])}


def new_project() -> dict:
    defaults = default_templates()
    card = new_card(defaults["compact-90x60"])
    return {"version": 1, "templates": {}, "cards": [card], "current_id": card["id"],
            "queue": [], "assets": {}, "snippets": [
                {"name": "寬高深尺寸", "text": "寬＿＿ × 高＿＿ × 深＿＿ mm"},
                {"name": "不含底座尺寸", "text": "不含底座：寬＿＿ × 高＿＿ × 深＿＿ mm"},
                {"name": "洗衣容量", "text": "洗衣容量：＿＿ kg"},
                {"name": "冰箱容量", "text": "總容量：＿＿ L"},
            ], "print": {"paper": "A4", "orientation": "自動", "margin_mm": 5,
            "gap_mm": 2, "crop_marks": True}}


def get_card(project: dict) -> dict:
    return next(c for c in project["cards"] if c["id"] == project["current_id"])


def all_templates(project: dict) -> dict[str, dict]:
    return {**default_templates(), **project.get("templates", {})}


def switch_template(card: dict, template: dict) -> None:
    card.update({"template_id": template["id"], "width_mm": template["width_mm"],
                 "height_mm": template["height_mm"], "mode": template["mode"],
                 "safe_margin_mm": template["safe_margin_mm"],
                 "elements": copy.deepcopy(template["elements"])})


def save_as_template(project: dict, card: dict, name: str) -> dict:
    t = {"id": "custom-" + uuid.uuid4().hex[:10], "name": name.strip(),
         "width_mm": float(card["width_mm"]), "height_mm": float(card["height_mm"]),
         "mode": card["mode"], "safe_margin_mm": float(card["safe_margin_mm"]),
         "elements": copy.deepcopy(card["elements"]), "builtin": False}
    if not t["name"]:
        raise ValueError("版型需要名稱")
    project["templates"][t["id"]] = t
    card["template_id"] = t["id"]
    return t


def move_element(element: dict, dx: float, dy: float, card: dict) -> bool:
    if element.get("locked"):
        return False
    rect = element["rect"]
    nx = max(0, min(float(card["width_mm"]) - rect[2], rect[0] + dx))
    ny = max(0, min(float(card["height_mm"]) - rect[3], rect[1] + dy))
    if nx == rect[0] and ny == rect[1]:
        return False
    rect[0], rect[1] = round(nx, 2), round(ny, 2)
    return True


def save_project(path: os.PathLike, project: dict) -> None:
    # Only JSON values are accepted; no pickle, scripts, or external image paths.
    if project.get("version") != 1:
        raise ValueError("專案版本不支援")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def load_project(path: os.PathLike) -> dict:
    p = json.loads(Path(path).read_text(encoding="utf-8"))
    if p.get("version") != 1 or not isinstance(p.get("cards"), list) or not p["cards"]:
        raise ValueError("無法讀取此專案版本或價格牌資料")
    if p.get("current_id") not in {c.get("id") for c in p["cards"]}:
        raise ValueError("找不到目前價格牌")
    p.setdefault("templates", {}); p.setdefault("assets", {}); p.setdefault("queue", [])
    p.setdefault("snippets", new_project()["snippets"])
    p.setdefault("print", new_project()["print"])
    return p


def attach_logo(project: dict, filename: str, raw: bytes) -> str:
    if len(raw) > 8_000_000:
        raise ValueError("Logo 圖片不得超過 8 MB")
    try:
        with Image.open(BytesIO(raw)) as img:
            if img.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError("圖片格式不支援")
            img.verify()
    except Exception as exc:
        raise ValueError("無法讀取此 Logo 圖片，請使用 PNG、JPEG 或 WebP") from exc
    key = "upload-" + uuid.uuid4().hex[:12]
    project["assets"][key] = {"filename": Path(filename).name, "data": base64.b64encode(raw).decode("ascii")}
    return key


def _rgb(s: str) -> tuple[float, float, float]:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", s):
        raise ValueError("顏色請輸入 #RRGGBB")
    return tuple(int(s[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _format_price(raw: str) -> str:
    s = str(raw).strip().replace(",", "")
    if not s:
        return ""
    if re.fullmatch(r"\d+", s):
        return f"{int(s):,}"
    return str(raw).strip()


def _field_text(card: dict, element: dict) -> str:
    p, f = card["product"], element["field"]
    if f == "name": return p.get("name", "")
    if f == "model": return p.get("model", "")
    if f == "features": return p.get("features", "")
    if f == "dimensions": return p.get("dimensions", "")
    if f == "specifications": return "\n".join(x for x in (p.get("features", ""), p.get("dimensions", "")) if x)
    if f == "components": return p.get("components", "")
    if f == "price_label": return p.get("price_label", "") if p.get("price", "") else ""
    if f == "price_value": return _format_price(p.get("price", ""))
    if f == "old_price": return f"原價 {_format_price(p['old_price'])} 元" if p.get("old_price", "") else ""
    if f == "custom_text": return p.get("custom", {}).get(element["id"], "")
    m = re.fullmatch(r"variant_(\d+)_(model|desc|price)", f)
    if m:
        n, key = int(m.group(1)) - 1, m.group(2)
        variants = p.get("variants", [])
        if n >= len(variants): return ""
        if key == "price": return _format_price(variants[n].get("price", ""))
        return str(variants[n].get("description" if key == "desc" else key, ""))
    return ""


def layout_for(w: float, h: float, paper: str, orientation: str = "自動",
               margin: float = 5, gap: float = 2) -> dict:
    if paper not in PAPER: raise ValueError("紙張須為 A4 或 A3")
    if margin < 0 or gap < 0: raise ValueError("邊距與牌間距不可為負數")
    pw, ph = PAPER[paper]
    options = [(pw, ph, "直式"), (ph, pw, "橫式")]
    if orientation != "自動": options = [o for o in options if o[2] == orientation]
    if not options: raise ValueError("頁面方向無效")
    candidates = []
    for pwidth, pheight, label in options:
        cols = max(0, math.floor((pwidth - 2 * margin + gap + 1e-8) / (w + gap)))
        rows = max(0, math.floor((pheight - 2 * margin + gap + 1e-8) / (h + gap)))
        candidates.append({"paper_width": pwidth, "paper_height": pheight,
                           "orientation": label, "cols": cols, "rows": rows, "capacity": cols * rows})
    best = max(candidates, key=lambda x: x["capacity"])
    if not best["capacity"]:
        raise ValueError(f"{w:g} × {h:g} mm 放不進 {paper} 的目前方向及邊距；請改紙張方向或尺寸")
    return best



from .core_pdf import render_card_pdf, export_single, export_sheet  # noqa: E402
