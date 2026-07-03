import os
import sys
import time
import json
import re
import logging
import threading
from datetime import datetime
from collections import Counter, deque
from typing import List, Dict, Tuple, Optional
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageGrab, ImageDraw, ImageFont
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# 可选的OCR引擎
try:
    from rapidocr_onnxruntime import RapidOCR
    RAPIDOCR_AVAILABLE = True
except ImportError:
    RAPIDOCR_AVAILABLE = False

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
                "check_interval": 0.5,
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
                    "actions": [{"type": "key_press", "key": "p", "presses": 1}]
                },
                "single_stuck": {
                    "name": "单一移动卡死处理",
                    "description": "当检测到单一移动事件卡死时执行（60秒窗口）",
                    "match_ids": ["当前事件", "移动"],
                    "exclude_ids": [],
                    "match_stuck_type": "single",
                    "severity": 1.0,
                    "actions": [{"type": "screenshot"}, {"type": "key_press", "key": "p", "presses": 2, "interval": 0.5}],
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
                    "actions": [{"type": "screenshot"}, {"type": "key_press", "key": "p", "presses": 2, "interval": 0.5}],
                    "stuck_threshold": 200, "stuck_ratio": 0.8
                },
                "alternating_stuck": {
                    "name": "交替卡死处理",
                    "description": "当检测到两个事件交替卡死时执行",
                    "match_ids": ["当前事件"],
                    "exclude_ids": [],
                    "match_stuck_type": "alternating",
                    "severity": 2.0,
                    "actions": [{"type": "key_press", "key": "p", "presses": 2}]
                },
                "path_error": {
                    "name": "路径错误处理",
                    "description": "当检测到路径相关错误时执行",
                    "match_ids": ["路径", "错误"],
                    "match_stuck_type": "single",
                    "severity": 2.0,
                    "actions": [{"type": "key_press", "key": "p", "presses": 1}]
                },
                "no_bounty_stuck": {
                    "name": "无悬赏卡死处理",
                    "description": "当未检测到悬赏时，如果发生单一卡死则执行",
                    "match_ids": [],
                    "exclude_ids": ["悬赏"],
                    "match_stuck_type": "single",
                    "severity": 1.0,
                    "actions": [{"type": "key_press", "key": "p", "presses": 1}]
                }
            },
            "logging": {"level": "INFO", "log_to_file": True, "log_file": "game_monitor.log", "save_screenshots": True, "screenshot_dir": "screenshots"},
            "hotkeys": {"start_stop": "F8", "pause_resume": "F10"},
            "ui_options": {"always_on_top_game": False, "show_floating_stats": True},
            "alert": {
                "pushplus_enabled": False, "pushplus_token": "",
                "email_enabled": False,
                "email_smtp_server": "", "email_smtp_port": 465, "email_use_ssl": True,
                "email_user": "", "email_password": "", "email_to": "",
                "alert_cooldown_minutes": 15,
                "alert_trigger_threshold": 6
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
    def strategies(self):
        return self.data.get('strategies', {})

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
        import ctypes
        import ctypes.wintypes

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
        import ctypes
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
        if self.config.window.get('use_window', False) and self.window_rect:
            self._cap_left = self.window_rect[0] + region.get('left', 0)
            self._cap_top = self.window_rect[1] + region.get('top', 0)
        else:
            self._cap_left = region.get('left', 0)
            self._cap_top = region.get('top', 0)
        self._cap_width = region.get('width', 200)
        self._cap_height = region.get('height', 100)

    def capture_region(self) -> Image.Image:
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

    def _capture_gdi(self) -> Image.Image:
        import ctypes
        from ctypes import wintypes

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
                    ('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG),
                    ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                    ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                    ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                    ('biClrImportant', wintypes.DWORD)
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
        self.last_result = ""
        self.ocr = self._get_ocr_instance()
        # 预热：让 ONNX Runtime 完成模型加载，避免第一次识别在监控循环中卡住
        try:
            import numpy as np
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

    @staticmethod
    def _normalize_ocr_text(text: str) -> str:
        """标准化OCR文本：统一容易混淆的符号"""
        import re
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
        import ctypes
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
            if action_type == 'key_press':
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
        try:
            import base64, io, json, urllib.request, urllib.parse
            from PIL import Image as PILImage
            if image_path and os.path.isfile(image_path):
                img = PILImage.open(image_path)
            elif image_data is not None:
                img = image_data
            else:
                return ''
            # 缩小尺寸以适应推送，最大宽度400px
            max_w = 400
            if img.width > max_w:
                ratio = max_w / img.width
                img = img.resize((max_w, int(img.height * ratio)), PILImage.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
            upload_data = urllib.parse.urlencode({
                'key': imgbb_key,
                'image': b64,
                'expiration': 86400
            }).encode('utf-8')
            upload_req = urllib.request.Request(
                'https://api.imgbb.com/1/upload',
                data=upload_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                method='POST'
            )
            with urllib.request.urlopen(upload_req, timeout=10) as upload_resp:
                upload_result = json.loads(upload_resp.read().decode('utf-8'))
                if upload_result.get('success'):
                    url = upload_result['data']['url']
                    logging.info(f"[图床] 截图已上传: {url}")
                    return url
                else:
                    logging.warning(f"[图床] 上传失败: {upload_result}")
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

    def _key_press(self, action: Dict):
        import ctypes
        key = action.get('key', '')
        presses = action.get('presses', 1)
        duration = action.get('duration', 0.1)

        # 发送按键前确保游戏窗口在前台
        self._activate_window()

        vk_code = self._get_vk_code(key)
        if not vk_code:
            logging.warning(f"无法映射按键: {key}")
            return

        for _ in range(presses):
            ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
            time.sleep(duration)
            ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)
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
        }
        if key in key_map:
            return key_map[key]
        if len(key) == 1:
            return ord(key.upper())
        return 0

    def _mouse_click(self, action: Dict):
        import ctypes
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
        import ctypes
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
        import ctypes
        from ctypes import wintypes as w
        from datetime import datetime

        if not self.window_hwnd:
            logging.warning("[截图动作] 未设置窗口句柄，无法截图")
            return

        # 先激活窗口，确保前台显示
        self._activate_window()

        try:
            # 获取窗口矩形
            rect = w.RECT()
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
        from collections import Counter

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

        counts = Counter(ids)
        total = len(ids)
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

    def analyze(self) -> dict:
        from collections import Counter

        strategies = self.config.data.get('strategies', {})
        results = []

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
            r = self._analyze_queue(
                samples, match_type,
                stuck_threshold=strategy.get('stuck_threshold'),
                stuck_ratio=strategy.get('stuck_ratio'),
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


class StrategyEngine:
    """策略引擎 - 管理策略匹配和动作执行"""

    def __init__(self, config: Config, executor: ActionExecutor, analyzer: FrequencyAnalyzer,
                 screen_capture=None, ocr_engine=None):
        self.config = config
        self.executor = executor
        self.analyzer = analyzer
        self.screen_capture = screen_capture
        self.ocr_engine = ocr_engine
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
        self.trigger_history = [t for t in self.trigger_history if now - t.get('time', t) <= detect_window]
        # 计算窗口内总系数
        total_severity = sum(t.get('severity', 1.0) for t in self.trigger_history)
        severity_threshold = self.config.alert.get('alert_severity_threshold', 10)
        return total_severity >= severity_threshold

    def get_stats(self) -> dict:
        if self.monitor_start_time is None:
            return {'runtime': 0, 'total_triggers': 0, 'triggers_per_hour': 0.0}
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

        return {
            'runtime': runtime,
            'total_triggers': self.total_trigger_count,
            'triggers_per_hour': tph,
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
        # 将完整OCR文本作为整体添加一次，而非逐行添加
        self.analyzer.add_sample(current_id, full_text=current_id)

        result = self.analyzer.analyze()
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

            logging.warning(f"触发策略 [{strategy.get('name', strategy_key)}] - {r.get('details', '')}")
            logging.info(f"[策略] 事件卡死: {stuck_ids[0] if stuck_ids else 'N/A'} | 占比: {r.get('top_ratio', 0):.1%} | 总计: {r.get('total', 0)}")

            actions = strategy.get('actions', [])
            if actions:
                self.executor._current_strategy_name = strategy.get('name', strategy_key)
                self.executor.execute_actions(actions)

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
            import json
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

        import threading
        threading.Thread(target=_send_pushplus, daemon=True).start()
        threading.Thread(target=_send_email, daemon=True).start()

    def _build_alert_html(self, trigger_count, detect_window, threshold, stats,
                          strategy_name, stuck_type, stuck_ids, result):
        """构建 HTML 格式的报警内容"""
        from datetime import datetime
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
        import re
        text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'</(p|div|tr|h[1-6])>', '\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _build_stats_report_html(self) -> str:
        """构建运行统计报告 HTML"""
        from datetime import datetime
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        stats = self.get_stats()

        # 截取当前游戏画面并上传
        screenshot_html = ''
        try:
            current_screenshot = self.screen_capture.capture_region()
            if current_screenshot:
                screenshot_url = self.executor.upload_screenshot_to_imgbb(image_data=current_screenshot)
                if screenshot_url:
                    screenshot_html = f'''
  <div style="background:#0f3460;border-radius:12px;padding:16px;margin-bottom:16px;">
    <h3 style="color:#53a8b6;margin:0 0 12px 0;">📷 当前游戏画面</h3>
    <div style="text-align:center;">
      <img src="{screenshot_url}" style="max-width:100%%;border-radius:8px;" />
    </div>
  </div>'''
        except Exception as e:
            logging.debug(f"[统计报告] 截图上传失败: {e}")
        runtime = stats['runtime']
        total_triggers = stats['total_triggers']
        tph = stats['triggers_per_hour']

        # 从OCR文本中提取当前轮数
        current_round = self._last_known_round or '未知'
        round_text = str(current_round) if current_round != '未知' else '未知'

        # 轮数效率
        round_events = getattr(self, '_round_events', {})
        rounds_count = len(round_events)
        hours = runtime / 3600.0 if runtime > 0 else 0
        rounds_per_hour = rounds_count / hours if hours > 0 else 0

        # 策略触发统计
        strategy_counts = stats.get('strategy_trigger_counts', {})
        strategies = self.config.strategies
        strategy_rows = ''
        for key, count in sorted(strategy_counts.items(), key=lambda x: x[1], reverse=True):
            name = strategies.get(key, {}).get('name', key)
            pct = count / total_triggers * 100 if total_triggers > 0 else 0
            strategy_rows += f'''
      <tr>
        <td style="padding:6px 8px;border-bottom:1px solid #1a1a2e;font-size:13px;">{name}</td>
        <td style="padding:6px 8px;border-bottom:1px solid #1a1a2e;font-size:13px;">{count} 次</td>
        <td style="padding:6px 8px;border-bottom:1px solid #1a1a2e;font-size:13px;">{pct:.1f}%%</td>
        <td style="padding:6px 8px;width:40%%;border-bottom:1px solid #1a1a2e;">
          <div style="background:#1a1a2e;border-radius:4px;height:8px;overflow:hidden;">
            <div style="background:#4ecca3;height:100%%;width:{pct}%%;border-radius:4px;"></div>
          </div>
        </td>
      </tr>'''

        # 卡死事件统计
        event_counts = stats.get('stuck_event_counts', {})
        event_rows = ''
        for sid, count in sorted(event_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            pct = count / total_triggers * 100 if total_triggers > 0 else 0
            event_rows += f'''
      <tr>
        <td style="padding:4px 8px;color:#ccc;font-size:12px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{sid}</td>
        <td style="padding:4px 8px;font-size:12px;">{count} 次 ({pct:.1f}%%)</td>
        <td style="padding:4px 8px;width:35%%;">
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
            analysis_rows += f'''
      <tr>
        <td style="padding:4px 8px;color:#ccc;font-size:12px;">{sname}</td>
        <td style="padding:4px 8px;font-size:12px;">{len(samples)}</td>
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
      <tr><td style="padding:8px;color:#aaa;border-bottom:1px solid #1a1a2e;">轮数效率</td><td style="padding:8px;border-bottom:1px solid #1a1a2e;">{rounds_per_hour:.1f} 轮/时</td></tr>
      <tr><td style="padding:8px;color:#aaa;border-bottom:1px solid #1a1a2e;">已触发策略数</td><td style="padding:8px;color:#e94560;font-weight:bold;border-bottom:1px solid #1a1a2e;">{total_triggers} 次</td></tr>
      <tr><td style="padding:8px;color:#aaa;">触发频率</td><td style="padding:8px;">{tph:.1f} 次/时</td></tr>
    </table>
  </div>

  <div style="background:#0f3460;border-radius:12px;padding:16px;margin-bottom:16px;">
    <h3 style="color:#53a8b6;margin:0 0 12px 0;">📋 策略触发占比</h3>
    <table style="width:100%%;border-collapse:collapse;">
      <tr style="color:#888;font-size:11px;">
        <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">策略名称</th>
        <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">触发次数</th>
        <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">占比</th>
        <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #1a1a2e;"></th>
      </tr>
      {strategy_rows if strategy_rows else '<tr><td style="padding:8px;color:#666;" colspan="4">暂无触发记录</td></tr>'}
    </table>
  </div>

  <div style="background:#0f3460;border-radius:12px;padding:16px;margin-bottom:16px;">
    <h3 style="color:#53a8b6;margin:0 0 12px 0;">🔍 卡死事件占比</h3>
    <table style="width:100%%;border-collapse:collapse;">
      <tr style="color:#888;font-size:11px;">
        <th style="padding:4px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">事件ID</th>
        <th style="padding:4px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">次数</th>
        <th style="padding:4px 8px;text-align:left;border-bottom:1px solid #1a1a2e;"></th>
      </tr>
      {event_rows if event_rows else '<tr><td style="padding:8px;color:#666;" colspan="3">暂无卡死记录</td></tr>'}
    </table>
  </div>

  <div style="background:#0f3460;border-radius:12px;padding:16px;margin-bottom:16px;">
    <h3 style="color:#53a8b6;margin:0 0 12px 0;">📈 当前样本库</h3>
    <table style="width:100%%;border-collapse:collapse;">
      <tr style="color:#888;font-size:11px;">
        <th style="padding:4px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">策略</th>
        <th style="padding:4px 8px;text-align:left;border-bottom:1px solid #1a1a2e;">窗口内样本数</th>
      </tr>
      {analysis_rows if analysis_rows else '<tr><td style="padding:8px;color:#666;" colspan="2">暂无样本</td></tr>'}
    </table>
  </div>

  <div style="text-align:center;padding:12px;color:#666;font-size:12px;">
    SMD游戏监控程序 V{self.VERSION}
  </div>
</div>'''
        return html

    def _send_stats_report(self):
        """发送运行统计报告（定期调用）"""
        if not self.config.alert.get('stats_report_enabled', False):
            return
        # 检查是否有可用的推送渠道
        if not (self.config.alert.get('pushplus_enabled', False) or
                self.config.alert.get('email_enabled', False)):
            return

        from datetime import datetime
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
            import json, urllib.request
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

        import threading
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
            trigger_count=self.trigger_count,
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

        # 确保日志级别为 DEBUG（GUI中通过勾选控制显示），并添加文件 handler
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        log_file = self.config.logging_config.get('log_file', 'game_monitor.log')
        has_file_handler = any(isinstance(h, logging.FileHandler) for h in root_logger.handlers)
        if not has_file_handler:
            fh = logging.FileHandler(log_file, encoding='utf-8')
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
            root_logger.addHandler(fh)

        self.screen_capture = ScreenCapture(self.config)
        self.ocr_engine = OCREngine(self.config)
        self.executor = ActionExecutor(self.config)
        # 将图床API key传递给executor
        self.executor._imgbb_api_key = self.config.alert.get('imgbb_api_key', '')
        self.frequency_analyzer = FrequencyAnalyzer(self.config)
        self.analyzer = self.frequency_analyzer
        self.strategy_engine = StrategyEngine(self.config, self.executor, self.frequency_analyzer,
                                               self.screen_capture, self.ocr_engine)
        self.running = False
        self.paused = False
        self.current_script_id = ""
        self.stable_count = 0

        # 统计报告追踪
        self._last_stats_report_time = 0
        self._round_events = {}  # {轮数: 时间戳}
        self._last_known_round = None

    def start(self):
        self.strategy_engine.monitor_start_time = time.time()
        self.strategy_engine.total_trigger_count = 0
        self.strategy_engine.trigger_history = []
        self._last_stats_report_time = time.time()
        self._round_events = {}
        self._last_known_round = None

        self._setup_screenshot_dir()

        if self.config.window.get('use_window', False):
            if not self.screen_capture.find_window():
                logging.error("未找到游戏窗口，请检查配置")
                return
            hwnd = self.screen_capture.window_hwnd
            if hwnd:
                offset = (self.screen_capture.window_rect[0], self.screen_capture.window_rect[1]) if self.screen_capture.window_rect else None
                self.executor.set_window(hwnd, offset)

        self.running = True
        self._monitor_loop()

    def stop(self):
        self.running = False
        logging.info("[GameMonitor] stop() 已调用，running=False")

    def pause(self):
        self.paused = True
        logging.info("监控已暂停")

    def resume(self):
        self.paused = False
        logging.info("监控已恢复")

    def _monitor_loop(self):
        check_interval = float(self.config.monitor.get('check_interval', 0.5))
        min_stable = self.config.debounce.get('min_stable_frames', 2)
        freq_cfg = self.config.data.get('frequency', {})

        logging.info("=" * 50)
        logging.info("SMD游戏监控已启动 [频率检测模式]")
        logging.info(f"  监控区域: {self.config.monitor.get('region', {})}")
        logging.info(f"  检查间隔: {check_interval}s")
        logging.info(f"  统计窗口: {freq_cfg.get('window_seconds', 60)}s")
        logging.info(f"  热键: F8=开始/停止 | F10=暂停/恢复")
        logging.info("=" * 50)

        loop_count = 0
        while self.running:
            loop_count += 1
            logging.debug(f"[_monitor_loop] 第{loop_count}轮循环开始，running={self.running}")

            if self.strategy_engine.emergency_stop_triggered:
                logging.error("[紧急停止] 监控循环因脚本完全卡死而终止")
                self.running = False
                break

            if self.paused:
                time.sleep(0.1)
                continue

            try:
                logging.debug("[_monitor_loop] 开始截图...")
                screenshot = self.screen_capture.capture_region()
                logging.debug("[_monitor_loop] 截图完成")

                logging.debug("[_monitor_loop] 开始OCR...")
                raw_result = self.ocr_engine.recognize(screenshot)
                logging.debug(f"[_monitor_loop] OCR完成，结果长度={len(raw_result)}")

                # 追踪轮数变化
                for line in raw_result.split('\n'):
                    line = line.strip()
                    if '当前轮数' in line:
                        import re
                        m = re.search(r'当前轮数[-\s]*(\d+)', line)
                        if m:
                            new_round = int(m.group(1))
                            if new_round != self._last_known_round:
                                if self._last_known_round is not None:
                                    self._round_events[new_round] = time.time()
                                self._last_known_round = new_round
                        break

                if raw_result == self.current_script_id or not self.current_script_id:
                    self.stable_count += 1
                else:
                    self.stable_count = 1
                    self.current_script_id = raw_result

                if self.stable_count >= min_stable and raw_result:
                    self.strategy_engine.check_and_trigger(raw_result)

                result = self.analyzer.analyze()
                now = time.time()
                if not hasattr(self, '_last_status_print') or now - self._last_status_print >= 5:
                    self._last_status_print = now
                    queue_info = ', '.join([f"{k}={len(v)}" for k, v in self.analyzer.strategy_samples.items() if k != '_unmatched'])
                    if result.get('is_stuck') and result.get('results'):
                        details_list = [r.get('details', '') for r in result['results']]
                        details_str = ' | '.join(details_list)
                    else:
                        total_samples = result.get('total_samples', sum(len(s) for s in self.analyzer.strategy_samples.values()))
                        details_str = result.get('details', f'样本不足或未达到阈值 (总样本{total_samples})')
                    logging.info(f"[统计] {queue_info} | {details_str}")

                # 定期发送统计报告
                stats_interval = int(self.config.alert.get('stats_report_interval', 60)) * 60
                if stats_interval > 0 and now - self._last_stats_report_time >= stats_interval:
                    self._last_stats_report_time = now
                    self.strategy_engine._send_stats_report()

                sleep_steps = max(1, int(check_interval / 0.1))
                for _ in range(sleep_steps):
                    if not self.running:
                        logging.debug("[_monitor_loop] 睡眠中检测到 running=False，提前退出")
                        break
                    time.sleep(0.1)

            except Exception as e:
                import traceback
                logging.error(f"监控循环异常: {e}\n{traceback.format_exc()}")

        logging.info(f"[_monitor_loop] 循环已退出，共执行{loop_count}轮")

    def _setup_screenshot_dir(self):
        screenshot_dir = self.config.logging_config.get('screenshot_dir', 'screenshots')
        if os.path.exists(screenshot_dir):
            for f in os.listdir(screenshot_dir):
                if f.endswith('.png'):
                    try:
                        os.remove(os.path.join(screenshot_dir, f))
                    except:
                        pass
        else:
            os.makedirs(screenshot_dir, exist_ok=True)
        logging.info(f"截图目录已清空: {screenshot_dir}")

    def _save_debug_screenshot(self, original: Image.Image, processed: Image.Image,
                                ocr_result: str):
        def _do_save():
            try:
                screenshot_dir = self.config.logging_config.get('screenshot_dir', 'screenshots')
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

                if not os.path.exists(screenshot_dir):
                    os.makedirs(screenshot_dir, exist_ok=True)

                safe_name = re.sub(r'[<>:"\/\\|?*\s%]', '_', ocr_result) if ocr_result else 'empty'
                safe_name = safe_name[:50]

                for f in os.listdir(screenshot_dir):
                    if f.startswith('debug_') and f.endswith('.png'):
                        try:
                            os.remove(os.path.join(screenshot_dir, f))
                        except:
                            pass

                processed_path = os.path.join(screenshot_dir, f"debug_{timestamp}_{safe_name}.png")
                original.save(processed_path)
                logging.debug(f"调试截图已保存: {processed_path}")
            except Exception as e:
                logging.warning(f"保存调试截图失败: {e}")

        threading.Thread(target=_do_save, daemon=True).start()

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
