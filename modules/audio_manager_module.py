# --- START OF FILE modules/audio_manager_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "音频数据管理器"
MODULE_DESCRIPTION = "浏览、试听、管理已录制的音频文件，并支持基于波形预览的裁切与合并操作。"
# ---

import os
import sys
import shutil
import tempfile
from datetime import datetime
import subprocess 
from copy import deepcopy
import re  # <--- [新增]
import json # <--- [新增]

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
                             QHeaderView, QAbstractItemView, QMenu, QSplitter, QInputDialog, QLineEdit,
                             QSlider, QComboBox, QApplication, QGroupBox, QSpacerItem, QSizePolicy, QShortcut, QDialog, QDialogButtonBox, QFormLayout, QStyle, QStyleOptionSlider, QCheckBox)
from PyQt5.QtCore import Qt, QTimer, QUrl, QRect, pyqtProperty, pyqtSignal, QEvent, QSize, QEasingCurve, QPropertyAnimation
from PyQt5.QtGui import QIcon, QKeySequence, QPainter, QColor, QPen, QBrush, QPalette, QCursor
from modules.custom_widgets_module import AnimatedListWidget, AnimatedSlider, AnimatedIconButton, WordlistSelectionDialog
# [新增] 导入 QMediaPlayer 和 QMediaContent
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

try:
    import numpy as np
    import soundfile as sf
    AUDIO_ANALYSIS_AVAILABLE = True
except ImportError:
    AUDIO_ANALYSIS_AVAILABLE = False
    print("WARNING: numpy or soundfile not found. Audio auto-volume, editing and visualization features will be disabled.")

# [新增] 自定义QSlider，以支持点击跳转
class ClickableSlider(QSlider):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)

    def _get_value_from_pos(self, pos):
        """根据鼠标位置计算滑块的值。"""
        if self.orientation() == Qt.Horizontal:
            # 使用更精确的 QStyle 方法来计算
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            gr = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
            sr = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
            
            if gr.width() <= 0: return self.minimum()

            slider_length = gr.width()
            slider_min = gr.x()
            slider_max = gr.right() - sr.width()
            
            # 确保点击位置在有效范围内
            clamped_x = max(slider_min, min(pos.x(), slider_max))
            
            value_ratio = (clamped_x - slider_min) / (slider_max - slider_min)

        else: # 垂直方向
            # (类似地，但为简洁起见，我们主要关注水平方向)
            value_ratio = (self.height() - pos.y()) / self.height()

        return self.minimum() + value_ratio * (self.maximum() - self.minimum())

    def mousePressEvent(self, event):
        """当鼠标按下时，立即跳转到该位置。"""
        if event.button() == Qt.LeftButton:
            new_value = self._get_value_from_pos(event.pos())
            self.setValue(int(new_value))
            # 发射 sliderMoved 信号，让播放器立即响应
            self.sliderMoved.emit(int(new_value))
            # 这一步是关键，它使得在按下后立即移动鼠标也能触发 mouseMoveEvent
            # 就像标准的拖动一样
            event.accept()
            return
        
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """在鼠标按住并移动时，持续更新位置。"""
        # 我们只在左键按下的情况下才处理移动事件
        if event.buttons() & Qt.LeftButton:
            new_value = self._get_value_from_pos(event.pos())
            self.setValue(int(new_value))
            self.sliderMoved.emit(int(new_value))
            event.accept()
            return

        super().mouseMoveEvent(event)

class ReorderDialog(QDialog):
    """一个让用户拖动或使用按钮来重排音频文件顺序的对话框。"""
    def __init__(self, filepaths, parent=None, icon_manager=None):
        super().__init__(parent)
        self.icon_manager = icon_manager
        self.setWindowTitle("连接并重排音频")
        self.setMinimumSize(450, 300)

        # 保存原始路径以供后续重排
        self.original_paths = filepaths

        # --- UI 初始化 ---
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("请拖动文件以调整顺序，或使用按钮微调，并输入新文件名:"))

        # 文件列表 (使用支持动画的自定义控件)
        self.file_list = AnimatedListWidget()
        self.file_list.setDragDropMode(QAbstractItemView.InternalMove) # 启用内置的拖放排序
        
        # [关键修复] 添加缺失的这一行，用文件名填充列表
        # 使用 addItemsWithAnimation 是因为这是一个 AnimatedListWidget
        self.file_list.addItemsWithAnimation([os.path.basename(p) for p in filepaths])
        
        # 上移/下移按钮
        button_layout = QHBoxLayout()
        self.up_button = QPushButton("上移")
        self.down_button = QPushButton("下移")
        button_layout.addStretch()
        button_layout.addWidget(self.up_button)
        button_layout.addWidget(self.down_button)

        # 新文件名输入
        form_layout = QFormLayout()
        self.new_name_input = QLineEdit("concatenated_output")
        form_layout.addRow("新文件名:", self.new_name_input)
        
        # OK / Cancel 按钮
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        layout.addWidget(self.file_list)
        layout.addLayout(button_layout)
        layout.addLayout(form_layout)
        layout.addWidget(self.button_box)

        # --- 信号连接 ---
        self._connect_signals()
        
        # --- 图标设置 ---
        self._update_icons()

    def _connect_signals(self):
        """连接此对话框中实际存在的控件信号。"""
        self.up_button.clicked.connect(self.move_up)
        self.down_button.clicked.connect(self.move_down)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def _update_icons(self):
        """设置按钮图标。"""
        if self.icon_manager:
            self.up_button.setIcon(self.icon_manager.get_icon("move_up"))
            self.down_button.setIcon(self.icon_manager.get_icon("move_down"))

    def move_up(self):
        """将当前选中的项向上移动一行。"""
        current_row = self.file_list.currentRow()
        if current_row > 0:
            item = self.file_list.takeItem(current_row)
            self.file_list.insertItem(current_row - 1, item)
            self.file_list.setCurrentRow(current_row - 1)

    def move_down(self):
        """将当前选中的项向下移动一行。"""
        current_row = self.file_list.currentRow()
        if current_row < self.file_list.count() - 1:
            item = self.file_list.takeItem(current_row)
            self.file_list.insertItem(current_row + 1, item)
            self.file_list.setCurrentRow(current_row + 1)
            
    def get_reordered_paths_and_name(self):
        """根据UI中的当前顺序，返回重排后的完整文件路径列表和新文件名。"""
        reordered_filenames = [self.file_list.item(i).text() for i in range(self.file_list.count())]
        path_map = {os.path.basename(p): p for p in self.original_paths}
        reordered_full_paths = [path_map[fname] for fname in reordered_filenames]
        new_name = self.new_name_input.text().strip()
        return reordered_full_paths, new_name

# --- WaveformWidget 类定义保持不变 ---
class WaveformWidget(QWidget):
    clicked_at_ratio = pyqtSignal(float)
    marker_requested_at_ratio = pyqtSignal(float)
    clear_markers_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.setMaximumHeight(60)
        self.setToolTip("音频波形预览。\n- 左键点击/拖动: 寻轨\n- 右键点击: 标记起点/终点\n- 中键点击: 清除标记")
        self._waveform_data = None
        self._playback_pos_ratio = 0.0
        self._trim_start_ratio = -1.0
        self._trim_end_ratio = -1.0
        self.is_scrubbing = False

        # [核心修改] 新增一个属性来保存当前文件的路径
        self._current_filepath = None

        # --- 颜色属性 (无变动) ---
        self._waveformColor = self.palette().color(QPalette.Highlight)
        self._cursorColor = QColor("red")
        self._selectionColor = QColor(0, 100, 255, 60)

    # --- pyqtProperty 定义 (无变动) ---
    @pyqtProperty(QColor)
    def waveformColor(self): return self._waveformColor
    @waveformColor.setter
    def waveformColor(self, color): self._waveformColor = color; self.update()
    @pyqtProperty(QColor)
    def cursorColor(self): return self._cursorColor
    @cursorColor.setter
    def cursorColor(self, color): self._cursorColor = color; self.update()
    @pyqtProperty(QColor)
    def selectionColor(self): return self._selectionColor
    @selectionColor.setter
    def selectionColor(self, color): self._selectionColor = color; self.update()

    def set_waveform_data(self, audio_filepath):
        self.clear() # clear会重置所有内部状态，包括 _current_filepath
        
        if not (audio_filepath and os.path.exists(audio_filepath)):
            self.update()
            return
            
        # [核心修改] 保存文件路径，供 resizeEvent 使用
        self._current_filepath = audio_filepath

        # 防御性检查：如果此时宽度为0，先不处理数据，等待 resizeEvent
        if self.width() <= 0:
            return

        try:
            data, sr = sf.read(audio_filepath, dtype='float32')
            if data.ndim > 1: data = data.mean(axis=1)
            num_samples = len(data)
            target_points = self.width() * 2 
            if num_samples <= target_points or target_points <= 0: self._waveform_data = data
            else:
                step = num_samples // target_points
                peak_data = [np.max(np.abs(data[i:i+step])) for i in range(0, num_samples, step)]
                self._waveform_data = np.array(peak_data)
        except Exception as e:
            print(f"Error loading waveform for {os.path.basename(audio_filepath)}: {e}")
            self._waveform_data = None
        
        self.update()
        
    def update_playback_position(self, current_ms, total_ms):
        self._playback_pos_ratio = current_ms / total_ms if total_ms > 0 else 0.0
        self.update()

    def set_trim_points(self, start_ms, end_ms, total_ms):
        self._trim_start_ratio = start_ms / total_ms if start_ms is not None and total_ms > 0 else -1.0
        self._trim_end_ratio = end_ms / total_ms if end_ms is not None and total_ms > 0 else -1.0
        self.update()

    def clear(self):
        self._waveform_data = None
        self._playback_pos_ratio = 0.0
        self._trim_start_ratio = -1.0
        self._trim_end_ratio = -1.0
        self._current_filepath = None # [核心修改] 清理时也重置路径
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_scrubbing = True; self._handle_scrub(event.pos()); event.accept()
        elif event.button() == Qt.RightButton:
            ratio = event.x() / self.width()
            if 0 <= ratio <= 1: self.marker_requested_at_ratio.emit(ratio)
            event.accept()
        elif event.button() == Qt.MiddleButton:
            self.clear_markers_requested.emit(); event.accept()
        else: super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_scrubbing: self._handle_scrub(event.pos()); event.accept()
        else: super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton: self.is_scrubbing = False; event.accept()
        else: super().mouseReleaseEvent(event)

    def _handle_scrub(self, pos):
        ratio = pos.x() / self.width(); clamped_ratio = max(0.0, min(1.0, ratio))
        self.clicked_at_ratio.emit(clamped_ratio)

    # [新增] 覆盖 resizeEvent 来处理尺寸变化
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 如果当前有一个文件路径，并且控件现在有有效宽度，就强制重新渲染波形
        if self._current_filepath and self.width() > 0:
            # 调用 set_waveform_data 会重新计算波形以适应新宽度
            # 为了避免无限循环，我们只在 _waveform_data 为 None 时才重新加载
            # 这意味着初次加载时宽度为0，现在resize了，需要加载
            if self._waveform_data is None:
                 self.set_waveform_data(self._current_filepath)

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        bg_color = self.palette().color(QPalette.Base); painter.fillRect(self.rect(), bg_color)
        if self._waveform_data is None or len(self._waveform_data) == 0:
            painter.setPen(self.palette().color(QPalette.Mid)); painter.drawText(self.rect(), Qt.AlignCenter, "无波形数据"); return
        pen = QPen(self._waveformColor, 1); painter.setPen(pen)
        h = self.height(); half_h = h / 2; w = self.width(); num_points = len(self._waveform_data)
        max_val = np.max(self._waveform_data)
        if max_val == 0: max_val = 1.0
        for i, val in enumerate(self._waveform_data):
            x = int(i * w / num_points); y_offset = (val / max_val) * half_h
            painter.drawLine(x, int(half_h - y_offset), x, int(half_h + y_offset))
        if self._trim_start_ratio >= 0 and self._trim_end_ratio > self._trim_start_ratio:
            start_x = int(self._trim_start_ratio * w); end_x = int(self._trim_end_ratio * w)
            trim_rect = QRect(start_x, 0, end_x - start_x, h)
            painter.setBrush(QBrush(self._selectionColor)); painter.setPen(Qt.NoPen); painter.drawRect(trim_rect)
        if self._playback_pos_ratio >= 0:
            pos_x = int(self._playback_pos_ratio * w)
            painter.setPen(QPen(self._cursorColor, 2)); painter.drawLine(pos_x, 0, pos_x, h)

