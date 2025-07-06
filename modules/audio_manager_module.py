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

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
                             QHeaderView, QAbstractItemView, QMenu, QSplitter, QInputDialog, QLineEdit,
                             QSlider, QComboBox, QApplication, QGroupBox, QSpacerItem, QSizePolicy, QShortcut, QDialog, QDialogButtonBox, QFormLayout, QStyle, QStyleOptionSlider)
from PyQt5.QtCore import Qt, QTimer, QUrl, QRect, pyqtProperty, pyqtSignal
from PyQt5.QtGui import QIcon, QKeySequence, QPainter, QColor, QPen, QBrush, QPalette

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
    def __init__(self, filepaths, parent=None, icon_manager=None):
        super().__init__(parent)
        self.icon_manager = icon_manager
        self.setWindowTitle("连接并重排音频")
        self.setMinimumSize(450, 300)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("请拖动文件以调整顺序，并输入新文件名:"))

        # 文件列表
        self.file_list = QListWidget()
        self.file_list.setDragDropMode(QAbstractItemView.InternalMove) # 启用拖放排序
        self.file_list.addItems([os.path.basename(p) for p in filepaths])
        self.original_paths = filepaths # 保存原始路径以供重排
        
        # 移动按钮
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
        
        # 确定/取消按钮
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        layout.addWidget(self.file_list)
        layout.addLayout(button_layout)
        layout.addLayout(form_layout)
        layout.addWidget(self.button_box)

        self._connect_signals()
        self._update_icons()

    def _connect_signals(self):
        self.up_button.clicked.connect(self.move_up)
        self.down_button.clicked.connect(self.move_down)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def _update_icons(self):
        if self.icon_manager:
            self.up_button.setIcon(self.icon_manager.get_icon("move_up"))
            self.down_button.setIcon(self.icon_manager.get_icon("move_down"))

    def move_up(self):
        current_row = self.file_list.currentRow()
        if current_row > 0:
            item = self.file_list.takeItem(current_row)
            self.file_list.insertItem(current_row - 1, item)
            self.file_list.setCurrentRow(current_row - 1)

    def move_down(self):
        current_row = self.file_list.currentRow()
        if current_row < self.file_list.count() - 1:
            item = self.file_list.takeItem(current_row)
            self.file_list.insertItem(current_row + 1, item)
            self.file_list.setCurrentRow(current_row + 1)
            
    def get_reordered_paths_and_name(self):
        # 根据当前 QListWidget 中的顺序，重构文件路径列表
        reordered_filenames = [self.file_list.item(i).text() for i in range(self.file_list.count())]
        
        # 创建一个从文件名到原始完整路径的映射
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

        self._waveformColor = self.palette().color(QPalette.Highlight)
        self._cursorColor = QColor("red")
        self._selectionColor = QColor(0, 100, 255, 60)
        self.is_scrubbing = False

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
        self.clear()
        if not (audio_filepath and os.path.exists(audio_filepath)): self.update(); return
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
        except Exception as e: print(f"Error loading waveform: {e}"); self._waveform_data = None
        self.update()
        
    def update_playback_position(self, current_ms, total_ms):
        self._playback_pos_ratio = current_ms / total_ms if total_ms > 0 else 0.0
        self.update()

    def set_trim_points(self, start_ms, end_ms, total_ms):
        self._trim_start_ratio = start_ms / total_ms if start_ms is not None and total_ms > 0 else -1.0
        self._trim_end_ratio = end_ms / total_ms if end_ms is not None and total_ms > 0 else -1.0
        self.update()

    def clear(self):
        self._waveform_data = None; self._playback_pos_ratio = 0.0
        self._trim_start_ratio = -1.0; self._trim_end_ratio = -1.0
        self.update()

    # [重构] 完整的鼠标事件处理
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_scrubbing = True
            self._handle_scrub(event.pos())
            event.accept()
        elif event.button() == Qt.RightButton:
            # 右键点击，发射请求标记的信号
            ratio = event.x() / self.width()
            if 0 <= ratio <= 1:
                self.marker_requested_at_ratio.emit(ratio)
            event.accept()
        elif event.button() == Qt.MiddleButton:
            # 中键点击，发射请求清除标记的信号
            self.clear_markers_requested.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_scrubbing:
            self._handle_scrub(event.pos())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_scrubbing = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    # [新增] 辅助方法，用于处理寻轨逻辑
    def _handle_scrub(self, pos):
        # 计算点击位置在宽度上的比例 (0.0 to 1.0)
        ratio = pos.x() / self.width()
        # 确保比例在有效范围内
        clamped_ratio = max(0.0, min(1.0, ratio))
        # 发射信号，将比例传递出去
        self.clicked_at_ratio.emit(clamped_ratio)

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

        # [重构] 使用播放器缓存池替代单一播放器
        self.player_cache = {}  # {filepath: QMediaPlayer_instance}
        self.active_player = None # 指向当前与UI交互的播放器
        self.preview_player = None
        self.staged_files = {} # 使用字典来存储 {filepath: display_name} 以防止重复添加
        # --- [新增] 在此处加载持久化设置 ---
        module_states = self.config.get("module_states", {}).get("audio_manager", {})
        self.shortcut_button_action = module_states.get('shortcut_action', 'delete') # 默认是删除
        self.adaptive_volume_default_state = module_states.get('adaptive_volume', True) # 默认开启
        # --- 结束新增 ---
        
        self._init_ui()
        self._connect_signals()
        self.update_icons()
        self.apply_layout_settings()
        
    def _init_ui(self):
        main_splitter = QSplitter(Qt.Horizontal, self)
        self.left_panel = QWidget(); left_layout = QVBoxLayout(self.left_panel)
        left_layout.addWidget(QLabel("选择数据源:")); self.source_combo = QComboBox(); self.source_combo.addItems(self.DATA_SOURCES.keys()); self.source_combo.setToolTip("选择要查看的数据类型。")
        left_layout.addWidget(self.source_combo); left_layout.addWidget(QLabel("项目列表:"))
        self.session_list_widget = QListWidget(); self.session_list_widget.setContextMenuPolicy(Qt.CustomContextMenu); self.session_list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.session_list_widget.setToolTip("双击可直接在文件浏览器中打开。\n右键可进行批量操作。"); left_layout.addWidget(self.session_list_widget, 1)
        # [新增] 音频暂存区 UI
        staging_group = QGroupBox("音频暂存区")
        staging_group.setToolTip("一个临时的区域，用于收集来自不同文件夹的音频以进行连接。")
        staging_layout = QVBoxLayout(staging_group)
        
        self.staging_list_widget = QListWidget()
        self.staging_list_widget.setToolTip("当前已暂存的音频文件。\n可在此处预览顺序。")
        
        staging_btn_layout = QHBoxLayout()
        self.connect_staged_btn = QPushButton("连接音频")
        self.connect_staged_btn.setObjectName("")
        self.clear_staged_btn = QPushButton("清空")

        staging_btn_layout.addWidget(self.connect_staged_btn)
        staging_btn_layout.addWidget(self.clear_staged_btn)
        
        staging_layout.addWidget(self.staging_list_widget)
        staging_layout.addLayout(staging_btn_layout)
        
        left_layout.addWidget(staging_group)
        # [新增] 在左下角添加本地状态标签
        self.status_label = QLabel("准备就绪")
        self.status_label.setObjectName("StatusLabelModule") # 与其他模块保持一致
        self.status_label.setMinimumHeight(25)
        self.status_label.setWordWrap(True)
        left_layout.addWidget(self.status_label)

        left_layout.setStretchFactor(self.session_list_widget, 2) # 让会话列表占更多空间
        left_layout.setStretchFactor(staging_group, 1) # 让暂存区占较少空间
        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel)
        self.table_label = QLabel("请从左侧选择一个项目以查看文件"); self.table_label.setAlignment(Qt.AlignCenter)
        self.audio_table_widget = QTableWidget(); self.audio_table_widget.setColumnCount(4); self.audio_table_widget.setHorizontalHeaderLabels(["文件名", "文件大小", "修改日期", ""]); self.audio_table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.audio_table_widget.setSelectionBehavior(QAbstractItemView.SelectRows); self.audio_table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers); self.audio_table_widget.verticalHeader().setVisible(False); self.audio_table_widget.setAlternatingRowColors(True)
        self.audio_table_widget.setContextMenuPolicy(Qt.CustomContextMenu); self.audio_table_widget.setColumnWidth(1, 120); self.audio_table_widget.setColumnWidth(2, 180); self.audio_table_widget.setColumnWidth(3, 80)
        self.audio_table_widget.setToolTip("双击或按Enter键可播放，右键可进行更多操作。")
        playback_v_layout = QVBoxLayout(); playback_v_layout.setContentsMargins(0, 5, 0, 5)
        playback_h_layout = QHBoxLayout()
        self.play_pause_btn = QPushButton(""); self.play_pause_btn.setMinimumWidth(80); self.play_pause_btn.setToolTip("播放或暂停当前选中的音频。")
        self.playback_slider = ClickableSlider(Qt.Horizontal)
        self.playback_slider.setToolTip("显示当前播放进度，可拖动或点击以跳转。")
        volume_layout = QHBoxLayout(); volume_layout.setSpacing(5)
        # [修改] 在创建 adaptive_volume_switch 后，设置其加载好的状态
        self.adaptive_volume_switch = self.ToggleSwitch()
        self.adaptive_volume_switch.setToolTip("开启后，将根据音频响度自动调整初始音量。")
        self.adaptive_volume_switch.setChecked(self.adaptive_volume_default_state) # <-- 在此应用加载的状态
        volume_layout.addWidget(self.adaptive_volume_switch); volume_layout.addWidget(QLabel("自适应"))
        self.volume_label = QLabel("音量:"); self.volume_slider = QSlider(Qt.Horizontal); self.volume_slider.setFixedWidth(120); self.volume_slider.setRange(0, 100); self.volume_slider.setValue(100); self.volume_slider.setToolTip("调整播放音量。")
        self.volume_percent_label = QLabel("100%"); volume_layout.addWidget(self.volume_label); volume_layout.addWidget(self.volume_slider); volume_layout.addWidget(self.volume_percent_label)
        playback_h_layout.addWidget(self.play_pause_btn); playback_h_layout.addWidget(self.playback_slider, 10); playback_h_layout.addStretch(1); playback_h_layout.addLayout(volume_layout)
        waveform_time_layout = QHBoxLayout(); self.waveform_widget = WaveformWidget(); self.duration_label = QLabel("00:00.00 / 00:00.00")
        waveform_time_layout.addWidget(self.waveform_widget, 10); waveform_time_layout.addWidget(self.duration_label)
        playback_v_layout.addLayout(playback_h_layout); playback_v_layout.addLayout(waveform_time_layout)
        self.edit_panel_container = QWidget(); container_layout = QVBoxLayout(self.edit_panel_container); container_layout.setContentsMargins(0,0,0,0)
        self.edit_panel = QGroupBox("音频编辑")
        edit_controls_layout = QHBoxLayout(self.edit_panel)
        edit_controls_layout.setSpacing(10)
        
        self.trim_start_label = QLabel("起点: --:--.--")
        self.set_start_btn = QPushButton("起点")
        # [修改] 更新 Tooltip
        self.set_start_btn.setToolTip("将当前播放位置标记为裁切起点。\n快捷键：在波形图上右键单击。")
        
        self.set_end_btn = QPushButton("终点")
        # [修改] 更新 Tooltip
        self.set_end_btn.setToolTip("将当前播放位置标记为裁切终点。\n快捷键：在波形图上再次右键单击。")
        
        self.trim_end_label = QLabel("终点: --:--.--")
        
        self.clear_trim_btn = QPushButton("清除")
        # [修改] 更新 Tooltip
        self.clear_trim_btn.setToolTip("清除已标记的起点和终点。\n快捷键：在波形图上中键单击。")
        self.preview_trim_btn = QPushButton("预览"); self.preview_trim_btn.setToolTip("试听当前标记范围内的音频。")
        self.save_trim_btn = QPushButton("保存"); self.save_trim_btn.setToolTip("将裁切后的音频另存为新文件。"); self.save_trim_btn.setObjectName("AccentButton")
        edit_controls_layout.addWidget(self.trim_start_label); edit_controls_layout.addWidget(self.set_start_btn); edit_controls_layout.addWidget(self.set_end_btn); edit_controls_layout.addWidget(self.trim_end_label)
        edit_controls_layout.addStretch(1); edit_controls_layout.addWidget(self.clear_trim_btn); edit_controls_layout.addWidget(self.preview_trim_btn); edit_controls_layout.addWidget(self.save_trim_btn)
        container_layout.addWidget(self.edit_panel); self.edit_panel_container.setVisible(False)
        right_layout.addWidget(self.table_label); right_layout.addWidget(self.audio_table_widget, 1); right_layout.addWidget(self.edit_panel_container); right_layout.addLayout(playback_v_layout)
        main_splitter.addWidget(self.left_panel); main_splitter.addWidget(right_panel); main_splitter.setStretchFactor(0, 1); main_splitter.setStretchFactor(1, 3)
        page_layout = QHBoxLayout(self); page_layout.addWidget(main_splitter); self.setFocusPolicy(Qt.StrongFocus)
        self.reset_player()

    def _connect_signals(self):
        self.source_combo.currentTextChanged.connect(self.populate_session_list)
        self.session_list_widget.itemSelectionChanged.connect(self.on_session_selection_changed); self.session_list_widget.customContextMenuRequested.connect(self.open_folder_context_menu)
        self.session_list_widget.itemDoubleClicked.connect(self.on_session_item_double_clicked); self.play_pause_btn.clicked.connect(self.on_play_button_clicked)
        self.playback_slider.sliderMoved.connect(self.set_playback_position); self.volume_slider.valueChanged.connect(self._on_volume_slider_changed)
        self.adaptive_volume_switch.stateChanged.connect(self._on_adaptive_volume_toggled_and_save)
        self.audio_table_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.audio_table_widget.customContextMenuRequested.connect(self.open_file_context_menu); self.audio_table_widget.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.set_start_btn.clicked.connect(self._set_trim_start); self.set_end_btn.clicked.connect(self._set_trim_end)
        self.clear_trim_btn.clicked.connect(self._clear_trim_points); self.preview_trim_btn.clicked.connect(self._preview_trim)
        self.save_trim_btn.clicked.connect(self._save_trim)
        self.connect_staged_btn.clicked.connect(self._concatenate_staged_files)
        self.clear_staged_btn.clicked.connect(self._clear_staging_area)
        self.waveform_widget.clicked_at_ratio.connect(self.seek_from_waveform_click)
        self.waveform_widget.marker_requested_at_ratio.connect(self.set_marker_from_waveform)
        self.waveform_widget.clear_markers_requested.connect(self._clear_trim_points)
        # [新增] 使用 QShortcut 设置快捷键，这是处理焦点问题的正确方法
        # 播放/暂停快捷键 (空格)
        self.toggle_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        self.toggle_shortcut.activated.connect(self.toggle_playback)
        
        # 播放选中项快捷键 (回车)
        self.play_shortcut = QShortcut(QKeySequence(Qt.Key_Return), self)
        self.play_shortcut.activated.connect(self.play_current_selected_item_from_shortcut)
        self.play_shortcut_enter = QShortcut(QKeySequence(Qt.Key_Enter), self)
        self.play_shortcut_enter.activated.connect(self.play_current_selected_item_from_shortcut)

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
        if self.active_player:
            try:
                self.active_player.positionChanged.disconnect(self.update_playback_position); self.active_player.durationChanged.disconnect(self.update_playback_duration)
                self.active_player.stateChanged.disconnect(self.on_player_state_changed)
            except TypeError: pass
        new_player = self.player_cache.get(filepath); self.active_player = new_player
        if not self.active_player: self.reset_player(); return
        self.active_player.positionChanged.connect(self.update_playback_position); self.active_player.durationChanged.connect(self.update_playback_duration)
        self.active_player.stateChanged.connect(self.on_player_state_changed)
        self.update_playback_duration(self.active_player.duration()); self.update_playback_position(self.active_player.position())
        self.on_player_state_changed(self.active_player.state()); self._on_volume_slider_changed(self.volume_slider.value())

    # [新增] 核心方法：清理整个缓存池
    def _clear_player_cache(self):
        # [修复] 采用同步清理，避免 deleteLater 的时序问题
        for player in self.player_cache.values():
            if player:
                player.stop()
                player.setMedia(QMediaContent())
        
        self.player_cache.clear()
        
        if self.active_player:
            self.active_player.stop()
            self.active_player.setMedia(QMediaContent())
            self.active_player = None

    # [修改] 表格选择变化时，更新缓存
    def _on_table_selection_changed(self):
        selected_items = self.audio_table_widget.selectedItems(); selected_rows_count = len(set(item.row() for item in selected_items)); is_single_selection = selected_rows_count == 1
        self.edit_panel_container.setVisible(AUDIO_ANALYSIS_AVAILABLE); self.edit_panel.setEnabled(is_single_selection); self.waveform_widget.setEnabled(is_single_selection)
        if is_single_selection:
            current_row = self.audio_table_widget.currentRow(); filepath = self.audio_table_widget.item(current_row, 0).data(Qt.UserRole)
            self.waveform_widget.set_waveform_data(filepath); self._update_player_cache(current_row); self._set_active_player(filepath)
        else: self.waveform_widget.clear(); self._clear_trim_points()

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
        
    def _execute_audio_operation(self, operation_func, *args):
        if not AUDIO_ANALYSIS_AVAILABLE: QMessageBox.warning(self, "功能受限", "此功能需要 numpy 和 soundfile 库。"); return
        try: operation_func(*args)
        except Exception as e: QMessageBox.critical(self, "音频处理错误", f"执行操作时出错: {e}")
        
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

    def _save_trim_logic(self):
        if self.trim_start_ms is None or self.trim_end_ms is None: QMessageBox.warning(self, "提示", "请先标记起点和终点。"); return
        filepath = self.audio_table_widget.item(self.audio_table_widget.currentRow(), 0).data(Qt.UserRole); base, ext = os.path.splitext(os.path.basename(filepath)); new_name, ok = QInputDialog.getText(self, "保存裁切文件", "输入新文件名:", QLineEdit.Normal, f"{base}_trimmed")
        if not (ok and new_name): return
        new_filepath = os.path.join(os.path.dirname(filepath), new_name + ext)
        if os.path.exists(new_filepath): QMessageBox.warning(self, "文件已存在", "该文件名已存在。"); return
        data, sr = sf.read(filepath); start_sample = int(self.trim_start_ms / 1000 * sr); end_sample = int(self.trim_end_ms / 1000 * sr); trimmed_data = data[start_sample:end_sample]; sf.write(new_filepath, trimmed_data, sr)
        QMessageBox.information(self, "成功", f"文件已保存为:\n{new_filepath}"); self.populate_audio_table()
    
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
        self.staging_list_widget.clear()
        # 这里我们不直接用staged_files.values()，因为字典是无序的。
        # 我们按照添加的顺序（或一个固定的顺序）来显示。
        # 更好的做法是让 staged_files 是一个 list of tuples。
        # 但为了简单，我们暂时用字典并排序key。
        for path in sorted(self.staged_files.keys()):
            self.staging_list_widget.addItem(self.staged_files[path])

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
        item = self.audio_table_widget.itemAt(position);
        if not item: return
        row = item.row(); filepath = self.audio_table_widget.item(row, 0).data(Qt.UserRole)
        selected_items = self.audio_table_widget.selectedItems()
        selected_rows_count = len(set(i.row() for i in selected_items))
        
        menu = QMenu(self.audio_table_widget)
        play_action = menu.addAction(self.icon_manager.get_icon("play_audio"), "试听 / 暂停")
        analyze_action = menu.addAction(self.icon_manager.get_icon("analyze"), "在音频分析中打开")
        analyze_action.setEnabled(hasattr(self.parent_window, 'go_to_audio_analysis') and selected_rows_count == 1)
        menu.addSeparator()

        add_to_staging_action = menu.addAction(self.icon_manager.get_icon("add_row"), f"将 {selected_rows_count} 个文件添加到暂存区")
        add_to_staging_action.setEnabled(selected_rows_count > 0)
        menu.addSeparator()

        rename_action = menu.addAction(self.icon_manager.get_icon("rename"), "重命名")
        rename_action.setEnabled(selected_rows_count == 1)
        delete_action = menu.addAction(self.icon_manager.get_icon("delete"), "删除")
        delete_action.setEnabled(selected_rows_count == 1)
        menu.addSeparator()
        
        open_folder_action = menu.addAction(self.icon_manager.get_icon("show_in_explorer"), "在文件浏览器中显示")
        open_folder_action.setEnabled(selected_rows_count == 1)
        
        # [新增] 设置快捷按钮功能的子菜单
        menu.addSeparator()
        shortcut_menu = menu.addMenu(self.icon_manager.get_icon("draw"), "设置快捷按钮")
        shortcut_actions = {
            'play': shortcut_menu.addAction(self.icon_manager.get_icon("play_audio"), "试听 / 暂停"),
            'analyze': shortcut_menu.addAction(self.icon_manager.get_icon("analyze"), "在音频分析中打开"),
            'stage': shortcut_menu.addAction(self.icon_manager.get_icon("add_row"), "添加到暂存区"),
            'rename': shortcut_menu.addAction(self.icon_manager.get_icon("rename"), "重命名"),
            'explorer': shortcut_menu.addAction(self.icon_manager.get_icon("show_in_explorer"), "在文件浏览器中显示"),
            'delete': shortcut_menu.addAction(self.icon_manager.get_icon("delete"), "删除 (默认)"),
        }
        # 标记当前选中的快捷方式
        for action_key, q_action in shortcut_actions.items():
            q_action.setCheckable(True)
            if self.shortcut_button_action == action_key:
                q_action.setChecked(True)

        action = menu.exec_(self.audio_table_widget.mapToGlobal(position))
        
        # --- 事件处理 ---
        # [新增] 处理快捷按钮设置
        for action_key, q_action in shortcut_actions.items():
            if action == q_action:
                self.set_shortcut_button_action(action_key)
                return # 结束处理

        if action == play_action: self.play_selected_item(row)
        elif action == analyze_action: self.parent_window.go_to_audio_analysis(filepath)
        elif action == add_to_staging_action: self._add_selected_to_staging()
        elif action == rename_action: self.rename_selected_file(row)
        elif action == delete_action: self.delete_file(filepath)
        elif action == open_folder_action: self.open_in_explorer(os.path.dirname(filepath), select_file=os.path.basename(filepath))
    def closeEvent(self, event):
        self._clear_player_cache();
        if self.temp_preview_file and os.path.exists(self.temp_preview_file):
            try: os.remove(self.temp_preview_file)
            except: pass
        super().closeEvent(event)
        
    def update_icons(self):
        self.on_player_state_changed(self.active_player.state() if self.active_player else QMediaPlayer.StoppedState)
        for row in range(self.audio_table_widget.rowCount()):
            btn = self.audio_table_widget.cellWidget(row, 3)
            if isinstance(btn, QPushButton): btn.setIcon(self.icon_manager.get_icon("delete"))
        self.set_start_btn.setIcon(self.icon_manager.get_icon("next")); self.set_end_btn.setIcon(self.icon_manager.get_icon("prev")); self.clear_trim_btn.setIcon(self.icon_manager.get_icon("clear_marker")); self.preview_trim_btn.setIcon(self.icon_manager.get_icon("preview")); self.save_trim_btn.setIcon(self.icon_manager.get_icon("save_2"))
        self.connect_staged_btn.setIcon(self.icon_manager.get_icon("concatenate"))
        self.clear_staged_btn.setIcon(self.icon_manager.get_icon("clear"))       
    def apply_layout_settings(self):
        config = self.parent_window.config; ui_settings = config.get("ui_settings", {}); width = ui_settings.get("editor_sidebar_width", 350); self.left_panel.setFixedWidth(width)
        
    def load_and_refresh(self):
         # [修改] 确保 self.config 是最新的
        self.config = self.parent_window.config
        self.apply_layout_settings()
        self.update_icons()
        results_dir_base = self.config.get('file_settings', {}).get('results_dir', os.path.join(self.BASE_PATH, "Results"))
        self.DATA_SOURCES["标准朗读采集"]["path"] = os.path.join(results_dir_base, "common")
        self.DATA_SOURCES["看图说话采集"]["path"] = os.path.join(results_dir_base, "visual")
        self.DATA_SOURCES["语音包录制"]["path"] = os.path.join(self.BASE_PATH, "audio_record")
        self.DATA_SOURCES["TTS 工具语音"]["path"] = os.path.join(self.BASE_PATH, "audio_tts")
        current_source = self.source_combo.currentText(); self.source_combo.blockSignals(True); self.source_combo.clear(); self.source_combo.addItems(self.DATA_SOURCES.keys()); self.source_combo.setCurrentText(current_source); self.source_combo.blockSignals(False)
        if self.source_combo.findText(current_source) != -1: self.populate_session_list()
        else: self.session_list_widget.clear(); self.audio_table_widget.setRowCount(0); self.table_label.setText("请从左侧选择一个项目以查看文件"); self.reset_player()
        
    def populate_session_list(self):
        source_name = self.source_combo.currentText(); source_info = self.DATA_SOURCES.get(source_name)
        if not source_info: return
        self.session_active = False; self.reset_player()
        current_text = self.session_list_widget.currentItem().text() if self.session_list_widget.currentItem() else None; self.session_list_widget.clear()
        base_path = source_info["path"]; path_filter = source_info["filter"]
        if not os.path.exists(base_path): os.makedirs(base_path, exist_ok=True); return
        try:
            sessions = sorted([d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d)) and path_filter(d, base_path)], key=lambda s: os.path.getmtime(os.path.join(base_path, s)), reverse=True)
            self.session_list_widget.addItems(sessions)
            if current_text:
                items = self.session_list_widget.findItems(current_text, Qt.MatchFixedString)
                if items: self.session_list_widget.setCurrentItem(items[0])
        except Exception as e: QMessageBox.critical(self, "错误", f"加载项目列表失败: {e}")
        
    def populate_audio_table(self):
        self.reset_player(); self.waveform_widget.clear(); self.audio_table_widget.setRowCount(0)
        if not self.current_session_path: return
        try:
            supported_exts = ('.wav', '.mp3', '.flac', '.ogg'); audio_files = sorted([f for f in os.listdir(self.current_session_path) if f.lower().endswith(supported_exts)])
            self.audio_table_widget.setRowCount(len(audio_files))
            for row, filename in enumerate(audio_files): self.update_table_row(row, os.path.join(self.current_session_path, filename))
            # 预加载第一个项目
            if len(audio_files) > 0: self._update_player_cache(0)
        except Exception as e: QMessageBox.critical(self, "错误", f"加载音频文件列表失败: {e}")
        
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
        self.session_active = True; source_name = self.source_combo.currentText(); self.current_session_path = os.path.join(self.DATA_SOURCES[source_name]["path"], selected_items[0].text())
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
        source_name = self.source_combo.currentText(); base_dir = self.DATA_SOURCES[source_name]["path"]
        if action == delete_action: self.delete_folders(selected_items, base_dir)
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
        if self.preview_player:
            self.preview_player.stop()
            self.preview_player = None
        self._clear_player_cache(); self.playback_slider.setValue(0); self.playback_slider.setEnabled(False)
        self.duration_label.setText("00:00.00 / 00:00.00"); self.on_player_state_changed(QMediaPlayer.StoppedState)
# [新增] 用于处理和保存持久化设置的槽函数
    def _on_persistent_setting_changed(self, key, value):
        """当用户更改任何可记忆的设置时，调用此方法以保存状态。"""
        self.parent_window.update_and_save_module_state('audio_manager', key, value)