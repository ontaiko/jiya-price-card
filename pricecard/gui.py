"""Windows 桌面編輯介面；中央預覽與 PDF 使用同一套排版。"""

from __future__ import annotations

import copy
import ctypes
import math
import os
import sys
import time
import unicodedata
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser

import pypdfium2 as pdfium
from PIL import Image, ImageTk

from . import core
from .workspace import Workspace


def parse_number(value: str) -> float:
    """Accept common punctuation produced by Chinese input methods."""
    text = unicodedata.normalize("NFKC", value).strip()
    for mark in ("。", "﹒", "·", "，", ","):
        text = text.replace(mark, ".")
    number = float(text)
    if not math.isfinite(number):
        raise ValueError("請輸入有效數字")
    return number


def insert_numpad_ascii(event, allow_decimal=True):
    """Use Windows virtual key codes before an IME can change keypad text."""
    code = event.keycode if sys.platform == "win32" else None
    if code is not None and 96 <= code <= 105:
        char = str(code - 96)
    elif code == 110 or event.keysym in ("KP_Decimal", "KP_Separator"):
        if not allow_decimal:
            return "break"
        char = "."
    else:
        return None
    widget = event.widget
    if widget.selection_present():
        widget.delete("sel.first", "sel.last")
    widget.insert("insert", char)
    return "break"


class NumericInput:
    """Keep the IME away from focused number fields without changing text fields."""

    def __init__(self):
        self._previous_contexts = {}
        self._associate = None
        if sys.platform == "win32":
            try:
                self._imm32 = ctypes.WinDLL("imm32", use_last_error=True)
                self._associate = self._imm32.ImmAssociateContext
                self._associate.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
                self._associate.restype = ctypes.c_void_p
            except (OSError, AttributeError):
                self._associate = None

    @staticmethod
    def _normalise(text, allow_decimal):
        text = unicodedata.normalize("NFKC", text)
        if allow_decimal:
            for mark in ("。", "﹒", "·", "，"):
                text = text.replace(mark, ".")
        return text

    def bind(self, widget, allow_decimal=True):
        widget.bind("<KeyPress>", lambda event: insert_numpad_ascii(event, allow_decimal), add="+")
        widget.bind("<KeyRelease>", lambda event: self._normalise_widget(event.widget, allow_decimal), add="+")
        widget.bind("<FocusIn>", self._focus_in, add="+")
        widget.bind("<FocusOut>", lambda event: self._focus_out(event, allow_decimal), add="+")
        widget.bind("<Destroy>", self._focus_out, add="+")

    def _normalise_widget(self, widget, allow_decimal):
        value = widget.get()
        normalised = self._normalise(value, allow_decimal)
        if normalised == value:
            return
        cursor = widget.index(tk.INSERT)
        selection = None
        if widget.selection_present():
            selection = (widget.index("sel.first"), widget.index("sel.last"))
        widget.delete(0, tk.END)
        widget.insert(0, normalised)
        widget.icursor(len(self._normalise(value[:cursor], allow_decimal)))
        if selection is not None:
            start, end = selection
            widget.selection_range(len(self._normalise(value[:start], allow_decimal)),
                                   len(self._normalise(value[:end], allow_decimal)))

    def _focus_in(self, event):
        if self._associate is None:
            return
        widget = event.widget
        if widget not in self._previous_contexts:
            hwnd = widget.winfo_id()
            self._previous_contexts[widget] = (hwnd, self._associate(hwnd, None))

    def _focus_out(self, event, allow_decimal=True):
        if event.type != tk.EventType.Destroy:
            self._normalise_widget(event.widget, allow_decimal)
        if self._associate is None:
            return
        previous = self._previous_contexts.pop(event.widget, None)
        if previous is not None:
            hwnd, context = previous
            self._associate(hwnd, context)

    def restore_all(self):
        if self._associate is not None:
            for hwnd, previous in self._previous_contexts.values():
                self._associate(hwnd, previous)
        self._previous_contexts.clear()


class NumericFloatDialog(simpledialog.Dialog):
    def __init__(self, parent, title, prompt, initialvalue, minvalue, maxvalue):
        self.prompt = prompt
        self.initialvalue = initialvalue
        self.minvalue = minvalue
        self.maxvalue = maxvalue
        self.parsed = None
        self.numeric_input = parent.numeric_input
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text=self.prompt).pack(anchor="w", pady=(0, 7))
        self.entry = ttk.Entry(master, width=24)
        self.entry.pack(fill="x")
        self.entry.insert(0, f"{self.initialvalue:g}")
        self.entry.selection_range(0, "end")
        self.numeric_input.bind(self.entry)
        return self.entry

    def validate(self):
        try:
            value = parse_number(self.entry.get())
            if not self.minvalue <= value <= self.maxvalue:
                raise ValueError()
        except ValueError:
            messagebox.showerror("數值範圍", f"請輸入 {self.minvalue:g} 至 {self.maxvalue:g} 的數字。", parent=self)
            return False
        self.parsed = value
        return True

    def apply(self):
        self.result = self.parsed


class ElementChoiceDialog(simpledialog.Dialog):
    def __init__(self, parent, options):
        self.options = options
        super().__init__(parent, "新增方塊")

    def body(self, master):
        ttk.Label(master, text="選擇要新增的方塊種類：").pack(anchor="w", pady=(0, 7))
        self.choice = ttk.Combobox(master, values=self.options, state="readonly", width=26)
        self.choice.pack(fill="x")
        self.choice.current(0)
        return self.choice

    def apply(self):
        self.result = self.choice.get()


class ListChoiceDialog(simpledialog.Dialog):
    def __init__(self, parent, title, rows, caption):
        self.rows = rows
        self.caption = caption
        self.result = None
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text=self.caption).pack(anchor="w", pady=(0, 8))
        frame = ttk.Frame(master)
        frame.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(frame, width=58, height=min(18, max(6, len(self.rows))))
        self.listbox.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(frame, orient="vertical", command=self.listbox.yview)
        bar.pack(side="right", fill="y")
        self.listbox.configure(yscrollcommand=bar.set)
        for _, label in self.rows: self.listbox.insert("end", label)
        if self.rows: self.listbox.selection_set(0)
        self.listbox.bind("<Double-Button-1>", lambda _e: self.ok())
        return self.listbox

    def validate(self):
        if not self.listbox.curselection():
            messagebox.showinfo("選擇項目", "請先選擇一個項目。", parent=self)
            return False
        return True

    def apply(self):
        self.result = self.rows[self.listbox.curselection()[0]][0]


class ProjectManager(tk.Toplevel):
    def __init__(self, app, startup=False, create_immediately=False):
        super().__init__(app)
        self.app = app
        self.numeric_input = app.numeric_input
        self.startup = startup
        self.result = None
        self.title("選擇廠商專案")
        self.geometry("620x460")
        self.minsize(500, 360)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        main = ttk.Frame(self, padding=18);main.pack(fill="both", expand=True)
        ttk.Label(main, text="選擇廠商專案", font=("Microsoft JhengHei", 16, "bold")).pack(anchor="w")
        ttk.Label(main, text="每個廠商各自保存價格牌；列印清單可跨廠商使用。",
                  foreground="#666666").pack(anchor="w", pady=(4, 14))
        self.deleted = tk.BooleanVar(value=False)
        ttk.Checkbutton(main, text="顯示已刪除區", variable=self.deleted,
                        command=self.refresh).pack(anchor="w")
        self.tree = ttk.Treeview(main, columns=("name", "updated"), show="headings", selectmode="browse")
        self.tree.heading("name", text="廠商");self.tree.heading("updated", text="最後更新")
        self.tree.column("name", width=310);self.tree.column("updated", width=170)
        self.tree.pack(fill="both", expand=True, pady=8)
        self.tree.bind("<Double-Button-1>", lambda _e: self.open_selected())
        actions = ttk.Frame(main);actions.pack(fill="x", pady=(3, 0))
        for label, action in (("開啟", self.open_selected), ("新增廠商", self.create),
                              ("匯入 .jyp", self.import_file), ("重新命名", self.rename),
                              ("移至已刪除區／還原", self.toggle_archive)):
            ttk.Button(actions, text=label, command=action).pack(side="left", padx=(0, 5))
        ttk.Button(main, text="關閉", command=self.destroy).pack(anchor="e", pady=(9, 0))
        self.refresh()
        self.grab_set()
        self.lift()
        self.focus_force()
        if create_immediately:self.after(0, self.create)
        self.wait_window()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for record in sorted(self.app.workspace.records(self.deleted.get()), key=lambda x: x["name"].casefold()):
            self.tree.insert("", "end", iid=record["id"],
                             values=(record["name"], record.get("updated_at", "")[:16].replace("T", " ")))

    def selected_id(self):
        selected = self.tree.selection()
        return selected[0] if selected else None

    def open_selected(self):
        project_id = self.selected_id()
        if not project_id: return
        if self.deleted.get():
            messagebox.showinfo("廠商已刪除", "請先還原此廠商。", parent=self);return
        self.result = project_id
        self.destroy()

    def create(self):
        name = simpledialog.askstring("新增廠商", "廠商名稱：", parent=self)
        if not name: return
        card = self.app.choose_new_card(self)
        if card is None: return
        project, new_card = card
        try:
            project_id = self.app.workspace.create_project(name, project)
        except Exception as exc:
            messagebox.showerror("新增廠商", str(exc), parent=self);return
        self.result = project_id
        self.destroy()

    def import_file(self):
        filename = filedialog.askopenfilename(parent=self, title="匯入舊專案副本",
                                               filetypes=[("集雅社專案", "*.jyp")])
        if not filename:return
        initial = Path(filename).stem
        name = simpledialog.askstring("匯入廠商", "匯入後的廠商名稱：", initialvalue=initial, parent=self)
        if not name:return
        try:
            old = core.load_project(filename)
            with_queue = bool(old.get("queue")) and messagebox.askyesno(
                "匯入列印清單", "也匯入這份舊專案的列印清單嗎？\n預設只匯入價格牌。",
                default=messagebox.NO, parent=self)
            project_id = self.app.workspace.import_project(Path(filename), name, with_queue)
        except Exception as exc:
            messagebox.showerror("匯入專案", str(exc), parent=self);return
        self.result = project_id
        self.destroy()

    def rename(self):
        project_id = self.selected_id()
        if not project_id:return
        old = self.app.workspace.record(project_id)["name"]
        name = simpledialog.askstring("重新命名廠商", "廠商名稱：", initialvalue=old, parent=self)
        if not name:return
        try:self.app.workspace.rename_project(project_id, name)
        except Exception as exc:messagebox.showerror("重新命名", str(exc), parent=self);return
        self.refresh()

    def toggle_archive(self):
        project_id = self.selected_id()
        if not project_id:return
        try:
            if self.deleted.get():
                self.app.workspace.restore_project(project_id)
            elif messagebox.askyesno("移至已刪除區", "將此廠商移至已刪除區？\n列印清單中的項目會標示為不可列印，還原後可繼續使用。", parent=self):
                self.app.workspace.archive_project(project_id)
            else:return
        except Exception as exc:messagebox.showerror("廠商專案", str(exc), parent=self);return
        self.refresh()


class ScrolledFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg="#ffffff")
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas, padding=14)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))

    def scroll_wheel(self, delta):
        if delta:
            steps = max(1, round(abs(delta) / 120))
            self.canvas.yview_scroll(-steps if delta > 0 else steps, "units")


class PriceCardApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("集雅社價格牌產生器  •  v1.3.2")
        try:
            icon = str(core.resources() / "app.ico")
            self.iconbitmap(icon)
            self.iconbitmap(default=icon)
        except Exception:pass
        self.geometry("1480x900")
        self.minsize(1080, 680)
        if sys.platform == "win32":
            self.state("zoomed")
        self.numeric_input = NumericInput()
        self.option_add("*Font", "{Microsoft JhengHei} 10" if sys.platform == "win32" else "TkDefaultFont 10")
        self.style = ttk.Style(self)
        if "clam" in self.style.theme_names(): self.style.theme_use("clam")
        self.style.configure("Accent.TButton", foreground="#ffffff", background="#B70031", padding=(11, 8))
        self.style.map("Accent.TButton", background=[("active", "#910027")])
        self.style.configure("Tool.TButton", padding=(8, 8))
        self.style.configure("Pane.TLabelframe", padding=4)
        self.workspace = Workspace()
        self.project = core.new_project()
        self.project_id: str | None = None
        self.selected: str | None = None
        self.preview_image = None
        self.preview_scale = 1.0
        self.preview_origin = (0.0, 0.0)
        self.preview_pan = (0.0, 0.0)
        self.page_size_pt = None
        self.render_ratio = None
        self.pan_start = None
        self.render_job = None
        self.save_job = None
        self.undo_stack = []
        self.redo_stack = []
        self.drag_start = None
        self.drag_rect = None
        self.drag_corner = None
        self._loading = False
        self._loading_properties = False
        self._last_edit = (None, 0.0)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        try:
            old_project_id = self.workspace.migrate_legacy()
        except Exception as exc:
            messagebox.showerror("舊專案匯入", "舊資料未變更，請先檢查檔案：\n" + str(exc), parent=self)
            self.destroy();return
        if old_project_id:
            new_name = simpledialog.askstring("舊專案已匯入", "舊專案已複製保存。可以為這個廠商重新命名：",
                                              initialvalue="舊專案", parent=self)
            if new_name:
                try:self.workspace.rename_project(old_project_id, new_name)
                except Exception as exc:messagebox.showerror("廠商名稱", str(exc), parent=self)
        self.open_project(startup=True)

    @property
    def card(self): return core.get_card(self.project)

    def _build(self):
        self.configure(bg="#f3f4f6")
        self._make_menu()
        vendor = ttk.Frame(self, padding=(16, 8));vendor.pack(fill="x")
        ttk.Label(vendor, text="目前廠商：", font=("Microsoft JhengHei", 13, "bold")).pack(side="left")
        self.vendor_label = tk.StringVar(value="尚未選擇")
        ttk.Label(vendor, textvariable=self.vendor_label, font=("Microsoft JhengHei", 14, "bold"),
                  foreground="#B70031").pack(side="left", padx=(0, 18))
        ttk.Button(vendor, text="切換／管理廠商…", command=self.open_project,
                   style="Accent.TButton").pack(side="left")
        top = ttk.Frame(self, padding=(16, 12))
        top.pack(fill="x")
        ttk.Label(top, text="集雅社  /  價格牌產生器", font=("Microsoft JhengHei", 16, "bold")).pack(side="left", padx=(0, 18))
        ttk.Label(top, text="價格牌").pack(side="left")
        self.card_combo = ttk.Combobox(top, state="readonly", width=22)
        self.card_combo.pack(side="left", padx=(6, 9));self.card_combo.bind("<<ComboboxSelected>>", self._choose_card)
        ttk.Button(top, text="新增價格牌", command=self.new_card, style="Tool.TButton").pack(side="left", padx=2)
        ttk.Button(top, text="複製", command=self.duplicate_card, style="Tool.TButton").pack(side="left", padx=2)
        ttk.Button(top, text="刪除", command=self.delete_card, style="Tool.TButton").pack(side="left", padx=2)
        ttk.Button(top, text="調整尺寸", command=self.resize_card, style="Tool.TButton").pack(side="left", padx=2)
        ttk.Button(top, text="儲存專案", command=self.save_project, style="Tool.TButton").pack(side="right", padx=3)
        ttk.Button(top, text="匯出單張 PDF", command=self.export_one, style="Accent.TButton").pack(side="right", padx=3)
        ttk.Button(top, text="重做", command=self.redo, style="Tool.TButton").pack(side="right", padx=3)
        ttk.Button(top, text="復原", command=self.undo, style="Tool.TButton").pack(side="right", padx=3)

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        left = ttk.Frame(paned, width=290)
        paned.add(left, weight=2)
        self.left_scroll = ScrolledFrame(left);self.left_scroll.pack(fill="both", expand=True)
        middle = ttk.Frame(paned, width=680)
        paned.add(middle, weight=6)
        self._build_preview(middle)
        right = ttk.Frame(paned, width=340)
        paned.add(right, weight=3)
        self._build_right(right)
        self.bind_class("PriceCardSideWheel", "<MouseWheel>", self._route_mouse_wheel)
        self._bind_side_wheel(self.right_edit_scroll)
        self._bind_side_wheel(self.right_print_scroll)
        status = ttk.Frame(self, padding=(15, 6));status.pack(fill="x")
        self.status = tk.StringVar(value="選擇尺寸與版型，於左側填寫商品內容。")
        ttk.Label(status, textvariable=self.status).pack(side="left")
        ttk.Label(status, text="方向鍵 0.1 mm  •  Shift 方向鍵 1 mm  •  Ctrl+Z 復原", foreground="#666666").pack(side="right")
        self.bind_all("<Control-KeyPress>", self._control_shortcut, add="+")
        self.bind_all("<MouseWheel>", self._route_mouse_wheel, add="+")

    def _make_menu(self):
        bar = tk.Menu(self)
        filemenu = tk.Menu(bar, tearoff=0)
        for label, cmd in [
            ("新增廠商專案…", self.new_project), ("切換／管理廠商…", self.open_project),
            ("儲存專案", self.save_project), ("匯出專案備份…", self.save_project_as),
            ("匯入自訂版型…", self.import_template), ("匯出目前版型…", self.export_template),
            ("匯出單張 PDF…", self.export_one), ("匯出列印清單 PDF…", self.export_queue),
        ]: filemenu.add_command(label=label, command=cmd)
        bar.add_cascade(label="檔案", menu=filemenu)
        edit = tk.Menu(bar, tearoff=0)
        edit.add_command(label="復原 Ctrl+Z", command=self.undo)
        edit.add_command(label="重做 Ctrl+Y", command=self.redo)
        edit.add_command(label="另存自訂版型…", command=self.save_template)
        bar.add_cascade(label="編輯", menu=edit)
        helpmenu = tk.Menu(bar, tearoff=0)
        helpmenu.add_command(label="操作說明", command=self.show_help)
        bar.add_cascade(label="說明", menu=helpmenu)
        self.config(menu=bar)

    def _build_preview(self, parent):
        heading = ttk.Frame(parent, padding=(12, 10));heading.pack(fill="x")
        ttk.Label(heading, text="成品預覽", font=("Microsoft JhengHei", 13, "bold")).pack(side="left")
        self.size_label = tk.StringVar()
        ttk.Label(heading, textvariable=self.size_label, foreground="#656565").pack(side="left", padx=(12, 0))
        ttk.Button(heading, text="放大 ＋", command=lambda: self.zoom(1.2)).pack(side="right", padx=2)
        ttk.Button(heading, text="縮小 －", command=lambda: self.zoom(.83)).pack(side="right", padx=2)
        ttk.Button(heading, text="適合視窗", command=lambda: self.zoom(None)).pack(side="right", padx=2)
        self.canvas = tk.Canvas(parent, bg="#e8ebee", highlightthickness=0, cursor="arrow")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.schedule_render())
        self.canvas.bind("<Button-1>", self._mouse_down)
        self.canvas.bind("<B1-Motion>", self._mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._mouse_up)
        self.canvas.bind("<Motion>", self._mouse_hover)
        self.canvas.bind("<MouseWheel>", self._preview_wheel)
        self.canvas.bind("<ButtonPress-2>", self._pan_down)
        self.canvas.bind("<B2-Motion>", self._pan_drag)
        self.canvas.bind("<ButtonRelease-2>", self._pan_up)
        self.canvas.bind("<KeyPress>", self._key_move)
        self.canvas.configure(takefocus=1)
        self.warn_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.warn_var, foreground="#9b5622", padding=(10, 7), wraplength=630).pack(fill="x")

    def _build_right(self, parent):
        self.tabs = ttk.Notebook(parent)
        self.tabs.pack(fill="both", expand=True)
        edit_tab = ttk.Frame(self.tabs, padding=12)
        print_tab = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(edit_tab, text="版型與方塊")
        self.tabs.add(print_tab, text="列印清單")
        edit_scroll = ScrolledFrame(edit_tab)
        edit_scroll.pack(fill="both", expand=True)
        self._build_properties(edit_scroll.inner)
        print_scroll = ScrolledFrame(print_tab)
        print_scroll.pack(fill="both", expand=True)
        self._build_print(print_scroll.inner)
        self.right_edit_scroll = edit_scroll
        self.right_print_scroll = print_scroll

    def _section(self, parent, title):
        box = ttk.LabelFrame(parent, text=title, padding=10)
        box.pack(fill="x", pady=(0, 12))
        return box

    def _line(self, parent, label, var, width=24, numeric=False):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=9).pack(side="left")
        ent = ttk.Entry(row, textvariable=var, width=width)
        ent.pack(side="left", fill="x", expand=True)
        ent.bind("<Control-KeyPress>", self._control_shortcut)
        if numeric:
            self.numeric_input.bind(ent)
        return ent

    def _product_entry(self, parent, key, label):
        v = tk.StringVar()
        self.product_vars[key] = v
        v.trace_add("write", lambda *_a, k=key, variable=v: self._product_changed(k, variable.get()))
        return self._line(parent, label, v, numeric=key in ("old_price", "price") or key.endswith("_price"))

    def _product_text(self, parent, key, label, height=3):
        ttk.Label(parent, text=label).pack(anchor="w", pady=(5, 0))
        t = tk.Text(parent, height=height, wrap="word", undo=True, relief="solid", borderwidth=1,
                    highlightthickness=0, font=("Microsoft JhengHei", 10))
        t.pack(fill="x", pady=(3, 4))
        t.bind("<<Modified>>", lambda _e, k=key, widget=t: self._text_changed(k, widget))
        t.bind("<Control-KeyPress>", self._control_shortcut)
        self.text_widgets[key] = t
        return t

    def _build_product_form(self):
        for w in self.left_scroll.inner.winfo_children(): w.destroy()
        self.product_vars = {};self.text_widgets = {}
        parent = self.left_scroll.inner
        ttk.Label(parent, text="商品內容", font=("Microsoft JhengHei", 13, "bold")).pack(anchor="w", pady=(0, 10))
        brand = self._section(parent, "品牌")
        self.brand_var = tk.StringVar();self.product_vars["brand"] = self.brand_var
        self.brand_var.trace_add("write", lambda *_a: self._product_changed("brand", self.brand_var.get()))
        ttk.Label(brand, text="廠牌").pack(anchor="w")
        self.brand_picker = ttk.Combobox(brand, textvariable=self.brand_var,
                                         values=["", *core.BRAND_ASSETS.keys()], state="normal")
        self.brand_picker.pack(fill="x", pady=(3, 7))
        self.brand_mode = tk.StringVar();self.product_vars["brand_mode"] = self.brand_mode
        self.brand_mode.trace_add("write", lambda *_a: self._product_changed("brand_mode", self.brand_mode.get()))
        ttk.Combobox(brand, textvariable=self.brand_mode, values=["logo", "text", "hidden"], state="readonly").pack(fill="x")
        ttk.Label(brand, text="Logo／文字／隱藏", foreground="#666666").pack(anchor="w")
        self._product_entry(brand, "brand_text", "品牌文字")
        ttk.Button(brand, text="上傳自訂 Logo…", command=self.upload_brand).pack(anchor="w", pady=(5, 0))

        content = self._section(parent, "基本資料")
        self._product_entry(content, "name", "商品名稱")
        self._product_entry(content, "model", "型號")
        self._product_text(content, "features", "特色說明（每行一項）", 4)
        self._product_entry(content, "dimensions", "尺寸說明")
        price = self._section(parent, "價格")
        self._product_entry(price, "old_price", "原價")
        self._product_entry(price, "price", "售價")
        self._product_entry(price, "price_label", "價格標籤")
        if self.card["mode"] == "variants":
            variant = self._section(parent, "同系列多型號")
            for n in (1, 2):
                ttk.Label(variant, text=f"第 {n} 款", foreground="#B70031").pack(anchor="w", pady=(6, 0))
                self._product_entry(variant, f"variant_{n}_model", "型號")
                self._product_entry(variant, f"variant_{n}_desc", "補充說明")
                self._product_entry(variant, f"variant_{n}_price", "價格")
        if self.card["mode"] == "bundle":
            bundle = self._section(parent, "組合商品")
            self._product_text(bundle, "components", "構成商品（每行一項）", 4)
        self.custom_frame = self._section(parent, "自訂文字")
        for el in self.card["elements"]:
            if el["field"] == "custom_text":
                self._product_entry(self.custom_frame, "custom:" + el["id"], el.get("label", "自訂文字"))
        internal = self._section(parent, "內部紀錄（不列印）")
        self._product_entry(internal, "sku", "商品代碼")
        self._product_entry(internal, "location", "擺放位置")
        self._product_text(internal, "notes", "備註", 2)
        self._bind_side_wheel(self.left_scroll)

    def _build_properties(self, tab):
        ttk.Label(tab, text="點預覽選取；拖移方塊或四角縮放，方向鍵可微調", foreground="#656565", wraplength=300).pack(anchor="w")
        self.listbox = tk.Listbox(tab, height=10, exportselection=False, activestyle="dotbox")
        self.listbox.pack(fill="x", pady=8)
        self.listbox.bind("<<ListboxSelect>>", self._choose_element)
        buttons = ttk.Frame(tab);buttons.pack(fill="x")
        ttk.Button(buttons, text="新增方塊…", command=self.add_element).pack(side="left")
        ttk.Button(buttons, text="刪除", command=self.delete_element).pack(side="left", padx=3)
        ttk.Button(buttons, text="上移", command=lambda: self.layer(1)).pack(side="left", padx=2)
        ttk.Button(buttons, text="下移", command=lambda: self.layer(-1)).pack(side="left")
        self.selected_label = tk.StringVar(value="未選取方塊")
        ttk.Label(tab, textvariable=self.selected_label, font=("Microsoft JhengHei", 11, "bold")).pack(anchor="w", pady=(14, 4))
        grid = ttk.Frame(tab);grid.pack(fill="x")
        self.prop_vars = {}
        self.geometry_entries = []
        for pair in (("X", "Y"), ("寬", "高"), ("字級 pt",)):
            row = ttk.Frame(grid);row.pack(fill="x", pady=3)
            for label in pair:
                ttk.Label(row, text=label, width=8 if label != "字級 pt" else 9).pack(side="left")
                v = tk.StringVar();self.prop_vars[label] = v
                entry = ttk.Entry(row, textvariable=v, width=10)
                entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
                entry.bind("<Control-KeyPress>", self._control_shortcut)
                self.numeric_input.bind(entry)
                self.geometry_entries.append(entry)
                entry.bind("<Return>", self.apply_properties, add="+")
                entry.bind("<FocusOut>", self.apply_properties, add="+")
        colors = ttk.Frame(tab);colors.pack(fill="x", pady=(7, 2))
        foreground = ttk.Frame(colors);foreground.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Label(foreground, text="方塊顏色").pack(anchor="w")
        foreground_row = ttk.Frame(foreground);foreground_row.pack(fill="x")
        self.prop_vars["顏色"] = tk.StringVar()
        color_entry = ttk.Entry(foreground_row, textvariable=self.prop_vars["顏色"], width=8)
        color_entry.pack(side="left", fill="x", expand=True)
        color_entry.bind("<Control-KeyPress>", self._control_shortcut)
        color_entry.bind("<Return>", self.apply_properties, add="+")
        color_entry.bind("<FocusOut>", self.apply_properties, add="+")
        ttk.Button(foreground_row, text="選", width=3, command=self.pick_color).pack(side="left", padx=(2, 0))
        background = ttk.Frame(colors);background.pack(side="left", fill="x", expand=True)
        ttk.Label(background, text="文字背景色").pack(anchor="w")
        background_row = ttk.Frame(background);background_row.pack(fill="x")
        self.background_var = tk.StringVar()
        self.background_entry = ttk.Entry(background_row, textvariable=self.background_var, width=8)
        self.background_entry.pack(side="left", fill="x", expand=True)
        self.background_entry.bind("<Control-KeyPress>", self._control_shortcut)
        self.background_entry.bind("<Return>", self.apply_properties, add="+")
        self.background_entry.bind("<FocusOut>", self.apply_properties, add="+")
        self.background_picker = ttk.Button(background_row, text="選", width=3, command=self.pick_background_color)
        self.background_picker.pack(side="left", padx=(2, 0))
        self.background_clear = ttk.Button(background_row, text="×", width=2, command=self.clear_background)
        self.background_clear.pack(side="left", padx=(2, 0))
        self.bold_var = tk.BooleanVar(value=False)
        self.bold_check = ttk.Checkbutton(tab, text="粗體", variable=self.bold_var, command=self.apply_properties)
        self.bold_check.pack(anchor="w", pady=(6, 0))
        ttk.Label(tab, text="文字對齊").pack(anchor="w", pady=(6, 2))
        self.align_var = tk.StringVar()
        align_combo = ttk.Combobox(tab, textvariable=self.align_var, values=["left", "center", "right"], state="readonly")
        align_combo.pack(fill="x");align_combo.bind("<<ComboboxSelected>>", self.apply_properties)
        flags = ttk.Frame(tab);flags.pack(fill="x", pady=8)
        self.visible_var = tk.BooleanVar(value=True);self.locked_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(flags, text="顯示", variable=self.visible_var, command=self.apply_properties).pack(side="left")
        ttk.Checkbutton(flags, text="鎖定", variable=self.locked_var, command=self.toggle_lock).pack(side="left", padx=20)
        self.property_error = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.property_error, foreground="#B70031", wraplength=290).pack(anchor="w")
        alignrow = ttk.Frame(tab);alignrow.pack(fill="x", pady=8)
        ttk.Button(alignrow, text="水平置中", command=lambda: self.center_element("x")).pack(side="left", padx=2)
        ttk.Button(alignrow, text="垂直置中", command=lambda: self.center_element("y")).pack(side="left", padx=2)
        ttk.Separator(tab).pack(fill="x", pady=(12, 10))
        ttk.Button(tab, text="另存自訂版型…", command=self.save_template).pack(fill="x", pady=3)
        ttk.Button(tab, text="管理共用版型…", command=self.manage_templates).pack(fill="x", pady=3)
        ttk.Label(tab, text="設定會自動套用；另存後可供所有廠商使用。",
                  foreground="#777777", wraplength=285).pack(anchor="w", pady=5)

    def _build_print(self, tab):
        ttk.Label(tab, text="依清單順序合版；不同尺寸放得下時會共用同一頁。", foreground="#555555", wraplength=300).pack(anchor="w", pady=(0, 8))
        row = ttk.Frame(tab);row.pack(fill="x")
        ttk.Label(row, text="份數").pack(side="left")
        self.qty = tk.IntVar(value=1)
        qty_entry = tk.Spinbox(row, from_=1, to=1000, textvariable=self.qty, width=6)
        qty_entry.pack(side="left", padx=5)
        self.numeric_input.bind(qty_entry, allow_decimal=False)
        ttk.Button(row, text="加入目前價格牌", command=self.add_queue).pack(side="left", padx=5)
        self.queue_list = tk.Listbox(tab, height=12, exportselection=False)
        self.queue_list.pack(fill="x", pady=10)
        queue_actions = ttk.Frame(tab);queue_actions.pack(fill="x")
        ttk.Button(queue_actions, text="移除選取項目", command=self.remove_queue).pack(side="left")
        ttk.Button(queue_actions, text="清空全部", command=self.clear_queue).pack(side="right")
        opt = self._section(tab, "列印設定")
        self.paper = tk.StringVar(value="A4")
        self.orientation = tk.StringVar(value="自動")
        self.margin = tk.StringVar(value="5")
        self.gap = tk.StringVar(value="2")
        self.marks = tk.BooleanVar(value=True)
        for label, var, options in [("紙張", self.paper, ("A4", "A3")),
                                    ("方向", self.orientation, ("自動", "直式", "橫式"))]:
            ttk.Label(opt, text=label).pack(anchor="w")
            c = ttk.Combobox(opt, textvariable=var, values=options, state="readonly")
            c.pack(fill="x", pady=(2, 6));c.bind("<<ComboboxSelected>>", self.refresh_layout_label)
        margin_entry = self._line(opt, "頁邊距 mm", self.margin, numeric=True)
        gap_entry = self._line(opt, "牌間距 mm", self.gap, numeric=True)
        for entry in (margin_entry, gap_entry):
            entry.bind("<Return>", self.refresh_layout_label, add="+")
            entry.bind("<FocusOut>", self.refresh_layout_label, add="+")
        ttk.Checkbutton(opt, text="裁切線", variable=self.marks,
                        command=self.refresh_layout_label).pack(anchor="w", pady=4)
        self.layout_label = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.layout_label, foreground="#595959", wraplength=300).pack(anchor="w", pady=(0, 10))
        self.margin.trace_add("write", lambda *_args: self.refresh_layout_label())
        self.gap.trace_add("write", lambda *_args: self.refresh_layout_label())
        ttk.Button(tab, text="匯出列印清單 PDF…", command=self.export_queue,
                   style="Accent.TButton").pack(fill="x")
        ttk.Label(tab, text="請在 PDF 閱讀器選擇 100%／實際大小列印。",
                  foreground="#656565", wraplength=290).pack(anchor="w", pady=8)

    def _product_changed(self, key, value):
        if self._loading: return
        p = self.card["product"]
        current = p.get(key, "")
        if key.startswith("custom:"):
            current = p.setdefault("custom", {}).get(key[7:], "")
        elif key.startswith("variant_"):
            _, n, attr = key.split("_")
            attr = "description" if attr == "desc" else attr
            current = p.setdefault("variants", [{}, {}])[int(n) - 1].get(attr, "")
        if current == value: return
        if self._last_edit[0] != key or time.monotonic() - self._last_edit[1] > 1.0:
            self._snapshot()
        self._last_edit = (key, time.monotonic())
        if key.startswith("custom:"): p["custom"][key[7:]] = value
        elif key.startswith("variant_"):
            p["variants"][int(n) - 1][attr] = value
        else:
            p[key] = value
            if key == "brand":p["custom_logo"] = ""
        if key == "name":
            self.card["name"] = value or "未命名價格牌"
            self.refresh_combos()
        self.schedule_render()
        self.schedule_save()

    def _text_changed(self, key, widget):
        if not widget.edit_modified(): return
        widget.edit_modified(False)
        if self._loading: return
        self._product_changed(key, widget.get("1.0", "end-1c"))

    def _snapshot(self):
        self.undo_stack.append(copy.deepcopy(self.card))
        if len(self.undo_stack) > 70: self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _control_shortcut(self, event):
        # Windows IMEs may change keysym; virtual key codes still identify Z/Y/S.
        if event.widget.winfo_toplevel() is not self:
            return
        key = event.keysym.lower()
        code = event.keycode if sys.platform == "win32" else None
        if key == "z" or code == 90:
            if event.state & 0x0001: self.redo()
            else: self.undo()
            return "break"
        if key == "y" or code == 89:
            self.redo()
            return "break"
        if key == "s" or code == 83:
            self.save_project()
            return "break"

    def _route_mouse_wheel(self, event):
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return
        if widget is None or widget.winfo_toplevel() is not self:
            return
        areas = (self.left_scroll, self.right_edit_scroll, self.right_print_scroll)
        current = widget
        while current is not None:
            if current in areas:
                current.scroll_wheel(event.delta)
                return "break"
            parent_name = current.winfo_parent()
            try:
                current = current.nametowidget(parent_name) if parent_name else None
            except KeyError:
                return

    def _bind_side_wheel(self, widget):
        tags = widget.bindtags()
        if "PriceCardSideWheel" not in tags:
            widget.bindtags(("PriceCardSideWheel",) + tags)
        for child in widget.winfo_children():
            self._bind_side_wheel(child)

    def _replace_card(self, replacement):
        for index, c in enumerate(self.project["cards"]):
            if c["id"] == replacement["id"]:
                self.project["cards"][index] = replacement
                return

    def undo(self, _event=None):
        if not self.undo_stack: return
        self.redo_stack.append(copy.deepcopy(self.card))
        self._replace_card(self.undo_stack.pop())
        self.load_card();self.schedule_save()

    def redo(self, _event=None):
        if not self.redo_stack: return
        self.undo_stack.append(copy.deepcopy(self.card))
        self._replace_card(self.redo_stack.pop())
        self.load_card();self.schedule_save()

    def load_card(self):
        self._loading = True
        self._build_product_form()
        self.refresh_combos()
        p = self.card["product"]
        for key, var in self.product_vars.items():
            if key.startswith("custom:"): val = p.get("custom", {}).get(key[7:], "")
            elif key.startswith("variant_"):
                _, n, attr = key.split("_")
                val = p.get("variants", [{}, {}])[int(n) - 1].get("description" if attr == "desc" else attr, "")
            else: val = p.get(key, "")
            var.set(val)
        for key, widget in self.text_widgets.items():
            widget.delete("1.0", "end")
            widget.insert("1.0", p.get(key, ""))
            widget.edit_modified(False)
        pr = self.workspace.queue["print"]
        self.paper.set(pr.get("paper", "A4"));self.orientation.set(pr.get("orientation", "自動"))
        self.margin.set(str(pr.get("margin_mm", 5)));self.gap.set(str(pr.get("gap_mm", 2)))
        self.marks.set(bool(pr.get("crop_marks", True)))
        self._loading = False
        self._last_edit = (None, 0.0)
        self.refresh_elements()
        self.refresh_queue()
        if self.project_id:
            self.vendor_label.set(self.workspace.record(self.project_id)["name"])
        self.size_label.set(f"{self.card['width_mm']:g} × {self.card['height_mm']:g} mm  •  100% PDF")
        self.schedule_render()

    def refresh_combos(self):
        self.card_combo["values"] = [c["name"] + f"  ({c['id'][:4]})" for c in self.project["cards"]]
        idx = next(i for i, c in enumerate(self.project["cards"]) if c["id"] == self.project["current_id"])
        self.card_combo.current(idx)

    def refresh_elements(self):
        self.listbox.delete(0, "end")
        for el in self.card["elements"]:
            title = el.get("label") or core.FIELD_LABELS.get(el["field"], el["field"])
            self.listbox.insert("end", ("🔒 " if el.get("locked") else "   ") + title)
        selected = next((i for i, el in enumerate(self.card["elements"]) if el["id"] == self.selected), None)
        if selected is not None:
            self.listbox.selection_set(selected);self.listbox.see(selected)
            self._load_properties(self.card["elements"][selected])
        else:
            self.selected_label.set("未選取方塊")
            self.background_entry.configure(state="disabled")
            self.background_picker.configure(state="disabled")
            self.background_clear.configure(state="disabled")
            self.bold_check.configure(state="disabled")

    def _choose_element(self, _event=None):
        selected = self.listbox.curselection()
        if not selected: return
        el = self.card["elements"][selected[0]]
        self.selected = el["id"]
        self._load_properties(el)
        self.canvas.focus_set()
        self.draw_selection()

    def element(self):
        return next((el for el in self.card["elements"] if el["id"] == self.selected), None)

    def _load_properties(self, el):
        self._loading_properties = True
        self.selected_label.set(el.get("label") or core.FIELD_LABELS.get(el["field"], "方塊"))
        for key, value in zip(("X", "Y", "寬", "高"), el["rect"]):self.prop_vars[key].set(f"{value:g}")
        self.prop_vars["字級 pt"].set(f"{el.get('size', 10):g}")
        self.prop_vars["顏色"].set(el.get("color", "#121212"))
        self.background_var.set(el.get("fill") or "")
        self.bold_var.set(bool(el.get("bold", False)))
        text_state = "normal" if el.get("kind") == "text" else "disabled"
        self.background_entry.configure(state=text_state)
        self.background_picker.configure(state=text_state)
        self.background_clear.configure(state=text_state)
        self.bold_check.configure(state=text_state)
        self.align_var.set(el.get("align", "left"))
        self.visible_var.set(el.get("visible", True))
        self.locked_var.set(el.get("locked", False))
        for entry in self.geometry_entries:
            entry.configure(state="disabled" if el.get("locked") else "normal")
        self.property_error.set("")
        self._loading_properties = False

    def toggle_lock(self):
        el = self.element()
        if el is None:return
        locked = self.locked_var.get()
        if bool(el.get("locked")) == locked:return
        self._snapshot()
        el["locked"] = locked
        self.refresh_elements();self.draw_selection();self.schedule_render();self.schedule_save()

    def apply_properties(self, _event=None):
        if self._loading_properties or self._loading:return
        el = self.element()
        if el is None: return
        try:
            rect = [round(parse_number(self.prop_vars[k].get()), 2) for k in ("X", "Y", "寬", "高")]
            if el.get("locked"):rect = list(el["rect"])
            size = parse_number(self.prop_vars["字級 pt"].get())
            color = self.prop_vars["顏色"].get().strip()
            core._rgb(color)
            background = self.background_var.get().strip()
            if background and el.get("kind") == "text": core._rgb(background)
            if rect[2] <= 0 or rect[3] <= 0 or size < 4 or size > 100: raise ValueError()
            if rect[0] < 0 or rect[1] < 0 or rect[0] + rect[2] > self.card["width_mm"] or rect[1] + rect[3] > self.card["height_mm"]:
                raise ValueError()
        except Exception:
            self.property_error.set("請檢查座標、大小、字級及 #RRGGBB 色彩；方塊須在成品內。")
            return
        proposed = {"rect": rect, "size": size, "color": color, "align": self.align_var.get(),
                    "visible": self.visible_var.get()}
        if el.get("kind") == "text":
            proposed["bold"] = self.bold_var.get()
            proposed["fill"] = background or None
        if all(el.get(key) == value for key, value in proposed.items()):
            self.property_error.set("")
            return
        self._snapshot()
        el.update(proposed)
        self.property_error.set("")
        self.refresh_elements();self.schedule_render();self.schedule_save()

    def pick_color(self):
        result = colorchooser.askcolor(self.prop_vars["顏色"].get(), title="選取方塊顏色")
        if result[1]:
            self.prop_vars["顏色"].set(result[1].upper())
            self.apply_properties()

    def pick_background_color(self):
        el = self.element()
        if el is None or el.get("kind") != "text": return
        result = colorchooser.askcolor(self.background_var.get() or "#FFFFFF", title="選取文字背景色")
        if result[1]:
            self.background_var.set(result[1].upper())
            self.apply_properties()

    def clear_background(self):
        self.background_var.set("")
        self.apply_properties()

    def center_element(self, axis):
        el = self.element()
        if el is None or el.get("locked"):return
        self._snapshot(); r = el["rect"]
        n = 0 if axis == "x" else 1
        r[n] = round((self.card["width_mm" if n == 0 else "height_mm"] - r[n + 2]) / 2, 2)
        self._load_properties(el);self.schedule_render();self.schedule_save()

    def add_element(self):
        options = ("集雅社標誌", "右下五條裝飾", "品牌標誌", "商品名稱", "型號", "說明", "尺寸", "售價", "原價",
                   "價格標籤", "組合內容", "自訂文字", "圖片", "矩形", "分隔線")
        choice = ElementChoiceDialog(self, options).result
        if not choice: return
        field_map = {"集雅社標誌": "store_logo", "右下五條裝飾": "corner_stripes", "品牌標誌": "brand_logo", "商品名稱": "name", "型號": "model", "說明": "features", "尺寸": "dimensions",
                     "售價": "price_value", "原價": "old_price", "價格標籤": "price_label", "組合內容": "components", "自訂文字": "custom_text"}
        field = field_map.get(choice)
        key = "custom-" + uuid.uuid4().hex[:8]
        m = self.card["safe_margin_mm"]
        rect = [m, round(self.card["height_mm"] * .4, 1), min(54, self.card["width_mm"] - 2 * m), 9]
        el = core._elt(field or "asset_image", rect, 11)
        el["id"] = key;el["label"] = choice
        if field == "store_logo":el["image_fit"] = "stretch"
        if field in ("store_logo", "brand_logo"):
            el["kind"] = "image"
            el["rect"][3] = 7
            if field == "store_logo":
                el["image_fit"] = "stretch"
                template = core.default_templates().get(self.card["template_id"])
                if template:
                    el["rect"] = copy.deepcopy(next(item["rect"] for item in template["elements"] if item["field"] == "store_logo"))
        if field == "corner_stripes":
            el["kind"] = "stripes"
            el["color"] = core.COLORS["store"]
            el["rect"] = core._default_decoration_rect(float(self.card["width_mm"]), float(self.card["height_mm"]))
        if choice == "矩形":el.update({"kind": "rectangle", "field": "rectangle", "fill": None, "color": "#B70031"})
        if choice == "分隔線":el.update({"kind": "line", "field": "line", "rect": [m, rect[1], self.card["width_mm"] - 2 * m, .5], "color": "#B70031"})
        if choice == "圖片":
            filename = filedialog.askopenfilename(title="選取圖片", filetypes=[("圖片", "*.png *.jpg *.jpeg *.webp")])
            if not filename:return
            try: el["asset_key"] = core.attach_logo(self.project, filename, Path(filename).read_bytes())
            except Exception as exc:messagebox.showerror("圖片", str(exc));return
            el["kind"] = "image"
        self._snapshot()
        self.card["elements"].append(el)
        if field == "custom_text":self.card["product"].setdefault("custom", {})[key] = ""
        self.selected = key
        self.load_card();self.schedule_save()

    def delete_element(self):
        el = self.element()
        if el is None or el.get("locked"):return
        self._snapshot()
        self.card["elements"].remove(el)
        self.card["product"].get("custom", {}).pop(el["id"], None)
        self.selected = None
        self.load_card();self.schedule_save()

    def layer(self, direction):
        el = self.element()
        if el is None or el.get("locked"):return
        elements = self.card["elements"]
        i = elements.index(el);j = i + direction
        if not (0 <= j < len(elements)):return
        self._snapshot();elements[i], elements[j] = elements[j], elements[i]
        self.refresh_elements();self.schedule_render();self.schedule_save()

    def upload_brand(self):
        filename = filedialog.askopenfilename(title="上傳品牌 Logo", filetypes=[("圖片", "*.png *.jpg *.jpeg *.webp")])
        if not filename:return
        try:key = core.attach_logo(self.project, filename, Path(filename).read_bytes())
        except Exception as exc:messagebox.showerror("品牌 Logo", str(exc));return
        self._snapshot();self.card["product"]["custom_logo"] = key
        self.brand_mode.set("logo")
        self.schedule_render();self.schedule_save()

    def insert_snippet(self):
        i = self.snippet_combo.current()
        if i < 0:return
        widget = self.text_widgets["features"]
        current = widget.get("1.0", "end-1c")
        widget.insert("end", ("\n" if current else "") + self.project["snippets"][i]["text"])
        widget.edit_modified(True)

    def save_snippet(self):
        text = self.text_widgets["features"].get("1.0", "end-1c").strip()
        if not text:
            messagebox.showinfo("常用說明", "請先填寫說明文字。")
            return
        name = simpledialog.askstring("儲存常用說明", "這段說明的名稱：", parent=self)
        if not name:return
        self.project["snippets"].append({"name": name.strip(), "text": text})
        self.snippet_combo["values"] = [s["name"] for s in self.project["snippets"]]
        self.snippet_combo.current(len(self.project["snippets"]) - 1)
        self.schedule_save()

    def schedule_render(self):
        if self.render_job:self.after_cancel(self.render_job)
        self.render_job = self.after(140, self.render_preview)

    def _preview_ratio(self, scale):
        if self.page_size_pt is None:
            return None
        page_width, page_height = self.page_size_pt
        available_w = max(200, self.canvas.winfo_width() - 58)
        available_h = max(180, self.canvas.winfo_height() - 58)
        fit = min(available_w / page_width, available_h / page_height, 3.0)
        return max(.35, min(5.0, fit * scale))

    def render_preview(self):
        self.render_job = None
        try:
            blob, warnings = core.render_card_pdf(self.card, self.project)
            pdf = pdfium.PdfDocument(blob)
            p = pdf[0]
            page_width, page_height = p.get_size()
            self.page_size_pt = (page_width, page_height)
            ratio = self._preview_ratio(self.preview_scale)
            bitmap = p.render(scale=ratio)
            img = bitmap.to_pil().convert("RGB")
            self.preview_image = ImageTk.PhotoImage(img)
            self.view_px_per_mm = ratio * core.PT_PER_MM
            self.render_ratio = ratio
            self.preview_origin = ((self.canvas.winfo_width() - img.width) / 2 + self.preview_pan[0],
                                   (self.canvas.winfo_height() - img.height) / 2 + self.preview_pan[1])
            self.canvas.delete("all")
            x, y = self.preview_origin
            self.canvas.create_rectangle(x - 2, y - 2, x + img.width + 2, y + img.height + 2,
                                         fill="#ffffff", outline="#c9c9c9", width=1, tags="shadow")
            self.canvas.create_image(x, y, image=self.preview_image, anchor="nw", tags="page")
            self.draw_selection()
            self.warn_var.set("；".join(warnings[:3]) + ("…" if len(warnings) > 3 else "") if warnings else "")
            self.status.set("檢查提示：" + ("；".join(warnings[:2]) if warnings else "版面可輸出"))
            p.close();pdf.close()
        except Exception as exc:
            self.warn_var.set("預覽失敗：" + str(exc))

    def draw_selection(self):
        self.canvas.delete("selection")
        el = self.element()
        if el is None:return
        x, y, w, h = el["rect"]
        ox, oy = self.preview_origin
        sc = getattr(self, "view_px_per_mm", 1)
        left, top, right, bottom = ox + x * sc, oy + y * sc, ox + (x + w) * sc, oy + (y + h) * sc
        self.canvas.create_rectangle(left, top, right, bottom, outline="#1476c8", width=2,
                                     dash=(5, 2), tags="selection")
        if not el.get("locked"):
            for px, py in ((left, top), (right, top), (left, bottom), (right, bottom)):
                self.canvas.create_rectangle(px - 5, py - 5, px + 5, py + 5,
                                             fill="#ffffff", outline="#1476c8", width=2,
                                             tags="selection")

    def _handle_at(self, px, py):
        el = self.element()
        if el is None or el.get("locked") or not el.get("visible", True): return None
        x, y, w, h = el["rect"]
        ox, oy = self.preview_origin
        sc = getattr(self, "view_px_per_mm", 1)
        points = {"nw": (ox + x * sc, oy + y * sc),
                  "ne": (ox + (x + w) * sc, oy + y * sc),
                  "sw": (ox + x * sc, oy + (y + h) * sc),
                  "se": (ox + (x + w) * sc, oy + (y + h) * sc)}
        return next((name for name, (hx, hy) in points.items()
                     if abs(px - hx) <= 8 and abs(py - hy) <= 8), None)

    def _mouse_hover(self, event):
        if self.pan_start is not None:
            self.canvas.configure(cursor="fleur")
            return
        self.canvas.configure(cursor="crosshair" if self._handle_at(event.x, event.y) else "arrow")

    def _mouse_down(self, event):
        self.canvas.focus_set()
        corner = self._handle_at(event.x, event.y)
        if corner:
            self.drag_corner = corner
            self.drag_start = (event.x, event.y, copy.deepcopy(self.element()["rect"]))
            self.drag_snapshot_taken = False
            return
        sc = getattr(self, "view_px_per_mm", 1)
        px = (event.x - self.preview_origin[0]) / sc
        py = (event.y - self.preview_origin[1]) / sc
        self.selected = None
        candidates = list(reversed(self.card["elements"]))
        candidates.sort(key=lambda item: item.get("field") != "corner_stripes")
        for el in candidates:
            x, y, w, h = el["rect"]
            if el.get("visible", True) and x <= px <= x + w and y <= py <= y + h:
                self.selected = el["id"]
                break
        self.refresh_elements();self.draw_selection()
        el = self.element()
        self.drag_start = (event.x, event.y, copy.deepcopy(el["rect"])) if el and not el.get("locked") else None
        self.drag_corner = None
        self.drag_snapshot_taken = False

    def _mouse_drag(self, event):
        if not self.drag_start:return
        el = self.element()
        if el is None:return
        sx, sy, old = self.drag_start
        sc = getattr(self, "view_px_per_mm", 1)
        dx, dy = (event.x - sx) / sc, (event.y - sy) / sc
        if abs(dx) + abs(dy) < .12:return
        if self.drag_corner:
            new_rect = core.resized_rect(old, self.drag_corner, dx, dy, self.card)
            if new_rect == el["rect"]: return
            if not self.drag_snapshot_taken:
                self._snapshot();self.drag_snapshot_taken = True
            el["rect"] = new_rect
            self._load_properties(el)
            self.draw_selection()
            self.schedule_render()
            return
        if not self.drag_snapshot_taken:
            self._snapshot();self.drag_snapshot_taken = True
        el["rect"][:2] = old[:2]
        core.move_element(el, dx, dy, self.card)
        self._load_properties(el)
        self.draw_selection()
        self.schedule_render()

    def _mouse_up(self, _event):
        self.drag_start = None
        self.drag_corner = None
        if getattr(self, "drag_snapshot_taken", False):
            self.schedule_render();self.schedule_save()

    def _key_move(self, event):
        directions = {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}
        if event.keysym not in directions:return
        el = self.element()
        if el is None or el.get("locked"):return "break"
        amount = 1.0 if event.state & 0x0001 else .1
        dx, dy = directions[event.keysym]
        if self._last_edit[0] != "arrow" or time.monotonic() - self._last_edit[1] > .8:
            self._snapshot()
        self._last_edit = ("arrow", time.monotonic())
        if core.move_element(el, dx * amount, dy * amount, self.card):
            self._load_properties(el);self.draw_selection();self.schedule_render();self.schedule_save()
        return "break"

    def _preview_wheel(self, event):
        if event.delta:
            notches = max(1, round(abs(event.delta) / 120))
            factor = 1.2 ** (notches if event.delta > 0 else -notches)
            self.zoom(factor, (event.x, event.y))
        return "break"

    def _pan_down(self, event):
        self.pan_start = (event.x, event.y)
        self.canvas.configure(cursor="fleur")
        return "break"

    def _pan_drag(self, event):
        if self.pan_start is None:
            return "break"
        dx, dy = event.x - self.pan_start[0], event.y - self.pan_start[1]
        self.pan_start = (event.x, event.y)
        self.preview_pan = (self.preview_pan[0] + dx, self.preview_pan[1] + dy)
        self.preview_origin = (self.preview_origin[0] + dx, self.preview_origin[1] + dy)
        self.canvas.move("all", dx, dy)
        return "break"

    def _pan_up(self, _event):
        self.pan_start = None
        self.canvas.configure(cursor="arrow")
        self.schedule_render()
        return "break"

    def zoom(self, factor, anchor=None):
        if factor is None:
            self.preview_scale = 1.0
            self.preview_pan = (0.0, 0.0)
            fit_ratio = self._preview_ratio(1.0)
            if fit_ratio is not None:
                page_width, page_height = self.page_size_pt
                self.render_ratio = fit_ratio
                self.preview_origin = ((self.canvas.winfo_width() - page_width * fit_ratio) / 2,
                                       (self.canvas.winfo_height() - page_height * fit_ratio) / 2)
                self.view_px_per_mm = fit_ratio * core.PT_PER_MM
            self.schedule_render()
            return
        new_scale = max(.45, min(3.0, self.preview_scale * factor))
        old_ratio = self.render_ratio
        new_ratio = self._preview_ratio(new_scale)
        if old_ratio and new_ratio:
            if anchor is None:
                anchor = (self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)
            new_origin = (anchor[0] - (anchor[0] - self.preview_origin[0]) * new_ratio / old_ratio,
                          anchor[1] - (anchor[1] - self.preview_origin[1]) * new_ratio / old_ratio)
            page_width, page_height = self.page_size_pt
            centered = ((self.canvas.winfo_width() - page_width * new_ratio) / 2,
                        (self.canvas.winfo_height() - page_height * new_ratio) / 2)
            self.preview_pan = (new_origin[0] - centered[0], new_origin[1] - centered[1])
            self.preview_origin = new_origin
            self.render_ratio = new_ratio
            self.view_px_per_mm = new_ratio * core.PT_PER_MM
        self.preview_scale = new_scale
        self.schedule_render()

    def _choose_card(self, _event):
        index = self.card_combo.current()
        if index < 0:return
        self.project["current_id"] = self.project["cards"][index]["id"]
        self.selected = None;self.undo_stack.clear();self.redo_stack.clear()
        self.load_card()

    def resize_card(self):
        w = NumericFloatDialog(self, "成品寬度", "寬度 mm（40 至 420）：", self.card["width_mm"], 40, 420).result
        if w is None:return
        h = NumericFloatDialog(self, "成品高度", "高度 mm（30 至 420）：", self.card["height_mm"], 30, 420).result
        if h is None:return
        self._snapshot();self.card["width_mm"] = w;self.card["height_mm"] = h
        self.size_label.set(f"{w:g} × {h:g} mm  •  100% PDF")
        self.refresh_queue();self.schedule_render();self.schedule_save()

    def new_card(self):
        result = self.choose_new_card(self)
        if result is None:return
        draft, card = result
        self.project["assets"].update(draft["assets"])
        self.project["templates"].update(draft["templates"])
        self.project["cards"].append(card);self.project["current_id"] = card["id"]
        self.selected = None;self.undo_stack.clear();self.redo_stack.clear()
        self.load_card();self.schedule_save()

    def choose_new_card(self, parent):
        rows = [(key, f"內建｜{t['name']}  {t['width_mm']:g}×{t['height_mm']:g} mm")
                for key, t in core.default_templates().items()]
        rows += [(t["id"], f"自訂｜{t['name']}  {t['template']['width_mm']:g}×{t['template']['height_mm']:g} mm")
                 for t in self.workspace.active_templates()]
        rows.append(("blank", "空白價格牌｜自行指定尺寸"))
        choice = ListChoiceDialog(parent, "選擇預設版型", rows, "新增價格牌時選擇版型；現有價格牌可直接調整方塊與尺寸。").result
        if choice is None:return None
        draft = core.new_project()
        if choice == "blank":
            w = NumericFloatDialog(parent, "空白價格牌", "成品寬度 mm（40 至 420）：", 90, 40, 420).result
            if w is None:return None
            h = NumericFloatDialog(parent, "空白價格牌", "成品高度 mm（30 至 420）：", 60, 30, 420).result
            if h is None:return None
            template = {"id": "blank-" + uuid.uuid4().hex[:10], "name": f"空白 {w:g}×{h:g}",
                        "width_mm": w, "height_mm": h, "mode": "single",
                        "safe_margin_mm": 3, "elements": [], "builtin": False}
            draft["templates"][template["id"]] = template
            card = core.new_card(template)
        else:
            card = self.workspace.card_from_template(draft, choice)
        draft["cards"] = [card]
        draft["current_id"] = card["id"]
        return draft, card

    def delete_card(self):
        if len(self.project["cards"]) < 2:
            messagebox.showinfo("刪除價格牌", "專案至少保留一張價格牌。")
            return
        if not messagebox.askyesno("刪除價格牌", "刪除此張價格牌及其列印清單項目？"):
            return
        card_id = self.card["id"]
        self.project["cards"] = [c for c in self.project["cards"] if c["id"] != card_id]
        self.workspace.remove_card_from_queue(self.project_id, card_id)
        self.project["current_id"] = self.project["cards"][0]["id"]
        self.selected = None;self.undo_stack.clear();self.redo_stack.clear()
        self.load_card();self.schedule_save()

    def duplicate_card(self):
        card = copy.deepcopy(self.card)
        card["id"] = uuid.uuid4().hex[:12];card["name"] += " 副本"
        self.project["cards"].append(card);self.project["current_id"] = card["id"]
        self.selected = None;self.undo_stack.clear();self.redo_stack.clear()
        self.load_card();self.schedule_save()

    def new_project(self):
        if not self._save_current():return
        manager = ProjectManager(self, create_immediately=True)
        if manager.result:self._activate_project(manager.result)
        elif self.project_id and self.workspace.record(self.project_id).get("archived"):
            self.project_id = None;self.open_project(startup=True)

    def open_project(self, startup=False):
        if not startup and self.project_id and not self._save_current():return
        manager = ProjectManager(self, startup=startup)
        if manager.result:
            try:self._activate_project(manager.result)
            except Exception as exc:
                messagebox.showerror("開啟專案", str(exc), parent=self)
                if startup:self.destroy()
        elif startup:self.destroy()
        elif self.project_id:
            if self.workspace.record(self.project_id).get("archived"):
                self.project_id = None
                self.open_project(startup=True)
                return
            self.vendor_label.set(self.workspace.record(self.project_id)["name"])
            self.refresh_queue()

    def _activate_project(self, project_id):
        project = self.workspace.load_project(project_id)
        self.project = project;self.project_id = project_id
        self.undo_stack.clear();self.redo_stack.clear();self.selected = None
        self.deiconify()
        if sys.platform == "win32":self.state("zoomed")
        self.load_card();self.schedule_save()

    def save_project_as(self):
        filename = filedialog.asksaveasfilename(title="匯出專案備份", defaultextension=".jyp",
                                                 filetypes=[("集雅社專案", "*.jyp")])
        if filename:
            if not self._save_current():return
            try:core.save_project(Path(filename), copy.deepcopy(self.project))
            except Exception as exc:messagebox.showerror("匯出備份", str(exc));return
            self.status.set("專案備份已匯出：" + Path(filename).name)

    def save_project(self):
        if self._save_current():self.status.set("已儲存廠商專案：" + self.vendor_label.get())

    def _save_current(self):
        if not self.project_id:return True
        if self.save_job:
            self.after_cancel(self.save_job);self.save_job = None
        try:self.workspace.save_project(self.project_id, self.project)
        except Exception as exc:
            messagebox.showerror("儲存專案", str(exc), parent=self);return False
        return True

    def schedule_save(self):
        if self.save_job:self.after_cancel(self.save_job)
        self.save_job = self.after(1800, self._autosave)

    def _autosave(self):
        self.save_job = None
        if not self.project_id:return
        try:self.workspace.save_project(self.project_id, self.project)
        except Exception as exc:self.status.set("自動儲存未完成：" + str(exc))

    def save_template(self):
        name = simpledialog.askstring("另存自訂版型", "自訂版型名稱：", initialvalue="我的「" + self.card["mode"] + "」版型", parent=self)
        if not name:return
        try:self.workspace.save_card_template(self.project, self.card, name)
        except Exception as exc:messagebox.showerror("版型", str(exc));return
        self.schedule_save()
        self.status.set("已儲存自訂版型：" + name)

    def manage_templates(self):
        entries = self.workspace.templates["templates"]
        if not entries:
            messagebox.showinfo("共用版型", "目前沒有自訂版型。可以將目前價格牌另存為新版型。", parent=self)
            return
        rows = [(entry["id"], ("已刪除｜" if entry.get("archived") else "可使用｜") + entry["name"])
                for entry in entries]
        chosen = ListChoiceDialog(self, "管理共用版型", rows, "選擇要重新命名、移至已刪除區或還原的版型。").result
        if chosen is None:return
        entry = next(item for item in entries if item["id"] == chosen)
        actions = [("rename", "重新命名"),
                   ("restore" if entry.get("archived") else "archive",
                    "還原" if entry.get("archived") else "移至已刪除區")]
        action = ListChoiceDialog(self, "版型操作", actions, entry["name"]).result
        if action is None:return
        try:
            if action == "rename":
                name = simpledialog.askstring("重新命名版型", "新版型名稱：", initialvalue=entry["name"], parent=self)
                if name:self.workspace.rename_template(chosen, name)
            elif action == "archive":
                if messagebox.askyesno("移至已刪除區", "將此版型移至已刪除區？已建立的價格牌不受影響。", parent=self):
                    self.workspace.archive_template(chosen, True)
            else:self.workspace.archive_template(chosen, False)
        except Exception as exc:messagebox.showerror("共用版型", str(exc), parent=self)

    def export_template(self):
        source = core.all_templates(self.project).get(self.card["template_id"])
        if source is None:return
        filename = filedialog.asksaveasfilename(title="匯出版型", defaultextension=".jyt", filetypes=[("集雅社版型", "*.jyt")])
        if not filename:return
        import json
        template = {**source, "width_mm": self.card["width_mm"], "height_mm": self.card["height_mm"],
                    "safe_margin_mm": self.card["safe_margin_mm"], "elements": self.card["elements"], "builtin": False}
        keys = {el.get("asset_key") for el in template["elements"] if el.get("asset_key")}
        assets = {k: v for k, v in self.project["assets"].items() if k in keys}
        Path(filename).write_text(json.dumps({"version": 1, "template": template, "assets": assets}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.status.set("版型已匯出")

    def import_template(self):
        filename = filedialog.askopenfilename(title="匯入版型", filetypes=[("集雅社版型", "*.jyt")])
        if not filename:return
        import json
        try:
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
            t = data["template"]
            if data["version"] != 1 or not isinstance(t["elements"], list) or not t["name"]:
                raise ValueError("版型格式不正確")
            if not 40 <= float(t["width_mm"]) <= 420 or not 30 <= float(t["height_mm"]) <= 420:
                raise ValueError("版型尺寸超出範圍")
        except Exception as exc:messagebox.showerror("匯入版型", str(exc));return
        try:
            core.upgrade_visual_elements(t)
            entry = self.workspace.add_template(t, data.get("assets", {}))
        except Exception as exc:messagebox.showerror("匯入版型", str(exc));return
        self.status.set("已匯入版型：" + entry["name"])

    def _confirm_warnings(self, warnings):
        if not warnings:return True
        return messagebox.askyesno("輸出前檢查", "偵測到以下提示：\n\n" + "\n".join(warnings[:12]) + "\n\n仍要輸出 PDF 嗎？")

    def export_one(self):
        filename = filedialog.asksaveasfilename(title="輸出單張實際尺寸 PDF", defaultextension=".pdf",
                                                 initialfile=self.card["name"].replace("/", "_") + ".pdf",
                                                 filetypes=[("PDF", "*.pdf")])
        if not filename:return
        try:
            _blob, warnings = core.render_card_pdf(self.card, self.project)
            if not self._confirm_warnings(warnings):return
            core.export_single(filename, self.card, self.project)
        except Exception as exc:messagebox.showerror("匯出 PDF", str(exc));return
        self._export_finished(filename)

    def refresh_queue(self):
        self.queue_list.delete(0, "end")
        for item in self._resolved_queue(True):
            card = item["card"]
            name = card["name"] if card else item["card_id"] or "未知價格牌"
            detail = f"{card['width_mm']:g}×{card['height_mm']:g} mm" if card else item["reason"]
            self.queue_list.insert("end", f"{item['vendor']}｜{name}  ·  {detail}  ·  {item['qty']} 張"
                                   + (f"【不可列印：{item['reason']}】" if item["reason"] else ""))
        self.refresh_layout_label()

    def _resolved_queue(self, allow_unavailable=False):
        return self.workspace.resolve_queue(allow_unavailable, self.project_id, self.project)

    def _queued_cards(self):
        cards = []
        for item in self._resolved_queue():
            if not 1 <= item["qty"] <= 1000:raise ValueError("份數須為 1 至 1000")
            cards.extend([item["card"]] * item["qty"])
        if len(cards) > 1000: raise ValueError("每次最多輸出 1000 張價格牌")
        return cards

    def add_queue(self):
        try:qty = int(self.qty.get());assert 1 <= qty <= 1000
        except Exception:messagebox.showwarning("份數", "請輸入 1 至 1000 張。");return
        try:self.workspace.add_queue_item(self.project_id, self.card["id"], qty)
        except Exception as exc:messagebox.showerror("列印清單", str(exc));return
        self.refresh_queue();self.tabs.select(1)

    def remove_queue(self):
        selected = self.queue_list.curselection()
        if not selected:return
        try:self.workspace.remove_queue_item(selected[0])
        except Exception as exc:messagebox.showerror("列印清單", str(exc));return
        self.refresh_queue()

    def clear_queue(self):
        if not self.workspace.queue["items"]:return
        if not messagebox.askyesno("清空列印清單", "清空全部廠商的列印清單？", parent=self):return
        try:self.workspace.clear_queue()
        except Exception as exc:messagebox.showerror("列印清單", str(exc));return
        self.refresh_queue()

    def _print_settings(self):
        return {"paper": self.paper.get(), "orientation": self.orientation.get(),
                "margin_mm": parse_number(self.margin.get()), "gap_mm": parse_number(self.gap.get()),
                "crop_marks": self.marks.get()}

    def refresh_layout_label(self, _event=None):
        try:
            if self.workspace.queue["items"]:
                cards = self._queued_cards()
                lo = core.plan_sheet(cards, self.paper.get(), self.orientation.get(),
                                     parse_number(self.margin.get()), parse_number(self.gap.get()))
                self.layout_label.set(f"列印清單預估：{len(cards)} 張，{self.paper.get()}{lo['orientation']}，共 {len(lo['pages'])} 頁")
            else:
                lo = core.layout_for(float(self.card["width_mm"]), float(self.card["height_mm"]),
                                     self.paper.get(), self.orientation.get(), parse_number(self.margin.get()), parse_number(self.gap.get()))
                self.layout_label.set(f"目前尺寸參考：{lo['orientation']}，每頁 {lo['cols']} 欄 × {lo['rows']} 列，最多 {lo['capacity']} 張")
            if not self._loading:self.workspace.save_print_settings(self._print_settings())
        except Exception as exc:self.layout_label.set(str(exc))

    def export_queue(self):
        if not self.workspace.queue["items"]:
            messagebox.showinfo("列印清單", "請先將價格牌加入列印清單。")
            return
        try:
            settings = self._print_settings()
            core.plan_sheet(self._queued_cards(), settings["paper"], settings["orientation"],
                            settings["margin_mm"], settings["gap_mm"])
        except Exception as exc:messagebox.showerror("列印設定", str(exc));return
        filename = filedialog.asksaveasfilename(title="匯出整頁列印 PDF", defaultextension=".pdf",
                                                 initialfile="集雅社價格牌列印.pdf", filetypes=[("PDF", "*.pdf")])
        if not filename:return
        if not self._save_current():return
        try:
            warnings = []
            resolved = self._resolved_queue()
            for item in resolved:
                _blob, problem = core.render_card_pdf(item["card"], item["project"])
                warnings.extend(problem)
            if not self._confirm_warnings(list(dict.fromkeys(warnings))):return
            pages, _ = core.export_sheet_multi(filename, resolved, settings)
        except Exception as exc:messagebox.showerror("匯出 PDF", str(exc));return
        self.workspace.save_print_settings(settings)
        self._export_finished(filename, pages)

    def _export_finished(self, filename, pages=None):
        suffix = f"（{pages} 頁）" if pages else ""
        self.status.set("PDF 已輸出" + suffix + "：" + Path(filename).name)
        if messagebox.askyesno("PDF 已輸出", "已依實際尺寸產生 PDF" + suffix + "。\n要開啟 PDF 進行列印嗎？"):
            try:
                if sys.platform == "win32":os.startfile(filename)
                elif sys.platform == "darwin":os.system("open " + repr(filename))
                else:os.system("xdg-open " + repr(filename))
            except Exception as exc:messagebox.showwarning("開啟 PDF", str(exc))

    def show_help(self):
        messagebox.showinfo("操作說明", "1. 開啟廠商專案，新增價格牌時選擇版型，於左側輸入內容。\n"
                            "2. 在預覽點選方塊，拖移方塊可移動，拖移四角可調整大小。\n"
                            "3. 左右欄可用滾輪捲動；預覽滾輪縮放，中鍵拖曳平移。\n"
                            "4. 右側可設定座標、粗體與顏色；數值欄可直接用右側數字鍵盤輸入。\n"
                            "5. 專案會自動儲存；另存共用版型後可供所有廠商使用。跨廠商列印清單可一起匯出 PDF。\n"
                            "Ctrl+Z 復原、Ctrl+Y 或 Ctrl+Shift+Z 重做；上方亦有按鈕。\n"
                            "列印時請選擇 100%／實際大小。示範內容不代表現價。")

    def on_close(self):
        if self.save_job:self.after_cancel(self.save_job)
        if not self._save_current():return
        self.numeric_input.restore_all()
        self.destroy()


def main():
    PriceCardApp().mainloop()


if __name__ == "__main__": main()
