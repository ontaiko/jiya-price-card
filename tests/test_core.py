from io import BytesIO
import sys
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pricecard import core


class PriceCardCoreTests(unittest.TestCase):
    def setUp(self):
        self.project = core.new_project()

    def populated(self, template_id):
        t = core.default_templates()[template_id]
        card = core.new_card(t)
        card["product"].update({
            "brand": "SONY", "name": "65吋 Mini LED 4K 智慧顯示器",
            "model": "Y-65XR50", "features": "BRAVIA 5",
            "dimensions": "不含底座 1447 × 832 × 58 mm", "price": "45900",
            "old_price": "59900", "components": "YAMAHA CD-NT670\nTANGENT X4",
            "variants": [{"model": "WF-C510", "description": "22小時續航", "price": "1990"},
                         {"model": "WF-C710N", "description": "降噪功能", "price": "3490"}],
        })
        return card

    def test_all_seven_template_sizes_and_cjk_text(self):
        specs = core.builtin_specs()
        self.assertEqual(len(specs), 7)
        self.assertEqual(len(core.default_templates()), 7)
        for s in specs:
            with self.subTest(template=s["id"]):
                card = self.populated(s["id"])
                blob, warnings = core.render_card_pdf(card, self.project)
                page = PdfReader(BytesIO(blob)).pages[0]
                self.assertAlmostEqual(float(page.mediabox.width), s["width_mm"] * core.PT_PER_MM, places=2)
                self.assertAlmostEqual(float(page.mediabox.height), s["height_mm"] * core.PT_PER_MM, places=2)
                words = page.extract_text()
                self.assertIn("65吋", words)
                self.assertIn("45,900" if s["mode"] != "variants" else "1,990", words)
                self.assertNotIn("超出成品邊界", " ".join(warnings))

    def test_sheet_keeps_exact_text_size_and_card_width(self):
        card = self.populated("compact-90x60")
        self.project["cards"] = [card]
        self.project["current_id"] = card["id"]
        self.project["queue"] = [{"card_id": card["id"], "qty": 9}]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sheet.pdf"
            page_count, _warnings = core.export_sheet(out, self.project, orientation="直式")
            self.assertEqual(page_count, 2)
            pdf = PdfReader(out)
            self.assertAlmostEqual(float(pdf.pages[0].mediabox.width) / core.PT_PER_MM, 210, places=2)
            self.assertAlmostEqual(float(pdf.pages[0].mediabox.height) / core.PT_PER_MM, 297, places=2)
            self.assertEqual(pdf.pages[0].extract_text().count("45,900"), 8)
            sizes = []
            pdf.pages[0].extract_text(visitor_text=lambda text, _cm, _tm, _fd, size: sizes.append(size) if "45,900" in text else None)
            self.assertEqual(len(sizes), 8)
            self.assertTrue(all(abs(size - 28) < .05 for size in sizes))

    def test_imposition_for_large_cards(self):
        self.assertEqual(core.layout_for(115, 65, "A4")["capacity"], 6)
        self.assertEqual(core.layout_for(60, 65, "A4")["capacity"], 12)
        self.assertEqual(core.layout_for(210, 130, "A4")["capacity"], 1)
        self.assertEqual(core.layout_for(210, 130, "A3")["capacity"], 3)
        with self.assertRaises(ValueError): core.layout_for(210, 130, "A4", "直式")

    def test_position_nudge_and_boundary(self):
        card = self.populated("compact-90x60")
        name = next(e for e in card["elements"] if e["id"] == "name")
        self.assertTrue(core.move_element(name, .1, 0, card))
        self.assertEqual(name["rect"][0], 3.1)
        core.move_element(name, 999, 999, card)
        self.assertEqual(name["rect"][0] + name["rect"][2], card["width_mm"])
        self.assertEqual(name["rect"][1] + name["rect"][3], card["height_mm"])
        locked = next(e for e in card["elements"] if e["id"] == "store_logo")
        self.assertFalse(core.move_element(locked, 1, 0, card))

    def test_project_round_trip_assets_and_independent_template(self):
        card = core.get_card(self.project)
        self.assertFalse(card["product"]["price"])
        card["product"]["name"] = "測試商品"
        name = next(e for e in card["elements"] if e["id"] == "name")
        core.move_element(name, 1, 0, card)
        t = core.save_as_template(self.project, card, "店員版")
        self.assertTrue(t["id"].startswith("custom-"))
        self.assertEqual(core.default_templates()["compact-90x60"]["elements"][2]["rect"][0], 3)
        logo = (core.resources() / "logos" / "sony.png").read_bytes()
        key = core.attach_logo(self.project, "sony.png", logo)
        card["product"]["custom_logo"] = key
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project.jyp"
            core.save_project(path, self.project)
            reopened = core.load_project(path)
            self.assertEqual(reopened["assets"][key]["filename"], "sony.png")
            self.assertEqual(core.get_card(reopened)["elements"][2]["rect"][0], 4)
            self.assertIn(t["id"], core.all_templates(reopened))
            blob, _ = core.render_card_pdf(core.get_card(reopened), reopened)
            self.assertIn("測試商品", PdfReader(BytesIO(blob)).pages[0].extract_text())

    def test_overflow_is_reported(self):
        card = self.populated("compact-90x60")
        card["product"]["name"] = "很長的電視商品名稱" * 12
        _blob, issues = core.render_card_pdf(card, self.project)
        self.assertTrue(any("商品名稱文字溢出" in i for i in issues))


if __name__ == "__main__": unittest.main()
