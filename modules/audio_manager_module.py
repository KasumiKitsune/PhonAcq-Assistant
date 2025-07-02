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
                             QSlider, QComboBox, QApplication, QGroupBox)
from PyQt5.QtCore import Qt, QTimer, QUrl, QRect, pyqtProperty
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtGui import QIcon, QKeySequence, QPainter, QColor, QPen, QBrush, QPalette

try:
    import numpy as np
    import soundfile as sf
    AUDIO_ANALYSIS_AVAILABLE = True
except ImportError:
    AUDIO_ANALYSIS_AVAILABLE = False
    print("WARNING: numpy or soundfile not found. Audio auto-volume, editing and visualization features will be disabled.")

# ... (WaveformWidget class remains unchanged) ...
class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.setMaximumHeight(60)
        self.setToolTip("音频波形预览。\n蓝色区域表示裁切范围，红色竖线是当前播放位置。")
        self._waveform_data = None
        self._playback_pos_ratio = 0.0
        self._trim_start_ratio = -1.0
        self._trim_end_ratio = -1.0

        # [新增] 为QSS定义颜色属性和默认值
        self._waveformColor = self.palette().color(QPalette.Highlight)
        self._cursorColor = QColor("red")
        self._selectionColor = QColor(0, 100, 255, 60)

    # --- [新增] 定义pyqtProperty，暴露给QSS ---
    @pyqtProperty(QColor)
    def waveformColor(self):
        return self._waveformColor

    @waveformColor.setter
    def waveformColor(self, color):
        self._waveformColor = color
        self.update()

    @pyqtProperty(QColor)
    def cursorColor(self):
        return self._cursorColor

    @cursorColor.setter
    def cursorColor(self, color):
        self._cursorColor = color
        self.update()

    @pyqtProperty(QColor)
    def selectionColor(self):
        return self._selectionColor

    @selectionColor.setter
    def selectionColor(self, color):
        self._selectionColor = color
        self.update()
    # --- 结束新增 ---

    def set_waveform_data(self, audio_filepath):
        # ... 此方法无变化 ...
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
        # ... 此方法无变化 ...
        self._playback_pos_ratio = current_ms / total_ms if total_ms > 0 else 0.0
        self.update()

    def set_trim_points(self, start_ms, end_ms, total_ms):
        # ... 此方法无变化 ...
        self._trim_start_ratio = start_ms / total_ms if start_ms is not None and total_ms > 0 else -1.0
        self._trim_end_ratio = end_ms / total_ms if end_ms is not None and total_ms > 0 else -1.0
        self.update()

    def clear(self):
        # ... 此方法无变化 ...
        self._waveform_data = None; self._playback_pos_ratio = 0.0
        self._trim_start_ratio = -1.0; self._trim_end_ratio = -1.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bg_color = self.palette().color(QPalette.Base); painter.fillRect(self.rect(), bg_color)
        
        if self._waveform_data is None or len(self._waveform_data) == 0:
            painter.setPen(self.palette().color(QPalette.Mid)); painter.drawText(self.rect(), Qt.AlignCenter, "无波形数据"); return
        
        # [修改] 使用新的颜色属性进行绘制
        pen = QPen(self._waveformColor, 1)
        painter.setPen(pen)

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
def create_page(parent_window, CONFIG, BASE_PATH, RESULTS_DIR, AUDIO_RECORD_DIR, icon_manager, ToggleSwitchClass):
    AUDIO_TTS_DIR = os.path.join(BASE_PATH, "audio_tts")
    return AudioManagerPage(parent_window, CONFIG, BASE_PATH, RESULTS_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, icon_manager, ToggleSwitchClass)

