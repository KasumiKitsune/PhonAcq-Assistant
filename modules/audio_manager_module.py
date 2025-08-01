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

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
                             QHeaderView, QAbstractItemView, QMenu, QSplitter, QInputDialog, QLineEdit,
                             QSlider, QComboBox, QApplication, QGroupBox, QSpacerItem, QSizePolicy, QShortcut, QDialog, QDialogButtonBox, QFormLayout, QStyle, QStyleOptionSlider)
from PyQt5.QtCore import Qt, QTimer, QUrl, QRect, pyqtProperty, pyqtSignal
from PyQt5.QtGui import QIcon, QKeySequence, QPainter, QColor, QPen, QBrush, QPalette
from modules.custom_widgets_module import AnimatedListWidget, AnimatedSlider # [新增]
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
        self.parent_window = parent_window; self.config = config; self.BASE_PATH = base_path
        self.icon_manager = icon_manager; self.ToggleSwitch = ToggleSwitchClass
        self.DATA_SOURCES = data_sources
        self.current_session_path = None; self.current_data_type = None; self.current_displayed_duration = 0
        self.trim_start_ms = None; self.trim_end_ms = None; self.temp_preview_file = None

        # [新增] 初始化自定义数据源列表
        self.custom_data_sources = []

        # [重构] 使用播放器缓存池替代单一播放器
        self.player_cache = {}  # {filepath: QMediaPlayer_instance}
        self.active_player = None # 指向当前与UI交互的播放器
        self.preview_player = None
        self.staged_files = {} # 使用字典来存储 {filepath: display_name} 以防止重复添加
        # --- [新增] 用于搜索和排序的状态属性 ---
        self.all_files_data = []  # 存储当前文件夹下所有文件的完整信息
        self.current_sort_key = 'name'
        # self.current_sort_order = Qt.AscendingOrder # 此属性已被 sort_order_btn.isChecked() 替代
        # --- [新增结束] ---
        
        # --- [新增] 在此处加载持久化设置 ---
        module_states = self.config.get("module_states", {}).get("audio_manager", {})
        self.shortcut_button_action = module_states.get('shortcut_action', 'delete') # 默认是删除
        self.adaptive_volume_default_state = module_states.get('adaptive_volume', True) # 默认开启
        # --- 结束新增 ---
        
        self._init_ui()
        self._connect_signals()
        self.apply_layout_settings()
        
        # --- [修改] ---
        # 确保在程序启动时，按钮就有正确的图标
        self.update_icons() 
        # --- [修改结束] ---
        
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
        self.connect_staged_btn = QPushButton("连接")
        self.clear_staged_btn = QPushButton("清空")
        staging_btn_layout.addWidget(self.connect_staged_btn)
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
        self.sort_combo.addItems(["按名称排序", "按大小排序", "按修改日期排序"])
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
        self.audio_table_widget.verticalHeader().setVisible(False)
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
        self.play_pause_btn = QPushButton("")
        self.play_pause_btn.setMinimumWidth(80)
        self.play_pause_btn.setToolTip("播放或暂停当前选中的音频。")
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
        self.setFocusPolicy(Qt.StrongFocus)
        self.reset_player()

    def _connect_signals(self):
        # [核心修改] 使用 currentTextChanged 信号，这样可以处理用户输入和程序设置
        self.source_combo.currentTextChanged.connect(self.on_source_changed)

        # [新增] 连接右键菜单信号
        self.source_combo.customContextMenuRequested.connect(self.open_source_context_menu)

        self.session_list_widget.itemSelectionChanged.connect(self.on_session_selection_changed); self.session_list_widget.customContextMenuRequested.connect(self.open_folder_context_menu)
        self.session_list_widget.itemDoubleClicked.connect(self.on_session_item_double_clicked); self.play_pause_btn.clicked.connect(self.on_play_button_clicked)
        self.playback_slider.sliderMoved.connect(self.set_playback_position); self.volume_slider.valueChanged.connect(self._on_volume_slider_changed)
        self.adaptive_volume_switch.stateChanged.connect(self._on_adaptive_volume_toggled_and_save)
        self.audio_table_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.audio_table_widget.customContextMenuRequested.connect(self.open_file_context_menu); self.audio_table_widget.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.set_start_btn.clicked.connect(self._set_trim_start); self.set_end_btn.clicked.connect(self._set_trim_end)
        self.clear_trim_btn.clicked.connect(self._clear_trim_points); self.preview_trim_btn.clicked.connect(self._preview_trim)
        # 新增右键菜单信号连接
        self.save_trim_btn.customContextMenuRequested.connect(self._show_save_trim_menu)
        # 左键点击也弹出菜单，提供更直观的操作
        self.save_trim_btn.clicked.connect(lambda: self._show_save_trim_menu(self.save_trim_btn.rect().bottomLeft()))
        self.connect_staged_btn.clicked.connect(self._concatenate_staged_files)
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
                player = QMediaPlayer(); player.setNotifyInterval(16); player.setMedia(QMediaContent(QUrl.fromLocalFile(path))); self.player_cache[path] = player

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
        """[v2.2 健壮版] 安全地设置当前激活的播放器并连接UI。"""
        try:
            if self.active_player:
                # 在断开连接前，先检查对象是否还“活着”
                # 这是一个隐式检查，如果对象死了，访问属性就会抛出异常
                _ = self.active_player.state() 
                self.active_player.positionChanged.disconnect(self.update_playback_position)
                self.active_player.durationChanged.disconnect(self.update_playback_duration)
                self.active_player.stateChanged.disconnect(self.on_player_state_changed)
        except (RuntimeError, TypeError):
            # 对象已死或信号未连接，安全地忽略
            pass
        finally:
            # 无论如何，先将旧的Python引用清空
            self.active_player = None

        # 后续的加载新播放器和连接新信号的逻辑保持不变...
        new_player = self.player_cache.get(filepath)
        self.active_player = new_player
    
        if not self.active_player:
            self.reset_player_ui()
            return
        
        self.active_player.positionChanged.connect(self.update_playback_position)
        self.active_player.durationChanged.connect(self.update_playback_duration)
        self.active_player.stateChanged.connect(self.on_player_state_changed)
    
        self.update_playback_duration(self.active_player.duration())
        self.update_playback_position(self.active_player.position())
        self.on_player_state_changed(self.active_player.state())
        self._on_volume_slider_changed(self.volume_slider.value())

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
            
            # 正确顺序：先设置新播放器（它会安全地处理旧播放器），再更新缓存
            self.waveform_widget.set_waveform_data(filepath)
            self._set_active_player(filepath)      # <--- 步骤1: 安全地断开旧播放器的连接，并激活新播放器
            self._update_player_cache(current_row) # <--- 步骤2: 现在可以安全地清理缓存了
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
            # 确保在播放前，播放位置回到开头
            self.active_player.setPosition(0)
            self.active_player.play()

        
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
        if not self.playback_slider.isSliderDown(): self.playback_slider.setValue(position)
        total_duration = self.active_player.duration() if self.active_player else 0
        if total_duration > self.current_displayed_duration: self.update_playback_duration(total_duration)
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
        [重构] 根据指定的模式，对音频进行裁切并保存。
        新增 overwrite 参数以支持直接覆盖原文件。
        """
        # 1. 安全检查和获取基本信息 (保持不变)
        filepath = self.audio_table_widget.item(self.audio_table_widget.currentRow(), 0).data(Qt.UserRole)
        if not filepath: return
        
        data, sr = sf.read(filepath)
        total_samples = len(data)
        
        # 2. 根据模式计算需要保留的音频片段 (保持不变)
        final_data = None
        # ... (所有 if/elif mode == '...' 的逻辑保持不变)
        if mode == 'keep_selection':
            if self.trim_start_ms is None or self.trim_end_ms is None: return
            start_sample = int(self.trim_start_ms / 1000 * sr)
            end_sample = int(self.trim_end_ms / 1000 * sr)
            final_data = data[start_sample:end_sample]
        
        elif mode == 'trim_selection':
            if self.trim_start_ms is None or self.trim_end_ms is None: return
            start_sample = int(self.trim_start_ms / 1000 * sr)
            end_sample = int(self.trim_end_ms / 1000 * sr)
            part1 = data[:start_sample]
            part2 = data[end_sample:]
            final_data = np.concatenate((part1, part2))

        elif mode == 'trim_before':
            if self.trim_start_ms is None: return
            start_sample = int(self.trim_start_ms / 1000 * sr)
            final_data = data[start_sample:]
            
        elif mode == 'trim_after':
            if self.trim_end_ms is None: return
            end_sample = int(self.trim_end_ms / 1000 * sr)
            final_data = data[:end_sample]
        
        if final_data is None:
            QMessageBox.warning(self, "操作无效", "无法根据当前标记点执行该操作。")
            return
            
        # 3. 获取新文件名并保存 (核心修改点)
        target_filepath = ""
        if overwrite:
            # --- [修正后的覆盖逻辑] ---
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("确认覆盖原文件")
            msg_box.setText("您确定要用裁切后的版本直接覆盖原始文件吗？") # 主文本使用纯文本

            # 使用 setInformativeText 来显示包含HTML的详细信息
            informative_text = (
                f"<b>文件名:</b> {os.path.basename(filepath)}<br><br>"
                f"<font color='red'><b>此操作不可撤销！原始音频数据将永久丢失！</b></font>"
            )
            msg_box.setInformativeText(informative_text)
            
            # 确保Qt知道如何解析这段文本
            # 实际上，setInformativeText通常会自动检测，但明确设置更保险
            msg_box.setTextFormat(Qt.RichText)

            # 添加按钮
            msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg_box.setDefaultButton(QMessageBox.No) # 默认选择“No”更安全

            reply = msg_box.exec_() # 执行对话框

            if reply == QMessageBox.No:
                self.status_label.setText("覆盖操作已取消。")
                QTimer.singleShot(2000, lambda: self.status_label.setText("准备就绪"))
                return
            
            target_filepath = filepath
            # --- [覆盖逻辑结束] ---
        else:
            # --- [原有的“另存为”逻辑] ---
            base, ext = os.path.splitext(os.path.basename(filepath))
            suffix_map = {
                'keep_selection': '_selected',
                'trim_selection': '_trimmed',
                'trim_before': '_trimmed_start',
                'trim_after': '_trimmed_end'
            }
            suggested_name = f"{base}{suffix_map.get(mode, '_edited')}"
            
            new_name, ok = QInputDialog.getText(self, "保存裁切文件", "输入新文件名:", QLineEdit.Normal, suggested_name)
            if not (ok and new_name): return

            new_filepath = os.path.join(os.path.dirname(filepath), new_name + ext)
            if os.path.exists(new_filepath):
                QMessageBox.warning(self, "文件已存在", "该文件名已存在。")
                return
            target_filepath = new_filepath
            # --- [“另存为”逻辑结束] ---

        # 4. 执行文件写入
        if not target_filepath: return
        
        try:
            # [关键] 写入前，先重置播放器以释放文件句柄
            # 这在覆盖操作中至关重要，否则Windows下会报“文件被占用”的错误
            self.reset_player()
            QApplication.processEvents() # 确保事件循环处理完播放器停止的请求
            
            sf.write(target_filepath, final_data, sr)

            if overwrite:
                QMessageBox.information(self, "成功", f"原文件已成功覆盖！")
                # 因为文件内容变了，波形图需要刷新
                self.waveform_widget.set_waveform_data(target_filepath)
            else:
                QMessageBox.information(self, "成功", f"文件已保存为:\n{target_filepath}")
            
            # 无论哪种模式，都刷新文件列表
            self.populate_audio_table()
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
        [修改后] 构建文件列表的右键上下文菜单。
        """
        selected_items = self.audio_table_widget.selectedItems()
        if not selected_items:
            return

        # 获取选中的不重复行数和文件路径 (这部分逻辑不变)
        selected_rows = sorted(list(set(item.row() for item in selected_items)))
        selected_filepaths = [self.audio_table_widget.item(row, 0).data(Qt.UserRole) for row in selected_rows]
        selected_rows_count = len(selected_rows)

        menu = QMenu(self.audio_table_widget)

        # --- 标准操作 (保持不变) ---
        play_action = menu.addAction(self.icon_manager.get_icon("play_audio"), "试听 / 暂停")
        if selected_rows_count == 1:
            play_action.triggered.connect(lambda: self.play_selected_item(selected_rows[0]))
        else:
            play_action.setEnabled(False)

        # --- [核心修改开始] ---

        # 1. 检查音频分析模块是否已加载 (这是我们的“钩子”)
        #    我们通过检查主窗口是否存在 audio_analysis_page 属性来判断
        analysis_module_available = hasattr(self.parent_window, 'audio_analysis_page') and self.parent_window.audio_analysis_page is not None

        # 2. 创建菜单项
        analyze_action = menu.addAction(self.icon_manager.get_icon("analyze"), "在音频分析中打开")
        
        # 3. 根据模块可用性和选择数量来设置菜单项状态
        analyze_action.setEnabled(analysis_module_available and selected_rows_count == 1)
        
        # 4. 设置有用的工具提示，告知用户为什么不可用
        if not analysis_module_available:
            analyze_action.setToolTip("音频分析模块未加载或初始化失败。")
        elif selected_rows_count != 1:
            analyze_action.setToolTip("请只选择一个音频文件进行分析。")
        else:
            # 当可用时，连接信号到新的辅助方法
            # 使用 partial 来传递文件路径，避免 lambda 作用域问题
            from functools import partial
            analyze_action.triggered.connect(partial(self.send_to_audio_analysis, selected_filepaths[0]))
        
        # --- [核心修改结束] ---
        
        menu.addSeparator()

        add_to_staging_action = menu.addAction(self.icon_manager.get_icon("add_row"), f"将 {selected_rows_count} 个文件添加到暂存区")
        add_to_staging_action.triggered.connect(self._add_selected_to_staging)
    
        # --- 批量处理器插件入口 (保持不变) ---
        if hasattr(self, 'batch_processor_plugin_active'):
            # [修改] 使用一个子菜单来组织插件的功能
            processor_menu = menu.addMenu(self.icon_manager.get_icon("submit"), "批量处理")

            # 原有的功能：打开完整对话框
            open_dialog_action = processor_menu.addAction(self.icon_manager.get_icon("options"), f"高级处理 ({selected_rows_count} 个文件)...")
            open_dialog_action.triggered.connect(self._send_to_batch_processor)

            # [新增] 新的快捷功能
            quick_normalize_action = processor_menu.addAction(self.icon_manager.get_icon("wand"), "一键标准化")
            quick_normalize_action.setToolTip(
                "将选中的文件标准化 (WAV, 44.1kHz, 单声道, RMS) 并直接覆盖原文件。\n"
                "此操作不可撤销，请谨慎使用！"
            )
            # 将其 triggered 信号连接到一个新的辅助方法
            quick_normalize_action.triggered.connect(self._run_quick_normalize)

        # --- [核心修改] 新的外部工具启动器插件入口 ---
        # 1. 检查钩子是否存在
        if hasattr(self, 'external_launcher_plugin_active'):
            launcher_plugin = self.external_launcher_plugin_active
        
            # 2. 调用插件的API来填充菜单
            #    插件内部会根据文件类型决定是否添加菜单项
            launcher_plugin.populate_menu(menu, selected_filepaths)
        # --- [修改结束] ---

        menu.addSeparator()

        # --- 其他标准操作 (保持不变) ---
        rename_action = menu.addAction(self.icon_manager.get_icon("rename"), "重命名")
        if selected_rows_count == 1:
            rename_action.triggered.connect(lambda: self.rename_selected_file(selected_rows[0]))
        else:
            rename_action.setEnabled(False)
        
        delete_action = menu.addAction(self.icon_manager.get_icon("delete"), f"删除选中的 {selected_rows_count} 个文件")
        delete_action.triggered.connect(self.delete_selected_files)
    
        menu.addSeparator()
    
        open_folder_action = menu.addAction(self.icon_manager.get_icon("show_in_explorer"), "在文件浏览器中显示")
        if selected_rows_count == 1:
            folder_path = os.path.dirname(selected_filepaths[0])
            file_name = os.path.basename(selected_filepaths[0])
            open_folder_action.triggered.connect(lambda: self.open_in_explorer(folder_path, select_file=file_name))
        else:
            open_folder_action.setEnabled(False)

        # --- 快捷按钮设置 (保持不变) ---
        menu.addSeparator()
        shortcut_menu = menu.addMenu(self.icon_manager.get_icon("draw"), "设置快捷按钮")
        # ... (这部分逻辑完全不变)
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
        调用主窗口的公共API来切换到音频分析模块并加载文件。
        """
        # 再次进行安全检查
        if not (hasattr(self.parent_window, 'go_to_audio_analysis') and callable(self.parent_window.go_to_audio_analysis)):
            QMessageBox.critical(self, "功能缺失", "主程序缺少必要的跳转功能 (go_to_audio_analysis)。")
            return
            
        self.parent_window.go_to_audio_analysis(filepath)

    def delete_selected_files(self):
        """
        [新增] 删除所有在表格中被选中的文件。
        """
        # 1. 获取所有选中的、不重复的文件路径
        selected_items = self.audio_table_widget.selectedItems()
        if not selected_items:
            return
            
        selected_filepaths = sorted(list(set(
            self.audio_table_widget.item(i.row(), 0).data(Qt.UserRole) for i in selected_items
        )))
        
        count = len(selected_filepaths)
        
        # 2. 弹窗向用户进行最终确认
        # 显示前几个文件名作为示例
        file_examples = "\n".join(f"- {os.path.basename(p)}" for p in selected_filepaths[:3])
        if count > 3:
            file_examples += "\n- ..."
            
        reply = QMessageBox.question(self, "确认删除", 
                                     f"您确定要永久删除这 {count} 个文件吗？\n\n{file_examples}\n\n此操作不可撤销！", 
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.No:
            return

        # 3. 准备删除操作
        error_files = []
        self.status_label.setText(f"正在删除 {count} 个文件...")
        QApplication.processEvents()

        # [关键] 在删除任何文件之前，重置所有播放器以释放文件句柄
        self.reset_player()
        QApplication.processEvents() # 确保事件循环处理完播放器停止的请求

        # 4. 循环删除文件
        for i, filepath in enumerate(selected_filepaths):
            filename = os.path.basename(filepath)
            self.status_label.setText(f"正在删除 ({i+1}/{count}): {filename}")
            QApplication.processEvents()
            
            try:
                os.remove(filepath)
            except Exception as e:
                error_files.append(f"{filename}: {e}")
        
        # 5. 报告结果
        if error_files:
            error_details = "\n".join(error_files)
            QMessageBox.critical(self, "部分文件删除失败", f"以下文件未能成功删除:\n\n{error_details}")
            self.status_label.setText("部分文件删除失败。")
        else:
            self.status_label.setText(f"成功删除 {count} 个文件。")
            QTimer.singleShot(4000, lambda: self.status_label.setText("准备就绪"))

        # 6. 刷新UI
        self.populate_audio_table()
        # [可选] 刷新后，如果列表不为空，可以自动选中第一项
        if self.audio_table_widget.rowCount() > 0:
            self.audio_table_widget.setCurrentCell(0, 0)

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
        self.connect_staged_btn.setIcon(self.icon_manager.get_icon("concatenate"))
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
        self.apply_layout_settings()
        self.update_icons()

        # 1. 加载自定义源
        self.custom_data_sources = self.config.get("file_settings", {}).get("custom_data_sources", [])

        # 2. 填充下拉框
        self.source_combo.blockSignals(True)
        current_text = self.source_combo.currentText()
        self.source_combo.clear()

        # 添加内置源
        for name in self.DATA_SOURCES.keys():
            self.source_combo.addItem(name)
        
        if self.custom_data_sources:
            self.source_combo.insertSeparator(self.source_combo.count())
            for source in self.custom_data_sources:
                # 使用图标来区分自定义源
                self.source_combo.addItem(self.icon_manager.get_icon("folder"), source['name'])

        # 添加特殊操作项
        self.source_combo.insertSeparator(self.source_combo.count())
        self.source_combo.addItem(self.icon_manager.get_icon("duplicate_row"), "< 添加/管理自定义源... >")
        
        # 尝试恢复之前的选择
        index = self.source_combo.findText(current_text)
        if index != -1:
            self.source_combo.setCurrentIndex(index)
        
        self.source_combo.blockSignals(False)

        # 触发一次刷新
        self.on_source_changed(self.source_combo.currentText())

    # [新增] on_source_changed 槽函数，替代 populate_session_list
    def on_source_changed(self, text):
        if text == "< 添加/管理自定义源... >":
            self._manage_custom_sources() # 调用新的管理方法
            return
    
        self.populate_session_list()

    # [重构] populate_session_list 现在只负责填充列表，数据源由 on_source_changed 决定
    def populate_session_list(self):
        source_name = self.source_combo.currentText()
        source_info = self.DATA_SOURCES.get(source_name)
        is_custom = False

        if not source_info:
            # 如果不是内置源，就从自定义源中查找
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

        self.session_active = False; self.reset_player()
        current_text = self.session_list_widget.currentItem().text() if self.session_list_widget.currentItem() else None
        self.session_list_widget.clear()
        
        base_path = source_info["path"]
        
        if not os.path.exists(base_path):
            if is_custom:
                self.session_list_widget.addItem(f"错误: 路径不存在\n{base_path}")
            else:
                os.makedirs(base_path, exist_ok=True)
            return

        try:
            # 这里的 filter 应该应用于 os.listdir 的结果，而不是 os.path.isdir
            # 并且需要确保只列出目录
            sessions = sorted([d for d in os.listdir(base_path) if source_info["filter"](d, base_path)], 
                              key=lambda s: os.path.getmtime(os.path.join(base_path, s)), reverse=True)
            self.session_list_widget.addItemsWithAnimation(sessions)
            if current_text:
                items = self.session_list_widget.findItems(current_text, Qt.MatchFixedString)
                if items: self.session_list_widget.setCurrentItem(items[0])
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载项目列表失败: {e}")

    # [新增] 添加自定义源的逻辑
    def _manage_custom_sources(self):
        # 记录下在打开对话框之前，用户实际选择的数据源是什么
        previous_source_name = self.source_combo.currentText()
        if previous_source_name == "< 添加/管理自定义源... >":
            # 如果用户直接点击的管理项，我们没有一个“之前”的源，就默认回到第一个
            previous_source_name = self.source_combo.itemText(0)

        dialog = ManageSourcesDialog(self.custom_data_sources, self, self.icon_manager)
    
        if dialog.exec_() == QDialog.Accepted:
            updated_sources = dialog.sources
        
            # 只有在数据源实际发生变化时才保存和刷新
            if updated_sources != self.custom_data_sources:
                self.custom_data_sources = updated_sources
            
                file_settings = self.config.setdefault("file_settings", {})
                file_settings["custom_data_sources"] = self.custom_data_sources
                self.parent_window.update_and_save_module_state("file_settings", file_settings)
            
                # [核心修正] 在刷新前，先将下拉框重置到一个安全的位置
                self.source_combo.blockSignals(True)
                # 找到之前的数据源并选中它，如果找不到了就回到第一个
                index_to_restore = self.source_combo.findText(previous_source_name)
                self.source_combo.setCurrentIndex(index_to_restore if index_to_restore != -1 else 0)
                self.source_combo.blockSignals(False)

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
        
    def populate_audio_table(self):
        """
        [重构] 第一阶段：加载所有文件数据到 self.all_files_data 中。
        """
        self.reset_player()
        self.waveform_widget.clear()
        self.audio_table_widget.setRowCount(0)
        self.all_files_data.clear() # 清空旧数据

        if not self.current_session_path:
            return

        try:
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
                            'mtime': stat.st_mtime # 修改时间 (float)
                        })
                    except OSError:
                        continue # 忽略无法访问的文件
            
            # 加载完成后，立即进行一次排序和渲染
            self.on_sort_changed() # 这会触发排序和渲染

        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载音频文件列表失败: {e}")
     
    def on_sort_order_changed(self, checked):
        """
        [新增] 当排序顺序按钮被点击时调用。
        """
        # 仅仅是更新UI和重新触发排序渲染即可
        self.update_icons() # 更新按钮图标（升序/降序）
        self.filter_and_render_files() # 使用新的顺序重新排序和渲染列表

    def on_sort_changed(self):
        """
        [重构] 当排序方式（名称、大小、日期）变化时调用。
        """
        sort_text = self.sort_combo.currentText()
        if "名称" in sort_text:
            self.current_sort_key = 'name'
            # 默认按名称升序
            self.sort_order_btn.setChecked(False) 
        elif "大小" in sort_text:
            self.current_sort_key = 'size'
            # 默认按大小降序
            self.sort_order_btn.setChecked(True)
        elif "日期" in sort_text:
            self.current_sort_key = 'mtime'
            # 默认按日期降序
            self.sort_order_btn.setChecked(True)
        
        # 注意：这里我们不再调用 filter_and_render_files()，
        # 因为 setChecked() 会触发 on_sort_order_changed，
        # 从而避免了重复渲染。
        # 如果 setChecked() 的状态没有改变，我们手动调用一次以确保更新。
        # 为简单起见，我们直接调用它。
        self.filter_and_render_files()

    def filter_and_render_files(self):
        """
        [重构] 基于当前搜索词和排序规则，处理并显示文件。
        """
        # 1. 排序
        # --- [核心修改] ---
        # 直接从按钮的 checked 状态判断是升序还是降序
        is_reverse = self.sort_order_btn.isChecked()
        # --- [修改结束] ---

        sorted_files = sorted(self.all_files_data, key=lambda x: x[self.current_sort_key], reverse=is_reverse)

        # 2. 搜索/筛选 (这部分逻辑保持不变)
        search_term = self.search_input.text().lower()
        if search_term:
            files_to_display = [f for f in sorted_files if search_term in f['name'].lower()]
        else:
            files_to_display = sorted_files
            
        # 3. 渲染到表格 (这部分逻辑保持不变)
        self.render_to_table(files_to_display)

    def render_to_table(self, files_data):
        """
        [新增] 第三阶段：将处理好的数据模型渲染到 QTableWidget 中。
        """
        self.audio_table_widget.setRowCount(0) # 先清空
        self.audio_table_widget.setRowCount(len(files_data))
        
        for row, file_info in enumerate(files_data):
            self.update_table_row(row, file_info['path']) # 复用已有的行更新方法
            
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
            shortcut_btn.setToolTip("快捷操作：试听此文件")
            shortcut_btn.clicked.connect(lambda _, r=row: self.play_selected_item(r))
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
        if state == QMediaPlayer.PlayingState: self.play_pause_btn.setText("暂停"); self.play_pause_btn.setIcon(self.icon_manager.get_icon("pause"))
        else: self.play_pause_btn.setText("播放"); self.play_pause_btn.setIcon(self.icon_manager.get_icon("play"))
        if state == QMediaPlayer.StoppedState: self.play_pause_btn.setEnabled(False if not self.active_player else True)
        elif state == QMediaPlayer.PausedState: self.play_pause_btn.setEnabled(True)
        else: self.play_pause_btn.setEnabled(True)
        if state == QMediaPlayer.EndOfMedia and self.active_player: self.playback_slider.setValue(0); self.duration_label.setText(f"00:00.00 / {self.format_time(self.active_player.duration())}")
        
    def on_item_double_clicked(self, item): self.play_selected_item(item.row())
    
    def on_session_selection_changed(self):
        selected_items = self.session_list_widget.selectedItems()
        if not selected_items: self.audio_table_widget.setRowCount(0); self.table_label.setText("请从左侧选择一个项目以查看文件"); self.session_active = False; self.reset_player(); return
        
        # 获取当前选中的数据源类型，判断是内置还是自定义
        source_name = self.source_combo.currentText()
        source_info = self.DATA_SOURCES.get(source_name)
        
        if not source_info: # 可能是自定义源
            for custom_source in self.custom_data_sources:
                if custom_source['name'] == source_name:
                    source_info = {"path": custom_source['path']} # 只需要路径
                    break
        
        if not source_info: # 仍然没有找到，说明数据源无效
            self.audio_table_widget.setRowCount(0)
            self.table_label.setText("无效的数据源")
            self.session_active = False
            self.reset_player()
            return

        self.session_active = True
        self.current_session_path = os.path.join(source_info["path"], selected_items[0].text())
        self.table_label.setText(f"项目: {selected_items[0].text()}"); self.populate_audio_table()
        
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
        selected_items = self.session_list_widget.selectedItems();
        if not selected_items: return
        menu = QMenu(self.audio_table_widget); delete_action = menu.addAction(self.icon_manager.get_icon("delete"), f"删除选中的 {len(selected_items)} 个项目"); rename_action = menu.addAction(self.icon_manager.get_icon("rename"), "重命名"); rename_action.setEnabled(len(selected_items) == 1); menu.addSeparator()
        open_folder_action = menu.addAction(self.icon_manager.get_icon("open_folder"), "在文件浏览器中打开"); open_folder_action.setEnabled(len(selected_items) == 1); action = menu.exec_(self.session_list_widget.mapToGlobal(position))
        
        # 获取当前选中的数据源类型，判断是内置还是自定义
        source_name = self.source_combo.currentText()
        base_dir = None
        
        # 优先从内置数据源查找
        if source_name in self.DATA_SOURCES:
            base_dir = self.DATA_SOURCES[source_name]["path"]
        else: # 从自定义数据源查找
            for custom_source in self.custom_data_sources:
                if custom_source['name'] == source_name:
                    base_dir = custom_source['path']
                    break
        
        if not base_dir: # 如果没有找到对应的base_dir，则无法执行操作
            QMessageBox.warning(self, "错误", "无法确定数据源路径。")
            return

        if action == delete_action: self.delete_folders(selected_items, base_dir)
        elif action == getattr(self, 'last_praat_action', None) and action is not None:
            self._send_to_external_launcher()
        elif action == rename_action: self.rename_folder(selected_items[0], base_dir)
        elif action == open_folder_action: self.open_in_explorer(os.path.join(base_dir, selected_items[0].text()))
        
    def delete_folders(self, items, base_dir):
        count = len(items); reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除选中的 {count} 个项目及其所有内容吗？\n此操作不可撤销！", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.status_label.setText(f"正在删除 {count} 个项目...")
            QApplication.processEvents(); error_occurred = False
            for item in items:
                try:
                    self.status_label.setText(f"正在删除: {item.text()}...")
                    QApplication.processEvents()
                    shutil.rmtree(os.path.join(base_dir, item.text()))
                except Exception as e:
                    error_message = f"删除 '{item.text()}' 时出错。"
                    self.status_label.setText(error_message)
                    QMessageBox.critical(self, "删除失败", f"{error_message}\n{e}")
                    error_occurred = True
                    break
            if not error_occurred:
                success_message = f"成功删除 {count} 个项目。"
                self.status_label.setText(success_message)
                QTimer.singleShot(4000, lambda: self.status_label.setText("准备就绪"))
            self.populate_session_list()
            
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
        
    def delete_file(self, filepath):
        filename = os.path.basename(filepath)
        reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除文件 '{filename}' 吗？\n此操作不可撤销。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            try:
                # 1. 首先，完全重置所有播放器，释放所有文件句柄
                self.reset_player()
                QApplication.processEvents()

                # 2. 现在可以安全地删除文件
                os.remove(filepath)

                # 3. [修复] 在刷新表格前，阻塞可能引发问题的信号
                self.audio_table_widget.blockSignals(True)
                
                self.populate_audio_table()
                
                # 4. 刷新完成后，解除信号阻塞
                self.audio_table_widget.blockSignals(False)

                # 5. [可选但推荐] 手动触发一次选中事件，以恢复UI状态
                # 因为阻塞期间可能丢失了默认的选中事件
                if self.audio_table_widget.rowCount() > 0:
                    self.audio_table_widget.setCurrentCell(0, 0)
                    self._on_table_selection_changed() # 手动调用
                else:
                    # 如果表格空了，确保所有相关UI都重置
                    self.reset_player_ui()

            except Exception as e:
                QMessageBox.critical(self, "删除失败", f"删除文件时出错:\n{e}")
                # 出错后，最好也解除阻塞
                self.audio_table_widget.blockSignals(False)
    def reset_player_ui(self):
        self.playback_slider.setValue(0)
        self.playback_slider.setEnabled(False)
        self.duration_label.setText("00:00.00 / 00:00.00")
        self.play_pause_btn.setEnabled(False)
        self.on_player_state_changed(QMediaPlayer.StoppedState)
        self.waveform_widget.clear()
        self._clear_trim_points()
            
    def on_play_button_clicked(self):
        if self.active_player and self.active_player.state() in [QMediaPlayer.PlayingState, QMediaPlayer.PausedState]: self.toggle_playback()
        else:
            current_row = self.audio_table_widget.currentRow()
            if current_row != -1: self.play_selected_item(current_row)
            
    def toggle_playback(self):
        if not self.active_player: return
        if self.active_player.state() == QMediaPlayer.PlayingState: self.active_player.pause()
        else: self.active_player.play()
        
    def update_playback_duration(self, duration):
        if self.active_player and duration > 0 and duration != self.current_displayed_duration:
            self.current_displayed_duration = duration; self.playback_slider.setRange(0, duration); self.duration_label.setText(f"{self.format_time(self.active_player.position())} / {self.format_time(duration)}")
            self.playback_slider.setEnabled(True)
            
    def set_playback_position(self, position):
        if self.active_player: self.active_player.setPosition(position)
        
    def format_time(self, ms):
        if ms <= 0: return "00:00.00"
        total_seconds = ms / 1000.0; m, s_frac = divmod(total_seconds, 60); s_int = int(s_frac); cs = int(round((s_frac - s_int) * 100));
        if cs == 100: cs = 0; s_int +=1
        if s_int == 60: s_int = 0; m += 1
        return f"{int(m):02d}:{s_int:02d}.{cs:02d}"
        
    def reset_player(self):
        """[v2.2 健壮版] 安全地重置所有播放器和UI。"""
        try:
            if self.preview_player:
                self.preview_player.stop()
        except RuntimeError:
            pass
        finally:
            self.preview_player = None
    
        # 调用已经加固过的清理方法
        self._clear_player_cache()
    
        self.playback_slider.setValue(0)
        self.playback_slider.setEnabled(False)
        self.duration_label.setText("00:00.00 / 00:00.00")
        self.on_player_state_changed(QMediaPlayer.StoppedState)
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