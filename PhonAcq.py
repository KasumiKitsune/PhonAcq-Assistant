# --- START OF FILE Dev.py ---

import os
import sys
import time
import random
import re
import json
import threading
import queue
from datetime import datetime
import importlib.util

# ==============================================================================
# 阶段一：绝对最小化导入，用于瞬时启动画面
# ==============================================================================
from PyQt5.QtWidgets import QApplication, QSplashScreen, QProgressBar
from PyQt5.QtGui import QPixmap, QColor, QFont, QIcon
from PyQt5.QtCore import Qt, QCoreApplication, QTimer

# --- 启动画面立即执行 ---
# 这部分代码在主程序块中立即执行，以最快速度显示启动画面。
if __name__ == "__main__":
    app = QApplication(sys.argv)

    def get_base_path_for_splash():
        """获取用于启动画面的基本路径，兼容打包和源码运行。"""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        else:
            return os.path.abspath(".")
    
    base_path_splash = get_base_path_for_splash()
    splash_pix = None
    splash_dir = os.path.join(base_path_splash, "assets", "splashes")
    if os.path.exists(splash_dir) and os.path.isdir(splash_dir):
        images = [f for f in os.listdir(splash_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp'))]
        if images:
            chosen_image_path = os.path.join(splash_dir, random.choice(images))
            splash_pix = QPixmap(chosen_image_path)
    
    if splash_pix is None or splash_pix.isNull():
        splash_pix = QPixmap(600, 350)
        splash_pix.fill(QColor("#FCEAE4"))

    splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
    splash.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    
    splash.progressBar = QProgressBar(splash)
    splash.progressBar.setGeometry(15, splash_pix.height() - 60, splash_pix.width() - 30, 24)
    splash.progressBar.setRange(0, 100)
    splash.progressBar.setValue(0)
    splash.progressBar.setTextVisible(False)
    splash.setFont(QFont("Microsoft YaHei", 10))
    
    # 硬编码样式以确保启动画面样式独立于外部文件
    hardcoded_style = """
        QProgressBar { 
            background-color: rgba(0, 0, 0, 120); 
            border: 1px solid rgba(255, 255, 255, 80); 
            border-radius: 12px; 
            text-align: center; 
            color: white; 
        }
        QProgressBar::chunk { 
            background-color: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #FFDBCF, stop: 1 #FCEAE4); 
            border-radius: 11px; 
        }
        QSplashScreen > QLabel { 
            background-color: rgba(0, 0, 0, 150); 
            color: white; 
            padding: 4px 8px; 
            border-radius: 4px; 
        }
    """
    splash.setStyleSheet(hardcoded_style)
    
    splash.show()
    splash.showMessage("正在准备环境...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
    
    app.processEvents()

# ==============================================================================
# 阶段二：延迟导入所有重量级库和应用模块
# ==============================================================================
# [修改] 导入 IconManager
from modules.icon_manager import IconManager
from modules.plugin_system import BasePlugin, PluginManager, PluginManagementDialog
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QListWidget, QListWidgetItem, QLineEdit, 
                             QFileDialog, QMessageBox, QComboBox, QSlider, QStyle, 
                             QFormLayout, QGroupBox, QCheckBox, QTabWidget, QScrollArea, 
                             QSpacerItem, QSizePolicy)
from PyQt5.QtGui import QIntValidator, QPainter, QPen, QBrush
from PyQt5.QtCore import QThread, pyqtSignal, QObject, pyqtProperty, QRect, QSize

try:
    import pandas as pd
    import openpyxl
    import sounddevice as sd 
    import soundfile as sf
    import numpy as np
    from gtts import gTTS
    import pypinyin
    import markdown 
except ImportError as e:
    if 'splash' in locals():
        splash.hide()
    QMessageBox.critical(None, "依赖库缺失", f"错误: {e}\n\n请运行: pip install PyQt5 pandas openpyxl sounddevice soundfile numpy gtts markdown pypinyin")
    sys.exit(1)


# --- 全局变量的完整定义 ---
BASE_PATH = get_base_path_for_splash()
CONFIG_DIR = os.path.join(BASE_PATH, "config")
WORD_LIST_DIR = os.path.join(BASE_PATH, "word_lists")
THEMES_DIR = os.path.join(BASE_PATH, "themes")
AUDIO_TTS_DIR = os.path.join(BASE_PATH, "audio_tts")
AUDIO_RECORD_DIR = os.path.join(BASE_PATH, "audio_record")
MODULES_DIR = os.path.join(BASE_PATH, "modules")
DEFAULT_ICON_DIR = os.path.join(BASE_PATH, "assets", "icons") # [新增] 默认图标目录
PLUGINS_DIR = os.path.join(BASE_PATH, "plugins") # 新增
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
TOOLTIPS_FILE = os.path.join(CONFIG_DIR, "tooltips.json")

tooltips_config = {}
MODULES = {}
main_config = {}
icon_manager = None # [新增] 全局图标管理器实例

def setup_and_load_config():
    """设置并加载配置文件，如果不存在则创建默认配置。"""
    if not os.path.exists(CONFIG_DIR): os.makedirs(CONFIG_DIR)
    default_settings = {
        "ui_settings": { "collector_sidebar_width": 320, "editor_sidebar_width": 280, "hide_all_tooltips": False },
        "audio_settings": { "sample_rate": 44100, "channels": 1, "recording_gain": 1.0, "input_device_index": None, "recording_format": "wav" },
        "file_settings": {"word_list_file": "", "participant_base_name": "participant", "results_dir": os.path.join(BASE_PATH, "Results")},
        "gtts_settings": {"default_lang": "en-us", "auto_detect": True},
        "app_settings": {"enable_logging": True},
        "theme": "default.qss"
    }
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_settings, f, indent=4)
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        # 确保所有默认键都存在于配置中
        updated = False
        for key, default_value_section in default_settings.items():
            if key not in config:
                config[key] = default_value_section
                updated = True
            elif isinstance(config[key], dict) and isinstance(default_value_section, dict):
                for sub_key, default_sub_value in default_value_section.items():
                    if sub_key not in config[key]:
                        config[key][sub_key] = default_sub_value
                        updated = True
        if updated:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
        return config
    except Exception:
        return default_settings

def ensure_directories_exist():
    """确保所有必需的应用程序目录都存在。"""
    required_paths = [
        CONFIG_DIR, WORD_LIST_DIR, THEMES_DIR, AUDIO_TTS_DIR, AUDIO_RECORD_DIR, MODULES_DIR,
        DEFAULT_ICON_DIR, # [新增] 确保默认图标目录存在
        PLUGINS_DIR,
        os.path.join(BASE_PATH, "assets", "flags"), 
        os.path.join(BASE_PATH, "assets", "help"),
        os.path.join(BASE_PATH, "assets", "splashes"), 
        os.path.join(BASE_PATH, "dialect_visual_wordlists"),
        main_config.get('file_settings', {}).get('results_dir', os.path.join(BASE_PATH, "Results"))
    ]
    for path in required_paths:
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as e:
                print(f"[ERROR] 创建文件夹失败: {path} - {e}", file=sys.stderr)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'modules')))
