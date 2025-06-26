# --- START OF FILE voicebank_recorder_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "语音包录制"
MODULE_DESCRIPTION = "为标准词表录制高质量的真人提示音，以替代在线TTS。"
# ---

import os
import threading
import queue
import importlib.util

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QMessageBox, QComboBox, QFormLayout,
                             QGroupBox, QProgressBar, QStyle)
from PyQt5.QtCore import Qt, QTimer, QThread

try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
    DEPENDENCIES_MISSING = False
except ImportError as e:
    print(f"CRITICAL: voicebank_recorder_module.py - Missing dependencies: {e}")
    DEPENDENCIES_MISSING = True
    MISSING_ERROR_MESSAGE = str(e)


# ===== 标准化模块入口函数 =====
def create_page(parent_window, WORD_LIST_DIR, AUDIO_RECORD_DIR, ToggleSwitchClass, WorkerClass):
    """模块的入口函数，用于创建页面。"""
    if DEPENDENCIES_MISSING:
        error_page = QWidget()
        layout = QVBoxLayout(error_page)
        label = QLabel(f"语音包录制模块加载失败：\n缺少必要的依赖库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install sounddevice soundfile numpy")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        return error_page

    return VoicebankRecorderPage(parent_window, WORD_LIST_DIR, AUDIO_RECORD_DIR, ToggleSwitchClass, WorkerClass)


