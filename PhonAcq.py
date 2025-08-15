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
import traceback

# ==============================================================================
# 阶段一：绝对最小化导入，用于瞬时启动画面
# ==============================================================================
from PyQt5.QtWidgets import QApplication, QSplashScreen, QProgressBar
from PyQt5.QtGui import QPixmap, QColor, QFont, QIcon
from PyQt5.QtCore import Qt, QCoreApplication, QTimer

# --- 启动画面立即执行 ---
# 这部分代码在主程序块中立即执行，以最快速度显示启动画面。
def global_exception_handler(exc_type, exc_value, exc_traceback):
    """
    一个全局的“安全网”，捕获所有未被处理的异常，并以一个友好的、
    非侵入式的小窗口提示用户，而不是让程序崩溃。
    """
    # 首先，在控制台打印出完整的错误信息，方便开发者调试。
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

    # 格式化错误信息，以便在“详情”中显示。
    error_message = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    
    # 我们使用 QTimer.singleShot 来确保UI操作在安全的事件循环中执行。
    def show_friendly_error_dialog():
        # 创建一个“信息”类型的对话框，而不是“严重错误”类型。
        error_box = QMessageBox()
        error_box.setIcon(QMessageBox.Information) # 使用蓝色的 'i' 图标，而非红色的 'X'

        error_box.setWindowTitle("提示")
        error_box.setText("<b>这里好像有点小问题。</b>")
        
        informative_text = (
            "但是您可以尝试继续操作。\n"
            "如果问题持续出现，可以展开详情并向我们反馈。"
        )
        error_box.setInformativeText(informative_text)
        
        error_box.setDetailedText(error_message) # 详细的错误代码依然保留，但默认隐藏

        # --- 查找主窗口并应用主题样式的逻辑保持不变 ---
        main_window = None
        app_instance = QApplication.instance()
        if app_instance:
            for widget in app_instance.topLevelWidgets():
                if isinstance(widget, MainWindow):
                    main_window = widget
                    break
        
        if main_window:
            error_box.setStyleSheet(main_window.styleSheet())
            error_box.setWindowIcon(main_window.windowIcon())
        
        # --- 置顶逻辑保持不变 ---
        error_box.setWindowFlags(error_box.windowFlags() | Qt.WindowStaysOnTopHint)
        
        # 显示对话框。
        error_box.exec_()

    QTimer.singleShot(0, show_friendly_error_dialog)


