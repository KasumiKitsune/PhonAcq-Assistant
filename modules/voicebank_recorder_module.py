# --- START OF FILE modules/voicebank_recorder_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "提示音录制"
MODULE_DESCRIPTION = "为标准词表录制高质量的真人提示音，以替代在线TTS。"
# ---

import os
import sys
import threading
import queue
import time
import json

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget,
                             QTableWidgetItem, QMessageBox, QComboBox, QFormLayout,
                             QGroupBox, QProgressBar, QStyle, QHeaderView, QAbstractItemView,
                             QLineEdit) # [新增] 导入 QLineEdit
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, pyqtProperty
from PyQt5.QtGui import QIcon, QPainter, QPen, QPalette, QColor

try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
    DEPENDENCIES_MISSING = False
except ImportError as e:
    DEPENDENCIES_MISSING = True
    MISSING_ERROR_MESSAGE = str(e)

# --- 波形预览控件 (无变动) ---
class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(40)
        self._waveform_data = None
        self._waveformColor = self.palette().color(QPalette.Highlight)
        self._cursorColor = QColor("red")
        self._selectionColor = QColor(0, 100, 255, 60)
    @pyqtProperty(QColor)
    def waveformColor(self): return self._waveformColor
    @waveformColor.setter
    def waveformColor(self, color):
        if self._waveformColor != color: self._waveformColor = color; self.update()
    @pyqtProperty(QColor)
    def cursorColor(self): return self._cursorColor
    @cursorColor.setter
    def cursorColor(self, color):
        if self._cursorColor != color: self._cursorColor = color; self.update()
    @pyqtProperty(QColor)
    def selectionColor(self): return self._selectionColor
    @selectionColor.setter
    def selectionColor(self, color):
        if self._selectionColor != color: self._selectionColor = color; self.update()
    def set_waveform_data(self, audio_filepath):
        self._waveform_data = None
        if not (audio_filepath and os.path.exists(audio_filepath)): self.update(); return
        try:
            data, sr = sf.read(audio_filepath, dtype='float32')
            if data.ndim > 1: data = data.mean(axis=1)
            num_samples = len(data); target_points = self.width() * 2 if self.width() > 0 else 400
            if num_samples <= target_points: self._waveform_data = data
            else:
                step = num_samples // target_points
                peak_data = [np.max(np.abs(data[i:i+step])) for i in range(0, num_samples, step)]
                self._waveform_data = np.array(peak_data)
        except Exception as e: self._waveform_data = None
        self.update()
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.palette().color(QPalette.Base))
        if self._waveform_data is None or len(self._waveform_data) == 0: return
        pen = QPen(self._waveformColor, 1); painter.setPen(pen)
        h, w, num_points = self.height(), self.width(), len(self._waveform_data)
        half_h = h / 2; max_val = np.max(self._waveform_data)
        if max_val == 0: max_val = 1.0
        for i, val in enumerate(self._waveform_data):
            x = int(i * w / num_points); y_offset = (val / max_val) * half_h
            painter.drawLine(x, int(half_h - y_offset), x, int(half_h + y_offset))

# --- 模块入口函数 (无变动) ---
def create_page(parent_window, WORD_LIST_DIR, AUDIO_RECORD_DIR, ToggleSwitchClass, WorkerClass, LoggerClass, icon_manager, resolve_device_func):
    if DEPENDENCIES_MISSING:
        error_page = QWidget(); layout = QVBoxLayout(error_page)
        label = QLabel(f"提示音录制模块加载失败：\n缺少必要的依赖库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install sounddevice soundfile numpy")
        label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); layout.addWidget(label)
        return error_page
    return VoicebankRecorderPage(parent_window, WORD_LIST_DIR, AUDIO_RECORD_DIR, ToggleSwitchClass, WorkerClass, LoggerClass, icon_manager, resolve_device_func)


