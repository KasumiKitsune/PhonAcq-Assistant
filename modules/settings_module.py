# --- START OF FILE modules/settings_module.py ---

# --- 模块元数据 ---
# 定义模块的名称和描述，用于在应用程序中显示在标签页上。
MODULE_NAME = "程序设置"
MODULE_DESCRIPTION = "调整应用的各项参数，包括UI布局、音频设备、TTS默认设置和主题皮肤等。"
# ---

import os
import sys
import json
import shutil # 用于文件操作，如复制和删除模块文件
import threading
import queue
from collections import deque

# 尝试导入 numpy
try:
    import numpy as np
except ImportError:
    # 如果 numpy 缺失，可以创建一个 Mock 对象，但测试功能将不可用
    class MockNumpy:
        def linalg(self): return self
        def norm(self, _): return 0
        def sqrt(self, _): return 1
        def clip(self, data, *args): return data
    np = MockNumpy()
    print("WARNING: numpy library not found. Audio test functionality will be degraded.")
# PyQt5 GUI 库的核心组件导入
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QFileDialog, QMessageBox, QComboBox, QFormLayout, 
    QGroupBox, QLineEdit, QSlider, QSpacerItem, QSizePolicy,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QAbstractItemView, QDialogButtonBox, QDialog, QMenu, QScrollArea, QStackedWidget, QListWidget, QListWidgetItem, QGridLayout # 新增QMenu, QScrollArea
)
from PyQt5.QtGui import QIntValidator, QColor, QBrush, QIcon, QPalette, QPixmap, QPainter
from PyQt5.QtCore import Qt, QTimer, QSize, pyqtSignal, QEasingCurve, QPropertyAnimation, pyqtProperty
from modules.custom_widgets_module import AnimatedSlider
# 尝试导入 sounddevice 库用于音频设备检测，如果失败则使用 Mock 对象以避免程序崩溃
try:
    import sounddevice as sd
    import soundfile as sf
except ImportError:
    class MockSoundDevice:
        def query_devices(self): return []
        @property
        def default(self):
            class MockDefault: device = [-1, -1]
            return MockDefault()
    sd = MockSoundDevice()
    sf = None
    print("WARNING: sounddevice library not found. Audio device settings will be unavailable.")

