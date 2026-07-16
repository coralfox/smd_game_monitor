import os
import sys
import time
import json
import re
import gc
import logging
import threading
import ctypes
import tkinter as tk
from datetime import datetime
from collections import Counter
from typing import List, Dict, Tuple

import cv2
import numpy as np
from PIL import Image, ImageGrab

# 可选的OCR引擎
try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    pass

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False


class Config:
    """配置管理器"""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.data = {}
        self._load()

    def _load(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        else:
            self.data = self._default_config()
            self._save()

    def _save(self):
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def _default_config(self):
        return {
            "window": {"title": "", "class_name": "", "use_window": False},
            "monitor": {
                "region": {"left": 10, "top": 10, "width": 250, "height": 120},
                "check_interval": 1.0,
                "preprocess": {"grayscale": False, "scale": 1}
            },
            "debounce": {"enabled": True, "min_stable_frames": 2},
            "frequency": {
                "window_seconds": 60, "stuck_threshold": 100, "stuck_ratio": 0.8,
                "min_samples": 20, "alternating_threshold": 80, "alternating_ratio": 0.9,
                "cooldown_seconds": 30
            },
            "strategies": {
                "stuck_fallback": {
                    "name": "默认卡死处理",
                    "description": "当检测到脚本卡死时执行的默认操作",
                    "match_ids": [],
                    "match_stuck_type": "single",
                    "severity": 1.0,
                    "actions": [{"type": "release_keys", "keys": "w,a,s,d,ctrl"}, {"type": "key_press", "key": "p", "presses": 1}]
                },
                "single_stuck": {
                    "name": "单一移动卡死处理",
                    "description": "当检测到单一移动事件卡死时执行（60秒窗口）",
                    "match_ids": ["当前事件", "移动"],
                    "exclude_ids": [],
                    "match_stuck_type": "single",
                    "severity": 1.0,
                    "actions": [{"type": "release_keys", "keys": "w,a,s,d,ctrl"}, {"type": "screenshot"}, {"type": "key_press", "key": "p", "presses": 2, "interval": 0.5}],
                    "stuck_threshold": 30, "stuck_ratio": 0.8
                },
                "action_stuck": {
                    "name": "事件动作卡死处理",
                    "description": "当检测到非移动类事件卡死时执行（5分钟窗口，容忍长处理）",
                    "match_ids": ["当前事件"],
                    "exclude_ids": ["移动"],
                    "match_stuck_type": "single",
                    "severity": 1.0,
                    "window_seconds": 300, "min_samples": 100,
                    "actions": [{"type": "release_keys", "keys": "w,a,s,d,ctrl"}, {"type": "screenshot"}, {"type": "key_press", "key": "p", "presses": 2, "interval": 0.5}],
                    "stuck_threshold": 200, "stuck_ratio": 0.8
                },
                "alternating_stuck": {
                    "name": "交替卡死处理",
                    "description": "当检测到两个事件交替卡死时执行",
                    "match_ids": ["当前事件"],
                    "exclude_ids": [],
                    "match_stuck_type": "alternating",
                    "severity": 2.0,
                    "actions": [{"type": "release_keys", "keys": "w,a,s,d,ctrl"}, {"type": "key_press", "key": "p", "presses": 2}]
                },
                "path_error": {
                    "name": "路径错误处理",
                    "description": "当检测到路径相关错误时执行",
                    "match_ids": ["路径", "错误"],
                    "match_stuck_type": "single",
                    "severity": 2.0,
                    "actions": [{"type": "release_keys", "keys": "w,a,s,d,ctrl"}, {"type": "key_press", "key": "p", "presses": 1}]
                },
                "no_bounty_stuck": {
                    "name": "无悬赏卡死处理",
                    "description": "当未检测到悬赏时，如果发生单一卡死则执行",
                    "match_ids": [],
                    "exclude_ids": ["悬赏"],
                    "match_stuck_type": "single",
                    "severity": 1.0,
                    "actions": [{"type": "release_keys", "keys": "w,a,s,d,ctrl"}, {"type": "key_press", "key": "p", "presses": 1}]
                }
            },
            "adaptive": {
                "enabled": True,
                "warmup_seconds": 300,
                "tune_interval": 60
            },
            "restart_settings": {
                "enabled": False,
                "bat_path": "",
                "rundll32_title": "音乐盒子",
                "rundll32_class": "",
                "play_button_text": "播放",
                "play_wait_text": "等待歌曲启动后点击",
                "game_shortcut": "",
                "game_title": "Tom Clancy's The Division 2",
                "config_positions": {},
                "burst_trigger_count": 5,
                "cooldown_trigger_threshold": 10
            },
            "idle_settings": {
                "enabled": False,
                "stop_after_minutes": 0,
                "stop_at_time": "",
                "stop_after_rounds": 0,
                "stop_after_executions": 0
            },
            "stats_report_time": {
                "enabled": False,
                "start_time": "00:00",
                "end_time": "24:00"
            },
            "logging": {"level": "INFO", "log_to_file": True},
            "hotkeys": {"start_stop": "F8", "pause_resume": "F10"},
            "ui_options": {"always_on_top_game": False, "show_floating_stats": True},
            "alert": {
                "pushplus_enabled": False, "pushplus_token": "",
                "email_enabled": False,
                "email_smtp_server": "", "email_smtp_port": 465, "email_use_ssl": True,
                "email_user": "", "email_password": "", "email_to": "",
                "alert_cooldown_minutes": 15,
                "alert_trigger_threshold": 6,
                "imgbb_api_key": "",
                "imgbb_expiration_days": 7
            }
        }

    @property
    def window(self):
        return self.data.get('window', {})

    @property
    def monitor(self):
        return self.data.get('monitor', {})

    @property
    def debounce(self):
        return self.data.get('debounce', {})

    @property
    def frequency(self):
        return self.data.get('frequency', {})

    @property
    def adaptive(self):
        return self.data.get('adaptive', {})

    @property
    def strategies(self):
        return self.data.get('strategies', {})

    @property
    def idle_settings(self):
        return self.data.get('idle_settings', {})

    @property
    def stats_report_time(self):
        return self.data.get('stats_report_time', {})

    @property
    def logging_config(self):
        return self.data.get('logging', {})

    @property
    def hotkeys(self):
        return self.data.get('hotkeys', {})

    @property
    def alert(self):
        return self.data.get('alert', {})


class ScreenCapture:
    """屏幕截图工具 - 支持窗口模式和屏幕模式"""

    def __init__(self, config: Config):
        self.config = config
        self.window_hwnd = None
        self.window_rect = None
        self._cap_left = 0
        self._cap_top = 0
        self._cap_width = 0
        self._cap_height = 0
        self.SRCCOPY = 0x00CC0020
        self.CAPTUREBLT = 0x40000000

    def find_window(self):
        title = self.config.window.get('title', '')
        class_name = self.config.window.get('class_name', '')

        hwnd = ctypes.windll.user32.FindWindowW(
            class_name if class_name else None,
            title if title else None
        )

        if hwnd:
            self.window_hwnd = hwnd
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            self.window_rect = (rect.left, rect.top, rect.right, rect.bottom)
            logging.info(f"找到游戏窗口: {title} 位置: {self.window_rect}")
            return True
        return False

    def set_window_topmost(self, topmost: bool = True):
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_SHOWWINDOW = 0x0040
        if self.window_hwnd:
            hwnd = self.window_hwnd
            flag = HWND_TOPMOST if topmost else HWND_NOTOPMOST
            ctypes.windll.user32.SetWindowPos(hwnd, flag, 0, 0, 0, 0,
                                               SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW)
            state = "置顶" if topmost else "取消置顶"
            logging.info(f"游戏窗口已{state}")

    def _update_capture_rect(self):
        region = self.config.monitor.get('region', {})
        if self.config.window.get('use_window', False) and self.window_hwnd:
            # 每次截图前重新获取窗口当前位置（窗口可能已移动）
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(self.window_hwnd, ctypes.byref(rect))
            self._cap_left = rect.left + region.get('left', 0)
            self._cap_top = rect.top + region.get('top', 0)
        else:
            self._cap_left = region.get('left', 0)
            self._cap_top = region.get('top', 0)
        self._cap_width = region.get('width', 200)
        self._cap_height = region.get('height', 100)

    def _activate_window(self):
        """激活游戏窗口，确保截图时游戏在前台"""
        if not self.window_hwnd:
            return
        try:
            fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
            if fg_hwnd == self.window_hwnd:
                return
            curr_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            target_thread = ctypes.windll.user32.GetWindowThreadProcessId(self.window_hwnd, None)
            ctypes.windll.user32.AttachThreadInput(target_thread, curr_thread, True)
            SW_RESTORE = 9
            if ctypes.windll.user32.IsIconic(self.window_hwnd):
                ctypes.windll.user32.ShowWindow(self.window_hwnd, SW_RESTORE)
            ctypes.windll.user32.SetForegroundWindow(self.window_hwnd)
            ctypes.windll.user32.AttachThreadInput(target_thread, curr_thread, False)
        except Exception:
            pass

    def capture_region(self) -> Image.Image:
        self._activate_window()
        self._update_capture_rect()
        try:
            img = self._capture_gdi()
            if img is not None:
                return img
        except Exception as e:
            logging.warning(f"GDI截图失败，将使用ImageGrab: {e}")
        try:
            return ImageGrab.grab(bbox=(self._cap_left, self._cap_top,
                                         self._cap_left + self._cap_width,
                                         self._cap_top + self._cap_height))
        except Exception as e:
            logging.error(f"截图完全失败: {e}")
            raise

    def capture_full_window(self) -> Image.Image:
        """截取整个游戏窗口（使用PrintWindow获取高质量截图）"""
        self._activate_window()
        if not self.window_hwnd:
            return None
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(self.window_hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None
        try:
            # 方法1: 使用 PrintWindow 捕获硬件加速窗口（DirectX/OpenGL）
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            hdc_screen = user32.GetDC(None)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbm = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
            gdi32.SelectObject(hdc_mem, hbm)
            # PW_RENDERFULLCONTENT = 0x00000002 捕获完整内容
            PW_RENDERFULLCONTENT = 0x00000002
            result = user32.PrintWindow(self.window_hwnd, hdc_mem, PW_RENDERFULLCONTENT)
            if result:
                # 转换为 PIL Image
                class BITMAPINFOHEADER(ctypes.Structure):
                    _fields_ = [
                        ('biSize', ctypes.wintypes.DWORD), ('biWidth', ctypes.wintypes.LONG), ('biHeight', ctypes.wintypes.LONG),
                        ('biPlanes', ctypes.wintypes.WORD), ('biBitCount', ctypes.wintypes.WORD), ('biCompression', ctypes.wintypes.DWORD),
                        ('biSizeImage', ctypes.wintypes.DWORD), ('biXPelsPerMeter', ctypes.wintypes.LONG),
                        ('biYPelsPerMeter', ctypes.wintypes.LONG), ('biClrUsed', ctypes.wintypes.DWORD), ('biClrImportant', ctypes.wintypes.DWORD)
                    ]
                bmi = BITMAPINFOHEADER()
                bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.biWidth = w
                bmi.biHeight = -h  # 负值表示自顶向下
                bmi.biPlanes = 1
                bmi.biBitCount = 32
                bmi.biCompression = 0
                buf_size = w * h * 4
                buf = ctypes.create_string_buffer(buf_size)
                gdi32.GetDIBits(hdc_mem, hbm, 0, h, buf, ctypes.byref(bmi), 0)
                img = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1)
                img = img.convert('RGB')
            else:
                # PrintWindow 失败，回退到 ImageGrab
                img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
            # 清理
            gdi32.DeleteObject(hbm)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(None, hdc_screen)
            return img
        except Exception as e:
            logging.warning(f"PrintWindow截图失败: {e}，回退到ImageGrab")
            try:
                return ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
            except Exception as e2:
                logging.warning(f"全窗口截图失败: {e2}")
                return None

    def _capture_gdi(self) -> Image.Image:
        try:
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32

            hdc_screen = user32.GetDC(None)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbm = gdi32.CreateCompatibleBitmap(hdc_screen, self._cap_width, self._cap_height)
            gdi32.SelectObject(hdc_mem, hbm)
            gdi32.BitBlt(hdc_mem, 0, 0, self._cap_width, self._cap_height,
                         hdc_screen, self._cap_left, self._cap_top, self.SRCCOPY | self.CAPTUREBLT)

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ('biSize', ctypes.wintypes.DWORD), ('biWidth', ctypes.wintypes.LONG),
                    ('biHeight', ctypes.wintypes.LONG), ('biPlanes', ctypes.wintypes.WORD),
                    ('biBitCount', ctypes.wintypes.WORD), ('biCompression', ctypes.wintypes.DWORD),
                    ('biSizeImage', ctypes.wintypes.DWORD), ('biXPelsPerMeter', ctypes.wintypes.LONG),
                    ('biYPelsPerMeter', ctypes.wintypes.LONG), ('biClrUsed', ctypes.wintypes.DWORD),
                    ('biClrImportant', ctypes.wintypes.DWORD)
                ]

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = self._cap_width
            bmi.biHeight = -self._cap_height
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0

            buf_size = self._cap_width * self._cap_height * 4
            buf = ctypes.create_string_buffer(buf_size)

            gdi32.GetDIBits(hdc_mem, hbm, 0, self._cap_height, buf, ctypes.byref(bmi), 0)

            gdi32.DeleteObject(hbm)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(None, hdc_screen)

            img = Image.frombuffer('RGBA', (self._cap_width, self._cap_height), buf, 'raw', 'BGRA', 0, 1)
            return img.convert('RGB')
        except Exception:
            return None

    def preprocess_image(self, image: Image.Image) -> np.ndarray:
        preprocess = self.config.monitor.get('preprocess', {})
        img_array = np.array(image)
        if preprocess.get('grayscale', False):
            img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            img_array = cv2.cvtColor(img_array, cv2.COLOR_GRAY2RGB)
        scale = preprocess.get('scale', 1)
        if scale != 1:
            h, w = img_array.shape[:2]
            img_array = cv2.resize(img_array, (int(w * scale), int(h * scale)))
        return img_array


class OCREngine:
    """OCR识别引擎"""

    def __init__(self, config: Config):
        self.config = config
        self.ocr = self._get_ocr_instance()
        # 预热：让 ONNX Runtime 完成模型加载，避免第一次识别在监控循环中卡住
        try:
            self.ocr(np.zeros((32, 32, 3), dtype=np.uint8))
        except Exception:
            pass

    def _get_ocr_instance(self):
        return RapidOCR()

    def recognize(self, screenshot: np.ndarray) -> str:
        if isinstance(screenshot, Image.Image):
            screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        result = self.ocr(screenshot)
        lines = []
        if result and isinstance(result, (list, tuple)) and len(result) > 0 and result[0]:
            for line in result[0]:
                if not isinstance(line, (list, tuple)) or len(line) < 2:
                    continue
                text = line[1]
                if not isinstance(text, str):
                    continue
                text = text.strip()
                if text:
                    if text.isdigit():
                        continue
                    lines.append(text)
        raw_text = '\n'.join(lines)
        # 标准化OCR文本：统一相似符号，减少误判
        raw_text = self._normalize_ocr_text(raw_text)
        logging.debug(f"RapidOCR原始结果: [{raw_text}]")
        return raw_text

    def recognize_with_pos(self, screenshot: np.ndarray):
        """OCR识别并返回带坐标的结果: [(text, center_x, center_y), ...]"""
        if isinstance(screenshot, Image.Image):
            screenshot = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        result = self.ocr(screenshot)
        items = []
        if result and isinstance(result, (list, tuple)) and len(result) > 0 and result[0]:
            for line in result[0]:
                if not isinstance(line, (list, tuple)) or len(line) < 2:
                    continue
                boxes = line[0]
                text = line[1]
                if not isinstance(text, str):
                    continue
                text = text.strip()
                if not text:
                    continue
                # boxes 是4个角点坐标 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                if boxes is not None and len(boxes) >= 4:
                    pts = np.array(boxes)
                    cx = int(pts[:, 0].mean())
                    cy = int(pts[:, 1].mean())
                    items.append((text, cx, cy))
        return items

    @staticmethod
    def _normalize_ocr_text(text: str) -> str:
        """标准化OCR文本：统一容易混淆的符号"""
        # 下划线 → 连字符（OCR经常把-识别为_）
        text = text.replace('_', '-')
        # 等号 → 连字符（OCR可能把-识别为=）
        text = text.replace('=', '-')
        # 全角符号 → 半角
        text = text.replace('－', '-').replace('—', '-')
        text = text.replace('（', '(').replace('）', ')')
        text = text.replace('：', ':')
        # 数字与汉字之间缺少连字符的补全：如 "当前事件57移动" → "当前事件-57-移动"
        text = re.sub(r'([\u4e00-\u9fff])(\d)', r'\1-\2', text)   # 汉字后接数字：事件57 → 事件-57
        text = re.sub(r'(\d)([\u4e00-\u9fff])', r'\1-\2', text)   # 数字后接汉字：57移动 → 57-移动
        # 冒号/负号后跟空格再跟数字时，去掉空格（OCR把"当前事件:-214"识别成"当前事件: 214"和"当前事件-214"）
        text = re.sub(r'([:\-－—])\s+(\d)', r'\1\2', text)
        # 多余空格清理
        text = text.replace('  ', ' ')
        return text