class ManageSourcesDialog(QDialog):
    """一个用于批量管理自定义数据源的对话框。"""
    def __init__(self, sources, parent=None, icon_manager=None):
        super().__init__(parent)
        self.setWindowTitle("管理自定义数据源")
        self.setMinimumSize(600, 400)
        
        self.sources = deepcopy(sources)
        self.icon_manager = icon_manager
        
        # --- [核心修改] 新增状态标志 ---
        self.is_dirty = False

        self._init_ui()
        self._connect_signals()
        
        self.populate_table()
        self._update_button_icons()
        # --- [核心修改] 初始化按钮状态 ---
        self._update_main_button_state()

    # --- [核心修正 1] 添加缺失的 _connect_signals 方法 ---
    def _connect_signals(self):
        """连接所有UI控件的信号与槽。"""
        self.add_btn.clicked.connect(self.add_source)
        self.edit_btn.clicked.connect(self.edit_source)
        self.remove_btn.clicked.connect(self.remove_source)
        self.table.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        # --- [核心修改] ---
        # 监听表格单元格内容的变化，任何编辑都会将状态标记为“脏”
        self.table.itemChanged.connect(self._mark_as_dirty)
        # 将主按钮连接到新的状态处理函数
        self.save_close_btn.clicked.connect(self._on_main_button_clicked)

    def _init_ui(self):
        """构建对话框的用户界面。"""
        # ... (此方法的代码保持不变) ...
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("在这里添加、编辑或删除您的自定义数据源快捷方式。"))
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["源名称", "文件夹路径"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("添加新源...")
        self.edit_btn = QPushButton("编辑...")
        self.remove_btn = QPushButton("删除")
        self.save_close_btn = QPushButton("保存/关闭")
        self.save_close_btn.setObjectName("AccentButton")
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.edit_btn)
        btn_layout.addWidget(self.remove_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_close_btn)
        layout.addWidget(self.table)
        layout.addLayout(btn_layout)

    def _validate_and_get_source_path(self, initial_path=""):
        path = QFileDialog.getExistingDirectory(self, "选择数据源文件夹 (应包含多个音频项目文件夹)", initial_path)
        if not path: return None
        supported_exts = ('.wav', '.mp3', '.flac', '.ogg')
        try:
            if any(f.lower().endswith(supported_exts) for f in os.listdir(path)):
                reply = QMessageBox.question(self, "路径可能不正确", f"您选择的文件夹 '{os.path.basename(path)}'似乎直接包含音频文件。\n\n数据源通常是一个包含多个【项目文件夹】的目录。\n\n是否要使用它的上一级目录作为数据源？", QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
                if reply == QMessageBox.Yes: return os.path.dirname(path)
                elif reply == QMessageBox.No: return path
                else: return None
        except OSError: return path
        return path

    def populate_table(self):
        self.table.setRowCount(0)
        for i, source in enumerate(self.sources):
            self.table.insertRow(i)
            name_item = QTableWidgetItem(source['name'])
            path_item = QTableWidgetItem(source['path'])
            path_item.setFlags(path_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 0, name_item)
            self.table.setItem(i, 1, path_item)
    
    def on_item_double_clicked(self, item):
        self.edit_source()

    def add_source(self):
        name, ok1 = QInputDialog.getText(self, "添加新源", "请输入源名称 (可留空以使用文件夹名):")
        if not ok1: return
        path = self._validate_and_get_source_path()
        if not path: return
        final_name = name if name else os.path.basename(path)
        if any(s['name'] == final_name for s in self.sources):
            QMessageBox.warning(self, "名称重复", f"源名称 '{final_name}' 已存在。"); return
        self.sources.append({'name': final_name, 'path': path}); self.populate_table()
        self._mark_as_dirty()

    def edit_source(self):
        current_row = self.table.currentRow()
        if current_row < 0: QMessageBox.information(self, "提示", "请先选择一个要编辑的项目。"); return
        source_to_edit = self.sources[current_row]
        new_name, ok1 = QInputDialog.getText(self, "编辑源名称", "请输入新的源名称:", QLineEdit.Normal, source_to_edit['name'])
        if not (ok1 and new_name.strip()): return
        if any(i != current_row and s['name'] == new_name for i, s in enumerate(self.sources)):
            QMessageBox.warning(self, "名称重复", "该源名称已存在。"); return
        new_path = self._validate_and_get_source_path(source_to_edit['path'])
        if not new_path: return
        self.sources[current_row]['name'] = new_name; self.sources[current_row]['path'] = new_path
        self.populate_table(); self.table.setCurrentCell(current_row, 0)
        self._mark_as_dirty()

    def _update_button_icons(self):
        if self.icon_manager:
            self.add_btn.setIcon(self.icon_manager.get_icon("add_row"))
            self.edit_btn.setIcon(self.icon_manager.get_icon("edit"))
            self.remove_btn.setIcon(self.icon_manager.get_icon("delete"))
            self.save_close_btn.setIcon(self.icon_manager.get_icon("save_2"))

    def remove_source(self):
        current_row = self.table.currentRow()
        if current_row < 0: QMessageBox.information(self, "提示", "请先选择一个要删除的项目。"); return
        source_name = self.sources[current_row]['name']
        reply = QMessageBox.question(self, "确认删除", f"您确定要删除快捷方式 '{source_name}' 吗？\n这不会影响您的原始文件夹。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes: del self.sources[current_row]; self.populate_table()
        self._mark_as_dirty()

    def get_sources(self):
        final_sources = []
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text().strip()
            path = self.table.item(row, 1).text().strip()
            if name and path:
                if any(s['name'] == name for s in final_sources):
                    QMessageBox.warning(self, "保存失败", f"存在重复的源名称: '{name}'。\n请在关闭前修正。"); return None
                final_sources.append({'name': name, 'path': path})
        return final_sources

    def accept(self):
        """重写 accept，在关闭前检查是否有未保存的更改。"""
        if self.is_dirty:
            reply = QMessageBox.question(self, "未保存的更改",
                                         "您有未保存的更改。是否要在关闭前保存它们？",
                                         QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                         QMessageBox.Save)
            
            if reply == QMessageBox.Save:
                if self._save_changes():
                    super().accept() # 只有在保存成功后才关闭
            elif reply == QMessageBox.Discard:
                super().accept() # 用户选择放弃更改，直接关闭
            else: # Cancel
                return # 用户取消关闭，什么都不做
        else:
            super().accept() # 没有更改，直接关闭

    def reject(self):
        """重写 reject，使其行为与 accept 一致，确保关闭窗口 'X' 也能触发检查。"""
        self.accept()

    def _mark_as_dirty(self, item=None):
        """将对话框标记为有未保存的更改，并更新按钮状态。"""
        if not self.is_dirty:
            self.is_dirty = True
            self._update_main_button_state()

    def _update_main_button_state(self):
        """根据 'is_dirty' 状态更新主按钮的文本和图标。"""
        if self.is_dirty:
            self.save_close_btn.setText("保存")
            if self.icon_manager:
                self.save_close_btn.setIcon(self.icon_manager.get_icon("save_2"))
            self.save_close_btn.setToolTip("保存当前更改。")
        else:
            self.save_close_btn.setText("关闭")
            if self.icon_manager:
                # 假设有一个关闭图标，如果没有，它会回退
                self.save_close_btn.setIcon(self.icon_manager.get_icon("close"))
            self.save_close_btn.setToolTip("关闭此对话框。")

    def _on_main_button_clicked(self):
        """主按钮（保存/关闭）被点击时的处理函数。"""
        if self.is_dirty:
            self._save_changes()
        else:
            self.accept() # 如果状态是干净的，则直接关闭

    def _save_changes(self):
        """执行保存操作。"""
        final_sources = self.get_sources()
        if final_sources is not None:
            self.sources = final_sources
            
            # 标记状态为“干净”并更新UI
            self.is_dirty = False
            self._update_main_button_state()
            
            # 可选：给用户一个明确的反馈
            if hasattr(self.parent(), 'status_label'):
                self.parent().status_label.setText("自定义数据源已保存。")
                QTimer.singleShot(3000, lambda: self.parent().status_label.setText("准备就绪"))
            return True
        return False

def create_page(parent_window, config, base_path, results_dir, audio_record_dir, icon_manager, ToggleSwitchClass):
    # [修改] 更新数据源名称
    data_sources = {
        "标准朗读采集": {"path": os.path.join(results_dir, "common"), "filter": lambda d,p: os.path.isdir(os.path.join(p, d))},
        "看图说话采集": {"path": os.path.join(results_dir, "visual"), "filter": lambda d,p: os.path.isdir(os.path.join(p, d))},
        "语音包录制": {"path": audio_record_dir, "filter": lambda d, p: True},
    }
    AUDIO_TTS_DIR = os.path.join(base_path, "audio_tts")
    data_sources["TTS 工具语音"] = {"path": AUDIO_TTS_DIR, "filter": lambda d, p: True}
    return AudioManagerPage(parent_window, config, base_path, data_sources, icon_manager, ToggleSwitchClass)

class AudioManagerPage(QWidget):
    TARGET_RMS = 0.12 
    
    def __init__(self, parent_window, config, base_path, data_sources, icon_manager, ToggleSwitchClass):
        super().__init__()
        self.parent_window = parent_window
        self.config = config
        self.BASE_PATH = base_path
        self.icon_manager = icon_manager
        self.ToggleSwitch = ToggleSwitchClass
        self.DATA_SOURCES = data_sources
        self.current_session_path = None
        self.current_data_type = None
        self.current_displayed_duration = 0
        self.trim_start_ms = None
        self.trim_end_ms = None
        self.temp_preview_file = None
        self.custom_data_sources = []
        self.player_cache = {}
        self.active_player = None
        self.preview_player = None
        self.staged_files = {}
        self.all_files_data = []
        self.current_sort_key = 'name'
        self.global_file_index = []
        self.is_global_search_active = False
        self._is_slider_resetting = False

        # --- 核心修复点 ---
        # 1. 在调用 _init_ui() 之前，提前加载所有UI控件创建时需要依赖的配置值。
        module_states = self.config.get("module_states", {}).get("audio_manager", {})
        self.shortcut_button_action = module_states.get('shortcut_action', 'delete')
        self.adaptive_volume_default_state = module_states.get('adaptive_volume', True)
        
        # 2. 现在可以安全地初始化UI了，因为它依赖的值已经存在。
        self._init_ui()

        # 3. 连接信号和应用布局。
        self._connect_signals()
        self.apply_layout_settings()
        
        # 4. 最后更新图标和加载数据。
        self.update_icons()
        
    def _init_ui(self):
        main_splitter = QSplitter(Qt.Horizontal, self)
        
        # --- 左侧面板 ---
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.addWidget(QLabel("选择数据源:"))
        self.source_combo = QComboBox()
        self.source_combo.addItems(self.DATA_SOURCES.keys())
        self.source_combo.setToolTip("选择要查看的数据类型。")
        
        # [新增] 启用自定义上下文菜单
        self.source_combo.setContextMenuPolicy(Qt.CustomContextMenu)

        left_layout.addWidget(self.source_combo)
        
        left_layout.addWidget(QLabel("项目列表:"))
        self.session_list_widget = AnimatedListWidget()
        self.session_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.session_list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.session_list_widget.setToolTip("双击可直接在文件浏览器中打开。\n右键可进行批量操作。")
        left_layout.addWidget(self.session_list_widget, 1)

        # 音频暂存区 UI
        staging_group = QGroupBox("音频暂存区")
        staging_group.setToolTip("一个临时的区域，用于收集来自不同文件夹的音频以进行连接。")
        staging_layout = QVBoxLayout(staging_group)
        self.staging_list_widget = AnimatedListWidget()
        self.staging_list_widget.setToolTip("当前已暂存的音频文件。\n可在此处预览顺序。")
        
        staging_btn_layout = QHBoxLayout()
        self.process_staged_btn = QPushButton("处理...")
        self.clear_staged_btn = QPushButton("清空")
        staging_btn_layout.addWidget(self.process_staged_btn)
        staging_btn_layout.addWidget(self.clear_staged_btn)
        
        staging_layout.addWidget(self.staging_list_widget)
        staging_layout.addLayout(staging_btn_layout)
        left_layout.addWidget(staging_group)

        # 本地状态标签
        self.status_label = QLabel("准备就绪")
        self.status_label.setObjectName("StatusLabelModule")
        self.status_label.setMinimumHeight(25)
        self.status_label.setWordWrap(True)
        left_layout.addWidget(self.status_label)

        left_layout.setStretchFactor(self.session_list_widget, 1)
        left_layout.setStretchFactor(staging_group, 1)

        # --- 右侧面板 ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.table_label = QLabel("请从左侧选择一个项目以查看文件")
        self.table_label.setAlignment(Qt.AlignCenter)

        # [新增] 搜索和排序控件栏
        controls_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索文件名...")
        self.search_input.setClearButtonEnabled(True)
        
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["按名称排序", "按大小排序", "按修改日期排序", "按词表顺序排序"])
        self.sort_combo.setToolTip("选择文件列表的排序方式。")

        # --- [新增代码] ---
        self.sort_order_btn = QPushButton(" 升/降")
        self.sort_order_btn.setCheckable(True) # 让按钮可以保持按下/弹起状态
        self.sort_order_btn.setToolTip("切换升序/降序排列。")
        # --- [新增结束] ---

        controls_layout.addWidget(self.search_input, 1) # 搜索框占据更多空间
        controls_layout.addWidget(self.sort_combo)
        # --- [新增代码] ---
        controls_layout.addWidget(self.sort_order_btn) # 将新按钮添加到布局中
        # --- [新增结束] ---

        self.audio_table_widget = QTableWidget()
        self.audio_table_widget.setColumnCount(4)
        self.audio_table_widget.setHorizontalHeaderLabels(["文件名", "文件大小", "修改日期", ""])
        self.audio_table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.audio_table_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.audio_table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.audio_table_widget.verticalHeader().setVisible(True)
        self.audio_table_widget.setAlternatingRowColors(True)
        self.audio_table_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.audio_table_widget.setColumnWidth(1, 120)
        self.audio_table_widget.setColumnWidth(2, 180)
        self.audio_table_widget.setColumnWidth(3, 80)
        self.audio_table_widget.setToolTip("双击或按Enter键可播放，右键可进行更多操作。")

        # 播放器UI
        playback_v_layout = QVBoxLayout()
        playback_v_layout.setContentsMargins(0, 5, 0, 5)
        
        playback_h_layout = QHBoxLayout()
        # [核心修改] 使用新的 AnimatedIconButton 替换 QPushButton
        self.play_pause_btn = AnimatedIconButton(self.icon_manager, self)
        self.play_pause_btn.setMinimumWidth(50)
        self.play_pause_btn.setIconSize(QSize(20, 20))
        self.play_pause_btn.setToolTip("播放或暂停当前选中的音频 (空格键)")
        
        # [核心修正] 调用 setIcons 时传入图标名称字符串
        self.play_pause_btn.setIcons("play", "pause")
        # [核心修改] 使用新的 AnimatedSlider 替换 ClickableSlider
        self.playback_slider = AnimatedSlider(Qt.Horizontal)
        self.playback_slider.setObjectName("PlaybackSlider") # 增加 objectName 以便 QSS 定位
        self.playback_slider.setToolTip("显示当前播放进度，可拖动或点击以跳转。")
        
        volume_layout = QHBoxLayout()
        volume_layout.setSpacing(5)
        self.adaptive_volume_switch = self.ToggleSwitch()
        self.adaptive_volume_switch.setToolTip("开启后，将根据音频响度自动调整初始音量。")
        self.adaptive_volume_switch.setChecked(self.adaptive_volume_default_state)
        volume_layout.addWidget(self.adaptive_volume_switch)
        volume_layout.addWidget(QLabel("自适应"))
        self.volume_label = QLabel("音量:")
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setToolTip("调整播放音量。")
        self.volume_percent_label = QLabel("100%")
        volume_layout.addWidget(self.volume_label)
        volume_layout.addWidget(self.volume_slider)
        volume_layout.addWidget(self.volume_percent_label)
        
        playback_h_layout.addWidget(self.play_pause_btn)
        playback_h_layout.addWidget(self.playback_slider, 10)
        playback_h_layout.addStretch(1)
        playback_h_layout.addLayout(volume_layout)
        
        waveform_time_layout = QHBoxLayout()
        self.waveform_widget = WaveformWidget()
        self.duration_label = QLabel("00:00.00 / 00:00.00")
        waveform_time_layout.addWidget(self.waveform_widget, 10)
        waveform_time_layout.addWidget(self.duration_label)
        
        playback_v_layout.addLayout(playback_h_layout)
        playback_v_layout.addLayout(waveform_time_layout)

        # 编辑面板UI
        self.edit_panel_container = QWidget()
        container_layout = QVBoxLayout(self.edit_panel_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        self.edit_panel = QGroupBox("音频编辑")
        edit_controls_layout = QHBoxLayout(self.edit_panel)
        edit_controls_layout.setSpacing(10)
        
        self.trim_start_label = QLabel("起点: --:--.--")
        self.set_start_btn = QPushButton("起点")
        self.set_start_btn.setToolTip("将当前播放位置标记为裁切起点。\n快捷键：在波形图上右键单击。")
        self.set_end_btn = QPushButton("终点")
        self.set_end_btn.setToolTip("将当前播放位置标记为裁切终点。\n快捷键：在波形图上再次右键单击。")
        self.trim_end_label = QLabel("终点: --:--.--")
        
        self.clear_trim_btn = QPushButton("清除")
        self.clear_trim_btn.setToolTip("清除已标记的起点和终点。\n快捷键：在波形图上中键单击。")
        self.preview_trim_btn = QPushButton("预览")
        self.preview_trim_btn.setToolTip("试听当前标记范围内的音频。")
        self.save_trim_btn = QPushButton("保存...") # 加上省略号，暗示有更多选项
        self.save_trim_btn.setToolTip("将处理后的音频另存为新文件。\n右键单击可选择不同的保存模式。")
        self.save_trim_btn.setObjectName("AccentButton")
        self.save_trim_btn.setContextMenuPolicy(Qt.CustomContextMenu) # 设置右键菜单策略
        self.save_trim_btn = QPushButton("保存")
        self.save_trim_btn.setToolTip("将裁切后的音频另存为新文件。")
        self.save_trim_btn.setObjectName("AccentButton")
        
        edit_controls_layout.addWidget(self.trim_start_label)
        edit_controls_layout.addWidget(self.set_start_btn)
        edit_controls_layout.addWidget(self.set_end_btn)
        edit_controls_layout.addWidget(self.trim_end_label)
        edit_controls_layout.addStretch(1)
        edit_controls_layout.addWidget(self.clear_trim_btn)
        edit_controls_layout.addWidget(self.preview_trim_btn)
        edit_controls_layout.addWidget(self.save_trim_btn)
        
        container_layout.addWidget(self.edit_panel)
        self.edit_panel_container.setVisible(False)
        
        # 组装右侧面板布局
        right_layout.addWidget(self.table_label)
        right_layout.addLayout(controls_layout)  # [修改] 添加新控件栏到布局中
        right_layout.addWidget(self.audio_table_widget, 1)
        right_layout.addWidget(self.edit_panel_container)
        right_layout.addLayout(playback_v_layout)
        
        # 组装主布局
        main_splitter.addWidget(self.left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)
        
        page_layout = QHBoxLayout(self)
        page_layout.addWidget(main_splitter)
        # 启用拖放并安装事件过滤器
        self.session_list_widget.setAcceptDrops(True)
        self.audio_table_widget.setAcceptDrops(True)
        self.session_list_widget.installEventFilter(self)
        self.audio_table_widget.installEventFilter(self)
        self.source_combo.installEventFilter(self)
        self.setFocusPolicy(Qt.StrongFocus)
        self.reset_player()

    def eventFilter(self, obj, event):
        """
        [v1.2 - Fix] 事件过滤器。
        移除了之前为排序下拉框添加的双击清除词表关联的逻辑。
        """
        # --- 拖放事件处理 ---
        if obj is self.session_list_widget:
            if event.type() == QEvent.DragEnter:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Drop:
                self._handle_folder_drop(event)
                return True
        elif obj is self.audio_table_widget:
            # ... (拖放逻辑不变) ...
            if event.type() == QEvent.Drop:
                self._handle_audio_file_drop(event)
                return True
        
        # [核心修复] 下面这整个 'elif' 代码块已被完全移除
        # elif obj is self.sort_combo and event.type() == QEvent.MouseButtonDblClick:
        #    ...

        # --- 原有的数据源下拉框双击事件处理 ---
        if obj is self.source_combo and event.type() == QEvent.MouseButtonDblClick:
            self._manage_custom_sources()
            return True
        
        # 对于所有其他事件，调用父类的默认实现
        return super().eventFilter(obj, event)

    def _perform_file_operation(self, paths, dest_dir):
        """
        [新增 v1.1 - 修复版] 
        弹窗询问用户是复制还是移动，并根据项目类型（文件或文件夹）执行相应的操作。
        """
        if not paths: return False
        
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("选择操作")
        msg_box.setText(f"要将 {len(paths)} 个项目如何处理？")
        msg_box.setInformativeText(f"目标目录: {os.path.basename(dest_dir)}")
        copy_button = msg_box.addButton("复制", QMessageBox.AcceptRole)
        move_button = msg_box.addButton("移动", QMessageBox.DestructiveRole)
        msg_box.addButton("取消", QMessageBox.RejectRole)
        msg_box.exec_()
        
        clicked_button = msg_box.clickedButton()
        is_copy = clicked_button == copy_button
        is_move = clicked_button == move_button

        if not (is_copy or is_move):
            return False # 用户取消

        errors = []
        for path in paths:
            try:
                target_path = os.path.join(dest_dir, os.path.basename(path))
                if os.path.exists(target_path):
                    errors.append(f"跳过 '{os.path.basename(path)}'：目标位置已存在同名项。")
                    continue
                
                # --- [核心修复] ---
                # 根据操作类型和文件/文件夹类型选择正确的 shutil 函数
                if is_copy:
                    if os.path.isdir(path):
                        # 对文件夹使用 shutil.copytree
                        # copytree 的目标路径(target_path)必须是不存在的
                        shutil.copytree(path, target_path)
                    else:
                        # 对文件使用 shutil.copy2
                        # copy2 的目标路径(dest_dir)是目录
                        shutil.copy2(path, dest_dir)
                elif is_move:
                    # shutil.move 可以智能处理文件和文件夹
                    # 它的目标路径(dest_dir)是目录
                    shutil.move(path, dest_dir)
                # --- [修复结束] ---

            except Exception as e:
                errors.append(f"处理 '{os.path.basename(path)}' 时出错: {e}")

        if errors:
            QMessageBox.warning(self, "操作中出现问题", "\n".join(errors))
        return True

    def _handle_folder_drop(self, event):
        """[新增] 处理拖拽到项目列表（session_list_widget）的事件。"""
        source_name = self.source_combo.currentText()
        source_info = self.DATA_SOURCES.get(source_name)
        if not source_info:
            for custom_source in self.custom_data_sources:
                if custom_source['name'] == source_name:
                    source_info = {"path": custom_source['path']}
                    break
        if not source_info:
            QMessageBox.warning(self, "操作无效", "无法确定当前数据源的目标路径。")
            return
            
        dest_dir = source_info['path']
        
        # 筛选出拖入的文件夹
        dropped_folders = [
            url.toLocalFile() for url in event.mimeData().urls() 
            if os.path.isdir(url.toLocalFile())
        ]
        
        if not dropped_folders:
            self.status_label.setText("操作取消：没有拖入文件夹。")
            QTimer.singleShot(2000, lambda: self.status_label.setText("准备就绪"))
            return

        if self._perform_file_operation(dropped_folders, dest_dir):
            self.populate_session_list() # 成功后刷新列表

    def _handle_audio_file_drop(self, event):
        """[新增] 处理拖拽到文件列表（audio_table_widget）的事件。"""
        if not self.current_session_path:
            QMessageBox.warning(self, "操作无效", "请先从左侧选择一个项目文件夹。")
            return
            
        dest_dir = self.current_session_path
        supported_exts = ('.wav', '.mp3', '.flac', '.ogg')
        
        # 筛选出拖入的音频文件
        dropped_files = [
            url.toLocalFile() for url in event.mimeData().urls()
            if os.path.isfile(url.toLocalFile()) and url.toLocalFile().lower().endswith(supported_exts)
        ]

        if not dropped_files:
            self.status_label.setText("操作取消：没有拖入支持的音频文件。")
            QTimer.singleShot(2000, lambda: self.status_label.setText("准备就绪"))
            return

        if self._perform_file_operation(dropped_files, dest_dir):
            self.populate_audio_table() # 成功后刷新列表

    def send_to_batch_analysis(self, filepaths):
        """
        [新增] 一个辅助方法，用于将文件列表发送到音频分析模块的批量模式。
        """
        # 1. 安全检查，确保音频分析模块已加载
        if not hasattr(self.parent_window, 'audio_analysis_page'):
            QMessageBox.warning(self, "功能缺失", "音频分析模块未成功加载。")
            return
        
        audio_analysis_page = self.parent_window.audio_analysis_page
    
        # 2. 调用主窗口的导航API，切换到“音频分析” -> “批量分析”标签页
        target_page = self.parent_window._navigate_to_tab("资源管理", "音频分析")
        if target_page:
            # 切换到批量分析模式 (通过切换ToggleSwitch)
            target_page.mode_toggle.setChecked(True)
        
            # 3. 调用批量面板的公共API来加载文件
            if hasattr(target_page, 'batch_analysis_panel') and \
               hasattr(target_page.batch_analysis_panel, 'load_files_from_external'):
                target_page.batch_analysis_panel.load_files_from_external(filepaths)
        else:
            QMessageBox.warning(self, "导航失败", "无法切换到音频分析模块。")

# [新增] 用于处理表格中快捷播放按钮点击的智能方法
    def _on_shortcut_play_button_clicked(self, row):
        """
        处理表格中快捷播放/暂停按钮的点击事件。
        """
        # [核心修正] 区分全局搜索和常规模式
        if self.is_global_search_active:
            item = self.audio_table_widget.item(row, 0)
            if item:
                filepath = item.data(Qt.UserRole)
                self.go_to_file(filepath)
        else:
            # 常规模式下的逻辑保持不变
            current_row = self.audio_table_widget.currentRow()
            if row == current_row:
                self.toggle_playback()
            else:
                self.play_selected_item(row)

    def _connect_signals(self):
        # [核心修改] 使用 currentTextChanged 信号，这样可以处理用户输入和程序设置
        self.source_combo.currentTextChanged.connect(self.on_source_changed)

        # [新增] 连接右键菜单信号
        self.source_combo.customContextMenuRequested.connect(self.open_source_context_menu)

        self.session_list_widget.itemSelectionChanged.connect(self.on_session_selection_changed); self.session_list_widget.customContextMenuRequested.connect(self.open_folder_context_menu)
        self.session_list_widget.itemDoubleClicked.connect(self.on_session_item_double_clicked)
        self.play_pause_btn.toggled.connect(self.on_play_button_toggled)
        self.playback_slider.sliderMoved.connect(self.set_playback_position)
        self.volume_slider.valueChanged.connect(self._on_volume_slider_changed)
        self.adaptive_volume_switch.stateChanged.connect(self._on_adaptive_volume_toggled_and_save)
        self.audio_table_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.audio_table_widget.customContextMenuRequested.connect(self.open_file_context_menu); self.audio_table_widget.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.set_start_btn.clicked.connect(self._set_trim_start); self.set_end_btn.clicked.connect(self._set_trim_end)
        self.clear_trim_btn.clicked.connect(self._clear_trim_points); self.preview_trim_btn.clicked.connect(self._preview_trim)
        # 新增右键菜单信号连接
        self.save_trim_btn.customContextMenuRequested.connect(self._show_save_trim_menu)
        # 左键点击也弹出菜单，提供更直观的操作
        self.save_trim_btn.clicked.connect(lambda: self._show_save_trim_menu(self.save_trim_btn.rect().bottomLeft()))
        self.process_staged_btn.clicked.connect(self._show_staging_process_menu)
        self.clear_staged_btn.clicked.connect(self._clear_staging_area)
        self.waveform_widget.clicked_at_ratio.connect(self.seek_from_waveform_click)
        self.waveform_widget.marker_requested_at_ratio.connect(self.set_marker_from_waveform)
        self.waveform_widget.clear_markers_requested.connect(self._clear_trim_points)
        # --- [新增] 连接搜索和排序信号 ---
        self.search_input.textChanged.connect(self.filter_and_render_files)
        self.sort_combo.currentIndexChanged.connect(self.on_sort_changed)
        # --- [新增代码] ---
        self.sort_order_btn.toggled.connect(self.on_sort_order_changed)
        # --- [新增结束] ---
        # [新增] 使用 QShortcut 设置快捷键，这是处理焦点问题的正确方法
        # 播放/暂停快捷键 (空格)
        self.toggle_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        self.toggle_shortcut.activated.connect(self.toggle_playback)
        
        # 播放选中项快捷键 (回车)
        self.play_shortcut = QShortcut(QKeySequence(Qt.Key_Return), self)
        self.play_shortcut.activated.connect(self.play_current_selected_item_from_shortcut)
        self.play_shortcut_enter = QShortcut(QKeySequence(Qt.Key_Enter), self)
        self.play_shortcut_enter.activated.connect(self.play_current_selected_item_from_shortcut)
    def open_settings_dialog(self):
        """
        创建并显示音频管理器的设置对话框。
        """
        # --- [核心修改] ---
        # 1. 在创建对话框前，先检查插件是否可用
        file_manager_plugin = self.parent_window.plugin_manager.get_plugin_instance("com.phonacq.file_manager")
        is_plugin_available = file_manager_plugin is not None and hasattr(file_manager_plugin, 'move_to_trash')

        # 2. 将插件可用状态传递给对话框的构造函数
        dialog = SettingsDialog(self, file_manager_available=is_plugin_available)
        # --- 修改结束 ---

        if dialog.exec_() == QDialog.Accepted:
            self.parent_window.request_tab_refresh(self)

    def _show_save_trim_menu(self, position):
        """
        [新增] 创建并显示保存/裁切选项的右键菜单。
        """
        # 只有在至少标记了一个点时才显示菜单
        if self.trim_start_ms is None and self.trim_end_ms is None:
            QMessageBox.information(self, "无标记点", "请先在波形图上使用右键单击来标记起点或终点。")
            return

        menu = QMenu(self)
        
        # --- 根据标记点动态构建菜单项 ---
        has_start = self.trim_start_ms is not None
        has_end = self.trim_end_ms is not None
        
        if has_start and has_end:
            # 同时有起点和终点
            save_selection_action = menu.addAction(self.icon_manager.get_icon("save"), "保存选中部分 (保留)")
            save_selection_action.triggered.connect(lambda: self._execute_audio_operation(self._save_trim_logic, mode='keep_selection'))

            trim_selection_action = menu.addAction(self.icon_manager.get_icon("cut"), "裁去选中部分 (删除)")
            trim_selection_action.triggered.connect(lambda: self._execute_audio_operation(self._save_trim_logic, mode='trim_selection'))
        
        elif has_start:
            # 只有起点
            trim_before_action = menu.addAction(self.icon_manager.get_icon("prev"), "裁去起点之前的部分")
            trim_before_action.triggered.connect(lambda: self._execute_audio_operation(self._save_trim_logic, mode='trim_before'))

        elif has_end:
            # 只有终点
            trim_after_action = menu.addAction(self.icon_manager.get_icon("next"), "裁去终点之后的部分")
            trim_after_action.triggered.connect(lambda: self._execute_audio_operation(self._save_trim_logic, mode='trim_after'))

        # 仅当至少有一个标记点时，才显示覆盖选项
        if has_start or has_end:
            menu.addSeparator()
            
            # 创建一个子菜单来放置所有危险的覆盖操作
            overwrite_menu = menu.addMenu("覆盖原文件 (危险！)")
            overwrite_menu.setIcon(self.icon_manager.get_icon("replace")) # 假设有此图标

            if has_start and has_end:
                overwrite_keep_action = overwrite_menu.addAction("保留选中部分 (覆盖)")
                overwrite_keep_action.triggered.connect(lambda: self._execute_audio_operation(self._save_trim_logic, mode='keep_selection', overwrite=True))
                
                overwrite_trim_action = overwrite_menu.addAction("裁去选中部分 (覆盖)")
                overwrite_trim_action.triggered.connect(lambda: self._execute_audio_operation(self._save_trim_logic, mode='trim_selection', overwrite=True))

            elif has_start:
                overwrite_before_action = overwrite_menu.addAction("裁去起点之前 (覆盖)")
                overwrite_before_action.triggered.connect(lambda: self._execute_audio_operation(self._save_trim_logic, mode='trim_before', overwrite=True))
                
            elif has_end:
                overwrite_after_action = overwrite_menu.addAction("裁去终点之后 (覆盖)")
                overwrite_after_action.triggered.connect(lambda: self._execute_audio_operation(self._save_trim_logic, mode='trim_after', overwrite=True))

        # 在按钮下方显示菜单
        menu.exec_(self.save_trim_btn.mapToGlobal(position))

    def play_current_selected_item_from_shortcut(self):
        """专门用于响应回车快捷键，播放当前在表格中选中的项。"""
        if self.audio_table_widget.hasFocus():
            current_row = self.audio_table_widget.currentRow()
            if current_row != -1:
                self.play_selected_item(current_row)

    # [新增] 核心方法：更新播放器缓存池
    def _update_player_cache(self, current_row):
        if not self.session_active or self.audio_table_widget.rowCount() == 0: return

        # [修改] 动态从配置读取并计算缓存大小
        total_cache_size = self.config.get("audio_settings", {}).get("player_cache_size", 5)
        
        # 按 1:3 的比例分配，确保 prev_cache 至少为1，next_cache 至少为1
        prev_cache = max(1, round(total_cache_size / 4))
        next_cache = total_cache_size - prev_cache - 1 # -1 是因为当前项也占一个名额
        if next_cache < 1:
            next_cache = 1
            prev_cache = max(1, total_cache_size - next_cache - 1)

        # 1. 确定需要缓存的文件范围
        center_index = current_row
        num_rows = self.audio_table_widget.rowCount()
        
        start_index = max(0, center_index - prev_cache)
        end_index = min(num_rows, center_index + next_cache + 1) # +1是因为range不包含末尾
        
        needed_filepaths = set()
        for i in range(start_index, end_index):
            item = self.audio_table_widget.item(i, 0)
            if item:
                needed_filepaths.add(item.data(Qt.UserRole))

        # ... (后续的清理和加载逻辑不变) ...
        cached_paths = set(self.player_cache.keys())
        paths_to_remove = cached_paths - needed_filepaths
        for path in paths_to_remove:
            player_to_remove = self.player_cache.pop(path, None)
            if player_to_remove: player_to_remove.stop(); player_to_remove.setMedia(QMediaContent()); player_to_remove.deleteLater()
        for path in needed_filepaths:
            if path not in self.player_cache:
                player = QMediaPlayer()
                player.setNotifyInterval(16)
                player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
                
                # [核心新增] 为每个新创建的播放器连接错误处理信号
                player.error.connect(self._handle_playback_error)
                
                self.player_cache[path] = player

    # [新增] 用于处理播放错误的槽函数
    def _handle_playback_error(self, error):
        if error == QMediaPlayer.NoError:
            return
            
        failed_player = self.sender()
        if not failed_player: return

        filepath = failed_player.media().canonicalUrl().toLocalFile()
        
        processor_plugin = getattr(self, 'batch_processor_plugin_active', None)
        if processor_plugin and hasattr(processor_plugin, 'execute_automatic_fix'):
            print(f"Playback error on {filepath}. Attempting automatic fix via plugin.")
            
            # [优化] 将 self.reset_player 作为前置回调传递给插件
            # self.reset_player 会停止所有播放器并释放文件句柄
            processor_plugin.execute_automatic_fix(
                filepath=filepath,
                on_success_callback=self._on_auto_fix_success,
                pre_fix_callback=self.reset_player 
            )
        else:
            QMessageBox.critical(self, "播放错误", f"无法播放文件: {os.path.basename(filepath)}\n\n错误代码: {error}")

    # [新增] 自动修复成功后的回调函数
    def _on_auto_fix_success(self, new_filepath):
        """
        当插件成功修复并转换文件后，此方法被调用。
        """
        print(f"File successfully fixed. New file at: {new_filepath}")
        
        # 1. 刷新文件列表以显示新的 .wav 文件并移除旧文件
        self.populate_audio_table()
        
        # 2. 延迟执行，确保UI刷新完成
        def find_and_play_new_file():
            for row in range(self.audio_table_widget.rowCount()):
                item_path = self.audio_table_widget.item(row, 0).data(Qt.UserRole)
                if item_path == new_filepath:
                    # 3. 找到了新文件，选中它并尝试播放
                    self.audio_table_widget.setCurrentCell(row, 0)
                    self.play_selected_item(row)
                    break
        
        QTimer.singleShot(100, find_and_play_new_file)

    # [新增] 构建全局文件索引
    def _build_global_file_index(self):
        """
        遍历所有数据源（内置和自定义），构建一个包含所有音频文件的全局索引。
        """
        self.global_file_index.clear()
        all_sources = self.DATA_SOURCES.copy()
        for source in self.custom_data_sources:
            all_sources[source['name']] = {"path": source['path'], "filter": lambda d, p: os.path.isdir(os.path.join(p, d))}

        supported_exts = ('.wav', '.mp3', '.flac', '.ogg')

        for source_name, source_info in all_sources.items():
            base_path = source_info["path"]
            if not os.path.exists(base_path):
                continue
            
            try:
                # 遍历项目文件夹
                for project_name in os.listdir(base_path):
                    project_path = os.path.join(base_path, project_name)
                    if not os.path.isdir(project_path):
                        continue
                    
                    # 遍历项目文件夹内的音频文件
                    for filename in os.listdir(project_path):
                        if filename.lower().endswith(supported_exts):
                            filepath = os.path.join(project_path, filename)
                            self.global_file_index.append({
                                'path': filepath,
                                'name': filename,
                                'source_name': source_name,
                                'project_name': project_name,
                            })
            except Exception as e:
                print(f"Error building index for source '{source_name}': {e}")

    # [新增] 用于处理波形图右键点击标记的槽函数
    def set_marker_from_waveform(self, ratio):
        """根据波形图上的右键点击来设置起点或终点。"""
        if not self.active_player or self.active_player.duration() <= 0:
            return

        # 计算点击位置对应的时间（毫秒）
        clicked_ms = int(self.active_player.duration() * ratio)

        # 如果没有起点，则将本次点击设为起点
        if self.trim_start_ms is None:
            self.trim_start_ms = clicked_ms
        else:
            # 如果已有起点，则将本次点击设为终点
            # 并确保起点总是在终点之前
            if clicked_ms < self.trim_start_ms:
                # 如果新点在起点前，则将原起点设为终点，新点设为起点
                self.trim_end_ms = self.trim_start_ms
                self.trim_start_ms = clicked_ms
            else:
                self.trim_end_ms = clicked_ms
        
        # 更新UI显示
        self.trim_start_label.setText(f"起点: {self.format_time(self.trim_start_ms)}")
        if self.trim_end_ms is not None:
            self.trim_end_label.setText(f"终点: {self.format_time(self.trim_end_ms)}")
        else:
            self.trim_end_label.setText("终点: --:--.--")
            
        # 更新波形图上的选区高亮
        self.waveform_widget.set_trim_points(self.trim_start_ms, self.trim_end_ms, self.active_player.duration())

    def seek_from_waveform_click(self, ratio):
        """根据点击的比例，跳转到音频的相应位置。"""
        if self.active_player and self.active_player.duration() > 0:
            target_position = int(self.active_player.duration() * ratio)
            self.active_player.setPosition(target_position)
                
    # [新增] 核心方法：设置当前激活的播放器并连接UI
    def _set_active_player(self, filepath):
        """[v2.3 信号修正版] 安全地设置当前激活的播放器并连接UI。"""
        try:
            if self.active_player:
                # 断开所有旧连接
                self.active_player.positionChanged.disconnect(self.update_playback_position)
                self.active_player.durationChanged.disconnect(self.update_playback_duration)
                self.active_player.stateChanged.disconnect(self.on_player_state_changed)
                # [核心修正] 断开 mediaStatusChanged 信号
                self.active_player.mediaStatusChanged.disconnect(self._on_media_status_changed)
        except (RuntimeError, TypeError):
            pass
        finally:
            self.active_player = None

        new_player = self.player_cache.get(filepath)
        self.active_player = new_player
    
        if not self.active_player:
            self.reset_player_ui()
            return
        
        # 建立所有新连接
        self.active_player.positionChanged.connect(self.update_playback_position)
        self.active_player.durationChanged.connect(self.update_playback_duration)
        self.active_player.stateChanged.connect(self.on_player_state_changed)
        # [核心修正] 连接 mediaStatusChanged 信号
        self.active_player.mediaStatusChanged.connect(self._on_media_status_changed)
    
        # ... (后续的UI更新代码保持不变) ...
        self.update_playback_duration(self.active_player.duration())
        self.update_playback_position(self.active_player.position())
        self.on_player_state_changed(self.active_player.state())
        self._on_volume_slider_changed(self.volume_slider.value())

    def _on_media_status_changed(self, status):
        """
        当播放器的媒体状态改变时调用，专门用于处理播放结束事件。
        """
        if status == QMediaPlayer.EndOfMedia:
            # 逻辑上重置播放器
            if self.active_player:
                self.active_player.blockSignals(True)
                self.active_player.stop() 
                self.active_player.setPosition(0)
                self.active_player.blockSignals(False)

            # 切换按钮状态
            self.play_pause_btn.setChecked(False)
            
            # [核心修改] 不再手动更新UI，而是启动平滑的归零动画
            self._start_slider_reset_animation()

    def _clear_player_cache(self):
        """[v2.2 健壮版] 安全地清理所有播放器实例。"""
        # 清理缓存池中的所有播放器
        for player in self.player_cache.values():
            try:
                # 检查 C++ 对象是否存在，如果不存在或已删除，访问属性会触发 RuntimeError
                if player:
                    player.stop()
                    player.setMedia(QMediaContent())
            except RuntimeError:
                # 对象已被删除，静默地忽略
                pass
        self.player_cache.clear()

        # 安全地清理当前激活的播放器
        try:
            if self.active_player:
                self.active_player.stop()
                self.active_player.setMedia(QMediaContent())
        except RuntimeError:
            pass # 静默忽略
        finally:
            # 无论如何，都将Python引用设为None
            self.active_player = None

    # [修改] 表格选择变化时，更新缓存
    def _on_table_selection_changed(self):
        selected_items = self.audio_table_widget.selectedItems(); selected_rows_count = len(set(item.row() for item in selected_items)); is_single_selection = selected_rows_count == 1
        self.edit_panel_container.setVisible(AUDIO_ANALYSIS_AVAILABLE); self.edit_panel.setEnabled(is_single_selection); self.waveform_widget.setEnabled(is_single_selection)
        if is_single_selection:
            current_row = self.audio_table_widget.currentRow()
            filepath = self.audio_table_widget.item(current_row, 0).data(Qt.UserRole)
            
            # 正确的顺序：先确保资源就绪，再使用资源
            # 步骤1：更新缓存，确保播放器实例已创建并放入 self.player_cache
            self._update_player_cache(current_row) 
            
            # 步骤2：现在可以安全地设置波形图和激活播放器了
            self.waveform_widget.set_waveform_data(filepath)
            self._set_active_player(filepath)      # 此时它一定能从缓存中找到播放器
        else:
            self.waveform_widget.clear()
            self._clear_trim_points()

    # [修改] 播放逻辑
    def play_selected_item(self, row):
        item = self.audio_table_widget.item(row, 0)
        if not item: return

        # [核心修改] 在播放主音频前，先停止预览播放器并清理其状态
        if self.preview_player and self.preview_player.state() != QMediaPlayer.StoppedState:
            self._on_preview_player_state_changed(QMediaPlayer.StoppedState) # 调用清理方法
            self.preview_player.stop()

        # ... (后续的停止缓存池播放器、加载和播放主音频的逻辑保持不变) ...
        for player in self.player_cache.values():
            if player and player.state() == QMediaPlayer.PlayingState:
                player.stop()

        filepath = item.data(Qt.UserRole)
        self._calculate_and_set_optimal_volume(filepath)
        
        if not self.active_player or (self.active_player.media() and self.active_player.media().canonicalUrl().toLocalFile() != filepath):
            self._update_player_cache(row)
            self._set_active_player(filepath)
        
        if self.active_player:
            # [核心修正] 主动更新UI，立即响应用户的播放意图。
            # 在发送 play() 指令前，就手动将按钮设置为“播放中”(checked)状态。
            self.play_pause_btn.setChecked(True)

            # 确保在播放前，播放位置回到开头
            self.active_player.setPosition(0)
            self.active_player.play()

    def _request_delete_items(self, paths, is_folder=False):
        """
        [v3.0 - 配置统一版]
        处理文件或文件夹的删除请求。
        根据用户在设置中选择的删除行为（回收站或永久删除），执行相应的操作。
        """
        if not paths:
            return

        # 1. 从配置中读取用户首选的删除方式
        module_states = self.config.get("module_states", {}).get("audio_manager", {})
        # 默认为 'trash'，如果未设置，则优先尝试回收站
        delete_behavior = module_states.get("deletion_behavior", "trash")
        
        # 2. 尝试获取文件管理器插件实例
        file_manager_plugin = self.parent_window.plugin_manager.get_plugin_instance("com.phonacq.file_manager")
        is_plugin_available = file_manager_plugin and hasattr(file_manager_plugin, 'move_to_trash')

        # 3. 决策逻辑：只有在用户首选且插件可用时，才使用回收站
        if delete_behavior == "trash" and is_plugin_available:
            # --- 方案A: 使用插件的回收站功能 ---
            success, message = file_manager_plugin.move_to_trash(paths)
            if success:
                self.status_label.setText(message)
                QTimer.singleShot(3000, lambda: self.status_label.setText("准备就绪"))
            else:
                QMessageBox.critical(self, "移至回收站失败", message)
        else:
            # --- 方案B: 回退到永久删除 ---
            count = len(paths)
            item_type = "项目" if is_folder else "文件"
            
            # 准备详细的警告信息
            warning_text = f"您确定要永久删除这 {count} 个{item_type}吗？"
            informative_text = "<b>此操作不可撤销！</b><br><br>"
            
            # 如果是回退情况，向用户解释原因
            if delete_behavior == "trash" and not is_plugin_available:
                informative_text += "（注意：文件管理器插件未激活，无法移至回收站）"

            # 创建并显示确认对话框
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("确认永久删除")
            msg_box.setText(warning_text)
            msg_box.setInformativeText(informative_text)
            msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg_box.setDefaultButton(QMessageBox.No)
            
            reply = msg_box.exec_()
            
            if reply == QMessageBox.No:
                return
            
            # 在执行物理删除前，彻底释放可能被占用的文件句柄
            self.reset_player()
            QApplication.processEvents()

            if is_folder:
                self._delete_folders_permanently(paths)
            else:
                self._delete_files_permanently(paths)

        # 4. 无论使用何种方式，删除成功后都刷新UI
        if is_folder:
            self.populate_session_list()
        else:
            self.populate_audio_table()

        
    def on_session_item_double_clicked(self, item):
        source_name = self.source_combo.currentText(); base_dir = self.DATA_SOURCES[source_name]["path"]; folder_path = os.path.join(base_dir, item.text()); self.open_in_explorer(folder_path)
        
    def _on_volume_slider_changed(self, value):
        if self.active_player: self.active_player.setVolume(value)
        self.volume_percent_label.setText(f"{value}%")
        
    # [重命名并修改] _on_adaptive_volume_toggled -> _on_adaptive_volume_toggled_and_save
    def _on_adaptive_volume_toggled_and_save(self, checked):
        # 步骤 1: 调用原有的UI响应逻辑
        if not checked:
            self.volume_slider.setValue(100)
        # 步骤 2: 调用新的持久化方法
        self._on_persistent_setting_changed('adaptive_volume', bool(checked))
        
    def _calculate_and_set_optimal_volume(self, filepath):
        if not self.adaptive_volume_switch.isChecked() or not AUDIO_ANALYSIS_AVAILABLE: self.volume_slider.setValue(100); return
        try:
            data, sr = sf.read(filepath, dtype='float32');
            if data.ndim > 1: data = data.mean(axis=1)
            rms = np.sqrt(np.mean(data**2)); 
            if rms == 0: self.volume_slider.setValue(100); return
            required_gain = self.TARGET_RMS / rms; slider_value = required_gain * 100
            self.volume_slider.setValue(int(np.clip(slider_value, 0, 100)))
        except Exception as e: print(f"Error analyzing audio: {e}"); self.volume_slider.setValue(100)
        
    def update_playback_position(self, position):
        # [核心修改] 如果正在执行归零动画，则忽略来自播放器的实时位置更新
        if self._is_slider_resetting:
            return
        if not self.playback_slider.isSliderDown():
            self.playback_slider.setValue(position)
        
        total_duration = self.active_player.duration() if self.active_player else 0
        
        # 在播放过程中，如果总时长信息突然变得可用，也更新它
        if total_duration > self.current_displayed_duration:
            self.update_playback_duration(total_duration)
        
        self.duration_label.setText(f"{self.format_time(position)} / {self.format_time(self.current_displayed_duration)}")
        self.waveform_widget.update_playback_position(position, self.current_displayed_duration)
        
    def _set_trim_start(self):
        # [修复] 使用 active_player 并增加安全检查
        if not self.active_player: return
        self.trim_start_ms = self.active_player.position()
        self.trim_start_label.setText(f"起点: {self.format_time(self.trim_start_ms)}")
        if self.trim_end_ms is not None and self.trim_start_ms >= self.trim_end_ms:
            self.trim_end_ms = None
            self.trim_end_label.setText("终点: --:--.--")
        self.waveform_widget.set_trim_points(self.trim_start_ms, self.trim_end_ms, self.active_player.duration())
        
    def _set_trim_end(self):
        # [修复] 使用 active_player 并增加安全检查
        if not self.active_player: return
        self.trim_end_ms = self.active_player.position()
        self.trim_end_label.setText(f"终点: {self.format_time(self.trim_end_ms)}")
        if self.trim_start_ms is not None and self.trim_end_ms <= self.trim_start_ms:
            self.trim_start_ms = None
            self.trim_start_label.setText("起点: --:--.--")
        self.waveform_widget.set_trim_points(self.trim_start_ms, self.trim_end_ms, self.active_player.duration())
        
    def _clear_trim_points(self):
        self.trim_start_ms = None
        self.trim_end_ms = None
        self.trim_start_label.setText("起点: --:--.--")
        self.trim_end_label.setText("终点: --:--.--")
        # [修复] 使用 active_player 并增加安全检查
        if self.active_player:
            self.waveform_widget.set_trim_points(None, None, self.active_player.duration())
        else:
            self.waveform_widget.set_trim_points(None, None, 0)
        
    def _execute_audio_operation(self, operation_func, *args, **kwargs):
        """
        [重构] 执行一个需要音频分析库的后台操作，并处理异常。
        现在支持传递位置参数和关键字参数。
        """
        if not AUDIO_ANALYSIS_AVAILABLE:
            QMessageBox.warning(self, "功能受限", "此功能需要 numpy 和 soundfile 库。")
            return
        try:
            # 将收到的所有位置参数和关键字参数都传递给目标函数
            operation_func(*args, **kwargs)
        except Exception as e:
            QMessageBox.critical(self, "音频处理错误", f"执行操作时出错: {e}")
            
    def _preview_trim(self): self._execute_audio_operation(self._preview_trim_logic)
    def _save_trim(self): self._execute_audio_operation(self._save_trim_logic)
    def _concatenate_selected(self): self._execute_audio_operation(self._concatenate_selected_logic)
    
    def _preview_trim_logic(self):
        if self.trim_start_ms is None or self.trim_end_ms is None:
            QMessageBox.warning(self, "提示", "请先标记起点和终点。")
            return
        
        # 停止主播放器
        if self.active_player:
            self.active_player.stop()

        # 如果上一个预览播放器还在，先停止它
        if self.preview_player and self.preview_player.state() == QMediaPlayer.PlayingState:
            self.preview_player.stop()

        # ... (读取、裁切、保存临时文件的逻辑不变) ...
        data, sr = sf.read(self.audio_table_widget.item(self.audio_table_widget.currentRow(), 0).data(Qt.UserRole))
        start_sample = int(self.trim_start_ms / 1000 * sr)
        end_sample = int(self.trim_end_ms / 1000 * sr)
        trimmed_data = data[start_sample:end_sample]
        if self.temp_preview_file and os.path.exists(self.temp_preview_file): os.remove(self.temp_preview_file)
        fd, self.temp_preview_file = tempfile.mkstemp(suffix=".wav"); os.close(fd); sf.write(self.temp_preview_file, trimmed_data, sr)
        
        self.preview_player = QMediaPlayer()
        self.preview_player.setNotifyInterval(16)
        
        # [核心修改] 将 positionChanged 连接到新的专用槽函数
        self.preview_player.positionChanged.connect(self.update_preview_ui)
        # 状态变化用于预览结束后的清理
        self.preview_player.stateChanged.connect(self._on_preview_player_state_changed)
        
        self.preview_player.setMedia(QMediaContent(QUrl.fromLocalFile(self.temp_preview_file)))
        self.preview_player.play()     
        
    # [新增] 专用于预览的UI更新槽，这是正确的实现
    def update_preview_ui(self, preview_position):
        """
        专门处理预览播放器的位置更新，执行坐标转换并更新UI。
        """
        # 1. 计算绝对位置，用于更新滑块和波形图播放头
        # 这是相对于整个原始音频文件的位置
        absolute_position = self.trim_start_ms + preview_position
        
        if not self.playback_slider.isSliderDown():
            self.playback_slider.setValue(absolute_position)
        
        # 确保波形图播放头也使用绝对位置来绘制
        if self.active_player:
            self.waveform_widget.update_playback_position(absolute_position, self.active_player.duration())

        # 2. 计算并显示相对于裁切片段的时间
        # 这是为了让用户看到预览片段自身的播放进度
        preview_duration = self.preview_player.duration()
        self.duration_label.setText(f"{self.format_time(preview_position)} / {self.format_time(preview_duration)}")

    # [新增] 用于处理预览播放器状态变化的槽函数
    def _on_preview_player_state_changed(self, state):
        """当预览播放器停止或播放结束时，断开其与UI的信号连接，并恢复UI状态。"""
        if state == QMediaPlayer.StoppedState:
            if self.preview_player:
                try:
                    # [核心修改] 只断开我们挂接的信号
                    self.preview_player.positionChanged.disconnect(self.update_preview_ui)
                except TypeError:
                    pass
            
            # [核心修改] 将UI恢复到主播放器的状态
            if self.active_player:
                # 用主播放器的当前位置和总时长来重置UI
                self.update_playback_position(self.active_player.position())
            else:
                # 如果连主播放器都没有，就停在起点
                start_pos = self.trim_start_ms or 0
                self.playback_slider.setValue(start_pos)
                self.waveform_widget.update_playback_position(start_pos, self.current_displayed_duration)
                self.duration_label.setText(f"{self.format_time(start_pos)} / {self.format_time(self.current_displayed_duration)}")

    def _save_trim_logic(self, mode='keep_selection', overwrite=False):
        """
        [v2.1 - 完整无省略版]
        根据指定的模式，对音频进行裁切并保存。
        新增 overwrite 参数以支持直接覆盖原文件。
        """
        # 1. 安全检查和获取基本信息
        current_row = self.audio_table_widget.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "操作无效", "请先选择一个文件。")
            return
            
        filepath = self.audio_table_widget.item(current_row, 0).data(Qt.UserRole)
        if not filepath: return
        
        data, sr = sf.read(filepath)
        total_samples = len(data)
        
        # 2. 根据模式计算需要保留的音频片段
        final_data = None
        if mode == 'keep_selection':
            if self.trim_start_ms is None or self.trim_end_ms is None:
                QMessageBox.warning(self, "操作无效", "需要同时标记起点和终点才能'保存选中部分'。")
                return
            start_sample = int(self.trim_start_ms / 1000 * sr)
            end_sample = int(self.trim_end_ms / 1000 * sr)
            final_data = data[start_sample:end_sample]
        
        elif mode == 'trim_selection':
            if self.trim_start_ms is None or self.trim_end_ms is None:
                QMessageBox.warning(self, "操作无效", "需要同时标记起点和终点才能'裁去选中部分'。")
                return
            start_sample = int(self.trim_start_ms / 1000 * sr)
            end_sample = int(self.trim_end_ms / 1000 * sr)
            part1 = data[:start_sample]
            part2 = data[end_sample:]
            final_data = np.concatenate((part1, part2))

        elif mode == 'trim_before':
            if self.trim_start_ms is None:
                QMessageBox.warning(self, "操作无效", "需要标记起点才能'裁去起点之前'。")
                return
            start_sample = int(self.trim_start_ms / 1000 * sr)
            final_data = data[start_sample:]
            
        elif mode == 'trim_after':
            if self.trim_end_ms is None:
                QMessageBox.warning(self, "操作无效", "需要标记终点才能'裁去终点之后'。")
                return
            end_sample = int(self.trim_end_ms / 1000 * sr)
            final_data = data[:end_sample]
        
        if final_data is None:
            QMessageBox.warning(self, "操作无效", "无法根据当前标记点执行该操作。")
            return
            
        # 3. 获取新文件名并准备保存
        target_filepath = ""
        if overwrite:
            # --- [补全] 完整的覆盖确认对话框 ---
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("确认覆盖原文件")
            msg_box.setText("您确定要用处理后的版本直接覆盖原始文件吗？")

            informative_text = (
                f"<b>文件名:</b> {os.path.basename(filepath)}<br><br>"
                f"<font color='red'><b>此操作不可撤销！原始音频数据将永久丢失！</b></font>"
            )
            msg_box.setInformativeText(informative_text)
            
            msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg_box.setDefaultButton(QMessageBox.No)
            
            reply = msg_box.exec_()
            
            if reply == QMessageBox.No:
                self.status_label.setText("覆盖操作已取消。")
                QTimer.singleShot(2000, lambda: self.status_label.setText("准备就绪"))
                return
            
            target_filepath = filepath
            # --- 补全结束 ---
        else:
            # --- [补全] 完整的“另存为”对话框 ---
            base, ext = os.path.splitext(os.path.basename(filepath))
            suffix_map = {
                'keep_selection': '_selected',
                'trim_selection': '_trimmed',
                'trim_before': '_trimmed_start',
                'trim_after': '_trimmed_end'
            }
            suggested_name = f"{base}{suffix_map.get(mode, '_edited')}"
            
            new_name, ok = QInputDialog.getText(self, "保存裁切文件", "请输入新文件名:", QLineEdit.Normal, suggested_name)
            
            if not (ok and new_name and new_name.strip()):
                return

            new_filepath = os.path.join(os.path.dirname(filepath), new_name.strip() + ext)
            if os.path.exists(new_filepath):
                QMessageBox.warning(self, "文件已存在", f"文件 '{os.path.basename(new_filepath)}' 已存在，请使用其他名称。")
                return
            target_filepath = new_filepath
            # --- 补全结束 ---

        # 4. 执行文件写入
        if not target_filepath: return
        
        try:
            self.reset_player()
            QApplication.processEvents()
            
            sf.write(target_filepath, final_data, sr)

            if overwrite:
                QMessageBox.information(self, "成功", f"原文件已成功覆盖！")
                self.waveform_widget.set_waveform_data(target_filepath)
            else:
                QMessageBox.information(self, "成功", f"文件已保存为:\n{target_filepath}")
            
            self.populate_audio_table()
            
            # 调用自动选中功能
            if not overwrite:
                self._find_and_select_file(target_filepath)

        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"写入文件时发生错误:\n{e}")
            
    def _add_selected_to_staging(self):
        selected_rows = sorted(list(set(item.row() for item in self.audio_table_widget.selectedItems())))
        added_count = 0
        for row in selected_rows:
            filepath = self.audio_table_widget.item(row, 0).data(Qt.UserRole)
            if filepath not in self.staged_files:
                display_name = f"{os.path.basename(os.path.dirname(filepath))} / {os.path.basename(filepath)}"
                self.staged_files[filepath] = display_name
                added_count += 1
        self._update_staging_list_widget()
        
        # [修改] 使用本地状态标签
        status_text = f"已添加 {added_count} 个新文件到暂存区。"
        self.status_label.setText(status_text)
        QTimer.singleShot(3000, lambda: self.status_label.setText("准备就绪"))

    # [新增] 更新暂存区列表UI
    def _update_staging_list_widget(self):
        items_text = [self.staged_files[path] for path in sorted(self.staged_files.keys())]
        self.staging_list_widget.addItemsWithAnimation(items_text)

    # [新增] 清空暂存区
    def _clear_staging_area(self):
        self.staged_files.clear()
        self.staging_list_widget.clear()
        # [修改] 使用本地状态标签
        self.status_label.setText("暂存区已清空。")
        QTimer.singleShot(2000, lambda: self.status_label.setText("准备就绪"))

    # [重构] 这是新的连接逻辑，替代 _concatenate_selected_logic
    def _concatenate_staged_files(self):
        if len(self.staged_files) < 2:
            QMessageBox.information(self, "提示", "请至少向暂存区添加两个音频文件以进行连接。")
            return

        initial_filepaths = list(self.staged_files.keys())
        
        # 检查文件格式是否一致 (与之前逻辑相同)
        try:
            first_file_info = sf.info(initial_filepaths[0]); sr, channels = first_file_info.samplerate, first_file_info.channels
            for fp in initial_filepaths[1:]:
                info = sf.info(fp)
                if info.samplerate != sr or info.channels != channels:
                    QMessageBox.critical(self, "无法连接", f"文件格式不匹配。所有文件的采样率和通道数必须相同。"); return
        except Exception as e:
            QMessageBox.critical(self, "文件信息错误", f"无法读取文件信息: {e}"); return

        # 使用 ReorderDialog 让用户排序和命名
        dialog = ReorderDialog(initial_filepaths, self, self.icon_manager)
        if dialog.exec_() == QDialog.Accepted:
            reordered_paths, new_name = dialog.get_reordered_paths_and_name()
            if not new_name: QMessageBox.warning(self, "输入无效", "请输入有效的新文件名。"); return
            
            # [修改] 让用户选择保存位置
            ext = os.path.splitext(reordered_paths[0])[1]
            save_path, _ = QFileDialog.getSaveFileName(self, "保存连接后的音频", f"{new_name}{ext}", f"音频文件 (*{ext})")
            
            if not save_path: return

            try:
                all_data = [sf.read(fp)[0] for fp in reordered_paths]; concatenated_data = np.concatenate(all_data)
                sf.write(save_path, concatenated_data, sr)
                QMessageBox.information(self, "成功", f"文件已连接并保存至:\n{save_path}")
                # 连接成功后可以选择清空暂存区
                reply = QMessageBox.question(self, "操作完成", "连接成功！是否要清空暂存区？", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if reply == QMessageBox.Yes:
                    self._clear_staging_area()
            except Exception as e:
                QMessageBox.critical(self, "连接失败", f"保存连接文件时出错: {e}")        

    def open_file_context_menu(self, position):
        """
        [v2.3 - 修复重复执行Bug]
        构建文件列表的右键上下文菜单。
        修复了因重复定义 selected_filepaths 导致外部工具被多次调用的问题。
        """
        menu = QMenu(self.audio_table_widget)
        selected_items = self.audio_table_widget.selectedItems()

        if selected_items:
            # --- 第一次，也是唯一一次正确的定义 ---
            is_single_selection = len(set(item.row() for item in selected_items)) == 1
            selected_rows_count = len(set(item.row() for item in selected_items))
            selected_filepaths = sorted(list(set(
                self.audio_table_widget.item(i.row(), 0).data(Qt.UserRole) for i in selected_items
            )))

            # --- 第一组：核心播放与分析 ---
            play_action = menu.addAction(self.icon_manager.get_icon("play_audio"), "试听 / 暂停")
            play_action.triggered.connect(self.toggle_playback)
            play_action.setEnabled(is_single_selection)

            analysis_module_available = hasattr(self.parent_window, 'audio_analysis_page') and self.parent_window.audio_analysis_page is not None
            if analysis_module_available:
                if is_single_selection:
                    analyze_single_action = menu.addAction(self.icon_manager.get_icon("analyze"), "在音频分析中打开")
                    analyze_single_action.triggered.connect(lambda: self.send_to_audio_analysis(selected_filepaths[0]))
                else:
                    analyze_batch_action = menu.addAction(self.icon_manager.get_icon("analyze_dark"), f"发送 {selected_rows_count} 个文件到批量分析")
                    analyze_batch_action.triggered.connect(lambda: self.send_to_batch_analysis(selected_filepaths))

            menu.addSeparator()

            # --- 第二组：文件处理与修改 ---
            # [核心修复] 删除下面这两行多余且错误的重定义！
            # selected_rows_count = len(set(item.row() for item in selected_items))  <-- 已删除
            # selected_filepaths = [self.audio_table_widget.item(item.row(), 0).data(Qt.UserRole) for item in selected_items] <-- 已删除

            rename_action = menu.addAction(self.icon_manager.get_icon("rename"), "重命名")
            rename_action.triggered.connect(lambda: self.rename_selected_file(selected_items[0].row()))
            rename_action.setEnabled(is_single_selection)

            if hasattr(self, 'batch_processor_plugin_active'):
                processor_menu = menu.addMenu(self.icon_manager.get_icon("submit"), "批量处理")
                open_dialog_action = processor_menu.addAction(self.icon_manager.get_icon("options"), f"高级处理 ({selected_rows_count} 个文件)...")
                open_dialog_action.triggered.connect(self._send_to_batch_processor)
                quick_normalize_action = processor_menu.addAction(self.icon_manager.get_icon("wand"), "一键标准化")
                quick_normalize_action.triggered.connect(self._run_quick_normalize)

            delete_action = menu.addAction(self.icon_manager.get_icon("delete"), f"删除选中的 {selected_rows_count} 个文件")
            delete_action.triggered.connect(self.delete_selected_files)
        
            menu.addSeparator()

            # --- 第三组：系统与外部交互 ---
            if hasattr(self, 'external_launcher_plugin_active'):
                # 现在这里接收到的 selected_filepaths 是正确的、去重后的列表
                launcher_plugin = self.external_launcher_plugin_active
                launcher_plugin.populate_menu(menu, selected_filepaths)

            add_to_staging_action = menu.addAction(self.icon_manager.get_icon("add_row"), f"将 {selected_rows_count} 个文件添加到暂存区")
            add_to_staging_action.triggered.connect(self._add_selected_to_staging)
        
            open_folder_action = menu.addAction(self.icon_manager.get_icon("show_in_explorer"), "在文件浏览器中显示")
            if is_single_selection:
                filepath = selected_filepaths[0] # 直接使用去重后的列表
                folder_path = os.path.dirname(filepath)
                file_name = os.path.basename(filepath)
                open_folder_action.triggered.connect(lambda: self.open_in_explorer(folder_path, select_file=file_name))
            else:
                open_folder_action.setEnabled(False)

        # --- 无论是否选中，始终显示刷新和设置 ---
        if menu.actions():
            menu.addSeparator()

        refresh_action = menu.addAction(self.icon_manager.get_icon("refresh"), "刷新文件列表")
        refresh_action.triggered.connect(self.populate_audio_table)
        
        shortcut_menu = menu.addMenu(self.icon_manager.get_icon("draw"), "设置快捷按钮")
        shortcut_actions = {
            'play': shortcut_menu.addAction(self.icon_manager.get_icon("play_audio"), "试听 / 暂停"),
            'analyze': shortcut_menu.addAction(self.icon_manager.get_icon("analyze"), "在音频分析中打开"),
            'stage': shortcut_menu.addAction(self.icon_manager.get_icon("add_row"), "添加到暂存区"),
            'rename': shortcut_menu.addAction(self.icon_manager.get_icon("rename"), "重命名"),
            'explorer': shortcut_menu.addAction(self.icon_manager.get_icon("show_in_explorer"), "在文件浏览器中显示"),
            'delete': shortcut_menu.addAction(self.icon_manager.get_icon("delete"), "删除 (默认)"),
        }
        for action_key, q_action in shortcut_actions.items():
            q_action.setCheckable(True)
            if self.shortcut_button_action == action_key:
                q_action.setChecked(True)
            q_action.triggered.connect(lambda checked, key=action_key: self.set_shortcut_button_action(key))

        menu.exec_(self.audio_table_widget.mapToGlobal(position))

    def send_to_audio_analysis(self, filepath):
        """
        [v2.0 - 模式切换修复版]
        调用主窗口的公共API来切换到音频分析模块并加载单个文件。
        此版本增加了在加载前强制切换到“单个文件”模式的机制，
        确保无论用户之前处于何种模式，加载行为都正确无误。
        """
        # 1. 安全检查，确保音频分析模块已加载 (保持不变)
        if not (hasattr(self.parent_window, 'go_to_audio_analysis') and callable(self.parent_window.go_to_audio_analysis)):
            QMessageBox.critical(self, "功能缺失", "主程序缺少必要的跳转功能 (go_to_audio_analysis)。")
            return
            
        # 2. 调用主窗口的导航 API，它会负责切换到“音频分析”主标签页
        #    并返回 audio_analysis_page 实例
        audio_analysis_page = self.parent_window.go_to_audio_analysis(filepath)

        # 3. [核心修复] 在加载文件前，检查并设置正确的模式
        if audio_analysis_page:
            # 检查 mode_toggle 是否存在并且当前处于批量模式 (checked)
            if hasattr(audio_analysis_page, 'mode_toggle') and audio_analysis_page.mode_toggle.isChecked():
                # 如果是，则以编程方式将其切换回单个文件模式
                audio_analysis_page.mode_toggle.setChecked(False)
                # 给予UI一点时间来处理模式切换的事件
                QApplication.processEvents()
        
        # 4. go_to_audio_analysis 内部已经调用了 load_audio_file,
        #    但为了确保在模式切换后逻辑依然稳健，我们可以在 go_to_audio_analysis 中调整。
        #    或者，如果 go_to_audio_analysis 只负责导航，我们在这里加载。
        #    根据 Canary.py 的实现，go_to_audio_analysis 会返回页面实例并加载文件。
        #    我们的任务是确保在它加载之前，模式是正确的。
        #    为了更稳健，我们在这里再调用一次 load_audio_file 确保覆盖。
        #    （更好的做法是修改 go_to_audio_analysis，但为了最小化改动，我们这样做）
        if audio_analysis_page and hasattr(audio_analysis_page, 'load_audio_file'):
             audio_analysis_page.load_audio_file(filepath)

    def delete_selected_files(self):
        """删除所有在表格中被选中的文件。"""
        selected_filepaths = sorted(list(set(
            self.audio_table_widget.item(i.row(), 0).data(Qt.UserRole) for i in self.audio_table_widget.selectedItems()
        )))
        if selected_filepaths:
            self._request_delete_items(selected_filepaths, is_folder=False)

    def closeEvent(self, event):
        self._clear_player_cache();
        if self.temp_preview_file and os.path.exists(self.temp_preview_file):
            try: os.remove(self.temp_preview_file)
            except: pass
        super().closeEvent(event)
        
    def update_icons(self):
        # [核心修复] 使用 try...except 块来防御性地处理可能已被删除的播放器对象
        try:
            # 尝试获取播放器状态。如果 self.active_player 是一个 "僵尸对象", 
            # 访问 .state() 会在此处触发 RuntimeError。
            state = self.active_player.state() if self.active_player else QMediaPlayer.StoppedState
        except RuntimeError:
            # 捕获到错误，意味着 C++ 对象已消失。
            # 1. 将状态安全地设置为停止状态。
            state = QMediaPlayer.StoppedState
            # 2. 清理掉无效的僵尸引用，防止后续代码再次出错。
            self.active_player = None
        
        # 现在使用安全获取到的 state 来更新UI
        self.on_player_state_changed(state)
        
        # --- 后续的图标更新代码保持不变 ---
        for row in range(self.audio_table_widget.rowCount()):
            btn = self.audio_table_widget.cellWidget(row, 3)
            if isinstance(btn, QPushButton): 
                # [小优化] 直接从快捷按钮的动作获取图标，而不是写死
                action_key = self.shortcut_button_action
                icon_name_map = {
                    'delete': 'delete', 'play': 'play_audio',
                    'analyze': 'analyze', 'stage': 'add_row',
                    'rename': 'rename', 'explorer': 'show_in_explorer'
                }
                icon = self.icon_manager.get_icon(icon_name_map.get(action_key, 'delete'))
                btn.setIcon(icon)

        self.set_start_btn.setIcon(self.icon_manager.get_icon("next")); self.set_end_btn.setIcon(self.icon_manager.get_icon("prev")); self.clear_trim_btn.setIcon(self.icon_manager.get_icon("clear_marker")); self.preview_trim_btn.setIcon(self.icon_manager.get_icon("preview")); self.save_trim_btn.setIcon(self.icon_manager.get_icon("save_2"))
        self.process_staged_btn.setIcon(self.icon_manager.get_icon("submit"))
        self.clear_staged_btn.setIcon(self.icon_manager.get_icon("clear"))
        
        if self.sort_order_btn.isChecked():
            self.sort_order_btn.setIcon(self.icon_manager.get_icon("sort_desc"))
        else:
            self.sort_order_btn.setIcon(self.icon_manager.get_icon("sort_asc"))

    def apply_layout_settings(self):
        config = self.parent_window.config; ui_settings = config.get("ui_settings", {}); width = ui_settings.get("editor_sidebar_width", 350); self.left_panel.setFixedWidth(width)
        
    # [重构] load_and_refresh 现在负责合并数据源并填充下拉框
    def load_and_refresh(self):
        self.config = self.parent_window.config
        module_states = self.config.get("module_states", {}).get("audio_manager", {})
        
        # 恢复所有持久化控件的状态
        self.shortcut_button_action = module_states.get('shortcut_action', 'delete')
        self.adaptive_volume_switch.setChecked(module_states.get('adaptive_volume', True))

        self.apply_layout_settings()
        self.update_icons()

        # 加载自定义源
        self.custom_data_sources = self.config.get("file_settings", {}).get("custom_data_sources", [])
        self._build_global_file_index()

        # 填充数据源下拉框
        self.source_combo.blockSignals(True)
        current_text = self.source_combo.currentText() # 记录之前的选择
        self.source_combo.clear()

        # 添加内置源和自定义源
        for name in self.DATA_SOURCES.keys():
            self.source_combo.addItem(name)
        if self.custom_data_sources:
            self.source_combo.insertSeparator(self.source_combo.count())
            for source in self.custom_data_sources:
                self.source_combo.addItem(self.icon_manager.get_icon("folder"), source['name'])
        
        # 恢复之前的选择，或根据设置加载上次的源
        load_last = module_states.get("load_last_source", True)
        last_source = module_states.get("last_source")
        
        if load_last and last_source:
            index = self.source_combo.findText(last_source)
            if index != -1:
                self.source_combo.setCurrentIndex(index)
        else: # 如果不加载上次的，就恢复刷新前的选择
            index = self.source_combo.findText(current_text)
            if index != -1:
                 self.source_combo.setCurrentIndex(index)

        self.source_combo.blockSignals(False)

        # 触发一次列表填充
        self.on_source_changed(self.source_combo.currentText())

    # [新增] on_source_changed 槽函数，替代 populate_session_list
    def on_source_changed(self, text):
        module_states = self.config.get("module_states", {}).get("audio_manager", {})
        if module_states.get("load_last_source", True):
            self._on_persistent_setting_changed("last_source", text)
        
        self.populate_session_list()

    # [重构] populate_session_list 现在只负责填充列表，数据源由 on_source_changed 决定
    def populate_session_list(self):
        """
        [v1.2 - Reselection & Association Icon] 填充项目列表。
        - 检查每个文件夹的词表关联状态，并显示相应的图标。
        - 在刷新前后保持用户的当前选择。
        """
        self.status_label.setText("正在刷新项目列表...")
        QApplication.processEvents()

        # 步骤1: 在清空列表前，记录当前选中的项目文本
        current_item = self.session_list_widget.currentItem()
        text_to_reselect = current_item.text() if current_item else None
        
        # 获取当前数据源信息
        source_name = self.source_combo.currentText()
        source_info = self.DATA_SOURCES.get(source_name)
        is_custom = False

        if not source_info:
            for custom_source in self.custom_data_sources:
                if custom_source['name'] == source_name:
                    source_info = {"path": custom_source['path'], "filter": lambda d, p: os.path.isdir(os.path.join(p, d))}
                    is_custom = True
                    break
        
        if not source_info:
            self.session_list_widget.clear()
            self.audio_table_widget.setRowCount(0)
            self.table_label.setText("无效的数据源")
            return

        # 重置会话状态
        self.session_active = False
        self.reset_player()
        
        base_path = source_info["path"]
        
        if not os.path.exists(base_path):
            self.session_list_widget.clear()
            if is_custom:
                error_item_data = {'type': 'item', 'text': f"错误: 路径不存在\n{base_path}", 'icon': self.icon_manager.get_icon("error")}
                self.session_list_widget.setHierarchicalData([error_item_data])
            else:
                os.makedirs(base_path, exist_ok=True)
            return

        try:
            items_to_display = []
            
            # 扫描并构建包含图标信息的数据列表
            all_sessions = sorted([d for d in os.listdir(base_path) if source_info["filter"](d, base_path)], 
                                  key=lambda s: os.path.getmtime(os.path.join(base_path, s)), reverse=True)

            for session_name in all_sessions:
                folder_path = os.path.join(base_path, session_name)
                
                # 调用辅助方法检查关联状态
                is_associated = self._is_folder_associated(folder_path)
                
                # 根据状态选择图标
                icon = self.icon_manager.get_icon("concatenate") if is_associated else self.icon_manager.get_icon("music_record")
                
                # 构建 AnimatedListWidget 所需的数据结构
                item_data = {
                    'type': 'item', # 在此列表中，每个文件夹都是一个可点击的 'item'
                    'text': session_name,
                    'icon': icon,
                    'tooltip': f"项目文件夹: {session_name}" + (" (已关联词表)" if is_associated else ""),
                    'data': {'path': folder_path}
                }
                items_to_display.append(item_data)

            # 使用 setHierarchicalData API 来填充列表
            self.session_list_widget.setHierarchicalData(items_to_display)

            # 步骤2: 在列表填充后，恢复之前的选择
            item_to_select = None
            if text_to_reselect:
                # 优先恢复刷新前的选择
                items = self.session_list_widget.findItems(text_to_reselect, Qt.MatchFixedString)
                if items:
                    item_to_select = items[0]
            
            # 如果没有之前的选择，则回退到“加载上次项目”的逻辑
            if not item_to_select:
                module_states = self.config.get("module_states", {}).get("audio_manager", {})
                load_last = module_states.get("load_last_source", True)
                last_project = module_states.get("last_project")
                if load_last and last_project:
                    items = self.session_list_widget.findItems(last_project, Qt.MatchFixedString)
                    if items:
                        item_to_select = items[0]

            if item_to_select:
                self.session_list_widget.setCurrentItem(item_to_select)
            
            self.status_label.setText("项目列表已刷新。")
            QTimer.singleShot(2000, lambda: self.status_label.setText("准备就绪"))
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载项目列表失败: {e}")
            self.status_label.setText("刷新失败！")

    def _show_staging_process_menu(self):
        """
        [v2.0 - 批量分析集成版]
        当点击“处理暂存区”按钮时，构建并显示一个包含所有可用操作的菜单。
        """
        if not self.staged_files:
            QMessageBox.information(self, "暂存区为空", "请先将文件添加到暂存区再进行处理。")
            return

        menu = QMenu(self)
        staged_filepaths = list(self.staged_files.keys())

        # 1. 添加“连接”操作 (保持不变)
        connect_action = menu.addAction(self.icon_manager.get_icon("concatenate"), "连接所有暂存文件...")
        connect_action.triggered.connect(self._concatenate_staged_files)
    
        menu.addSeparator()

        # --- [核心修改] 新增“发送到批量分析”操作 ---
        # 检查音频分析模块是否可用
        analysis_module_available = hasattr(self.parent_window, 'audio_analysis_page') and self.parent_window.audio_analysis_page is not None
        if analysis_module_available:
            send_to_analysis_action = menu.addAction(self.icon_manager.get_icon("analyze_dark"), "发送到批量分析...")
            send_to_analysis_action.triggered.connect(self._send_staged_to_batch_analysis)
        # --- 修改结束 ---

        # 2. 添加“批量处理”插件操作 (保持不变)
        if hasattr(self, 'batch_processor_plugin_active'):
            process_action = menu.addAction(self.icon_manager.get_icon("submit"), "用批量处理器打开...")
            process_action.triggered.connect(self._send_staged_to_batch_processor)

        # 3. 添加“用外部工具打开”插件操作 (保持不变)
        if hasattr(self, 'external_launcher_plugin_active'):
            launcher_plugin = self.external_launcher_plugin_active
            launcher_plugin.populate_menu(menu, staged_filepaths)

        menu.exec_(QCursor.pos())


    def _send_staged_to_batch_analysis(self):
        """
        [新增] 核心功能：将暂存区的所有文件发送到音频分析模块的批量模式。
        """
        # 1. 检查暂存区是否为空
        if not self.staged_files:
            QMessageBox.information(self, "暂存区为空", "暂存区中没有文件可以发送。")
            return
        
        filepaths = list(self.staged_files.keys())
    
        # 2. 安全检查，确保音频分析模块已加载
        if not hasattr(self.parent_window, 'audio_analysis_page'):
            QMessageBox.warning(self, "功能缺失", "音频分析模块未成功加载。")
            return
        
        audio_analysis_page = self.parent_window.audio_analysis_page
    
        # 3. 调用主窗口的导航API，切换到“音频分析”模块
        target_page = self.parent_window._navigate_to_tab("资源管理", "音频分析")
        if target_page:
            # 4. 强制切换到批量分析模式 (通过操作ToggleSwitch)
            if hasattr(target_page, 'mode_toggle'):
                target_page.mode_toggle.setChecked(True) # True 表示批量模式
        
            # 5. 调用批量面板的公共API来加载文件
            if hasattr(target_page, 'batch_analysis_panel') and \
               hasattr(target_page.batch_analysis_panel, 'load_files_from_external'):
                target_page.batch_analysis_panel.load_files_from_external(filepaths)
            else:
                QMessageBox.warning(self, "接口错误", "无法找到音频分析模块的批量加载接口。")
        else:
            QMessageBox.warning(self, "导航失败", "无法切换到音频分析模块。")

    # [新增] 将暂存区文件发送到批量处理插件的辅助方法
    def _send_staged_to_batch_processor(self):
        """
        收集暂存区的所有文件路径，并通过插件管理器执行批量处理插件。
        """
        if not self.staged_files: return
        
        filepaths = list(self.staged_files.keys())
        
        # 获取插件实例并执行
        processor_plugin = getattr(self, 'batch_processor_plugin_active', None)
        if processor_plugin:
            processor_plugin.execute(filepaths=filepaths)

    # [新增] 添加自定义源的逻辑
    def _manage_custom_sources(self):
        # 记录下在打开对话框之前，用户实际选择的数据源是什么
        previous_source_name = self.source_combo.currentText()
        if previous_source_name == "< 添加/管理自定义源... >":
            # 如果用户直接点击的管理项，我们没有一个“之前”的源，就默认回到第一个
            previous_source_name = self.source_combo.itemText(0)

        dialog = ManageSourcesDialog(self.custom_data_sources, self, self.icon_manager)
    
        if dialog.exec_() == QDialog.Accepted:
            # [核心修正] 这里的 sources 已经是从对话框中验证和处理过的
            updated_sources = dialog.get_sources() 
            if updated_sources is None: # 如果验证失败（比如有重名），则不进行任何操作
                 return

            # 只有在数据源实际发生变化时才保存和刷新
            if updated_sources != self.custom_data_sources:
                self.custom_data_sources = updated_sources
            
                # 直接修改主配置字典
                file_settings = self.config.setdefault("file_settings", {})
                file_settings["custom_data_sources"] = self.custom_data_sources
                
                # [核心修正] 直接调用全局保存方法，而不是错误的API
                if hasattr(self.parent_window, 'save_config'):
                    self.parent_window.save_config()
            
                # [核心修正] 在刷新前，先将下拉框重置到一个安全的位置
                self.source_combo.blockSignals(True)
                # 找到之前的数据源并选中它，如果找不到了就回到第一个
                index_to_restore = self.source_combo.findText(previous_source_name)
                self.source_combo.setCurrentIndex(index_to_restore if index_to_restore != -1 else 0)
                self.source_combo.blockSignals(False)
                self._build_global_file_index()
                # 现在可以安全地刷新了
                self.load_and_refresh()

        else: # 如果用户点击了 "Cancel" 或通过 'X' 关闭
            # 同样需要恢复到之前的选择，以防UI停留在管理项上
            self.source_combo.blockSignals(True)
            index = self.source_combo.findText(previous_source_name)
            if index != -1:
                self.source_combo.setCurrentIndex(index)
            self.source_combo.blockSignals(False)

    # [新增] 右键菜单逻辑
    def open_source_context_menu(self, position):
        index = self.source_combo.currentIndex()
        source_name = self.source_combo.currentText()

        # 检查是否是自定义源
        is_custom = any(source['name'] == source_name for source in self.custom_data_sources)
        
        if not is_custom:
            return

        menu = QMenu(self)
        remove_action = menu.addAction(self.icon_manager.get_icon("delete"), "移除此自定义源")
        action = menu.exec_(self.source_combo.mapToGlobal(position))

        if action == remove_action:
            reply = QMessageBox.question(self, "确认移除", f"您确定要移除自定义数据源 '{source_name}' 吗？\n这只会从列表中移除快捷方式，不会删除实际的文件夹。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.custom_data_sources = [s for s in self.custom_data_sources if s['name'] != source_name]
                file_settings = self.config.setdefault("file_settings", {})
                file_settings["custom_data_sources"] = self.custom_data_sources
                self.parent_window.update_and_save_module_state("file_settings", file_settings)
                self.load_and_refresh()

    def _setup_shortcut_button(self, row, filepath):
        """
        为指定行创建、设置并连接快捷操作按钮。
        
        Args:
            row (int): 要放置按钮的行号。
            filepath (str): 该行对应的文件完整路径。
        """
        shortcut_btn = QPushButton()
        shortcut_btn.setCursor(Qt.PointingHandCursor)
        shortcut_btn.setObjectName("LinkButton")

        action = self.shortcut_button_action

        # 根据当前设置的快捷操作，配置按钮的图标、提示和点击事件
        if action == 'delete':
            shortcut_btn.setIcon(self.icon_manager.get_icon("delete"))
            shortcut_btn.setToolTip("快捷操作：删除此文件")
            # 使用 lambda 确保传递的是当前的 filepath
            shortcut_btn.clicked.connect(lambda _, r=row: self._delete_single_item_from_shortcut(r))

        elif action == 'play':
            shortcut_btn.setIcon(self.icon_manager.get_icon("play_audio"))
            shortcut_btn.setToolTip("快捷操作：试听/暂停此文件")
            # 使用 lambda 确保传递的是当前的 row
            shortcut_btn.clicked.connect(lambda _, r=row: self._on_shortcut_play_button_clicked(r))

        elif action == 'analyze':
            shortcut_btn.setIcon(self.icon_manager.get_icon("analyze"))
            shortcut_btn.setToolTip("快捷操作：在音频分析中打开")
            shortcut_btn.clicked.connect(lambda _, f=filepath: self.parent_window.go_to_audio_analysis(f))
        
        elif action == 'stage':
            shortcut_btn.setIcon(self.icon_manager.get_icon("add_row"))
            shortcut_btn.setToolTip("快捷操作：将此文件添加到暂存区")
            shortcut_btn.clicked.connect(lambda _, r=row: self._add_single_to_staging(r))

        elif action == 'rename':
            shortcut_btn.setIcon(self.icon_manager.get_icon("rename"))
            shortcut_btn.setToolTip("快捷操作：重命名此文件")
            shortcut_btn.clicked.connect(lambda _, r=row: self.rename_selected_file(r))

        elif action == 'explorer':
            shortcut_btn.setIcon(self.icon_manager.get_icon("show_in_explorer"))
            shortcut_btn.setToolTip("快捷操作：在文件浏览器中显示")
            shortcut_btn.clicked.connect(lambda _, f=filepath: self.open_in_explorer(os.path.dirname(f), select_file=os.path.basename(f)))
        
        # 将配置好的按钮设置到表格的指定单元格中
        self.audio_table_widget.setCellWidget(row, 3, shortcut_btn)
        
    def populate_audio_table(self):
        """
        [v3.1 - Reselection] 现在只负责加载和显示当前文件夹的内容，
        并在刷新后恢复之前的选择。
        """
        # [核心修改] 步骤1: 在清空前记录当前选中的文件路径
        current_row = self.audio_table_widget.currentRow()
        path_to_reselect = None
        if current_row != -1:
            item = self.audio_table_widget.item(current_row, 0)
            if item:
                path_to_reselect = item.data(Qt.UserRole)

        self.status_label.setText("正在刷新文件列表...")
        QApplication.processEvents()
        self.reset_player()
        self.waveform_widget.clear()
        self.audio_table_widget.setRowCount(0)
        self.all_files_data.clear()
        
        self.audio_table_widget.setHorizontalHeaderLabels(["文件名", "文件大小", "修改日期", ""])

        if not self.current_session_path:
            self.table_label.setText("请从左侧选择一个项目以查看文件")
            return
        
        self.table_label.setText(f"项目: {os.path.basename(self.current_session_path)}")

        try:
            # ... (加载文件的逻辑保持不变) ...
            supported_exts = ('.wav', '.mp3', '.flac', '.ogg')
            for filename in os.listdir(self.current_session_path):
                if filename.lower().endswith(supported_exts):
                    filepath = os.path.join(self.current_session_path, filename)
                    try:
                        stat = os.stat(filepath)
                        self.all_files_data.append({
                            'path': filepath,
                            'name': filename,
                            'size': stat.st_size,
                            'mtime': stat.st_mtime
                        })
                    except OSError:
                        continue
            
            self.status_label.setText("文件列表已刷新。")
            QTimer.singleShot(2000, lambda: self.status_label.setText("准备就绪"))            
            self.filter_and_render_files()

            # [核心修改] 步骤2: 在表格渲染后，尝试恢复选择
            if path_to_reselect:
                for row in range(self.audio_table_widget.rowCount()):
                    item = self.audio_table_widget.item(row, 0)
                    if item and item.data(Qt.UserRole) == path_to_reselect:
                        self.audio_table_widget.setCurrentCell(row, 0)
                        break # 找到后即停止循环

        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载音频文件列表失败: {e}")
            self.status_label.setText("刷新失败！")
    def on_sort_order_changed(self, checked):
        """
        [新增] 当排序顺序按钮被点击时调用。
        """
        # 仅仅是更新UI和重新触发排序渲染即可
        self.update_icons() # 更新按钮图标（升序/降序）
        self.filter_and_render_files() # 使用新的顺序重新排序和渲染列表

    def on_sort_changed(self):
        """
        [v1.2 - Fix] 当排序方式变化时调用。
        修复了切换到“按词表顺序”时未重置升/降序状态的BUG。
        """
        sort_text = self.sort_combo.currentText()
        self.sort_order_btn.blockSignals(True)
        
        if "名称" in sort_text:
            self.current_sort_key = 'name'
            self.sort_order_btn.setChecked(False) 
        elif "大小" in sort_text:
            self.current_sort_key = 'size'
            self.sort_order_btn.setChecked(True)
        elif "日期" in sort_text:
            self.current_sort_key = 'mtime'
            self.sort_order_btn.setChecked(True)
        elif "词表顺序" in sort_text:
            self.current_sort_key = 'wordlist'
            # [核心修复] 切换到词表排序时，总是默认设置为升序 (A->Z)。
            self.sort_order_btn.setChecked(False)
            
        self.sort_order_btn.blockSignals(False)
        self.sort_order_btn.setEnabled(True)

        self.filter_and_render_files()

    # [重构 v2.0] 智能搜索评分函数，替换旧的 _fuzzy_match
    def _calculate_search_score(self, search_term, file_info):
        """
        根据一系列直观的规则计算文件的搜索匹配分数。
        分数越高，相关性越强。不匹配则返回 0。
        """
        search_term = search_term.lower()
        filename = file_info['name'].lower()
        filename_base, _ = os.path.splitext(filename)

        # 规则 1: 完全匹配 (最高优先级)
        if search_term == filename_base:
            return 100000

        # 规则 2: 前缀匹配 (次高优先级)
        if filename.startswith(search_term):
            # 分数 = 基础分 + 匹配长度奖励 (越长越具体)
            return 50000 + len(search_term)

        # 规则 3: 连续字符串包含 (中等优先级)
        try:
            # find() 返回第一次出现的位置，位置越靠前，分数越高
            index = filename.find(search_term)
            if index != -1:
                return 10000 - index
        except:
            pass # 忽略可能发生的异常

        # 规则 4: 多词全包含 (较低优先级)
        search_words = search_term.split()
        if len(search_words) > 1:
            if all(word in filename for word in search_words):
                # 基础分 + 单词数奖励 + 总长度奖励
                return 1000 + len(search_words) * 100 + len(search_term)

        # 如果以上规则都不满足，则认为不匹配
        return 0
    # [新增 v3.3] 启动滑块平滑归零动画
    def _start_slider_reset_animation(self):
        """
        创建一个属性动画，将播放进度条平滑地从当前位置移动到0。
        """
        # 如果已有动画正在运行，则停止它
        if hasattr(self, '_slider_reset_anim') and self._slider_reset_anim.state() == QPropertyAnimation.Running:
            self._slider_reset_anim.stop()

        # 设置状态标志，告知其他部分我们正在执行归零动画
        self._is_slider_resetting = True
        
        self._slider_reset_anim = QPropertyAnimation(self.playback_slider, b"value", self)
        self._slider_reset_anim.setDuration(200)  # 动画时长，单位毫秒
        self._slider_reset_anim.setEasingCurve(QEasingCurve.OutCubic) # 缓出效果，更自然
        
        # 动画从滑块的当前值（即音频末尾）开始
        self._slider_reset_anim.setStartValue(self.playback_slider.value())
        # 动画在0结束
        self._slider_reset_anim.setEndValue(0)
        
        # 将动画的完成信号连接到状态重置函数
        self._slider_reset_anim.finished.connect(self._on_slider_reset_finished)
        
        self._slider_reset_anim.start()

    # [新增 v3.3] 归零动画完成后的回调
    def _on_slider_reset_finished(self):
        """当归零动画完成时，重置状态标志。"""
        self._is_slider_resetting = False
        # 为确保最终UI的精确性，手动再更新一次
        self.update_playback_position(0)

    # [重构 v3.2] 核心搜索与渲染方法，使用新的智能评分系统
    def filter_and_render_files(self):
        """
        [v3.4 - Correct Wordlist Sort]
        修复了词表降序排序的逻辑错误。
        """
        search_term = self.search_input.text().strip()

        if search_term:
            # --- 模式1: 全局搜索 (逻辑不变) ---
            # ... (此部分代码无需改动) ...
            self.is_global_search_active = True
            search_results = []
            for file_info in self.global_file_index:
                base_score = self._calculate_search_score(search_term, file_info)
                if base_score > 0:
                    result_item = file_info.copy()
                    is_in_context = (self.current_session_path is not None and 
                                     file_info['project_name'] == os.path.basename(self.current_session_path) and
                                     file_info['source_name'] == self.source_combo.currentText())
                    context_bonus = 500000 if is_in_context else 0
                    result_item['score'] = base_score + context_bonus
                    search_results.append(result_item)
            sorted_results = sorted(search_results, key=lambda x: x['score'], reverse=True)
            self.render_global_search_results(sorted_results)

        elif self.current_sort_key == 'wordlist' and self.current_session_path:
            # --- 模式2: 按词表顺序排序 ---
            self.is_global_search_active = False
            word_order = self._get_word_order()

            if word_order:
                # [核心修复] 不再手动反转词序列表。
                # if self.sort_order_btn.isChecked():
                #     word_order.reverse() # <--- 已移除此行

                order_map = {word: i for i, word in enumerate(word_order)}
                
                matched_files = []
                unmatched_files = []

                for file_info in self.all_files_data:
                    word_stem, _ = os.path.splitext(file_info['name'])
                    if word_stem in order_map:
                        file_info['order'] = order_map[word_stem]
                        matched_files.append(file_info)
                    else:
                        unmatched_files.append(file_info)

                # [核心修复] 使用 sort() 方法的 reverse 参数来处理升/降序。
                # self.sort_order_btn.isChecked() == True 意为“降序”。
                is_descending = self.sort_order_btn.isChecked()
                matched_files.sort(key=lambda x: x['order'], reverse=is_descending)
                
                # 未匹配的文件总是按名称升序排列，放在列表末尾。
                unmatched_files.sort(key=lambda x: x['name'])

                # 如果是降序，未匹配的文件应该放在最前面。
                if is_descending:
                    sorted_files = unmatched_files + matched_files
                else:
                    sorted_files = matched_files + unmatched_files
                
                self.render_to_table(sorted_files)
            else:
                # --- (回退逻辑不变) ---
                self.status_label.setText("操作取消，已切换回按名称排序。")
                QTimer.singleShot(3000, lambda: self.status_label.setText("准备就绪"))
                self.sort_combo.setCurrentIndex(0)

        else:
            # --- 模式3: 常规排序 (逻辑不变) ---
            # ... (此部分代码无需改动) ...
            self.is_global_search_active = False
            self.audio_table_widget.setHorizontalHeaderLabels(["文件名", "文件大小", "修改日期", ""])
            if self.current_session_path:
                self.table_label.setText(f"项目: {os.path.basename(self.current_session_path)}")
            else:
                 self.table_label.setText("请从左侧选择一个项目以查看文件")
            is_reverse = self.sort_order_btn.isChecked()
            sorted_files = sorted(self.all_files_data, key=lambda x: x.get(self.current_sort_key, 0), reverse=is_reverse)
            self.render_to_table(sorted_files)

    def go_to_file(self, target_filepath):
        """
        根据给定的文件路径，自动切换UI到该文件所在的 数据源->项目，
        然后在文件列表中选中该文件，并开始播放。
        """
        # 1. 在全局索引中查找文件的元数据 (source_name, project_name)
        file_info = next((item for item in self.global_file_index if item['path'] == target_filepath), None)
        if not file_info:
            QMessageBox.warning(self, "跳转失败", "无法在全局文件索引中找到该文件的信息。")
            return

        # 2. 清空搜索框并重置搜索状态。这将自动触发 filter_and_render_files
        #    并使UI准备好恢复到常规浏览模式。
        #    我们先阻塞信号，以避免在跳转完成前触发不必要的刷新。
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
        self.is_global_search_active = False

        # 3. 以编程方式切换数据源
        source_index = self.source_combo.findText(file_info['source_name'])
        if source_index != -1:
            # 切换下拉框会触发 on_source_changed -> populate_session_list
            self.source_combo.setCurrentIndex(source_index)
        else:
            print(f"跳转失败: 找不到数据源 '{file_info['source_name']}'")
            return

        # 强制Qt处理完UI事件，确保项目列表已更新
        QApplication.processEvents()

        # 4. 在新的项目列表中找到并切换到目标项目
        items = self.session_list_widget.findItems(file_info['project_name'], Qt.MatchFixedString)
        if items:
            # 选中项目会触发 on_session_selection_changed -> populate_audio_table
            self.session_list_widget.setCurrentItem(items[0])
        else:
            print(f"跳转失败: 找不到项目 '{file_info['project_name']}'")
            return
            
        # 再次强制处理事件，确保文件列表已更新
        QApplication.processEvents()

        # 5. 在新加载的文件列表中找到目标文件，选中并播放
        for row in range(self.audio_table_widget.rowCount()):
            item = self.audio_table_widget.item(row, 0)
            if item and item.data(Qt.UserRole) == target_filepath:
                self.audio_table_widget.setCurrentCell(row, 0)
                # 此时，UI上下文已完全正确，可以安全地调用播放了
                self.play_selected_item(row)
                return


    # [新增] 专门用于渲染全局搜索结果的方法
    def render_global_search_results(self, results):
        """
        将全局搜索的结果渲染到表格中，并显示额外的上下文信息。
        """
        self.audio_table_widget.setRowCount(0)
        self.table_label.setText(f"全局搜索到 {len(results)} 个结果")

        if not results:
            return

        # 调整表头以显示上下文信息
        self.audio_table_widget.setHorizontalHeaderLabels(["文件名 (项目 @ 数据源)", "文件大小", "修改日期", ""])
        
        self.audio_table_widget.setRowCount(len(results))
        for row, file_info in enumerate(results):
            # 在文件名中加入上下文
            display_name = f"{file_info['name']}  (@{file_info['project_name']})"
            item_filename = QTableWidgetItem(display_name)
            item_filename.setData(Qt.UserRole, file_info['path'])
            item_filename.setToolTip(f"路径: {file_info['path']}")

            # 其他列的信息需要重新获取
            try:
                stat = os.stat(file_info['path'])
                size_str = f"{stat.st_size / 1024:.1f} KB"
                mtime_str = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
            except OSError:
                size_str = "N/A"
                mtime_str = "N/A"
            
            self.audio_table_widget.setItem(row, 0, item_filename)
            self.audio_table_widget.setItem(row, 1, QTableWidgetItem(size_str))
            self.audio_table_widget.setItem(row, 2, QTableWidgetItem(mtime_str))
            
            # 快捷按钮的逻辑保持不变，可以复用
            self._setup_shortcut_button(row, file_info['path'])
            
        if results:
            self._update_player_cache(0)

    def render_to_table(self, files_data):
        """
        [v3.0] 将处理好的局部文件数据模型渲染到 QTableWidget 中。
        """
        self.audio_table_widget.setRowCount(0)
        self.audio_table_widget.setRowCount(len(files_data))
        
        for row, file_info in enumerate(files_data):
            # 1. 填充前三列的数据
            filepath = file_info['path']
            filename = file_info['name']
            file_size_str = f"{file_info['size'] / 1024:.1f} KB"
            mod_time_str = datetime.fromtimestamp(file_info['mtime']).strftime('%Y-%m-%d %H:%M')
            
            item_filename = QTableWidgetItem(filename)
            item_filename.setData(Qt.UserRole, filepath)
            
            self.audio_table_widget.setItem(row, 0, item_filename)
            self.audio_table_widget.setItem(row, 1, QTableWidgetItem(file_size_str))
            self.audio_table_widget.setItem(row, 2, QTableWidgetItem(mod_time_str))
            
            # 2. 调用新方法来创建第四列的按钮
            self._setup_shortcut_button(row, filepath)
            
        # 预加载第一个项目
        if len(files_data) > 0:
            self._update_player_cache(0)
            

    def update_table_row(self, row, filepath):
        filename = os.path.basename(filepath); file_size = os.path.getsize(filepath); mod_time = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M')
        item_filename = QTableWidgetItem(filename); item_filename.setData(Qt.UserRole, filepath)
        self.audio_table_widget.setItem(row, 0, item_filename); self.audio_table_widget.setItem(row, 1, QTableWidgetItem(f"{file_size / 1024:.1f} KB")); self.audio_table_widget.setItem(row, 2, QTableWidgetItem(mod_time))
        
        # [重构] 根据 self.shortcut_button_action 动态创建快捷按钮
        shortcut_btn = QPushButton()
        shortcut_btn.setCursor(Qt.PointingHandCursor)
        shortcut_btn.setObjectName("LinkButton")

        action = self.shortcut_button_action
        if action == 'delete':
            shortcut_btn.setIcon(self.icon_manager.get_icon("delete"))
            shortcut_btn.setToolTip("快捷操作：删除此文件")
            shortcut_btn.clicked.connect(lambda _, f=filepath: self.delete_file(f))
        elif action == 'play':
            shortcut_btn.setIcon(self.icon_manager.get_icon("play_audio"))
            # [核心修正] 更新工具提示，使其更准确
            shortcut_btn.setToolTip("快捷操作：试听/暂停此文件")
            # [核心修正] 连接到新的智能处理函数
            shortcut_btn.clicked.connect(lambda _, r=row: self._on_shortcut_play_button_clicked(r))
        elif action == 'analyze':
            shortcut_btn.setIcon(self.icon_manager.get_icon("analyze"))
            shortcut_btn.setToolTip("快捷操作：在音频分析中打开")
            shortcut_btn.clicked.connect(lambda _, f=filepath: self.parent_window.go_to_audio_analysis(f))
        elif action == 'stage':
            shortcut_btn.setIcon(self.icon_manager.get_icon("add_row"))
            shortcut_btn.setToolTip("快捷操作：将此文件添加到暂存区")
            shortcut_btn.clicked.connect(lambda _, r=row: self._add_single_to_staging(r))
        elif action == 'rename':
            shortcut_btn.setIcon(self.icon_manager.get_icon("rename"))
            shortcut_btn.setToolTip("快捷操作：重命名此文件")
            shortcut_btn.clicked.connect(lambda _, r=row: self.rename_selected_file(r))
        elif action == 'explorer':
            shortcut_btn.setIcon(self.icon_manager.get_icon("show_in_explorer"))
            shortcut_btn.setToolTip("快捷操作：在文件浏览器中显示")
            shortcut_btn.clicked.connect(lambda _, f=filepath: self.open_in_explorer(os.path.dirname(f), select_file=os.path.basename(f)))
            
        self.audio_table_widget.setCellWidget(row, 3, shortcut_btn)
        
    def on_player_state_changed(self, state):
        # 1. 根据播放器是否在“播放中”状态，决定按钮是否应被“勾选”
        should_be_checked = (state == QMediaPlayer.PlayingState)
        
        # 2. 在同步UI前阻塞信号，防止无限循环
        self.play_pause_btn.blockSignals(True)
        self.play_pause_btn.setChecked(should_be_checked)
        self.play_pause_btn.blockSignals(False)

        # 3. 更新按钮的启用状态
        if state == QMediaPlayer.StoppedState and not self.active_player:
             self.play_pause_btn.setEnabled(False)
        else:
             self.play_pause_btn.setEnabled(True)
        
    def on_item_double_clicked(self, item):
        module_states = self.config.get("module_states", {}).get("audio_manager", {})
        action = module_states.get("double_click_action", "play")
        row = item.row()
        
        if action == "play":
            # 区分全局搜索和常规模式
            if self.is_global_search_active:
                filepath = item.data(Qt.UserRole)
                if filepath:
                    self.go_to_file(filepath)
            else:
                self.play_selected_item(row)
        elif action == "analyze":
            filepath = self.audio_table_widget.item(row, 0).data(Qt.UserRole)
            if filepath: self.send_to_audio_analysis(filepath)
        elif action == "explorer":
            filepath = self.audio_table_widget.item(row, 0).data(Qt.UserRole)
            if filepath: self.open_in_explorer(os.path.dirname(filepath), select_file=os.path.basename(filepath))
        elif action == "rename":
            self.rename_selected_file(row)
    
    def on_session_selection_changed(self):
        selected_items = self.session_list_widget.selectedItems()
        if not selected_items:
            self.audio_table_widget.setRowCount(0)
            self.table_label.setText("请从左侧选择一个项目以查看文件")
            self.session_active = False
            self.reset_player()
            return
        
        # 保存当前选中的项目状态
        module_states = self.config.get("module_states", {}).get("audio_manager", {})
        if module_states.get("load_last_source", True):
            self._on_persistent_setting_changed("last_project", selected_items[0].text())

        source_name = self.source_combo.currentText()
        source_info = self.DATA_SOURCES.get(source_name)
        
        if not source_info:
            for custom_source in self.custom_data_sources:
                if custom_source['name'] == source_name:
                    source_info = {"path": custom_source['path']}
                    break
        
        if not source_info:
            self.audio_table_widget.setRowCount(0)
            self.table_label.setText("无效的数据源")
            self.session_active = False
            self.reset_player()
            return

        self.session_active = True
        self.current_session_path = os.path.join(source_info["path"], selected_items[0].text())
        self.table_label.setText(f"项目: {selected_items[0].text()}")
        self.populate_audio_table()

    def _find_and_select_file(self, filepath_to_find):
        module_states = self.config.get("module_states", {}).get("audio_manager", {})
        if not module_states.get("auto_select_new_file", True):
            return

        for row in range(self.audio_table_widget.rowCount()):
            item = self.audio_table_widget.item(row, 0)
            if item and item.data(Qt.UserRole) == filepath_to_find:
                self.audio_table_widget.setCurrentCell(row, 0)
                # 确保选中行可见
                self.audio_table_widget.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                break
        
    def rename_folder(self, item, base_dir):
        old_name = item.text()
        old_path = os.path.join(base_dir, old_name)
        new_name, ok = QInputDialog.getText(self, "重命名文件夹", "请输入新的文件夹名称:", QLineEdit.Normal, old_name)
        
        if ok and new_name and new_name.strip() and new_name != old_name:
            new_path = os.path.join(base_dir, new_name.strip())
            if os.path.exists(new_path):
                QMessageBox.warning(self, "错误", "该名称的文件夹已存在。")
                return
            
            try:
                # [修复] 在重命名文件夹之前，彻底释放所有可能的文件句柄
                self.reset_player()
                QApplication.processEvents() # 允许事件循环处理播放器停止

                os.rename(old_path, new_path)
                item.setText(new_name)
                
                # [可选但推荐] 更新 current_session_path，如果重命名的是当前选中的文件夹
                if self.current_session_path == old_path:
                    self.current_session_path = new_path

            except Exception as e:
                QMessageBox.critical(self, "错误", f"重命名失败: {e}")
            
    def open_folder_context_menu(self, position):
        selected_items = self.session_list_widget.selectedItems()
        if not selected_items: return
        
        menu = QMenu(self.audio_table_widget)

        # --- 原有的删除、重命名、打开文件夹等操作逻辑保持不变 ---
        delete_action = menu.addAction(self.icon_manager.get_icon("delete"), f"删除选中的 {len(selected_items)} 个项目")
        rename_action = menu.addAction(self.icon_manager.get_icon("rename"), "重命名")
        rename_action.setEnabled(len(selected_items) == 1)
        menu.addSeparator()
        open_folder_action = menu.addAction(self.icon_manager.get_icon("open_folder"), "在文件浏览器中打开")
        open_folder_action.setEnabled(len(selected_items) == 1)

        # --- [核心重构] 动态的、单一的词表关联操作 ---
        if len(selected_items) == 1:
            item = selected_items[0]
            # 获取当前选中的项目文件夹的完整路径
            source_name = self.source_combo.currentText()
            base_dir = self.DATA_SOURCES.get(source_name, {}).get("path")
            if not base_dir:
                 for custom_source in self.custom_data_sources:
                    if custom_source['name'] == source_name:
                        base_dir = custom_source['path']
                        break
            
            if base_dir:
                folder_path = os.path.join(base_dir, item.text())
                
                menu.addSeparator()
                
                # 1. 检查是否存在关联
                cache_file_path = self._get_wordlist_order_path_for_folder(folder_path)
                is_associated = os.path.exists(cache_file_path)

                # 2. 根据关联状态，动态创建唯一的菜单项
                if is_associated:
                    # 如果已关联，则创建 "清除关联" 操作
                    association_action = menu.addAction(self.icon_manager.get_icon("unlink"), "清除词表关联")
                    association_action.setToolTip("清除当前项目文件夹与词表的关联，以便重新选择。")
                    association_action.triggered.connect(lambda: self._clear_wordlist_association_for_folder(folder_path))
                else:
                    # 如果未关联，则创建 "关联词表" 操作
                    association_action = menu.addAction(self.icon_manager.get_icon("link"), "关联词表...")
                    association_action.setToolTip("为此项目文件夹指定一个词表，用于'按词表顺序'排序。")
                    association_action.triggered.connect(lambda: self._associate_wordlist_for_folder(folder_path))

        # --- 后续的菜单显示和事件处理逻辑保持不变 ---
        action = menu.exec_(self.session_list_widget.mapToGlobal(position))
        
        source_name = self.source_combo.currentText()
        base_dir = self.DATA_SOURCES.get(source_name, {}).get("path")
        if not base_dir:
            for custom_source in self.custom_data_sources:
                if custom_source['name'] == source_name: base_dir = custom_source['path']; break
        
        if not base_dir:
            QMessageBox.warning(self, "错误", "无法确定数据源路径。"); return

        if action == delete_action: self.delete_folders(selected_items, base_dir)
        elif action == rename_action: self.rename_folder(selected_items[0], base_dir)
        elif action == open_folder_action: self.open_in_explorer(os.path.join(base_dir, selected_items[0].text()))

    # ==============================================================================
    # [新增] 词表关联辅助方法
    # ==============================================================================
    def _get_wordlist_order_path_for_folder(self, folder_path):
        """
        获取指定项目文件夹下.wordlist_order缓存文件的路径。
        这是一个更通用的版本，不依赖于 self.current_session_path。
        """
        if not folder_path:
            return None
        return os.path.join(folder_path, '.wordlist_order')


    def _is_folder_associated(self, folder_path):
        """
        检查指定的项目文件夹是否已通过日志或缓存文件关联了词表。
        """
        if not folder_path or not os.path.isdir(folder_path):
            return False

        # 优先级1：检查log.txt
        log_path = os.path.join(folder_path, 'log.txt')
        if os.path.exists(log_path):
            if self._parse_log_for_wordlist(log_path):
                return True # 如果能从日志中解析出词表，则为关联状态

        # 优先级2：检查.wordlist_order缓存文件
        cache_file_path = self._get_wordlist_order_path_for_folder(folder_path)
        if os.path.exists(cache_file_path):
            return True # 如果存在手动关联的缓存文件，则为关联状态

        return False # 两种情况都不满足，则未关联

    def _associate_wordlist_for_folder(self, folder_path):
        """
        [v1.1 - Custom Dialog] 为指定的文件夹弹出自定义词表选择器并关联一个词表。
        """
        word_list_dir = os.path.join(self.BASE_PATH, "word_lists")
        # [核心修改] 使用 WordlistSelectionDialog
        dialog = WordlistSelectionDialog(self, word_list_dir, self.icon_manager, pin_handler=None)
        dialog.setWindowTitle(f"为 '{os.path.basename(folder_path)}' 关联词表")

        if dialog.exec_() == QDialog.Accepted and dialog.selected_file_relpath:
            rel_path = dialog.selected_file_relpath
            self._save_wordlist_association(rel_path, folder_path=folder_path) # 传递folder_path
            self.status_label.setText(f"项目 '{os.path.basename(folder_path)}' 已成功关联词表。")
            
            if folder_path == self.current_session_path and self.current_sort_key == 'wordlist':
                self.filter_and_render_files()
            
            # 刷新项目列表以更新图标
            self.populate_session_list()

    def _clear_wordlist_association_for_folder(self, folder_path):
        """
        [v1.1] 清除指定文件夹的词表关联，并刷新UI。
        """
        cache_file_path = self._get_wordlist_order_path_for_folder(folder_path)
        if cache_file_path and os.path.exists(cache_file_path):
            try:
                os.remove(cache_file_path)
                self.status_label.setText(f"项目 '{os.path.basename(folder_path)}' 的词表关联已清除。")
                
                # [核心修复] 在清除关联后，立即调用列表刷新方法
                self.populate_session_list()
                
                if folder_path == self.current_session_path and self.current_sort_key == 'wordlist':
                    self.sort_combo.setCurrentIndex(0)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"清除关联失败: {e}")
        
    def delete_folders(self, items, base_dir):
        """删除所有在项目列表中选中的文件夹。"""
        paths = [os.path.join(base_dir, item.text()) for item in items]
        if paths:
            self._request_delete_items(paths, is_folder=True)

    # --- [新增] 提取出的物理删除逻辑 ---
    def _delete_files_permanently(self, filepaths):
        """执行文件的物理删除。(前置的reset_player由_request_delete_items负责)"""
        error_files = []
        for path in filepaths:
            try:
                os.remove(path)
            except Exception as e:
                error_files.append(f"{os.path.basename(path)}: {e}")
        if error_files:
            QMessageBox.critical(self, "部分文件删除失败", "\n".join(error_files))

    def _delete_folders_permanently(self, dirpaths):
        """执行文件夹的物理删除。"""
        for path in dirpaths:
            try:
                shutil.rmtree(path)
            except Exception as e:
                QMessageBox.critical(self, "删除失败", f"删除 '{os.path.basename(path)}' 时出错:\n{e}")
                break
            
    # [修改] set_shortcut_button_action 方法，增加持久化调用
    def set_shortcut_button_action(self, action_key):
        if self.shortcut_button_action != action_key:
            self.shortcut_button_action = action_key
            # 调用新的持久化方法
            self._on_persistent_setting_changed('shortcut_action', action_key)
            self.populate_audio_table() # 重绘整个表格以应用新按钮

    # [新增] 添加单个文件到暂存区的辅助方法
    def _add_single_to_staging(self, row):
        filepath = self.audio_table_widget.item(row, 0).data(Qt.UserRole)
        if filepath not in self.staged_files:
            display_name = f"{os.path.basename(os.path.dirname(filepath))} / {os.path.basename(filepath)}"
            self.staged_files[filepath] = display_name
            self.status_label.setText("已添加 1 个新文件到暂存区。")
            QTimer.singleShot(3000, lambda: self.status_label.setText("准备就绪"))
        else:
            self.status_label.setText("该文件已在暂存区中。")
            QTimer.singleShot(3000, lambda: self.status_label.setText("准备就绪"))
        self._update_staging_list_widget()
    
    # [修改] 重命名文件方法，使其可以接受行号
    def rename_selected_file(self, row_to_rename=None):
        if row_to_rename is None:
            selected_items = self.audio_table_widget.selectedItems()
            if not selected_items: return
            row = selected_items[0].row()
        else:
            row = row_to_rename
            
        old_filepath = self.audio_table_widget.item(row, 0).data(Qt.UserRole)
        old_basename, ext = os.path.splitext(os.path.basename(old_filepath))
        new_basename, ok = QInputDialog.getText(self, "重命名文件", "请输入新的文件名:", QLineEdit.Normal, old_basename)
        if ok and new_basename and new_basename.strip() and new_basename != old_basename:
            new_filepath = os.path.join(self.current_session_path, new_basename.strip() + ext)
            if os.path.exists(new_filepath): QMessageBox.warning(self, "错误", "文件名已存在。"); return
            try:
                # 同样，在重命名前，重置播放器以释放句柄
                self.reset_player()
                QApplication.processEvents()
                os.rename(old_filepath, new_filepath)
                self.populate_audio_table() # 重绘表格以更新
                self._find_and_select_file(new_filepath)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"重命名失败: {e}")
            
    def open_in_explorer(self, path, select_file=None):
        if not path or not os.path.exists(path): return
        try:
            if sys.platform == 'win32':
                if select_file: subprocess.run(['explorer', '/select,', os.path.join(path, select_file)])
                else: os.startfile(os.path.realpath(path))
            elif sys.platform == 'darwin': subprocess.check_call(['open', '-R', os.path.join(path, select_file)] if select_file else ['open', path])
            else: subprocess.check_call(['xdg-open', path])
        except Exception as e: QMessageBox.critical(self, "错误", f"无法打开路径: {e}")
    def _delete_single_item_from_shortcut(self, row):
        """
        当用户点击行末的快捷删除按钮时调用。
        它会先以编程方式选中该行，然后调用通用的删除方法。
        """
        # 步骤1：强制清除当前所有选择
        self.audio_table_widget.clearSelection()
        
        # 步骤2：以编程方式选中按钮所在的行
        self.audio_table_widget.selectRow(row)
        
        # 步骤3：现在，调用那个已经被我们修复好的、处理“选中项”的删除方法
        # 此时的程序状态与用户手动右键删除完全一致
        self.delete_selected_files()        
    def reset_player_ui(self):
        self.playback_slider.setValue(0)
        self.playback_slider.setEnabled(False)
        self.duration_label.setText("00:00.00 / 00:00.00")
        self.play_pause_btn.setEnabled(False)
        self.on_player_state_changed(QMediaPlayer.StoppedState)
        self.waveform_widget.clear()
        self._clear_trim_points()
            
    def on_play_button_toggled(self, checked):
        # [核心修改] 如果用户在归零动画期间点击播放，则立即停止动画
        if self._is_slider_resetting:
            if hasattr(self, '_slider_reset_anim'):
                self._slider_reset_anim.stop()
            self._is_slider_resetting = False
            # 确保UI立即跳转到0，准备播放
            self.update_playback_position(0)
        if not self.active_player:
            # 如果没有激活的播放器，但用户点击了播放
            if checked:
                current_row = self.audio_table_widget.currentRow()
                if current_row != -1:
                    self.play_selected_item(current_row)
                else:
                    # 没有选中项，无法播放，将按钮弹回
                    self.play_pause_btn.setChecked(False)
            return

        # 如果有激活的播放器
        if checked and self.active_player.state() != QMediaPlayer.PlayingState:
            self.active_player.play()
        elif not checked and self.active_player.state() == QMediaPlayer.PlayingState:
            self.active_player.pause()

    # [保留并简化] toggle_playback 现在只作为快捷键的入口
    def toggle_playback(self):
        """响应空格快捷键，切换按钮的 checked 状态。"""
        # 只切换状态，UI动画和播放逻辑将由 toggled 信号的槽函数处理
        if self.play_pause_btn.isEnabled():
            self.play_pause_btn.toggle()
        
    def update_playback_duration(self, duration):
        if self.active_player and duration > 0 and duration != self.current_displayed_duration:
            self.current_displayed_duration = duration; self.playback_slider.setRange(0, duration); self.duration_label.setText(f"{self.format_time(self.active_player.position())} / {self.format_time(duration)}")
            self.playback_slider.setEnabled(True)
            
    def set_playback_position(self, position):
        # [核心修改] 如果用户在归零动画期间与滑块交互，则立即停止动画
        if self._is_slider_resetting:
            if hasattr(self, '_slider_reset_anim'):
                self._slider_reset_anim.stop()
            self._is_slider_resetting = False

        if self.active_player: self.active_player.setPosition(position)
        
    def format_time(self, ms):
        if ms <= 0: return "00:00.00"
        total_seconds = ms / 1000.0; m, s_frac = divmod(total_seconds, 60); s_int = int(s_frac); cs = int(round((s_frac - s_int) * 100));
        if cs == 100: cs = 0; s_int +=1
        if s_int == 60: s_int = 0; m += 1
        return f"{int(m):02d}:{s_int:02d}.{cs:02d}"
    # ==============================================================================
    # [新增] 词表排序核心逻辑
    # ==============================================================================
    def _get_word_order(self):
        """
        [v1.2 - Configurable Auto-match] 核心调度器：按优先级获取词序列表。
        自动匹配逻辑现在受设置控制。
        """
        if not self.current_session_path:
            return None

        # 优先级 1 & 2: 检查log.txt和.wordlist_order缓存 (逻辑不变)
        log_path = os.path.join(self.current_session_path, 'log.txt')
        if os.path.exists(log_path):
            wordlist_rel_path = self._parse_log_for_wordlist(log_path)
            if wordlist_rel_path:
                self.status_label.setText("状态：检测到日志，按日志中词表排序。")
                QTimer.singleShot(3000, lambda: self.status_label.setText("准备就绪"))
                return self._load_word_order_from_file(wordlist_rel_path)
        
        cache_file_path = self._get_wordlist_order_path()
        if os.path.exists(cache_file_path):
            with open(cache_file_path, 'r', encoding='utf-8') as f:
                wordlist_rel_path = f.read().strip()
            if wordlist_rel_path:
                return self._load_word_order_from_file(wordlist_rel_path)
        
        # [核心修改] 优先级 3: 检查设置，如果启用，则尝试自动匹配
        module_states = self.config.get("module_states", {}).get("audio_manager", {})
        is_auto_associate_enabled = module_states.get("auto_associate_wordlist", True)

        if is_auto_associate_enabled:
            self.status_label.setText("状态：正在尝试自动匹配同名词表...")
            QApplication.processEvents()
            
            found_rel_path = self._find_matching_wordlist_automatically()
            if found_rel_path:
                self.status_label.setText(f"状态：成功自动关联到词表 '{os.path.basename(found_rel_path)}'！")
                QTimer.singleShot(3000, lambda: self.status_label.setText("准备就绪"))
                
                self._save_wordlist_association(found_rel_path)
                self.populate_session_list()
                return self._load_word_order_from_file(found_rel_path)

        # 优先级 4 (回退): 提示用户手动选择
        self.status_label.setText("状态：未找到自动匹配，请手动选择词表。")
        return self._prompt_and_save_wordlist_order()

    def _find_matching_wordlist_automatically(self):
        """
        [新增] 遍历 word_lists 目录及其所有子目录，
        查找与当前项目文件夹同名的词表文件。
        """
        if not self.current_session_path:
            return None
        
        project_name = os.path.basename(self.current_session_path)
        word_lists_root = os.path.join(self.BASE_PATH, "word_lists")

        for root, _, files in os.walk(word_lists_root):
            for filename in files:
                if filename.lower().endswith('.json'):
                    file_stem, _ = os.path.splitext(filename)
                    if file_stem == project_name:
                        # 找到了匹配项！
                        full_path = os.path.join(root, filename)
                        # 返回相对于 word_lists 根目录的路径
                        rel_path = os.path.relpath(full_path, word_lists_root)
                        return rel_path.replace(os.path.sep, '/')
        
        # 遍历完成，没有找到匹配项
        return None

    def _save_wordlist_association(self, rel_path, folder_path=None):
        """
        [v1.1] 将一个词表关联保存到指定项目（或当前项目）的.wordlist_order文件中。
        """
        try:
            # [核心修改] 如果未提供 folder_path，则使用 self.current_session_path
            target_folder = folder_path if folder_path else self.current_session_path
            cache_file_path = self._get_wordlist_order_path_for_folder(target_folder)
            
            if cache_file_path:
                with open(cache_file_path, 'w', encoding='utf-8') as f:
                    f.write(rel_path)
                return True
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存词表关联时出错: {e}")
        return False

    def _parse_log_for_wordlist(self, log_path):
        """解析log.txt文件，提取词表相对路径。"""
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                content = f.read()
            match = re.search(r"\[SESSION_CONFIG\] Wordlist: '(.*?)'", content)
            if match:
                return match.group(1)
        except Exception as e:
            print(f"Error parsing log file {log_path}: {e}")
        return None

    def _get_wordlist_order_path(self):
        """获取当前项目文件夹下.wordlist_order缓存文件的路径。"""
        if not self.current_session_path:
            return None
        return os.path.join(self.current_session_path, '.wordlist_order')

    def _prompt_and_save_wordlist_order(self):
        """
        [v1.1 - Custom Dialog] 弹出自定义词表选择器，让用户选择词表，
        并保存其相对路径。
        """
        word_list_dir = os.path.join(self.BASE_PATH, "word_lists")
        # [核心修改] 使用 WordlistSelectionDialog
        # 因为音频管理器不处理固定功能，所以 pin_handler=None
        dialog = WordlistSelectionDialog(self, word_list_dir, self.icon_manager, pin_handler=None)
        
        if dialog.exec_() == QDialog.Accepted and dialog.selected_file_relpath:
            rel_path = dialog.selected_file_relpath
            if self._save_wordlist_association(rel_path):
                self.populate_session_list()
                return self._load_word_order_from_file(rel_path)
            else:
                return None
        else:
            return None # 用户取消
            
    def _load_word_order_from_file(self, wordlist_rel_path):
        """从指定的JSON词表文件中加载并“压平”词序。"""
        word_list_dir = os.path.join(self.BASE_PATH, "word_lists")
        full_path = os.path.join(word_list_dir, wordlist_rel_path)

        if not os.path.exists(full_path):
            QMessageBox.warning(self, "词表丢失", f"找不到指定的词表文件:\n{full_path}\n请重新指定。")
            # 删除无效的缓存文件
            cache_path = self._get_wordlist_order_path()
            if os.path.exists(cache_path):
                os.remove(cache_path)
            return self._prompt_and_save_wordlist_order() # 引导用户重新选择

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            word_order = []
            if "groups" in data and isinstance(data["groups"], list):
                for group in data["groups"]:
                    if "items" in group and isinstance(group["items"], list):
                        for item in group["items"]:
                            if "text" in item:
                                word_order.append(item["text"])
            return word_order
        except Exception as e:
            QMessageBox.critical(self, "词表解析失败", f"无法加载或解析词表 '{os.path.basename(full_path)}':\n{e}")
            return None
        
    def reset_player(self):
        """[v2.3 彻底清理版] 安全地重置所有播放器和UI。"""
        try:
            if self.preview_player:
                self.preview_player.stop()
        except RuntimeError:
            pass
        finally:
            self.preview_player = None
            self._is_slider_resetting = False
        
        # [核心修正] 彻底清理所有播放器资源
        self._clear_player_cache()
        
        # [核心修正] 在清理缓存后，显式地将 active_player 也设为 None
        # _clear_player_cache 内部虽然做了，但在这里再次确认，确保状态绝对干净
        self.active_player = None

        # [核心修正] 立即将所有与播放器相关的UI重置到初始状态
        # 这确保了在文件被删除、UI刷新之前，没有任何UI元素会去引用一个无效的播放器
        self.reset_player_ui()
