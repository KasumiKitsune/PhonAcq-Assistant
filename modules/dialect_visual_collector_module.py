# --- START OF FILE dialect_visual_collector_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "方言图文采集"
MODULE_DESCRIPTION = "展示图片并录制方言描述，支持文字备注显隐及图片缩放。"
# ---

import os
import sys # 确保 sys 被导入
import importlib.util
import threading
import queue
import time
import random

from PyQt5.QtCore import QObject, pyqtSignal, Qt, QSize, QEvent, QTimer, QUrl, QThread, QPoint
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QFileDialog, QMessageBox, QComboBox, QFormLayout,
                             QGroupBox, QTextEdit, QScrollArea, QSizePolicy, QProgressBar, QApplication,
                             QCheckBox, QStyle)
from PyQt5.QtGui import QPixmap, QImageReader, QIcon, QColor, QPainter, QTransform

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


# 全局变量，用于在 create_page 中设置，然后在类中使用
WORD_LIST_DIR_FOR_DIALECT_VISUAL = ""
AUDIO_RECORD_DIR_FOR_DIALECT_VISUAL = ""

def create_page(parent_window, config, base_path, word_list_dir_visual, audio_record_dir_visual, 
                ToggleSwitchClass, WorkerClass, LoggerClass):
    global WORD_LIST_DIR_FOR_DIALECT_VISUAL, AUDIO_RECORD_DIR_FOR_DIALECT_VISUAL
    WORD_LIST_DIR_FOR_DIALECT_VISUAL = word_list_dir_visual
    AUDIO_RECORD_DIR_FOR_DIALECT_VISUAL = audio_record_dir_visual

    if DEPENDENCIES_MISSING:
        error_page = QWidget()
        layout = QVBoxLayout(error_page)
        label = QLabel(f"方言图文采集模块加载失败：\n缺少必要的依赖库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install sounddevice soundfile numpy")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        return error_page
        
    return DialectVisualCollectorPage(parent_window, config, base_path, ToggleSwitchClass, WorkerClass, LoggerClass)

class ScalableImageLabel(QLabel):
    # ... (ScalableImageLabel 类的代码保持不变，此处省略以减少篇幅) ...
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.pixmap = None; self.scale = 1.0; self.min_scale = 1.0
        self.offset = QPoint(0, 0); self.panning = False; self.last_mouse_pos = QPoint()
        self.setMinimumSize(400, 300); self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("QLabel { border: 1px solid #cccccc; background-color: #f0f0f0; color: #888888; }")
    def set_pixmap(self, pixmap): self.pixmap = pixmap; self.reset_view()
    def calculate_min_scale(self):
        if not self.pixmap or self.pixmap.isNull() or self.width() <= 0 or self.height() <= 0: self.min_scale = 1.0; return
        pix_size = self.pixmap.size()
        if pix_size.width() <= 0 or pix_size.height() <= 0: self.min_scale = 1.0; return
        self.min_scale = min(self.width() / pix_size.width(), self.height() / pix_size.height())
    def reset_view(self):
        self.calculate_min_scale(); self.scale = self.min_scale; self.offset = QPoint(0, 0); self.update()
    def wheelEvent(self, event):
        if not self.pixmap or self.pixmap.isNull(): return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_scale = self.scale * factor
        if new_scale < self.min_scale: new_scale = self.min_scale
        elif new_scale > 10.0: new_scale = 10.0
        if new_scale != self.scale: self.scale = new_scale; self.clamp_offset(); self.update()
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.pixmap:
            self.panning = True; self.last_mouse_pos = event.pos(); self.setCursor(Qt.ClosedHandCursor)
    def mouseMoveEvent(self, event):
        if self.panning and self.pixmap:
            scaled_w = self.pixmap.width() * self.scale; scaled_h = self.pixmap.height() * self.scale
            if scaled_w > self.width() or scaled_h > self.height():
                 delta = event.pos() - self.last_mouse_pos; self.offset += delta
                 self.last_mouse_pos = event.pos(); self.clamp_offset(); self.update()
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton: self.panning = False; self.setCursor(Qt.ArrowCursor)
    def clamp_offset(self):
        if not self.pixmap: return
        scaled_w = self.pixmap.width() * self.scale; scaled_h = self.pixmap.height() * self.scale
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
        if not self.pixmap or self.pixmap.isNull(): super().paintEvent(event); return
        painter = QPainter(self); painter.setRenderHint(QPainter.SmoothPixmapTransform)
        scaled_pixmap_size = self.pixmap.size() * self.scale
        center_x = (self.width() - scaled_pixmap_size.width()) / 2
        center_y = (self.height() - scaled_pixmap_size.height()) / 2
        draw_x = center_x + self.offset.x(); draw_y = center_y + self.offset.y()
        painter.drawPixmap(int(draw_x), int(draw_y), int(scaled_pixmap_size.width()), int(scaled_pixmap_size.height()), self.pixmap)
    def resizeEvent(self, event):
        self.reset_view(); super().resizeEvent(event)


