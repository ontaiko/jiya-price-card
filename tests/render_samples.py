"""產生供人工檢查的七張非現價樣張。"""
from pathlib import Path
import sys
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pricecard import core


def main():
    project = core.new_project()
    project["cards"] = []
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "sample-check")
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for spec in core.builtin_specs():
        card = core.new_card(core.default_templates()[spec["id"]])
        product = card["product"]
        if spec["mode"] == "variants":
            product.update({"brand": "SONY", "name": "耳式真無線藍牙耳機",
                            "variants": [{"model": "WF-C510", "description": "續航 22 小時", "price": "1990"},
                                         {"model": "WF-C710N", "description": "降噪功能", "price": "3490"}]})
        elif spec["mode"] == "bundle":
            product.update({"brand": "YAMAHA", "name": "4～8坪 入門聆聽音響組",
                            "components": "CD-NT670 + A670\nTANGENT X4 書架喇叭",
                            "features": "支援 CD／AirPlay／藍牙", "old_price": "46900", "price": "41900", "price_label": "組合特價"})
        elif spec["width_mm"] == 210:
            product.update({"brand": "SAMSUNG", "name": "655L 美式對開系列冰箱 夜幕黑",
                            "model": "RS70F65Q4FT", "dimensions": "寬912 × 高1780 × 深716 mm",
                            "features": "AI 智慧節能模式\nSpaceMax 薄窄邊框\n壓縮機 20 年保固", "price": "59900", "price_label": "訂價"})
        else:
            product.update({"brand": "SONY", "name": "65吋 Mini LED 4K 智慧顯示器",
                            "model": "Y-65XR50", "features": "BRAVIA 5",
                            "dimensions": "不含底座 1447 × 832 × 58 mm", "old_price": "59900",
                            "price": "45900"})
        blob, warnings = core.render_card_pdf(card, project)
        (out / f"{spec['id']}.pdf").write_bytes(blob)
        pdf = pdfium.PdfDocument(blob)
        page = pdf[0]
        pix = page.render(scale=2.2).to_pil()
        png = out / f"{spec['id']}.png"
        pix.save(png)
        page.close();pdf.close()
        print(spec["id"], warnings)
        card["name"] = "【示範非現價】" + spec["name"]
        card["product"]["notes"] = "舊價格牌的範例內容，僅供版型操作測試；請勿作為現行售價。"
        project["cards"].append(card)
        im = Image.open(png).convert("RGB")
        im.thumbnail((570, 330))
        rows.append((spec["name"], im))
    board = Image.new("RGB", (1240, 4 * 400 + 50), "#f2f3f5")
    dr = ImageDraw.Draw(board)
    font = ImageFont.truetype(str(core.resources() / "CJK.ttf"), 22)
    for i, (name, im) in enumerate(rows):
        x = 35 + (i % 2) * 620
        y = 35 + (i // 2) * 400
        dr.text((x, y), name, font=font, fill="#2c2c2c")
        board.paste(im, (x, y + 44))
    board.save(out / "contact.png")
    project["current_id"] = project["cards"][0]["id"]
    project["queue"] = [{"card_id": card["id"], "qty": 1} for card in project["cards"]]
    core.save_project(Path(__file__).resolve().parents[1] / "範例專案_非現價.jyp", project)


if __name__ == "__main__": main()
