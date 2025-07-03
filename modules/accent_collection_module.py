# --- START OF FILE modules/accent_collection_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "标准朗读采集"
MODULE_DESCRIPTION = "进行标准的文本到语音实验，适用于朗读任务、最小音对测试、句子复述等场景。"
# ---

import os
import threading
import queue
import importlib.util
import time
import random
import sys
import json

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget,
                             QTableWidgetItem, QMessageBox, QComboBox, QFormLayout,
                             QGroupBox, QProgressBar, QStyle, QLineEdit, QHeaderView,
                             QAbstractItemView)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, pyqtProperty
from PyQt5.QtGui import QPainter, QPen, QColor, QPalette

# 模块级别的依赖检查
try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
    from gtts import gTTS
    DEPENDENCIES_MISSING = False
except ImportError as e:
    print(f"CRITICAL: accent_collection_module.py - Missing dependencies: {e}")
    DEPENDENCIES_MISSING = True
    MISSING_ERROR_MESSAGE = str(e)

# --- [新增] 本地化的波形可视化控件 ---
class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(40)
        self._waveform_data = None
        
        # [新增] 为QSS定义颜色属性和默认值
        self._waveformColor = self.palette().color(QPalette.Highlight)
        self._cursorColor = QColor("red") # 虽然QSS会覆盖，但提供一个默认值
        self._selectionColor = QColor(0, 100, 255, 60) # 同上

    # --- [新增] 定义pyqtProperty，暴露给QSS ---
    @pyqtProperty(QColor)
    def waveformColor(self):
        return self._waveformColor

    @waveformColor.setter
    def waveformColor(self, color):
        if self._waveformColor != color:
            self._waveformColor = color
            self.update()

    @pyqtProperty(QColor)
    def cursorColor(self):
        return self._cursorColor

    @cursorColor.setter
    def cursorColor(self, color):
        if self._cursorColor != color:
            self._cursorColor = color
            self.update()

    @pyqtProperty(QColor)
    def selectionColor(self):
        return self._selectionColor

    @selectionColor.setter
    def selectionColor(self, color):
        if self._selectionColor != color:
            self._selectionColor = color
            self.update()
    # --- 结束新增 ---

    def set_waveform_data(self, audio_filepath):
        # ... 此方法保持原样，无需修改 ...
        self._waveform_data = None
        if not (audio_filepath and os.path.exists(audio_filepath)):
            self.update()
            return

        try:
            data, sr = sf.read(audio_filepath, dtype='float32')
            if data.ndim > 1: data = data.mean(axis=1)
            num_samples = len(data)
            target_points = self.width() * 2 if self.width() > 0 else 400
            if num_samples <= target_points: self._waveform_data = data
            else:
                step = num_samples // target_points
                peak_data = [np.max(np.abs(data[i:i+step])) for i in range(0, num_samples, step)]
                self._waveform_data = np.array(peak_data)
        except Exception as e:
            print(f"Error loading waveform for {os.path.basename(audio_filepath)}: {e}")
            self._waveform_data = None
        self.update()

    def paintEvent(self, event):
        # ... 此方法也需要更新以使用新属性 ...
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        bg_color = self.palette().color(QPalette.Base)
        painter.fillRect(self.rect(), bg_color)
        
        if self._waveform_data is None or len(self._waveform_data) == 0:
            return

        # [修改] 使用新的颜色属性进行绘制
        pen = QPen(self._waveformColor, 1)
        painter.setPen(pen)

        h = self.height(); half_h = h / 2; w = self.width(); num_points = len(self._waveform_data)
        max_val = np.max(self._waveform_data)
        if max_val == 0: max_val = 1.0
        for i, val in enumerate(self._waveform_data):
            x = int(i * w / num_points); y_offset = (val / max_val) * half_h
            painter.drawLine(x, int(half_h - y_offset), x, int(half_h + y_offset))

# ===== 标准化模块入口函数 =====
def create_page(parent_window, config, ToggleSwitchClass, WorkerClass, LoggerClass,
                detect_language_func, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH, icon_manager):
    if DEPENDENCIES_MISSING:
        error_page = QWidget(); layout = QVBoxLayout(error_page)
        label = QLabel(f"标准朗读采集模块加载失败：\n缺少必要的依赖库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install sounddevice soundfile numpy gtts")
        label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); layout.addWidget(label)
        return error_page

    return AccentCollectionPage(parent_window, config, ToggleSwitchClass, WorkerClass, LoggerClass,
                                detect_language_func, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH, icon_manager)


