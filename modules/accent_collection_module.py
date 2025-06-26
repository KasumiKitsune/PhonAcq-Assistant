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
from PyQt5.QtCore import Qt, QTimer, QThread

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

    def __init__(self, parent_window, config, ToggleSwitchClass, WorkerClass, LoggerClass,
                 detect_language_func, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH):
        super().__init__()
        self.parent_window = parent_window
        self.config = config
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

        self.reset_ui()
        self.apply_layout_settings()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        left_layout = QVBoxLayout()
        
        # 将右侧面板保存为成员变量
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)

        # 左侧：列表和状态
        self.list_widget = QListWidget()
        self.status_label = QLabel("状态：准备就绪")
        self.progress_bar = QProgressBar(); self.progress_bar.setVisible(False)
        left_layout.addWidget(QLabel("测试词语列表:"))
        left_layout.addWidget(self.list_widget)
        left_layout.addWidget(self.status_label)
        left_layout.addWidget(self.progress_bar)

        # 右侧控制面板
        right_panel_group = QGroupBox("控制面板")
        self.right_layout_container = QVBoxLayout(right_panel_group)

        # 会话前控件
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

        # 会话中控件
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
        main_layout.addWidget(self.right_panel, 1) # 修改这里

    def apply_layout_settings(self):
        """从配置中读取并应用侧边栏宽度。"""
        ui_settings = self.config.get("ui_settings", {})
        width = ui_settings.get("collector_sidebar_width", 320)
        self.right_panel.setFixedWidth(width)

    def load_config_and_prepare(self):
        self.config = self.parent_window.config
        self.apply_layout_settings()
        if not self.session_active:
            self.populate_word_lists()
            self.participant_input.setText(self.config['file_settings'].get('participant_base_name', 'participant'))
    
    # ... (其余所有方法保持不变) ...
    # (keyPressEvent, _get_weighted_length, ..., check_and_generate_audio_logic)
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
            data_chunk = self.audio_queue.get()
            volume_norm = np.linalg.norm(data_chunk) * 10
            self.volume_meter.setValue(int(volume_norm))
        else:
            current_value = self.volume_meter.value()
            self.volume_meter.setValue(int(current_value * 0.8))
            
    def start_recording_logic(self):
        self.recording_indicator.setText("● 正在录音"); self.recording_indicator.setStyleSheet("color: red;")
        self.update_timer.start(50)
        self.stop_event.clear(); self.audio_queue=queue.Queue()
        self.recording_thread=threading.Thread(target=self.recorder_thread_task,daemon=True); self.recording_thread.start()

    def stop_recording_logic(self):
        self.update_timer.stop()
        self.recording_indicator.setText("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_meter.setValue(0)
        self.stop_event.set()
        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=0.5)
        self.run_task_in_thread(self.save_recording_task)

    def populate_word_lists(self):
        self.word_list_combo.clear()
        if os.path.exists(self.WORD_LIST_DIR):
            self.word_list_combo.addItems([f for f in os.listdir(self.WORD_LIST_DIR) if f.endswith('.py')])
        default_list = self.config['file_settings'].get('word_list_file', '')
        if default_list:
            index = self.word_list_combo.findText(default_list, Qt.MatchFixedString)
            if index >= 0:
                self.word_list_combo.setCurrentIndex(index)

    def on_session_mode_changed(self):
        if not self.session_active: return
        self.prepare_word_list()
        if self.current_word_list: self.record_btn.setText(f"开始录制 (1/{len(self.current_word_list)})")
        
    def reset_ui(self):
        self.pre_session_widget.show()
        self.in_session_widget.hide()
        self.record_btn.setEnabled(False)
        self.replay_btn.setEnabled(False)
        self.record_btn.setText("开始录制下一个")
        self.list_widget.clear()
        self.status_label.setText("状态：准备就绪")
        self.progress_bar.setVisible(False)
        
    def end_session(self):
        reply = QMessageBox.question(self, '结束会话', '您确定要结束当前的口音采集会话吗？',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.session_active = False
            self.current_word_list = []
            self.current_word_index = -1
            self.reset_ui()
            self.load_config_and_prepare()

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
            self.progress_bar.setVisible(True); self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0)
            self.run_task_in_thread(self.check_and_generate_audio_logic, word_groups)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载单词表失败: {e}")
        
    def update_tts_progress(self, percentage, text):
        self.progress_bar.setValue(percentage)
        self.status_label.setText(f"状态：{text}")
        
    def on_tts_finished(self, error_msg):
        if error_msg:
            QMessageBox.warning(self, "音频检查完成", error_msg)
            self.reset_ui()
            return
        self.progress_bar.setVisible(False)
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
            if self.current_word_index==-1:return
            self.is_recording=True;self.record_btn.setText("停止录制");self.list_widget.setEnabled(False);self.replay_btn.setEnabled(True)
            self.random_switch.setEnabled(False);self.full_list_switch.setEnabled(False)
            self.status_label.setText(f"状态：正在录制 '{self.current_word_list[self.current_word_index]['word']}'...")
            self.play_audio_logic();self.start_recording_logic()
        else:
            self.stop_recording_logic();self.is_recording=False;self.record_btn.setText("准备就绪");self.record_btn.setEnabled(False)
            self.status_label.setText("状态：正在保存录音...")
            
    def on_recording_saved(self):
        self.status_label.setText("状态：录音已保存。");self.list_widget.setEnabled(True);self.replay_btn.setEnabled(True)
        self.random_switch.setEnabled(True);self.full_list_switch.setEnabled(True)
        item_data=self.current_word_list[self.current_word_index];item_data['recorded']=True
        list_item=self.list_widget.item(self.current_word_index)
        display_text = self._format_list_item_text(item_data['word'], item_data['ipa'])
        list_item.setText(display_text)
        list_item.setIcon(self.style().standardIcon(QStyle.SP_DialogOkButton))
        all_recorded=all(item['recorded'] for item in self.current_word_list)
        if all_recorded:self.handle_session_completion();return
        next_index=-1;indices=list(range(len(self.current_word_list)))
        for i in indices[self.current_word_index+1:]+indices[:self.current_word_index+1]:
            if not self.current_word_list[i]['recorded']:next_index=i;break
        if next_index!=-1:
            self.list_widget.setCurrentRow(next_index);self.record_btn.setEnabled(True)
            self.record_btn.setText("开始录制 ({}/{})".format(sum(1 for i in self.current_word_list if i['recorded'])+1,len(self.current_word_list)))
        else:self.handle_session_completion()
        
    def handle_session_completion(self):
        unrecorded_count=sum(1 for item in self.current_word_list if not item['recorded'])
        if self.current_word_list:
            QMessageBox.information(self,"会话结束",f"本次会话已结束。\n总共录制了 {len(self.current_word_list)-unrecorded_count} 个词语。")
        self.end_session()
        
    def on_list_item_changed(self,row):
        if row!=-1 and not self.is_recording:self.replay_btn.setEnabled(True)
        
    def replay_audio(self, item=None):
        self.play_audio_logic()
    
    def play_audio_logic(self,index=None):
        if not self.session_active: return
        if index is None: index = self.list_widget.currentRow()
        if index == -1: return
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
        except Exception as e: self.logger.log(f"ERROR playing sound: {e}")
        
    def recorder_thread_task(self):
        try:
            with sd.InputStream(samplerate=self.config['audio_settings']['sample_rate'],channels=self.config['audio_settings']['channels'],callback=lambda i,f,t,s:self.audio_queue.put(i.copy())):self.stop_event.wait()
        except Exception as e:print(f"录音错误: {e}")
        
    def save_recording_task(self,worker):
        if self.audio_queue.empty():return
        data=[self.audio_queue.get() for _ in range(self.audio_queue.qsize())];rec=np.concatenate(data,axis=0)
        gain=self.config['audio_settings'].get('recording_gain',1.0)
        if gain!=1.0:rec=np.clip(rec*gain,-1.0,1.0)
        word=self.current_word_list[self.current_word_index]['word']
        filepath=os.path.join(self.recordings_folder,f"{word}.wav")
        sf.write(filepath,rec,self.config['audio_settings']['sample_rate']);self.logger.log(f"Recording saved: {filepath}")
        
    def run_task_in_thread(self,task_func,*args):
        self.thread=QThread();self.worker=self.Worker(task_func,*args);self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run);self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater);self.thread.finished.connect(self.thread.deleteLater)
        self.worker.progress.connect(self.update_tts_progress)
        self.worker.error.connect(lambda msg:QMessageBox.critical(self,"后台错误",msg))
        if task_func==self.check_and_generate_audio_logic:self.worker.finished.connect(self.on_tts_finished)
        elif task_func==self.save_recording_task:self.worker.finished.connect(self.on_recording_saved)
        self.thread.start()
        
    def load_word_list_logic(self):
        filename = self.current_wordlist_name
        filepath = os.path.join(self.WORD_LIST_DIR, filename)
        if not os.path.exists(filepath): raise FileNotFoundError(f"找不到单词表文件: {filename}")
        spec = importlib.util.spec_from_file_location("word_list_module", filepath)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.WORD_GROUPS
        
    def check_and_generate_audio_logic(self,worker,word_groups):
        wordlist_name, _ = os.path.splitext(self.current_wordlist_name)
        gtts_settings=self.config.get("gtts_settings",{});gtts_default_lang=gtts_settings.get("default_lang","en-us");gtts_auto_detect=gtts_settings.get("auto_detect",True)
        all_words_with_lang={};
        for group in word_groups:
            for word,value in group.items():
                lang=value[1] if isinstance(value,tuple) and len(value)==2 and value[1] else None
                if not lang and gtts_auto_detect:lang=self.detect_language(word)
                if not lang:lang=gtts_default_lang
                all_words_with_lang[word]=lang
        record_audio_folder = os.path.join(self.AUDIO_RECORD_DIR, wordlist_name)
        tts_audio_folder = os.path.join(self.AUDIO_TTS_DIR, wordlist_name)
        if not os.path.exists(tts_audio_folder):os.makedirs(tts_audio_folder)
        missing = [w for w in all_words_with_lang if not os.path.exists(os.path.join(record_audio_folder, f"{w}.mp3")) and not os.path.exists(os.path.join(tts_audio_folder, f"{w}.mp3"))]
        if not missing: return None
        total_missing=len(missing)
        for i,word in enumerate(missing):
            percentage=int((i+1)/total_missing*100)
            progress_text=f"正在生成TTS ({i+1}/{total_missing}): {word}...";worker.progress.emit(percentage,progress_text)
            filepath=os.path.join(tts_audio_folder, f"{word}.mp3")
            try:
                gTTS(text=word,lang=all_words_with_lang[word],slow=False).save(filepath)
                time.sleep(0.5)
            except Exception as e:
                return f"为'{word}'生成TTS音频失败: {e}\n\n请检查您的网络连接或gTTS服务是否可用。"
        return None