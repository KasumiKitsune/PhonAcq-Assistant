# --- START OF FILE modules/tts_utility_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "TTS 工具"
MODULE_DESCRIPTION = "批量或即时将文本转换为语音，支持多种语言和自定义输出。"
# ---

import os
import sys
import threading
import time
import importlib.util
from datetime import datetime
import re 
import subprocess 

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QFileDialog, QMessageBox, QComboBox, QFormLayout,
                             QGroupBox, QProgressBar, QStyle, QLineEdit, QTableWidget,
                             QTableWidgetItem, QHeaderView, QCheckBox, QPlainTextEdit,
                             QSplitter, QSizePolicy) 
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize 
from PyQt5.QtGui import QIcon 

try:
    from gtts import gTTS
    DEPENDENCIES_MISSING = False
except ImportError as e:
    print(f"CRITICAL: tts_utility_module.py - Missing gTTS: {e}")
    DEPENDENCIES_MISSING = True
    MISSING_ERROR_MESSAGE = str(e)

def get_base_path_for_module():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

LANGUAGE_MAP_TTS = {
    "自动检测": "", "美式英语 (en-us)": "en-us", "英式英语 (en-uk)": "en-uk", 
    "澳洲英语 (en-au)": "en-au", "印度英语 (en-in)": "en-in", "中文普通话 (zh-cn)": "zh-cn", 
    "日语 (ja)": "ja", "韩语 (ko)": "ko", "法语 (fr-fr)": "fr-fr", 
    "德语 (de-de)": "de-de", "西班牙语 (es-es)": "es-es", "俄语 (ru)": "ru",
}
FLAG_CODE_MAP_TTS = {
    "": "auto", "en-us": "us", "en-uk": "gb", "en-au": "au", "en-in": "in",
    "zh-cn": "cn", "ja": "jp", "ko": "kr", "fr-fr": "fr", "de-de": "de", 
    "es-es": "es", "ru": "ru"
}

def create_page(parent_window, config, AUDIO_TTS_DIR_ROOT, ToggleSwitchClass, WorkerClass, detect_language_func, STD_WORD_LIST_DIR):
    if DEPENDENCIES_MISSING:
        error_page = QWidget(); layout = QVBoxLayout(error_page)
        label = QLabel(f"TTS 工具模块加载失败：\n缺少 gTTS 库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install gTTS")
        label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); layout.addWidget(label)
        return error_page
    return TtsUtilityPage(parent_window, config, AUDIO_TTS_DIR_ROOT, ToggleSwitchClass, WorkerClass, detect_language_func, STD_WORD_LIST_DIR)