class DialectVisualCollectorPage(QWidget):
    LINE_WIDTH_THRESHOLD = 90 # 虽然在这个模块中列表项显示简单，但保留以防万一
    def __init__(self, parent_window, config, base_path, ToggleSwitchClass, WorkerClass, LoggerClass):
        super().__init__()
        self.parent_window = parent_window; self.config = config; self.BASE_PATH = base_path
        self.ToggleSwitch = ToggleSwitchClass; self.Worker = WorkerClass; self.Logger = LoggerClass
        self.session_active = False; self.is_recording = False
        self.original_items_list = []
        self.current_items_list = []
        self.current_item_index = -1; self.current_wordlist_path = None; self.current_wordlist_name = None
        self.current_audio_folder = None; self.audio_queue = queue.Queue(); self.recording_thread = None
        self.stop_event = threading.Event(); self.logger_instance = None
        
        self._init_ui() # 构建UI

        # 连接信号
        self.start_btn.clicked.connect(self.start_session)
        self.end_session_btn.clicked.connect(self.end_session)
        self.record_btn.pressed.connect(self.handle_record_pressed)
        self.record_btn.released.connect(self.handle_record_released)
        self.item_list_widget.currentItemChanged.connect(self.on_item_selected)
        self.show_notes_switch.stateChanged.connect(self.toggle_notes_visibility)
        self.show_prompt_switch.stateChanged.connect(self.toggle_prompt_visibility)
        self.random_order_switch.stateChanged.connect(self.on_order_mode_changed)
        self.setFocusPolicy(Qt.StrongFocus)

        # 初始加载配置（这也会调用 apply_layout_settings 如果需要）
        self.load_config_and_prepare()


    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        
        # 左侧面板 (列表)
        self.left_panel = QWidget() # 保存以便应用宽度设置
        left_layout = QVBoxLayout(self.left_panel)
        # left_panel.setFixedWidth(300) # 移除硬编码宽度

        self.item_list_widget = QListWidget(); self.item_list_widget.setObjectName("DialectItemList")
        self.item_list_widget.setWordWrap(True); self.item_list_widget.setResizeMode(QListWidget.Adjust)
        self.item_list_widget.setUniformItemSizes(False); self.item_list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.status_label = QLabel("状态：请选择图文词表开始采集。"); self.status_label.setObjectName("StatusLabelModule")
        self.status_label.setMinimumHeight(25); self.status_label.setWordWrap(True)
        left_layout.addWidget(QLabel("采集项目:")); left_layout.addWidget(self.item_list_widget, 1); left_layout.addWidget(self.status_label)
        
        # 中间面板 (图片和文本)
        center_panel = QWidget(); center_layout = QVBoxLayout(center_panel)
        self.image_viewer = ScalableImageLabel("图片区域"); self.image_viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.prompt_text_label = QLabel("提示文字区域"); self.prompt_text_label.setAlignment(Qt.AlignCenter); self.prompt_text_label.setWordWrap(True)
        self.prompt_text_label.setFixedHeight(60); self.prompt_text_label.setStyleSheet("QLabel { padding: 5px; color: #555; }")
        self.notes_text_edit = QTextEdit(); self.notes_text_edit.setReadOnly(True); self.notes_text_edit.setObjectName("NotesTextEdit")
        self.notes_text_edit.setFixedHeight(120); self.notes_text_edit.setStyleSheet("QTextEdit#NotesTextEdit {background-color: #fdfaf6; border: 1px solid #EAE0C9; border-radius: 4px; padding: 8px; color: #4A4034;}")
        self.notes_text_edit.setVisible(False)
        center_layout.addWidget(self.image_viewer, 1); center_layout.addWidget(self.prompt_text_label); center_layout.addWidget(self.notes_text_edit)

        # 右侧面板 (控制) - 这个模块的右侧面板宽度保持默认或由其内容决定
        self.right_panel = QWidget() 
        right_panel_layout = QVBoxLayout(self.right_panel)
        # right_panel.setFixedWidth(320) # 移除此模块右侧面板的固定宽度

        control_group = QGroupBox("操作面板"); self.control_layout = QFormLayout(control_group)
        self.word_list_combo = QComboBox(); self.start_btn = QPushButton("加载并开始"); self.start_btn.setObjectName("AccentButton")
        self.end_session_btn = QPushButton("结束当前会话"); self.end_session_btn.setObjectName("ActionButton_Delete"); self.end_session_btn.hide()
        self.control_layout.addRow("选择图文词表:", self.word_list_combo); self.control_layout.addRow(self.start_btn)
        
        options_group = QGroupBox("会话选项")
        options_layout = QFormLayout(options_group)
        self.random_order_switch = self.ToggleSwitch()
        random_order_layout = QHBoxLayout(); random_order_layout.addWidget(QLabel("随机顺序:")); random_order_layout.addStretch(); random_order_layout.addWidget(self.random_order_switch)
        options_layout.addRow(random_order_layout)
        self.show_prompt_switch = self.ToggleSwitch(); self.show_prompt_switch.setChecked(True)
        show_prompt_layout = QHBoxLayout(); show_prompt_layout.addWidget(QLabel("显示描述:")); show_prompt_layout.addStretch(); show_prompt_layout.addWidget(self.show_prompt_switch)
        options_layout.addRow(show_prompt_layout)
        self.show_notes_switch = self.ToggleSwitch()
        show_notes_layout = QHBoxLayout(); show_notes_layout.addWidget(QLabel("显示备注:")); show_notes_layout.addStretch(); show_notes_layout.addWidget(self.show_notes_switch)
        options_layout.addRow(show_notes_layout)

        self.recording_status_panel = QGroupBox("录音状态")
        status_panel_layout = QVBoxLayout(self.recording_status_panel)
        self.recording_indicator = QLabel("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_label = QLabel("当前音量:"); self.volume_meter = QProgressBar(); self.volume_meter.setRange(0,100); self.volume_meter.setValue(0); self.volume_meter.setTextVisible(False)
        status_panel_layout.addWidget(self.recording_indicator); status_panel_layout.addWidget(self.volume_label); status_panel_layout.addWidget(self.volume_meter)
        self.update_timer = QTimer(); self.update_timer.timeout.connect(self.update_volume_meter)

        self.record_btn = QPushButton("按住录音"); self.record_btn.setEnabled(False)
        self.record_btn.setFixedHeight(50); self.record_btn.setStyleSheet("QPushButton {font-size: 18px; font-weight: bold;}")
        
        right_panel_layout.addWidget(control_group); right_panel_layout.addWidget(options_group)
        right_panel_layout.addWidget(self.recording_status_panel); right_panel_layout.addStretch(); right_panel_layout.addWidget(self.record_btn)
        
        main_layout.addWidget(self.left_panel); 
        main_layout.addWidget(center_panel, 1); 
        main_layout.addWidget(self.right_panel) # 右侧面板加入布局
        self.setLayout(main_layout)

    # ===== 新增/NEW: 应用左侧面板宽度的方法 =====
    def apply_layout_settings(self):
        """从配置中读取并应用左侧边栏宽度。"""
        config = self.parent_window.config 
        ui_settings = config.get("ui_settings", {})
        # 注意：方言图文采集左侧是列表，应使用 editor_sidebar_width
        width = ui_settings.get("editor_sidebar_width", 300) 
        self.left_panel.setFixedWidth(width)


    def load_config_and_prepare(self):
        self.config = self.parent_window.config
        self.apply_layout_settings() # 确保切换到此页面时，宽度被应用
        if not self.session_active: self.populate_word_lists()

    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.record_btn.isEnabled() and not self.is_recording:
                self.is_recording = True; self.handle_record_pressed(); event.accept()
        else: super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.is_recording: self.handle_record_released(); event.accept()
        else: super().keyReleaseEvent(event)

    def handle_record_pressed(self):
        if not self.session_active or self.is_recording: return
        self.is_recording = True; self._start_recording_logic()

    def handle_record_released(self):
        if not self.session_active or not self.is_recording: return
        self._stop_recording_logic()

    def _start_recording_logic(self):
        self.current_item_index = self.item_list_widget.currentRow()
        if self.current_item_index == -1: self.log("请先在列表中选择一个项目！"); self.is_recording = False; return
        self.recording_indicator.setText("● 正在录音"); self.recording_indicator.setStyleSheet("color: red;"); self.update_timer.start(50)
        self.record_btn.setText("正在录音..."); self.record_btn.setStyleSheet("background-color: #f44336; color: white;")
        self.log(f"录制项目: '{self.current_items_list[self.current_item_index].get('id', '未知项目')}'")
        self.audio_queue = queue.Queue(); self.stop_event.clear()
        self.recording_thread = threading.Thread(target=self._recorder_thread_task, daemon=True); self.recording_thread.start()

    def _stop_recording_logic(self):
        if not self.recording_thread or not self.recording_thread.is_alive():
            if self.is_recording: self.is_recording = False
            self.record_btn.setText("按住录音"); self.record_btn.setStyleSheet("")
            return
        self.update_timer.stop()
        self.recording_indicator.setText("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_meter.setValue(0); self.record_btn.setText("按住录音"); self.record_btn.setStyleSheet("")
        self.log("正在保存...")
        self.stop_event.set()
        if self.recording_thread.is_alive(): self.recording_thread.join(timeout=0.5)
        self.is_recording = False
        self._run_task_in_thread(self._save_recording_task)

    def _format_list_item_text(self, item_id, prompt_text): return item_id

    def toggle_notes_visibility(self, state): self.notes_text_edit.setVisible(state == Qt.Checked)
    
    def toggle_prompt_visibility(self, state): self.prompt_text_label.setVisible(state == Qt.Checked)
    
    def on_order_mode_changed(self, state):
        if not self.session_active or not self.current_items_list: return
        current_id = None
        if 0 <= self.current_item_index < len(self.current_items_list):
            current_id = self.current_items_list[self.current_item_index].get('id')
        if state == Qt.Checked:
            self.current_items_list = list(self.original_items_list); random.shuffle(self.current_items_list)
            self.log("项目顺序已切换为: 随机")
        else:
            self.current_items_list = list(self.original_items_list); self.log("项目顺序已切换为: 顺序")
        new_row_index = -1
        if current_id:
            for i, item_data in enumerate(self.current_items_list):
                if item_data.get('id') == current_id: new_row_index = i; break
        self.current_item_index = new_row_index if new_row_index != -1 else 0
        self.update_list_widget()

    def on_item_selected(self, current_item, previous_item):
        if not current_item or not self.session_active:
            self.image_viewer.set_pixmap(None); self.image_viewer.setText("请选择项目")
            self.prompt_text_label.setText(""); self.notes_text_edit.setPlainText("")
            return
        self.current_item_index = self.item_list_widget.row(current_item)
        if self.current_item_index < 0 or self.current_item_index >= len(self.current_items_list): return
        item_data = self.current_items_list[self.current_item_index]
        wordlist_base_dir = os.path.dirname(self.current_wordlist_path)
        image_rel_path = item_data.get('image_path', '')
        image_full_path = os.path.join(wordlist_base_dir, image_rel_path) if image_rel_path else ''
        if image_full_path and os.path.exists(image_full_path):
            reader = QImageReader(image_full_path); reader.setAutoTransform(True); image = reader.read()
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                if not pixmap.isNull(): self.image_viewer.set_pixmap(pixmap)
                else: self.image_viewer.set_pixmap(None); self.image_viewer.setText(f"图片转换失败:\n{os.path.basename(image_rel_path)}")
            else: self.image_viewer.set_pixmap(None); self.image_viewer.setText(f"无法读取图片:\n{os.path.basename(image_rel_path)}\n错误: {reader.errorString()}")
        elif image_rel_path: self.image_viewer.set_pixmap(None); self.image_viewer.setText(f"图片未找到:\n{image_rel_path}")
        else: self.image_viewer.set_pixmap(None); self.image_viewer.setText("此项目无图片或路径未指定")
        self.prompt_text_label.setText(item_data.get('prompt_text', ''))
        self.notes_text_edit.setPlainText(item_data.get('notes', '无备注'))

    def update_volume_meter(self):
        if not self.audio_queue.empty():
            data_chunk = self.audio_queue.get()
            if data_chunk is not None:
                try: volume_norm = np.linalg.norm(data_chunk) * 10; self.volume_meter.setValue(int(volume_norm))
                except Exception as e: print(f"Error calculating volume: {e}")
        else: self.volume_meter.setValue(int(self.volume_meter.value() * 0.8))

    def log(self, msg): self.status_label.setText(f"状态: {msg}")

    def populate_word_lists(self):
        self.word_list_combo.clear()
        if WORD_LIST_DIR_FOR_DIALECT_VISUAL and os.path.exists(WORD_LIST_DIR_FOR_DIALECT_VISUAL):
            try: self.word_list_combo.addItems(sorted([f for f in os.listdir(WORD_LIST_DIR_FOR_DIALECT_VISUAL) if f.endswith('.py')]))
            except Exception as e: self.log(f"错误: 无法读取图文词表目录: {e}")
        else: self.log(f"提示: 图文词表目录未设置或不存在 ({WORD_LIST_DIR_FOR_DIALECT_VISUAL})")

    def reset_ui(self):
        self.word_list_combo.show(); self.start_btn.show()
        for i in range(self.control_layout.rowCount()):
            item_widget = self.control_layout.itemAt(i, QFormLayout.FieldRole).widget() if self.control_layout.itemAt(i, QFormLayout.FieldRole) else None
            if item_widget == self.end_session_btn:
                self.control_layout.removeRow(i); break
        self.item_list_widget.clear(); self.image_viewer.set_pixmap(None); self.image_viewer.setText("请加载图文词表")
        self.prompt_text_label.setText(""); self.notes_text_edit.setPlainText(""); self.notes_text_edit.setVisible(False)
        self.show_notes_switch.setChecked(False); self.record_btn.setEnabled(False); self.log("请选择图文词表开始采集。")

    def end_session(self):
        reply = QMessageBox.question(self, '结束会话', '您确定要结束当前的图文采集会话吗？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.session_active = False; self.current_items_list = []; self.original_items_list = []; self.current_item_index = -1
            self.current_wordlist_path = None; self.current_wordlist_name = None; self.current_audio_folder = None
            self.logger_instance = None; self.reset_ui(); self.populate_word_lists()

    def start_session(self):
        wordlist_file = self.word_list_combo.currentText()
        if not wordlist_file: QMessageBox.warning(self, "错误", "请先选择一个图文词表。"); return
        try:
            self.current_wordlist_name = wordlist_file
            self.original_items_list = self.load_word_list_logic(wordlist_file) 
            if not self.original_items_list: QMessageBox.warning(self, "错误", f"词表 '{wordlist_file}' 为空或加载失败。"); return
            self.current_items_list = list(self.original_items_list)
            if self.random_order_switch.isChecked(): random.shuffle(self.current_items_list)
            self.current_item_index = 0
            wordlist_name_no_ext, _ = os.path.splitext(self.current_wordlist_name)
            self.current_audio_folder = os.path.join(AUDIO_RECORD_DIR_FOR_DIALECT_VISUAL, wordlist_name_no_ext)
            if not os.path.exists(self.current_audio_folder): os.makedirs(self.current_audio_folder)
            log_file_path = os.path.join(self.current_audio_folder, "collection_log.txt")
            self.logger_instance = self.Logger(log_file_path)
            self.logger_instance.log(f"Dialect visual collection session started for wordlist: {self.current_wordlist_name}")
            self.word_list_combo.hide(); self.start_btn.hide()
            self.end_session_btn = QPushButton("结束当前会话"); self.end_session_btn.setObjectName("ActionButton_Delete")
            self.end_session_btn.clicked.connect(self.end_session)
            self.control_layout.addRow(self.end_session_btn)
            QTimer.singleShot(0, self.update_list_widget)
            self.record_btn.setEnabled(True); self.log("准备就绪，请选择项目并开始录音。"); self.session_active = True
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动会话失败: {e}"); self.session_active = False
            if hasattr(self, 'logger_instance') and self.logger_instance: self.logger_instance.log(f"ERROR starting session: {e}")

    def update_list_widget(self):
        current_row = self.item_list_widget.currentRow() if self.item_list_widget.count() > 0 else 0
        self.item_list_widget.clear()
        for index, item_data in enumerate(self.current_items_list):
            display_text = self._format_list_item_text(item_data.get('id', f"项目_{index+1}"), item_data.get('prompt_text', ''))
            list_item = QListWidgetItem(display_text)
            audio_filename = f"{item_data.get('id', f'item_{index+1}')}.mp3"
            if self.current_audio_folder and os.path.exists(os.path.join(self.current_audio_folder, audio_filename)):
                list_item.setIcon(QApplication.style().standardIcon(QStyle.SP_DialogOkButton))
            self.item_list_widget.addItem(list_item)
        if self.current_items_list:
             new_row_to_select = self.current_item_index if self.current_item_index != -1 and self.current_item_index < len(self.current_items_list) else 0
             if new_row_to_select < self.item_list_widget.count():
                self.item_list_widget.setCurrentRow(new_row_to_select)
                selected_item_to_display = self.item_list_widget.item(new_row_to_select)
                if selected_item_to_display: self.on_item_selected(selected_item_to_display, None)

    def on_recording_saved(self):
        self.log("录音已保存。"); self.update_list_widget() 
        if self.current_item_index + 1 < len(self.current_items_list):
            self.current_item_index += 1; self.item_list_widget.setCurrentRow(self.current_item_index)
        else: 
            QMessageBox.information(self,"完成","所有项目已录制完毕！")
            if self.session_active: self.end_session()
        
    # ===== 修改/MODIFIED: 使用配置文件中的录音设备 =====
    def _recorder_thread_task(self):
        try:
            device_index = self.config['audio_settings'].get('input_device_index', None)
            sr = self.config.get('audio_settings', {}).get('sample_rate', 44100)
            ch = self.config.get('audio_settings', {}).get('channels', 1)
            with sd.InputStream(
                device=device_index, 
                samplerate=sr, 
                channels=ch, 
                callback=lambda i,f,t,s:self.audio_queue.put(i.copy())
            ): 
                self.stop_event.wait()
        except Exception as e: 
            print(f"录音线程错误 (DialectVisualCollector): {e}"); self.log(f"录音错误: {e}")

    def _save_recording_task(self, worker_instance):
        if self.audio_queue.empty(): return
        data_chunks = [];
        while not self.audio_queue.empty(): data_chunks.append(self.audio_queue.get())
        if not data_chunks: return
        rec = np.concatenate(data_chunks, axis=0)
        gain = self.config.get('audio_settings', {}).get('recording_gain', 1.0)
        if gain != 1.0: rec = np.clip(rec * gain, -1.0, 1.0)
        item_id = self.current_items_list[self.current_item_index].get('id', f"item_{self.current_item_index + 1}")
        filename = f"{item_id}.mp3"; filepath = os.path.join(self.current_audio_folder, filename)
        try:
            sr = self.config.get('audio_settings', {}).get('sample_rate', 44100)
            sf.write(filepath, rec, sr, format='MP3'); self.log(f"文件 '{filename}' 已保存。")
            if self.logger_instance: self.logger_instance.log(f"Recording saved: {filepath}")
        except Exception as e:
            self.log(f"保存MP3失败: {e}");
            if self.logger_instance: self.logger_instance.log(f"ERROR saving MP3: {e}")
            try:
                wav_path = os.path.splitext(filepath)[0] + ".wav"
                sf.write(wav_path, rec, sr); self.log(f"已尝试保存为WAV: {os.path.basename(wav_path)}")
                if self.logger_instance: self.logger_instance.log(f"Fallback WAV saved: {wav_path}")
            except Exception as e_wav:
                self.log(f"保存WAV也失败: {e_wav}")
                if self.logger_instance: self.logger_instance.log(f"ERROR saving WAV: {e_wav}")
        return None

    def _run_task_in_thread(self, task_func, *args):
        self.thread = QThread(); self.worker = self.Worker(task_func, *args) 
        self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater); self.thread.finished.connect(self.thread.deleteLater)
        self.worker.error.connect(lambda msg:QMessageBox.critical(self,"后台错误",msg))
        if task_func == self._save_recording_task: self.worker.finished.connect(self.on_recording_saved)
        self.thread.start()
        
    def load_word_list_logic(self, filename_from_combo):
        self.current_wordlist_path = os.path.join(WORD_LIST_DIR_FOR_DIALECT_VISUAL, filename_from_combo)
        if not os.path.exists(self.current_wordlist_path): raise FileNotFoundError(f"找不到图文词表文件: {self.current_wordlist_path}")
        module_name = f"dialect_data_{os.path.splitext(filename_from_combo)[0].replace('-', '_').replace('.', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, self.current_wordlist_path)
        if spec is None: raise ImportError(f"无法为 '{self.current_wordlist_path}' 创建模块规范。")
        module_data = importlib.util.module_from_spec(spec)
        try: spec.loader.exec_module(module_data)
        except Exception as e: raise ImportError(f"执行模块 '{self.current_wordlist_path}' 失败: {e}")
        if not hasattr(module_data, 'ITEMS') or not isinstance(module_data.ITEMS, list):
            raise ValueError(f"词表 '{filename_from_combo}' 必须包含一个名为 'ITEMS' 的列表。")
        return module_data.ITEMS