# --- START OF FILE Dev.py ---

import os
import sys
import time # 用于非常短的延时，确保splash有时间绘制
import random
import re # 新增：用于解析QSS

# ===== 阶段一：最小化初始导入，用于立即显示 Splash Screen =====
from PyQt5.QtWidgets import QApplication, QSplashScreen, QProgressBar
from PyQt5.QtGui import QPixmap, QColor, QFont, QIntValidator
from PyQt5.QtCore import Qt, QCoreApplication

# 全局变量，提前定义，后续填充
BASE_PATH = ""
CONFIG_DIR = ""
WORD_LIST_DIR = ""
THEMES_DIR = ""
AUDIO_TTS_DIR = ""
AUDIO_RECORD_DIR = ""
MODULES_DIR = ""
SETTINGS_FILE = ""
TOOLTIPS_FILE = ""
tooltips_config = {}
MODULES = {}
main_config = {}


# 提前定义 get_base_path，因为它不依赖太多外部库
def get_base_path():
    """Gets the base path of the application, handling frozen executables."""
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(".")

def ensure_directories_exist():
    """
    Checks and creates all core directories required for the application to run.
    """
    required_paths = [
        CONFIG_DIR,
        WORD_LIST_DIR,
        THEMES_DIR,
        AUDIO_TTS_DIR,
        AUDIO_RECORD_DIR,
        MODULES_DIR,
        os.path.join(BASE_PATH, "assets", "flags"),
        os.path.join(BASE_PATH, "assets", "help"),
        os.path.join(BASE_PATH, "assets", "splashes"),
        os.path.join(BASE_PATH, "dialect_visual_wordlists"),
        main_config.get('file_settings', {}).get('results_dir', os.path.join(BASE_PATH, "Results"))
    ]
    
    print("--- 检查并创建所需文件夹 ---")
    for path in required_paths:
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
                print(f"  [创建成功]: {path}")
            except Exception as e:
                print(f"  [创建失败]: {path} - 错误: {e}")
    print("--- 文件夹检查完毕 ---")


# ===== 阶段二：现在可以导入其他模块和定义函数了 =====
import json
import threading
import queue
from datetime import datetime
import importlib.util

from PyQt5.QtWidgets import (QApplication, QSplashScreen, QProgressBar, QMainWindow, 
                             QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
                             QListWidget, QListWidgetItem, QLineEdit, QFileDialog, 
                             QMessageBox, QComboBox, QSlider, QStyle, QFormLayout, 
                             QGroupBox, QCheckBox, QTabWidget, QScrollArea, QSpacerItem,
                             QSizePolicy)
from PyQt5.QtGui import (QPixmap, QColor, QFont, QIntValidator, QPainter, 
                         QPen, QBrush, QIcon) # 导入更多 GDI+ 相关的类
from PyQt5.QtCore import Qt, QCoreApplication, QThread, pyqtSignal, QObject, QTimer, pyqtProperty, QRect # 导入 pyqtProperty

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
    app = QApplication(sys.argv)
    QMessageBox.critical(None, "依赖库缺失", f"错误: {e}\n\n请运行: pip install PyQt5 pandas openpyxl sounddevice soundfile numpy gtts markdown pypinyin")
    sys.exit(1)


# --- 全局路径变量的完整定义 ---
BASE_PATH = get_base_path()
CONFIG_DIR = os.path.join(BASE_PATH, "config")
WORD_LIST_DIR = os.path.join(BASE_PATH, "word_lists")
THEMES_DIR = os.path.join(BASE_PATH, "themes")
AUDIO_TTS_DIR = os.path.join(BASE_PATH, "audio_tts")
AUDIO_RECORD_DIR = os.path.join(BASE_PATH, "audio_record")
MODULES_DIR = os.path.join(BASE_PATH, "modules")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
TOOLTIPS_FILE = os.path.join(CONFIG_DIR, "tooltips.json")


