# --- START OF FILE Beta.py ---

import os
import sys
import time # 用于非常短的延时，确保splash有时间绘制
import random

# ===== 阶段一：最小化初始导入，用于立即显示 Splash Screen =====
from PyQt5.QtWidgets import QApplication, QSplashScreen, QProgressBar, QSpinBox
from PyQt5.QtGui import QPixmap, QColor, QFont
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
MODULES = {}
main_config = {}


# 提前定义 get_base_path，因为它不依赖太多外部库
def get_base_path():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(".")

def ensure_directories_exist():
    """
    检查并创建程序运行所需的所有核心文件夹。
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


# ===== 主程序执行块提前，以便尽快显示 Splash Screen =====
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
    splash.setStyleSheet("""
        QProgressBar {
            background-color: rgba(0, 0, 0, 80); border: none; border-radius: 12px; text-align: center; color: white;
        }
        QProgressBar::chunk { background-color: white; border-radius: 12px; }
        QSplashScreen > QLabel { background-color: rgba(0, 0, 0, 100); color: white; padding: 4px 8px; border-radius: 4px; }
    """)
    splash.show()
    splash.showMessage("正在准备环境...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
    app.processEvents()

# ===== 阶段二：现在可以导入其他模块和定义函数了 =====
import json
import threading
import queue
from datetime import datetime
import importlib.util

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QListWidget, QListWidgetItem,
                             QLineEdit, QFileDialog, QMessageBox, QComboBox, QSlider, QStyle,
                             QFormLayout, QGroupBox, QCheckBox,
                             QTabWidget, QScrollArea) # QSpinBox 已在顶部导入
from PyQt5.QtCore import QThread, pyqtSignal, QObject, QTimer
from PyQt5.QtGui import QIcon, QFont, QPainter

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
    if 'splash' in locals() and splash: splash.hide()
    QMessageBox.critical(None, "依赖库缺失", f"错误: {e}\n\n请运行: pip install PyQt5 pandas openpyxl sounddevice soundfile numpy gtts")
    sys.exit(1)


# --- 全局路径变量的完整定义 ---
CONFIG_DIR = os.path.join(BASE_PATH, "config")
WORD_LIST_DIR = os.path.join(BASE_PATH, "word_lists")
THEMES_DIR = os.path.join(BASE_PATH, "themes")
AUDIO_TTS_DIR = os.path.join(BASE_PATH, "audio_tts")
AUDIO_RECORD_DIR = os.path.join(BASE_PATH, "audio_record")
MODULES_DIR = os.path.join(BASE_PATH, "modules")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")

# --- 动态模块加载 ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'modules')))
def load_modules(splash_ref=None, progress_offset=0, progress_scale=1.0):
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
            app.processEvents()
        module_name = filename[:-3]
        try:
            filepath = os.path.join(modules_dir, filename)
            spec = importlib.util.spec_from_file_location(module_name, filepath); module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            MODULES[module_name] = {'module': module, 'name': getattr(module, 'MODULE_NAME', module_name), 'desc': getattr(module, 'MODULE_DESCRIPTION', '无描述'), 'file': filename}
        except Exception as e: print(f"加载模块 '{filename}' 失败: {e}")

# --- 核心逻辑与辅助函数 ---
class Logger:
    def __init__(self, fp): self.fp = fp; open(self.fp, 'a', encoding='utf-8').write(f"\n--- Log started at {datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
    def log(self, msg): open(self.fp, 'a', encoding='utf-8').write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] - {msg}\n")

def setup_and_load_config():
    if not os.path.exists(CONFIG_DIR): os.makedirs(CONFIG_DIR)
    default_settings = {
        "ui_settings": {
            "collector_sidebar_width": 320,
            "editor_sidebar_width": 280
        },
        "audio_settings": {"sample_rate": 44100, "channels": 1, "recording_gain": 1.0},
        "file_settings": {"word_list_file": "default_list.py", "participant_base_name": "participant", "results_dir": os.path.join(BASE_PATH, "Results")},
        "gtts_settings": {"default_lang": "en-us", "auto_detect": True}, "theme": "Modern_light_tab.qss"
    }
    if not os.path.exists(SETTINGS_FILE): open(SETTINGS_FILE, 'w', encoding='utf-8').write(json.dumps(default_settings, indent=4))
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f: config = json.load(f)
        updated = False
        for key, value in default_settings.items():
            if key not in config:
                config[key] = value
                updated = True
        
        # 对内嵌字典进行深度检查
        if "collector_sidebar_width" not in config.get("ui_settings", {}):
            config.setdefault("ui_settings", {})["collector_sidebar_width"] = default_settings["ui_settings"]["collector_sidebar_width"]
            updated = True
        if "editor_sidebar_width" not in config.get("ui_settings", {}):
            config.setdefault("ui_settings", {})["editor_sidebar_width"] = default_settings["ui_settings"]["editor_sidebar_width"]
            updated = True
        if "sample_rate" not in config.get("audio_settings", {}): # 确保旧配置也能被更新
            config.setdefault("audio_settings", {})["sample_rate"] = default_settings["audio_settings"]["sample_rate"]
            updated = True
        if "channels" not in config.get("audio_settings", {}):
            config.setdefault("audio_settings", {})["channels"] = default_settings["audio_settings"]["channels"]
            updated = True
        if "recording_gain" not in config.get("audio_settings", {}):
            config.setdefault("audio_settings", {})["recording_gain"] = default_settings["audio_settings"]["recording_gain"]
            updated = True


        if updated: open(SETTINGS_FILE, 'w', encoding='utf-8').write(json.dumps(config, indent=4))
        return config
    except Exception as e:
        print(f"Error loading or updating config: {e}")
        return default_settings

def detect_language(text):
    if not text: return None
    ranges = {'han': (0x4e00, 0x9fff),'kana': (0x3040, 0x30ff),'hangul': (0xac00, 0xd7a3),'cyrillic': (0x0400, 0x04ff)}
    counts = {'han': 0,'kana': 0,'hangul': 0,'cyrillic': 0,'latin': 0,'other': 0}
    for char in text:
        code = ord(char)
        if ranges['han'][0] <= code <= ranges['han'][1]: counts['han'] += 1
        elif 'a' <= char.lower() <= 'z': counts['latin'] += 1
    if counts['han'] > 0: return 'zh-cn' # 简单示例，实际应用中可能更复杂
    if counts['kana'] > 0: return 'ja'
    if counts['hangul'] > 0: return 'ko'
    if counts['cyrillic'] > 0: return 'ru'
    return 'en-us' # 默认为英语

class Worker(QObject):
    finished = pyqtSignal(object); progress = pyqtSignal(int, str); error = pyqtSignal(str)
    def __init__(self, task, *args, **kwargs): super().__init__(); self.task=task; self.args=args; self.kwargs=kwargs
    def run(self):
        try:
            res = self.task(self, *self.args, **self.kwargs)
            self.finished.emit(res)
        except Exception as e: self.error.emit(f"后台任务失败: {e}")

class ToggleSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 30)
        self.setCursor(Qt.PointingHandCursor)
        self._bg_color = "#E0E0E0"; self._circle_color = QColor("white"); self._active_color = QColor("#8F4C33")
    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
        rect = self.rect()
        p.setBrush(self._active_color if self.isChecked() else QColor(self._bg_color))
        p.drawRoundedRect(rect, 15, 15)
        p.setBrush(self._circle_color); margin = 3; diameter = rect.height() - 2 * margin
        x_pos = rect.width() - diameter - margin if self.isChecked() else margin
        p.drawEllipse(x_pos, margin, diameter, diameter)
    def mousePressEvent(self, event):
        self.setChecked(not self.isChecked()); return super().mousePressEvent(event)

# ========== 主窗口和页面类 ==========
class MainWindow(QMainWindow):
    def __init__(self, splash_ref=None):
        super().__init__()
        self.splash_ref = splash_ref
        if self.splash_ref: self.splash_ref.showMessage("初始化主窗口...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); self.splash_ref.progressBar.setValue(35); app.processEvents()
        self.setWindowTitle("PhonAcq Assistant - 音韵习得实验助手"); self.setGeometry(100, 100, 1200, 850)
        icon_path = os.path.join(BASE_PATH, "icon.ico")
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))
        self.config = main_config
        self.main_tabs = QTabWidget(); self.main_tabs.setObjectName("MainTabWidget"); self.setCentralWidget(self.main_tabs)
        if self.splash_ref: self.splash_ref.showMessage("创建核心页面...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); self.splash_ref.progressBar.setValue(50); app.processEvents()
        
        self.accent_collection_page = self.create_module_or_placeholder('accent_collection_module', '口音采集会话', lambda m, ts, w, l: m.create_page(self, self.config, ts, w, l, detect_language, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH))
        self.voicebank_recorder_page = self.create_module_or_placeholder('voicebank_recorder_module', '语音包录制', lambda m, ts, w: m.create_page(self, WORD_LIST_DIR, AUDIO_RECORD_DIR, ts, w))
        self.audio_manager_page = self.create_module_or_placeholder('audio_manager_module', '数据管理器', lambda m: m.create_page(self, self.config, BASE_PATH, self.config['file_settings'].get("results_dir"), AUDIO_RECORD_DIR))
        self.wordlist_editor_page = self.create_module_or_placeholder('wordlist_editor_module', '词表编辑器', lambda m: m.create_page(self, WORD_LIST_DIR))
        self.converter_page = self.create_module_or_placeholder('excel_converter_module', 'Excel 转换器', lambda m: m.create_page(self, WORD_LIST_DIR, MODULES))
        self.help_page = self.create_module_or_placeholder('help_module', '帮助文档', lambda m: m.create_page(self))
        DIALECT_VISUAL_WORDLIST_DIR = os.path.join(BASE_PATH, "dialect_visual_wordlists"); os.makedirs(DIALECT_VISUAL_WORDLIST_DIR, exist_ok=True)
        self.dialect_visual_page = self.create_module_or_placeholder('dialect_visual_collector_module', '方言图文采集', lambda m, ts, w, l: m.create_page(self, self.config, BASE_PATH, DIALECT_VISUAL_WORDLIST_DIR, AUDIO_RECORD_DIR, ts, w, l))
        self.dialect_visual_editor_page = self.create_module_or_placeholder('dialect_visual_editor_module', '图文词表编辑器', lambda m: m.create_page(self, DIALECT_VISUAL_WORDLIST_DIR))
        self.pinyin_to_ipa_page = self.create_module_or_placeholder('pinyin_to_ipa_module', '拼音转IPA', lambda m, ts: m.create_page(self, ts))
        self.settings_page = SettingsPage(self)
        
        if self.splash_ref: self.splash_ref.showMessage("构建用户界面...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); self.splash_ref.progressBar.setValue(75); app.processEvents()
        
        collection_tabs = QTabWidget(); collection_tabs.setObjectName("SubTabWidget"); collection_tabs.addTab(self.accent_collection_page, "口音采集会话"); collection_tabs.addTab(self.voicebank_recorder_page, "语音包录制")
        dialect_study_tabs = QTabWidget(); dialect_study_tabs.setObjectName("SubTabWidget"); dialect_study_tabs.addTab(self.dialect_visual_page, "图文采集"); dialect_study_tabs.addTab(self.dialect_visual_editor_page, "图文词表编辑")
        corpus_tabs = QTabWidget(); corpus_tabs.setObjectName("SubTabWidget"); corpus_tabs.addTab(self.wordlist_editor_page, "词表编辑器"); corpus_tabs.addTab(self.converter_page, "Excel 转换器"); corpus_tabs.addTab(self.audio_manager_page, "数据管理器")
        utilities_tabs = QTabWidget(); utilities_tabs.setObjectName("SubTabWidget"); utilities_tabs.addTab(self.pinyin_to_ipa_page, "拼音转IPA")
        settings_and_help_tabs = QTabWidget(); settings_and_help_tabs.setObjectName("SubTabWidget"); settings_and_help_tabs.addTab(self.settings_page, "程序设置"); settings_and_help_tabs.addTab(self.help_page, "帮助文档")
        
        self.main_tabs.addTab(collection_tabs, "数据采集"); self.main_tabs.addTab(dialect_study_tabs, "方言研究"); self.main_tabs.addTab(corpus_tabs, "语料管理"); self.main_tabs.addTab(utilities_tabs, "实用工具"); self.main_tabs.addTab(settings_and_help_tabs, "系统与帮助")
        
        self.main_tabs.currentChanged.connect(self.on_main_tab_changed); collection_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("数据采集", i)); corpus_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("语料管理", i)); dialect_study_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("方言研究", i)); utilities_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("实用工具", i)); settings_and_help_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("系统与帮助", i))
        
        if self.splash_ref: self.splash_ref.showMessage("准备完成! (100%)", Qt.AlignBottom | Qt.AlignLeft, Qt.white); self.splash_ref.progressBar.setValue(100); app.processEvents()
        
        self.apply_theme(); self.on_main_tab_changed(0)

    def create_module_or_placeholder(self, module_key, name, page_factory):
        if module_key in MODULES:
            try:
                module = MODULES[module_key]['module']
                # 根据模块名决定是否传递额外参数
                if module_key == 'accent_collection_module':
                    return page_factory(module, ToggleSwitch, Worker, Logger) # detect_language 通过lambda传递
                elif module_key == 'dialect_visual_collector_module':
                    return page_factory(module, ToggleSwitch, Worker, Logger)
                elif module_key == 'pinyin_to_ipa_module':
                    return page_factory(module, ToggleSwitch)
                elif module_key == 'voicebank_recorder_module':
                    return page_factory(module, ToggleSwitch, Worker)
                else: # 适用于 audio_manager, wordlist_editor, excel_converter, help 等
                    return page_factory(module)
            except Exception as e: print(f"创建模块 '{name}' 页面时出错: {e}")
        page = QWidget(); layout = QVBoxLayout(page); layout.setAlignment(Qt.AlignCenter); layout.addWidget(QLabel(f"模块 '{name}' 未加载或创建失败。")); return page
        
    def on_main_tab_changed(self, index):
        # 使用 main_tabs.tabText(index) 来获取当前一级标签的文本
        current_main_tab_text = self.main_tabs.tabText(index)
        current_main_widget = self.main_tabs.widget(index)
        if current_main_widget and isinstance(current_main_widget, QTabWidget): # 确保是一二级标签页结构
            self.on_sub_tab_changed(current_main_tab_text, current_main_widget.currentIndex())
        
    def on_sub_tab_changed(self, group_name, index):
        # group_name 现在是一级标签的文本
        if group_name == "数据采集":
            if index == 0 and 'accent_collection_module' in MODULES: self.accent_collection_page.load_config_and_prepare()
            elif index == 1 and 'voicebank_recorder_module' in MODULES: self.voicebank_recorder_page.load_config_and_prepare()
        elif group_name == "方言研究":
            if index == 0 and 'dialect_visual_collector_module' in MODULES: self.dialect_visual_page.load_config_and_prepare()
            elif index == 1 and 'dialect_visual_editor_module' in MODULES: self.dialect_visual_editor_page.refresh_file_list()
        elif group_name == "语料管理":
            if index == 0 and 'wordlist_editor_module' in MODULES: self.wordlist_editor_page.refresh_file_list()
            elif index == 1 and 'excel_converter_module' in MODULES:
                # Excel转换器页面在切换时通常不需要特殊操作，其状态在内部管理
                pass
            elif index == 2 and 'audio_manager_module' in MODULES: self.audio_manager_page.load_and_refresh()
        elif group_name == "实用工具":
            # 拼音转IPA页面是静态的，目前无需加载
            pass
        elif group_name == "系统与帮助":
            if index == 0: self.settings_page.load_settings()
            elif index == 1 and hasattr(self, 'help_page') and hasattr(self.help_page, 'update_help_content'):
                self.help_page.update_help_content()

    def apply_theme(self):
        theme_path = os.path.join(THEMES_DIR, self.config.get("theme", "Modern_light_tab.qss"))
        if os.path.exists(theme_path):
            with open(theme_path, "r", encoding="utf-8") as f: self.setStyleSheet(f.read())
        else:
            print(f"主题文件未找到: {theme_path}")
            self.setStyleSheet("") # 应用空样式以清除旧样式
        if hasattr(self, 'help_page') and hasattr(self.help_page, 'update_help_content'):
            QTimer.singleShot(0, self.help_page.update_help_content)

# ===== SettingsPage 保持在主文件中，作为核心系统组件 =====
class SettingsPage(QWidget):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        
        # 主垂直布局
        main_layout = QVBoxLayout(self)

        # 创建一个水平布局来容纳两栏
        columns_layout = QHBoxLayout()

        # 左栏和右栏的垂直布局
        left_column_layout = QVBoxLayout()
        right_column_layout = QVBoxLayout()

        # --- 第1组: 界面与外观 (合并UI布局和主题) ---
        ui_appearance_group = QGroupBox("界面与外观")
        ui_appearance_form_layout = QFormLayout(ui_appearance_group)
        # UI布局设置
        self.collector_width_spin = QSpinBox(); self.collector_width_spin.setRange(200, 500); self.collector_width_spin.setSuffix(" px")
        self.editor_width_spin = QSpinBox(); self.editor_width_spin.setRange(200, 500); self.editor_width_spin.setSuffix(" px")
        ui_appearance_form_layout.addRow("采集类页面侧边栏宽度:", self.collector_width_spin)
        ui_appearance_form_layout.addRow("管理/编辑类页面侧边栏宽度:", self.editor_width_spin)
        # 主题设置
        self.theme_combo = QComboBox()
        ui_appearance_form_layout.addRow("主题皮肤:", self.theme_combo)
        
        # --- 第2组: 文件与路径 ---
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
        
        # --- 第3组: gTTS (在线) 设置 ---
        gtts_group = QGroupBox("gTTS (在线) 设置")
        gtts_layout = QFormLayout(gtts_group)
        self.gtts_lang_combo = QComboBox()
        self.gtts_lang_combo.addItems(['en-us','en-uk','en-au','en-in','zh-cn','ja','fr-fr','de-de','es-es','ru','ko'])
        self.gtts_auto_detect_switch = ToggleSwitch()
        auto_detect_layout = QHBoxLayout(); auto_detect_layout.addWidget(self.gtts_auto_detect_switch); auto_detect_layout.addStretch()
        gtts_layout.addRow("默认语言 (无指定时):", self.gtts_lang_combo)
        gtts_layout.addRow("自动检测语言 (中/日等):", auto_detect_layout)

        # --- 第4组: 音频与录音 ---
        audio_group = QGroupBox("音频与录音")
        audio_layout = QFormLayout(audio_group)
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
        
        # 将 GroupBox 添加到左右两栏
        left_column_layout.addWidget(ui_appearance_group)
        left_column_layout.addWidget(file_group)
        left_column_layout.addStretch() # 使得左栏的 GroupBox 向上靠拢

        right_column_layout.addWidget(gtts_group)
        right_column_layout.addWidget(audio_group)
        right_column_layout.addStretch() # 使得右栏的 GroupBox 向上靠拢

        # 将左右两栏添加到水平布局中
        columns_layout.addLayout(left_column_layout)
        columns_layout.addLayout(right_column_layout)

        # 保存按钮
        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存所有设置"); self.save_btn.setObjectName("AccentButton")
        button_layout.addStretch(); button_layout.addWidget(self.save_btn)
        
        # 将包含两栏的水平布局和按钮布局添加到主垂直布局
        main_layout.addLayout(columns_layout)
        main_layout.addLayout(button_layout)
        
        # 连接信号
        self.gain_slider.valueChanged.connect(lambda v: self.gain_label.setText(f"{v/10.0:.1f}x"))
        self.save_btn.clicked.connect(self.save_settings)
        self.results_dir_btn.clicked.connect(self.select_results_dir)
        self.theme_combo.currentTextChanged.connect(self.preview_theme)

    def populate_all(self):
        self.populate_themes(); self.populate_word_lists()

    def select_results_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择结果文件夹", self.results_dir_input.text())
        if directory: self.results_dir_input.setText(directory)

    def populate_word_lists(self):
        self.word_list_combo.clear()
        if os.path.exists(WORD_LIST_DIR): self.word_list_combo.addItems([f for f in os.listdir(WORD_LIST_DIR) if f.endswith('.py')])

    def populate_themes(self):
        self.theme_combo.clear()
        if os.path.exists(THEMES_DIR): self.theme_combo.addItems([f for f in os.listdir(THEMES_DIR) if f.endswith('.qss')])
    
    def load_settings(self):
        self.populate_all()
        self.config = self.parent_window.config
        
        ui_settings = self.config.get("ui_settings", {})
        self.collector_width_spin.setValue(ui_settings.get("collector_sidebar_width", 320))
        self.editor_width_spin.setValue(ui_settings.get("editor_sidebar_width", 280))

        self.theme_combo.setCurrentText(self.config.get("theme", "Modern_light_tab.qss"))
        file_settings = self.config.get("file_settings", {}); gtts_settings = self.config.get("gtts_settings", {}); audio_settings = self.config.get("audio_settings", {})
        
        self.word_list_combo.setCurrentText(file_settings.get('word_list_file', ''))
        self.participant_name_input.setText(file_settings.get('participant_base_name', ''))
        self.results_dir_input.setText(file_settings.get("results_dir", os.path.join(BASE_PATH, "Results")))
        self.gtts_lang_combo.setCurrentText(gtts_settings.get('default_lang', 'en-us'))
        self.gtts_auto_detect_switch.setChecked(gtts_settings.get('auto_detect', True))
        
        sr_text = next((s for s in [self.sample_rate_combo.itemText(i) for i in range(self.sample_rate_combo.count())] if str(audio_settings.get('sample_rate', 44100)) in s), "44100 Hz (CD质量, 推荐)")
        self.sample_rate_combo.setCurrentText(sr_text)
        ch_text = next((s for s in [self.channels_combo.itemText(i) for i in range(self.channels_combo.count())] if str(audio_settings.get('channels', 1)) in s), "1 (单声道, 推荐)")
        self.channels_combo.setCurrentText(ch_text)
        gain = audio_settings.get('recording_gain', 1.0)
        self.gain_slider.setValue(int(gain * 10))

    def preview_theme(self, theme_file):
        if not theme_file: return
        theme_path = os.path.join(THEMES_DIR, theme_file)
        if os.path.exists(theme_path):
            with open(theme_path, "r", encoding="utf-8") as f: self.parent_window.setStyleSheet(f.read())
            
    def save_settings(self):
        self.config.setdefault("ui_settings", {})["collector_sidebar_width"] = self.collector_width_spin.value()
        self.config.setdefault("ui_settings", {})["editor_sidebar_width"] = self.editor_width_spin.value()
        
        self.config['theme'] = self.theme_combo.currentText()
        self.config['file_settings'] = {"word_list_file": self.word_list_combo.currentText(), "participant_base_name": self.participant_name_input.text(), "results_dir": self.results_dir_input.text()}
        self.config['gtts_settings'] = {"default_lang": self.gtts_lang_combo.currentText(), "auto_detect": self.gtts_auto_detect_switch.isChecked()}
        sample_rate_text = self.sample_rate_combo.currentText().split(' ')[0]
        channels_text = self.channels_combo.currentText().split(' ')[0]
        self.config['audio_settings'] = {"sample_rate": int(sample_rate_text), "channels": int(channels_text), "recording_gain": self.gain_slider.value() / 10.0}
        
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f: json.dump(self.config, f, indent=4)
            self.parent_window.config = self.config # 更新主窗口的配置引用
            self.parent_window.apply_theme() # 应用主题，这也会触发帮助页面的CSS更新
            # 触发所有受影响的页面更新其布局
            if hasattr(self.parent_window, 'accent_collection_page') and hasattr(self.parent_window.accent_collection_page, 'apply_layout_settings'):
                self.parent_window.accent_collection_page.apply_layout_settings()
            if hasattr(self.parent_window, 'voicebank_recorder_page') and hasattr(self.parent_window.voicebank_recorder_page, 'apply_layout_settings'):
                self.parent_window.voicebank_recorder_page.apply_layout_settings()
            if hasattr(self.parent_window, 'wordlist_editor_page') and hasattr(self.parent_window.wordlist_editor_page, 'apply_layout_settings'):
                self.parent_window.wordlist_editor_page.apply_layout_settings()
            if hasattr(self.parent_window, 'dialect_visual_editor_page') and hasattr(self.parent_window.dialect_visual_editor_page, 'apply_layout_settings'):
                self.parent_window.dialect_visual_editor_page.apply_layout_settings()
            if hasattr(self.parent_window, 'audio_manager_page') and hasattr(self.parent_window.audio_manager_page, 'apply_layout_settings'):
                self.parent_window.audio_manager_page.apply_layout_settings()

            QMessageBox.information(self, "成功", "所有设置已成功保存并应用！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")

if __name__ == "__main__":
    splash.showMessage("加载核心组件...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); splash.progressBar.setValue(10); app.processEvents()
    main_config = setup_and_load_config()
    splash.showMessage("加载用户配置...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); splash.progressBar.setValue(20); app.processEvents()
    ensure_directories_exist()
    splash.showMessage("准备文件目录...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); splash.progressBar.setValue(30); app.processEvents()
    load_modules(splash, progress_offset=30, progress_scale=0.4)
    splash.progressBar.setValue(70) # 假设加载模块占用了40%的进度条
    window = MainWindow(splash_ref=splash) # MainWindow的init会处理剩下的进度
    window.show()
    splash.finish(window)
    sys.exit(app.exec_())