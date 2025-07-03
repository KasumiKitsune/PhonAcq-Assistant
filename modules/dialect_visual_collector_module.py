# --- START OF FILE modules/dialect_visual_collector_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "看图说话采集"
MODULE_DESCRIPTION = "展示图片并录制方言描述，支持文字备注显隐及图片缩放。"
# ---

import os
import sys 
import importlib.util
import threading
import queue
import time
import random
import json

from PyQt5.QtCore import QObject, pyqtSignal, Qt, QSize, QEvent, QTimer, QUrl, QThread, QPoint
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QFileDialog, QMessageBox, QComboBox, QFormLayout,
                             QGroupBox, QTextEdit, QSizePolicy, QProgressBar, QApplication,
                             QStyle, QSlider, QMenu, QLineEdit)
from PyQt5.QtGui import QPixmap, QImageReader, QIcon, QColor, QPainter, QTransform, QPen

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


# 全局变量
WORD_LIST_DIR_FOR_DIALECT_VISUAL = ""

# 模块入口函数
def create_page(parent_window, config, base_path, word_list_dir_visual, audio_record_dir_visual, 
                ToggleSwitchClass, WorkerClass, LoggerClass, icon_manager):
    global WORD_LIST_DIR_FOR_DIALECT_VISUAL
    WORD_LIST_DIR_FOR_DIALECT_VISUAL = word_list_dir_visual

    if DEPENDENCIES_MISSING:
        error_page = QWidget()
        layout = QVBoxLayout(error_page)
        label = QLabel(f"看图说话采集模块加载失败：\n缺少必要的依赖库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install sounddevice soundfile numpy")
        label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); layout.addWidget(label)
        return error_page
        
    return DialectVisualCollectorPage(parent_window, config, base_path, ToggleSwitchClass, WorkerClass, LoggerClass, icon_manager)

