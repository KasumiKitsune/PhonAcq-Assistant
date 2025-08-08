# --- START OF FILE modules/dialect_visual_collector_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "看图说话采集"
MODULE_DESCRIPTION = "展示图片并录制方言描述，支持文字备注显隐及图片缩放。"
# ---

import os
import sys 
import threading
import queue
import time
import random
import shutil
import json
import subprocess # [新增] 用于打开文件夹
from collections import deque
from PyQt5.QtCore import pyqtSignal, Qt, QSize, QEvent, QTimer, QThread, QPoint
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QMessageBox, QComboBox, QFormLayout,
                             QGroupBox, QTextEdit, QSizePolicy, QProgressBar, QApplication,
                             QStyle, QSlider, QMenu, QLineEdit, QDialog, QCheckBox) # [修改] 新增 QDialog
from PyQt5.QtGui import QPixmap, QImageReader, QIcon, QColor, QPainter, QTransform, QPen

# [新增] 导入共享的自定义列表控件
from modules.custom_widgets_module import AnimatedListWidget

# 模块级别依赖检查
try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
    DEPENDENCIES_MISSING = False
except ImportError as e:
    print(f"CRITICAL: dialect_visual_collector_module.py - Missing dependencies: {e}")
    DEPENDENCIES_MISSING = True
    MISSING_ERROR_MESSAGE = str(e)


# 全局变量 - 词表目录路径
WORD_LIST_DIR_FOR_DIALECT_VISUAL = ""

# 模块入口函数
def create_page(parent_window, config, base_path, word_list_dir_visual, audio_record_dir_visual, 
                ToggleSwitchClass, WorkerClass, LoggerClass, icon_manager, resolve_device_func):
    global WORD_LIST_DIR_FOR_DIALECT_VISUAL
    WORD_LIST_DIR_FOR_DIALECT_VISUAL = word_list_dir_visual

    if DEPENDENCIES_MISSING:
        error_page = QWidget()
        layout = QVBoxLayout(error_page)
        label = QLabel(f"看图说话采集模块加载失败：\n缺少必要的依赖库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install sounddevice soundfile numpy")
        label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); layout.addWidget(label)
        return error_page
    
    return DialectVisualCollectorPage(parent_window, config, base_path, ToggleSwitchClass, WorkerClass, LoggerClass, icon_manager, resolve_device_func)

class ScalableImageLabel(QLabel):
    """
    可缩放和平移的图片显示控件，支持临时绘图功能。
    """
    zoom_changed = pyqtSignal(float) # 缩放比例改变时发出信号

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.pixmap = None
        self.scale_multiplier = 1.0 # 用户额外缩放倍数
        self.min_scale = 1.0        # 适应窗口的最小缩放倍数
        self.offset = QPoint(0, 0)  # 图片偏移量，用于平移
        self.panning = False        # 是否正在平移
        self.last_mouse_pos = QPoint() # 记录上次鼠标位置用于平移计算
        self.setMinimumSize(400, 300)
        self.setAlignment(Qt.AlignCenter)
        self.setObjectName("ScalableImageLabel")

        self.drawing_mode = False   # 是否处于绘图模式
        self.drawing = False        # 是否正在绘制
        self.drawn_paths = []       # 已完成的路径列表
        self.current_path = []      # 当前正在绘制的路径
        self.drawing_pen = QPen(QColor("#FF3B30"), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin) # 画笔样式

    def set_pixmap(self, pixmap):
        """设置要显示的图片，并重置视图和清除绘图。"""
        self.pixmap = pixmap
        self.clear_drawings() 
        self.reset_view()

    def clear_drawings(self):
        """清除所有绘制的路径。"""
        self.drawn_paths.clear()
        self.current_path.clear()
        self.update() # 刷新UI

    def toggle_drawing_mode(self, enabled):
        """启用或禁用绘图模式。"""
        self.drawing_mode = enabled
        if not enabled:
            self.clear_drawings() # 禁用时清除绘图
            self.setCursor(Qt.ArrowCursor) # 恢复默认光标
        else:
            self.setCursor(Qt.CrossCursor) # 绘图模式下显示十字光标

    def total_scale(self):
        """计算总的缩放比例（适应窗口 + 用户缩放）。"""
        return self.min_scale * self.scale_multiplier

    def set_zoom_level(self, level):
        """根据滑动条值设置缩放级别 (100 -> 1.0x, 200 -> 2.0x)。"""
        if not self.pixmap or self.pixmap.isNull(): return
        new_multiplier = level / 100.0
        # 避免极小的浮点数变化触发不必要的更新
        if abs(new_multiplier - self.scale_multiplier) > 0.001:
            self.scale_multiplier = new_multiplier
            self.clamp_offset() # 缩放后调整偏移量，防止图片滑出视图
            self.update()
            self.zoom_changed.emit(self.scale_multiplier)

    def _widget_pos_to_pixmap_pos(self, widget_pos):
        """将控件上的鼠标位置转换为图片上的对应像素位置。"""
        if not self.pixmap or self.pixmap.isNull(): return QPoint()
        current_total_scale = self.total_scale()
        if current_total_scale == 0: return QPoint()
        scaled_w = self.pixmap.width() * current_total_scale
        scaled_h = self.pixmap.height() * current_total_scale
        # 计算图片左上角在控件中的坐标
        top_left_in_widget = QPoint(int((self.width() - scaled_w) / 2 + self.offset.x()), 
                                    int((self.height() - scaled_h) / 2 + self.offset.y()))
        relative_pos = widget_pos - top_left_in_widget
        pixmap_pos = relative_pos / current_total_scale
        return pixmap_pos

    def calculate_min_scale(self):
        """计算图片在不裁剪的情况下适应控件尺寸的最小缩放比例。"""
        if not self.pixmap or self.pixmap.isNull() or self.width() <= 0 or self.height() <= 0: self.min_scale = 1.0; return
        pix_size = self.pixmap.size()
        if pix_size.width() <= 0 or pix_size.height() <= 0: self.min_scale = 1.0; return
        self.min_scale = min(self.width() / pix_size.width(), self.height() / pix_size.height())

    def reset_view(self):
        """重置视图到默认缩放（适应窗口）和居中位置。"""
        self.calculate_min_scale()
        self.scale_multiplier = 1.0
        self.offset = QPoint(0, 0)
        self.update()
        self.zoom_changed.emit(self.scale_multiplier)

    def wheelEvent(self, event):
        """鼠标滚轮事件，用于缩放图片。"""
        if not self.pixmap or self.pixmap.isNull(): return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15 # 根据滚轮方向确定缩放因子
        new_multiplier = self.scale_multiplier * factor
        if new_multiplier < 1.0: new_multiplier = 1.0 # 最小缩放为1.0x
        elif new_multiplier > 8.0: new_multiplier = 8.0 # 最大缩放为8.0x
        if abs(new_multiplier - self.scale_multiplier) > 0.001:
            self.scale_multiplier = new_multiplier
            self.clamp_offset()
            self.update()
            self.zoom_changed.emit(self.scale_multiplier)

    def mousePressEvent(self, event):
        """鼠标按下事件，处理平移和绘图的起始。"""
        if self.pixmap:
            if self.drawing_mode and event.button() == Qt.LeftButton:
                self.drawing = True
                # 记录鼠标在图片上的起始位置
                self.current_path = [self._widget_pos_to_pixmap_pos(event.pos())]
                self.update()
            elif event.button() == Qt.LeftButton:
                self.panning = True
                self.last_mouse_pos = event.pos()
                self.setCursor(Qt.ClosedHandCursor) # 平移时显示抓手光标

    def mouseMoveEvent(self, event):
        """鼠标移动事件，处理平移和绘图过程。"""
        if self.drawing:
            # 持续添加当前鼠标在图片上的位置到路径
            self.current_path.append(self._widget_pos_to_pixmap_pos(event.pos()))
            self.update()
        elif self.panning:
            current_total_scale = self.total_scale()
            scaled_w = self.pixmap.width() * current_total_scale
            scaled_h = self.pixmap.height() * current_total_scale
            # 只有当图片大于控件尺寸时才允许平移
            if scaled_w > self.width() or scaled_h > self.height():
                 delta = event.pos() - self.last_mouse_pos
                 self.offset += delta # 更新偏移量
                 self.last_mouse_pos = event.pos()
                 self.clamp_offset() # 限制偏移量，防止图片滑出可视区域
                 self.update()

    def mouseReleaseEvent(self, event):
        """鼠标释放事件，处理平移和绘图的结束。"""
        if self.drawing:
            self.drawing = False
            if self.current_path: self.drawn_paths.append(self.current_path) # 将当前路径添加到已绘制路径列表
            self.current_path = [] # 清空当前路径
            self.update()
        elif self.panning:
            self.panning = False
            # 根据是否在绘图模式恢复不同光标
            if self.drawing_mode: self.setCursor(Qt.CrossCursor)
            else: self.setCursor(Qt.ArrowCursor)

    def clamp_offset(self):
        """限制图片的平移偏移量，确保图片内容不会完全滑出可见区域。"""
        if not self.pixmap: return
        current_total_scale = self.total_scale()
        scaled_w = self.pixmap.width() * current_total_scale; scaled_h = self.pixmap.height() * current_total_scale
        center_x_margin = (self.width() - scaled_w) / 2; center_y_margin = (self.height() - scaled_h) / 2
        
        # X轴偏移量限制
        if scaled_w <= self.width(): self.offset.setX(0) # 图片比控件窄时，X轴不偏移
        else:
            max_offset_x = -center_x_margin
            min_offset_x = self.width() - scaled_w - center_x_margin
            if self.offset.x() > max_offset_x: self.offset.setX(int(max_offset_x))
            elif self.offset.x() < min_offset_x: self.offset.setX(int(min_offset_x))
        
        # Y轴偏移量限制
        if scaled_h <= self.height(): self.offset.setY(0) # 图片比控件矮时，Y轴不偏移
        else:
            max_offset_y = -center_y_margin
            min_offset_y = self.height() - scaled_h - center_y_margin
            if self.offset.y() > max_offset_y: self.offset.setY(int(max_offset_y))
            elif self.offset.y() < min_offset_y: self.offset.setY(int(min_offset_y))
    
    def paintEvent(self, event):
        """绘制图片和绘制路径。"""
        if not self.pixmap or self.pixmap.isNull():
            super().paintEvent(event) # 如果没有图片，则调用父类的绘制，显示文本
            return
        painter = QPainter(self); painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        current_total_scale = self.total_scale()
        scaled_pixmap_size = self.pixmap.size() * current_total_scale
        
        # 计算图片居中位置的起始坐标
        center_x = (self.width() - scaled_pixmap_size.width()) / 2
        center_y = (self.height() - scaled_pixmap_size.height()) / 2
        
        # 加上用户平移的偏移量
        draw_x = center_x + self.offset.x()
        draw_y = center_y + self.offset.y()
        
        # 绘制图片
        painter.drawPixmap(int(draw_x), int(draw_y), int(scaled_pixmap_size.width()), int(scaled_pixmap_size.height()), self.pixmap)
        
        # 绘制路径
        painter.setPen(self.drawing_pen)
        painter.save() # 保存画家的状态
        painter.translate(draw_x, draw_y) # 将坐标原点移动到图片绘制的左上角
        painter.scale(current_total_scale, current_total_scale) # 缩放坐标系，使绘图与图片同步缩放

        for path in self.drawn_paths:
            if len(path) > 1:
                for i in range(len(path) - 1): painter.drawLine(path[i], path[i+1])
        if self.current_path and len(self.current_path) > 1:
            for i in range(len(self.current_path) - 1): painter.drawLine(self.current_path[i], self.current_path[i+1])
        painter.restore() # 恢复画家状态

    def set_pen_width(self, width):
        """设置绘图画笔的宽度。"""
        self.drawing_pen.setWidth(width)

    def resizeEvent(self, event):
        """控件尺寸改变时触发，重置视图以适应新尺寸。"""
        self.reset_view()
        super().resizeEvent(event)