def get_base_path_for_module():
    """
    获取 PhonAcq Assistant 项目的根目录路径。
    此函数兼容程序被 PyInstaller 打包后运行和从源代码直接运行两种情况。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        # 当前文件位于 '项目根目录/modules/'，需要向上返回一级目录
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def create_page(parent_window, ToggleSwitchClass, THEMES_DIR, WORD_LIST_DIR, resolve_device_func):
    """
    创建并返回设置页面的工厂函数。
    被主程序调用以实例化模块。
    Args:
        parent_window (QMainWindow): 主应用程序窗口实例。
        ToggleSwitchClass (class): 自定义 ToggleSwitch 控件的类。
        THEMES_DIR (str): 主题文件目录的路径。
        WORD_LIST_DIR (str): 词表文件目录的路径。
    Returns:
        SettingsPage: 设置页面实例。
    """
    return SettingsPage(parent_window, ToggleSwitchClass, THEMES_DIR, WORD_LIST_DIR, resolve_device_func) # <-- 传递给构造函数
# ==============================================================================
#   内部自定义控件：AnimatedLogoLabel
# ==============================================================================
class AnimatedLogoLabel(QLabel):
    """
    一个专门用于“关于”页面的、支持悬停和点击缩放动画的Logo标签。
    v2.0: 修复了放大动画时边缘被裁切的问题。
    """
    # [核心修复 1] 定义一个常量来控制最大缩放，方便维护
    MAX_HOVER_SCALE = 1.1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignCenter)
        
        self._base_pixmap = QPixmap()
        self._scale = 1.0

        self.scale_animation = QPropertyAnimation(self, b"_scale")
        self.scale_animation.setDuration(150)
        self.scale_animation.setEasingCurve(QEasingCurve.OutCubic)

    def setPixmap(self, pixmap):
        """
        重写 setPixmap。我们存储 pixmap，并通知布局系统重新计算尺寸。
        """
        self._base_pixmap = pixmap
        # [核心修复 2] 移除 setFixedSize，改用 updateGeometry
        # 这会触发对 sizeHint 的重新查询，让布局系统分配正确的空间
        self.updateGeometry()
        self.update()

    # [核心修复 3] 重写 sizeHint 和 minimumSizeHint
    def sizeHint(self):
        """告诉布局系统此控件的理想尺寸是其最大动画状态下的尺寸。"""
        if self._base_pixmap.isNull():
            return super().sizeHint()
        
        # QSize 对象支持与浮点数相乘
        return self._base_pixmap.size() * self.MAX_HOVER_SCALE

    def minimumSizeHint(self):
        """最小尺寸应与理想尺寸相同，以保证动画空间始终被保留。"""
        return self.sizeHint()

    @pyqtProperty(float)
    def _scale(self):
        return self.__scale
    
    @_scale.setter
    def _scale(self, value):
        self.__scale = value
        self.update()

    def paintEvent(self, event):
        """
        paintEvent 逻辑保持不变，它现在会在一个更大的、由 sizeHint
        保证的画布 (self.rect()) 内进行绘制。
        """
        if self._base_pixmap.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        
        center = self.rect().center()
        
        painter.translate(center)
        painter.scale(self._scale, self._scale)
        painter.translate(-center)
        
        target_rect = self._base_pixmap.rect()
        target_rect.moveCenter(self.rect().center())

        painter.drawPixmap(target_rect, self._base_pixmap)

    # --- 事件处理方法保持不变 ---
    def enterEvent(self, event):
        self.scale_animation.stop()
        self.scale_animation.setEndValue(self.MAX_HOVER_SCALE) # 使用常量
        self.scale_animation.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.scale_animation.stop()
        self.scale_animation.setEndValue(1.0)
        self.scale_animation.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.scale_animation.stop()
            self.scale_animation.setEndValue(0.9)
            self.scale_animation.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.scale_animation.stop()
            target_scale = self.MAX_HOVER_SCALE if self.underMouse() else 1.0
            self.scale_animation.setEndValue(target_scale)
            self.scale_animation.start()
        super().mouseReleaseEvent(event)

class SettingsPage(QWidget):
    """
    程序设置页面。
    允许用户调整UI布局、音频设备、TTS默认设置、主题皮肤，并管理核心模块。
    UI采用左侧导航栏和右侧内容区的双栏布局。
    """
    device_name_resolved = pyqtSignal(str)
    def __init__(self, parent_window, ToggleSwitchClass, THEMES_DIR, WORD_LIST_DIR, resolve_device_func):
        super().__init__()
        self.parent_window = parent_window
        self.ToggleSwitch = ToggleSwitchClass
        self.THEMES_DIR = THEMES_DIR
        self.WORD_LIST_DIR = WORD_LIST_DIR
        self.resolve_device_func = resolve_device_func 
        self.icon_manager = self.parent_window.icon_manager
        self.is_testing_mic = False
        self.test_mic_thread = None
        self.test_mic_stop_event = threading.Event()
        # 使用一个专用的队列，避免与任何其他模块冲突
        self.test_mic_volume_queue = queue.Queue(maxsize=2)
        # 用于平滑音量计显示的双端队列
        self.test_mic_volume_history = deque(maxlen=5)
        # 用于更新音量计UI的定时器
        self.test_mic_update_timer = QTimer()
        # --- 新增：用于录制和回放的状态变量 ---
        self.test_mic_audio_chunks = []  # 用于累积测试时的音频数据块
        self.last_test_recording = None  # 用于存储最后一次完整的测试录音 (numpy array)
        # --- [核心新增] 播放器所需的状态变量 ---
        self.is_playing_back = False
        self.playback_update_timer = QTimer()
        self.playback_start_time = 0
        self.playback_duration_ms = 0
        self._init_ui()
        self._connect_signals()
        self.update_icons()
    
    def _init_ui(self):
        """
        [v2.2 - 多页面版] 构建页面的用户界面布局。
        此版本将设置项拆分为多个独立的页面，并通过左侧导航栏进行切换。
        """
        # --- 主布局：垂直布局，顶部是水平内容区，底部是配置管理按钮 ---
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # --- 内容区布局：水平分割，左侧为导航，右侧为页面 ---
        content_layout = QHBoxLayout()
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addLayout(content_layout, 1) # 内容区占据大部分垂直空间

        # --- 1. 左侧导航栏 (QListWidget) ---
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(250) # 设置导航栏宽度
        self.nav_list.setObjectName("SettingsNavList") # 设置对象名以便QSS样式化
        self.nav_list.setIconSize(QSize(36, 36)) # 设置图标大小
        content_layout.addWidget(self.nav_list)
        # 为列表项设置样式，增加高度和内边距
        self.nav_list.setStyleSheet("""
            QListWidget#SettingsNavList::item {
                min-height: 35px;
                padding-left: 10px;
            }
        """)
        
        # 添加带图标的导航项
        general_item = QListWidgetItem(self.icon_manager.get_icon("settings"), "  常规设置")
        audio_item = QListWidgetItem(self.icon_manager.get_icon("wav"), "  音频设置")
        module_item = QListWidgetItem(self.icon_manager.get_icon("modules"), "  模块管理")
        about_item = QListWidgetItem(self.icon_manager.get_icon("info"), "  关于")
        
        self.nav_list.addItem(general_item)
        self.nav_list.addItem(audio_item)
        self.nav_list.addItem(module_item)
        self.nav_list.addItem(about_item)

        # --- 2. 右侧内容区 (QStackedWidget) ---
        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1) # 占据剩余水平空间

        # --- 3. 创建并添加各个设置页面到 QStackedWidget ---
        # 依次调用辅助方法来创建每个页面
        self._create_general_settings_page()
        self._create_audio_settings_page()
        self._create_module_management_page()
        self._create_about_page()

        # --- 底部统一的“配置管理”按钮组 ---
        config_management_group = QGroupBox("配置管理")
        config_management_layout = QHBoxLayout(config_management_group)
        
        self.restore_defaults_btn = QPushButton("恢复默认设置")
        self.import_settings_btn = QPushButton("导入配置...")
        self.export_settings_btn = QPushButton("导出配置...")
        self.save_btn = QPushButton("保存所有设置")
        
        # 为按钮设置对象名和工具提示
        self.restore_defaults_btn.setObjectName("ActionButton_Delete")
        self.restore_defaults_btn.setToolTip("将所有设置恢复到程序初始状态，此操作将删除您当前的配置文件，且不可撤销。")
        self.import_settings_btn.setToolTip("从外部JSON文件导入之前导出的设置。")
        self.export_settings_btn.setToolTip("将当前所有设置导出为一个JSON文件，方便备份或在其他设备上使用。")
        self.save_btn.setToolTip("保存并应用所有修改后的设置。")
        self.save_btn.setEnabled(False) # 初始禁用

        # 将按钮添加到布局中
        config_management_layout.addWidget(self.restore_defaults_btn)
        config_management_layout.addStretch()
        config_management_layout.addWidget(self.import_settings_btn)
        config_management_layout.addWidget(self.export_settings_btn)
        config_management_layout.addWidget(self.save_btn)
        
        main_layout.addWidget(config_management_group) # 添加到主布局底部

    def update_icons(self):
        """
        [新增] 刷新此页面上所有控件的图标，以响应主题变化。
        """
        # 1. 刷新导航列表的图标
        self.nav_list.item(0).setIcon(self.icon_manager.get_icon("settings"))
        self.nav_list.item(1).setIcon(self.icon_manager.get_icon("audio"))
        self.nav_list.item(2).setIcon(self.icon_manager.get_icon("modules"))
        self.nav_list.item(3).setIcon(self.icon_manager.get_icon("info"))

        # 2. 刷新配置管理按钮的图标
        self.restore_defaults_btn.setIcon(self.icon_manager.get_icon("reset"))
        self.import_settings_btn.setIcon(self.icon_manager.get_icon("import"))
        self.export_settings_btn.setIcon(self.icon_manager.get_icon("export"))
        self.save_btn.setIcon(self.icon_manager.get_icon("save_all"))

        # 3. 刷新“模块管理”页面的按钮
        self.add_module_btn.setIcon(self.icon_manager.get_icon("add_row"))
        self.module_settings_btn.setIcon(self.icon_manager.get_icon("settings"))
        self.remove_module_btn.setIcon(self.icon_manager.get_icon("delete"))
        
        # 4. 刷新“关于”页面的按钮
        if hasattr(self, 'github_btn'): # 检查按钮是否已创建
            self.github_btn.setIcon(self.icon_manager.get_icon("github"))
            self.report_bug_btn.setIcon(self.icon_manager.get_icon("bug"))
            self.manual_btn.setIcon(self.icon_manager.get_icon("help"))
            self.check_update_btn.setIcon(self.icon_manager.get_icon("refresh"))

        # 5. 重新填充模块表格以刷新其内部图标
        self.populate_module_table()
        # 6. 刷新音频测试按钮的图标
        if hasattr(self, 'test_mic_btn'):
            if self.is_testing_mic:
                self.test_mic_btn.setIcon(self.icon_manager.get_icon("stop"))
            else:
                self.test_mic_btn.setIcon(self.icon_manager.get_icon("record"))
        # 7. 刷新音频测试和回放按钮的图标
        if hasattr(self, 'test_mic_btn'):
            if self.is_testing_mic:
                self.test_mic_btn.setIcon(self.icon_manager.get_icon("stop"))
            else:
                self.test_mic_btn.setIcon(self.icon_manager.get_icon("record"))
            self.playback_test_btn.setIcon(self.icon_manager.get_icon("play"))
        # 8. 重新计算右侧按钮的状态（这会刷新 toggle_enabled_btn 的图标）
        self._update_module_buttons_state()

    def _create_about_page(self):
        """
        [v2.1 - 内容与功能增强版] 创建“关于”页面。
        此版本更新了鸣谢列表，修复了HTML代码显示问题，并实现了本地手册的打开功能。
        同时，将交互式按钮提升为实例属性，以便 update_icons() 可以刷新它们。
        """
        # --- 1. 创建主容器和布局 ---
        page = QWidget()
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(page)
        scroll_area.setObjectName("SettingsScrollArea")
        scroll_area.setStyleSheet("QScrollArea#SettingsScrollArea { border: none; }")

        # 使用一个包装布局来实现垂直和水平居中
        page_layout = QHBoxLayout(page)
        page_layout.addStretch() # 左侧弹簧

        # 内容容器，固定宽度以保证在宽屏下的可读性
        content_container = QWidget()
        content_container.setFixedWidth(700)
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(20) # 各个卡片之间的间距

        # --- 2. 顶部应用信息卡片 ---
        app_info_group = QGroupBox()
        app_info_group.setObjectName("CardGroup")
        app_info_layout = QHBoxLayout(app_info_group)
        app_info_layout.setSpacing(30)
        
        # --- [核心修改] 使用我们新的 AnimatedLogoLabel 类 ---
        logo_label = AnimatedLogoLabel()
        # --- [修改结束] ---
        
        custom_logo_path = os.path.join(get_base_path_for_module(), "assets", "logo.png")
        
        logo_pixmap = QPixmap()
        if os.path.exists(custom_logo_path):
            logo_pixmap.load(custom_logo_path)
        else:
            app_icon = self.parent_window.windowIcon()
            logo_pixmap = app_icon.pixmap(QSize(128, 128))
        
        # 将 pixmap 缩放到统一尺寸并设置给我们的动画标签
        final_pixmap = logo_pixmap.scaled(QSize(128, 128), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        logo_label.setPixmap(final_pixmap)
        
        app_info_layout.addWidget(logo_label)

        # 右侧文本信息
        text_info_layout = QVBoxLayout()
        text_info_layout.setSpacing(5)
        
        title_label = QLabel("PhonAcq Assistant")
        title_label.setObjectName("AboutTitleLabel") # 用于QSS样式化
        
        version_str = "v1.7.0" # 示例版本信息
        version_label = QLabel(f"版本: {version_str}")
        version_label.setObjectName("SubtleStatusLabel")
        
        copyright_label = QLabel("© 2025 KasumiKitsune. All Rights Reserved.")
        
        text_info_layout.addWidget(title_label)
        text_info_layout.addWidget(version_label)
        text_info_layout.addStretch()
        text_info_layout.addWidget(copyright_label)
        
        app_info_layout.addLayout(text_info_layout, 1) # 文本部分占据伸缩空间
        content_layout.addWidget(app_info_group)

        # --- 3. 链接与资源卡片 ---
        links_group = QGroupBox("链接与资源")
        links_group.setObjectName("CardGroup")
        links_layout = QGridLayout(links_group) # 使用网格布局
        
        # [核心修改] 将按钮提升为实例属性 (self.xxx_btn)
        self.github_btn = QPushButton("  项目主页")
        self.report_bug_btn = QPushButton("  报告问题")
        self.manual_btn = QPushButton("  查看手册")
        self.check_update_btn = QPushButton("  检查更新")
        
        # 连接信号
        self.github_btn.clicked.connect(lambda: self._open_link("https://github.com/KasumiKitsune/PhonAcq-Assistant"))
        self.report_bug_btn.clicked.connect(lambda: self._open_link("https://github.com/KasumiKitsune/PhonAcq-Assistant/issues"))
        self.manual_btn.clicked.connect(self._open_manual)
        
        # 暂时禁用“检查更新”按钮
        self.check_update_btn.setToolTip("此功能将在未来版本中实现。")
        self.check_update_btn.setEnabled(False)

        # 将按钮添加到网格布局中
        links_layout.addWidget(self.github_btn, 0, 0)
        links_layout.addWidget(self.report_bug_btn, 0, 1)
        links_layout.addWidget(self.manual_btn, 1, 0)
        links_layout.addWidget(self.check_update_btn, 1, 1)

        content_layout.addWidget(links_group)
        
        # --- 4. 鸣谢卡片 (核心修改) ---
        acknowledgements_group = QGroupBox("鸣谢")
        acknowledgements_group.setObjectName("CardGroup")
        ack_layout = QVBoxLayout(acknowledgements_group)
        
        # [核心修改] 更新鸣谢文本，为每个项目添加超链接
        ack_text = (
            "本软件的开发离不开以下优秀的开源项目：<br><br>"
            "• <b>核心库:</b> "
            "<a href='https://www.riverbankcomputing.com/software/pyqt/intro'>PyQt5</a>, "
            "<a href='https://librosa.org/'>librosa</a>, "
            "<a href='https://numpy.org/'>NumPy</a>, "
            "<a href='https://pandas.pydata.org/'>Pandas</a>, "
            "<a href='https://python-sounddevice.readthedocs.io/'>sounddevice</a>, "
            "<a href='https://python-soundfile.readthedocs.io/'>soundfile</a>, "
            "<a href='https://openpyxl.readthedocs.io/'>openpyxl</a>, "
            "<a href='https://github.com/giampaolo/psutil'>psutil</a>"
            "<br>"
            "• <b>辅助工具:</b> "
            "<a href='https://gtts.readthedocs.io/'>gTTS</a>, "
            "<a href='https://github.com/mozillazg/python-pinyin'>pypinyin</a>, "
            "<a href='https://daringfireball.net/projects/markdown/'>Markdown</a>, "
            "<a href='https://requests.readthedocs.io/'>Requests</a>, "
            "<a href='https://textgridtools.readthedocs.io/'>textgrid</a>, "
            "<a href='https://github.com/seatgeek/thefuzz'>thefuzz</a>"
            "<br>"
            "• <b>图标集:</b> Material Rounded, Glyph Neue (Icons by <a href='https://icons8.com/'>Icons8</a>)"
            "<br><br>"
            "以及所有在 <code>requirements.txt</code> 中列出的依赖库。"
        )
        ack_label = QLabel(ack_text)
        
        ack_label.setTextFormat(Qt.RichText)
        ack_label.setWordWrap(True)
        # [核心修改] 确保QLabel可以处理超链接点击事件
        ack_label.setOpenExternalLinks(True)
        
        ack_layout.addWidget(ack_label)
        content_layout.addWidget(acknowledgements_group)
        
        content_layout.addStretch()

        page_layout.addWidget(content_container)
        page_layout.addStretch()

        self.stack.addWidget(scroll_area)


    def _open_manual(self):
        """
        [新增] 查找并尝试打开项目根目录下的 "PhonAcq手册.pdf"。
        """
        try:
            # 使用 get_base_path_for_module() 来安全地获取项目根目录
            base_path = get_base_path_for_module()
            manual_path = os.path.join(base_path, "PhonAcq手册.pdf")
            
            if os.path.exists(manual_path):
                # 如果文件存在，则使用 QDesktopServices 打开它
                from PyQt5.QtGui import QDesktopServices
                from PyQt5.QtCore import QUrl
                QDesktopServices.openUrl(QUrl.fromLocalFile(manual_path))
            else:
                # 如果文件不存在，给用户一个明确的提示
                QMessageBox.information(self, "手册未找到", f"无法在以下路径找到手册文件：\n{manual_path}")
        except Exception as e:
            QMessageBox.critical(self, "打开失败", f"打开手册时发生错误：\n{e}")

    def _open_link(self, url_str):
        """
        [新增] 一个安全的辅助方法，用于在用户的默认浏览器中打开URL。
        """
        from PyQt5.QtGui import QDesktopServices
        from PyQt5.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url_str))

    def _create_general_settings_page(self):
        """
        [v2.1] 创建“常规设置”页面，包含UI布局、文件路径和TTS设置。
        增加了左右外边距以改善布局。
        """
        page = QWidget()
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(page)
        scroll_area.setObjectName("SettingsScrollArea")
        scroll_area.setStyleSheet("QScrollArea#SettingsScrollArea { border: none; }")
        
        # 使用一个包装布局来增加左右外边距
# --- 页面主布局 (QHBoxLayout，用于水平居中) ---
        page_layout = QHBoxLayout(page)
        page_layout.setContentsMargins(20, 10, 20, 10)

        # --- 内容容器 (QWidget + QVBoxLayout) ---
        # 创建一个垂直布局来容纳所有设置组
        content_container = QWidget()
        content_container.setMinimumWidth(700)
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(15)

        # --- 1. 界面与外观组 ---
        ui_appearance_group = QGroupBox("界面与外观")
        ui_appearance_form_layout = QFormLayout(ui_appearance_group)
        
        self.collector_width_slider = QSlider(Qt.Horizontal)
        self.collector_width_slider.setRange(200, 600)
        self.collector_width_slider.setToolTip("设置采集类页面右侧边栏的宽度。")
        self.collector_width_label = QLabel("350 px")
        collector_width_layout = QHBoxLayout(); collector_width_layout.addWidget(self.collector_width_slider); collector_width_layout.addWidget(self.collector_width_label)
        ui_appearance_form_layout.addRow("采集类页面侧边栏宽度:", collector_width_layout)
        
        self.editor_width_slider = QSlider(Qt.Horizontal)
        self.editor_width_slider.setRange(200, 600)
        self.editor_width_slider.setToolTip("设置管理/编辑类页面左侧边栏的宽度。")
        self.editor_width_label = QLabel("320 px")
        editor_width_layout = QHBoxLayout(); editor_width_layout.addWidget(self.editor_width_slider); editor_width_layout.addWidget(self.editor_width_label)
        ui_appearance_form_layout.addRow("管理类页面侧边栏宽度:", editor_width_layout)
        
        self.theme_combo = QComboBox()
        self.theme_combo.setToolTip("选择应用程序的视觉主题。")
        self.compact_mode_switch = self.ToggleSwitch()
        self.compact_mode_switch.setToolTip("切换当前主题的标准版与紧凑版。")
        theme_layout = QHBoxLayout(); theme_layout.addWidget(self.theme_combo, 1); theme_layout.addWidget(QLabel("标准")); theme_layout.addWidget(self.compact_mode_switch); theme_layout.addWidget(QLabel("紧凑"))
        ui_appearance_form_layout.addRow("主题皮肤:", theme_layout)
        
        self.hide_tooltips_switch = self.ToggleSwitch()
        hide_tooltips_layout = QHBoxLayout(); hide_tooltips_layout.addWidget(self.hide_tooltips_switch); hide_tooltips_layout.addStretch()
        ui_appearance_form_layout.addRow("隐藏Tab文字提示:", hide_tooltips_layout)
        
        content_layout.addWidget(ui_appearance_group)

        # --- 2. 文件与路径组 ---
        file_group = QGroupBox("文件与路径")
        file_layout = QFormLayout(file_group)
        self.results_dir_input = QLineEdit()
        self.results_dir_btn = QPushButton("...")
        results_dir_layout = QHBoxLayout(); results_dir_layout.addWidget(self.results_dir_input); results_dir_layout.addWidget(self.results_dir_btn)
        file_layout.addRow("结果文件夹:", results_dir_layout)
        
        self.participant_name_input = QLineEdit()
        file_layout.addRow("默认被试者名称:", self.participant_name_input)
        
        self.enable_logging_switch = self.ToggleSwitch()
        enable_logging_layout = QHBoxLayout(); enable_logging_layout.addWidget(self.enable_logging_switch); enable_logging_layout.addStretch()
        file_layout.addRow("启用详细日志记录:", enable_logging_layout)
        
        content_layout.addWidget(file_group)

        # --- 3. gTTS (在线) 设置组 (已移至此处) ---
        gtts_group = QGroupBox("gTTS (在线) 设置")
        gtts_layout = QFormLayout(gtts_group)
        self.gtts_lang_combo = QComboBox()
        self.gtts_lang_combo.addItems(['en-us','en-uk','en-au','en-in','zh-cn','ja','fr-fr','de-de','es-es','ru','ko'])
        gtts_layout.addRow("默认语言 (无指定时):", self.gtts_lang_combo)
        
        self.gtts_auto_detect_switch = self.ToggleSwitch()
        auto_detect_layout = QHBoxLayout(); auto_detect_layout.addWidget(self.gtts_auto_detect_switch); auto_detect_layout.addStretch()
        gtts_layout.addRow("自动检测语言 (中/日等):", auto_detect_layout)
        
        content_layout.addWidget(gtts_group)

        # 添加一个垂直弹簧，确保所有组都靠上对齐
        content_layout.addStretch()

        # --- 将内容容器添加到居中布局中 ---
        page_layout.addStretch()
        page_layout.addWidget(content_container)
        page_layout.addStretch()

        self.stack.addWidget(scroll_area)

    def _create_audio_settings_page(self):
        """
        [v3.0 - 布局优化版]
        创建“音频设置”页面。此版本将UI拆分为两个独立的、逻辑清晰的组：
        一个用于配置持久化设置，另一个用于即时设备测试和回放。
        """
        # --- 1. 创建顶层容器和滚动区域，确保内容可滚动 ---
        page = QWidget()
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(page)
        scroll_area.setObjectName("SettingsScrollArea")
        scroll_area.setStyleSheet("QScrollArea#SettingsScrollArea { border: none; }")

        # --- 2. 创建一个水平居中的包装布局 ---
        # 这使得所有内容在宽屏上也能保持一个舒适的阅读宽度。
        wrapper_layout = QHBoxLayout(page)
        wrapper_layout.setContentsMargins(20, 10, 20, 10)
        wrapper_layout.addStretch() # 左侧弹簧

        # --- 3. 创建一个垂直布局来容纳所有设置组 ---
        content_container = QWidget()
        content_container.setMinimumWidth(700) # 保证最小宽度
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(15) # 设置组与组之间的垂直间距

        # --- 组 1: 音频与录音 (持久化设置) ---
        audio_group = QGroupBox("音频与录音")
        audio_layout = QFormLayout(audio_group)

        # 录音设备模式开关
        self.simple_mode_switch = self.ToggleSwitch()
        self.simple_mode_switch.setToolTip("开启后，将提供简化的设备选项，方便非专业用户使用。")
        simple_mode_layout = QHBoxLayout()
        simple_mode_layout.addWidget(QLabel("专家模式"))
        simple_mode_layout.addWidget(self.simple_mode_switch)
        simple_mode_layout.addWidget(QLabel("简易模式"))
        simple_mode_layout.addStretch()
        audio_layout.addRow("录音设备模式:", simple_mode_layout)

        # 录音设备选择
        self.input_device_combo = QComboBox()
        self.input_device_combo.setToolTip("选择用于录制音频的麦克风设备。")
        audio_layout.addRow("录音设备:", self.input_device_combo)

        # 录音保存格式
        self.recording_format_switch = self.ToggleSwitch()
        self.recording_format_switch.setToolTip("选择录音文件的保存格式。\nWAV提供最佳质量但文件大，MP3压缩率高但可能需要额外编码器。")
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("WAV (高质量)"))
        format_layout.addWidget(self.recording_format_switch)
        format_layout.addWidget(QLabel("MP3 (高压缩)"))
        audio_layout.addRow("录音保存格式:", format_layout)

        # 采样率
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(["44100 Hz (CD质量, 推荐)","48000 Hz (录音室质量)","22050 Hz (中等质量)","16000 Hz (语音识别常用)"])
        self.sample_rate_combo.setToolTip("设置录音的采样率。")
        audio_layout.addRow("采样率:", self.sample_rate_combo)

        # 通道数
        self.channels_combo = QComboBox()
        self.channels_combo.addItems(["1 (单声道, 推荐)","2 (立体声)"])
        self.channels_combo.setToolTip("设置录音通道数。")
        audio_layout.addRow("通道:", self.channels_combo)

        # 录音音量增益
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setRange(5, 50)
        self.gain_slider.setValue(10)
        self.gain_slider.setToolTip("调整录音的数字音量增益。")
        self.gain_label = QLabel("1.0x")
        gain_layout = QHBoxLayout()
        gain_layout.addWidget(self.gain_slider)
        gain_layout.addWidget(self.gain_label)
        audio_layout.addRow("录音音量增益:", gain_layout)

        # 播放缓存容量
        self.player_cache_slider = QSlider(Qt.Horizontal)
        self.player_cache_slider.setRange(3, 20)
        self.player_cache_slider.setValue(5)
        self.player_cache_slider.setToolTip("设置在“音频数据管理器”中预加载到内存的音频文件数量。")
        self.player_cache_label = QLabel("5 个文件")
        cache_layout = QHBoxLayout()
        cache_layout.addWidget(self.player_cache_slider)
        cache_layout.addWidget(self.player_cache_label)
        audio_layout.addRow("播放缓存容量:", cache_layout)

        content_layout.addWidget(audio_group) # 将音频设置组添加到垂直容器中

        # --- 组 2: 即时设备测试 ---
        test_group = QGroupBox("即时设备测试")
        test_layout = QGridLayout(test_group)
        test_layout.setColumnStretch(1, 1)

        # Row 0: 状态提示
        self.test_mic_status_label = QLabel("● 未在测试")
        self.test_mic_status_label.setObjectName("SubtleStatusLabel")
        test_layout.addWidget(self.test_mic_status_label, 0, 0, 1, 2)

        # Row 1: 录制控制
        self.test_mic_btn = QPushButton("测试麦克风")
        self.test_mic_btn.setToolTip("点击开始/停止测试，以验证当前选中的音频设备和增益设置。")
        self.test_mic_volume_meter = QProgressBar()
        self.test_mic_volume_meter.setRange(0, 100); self.test_mic_volume_meter.setValue(0); self.test_mic_volume_meter.setTextVisible(False)
        test_layout.addWidget(self.test_mic_btn, 1, 0)

        # 音量计包裹容器
        volume_meter_container = QWidget()
        volume_meter_layout = QHBoxLayout(volume_meter_container)
        volume_meter_layout.setContentsMargins(0, 0, 0, 0)
        volume_meter_layout.addStretch(1) # 左侧弹簧，占1份空间
        # --- [核心修改 1] 为音量计设置一个拉伸因子 ---
        volume_meter_layout.addWidget(self.test_mic_volume_meter, 3) # 音量计本身，占2份空间
        volume_meter_layout.addStretch(1) # 右侧弹簧，占1份空间
        test_layout.addWidget(volume_meter_container, 1, 1)

        # Row 2: 回放控制
        self.playback_test_btn = QPushButton("回放")
        self.playback_test_btn.setToolTip("播放上一次测试录制的音频。")
        self.playback_test_btn.setEnabled(False)
        self.playback_slider = AnimatedSlider(Qt.Horizontal)
        self.playback_slider.setRange(0, 100); self.playback_slider.setValue(0); self.playback_slider.setEnabled(False)
        test_layout.addWidget(self.playback_test_btn, 2, 0)

        # 播放滑块包裹容器
        playback_slider_container = QWidget()
        playback_slider_layout = QHBoxLayout(playback_slider_container)
        playback_slider_layout.setContentsMargins(0, 0, 0, 0)
        playback_slider_layout.addStretch(1) # 左侧弹簧，占1份空间
        # --- [核心修改 2] 为播放滑块设置一个拉伸因子 ---
        playback_slider_layout.addWidget(self.playback_slider, 3) # 播放滑块本身，占2份空间
        playback_slider_layout.addStretch(1) # 右侧弹簧，占1份空间
        test_layout.addWidget(playback_slider_container, 2, 1)
        
        content_layout.addWidget(test_group)

        # --- 4. 最终布局 (保持不变) ---
        content_layout.addStretch()
        wrapper_layout.addWidget(content_container)
        wrapper_layout.addStretch()

        # --- 5. 添加到堆栈 (保持不变) ---
        self.stack.addWidget(scroll_area)

    def _create_module_management_page(self):
        """
        创建“模块管理”页面。
        此页面采用左右双栏布局，左侧为可滚动的模块列表，右侧为上下文操作按钮。
        """
        # --- 1. 创建页面主容器和布局 ---
        page = QWidget()
        page_layout = QVBoxLayout(page)
        # 为整个页面添加一些内边距，使其看起来不那么拥挤
        page_layout.setContentsMargins(10, 10, 10, 10) 
        
        # --- 2. 创建水平布局，用于分割列表和按钮 ---
        content_layout = QHBoxLayout()
        page_layout.addLayout(content_layout) # 将水平布局添加到主布局中

        # --- 3. 创建左侧的模块表格 ---
        self.module_table = QTableWidget()
        self.module_table.setColumnCount(3)
        self.module_table.setHorizontalHeaderLabels(["状态", "模块名称", "描述"])
        self.module_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.module_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive) # 允许用户拖动调整宽度
        self.module_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch) # 描述列自动拉伸
        self.module_table.setColumnWidth(1, 200) # 给“模块名称”列一个合理的初始宽度
        self.module_table.setSelectionBehavior(QAbstractItemView.SelectRows) # 整行选择
        self.module_table.setEditTriggers(QAbstractItemView.NoEditTriggers) # 不允许直接编辑
        self.module_table.setContextMenuPolicy(Qt.CustomContextMenu) # 启用右键菜单
        self.module_table.setAlternatingRowColors(True) # 隔行变色
        
        content_layout.addWidget(self.module_table, 1) # 添加到水平布局，并设置为可伸缩

        # --- 4. 创建右侧的按钮面板 ---
        button_panel = QVBoxLayout()
        button_panel.setContentsMargins(10, 0, 0, 0) # 左侧留出与表格的间距
        button_panel.setSpacing(8) # 按钮之间的垂直间距

        # “添加模块”按钮
        self.add_module_btn = QPushButton(" 添加模块...")
        self.add_module_btn.setIcon(self.icon_manager.get_icon("add_row"))
        self.add_module_btn.setToolTip("从本地文件系统添加一个新的模块文件。")
        
        # “模块设置”按钮
        self.module_settings_btn = QPushButton(" 模块设置...")
        self.module_settings_btn.setIcon(self.icon_manager.get_icon("settings"))
        self.module_settings_btn.setToolTip("打开当前选中模块的专属设置页面（如果可用）。")
        
        # “启用/禁用”按钮 (文本和图标将动态改变)
        self.toggle_enabled_btn = QPushButton(" 启用/禁用")
        self.toggle_enabled_btn.setToolTip("切换当前选中模块的启用状态。")
        
        # “卸载模块”按钮
        self.remove_module_btn = QPushButton(" 卸载模块...")
        self.remove_module_btn.setIcon(self.icon_manager.get_icon("delete"))
        self.remove_module_btn.setObjectName("ActionButton_Delete") # 用于QSS样式
        self.remove_module_btn.setToolTip("从磁盘上永久删除选中的模块文件。")

        # 将按钮添加到垂直布局中
        button_panel.addWidget(self.add_module_btn)
        button_panel.addWidget(self.module_settings_btn)
        button_panel.addWidget(self.toggle_enabled_btn)
        button_panel.addWidget(self.remove_module_btn)
        
        button_panel.addStretch() # 弹簧将下方的提示信息推到底部

        # 重启提示标签
        self.restart_info_label = QLabel("<b>注意:</b> 更改模块状态后\n需要<b>重启程序</b>才能生效。")
        self.restart_info_label.setObjectName("SubtleStatusLabel")
        self.restart_info_label.setWordWrap(True) # 允许文本换行
        button_panel.addWidget(self.restart_info_label)
        
        # 将按钮面板添加到水平布局中
        content_layout.addLayout(button_panel)
        
        # --- 5. 将整个页面添加到 QStackedWidget 中 ---
        self.stack.addWidget(page)

    def _update_module_buttons_state(self):
        """[v2.1] 根据当前表格的选择，更新右侧模块操作按钮的启用状态和文本。"""
        selected_rows = self.module_table.selectionModel().selectedRows()
        is_single_selection = len(selected_rows) == 1

        if not is_single_selection:
            self.module_settings_btn.setEnabled(False)
            self.toggle_enabled_btn.setEnabled(False)
            self.remove_module_btn.setEnabled(False)
            self.toggle_enabled_btn.setText(" 启用/禁用")
            self.toggle_enabled_btn.setIcon(QIcon())
            return
        
        row = selected_rows[0].row()
        name_item = self.module_table.item(row, 1)
        if not name_item: return

        module_key = name_item.data(Qt.UserRole)

        PROTECTED_MODULES = [
            'settings_module', 'plugin_system', 'icon_manager', 
            'custom_widgets_module', 'language_detector_module', 'shared_widgets_module'
        ]
        is_protected = module_key in PROTECTED_MODULES

        # 1. 更新“模块设置”按钮状态
        target_page = None
        for attr_name in dir(self.parent_window):
            attr_value = getattr(self.parent_window, attr_name)
            if isinstance(attr_value, QWidget) and attr_value.property("module_key") == module_key:
                target_page = attr_value
                break
        can_open_settings = bool(target_page and hasattr(target_page, 'open_settings_dialog'))
        self.module_settings_btn.setEnabled(can_open_settings)

        # 2. 更新“启用/禁用”和“卸载”按钮状态
        self.remove_module_btn.setEnabled(not is_protected)
        self.toggle_enabled_btn.setEnabled(not is_protected)

        if not is_protected:
            disabled_modules = self.parent_window.config.get("app_settings", {}).get("disabled_modules", [])
            is_enabled = module_key not in disabled_modules
            if is_enabled:
                self.toggle_enabled_btn.setText(" 禁用模块")
                self.toggle_enabled_btn.setIcon(self.icon_manager.get_icon("lock"))
            else:
                self.toggle_enabled_btn.setText(" 启用模块")
                self.toggle_enabled_btn.setIcon(self.icon_manager.get_icon("unlock"))

    def _connect_signals(self):
        """
        [v2.0 - 修复版]
        连接所有UI控件的信号到相应的槽函数。
        此版本修复了重复连接的问题，并对连接进行了逻辑分组。
        """
        # --- 1. 常规设置页面的信号连接 ---
        self.collector_width_slider.valueChanged.connect(self._on_setting_changed)
        self.editor_width_slider.valueChanged.connect(self._on_setting_changed)
        self.collector_width_slider.valueChanged.connect(lambda v: self.collector_width_label.setText(f"{v} px"))
        self.editor_width_slider.valueChanged.connect(lambda v: self.editor_width_label.setText(f"{v} px"))
        
        self.theme_combo.currentIndexChanged.connect(self._on_setting_changed)
        self.compact_mode_switch.stateChanged.connect(self._on_setting_changed)
        self.theme_combo.currentIndexChanged.connect(self._update_compact_switch_state)

        self.hide_tooltips_switch.stateChanged.connect(self._on_setting_changed)
        
        self.results_dir_btn.clicked.connect(self.select_results_dir) 
        self.results_dir_input.textChanged.connect(self._on_setting_changed)

        self.participant_name_input.textChanged.connect(self._on_setting_changed)
        self.enable_logging_switch.stateChanged.connect(self._on_setting_changed)
        
        self.gtts_lang_combo.currentIndexChanged.connect(self._on_setting_changed)
        self.gtts_auto_detect_switch.stateChanged.connect(self._on_setting_changed)
        
        # --- 2. 音频设置页面的信号连接 ---
        self.simple_mode_switch.stateChanged.connect(self.on_device_mode_toggled)
        self.input_device_combo.currentIndexChanged.connect(self._on_setting_changed)
        self.recording_format_switch.stateChanged.connect(self._on_setting_changed)
        self.sample_rate_combo.currentIndexChanged.connect(self._on_setting_changed)
        self.channels_combo.currentIndexChanged.connect(self._on_setting_changed)
        self.gain_slider.valueChanged.connect(self._on_setting_changed)
        self.gain_slider.valueChanged.connect(lambda v: self.gain_label.setText(f"{v/10.0:.1f}x"))
        self.player_cache_slider.valueChanged.connect(self._on_setting_changed)
        self.player_cache_slider.valueChanged.connect(lambda v: self.player_cache_label.setText(f"{v} 个文件"))
        
        # --- [核心修复] 将所有即时测试相关的连接集中在此 ---
        self.device_name_resolved.connect(self._update_status_label_device_name)
        self.test_mic_btn.clicked.connect(self._on_test_mic_btn_clicked)
        self.playback_test_btn.clicked.connect(self._on_playback_test_clicked)
        self.test_mic_update_timer.timeout.connect(self._update_test_volume_meter)
        self.playback_update_timer.timeout.connect(self._update_playback_progress) # <-- 新增
        # --- 修复结束 ---
        
        # --- 3. 模块管理页面的信号连接 ---
        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        
        self.add_module_btn.clicked.connect(self.add_module)
        self.module_settings_btn.clicked.connect(self.on_module_settings_btn_clicked)
        self.toggle_enabled_btn.clicked.connect(self.on_toggle_enabled_btn_clicked)
        self.remove_module_btn.clicked.connect(lambda: self.remove_module_file(self.module_table.currentRow()))
        
        self.module_table.customContextMenuRequested.connect(self.show_module_context_menu)
        self.module_table.itemDoubleClicked.connect(self.on_module_double_clicked)
        self.module_table.itemSelectionChanged.connect(self._update_module_buttons_state)

        # --- 4. 底部配置管理按钮的信号连接 ---
        self.save_btn.clicked.connect(self.save_settings)
        self.restore_defaults_btn.clicked.connect(self.restore_defaults)
        self.import_settings_btn.clicked.connect(self.import_settings)
        self.export_settings_btn.clicked.connect(self.export_settings)

    def hideEvent(self, event):
        """
        重写 hideEvent，确保当用户切换到其他主标签页时，
        麦克风测试能被安全地停止。
        """
        if self.is_testing_mic:
            self._stop_mic_test() # 调用停止逻辑
        super().hideEvent(event)

    def _on_test_mic_btn_clicked(self):
        """切换麦克风测试的开始和停止状态。"""
        if self.is_testing_mic:
            self._stop_mic_test()
        else:
            self._start_mic_test()

    def _start_mic_test(self):
        """
        [v2.0 - 修正版]
        启动麦克风测试线程和UI更新，并为新录制做准备。
        """
        # --- 准备新录制 (逻辑不变) ---
        self.test_mic_audio_chunks.clear()
        self.last_test_recording = None
        self.playback_test_btn.setEnabled(False)
        self.playback_slider.setEnabled(False)
        self.playback_slider.setValue(0)

        # --- 更新UI状态 ---
        self.is_testing_mic = True
        # [核心修复] 使用正确的属性名 self.test_mic_status_label
        self.test_mic_status_label.setText("● 正在测试...")
        self.test_mic_btn.setText("停止测试")
        self.test_mic_btn.setIcon(self.icon_manager.get_icon("stop"))

        # --- 启动后台线程和定时器 (逻辑不变) ---
        self.test_mic_stop_event.clear()
        self.test_mic_thread = threading.Thread(target=self._test_recorder_task, daemon=True)
        self.test_mic_thread.start()
        self.test_mic_update_timer.start(16) # 维持16ms的更新频率

    def _stop_mic_test(self):
        """
        [v3.1 - 修正与优化版]
        停止麦克风测试，处理已录制的音频数据块，并重置所有相关的UI控件。
        """
        # 如果测试并未在运行，则直接返回
        if not self.is_testing_mic:
            return

        # --- 1. 停止后台线程和UI定时器 ---
        self.is_testing_mic = False
        self.test_mic_update_timer.stop()
        self.test_mic_stop_event.set()

        # 安全地等待后台线程退出
        if self.test_mic_thread and self.test_mic_thread.is_alive():
            self.test_mic_thread.join(timeout=0.5)
        self.test_mic_thread = None

        # --- 2. 处理并保存录制的音频数据 ---
        if self.test_mic_audio_chunks:
            recording_data = np.concatenate(self.test_mic_audio_chunks, axis=0)
            gain = self.gain_slider.value() / 10.0
            
            if gain != 1.0:
                self.last_test_recording = np.clip(recording_data * gain, -1.0, 1.0)
            else:
                self.last_test_recording = recording_data
            
            self.test_mic_audio_chunks.clear()
            
            # 录制成功，启用回放功能
            self.playback_test_btn.setEnabled(True)
            self.playback_slider.setEnabled(True)
        else:
            self.last_test_recording = None
            self.playback_test_btn.setEnabled(False)
            self.playback_slider.setEnabled(False)

        # --- 3. 重置UI状态到“空闲” ---
        # [核心修复] 使用正确的属性名 self.test_mic_status_label
        self.test_mic_status_label.setText("● 未在测试")
        self.test_mic_btn.setText("测试麦克风")
        self.test_mic_btn.setIcon(self.icon_manager.get_icon("record"))
        
        self.test_mic_volume_meter.setValue(0)
        self.test_mic_volume_history.clear()
        self.playback_slider.setValue(0)
        
        # 清空队列中可能残留的数据
        while not self.test_mic_volume_queue.empty():
            try:
                self.test_mic_volume_queue.get_nowait()
            except queue.Empty:
                break
    def _update_status_label_device_name(self, name):
        """安全地在UI线程中更新状态标签以显示设备名称。"""
        if self.is_testing_mic: # 再次检查状态，防止延迟的信号更新已停止的UI
            self.test_mic_status_label.setText(f"● 正在测试: {name}")
    def _test_recorder_task(self):
        """
        [v2.0 - 依赖修复版]
        在后台线程中运行的录音任务，并正确解析设备名称。
        """
        try:
            device_index = None
            device_name = "系统默认"
            
            # 始终从主窗口获取最新的、完整的配置副本
            current_config = self.parent_window.config.copy()

            if self.simple_mode_switch.isChecked():
                # --- [核心修复] ---
                # 1. 直接更新配置副本中的模式，而不是创建临时字典
                current_config.setdefault("audio_settings", {})["input_device_mode"] = self.input_device_combo.currentData()
                # 2. 调用存储在本类中的解析函数
                device_index = self.resolve_device_func(current_config)
            else:
                # 专家模式下直接使用UI上的索引
                device_index = self.input_device_combo.currentData()

            # --- 解析设备名称的逻辑保持不变 ---
            try:
                devices = sd.query_devices()
                if device_index is not None and 0 <= device_index < len(devices):
                    device_name = devices[device_index]['name']
                elif device_index is None:
                    # 如果是系统默认，尝试找到默认设备名称
                    default_idx = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) and len(sd.default.device) > 0 else -1
                    if default_idx != -1 and 0 <= default_idx < len(devices):
                        device_name = devices[default_idx]['name']
            except Exception as e:
                print(f"解析设备名称时出错: {e}")

            self.device_name_resolved.emit(device_name)

            # --- 后续的音频流启动逻辑保持不变 ---
            sample_rate = int(self.sample_rate_combo.currentText().split(' ')[0])
            channels = int(self.channels_combo.currentText().split(' ')[0])

            with sd.InputStream(
                device=device_index,
                samplerate=sample_rate,
                channels=channels,
                callback=self._test_audio_callback
            ):
                self.test_mic_stop_event.wait()

        except Exception as e:
            QTimer.singleShot(0, lambda: QMessageBox.critical(self, "设备测试失败", f"无法启动麦克风测试：\n{e}"))
            QTimer.singleShot(0, self._stop_mic_test)

    def _test_audio_callback(self, indata, frames, time, status):
        """
        [v3.0 - 健壮双轨版]
        sounddevice库的回调函数。此版本采用“双轨制”数据处理：
        1. 原始数据被累积到列表中，用于无损回放。
        2. 经过增益处理的数据被放入队列，用于实时的音量计显示。
        """
        if status:
            # 在设置页面进行测试时，通常可以安全地忽略状态警告，避免控制台刷屏
            # print(f"Audio callback status in settings: {status}", file=sys.stderr)
            pass

        # --- 轨道 1: 累积原始音频数据用于回放 ---
        # 我们复制一份原始、未经修改的数据块，并将其添加到列表中。
        # 这是为了确保回放时听到的是最真实的录音效果。
        if self.is_testing_mic:
            self.test_mic_audio_chunks.append(indata.copy())

        # --- 轨道 2: 处理数据并更新音量计队列 ---
        # 创建一个临时副本，应用UI上的增益，然后放入音量计队列。
        # 这部分数据仅用于UI实时反馈，不影响最终的回放质量。
        gain = self.gain_slider.value() / 10.0
        processed_for_meter = np.clip(indata * gain, -1.0, 1.0)

        # 使用“覆盖最新值”模式来更新队列，从根本上解决 queue.Full 异常。
        # 它的逻辑是：我们只关心最新的数据块，所以每次都尝试清空旧的，再放入新的。
        while not self.test_mic_volume_queue.empty():
            try:
                self.test_mic_volume_queue.get_nowait()
            except queue.Empty:
                # 在多线程环境中，队列可能在我们检查后、获取前变空，
                # 捕获这个异常可以安全地退出循环。
                break
        
        try:
            # 将最新的数据块放入队列。由于上面已经清空，这里的 put_nowait 几乎不可能失败。
            self.test_mic_volume_queue.put_nowait(processed_for_meter)
        except queue.Full:
            # 即使在极端的竞争条件下队列仍然满了，我们也只是简单地丢弃这一帧数据，
            # 这对于音量计来说是完全可以接受的，并且不会产生任何错误日志。
            pass

    def _on_playback_test_clicked(self):
        """响应回放按钮，使用QTimer驱动进度条更新。"""
        import time

        if self.is_playing_back or self.last_test_recording is None or not self.last_test_recording.any():
            return
        if sf is None:
            QMessageBox.critical(self, "功能缺失", "无法回放，缺少 soundfile 库。")
            return

        self.is_playing_back = True
        self.playback_test_btn.setEnabled(False)
        self.playback_slider.setEnabled(True)
        self.playback_slider.setValue(0)

        try:
            sample_rate = int(self.sample_rate_combo.currentText().split(' ')[0])
            self.playback_duration_ms = (len(self.last_test_recording) / sample_rate) * 1000

            # 在后台线程中播放音频
            playback_thread = threading.Thread(target=sd.play, args=(self.last_test_recording, sample_rate), daemon=True)
            playback_thread.start()
            
            self.playback_start_time = time.time()
            self.playback_update_timer.start(25) # 每25ms更新一次进度条

            # 安排一个一次性定时器，在播放结束后调用清理函数
            QTimer.singleShot(int(self.playback_duration_ms) + 100, self._on_playback_finished)
        except Exception as e:
            QMessageBox.critical(self, "回放失败", f"播放测试录音时出错：\n{e}")
            self._on_playback_finished() # 出错时也要清理

    def _update_playback_progress(self):
        """由定时器调用，根据经过的时间更新播放进度条。"""
        import time
        if not self.is_playing_back:
            return
        
        elapsed_ms = (time.time() - self.playback_start_time) * 1000
        progress = (elapsed_ms / self.playback_duration_ms) * 100 if self.playback_duration_ms > 0 else 0
        
        # 阻止信号循环，仅更新UI
        self.playback_slider.blockSignals(True)
        self.playback_slider.setValue(int(min(progress, 100)))
        self.playback_slider.blockSignals(False)

    def _on_playback_finished(self):
        """播放结束后，重置所有播放相关的UI和状态。"""
        if not self.is_playing_back: # 防止被重复调用
            return
            
        self.playback_update_timer.stop()
        self.is_playing_back = False
        self.playback_test_btn.setEnabled(True)
        self.playback_slider.setEnabled(False)
        self.playback_slider.setValue(0)

    def _update_test_volume_meter(self):
        """
        从队列中获取音频数据，计算音量，并平滑地更新进度条。
        此逻辑直接借鉴自 voicebank_recorder_module。
        """
        raw_target_value = 0
        try:
            data_chunk = self.test_mic_volume_queue.get_nowait()
            # 计算RMS值，然后转换为dBFS，最后映射到0-100的范围
            rms = np.linalg.norm(data_chunk) / np.sqrt(len(data_chunk)) if data_chunk.any() else 0
            dbfs = 20 * np.log10(rms + 1e-7)
            raw_target_value = max(0, min(100, (dbfs + 60) * (100 / 60)))
        except queue.Empty:
            # 如果队列为空，则让音量缓慢回落
            raw_target_value = self.test_mic_volume_meter.value() * 0.8
        except Exception:
            raw_target_value = 0 # 发生其他错误则重置

        # 使用历史数据进行平滑处理，避免音量条剧烈跳动
        self.test_mic_volume_history.append(raw_target_value)
        smoothed_target_value = sum(self.test_mic_volume_history) / len(self.test_mic_volume_history)

        # 渐进式更新，使视觉效果更流畅
        current_value = self.test_mic_volume_meter.value()
        smoothing_factor = 0.4
        new_value = int(current_value * (1 - smoothing_factor) + smoothed_target_value * smoothing_factor)
    
        self.test_mic_volume_meter.setValue(new_value)

    def on_module_settings_btn_clicked(self):
        """响应“模块设置”按钮的点击事件。"""
        row = self.module_table.currentRow()
        if row != -1:
            # 从第 1 列（模块名称列）获取 item，因为它包含数据
            name_item = self.module_table.item(row, 1)
            # 复用双击的逻辑，并传递正确的 item
            self.on_module_double_clicked(name_item)

    def on_toggle_enabled_btn_clicked(self):
        """响应“启用/禁用”按钮的点击事件。"""
        row = self.module_table.currentRow()
        if row == -1: return

        name_item = self.module_table.item(row, 1)
        if not name_item: return

        module_key = name_item.data(Qt.UserRole)
        disabled_modules = self.parent_window.config.get("app_settings", {}).get("disabled_modules", [])
        is_currently_enabled = module_key not in disabled_modules

        # 切换状态
        self.toggle_module_enabled(module_key, enable=not is_currently_enabled)

    def _on_setting_changed(self):
        """当任何设置被用户修改时，启用保存按钮。"""
        self.save_btn.setEnabled(True)
        
    def on_device_mode_toggled(self, is_simple_mode):
        """当录音设备模式开关切换时，重新填充设备列表。"""
        self.populate_input_devices()
        self._on_setting_changed()

    def populate_all(self):
        """填充所有下拉框和动态内容，包括主题、设备和模块表格。"""
        self.populate_themes()
        self.populate_input_devices()
        self.populate_module_table()

    def _update_compact_switch_state(self, index):
        """
        当主题下拉框选择变化时，检查新选中的主题是否有紧凑版，
        并据此启用或禁用“紧凑模式”开关，同时更新Tooltip。
        """
        was_checked = self.compact_mode_switch.isChecked() # 记录状态，用于判断是否触发保存

        if index < 0: # 如果没有选中项
            self.compact_mode_switch.setEnabled(False)
            self.compact_mode_switch.setToolTip("当前选中的主题没有提供紧凑版本。")
            return

        theme_data = self.theme_combo.itemData(index) # 获取存储在 itemData 中的字典
        if theme_data and theme_data.get('compact_path'):
            self.compact_mode_switch.setEnabled(True)
            self.compact_mode_switch.setToolTip("切换当前选中主题的标准版与紧凑版。")
        else:
            self.compact_mode_switch.setEnabled(False)
            self.compact_mode_switch.setChecked(False) # 如果禁用，强制设为“关闭”状态
            self.compact_mode_switch.setToolTip("当前选中的主题没有提供紧凑版本。")

        # 如果开关的 checked 状态因为程序逻辑而改变，手动触发 _on_setting_changed
        if self.compact_mode_switch.isChecked() != was_checked:
            self._on_setting_changed()

    def populate_input_devices(self):
        """根据当前设备模式填充录音设备下拉框。"""
        self.input_device_combo.clear()
        is_simple_mode = self.simple_mode_switch.isChecked()

        if is_simple_mode:
            self.input_device_combo.setToolTip("选择一个简化的录音设备类型。")
            self.input_device_combo.addItem("智能选择 (推荐)", "smart")
            self.input_device_combo.addItem("系统默认", "default")
            self.input_device_combo.addItem("内置麦克风", "internal")
            self.input_device_combo.addItem("外置设备 (USB/蓝牙等)", "external")
            self.input_device_combo.addItem("电脑内部声音", "loopback")
        else: # 专家模式
            self.input_device_combo.setToolTip("选择用于录制音频的物理麦克风设备。")
            try:
                devices = sd.query_devices()
                # 兼容旧版本的 sounddevice.default.device 可能不是列表的情况
                default_input_idx = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) and len(sd.default.device) > 0 else -1
                
                self.input_device_combo.addItem("系统默认", None) # None 表示让 sounddevice 自动选择默认设备
                
                for i, device in enumerate(devices):
                    if device['max_input_channels'] > 0: # 只有输入通道大于0的才是输入设备
                        self.input_device_combo.addItem(f"{device['name']}" + (" (推荐)" if i == default_input_idx else ""), i)
            except Exception as e:
                print(f"获取录音设备失败: {e}", file=sys.stderr)
                self.input_device_combo.addItem("无法获取设备列表", -1) # 错误时显示提示信息

    def select_results_dir(self):
        """打开文件对话框，让用户选择结果文件夹。"""
        directory = QFileDialog.getExistingDirectory(self, "选择结果文件夹", self.results_dir_input.text())
        if directory:
            self.results_dir_input.setText(directory)
            self._on_setting_changed()

    def populate_themes(self):
        """
        扫描主题文件夹，自动配对标准版和紧凑版主题文件，
        并将其添加到主题选择下拉框。
        """
        self.theme_combo.clear()
        if not os.path.exists(self.THEMES_DIR): return
        
        themes = {} # 临时字典，用于存储解析后的主题信息，键为主题的基础名称

        try:
            all_items = os.listdir(self.THEMES_DIR)
            
            def process_theme_file(file_path, display_name_base):
                """辅助函数：解析主题文件名，判断是否为紧凑版并存储路径。"""
                is_compact = any(kw in display_name_base.lower() for kw in ["compact", "紧凑", "紧凑版"])
                base_name = display_name_base.replace("Compact", "").replace("紧凑版", "").replace("紧凑", "").strip()
                
                if not base_name: return # 避免添加空名称的主题

                if base_name not in themes:
                    themes[base_name] = {'standard_path': None, 'compact_path': None}
                
                if is_compact:
                    themes[base_name]['compact_path'] = file_path
                else:
                    themes[base_name]['standard_path'] = file_path

            # 遍历主题目录下的所有文件和文件夹
            for item in all_items:
                item_path = os.path.join(self.THEMES_DIR, item)
                if os.path.isdir(item_path): # 如果是文件夹（例如 "The_Great_Wave_Daylight" 目录）
                    qss_file_in_dir = f"{item}.qss"
                    if os.path.exists(os.path.join(item_path, qss_file_in_dir)):
                        display_name = item.replace("_", " ").title() # 格式化显示名称
                        relative_path = os.path.join(item, qss_file_in_dir).replace("\\", "/") # 相对路径
                        process_theme_file(relative_path, display_name)
                elif item.endswith('.qss') and not item.startswith('_'): # 如果是 .qss 文件（例如 "Default.qss"）
                    display_name = os.path.splitext(item)[0].replace("_", " ").replace("-", " ").title()
                    process_theme_file(item, display_name)

        except Exception as e: 
            print(f"扫描主题文件夹时出错: {e}")

        # 将解析后的主题数据添加到下拉框，按名称排序
        sorted_theme_names = sorted(themes.keys())
        for name in sorted_theme_names:
            theme_info = themes[name]
            # 只有当存在标准版路径时，才将其添加到下拉框
            if theme_info.get('standard_path'):
                self.theme_combo.addItem(name, theme_info) # itemData 存储的是 {'standard_path': ..., 'compact_path': ...}
        
        # 初始时确保 compact_mode_switch 的状态正确
        self._update_compact_switch_state(self.theme_combo.currentIndex())

    def load_settings(self):
        """
        从全局配置中加载所有设置，并更新UI控件的状态。
        包括常规设置（UI、文件、TTS、音频）和模块管理状态。
        """
        self.populate_all() # 确保所有下拉框和表格被填充

        config = self.parent_window.config # 获取主窗口的最新配置
        
        # --- UI 外观设置 ---
        ui_settings = config.get("ui_settings", {})
        self.collector_width_slider.setValue(ui_settings.get("collector_sidebar_width", 350))
        self.editor_width_slider.setValue(ui_settings.get("editor_sidebar_width", 320))
        self.hide_tooltips_switch.setChecked(ui_settings.get("hide_all_tooltips", False))
        
        # --- 主题设置 ---
        saved_theme_path = config.get("theme", "默认.qss") # 获取当前保存的主题路径
        # 判断保存的主题是否为紧凑版
        is_compact_saved = isinstance(saved_theme_path, str) and any(kw in saved_theme_path.lower() for kw in ["compact", "紧凑", "紧凑版"])
        
        # 临时禁用信号，防止在设置UI值时触发 _on_setting_changed
        self.theme_combo.blockSignals(True)
        self.compact_mode_switch.blockSignals(True)

        found = False
        for i in range(self.theme_combo.count()):
            theme_data = self.theme_combo.itemData(i) # 获取存储在 itemData 中的字典
            # 检查保存的路径是否与当前下拉项的标准版或紧凑版路径匹配
            if (theme_data.get('standard_path') == saved_theme_path or 
                theme_data.get('compact_path') == saved_theme_path):
                self.theme_combo.setCurrentIndex(i)
                self.compact_mode_switch.setChecked(is_compact_saved)
                found = True
                break
        
        if not found and self.theme_combo.count() > 0:
            # 如果没找到匹配项，或者配置文件中的主题文件不存在，默认选中第一个主题
            self.theme_combo.setCurrentIndex(0)
            self.compact_mode_switch.setChecked(False) # 默认到标准版

        # 重新启用信号
        self.theme_combo.blockSignals(False)
        self.compact_mode_switch.blockSignals(False)
        
        # 确保开关状态和Tooltip在加载完成后立即更新
        self._update_compact_switch_state(self.theme_combo.currentIndex())
        # 强制同步视觉状态，解决QSS覆盖问题 (尤其是在主题切换后)
        self.compact_mode_switch.sync_visual_state_to_checked_state() 
        
        # --- 文件设置 ---
        file_settings = config.get("file_settings", {})
        self.participant_name_input.setText(file_settings.get('participant_base_name', ''))        
        self.results_dir_input.setText(file_settings.get("results_dir", os.path.join(get_base_path_for_module(), "Results")))
        
        # --- 应用设置 (日志) ---
        app_settings = config.get("app_settings", {})
        self.enable_logging_switch.setChecked(app_settings.get("enable_logging", True))
        
        # --- gTTS 设置 ---
        gtts_settings = config.get("gtts_settings", {})
        self.gtts_lang_combo.setCurrentText(gtts_settings.get('default_lang', 'en-us'))
        self.gtts_auto_detect_switch.setChecked(gtts_settings.get('auto_detect', True))
        
        # --- 音频设置 ---
        audio_settings = config.get("audio_settings", {})
        device_mode = audio_settings.get("input_device_mode", "manual")
        is_simple = device_mode != "manual"
        
        self.simple_mode_switch.blockSignals(True) # 暂时阻塞信号，避免触发 populate_input_devices
        self.simple_mode_switch.setChecked(is_simple)
        self.simple_mode_switch.blockSignals(False)

        self.populate_input_devices() # 根据切换后的模式重新填充设备列表

        # 设置正确的设备项
        if is_simple:
            index_in_combo = self.input_device_combo.findData(device_mode)
        else:
            saved_device_idx = audio_settings.get("input_device_index", None)
            index_in_combo = self.input_device_combo.findData(saved_device_idx)

        if index_in_combo != -1: self.input_device_combo.setCurrentIndex(index_in_combo)
        elif self.input_device_combo.count() > 0: self.input_device_combo.setCurrentIndex(0) # 找不到匹配时默认选中第一个

        self.recording_format_switch.setChecked(audio_settings.get("recording_format", "wav") == "mp3")
        
        # 从文本中解析采样率和通道数，并设置下拉框
        sr_text = next((s for s in [self.sample_rate_combo.itemText(i) for i in range(self.sample_rate_combo.count())] if str(audio_settings.get('sample_rate', 44100)) in s), "44100 Hz (CD质量, 推荐)")
        self.sample_rate_combo.setCurrentText(sr_text)
        ch_text = next((s for s in [self.channels_combo.itemText(i) for i in range(self.channels_combo.count())] if str(audio_settings.get('channels', 1)) in s), "1 (单声道, 推荐)")
        self.channels_combo.setCurrentText(ch_text)
        
        self.gain_slider.setValue(int(audio_settings.get('recording_gain', 1.0) * 10))
        self.player_cache_slider.setValue(audio_settings.get("player_cache_size", 5))
      
        self.save_btn.setEnabled(False) # 加载完成后，保存按钮应为禁用状态，表示当前是“干净”状态
        if self.nav_list.count() > 0:
            self.nav_list.setCurrentRow(0)
        
    def save_settings(self):
        """
        保存所有设置到配置文件，并触发主窗口的更新。
        此方法现在包含常规设置和模块管理设置的保存。
        """
        config = self.parent_window.config # 获取主窗口的当前配置字典
        
        # --- 常规设置的收集与保存 ---
        # UI外观设置
        config.setdefault("ui_settings", {})["collector_sidebar_width"] = self.collector_width_slider.value()
        config.setdefault("ui_settings", {})["editor_sidebar_width"] = self.editor_width_slider.value()
        config.setdefault("ui_settings", {})["hide_all_tooltips"] = self.hide_tooltips_switch.isChecked()
        
        # 主题设置（根据标准版/紧凑版开关选择路径）
        current_index = self.theme_combo.currentIndex()
        if current_index >= 0:
            theme_data = self.theme_combo.itemData(current_index)
            is_compact_selected = self.compact_mode_switch.isChecked()
            
            if is_compact_selected and theme_data.get('compact_path'):
                config['theme'] = theme_data['compact_path']
            else:
                config['theme'] = theme_data['standard_path']
        else: # 如果没有选择任何主题（理论上不会发生，除非列表为空）
            config['theme'] = "默认.qss" # 回退到默认值
            
        # 文件设置
        config['file_settings'] = {
            "word_list_file": "", # 这个设置通常在词表编辑器中更新，这里保留空值以确保兼容性
            "participant_base_name": self.participant_name_input.text(), 
            "results_dir": self.results_dir_input.text()
        }
        # gTTS 设置
        config['gtts_settings'] = {"default_lang": self.gtts_lang_combo.currentText(), "auto_detect": self.gtts_auto_detect_switch.isChecked()}
        
        # 应用设置 (日志)
        app_settings = config.setdefault("app_settings", {})
        app_settings["enable_logging"] = self.enable_logging_switch.isChecked()

        # 音频设置
        audio_settings = config.setdefault("audio_settings", {})
        if self.simple_mode_switch.isChecked(): # 如果是简易模式
            audio_settings["input_device_mode"] = self.input_device_combo.currentData() # 保存模式字符串 (smart, default等)
            if "input_device_index" in audio_settings:
                del audio_settings["input_device_index"] # 如果切换到简易模式，移除具体的设备索引
        else: # 专家模式
            audio_settings["input_device_mode"] = "manual" # 保存为 manual 模式
            audio_settings["input_device_index"] = self.input_device_combo.currentData() # 保存具体设备索引

        audio_settings["sample_rate"] = int(self.sample_rate_combo.currentText().split(' ')[0])
        audio_settings["channels"] = int(self.channels_combo.currentText().split(' ')[0])
        audio_settings["recording_gain"] = self.gain_slider.value() / 10.0
        audio_settings["recording_format"] = "mp3" if self.recording_format_switch.isChecked() else "wav"
        audio_settings["player_cache_size"] = self.player_cache_slider.value()
        
        # --- 模块管理设置 ---
        # 模块的启用/禁用状态已经在 on_module_status_changed 中实时更新到 config['app_settings']['disabled_modules'] 中了，
        # 所以这里不需要额外处理，直接保存整个 config 即可。

        # 写入文件并应用更改
        if self._write_config_and_apply(config):
            QMessageBox.information(self, "成功", "所有设置已成功保存并应用！")
            self.save_btn.setEnabled(False) # 保存成功后禁用保存按钮

    def _write_config_and_apply(self, config_dict):
        """
        将配置字典写入文件，并通知主窗口应用新的配置。
        此方法负责触发主UI的整体刷新。
        Args:
            config_dict (dict): 要写入文件并应用的配置字典。
        Returns:
            bool: 如果成功写入并应用则返回 True，否则返回 False。
        """
        try:
            settings_file_path = os.path.join(get_base_path_for_module(), "config", "settings.json")
            with open(settings_file_path, 'w', encoding='utf-8') as f: json.dump(config_dict, f, indent=4)
            
            # 更新主窗口的配置引用，确保整个应用程序使用最新的配置
            self.parent_window.config = config_dict 
            
            # 重新应用主题，这将触发所有页面调用其 update_icons 方法，从而刷新图标和自定义颜色
            self.parent_window.apply_theme() 
            self.parent_window.apply_tooltips() # 重新应用工具提示

            # 通知主窗口刷新所有标签页，确保模块状态和布局更新
            # 遍历所有主标签页
            for i in range(self.parent_window.main_tabs.count()):
                main_tab_widget = self.parent_window.main_tabs.widget(i)
                # 检查是否是包含子标签页的 QTabWidget
                if isinstance(main_tab_widget, QTabWidget):
                    for j in range(main_tab_widget.count()):
                        page = main_tab_widget.widget(j)
                        # 如果页面有 load_config_and_prepare 方法，调用它以重新加载配置和刷新UI
                        if hasattr(page, 'load_config_and_prepare'):
                            try:
                                page.load_config_and_prepare()
                            except Exception as e:
                                print(f"加载页面配置失败 ({page.__class__.__name__}): {e}", file=sys.stderr)
                else: # 如果是直接的主页面（例如设置页面自身）
                    if hasattr(main_tab_widget, 'load_settings'): # 对于设置页面自身
                        try:
                            main_tab_widget.load_settings() # 重新加载设置，确保UI状态正确
                        except Exception as e:
                            print(f"加载页面配置失败 ({main_tab_widget.__class__.__name__}): {e}", file=sys.stderr)
            
            return True
        except Exception as e:
            QMessageBox.critical(self, "错误", f"应用配置失败: {e}")
            return False

    def restore_defaults(self):
        """将所有设置恢复为出厂默认值，并重启程序。"""
        reply = QMessageBox.warning(self, "恢复默认设置", "您确定要将所有设置恢复为出厂默认值吗？\n\n此操作将删除您当前的配置文件，且不可撤销。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                settings_file_path = os.path.join(get_base_path_for_module(), "config", "settings.json")
                if os.path.exists(settings_file_path): os.remove(settings_file_path) # 删除现有配置文件
                
                # 重新加载默认配置，这会从Canary.py的setup_and_load_config获取
                new_config = self.parent_window.setup_and_load_config_external()
                self.parent_window.config = new_config # 更新主窗口的配置引用
                
                # 重新加载UI以反映新配置并应用主题
                if self._write_config_and_apply(new_config):
                    QMessageBox.information(self, "成功", "已成功恢复默认设置。")
                    self.save_btn.setEnabled(False)
            except Exception as e:
                QMessageBox.critical(self, "恢复失败", f"恢复默认设置时出错: {e}")

    def import_settings(self):
        """从外部JSON文件导入设置。"""
        filepath, _ = QFileDialog.getOpenFileName(self, "导入配置文件", "", "JSON 文件 (*.json)")
        if not filepath: return
        try:
            with open(filepath, 'r', encoding='utf-8') as f: new_config = json.load(f)
            if not isinstance(new_config, dict): raise ValueError("配置文件格式无效，必须是一个JSON对象。")
            
            # 在导入时，需要处理 results_dir 的相对路径问题
            if 'file_settings' in new_config and 'results_dir' in new_config['file_settings']:
                current_results_dir = new_config['file_settings']['results_dir']
                # 如果导入的 results_dir 是相对路径，则转换为绝对路径
                if not os.path.isabs(current_results_dir):
                    app_base_path = get_base_path_for_module()
                    new_config['file_settings']['results_dir'] = os.path.join(app_base_path, current_results_dir)

            if self._write_config_and_apply(new_config):
                QMessageBox.information(self, "成功", "配置文件已成功导入并应用。")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"无法导入配置文件:\n{e}")

    def export_settings(self):
        """将当前所有设置导出为一个JSON文件。"""
        filepath, _ = QFileDialog.getSaveFileName(self, "导出配置文件", "PhonAcq_settings.json", "JSON 文件 (*.json)")
        if not filepath: return
        try:
            config_to_export = self.parent_window.config.copy() # 复制一份，避免修改live config
            
            # 导出时，如果 results_dir 是在 BASE_PATH 下，可以将其转换为相对路径，更通用
            if 'file_settings' in config_to_export and 'results_dir' in config_to_export['file_settings']:
                current_results_dir = config_to_export['file_settings']['results_dir']
                app_base_path = get_base_path_for_module()
                if os.path.isabs(current_results_dir) and current_results_dir.startswith(app_base_path):
                    config_to_export['file_settings']['results_dir'] = os.path.relpath(current_results_dir, app_base_path)
            
            with open(filepath, 'w', encoding='utf-8') as f: json.dump(config_to_export, f, indent=4)
            QMessageBox.information(self, "导出成功", f"当前配置已成功导出至:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"无法导出文件:\n{e}")

    # --- 模块管理的核心逻辑方法 ---
    def populate_module_table(self):
        """
        [v2.4 - 设置图标版] 扫描模块文件夹，并根据配置填充模块管理表格。
        此版本会在可配置的模块名称前添加一个设置图标。
        """
        self.module_table.blockSignals(True)
        self.module_table.setRowCount(0)
        
        disabled_modules = self.parent_window.config.get("app_settings", {}).get("disabled_modules", [])
        all_loaded_modules_info = self.parent_window.MODULES
        
        modules_dir = os.path.join(get_base_path_for_module(), "modules")
        physical_modules_files = [f for f in os.listdir(modules_dir) if f.endswith('.py') and not f.startswith('__')]
        
        PROTECTED_MODULES = [
            'settings_module', 'plugin_system', 'icon_manager', 
            'custom_widgets_module', 'language_detector_module', 'shared_widgets_module'
        ]

        display_modules = {}

        # 1. 收集所有模块的信息
        for filename in physical_modules_files:
            module_key = filename.replace('.py', '')
            info = { 'name': module_key, 'desc': "", 'is_protected': module_key in PROTECTED_MODULES }

            if module_key in all_loaded_modules_info:
                loaded_info = all_loaded_modules_info[module_key]
                info.update({'name': loaded_info['name'], 'desc': loaded_info['desc'], 'status_type': 'loaded'})
            else:
                if module_key in disabled_modules:
                    info.update({'status_type': 'disabled_by_user', 'desc': "此模块已被用户禁用。"})
                else:
                    info.update({'status_type': 'unloaded_error', 'desc': "无法加载，可能依赖缺失或存在错误。"})
            
            display_modules[module_key] = info

        # 2. 排序并填充表格
        sorted_keys = sorted(display_modules.keys(), key=lambda k: (display_modules[k]['is_protected'], display_modules[k]['name']))
        
        for module_key in sorted_keys:
            info = display_modules[module_key]
            row = self.module_table.rowCount()
            self.module_table.insertRow(row)

            # 状态图标列 (逻辑不变)
            # ... (此处代码与之前完全相同) ...
            status_icon = self.icon_manager.get_icon("modules")
            status_tooltip = "状态未知"
            if info['is_protected']:
                status_icon = self.icon_manager.get_icon("modules")
                status_tooltip = "核心组件 (始终启用)"
            elif info['status_type'] == 'unloaded_error':
                status_icon = self.icon_manager.get_icon("error")
                status_tooltip = "加载失败或依赖缺失"
            elif module_key not in disabled_modules:
                status_icon = self.icon_manager.get_icon("success")
                status_tooltip = "已启用"
            else:
                status_icon = self.icon_manager.get_icon("info")
                status_tooltip = "已禁用"
            cell_widget = QWidget()
            icon_label = QLabel()
            icon_label.setPixmap(status_icon.pixmap(QSize(24, 24)))
            icon_label.setAlignment(Qt.AlignCenter)
            layout = QHBoxLayout(cell_widget)
            layout.addWidget(icon_label)
            layout.setAlignment(Qt.AlignCenter)
            layout.setContentsMargins(0, 0, 0, 0)
            cell_widget.setToolTip(status_tooltip)
            self.module_table.setCellWidget(row, 0, cell_widget)
            
            # --- [核心修复] 模块名称列 (增加设置图标检查) ---
            # 1. 检查此模块是否有设置页面
            target_page = None
            for attr_name in dir(self.parent_window):
                attr_value = getattr(self.parent_window, attr_name)
                if isinstance(attr_value, QWidget) and attr_value.property("module_key") == module_key:
                    target_page = attr_value
                    break
            has_settings = bool(target_page and hasattr(target_page, 'open_settings_dialog'))

            # 2. 创建单元格项并设置文本
            name_item = QTableWidgetItem(info['name'])
            name_item.setToolTip(info['name'])
            
            # 3. 如果有设置页面，则添加设置图标
            if has_settings:
                name_item.setIcon(self.icon_manager.get_icon("settings"))
            
            # 4. 设置其他数据和标志
            name_item.setData(Qt.UserRole, module_key)
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.module_table.setItem(row, 1, name_item)
            # --- [修复结束] ---

            # 描述列 (逻辑不变)
            desc_item = QTableWidgetItem(info['desc'])
            desc_item.setToolTip(info['desc'])
            desc_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.module_table.setItem(row, 2, desc_item)
            
        self.module_table.blockSignals(False)
        self._update_module_buttons_state()

    def show_module_context_menu(self, position):
        """[v2.3] 为模块列表创建并显示右键上下文菜单。"""
        item = self.module_table.itemAt(position)
        if not item: return

        row = item.row()
        name_item = self.module_table.item(row, 1)
        if not name_item: return
        
        module_key = name_item.data(Qt.UserRole)
        module_display_name = name_item.text()

        PROTECTED_MODULES = ['settings_module', 'plugin_system', 'icon_manager', 'custom_widgets_module', 'language_detector_module', 'shared_widgets_module']
        is_protected = module_key in PROTECTED_MODULES

        menu = QMenu(self)
        
        # 模块设置
        target_page = None
        for attr_name in dir(self.parent_window):
            attr_value = getattr(self.parent_window, attr_name)
            if isinstance(attr_value, QWidget) and attr_value.property("module_key") == module_key:
                target_page = attr_value
                break
        
        has_settings = bool(target_page and hasattr(target_page, 'open_settings_dialog'))
        settings_action = menu.addAction(self.icon_manager.get_icon("settings"), "模块设置...")
        settings_action.setEnabled(has_settings)
        if has_settings:
            settings_action.triggered.connect(target_page.open_settings_dialog)
        
        # --- [核心修复] ---
        # 启用/禁用/卸载的逻辑现在只基于 is_protected
        if not is_protected:
            menu.addSeparator()
            disabled_modules = self.parent_window.config.get("app_settings", {}).get("disabled_modules", [])
            is_enabled = module_key not in disabled_modules
            
            if is_enabled:
                toggle_action = menu.addAction(self.icon_manager.get_icon("lock"), "禁用模块")
                toggle_action.triggered.connect(lambda: self.toggle_module_enabled(module_key, False))
            else:
                toggle_action = menu.addAction(self.icon_manager.get_icon("unlock"), "启用模块")
                toggle_action.triggered.connect(lambda: self.toggle_module_enabled(module_key, True))
            
            uninstall_action = menu.addAction(self.icon_manager.get_icon("delete"), f"卸载 '{module_display_name}'...")
            uninstall_action.triggered.connect(lambda: self.remove_module_file(row))
        # --- [修复结束] ---
        
        if not menu.isEmpty():
            menu.exec_(self.module_table.mapToGlobal(position))

    def toggle_module_enabled(self, module_key, enable):
        """
        [v2.1 - 修复版] 启用或禁用指定的模块。
        此版本会直接更新UI行状态，而不是触发全局刷新，以避免逻辑错误。
        """
        # 1. 更新配置文件中的 disabled_modules 列表
        app_settings = self.parent_window.config.setdefault("app_settings", {})
        disabled_list = app_settings.get("disabled_modules", [])
        
        if enable:
            if module_key in disabled_list:
                disabled_list.remove(module_key)
        else:
            if module_key not in disabled_list:
                disabled_list.append(module_key)
        
        app_settings["disabled_modules"] = disabled_list
        
        # --- [核心修复 2] ---
        # 2. 手动查找并更新UI中的对应行，而不是全局刷新
        for row in range(self.module_table.rowCount()):
            name_item = self.module_table.item(row, 1)
            if name_item and name_item.data(Qt.UserRole) == module_key:
                cell_widget = self.module_table.cellWidget(row, 0)
                if cell_widget:
                    icon_label = cell_widget.findChild(QLabel)
                    if icon_label:
                        if enable:
                            icon_label.setPixmap(self.icon_manager.get_icon("success").pixmap(QSize(24, 24)))
                            cell_widget.setToolTip("已启用")
                        else:
                            icon_label.setPixmap(self.icon_manager.get_icon("lock").pixmap(QSize(24, 24)))
                            cell_widget.setToolTip("已禁用")
                break # 找到并更新后即可退出循环
        # --- [修复结束] ---
        
        # 3. 启用保存按钮并更新右侧按钮状态
        self._on_setting_changed()
        self._update_module_buttons_state()

    def on_module_double_clicked(self, item):
        """
        双击模块行时，尝试打开其专属的设置对话框（如果存在）。
        """
        row = item.row()
        module_key = self.module_table.item(row, 1).data(Qt.UserRole) # 获取模块键名
        
        # 查找 MainWindow 中对应模块的页面实例
        target_page = None
        for attr_name in dir(self.parent_window):
            attr_value = getattr(self.parent_window, attr_name)
            # 检查这个属性是否是 QWidget，并且其 property("module_key") 匹配
            if isinstance(attr_value, QWidget) and attr_value.property("module_key") == module_key:
                target_page = attr_value
                break
        
        if target_page and hasattr(target_page, 'open_settings_dialog'):
            target_page.open_settings_dialog()
        else:
            QMessageBox.information(self, "无设置", f"模块 '{self.module_table.item(row, 1).text()}' 没有专属的设置页面。")

    def add_module(self):
        """
        通过文件对话框从外部文件系统添加新的模块文件到应用程序的模块目录。
        """
        filepaths, _ = QFileDialog.getOpenFileNames(self, "选择要添加的模块文件", "", "Python 文件 (*.py)")
        if not filepaths:
            return
            
        modules_dir = os.path.join(get_base_path_for_module(), "modules")
        added_count = 0
        for src_path in filepaths:
            try:
                dest_filename = os.path.basename(src_path)
                dest_path = os.path.join(modules_dir, dest_filename)
                
                if os.path.exists(dest_path):
                    QMessageBox.warning(self, "模块已存在", f"文件 '{dest_filename}' 已存在于模块目录中，已跳过。")
                    continue
                
                shutil.copy2(src_path, dest_path) # 复制文件
                added_count += 1
            except Exception as e:
                QMessageBox.critical(self, "添加失败", f"无法添加模块 '{os.path.basename(src_path)}':\n{e}")
        
        if added_count > 0:
            QMessageBox.information(self, "添加成功", f"成功添加 {added_count} 个新模块。\n请重启程序以加载它们。")
            self.populate_module_table() # 刷新表格以显示新添加的模块（状态为“未加载”）
            self._on_setting_changed() # 启用保存按钮，因为文件系统发生了变化

    def remove_module_file(self, row):
        """
        从模块目录中永久删除选中的模块文件。
        Args:
            row (int): 要删除模块所在的表格行索引。
        """
        name_item = self.module_table.item(row, 1)
        if not name_item: return
        
        module_key = name_item.data(Qt.UserRole)
        module_display_name = name_item.text()
        filename_on_disk = f"{module_key}.py" # 模块文件在磁盘上的实际名称通常是 key.py

        PROTECTED_MODULES = [
            'settings_module', 'plugin_system', 'icon_manager', 
            'custom_widgets_module', 'language_detector_module', 'shared_widgets_module'
        ]
        if module_key in PROTECTED_MODULES:
            QMessageBox.warning(self, "操作禁止", f"模块 '{module_display_name}' 是核心组件，不可移除。")
            return

        reply = QMessageBox.warning(self, "确认卸载", 
            f"您确定要永久删除模块 '{module_display_name}' 吗？\n\n文件 '{filename_on_disk}' 将被从磁盘上删除。\n此操作不可撤销！",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            try:
                filepath = os.path.join(get_base_path_for_module(), "modules", filename_on_disk)
                if os.path.exists(filepath):
                    os.remove(filepath) # 永久删除文件
                
                # 确保从配置的禁用列表中移除该模块的键
                app_settings = self.parent_window.config.setdefault("app_settings", {})
                disabled_list = app_settings.get("disabled_modules", [])
                if module_key in disabled_list:
                    disabled_list.remove(module_key)
                app_settings["disabled_modules"] = disabled_list # 确保更新回配置
                
                QMessageBox.information(self, "卸载成功", f"模块 '{module_display_name}' 已被成功删除。\n请重启程序以使更改生效。")
                self.populate_module_table() # 刷新表格
                self._on_setting_changed() # 启用保存按钮以保存配置更改
            except Exception as e:
                QMessageBox.critical(self, "卸载失败", f"无法删除模块文件:\n{e}")

# --- END OF FILE modules/settings_module.py ---