class ActionExecutor:
    """动作执行器 - 模拟键盘和鼠标操作"""

    def __init__(self, config: Config):
        self.config = config
        self.window_hwnd = None
        self.window_offset = (0, 0)
        self._current_strategy_name = ''  # 当前执行的策略名，用于截图命名

    def set_window(self, hwnd: int, offset: Tuple[int, int] = None):
        self.window_hwnd = hwnd
        if offset:
            self.window_offset = offset

    def _activate_window(self):
        """激活游戏窗口，避免按键被输入法或其他窗口干扰"""
        if not self.window_hwnd:
            return
        try:
            # 获取当前线程ID和目标窗口线程ID
            curr_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            target_thread = ctypes.windll.user32.GetWindowThreadProcessId(self.window_hwnd, None)

            # 附加线程输入（确保 SetForegroundWindow 能成功）
            ctypes.windll.user32.AttachThreadInput(target_thread, curr_thread, True)

            # 如果窗口最小化，先恢复
            SW_RESTORE = 9
            if ctypes.windll.user32.IsIconic(self.window_hwnd):
                ctypes.windll.user32.ShowWindow(self.window_hwnd, SW_RESTORE)

            # 设置前台窗口
            ctypes.windll.user32.SetForegroundWindow(self.window_hwnd)

            # 分离线程输入
            ctypes.windll.user32.AttachThreadInput(target_thread, curr_thread, False)

            time.sleep(0.05)
        except Exception as e:
            logging.warning(f"激活游戏窗口失败: {e}")

    def execute_action(self, action: Dict):
        action_type = action.get('type', '')
        try:
            if action_type == 'release_keys':
                self._release_keys_action(action)
            elif action_type == 'key_press':
                self._key_press(action)
            elif action_type == 'mouse_click':
                self._mouse_click(action)
            elif action_type == 'mouse_move':
                self._mouse_move(action)
            elif action_type == 'text_input':
                self._text_input(action)
            elif action_type == 'wait':
                time.sleep(action.get('duration', 0.5))
            elif action_type == 'delay':
                time.sleep(action.get('seconds', 0.5))
            elif action_type == 'log':
                message = action.get('message', '')
                logging.info(f"[动作日志] {message}")
            elif action_type == 'screenshot':
                self._screenshot_action(action)
            else:
                logging.warning(f"未知动作类型: {action_type}")
        except Exception as e:
            logging.error(f"执行动作失败: {e}")

    def upload_screenshot_to_imgbb(self, image_path: str = None, image_data=None) -> str:
        """上传截图到ImgBB图床，返回URL。优先使用本地文件，其次使用PIL Image对象"""
        imgbb_key = getattr(self, '_imgbb_api_key', '')
        if not imgbb_key:
            return ''
        # 从配置读取过期时间（默认7天）
        expiration_days = 7
        if hasattr(self.config, 'alert'):
            expiration_days = self.config.alert.get('imgbb_expiration_days', 7)
        # 转换为秒: 天 * 86400
        expiration_seconds = int(expiration_days * 86400)
        try:
            import base64, io, urllib.request, urllib.parse
            if image_path and os.path.isfile(image_path):
                img = Image.open(image_path)
            elif image_data is not None:
                img = image_data
            else:
                return ''
            # 压缩参数：统计报告截图保持较高分辨率
            max_w = 1200
            if img.width > max_w:
                ratio = max_w / img.width
                img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=90)
            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
            upload_data = urllib.parse.urlencode({
                'key': imgbb_key,
                'image': b64,
                'expiration': expiration_seconds
            }).encode('utf-8')
            upload_req = urllib.request.Request(
                'https://api.imgbb.com/1/upload',
                data=upload_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                method='POST'
            )
            # 超时30秒，SSL握手慢时可能需要更长时间
            with urllib.request.urlopen(upload_req, timeout=30) as upload_resp:
                upload_result = json.loads(upload_resp.read().decode('utf-8'))
                if upload_result.get('success'):
                    url = upload_result['data']['url']
                    logging.info(f"[图床] 截图已上传: {url}")
                    return url
                else:
                    logging.warning(f"[图床] 上传失败: {upload_result}")
                    return ''
        except urllib.error.URLError as e:
            # SSL握手超时等网络问题，重试一次
            logging.warning(f"[图床] 上传异常(将重试): {e}")
            try:
                import time
                time.sleep(3)
                with urllib.request.urlopen(upload_req, timeout=30) as upload_resp:
                    upload_result = json.loads(upload_resp.read().decode('utf-8'))
                    if upload_result.get('success'):
                        url = upload_result['data']['url']
                        logging.info(f"[图床] 重试上传成功: {url}")
                        return url
                    else:
                        logging.warning(f"[图床] 重试上传失败: {upload_result}")
                        return ''
            except Exception as e2:
                logging.warning(f"[图床] 重试上传异常: {e2}")
                return ''
        except Exception as e:
            logging.warning(f"[图床] 上传异常: {e}")
            return ''

    def execute_actions(self, actions: List[Dict], delay: float = 0.5):
        if not actions:
            return
        # 执行动作前先激活游戏窗口
        self._activate_window()
        logging.info(f"[执行] 开始执行 {len(actions)} 个动作...")
        for i, action in enumerate(actions):
            logging.info(f"[执行] 动作 {i+1}/{len(actions)}: {action.get('type', 'unknown')}")
            self.execute_action(action)
            if i < len(actions) - 1:
                time.sleep(delay)
        logging.info("[执行] 动作序列执行完成")

    def _release_keys_action(self, action: Dict):
        """释放指定的按键（支持逗号分隔的按键名，兼容 key 和 keys 字段）"""
        keys_str = action.get('keys', 'w,a,s,d,ctrl')
        key_list = [k.strip().lower() for k in keys_str.split(',') if k.strip()]
        for key_name in key_list:
            vk = self._get_vk_code(key_name)
            if vk:
                ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        logging.debug(f"[按键] 已释放按键: {keys_str}")

    def _release_all_keys(self):
        """释放所有可能卡住的按键（内部备用方法）"""
        stuck_keys = [
            0x57, 0x41, 0x53, 0x44,  # W A S D
            0xA0, 0xA1,              # LSHIFT RSHIFT
            0xA2, 0xA3,              # LCTRL RCTRL
            0xA4, 0xA5,              # LALT RALT
            0x20,                    # SPACE
            0x26, 0x28, 0x25, 0x27,  # UP DOWN LEFT RIGHT
            0x11, 0x10, 0x12,        # VK_CONTROL VK_SHIFT VK_ALT (通用)
        ]
        for vk in stuck_keys:
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        logging.debug("[按键] 已释放所有可能卡住的按键")

    def _key_press(self, action: Dict):
        key = action.get('key', '')
        presses = action.get('presses', 1)
        duration = action.get('duration', 0.1)

        # 发送按键前确保游戏窗口在前台
        self._activate_window()

        vk_code = self._get_vk_code(key)
        if not vk_code:
            logging.warning(f"无法映射按键: {key}")
            return

        # 使用 SendInput + 扫描码发送按键，绕过输入法干扰
        MAPVK_VK_TO_VSC = 0
        KEYEVENTF_SCANCODE = 0x0008
        KEYEVENTF_KEYUP = 0x0002
        INPUT_KEYBOARD = 1
        scan = ctypes.windll.user32.MapVirtualKeyW(vk_code, MAPVK_VK_TO_VSC)
        if not scan:
            # 回退到 keybd_event
            for _ in range(presses):
                ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
                time.sleep(duration)
                ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)
                time.sleep(0.1)
            return

        for _ in range(presses):
            inp_down = _INPUT()
            inp_down.type = INPUT_KEYBOARD
            inp_down.union.ki.wVk = 0
            inp_down.union.ki.wScan = scan
            inp_down.union.ki.dwFlags = KEYEVENTF_SCANCODE
            inp_down.union.ki.time = 0
            inp_down.union.ki.dwExtraInfo = 0
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp_down), _INPUT_SIZE)
            time.sleep(duration)
            inp_up = _INPUT()
            inp_up.type = INPUT_KEYBOARD
            inp_up.union.ki.wVk = 0
            inp_up.union.ki.wScan = scan
            inp_up.union.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
            inp_up.union.ki.time = 0
            inp_up.union.ki.dwExtraInfo = 0
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp_up), _INPUT_SIZE)
            time.sleep(0.1)

    def _get_vk_code(self, key: str) -> int:
        key_map = {
            'p': 0x50, 'P': 0x50,
            'enter': 0x0D, 'Enter': 0x0D,
            'space': 0x20, 'Space': 0x20,
            'esc': 0x1B, 'Esc': 0x1B,
            'tab': 0x09, 'Tab': 0x09,
            'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
            'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
            'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
            'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
            'ctrl': 0x11, 'Ctrl': 0x11, 'shift': 0x10, 'Shift': 0x10,
            'alt': 0x12, 'Alt': 0x12,
            'w': 0x57, 'W': 0x57, 'a': 0x41, 'A': 0x41,
            's': 0x53, 'S': 0x53, 'd': 0x44, 'D': 0x44,
        }
        if key in key_map:
            return key_map[key]
        if len(key) == 1:
            return ord(key.upper())
        return 0

    def _mouse_click(self, action: Dict):
        x = action.get('x', 0)
        y = action.get('y', 0)
        button = action.get('button', 'left')
        clicks = action.get('clicks', 1)

        abs_x = int((x + self.window_offset[0]) * 65535 / ctypes.windll.user32.GetSystemMetrics(0))
        abs_y = int((y + self.window_offset[1]) * 65535 / ctypes.windll.user32.GetSystemMetrics(1))

        if button == 'left':
            down_flag, up_flag = 0x0002, 0x0004
        else:
            down_flag, up_flag = 0x0008, 0x0010

        for _ in range(clicks):
            ctypes.windll.user32.mouse_event(down_flag | up_flag, abs_x, abs_y, 0, 0)
            time.sleep(0.1)

    def _mouse_move(self, action: Dict):
        x = action.get('x', 0)
        y = action.get('y', 0)
        abs_x = int((x + self.window_offset[0]) * 65535 / ctypes.windll.user32.GetSystemMetrics(0))
        abs_y = int((y + self.window_offset[1]) * 65535 / ctypes.windll.user32.GetSystemMetrics(1))
        ctypes.windll.user32.mouse_event(0x8000 | 0x4000, abs_x, abs_y, 0, 0)

    def _text_input(self, action: Dict):
        text = action.get('text', '')
        for char in text:
            self.execute_action({'type': 'key_press', 'key': char, 'presses': 1})

    def _screenshot_action(self, action: Dict):
        """截图动作：激活窗口并截取整个游戏窗口，保存到异常子目录"""
        if not self.window_hwnd:
            logging.warning("[截图动作] 未设置窗口句柄，无法截图")
            return

        # 先激活窗口，确保前台显示
        self._activate_window()

        try:
            # 获取窗口矩形
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(self.window_hwnd, ctypes.byref(rect))
            left, top = rect.left, rect.top
            right, bottom = rect.right, rect.bottom
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                logging.warning("[截图动作] 窗口尺寸无效，无法截图")
                return

            # 使用PIL ImageGrab截取窗口区域（彩色、正常分辨率）
            img = ImageGrab.grab(bbox=(left, top, right, bottom))

            # 保存到异常子目录（兼容 PyInstaller 单文件模式）
            if getattr(sys, 'frozen', False):
                app_dir = os.path.dirname(sys.executable)
            else:
                app_dir = os.path.dirname(os.path.abspath(__file__))
            anomaly_dir = os.path.join(app_dir, '异常')
            os.makedirs(anomaly_dir, exist_ok=True)

            strategy_name = self._current_strategy_name or 'unknown'
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{strategy_name}_{timestamp}.png"
            filepath = os.path.join(anomaly_dir, filename)

            img.save(filepath, 'PNG')
            logging.info(f"[截图动作] 已保存异常截图: {filename}")
            # 记录最近截图路径，供报警推送时上传
            self._last_screenshot_path = filepath
        except Exception as e:
            logging.error(f"[截图动作] 截图失败: {e}")


class FrequencyAnalyzer:
    """频率分析器 - 按策略维护独立样本库，分别统计检测卡脚本"""

    def __init__(self, config: Config):
        self.config = config
        self.window_seconds = config.data.get('frequency', {}).get('window_seconds', 60)
        self.stuck_threshold = config.data.get('frequency', {}).get('stuck_threshold', 100)
        self.stuck_ratio = config.data.get('frequency', {}).get('stuck_ratio', 0.8)
        self.min_samples = config.data.get('frequency', {}).get('min_samples', 20)
        self.alternating_threshold = config.data.get('frequency', {}).get('alternating_threshold', 80)
        self.alternating_ratio = config.data.get('frequency', {}).get('alternating_ratio', 0.9)

        self.strategy_samples = {}
        self.last_trigger_time = 0

        self._strategy_keyword_groups = self._build_keyword_groups()

    def _build_keyword_groups(self) -> list:
        groups = []
        strategies = self.config.data.get('strategies', {})
        for key, strategy in strategies.items():
            if key in ('default', 'stuck_fallback'):
                continue
            match_ids = strategy.get('match_ids', [])
            exclude_ids = strategy.get('exclude_ids', [])
            if match_ids or exclude_ids:
                groups.append((key, match_ids, exclude_ids))
        return groups

    def add_sample(self, script_id: str, full_text: str = None):
        now = time.time()
        added = False
        check_text = full_text if full_text else script_id
        for strategy_key, match_ids, exclude_ids in self._strategy_keyword_groups:
            # 排除匹配：使用完整多行文本检查
            if exclude_ids and any(kw in check_text for kw in exclude_ids):
                continue
            # 正向匹配：使用完整多行文本检查
            if match_ids and not all(kw in check_text for kw in match_ids):
                continue
            # 提取样本ID：有match_ids时，提取匹配到的行作为稳定标识
            if match_ids:
                sample_id = self._extract_matched_line(check_text, match_ids)
            else:
                # 无match_ids时（如no_bounty_stuck），用统一标记
                # （有悬赏执行的文本已被第一层 exclude_ids 过滤掉）
                sample_id = "__无悬赏卡死__"
            if strategy_key not in self.strategy_samples:
                self.strategy_samples[strategy_key] = []
            self.strategy_samples[strategy_key].append((now, sample_id))
            added = True
        if not added:
            if '_unmatched' not in self.strategy_samples:
                self.strategy_samples['_unmatched'] = []
            self.strategy_samples['_unmatched'].append((now, script_id))

        # 定期清理过期样本（避免内存无限增长）
        self._cleanup_old_samples(now)

    @staticmethod
    def _extract_matched_line(text: str, match_ids: list) -> str:
        """从多行文本中提取包含所有匹配关键词的行"""
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if line and all(kw in line for kw in match_ids):
                return line
        # 没找到精确匹配行，返回包含第一个关键词的行
        for line in lines:
            line = line.strip()
            if line and match_ids[0] in line:
                return line
        return lines[0].strip() if lines else text

    def _cleanup_old_samples(self, now: float = None):
        if now is None:
            now = time.time()
        strategies = self.config.data.get('strategies', {})
        for key in list(self.strategy_samples.keys()):
            # 每策略可单独配置统计窗口
            ws = self.window_seconds
            if key != '_unmatched':
                s = strategies.get(key, {})
                ws = s.get('window_seconds', ws)
            cutoff = now - ws
            self.strategy_samples[key] = [(t, sid) for t, sid in self.strategy_samples[key] if t > cutoff]
            if not self.strategy_samples[key]:
                del self.strategy_samples[key]

    def _analyze_queue(self, samples: list, match_stuck_type: str = 'any',
                       stuck_threshold: int = None, stuck_ratio: float = None,
                       alternating_threshold: int = None, alternating_ratio: float = None,
                       window_seconds: float = None) -> dict:

        st = stuck_threshold if stuck_threshold is not None else self.stuck_threshold
        sr = stuck_ratio if stuck_ratio is not None else self.stuck_ratio
        at = alternating_threshold if alternating_threshold is not None else self.alternating_threshold
        ar = alternating_ratio if alternating_ratio is not None else self.alternating_ratio
        ws = window_seconds if window_seconds is not None else self.window_seconds

        # 按时间窗口过滤样本，只保留最近 ws 内的
        cutoff = time.time() - ws
        windowed = [(t, sid) for t, sid in samples if t >= cutoff]
        ids = [sid for _, sid in windowed if sid]
        if not ids:
            return None

        # 规范化ID：对于事件编号，去掉前导负号（OCR可能把:-214识别为:214）
        def _normalize_id(sid):
            m = re.search(r'(-?\d+)(?:-|$)', sid)
            if m:
                num = m.group(1).lstrip('-')
                return re.sub(r'-?\d+', num, sid, count=1)
            return sid

        normalized_ids = [_normalize_id(sid) for sid in ids]
        counts = Counter(normalized_ids)
        total = len(normalized_ids)
        most_common = counts.most_common()
        top_id, top_count = most_common[0]
        top_ratio = top_count / total

        if match_stuck_type in ('any', 'single'):
            if top_count >= st and top_ratio >= sr:
                # 对于策略标记样本（排除型策略），显示策略名称
                display_id = top_id
                if top_id.startswith('__') and top_id.endswith('__'):
                    marker_key = top_id[2:-2]
                    # 尝试从配置中获取策略名称
                    strategies = self.config.data.get('strategies', {})
                    if marker_key in strategies:
                        display_id = strategies[marker_key].get('name', marker_key)
                    else:
                        display_id = marker_key
                return {
                    'is_stuck': True,
                    'stuck_type': 'single',
                    'stuck_ids': [top_id],
                    'counts': dict(counts),
                    'total': total,
                    'top_ratio': top_ratio,
                    'details': (f"单一编号卡死: [{display_id}] 出现 {top_count} 次 "
                               f"(占比 {top_ratio:.1%}, 阈值 {st}/{sr:.0%})")
                }

        if match_stuck_type in ('any', 'alternating'):
            if len(most_common) >= 2:
                top_count = most_common[0][1]
                second_count = most_common[1][1]
                top2_count = top_count + second_count
                top2_ratio = top2_count / total
                # 交替卡死要求两个事件次数相对均衡（次高 >= 最高的30%）
                min_alternating_balance = 0.3
                if top2_count >= at and top2_ratio >= ar and second_count >= top_count * min_alternating_balance:
                    id0, id1 = most_common[0][0], most_common[1][0]
                    # 对于策略标记样本，显示策略名称
                    strategies = self.config.data.get('strategies', {})
                    def _display_name(sid):
                        if sid.startswith('__') and sid.endswith('__'):
                            mk = sid[2:-2]
                            return strategies.get(mk, {}).get('name', mk) if mk in strategies else mk
                        return sid
                    return {
                        'is_stuck': True,
                        'stuck_type': 'alternating',
                        'stuck_ids': [id0, id1],
                        'counts': dict(counts),
                        'total': total,
                        'top_ratio': top2_ratio,
                        'details': (f"双编号交替卡死: [{_display_name(id0)}]x{most_common[0][1]} "
                                   f"[{_display_name(id1)}]x{most_common[1][1]} "
                                   f"(合计占比 {top2_ratio:.1%}, 阈值 {at}/{ar:.0%})")
                    }

        return {
            'is_stuck': False,
            'stuck_type': None,
            'stuck_ids': [],
            'counts': dict(counts),
            'total': total,
            'top_ratio': top_ratio,
            'details': (f"正常: 最高频 [{top_id}] {top_count} 次 "
                       f"(占比 {top_ratio:.1%})")
        }

    def analyze(self, adaptive_params=None) -> dict:

        strategies = self.config.data.get('strategies', {})
        results = []
        ap = adaptive_params or {}  # 自适应参数覆盖

        # DEBUG: 输出所有策略样本库的详细信息
        logging.debug("[analyze] ===== 样本库详情 =====")
        for strategy_key, samples in self.strategy_samples.items():
            if not samples:
                continue
            sname = strategies.get(strategy_key, {}).get('name', strategy_key)
            s_min = strategies.get(strategy_key, {}).get('min_samples', self.min_samples)
            ids = [sid for _, sid in samples]
            id_counts = Counter(ids)
            top5 = id_counts.most_common(5)
            top5_str = ', '.join(f'{sid}={cnt}' for sid, cnt in top5)
            skip = len(samples) < s_min
            logging.debug(f"[analyze] 策略 '{sname}' [{strategy_key}] 样本数={len(samples)} min={s_min} {'跳过' if skip else '分析中'} | Top: {top5_str}")
        logging.debug("[analyze] =========================")

        for strategy_key, samples in self.strategy_samples.items():
            if strategy_key == '_unmatched':
                continue
            strategy = strategies.get(strategy_key, {})
            # 每策略可单独配置统计窗口和最小样本
            s_min = strategy.get('min_samples', self.min_samples)
            if len(samples) < s_min:
                continue
            match_type = strategy.get('match_stuck_type', 'any')
            s_window = strategy.get('window_seconds', self.window_seconds)
            # 优先使用自适应参数，否则从配置读取
            ap_thr = ap.get('stuck_threshold', {}).get(strategy_key)
            ap_ratio = ap.get('stuck_ratio', {}).get(strategy_key)
            r = self._analyze_queue(
                samples, match_type,
                stuck_threshold=ap_thr if ap_thr is not None else strategy.get('stuck_threshold'),
                stuck_ratio=ap_ratio if ap_ratio is not None else strategy.get('stuck_ratio'),
                alternating_threshold=strategy.get('alternating_threshold'),
                alternating_ratio=strategy.get('alternating_ratio'),
                window_seconds=s_window
            )
            if r is None:
                continue
            # 调试日志：显示每个策略的样本统计
            if r and strategy_key != '_unmatched':
                top_id = (r.get('stuck_ids') or [None])[0]
                top_count = dict(r.get('counts', {})).get(top_id, 0)
                logging.debug(f"[analyze] 策略 '{strategy_key}' 样本数={len(samples)} 最高事件={top_id} 次数={top_count} 总样本={r.get('total',0)} 占比={r.get('top_ratio',0):.1%} 是否卡死={r['is_stuck']}")
            if r and r['is_stuck']:
                r['_strategy_key'] = strategy_key
                results.append(r)

        if not results:
            total_samples = sum(len(s) for s in self.strategy_samples.values())
            return {
                'is_stuck': False,
                'stuck_type': None,
                'stuck_ids': [],
                'counts': {},
                'total': total_samples,
                'top_ratio': 0.0,
                'details': f'样本不足或未达到阈值 (总样本{total_samples})'
            }

        single_results = [r for r in results if r['stuck_type'] == 'single']
        if single_results:
            total_samples = sum(len(s) for s in self.strategy_samples.values() if s and isinstance(s, list))
            best = max(single_results, key=lambda x: x['total'])
            strategy_key = best.pop('_strategy_key', '')
            best['_strategy_key'] = strategy_key
            return {'is_stuck': True, 'results': single_results, 'total_samples': total_samples}

        alternating_results = [r for r in results if r['stuck_type'] == 'alternating']
        if alternating_results:
            total_samples = sum(len(s) for s in self.strategy_samples.values() if s and isinstance(s, list))
            best = max(alternating_results, key=lambda x: x['total'])
            strategy_key = best.pop('_strategy_key', '')
            best['_strategy_key'] = strategy_key
            return {'is_stuck': True, 'results': alternating_results, 'total_samples': total_samples}

        return results[0]

    def reset(self):
        self.strategy_samples = {}
        self.last_trigger_time = 0