class ScalableImageLabel(QLabel):
    zoom_changed = pyqtSignal(float)

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.pixmap = None
        self.scale_multiplier = 1.0 
        self.min_scale = 1.0
        self.offset = QPoint(0, 0)
        self.panning = False
        self.last_mouse_pos = QPoint()
        self.setMinimumSize(400, 300)
        self.setAlignment(Qt.AlignCenter)
        self.setObjectName("ScalableImageLabel")

        self.drawing_mode = False
        self.drawing = False
        self.drawn_paths = [] 
        self.current_path = []
        self.drawing_pen = QPen(QColor("#FF3B30"), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

    def set_pixmap(self, pixmap):
        self.pixmap = pixmap
        self.clear_drawings() 
        self.reset_view()

    def clear_drawings(self):
        self.drawn_paths.clear()
        self.current_path.clear()
        self.update()

    def toggle_drawing_mode(self, enabled):
        self.drawing_mode = enabled
        if not enabled:
            self.clear_drawings()
            self.setCursor(Qt.ArrowCursor)
        else:
            self.setCursor(Qt.CrossCursor)

    def total_scale(self):
        return self.min_scale * self.scale_multiplier

    def set_zoom_level(self, level):
        if not self.pixmap or self.pixmap.isNull(): return
        new_multiplier = level / 100.0
        if abs(new_multiplier - self.scale_multiplier) > 0.001:
            self.scale_multiplier = new_multiplier
            self.clamp_offset()
            self.update()
            self.zoom_changed.emit(self.scale_multiplier)

    def _widget_pos_to_pixmap_pos(self, widget_pos):
        if not self.pixmap or self.pixmap.isNull(): return QPoint()
        current_total_scale = self.total_scale()
        if current_total_scale == 0: return QPoint()
        scaled_w = self.pixmap.width() * current_total_scale
        scaled_h = self.pixmap.height() * current_total_scale
        top_left_in_widget = QPoint(int((self.width() - scaled_w) / 2 + self.offset.x()), int((self.height() - scaled_h) / 2 + self.offset.y()))
        relative_pos = widget_pos - top_left_in_widget
        pixmap_pos = relative_pos / current_total_scale
        return pixmap_pos

    def calculate_min_scale(self):
        if not self.pixmap or self.pixmap.isNull() or self.width() <= 0 or self.height() <= 0: self.min_scale = 1.0; return
        pix_size = self.pixmap.size()
        if pix_size.width() <= 0 or pix_size.height() <= 0: self.min_scale = 1.0; return
        self.min_scale = min(self.width() / pix_size.width(), self.height() / pix_size.height())

    def reset_view(self):
        self.calculate_min_scale()
        self.scale_multiplier = 1.0
        self.offset = QPoint(0, 0)
        self.update()
        self.zoom_changed.emit(self.scale_multiplier)

    def wheelEvent(self, event):
        if not self.pixmap or self.pixmap.isNull(): return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_multiplier = self.scale_multiplier * factor
        if new_multiplier < 1.0: new_multiplier = 1.0
        elif new_multiplier > 8.0: new_multiplier = 8.0
        if abs(new_multiplier - self.scale_multiplier) > 0.001:
            self.scale_multiplier = new_multiplier
            self.clamp_offset()
            self.update()
            self.zoom_changed.emit(self.scale_multiplier)

    def mousePressEvent(self, event):
        if self.pixmap:
            if self.drawing_mode and event.button() == Qt.LeftButton:
                self.drawing = True
                self.current_path = [self._widget_pos_to_pixmap_pos(event.pos())]
                self.update()
            elif event.button() == Qt.LeftButton:
                self.panning = True
                self.last_mouse_pos = event.pos()
                self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.drawing:
            self.current_path.append(self._widget_pos_to_pixmap_pos(event.pos()))
            self.update()
        elif self.panning:
            current_total_scale = self.total_scale()
            scaled_w = self.pixmap.width() * current_total_scale
            scaled_h = self.pixmap.height() * current_total_scale
            if scaled_w > self.width() or scaled_h > self.height():
                 delta = event.pos() - self.last_mouse_pos
                 self.offset += delta
                 self.last_mouse_pos = event.pos()
                 self.clamp_offset()
                 self.update()

    def mouseReleaseEvent(self, event):
        if self.drawing:
            self.drawing = False
            if self.current_path: self.drawn_paths.append(self.current_path)
            self.current_path = []
            self.update()
        elif self.panning:
            self.panning = False
            if self.drawing_mode: self.setCursor(Qt.CrossCursor)
            else: self.setCursor(Qt.ArrowCursor)

    def clamp_offset(self):
        if not self.pixmap: return
        current_total_scale = self.total_scale()
        scaled_w = self.pixmap.width() * current_total_scale; scaled_h = self.pixmap.height() * current_total_scale
        center_x_margin = (self.width() - scaled_w) / 2; center_y_margin = (self.height() - scaled_h) / 2
        if scaled_w <= self.width(): self.offset.setX(0)
        else:
            max_offset_x = -center_x_margin; min_offset_x = self.width() - scaled_w - center_x_margin
            if self.offset.x() > max_offset_x: self.offset.setX(int(max_offset_x))
            elif self.offset.x() < min_offset_x: self.offset.setX(int(min_offset_x))
        if scaled_h <= self.height(): self.offset.setY(0)
        else:
            max_offset_y = -center_y_margin; min_offset_y = self.height() - scaled_h - center_y_margin
            if self.offset.y() > max_offset_y: self.offset.setY(int(max_offset_y))
            elif self.offset.y() < min_offset_y: self.offset.setY(int(min_offset_y))
    
    def paintEvent(self, event):
        if not self.pixmap or self.pixmap.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self); painter.setRenderHint(QPainter.SmoothPixmapTransform)
        current_total_scale = self.total_scale(); scaled_pixmap_size = self.pixmap.size() * current_total_scale
        center_x = (self.width() - scaled_pixmap_size.width()) / 2; center_y = (self.height() - scaled_pixmap_size.height()) / 2
        draw_x = center_x + self.offset.x(); draw_y = center_y + self.offset.y()
        painter.drawPixmap(int(draw_x), int(draw_y), int(scaled_pixmap_size.width()), int(scaled_pixmap_size.height()), self.pixmap)
        painter.setPen(self.drawing_pen); painter.save(); painter.translate(draw_x, draw_y); painter.scale(current_total_scale, current_total_scale)
        for path in self.drawn_paths:
            if len(path) > 1:
                for i in range(len(path) - 1): painter.drawLine(path[i], path[i+1])
        if self.current_path and len(self.current_path) > 1:
            for i in range(len(self.current_path) - 1): painter.drawLine(self.current_path[i], self.current_path[i+1])
        painter.restore()

    def set_pen_width(self, width):
        self.drawing_pen.setWidth(width)

    def resizeEvent(self, event):
        self.reset_view()
        super().resizeEvent(event)