class VoicebankRecorderPage(QWidget):
    LINE_WIDTH_THRESHOLD = 90

    def __init__(self, parent_window, WORD_LIST_DIR, AUDIO_RECORD_DIR, ToggleSwitchClass, WorkerClass):
        super().__init__()
        self.parent_window = parent_window
        self.WORD_LIST_DIR = WORD_LIST_DIR
        self.AUDIO_RECORD_DIR = AUDIO_RECORD_DIR
        self.ToggleSwitch = ToggleSwitchClass # 虽然本页面未使用，但保持接口一致性
        self.Worker = WorkerClass
        # 从父窗口获取最新的配置
        self.config = self.parent_window.config

        self.session_active = False
        self.is_recording = False
        self.current_word_list = []
        self.current_word_index = -1
        self.audio_queue = queue.Queue()
        self.recording_thread = None
        self.stop_event = threading.Event()
        
        self._init_ui()

        self.start_btn.clicked.connect(self.start_session)
        self.end_session_btn.clicked.connect(self.end_session)
        self.record_btn.pressed.connect(self.start_recording)
        self.record_btn.released.connect(self.stop_recording)
        
        self.setFocusPolicy(Qt.StrongFocus)
        self.apply_layout_settings() # 初始化时应用一次

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        left_layout = QVBoxLayout()
        
        # 将右侧面板保存为成员变量以便后续调整宽度
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
        self.end_session_btn.hide() # 初始隐藏
        
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
        main_layout.addWidget(self.right_panel, 1) # 使用 self.right_panel

    def apply_layout_settings(self):
        """从配置中读取并应用侧边栏宽度。"""
        ui_settings = self.config.get("ui_settings", {})
        width = ui_settings.get("collector_sidebar_width", 320)
        self.right_panel.setFixedWidth(width)

    def load_config_and_prepare(self):
        """当标签页被选中时调用，加载最新配置并准备UI。"""
        self.config = self.parent_window.config # 获取最新的全局配置
        self.apply_layout_settings() # 确保侧边栏宽度是最新的
        if not self.session_active:
            self.populate_word_lists()
            
    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.record_btn.isEnabled() and not self.is_recording:
                self.is_recording = True
                self.start_recording()
                event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.is_recording:
                self.is_recording = False
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
        if not self.audio_queue.empty():
            data_chunk = self.audio_queue.get()
            volume_norm = np.linalg.norm(data_chunk) * 10
            self.volume_meter.setValue(int(volume_norm))
        else:
            current_value = self.volume_meter.value()
            self.volume_meter.setValue(int(current_value * 0.8))

    def start_recording(self):
        self.current_word_index = self.list_widget.currentRow()
        if self.current_word_index == -1: 
            self.log("请先在列表中选择一个词！")
            self.is_recording = False
            return

        self.recording_indicator.setText("● 正在录音"); self.recording_indicator.setStyleSheet("color: red;")
        self.update_timer.start(50)
            
        self.record_btn.setText("正在录音..."); self.record_btn.setStyleSheet("background-color: #f44336;")
        self.log(f"录制 '{self.current_word_list[self.current_word_index]['word']}'")
        self.stop_event.clear(); self.audio_queue = queue.Queue()
        self.recording_thread = threading.Thread(target=self.recorder_thread_task, daemon=True); self.recording_thread.start()

    def stop_recording(self):
        if not self.recording_thread or not self.recording_thread.is_alive(): 
            self.is_recording = False # 确保状态正确
            return

        self.update_timer.stop()
        self.recording_indicator.setText("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_meter.setValue(0)
            
        self.stop_event.set(); self.record_btn.setText("按住录音"); self.record_btn.setStyleSheet("")
        self.log("正在保存...")
        if self.recording_thread.is_alive():
            self.recording_thread.join(timeout=0.5) # 等待线程结束
        self.run_task_in_thread(self.save_recording_task)
        self.is_recording = False # 确保在所有操作后重置状态
    
    def log(self, msg): self.status_label.setText(f"状态: {msg}")
    
    def populate_word_lists(self):
        self.word_list_combo.clear()
        if os.path.exists(self.WORD_LIST_DIR): 
            self.word_list_combo.addItems([f for f in os.listdir(self.WORD_LIST_DIR) if f.endswith('.py')])
        
    def reset_ui(self):
        """重置UI到初始状态，但不清除数据。"""
        self.word_list_combo.show()
        self.start_btn.show()

        # 从布局中移除“结束会话”按钮的整行
        # 检查按钮是否真的在布局中，避免重复移除或对已删除对象操作
        if self.end_session_btn.parent() is not None: # 检查按钮是否已添加到布局中
             self.control_layout.removeRow(self.end_session_btn)
             # self.end_session_btn.deleteLater() # 可选：彻底删除按钮对象

        self.list_widget.clear()
        self.record_btn.setEnabled(False)
        self.log("请选择一个单词表开始录制。")
    
    def end_session(self):
        """结束当前录制会话，清理数据并重置UI。"""
        reply = QMessageBox.question(self, '结束会话', '您确定要结束当前的语音包录制会话吗？',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            if self.is_recording: # 如果正在录音，先停止
                self.stop_recording()
            self.session_active = False
            self.current_word_list = []
            self.current_word_index = -1
            self.reset_ui()

    def start_session(self):
        wordlist_file=self.word_list_combo.currentText()
        if not wordlist_file: QMessageBox.warning(self,"错误","请先选择一个单词表。");return
        wordlist_name,_=os.path.splitext(wordlist_file)
        self.audio_folder=os.path.join(self.AUDIO_RECORD_DIR,wordlist_name)
        if not os.path.exists(self.audio_folder): os.makedirs(self.audio_folder)
        
        try:
            word_groups=self.load_word_list_logic(wordlist_file)
            self.current_word_list=[]
            for group in word_groups:
                for word,value in group.items():
                    ipa=value[0] if isinstance(value,tuple) else str(value)
                    self.current_word_list.append({'word':word,'ipa':ipa})
            self.current_word_index=0 # 默认选中第一个
            
            self.word_list_combo.hide()
            self.start_btn.hide()
            # 重新创建按钮实例，以确保它在布局中是新的
            self.end_session_btn = QPushButton("结束当前会话")
            self.end_session_btn.setObjectName("ActionButton_Delete")
            self.end_session_btn.clicked.connect(self.end_session)
            self.end_session_btn.show() # 确保按钮可见
            self.control_layout.addRow(self.end_session_btn)


            self.update_list_widget()
            self.record_btn.setEnabled(True)
            self.log("准备就绪，请选择词语并录音。")
            
            self.session_active = True

        except Exception as e: 
            QMessageBox.critical(self,"错误",f"加载单词表失败: {e}")
            self.session_active = False
        
    def update_list_widget(self):
        current_row = self.list_widget.currentRow()
        if current_row == -1 and self.current_word_list: current_row = 0 # 如果没有选中项且列表不空，默认选第一个

        self.list_widget.clear()
        for item_data in self.current_word_list:
            display_text = self._format_list_item_text(item_data['word'], item_data['ipa'])
            item = QListWidgetItem(display_text)
            
            filepath=os.path.join(self.audio_folder,f"{item_data['word']}.mp3")
            if os.path.exists(filepath): item.setIcon(self.style().standardIcon(QStyle.SP_DialogOkButton))
            
            self.list_widget.addItem(item)
            
        if self.current_word_list and 0 <= current_row < len(self.current_word_list):
             self.list_widget.setCurrentRow(current_row)
             
    def on_recording_saved(self):
        self.log("录音已保存。")
        self.update_list_widget() 
        
        if self.current_word_index + 1 < len(self.current_word_list):
            self.current_word_index += 1
            self.list_widget.setCurrentRow(self.current_word_index)
        else: 
            QMessageBox.information(self,"完成","所有词条已录制完毕！")
            if self.session_active: self.end_session()
        
    def recorder_thread_task(self):
        try:
            # ===== 新增/MODIFIED: 获取选择的录音设备 =====
            device_index = self.config['audio_settings'].get('input_device_index', None)
            # 如果 device_index 是 None, sounddevice 会使用系统默认设备
            
            with sd.InputStream(
                device=device_index, # <--- 使用选择的设备
                samplerate=self.config['audio_settings']['sample_rate'],
                channels=self.config['audio_settings']['channels'],
                callback=lambda i,f,t,s:self.audio_queue.put(i.copy())
            ): 
                self.stop_event.wait()
        except Exception as e:
            print(f"录音错误 (VoicebankRecorderPage): {e}")
            # 可以在这里添加一个错误提示给用户，例如通过信号
            self.parent_window.statusBar().showMessage(f"录音设备错误: {e}", 5000)


    def save_recording_task(self,worker_instance): # 参数名改为 worker_instance
        if self.audio_queue.empty():return
        data=[self.audio_queue.get() for _ in range(self.audio_queue.qsize())];rec=np.concatenate(data,axis=0)
        gain=self.config['audio_settings'].get('recording_gain',1.0)
        if gain!=1.0: rec=np.clip(rec*gain,-1.0,1.0)
        word=self.current_word_list[self.current_word_index]['word']
        filepath=os.path.join(self.audio_folder,f"{word}.mp3")
        try: sf.write(filepath,rec,self.config['audio_settings']['sample_rate'],format='MP3')
        except Exception as e:
            self.log(f"保存MP3失败: {e}")
            try:
                wav_path=os.path.splitext(filepath)[0]+".wav"
                sf.write(wav_path,rec,self.config['audio_settings']['sample_rate']); self.log(f"已保存为WAV格式: {wav_path}")
            except Exception as e_wav: self.log(f"保存WAV也失败: {e_wav}")
            
    def run_task_in_thread(self,task_func,*args):
        self.thread=QThread();self.worker=self.Worker(task_func,*args);self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run);self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater);self.thread.finished.connect(self.thread.deleteLater)
        self.worker.error.connect(lambda msg:QMessageBox.critical(self,"后台错误",msg))
        if task_func==self.save_recording_task:self.worker.finished.connect(self.on_recording_saved)
        self.thread.start()
        
    def load_word_list_logic(self,filename):
        filepath=os.path.join(self.WORD_LIST_DIR,filename)
        if not os.path.exists(filepath):raise FileNotFoundError(f"找不到单词表文件: {filename}")
        spec=importlib.util.spec_from_file_location("word_list_module",filepath);module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module);return module.WORD_GROUPS