# 将我们自定义的函数设置为Python的全局异常处理器。
sys.excepthook = global_exception_handler

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
    splash.progressBar.setGeometry(15, splash_pix.height() - 60, splash_pix.width() - 30, 18)
    splash.progressBar.setRange(0, 100)
    splash.progressBar.setValue(0)
    splash.progressBar.setTextVisible(False)
    splash.setFont(QFont("Microsoft YaHei", 10))
    
    # 硬编码样式以确保启动画面样式独立于外部文件
    hardcoded_style = """
        QProgressBar { 
            background-color: rgba(0, 0, 0, 120); 
            border: 1px solid rgba(255, 255, 255, 80); 
            border-radius: 9px; 
            text-align: center; 
            color: white; 
        }
        QProgressBar::chunk { 
            background-color: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #FFFFFF, stop: 1 #FFFFFF); 
            border-radius: 8px; 
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
from modules.language_detector_module import detect_language
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QListWidget, QListWidgetItem, QLineEdit, 
                             QFileDialog, QMessageBox, QComboBox, QSlider, QStyle, 
                             QFormLayout, QGroupBox, QCheckBox, QTabWidget, QScrollArea, 
                             QSpacerItem, QSizePolicy, QGraphicsOpacityEffect, QWidgetAction, QMenu, QDialog)
from PyQt5.QtGui import QIntValidator, QPainter, QPen, QBrush
from PyQt5.QtCore import QThread, pyqtSignal, QObject, pyqtProperty, QRect, QSize, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, QPoint, QEvent
from modules.custom_widgets_module import ToggleSwitch
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
        "ui_settings": { "collector_sidebar_width": 350, "editor_sidebar_width": 320, "hide_all_tooltips": False },
        "audio_settings": { "sample_rate": 44100, "channels": 1, "recording_gain": 1.0, "input_device_index": None, "recording_format": "wav" },
        "file_settings": {"word_list_file": "", "participant_base_name": "participant", "results_dir": os.path.join(BASE_PATH, "Results")},
        "gtts_settings": {"default_lang": "en-us", "auto_detect": True},
        "app_settings": {"enable_logging": True, "startup_page": None}, # [新增] startup_page: None
        "theme": "默认.qss"
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
    """
    [v2.0 - 可禁用版] 动态加载所有位于 'modules' 目录下的模块。
    此版本会读取配置，并跳过被用户禁用的模块。
    """
    global MODULES, main_config
    MODULES = {}
    modules_dir = os.path.join(BASE_PATH, "modules")
    if not os.path.exists(modules_dir): os.makedirs(modules_dir)
    
    # --- [核心修改] ---
    # 1. 从已加载的全局配置中获取禁用的模块列表
    disabled_modules = main_config.get("app_settings", {}).get("disabled_modules", [])
    
    # 2. 筛选出所有未被禁用的模块文件
    all_module_files = [f for f in os.listdir(modules_dir) if f.endswith('.py') and not f.startswith('__')]
    enabled_module_files = [f for f in all_module_files if f.replace('.py', '') not in disabled_modules]
    # --- [修改结束] ---
    
    total_modules = len(enabled_module_files)
    for i, filename in enumerate(enabled_module_files): # <--- [核心修改] 遍历筛选后的列表
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

class AnimationManager:
    """
    一个用于管理全局UI动画的中央引擎。
    支持页面切换、主窗口尺寸变换，以及可配置的菜单弹出/消失动画。
    """
    def __init__(self, parent):
        self.parent = parent # parent 应该是 MainWindow 实例
        self.active_animations = {}

    def slide_and_fade_in(self, widget, direction='right', duration=300, offset=30):
        # ... (此方法保持不变) ...
        if not widget or not self.parent.animations_enabled: return
        effect = widget.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(widget); widget.setGraphicsEffect(effect)
        opacity_anim = QPropertyAnimation(effect, b"opacity")
        opacity_anim.setDuration(duration); opacity_anim.setStartValue(0.0); opacity_anim.setEndValue(1.0)
        opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        pos_anim = QPropertyAnimation(widget, b"pos"); pos_anim.setDuration(duration)
        start_pos = widget.pos(); end_pos = widget.pos()
        if direction == 'right': start_pos.setX(end_pos.x() + offset)
        else: start_pos.setX(end_pos.x() - offset)
        pos_anim.setStartValue(start_pos); pos_anim.setEndValue(end_pos)
        pos_anim.setEasingCurve(QEasingCurve.OutCubic)
        anim_group = QParallelAnimationGroup()
        anim_group.addAnimation(opacity_anim); anim_group.addAnimation(pos_anim)
        anim_group.finished.connect(lambda: self.active_animations.pop(id(widget), None))
        self.active_animations[id(widget)] = (anim_group, effect)
        anim_group.start(QParallelAnimationGroup.DeleteWhenStopped)

    def animate_window_resize(self, target_size, duration=350):
        # ... (此方法保持不变) ...
        animation = QPropertyAnimation(self.parent, b"size")
        animation.setDuration(duration); animation.setEndValue(target_size)
        animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.active_animations['window_resize'] = animation
        animation.finished.connect(lambda: self.active_animations.pop('window_resize', None))
        animation.start(QPropertyAnimation.DeleteWhenStopped)

    # --- [核心修改] 新增的菜单动画方法 ---
    def animate_menu(self, menu, final_pos):
        """
        为 QMenu 应用一个可配置的、双向的弹出/消失动画。
        如果主题禁用了动画，则回退到标准的 exec_()。
        :param menu: 要应用动画的 QMenu 实例。
        :param final_pos: 菜单动画结束时的最终位置。
        :return: 无
        """
        # 1. 检查动画是否被主题禁用
        if not self.parent.animations_enabled:
            menu.exec_(final_pos)
            return

        # 2. 定义动画参数
        duration = 100
        offset = 20

        # --- 消失动画逻辑 ---
        def create_disappear_animation():
            anim_group_disappear = QParallelAnimationGroup(menu)
            
            opacity_anim_out = QPropertyAnimation(menu, b"windowOpacity")
            opacity_anim_out.setDuration(duration)
            opacity_anim_out.setStartValue(1.0)
            opacity_anim_out.setEndValue(0.0)
            opacity_anim_out.setEasingCurve(QEasingCurve.InCubic)
            
            pos_anim_out = QPropertyAnimation(menu, b"pos")
            pos_anim_out.setDuration(duration)
            pos_anim_out.setStartValue(menu.pos())
            # 向上移动消失
            pos_anim_out.setEndValue(QPoint(menu.pos().x(), menu.pos().y() - offset))
            pos_anim_out.setEasingCurve(QEasingCurve.InCubic)
            
            anim_group_disappear.addAnimation(opacity_anim_out)
            anim_group_disappear.addAnimation(pos_anim_out)
            
            # 动画结束后，才真正关闭并销毁菜单
            anim_group_disappear.finished.connect(menu.close)
            
            return anim_group_disappear

        # --- 启动消失动画的函数 ---
        # 这个函数将是我们新的“关闭”命令
        def start_disappear():
            # 检查是否已有动画在运行，防止重复触发
            if 'menu_disappear' in self.active_animations: return
            
            anim = create_disappear_animation()
            self.active_animations['menu_disappear'] = anim
            anim.finished.connect(lambda: self.active_animations.pop('menu_disappear', None))
            anim.start(QParallelAnimationGroup.DeleteWhenStopped)
        
        # --- 出现动画逻辑 ---
        menu.setWindowOpacity(0.0)
        start_pos = QPoint(final_pos.x(), final_pos.y() - offset)
        menu.move(start_pos)
        menu.show()
        
        anim_group_appear = QParallelAnimationGroup(menu)
        opacity_anim_in = QPropertyAnimation(menu, b"windowOpacity"); opacity_anim_in.setDuration(duration)
        opacity_anim_in.setStartValue(0.0); opacity_anim_in.setEndValue(1.0); opacity_anim_in.setEasingCurve(QEasingCurve.OutCubic)
        pos_anim_in = QPropertyAnimation(menu, b"pos"); pos_anim_in.setDuration(duration)
        pos_anim_in.setStartValue(start_pos); pos_anim_in.setEndValue(final_pos); pos_anim_in.setEasingCurve(QEasingCurve.OutCubic)
        anim_group_appear.addAnimation(opacity_anim_in); anim_group_appear.addAnimation(pos_anim_in)
        
        # --- 事件过滤器，处理外部点击 ---
        class MenuEventFilter(QObject):
            def __init__(self, menu, closer_func, parent=None):
                super().__init__(parent); self.menu = menu; self.closer_func = closer_func
            def eventFilter(self, obj, event):
                if event.type() == QEvent.MouseButtonPress:
                    if self.menu.isVisible() and not self.menu.rect().contains(self.menu.mapFromGlobal(event.globalPos())):
                        self.closer_func() # 调用关闭函数（启动消失动画）
                        QApplication.instance().removeEventFilter(self)
                        return True
                return super().eventFilter(obj, event)

        # 绑定事件
        menu_event_filter = MenuEventFilter(menu, start_disappear, menu)
        QApplication.instance().installEventFilter(menu_event_filter)
        menu.aboutToHide.connect(lambda: QApplication.instance().removeEventFilter(menu_event_filter))
        
        # 将“关闭函数”连接到所有菜单项的点击事件
        for action in menu.actions():
            if isinstance(action, QWidgetAction):
                widget = action.defaultWidget()
                if hasattr(widget, 'clicked'):
                    widget.clicked.connect(start_disappear)

        anim_group_appear.start(QParallelAnimationGroup.DeleteWhenStopped)

class MainWindow(QMainWindow):
    class RememberingWindow(QMainWindow):
        def __init__(self, module_key, main_window_ref, parent=None):
            super().__init__(parent)
            self.module_key = module_key
            self.main_window_ref = main_window_ref

        def closeEvent(self, event):
            """当窗口关闭时，重写此事件以保存其几何信息。"""
            # 1. 确保 'window_geometries' 键在配置中存在
            if 'window_geometries' not in self.main_window_ref.config:
                self.main_window_ref.config['window_geometries'] = {}
            
            # 2. 获取几何信息并将其转换为JSON兼容的字符串 (Base64)
            geometry_data = self.saveGeometry().toBase64().data().decode('utf-8')
            self.main_window_ref.config['window_geometries'][self.module_key] = geometry_data
            
            # 3. 调用主窗口的保存方法
            self.main_window_ref.save_config()
            
            # 4. 必须调用父类的closeEvent，否则窗口不会关闭！
            super().closeEvent(event)
    def __init__(self, app_ref, splash_ref=None, tooltips_ref=None):
        super().__init__()
        self.app_ref = app_ref
        self.animation_manager = AnimationManager(self)
        self.last_sub_tab_indices = {}
        self.animations_enabled = True # 默认启用动画
        self.BASE_PATH = BASE_PATH
        self.audio_record_dir = AUDIO_RECORD_DIR
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
        self.COMPACT_MIN_SIZE = (1150, 850)
        
        # 将初始尺寸设置为默认值
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

        # --- [核心修复] 将全局 MODULES 字典暴露为实例属性 ---
        self.MODULES = MODULES
        # --- [修复结束] ---


        # 页面创建
        self.accent_collection_page = self.create_module_or_placeholder('accent_collection_page', 'accent_collection_module', '标准朗读采集', 
            lambda m, ts, w, l, im, rdf: m.create_page(self, self.config, ts, w, l, detect_language, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH, im, rdf))

        self.voicebank_recorder_page = self.create_module_or_placeholder('voicebank_recorder_page', 'voicebank_recorder_module', '提示音录制', 
            lambda m, ts, w, l, im, rdf: m.create_page(self, WORD_LIST_DIR, AUDIO_RECORD_DIR, ts, w, l, im, rdf))
        
        self.audio_manager_page = self.create_module_or_placeholder('audio_manager_page', 'audio_manager_module', '音频数据管理器', 
            lambda m, ts, im: m.create_page(self, self.config, BASE_PATH, self.config['file_settings'].get("results_dir"), AUDIO_RECORD_DIR, im, ts))

        # ... 对所有其他页面创建调用进行同样的修改 ...
        self.wordlist_editor_page = self.create_module_or_placeholder('wordlist_editor_page', 'wordlist_editor_module', '通用词表编辑器', 
            lambda m, im, dl: m.create_page(self, WORD_LIST_DIR, im, dl))
            
        self.converter_page = self.create_module_or_placeholder('converter_page', 'excel_converter_module', 'Excel转换器', 
            lambda m, im: m.create_page(self, WORD_LIST_DIR, MODULES, im))

        self.help_page = self.create_module_or_placeholder('help_page', 'help_module', '帮助文档', 
            lambda m: m.create_page(self))
        
        # [核心修改] 将局部变量提升为实例变量
        self.DIALECT_VISUAL_WORDLIST_DIR = os.path.join(self.BASE_PATH, "dialect_visual_wordlists")
        os.makedirs(self.DIALECT_VISUAL_WORDLIST_DIR, exist_ok=True)
        
        # [核心修改] 更新创建页面时的调用，使用 self.DIALECT_VISUAL_WORDLIST_DIR
        self.dialect_visual_page = self.create_module_or_placeholder('dialect_visual_page', 'dialect_visual_collector_module', '看图说话采集', 
            lambda m, ts, w, l, im, rdf: m.create_page(self, self.config, self.BASE_PATH, self.DIALECT_VISUAL_WORDLIST_DIR, AUDIO_RECORD_DIR, ts, w, l, im, rdf))
        
        self.dialect_visual_editor_page = self.create_module_or_placeholder('dialect_visual_editor_page', 'dialect_visual_editor_module', '图文词表编辑器', 
            lambda m, ts, im: m.create_page(self, self.DIALECT_VISUAL_WORDLIST_DIR, ts, im))
        
        self.tts_utility_page = self.create_module_or_placeholder('tts_utility_page', 'tts_utility_module', 'TTS 工具',
            lambda m, ts, w, dl, std_wld, im: m.create_page(self, self.config, AUDIO_TTS_DIR, ts, w, dl, std_wld, im))

        self.flashcard_page = self.create_module_or_placeholder('flashcard_page', 'flashcard_module', '速记卡',
            lambda m, ts_class, sil_class, bp_val, gtts_dir_val, gr_dir_val, im_val: m.create_page(self, ts_class, sil_class, bp_val, gtts_dir_val, gr_dir_val, im_val))
        
        self.settings_page = self.create_module_or_placeholder('settings_page', 'settings_module', '程序设置',
            lambda m, ts, t_dir, w_dir, rdf: m.create_page(self, ts, t_dir, w_dir, rdf),
            extra_args={'rdf': resolve_recording_device})

        self.audio_analysis_page = self.create_module_or_placeholder('audio_analysis_page', 'audio_analysis_module', '音频分析', 
            lambda m, im, ts: m.create_page(self, im, ts))

        self.log_viewer_page = self.create_module_or_placeholder('log_viewer_page', 'log_viewer_module', '日志查看器',
            lambda m, ts, im: m.create_page(self, self.config, ts, im))
            
        # [新增] 在 __init__ 中初始化独立窗口列表
        self.independent_windows = []
        
        if self.splash_ref:
            self.splash_ref.showMessage("构建用户界面...", Qt.AlignBottom | Qt.AlignLeft, Qt.white)
            self.splash_ref.progressBar.setValue(90)
            QApplication.processEvents()
        
        # --- [核心修改] 构建Tab结构，并根据配置隐藏禁用的模块 ---
        
        # 1. 首先从配置中获取已禁用的模块列表
        disabled_modules = self.config.get("app_settings", {}).get("disabled_modules", [])

        # 2. 为每个主标签页创建子 QTabWidget
        collection_tabs = QTabWidget(); collection_tabs.setObjectName("SubTabWidget")
        preparation_tabs = QTabWidget(); preparation_tabs.setObjectName("SubTabWidget")
        management_tabs = QTabWidget(); management_tabs.setObjectName("SubTabWidget")
        utilities_tabs = QTabWidget(); utilities_tabs.setObjectName("SubTabWidget")
        system_tabs = QTabWidget(); system_tabs.setObjectName("SubTabWidget")

        # 3. 条件性地向子 QTabWidget 添加标签页
        # 只有当模块的 key 不在 disabled_modules 列表中时，才添加它的标签页
        
        # 数据采集
        if 'accent_collection_module' not in disabled_modules:
            collection_tabs.addTab(self.accent_collection_page, "标准朗读采集")
        if 'dialect_visual_collector_module' not in disabled_modules:
            collection_tabs.addTab(self.dialect_visual_page, "看图说话采集")
        if 'voicebank_recorder_module' not in disabled_modules:
            collection_tabs.addTab(self.voicebank_recorder_page, "提示音录制")

        # 数据准备
        if 'wordlist_editor_module' not in disabled_modules:
            preparation_tabs.addTab(self.wordlist_editor_page, "通用词表编辑器")
        if 'dialect_visual_editor_module' not in disabled_modules:
            preparation_tabs.addTab(self.dialect_visual_editor_page, "图文词表编辑器")
        if 'excel_converter_module' not in disabled_modules:
            preparation_tabs.addTab(self.converter_page, "Excel转换器")
        
        # 资源管理
        if 'audio_manager_module' not in disabled_modules:
            management_tabs.addTab(self.audio_manager_page, "音频数据管理器")
        if 'audio_analysis_module' not in disabled_modules:
            management_tabs.addTab(self.audio_analysis_page, "音频分析")
        if 'log_viewer_module' not in disabled_modules:
            management_tabs.addTab(self.log_viewer_page, "日志查看器")
        
        # 实用工具
        if 'tts_utility_module' not in disabled_modules:
            utilities_tabs.addTab(self.tts_utility_page, "TTS 工具")
        if 'flashcard_module' not in disabled_modules:
            utilities_tabs.addTab(self.flashcard_page, "速记卡")
        
        # 系统与帮助 (settings_module 和 help_module 通常应为核心模块，但为保持一致性也做检查)
        if 'settings_module' not in disabled_modules:
            system_tabs.addTab(self.settings_page, "程序设置")
        if 'help_module' not in disabled_modules:
            system_tabs.addTab(self.help_page, "帮助文档")
        
        # 4. 只有当子 QTabWidget 中有内容时，才将它添加到主 QTabWidget
        #    这可以防止在整个类别被禁用时出现一个空的主标签页
        if collection_tabs.count() > 0:
            self.main_tabs.addTab(collection_tabs, "数据采集")
        if preparation_tabs.count() > 0:
            self.main_tabs.addTab(preparation_tabs, "数据准备")
        if management_tabs.count() > 0:
            self.main_tabs.addTab(management_tabs, "资源管理")
        if utilities_tabs.count() > 0:
            self.main_tabs.addTab(utilities_tabs, "实用工具")
        if system_tabs.count() > 0:
            self.main_tabs.addTab(system_tabs, "系统与帮助")
            
        # --- [修改结束] ---

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
        self._install_tab_bar_event_filters()
        self._setup_tab_context_menus()
        
        # --- [核心修改] 在末尾调用新的启动页应用函数 ---
        self._apply_startup_page()

    def _install_tab_bar_event_filters(self):
        """
        遍历所有主、子标签页，并为它们的 TabBar 安装事件过滤器，
        以捕获双击事件。
        """
        # 为主标签页的 TabBar 安装过滤器
        self.main_tabs.tabBar().installEventFilter(self)
        
        # 遍历所有子标签页的 TabBar 并安装过滤器
        for i in range(self.main_tabs.count()):
            sub_widget = self.main_tabs.widget(i)
            if isinstance(sub_widget, QTabWidget):
                sub_widget.tabBar().installEventFilter(self)

    def eventFilter(self, obj, event):
        """
        重写 QObject.eventFilter 来处理安装在 TabBar 上的事件。
        """
        # 检查事件类型是否为鼠标双击
        if event.type() == QEvent.MouseButtonDblClick:
            # 确保事件源是一个 QTabBar
            if "QTabBar" in obj.metaObject().className():
                tab_bar = obj
                tab_widget = tab_bar.parent()
                
                # 确定被双击的标签页索引
                tab_index = tab_bar.tabAt(event.pos())
                
                if tab_index != -1:
                    # 获取对应的页面控件
                    page_widget = tab_widget.widget(tab_index)
                    
                    # 检查页面是否有可用的设置对话框
                    if hasattr(page_widget, 'open_settings_dialog'):
                        # 调用设置对话框
                        page_widget.open_settings_dialog()
                        # 返回 True，表示我们已经处理了这个事件，它不应再被传递
                        return True
        
        # 对于所有其他事件，调用父类的默认实现
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        """
        [新增] 重写键盘按下事件，以处理全局快捷键。
        """
        # --- 检查 Ctrl 键是否被按下 ---
        # 如果没有按下 Ctrl，则不处理，将事件传递给默认处理器
        if not (event.modifiers() & Qt.ControlModifier):
            super().keyPressEvent(event)
            return

        key = event.key()

        # --- 1. 处理一级标签页切换 (Ctrl + 1-5) ---
        if Qt.Key_1 <= key <= Qt.Key_5:
            target_index = key - Qt.Key_1 # Qt.Key_1 的值是 49, Qt.Key_2 是 50...
            if target_index < self.main_tabs.count():
                self.main_tabs.setCurrentIndex(target_index)
                event.accept() # 标记事件已处理
                return

        # --- 2. 处理二级标签页切换 (Ctrl + Left/Right) ---
        elif key in (Qt.Key_Left, Qt.Key_Right):
            # 获取当前活动的主标签页下的子 QTabWidget
            current_main_widget = self.main_tabs.currentWidget()
            if isinstance(current_main_widget, QTabWidget):
                sub_tabs = current_main_widget
                count = sub_tabs.count()
                if count > 0:
                    current_index = sub_tabs.currentIndex()
                    
                    if key == Qt.Key_Left:
                        # 计算上一个索引，并实现循环
                        next_index = (current_index - 1 + count) % count
                    else: # Qt.Key_Right
                        # 计算下一个索引，并实现循环
                        next_index = (current_index + 1) % count
                        
                    sub_tabs.setCurrentIndex(next_index)
                    event.accept() # 标记事件已处理
                    return

        # 如果快捷键不匹配，调用父类的实现
        super().keyPressEvent(event)

    def _apply_startup_page(self):
        """
        [新增] 在程序启动时，读取配置并尝试导航到指定的启动页。
        如果失败或未设置，则默认导航到第一个标签页。
        """
        startup_setting = self.config.get("app_settings", {}).get("startup_page")
        
        navigated = False
        if isinstance(startup_setting, dict):
            main_tab = startup_setting.get("main")
            sub_tab = startup_setting.get("sub")
            if main_tab:
                # 尝试导航，如果成功，_navigate_to_tab 会返回目标页面实例
                if self._navigate_to_tab(main_tab, sub_tab) is not None:
                    navigated = True
        
        # 如果导航失败或没有设置启动页，则安全地回退到默认行为
        if not navigated:
            self.main_tabs.setCurrentIndex(0)
            # 确保第一个标签页的内容也被正确加载
            self.on_main_tab_changed(0)

    def _setup_tab_context_menus(self):
        """遍历并为所有主、子标签页的TabBar设置上下文菜单策略。"""
        # 为主标签页设置
        self.main_tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.main_tabs.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)
        
        # 遍历主标签页，为所有子标签页（如果存在）设置
        for i in range(self.main_tabs.count()):
            sub_widget = self.main_tabs.widget(i)
            if isinstance(sub_widget, QTabWidget):
                sub_widget.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
                sub_widget.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)

    def request_tab_refresh(self, page_instance):
        """
        [新增] 公共API，供子模块页面调用以请求刷新自身。
        """
        # 1. 遍历所有标签页，找到发出请求的页面实例在哪个位置
        for i in range(self.main_tabs.count()):
            main_widget = self.main_tabs.widget(i)
            if main_widget == page_instance:
                # 请求来自一个没有子标签的主页面 (不太可能，但做个兼容)
                self._refresh_tab(self.main_tabs, i)
                return

            if isinstance(main_widget, QTabWidget):
                for j in range(main_widget.count()):
                    sub_widget = main_widget.widget(j)
                    if sub_widget == page_instance:
                        # 找到了！调用底层的刷新方法
                        self._refresh_tab(main_widget, j)
                        return
        
        # 如果找不到，可能是一个独立窗口，或者代码逻辑有误
        print(f"警告: 页面 {page_instance} 请求刷新，但在标签页中未找到它。")

    def _show_tab_context_menu(self, position):

        # --- 1. 动态导入依赖 ---
        try:
            from modules.performance_monitor import PerformanceMonitor
            psutil_available = True
        except ImportError:
            psutil_available = False

        # --- 2. 确定被点击的UI元素和页面 ---
        tab_widget = self.sender().parent()
        if not isinstance(tab_widget, QTabWidget):
            return

        tab_index = tab_widget.tabBar().tabAt(position)
        if tab_index == -1:
            return
            
        page_widget = tab_widget.widget(tab_index)
        if not page_widget:
            return

        # --- 3. 确定被点击页面的完整标识 (主/子标签名称) ---
        main_tab_text = None
        sub_tab_text = None

        if tab_widget == self.main_tabs:
            # 右键点击的是主标签页
            main_tab_text = self.main_tabs.tabText(tab_index)
            sub_widget = self.main_tabs.widget(tab_index)
            if isinstance(sub_widget, QTabWidget) and sub_widget.count() > 0:
                # 子标签是当前主标签下已选中的那个
                sub_tab_text = sub_widget.tabText(sub_widget.currentIndex())
        else:
            # 右键点击的是子标签页
            sub_tab_text = tab_widget.tabText(tab_index)
            # 向上查找其所属的主标签页
            for i in range(self.main_tabs.count()):
                if self.main_tabs.widget(i) == tab_widget:
                    main_tab_text = self.main_tabs.tabText(i)
                    break
        
        # 如果无法确定页面标识，则不继续 (主要针对主标签)
        if not main_tab_text:
            return

        # --- 4. 检查各项功能的可用性 ---
        can_refresh = bool(page_widget.property("recreation_factory"))
        attr_name = page_widget.property("main_window_attr_name")
        
        DISABLED_FOR_NEW_WINDOW = ['settings_page', 'help_page']
        can_open_new = can_refresh and (attr_name not in DISABLED_FOR_NEW_WINDOW)
        can_monitor = psutil_available and attr_name is not None
        can_set_startup = attr_name is not None


        # --- [核心修改] ---
        # 检查页面是否有自己的设置对话框
        can_configure = hasattr(page_widget, 'open_settings_dialog') and attr_name != 'settings_page'

        # 如果所有功能都不可用，则不显示菜单
        # [修改] 将 can_configure 添加到检查中
        if not (can_refresh or can_open_new or can_monitor or can_set_startup or can_configure):
            return

        # --- 5. 构建菜单 ---
        menu = QMenu(self)

        # 功能块: 页面操作
        if can_refresh:
            refresh_icon = self.icon_manager.get_icon("refresh")
            refresh_action = menu.addAction(refresh_icon, "刷新此标签页")
            refresh_action.triggered.connect(lambda: self._refresh_tab(tab_widget, tab_index))

        if can_open_new:
            new_window_icon = self.icon_manager.get_icon("new_window")
            new_window_action = menu.addAction(new_window_icon, "在新窗口中打开")
            new_window_action.triggered.connect(lambda: self._open_tab_in_new_window(tab_widget, tab_index))
        
        # [核心修改] 将 "模块设置" 和 "性能监视" 放在同一个功能块中
        
        # 只有当这个功能块有内容时，才在它之前添加分割线
        if (can_configure or can_monitor) and not menu.isEmpty():
            menu.addSeparator()

        # 功能块: 模块设置与分析
        if can_configure:
            settings_icon = self.icon_manager.get_icon("settings")
            settings_action = menu.addAction(settings_icon, "模块设置")
            settings_action.setToolTip("打开此模块专属的设置面板")
            settings_action.triggered.connect(page_widget.open_settings_dialog)

        if can_monitor:
            monitor_icon = self.icon_manager.get_icon("monitor")
            monitor_action = menu.addAction(monitor_icon, "性能监视")
            monitor_action.triggered.connect(lambda: self.open_performance_monitor(page_widget))
        elif not can_monitor and not psutil_available:
             monitor_action = menu.addAction("性能监视 (不可用)")
             monitor_action.setToolTip("请安装 psutil 库以启用此功能 (pip install psutil)")
             monitor_action.setEnabled(False)

        # 功能块: 个性化设置
        if can_set_startup:
            # [核心修改] 将分割线移到这里
            if not menu.isEmpty():
                menu.addSeparator()

            startup_icon = self.icon_manager.get_icon("launch")
            startup_action = menu.addAction(startup_icon, "设为启动页")
            startup_action.triggered.connect(lambda: self._set_startup_page(main_tab_text, sub_tab_text))

            current_startup_page = self.config.get("app_settings", {}).get("startup_page")
            if current_startup_page is not None:
                clear_icon = self.icon_manager.get_icon("clear_contents")
                clear_action = menu.addAction(clear_icon, "清除启动页设置")
                clear_action.triggered.connect(lambda: self._set_startup_page(None, None))

        # --- 6. 显示菜单 ---
        if menu.isEmpty():
            return
            
        global_pos = tab_widget.tabBar().mapToGlobal(position)
        self.animation_manager.animate_menu(menu, global_pos)


    def _set_startup_page(self, main_text, sub_text):
        """
        [新增] 将指定的页面设为启动页并保存配置。
        如果 main_text 和 sub_text 都为 None，则清除设置。
        """
        app_settings = self.config.setdefault("app_settings", {})
        
        if main_text is None:
            # 清除设置
            app_settings["startup_page"] = None
            QMessageBox.information(self, "提示", "启动页设置已清除。")
        else:
            # 设置新的启动页
            startup_config = {"main": main_text, "sub": sub_text}
            app_settings["startup_page"] = startup_config
            display_text = f"{main_text}" + (f" -> {sub_text}" if sub_text else "")
            QMessageBox.information(self, "提示", f"'{display_text}' 已设为启动页。")
            
        self.save_config()

    # [新增] 在 MainWindow 中添加打开监视器的槽函数
    def open_performance_monitor(self, target_widget):
        """
        为指定的小部件打开一个性能监视器窗口。
        此版本会动态地为目标小部件添加一个销毁信号，并将其传递给
        监视器，以建立一个健壮的生命周期管理链接。
        """
        # --- 防止重复打开同一个监视器的逻辑保持不变 ---
        # 我们检查是否已经为这个小部件打开了一个监视器
        for win in self.independent_windows:
            # 增加一个对 QDialog 的检查，使其更具鲁棒性
            if isinstance(win, QDialog) and getattr(win, 'target_widget', None) == target_widget:
                win.activateWindow()
                win.raise_()
                return
        
        # --- 动态创建信号并实例化监视器 ---
        try:
            from modules.performance_monitor import PerformanceMonitor
            from PyQt5.QtCore import pyqtSignal

            # [核心修复] 在目标页面上动态创建信号，如果它还不存在的话。
            # 这使得任何 QWidget 都可以被监视，而无需修改其原始类。
            if not hasattr(target_widget, 'aboutToBeDestroyed'):
                 target_widget.aboutToBeDestroyed = pyqtSignal()
            
            # 创建监视器实例，并将主窗口(self)作为父级传入
            monitor_dialog = PerformanceMonitor(target_widget, parent=self)
            
            # --- 后续的生命周期管理逻辑保持不变 ---
            # 将其添加到独立窗口列表中以管理其生命周期
            self.independent_windows.append(monitor_dialog)
            # 当监视器窗口被销毁时（例如用户关闭它），自动从列表中移除，防止内存泄漏
            monitor_dialog.destroyed.connect(lambda obj=monitor_dialog: self.independent_windows.remove(obj) if obj in self.independent_windows else None)
            
            monitor_dialog.show()

        except ImportError:
             # 如果 performance_monitor.py 或 psutil 缺失，给出提示
             QMessageBox.warning(self, "功能缺失", "无法加载性能监视器模块。\n请确保 'modules/performance_monitor.py' 文件存在，并且已安装 'psutil' 库。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开性能监视器时发生未知错误:\n{e}")


    def _refresh_tab(self, tab_widget, index):
        """
        [v2 - 带通知版]
        销毁并重建指定的标签页，并在销毁前发出通知，以便关联的窗口
        （如性能监视器）可以安全地关闭。
        """
        old_widget = tab_widget.widget(index)
        if not old_widget:
            return
        
        factory = old_widget.property("recreation_factory")
        attr_name = old_widget.property("main_window_attr_name") 

        if not factory or not attr_name:
            print(f"警告: 标签页 '{tab_widget.tabText(index)}' 缺少重建信息，无法刷新。")
            return

        # [核心修复] 在销毁前，发射 aboutToBeDestroyed 信号
        # 检查该信号是否存在，以防万一
        if hasattr(old_widget, 'aboutToBeDestroyed'):
            try:
                old_widget.aboutToBeDestroyed.emit()
            except Exception as e:
                print(f"发射 aboutToBeDestroyed 信号时出错: {e}")

        # --- 后续的页面替换逻辑保持不变 ---
        tab_text = tab_widget.tabText(index)
        tab_icon = tab_widget.tabIcon(index)
        tab_tooltip = tab_widget.tabToolTip(index)

        # 使用工厂创建新的页面实例
        new_widget = factory()

        # 更新 MainWindow 上的直接引用
        setattr(self, attr_name, new_widget)

        # 在UI上执行替换
        tab_widget.removeTab(index)
        old_widget.deleteLater() # 安全地安排旧部件的删除
        tab_widget.insertTab(index, new_widget, tab_icon, tab_text)
        tab_widget.setTabToolTip(index, tab_tooltip)
        
        # 切换到新创建的标签页以触发其加载逻辑
        tab_widget.setCurrentIndex(index)

    def _open_tab_in_new_window(self, tab_widget, index):
        """
        [v3 - State-Aware]
        在一个新的独立窗口中创建标签页的副本。
        - 首先尝试从设置中加载上次的窗口几何信息。
        - 如果没有，则使用主题感知的智能尺寸计算作为后备。
        - 窗口关闭时会自动保存其位置和大小。
        """
        from PyQt5.QtCore import QByteArray # 确保导入 QByteArray

        current_widget = tab_widget.widget(index)
        if not current_widget: return

        factory = current_widget.property("recreation_factory")
        tab_text = tab_widget.tabText(index)
        module_key = current_widget.property("module_key")

        if not factory or not module_key:
            QMessageBox.warning(self, "操作失败", "此标签页不支持在新窗口中打开或缺少身份信息。")
            return

        # 1. 创建窗口和内容实例
        #    使用我们新的 RememberingWindow 类！
        new_win = self.RememberingWindow(module_key, self)
        new_widget_instance = factory()

        # 2. 准备窗口的基本属性
        new_win.setAttribute(Qt.WA_DeleteOnClose)
        new_win.setWindowTitle(f"{tab_text} - [独立窗口] ")
        new_win.setWindowIcon(self.windowIcon())
        new_win.setStyleSheet(self.styleSheet())
        new_win.setCentralWidget(new_widget_instance)

        # 3. [核心逻辑] 尝试加载已保存的几何信息
        saved_geometries = self.config.get('window_geometries', {})
        saved_geom_b64 = saved_geometries.get(module_key)

        if saved_geom_b64:
            # 如果找到了，就恢复它
            geom_data = QByteArray.fromBase64(saved_geom_b64.encode('utf-8'))
            new_win.restoreGeometry(geom_data)
        else:
            # 如果没找到（第一次打开），则使用我们的智能尺寸计算作为后备
            # --- 主题感知的智能尺寸计算逻辑 (保持不变) ---
            content_min_size = (750, 550)
            content_pref_size = (950, 750)
            if module_key in MODULES:
                try:
                    module_obj = MODULES[module_key]['module']
                    if hasattr(module_obj, 'MODULE_CONTENT_MINIMUM_SIZE'):
                        content_min_size = module_obj.MODULE_CONTENT_MINIMUM_SIZE
                    if hasattr(module_obj, 'MODULE_CONTENT_PREFERRED_SIZE'):
                        content_pref_size = module_obj.MODULE_CONTENT_PREFERRED_SIZE
                except Exception as e:
                    print(f"从模块 '{module_key}' 获取内容尺寸元数据时出错: {e}")
            
            frame_width = new_win.frameGeometry().width() - new_win.geometry().width()
            frame_height = new_win.frameGeometry().height() - new_win.geometry().height()
            final_min_size = (content_min_size[0] + frame_width, content_min_size[1] + frame_height)
            final_pref_size = (content_pref_size[0] + frame_width, content_pref_size[1] + frame_height)
            
            new_win.setMinimumSize(*final_min_size)
            new_win.resize(*final_pref_size)
            new_win.move(self.x() + 50, self.y() + 50)

        # 4. 显示窗口并管理其生命周期
        new_win.show()
        self.independent_windows.append(new_win)
        new_win.destroyed.connect(lambda obj=new_win: self.independent_windows.remove(obj) if obj in self.independent_windows else None)

    def save_config(self):
        """A centralized helper to save the current self.config state to file."""
        try:
            with open(self.SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Error saving configuration to {self.SETTINGS_FILE}: {e}", file=sys.stderr)

    # [新增] 用于模块间通信的槽函数
    def go_to_audio_analysis(self, filepath):
        """
        [v2.0 - 导航优化版]
        切换到音频分析模块。此版本只负责导航和返回页面实例，
        不再负责加载文件，将加载的责任交还给调用者。
        """
        if not hasattr(self, 'audio_analysis_page'):
            QMessageBox.warning(self, "功能缺失", "音频分析模块未成功加载。")
            return None # 返回 None 表示失败

        target_page = self._navigate_to_tab("资源管理", "音频分析")
        
        if target_page:
            # [修改] 移除文件加载的调用
            # target_page.load_audio_file(filepath)
            return target_page # 返回页面实例
        
        return None

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

    def create_module_or_placeholder(self, attr_name, module_key, name, page_factory, extra_args=None):
        """
        [v4 - 稳定闭环版]
        根据模块是否加载成功，创建真实页面或占位符页面。
        此版本基于已知的工作结构进行修复，确保重建的页面也能获得
        完整的属性和新的重建配方，实现无限次刷新。

        :param attr_name: 页面在 MainWindow 实例中对应的属性名 (e.g., 'accent_collection_page')。
        :param module_key: 在全局 MODULES 字典中的键名 (e.g., 'accent_collection_module')。
        :param name: 用户友好的模块名称 (e.g., '标准朗读采集')。
        :param page_factory: 一个lambda函数，封装了创建页面实例所需的具体调用。
        :return: 创建好的 QWidget 页面实例，或一个占位符 QWidget。
        """
        # [核心修复] 立即定义能够创建“下一代”页面的、闭环的重建配方。
        # 它的工作就是重新调用本函数，确保任何被创建的页面都经过完整的属性注入流程。
        future_recreation_factory = lambda: self.create_module_or_placeholder(
            attr_name, module_key, name, page_factory, extra_args
        )

        page = None
        # --- 以下逻辑用于创建“当前这一代”的页面实例 ---
        if module_key in MODULES:
            try:
                # 这个 try-except 块只负责创建初始页面，不再需要定义或存储它自己的工厂。
                module = MODULES[module_key]['module']

                # --- 根据模块标识符，直接调用 page_factory 创建页面 ---
                if module_key == 'settings_module':
                    page = page_factory(module, ToggleSwitch, THEMES_DIR, WORD_LIST_DIR, extra_args['rdf'])
                
                elif module_key == 'flashcard_module':
                    from PyQt5.QtWidgets import QLabel
                    ScalableImageLabelClass = QLabel
                    if 'dialect_visual_collector_module' in MODULES:
                        ScalableImageLabelClass = getattr(MODULES['dialect_visual_collector_module']['module'], 'ScalableImageLabel', QLabel)
                    page = page_factory(module, ToggleSwitch, ScalableImageLabelClass, 
                                        BASE_PATH, AUDIO_TTS_DIR, AUDIO_RECORD_DIR, icon_manager)

                elif module_key == 'accent_collection_module':
                    page = page_factory(module, ToggleSwitch, Worker, Logger, icon_manager, resolve_recording_device)

                elif module_key == 'dialect_visual_collector_module':
                    page = page_factory(module, ToggleSwitch, Worker, Logger, icon_manager, resolve_recording_device)

                elif module_key == 'voicebank_recorder_module':
                    page = page_factory(module, ToggleSwitch, Worker, Logger, icon_manager, resolve_recording_device)
                
                elif module_key == 'dialect_visual_editor_module':
                    page = page_factory(module, ToggleSwitch, icon_manager)
                
                elif module_key == 'audio_manager_module':
                    page = page_factory(module, ToggleSwitch, icon_manager)
                
                elif module_key == 'wordlist_editor_module':
                    page = page_factory(module, icon_manager, detect_language)

                elif module_key == 'excel_converter_module':
                    page = page_factory(module, icon_manager)
                
                elif module_key == 'tts_utility_module':
                    page = page_factory(module, ToggleSwitch, Worker, detect_language, WORD_LIST_DIR, icon_manager)

                elif module_key == 'audio_analysis_module':
                    page = page_factory(module, icon_manager, ToggleSwitch)

                elif module_key == 'log_viewer_module':
                    page = page_factory(module, ToggleSwitch, icon_manager)

                else:
                    # 适用于没有复杂依赖的模块, 如 help_module
                    page = page_factory(module)

            except Exception as e:
                print(f"创建模块 '{name}' 页面时出错: {e}", file=sys.stderr)
                page = None
        
        # --- [核心修改] 优化后的占位符创建逻辑 ---
        if page is None:
            from PyQt5.QtWidgets import QLabel, QVBoxLayout
            from PyQt5.QtCore import QSize
            
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setAlignment(Qt.AlignCenter)
            layout.setSpacing(20) # 增加图片和文字之间的间距

            # 1. 创建并添加图片标签
            image_label = QLabel()
            # 从 IconManager 获取图标，如果不存在会优雅地回退
            # 建议在 assets/icons/ 中添加一个名为 module_missing.svg 的图片
            icon = self.icon_manager.get_icon("module_missing") 
            pixmap = icon.pixmap(QSize(512, 512))
            image_label.setPixmap(pixmap)
            image_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(image_label)

            # 2. 创建并添加文本标签
            # 确定要显示的文本
            if module_key == 'settings_module':
                label_text = f"<b>核心模块加载失败</b><br><br>设置模块 ('{name}') 未能加载。<br>请检查 'modules/settings_module.py' 文件是否存在且无误。"
            else:
                label_text = f"<b>模块 '{name}' 未能加载</b><br><br>请检查 'modules/{module_key}.py' 文件及其相关依赖是否正确。"
            
            text_label = QLabel(label_text)
            text_label.setWordWrap(True)
            text_label.setAlignment(Qt.AlignCenter)
            # 为标签设置对象名，以便主题可以对其进行样式化
            text_label.setObjectName("ModuleMissingTextLabel") 
            
            # 移除硬编码的样式表！让颜色和字体完全由当前主题决定。
            # text_label.setStyleSheet("color: #D32F2F; font-size: 24px;") # <-- 已移除
            
            layout.addWidget(text_label)
            
        # [核心修复] 为最终创建的页面（无论是真实模块还是占位符）注入“未来”的重建配方。
        if page:
            page.setProperty("recreation_factory", future_recreation_factory)
            page.setProperty("main_window_attr_name", attr_name) 
            page.setProperty("module_key", module_key)
        return page
    
    def on_main_tab_changed(self, index):
        """主标签页切换时触发，进而触发子标签页的刷新逻辑和动画。"""
        current_main_tab_text = self.main_tabs.tabText(index)
        current_main_widget = self.main_tabs.widget(index)
        if current_main_widget and isinstance(current_main_widget, QTabWidget):
            # 强制将该组的上一个索引设为-1，确保总是从左侧进入
            self.last_sub_tab_indices[current_main_tab_text] = -1
            
            # 调用 on_sub_tab_changed，它现在已经包含了动画逻辑
            self.on_sub_tab_changed(current_main_tab_text, current_main_widget.currentIndex())
        
    def on_sub_tab_changed(self, group_name, index):
        """子标签页切换时触发，判断切换方向，并根据主题设置应用动画。"""
        active_sub_tab_widget = None
        try:
            main_tab_content_widget = None
            for i in range(self.main_tabs.count()):
                if self.main_tabs.tabText(i) == group_name:
                    main_tab_content_widget = self.main_tabs.widget(i)
                    break
            
            if main_tab_content_widget and isinstance(main_tab_content_widget, QTabWidget): 
                active_sub_tab_widget = main_tab_content_widget.widget(index)
        except Exception as e: 
             print(f"Error finding active sub-tab: {e}")

        # --- [核心修改] ---
        # 只有在动画被启用时，才执行动画逻辑
        if active_sub_tab_widget and self.animations_enabled:
            last_index = self.last_sub_tab_indices.get(group_name, -1)
            
            if last_index != -1 and index > last_index:
                direction = 'right'
            else:
                direction = 'left'
            
            self.animation_manager.slide_and_fade_in(active_sub_tab_widget, direction=direction)

        # 无论动画是否播放，都更新索引记录
        self.last_sub_tab_indices[group_name] = index

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

        # 1. 获取主题文件路径
        theme_file_path = self.config.get("theme", "默认.qss")
        if not theme_file_path: theme_file_path = "默认.qss"
        absolute_theme_path = os.path.join(THEMES_DIR, theme_file_path)
        
        # 2. 初始化主题相关状态变量
        is_compact_theme = False
        icons_disabled = False
        is_dark_theme = False # 默认不是暗色主题
        theme_icon_path_to_set = None
        override_color = None # 默认没有图标覆盖颜色

        # 记录动画状态，以便在应用新主题后恢复
        animations_were_enabled = self.animations_enabled 
        self.animations_enabled = True # 默认启用动画，如果主题禁用则会覆盖

        # 3. 读取QSS文件并解析元数据
        stylesheet = ""
        if os.path.exists(absolute_theme_path):
            try:
                with open(absolute_theme_path, "r", encoding="utf-8") as f:
                    stylesheet = f.read()
                
                # --- 解析 @icon-path ---
                icon_path_match = re.search(r'/\*\s*@icon-path:\s*"(.*?)"\s*\*/', stylesheet)
                if icon_path_match:
                    relative_icon_path_str = icon_path_match.group(1).replace("\\", "/")
                    qss_file_directory = os.path.dirname(absolute_theme_path)
                    absolute_icon_path = os.path.join(qss_file_directory, relative_icon_path_str)
                    theme_icon_path_to_set = os.path.normpath(absolute_icon_path)

                # --- 解析 @theme-type ---
                dark_match = re.search(r'/\*\s*@theme-type:\s*dark\s*\*/', stylesheet)
                if dark_match:
                    is_dark_theme = True

                # --- 解析 @icon-override-color ---
                color_match = re.search(r'/\*\s*@icon-override-color:\s*(.*?)\s*\*/', stylesheet)
                if color_match:
                    try:
                        # 尝试将匹配到的字符串转换为 QColor
                        override_color = QColor(color_match.group(1).strip())
                        if not override_color.isValid():
                            raise ValueError(f"无效的颜色值: {color_match.group(1).strip()}")
                    except Exception:
                        print(f"警告: 无法解析主题颜色 '{color_match.group(1).strip()}' (格式可能不正确，例如 #RRGGBB)。")
                        override_color = None # 解析失败则设为None

                # --- 解析 @icon-theme: none ---
                icon_theme_match = re.search(r'/\*\s*@icon-theme:\s*none\s*\*/', stylesheet)
                if icon_theme_match: 
                    icons_disabled = True
                
                # --- 解析 @theme-property-compact ---
                compact_match = re.search(r'/\*\s*@theme-property-compact:\s*true\s*\*/', stylesheet)
                if compact_match: 
                    is_compact_theme = True

                # --- 解析 @animations ---
                anim_match = re.search(r'/\*\s*@animations:\s*disabled\s*\*/', stylesheet)
                if anim_match: 
                    self.animations_enabled = False
                
            except Exception as e:
                print(f"读取或解析主题文件 '{absolute_theme_path}' 时出错: {e}", file=sys.stderr)
                stylesheet = "" # 出错时清空样式表，避免应用部分错误样式

        else:
            print(f"主题文件未找到: {absolute_theme_path}", file=sys.stderr)
            stylesheet = "" # 文件不存在时清空样式表

        # 4. 应用样式表
        self.setStyleSheet(stylesheet)

        # 5. 通知 IconManager 更新其状态
        # 即使主题文件不存在或解析失败，也需要调用这些方法来重置IconManager的状态
        self.icon_manager.set_theme_icon_path(theme_icon_path_to_set, icons_disabled=icons_disabled)
        self.icon_manager.set_theme_override_color(override_color)
        self.icon_manager.set_dark_mode(is_dark_theme)

        # 6. 调整窗口尺寸 (保持不变)
        current_size = self.size()
        target_size = None
        if is_compact_theme:
            self.setMinimumSize(self.COMPACT_MIN_SIZE[0], self.COMPACT_MIN_SIZE[1])
            target_size = QSize(self.COMPACT_MIN_SIZE[0], self.COMPACT_MIN_SIZE[1])
        else:
            self.setMinimumSize(self.DEFAULT_MIN_SIZE[0], self.DEFAULT_MIN_SIZE[1])
            new_width = max(current_size.width(), self.DEFAULT_MIN_SIZE[0])
            new_height = max(current_size.height(), self.DEFAULT_MIN_SIZE[1])
            target_size = QSize(new_width, new_height)

        if current_size != target_size:
            if self.animations_enabled:
                self.animation_manager.animate_window_resize(target_size)
            else:
                self.resize(target_size)
        
        # 7. 更新所有模块的图标 (保持不变)
        self.update_all_module_icons()
        if hasattr(self, 'plugin_menu_button'):
            self.plugin_menu_button.setIcon(self.icon_manager.get_icon("plugin"))

        # 8. 更新帮助内容（如果需要） (保持不变)
        if hasattr(self, 'help_page') and hasattr(self.help_page, 'update_help_content'):
            QTimer.singleShot(0, self.help_page.update_help_content)

    def update_all_module_icons(self):
        """
        [v1.1] 遍历所有已创建的页面和UI组件，并调用它们的图标更新方法。
        这是在主题切换后，一个集中的UI刷新入口。
        """
        # --- 原有的模块图标刷新逻辑保持不变 ---
        pages_with_icons = [
            'accent_collection_page',
            'log_viewer_page',
            'dialect_visual_collector_module', 
            'voicebank_recorder_page', 
            'audio_manager_page', 
            'wordlist_editor_page',
            'dialect_visual_editor_page', 
            'converter_page',
            'audio_analysis_page',
            'tts_utility_page',
            'flashcard_page',
            'settings_page',
        ]
        for page_attr_name in pages_with_icons:
            page = getattr(self, page_attr_name, None)
            if page and hasattr(page, 'update_icons'):
                try:
                    page.update_icons()
                except Exception as e:
                    print(f"更新模块 '{page_attr_name}' 的图标时出错: {e}")

        # [核心修改] 2. 在此方法中，增加对固定插件UI的刷新调用
        self.update_pinned_plugins_ui()

    # --- [vNext 新增] 插件交互API ---

    def _navigate_to_tab(self, main_tab_name, sub_tab_name=None):
        """
        一个通用的导航函数，用于切换到指定的主标签页和子标签页。
        :param main_tab_name: 主标签页的文本。
        :param sub_tab_name: 子标签页的文本 (可选)。
        :return: 成功则返回目标页面实例，失败则返回 None。
        """
        for i in range(self.main_tabs.count()):
            if self.main_tabs.tabText(i) == main_tab_name:
                self.main_tabs.setCurrentIndex(i)
                QApplication.processEvents() # 确保UI更新
                
                main_widget = self.main_tabs.widget(i)
                if sub_tab_name is None:
                    return main_widget

                if isinstance(main_widget, QTabWidget):
                    for j in range(main_widget.count()):
                        if main_widget.tabText(j) == sub_tab_name:
                            main_widget.setCurrentIndex(j)
                            QApplication.processEvents()
                            return main_widget.widget(j)
        return None

    def open_in_wordlist_editor(self, filepath):
        """公共API: 在正确的词表编辑器中打开一个文件。"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            file_format = data.get("meta", {}).get("format", "")
            
            target_page = None
            if file_format == "standard_wordlist":
                target_page = self._navigate_to_tab("数据准备", "通用词表编辑器")
            elif file_format == "visual_wordlist":
                target_page = self._navigate_to_tab("数据准备", "图文词表编辑器")
            
            if target_page and hasattr(target_page, 'load_file_from_path'):
                target_page.load_file_from_path(filepath)
            elif target_page is None:
                QMessageBox.warning(self, "导航失败", "无法找到对应的词表编辑器标签页。")
        except Exception as e:
            QMessageBox.critical(self, "打开失败", f"无法打开或解析词表文件:\n{e}")

    def open_in_log_viewer(self, filepath):
        """公共API: 在日志查看器中打开一个日志文件。"""
        target_page = self._navigate_to_tab("资源管理", "日志查看器")
        if target_page and hasattr(target_page, 'load_log_file_from_path'):
            target_page.load_log_file_from_path(filepath)
        elif target_page is None:
             QMessageBox.warning(self, "导航失败", "无法找到日志查看器标签页。")

    # [新增] closeEvent 方法，用于安全退出
    def closeEvent(self, event):
        """在关闭主窗口前，确保所有插件都已安全卸载。"""
        print("[主程序] 正在关闭，卸载所有插件...")
        self.plugin_manager.teardown_all_plugins()
        super().closeEvent(event)

    # [新增] 插件UI设置
    def setup_plugin_ui(self):
        self.corner_widget = QWidget()
        self.plugin_bar_layout = QHBoxLayout(self.corner_widget)
        self.plugin_bar_layout.setContentsMargins(0, 5, 15, 5)
        self.plugin_bar_layout.setSpacing(5)

        self.pinned_plugins_widget = QWidget()
        self.pinned_plugins_layout = QHBoxLayout(self.pinned_plugins_widget)
        self.pinned_plugins_layout.setContentsMargins(0, 0, 0, 0)
        self.pinned_plugins_layout.setSpacing(5)
        self.pinned_plugins_layout.setAlignment(Qt.AlignRight)

        self.plugin_menu_button = QPushButton("插件") 
        # --- [核心修改] 图标设置现在通过 icon_manager 进行，它会自动处理禁用情况 ---
        self.plugin_menu_button.setIcon(self.icon_manager.get_icon("plugin"))
        self.plugin_menu_button.setToolTip("管理和执行已安装的插件")
        self.plugin_menu_button.setObjectName("PluginMenuButtonCircular")
        self.plugin_menu_button.setFixedSize(32, 32)
        
        self.plugin_bar_layout.addWidget(self.pinned_plugins_widget)
        self.plugin_bar_layout.addWidget(self.plugin_menu_button)
        
        self.main_tabs.setCornerWidget(self.corner_widget, Qt.TopRightCorner)
        self.plugin_menu_button.clicked.connect(self._show_plugin_menu)

    def update_pinned_plugins_ui(self):
        """
        根据配置文件，清空并重新创建所有固定的插件快捷按钮。
        """
        # ... (清空和读取配置的逻辑保持不变) ...
        while self.pinned_plugins_layout.count():
            item = self.pinned_plugins_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        plugin_settings = self.config.get("plugin_settings", {})
        pinned_plugins = plugin_settings.get("pinned", [])

        for plugin_id in pinned_plugins:
            meta = self.plugin_manager.available_plugins.get(plugin_id)
            if not meta:
                continue

            btn = QPushButton()
            
            # [核心修改] 直接调用新的权威方法来获取图标
            btn.setIcon(self.plugin_manager.get_plugin_icon(plugin_id))
            
            btn.setToolTip(f"{meta['name']}")
            btn.setObjectName("PinnedPluginButton")
            btn.setFixedSize(32, 32)
            btn.clicked.connect(lambda checked, pid=plugin_id: self.plugin_manager.execute_plugin(pid))
            self.pinned_plugins_layout.addWidget(btn)

    def _show_plugin_menu(self):
        # 导入所有必要的类
        from PyQt5.QtWidgets import QMenu, QToolButton, QGridLayout, QWidget, QWidgetAction, QSizePolicy
        from PyQt5.QtCore import QPoint, Qt, QSize
        from PyQt5.QtGui import QIcon, QFontMetrics

        # --- 菜单构建逻辑 (与之前版本完全一致) ---
        menu = QMenu(self)
        self.update_pinned_plugins_ui()
        active_plugins_sorted = sorted(self.plugin_manager.active_plugins.items(), 
                                       key=lambda item: self.plugin_manager.available_plugins.get(item[0], {}).get('name', item[0]))
        num_active_plugins = len(active_plugins_sorted)
        
        if num_active_plugins == 0:
            no_plugins_action = menu.addAction("未启用插件"); no_plugins_action.setEnabled(False)
        else:
            grid_widget = QWidget(); grid_layout = QGridLayout(grid_widget)
            grid_layout.setContentsMargins(10, 10, 10, 10); grid_layout.setSpacing(10)
            PLUGINS_PER_COLUMN = 6
            num_cols = (num_active_plugins - 1) // PLUGINS_PER_COLUMN + 1 if num_active_plugins > 0 else 1
            MAX_COLUMNS = 3
            if num_cols > MAX_COLUMNS:
                num_cols = MAX_COLUMNS; PLUGINS_PER_COLUMN = (num_active_plugins - 1) // MAX_COLUMNS + 1
            for col_idx in range(num_cols): grid_layout.setColumnStretch(col_idx, 1)
            longest_plugin_name = ""
            for plugin_id, _ in active_plugins_sorted:
                meta = self.plugin_manager.available_plugins.get(plugin_id)
                if meta and len(meta['name']) > len(longest_plugin_name): longest_plugin_name = meta['name']
            font_metrics = QFontMetrics(self.font()); estimated_text_width = font_metrics.width(longest_plugin_name) 
            min_btn_width = estimated_text_width + 24 + 5 + 10;
            if min_btn_width < 100: min_btn_width = 100 
            grid_widget.setMinimumWidth(min_btn_width * num_cols + grid_layout.spacing() * (num_cols - 1) + grid_layout.contentsMargins().left() + grid_layout.contentsMargins().right())
            for i, (plugin_id, instance) in enumerate(active_plugins_sorted):
                btn = QToolButton(); btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon); btn.setAutoRaise(True) 
                btn.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Minimum); btn.setMinimumSize(QSize(min_btn_width, 36)) 
                meta = self.plugin_manager.available_plugins.get(plugin_id)
                if not meta: continue 

                # [核心修改] 直接调用新的权威方法来获取图标
                plugin_icon = self.plugin_manager.get_plugin_icon(plugin_id)
                
                btn.setIcon(plugin_icon); btn.setIconSize(QSize(24, 24)); btn.setText(meta['name']); btn.setToolTip(meta['description'])
                btn.setObjectName("PluginMenuItemToolButton") 
                btn.clicked.connect(lambda checked, pid=plugin_id: self.plugin_manager.execute_plugin(pid))
                row = i % PLUGINS_PER_COLUMN; col = (num_cols - 1) - (i // PLUGINS_PER_COLUMN)
                grid_layout.addWidget(btn, row, col)
            widget_action = QWidgetAction(menu); widget_action.setDefaultWidget(grid_widget); menu.addAction(widget_action)

        menu.addSeparator()
        manage_btn = QToolButton(); manage_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon); manage_btn.setAutoRaise(True)
        manage_btn.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
        manage_btn_width = menu.sizeHint().width() - 20;
        if manage_btn_width < 150: manage_btn_width = 150
        manage_btn.setMinimumSize(QSize(manage_btn_width, 36))
        manage_btn.setIcon(self.icon_manager.get_icon("check")); manage_btn.setIconSize(QSize(24, 24))
        manage_btn.setText("管理插件..."); manage_btn.setToolTip("打开插件管理对话框，安装、卸载、启用或禁用插件。")
        manage_btn.setObjectName("PluginMenuItemToolButton")
        manage_btn.clicked.connect(self._open_plugin_manager_dialog)
        manage_widget_action = QWidgetAction(menu); manage_widget_action.setDefaultWidget(manage_btn); menu.addAction(manage_widget_action)
        
        # --- [核心修改] 将显示和动画全权委托给 AnimationManager ---
        
        # 1. 计算最终位置
        menu_size = menu.sizeHint()
        button_bottom_right = self.plugin_menu_button.mapToGlobal(self.plugin_menu_button.rect().bottomRight())
        final_pos = QPoint(button_bottom_right.x() - menu_size.width(), button_bottom_right.y())

        # 2. 调用动画管理器来处理显示
        self.animation_manager.animate_menu(menu, final_pos)
        
        # 3. 将UI刷新连接到菜单的关闭信号
        menu.aboutToHide.connect(self.update_pinned_plugins_ui)

    # [新增] 打开插件管理对话框的逻辑
    def _open_plugin_manager_dialog(self):
        """打开插件管理对话框。"""
        dialog = PluginManagementDialog(self.plugin_manager, self)
        dialog.exec_()
    
        # 对话框关闭后，可以根据需要刷新UI，但目前菜单是动态生成的，所以无需操作。

    def update_and_save_module_state(self, module_key, key_or_value, value=None):
        """
        [v1.3 - None模式健壮版]
        更新并立即保存一个特定模块的状态到 settings.json。
        此版本使用 None 作为哨兵来区分双参数和三参数调用模式。
        """
        # [核心修复] 使用一个稳定的 None 值来判断 'value' 是否被传递
        if value is not None:
            # --- 模式1：传入了三个参数 (module_key, setting_key, value) ---
            # 即使 value 是 False 或 0，这个分支也能被正确执行

            # 确保 module_states 字典存在
            if "module_states" not in self.config:
                self.config["module_states"] = {}

            # 确保目标模块的状态是一个字典
            if not isinstance(self.config["module_states"].get(module_key), dict):
                self.config["module_states"][module_key] = {}

            setting_key = key_or_value
            self.config["module_states"][module_key][setting_key] = value
        else:
            # --- 模式2：只传入了两个参数 (module_key, settings_dict) ---
            # 这种模式下，settings_dict 应该是一个字典
            settings_dict = key_or_value
            if isinstance(settings_dict, dict):
                # 确保 module_states 字典存在
                if "module_states" not in self.config:
                    self.config["module_states"] = {}
                
                # 直接用新的字典替换旧的
                self.config["module_states"][module_key] = settings_dict
            else:
                # 警告逻辑保持不变
                print(f"警告: 尝试用非字典类型 '{type(settings_dict)}' 覆盖模块 '{module_key}' 的状态。", file=sys.stderr)
                return

        # 写入文件的逻辑保持不变
        try:
            with open(self.SETTINGS_FILE, 'w', encoding='utf-8') as f:
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
    
    icon_manager = IconManager(DEFAULT_ICON_DIR)
    
    load_modules(progress_offset=30, progress_scale=0.4)
    
    # 将 app 实例传递给 MainWindow
    window = MainWindow(app_ref=app, splash_ref=splash, tooltips_ref=tooltips_config)
    
    window.show()
    
    # --- [核心修改] 创建并启动淡出动画 ---
    
    # 1. 创建一个针对 splash 透明度的动画
    animation = QPropertyAnimation(splash, b"windowOpacity")
    animation.setDuration(100) # 动画时长 500ms
    animation.setStartValue(1.0) # 从完全不透明开始
    animation.setEndValue(0.0)   # 到完全透明结束
    animation.setEasingCurve(QEasingCurve.OutCubic) # 平滑的缓动曲线

    # 2. 当动画完成时，关闭 splash 窗口
    animation.finished.connect(splash.close)

    # 3. 启动动画
    animation.start()
    
    # --- [修改结束] ---
    
    sys.exit(app.exec_())