class TtsUtilityPage(QWidget):
    log_message_signal = pyqtSignal(str)
    task_finished_signal = pyqtSignal(str)

    def __init__(self, parent_window, config, AUDIO_TTS_DIR_ROOT, ToggleSwitchClass, WorkerClass, detect_language_func, STD_WORD_LIST_DIR):
        super().__init__()
        self.parent_window = parent_window; self.config = config 
        self.AUDIO_TTS_DIR_ROOT = AUDIO_TTS_DIR_ROOT 
        self.ToggleSwitch = ToggleSwitchClass; self.Worker = WorkerClass
        self.detect_language = detect_language_func
        self.STD_WORD_LIST_DIR = STD_WORD_LIST_DIR 

        self.current_wordlist_path = None
        self.tts_thread = None 
        self.tts_worker = None 
        self.stop_tts_event = threading.Event()
        
        self.base_path_module = get_base_path_for_module() 
        self.flags_path = os.path.join(self.base_path_module, 'assets', 'flags')

        self._init_ui()
        self._connect_signals()
        self.log_message_signal.connect(self.log_message)
        self.task_finished_signal.connect(self.on_tts_task_finished)

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        load_group = QGroupBox("从文件批量转换")
        load_layout = QFormLayout(load_group)
        self.load_wordlist_btn = QPushButton("加载标准词表 (.py)")
        self.loaded_file_label = QLabel("未加载文件"); self.loaded_file_label.setWordWrap(True)
        load_layout.addRow(self.load_wordlist_btn); load_layout.addRow(QLabel("当前文件:"), self.loaded_file_label)
        
        editor_group = QGroupBox("即时编辑与转换")
        editor_v_layout = QVBoxLayout(editor_group)
        self.editor_table = QTableWidget()
        self.editor_table.setColumnCount(2)
        self.editor_table.setHorizontalHeaderLabels(["单词/短语", "语言"])
        self.editor_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.editor_table.setColumnWidth(1, 200)
        self.editor_table.setAlternatingRowColors(True)

        editor_btn_layout = QHBoxLayout()
        self.add_row_btn = QPushButton("添加行"); self.remove_row_btn = QPushButton("删除选中行"); self.clear_table_btn = QPushButton("清空列表")
        editor_btn_layout.addWidget(self.add_row_btn); editor_btn_layout.addWidget(self.remove_row_btn); editor_btn_layout.addWidget(self.clear_table_btn)
        editor_btn_layout.addStretch()
        self.submit_edited_btn = QPushButton("提交当前列表进行TTS"); self.submit_edited_btn.setObjectName("AccentButton")
        editor_v_layout.addWidget(self.editor_table); editor_v_layout.addLayout(editor_btn_layout); editor_v_layout.addWidget(self.submit_edited_btn, 0, Qt.AlignRight)

        left_layout.addWidget(load_group); left_layout.addWidget(editor_group)
        left_panel.setMinimumWidth(450)

        right_panel_container = QWidget() 
        right_panel_main_layout = QVBoxLayout(right_panel_container)
        right_panel_container.setMinimumWidth(320); right_panel_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        settings_group = QGroupBox("TTS 参数设置")
        settings_form_layout = QFormLayout(settings_group)
        self.default_lang_combo = QComboBox()
        for name, code in LANGUAGE_MAP_TTS.items(): self.default_lang_combo.addItem(name, code)
        gtts_conf = self.config.get("gtts_settings", {}); default_lang_val = gtts_conf.get("default_lang", "en-us")
        idx = self.default_lang_combo.findData(default_lang_val)
        if idx != -1: self.default_lang_combo.setCurrentIndex(idx)
        else: self.default_lang_combo.setCurrentIndex(self.default_lang_combo.findData("en-us") or 0)
        
        # ===== 修改/MODIFIED: 使用 ToggleSwitch 替换 QCheckBox =====
        self.auto_detect_lang_switch = self.ToggleSwitch()
        self.auto_detect_lang_switch.setChecked(gtts_conf.get("auto_detect", True))
        auto_detect_layout = QHBoxLayout()
        auto_detect_layout.addWidget(self.auto_detect_lang_switch)
        auto_detect_layout.addStretch()

        self.slow_speed_switch = self.ToggleSwitch()
        self.slow_speed_switch.setChecked(False)
        slow_speed_layout = QHBoxLayout()
        slow_speed_layout.addWidget(self.slow_speed_switch)
        slow_speed_layout.addStretch()

        output_dir_layout = QHBoxLayout()
        self.output_subdir_input = QLineEdit(f"tts_util_{datetime.now().strftime('%Y%m%d')}")
        self.output_subdir_input.setPlaceholderText("例如: my_project_tts")
        self.open_output_dir_btn = QPushButton("打开"); self.open_output_dir_btn.setToolTip("打开当前指定的输出文件夹")
        output_dir_layout.addWidget(self.output_subdir_input, 1); output_dir_layout.addWidget(self.open_output_dir_btn)
        
        settings_form_layout.addRow("默认转换语言:", self.default_lang_combo)
        settings_form_layout.addRow("语言检测:", auto_detect_layout)
        settings_form_layout.addRow("放慢语速:", slow_speed_layout)
        settings_form_layout.addRow("输出文件夹:", output_dir_layout)
        
        right_panel_main_layout.addWidget(settings_group)
        status_group = QGroupBox("转换状态与日志")
        status_layout = QVBoxLayout(status_group)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True); self.progress_bar.setValue(0); self.progress_bar.setFormat("%p% - 当前状态")
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True); self.log_output.setPlaceholderText("TTS转换日志将显示在此...")
        self.log_output.setFixedHeight(150) 
        status_layout.addWidget(self.progress_bar); status_layout.addWidget(self.log_output)
        right_panel_main_layout.addWidget(status_group) 
        right_panel_main_layout.addStretch(1) 
        action_buttons_group = QGroupBox("操作"); action_buttons_layout = QVBoxLayout(action_buttons_group)
        self.start_tts_btn = QPushButton("开始TTS转换"); self.start_tts_btn.setObjectName("AccentButton"); self.start_tts_btn.setFixedHeight(50)
        self.stop_tts_btn = QPushButton("停止当前任务"); self.stop_tts_btn.setEnabled(False); self.stop_tts_btn.setFixedHeight(50)
        action_buttons_layout.addWidget(self.start_tts_btn); action_buttons_layout.addWidget(self.stop_tts_btn)
        right_panel_main_layout.addWidget(action_buttons_group)
        main_layout.addWidget(left_panel, 6); main_layout.addWidget(right_panel_container, 4)
        self.add_table_row() 

    def _connect_signals(self):
        # ... (与上一版本一致)
        self.load_wordlist_btn.clicked.connect(self.load_wordlist_from_file)
        self.add_row_btn.clicked.connect(self.add_table_row)
        self.remove_row_btn.clicked.connect(self.remove_selected_table_row)
        self.clear_table_btn.clicked.connect(self.clear_editor_table)
        self.submit_edited_btn.clicked.connect(self.process_edited_list)
        self.start_tts_btn.clicked.connect(self.start_tts_processing)
        self.stop_tts_btn.clicked.connect(self.stop_tts_processing)
        self.open_output_dir_btn.clicked.connect(self.open_target_output_directory)

    def open_target_output_directory(self):
        # ... (与上一版本一致)
        subdir_name = self.output_subdir_input.text().strip()
        if not subdir_name: QMessageBox.warning(self, "目录为空", "请输入或确认输出子目录名称。"); return
        safe_subdir_name = re.sub(r'[\\/*?:"<>|]', "_", subdir_name)
        target_dir = os.path.join(self.AUDIO_TTS_DIR_ROOT, safe_subdir_name)
        if not os.path.exists(target_dir):
            reply = QMessageBox.question(self, "目录不存在", f"目录 '{target_dir}' 不存在。\n是否现在创建它？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                try: os.makedirs(target_dir); self.log_message(f"目录已创建: {target_dir}")
                except Exception as e: QMessageBox.critical(self, "创建失败", f"无法创建目录:\n{e}"); return
            else: return
        try:
            if sys.platform == 'win32': os.startfile(os.path.realpath(target_dir))
            elif sys.platform == 'darwin': subprocess.check_call(['open', target_dir])
            else: subprocess.check_call(['xdg-open', target_dir])
            self.log_message(f"尝试打开目录: {target_dir}")
        except Exception as e: QMessageBox.critical(self, "打开失败", f"无法打开目录:\n{e}")

    def log_message(self, message):
        # ... (与上一版本一致)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(f"[{timestamp}] {message}")
        self.log_output.ensureCursorVisible()

    def update_progress(self, value, text_format): 
        # ... (与上一版本一致)
        self.progress_bar.setValue(value); self.progress_bar.setFormat(text_format)

    def on_tts_task_finished(self, message):
        # ... (与上一版本一致)
        self.log_message(message)
        is_error_or_interrupted = "错误" in message or "中断" in message
        current_progress = self.progress_bar.value()
        self.progress_bar.setValue(100 if not is_error_or_interrupted else current_progress)
        self.progress_bar.setFormat(message if is_error_or_interrupted else "任务完成!")
        self.start_tts_btn.setEnabled(True); self.submit_edited_btn.setEnabled(True)
        self.load_wordlist_btn.setEnabled(True); self.stop_tts_btn.setEnabled(False)
        if self.tts_thread:
            if self.tts_thread.isRunning(): self.tts_thread.quit(); self.tts_thread.wait()
            self.tts_thread.deleteLater(); self.tts_thread = None
        if self.tts_worker: self.tts_worker.deleteLater(); self.tts_worker = None

    def add_table_row(self, word="", lang_code=""):
        # ... (与上一版本一致)
        row_position = self.editor_table.rowCount()
        self.editor_table.insertRow(row_position)
        self.editor_table.setItem(row_position, 0, QTableWidgetItem(word))
        lang_combo_in_table = QComboBox(); lang_combo_in_table.setIconSize(QSize(24, 18))
        current_selection_code = lang_code if lang_code else ""
        for display_name, code_val in LANGUAGE_MAP_TTS.items():
            flag_name = FLAG_CODE_MAP_TTS.get(code_val, "auto")
            icon_path = os.path.join(self.flags_path, f"{flag_name}.png")
            icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
            lang_combo_in_table.addItem(icon, display_name, code_val)
        index_to_set = lang_combo_in_table.findData(current_selection_code)
        if index_to_set != -1: lang_combo_in_table.setCurrentIndex(index_to_set)
        else: lang_combo_in_table.setCurrentIndex(lang_combo_in_table.findData("") or 0)
        self.editor_table.setCellWidget(row_position, 1, lang_combo_in_table)
        self.editor_table.scrollToBottom()

    def remove_selected_table_row(self):
        # ... (与上一版本一致)
        selected_rows = sorted(list(set(index.row() for index in self.editor_table.selectedIndexes())), reverse=True)
        if not selected_rows: QMessageBox.information(self, "提示", "请先选择要删除的行。"); return
        for row_index in selected_rows: self.editor_table.removeRow(row_index)

    def clear_editor_table(self):
        # ... (与上一版本一致)
        self.editor_table.setRowCount(0); self.add_table_row() 

    def load_wordlist_from_file(self):
        # ... (与上一版本一致)
        filepath, _ = QFileDialog.getOpenFileName(self, "选择标准词表文件", self.STD_WORD_LIST_DIR, "Python 文件 (*.py)")
        if not filepath: return
        self.current_wordlist_path = filepath; self.loaded_file_label.setText(os.path.basename(filepath))
        self.log_message(f"已加载词表: {os.path.basename(filepath)}")
        try:
            spec = importlib.util.spec_from_file_location("temp_wordlist_module", filepath)
            wordlist_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(wordlist_module)
            if not hasattr(wordlist_module, 'WORD_GROUPS'):
                QMessageBox.warning(self, "格式错误", "选择的Python文件不包含 'WORD_GROUPS' 变量。"); self.loaded_file_label.setText("加载失败，格式错误"); self.current_wordlist_path = None; return
            self.editor_table.setRowCount(0); words_to_add = []
            for group in wordlist_module.WORD_GROUPS:
                for word, value_tuple in group.items():
                    ipa, lang = value_tuple if isinstance(value_tuple, tuple) and len(value_tuple) == 2 else (str(value_tuple), "")
                    words_to_add.append({'text': word, 'lang': lang})
            for item in words_to_add: self.add_table_row(item['text'], item['lang'])
            self.log_message(f"词表中的 {len(words_to_add)} 个词条已填充到编辑器。")
        except Exception as e:
            QMessageBox.critical(self, "加载错误", f"加载词表文件失败: {e}"); self.loaded_file_label.setText("加载失败"); self.current_wordlist_path = None

    def get_items_from_editor(self):
        # ... (与上一版本一致)
        items = []
        for r in range(self.editor_table.rowCount()):
            text_item = self.editor_table.item(r, 0); text = text_item.text().strip() if text_item else ""
            lang_combo_widget = self.editor_table.cellWidget(r, 1); lang_code = lang_combo_widget.currentData() if lang_combo_widget else ""
            if text: items.append({'text': text, 'lang': lang_code})
        return items

    def process_edited_list(self):
        # ... (与上一版本一致)
        self.current_wordlist_path = None ; self.loaded_file_label.setText("<当前编辑列表>")
        self.start_tts_processing()

    def start_tts_processing(self):
        # ... (与上一版本一致，但会使用新的 self.auto_detect_lang_switch 和 self.slow_speed_switch)
        items_to_process = self.get_items_from_editor()
        source_description = self.loaded_file_label.text()
        if not items_to_process: QMessageBox.information(self, "无内容", "没有有效的词条进行TTS转换。"); return
        output_subdir_name = self.output_subdir_input.text().strip()
        if not output_subdir_name: output_subdir_name = f"tts_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}"; self.output_subdir_input.setText(output_subdir_name)
        output_subdir_name = re.sub(r'[\\/*?:"<>|]', "_", output_subdir_name)
        target_dir = os.path.join(self.AUDIO_TTS_DIR_ROOT, output_subdir_name)
        if not os.path.exists(target_dir):
            try: os.makedirs(target_dir)
            except Exception as e: QMessageBox.critical(self, "创建目录失败", f"无法创建输出子目录 '{target_dir}':\n{e}"); return
        
        self.log_message(f"开始TTS转换任务 ({source_description})... 输出到: {target_dir}")
        self.progress_bar.setValue(0); self.progress_bar.setFormat("准备中... (0%)")
        self.start_tts_btn.setEnabled(False); self.submit_edited_btn.setEnabled(False)
        self.load_wordlist_btn.setEnabled(False); self.stop_tts_btn.setEnabled(True)
        self.stop_tts_event.clear()
        
        # ===== 修改/MODIFIED: 从 ToggleSwitch 获取设置 =====
        tts_settings = {
            'default_lang': self.default_lang_combo.currentData(), 
            'auto_detect': self.auto_detect_lang_switch.isChecked(), 
            'slow': self.slow_speed_switch.isChecked()
        }

        self.tts_thread = QThread()
        self.tts_worker = self.Worker(self._perform_tts_task, items_to_process, target_dir, tts_settings, self.stop_tts_event)
        self.tts_worker.moveToThread(self.tts_thread)
        self.tts_worker.progress.connect(self.update_progress) 
        self.tts_worker.finished.connect(self.task_finished_signal.emit) 
        self.tts_worker.error.connect(lambda e_msg: self.task_finished_signal.emit(f"TTS任务出错: {e_msg}"))
        self.tts_thread.started.connect(self.tts_worker.run)
        self.tts_worker.finished.connect(self.tts_thread.quit) 
        self.tts_thread.start()

    def stop_tts_processing(self):
        # ... (与上一版本一致)
        if self.tts_thread and self.tts_thread.isRunning():
            self.stop_tts_event.set()
            self.log_message("已发送停止请求，正在等待当前条目处理完毕...")
            self.stop_tts_btn.setEnabled(False) 

    def _perform_tts_task(self, worker_instance, items, target_dir, tts_settings, stop_event):
        # ... (与上一版本一致)
        total_items = len(items); processed_count = 0; errors = []
        worker_instance.progress.emit(0, "准备开始...") 
        for i, item_data in enumerate(items):
            if stop_event.is_set(): self.log_message_signal.emit("TTS任务被用户提前中断。"); return "TTS任务被用户中断。"
            text_to_speak = item_data['text']; lang_code = item_data['lang']
            if not lang_code: 
                if tts_settings['auto_detect']:
                    detected = self.detect_language(text_to_speak)
                    lang_code = detected if detected else tts_settings['default_lang']
                else: lang_code = tts_settings['default_lang']
            if not lang_code: lang_code = "en-us" 
            safe_filename_base = re.sub(r'[^\w\s-]', '', text_to_speak).strip().replace(' ', '_')
            if not safe_filename_base: safe_filename_base = f"item_{i+1}_ts{int(time.time())}"
            safe_filename_base = safe_filename_base[:50] 
            output_filepath = os.path.join(target_dir, f"{safe_filename_base}.mp3")
            counter = 1; temp_filepath = output_filepath
            while os.path.exists(temp_filepath):
                temp_filepath = os.path.join(target_dir, f"{safe_filename_base}_{counter}.mp3"); counter += 1
            output_filepath = temp_filepath
            progress_percent = int(((i + 1) / total_items) * 100)
            progress_text_format = f"处理中 ({i+1}/{total_items}): {text_to_speak[:20]}..." if len(text_to_speak) > 20 else f"处理中 ({i+1}/{total_items}): {text_to_speak}"
            worker_instance.progress.emit(progress_percent, progress_text_format)
            try:
                tts = gTTS(text=text_to_speak, lang=lang_code, slow=tts_settings['slow'])
                tts.save(output_filepath); processed_count += 1
            except Exception as e:
                error_msg = f"错误处理 '{text_to_speak}' (Lang: {lang_code}): {type(e).__name__} - {str(e)}"
                errors.append(error_msg); print(error_msg) 
            if stop_event.is_set(): self.log_message_signal.emit("TTS任务在条目处理后被中断。"); return "TTS任务被用户中断 (在条目处理后)。"
        completion_message = f"TTS转换完成！成功处理 {processed_count}/{total_items} 个词条。"
        if errors: completion_message += f"\n发生 {len(errors)} 个错误 (详情请查看控制台或日志)。"
        return completion_message