class VoicebankRecorderPage(QWidget):
    recording_device_error_signal = pyqtSignal(str)

    def __init__(self, parent_window, WORD_LIST_DIR, AUDIO_RECORD_DIR, ToggleSwitchClass, WorkerClass, LoggerClass, icon_manager, resolve_device_func):
        super().__init__()
        self.parent_window = parent_window; self.WORD_LIST_DIR = WORD_LIST_DIR; self.AUDIO_RECORD_DIR = AUDIO_RECORD_DIR
        self.ToggleSwitch = ToggleSwitchClass; self.Worker = WorkerClass; self.LoggerClass = LoggerClass
        self.icon_manager = icon_manager
        self.resolve_device_func = resolve_device_func
        self.config = self.parent_window.config
        self.session_active = False; self.is_recording = False; self.current_word_list = []; self.current_word_index = -1; self.logger = None
        self.audio_folder = None # [新增] 用于存储当前会话的动态文件夹路径
        self.audio_queue = queue.Queue(); self.volume_meter_queue = queue.Queue(maxsize=2)
        self.recording_thread = None; self.session_stop_event = threading.Event()
        self.last_warning_log_time = 0
        
        self._init_ui()
        self._connect_signals()
        self.update_icons()
        self.setFocusPolicy(Qt.StrongFocus)
        self.apply_layout_settings()

    def _init_ui(self):
        main_layout = QHBoxLayout(self); left_layout = QVBoxLayout()
        self.right_panel = QWidget(); right_layout = QVBoxLayout(self.right_panel)
        self.list_widget = QTableWidget()
        self.list_widget.setColumnCount(3)
        self.list_widget.setHorizontalHeaderLabels(["词语", "IPA/备注", "波形预览"])
        self.list_widget.verticalHeader().setVisible(False)
        self.list_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setWordWrap(True)
        header = self.list_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive); header.setSectionResizeMode(1, QHeaderView.Interactive); header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setStretchLastSection(True)
        self.list_widget.setToolTip("当前词表中所有需要录制的词语。\n- 绿色对勾表示已录制。\n- 双击任意行可试听已录制的音频。")
        self.status_label = QLabel("状态：请选择一个单词表开始录制。")
        left_layout.addWidget(QLabel("待录制词语列表:")); left_layout.addWidget(self.list_widget); left_layout.addWidget(self.status_label)
        
        control_group = QGroupBox("控制面板"); self.control_layout = QFormLayout(control_group) 
        self.word_list_combo = QComboBox(); self.word_list_combo.setToolTip("选择一个用于录制提示音的单词表。")
        
        # [核心修改] 新增批次名称输入框
        self.session_name_input = QLineEdit()
        self.session_name_input.setToolTip("为本次录制指定一个批次名称。\n如果名称已存在，程序会自动在后面添加数字后缀 (如 _1, _2)。\n留空则默认使用词表名。")
        
        self.start_btn = QPushButton("加载词表并开始"); self.start_btn.setObjectName("AccentButton"); self.start_btn.setToolTip("加载选中的单词表，并开始一个新的录制会话。")
        self.end_session_btn = QPushButton("结束当前会话"); self.end_session_btn.setObjectName("ActionButton_Delete"); self.end_session_btn.setToolTip("提前结束当前的录制会话。")
        
        self.control_layout.addRow("选择单词表:", self.word_list_combo)
        self.control_layout.addRow("录音批次名称:", self.session_name_input) # 新增的行
        self.control_layout.addRow(self.start_btn)
        self.control_layout.addRow(self.end_session_btn)

        self.end_session_btn.hide()
        self.recording_status_panel = QGroupBox("录音状态"); status_panel_layout = QVBoxLayout(self.recording_status_panel)
        self.recording_indicator = QLabel("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_label = QLabel("当前音量:"); self.volume_meter = QProgressBar(); self.volume_meter.setRange(0, 100); self.volume_meter.setValue(0); self.volume_meter.setTextVisible(False)
        status_panel_layout.addWidget(self.recording_indicator); status_panel_layout.addWidget(self.volume_label); status_panel_layout.addWidget(self.volume_meter)
        self.update_timer = QTimer(); self.update_timer.timeout.connect(self.update_volume_meter)
        
        self.record_btn = QPushButton("按住录音"); self.record_btn.setEnabled(False); self.record_btn.setToolTip("按住此按钮或键盘的回车键，为当前选中的词语录音。")
        
        right_layout.addWidget(control_group); right_layout.addStretch(); right_layout.addWidget(self.recording_status_panel); right_layout.addWidget(self.record_btn)
        main_layout.addLayout(left_layout, 2); main_layout.addWidget(self.right_panel, 1)

    def _connect_signals(self):
        self.start_btn.clicked.connect(self.start_session)
        self.end_session_btn.clicked.connect(self.end_session)
        self.record_btn.pressed.connect(self.start_recording)
        self.record_btn.released.connect(self.stop_recording)
        self.recording_device_error_signal.connect(self.show_recording_device_error)
        self.word_list_combo.currentIndexChanged.connect(self.on_wordlist_selection_changed) # 新增连接
        self.list_widget.cellDoubleClicked.connect(self.on_cell_double_clicked) # 新增连接

    def on_wordlist_selection_changed(self, index):
        """当用户选择新词表时，自动填充批次名称。"""
        wordlist_filename = self.word_list_combo.itemText(index)
        if wordlist_filename:
            base_name, _ = os.path.splitext(wordlist_filename)
            self.session_name_input.setText(base_name)

    def on_cell_double_clicked(self, row, column):
        """处理双击事件，用于试听。"""
        self.replay_audio(row)
        
    def replay_audio(self, row):
        """播放指定行号的音频。"""
        if not self.session_active or not (0 <= row < len(self.current_word_list)):
            return
            
        word = self.current_word_list[row]['word']
        filepath = self._find_existing_audio(word)
        if filepath:
            self.log(f"正在试听: {os.path.basename(filepath)}")
            self._robust_play_sound(filepath)
        else:
            self.log(f"提示: '{word}' 尚未录制，无法试听。")

    def update_item_quality_status(self, row, warnings):
        """
        由质量分析器插件在分析完成后调用。
        此方法负责更新内部状态并触发UI刷新。
        """
        if not (0 <= row < len(self.current_word_list)):
            return

        # 获取对应的QTableWidgetItem
        list_item = self.list_widget.item(row, 0) # 词语列的QTableWidgetItem
        if not list_item:
            return

        original_tooltip_text = self.current_word_list[row]['word'] # 获取原始词语文本作为Tooltip基础

        analyzer_plugin = getattr(self, 'quality_analyzer_plugin', None)
        if not analyzer_plugin: # 如果插件不存在，则默认显示成功图标
            list_item.setIcon(self.icon_manager.get_icon("success"))
            list_item.setToolTip(original_tooltip_text)
            return

        if not warnings:
            list_item.setIcon(self.icon_manager.get_icon("success"))
            list_item.setToolTip(original_tooltip_text)
        else:
            # 根据警告类型设置不同图标
            has_critical = any(w['type'] in analyzer_plugin.critical_warnings for w in warnings)
            list_item.setIcon(analyzer_plugin.warning_icon if has_critical else analyzer_plugin.info_icon)
            
            # 构建详细的Tooltip
            html = f"<b>{original_tooltip_text}</b><hr>"
            html += "<b>质量报告:</b><br>"
            warning_list_html = [
                f"• <b>{analyzer_plugin.warning_type_map.get(w['type'], w['type'])}:</b> {w['details']}"
                for w in warnings
            ]
            html += "<br>".join(warning_list_html)
            list_item.setToolTip(html)
            
    def _robust_play_sound(self, path):
        """在一个独立的非守护线程中播放音频，避免UI卡顿。"""
        playback_thread = threading.Thread(target=self._play_sound_task, args=(path,), daemon=False)
        playback_thread.start()

    def _play_sound_task(self, path):
        """实际执行音频播放的线程任务。"""
        try:
            data, sr = sf.read(path)
            sd.play(data, sr)
            sd.wait()
        except Exception as e:
            print(f"播放音频 '{path}' 失败: {e}")

    def start_session(self):
        wordlist_file = self.word_list_combo.currentText()
        if not wordlist_file:
            QMessageBox.warning(self, "错误", "请先选择一个单词表。")
            return

        # [核心重构] 实现带版本控制的文件夹创建逻辑
        session_base_name = self.session_name_input.text().strip()
        if not session_base_name:
            session_base_name, _ = os.path.splitext(wordlist_file) # 如果留空，默认使用词表名

        # 确定最终的、唯一的文件夹名称
        final_folder_name = session_base_name
        i = 1
        while os.path.exists(os.path.join(self.AUDIO_RECORD_DIR, final_folder_name)):
            final_folder_name = f"{session_base_name}_{i}"
            i += 1
        
        self.audio_folder = os.path.join(self.AUDIO_RECORD_DIR, final_folder_name)
        os.makedirs(self.audio_folder)
        
        self.log(f"新录音批次文件夹已创建: {final_folder_name}")

        self.logger = None
        if self.config.get("app_settings", {}).get("enable_logging", True):
            self.logger = self.LoggerClass(os.path.join(self.audio_folder, "log.txt"))
            
        try:
            word_groups = self.load_word_list_logic(wordlist_file)
            self.current_word_list = []
            for group in word_groups:
                for word, value in group.items():
                    ipa = value[0] if isinstance(value, tuple) else str(value)
                    self.current_word_list.append({'word': word, 'ipa': ipa})
            
            self.current_word_index = 0
            if self.logger:
                self.logger.log(f"[SESSION_START] Voicebank recording for wordlist: '{wordlist_file}'")
                self.logger.log(f"[SESSION_CONFIG] Batch Name: '{session_base_name}', Final Output Folder: '{self.audio_folder}'")

            self.session_stop_event.clear()
            self.recording_thread = threading.Thread(target=self._persistent_recorder_task, daemon=True)
            self.recording_thread.start()
            self.update_timer.start(30)
            
            self.word_list_combo.hide()
            self.session_name_input.hide() # 隐藏批次名称输入框
            self.start_btn.hide()
            self.end_session_btn.show()

            self.update_list_widget()
            self.record_btn.setEnabled(True)
            self.log("准备就绪，请选择词语并录音。")
            self.session_active = True
        except Exception as e: 
            if self.logger: self.logger.log(f"[ERROR] Failed to start session: {e}")
            QMessageBox.critical(self, "错误", f"加载单词表失败: {e}")
            self.session_active = False
            # 如果启动失败，需要清理已创建的空文件夹
            if os.path.exists(self.audio_folder) and not os.listdir(self.audio_folder):
                os.rmdir(self.audio_folder)

    def reset_ui(self):
        self.word_list_combo.show()
        self.session_name_input.show() # 显示批次名称输入框
        self.start_btn.show()
        self.end_session_btn.hide()
        
        self.list_widget.setRowCount(0)
        self.record_btn.setEnabled(False)
        self.log("请选择一个单词表开始录制。")
        # 触发一次默认值填充
        self.on_wordlist_selection_changed(self.word_list_combo.currentIndex())

    # --- 其他方法保持不变，但需要确保它们使用了 self.audio_folder ---
    # ... (resizeEvent, update_icons, apply_layout_settings, etc. - 无需修改) ...
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.list_widget.width() > 0:
            w1 = int(self.list_widget.width() * 0.5); w2 = int(self.list_widget.width() * 0.25)
            self.list_widget.setColumnWidth(0, w1); self.list_widget.setColumnWidth(1, w2); self.list_widget.setColumnWidth(2, self.list_widget.width() - w1 - w2 - 20)
    def update_icons(self):
        self.start_btn.setIcon(self.icon_manager.get_icon("start_session")); self.end_session_btn.setIcon(self.icon_manager.get_icon("end_session"))
        self.record_btn.setIcon(self.icon_manager.get_icon("record")); self.update_list_widget_icons()
    def update_list_widget_icons(self):
        if not self.session_active: return
        for index in range(self.list_widget.rowCount()):
            item = self.list_widget.item(index, 0);
            if not item: continue
            if self._find_existing_audio(item.text()): item.setIcon(self.icon_manager.get_icon("success"))
            else: item.setIcon(QIcon())
    def apply_layout_settings(self):
        self.right_panel.setFixedWidth(self.config.get("ui_settings", {}).get("collector_sidebar_width", 320))
    def load_config_and_prepare(self):
        self.config = self.parent_window.config; self.apply_layout_settings()
        if not self.session_active: self.populate_word_lists()
    def _audio_callback(self, indata, frames, time, status):
        if status:
            current_time = time.monotonic()
            if current_time - self.last_warning_log_time > 5: self.last_warning_log_time = current_time; print(f"Audio callback status: {status}", file=sys.stderr)
        try: self.volume_meter_queue.put_nowait(indata.copy())
        except queue.Full: pass
        if self.is_recording:
            try: self.audio_queue.put(indata.copy())
            except queue.Full: pass
    def show_recording_device_error(self, error_message):
        QMessageBox.critical(self, "录音设备错误", error_message); self.log("录音设备错误，请检查设置。")
        if self.session_active: self.end_session(force=True)
    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.record_btn.isEnabled(): self.start_recording(); event.accept()
        else: super().keyPressEvent(event)
    def keyReleaseEvent(self, event):
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.is_recording: self.stop_recording(); event.accept()
        else: super().keyReleaseEvent(event)
    def update_volume_meter(self):
        try: data_chunk = self.volume_meter_queue.get_nowait(); volume_norm = np.linalg.norm(data_chunk) * 20; self.volume_meter.setValue(int(volume_norm))
        except queue.Empty: self.volume_meter.setValue(int(self.volume_meter.value() * 0.8))
        except Exception: pass
    def start_recording(self):
        if not self.session_active or self.is_recording: return
        self.current_word_index = self.list_widget.currentRow()
        if self.current_word_index == -1: self.log("请先在列表中选择一个词！"); return
        while not self.audio_queue.empty():
            try: self.audio_queue.get_nowait()
            except queue.Empty: break
        self.is_recording = True; self.recording_indicator.setText("● 正在录音"); self.recording_indicator.setStyleSheet("color: red;"); self.record_btn.setText("正在录音..."); self.record_btn.setStyleSheet("background-color: #f44336; color: white;")
        word_to_record = self.current_word_list[self.current_word_index]['word']; self.log(f"录制 '{word_to_record}'");
        if self.logger: self.logger.log(f"[RECORD_START] Word: '{word_to_record}'")
    def stop_recording(self):
        if not self.session_active or not self.is_recording: return
        self.is_recording = False; self.recording_indicator.setText("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;"); self.record_btn.setText("按住录音"); self.record_btn.setStyleSheet(""); self.log("正在保存..."); self.run_task_in_thread(self.save_recording_task)
    def log(self, msg): self.status_label.setText(f"状态: {msg}")
    def populate_word_lists(self):
        self.word_list_combo.clear();
        if os.path.exists(self.WORD_LIST_DIR): self.word_list_combo.addItems([f for f in os.listdir(self.WORD_LIST_DIR) if f.endswith('.json')])
        self.on_wordlist_selection_changed(self.word_list_combo.currentIndex())
    def end_session(self, force=False):
        if not force:
            if QMessageBox.question(self, '结束会话', '您确定要结束当前的语音包录制会话吗？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        if self.logger: self.logger.log("[SESSION_END] Session ended by user.")
        self.update_timer.stop(); self.volume_meter.setValue(0); self.session_stop_event.set()
        if self.recording_thread and self.recording_thread.is_alive(): self.recording_thread.join(timeout=1.0)
        self.recording_thread = None; self.session_active = False; self.current_word_list = []; self.current_word_index = -1; self.logger = None; self.audio_folder = None; self.reset_ui()
    def _find_existing_audio(self, word):
        if not self.audio_folder: return None
        for ext in ['.wav', '.mp3', '.flac', '.ogg']:
             path = os.path.join(self.audio_folder, f"{word}{ext}")
             if os.path.exists(path): return path
        return None
    def update_list_widget(self):
        current_row = self.list_widget.currentRow();
        if current_row == -1 and self.current_word_list: current_row = 0
        self.list_widget.setRowCount(0); self.list_widget.setRowCount(len(self.current_word_list))
        for i, item_data in enumerate(self.current_word_list):
            word_item = QTableWidgetItem(item_data['word']); ipa_item = QTableWidgetItem(item_data['ipa'])
            self.list_widget.setItem(i, 0, word_item); self.list_widget.setItem(i, 1, ipa_item)
            waveform_widget = WaveformWidget(self); self.list_widget.setCellWidget(i, 2, waveform_widget)
            filepath = self._find_existing_audio(item_data['word'])
            if filepath: word_item.setIcon(self.icon_manager.get_icon("success")); waveform_widget.set_waveform_data(filepath)
        self.list_widget.resizeRowsToContents()
        if self.current_word_list and 0 <= current_row < len(self.current_word_list): self.list_widget.setCurrentCell(current_row, 0)
    def on_recording_saved(self, result):
        if result == "save_failed_mp3_encoder": QMessageBox.critical(self, "MP3 编码器缺失", "无法将录音保存为 MP3 格式..."); self.log("MP3保存失败！"); return
        self.log("录音已保存.")
        item = self.list_widget.item(self.current_word_index, 0);
        filepath = self._find_existing_audio(self.current_word_list[self.current_word_index]['word'])
        
        waveform_widget = self.list_widget.cellWidget(self.current_word_index, 2)
        if isinstance(waveform_widget, WaveformWidget):
            if filepath: waveform_widget.set_waveform_data(filepath)

        # 确保这里调用了质量分析插件的回调
        analyzer_plugin = getattr(self, 'quality_analyzer_plugin', None)
        if analyzer_plugin and filepath:
            analyzer_plugin.analyze_and_update_ui('voicebank_recorder', filepath, self.current_word_index)
        else:
            # 如果插件不存在或文件路径无效，仍然需要更新为成功图标
            if item: item.setIcon(self.icon_manager.get_icon("success"))
            item.setToolTip(self.current_word_list[self.current_word_index]['word']) # 确保Tooltip也被重置为原始词语
        waveform_widget = self.list_widget.cellWidget(self.current_word_index, 2)
        if isinstance(waveform_widget, WaveformWidget) and filepath: waveform_widget.set_waveform_data(filepath)
        analyzer_plugin = getattr(self, 'quality_analyzer_plugin', None)
        if analyzer_plugin and filepath: analyzer_plugin.analyze_and_update_ui('voicebank_recorder', filepath, self.current_word_index)
        if self.current_word_index + 1 < len(self.current_word_list): self.list_widget.setCurrentCell(self.current_word_index + 1, 0)
        else:
            all_done = all(self._find_existing_audio(item['word']) for item in self.current_word_list)
            if all_done:
                if self.logger: self.logger.log("[INFO] All items in the list have been recorded."); QMessageBox.information(self,"完成","所有词条已录制完毕！");
                if self.session_active: self.end_session()
    def _persistent_recorder_task(self):
        try:
            device_index = self.resolve_device_func(self.config)
            with sd.InputStream(device=device_index, samplerate=self.config['audio_settings']['sample_rate'], channels=self.config['audio_settings']['channels'], callback=self._audio_callback): self.session_stop_event.wait()
        except Exception as e: self.recording_device_error_signal.emit(f"无法启动录音: {e}")
    def save_recording_task(self, worker_instance):
        if self.audio_queue.empty(): return
        data_chunks = [];
        while not self.audio_queue.empty():
            try: data_chunks.append(self.audio_queue.get_nowait())
            except queue.Empty: break
        if not data_chunks: return
        rec = np.concatenate(data_chunks, axis=0); gain = self.config['audio_settings'].get('recording_gain', 1.0)
        if gain != 1.0: rec = np.clip(rec * gain, -1.0, 1.0)
        word = self.current_word_list[self.current_word_index]['word']; recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower(); filename = f"{word}.{recording_format}"; filepath = os.path.join(self.audio_folder, filename)
        if self.logger: self.logger.log(f"[RECORDING_SAVE_ATTEMPT] Word: '{word}', Format: '{recording_format}', Path: '{filepath}'")
        try: sf.write(filepath, rec, self.config['audio_settings']['sample_rate']);
        except Exception as e:
            if 'format not understood' in str(e).lower() and recording_format == 'mp3': return "save_failed_mp3_encoder"
            try: wav_path = os.path.splitext(filepath)[0] + ".wav"; sf.write(wav_path, rec, self.config['audio_settings']['sample_rate'])
            except Exception as e_wav: print(f"回退保存WAV也失败: {e_wav}")
    def run_task_in_thread(self,task_func,*args):
        self.thread=QThread();self.worker=self.Worker(task_func,*args);self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run);self.worker.finished.connect(self.thread.quit); self.worker.finished.connect(self.worker.deleteLater);self.thread.finished.connect(self.thread.deleteLater); self.worker.error.connect(lambda msg:QMessageBox.critical(self,"后台错误",msg))
        if task_func==self.save_recording_task: self.worker.finished.connect(self.on_recording_saved)
        self.thread.start()
    def load_word_list_logic(self,filename):
        filepath=os.path.join(self.WORD_LIST_DIR,filename)
        if not os.path.exists(filepath): raise FileNotFoundError(f"找不到单词表文件: {filename}")
        try:
            with open(filepath, 'r', encoding='utf-8') as f: data = json.load(f)
        except json.JSONDecodeError as e: raise ValueError(f"词表文件 '{filename}' 不是有效的JSON格式: {e}")
        if "meta" not in data or data.get("meta", {}).get("format") != "standard_wordlist" or "groups" not in data: raise ValueError(f"词表文件 '{filename}' 格式不正确或不受支持。")
        word_groups = []
        for group_data in data.get("groups", []):
            group_dict = {}
            for item in group_data.get("items", []):
                text = item.get("text")
                if text: note = item.get("note", ""); lang = item.get("lang", ""); group_dict[text] = (note, lang)
            if group_dict: word_groups.append(group_dict)
        return word_groups