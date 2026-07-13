"""SMD游戏监控程序 - GUI版本
可视化配置监控区域、频率检测参数和策略动作
支持窗口选择和相对坐标
"""

import json
import os
import re
import sys
import time
import threading
import numpy as np
import qrcode
import pyautogui
import requests

from PIL import Image, ImageTk, ImageDraw,ImageGrab

from io import BytesIO

# 导入Tkinter模块
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime
from pathlib import Path

# 导入RapidOCR（无需PaddlePaddle，轻量稳定）
from rapidocr_onnxruntime import RapidOCR

# 全局RapidOCR实例（单例）
_RAPIDOCR_INSTANCE = None
def get_rapidocr():
    global _RAPIDOCR_INSTANCE
    if _RAPIDOCR_INSTANCE is None:
        _RAPIDOCR_INSTANCE = RapidOCR()
    return _RAPIDOCR_INSTANCE

# 导入核心模块
from game_monitor import (
    Config, ScreenCapture, OCREngine, ActionExecutor,
    FrequencyAnalyzer, StrategyEngine, GameMonitor
)


def get_window_list():
    """获取所有可见窗口列表"""
    import ctypes
    import ctypes.wintypes

    windows = []

    # 使用纯ctypes方式枚举窗口，避免Python 3.14回调问题
    hwnd_list = []

    def enum_proc(hwnd, lparam):
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                hwnd_list.append(hwnd)
        return True

    # 使用C函数指针
    prototype = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_long)
    proc = prototype(enum_proc)
    ctypes.windll.user32.EnumWindows(proc, 0)

    for hwnd in hwnd_list:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value

        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))

        if rect.right > rect.left and rect.bottom > rect.top and title:
            windows.append({
                'hwnd': hwnd,
                'title': title,
                'left': rect.left,
                'top': rect.top,
                'width': rect.right - rect.left,
                'height': rect.bottom - rect.top
            })

    return windows


def capture_window_region(hwnd, left, top, width, height):
    """截取窗口内指定区域"""
    import ctypes
    import ctypes.wintypes

    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    abs_left = rect.left + left
    abs_top = rect.top + top
    return ImageGrab.grab(bbox=(abs_left, abs_top, abs_left + width, abs_top + height))


class WindowSelectorDialog:
    """窗口选择对话框"""

    def __init__(self, parent, callback):
        self.parent = parent
        self.callback = callback
        self.selected_hwnd = None
        self.closed = False

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("选择游戏窗口")
        self.dialog.geometry("500x400")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # 绑定关闭事件：X按钮、ESC键
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)
        self.dialog.bind("<Escape>", lambda e: self._on_close())

        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        tk.Label(self.dialog, text="双击选择窗口，或点击刷新列表",
                 font=('微软雅黑', 10)).pack(pady=5)

        # 窗口列表
        list_frame = tk.Frame(self.dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(list_frame, columns=('title', 'size'),
                                 show='headings', yscrollcommand=scrollbar.set)
        self.tree.heading('title', text='窗口标题')
        self.tree.heading('size', text='尺寸')
        self.tree.column('title', width=350)
        self.tree.column('size', width=100)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tree.yview)

        self.tree.bind('<Double-1>', self._on_select)

        # 按钮
        btn_frame = tk.Frame(self.dialog)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="刷新列表", command=self._refresh_list,
                  width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="使用当前鼠标位置窗口", command=self._use_mouse_window,
                  width=18, bg='#2196F3', fg='white').pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="取消", command=self._on_close,
                  width=12).pack(side=tk.LEFT, padx=5)

    def _on_close(self):
        """安全关闭对话框"""
        if self.closed:
            return
        self.closed = True
        try:
            self.dialog.grab_release()
        except tk.TclError:
            pass
        self.dialog.destroy()

    def _refresh_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.windows = get_window_list()
        for win in self.windows:
            self.tree.insert('', tk.END, values=(
                win['title'],
                f"{win['width']}x{win['height']}"
            ))

    def _on_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        win = self.windows[idx]
        self.callback(win)
        self._on_close()

    def _use_mouse_window(self):
        """使用鼠标当前位置下的窗口"""
        import ctypes
        x, y = pyautogui.position()
        hwnd = ctypes.windll.user32.WindowFromPoint(ctypes.wintypes.POINT(x, y))
        if hwnd:
            # 获取顶层窗口
            root = ctypes.windll.user32.GetAncestor(hwnd, 2)  # GA_ROOT
            if root:
                hwnd = root
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)

            win = {
                'hwnd': hwnd,
                'title': buffer.value,
                'left': rect.left,
                'top': rect.top,
                'width': rect.right - rect.left,
                'height': rect.bottom - rect.top
            }
            self.callback(win)
            self._on_close()


class RegionSelector:
    """区域选择器 - 在游戏窗口上选择相对区域"""

    def __init__(self, callback, window_rect=None):
        self.callback = callback
        self.window_rect = window_rect  # (left, top, width, height) 相对于游戏窗口
        self.is_absolute = window_rect is None  # 是否使用绝对坐标
        self.start_x = None
        self.start_y = None
        self.rect = None
        self.overlay = None
        self.overlay_offset = (0, 0)  # 覆盖层在屏幕上的偏移

    def start(self):
        """启动区域选择"""
        self.overlay = tk.Toplevel()
        self.overlay.attributes('-topmost', True)
        self.overlay.overrideredirect(True)

        if self.window_rect:
            # 只覆盖游戏窗口区域
            self.overlay.geometry(f"{self.window_rect[2]}x{self.window_rect[3]}+{self.window_rect[0]}+{self.window_rect[1]}")
            self.overlay_offset = (self.window_rect[0], self.window_rect[1])
        else:
            # 全屏
            self.overlay.geometry(f"{self.overlay.winfo_screenwidth()}x{self.overlay.winfo_screenheight()}+0+0")
            self.overlay_offset = (0, 0)

        self.overlay.attributes('-alpha', 0.3)
        self.overlay.configure(bg='black')

        self.canvas = tk.Canvas(self.overlay, highlightthickness=0, bg='black')
        self.canvas.pack(fill=tk.BOTH, expand=True)

        offset_text = "(相对于游戏窗口)" if self.window_rect else "(屏幕绝对坐标)"
        self.label = tk.Label(self.overlay,
                              text=f"按住鼠标左键拖动选择区域 {offset_text}，松开确认，ESC取消",
                              font=('微软雅黑', 14), fg='white', bg='black')
        self.label.place(relx=0.5, rely=0.1, anchor='center')

        self.canvas.bind('<Button-1>', self.on_press)
        self.canvas.bind('<B1-Motion>', self.on_drag)
        self.canvas.bind('<ButtonRelease-1>', self.on_release)
        self.overlay.bind('<Escape>', self.on_cancel)

    def _get_mouse_screen_pos(self, event):
        """获取鼠标在屏幕上的绝对坐标"""
        if self.is_absolute:
            # 绝对坐标模式：直接使用鼠标位置
            return pyautogui.position()
        else:
            # 相对坐标模式：鼠标位置 + 窗口偏移
            x, y = pyautogui.position()
            return (x - self.overlay_offset[0], y - self.overlay_offset[1])

    def on_press(self, event):
        # 获取屏幕绝对坐标
        screen_pos = self._get_mouse_screen_pos(event)
        self.start_x = screen_pos[0]
        self.start_y = screen_pos[1]
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline='red', width=3
        )

    def on_drag(self, event):
        if self.rect:
            self.canvas.coords(self.rect, self.start_x - self.overlay_offset[0], 
                               self.start_y - self.overlay_offset[1], event.x, event.y)
        screen_pos = self._get_mouse_screen_pos(event)
        self.label.config(text=f"区域: ({self.start_x}, {self.start_y}) - ({screen_pos[0]}, {screen_pos[1]}) "
                                f"大小: {abs(screen_pos[0] - self.start_x)}x{abs(screen_pos[1] - self.start_y)}")

    def on_release(self, event):
        screen_pos = self._get_mouse_screen_pos(event)
        x1, y1 = min(self.start_x, screen_pos[0]), min(self.start_y, screen_pos[1])
        x2, y2 = max(self.start_x, screen_pos[0]), max(self.start_y, screen_pos[1])
        w, h = x2 - x1, y2 - y1
        self.overlay.destroy()
        self.callback(x1, y1, w, h)

    def on_cancel(self, event):
        self.overlay.destroy()


class ActionEditorDialog:
    """动作编辑器对话框"""

    # 动作类型映射：中文显示名称 -> {英文type, 字段配置}
    ACTION_TYPES = {
        '按键': {'type': 'key_press', 'fields': [
            ('key', '按键', 'entry'),
            ('presses', '次数', 'spin', 1, 10),
            ('interval', '间隔(秒)', 'entry')
        ]},
        '按下键': {'type': 'key_down', 'fields': [
            ('key', '按键', 'entry')
        ]},
        '释放键': {'type': 'release_keys', 'fields': [
            ('keys', '按键(逗号分隔)', 'entry')
        ]},
        '组合键': {'type': 'key_combo', 'fields': [
            ('keys', '按键列表(逗号分隔)', 'entry')
        ]},
        '输入文本': {'type': 'type_text', 'fields': [
            ('text', '文本内容', 'entry'),
            ('interval', '输入间隔(秒)', 'entry')
        ]},
        '鼠标点击': {'type': 'mouse_click', 'fields': [
            ('x', 'X坐标', 'entry'),
            ('y', 'Y坐标', 'entry'),
            ('button', '按键', 'combo', ['left', 'right', 'middle']),
            ('clicks', '点击次数', 'spin', 1, 5)
        ]},
        '鼠标移动': {'type': 'mouse_move', 'fields': [
            ('x', 'X坐标', 'entry'),
            ('y', 'Y坐标', 'entry'),
            ('duration', '移动时间(秒)', 'entry')
        ]},
        '鼠标拖拽': {'type': 'mouse_drag', 'fields': [
            ('start_x', '起点X', 'entry'),
            ('start_y', '起点Y', 'entry'),
            ('end_x', '终点X', 'entry'),
            ('end_y', '终点Y', 'entry'),
            ('duration', '拖拽时间(秒)', 'entry')
        ]},
        '鼠标滚动': {'type': 'mouse_scroll', 'fields': [
            ('clicks', '滚动量', 'entry'),
            ('x', 'X坐标', 'entry'),
            ('y', 'Y坐标', 'entry')
        ]},
        '等待': {'type': 'delay', 'fields': [
            ('seconds', '等待秒数', 'entry')
        ]},
        '输出日志': {'type': 'log', 'fields': [
            ('message', '日志内容', 'entry')
        ]},
        '保存截图': {'type': 'screenshot', 'fields': [
            ('filename', '文件名(可选)', 'entry')
        ]},
        '自定义代码': {'type': 'custom', 'fields': [
            ('code', 'Python代码', 'text')
        ]}
    }

    # 反向映射：英文type -> 中文显示名称
    TYPE_TO_LABEL = {v['type']: k for k, v in ACTION_TYPES.items()}

    def __init__(self, parent, action=None, callback=None):
        self.parent = parent
        self.action = action or {}
        self.callback = callback
        self.result = None
        self.fields = {}

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("编辑动作")
        self.dialog.geometry("500x400")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self._build_ui()

        if action:
            self._load_action(action)

    def _build_ui(self):
        # 动作类型选择
        tk.Label(self.dialog, text="动作类型:", font=('微软雅黑', 11)).pack(pady=5)
        self.type_var = tk.StringVar(value='按键')
        self.type_combo = ttk.Combobox(self.dialog, textvariable=self.type_var,
                                       values=list(self.ACTION_TYPES.keys()),
                                       state='readonly', width=30)
        self.type_combo.pack(pady=5)
        self.type_combo.bind('<<ComboboxSelected>>', self._on_type_change)

        # 参数区域
        self.params_frame = tk.LabelFrame(self.dialog, text="参数", font=('微软雅黑', 10))
        self.params_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 按钮
        btn_frame = tk.Frame(self.dialog)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="确定", command=self._on_ok,
                  width=10, bg='#4CAF50', fg='white').pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="取消", command=self.dialog.destroy,
                  width=10).pack(side=tk.LEFT, padx=5)

        self._on_type_change()

    def _on_type_change(self, event=None):
        action_label = self.type_var.get()
        config = self.ACTION_TYPES.get(action_label, {})

        # 清空参数区域
        for widget in self.params_frame.winfo_children():
            widget.destroy()
        self.fields = {}

        # 创建参数字段
        for field_config in config.get('fields', []):
            field_name, field_label, field_type = field_config[:3]

            row = tk.Frame(self.params_frame)
            row.pack(fill=tk.X, pady=3)

            tk.Label(row, text=field_label + ":", width=20, anchor='e').pack(side=tk.LEFT, padx=5)

            if field_type == 'entry':
                var = tk.StringVar()
                entry = tk.Entry(row, textvariable=var, width=30)
                entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
                self.fields[field_name] = var

            elif field_type == 'spin':
                min_val, max_val = field_config[3], field_config[4]
                var = tk.IntVar(value=min_val)
                spin = tk.Spinbox(row, from_=min_val, to=max_val, textvariable=var, width=10)
                spin.pack(side=tk.LEFT, padx=5)
                self.fields[field_name] = var

            elif field_type == 'combo':
                options = field_config[3]
                var = tk.StringVar(value=options[0])
                combo = ttk.Combobox(row, textvariable=var, values=options, state='readonly', width=15)
                combo.pack(side=tk.LEFT, padx=5)
                self.fields[field_name] = var

            elif field_type == 'text':
                text = tk.Text(row, width=30, height=5)
                text.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
                self.fields[field_name] = text

    def _load_action(self, action):
        # 将英文type转换为中文label
        eng_type = action.get('type', 'key_press')
        label = self.TYPE_TO_LABEL.get(eng_type, '按键')
        self.type_var.set(label)
        self._on_type_change()

        for key, value in action.items():
            if key == 'type':
                continue
            if key in self.fields:
                widget = self.fields[key]
                if isinstance(widget, tk.Text):
                    widget.delete('1.0', tk.END)
                    widget.insert('1.0', str(value))
                elif isinstance(widget, tk.StringVar):
                    widget.set(str(value))
                elif isinstance(widget, tk.IntVar):
                    widget.set(int(value))

    def _on_ok(self):
        action_label = self.type_var.get()
        config = self.ACTION_TYPES.get(action_label, {})
        eng_type = config.get('type', 'key_press')
        result = {'type': eng_type}

        for key, widget in self.fields.items():
            if isinstance(widget, tk.Text):
                value = widget.get('1.0', tk.END).strip()
            elif isinstance(widget, tk.StringVar):
                value = widget.get()
            elif isinstance(widget, tk.IntVar):
                value = widget.get()
            else:
                continue

            # 跳过空字符串，但保留数值0
            if value == "" or value is None:
                continue

            # 类型转换
            if key in ['x', 'y', 'start_x', 'start_y', 'end_x', 'end_y',
                       'clicks', 'presses']:
                value = int(value)
            elif key in ['seconds', 'interval', 'duration']:
                value = float(value)
            elif key == 'keys':
                value = [k.strip() for k in value.split(',')]

            result[key] = value

        self.result = result
        if self.callback:
            self.callback(result)
        self.dialog.destroy()


