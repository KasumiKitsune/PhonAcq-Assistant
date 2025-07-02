# --- START OF FILE modules/tts_utility_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "TTS 工具"
MODULE_DESCRIPTION = "批量或即时将文本转换为语音，支持多种语言和自定义输出，可直接为速记卡模块生成音频。"
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
    from gtts.tts import gTTSError
    DEPENDENCIES_MISSING = False
except ImportError as e:
    print(f"CRITICAL: tts_utility_module.py - Missing gTTS: {e}")
    DEPENDENCIES_MISSING = True
    MISSING_ERROR_MESSAGE = str(e)
    class gTTSError(Exception): pass


def get_base_path_for_module():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

LANGUAGE_MAP_TTS = {
    "自动检测": "", 
    "英语 (美国)": "en-us", 
    "英语 (英国)": "en-uk", 
    "中文 (普通话)": "zh-cn",
    "日语": "ja",
    "韩语": "ko",
    "法语 (法国)": "fr", # fr-fr, fr-ca 等映射到 fr
    "德语": "de",
    "西班牙语": "es",
    "葡萄牙语": "pt",
    "意大利语": "it",
    "俄语": "ru",
    "荷兰语": "nl",
    "波兰语": "pl",
    "土耳其语": "tr",
    "越南语": "vi",
    "印地语": "hi",
    "阿拉伯语": "ar",
    "泰语": "th",
    "印尼语": "id",
    # ...可以继续添加更多gTTS支持的语言...
}

# [修复] 对应的旗帜代码映射
FLAG_CODE_MAP_TTS = {
    "": "auto", "en-us": "us", "en-uk": "gb", "zh-cn": "cn", 
    "ja": "jp", "ko": "kr", "fr": "fr", "de": "de", "es": "es", "pt": "pt",
    "it": "it", "ru": "ru", "nl": "nl", "pl": "pl", "tr": "tr",
    "vi": "vn", "hi": "in", "ar": "sa", "th": "th", "id": "id",
}

# [修改] 接收 icon_manager
def create_page(parent_window, config, AUDIO_TTS_DIR_ROOT, ToggleSwitchClass, WorkerClass, detect_language_func, STD_WORD_LIST_DIR, icon_manager):
    if DEPENDENCIES_MISSING:
        error_page = QWidget(); layout = QVBoxLayout(error_page)
        label = QLabel(f"TTS 工具模块加载失败：\n缺少 gTTS 库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install gTTS")
        label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); layout.addWidget(label)
        return error_page
    return TtsUtilityPage(parent_window, config, AUDIO_TTS_DIR_ROOT, ToggleSwitchClass, WorkerClass, detect_language_func, STD_WORD_LIST_DIR, icon_manager)