class DialectVisualCollectorPage(QWidget):
    recording_device_error_signal = pyqtSignal(str)
    
    def __init__(self, parent_window, config, base_path, ToggleSwitchClass, WorkerClass, LoggerClass, icon_manager):
        super().__init__()
        self.parent_window = parent_window; self.config = config; self.BASE_PATH = base_path
        self.ToggleSwitch = ToggleSwitchClass; self.Worker = WorkerClass; self.Logger = LoggerClass
        self.icon_manager = icon_manager
        self.session_active = False; self.is_recording = False; self.original_items_list = []; self.current_items_list = []
        self.current_item_index = -1; self.current_wordlist_path = None; self.current_wordlist_name = None; self.current_audio_folder = None
        self.audio_queue = queue.Queue(); self.volume_meter_queue = queue.Queue(maxsize=2)
        self.recording_thread = None; self.session_stop_event = threading.Event(); self.logger = None
        self.last_warning_log_time = 0
        
        self._init_ui() # This will create self.participant_input
        self._connect_signals()
        self.update_icons()
        self.load_config_and_prepare() # This needs self.participant_input to exist

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        self.left_panel = QWidget(); left_layout = QVBoxLayout(self.left_panel)
        self.item_list_widget = QListWidget(); self.item_list_widget.setObjectName("DialectItemList"); self.item_list_widget.setWordWrap(True)
        self.item_list_widget.setToolTip("当前采集会话中的所有项目。\n绿色对勾表示已录制。\n点击可切换到对应项目。")
        self.status_label = QLabel("状态：请选择图文词表开始采集。"); self.status_label.setObjectName("StatusLabelModule"); self.status_label.setMinimumHeight(25); self.status_label.setWordWrap(True)
        left_layout.addWidget(QLabel("采集项目:")); left_layout.addWidget(self.item_list_widget, 1); left_layout.addWidget(self.status_label)
        
        center_panel = QWidget(); center_layout = QVBoxLayout(center_panel); center_layout.setContentsMargins(0, 0, 0, 0)
        self.image_viewer = ScalableImageLabel("图片区域"); self.image_viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding); self.image_viewer.setToolTip("显示当前项目的图片。\n使用鼠标滚轮进行缩放，按住并拖动鼠标进行平移。")
        self.prompt_text_label = QLabel("提示文字区域"); self.prompt_text_label.setObjectName("PromptTextLabel"); self.prompt_text_label.setAlignment(Qt.AlignCenter); self.prompt_text_label.setWordWrap(True); self.prompt_text_label.setFixedHeight(60)
        self.notes_text_edit = QTextEdit(); self.notes_text_edit.setObjectName("NotesTextEdit"); self.notes_text_edit.setReadOnly(True); self.notes_text_edit.setFixedHeight(120); self.notes_text_edit.setVisible(False)
        center_layout.addWidget(self.image_viewer, 1); center_layout.addWidget(self.prompt_text_label); center_layout.addWidget(self.notes_text_edit)
        
        self.right_panel = QWidget(); right_panel_layout = QVBoxLayout(self.right_panel)
        control_group = QGroupBox("操作面板"); self.control_layout = QFormLayout(control_group)
        self.word_list_combo = QComboBox(); self.word_list_combo.setToolTip("选择一个用于本次采集的图文词表。")
        self.participant_input = QLineEdit(); self.participant_input.setPlaceholderText("例如: participant_1"); self.participant_input.setToolTip("输入被试者的唯一标识符。\n此名称将用于创建结果文件夹。")
        self.start_btn = QPushButton("加载并开始"); self.start_btn.setObjectName("AccentButton"); self.start_btn.setToolTip("加载选中的图文词表，并开始一个新的采集会话。")
        self.end_session_btn = QPushButton("结束当前会话"); self.end_session_btn.setObjectName("ActionButton_Delete"); self.end_session_btn.setToolTip("提前结束当前的采集会话。"); self.end_session_btn.hide()
        self.control_layout.addRow("选择图文词表:", self.word_list_combo); self.control_layout.addRow("被试者名称:", self.participant_input); self.control_layout.addRow(self.start_btn)
        
        options_group = QGroupBox("会话选项"); options_layout = QFormLayout(options_group)
        self.random_order_switch = self.ToggleSwitch(); self.random_order_switch.setToolTip("开启后，将打乱词表中所有项目的呈现顺序。\n此设置在会话开始后仍可更改。")
        random_order_layout = QHBoxLayout(); random_order_layout.addWidget(QLabel("随机顺序:")); random_order_layout.addStretch(); random_order_layout.addWidget(self.random_order_switch); options_layout.addRow(random_order_layout)
        self.show_prompt_switch = self.ToggleSwitch(); self.show_prompt_switch.setChecked(True); self.show_prompt_switch.setToolTip("控制是否在图片下方显示提示性描述文字。")
        show_prompt_layout = QHBoxLayout(); show_prompt_layout.addWidget(QLabel("显示描述:")); show_prompt_layout.addStretch(); show_prompt_layout.addWidget(self.show_prompt_switch); options_layout.addRow(show_prompt_layout)
        self.show_notes_switch = self.ToggleSwitch(); self.show_notes_switch.setToolTip("控制是否显示研究者备注。\n此备注信息仅研究者可见，不会展示给被试者。")
        show_notes_layout = QHBoxLayout(); show_notes_layout.addWidget(QLabel("显示备注:")); show_notes_layout.addStretch(); show_notes_layout.addWidget(self.show_notes_switch); options_layout.addRow(show_notes_layout)

        image_tools_group = QGroupBox("图片工具"); image_tools_layout = QFormLayout(image_tools_group)
        zoom_layout = QHBoxLayout(); self.zoom_slider = QSlider(Qt.Horizontal); self.zoom_slider.setRange(100, 800); self.zoom_slider.setToolTip("拖动以缩放图片"); self.zoom_label = QLabel("1.0x"); self.zoom_label.setFixedWidth(40); zoom_layout.addWidget(self.zoom_slider); zoom_layout.addWidget(self.zoom_label); image_tools_layout.addRow("缩放:", zoom_layout)
        self.draw_button = QPushButton("圈划"); self.draw_button.setCheckable(True); self.draw_button.setToolTip("启用/禁用临时绘图模式\n右键单击可选择画笔颜色"); self.draw_button.setContextMenuPolicy(Qt.CustomContextMenu)
        pen_width_layout = QHBoxLayout(); self.pen_width_slider = QSlider(Qt.Horizontal); self.pen_width_slider.setRange(2, 16); self.pen_width_slider.setValue(8); self.pen_width_slider.setToolTip("调整画笔粗细"); self.pen_width_label = QLabel("8"); self.pen_width_label.setFixedWidth(30); pen_width_layout.addWidget(self.pen_width_slider); pen_width_layout.addWidget(self.pen_width_label); image_tools_layout.addRow(self.draw_button, pen_width_layout)

        self.recording_status_panel = QGroupBox("录音状态"); status_panel_layout = QVBoxLayout(self.recording_status_panel)
        self.recording_indicator = QLabel("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;"); self.volume_label = QLabel("当前音量:"); self.volume_meter = QProgressBar(); self.volume_meter.setRange(0,100); self.volume_meter.setValue(0); self.volume_meter.setTextVisible(False); status_panel_layout.addWidget(self.recording_indicator); status_panel_layout.addWidget(self.volume_label); status_panel_layout.addWidget(self.volume_meter); self.update_timer = QTimer(); self.update_timer.timeout.connect(self.update_volume_meter)
        
        self.record_btn = QPushButton("开始录音"); self.record_btn.setEnabled(False); self.record_btn.setFixedHeight(50); self.record_btn.setStyleSheet("QPushButton {font-size: 18px; font-weight: bold;}"); self.record_btn.setToolTip("点击开始录制当前项目。")
        
        right_panel_layout.addWidget(control_group); right_panel_layout.addWidget(options_group); right_panel_layout.addWidget(image_tools_group); right_panel_layout.addWidget(self.recording_status_panel); right_panel_layout.addStretch(); right_panel_layout.addWidget(self.record_btn)
        main_layout.addWidget(self.left_panel); main_layout.addWidget(center_panel, 1); main_layout.addWidget(self.right_panel); self.setLayout(main_layout)

    def _connect_signals(self):
        self.start_btn.clicked.connect(self.start_session)
        self.end_session_btn.clicked.connect(self.end_session)
        self.record_btn.clicked.connect(self.handle_record_button)
        self.item_list_widget.currentItemChanged.connect(self.on_item_selected)
        self.show_notes_switch.stateChanged.connect(self.toggle_notes_visibility)
        self.show_prompt_switch.stateChanged.connect(self.toggle_prompt_visibility)
        self.random_order_switch.stateChanged.connect(self.on_order_mode_changed)
        self.recording_device_error_signal.connect(self.show_recording_device_error)
        self.setFocusPolicy(Qt.StrongFocus)
        self.zoom_slider.valueChanged.connect(self.image_viewer.set_zoom_level)
        self.image_viewer.zoom_changed.connect(self.on_zoom_changed_by_viewer)
        self.draw_button.toggled.connect(self.on_draw_button_toggled)
        self.draw_button.customContextMenuRequested.connect(self.show_draw_color_menu)
        self.pen_width_slider.valueChanged.connect(self.image_viewer.set_pen_width)
        self.pen_width_slider.valueChanged.connect(lambda value: self.pen_width_label.setText(f"{value}"))

    def on_zoom_changed_by_viewer(self, multiplier):
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(int(multiplier * 100))
        self.zoom_slider.blockSignals(False)
        self.zoom_label.setText(f"{multiplier:.1f}x")

    def show_draw_color_menu(self, position):
        menu = QMenu(); colors = {"红色": QColor("#FF3B30"), "黄色": QColor("#FFCC00"), "蓝色": QColor("#007AFF"), "绿色": QColor("#34C759"), "黑色": QColor("#000000"), "白色": QColor("#FFFFFF")}
        for name, color in colors.items():
            action = menu.addAction(name); pixmap = QPixmap(16, 16); pixmap.fill(color); action.setIcon(QIcon(pixmap)); action.setData(color)
        action = menu.exec_(self.draw_button.mapToGlobal(position))
        if action: self.image_viewer.drawing_pen.setColor(action.data());
        if self.image_viewer.drawing_mode: self.image_viewer.update()

    def on_draw_button_toggled(self, checked):
        if checked: self.draw_button.setText("禁用"); self.draw_button.setToolTip("禁用临时绘图模式")
        else: self.draw_button.setText("圈划"); self.draw_button.setToolTip("启用临时绘图模式\n右键单击可选择画笔颜色")
        self.image_viewer.toggle_drawing_mode(checked)

    def update_icons(self):
        self.start_btn.setIcon(self.icon_manager.get_icon("start_session")); self.end_session_btn.setIcon(self.icon_manager.get_icon("end_session"))
        self.record_btn.setIcon(self.icon_manager.get_icon("record")); self.draw_button.setIcon(self.icon_manager.get_icon("draw")); self.update_list_widget_icons()

    def update_list_widget_icons(self):
        if not self.session_active: return
        recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower()
        for index, item_data in enumerate(self.current_items_list):
            list_item = self.item_list_widget.item(index)
            if not list_item: continue
            main_audio_filename = f"{item_data.get('id')}.{recording_format}"
            wav_fallback_filename = f"{item_data.get('id')}.wav"
            if self.current_audio_folder and (os.path.exists(os.path.join(self.current_audio_folder, main_audio_filename)) or os.path.exists(os.path.join(self.current_audio_folder, wav_fallback_filename))):
                list_item.setIcon(self.icon_manager.get_icon("success"))
            else: list_item.setIcon(QIcon())

    def apply_layout_settings(self):
        ui_settings = self.config.get("ui_settings", {}); width = ui_settings.get("collector_sidebar_width", 320); self.left_panel.setFixedWidth(width)

    def load_config_and_prepare(self):
        self.config = self.parent_window.config; self.apply_layout_settings()
        if not self.session_active:
            self.populate_word_lists()
            default_participant = self.config.get('file_settings', {}).get('participant_base_name', 'participant')
            self.participant_input.setText(default_participant)

    def show_recording_device_error(self, error_message):
        QMessageBox.critical(self, "录音设备错误", error_message); log_message = "录音设备错误，请检查设置。"; self.log(log_message)
        if self.logger: self.logger.log(f"[FATAL] {log_message} Details: {error_message}")
        self.record_btn.setEnabled(False);
        if self.session_active: self.end_session(force=True)

    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.record_btn.isEnabled(): self.handle_record_button(); event.accept()
        else: super().keyPressEvent(event)

    def keyReleaseEvent(self, event): super().keyReleaseEvent(event)

    def handle_record_button(self):
        if not self.session_active: return
        if not self.is_recording:
            self.current_item_index = self.item_list_widget.currentRow()
            if self.current_item_index == -1: self.log("请先在列表中选择一个项目！"); return
            self.item_list_widget.setEnabled(False); self.left_panel.setEnabled(False); self.random_order_switch.setEnabled(False)
            self._start_recording_logic()
            self.record_btn.setText("停止录音"); self.record_btn.setIcon(self.icon_manager.get_icon("stop")); self.record_btn.setToolTip("点击停止当前录音。")
        else:
            self._stop_recording_logic(); self.record_btn.setText("保存中..."); self.record_btn.setEnabled(False); self.record_btn.setIcon(self.icon_manager.get_icon("record"))

    def _start_recording_logic(self):
        while not self.audio_queue.empty():
            try: self.audio_queue.get_nowait()
            except queue.Empty: break
        self.is_recording = True; self.recording_indicator.setText("● 正在录音"); self.recording_indicator.setStyleSheet("color: red;")
        item_id = self.current_items_list[self.current_item_index].get('id', '未知项目'); self.log(f"录制项目: '{item_id}'")
        if self.logger: self.logger.log(f"[RECORD_START] Item ID: '{item_id}'")

    def _stop_recording_logic(self):
        self.is_recording = False; self.recording_indicator.setText("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.log("正在保存..."); self._run_task_in_thread(self._save_recording_task)

    def _format_list_item_text(self, item_id, prompt_text): return item_id
    def toggle_notes_visibility(self, state): self.notes_text_edit.setVisible(state == Qt.Checked)
    def toggle_prompt_visibility(self, state): self.prompt_text_label.setVisible(state == Qt.Checked)

    def on_order_mode_changed(self, state):
        if not self.session_active or not self.current_items_list: return
        current_id = None
        if 0 <= self.current_item_index < len(self.current_items_list): current_id = self.current_items_list[self.current_item_index].get('id')
        mode_text = "随机" if state == Qt.Checked else "顺序"; self.log(f"项目顺序已切换为: {mode_text}")
        if self.logger: self.logger.log(f"[SESSION_CONFIG_CHANGE] Order changed to: {mode_text}")
        if state == Qt.Checked: random.shuffle(self.current_items_list)
        else: self.current_items_list = list(self.original_items_list)
        new_row_index = next((i for i, item in enumerate(self.current_items_list) if item.get('id') == current_id), 0)
        self.current_item_index = new_row_index; self.update_list_widget()

    def on_item_selected(self, current_item, previous_item):
        if not current_item or not self.session_active:
            self.image_viewer.set_pixmap(None); self.image_viewer.setText("请选择项目"); self.prompt_text_label.setText(""); self.notes_text_edit.setPlainText(""); return
        if self.draw_button.isChecked(): self.draw_button.setChecked(False)
        self.current_item_index = self.item_list_widget.row(current_item)
        if self.current_item_index < 0 or self.current_item_index >= len(self.current_items_list): return
        item_data = self.current_items_list[self.current_item_index]; wordlist_base_dir = os.path.dirname(self.current_wordlist_path)
        image_rel_path = item_data.get('image_path', ''); image_full_path = os.path.join(wordlist_base_dir, image_rel_path) if image_rel_path else ''
        if image_full_path and os.path.exists(image_full_path):
            reader = QImageReader(image_full_path); reader.setAutoTransform(True); image = reader.read()
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                if not pixmap.isNull(): self.image_viewer.set_pixmap(pixmap)
                else: self.image_viewer.set_pixmap(None); self.image_viewer.setText(f"图片转换失败:\n{os.path.basename(image_rel_path)}")
            else: self.image_viewer.set_pixmap(None); self.image_viewer.setText(f"无法读取图片:\n{os.path.basename(image_rel_path)}\n错误: {reader.errorString()}")
        elif image_rel_path: self.image_viewer.set_pixmap(None); self.image_viewer.setText(f"图片未找到:\n{image_rel_path}")
        else: self.image_viewer.set_pixmap(None); self.image_viewer.setText("此项目无图片或路径未指定"); self.on_zoom_changed_by_viewer(1.0)
        self.prompt_text_label.setText(item_data.get('prompt_text', '')); self.notes_text_edit.setPlainText(item_data.get('notes', '无备注'))

    def update_volume_meter(self):
        try:
            data_chunk = self.volume_meter_queue.get_nowait(); volume_norm = np.linalg.norm(data_chunk) * 20; self.volume_meter.setValue(int(volume_norm))
        except queue.Empty: self.volume_meter.setValue(int(self.volume_meter.value() * 0.8))
        except Exception as e: print(f"Error calculating volume: {e}")

    def log(self, msg): self.status_label.setText(f"状态: {msg}")

    def populate_word_lists(self):
        self.word_list_combo.clear()
        if WORD_LIST_DIR_FOR_DIALECT_VISUAL and os.path.exists(WORD_LIST_DIR_FOR_DIALECT_VISUAL):
            try:
                # [修改] 只查找 .json 文件
                self.word_list_combo.addItems(sorted([f for f in os.listdir(WORD_LIST_DIR_FOR_DIALECT_VISUAL) if f.endswith('.json')]))
            except Exception as e:
                self.log(f"错误: 无法读取图文词表目录: {e}")
        else:
            self.log(f"提示: 图文词表目录未设置或不存在 ({WORD_LIST_DIR_FOR_DIALECT_VISUAL})")

    def reset_ui(self):
        self.word_list_combo.show(); self.participant_input.show(); self.start_btn.show()
        if self.end_session_btn.parent() is not None: self.control_layout.removeRow(self.end_session_btn)
        self.item_list_widget.clear(); self.image_viewer.set_pixmap(None); self.image_viewer.setText("请加载图文词表"); self.prompt_text_label.setText(""); self.notes_text_edit.setPlainText(""); self.notes_text_edit.setVisible(False)
        self.show_notes_switch.setChecked(False); self.record_btn.setEnabled(False); self.log("请选择图文词表开始采集。")

    def end_session(self, force=False):
        if not force:
            reply = QMessageBox.question(self, '结束会话', '您确定要结束当前的图文采集会话吗？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes: return
        if self.logger: self.logger.log("[SESSION_END] Session ended by user."); self.update_timer.stop(); self.volume_meter.setValue(0); self.session_stop_event.set()
        if self.recording_thread and self.recording_thread.is_alive(): self.recording_thread.join(timeout=1.0)
        self.recording_thread = None; self.session_active = False; self.current_items_list = []; self.original_items_list = []; self.current_item_index = -1
        self.current_wordlist_path = None; self.current_wordlist_name = None; self.current_audio_folder = None; self.logger = None; self.reset_ui()

    def start_session(self):
        wordlist_file = self.word_list_combo.currentText()
        if not wordlist_file: QMessageBox.warning(self, "错误", "请先选择一个图文词表。"); return
        participant_name = self.participant_input.text().strip()
        if not participant_name: QMessageBox.warning(self, "输入错误", "请输入被试者名称。"); return
        try:
            self.current_wordlist_name = wordlist_file; self.original_items_list = self.load_word_list_logic(wordlist_file) 
            if not self.original_items_list: QMessageBox.warning(self, "错误", f"词表 '{wordlist_file}' 为空或加载失败。"); return
            self.current_items_list = list(self.original_items_list)
            if self.random_order_switch.isChecked(): random.shuffle(self.current_items_list)
            
            results_base_dir = self.config.get('file_settings', {}).get('results_dir', os.path.join(self.BASE_PATH, "Results"))
            visual_results_dir = os.path.join(results_base_dir, "visual"); os.makedirs(visual_results_dir, exist_ok=True)
            
            # [修改] 确保从 .json 文件名中正确提取基础名称
            wordlist_name_no_ext, _ = os.path.splitext(self.current_wordlist_name)
            base_folder_name = f"{participant_name}-{wordlist_name_no_ext}"
            
            i = 1; folder_name = base_folder_name
            while os.path.exists(os.path.join(visual_results_dir, folder_name)): folder_name = f"{base_folder_name}_{i}"; i += 1
            self.current_audio_folder = os.path.join(visual_results_dir, folder_name); os.makedirs(self.current_audio_folder, exist_ok=True)
            
            self.logger = None
            if self.config.get("app_settings", {}).get("enable_logging", True): self.logger = self.Logger(os.path.join(self.current_audio_folder, "log.txt"))
            if self.logger:
                mode = "Random" if self.random_order_switch.isChecked() else "Sequential"
                self.logger.log(f"[SESSION_START] Dialect visual collection for wordlist: {self.current_wordlist_name}")
                self.logger.log(f"[SESSION_CONFIG] Participant: '{participant_name}', Output folder: '{self.current_audio_folder}', Mode: {mode}")

            self.session_stop_event.clear(); self.recording_thread = threading.Thread(target=self._persistent_recorder_task, daemon=True); self.recording_thread.start(); self.update_timer.start(30)
            
            self.word_list_combo.hide(); self.participant_input.hide(); self.start_btn.hide()
            self.end_session_btn = QPushButton("结束当前会话"); self.end_session_btn.setObjectName("ActionButton_Delete"); self.end_session_btn.clicked.connect(self.end_session); self.update_icons(); self.control_layout.addRow(self.end_session_btn)

            QTimer.singleShot(0, self.update_list_widget); self.record_btn.setEnabled(True); self.log("准备就绪，请选择项目并开始录音。"); self.session_active = True
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动会话失败: {e}"); self.session_active = False
            if hasattr(self, 'logger') and self.logger: self.logger.log(f"[ERROR] Failed to start session: {e}")

    def update_list_widget(self):
        current_row = self.item_list_widget.currentRow() if self.item_list_widget.count() > 0 else 0; self.item_list_widget.clear()
        for index, item_data in enumerate(self.current_items_list):
            display_text = self._format_list_item_text(item_data.get('id', f"项目_{index+1}"), item_data.get('prompt_text', ''))
            self.item_list_widget.addItem(QListWidgetItem(display_text))
        self.update_list_widget_icons()
        if self.current_items_list and 0 <= current_row < len(self.current_items_list):
             self.item_list_widget.setCurrentRow(current_row); selected_item_to_display = self.item_list_widget.item(current_row)
             if selected_item_to_display: self.on_item_selected(selected_item_to_display, None)

    def on_recording_saved(self, result):
        self.record_btn.setText("开始录音"); self.record_btn.setToolTip("点击开始录制当前项目。"); self.record_btn.setEnabled(True)
        self.item_list_widget.setEnabled(True); self.left_panel.setEnabled(True); self.random_order_switch.setEnabled(True)
        if result == "save_failed_mp3_encoder":
            QMessageBox.critical(self, "MP3 编码器缺失", "无法将录音保存为 MP3 格式。\n\n建议：请在“程序设置”中将录音格式切换为 WAV (高质量)，或为您的系统安装 LAME 编码器。"); self.log("MP3保存失败！请检查编码器或设置。"); return
        self.log("录音已保存。"); self.update_list_widget_icons()
        if self.current_item_index + 1 < len(self.current_items_list):
            self.item_list_widget.setCurrentRow(self.current_item_index + 1)
        else:
            all_done = True; recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower()
            for item_data in self.current_items_list:
                main_audio_filename = f"{item_data.get('id')}.{recording_format}"; wav_fallback_filename = f"{item_data.get('id')}.wav"
                if not os.path.exists(os.path.join(self.current_audio_folder, main_audio_filename)) and not os.path.exists(os.path.join(self.current_audio_folder, wav_fallback_filename)): all_done = False; break
            if all_done: QMessageBox.information(self,"完成","所有项目已录制完毕！");
            if self.session_active: self.end_session()

    def _persistent_recorder_task(self):
        try:
            device_index = self.config['audio_settings'].get('input_device_index', None); sr = self.config.get('audio_settings', {}).get('sample_rate', 44100); ch = self.config.get('audio_settings', {}).get('channels', 1)
            with sd.InputStream(device=device_index, samplerate=sr, channels=ch, callback=self._audio_callback): self.session_stop_event.wait()
        except Exception as e: 
            error_msg = f"无法启动录音，请检查设备设置或权限。\n错误详情: {e}"; print(f"持久化录音线程错误: {error_msg}")
            if self.logger: self.logger.log(f"[FATAL_ERROR] Cannot start audio stream: {e}"); self.recording_device_error_signal.emit(error_msg)

    def _audio_callback(self, indata, frames, time_info, status):
        if status and (status.input_overflow or status.output_overflow or status.priming_output):
            current_time = time.monotonic()
            if current_time - self.last_warning_log_time > 5:
                self.last_warning_log_time = current_time; warning_msg = f"Audio callback status: {status}"
                print(warning_msg, file=sys.stderr)
                if self.logger: self.logger.log(f"[WARNING] {warning_msg}")
        try: self.volume_meter_queue.put_nowait(indata.copy())
        except queue.Full: pass
        if self.is_recording:
            try: self.audio_queue.put(indata.copy())
            except queue.Full: pass

    def _save_recording_task(self, worker_instance):
        if self.audio_queue.empty(): return None
        data_chunks = [];
        while not self.audio_queue.empty():
            try: data_chunks.append(self.audio_queue.get_nowait())
            except queue.Empty: break
        if not data_chunks: return None
        rec = np.concatenate(data_chunks, axis=0); gain = self.config.get('audio_settings', {}).get('recording_gain', 1.0)
        if gain != 1.0: rec = np.clip(rec * gain, -1.0, 1.0)
        recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower()
        item_id = self.current_items_list[self.current_item_index].get('id', f"item_{self.current_item_index + 1}"); filename = f"{item_id}.{recording_format}"; filepath = os.path.join(self.current_audio_folder, filename)
        if self.logger: self.logger.log(f"[RECORDING_SAVE_ATTEMPT] Item ID: '{item_id}', Format: '{recording_format}', Path: '{filepath}'")
        try:
            sr = self.config.get('audio_settings', {}).get('sample_rate', 44100); sf.write(filepath, rec, sr)
            if self.logger: self.logger.log("[RECORDING_SAVE_SUCCESS] File saved successfully.")
        except Exception as e:
            if self.logger: self.logger.log(f"[ERROR] Failed to save {recording_format.upper()}: {e}")
            if recording_format == 'mp3' and 'format not understood' in str(e).lower(): return "save_failed_mp3_encoder"
            if recording_format != 'wav':
                try:
                    wav_path = os.path.splitext(filepath)[0] + ".wav"; sf.write(wav_path, rec, sr); self.log(f"已尝试回退保存为WAV: {os.path.basename(wav_path)}")
                    if self.logger: self.logger.log(f"[RECORDING_SAVE_FALLBACK] Fallback WAV saved: {wav_path}")
                except Exception as e_wav: self.log(f"回退保存WAV也失败: {e_wav}");
                if self.logger: self.logger.log(f"[ERROR] Fallback WAV save also failed: {e_wav}")
        return None
    def _run_task_in_thread(self, task_func, *args):
        self.thread = QThread(); self.worker = self.Worker(task_func, *args); self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit); self.worker.finished.connect(self.worker.deleteLater); self.thread.finished.connect(self.thread.deleteLater)
        self.worker.error.connect(lambda msg:QMessageBox.critical(self,"后台错误",msg))
        if task_func == self._save_recording_task: self.worker.finished.connect(self.on_recording_saved)
        self.thread.start()
        
    def load_word_list_logic(self, filename_from_combo):
        self.current_wordlist_path = os.path.join(WORD_LIST_DIR_FOR_DIALECT_VISUAL, filename_from_combo)
        if not os.path.exists(self.current_wordlist_path):
            raise FileNotFoundError(f"找不到图文词表文件: {self.current_wordlist_path}")

        # [修改] 使用 json.load() 读取并解析
        try:
            with open(self.current_wordlist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"词表文件 '{filename_from_combo}' 不是有效的JSON格式: {e}")
        
        # 验证文件格式
        if "meta" not in data or data.get("meta", {}).get("format") != "visual_wordlist" or "items" not in data:
             raise ValueError(f"词表文件 '{filename_from_combo}' 格式不正确或不受支持。")
        
        # 返回 items 列表，其结构与之前的 ITEMS 变量兼容
        items_list = data.get("items", [])
        if not isinstance(items_list, list):
             raise ValueError(f"词表文件 '{filename_from_combo}' 中的 'items' 必须是一个列表。")
             
        return items_list