"""
SMD 配置设定参数编辑器
功能：管理不同界面（绘制、全局时间、手动配置、掉落筛选、脚本编辑等）下的设定参数配置。
支持新建、编辑、删除设定参数，拖放排序，保存/加载 JSON 配置文件。
"""

import os
import sys
import json
import time
import tkinter as tk
import ctypes
from tkinter import ttk, messagebox

# 基础目录（兼容 PyInstaller 打包）
if getattr(sys, 'frozen', False):
    _BASE_DIR = getattr(sys, '_MEIPASS', os.path.join(os.path.dirname(sys.executable), '_internal'))
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 用户数据目录（保存配置等可写操作，打包时为 exe 同级目录）
_DATA_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))

# SMD 左侧导航的标签页列表（按顺序）
SMD_TABS = [
    {"key": "draw", "name": "绘制"},
    {"key": "player", "name": "Player"},
    {"key": "aim", "name": "自瞄类"},
    {"key": "global_time", "name": "全局时间"},
    {"key": "manual", "name": "手动配置"},
    {"key": "bounty", "name": "悬赏"},
    {"key": "rogue", "name": "肉鸽-4级"},
    {"key": "nuclear", "name": "核电-高峰"},
    {"key": "drop_filter", "name": "挑落筛选"},
    {"key": "script_edit", "name": "脚本编辑", "has_script_selector": True},
    {"key": "no_action", "name": "无动作功能"},
]

# 类型与设置方式的中文映射
TYPE_MAP = {
    "toggle": "蓝色开关",
    "check_toggle": "勾选开关",
    "round_slider": "圆形滑条",
    "text": "文本",
    "dropdown": "下拉选项",
    "action": "按钮",
    "special": "特殊操作",
}
TYPE_MAP_REVERSE = {v: k for k, v in TYPE_MAP.items()}

METHOD_MAP = {
    "click": "点击",
    "ctrl_click": "Ctrl+点击",
    "round_slider": "滑块拖拽",
    "special": "特殊操作",
}
METHOD_MAP_REVERSE = {v: k for k, v in METHOD_MAP.items()}

# 深色主题颜色
COLORS = {
    "bg": "#2b2b2b",
    "fg": "white",
    "button_bg": "#3c3c3c",
    "button_fg": "white",
    "listbox_bg": "#353535",
    "listbox_fg": "white",
    "listbox_select_bg": "#505050",
    "entry_bg": "#3c3c3c",
    "entry_fg": "white",
    "frame_bg": "#2b2b2b",
    "label_fg": "#cccccc",
    "border_color": "#555555",
    "highlight_bg": "#4a6fa5",
    "drag_bg": "#555555",
    "special_frame_bg": "#333333",
    "checkbutton_bg": "#2b2b2b",
    "checkbutton_fg": "white",
    "checkbutton_select": "#4a6fa5",
}


class CompareItem:
    """单个设定参数"""

    def __init__(self, name='', ocr_label='', item_type='toggle',
                 target_value='', value_set_method='click',
                 offset_x=0, offset_y=0):
        self.name = name
        self.ocr_label = ocr_label
        self.item_type = item_type          # toggle/slider/text/dropdown
        self.target_value = target_value
        self.value_set_method = value_set_method  # click/ctrl_click/slider_drag
        self.offset_x = int(offset_x or 0)  # 识别范围X偏移(像素)
        self.offset_y = int(offset_y or 0)  # 识别范围Y偏移(像素)

    def to_dict(self):
        return {
            'name': self.name,
            'ocr_label': self.ocr_label,
            'item_type': self.item_type,
            'target_value': self.target_value,
            'value_set_method': self.value_set_method,
            'offset_x': self.offset_x,
            'offset_y': self.offset_y,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d.get('name', ''),
            ocr_label=d.get('ocr_label', ''),
            item_type=d.get('item_type', 'toggle'),
            target_value=d.get('target_value', ''),
            value_set_method=d.get('value_set_method', 'click'),
            offset_x=d.get('offset_x', d.get('click_offset_x', 0)),
            offset_y=d.get('offset_y', d.get('click_offset_y', 0)),
        )