class AccentCollectionPage(QWidget):
    recording_device_error_signal = pyqtSignal(str)

    def __init__(self, parent_window, config, ToggleSwitchClass, WorkerClass, LoggerClass,
                 detect_language_func, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH, icon_manager):
        super().__init__()
        self.parent_window = parent_window; self.config = config; self.ToggleSwitch = ToggleSwitchClass; self.Worker = WorkerClass
        self.Logger = LoggerClass; self.icon_manager = icon_manager; self.detect_language = detect_language_func
        self.WORD_LIST_DIR = WORD_LIST_DIR; self.AUDIO_RECORD_DIR = AUDIO_RECORD_DIR; self.AUDIO_TTS_DIR = AUDIO_TTS_DIR; self.BASE_PATH = BASE_PATH
        self.session_active = False; self.is_recording = False; self.current_word_list = []; self.current_word_index = -1
        self.audio_queue = queue.Queue(); self.volume_meter_queue = queue.Queue(maxsize=2); self.recording_thread = None
        self.session_stop_event = threading.Event(); self.logger = None
        
        self._init_ui(); self._connect_signals(); self.update_icons(); self.reset_ui(); self.apply_layout_settings()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        left_layout = QVBoxLayout()
        
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)

        # [修改] 使用 QTableWidget 替换 QListWidget
        self.list_widget = QTableWidget()
        self.list_widget.setColumnCount(3)
        self.list_widget.setHorizontalHeaderLabels(["词语", "IPA/备注", "波形预览"])
        self.list_widget.verticalHeader().setVisible(False)
        self.list_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setWordWrap(True)
        
        header = self.list_widget.horizontalHeader()
        # [修改] 设置为 Interactive 以允许用户自由拖动
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        
        # [新增] 使用 setStretchLastSection 来确保表格填满宽度
        # 这通常是默认行为，但明确设置一下更保险
        self.list_widget.horizontalHeader().setStretchLastSection(True)

        # [修改] 在拥有有效宽度后设置初始比例
        # 我们不能在_init_ui中立即设置，因为此时控件宽度可能为0。
        # 一个好的做法是在第一次显示或调整大小时设置。
        # 为了简单起见，我们可以在这里设置一个初始的、非零的宽度，
        # 或者更好地，在 resizeEvent 中处理。但对于初始比例，直接设置宽度是可行的。
        # 我们将在`resizeEvent`中处理，这里先移除旧代码。

        self.list_widget.setToolTip("当前会话需要录制的所有词语。\n绿色对勾表示已录制。\n双击可重听提示音。")
        self.status_label = QLabel("状态：准备就绪")
        self.progress_bar = QProgressBar(); self.progress_bar.setVisible(False)
        left_layout.addWidget(QLabel("测试词语列表:"))
        left_layout.addWidget(self.list_widget)
        left_layout.addWidget(self.status_label)
        left_layout.addWidget(self.progress_bar)

        right_panel_group = QGroupBox("控制面板")
        self.right_layout_container = QVBoxLayout(right_panel_group)

        self.pre_session_widget = QWidget()
        pre_session_layout = QFormLayout(self.pre_session_widget)
        pre_session_layout.setContentsMargins(11, 0, 11, 0)
        self.word_list_combo = QComboBox()
        self.word_list_combo.setToolTip("选择一个用于本次采集任务的单词表文件。")
        self.participant_input = QLineEdit()
        self.participant_input.setToolTip("输入被试者的唯一标识符。\n此名称将用于创建结果文件夹，例如 'participant_1'。")
        self.start_session_btn = QPushButton("开始新会话")
        self.start_session_btn.setObjectName("AccentButton")
        self.start_session_btn.setToolTip("加载选定的单词表，检查/生成提示音，并开始一个新的采集会话。")
        pre_session_layout.addRow("选择单词表:", self.word_list_combo)
        pre_session_layout.addRow("被试者名称:", self.participant_input)
        pre_session_layout.addRow(self.start_session_btn)

        self.in_session_widget = QWidget()
        in_session_layout = QVBoxLayout(self.in_session_widget)
        mode_group = QGroupBox("会话模式")
        mode_layout = QFormLayout(mode_group)
        self.random_switch = self.ToggleSwitch(); self.random_switch.setToolTip("开启后，将打乱词表中所有词语的顺序进行呈现。")
        self.full_list_switch = self.ToggleSwitch(); self.full_list_switch.setToolTip("开启后，将使用词表中的所有词语。\n关闭后，将只从每个组别中随机抽取一个词语。")
        random_layout = QHBoxLayout(); random_layout.addWidget(QLabel("顺序")); random_layout.addWidget(self.random_switch); random_layout.addWidget(QLabel("随机"))
        full_list_layout = QHBoxLayout(); full_list_layout.addWidget(QLabel("部分")); full_list_layout.addWidget(self.full_list_switch); full_list_layout.addWidget(QLabel("完整"))
        mode_layout.addRow(random_layout); mode_layout.addRow(full_list_layout)
        self.end_session_btn = QPushButton("结束当前会话")
        self.end_session_btn.setObjectName("ActionButton_Delete")
        self.end_session_btn.setToolTip("提前结束当前的采集会话。")
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
        
        self.record_btn = QPushButton("开始录制下一个")
        self.replay_btn = QPushButton("重听当前音频")
        self.replay_btn.setToolTip("重新播放当前选中词语的提示音 (可双击列表项触发)。")
        
        right_layout.addWidget(right_panel_group)
        right_layout.addStretch()
        right_layout.addWidget(self.recording_status_panel)
        right_layout.addWidget(self.record_btn)
        right_layout.addWidget(self.replay_btn)
        
        main_layout.addLayout(left_layout, 2)
        main_layout.addWidget(self.right_panel, 1)

    def resizeEvent(self, event):
        """
        在窗口大小改变时，重新计算并设置列宽以保持2:1:1的比例。
        """
        super().resizeEvent(event)
        
        # 减去垂直滚动条和表头的宽度，以获得可用的内容区域宽度
        header_width = self.list_widget.verticalHeader().width()
        scrollbar_width = self.list_widget.verticalScrollBar().width() if self.list_widget.verticalScrollBar().isVisible() else 0
        available_width = self.list_widget.viewport().width() - header_width - scrollbar_width
        
        if available_width > 0:
            # 分配宽度，确保总和等于可用宽度
            width1 = int(available_width * 0.5)
            width2 = int(available_width * 0.25)
            # 最后一列使用剩余的所有空间，避免四舍五入导致空隙
            width3 = available_width - width1 - width2
            
            self.list_widget.setColumnWidth(0, width1)
            self.list_widget.setColumnWidth(1, width2)
            self.list_widget.setColumnWidth(2, width3)

    def _connect_signals(self):
        self.start_session_btn.clicked.connect(self.start_session)
        self.end_session_btn.clicked.connect(self.end_session)
        self.record_btn.clicked.connect(self.handle_record_button)
        self.replay_btn.clicked.connect(self.replay_audio)
        # [修改] 连接表格信号
        self.list_widget.itemSelectionChanged.connect(self.on_list_item_changed)
        self.list_widget.cellDoubleClicked.connect(self.on_cell_double_clicked)
        self.random_switch.stateChanged.connect(self.on_session_mode_changed)
        self.full_list_switch.stateChanged.connect(self.on_session_mode_changed)
        self.recording_device_error_signal.connect(self.show_recording_device_error)

    def on_cell_double_clicked(self, row, column):
        # 无论双击哪一列，都视为重听
        self.replay_audio()

    def update_icons(self):
        self.start_session_btn.setIcon(self.icon_manager.get_icon("start_session")); self.end_session_btn.setIcon(self.icon_manager.get_icon("end_session")); self.replay_btn.setIcon(self.icon_manager.get_icon("play_audio"))
        if self.is_recording: self.record_btn.setIcon(self.icon_manager.get_icon("stop"))
        else: self.record_btn.setIcon(self.icon_manager.get_icon("record"))
        if self.session_active:
            for i, item_data in enumerate(self.current_word_list):
                if item_data.get('recorded', False):
                    # [修改] 图标设置到第一列的item上
                    list_item = self.list_widget.item(i, 0)
                    if list_item: list_item.setIcon(self.icon_manager.get_icon("success"))

    def apply_layout_settings(self):
        ui_settings = self.config.get("ui_settings", {}); width = ui_settings.get("collector_sidebar_width", 320); self.right_panel.setFixedWidth(width)

    def load_config_and_prepare(self):
        self.config = self.parent_window.config; self.apply_layout_settings()
        if not self.session_active: self.populate_word_lists(); self.participant_input.setText(self.config['file_settings'].get('participant_base_name', 'participant'))
    
    def show_recording_device_error(self, error_message):
        QMessageBox.critical(self, "录音设备错误", error_message); self.status_label.setText("状态：录音设备错误，请检查设置。"); self.record_btn.setEnabled(False)
        if self.session_active: self.end_session(force=True)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if self.list_widget.hasFocus() and self.replay_btn.isEnabled(): self.replay_audio(); event.accept()
        else: super().keyPressEvent(event)

    def update_volume_meter(self):
        try:
            data_chunk = self.volume_meter_queue.get_nowait()
            if data_chunk is not None: volume_norm = np.linalg.norm(data_chunk) * 20; self.volume_meter.setValue(int(volume_norm))
        except queue.Empty: self.volume_meter.setValue(int(self.volume_meter.value() * 0.8))
        except Exception as e: print(f"Error calculating volume: {e}")
            
    def _start_recording_logic(self):
        self.recording_indicator.setText("● 正在录音"); self.recording_indicator.setStyleSheet("color: red;")
        while not self.audio_queue.empty():
            try: self.audio_queue.get_nowait()
            except queue.Empty: break
        self.is_recording = True

    def _stop_recording_logic(self):
        self.is_recording = False; self.recording_indicator.setText("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.run_task_in_thread(self.save_recording_task)

    def populate_word_lists(self):
        self.word_list_combo.clear()
        if os.path.exists(self.WORD_LIST_DIR):
            try:
                # [修改] 只查找 .json 文件
                self.word_list_combo.addItems([f for f in os.listdir(self.WORD_LIST_DIR) if f.endswith('.json')])
            except Exception as e:
                QMessageBox.warning(self, "错误", f"无法读取单词表目录: {e}")
        
        default_list = self.config['file_settings'].get('word_list_file', '')
        if default_list:
            # 确保在查找时也匹配 .json
            if not default_list.endswith('.json') and default_list.endswith('.py'):
                 default_list = os.path.splitext(default_list)[0] + '.json'
            
            index = self.word_list_combo.findText(default_list, Qt.MatchFixedString)
            if index >= 0:
                self.word_list_combo.setCurrentIndex(index)

    def on_session_mode_changed(self):
        if not self.session_active: return
        self.prepare_word_list()
        if self.current_word_list: 
            recorded_count = sum(1 for item in self.current_word_list if item['recorded'])
            self.record_btn.setText(f"开始录制 ({recorded_count + 1}/{len(self.current_word_list)})")
        
    def reset_ui(self):
        self.pre_session_widget.show(); self.in_session_widget.hide(); self.record_btn.setEnabled(False); self.replay_btn.setEnabled(False); self.record_btn.setText("开始录制下一个")
        self.list_widget.setRowCount(0); self.status_label.setText("状态：准备就绪"); self.progress_bar.setVisible(False); self.progress_bar.setValue(0)
        
    def end_session(self, force=False):
        if not force:
            reply = QMessageBox.question(self, '结束会话', '您确定要结束当前的口音采集会话吗？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes: return
        if self.logger:
            recorded_count = sum(1 for item in self.current_word_list if item.get('recorded', False)); total_count = len(self.current_word_list)
            self.logger.log(f"[SESSION_END] Session ended by user. Recorded {recorded_count}/{total_count} items.")
        self.update_timer.stop(); self.volume_meter.setValue(0); self.session_stop_event.set()
        if self.recording_thread and self.recording_thread.is_alive(): self.recording_thread.join(timeout=1.0)
        self.recording_thread = None; self.session_active = False; self.is_recording = False; self.current_word_list = []; self.current_word_index = -1; self.logger = None
        self.reset_ui(); self.load_config_and_prepare()

    def start_session(self):
        wordlist_file = self.word_list_combo.currentText()
        if not wordlist_file: QMessageBox.warning(self, "选择错误", "请先选择一个单词表。"); return
        base_name = self.participant_input.text().strip()
        if not base_name: QMessageBox.warning(self, "输入错误", "请输入被试者名称。"); return
        
        # [修改] 结果保存路径
        results_dir = self.config['file_settings'].get("results_dir", os.path.join(self.BASE_PATH, "Results"))
        common_results_dir = os.path.join(results_dir, "common"); os.makedirs(common_results_dir, exist_ok=True)
        i = 1; folder_name = base_name
        while os.path.exists(os.path.join(common_results_dir, folder_name)): i += 1; folder_name = f"{base_name}_{i}"
        self.recordings_folder = os.path.join(common_results_dir, folder_name); os.makedirs(self.recordings_folder)
        
        self.logger = None
        if self.config.get("app_settings", {}).get("enable_logging", True): self.logger = self.Logger(os.path.join(self.recordings_folder, "log.txt"))
        try:
            self.current_wordlist_name = wordlist_file; word_groups = self.load_word_list_logic()
            if not word_groups:
                QMessageBox.warning(self, "词表错误", f"单词表 '{wordlist_file}' 为空或无法解析。")
                if self.logger: self.logger.log(f"[ERROR] Wordlist '{wordlist_file}' is empty or could not be parsed.")
                self.reset_ui(); return
            if self.logger:
                mode = "Random" if self.random_switch.isChecked() else "Sequential"; scope = "Full List" if self.full_list_switch.isChecked() else "Partial (One per group)"
                self.logger.log(f"[SESSION_START] Participant: '{base_name}', Session Folder: '{folder_name}'"); self.logger.log(f"[SESSION_CONFIG] Wordlist: '{wordlist_file}', Mode: {mode}, Scope: {scope}")
            self.progress_bar.setVisible(True); self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0); self.run_task_in_thread(self.check_and_generate_audio_logic, word_groups)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载单词表失败: {e}");
            if self.logger: self.logger.log(f"[ERROR] Failed to load wordlist '{wordlist_file}': {e}")
            self.reset_ui()
        
    def update_tts_progress(self, percentage, text):
        self.progress_bar.setValue(percentage); self.status_label.setText(f"状态：{text}")
        
    def on_tts_finished(self, error_msg):
        self.progress_bar.setVisible(False)
        if error_msg:
            QMessageBox.warning(self, "音频检查/生成失败", error_msg)
            if self.logger: self.logger.log(f"[ERROR] TTS Generation Error: {error_msg}")
            self.reset_ui(); return
        self.session_stop_event.clear(); self.recording_thread = threading.Thread(target=self._persistent_recorder_task, daemon=True); self.recording_thread.start(); self.update_timer.start(30)
        self.status_label.setText("状态：音频准备就绪。"); self.pre_session_widget.hide(); self.in_session_widget.show(); self.record_btn.setEnabled(True); self.session_active = True
        self.prepare_word_list()
        if self.current_word_list: self.record_btn.setText("开始录制 (1/{})".format(len(self.current_word_list)))
        
    def _find_existing_audio(self, word):
        # 辅助函数，用于查找给定单词的已存在音频文件
        if not self.recordings_folder: return None
        for ext in ['.mp3', '.wav']: # 优先使用会话中录制的格式
             path = os.path.join(self.recordings_folder, f"{word}{ext}")
             if os.path.exists(path): return path
        return None

    def prepare_word_list(self):
        word_groups = self.load_word_list_logic(); is_random = self.random_switch.isChecked(); is_full = self.full_list_switch.isChecked(); temp_list = []
        if not is_full:
            for group in word_groups:
                if group: temp_list.append(random.choice(list(group.items())))
        else:
            for group in word_groups: temp_list.extend(group.items())
        if is_random: random.shuffle(temp_list)
        self.current_word_list = []
        for word, value in temp_list:
            ipa = value[0] if isinstance(value, tuple) else str(value); self.current_word_list.append({'word': word, 'ipa': ipa, 'recorded': False})
        
        # [修改] 使用新的表格填充逻辑
        self.list_widget.setRowCount(0) # Clear table
        for i, item_data in enumerate(self.current_word_list):
            self.list_widget.insertRow(i)
            # Column 0: Word
            word_item = QTableWidgetItem(item_data['word'])
            self.list_widget.setItem(i, 0, word_item)
            # Column 1: IPA
            ipa_item = QTableWidgetItem(item_data['ipa'])
            self.list_widget.setItem(i, 1, ipa_item)
            # Column 2: Waveform Widget
            waveform_widget = WaveformWidget(self)
            self.list_widget.setCellWidget(i, 2, waveform_widget)
            
            # 检查此单词是否已经有录音（比如继续上一次的会话）
            filepath = self._find_existing_audio(item_data['word'])
            if filepath:
                item_data['recorded'] = True
                word_item.setIcon(self.icon_manager.get_icon("success"))
                waveform_widget.set_waveform_data(filepath)

        self.list_widget.resizeRowsToContents()
        if self.current_word_list: self.list_widget.setCurrentCell(0, 0)
        
    def handle_record_button(self):
        if not self.is_recording:
            self.current_word_index=self.list_widget.currentRow()
            if self.current_word_index==-1: QMessageBox.information(self, "提示", "请先在左侧列表中选择一个词条。"); return
            word_to_record = self.current_word_list[self.current_word_index]['word']
            if self.logger: self.logger.log(f"[RECORDING_START] Word: '{word_to_record}'")
            self.is_recording=True; self.record_btn.setText("停止录制"); self.record_btn.setIcon(self.icon_manager.get_icon("stop")); self.record_btn.setToolTip("点击停止当前录音。")
            self.list_widget.setEnabled(False); self.random_switch.setEnabled(False);self.full_list_switch.setEnabled(False)
            self.status_label.setText(f"状态：正在录制 '{word_to_record}'..."); self.play_audio_logic(); self._start_recording_logic()
        else:
            self.is_recording=False; self._stop_recording_logic(); self.record_btn.setText("准备就绪"); self.record_btn.setIcon(self.icon_manager.get_icon("record"))
            self.record_btn.setToolTip("点击开始录制当前选中的词语。"); self.record_btn.setEnabled(False); self.status_label.setText("状态：正在保存录音...")
            
    def on_recording_saved(self, result):
        self.status_label.setText("状态：录音已保存。"); self.list_widget.setEnabled(True); self.replay_btn.setEnabled(True)
        self.random_switch.setEnabled(True);self.full_list_switch.setEnabled(True)
        if result == "save_failed_mp3_encoder":
            QMessageBox.critical(self, "MP3 编码器缺失", "无法将录音保存为 MP3 格式。..."); self.status_label.setText("状态：MP3保存失败！"); return
        if self.current_word_index < 0 or self.current_word_index >= len(self.current_word_list):
             if self.logger: self.logger.log(f"[ERROR] current_word_index ({self.current_word_index}) out of bounds in on_recording_saved.")
             self.record_btn.setEnabled(True); return
        item_data=self.current_word_list[self.current_word_index]; item_data['recorded']=True
        
        # [修改] 更新表格中的图标和波形
        list_item = self.list_widget.item(self.current_word_index, 0)
        if list_item: list_item.setIcon(self.icon_manager.get_icon("success"))
        
        waveform_widget = self.list_widget.cellWidget(self.current_word_index, 2)
        if isinstance(waveform_widget, WaveformWidget):
            filepath = self._find_existing_audio(item_data['word'])
            if filepath: waveform_widget.set_waveform_data(filepath)
        
        all_recorded=all(item['recorded'] for item in self.current_word_list)
        if all_recorded: self.handle_session_completion(); return
        next_index=-1; indices=list(range(len(self.current_word_list)))
        for i in indices[self.current_word_index+1:]+indices[:self.current_word_index]:
            if not self.current_word_list[i]['recorded']:next_index=i;break
        if next_index!=-1:
            self.list_widget.setCurrentCell(next_index, 0); self.record_btn.setEnabled(True); self.record_btn.setToolTip("点击开始录制当前选中的词语。")
            recorded_count = sum(1 for item in self.current_word_list if item['recorded'])
            self.record_btn.setText(f"开始录制 ({recorded_count + 1}/{len(self.current_word_list)})")
        else: self.handle_session_completion()

    def handle_session_completion(self):
        unrecorded_count=sum(1 for item in self.current_word_list if not item['recorded'])
        if self.current_word_list: QMessageBox.information(self,"会话结束",f"本次会话已结束。\n总共录制了 {len(self.current_word_list)-unrecorded_count} 个词语。")
        self.end_session()
        
    def on_list_item_changed(self):
        row = self.list_widget.currentRow()
        if row!=-1 and not self.is_recording: self.replay_btn.setEnabled(True)
        
    def replay_audio(self, item=None):
        self.play_audio_logic()
    
    def play_audio_logic(self,index=None):
        if not self.session_active: return
        if index is None: index = self.list_widget.currentRow()
        if index == -1 or index >= len(self.current_word_list): return
        word = self.current_word_list[index]['word']; wordlist_name, _ = os.path.splitext(self.current_wordlist_name)
        record_path = os.path.join(self.AUDIO_RECORD_DIR, wordlist_name, f"{word}.mp3"); tts_path = os.path.join(self.AUDIO_TTS_DIR, wordlist_name, f"{word}.mp3")
        final_path = record_path if os.path.exists(record_path) else tts_path
        if os.path.exists(final_path): threading.Thread(target=self.play_sound_task, args=(final_path,), daemon=True).start()
        else: self.status_label.setText(f"状态：找不到 '{word}' 的提示音！")
        
    def play_sound_task(self,path):
        try:data,sr=sf.read(path,dtype='float32');sd.play(data,sr);sd.wait()
        except Exception as e: 
            if self.logger: self.logger.log(f"[ERROR] playing sound '{path}': {e}")
            self.parent_window.statusBar().showMessage(f"播放音频失败: {os.path.basename(path)}", 3000)

    def _persistent_recorder_task(self):
        try:
            device_index = self.config['audio_settings'].get('input_device_index', None)
            with sd.InputStream(device=device_index,samplerate=self.config['audio_settings']['sample_rate'],channels=self.config['audio_settings']['channels'],callback=self._audio_callback): self.session_stop_event.wait()
        except Exception as e:
            error_msg = f"无法启动录音，请检查录音设备设置或权限。\n错误详情: {e}"; print(f"持久化录音线程错误: {error_msg}")
            if self.logger: self.logger.log(f"[ERROR] Persistent recorder task failed: {error_msg}")
            self.recording_device_error_signal.emit(error_msg)
            
    def _audio_callback(self, indata, frames, time, status):
        if status: print(f"录音状态警告: {status}", file=sys.stderr)
        try: self.volume_meter_queue.put_nowait(indata.copy())
        except queue.Full: pass
        if self.is_recording: self.audio_queue.put(indata.copy())
        
    def save_recording_task(self, worker):
        if self.audio_queue.empty(): return None 
        data_frames = [];
        while not self.audio_queue.empty():
            try: data_frames.append(self.audio_queue.get_nowait())
            except queue.Empty: break
        if not data_frames: return None
        rec = np.concatenate(data_frames, axis=0); gain = self.config['audio_settings'].get('recording_gain', 1.0)
        if gain != 1.0: rec = np.clip(rec * gain, -1.0, 1.0)
        if self.current_word_index < 0 or self.current_word_index >= len(self.current_word_list):
            if self.logger: self.logger.log(f"[ERROR] Invalid current_word_index ({self.current_word_index}) in save_recording_task.")
            return "save_failed_invalid_index"
        recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower(); word = self.current_word_list[self.current_word_index]['word']; filename = f"{word}.{recording_format}"
        filepath = os.path.join(self.recordings_folder, filename)
        if self.logger: self.logger.log(f"[RECORDING_SAVE_ATTEMPT] Word: '{word}', Format: '{recording_format}', Path: '{filepath}'")
        try:
            sf.write(filepath, rec, self.config['audio_settings']['sample_rate'])
            if self.logger: self.logger.log(f"[RECORDING_SAVE_SUCCESS] File saved successfully.")
            return "save_successful"
        except Exception as e:
            if self.logger: self.logger.log(f"[ERROR] Failed to save recording '{filepath}': {e}")
            if recording_format == 'mp3' and 'format not understood' in str(e).lower():
                 error_msg = "MP3 save failed: LAME encoder is likely missing.";
                 if self.logger: self.logger.log(f"[FATAL] {error_msg}"); return f"save_failed_mp3_encoder"
            return f"save_failed_exception: {e}"

    def run_task_in_thread(self,task_func,*args):
        self.thread=QThread();self.worker=self.Worker(task_func,*args);self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit); self.worker.finished.connect(self.worker.deleteLater); self.thread.finished.connect(self.thread.deleteLater)
        self.worker.progress.connect(self.update_tts_progress); self.worker.error.connect(lambda msg:QMessageBox.critical(self,"后台错误",msg))
        if task_func==self.check_and_generate_audio_logic:self.worker.finished.connect(self.on_tts_finished)
        elif task_func==self.save_recording_task:self.worker.finished.connect(self.on_recording_saved)
        self.thread.start()
        
    def load_word_list_logic(self):
        filename = self.current_wordlist_name
        filepath = os.path.join(self.WORD_LIST_DIR, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"找不到单词表文件: {filename}")

        # [修改] 使用 json.load() 读取并解析
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"词表文件 '{filename}' 不是有效的JSON格式: {e}")

        # 验证文件格式并转换为内部使用的 WORD_GROUPS 格式
        if "meta" not in data or data.get("meta", {}).get("format") != "standard_wordlist" or "groups" not in data:
            raise ValueError(f"词表文件 '{filename}' 格式不正确或不受支持。")

        word_groups = []
        for group_data in data.get("groups", []):
            group_dict = {}
            group_items = group_data.get("items", [])
            for item in group_items:
                # 兼容新旧格式，note 和 lang 都是可选的
                text = item.get("text")
                if text:
                    note = item.get("note", "")
                    lang = item.get("lang", "")
                    group_dict[text] = (note, lang)
            if group_dict:
                word_groups.append(group_dict)
        
        return word_groups
        
    def check_and_generate_audio_logic(self,worker,word_groups):
        wordlist_name, _ = os.path.splitext(self.current_wordlist_name)
        gtts_settings = self.config.get("gtts_settings", {})
        gtts_default_lang = gtts_settings.get("default_lang", "en-us")
        gtts_auto_detect = gtts_settings.get("auto_detect", True)
        all_words_with_lang = {}

        for group_idx, group in enumerate(word_groups):
            if not isinstance(group, dict):
                if self.logger: self.logger.log(f"[WARNING] Word group at index {group_idx} in '{wordlist_name}' is not a dictionary, skipping.")
                continue
            
            for word, value in group.items():
                # 1. Get language from wordlist if specified
                lang = value[1] if isinstance(value, tuple) and len(value) == 2 and value[1] else None
                
                # 2. If not specified, try to auto-detect
                if not lang and gtts_auto_detect:
                    lang = self.detect_language(word)
                
                # 3. If still no language, fallback to default
                if not lang:
                    lang = gtts_default_lang
                
                # [修复] Ensure every word is added to the dictionary, regardless of how its language was determined
                all_words_with_lang[word] = lang
        
        record_audio_folder = os.path.join(self.AUDIO_RECORD_DIR, wordlist_name)
        tts_audio_folder = os.path.join(self.AUDIO_TTS_DIR, wordlist_name)
        if not os.path.exists(tts_audio_folder):
            try:
                os.makedirs(tts_audio_folder)
            except Exception as e:
                return f"创建TTS音频目录失败: {e}"
        
        # [修改] 现在，我们需要检查所有类型的提示音，包括已经由用户录制的。
        # TTS 应该只在完全没有任何提示音（无论是录制的还是已生成的TTS）时才生成。
        # 我们需要检查两个目录：用户录音目录和TTS目录。
        missing = []
        for w in all_words_with_lang:
            # 检查用户录制的语音包
            user_recorded_exists = False
            for ext in ['.wav', '.mp3', '.flac', '.ogg']: # Check common formats
                if os.path.exists(os.path.join(self.AUDIO_RECORD_DIR, wordlist_name, f"{w}{ext}")):
                    user_recorded_exists = True
                    break
            
            # 检查已生成的TTS
            tts_exists = os.path.exists(os.path.join(tts_audio_folder, f"{w}.mp3"))

            if not user_recorded_exists and not tts_exists:
                missing.append(w)

        if not missing:
            if self.logger: self.logger.log("[INFO] No missing TTS audio files to generate.")
            return None
            
        if self.logger: self.logger.log(f"[INFO] Found {len(missing)} missing TTS files. Starting generation...")
        
        total_missing = len(missing)
        errors_occurred = []
        for i, word in enumerate(missing):
            percentage = int(((i + 1) / total_missing) * 100)
            progress_text = f"正在生成TTS ({i+1}/{total_missing}): {word}..."
            worker.progress.emit(percentage, progress_text)
            filepath = os.path.join(tts_audio_folder, f"{word}.mp3")
            try:
                gTTS(text=word, lang=all_words_with_lang[word], slow=False).save(filepath)
                if self.logger: self.logger.log(f"[TTS_SUCCESS] Generated '{word}.mp3' with lang '{all_words_with_lang[word]}'.")
                time.sleep(0.3) # Be nice to Google's servers
            except Exception as e:
                error_detail = f"for '{word}': {e}"
                errors_occurred.append(error_detail)
                if self.logger: self.logger.log(f"[TTS_ERROR] Failed to generate TTS {error_detail}")
        
        if errors_occurred:
            return "部分TTS音频生成失败，请检查日志和网络连接。\n" + "\n".join(errors_occurred[:3])
            
        return None