class AudioManagerPage(QWidget):
    TARGET_RMS = 0.12 
    def __init__(self, parent_window, config, base_path, results_dir, audio_record_dir, audio_tts_dir, icon_manager, ToggleSwitchClass):
        super().__init__()
        self.parent_window = parent_window; self.config = config; self.BASE_PATH = base_path
        self.icon_manager = icon_manager; self.ToggleSwitch = ToggleSwitchClass
        self.DATA_SOURCES = {"口音采集会话": {"path": results_dir, "filter": lambda d, p: os.path.exists(os.path.join(p, d, 'log.txt'))}, "语音包/图文采集": {"path": audio_record_dir, "filter": lambda d, p: True}, "TTS 语音": {"path": audio_tts_dir, "filter": lambda d, p: True}}
        self.current_session_path = None; self.current_data_type = None; self.current_displayed_duration = 0
        self.player = QMediaPlayer(); self.player.setNotifyInterval(50) 
        self.trim_start_ms = None; self.trim_end_ms = None; self.temp_preview_file = None
        self._init_ui(); self._connect_signals(); self.update_icons(); self.apply_layout_settings()

    def _init_ui(self):
        main_splitter = QSplitter(Qt.Horizontal, self)
        self.left_panel = QWidget(); left_layout = QVBoxLayout(self.left_panel)
        left_layout.addWidget(QLabel("选择数据源:")); self.source_combo = QComboBox(); self.source_combo.addItems(self.DATA_SOURCES.keys()); self.source_combo.setToolTip("选择要查看的数据类型。")
        left_layout.addWidget(self.source_combo); left_layout.addWidget(QLabel("项目列表:"))
        self.session_list_widget = QListWidget(); self.session_list_widget.setContextMenuPolicy(Qt.CustomContextMenu); self.session_list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.session_list_widget.setToolTip("双击可直接在文件浏览器中打开。\n右键可进行批量操作。"); left_layout.addWidget(self.session_list_widget, 1)
        
        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel)
        self.table_label = QLabel("请从左侧选择一个项目以查看文件"); self.table_label.setAlignment(Qt.AlignCenter)
        self.audio_table_widget = QTableWidget(); self.audio_table_widget.setColumnCount(4); self.audio_table_widget.setHorizontalHeaderLabels(["文件名", "文件大小", "修改日期", ""]); self.audio_table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.audio_table_widget.setSelectionBehavior(QAbstractItemView.SelectRows); self.audio_table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers); self.audio_table_widget.verticalHeader().setVisible(False); self.audio_table_widget.setAlternatingRowColors(True)
        self.audio_table_widget.setContextMenuPolicy(Qt.CustomContextMenu); self.audio_table_widget.setColumnWidth(1, 120); self.audio_table_widget.setColumnWidth(2, 180); self.audio_table_widget.setColumnWidth(3, 80)
        self.audio_table_widget.setToolTip("双击或按Enter键可播放，右键可进行更多操作。")
        
        # --- [重构] 播放控制区 ---
        playback_v_layout = QVBoxLayout(); playback_v_layout.setContentsMargins(0, 5, 0, 5)
        
        playback_h_layout = QHBoxLayout()
        self.play_pause_btn = QPushButton(""); self.play_pause_btn.setMinimumWidth(80); self.play_pause_btn.setToolTip("播放或暂停当前选中的音频。")
        self.playback_slider = QSlider(Qt.Horizontal); self.playback_slider.setToolTip("显示当前播放进度，可拖动以快进或后退。")
        volume_layout = QHBoxLayout(); volume_layout.setSpacing(5)
        self.adaptive_volume_switch = self.ToggleSwitch(); self.adaptive_volume_switch.setToolTip("开启后，将根据音频响度自动调整初始音量。"); self.adaptive_volume_switch.setChecked(True)
        volume_layout.addWidget(QLabel("自适应")); volume_layout.addWidget(self.adaptive_volume_switch)
        self.volume_label = QLabel("  音量:"); self.volume_slider = QSlider(Qt.Horizontal); self.volume_slider.setFixedWidth(120); self.volume_slider.setRange(0, 100); self.volume_slider.setValue(100); self.volume_slider.setToolTip("调整播放音量。")
        self.volume_percent_label = QLabel("100%"); volume_layout.addWidget(self.volume_label); volume_layout.addWidget(self.volume_slider); volume_layout.addWidget(self.volume_percent_label)
        playback_h_layout.addWidget(self.play_pause_btn); playback_h_layout.addWidget(self.playback_slider, 10); playback_h_layout.addStretch(1); playback_h_layout.addLayout(volume_layout)
        
        # [修改] 波形图与时间同行的新布局
        waveform_time_layout = QHBoxLayout()
        self.waveform_widget = WaveformWidget()
        self.duration_label = QLabel("00:00.00 / 00:00.00")
        waveform_time_layout.addWidget(self.waveform_widget, 10) # 波形占大部分空间
        waveform_time_layout.addWidget(self.duration_label)

        playback_v_layout.addLayout(playback_h_layout)
        playback_v_layout.addLayout(waveform_time_layout)
        # --- 结束重构 ---

        # [修改] 为编辑面板创建一个固定的容器，以修复UI抖动
        self.edit_panel_container = QWidget()
        container_layout = QVBoxLayout(self.edit_panel_container)
        container_layout.setContentsMargins(0,0,0,0)
        self.edit_panel = QGroupBox("音频编辑")
        edit_controls_layout = QHBoxLayout(self.edit_panel); edit_controls_layout.setSpacing(10)
        self.trim_start_label = QLabel("起点: --:--.--"); self.set_start_btn = QPushButton("标记起点"); self.set_start_btn.setToolTip("将当前播放位置标记为裁切起点。")
        self.set_end_btn = QPushButton("标记终点"); self.set_end_btn.setToolTip("将当前播放位置标记为裁切终点。"); self.trim_end_label = QLabel("终点: --:--.--")
        self.clear_trim_btn = QPushButton("清除标记"); self.clear_trim_btn.setToolTip("清除已标记的起点和终点。")
        self.preview_trim_btn = QPushButton("预览"); self.preview_trim_btn.setToolTip("试听当前标记范围内的音频。")
        self.save_trim_btn = QPushButton("保存裁切"); self.save_trim_btn.setToolTip("将裁切后的音频另存为新文件。"); self.save_trim_btn.setObjectName("AccentButton")
        edit_controls_layout.addWidget(self.trim_start_label); edit_controls_layout.addWidget(self.set_start_btn); edit_controls_layout.addWidget(self.set_end_btn); edit_controls_layout.addWidget(self.trim_end_label)
        edit_controls_layout.addStretch(1); edit_controls_layout.addWidget(self.clear_trim_btn); edit_controls_layout.addWidget(self.preview_trim_btn); edit_controls_layout.addWidget(self.save_trim_btn)
        container_layout.addWidget(self.edit_panel)
        self.edit_panel_container.setVisible(False) # 默认隐藏整个容器

        right_layout.addWidget(self.table_label); right_layout.addWidget(self.audio_table_widget, 1)
        right_layout.addWidget(self.edit_panel_container)
        right_layout.addLayout(playback_v_layout)
        
        main_splitter.addWidget(self.left_panel); main_splitter.addWidget(right_panel); main_splitter.setStretchFactor(0, 1); main_splitter.setStretchFactor(1, 3)
        page_layout = QHBoxLayout(self); page_layout.addWidget(main_splitter)
        self.setFocusPolicy(Qt.StrongFocus)

    def _on_table_selection_changed(self):
        selected_items = self.audio_table_widget.selectedItems()
        selected_rows_count = len(set(item.row() for item in selected_items))
        is_single_selection = selected_rows_count == 1
    
        # [修改] 容器永远可见，只在有音频分析库时才可能启用
        self.edit_panel_container.setVisible(AUDIO_ANALYSIS_AVAILABLE)
    
        # [修改] 根据是否单选来启用/禁用编辑面板和波形图
        self.edit_panel.setEnabled(is_single_selection)
        self.waveform_widget.setEnabled(is_single_selection)

        if is_single_selection:
            filepath = self.audio_table_widget.item(self.audio_table_widget.currentRow(), 0).data(Qt.UserRole)
            self.waveform_widget.set_waveform_data(filepath)
        else:
            self.waveform_widget.clear()
            self._clear_trim_points()

    # [修改] 修复播放时波形消失的bug
    def play_selected_item(self, row):
        if row < 0 or row >= self.audio_table_widget.rowCount(): return
        filepath = self.audio_table_widget.item(row, 0).data(Qt.UserRole)
        if not (filepath and os.path.exists(filepath)): return

        if self.player.media().canonicalUrl() == QUrl.fromLocalFile(filepath) and self.player.state() != QMediaPlayer.StoppedState:
            self.toggle_playback()
        else:
            # 关键：先加载新波形，再重置播放器
            self.waveform_widget.set_waveform_data(filepath)
            self.reset_player() # reset_player内部不再clear waveform
            self._calculate_and_set_optimal_volume(filepath)
            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(filepath)))
            self.player.play()
    
    # [修改] reset_player不再清除波形图，由调用者决定
    def reset_player(self):
        self.player.stop()
        self.playback_slider.setValue(0)
        self.playback_slider.setRange(0, 0)
        self.duration_label.setText("00:00.00 / 00:00.00")
        self.current_displayed_duration = 0
        self.waveform_widget.update_playback_position(0, 0) # 仅重置播放头

    def on_session_selection_changed(self):
        selected_items = self.session_list_widget.selectedItems()
        self.edit_panel_container.setVisible(False)
        self.waveform_widget.clear()
        self._clear_trim_points()
        if len(selected_items) != 1:
            self.current_session_path = None; self.current_data_type = None; self.audio_table_widget.setRowCount(0)
            self.table_label.setText(f"已选择 {len(selected_items)} 个项目" if selected_items else "请从左侧选择一个项目"); self.reset_player(); return
        current_item = selected_items[0]; source_name = self.source_combo.currentText(); source_info = self.DATA_SOURCES.get(source_name)
        if not source_info: return
        self.current_data_type = source_name; base_dir = source_info["path"]; self.current_session_path = os.path.join(base_dir, current_item.text())
        self.table_label.setText(f"正在查看: {current_item.text()}"); self.populate_audio_table()

    # --- 以下方法基本保持不变 ---
    def _connect_signals(self):
        self.player.positionChanged.connect(self.update_playback_position); self.player.durationChanged.connect(self.update_playback_duration)
        self.player.stateChanged.connect(self.on_player_state_changed); self.source_combo.currentTextChanged.connect(self.populate_session_list)
        self.session_list_widget.itemSelectionChanged.connect(self.on_session_selection_changed); self.session_list_widget.customContextMenuRequested.connect(self.open_folder_context_menu)
        self.session_list_widget.itemDoubleClicked.connect(self.on_session_item_double_clicked); self.play_pause_btn.clicked.connect(self.on_play_button_clicked)
        self.playback_slider.sliderMoved.connect(self.set_playback_position); self.volume_slider.valueChanged.connect(self._on_volume_slider_changed)
        self.adaptive_volume_switch.stateChanged.connect(self._on_adaptive_volume_toggled); self.audio_table_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.audio_table_widget.customContextMenuRequested.connect(self.open_file_context_menu); self.audio_table_widget.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.set_start_btn.clicked.connect(self._set_trim_start); self.set_end_btn.clicked.connect(self._set_trim_end)
        self.clear_trim_btn.clicked.connect(self._clear_trim_points); self.preview_trim_btn.clicked.connect(self._preview_trim)
        self.save_trim_btn.clicked.connect(self._save_trim)
    def keyPressEvent(self, event):
        if self.audio_table_widget.hasFocus() and (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter):
            current_row = self.audio_table_widget.currentRow()
            if current_row != -1: self.play_selected_item(current_row); event.accept()
        else: super().keyPressEvent(event)
    def on_session_item_double_clicked(self, item):
        source_name = self.source_combo.currentText(); base_dir = self.DATA_SOURCES[source_name]["path"]; folder_path = os.path.join(base_dir, item.text()); self.open_in_explorer(folder_path)
    def _on_volume_slider_changed(self, value): self.player.setVolume(value); self.volume_percent_label.setText(f"{value}%")
    def _on_adaptive_volume_toggled(self, checked):
        if not checked: self.volume_slider.setValue(100)
    def _calculate_and_set_optimal_volume(self, filepath):
        if not self.adaptive_volume_switch.isChecked(): self.volume_slider.setValue(100); return
        if not AUDIO_ANALYSIS_AVAILABLE: self.volume_slider.setValue(100); return
        try:
            data, sr = sf.read(filepath, dtype='float32')
            if data.ndim > 1: data = data.mean(axis=1)
            rms = np.sqrt(np.mean(data**2)); 
            if rms == 0: self.volume_slider.setValue(100); return
            required_gain = self.TARGET_RMS / rms; slider_value = required_gain * 100
            clamped_value = int(np.clip(slider_value, 0, 100)); self.volume_slider.setValue(clamped_value)
        except Exception as e: print(f"Error analyzing audio: {e}"); self.volume_slider.setValue(100)
    def update_playback_position(self, position):
        if not self.playback_slider.isSliderDown(): self.playback_slider.setValue(position)
        total_duration = self.player.duration()
        if total_duration > self.current_displayed_duration: self.update_playback_duration(total_duration)
        self.duration_label.setText(f"{self.format_time(position)} / {self.format_time(self.current_displayed_duration)}")
        self.waveform_widget.update_playback_position(position, self.current_displayed_duration)
    def _set_trim_start(self):
        self.trim_start_ms = self.player.position(); self.trim_start_label.setText(f"起点: {self.format_time(self.trim_start_ms)}")
        if self.trim_end_ms is not None and self.trim_start_ms >= self.trim_end_ms: self.trim_end_ms = None; self.trim_end_label.setText("终点: --:--.--")
        self.waveform_widget.set_trim_points(self.trim_start_ms, self.trim_end_ms, self.player.duration())
    def _set_trim_end(self):
        self.trim_end_ms = self.player.position(); self.trim_end_label.setText(f"终点: {self.format_time(self.trim_end_ms)}")
        if self.trim_start_ms is not None and self.trim_end_ms <= self.trim_start_ms: self.trim_start_ms = None; self.trim_start_label.setText("起点: --:--.--")
        self.waveform_widget.set_trim_points(self.trim_start_ms, self.trim_end_ms, self.player.duration())
    def _clear_trim_points(self):
        self.trim_start_ms = None; self.trim_end_ms = None
        self.trim_start_label.setText("起点: --:--.--"); self.trim_end_label.setText("终点: --:--.--")
        self.waveform_widget.set_trim_points(None, None, self.player.duration())
    def _execute_audio_operation(self, operation_func, *args):
        if not AUDIO_ANALYSIS_AVAILABLE: QMessageBox.warning(self, "功能受限", "此功能需要 numpy 和 soundfile 库。"); return
        try: operation_func(*args)
        except Exception as e: QMessageBox.critical(self, "音频处理错误", f"执行操作时出错: {e}")
    def _preview_trim(self): self._execute_audio_operation(self._preview_trim_logic)
    def _save_trim(self): self._execute_audio_operation(self._save_trim_logic)
    def _concatenate_selected(self): self._execute_audio_operation(self._concatenate_selected_logic)
    def _preview_trim_logic(self):
        if self.trim_start_ms is None or self.trim_end_ms is None: QMessageBox.warning(self, "提示", "请先标记起点和终点。"); return
        filepath = self.audio_table_widget.item(self.audio_table_widget.currentRow(), 0).data(Qt.UserRole)
        data, sr = sf.read(filepath); start_sample = int(self.trim_start_ms / 1000 * sr); end_sample = int(self.trim_end_ms / 1000 * sr)
        trimmed_data = data[start_sample:end_sample]
        if self.temp_preview_file and os.path.exists(self.temp_preview_file): os.remove(self.temp_preview_file)
        fd, self.temp_preview_file = tempfile.mkstemp(suffix=".wav"); os.close(fd); sf.write(self.temp_preview_file, trimmed_data, sr)
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(self.temp_preview_file))); self.player.play()
    def _save_trim_logic(self):
        if self.trim_start_ms is None or self.trim_end_ms is None: QMessageBox.warning(self, "提示", "请先标记起点和终点。"); return
        filepath = self.audio_table_widget.item(self.audio_table_widget.currentRow(), 0).data(Qt.UserRole)
        base, ext = os.path.splitext(os.path.basename(filepath)); new_name, ok = QInputDialog.getText(self, "保存裁切文件", "输入新文件名:", QLineEdit.Normal, f"{base}_trimmed")
        if not (ok and new_name): return
        new_filepath = os.path.join(os.path.dirname(filepath), new_name + ext)
        if os.path.exists(new_filepath): QMessageBox.warning(self, "文件已存在", "该文件名已存在。"); return
        data, sr = sf.read(filepath); start_sample = int(self.trim_start_ms / 1000 * sr); end_sample = int(self.trim_end_ms / 1000 * sr)
        trimmed_data = data[start_sample:end_sample]; sf.write(new_filepath, trimmed_data, sr)
        QMessageBox.information(self, "成功", f"文件已保存为:\n{new_filepath}"); self.populate_audio_table()
    def _concatenate_selected_logic(self):
        selected_rows = sorted(list(set(item.row() for item in self.audio_table_widget.selectedItems())))
        if len(selected_rows) < 2: return
        filepaths = [self.audio_table_widget.item(row, 0).data(Qt.UserRole) for row in selected_rows]
        first_file_info = sf.info(filepaths[0]); sr, channels = first_file_info.samplerate, first_file_info.channels
        for fp in filepaths[1:]:
            info = sf.info(fp)
            if info.samplerate != sr or info.channels != channels: QMessageBox.critical(self, "无法连接", f"文件格式不匹配。"); return
        new_name, ok = QInputDialog.getText(self, "保存连接文件", "输入新文件名:", QLineEdit.Normal, "concatenated_output")
        if not (ok and new_name): return
        new_filepath = os.path.join(self.current_session_path, new_name + os.path.splitext(filepaths[0])[1])
        if os.path.exists(new_filepath): QMessageBox.warning(self, "文件已存在", "该文件名已存在。"); return
        all_data = [sf.read(fp)[0] for fp in filepaths]; concatenated_data = np.concatenate(all_data); sf.write(new_filepath, concatenated_data, sr)
        QMessageBox.information(self, "成功", f"文件已连接并保存为:\n{new_filepath}"); self.populate_audio_table()
    def open_file_context_menu(self, position):
        item = self.audio_table_widget.itemAt(position);
        if not item: return
        row = item.row(); filepath = self.audio_table_widget.item(row, 0).data(Qt.UserRole)
        selected_rows_count = len(set(i.row() for i in self.audio_table_widget.selectedItems()))
        menu = QMenu(); play_action = menu.addAction(self.icon_manager.get_icon("play_audio"), "试听 / 暂停")
        rename_action = menu.addAction(self.icon_manager.get_icon("rename"), "重命名"); delete_action = menu.addAction(self.icon_manager.get_icon("delete"), "删除"); menu.addSeparator()
        if AUDIO_ANALYSIS_AVAILABLE:
            concatenate_action = menu.addAction(self.icon_manager.get_icon("concatenate"), "连接选中音频"); concatenate_action.setEnabled(selected_rows_count > 1)
            concatenate_action.triggered.connect(self._concatenate_selected); menu.addSeparator()
        open_folder_action = menu.addAction(self.icon_manager.get_icon("show_in_explorer"), "在文件浏览器中显示")
        action = menu.exec_(self.audio_table_widget.mapToGlobal(position))
        if action == play_action: self.play_selected_item(row)
        elif action == rename_action: self.rename_selected_file()
        elif action == delete_action: self.delete_file(filepath)
        elif action == open_folder_action: self.open_in_explorer(self.current_session_path, select_file=os.path.basename(filepath))
    def closeEvent(self, event):
        if self.temp_preview_file and os.path.exists(self.temp_preview_file):
            try: os.remove(self.temp_preview_file)
            except: pass
        super().closeEvent(event)
    def update_icons(self):
        self.on_player_state_changed(self.player.state())
        for row in range(self.audio_table_widget.rowCount()):
            btn = self.audio_table_widget.cellWidget(row, 3)
            if isinstance(btn, QPushButton): btn.setIcon(self.icon_manager.get_icon("delete"))
        self.set_start_btn.setIcon(self.icon_manager.get_icon("next")); self.set_end_btn.setIcon(self.icon_manager.get_icon("prev"))
        self.clear_trim_btn.setIcon(self.icon_manager.get_icon("clear_marker")); self.preview_trim_btn.setIcon(self.icon_manager.get_icon("preview"))
        self.save_trim_btn.setIcon(self.icon_manager.get_icon("save_2"))
    def apply_layout_settings(self):
        config = self.parent_window.config; ui_settings = config.get("ui_settings", {}); width = ui_settings.get("editor_sidebar_width", 350); self.left_panel.setFixedWidth(width)
    def load_and_refresh(self):
        self.config = self.parent_window.config; self.apply_layout_settings(); self.update_icons()
        self.DATA_SOURCES["口音采集会话"]["path"] = self.config['file_settings'].get("results_dir", os.path.join(self.BASE_PATH, "Results"))
        self.DATA_SOURCES["语音包/图文采集"]["path"] = os.path.join(self.BASE_PATH, "audio_record"); self.DATA_SOURCES["TTS 语音"]["path"] = os.path.join(self.BASE_PATH, "audio_tts")
        self.populate_session_list()
        if self.session_list_widget.currentItem(): self.on_session_selection_changed()
        else: self.audio_table_widget.clearContents(); self.audio_table_widget.setRowCount(0); self.table_label.setText("请从左侧选择一个项目以查看文件"); self.reset_player()
    def populate_session_list(self):
        source_name = self.source_combo.currentText(); source_info = self.DATA_SOURCES.get(source_name)
        if not source_info: return
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
        self.audio_table_widget.setRowCount(0); self.reset_player()
        if not self.current_session_path: return
        try:
            supported_exts = ('.wav', '.mp3', '.flac', '.ogg')
            audio_files = sorted([f for f in os.listdir(self.current_session_path) if f.lower().endswith(supported_exts)])
            self.audio_table_widget.setRowCount(len(audio_files))
            for row, filename in enumerate(audio_files): self.update_table_row(row, os.path.join(self.current_session_path, filename))
        except Exception as e: QMessageBox.critical(self, "错误", f"加载音频文件列表失败: {e}")
    def update_table_row(self, row, filepath):
        filename = os.path.basename(filepath); file_size = os.path.getsize(filepath); mod_time = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M')
        item_filename = QTableWidgetItem(filename); item_filename.setData(Qt.UserRole, filepath)
        self.audio_table_widget.setItem(row, 0, item_filename); self.audio_table_widget.setItem(row, 1, QTableWidgetItem(f"{file_size / 1024:.1f} KB")); self.audio_table_widget.setItem(row, 2, QTableWidgetItem(mod_time))
        delete_btn = QPushButton(); delete_btn.setIcon(self.icon_manager.get_icon("delete"))
        delete_btn.setToolTip("删除此文件"); delete_btn.setCursor(Qt.PointingHandCursor); delete_btn.setObjectName("LinkButton")
        delete_btn.clicked.connect(lambda _, f=filepath: self.delete_file(f))
        self.audio_table_widget.setCellWidget(row, 3, delete_btn)
    def open_folder_context_menu(self, position):
        selected_items = self.session_list_widget.selectedItems();
        if not selected_items: return
        source_name = self.source_combo.currentText(); base_dir = self.DATA_SOURCES[source_name]["path"]
        menu = QMenu(); open_action = menu.addAction(self.icon_manager.get_icon("open_folder"), "打开文件夹"); rename_action = menu.addAction(self.icon_manager.get_icon("rename"), "重命名"); delete_action = menu.addAction(self.icon_manager.get_icon("delete"), "删除选中项")
        if len(selected_items) > 1: rename_action.setEnabled(False)
        action = menu.exec_(self.session_list_widget.mapToGlobal(position))
        if action == open_action: self.open_in_explorer(os.path.join(base_dir, selected_items[0].text()))
        elif action == rename_action: self.rename_folder(selected_items[0], base_dir)
        elif action == delete_action: self.delete_folders(selected_items, base_dir)
    def on_player_state_changed(self, state):
        if state == QMediaPlayer.PlayingState: self.play_pause_btn.setText("暂停"); self.play_pause_btn.setIcon(self.icon_manager.get_icon("pause"))
        else: self.play_pause_btn.setText("播放"); self.play_pause_btn.setIcon(self.icon_manager.get_icon("play"))
        if state == QMediaPlayer.EndOfMedia: self.playback_slider.setValue(0); self.duration_label.setText(f"00:00.00 / {self.format_time(self.player.duration())}")
    def on_item_double_clicked(self, item): self.play_selected_item(item.row())
    def rename_folder(self, item, base_dir):
        old_name = item.text(); old_path = os.path.join(base_dir, old_name)
        new_name, ok = QInputDialog.getText(self, "重命名文件夹", "请输入新的文件夹名称:", QLineEdit.Normal, old_name)
        if ok and new_name and new_name != old_name:
            new_path = os.path.join(base_dir, new_name.strip())
            if os.path.exists(new_path): QMessageBox.warning(self, "错误", "该名称的文件夹已存在。"); return
            try: os.rename(old_path, new_path); item.setText(new_name)
            except Exception as e: QMessageBox.critical(self, "错误", f"重命名失败: {e}")
    def delete_folders(self, items, base_dir):
        count = len(items); reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除选中的 {count} 个项目及其所有内容吗？\n此操作不可撤销！", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.parent_window.statusBar().showMessage(f"正在删除 {count} 个项目...", 0); QApplication.processEvents()
            error_occurred = False
            for item in items:
                try: self.parent_window.statusBar().showMessage(f"正在删除: {item.text()}...", 0); QApplication.processEvents(); shutil.rmtree(os.path.join(base_dir, item.text()))
                except Exception as e: self.parent_window.statusBar().showMessage(f"删除 '{item.text()}' 时出错。", 5000); QMessageBox.critical(self, "删除失败", f"删除文件夹 '{item.text()}' 时出错: {e}"); error_occurred = True; break
            if not error_occurred: self.parent_window.statusBar().showMessage(f"成功删除 {count} 个项目。", 4000)
            self.populate_session_list()
    def rename_selected_file(self):
        selected_items = self.audio_table_widget.selectedItems()
        if not selected_items: return
        row = selected_items[0].row(); old_filepath = self.audio_table_widget.item(row, 0).data(Qt.UserRole); old_basename, ext = os.path.splitext(os.path.basename(old_filepath))
        new_basename, ok = QInputDialog.getText(self, "重命名文件", "请输入新的文件名:", QLineEdit.Normal, old_basename)
        if ok and new_basename and new_basename.strip() and new_basename != old_basename:
            new_filepath = os.path.join(self.current_session_path, new_basename.strip() + ext)
            if os.path.exists(new_filepath): QMessageBox.warning(self, "错误", "文件名已存在。"); return
            try: os.rename(old_filepath, new_filepath); self.update_table_row(row, new_filepath)
            except Exception as e: QMessageBox.critical(self, "错误", f"重命名失败: {e}")
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
        filename = os.path.basename(filepath); reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除文件 '{filename}' 吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                if self.player.media().canonicalUrl() == QUrl.fromLocalFile(filepath): self.reset_player()
                os.remove(filepath); self.populate_audio_table()
            except Exception as e: QMessageBox.critical(self, "错误", f"删除失败: {e}")
    def on_play_button_clicked(self):
        if self.player.state() in [QMediaPlayer.PlayingState, QMediaPlayer.PausedState]: self.toggle_playback()
        else:
            current_row = self.audio_table_widget.currentRow()
            if current_row != -1: self.play_selected_item(current_row)
    def toggle_playback(self):
        if self.player.state() == QMediaPlayer.PlayingState: self.player.pause()
        else: self.player.play()
    def update_playback_duration(self, duration):
        if duration > 0 and duration != self.current_displayed_duration:
            self.current_displayed_duration = duration; self.playback_slider.setRange(0, duration); self.duration_label.setText(f"{self.format_time(self.player.position())} / {self.format_time(duration)}")
    def set_playback_position(self, position): self.player.setPosition(position)
    def format_time(self, ms):
        if ms <= 0: return "00:00.00"
        total_seconds = ms / 1000.0; m, s_frac = divmod(total_seconds, 60); s_int = int(s_frac); cs = int(round((s_frac - s_int) * 100));
        if cs == 100: cs = 0; s_int +=1
        if s_int == 60: s_int = 0; m += 1
        return f"{int(m):02d}:{s_int:02d}.{cs:02d}"