# --- 动态模块加载 ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'modules')))
def load_modules(splash_ref=None, progress_offset=0, progress_scale=1.0):
    """Dynamically loads modules from the 'modules' directory."""
    global MODULES; MODULES = {}
    modules_dir = os.path.join(get_base_path(), "modules")
    if not os.path.exists(modules_dir): os.makedirs(modules_dir)
    module_files = [f for f in os.listdir(modules_dir) if f.endswith('.py') and not f.startswith('__')]
    total_modules = len(module_files)
    for i, filename in enumerate(module_files):
        base_progress = progress_offset
        current_stage_progress = int(((i + 1) / total_modules) * (100 * progress_scale)) if total_modules > 0 else int(100 * progress_scale)
        if splash_ref:
            splash_ref.showMessage(f"加载模块: {filename} ...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            splash_ref.progressBar.setValue(base_progress + current_stage_progress)
            QApplication.processEvents()
        module_name = filename[:-3]
        try:
            filepath = os.path.join(modules_dir, filename)
            spec = importlib.util.spec_from_file_location(module_name, filepath); module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            MODULES[module_name] = {'module': module, 'name': getattr(module, 'MODULE_NAME', module_name), 'desc': getattr(module, 'MODULE_DESCRIPTION', '无描述'), 'file': filename}
        except Exception as e: print(f"加载模块 '{filename}' 失败: {e}")

def load_tooltips_config():
    """
    加载 config/tooltips.json 文件。如果文件不存在，则创建一个包含占位符的默认文件。
    """
    default_tooltips = {
        "数据采集": { "description": "包含所有用于实时录制和收集语音数据的功能模块。", "sub_tabs": { "口音采集会话": "适用于标准的文本到语音朗读任务。", "语音包录制": "用于为标准词表录制高质量的真人提示音。" }},
        "方言研究": { "description": "专为方言学田野调查设计的工具集。", "sub_tabs": { "图文采集": "展示图片并录制方言描述。", "图文词表编辑": "在程序内直接创建、编辑和保存用于“图文采集”的词表。" }},
        "语料管理": { "description": "提供对项目所使用的词表和已生成的音频数据进行管理的工具。", "sub_tabs": { "词表编辑器": "可视化地创建和编辑标准词表。", "Excel 转换器": "支持标准词表与图文词表的双向转换。", "数据管理器": "浏览、试听、重命名和删除所有已录制的音频数据。" }},
        "实用工具": { "description": "提供一系列辅助性的语言学工具。", "sub_tabs": { "拼音转IPA": "将汉字实时转换为国际音标。", "TTS 工具": "批量或即时将文本列表转换为语音文件。" }},
        "系统与帮助": { "description": "配置应用程序的行为、外观，并获取使用帮助。", "sub_tabs": { "程序设置": "调整应用的各项参数，包括UI布局、音频设备和主题皮肤等。", "帮助文档": "提供详细的程序使用指南和常见问题解答。" }}
    }
    if not os.path.exists(TOOLTIPS_FILE):
        try:
            with open(TOOLTIPS_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_tooltips, f, indent=4, ensure_ascii=False)
            print(f"创建默认 tooltips 文件: {TOOLTIPS_FILE}")
            return default_tooltips
        except Exception as e:
            print(f"创建默认 tooltips 文件失败: {e}")
            return {}

    try:
        with open(TOOLTIPS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"加载 tooltips 文件失败: {e}")
        return {}

# --- 核心逻辑与辅助函数 ---
class Logger:
    """A simple file logger."""
    def __init__(self, fp): self.fp = fp; open(self.fp, 'a', encoding='utf-8').write(f"\n--- Log started at {datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
    def log(self, msg): open(self.fp, 'a', encoding='utf-8').write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] - {msg}\n")

def setup_and_load_config():
    """Initializes and loads the main configuration file."""
    if not os.path.exists(CONFIG_DIR): os.makedirs(CONFIG_DIR)
    default_settings = {
        "ui_settings": {
            "collector_sidebar_width": 320,
            "editor_sidebar_width": 280
        },
        "audio_settings": {
            "sample_rate": 44100, 
            "channels": 1, 
            "recording_gain": 1.0,
            "input_device_index": None
        },
        "file_settings": {"word_list_file": "default_list.py", "participant_base_name": "participant", "results_dir": os.path.join(BASE_PATH, "Results")},
        "gtts_settings": {"default_lang": "en-us", "auto_detect": True}, "theme": "Modern_light_tab.qss"
    }
    if not os.path.exists(SETTINGS_FILE): open(SETTINGS_FILE, 'w', encoding='utf-8').write(json.dumps(default_settings, indent=4))
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f: config = json.load(f)
        updated = False
        for key, default_value_section in default_settings.items():
            if key not in config:
                config[key] = default_value_section
                updated = True
            elif not isinstance(config[key], dict) and isinstance(default_value_section, dict):
                config[key] = default_value_section
                updated = True
            elif isinstance(config[key], dict) and isinstance(default_value_section, dict):
                for sub_key, default_sub_value in default_value_section.items():
                    if sub_key not in config[key]:
                        config[key][sub_key] = default_sub_value
                        updated = True
        if updated: open(SETTINGS_FILE, 'w', encoding='utf-8').write(json.dumps(config, indent=4))
        return config
    except Exception as e:
        print(f"Error loading or updating config: {e}")
        try:
            corrupted_path = SETTINGS_FILE + ".corrupted_" + datetime.now().strftime("%Y%m%d%H%M%S")
            if os.path.exists(SETTINGS_FILE):
                os.rename(SETTINGS_FILE, corrupted_path)
            print(f"Corrupted settings file moved to {corrupted_path}. Loading default settings.")
            open(SETTINGS_FILE, 'w', encoding='utf-8').write(json.dumps(default_settings, indent=4))
        except Exception as e_move:
            print(f"Could not move/recreate settings file: {e_move}")
        return default_settings

def detect_language(text):
    """Detects the primary language of a given text string."""
    if not text: return None
    ranges = {
        'han': (0x4e00, 0x9fff), 'kana': (0x3040, 0x30ff), 
        'hangul_syllables': (0xac00, 0xd7a3), 'hangul_jamo': (0x1100, 0x11ff),
        'hangul_compat_jamo': (0x3130, 0x318f), 'cyrillic': (0x0400, 0x04ff),
        'latin_basic': (0x0041, 0x005a), 'latin_basic_lower': (0x0061, 0x007a)
    }
    counts = {key: 0 for key in ranges}; counts['other'] = 0; total_meaningful_chars = 0

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
    """A generic worker thread for running tasks in the background."""
    finished = pyqtSignal(object); progress = pyqtSignal(int, str); error = pyqtSignal(str)
    def __init__(self, task, *args, **kwargs): super().__init__(); self.task=task; self.args=args; self.kwargs=kwargs
    def run(self):
        try: res = self.task(self, *self.args, **self.kwargs); self.finished.emit(res)
        except Exception as e: self.error.emit(f"后台任务失败: {e}")

class ToggleSwitch(QCheckBox):
    """
    A QSS-driven toggle switch widget.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self._trackColorOff = QColor("#E0E0E0"); self._trackColorOn = QColor("#8F4C33"); self._knobColor = QColor("#FFFFFF")
        self._trackBorderRadius = 14; self._knobMargin = 3; self._knobShape = 'ellipse' ; self._knobBorderRadius = 0 
        self._borderColor = QColor(Qt.transparent); self._borderWidth = 0 
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
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); rect = self.rect()
        if self._borderWidth > 0 and self._borderColor.isValid() and self._borderColor.alpha() > 0:
            pen = QPen(self._borderColor, self._borderWidth); pen.setJoinStyle(Qt.RoundJoin); p.setPen(pen)
            half_pen_width = self._borderWidth // 2
            border_rect = rect.adjusted(half_pen_width, half_pen_width, -half_pen_width, -half_pen_width)
            p.setBrush(Qt.NoBrush); p.drawRoundedRect(border_rect, self.trackBorderRadius, self.trackBorderRadius)
        p.setPen(Qt.NoPen); track_color = self.trackColorOn if self.isChecked() else self.trackColorOff
        p.setBrush(QBrush(track_color)); track_rect = rect.adjusted(self._borderWidth, self._borderWidth, -self._borderWidth, -self._borderWidth)
        track_inner_radius = max(0, self.trackBorderRadius - self._borderWidth)
        p.drawRoundedRect(track_rect, track_inner_radius, track_inner_radius)
        margin = self.knobMargin; knob_height = track_rect.height() - (2 * margin); knob_width = knob_height 
        if self.isChecked(): x_pos = track_rect.right() - knob_width - margin + 1
        else: x_pos = track_rect.left() + margin
        knob_rect = QRect(x_pos, track_rect.top() + margin, knob_width, knob_height); p.setBrush(QBrush(self.knobColor))
        if self.knobShape == 'rectangle': p.drawRoundedRect(knob_rect, self.knobBorderRadius, self.knobBorderRadius)
        else: p.drawEllipse(knob_rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton: self.setChecked(not self.isChecked()); event.accept() 
        else: super().mousePressEvent(event)


# ========== 主窗口和页面类 ==========
class MainWindow(QMainWindow):
    """The main application window."""
    def __init__(self, splash_ref=None, tooltips_ref=None):
        super().__init__()
        self.splash_ref = splash_ref
        self.tooltips_config = tooltips_ref if tooltips_ref is not None else {}
        
        if self.splash_ref: self.splash_ref.showMessage("初始化主窗口...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); self.splash_ref.progressBar.setValue(35); QApplication.processEvents()
        self.setWindowTitle("PhonAcq - 风纳客"); self.setGeometry(100, 100, 1200, 850)
        icon_path = os.path.join(BASE_PATH, "config", "icon.ico") 
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))
        self.config = main_config
        self.main_tabs = QTabWidget(); self.main_tabs.setObjectName("MainTabWidget"); self.setCentralWidget(self.main_tabs)
        if self.splash_ref: self.splash_ref.showMessage("创建核心页面...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); self.splash_ref.progressBar.setValue(50); QApplication.processEvents()

        self.accent_collection_page = self.create_module_or_placeholder('accent_collection_module', '口音采集会话', 
            lambda m, ts, w, l: m.create_page(self, self.config, ts, w, l, detect_language, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH))
        self.voicebank_recorder_page = self.create_module_or_placeholder('voicebank_recorder_module', '语音包录制', 
            lambda m, ts, w: m.create_page(self, WORD_LIST_DIR, AUDIO_RECORD_DIR, ts, w))
        self.audio_manager_page = self.create_module_or_placeholder('audio_manager_module', '数据管理器', 
            lambda m: m.create_page(self, self.config, BASE_PATH, self.config['file_settings'].get("results_dir"), AUDIO_RECORD_DIR))
        self.wordlist_editor_page = self.create_module_or_placeholder('wordlist_editor_module', '词表编辑器', 
            lambda m: m.create_page(self, WORD_LIST_DIR))
        self.converter_page = self.create_module_or_placeholder('excel_converter_module', 'Excel 转换器', 
            lambda m: m.create_page(self, WORD_LIST_DIR, MODULES))
        self.help_page = self.create_module_or_placeholder('help_module', '帮助文档', 
            lambda m: m.create_page(self))
        DIALECT_VISUAL_WORDLIST_DIR = os.path.join(BASE_PATH, "dialect_visual_wordlists"); os.makedirs(DIALECT_VISUAL_WORDLIST_DIR, exist_ok=True)
        self.dialect_visual_page = self.create_module_or_placeholder('dialect_visual_collector_module', '方言图文采集', 
            lambda m, ts, w, l: m.create_page(self, self.config, BASE_PATH, DIALECT_VISUAL_WORDLIST_DIR, AUDIO_RECORD_DIR, ts, w, l))
        self.dialect_visual_editor_page = self.create_module_or_placeholder('dialect_visual_editor_module', '图文词表编辑器', 
            lambda m: m.create_page(self, DIALECT_VISUAL_WORDLIST_DIR))
        self.pinyin_to_ipa_page = self.create_module_or_placeholder('pinyin_to_ipa_module', '拼音转IPA', 
            lambda m, ts: m.create_page(self, ts))
        self.tts_utility_page = self.create_module_or_placeholder('tts_utility_module', 'TTS 工具',
            lambda m, ts, w, dl, std_wld: m.create_page(self, self.config, AUDIO_TTS_DIR, ts, w, dl, std_wld)
        )
        self.settings_page = SettingsPage(self) 
        
        if self.splash_ref: self.splash_ref.showMessage("构建用户界面...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); self.splash_ref.progressBar.setValue(75); QApplication.processEvents()
        collection_tabs = QTabWidget(); collection_tabs.setObjectName("SubTabWidget"); collection_tabs.addTab(self.accent_collection_page, "口音采集会话"); collection_tabs.addTab(self.voicebank_recorder_page, "语音包录制")
        dialect_study_tabs = QTabWidget(); dialect_study_tabs.setObjectName("SubTabWidget"); dialect_study_tabs.addTab(self.dialect_visual_page, "图文采集"); dialect_study_tabs.addTab(self.dialect_visual_editor_page, "图文词表编辑")
        corpus_tabs = QTabWidget(); corpus_tabs.setObjectName("SubTabWidget"); corpus_tabs.addTab(self.wordlist_editor_page, "词表编辑器"); corpus_tabs.addTab(self.converter_page, "Excel 转换器"); corpus_tabs.addTab(self.audio_manager_page, "数据管理器")
        utilities_tabs = QTabWidget(); utilities_tabs.setObjectName("SubTabWidget"); utilities_tabs.addTab(self.pinyin_to_ipa_page, "拼音转IPA"); utilities_tabs.addTab(self.tts_utility_page, "TTS 工具")
        settings_and_help_tabs = QTabWidget(); settings_and_help_tabs.setObjectName("SubTabWidget"); settings_and_help_tabs.addTab(self.settings_page, "程序设置"); settings_and_help_tabs.addTab(self.help_page, "帮助文档")
        self.main_tabs.addTab(collection_tabs, "数据采集"); self.main_tabs.addTab(dialect_study_tabs, "方言研究"); self.main_tabs.addTab(corpus_tabs, "语料管理"); self.main_tabs.addTab(utilities_tabs, "实用工具"); self.main_tabs.addTab(settings_and_help_tabs, "系统与帮助")
        self.main_tabs.currentChanged.connect(self.on_main_tab_changed); collection_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("数据采集", i)); corpus_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("语料管理", i)); dialect_study_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("方言研究", i)); utilities_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("实用工具", i)); settings_and_help_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("系统与帮助", i))
        
        self.apply_tooltips()
        
        if self.splash_ref: self.splash_ref.showMessage("准备完成! (100%)", Qt.AlignBottom | Qt.AlignLeft, Qt.white); self.splash_ref.progressBar.setValue(100); QApplication.processEvents()
        self.apply_theme(); self.on_main_tab_changed(0)

    def apply_tooltips(self):
        """遍历所有Tab并从配置文件中应用Tooltips。"""
        if not self.tooltips_config:
            return

        for i in range(self.main_tabs.count()):
            main_tab_text = self.main_tabs.tabText(i)
            main_tab_data = self.tooltips_config.get(main_tab_text, {})
            
            main_tooltip = main_tab_data.get('description', f"{main_tab_text} 功能模块")
            self.main_tabs.setTabToolTip(i, main_tooltip)
            
            sub_tab_widget = self.main_tabs.widget(i)
            if isinstance(sub_tab_widget, QTabWidget):
                sub_tabs_data = main_tab_data.get('sub_tabs', {})
                for j in range(sub_tab_widget.count()):
                    sub_tab_text = sub_tab_widget.tabText(j)
                    sub_tooltip = sub_tabs_data.get(sub_tab_text, "无详细描述。")
                    sub_tab_widget.setTabToolTip(j, sub_tooltip)

    def create_module_or_placeholder(self, module_key, name, page_factory):
        """Creates a page from a module or a placeholder if the module is missing."""
        if module_key in MODULES:
            try:
                module = MODULES[module_key]['module']
                if module_key == 'accent_collection_module': return page_factory(module, ToggleSwitch, Worker, Logger)
                elif module_key == 'dialect_visual_collector_module': return page_factory(module, ToggleSwitch, Worker, Logger)
                elif module_key == 'pinyin_to_ipa_module': return page_factory(module, ToggleSwitch)
                elif module_key == 'voicebank_recorder_module': return page_factory(module, ToggleSwitch, Worker)
                elif module_key == 'tts_utility_module': 
                    return page_factory(module, ToggleSwitch, Worker, detect_language, WORD_LIST_DIR) 
                return page_factory(module)
            except Exception as e: print(f"创建模块 '{name}' 页面时出错: {e}")
        page = QWidget(); layout = QVBoxLayout(page); layout.setAlignment(Qt.AlignCenter); layout.addWidget(QLabel(f"模块 '{name}' 未加载或创建失败。")); return page

    def on_main_tab_changed(self, index):
        """Handles logic when the main tab changes."""
        current_main_tab_text = self.main_tabs.tabText(index)
        current_main_widget = self.main_tabs.widget(index)
        if current_main_widget and isinstance(current_main_widget, QTabWidget): 
            self.on_sub_tab_changed(current_main_tab_text, current_main_widget.currentIndex())
        
    def on_sub_tab_changed(self, group_name, index):
        """Handles logic when a sub-tab changes, calling refresh/load methods."""
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

        if group_name == "数据采集":
            if index == 0 and 'accent_collection_module' in MODULES and hasattr(self, 'accent_collection_page') and self.accent_collection_page == active_sub_tab_widget: self.accent_collection_page.load_config_and_prepare()
            elif index == 1 and 'voicebank_recorder_module' in MODULES and hasattr(self, 'voicebank_recorder_page') and self.voicebank_recorder_page == active_sub_tab_widget: self.voicebank_recorder_page.load_config_and_prepare()
        elif group_name == "方言研究":
            if index == 0 and 'dialect_visual_collector_module' in MODULES and hasattr(self, 'dialect_visual_page') and self.dialect_visual_page == active_sub_tab_widget: self.dialect_visual_page.load_config_and_prepare()
            elif index == 1 and 'dialect_visual_editor_module' in MODULES and hasattr(self, 'dialect_visual_editor_page') and self.dialect_visual_editor_page == active_sub_tab_widget: self.dialect_visual_editor_page.refresh_file_list()
        elif group_name == "语料管理":
            if index == 0 and 'wordlist_editor_module' in MODULES and hasattr(self, 'wordlist_editor_page') and self.wordlist_editor_page == active_sub_tab_widget: self.wordlist_editor_page.refresh_file_list()
            elif index == 2 and 'audio_manager_module' in MODULES and hasattr(self, 'audio_manager_page') and self.audio_manager_page == active_sub_tab_widget: self.audio_manager_page.load_and_refresh()
        elif group_name == "实用工具":
            pass 
        elif group_name == "系统与帮助":
            if index == 0 and hasattr(self, 'settings_page') and self.settings_page == active_sub_tab_widget: self.settings_page.load_settings()
            elif index == 1 and hasattr(self, 'help_page') and self.help_page == active_sub_tab_widget and hasattr(self.help_page, 'update_help_content'): self.help_page.update_help_content()
            
    def apply_theme(self):
        """Applies the currently selected theme from the configuration."""
        theme_path = os.path.join(THEMES_DIR, self.config.get("theme", "Modern_light_tab.qss"))
        if os.path.exists(theme_path):
            with open(theme_path, "r", encoding="utf-8") as f: self.setStyleSheet(f.read())
        else:
            print(f"主题文件未找到: {theme_path}")
            self.setStyleSheet("") 
        if hasattr(self, 'help_page') and hasattr(self.help_page, 'update_help_content'):
            QTimer.singleShot(0, self.help_page.update_help_content)

class SettingsPage(QWidget):
    """The settings page for the application."""
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        
        main_layout = QVBoxLayout(self)
        columns_layout = QHBoxLayout()

        self.left_column_widget = QWidget()
        left_column_layout = QVBoxLayout(self.left_column_widget)
        
        self.right_column_widget = QWidget()
        right_column_layout = QVBoxLayout(self.right_column_widget)

        ui_appearance_group = QGroupBox("界面与外观")
        ui_appearance_form_layout = QFormLayout(ui_appearance_group)
        self.collector_width_input = QLineEdit()
        self.collector_width_input.setValidator(QIntValidator(200, 600, self))
        self.collector_width_label = QLabel("范围: 200-600 px")
        collector_width_layout = QHBoxLayout()
        collector_width_layout.addWidget(self.collector_width_input)
        collector_width_layout.addWidget(self.collector_width_label)
        ui_appearance_form_layout.addRow("采集类页面侧边栏宽度:", collector_width_layout)
        self.editor_width_input = QLineEdit()
        self.editor_width_input.setValidator(QIntValidator(200, 600, self))
        self.editor_width_label = QLabel("范围: 200-600 px")
        editor_width_layout = QHBoxLayout()
        editor_width_layout.addWidget(self.editor_width_input)
        editor_width_layout.addWidget(self.editor_width_label)
        ui_appearance_form_layout.addRow("管理/编辑类页面侧边栏宽度:", editor_width_layout)
        self.theme_combo = QComboBox()
        ui_appearance_form_layout.addRow("主题皮肤:", self.theme_combo)
        
        file_group = QGroupBox("文件与路径")
        file_layout = QFormLayout(file_group)
        self.results_dir_input = QLineEdit()
        self.results_dir_btn = QPushButton("...")
        results_dir_layout = QHBoxLayout(); results_dir_layout.addWidget(self.results_dir_input); results_dir_layout.addWidget(self.results_dir_btn)
        self.word_list_combo = QComboBox()
        self.participant_name_input = QLineEdit()
        file_layout.addRow("结果文件夹:", results_dir_layout)
        file_layout.addRow("默认单词表 (口音采集):", self.word_list_combo)
        file_layout.addRow("默认被试者名称:", self.participant_name_input)
        
        gtts_group = QGroupBox("gTTS (在线) 设置")
        gtts_layout = QFormLayout(gtts_group)
        self.gtts_lang_combo = QComboBox()
        self.gtts_lang_combo.addItems(['en-us','en-uk','en-au','en-in','zh-cn','ja','fr-fr','de-de','es-es','ru','ko'])
        self.gtts_auto_detect_switch = ToggleSwitch()
        auto_detect_layout = QHBoxLayout(); auto_detect_layout.addWidget(self.gtts_auto_detect_switch); auto_detect_layout.addStretch()
        gtts_layout.addRow("默认语言 (无指定时):", self.gtts_lang_combo)
        gtts_layout.addRow("自动检测语言 (中/日等):", auto_detect_layout)

        audio_group = QGroupBox("音频与录音")
        audio_layout = QFormLayout(audio_group)
        self.input_device_combo = QComboBox() 
        audio_layout.addRow("录音设备:", self.input_device_combo)
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(["44100 Hz (CD质量, 推荐)","48000 Hz (录音室质量)","22050 Hz (中等质量)","16000 Hz (语音识别常用)"])
        self.channels_combo = QComboBox()
        self.channels_combo.addItems(["1 (单声道, 推荐)","2 (立体声)"])
        self.gain_slider = QSlider(Qt.Horizontal); self.gain_label = QLabel("1.0x")
        self.gain_slider.setRange(5, 50); self.gain_slider.setValue(10)
        gain_layout = QHBoxLayout(); gain_layout.addWidget(self.gain_slider); gain_layout.addWidget(self.gain_label)
        audio_layout.addRow("采样率:", self.sample_rate_combo)
        audio_layout.addRow("通道:", self.channels_combo)
        audio_layout.addRow("录音音量增益:", gain_layout)
        
        left_column_layout.addWidget(ui_appearance_group)
        left_column_layout.addWidget(file_group)
        left_column_layout.addStretch()
        right_column_layout.addWidget(gtts_group)
        right_column_layout.addWidget(audio_group)
        right_column_layout.addStretch()
        self.left_column_widget.setMaximumWidth(600)
        self.right_column_widget.setMaximumWidth(600)
        columns_layout.addWidget(self.left_column_widget)
        columns_layout.addWidget(self.right_column_widget)

        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存所有设置"); self.save_btn.setObjectName("AccentButton")
        button_layout.addStretch(); button_layout.addWidget(self.save_btn)
        
        main_layout.addLayout(columns_layout)
        main_layout.addLayout(button_layout)
        
        self.gain_slider.valueChanged.connect(lambda v: self.gain_label.setText(f"{v/10.0:.1f}x"))
        self.save_btn.clicked.connect(self.save_settings)
        self.results_dir_btn.clicked.connect(self.select_results_dir)
        self.theme_combo.currentTextChanged.connect(self.preview_theme)

    def populate_all(self):
        """Populates all combo boxes with available options."""
        self.populate_themes(); self.populate_word_lists(); self.populate_input_devices()

    def populate_input_devices(self):
        """Populates the input device combo box."""
        self.input_device_combo.clear()
        try:
            devices = sd.query_devices()
            default_input_idx = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) and len(sd.default.device) > 0 else -1
            self.input_device_combo.addItem("系统默认", None) 
            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    device_name = f"{device['name']}"
                    if i == default_input_idx:
                        device_name += " (推荐)"
                    self.input_device_combo.addItem(device_name, i)
        except Exception as e:
            print(f"获取录音设备失败: {e}")
            self.input_device_combo.addItem("无法获取设备列表", -1)

    def select_results_dir(self):
        """Opens a dialog to select the results directory."""
        directory = QFileDialog.getExistingDirectory(self, "选择结果文件夹", self.results_dir_input.text())
        if directory: self.results_dir_input.setText(directory)

    def populate_word_lists(self):
        """Populates the word list combo box."""
        self.word_list_combo.clear()
        if os.path.exists(WORD_LIST_DIR): self.word_list_combo.addItems([f for f in os.listdir(WORD_LIST_DIR) if f.endswith('.py')])

    def populate_themes(self):
        """Populates the theme combo box."""
        self.theme_combo.clear()
        themes_dir_path = os.path.join(get_base_path(), "themes")
        if os.path.exists(themes_dir_path): 
            self.theme_combo.addItems([f for f in os.listdir(themes_dir_path) if f.endswith('.qss') and not f.startswith('_')])

    def load_settings(self):
        """Loads all settings from the config and populates the UI fields."""
        self.populate_all() 
        self.config = self.parent_window.config
        
        ui_settings = self.config.get("ui_settings", {})
        self.collector_width_input.setText(str(ui_settings.get("collector_sidebar_width", 320)))
        self.editor_width_input.setText(str(ui_settings.get("editor_sidebar_width", 280)))

        self.theme_combo.setCurrentText(self.config.get("theme", "Modern_light_tab.qss"))
        file_settings = self.config.get("file_settings", {}); gtts_settings = self.config.get("gtts_settings", {}); audio_settings = self.config.get("audio_settings", {})
        
        self.word_list_combo.setCurrentText(file_settings.get('word_list_file', ''))
        self.participant_name_input.setText(file_settings.get('participant_base_name', ''))
        self.results_dir_input.setText(file_settings.get("results_dir", os.path.join(BASE_PATH, "Results")))
        self.gtts_lang_combo.setCurrentText(gtts_settings.get('default_lang', 'en-us'))
        self.gtts_auto_detect_switch.setChecked(gtts_settings.get('auto_detect', True))
        
        saved_device_idx = audio_settings.get("input_device_index", None)
        if saved_device_idx is None: 
            index_in_combo = self.input_device_combo.findData(None)
            if index_in_combo != -1: self.input_device_combo.setCurrentIndex(index_in_combo)
        elif isinstance(saved_device_idx, int):
            index_in_combo = self.input_device_combo.findData(saved_device_idx)
            if index_in_combo != -1: self.input_device_combo.setCurrentIndex(index_in_combo)
            else: 
                index_in_combo_default = self.input_device_combo.findData(None)
                if index_in_combo_default != -1: self.input_device_combo.setCurrentIndex(index_in_combo_default)

        sr_text = next((s for s in [self.sample_rate_combo.itemText(i) for i in range(self.sample_rate_combo.count())] if str(audio_settings.get('sample_rate', 44100)) in s), "44100 Hz (CD质量, 推荐)")
        self.sample_rate_combo.setCurrentText(sr_text)
        ch_text = next((s for s in [self.channels_combo.itemText(i) for i in range(self.channels_combo.count())] if str(audio_settings.get('channels', 1)) in s), "1 (单声道, 推荐)")
        self.channels_combo.setCurrentText(ch_text)
        gain = audio_settings.get('recording_gain', 1.0)
        self.gain_slider.setValue(int(gain * 10))

    def preview_theme(self, theme_file):
        """Temporarily applies a theme for previewing."""
        if not theme_file: return
        theme_path = os.path.join(THEMES_DIR, theme_file)
        if os.path.exists(theme_path):
            with open(theme_path, "r", encoding="utf-8") as f: self.parent_window.setStyleSheet(f.read())
            
    # ===== 修改/MODIFIED: 优化 save_settings 方法 =====
    def save_settings(self):
        """Saves all settings to the config file and applies them."""
        try:
            collector_width = int(self.collector_width_input.text())
            editor_width = int(self.editor_width_input.text())
            if not (200 <= collector_width <= 600 and 200 <= editor_width <= 600):
                raise ValueError("侧边栏宽度必须在 200 到 600 像素之间。")
        except ValueError as e:
            QMessageBox.warning(self, "输入无效", str(e))
            ui_settings = self.config.get("ui_settings", {})
            self.collector_width_input.setText(str(ui_settings.get("collector_sidebar_width", 320)))
            self.editor_width_input.setText(str(ui_settings.get("editor_sidebar_width", 280)))
            return

        # 1. 保存旧主题名以供比较
        old_theme = self.config.get('theme')
        new_theme = self.theme_combo.currentText()

        # 2. 更新配置字典
        self.config.setdefault("ui_settings", {})["collector_sidebar_width"] = collector_width
        self.config.setdefault("ui_settings", {})["editor_sidebar_width"] = editor_width
        
        self.config['theme'] = new_theme
        self.config['file_settings'] = {"word_list_file": self.word_list_combo.currentText(), "participant_base_name": self.participant_name_input.text(), "results_dir": self.results_dir_input.text()}
        self.config['gtts_settings'] = {"default_lang": self.gtts_lang_combo.currentText(), "auto_detect": self.gtts_auto_detect_switch.isChecked()}
        
        audio_settings = self.config.setdefault("audio_settings", {})
        audio_settings["sample_rate"] = int(self.sample_rate_combo.currentText().split(' ')[0])
        audio_settings["channels"] = int(self.channels_combo.currentText().split(' ')[0])
        audio_settings["recording_gain"] = self.gain_slider.value() / 10.0
        audio_settings["input_device_index"] = self.input_device_combo.currentData()

        try:
            # 3. 仅在主题更改或缓存文件不存在时，才更新缓存
            cache_path = os.path.join(THEMES_DIR, "_splash_progressbar.qss")
            if old_theme != new_theme or not os.path.exists(cache_path):
                print("主题已更改或缓存不存在，正在更新启动进度条样式...")
                self.cache_splash_progressbar_style()

            # 4. 写入主配置文件
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f: json.dump(self.config, f, indent=4)
            
            # 5. 应用更改
            self.parent_window.config = self.config 
            self.parent_window.apply_theme() 
            self.parent_window.apply_tooltips()
            
            for page_attr_name in ['accent_collection_page', 'voicebank_recorder_page', 
                                   'wordlist_editor_page', 'dialect_visual_editor_page', 'audio_manager_page',
                                   'dialect_visual_collector_page']: 
                page = getattr(self.parent_window, page_attr_name, None)
                if page and hasattr(page, 'apply_layout_settings'):
                    page.apply_layout_settings()

            QMessageBox.information(self, "成功", "所有设置已成功保存并应用！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")

    def cache_splash_progressbar_style(self):
        """
        解析选定的主题文件，提取 QProgressBar 的样式，并保存到缓存文件中。
        """
        selected_theme_file = self.theme_combo.currentText()
        theme_path = os.path.join(THEMES_DIR, selected_theme_file)
        cache_path = os.path.join(THEMES_DIR, "_splash_progressbar.qss")

        if not os.path.exists(theme_path):
            if os.path.exists(cache_path):
                try: os.remove(cache_path)
                except Exception as e: print(f"无法删除缓存的进度条样式: {e}")
            return

        try:
            with open(theme_path, 'r', encoding='utf-8') as f:
                full_qss = f.read()
            progressbar_styles = re.findall(r'(QProgressBar[^{]*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})', full_qss)
            
            final_style_to_cache = ""
            if progressbar_styles:
                final_style_to_cache = progressbar_styles[0]
                
            chunk_styles = re.findall(r'(QProgressBar::chunk[^{]*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})', full_qss)
            if chunk_styles:
                final_style_to_cache += "\n" + chunk_styles[0]
            
            if final_style_to_cache:
                with open(cache_path, 'w', encoding='utf-8') as f_cache:
                    f_cache.write(f"/* Auto-generated for splash screen from {selected_theme_file} */\n")
                    f_cache.write(final_style_to_cache)
                print(f"启动进度条样式已缓存至: {cache_path}")
            else:
                if os.path.exists(cache_path):
                    os.remove(cache_path)
        except Exception as e:
            print(f"缓存启动进度条样式时出错: {e}")

# ===== 主程序执行块 =====
if __name__ == "__main__":
    app = QApplication(sys.argv)
    BASE_PATH = get_base_path() 
    assets_path = os.path.join(BASE_PATH, "assets")
    
    splash_dir = os.path.join(assets_path, "splashes")
    splash_pix = None
    if os.path.exists(splash_dir) and os.path.isdir(splash_dir):
        images = [f for f in os.listdir(splash_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp'))]
        if images:
            chosen_image_path = os.path.join(splash_dir, random.choice(images))
            splash_pix = QPixmap(chosen_image_path)
            print(f"随机加载启动图: {os.path.basename(chosen_image_path)}")
    if splash_pix is None or splash_pix.isNull():
        default_splash_path = os.path.join(assets_path, "splash.png")
        splash_pix = QPixmap(default_splash_path)
        if splash_pix.isNull():
            splash_pix = QPixmap(600, 350)
            splash_pix.fill(QColor("#FCEAE4"))
    
    splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
    splash.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    
    splash.progressBar = QProgressBar(splash)
    splash.progressBar.setGeometry(15, splash_pix.height() - 60, splash_pix.width() - 30, 24)
    splash.progressBar.setRange(0, 100); splash.progressBar.setValue(0); splash.progressBar.setTextVisible(False)
    splash.setFont(QFont("Microsoft YaHei", 10))
    
    splash_progressbar_style_cache = os.path.join(get_base_path(), "themes", "_splash_progressbar.qss")
    
    splash_style = ""
    if os.path.exists(splash_progressbar_style_cache):
        try:
            with open(splash_progressbar_style_cache, 'r', encoding='utf-8') as f:
                splash_style = f.read()
            print("从缓存加载启动进度条样式。")
        except Exception as e:
            print(f"读取缓存样式失败: {e}")
            splash_style = ""

    if not splash_style:
        print("使用默认启动进度条样式。")
        splash_style = """
            QProgressBar {
                background-color: rgba(0, 0, 0, 80); border: none; border-radius: 12px; 
                text-align: center; color: white;
            }
            QProgressBar::chunk { background-color: white; border-radius: 12px; }
        """
        
    splash_style += """
        QSplashScreen > QLabel { 
            background-color: rgba(0, 0, 0, 100); color: white; 
            padding: 4px 8px; border-radius: 4px; 
        }
    """
    
    splash.setStyleSheet(splash_style)

    splash.show()
    splash.showMessage("正在准备环境...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
    app.processEvents()

    # --- 主程序执行流程 ---
    splash.showMessage("加载核心组件...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); splash.progressBar.setValue(10); app.processEvents()
    main_config = setup_and_load_config()
    
    tooltips_config = load_tooltips_config()
    
    splash.showMessage("加载用户配置...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); splash.progressBar.setValue(20); app.processEvents()
    ensure_directories_exist()
    splash.showMessage("准备文件目录...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); splash.progressBar.setValue(30); app.processEvents()
    load_modules(splash, progress_offset=30, progress_scale=0.4)
    splash.progressBar.setValue(70) 
    
    window = MainWindow(splash_ref=splash, tooltips_ref=tooltips_config)
    
    window.show()
    splash.finish(window)
    sys.exit(app.exec_())