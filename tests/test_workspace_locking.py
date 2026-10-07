"""廠商切換時，價格牌與共用版型的方塊鎖定狀態不得消失。"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pricecard import core
from pricecard.gui import PriceCardApp
from pricecard.workspace import Workspace


class WorkspaceLockingTests(unittest.TestCase):
    def test_all_element_kinds_stay_locked_after_switching_vendors(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Workspace(Path(folder))
            first = core.new_project()
            card = core.get_card(first)
            card["elements"].extend([
                core._elt("custom_image", [5, 20, 10, 10], 10, kind="image"),
                core._elt("custom_rectangle", [15, 20, 10, 10], 10, kind="rectangle"),
                core._elt("custom_line", [30, 20, 10, .5], 10, kind="line"),
            ])
            logo = next(element for element in card["elements"] if element["field"] == "store_logo")
            logo["rect"] = core._legacy_store_rect(card["width_mm"], card["safe_margin_mm"])
            extra_logo = core._elt("store_logo", [40, 30, 12, 6], 10, kind="image")
            extra_logo["id"] = "added_store_logo"
            card["elements"].append(extra_logo)
            for element in card["elements"]:
                element["locked"] = True
            saved_rects = {element["id"]: element["rect"][:] for element in card["elements"]}
            template = core.save_as_template(first, card, "鎖定版型")
            first_id = workspace.create_project("廠商甲", first)
            second_id = workspace.create_project("廠商乙", core.new_project())

            workspace.load_project(second_id)
            reopened = workspace.load_project(first_id)
            reopened_card = core.get_card(reopened)
            self.assertEqual(saved_rects, {element["id"]: element["rect"] for element in reopened_card["elements"]})
            for element in reopened_card["elements"]:
                with self.subTest(card_field=element["field"]):
                    self.assertTrue(element["locked"])
            for element in reopened["templates"][template["id"]]["elements"]:
                with self.subTest(template_field=element["field"]):
                    self.assertTrue(element["locked"])
            for element in reopened_card["elements"]:
                with self.subTest(field=element["field"]):
                    self.assertFalse(core.move_element(element, 1, 0, reopened_card))
            shared = workspace.save_card_template(reopened, reopened_card, "跨廠商鎖定版型")
            destination = core.new_project()
            copied_card = workspace.card_from_template(destination, shared["id"])
            self.assertTrue(all(element["locked"] for element in copied_card["elements"]))

    def test_locked_object_cannot_change_layer_and_unlock_is_independent(self):
        card = core.new_card(core.default_templates()["compact-90x60"])
        logo = next(element for element in card["elements"] if element["field"] == "store_logo")
        original_order = [element["id"] for element in card["elements"]]

        class Flag:
            def get(self):return True

        class Editor:
            def __init__(self):
                self.card = card
                self.locked_var = Flag()
                self.snapshots = 0

            def element(self):return logo
            def _snapshot(self):self.snapshots += 1
            def refresh_elements(self):pass
            def draw_selection(self):pass
            def schedule_render(self):pass
            def schedule_save(self):pass

        editor = Editor()
        PriceCardApp.toggle_lock(editor)
        self.assertTrue(logo["locked"])
        self.assertEqual(editor.snapshots, 1)
        PriceCardApp.layer(editor, 1)
        self.assertEqual([element["id"] for element in card["elements"]], original_order)
        self.assertEqual(editor.snapshots, 1)

    def test_legacy_fixed_store_logo_is_unlocked_once_on_import(self):
        with tempfile.TemporaryDirectory() as folder:
            legacy = core.new_project()
            card = core.get_card(legacy)
            card["elements"] = [element for element in card["elements"]
                                if element["field"] != "corner_stripes"]
            logo = next(element for element in card["elements"] if element["field"] == "store_logo")
            logo["locked"] = True
            logo.pop("image_fit", None)
            logo["rect"] = core._legacy_store_rect(card["width_mm"], card["safe_margin_mm"])
            path = Path(folder) / "legacy.jyp"
            core.save_project(path, legacy)

            imported = core.load_project(path)
            imported_logo = next(element for element in core.get_card(imported)["elements"]
                                 if element["field"] == "store_logo")
            self.assertFalse(imported_logo["locked"])
            self.assertEqual(imported_logo["image_fit"], "stretch")
            self.assertTrue(any(element["field"] == "corner_stripes"
                                for element in core.get_card(imported)["elements"]))
            core.save_project(path, imported)
            reopened_logo = next(element for element in core.get_card(core.load_project(path))["elements"]
                                 if element["field"] == "store_logo")
            self.assertFalse(reopened_logo["locked"])
            self.assertEqual(reopened_logo["rect"], imported_logo["rect"])

    def test_custom_store_logo_without_stripes_keeps_user_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            project = core.new_project()
            card = core.get_card(project)
            card["elements"] = [element for element in card["elements"]
                                if element["field"] not in ("corner_stripes", "store_logo")]
            extra = core._elt("store_logo", core._legacy_store_rect(card["width_mm"], card["safe_margin_mm"]),
                              10, kind="image")
            extra["id"] = "custom-store-logo"
            extra["locked"] = True
            card["elements"].append(extra)
            path = Path(folder) / "custom.jyp"
            core.save_project(path, project)

            reopened = core.get_card(core.load_project(path))
            saved = next(element for element in reopened["elements"] if element["id"] == "custom-store-logo")
            self.assertTrue(saved["locked"])
            self.assertEqual(saved["rect"], extra["rect"])


if __name__ == "__main__":
    unittest.main()
