# --- START OF FILE Dev.py ---

import os
import sys
import time
import random
import re

# ==============================================================================
# 阶段一：绝对最小化导入，用于瞬时启动画面
# ==============================================================================
from PyQt5.QtWidgets import QApplication, QSplashScreen, QProgressBar
from PyQt5.QtGui import QPixmap, QColor, QFont
from PyQt5.QtCore import Qt, QCoreApplication

# --- 启动画面立即执行 ---
if __name__ == "__main__":
    app = QApplication(sys.argv)

    def get_base_path_for_splash():
        if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
        else: return os.path.abspath(".")
    
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
    splash.progressBar.setRange(0, 100); splash.progressBar.setValue(0); splash.progressBar.setTextVisible(False)
    splash.setFont(QFont("Microsoft YaHei", 10))
    
    hardcoded_style = """
        QProgressBar { background-color: rgba(0, 0, 0, 120); border: 1px solid rgba(255, 255, 255, 80); border-radius: 12px; text-align: center; color: white; }
        QProgressBar::chunk { background-color: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #FFDBCF, stop: 1 #FCEAE4); border-radius: 11px; }
        QSplashScreen > QLabel { background-color: rgba(0, 0, 0, 150); color: white; padding: 4px 8px; border-radius: 4px; }
    """
    splash.setStyleSheet(hardcoded_style)
    
    splash.show()
    splash.showMessage("正在准备环境...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
    
    app.processEvents()

# ==============================================================================
# 阶段二：延迟导入所有重量级库和应用模块
# ==============================================================================
import json
import threading
import queue
from datetime import datetime
import importlib.util

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QListWidget, QListWidgetItem, QLineEdit, 
                             QFileDialog, QMessageBox, QComboBox, QSlider, QStyle, 
                             QFormLayout, QGroupBox, QCheckBox, QTabWidget, QScrollArea, 
                             QSpacerItem, QSizePolicy)
from PyQt5.QtGui import QIntValidator, QPainter, QPen, QBrush, QIcon
from PyQt5.QtCore import QThread, pyqtSignal, QObject, QTimer, pyqtProperty, QRect

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
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
TOOLTIPS_FILE = os.path.join(CONFIG_DIR, "tooltips.json")

tooltips_config = {}
MODULES = {}
main_config = {}