class CompareItemDialog(tk.Toplevel):
    """设定参数编辑对话框（新建/编辑共用）"""

    def __init__(self, parent, item=None, title="编辑设定参数", has_special_type=False):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.result = None  # 关闭时存放 CompareItem 或 None
        self._has_special_type = has_special_type

        self.configure(bg=COLORS["bg"])

        # 如果传入了设定参数，则为编辑模式，填充数据
        self._item = item

        self._build_ui()
        self._apply_dark_theme()

        if item is not None:
            self._fill_from_item(item)

        # 居中显示
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        """构建对话框界面"""
        pad_x = 15
        pad_y = 8

        main_frame = tk.Frame(self, bg=COLORS["bg"])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=pad_x, pady=pad_y)

        # 名称
        row = 0
        tk.Label(main_frame, text="名称:", bg=COLORS["bg"], fg=COLORS["label_fg"],
                 font=("Microsoft YaHei UI", 9)).grid(
            row=row, column=0, sticky=tk.E, padx=(0, 8), pady=pad_y)
        self.name_var = tk.StringVar()
        self.name_entry = tk.Entry(main_frame, textvariable=self.name_var, width=30,
                                   font=("Microsoft YaHei UI", 9))
        self.name_entry.grid(row=row, column=1, columnspan=2, sticky=tk.W, pady=pad_y)

        # OCR标签
        row = 1
        tk.Label(main_frame, text="OCR标签:", bg=COLORS["bg"], fg=COLORS["label_fg"],
                 font=("Microsoft YaHei UI", 9)).grid(
            row=row, column=0, sticky=tk.E, padx=(0, 8), pady=pad_y)
        self.ocr_label_var = tk.StringVar()
        self.ocr_label_entry = tk.Entry(main_frame, textvariable=self.ocr_label_var, width=30,
                                        font=("Microsoft YaHei UI", 9))
        self.ocr_label_entry.grid(row=row, column=1, columnspan=2, sticky=tk.W, pady=pad_y)

        # 类型
        row = 2
        tk.Label(main_frame, text="类型:", bg=COLORS["bg"], fg=COLORS["label_fg"],
                 font=("Microsoft YaHei UI", 9)).grid(
            row=row, column=0, sticky=tk.E, padx=(0, 8), pady=pad_y)
        self.type_var = tk.StringVar(value="蓝色开关")
        type_values = list(TYPE_MAP.values())
        if not self._has_special_type:
            type_values = [v for v in type_values if v != "特殊操作"]
        self.type_combo = ttk.Combobox(main_frame, textvariable=self.type_var,
                                       values=type_values,
                                       state="readonly", width=28,
                                       font=("Microsoft YaHei UI", 9))
        self.type_combo.grid(row=row, column=1, columnspan=2, sticky=tk.W, pady=pad_y)

        # 目标值（根据类型动态切换：开关=下拉，其他=输入框）
        row = 3
        tk.Label(main_frame, text="目标值:", bg=COLORS["bg"], fg=COLORS["label_fg"],
                 font=("Microsoft YaHei UI", 9)).grid(
            row=row, column=0, sticky=tk.E, padx=(0, 8), pady=pad_y)

        # 目标值输入框（用于 slider/text/dropdown）
        self.target_value_var = tk.StringVar()
        self.target_value_entry = tk.Entry(main_frame, textvariable=self.target_value_var,
                                           width=30, font=("Microsoft YaHei UI", 9))
        # 目标值下拉框（用于 toggle）
        self.target_value_combo = ttk.Combobox(main_frame, textvariable=self.target_value_var,
                                               values=["开启", "关闭"], state="readonly", width=28,
                                               font=("Microsoft YaHei UI", 9))
        # 默认显示输入框
        self.target_value_entry.grid(row=row, column=1, columnspan=2, sticky=tk.W, pady=pad_y)
        # 类型切换时自动调整目标值控件
        self.type_combo.bind("<<ComboboxSelected>>", self._on_type_changed)

        # 设置方式
        row = 4
        tk.Label(main_frame, text="设置方式:", bg=COLORS["bg"], fg=COLORS["label_fg"],
                 font=("Microsoft YaHei UI", 9)).grid(
            row=row, column=0, sticky=tk.E, padx=(0, 8), pady=pad_y)
        self.method_var = tk.StringVar(value="点击")
        self.method_combo = ttk.Combobox(main_frame, textvariable=self.method_var,
                                         values=list(METHOD_MAP.values()),
                                         state="readonly", width=28,
                                         font=("Microsoft YaHei UI", 9))
        self.method_combo.grid(row=row, column=1, columnspan=2, sticky=tk.W, pady=pad_y)

        # 识别范围偏移
        row = 5
        tk.Label(main_frame, text="识别偏移:", bg=COLORS["bg"], fg=COLORS["label_fg"],
                 font=("Microsoft YaHei UI", 9)).grid(
            row=row, column=0, sticky=tk.E, padx=(0, 8), pady=pad_y)
        offset_frame = tk.Frame(main_frame, bg=COLORS["bg"])
        offset_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W, pady=pad_y)
        self.offset_x_var = tk.StringVar(value="0")
        self.offset_y_var = tk.StringVar(value="0")
        tk.Label(offset_frame, text="X:", bg=COLORS["bg"], fg=COLORS["label_fg"],
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        tk.Entry(offset_frame, textvariable=self.offset_x_var, width=6,
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(2, 8))
        tk.Label(offset_frame, text="Y:", bg=COLORS["bg"], fg=COLORS["label_fg"],
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        tk.Entry(offset_frame, textvariable=self.offset_y_var, width=6,
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(2, 0))

        # 按钮区域
        row = 6
        btn_frame = tk.Frame(main_frame, bg=COLORS["bg"])
        btn_frame.grid(row=row, column=0, columnspan=3, pady=(15, 5))

        self.ok_btn = tk.Button(btn_frame, text="确定", width=10,
                                command=self._on_ok,
                                bg=COLORS["highlight_bg"], fg="white",
                                font=("Microsoft YaHei UI", 9),
                                activebackground="#5a7fb5", activeforeground="white",
                                relief=tk.FLAT, cursor="hand2")
        self.ok_btn.pack(side=tk.LEFT, padx=10)

        self.cancel_btn = tk.Button(btn_frame, text="取消", width=10,
                                    command=self._on_cancel,
                                    bg=COLORS["button_bg"], fg="white",
                                    font=("Microsoft YaHei UI", 9),
                                    activebackground="#4c4c4c", activeforeground="white",
                                    relief=tk.FLAT, cursor="hand2")
        self.cancel_btn.pack(side=tk.LEFT, padx=10)

        # 绑定回车确认、Esc取消
        self.bind("<Return>", lambda e: self._on_ok())
        self.bind("<Escape>", lambda e: self._on_cancel())

        # 根据初始类型刷新目标值控件
        self._on_type_changed()

    def _apply_dark_theme(self):
        """为 ttk 控件应用深色主题样式"""
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox",
                        fieldbackground=COLORS["entry_bg"],
                        background=COLORS["button_bg"],
                        foreground=COLORS["entry_fg"],
                        arrowcolor=COLORS["fg"],
                        bordercolor=COLORS["border_color"],
                        lightcolor=COLORS["border_color"],
                        darkcolor=COLORS["border_color"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", COLORS["entry_bg"])],
                  selectbackground=[("readonly", COLORS["highlight_bg"])],
                  selectforeground=[("readonly", "white")])

    def _fill_from_item(self, item):
        """编辑模式：用已有设定参数数据填充表单"""
        self.name_var.set(item.name)
        self.ocr_label_var.set(item.ocr_label)
        self.type_var.set(TYPE_MAP.get(item.item_type, "开关"))
        self.target_value_var.set(item.target_value)
        self.method_var.set(METHOD_MAP.get(item.value_set_method, "点击"))
        self.offset_x_var.set(str(item.offset_x))
        self.offset_y_var.set(str(item.offset_y))
        # 根据类型刷新目标值控件
        self._on_type_changed()

    def _on_type_changed(self, event=None):
        """类型切换时动态调整目标值控件：开关=下拉，操作/特殊操作=隐藏，其他=输入框"""
        type_cn = self.type_var.get()
        row = 3
        if type_cn in ("蓝色开关", "勾选开关"):
            self.target_value_entry.grid_forget()
            self.target_value_combo.grid(row=row, column=1, columnspan=2, sticky=tk.W, pady=8)
            self.method_combo.config(state="readonly")
            if self.target_value_var.get() not in ("开启", "关闭"):
                self.target_value_var.set("开启")
        elif type_cn in ("按钮", "特殊操作"):
            self.target_value_entry.grid_forget()
            self.target_value_combo.grid_forget()
            if type_cn == "特殊操作":
                self.method_combo.config(state="disabled")
                self.target_value_var.set("")
            else:
                self.method_combo.config(state="readonly")
        else:
            self.target_value_combo.grid_forget()
            self.target_value_entry.grid(row=row, column=1, columnspan=2, sticky=tk.W, pady=8)
            self.method_combo.config(state="readonly")
            if self.target_value_var.get() in ("开启", "关闭"):
                self.target_value_var.set("")

    def _on_ok(self):
        """确定按钮回调"""
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入设定参数名称", parent=self)
            self.name_entry.focus_set()
            return

        type_cn = self.type_var.get()
        method_cn = self.method_var.get()

        # 特殊操作强制设置方法为 special
        if type_cn == "特殊操作":
            method_cn = "special"

        self.result = CompareItem(
            name=name,
            ocr_label=self.ocr_label_var.get().strip(),
            item_type=TYPE_MAP_REVERSE.get(type_cn, "toggle"),
            target_value=self.target_value_var.get().strip(),
            value_set_method=METHOD_MAP_REVERSE.get(method_cn, "click"),
            offset_x=self.offset_x_var.get().strip(),
            offset_y=self.offset_y_var.get().strip(),
        )
        self.destroy()

    def _on_cancel(self):
        """取消按钮回调"""
        self.result = None
        self.destroy()


class SMDConfigEditor(tk.Toplevel):
    """SMD 配置设定参数编辑器主窗口"""

    def __init__(self, parent, on_save_callback=None, game_monitor_ref=None, config_path=None):
        super().__init__(parent)
        self.title("SMD 配置编辑器")
        self.geometry("800x700")
        self.minsize(700, 600)
        self.configure(bg=COLORS["bg"])

        # 回调函数：保存后通知父窗口
        self.on_save_callback = on_save_callback
        # GameMonitor 实例引用（用于测试功能）
        self.game_monitor_ref = game_monitor_ref

        # 默认配置文件路径（优先用户数据目录，回退到 _internal）
        _default_user = os.path.join(_DATA_DIR, 'smd_config', 'smd_settings.json')
        _default_internal = os.path.join(_BASE_DIR, 'smd_config', 'smd_settings.json')
        self.default_config_path = _default_user if os.path.isfile(_default_user) else _default_internal
        self.config_path = config_path if config_path and os.path.isfile(config_path) else self.default_config_path

        # 配置数据结构：{tab_key: {"items": [CompareItem, ...], "extra": {}}}
        self.config_data = {}
        for tab in SMD_TABS:
            self.config_data[tab["key"]] = {
                "items": [],
                "extra": {},
            }

        # 当前选中的标签页索引
        self.current_tab_index = 0

        # 拖放相关状态
        self._drag_start_index = None
        self._dragging = False

        # 各脚本类型的已选脚本名（内存中独立保存，不立即写入文件）
        self._script_selections = {}

        self._build_ui()
        self._apply_dark_theme()

        # 如果传入了配置路径且文件存在，则自动加载
        if self.config_path and os.path.isfile(self.config_path):
            self._load_from_file(self.config_path)

        # 刷新显示
        self._refresh_items_list()

        # 居中显示
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        """构建主界面"""
        # 顶层容器
        top_frame = tk.Frame(self, bg=COLORS["bg"])
        top_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ===== 左侧标签列表 =====
        left_frame = tk.Frame(top_frame, bg=COLORS["bg"], width=120)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        left_frame.pack_propagate(False)

        tk.Label(left_frame, text="界面标签", bg=COLORS["bg"], fg=COLORS["label_fg"],
                 font=("Microsoft YaHei UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 5))

        self.tab_listbox = tk.Listbox(
            left_frame,
            bg=COLORS["listbox_bg"],
            fg=COLORS["listbox_fg"],
            selectbackground=COLORS["highlight_bg"],
            selectforeground="white",
            font=("Microsoft YaHei UI", 9),
            relief=tk.FLAT,
            highlightthickness=1,
            highlightcolor=COLORS["border_color"],
            highlightbackground=COLORS["border_color"],
            activestyle="none",
            cursor="hand2",
        )
        self.tab_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 填充标签名称
        for tab in SMD_TABS:
            self.tab_listbox.insert(tk.END, tab["name"])

        # 默认选中第一个
        if SMD_TABS:
            self.tab_listbox.selection_set(0)

        # 绑定标签切换事件
        self.tab_listbox.bind("<<ListboxSelect>>", self._on_tab_selected)

        # ===== 右侧内容区域 =====
        right_frame = tk.Frame(top_frame, bg=COLORS["bg"])
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 设定参数列表区域
        items_label_frame = tk.LabelFrame(
            right_frame, text=" 设定参数列表（拖放排序） ",
            bg=COLORS["bg"], fg=COLORS["label_fg"],
            font=("Microsoft YaHei UI", 9, "bold"),
            relief=tk.GROOVE, bd=1,
        )
        items_label_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # 设定参数列表（使用 Listbox，方便拖放排序）
        list_container = tk.Frame(items_label_frame, bg=COLORS["bg"])
        list_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 滚动条
        scrollbar = tk.Scrollbar(list_container, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.items_listbox = tk.Listbox(
            list_container,
            bg=COLORS["listbox_bg"],
            fg=COLORS["listbox_fg"],
            selectbackground=COLORS["highlight_bg"],
            selectforeground="white",
            font=("Consolas", 9),
            relief=tk.FLAT,
            highlightthickness=1,
            highlightcolor=COLORS["border_color"],
            highlightbackground=COLORS["border_color"],
            activestyle="none",
            yscrollcommand=scrollbar.set,
            cursor="hand2",
        )
        self.items_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.items_listbox.yview)

        # 绑定拖放事件
        self.items_listbox.bind("<ButtonPress-1>", self._on_item_press)
        self.items_listbox.bind("<B1-Motion>", self._on_item_motion)
        self.items_listbox.bind("<ButtonRelease-1>", self._on_item_release)

        # 按钮区域（新建、编辑、删除）
        item_btn_frame = tk.Frame(items_label_frame, bg=COLORS["bg"])
        item_btn_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        btn_add = tk.Button(item_btn_frame, text="+ 新建设定参数", width=14,
                            command=self._on_add_item,
                            bg=COLORS["highlight_bg"], fg="white",
                            font=("Microsoft YaHei UI", 9),
                            activebackground="#5a7fb5", activeforeground="white",
                            relief=tk.FLAT, cursor="hand2")
        btn_add.pack(side=tk.LEFT, padx=(0, 5))

        btn_edit = tk.Button(item_btn_frame, text="编辑", width=8,
                             command=self._on_edit_item,
                             bg=COLORS["button_bg"], fg="white",
                             font=("Microsoft YaHei UI", 9),
                             activebackground="#4c4c4c", activeforeground="white",
                             relief=tk.FLAT, cursor="hand2")
        btn_edit.pack(side=tk.LEFT, padx=(0, 5))

        btn_delete = tk.Button(item_btn_frame, text="删除", width=8,
                               command=self._on_delete_item,
                               bg=COLORS["button_bg"], fg="white",
                               font=("Microsoft YaHei UI", 9),
                               activebackground="#4c4c4c", activeforeground="white",
                               relief=tk.FLAT, cursor="hand2")
        btn_delete.pack(side=tk.LEFT)

        btn_test_one = tk.Button(item_btn_frame, text="测试选中", width=10,
                                  command=self._on_test_selected,
                                  bg="#3c6e71", fg="white",
                                  font=("Microsoft YaHei UI", 9),
                                  activebackground="#4c8a8d", activeforeground="white",
                                  relief=tk.FLAT, cursor="hand2")
        btn_test_one.pack(side=tk.LEFT, padx=(5, 0))

        btn_test_tab = tk.Button(item_btn_frame, text="测试本页", width=10,
                                 command=self._on_test_tab,
                                 bg="#3c6e71", fg="white",
                                 font=("Microsoft YaHei UI", 9),
                                 activebackground="#4c8a8d", activeforeground="white",
                                 relief=tk.FLAT, cursor="hand2")
        btn_test_tab.pack(side=tk.LEFT, padx=(5, 0))

        # 界面特殊操作区域
        self.special_frame = tk.LabelFrame(
            right_frame, text=" 界面特殊操作 ",
            bg=COLORS["special_frame_bg"], fg=COLORS["label_fg"],
            font=("Microsoft YaHei UI", 9, "bold"),
            relief=tk.GROOVE, bd=1,
        )
        self.special_frame.pack(fill=tk.X, pady=(0, 5))

        self.special_inner_frame = tk.Frame(self.special_frame, bg=COLORS["special_frame_bg"])
        self.special_inner_frame.pack(fill=tk.X, padx=10, pady=8)

        # 存放 Checkbutton 变量的字典
        self.special_check_vars = {}

        # 测试日志区域
        self.log_frame = tk.LabelFrame(
            right_frame, text=" 测试日志 ",
            bg=COLORS["special_frame_bg"], fg=COLORS["label_fg"],
            font=("Microsoft YaHei UI", 9, "bold"),
            relief=tk.GROOVE, bd=1,
        )
        self.log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        log_inner = tk.Frame(self.log_frame, bg=COLORS["special_frame_bg"])
        log_inner.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.log_text = tk.Text(log_inner, bg="#1a1a1a", fg="#cccccc",
                                font=("Consolas", 8),
                                height=6, wrap=tk.WORD,
                                state=tk.DISABLED)
        log_scrollbar = tk.Scrollbar(log_inner, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 清空按钮放在日志区域标题栏右侧
        btn_clear_log = tk.Button(self.log_frame, text="清空", width=5,
                                   command=lambda: self.log_text.configure(state=tk.NORMAL) or self.log_text.delete("1.0", tk.END) or self.log_text.configure(state=tk.DISABLED),
                                   bg="#4c4c4c", fg="white",
                                   font=("Microsoft YaHei UI", 8),
                                   activebackground="#666", activeforeground="white",
                                   relief=tk.FLAT, cursor="hand2")
        # 将清空按钮放到LabelFrame的标题旁边（使用place定位在右上角）
        btn_clear_log.place(in_=self.log_frame, relx=1.0, x=-5, y=2, anchor=tk.NE)

        # 底部按钮栏
        bottom_frame = tk.Frame(self, bg=COLORS["bg"])
        bottom_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        # 创建水平容器，包含左侧控件组和右侧关闭按钮
        content_frame = tk.Frame(bottom_frame, bg=COLORS["bg"])
        content_frame.pack(fill=tk.X)

        # 左侧控件组（保存到、下拉框、保存配置、恢复默认）
        left_frame = tk.Frame(content_frame, bg=COLORS["bg"])
        left_frame.pack(side=tk.LEFT, fill=tk.X, pady=5)

        # 保存目标选择
        save_row = tk.Frame(left_frame, bg=COLORS["bg"])
        save_row.pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(save_row, text="保存到:", bg=COLORS["bg"], fg=COLORS["label_fg"],
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 5))
        self._save_target_var = tk.StringVar()
        self._save_target_combo = ttk.Combobox(save_row, textvariable=self._save_target_var,
                                               values=[], width=15,
                                               font=("Microsoft YaHei UI", 9))
        self._save_target_combo.pack(side=tk.LEFT, padx=2)
        # 初始化保存目标列表
        self._refresh_save_targets()

        # 保存配置按钮
        btn_save = tk.Button(left_frame, text="保存配置", width=12,
                             command=self._on_save_config,
                             bg=COLORS["highlight_bg"], fg="white",
                             font=("Microsoft YaHei UI", 9),
                             activebackground="#5a7fb5", activeforeground="white",
                             relief=tk.FLAT, cursor="hand2")
        btn_save.pack(side=tk.LEFT, padx=(0, 5))

        # 恢复默认按钮
        btn_restore = tk.Button(left_frame, text="恢复默认", width=12,
                                command=self._on_restore_default,
                                bg="#6a4a4a", fg="white",
                                font=("Microsoft YaHei UI", 9),
                                activebackground="#7a5a5a", activeforeground="white",
                                relief=tk.FLAT, cursor="hand2")
        btn_restore.pack(side=tk.LEFT, padx=(0, 5))

        # 右侧关闭按钮
        btn_close = tk.Button(content_frame, text="关闭", width=12,
                              command=self._on_close,  # 假设你有这个方法
                              bg="#555555", fg="white",
                              font=("Microsoft YaHei UI", 9),
                              activebackground="#666666", activeforeground="white",
                              relief=tk.FLAT, cursor="hand2")
        btn_close.pack(side=tk.RIGHT, pady=5)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_dark_theme(self):
        """为 ttk 控件应用深色主题样式"""
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox",
                        fieldbackground=COLORS["entry_bg"],
                        background=COLORS["button_bg"],
                        foreground=COLORS["entry_fg"],
                        arrowcolor=COLORS["fg"],
                        bordercolor=COLORS["border_color"],
                        lightcolor=COLORS["border_color"],
                        darkcolor=COLORS["border_color"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", COLORS["entry_bg"])],
                  selectbackground=[("readonly", COLORS["highlight_bg"])],
                  selectforeground=[("readonly", "white")])

    # ==================== 标签切换 ====================

    def _on_tab_selected(self, event=None):
        """标签页选择切换"""
        selection = self.tab_listbox.curselection()
        if not selection:
            return
        self.current_tab_index = selection[0]
        self._refresh_items_list()
        self._refresh_special_actions()

    def _get_current_tab_key(self):
        """获取当前选中标签页的 key"""
        if 0 <= self.current_tab_index < len(SMD_TABS):
            return SMD_TABS[self.current_tab_index]["key"]
        return None

    # ==================== 设定参数列表显示 ====================

    def _refresh_items_list(self):
        """刷新右侧设定参数列表"""
        self.items_listbox.delete(0, tk.END)
        tab_key = self._get_current_tab_key()
        if tab_key is None:
            return

        items = self.config_data[tab_key]["items"]
        for idx, item in enumerate(items):
            # 显示格式：序号. 名称 [目标值] 类型(设置方式)
            type_cn = TYPE_MAP.get(item.item_type, item.item_type)
            method_cn = METHOD_MAP.get(item.value_set_method, item.value_set_method)
            display = f"{idx + 1}. {item.name}  [{item.target_value}]  {type_cn}({method_cn})"
            if item.offset_x or item.offset_y:
                display += f"  识别偏移({item.offset_x},{item.offset_y})"
            self.items_listbox.insert(tk.END, display)

        self._refresh_special_actions()

    def _refresh_special_actions(self):
        """刷新特殊操作区域"""
        for widget in self.special_inner_frame.winfo_children():
            widget.destroy()
        self.special_check_vars.clear()

        tab_key = self._get_current_tab_key()
        if tab_key is None:
            return

        tab_info = SMD_TABS[self.current_tab_index]

        # 恢复已保存的 extra 数据到 tab_info
        extra = self.config_data[tab_key].get("extra", {})
        for k, v in extra.items():
            tab_info[k] = v

        # 只有脚本编辑有特殊UI（脚本选择器）
        if not tab_info.get("has_script_selector"):
            tk.Label(self.special_inner_frame,
                     text="无额外配置",
                     bg=COLORS["special_frame_bg"], fg="#888",
                     font=("Microsoft YaHei UI", 8)).pack(anchor=tk.W)
            return

        # 脚本编辑：脚本类型选择 + 文件列表
        type_row = tk.Frame(self.special_inner_frame, bg=COLORS["special_frame_bg"])
        type_row.pack(fill=tk.X, pady=2)
        tk.Label(type_row, text="脚本类型:", bg=COLORS["special_frame_bg"],
                 fg=COLORS["label_fg"], font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.script_type_var = tk.StringVar(value=tab_info.get("script_type", "恶化"))
        script_type_combo = ttk.Combobox(type_row, textvariable=self.script_type_var,
                                          values=["恶化", "入侵", "副本", "支线", "报复", "自定义"],
                                          state="readonly", width=10,
                                          font=("Microsoft YaHei UI", 9))
        script_type_combo.pack(side=tk.LEFT, padx=5)
        script_type_combo.bind("<<ComboboxSelected>>", self._on_script_type_changed)

        # 已选脚本名（只读显示）
        tk.Label(type_row, text="已选:", bg=COLORS["special_frame_bg"],
                 fg=COLORS["label_fg"], font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(10, 2))
        self.selected_script_var = tk.StringVar(value=tab_info.get("selected_script", ""))
        self.selected_script_entry = tk.Entry(type_row, textvariable=self.selected_script_var,
                                              width=28, font=("Consolas", 9), state="readonly",
                                              bg=COLORS["entry_bg"], fg="#4ecca3",
                                              readonlybackground=COLORS["entry_bg"],
                                              relief=tk.FLAT)
        self.selected_script_entry.pack(side=tk.LEFT, padx=2)

        # 脚本文件列表（带滚动条）
        list_row = tk.Frame(self.special_inner_frame, bg=COLORS["special_frame_bg"])
        list_row.pack(fill=tk.BOTH, expand=True, pady=2)

        script_scroll = tk.Scrollbar(list_row, orient=tk.VERTICAL)
        script_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.script_listbox = tk.Listbox(
            list_row, height=5,
            bg=COLORS["listbox_bg"], fg=COLORS["listbox_fg"],
            selectbackground=COLORS["highlight_bg"], selectforeground="white",
            font=("Consolas", 9), relief=tk.FLAT,
            highlightthickness=1,
            highlightcolor=COLORS["border_color"],
            highlightbackground=COLORS["border_color"],
            activestyle="none", yscrollcommand=script_scroll.set,
            cursor="hand2",
        )
        self.script_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        script_scroll.config(command=self.script_listbox.yview)

        self.script_listbox.bind("<<ListboxSelect>>", self._on_script_selected)
        self._refresh_script_list()

        # 脚本信息按钮（每次刷新时重建）
        meta_row = tk.Frame(list_row, bg=COLORS["special_frame_bg"])
        meta_row.pack(fill=tk.X, pady=(4, 0))
        tk.Button(meta_row, text="脚本信息", font=("Microsoft YaHei UI", 8),
                  bg="#4a4a6a", fg="white", relief=tk.FLAT, cursor="hand2",
                  command=self._open_script_meta_editor).pack(side=tk.LEFT)

    def _on_script_type_changed(self, event=None):
        """脚本类型切换时刷新文件列表，并显示当前类型已选脚本名"""
        script_type = self.script_type_var.get()
        # 显示当前类型在内存中的已选脚本名
        last_script = self._script_selections.get(script_type, "")
        self.selected_script_var.set(last_script)
        self._refresh_script_list()
        self._save_tab_extra("script_type", script_type)

    def _refresh_script_list(self):
        """根据脚本类型刷新 C:\\Spc\\ 下的 .bin 文件列表"""
        if not hasattr(self, 'script_listbox'):
            return
        self.script_listbox.delete(0, tk.END)

        script_type = self.script_type_var.get() if hasattr(self, 'script_type_var') else "恶化"

        # 根据类型确定前缀规则
        prefix_map = {
            "恶化": "eh_",
            "入侵": "rq_",
            "副本": "fb_",
            "支线": "zx_",
            "报复": "bf_",
            "自定义": "",
        }
        prefix = prefix_map.get(script_type, "")

        # 扫描目录
        scan_dir = r"C:\Spc"
        if not os.path.isdir(scan_dir):
            self.script_listbox.insert(tk.END, f"目录不存在: {scan_dir}")
            self._set_script_name_color("red")
            return

        try:
            files = sorted([f for f in os.listdir(scan_dir) if f.endswith('.bin')])
        except Exception:
            self._set_script_name_color("red")
            return

        # 过滤：自定义显示全部，其他按前缀
        if script_type == "自定义":
            matched = files
        elif prefix:
            matched = [f for f in files if f.lower().startswith(prefix.lower())]
        else:
            matched = files

        if not matched:
            self.script_listbox.insert(tk.END, f"未找到匹配的脚本文件")
            # 列表为空，已选脚本名变红色提示
            self._set_script_name_color("red")
            return

        # 从内存中读取当前类型的已选脚本
        last_selected = self._script_selections.get(script_type, "")
        select_idx = -1
        for i, f in enumerate(matched):
            self.script_listbox.insert(tk.END, f)
            if f == last_selected:
                select_idx = i

        # 设置选中并恢复绿色
        self._set_script_name_color("#4ecca3")
        if select_idx >= 0:
            self.script_listbox.selection_set(select_idx)
            self.script_listbox.see(select_idx)
        elif matched:
            self.script_listbox.selection_set(0)
            self.script_listbox.see(0)

    def _set_script_name_color(self, color):
        """设置已选脚本名的显示颜色"""
        if hasattr(self, 'selected_script_entry') and self.selected_script_entry:
            self.selected_script_entry.config(fg=color)

    def _open_script_meta_editor(self):
        """打开选中脚本的元数据编辑器"""
        sel = self.script_listbox.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一个脚本文件", parent=self)
            return
        script_name = self.script_listbox.get(sel[0])
        ScriptMetaEditor(self, script_name)

    def _on_script_selected(self, event=None):
        """脚本文件选中回调（保存到内存，不立即写入文件）"""
        sel = self.script_listbox.curselection()
        if sel:
            script_name = self.script_listbox.get(sel[0])
            self.selected_script_var.set(script_name)
            script_type = self.script_type_var.get() if hasattr(self, 'script_type_var') else "恶化"
            self._script_selections[script_type] = script_name
            self._set_script_name_color("#4ecca3")

    def _save_tab_extra(self, key, value):
        """保存标签页的额外配置（脚本类型、选中的脚本等）"""
        tab_key = self._get_current_tab_key()
        if tab_key is None:
            return
        if "extra" not in self.config_data[tab_key]:
            self.config_data[tab_key]["extra"] = {}
        self.config_data[tab_key]["extra"][key] = value

    # ==================== 设定参数增删改 ====================

    def _on_add_item(self):
        """新建设定参数"""
        tab_key = self._get_current_tab_key()
        if tab_key is None:
            return

        tab_info = SMD_TABS[self.current_tab_index]
        has_special = tab_info.get("has_script_selector", False)
        dialog = CompareItemDialog(self, item=None, title="新建设定参数", has_special_type=has_special)
        self.wait_window(dialog)

        if dialog.result is not None:
            self.config_data[tab_key]["items"].append(dialog.result)
            self._refresh_items_list()

    def _on_edit_item(self):
        """编辑选中的设定参数"""
        tab_key = self._get_current_tab_key()
        if tab_key is None:
            return

        selection = self.items_listbox.curselection()
        if not selection:
            messagebox.showinfo("提示", "请先选择要编辑的设定参数", parent=self)
            return

        idx = selection[0]
        items = self.config_data[tab_key]["items"]
        if idx >= len(items):
            return

        item = items[idx]
        tab_info = SMD_TABS[self.current_tab_index]
        has_special = tab_info.get("has_script_selector", False)
        dialog = CompareItemDialog(self, item=item, title="编辑设定参数", has_special_type=has_special)
        self.wait_window(dialog)

        if dialog.result is not None:
            items[idx] = dialog.result
            self._refresh_items_list()

    def _on_delete_item(self):
        """删除选中的设定参数"""
        tab_key = self._get_current_tab_key()
        if tab_key is None:
            return

        selection = self.items_listbox.curselection()
        if not selection:
            messagebox.showinfo("提示", "请先选择要删除的设定参数", parent=self)
            return

        idx = selection[0]
        items = self.config_data[tab_key]["items"]
        if idx >= len(items):
            return

        item_name = items[idx].name
        if messagebox.askyesno("确认删除", f"确定要删除设定参数「{item_name}」吗？", parent=self):
            items.pop(idx)
            self._refresh_items_list()

    def _normalize_match_text(self, text):
        """规范化匹配文本：去掉 - ( ) _ 等干扰符号"""
        return (text.replace('-', '').replace('－', '')
                .replace('(', '').replace(')', '')
                .replace('（', '').replace('）', '')
                .replace('_', '').replace(' ', ''))

    def _strip_bin(self, name):
        """去掉 .bin 后缀"""
        if name and name.lower().endswith('.bin'):
            return name[:-4]
        return name

    def _normalize_script_name(self, text):
        """专门用于脚本名匹配的规范化：去掉更多干扰符号、统一小写"""
        return (text.replace('-', '').replace('－', '')
                .replace('(', '').replace(')', '')
                .replace('（', '').replace('）', '')
                .replace('_', '').replace(' ', '')
                .replace('.', '').replace('x', '').replace('X', '')
                .lower())

    def _match_script_name(self, target, ocr_text):
        """匹配脚本名：去掉.bin、干扰符号和x后，统一小写，支持截断匹配"""
        t = self._normalize_script_name(self._strip_bin(target))
        o = self._normalize_script_name(self._strip_bin(ocr_text))
        if not t or not o:
            return False
        # 前缀/包含匹配（列表截断或OCR误差）
        if t in o or o in t:
            return True
        # 取较短的长度做前缀匹配（至少3个字符）
        min_len = min(len(t), len(o))
        if min_len >= 3:
            return t[:min_len] == o[:min_len]
        return False

    def _test_click_in_game(self, hwnd, ocr_label):
        """在游戏窗口中OCR查找文字并点击（忽略 - ( ) 等符号），返回是否成功"""
        import ctypes
        import time
        try:
            from PIL import ImageGrab
            ocr_engine = self._get_test_ocr()
            if not ocr_engine:
                self._log(f"[测试]   OCR引擎未就绪")
                return False
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            win_w = rect.right - rect.left
            win_h = rect.bottom - rect.top
            img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
            items = self._ocr_recognize_with_pos(ocr_engine, img)

            self._log(f"[测试]   窗口尺寸={win_w}x{win_h}, OCR识别到{len(items)}个文本:")
            for i, (text, cx, cy) in enumerate(items):
                self._log(f"[测试]     [{i}] '{text}' -> 相对窗口=({cx},{cy})")
            # 覆盖层：红色标记目标标签
            norm_label = self._normalize_match_text(ocr_label)
            for text, cx, cy in items:
                if norm_label in self._normalize_match_text(text):
                    self._show_overlay(
                        [(*self._text_rect(rect, cx, cy, text), '#FF0000', text)],
                        window_rect=rect)
                    break

            self._log(f"[测试]   搜索目标(规范化): '{norm_label}'")

            for text, cx, cy in items:
                norm_text = self._normalize_match_text(text)
                if norm_label in norm_text:
                    # 计算点击坐标（窗口绝对坐标）
                    abs_x = rect.left + cx
                    abs_y = rect.top + cy

                    # 多词偏移（同game_monitor.py）
                    if len(norm_text) > len(norm_label) + 1:
                        idx = norm_text.find(norm_label)
                        if idx >= 0:
                            char_width = 15
                            offset_x = int((idx + len(norm_label) / 2) * char_width
                                           - len(norm_text) / 2 * char_width)
                            cx += offset_x
                            abs_x = rect.left + cx
                            self._log(f"[测试]   多词偏移: '{ocr_label}'在'{text}'中位置{idx}，偏移{offset_x}px")

                    self._log(f"[测试]   匹配成功: '{text}' -> 相对=({cx},{cy}) -> 绝对屏幕=({abs_x},{abs_y})")
                    ctypes.windll.user32.SetCursorPos(abs_x, abs_y)
                    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                    time.sleep(0.05)
                    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                    return True

            self._log(f"[测试]   未匹配到 '{ocr_label}'")
            return False
        except Exception as e:
            self._log(f"[测试]   点击异常: {e}")
            return False

    # ==================== OCR 可视化覆盖层 ====================

    def _show_overlay(self, regions, duration=3000, window_rect=None):
        """在屏幕上用彩色矩形框绘制指定区域，几秒后自动消失
        Args:
            regions: [(x1, y1, x2, y2, color, label), ...] 屏幕绝对坐标的区域列表
                     color: '#FF0000'(红) '#00FF00'(绿) '#00BFFF'(蓝) 等
            duration: 显示时长(毫秒)，默认3000
            window_rect: 窗口RECT对象，有则绘制白色虚线窗口边框
        """
        try:
            overlay = tk.Toplevel(self)
            overlay.overrideredirect(True)
            overlay.attributes('-topmost', True)
            overlay.attributes('-alpha', 0.4)
            sw = overlay.winfo_screenwidth()
            sh = overlay.winfo_screenheight()
            overlay.geometry(f"{sw}x{sh}+0+0")
            canvas = tk.Canvas(overlay, bg='#111111', highlightthickness=0)
            canvas.pack(fill=tk.BOTH, expand=True)

            # 游戏窗口边框（白色虚线）
            if window_rect:
                canvas.create_rectangle(
                    window_rect.left, window_rect.top, window_rect.right, window_rect.bottom,
                    outline='#FFFFFF', width=2, dash=(8, 4))

            # 绘制各区域
            for x1, y1, x2, y2, color, label in regions:
                lw = 3 if color in ('#FF0000', '#00FF00') else 2
                canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=lw)
                if label:
                    canvas.create_text(x1, y1 - 8, text=label, fill=color,
                                       font=('Microsoft YaHei', 8), anchor=tk.S)

            overlay.after(duration, overlay.destroy)
        except Exception:
            pass

    def _text_rect(self, rect, cx, cy, text, char_w=14, text_h=22):
        """根据OCR文字中心位置和文字内容，估算屏幕绝对坐标矩形"""
        w = max(len(text) * char_w, 30)
        return (rect.left + cx - w // 2, rect.top + cy - text_h // 2,
                rect.left + cx + w // 2, rect.top + cy + text_h // 2)

    def _get_test_ocr(self):
        """获取测试用的OCR引擎（不依赖监控启动）"""
        if self.game_monitor_ref and hasattr(self.game_monitor_ref, 'ocr_engine') and self.game_monitor_ref.ocr_engine:
            return self.game_monitor_ref.ocr_engine
        # 临时创建OCR引擎
        if not hasattr(self, '_test_ocr_engine') or self._test_ocr_engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
                import numpy as np
                self._test_ocr_engine = RapidOCR()
                self._test_ocr_engine(np.zeros((32, 32, 3), dtype=np.uint8))
            except Exception as e:
                self._test_ocr_engine = None
                self._log(f"[测试] OCR引擎初始化失败: {e}")
                return None
        return self._test_ocr_engine

    def _send_key_to_game(self, hwnd, vk):
        """发送按键到游戏窗口（SendInput + 扫描码 + AttachThreadInput）"""
        KEYEVENTF_KEYUP = 0x0002
        KEYEVENTF_SCANCODE = 0x0008
        INPUT_KEYBOARD = 1
        scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                        ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                        ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                        ("dwExtraInfo", ctypes.c_size_t)]
        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort),
                        ("wParamH", ctypes.c_ushort)]
        class INPUT_UNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]
        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]

        inp_size = ctypes.sizeof(INPUT)
        fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
        fg_tid = ctypes.windll.user32.GetWindowThreadProcessId(fg_hwnd, None)
        tg_tid = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)
        need = (fg_tid != tg_tid)
        if need:
            ctypes.windll.user32.AttachThreadInput(fg_tid, tg_tid, True)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.05)
        for flags in [KEYEVENTF_SCANCODE, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP]:
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.union.ki.wScan = scan
            inp.union.ki.dwFlags = flags
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp), inp_size)
            time.sleep(0.05)
        if need:
            ctypes.windll.user32.AttachThreadInput(fg_tid, tg_tid, False)

    def _activate_window(self, hwnd):
        """激活窗口（强制前台，使用AttachThreadInput确保获取焦点）"""
        import ctypes
        import time
        try:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            foreground_tid = ctypes.windll.user32.GetWindowThreadProcessId(
                ctypes.windll.user32.GetForegroundWindow(), None)
            target_tid = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)
            if foreground_tid != target_tid:
                ctypes.windll.user32.AttachThreadInput(foreground_tid, target_tid, True)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            ctypes.windll.user32.BringWindowToTop(hwnd)
            time.sleep(0.1)
            if foreground_tid != target_tid:
                ctypes.windll.user32.AttachThreadInput(foreground_tid, target_tid, False)
        except Exception as e:
            self._log(f"[测试] 激活窗口失败: {e}")

    def _ocr_recognize(self, ocr_engine, img):
        """统一OCR识别（兼容OCREngine和RapidOCR）"""
        import numpy as np
        import cv2
        from PIL import Image as PILImage
        if isinstance(img, PILImage.Image):
            img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        result = ocr_engine(img) if not hasattr(ocr_engine, 'recognize') else ocr_engine.recognize(img)
        if isinstance(result, str):
            return result
        # RapidOCR返回格式: (results, elapse)
        if isinstance(result, tuple) and len(result) >= 1 and result[0]:
            lines = []
            for item in result[0]:
                if len(item) >= 2:
                    lines.append(str(item[1]))
            return '\n'.join(lines)
        return ''

    def _ocr_recognize_with_pos(self, ocr_engine, img):
        """统一OCR识别+位置"""
        import numpy as np
        import cv2
        from PIL import Image as PILImage
        if isinstance(img, PILImage.Image):
            img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        # 优先用recognize_with_pos
        if hasattr(ocr_engine, 'recognize_with_pos'):
            return ocr_engine.recognize_with_pos(img)
        result = ocr_engine(img) if not hasattr(ocr_engine, 'recognize') else ocr_engine.recognize(img)
        items = []
        if isinstance(result, tuple) and len(result) >= 1 and result[0]:
            for item in result[0]:
                if len(item) >= 2 and len(item[0]) >= 4:
                    bbox = item[0]
                    cx = (bbox[0][0] + bbox[2][0]) // 2
                    cy = (bbox[0][1] + bbox[1][1]) // 2
                    items.append((str(item[1]), int(cx), int(cy)))
        return items

    def _click_ocr_in_game(self, hwnd, text):
        """在游戏窗口中OCR找到文字并点击（忽略 - ( ) 等符号）
        当OCR文本比搜索文本长时，自动估算目标文字在OCR文本中的位置偏移
        """
        import ctypes
        import ctypes.wintypes
        import time
        try:
            from PIL import ImageGrab
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))

            ocr_engine = self._get_test_ocr()
            if not ocr_engine:
                return False
            items = self._ocr_recognize_with_pos(ocr_engine, img)
            norm_text = self._normalize_match_text(text)
            # 覆盖层：红色标目标
            for ocr_t, cx, cy in items:
                if norm_text in self._normalize_match_text(ocr_t):
                    self._show_overlay(
                        [(*self._text_rect(rect, cx, cy, ocr_t), '#FF0000', ocr_t)],
                        window_rect=rect)
                    break
            # 收集所有匹配项，优先选择长度最接近的（最精确匹配）
            candidates = []
            for ocr_text, cx, cy in items:
                norm_ocr = self._normalize_match_text(ocr_text)
                if norm_text in norm_ocr:
                    candidates.append((abs(len(norm_ocr) - len(norm_text)), ocr_text, cx, cy))
            if candidates:
                candidates.sort(key=lambda x: x[0])
                _, best_ocr, cx, cy = candidates[0]

                # 多词偏移
                norm_ocr = self._normalize_match_text(best_ocr)
                if len(norm_ocr) > len(norm_text) + 1:
                    idx = norm_ocr.find(norm_text)
                    if idx >= 0:
                        char_width = 15
                        offset_x = int((idx + len(norm_text) / 2) * char_width
                                       - len(norm_ocr) / 2 * char_width)
                        cx += offset_x

                abs_x = rect.left + cx
                abs_y = rect.top + cy
                self._activate_window(hwnd)
                time.sleep(0.2)
                ctypes.windll.user32.SetCursorPos(abs_x, abs_y)
                time.sleep(0.1)
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                time.sleep(0.05)
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                time.sleep(0.3)
                return True
            self._log(f"[测试]   未匹配到'{text}'")
        except Exception as e:
            self._log(f"[测试]   OCR点击异常: {e}")
        return False

    def _find_slider_thumb(self, img, value_pos, label_pos, win_w, win_h, current_value=None, offset_x=0, offset_y=0):
        """在截图上找圆形滑块位置（白色圆形，在数值右侧）
        搜索范围：数值x坐标 + 字符长度*10/2 + offset_x 起，宽130像素，y±15+offset_y
        使用区域采样白色像素密度找滑块中心，避免和文字混淆
        返回 (x, y) 绝对窗口内坐标，或 None
        """
        import cv2
        import numpy as np
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

        if not value_pos:
            return None

        # 搜索范围：数值右侧
        char_len = len(current_value) if current_value else 3
        search_left = int(value_pos[0] + char_len * 10 / 2 + offset_x)
        search_right = search_left + 130
        search_top = max(0, value_pos[1] - 15 + offset_y)
        search_bottom = min(win_h, value_pos[1] + 15 + offset_y)

        if search_left >= search_right or search_top >= search_bottom:
            return None

        roi = img_cv[search_top:search_bottom, search_left:search_right]

        # 区域采样：白色像素 (R>200, G>200, B>200) 的密集区域
        white_mask = (roi[:, :, 2] > 200) & (roi[:, :, 1] > 200) & (roi[:, :, 0] > 200)
        white_pts = np.where(white_mask)
        if len(white_pts[0]) > 0:
            cx = int(np.median(white_pts[1])) + search_left
            cy = int(np.median(white_pts[0])) + search_top
            return (cx, cy)
        return None

    def _drag_slider_to_value(self, hwnd, rect, ocr_label, thumb_pos, cur_val, tgt_val, label_pos, max_iterations=15):
        """二分法在滑条轨道上逼近目标值（不依赖线性假设）"""
        import ctypes
        import time
        from PIL import ImageGrab

        # 滑条轨道范围
        left_bound = thumb_pos[0] - 65
        right_bound = thumb_pos[0] + 65
        target_y = thumb_pos[1]

        for iteration in range(max_iterations):
            if abs(cur_val - tgt_val) < 0.1:
                self._log(f"[测试]   圆形滑条: 达到目标值 {tgt_val}")
                break

            # 二分：点击中点
            mid_x = int((left_bound + right_bound) / 2)
            abs_x = rect.left + mid_x
            abs_y = rect.top + target_y

            self._activate_window(hwnd)
            time.sleep(0.1)
            ctypes.windll.user32.SetCursorPos(abs_x, abs_y)
            time.sleep(0.05)
            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.05)
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
            time.sleep(0.8)

            # 重新截图读取当前值
            try:
                r = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
                new_img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
                ocr_engine = self._get_test_ocr()
                if ocr_engine:
                    items = self._ocr_recognize_with_pos(ocr_engine, new_img)
                    norm_label = self._normalize_match_text(ocr_label)
                    new_val = None
                    for ocr_text, cx, cy in items:
                        if abs(cy - label_pos[1]) < 10 and cx > label_pos[0] and cx - label_pos[0] < 100:
                            if any(c.isdigit() or c == '.' for c in ocr_text):
                                try:
                                    new_val = float(ocr_text)
                                    break
                                except ValueError:
                                    continue
                    if new_val is not None:
                        cur_val = new_val
                        self._log(f"[测试]   圆形滑条: 迭代{iteration+1}, 当前值={cur_val}, 目标={tgt_val}")
                        # 二分调整范围
                        if cur_val > tgt_val:
                            right_bound = mid_x
                        else:
                            left_bound = mid_x
                    else:
                        self._log(f"[测试]   圆形滑条: 无法读取当前值，停止迭代")
                        break
            except Exception as e:
                self._log(f"[测试]   圆形滑条: 迭代读取失败: {e}")
                break

        # 最终点击标题让值生效
        self._click_ocr_in_game(hwnd, ocr_label)

    def _click_slider_area_to_value(self, hwnd, rect, ocr_label,
                                     value_pos, current_value, target_value,
                                     label_pos, win_w):
        """找不到滑块时的回退方案：点击滑条区域逐步逼近（简化版）"""
        # 在数值右侧区域尝试点击不同位置
        # 这是最简实现：直接点击滑条中间位置几次
        self._log(f"[重启] 圆形滑条回退: 无法精确控制，跳过 '{ocr_label}'")

    def _send_unicode_char(self, hwnd, ch):
        """发送单个Unicode字符到窗口"""
        import ctypes
        import time
        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(0, ord(ch), KEYEVENTF_UNICODE, 0)
        time.sleep(0.02)
        ctypes.windll.user32.keybd_event(0, ord(ch), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)

    def _set_smd_parameter(self, hwnd, item):
        """设置单个SMD参数（原力界面：控件在左，标题在右）"""
        import ctypes
        import ctypes.wintypes
        import time
        name = item.get('name', '')
        ocr_label = item.get('ocr_label', '')
        item_type = item.get('item_type', 'toggle')
        target_value = item.get('target_value', '')
        method = item.get('value_set_method', 'click')
        offset_x = int(item.get('offset_x', 0) or 0)
        offset_y = int(item.get('offset_y', 0) or 0)

        if not ocr_label:
            return

        self._log(f"[重启] 设置参数: {name} = {target_value} (类型:{item_type}, 方式:{method})")

        if method == 'click':
            # 开关/下拉框：控件在左，标题在右
            # 下拉框：需要先点击控件(当前值区域)展开列表，再选择目标值
            # 开关：直接点击控件区域即可切换
            if item_type == 'dropdown':
                # 下拉框操作（原力界面布局：[当前值 | ▼] ... 标题文字）
                # 1. OCR找到标题文字位置
                # 2. 在标题左侧找下拉箭头(▼)按钮并点击展开
                # 3. 在展开列表中找到目标值并点击
                self._log(f"[重启] 下拉框: 找标题'{ocr_label}'，展开后选'{target_value}'")
                try:
                    from PIL import ImageGrab
                    import numpy as np
                    import cv2
                    rect = ctypes.wintypes.RECT()
                    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))

                    if self._get_test_ocr():
                        items = self._ocr_recognize_with_pos(self._get_test_ocr(), img)
                        norm_label = self._normalize_match_text(ocr_label)
                        # 找标题文字位置
                        title_pos = None
                        title_text = ''
                        for ocr_text, cx, cy in items:
                            if norm_label in self._normalize_match_text(ocr_text):
                                title_pos = (cx, cy)
                                title_text = ocr_text
                                break
                        # 覆盖层：红色标签 + 绿色箭头范围
                        regions = []
                        if title_pos:
                            regions.append((*self._text_rect(rect, title_pos[0], title_pos[1], title_text),
                                            '#FF0000', title_text))
                            arrow_x = max(0, title_pos[0] - len(ocr_label) / 2 * 15 - 50)
                            arrow_y = title_pos[1] + 10
                            regions.append((rect.left + arrow_x - 15, rect.top + arrow_y - 15,
                                            rect.left + arrow_x + 15, rect.top + arrow_y + 15,
                                            '#00FF00', '箭头'))
                        self._show_overlay(regions, window_rect=rect)
                        if not title_pos:
                            self._log(f"[重启] 下拉框: 未找到标题 '{ocr_label}'")
                            return

                        # 3. 点击标题左侧固定偏移处的下拉箭头(▼)
                        # 原力界面布局: [当前值文本 | ▼] ... 标题文字
                        char_count = len(ocr_label)
                        text_half_width = int(char_count / 2 * 15)
                        arrow_x = max(0, title_pos[0] - text_half_width - 50 - offset_x)
                        arrow_y = title_pos[1] + 10 + offset_y
                        abs_x = rect.left + arrow_x
                        abs_y = rect.top + arrow_y
                        self._log(f"[重启] 下拉框: 点击固定偏移箭头位置 ({arrow_x}, {arrow_y})")
                        self._activate_window(hwnd)
                        time.sleep(0.2)
                        ctypes.windll.user32.SetCursorPos(abs_x, abs_y)
                        time.sleep(0.1)
                        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                        time.sleep(0.05)
                        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)

                        time.sleep(0.8)  # 等待下拉列表展开

                        # 4. 在展开的列表中找到目标值并点击
                        if target_value:
                            if not self._click_ocr_in_game(hwnd, target_value):
                                self._log(f"[重启] 下拉列表中未找到 '{target_value}'")
                except Exception as e:
                    self._log(f"[重启] 下拉框操作失败: {e}")
            elif item_type == 'toggle':
                # 蓝色开关：通过颜色检测判断当前状态（蓝色=开启，灰色/黑色=关闭）
                need_click = True
                try:
                    import cv2
                    import numpy as np
                    from PIL import ImageGrab
                    rect = ctypes.wintypes.RECT()
                    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))

                    if self._get_test_ocr():
                        items = self._ocr_recognize_with_pos(self._get_test_ocr(), img)
                        norm_label = self._normalize_match_text(ocr_label)
                        # 找到标签文字位置
                        label_pos = None
                        label_text = ''
                        for ocr_text, cx, cy in items:
                            if norm_label in self._normalize_match_text(ocr_text):
                                label_pos = (cx, cy)
                                label_text = ocr_text
                                break
                        # 覆盖层：红色标签
                        regions = []
                        if label_pos:
                            regions.append((*self._text_rect(rect, label_pos[0], label_pos[1], label_text),
                                            '#FF0000', label_text))
                        self._show_overlay(regions, window_rect=rect)
                        if label_pos:
                            # 开关控件在标签文字的左侧
                            # 根据标签文字长度和开关按钮大小动态计算扫描范围
                            # 原力界面布局: [开关按钮50px] [间距] [标签文字]
                            # scan_left = 标签中心 - 字数/2*15 - 开关宽度50
                            # scan_right = 标签中心 - 字数/2*15 - 间距10
                            import numpy as np
                            img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                            char_count = len(ocr_label)
                            text_half_width = int(char_count / 2 * 15)
                            switch_width = 50
                            switch_height = 30
                            scan_left = max(0, label_pos[0] - text_half_width - switch_width - offset_x)
                            scan_right = max(0, label_pos[0] - text_half_width - 10 - offset_x)
                            scan_top = max(0, label_pos[1] - switch_height // 2 + offset_y)
                            scan_bottom = min(img_cv.shape[0], label_pos[1] + switch_height // 2 + offset_y)
                            # 覆盖层：绿色开关扫描范围
                            self._show_overlay(
                                [(rect.left + scan_left, rect.top + scan_top,
                                  rect.left + scan_right, rect.top + scan_bottom,
                                  '#00FF00', '开关范围')],
                                window_rect=rect)
                            if scan_left < scan_right and scan_top < scan_bottom:
                                scan_roi = img_cv[scan_top:scan_bottom, scan_left:scan_right]
                                # 找蓝色像素（B>80, B>G+20, B>R+20）
                                blue_mask = (scan_roi[:, :, 0] > 80) & (scan_roi[:, :, 0] > scan_roi[:, :, 1] + 20) & (scan_roi[:, :, 0] > scan_roi[:, :, 2] + 20)
                                blue_pts = np.where(blue_mask)
                                if len(blue_pts[0]) > 0:
                                    blue_cx = int(np.median(blue_pts[1])) + scan_left
                                    blue_cy = int(np.median(blue_pts[0])) + scan_top
                                    sample_left = max(0, blue_cx - 12)
                                    sample_right = min(img_cv.shape[1], blue_cx + 12)
                                    sample_top = max(0, blue_cy - 6)
                                    sample_bottom = min(img_cv.shape[0], blue_cy + 6)
                                    sample_roi = img_cv[sample_top:sample_bottom, sample_left:sample_right]
                                    mean_bgr = sample_roi.mean(axis=(0, 1))
                                    b, g, r = mean_bgr
                                    is_blue = (b > 80) and (b > g + 20) and (b > r + 20)
                                    self._log(f"[重启] 蓝色开关 '{name}' 颜色采样 位置=({blue_cx},{blue_cy}) B={b:.0f} G={g:.0f} R={r:.0f}, "
                                                 f"{'蓝色=开启' if is_blue else '非蓝=关闭'}")
                                    want_on = target_value in ('开启', '1', 'true', 'True', 'on', 'ON')
                                    if is_blue and want_on:
                                        self._log(f"[重启] 蓝色开关 '{name}' 已是开启状态，跳过")
                                        need_click = False
                                    elif not is_blue and not want_on:
                                        self._log(f"[重启] 蓝色开关 '{name}' 已是关闭状态，跳过")
                                        need_click = False
                                    else:
                                        self._log(f"[重启] 蓝色开关 '{name}' 目标{'开启' if want_on else '关闭'}，执行点击")
                                else:
                                    self._log(f"[重启] 蓝色开关 '{name}' 未检测到蓝色像素，跳过检测直接点击")
                except Exception as e:
                    self._log(f"[重启] 检测蓝色开关状态失败，继续点击: {e}")
                if need_click:
                    self._click_ocr_in_game(hwnd, ocr_label)
            elif item_type == 'check_toggle':
                # 勾选开关：通过检测白色对勾像素判断当前状态（有对勾=开启，无对勾=关闭）
                need_click = True
                try:
                    import cv2
                    import numpy as np
                    from PIL import ImageGrab
                    rect = ctypes.wintypes.RECT()
                    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))

                    if self._get_test_ocr():
                        items = self._ocr_recognize_with_pos(self._get_test_ocr(), img)
                        norm_label = self._normalize_match_text(ocr_label)
                        # 找到标签文字位置
                        label_pos = None
                        label_text = ''
                        for ocr_text, cx, cy in items:
                            if norm_label in self._normalize_match_text(ocr_text):
                                label_pos = (cx, cy)
                                label_text = ocr_text
                                break
                        # 覆盖层：红色标签
                        regions = []
                        if label_pos:
                            regions.append((*self._text_rect(rect, label_pos[0], label_pos[1], label_text),
                                            '#FF0000', label_text))
                        self._show_overlay(regions, window_rect=rect)
                        if label_pos:
                            # 勾选框在标签文字的左侧
                            # 布局: [勾选框] [间距] [标签文字]
                            img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                            char_count = len(ocr_label)
                            text_half_width = int(char_count / 2 * 15)
                            box_width = 20
                            box_height = 20
                            scan_left = max(0, label_pos[0] - text_half_width - box_width - 20 - offset_x)
                            scan_right = max(0, label_pos[0] - text_half_width - 5 - offset_x)
                            scan_top = max(0, label_pos[1] - box_height // 2 + 10 + offset_y)
                            scan_bottom = min(img_cv.shape[0], label_pos[1] + box_height // 2 + 10 + offset_y)
                            # 覆盖层：绿色勾选框范围
                            self._show_overlay(
                                [(rect.left + scan_left, rect.top + scan_top,
                                  rect.left + scan_right, rect.top + scan_bottom,
                                  '#00FF00', '勾选范围')],
                                window_rect=rect)
                            if scan_left < scan_right and scan_top < scan_bottom:
                                scan_roi = img_cv[scan_top:scan_bottom, scan_left:scan_right]
                                # 找白色/浅色像素（对勾颜色），对勾通常是白色或浅灰色
                                white_mask = (scan_roi[:, :, 2] > 180) & (scan_roi[:, :, 1] > 180) & (scan_roi[:, :, 0] > 180)
                                white_pts = np.where(white_mask)
                                white_count = len(white_pts[0])
                                total_pixels = scan_roi.shape[0] * scan_roi.shape[1]
                                # 白色像素占比超过一定阈值认为有对勾（开启状态）
                                check_ratio = white_count / total_pixels if total_pixels > 0 else 0
                                is_checked = check_ratio > 0.08
                                self._log(f"[重启] 勾选开关 '{name}' 检测: 白色像素{white_count}/{total_pixels}, "
                                         f"占比={check_ratio:.2%}, {'已勾选=开启' if is_checked else '未勾选=关闭'}")
                                want_on = target_value in ('开启', '1', 'true', 'True', 'on', 'ON')
                                if is_checked and want_on:
                                    self._log(f"[重启] 勾选开关 '{name}' 已是开启状态，跳过")
                                    need_click = False
                                elif not is_checked and not want_on:
                                    self._log(f"[重启] 勾选开关 '{name}' 已是关闭状态，跳过")
                                    need_click = False
                                else:
                                    self._log(f"[重启] 勾选开关 '{name}' 目标{'开启' if want_on else '关闭'}，执行点击")
                            else:
                                self._log(f"[重启] 勾选开关 '{name}' 扫描区域无效，跳过检测直接点击")
                except Exception as e:
                    self._log(f"[重启] 检测勾选开关状态失败，继续点击: {e}")
                if need_click:
                    self._click_ocr_in_game(hwnd, ocr_label)
            elif item_type == 'special':
                # 特殊操作：以 ocr_label 为锚点，在其下方列表区域中寻找已选脚本名并点击
                # 目标值取当前脚本类型的已选脚本名（从内存中读取）
                script_type = self.script_type_var.get() if hasattr(self, 'script_type_var') else "恶化"
                target_value = self._script_selections.get(script_type, "")
                if not target_value:
                    # 回退到配置文件中的值
                    tab_info = SMD_TABS[self.current_tab_index]
                    target_value = tab_info.get("selected_script", "")
                if not target_value:
                    self._log(f"[重启] 特殊操作: 未找到已选脚本名，跳过")
                    return
                self._log(f"[重启] 特殊操作: 查找脚本 '{target_value}'（类型: {script_type}）")
                # 列表范围：锚点下方，宽200像素，高600像素
                # 找不到则向下滚动继续寻找，直到列表底部
                try:
                    from PIL import ImageGrab
                    import numpy as np
                    import cv2
                    rect = ctypes.wintypes.RECT()
                    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    win_w = rect.right - rect.left
                    win_h = rect.bottom - rect.top

                    # 先找到 ocr_label 的位置作为锚点
                    img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
                    anchor_pos = None
                    if self._get_test_ocr():
                        items = self._ocr_recognize_with_pos(self._get_test_ocr(), img)
                        norm_label = self._normalize_match_text(ocr_label)
                        anchor_text = ''
                        for ocr_text, cx, cy in items:
                            if norm_label in self._normalize_match_text(ocr_text):
                                anchor_pos = (cx, cy)
                                anchor_text = ocr_text
                                break
                        # 覆盖层：红色锚点
                        if anchor_pos:
                            self._show_overlay(
                                [(*self._text_rect(rect, anchor_pos[0], anchor_pos[1], anchor_text),
                                  '#FF0000', anchor_text)],
                                window_rect=rect)

                    if not anchor_pos:
                        self._log(f"[重启] 特殊操作: 未找到锚点 '{ocr_label}'")
                        return

                    # 列表区域：锚点下方，宽200像素，高600像素
                    list_left = max(0, anchor_pos[0] - 200)
                    list_right = min(win_w, anchor_pos[0] + 50)
                    list_top = anchor_pos[1] + 10
                    list_bottom = min(win_h, list_top + 650)

                    max_scroll_attempts = 10
                    scroll_step = 60  # 每次滚动像素

                    # 先滚到列表顶部，避免漏找
                    self._activate_window(hwnd)
                    scroll_x = rect.left + (list_left + list_right) // 2
                    scroll_y = rect.top + (list_top + list_bottom) // 2
                    ctypes.windll.user32.SetCursorPos(scroll_x, scroll_y)
                    time.sleep(0.1)
                    WHEEL_DELTA = 120
                    for _ in range(20):
                        ctypes.windll.user32.mouse_event(0x0800, 0, 0, WHEEL_DELTA, 0)
                        time.sleep(0.05)
                    time.sleep(0.3)

                    for attempt in range(max_scroll_attempts):
                        # 截取列表区域
                        abs_left = rect.left + list_left
                        abs_top = rect.top + list_top
                        abs_right = rect.left + list_right
                        abs_bottom = rect.top + list_bottom
                        list_img = ImageGrab.grab(bbox=(abs_left, abs_top, abs_right, abs_bottom))

                        if self._get_test_ocr():
                            list_items = self._ocr_recognize_with_pos(self._get_test_ocr(), list_img)
                            # 覆盖层：红色标目标脚本
                            t_norm = self._normalize_script_name(self._strip_bin(target_value))
                            for lt, lcx, lcy in list_items:
                                if t_norm in self._normalize_script_name(lt):
                                    self._show_overlay(
                                        [(abs_left + lcx - len(lt)*7, abs_top + lcy - 11,
                                          abs_left + lcx + len(lt)*7, abs_top + lcy + 11,
                                          '#FF0000', lt)],
                                        window_rect=rect)
                                    break
                            t_norm = self._normalize_script_name(self._strip_bin(target_value))
                            best_match = None
                            best_diff = 999
                            for ocr_text, cx, cy in list_items:
                                o_norm = self._normalize_script_name(self._strip_bin(ocr_text))
                                if not t_norm or not o_norm:
                                    continue
                                is_match = (t_norm in o_norm or o_norm in t_norm)
                                if not is_match and len(t_norm) >= 3 and len(o_norm) >= 3:
                                    min_len = min(len(t_norm), len(o_norm))
                                    is_match = t_norm[:min_len] == o_norm[:min_len]
                                if is_match:
                                    diff = abs(len(o_norm) - len(t_norm))
                                    if diff < best_diff:
                                        best_diff = diff
                                        best_match = (ocr_text, cx, cy)
                            if best_match:
                                ocr_text, cx, cy = best_match
                                # 找到了，点击
                                click_x = abs_left + cx
                                click_y = abs_top + cy
                                self._activate_window(hwnd)
                                time.sleep(0.2)
                                ctypes.windll.user32.SetCursorPos(click_x, click_y)
                                time.sleep(0.1)
                                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                                time.sleep(0.05)
                                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                                self._log(f"[重启] 特殊操作: 在列表中找到 '{target_value}' (OCR: '{ocr_text}') 并点击")
                                return

                        # 没找到，向下滚动列表区域
                        self._log(f"[重启] 特殊操作: 第{attempt + 1}次滚动寻找 '{target_value}'")
                        self._activate_window(hwnd)
                        # 在列表区域中心滚轮向下
                        scroll_x = rect.left + (list_left + list_right) // 2
                        scroll_y = rect.top + (list_top + list_bottom) // 2
                        ctypes.windll.user32.SetCursorPos(scroll_x, scroll_y)
                        time.sleep(0.1)
                        # 滚轮向下 (-WHEEL_DELTA)
                        WHEEL_DELTA = 300
                        ctypes.windll.user32.mouse_event(0x0800, 0, 0, -WHEEL_DELTA, 0)
                        time.sleep(0.5)

                    self._log(f"[重启] 特殊操作: 滚动到底仍未找到 '{target_value}'")
                except Exception as e:
                    self._log(f"[重启] 特殊操作失败: {e}")

            else:
                self._click_ocr_in_game(hwnd, ocr_label)

        elif method == 'ctrl_click':
            # 滑块操作（控件在左，标题在右）：
            # 1. Ctrl+左键点击控件（滑块/值区域）→ 变为输入框
            # 2. 输入目标值
            # 3. 点击右侧标题文字让输入值生效
            try:
                from PIL import ImageGrab
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))

                if self._get_test_ocr():
                    items = self._ocr_recognize_with_pos(self._get_test_ocr(), img)
                    ctrl_pos = None
                    ctrl_text = ''
                    for ocr_text, cx, cy in items:
                        if ocr_label in ocr_text:
                            ctrl_pos = (cx, cy)
                            ctrl_text = ocr_text
                            break
                    # 覆盖层：红色标签
                    if ctrl_pos:
                        self._show_overlay(
                            [(*self._text_rect(rect, ctrl_pos[0], ctrl_pos[1], ctrl_text),
                              '#FF0000', ctrl_text)],
                            window_rect=rect)

                    if not ctrl_pos:
                        self._log(f"[重启] 未找到滑块 '{ocr_label}'")
                        return

                    char_count = len(ocr_label)
                    text_half_width = int(char_count / 2 * 15)
                    input_width = 100
                    # input_height = 20

                    click_left = max(0, ctrl_pos[0] - text_half_width - input_width - offset_x)
                    click_top = max(0, ctrl_pos[1] + offset_y)
                    abs_x = rect.left + click_left
                    abs_y = rect.top + click_top

                    # 步骤1: Ctrl+左键点击控件区域
                    self._activate_window(hwnd)
                    time.sleep(0.2)

                    # 按下Ctrl
                    VK_CONTROL = 0x11
                    INPUT_KEYBOARD = 1
                    KEYEVENTF_SCANCODE = 0x0008
                    KEYEVENTF_KEYUP = 0x0002
                    ctrl_scan = ctypes.windll.user32.MapVirtualKeyW(VK_CONTROL, 0)

                    class MOUSEINPUT(ctypes.Structure):
                        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                                    ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                                    ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]
                    class KEYBDINPUT(ctypes.Structure):
                        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                                    ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                                    ("dwExtraInfo", ctypes.c_size_t)]
                    class HARDWAREINPUT(ctypes.Structure):
                        _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort),
                                    ("wParamH", ctypes.c_ushort)]
                    class _IU(ctypes.Union):
                        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]
                    class _INP(ctypes.Structure):
                        _fields_ = [("type", ctypes.c_ulong), ("u", _IU)]
                    inp_size = ctypes.sizeof(_INP)

                    # Ctrl down
                    ci = _INP(); ci.type = INPUT_KEYBOARD
                    ci.u.ki.wScan = ctrl_scan; ci.u.ki.dwFlags = KEYEVENTF_SCANCODE
                    ctypes.windll.user32.SendInput(1, ctypes.byref(ci), inp_size)
                    time.sleep(0.1)

                    # 左键点击控件位置
                    ctypes.windll.user32.SetCursorPos(abs_x, abs_y)
                    time.sleep(0.1)
                    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                    time.sleep(0.05)
                    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                    time.sleep(0.3)

                    # Ctrl up
                    ci2 = _INP(); ci2.type = INPUT_KEYBOARD
                    ci2.u.ki.wScan = ctrl_scan; ci2.u.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
                    ctypes.windll.user32.SendInput(1, ctypes.byref(ci2), inp_size)
                    time.sleep(0.5)

                    # 步骤2: 输入目标值
                    if target_value:
                        for ch in target_value:
                            self._send_unicode_char(hwnd, ch)
                            time.sleep(0.05)
                        time.sleep(0.3)

                    # 步骤3: 点击右侧标题文字让值生效
                    self._click_ocr_in_game(hwnd, ocr_label)
                    time.sleep(0.3)

                    self._log(f"[重启] 滑块: Ctrl+点击 '{ocr_label}'，输入 '{target_value}'，点击标题生效")
                    return
            except Exception as e:
                self._log(f"[重启] 设置参数 '{name}' 失败: {e}")
        elif method == 'round_slider':
            # 圆形滑条：标题在左，数值在中（只读），滑条在右
            # 数值无法点击编辑，只能通过点击滑条进度位置或拖拽圆形滑块来变动
            # 策略：找到当前数值，计算目标比例，点击滑条对应位置
            try:
                import ctypes
                import ctypes.wintypes
                from PIL import ImageGrab
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                win_w = rect.right - rect.left
                win_h = rect.bottom - rect.top
                img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))

                if self._get_test_ocr():
                    items = self._ocr_recognize_with_pos(self._get_test_ocr(), img)
                    norm_label = self._normalize_match_text(ocr_label)

                    # 1. 找到标签位置
                    label_pos = None
                    label_text = ''
                    for ocr_text, cx, cy in items:
                        if norm_label in self._normalize_match_text(ocr_text):
                            label_pos = (cx, cy)
                            label_text = ocr_text
                            break
                    if not label_pos:
                        self._log(f"[重启] 圆形滑条: 未找到标签 '{ocr_label}'")
                        return

                    # 2. 找同行的数值文字（包含数字，在标签右侧）
                    current_value = None
                    value_pos = None
                    value_text = ''
                    for ocr_text, cx, cy in items:
                        if abs(cy - label_pos[1] - offset_y) < 10 and cx > label_pos[0] + offset_x and cx - label_pos[0] < 100 + offset_x:
                            if any(c.isdigit() or c == '.' for c in ocr_text):
                                current_value = ocr_text
                                value_pos = (cx, cy)
                                value_text = ocr_text
                                break

                    # 3. 找圆形滑块位置（同行、在数值右侧、通过区域采样白色像素检测）
                    thumb_pos = self._find_slider_thumb(img, value_pos, label_pos, win_w, win_h, current_value, offset_x, offset_y)

                    # 覆盖层：红色标签 + 蓝色目标值范围 + 绿色当前值 + 蓝色滑块范围
                    regions = []
                    if label_pos:
                        regions.append((*self._text_rect(rect, label_pos[0], label_pos[1], label_text),
                                        '#FF0000', label_text))
                    if value_pos:
                        regions.append((*self._text_rect(rect, value_pos[0], value_pos[1], value_text),
                                        '#00FF00', value_text))
                        # 蓝色：数值搜索范围（标签右侧100px内同行）
                        char_len = len(value_text) if value_text else 3
                        srch_left = max(0, value_pos[0] - char_len * 5)
                        srch_right = min(win_w, value_pos[0] + char_len * 5)
                        regions.append((rect.left + srch_left, rect.top + value_pos[1] - 15,
                                        rect.left + srch_right, rect.top + value_pos[1] + 15,
                                        '#00BFFF', '数值范围'))
                    if thumb_pos:
                        # 蓝色：滑块搜索范围（数值右侧到窗口边缘）
                        sl_left = max(0, (value_pos[0] if value_pos else label_pos[0]) + 80)
                        regions.append((rect.left + sl_left, rect.top + label_pos[1] - 20,
                                        rect.right - 10, rect.top + label_pos[1] + 20,
                                        '#00BFFF', '滑块范围'))
                    self._show_overlay(regions, window_rect=rect)

                    if thumb_pos and current_value and target_value:
                        try:
                            cur_val = float(current_value)
                            tgt_val = float(target_value)
                            self._log(f"[重启] 圆形滑条 '{name}': 当前值={cur_val}, 目标值={tgt_val}, 滑块位置={thumb_pos}")
                        except ValueError:
                            self._log(f"[重启] 圆形滑条: 无法解析数值 '{current_value}' 或 '{target_value}'")
                            return

                        if abs(cur_val - tgt_val) < 0.001:
                            self._log(f"[重启] 圆形滑条 '{name}' 值已一致，跳过")
                            return

                        # 4. 计算滑条区域范围（通过多次截图或估算）
                        # 滑条通常在数值右侧到窗口右边缘之间
                        # 简化方案：从当前滑块位置开始，向左/右拖拽到目标位置
                        # 使用比例估算：假设滑条范围是从滑块可见区域的最左到最右
                        # 更可靠的方式：多次小步拖拽并每次读取数值，直到接近目标值

                        self._drag_slider_to_value(hwnd, rect, ocr_label, thumb_pos,
                                                   cur_val, tgt_val, label_pos)
                        return
                    else:
                        # 找不到滑块，回退：通过点击滑条区域（数值右侧一定范围）来逼近
                        self._log(f"[重启] 圆形滑条: 未找到滑块，尝试点击滑条区域逼近")
                        self._click_slider_area_to_value(hwnd, rect, ocr_label,
                                                       value_pos, current_value, target_value,
                                                       label_pos, win_w)
                        return
            except Exception as e:
                self._log(f"[重启] 设置圆形滑条 '{name}' 失败: {e}")
        elif method == 'slider_drag':
            self._log(f"[重启] 滑块拖拽暂未实现: {name}")

    def _on_test_selected(self):
        """测试列表中选中的单个参数"""
        sel = self.items_listbox.curselection()
        if not sel:
            self._log("[测试] 请先在列表中选择一个参数")
            return
        idx = sel[0]
        tab = SMD_TABS[self.current_tab_index]
        tab_key = tab["key"]
        items = self.config_data.get(tab_key, {}).get("items", [])
        if idx >= len(items):
            return
        item = items[idx]

        ocr_engine = self._get_test_ocr()
        if not ocr_engine:
            return

        game_title = ''
        if self.game_monitor_ref:
            game_title = self.game_monitor_ref.config.window.get('title', '')
        if not game_title:
            config_path = os.path.join(_BASE_DIR, 'configs', 'default.json')
            if os.path.isfile(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                    game_title = cfg.get('window', {}).get('title', '')
                except Exception:
                    pass
        if not game_title:
            self._log("[测试] 未配置游戏窗口标题")
            return

        import ctypes
        import ctypes.wintypes
        import time
        hwnd = ctypes.windll.user32.FindWindowW(None, game_title)
        if not hwnd:
            self._log(f"[测试] 未找到游戏窗口: {game_title}")
            return

        ctypes.windll.user32.ShowWindow(hwnd, 9)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)

        label = item.ocr_label or item.name
        self._log(f"[测试] 参数: {item.name} (类型={TYPE_MAP.get(item.item_type, item.item_type)}, 目标值={item.target_value}, ocr_label='{label}')")

        # 统一调用实际执行逻辑，所有类型检测都在 _set_smd_parameter 内部处理
        try:
            self._set_smd_parameter(hwnd, item.to_dict())
            # 特殊操作不输出"完成"（内部有自己的日志）
            if item.value_set_method != 'special':
                self._log(f"[测试] ✓ 完成 '{label}'")
        except Exception as e:
            self._log(f"[测试] ✗ 失败 '{label}': {e}")

    def _on_test_tab(self):
        """测试当前标签页的所有参数"""
        import ctypes
        import time

        ocr_engine = self._get_test_ocr()
        if not ocr_engine:
            return

        game_title = ''
        if self.game_monitor_ref:
            game_title = self.game_monitor_ref.config.window.get('title', '')
        if not game_title:
            # 尝试从配置文件读取
            config_path = os.path.join(_BASE_DIR, 'configs', 'default.json')
            if os.path.isfile(config_path):
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                    game_title = cfg.get('window', {}).get('title', '')
                except Exception:
                    pass
        if not game_title:
            self._log("[测试] 未配置游戏窗口标题，请先在主界面设置")
            return

        hwnd = ctypes.windll.user32.FindWindowW(None, game_title)
        if not hwnd:
            self._log(f"[测试] 未找到游戏窗口: {game_title}")
            return

        tab = SMD_TABS[self.current_tab_index]
        tab_key = tab["key"]
        tab_name = tab["name"]
        items = self.config_data.get(tab_key, {}).get("items", [])
        if not items:
            self._log("[测试] 当前标签页没有参数")
            return

        # 前显游戏窗口
        ctypes.windll.user32.ShowWindow(hwnd, 9)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.5)

        # 检测原力配置界面是否已打开
        force_open = False
        try:
            from PIL import ImageGrab
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
            text = self._ocr_recognize(ocr_engine, img)
            self._log(f"[测试] 原力界面OCR检测: {text[:200]}")
            for tab in SMD_TABS:
                if tab["name"] in text or tab["name"][:2] in text:
                    force_open = True
                    break
        except Exception:
            pass

        VK_F11 = 0x7A
        if not force_open:
            self._log("[测试] 原力界面未打开，发送F11")
            self._send_key_to_game(hwnd, VK_F11)
            time.sleep(2)

        # 切换到标签页
        self._log(f"[测试] 切换到标签页 '{tab_name}'")
        if not self._test_click_in_game(hwnd, tab_name):
            self._log(f"[测试] 未找到标签 '{tab_name}'")
            return
        time.sleep(1.5)

        # 逐个测试
        results = []
        for item in items:
            label = item.ocr_label or item.name
            self._log(f"[测试] 参数: {item.name} | 类型={TYPE_MAP.get(item.item_type, item.item_type)} | "
                      f"目标值={item.target_value} | 方式={METHOD_MAP.get(item.value_set_method, item.value_set_method)} | "
                      f"ocr_label='{label}'")

            # 统一调用实际执行逻辑，所有类型检测都在 _set_smd_parameter 内部处理
            try:
                self._set_smd_parameter(hwnd, item.to_dict())
                results.append(f"✓ {item.name} ({label})")
                if item.value_set_method != 'special':
                    self._log(f"[测试] ✓ 完成 '{label}'")
            except Exception as e:
                results.append(f"✗ {item.name} ({label})")
                self._log(f"[测试] ✗ 失败 '{label}': {e}")
            time.sleep(0.5)

        # 测试完成后不关闭F11，保持原力界面
        self._log("[测试] 测试完成:")
        for r in results:
            self._log(f"[测试]   {r}")

    # ==================== 拖放排序 ====================

    def _on_item_press(self, event):
        """鼠标按下：记录拖放起始位置"""
        # 检查是否点击了列表项
        index = self.items_listbox.nearest(event.y)
        if index < 0:
            self._drag_start_index = None
            return
        self._drag_start_index = index
        self._dragging = False
        # 选中当前项
        self.items_listbox.selection_clear(0, tk.END)
        self.items_listbox.selection_set(index)

    def _on_item_motion(self, event):
        """鼠标拖动：仅标记拖动中（不实时交换）"""
        if self._drag_start_index is None:
            return
        self._dragging = True

    def _on_item_release(self, event):
        """鼠标释放：执行一次插入操作"""
        if not self._dragging or self._drag_start_index is None:
            self._drag_start_index = None
            self._dragging = False
            return

        tab_key = self._get_current_tab_key()
        if tab_key is None:
            self._drag_start_index = None
            self._dragging = False
            return

        items = self.config_data[tab_key]["items"]
        if not items:
            self._drag_start_index = None
            self._dragging = False
            return

        target_index = self.items_listbox.nearest(event.y)
        if target_index < 0 or target_index == self._drag_start_index:
            self._drag_start_index = None
            self._dragging = False
            return

        # 从原位置取出，插入到目标位置
        start = self._drag_start_index
        item = items.pop(start)
        # pop后目标索引需要调整
        adjusted_target = target_index - 1 if target_index > start else target_index
        items.insert(adjusted_target, item)

        # 刷新列表显示
        self._refresh_items_list()

        # 保持选中状态（移动到了新位置）
        self.items_listbox.selection_clear(0, tk.END)
        self.items_listbox.selection_set(adjusted_target)

        self._drag_start_index = None
        self._dragging = False

    # ==================== 保存/加载 ====================

    def _build_save_dict(self):
        """构建保存用的字典结构"""
        result = {}
        for tab in SMD_TABS:
            key = tab["key"]
            data = self.config_data[key]
            extra = dict(data.get("extra", {}))
            result[key] = {
                "items": [item.to_dict() for item in data["items"]],
                "extra": extra,
            }
        # script_selections 和 selected_script 同步保存
        if "script_edit" not in result:
            result["script_edit"] = {"items": [], "extra": {}}
        extra = result["script_edit"]["extra"]
        if self._script_selections:
            extra["script_selections"] = dict(self._script_selections)
        # selected_script 必须和当前 script_type 对应的 script_selections 一致
        script_type = extra.get("script_type", "恶化")
        if self._script_selections and script_type in self._script_selections:
            extra["selected_script"] = self._script_selections[script_type]
        return result

    def _load_from_dict(self, data):
        """从字典加载数据"""
        for tab in SMD_TABS:
            key = tab["key"]
            if key in data:
                tab_data = data[key]
                items = [CompareItem.from_dict(d) for d in tab_data.get("items", [])]
                extra = tab_data.get("extra", {})
                # script_selections 只从 script_edit 标签加载，清除其他标签中的残留
                if "script_selections" in extra:
                    if key == "script_edit":
                        self._script_selections.update(extra["script_selections"])
                    del extra["script_selections"]
                self.config_data[key] = {
                    "items": items,
                    "extra": extra,
                }
            else:
                self.config_data[key] = {
                    "items": [],
                    "extra": {},
                }
        # 加载完成后同步 script_edit 的 selected_script
        script_edit_extra = self.config_data.get("script_edit", {}).get("extra", {})
        st = script_edit_extra.get("script_type", "恶化")
        if self._script_selections and st in self._script_selections:
            script_edit_extra["selected_script"] = self._script_selections[st]

    def _load_from_file(self, filepath):
        """从文件加载配置"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._load_from_dict(data)
            self.config_path = filepath
            self._refresh_items_list()
            return True
        except Exception as e:
            messagebox.showerror("加载失败", f"无法加载配置文件：\n{e}", parent=self)
            return False

    def _save_to_file(self, filepath):
        """保存配置到文件"""
        try:
            data = self._build_save_dict()
            # 确保目录存在
            dir_path = os.path.dirname(filepath)
            if dir_path and not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.config_path = filepath
            return True
        except Exception as e:
            messagebox.showerror("保存失败", f"无法保存配置文件：\n{e}", parent=self)
            return False

    def _log(self, message):
        """在编辑器日志区域输出消息（限制最大500行，防止内存增长）"""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line)
        # 限制最大行数，删除最早的行
        total_lines = int(self.log_text.index('end-1c').split('.')[0])
        max_lines = 500
        if total_lines > max_lines:
            self.log_text.delete('1.0', f'{total_lines - max_lines}.0')
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def release_resources(self):
        """释放资源（OCR引擎、日志处理器等）"""
        if hasattr(self, '_test_ocr_engine') and self._test_ocr_engine is not None:
            del self._test_ocr_engine
            self._test_ocr_engine = None
        # 清空日志文本框
        if hasattr(self, 'log_text') and self.log_text:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.delete('1.0', tk.END)
            self.log_text.configure(state=tk.DISABLED)

    def _on_close(self):
        """窗口关闭时自动保存配置并释放资源"""
        # 自动保存配置（静默，不弹窗）
        try:
            self._save_to_file(self.config_path)
            # 通知父窗口
            if self.on_save_callback:
                self.on_save_callback(self.config_path, self._build_save_dict())
        except Exception:
            pass
        self.release_resources()
        self.destroy()

    def get_smd_config(self):
        """返回当前配置字典（供外部同步使用）"""
        return self._build_save_dict()

    def set_smd_config(self, config_dict):
        """从外部设置配置（供外部同步使用）"""
        self._load_from_dict(config_dict)
        self.config_data = {}
        for tab in SMD_TABS:
            key = tab["key"]
            if key in config_dict:
                tab_data = config_dict[key]
                items = [CompareItem.from_dict(d) for d in tab_data.get("items", [])]
                self.config_data[key] = {
                    "items": items,
                    "extra": tab_data.get("extra", {}),
                }
            else:
                self.config_data[key] = {
                    "items": [],
                    "extra": {},
                }
        self._save_to_file(self.config_path)
        self._refresh_items_list()

    def _refresh_save_targets(self):
        """刷新保存目标下拉列表（隐藏默认 smd_settings.json）"""
        smd_dir = os.path.join(_DATA_DIR, 'smd_config')
        files = []
        if os.path.isdir(smd_dir):
            try:
                files = sorted([f for f in os.listdir(smd_dir) if f.endswith('.json') and f != 'smd_settings.json'])
            except Exception:
                pass
        self._save_target_combo['values'] = files
        # 默认选中当前配置文件名
        if self.config_path:
            name = os.path.basename(self.config_path)
            if name in files:
                self._save_target_var.set(name)
            elif files:
                self._save_target_var.set(files[0])
            else:
                self._save_target_var.set('')

    def _on_save_config(self):
        """保存配置到下拉框选中的文件（支持手动输入新文件名）"""
        target = self._save_target_var.get().strip()
        if not target:
            messagebox.showwarning("提示", "请选择或输入保存目标文件名", parent=self)
            return
        if not target.endswith('.json'):
            target += '.json'
        smd_dir = os.path.join(_DATA_DIR, 'smd_config')
        os.makedirs(smd_dir, exist_ok=True)
        filepath = os.path.join(smd_dir, target)
        if self._save_to_file(filepath):
            messagebox.showinfo("保存成功", f"配置已保存到：\n{filepath}", parent=self)
            # 刷新保存目标列表
            self._refresh_save_targets()
            self._save_target_var.set(target)
            # 通知父窗口
            if self.on_save_callback:
                self.on_save_callback(filepath, self._build_save_dict())

    def _on_restore_default(self):
        """恢复默认配置：重新加载 smd_settings.json"""
        if self.config_path == self.default_config_path:
            messagebox.showinfo("提示", "当前已是默认配置", parent=self)
            return
        if messagebox.askyesno("确认", "恢复默认配置将丢弃当前修改，是否继续？", parent=self):
            self._load_from_file(self.default_config_path)
            self._log("[配置] 已恢复默认配置")


# ==================== 脚本元数据编辑器 ====================

# 脚本元数据保存目录
SCRIPT_META_DIR = os.path.join(_DATA_DIR, 'script_meta')


class ScriptMetaEditor(tk.Toplevel):
    """脚本元数据编辑器（傻瓜式：填表保存，文件名不带额外信息）

    元数据字段：
    - 适用副本（多选或自由输入）
    - 适用模式
    - 作者
    - 更新记录（按时间倒序）
    - 备注

    保存位置：game_monitor/script_meta/{脚本名去掉.bin}.json
    上传时：把 script_meta 目录整体打包上传
    获取时：下载后放入 script_meta 目录即可
    """

    # 预设副本列表
    PRESET_DUNGEONS = [
        "纽约州长图书馆", "联邦空地储备", "时代广场", "林肯隧道",
        "俄国大使馆", "麦迪逊广场花园", "中央车站", "地狱厨房",
        "暗区", "冲突", "占领", "传奇难度", "英雄难度",
    ]

    # 预设模式
    PRESET_MODES = [
        "单人", "双人", "四人", "全匹配",
        "普通", "困难", "挑战", "英雄", "传奇",
    ]

    def __init__(self, parent, script_name):
        super().__init__(parent)
        self.script_name = script_name
        self.meta_key = script_name.replace('.bin', '')
        self._script_hash = self._calc_file_hash()
        self.title(f"脚本信息 - {script_name}")
        self.configure(bg=COLORS["bg"])
        self.geometry("520x580")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # 确保元数据目录存在
        os.makedirs(SCRIPT_META_DIR, exist_ok=True)

        self._create_widgets()
        self._load_meta()
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - 420) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - 540) // 2
        self.geometry(f"+{max(0,x)}+{max(0,y)}")

    def _calc_file_hash(self):
        """计算脚本文件的MD5（前8位），用于跨文件名匹配"""
        script_path = os.path.join(r"C:\Spc", self.script_name)
        if os.path.isfile(script_path):
            try:
                import hashlib
                with open(script_path, 'rb') as f:
                    return hashlib.md5(f.read()).hexdigest()[:8]
            except Exception:
                pass
        return ""

    def _create_widgets(self):
        pad = {"padx": 15, "pady": 3}
        bg = COLORS["bg"]
        fg = COLORS["fg"]
        entry_bg = COLORS["entry_bg"]

        # 脚本名（只读）
        tk.Label(self, text="脚本文件:", bg=bg, fg=fg,
                 font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky=tk.E, **pad)
        tk.Label(self, text=self.script_name, bg=bg, fg="#4ecca3",
                 font=("Consolas", 9)).grid(row=0, column=1, columnspan=2, sticky=tk.W, **pad)

        # 文件hash（用于跨文件名匹配，只读显示）
        hash_text = self._script_hash if self._script_hash else "未计算"
        tk.Label(self, text="文件标识:", bg=bg, fg=fg,
                 font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky=tk.E, **pad)
        tk.Label(self, text=hash_text, bg=bg, fg="#888888",
                 font=("Consolas", 9)).grid(row=1, column=1, columnspan=2, sticky=tk.W, **pad)

        # 适用副本（可多选的Listbox）
        tk.Label(self, text="适用副本:", bg=bg, fg=fg,
                 font=("Microsoft YaHei UI", 9)).grid(row=2, column=0, sticky=tk.NE, **pad)
        dungeon_frame = tk.Frame(self, bg=bg)
        dungeon_frame.grid(row=2, column=1, columnspan=2, sticky=tk.W, **pad)
        self.dungeon_entry = tk.Entry(dungeon_frame, width=30, bg=entry_bg, fg=fg,
                                       font=("Microsoft YaHei UI", 9), insertbackground=fg)
        self.dungeon_entry.pack(side=tk.LEFT)
        self.dungeon_entry.bind("<Return>", self._add_dungeon)
        self.dungeon_listbox = tk.Listbox(dungeon_frame, height=3, width=30,
                                           bg=COLORS["listbox_bg"], fg=COLORS["listbox_fg"],
                                           selectbackground=COLORS["highlight_bg"],
                                           font=("Microsoft YaHei UI", 9), relief=tk.FLAT)
        self.dungeon_listbox.pack(side=tk.LEFT, padx=(5, 0))
        self.dungeon_listbox.bind("<Double-Button-1>", self._remove_dungeon)

        # 适用模式（同上）
        tk.Label(self, text="适用模式:", bg=bg, fg=fg,
                 font=("Microsoft YaHei UI", 9)).grid(row=3, column=0, sticky=tk.NE, **pad)
        mode_frame = tk.Frame(self, bg=bg)
        mode_frame.grid(row=3, column=1, columnspan=2, sticky=tk.W, **pad)
        self.mode_entry = tk.Entry(mode_frame, width=30, bg=entry_bg, fg=fg,
                                    font=("Microsoft YaHei UI", 9), insertbackground=fg)
        self.mode_entry.pack(side=tk.LEFT)
        self.mode_entry.bind("<Return>", self._add_mode)
        self.mode_listbox = tk.Listbox(mode_frame, height=3, width=30,
                                        bg=COLORS["listbox_bg"], fg=COLORS["listbox_fg"],
                                        selectbackground=COLORS["highlight_bg"],
                                        font=("Microsoft YaHei UI", 9), relief=tk.FLAT)
        self.mode_listbox.pack(side=tk.LEFT, padx=(5, 0))
        self.mode_listbox.bind("<Double-Button-1>", self._remove_mode)

        # 作者
        tk.Label(self, text="作者:", bg=bg, fg=fg,
                 font=("Microsoft YaHei UI", 9)).grid(row=4, column=0, sticky=tk.E, **pad)
        self.author_var = tk.StringVar()
        tk.Entry(self, textvariable=self.author_var, width=35, bg=entry_bg, fg=fg,
                 font=("Microsoft YaHei UI", 9), insertbackground=fg).grid(
            row=4, column=1, columnspan=2, sticky=tk.W, **pad)

        # 备注
        tk.Label(self, text="备注:", bg=bg, fg=fg,
                 font=("Microsoft YaHei UI", 9)).grid(row=5, column=0, sticky=tk.NE, **pad)
        self.remark_var = tk.StringVar()
        tk.Entry(self, textvariable=self.remark_var, width=35, bg=entry_bg, fg=fg,
                 font=("Microsoft YaHei UI", 9), insertbackground=fg).grid(
            row=5, column=1, columnspan=2, sticky=tk.W, **pad)

        # 更新记录
        tk.Label(self, text="更新记录:", bg=bg, fg=fg,
                 font=("Microsoft YaHei UI", 9)).grid(row=6, column=0, sticky=tk.NE, **pad)
        update_frame = tk.Frame(self, bg=bg)
        update_frame.grid(row=6, column=1, columnspan=2, sticky=tk.NSEW, **pad)
        self.update_entry = tk.Entry(update_frame, width=35, bg=entry_bg, fg=fg,
                                      font=("Microsoft YaHei UI", 9), insertbackground=fg)
        self.update_entry.pack(side=tk.LEFT, fill=tk.X)
        self.update_entry.bind("<Return>", self._add_update)
        tk.Button(update_frame, text="添加", font=("Microsoft YaHei UI", 8),
                  bg="#3c6e71", fg="white", relief=tk.FLAT, cursor="hand2",
                  command=self._add_update).pack(side=tk.LEFT, padx=(3, 0))
        self.update_listbox = tk.Listbox(self, height=6, bg=COLORS["listbox_bg"],
                                          fg=COLORS["listbox_fg"],
                                          selectbackground=COLORS["highlight_bg"],
                                          font=("Microsoft YaHei UI", 9), relief=tk.FLAT)
        self.update_listbox.grid(row=7, column=0, columnspan=3, sticky=tk.NSEW, padx=15, pady=3)
        self.update_listbox.bind("<Double-Button-1>", self._remove_update)

        # 底部按钮
        btn_row = tk.Frame(self, bg=bg)
        btn_row.grid(row=8, column=0, columnspan=3, pady=10)
        tk.Button(btn_row, text="保存", font=("Microsoft YaHei UI", 10),
                  bg="#4CAF50", fg="white", width=10, relief=tk.FLAT, cursor="hand2",
                  command=self._save).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_row, text="关闭", font=("Microsoft YaHei UI", 10),
                  bg=COLORS["button_bg"], fg=fg, width=10, relief=tk.FLAT, cursor="hand2",
                  command=self.destroy).pack(side=tk.LEFT, padx=10)

    def _add_dungeon(self, event=None):
        val = self.dungeon_entry.get().strip()
        if val and val not in self.dungeon_listbox.get(0, tk.END):
            self.dungeon_listbox.insert(tk.END, val)
        self.dungeon_entry.delete(0, tk.END)

    def _remove_dungeon(self, event=None):
        sel = self.dungeon_listbox.curselection()
        if sel:
            self.dungeon_listbox.delete(sel[0])

    def _add_mode(self, event=None):
        val = self.mode_entry.get().strip()
        if val and val not in self.mode_listbox.get(0, tk.END):
            self.mode_listbox.insert(tk.END, val)
        self.mode_entry.delete(0, tk.END)

    def _remove_mode(self, event=None):
        sel = self.mode_listbox.curselection()
        if sel:
            self.mode_listbox.delete(sel[0])

    def _add_update(self, event=None):
        val = self.update_entry.get().strip()
        if val:
            # 自动加日期前缀
            from datetime import datetime
            date_str = datetime.now().strftime("%Y-%m-%d")
            entry = f"[{date_str}] {val}"
            self.update_listbox.insert(0, entry)  # 最新的在最上面
        self.update_entry.delete(0, tk.END)

    def _remove_update(self, event=None):
        sel = self.update_listbox.curselection()
        if sel:
            self.update_listbox.delete(sel[0])

    def _meta_path(self):
        return os.path.join(SCRIPT_META_DIR, f"{self.meta_key}.json")

    def _load_meta(self):
        """加载元数据：先按hash全局搜索，再按文件名查找"""
        # 优先按hash查找（支持文件名不同但内容相同的脚本）
        if self._script_hash:
            for fname in os.listdir(SCRIPT_META_DIR):
                if not fname.endswith('.json'):
                    continue
                try:
                    fpath = os.path.join(SCRIPT_META_DIR, fname)
                    with open(fpath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if data.get('file_hash') == self._script_hash:
                        self._fill_from_data(data)
                        return
                except Exception:
                    pass
        # 其次按文件名查找
        path = self._meta_path()
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._fill_from_data(data)
            except Exception:
                pass

    def _fill_from_data(self, data):
        """从字典填充界面"""
        self.author_var.set(data.get('author', ''))
        self.remark_var.set(data.get('remark', ''))
        for d in data.get('dungeons', []):
            self.dungeon_listbox.insert(tk.END, d)
        for m in data.get('modes', []):
            self.mode_listbox.insert(tk.END, m)
        for u in data.get('updates', []):
            self.update_listbox.insert(tk.END, u)

    def _save(self):
        data = {
            "script": self.script_name,
            "file_hash": self._script_hash,
            "author": self.author_var.get().strip(),
            "remark": self.remark_var.get().strip(),
            "dungeons": list(self.dungeon_listbox.get(0, tk.END)),
            "modes": list(self.mode_listbox.get(0, tk.END)),
            "updates": list(self.update_listbox.get(0, tk.END)),
        }
        try:
            with open(self._meta_path(), 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("保存成功", f"脚本信息已保存", parent=self)
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self)


# ==================== 独立运行测试 ====================

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口

    editor = SMDConfigEditor(root)
    editor.mainloop()

    root.destroy()