class DialectVisualCollectorPage(QWidget):
    """
    看图说话采集模块的主页面。
    允许用户加载图文词表，展示图片和提示文字，录制方言描述，并管理录音过程。
    """
    recording_device_error_signal = pyqtSignal(str) # 录音设备错误信号
    
    def __init__(self, parent_window, config, base_path, ToggleSwitchClass, WorkerClass, LoggerClass, icon_manager, resolve_device_func):
        super().__init__()
        self.parent_window = parent_window
        self.config = config
        self.BASE_PATH = base_path
        self.ToggleSwitch = ToggleSwitchClass
        self.Worker = WorkerClass
        self.Logger = LoggerClass
        self.icon_manager = icon_manager
        self.resolve_device_func = resolve_device_func # [新增] 保存解析设备函数

        self.session_active = False # 会话是否激活
        self.is_recording = False   # 是否正在录音
        self.original_items_list = [] # 原始加载的词表项目列表
        self.current_items_list = []  # 当前会话使用的词表项目列表（可能已打乱）
        self.current_item_index = -1  # 当前选中的项目索引
        self.current_wordlist_path = None # 当前词表文件完整路径
        self.current_wordlist_name = None # 当前词表文件名（含扩展名）
        self.current_audio_folder = None # 当前会话的录音输出文件夹
        self.audio_queue = queue.Queue() # 录音数据队列
        self.volume_meter_queue = queue.Queue(maxsize=2) # 音量计数据队列
        self.volume_history = deque(maxlen=5) # 音量历史，用于平滑显示
        self.recording_thread = None # 录音线程
        self.session_stop_event = threading.Event() # 会话停止事件
        self.logger = None # 日志记录器实例
        self.last_warning_log_time = 0 # 上次录音警告日志时间戳
        
        # [新增] 初始化固定词表列表
        # 这将从配置文件中加载，如果第一次运行则为空
        self.pinned_wordlists = [] 
        
        self._init_ui() # 初始化UI界面
        self._connect_signals() # 连接信号与槽
        self.update_icons() # 更新图标
        self.load_config_and_prepare() # 加载配置并准备界面

    def _init_ui(self):
        """初始化模块的用户界面布局和控件。"""
        main_layout = QHBoxLayout(self)

        # --- [布局修改 1/3] ---
        # 左侧面板：现在包含操作面板和项目列表
        self.left_panel = QWidget(); left_layout = QVBoxLayout(self.left_panel)
        
        # [核心修改] 将“操作面板”移动到左侧顶部
        control_group = QGroupBox("操作面板")
        # [核心修改] 使用 QVBoxLayout 实现标签和控件的换行
        control_v_layout = QVBoxLayout(control_group)
        control_v_layout.setContentsMargins(10, 10, 10, 10) # 调整内边距
        control_v_layout.setSpacing(8) # 调整控件间距

        # 图文词表选择部分
        control_v_layout.addWidget(QLabel("选择图文词表:"))
        self.word_list_select_btn = QPushButton("请选择图文词表...")
        self.word_list_select_btn.setToolTip("点击选择一个用于本次采集的图文词表。")
        control_v_layout.addWidget(self.word_list_select_btn)

        # 被试者名称部分
        control_v_layout.addWidget(QLabel("被试者名称:"))
        self.participant_input = QLineEdit(); self.participant_input.setPlaceholderText("例如: participant_1")
        self.participant_input.setToolTip("输入被试者的唯一标识符。\n此名称将用于创建结果文件夹。")
        control_v_layout.addWidget(self.participant_input)
        
        # 开始/结束按钮部分 (使用一个容器来切换)
        self.session_button_container = QWidget()
        self.session_button_layout = QVBoxLayout(self.session_button_container)
        self.session_button_layout.setContentsMargins(0, 5, 0, 0) # 顶部加一点间距
        self.start_btn = QPushButton("加载并开始"); self.start_btn.setObjectName("AccentButton"); self.start_btn.setToolTip("加载选中的图文词表，并开始一个新的采集会话。")
        self.end_session_btn = QPushButton("结束当前会话"); self.end_session_btn.setObjectName("ActionButton_Delete"); self.end_session_btn.setToolTip("提前结束当前的采集会话。"); self.end_session_btn.hide()
        self.session_button_layout.addWidget(self.start_btn)
        self.session_button_layout.addWidget(self.end_session_btn)
        control_v_layout.addWidget(self.session_button_container)
        
        # 将操作面板添加到左侧布局
        left_layout.addWidget(control_group)

        # 采集项目列表
        self.item_list_widget = QListWidget(); self.item_list_widget.setObjectName("DialectItemList"); self.item_list_widget.setWordWrap(True)
        self.item_list_widget.setToolTip("当前采集会话中的所有项目。\n绿色对勾表示已录制。\n点击可切换到对应项目。")
        
        # 状态标签
        self.status_label = QLabel("状态：请选择图文词表开始采集。"); self.status_label.setObjectName("StatusLabelModule"); self.status_label.setMinimumHeight(25); self.status_label.setWordWrap(True)
        
        # 将采集项目和状态标签添加到左侧布局
        left_layout.addWidget(QLabel("采集项目:"))
        left_layout.addWidget(self.item_list_widget, 1) # 列表占据剩余空间
        left_layout.addWidget(self.status_label)
        
        # 中央面板：(保持不变)
        center_panel = QWidget(); center_layout = QVBoxLayout(center_panel); center_layout.setContentsMargins(0, 0, 0, 0)
        self.image_viewer = ScalableImageLabel("图片区域"); self.image_viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding); self.image_viewer.setToolTip("显示当前项目的图片。\n使用鼠标滚轮进行缩放，按住并拖动鼠标进行平移。")
        self.prompt_text_label = QLabel("提示文字区域"); self.prompt_text_label.setObjectName("PromptTextLabel"); self.prompt_text_label.setAlignment(Qt.AlignCenter); self.prompt_text_label.setWordWrap(True); self.prompt_text_label.setFixedHeight(60)
        self.notes_text_edit = QTextEdit(); self.notes_text_edit.setObjectName("NotesTextEdit"); self.notes_text_edit.setReadOnly(True); self.notes_text_edit.setFixedHeight(120); self.notes_text_edit.setVisible(False)
        center_layout.addWidget(self.image_viewer, 1); center_layout.addWidget(self.prompt_text_label); center_layout.addWidget(self.notes_text_edit)
        
        # --- [布局修改 2/3] ---
        # 右侧面板：现在只包含会话选项、工具和录音状态
        self.right_panel = QWidget(); right_panel_layout = QVBoxLayout(self.right_panel)
        
        # 会话选项 (保持不变)
        options_group = QGroupBox("会话选项"); options_layout = QFormLayout(options_group)
        self.random_order_switch = self.ToggleSwitch(); self.random_order_switch.setToolTip("开启后，将打乱词表中所有项目的呈现顺序。\n此设置在会话开始后仍可更改。")
        random_order_layout = QHBoxLayout(); random_order_layout.addWidget(QLabel("随机顺序:")); random_order_layout.addStretch(); random_order_layout.addWidget(self.random_order_switch); options_layout.addRow(random_order_layout)
        self.show_prompt_switch = self.ToggleSwitch(); self.show_prompt_switch.setChecked(True); self.show_prompt_switch.setToolTip("控制是否在图片下方显示提示性描述文字。")
        show_prompt_layout = QHBoxLayout(); show_prompt_layout.addWidget(QLabel("显示描述:")); show_prompt_layout.addStretch(); show_prompt_layout.addWidget(self.show_prompt_switch); options_layout.addRow(show_prompt_layout)
        self.show_notes_switch = self.ToggleSwitch(); self.show_notes_switch.setToolTip("控制是否显示研究者备注。\n此备注信息仅研究者可见，不会展示给被试者。")
        show_notes_layout = QHBoxLayout(); show_notes_layout.addWidget(QLabel("显示备注:")); show_notes_layout.addStretch(); show_notes_layout.addWidget(self.show_notes_switch); options_layout.addRow(show_notes_layout)

        # 图片工具栏 (保持不变)
        self.image_tools_toggle_btn = QPushButton("▶ 图片工具")
        self.image_tools_toggle_btn.setCheckable(True); self.image_tools_toggle_btn.setChecked(False)
        self.image_tools_toggle_btn.setStyleSheet("QPushButton { text-align: left; font-weight: bold; padding: 5px; }")
        self.image_tools_container = QWidget(); image_tools_layout = QFormLayout(self.image_tools_container)
        image_tools_layout.setContentsMargins(10, 5, 5, 5)
        zoom_layout = QHBoxLayout()
        self.zoom_slider = QSlider(Qt.Horizontal); self.zoom_slider.setRange(100, 800); self.zoom_slider.setToolTip("拖动以缩放图片")
        self.zoom_label = QLabel("1.0x"); self.zoom_label.setFixedWidth(40)
        zoom_layout.addWidget(self.zoom_slider); zoom_layout.addWidget(self.zoom_label)
        image_tools_layout.addRow("缩放:", zoom_layout)
        self.draw_button = QPushButton("圈划"); self.draw_button.setCheckable(True); self.draw_button.setToolTip("启用/禁用临时绘图模式\n右键单击可选择画笔颜色")
        self.draw_button.setContextMenuPolicy(Qt.CustomContextMenu)
        pen_width_layout = QHBoxLayout()
        self.pen_width_slider = QSlider(Qt.Horizontal); self.pen_width_slider.setRange(2, 16); self.pen_width_slider.setValue(8)
        self.pen_width_slider.setToolTip("调整画笔粗细")
        self.pen_width_label = QLabel("8"); self.pen_width_label.setFixedWidth(30)
        pen_width_layout.addWidget(self.pen_width_slider); pen_width_layout.addWidget(self.pen_width_label)
        image_tools_layout.addRow(self.draw_button, pen_width_layout)
        self.image_tools_container.setVisible(False)

        # 录音状态面板 (保持不变)
        self.recording_status_panel = QGroupBox("录音状态"); status_panel_layout = QVBoxLayout(self.recording_status_panel)
        self.recording_indicator = QLabel("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_label = QLabel("当前音量:"); self.volume_meter = QProgressBar(); self.volume_meter.setRange(0,100); self.volume_meter.setValue(0); self.volume_meter.setTextVisible(False)
        status_panel_layout.addWidget(self.recording_indicator); status_panel_layout.addWidget(self.volume_label); status_panel_layout.addWidget(self.volume_meter)
        self.update_timer = QTimer(); self.update_timer.timeout.connect(self.update_volume_meter)
        
        # 录音按钮 (保持不变)
        self.record_btn = QPushButton("开始录音"); self.record_btn.setEnabled(False); self.record_btn.setFixedHeight(50); self.record_btn.setStyleSheet("QPushButton {font-size: 18px; font-weight: bold;}"); self.record_btn.setToolTip("点击开始录制当前项目。")
        
        # 将所有组和按钮添加到右侧面板布局
        right_panel_layout.addWidget(options_group)
        right_panel_layout.addWidget(self.image_tools_toggle_btn)
        right_panel_layout.addWidget(self.image_tools_container)
        right_panel_layout.addWidget(self.recording_status_panel)
        right_panel_layout.addStretch() # 伸缩器将录音按钮推到底部
        right_panel_layout.addWidget(self.record_btn)

        # --- [布局修改 3/3] ---
        # 将左右中面板添加到主布局
        main_layout.addWidget(self.left_panel) # 左侧面板宽度由内容和父窗口配置决定
        main_layout.addWidget(center_panel, 1) # 中心面板占据更多空间
        main_layout.addWidget(self.right_panel)
        self.setLayout(main_layout)

    def _toggle_image_tools_visibility(self, checked):
        """根据按钮的勾选状态，切换图片工具面板的可见性。"""
        self.image_tools_container.setVisible(checked)
        self.image_tools_toggle_btn.setText("▼ 图片工具" if checked else "▶ 图片工具")

    def _connect_signals(self):
        """连接所有UI控件的信号到对应的槽函数。"""
        # [修改] 连接新的词表选择按钮
        self.word_list_select_btn.clicked.connect(self.open_wordlist_selector) 
        self.start_btn.clicked.connect(self.start_session)
        self.end_session_btn.clicked.connect(self.end_session)
        self.record_btn.clicked.connect(self.handle_record_button)
        self.item_list_widget.currentItemChanged.connect(self.on_item_selected)
        self.show_notes_switch.stateChanged.connect(
            lambda state: self._on_persistent_setting_changed('show_notes', bool(state))
        )
        self.show_prompt_switch.stateChanged.connect(
            lambda state: self._on_persistent_setting_changed('show_prompt', bool(state))
        )
        self.random_order_switch.stateChanged.connect(
            lambda state: self._on_persistent_setting_changed('is_random', bool(state))
        )
        
        self.recording_device_error_signal.connect(self.show_recording_device_error)
        self.show_notes_switch.stateChanged.connect(self.toggle_notes_visibility)
        self.show_prompt_switch.stateChanged.connect(self.toggle_prompt_visibility)
        self.random_order_switch.stateChanged.connect(self.on_order_mode_changed)
        self.recording_device_error_signal.connect(self.show_recording_device_error)
        self.setFocusPolicy(Qt.StrongFocus) # 允许接收键盘事件

        # 图片工具相关信号
        self.image_tools_toggle_btn.toggled.connect(self._toggle_image_tools_visibility) 
        self.zoom_slider.valueChanged.connect(self.image_viewer.set_zoom_level)
        self.image_viewer.zoom_changed.connect(self.on_zoom_changed_by_viewer)
        self.draw_button.toggled.connect(self.on_draw_button_toggled)
        self.draw_button.customContextMenuRequested.connect(self.show_draw_color_menu)
        self.pen_width_slider.valueChanged.connect(self.image_viewer.set_pen_width)
        self.pen_width_slider.valueChanged.connect(lambda value: self.pen_width_label.setText(f"{value}"))

    def on_zoom_changed_by_viewer(self, multiplier):
        """图片查看器缩放比例改变时，更新滑动条和标签显示。"""
        self.zoom_slider.blockSignals(True) # 阻止信号回传，避免循环触发
        self.zoom_slider.setValue(int(multiplier * 100))
        self.zoom_slider.blockSignals(False)
        self.zoom_label.setText(f"{multiplier:.1f}x")

    def show_draw_color_menu(self, position):
        """显示绘图画笔颜色选择的上下文菜单。"""
        menu = QMenu()
        colors = {"红色": QColor("#FF3B30"), "黄色": QColor("#FFCC00"), "蓝色": QColor("#007AFF"), 
                  "绿色": QColor("#34C759"), "黑色": QColor("#000000"), "白色": QColor("#FFFFFF")}
        for name, color in colors.items():
            action = menu.addAction(name)
            pixmap = QPixmap(16, 16); pixmap.fill(color)
            action.setIcon(QIcon(pixmap)); action.setData(color) # 将颜色数据存储在action中
        
        # 显示菜单并获取选择的动作
        action = menu.exec_(self.draw_button.mapToGlobal(position))
        if action: 
            self.image_viewer.drawing_pen.setColor(action.data()) # 设置画笔颜色
            if self.image_viewer.drawing_mode: self.image_viewer.update() # 如果在绘图模式，立即更新显示

    def on_draw_button_toggled(self, checked):
        """绘图按钮切换状态时，更新按钮文本和图片查看器的绘图模式。"""
        if checked: self.draw_button.setText("禁用"); self.draw_button.setToolTip("禁用临时绘图模式")
        else: self.draw_button.setText("圈划"); self.draw_button.setToolTip("启用临时绘图模式\n右键单击可选择画笔颜色")
        self.image_viewer.toggle_drawing_mode(checked)

    def update_icons(self):
        """更新所有按钮和列表项的图标。"""
        self.start_btn.setIcon(self.icon_manager.get_icon("start_session"))
        self.end_session_btn.setIcon(self.icon_manager.get_icon("end_session"))
        self.record_btn.setIcon(self.icon_manager.get_icon("record"))
        self.draw_button.setIcon(self.icon_manager.get_icon("draw"))
        self.update_list_widget_icons()

    def update_list_widget_icons(self):
        """[核心修改] 重构为智能的、基于状态的图标更新函数。"""
        if not self.session_active: return
        
        # 获取质量分析器插件实例（如果已加载并存在）
        analyzer_plugin = getattr(self, 'quality_analyzer_plugin', None)
        
        for index, item_data in enumerate(self.current_items_list):
            list_item = self.item_list_widget.item(index)
            if not list_item: continue
            
            # 1. 检查录音文件是否存在
            recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower()
            main_audio_filename = f"{item_data.get('id')}.{recording_format}"
            wav_fallback_filename = f"{item_data.get('id')}.wav" # 考虑到可能的 WAV 回退
            is_recorded = self.current_audio_folder and \
                          (os.path.exists(os.path.join(self.current_audio_folder, main_audio_filename)) or \
                           os.path.exists(os.path.join(self.current_audio_folder, wav_fallback_filename)))
            
            if not is_recorded:
                list_item.setIcon(QIcon()) # 未录制，无图标
                list_item.setToolTip(item_data.get('id', '')) # 恢复原始Tooltip
                continue

            # 2. 如果已录制，检查质量警告
            warnings = item_data.get('quality_warnings', [])
            original_tooltip = item_data.get('id', '')

            if not warnings:
                list_item.setIcon(self.icon_manager.get_icon("success")) # 无警告，显示成功图标
                list_item.setToolTip(original_tooltip)
            else:
                if analyzer_plugin: # 如果质量分析器插件存在
                    # 检查是否有严重警告
                    has_critical = any(w['type'] in analyzer_plugin.critical_warnings for w in warnings)
                    list_item.setIcon(analyzer_plugin.warning_icon if has_critical else analyzer_plugin.info_icon)
                    
                    # 构建详细的HTML Tooltip
                    html = f"<b>{original_tooltip}</b><hr>"
                    html += "<b>质量报告:</b><br>"
                    warning_list_html = [f"• <b>{analyzer_plugin.warning_type_map.get(w['type'], w['type'])}:</b> {w['details']}" for w in warnings]
                    html += "<br>".join(warning_list_html)
                    list_item.setToolTip(html)
                else: # 插件未加载时的后备方案，显示成功图标
                    list_item.setIcon(self.icon_manager.get_icon("success"))
                    list_item.setToolTip(original_tooltip)

    # [新增] 质量分析器插件的回调接口
    def update_item_quality_status(self, row, warnings):
        """
        由质量分析器插件在分析完成后调用。
        此方法负责更新内部状态并触发UI刷新。
        :param row: 发生变化的列表项的索引。
        :param warnings: 该列表项对应的音频文件的警告列表。
        """
        if 0 <= row < len(self.current_items_list):
            self.current_items_list[row]['quality_warnings'] = warnings # 更新内部数据
            self.update_list_widget_icons() # 状态更新后，刷新整个列表的图标以反映变化

    def apply_layout_settings(self):
        """应用从配置中读取的UI布局设置。"""
        ui_settings = self.config.get("ui_settings", {})
        width = ui_settings.get("collector_sidebar_width", 320)
        self.left_panel.setFixedWidth(width)
        right_width = ui_settings.get("collector_right_sidebar_width", 300) 
        self.right_panel.setFixedWidth(right_width)
    def load_config_and_prepare(self):
        """加载应用程序配置，包括模块的持久化状态，并准备UI。"""
        self.config = self.parent_window.config
        self.apply_layout_settings()

        # [新增] 加载并应用已保存的模块状态
        module_states = self.config.get("module_states", {}).get("dialect_visual_collector", {})
        
        # [新增] 加载固定词表设置
        self.pinned_wordlists = module_states.get("pinned_wordlists", [])

        # blockSignals 确保在设置初始状态时不触发 stateChanged，避免不必要的写入
        self.random_order_switch.blockSignals(True)
        self.show_prompt_switch.blockSignals(True)
        self.show_notes_switch.blockSignals(True)
        
        # 从配置中读取值，如果找不到，则使用默认值
        self.random_order_switch.setChecked(module_states.get("is_random", False))
        self.show_prompt_switch.setChecked(module_states.get("show_prompt", True))
        self.show_notes_switch.setChecked(module_states.get("show_notes", False))
        
        self.random_order_switch.blockSignals(False)
        self.show_prompt_switch.blockSignals(False)
        self.show_notes_switch.blockSignals(False)
        
        # 触发一次初始的UI更新
        self.toggle_notes_visibility(self.show_notes_switch.isChecked())
        self.toggle_prompt_visibility(self.show_prompt_switch.isChecked())

        if not self.session_active:
            # [修改] 调用新的方法更新按钮文本，而不是填充ComboBox
            self._update_wordlist_button_display()
            default_participant = self.config.get('file_settings', {}).get('participant_base_name', 'participant')
            self.participant_input.setText(default_participant)

    def show_recording_device_error(self, error_message):
        """显示录音设备错误信息并禁用录音按钮。"""
        QMessageBox.critical(self, "录音设备错误", error_message)
        log_message = "录音设备错误，请检查设置。"
        self.log(log_message)
        if self.logger: self.logger.log(f"[FATAL] {log_message} Details: {error_message}")
        self.record_btn.setEnabled(False)
        if self.session_active: self.end_session(force=True) # 强制结束会话

    def keyPressEvent(self, event):
        """键盘按下事件处理。回车键用于触发录音/停止。"""
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.record_btn.isEnabled(): self.handle_record_button(); event.accept()
        else: super().keyPressEvent(event)

    def keyReleaseEvent(self, event): 
        """键盘释放事件。"""
        super().keyReleaseEvent(event)

    def handle_record_button(self):
        """处理录音按钮的点击事件（开始或停止录音）。"""
        if not self.session_active: return
        if not self.is_recording:
            self.current_item_index = self.item_list_widget.currentRow()
            if self.current_item_index == -1: self.log("请先在列表中选择一个项目！"); return
            
            # 禁用相关UI，防止录音过程中误操作
            self.item_list_widget.setEnabled(False)
            self.left_panel.setEnabled(False)
            self.random_order_switch.setEnabled(False)
            self._start_recording_logic()
            self.record_btn.setText("停止录音"); self.record_btn.setIcon(self.icon_manager.get_icon("stop"))
            self.record_btn.setToolTip("点击停止当前录音。")
        else:
            self._stop_recording_logic()
            self.record_btn.setText("保存中..."); self.record_btn.setEnabled(False)
            self.record_btn.setIcon(self.icon_manager.get_icon("record")) # 恢复默认图标

    def _start_recording_logic(self):
        """启动录音的内部逻辑。"""
        # 清空音频队列，防止旧数据残留
        while not self.audio_queue.empty():
            try: self.audio_queue.get_nowait()
            except queue.Empty: break
        
        self.is_recording = True
        self.recording_indicator.setText("● 正在录音"); self.recording_indicator.setStyleSheet("color: red;")
        item_id = self.current_items_list[self.current_item_index].get('id', '未知项目')
        self.log(f"录制项目: '{item_id}'")
        if self.logger: self.logger.log(f"[RECORD_START] Item ID: '{item_id}'")

    def _stop_recording_logic(self):
        """停止录音的内部逻辑，并触发保存任务。"""
        self.is_recording = False
        self.recording_indicator.setText("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.log("正在保存...")
        # 在单独线程中运行保存任务，避免UI阻塞
        self._run_task_in_thread(self._save_recording_task)

    def _format_list_item_text(self, item_id, prompt_text): 
        """格式化列表项显示文本。目前只显示ID。"""
        return item_id

    def toggle_notes_visibility(self, state): 
        """根据开关状态切换备注文本框的可见性。"""
        self.notes_text_edit.setVisible(state == Qt.Checked)

    def toggle_prompt_visibility(self, state): 
        """根据开关状态切换提示文字标签的可见性。"""
        self.prompt_text_label.setVisible(state == Qt.Checked)

    def on_order_mode_changed(self, state):
        """当随机/顺序模式切换时触发，重新排列列表并更新UI。"""
        if not self.session_active or not self.current_items_list: return
        
        current_id = None
        current_item = self.current_items_list[self.current_item_index] if 0 <= self.current_item_index < len(self.current_items_list) else None

        mode_text = "随机" if state else "顺序"
        self.log(f"项目顺序已切换为: {mode_text}")
        if self.logger: self.logger.log(f"[SESSION_CONFIG_CHANGE] Order changed to: {mode_text}")
        
        # [核心修改] 确保随机排序时，警告状态跟随意图项
        if state: # 随机模式
            random.shuffle(self.current_items_list)
        else: # 顺序模式，按原始ID顺序恢复
            # 创建一个原始ID到项的映射，方便排序
            original_id_map = {item.get('id'): item for item in self.original_items_list}
            # 使用原始顺序的ID来排序当前列表
            self.current_items_list.sort(key=lambda x: list(original_id_map.keys()).index(x.get('id')))

        # 找到当前选中项目在新列表中的位置
        new_row_index = next((i for i, item in enumerate(self.current_items_list) if item == current_item), 0) if current_item else 0
        self.current_item_index = new_row_index
        self.update_list_widget() # 刷新列表UI

    def on_item_selected(self, current_item, previous_item):
        """当列表中的项目被选中时，更新图片和文本显示。"""
        if not current_item or not self.session_active:
            self.image_viewer.set_pixmap(None)
            self.image_viewer.setText("请选择项目")
            self.prompt_text_label.setText("")
            self.notes_text_edit.setPlainText("")
            return
        
        if self.draw_button.isChecked(): self.draw_button.setChecked(False)
        
        self.current_item_index = self.item_list_widget.row(current_item)
        if self.current_item_index < 0 or self.current_item_index >= len(self.current_items_list): return

        item_data = self.current_items_list[self.current_item_index]
        wordlist_base_dir = os.path.dirname(self.current_wordlist_path)

        # 加载图片 (此部分逻辑保持不变)
        image_rel_path = item_data.get('image_path', '')
        image_full_path = os.path.join(wordlist_base_dir, image_rel_path) if image_rel_path else ''
        if image_full_path and os.path.exists(image_full_path):
            reader = QImageReader(image_full_path)
            reader.setAutoTransform(True)
            image = reader.read()
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                if not pixmap.isNull(): self.image_viewer.set_pixmap(pixmap)
                else: self.image_viewer.set_pixmap(None); self.image_viewer.setText(f"图片转换失败:\n{os.path.basename(image_rel_path)}")
            else: self.image_viewer.set_pixmap(None); self.image_viewer.setText(f"无法读取图片:\n{os.path.basename(image_rel_path)}\n错误: {reader.errorString()}")
        elif image_rel_path: 
            self.image_viewer.set_pixmap(None); self.image_viewer.setText(f"图片未找到:\n{image_rel_path}")
        else: 
            self.image_viewer.set_pixmap(None); self.image_viewer.setText("此项目无图片或路径未指定")
            self.on_zoom_changed_by_viewer(1.0)
        
        # 更新提示文字和备注
        self.prompt_text_label.setText(item_data.get('prompt_text', ''))
        self.notes_text_edit.setPlainText(item_data.get('notes', '无备注'))

        # --- [核心修复 v2.0] ---
        # 每次选择新项目并填充内容后，都立即根据开关的当前状态强制更新UI可见性。
        # 这可以解决在会话开始时，因时序问题导致已勾选的UI不显示的问题。
        self.prompt_text_label.setVisible(self.show_prompt_switch.isChecked())
        self.notes_text_edit.setVisible(self.show_notes_switch.isChecked())
        # --- [修复结束] ---

    def update_volume_meter(self):
        """更新音量计的显示，实现平滑效果。"""
        raw_target_value = 0
        try:
            data_chunk = self.volume_meter_queue.get_nowait()
            # 计算 RMS (Root Mean Square) 值作为音量
            rms = np.linalg.norm(data_chunk) / np.sqrt(len(data_chunk)) if data_chunk.any() else 0
            # 转换为 dBFS (decibels relative to full scale)
            dbfs = 20 * np.log10(rms + 1e-7) # 1e-7 防止 log(0) 错误
            # 将 dBFS 映射到 0-100 的进度条范围 (假设 -60dBFS 为 0，0dBFS 为 100)
            raw_target_value = max(0, min(100, (dbfs + 60) * (100 / 60)))
        except queue.Empty:
            raw_target_value = 0
        except Exception as e:
            print(f"Error calculating volume: {e}")
            raw_target_value = 0
 
        # 1. 防抖动：将新计算出的原始值添加到历史记录中
        self.volume_history.append(raw_target_value)
        
        # 2. 计算移动平均值作为我们新的、稳定的目标
        smoothed_target_value = sum(self.volume_history) / len(self.volume_history)
 
        # 3. 平滑动画：让当前值向“稳定的目标值”平滑过渡
        current_value = self.volume_meter.value()
        smoothing_factor = 0.4 # 平滑因子，值越大越平滑
        new_value = int(current_value * (1 - smoothing_factor) + smoothed_target_value * smoothing_factor)
        
        # 当接近目标值时，直接跳到目标值，避免抖动
        if abs(new_value - smoothed_target_value) < 2:
            new_value = int(smoothed_target_value)
            
        self.volume_meter.setValue(new_value)

    def log(self, msg):
        """在状态标签上显示信息。"""
        self.status_label.setText(f"状态: {msg}")

    # [删除] 移除了旧的 populate_word_lists 方法，因为它已被新的按钮和对话框取代

    def _update_wordlist_button_display(self):
        """
        [新增] 根据当前选择的词表更新按钮文本，或重置为默认值。
        取代了旧的 ComboBox 填充逻辑。
        """
        if self.current_wordlist_name:
            # 从完整路径中提取不带后缀的文件名用于显示
            base_name, _ = os.path.splitext(os.path.basename(self.current_wordlist_name))
            self.word_list_select_btn.setText(base_name)
            self.word_list_select_btn.setToolTip(f"当前选择: {self.current_wordlist_name}")
        else:
            self.word_list_select_btn.setText("请选择图文词表...")
            self.word_list_select_btn.setToolTip("点击选择一个用于本次采集的图文词表。")

    # [新增] 打开词表选择对话框的槽函数
    def open_wordlist_selector(self):
        """打开图文词表选择对话框。"""
        # 实例化内置的 WordlistSelectionDialog
        dialog = WordlistSelectionDialog(self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_file_relpath:
            self.current_wordlist_name = dialog.selected_file_relpath
            self._update_wordlist_button_display() # 更新按钮显示

    # [新增] 检查词表是否被固定的接口方法
    def is_wordlist_pinned(self, rel_path):
        """检查一个图文词表是否已被固定。"""
        return rel_path in self.pinned_wordlists

    # [新增] 切换词表固定状态的接口方法
    def toggle_pin_wordlist(self, rel_path):
        """固定或取消固定一个图文词表，并保存到配置。"""
        if self.is_wordlist_pinned(rel_path):
            self.pinned_wordlists.remove(rel_path)
        else:
            # 限制最多只能固定3个
            if len(self.pinned_wordlists) >= 3:
                QMessageBox.warning(self, "固定已达上限", "最多只能固定3个图文词表。")
                return
            self.pinned_wordlists.append(rel_path)
        self._save_pinned_wordlists() # 保存更改到配置文件

    # [新增] 保存固定词表列表到配置文件的辅助方法
    def _save_pinned_wordlists(self):
        """将当前的固定列表保存到 settings.json。"""
        self.parent_window.update_and_save_module_state(
            'dialect_visual_collector', # 模块的唯一标识符
            'pinned_wordlists',         # 要保存的键名
            self.pinned_wordlists      # 要保存的值
        )

    # [新增] 跨平台打开文件或目录的辅助方法
    def _open_system_default(self, path):
        """跨平台地使用系统默认程序打开文件或文件夹。"""
        try:
            if sys.platform == 'win32': os.startfile(os.path.realpath(path))
            elif sys.platform == 'darwin': subprocess.check_call(['open', path])
            else: subprocess.check_call(['xdg-open', path])
        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"无法打开路径: {path}\n错误: {e}")

    def reset_ui(self):
        """重置UI到会话未开始时的状态。"""
        # --- [核心修改] ---
        # 显示词表选择和被试者输入
        self.word_list_select_btn.show()
        self.participant_input.show()
        # 切换会话按钮的可见性
        self.start_btn.show()
        self.end_session_btn.hide()
        
        self.item_list_widget.clear()
        self.image_viewer.set_pixmap(None)
        self.image_viewer.setText("请加载图文词表")
        self.prompt_text_label.setText("")
        self.notes_text_edit.setPlainText("")
        self.notes_text_edit.setVisible(False)
        self.show_notes_switch.setChecked(False)
        self.record_btn.setEnabled(False)
        self.log("请选择图文词表开始采集。")
        self._update_wordlist_button_display()

    def end_session(self, force=False):
        """
        结束当前的采集会话。
        :param force: 如果为True，则不显示确认对话框，直接结束。
        """
        if not force:
            reply = QMessageBox.question(self, '结束会话', '您确定要结束当前的图文采集会话吗？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes: return
        
        if self.logger: self.logger.log("[SESSION_END] Session ended by user.")
        self.update_timer.stop() # 停止音量计更新定时器
        self.volume_meter.setValue(0) # 清空音量计
        self.session_stop_event.set() # 发送停止信号给录音线程

        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=1.0) # 等待录音线程结束
        self._cleanup_empty_session_folder()
        self.recording_thread = None
        self.session_active = False
        self.current_items_list = []
        self.original_items_list = []
        self.current_item_index = -1
        self.current_wordlist_path = None
        self.current_wordlist_name = None
        self.current_audio_folder = None
        self.logger = None
        self.reset_ui() # 重置UI

    def _cleanup_empty_session_folder(self):
        """
        [新增] 在会话结束时，根据设置检查并清理空会话文件夹。
        """
        module_states = self.config.get("module_states", {}).get("dialect_visual_collector", {})
        is_cleanup_enabled = module_states.get("cleanup_empty_folder", True)
        
        if not is_cleanup_enabled:
            return

        if not hasattr(self, 'current_audio_folder') or not os.path.isdir(self.current_audio_folder):
            return

        try:
            items_in_folder = os.listdir(self.current_audio_folder)
            audio_extensions = ('.wav', '.mp3', '.flac', '.ogg', '.m4a')
            has_audio_files = any(item.lower().endswith(audio_extensions) for item in items_in_folder)
            
            if has_audio_files:
                return

            other_files = [
                item for item in items_in_folder 
                if not item.lower().endswith(audio_extensions) and os.path.isfile(os.path.join(self.current_audio_folder, item))
            ]
            
            if not other_files or (len(other_files) == 1 and other_files[0] == 'log.txt'):
                folder_to_delete = self.current_audio_folder
                
                self.log("会话结束。已自动清理空的结果文件夹。")
                if self.logger:
                    self.logger.log(f"[CLEANUP] Session folder '{os.path.basename(folder_to_delete)}' contains no audio. Deleting.")
                
                shutil.rmtree(folder_to_delete)
                print(f"[INFO] Cleaned up empty session folder: {folder_to_delete}")

        except Exception as e:
            print(f"[ERROR] Failed to cleanup empty session folder '{self.current_audio_folder}': {e}")

    def start_session(self):
        """
        开始一个新的采集会话。
        此方法负责加载词表、创建结果文件夹、初始化日志和启动后台录音线程。
        """
        # [修改] 从实例变量获取当前选中的词表文件名，而不是从UI控件
        wordlist_file = self.current_wordlist_name 
        if not wordlist_file: 
            QMessageBox.warning(self, "错误", "请先选择一个图文词表。")
            return
        
        participant_name = self.participant_input.text().strip()
        if not participant_name: 
            QMessageBox.warning(self, "输入错误", "请输入被试者名称。")
            return
        
        try:
            self.current_wordlist_name = wordlist_file
            # 加载词表，并在每个项目初始化时添加一个空的 'quality_warnings' 列表，供插件使用
            original_items = self.load_word_list_logic(wordlist_file)
            self.original_items_list = [{'quality_warnings': [], **item} for item in original_items]
            
            if not self.original_items_list: 
                QMessageBox.warning(self, "错误", f"词表 '{wordlist_file}' 为空或加载失败。")
                return
            
            # 复制一份作为当前会话列表，如果开启随机模式，则打乱顺序
            self.current_items_list = list(self.original_items_list)
            if self.random_order_switch.isChecked(): 
                random.shuffle(self.current_items_list)
            
            # 确定并创建结果输出目录，处理重名情况
            results_base_dir = self.config.get('file_settings', {}).get('results_dir', os.path.join(self.BASE_PATH, "Results"))
            visual_results_dir = os.path.join(results_base_dir, "visual")
            os.makedirs(visual_results_dir, exist_ok=True)
            
            wordlist_name_no_ext, _ = os.path.splitext(self.current_wordlist_name)
            base_folder_name = f"{participant_name}-{wordlist_name_no_ext}"
            
            i = 1
            folder_name = base_folder_name
            while os.path.exists(os.path.join(visual_results_dir, folder_name)): 
                folder_name = f"{base_folder_name}_{i}"
                i += 1
            self.current_audio_folder = os.path.join(visual_results_dir, folder_name)
            os.makedirs(self.current_audio_folder, exist_ok=True)
            
            # 根据全局设置，初始化日志记录器
            self.logger = None
            if self.config.get("app_settings", {}).get("enable_logging", True): 
                self.logger = self.Logger(os.path.join(self.current_audio_folder, "log.txt"))
            if self.logger:
                mode = "Random" if self.random_order_switch.isChecked() else "Sequential"
                self.logger.log(f"[SESSION_START] Dialect visual collection for wordlist: {self.current_wordlist_name}")
                self.logger.log(f"[SESSION_CONFIG] Participant: '{participant_name}', Output folder: '{self.current_audio_folder}', Mode: {mode}")

            # --- [修改] 应用“音量计刷新间隔”设置 ---
            # 从配置中读取刷新间隔，如果不存在则使用默认值 16ms
            module_states = self.config.get("module_states", {}).get("dialect_visual_collector", {})
            interval = module_states.get("volume_meter_interval", 16)
            self.update_timer.setInterval(interval)

            # 启动持久化录音线程和音量计更新定时器
            self.session_stop_event.clear()
            self.recording_thread = threading.Thread(target=self._persistent_recorder_task, daemon=True)
            self.recording_thread.start()
            self.update_timer.start() # 直接启动，不再需要传入间隔
            
            # 更新UI状态以反映会话已开始
            self.word_list_select_btn.hide() 
            self.participant_input.hide()
            self.start_btn.hide()
            self.end_session_btn.show()
            self.end_session_btn.setIcon(self.icon_manager.get_icon("end_session"))

            # 延迟更新列表，确保UI稳定
            QTimer.singleShot(0, self.update_list_widget)
            
            # 启用录音按钮并更新状态
            self.record_btn.setEnabled(True)
            self.log("准备就绪，请选择项目并开始录音。")
            self.session_active = True

        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动会话失败: {e}")
            self.session_active = False
            if hasattr(self, 'logger') and self.logger: self.logger.log(f"[ERROR] Failed to start session: {e}")

    def open_settings_dialog(self):
        """
        [新增] 打开此模块的设置对话框，并在确认后请求主窗口进行彻底刷新，
        以确保所有设置（特别是性能相关设置）能被正确应用。
        """
        # 实例化我们新创建的 SettingsDialog
        dialog = SettingsDialog(self)
        
        # 对话框关闭后，如果用户点击了"OK"
        if dialog.exec_() == QDialog.Accepted:
            # 调用主窗口提供的公共API来刷新自己。
            # 这会重新加载配置并应用所有新设置。
            self.parent_window.request_tab_refresh(self)

    def update_list_widget(self):
        """刷新项目列表widget的显示内容。"""
        current_row = self.item_list_widget.currentRow() if self.item_list_widget.count() > 0 else 0
        self.item_list_widget.clear() # 清空现有列表项
        
        for index, item_data in enumerate(self.current_items_list):
            display_text = self._format_list_item_text(item_data.get('id', f"项目_{index+1}"), item_data.get('prompt_text', ''))
            self.item_list_widget.addItem(QListWidgetItem(display_text))
        
        self.update_list_widget_icons() # 更新列表项的图标（成功/警告）

        # 重新选中之前的项目，或选中第一个项目
        if self.current_items_list and 0 <= current_row < len(self.current_items_list):
             self.item_list_widget.setCurrentRow(current_row)
             selected_item_to_display = self.item_list_widget.item(current_row)
             if selected_item_to_display: self.on_item_selected(selected_item_to_display, None) # 触发选中事件

    def on_recording_saved(self, result):
        """
        录音保存任务完成后调用的槽函数。
        :param result: 保存任务的结果，例如错误信息或None。
        """
        # 1. 恢复UI状态
        self.record_btn.setText("开始录音")
        self.record_btn.setToolTip("点击开始录制当前项目。")
        self.record_btn.setEnabled(True)
        self.item_list_widget.setEnabled(True)
        self.left_panel.setEnabled(True)
        self.random_order_switch.setEnabled(True)
    
        # 2. 处理保存失败的情况 (MP3编码器缺失)
        if result == "save_failed_mp3_encoder":
            QMessageBox.critical(self, "MP3 编码器缺失", "无法将录音保存为 MP3 格式。\n\n建议：请在“程序设置”中将录音格式切换为 WAV (高质量)，或为您的系统安装 LAME 编码器。")
            self.log("MP3保存失败！请检查编码器或设置。")
            return
        
        self.log("录音已保存。")
    
        # 3. 准备调用插件进行质量分析
        analyzer_plugin = getattr(self, 'quality_analyzer_plugin', None)
        if analyzer_plugin and self.current_audio_folder:
            recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower()
            item_id = self.current_items_list[self.current_item_index].get('id')
            filepath = os.path.join(self.current_audio_folder, f"{item_id}.{recording_format}")
        
            # 处理回退保存为WAV的情况
            if not os.path.exists(filepath) and recording_format != 'wav':
                filepath = os.path.join(self.current_audio_folder, f"{item_id}.wav")

            if os.path.exists(filepath):
                # 4. [核心修改] 调用插件进行分析，分析结果将通过回调函数 update_item_quality_status 返回
                analyzer_plugin.analyze_and_update_ui('dialect_visual_collector', filepath, self.current_item_index)
            else:
                # 如果文件都找不到，直接刷新UI显示成功对勾
                self.update_list_widget_icons()
        else:
            # 如果插件不存在，也刷新UI显示成功对勾
            self.update_list_widget_icons()
            
        module_states = self.config.get("module_states", {}).get("dialect_visual_collector", {})
        auto_advance_enabled = module_states.get("auto_advance", True)

        if auto_advance_enabled:
            # 5. 移动到下一个项目
            if self.current_item_index + 1 < len(self.current_items_list):
                self.item_list_widget.setCurrentRow(self.current_item_index + 1)
            else:
                # 检查是否所有项目都已录制
                all_done = True
                recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower()
                for item_data in self.current_items_list:
                    main_audio_filename = f"{item_data.get('id')}.{recording_format}"
                    wav_fallback_filename = f"{item_data.get('id')}.wav"
                    if not os.path.exists(os.path.join(self.current_audio_folder, main_audio_filename)) and not os.path.exists(os.path.join(self.current_audio_folder, wav_fallback_filename)):
                        all_done = False; break
                if all_done:
                    QMessageBox.information(self, "完成", "所有项目已录制完毕！")
                    if self.session_active: self.end_session()

    def _persistent_recorder_task(self):
        """
        在后台线程中运行的持久化录音任务。
        负责启动和管理音频输入流。
        """
        try:
            # [修改] 调用解析函数来获取设备索引，而不是直接读取配置
            device_index = self.resolve_device_func(self.config)
            
            sr = self.config.get('audio_settings', {}).get('sample_rate', 44100)
            ch = self.config.get('audio_settings', {}).get('channels', 1)
            
            # 使用 sounddevice.InputStream 启动音频流
            with sd.InputStream(device=device_index, samplerate=sr, channels=ch, callback=self._audio_callback):
                self.session_stop_event.wait() # 阻塞线程，直到收到停止信号
        except Exception as e: 
            error_msg = f"无法启动录音，请检查设备设置或权限。\n错误详情: {e}"
            print(f"持久化录音线程错误: {error_msg}")
            if self.logger: self.logger.log(f"[FATAL_ERROR] Cannot start audio stream: {e}")
            self.recording_device_error_signal.emit(error_msg) # 通过信号通知主线程显示错误

    def _audio_callback(self, indata, frames, time_info, status):
        """Sounddevice 音频输入回调函数，在每个音频块到达时触发。"""
        if status:
            # 如果有警告或错误状态，打印并记录
            current_time = time.monotonic()
            if current_time - self.last_warning_log_time > 5: # 每5秒记录一次，避免日志泛滥
                self.last_warning_log_time = current_time
                warning_msg = f"Audio callback status: {status}"
                print(warning_msg, file=sys.stderr)
                if self.logger: self.logger.log(f"[WARNING] {warning_msg}")
 
        # 1. 将原始、未经修改的数据放入录音队列，用于最终保存。
        if self.is_recording:
            try:
                self.audio_queue.put(indata.copy())
            except queue.Full:
                pass # 队列满时丢弃，防止阻塞

        # 2. 创建一个临时副本，应用增益，然后放入音量条队列，用于UI实时反馈。
        gain = self.config.get('audio_settings', {}).get('recording_gain', 1.0)
        
        processed_for_meter = indata
        if gain != 1.0:
            # 应用增益并裁剪到有效范围 [-1.0, 1.0]
            processed_for_meter = np.clip(indata * gain, -1.0, 1.0)
 
        try:
            self.volume_meter_queue.put_nowait(processed_for_meter.copy())
        except queue.Full:
            pass # 队列满时丢弃，防止阻塞

    def _save_recording_task(self, worker_instance):
        """
        在工作线程中执行的录音保存任务。
        :param worker_instance: 传递工作器实例，以便可以通过其信号报告进度/错误。
        """
        if self.audio_queue.empty(): return None # 如果队列为空，没有数据可保存

        data_chunks = []
        while not self.audio_queue.empty():
            try: data_chunks.append(self.audio_queue.get_nowait())
            except queue.Empty: break
        
        if not data_chunks: return None # 再次检查是否收集到数据
        
        rec = np.concatenate(data_chunks, axis=0) # 将所有音频数据块拼接起来
        
        gain = self.config.get('audio_settings', {}).get('recording_gain', 1.0)
        if gain != 1.0: rec = np.clip(rec * gain, -1.0, 1.0) # 再次应用增益并裁剪

        recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower()
        item_id = self.current_items_list[self.current_item_index].get('id', f"item_{self.current_item_index + 1}")
        filename = f"{item_id}.{recording_format}"
        filepath = os.path.join(self.current_audio_folder, filename)
        
        if self.logger: self.logger.log(f"[RECORDING_SAVE_ATTEMPT] Item ID: '{item_id}', Format: '{recording_format}', Path: '{filepath}'")
        
        try:
            sr = self.config.get('audio_settings', {}).get('sample_rate', 44100)
            sf.write(filepath, rec, sr) # 保存音频文件
            if self.logger: self.logger.log("[RECORDING_SAVE_SUCCESS] File saved successfully.")
            return None # 成功保存，返回None
        except Exception as e:
            if self.logger: self.logger.log(f"[ERROR] Failed to save {recording_format.upper()}: {e}")
            
            if recording_format == 'mp3' and 'format not understood' in str(e).lower(): 
                return "save_failed_mp3_encoder" # 特定错误提示
            
            # 尝试回退到 WAV 格式保存
            if recording_format != 'wav':
                try:
                    wav_path = os.path.splitext(filepath)[0] + ".wav"
                    sf.write(wav_path, rec, sr)
                    self.log(f"已尝试回退保存为WAV: {os.path.basename(wav_path)}")
                    if self.logger: self.logger.log(f"[RECORDING_SAVE_FALLBACK] Fallback WAV saved: {wav_path}")
                except Exception as e_wav: 
                    self.log(f"回退保存WAV也失败: {e_wav}")
                    if self.logger: self.logger.log(f"[ERROR] Fallback WAV save also failed: {e_wav}")
        return None

    def _run_task_in_thread(self, task_func, *args):
        """
        在新的QThread中运行给定的任务函数。
        :param task_func: 要执行的任务函数。
        :param args: 任务函数所需的参数。
        """
        self.thread = QThread()
        self.worker = self.Worker(task_func, *args) # 实例化工作器
        self.worker.moveToThread(self.thread) # 将工作器移动到新线程

        # 连接信号：线程启动 -> 工作器运行；工作器完成 -> 线程退出；工作器完成 -> 销毁工作器；线程结束 -> 销毁线程
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.error.connect(lambda msg:QMessageBox.critical(self,"后台错误",msg)) # 错误处理

        # 根据任务函数连接不同的完成信号
        if task_func == self._save_recording_task: 
            self.worker.finished.connect(self.on_recording_saved)
        
        self.thread.start() # 启动线程

    def load_word_list_logic(self, filename_from_combo):
        """
        加载并解析指定的图文词表JSON文件。
        :param filename_from_combo: 从UI选择的词表文件名 (相对路径)。
        :return: 解析后的词表项目列表。
        :raises FileNotFoundError: 如果文件不存在。
        :raises ValueError: 如果文件不是有效的JSON或格式不正确。
        """
        # [修改] 使用全局变量 WORD_LIST_DIR_FOR_DIALECT_VISUAL 来构建完整路径
        self.current_wordlist_path = os.path.join(WORD_LIST_DIR_FOR_DIALECT_VISUAL, filename_from_combo)
        if not os.path.exists(self.current_wordlist_path):
            raise FileNotFoundError(f"找不到图文词表文件: {self.current_wordlist_path}")

        try:
            with open(self.current_wordlist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"词表文件 '{filename_from_combo}' 不是有效的JSON格式: {e}")
        
        # 验证文件格式
        if "meta" not in data or data.get("meta", {}).get("format") != "visual_wordlist" or "items" not in data:
             raise ValueError(f"词表文件 '{filename_from_combo}' 格式不正确或不受支持。")
        
        items_list = data.get("items", [])
        if not isinstance(items_list, list):
             raise ValueError(f"词表文件 '{filename_from_combo}' 中的 'items' 必须是一个列表。")
             
        return items_list

    def _on_persistent_setting_changed(self, key, value):
        """
        当模块的持久化设置改变时调用，通知主窗口保存配置。
        :param key: 设置项的键。
        :param value: 设置项的新值。
        """
        # 1. 调用主窗口的API来保存状态
        # 'dialect_visual_collector' 是这个模块在配置文件中的唯一标识符，必须唯一
        self.parent_window.update_and_save_module_state('dialect_visual_collector', key, value)
        
        # 2. 调用原有的响应逻辑，以确保UI实时更新
        if key == 'show_notes':
            self.toggle_notes_visibility(value)
        elif key == 'show_prompt':
            self.toggle_prompt_visibility(value)
        elif key == 'is_random' and self.session_active:
            self.on_order_mode_changed(value)

# [新增] 内置的、为图文词表定制的词表选择对话框
class WordlistSelectionDialog(QDialog):
    """
    一个内置于本模块的、弹出式的对话框，使用 AnimatedListWidget 来提供层级式词表选择。
    此版本经过适配，专门用于“看图说话采集”模块。
    """
    
    def __init__(self, parent_page):
        super().__init__(parent_page)
        self.parent_page = parent_page
        self.selected_file_relpath = None 
        self._all_items_cache = [] # 缓存所有词表数据，用于搜索

        self.setWindowTitle("选择图文词表")
        self.setWindowIcon(self.parent_page.parent_window.windowIcon())
        self.setStyleSheet(self.parent_page.parent_window.styleSheet())
        self.setMinimumSize(400, 500)
        
        self._init_ui()
        self._connect_signals()
        self.populate_list() # 填充词表列表

    def _init_ui(self):
        """构建对话框的用户界面。"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        container_groupbox = QGroupBox("可用的图文词表")
        container_layout = QVBoxLayout(container_groupbox)
        container_layout.setContentsMargins(10, 15, 10, 10)
        container_layout.setSpacing(8)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索词表 (例如: family)...")
        self.search_input.setClearButtonEnabled(True) # 显示清除按钮
        self.search_input.setObjectName("WordlistSearchInput")

        self.list_widget = AnimatedListWidget(icon_manager=self.parent_page.icon_manager)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu) # 启用上下文菜单

        container_layout.addWidget(self.search_input)
        container_layout.addWidget(self.list_widget)
        main_layout.addWidget(container_groupbox)

    def _connect_signals(self):
        """连接所有UI控件的信号到对应的槽函数。"""
        self.list_widget.item_activated.connect(self.on_item_selected) # 双击或回车选中
        self.search_input.textChanged.connect(self._filter_list) # 搜索框文本变化时过滤列表
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu) # 右键菜单

    def on_item_selected(self, item):
        """当用户通过双击或回车选择一个文件后，存储其相对路径并关闭对话框。"""
        item_data = item.data(AnimatedListWidget.HIERARCHY_DATA_ROLE)
        full_path = item_data.get('data', {}).get('path')
        if full_path:
            # [核心适配] 使用本模块的全局路径变量来计算相对路径
            rel_path = os.path.relpath(full_path, WORD_LIST_DIR_FOR_DIALECT_VISUAL)
            self.selected_file_relpath = rel_path.replace("\\", "/") # 统一路径分隔符
            self.accept() # 接受并关闭对话框

    def _filter_list(self, text):
        """根据搜索框的文本实时过滤列表显示内容。"""
        search_term = text.strip().lower()
        if not search_term:
            # 如果搜索框为空，恢复到当前导航堆栈顶部的层级
            if self.list_widget._navigation_stack:
                 top_level_data = self.list_widget._navigation_stack[0]
                 self.list_widget._populate_list_with_animation(top_level_data)
            return
        
        # 从缓存中查找匹配项
        matching_items = [item for item in self._all_items_cache if search_term in item['search_text']]
        # 为了搜索结果显示更友好，将路径中的斜杠替换为 " / "
        for item in matching_items:
            item['text'] = item['search_text'].replace("/", " / ")
        self.list_widget._populate_list_with_animation(matching_items) # 显示搜索结果

    def show_context_menu(self, position):
        """当用户在列表上右键单击时，显示上下文菜单。"""
        item = self.list_widget.itemAt(position)
        if not item: return
        item_data = item.data(AnimatedListWidget.HIERARCHY_DATA_ROLE)
        if not item_data: return

        item_type = item_data.get('type')
        full_path = item_data.get('data', {}).get('path')
        icon_manager = self.parent_page.icon_manager
        menu = QMenu(self.list_widget)

        if item_type == 'item': # 如果右键点击的是词表文件
            # [核心适配] 使用本模块的全局路径变量来计算相对路径
            rel_path = os.path.relpath(full_path, WORD_LIST_DIR_FOR_DIALECT_VISUAL).replace("\\", "/")
            is_pinned = self.parent_page.is_wordlist_pinned(rel_path)
            
            # 固定/取消固定动作
            pin_action = menu.addAction(icon_manager.get_icon("unpin" if is_pinned else "pin"), 
                                        "取消固定" if is_pinned else "固定到顶部")
            menu.addSeparator()
            # 打开所在目录动作
            open_folder_action = menu.addAction(icon_manager.get_icon("open_folder"), "打开所在目录")
            
            action = menu.exec_(self.list_widget.mapToGlobal(position)) # 显示并等待用户选择
            if action == pin_action:
                self.parent_page.toggle_pin_wordlist(rel_path) # 调用父页面的方法切换固定状态
                self.populate_list() # 刷新列表以显示固定状态变化
            elif action == open_folder_action: 
                self.parent_page._open_system_default(os.path.dirname(full_path)) # 调用父页面的方法打开目录
    
    def populate_list(self):
        """扫描图文词表目录，构建一个包含固定项快捷方式和层级浏览区的列表。"""
        # [核心适配] 使用本模块的全局路径变量
        base_dir = WORD_LIST_DIR_FOR_DIALECT_VISUAL
        icon_manager = self.parent_page.icon_manager
        
        pinned_shortcuts, regular_items = [], []
        self._all_items_cache.clear() # 清空缓存
        folder_map = {} # 用于构建文件夹层级结构

        try:
            for root, _, files in os.walk(base_dir):
                for filename in files:
                    if not filename.endswith('.json'): continue # 只处理JSON文件
                    
                    full_path = os.path.join(root, filename)
                    # [核心适配] 使用本模块的全局路径变量
                    rel_path = os.path.relpath(full_path, base_dir).replace("\\", "/")
                    display_name, _ = os.path.splitext(filename) # 移除 .json 后缀
                    is_pinned = self.parent_page.is_wordlist_pinned(rel_path)
                    
                    item_data = {'type': 'item', 'icon': icon_manager.get_icon("document"), 'data': {'path': full_path}}
                    
                    if is_pinned:
                        shortcut = item_data.copy()
                        shortcut['icon'] = icon_manager.get_icon("pin") # 固定项显示图钉图标
                        # 如果不是根目录下的文件，显示 "父文件夹 / 文件名" 格式
                        shortcut['text'] = f"{os.path.basename(root)} / {display_name}" if root != base_dir else display_name
                        pinned_shortcuts.append(shortcut)
                    else:
                        item_data['text'] = display_name
                        if root not in folder_map: folder_map[root] = []
                        folder_map[root].append(item_data)
                    
                    # 构建用于搜索的文本，包含完整路径信息
                    search_item = item_data.copy()
                    search_item['search_text'] = f"{os.path.basename(root)}/{display_name}".lower() if root != base_dir else display_name.lower()
                    self._all_items_cache.append(search_item)
            
            # 处理根目录下的文件
            if base_dir in folder_map:
                root_files = sorted(folder_map[base_dir], key=lambda x: x['text'])
                regular_items.extend(root_files)
                del folder_map[base_dir] # 从文件夹映射中移除根目录
            
            # 处理子文件夹
            for folder_path in sorted(folder_map.keys()):
                children = sorted(folder_map[folder_path], key=lambda x: x['text'])
                regular_items.append({'type': 'folder', 'text': os.path.basename(folder_path), 
                                      'icon': icon_manager.get_icon("folder"), 'children': children})
            
            # 排序：文件夹在前，然后是文件，按文本排序
            regular_items.sort(key=lambda x: (x['type'] != 'folder', x['text']))
            pinned_shortcuts.sort(key=lambda x: x['text']) # 固定项也排序

            # 将所有数据设置到 AnimatedListWidget
            self.list_widget.setHierarchicalData(pinned_shortcuts + regular_items)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"扫描并构建图文词表列表时发生错误: {e}")
# --- [核心新增] ---
# 为“看图说话采集”模块定制的设置对话框
class SettingsDialog(QDialog):
    """
    一个专门用于配置“看图说话采集”模块的对话框。
    """
    def __init__(self, parent_page):
        # parent_page 是 DialectVisualCollectorPage 的实例
        super().__init__(parent_page)
        
        self.parent_page = parent_page
        self.setWindowTitle("看图说话采集设置")
        self.setWindowIcon(self.parent_page.parent_window.windowIcon())
        self.setStyleSheet(self.parent_page.parent_window.styleSheet())
        self.setMinimumWidth(400)
        
        # 主布局
        layout = QVBoxLayout(self)
        
        # --- 组1: 工作流设置 ---
        workflow_group = QGroupBox("工作流设置")
        workflow_form_layout = QFormLayout(workflow_group)
        
        self.auto_advance_checkbox = QCheckBox("录制后自动前进到下一项")
        self.auto_advance_checkbox.setToolTip("勾选后，成功录制一个项目后，列表会自动跳转到下一个未录制的项目。\n取消勾选则停留在当前项，方便检查或重录。")
        
        self.cleanup_empty_folder_checkbox = QCheckBox("自动清理未录音的会话文件夹")
        self.cleanup_empty_folder_checkbox.setToolTip("勾选后，如果一个会话结束时没有录制任何音频，\n其对应的结果文件夹将被自动删除，以保持目录整洁。")
        
        workflow_form_layout.addRow(self.auto_advance_checkbox)
        workflow_form_layout.addRow(self.cleanup_empty_folder_checkbox)
        
        layout.addWidget(workflow_group)

        # --- 组2: 界面与性能 ---
        ui_perf_group = QGroupBox("界面与性能")
        ui_perf_form_layout = QFormLayout(ui_perf_group)
        
        # 音量计刷新率 Slider
        volume_slider_layout = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(10, 100) # 10ms (100Hz) - 100ms (10Hz)
        self.volume_slider.setTickInterval(10)
        self.volume_slider.setTickPosition(QSlider.TicksBelow)
        self.volume_slider.setToolTip("调整音量计UI的更新频率。\n值越小反馈越实时，但可能消耗更多CPU资源。")
        self.volume_slider_label = QLabel("16 ms") # 默认值
        self.volume_slider.valueChanged.connect(lambda v: self.volume_slider_label.setText(f"{v} ms"))
        
        volume_slider_layout.addWidget(self.volume_slider)
        volume_slider_layout.addWidget(self.volume_slider_label)
        
        ui_perf_form_layout.addRow("音量计刷新间隔:", volume_slider_layout)
        
        layout.addWidget(ui_perf_group)
        
        # OK 和 Cancel 按钮
        from PyQt5.QtWidgets import QDialogButtonBox
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        layout.addWidget(self.button_box)
        
        self.load_settings()

    def load_settings(self):
        """从主配置加载所有设置并更新UI。"""
        module_states = self.parent_page.config.get("module_states", {}).get("dialect_visual_collector", {})
        
        # 加载工作流设置
        self.auto_advance_checkbox.setChecked(module_states.get("auto_advance", True)) # 默认启用
        self.cleanup_empty_folder_checkbox.setChecked(module_states.get("cleanup_empty_folder", True)) # 默认启用
        
        # 加载界面与性能设置
        self.volume_slider.setValue(module_states.get("volume_meter_interval", 16)) # 默认 16ms
        self.volume_slider_label.setText(f"{self.volume_slider.value()} ms")


    def save_settings(self):
        """将UI上的所有设置保存回主配置。"""
        main_window = self.parent_page.parent_window
        
        settings_to_save = {
            "auto_advance": self.auto_advance_checkbox.isChecked(),
            "cleanup_empty_folder": self.cleanup_empty_folder_checkbox.isChecked(),
            "volume_meter_interval": self.volume_slider.value(),
        }
        
        # 为了不丢失其他已有设置（如 is_random, pinned_wordlists 等），我们先读取旧设置，再更新
        current_settings = main_window.config.get("module_states", {}).get("dialect_visual_collector", {})
        current_settings.update(settings_to_save)

        main_window.update_and_save_module_state('dialect_visual_collector', current_settings)

    def accept(self):
        """重写 accept 方法，在关闭对话框前先保存设置。"""
        self.save_settings()
        super().accept()