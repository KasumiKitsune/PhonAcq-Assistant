# --- START OF FILE voicebank_recorder_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "语音包录制"
MODULE_DESCRIPTION = "为标准词表录制高质量的真人提示音，以替代在线TTS。"
# ---

import os
import sys
import threading
import queue
import importlib.util

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QMessageBox, QComboBox, QFormLayout,
                             QGroupBox, QProgressBar, QStyle)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal

try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
    DEPENDENCIES_MISSING = False
except ImportError as e:
    print(f"CRITICAL: voicebank_recorder_module.py - Missing dependencies: {e}")
    DEPENDENCIES_MISSING = True
    MISSING_ERROR_MESSAGE = str(e)


# ===== [修改] 标准化模块入口函数，接收LoggerClass =====
def create_page(parent_window, WORD_LIST_DIR, AUDIO_RECORD_DIR, ToggleSwitchClass, WorkerClass, LoggerClass):
    """模块的入口函数，用于创建页面。"""
    if DEPENDENCIES_MISSING:
        error_page = QWidget()
        layout = QVBoxLayout(error_page)
        label = QLabel(f"语音包录制模块加载失败：\n缺少必要的依赖库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install sounddevice soundfile numpy")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        return error_page

    return VoicebankRecorderPage(parent_window, WORD_LIST_DIR, AUDIO_RECORD_DIR, ToggleSwitchClass, WorkerClass, LoggerClass)