# [新增] 用于处理和保存持久化设置的槽函数
    def _on_persistent_setting_changed(self, key, value):
        """当用户更改任何可记忆的设置时，调用此方法以保存状态。"""
        self.parent_window.update_and_save_module_state('audio_manager', key, value)

    def _send_to_batch_processor(self):
        """收集所有选中的文件路径，并通过插件管理器执行批量处理插件。"""
        selected_rows = sorted(list(set(item.row() for item in self.audio_table_widget.selectedItems())))
        if not selected_rows:
            return
        
        filepaths = [self.audio_table_widget.item(row, 0).data(Qt.UserRole) for row in selected_rows]
        
        # [核心修正] 使用 self.parent_window 访问插件管理器
        self.parent_window.plugin_manager.execute_plugin(
            'com.phonacq.batch_processor',
            filepaths=filepaths
        )
    # [新增] 调用插件快速标准化功能的辅助方法
    def _run_quick_normalize(self):
        """
        收集选中的文件路径，并调用批量处理插件的快速标准化功能。
        """
        selected_rows = sorted(list(set(item.row() for item in self.audio_table_widget.selectedItems())))
        if not selected_rows:
            return
        
        filepaths = [self.audio_table_widget.item(row, 0).data(Qt.UserRole) for row in selected_rows]
        
        # 获取插件实例并调用新方法
        processor_plugin = getattr(self, 'batch_processor_plugin_active', None)
        if processor_plugin and hasattr(processor_plugin, 'execute_quick_normalize'):
            processor_plugin.execute_quick_normalize(filepaths=filepaths)
        else:
            QMessageBox.critical(self, "功能错误", "批量处理器插件已激活，但缺少 'execute_quick_normalize' 方法。")