class AdaptiveTuner:
    """动态自适应调整器 - 根据误报/漏报自动调参"""

    def __init__(self, config):
        self.config = config
        adaptive_cfg = config.data.get('adaptive', {})

        # 开关与控制参数
        self._enabled = adaptive_cfg.get('enabled', True)
        self._warmup_seconds = adaptive_cfg.get('warmup_seconds', 300)
        self._verification_window = adaptive_cfg.get('verification_window', 30)
        self._adjust_cooldown = adaptive_cfg.get('adjust_cooldown', 60)
        self._max_adjustments = adaptive_cfg.get('max_adjustments', 20)
        self._margin_threshold = adaptive_cfg.get('margin_threshold', 0.05)
        self._oscillation_threshold = adaptive_cfg.get('oscillation_threshold', 0.5)
        self._oscillation_freeze_seconds = adaptive_cfg.get('oscillation_freeze_seconds', 1800)

        # 初始参数快照（从配置读取）
        strategies = config.data.get('strategies', {})
        self._initial_params = {
            'check_interval': float(config.monitor.get('check_interval', 1.0)),
            'min_samples': {},
            'stuck_ratio': {},
            'stuck_threshold': {},
        }
        for key, s in strategies.items():
            self._initial_params['min_samples'][key] = s.get('min_samples', config.data.get('frequency', {}).get('min_samples', 20))
            self._initial_params['stuck_ratio'][key] = s.get('stuck_ratio', 0.8)
            self._initial_params['stuck_threshold'][key] = s.get('stuck_threshold', 30)

        # 运行时参数（深拷贝初始值）
        self._params = {
            'check_interval': self._initial_params['check_interval'],
            'min_samples': dict(self._initial_params['min_samples']),
            'stuck_ratio': dict(self._initial_params['stuck_ratio']),
            'stuck_threshold': dict(self._initial_params['stuck_threshold']),
        }

        # 触发记录
        self._trigger_records = []  # {time, strategy_key, stuck_id, top_ratio, total, margin, verified, ocr_snapshot}
        # 调整历史
        self._adjustment_history = []  # {time, param, strategy_key, old_val, new_val, reason}
        # 统计
        self._fp_count = 0
        self._fn_count = 0
        self._total_adjustments = 0
        self._last_adjust_time = 0
        self._direction_history = {}  # {param_key: [+1, -1, +1, ...]} 用于振荡检测
        self._frozen_params = {}  # {param_key: freeze_until_time}
        self._start_time = None

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, val):
        self._enabled = val

    def record_trigger(self, strategy_key, result, ocr_text):
        """策略触发时调用，记录触发信息"""
        if not self._enabled:
            return
        now = time.time()
        if self._start_time is None:
            self._start_time = now
        # 暖身期内不记录
        if now - self._start_time < self._warmup_seconds:
            return
        ratio = result.get('top_ratio', 0.0)
        s_ratio = self._params['stuck_ratio'].get(strategy_key, 0.8)
        margin = ratio - s_ratio
        record = {
            'time': now,
            'strategy_key': strategy_key,
            'stuck_id': (result.get('stuck_ids') or [''])[0],
            'top_ratio': ratio,
            'total': result.get('total', 0),
            'margin': margin,
            'verified': None,
            'ocr_snapshot': ocr_text[:200],
        }
        self._trigger_records.append(record)
        # 只保留最近20条
        if len(self._trigger_records) > 20:
            self._trigger_records.pop(0)
        logging.debug(f"[自适应] 记录触发: {strategy_key} margin={margin:.3f}")

    def verify_recent_triggers(self, ocr_text):
        """每轮循环调用，检测误报"""
        if not self._enabled:
            return
        now = time.time()
        if self._start_time is None or now - self._start_time < self._warmup_seconds:
            return

        for record in self._trigger_records:
            if record['verified'] is not None:
                continue
            elapsed = now - record['time']
            # 超时未验证，标记为真触发
            if elapsed > self._verification_window:
                record['verified'] = True
                continue
            # 边缘触发检测：margin < 阈值
            if record['margin'] < self._margin_threshold:
                # 检查当前OCR是否与触发时不同（游戏自然变化）
                if ocr_text[:200] != record['ocr_snapshot']:
                    # 且不是同一样本卡住
                    current_stuck = ocr_text.strip().split('\n')[0][:30] if ocr_text.strip() else ''
                    if current_stuck != record['stuck_id']:
                        record['verified'] = False
                        self._handle_false_positive(record)
                        continue

    def record_recovery(self, strategy_key, ocr_text):
        """检测到OCR文本变化时调用，确认真触发"""
        if not self._enabled:
            return
        for record in reversed(self._trigger_records):
            if (record['strategy_key'] == strategy_key and record['verified'] is None
                    and time.time() - record['time'] < self._verification_window):
                record['verified'] = True
                break

    def record_false_negative(self, strategy_key, context=None):
        """漏报时调用（如紧急停止触发时）"""
        if not self._enabled:
            return
        now = time.time()
        if self._start_time is None or now - self._start_time < self._warmup_seconds:
            return
        self._fn_count += 1
        logging.info(f"[自适应] 漏报检测: {strategy_key} 累计漏报={self._fn_count}")
        self._handle_false_negative(strategy_key)

    def _handle_false_positive(self, record):
        """误报处理 - 收紧阈值"""
        self._fp_count += 1
        key = record['strategy_key']
        logging.info(f"[自适应] 误报检测: {key} margin={record['margin']:.3f} 累计误报={self._fp_count}")

        # 调整 stuck_ratio
        self._adjust_param(f'{key}.stuck_ratio', step=0.03, direction=1,
                           min_val=0.50, max_val=0.98, reason=f'误报收紧 {key}')
        # 调整 stuck_threshold
        self._adjust_param(f'{key}.stuck_threshold', step=5, direction=1,
                           min_val=max(5, int(self._initial_params['stuck_threshold'].get(key, 30) * 0.3)),
                           max_val=int(self._initial_params['stuck_threshold'].get(key, 30) * 3),
                           reason=f'误报收紧 {key}')
        # 上调 check_interval（降低采样频率）
        self._adjust_param('check_interval', step=0.1, direction=1,
                           min_val=0.3, max_val=5.0, reason='误报-降低采样频率')

    def _handle_false_negative(self, strategy_key):
        """漏报处理 - 放宽阈值"""
        key = strategy_key
        # 下调 stuck_ratio
        self._adjust_param(f'{key}.stuck_ratio', step=-0.03, direction=-1,
                           min_val=0.50, max_val=0.98, reason=f'漏报放宽 {key}')
        # 下调 stuck_threshold
        self._adjust_param(f'{key}.stuck_threshold', step=-5, direction=-1,
                           min_val=max(5, int(self._initial_params['stuck_threshold'].get(key, 30) * 0.3)),
                           max_val=int(self._initial_params['stuck_threshold'].get(key, 30) * 3),
                           reason=f'漏报放宽 {key}')
        # 下调 check_interval（提高采样频率）
        self._adjust_param('check_interval', step=-0.1, direction=-1,
                           min_val=0.3, max_val=5.0, reason='漏报-提高采样频率')

    def _adjust_param(self, param_key, step, direction, min_val, max_val, reason):
        """调整单个参数（带振荡检测和冷却期）"""
        now = time.time()
        # 冷却期检查
        if now - self._last_adjust_time < self._adjust_cooldown:
            return
        # 总调整次数检查
        if self._total_adjustments >= self._max_adjustments:
            logging.warning(f"[自适应] 达到最大调整次数({self._max_adjustments})，参数已锁定")
            return
        # 冻结检查
        if param_key in self._frozen_params and now < self._frozen_params[param_key]:
            return

        # 振荡检测
        if param_key not in self._direction_history:
            self._direction_history[param_key] = []
        self._direction_history[param_key].append(direction)
        if len(self._direction_history[param_key]) > 10:
            self._direction_history[param_key].pop(0)
        recent = self._direction_history[param_key][-10:]
        reversals = sum(1 for i in range(1, len(recent)) if recent[i] != recent[i-1])
        if len(recent) >= 10 and reversals >= 5:
            logging.warning(f"[自适应] 振荡检测: {param_key} 过去10次调整中{reversals}次反向，冻结{self._oscillation_freeze_seconds//60}分钟")
            self._frozen_params[param_key] = now + self._oscillation_freeze_seconds
            return

        # 解析参数路径
        parts = param_key.split('.')
        if len(parts) == 2:
            # strategy_key.param_name
            s_key, p_name = parts
            if p_name in self._params and s_key in self._params[p_name]:
                old_val = self._params[p_name][s_key]
                new_val = max(min_val, min(max_val, old_val + step))
                if new_val == old_val:
                    return
                self._params[p_name][s_key] = new_val
                self._last_adjust_time = now
                self._total_adjustments += 1
                entry = {'time': now, 'param': param_key, 'old_val': old_val, 'new_val': new_val, 'reason': reason}
                self._adjustment_history.append(entry)
                if len(self._adjustment_history) > 50:
                    self._adjustment_history.pop(0)
                logging.info(f"[自适应] 参数调整: {param_key} {old_val:.3f} -> {new_val:.3f} ({reason})")
        else:
            # 全局参数
            p_name = parts[0]
            if p_name in self._params:
                old_val = self._params[p_name]
                new_val = max(min_val, min(max_val, old_val + step))
                if new_val == old_val:
                    return
                self._params[p_name] = new_val
                self._last_adjust_time = now
                self._total_adjustments += 1
                entry = {'time': now, 'param': param_key, 'old_val': old_val, 'new_val': new_val, 'reason': reason}
                self._adjustment_history.append(entry)
                if len(self._adjustment_history) > 50:
                    self._adjustment_history.pop(0)
                logging.info(f"[自适应] 参数调整: {param_key} {old_val:.3f} -> {new_val:.3f} ({reason})")

    def get_param(self, param_name, strategy_key=None):
        """获取当前运行时参数值"""
        if strategy_key and param_name in self._params and strategy_key in self._params[param_name]:
            return self._params[param_name][strategy_key]
        if param_name in self._params:
            return self._params[param_name]
        return None

    def get_check_interval(self):
        return self._params.get('check_interval', 1.0)

    def get_adaptive_stats(self):
        """返回供GUI显示的自适应状态"""
        # 检查是否有参数被调整过
        changes = []
        for key, val in self._params.get('stuck_ratio', {}).items():
            init = self._initial_params['stuck_ratio'].get(key, 0.8)
            if abs(val - init) > 0.001:
                changes.append(f"ratio:{val:.2f}({val-init:+.2f})")
        for key, val in self._params.get('stuck_threshold', {}).items():
            init = self._initial_params['stuck_threshold'].get(key, 30)
            if abs(val - init) > 0.1:
                changes.append(f"thr:{int(val)}({int(val-init):+d})")
        ci = self._params.get('check_interval', 1.0)
        ci_init = self._initial_params['check_interval']
        if abs(ci - ci_init) > 0.01:
            changes.append(f"int:{ci:.1f}s({ci-ci_init:+.1f})")

        # 检查冻结
        now = time.time()
        frozen_list = [k for k, v in self._frozen_params.items() if now < v]
        frozen_str = f" [冻结:{','.join(frozen_list)}]" if frozen_list else ""

        return {
            'enabled': self._enabled,
            'fp_count': self._fp_count,
            'fn_count': self._fn_count,
            'total_adjustments': self._total_adjustments,
            'changes_str': ' '.join(changes) if changes else '参数正常',
            'frozen': frozen_str,
        }

    def reset(self):
        """重置所有参数到初始值"""
        self._params['check_interval'] = self._initial_params['check_interval']
        self._params['min_samples'] = dict(self._initial_params['min_samples'])
        self._params['stuck_ratio'] = dict(self._initial_params['stuck_ratio'])
        self._params['stuck_threshold'] = dict(self._initial_params['stuck_threshold'])
        self._trigger_records.clear()
        self._adjustment_history.clear()
        self._fp_count = 0
        self._fn_count = 0
        self._total_adjustments = 0
        self._direction_history.clear()
        self._frozen_params.clear()
        logging.info("[自适应] 参数已重置为初始值")


