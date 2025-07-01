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

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QListWidget, QListWidgetItem, QLineEdit, 
                             QFileDialog, QMessageBox, QComboBox, QSlider, QStyle, 
                             QFormLayout, QGroupBox, QCheckBox, QTabWidget, QScrollArea, 
                             QSpacerItem, QSizePolicy)
from PyQt5.QtGui import QIntValidator, QPainter, QPen, QBrush
from PyQt5.QtCore import QThread, pyqtSignal, QObject, pyqtProperty, QRect

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
        "语料管理": { "description": "提供对项目所使用的词表和已生成的音频数据进行管理的工具。", "sub_tabs": { "词表编辑器": "可视化地创建和编辑标准词表。", "Excel转换器": "支持标准词表与图文词表的双向转换。", "数据管理器": "浏览、试听、重命名和删除所有已录制的音频数据。" }},
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

def detect_language(text):
    """根据文本中的字符范围简单检测语言。"""
    if not text: return None
    ranges = { 'han': (0x4e00, 0x9fff), 'kana': (0x3040, 0x30ff), 'hangul_syllables': (0xac00, 0xd7a3), 'hangul_jamo': (0x1100, 0x11ff), 'hangul_compat_jamo': (0x3130, 0x318f), 'cyrillic': (0x0400, 0x04ff), 'latin_basic': (0x0041, 0x005a), 'latin_basic_lower': (0x0061, 0x007a) }
    counts = {key: 0 for key in ranges}
    counts['other'] = 0
    total_meaningful_chars = 0
    for char in text:
        code = ord(char)
        is_meaningful = False
        if ranges['kana'][0] <= code <= ranges['kana'][1]: counts['kana'] += 1; is_meaningful = True
        elif ranges['hangul_syllables'][0] <= code <= ranges['hangul_syllables'][1] or \
             ranges['hangul_jamo'][0] <= code <= ranges['hangul_jamo'][1] or \
             ranges['hangul_compat_jamo'][0] <= code <= ranges['hangul_compat_jamo'][1]:
            counts['hangul_syllables'] += 1; is_meaningful = True
        elif ranges['han'][0] <= code <= ranges['han'][1]: counts['han'] += 1; is_meaningful = True
        elif ranges['cyrillic'][0] <= code <= ranges['cyrillic'][1]: counts['cyrillic'] += 1; is_meaningful = True
        elif ranges['latin_basic'][0] <= code <= ranges['latin_basic'][1] or \
             ranges['latin_basic_lower'][0] <= code <= ranges['latin_basic_lower'][1]:
            counts['latin_basic'] += 1; is_meaningful = True
        else: counts['other'] += 1
        if is_meaningful: total_meaningful_chars +=1
    if total_meaningful_chars == 0: return None
    if counts['hangul_syllables'] / total_meaningful_chars > 0.3: return 'ko'
    if counts['kana'] / total_meaningful_chars > 0.05 or counts['kana'] > 1 : return 'ja'
    if counts['cyrillic'] / total_meaningful_chars > 0.3: return 'ru'
    if counts['han'] / total_meaningful_chars > 0.4 : return 'zh-cn'
    if counts['latin_basic'] / total_meaningful_chars > 0.5: return 'en-us'
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

