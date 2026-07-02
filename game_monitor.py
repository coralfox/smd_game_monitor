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
                    "actions": [{"type": "key_press", "key": "p", "presses": 1}]
                },
                "single_stuck": {
                    "name": "单一卡死处理",
                    "description": "当检测到单一事件卡死时执行",
                    "match_ids": [],
                    "match_stuck_type": "single",
                    "actions": [{"type": "key_press", "key": "p", "presses": 1}]
                },
                "alternating_stuck": {
                    "name": "交替卡死处理",
                    "description": "当检测到两个事件交替卡死时执行",
                    "match_ids": [],
                    "match_stuck_type": "alternating",
                    "actions": [{"type": "key_press", "key": "p", "presses": 2}]
                },
                "path_error": {
                    "name": "路径错误处理",
                    "description": "当检测到路径相关错误时执行",
                    "match_ids": ["路径", "错误"],
                    "match_stuck_type": "single",
                    "actions": [{"type": "key_press", "key": "p", "presses": 1}]
                },
                "no_bounty_stuck": {
                    "name": "无悬赏卡死处理",
                    "description": "当未检测到悬赏时，如果发生单一卡死则执行",
                    "match_ids": [],
                    "exclude_ids": ["悬赏"],
                    "match_stuck_type": "single",
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
        if result and result[0]:
            for line in result[0]:
                text = line[1]
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
        """截图动作：截取整个游戏窗口，保存到异常子目录"""
        import ctypes
        from ctypes import wintypes as w
        from datetime import datetime

        if not self.window_hwnd:
            logging.warning("[截图动作] 未设置窗口句柄，无法截图")
            return

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
        for strategy_key, match_ids, exclude_ids in self._strategy_keyword_groups:
            # 排除匹配：使用完整多行文本检查，避免单行漏检
            check_text = full_text if full_text else script_id
            if exclude_ids and any(kw in check_text for kw in exclude_ids):
                continue
            # 正向匹配：使用完整多行文本检查
            if match_ids and not all(kw in check_text for kw in match_ids):
                continue
            if strategy_key not in self.strategy_samples:
                self.strategy_samples[strategy_key] = []
            # 对于只有exclude_ids没有match_ids的排除型策略，添加策略标记样本
            # 这样策略只检测"排除条件未触发"的频率，而不是普通事件的频率
            if not match_ids and exclude_ids:
                sample_id = f"__{strategy_key}__"
            else:
                sample_id = script_id
            self.strategy_samples[strategy_key].append((now, sample_id))
            added = True
        if not added:
            if '_unmatched' not in self.strategy_samples:
                self.strategy_samples['_unmatched'] = []
            self.strategy_samples['_unmatched'].append((now, script_id))
        self._cleanup_old_samples(now)

    def _cleanup_old_samples(self, now: float):
        cutoff = now - self.window_seconds
        for key in list(self.strategy_samples.keys()):
            self.strategy_samples[key] = [(t, sid) for t, sid in self.strategy_samples[key] if t > cutoff]
            if not self.strategy_samples[key]:
                del self.strategy_samples[key]

    def _analyze_queue(self, samples: list, match_stuck_type: str = 'any',
                       stuck_threshold: int = None, stuck_ratio: float = None,
                       alternating_threshold: int = None, alternating_ratio: float = None) -> dict:
        from collections import Counter

        st = stuck_threshold if stuck_threshold is not None else self.stuck_threshold
        sr = stuck_ratio if stuck_ratio is not None else self.stuck_ratio
        at = alternating_threshold if alternating_threshold is not None else self.alternating_threshold
        ar = alternating_ratio if alternating_ratio is not None else self.alternating_ratio

        ids = [sid for _, sid in samples if sid]
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
        strategies = self.config.data.get('strategies', {})
        results = []
        for strategy_key, samples in self.strategy_samples.items():
            if strategy_key == '_unmatched' or len(samples) < self.min_samples:
                continue
            strategy = strategies.get(strategy_key, {})
            match_type = strategy.get('match_stuck_type', 'any')
            r = self._analyze_queue(
                samples, match_type,
                stuck_threshold=strategy.get('stuck_threshold'),
                stuck_ratio=strategy.get('stuck_ratio'),
                alternating_threshold=strategy.get('alternating_threshold'),
                alternating_ratio=strategy.get('alternating_ratio')
            )
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
            best = max(single_results, key=lambda x: x['total'])
            del best['_strategy_key']
            return best

        alternating_results = [r for r in results if r['stuck_type'] == 'alternating']
        if alternating_results:
            best = max(alternating_results, key=lambda x: x['total'])
            del best['_strategy_key']
            return best

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

    def _record_trigger(self):
        self.total_trigger_count += 1
        now = time.time()
        self.trigger_history.append(now)
        # 检测时间窗口 = 触发冷却 × 阈值 × 2
        cooldown = self.config.data.get('frequency', {}).get('cooldown_seconds', 30)
        threshold = self.config.alert.get('alert_trigger_threshold', 6)
        detect_window = cooldown * threshold * 2
        self.trigger_history = [t for t in self.trigger_history if now - t <= detect_window]
        return len(self.trigger_history) >= threshold

    def get_stats(self) -> dict:
        if self.monitor_start_time is None:
            return {'runtime': 0, 'total_triggers': 0, 'triggers_per_hour': 0.0}
        runtime = time.time() - self.monitor_start_time
        hours = runtime / 3600.0 if runtime > 0 else 0
        tph = self.total_trigger_count / hours if hours > 0 else 0.0
        return {
            'runtime': runtime,
            'total_triggers': self.total_trigger_count,
            'triggers_per_hour': tph
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
        lines = [line.strip() for line in current_id.split('\n') if line.strip()]
        for line in lines:
            self.analyzer.add_sample(line, full_text=current_id)

        result = self.analyzer.analyze()
        if not result['is_stuck']:
            return

        cooldown = self.config.data.get('frequency', {}).get('cooldown_seconds', 30)
        now = time.time()
        if now - self.last_trigger_time < cooldown:
            return

        self.last_trigger_time = now

        stuck_ids = result['stuck_ids']
        stuck_type = result['stuck_type']

        for strategy_key in self._match_strategy(stuck_ids[0] if stuck_ids else ''):
            strategy = self.config.strategies.get(strategy_key)
            if not strategy:
                continue
            stuck_type_match = strategy.get('match_stuck_type', 'single')
            if stuck_type != stuck_type_match and stuck_type_match != 'any':
                continue

            logging.warning(f"触发策略 [{strategy.get('name', strategy_key)}] - {result['details']}")
            logging.info(f"[策略] 事件卡死: {stuck_ids[0] if stuck_ids else 'N/A'} | 占比: {result['top_ratio']:.1%} | 总计: {result['total']}")

            actions = strategy.get('actions', [])
            if actions:
                self.executor._current_strategy_name = strategy.get('name', strategy_key)
                self.executor.execute_actions(actions)

            # 触发后清空该策略对应的样本库，重新采集
            if strategy_key in self.analyzer.strategy_samples:
                del self.analyzer.strategy_samples[strategy_key]
                logging.info(f"[策略] 清空策略 '{strategy_key}' 的样本库，重新采集")

            if self._record_trigger():
                cooldown = self.config.data.get('frequency', {}).get('cooldown_seconds', 30)
                threshold = self.config.alert.get('alert_trigger_threshold', 6)
                detect_window = cooldown * threshold * 2
                logging.warning("=" * 50)
                logging.warning(f"警告: {detect_window}秒内连续触发超过{threshold}次，脚本可能完全卡死！发送报警")
                logging.warning("=" * 50)
                stats = self.get_stats()
                content = (
                    f"{detect_window}秒内连续触发超过{threshold}次，脚本可能完全卡死！\n"
                    f"运行时间: {self._fmt_time(stats['runtime'])}\n"
                    f"总触发次数: {stats['total_triggers']}\n"
                    f"触发频率: {stats['triggers_per_hour']:.1f} 次/时"
                )
                self._send_alert("游戏监控-触发频率过高警告", content)
                break

    def _send_alert(self, title: str, content: str):
        """发送报警信息（异步，不阻塞）- 根据配置选择PushPlus和/或邮件"""
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
                    'token': token, 'title': title, 'content': content
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
                msg = MIMEText(content, 'plain', 'utf-8')
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

    def _emergency_stop(self):
        self.emergency_stop_triggered = True
        logging.error("=" * 60)
        logging.error("检测到脚本完全卡死！执行紧急停止")
        logging.error("=" * 60)

        # 发送报警
        stats = self.get_stats()
        content = (
            f"检测到脚本完全卡死，已执行紧急停止。\n"
            f"运行时间: {self._fmt_time(stats['runtime'])}\n"
            f"总触发次数: {stats['total_triggers']}\n"
            f"触发频率: {stats['triggers_per_hour']:.1f} 次/时"
        )
        self._send_alert("游戏监控-紧急停止", content)

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
            fh.setLevel(logging.INFO)
            fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
            root_logger.addHandler(fh)

        self.screen_capture = ScreenCapture(self.config)
        self.ocr_engine = OCREngine(self.config)
        self.executor = ActionExecutor(self.config)
        self.frequency_analyzer = FrequencyAnalyzer(self.config)
        self.analyzer = self.frequency_analyzer
        self.strategy_engine = StrategyEngine(self.config, self.executor, self.frequency_analyzer,
                                               self.screen_capture, self.ocr_engine)
        self.running = False
        self.paused = False
        self.current_script_id = ""
        self.stable_count = 0

    def start(self):
        self.strategy_engine.monitor_start_time = time.time()
        self.strategy_engine.total_trigger_count = 0
        self.strategy_engine.trigger_history = []

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
                    counts_str = ', '.join([f"{k}={v}" for k, v in list(result['counts'].items())[:5]])
                    queue_info = ', '.join([f"{k}={len(v)}" for k, v in self.analyzer.strategy_samples.items() if k != '_unmatched'])
                    logging.info(f"[统计] {queue_info} | {counts_str} | {result['details']}")
                    self._last_status_print = now

                sleep_steps = max(1, int(check_interval / 0.1))
                for _ in range(sleep_steps):
                    if not self.running:
                        logging.debug("[_monitor_loop] 睡眠中检测到 running=False，提前退出")
                        break
                    time.sleep(0.1)

            except Exception as e:
                logging.error(f"监控循环异常: {e}")
                import traceback
                logging.debug(traceback.format_exc())

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