class TtsUtilityPage(QWidget):
    log_message_signal = pyqtSignal(str)
    task_finished_signal = pyqtSignal(str)

    # [修改] 接收 icon_manager
    def __init__(self, parent_window, config, AUDIO_TTS_DIR_ROOT, ToggleSwitchClass, WorkerClass, detect_language_func, STD_WORD_LIST_DIR, icon_manager):
        super().__init__()
        self.parent_window = parent_window; self.config = config 
        self.AUDIO_TTS_DIR_ROOT = AUDIO_TTS_DIR_ROOT 
        self.ToggleSwitch = ToggleSwitchClass; self.Worker = WorkerClass
        self.detect_language = detect_language_func
        self.STD_WORD_LIST_DIR = STD_WORD_LIST_DIR 
        self.icon_manager = icon_manager # [新增] 保存 icon_manager 实例

        self.current_wordlist_path = None
        self.tts_thread = None; self.tts_worker = None 
        self.stop_tts_event = threading.Event()
        
        self.base_path_module = get_base_path_for_module() 
        self.flags_path = os.path.join(self.base_path_module, 'assets', 'flags')

        self.setAcceptDrops(True)
        self._init_ui()
        self._connect_signals()
        self.update_icons() # [新增] 首次加载时更新图标
        self.log_message_signal.connect(self.log_message)
        self.task_finished_signal.connect(self.on_tts_task_finished)

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        left_panel = QWidget(); left_layout = QVBoxLayout(left_panel); left_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        load_group = QGroupBox("从文件批量转换")
        load_layout = QFormLayout(load_group)
        # [修改] 只创建按钮，不在此设置图标
        self.load_wordlist_btn = QPushButton("加载词表 (.py)")
        self.load_wordlist_btn.setToolTip("点击选择一个标准词表或图文词表文件，\n其内容将填充到下方的编辑器中。\n也可以将文件直接拖拽到此模块窗口。")
        self.loaded_file_label = QLabel("未加载文件"); self.loaded_file_label.setWordWrap(True)
        self.loaded_file_label.setToolTip("当前加载的词表文件名。若未加载文件，则表示使用当前编辑器中的文本进行转换。")
        load_layout.addRow(self.load_wordlist_btn); load_layout.addRow(QLabel("当前文件:"), self.loaded_file_label)
        
        editor_group = QGroupBox("即时编辑与转换"); editor_v_layout = QVBoxLayout(editor_group)
        self.editor_table = QTableWidget(); self.editor_table.setColumnCount(2); self.editor_table.setHorizontalHeaderLabels(["待转换文本 (单词或ID)", "语言"])
        self.editor_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch); self.editor_table.setColumnWidth(1, 200); self.editor_table.setAlternatingRowColors(True)
        self.editor_table.setToolTip("在此表格中直接编辑要转换的文本和对应的语言。\n留空语言列将使用右侧的默认设置。")
        editor_btn_layout = QHBoxLayout()
        # [修改] 只创建按钮，不在此设置图标
        self.add_row_btn = QPushButton("添加行"); self.add_row_btn.setToolTip("在表格末尾添加一个空行。")
        self.remove_row_btn = QPushButton("删除选中行"); self.remove_row_btn.setToolTip("删除表格中所有选中的行。")
        self.clear_table_btn = QPushButton("清空列表"); self.clear_table_btn.setToolTip("清空整个编辑列表。")
        editor_btn_layout.addWidget(self.add_row_btn); editor_btn_layout.addWidget(self.remove_row_btn); editor_btn_layout.addWidget(self.clear_table_btn); editor_btn_layout.addStretch()
        # [修改] 只创建按钮，不在此设置图标
        self.submit_edited_btn = QPushButton("提交当前列表进行TTS"); self.submit_edited_btn.setObjectName("AccentButton")
        self.submit_edited_btn.setToolTip("将当前表格中的所有有效行作为转换任务，\n不考虑已加载的文件。")
        editor_v_layout.addWidget(self.editor_table); editor_v_layout.addLayout(editor_btn_layout); editor_v_layout.addWidget(self.submit_edited_btn, 0, Qt.AlignRight)
        left_layout.addWidget(load_group); left_layout.addWidget(editor_group); left_panel.setMinimumWidth(450)

        right_panel_container = QWidget(); right_panel_main_layout = QVBoxLayout(right_panel_container); right_panel_container.setMinimumWidth(320); right_panel_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        settings_group = QGroupBox("TTS 参数设置"); settings_form_layout = QFormLayout(settings_group)
        self.default_lang_combo = QComboBox(); self.default_lang_combo.setToolTip("当列表中的语言列为空时，将使用此处的默认语言。")
        for name, code in LANGUAGE_MAP_TTS.items(): self.default_lang_combo.addItem(name, code)
        gtts_conf = self.config.get("gtts_settings", {}); default_lang_val = gtts_conf.get("default_lang", "en-us")
        idx = self.default_lang_combo.findData(default_lang_val); self.default_lang_combo.setCurrentIndex(idx if idx != -1 else 0)
        self.auto_detect_lang_switch = self.ToggleSwitch(); self.auto_detect_lang_switch.setChecked(gtts_conf.get("auto_detect", True)); self.auto_detect_lang_switch.setToolTip("开启后，将尝试自动检测文本的语言（如中/日/韩），\n如果检测失败，则使用上面的默认语言。")
        auto_detect_layout = QHBoxLayout(); auto_detect_layout.addWidget(self.auto_detect_lang_switch); auto_detect_layout.addStretch()
        self.slow_speed_switch = self.ToggleSwitch(); self.slow_speed_switch.setChecked(False); self.slow_speed_switch.setToolTip("开启后，将以较慢的语速生成语音，适合教学场景。")
        slow_speed_layout = QHBoxLayout(); slow_speed_layout.addWidget(self.slow_speed_switch); slow_speed_layout.addStretch()
        
        self.output_to_flashcard_switch = self.ToggleSwitch(); self.output_to_flashcard_switch.setChecked(False); self.output_to_flashcard_switch.setToolTip("开启后，音频将直接生成到“速记卡”模块对应的词表文件夹内。\n此模式下，必须先加载一个词表文件以确定目标文件夹。")
        flashcard_output_layout = QHBoxLayout(); flashcard_output_layout.addWidget(self.output_to_flashcard_switch); flashcard_output_layout.addStretch()

        output_dir_layout = QHBoxLayout()
        self.output_subdir_input = QLineEdit(f"tts_util_{datetime.now().strftime('%Y%m%d')}"); self.output_subdir_input.setPlaceholderText("例如: my_project_tts"); self.output_subdir_input.setToolTip("生成的音频文件将被保存在 audio_tts/ 下的这个子文件夹中。")
        # [修改] 只创建按钮，不在此设置图标
        self.open_output_dir_btn = QPushButton("打开"); self.open_output_dir_btn.setToolTip("在文件浏览器中打开当前指定的输出文件夹。")
        output_dir_layout.addWidget(self.output_subdir_input, 1); output_dir_layout.addWidget(self.open_output_dir_btn)
        
        settings_form_layout.addRow("默认转换语言:", self.default_lang_combo)
        settings_form_layout.addRow("语言检测:", auto_detect_layout)
        settings_form_layout.addRow("放慢语速:", slow_speed_layout)
        settings_form_layout.addRow("输出到速记卡模块:", flashcard_output_layout)
        settings_form_layout.addRow("自定义输出文件夹:", output_dir_layout)
        
        right_panel_main_layout.addWidget(settings_group)
        status_group = QGroupBox("转换状态与日志"); status_layout = QVBoxLayout(status_group)
        self.progress_bar = QProgressBar(); self.progress_bar.setTextVisible(True); self.progress_bar.setValue(0); self.progress_bar.setFormat("%p% - 当前状态")
        self.progress_bar.setToolTip("显示当前TTS转换任务的总体进度。") # [新增] tooltip
        self.log_output = QPlainTextEdit(); self.log_output.setReadOnly(True); self.log_output.setPlaceholderText("TTS转换日志将显示在此..."); self.log_output.setFixedHeight(150) 
        self.log_output.setToolTip("显示TTS转换过程中的详细日志信息和错误报告。") # [新增] tooltip
        status_layout.addWidget(self.progress_bar); status_layout.addWidget(self.log_output)
        right_panel_main_layout.addWidget(status_group); right_panel_main_layout.addStretch(1) 
        action_buttons_group = QGroupBox("操作"); action_buttons_layout = QVBoxLayout(action_buttons_group)
        # [修改] 只创建按钮，不在此设置图标
        self.start_tts_btn = QPushButton("开始TTS转换"); self.start_tts_btn.setObjectName("AccentButton"); self.start_tts_btn.setFixedHeight(50); self.start_tts_btn.setToolTip("使用当前编辑器列表和右侧的设置，开始批量转换任务。")
        self.stop_tts_btn = QPushButton("停止当前任务"); self.stop_tts_btn.setEnabled(False); self.stop_tts_btn.setFixedHeight(50); self.stop_tts_btn.setToolTip("请求中止正在进行的批量转换任务。")
        action_buttons_layout.addWidget(self.start_tts_btn); action_buttons_layout.addWidget(self.stop_tts_btn)
        right_panel_main_layout.addWidget(action_buttons_group)
        main_layout.addWidget(left_panel, 6); main_layout.addWidget(right_panel_container, 4)
        self.add_table_row() 

    def _connect_signals(self):
        self.load_wordlist_btn.clicked.connect(self.load_wordlist_from_file)
        self.add_row_btn.clicked.connect(self.add_table_row)
        self.remove_row_btn.clicked.connect(self.remove_selected_table_row)
        self.clear_table_btn.clicked.connect(self.clear_editor_table)
        self.submit_edited_btn.clicked.connect(self.process_edited_list)
        self.start_tts_btn.clicked.connect(self.start_tts_processing)
        self.stop_tts_btn.clicked.connect(self.stop_tts_processing)
        self.open_output_dir_btn.clicked.connect(self.open_target_output_directory)
        self.output_to_flashcard_switch.stateChanged.connect(self.toggle_output_dir_input)
    
    # --- [新增] 更新图标的方法 ---
    def update_icons(self):
        """从IconManager获取并设置所有图标。"""
        self.load_wordlist_btn.setIcon(self.icon_manager.get_icon("open_file"))
        self.add_row_btn.setIcon(self.icon_manager.get_icon("add_row"))
        self.remove_row_btn.setIcon(self.icon_manager.get_icon("remove_row"))
        self.clear_table_btn.setIcon(self.icon_manager.get_icon("delete")) 
        self.submit_edited_btn.setIcon(self.icon_manager.get_icon("submit_process")) # 新图标
        self.open_output_dir_btn.setIcon(self.icon_manager.get_icon("open_folder"))
        self.start_tts_btn.setIcon(self.icon_manager.get_icon("start_session"))
        self.stop_tts_btn.setIcon(self.icon_manager.get_icon("stop"))

    # --- [新增] 拖放事件处理 ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                filepath = urls[0].toLocalFile()
                if filepath.lower().endswith('.py'):
                    event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            filepath = event.mimeData().urls()[0].toLocalFile()
            self.load_wordlist_from_file(filepath)

    def toggle_output_dir_input(self, state):
        self.output_subdir_input.setEnabled(not state)

    def open_target_output_directory(self):
        is_for_flashcard = self.output_to_flashcard_switch.isChecked()
        target_dir = ""
        if is_for_flashcard:
            if not self.current_wordlist_path: QMessageBox.warning(self, "未加载文件", "请先加载一个词表以确定速记卡输出目录。"); return
            wordlist_name = os.path.splitext(os.path.basename(self.current_wordlist_path))[0]
            target_dir = os.path.join(self.base_path_module, "flashcards", "audio_tts", wordlist_name)
        else:
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
        except Exception as e: QMessageBox.critical(self, "打开失败", f"无法打开目录:\n{e}")

    def log_message(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S"); self.log_output.appendPlainText(f"[{timestamp}] {message}"); self.log_output.ensureCursorVisible()

    def update_progress(self, value, text_format): 
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(text_format)
        self.parent_window.statusBar().showMessage(text_format, 2000)

    def on_tts_task_finished(self, message):
        self.log_message(message)
        is_error = "错误" in message or "中断" in message
        self.progress_bar.setValue(100 if not is_error else self.progress_bar.value())
        self.progress_bar.setFormat(message if is_error else "任务完成!")
        self.parent_window.statusBar().showMessage(message, 5000)
        self.start_tts_btn.setEnabled(True); self.submit_edited_btn.setEnabled(True); self.load_wordlist_btn.setEnabled(True)
        self.stop_tts_btn.setEnabled(False)
        if self.tts_thread and self.tts_thread.isRunning(): 
            self.tts_thread.quit(); self.tts_thread.wait()

    def add_table_row(self, word="", lang_code=""):
        row_pos = self.editor_table.rowCount(); self.editor_table.insertRow(row_pos); self.editor_table.setItem(row_pos, 0, QTableWidgetItem(word))
        combo = QComboBox(); combo.setIconSize(QSize(24, 18))
        for name, code in LANGUAGE_MAP_TTS.items():
            icon_path = os.path.join(self.flags_path, f"{FLAG_CODE_MAP_TTS.get(code, 'auto')}.png")
            combo.addItem(QIcon(icon_path) if os.path.exists(icon_path) else QIcon(), name, code)
        idx = combo.findData(lang_code or ""); combo.setCurrentIndex(idx if idx != -1 else 0)
        self.editor_table.setCellWidget(row_pos, 1, combo); self.editor_table.scrollToBottom()

    def remove_selected_table_row(self):
        rows = sorted(list(set(index.row() for index in self.editor_table.selectedIndexes())), reverse=True)
        if not rows: QMessageBox.information(self, "提示", "请先选择要删除的行。"); return
        for r in rows: self.editor_table.removeRow(r)

    def clear_editor_table(self):
        self.editor_table.setRowCount(0); self.add_table_row() 

    def load_wordlist_from_file(self, filepath=None):
        if not filepath:
            filepath, _ = QFileDialog.getOpenFileName(self, "选择标准或图文词表文件", self.STD_WORD_LIST_DIR, "Python 文件 (*.py)")
        if not filepath: return
        self.current_wordlist_path = filepath; self.loaded_file_label.setText(os.path.basename(filepath))
        self.log_message(f"已加载词表: {os.path.basename(filepath)}")
        try:
            spec = importlib.util.spec_from_file_location("temp_tts_wordlist", filepath); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            self.editor_table.setRowCount(0); words_to_add = []
            if hasattr(module, 'WORD_GROUPS'):
                for group in module.WORD_GROUPS:
                    for word, value in group.items(): _, lang = value if isinstance(value, tuple) and len(value) == 2 else ("", ""); words_to_add.append({'text': word, 'lang': lang})
            elif hasattr(module, 'ITEMS'):
                for item in module.ITEMS: text_to_read = item.get('id', ''); words_to_add.append({'text': text_to_read, 'lang': ''})
            else: QMessageBox.warning(self, "格式错误", "选择的Python文件既不包含 'WORD_GROUPS' 也不包含 'ITEMS' 变量。"); self.loaded_file_label.setText("加载失败，格式错误"); self.current_wordlist_path = None; return
            for item in words_to_add: self.add_table_row(item['text'], item['lang'])
            self.log_message(f"词表中的 {len(words_to_add)} 个词条已填充到编辑器。")
        except Exception as e: QMessageBox.critical(self, "加载错误", f"加载词表文件失败: {e}"); self.loaded_file_label.setText("加载失败"); self.current_wordlist_path = None

    def get_items_from_editor(self):
        items = []
        for r in range(self.editor_table.rowCount()):
            text_item = self.editor_table.item(r, 0); text = text_item.text().strip() if text_item else ""
            lang_combo = self.editor_table.cellWidget(r, 1); lang_code = lang_combo.currentData() if lang_combo else ""
            if text: items.append({'text': text, 'lang': lang_code})
        return items

    def process_edited_list(self):
        self.current_wordlist_path = None ; self.loaded_file_label.setText("<当前编辑列表>")
        self.start_tts_processing()

    def start_tts_processing(self):
        items_to_process = self.get_items_from_editor()
        if not items_to_process: QMessageBox.information(self, "无内容", "没有有效的词条进行TTS转换。"); return
        is_for_flashcard = self.output_to_flashcard_switch.isChecked(); target_dir = ""
        if is_for_flashcard:
            if not self.current_wordlist_path: QMessageBox.warning(self, "模式错误", "“输出到速记卡模块”模式需要先加载一个词表文件。"); return
            wordlist_name = os.path.splitext(os.path.basename(self.current_wordlist_path))[0]; target_dir = os.path.join(self.base_path_module, "flashcards", "audio_tts", wordlist_name)
        else:
            subdir_name = self.output_subdir_input.text().strip()
            if not subdir_name: subdir_name = f"tts_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}"; self.output_subdir_input.setText(subdir_name)
            safe_subdir_name = re.sub(r'[\\/*?:"<>|]', "_", subdir_name); target_dir = os.path.join(self.AUDIO_TTS_DIR_ROOT, safe_subdir_name)
        if not os.path.exists(target_dir):
            try: os.makedirs(target_dir)
            except Exception as e: QMessageBox.critical(self, "创建目录失败", f"无法创建输出目录 '{target_dir}':\n{e}"); return
        source_desc = os.path.basename(self.current_wordlist_path) if self.current_wordlist_path else "<当前编辑列表>"
        self.log_message(f"开始TTS转换任务 ({source_desc})... 输出到: {target_dir}"); self.progress_bar.setValue(0); self.progress_bar.setFormat("准备中... (0%)")
        self.start_tts_btn.setEnabled(False); self.submit_edited_btn.setEnabled(False); self.load_wordlist_btn.setEnabled(False); self.stop_tts_btn.setEnabled(True)
        self.stop_tts_event.clear()
        tts_settings = {'default_lang': self.default_lang_combo.currentData(), 'auto_detect': self.auto_detect_lang_switch.isChecked(), 'slow': self.slow_speed_switch.isChecked()}
        self.tts_thread = QThread(); self.tts_worker = self.Worker(self._perform_tts_task, items_to_process, target_dir, tts_settings, self.stop_tts_event, is_for_flashcard)
        self.tts_worker.moveToThread(self.tts_thread); self.tts_worker.progress.connect(self.update_progress) 
        self.tts_worker.finished.connect(self.task_finished_signal.emit); self.tts_worker.error.connect(lambda e_msg: self.task_finished_signal.emit(f"TTS任务出错: {e_msg}"))
        self.tts_thread.started.connect(self.tts_worker.run); self.tts_worker.finished.connect(self.tts_thread.quit) 
        self.tts_thread.start()

    def stop_tts_processing(self):
        if self.tts_thread and self.tts_thread.isRunning():
            self.stop_tts_event.set(); self.log_message("已发送停止请求..."); self.stop_tts_btn.setEnabled(False) 

    def _perform_tts_task(self, worker_instance, items, target_dir, tts_settings, stop_event, is_for_flashcard):
        total_items = len(items); processed_count = 0; errors = []
        worker_instance.progress.emit(0, "准备开始...") 
        for i, item_data in enumerate(items):
            if stop_event.is_set(): return "TTS任务被用户中断。"
            
            text_to_speak_original = item_data['text']; lang_code = item_data['lang']
            text_to_speak_processed = text_to_speak_original.replace('_', ' ')
            
            if not lang_code: 
                if tts_settings['auto_detect']: lang_code = self.detect_language(text_to_speak_processed) or tts_settings['default_lang']
                else: lang_code = tts_settings['default_lang']
            if not lang_code: lang_code = "en-us" 
            
            safe_filename_base = text_to_speak_original if is_for_flashcard else re.sub(r'[^\w\s-]', '', text_to_speak_original).strip().replace(' ', '_')
            if not safe_filename_base: safe_filename_base = f"item_{i+1}_ts{int(time.time())}"
            safe_filename_base = safe_filename_base[:50] 
            output_filepath = os.path.join(target_dir, f"{safe_filename_base}.mp3")
            if not is_for_flashcard and os.path.exists(output_filepath):
                counter = 1; temp_filepath = output_filepath
                while os.path.exists(temp_filepath): temp_filepath = os.path.join(target_dir, f"{safe_filename_base}_{counter}.mp3"); counter += 1
                output_filepath = temp_filepath

            progress_percent = int(((i + 1) / total_items) * 100)
            progress_text_format = f"处理中 ({i+1}/{total_items}): {text_to_speak_original[:20]}..."
            worker_instance.progress.emit(progress_percent, progress_text_format)
            
            # --- CFE-6: 失败重试机制 ---
            success = False
            for attempt in range(3):
                if stop_event.is_set(): return "TTS任务被用户中断。"
                try:
                    tts = gTTS(text=text_to_speak_processed, lang=lang_code, slow=tts_settings['slow'])
                    tts.save(output_filepath)
                    success = True
                    break
                except gTTSError as e:
                    log_msg = f"网络错误 (尝试 {attempt+1}/3) 处理 '{text_to_speak_original}': {e}"
                    self.log_message_signal.emit(log_msg)
                    if attempt < 2: time.sleep(1.5)
                except Exception as e:
                    log_msg = f"未知错误处理 '{text_to_speak_original}': {type(e).__name__}"
                    self.log_message_signal.emit(log_msg)
                    errors.append(log_msg)
                    break
            
            if success:
                processed_count += 1
            else:
                errors.append(f"最终失败: '{text_to_speak_original}'")
        
        completion_message = f"TTS转换完成！成功处理 {processed_count}/{total_items} 个词条。"
        if errors: completion_message += f"\n发生 {len(errors)} 个错误 (详情请查看上方日志)。"
        return completion_message