class StrategyEditorDialog:
    """策略编辑器对话框"""

    def __init__(self, parent, strategy_key='', strategy=None, callback=None):
        self.parent = parent
        self.strategy_key = strategy_key
        self.strategy = strategy or {}
        self.callback = callback
        self.actions = list(self.strategy.get('actions', []))
        self.dirty = False  # 标记是否有未保存更改

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("编辑策略")
        self.dialog.geometry("650x800")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # 绑定关闭事件
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close)
        self.dialog.bind("<Escape>", lambda e: self._on_close())

        self._build_ui()

    def _build_ui(self):
        # 底部确定/取消按钮（先pack，确保始终可见）
        ok_frame = tk.Frame(self.dialog)
        ok_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=2)

        tk.Button(ok_frame, text="确定", command=self._on_ok,
                  width=10, bg='#4CAF50', fg='white', font=('微软雅黑', 10)).pack(side=tk.RIGHT, padx=5)
        tk.Button(ok_frame, text="取消", command=self._on_close,
                  width=10, font=('微软雅黑', 10)).pack(side=tk.RIGHT, padx=5)

        # 中间可滚动内容区域（放一个容器承载所有配置）
        content = tk.Frame(self.dialog)
        content.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 基本信息
        basic_frame = tk.LabelFrame(content, text="基本信息", font=('微软雅黑', 10))
        basic_frame.pack(fill=tk.X, padx=0, pady=5)

        # 策略ID
        row = tk.Frame(basic_frame)
        row.pack(fill=tk.X, pady=3)
        tk.Label(row, text="策略ID:", width=15, anchor='e').pack(side=tk.LEFT, padx=5)
        self.key_var = tk.StringVar(value=self.strategy_key)
        tk.Entry(row, textvariable=self.key_var, width=30).pack(side=tk.LEFT, padx=5)

        # 名称
        row = tk.Frame(basic_frame)
        row.pack(fill=tk.X, pady=3)
        tk.Label(row, text="名称:", width=15, anchor='e').pack(side=tk.LEFT, padx=5)
        self.name_var = tk.StringVar(value=self.strategy.get('name', ''))
        tk.Entry(row, textvariable=self.name_var, width=30).pack(side=tk.LEFT, padx=5)

        # 描述
        row = tk.Frame(basic_frame)
        row.pack(fill=tk.X, pady=3)
        tk.Label(row, text="描述:", width=15, anchor='e').pack(side=tk.LEFT, padx=5)
        self.desc_var = tk.StringVar(value=self.strategy.get('description', ''))
        tk.Entry(row, textvariable=self.desc_var, width=50).pack(side=tk.LEFT, padx=5)

        # 匹配设置
        match_frame = tk.LabelFrame(content, text="匹配设置", font=('微软雅黑', 10))
        match_frame.pack(fill=tk.X, padx=0, pady=5)

        row = tk.Frame(match_frame)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text="匹配文本(逗号分隔):", width=20, anchor='e').pack(side=tk.LEFT, padx=5)
        match_ids = self.strategy.get('match_ids', [])
        self.match_ids_var = tk.StringVar(value=','.join(match_ids))
        tk.Entry(row, textvariable=self.match_ids_var, width=30).pack(side=tk.LEFT, padx=5)
        tk.Label(row, text="(空=匹配所有)").pack(side=tk.LEFT)

        row = tk.Frame(match_frame)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text="排除文本(逗号分隔):", width=20, anchor='e').pack(side=tk.LEFT, padx=5)
        exclude_ids = self.strategy.get('exclude_ids', [])
        self.exclude_ids_var = tk.StringVar(value=','.join(exclude_ids))
        tk.Entry(row, textvariable=self.exclude_ids_var, width=30).pack(side=tk.LEFT, padx=5)
        tk.Label(row, text="(包含这些则不触发)", fg='gray').pack(side=tk.LEFT)

        row = tk.Frame(match_frame)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text="匹配卡脚本类型:", width=20, anchor='e').pack(side=tk.LEFT, padx=5)

        # 卡脚本类型中文映射
        self.stuck_type_map = {'任意': 'any', '单一卡死': 'single', '交替卡死': 'alternating'}
        self.stuck_type_reverse = {v: k for k, v in self.stuck_type_map.items()}

        default_type = self.strategy.get('match_stuck_type', 'any')
        self.match_type_var = tk.StringVar(value=self.stuck_type_reverse.get(default_type, '任意'))
        ttk.Combobox(row, textvariable=self.match_type_var,
                     values=list(self.stuck_type_map.keys()),
                     state='readonly', width=15).pack(side=tk.LEFT, padx=5)

        # 阈值设置
        threshold_frame = tk.LabelFrame(content, text="触发阈值", font=('微软雅黑', 10))
        threshold_frame.pack(fill=tk.X, padx=0, pady=5)

        row = tk.Frame(threshold_frame)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text="单一: 出现次数≥", width=15, anchor='e').pack(side=tk.LEFT, padx=5)
        self.stuck_threshold_var = tk.StringVar(value=str(self.strategy.get('stuck_threshold', '')))
        tk.Entry(row, textvariable=self.stuck_threshold_var, width=8).pack(side=tk.LEFT, padx=5)
        tk.Label(row, text="占比≥", width=6, anchor='e').pack(side=tk.LEFT, padx=5)
        self.stuck_ratio_var = tk.StringVar(value=str(self.strategy.get('stuck_ratio', '')))
        tk.Entry(row, textvariable=self.stuck_ratio_var, width=8).pack(side=tk.LEFT, padx=5)
        tk.Label(row, text="(如30 / 0.8)", fg='gray').pack(side=tk.LEFT)

        row = tk.Frame(threshold_frame)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text="交替: 合计次数≥", width=15, anchor='e').pack(side=tk.LEFT, padx=5)
        self.alternating_threshold_var = tk.StringVar(value=str(self.strategy.get('alternating_threshold', '')))
        tk.Entry(row, textvariable=self.alternating_threshold_var, width=8).pack(side=tk.LEFT, padx=5)
        tk.Label(row, text="占比≥", width=6, anchor='e').pack(side=tk.LEFT, padx=5)
        self.alternating_ratio_var = tk.StringVar(value=str(self.strategy.get('alternating_ratio', '')))
        tk.Entry(row, textvariable=self.alternating_ratio_var, width=8).pack(side=tk.LEFT, padx=5)
        tk.Label(row, text="(如25 / 0.85)", fg='gray').pack(side=tk.LEFT)

        row = tk.Frame(threshold_frame)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text="严重程度系数:", width=15, anchor='e').pack(side=tk.LEFT, padx=5)
        self.severity_var = tk.StringVar(value=str(self.strategy.get('severity', '')))
        tk.Entry(row, textvariable=self.severity_var, width=8).pack(side=tk.LEFT, padx=5)
        tk.Label(row, text="(空=默认1.0, 移动类=1, 限时打怪=2等, 报警按总系数触发)", fg='gray').pack(side=tk.LEFT)

        row = tk.Frame(threshold_frame)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text="统计窗口(秒):", width=15, anchor='e').pack(side=tk.LEFT, padx=5)
        self.window_seconds_var = tk.StringVar(value=str(self.strategy.get('window_seconds', '')))
        tk.Entry(row, textvariable=self.window_seconds_var, width=8).pack(side=tk.LEFT, padx=5)
        tk.Label(row, text="最小样本:", width=8, anchor='e').pack(side=tk.LEFT, padx=5)
        self.min_samples_var = tk.StringVar(value=str(self.strategy.get('min_samples', '')))
        tk.Entry(row, textvariable=self.min_samples_var, width=8).pack(side=tk.LEFT, padx=5)
        tk.Label(row, text="(空=使用全局默认值)", fg='gray').pack(side=tk.LEFT)

        # 动作列表（固定高度，不扩展）
        actions_frame = tk.LabelFrame(content, text="动作序列", font=('微软雅黑', 5))
        actions_frame.pack(fill=tk.X, padx=0, pady=5)

        # 动作操作按钮（先pack，确保不被listbox挤压）
        btn_frame = tk.Frame(actions_frame)
        btn_frame.pack(pady=(0, 5), fill=tk.X)
        tk.Button(btn_frame, text="添加", command=self._add_action,
                  width=8, bg='#4CAF50', fg='white').pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="编辑", command=self._edit_action,
                  width=8).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="删除", command=self._delete_action,
                  width=8, bg='#f44336', fg='white').pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="上移", command=self._move_up,
                  width=8).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="下移", command=self._move_down,
                  width=8).pack(side=tk.LEFT, padx=2)

        # 动作列表框
        list_frame = tk.Frame(actions_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.actions_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                                          font=('Consolas', 10), height=10)
        self.actions_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.actions_listbox.yview)

        self._refresh_actions_list()

    def _refresh_actions_list(self):
        self.actions_listbox.delete(0, tk.END)
        for i, action in enumerate(self.actions):
            action_type = action.get('type', 'unknown')
            # 将英文type转换为中文显示
            type_label = ActionEditorDialog.TYPE_TO_LABEL.get(action_type, action_type)
            desc = self._action_desc(action)
            self.actions_listbox.insert(tk.END, f"{i+1}. [{type_label}] {desc}")

    def _action_desc(self, action):
        action_type = action.get('type', '')
        if action_type == 'key_press':
            return f"按键 {action.get('key', '')} x{action.get('presses', 1)}"
        elif action_type == 'key_down':
            return f"按下 {action.get('key', '')}"
        elif action_type == 'release_keys':
            return f"释放 {action.get('keys', '')}"
        elif action_type == 'key_combo':
            return f"{'+'.join(action.get('keys', []))}"
        elif action_type == 'type_text':
            text = action.get('text', '')
            return f"\"{text[:20]}{'...' if len(text) > 20 else ''}\""
        elif action_type == 'mouse_click':
            return f"({action.get('x', 0)}, {action.get('y', 0)}) {action.get('button', 'left')}x{action.get('clicks', 1)}"
        elif action_type == 'mouse_move':
            return f"({action.get('x', 0)}, {action.get('y', 0)})"
        elif action_type == 'mouse_drag':
            return f"({action.get('start_x', 0)},{action.get('start_y', 0)})->({action.get('end_x', 0)},{action.get('end_y', 0)})"
        elif action_type == 'mouse_scroll':
            return f"{action.get('clicks', 0)} ({action.get('x', 0)}, {action.get('y', 0)})"
        elif action_type == 'delay':
            return f"{action.get('seconds', 0)}秒"
        elif action_type == 'log':
            msg = action.get('message', '')
            return f"\"{msg[:30]}{'...' if len(msg) > 30 else ''}\""
        elif action_type == 'screenshot':
            filename = action.get('filename', '')
            return f"{filename}" if filename else "默认文件名"
        elif action_type == 'custom':
            return "Python代码"
        else:
            return str(action)

    def _add_action(self):
        def on_save(action):
            self.actions.append(action)
            self.dirty = True
            self._refresh_actions_list()
        ActionEditorDialog(self.dialog, callback=on_save)

    def _edit_action(self):
        sel = self.actions_listbox.curselection()
        if not sel:
            return
        idx = sel[0]

        def on_save(action):
            self.actions[idx] = action
            self.dirty = True
            self._refresh_actions_list()
        ActionEditorDialog(self.dialog, action=self.actions[idx], callback=on_save)

    def _delete_action(self):
        sel = self.actions_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        del self.actions[idx]
        self.dirty = True
        self._refresh_actions_list()

    def _move_up(self):
        sel = self.actions_listbox.curselection()
        if not sel or sel[0] == 0:
            return
        idx = sel[0]
        self.actions[idx], self.actions[idx-1] = self.actions[idx-1], self.actions[idx]
        self.dirty = True
        self._refresh_actions_list()
        self.actions_listbox.selection_set(idx-1)

    def _move_down(self):
        sel = self.actions_listbox.curselection()
        if not sel or sel[0] >= len(self.actions) - 1:
            return
        idx = sel[0]
        self.actions[idx], self.actions[idx+1] = self.actions[idx+1], self.actions[idx]
        self.dirty = True
        self._refresh_actions_list()
        self.actions_listbox.selection_set(idx+1)

    def _on_close(self):
        """安全关闭：询问是否保存未保存的更改"""
        if self.dirty:
            result = messagebox.askyesnocancel("未保存更改", 
                "有未保存的更改，是否保存?\n\n是=保存  否=放弃  取消=返回编辑")
            if result is None:  # 取消
                return
            if result:  # 是
                self._on_ok(skip_close=True)
        try:
            self.dialog.grab_release()
        except tk.TclError:
            pass
        self.dialog.destroy()

    def _on_ok(self, skip_close=False):
        strategy_key = self.key_var.get().strip()
        if not strategy_key:
            messagebox.showerror("错误", "策略ID不能为空")
            return

        # 将中文卡脚本类型转换回英文
        stuck_type_cn = self.match_type_var.get()
        stuck_type_en = self.stuck_type_map.get(stuck_type_cn, 'any')

        strategy = {
            'name': self.name_var.get(),
            'description': self.desc_var.get(),
            'match_ids': [s.strip() for s in self.match_ids_var.get().split(',') if s.strip()],
            'exclude_ids': [s.strip() for s in self.exclude_ids_var.get().split(',') if s.strip()],
            'match_stuck_type': stuck_type_en,
            'actions': self.actions
        }

        # 保存阈值（空值则不保存，使用全局默认值）
        st = self.stuck_threshold_var.get().strip()
        sr = self.stuck_ratio_var.get().strip()
        at = self.alternating_threshold_var.get().strip()
        ar = self.alternating_ratio_var.get().strip()
        if st:
            strategy['stuck_threshold'] = int(st)
        if sr:
            strategy['stuck_ratio'] = float(sr)
        if at:
            strategy['alternating_threshold'] = int(at)
        if ar:
            strategy['alternating_ratio'] = float(ar)

        # 严重程度系数
        sev = self.severity_var.get().strip()
        if sev:
            strategy['severity'] = float(sev)

        # 统计窗口和最小样本（空值不保存，使用全局默认）
        ws = self.window_seconds_var.get().strip()
        if ws:
            strategy['window_seconds'] = int(ws)
        ms = self.min_samples_var.get().strip()
        if ms:
            strategy['min_samples'] = int(ms)

        self.dirty = False
        self.result = (strategy_key, strategy)
        if self.callback:
            self.callback(strategy_key, strategy)
        if not skip_close:
            try:
                self.dialog.grab_release()
            except tk.TclError:
                pass
            self.dialog.destroy()