class SettingsDialog(QDialog):
    """
    音频数据管理器的专属设置对话框。
    
    这个对话框被设计为完全自包含的，负责：
    1. 构建所有与此模块相关的设置UI。
    2. 从主配置文件中加载当前设置并填充UI。
    3. 在用户确认后，将UI上的新设置保存回主配置文件。
    """
    
    def __init__(self, parent_page, file_manager_available):
        """
        构造函数。
        
        Args:
            parent_page (AudioManagerPage): 对主页面实例的引用，用于访问配置和主窗口。
            file_manager_available (bool): 指示文件管理器插件是否可用，用于控制UI状态。
        """
        super().__init__(parent_page)
        
        # --- 属性初始化 ---
        self.parent_page = parent_page
        
        # --- 窗口基本设置 ---
        self.setWindowTitle("音频管理器设置")
        self.setWindowIcon(self.parent_page.parent_window.windowIcon())
        self.setStyleSheet(self.parent_page.parent_window.styleSheet())
        self.setMinimumWidth(450)
        
        # --- UI构建与数据加载 ---
        self._init_ui(file_manager_available)
        self._connect_signals()
        self.load_settings()

    # ==============================================================================
    # UI 构建
    # ==============================================================================
    def _init_ui(self, file_manager_available):
        """构建对话框的用户界面。"""
        # 主布局，采用垂直布局
        layout = QVBoxLayout(self)

        # --- 组1: 界面与交互 ---
        ui_group = QGroupBox("界面与交互")
        ui_form_layout = QFormLayout(ui_group)
        ui_form_layout.setRowWrapPolicy(QFormLayout.WrapAllRows) # 确保长文本能换行

        # 控件：文件双击行为
        self.double_click_combo = QComboBox()
        self.double_click_combo.addItems([
            "播放/暂停", 
            "在音频分析中打开", 
            "在文件浏览器中显示", 
            "重命名"
        ])
        self.double_click_combo.setToolTip(
            "自定义在文件列表中双击一个文件时执行的操作。"
        )

        # 控件：启动时自动加载上次的数据源
        self.load_last_source_check = QCheckBox("启动时自动加载上次的数据源")
        self.load_last_source_check.setToolTip(
            "下次进入此模块时，自动恢复到您上次查看的项目。"
        )
        
        # 将控件添加到表单布局
        ui_form_layout.addRow("文件双击行为:", self.double_click_combo)
        ui_form_layout.addRow(self.load_last_source_check)
        
        layout.addWidget(ui_group)

        # --- 组2: 文件操作 ---
        file_ops_group = QGroupBox("文件操作")
        file_ops_form_layout = QFormLayout(file_ops_group)
        file_ops_form_layout.setRowWrapPolicy(QFormLayout.WrapAllRows)

        # 控件：重命名或裁切后自动选中
        self.auto_select_check = QCheckBox("重命名或裁切后自动选中新文件")
        self.auto_select_check.setToolTip(
            "启用后，程序会自动在列表中找到并高亮新创建的文件。"
        )

        # 控件：删除时移至回收站
        self.recycle_bin_checkbox = QCheckBox("删除时移至回收站")
        self.recycle_bin_checkbox.setEnabled(file_manager_available)
        if file_manager_available:
            self.recycle_bin_checkbox.setToolTip(
                "勾选后，删除的文件将进入回收站（如果可用）。\n"
                "取消勾选则会直接永久删除。"
            )
        else:
            self.recycle_bin_checkbox.setToolTip(
                "此选项需要 '文件管理器' 插件被启用。"
            )
        
        # [核心新增] 控件：自动匹配同名词表
        self.auto_associate_checkbox = QCheckBox("自动匹配同名词表")
        self.auto_associate_checkbox.setToolTip(
            "勾选后，在'按词表顺序'排序时，\n"
            "如果项目未关联词表，将自动在词表库中搜索同名文件并关联。"
        )

        # 将控件添加到表单布局
        file_ops_form_layout.addRow(self.auto_select_check)
        file_ops_form_layout.addRow(self.recycle_bin_checkbox)
        # [核心新增] 将新控件添加到布局中
        file_ops_form_layout.addRow(self.auto_associate_checkbox)
        layout.addWidget(file_ops_group)

        # --- 底部按钮栏 ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(self.button_box)

    def _connect_signals(self):
        """连接所有UI控件的信号与槽。"""
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    # ==============================================================================
    # 数据加载与保存
    # ==============================================================================
    def load_settings(self):
        """从主配置文件中加载设置，并更新UI控件的当前状态。"""
        # 安全地获取本模块的设置字典
        module_states = self.parent_page.config.get("module_states", {}).get("audio_manager", {})
        
        # 定义内部存储值与UI显示文本的映射关系，方便双向转换
        action_map = {
            "play": "播放/暂停", 
            "analyze": "在音频分析中打开", 
            "explorer": "在文件浏览器中显示", 
            "rename": "重命名"
        }
        
        # --- 加载“界面与交互”设置 ---
        # 默认为 'play'
        double_click_action = module_states.get("double_click_action", "play")
        self.double_click_combo.setCurrentText(action_map.get(double_click_action, "播放/暂停"))
        
        # 默认为 True
        self.load_last_source_check.setChecked(module_states.get("load_last_source", True))
        
        # --- 加载“文件操作”设置 ---
        # 默认为 True
        self.auto_select_check.setChecked(module_states.get("auto_select_new_file", True))
        
        # 默认为 'trash'
        deletion_behavior = module_states.get("deletion_behavior", "trash")
        self.recycle_bin_checkbox.setChecked(deletion_behavior == "trash")
        self.auto_associate_checkbox.setChecked(module_states.get("auto_associate_wordlist", True))

    def save_settings(self):
        """从UI控件收集当前的设置值，并将其保存回主配置文件。"""
        # 定义UI显示文本与内部存储值的反向映射
        reverse_action_map = {
            "播放/暂停": "play", 
            "在音频分析中打开": "analyze", 
            "在文件浏览器中显示": "explorer", 
            "重命名": "rename"
        }

        # 构建要保存的设置字典
        settings_to_save = {
            # --- 保存“界面与交互”设置 ---
            "double_click_action": reverse_action_map.get(self.double_click_combo.currentText(), "play"),
            "load_last_source": self.load_last_source_check.isChecked(),
            
            # --- 保存“文件操作”设置 ---
            "auto_select_new_file": self.auto_select_check.isChecked(),
            "deletion_behavior": "trash" if self.recycle_bin_checkbox.isChecked() else "permanent",
            "auto_associate_wordlist": self.auto_associate_checkbox.isChecked(),
            
            # --- 保留从主页面读取的其他既有设置，避免覆盖 ---
            "shortcut_action": self.parent_page.shortcut_button_action,
            "adaptive_volume": self.parent_page.adaptive_volume_switch.isChecked(),
        }
        
        # 如果启用了“加载上次源”，则额外保存当前的位置信息
        if self.load_last_source_check.isChecked():
            settings_to_save['last_source'] = self.parent_page.source_combo.currentText()
            current_project_item = self.parent_page.session_list_widget.currentItem()
            settings_to_save['last_project'] = current_project_item.text() if current_project_item else None
        
        # 通过主窗口的公共API来更新并保存配置
        main_window = self.parent_page.parent_window
        main_window.update_and_save_module_state('audio_manager', settings_to_save)

    # ==============================================================================
    # QDialog 标准方法重写
    # ==============================================================================
    def accept(self):
        """
        重写 QDialog 的 accept 方法。
        当用户点击 "OK" 按钮时，先执行保存操作，然后再调用父类的 accept 方法关闭对话框。
        """
        self.save_settings()
        super().accept()