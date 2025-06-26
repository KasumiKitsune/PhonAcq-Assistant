import os
import sys
import time # 用于非常短的延时，确保splash有时间绘制
import random

# ===== 阶段一：最小化初始导入，用于立即显示 Splash Screen =====
from PyQt5.QtWidgets import QApplication, QSplashScreen, QProgressBar
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
    # 将所有需要存在的文件夹路径放入一个列表中
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
        # 从配置中读取结果文件夹路径，也一并检查创建
        # 注意: setup_and_load_config 必须在此之前被调用
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

    # 尽早计算 BASE_PATH，因为 splash 图片路径依赖它
    BASE_PATH = get_base_path() 
    assets_path = os.path.join(BASE_PATH, "assets") # assets 文件夹路径
    splash_dir = os.path.join(assets_path, "splashes")
    splash_pix = None
    
    # 尝试从新目录随机加载
    if os.path.exists(splash_dir) and os.path.isdir(splash_dir):
        images = [f for f in os.listdir(splash_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp'))]
        if images:
            chosen_image_path = os.path.join(splash_dir, random.choice(images))
            splash_pix = QPixmap(chosen_image_path)
            print(f"随机加载启动图: {os.path.basename(chosen_image_path)}")

    # 如果随机加载失败，则回退到默认路径
    if splash_pix is None or splash_pix.isNull():
        default_splash_path = os.path.join(assets_path, "splash.png")
        splash_pix = QPixmap(default_splash_path)
        if splash_pix.isNull():
            print(f"警告: 所有启动图片均未找到。创建默认颜色背景。")
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
    
    # 新的、更现代的QSS样式
    splash.setStyleSheet("""
        QProgressBar {
            background-color: rgba(0, 0, 0, 80); /* 半透明深色轨道 */
            border: none;
            border-radius: 12px;
            text-align: center;
            color: white; /* 进度百分比文字颜色 (如果显示) */
        }
        QProgressBar::chunk {
            background-color: white; /* 进度块颜色 */
            border-radius: 12px;
        }
        /* 为启动消息(showMessage)的 QLabel 添加样式 */
        QSplashScreen > QLabel {
            background-color: rgba(0, 0, 0, 100); /* 更深的半透明背景以保证可读性 */
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
        }
    """)

    splash.show()
    # 强制处理事件，确保启动画面立即绘制出来
    splash.showMessage("正在准备环境...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
    app.processEvents() # 使用 app.processEvents() 更通用
    # time.sleep(0.05) # 给UI一点点时间响应，如果非常快，可以不需要

# ===== 阶段二：现在可以导入其他模块和定义函数了 =====
# 这些导入会在启动画面显示之后执行

import json
import random
import threading
import queue
from datetime import datetime
import importlib.util

# --- 延迟导入的 PyQt5 控件 ---
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QListWidget, QListWidgetItem,
                             QLineEdit, QFileDialog, QMessageBox, QComboBox, QSlider, QStyle,
                             QPlainTextEdit, QFormLayout, QGroupBox, QCheckBox,
                             QTabWidget, QScrollArea)
from PyQt5.QtCore import QThread, pyqtSignal, QObject, QTimer # QCoreApplication 已在顶部导入
from PyQt5.QtGui import QIcon, QFont, QPainter # QPixmap, QColor 已在顶部导入

# --- 延迟导入的第三方依赖库 ---
# 我们将它们的导入和错误处理也放在这个阶段
try:
    import pandas as pd
    import openpyxl
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
    from gtts import gTTS
    import pypinyin
except ImportError as e:
    # 如果在这里出错，启动画面已经显示，我们可以通过它提示用户
    if 'splash' in locals() and splash: # 确保splash已定义
        splash.hide() # 先隐藏启动画面
    QMessageBox.critical(None, "依赖库缺失", f"错误: {e}\n\n请运行: pip install PyQt5 pandas openpyxl sounddevice soundfile numpy gtts")
    sys.exit(1)


# --- 全局路径变量的完整定义 (依赖 BASE_PATH) ---
CONFIG_DIR = os.path.join(BASE_PATH, "config")
WORD_LIST_DIR = os.path.join(BASE_PATH, "word_lists")
THEMES_DIR = os.path.join(BASE_PATH, "themes")
AUDIO_TTS_DIR = os.path.join(BASE_PATH, "audio_tts")
AUDIO_RECORD_DIR = os.path.join(BASE_PATH, "audio_record")
MODULES_DIR = os.path.join(BASE_PATH, "modules")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")

# --- 动态模块加载 ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'modules')))
def load_modules(splash_ref=None, progress_offset=0, progress_scale=1.0): # 参数名改为 splash_ref
    global MODULES; MODULES = {}
    modules_dir = os.path.join(get_base_path(), "modules")
    if not os.path.exists(modules_dir): os.makedirs(modules_dir)
    
    module_files = [f for f in os.listdir(modules_dir) if f.endswith('.py') and not f.startswith('__')]
    total_modules = len(module_files)
    
    for i, filename in enumerate(module_files):
        if splash_ref:
            current_module_progress_in_stage = int((i + 1) / total_modules * 100) if total_modules > 0 else 100
            splash_ref.showMessage(f"加载模块: {filename} ({current_module_progress_in_stage}% of modules)...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            app.processEvents()

        module_name = filename[:-3]
        try:
            filepath = os.path.join(modules_dir, filename)
            spec = importlib.util.spec_from_file_location(module_name, filepath); module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            MODULES[module_name] = {'module': module, 'name': getattr(module, 'MODULE_NAME', module_name), 'desc': getattr(module, 'MODULE_DESCRIPTION', '无描述'), 'file': filename}
        except Exception as e: print(f"加载模块 '{filename}' 失败: {e}")

# --- 核心逻辑与辅助函数 (Logger, setup_and_load_config, detect_language, Worker, ToggleSwitch) ---
# ... (这些函数的定义保持不变，但它们现在在延迟导入之后) ...
# 您之前提供的版本已经是最新，这里不再重复粘贴

class Logger:
    def __init__(self, fp): self.fp = fp; open(self.fp, 'a', encoding='utf-8').write(f"\n--- Log started at {datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
    def log(self, msg): open(self.fp, 'a', encoding='utf-8').write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] - {msg}\n")

def setup_and_load_config():
    if not os.path.exists(CONFIG_DIR): os.makedirs(CONFIG_DIR)
    default_settings = {
        "audio_settings": {"sample_rate": 44100, "channels": 1, "recording_gain": 1.0},
        "file_settings": {"word_list_file": "default_list.py", "participant_base_name": "participant", "results_dir": os.path.join(BASE_PATH, "Results")},
        "gtts_settings": {"default_lang": "en-us", "auto_detect": True}, "theme": "Modern_light_tab.qss"
    }
    if not os.path.exists(SETTINGS_FILE): open(SETTINGS_FILE, 'w', encoding='utf-8').write(json.dumps(default_settings, indent=4))
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f: config = json.load(f)
        updated = False
        if "audio_settings" not in config: config["audio_settings"] = default_settings["audio_settings"]; updated = True
        else:
            if "sample_rate" not in config["audio_settings"]: config["audio_settings"]["sample_rate"] = default_settings["audio_settings"]["sample_rate"]; updated = True
            if "channels" not in config["audio_settings"]: config["audio_settings"]["channels"] = default_settings["audio_settings"]["channels"]; updated = True
        if "file_settings" not in config: config["file_settings"] = default_settings["file_settings"]; updated = True
        if "gtts_settings" not in config: config["gtts_settings"] = default_settings["gtts_settings"]; updated = True
        if "theme" not in config: config["theme"] = default_settings["theme"]; updated = True
        if updated: open(SETTINGS_FILE, 'w', encoding='utf-8').write(json.dumps(config, indent=4))
        return config
    except: return default_settings

def detect_language(text):
    if not text: return None
    ranges = {'han': (0x4e00, 0x9fff),'kana': (0x3040, 0x30ff),'hangul': (0xac00, 0xd7a3),'cyrillic': (0x0400, 0x04ff)}
    counts = {'han': 0,'kana': 0,'hangul': 0,'cyrillic': 0,'latin': 0,'other': 0}
    for char in text:
        code = ord(char)
        if ranges['han'][0] <= code <= ranges['han'][1]: counts['han'] += 1
        elif ranges['kana'][0] <= code <= ranges['kana'][1]: counts['kana'] += 1
        elif ranges['hangul'][0] <= code <= ranges['hangul'][1]: counts['hangul'] += 1
        elif ranges['cyrillic'][0] <= code <= ranges['cyrillic'][1]: counts['cyrillic'] += 1
        elif 'a' <= char.lower() <= 'z' or '0' <= char <= '9': counts['latin'] += 1
        else: counts['other'] += 1
    if counts['hangul'] > 0: return 'ko'
    if counts['kana'] > 0: return 'ja'
    if counts['cyrillic'] > 0: return 'ru'
    if counts['han'] > 0: return 'zh-cn'
    return None

class Worker(QObject):
    finished = pyqtSignal(object); progress = pyqtSignal(int, str); error = pyqtSignal(str)
    def __init__(self, task, *args, **kwargs): super().__init__(); self.task=task; self.args=args; self.kwargs=kwargs
    def run(self):
        res = None;
        try: res = self.task(self, *self.args, **self.kwargs)
        except Exception as e: self.error.emit(f"后台任务失败: {e}")
        finally: self.finished.emit(res)

class ToggleSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 30)
        self.setCursor(Qt.PointingHandCursor)
        self._bg_color = "#E0E0E0" 
        self._circle_color = QColor("white")
        self._active_color = QColor("#8F4C33") 

    def set_colors(self, bg_color, active_color):
        self._bg_color = bg_color
        self._active_color = QColor(active_color)
        self.update()

    def mousePressEvent(self, event): self.setChecked(not self.isChecked()); return super().mousePressEvent(event)
    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
        rect = p.window();
        if self.isChecked(): p.setBrush(self._active_color)
        else: p.setBrush(QColor(self._bg_color))
        p.drawRoundedRect(0, 0, rect.width(), rect.height(), 15, 15); p.setBrush(self._circle_color); margin = 3
        circle_diameter = rect.height() - 2 * margin
        if self.isChecked(): p.drawEllipse(rect.width() - circle_diameter - margin, margin, circle_diameter, circle_diameter)
        else: p.drawEllipse(margin, margin, circle_diameter, circle_diameter)

# ========== 主窗口和页面类 ==========
# ... (MainWindow, AccentCollectionPage, VoicebankRecorderPage, ConverterPage, SettingsPage 类的定义保持不变) ...
# 请确保 MainWindow 的 __init__ 接受 splash 参数，并在其内部通过 self.splash.progressBar.setValue() 更新进度
# 例如，在 MainWindow 的 __init__ 中：
# if self.splash and hasattr(self.splash, 'progressBar'): self.splash.progressBar.setValue(X)

# 确保所有页面类定义都在这里，在主执行块之前

# ==================== Canary.py: 替换 MainWindow 类 ====================
class MainWindow(QMainWindow):
    def __init__(self, splash_ref=None):
        super().__init__()
        self.splash_ref = splash_ref

        if self.splash_ref and hasattr(self.splash_ref, 'progressBar'):
            self.splash_ref.showMessage("初始化主窗口... (35%)", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            self.splash_ref.progressBar.setValue(35)
            app.processEvents()

        self.setWindowTitle("PhonAcq Assistant - 音韵习得实验助手")
        self.setGeometry(100, 100, 1200, 850)
        icon_path = os.path.join(BASE_PATH, "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.config = main_config

        self.main_tabs = QTabWidget()
        self.main_tabs.setObjectName("MainTabWidget")
        self.setCentralWidget(self.main_tabs)

        if self.splash_ref and hasattr(self.splash_ref, 'progressBar'):
            self.splash_ref.showMessage("创建核心页面... (50%)", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            self.splash_ref.progressBar.setValue(50)
            app.processEvents()

        # 1. 实例化所有功能页面
        self.accent_collection_page = AccentCollectionPage(self)
        self.voicebank_recorder_page = VoicebankRecorderPage(self)
        
        self.audio_manager_page = self.create_module_or_placeholder('audio_manager_module', '数据管理器', 
            lambda m: m.create_page(self, self.config, BASE_PATH, self.config['file_settings'].get("results_dir"), AUDIO_RECORD_DIR))
            
        self.wordlist_editor_page = self.create_module_or_placeholder('wordlist_editor_module', '词表编辑器',
            lambda m: m.create_page(self, WORD_LIST_DIR))
        
        self.converter_page = self.create_module_or_placeholder('excel_converter_module', 'Excel 转换器',
            lambda m: ConverterPage(self))
        
        self.help_page = self.create_module_or_placeholder('help_module', '帮助文档',
            lambda m: m.create_page(self))
            
        DIALECT_VISUAL_WORDLIST_DIR = os.path.join(BASE_PATH, "dialect_visual_wordlists")
        if not os.path.exists(DIALECT_VISUAL_WORDLIST_DIR):
            os.makedirs(DIALECT_VISUAL_WORDLIST_DIR); print(f"已创建方言图文词表目录: {DIALECT_VISUAL_WORDLIST_DIR}")
            
        self.dialect_visual_page = self.create_module_or_placeholder(
            'dialect_visual_collector_module', '方言图文采集',
            lambda m, ts_cls, w_cls, l_cls: m.create_page(self, self.config, BASE_PATH, DIALECT_VISUAL_WORDLIST_DIR, AUDIO_RECORD_DIR, ts_cls, w_cls, l_cls))
        
        self.dialect_visual_editor_page = self.create_module_or_placeholder(
            'dialect_visual_editor_module', '图文词表编辑器',
            lambda m: m.create_page(self, DIALECT_VISUAL_WORDLIST_DIR))
            
        # ===== 新增/NEW: 实例化拼音转IPA页面 =====
        self.pinyin_to_ipa_page = self.create_module_or_placeholder(
            'pinyin_to_ipa_module',
            '拼音转IPA',
            # ===== 修正/FIX: lambda 函数现在接收两个参数 m 和 ts_cls =====
            lambda m, ts_cls: m.create_page(self, ts_cls)
        )
            
        self.settings_page = SettingsPage(self)

        if self.splash_ref and hasattr(self.splash_ref, 'progressBar'):
            self.splash_ref.showMessage("构建用户界面... (75%)", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            self.splash_ref.progressBar.setValue(75)
            app.processEvents()

        # 2. 创建二级标签页并装载功能页面
        collection_tabs = QTabWidget(); collection_tabs.setObjectName("SubTabWidget")
        collection_tabs.addTab(self.accent_collection_page, "口音采集会话")
        collection_tabs.addTab(self.voicebank_recorder_page, "语音包录制")
        
        dialect_study_tabs = QTabWidget(); dialect_study_tabs.setObjectName("SubTabWidget")
        dialect_study_tabs.addTab(self.dialect_visual_page, "图文采集")
        dialect_study_tabs.addTab(self.dialect_visual_editor_page, "图文词表编辑")
        
        corpus_tabs = QTabWidget(); corpus_tabs.setObjectName("SubTabWidget")
        corpus_tabs.addTab(self.wordlist_editor_page, "词表编辑器")
        corpus_tabs.addTab(self.converter_page, "Excel 转换器")
        corpus_tabs.addTab(self.audio_manager_page, "数据管理器")
        
        # ===== 新增/NEW: 实用工具的二级标签页 =====
        utilities_tabs = QTabWidget()
        utilities_tabs.setObjectName("SubTabWidget")
        utilities_tabs.addTab(self.pinyin_to_ipa_page, "拼音转IPA")

        settings_and_help_tabs = QTabWidget(); settings_and_help_tabs.setObjectName("SubTabWidget")
        settings_and_help_tabs.addTab(self.settings_page, "程序设置")
        settings_and_help_tabs.addTab(self.help_page, "帮助文档")
        
        # 3. 将二级标签页组作为一级标签页添加到主框架中
        self.main_tabs.addTab(collection_tabs, "数据采集")
        self.main_tabs.addTab(dialect_study_tabs, "方言研究") 
        self.main_tabs.addTab(corpus_tabs, "语料管理")
        self.main_tabs.addTab(utilities_tabs, "实用工具") # <--- 新增
        self.main_tabs.addTab(settings_and_help_tabs, "系统与帮助")

        # 4. 连接信号
        self.main_tabs.currentChanged.connect(self.on_main_tab_changed)
        collection_tabs.currentChanged.connect(lambda index: self.on_sub_tab_changed("collection", index))
        corpus_tabs.currentChanged.connect(lambda index: self.on_sub_tab_changed("corpus", index))
        dialect_study_tabs.currentChanged.connect(lambda index: self.on_sub_tab_changed("dialect_study", index))
        utilities_tabs.currentChanged.connect(lambda index: self.on_sub_tab_changed("utilities", index)) # <--- 连接新信号
        settings_and_help_tabs.currentChanged.connect(lambda index: self.on_sub_tab_changed("system_help", index))

        if self.splash_ref and hasattr(self.splash_ref, 'progressBar'):
            self.splash_ref.showMessage("应用主题... (95%)", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            self.splash_ref.progressBar.setValue(95)
            app.processEvents()
        self.apply_theme()
        
        if self.splash_ref and hasattr(self.splash_ref, 'progressBar'):
            self.splash_ref.showMessage("准备完成! (100%)", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            self.splash_ref.progressBar.setValue(100)
            app.processEvents()
        
        self.on_main_tab_changed(0)

    def create_module_or_placeholder(self, module_key, name, page_factory):
        if module_key in MODULES:
            try:
                module_instance = MODULES[module_key]['module']
                # 根据模块名决定是否传递额外参数
                if module_key == 'dialect_visual_collector_module':
                    return page_factory(module_instance, ToggleSwitch, Worker, Logger)
                elif module_key == 'pinyin_to_ipa_module': # 为新模块传递 ToggleSwitch
                    return page_factory(module_instance, ToggleSwitch)
                else:
                    return page_factory(module_instance)
            except Exception as e:
                 print(f"创建模块 '{name}' 页面时出错: {e}")
        
        page = QWidget(); layout = QVBoxLayout(page); layout.setAlignment(Qt.AlignCenter)
        label = QLabel(f"模块 '{name}' 未加载或创建失败。\n请检查 'modules' 文件夹并重启。"); label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label); return page

    def on_main_tab_changed(self, index):
        current_main_widget = self.main_tabs.widget(index)
        if not current_main_widget: return

        # 更新索引判断以匹配新的标签页顺序
        if index == 0: self.on_sub_tab_changed("collection", current_main_widget.currentIndex())
        elif index == 1: self.on_sub_tab_changed("dialect_study", current_main_widget.currentIndex())
        elif index == 2: self.on_sub_tab_changed("corpus", current_main_widget.currentIndex())
        elif index == 3: self.on_sub_tab_changed("utilities", current_main_widget.currentIndex())
        elif index == 4: # 系统与帮助 (现在是索引4)
            self.on_sub_tab_changed("system_help", current_main_widget.currentIndex())

    def on_sub_tab_changed(self, group_name, index):
        if group_name == "collection":
            if index == 0: self.accent_collection_page.load_config_and_prepare()
            elif index == 1: self.voicebank_recorder_page.load_config_and_prepare()
        elif group_name == "dialect_study":
            if index == 0 and 'dialect_visual_collector_module' in MODULES: self.dialect_visual_page.load_config_and_prepare()
            elif index == 1 and 'dialect_visual_editor_module' in MODULES: self.dialect_visual_editor_page.refresh_file_list()
        elif group_name == "corpus":
            if index == 0 and 'wordlist_editor_module' in MODULES: self.wordlist_editor_page.refresh_file_list()
            elif index == 1 and 'excel_converter_module' in MODULES: self.converter_page.update_module_status()
            elif index == 2 and 'audio_manager_module' in MODULES: self.audio_manager_page.load_and_refresh()
        elif group_name == "utilities":
            # 拼音转IPA页面是静态的，目前无需加载
            pass
        elif group_name == "system_help":
            if index == 0: # 程序设置
                self.settings_page.load_settings()
            elif index == 1: # 帮助文档
                 if hasattr(self, 'help_page') and hasattr(self.help_page, 'update_help_content'):
                    self.help_page.update_help_content()

    def apply_theme(self):
        theme_file = self.config.get("theme", "Modern_light_tab.qss")
        theme_path = os.path.join(THEMES_DIR, theme_file)
        if not os.path.exists(THEMES_DIR): os.makedirs(THEMES_DIR)
        if os.path.exists(theme_path):
            with open(theme_path, "r", encoding="utf-8") as f: self.setStyleSheet(f.read())
        else:
            print(f"警告: 找不到主题文件 {theme_path}")
            self.setStyleSheet("")
        if hasattr(self, 'help_page') and hasattr(self.help_page, 'update_help_content'):
            QTimer.singleShot(0, self.help_page.update_help_content)
# # ==================== Canary.py: 替换 AccentCollectionPage ====================
class AccentCollectionPage(QWidget):
    LINE_WIDTH_THRESHOLD = 90

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        # ===== 新增/NEW: 会话状态管理 =====
        self.session_active = False
        
        self.is_recording = False
        self.current_word_list = []
        self.current_word_index = -1
        self.audio_queue = queue.Queue()
        self.recording_thread = None
        self.stop_event = threading.Event()
        
        main_layout = QHBoxLayout(self)
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()

        # 左侧：列表和状态
        self.list_widget = QListWidget()
        self.status_label = QLabel("状态：准备就绪")
        self.progress_bar = QProgressBar(); self.progress_bar.setVisible(False)
        left_layout.addWidget(QLabel("测试词语列表:"))
        left_layout.addWidget(self.list_widget)
        left_layout.addWidget(self.status_label)
        left_layout.addWidget(self.progress_bar)

        # ===== 修改/MODIFIED: 重构右侧控制面板 =====
        right_panel_group = QGroupBox("控制面板")
        self.right_layout_container = QVBoxLayout(right_panel_group) # 使用一个容器布局

        # 会话前控件
        self.pre_session_widget = QWidget()
        pre_session_layout = QFormLayout(self.pre_session_widget)
        pre_session_layout.setContentsMargins(11, 0, 11, 0)
        self.word_list_combo = QComboBox()
        self.participant_input = QLineEdit()
        self.start_session_btn = QPushButton("开始新会话")
        self.start_session_btn.setObjectName("AccentButton")
        pre_session_layout.addRow("选择单词表:", self.word_list_combo)
        pre_session_layout.addRow("被试者名称:", self.participant_input)
        pre_session_layout.addRow(self.start_session_btn)

        # 会话中控件
        self.in_session_widget = QWidget()
        in_session_layout = QVBoxLayout(self.in_session_widget)
        mode_group = QGroupBox("会话模式")
        mode_layout = QFormLayout(mode_group)
        self.random_switch = ToggleSwitch(); self.full_list_switch = ToggleSwitch()
        random_layout = QHBoxLayout(); random_layout.addWidget(QLabel("顺序")); random_layout.addWidget(self.random_switch); random_layout.addWidget(QLabel("随机"))
        full_list_layout = QHBoxLayout(); full_list_layout.addWidget(QLabel("部分")); full_list_layout.addWidget(self.full_list_switch); full_list_layout.addWidget(QLabel("完整"))
        mode_layout.addRow(random_layout); mode_layout.addRow(full_list_layout)
        self.end_session_btn = QPushButton("结束当前会话")
        self.end_session_btn.setObjectName("ActionButton_Delete")
        in_session_layout.addWidget(mode_group)
        in_session_layout.addWidget(self.end_session_btn)
        
        self.right_layout_container.addWidget(self.pre_session_widget)
        self.right_layout_container.addWidget(self.in_session_widget)

        self.recording_status_panel = QGroupBox("录音状态")
        status_panel_layout = QVBoxLayout(self.recording_status_panel)
        self.recording_indicator = QLabel("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_label = QLabel("当前音量:")
        self.volume_meter = QProgressBar(); self.volume_meter.setRange(0, 100); self.volume_meter.setValue(0); self.volume_meter.setTextVisible(False)
        status_panel_layout.addWidget(self.recording_indicator); status_panel_layout.addWidget(self.volume_label); status_panel_layout.addWidget(self.volume_meter)
        self.update_timer = QTimer(); self.update_timer.timeout.connect(self.update_volume_meter)
        
        self.record_btn = QPushButton("开始录制下一个"); self.replay_btn = QPushButton("重听当前音频")
        
        right_layout.addWidget(right_panel_group)
        right_layout.addStretch()
        right_layout.addWidget(self.recording_status_panel)
        right_layout.addWidget(self.record_btn)
        right_layout.addWidget(self.replay_btn)
        
        main_layout.addLayout(left_layout, 2)
        main_layout.addLayout(right_layout, 1)

        # 连接信号
        self.start_session_btn.clicked.connect(self.start_session)
        self.end_session_btn.clicked.connect(self.end_session)
        self.record_btn.clicked.connect(self.handle_record_button)
        self.replay_btn.clicked.connect(self.replay_audio)
        self.list_widget.currentRowChanged.connect(self.on_list_item_changed)
        self.list_widget.itemDoubleClicked.connect(self.replay_audio)
        self.random_switch.stateChanged.connect(self.on_session_mode_changed)
        self.full_list_switch.stateChanged.connect(self.on_session_mode_changed)

        # 初始化UI状态
        self.reset_ui()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if self.list_widget.hasFocus() and self.replay_btn.isEnabled():
                self.replay_audio()
                event.accept()
        else:
            super().keyPressEvent(event)

    def _get_weighted_length(self, text):
        length = 0
        for char in text:
            if '\u4e00' <= char <= '\u9fff' or \
               '\u3040' <= char <= '\u30ff' or \
               '\uff00' <= char <= '\uffef':
                length += 2
            else:
                length += 1
        return length

    def _format_list_item_text(self, word, ipa):
        ipa_display = f"({ipa})" if ipa else ""
        total_weighted_length = self._get_weighted_length(word) + self._get_weighted_length(ipa_display)
        if total_weighted_length > self.LINE_WIDTH_THRESHOLD and ipa_display:
            return f"{word}\n{ipa_display}"
        else:
            return f"{word} {ipa_display}".strip()

    def update_volume_meter(self):
        if not self.audio_queue.empty():
            data_chunk = self.audio_queue.get()
            volume_norm = np.linalg.norm(data_chunk) * 10
            self.volume_meter.setValue(int(volume_norm))
        else:
            current_value = self.volume_meter.value()
            self.volume_meter.setValue(int(current_value * 0.8))
            
    def start_recording_logic(self):
        self.recording_indicator.setText("● 正在录音"); self.recording_indicator.setStyleSheet("color: red;")
        self.update_timer.start(50)
        self.stop_event.clear(); self.audio_queue=queue.Queue()
        self.recording_thread=threading.Thread(target=self.recorder_thread_task,daemon=True); self.recording_thread.start()

    def stop_recording_logic(self):
        self.update_timer.stop()
        self.recording_indicator.setText("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_meter.setValue(0)
        self.stop_event.set()
        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=0.5)
        self.run_task_in_thread(self.save_recording_task)
    
    # ===== 修改/MODIFIED: 改造 load_config_and_prepare =====
    def load_config_and_prepare(self):
        self.config = self.parent_window.config
        if not self.session_active:
            self.populate_word_lists()
            self.participant_input.setText(self.config['file_settings'].get('participant_base_name', 'participant'))

    def populate_word_lists(self):
        self.word_list_combo.clear()
        if os.path.exists(WORD_LIST_DIR):
            self.word_list_combo.addItems([f for f in os.listdir(WORD_LIST_DIR) if f.endswith('.py')])
        # 尝试设置默认单词表
        default_list = self.config['file_settings'].get('word_list_file', '')
        if default_list:
            index = self.word_list_combo.findText(default_list, Qt.MatchFixedString)
            if index >= 0:
                self.word_list_combo.setCurrentIndex(index)

    def on_session_mode_changed(self):
        if not self.session_active: return
        self.prepare_word_list()
        if self.current_word_list: self.record_btn.setText(f"开始录制 (1/{len(self.current_word_list)})")
        
    def reset_ui(self):
        """重置UI到初始状态，但不清除数据"""
        self.pre_session_widget.show()
        self.in_session_widget.hide()
        
        self.record_btn.setEnabled(False)
        self.replay_btn.setEnabled(False)
        self.record_btn.setText("开始录制下一个")
        self.list_widget.clear()
        self.status_label.setText("状态：准备就绪")
        self.progress_bar.setVisible(False)
        
    def end_session(self):
        """结束当前会话，清理数据并重置UI"""
        reply = QMessageBox.question(self, '结束会话', '您确定要结束当前的口音采集会话吗？',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.session_active = False
            self.current_word_list = []
            self.current_word_index = -1
            self.reset_ui()
            # 重新加载配置和单词表
            self.load_config_and_prepare()

    def start_session(self):
        # 1. 数据验证
        wordlist_file = self.word_list_combo.currentText()
        if not wordlist_file:
            QMessageBox.warning(self, "选择错误", "请先选择一个单词表。")
            return
            
        base_name = self.participant_input.text().strip()
        if not base_name:
            QMessageBox.warning(self, "输入错误", "请输入被试者名称。")
            return

        # 2. 创建结果文件夹和日志
        results_dir = self.config['file_settings'].get("results_dir", os.path.join(BASE_PATH, "Results"))
        if not os.path.exists(results_dir): os.makedirs(results_dir)
        i = 1; folder_name = base_name
        while os.path.exists(os.path.join(results_dir, folder_name)): i += 1; folder_name = f"{base_name}_{i}"
        self.recordings_folder = os.path.join(results_dir, folder_name); os.makedirs(self.recordings_folder)
        self.logger = Logger(os.path.join(self.recordings_folder, "log.txt"))
        
        # 3. 加载单词表并生成TTS
        try:
            self.current_wordlist_name = wordlist_file
            word_groups = self.load_word_list_logic()
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.run_task_in_thread(self.check_and_generate_audio_logic, word_groups)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载单词表失败: {e}")
        
    def update_tts_progress(self, percentage, text):
        self.progress_bar.setValue(percentage)
        self.status_label.setText(f"状态：{text}")
        
    def on_tts_finished(self, error_msg):
        if error_msg:
            QMessageBox.warning(self, "音频检查完成", error_msg)
            # TTS失败，重置UI
            self.reset_ui()
            return
            
        self.progress_bar.setVisible(False)
        self.status_label.setText("状态：音频准备就绪。")
        
        # 切换UI到会话中状态
        self.pre_session_widget.hide()
        self.in_session_widget.show()
        self.record_btn.setEnabled(True)
        self.session_active = True
        
        # 准备单词列表
        self.prepare_word_list()
        if self.current_word_list:
            self.record_btn.setText("开始录制 (1/{})".format(len(self.current_word_list)))
        
    def prepare_word_list(self):
        word_groups = self.load_word_list_logic()
        is_random = self.random_switch.isChecked()
        is_full = self.full_list_switch.isChecked()
        temp_list = []
        if not is_full:
            for group in word_groups:
                if group: temp_list.append(random.choice(list(group.items())))
        else:
            for group in word_groups: temp_list.extend(group.items())
        if is_random: random.shuffle(temp_list)
        
        self.current_word_list = []
        for word, value in temp_list:
            ipa = value[0] if isinstance(value, tuple) else str(value)
            self.current_word_list.append({'word': word, 'ipa': ipa, 'recorded': False})
        
        self.list_widget.clear()
        for item_data in self.current_word_list:
            display_text = self._format_list_item_text(item_data['word'], item_data['ipa'])
            self.list_widget.addItem(QListWidgetItem(display_text))
            
        if self.current_word_list: self.list_widget.setCurrentRow(0)
        
    def handle_record_button(self):
        if not self.is_recording:
            self.current_word_index=self.list_widget.currentRow()
            if self.current_word_index==-1:return
            self.is_recording=True;self.record_btn.setText("停止录制");self.list_widget.setEnabled(False);self.replay_btn.setEnabled(True)
            self.random_switch.setEnabled(False);self.full_list_switch.setEnabled(False)
            self.status_label.setText(f"状态：正在录制 '{self.current_word_list[self.current_word_index]['word']}'...")
            self.play_audio_logic();self.start_recording_logic()
        else:
            self.stop_recording_logic();self.is_recording=False;self.record_btn.setText("准备就绪");self.record_btn.setEnabled(False)
            self.status_label.setText("状态：正在保存录音...")
            
    def on_recording_saved(self):
        self.status_label.setText("状态：录音已保存。");self.list_widget.setEnabled(True);self.replay_btn.setEnabled(True)
        self.random_switch.setEnabled(True);self.full_list_switch.setEnabled(True)
        item_data=self.current_word_list[self.current_word_index];item_data['recorded']=True
        
        list_item=self.list_widget.item(self.current_word_index)
        display_text = self._format_list_item_text(item_data['word'], item_data['ipa'])
        list_item.setText(display_text)
        
        list_item.setIcon(self.style().standardIcon(QStyle.SP_DialogOkButton))
        all_recorded=all(item['recorded'] for item in self.current_word_list)
        if all_recorded:self.handle_session_completion();return
        next_index=-1;indices=list(range(len(self.current_word_list)))
        for i in indices[self.current_word_index+1:]+indices[:self.current_word_index+1]:
            if not self.current_word_list[i]['recorded']:next_index=i;break
        if next_index!=-1:
            self.list_widget.setCurrentRow(next_index);self.record_btn.setEnabled(True)
            self.record_btn.setText("开始录制 ({}/{})".format(sum(1 for i in self.current_word_list if i['recorded'])+1,len(self.current_word_list)))
        else:self.handle_session_completion()
        
    def handle_session_completion(self):
        unrecorded_count=sum(1 for item in self.current_word_list if not item['recorded'])
        if self.current_word_list:
            QMessageBox.information(self,"会话结束",f"本次会话已结束。\n总共录制了 {len(self.current_word_list)-unrecorded_count} 个词语。")
        self.end_session()
        
    def on_list_item_changed(self,row):
        if row!=-1 and not self.is_recording:self.replay_btn.setEnabled(True)
        
    def replay_audio(self, item=None):
        self.play_audio_logic()
    
    def play_audio_logic(self,index=None):
        if not self.session_active: return
        if index is None: index = self.list_widget.currentRow()
        if index == -1: return
        
        word = self.current_word_list[index]['word']
        wordlist_name, _ = os.path.splitext(self.current_wordlist_name)
        
        record_path = os.path.join(AUDIO_RECORD_DIR, wordlist_name, f"{word}.mp3")
        tts_path = os.path.join(AUDIO_TTS_DIR, wordlist_name, f"{word}.mp3")
        final_path = record_path if os.path.exists(record_path) else tts_path
        
        if os.path.exists(final_path):
            threading.Thread(target=self.play_sound_task, args=(final_path,), daemon=True).start()
        else:
            self.status_label.setText(f"状态：找不到 '{word}' 的提示音！")
        
    def play_sound_task(self,path):
        try:data,sr=sf.read(path,dtype='float32');sd.play(data,sr);sd.wait()
        except Exception as e:self.logger.log(f"ERROR playing sound: {e}")
        
    def recorder_thread_task(self):
        try:
            with sd.InputStream(samplerate=self.config['audio_settings']['sample_rate'],channels=self.config['audio_settings']['channels'],callback=lambda i,f,t,s:self.audio_queue.put(i.copy())):self.stop_event.wait()
        except Exception as e:print(f"录音错误: {e}")
        
    def save_recording_task(self,worker):
        if self.audio_queue.empty():return
        data=[self.audio_queue.get() for _ in range(self.audio_queue.qsize())];rec=np.concatenate(data,axis=0)
        gain=self.config['audio_settings'].get('recording_gain',1.0)
        if gain!=1.0:rec=np.clip(rec*gain,-1.0,1.0)
        word=self.current_word_list[self.current_word_index]['word']
        filepath=os.path.join(self.recordings_folder,f"{word}.wav")
        sf.write(filepath,rec,self.config['audio_settings']['sample_rate']);self.logger.log(f"Recording saved: {filepath}")
        
    def run_task_in_thread(self,task_func,*args):
        self.thread=QThread();self.worker=Worker(task_func,*args);self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run);self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater);self.thread.finished.connect(self.thread.deleteLater)
        self.worker.progress.connect(self.update_tts_progress)
        self.worker.error.connect(lambda msg:QMessageBox.critical(self,"后台错误",msg))
        if task_func==self.check_and_generate_audio_logic:self.worker.finished.connect(self.on_tts_finished)
        elif task_func==self.save_recording_task:self.worker.finished.connect(self.on_recording_saved)
        self.thread.start()
        
    def load_word_list_logic(self):
        filename = self.current_wordlist_name # 使用会话开始时保存的文件名
        filepath = os.path.join(WORD_LIST_DIR, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"找不到单词表文件: {filename}")
        spec = importlib.util.spec_from_file_location("word_list_module", filepath)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.WORD_GROUPS
        
    def check_and_generate_audio_logic(self,worker,word_groups):
        wordlist_name, _ = os.path.splitext(self.current_wordlist_name)
        
        gtts_settings=self.config.get("gtts_settings",{});gtts_default_lang=gtts_settings.get("default_lang","en-us");gtts_auto_detect=gtts_settings.get("auto_detect",True)
        all_words_with_lang={};
        for group in word_groups:
            for word,value in group.items():
                lang=value[1] if isinstance(value,tuple) and len(value)==2 and value[1] else None
                if not lang and gtts_auto_detect:lang=detect_language(word)
                if not lang:lang=gtts_default_lang
                all_words_with_lang[word]=lang
        
        record_audio_folder = os.path.join(AUDIO_RECORD_DIR, wordlist_name)
        tts_audio_folder = os.path.join(AUDIO_TTS_DIR, wordlist_name)
        if not os.path.exists(tts_audio_folder):os.makedirs(tts_audio_folder)
        
        missing = [
            w for w in all_words_with_lang 
            if not os.path.exists(os.path.join(record_audio_folder, f"{w}.mp3")) 
            and not os.path.exists(os.path.join(tts_audio_folder, f"{w}.mp3"))
        ]

        if not missing: return None
        
        total_missing=len(missing)
        for i,word in enumerate(missing):
            percentage=int((i+1)/total_missing*100)
            progress_text=f"正在生成TTS ({i+1}/{total_missing}): {word}...";worker.progress.emit(percentage,progress_text)
            filepath=os.path.join(tts_audio_folder, f"{word}.mp3")
            try:
                gTTS(text=word,lang=all_words_with_lang[word],slow=False).save(filepath)
                time.sleep(0.5)
            except Exception as e:
                return f"为'{word}'生成TTS音频失败: {e}\n\n请检查您的网络连接或gTTS服务是否可用。"
        return None

# ==================== Canary.py: 替换 VoicebankRecorderPage ====================
class VoicebankRecorderPage(QWidget):
    LINE_WIDTH_THRESHOLD = 90

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.session_active = False
        
        self.is_recording = False
        self.current_word_list = []
        self.current_word_index = -1
        self.audio_queue = queue.Queue()
        self.recording_thread = None
        self.stop_event = threading.Event()

        main_layout = QHBoxLayout(self)
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()

        self.list_widget = QListWidget()
        self.status_label = QLabel("状态：请选择一个单词表开始录制。")
        left_layout.addWidget(QLabel("待录制词语列表:"))
        left_layout.addWidget(self.list_widget)
        left_layout.addWidget(self.status_label)
        
        control_group = QGroupBox("控制面板")
        self.control_layout = QFormLayout(control_group) 
        
        self.word_list_combo = QComboBox()
        self.start_btn = QPushButton("加载词表并开始")
        self.start_btn.setObjectName("AccentButton")
        self.end_session_btn = QPushButton("结束当前会话")
        self.end_session_btn.setObjectName("ActionButton_Delete")
        # 初始时隐藏结束按钮
        self.end_session_btn.hide()
        
        self.control_layout.addRow("选择单词表:", self.word_list_combo)
        self.control_layout.addRow(self.start_btn)
        
        self.recording_status_panel = QGroupBox("录音状态")
        status_panel_layout = QVBoxLayout(self.recording_status_panel)
        self.recording_indicator = QLabel("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_label = QLabel("当前音量:")
        self.volume_meter = QProgressBar(); self.volume_meter.setRange(0, 100); self.volume_meter.setValue(0); self.volume_meter.setTextVisible(False)
        status_panel_layout.addWidget(self.recording_indicator); status_panel_layout.addWidget(self.volume_label); status_panel_layout.addWidget(self.volume_meter)
        self.update_timer = QTimer(); self.update_timer.timeout.connect(self.update_volume_meter)
        
        self.record_btn = QPushButton("按住录音"); self.record_btn.setEnabled(False)
        
        right_layout.addWidget(control_group); right_layout.addStretch()
        right_layout.addWidget(self.recording_status_panel)
        right_layout.addWidget(self.record_btn)
        
        main_layout.addLayout(left_layout, 2)
        main_layout.addLayout(right_layout, 1)

        self.start_btn.clicked.connect(self.start_session)
        self.end_session_btn.clicked.connect(self.end_session)
        self.record_btn.pressed.connect(self.start_recording)
        self.record_btn.released.connect(self.stop_recording)
        
        self.setFocusPolicy(Qt.StrongFocus)

    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.record_btn.isEnabled() and not self.is_recording:
                self.is_recording = True
                self.start_recording()
                event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.is_recording:
                self.is_recording = False
                self.stop_recording()
                event.accept()
        else:
            super().keyReleaseEvent(event)
    
    def _get_weighted_length(self, text):
        length = 0
        for char in text:
            if '\u4e00' <= char <= '\u9fff' or \
               '\u3040' <= char <= '\u30ff' or \
               '\uff00' <= char <= '\uffef':
                length += 2
            else:
                length += 1
        return length

    def _format_list_item_text(self, word, ipa):
        ipa_display = f"({ipa})" if ipa else ""
        total_weighted_length = self._get_weighted_length(word) + self._get_weighted_length(ipa_display)
        if total_weighted_length > self.LINE_WIDTH_THRESHOLD and ipa_display:
            return f"{word}\n{ipa_display}"
        else:
            return f"{word} {ipa_display}".strip()

    def update_volume_meter(self):
        if not self.audio_queue.empty():
            data_chunk = self.audio_queue.get()
            volume_norm = np.linalg.norm(data_chunk) * 10
            self.volume_meter.setValue(int(volume_norm))
        else:
            current_value = self.volume_meter.value()
            self.volume_meter.setValue(int(current_value * 0.8))

    def start_recording(self):
        self.current_word_index = self.list_widget.currentRow()
        if self.current_word_index == -1: 
            self.log("请先在列表中选择一个词！")
            self.is_recording = False
            return

        self.recording_indicator.setText("● 正在录音"); self.recording_indicator.setStyleSheet("color: red;")
        self.update_timer.start(50)
            
        self.record_btn.setText("正在录音..."); self.record_btn.setStyleSheet("background-color: #f44336;")
        self.log(f"录制 '{self.current_word_list[self.current_word_index]['word']}'")
        self.stop_event.clear(); self.audio_queue = queue.Queue()
        self.recording_thread = threading.Thread(target=self.recorder_thread_task, daemon=True); self.recording_thread.start()

    def stop_recording(self):
        if not self.recording_thread or not self.recording_thread.is_alive(): 
            self.is_recording = False
            return

        self.update_timer.stop()
        self.recording_indicator.setText("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_meter.setValue(0)
            
        self.stop_event.set(); self.record_btn.setText("按住录音"); self.record_btn.setStyleSheet("")
        self.log("正在保存...")
        if self.recording_thread.is_alive():
            self.recording_thread.join(timeout=0.5)
        self.run_task_in_thread(self.save_recording_task)
    
    def log(self, msg): self.status_label.setText(f"状态: {msg}")
    
    def load_config_and_prepare(self):
        self.config = self.parent_window.config
        if not self.session_active:
            self.populate_word_lists()
        
    def populate_word_lists(self):
        self.word_list_combo.clear()
        if os.path.exists(WORD_LIST_DIR): 
            self.word_list_combo.addItems([f for f in os.listdir(WORD_LIST_DIR) if f.endswith('.py')])
        
    # ===== 修改/MODIFIED: 修正 reset_ui 方法 =====
    def reset_ui(self):
        """重置UI到初始状态，但不清除数据。"""
        # 1. 恢复“开始”按钮和下拉框
        self.word_list_combo.show()
        self.start_btn.show()

        # 2. 从布局中移除“结束会话”按钮的整行
        #    这会自动销毁按钮，所以我们不需要再对它进行任何操作
        self.control_layout.removeRow(self.end_session_btn)

        # 3. 清理和禁用其他控件
        self.list_widget.clear()
        self.record_btn.setEnabled(False)
        self.log("请选择一个单词表开始录制。")
    
    def end_session(self):
        """结束当前录制会话，清理数据并重置UI。"""
        reply = QMessageBox.question(self, '结束会话', '您确定要结束当前的语音包录制会话吗？',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.session_active = False
            self.current_word_list = []
            self.current_word_index = -1
            self.reset_ui()

    def start_session(self):
        wordlist_file=self.word_list_combo.currentText()
        if not wordlist_file: QMessageBox.warning(self,"错误","请先选择一个单词表。");return
        wordlist_name,_=os.path.splitext(wordlist_file)
        self.audio_folder=os.path.join(AUDIO_RECORD_DIR,wordlist_name)
        if not os.path.exists(self.audio_folder): os.makedirs(self.audio_folder)
        
        try:
            word_groups=self.load_word_list_logic(wordlist_file)
            self.current_word_list=[]
            for group in word_groups:
                for word,value in group.items():
                    ipa=value[0] if isinstance(value,tuple) else str(value)
                    self.current_word_list.append({'word':word,'ipa':ipa})
            self.current_word_index=0
            
            # ===== 修改/MODIFIED: 更新UI到“会话中”的状态 =====
            self.word_list_combo.hide()
            self.start_btn.hide()
            # 重新创建按钮实例，以防万一
            self.end_session_btn = QPushButton("结束当前会话")
            self.end_session_btn.setObjectName("ActionButton_Delete")
            self.end_session_btn.clicked.connect(self.end_session)
            self.control_layout.addRow(self.end_session_btn)

            self.update_list_widget()
            self.record_btn.setEnabled(True)
            self.log("准备就绪，请选择词语并录音。")
            
            self.session_active = True

        except Exception as e: 
            QMessageBox.critical(self,"错误",f"加载单词表失败: {e}")
            self.session_active = False
        
    def update_list_widget(self):
        current_row = self.list_widget.currentRow()
        if current_row == -1: current_row = 0

        self.list_widget.clear()
        for item_data in self.current_word_list:
            display_text = self._format_list_item_text(item_data['word'], item_data['ipa'])
            item = QListWidgetItem(display_text)
            
            filepath=os.path.join(self.audio_folder,f"{item_data['word']}.mp3")
            if os.path.exists(filepath): item.setIcon(self.style().standardIcon(QStyle.SP_DialogOkButton))
            
            self.list_widget.addItem(item)
            
        if self.current_word_list and current_row < len(self.current_word_list):
             self.list_widget.setCurrentRow(current_row)
             
    def on_recording_saved(self):
        self.log("录音已保存。")
        self.update_list_widget() 
        
        if self.current_word_index + 1 < len(self.current_word_list):
            self.current_word_index += 1
            self.list_widget.setCurrentRow(self.current_word_index)
        else: 
            QMessageBox.information(self,"完成","所有词条已录制完毕！")
            # 录完后自动结束会话
            if self.session_active: self.end_session()
        
    def recorder_thread_task(self):
        try:
            with sd.InputStream(samplerate=self.config['audio_settings']['sample_rate'],channels=self.config['audio_settings']['channels'],
                                callback=lambda i,f,t,s:self.audio_queue.put(i.copy())): self.stop_event.wait()
        except Exception as e:print(f"录音错误: {e}")
        
    def save_recording_task(self,worker):
        if self.audio_queue.empty():return
        data=[self.audio_queue.get() for _ in range(self.audio_queue.qsize())];rec=np.concatenate(data,axis=0)
        gain=self.config['audio_settings'].get('recording_gain',1.0)
        if gain!=1.0: rec=np.clip(rec*gain,-1.0,1.0)
        word=self.current_word_list[self.current_word_index]['word']
        filepath=os.path.join(self.audio_folder,f"{word}.mp3")
        try: sf.write(filepath,rec,self.config['audio_settings']['sample_rate'],format='MP3')
        except Exception as e:
            self.log(f"保存MP3失败: {e}")
            try:
                wav_path=os.path.splitext(filepath)[0]+".wav"
                sf.write(wav_path,rec,self.config['audio_settings']['sample_rate']); self.log(f"已保存为WAV格式: {wav_path}")
            except Exception as e_wav: self.log(f"保存WAV也失败: {e_wav}")
            
    def run_task_in_thread(self,task_func,*args):
        self.thread=QThread();self.worker=Worker(task_func,*args);self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run);self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater);self.thread.finished.connect(self.thread.deleteLater)
        self.worker.error.connect(lambda msg:QMessageBox.critical(self,"后台错误",msg))
        if task_func==self.save_recording_task:self.worker.finished.connect(self.on_recording_saved)
        self.thread.start()
        
    def load_word_list_logic(self,filename):
        filepath=os.path.join(WORD_LIST_DIR,filename)
        if not os.path.exists(filepath):raise FileNotFoundError(f"找不到单词表文件: {filename}")
        spec=importlib.util.spec_from_file_location("word_list_module",filepath);module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module);return module.WORD_GROUPS
# =========================================================================

class ConverterPage(QWidget):
    def __init__(self, parent_window):
        super().__init__(); self.parent_window=parent_window
        main_layout=QHBoxLayout(self); left_layout=QVBoxLayout()
        self.convert_btn=QPushButton("选择Excel文件并转换"); self.convert_btn.setObjectName("AccentButton")
        templates_group=QGroupBox("生成模板"); templates_layout=QVBoxLayout(templates_group)
        template_selection_layout = QHBoxLayout()
        self.template_combo = QComboBox()
        self.generate_template_btn = QPushButton("生成选中模板")
        template_selection_layout.addWidget(self.template_combo, 1); template_selection_layout.addWidget(self.generate_template_btn)
        self.template_description_label = QLabel("请从上方选择一个模板以查看其详细说明。")
        self.template_description_label.setWordWrap(True); self.template_description_label.setAlignment(Qt.AlignTop)
        self.template_description_label.setObjectName("DescriptionLabel")
        templates_layout.addLayout(template_selection_layout); templates_layout.addWidget(self.template_description_label, 1)
        left_layout.addWidget(self.convert_btn); left_layout.addWidget(templates_group, 1); left_layout.addStretch()
        self.log_display=QPlainTextEdit(); self.log_display.setReadOnly(True)
        self.log_display.setPlaceholderText("此处将显示操作日志和结果..."); self.log_display.setObjectName("LogDisplay")
        main_layout.addLayout(left_layout,1); main_layout.addWidget(self.log_display,3)
        self.convert_btn.clicked.connect(self.run_conversion)
        self.generate_template_btn.clicked.connect(self.generate_template)
        self.template_combo.currentIndexChanged.connect(self.update_template_description); self.update_module_status()

    def log(self,message): self.log_display.appendPlainText(f"[{datetime.now():%H:%M:%S}] {message}")
    
    def update_module_status(self):
        is_enabled='excel_converter_module' in MODULES
        self.convert_btn.setEnabled(is_enabled); self.template_combo.setEnabled(is_enabled); self.generate_template_btn.setEnabled(is_enabled)
        if not is_enabled:self.log("警告: Excel转换模块 (excel_converter_module.py) 未加载，相关功能已禁用。")
        else: self.populate_template_combo()

    def populate_template_combo(self):
        self.template_combo.clear()
        if 'excel_converter_module' in MODULES:
            templates = getattr(MODULES['excel_converter_module']['module'], 'templates', {})
            for key, info in templates.items():
                display_name = os.path.splitext(info['filename'])[0][2:]
                self.template_combo.addItem(display_name, key)

    def update_template_description(self, index):
        if index == -1 or 'excel_converter_module' not in MODULES:
            self.template_description_label.setText("请从上方选择一个模板以查看其详细说明。"); return
        template_type = self.template_combo.currentData()
        templates = getattr(MODULES['excel_converter_module']['module'], 'templates', {})
        description = templates.get(template_type, {}).get('description', '无可用描述。')
        self.template_description_label.setText(description)

    def generate_template(self):
        if 'excel_converter_module' not in MODULES: self.log("错误: Excel转换模块缺失。"); return
        template_type = self.template_combo.currentData()
        templates = getattr(MODULES['excel_converter_module']['module'], 'templates', {})
        template_filename = templates.get(template_type, {}).get('filename', f'{template_type}_template.xlsx')
        template_path = os.path.join(WORD_LIST_DIR, template_filename)
        if os.path.exists(template_path):
            reply = QMessageBox.question(self, '文件已存在', f"模板文件 '{template_filename}' 已存在，是否覆盖?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No: self.log("操作取消。"); return
        success,msg=MODULES['excel_converter_module']['module'].generate_template(WORD_LIST_DIR, template_type=template_type)
        self.log(msg)
        
    def run_conversion(self):
        if 'excel_converter_module' not in MODULES: self.log("错误: Excel转换模块缺失。"); return
        
        filepath, _ = QFileDialog.getOpenFileName(self, "选择Excel文件", "", "Excel 文件 (*.xlsx *.xls)")
        if not filepath:
            self.log("操作取消。"); return
            
        self.log(f"正在读取文件: {os.path.basename(filepath)}...")
        
        default_py_name = os.path.splitext(os.path.basename(filepath))[0] + ".py"
        default_save_path = os.path.join(WORD_LIST_DIR, default_py_name)
        
        output_filename, _ = QFileDialog.getSaveFileName(self, "保存为Python文件", default_save_path, "Python 文件 (*.py)")
        
        if not output_filename:
            self.log("操作取消。"); return
            
        success, msg = MODULES['excel_converter_module']['module'].convert_file(filepath, output_filename)
        self.log(msg)
        if not success:
            QMessageBox.critical(self, "错误", msg)

# ==================== Canary.py: 替换 SettingsPage 类 ====================
class SettingsPage(QWidget):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        
        # ===== 修改/MODIFIED: 在 __init__ 中直接构建完整的UI =====
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        form_layout.setSpacing(20)

        # --- 外观设置 ---
        appearance_group = QGroupBox("外观设置")
        appearance_layout = QFormLayout(appearance_group)
        self.theme_combo = QComboBox()
        appearance_layout.addRow("主题皮肤:", self.theme_combo)
        
        # --- 文件与路径 ---
        file_group = QGroupBox("文件与路径")
        file_layout = QFormLayout(file_group)
        self.results_dir_input = QLineEdit()
        self.results_dir_btn = QPushButton("...")
        results_dir_layout = QHBoxLayout()
        results_dir_layout.addWidget(self.results_dir_input); results_dir_layout.addWidget(self.results_dir_btn)
        self.word_list_combo = QComboBox()
        self.participant_name_input = QLineEdit()
        file_layout.addRow("结果文件夹:", results_dir_layout)
        file_layout.addRow("默认单词表 (口音采集):", self.word_list_combo)
        file_layout.addRow("默认被试者名称:", self.participant_name_input)
        
        # --- gTTS (在线) 设置 ---
        gtts_group = QGroupBox("gTTS (在线) 设置")
        gtts_layout = QFormLayout(gtts_group)
        self.gtts_lang_combo = QComboBox()
        self.gtts_lang_combo.addItems(['en-us','en-uk','en-au','en-in','zh-cn','ja','fr-fr','de-de','es-es','ru','ko'])
        self.gtts_auto_detect_switch = ToggleSwitch()
        auto_detect_layout = QHBoxLayout()
        auto_detect_layout.addWidget(self.gtts_auto_detect_switch); auto_detect_layout.addStretch()
        gtts_layout.addRow("默认语言 (Excel留空时):", self.gtts_lang_combo)
        gtts_layout.addRow("自动检测语言 (中/日等):", auto_detect_layout)
        
        # --- 音频与录音 ---
        audio_group = QGroupBox("音频与录音")
        audio_layout = QFormLayout(audio_group)
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(["44100 Hz (CD质量, 推荐)","48000 Hz (录音室质量)","22050 Hz (中等质量)","16000 Hz (语音识别常用)"])
        self.channels_combo = QComboBox()
        self.channels_combo.addItems(["1 (单声道, 推荐)","2 (立体声)"])
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_label = QLabel("1.0x")
        self.gain_slider.setRange(5, 50); self.gain_slider.setValue(10)
        gain_layout = QHBoxLayout(); gain_layout.addWidget(self.gain_slider); gain_layout.addWidget(self.gain_label)
        audio_layout.addRow("采样率:", self.sample_rate_combo)
        audio_layout.addRow("通道:", self.channels_combo)
        audio_layout.addRow("录音音量增益:", gain_layout)
        
        # 将所有 GroupBox 添加到主布局
        form_layout.addRow(appearance_group)
        form_layout.addRow(file_group)
        form_layout.addRow(gtts_group)
        form_layout.addRow(audio_group)

        # --- 保存按钮 ---
        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存所有设置")
        self.save_btn.setObjectName("AccentButton")
        button_layout.addStretch()
        button_layout.addWidget(self.save_btn)
        
        # 将 QFormLayout 放入一个可以滚动的区域
        scroll_content = QWidget()
        scroll_content.setLayout(form_layout)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(scroll_content)
        scroll_area.setFrameShape(QScrollArea.NoFrame) # 无边框，与背景融合

        layout.addWidget(scroll_area) # 添加滚动区域
        layout.addLayout(button_layout) # 保存按钮在滚动区外，总是在底部可见
        
        # --- 连接信号 ---
        self.gain_slider.valueChanged.connect(lambda v: self.gain_label.setText(f"{v/10.0:.1f}x"))
        self.save_btn.clicked.connect(self.save_settings)
        self.results_dir_btn.clicked.connect(self.select_results_dir)
        self.theme_combo.currentTextChanged.connect(self.preview_theme)

    # 移除 create_general_settings_widget, create_audio_settings_widget, create_gtts_settings_widget
    # ...

    def populate_all(self):
        self.populate_themes()
        self.populate_word_lists()

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
        
        self.theme_combo.setCurrentText(self.config.get("theme", "Modern_light_tab.qss"))
        file_settings = self.config.get("file_settings", {})
        self.word_list_combo.setCurrentText(file_settings.get('word_list_file', ''))
        self.participant_name_input.setText(file_settings.get('participant_base_name', ''))
        self.results_dir_input.setText(file_settings.get("results_dir", os.path.join(BASE_PATH, "Results")))
        
        gtts_settings = self.config.get("gtts_settings", {})
        self.gtts_lang_combo.setCurrentText(gtts_settings.get('default_lang', 'en-us'))
        self.gtts_auto_detect_switch.setChecked(gtts_settings.get('auto_detect', True))
        
        audio_settings = self.config.get("audio_settings", {})
        sr_text = next((s for s in [self.sample_rate_combo.itemText(i) for i in range(self.sample_rate_combo.count())] if str(audio_settings.get('sample_rate', 44100)) in s), "44100 Hz (CD质量, 推荐)")
        self.sample_rate_combo.setCurrentText(sr_text)
        ch_text = next((s for s in [self.channels_combo.itemText(i) for i in range(self.channels_combo.count())] if str(audio_settings.get('channels', 1)) in s), "1 (单声道, 推荐)")
        self.channels_combo.setCurrentText(ch_text)
        gain = audio_settings.get('recording_gain', 1.0)
        self.gain_slider.setValue(int(gain * 10))
        self.gain_label.setText(f"{gain:.1f}x")

    def preview_theme(self, theme_file):
        if not theme_file: return
        theme_path = os.path.join(THEMES_DIR, theme_file)
        if os.path.exists(theme_path):
            with open(theme_path, "r", encoding="utf-8") as f: self.parent_window.setStyleSheet(f.read())
            
    def save_settings(self):
        self.config['theme'] = self.theme_combo.currentText()
        self.config['file_settings'] = {"word_list_file": self.word_list_combo.currentText(), "participant_base_name": self.participant_name_input.text(), "results_dir": self.results_dir_input.text()}
        self.config['gtts_settings'] = {"default_lang": self.gtts_lang_combo.currentText(), "auto_detect": self.gtts_auto_detect_switch.isChecked()}
        sample_rate_text = self.sample_rate_combo.currentText().split(' ')[0]
        channels_text = self.channels_combo.currentText().split(' ')[0]
        self.config['audio_settings'] = {"sample_rate": int(sample_rate_text), "channels": int(channels_text), "recording_gain": self.gain_slider.value() / 10.0}
        
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f: json.dump(self.config, f, indent=4)
            self.parent_window.config = self.config
            self.parent_window.apply_theme()
            QMessageBox.information(self, "成功", "所有设置已成功保存！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")
if __name__ == "__main__":
    # `app` 和 `splash` 已经在文件顶部创建并显示

    # 阶段3: 执行主要的、可能耗时的导入和定义
    splash.showMessage("加载核心组件... (10%)", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
    splash.progressBar.setValue(10)
    app.processEvents()
    
    # ... (延迟导入的代码会在这里执行) ...

    # 阶段4: 加载配置 (15% -> 25%)
    splash.showMessage("加载用户配置... (15%)", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
    splash.progressBar.setValue(15)
    app.processEvents()
    main_config = setup_and_load_config()
    splash.progressBar.setValue(25)
    app.processEvents()

    # ===== 新增/NEW: 阶段5: 准备文件夹 (25% -> 30%) =====
    splash.showMessage("准备文件目录... (25%)", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
    app.processEvents()
    ensure_directories_exist() # 调用新函数
    splash.progressBar.setValue(30)
    app.processEvents()
    
    # 阶段6: 加载模块 (30% -> 50%)
    splash.showMessage("加载功能模块... (30%)", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
    load_modules(splash, progress_offset=30, progress_scale=0.20)
    splash.progressBar.setValue(50)
    app.processEvents()

    # 阶段7: 创建主窗口实例 (MainWindow 的 __init__ 会接管后续进度更新)
    window = MainWindow(splash_ref=splash)

    # 阶段8: 显示主窗口并关闭启动画面
    window.show()
    splash.finish(window)

    sys.exit(app.exec_())

    # 执行一个简单的循环来实现淡出
    opacity = 1.0
    while opacity > 0:
        splash.setWindowOpacity(opacity)
        opacity -= 0.05 # 每次降低5%的不透明度
        time.sleep(0.008) # 8毫秒的间隔，使动画平滑
        app.processEvents()

    splash.close()

    sys.exit(app.exec_())