# --- 辅助函数和核心类 ---
def ensure_directories_exist():
    required_paths = [
        CONFIG_DIR, WORD_LIST_DIR, THEMES_DIR, AUDIO_TTS_DIR, AUDIO_RECORD_DIR, MODULES_DIR,
        os.path.join(BASE_PATH, "assets", "flags"), os.path.join(BASE_PATH, "assets", "help"),
        os.path.join(BASE_PATH, "assets", "splashes"), os.path.join(BASE_PATH, "dialect_visual_wordlists"),
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
    global MODULES; MODULES = {}
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
            spec = importlib.util.spec_from_file_location(module_name, filepath); module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            MODULES[module_name] = {'module': module, 'name': getattr(module, 'MODULE_NAME', module_name), 'desc': getattr(module, 'MODULE_DESCRIPTION', '无描述'), 'file': filename}
        except Exception as e: print(f"加载模块 '{filename}' 失败: {e}", file=sys.stderr)

def load_tooltips_config():
    default_tooltips = {
        "数据采集": { "description": "包含所有用于实时录制和收集语音数据的功能模块。", "sub_tabs": { "口音采集会话": "适用于标准的文本到语音朗读任务。", "语音包录制": "用于为标准词表录制高质量的真人提示音。" }},
        "方言研究": { "description": "专为方言学田野调查设计的工具集。", "sub_tabs": { "图文采集": "展示图片并录制方言描述。", "图文词表编辑": "在程序内直接创建、编辑和保存用于“图文采集”的词表。" }},
        "语料管理": { "description": "提供对项目所使用的词表和已生成的音频数据进行管理的工具。", "sub_tabs": { "词表编辑器": "可视化地创建和编辑标准词表。", "Excel 转换器": "支持标准词表与图文词表的双向转换。", "数据管理器": "浏览、试听、重命名和删除所有已录制的音频数据。" }},
        "实用工具": { "description": "提供一系列辅助性的语言学工具。", "sub_tabs": { "拼音转IPA": "将汉字实时转换为国际音标。", "TTS 工具": "批量或即时将文本列表转换为语音文件。" }},
        "系统与帮助": { "description": "配置应用程序的行为、外观，并获取使用帮助。", "sub_tabs": { "程序设置": "调整应用的各项参数，包括UI布局、音频设备和主题皮肤等。", "帮助文档": "提供详细的程序使用指南和常见问题解答。" }}
    }
    if not os.path.exists(TOOLTIPS_FILE):
        try:
            with open(TOOLTIPS_FILE, 'w', encoding='utf-8') as f: json.dump(default_tooltips, f, indent=4, ensure_ascii=False)
            return default_tooltips
        except Exception: return {}
    try:
        with open(TOOLTIPS_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception: return {}

class Logger:
    def __init__(self, fp): self.fp = fp; open(self.fp, 'a', encoding='utf-8').write(f"\n--- Log started at {datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
    def log(self, msg): open(self.fp, 'a', encoding='utf-8').write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] - {msg}\n")

def setup_and_load_config():
    if not os.path.exists(CONFIG_DIR): os.makedirs(CONFIG_DIR)
    default_settings = {
        "ui_settings": { "collector_sidebar_width": 320, "editor_sidebar_width": 280 },
        "audio_settings": { "sample_rate": 44100, "channels": 1, "recording_gain": 1.0, "input_device_index": None, "recording_format": "wav" },
        "file_settings": {"word_list_file": "default_list.py", "participant_base_name": "participant", "results_dir": os.path.join(BASE_PATH, "Results")},
        "gtts_settings": {"default_lang": "en-us", "auto_detect": True},
        "theme": "Modern_light_tab.qss"
    }
    if not os.path.exists(SETTINGS_FILE): open(SETTINGS_FILE, 'w', encoding='utf-8').write(json.dumps(default_settings, indent=4))
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f: config = json.load(f)
        updated = False
        for key, default_value_section in default_settings.items():
            if key not in config: config[key] = default_value_section; updated = True
            elif not isinstance(config[key], dict) and isinstance(default_value_section, dict): config[key] = default_value_section; updated = True
            elif isinstance(config[key], dict) and isinstance(default_value_section, dict):
                for sub_key, default_sub_value in default_value_section.items():
                    if sub_key not in config[key]: config[key][sub_key] = default_sub_value; updated = True
        if updated: open(SETTINGS_FILE, 'w', encoding='utf-8').write(json.dumps(config, indent=4))
        return config
    except Exception: return default_settings

def detect_language(text):
    if not text: return None
    ranges = { 'han': (0x4e00, 0x9fff), 'kana': (0x3040, 0x30ff), 'hangul_syllables': (0xac00, 0xd7a3), 'hangul_jamo': (0x1100, 0x11ff), 'hangul_compat_jamo': (0x3130, 0x318f), 'cyrillic': (0x0400, 0x04ff), 'latin_basic': (0x0041, 0x005a), 'latin_basic_lower': (0x0061, 0x007a) }
    counts = {key: 0 for key in ranges}; counts['other'] = 0; total_meaningful_chars = 0
    for char in text:
        code = ord(char); is_meaningful = False
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
    finished = pyqtSignal(object); progress = pyqtSignal(int, str); error = pyqtSignal(str)
    def __init__(self, task, *args, **kwargs): super().__init__(); self.task=task; self.args=args; self.kwargs=kwargs
    def run(self):
        try: res = self.task(self, *self.args, **self.kwargs); self.finished.emit(res)
        except Exception as e: self.error.emit(f"后台任务失败: {e}")

class ToggleSwitch(QCheckBox):
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
            half_pen_width = self._borderWidth // 2; border_rect = rect.adjusted(half_pen_width, half_pen_width, -half_pen_width, -half_pen_width)
            p.setBrush(Qt.NoBrush); p.drawRoundedRect(border_rect, self.trackBorderRadius, self.trackBorderRadius)
        p.setPen(Qt.NoPen); track_color = self.trackColorOn if self.isChecked() else self.trackColorOff
        p.setBrush(QBrush(track_color)); track_rect = rect.adjusted(self._borderWidth, self._borderWidth, -self._borderWidth, -self._borderWidth)
        track_inner_radius = max(0, self.trackBorderRadius - self._borderWidth)
        p.drawRoundedRect(track_rect, track_inner_radius, track_inner_radius)
        margin = self.knobMargin; knob_height = track_rect.height() - (2 * margin); knob_width = knob_height 
        x_pos = track_rect.right() - knob_width - margin + 1 if self.isChecked() else track_rect.left() + margin
        knob_rect = QRect(x_pos, track_rect.top() + margin, knob_width, knob_height); p.setBrush(QBrush(self.knobColor))
        if self.knobShape == 'rectangle': p.drawRoundedRect(knob_rect, self.knobBorderRadius, self.knobBorderRadius)
        else: p.drawEllipse(knob_rect)
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton: self.setChecked(not self.isChecked()); event.accept() 
        else: super().mousePressEvent(event)

class MainWindow(QMainWindow):
    def __init__(self, splash_ref=None, tooltips_ref=None):
        super().__init__()
        self.splash_ref = splash_ref
        self.tooltips_config = tooltips_ref if tooltips_ref is not None else {}
        
        if self.splash_ref: self.splash_ref.showMessage("初始化主窗口...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); self.splash_ref.progressBar.setValue(75); QApplication.processEvents()
        self.setWindowTitle("PhonAcq - 风纳客"); self.setGeometry(100, 100, 1200, 850)
        icon_path = os.path.join(BASE_PATH, "config", "icon.ico") 
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))
        self.config = main_config
        self.main_tabs = QTabWidget(); self.main_tabs.setObjectName("MainTabWidget"); self.setCentralWidget(self.main_tabs)
        if self.splash_ref: self.splash_ref.showMessage("创建核心页面...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); self.splash_ref.progressBar.setValue(80); QApplication.processEvents()

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
            lambda m, ts: m.create_page(self, DIALECT_VISUAL_WORDLIST_DIR, ts) # [修改] lambda现在接收并传递ts (ToggleSwitch)
        )
        self.pinyin_to_ipa_page = self.create_module_or_placeholder('pinyin_to_ipa_module', '拼音转IPA', 
            lambda m, ts: m.create_page(self, ts))
        self.tts_utility_page = self.create_module_or_placeholder('tts_utility_module', 'TTS 工具',
            lambda m, ts, w, dl, std_wld: m.create_page(self, self.config, AUDIO_TTS_DIR, ts, w, dl, std_wld)
        )
        self.flashcard_page = self.create_module_or_placeholder('flashcard_module', '速记卡',
            lambda m, ts, sil: m.create_page(self, ts, sil, BASE_PATH, AUDIO_TTS_DIR, AUDIO_RECORD_DIR)
        )
        self.settings_page = self.create_module_or_placeholder('settings_module', '程序设置',
            lambda m, ts, t_dir, w_dir: m.create_page(self, ts, t_dir, w_dir)
        )
        
        if self.splash_ref: self.splash_ref.showMessage("构建用户界面...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); self.splash_ref.progressBar.setValue(90); QApplication.processEvents()
        collection_tabs = QTabWidget(); collection_tabs.setObjectName("SubTabWidget"); collection_tabs.addTab(self.accent_collection_page, "口音采集会话"); collection_tabs.addTab(self.voicebank_recorder_page, "语音包录制")
        dialect_study_tabs = QTabWidget(); dialect_study_tabs.setObjectName("SubTabWidget"); dialect_study_tabs.addTab(self.dialect_visual_page, "图文采集"); dialect_study_tabs.addTab(self.dialect_visual_editor_page, "图文词表编辑")
        corpus_tabs = QTabWidget(); corpus_tabs.setObjectName("SubTabWidget"); corpus_tabs.addTab(self.wordlist_editor_page, "词表编辑器"); corpus_tabs.addTab(self.converter_page, "Excel 转换器"); corpus_tabs.addTab(self.audio_manager_page, "数据管理器")
        utilities_tabs = QTabWidget(); utilities_tabs.setObjectName("SubTabWidget"); utilities_tabs.addTab(self.pinyin_to_ipa_page, "拼音转IPA"); utilities_tabs.addTab(self.tts_utility_page, "TTS 工具"); utilities_tabs.addTab(self.flashcard_page, "速记卡")
        settings_and_help_tabs = QTabWidget(); settings_and_help_tabs.setObjectName("SubTabWidget"); settings_and_help_tabs.addTab(self.settings_page, "程序设置"); settings_and_help_tabs.addTab(self.help_page, "帮助文档")
        self.main_tabs.addTab(collection_tabs, "数据采集"); self.main_tabs.addTab(dialect_study_tabs, "方言研究"); self.main_tabs.addTab(corpus_tabs, "语料管理"); self.main_tabs.addTab(utilities_tabs, "实用工具"); self.main_tabs.addTab(settings_and_help_tabs, "系统与帮助")
        self.main_tabs.currentChanged.connect(self.on_main_tab_changed); collection_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("数据采集", i)); corpus_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("语料管理", i)); dialect_study_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("方言研究", i)); utilities_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("实用工具", i)); settings_and_help_tabs.currentChanged.connect(lambda i: self.on_sub_tab_changed("系统与帮助", i))
        
        self.apply_tooltips()
        
        if self.splash_ref: self.splash_ref.showMessage("准备完成!", Qt.AlignBottom | Qt.AlignLeft, Qt.white); self.splash_ref.progressBar.setValue(100); QApplication.processEvents()
        self.apply_theme(); self.on_main_tab_changed(0)
        
    def apply_tooltips(self):
        if not self.tooltips_config: return
        for i in range(self.main_tabs.count()):
            main_tab_text = self.main_tabs.tabText(i); main_tab_data = self.tooltips_config.get(main_tab_text, {})
            self.main_tabs.setTabToolTip(i, main_tab_data.get('description', f"{main_tab_text} 功能模块"))
            sub_tab_widget = self.main_tabs.widget(i)
            if isinstance(sub_tab_widget, QTabWidget):
                sub_tabs_data = main_tab_data.get('sub_tabs', {});
                for j in range(sub_tab_widget.count()):
                    sub_tab_text = sub_tab_widget.tabText(j)
                    sub_tab_widget.setTabToolTip(j, sub_tabs_data.get(sub_tab_text, "无详细描述。"))

    def create_module_or_placeholder(self, module_key, name, page_factory):
        if module_key in MODULES:
            try:
                module = MODULES[module_key]['module']
                
                # --- 根据模块的 key 注入不同的依赖项 ---

                if module_key == 'settings_module':
                    # 设置模块需要 ToggleSwitch 和两个路径
                    return page_factory(module, ToggleSwitch, THEMES_DIR, WORD_LIST_DIR)
                
                elif module_key == 'flashcard_module':
                    # 速记卡模块需要 ToggleSwitch 和 ScalableImageLabel
                    # 我们从已加载的 dialect_visual_collector_module 中获取 ScalableImageLabel
                    from PyQt5.QtWidgets import QLabel # 作为备用
                    ScalableImageLabelClass = QLabel
                    if 'dialect_visual_collector_module' in MODULES:
                        ScalableImageLabelClass = getattr(MODULES['dialect_visual_collector_module']['module'], 'ScalableImageLabel', QLabel)
                    return page_factory(module, ToggleSwitch, ScalableImageLabelClass)

                elif module_key in ['accent_collection_module', 'dialect_visual_collector_module']:
                    # 这两个采集模块需要 ToggleSwitch, Worker, 和 Logger
                    return page_factory(module, ToggleSwitch, Worker, Logger)

                elif module_key == 'voicebank_recorder_module':
                     # 语音包录制模块需要 ToggleSwitch 和 Worker
                    return page_factory(module, ToggleSwitch, Worker)
                
                elif module_key == 'pinyin_to_ipa_module':
                    # 拼音转换模块只需要 ToggleSwitch
                    return page_factory(module, ToggleSwitch)
                
                elif module_key == 'dialect_visual_editor_module':
                    # 图文词表编辑器模块只需要 ToggleSwitch
                    return page_factory(module, ToggleSwitch)
                    
                elif module_key == 'tts_utility_module':
                    # TTS 工具模块需要多个依赖
                    return page_factory(module, ToggleSwitch, Worker, detect_language, WORD_LIST_DIR) 

                else:
                    # 对于没有特殊依赖的模块 (如 help_module, excel_converter_module 等)
                    return page_factory(module)

            except Exception as e:
                print(f"创建模块 '{name}' 页面时出错: {e}", file=sys.stderr)
        
        # --- 如果模块加载失败，则创建占位符页面 ---
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        
        if module_key == 'settings_module':
            label_text = f"设置模块 ('{name}') 加载失败。\n请检查 'modules/settings_module.py' 文件是否存在且无误。"
        else:
            label_text = f"模块 '{name}' 未加载或创建失败。"
            
        label = QLabel(label_text)
        label.setWordWrap(True)
        layout.addWidget(label)
        return page
    def on_main_tab_changed(self, index):
        current_main_tab_text = self.main_tabs.tabText(index)
        current_main_widget = self.main_tabs.widget(index)
        if current_main_widget and isinstance(current_main_widget, QTabWidget): 
            self.on_sub_tab_changed(current_main_tab_text, current_main_widget.currentIndex())
        
    def on_sub_tab_changed(self, group_name, index):
        try:
            main_tab_content_widget = None
            for i in range(self.main_tabs.count()):
                if self.main_tabs.tabText(i) == group_name:
                    main_tab_content_widget = self.main_tabs.widget(i); break
            if not main_tab_content_widget or not isinstance(main_tab_content_widget, QTabWidget): return
            active_sub_tab_widget = main_tab_content_widget.widget(index)
        except Exception: active_sub_tab_widget = None

        if group_name == "数据采集":
            if index == 0 and 'accent_collection_module' in MODULES and hasattr(self, 'accent_collection_page') and self.accent_collection_page == active_sub_tab_widget: self.accent_collection_page.load_config_and_prepare()
            elif index == 1 and 'voicebank_recorder_module' in MODULES and hasattr(self, 'voicebank_recorder_page') and self.voicebank_recorder_page == active_sub_tab_widget: self.voicebank_recorder_page.load_config_and_prepare()
        elif group_name == "方言研究":
            if index == 0 and 'dialect_visual_collector_module' in MODULES and hasattr(self, 'dialect_visual_page') and self.dialect_visual_page == active_sub_tab_widget: self.dialect_visual_page.load_config_and_prepare()
            elif index == 1 and 'dialect_visual_editor_module' in MODULES and hasattr(self, 'dialect_visual_editor_page') and self.dialect_visual_editor_page == active_sub_tab_widget: self.dialect_visual_editor_page.refresh_file_list()
        elif group_name == "语料管理":
            if index == 0 and 'wordlist_editor_module' in MODULES and hasattr(self, 'wordlist_editor_page') and self.wordlist_editor_page == active_sub_tab_widget: self.wordlist_editor_page.refresh_file_list()
            elif index == 2 and 'audio_manager_module' in MODULES and hasattr(self, 'audio_manager_page') and self.audio_manager_page == active_sub_tab_widget: self.audio_manager_page.load_and_refresh()
        elif group_name == "系统与帮助":
            if index == 0 and hasattr(self, 'settings_page') and self.settings_page == active_sub_tab_widget: self.settings_page.load_settings()
            elif index == 1 and hasattr(self, 'help_page') and self.help_page == active_sub_tab_widget and hasattr(self.help_page, 'update_help_content'): self.help_page.update_help_content()
            
    def apply_theme(self):
        theme_path = os.path.join(THEMES_DIR, self.config.get("theme", "Modern_light_tab.qss"))
        if os.path.exists(theme_path):
            with open(theme_path, "r", encoding="utf-8") as f: self.setStyleSheet(f.read())
        else:
            print(f"主题文件未找到: {theme_path}", file=sys.stderr)
            self.setStyleSheet("") 
        if hasattr(self, 'help_page') and hasattr(self.help_page, 'update_help_content'):
            QTimer.singleShot(0, self.help_page.update_help_content)

# --- 主程序执行块 ---
if __name__ == "__main__":
    splash.showMessage("加载核心组件...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); splash.progressBar.setValue(10); app.processEvents()
    main_config = setup_and_load_config()
    
    splash.showMessage("加载用户配置...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); splash.progressBar.setValue(20); app.processEvents()
    tooltips_config = load_tooltips_config()
    
    splash.showMessage("准备文件目录...", Qt.AlignBottom | Qt.AlignLeft, Qt.white); splash.progressBar.setValue(30); app.processEvents()
    ensure_directories_exist()
    
    load_modules(progress_offset=30, progress_scale=0.4)
    
    window = MainWindow(splash_ref=splash, tooltips_ref=tooltips_config)
    
    window.show()
    
    splash.finish(window)
    
    sys.exit(app.exec_())