class MainWindow(QMainWindow):
    def __init__(self, splash_ref=None, tooltips_ref=None):
        super().__init__()
        self.splash_ref = splash_ref
        self.tooltips_config = tooltips_ref if tooltips_ref is not None else {}
        
        if self.splash_ref:
            self.splash_ref.showMessage("初始化主窗口...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            self.splash_ref.progressBar.setValue(75)
            QApplication.processEvents()
            
        self.setWindowTitle("PhonAcq - 风纳客")
        self.setGeometry(100, 100, 1200, 850)
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

        # [修改] 在创建页面前，确保 icon_manager 已经实例化
        global icon_manager
        if icon_manager is None:
            icon_manager = IconManager(DEFAULT_ICON_DIR)

        # 页面创建
        self.accent_collection_page = self.create_module_or_placeholder('accent_collection_module', '标准朗读采集', 
            lambda m, ts, w, l, im: m.create_page(self, self.config, ts, w, l, detect_language, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH, im))
        self.voicebank_recorder_page = self.create_module_or_placeholder('voicebank_recorder_module', '提示音录制', 
            lambda m, ts, w, l, im: m.create_page(self, WORD_LIST_DIR, AUDIO_RECORD_DIR, ts, w, l, im))
        self.audio_manager_page = self.create_module_or_placeholder('audio_manager_module', '音频数据管理器', 
            lambda m, im: m.create_page(self, self.config, BASE_PATH, self.config['file_settings'].get("results_dir"), AUDIO_RECORD_DIR, im))
        self.wordlist_editor_page = self.create_module_or_placeholder('wordlist_editor_module', '通用词表编辑器', 
            lambda m, im: m.create_page(self, WORD_LIST_DIR, im))
        self.converter_page = self.create_module_or_placeholder('excel_converter_module', 'Excel转换器', 
            lambda m, im: m.create_page(self, WORD_LIST_DIR, MODULES, im))
        self.help_page = self.create_module_or_placeholder('help_module', '帮助文档', 
            lambda m: m.create_page(self))
        DIALECT_VISUAL_WORDLIST_DIR = os.path.join(BASE_PATH, "dialect_visual_wordlists")
        os.makedirs(DIALECT_VISUAL_WORDLIST_DIR, exist_ok=True)
        self.dialect_visual_page = self.create_module_or_placeholder('dialect_visual_collector_module', '看图说话采集', 
            lambda m, ts, w, l, im: m.create_page(self, self.config, BASE_PATH, DIALECT_VISUAL_WORDLIST_DIR, AUDIO_RECORD_DIR, ts, w, l, im))
        self.dialect_visual_editor_page = self.create_module_or_placeholder('dialect_visual_editor_module', '图文词表编辑器', 
            lambda m, ts, im: m.create_page(self, DIALECT_VISUAL_WORDLIST_DIR, ts, im))
        self.pinyin_to_ipa_page = self.create_module_or_placeholder('pinyin_to_ipa_module', '拼音转IPA', 
            lambda m, ts: m.create_page(self, ts))
        self.tts_utility_page = self.create_module_or_placeholder('tts_utility_module', 'TTS 工具',
            lambda m, ts, w, dl, std_wld, im: m.create_page(self, self.config, AUDIO_TTS_DIR, ts, w, dl, std_wld, im))
        self.flashcard_page = self.create_module_or_placeholder('flashcard_module', '速记卡',
            lambda m, ts_class, sil_class, bp_val, gtts_dir_val, gr_dir_val, im_val: \
        m.create_page(self, ts_class, sil_class, bp_val, gtts_dir_val, gr_dir_val, im_val)
        )
        self.settings_page = self.create_module_or_placeholder('settings_module', '程序设置',
            lambda m, ts, t_dir, w_dir: m.create_page(self, ts, t_dir, w_dir)) 
        
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
        management_tabs.addTab(self.log_viewer_page, "日志查看器")
        
        utilities_tabs = QTabWidget(); utilities_tabs.setObjectName("SubTabWidget")
        utilities_tabs.addTab(self.pinyin_to_ipa_page, "拼音转IPA")
        utilities_tabs.addTab(self.tts_utility_page, "TTS 工具")
        utilities_tabs.addTab(self.flashcard_page, "速记卡")
        
        system_tabs = QTabWidget(); system_tabs.setObjectName("SubTabWidget")
        system_tabs.addTab(self.settings_page, "程序设置")
        system_tabs.addTab(self.help_page, "帮助文档")
        
        self.main_tabs.addTab(collection_tabs, "数据采集")
        self.main_tabs.addTab(preparation_tabs, "数据准备")
        self.main_tabs.addTab(management_tabs, "语料管理")
        self.main_tabs.addTab(utilities_tabs, "实用工具")
        self.main_tabs.addTab(system_tabs, "系统与帮助")

        # 连接信号与槽
        self.main_tabs.currentChanged.connect(self.on_main_tab_changed)
        collection_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("数据采集", i))
        preparation_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("数据准备", i))
        management_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("语料管理", i))
        utilities_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("实用工具", i))
        system_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("系统与帮助", i))
        
        self.apply_tooltips()
        
        if self.splash_ref:
            self.splash_ref.showMessage("准备完成!", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            self.splash_ref.progressBar.setValue(100)
            QApplication.processEvents()
            
        self.apply_theme()
        self.on_main_tab_changed(0) # 初始加载第一个标签页

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
                    # 确保 QLabel 已导入，作为 ScalableImageLabelClass 的回退
                    from PyQt5.QtWidgets import QLabel 
                    ScalableImageLabelClass = QLabel
                    # 如果 dialect_visual_collector_module 已加载，则尝试从中获取 ScalableImageLabel
                    if 'dialect_visual_collector_module' in MODULES:
                        ScalableImageLabelClass = getattr(MODULES['dialect_visual_collector_module']['module'], 'ScalableImageLabel', QLabel)
    
                    # 传递给 page_factory (lambda) 的参数必须与 lambda 的签名和 m.create_page 的签名匹配
                    return page_factory(module, ToggleSwitch, ScalableImageLabelClass, 
                                        BASE_PATH, AUDIO_TTS_DIR, AUDIO_RECORD_DIR, icon_manager)

                elif module_key == 'accent_collection_module':
                    # 现在它需要 ToggleSwitch, Worker, Logger, 和 IconManager
                    return page_factory(module, ToggleSwitch, Worker, Logger, icon_manager)

                elif module_key == 'dialect_visual_collector_module':
                    return page_factory(module, ToggleSwitch, Worker, Logger, icon_manager)

                elif module_key == 'voicebank_recorder_module':
                    return page_factory(module, ToggleSwitch, Worker, Logger, icon_manager)

                elif module_key == 'dialect_visual_editor_module':
                    # 现在它需要 ToggleSwitch 和 IconManager
                    return page_factory(module, ToggleSwitch, icon_manager)
                
                elif module_key == 'audio_manager_module':
                    # 现在它需要 icon_manager
                    return page_factory(module, icon_manager)
                
                elif module_key in ['pinyin_to_ipa_module', 'dialect_visual_editor_module']:
                    return page_factory(module, ToggleSwitch)
                
                elif module_key == 'wordlist_editor_module':
                    # 现在它需要 icon_manager
                    return page_factory(module, icon_manager)

                elif module_key == 'excel_converter_module':
                    # 现在它需要 icon_manager
                    return page_factory(module, icon_manager)
                
                elif module_key == 'tts_utility_module':
                    return page_factory(module, ToggleSwitch, Worker, detect_language, WORD_LIST_DIR, icon_manager)

                # --- [修改] 为 log_viewer_module 添加 IconManager 依赖 ---
                elif module_key == 'log_viewer_module':
                    return page_factory(module, ToggleSwitch, icon_manager)

                else:
                    return page_factory(module)

            except Exception as e:
                print(f"创建模块 '{name}' 页面时出错: {e}", file=sys.stderr)
        
        # --- [修复] 解决 UnboundLocalError ---
        # 确保 QLabel 在此作用域内可用
        from PyQt5.QtWidgets import QLabel, QVBoxLayout
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        if module_key == 'settings_module':
            label_text = f"设置模块 ('{name}') 加载失败。\n请检查 'modules/settings_module.py' 文件是否存在且无误。"
        else:
            label_text = f"模块 '{name}' 未加载或创建失败。\n请检查 'modules/{module_key}.py' 文件以及相关依赖。"
        
        label = QLabel(label_text) # 现在 QLabel 是已定义的
        label.setWordWrap(True)
        label.setStyleSheet("color: #D32F2F; font-size: 14px;") # Give it a distinct error style
        layout.addWidget(label)
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
            
        elif group_name == "语料管理":
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
        theme_file_path = self.config.get("theme", "Modern_light_tab.qss")
        if not theme_file_path: theme_file_path = "Modern_light_tab.qss"
        absolute_theme_path = os.path.join(THEMES_DIR, theme_file_path)
        
        if os.path.exists(absolute_theme_path):
            with open(absolute_theme_path, "r", encoding="utf-8") as f:
                stylesheet = f.read()
                theme_icon_path_to_set = None
                match = re.search(r'/\*\s*@icon-path:\s*"(.*?)"\s*\*/', stylesheet)
                if match:
                    relative_icon_path_str = match.group(1).replace("\\", "/")
                    qss_file_directory = os.path.dirname(absolute_theme_path)
                    absolute_icon_path = os.path.join(qss_file_directory, relative_icon_path_str)
                    theme_icon_path_to_set = os.path.normpath(absolute_icon_path)
                
                # 1. 首先设置IconManager的路径
                icon_manager.set_theme_icon_path(theme_icon_path_to_set)
                
                # 2. 然后应用样式表
                self.setStyleSheet(stylesheet)
        else:
            print(f"主题文件未找到: {absolute_theme_path}", file=sys.stderr)
            self.setStyleSheet("") 
            icon_manager.set_theme_icon_path(None)
            
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