class StrategyEngine:
    """策略引擎 - 管理策略匹配和动作执行"""

    def __init__(self, config: Config, executor: ActionExecutor, analyzer: FrequencyAnalyzer,
                 screen_capture=None, ocr_engine=None, adaptive_tuner=None):
        self.config = config
        self.executor = executor
        self.analyzer = analyzer
        self.screen_capture = screen_capture
        self.ocr_engine = ocr_engine
        self.adaptive_tuner = adaptive_tuner
        self.VERSION = getattr(config, '_version', '1.1.0')
        self.last_trigger_time = 0
        self.last_alert_time = 0
        self.trigger_history = []
        self.emergency_stop_triggered = False
        self.total_trigger_count = 0
        self.monitor_start_time = None

    def _record_trigger(self, strategy_key='', stuck_id=''):
        self.total_trigger_count += 1
        now = time.time()
        # 获取该策略的严重程度系数
        strategy = self.config.strategies.get(strategy_key, {})
        severity = strategy.get('severity', 1.0)
        self.trigger_history.append({
            'time': now,
            'strategy_key': strategy_key,
            'stuck_id': stuck_id,
            'severity': severity
        })
        # 检测时间窗口 = 触发冷却 × 阈值 × 2
        cooldown = self.config.data.get('frequency', {}).get('cooldown_seconds', 30)
        threshold = self.config.alert.get('alert_trigger_threshold', 6)
        detect_window = cooldown * threshold * 2
        # 动态计算窗口内的记录（不清理完整历史，用于统计报告）
        window_history = [t for t in self.trigger_history if now - t.get('time', t) <= detect_window]
        # 计算窗口内总系数
        total_severity = sum(t.get('severity', 1.0) for t in window_history)
        severity_threshold = self.config.alert.get('alert_severity_threshold', 10)
        return total_severity >= severity_threshold

    def get_stats(self) -> dict:
        if self.monitor_start_time is None:
            return {'runtime': 0, 'total_triggers': 0, 'triggers_per_hour': 0.0,
                    'total_rounds': 0, 'rounds_per_hour': 0.0, 'avg_round_time': 0.0}
        runtime = time.time() - self.monitor_start_time
        hours = runtime / 3600.0 if runtime > 0 else 0
        tph = self.total_trigger_count / hours if hours > 0 else 0.0

        # 各策略触发次数统计
        strategy_trigger_counts = {}
        for entry in self.trigger_history:
            key = entry.get('strategy_key', 'unknown')
            strategy_trigger_counts[key] = strategy_trigger_counts.get(key, 0) + 1

        # 卡死事件统计
        stuck_event_counts = {}
        for entry in self.trigger_history:
            sid = entry.get('stuck_id', 'unknown')
            stuck_event_counts[sid] = stuck_event_counts.get(sid, 0) + 1

        # 轮数统计
        round_events = getattr(self, '_round_events', {})
        total_rounds = len(round_events)
        rph = total_rounds / hours if hours > 0 else 0.0
        # 每轮平均用时（基于相邻轮次的时间差）
        avg_round_time = 0.0
        if len(round_events) >= 2:
            times = sorted(round_events.values())
            diffs = [times[i+1] - times[i] for i in range(len(times)-1)]
            avg_round_time = sum(diffs) / len(diffs) if diffs else 0.0

        # 从挂载的 monitor 获取轮数数据（如果自身没有则从 _game_monitor 取）
        if not round_events and hasattr(self, '_game_monitor'):
            gm_re = getattr(self._game_monitor, '_round_events', {})
            if gm_re:
                total_rounds = len(gm_re)
                rph = total_rounds / hours if hours > 0 else 0.0
                if len(gm_re) >= 2:
                    times = sorted(gm_re.values())
                    diffs = [times[i+1] - times[i] for i in range(len(times)-1)]
                    avg_round_time = sum(diffs) / len(diffs) if diffs else 0.0

        return {
            'runtime': runtime,
            'total_triggers': self.total_trigger_count,
            'triggers_per_hour': tph,
            'total_rounds': total_rounds,
            'rounds_per_hour': rph,
            'avg_round_time': avg_round_time,
            'strategy_trigger_counts': strategy_trigger_counts,
            'stuck_event_counts': stuck_event_counts,
            'trigger_history': self.trigger_history
        }

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        """将秒数格式化为 时:分:秒 格式"""
        if seconds <= 0:
            return "0秒"
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if h > 0:
            return f"{h}时{m}分{s}秒"
        elif m > 0:
            return f"{m}分{s}秒"
        else:
            return f"{s}秒"

    def _match_strategy(self, script_id: str) -> List[str]:
        matched = []
        strategies = self.config.strategies
        for key, strategy in strategies.items():
            exclude_ids = strategy.get('exclude_ids', [])
            # 排除匹配：如果包含排除关键词，则不匹配
            if exclude_ids and any(kw in script_id for kw in exclude_ids):
                continue
            match_ids = strategy.get('match_ids', [])
            # 正向匹配：如果设置了match_ids，则必须全部包含
            if match_ids and not all(kw in script_id for kw in match_ids):
                continue
            matched.append(key)
        return matched

    def check_and_trigger(self, current_id: str):
        self._last_trigger_occurred = False
        # 将完整OCR文本作为整体添加一次，而非逐行添加
        self.analyzer.add_sample(current_id, full_text=current_id)

        # 传入自适应参数覆盖
        adaptive_params = None
        if self.adaptive_tuner and self.adaptive_tuner.enabled:
            adaptive_params = self.adaptive_tuner._params
        result = self.analyzer.analyze(adaptive_params=adaptive_params)
        if not result.get('is_stuck'):
            return

        cooldown = self.config.data.get('frequency', {}).get('cooldown_seconds', 30)
        now = time.time()
        if now - self.last_trigger_time < cooldown:
            return

        self.last_trigger_time = now

        # 遍历所有卡死结果，每个结果对应自己的策略
        for r in result.get('results', []):
            strategy_key = r.get('_strategy_key', '')
            stuck_ids = r.get('stuck_ids', [])
            stuck_type = r.get('stuck_type', '')

            strategy = self.config.strategies.get(strategy_key)
            if not strategy:
                continue

            stuck_type_match = strategy.get('match_stuck_type', 'single')
            if stuck_type != stuck_type_match and stuck_type_match != 'any':
                continue

            # 自适应记录触发
            if self.adaptive_tuner:
                self.adaptive_tuner.record_trigger(strategy_key, r, current_id)

            logging.warning(f"触发策略 [{strategy.get('name', strategy_key)}] - {r.get('details', '')}")
            logging.info(f"[策略] 事件卡死: {stuck_ids[0] if stuck_ids else 'N/A'} | 占比: {r.get('top_ratio', 0):.1%} | 总计: {r.get('total', 0)}")

            actions = strategy.get('actions', [])
            if actions:
                self.executor._current_strategy_name = strategy.get('name', strategy_key)
                self.executor.execute_actions(actions)
            self._last_trigger_occurred = True

            # 触发后清空该策略对应的样本库，重新采集
            if strategy_key in self.analyzer.strategy_samples:
                del self.analyzer.strategy_samples[strategy_key]
                logging.info(f"[策略] 清空策略 '{strategy_key}' 的样本库，重新采集")

            if self._record_trigger(strategy_key=strategy_key,
                                   stuck_id=stuck_ids[0] if stuck_ids else ''):
                cooldown = self.config.data.get('frequency', {}).get('cooldown_seconds', 30)
                threshold = self.config.alert.get('alert_trigger_threshold', 6)
                detect_window = cooldown * threshold * 2
                severity_threshold = self.config.alert.get('alert_severity_threshold', 10)
                total_severity = sum(t.get('severity', 1.0) for t in self.trigger_history)
                trigger_count_in_window = len(self.trigger_history)
                logging.warning("=" * 50)
                logging.warning(f"警告: {detect_window}秒内累计系数 {total_severity:.1f} >= {severity_threshold}（{trigger_count_in_window}次触发），脚本可能完全卡死！发送报警")
                logging.warning("=" * 50)
                stats = self.get_stats()
                html_content = self._build_alert_html(
                    trigger_count=trigger_count_in_window,
                    detect_window=detect_window,
                    threshold=threshold,
                    stats=stats,
                    strategy_name=strategy.get('name', strategy_key),
                    stuck_type=stuck_type,
                    stuck_ids=stuck_ids,
                    result=result
                )
                self._send_alert("游戏监控-触发频率过高警告", html_content)
                break

    def _send_alert(self, title: str, content: str):
        """发送报警信息（异步，不阻塞）- content 为 HTML 格式"""
        # 报警冷却检查
        cooldown_minutes = int(self.config.alert.get('alert_cooldown_minutes', 15))
        cooldown_seconds = cooldown_minutes * 60
        now = time.time()
        if self.last_alert_time > 0 and (now - self.last_alert_time) < cooldown_seconds:
            remaining = cooldown_seconds - (now - self.last_alert_time)
            logging.info(f"[_send_alert] 报警冷却中，剩余 {int(remaining)} 秒，跳过发送")
            return
        self.last_alert_time = now

        alert_cfg = self.config.alert
        logging.info(f"[_send_alert] 准备发送报警，title={title}")
        logging.info(f"[_send_alert] 报警配置: pushplus_enabled={alert_cfg.get('pushplus_enabled', False)}, "
                     f"email_enabled={alert_cfg.get('email_enabled', False)}")

        # 邮件使用纯文本摘要
        plain_text = self._html_to_plain(content)

        def _send_pushplus():
            if not alert_cfg.get('pushplus_enabled', False):
                logging.info("[报警-PushPlus] 未启用，跳过")
                return
            token = alert_cfg.get('pushplus_token', '')
            if not token:
                logging.warning("[报警-PushPlus] 未配置 token，跳过")
                return
            logging.info("[报警-PushPlus] 开始发送")
            try:
                import urllib.request
                url = 'http://www.pushplus.plus/send'
                data = json.dumps({
                    'token': token, 'title': title,
                    'content': content,
                    'template': 'html'
                }).encode('utf-8')
                req = urllib.request.Request(url, data=data,
                                              headers={'Content-Type': 'application/json'},
                                              method='POST')
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = resp.read().decode('utf-8')
                    logging.info(f"[报警-PushPlus] 发送成功: {result}")
            except Exception as e:
                logging.error(f"[报警-PushPlus] 发送失败: {e}")

        def _send_email():
            if not alert_cfg.get('email_enabled', False):
                logging.info("[报警-邮件] 未启用，跳过")
                return
            smtp_server = alert_cfg.get('email_smtp_server', '')
            smtp_port = int(alert_cfg.get('email_smtp_port', 465))
            use_ssl = alert_cfg.get('email_use_ssl', True)
            user = alert_cfg.get('email_user', '')
            password = alert_cfg.get('email_password', '')
            to_addr = alert_cfg.get('email_to', '')
            if not all([smtp_server, user, password, to_addr]):
                logging.warning("[报警-邮件] 配置不完整，跳过")
                return
            logging.info(f"[报警-邮件] 开始发送 -> {to_addr}")
            try:
                import smtplib
                from email.mime.text import MIMEText
                from email.header import Header
                msg = MIMEText(plain_text, 'plain', 'utf-8')
                msg['Subject'] = Header(title, 'utf-8')
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
                logging.info(f"[报警-邮件] 发送成功 -> {to_addr}")
            except Exception as e:
                logging.error(f"[报警-邮件] 发送失败: {e}")

        threading.Thread(target=_send_pushplus, daemon=True).start()
        threading.Thread(target=_send_email, daemon=True).start()

    def _build_alert_html(self, trigger_count, detect_window, threshold, stats,
                          strategy_name, stuck_type, stuck_ids, result):
        """构建 HTML 格式的报警内容"""
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 上传异常截图到图床
        screenshot_url = ''
        screenshot_path = getattr(self.executor, '_last_screenshot_path', '')
        if screenshot_path and os.path.isfile(screenshot_path):
            screenshot_url = self.executor.upload_screenshot_to_imgbb(image_path=screenshot_path)
        screenshot_html = ''
        if screenshot_url:
            screenshot_html = f'''
    <div style="background:#0f3460;border-radius:12px;padding:16px;margin-bottom:16px;">
      <h3 style="color:#53a8b6;margin:0 0 12px 0;">📷 游戏截图</h3>
      <div style="text-align:center;">
        <img src="{screenshot_url}" style="max-width:100%%;border-radius:8px;" />
      </div>
    </div>'''

        # 构建触发策略详情
        strategies = self.config.strategies
        strategy_rows = ''
        for key, s in strategies.items():
            if key in ('default', 'stuck_fallback'):
                continue
            name = s.get('name', key)
            stype = s.get('match_stuck_type', '')
            match = ', '.join(s.get('match_ids', [])) or '全部'
            exclude = ', '.join(s.get('exclude_ids', [])) or '无'
            actions_desc = []
            for a in s.get('actions', []):
                atype = a.get('type', '')
                if atype == 'key_press':
                    actions_desc.append(f"按键 {a.get('key', '').upper()} x{a.get('presses', 1)}")
                elif atype == 'screenshot':
                    actions_desc.append("截图")
                elif atype == 'delay':
                    actions_desc.append(f"等待 {a.get('seconds', 0)}s")
                elif atype == 'mouse_click':
                    actions_desc.append("鼠标点击")
            actions_str = ' → '.join(actions_desc) if actions_desc else '无'
            highlight = 'background:#2a1a1a;' if key == strategy_name else ''
            sev = s.get('severity', 1.0)
            strategy_rows += f'''
      <tr style="{highlight}">
        <td style="padding:6px 8px;border-bottom:1px solid #1a1a2e;font-size:13px;">{name}</td>
        <td style="padding:6px 8px;border-bottom:1px solid #1a1a2e;font-size:13px;">{'单一' if stype == 'single' else '交替'}</td>
        <td style="padding:6px 8px;border-bottom:1px solid #1a1a2e;font-size:13px;color:#e94560;font-weight:bold;">{sev}</td>
        <td style="padding:6px 8px;border-bottom:1px solid #1a1a2e;font-size:13px;">{match}</td>
        <td style="padding:6px 8px;border-bottom:1px solid #1a1a2e;font-size:13px;">{exclude}</td>
        <td style="padding:6px 8px;border-bottom:1px solid #1a1a2e;font-size:13px;">{actions_str}</td>
      </tr>'''

        # 卡死详情
        stuck_detail = ''
        if result:
            counts = result.get('counts', {})
            top_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]
            detail_rows = ''
            for sid, cnt in top_items:
                pct = cnt / result.get('total', 1) * 100
                bar_color = '#e94560' if pct > 50 else '#53a8b6'
                detail_rows += f'''
        <tr>
          <td style="padding:4px 8px;color:#ccc;font-size:12px;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{sid}</td>
          <td style="padding:4px 8px;font-size:12px;">{cnt} ({pct:.1f}%%)</td>
          <td style="padding:4px 8px;width:40%%;">
            <div style="background:#1a1a2e;border-radius:4px;height:8px;overflow:hidden;">
              <div style="background:{bar_color};height:100%%;width:{pct}%%;border-radius:4px;"></div>
            </div>
          </td>
        </tr>'''
            stuck_detail = f'''
    <div style="background:#0f3460;border-radius:12px;padding:16px;margin-bottom:16px;">
      <h3 style="color:#53a8b6;margin:0 0 12px 0;">🔍 卡死分析</h3>
      <p style="color:#e94560;margin:0 0 8px 0;font-size:13px;">{result.get('details', '')}</p>
      <table style="width:100%%;border-collapse:collapse;">
        <tr style="color:#888;font-size:11px;">
          <th style="padding:4px 8px;text-align:left;">事件ID</th>
          <th style="padding:4px 8px;text-align:left;">次数</th>
          <th style="padding:4px 8px;text-align:left;">占比</th>
        </tr>
        {detail_rows}
      </table>
    </div>'''

        html = f'''<div style="background:#1a1a2e;color:#e0e0e0;padding:20px;font-family:'Microsoft YaHei',sans-serif;">
  <div style="background:#16213e;border-radius:12px;padding:20px;margin-bottom:16px;">
    <h2 style="color:#e94560;margin:0 0 8px 0;">⚠️ 脚本卡死报警</h2>
    <p style="color:#aaa;margin:0;font-size:13px;">SMD游戏监控程序 V{self.VERSION} | {now_str}</p>
  </div>
{screenshot_html}
{stuck_detail}
  <div style="background:#0f3460;border-radius:12px;padding:16px;margin-bottom:16px;">
    <h3 style="color:#53a8b6;margin:0 0 12px 0;">📊 运行统计</h3>
    <table style="width:100%%;border-collapse:collapse;font-size:14px;">
      <tr><td style="padding:8px;color:#aaa;border-bottom:1px solid #1a1a2e;">运行时间</td><td style="padding:8px;border-bottom:1px solid #1a1a2e;">{self._fmt_time(stats['runtime'])}</td></tr>
      <tr><td style="padding:8px;color:#aaa;border-bottom:1px solid #1a1a2e;">总触发次数</td><td style="padding:8px;color:#e94560;font-weight:bold;border-bottom:1px solid #1a1a2e;">{stats['total_triggers']} 次</td></tr>
      <tr><td style="padding:8px;color:#aaa;border-bottom:1px solid #1a1a2e;">触发频率</td><td style="padding:8px;border-bottom:1px solid #1a1a2e;">{stats['triggers_per_hour']:.1f} 次/时</td></tr>
      <tr><td style="padding:8px;color:#aaa;">当前策略</td><td style="padding:8px;color:#4ecca3;">{strategy_name}</td></tr>
    </table>
  </div>
  <div style="background:#0f3460;border-radius:12px;padding:16px;">
    <h3 style="color:#53a8b6;margin:0 0 12px 0;">📋 触发策略配置</h3>
    <div style="overflow-x:auto;">
      <table style="width:100%%;border-collapse:collapse;min-width:500px;">
        <tr style="color:#888;font-size:11px;">
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">策略名称</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">类型</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">系数</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">匹配词</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">排除词</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">执行动作</th>
        </tr>
        {strategy_rows}
      </table>
    </div>
  </div>
  <div style="text-align:center;padding:12px;color:#666;font-size:12px;">
    SMD游戏监控程序 V{self.VERSION}
  </div>
</div>'''
        return html

    @staticmethod
    def _html_to_plain(html):
        """简单提取 HTML 中的文本内容，用于邮件纯文本发送"""
        text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'</(p|div|tr|h[1-6])>', '\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _build_stats_report_html(self) -> str:
        """构建运行统计报告 HTML"""
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        stats = self.get_stats()

        # 截取当前游戏全窗口画面并上传
        screenshot_html = ''
        try:
            full_shot = self.screen_capture.capture_full_window()
            if full_shot:
                screenshot_url = self.executor.upload_screenshot_to_imgbb(image_data=full_shot)
                if screenshot_url:
                    # 缩略图用 display:none 隐藏原图，点击打开大图
                    screenshot_html = f'''
  <div style="background:#0f3460;border-radius:12px;padding:16px;margin-bottom:16px;">
    <h3 style="color:#53a8b6;margin:0 0 10px 0;">📷 当前游戏画面</h3>
    <div style="text-align:center;">
      <a href="{screenshot_url}" target="_blank">
        <img src="{screenshot_url}" style="max-width:100%%;border-radius:8px;cursor:pointer;" />
      </a>
    </div>
    <p style="text-align:center;margin:6px 0 0;font-size:11px;color:#666;">点击图片查看大图</p>
  </div>'''
        except Exception as e:
            logging.debug(f"[统计报告] 截图上传失败: {e}")
        runtime = stats['runtime']
        total_triggers = stats['total_triggers']
        tph = stats['triggers_per_hour']
        total_rounds = stats.get('total_rounds', 0)
        rph = stats.get('rounds_per_hour', 0.0)
        avg_rt = stats.get('avg_round_time', 0.0)
        avg_text = self._fmt_time(avg_rt) if avg_rt > 0 else '未知'

        # 从OCR文本中提取当前轮数（优先从 _game_monitor 获取）
        gm_round = getattr(self, '_game_monitor', None)
        if gm_round:
            current_round = getattr(gm_round, '_last_known_round', None) or '未知'
        else:
            current_round = getattr(self, '_last_known_round', None) or '未知'
        round_text = str(current_round) if current_round != '未知' else '未知'

        # 策略触发统计（只显示名称+次数+进度条，不要占比%列）
        strategy_counts = stats.get('strategy_trigger_counts', {})
        strategies = self.config.strategies
        strategy_rows = ''
        for key, count in sorted(strategy_counts.items(), key=lambda x: x[1], reverse=True):
            name = strategies.get(key, {}).get('name', key)
            pct = count / total_triggers * 100 if total_triggers > 0 else 0
            strategy_rows += f'''
      <tr>
        <td style="padding:6px 8px;border-bottom:1px solid #1a1a2e;font-size:13px;">{name}</td>
        <td style="padding:6px 8px;border-bottom:1px solid #1a1a2e;font-size:13px;text-align:center;">{count} 次</td>
        <td style="padding:6px 8px;border-bottom:1px solid #1a1a2e;width:45%%;">
          <div style="background:#1a1a2e;border-radius:4px;height:8px;overflow:hidden;">
            <div style="background:#4ecca3;height:100%%;width:{pct}%%;border-radius:4px;"></div>
          </div>
        </td>
      </tr>'''

        # 卡死事件统计（只显示事件ID+次数+进度条，不要%）
        event_counts = stats.get('stuck_event_counts', {})
        event_rows = ''
        for sid, count in sorted(event_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            pct = count / total_triggers * 100 if total_triggers > 0 else 0
            event_rows += f'''
      <tr>
        <td style="padding:5px 8px;color:#ccc;font-size:12px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{sid}</td>
        <td style="padding:5px 8px;font-size:12px;text-align:center;">{count} 次</td>
        <td style="padding:5px 8px;width:40%%;">
          <div style="background:#1a1a2e;border-radius:4px;height:8px;overflow:hidden;">
            <div style="background:#e94560;height:100%%;width:{pct}%%;border-radius:4px;"></div>
          </div>
        </td>
      </tr>'''

        # 当前样本库分析
        analysis_rows = ''
        for skey, samples in self.analyzer.strategy_samples.items():
            if skey == '_unmatched':
                continue
            sname = strategies.get(skey, {}).get('name', skey)
            s_cfg = strategies.get(skey, {})
            s_min = s_cfg.get('min_samples', self.analyzer.min_samples)
            status = '✅' if len(samples) >= s_min else '⏳'
            # Top样本ID（缩短显示，去掉"当前事件-"前缀）
            ids = [sid for _, sid in samples]
            id_counts = Counter(ids)
            top3 = id_counts.most_common(3)
            top_lines_list = []
            for sid, c in top3:
                short = sid.replace('当前事件-', '').replace('当前', '')[0:12]
                top_lines_list.append(f'• {short}={c}')
            top_lines = '<br>'.join(top_lines_list) if top_lines_list else '暂无'
            analysis_rows += f'''
      <tr>
        <td style="padding:4px 6px;color:#ccc;font-size:12px;white-space:nowrap;vertical-align:middle;">{status} {sname}</td>
        <td style="padding:4px 6px;font-size:12px;text-align:center;white-space:nowrap;vertical-align:middle;width:60px;">{len(samples)}/{s_min}</td>
        <td style="padding:4px 6px;color:#888;font-size:11px;vertical-align:middle;white-space:nowrap;">{top_lines}</td>
      </tr>'''

        html = f'''<div style="background:#1a1a2e;color:#e0e0e0;padding:20px;font-family:'Microsoft YaHei',sans-serif;">
  <div style="background:#16213e;border-radius:12px;padding:20px;margin-bottom:16px;">
    <h2 style="color:#4ecca3;margin:0 0 8px 0;">📊 运行统计报告</h2>
    <p style="color:#aaa;margin:0;font-size:13px;">SMD游戏监控程序 V{self.VERSION} | {now_str}</p>
  </div>
{screenshot_html}
  <div style="background:#0f3460;border-radius:12px;padding:16px;margin-bottom:16px;">
    <h3 style="color:#53a8b6;margin:0 0 12px 0;">⏱ 基本统计</h3>
    <table style="width:100%%;border-collapse:collapse;font-size:14px;">
      <tr><td style="padding:8px;color:#aaa;border-bottom:1px solid #1a1a2e;">运行时间</td><td style="padding:8px;border-bottom:1px solid #1a1a2e;">{self._fmt_time(runtime)}</td></tr>
      <tr><td style="padding:8px;color:#aaa;border-bottom:1px solid #1a1a2e;">当前轮数</td><td style="padding:8px;border-bottom:1px solid #1a1a2e;">{round_text}</td></tr>
      <tr><td style="padding:8px;color:#aaa;border-bottom:1px solid #1a1a2e;">总轮数</td><td style="padding:8px;border-bottom:1px solid #1a1a2e;">{total_rounds} 轮</td></tr>
      <tr><td style="padding:8px;color:#aaa;border-bottom:1px solid #1a1a2e;">轮数效率</td><td style="padding:8px;border-bottom:1px solid #1a1a2e;">{rph:.1f} 轮/时</td></tr>
      <tr><td style="padding:8px;color:#aaa;border-bottom:1px solid #1a1a2e;">每轮用时</td><td style="padding:8px;border-bottom:1px solid #1a1a2e;">{avg_text}</td></tr>
      <tr><td style="padding:8px;color:#aaa;border-bottom:1px solid #1a1a2e;">已触发策略</td><td style="padding:8px;color:#e94560;font-weight:bold;border-bottom:1px solid #1a1a2e;">{total_triggers} 次</td></tr>
      <tr><td style="padding:8px;color:#aaa;">触发频率</td><td style="padding:8px;">{tph:.1f} 次/时</td></tr>
    </table>
  </div>

  <div style="background:#0f3460;border-radius:12px;padding:16px;margin-bottom:16px;">
    <h3 style="color:#53a8b6;margin:0 0 12px 0;">📋 策略触发统计</h3>
    <table style="width:100%%;border-collapse:collapse;">
      <tr style="color:#888;font-size:11px;">
        <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">策略名称</th>
        <th style="padding:6px 8px;text-align:center;border-bottom:1px solid #1a1a2e;">次数</th>
        <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #1a1a2e;"></th>
      </tr>
      {strategy_rows if strategy_rows else '<tr><td style="padding:8px;color:#666;" colspan="3">暂无触发记录</td></tr>'}
    </table>
  </div>

  <div style="background:#0f3460;border-radius:12px;padding:16px;margin-bottom:16px;">
    <h3 style="color:#53a8b6;margin:0 0 12px 0;">🔍 卡死事件统计</h3>
    <table style="width:100%%;border-collapse:collapse;">
      <tr style="color:#888;font-size:11px;">
        <th style="padding:5px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">事件ID</th>
        <th style="padding:5px 8px;text-align:center;border-bottom:1px solid #1a1a2e;">次数</th>
        <th style="padding:5px 8px;text-align:left;border-bottom:1px solid #1a1a2e;"></th>
      </tr>
      {event_rows if event_rows else '<tr><td style="padding:8px;color:#666;" colspan="3">暂无卡死记录</td></tr>'}
    </table>
  </div>

  <div style="background:#0f3460;border-radius:12px;padding:16px;margin-bottom:16px;">
    <h3 style="color:#53a8b6;margin:0 0 12px 0;">📈 当前样本库</h3>
    <table style="width:100%%;border-collapse:collapse;table-layout:fixed;">
      <col style="width:34%%;">
      <col style="width:20%%;">
      <col style="width:46%%;">
      <tr style="color:#888;font-size:11px;">
        <th style="padding:5px 6px;text-align:left;border-bottom:1px solid #1a1a2e;white-space:nowrap;">策略</th>
        <th style="padding:5px 6px;text-align:center;border-bottom:1px solid #1a1a2e;white-space:nowrap;">样本/最小</th>
        <th style="padding:5px 6px;text-align:left;border-bottom:1px solid #1a1a2e;white-space:nowrap;">Top样本</th>
      </tr>
      {analysis_rows if analysis_rows else '<tr><td style="padding:8px;color:#666;" colspan="3">暂无样本</td></tr>'}
    </table>
  </div>

  <div style="text-align:center;padding:12px;color:#666;font-size:12px;">
    SMD游戏监控程序 V{self.VERSION}
  </div>
</div>'''
        return html

    def _send_stats_report(self):
        """发送运行统计报告（定期调用）"""
        # 检查统计报告时间窗口
        srt = self.config.stats_report_time
        if srt.get('enabled', False):
            now_dt = datetime.now()
            start_str = srt.get('start_time', '00:00')
            end_str = srt.get('end_time', '24:00')
            try:
                start_h, start_m = int(start_str.split(':')[0]), int(start_str.split(':')[1])
                end_h, end_m = int(end_str.split(':')[0]), int(end_str.split(':')[1])
                now_minutes = now_dt.hour * 60 + now_dt.minute
                start_minutes = start_h * 60 + start_m
                end_minutes = end_h * 60 + end_m
                if not (start_minutes <= now_minutes < end_minutes):
                    logging.info(f"[统计报告] 当前时间{now_dt.strftime('%H:%M')}不在报告窗口({start_str}-{end_str})内，跳过")
                    return
            except Exception:
                pass
        if not self.config.alert.get('stats_report_enabled', False):
            return
        # 检查是否有可用的推送渠道
        if not (self.config.alert.get('pushplus_enabled', False) or
                self.config.alert.get('email_enabled', False)):
            return

        now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
        html_content = self._build_stats_report_html()
        title = f"📊 运行统计报告 - {now_str}"
        logging.info(f"[统计报告] 开始发送: {title}")

        # 直接复用 _send_alert 的发送逻辑，但不受报警冷却限制
        alert_cfg = self.config.alert
        plain_text = self._html_to_plain(html_content)

        def _send_pushplus():
            if not alert_cfg.get('pushplus_enabled', False):
                return
            token = alert_cfg.get('pushplus_token', '')
            if not token:
                return
            import urllib.request
            try:
                url = 'http://www.pushplus.plus/send'
                data = json.dumps({
                    'token': token, 'title': title,
                    'content': html_content,
                    'template': 'html'
                }).encode('utf-8')
                req = urllib.request.Request(url, data=data,
                                              headers={'Content-Type': 'application/json'},
                                              method='POST')
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = resp.read().decode('utf-8')
                    logging.info(f"[统计报告-PushPlus] 发送成功")
            except Exception as e:
                logging.error(f"[统计报告-PushPlus] 发送失败: {e}")

        def _send_email():
            if not alert_cfg.get('email_enabled', False):
                return
            smtp_server = alert_cfg.get('email_smtp_server', '')
            smtp_port = int(alert_cfg.get('email_smtp_port', 465))
            use_ssl = alert_cfg.get('email_use_ssl', True)
            user = alert_cfg.get('email_user', '')
            password = alert_cfg.get('email_password', '')
            to_addr = alert_cfg.get('email_to', '')
            if not all([smtp_server, user, password, to_addr]):
                return
            try:
                import smtplib
                from email.mime.text import MIMEText
                from email.header import Header
                msg = MIMEText(plain_text, 'plain', 'utf-8')
                msg['Subject'] = Header(title, 'utf-8')
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
                logging.info(f"[统计报告-邮件] 发送成功 -> {to_addr}")
            except Exception as e:
                logging.error(f"[统计报告-邮件] 发送失败: {e}")

        threading.Thread(target=_send_pushplus, daemon=True).start()
        threading.Thread(target=_send_email, daemon=True).start()

    def _emergency_stop(self):
        self.emergency_stop_triggered = True
        logging.error("=" * 60)
        logging.error("检测到脚本完全卡死！执行紧急停止")
        logging.error("=" * 60)

        # 发送报警
        stats = self.get_stats()
        html_content = self._build_alert_html(
            trigger_count=self.total_trigger_count,
            detect_window=0,
            threshold=0,
            stats=stats,
            strategy_name="紧急停止",
            stuck_type="emergency",
            stuck_ids=[],
            result=None
        )
        self._send_alert("游戏监控-紧急停止", html_content)

        max_attempts = 10
        for attempt in range(1, max_attempts + 1):
            self.executor.execute_action({'type': 'key_press', 'key': 'p', 'presses': 1})
            logging.error(f"[紧急停止] 第 {attempt}/{max_attempts} 次发送P键...")
            time.sleep(1.5)

            if self.screen_capture and self.ocr_engine:
                try:
                    screenshot = self.screen_capture.capture_region()
                    raw_result = self.ocr_engine.recognize(screenshot)
                    if '悬赏执行' not in raw_result:
                        logging.error("[紧急停止] 未检测到'悬赏执行'，脚本已成功停止。监控即将停止。")
                        return
                except Exception as e:
                    logging.warning(f"[紧急停止] 截图OCR检查失败: {e}")
            else:
                time.sleep(1.0)
                return

        logging.error("[紧急停止] 超过最大尝试次数(10次)，脚本仍未停止。监控即将停止。")


class GameMonitor:
    """游戏监控主类"""

    def __init__(self, config_path: str):
        self.config = Config(config_path)
        self.config_path = config_path

        # 确保日志级别为 DEBUG（GUI中通过勾选控制显示）
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)

        self.screen_capture = ScreenCapture(self.config)
        self.ocr_engine = OCREngine(self.config)
        self.executor = ActionExecutor(self.config)
        # 将图床API key传递给executor
        self.executor._imgbb_api_key = self.config.alert.get('imgbb_api_key', '')
        self.frequency_analyzer = FrequencyAnalyzer(self.config)
        self.analyzer = self.frequency_analyzer
        self.adaptive_tuner = AdaptiveTuner(self.config)
        self.strategy_engine = StrategyEngine(self.config, self.executor, self.frequency_analyzer,
                                               self.screen_capture, self.ocr_engine,
                                               adaptive_tuner=self.adaptive_tuner)
        self.config._version = getattr(self, 'VERSION', '1.1.0')
        self.strategy_engine.VERSION = self.config._version
        self.strategy_engine._game_monitor = self  # 引用，用于获取轮数等数据
        self.running = False
        self.paused = False
        self.current_script_id = ""
        self.stable_count = 0
        self.tk_root = None

        # 统计报告追踪
        self._last_stats_report_time = 0
        self._round_events = {}  # {轮数: 时间戳}
        self._last_known_round = None
        self._last_memory_check = 0

    def _get_ocr_engine(self):
        """获取可用的OCR引擎"""
        if hasattr(self, 'ocr_engine') and self.ocr_engine:
            return self.ocr_engine
        return None

    def start(self):
        self.start_time = time.time()
        self.strategy_engine.monitor_start_time = time.time()
        self.strategy_engine.total_trigger_count = 0
        self.strategy_engine.trigger_history = []
        self._last_stats_report_time = time.time()
        self._round_events = {}
        self._last_known_round = None
        # 初始化重启器
        self.restarter = GameRestarter(self.config, self, tk_root=getattr(self, 'tk_root', None))

        # 每次开始监控时创建新的日志文件（带时间戳），保留最近10个
        root_logger = logging.getLogger()
        config_abs = os.path.abspath(self.config_path)
        # 如果 config_path 在子目录（如 configs/default.json），取父级的父级
        parent = os.path.dirname(config_abs)
        if os.path.basename(parent) in ('configs', 'config'):
            base_dir = os.path.dirname(parent)
        else:
            base_dir = parent
        logs_dir = os.path.join(base_dir, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = os.path.join(logs_dir, f'game_monitor_{ts}.log')

        # 移除旧的文件 handler
        for h in list(root_logger.handlers):
            if isinstance(h, logging.FileHandler):
                h.close()
                root_logger.removeHandler(h)

        # 添加新的文件 handler
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        root_logger.addHandler(fh)

        # 清理旧日志，只保留最近10个
        try:
            all_logs = sorted(
                [f for f in os.listdir(logs_dir) if f.startswith('game_monitor_') and f.endswith('.log')],
                key=lambda x: os.path.getmtime(os.path.join(logs_dir, x))
            )
            for old in all_logs[:-10]:
                os.remove(os.path.join(logs_dir, old))
        except Exception:
            pass

        logging.info(f"[日志] 新建监控日志: {log_file}")

        if self.config.window.get('use_window', False):
            if not self.screen_capture.find_window():
                # 恢复标记：跳过重启触发
                if getattr(self, '_restart_recovery', False):
                    logging.info("[GameMonitor] 恢复模式，跳过重启触发")
                    self._restart_recovery = False
                    return
                logging.warning("未找到游戏窗口，尝试触发重启流程")
                # 检查重启器是否启用
                if hasattr(self, 'restarter') and self.restarter and self.restarter.enabled:
                    self.restarter.start_restart('启动时游戏窗口不存在', auto_restart=True)
                    # 等待重启完成（最多等10分钟）
                    if hasattr(self.restarter, '_restart_thread') and self.restarter._restart_thread:
                        self.restarter._restart_thread.join(timeout=600)
                    # 重启等待期间用户可能已停止监控
                    if not self.running:
                        logging.info("[GameMonitor] 监控已被用户停止，不继续启动")
                        return
                    # 重启后重新查找窗口
                    if not self.screen_capture.find_window():
                        logging.error("重启后仍未找到游戏窗口，停止监控")
                        return
                    logging.info("重启后成功找到游戏窗口")
                else:
                    logging.error("重启功能未启用，停止监控")
                    return
            hwnd = self.screen_capture.window_hwnd
            if hwnd:
                offset = (self.screen_capture.window_rect[0], self.screen_capture.window_rect[1]) if self.screen_capture.window_rect else None
                self.executor.set_window(hwnd, offset)

        self.running = True
        self._monitor_loop()

    def stop(self):
        self.running = False
        # 停止重启流程（如果正在进行）
        if hasattr(self, 'restarter') and self.restarter:
            self.restarter.stop_restart()
        logging.info("[GameMonitor] stop() 已调用，running=False")

    def pause(self):
        self.paused = True
        logging.info("监控已暂停")

    def resume(self):
        self.paused = False
        logging.info("监控已恢复")

    def _monitor_loop(self):
        check_interval = float(self.config.monitor.get('check_interval', 1.0))
        min_stable = self.config.debounce.get('min_stable_frames', 2)
        freq_cfg = self.config.data.get('frequency', {})

        logging.info("=" * 50)
        logging.info("SMD游戏监控已启动 [频率检测模式 + 自适应调整]")
        logging.info(f"  监控区域: {self.config.monitor.get('region', {})}")
        logging.info(f"  检查间隔: {check_interval}s (自适应可调)")
        logging.info(f"  统计窗口: {freq_cfg.get('window_seconds', 60)}s")
        logging.info(f"  自适应调整: {'已启用' if self.adaptive_tuner.enabled else '已禁用'}")
        if self.adaptive_tuner.enabled:
            logging.info(f"  暖身期: {self.adaptive_tuner._warmup_seconds}s")
        hotkeys = self.config.hotkeys
        logging.info(f"  热键: {hotkeys.get('start_stop', 'F8')}=开始/停止 | {hotkeys.get('pause_resume', 'F10')}=暂停/恢复")
        logging.info("=" * 50)

        loop_count = 0
        while self.running:
            loop_count += 1

            if self.strategy_engine.emergency_stop_triggered:
                logging.error("[紧急停止] 监控循环因脚本完全卡死而终止")
                if self.adaptive_tuner and self.adaptive_tuner.enabled:
                    self.adaptive_tuner.record_false_negative('_emergency_stop')
                self.running = False
                break

            if self.paused:
                time.sleep(0.5)
                continue

            try:
                # 动态调整检查间隔
                if self.adaptive_tuner and self.adaptive_tuner.enabled:
                    check_interval = self.adaptive_tuner.get_check_interval()

                screenshot = self.screen_capture.capture_region()

                raw_result = self.ocr_engine.recognize(screenshot)

                # 自适应误报检测
                if self.adaptive_tuner and self.adaptive_tuner.enabled:
                    self.adaptive_tuner.verify_recent_triggers(raw_result)

                # 挂机条件检测
                idle_cfg = self.config.idle_settings
                if idle_cfg.get('enabled', False):
                    should_stop = False
                    stop_reason = ''
                    # 条件1: 运行时间
                    max_minutes = idle_cfg.get('stop_after_minutes', 0)
                    if max_minutes > 0 and (now - self.start_time) >= max_minutes * 60:
                        should_stop = True
                        stop_reason = f'运行时间达到{max_minutes}分钟'
                    # 条件2: 到达指定时间
                    stop_at = idle_cfg.get('stop_at_time', '')
                    if not should_stop and stop_at:
                        try:
                            target_h, target_m = int(stop_at.split(':')[0]), int(stop_at.split(':')[1])
                            now_dt = datetime.now()
                            if now_dt.hour == target_h and now_dt.minute >= target_m:
                                should_stop = True
                                stop_reason = f'到达指定时间{stop_at}'
                        except Exception:
                            pass
                    # 条件3: 总轮数
                    max_rounds = idle_cfg.get('stop_after_rounds', 0)
                    total_rounds = len(self._round_events)
                    if not should_stop and max_rounds > 0 and total_rounds >= max_rounds:
                        should_stop = True
                        stop_reason = f'总轮数达到{max_rounds}轮'
                    # 条件4: 执行次数
                    max_execs = idle_cfg.get('stop_after_executions', 0)
                    total_execs = stats.get('total_triggers', 0)
                    if not should_stop and max_execs > 0 and total_execs >= max_execs:
                        should_stop = True
                        stop_reason = f'执行次数达到{max_execs}次'

                    if should_stop:
                        logging.info(f"[挂机] {stop_reason}，自动停止监控")
                        # 按P键停止脚本
                        try:
                            self.executor._activate_window()
                            self.executor._send_key_action({'key': 'p', 'presses': 1, 'interval': 0.5})
                        except Exception:
                            pass
                        self.running = False
                        # 取消挂机启用，避免下次启动自动停止
                        idle_cfg['enabled'] = False
                        break

                # 追踪轮数变化（支持多种格式：当前轮数12 / 当前轮数:12 / 当前轮数-12等）
                for line in raw_result.split('\n'):
                    line = line.strip()
                    # 匹配 "当前轮数" 后面跟着数字的各种格式
                    m = re.search(r'当前轮数[:：\-\s]*(\d+)', line)
                    if m:
                        new_round = int(m.group(1))
                        if self._last_known_round is not None:
                            diff = new_round - self._last_known_round
                            if diff < 0:
                                # 轮数回退（如10→1），OCR误识别，忽略但不更新
                                logging.debug(f"[轮数] 忽略轮数回退: {self._last_known_round} -> {new_round}（可能OCR误识别）")
                                break
                            if diff == 0:
                                # 相同轮数，不记录
                                break
                            if diff > 5:
                                # 跳变过大（>5），极可能是OCR误识别，忽略
                                logging.debug(f"[轮数] 忽略过大跳变: {self._last_known_round} -> {new_round}（差距{diff}，可能OCR误识别）")
                                break
                            if diff > 1:
                                # 跳变2-5：需要额外校验，记录待确认
                                if not hasattr(self, '_pending_round'):
                                    self._pending_round = None
                                if self._pending_round != new_round:
                                    self._pending_round = new_round
                                    self._pending_round_count = 1
                                    logging.debug(f"[轮数] 跳变待确认: {self._last_known_round} -> {new_round}（第1次检测）")
                                    break
                                else:
                                    self._pending_round_count += 1
                                    if self._pending_round_count >= 3:
                                        # 连续3次确认，接受跳变
                                        logging.info(f"[轮数] 跳变已确认: {self._last_known_round} -> {new_round}（连续3次检测）")
                                        for r in range(self._last_known_round + 1, new_round + 1):
                                            if r not in self._round_events:
                                                self._round_events[r] = time.time()
                                        logging.info(f"[轮数] 检测到轮数跳变: {self._last_known_round} -> {new_round}，补记{diff}轮")
                                        self._pending_round = None
                                        self._pending_round_count = 0
                                    else:
                                        logging.debug(f"[轮数] 跳变待确认: {self._last_known_round} -> {new_round}（第{self._pending_round_count}次检测）")
                                    break
                            # diff == 1: 正常+1
                            logging.info(f"[轮数] 检测到轮数变化: {self._last_known_round} -> {new_round}")
                            self._round_events[new_round] = time.time()
                            self._pending_round = None
                            self._pending_round_count = 0
                        self._last_known_round = new_round
                        break
                else:
                    # 未匹配到
                    if loop_count % 50 == 0:  # 每50轮才记录一次，减少日志
                        lines_with_round = [l for l in raw_result.split(chr(10)) if '轮' in l]
                        if not lines_with_round:
                            # 如果完全没有"轮"字，输出前几行OCR文本用于排查
                            first_lines = [l.strip() for l in raw_result.split(chr(10))[:3] if l.strip()]
                            logging.debug(f"[轮数] OCR文本中无'轮'字，前3行: {first_lines}")
                        elif lines_with_round:
                            logging.debug(f"[轮数] OCR未识别到轮数，相关文本: {lines_with_round[:3]}")

                if raw_result == self.current_script_id or not self.current_script_id:
                    self.stable_count += 1
                else:
                    self.stable_count = 1
                    self.current_script_id = raw_result
                    # OCR变化，通知自适应器确认真触发
                    if self.adaptive_tuner and self.adaptive_tuner.enabled:
                        self.adaptive_tuner.record_recovery('all', raw_result)

                if self.stable_count >= min_stable and raw_result:
                    self.strategy_engine.check_and_trigger(raw_result)
                    # 检查重启条件
                    if hasattr(self, 'restarter') and self.restarter:
                        cooldown_min = int(self.config.alert.get('alert_cooldown_minutes', 15))
                        cd_secs = cooldown_min * 60
                        in_cd = (time.time() - self.strategy_engine.last_alert_time) < cd_secs
                        should_restart, reason = self.restarter.check_trigger_conditions(
                            raw_result, 
                            trigger_occurred=self.strategy_engine._last_trigger_occurred if hasattr(self.strategy_engine, '_last_trigger_occurred') else False,
                            in_cooldown=in_cd
                        )
                        if should_restart:
                            self.restarter.start_restart(reason, auto_restart=True)
                            break

                # 分析频率降低：每5轮分析一次（节省CPU）
                if loop_count % 5 == 0:
                    result = self.analyzer.analyze()
                    now = time.time()
                    if not hasattr(self, '_last_status_print') or now - self._last_status_print >= 10:
                        self._last_status_print = now
                        queue_info = ', '.join([f"{k}={len(v)}" for k, v in self.analyzer.strategy_samples.items() if k != '_unmatched'])
                        if result.get('is_stuck') and result.get('results'):
                            details_list = [r.get('details', '') for r in result['results']]
                            details_str = ' | '.join(details_list)
                        else:
                            total_samples = result.get('total_samples', sum(len(s) for s in self.analyzer.strategy_samples.values()))
                            details_str = result.get('details', f'样本不足或未达到阈值 (总样本{total_samples})')
                        logging.info(f"[统计] {queue_info} | {details_str}")
                elif loop_count % 5 == 1:
                    now = time.time()
                    # 定期发送统计报告（不在分析轮中重复计算）
                    stats_interval = int(self.config.alert.get('stats_report_interval', 60)) * 60
                    if stats_interval > 0 and now - self._last_stats_report_time >= stats_interval:
                        self._last_stats_report_time = now
                        self.strategy_engine._send_stats_report()

                sleep_steps = max(1, int(check_interval / 0.1))
                for _ in range(sleep_steps):
                    if not self.running:
                        break
                    time.sleep(0.1)

                # 定期内存检查与释放（每60秒检查一次）
                now = time.time()
                if now - self._last_memory_check >= 60:
                    self._last_memory_check = now
                    self._check_and_release_memory()

            except Exception as e:
                import traceback
                logging.error(f"监控循环异常: {e}\n{traceback.format_exc()}")

        logging.info(f"[_monitor_loop] 循环已退出，共执行{loop_count}轮")

    def _get_process_memory_mb(self):
        """获取当前进程内存占用（MB），使用Windows API，无需psutil"""
        try:
            kernel32 = ctypes.windll.kernel32
            GetCurrentProcess = kernel32.GetCurrentProcess
            GetProcessMemoryInfo = kernel32.GetProcessMemoryInfo
            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_ulong),
                            ("PageFaultCount", ctypes.c_ulong),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]
            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = GetCurrentProcess()
            if GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                return pmc.WorkingSetSize / 1024 / 1024
        except Exception:
            pass
        return 0

    def _check_and_release_memory(self):
        """检查内存占用，超过阈值时执行释放"""
        threshold_mb = self.config.data.get('memory_threshold_mb', 200)
        current_mb = self._get_process_memory_mb()
        if current_mb <= 0:
            return
        if current_mb > threshold_mb:
            logging.info(f"[内存] 当前{current_mb:.1f}MB 超过阈值{threshold_mb}MB，执行内存释放")
            before = current_mb
            # 1. 强制垃圾回收
            gc.collect()
            # 2. 清理过旧的轮数记录（保留最近500轮）
            if len(self._round_events) > 500:
                sorted_rounds = sorted(self._round_events.keys())
                for r in sorted_rounds[:-500]:
                    del self._round_events[r]
            # 3. 清理分析器中的旧样本
            if hasattr(self, 'analyzer') and hasattr(self.analyzer, '_cleanup_old_samples'):
                self.analyzer._cleanup_old_samples()
            after = self._get_process_memory_mb()
            logging.info(f"[内存] 释放完成: {before:.1f}MB -> {after:.1f}MB")

    def setup_hotkeys(self, toggle_start_stop, toggle_pause_resume, exit_program):
        if not KEYBOARD_AVAILABLE:
            return
        hotkeys = self.config.hotkeys
        try:
            keyboard.add_hotkey(hotkeys.get('start_stop', 'F8'), toggle_start_stop)
            keyboard.add_hotkey(hotkeys.get('pause_resume', 'F10'), toggle_pause_resume)
            keyboard.add_hotkey(hotkeys.get('exit', 'F12'), exit_program)
            logging.info("全局热键已注册")
        except Exception as e:
            logging.warning(f"热键设置失败: {e}")