class VoicebankRecorderPage(QWidget):
    LINE_WIDTH_THRESHOLD = 90
    recording_device_error_signal = pyqtSignal(str)

    # [修改] 更新 __init__ 以接收 LoggerClass
    def __init__(self, parent_window, WORD_LIST_DIR, AUDIO_RECORD_DIR, ToggleSwitchClass, WorkerClass, LoggerClass):
        super().__init__()
        self.parent_window = parent_window
        self.WORD_LIST_DIR = WORD_LIST_DIR
        self.AUDIO_RECORD_DIR = AUDIO_RECORD_DIR
        self.ToggleSwitch = ToggleSwitchClass
        self.Worker = WorkerClass
        self.LoggerClass = LoggerClass # [新增] 保存Logger类
        self.config = self.parent_window.config

        self.session_active = False
        self.is_recording = False
        self.current_word_list = []
        self.current_word_index = -1
        self.logger = None # [新增] 初始化logger实例为None
        
        # 分别初始化两个队列
        self.audio_queue = queue.Queue()
        self.volume_meter_queue = queue.Queue(maxsize=2)

        self.recording_thread = None
        self.session_stop_event = threading.Event()
        
        self._init_ui()

        self.start_btn.clicked.connect(self.start_session)
        self.end_session_btn.clicked.connect(self.end_session)
        self.record_btn.pressed.connect(self.start_recording)
        self.record_btn.released.connect(self.stop_recording)
        self.recording_device_error_signal.connect(self.show_recording_device_error)
        
        self.setFocusPolicy(Qt.StrongFocus)
        self.apply_layout_settings()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        left_layout = QVBoxLayout()
        
        self.right_panel = QWidget() 
        right_layout = QVBoxLayout(self.right_panel)

        self.list_widget = QListWidget()
        self.status_label = QLabel("状态：请选择一个单词表开始录制。")
        left_layout.addWidget(QLabel("待录制词语列表:"))
        left_layout.addWidget(self.list_widget)
        left_layout.addWidget(self.status_label)
        
        control_group = QGroupBox("控制面板")
        self.control_layout = QFormLayout(control_group) 
        
        self.word_list_combo = QComboBox()
        self.start_btn = QPushButton("加载词表并开始")
        self.start_btn.setObjectName("AccentButton")
        self.end_session_btn = QPushButton("结束当前会话")
        self.end_session_btn.setObjectName("ActionButton_Delete")
        self.end_session_btn.hide()
        
        self.control_layout.addRow("选择单词表:", self.word_list_combo)
        self.control_layout.addRow(self.start_btn)
        
        self.recording_status_panel = QGroupBox("录音状态")
        status_panel_layout = QVBoxLayout(self.recording_status_panel)
        self.recording_indicator = QLabel("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_label = QLabel("当前音量:")
        self.volume_meter = QProgressBar(); self.volume_meter.setRange(0, 100); self.volume_meter.setValue(0); self.volume_meter.setTextVisible(False)
        status_panel_layout.addWidget(self.recording_indicator); status_panel_layout.addWidget(self.volume_label); status_panel_layout.addWidget(self.volume_meter)
        self.update_timer = QTimer(); self.update_timer.timeout.connect(self.update_volume_meter)
        
        self.record_btn = QPushButton("按住录音"); self.record_btn.setEnabled(False)
        
        right_layout.addWidget(control_group); right_layout.addStretch()
        right_layout.addWidget(self.recording_status_panel)
        right_layout.addWidget(self.record_btn)
        
        main_layout.addLayout(left_layout, 2)
        main_layout.addWidget(self.right_panel, 1)

    def apply_layout_settings(self):
        ui_settings = self.config.get("ui_settings", {})
        width = ui_settings.get("collector_sidebar_width", 320)
        self.right_panel.setFixedWidth(width)

    def load_config_and_prepare(self):
        self.config = self.parent_window.config
        self.apply_layout_settings()
        if not self.session_active:
            self.populate_word_lists()
            
    def show_recording_device_error(self, error_message):
        QMessageBox.critical(self, "录音设备错误", error_message)
        log_message = f"录音设备错误，请检查设置。"
        self.log(log_message)
        if self.logger: self.logger.log(f"[FATAL] {log_message} Details: {error_message}")
        self.record_btn.setEnabled(False)
        if self.session_active:
            self.end_session(force=True)

    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.record_btn.isEnabled():
                self.start_recording()
                event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.is_recording:
                self.stop_recording()
                event.accept()
        else:
            super().keyReleaseEvent(event)
    
    def _get_weighted_length(self, text):
        length = 0
        for char in text:
            if '\u4e00' <= char <= '\u9fff' or \
               '\u3040' <= char <= '\u30ff' or \
               '\uff00' <= char <= '\uffef':
                length += 2
            else:
                length += 1
        return length

    def _format_list_item_text(self, word, ipa):
        ipa_display = f"({ipa})" if ipa else ""
        total_weighted_length = self._get_weighted_length(word) + self._get_weighted_length(ipa_display)
        if total_weighted_length > self.LINE_WIDTH_THRESHOLD and ipa_display:
            return f"{word}\n{ipa_display}"
        else:
            return f"{word} {ipa_display}".strip()

    def update_volume_meter(self):
        try:
            data_chunk = self.volume_meter_queue.get_nowait()
            if data_chunk is not None:
                volume_norm = np.linalg.norm(data_chunk) * 20
                self.volume_meter.setValue(int(volume_norm))
        except queue.Empty:
            self.volume_meter.setValue(int(self.volume_meter.value() * 0.8))
        except Exception as e:
            print(f"Error calculating volume: {e}")

    def start_recording(self):
        if not self.session_active or self.is_recording:
            return
            
        self.current_word_index = self.list_widget.currentRow()
        if self.current_word_index == -1: 
            self.log("请先在列表中选择一个词！")
            return

        while not self.audio_queue.empty():
            try: self.audio_queue.get_nowait()
            except queue.Empty: break

        self.is_recording = True
        self.recording_indicator.setText("● 正在录音"); self.recording_indicator.setStyleSheet("color: red;")
        self.record_btn.setText("正在录音..."); self.record_btn.setStyleSheet("background-color: #f44336; color: white;")
        
        word_to_record = self.current_word_list[self.current_word_index]['word']
        self.log(f"录制 '{word_to_record}'")
        if self.logger:
            self.logger.log(f"[RECORD_START] Word: '{word_to_record}'")
        
    def stop_recording(self):
        if not self.session_active or not self.is_recording:
            return

        self.is_recording = False
        self.recording_indicator.setText("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.record_btn.setText("按住录音"); self.record_btn.setStyleSheet("")
        self.log("正在保存...")
        self.run_task_in_thread(self.save_recording_task)
    
    def log(self, msg): self.status_label.setText(f"状态: {msg}")
    
    def populate_word_lists(self):
        self.word_list_combo.clear()
        if os.path.exists(self.WORD_LIST_DIR): 
            self.word_list_combo.addItems([f for f in os.listdir(self.WORD_LIST_DIR) if f.endswith('.py')])
        
    def reset_ui(self):
        self.word_list_combo.show()
        self.start_btn.show()

        if self.end_session_btn.parent() is not None:
             self.control_layout.removeRow(self.end_session_btn)

        self.list_widget.clear()
        self.record_btn.setEnabled(False)
        self.log("请选择一个单词表开始录制。")
    
    def end_session(self, force=False):
        if not force:
            reply = QMessageBox.question(self, '结束会话', '您确定要结束当前的语音包录制会话吗？',
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        if self.logger:
            self.logger.log("[SESSION_END] Session ended by user.")

        self.update_timer.stop()
        self.volume_meter.setValue(0)

        self.session_stop_event.set()
        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=1.0)
        self.recording_thread = None

        self.session_active = False
        self.current_word_list = []
        self.current_word_index = -1
        self.logger = None
        self.reset_ui()

    def start_session(self):
        wordlist_file=self.word_list_combo.currentText()
        if not wordlist_file: QMessageBox.warning(self,"错误","请先选择一个单词表。");return
        wordlist_name,_=os.path.splitext(wordlist_file)
        self.audio_folder=os.path.join(self.AUDIO_RECORD_DIR,wordlist_name)
        if not os.path.exists(self.audio_folder): os.makedirs(self.audio_folder)
        
        self.logger = None
        if self.config.get("app_settings", {}).get("enable_logging", True):
            self.logger = self.LoggerClass(os.path.join(self.audio_folder, "log.txt"))
        
        try:
            word_groups=self.load_word_list_logic(wordlist_file)
            self.current_word_list=[]
            for group in word_groups:
                for word,value in group.items():
                    ipa=value[0] if isinstance(value,tuple) else str(value)
                    self.current_word_list.append({'word':word,'ipa':ipa})
            self.current_word_index=0
            
            if self.logger:
                self.logger.log(f"[SESSION_START] Voicebank recording for wordlist: '{wordlist_file}'")
                self.logger.log(f"[SESSION_CONFIG] Output folder: '{self.audio_folder}'")

            self.session_stop_event.clear()
            self.recording_thread = threading.Thread(target=self._persistent_recorder_task, daemon=True)
            self.recording_thread.start()
            self.update_timer.start(30)
            
            self.word_list_combo.hide()
            self.start_btn.hide()
            self.end_session_btn = QPushButton("结束当前会话")
            self.end_session_btn.setObjectName("ActionButton_Delete")
            self.end_session_btn.clicked.connect(self.end_session)
            self.end_session_btn.show()
            self.control_layout.addRow(self.end_session_btn)

            self.update_list_widget()
            self.record_btn.setEnabled(True)
            self.log("准备就绪，请选择词语并录音。")
            self.session_active = True

        except Exception as e: 
            if self.logger:
                self.logger.log(f"[ERROR] Failed to start session: {e}")
            QMessageBox.critical(self,"错误",f"加载单词表失败: {e}")
            self.session_active = False
        
    def update_list_widget(self):
        current_row = self.list_widget.currentRow()
        if current_row == -1 and self.current_word_list: current_row = 0

        self.list_widget.clear()
        recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower()
        
        for item_data in self.current_word_list:
            display_text = self._format_list_item_text(item_data['word'], item_data['ipa'])
            item = QListWidgetItem(display_text)
            
            main_filepath = os.path.join(self.audio_folder, f"{item_data['word']}.{recording_format}")
            fallback_filepath = os.path.join(self.audio_folder, f"{item_data['word']}.wav")

            if os.path.exists(main_filepath) or (recording_format == 'mp3' and os.path.exists(fallback_filepath)):
                item.setIcon(self.style().standardIcon(QStyle.SP_DialogOkButton))
            
            self.list_widget.addItem(item)
            
        if self.current_word_list and 0 <= current_row < len(self.current_word_list):
             self.list_widget.setCurrentRow(current_row)
             
    def on_recording_saved(self, result):
        if result == "save_failed_mp3_encoder":
            QMessageBox.critical(self, "MP3 编码器缺失", 
                "无法将录音保存为 MP3 格式。\n\n"
                "这通常是因为您的系统中缺少 LAME MP3 编码器库 (例如 libmp3lame)。\n\n"
                "建议：请在“程序设置”中将录音格式切换为 WAV (高质量)，或为您的系统安装 LAME 编码器。")
            self.log("MP3保存失败！请检查编码器或设置。")
            return

        self.log("录音已保存。")
        self.update_list_widget() 
        
        if self.current_word_index + 1 < len(self.current_word_list):
            self.current_word_index += 1
            self.list_widget.setCurrentRow(self.current_word_index)
        else: 
            all_done = True
            recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower()
            for item_data in self.current_word_list:
                main_filepath = os.path.join(self.audio_folder, f"{item_data.get('word')}.{recording_format}")
                fallback_filepath = os.path.join(self.audio_folder, f"{item_data.get('word')}.wav")
                if not os.path.exists(main_filepath) and not (recording_format == 'mp3' and os.path.exists(fallback_filepath)):
                    all_done = False
                    break
            if all_done:
                if self.logger: self.logger.log("[INFO] All items in the list have been recorded.")
                QMessageBox.information(self,"完成","所有词条已录制完毕！")
                if self.session_active: self.end_session()
        
    def _persistent_recorder_task(self):
        try:
            device_index = self.config['audio_settings'].get('input_device_index', None)
            with sd.InputStream(
                device=device_index,
                samplerate=self.config['audio_settings']['sample_rate'],
                channels=self.config['audio_settings']['channels'],
                callback=self._audio_callback
            ): 
                self.session_stop_event.wait()
        except Exception as e:
            error_msg = f"无法启动录音，请检查设备设置或权限。\n错误详情: {e}"
            print(f"持久化录音线程错误 (Voicebank): {error_msg}")
            self.recording_device_error_signal.emit(error_msg)

    def _audio_callback(self, indata, frames, time, status):
        if status:
            print(f"录音状态警告: {status}", file=sys.stderr)
        
        try:
            self.volume_meter_queue.put_nowait(indata.copy())
        except queue.Full:
            pass

        if self.is_recording:
            self.audio_queue.put(indata.copy())

    def save_recording_task(self, worker_instance):
        if self.audio_queue.empty(): return
        
        data_chunks = []
        while not self.audio_queue.empty():
            try:
                data_chunks.append(self.audio_queue.get_nowait())
            except queue.Empty:
                break
        
        if not data_chunks: return

        rec = np.concatenate(data_chunks, axis=0)
        gain = self.config['audio_settings'].get('recording_gain', 1.0)
        if gain != 1.0: rec = np.clip(rec * gain, -1.0, 1.0)
        
        word = self.current_word_list[self.current_word_index]['word']
        recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower()
        filename = f"{word}.{recording_format}"
        filepath = os.path.join(self.audio_folder, filename)
        
        if self.logger:
            self.logger.log(f"[RECORDING_SAVE_ATTEMPT] Word: '{word}', Format: '{recording_format}', Path: '{filepath}'")
        
        try:
            sf.write(filepath, rec, self.config['audio_settings']['sample_rate'])
            if self.logger:
                self.logger.log("[RECORDING_SAVE_SUCCESS] File saved successfully.")
        except Exception as e:
            log_msg = f"保存 {recording_format.upper()} 失败: {e}"
            self.log(log_msg)
            if self.logger:
                self.logger.log(f"[ERROR] {log_msg}")

            if recording_format == 'mp3' and 'format not understood' in str(e).lower():
                return "save_failed_mp3_encoder"

            if recording_format != 'wav':
                try:
                    wav_path = os.path.splitext(filepath)[0] + ".wav"
                    sf.write(wav_path, rec, self.config['audio_settings']['sample_rate'])
                    fallback_log_msg = f"已尝试回退保存为WAV格式: {os.path.basename(wav_path)}"
                    self.log(fallback_log_msg)
                    if self.logger:
                        self.logger.log(f"[INFO] {fallback_log_msg}")
                except Exception as e_wav:
                    fallback_err_msg = f"回退保存WAV也失败: {e_wav}"
                    self.log(fallback_err_msg)
                    if self.logger:
                        self.logger.log(f"[ERROR] {fallback_err_msg}")
            
    def run_task_in_thread(self,task_func,*args):
        self.thread=QThread();self.worker=self.Worker(task_func,*args);self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run);self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater);self.thread.finished.connect(self.thread.deleteLater)
        self.worker.error.connect(lambda msg:QMessageBox.critical(self,"后台错误",msg))
        if task_func==self.save_recording_task:
            self.worker.finished.connect(self.on_recording_saved)
        self.thread.start()
        
    def load_word_list_logic(self,filename):
        filepath=os.path.join(self.WORD_LIST_DIR,filename)
        if not os.path.exists(filepath):raise FileNotFoundError(f"找不到单词表文件: {filename}")
        spec=importlib.util.spec_from_file_location("word_list_module",filepath);module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module);return module.WORD_GROUPS