class FloatingStatsWindow:
    """悬浮统计窗口 - 显示在游戏窗口右侧的运行统计信息"""

    def __init__(self, gui):
        self.gui = gui
        self.window = None
        self._update_id = None
        self._logs = []  # 最近关键日志缓存
        self._last_logs = []  # 上次显示的日志快照
        self._max_logs = 5

    def show(self):
        """创建并显示悬浮窗口"""
        if self.window and self.window.winfo_exists():
            return
        self.window = tk.Toplevel(self.gui.root)
        self.window.overrideredirect(True)  # 无边框
        self.window.attributes('-topmost', True)  # 置顶
        self.window.attributes('-alpha', 0.92)  # 半透明
        self.window.configure(bg='#1a1a2e')

        # 内容区域
        self.content = tk.Frame(self.window, bg='#1a1a2e', padx=10, pady=8)
        self.content.pack(fill=tk.BOTH, expand=True)

        # 标题
        tk.Label(self.content, text='监控统计', font=('微软雅黑', 11, 'bold'),
                 fg='#e94560', bg='#1a1a2e').pack(anchor='w')
        tk.Frame(self.content, height=1, bg='#e94560').pack(fill=tk.X, pady=(2, 6))

        # 运行时间 + 状态（同一行）
        row0 = tk.Frame(self.content, bg='#1a1a2e')
        row0.pack(fill=tk.X, pady=1)
        self.runtime_var = tk.StringVar(value='运行: 00:00:00')
        tk.Label(row0, textvariable=self.runtime_var, font=('Consolas', 10),
                 fg='#eaeaea', bg='#1a1a2e').pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value='运行中')
        self.status_label = tk.Label(row0, textvariable=self.status_var, font=('Consolas', 10),
                 fg='#00ff88', bg='#1a1a2e')
        self.status_label.pack(side=tk.RIGHT)

        # 总触发 / 触发频率（同一行）
        row1 = tk.Frame(self.content, bg='#1a1a2e')
        row1.pack(fill=tk.X, pady=1)
        self.total_var = tk.StringVar(value='总触发:0')
        tk.Label(row1, textvariable=self.total_var, font=('Consolas', 10),
                 fg='#eaeaea', bg='#1a1a2e').pack(side=tk.LEFT)
        self.tph_var = tk.StringVar(value='触发频率:0.0次/时')
        tk.Label(row1, textvariable=self.tph_var, font=('Consolas', 10),
                 fg='#00d9ff', bg='#1a1a2e').pack(side=tk.RIGHT)

        # 总轮数 / 每轮用时（同一行，去掉轮频率）
        row2 = tk.Frame(self.content, bg='#1a1a2e')
        row2.pack(fill=tk.X, pady=1)
        self.rounds_var = tk.StringVar(value='总轮数:0')
        tk.Label(row2, textvariable=self.rounds_var, font=('Consolas', 10),
                 fg='#eaeaea', bg='#1a1a2e').pack(side=tk.LEFT)
        self.avg_round_var = tk.StringVar(value='均时:0秒')
        tk.Label(row2, textvariable=self.avg_round_var, font=('Consolas', 10),
                 fg='#a0e7a0', bg='#1a1a2e').pack(side=tk.RIGHT)

        # 分隔线
        tk.Frame(self.content, height=1, bg='#444').pack(fill=tk.X, pady=(6, 4))

        # 自适应状态（根据配置开关显示/隐藏）
        self.adaptive_frame = tk.Frame(self.content, bg='#1a1a2e')
        self.adaptive_frame.pack(fill=tk.X, pady=1)
        tk.Label(self.adaptive_frame, text='自适应', font=('微软雅黑', 10, 'bold'),
                 fg='#4ecca3', bg='#1a1a2e').pack(side=tk.LEFT)
        self.adaptive_status_var = tk.StringVar(value='[ON]')
        self.adaptive_status_label = tk.Label(self.adaptive_frame, textvariable=self.adaptive_status_var,
                                              font=('Consolas', 9), fg='#00ff88', bg='#1a1a2e')
        self.adaptive_status_label.pack(side=tk.LEFT, padx=4)
        self.adaptive_detail_var = tk.StringVar(value='误报:0 漏报:0 | 参数正常')
        self.adaptive_detail_label = tk.Label(self.adaptive_frame, textvariable=self.adaptive_detail_var, font=('Consolas', 9),
                 fg='#aaa', bg='#1a1a2e')
        self.adaptive_detail_label.pack(side=tk.LEFT, padx=2)

        # 倒计时信息（根据设置动态显示）
        self.countdown_frame = tk.Frame(self.content, bg='#1a1a2e')
        self.countdown_frame.pack(fill=tk.X, pady=1)
        self.countdown_var = tk.StringVar(value='')
        tk.Label(self.countdown_frame, textvariable=self.countdown_var, font=('Consolas', 9),
                 fg='#e94560', bg='#1a1a2e').pack(anchor='w')

        # 快捷键
        tk.Label(self.content, text='快捷键', font=('微软雅黑', 10, 'bold'),
                 fg='#ff9f43', bg='#1a1a2e').pack(anchor='w')
        # 从配置读取实际热键
        hk_start = 'F8'
        hk_pause = 'F10'
        if self.gui.config_data:
            hk = self.gui.config_data.get('hotkeys', {})
            hk_start = hk.get('start_stop', 'F8')
            hk_pause = hk.get('pause_resume', 'F10')
        tk.Label(self.content, text=f'{hk_start}=开始/停止  {hk_pause}=暂停/恢复',
                 font=('Consolas', 9), fg='#ccc', bg='#1a1a2e', justify=tk.LEFT).pack(anchor='w')

        # 分隔线
        tk.Frame(self.content, height=1, bg='#444').pack(fill=tk.X, pady=(6, 4))

        # 关键日志标题
        tk.Label(self.content, text='关键日志', font=('微软雅黑', 10, 'bold'),
                 fg='#ff9f43', bg='#1a1a2e').pack(anchor='w')

        # 日志区域（带横向滚动条，不换行，完整显示）
        log_frame = tk.Frame(self.content, bg='#1a1a2e')
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 0))

        self.log_text = tk.Text(log_frame, height=5, width=42, font=('Consolas', 9),
                                bg='#16213e', fg='#ccc', wrap=tk.NONE,
                                state=tk.DISABLED, relief=tk.SOLID, bd=1)
        self.log_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        h_scroll = tk.Scrollbar(log_frame, orient=tk.HORIZONTAL, command=self.log_text.xview,
                                bg='#1a1a2e', troughcolor='#1a1a2e', highlightthickness=0)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.log_text.config(xscrollcommand=h_scroll.set)

        self._position_window()
        self._schedule_update()

    def hide(self):
        """关闭悬浮窗口"""
        if self._update_id:
            self.gui.root.after_cancel(self._update_id)
            self._update_id = None
        if self.window and self.window.winfo_exists():
            self.window.destroy()
        self.window = None

    def add_log(self, message: str):
        """添加一条关键日志（精简显示：月日时分秒 + 内容，去掉级别）"""
        import re
        # 匹配 "2026-07-03 12:53:00,155 [ERROR] xxx" 格式
        m = re.search(r'(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2}),\d+\s*\[[A-Z]+\]\s*(.*)', message)
        if m:
            # MMdd HHmmss + 内容
            short = f"{m.group(2)}{m.group(3)} {m.group(4)}{m.group(5)}{m.group(6)} {m.group(7)[:40]}"
        else:
            short = message[:55]
        self._logs.append(short)
        if len(self._logs) > self._max_logs:
            self._logs.pop(0)

    def _position_window(self):
        """将悬浮窗口定位在游戏窗口右侧中间内部"""
        game_window = self.gui.selected_window

        # 如果 gui.selected_window 为空，尝试从 game_monitor 的 screen_capture 获取
        if not game_window and self.gui.game_monitor and self.gui.game_monitor.screen_capture:
            sc = self.gui.game_monitor.screen_capture
            if sc.window_hwnd:
                import ctypes
                import ctypes.wintypes
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(sc.window_hwnd, ctypes.byref(rect))
                game_window = {
                    'hwnd': sc.window_hwnd,
                    'left': rect.left,
                    'top': rect.top,
                    'width': rect.right - rect.left,
                    'height': rect.bottom - rect.top
                }

        if game_window:
            import ctypes
            import ctypes.wintypes
            hwnd = game_window.get('hwnd', 0)
            if hwnd:
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                gw = rect.right - rect.left
                gh = rect.bottom - rect.top
                gx = rect.left
                gy = rect.top
            else:
                gx = game_window.get('left', 0)
                gy = game_window.get('top', 0)
                gw = game_window.get('width', 0)
                gh = game_window.get('height', 0)
            w = 320
            h = 340
            # 右侧中间内部: x = 游戏窗口右侧 - 悬浮窗宽度 - 边距
            x = gx + gw - w - 10
            y = gy + (gh - h) // 2
        else:
            x = self.gui.root.winfo_x() + self.gui.root.winfo_width() + 8
            y = self.gui.root.winfo_y()
            w = 320
            h = 340
        self.window.geometry(f'{w}x{h}+{x}+{y}')

    def _schedule_update(self):
        """定时更新统计信息和位置"""
        self._update_stats()
        self._update_id = self.gui.root.after(2000, self._schedule_update)

    def _update_stats(self):
        """更新悬浮窗口的统计数据"""
        if not self.window or not self.window.winfo_exists():
            return

        # 获取统计
        stats = {'runtime': 0, 'total_triggers': 0, 'triggers_per_hour': 0.0}
        if self.gui.game_monitor and self.gui.game_monitor.strategy_engine:
            stats = self.gui.game_monitor.strategy_engine.get_stats()

        # 格式化运行时间
        rt = int(stats['runtime'])
        hours = rt // 3600
        mins = (rt % 3600) // 60
        secs = rt % 60
        self.runtime_var.set(f'运行: {hours}时{mins:02d}分{secs:02d}秒')
        self.total_var.set(f"总触发:{stats['total_triggers']}")
        self.tph_var.set(f"触发频率:{stats['triggers_per_hour']:.1f}次/时")

        # 轮数统计
        self.rounds_var.set(f"总轮数:{stats.get('total_rounds', 0)}")
        avg_rt = stats.get('avg_round_time', 0.0)
        if avg_rt >= 60:
            self.avg_round_var.set(f"均时:{avg_rt/60:.1f}分")
        else:
            self.avg_round_var.set(f"均时:{avg_rt:.0f}秒")

        # 更新运行状态
        if self.gui.game_monitor:
            if self.gui.game_monitor.paused:
                self.status_var.set('已暂停')
                self.status_label.config(fg='#ff9f43')
            elif self.gui.monitor_running:
                self.status_var.set('运行中')
                self.status_label.config(fg='#00ff88')
            else:
                self.status_var.set('已停止')
                self.status_label.config(fg='#e94560')
        else:
            self.status_var.set('状态: 已停止')

        # 更新自适应状态（根据配置开关显示/隐藏）
        if self.gui.config_data and self.gui.config_data.get('adaptive', {}).get('enabled', True):
            self.adaptive_frame.pack(fill=tk.X, pady=1)
            if self.gui.game_monitor and hasattr(self.gui.game_monitor, 'adaptive_tuner'):
                tuner = self.gui.game_monitor.adaptive_tuner
                if tuner:
                    astats = tuner.get_adaptive_stats()
                    if astats['enabled']:
                        self.adaptive_status_var.set('[ON]')
                        self.adaptive_status_label.config(fg='#00ff88')
                    else:
                        self.adaptive_status_var.set('[OFF]')
                        self.adaptive_status_label.config(fg='#666')
                    detail = f"误报:{astats['fp_count']} 漏报:{astats['fn_count']} | {astats['changes_str']}{astats['frozen']}"
                    self.adaptive_detail_var.set(detail)
        else:
            self.adaptive_frame.pack_forget()

        # 更新倒计时信息（根据挂机设置显示）
        idle_cfg = self.gui.config_data.get('idle_settings', {}) if self.gui.config_data else {}
        countdown_parts = []
        if idle_cfg.get('enabled', False):
            max_mins = idle_cfg.get('stop_after_minutes', 0)
            max_rounds = idle_cfg.get('stop_after_rounds', 0)
            max_execs = idle_cfg.get('stop_after_executions', 0)
            stop_at = idle_cfg.get('stop_at_time', '')
            if self.gui.game_monitor and self.gui.monitor_start_time:
                elapsed = time.time() - self.gui.monitor_start_time
                if max_mins > 0:
                    remain = max(max_mins * 60 - elapsed, 0)
                    m, s = divmod(int(remain), 60)
                    countdown_parts.append(f"时间剩余:{m}分{s}秒")
            if max_rounds > 0:
                total_rounds = len(self.gui.game_monitor._round_events) if self.gui.game_monitor else 0
                countdown_parts.append(f"轮数:{total_rounds}/{max_rounds}")
            if max_execs > 0:
                total_execs = stats.get('total_triggers', 0)
                countdown_parts.append(f"次数:{total_execs}/{max_execs}")
            if stop_at:
                countdown_parts.append(f"停止于:{stop_at}")
        if countdown_parts:
            self.countdown_var.set(' | '.join(countdown_parts))
            self.countdown_frame.pack(fill=tk.X, pady=1)
        else:
            self.countdown_frame.pack_forget()

        # 仅在日志发生变化时才更新日志文本
        if self._logs != self._last_logs:
            self._last_logs = list(self._logs)
            self.log_text.config(state=tk.NORMAL)
            self.log_text.delete('1.0', tk.END)
            if self._logs:
                for msg in self._logs:
                    self.log_text.insert(tk.END, msg + '\n')
            else:
                self.log_text.insert(tk.END, '暂无关键日志\n')
            self.log_text.config(state=tk.DISABLED)

        # 跟随游戏窗口位置（仅在位置变化时才更新）
        import ctypes
        import ctypes.wintypes
        game_hwnd = self._get_game_hwnd()
        if game_hwnd:
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(game_hwnd, ctypes.byref(rect))
            target_x = rect.right - 330
            target_y = rect.top + (rect.bottom - rect.top - 340) // 2
            cur_x = self.window.winfo_x()
            cur_y = self.window.winfo_y()
            if abs(cur_x - target_x) > 5 or abs(cur_y - target_y) > 5:
                self.window.geometry(f'+{target_x}+{target_y}')

    def _get_game_hwnd(self):
        """获取游戏窗口hwnd"""
        import ctypes
        hwnd = 0
        if self.gui.selected_window:
            hwnd = self.gui.selected_window.get('hwnd', 0)
        if not hwnd and self.gui.game_monitor and self.gui.game_monitor.screen_capture:
            hwnd = self.gui.game_monitor.screen_capture.window_hwnd
        if not hwnd:
            hwnd = self.gui.config_data.get('window', {}).get('hwnd', 0)
        if hwnd and ctypes.windll.user32.IsWindow(hwnd):
            return hwnd
        return 0