# Windows INPUT 结构体定义（用于 SendInput，GameRestarter 和 StrategyExecutor 共用）
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_size_t)]

class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort),
                ("wParamH", ctypes.c_ushort)]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]

class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUT_UNION)]

_INPUT_SIZE = ctypes.sizeof(_INPUT)


class GameRestarter:
    """游戏自动重启器 - 检测异常后自动重启游戏并恢复配置"""

    def __init__(self, config, game_monitor=None, tk_root=None):
        self.config = config
        self.game_monitor = game_monitor
        self.tk_root = tk_root
        self.restart_config = config.data.get('restart_settings', {})
        self.enabled = self.restart_config.get('enabled', False)
        self._recent_trigger_count = 0
        self._consecutive_cooldown_count = 0
        self._is_restarting = False
        self._stop_requested = False
        self._restart_thread = None
        # 恢复的配置截图（键名 -> PIL Image）
        self._saved_config_images = {}
        # 加载已保存的配置截图
        self._load_saved_configs()
        # 当前使用的SMD配置文件路径（可由主界面动态更新）
        self.smd_config_path = os.path.join(os.path.dirname(__file__), 'smd_config', 'smd_settings.json')
        # GUI当前选定的脚本（由主界面在启动重启前设置，特殊操作优先使用）
        self._gui_selected_script = ''
        self._gui_script_type = ''

        # OCR结果缓存（减少重复全屏OCR）
        self._ocr_cache = None  # (rect_tuple, ocr_items, timestamp)
        self._ocr_cache_ttl = 2.0  # 缓存有效期（秒）

        # 重试配置
        self._ocr_retry_count = 3  # 单个元素识别失败重试次数
        self._tab_retry_count = 2  # 标签页失败后重试次数
        self._tab_max_failures = 3  # 单个标签页内连续失败次数阈值，超过则重进标签页

        # 创建重启流程专用日志toast窗口
        self._init_toast_window()

    def _init_toast_window(self):
        """创建重启流程专用的左侧浮动日志toast窗口（不干扰游戏和音乐盒子）"""
        try:
            if self.tk_root:
                self._toast_root = self.tk_root
                self._toast_window = tk.Toplevel(self._toast_root)
            else:
                self._toast_root = tk.Tk()
                self._toast_root.withdraw()  # 隐藏主窗口
                self._toast_window = tk.Toplevel(self._toast_root)
            self._toast_window.overrideredirect(True)
            # 不抢焦点：允许其他窗口保持置顶
            self._toast_window.attributes('-topmost', False)
            # 左侧窄条
            sw = self._toast_root.winfo_screenwidth()
            sh = self._toast_root.winfo_screenheight()
            w, h = 380, min(500, sh - 100)
            x = 10
            y = (sh - h) // 2
            self._toast_window.geometry(f'{w}x{h}+{x}+{y}')
            self._toast_window.configure(bg='#1a1a2e')

            # 标题栏
            title_frame = tk.Frame(self._toast_window, bg='#16213e', height=24)
            title_frame.pack(fill=tk.X)
            title_frame.pack_propagate(False)
            tk.Label(title_frame, text=' SMD 重启日志', bg='#16213e', fg='#58a6ff',
                     font=('Microsoft YaHei UI', 8, 'bold'), anchor='w').pack(side=tk.LEFT, padx=5)

            # Text控件
            self._toast_text = tk.Text(self._toast_window, bg='#0a0a1a', fg='#00ff88',
                                       font=('Consolas', 9), wrap=tk.WORD, state=tk.DISABLED,
                                       relief=tk.FLAT, padx=8, pady=8)
            # 添加滚动条
            toast_scroll = tk.Scrollbar(self._toast_window, command=self._toast_text.yview)
            self._toast_text.configure(yscrollcommand=toast_scroll.set)
            self._toast_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            toast_scroll.pack(side=tk.RIGHT, fill=tk.Y)

            self._toast_window.withdraw()  # 初始隐藏

            # 记录游戏窗口句柄，显示toast时不抢焦点
            self._toast_game_hwnd = None
        except Exception as e:
            logging.warning(f"[重启] 创建toast窗口失败: {e}")
            self._toast_root = None
            self._toast_window = None
            self._toast_text = None

    def show_toast_log(self, msg):
        """在toast窗口追加一行日志（线程安全，不抢焦点）"""
        if not self._toast_root or not self._toast_text:
            return
        try:
            def _append():
                try:
                    if not self._toast_text or not self._toast_text.winfo_exists():
                        return
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    self._toast_text.config(state=tk.NORMAL)
                    self._toast_text.insert(tk.END, f"[{timestamp}] {msg}\n")
                    # 限制最大行数
                    total_lines = int(self._toast_text.index('end-1c').split('.')[0])
                    if total_lines > 300:
                        self._toast_text.delete('1.0', f'{total_lines - 300}.0')
                    self._toast_text.see(tk.END)
                    self._toast_text.config(state=tk.DISABLED)
                    # 确保窗口显示，但不抢焦点
                    if self._toast_window and self._toast_window.winfo_exists():
                        self._toast_window.deiconify()
                        self._toast_window.attributes('-topmost', False)
                except Exception:
                    pass
            self._toast_root.after(0, _append)
            # 保持Tk事件循环活跃（因为可能在非主线程调用）
            self._toast_root.update_idletasks()
        except Exception:
            pass

    def hide_toast(self):
        """隐藏/销毁toast窗口"""
        if not self._toast_root:
            return
        try:
            def _destroy():
                try:
                    if self._toast_window and self._toast_window.winfo_exists():
                        self._toast_window.destroy()
                    self._toast_text = None
                    self._toast_window = None
                except Exception:
                    pass
            self._toast_root.after(0, _destroy)
        except Exception:
            pass

    def _load_saved_configs(self):
        """从文件加载之前保存的配置截图"""
        import pickle
        save_dir = self.restart_config.get('config_images_dir', '')
        if not save_dir or not os.path.isdir(save_dir):
            return
        for fname in os.listdir(save_dir):
            if fname.endswith('.pkl'):
                key = fname[:-4]
                fpath = os.path.join(save_dir, fname)
                try:
                    with open(fpath, 'rb') as f:
                        img_data = pickle.load(f)
                    if isinstance(img_data, Image.Image):
                        self._saved_config_images[key] = img_data
                        logging.info(f"[重启] 加载配置截图: {key}")
                except Exception as e:
                    logging.warning(f"[重启] 加载配置截图失败 {fname}: {e}")

    def check_trigger_conditions(self, ocr_text, trigger_occurred, in_cooldown):
        """检查是否满足重启条件，返回 (should_restart, reason)"""
        if not self.enabled or self._is_restarting:
            return False, ''

        reasons = []

        # 条件1: 游戏进程消失（OCR完全无内容或窗口不存在）
        if self.game_monitor:
            sc = self.game_monitor.screen_capture
            if sc.window_hwnd and not ctypes.windll.user32.IsWindow(sc.window_hwnd):
                reasons.append('游戏窗口已消失')

        # 条件2: 触发策略次数激增（短时间内多次触发）
        if trigger_occurred:
            self._recent_trigger_count += 1
        else:
            self._recent_trigger_count = max(0, self._recent_trigger_count - 1)
        burst_threshold = self.restart_config.get('burst_trigger_count', 5)
        if self._recent_trigger_count >= burst_threshold:
            reasons.append(f'短时间触发{self._recent_trigger_count}次（阈值{burst_threshold}）')

        # 条件3: 报警冷却中仍然连续触发（说明问题持续存在）
        if in_cooldown and trigger_occurred:
            self._consecutive_cooldown_count += 1
        else:
            self._consecutive_cooldown_count = max(0, self._consecutive_cooldown_count - 1)
        cooldown_trigger_threshold = self.restart_config.get('cooldown_trigger_threshold', 10)
        if self._consecutive_cooldown_count >= cooldown_trigger_threshold:
            reasons.append(f'冷却中连续触发{self._consecutive_cooldown_count}次（阈值{cooldown_trigger_threshold}）')

        # 条件4: 紧急停止触发
        if self.game_monitor and hasattr(self.game_monitor, 'strategy_engine'):
            if self.game_monitor.strategy_engine.emergency_stop_triggered:
                reasons.append('紧急停止已触发')

        if reasons:
            return True, ' | '.join(reasons)
        return False, ''

    def start_restart(self, reason='', auto_restart=False):
        """在后台线程中执行重启流程（始终从阶段0开始）"""
        if self._is_restarting:
            return
        self._is_restarting = True
        self._stop_requested = False
        self._auto_restart = auto_restart
        logging.warning(f"[重启] ========== 开始重启流程 ==========")
        logging.warning(f"[重启] 触发原因: {reason}")
        self._restart_thread = threading.Thread(
            target=self._restart_flow, daemon=True)
        self._restart_thread.start()

    def stop_restart(self):
        """请求停止重启流程"""
        if self._is_restarting:
            self._stop_requested = True
            logging.warning("[重启] 收到停止请求，将在当前阶段完成后停止")

    def _restart_flow(self):
        """完整的重启流程（始终从阶段0开始），失败阶段自动重试"""
        try:
            self.show_toast_log("========== 开始重启流程 ==========")

            phases = [
                ('阶段0: 停止监控', self._phase_stop_monitor),
                ('阶段1: 关闭进程', self._phase_kill_processes),
                ('阶段2: 启动原力', self._phase_start_rundll32),
                ('阶段3: 启动游戏', self._phase_launch_game),
                ('阶段4: 等待原力加载', self._phase_wait_game_ready),
                ('阶段5+6: 进入游戏+恢复配置', self._phase_enter_game),
                ('阶段7: 恢复监控', self._phase_resume_monitor),
            ]

            phase_max_retries = 3  # 每个阶段最大重试次数

            for i, (phase_name, phase_func) in enumerate(phases):
                # 手动一键重启时跳过停止/恢复监控阶段
                if not self._auto_restart and i in (0, 6):
                    logging.info(f"[重启] 跳过 {phase_name}（手动重启不恢复监控）")
                    continue
                if self._stop_requested:
                    logging.warning(f"[重启] 停止请求已触发，跳过 {phase_name}")
                    self.show_toast_log(f"停止请求已触发，跳过 {phase_name}")
                    break

                # 执行阶段，失败时重试
                phase_ok = False
                for retry in range(phase_max_retries):
                    if self._stop_requested:
                        break
                    if retry > 0:
                        logging.info(f"[重启] {phase_name} 第{retry + 1}次重试...")
                        self.show_toast_log(f"{phase_name} 重试({retry + 1})")
                    result = phase_func()
                    # 阶段返回 None 或 True 表示成功
                    if result is None or result is True:
                        phase_ok = True
                        break
                    # False 表示失败，继续重试

                if not phase_ok and not self._stop_requested:
                    logging.error(f"[重启] {phase_name} 失败（已重试{phase_max_retries}次），终止流程")
                    self.show_toast_log(f"{phase_name} 失败，流程终止")
                    break

            if not self._stop_requested:
                logging.warning(f"[重启] ========== 重启流程完成 ==========")
                self.show_toast_log("========== 重启流程完成 ==========")
            else:
                logging.warning(f"[重启] ========== 重启流程已中止 ==========")
                self.show_toast_log("========== 重启流程已中止 ==========")
        except Exception as e:
            logging.error(f"[重启] 重启流程异常: {e}")
            import traceback
            logging.error(traceback.format_exc())
            self.show_toast_log(f"重启流程异常: {e}")
        finally:
            self._is_restarting = False
            self._stop_requested = False
            # 3秒后隐藏toast
            time.sleep(3)
            self.hide_toast()

    def start_quick_config(self):
        """一键配置：只执行阶段5+6（进游戏判断→按M打开地图→F11配置）"""
        if self._is_restarting:
            return
        self._is_restarting = True
        self._stop_requested = False
        logging.warning(f"[重启] ========== 开始一键配置 ==========")
        self._restart_thread = threading.Thread(
            target=self._quick_config_flow, daemon=True)
        self._restart_thread.start()

    def _quick_config_flow(self):
        """只执行阶段5+6：进游戏判断 → 按M打开地图 → F11配置"""
        try:
            self.show_toast_log("========== 开始一键配置 ==========")
            game_title = self.restart_config.get('game_title', '') or self.config.window.get('title', '')
            if not game_title:
                self.show_toast_log("错误: 游戏标题未设置")
                return
            self._phase_enter_game()
            if not self._stop_requested:
                logging.warning(f"[重启] ========== 一键配置完成 ==========")
                self.show_toast_log("========== 一键配置完成 ==========")
            else:
                logging.warning(f"[重启] ========== 一键配置已中止 ==========")
                self.show_toast_log("========== 一键配置已中止 ==========")
        except Exception as e:
            logging.error(f"[重启] 一键配置异常: {e}")
            import traceback
            logging.error(traceback.format_exc())
            self.show_toast_log(f"一键配置异常: {e}")
        finally:
            self._is_restarting = False
            self._stop_requested = False
            time.sleep(3)
            self.hide_toast()

    def _phase_stop_monitor(self):
        """阶段0: 停止当前监控"""
        logging.info("[重启] 阶段0: 停止监控")
        self.show_toast_log("停止监控")
        if self.game_monitor:
            self.game_monitor.running = False
            self.game_monitor.paused = False
        time.sleep(2)

    def _phase_kill_processes(self):
        """阶段1: 强制关闭游戏和rundll32进程"""
        logging.info("[重启] 阶段1: 关闭游戏和rundll32")
        self.show_toast_log("关闭游戏和rundll32")
        import subprocess

        # 强制结束游戏进程
        game_title = self.restart_config.get('game_title', '') or self.config.window.get('title', '')
        game_killed = False

        if game_title:
            # 先尝试FindWindow + WM_CLOSE（正常关闭）
            hwnd = ctypes.windll.user32.FindWindowW(None, game_title)
            if hwnd:
                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                logging.info(f"[重启] 已发送WM_CLOSE到游戏窗口")
                time.sleep(3)

            # 无论窗口是否存在，都通过进程名强制终止（处理卡窗口无窗口的情况）
            game_process_name = 'TheDivision2.exe'
            for _ in range(3):
                try:
                    result = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {game_process_name}',
                                             '/FO', 'CSV', '/NH'],
                                            capture_output=True, text=True, timeout=10)
                    lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
                    if len(lines) <= 1:
                        logging.info(f"[重启] {game_process_name} 已不存在")
                        game_killed = True
                        break
                    # 进程仍在，强制结束
                    result = subprocess.run(['taskkill', '/F', '/IM', game_process_name],
                                          capture_output=True, timeout=10)
                    logging.info(f"[重启] 已taskkill {game_process_name}")
                    self.show_toast_log(f"已taskkill {game_process_name}")
                    time.sleep(2)
                except Exception as e:
                    logging.warning(f"[重启] 结束{game_process_name}失败: {e}")
                    break

            if not game_killed:
                logging.warning(f"[重启] {game_process_name}可能仍在运行，继续后续流程")

        # 强制结束rundll32.exe
        for _ in range(3):
            try:
                subprocess.run(['taskkill', '/F', '/IM', 'rundll32.exe'],
                              capture_output=True, timeout=10)
                time.sleep(2)
                result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq rundll32.exe', '/FO', 'CSV', '/NH'],
                                        capture_output=True, text=True, timeout=10)
                lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
                if len(lines) <= 1:
                    logging.info("[重启] rundll32.exe已全部结束")
                    break
                logging.info(f"[重启] 仍有{len(lines)-1}个rundll32.exe进程，再次尝试")
            except Exception as e:
                logging.warning(f"[重启] 结束rundll32失败: {e}")
        time.sleep(1)

    def _has_rundll32_process(self):
        """检查是否有非系统的rundll32.exe进程"""
        import subprocess
        try:
            result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq rundll32.exe', '/FO', 'CSV', '/NH'],
                                    capture_output=True, text=True, timeout=10)
            lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
            return len(lines) > 1  # 超过1个说明有非系统rundll32
        except Exception:
            return False

    def _phase_start_rundll32(self):
        """阶段2: 启动rundll32，如果启动后进程消失则重试"""
        logging.info("[重启] 阶段2: 启动原力")
        self.show_toast_log("启动原力")
        bat_path = self.restart_config.get('bat_path', '')
        if not bat_path or not os.path.isfile(bat_path):
            raise RuntimeError(f"bat文件不存在: {bat_path}")
        import subprocess

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            if self._stop_requested:
                return
            logging.info(f"[重启] 启动bat (第{attempt}次): {bat_path}")
            subprocess.Popen(['cmd', '/c', bat_path], cwd=os.path.dirname(bat_path),
                             creationflags=0x08000000)  # CREATE_NO_WINDOW
            # 延时等待进程稳定
            time.sleep(5)
            # 检测rundll32.exe窗口是否出现
            start = time.time()
            found = False
            while time.time() - start < 30:
                hwnd = self._find_rundll32_window()
                if hwnd:
                    logging.info("[重启] 原力窗口已出现")
                    self.show_toast_log("原力窗口已出现")
                    found = True
                    break
                # 窗口没找到，检查进程是否还在
                if not self._has_rundll32_process():
                    logging.warning("[重启] rundll32.exe进程已消失，需要重试")
                    break
                time.sleep(1)

            if found:
                time.sleep(2)
                return
            # 没找到窗口且进程消失，重试
            if attempt < max_retries:
                logging.info(f"[重启] 等待3秒后重试...")
                time.sleep(3)

        if not self._find_rundll32_window():
            logging.error("[重启] 多次尝试后仍未找到原力窗口")

    def _phase_launch_game(self):
        """阶段3: 第一次播放 → 启动游戏 → 等logo过 → 第二次播放注入"""
        logging.info("[重启] 阶段3: 启动游戏并注入原力")

        # ===== 第一次播放（游戏启动前） =====
        hwnd = self._find_rundll32_window()
        if not hwnd:
            logging.error("[重启] 未找到原力窗口，无法点击播放")
            return False

        play_text = self.restart_config.get('play_button_text', '播放')
        wait_text = self.restart_config.get('play_wait_text', '等待歌曲启动后点击')

        if play_text:
            self._activate_window(hwnd)
            time.sleep(0.5)
            if not self._click_ocr_button(hwnd, play_text):
                logging.error("[重启] 第一次播放: 未能找到播放按钮")
                return False
            logging.info("[重启] 第一次播放: 已点击'播放'按钮")
            self.show_toast_log("已点击播放（第一次）")

        # 等待提示变为"等待歌曲启动后点击"
        if wait_text:
            logging.info(f"[重启] 第一次播放: 等待提示文字 '{wait_text}'")
            self._wait_for_ocr_text(hwnd, wait_text, timeout=60)
            logging.info("[重启] 第一次播放: 初始化成功")

        # ===== 启动游戏 =====
        game_shortcut = self.restart_config.get('game_shortcut', '')
        if game_shortcut:
            try:
                if '://' in game_shortcut:
                    os.startfile(game_shortcut)
                elif os.path.isfile(game_shortcut):
                    import subprocess
                    subprocess.Popen([game_shortcut],
                                     creationflags=0x08000000)  # CREATE_NO_WINDOW
                else:
                    logging.warning(f"[重启] 快捷方式无效: {game_shortcut}")
                logging.info(f"[重启] 已启动游戏: {game_shortcut}")
                self.show_toast_log(f"游戏已启动: {game_shortcut}")
            except Exception as e:
                logging.error(f"[重启] 启动游戏失败: {e}")

        # ===== 等待游戏窗口出现 =====
        game_title = self.restart_config.get('game_title', '') or self.config.window.get('title', '')
        if not game_title:
            logging.error("[重启] 未配置游戏标题")
            return False

        logging.info(f"[重启] 等待游戏窗口出现(标题: {game_title})")
        game_hwnd = self._wait_for_window(title=game_title, timeout=120)
        if not game_hwnd:
            logging.error("[重启] 等待游戏窗口超时")
            return False
        logging.info("[重启] 游戏窗口已出现")

        # ===== 等待logo界面过去 =====
        # Logo界面是无边框全屏，正常游戏窗口有标准Windows标题栏(WS_CAPTION)
        logging.info("[重启] 等待游戏logo界面过去...")
        GWL_STYLE = -16
        WS_CAPTION = 0x00C00000
        start = time.time()
        logo_done = False
        while time.time() - start < 120:
            if self._stop_requested:
                return
            # 重新查找窗口句柄（logo阶段可能句柄变化）
            game_hwnd = ctypes.windll.user32.FindWindowW(None, game_title)
            if game_hwnd:
                style = ctypes.windll.user32.GetWindowLongW(game_hwnd, GWL_STYLE)
                if style & WS_CAPTION:
                    logging.info(f"[重启] 检测到窗口标题栏(logo已过)，耗时{int(time.time()-start)}秒")
                    self.show_toast_log(f"logo已过，耗时{int(time.time()-start)}秒")
                    logo_done = True
                    break
            time.sleep(2)

        if not logo_done:
            logging.warning("[重启] 等待logo超时(120秒)，继续后续流程")

        # ===== 第二次播放（注入原力） =====
        # 等待提示出现 → 激活窗口前显 → 点击播放 → 等待窗口消失
        time.sleep(3)
        max_inject_retry = 5
        for inject_attempt in range(1, max_inject_retry + 1):
            if self._stop_requested:
                return

            # 每次循环重新获取句柄并激活前显
            hwnd = self._find_rundll32_window()
            if not hwnd:
                logging.info("[重启] 第二次播放: 原力窗口已消失，注入完成")
                break

            # 等待提示出现（同时联动检测窗口消失）
            if wait_text:
                logging.info(f"[重启] 第二次播放(第{inject_attempt}次): 等待提示 '{wait_text}'...")
                check_start = time.time()
                found_wait = False
                while time.time() - check_start < 30:
                    if self._stop_requested:
                        return
                    hwnd = self._find_rundll32_window()
                    if not hwnd:
                        logging.info("[重启] 第二次播放: 原力窗口已消失，注入完成")
                        found_wait = False
                        break
                    # 每次检测前先激活窗口确保前显
                    self._activate_window(hwnd)
                    time.sleep(0.3)
                    try:
                        rect = ctypes.wintypes.RECT()
                        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
                        if self.game_monitor and self.game_monitor.ocr_engine:
                            ocr_text = self.game_monitor.ocr_engine.recognize(img)
                            if wait_text in ocr_text:
                                logging.info(f"[重启] 第二次播放: 检测到提示，准备点击")
                                found_wait = True
                                break
                    except Exception:
                        pass
                    time.sleep(2)

                if not found_wait:
                    hwnd = self._find_rundll32_window()
                    if not hwnd:
                        logging.info("[重启] 第二次播放: 原力窗口已消失，注入完成")
                        break
                    logging.warning(f"[重启] 第二次播放: 未检测到提示，重试")
                    time.sleep(3)
                    continue

            # 激活窗口前显 → 点击播放
            hwnd = self._find_rundll32_window()
            if not hwnd:
                logging.info("[重启] 第二次播放: 原力窗口已消失，注入完成")
                break
            self._activate_window(hwnd)
            time.sleep(0.5)
            if play_text:
                if not self._click_ocr_button(hwnd, play_text):
                    logging.warning(f"[重启] 第二次播放: 未能找到播放按钮，重试")
                    time.sleep(3)
                    continue
                logging.info(f"[重启] 第二次播放(第{inject_attempt}次): 已点击播放，等待注入...")
                self.show_toast_log(f"已点击播放（第二次，第{inject_attempt}次）")

            # 点击后等待界面消失（注入成功的标志）
            inject_start = time.time()
            while time.time() - inject_start < 60:
                if self._stop_requested:
                    return
                if not self._find_rundll32_window():
                    elapsed = int(time.time() - inject_start)
                    logging.info(f"[重启] 第二次播放: 注入成功，界面消失（{elapsed}秒）")
                    self.show_toast_log(f"注入成功（{elapsed}秒）")
                    break
                time.sleep(2)
            else:
                logging.warning(f"[重启] 第二次播放: 等待界面消失超时，重试")
                time.sleep(2)
        else:
            logging.error("[重启] 第二次播放: 多次重试失败")

        # 原力加载成功后，前显游戏窗口
        game_title = self.restart_config.get('game_title', '') or self.config.window.get('title', '')
        if game_title:
            game_hwnd = ctypes.windll.user32.FindWindowW(None, game_title)
            if game_hwnd:
                self._activate_window(game_hwnd)
                logging.info("[重启] 已前显游戏窗口")
                self.show_toast_log("已前显游戏窗口")
        return True

    def _phase_wait_game_ready(self):
        """阶段4: 等待原力加载成功（游戏左侧出现红色浮动信息）"""
        logging.info("[重启] 阶段4: 等待原力浮动信息")
        game_title = self.restart_config.get('game_title', '') or self.config.window.get('title', '')
        if not game_title:
            return

        max_wait = 300
        start = time.time()
        ready = False

        while time.time() - start < max_wait and not ready:
            if self._stop_requested:
                return
            hwnd = ctypes.windll.user32.FindWindowW(None, game_title)
            if not hwnd:
                time.sleep(3)
                continue

            try:
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                # 截取左侧1/3区域（浮动信息在左侧）
                img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.left + w // 3, rect.bottom))

                if self.game_monitor and self.game_monitor.ocr_engine:
                    text = self.game_monitor.ocr_engine.recognize(img)
                    # 原力浮动信息特征
                    float_keywords = ['ins', '隐藏', '无限', 'INS', '子弹', '功能组']
                    if any(kw in text for kw in float_keywords):
                        elapsed = int(time.time() - start)
                        logging.info(f"[重启] 检测到原力浮动信息（{elapsed}秒）")
                        self.show_toast_log(f"检测到原力浮动信息（{elapsed}秒）")
                        ready = True
                        break
            except Exception:
                pass
            time.sleep(3)

        if not ready:
            logging.warning(f"[重启] 等待原力浮动信息超时（{max_wait}秒），继续后续流程")

    def _phase_enter_game(self):
        """阶段5+6: 按空格进入游戏 → 按M确认地图 → 恢复原力配置 → 失败则整体重试"""
        logging.info("[重启] 阶段5: 按空格进入游戏")
        game_title = self.restart_config.get('game_title', '') or self.config.window.get('title', '')
        if not game_title:
            return

        max_retries = 10
        for attempt in range(1, max_retries + 1):
            if self._stop_requested:
                return
            hwnd = ctypes.windll.user32.FindWindowW(None, game_title)
            if not hwnd:
                time.sleep(3)
                continue

            # 按空格
            self._activate_window(hwnd)
            time.sleep(0.5)
            self._send_key('space', presses=1)
            logging.info(f"[重启] 第{attempt}次按空格")
            self.show_toast_log(f"第{attempt}次按空格")
            time.sleep(8)  # 等待进入游戏或出现加载界面

            # 检查是否还在加载界面（有"下一个提示"等文字说明还在加载）
            if self._check_in_menu(game_title):
                logging.info(f"[重启] 仍在主菜单/加载界面，继续按空格")
                continue

            # 不在主菜单了，按M打开地图确认
            logging.info("[重启] 按M打开地图确认...")
            self._activate_window(hwnd)
            time.sleep(0.5)
            self._send_key('m', presses=1)
            time.sleep(3)

            # OCR检测地图是否打开
            map_opened = self._check_map_open(game_title)
            if not map_opened:
                logging.info("[重启] 地图未打开，关闭可能打开的地图后重试")
                self._send_key('m', presses=1)
                time.sleep(1)
                continue

            logging.info("[重启] 地图已打开，确认进入游戏（保持地图以显示光标）")
            self.show_toast_log("地图已打开")

            # 阶段6: 恢复原力配置
            self._phase_restore_config_inner(game_title)

            # 配置完成后关闭地图
            self._send_key('m', presses=1)
            logging.info("[重启] 已按M关闭地图")
            self.show_toast_log("关闭地图")
            time.sleep(1)
            return True

        logging.warning("[重启] 多次尝试后仍未完成，继续后续流程")
        return False

    def _check_in_menu(self, game_title):
        """检测是否还在主菜单/加载界面"""
        hwnd = ctypes.windll.user32.FindWindowW(None, game_title)
        if not hwnd:
            return False
        try:
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
            if self.game_monitor and self.game_monitor.ocr_engine:
                text = self.game_monitor.ocr_engine.recognize(img)
                menu_keywords = ['继续', '首页', '载入中', '加载中', '连接中', '正在初始化',
                                 '下一个提示', '前一个', '游戏性', '世界']
                return any(kw in text for kw in menu_keywords)
        except Exception:
            pass
        return False

    def _check_map_open(self, game_title):
        """检测地图是否打开（有报复行动/猎捕行动等文字）"""
        hwnd = ctypes.windll.user32.FindWindowW(None, game_title)
        if not hwnd:
            return False
        try:
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
            if self.game_monitor and self.game_monitor.ocr_engine:
                text = self.game_monitor.ocr_engine.recognize(img)
                map_keywords = ['报复行动', '猎捕行动', '悬赏', '全部']
                found = [kw for kw in map_keywords if kw in text]
                if found:
                    logging.info(f"[重启] 地图UI确认: {found}")
                    return True
        except Exception:
            pass
        return False

    def _phase_restore_config(self):
        """阶段6: F11打开原力配置界面 → 按SMD配置设置参数 → F11关闭"""
        logging.info("[重启] 阶段6: 恢复原力配置")
        game_title = self.restart_config.get('game_title', '') or self.config.window.get('title', '')
        if not game_title:
            return False
        hwnd = ctypes.windll.user32.FindWindowW(None, game_title)
        if not hwnd:
            return False

        # 加载SMD配置
        smd_config_path = self.smd_config_path
        if not os.path.isfile(smd_config_path):
            logging.info("[重启] 无SMD配置文件，跳过配置恢复")
            return True  # 无配置算成功

        try:
            with open(smd_config_path, 'r', encoding='utf-8') as f:
                smd_data = json.load(f)
        except Exception as e:
            logging.error(f"[重启] 加载SMD配置失败: {e}")
            return False

        if not smd_data:
            logging.info("[重启] SMD配置为空，跳过")
            return True

        # F11打开原力配置界面
        self._activate_window(hwnd)
        time.sleep(0.5)
        self._send_key('f11', presses=1)
        logging.info("[重启] 已按F11打开原力配置")
        self.show_toast_log("打开原力配置")
        time.sleep(3)

        # 遍历每个标签页的设定参数
        # 需要先点击标签切换到对应页面，再设置参数
        # 支持标签页级重试：单个参数连续失败超过阈值时，重新点击标签并重试该标签页
        from smd_config_editor import SMD_TABS
        for tab_info in SMD_TABS:
            if self._stop_requested:
                break
            tab_key = tab_info['key']
            tab_name = tab_info['name']
            tab_data = smd_data.get(tab_key, {})
            items = tab_data.get('items', [])
            if not items:
                continue

            # 标签页级重试
            tab_success = False
            for tab_attempt in range(self._tab_retry_count + 1):
                if self._stop_requested:
                    break
                if tab_attempt > 0:
                    logging.info(f"[重启] 标签 '{tab_name}' 第{tab_attempt}次重试...")
                    self.show_toast_log(f"标签重试: {tab_name} ({tab_attempt}/{self._tab_retry_count})")

                # 先点击标签切换到对应页面
                logging.info(f"[重启] 切换到标签: {tab_name}")
                self.show_toast_log(f"切换到标签: {tab_name}")
                self._activate_window(hwnd)
                time.sleep(0.3)
                if not self._click_ocr_in_game(hwnd, tab_name):
                    logging.warning(f"[重启] 未找到标签 '{tab_name}'，跳过")
                    break
                time.sleep(1.2)  # 等待标签切换完成
                self._invalidate_ocr_cache()

                # 按配置顺序逐个执行参数（保持action和普通参数的原始顺序）
                consecutive_failures = 0
                all_success = True
                for item_idx, item in enumerate(items):
                    if self._stop_requested:
                        break
                    ocr_label = item.get('ocr_label', item.get('name', ''))
                    success = True

                    if item.get('item_type') == 'action':
                        if ocr_label:
                            logging.info(f"[重启] 执行操作: {ocr_label}")
                            success = self._click_ocr_in_game(hwnd, ocr_label)
                            time.sleep(1.2)
                    else:
                        # item_type 为 special 时强制使用 special 方法
                        item_to_set = item
                        if item.get('item_type') == 'special':
                            item_to_set = dict(item)
                            item_to_set['value_set_method'] = 'special'
                        success = self._set_smd_parameter(hwnd, item_to_set)
                        time.sleep(0.3)

                    if success:
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                        all_success = False
                        logging.warning(f"[重启] 参数 '{ocr_label}' 设置失败（连续失败{consecutive_failures}次）")

                        # 连续失败超过阈值，重新从标签页开始
                        if consecutive_failures >= self._tab_max_failures:
                            logging.warning(f"[重启] 标签 '{tab_name}' 连续失败{consecutive_failures}个参数，重新进入标签页...")
                            break

                # 如果全部成功，或者不是因为连续失败而中断，则跳出标签重试循环
                if all_success or consecutive_failures < self._tab_max_failures:
                    tab_success = all_success
                    break

            if not tab_success:
                logging.warning(f"[重启] 标签 '{tab_name}' 配置恢复失败（已重试{self._tab_retry_count}次）")

        # F11关闭原力配置界面
        time.sleep(1)
        self._send_key('f11', presses=1)
        logging.info("[重启] 已按F11关闭原力配置")
        self.show_toast_log("原力配置已恢复")
        time.sleep(1)
        return True

    def _phase_restore_config_inner(self, game_title):
        """阶段6内部: 由阶段5+6统一调用"""
        return self._phase_restore_config()

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
        if t in o or o in t:
            return True
        min_len = min(len(t), len(o))
        if min_len >= 3:
            return t[:min_len] == o[:min_len]
        return False

    def _get_cached_ocr(self, hwnd, force_refresh=False):
        """获取全屏OCR结果（带缓存）
        force_refresh: True 时强制刷新缓存
        返回: (ocr_items, rect) 或 (None, None)
        """
        try:
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            rect_tuple = (rect.left, rect.top, rect.right, rect.bottom)
            now = time.time()

            # 检查缓存是否有效
            if (not force_refresh and self._ocr_cache and
                    self._ocr_cache[0] == rect_tuple and
                    now - self._ocr_cache[2] < self._ocr_cache_ttl):
                return self._ocr_cache[1], rect

            # 重新OCR
            ocr_engine = self.game_monitor._get_ocr_engine()
            if not ocr_engine:
                return None, rect

            img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
            items = ocr_engine.recognize_with_pos(img)
            self._ocr_cache = (rect_tuple, items, now)
            return items, rect
        except Exception as e:
            logging.debug(f"[重启] 缓存OCR异常: {e}")
            return None, None

    def _invalidate_ocr_cache(self):
        """使OCR缓存失效（UI发生变化后调用）"""
        self._ocr_cache = None

    def _click_ocr_in_game(self, hwnd, text, retry_count=None):
        """在游戏窗口中OCR找到文字并点击（忽略 - ( ) 等符号）
        当OCR文本比搜索文本长时，自动估算目标文字在OCR文本中的位置偏移
        retry_count: 重试次数，默认使用 self._ocr_retry_count
        """
        if retry_count is None:
            retry_count = self._ocr_retry_count

        for attempt in range(retry_count):
            if self._stop_requested:
                return False
            try:
                items, rect = self._get_cached_ocr(hwnd, force_refresh=(attempt > 0))
                if not items:
                    if attempt < retry_count - 1:
                        time.sleep(0.3)
                    continue

                norm_text = self._normalize_match_text(text)
                # 收集所有匹配项，优先选择长度最接近的（最精确匹配）
                candidates = []
                for ocr_text, cx, cy in items:
                    norm_ocr = self._normalize_match_text(ocr_text)
                    if norm_text in norm_ocr:
                        candidates.append((abs(len(norm_ocr) - len(norm_text)), ocr_text, cx, cy))
                if candidates:
                    candidates.sort(key=lambda x: x[0])
                    _, best_ocr, cx, cy = candidates[0]

                    # 如果OCR文本比搜索文本长很多，估算目标文字在OCR文本中的位置偏移
                    norm_ocr = self._normalize_match_text(best_ocr)
                    if len(norm_ocr) > len(norm_text) + 1:
                        # 找目标文字在规范化OCR文本中的起始位置
                        idx = norm_ocr.find(norm_text)
                        if idx >= 0:
                            # 估算每个字符的像素宽度（中文字符约15px）
                            char_width = 15
                            offset_x = int((idx + len(norm_text) / 2) * char_width
                                           - len(norm_ocr) / 2 * char_width)
                            cx += offset_x
                            logging.info(f"[重启] 多词偏移: '{text}'在'{best_ocr}'中位置{idx}，偏移{offset_x}px")

                    abs_x = rect.left + cx
                    abs_y = rect.top + cy
                    logging.info(f"[重启] 游戏内OCR匹配到'{text}'（OCR原文:'{best_ocr}'），点击: ({cx}, {cy})")
                    self._activate_window(hwnd)
                    time.sleep(0.15)
                    ctypes.windll.user32.SetCursorPos(abs_x, abs_y)
                    time.sleep(0.05)
                    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                    time.sleep(0.03)
                    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                    time.sleep(0.2)
                    # 点击后UI可能变化，使缓存失效
                    self._invalidate_ocr_cache()
                    return True

                if attempt < retry_count - 1:
                    logging.info(f"[重启] 游戏内未匹配到'{text}'，第{attempt + 1}次重试...")
                    time.sleep(0.3)
            except Exception as e:
                logging.error(f"[重启] 游戏内OCR点击异常: {e}")
                if attempt < retry_count - 1:
                    time.sleep(0.3)

        logging.warning(f"[重启] 游戏内未匹配到'{text}'（已重试{retry_count}次）")
        return False

    def _set_smd_parameter(self, hwnd, item, retry_count=None):
        """设置单个SMD参数（原力界面：控件在左，标题在右）
        返回: True 成功, False 失败
        """
        if retry_count is None:
            retry_count = self._ocr_retry_count

        name = item.get('name', '')
        ocr_label = item.get('ocr_label', '')
        item_type = item.get('item_type', 'toggle')
        target_value = item.get('target_value', '')
        method = item.get('value_set_method', 'click')

        if not ocr_label:
            return True

        logging.info(f"[重启] 设置参数: {name} = {target_value} (类型:{item_type}, 方式:{method})")

        if method == 'click':
            # 开关/下拉框：控件在左，标题在右
            # 下拉框：需要先点击控件(当前值区域)展开列表，再选择目标值
            # 开关：直接点击控件区域即可切换
            if item_type == 'dropdown':
                # 下拉框操作（原力界面布局：[当前值 | ▼] ... 标题文字）
                # 1. OCR找到标题文字位置
                # 2. 在标题左侧找下拉箭头(▼)按钮并点击展开
                # 3. 在展开列表中找到目标值并点击
                logging.info(f"[重启] 下拉框: 找标题'{ocr_label}'，展开后选'{target_value}'")
                for attempt in range(retry_count):
                    if self._stop_requested:
                        return False
                    try:
                        items, rect = self._get_cached_ocr(hwnd, force_refresh=(attempt > 0))
                        if not items:
                            if attempt < retry_count - 1:
                                time.sleep(0.3)
                            continue

                        norm_label = self._normalize_match_text(ocr_label)
                        # 找标题文字位置
                        title_pos = None
                        for ocr_text, cx, cy in items:
                            if norm_label in self._normalize_match_text(ocr_text):
                                title_pos = (cx, cy)
                                break
                        if not title_pos:
                            if attempt < retry_count - 1:
                                logging.info(f"[重启] 下拉框: 未找到标题 '{ocr_label}'，第{attempt + 1}次重试...")
                                time.sleep(0.3)
                            continue

                        # 点击标题左侧固定偏移处的下拉箭头(▼)
                        # 原力界面布局: [当前值文本 | ▼] ... 标题文字
                        char_count = len(ocr_label)
                        text_half_width = int(char_count / 2 * 15)
                        arrow_x = max(0, title_pos[0] - text_half_width - 50)
                        arrow_y = title_pos[1] + 10
                        abs_x = rect.left + arrow_x
                        abs_y = rect.top + arrow_y
                        logging.info(f"[重启] 下拉框: 点击固定偏移箭头位置 ({arrow_x}, {arrow_y})")
                        self._activate_window(hwnd)
                        time.sleep(0.15)
                        ctypes.windll.user32.SetCursorPos(abs_x, abs_y)
                        time.sleep(0.05)
                        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                        time.sleep(0.03)
                        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)

                        self._invalidate_ocr_cache()
                        time.sleep(0.6)  # 等待下拉列表展开

                        # 在展开的列表中找到目标值并点击
                        if target_value:
                            if not self._click_ocr_in_game(hwnd, target_value):
                                logging.warning(f"[重启] 下拉列表中未找到 '{target_value}'")
                        return True
                    except Exception as e:
                        logging.error(f"[重启] 下拉框操作失败: {e}")
                        if attempt < retry_count - 1:
                            time.sleep(0.3)
                logging.warning(f"[重启] 下拉框设置失败: {name}（已重试{retry_count}次）")
                return False
            elif item_type == 'toggle':
                # 蓝色开关：通过颜色检测判断当前状态（蓝色=开启，灰色/黑色=关闭）
                for attempt in range(retry_count):
                    if self._stop_requested:
                        return False
                    need_click = True
                    label_found = False
                    try:
                        items, rect = self._get_cached_ocr(hwnd, force_refresh=(attempt > 0))
                        if not items:
                            if attempt < retry_count - 1:
                                time.sleep(0.3)
                            continue

                        norm_label = self._normalize_match_text(ocr_label)
                        # 找到标签文字位置
                        label_pos = None
                        for ocr_text, cx, cy in items:
                            if norm_label in self._normalize_match_text(ocr_text):
                                label_pos = (cx, cy)
                                break
                        if not label_pos:
                            if attempt < retry_count - 1:
                                logging.info(f"[重启] 蓝色开关: 未找到标签 '{ocr_label}'，第{attempt + 1}次重试...")
                                time.sleep(0.3)
                            continue
                        label_found = True

                        # 开关控件在标签文字的左侧
                        # 根据标签文字长度和开关按钮大小动态计算扫描范围
                        # 原力界面布局: [开关按钮50px] [间距] [标签文字]
                        # scan_left = 标签中心 - 字数/2*15 - 开关宽度50
                        # scan_right = 标签中心 - 字数/2*15 - 间距10
                        img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
                        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                        char_count = len(ocr_label)
                        text_half_width = int(char_count / 2 * 15)
                        switch_width = 50
                        switch_height = 30
                        scan_left = max(0, label_pos[0] - text_half_width - switch_width)
                        scan_right = max(0, label_pos[0] - text_half_width - 10)
                        scan_top = max(0, label_pos[1] - switch_height // 2)
                        scan_bottom = min(img_cv.shape[0], label_pos[1] + switch_height // 2)
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
                                logging.info(f"[重启] 蓝色开关 '{name}' 颜色采样 位置=({blue_cx},{blue_cy}) B={b:.0f} G={g:.0f} R={r:.0f}, "
                                             f"{'蓝色=开启' if is_blue else '非蓝=关闭'}")
                                want_on = target_value in ('开启', '1', 'true', 'True', 'on', 'ON')
                                if is_blue and want_on:
                                    logging.info(f"[重启] 蓝色开关 '{name}' 已是开启状态，跳过")
                                    need_click = False
                                elif not is_blue and not want_on:
                                    logging.info(f"[重启] 蓝色开关 '{name}' 已是关闭状态，跳过")
                                    need_click = False
                                else:
                                    logging.info(f"[重启] 蓝色开关 '{name}' 目标{'开启' if want_on else '关闭'}，执行点击")
                            else:
                                logging.info(f"[重启] 蓝色开关 '{name}' 未检测到蓝色像素，跳过检测直接点击")
                    except Exception as e:
                        logging.debug(f"[重启] 检测蓝色开关状态失败，继续点击: {e}")

                    if label_found:
                        if need_click:
                            self._click_ocr_in_game(hwnd, ocr_label)
                        return True

                logging.warning(f"[重启] 蓝色开关设置失败: {name}（已重试{retry_count}次）")
                return False
            elif item_type == 'check_toggle':
                # 勾选开关：通过检测白色对勾像素判断当前状态（有对勾=开启，无对勾=关闭）
                for attempt in range(retry_count):
                    if self._stop_requested:
                        return False
                    need_click = True
                    label_found = False
                    try:
                        items, rect = self._get_cached_ocr(hwnd, force_refresh=(attempt > 0))
                        if not items:
                            if attempt < retry_count - 1:
                                time.sleep(0.3)
                            continue

                        norm_label = self._normalize_match_text(ocr_label)
                        # 找到标签文字位置
                        label_pos = None
                        for ocr_text, cx, cy in items:
                            if norm_label in self._normalize_match_text(ocr_text):
                                label_pos = (cx, cy)
                                break
                        if not label_pos:
                            if attempt < retry_count - 1:
                                logging.info(f"[重启] 勾选开关: 未找到标签 '{ocr_label}'，第{attempt + 1}次重试...")
                                time.sleep(0.3)
                            continue
                        label_found = True

                        # 勾选框在标签文字的左侧
                        # 布局: [勾选框] [间距] [标签文字]
                        img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
                        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                        char_count = len(ocr_label)
                        text_half_width = int(char_count / 2 * 15)
                        box_width = 30
                        box_height = 30
                        scan_left = max(0, label_pos[0] - text_half_width - box_width - 10)
                        scan_right = max(0, label_pos[0] - text_half_width - 5)
                        scan_top = max(0, label_pos[1] - box_height // 2)
                        scan_bottom = min(img_cv.shape[0], label_pos[1] + box_height // 2)
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
                            logging.info(f"[重启] 勾选开关 '{name}' 检测: 白色像素{white_count}/{total_pixels}, "
                                         f"占比={check_ratio:.2%}, {'已勾选=开启' if is_checked else '未勾选=关闭'}")
                            want_on = target_value in ('开启', '1', 'true', 'True', 'on', 'ON')
                            if is_checked and want_on:
                                logging.info(f"[重启] 勾选开关 '{name}' 已是开启状态，跳过")
                                need_click = False
                            elif not is_checked and not want_on:
                                logging.info(f"[重启] 勾选开关 '{name}' 已是关闭状态，跳过")
                                need_click = False
                            else:
                                logging.info(f"[重启] 勾选开关 '{name}' 目标{'开启' if want_on else '关闭'}，执行点击")
                        else:
                            logging.info(f"[重启] 勾选开关 '{name}' 扫描区域无效，跳过检测直接点击")
                    except Exception as e:
                        logging.debug(f"[重启] 检测勾选开关状态失败，继续点击: {e}")

                    if label_found:
                        if need_click:
                            self._click_ocr_in_game(hwnd, ocr_label)
                        return True

                logging.warning(f"[重启] 勾选开关设置失败: {name}（已重试{retry_count}次）")
                return False
            else:
                # 普通点击类型
                return self._click_ocr_in_game(hwnd, ocr_label, retry_count)

        elif method == 'ctrl_click':
            # 滑块操作（控件在左，标题在右）：
            # 1. Ctrl+左键点击控件（滑块/值区域）→ 变为输入框
            # 2. 输入目标值
            # 3. 点击右侧标题文字让输入值生效
            for attempt in range(retry_count):
                if self._stop_requested:
                    return False
                try:
                    items, rect = self._get_cached_ocr(hwnd, force_refresh=(attempt > 0))
                    if not items:
                        if attempt < retry_count - 1:
                            time.sleep(0.3)
                        continue

                    ctrl_pos = None
                    norm_label = self._normalize_match_text(ocr_label)
                    for ocr_text, cx, cy in items:
                        if norm_label in self._normalize_match_text(ocr_text):
                            ctrl_pos = (cx, cy)
                            break

                    if not ctrl_pos:
                        if attempt < retry_count - 1:
                            logging.info(f"[重启] 滑块: 未找到 '{ocr_label}'，第{attempt + 1}次重试...")
                            time.sleep(0.3)
                        continue

                    char_count = len(ocr_label)
                    text_half_width = int(char_count / 2 * 15)
                    input_width = 100

                    click_left = max(0, ctrl_pos[0] - text_half_width - input_width)
                    click_top = max(0, ctrl_pos[1])
                    abs_x = rect.left + click_left
                    abs_y = rect.top + click_top

                    # 步骤1: Ctrl+左键点击控件区域
                    self._activate_window(hwnd)
                    time.sleep(0.15)

                    # 按下Ctrl
                    VK_CONTROL = 0x11
                    INPUT_KEYBOARD = 1
                    KEYEVENTF_SCANCODE = 0x0008
                    KEYEVENTF_KEYUP = 0x0002
                    ctrl_scan = ctypes.windll.user32.MapVirtualKeyW(VK_CONTROL, 0)

                    # Ctrl down
                    ci = _INPUT(); ci.type = INPUT_KEYBOARD
                    ci.union.ki.wScan = ctrl_scan; ci.union.ki.dwFlags = KEYEVENTF_SCANCODE
                    ctypes.windll.user32.SendInput(1, ctypes.byref(ci), _INPUT_SIZE)
                    time.sleep(0.08)

                    # 左键点击控件位置
                    ctypes.windll.user32.SetCursorPos(abs_x, abs_y)
                    time.sleep(0.05)
                    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                    time.sleep(0.03)
                    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                    time.sleep(0.2)

                    # Ctrl up
                    ci2 = _INPUT(); ci2.type = INPUT_KEYBOARD
                    ci2.union.ki.wScan = ctrl_scan; ci2.union.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
                    ctypes.windll.user32.SendInput(1, ctypes.byref(ci2), _INPUT_SIZE)
                    self._invalidate_ocr_cache()
                    time.sleep(0.3)

                    # 步骤2: 输入目标值
                    if target_value:
                        for ch in target_value:
                            self._send_unicode_char(hwnd, ch)
                            time.sleep(0.03)
                        time.sleep(0.2)

                    # 步骤3: 点击右侧标题文字让值生效
                    self._click_ocr_in_game(hwnd, ocr_label)
                    time.sleep(0.2)

                    logging.info(f"[重启] 滑块: Ctrl+点击 '{ocr_label}'，输入 '{target_value}'，点击标题生效")
                    return True
                except Exception as e:
                    logging.error(f"[重启] 设置参数 '{name}' 失败: {e}")
                    if attempt < retry_count - 1:
                        time.sleep(0.3)

            logging.warning(f"[重启] 滑块设置失败: {name}（已重试{retry_count}次）")
            return False
        elif method == 'round_slider':
            # 圆形滑条：标题在左，数值在中（只读），滑条在右
            # 数值无法点击编辑，只能通过点击滑条进度位置或拖拽圆形滑块来变动
            # 策略：找到当前数值，计算目标比例，点击滑条对应位置
            for attempt in range(retry_count):
                if self._stop_requested:
                    return False
                try:
                    items, rect = self._get_cached_ocr(hwnd, force_refresh=(attempt > 0))
                    if not items:
                        if attempt < retry_count - 1:
                            time.sleep(0.3)
                        continue
                    win_w = rect.right - rect.left
                    win_h = rect.bottom - rect.top

                    norm_label = self._normalize_match_text(ocr_label)

                    # 1. 找到标签位置
                    label_pos = None
                    for ocr_text, cx, cy in items:
                        if norm_label in self._normalize_match_text(ocr_text):
                            label_pos = (cx, cy)
                            break
                    if not label_pos:
                        if attempt < retry_count - 1:
                            logging.info(f"[重启] 圆形滑条: 未找到标签 '{ocr_label}'，第{attempt + 1}次重试...")
                            time.sleep(0.3)
                        continue

                    # 2. 找同行的数值文字（包含数字，在标签右侧）
                    current_value = None
                    value_pos = None
                    for ocr_text, cx, cy in items:
                        if abs(cy - label_pos[1]) < 10 and cx > label_pos[0] and cx - label_pos[0] < 100:
                            if any(c.isdigit() or c == '.' for c in ocr_text):
                                current_value = ocr_text
                                value_pos = (cx, cy)
                                break

                    # 需要截图用于滑块检测
                    img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))

                    # 3. 找圆形滑块位置（同行、在数值右侧、通过区域采样白色像素检测）
                    thumb_pos = self._find_slider_thumb(img, value_pos, label_pos, win_h, current_value)

                    if thumb_pos and current_value and target_value:
                        try:
                            cur_val = float(current_value)
                            tgt_val = float(target_value)
                            logging.info(f"[重启] 圆形滑条 '{name}': 当前值={cur_val}, 目标值={tgt_val}, 滑块位置={thumb_pos}")
                        except ValueError:
                            logging.warning(f"[重启] 圆形滑条: 无法解析数值 '{current_value}' 或 '{target_value}'")
                            return False

                        if abs(cur_val - tgt_val) < 0.001:
                            logging.info(f"[重启] 圆形滑条 '{name}' 值已一致，跳过")
                            return True

                        # 4. 拖拽滑块到目标值
                        self._drag_slider_to_value(hwnd, rect, ocr_label, thumb_pos,
                                                   cur_val, tgt_val, label_pos)
                        self._invalidate_ocr_cache()
                        return True
                    else:
                        # 找不到滑块，回退：通过点击滑条区域（数值右侧一定范围）来逼近
                        logging.info(f"[重启] 圆形滑条: 未找到滑块，尝试点击滑条区域逼近")
                        return True  # 不算失败，只是用了回退方案
                except Exception as e:
                    logging.error(f"[重启] 设置圆形滑条 '{name}' 失败: {e}")
                    if attempt < retry_count - 1:
                        time.sleep(0.3)

            logging.warning(f"[重启] 圆形滑条设置失败: {name}（已重试{retry_count}次）")
            return False
        elif method == 'slider_drag':
            logging.warning(f"[重启] 滑块拖拽暂未实现: {name}")
            return True  # 未实现不算失败
        elif method == 'special':
            # 特殊操作：以 ocr_label 为锚点，在其下方列表区域中寻找已选脚本名并点击
            # 优先使用 GUI 当前选定的脚本名，回退到配置文件
            for attempt in range(retry_count):
                if self._stop_requested:
                    return False
                try:
                    # 优先使用 GUI 传入的当前选定脚本
                    target_script = self._gui_selected_script
                    script_type_name = self._gui_script_type or "恶化"

                    # 回退：从配置文件中读取
                    if not target_script:
                        smd_config_path = self.smd_config_path
                        if os.path.isfile(smd_config_path):
                            with open(smd_config_path, 'r', encoding='utf-8') as f:
                                smd_cfg = json.load(f)
                            script_edit = smd_cfg.get('script_edit', {})
                            extra = script_edit.get('extra', {})
                            script_type_name = extra.get('script_type', '恶化')
                            selections = extra.get('script_selections', {})
                            target_script = selections.get(script_type_name, extra.get('selected_script', ''))

                    if not target_script:
                        logging.warning(f"[重启] 特殊操作: 未找到已选脚本名，跳过")
                        return True

                    logging.info(f"[重启] 特殊操作: 查找脚本 '{target_script}'（类型: {script_type_name}）")

                    items, rect = self._get_cached_ocr(hwnd, force_refresh=(attempt > 0))
                    if not items:
                        if attempt < retry_count - 1:
                            time.sleep(0.3)
                        continue
                    win_w = rect.right - rect.left
                    win_h = rect.bottom - rect.top

                    # 先找到 ocr_label 的位置作为锚点
                    anchor_pos = None
                    norm_label = self._normalize_match_text(ocr_label)
                    for ocr_text, cx, cy in items:
                        if norm_label in self._normalize_match_text(ocr_text):
                            anchor_pos = (cx, cy)
                            break

                    if not anchor_pos:
                        if attempt < retry_count - 1:
                            logging.info(f"[重启] 特殊操作: 未找到锚点 '{ocr_label}'，第{attempt + 1}次重试...")
                            time.sleep(0.3)
                        continue

                    # 列表区域：锚点下方，宽250像素，高650像素
                    list_left = max(0, anchor_pos[0] - 200)
                    list_right = min(win_w, anchor_pos[0] + 50)
                    list_top = anchor_pos[1] + 10
                    list_bottom = min(win_h, list_top + 650)

                    max_scroll_attempts = 10

                    # 先滚到列表顶部，避免漏找
                    self._activate_window(hwnd)
                    scroll_x = rect.left + (list_left + list_right) // 2
                    scroll_y = rect.top + (list_top + list_bottom) // 2
                    ctypes.windll.user32.SetCursorPos(scroll_x, scroll_y)
                    time.sleep(0.05)
                    WHEEL_DELTA = 120
                    for _ in range(20):
                        ctypes.windll.user32.mouse_event(0x0800, 0, 0, WHEEL_DELTA, 0)
                        time.sleep(0.03)
                    time.sleep(0.2)

                    ocr_engine = self.game_monitor._get_ocr_engine()
                    found = False
                    for scroll_attempt in range(max_scroll_attempts):
                        if self._stop_requested:
                            return False
                        # 截取列表区域
                        abs_left = rect.left + list_left
                        abs_top = rect.top + list_top
                        abs_right = rect.left + list_right
                        abs_bottom = rect.top + list_bottom
                        list_img = ImageGrab.grab(bbox=(abs_left, abs_top, abs_right, abs_bottom))

                        if ocr_engine:
                            list_items = ocr_engine.recognize_with_pos(list_img)
                            t_norm = self._normalize_script_name(self._strip_bin(target_script))
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
                                time.sleep(0.1)
                                ctypes.windll.user32.SetCursorPos(click_x, click_y)
                                time.sleep(0.05)
                                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                                time.sleep(0.03)
                                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                                logging.info(f"[重启] 特殊操作: 在列表中找到 '{target_script}' (OCR: '{ocr_text}') 并点击")
                                self._invalidate_ocr_cache()
                                found = True
                                break

                        if found:
                            break
                        # 没找到，向下滚动列表区域
                        logging.info(f"[重启] 特殊操作: 第{scroll_attempt + 1}次滚动寻找 '{target_script}'")
                        self._activate_window(hwnd)
                        # 在列表区域中心滚轮向下
                        ctypes.windll.user32.SetCursorPos(scroll_x, scroll_y)
                        time.sleep(0.05)
                        # 滚轮向下 (-WHEEL_DELTA)
                        WHEEL_DELTA = 300
                        ctypes.windll.user32.mouse_event(0x0800, 0, 0, -WHEEL_DELTA, 0)
                        time.sleep(0.3)

                    if found:
                        time.sleep(0.5)
                        return True
                    else:
                        logging.warning(f"[重启] 特殊操作: 滚动到底仍未找到 '{target_script}'")
                        if attempt < retry_count - 1:
                            logging.info(f"[重启] 特殊操作: 第{attempt + 1}次重试...")
                            time.sleep(0.5)
                except Exception as e:
                    logging.error(f"[重启] 特殊操作失败: {e}")
                    if attempt < retry_count - 1:
                        time.sleep(0.3)

            logging.warning(f"[重启] 特殊操作失败（已重试{retry_count}次）")
            return False

    def _find_slider_thumb(self, img, value_pos, label_pos, win_h, current_value=None):
        """在截图上找圆形滑块位置（白色圆形，在数值右侧）
        搜索范围：数值x坐标 + 字符长度*10/2 起，宽130像素，y±15像素
        使用区域采样白色像素密度找滑块中心，避免和文字混淆
        返回 (x, y) 绝对窗口内坐标，或 None
        """
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

        if not value_pos:
            return None

        # 搜索范围：数值右侧
        char_len = len(current_value) if current_value else 3
        search_left = int(value_pos[0] + char_len * 10 / 2)
        search_right = search_left + 130
        search_top = max(0, value_pos[1] - 15)
        search_bottom = min(win_h, value_pos[1] + 15)

        if search_left >= search_right or search_top >= search_bottom:
            return None

        roi = img_cv[search_top:search_bottom, search_left:search_right]

        # 区域采样：白色像素 (R>200, G>200, B>200) 的密集区域
        white_mask = (roi[:, :, 2] > 200) & (roi[:, :, 1] > 200) & (roi[:, :, 0] > 200)
        white_pts = np.where(white_mask)
        if len(white_pts[0]) > 0:
            # 取白色像素的中位数位置（更稳健）
            cx = int(np.median(white_pts[1])) + search_left
            cy = int(np.median(white_pts[0])) + search_top
            return (cx, cy)
        return None

    def _drag_slider_to_value(self, hwnd, rect, ocr_label, thumb_pos,
                               cur_val, tgt_val, label_pos, max_iterations=15):
        """二分法在滑条轨道上逼近目标值（不依赖线性假设）"""

        # 滑条轨道范围
        left_bound = thumb_pos[0] - 65
        right_bound = thumb_pos[0] + 65
        target_y = thumb_pos[1]

        for iteration in range(max_iterations):
            if abs(cur_val - tgt_val) < 0.1:
                logging.info(f"[重启] 圆形滑条: 达到目标值 {tgt_val}")
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
                if self.game_monitor._get_ocr_engine():
                    items = self.game_monitor._get_ocr_engine().recognize_with_pos(new_img)
                else:
                    items = []
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
                    logging.info(f"[重启] 圆形滑条: 迭代{iteration+1}, 当前值={cur_val}, 目标={tgt_val}")
                    # 二分调整范围
                    if cur_val > tgt_val:
                        right_bound = mid_x
                    else:
                        left_bound = mid_x
                else:
                    logging.warning(f"[重启] 圆形滑条: 无法读取当前值，停止迭代")
                    break
            except Exception as e:
                logging.warning(f"[重启] 圆形滑条: 迭代读取失败: {e}")
                break

        # 最终点击标题让值生效
        self._click_ocr_in_game(hwnd, ocr_label)

    def _send_unicode_char(self, hwnd, ch):
        """发送单个Unicode字符到窗口"""
        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002
        vk = ord(ch)
        ctypes.windll.user32.keybd_event(0, vk, KEYEVENTF_UNICODE, 0)
        time.sleep(0.02)
        ctypes.windll.user32.keybd_event(0, vk, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)

    def _phase_resume_monitor(self):
        """恢复监控（在新线程中启动，避免阻塞重启线程导致toast无法退出）"""
        logging.info("[重启] 恢复监控")
        self.show_toast_log("恢复监控")
        if self.game_monitor:
            # 重置重启相关状态
            self._recent_trigger_count = 0
            self._consecutive_cooldown_count = 0
            self.game_monitor.strategy_engine.emergency_stop_triggered = False
            self.game_monitor.strategy_engine.total_trigger_count = 0
            self.game_monitor.strategy_engine.last_alert_time = time.time()  # 设为当前时间，避免立即触发冷却检测

            # 标记为重启恢复中，跳过首次窗口检测的重启触发
            self.game_monitor._restart_recovery = True

            # 在新线程中启动监控，避免 _monitor_loop 的 while 循环阻塞重启线程
            def _start_in_thread():
                try:
                    self.game_monitor.start()
                finally:
                    self.game_monitor._restart_recovery = False

            monitor_thread = threading.Thread(target=_start_in_thread, daemon=True)
            monitor_thread.start()

    # === 辅助方法 ===

    def _find_rundll32_window(self):
        """查找rundll32.exe窗口：先按进程查找窗口句柄，再OCR确认'音乐盒子'字样"""
        import subprocess
        # 枚举所有窗口，找到属于rundll32.exe进程的窗口
        EnumWindows = ctypes.windll.user32.EnumWindows
        GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
        IsWindowVisible = ctypes.windll.user32.IsWindowVisible
        GetWindowTextW = ctypes.windll.user32.GetWindowTextW
        GetClassNameW = ctypes.windll.user32.GetClassNameW

        # 获取rundll32.exe的PID列表
        try:
            result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq rundll32.exe', '/FO', 'CSV', '/NH'],
                                    capture_output=True, text=True, timeout=10)
            pids = set()
            for line in result.stdout.strip().split('\n'):
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2 and parts[0].lower() == 'rundll32.exe':
                    pids.add(int(parts[1]))
        except Exception:
            pids = set()

        if not pids:
            return None

        # 枚举窗口找匹配PID的可见窗口
        found_hwnds = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_callback(hwnd, lparam):
            if IsWindowVisible(hwnd):
                pid = ctypes.c_ulong()
                GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in pids:
                    found_hwnds.append(hwnd)
            return True

        EnumWindows(enum_callback, 0)

        if not found_hwnds:
            return None

        # 在找到的窗口中通过OCR确认"音乐盒子"字样
        target_text = self.restart_config.get('rundll32_title', '音乐盒子')
        for hwnd in found_hwnds:
            try:
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                if rect.right - rect.left < 50 or rect.bottom - rect.top < 50:
                    continue
                img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
                if self.game_monitor and self.game_monitor.ocr_engine:
                    text = self.game_monitor.ocr_engine.recognize(img)
                    if target_text in text:
                        return hwnd
            except Exception:
                pass

        # OCR未确认则返回第一个找到的窗口
        return found_hwnds[0] if found_hwnds else None

    def _wait_for_window(self, title='', class_name='', timeout=30):
        """等待指定窗口出现"""
        start = time.time()
        while time.time() - start < timeout:
            hwnd = ctypes.windll.user32.FindWindowW(
                class_name if class_name else None,
                title if title else None
            )
            if hwnd:
                return hwnd
            time.sleep(1)
        logging.warning(f"[重启] 等待窗口超时({timeout}s): {title}")

    def _wait_for_ocr_text(self, hwnd, text, timeout=60):
        """等待窗口中出现指定文字"""
        start = time.time()
        while time.time() - start < timeout:
            try:
                rect = ctypes.wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
                if self.game_monitor and self.game_monitor.ocr_engine:
                    ocr_text = self.game_monitor.ocr_engine.recognize(img)
                    if text in ocr_text:
                        return True
            except Exception:
                pass
            time.sleep(2)
        logging.warning(f"[重启] 等待文字'{text}'超时")

    def _activate_window(self, hwnd):
        """激活窗口（强制前台，使用AttachThreadInput确保获取焦点）"""
        try:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            # 获取前台窗口和目标窗口的线程ID
            foreground_tid = ctypes.windll.user32.GetWindowThreadProcessId(
                ctypes.windll.user32.GetForegroundWindow(), None)
            target_tid = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)
            # 附加线程输入队列，使目标线程能接收键盘焦点
            if foreground_tid != target_tid:
                ctypes.windll.user32.AttachThreadInput(foreground_tid, target_tid, True)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            ctypes.windll.user32.BringWindowToTop(hwnd)
            time.sleep(0.1)
            if foreground_tid != target_tid:
                ctypes.windll.user32.AttachThreadInput(foreground_tid, target_tid, False)
            time.sleep(0.3)
        except Exception:
            pass

    def _click_window_pos(self, hwnd, x, y):
        """点击窗口内指定坐标"""
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        abs_x = rect.left + x
        abs_y = rect.top + y
        # 移动鼠标并点击
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        ctypes.windll.user32.SetCursorPos(abs_x, abs_y)
        time.sleep(0.1)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.3)

    def _click_image_button(self, hwnd, image_path, confidence=0.8):
        """通过图像匹配在窗口中找到按钮并点击，返回是否成功"""
        if not image_path or not os.path.isfile(image_path):
            logging.warning(f"[重启] 按钮图片不存在: {image_path}")
            return False
        try:
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            screen_img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
            screen_arr = np.array(screen_img)
            screen_arr = cv2.cvtColor(screen_arr, cv2.COLOR_RGB2BGR)

            # 加载模板图片
            template = cv2.imread(image_path, cv2.IMREAD_COLOR)
            if template is None:
                logging.warning(f"[重启] 无法读取图片: {image_path}")
                return False

            th, tw = template.shape[:2]
            if th > screen_arr.shape[0] or tw > screen_arr.shape[1]:
                logging.warning(f"[重启] 模板图片({tw}x{th})大于窗口画面({screen_arr.shape[1]}x{screen_arr.shape[0]})")
                return False

            # 模板匹配
            result = cv2.matchTemplate(screen_arr, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            if max_val >= confidence:
                # 匹配成功，点击中心位置
                match_x = max_loc[0] + tw // 2
                match_y = max_loc[1] + th // 2
                abs_x = rect.left + match_x
                abs_y = rect.top + match_y
                logging.info(f"[重启] 图像匹配成功(置信度={max_val:.2f})，位置: ({match_x}, {match_y})")

                # 激活窗口后点击
                self._activate_window(hwnd)
                time.sleep(0.2)
                ctypes.windll.user32.SetCursorPos(abs_x, abs_y)
                time.sleep(0.1)
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
                time.sleep(0.05)
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
                time.sleep(0.3)
                return True
            else:
                logging.warning(f"[重启] 图像匹配失败(置信度={max_val:.2f} < {confidence})")
                return False
        except Exception as e:
            logging.error(f"[重启] 图像匹配异常: {e}")
            return False

    def _click_ocr_button(self, hwnd, button_text):
        """通过OCR识别窗口中的文字，找到匹配的按钮并点击，返回是否成功"""
        if not button_text:
            logging.warning("[重启] 按钮文字为空")
            return False
        try:
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            screen_img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))

            if not self.game_monitor._get_ocr_engine():
                logging.warning("[重启] OCR引擎不可用")
                return False

            items = self.game_monitor._get_ocr_engine().recognize_with_pos(screen_img)
            norm_btn = self._normalize_match_text(button_text)
            candidates = []
            for text, cx, cy in items:
                norm_t = self._normalize_match_text(text)
                if norm_btn in norm_t:
                    candidates.append((abs(len(norm_t) - len(norm_btn)), text, cx, cy))
            if candidates:
                candidates.sort(key=lambda x: x[0])
                _, best_text, cx, cy = candidates[0]
                # 多词偏移（同_click_ocr_in_game）
                norm_t = self._normalize_match_text(best_text)
                if len(norm_t) > len(norm_btn) + 1:
                    idx = norm_t.find(norm_btn)
                    if idx >= 0:
                        char_width = 15
                        offset_x = int((idx + len(norm_btn) / 2) * char_width
                                       - len(norm_t) / 2 * char_width)
                        cx += offset_x
                        logging.info(f"[重启] 多词偏移: '{button_text}'在'{best_text}'中位置{idx}，偏移{offset_x}px")
                abs_x = rect.left + cx
                abs_y = rect.top + cy
                logging.info(f"[重启] OCR匹配到'{button_text}'（OCR原文:'{best_text}'），位置: ({cx}, {cy})")
                self._activate_window(hwnd)
                time.sleep(0.2)
                ctypes.windll.user32.SetCursorPos(abs_x, abs_y)
                time.sleep(0.1)
                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
                time.sleep(0.05)
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
                time.sleep(0.3)
                return True
            logging.warning(f"[重启] OCR未匹配到'{button_text}'，识别结果: {[t for t, _, _ in items]}")
            return False
        except Exception as e:
            logging.error(f"[重启] OCR点击异常: {e}")
            return False

    def _send_key(self, key, presses=1, interval=0.3):
        """发送按键（SendInput + 扫描码 + 线程Attach，兼容DirectX游戏）"""
        key_map = {
            'space': 0x20, 'escape': 0x1B, 'esc': 0x1B,
            'm': 0x4D, 'f11': 0x7A, 'f12': 0x7B,
            'enter': 0x0D, 'tab': 0x09,
            'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10,
            '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33,
            '4': 0x34, '5': 0x35, '6': 0x36, '7': 0x37,
            '8': 0x38, '9': 0x39,
            'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44,
            'e': 0x45, 'f': 0x46, 'g': 0x47, 'h': 0x48,
            'i': 0x49, 'j': 0x4A, 'k': 0x4B, 'l': 0x4C,
            'm': 0x4D, 'n': 0x4E, 'o': 0x4F, 'p': 0x50,
            'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
            'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58,
            'y': 0x59, 'z': 0x5A,
        }
        vk = key_map.get(key.lower(), 0)
        if vk == 0:
            logging.warning(f"[重启] 未知按键: {key}")
            return
        try:
            KEYEVENTF_KEYUP = 0x0002
            KEYEVENTF_SCANCODE = 0x0008
            INPUT_KEYBOARD = 1

            # 使用 MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) 获取扫描码
            MAPVK_VK_TO_VSC = 0
            scan = ctypes.windll.user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)

            # 发送按键前确保目标窗口线程与当前线程输入队列关联
            # 先获取前台窗口句柄（SendInput 输入会送到前台窗口）
            foreground_hwnd = ctypes.windll.user32.GetForegroundWindow()
            # 查找游戏窗口（假设游戏窗口标题包含 "The Division"）
            game_title = self.restart_config.get('game_title', '') or self.config.window.get('title', '')
            game_hwnd = ctypes.windll.user32.FindWindowW(None, game_title) if game_title else None

            need_attach = False
            foreground_tid = 0
            target_tid = 0
            if game_hwnd and game_hwnd != foreground_hwnd:
                foreground_tid = ctypes.windll.user32.GetWindowThreadProcessId(foreground_hwnd, None)
                target_tid = ctypes.windll.user32.GetWindowThreadProcessId(game_hwnd, None)
                if foreground_tid != target_tid:
                    ctypes.windll.user32.AttachThreadInput(foreground_tid, target_tid, True)
                    need_attach = True
                    ctypes.windll.user32.SetForegroundWindow(game_hwnd)
                    time.sleep(0.05)

            for _ in range(presses):
                inp_down = _INPUT()
                inp_down.type = INPUT_KEYBOARD
                inp_down.union.ki.wVk = 0
                inp_down.union.ki.wScan = scan
                inp_down.union.ki.dwFlags = KEYEVENTF_SCANCODE
                inp_down.union.ki.time = 0
                inp_down.union.ki.dwExtraInfo = 0
                sent = ctypes.windll.user32.SendInput(1, ctypes.byref(inp_down), _INPUT_SIZE)
                if sent != 1:
                    logging.warning(f"[重启] SendInput down 失败，返回值={sent}")
                time.sleep(0.05)

                inp_up = _INPUT()
                inp_up.type = INPUT_KEYBOARD
                inp_up.union.ki.wVk = 0
                inp_up.union.ki.wScan = scan
                inp_up.union.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
                inp_up.union.ki.time = 0
                inp_up.union.ki.dwExtraInfo = 0
                sent = ctypes.windll.user32.SendInput(1, ctypes.byref(inp_up), _INPUT_SIZE)
                if sent != 1:
                    logging.warning(f"[重启] SendInput up 失败，返回值={sent}")
                time.sleep(interval)

            # 解除线程关联
            if need_attach:
                ctypes.windll.user32.AttachThreadInput(foreground_tid, target_tid, False)

        except Exception as e:
            logging.warning(f"[重启] 发送按键失败: {e}")


def main():
    print("""
╔═══════════════════════════════════════════════════════════╗
║              游戏监控程序 - 频率检测模式                    ║
╠═══════════════════════════════════════════════════════════╣
║  功能: 监控游戏脚本运行状态，检测卡脚本并自动处理           ║
║  模式: 频率检测 (统计单位时间内编号出现频率)                ║
╠═══════════════════════════════════════════════════════════╣
║  热键:                                                    ║
║    F8  - 开始/停止监控                                     ║
║    F10 - 暂停/恢复监控                                     ║
║    F12 - 退出程序                                         ║
╚═══════════════════════════════════════════════════════════╝
""")
    print("提示: 运行 GUI 版本请执行: python game_monitor_gui.py")
    print("      运行命令行版本请执行: python game_monitor.py --cli")
    print()


if __name__ == '__main__':
    main()