def load_modules(progress_offset=0, progress_scale=1.0):
    """动态加载所有位于 'modules' 目录下的模块。"""
    global MODULES
    MODULES = {}
    modules_dir = os.path.join(BASE_PATH, "modules")
    if not os.path.exists(modules_dir): os.makedirs(modules_dir)
    module_files = [f for f in os.listdir(modules_dir) if f.endswith('.py') and not f.startswith('__')]
    total_modules = len(module_files)
    for i, filename in enumerate(module_files):
        base_progress = progress_offset
        current_stage_progress = int(((i + 1) / total_modules) * (100 * progress_scale)) if total_modules > 0 else int(100 * progress_scale)
        if 'splash' in globals():
            splash.showMessage(f"加载模块: {filename} ...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            splash.progressBar.setValue(base_progress + current_stage_progress)
            QApplication.processEvents()
        module_name = filename[:-3]
        try:
            filepath = os.path.join(modules_dir, filename)
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            MODULES[module_name] = {
                'module': module, 
                'name': getattr(module, 'MODULE_NAME', module_name), 
                'desc': getattr(module, 'MODULE_DESCRIPTION', '无描述'), 
                'file': filename
            }
        except Exception as e:
            print(f"加载模块 '{filename}' 失败: {e}", file=sys.stderr)

def load_tooltips_config():
    """加载或创建工具提示的配置文件。"""
    default_tooltips = {
        "数据采集": { "description": "包含所有用于实时录制和收集语音数据的功能模块。", "sub_tabs": { "口音采集会话": "适用于标准的文本到语音朗读任务。", "语音包录制": "用于为标准词表录制高质量的真人提示音。" }},
        "方言研究": { "description": "专为方言学田野调查设计的工具集。", "sub_tabs": { "图文采集": "展示图片并录制方言描述。", "图文词表编辑": "在程序内直接创建、编辑和保存用于“图文采集”的词表。" }},
        "资源管理": { "description": "提供对项目所使用的词表和已生成的音频数据进行管理的工具。", "sub_tabs": { "词表编辑器": "可视化地创建和编辑标准词表。", "Excel转换器": "支持标准词表与图文词表的双向转换。", "数据管理器": "浏览、试听、重命名和删除所有已录制的音频数据。" }},
        "实用工具": { "description": "提供一系列辅助性的语言学工具。", "sub_tabs": { "拼音转IPA": "将汉字实时转换为国际音标。", "TTS 工具": "批量或即时将文本列表转换为语音文件。" }},
        "系统与帮助": { "description": "配置应用程序的行为、外观，并获取使用帮助。", "sub_tabs": { "程序设置": "调整应用的各项参数，包括UI布局、音频设备和主题皮肤等。", "帮助文档": "提供详细的程序使用指南和常见问题解答。" }}
    }
    if not os.path.exists(TOOLTIPS_FILE):
        try:
            with open(TOOLTIPS_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_tooltips, f, indent=4, ensure_ascii=False)
            return default_tooltips
        except Exception:
            return {}
    try:
        with open(TOOLTIPS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

class Logger:
    """一个简单的文件日志记录器。"""
    def __init__(self, fp):
        self.fp = fp
        with open(self.fp, 'a', encoding='utf-8') as f:
            f.write(f"\n--- Log started at {datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
    def log(self, msg):
        with open(self.fp, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] - {msg}\n")

# --- 建议放在 Dev.py 或一个专门的 aLgorithm_utils.py 中 ---

def detect_language(text):
    """
    根据文本中的字符范围、特征字母和高频词智能检测语言。
    (最终优化版：引入“杀手级特征”和权重调整，提升精准度)
    返回一个 gTTS 兼容的语言代码 (e.g., 'zh-cn', 'fr', 'en')。
    """
    if not text:
        return None

    text_lower = text.lower()
    text_length = len(text_lower)
    if text_length == 0:
        return None

    # --- 数据定义 (gTTS兼容) ---
    # [优化] 提升了非拉丁语系的权重
    RANGES = {
        'ja': (((0x3040, 0x309F), (0x30A0, 0x30FF)), 15.0, 1, 0.01), # 日语假名权重极高
        'ko': (((0xAC00, 0xD7A3), (0x1100, 0x11FF)), 10.0, 1, 0.1),
        'zh-cn': (((0x4E00, 0x9FFF),), 2.0, 1, 0.4),
        'ru': (((0x0400, 0x04FF),), 8.0, 2, 0.3),
        'hi': (((0x0900, 0x097F),), 10.0, 1, 0.1), # 提高印地语权重和降低阈值
        'ar': (((0x0600, 0x06FF),), 10.0, 1, 0.1), # 提高阿拉伯语权重
        'he': (((0x0590, 0x05FF),), 10.0, 1, 0.1), # 提高希伯来语权重
        'th': (((0x0E00, 0x0E7F),), 10.0, 1, 0.1), # 提高泰语权重
    }
    # [优化] 越南语的声调标记现在作为“杀手级特征”处理
    KILLER_FEATURES = {
        'de': 'ß',
        'es': '¿¡',
        'vi': 'ăâđêôơư' # 越南语基础变音字母，出现即是强证据
    }
    FEATURES = {
        'fr': "àâæçéèêëîïôœùûü", 'de': "äöü", 'es': "áéíóúüñ", # ß ñ 已移走
        'pt': "áàâãéêíóôõúç", 'it': "àèéìòù", 'pl': "ąćęłńóśźż",
        'tr': "çğıöşü", 'nl': "äëïöü"
    }
    STOP_WORDS = {
        'en': {'the', 'a', 'is', 'to', 'in', 'it', 'of', 'and', 'for', 'on'},
        'fr': {'le', 'la', 'de', 'et', 'est', 'un', 'une', 'je', 'tu'},
        'de': {'der', 'die', 'das', 'und', 'ist', 'ein', 'eine', 'ich', 'sie'},
        'es': {'el', 'la', 'de', 'y', 'es', 'un', 'una', 'en', 'que'},
        'pt': {'o', 'a', 'de', 'e', 'é', 'um', 'uma', 'em', 'que'},
        'it': {'il', 'la', 'di', 'e', 'è', 'un', 'una', 'che', 'in'},
        'nl': {'de', 'het', 'een', 'en', 'van', 'is', 'ik', 'in', 'op'}
    }

    scores = {}

    # 0. “杀手级特征”检测，一旦命中，直接返回
    for lang, chars in KILLER_FEATURES.items():
        if any(c in text_lower for c in chars):
            return lang

    # 1. 一级检测: 基于Unicode字符块
    meaningful_chars = 0; char_counts = {lang: 0 for lang in RANGES}
    for char in text:
        code = ord(char); is_meaningful = False
        for lang, (blocks, _, _, _) in RANGES.items():
            for start, end in blocks:
                if start <= code <= end:
                    char_counts[lang] += 1; is_meaningful = True; break
        if is_meaningful: meaningful_chars += 1
    
    if meaningful_chars > 0:
        for lang, count in char_counts.items():
            if count > 0:
                _, weight, min_chars, threshold = RANGES[lang]
                ratio = count / meaningful_chars
                if count >= min_chars and ratio >= threshold: scores[lang] = scores.get(lang, 0) + ratio * weight
    
    if scores: return max(scores, key=scores.get)

    # 2. 二级检测: 基于特征字母
    feature_counts = {lang: 0 for lang in FEATURES}
    for char in text_lower:
        for lang, letters in FEATURES.items():
            if char in letters: feature_counts[lang] += 1
    
    for lang, count in feature_counts.items():
        if count > 0: scores[lang] = scores.get(lang, 0) + count * 5.0

    if scores: return max(scores, key=scores.get)

    # 3. 三级检测: 基于高频词
    words = set(text_lower.split())
    # 英语优先检查
    if words.intersection(STOP_WORDS['en']): return 'en'
    # 其他语言检查
    for lang, stop_words in STOP_WORDS.items():
        if lang == 'en': continue
        if words.intersection(stop_words): scores[lang] = scores.get(lang, 0) + len(words.intersection(stop_words))
    
    if scores: return max(scores, key=scores.get)

    # 4. 最终回退
    is_basic_latin = all('a' <= char <= 'z' or char.isspace() or char in "'-.?!,;" for char in text_lower)
    if is_basic_latin and text_length > 0: return 'en'

    return None

class Worker(QObject):
    """用于在后台线程执行耗时任务的通用工作器。"""
    finished = pyqtSignal(object)
    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)
    def __init__(self, task, *args, **kwargs):
        super().__init__()
        self.task = task
        self.args = args
        self.kwargs = kwargs
    def run(self):
        try:
            res = self.task(self, *self.args, **self.kwargs)
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(f"后台任务失败: {e}")

class ToggleSwitch(QCheckBox):
    """一个可自定义样式的切换开关控件。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self._trackColorOff = QColor("#E0E0E0")
        self._trackColorOn = QColor("#8F4C33")
        self._knobColor = QColor("#FFFFFF")
        self._trackBorderRadius = 14
        self._knobMargin = 3
        self._knobShape = 'ellipse'
        self._knobBorderRadius = 0 
        self._borderColor = QColor(Qt.transparent)
        self._borderWidth = 0 
    
    # 定义可在样式表中设置的属性
    @pyqtProperty(QColor)
    def trackColorOff(self): return self._trackColorOff
    @trackColorOff.setter
    def trackColorOff(self, color): self._trackColorOff = color; self.update()

    @pyqtProperty(QColor)
    def trackColorOn(self): return self._trackColorOn
    @trackColorOn.setter
    def trackColorOn(self, color): self._trackColorOn = color; self.update()

    @pyqtProperty(QColor)
    def knobColor(self): return self._knobColor
    @knobColor.setter
    def knobColor(self, color): self._knobColor = color; self.update()

    @pyqtProperty(int)
    def trackBorderRadius(self): return self._trackBorderRadius
    @trackBorderRadius.setter
    def trackBorderRadius(self, radius): self._trackBorderRadius = radius; self.update()

    @pyqtProperty(int)
    def knobMargin(self): return self._knobMargin
    @knobMargin.setter
    def knobMargin(self, margin): self._knobMargin = margin; self.update()

    @pyqtProperty(str)
    def knobShape(self): return self._knobShape
    @knobShape.setter
    def knobShape(self, shape):
        if shape in ['ellipse', 'rectangle']: self._knobShape = shape; self.update()

    @pyqtProperty(int)
    def knobBorderRadius(self): return self._knobBorderRadius
    @knobBorderRadius.setter
    def knobBorderRadius(self, radius): self._knobBorderRadius = radius; self.update()

    @pyqtProperty(QColor)
    def borderColor(self): return self._borderColor
    @borderColor.setter
    def borderColor(self, color): self._borderColor = color; self.update()

    @pyqtProperty(int)
    def borderWidth(self): return self._borderWidth
    @borderWidth.setter
    def borderWidth(self, width): self._borderWidth = width; self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        # 绘制边框
        if self._borderWidth > 0 and self._borderColor.isValid() and self._borderColor.alpha() > 0:
            pen = QPen(self._borderColor, self._borderWidth)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            half_pen_width = self._borderWidth // 2
            border_rect = rect.adjusted(half_pen_width, half_pen_width, -half_pen_width, -half_pen_width)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(border_rect, self.trackBorderRadius, self.trackBorderRadius)

        # 绘制轨道
        p.setPen(Qt.NoPen)
        track_color = self.trackColorOn if self.isChecked() else self.trackColorOff
        p.setBrush(QBrush(track_color))
        track_rect = rect.adjusted(self._borderWidth, self._borderWidth, -self._borderWidth, -self._borderWidth)
        track_inner_radius = max(0, self.trackBorderRadius - self._borderWidth)
        p.drawRoundedRect(track_rect, track_inner_radius, track_inner_radius)
        
        # 绘制滑块
        margin = self.knobMargin
        knob_height = track_rect.height() - (2 * margin)
        knob_width = knob_height 
        x_pos = track_rect.right() - knob_width - margin + 1 if self.isChecked() else track_rect.left() + margin
        knob_rect = QRect(x_pos, track_rect.top() + margin, knob_width, knob_height)
        p.setBrush(QBrush(self.knobColor))
        if self.knobShape == 'rectangle':
            p.drawRoundedRect(knob_rect, self.knobBorderRadius, self.knobBorderRadius)
        else:
            p.drawEllipse(knob_rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self.isChecked())
            event.accept() 
        else:
            super().mousePressEvent(event)


def resolve_recording_device(config):
    """
    根据配置中的简易/专家模式，解析出最终要使用的物理设备索引。
    这是所有录音模块获取设备ID的唯一入口。
    """
    try:
        audio_settings = config.get("audio_settings", {})
        mode = audio_settings.get("input_device_mode", "manual")
        
        if mode == "manual":
            # 专家模式：直接返回保存的索引
            return audio_settings.get("input_device_index", None)

        if mode == "default":
            # 简易模式 - 系统默认
            return None

        devices = sd.query_devices()
        candidate_devices = []

        if mode == "loopback":
            # 寻找立体声混音
            for i, dev in enumerate(devices):
                if dev['max_input_channels'] > 0 and ('mix' in dev['name'].lower() or '混音' in dev['name']):
                    return i
            # 如果没找到，回退到系统默认
            return None 

        # 扫描所有输入设备
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                name_lower = dev['name'].lower()
                is_external = any(kw in name_lower for kw in ['usb', 'bluetooth', 'external'])
                is_internal = any(kw in name_lower for kw in ['internal', 'built-in', '内置'])
                
                # 排除立体声混音设备，除非模式明确是loopback
                if 'mix' in name_lower or '混音' in name_lower:
                    continue

                if mode == "external" and is_external:
                    candidate_devices.append({'index': i, 'name': name_lower})
                elif mode == "internal" and is_internal:
                    candidate_devices.append({'index': i, 'name': name_lower})
                elif mode == "smart":
                    if is_external:
                        # 在智能模式下，外置设备有最高优先级
                        candidate_devices.append({'index': i, 'name': name_lower, 'priority': 2})
                    elif is_internal:
                        candidate_devices.append({'index': i, 'name': name_lower, 'priority': 1})
        
        if candidate_devices:
            if mode == "smart":
                # 按优先级排序，优先级高的（外置）在前
                candidate_devices.sort(key=lambda x: x.get('priority', 0), reverse=True)
            # 返回找到的第一个（或优先级最高的）候选设备
            return candidate_devices[0]['index']

        # 如果根据模式没有找到任何匹配的设备，最终回退到系统默认
        return None

    except Exception as e:
        print(f"解析录音设备时出错: {e}", file=sys.stderr)
        # 出现任何异常都安全地回退到系统默认
        return None
class MainWindow(QMainWindow):
    def __init__(self, splash_ref=None, tooltips_ref=None):
        super().__init__()
        self.BASE_PATH = BASE_PATH
        self.splash_ref = splash_ref
        self.tooltips_config = tooltips_ref if tooltips_ref is not None else {}
        self.ToggleSwitch = ToggleSwitch
        if self.splash_ref:
            self.splash_ref.showMessage("初始化主窗口...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            self.splash_ref.progressBar.setValue(75)
            QApplication.processEvents()
            
        self.setWindowTitle("PhonAcq - 风纳客")
        # [新增] 定义默认和紧凑两种最小尺寸
        self.DEFAULT_MIN_SIZE = (1350, 1000)
        self.COMPACT_MIN_SIZE = (1100, 800)
        
        self.setGeometry(100, 100, self.DEFAULT_MIN_SIZE[0], self.DEFAULT_MIN_SIZE[1])
        self.setMinimumSize(self.DEFAULT_MIN_SIZE[0], self.DEFAULT_MIN_SIZE[1])

        icon_path = os.path.join(BASE_PATH, "config", "icon.ico") 
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.config = main_config
        self.main_tabs = QTabWidget()
        self.main_tabs.setObjectName("MainTabWidget")
        self.setCentralWidget(self.main_tabs)
        
        if self.splash_ref:
            self.splash_ref.showMessage("创建核心页面...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            self.splash_ref.progressBar.setValue(80)
            QApplication.processEvents()

        # 确保这些关键属性在任何其他逻辑之前被设置
        global icon_manager
        if icon_manager is None:
            icon_manager = IconManager(DEFAULT_ICON_DIR)
        self.icon_manager = icon_manager
        self.SETTINGS_FILE = SETTINGS_FILE 

        # --- [核心修正] 调整插件系统的初始化顺序 ---
        
        # 1. 实例化插件管理器
        self.plugin_manager = PluginManager(self, PLUGINS_DIR)
        
        # 2. 立即扫描插件以获取元数据
        self.plugin_manager.scan_plugins()
        
        # 3. 创建插件栏的UI框架
        self.setup_plugin_ui()
        
        # 4. 根据已扫描到的元数据，首次填充固定的插件
        self.update_pinned_plugins_ui() 
        
        # 5. 延迟加载并启用插件
        QTimer.singleShot(0, self.plugin_manager.load_enabled_plugins)

        # 页面创建
        self.accent_collection_page = self.create_module_or_placeholder('accent_collection_module', '标准朗读采集', 
            lambda m, ts, w, l, im, rdf: m.create_page(self, self.config, ts, w, l, detect_language, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH, im, rdf))

        self.voicebank_recorder_page = self.create_module_or_placeholder('voicebank_recorder_module', '提示音录制', 
            lambda m, ts, w, l, im, rdf: m.create_page(self, WORD_LIST_DIR, AUDIO_RECORD_DIR, ts, w, l, im, rdf))
        self.audio_manager_page = self.create_module_or_placeholder('audio_manager_module', '音频数据管理器', 
            lambda m, ts, im: m.create_page(self, self.config, BASE_PATH, self.config['file_settings'].get("results_dir"), AUDIO_RECORD_DIR, im, ts))
        self.wordlist_editor_page = self.create_module_or_placeholder('wordlist_editor_module', '通用词表编辑器', 
            lambda m, im, dl: m.create_page(self, WORD_LIST_DIR, im, dl))
        self.converter_page = self.create_module_or_placeholder('excel_converter_module', 'Excel转换器', 
            lambda m, im: m.create_page(self, WORD_LIST_DIR, MODULES, im))
        self.help_page = self.create_module_or_placeholder('help_module', '帮助文档', 
            lambda m: m.create_page(self))
        DIALECT_VISUAL_WORDLIST_DIR = os.path.join(BASE_PATH, "dialect_visual_wordlists")
        os.makedirs(DIALECT_VISUAL_WORDLIST_DIR, exist_ok=True)
        self.dialect_visual_page = self.create_module_or_placeholder('dialect_visual_collector_module', '看图说话采集', 
            lambda m, ts, w, l, im, rdf: m.create_page(self, self.config, BASE_PATH, DIALECT_VISUAL_WORDLIST_DIR, AUDIO_RECORD_DIR, ts, w, l, im, rdf))
        self.dialect_visual_editor_page = self.create_module_or_placeholder('dialect_visual_editor_module', '图文词表编辑器', 
            lambda m, ts, im: m.create_page(self, DIALECT_VISUAL_WORDLIST_DIR, ts, im))
        self.tts_utility_page = self.create_module_or_placeholder('tts_utility_module', 'TTS 工具',
            lambda m, ts, w, dl, std_wld, im: m.create_page(self, self.config, AUDIO_TTS_DIR, ts, w, dl, std_wld, im))
        self.flashcard_page = self.create_module_or_placeholder('flashcard_module', '速记卡',
            lambda m, ts_class, sil_class, bp_val, gtts_dir_val, gr_dir_val, im_val: \
        m.create_page(self, ts_class, sil_class, bp_val, gtts_dir_val, gr_dir_val, im_val)
        )
        self.settings_page = self.create_module_or_placeholder('settings_module', '程序设置',
            lambda m, ts, t_dir, w_dir: m.create_page(self, ts, t_dir, w_dir)) 
        self.audio_analysis_page = self.create_module_or_placeholder('audio_analysis_module', '音频分析', 
            lambda m, im, ts: m.create_page(self, im, ts))     
        # [修改] 日志查看器页面创建，注入 icon_manager
        self.log_viewer_page = self.create_module_or_placeholder('log_viewer_module', '日志查看器',
            lambda m, ts, im: m.create_page(self, self.config, ts, im))
        
        if self.splash_ref:
            self.splash_ref.showMessage("构建用户界面...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            self.splash_ref.progressBar.setValue(90)
            QApplication.processEvents()
        
        # 构建Tab结构
        collection_tabs = QTabWidget(); collection_tabs.setObjectName("SubTabWidget")
        collection_tabs.addTab(self.accent_collection_page, "标准朗读采集")
        collection_tabs.addTab(self.dialect_visual_page, "看图说话采集")
        collection_tabs.addTab(self.voicebank_recorder_page, "提示音录制")

        preparation_tabs = QTabWidget(); preparation_tabs.setObjectName("SubTabWidget")
        preparation_tabs.addTab(self.wordlist_editor_page, "通用词表编辑器")
        preparation_tabs.addTab(self.dialect_visual_editor_page, "图文词表编辑器")
        preparation_tabs.addTab(self.converter_page, "Excel转换器")
        
        management_tabs = QTabWidget(); management_tabs.setObjectName("SubTabWidget")
        management_tabs.addTab(self.audio_manager_page, "音频数据管理器")
        management_tabs.addTab(self.audio_analysis_page, "音频分析")
        management_tabs.addTab(self.log_viewer_page, "日志查看器")
        
        utilities_tabs = QTabWidget(); utilities_tabs.setObjectName("SubTabWidget")
        utilities_tabs.addTab(self.tts_utility_page, "TTS 工具")
        utilities_tabs.addTab(self.flashcard_page, "速记卡")
        
        system_tabs = QTabWidget(); system_tabs.setObjectName("SubTabWidget")
        system_tabs.addTab(self.settings_page, "程序设置")
        system_tabs.addTab(self.help_page, "帮助文档")
        
        self.main_tabs.addTab(collection_tabs, "数据采集")
        self.main_tabs.addTab(preparation_tabs, "数据准备")
        self.main_tabs.addTab(management_tabs, "资源管理")
        self.main_tabs.addTab(utilities_tabs, "实用工具")
        self.main_tabs.addTab(system_tabs, "系统与帮助")

        # 连接信号与槽
        self.main_tabs.currentChanged.connect(self.on_main_tab_changed)
        collection_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("数据采集", i))
        preparation_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("数据准备", i))
        management_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("资源管理", i))
        utilities_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("实用工具", i))
        system_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("系统与帮助", i))
        
        self.apply_tooltips()
        
        if self.splash_ref:
            self.splash_ref.showMessage("准备完成!", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            self.splash_ref.progressBar.setValue(100)
            QApplication.processEvents()
            
        self.apply_theme()
        self.on_main_tab_changed(0) # 初始加载第一个标签页

    # [新增] 用于模块间通信的槽函数
    def go_to_audio_analysis(self, filepath):
        """
        切换到音频分析模块并加载指定的文件。
        这是一个公共API，供其他模块调用。
        """
        if not hasattr(self, 'audio_analysis_page'):
            QMessageBox.warning(self, "功能缺失", "音频分析模块未成功加载。")
            return

        # 1. 找到“资源管理”主标签页并切换过去
        for i in range(self.main_tabs.count()):
            if self.main_tabs.tabText(i) == "资源管理":
                self.main_tabs.setCurrentIndex(i)
                # 2. 找到“音频分析”子标签页并切换过去
                sub_tab_widget = self.main_tabs.widget(i)
                if isinstance(sub_tab_widget, QTabWidget):
                    for j in range(sub_tab_widget.count()):
                        if sub_tab_widget.tabText(j) == "音频分析":
                            sub_tab_widget.setCurrentIndex(j)
                            # 确保UI更新
                            QApplication.processEvents()
                            # 3. 调用加载方法
                            self.audio_analysis_page.load_audio_file(filepath)
                            return

    def setup_and_load_config_external(self):
        """外部模块可调用的配置加载器"""
        return setup_and_load_config()

    def apply_tooltips(self):
        # ... (unchanged logic for main tabs and sub-tabs' tabToolTips) ...
        hide_tooltips = self.config.get("ui_settings", {}).get("hide_all_tooltips", False)

        for i in range(self.main_tabs.count()):
            main_tab_text = self.main_tabs.tabText(i)
            if hide_tooltips:
                self.main_tabs.setTabToolTip(i, "")
            else:
                main_tab_data = self.tooltips_config.get(main_tab_text, {})
                self.main_tabs.setTabToolTip(i, main_tab_data.get('description', f"{main_tab_text} 功能模块"))

            sub_tab_widget = self.main_tabs.widget(i)
            if isinstance(sub_tab_widget, QTabWidget):
                for j in range(sub_tab_widget.count()):
                    if hide_tooltips:
                        sub_tab_widget.setTabToolTip(j, "")
                    else:
                        sub_tabs_data = self.tooltips_config.get(main_tab_text, {}).get('sub_tabs', {})
                        sub_tab_text = sub_tab_widget.tabText(j)
                        sub_tab_widget.setTabToolTip(j, sub_tabs_data.get(sub_tab_text, "无详细描述。"))
    
        # [新增] 遍历所有已创建的模块页面，并调用其 update_tooltips 方法
        for page_attr_name in [attr for attr in dir(self) if attr.endswith('_page') or attr.endswith('_module')]: # 假设所有页面都有这个命名约定
            page = getattr(self, page_attr_name, None)
            if page and hasattr(page, 'update_tooltips'):
                try:
                    page.update_tooltips()
                except Exception as e:
                    print(f"更新模块 '{page_attr_name}' 的工具提示时出错: {e}")

    def create_module_or_placeholder(self, module_key, name, page_factory):
        """根据模块是否加载成功，创建真实页面或占位符页面。"""
        if module_key in MODULES:
            try:
                module = MODULES[module_key]['module']
                
                # --- 根据模块标识符注入不同依赖 ---
                if module_key == 'settings_module':
                    return page_factory(module, ToggleSwitch, THEMES_DIR, WORD_LIST_DIR)
                
                elif module_key == 'flashcard_module':
                    # ... (此模块逻辑不变) ...
                    from PyQt5.QtWidgets import QLabel 
                    ScalableImageLabelClass = QLabel
                    if 'dialect_visual_collector_module' in MODULES:
                        ScalableImageLabelClass = getattr(MODULES['dialect_visual_collector_module']['module'], 'ScalableImageLabel', QLabel)
                    return page_factory(module, ToggleSwitch, ScalableImageLabelClass, 
                                        BASE_PATH, AUDIO_TTS_DIR, AUDIO_RECORD_DIR, icon_manager)

                # --- [修改] 为所有录音模块注入 resolve_recording_device 函数 ---
                elif module_key == 'accent_collection_module':
                    return page_factory(module, ToggleSwitch, Worker, Logger, icon_manager, resolve_recording_device) # 新增

                elif module_key == 'dialect_visual_collector_module':
                    return page_factory(module, ToggleSwitch, Worker, Logger, icon_manager, resolve_recording_device) # 新增

                elif module_key == 'voicebank_recorder_module':
                    return page_factory(module, ToggleSwitch, Worker, Logger, icon_manager, resolve_recording_device) # 新增
                
                # --- 其他模块的依赖注入保持不变 ---
                elif module_key == 'dialect_visual_editor_module':
                    return page_factory(module, ToggleSwitch, icon_manager)
                
                elif module_key == 'audio_manager_module':
                    return page_factory(module, ToggleSwitch, icon_manager)
                
                elif module_key in ['pinyin_to_ipa_module']: # 修正：移除 dialect_visual_editor_module
                    return page_factory(module, ToggleSwitch)
                
                elif module_key == 'wordlist_editor_module':
                    return page_factory(module, icon_manager, detect_language)

                elif module_key == 'excel_converter_module':
                    return page_factory(module, icon_manager)
                
                elif module_key == 'tts_utility_module':
                    return page_factory(module, ToggleSwitch, Worker, detect_language, WORD_LIST_DIR, icon_manager)

                elif module_key == 'audio_analysis_module':
                    return page_factory(module, icon_manager, ToggleSwitch)

                elif module_key == 'log_viewer_module':
                    return page_factory(module, ToggleSwitch, icon_manager)

                else:
                    return page_factory(module)

            except Exception as e:
                print(f"创建模块 '{name}' 页面时出错: {e}", file=sys.stderr)
        
        # ... (占位符逻辑不变) ...
        from PyQt5.QtWidgets import QLabel, QVBoxLayout
        page = QWidget()
        layout = QVBoxLayout(page); layout.setAlignment(Qt.AlignCenter)
        if module_key == 'settings_module':
            label_text = f"设置模块 ('{name}') 加载失败。\n请检查 'modules/settings_module.py' 文件是否存在且无误。"
        else:
            label_text = f"模块 '{name}' 未加载或创建失败。\n请检查 'modules/{module_key}.py' 文件以及相关依赖。"
        label = QLabel(label_text); label.setWordWrap(True); label.setStyleSheet("color: #D32F2F; font-size: 24px;"); layout.addWidget(label)
        return page
    
    def on_main_tab_changed(self, index):
        """主标签页切换时触发，进而触发子标签页的刷新逻辑。"""
        current_main_tab_text = self.main_tabs.tabText(index)
        current_main_widget = self.main_tabs.widget(index)
        if current_main_widget and isinstance(current_main_widget, QTabWidget): 
            self.on_sub_tab_changed(current_main_tab_text, current_main_widget.currentIndex())
        
    def on_sub_tab_changed(self, group_name, index):
        """子标签页切换时触发，调用对应页面的刷新或加载方法。"""
        try:
            main_tab_content_widget = None
            for i in range(self.main_tabs.count()):
                if self.main_tabs.tabText(i) == group_name:
                    main_tab_content_widget = self.main_tabs.widget(i)
                    break
            
            if not main_tab_content_widget or not isinstance(main_tab_content_widget, QTabWidget): 
                return
                
            active_sub_tab_widget = main_tab_content_widget.widget(index)
        except Exception: 
            active_sub_tab_widget = None

        # 根据标签页名称和索引，调用特定页面的刷新方法
        if group_name == "数据采集":
            if index == 0 and hasattr(self, 'accent_collection_page') and hasattr(self.accent_collection_page, 'load_config_and_prepare'): 
                self.accent_collection_page.load_config_and_prepare()
            elif index == 1 and hasattr(self, 'dialect_visual_page') and hasattr(self.dialect_visual_page, 'load_config_and_prepare'):
                self.dialect_visual_page.load_config_and_prepare()
            elif index == 2 and hasattr(self, 'voicebank_recorder_page') and hasattr(self.voicebank_recorder_page, 'load_config_and_prepare'):
                self.voicebank_recorder_page.load_config_and_prepare()
                
        elif group_name == "数据准备":
            if index == 0 and hasattr(self, 'wordlist_editor_page') and hasattr(self.wordlist_editor_page, 'refresh_file_list'):
                self.wordlist_editor_page.refresh_file_list()
            elif index == 1 and hasattr(self, 'dialect_visual_editor_page') and hasattr(self.dialect_visual_editor_page, 'refresh_file_list'):
                self.dialect_visual_editor_page.refresh_file_list()
            
        elif group_name == "资源管理":
            if index == 0 and hasattr(self, 'audio_manager_page') and hasattr(self.audio_manager_page, 'load_and_refresh'):
                self.audio_manager_page.load_and_refresh()
            elif index == 1 and hasattr(self, 'log_viewer_page') and hasattr(self.log_viewer_page, 'load_and_refresh'):
                self.log_viewer_page.load_and_refresh()

        elif group_name == "实用工具":
             if index == 2 and hasattr(self, 'flashcard_page') and hasattr(self.flashcard_page, 'populate_wordlists'):
                if not getattr(self.flashcard_page, 'session_active', True):
                    self.flashcard_page.populate_wordlists()

        elif group_name == "系统与帮助":
            if index == 0 and hasattr(self, 'settings_page') and hasattr(self.settings_page, 'load_settings'): 
                self.settings_page.load_settings()
            elif index == 1 and hasattr(self, 'help_page') and hasattr(self.help_page, 'update_help_content'):
                self.help_page.update_help_content()
            
    def apply_theme(self):
        theme_file_path = self.config.get("theme", "default.qss")
        if not theme_file_path: theme_file_path = "default.qss"
        absolute_theme_path = os.path.join(THEMES_DIR, theme_file_path)
        
        is_compact_theme = False # [新增] 默认不为紧凑主题

        if os.path.exists(absolute_theme_path):
            with open(absolute_theme_path, "r", encoding="utf-8") as f:
                stylesheet = f.read()
                
                # --- [核心修改] 解析主题元属性 ---
                # 解析图标路径
                theme_icon_path_to_set = None
                icon_match = re.search(r'/\*\s*@icon-path:\s*"(.*?)"\s*\*/', stylesheet)
                if icon_match:
                    relative_icon_path_str = icon_match.group(1).replace("\\", "/")
                    qss_file_directory = os.path.dirname(absolute_theme_path)
                    absolute_icon_path = os.path.join(qss_file_directory, relative_icon_path_str)
                    theme_icon_path_to_set = os.path.normpath(absolute_icon_path)
                
                # [新增] 解析紧凑模式属性
                compact_match = re.search(r'/\*\s*@theme-property-compact:\s*true\s*\*/', stylesheet)
                if compact_match:
                    is_compact_theme = True
                # --- 结束核心修改 ---
                
                # 1. 首先设置IconManager的路径
                icon_manager.set_theme_icon_path(theme_icon_path_to_set)
                
                # 2. 然后应用样式表
                self.setStyleSheet(stylesheet)
        else:
            print(f"主题文件未找到: {absolute_theme_path}", file=sys.stderr)
            self.setStyleSheet("") 
            icon_manager.set_theme_icon_path(None)
        
        # [新增] 根据是否为紧凑主题，调整窗口最小尺寸
        if is_compact_theme:
            self.setMinimumSize(self.COMPACT_MIN_SIZE[0], self.COMPACT_MIN_SIZE[1])
        else:
            self.setMinimumSize(self.DEFAULT_MIN_SIZE[0], self.DEFAULT_MIN_SIZE[1])
            # 如果当前窗口尺寸小于默认最小尺寸，则将其放大
            if self.width() < self.DEFAULT_MIN_SIZE[0] or self.height() < self.DEFAULT_MIN_SIZE[1]:
                self.resize(self.DEFAULT_MIN_SIZE[0], self.DEFAULT_MIN_SIZE[1])

        # 3. (关键) 通知所有相关模块刷新它们的图标
        self.update_all_module_icons()
        
        if hasattr(self, 'help_page') and hasattr(self.help_page, 'update_help_content'):
            QTimer.singleShot(0, self.help_page.update_help_content)
    def update_all_module_icons(self):
        """遍历所有已创建的页面，如果它们有 update_icons 方法，就调用它。"""
        # [修改] 将 dialect_visual_collector_module 添加到通知列表
        pages_with_icons = [
            'accent_collection_page',
            'log_viewer_page', # from previous task
            'dialect_visual_collector_module', 
            'voicebank_recorder_page', 
            'audio_manager_page', 
            'wordlist_editor_page',
            'dialect_visual_editor_page', 
            'converter_page',
            'audio_analysis_page',
            'tts_utility_page', # <-- 新增项
            'flashcard_page', # <-- 新增项
            # ... 其他模块
        ]
        for page_attr_name in pages_with_icons:
            page = getattr(self, page_attr_name, None)
            if page and hasattr(page, 'update_icons'):
                try:
                    page.update_icons()
                except Exception as e:
                    print(f"更新模块 '{page_attr_name}' 的图标时出错: {e}")

    # [新增] closeEvent 方法，用于安全退出
    def closeEvent(self, event):
        """在关闭主窗口前，确保所有插件都已安全卸载。"""
        print("[主程序] 正在关闭，卸载所有插件...")
        self.plugin_manager.teardown_all_plugins()
        super().closeEvent(event)

    # [新增] 插件UI设置
    def setup_plugin_ui(self):
        """
        [重构] 创建插件栏的静态UI框架。
        这个框架包含一个水平布局，用于容纳固定的插件按钮和主菜单按钮。
        """
        # 1. 创建一个容器 QWidget 来作为 cornerWidget
        self.corner_widget = QWidget()
        # 2. 创建一个水平布局来排列按钮
        self.plugin_bar_layout = QHBoxLayout(self.corner_widget)
        self.plugin_bar_layout.setContentsMargins(0, 5, 15, 5) # 调整边距
        self.plugin_bar_layout.setSpacing(5) # 按钮间的间距

        # 3. 创建一个占位符，用于动态添加固定的插件按钮
        self.pinned_plugins_widget = QWidget()
        self.pinned_plugins_layout = QHBoxLayout(self.pinned_plugins_widget)
        self.pinned_plugins_layout.setContentsMargins(0, 0, 0, 0)
        self.pinned_plugins_layout.setSpacing(5)
        self.pinned_plugins_layout.setAlignment(Qt.AlignRight) # 确保图标从右向左添加

        # 4. 创建主插件菜单按钮
        self.plugin_menu_button = QPushButton("插件") 
        self.plugin_menu_button.setIcon(self.icon_manager.get_icon("plugin"))
        self.plugin_menu_button.setToolTip("管理和执行已安装的插件")
        # [核心样式] 设置为圆形按钮
        self.plugin_menu_button.setObjectName("PluginMenuButtonCircular")
        self.plugin_menu_button.setFixedSize(32, 32) # 固定大小以保持圆形

        # 5. 将组件添加到主布局中
        self.plugin_bar_layout.addWidget(self.pinned_plugins_widget)
        self.plugin_bar_layout.addWidget(self.plugin_menu_button)
        
        # 6. 将整个容器设置为 QTabWidget 的角落控件
        self.main_tabs.setCornerWidget(self.corner_widget, Qt.TopRightCorner)
        
        # 7. 连接信号
        self.plugin_menu_button.clicked.connect(self._show_plugin_menu)

    def update_pinned_plugins_ui(self):
        """
        根据配置文件，清空并重新创建所有固定的插件快捷按钮。
        """
        # 1. 清空现有的所有固定插件按钮
        while self.pinned_plugins_layout.count():
            item = self.pinned_plugins_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 2. 读取配置
        plugin_settings = self.config.get("plugin_settings", {})
        pinned_plugins = plugin_settings.get("pinned", [])

        # 3. 遍历并创建新的按钮
        for plugin_id in pinned_plugins:
            meta = self.plugin_manager.available_plugins.get(plugin_id)
            if not meta:
                continue

            # 创建按钮
            btn = QPushButton()
            icon_path = os.path.join(meta['path'], meta.get('icon', 'icon.png'))
            if os.path.exists(icon_path):
                btn.setIcon(QIcon(icon_path))
            else:
                # 如果插件没有图标，使用一个通用后备图标
                btn.setIcon(self.icon_manager.get_icon("plugin_default"))
            
            btn.setToolTip(f"{meta['name']}")
            btn.setObjectName("PinnedPluginButton") # 用于QSS样式
            btn.setFixedSize(32, 32) # 与主菜单按钮大小一致
            
            # 连接点击事件
            btn.clicked.connect(lambda checked, pid=plugin_id: self.plugin_manager.execute_plugin(pid))
            
            # 添加到布局中
            self.pinned_plugins_layout.addWidget(btn)

    # [修改] _show_plugin_menu 方法，实现多列菜单和自适应宽度
    def _show_plugin_menu(self):
        # 确保导入必要的类
        from PyQt5.QtWidgets import QMenu, QAction, QToolButton, QGridLayout, QWidget, QWidgetAction, QSizePolicy
        from PyQt5.QtCore import QPoint, Qt, QSize
        from PyQt5.QtGui import QIcon, QFontMetrics

        menu = QMenu(self)
        self.update_pinned_plugins_ui()

        active_plugins_sorted = sorted(self.plugin_manager.active_plugins.items(), 
                                       key=lambda item: self.plugin_manager.available_plugins.get(item[0], {}).get('name', item[0]))
        
        num_active_plugins = len(active_plugins_sorted)
        
        # --- [核心修改 1] 统一插件显示模式 ---
        if num_active_plugins == 0:
            no_plugins_action = menu.addAction("未启用插件")
            no_plugins_action.setEnabled(False)
        else:
            grid_widget = QWidget()
            grid_layout = QGridLayout(grid_widget)
            grid_layout.setContentsMargins(10, 10, 10, 10) 
            grid_layout.setSpacing(10) 

            PLUGINS_PER_COLUMN = 6 
            num_cols = (num_active_plugins - 1) // PLUGINS_PER_COLUMN + 1 if num_active_plugins > 0 else 1
            MAX_COLUMNS = 3 # 修复：之前是 MAX_cols，现在统一为 MAX_COLUMNS
            if num_cols > MAX_COLUMNS:
                num_cols = MAX_COLUMNS # 修复：使用正确的常量名
                PLUGINS_PER_COLUMN = (num_active_plugins - 1) // MAX_COLUMNS + 1

            for col_idx in range(num_cols):
                grid_layout.setColumnStretch(col_idx, 1)

            longest_plugin_name = ""
            for plugin_id, _ in active_plugins_sorted:
                meta = self.plugin_manager.available_plugins.get(plugin_id)
                if meta and len(meta['name']) > len(longest_plugin_name):
                    longest_plugin_name = meta['name']

            font_metrics = QFontMetrics(self.font())
            estimated_text_width = font_metrics.width(longest_plugin_name) 
            min_btn_width = estimated_text_width + 24 + 5 + 10 
            if min_btn_width < 100: min_btn_width = 100 

            grid_widget.setMinimumWidth(min_btn_width * num_cols + grid_layout.spacing() * (num_cols - 1) + 
                                        grid_layout.contentsMargins().left() + grid_layout.contentsMargins().right())

            for i, (plugin_id, instance) in enumerate(active_plugins_sorted):
                btn = QToolButton()
                btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon) 
                btn.setAutoRaise(True) 
                btn.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Minimum) 
                btn.setMinimumSize(QSize(min_btn_width, 36)) 

                meta = self.plugin_manager.available_plugins.get(plugin_id)
                if not meta: continue 

                icon_path = os.path.join(meta['path'], meta.get('icon', 'icon.png'))
                plugin_icon = QIcon(icon_path) if os.path.exists(icon_path) else self.icon_manager.get_icon("plugin_default")
                
                btn.setIcon(plugin_icon)
                btn.setIconSize(QSize(24, 24)) 
                btn.setText(meta['name'])
                btn.setToolTip(meta['description'])

                btn.setObjectName("PluginMenuItemToolButton") 
                btn.clicked.connect(lambda checked, pid=plugin_id: self.plugin_manager.execute_plugin(pid))
                
                row = i % PLUGINS_PER_COLUMN
                col = (num_cols - 1) - (i // PLUGINS_PER_COLUMN) # 从右到左填充

                grid_layout.addWidget(btn, row, col)
            
            widget_action = QWidgetAction(menu)
            widget_action.setDefaultWidget(grid_widget)
            menu.addAction(widget_action)

        # --- [核心修改 2] “管理插件”按钮样式统一 ---
        menu.addSeparator() # 分隔线

        # 创建“管理插件”的 QToolButton
        manage_btn = QToolButton()
        manage_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        manage_btn.setAutoRaise(True)
        manage_btn.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed) # 垂直方向不需要伸展
        
        # 按钮的宽度可以与插件按钮一致，但高度固定为标准菜单项高度
        manage_btn_width = menu.sizeHint().width() - 20 # 估算菜单宽度减去边距
        if manage_btn_width < 150: manage_btn_width = 150 # 确保最小宽度
        
        manage_btn.setMinimumSize(QSize(manage_btn_width, 36)) # 与插件按钮高度保持一致
        
        # 使用“管理”图标
        manage_btn.setIcon(self.icon_manager.get_icon("check")) 
        manage_btn.setIconSize(QSize(24, 24))
        manage_btn.setText("管理插件...")
        manage_btn.setToolTip("打开插件管理对话框，安装、卸载、启用或禁用插件。")
        manage_btn.setObjectName("PluginMenuItemToolButton") # 应用相同 QSS 样式

        manage_btn.clicked.connect(self._open_plugin_manager_dialog)
        
        # 将 manage_btn 包装成 QWidgetAction
        manage_widget_action = QWidgetAction(menu)
        manage_widget_action.setDefaultWidget(manage_btn)
        menu.addAction(manage_widget_action)

        # 在按钮下方弹出菜单 (调整弹出位置的健壮性代码，保持不变)
        menu_size = menu.sizeHint()
        button_bottom_right = self.plugin_menu_button.mapToGlobal(self.plugin_menu_button.rect().bottomRight())
        popup_pos = QPoint(button_bottom_right.x() - menu_size.width(), button_bottom_right.y())

        desktop = QApplication.desktop()
        screen_geometry = desktop.screenGeometry(desktop.screenNumber(popup_pos))
        
        if popup_pos.x() < screen_geometry.left():
            popup_pos.setX(screen_geometry.left() + 5) 
        if popup_pos.y() + menu_size.height() > screen_geometry.bottom():
            popup_pos.setY(screen_geometry.bottom() - menu_size.height() - 5)
            if popup_pos.y() < button_bottom_right.y() - menu_size.height(): 
                 popup_pos.setY(button_bottom_right.y() - menu_size.height() - 5)

        menu.exec_(popup_pos)
        self.update_pinned_plugins_ui()

    # [新增] 打开插件管理对话框的逻辑
    def _open_plugin_manager_dialog(self):
        """打开插件管理对话框。"""
        dialog = PluginManagementDialog(self.plugin_manager, self)
        dialog.exec_()
    
        # 对话框关闭后，可以根据需要刷新UI，但目前菜单是动态生成的，所以无需操作。

    def update_and_save_module_state(self, module_key, key_or_value, value=None):
        """
        更新并立即保存一个特定模块的状态到 settings.json。
        这是一个更灵活的API，支持两种调用模式。

        用法1 (保存单个键值对):
            update_and_save_module_state('my_module', 'some_setting', 123)
            
        用法2 (保存整个模块的设置对象):
            update_and_save_module_state('my_module', {'setting1': 123, 'setting2': 'abc'})
        """
        # 确保 module_states 字典存在
        if "module_states" not in self.config:
            self.config["module_states"] = {}
        
        # 通过检查第三个参数 value 是否被传递来判断调用模式
        if value is not None:
            # --- 模式1：传入了三个参数 (module_key, setting_key, value) ---
            # 这是旧的模式，用于保存单个设置项
            if module_key not in self.config["module_states"]:
                self.config["module_states"][module_key] = {}
            
            setting_key = key_or_value
            self.config["module_states"][module_key][setting_key] = value
        else:
            # --- 模式2：只传入了两个参数 (module_key, settings_dict) ---
            # 这是新的模式，用于一次性保存整个模块的配置
            settings_dict = key_or_value
            self.config["module_states"][module_key] = settings_dict

        # 立即将更新后的配置写入文件 (此部分逻辑不变)
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"为模块 '{module_key}' 保存状态时出错: {e}", file=sys.stderr)
# --- 主程序执行块 ---
if __name__ == "__main__":
    splash.showMessage("加载核心组件...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
    splash.progressBar.setValue(10)
    app.processEvents()
    main_config = setup_and_load_config()
    
    splash.showMessage("加载用户配置...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
    splash.progressBar.setValue(20)
    app.processEvents()
    tooltips_config = load_tooltips_config()
    
    splash.showMessage("准备文件目录...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
    splash.progressBar.setValue(30)
    app.processEvents()
    ensure_directories_exist()
    
    # [修改] 确保 icon_manager 在 MainWindow 创建前实例化
    icon_manager = IconManager(DEFAULT_ICON_DIR)
    
    load_modules(progress_offset=30, progress_scale=0.4)
    
    window = MainWindow(splash_ref=splash, tooltips_ref=tooltips_config)
    
    window.show()
    
    splash.finish(window)
    
    sys.exit(app.exec_())