class GameMonitorGUI:
    """游戏监控GUI主界面"""

    VERSION = "1.1.0"
    AUTHOR = "重楼一叶"
    PAN_LINK = "https://qj2smd.ysepan.com/"
    PAN_PASSWORD = "1234"
    GITHUB_LINK = "https://github.com/coralfox/smd_game_monitor"
    UPDATE_URL = "https://raw.githubusercontent.com/coralfox/smd_game_monitor/refs/heads/master/version.txt"
    GITEE_UPDATE_URL = "https://raw.giteeusercontent.com/coralfox/smd_game_monitor/raw/master/version.txt"
    CHANGELOG_URL = "https://raw.githubusercontent.com/coralfox/smd_game_monitor/refs/heads/master/CHANGELOG.html"
    GITEE_CHANGELOG_URL = "https://raw.giteeusercontent.com/coralfox/smd_game_monitor/raw/master/CHANGELOG.html"
    WECHAT_PAY_URL = "wxp://f2f0sSU1dBcu_SftrSutvSM9dVK1LasDZnOShA4l10NmCY4"       # 你的微信收款链接
    ALIPAY_PAY_URL = "https://qr.alipay.com/fkx10172eaxgrkqw2wlbtd3?t=1782895171528"  # 你的支付宝收款链接


    def __init__(self, root):
        self.root = root
        self.root.title(f"SMD游戏监控程序 v{self.VERSION} - 作者:{self.AUTHOR}")
        # 延迟检测更新，避免阻塞启动
        self.root.after(2000, self._check_update)
        self.root.geometry("960x750")
        self.root.minsize(960, 700)
        # 窗口居中显示
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 960) // 2
        y = (self.root.winfo_screenheight() - 700) // 2
        self.root.geometry(f"+{x}+{y}")

        # 配置文件路径（兼容 PyInstaller 单文件模式）
        if getattr(sys, 'frozen', False):
            self.app_dir = os.path.dirname(sys.executable)
        else:
            self.app_dir = os.path.dirname(os.path.abspath(__file__))
        self.configs_dir = os.path.join(self.app_dir, 'configs')
        os.makedirs(self.configs_dir, exist_ok=True)
        # 上次使用的配置记录
        self.last_config_file = os.path.join(self.configs_dir, '.last_config')
        # 加载上次使用的配置文件，或使用硬编码默认值
        self.config_path = self._get_last_config_path()
        self.config_data = self._load_config()
        self.config_filename = os.path.basename(self.config_path) if self.config_path else ''

        # 当前选中的窗口
        self.selected_window = None

        # 监控线程
        self.monitor_thread = None
        self.monitor_running = False
        self.game_monitor = None

        # 悬浮统计窗口
        self.floating_window = FloatingStatsWindow(self)

        self._build_ui()
        self._load_config_to_ui()

        # 生成默认配置文件（如果不存在）
        self._ensure_default_config()

        # 首次启动：如果没有上次配置记录，自动设为default.json并保存.last_config
        if not self.config_path:
            default_path = os.path.join(self.configs_dir, 'default.json')
            if os.path.exists(default_path):
                self.config_path = default_path
                self.config_filename = 'default.json'
                self.config_data = self._load_config()
                self._load_config_to_ui()
                self._refresh_config_combo()
                self._save_last_config()

        # 注册全局热键
        self._setup_hotkeys()

    def _load_config(self):
        if self.config_path and os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return self._default_config()

    def _get_last_config_path(self):
        """读取上次使用的配置文件路径，如果文件不存在则返回None"""
        try:
            if os.path.exists(self.last_config_file):
                with open(self.last_config_file, 'r', encoding='utf-8') as f:
                    name = f.read().strip()
                if name:
                    path = os.path.join(self.configs_dir, name)
                    if os.path.exists(path):
                        return path
        except:
            pass
        return None

    def _save_last_config(self):
        """记录当前使用的配置文件名"""
        try:
            name = os.path.basename(self.config_path)
            with open(self.last_config_file, 'w', encoding='utf-8') as f:
                f.write(name)
        except:
            pass

    def _scan_config_files(self):
        """扫描configs目录下所有.json文件，返回去掉.json后缀的名字列表"""
        files = []
        if os.path.exists(self.configs_dir):
            for f in os.listdir(self.configs_dir):
                if f.endswith('.json') and f != 'default.json':
                    files.append(f[:-5])  # 去掉.json后缀
        return sorted(files)

    def _refresh_config_combo(self):
        """刷新配置文件下拉框（显示名不含.json后缀）"""
        current = self.config_filename[:-5] if self.config_filename.endswith('.json') else self.config_filename
        self.config_combo['values'] = self._scan_config_files()
        if current and current in self.config_combo['values']:
            self.config_combo.set(current)
        else:
            self.config_combo.set('')

    def _ensure_default_config(self):
        """确保configs目录下存在default.json默认配置文件（优先从打包资源复制）"""
        default_path = os.path.join(self.configs_dir, 'default.json')
        if not os.path.exists(default_path):
            # PyInstaller 单文件模式：优先从打包资源复制
            if getattr(sys, 'frozen', False):
                bundled = os.path.join(sys._MEIPASS, 'configs', 'default.json')
                if os.path.exists(bundled):
                    import shutil
                    shutil.copy2(bundled, default_path)
                    self._refresh_config_combo()
                    return
            # 否则重新生成
            default_data = self._default_config()
            os.makedirs(self.configs_dir, exist_ok=True)
            with open(default_path, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, ensure_ascii=False, indent=4)
            self._refresh_config_combo()

    def _default_config(self):
        return {
            "window": {"title": "Tom Clancy's The Division 2", "class_name": "", "use_window": True},
            "monitor": {
                "region": {"left": 10, "top": 10, "width": 360, "height": 260},
                "check_interval": 1.0,
                "preprocess": {"grayscale": False, "scale": 1}
            },
            "debounce": {"enabled": True, "min_stable_frames": 2},
            "frequency": {
                "window_seconds": 60,
                "min_samples": 20,
                "cooldown_seconds": 30
            },
            "strategies": {
                "single_stuck": {
                    "name": "单一移动卡死处理",
                    "description": "当检测到单一移动事件卡死时执行（60秒窗口，快速响应）",
                    "match_ids": ["当前事件", "移动"],
                    "exclude_ids": [],
                    "match_stuck_type": "single",
                    "severity": 1.0,
                    "actions": [
                        {"type": "screenshot"},
                        {"type": "key_press", "key": "p", "presses": 2, "interval": 0.5}
                    ],
                    "stuck_threshold": 30,
                    "stuck_ratio": 0.8
                },
                "action_stuck": {
                    "name": "事件动作卡死处理",
                    "description": "当检测到非移动类事件卡死时执行（5分钟窗口，容忍限时打怪等长处理）",
                    "match_ids": ["当前事件"],
                    "exclude_ids": ["移动"],
                    "match_stuck_type": "single",
                    "severity": 1.0,
                    "window_seconds": 300,
                    "min_samples": 100,
                    "actions": [
                        {"type": "screenshot"},
                        {"type": "key_press", "key": "p", "presses": 2, "interval": 0.5}
                    ],
                    "stuck_threshold": 200,
                    "stuck_ratio": 0.8
                },
                "alternating_stuck": {
                    "name": "交替卡死处理",
                    "description": "当检测到两个事件交替卡死时执行",
                    "match_ids": ["当前事件"],
                    "exclude_ids": [],
                    "match_stuck_type": "alternating",
                    "severity": 2.0,
                    "actions": [
                        {"type": "screenshot"},
                        {"type": "delay", "seconds": 1.0},
                        {"type": "key_press", "key": "p", "presses": 2, "interval": 0.5}
                    ],
                    "alternating_threshold": 40,
                    "alternating_ratio": 0.85
                },
                "path_error": {
                    "name": "路径错误处理",
                    "description": "当检测到路径相关错误时执行",
                    "match_ids": ["路劲", "错误", "开头"],
                    "exclude_ids": [],
                    "match_stuck_type": "single",
                    "severity": 2.0,
                    "actions": [
                        {"type": "screenshot"},
                        {"type": "delay", "seconds": 1.0},
                        {"type": "key_press", "key": "p", "presses": 1}
                    ],
                    "stuck_threshold": 30,
                    "stuck_ratio": 0.8
                },
                "no_bounty_stuck": {
                    "name": "无悬赏卡死处理",
                    "description": "当前事件单一卡死且没有悬赏执行时触发，说明脚本未运行",
                    "match_ids": [],
                    "exclude_ids": ["悬赏执行"],
                    "match_stuck_type": "single",
                    "severity": 1.0,
                    "actions": [
                        {"type": "screenshot"},
                        {"type": "delay", "seconds": 1.0},
                        {"type": "key_press", "key": "p", "presses": 1}
                    ],
                    "stuck_threshold": 30,
                    "stuck_ratio": 0.8
                }
            },
            "logging": {"level": "INFO", "log_to_file": True, "log_file": "game_monitor.log", "save_screenshots": True, "screenshot_dir": "screenshots"},
            "hotkeys": {"start_stop": "F8", "pause_resume": "F10"},
            "ui_options": {"always_on_top_game": False, "show_floating_stats": True},
            "alert": {
                "pushplus_enabled": False, "pushplus_token": "",
                "email_enabled": False,
                "email_smtp_server": "smtp.qq.com", "email_smtp_port": 465, "email_use_ssl": True,
                "email_user": "", "email_password": "", "email_to": "",
                "alert_cooldown_minutes": 15,
                "alert_trigger_threshold": 6,
                "alert_severity_threshold": 10,
                "imgbb_api_key": "",
                "imgbb_expiration_days": 7,
                "stats_report_enabled": False,
                "stats_report_interval": 60
            }
        }

    def _save_config(self):
        if not self.config_path:
            return
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config_data, f, ensure_ascii=False, indent=4)

    def _build_ui(self):
        # 先构建底部控制栏（必须在Notebook之前pack，否则会被挤出窗口）
        self._build_control_bar()

        # 中间区域：标签页
        mid_frame = tk.Frame(self.root)
        mid_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))

        # Notebook占满主区域
        self.notebook = ttk.Notebook(mid_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # 标签页1: 监控设置
        self._build_monitor_tab()

        # 标签页2: 频率检测
        self._build_frequency_tab()

        # 标签页3: 重启原力
        self._build_restart_tab()

        # 标签页4: 策略管理
        self._build_strategies_tab()

        # 标签页4: 日志
        self._build_log_tab()

        # 标签页5: 更新记录
        self._build_changelog_tab()

        # 标签页6: 关于
        self._build_about_tab()

    def _build_monitor_tab(self):
        tab = tk.Frame(self.notebook)
        self.notebook.add(tab, text=" 监控设置 ")

        canvas = tk.Canvas(tab, highlightthickness=0)
        scrollbar = tk.Scrollbar(tab, orient=tk.VERTICAL, command=canvas.yview)
        self.monitor_scroll_frame = tk.Frame(canvas)

        # ===== 关键修改：绑定 Canvas 大小变化事件 =====
        def on_canvas_configure(event):
            # 当 Canvas 大小变化时，调整内部 Frame 的宽度
            canvas.itemconfig(self.canvas_window, width=event.width)
        
        canvas.bind('<Configure>', on_canvas_configure)
        
        # 创建窗口并保存引用
        self.canvas_window = canvas.create_window((0, 0), window=self.monitor_scroll_frame, anchor='nw')
        
        # 更新滚动区域
        def on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox('all'))
        
        self.monitor_scroll_frame.bind('<Configure>', on_frame_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        # ===== 鼠标滚轮绑定 =====
        def _on_mousewheel(event):
            current_tab = self.notebook.index('current')
            monitor_tab_idx = self.notebook.index(tab)
            if current_tab != monitor_tab_idx:
                return
            canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        
        canvas.bind('<MouseWheel>', _on_mousewheel)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # ===== 所有内容放在 scroll_frame 中 =====
        sf = self.monitor_scroll_frame

        # ===== 窗口选择区域 =====
        window_frame = tk.LabelFrame(sf, text="游戏窗口", font=('微软雅黑', 11))
        window_frame.pack(fill=tk.X, padx=20, pady=10)
        
        # 关键：让内部 Frame 的列权重为 1，使 Entry 能扩展
        window_frame.grid_columnconfigure(1, weight=1)
        
        row = tk.Frame(window_frame)
        row.pack(fill=tk.X, padx=20, pady=10)
        tk.Label(row, text="窗口标题:", width=10, anchor='e', font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=5)
        self.window_title_var = tk.StringVar(value="")
        self.window_title_entry = tk.Entry(row, textvariable=self.window_title_var, font=('微软雅黑', 10))
        self.window_title_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # 窗口状态标签
        self.window_status_var = tk.StringVar(value="未选择窗口")
        tk.Label(window_frame, textvariable=self.window_status_var,
                font=('微软雅黑', 9), fg='#666').pack(pady=2)

        # 窗口按钮
        btn_frame = tk.Frame(window_frame)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="选择游戏窗口", command=self._select_window,
                width=12, bg='#2196F3', fg='white', font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="使用当前鼠标下窗口", command=self._use_mouse_window,
                width=16, font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="根据标题查找窗口", command=self._find_window_by_title,
                width=16, bg='#FF9800', fg='white', font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="清除窗口", command=self._clear_window,
                width=10, font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=10)

        # ===== 监控区域 =====
        region_frame = tk.LabelFrame(sf, text="监控区域 (相对于游戏窗口左上角)", font=('微软雅黑', 11))
        region_frame.pack(fill=tk.X, padx=10, pady=10)

        # 区域坐标
        coords_frame = tk.Frame(region_frame)
        coords_frame.pack(pady=10)
        
        # 关键：让坐标输入框均匀分配空间
        for i in range(8):  # 4个标签 + 4个输入框
            coords_frame.grid_columnconfigure(i, weight=1)

        self.region_vars = {}
        for i, (label, key) in enumerate([('X:', 'left'), ('Y:', 'top'), ('宽:', 'width'), ('高:', 'height')]):
            tk.Label(coords_frame, text=label, font=('微软雅黑', 10)).grid(row=0, column=i*2, padx=5, sticky='e')
            var = tk.StringVar(value='0')
            entry = tk.Entry(coords_frame, textvariable=var, font=('Consolas', 10))
            entry.grid(row=0, column=i*2+1, padx=2, sticky='we')
            self.region_vars[key] = var

        # 区域选择按钮
        btn_frame = tk.Frame(region_frame)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="在窗口上选择区域", command=self._select_region_on_window,
                width=16, bg='#4CAF50', fg='white', font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="屏幕选择区域(绝对坐标)", command=self._select_region_screen,
                width=20, font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="测试截图", command=self._test_capture,
                width=12, font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="测试OCR", command=self._test_ocr,
                width=12, font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=10)

        # 截图预览
        preview_frame = tk.LabelFrame(sf, text="截图预览", font=('微软雅黑', 11))
        preview_frame.pack(fill=tk.BOTH, expand=False, padx=10, pady=5)
        preview_frame.pack_propagate(False)
        preview_frame.configure(height=200)

        self.preview_label = tk.Label(preview_frame, text="点击\"测试截图\"预览",
                                    font=('微软雅黑', 12), fg='gray')
        self.preview_label.pack(expand=True, fill=tk.BOTH)

        # OCR结果
        ocr_frame = tk.Frame(sf)
        ocr_frame.pack(fill=tk.X, padx=10, pady=5)
        self.ocr_result_var = tk.StringVar(value="OCR结果: 未识别")
        tk.Label(ocr_frame, textvariable=self.ocr_result_var,
                font=('Consolas', 12), fg='#2196F3').pack(fill=tk.X)

    def _build_frequency_tab(self):
        tab = tk.Frame(self.notebook)
        self.notebook.add(tab, text=" 监控参数 ")

        # ===== 检测配置 =====
        params_frame = tk.LabelFrame(tab, text="检测配置", font=('微软雅黑', 11))
        params_frame.pack(fill=tk.X, padx=10, pady=5)

        # 第一行：检查间隔 + 统计窗口 + 最小样本数 + 触发冷却
        row = tk.Frame(params_frame)
        row.pack(fill=tk.X, pady=3)
        tk.Label(row, text="检查间隔(秒):", anchor='e').pack(side=tk.LEFT, padx=(5, 2))
        self.interval_var = tk.StringVar(value='0.5')
        tk.Entry(row, textvariable=self.interval_var, width=6).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(row, text="统计窗口(秒):", anchor='e').pack(side=tk.LEFT, padx=(0, 2))
        self.freq_vars = {}
        self.freq_vars['window_seconds'] = tk.StringVar(value='60')
        tk.Entry(row, textvariable=self.freq_vars['window_seconds'], width=6).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(row, text="最小样本数:", anchor='e').pack(side=tk.LEFT, padx=(0, 2))
        self.freq_vars['min_samples'] = tk.StringVar(value='20')
        tk.Entry(row, textvariable=self.freq_vars['min_samples'], width=6).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(row, text="触发冷却(秒):", anchor='e').pack(side=tk.LEFT, padx=(0, 2))
        self.freq_vars['cooldown_seconds'] = tk.StringVar(value='30')
        tk.Entry(row, textvariable=self.freq_vars['cooldown_seconds'], width=6).pack(side=tk.LEFT, padx=(0, 5))

        # UI选项 + 自适应 + 快捷键
        ui_row = tk.Frame(params_frame)
        ui_row.pack(fill=tk.X, pady=3)
        self.always_on_top_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ui_row, text="总是置顶游戏窗口", variable=self.always_on_top_var,
                       font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=5)
        self.show_floating_var = tk.BooleanVar(value=True)
        tk.Checkbutton(ui_row, text="显示悬浮信息", variable=self.show_floating_var,
                       font=('微软雅黑', 10), command=self._toggle_floating).pack(side=tk.LEFT, padx=15)
        self.adaptive_enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(ui_row, text="自适应调整", variable=self.adaptive_enabled_var,
                       font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=15)

        # 快捷键设置（按键捕捉）
        tk.Label(ui_row, text="开始/停止:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(30, 2))
        self.hotkey_start_var = tk.StringVar(value='F8')
        self.hotkey_start_label = tk.Label(ui_row, textvariable=self.hotkey_start_var,
                                           font=('Consolas', 10, 'bold'), fg='#1565C0',
                                           width=8, anchor='center')
        self.hotkey_start_label.pack(side=tk.LEFT, padx=2)
        tk.Button(ui_row, text="设置", width=5, font=('微软雅黑', 9),
                  command=lambda: self._capture_hotkey('start')).pack(side=tk.LEFT, padx=2)

        tk.Label(ui_row, text="暂停/恢复:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(10, 2))
        self.hotkey_pause_var = tk.StringVar(value='F10')
        self.hotkey_pause_label = tk.Label(ui_row, textvariable=self.hotkey_pause_var,
                                           font=('Consolas', 10, 'bold'), fg='#1565C0',
                                           width=8, anchor='center')
        self.hotkey_pause_label.pack(side=tk.LEFT, padx=2)
        self.hotkey_pause_btn = tk.Button(ui_row, text="设置", width=5, font=('微软雅黑', 9),
                                          command=lambda: self._capture_hotkey('pause'))
        self.hotkey_pause_btn.pack(side=tk.LEFT, padx=2)

        # ===== 报警核心参数（含推送渠道、高级功能、统计报告时间窗口） =====
        core_frame = tk.LabelFrame(tab, text="报警核心参数", font=('微软雅黑', 10))
        core_frame.pack(fill=tk.X, padx=10, pady=5)

        # 行1: 报警冷却 + 检测窗口系数 + 严重度阈值 + 检测时间
        core_row = tk.Frame(core_frame)
        core_row.pack(fill=tk.X, pady=2)
        tk.Label(core_row, text="报警冷却:", font=('微软雅黑', 10), anchor='e').pack(side=tk.LEFT, padx=(5, 2))
        self.alert_cooldown_var = tk.StringVar(value='15')
        tk.Entry(core_row, textvariable=self.alert_cooldown_var, width=5,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=(0, 2))
        tk.Label(core_row, text="分", font=('微软雅黑', 9), fg='#888').pack(side=tk.LEFT, padx=(0, 12))

        tk.Label(core_row, text="窗口系数:", font=('微软雅黑', 10), anchor='e').pack(side=tk.LEFT, padx=(0, 2))
        self.alert_trigger_threshold_var = tk.StringVar(value='6')
        tk.Entry(core_row, textvariable=self.alert_trigger_threshold_var, width=5,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=(0, 2))
        tk.Label(core_row, text="×", font=('微软雅黑', 9), fg='#888').pack(side=tk.LEFT, padx=(0, 12))

        tk.Label(core_row, text="严重度:", font=('微软雅黑', 10), anchor='e').pack(side=tk.LEFT, padx=(0, 2))
        self.alert_severity_threshold_var = tk.StringVar(value='10')
        tk.Entry(core_row, textvariable=self.alert_severity_threshold_var, width=5,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=(0, 2))
        tk.Label(core_row, text="检测时间:", font=('微软雅黑', 10), anchor='e').pack(side=tk.LEFT, padx=(10, 2))
        self.alert_detect_time_var = tk.StringVar(value='计算中...')
        tk.Label(core_row, textvariable=self.alert_detect_time_var,
                 font=('Consolas', 10), fg='#1565C0').pack(side=tk.LEFT, padx=2)
        # 绑定数值变化时自动重新计算
        self.alert_trigger_threshold_var.trace_add('write', lambda *a: self._update_alert_detect_time())
        self.alert_severity_threshold_var.trace_add('write', lambda *a: self._update_alert_detect_time())
        self.freq_vars['cooldown_seconds'].trace_add('write', lambda *a: self._update_alert_detect_time())

        # 分隔线
        tk.Frame(core_frame, height=1, bg='#ccc').pack(fill=tk.X, padx=5, pady=(4, 2))

        # 行2: PushPlus
        pp_row = tk.Frame(core_frame)
        pp_row.pack(fill=tk.X, pady=1)
        self.pushplus_enabled_var = tk.BooleanVar(value=False)
        tk.Checkbutton(pp_row, text="PushPlus", variable=self.pushplus_enabled_var,
                       font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=5)
        pp_link = tk.Label(pp_row, text="(官网)", font=('微软雅黑', 9, 'underline'),
                           fg='#1565C0', cursor='hand2')
        pp_link.pack(side=tk.LEFT, padx=2)
        pp_link.bind('<Button-1>', lambda e: os.startfile('https://www.pushplus.plus/'))
        tk.Label(pp_row, text="Token:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(4, 2))
        self.pushplus_token_var = tk.StringVar(value='')
        tk.Entry(pp_row, textvariable=self.pushplus_token_var, width=32,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        tk.Button(pp_row, text="测试", command=self._test_pushplus,
                  width=6, bg='#4CAF50', fg='white', font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=6)

        # 行3: 邮件第1行 (SMTP + 端口 + SSL + 测试按钮)
        em_row1 = tk.Frame(core_frame)
        em_row1.pack(fill=tk.X, pady=1)
        self.email_enabled_var = tk.BooleanVar(value=False)
        tk.Checkbutton(em_row1, text="邮件", variable=self.email_enabled_var,
                       font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=5)
        tk.Label(em_row1, text="SMTP:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(4, 2))
        self.email_smtp_var = tk.StringVar(value='smtp.qq.com')
        tk.Entry(em_row1, textvariable=self.email_smtp_var, width=14,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        tk.Label(em_row1, text="端口:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(6, 2))
        self.email_port_var = tk.StringVar(value='465')
        tk.Entry(em_row1, textvariable=self.email_port_var, width=5,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        self.email_ssl_var = tk.BooleanVar(value=True)
        tk.Checkbutton(em_row1, text="SSL", variable=self.email_ssl_var,
                       font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=4)
        tk.Button(em_row1, text="测试", command=self._test_email,
                  width=6, bg='#4CAF50', fg='white', font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=8)

        # 行4: 邮件第2行 (发件邮箱 + 密码 + 收件邮箱)
        em_row2 = tk.Frame(core_frame)
        em_row2.pack(fill=tk.X, pady=1)
        tk.Label(em_row2, text="发件:", font=('微软雅黑', 9), anchor='e').pack(side=tk.LEFT, padx=(5, 2))
        self.email_user_var = tk.StringVar(value='')
        tk.Entry(em_row2, textvariable=self.email_user_var, width=18,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        tk.Label(em_row2, text="密码:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(6, 2))
        self.email_pass_var = tk.StringVar(value='')
        tk.Entry(em_row2, textvariable=self.email_pass_var, width=14,
                 font=('Consolas', 10), show='*').pack(side=tk.LEFT, padx=2)
        tk.Label(em_row2, text="收件:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(6, 2))
        self.email_to_var = tk.StringVar(value='')
        tk.Entry(em_row2, textvariable=self.email_to_var, width=18,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)

        # 分隔线
        tk.Frame(core_frame, height=1, bg='#ccc').pack(fill=tk.X, padx=5, pady=(4, 2))

        # (图床Key已移动到统计报告推送行)

        # 行6: 定期统计报告推送 + 图床Key
        sr_row = tk.Frame(core_frame)
        sr_row.pack(fill=tk.X, pady=1)
        self.stats_report_enabled_var = tk.BooleanVar(value=False)
        tk.Checkbutton(sr_row, text="定期统计报告推送", variable=self.stats_report_enabled_var,
                       font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=5)
        tk.Label(sr_row, text="间隔:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(8, 2))
        self.stats_report_interval_var = tk.StringVar(value='60')
        tk.Entry(sr_row, textvariable=self.stats_report_interval_var, width=6,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        tk.Label(sr_row, text="分钟", font=('微软雅黑', 8), fg='#888').pack(side=tk.LEFT, padx=2)
        ibb_link = tk.Label(sr_row, text="imgbb图床Key:", font=('微软雅黑', 9, 'underline'),
                            fg='#1565C0', cursor='hand2')
        ibb_link.pack(side=tk.LEFT, padx=(15, 2))
        ibb_link.bind('<Button-1>', lambda e: os.startfile('https://imgbb.com/'))
        self.imgbb_api_key_var = tk.StringVar(value='')
        tk.Entry(sr_row, textvariable=self.imgbb_api_key_var, width=22,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        tk.Label(sr_row, text="保存:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(6, 2))
        self.imgbb_expiration_var = tk.StringVar(value='7')
        tk.Spinbox(sr_row, from_=1, to=365, textvariable=self.imgbb_expiration_var, width=4,
                   font=('Consolas', 10), justify=tk.CENTER).pack(side=tk.LEFT)
        tk.Label(sr_row, text="天", font=('微软雅黑', 8), fg='#888').pack(side=tk.LEFT, padx=2)

        # 行7: 统计报告时间窗口
        srt_row = tk.Frame(core_frame)
        srt_row.pack(fill=tk.X, pady=1)
        self.srt_enabled_var = tk.BooleanVar(value=False)
        tk.Checkbutton(srt_row, text="报告时间窗口", variable=self.srt_enabled_var,
                       font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=5)
        tk.Label(srt_row, text="时段:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(8, 2))
        self.srt_start_hour_var = tk.StringVar(value='0')
        self.srt_start_min_var = tk.StringVar(value='0')
        tk.Spinbox(srt_row, from_=0, to=23, textvariable=self.srt_start_hour_var, width=3,
                   font=('Consolas', 10), justify=tk.CENTER).pack(side=tk.LEFT)
        tk.Label(srt_row, text=":", font=('微软雅黑', 10)).pack(side=tk.LEFT)
        tk.Spinbox(srt_row, from_=0, to=59, textvariable=self.srt_start_min_var, width=3,
                   font=('Consolas', 10), justify=tk.CENTER).pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(srt_row, text="~", font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=2)
        self.srt_end_hour_var = tk.StringVar(value='23')
        self.srt_end_min_var = tk.StringVar(value='59')
        tk.Spinbox(srt_row, from_=0, to=23, textvariable=self.srt_end_hour_var, width=3,
                   font=('Consolas', 10), justify=tk.CENTER).pack(side=tk.LEFT)
        tk.Label(srt_row, text=":", font=('微软雅黑', 10)).pack(side=tk.LEFT)
        tk.Spinbox(srt_row, from_=0, to=59, textvariable=self.srt_end_min_var, width=3,
                   font=('Consolas', 10), justify=tk.CENTER).pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(srt_row, text="(只在此时段内发送)", font=('微软雅黑', 8), fg='#888').pack(side=tk.LEFT, padx=4)

        # ===== 挂机设置（紧凑布局） =====
        idle_frame = tk.LabelFrame(tab, text="挂机设置", font=('微软雅黑', 10))
        idle_frame.pack(fill=tk.X, padx=10, pady=5)

        idle_row = tk.Frame(idle_frame)
        idle_row.pack(fill=tk.X, pady=3)
        self.idle_enabled_var = tk.BooleanVar(value=False)
        tk.Checkbutton(idle_row, text="启用", variable=self.idle_enabled_var,
                       font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=5)
        tk.Label(idle_row, text="时间(分):", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(10, 2))
        self.idle_minutes_var = tk.StringVar(value='0')
        tk.Entry(idle_row, textvariable=self.idle_minutes_var, width=6,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        tk.Label(idle_row, text="停止时间:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(10, 2))
        self.idle_stop_hour_var = tk.StringVar(value='0')
        self.idle_stop_min_var = tk.StringVar(value='0')
        tk.Spinbox(idle_row, from_=0, to=23, textvariable=self.idle_stop_hour_var, width=3,
                   font=('Consolas', 10), justify=tk.CENTER).pack(side=tk.LEFT)
        tk.Label(idle_row, text=":", font=('微软雅黑', 10)).pack(side=tk.LEFT)
        tk.Spinbox(idle_row, from_=0, to=59, textvariable=self.idle_stop_min_var, width=3,
                   font=('Consolas', 10), justify=tk.CENTER).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(idle_row, text="×", font=('微软雅黑', 8), width=2,
                  command=lambda: (self.idle_stop_hour_var.set('0'), self.idle_stop_min_var.set('0'))).pack(side=tk.LEFT)
        tk.Label(idle_row, text="轮数:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(10, 2))
        self.idle_rounds_var = tk.StringVar(value='0')
        tk.Entry(idle_row, textvariable=self.idle_rounds_var, width=6,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        tk.Label(idle_row, text="次数:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(10, 2))
        self.idle_execs_var = tk.StringVar(value='0')
        tk.Entry(idle_row, textvariable=self.idle_execs_var, width=6,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        tk.Label(idle_row, text="(0=无限,到达后取消启用)", font=('微软雅黑', 8), fg='#888').pack(side=tk.LEFT, padx=5)

        # (统计报告时间窗口已合并到报警核心参数中)

    def _build_restart_tab(self):
        """构建重启原力配置标签页"""
        tab = tk.Frame(self.notebook)
        self.notebook.add(tab, text=" 重启原力 ")

        # 基本设置
        basic_frame = tk.LabelFrame(tab, text="基本设置", font=('微软雅黑', 10))
        basic_frame.pack(fill=tk.X, padx=10, pady=5)

        en_row = tk.Frame(basic_frame)
        en_row.pack(fill=tk.X, pady=3)
        self.restart_enabled_var = tk.BooleanVar(value=False)
        tk.Checkbutton(en_row, text="启用自动重启", variable=self.restart_enabled_var,
                       font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=5)

        # bat文件路径
        bat_row = tk.Frame(basic_frame)
        bat_row.pack(fill=tk.X, pady=3)
        tk.Label(bat_row, text="启动Bat:", font=('微软雅黑', 9), width=10, anchor='e').pack(side=tk.LEFT, padx=5)
        self.restart_bat_var = tk.StringVar(value='')
        tk.Entry(bat_row, textvariable=self.restart_bat_var, width=40,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        tk.Button(bat_row, text="浏览", width=5, font=('微软雅黑', 9),
                  command=self._browse_bat).pack(side=tk.LEFT, padx=5)

        # 游戏快捷方式
        gs_row = tk.Frame(basic_frame)
        gs_row.pack(fill=tk.X, pady=3)
        tk.Label(gs_row, text="游戏快捷方式:", font=('微软雅黑', 9), width=12, anchor='e').pack(side=tk.LEFT, padx=5)
        self.restart_game_shortcut_var = tk.StringVar(value='')
        tk.Entry(gs_row, textvariable=self.restart_game_shortcut_var, width=35,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        tk.Button(gs_row, text="浏览", width=5, font=('微软雅黑', 9),
                  command=self._browse_game_shortcut).pack(side=tk.LEFT, padx=5)

        # rundll32窗口信息
        rd_row = tk.Frame(basic_frame)
        rd_row.pack(fill=tk.X, pady=3)
        tk.Label(rd_row, text="原力标题:", font=('微软雅黑', 9), width=10, anchor='e').pack(side=tk.LEFT, padx=5)
        self.restart_rundll32_title_var = tk.StringVar(value='音乐盒子')
        tk.Entry(rd_row, textvariable=self.restart_rundll32_title_var, width=20,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        tk.Label(rd_row, text="游戏标题:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(10, 2))
        self.restart_game_title_var = tk.StringVar(value="Tom Clancy's The Division 2")
        tk.Entry(rd_row, textvariable=self.restart_game_title_var, width=30,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)

        # 触发条件
        trigger_frame = tk.LabelFrame(tab, text="触发重启条件(策略触发)", font=('微软雅黑', 10))
        trigger_frame.pack(fill=tk.X, padx=10, pady=5)

        tg_row = tk.Frame(trigger_frame)
        tg_row.pack(fill=tk.X, pady=3)
        tk.Label(tg_row, text="连续触发次数(不变回0):", font=('微软雅黑', 9), width=12, anchor='e').pack(side=tk.LEFT, padx=5)
        self.restart_burst_var = tk.StringVar(value='5')
        tk.Entry(tg_row, textvariable=self.restart_burst_var, width=6,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        tk.Label(tg_row, text="冷却期间仍触发:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(15, 2))
        self.restart_cooldown_trigger_var = tk.StringVar(value='10')
        tk.Entry(tg_row, textvariable=self.restart_cooldown_trigger_var, width=6,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)
        tk.Label(tg_row, text="次", font=('微软雅黑', 9), fg='#888').pack(side=tk.LEFT)

        # 按钮文字
        btn_frame = tk.LabelFrame(tab, text="原力启动", font=('微软雅黑', 10))
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        # 播放按钮文字
        pb_row = tk.Frame(btn_frame)
        pb_row.pack(fill=tk.X, pady=2)
        tk.Label(pb_row, text="播放按钮文字:", font=('微软雅黑', 9), width=12, anchor='e').pack(side=tk.LEFT, padx=5)
        self.restart_play_text_var = tk.StringVar(value='播放')
        tk.Entry(pb_row, textvariable=self.restart_play_text_var, width=20,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)

        # 清理按钮文字
        cb_row = tk.Frame(btn_frame)
        cb_row.pack(fill=tk.X, pady=2)
        tk.Label(cb_row, text="清理按钮文字:", font=('微软雅黑', 9), width=12, anchor='e').pack(side=tk.LEFT, padx=5)
        self.restart_cleanup_text_var = tk.StringVar(value='清理歌曲播放')
        tk.Entry(cb_row, textvariable=self.restart_cleanup_text_var, width=20,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)

        # 等待文字
        wait_row = tk.Frame(btn_frame)
        wait_row.pack(fill=tk.X, pady=3)
        tk.Label(wait_row, text="播放等待文字:", font=('微软雅黑', 9), width=12, anchor='e').pack(side=tk.LEFT, padx=5)
        self.restart_wait_text_var = tk.StringVar(value='等待歌曲启动后点击')
        tk.Entry(wait_row, textvariable=self.restart_wait_text_var, width=30,
                 font=('Consolas', 10)).pack(side=tk.LEFT, padx=2)

        # SMD 配置编辑器
        cfg_frame = tk.LabelFrame(tab, text="SMD 配置管理", font=('微软雅黑', 10))
        cfg_frame.pack(fill=tk.X, padx=10, pady=5)

        op_row = tk.Frame(cfg_frame)
        op_row.pack(fill=tk.X, pady=5)
        tk.Button(op_row, text="打开 SMD 配置编辑器", font=('微软雅黑', 10),
                  bg='#2196F3', fg='white', command=self._open_smd_editor).pack(side=tk.LEFT, padx=10)
        tk.Button(op_row, text="测试重启流程", font=('微软雅黑', 10),
                  bg='#FF9800', fg='white', command=self._test_restart).pack(side=tk.LEFT, padx=10)

    def _browse_bat(self):
        """选择bat文件"""
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="选择启动Bat文件", filetypes=[("Bat文件", "*.bat"), ("所有文件", "*.*")])
        if path:
            self.restart_bat_var.set(path)

    def _browse_game_shortcut(self):
        """选择游戏快捷方式"""
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="选择游戏快捷方式",
                                          filetypes=[("快捷方式", "*.lnk"), ("所有文件", "*.*")])
        if path:
            self.restart_game_shortcut_var.set(path)

    def _open_smd_editor(self):
        """打开SMD配置编辑器"""
        try:
            from smd_config_editor import SMDConfigEditor
            SMDConfigEditor(self.root, game_monitor_ref=self.game_monitor)
        except Exception as e:
            messagebox.showerror("错误", f"打开编辑器失败: {e}")

    def _test_restart(self):
        """测试重启流程（仅日志输出，不实际执行）"""
        self._log("[重启] 测试模式 - 检查配置:")
        bat = self.restart_bat_var.get().strip()
        self._log(f"  Bat文件: {'✓' if bat and os.path.isfile(bat) else '✗ ' + ('未设置' if not bat else '文件不存在')}")
        gs = self.restart_game_shortcut_var.get().strip()
        if gs:
            if '://' in gs:
                self._log(f"  游戏快捷方式: ✓ {gs} (URL协议)")
            elif os.path.isfile(gs):
                self._log(f"  游戏快捷方式: ✓ {gs}")
            else:
                self._log(f"  游戏快捷方式: ✗ 无效 ({gs})")
        else:
            self._log("  游戏快捷方式: 未设置")
        self._log(f"  原力标题: {self.restart_rundll32_title_var.get() or '未设置'}")
        gt = self.restart_game_title_var.get() if hasattr(self, 'restart_game_title_var') else ''
        self._log(f"  游戏标题: {gt or '未设置'}")

    def _build_strategies_tab(self):
        tab = tk.Frame(self.notebook)
        self.notebook.add(tab, text=" 策略管理 ")

        # 策略列表
        list_frame = tk.LabelFrame(tab, text="策略列表", font=('微软雅黑', 11))
        list_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # 列表框
        tree_frame = tk.Frame(list_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.strategy_tree = ttk.Treeview(tree_frame,
                                          columns=('id', 'name', 'type', 'ids', 'excludes', 'actions'),
                                          show='headings', yscrollcommand=scrollbar.set)
        self.strategy_tree.heading('id', text='ID')
        self.strategy_tree.heading('name', text='名称')
        self.strategy_tree.heading('type', text='匹配类型')
        self.strategy_tree.heading('ids', text='匹配文本')
        self.strategy_tree.heading('excludes', text='排除文本')
        self.strategy_tree.heading('actions', text='动作数')
        self.strategy_tree.column('id', width=80)
        self.strategy_tree.column('name', width=100)
        self.strategy_tree.column('type', width=60)
        self.strategy_tree.column('ids', width=100)
        self.strategy_tree.column('excludes', width=80)
        self.strategy_tree.column('actions', width=20)
        self.strategy_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.strategy_tree.yview)

        # 按钮
        btn_frame = tk.Frame(list_frame)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="添加策略", command=self._add_strategy,
                  width=12, bg='#4CAF50', fg='white', font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=3)
        tk.Button(btn_frame, text="编辑策略", command=self._edit_strategy,
                  width=12, font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=3)
        tk.Button(btn_frame, text="删除策略", command=self._delete_strategy,
                  width=12, bg='#f44336', fg='white', font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=3)

    def _build_log_tab(self):
        tab = tk.Frame(self.notebook)
        self.notebook.add(tab, text=" 运行日志 ")

        # 日志过滤栏
        filter_frame = tk.Frame(tab)
        filter_frame.pack(fill=tk.X, padx=10, pady=(5, 0))

        tk.Label(filter_frame, text="日志级别:", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(0, 5))

        # 用独立标志位控制过滤，避免BooleanVar被回调重置
        self._log_level_enabled = {
            'DEBUG': False,
            'INFO': True,
            'WARNING': True,
            'ERROR': True,
        }
        # 存储所有日志行用于过滤重建
        self._log_entries = []  # [(message, tag), ...]
        self._log_level_checkbuttons = {}
        level_colors = {
            'DEBUG': '#888888',
            'INFO': '#2196F3',
            'WARNING': '#FF9800',
            'ERROR': '#f44336',
        }
        for level_name, color in level_colors.items():
            var = tk.IntVar(value=1 if self._log_level_enabled[level_name] else 0)
            self._log_level_checkbuttons[level_name] = var
            cb = tk.Checkbutton(filter_frame, text=level_name, variable=var,
                                fg=color,
                                font=('Consolas', 9, 'bold'),
                                command=self._on_level_toggle)
            cb.pack(side=tk.LEFT, padx=3)

        # 日志文本框（带颜色标签）
        self.log_text = scrolledtext.ScrolledText(tab, font=('Consolas', 10),
                                                   wrap=tk.WORD, state=tk.DISABLED,
                                                   spacing1=2, spacing3=2,
                                                   height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 配置各级别颜色标签
        self.log_text.tag_configure('DEBUG', foreground='#888888')
        self.log_text.tag_configure('INFO', foreground='#1565C0')
        self.log_text.tag_configure('WARNING', foreground='#E65100')
        self.log_text.tag_configure('ERROR', foreground='#C62828')

        # 日志计数器（用于行号）
        self._log_counter = 0

        # 日志控制
        btn_frame = tk.Frame(tab)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="清空日志", command=self._clear_log,
                  width=12).pack(side=tk.LEFT, padx=5)
        self.autoscroll_var = tk.BooleanVar(value=True)
        tk.Checkbutton(btn_frame, text="自动滚动", variable=self.autoscroll_var).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="全部显示", command=self._show_all_levels,
                  width=12).pack(side=tk.LEFT, padx=5)

    def _build_changelog_tab(self):
        tab = tk.Frame(self.notebook)
        self.notebook.add(tab, text=" 更新记录 ")

        # 顶部源选择 + 刷新
        ctrl_frame = tk.Frame(tab)
        ctrl_frame.pack(fill=tk.X, padx=10, pady=5)

        self.changelog_source_var = tk.StringVar(value='auto')
        tk.Label(ctrl_frame, text="源:", font=('微软雅黑', 10)).pack(side=tk.LEFT, padx=(0, 5))
        tk.Radiobutton(ctrl_frame, text="自动(竞速)", variable=self.changelog_source_var,
                       value='auto', font=('微软雅黑', 9)).pack(side=tk.LEFT)
        tk.Radiobutton(ctrl_frame, text="GitHub", variable=self.changelog_source_var,
                       value='github', font=('微软雅黑', 9)).pack(side=tk.LEFT)
        tk.Radiobutton(ctrl_frame, text="Gitee", variable=self.changelog_source_var,
                       value='gitee', font=('微软雅黑', 9)).pack(side=tk.LEFT)

        self.changelog_status_var = tk.StringVar(value="点击刷新获取更新记录...")
        tk.Label(ctrl_frame, textvariable=self.changelog_status_var,
                 font=('微软雅黑', 9), fg='#666').pack(side=tk.LEFT, padx=(20, 5))

        tk.Button(ctrl_frame, text="刷新", command=self._load_changelog,
                  width=8, bg='#4CAF50', fg='white', font=('微软雅黑', 9)).pack(side=tk.RIGHT, padx=5)

        # HtmlFrame 显示区域（100% 还原 HTML/CSS）
        try:
            from tkinterweb import HtmlFrame
            self.changelog_html = HtmlFrame(tab, messages_enabled=False)
            self.changelog_html.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        except Exception as e:
            self._log(f"[更新记录] HtmlFrame 加载失败: {e}")
            self.changelog_status_var.set("渲染引擎加载失败")
            return

        # 首次自动加载
        self.root.after(1500, self._load_changelog)

    def _load_changelog(self):
        """双源竞速获取 CHANGELOG.html"""
        import threading
        import urllib.request

        self.changelog_status_var.set("正在获取更新记录...")
        source = self.changelog_source_var.get()

        result_event = threading.Event()
        result_holder = {'content': None, 'source': None}

        def _fetch(url, name):
            if result_event.is_set():
                return
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    content = resp.read().decode('utf-8')
                if content and not result_event.is_set():
                    result_holder['content'] = content
                    result_holder['source'] = name
                    result_event.set()
            except Exception:
                pass

        def _on_result():
            result_event.wait(timeout=15)
            content = result_holder.get('content')
            src = result_holder.get('source', 'unknown')
            self.root.after(0, lambda: self._display_changelog(content, src))

        if source in ('auto', 'github'):
            threading.Thread(target=_fetch, args=(self.CHANGELOG_URL, "GitHub"), daemon=True).start()
        if source in ('auto', 'gitee'):
            threading.Thread(target=_fetch, args=(self.GITEE_CHANGELOG_URL, "Gitee"), daemon=True).start()
        threading.Thread(target=_on_result, daemon=True).start()

    def _display_changelog(self, content: str, source: str):
        if not hasattr(self, 'changelog_html'):
            return
        if content:
            self.changelog_html.load_html(content)
            self.changelog_status_var.set(f"已加载 (来自 {source})")
        else:
            # 加载失败时显示本地备份
            local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'CHANGELOG.html')
            if os.path.isfile(local_path):
                try:
                    self.changelog_html.load_file(local_path)
                    self.changelog_status_var.set("已加载本地备份 (网络不可用)")
                except Exception:
                    self.changelog_html.load_html(f'<html><body style="font-family:Microsoft YaHei;padding:20px;">'
                                                  f'<p>无法加载更新记录。</p>'
                                                  f'<p>请检查网络连接，或访问:</p>'
                                                  f'<a href="{self.GITHUB_LINK}">{self.GITHUB_LINK}</a>'
                                                  f'</body></html>')
                    self.changelog_status_var.set("加载失败")
            else:
                self.changelog_html.load_html(f'<html><body style="font-family:Microsoft YaHei;padding:20px;">'
                                              f'<p>无法加载更新记录。</p>'
                                              f'<p>请检查网络连接，或访问:</p>'
                                              f'<a href="{self.GITHUB_LINK}">{self.GITHUB_LINK}</a>'
                                              f'</body></html>')
                self.changelog_status_var.set("加载失败")

    def _build_about_tab(self):

        tab = tk.Frame(self.notebook)
        self.notebook.add(tab, text=" 关于 ")

        # ===== 标题 =====
        tk.Label(tab, text="SMD游戏监控程序", font=('微软雅黑', 18, 'bold'),
                fg='#333').pack(pady=(10, 2))

        # ===== 版本号 + 作者 =====
        info_frame = tk.Frame(tab)
        info_frame.pack(pady=5)

        tk.Label(info_frame, text=f"版本: {self.VERSION}", font=('Consolas', 12),
                fg='#666').pack(side=tk.LEFT, padx=(0, 15))

        tk.Label(info_frame, text="作者:", font=('微软雅黑', 11),
                width=5, anchor='e').pack(side=tk.LEFT)

        tk.Label(info_frame, text=self.AUTHOR, font=('Consolas', 11),
                fg='#1565C0').pack(side=tk.LEFT, padx=5)

        # ===== 链接按钮 =====
        link_frame = tk.Frame(tab)
        link_frame.pack(pady=5)

        tk.Button(link_frame, text="使用说明", width=12, font=('微软雅黑', 10),
                bg='#2196F3', fg='white',
                command=lambda: self._open_link('https://devfile.cn/preview/s0j6dt63/smdyouxijiankongchengxushiyongshuoming.html')).pack(side=tk.LEFT, padx=5)

        pan_text = f"访问网盘 (密码:{self.PAN_PASSWORD})" if self.PAN_PASSWORD else "访问网盘"
        tk.Button(link_frame, text=pan_text, width=20, font=('微软雅黑', 10),
                bg='#4CAF50', fg='white',
                command=lambda: self._open_link(self.PAN_LINK)).pack(side=tk.LEFT, padx=5)

        tk.Button(link_frame, text="访问 GitHub", width=12, font=('微软雅黑', 10),
                bg='#333', fg='white',
                command=lambda: self._open_link(self.GITHUB_LINK)).pack(side=tk.LEFT, padx=5)

        tk.Button(link_frame, text="检测更新", width=12, font=('微软雅黑', 10),
                bg='#E65100', fg='white',
                command=self._check_update).pack(side=tk.LEFT, padx=5)

        # ===== 更新状态 =====
        self.update_status_var = tk.StringVar(value="")
        tk.Label(tab, textvariable=self.update_status_var, font=('微软雅黑', 10),
                fg='#E65100').pack(pady=2)

        # ===== 收款码 =====
        donate_frame = tk.LabelFrame(tab, text=" 赞助作者 ", font=('微软雅黑', 11))
        donate_frame.pack(pady=(5, 5), padx=20, fill=tk.X)

        img_frame = tk.Frame(donate_frame)
        img_frame.pack(pady=5)

        # 微信
        wx_frame = tk.Frame(img_frame)
        wx_frame.pack(side=tk.LEFT, padx=30)

        tk.Label(wx_frame, text="微信支付", font=('微软雅黑', 10, 'bold'),
                fg='#07C160').pack(pady=(0, 5))

        try:
            wx_qr = qrcode.make(self.WECHAT_PAY_URL).resize((180, 180), Image.LANCZOS)
            self._wx_photo = ImageTk.PhotoImage(wx_qr)
            tk.Label(wx_frame, image=self._wx_photo).pack()
        except Exception as e:
            tk.Label(wx_frame, text=f"微信二维码生成失败\n{str(e)[:30]}",
                    font=('微软雅黑', 9), fg='red').pack()

        # 支付宝
        ali_frame = tk.Frame(img_frame)
        ali_frame.pack(side=tk.LEFT, padx=30)

        tk.Label(ali_frame, text="支付宝", font=('微软雅黑', 10, 'bold'),
                fg='#1677FF').pack(pady=(0, 5))

        try:
            ali_qr = qrcode.make(self.ALIPAY_PAY_URL).resize((180, 180), Image.LANCZOS)
            self._ali_photo = ImageTk.PhotoImage(ali_qr)
            tk.Label(ali_frame, image=self._ali_photo).pack()
        except Exception as e:
            tk.Label(ali_frame, text=f"支付宝二维码生成失败\n{str(e)[:30]}",
                    font=('微软雅黑', 9), fg='red').pack()

        # ===== 留言 / 捐赠记录 =====
        text_frame = tk.LabelFrame(tab, text=" 留言 / 捐赠记录 ", font=('微软雅黑', 11))
        text_frame.pack(pady=(5, 15), padx=20, fill=tk.BOTH, expand=False)
        text_frame.pack_propagate(False)
        text_frame.configure(height=280)

        txt_scroll = tk.Scrollbar(text_frame)
        txt_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.about_textbox = tk.Text(
            text_frame,
            height=10,
            font=('微软雅黑', 10),
            wrap=tk.WORD,
            yscrollcommand=txt_scroll.set,
            bg='#FAFAFA',
            relief='flat',
            padx=8,
            pady=5
        )
        self.about_textbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        txt_scroll.config(command=self.about_textbox.yview)

        self.about_textbox.insert(
            '1.0',
            "感谢以下用户的赞助支持，你们的支持将是我继续开发的重要动力："
        )
        self.about_textbox.config(state='disabled')

        # ===== 捐赠名单双源配置 =====
        GITHUB_DONORS_URL = "https://raw.githubusercontent.com/coralfox/smd_game_monitor/refs/heads/master/donors.json"
        GITEE_DONORS_URL = "https://raw.giteeusercontent.com/coralfox/smd_game_monitor/raw/master/donors.json"

        # 用字典保存 PhotoImage 引用，防止被 GC 回收
        self._donor_photos = []

        def get_circle_avatar(qq, size=32):
            """加载QQ头像（纯内存，不缓存到本地）"""
            url = f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s=100"
            resp = requests.get(url, timeout=8)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGBA")

            img = img.resize((size, size), Image.LANCZOS)

            # 圆形裁剪
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
            img.putalpha(mask)

            return ImageTk.PhotoImage(img)

        def insert_donor(photo, name, color):
            try:
                self.about_textbox.config(state='normal')
                self.about_textbox.insert(tk.END, "\n")

                if photo:
                    self.about_textbox.image_create(tk.END, image=photo)
                    self.about_textbox.insert(tk.END, " ")

                tag = f"donor_{name}"
                self.about_textbox.insert(tk.END, name, tag)
                self.about_textbox.tag_config(
                    tag,
                    foreground=color,
                    font=('微软雅黑', 10, 'bold')
                )
                self.about_textbox.config(state='disabled')
            except Exception as e:
                print(f"插入捐赠人失败: {e}")

        def _load_donors_source(url, name, result_holder, result_event):
            if result_event.is_set():
                return
            try:
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                donors = resp.json()
                if donors and not result_event.is_set():
                    result_holder['donors'] = donors
                    result_holder['source'] = name
                    result_event.set()
            except Exception:
                pass

        def _render_donors():
            result_event.wait(timeout=15)
            donors = result_holder.get('donors', [])
            if not donors:
                print("捐赠名单加载失败，双源均不可达")
                return

            for donor in donors:
                qq = str(donor.get("qq", "")).strip()
                name = donor.get("name", "").strip()
                color = donor.get("color", "#333")

                if not qq or not name:
                    continue

                try:
                    photo = get_circle_avatar(qq)
                except Exception as e:
                    print(f"头像加载失败 {qq}:", e)
                    photo = None

                # 保存引用，防止 GC
                self._donor_photos.append(photo)

                tab.after(0, insert_donor, photo, name, color)

        result_event = threading.Event()
        result_holder = {'donors': None, 'source': None}

        threading.Thread(target=_load_donors_source, args=(GITHUB_DONORS_URL, "GitHub", result_holder, result_event), daemon=True).start()
        threading.Thread(target=_load_donors_source, args=(GITEE_DONORS_URL, "Gitee", result_holder, result_event), daemon=True).start()
        threading.Thread(target=_render_donors, daemon=True).start()

    def _sync_checkbuttons(self):
        """同步Checkbutton的勾选状态到_level_enabled"""
        for name, var in self._log_level_checkbuttons.items():
            self._log_level_enabled[name] = (var.get() == 1)

    def _on_level_toggle(self):
        """单个级别勾选切换，重新过滤已显示的日志"""
        self._sync_checkbuttons()
        self._refilter_log()

    def _refilter_log(self):
        """根据当前级别过滤设置，清空并重新绘制可见日志"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete('1.0', tk.END)
        for display_msg, tag in self._log_entries:
            if tag and not self._log_level_enabled.get(tag, True):
                continue
            self.log_text.insert(tk.END, display_msg + '\n', tag if tag else ())
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _show_all_levels(self):
        """显示所有级别"""
        for name in self._log_level_enabled:
            self._log_level_enabled[name] = True
        for name, var in self._log_level_checkbuttons.items():
            var.set(1)
        self._refilter_log()

    def _build_control_bar(self):
        bar = tk.Frame(self.root, bg='#f0f0f0', relief=tk.RIDGE, bd=1)
        bar.pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=5)

        # 左侧：状态（fill占满，把右侧控件推到右边）
        left_frame = tk.Frame(bar, bg='#f0f0f0')
        left_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0), pady=5)

        self.status_var = tk.StringVar(value="就绪")
        tk.Label(left_frame, textvariable=self.status_var,
                 font=('微软雅黑', 11), bg='#f0f0f0', fg='#333').pack(side=tk.LEFT, padx=(5, 5))

        # 右侧：配置控件 + 控制按钮（紧挨着排列）
        right_frame = tk.Frame(bar, bg='#f0f0f0')
        right_frame.pack(side=tk.RIGHT, padx=(0, 5), pady=5)

        tk.Label(right_frame, text="配置文件:", font=('微软雅黑', 9), bg='#f0f0f0').pack(side=tk.LEFT, padx=(0, 2))
        self.config_combo = ttk.Combobox(right_frame, width=10, font=('微软雅黑', 9))
        self.config_combo.pack(side=tk.LEFT, padx=2)
        self.config_combo.bind('<<ComboboxSelected>>', self._on_config_selected)
        self._refresh_config_combo()

        tk.Button(right_frame, text="保存配置", command=self._save_config_from_ui,
                  width=6, font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(5, 0))

        tk.Button(right_frame, text="另存为", command=self._save_as_config,
                  width=6, font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(3, 0))

        tk.Button(right_frame, text="恢复默认", command=self._reset_to_defaults,
                  width=6, font=('微软雅黑', 9), fg='#E65100').pack(side=tk.LEFT, padx=(5, 10))

        self.start_btn = tk.Button(right_frame, text="开始监控", command=self._start_monitor,
                                   width=8, bg='#4CAF50', fg='white',
                                   font=('微软雅黑', 10, 'bold'))
        self.start_btn.pack(side=tk.LEFT, padx=3)

        self.stop_btn = tk.Button(right_frame, text="停止监控", command=self._stop_monitor,
                                  width=8, bg='#f44336', fg='white',
                                  font=('微软雅黑', 10), state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=3)

    def _load_config_to_ui(self):
        # 加载窗口设置
        window = self.config_data.get('window', {})
        saved_title = window.get('title', '')
        saved_hwnd = window.get('hwnd', 0)

        if saved_title:
            self.window_title_var.set(saved_title)
            # 尝试根据保存的hwnd或标题重新查找窗口
            if saved_hwnd:
                import ctypes
                import ctypes.wintypes
                # 验证hwnd是否仍然有效
                if ctypes.windll.user32.IsWindow(saved_hwnd):
                    rect = ctypes.wintypes.RECT()
                    ctypes.windll.user32.GetWindowRect(saved_hwnd, ctypes.byref(rect))
                    length = ctypes.windll.user32.GetWindowTextLengthW(saved_hwnd)
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(saved_hwnd, buffer, length + 1)
                    self.selected_window = {
                        'hwnd': saved_hwnd,
                        'title': buffer.value,
                        'left': rect.left, 'top': rect.top,
                        'width': rect.right - rect.left,
                        'height': rect.bottom - rect.top
                    }
                    self.window_status_var.set(
                        f"已恢复: {buffer.value[:40]} | ({rect.left},{rect.top}) {rect.right-rect.left}x{rect.bottom-rect.top}"
                    )
                else:
                    self.selected_window = None
                    self.window_status_var.set("窗口已关闭，请重新选择或点击\"根据标题查找窗口\"")
            else:
                self.selected_window = None
                self.window_status_var.set("已加载上次窗口标题，请点击\"根据标题查找窗口\"")
        else:
            self.window_title_var.set("")
            self.window_status_var.set("未选择窗口")

        # 加载区域设置
        region = self.config_data.get('monitor', {}).get('region', {})
        for key, var in self.region_vars.items():
            var.set(str(region.get(key, 0)))

        # 加载监控参数
        monitor = self.config_data.get('monitor', {})
        self.interval_var.set(str(monitor.get('check_interval', 0.5)))

        # 加载频率参数
        freq = self.config_data.get('frequency', {})
        for key, var in self.freq_vars.items():
            var.set(str(freq.get(key, var.get())))

        # 加载UI选项
        ui_opts = self.config_data.get('ui_options', {})
        self.always_on_top_var.set(ui_opts.get('always_on_top_game', False))
        self.show_floating_var.set(ui_opts.get('show_floating_stats', True))

        # 加载报警配置
        alert = self.config_data.get('alert', {})
        self.pushplus_enabled_var.set(alert.get('pushplus_enabled', False))
        self.pushplus_token_var.set(alert.get('pushplus_token', ''))
        self.email_enabled_var.set(alert.get('email_enabled', False))
        self.email_smtp_var.set(alert.get('email_smtp_server', 'smtp.qq.com'))
        self.email_port_var.set(str(alert.get('email_smtp_port', 465)))
        self.email_ssl_var.set(alert.get('email_use_ssl', True))
        self.email_user_var.set(alert.get('email_user', ''))
        self.email_pass_var.set(alert.get('email_password', ''))
        self.email_to_var.set(alert.get('email_to', ''))
        self.alert_cooldown_var.set(str(alert.get('alert_cooldown_minutes', 15)))
        self.imgbb_api_key_var.set(alert.get('imgbb_api_key', ''))
        self.imgbb_expiration_var.set(str(alert.get('imgbb_expiration_days', 7)))
        self.stats_report_enabled_var.set(alert.get('stats_report_enabled', False))
        self.stats_report_interval_var.set(str(alert.get('stats_report_interval', 60)))
        self.alert_trigger_threshold_var.set(str(alert.get('alert_trigger_threshold', 6)))
        self.alert_severity_threshold_var.set(str(alert.get('alert_severity_threshold', 10)))
        self._update_alert_detect_time()

        # 加载挂机设置
        idle = self.config_data.get('idle_settings', {})
        self.idle_enabled_var.set(idle.get('enabled', False))
        self.idle_minutes_var.set(str(idle.get('stop_after_minutes', 0)))
        self.idle_stop_hour_var.set('0')
        self.idle_stop_min_var.set('0')
        stop_at = idle.get('stop_at_time', '')
        if stop_at and ':' in stop_at:
            parts = stop_at.split(':')
            self.idle_stop_hour_var.set(parts[0])
            self.idle_stop_min_var.set(parts[1])
        self.idle_rounds_var.set(str(idle.get('stop_after_rounds', 0)))
        self.idle_execs_var.set(str(idle.get('stop_after_executions', 0)))

        # 加载自适应配置
        adaptive_cfg = self.config_data.get('adaptive', {})
        self.adaptive_enabled_var.set(adaptive_cfg.get('enabled', True))

        # 加载统计报告时间窗口
        srt = self.config_data.get('stats_report_time', {})
        self.srt_enabled_var.set(srt.get('enabled', False))
        start_t = srt.get('start_time', '00:00')
        end_t = srt.get('end_time', '24:00')
        if ':' in start_t:
            self.srt_start_hour_var.set(start_t.split(':')[0])
            self.srt_start_min_var.set(start_t.split(':')[1])
        if ':' in end_t:
            self.srt_end_hour_var.set(end_t.split(':')[0])
            self.srt_end_min_var.set(end_t.split(':')[1])

        # 加载重启原力配置
        rs = self.config_data.get('restart_settings', {})
        self.restart_enabled_var.set(rs.get('enabled', False))
        self.restart_bat_var.set(rs.get('bat_path', ''))
        self.restart_rundll32_title_var.set(rs.get('rundll32_title', '音乐盒子'))
        if hasattr(self, 'restart_game_title_var'):
            self.restart_game_title_var.set(rs.get('game_title', "Tom Clancy's The Division 2"))
        self.restart_play_text_var.set(rs.get('play_button_text', '播放'))
        self.restart_wait_text_var.set(rs.get('play_wait_text', '等待歌曲启动后点击'))
        self.restart_game_shortcut_var.set(rs.get('game_shortcut', ''))
        self.restart_cleanup_text_var.set(rs.get('cleanup_button_text', '清理歌曲播放'))
        self.restart_burst_var.set(str(rs.get('burst_trigger_count', 5)))
        self.restart_cooldown_trigger_var.set(str(rs.get('cooldown_trigger_threshold', 10)))

        # 加载热键配置
        hotkeys = self.config_data.get('hotkeys', {})
        self.hotkey_start_var.set(hotkeys.get('start_stop', 'F8'))
        self.hotkey_pause_var.set(hotkeys.get('pause_resume', 'F10'))

        # 加载策略列表
        self._refresh_strategy_list()

    def _refresh_strategy_list(self):
        for item in self.strategy_tree.get_children():
            self.strategy_tree.delete(item)

        # 卡脚本类型中文映射
        stuck_type_map = {'any': '任意', 'single': '单一卡死', 'alternating': '交替卡死'}

        strategies = self.config_data.get('strategies', {})
        for key, strategy in strategies.items():
            stuck_type = strategy.get('match_stuck_type', 'any')
            stuck_type_cn = stuck_type_map.get(stuck_type, stuck_type)
            self.strategy_tree.insert('', tk.END, values=(
                key,
                strategy.get('name', ''),
                stuck_type_cn,
                ', '.join(strategy.get('match_ids', [])) or '所有',
                ', '.join(strategy.get('exclude_ids', [])) or '-',
                len(strategy.get('actions', []))
            ))

    def _auto_save(self):
        """自动保存配置（静默保存，不弹窗提示）"""
        try:
            title = self.window_title_var.get().strip()
            if self.selected_window and self.selected_window.get('hwnd'):
                self.config_data['window'] = {
                    'title': self.selected_window.get('title', title),
                    'hwnd': self.selected_window.get('hwnd', 0),
                    'class_name': '',
                    'use_window': True
                }
            elif title:
                self.config_data['window'] = {
                    'title': title,
                    'hwnd': 0,
                    'class_name': '',
                    'use_window': True
                }
            else:
                self.config_data['window'] = {'title': '', 'hwnd': 0, 'class_name': '', 'use_window': False}

            # 保存区域设置
            self.config_data['monitor']['region'] = {
                'left': int(self.region_vars['left'].get() or 0),
                'top': int(self.region_vars['top'].get() or 0),
                'width': int(self.region_vars['width'].get() or 0),
                'height': int(self.region_vars['height'].get() or 0)
            }
            self.config_data['monitor']['check_interval'] = float(self.interval_var.get() or 0.5)
            # 移除已废弃的 extract_pattern 配置
            if 'extract_pattern' in self.config_data['monitor']:
                del self.config_data['monitor']['extract_pattern']

            # 保存频率参数（只保留通用配置，阈值在各策略中独立配置）
            self.config_data['frequency'] = {
                'window_seconds': int(self.freq_vars['window_seconds'].get()),
                'min_samples': int(self.freq_vars['min_samples'].get()),
                'cooldown_seconds': int(self.freq_vars['cooldown_seconds'].get())
            }

            # 保存UI选项
            self.config_data['ui_options'] = {
                'always_on_top_game': self.always_on_top_var.get(),
                'show_floating_stats': self.show_floating_var.get()
            }

            # 保存报警配置
            try:
                smtp_port = int(self.email_port_var.get() or 465)
            except ValueError:
                smtp_port = 465
            self.config_data['alert'] = {
                'pushplus_enabled': self.pushplus_enabled_var.get(),
                'pushplus_token': self.pushplus_token_var.get().strip(),
                'email_enabled': self.email_enabled_var.get(),
                'email_smtp_server': self.email_smtp_var.get().strip(),
                'email_smtp_port': smtp_port,
                'email_use_ssl': self.email_ssl_var.get(),
                'email_user': self.email_user_var.get().strip(),
                'email_password': self.email_pass_var.get().strip(),
                'email_to': self.email_to_var.get().strip(),
                'alert_cooldown_minutes': int(self.alert_cooldown_var.get() or 15),
                'alert_trigger_threshold': int(self.alert_trigger_threshold_var.get() or 6),
                'alert_severity_threshold': int(self.alert_severity_threshold_var.get() or 10),
                'imgbb_api_key': self.imgbb_api_key_var.get().strip(),
                'imgbb_expiration_days': int(self.imgbb_expiration_var.get() or 7),
                'stats_report_enabled': self.stats_report_enabled_var.get(),
                'stats_report_interval': int(self.stats_report_interval_var.get() or 60)
            }

            # 保存热键、挂机设置、统计报告时间窗口
            self.config_data['hotkeys'] = {
                'start_stop': self.hotkey_start_var.get().strip() or 'F8',
                'pause_resume': self.hotkey_pause_var.get().strip() or 'F10'
            }
            try:
                idle_minutes = int(self.idle_minutes_var.get() or 0)
            except ValueError:
                idle_minutes = 0
            try:
                idle_rounds = int(self.idle_rounds_var.get() or 0)
            except ValueError:
                idle_rounds = 0
            try:
                idle_execs = int(self.idle_execs_var.get() or 0)
            except ValueError:
                idle_execs = 0
            self.config_data['idle_settings'] = {
                'enabled': self.idle_enabled_var.get(),
                'stop_after_minutes': idle_minutes,
                'stop_at_time': f"{self.idle_stop_hour_var.get().strip()}:{self.idle_stop_min_var.get().strip()}",
                'stop_after_rounds': idle_rounds,
                'stop_after_executions': idle_execs
            }
            self.config_data['adaptive'] = {
                'enabled': self.adaptive_enabled_var.get()
            }
            self.config_data['stats_report_time'] = {
                'enabled': self.srt_enabled_var.get(),
                'start_time': f"{self.srt_start_hour_var.get().strip()}:{self.srt_start_min_var.get().strip()}",
                'end_time': f"{self.srt_end_hour_var.get().strip()}:{self.srt_end_min_var.get().strip()}"
            }

            self._save_config()
        except Exception as e:
            self._log(f"[自动保存失败: {e}]")

    def _test_pushplus(self):
        """测试 PushPlus 发送"""
        token = self.pushplus_token_var.get().strip()
        if not token:
            messagebox.showwarning("提示", "请先填写 PushPlus Token")
            return
        import json
        import urllib.request
        try:
            url = 'http://www.pushplus.plus/send'
            data = json.dumps({
                'token': token,
                'title': '游戏监控-测试消息',
                'content': '这是一条测试消息，如果您收到说明 PushPlus 配置正确。'
            }).encode('utf-8')
            req = urllib.request.Request(url, data=data,
                                          headers={'Content-Type': 'application/json'},
                                          method='POST')
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = resp.read().decode('utf-8')
                self._log(f"[测试-PushPlus] 发送成功: {result}")
                messagebox.showinfo("成功", "PushPlus 测试消息已发送，请检查微信/推送")
        except Exception as e:
            self._log(f"[测试-PushPlus] 发送失败: {e}")
            messagebox.showerror("失败", f"PushPlus 测试发送失败:\n{e}")

    def _test_email(self):
        """测试邮件发送"""
        smtp_server = self.email_smtp_var.get().strip()
        user = self.email_user_var.get().strip()
        password = self.email_pass_var.get().strip()
        to_addr = self.email_to_var.get().strip()
        if not all([smtp_server, user, password, to_addr]):
            messagebox.showwarning("提示", "请完整填写邮件配置信息")
            return
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.header import Header
            smtp_port = int(self.email_port_var.get() or 465)
            use_ssl = self.email_ssl_var.get()
            msg = MIMEText('这是一条测试邮件，如果您收到说明邮件配置正确。', 'plain', 'utf-8')
            msg['Subject'] = Header('游戏监控-测试邮件', 'utf-8')
            msg['From'] = user
            msg['To'] = to_addr
            if use_ssl:
                with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10) as server:
                    server.login(user, password)
                    server.sendmail(user, [to_addr], msg.as_string())
            else:
                with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
                    server.starttls()
                    server.login(user, password)
                    server.sendmail(user, [to_addr], msg.as_string())
            self._log(f"[测试-邮件] 发送成功 -> {to_addr}")
            messagebox.showinfo("成功", f"测试邮件已发送至 {to_addr}")
        except Exception as e:
            self._log(f"[测试-邮件] 发送失败: {e}")
            messagebox.showerror("失败", f"邮件测试发送失败:\n{e}")

    def _save_ui_to_config(self):
        """将UI中的配置保存到config_data（不弹窗）"""
        # 保存窗口设置（保存完整信息包括hwnd）
        title = self.window_title_var.get().strip()
        if self.selected_window and self.selected_window.get('hwnd'):
            self.config_data['window'] = {
                'title': self.selected_window.get('title', title),
                'hwnd': self.selected_window.get('hwnd', 0),
                'class_name': '',
                'use_window': True
            }
        elif title:
            self.config_data['window'] = {
                'title': title,
                'hwnd': 0,
                'class_name': '',
                'use_window': True
            }
        else:
            self.config_data['window'] = {'title': '', 'hwnd': 0, 'class_name': '', 'use_window': False}

        # 保存区域设置
        self.config_data['monitor']['region'] = {
            'left': int(self.region_vars['left'].get() or 0),
            'top': int(self.region_vars['top'].get() or 0),
            'width': int(self.region_vars['width'].get() or 0),
            'height': int(self.region_vars['height'].get() or 0)
        }
        self.config_data['monitor']['check_interval'] = float(self.interval_var.get() or 0.5)
        if 'extract_pattern' in self.config_data['monitor']:
            del self.config_data['monitor']['extract_pattern']
        for key in ['ocr_language', 'ocr_config']:
            self.config_data['monitor'].pop(key, None)

        # 保存频率参数
        self.config_data['frequency'] = {
            'window_seconds': int(self.freq_vars['window_seconds'].get()),
            'min_samples': int(self.freq_vars['min_samples'].get()),
            'cooldown_seconds': int(self.freq_vars['cooldown_seconds'].get())
        }

        # 保存UI选项
        self.config_data['ui_options'] = {
            'always_on_top_game': self.always_on_top_var.get(),
            'show_floating_stats': self.show_floating_var.get()
        }

        # 保存报警配置
        try:
            smtp_port = int(self.email_port_var.get() or 465)
        except ValueError:
            smtp_port = 465
        self.config_data['alert'] = {
            'pushplus_enabled': self.pushplus_enabled_var.get(),
            'pushplus_token': self.pushplus_token_var.get().strip(),
            'email_enabled': self.email_enabled_var.get(),
            'email_smtp_server': self.email_smtp_var.get().strip(),
            'email_smtp_port': smtp_port,
            'email_use_ssl': self.email_ssl_var.get(),
            'email_user': self.email_user_var.get().strip(),
            'email_password': self.email_pass_var.get().strip(),
            'email_to': self.email_to_var.get().strip(),
            'alert_cooldown_minutes': int(self.alert_cooldown_var.get() or 15),
            'alert_trigger_threshold': int(self.alert_trigger_threshold_var.get() or 6),
            'alert_severity_threshold': int(self.alert_severity_threshold_var.get() or 10),
            'imgbb_api_key': self.imgbb_api_key_var.get().strip(),
            'imgbb_expiration_days': int(self.imgbb_expiration_var.get() or 7),
            'stats_report_enabled': self.stats_report_enabled_var.get(),
            'stats_report_interval': int(self.stats_report_interval_var.get() or 60)
        }

        # 保存重启原力配置
        self.config_data['restart_settings'] = {
            'enabled': self.restart_enabled_var.get(),
            'bat_path': self.restart_bat_var.get().strip(),
            'rundll32_title': self.restart_rundll32_title_var.get().strip(),
            'game_title': self.restart_game_title_var.get().strip() if hasattr(self, 'restart_game_title_var') else '',
            'play_button_text': self.restart_play_text_var.get().strip(),
            'play_wait_text': self.restart_wait_text_var.get().strip(),
            'game_shortcut': self.restart_game_shortcut_var.get().strip(),
            'cleanup_button_text': self.restart_cleanup_text_var.get().strip(),
            'burst_trigger_count': int(self.restart_burst_var.get() or 5),
            'cooldown_trigger_threshold': int(self.restart_cooldown_trigger_var.get() or 10)
        }

        # 保存热键配置
        self.config_data['hotkeys'] = {
            'start_stop': self.hotkey_start_var.get().strip() or 'F8',
            'pause_resume': self.hotkey_pause_var.get().strip() or 'F10'
        }

        # 保存挂机设置
        try:
            idle_minutes = int(self.idle_minutes_var.get() or 0)
        except ValueError:
            idle_minutes = 0
        try:
            idle_rounds = int(self.idle_rounds_var.get() or 0)
        except ValueError:
            idle_rounds = 0
        try:
            idle_execs = int(self.idle_execs_var.get() or 0)
        except ValueError:
            idle_execs = 0
        self.config_data['idle_settings'] = {
            'enabled': self.idle_enabled_var.get(),
            'stop_after_minutes': idle_minutes,
            'stop_at_time': f"{self.idle_stop_hour_var.get().strip()}:{self.idle_stop_min_var.get().strip()}",
            'stop_after_rounds': idle_rounds,
            'stop_after_executions': idle_execs
        }
        # 保存自适应配置
        self.config_data['adaptive'] = {
            'enabled': self.adaptive_enabled_var.get()
        }

        # 保存统计报告时间窗口
        self.config_data['stats_report_time'] = {
            'enabled': self.srt_enabled_var.get(),
            'start_time': f"{self.srt_start_hour_var.get().strip()}:{self.srt_start_min_var.get().strip()}",
            'end_time': f"{self.srt_end_hour_var.get().strip()}:{self.srt_end_min_var.get().strip()}"
        }

        self._save_config()

    def _save_config_from_ui(self):
        """保存配置并弹窗提示（用于手动保存按钮）"""
        self._save_ui_to_config()
        # 如果没有配置文件，自动另存为
        if not self.config_path:
            self._save_as_config()
            return
        self._save_config()
        self._save_last_config()
        self._refresh_config_combo()
        display_name = self.config_filename[:-5] if self.config_filename.endswith('.json') else self.config_filename
        messagebox.showinfo("成功", f"配置已保存到 {display_name}")

    def _on_config_selected(self, event=None):
        """下拉框切换配置文件（显示名不含.json，实际文件名加.json）"""
        if self.monitor_running:
            messagebox.showwarning("提示", "监控运行中无法切换配置文件")
            display_name = self.config_filename[:-5] if self.config_filename.endswith('.json') else self.config_filename
            self.config_combo.set(display_name)
            return
        display_name = self.config_combo.get().strip()
        if not display_name:
            return
        name = display_name + '.json'
        path = os.path.join(self.configs_dir, name)
        if os.path.exists(path):
            self.config_path = path
            self.config_filename = name
            self.config_data = self._load_config()
            self._load_config_to_ui()
            self._update_alert_detect_time()
            self._save_last_config()
            self._log(f"[配置] 已切换到 {display_name}")

    def _save_as_config(self):
        """另存为新的配置文件（显示名不含.json，自动补全.json后缀）"""
        if self.monitor_running:
            messagebox.showwarning("提示", "监控运行中无法另存配置")
            return
        # 弹出输入框（默认显示名不含.json）
        from tkinter import simpledialog
        default_display = self.config_filename[:-5] if self.config_filename.endswith('.json') else (self.config_filename or 'my_config')
        display_name = simpledialog.askstring("另存为配置", "请输入配置文件名:", initialvalue=default_display)
        if not display_name:
            return
        name = display_name + '.json'
        # 保存
        self._save_ui_to_config()
        self.config_path = os.path.join(self.configs_dir, name)
        self.config_filename = name
        self._save_config()
        self._save_last_config()
        self._refresh_config_combo()
        self._log(f"[配置] 已另存为 {display_name}")
        messagebox.showinfo("成功", f"配置已保存到 {display_name}")

    def _reset_to_defaults(self):
        """恢复默认配置：加载default.json（不写入文件）"""
        if self.monitor_running:
            messagebox.showwarning("提示", "监控运行中无法恢复默认配置")
            return
        if not messagebox.askyesno("确认", "确定要将所有配置恢复为默认值吗？"):
            return

        # 加载default.json作为默认配置
        default_path = os.path.join(self.configs_dir, 'default.json')
        if os.path.exists(default_path):
            with open(default_path, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
            self._log("[配置] 已从 default.json 恢复默认值")
        else:
            # 如果default.json不存在，回退到硬编码默认
            self.config_data = self._default_config()
            self._log("[配置] 已从硬编码默认值恢复")

        # 清除当前配置文件路径
        self.config_path = None
        self.config_filename = ''

        # 刷新UI
        self._load_config_to_ui()
        self._update_alert_detect_time()
        self._refresh_config_combo()
        messagebox.showinfo("成功", "配置已恢复为默认值（未保存到文件）")

    def _open_link(self, url: str):
        """用默认浏览器打开链接"""
        import webbrowser
        webbrowser.open(url)

    def _get_game_hwnd(self):
        """获取游戏窗口的有效hwnd，返回0表示无效"""
        import ctypes
        hwnd = 0
        if self.selected_window:
            hwnd = self.selected_window.get('hwnd', 0)
        if not hwnd:
            hwnd = self.config_data.get('window', {}).get('hwnd', 0)
        if hwnd and ctypes.windll.user32.IsWindow(hwnd):
            return hwnd
        return 0

    def _activate_game_window(self):
        """激活游戏窗口并前显（与ActionExecutor._activate_window一致的可靠方法）"""
        import ctypes
        hwnd = self._get_game_hwnd()
        if not hwnd:
            return
        try:
            # 如果窗口已在前台，跳过
            fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
            if fg_hwnd == hwnd:
                return

            curr_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            target_thread = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)

            # 附加线程输入（确保 SetForegroundWindow 能成功）
            ctypes.windll.user32.AttachThreadInput(target_thread, curr_thread, True)

            # 如果窗口最小化，先恢复
            SW_RESTORE = 9
            if ctypes.windll.user32.IsIconic(hwnd):
                ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)

            # 设置前台窗口
            ctypes.windll.user32.SetForegroundWindow(hwnd)

            # 分离线程输入
            ctypes.windll.user32.AttachThreadInput(target_thread, curr_thread, False)
        except Exception as e:
            logging.debug(f"[置顶] 激活窗口失败: {e}")

    def _topmost_tick(self):
        """定时激活游戏窗口的回调"""
        if not self.monitor_running:
            self._topmost_timer_id = None
            return
        self._activate_game_window()
        self._topmost_timer_id = self.root.after(30000, self._topmost_tick)

    def _update_alert_detect_time(self):
        """根据触发冷却和严重度阈值计算报警检测时间"""
        try:
            cooldown = int(self.freq_vars['cooldown_seconds'].get() or 30)
            severity = int(self.alert_severity_threshold_var.get() or 10)
            detect_seconds = cooldown * severity * 2
            if detect_seconds >= 60:
                self.alert_detect_time_var.set(f"{detect_seconds // 60}分{detect_seconds % 60}秒 ({detect_seconds}秒)")
            else:
                self.alert_detect_time_var.set(f"{detect_seconds}秒")
        except (ValueError, tk.TclError):
            self.alert_detect_time_var.set("计算中...")

    def _toggle_floating(self):
        """勾选/取消勾选时切换悬浮窗口显示"""
        if self.show_floating_var.get():
            self.floating_window.show()
            self._log("[设置] 悬浮窗口已显示")
        else:
            self.floating_window.hide()
            self._log("[设置] 悬浮窗口已隐藏")

    def _check_update(self):
        """双源异步竞速检测更新，GitHub/Gitee 谁快用谁"""
        self.update_status_var.set("正在检测更新...")
        import threading
        import urllib.request

        result_event = threading.Event()
        result_holder = {'latest': None, 'source': None, 'done': False}

        def _check_source(url, name):
            if result_event.is_set():
                return
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    latest = resp.read().decode('utf-8').strip()
                if latest and not result_event.is_set():
                    result_holder['latest'] = latest
                    result_holder['source'] = name
                    result_event.set()
            except Exception:
                pass

        def _on_result():
            result_event.wait(timeout=15)
            latest = result_holder.get('latest')
            if latest and latest != self.VERSION:
                src = result_holder.get('source', 'unknown')
                msg = f"发现新版本 {latest} (来自 {src})"
                self.root.title(
                    f"SMD游戏监控程序 v{self.VERSION} - 作者:{self.AUTHOR}  [有新版本 {latest}]"
                )
                self.update_status_var.set(msg)
                self._log(f"[更新] {msg}")
            elif latest:
                msg = f"当前已是最新版本 v{self.VERSION}"
                self.update_status_var.set(msg)
                self._log(f"[更新] {msg}")
            else:
                msg = "检测更新失败，双源均不可达"
                self.update_status_var.set(msg)
                self._log(f"[更新] {msg}")

        threading.Thread(target=_check_source, args=(self.UPDATE_URL, "GitHub"), daemon=True).start()
        threading.Thread(target=_check_source, args=(self.GITEE_UPDATE_URL, "Gitee"), daemon=True).start()
        threading.Thread(target=_on_result, daemon=True).start()

    # ===== 窗口选择功能 =====
    def _select_window(self):
        def on_select(win):
            self.selected_window = win
            self.window_title_var.set(win['title'])
            self.window_status_var.set(
                f"已选择: {win['title'][:40]} | 位置: ({win['left']}, {win['top']}) | "
                f"大小: {win['width']}x{win['height']}"
            )
            self._log(f"选择窗口: {win['title']} ({win['width']}x{win['height']})")
            self._auto_save()
        WindowSelectorDialog(self.root, on_select)

    def _use_mouse_window(self):
        """使用鼠标当前位置下的窗口"""
        import ctypes
        import ctypes.wintypes

        x, y = pyautogui.position()
        hwnd = ctypes.windll.user32.WindowFromPoint(ctypes.wintypes.POINT(x, y))
        if hwnd:
            root = ctypes.windll.user32.GetAncestor(hwnd, 2)
            if root:
                hwnd = root
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)

            self.selected_window = {
                'hwnd': hwnd,
                'title': buffer.value,
                'left': rect.left,
                'top': rect.top,
                'width': rect.right - rect.left,
                'height': rect.bottom - rect.top
            }
            self.window_title_var.set(buffer.value)
            self.window_status_var.set(
                f"已选择: {buffer.value[:40]} | 位置: ({rect.left}, {rect.top}) | "
                f"大小: {rect.right - rect.left}x{rect.bottom - rect.top}"
            )
            self._log(f"选择窗口(鼠标): {buffer.value}")
            self._auto_save()
        else:
            messagebox.showwarning("提示", "未找到鼠标下的窗口")

    def _find_window_by_title(self):
        """根据输入框中的标题查找窗口"""
        title = self.window_title_var.get().strip()
        if not title:
            messagebox.showwarning("提示", "请先输入窗口标题")
            return

        import ctypes
        import ctypes.wintypes

        # 遍历所有窗口查找匹配的标题
        found = None
        windows = get_window_list()
        for win in windows:
            if title.lower() in win['title'].lower() or win['title'].lower() in title.lower():
                found = win
                break

        if found:
            self.selected_window = found
            self.window_title_var.set(found['title'])
            self.window_status_var.set(
                f"已找到: {found['title'][:40]} | 位置: ({found['left']}, {found['top']}) | "
                f"大小: {found['width']}x{found['height']}"
            )
            self._log(f"查找窗口: {found['title']} ({found['width']}x{found['height']})")
            self._auto_save()
            messagebox.showinfo("成功", f"找到窗口: {found['title']}")
        else:
            self.selected_window = None
            self.window_status_var.set(f"未找到匹配窗口: {title}")
            messagebox.showwarning("提示", f"未找到包含 '{title}' 的窗口\n请确认游戏已运行，或直接使用\"选择窗口\"按钮")

    def _clear_window(self):
        self.selected_window = None
        self.window_title_var.set("")
        self.window_status_var.set("未选择窗口 (使用屏幕绝对坐标)")
        self._log("清除窗口选择，使用屏幕绝对坐标")

    # ===== 区域选择功能 =====
    def _select_region_on_window(self):
        """在游戏窗口上选择相对区域"""
        if not self.selected_window:
            messagebox.showwarning("提示", "请先选择游戏窗口")
            return

        def on_select(x, y, w, h):
            self.region_vars['left'].set(str(x))
            self.region_vars['top'].set(str(y))
            self.region_vars['width'].set(str(w))
            self.region_vars['height'].set(str(h))
            self._log(f"选择相对区域: ({x}, {y}) 大小: {w}x{h}")
            self._auto_save()

        win = self.selected_window
        RegionSelector(on_select, window_rect=(win['left'], win['top'], win['width'], win['height'])).start()

    def _select_region_screen(self):
        """在屏幕上选择绝对区域"""
        def on_select(x, y, w, h):
            self.region_vars['left'].set(str(x))
            self.region_vars['top'].set(str(y))
            self.region_vars['width'].set(str(w))
            self.region_vars['height'].set(str(h))
            self._log(f"选择绝对区域: ({x}, {y}) 大小: {w}x{h}")
            self._auto_save()
        RegionSelector(on_select).start()

    def _test_capture(self):
        try:
            x = int(self.region_vars['left'].get())
            y = int(self.region_vars['top'].get())
            w = int(self.region_vars['width'].get())
            h = int(self.region_vars['height'].get())

            if self.selected_window and self.selected_window.get('hwnd'):
                # 先激活游戏窗口再截图
                self._activate_game_window()
                img = capture_window_region(self.selected_window['hwnd'], x, y, w, h)
                self._log(f"窗口内截图: ({x}, {y}) 大小: {w}x{h}")
            else:
                img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
                self._log(f"屏幕截图: ({x}, {y}) 大小: {w}x{h}")

            # 缩放显示
            display_w = min(400, w * 2)
            display_h = int(h * display_w / w)
            display_img = img.resize((display_w, display_h), Image.LANCZOS)

            photo = ImageTk.PhotoImage(display_img)
            self.preview_label.config(image=photo, text='')
            self.preview_label.image = photo

        except Exception as e:
            messagebox.showerror("错误", f"截图失败: {e}")

    def _test_ocr(self):
        try:
            x = int(self.region_vars['left'].get())
            y = int(self.region_vars['top'].get())
            w = int(self.region_vars['width'].get())
            h = int(self.region_vars['height'].get())

            if self.selected_window and self.selected_window.get('hwnd'):
                # 先激活游戏窗口再截图
                self._activate_game_window()
                img = capture_window_region(self.selected_window['hwnd'], x, y, w, h)
            else:
                img = ImageGrab.grab(bbox=(x, y, x + w, y + h))

            # 使用RapidOCR识别
            ocr = get_rapidocr()
            img_array = np.array(img.convert('RGB'))
            result, _ = ocr(img_array)

            all_text = ""
            lines = []
            if result:
                for item in result:
                    if len(item) >= 3:
                        text = item[1]
                        try:
                            confidence = float(item[2])
                        except (ValueError, TypeError):
                            confidence = 1.0
                    elif len(item) == 2:
                        text = item[1]
                        confidence = 1.0
                    else:
                        continue
                    if text and confidence > 0.3:
                        lines.append(text.strip())
                all_text = '\n'.join(lines)

            # 显示结果
            main_line = ""
            for line in lines:
                if '当前事件' in line or '事件' in line:
                    main_line = line
                    break
                if re.search(r'当前[^\s]+', line):
                    main_line = line
                    break
            if not main_line and lines:
                main_line = lines[0]

            result_str = f"OCR: [{main_line}]"

            # 显示策略关键词匹配
            keywords = []
            strategies = self.config_data.get('strategies', {})
            for key, strategy in strategies.items():
                for kw in strategy.get('match_ids', []):
                    if kw and kw not in keywords:
                        keywords.append(kw)
            matched_lines = [line for line in lines if any(kw in line for kw in keywords)]
            if matched_lines:
                result_str += f"\n关键词匹配: {', '.join(matched_lines[:3])}"

            self.ocr_result_var.set(result_str)
            self._log(f"RapidOCR完整结果:\n{all_text}")
            self._log(f"RapidOCR识别: {result_str}")
        except Exception as e:
            messagebox.showerror("错误", f"OCR失败: {e}")

    def _add_strategy(self):
        def on_save(key, strategy):
            self.config_data['strategies'][key] = strategy
            self._refresh_strategy_list()
            self._save_config()
        StrategyEditorDialog(self.root, callback=on_save)

    def _edit_strategy(self):
        sel = self.strategy_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个策略")
            return

        item = self.strategy_tree.item(sel[0])
        key = item['values'][0]
        strategy = self.config_data['strategies'].get(key, {})

        def on_save(new_key, new_strategy):
            if new_key != key and new_key in self.config_data['strategies']:
                if not messagebox.askyesno("确认", f"策略ID '{new_key}' 已存在，是否覆盖?"):
                    return
            if new_key != key:
                del self.config_data['strategies'][key]
            self.config_data['strategies'][new_key] = new_strategy
            self._refresh_strategy_list()
            self._save_config()

        StrategyEditorDialog(self.root, strategy_key=key, strategy=strategy, callback=on_save)

    def _delete_strategy(self):
        sel = self.strategy_tree.selection()
        if not sel:
            return

        item = self.strategy_tree.item(sel[0])
        key = item['values'][0]

        if messagebox.askyesno("确认", f"确定删除策略 '{key}'?"):
            del self.config_data['strategies'][key]
            self._refresh_strategy_list()
            self._save_config()

    def _start_monitor(self):
        self._save_ui_to_config()

        # 如果没有配置文件，自动另存为一个新文件
        if not self.config_path:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            name = f"auto_{timestamp}.json"
            self.config_path = os.path.join(self.configs_dir, name)
            self.config_filename = name
            self._save_config()
            self._refresh_config_combo()

        self._save_last_config()
        self.monitor_running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("监控运行中...")
        self._log("[启动] 监控已启动")

        # 开始监控时先激活一次游戏窗口
        self._activate_game_window()

        # 根据配置启动游戏窗口置顶定时器
        self._topmost_timer_id = None
        if self.always_on_top_var.get():
            self._topmost_timer_id = self.root.after(30000, self._topmost_tick)
            self._log("[启动] 游戏窗口定时激活已启用")

        # 监控启动时根据开关决定是否显示悬浮统计窗口
        if self.show_floating_var.get():
            self.floating_window.show()

        self.monitor_thread = threading.Thread(target=self._monitor_worker, daemon=True)
        self.monitor_thread.start()

    def _stop_monitor(self, emergency=False):
        # 先立即停止监控循环（线程安全，可在任意线程调用）
        if self.game_monitor:
            self.game_monitor.stop()
        # Tk操作放到主线程
        self.root.after(0, lambda: self._stop_monitor_ui(emergency))

    def _stop_monitor_ui(self, emergency=False):
        """更新停止后的UI状态（必须在主线程调用）"""
        try:
            self.monitor_running = False
            # game_monitor.stop() 已在外层调用

            # 取消游戏窗口置顶定时器
            if self._topmost_timer_id is not None:
                self.root.after_cancel(self._topmost_timer_id)
                self._topmost_timer_id = None
                self._log("[停止] 游戏窗口定时激活已取消")

            # 关闭悬浮统计窗口
            self.floating_window.hide()

            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            if emergency:
                self.status_var.set("监控已停止 - 脚本完全卡死，已发送P键")
                messagebox.showwarning("紧急停止", "检测到脚本完全卡死！\n已发送P键停止脚本，监控已自动停止。\n请检查游戏状态后手动处理。")
            else:
                self.status_var.set("监控已停止")
        except Exception as e:
            import traceback
            err = f"[停止] _stop_monitor 异常: {e}\n{traceback.format_exc()}"
            logging.error(err)
            # 强制恢复按钮状态
            try:
                self.start_btn.config(state=tk.NORMAL)
                self.stop_btn.config(state=tk.DISABLED)
                self.floating_window.hide()
            except:
                pass

    def _capture_hotkey(self, target):
        """捕捉用户按下的快捷键（后台线程捕获，不阻塞GUI）"""
        import keyboard
        import threading
        import time

        btn_map = {
            'start': (self.hotkey_start_label, self.hotkey_start_var, '开始/停止'),
            'pause': (self.hotkey_pause_label, self.hotkey_pause_var, '暂停/恢复')
        }
        label, var, name = btn_map[target]
        original_key = var.get()

        # 显示等待状态
        label.config(text='按任意键...', fg='#e74c3c')
        self.root.update()

        # 临时移除全局热键，避免按键冲突
        keyboard.clear_all_hotkeys()

        captured = {'key': None}

        def on_key(event):
            if captured['key'] is not None:
                return
            captured['key'] = event.name
            return False

        handler = keyboard.hook(on_key)

        def _wait_and_finish():
            deadline = time.time() + 5.0
            while captured['key'] is None and time.time() < deadline:
                time.sleep(0.05)
            keyboard.unhook(handler)
            # 无论超时还是捕获到，都在主线程中处理结果
            self.root.after(0, lambda: self._finish_capture(target, captured['key'], original_key))

        threading.Thread(target=_wait_and_finish, daemon=True).start()

    def _finish_capture(self, target, captured_key, original_key):
        """在捕捉到按键或超时后更新UI并重新注册热键"""
        btn_map = {
            'start': (self.hotkey_start_label, self.hotkey_start_var, '开始/停止'),
            'pause': (self.hotkey_pause_label, self.hotkey_pause_var, '暂停/恢复')
        }
        label, var, name = btn_map[target]

        if captured_key is None:
            # 超时
            var.set(original_key)
            label.config(text=original_key, fg='#1565C0')
            self._log(f"[热键] {name} 设置超时，已恢复")
        elif captured_key == 'esc':
            # ESC取消
            var.set(original_key)
            label.config(text=original_key, fg='#1565C0')
            self._log(f"[热键] {name} 已取消")
        else:
            key = captured_key
            if len(key) == 1 and key.isalpha():
                key = key.lower()
            var.set(key)
            label.config(text=key, fg='#1565C0')
            self._log(f"[热键] {name} 快捷键已设为: {key}")

        # 重新注册全局热键
        self._setup_hotkeys()

    def _setup_hotkeys(self):
        """注册全局热键"""
        try:
            import keyboard
            hotkeys = self.config_data.get('hotkeys', {})
            start_key = hotkeys.get('start_stop', 'F8')
            pause_key = hotkeys.get('pause_resume', 'F10')
            keyboard.add_hotkey(start_key, self._toggle_monitor)
            keyboard.add_hotkey(pause_key, self._toggle_pause)
            self._log(f"[热键] 全局热键已注册: {start_key}=开始/停止 {pause_key}=暂停/恢复")
        except Exception as e:
            self._log(f"[热键] 注册失败: {e}")

    def _toggle_monitor(self):
        """热键: 开始/停止监控（直接调用，不通过root.after，避免主线程阻塞时无法响应）"""
        try:
            if not self.monitor_running:
                self._start_monitor()
            else:
                self._stop_monitor()
        except Exception as e:
            logging.error(f"[热键] toggle_monitor异常: {e}")

    def _toggle_pause(self):
        """热键: 暂停/恢复监控（直接调用）"""
        if not self.monitor_running or not self.game_monitor:
            return
        try:
            if not self.game_monitor.paused:
                self._pause_monitor()
            else:
                self._resume_monitor()
        except Exception as e:
            logging.error(f"[热键] toggle_pause异常: {e}")

    def _pause_monitor(self):
        """暂停监控"""
        if self.game_monitor:
            self.game_monitor.pause()
            self.status_var.set("监控已暂停")
            self._log("[热键] 监控已暂停")

    def _resume_monitor(self):
        """恢复监控"""
        if self.game_monitor:
            self.game_monitor.resume()
            self.status_var.set("监控运行中")
            self._log("[热键] 监控已恢复")

    def _exit_app(self):
        """热键: 退出程序"""
        self.root.after(0, self.root.destroy)

    def _monitor_worker(self):
        try:
            self.game_monitor = GameMonitor(self.config_path)
            self.game_monitor.tk_root = self.root
            self._setup_gui_logging()
            self.game_monitor.start()
            # 监控正常结束后，检查是否因紧急停止退出
            if self.game_monitor and self.game_monitor.strategy_engine.emergency_stop_triggered:
                self.root.after(0, lambda: self._stop_monitor(emergency=True))
                return
        except Exception as e:
            import traceback
            error_msg = f"监控异常: {e}\n{traceback.format_exc()}"
            try:
                log_path = os.path.join(os.path.dirname(self.config_path), 'monitor_error.txt')
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {error_msg}\n{'='*40}\n")
            except:
                pass
            self._log(error_msg)
        self.root.after(0, self._stop_monitor)

    def _setup_gui_logging(self):
        import logging

        # 避免重复添加GUI handler
        root = logging.getLogger()
        for h in root.handlers:
            if isinstance(h, logging.Handler) and getattr(h, '_gui_handler', False):
                return  # 已有GUI handler，跳过

        class GUILogHandler(logging.Handler):
            _gui_handler = True  # 标记用于去重

            def __init__(self, gui):
                super().__init__()
                self.gui = gui

            def emit(self, record):
                try:
                    msg = self.format(record)
                    self.gui._log(msg)
                except Exception:
                    pass  # GUI日志失败不中断主流程

        handler = GUILogHandler(self)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        root.addHandler(handler)
        self._log("[GUI] 日志重定向已启用")

    def _log(self, message):
        """添加日志，带行号和级别过滤"""
        def update():
            self._log_counter += 1
            self.log_text.config(state=tk.NORMAL)
            display_msg = f"{self._log_counter:05d} | {message}"
            tag = None
            for level_name in self._log_level_enabled:
                if f'[{level_name}]' in message:
                    tag = level_name
                    break

            # 存储日志条目（用于后续过滤重建）
            self._log_entries.append((display_msg, tag))

            # 如果该级别被过滤，跳过不显示
            if tag and not self._log_level_enabled.get(tag, True):
                self.log_text.config(state=tk.DISABLED)
                # 关键日志同步到悬浮窗口 (WARNING/ERROR)
                if tag in ('WARNING', 'ERROR'):
                    self.floating_window.add_log(message)
                return

            self.log_text.insert(tk.END, display_msg + '\n', tag if tag else ())
            if self.autoscroll_var.get():
                self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

            # 关键日志同步到悬浮窗口 (WARNING/ERROR)
            if tag in ('WARNING', 'ERROR'):
                self.floating_window.add_log(message)
        self.root.after(0, update)

    def _clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state=tk.DISABLED)
        self._log_counter = 0
        self._log_entries.clear()


def main():
    # 全局异常日志文件（用于pythonw.exe无控制台时的调试）
    import sys, traceback
    def log_exception(exc_type, exc_value, exc_traceback):
        error_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'crash_log.txt')
        with open(error_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"Crash at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
            f.write(f"{'='*60}\n")
        # 也尝试标准错误输出
        traceback.print_exception(exc_type, exc_value, exc_traceback)

    sys.excepthook = log_exception

    root = tk.Tk()
    app = GameMonitorGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
