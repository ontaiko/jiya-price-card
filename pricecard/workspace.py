"""廠商專案、共用版型及跨廠商列印清單的本機資料庫。"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import core


def app_folder() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home()) / "JiYaPriceCard"


def _read(path: Path, fallback: dict) -> dict:
    if not path.exists():
        return copy.deepcopy(fallback)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError(f"資料格式不正確：{path.name}")
    return value


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class Workspace:
    def __init__(self, root: Path | None = None):
        self.root = root or app_folder()
        self.projects_dir = self.root / "projects"
        self.deleted_dir = self.projects_dir / "deleted"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.deleted_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "library.json"
        self.templates_path = self.root / "templates.json"
        self.queue_path = self.root / "print_queue.json"
        self.index = _read(self.index_path, {"version": 1, "projects": [], "legacy_migrated": False})
        self.templates = _read(self.templates_path, {"version": 1, "templates": []})
        self.queue = _read(self.queue_path, {"version": 1, "items": [],
                                             "print": copy.deepcopy(core.new_project()["print"])})
        if not isinstance(self.index.get("projects"), list) or not isinstance(self.templates.get("templates"), list) or not isinstance(self.queue.get("items"), list):
            raise ValueError("專案庫資料格式不正確")

    def records(self, archived: bool = False) -> list[dict]:
        return [record for record in self.index["projects"] if bool(record.get("archived")) == archived]

    def record(self, project_id: str) -> dict:
        return next(record for record in self.index["projects"] if record["id"] == project_id)

    def project_path(self, project_id: str) -> Path:
        record = self.record(project_id)
        folder = self.deleted_dir if record.get("archived") else self.projects_dir
        return folder / (project_id + ".jyp")

    def _name(self, name: str, except_id: str | None = None) -> str:
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("廠商名稱須為 1 至 80 個字")
        if any(record["name"].casefold() == name.casefold() and record["id"] != except_id
               for record in self.index["projects"]):
            raise ValueError("廠商名稱已存在，請使用其他名稱")
        return name

    def load_project(self, project_id: str) -> dict:
        return core.load_project(self.project_path(project_id))

    def create_project(self, name: str, project: dict) -> str:
        name = self._name(name)
        project_id = uuid.uuid4().hex
        project = copy.deepcopy(project)
        project["vendor_id"] = project_id
        project["vendor_name"] = name
        project["queue"] = []
        core.save_project(self.projects_dir / (project_id + ".jyp"), project)
        self.index["projects"].append({"id": project_id, "name": name, "archived": False,
                                         "updated_at": datetime.now(timezone.utc).isoformat()})
        _write(self.index_path, self.index)
        return project_id

    def save_project(self, project_id: str, project: dict) -> None:
        record = self.record(project_id)
        if record.get("archived"):
            raise ValueError("已刪除的廠商不能儲存；請先還原")
        project["vendor_id"] = project_id
        project["vendor_name"] = record["name"]
        project["queue"] = []
        core.save_project(self.project_path(project_id), project)
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write(self.index_path, self.index)

    def rename_project(self, project_id: str, name: str) -> None:
        name = self._name(name, project_id)
        project = self.load_project(project_id)
        project["vendor_name"] = name
        core.save_project(self.project_path(project_id), project)
        self.record(project_id)["name"] = name
        _write(self.index_path, self.index)

    def archive_project(self, project_id: str) -> None:
        record = self.record(project_id)
        if record.get("archived"): return
        source = self.project_path(project_id)
        target = self.deleted_dir / source.name
        source.replace(target)
        record["archived"] = True
        try: _write(self.index_path, self.index)
        except Exception:
            record["archived"] = False
            target.replace(source)
            raise

    def restore_project(self, project_id: str) -> None:
        record = self.record(project_id)
        if not record.get("archived"): return
        source = self.project_path(project_id)
        target = self.projects_dir / source.name
        source.replace(target)
        record["archived"] = False
        try: _write(self.index_path, self.index)
        except Exception:
            record["archived"] = True
            target.replace(source)
            raise

    def active_templates(self) -> list[dict]:
        return [entry for entry in self.templates["templates"] if not entry.get("archived")]

    def _template_name(self, name: str, except_id: str | None = None) -> str:
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("版型名稱須為 1 至 80 個字")
        names = [t["name"] for t in core.default_templates().values()]
        names += [entry["name"] for entry in self.templates["templates"] if entry["id"] != except_id]
        if name.casefold() in (item.casefold() for item in names):
            raise ValueError("版型名稱已存在，請使用其他名稱")
        return name

    def add_template(self, template: dict, assets: dict, name: str | None = None,
                     deduplicate: bool = False) -> dict:
        template = copy.deepcopy(template)
        assets = copy.deepcopy(assets)
        fingerprint = hashlib.sha256(json.dumps({"template": template, "assets": assets},
                                               sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        if deduplicate:
            existing = next((entry for entry in self.templates["templates"] if entry.get("fingerprint") == fingerprint), None)
            if existing: return existing
        base_name = (name or template.get("name") or "自訂版型").strip()
        candidate = base_name
        suffix = 2
        while True:
            try:
                candidate = self._template_name(candidate)
                break
            except ValueError as exc:
                if "已存在" not in str(exc): raise
                candidate = f"{base_name} ({suffix})"
                suffix += 1
        template_id = "custom-" + uuid.uuid4().hex[:12]
        template.update({"id": template_id, "name": candidate, "builtin": False})
        entry = {"id": template_id, "name": candidate, "template": template,
                 "assets": assets, "archived": False, "fingerprint": fingerprint}
        self.templates["templates"].append(entry)
        _write(self.templates_path, self.templates)
        return entry

    def save_card_template(self, project: dict, card: dict, name: str) -> dict:
        name = self._template_name(name)
        template = {key: copy.deepcopy(card[key]) for key in
                    ("width_mm", "height_mm", "mode", "safe_margin_mm", "elements")}
        template["name"] = name
        keys = {el.get("asset_key") for el in template["elements"] if el.get("asset_key")}
        assets = {key: project["assets"][key] for key in keys if key in project["assets"]}
        entry = self.add_template(template, assets, name)
        project["templates"][entry["id"]] = copy.deepcopy(entry["template"])
        card["template_id"] = entry["id"]
        return entry

    def rename_template(self, template_id: str, name: str) -> None:
        name = self._template_name(name, template_id)
        entry = next(item for item in self.templates["templates"] if item["id"] == template_id)
        entry["name"] = entry["template"]["name"] = name
        _write(self.templates_path, self.templates)

    def archive_template(self, template_id: str, archived: bool) -> None:
        entry = next(item for item in self.templates["templates"] if item["id"] == template_id)
        entry["archived"] = archived
        _write(self.templates_path, self.templates)

    def card_from_template(self, project: dict, template_id: str) -> dict:
        builtin = core.default_templates().get(template_id)
        if builtin:
            return core.new_card(builtin)
        entry = next(item for item in self.active_templates() if item["id"] == template_id)
        template = copy.deepcopy(entry["template"])
        remap = {}
        for key, asset in entry["assets"].items():
            new_key = "upload-" + uuid.uuid4().hex[:12]
            project["assets"][new_key] = copy.deepcopy(asset)
            remap[key] = new_key
        for element in template["elements"]:
            key = element.get("asset_key")
            if key in remap: element["asset_key"] = remap[key]
        project["templates"][template_id] = copy.deepcopy(template)
        return core.new_card(template)

    def import_legacy_templates(self, project: dict) -> None:
        for template in project.get("templates", {}).values():
            if template.get("builtin"): continue
            keys = {el.get("asset_key") for el in template.get("elements", []) if el.get("asset_key")}
            assets = {key: project["assets"][key] for key in keys if key in project.get("assets", {})}
            self.add_template(template, assets, deduplicate=True)

    def migrate_legacy(self) -> str | None:
        if self.index.get("legacy_migrated"): return None
        legacy = self.root / "autosave.jyp"
        imported = None
        if legacy.exists():
            project = core.load_project(legacy)
            name = "舊專案"
            suffix = 2
            while any(record["name"].casefold() == name.casefold() for record in self.index["projects"]):
                name = f"舊專案 ({suffix})"; suffix += 1
            self.import_legacy_templates(project)
            old_queue = copy.deepcopy(project.get("queue", []))
            imported = self.create_project(name, project)
            self._append_legacy_queue(imported, old_queue)
            self.queue["print"] = copy.deepcopy(project.get("print", self.queue["print"]))
            _write(self.queue_path, self.queue)
        self.index["legacy_migrated"] = True
        _write(self.index_path, self.index)
        return imported

    def import_project(self, path: Path, name: str, include_queue: bool = False) -> str:
        project = core.load_project(path)
        self.import_legacy_templates(project)
        old_queue = copy.deepcopy(project.get("queue", []))
        project_id = self.create_project(name, project)
        if include_queue: self._append_legacy_queue(project_id, old_queue)
        return project_id

    def _append_legacy_queue(self, project_id: str, items: list[dict]) -> None:
        project = self.load_project(project_id)
        card_ids = {card["id"] for card in project["cards"]}
        for item in items:
            if item.get("card_id") in card_ids and 1 <= int(item.get("qty", 0)) <= 1000:
                self.queue["items"].append({"project_id": project_id, "card_id": item["card_id"],
                                             "qty": int(item["qty"])})
        _write(self.queue_path, self.queue)

    def add_queue_item(self, project_id: str, card_id: str, qty: int) -> None:
        self.queue["items"].append({"project_id": project_id, "card_id": card_id, "qty": qty})
        _write(self.queue_path, self.queue)

    def remove_queue_item(self, index: int) -> None:
        self.queue["items"].pop(index)
        _write(self.queue_path, self.queue)

    def remove_card_from_queue(self, project_id: str, card_id: str) -> None:
        self.queue["items"] = [item for item in self.queue["items"]
                               if (item["project_id"], item["card_id"]) != (project_id, card_id)]
        _write(self.queue_path, self.queue)

    def clear_queue(self) -> None:
        self.queue["items"] = []
        _write(self.queue_path, self.queue)

    def save_print_settings(self, settings: dict) -> None:
        self.queue["print"] = copy.deepcopy(settings)
        _write(self.queue_path, self.queue)

    def resolve_queue(self, allow_unavailable: bool = False,
                      current_project_id: str | None = None,
                      current_project: dict | None = None) -> list[dict]:
        projects = {}
        resolved = []
        for item in self.queue["items"]:
            record = next((r for r in self.index["projects"] if r["id"] == item.get("project_id")), None)
            label = record["name"] if record else "未知廠商"
            reason = "廠商已刪除" if record and record.get("archived") else ""
            if not record: reason = "找不到廠商"
            project = None
            if record and not reason:
                try:
                    if record["id"] not in projects:
                        projects[record["id"]] = (current_project if record["id"] == current_project_id
                                                  and current_project is not None else self.load_project(record["id"]))
                    project = projects[record["id"]]
                except Exception:
                    reason = "無法讀取廠商專案"
            card = next((c for c in project["cards"] if c["id"] == item.get("card_id")), None) if project else None
            if not reason and not card: reason = "找不到價格牌"
            result = {"project_id": item.get("project_id"), "card_id": item.get("card_id"),
                      "vendor": label, "qty": int(item.get("qty", 0)), "project": project,
                      "card": card, "reason": reason}
            resolved.append(result)
        if not allow_unavailable:
            bad = [item for item in resolved if item["reason"]]
            if bad:
                raise ValueError("列印清單含不可列印項目：" + "、".join(f"{item['vendor']}（{item['reason']}）" for item in bad[:5]))
        return resolved
