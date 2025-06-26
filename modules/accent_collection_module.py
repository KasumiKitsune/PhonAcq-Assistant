# --- START OF FILE accent_collection_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "口音采集会话"
MODULE_DESCRIPTION = "进行标准的文本到语音实验，适用于朗读任务、最小音对测试、句子复述等场景。"
# ---

import os
import threading
import queue
import importlib.util
import time
import random

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QMessageBox, QComboBox, QFormLayout,
                             QGroupBox, QProgressBar, QStyle, QLineEdit)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal # 新增 pyqtSignal

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


# ===== 标准化模块入口函数 =====
def create_page(parent_window, config, ToggleSwitchClass, WorkerClass, LoggerClass,
                detect_language_func, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH):
    """模块的入口函数，用于创建页面。"""
    if DEPENDENCIES_MISSING:
        error_page = QWidget()
        layout = QVBoxLayout(error_page)
        label = QLabel(f"口音采集模块加载失败：\n缺少必要的依赖库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install sounddevice soundfile numpy gtts")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        return error_page

    return AccentCollectionPage(parent_window, config, ToggleSwitchClass, WorkerClass, LoggerClass,
                                detect_language_func, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH)


class AccentCollectionPage(QWidget):
    LINE_WIDTH_THRESHOLD = 90
    # 新增信号，用于在录音设备出错时通知主线程
    recording_device_error_signal = pyqtSignal(str)

    def __init__(self, parent_window, config, ToggleSwitchClass, WorkerClass, LoggerClass,
                 detect_language_func, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH):
        super().__init__()
        self.parent_window = parent_window
        self.config = config # 初始化时获取一次配置
        self.ToggleSwitch = ToggleSwitchClass
        self.Worker = WorkerClass
        self.Logger = LoggerClass
        self.detect_language = detect_language_func
        self.WORD_LIST_DIR = WORD_LIST_DIR
        self.AUDIO_RECORD_DIR = AUDIO_RECORD_DIR
        self.AUDIO_TTS_DIR = AUDIO_TTS_DIR
        self.BASE_PATH = BASE_PATH

        self.session_active = False
        self.is_recording = False
        self.current_word_list = []
        self.current_word_index = -1
        self.audio_queue = queue.Queue()
        self.recording_thread = None
        self.stop_event = threading.Event()
        self.logger = None # 初始化 logger 实例
        
        self._init_ui()

        # 连接信号
        self.start_session_btn.clicked.connect(self.start_session)
        self.end_session_btn.clicked.connect(self.end_session)
        self.record_btn.clicked.connect(self.handle_record_button)
        self.replay_btn.clicked.connect(self.replay_audio)
        self.list_widget.currentRowChanged.connect(self.on_list_item_changed)
        self.list_widget.itemDoubleClicked.connect(self.replay_audio)
        self.random_switch.stateChanged.connect(self.on_session_mode_changed)
        self.full_list_switch.stateChanged.connect(self.on_session_mode_changed)
        self.recording_device_error_signal.connect(self.show_recording_device_error) # 连接错误信号

        self.reset_ui()
        self.apply_layout_settings()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        left_layout = QVBoxLayout()
        
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)

        self.list_widget = QListWidget()
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
        self.participant_input = QLineEdit()
        self.start_session_btn = QPushButton("开始新会话")
        self.start_session_btn.setObjectName("AccentButton")
        pre_session_layout.addRow("选择单词表:", self.word_list_combo)
        pre_session_layout.addRow("被试者名称:", self.participant_input)
        pre_session_layout.addRow(self.start_session_btn)

        self.in_session_widget = QWidget()
        in_session_layout = QVBoxLayout(self.in_session_widget)
        mode_group = QGroupBox("会话模式")
        mode_layout = QFormLayout(mode_group)
        self.random_switch = self.ToggleSwitch(); self.full_list_switch = self.ToggleSwitch()
        random_layout = QHBoxLayout(); random_layout.addWidget(QLabel("顺序")); random_layout.addWidget(self.random_switch); random_layout.addWidget(QLabel("随机"))
        full_list_layout = QHBoxLayout(); full_list_layout.addWidget(QLabel("部分")); full_list_layout.addWidget(self.full_list_switch); full_list_layout.addWidget(QLabel("完整"))
        mode_layout.addRow(random_layout); mode_layout.addRow(full_list_layout)
        self.end_session_btn = QPushButton("结束当前会话")
        self.end_session_btn.setObjectName("ActionButton_Delete")
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
        
        self.record_btn = QPushButton("开始录制下一个"); self.replay_btn = QPushButton("重听当前音频")
        
        right_layout.addWidget(right_panel_group)
        right_layout.addStretch()
        right_layout.addWidget(self.recording_status_panel)
        right_layout.addWidget(self.record_btn)
        right_layout.addWidget(self.replay_btn)
        
        main_layout.addLayout(left_layout, 2)
        main_layout.addWidget(self.right_panel, 1)

    def apply_layout_settings(self):
        ui_settings = self.config.get("ui_settings", {})
        width = ui_settings.get("collector_sidebar_width", 320)
        self.right_panel.setFixedWidth(width)

    def load_config_and_prepare(self):
        self.config = self.parent_window.config # 确保获取最新的全局配置
        self.apply_layout_settings()
        if not self.session_active:
            self.populate_word_lists()
            self.participant_input.setText(self.config['file_settings'].get('participant_base_name', 'participant'))
    
    def show_recording_device_error(self, error_message):
        QMessageBox.critical(self, "录音设备错误", error_message)
        # 可以在这里尝试停止录音相关的UI状态
        if self.is_recording:
            self.stop_recording_logic() # 尝试停止
            self.is_recording = False
            self.record_btn.setText("开始录制下一个") # 或者更合适的文本
            self.record_btn.setEnabled(True) # 可能需要重新启用
            self.list_widget.setEnabled(True)
            self.random_switch.setEnabled(True)
            self.full_list_switch.setEnabled(True)
            self.status_label.setText("状态：录音设备错误，请检查设置。")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if self.list_widget.hasFocus() and self.replay_btn.isEnabled():
                self.replay_audio()
                event.accept()
        else:
            super().keyPressEvent(event)

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
            try:
                data_chunk = self.audio_queue.get_nowait() # 使用 nowait 避免阻塞
                volume_norm = np.linalg.norm(data_chunk) * 10
                self.volume_meter.setValue(int(volume_norm))
            except queue.Empty:
                pass # 队列为空是正常情况
            except Exception as e:
                print(f"Error processing audio queue: {e}")
        else:
            current_value = self.volume_meter.value()
            self.volume_meter.setValue(int(current_value * 0.8))
            
    def start_recording_logic(self):
        self.recording_indicator.setText("● 正在录音"); self.recording_indicator.setStyleSheet("color: red;")
        self.update_timer.start(50)
        self.stop_event.clear(); 
        while not self.audio_queue.empty(): # 清空上次可能残留的数据
            try: self.audio_queue.get_nowait()
            except queue.Empty: break
        self.recording_thread=threading.Thread(target=self.recorder_thread_task,daemon=True); self.recording_thread.start()

    def stop_recording_logic(self):
        self.update_timer.stop()
        self.recording_indicator.setText("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_meter.setValue(0)
        self.stop_event.set()
        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=1.0) # 增加超时确保线程能结束
            if self.recording_thread.is_alive():
                print("Warning: Recording thread did not terminate cleanly.")
        self.run_task_in_thread(self.save_recording_task)

    def populate_word_lists(self):
        self.word_list_combo.clear()
        if os.path.exists(self.WORD_LIST_DIR):
            try:
                self.word_list_combo.addItems([f for f in os.listdir(self.WORD_LIST_DIR) if f.endswith('.py')])
            except Exception as e:
                QMessageBox.warning(self, "错误", f"无法读取单词表目录: {e}")
        default_list = self.config['file_settings'].get('word_list_file', '')
        if default_list:
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
        self.pre_session_widget.show()
        self.in_session_widget.hide()
        self.record_btn.setEnabled(False)
        self.replay_btn.setEnabled(False)
        self.record_btn.setText("开始录制下一个")
        self.list_widget.clear()
        self.status_label.setText("状态：准备就绪")
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        
    def end_session(self):
        reply = QMessageBox.question(self, '结束会话', '您确定要结束当前的口音采集会话吗？',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            if self.is_recording: # 如果正在录音，先停止
                self.stop_recording_logic()
                self.is_recording = False # 确保状态更新

            self.session_active = False
            self.current_word_list = []
            self.current_word_index = -1
            self.logger = None # 重置logger
            self.reset_ui()
            self.load_config_and_prepare() # 重新加载，会获取最新的配置

    def start_session(self):
        wordlist_file = self.word_list_combo.currentText()
        if not wordlist_file:
            QMessageBox.warning(self, "选择错误", "请先选择一个单词表。")
            return
        base_name = self.participant_input.text().strip()
        if not base_name:
            QMessageBox.warning(self, "输入错误", "请输入被试者名称。")
            return
        results_dir = self.config['file_settings'].get("results_dir", os.path.join(self.BASE_PATH, "Results"))
        if not os.path.exists(results_dir): os.makedirs(results_dir)
        i = 1; folder_name = base_name
        while os.path.exists(os.path.join(results_dir, folder_name)): i += 1; folder_name = f"{base_name}_{i}"
        self.recordings_folder = os.path.join(results_dir, folder_name); os.makedirs(self.recordings_folder)
        self.logger = self.Logger(os.path.join(self.recordings_folder, "log.txt"))
        try:
            self.current_wordlist_name = wordlist_file
            word_groups = self.load_word_list_logic()
            if not word_groups: # 检查 word_groups 是否为空
                QMessageBox.warning(self, "词表错误", f"单词表 '{wordlist_file}' 为空或无法解析。")
                self.logger.log(f"ERROR: Wordlist '{wordlist_file}' is empty or could not be parsed.")
                self.reset_ui() # 重置UI回会话前状态
                return

            self.progress_bar.setVisible(True); self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0)
            self.run_task_in_thread(self.check_and_generate_audio_logic, word_groups)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载单词表失败: {e}")
            if self.logger: self.logger.log(f"ERROR: Failed to load wordlist '{wordlist_file}': {e}")
            self.reset_ui()
        
    def update_tts_progress(self, percentage, text):
        self.progress_bar.setValue(percentage)
        self.status_label.setText(f"状态：{text}")
        
    def on_tts_finished(self, error_msg): # error_msg 现在是后台任务的返回值
        self.progress_bar.setVisible(False)
        if error_msg: # 如果后台任务返回了错误信息字符串
            QMessageBox.warning(self, "音频检查/生成失败", error_msg)
            if self.logger: self.logger.log(f"TTS Generation Error: {error_msg}")
            self.reset_ui() # 重置UI
            return
            
        self.status_label.setText("状态：音频准备就绪。")
        self.pre_session_widget.hide(); self.in_session_widget.show(); self.record_btn.setEnabled(True); self.session_active = True
        self.prepare_word_list()
        if self.current_word_list:
            self.record_btn.setText("开始录制 (1/{})".format(len(self.current_word_list)))
        
    def prepare_word_list(self):
        word_groups = self.load_word_list_logic()
        is_random = self.random_switch.isChecked(); is_full = self.full_list_switch.isChecked()
        temp_list = []
        if not is_full:
            for group in word_groups:
                if group: temp_list.append(random.choice(list(group.items())))
        else:
            for group in word_groups: temp_list.extend(group.items())
        if is_random: random.shuffle(temp_list)
        self.current_word_list = []
        for word, value in temp_list:
            ipa = value[0] if isinstance(value, tuple) else str(value)
            self.current_word_list.append({'word': word, 'ipa': ipa, 'recorded': False})
        self.list_widget.clear()
        for item_data in self.current_word_list:
            display_text = self._format_list_item_text(item_data['word'], item_data['ipa'])
            self.list_widget.addItem(QListWidgetItem(display_text))
        if self.current_word_list: self.list_widget.setCurrentRow(0)
        
    def handle_record_button(self):
        if not self.is_recording:
            self.current_word_index=self.list_widget.currentRow()
            if self.current_word_index==-1:
                QMessageBox.information(self, "提示", "请先在左侧列表中选择一个词条。")
                return
            self.is_recording=True;self.record_btn.setText("停止录制");self.list_widget.setEnabled(False);self.replay_btn.setEnabled(True)
            self.random_switch.setEnabled(False);self.full_list_switch.setEnabled(False)
            self.status_label.setText(f"状态：正在录制 '{self.current_word_list[self.current_word_index]['word']}'...")
            self.play_audio_logic();self.start_recording_logic()
        else:
            self.stop_recording_logic();self.is_recording=False;self.record_btn.setText("准备就绪");self.record_btn.setEnabled(False) # 停止后按钮应暂时禁用，直到保存完成
            self.status_label.setText("状态：正在保存录音...")
            
    def on_recording_saved(self, result): # result 是 save_recording_task 的返回值
        self.status_label.setText("状态：录音已保存。");self.list_widget.setEnabled(True);self.replay_btn.setEnabled(True)
        self.random_switch.setEnabled(True);self.full_list_switch.setEnabled(True)
        
        if self.current_word_index < 0 or self.current_word_index >= len(self.current_word_list):
             if self.logger: self.logger.log("ERROR: current_word_index out of bounds in on_recording_saved.")
             self.record_btn.setEnabled(True) # 允许用户重试或选择其他
             return

        item_data=self.current_word_list[self.current_word_index];item_data['recorded']=True
        list_item=self.list_widget.item(self.current_word_index)
        if list_item: # 确保 item 存在
            display_text = self._format_list_item_text(item_data['word'], item_data['ipa'])
            list_item.setText(display_text)
            list_item.setIcon(self.style().standardIcon(QStyle.SP_DialogOkButton))
        
        all_recorded=all(item['recorded'] for item in self.current_word_list)
        if all_recorded:self.handle_session_completion();return
        
        next_index=-1;indices=list(range(len(self.current_word_list)))
        # 寻找下一个未录制的词条
        for i in indices[self.current_word_index+1:]+indices[:self.current_word_index]: # 优先向后找，再从头找
            if not self.current_word_list[i]['recorded']:next_index=i;break
        
        if next_index!=-1:
            self.list_widget.setCurrentRow(next_index)
            self.record_btn.setEnabled(True)
            recorded_count = sum(1 for item in self.current_word_list if item['recorded'])
            self.record_btn.setText(f"开始录制 ({recorded_count + 1}/{len(self.current_word_list)})")
        else: # 如果都录完了（理论上上面 all_recorded 会先捕获）
            self.handle_session_completion()
        
    def handle_session_completion(self):
        unrecorded_count=sum(1 for item in self.current_word_list if not item['recorded'])
        if self.current_word_list:
            QMessageBox.information(self,"会话结束",f"本次会话已结束。\n总共录制了 {len(self.current_word_list)-unrecorded_count} 个词语。")
        self.end_session()
        
    def on_list_item_changed(self,row):
        if row!=-1 and not self.is_recording:self.replay_btn.setEnabled(True)
        
    def replay_audio(self, item=None): # item 参数未使用，可以移除
        self.play_audio_logic()
    
    def play_audio_logic(self,index=None):
        if not self.session_active: return
        if index is None: index = self.list_widget.currentRow()
        if index == -1 or index >= len(self.current_word_list): return # 增加边界检查
        
        word = self.current_word_list[index]['word']
        wordlist_name, _ = os.path.splitext(self.current_wordlist_name)
        
        record_path = os.path.join(self.AUDIO_RECORD_DIR, wordlist_name, f"{word}.mp3")
        tts_path = os.path.join(self.AUDIO_TTS_DIR, wordlist_name, f"{word}.mp3")
        final_path = record_path if os.path.exists(record_path) else tts_path
        
        if os.path.exists(final_path):
            threading.Thread(target=self.play_sound_task, args=(final_path,), daemon=True).start()
        else:
            self.status_label.setText(f"状态：找不到 '{word}' 的提示音！")
        
    def play_sound_task(self,path):
        try:data,sr=sf.read(path,dtype='float32');sd.play(data,sr);sd.wait()
        except Exception as e: 
            if self.logger: self.logger.log(f"ERROR playing sound '{path}': {e}")
            # 可以在这里向用户显示一个非阻塞的提示
            self.parent_window.statusBar().showMessage(f"播放音频失败: {os.path.basename(path)}", 3000)

    def recorder_thread_task(self):
        try:
            device_index = self.config['audio_settings'].get('input_device_index', None)
            with sd.InputStream(
                device=device_index,
                samplerate=self.config['audio_settings']['sample_rate'],
                channels=self.config['audio_settings']['channels'],
                callback=lambda i,f,t,s:self.audio_queue.put(i.copy())
            ):
                self.stop_event.wait()
        except Exception as e:
            error_msg = f"无法启动录音，请检查录音设备设置或权限。\n错误详情: {e}"
            print(f"录音错误 (AccentCollectionPage): {error_msg}")
            self.recording_device_error_signal.emit(error_msg) # 发射信号
        
    def save_recording_task(self,worker):
        if self.audio_queue.empty():return None # 返回None表示没有数据
        data_frames = []
        while not self.audio_queue.empty():
            try:
                data_frames.append(self.audio_queue.get_nowait())
            except queue.Empty:
                break
        if not data_frames: return None

        rec = np.concatenate(data_frames,axis=0)
        gain = self.config['audio_settings'].get('recording_gain',1.0)
        if gain != 1.0: rec = np.clip(rec*gain,-1.0,1.0)
        
        # 确保 current_word_index 是有效的
        if self.current_word_index < 0 or self.current_word_index >= len(self.current_word_list):
            if self.logger: self.logger.log(f"ERROR: Invalid current_word_index ({self.current_word_index}) in save_recording_task.")
            return "save_failed_invalid_index" # 返回错误标识

        word = self.current_word_list[self.current_word_index]['word']
        filepath = os.path.join(self.recordings_folder,f"{word}.wav")
        try:
            sf.write(filepath,rec,self.config['audio_settings']['sample_rate'])
            if self.logger: self.logger.log(f"Recording saved: {filepath}")
            return "save_successful" # 返回成功标识
        except Exception as e:
            if self.logger: self.logger.log(f"ERROR saving recording '{filepath}': {e}")
            return f"save_failed_exception: {e}" # 返回错误标识及信息
        
    def run_task_in_thread(self,task_func,*args):
        self.thread=QThread();self.worker=self.Worker(task_func,*args);self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run);self.worker.finished.connect(self.thread.quit)
        # 修改：finished信号连接到worker的deleteLater，确保worker对象在完成后被安全删除
        self.worker.finished.connect(self.worker.deleteLater) 
        self.thread.finished.connect(self.thread.deleteLater) # 线程完成后也删除自身
        self.worker.progress.connect(self.update_tts_progress)
        self.worker.error.connect(lambda msg:QMessageBox.critical(self,"后台错误",msg))
        if task_func==self.check_and_generate_audio_logic:self.worker.finished.connect(self.on_tts_finished)
        elif task_func==self.save_recording_task:self.worker.finished.connect(self.on_recording_saved)
        self.thread.start()
        
    def load_word_list_logic(self):
        filename = self.current_wordlist_name
        filepath = os.path.join(self.WORD_LIST_DIR, filename)
        if not os.path.exists(filepath): raise FileNotFoundError(f"找不到单词表文件: {filename}")
        module_name = f"wordlist_{os.path.splitext(filename)[0].replace('-', '_')}" # 更安全的模块名
        spec = importlib.util.spec_from_file_location(module_name, filepath)
        if spec is None: raise ImportError(f"无法为 '{filename}' 创建模块规范。")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            raise ImportError(f"执行模块 '{filename}' 失败: {e}")
        
        if not hasattr(module, 'WORD_GROUPS') or not isinstance(module.WORD_GROUPS, list):
            raise ValueError(f"词表 '{filename}' 必须包含一个名为 'WORD_GROUPS' 的列表。")
        return module.WORD_GROUPS
        
    def check_and_generate_audio_logic(self,worker,word_groups):
        wordlist_name, _ = os.path.splitext(self.current_wordlist_name)
        gtts_settings=self.config.get("gtts_settings",{});gtts_default_lang=gtts_settings.get("default_lang","en-us");gtts_auto_detect=gtts_settings.get("auto_detect",True)
        all_words_with_lang={};
        for group_idx, group in enumerate(word_groups):
            if not isinstance(group, dict):
                if self.logger: self.logger.log(f"Warning: Word group at index {group_idx} in '{wordlist_name}' is not a dictionary, skipping.")
                continue
            for word,value in group.items():
                lang=value[1] if isinstance(value,tuple) and len(value)==2 and value[1] else None
                if not lang and gtts_auto_detect:lang=self.detect_language(word)
                if not lang:lang=gtts_default_lang
                all_words_with_lang[word]=lang
        
        record_audio_folder = os.path.join(self.AUDIO_RECORD_DIR, wordlist_name)
        tts_audio_folder = os.path.join(self.AUDIO_TTS_DIR, wordlist_name)
        if not os.path.exists(tts_audio_folder):
            try: os.makedirs(tts_audio_folder)
            except Exception as e: return f"创建TTS音频目录失败: {e}" # 返回错误信息
        
        missing = [w for w in all_words_with_lang if not os.path.exists(os.path.join(record_audio_folder, f"{w}.mp3")) and not os.path.exists(os.path.join(tts_audio_folder, f"{w}.mp3"))]
        if not missing: return None # 没有缺失，直接返回 None 表示成功
        
        total_missing=len(missing)
        errors_occurred = []
        for i,word in enumerate(missing):
            percentage=int((i+1)/total_missing*100)
            progress_text=f"正在生成TTS ({i+1}/{total_missing}): {word}...";worker.progress.emit(percentage,progress_text)
            filepath=os.path.join(tts_audio_folder, f"{word}.mp3")
            try:
                gTTS(text=word,lang=all_words_with_lang[word],slow=False).save(filepath)
                time.sleep(0.3) # 稍微减少延时，如果网络允许
            except Exception as e:
                error_detail = f"为'{word}'生成TTS音频失败: {e}"
                errors_occurred.append(error_detail)
                if self.logger: self.logger.log(f"TTS Error: {error_detail}")
                # 不立即返回，尝试生成其他词的TTS
        
        if errors_occurred:
            return "部分TTS音频生成失败，请检查日志和网络连接。\n" + "\n".join(errors_occurred[:3]) # 最多显示3条错误
        return None # 全部成功或部分失败但有日志记录