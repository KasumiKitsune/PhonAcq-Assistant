# --- START OF FILE modules/tts_utility_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "TTS 工具"
MODULE_DESCRIPTION = "批量或即时将文本转换为语音，支持多种语言和自定义输出，可直接为速记卡模块生成音频。"
# ---

import os
import sys
import threading
import time
from datetime import datetime
import re 
import subprocess 
import json
import asyncio

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QFileDialog, QMessageBox, QComboBox, QFormLayout,
                             QGroupBox, QProgressBar, QLineEdit, QTableWidget,
                             QTableWidgetItem, QHeaderView, QPlainTextEdit,QApplication, QAbstractItemView, QListWidgetItem,
                             QSplitter, QSizePolicy, QDialog, QStackedWidget, QFrame, QCheckBox, QDialogButtonBox, QSlider)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize 
from PyQt5.QtGui import QIcon, QPalette
from modules.custom_widgets_module import WordlistSelectionDialog
# [核心修改] 从一个 import 变为两个
from modules.language_detector_module import detect_language, detect_language_for_edge_tts


# --- 依赖检查 ---
try:
    from gtts import gTTS
    from gtts.tts import gTTSError
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False
    class gTTSError(Exception): pass

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

DEPENDENCIES_MISSING = not GTTS_AVAILABLE and not EDGE_TTS_AVAILABLE
MISSING_ERROR_MESSAGE = "至少需要安装 gTTS 或 edge-tts 库。\n请运行: pip install gTTS edge-tts"


def get_base_path_for_module():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

LANGUAGE_MAP_TTS = {
    "自动检测": "", "英语 (美国)": "en-us", "英语 (英国)": "en-uk", "中文 (普通话)": "zh-cn", "日语": "ja", "韩语": "ko",
    "法语 (法国)": "fr", "德语": "de", "西班牙语": "es", "葡萄牙语": "pt", "意大利语": "it", "俄语": "ru",
    "荷兰语": "nl", "波兰语": "pl", "土耳其语": "tr", "越南语": "vi", "印地语": "hi", "阿拉伯语": "ar", "泰语": "th", "印尼语": "id",
}

FLAG_CODE_MAP_TTS = {
    "": "auto", "en-us": "us", "en-uk": "gb", "zh-cn": "cn", "ja": "jp", "ko": "kr", "fr": "fr", "de": "de", "es": "es", "pt": "pt",
    "it": "it", "ru": "ru", "nl": "nl", "pl": "pl", "tr": "tr", "vi": "vn", "hi": "in", "ar": "sa", "th": "th", "id": "id",
}

EDGE_TTS_DEFAULT_VOICES = {
    "zh-cn": "zh-CN-XiaoxiaoNeural",
    "en-us": "en-US-JennyNeural",
    "en-uk": "en-GB-LibbyNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "es": "es-ES-ElviraNeural",
    "ru": "ru-RU-SvetlanaNeural",
    # 可以为其他语言添加更多默认语音...
}
EDGE_TTS_SUPPORTED_LANG_CODES = set(EDGE_TTS_DEFAULT_VOICES.keys())
EDGE_TTS_LANGUAGE_MAP = { "自动检测": "" }
for name, code in LANGUAGE_MAP_TTS.items():
    if code in EDGE_TTS_SUPPORTED_LANG_CODES:
        EDGE_TTS_LANGUAGE_MAP[name] = code
def create_page(parent_window, config, AUDIO_TTS_DIR_ROOT, ToggleSwitchClass, WorkerClass, detect_language_func, STD_WORD_LIST_DIR, icon_manager):
    if DEPENDENCIES_MISSING:
        error_page = QWidget(); layout = QVBoxLayout(error_page)
        label = QLabel(f"TTS 工具模块加载失败：\n{MISSING_ERROR_MESSAGE}")
        label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); layout.addWidget(label)
        return error_page
    # detect_language_func 现在是通用的gTTS检测函数
    return TtsUtilityPage(parent_window, config, AUDIO_TTS_DIR_ROOT, ToggleSwitchClass, WorkerClass, detect_language_func, STD_WORD_LIST_DIR, icon_manager)
class ClickableLabel(QLabel):
    """一个可以发射 clicked 信号的 QLabel。"""
    clicked = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

class TtsUtilityPage(QWidget):
    log_message_signal = pyqtSignal(str)
    task_finished_signal = pyqtSignal(object)
    # [核心新增] 定义用于占位符行的自定义角色
    ADD_NEW_ROW_ROLE = Qt.UserRole + 101

    def __init__(self, parent_window, config, AUDIO_TTS_DIR_ROOT, ToggleSwitchClass, WorkerClass, detect_language_func, STD_WORD_LIST_DIR, icon_manager):
        super().__init__()
        self.parent_window = parent_window; self.config = config 
        self.AUDIO_TTS_DIR_ROOT = AUDIO_TTS_DIR_ROOT 
        self.ToggleSwitch = ToggleSwitchClass; self.Worker = WorkerClass
        # detect_language_func 保持为 gTTS 的语言检测函数
        self.detect_language = detect_language_func 
        self.STD_WORD_LIST_DIR = STD_WORD_LIST_DIR 
        self.icon_manager = icon_manager

        self.current_wordlist_path = None
        self.tts_thread = None; self.tts_worker = None 
        self.stop_tts_event = threading.Event()
        self.last_loaded_wordlist_name = None
        
        self.base_path_module = get_base_path_for_module() 
        self.flags_path = os.path.join(self.base_path_module, 'assets', 'flags')

        self.setAcceptDrops(True)
        self._init_ui()
        self._connect_signals()
        self.update_icons()
        self.log_message_signal.connect(self.log_message)
        self.task_finished_signal.connect(self.on_tts_task_finished)
        self._setup_hooks()
        
        # [核心修复] __init__ 完成后，手动添加一次占位符行
        self._add_placeholder_row()

    def _setup_hooks(self):
        QTimer.singleShot(0, self._set_wordlist_editor_hook)

    def _set_wordlist_editor_hook(self):
        wordlist_editor_page = getattr(self.parent_window, 'wordlist_editor_page', None)
        if wordlist_editor_page:
            wordlist_editor_page.tts_utility_hook = self
            print("[TTS Utility] Hooked into Wordlist Editor successfully.")
        else:
            print("[TTS Utility] Warning: Wordlist Editor page not found, cannot set up hook.")

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        left_panel = QWidget(); left_layout = QVBoxLayout(left_panel); left_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        load_group = QGroupBox("从文件批量转换")
        load_layout = QFormLayout(load_group)
        self.load_wordlist_btn = QPushButton("加载词表...")
        self.load_wordlist_btn.setToolTip("点击选择一个标准词表或速记卡文件，\n其内容将填充到下方的编辑器中。\n也可以将文件直接拖拽到此模块窗口。")
        self.loaded_file_label = QLabel("未加载文件"); self.loaded_file_label.setWordWrap(True)
        self.loaded_file_label.setToolTip("当前加载的词表文件名。若未加载文件，则表示使用当前编辑器中的文本进行转换。")
        load_layout.addRow(self.load_wordlist_btn); load_layout.addRow(QLabel("当前文件:"), self.loaded_file_label)
        
        editor_group = QGroupBox("即时编辑与转换"); editor_v_layout = QVBoxLayout(editor_group)
        self.editor_table = QTableWidget(); self.editor_table.setColumnCount(2); self.editor_table.setHorizontalHeaderLabels(["待转换文本 (单词或ID)", "语言"])
        self.editor_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch); self.editor_table.setColumnWidth(1, 200); self.editor_table.setAlternatingRowColors(True)
        self.editor_table.setToolTip("在此表格中直接编辑要转换的文本和对应的语言。\n留空语言列将使用右侧的默认设置。")
        editor_btn_layout = QHBoxLayout()
        self.add_row_btn = QPushButton("添加行"); self.add_row_btn.setToolTip("在表格末尾添加一个空行。")
        self.remove_row_btn = QPushButton("删除选中行"); self.remove_row_btn.setToolTip("删除表格中所有选中的行。")
        self.clear_table_btn = QPushButton("清空列表"); self.clear_table_btn.setToolTip("清空整个编辑列表。")
        editor_btn_layout.addWidget(self.add_row_btn); editor_btn_layout.addWidget(self.remove_row_btn); editor_btn_layout.addWidget(self.clear_table_btn); editor_btn_layout.addStretch()
        self.submit_edited_btn = QPushButton("提交当前列表进行TTS"); self.submit_edited_btn.setObjectName("AccentButton")
        self.submit_edited_btn.setToolTip("将当前表格中的所有有效行作为转换任务，\n不考虑已加载的文件。")
        editor_v_layout.addWidget(self.editor_table); editor_v_layout.addLayout(editor_btn_layout); editor_v_layout.addWidget(self.submit_edited_btn, 0, Qt.AlignRight)
        left_layout.addWidget(load_group); left_layout.addWidget(editor_group); left_panel.setMinimumWidth(450)

        right_panel_container = QWidget(); right_panel_main_layout = QVBoxLayout(right_panel_container); right_panel_container.setMinimumWidth(320); right_panel_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        
        settings_group = QGroupBox("TTS 参数设置")
        self.settings_form_layout = QFormLayout(settings_group)
        
        module_states = self.config.get("module_states", {}).get("tts_utility", {})
        self.current_engine = module_states.get("tts_engine", "gtts" if GTTS_AVAILABLE else "edge-tts")
        self._update_engine_specific_ui()

        right_panel_main_layout.addWidget(settings_group)
        status_group = QGroupBox("转换状态与日志"); status_layout = QVBoxLayout(status_group)
        self.progress_bar = QProgressBar(); self.progress_bar.setTextVisible(True); self.progress_bar.setValue(0); self.progress_bar.setFormat("%p% - 当前状态")
        self.progress_bar.setToolTip("显示当前TTS转换任务的总体进度。")
        self.log_output = QPlainTextEdit(); self.log_output.setReadOnly(True); self.log_output.setPlaceholderText("TTS转换日志将显示在此..."); self.log_output.setFixedHeight(150) 
        self.log_output.setToolTip("显示TTS转换过程中的详细日志信息和错误报告。")
        status_layout.addWidget(self.progress_bar); status_layout.addWidget(self.log_output)
        right_panel_main_layout.addWidget(status_group); right_panel_main_layout.addStretch(1) 
        
        action_buttons_group = QGroupBox("操作"); action_buttons_layout = QVBoxLayout(action_buttons_group)
        self.start_tts_btn = QPushButton("开始TTS转换"); self.start_tts_btn.setObjectName("AccentButton"); self.start_tts_btn.setFixedHeight(50); self.start_tts_btn.setToolTip("使用当前编辑器列表和右侧的设置，开始批量转换任务。")
        self.stop_tts_btn = QPushButton("停止当前任务"); self.stop_tts_btn.setEnabled(False); self.stop_tts_btn.setFixedHeight(50); self.stop_tts_btn.setToolTip("请求中止正在进行的批量转换任务。")
        action_buttons_layout.addWidget(self.start_tts_btn); action_buttons_layout.addWidget(self.stop_tts_btn)
        right_panel_main_layout.addWidget(action_buttons_group)
        main_layout.addWidget(left_panel, 6); main_layout.addWidget(right_panel_container, 4)
        # [核心修复] 移除下面这行重复的调用

    def open_settings_dialog(self):
        dialog = SettingsDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.parent_window.request_tab_refresh(self)

    def _update_engine_specific_ui(self):
        """
        [v1.3 - Engine Switcher] 根据选择的TTS引擎更新UI。
        新增了可点击的引擎切换标签。
        """
        # --- (保存和清空UI的逻辑保持不变) ---
        existing_items = self.get_items_from_editor()
        while self.settings_form_layout.count():
            item = self.settings_form_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
            
        module_states = self.config.get("module_states", {}).get("tts_utility", {})
        self.current_engine = module_states.get("tts_engine", "gtts" if GTTS_AVAILABLE else "edge-tts")

        # --- [核心修改] 创建可点击的引擎切换标签 ---
        engine_display_map = {'gtts': 'gTTS', 'edge-tts': 'Edge-TTS'}
        engine_name = engine_display_map.get(self.current_engine, self.current_engine.upper())
        
        # 使用新的 ClickableLabel
        self.engine_switcher_label = ClickableLabel(f"<b>当前引擎: {engine_name}</b>")
        self.engine_switcher_label.setAlignment(Qt.AlignCenter)
        self.engine_switcher_label.setToolTip("点击切换到下一个可用的TTS引擎")
        self.engine_switcher_label.clicked.connect(self._toggle_tts_engine)
        
        # 创建一个水平布局来容纳图标和文本
        engine_header_layout = QHBoxLayout()
        self.engine_icon_label = QLabel() # 用于显示切换图标
        self.engine_icon_label.setPixmap(self.icon_manager.get_icon("swap").pixmap(QSize(16, 16)))
        
        engine_header_layout.addStretch()
        engine_header_layout.addWidget(self.engine_icon_label)
        engine_header_layout.addWidget(self.engine_switcher_label)
        engine_header_layout.addStretch()
        
        self.settings_form_layout.addRow(engine_header_layout)

        if self.current_engine == 'gtts' and GTTS_AVAILABLE:
            self.default_lang_combo = QComboBox()
            self.default_lang_combo.setToolTip("当列表中的语言列为空时，将使用此处的默认语言。")
            for name, code in LANGUAGE_MAP_TTS.items(): self.default_lang_combo.addItem(name, code)
            default_lang_val = module_states.get("gtts_default_lang", "en-us")
            idx = self.default_lang_combo.findData(default_lang_val); self.default_lang_combo.setCurrentIndex(idx if idx != -1 else 0)
            self.auto_detect_lang_switch = self.ToggleSwitch()
            self.auto_detect_lang_switch.setChecked(module_states.get("gtts_auto_detect", True))
            self.auto_detect_lang_switch.setToolTip("开启后，将尝试自动检测文本的语言（如中/日/韩），\n如果检测失败，则使用上面的默认语言。")
            self.slow_speed_switch = self.ToggleSwitch()
            self.slow_speed_switch.setChecked(module_states.get("gtts_slow", False))
            self.slow_speed_switch.setToolTip("开启后，将以较慢的语速生成语音，适合教学场景。")
            self.settings_form_layout.addRow("默认转换语言:", self.default_lang_combo)
            self.settings_form_layout.addRow("语言检测:", self.auto_detect_lang_switch)
            self.settings_form_layout.addRow("放慢语速:", self.slow_speed_switch)

        elif self.current_engine == 'edge-tts' and EDGE_TTS_AVAILABLE:
            self.edge_voice_combo = QComboBox()
            self.edge_voice_combo.setToolTip("选择一个特定的 Edge-TTS 语音模型。")
            for code, voice in EDGE_TTS_DEFAULT_VOICES.items():
                lang_name = next((name for name, c in LANGUAGE_MAP_TTS.items() if c == code), code)
                self.edge_voice_combo.addItem(f"{lang_name} - {voice}", voice)
            default_voice = module_states.get("edge_voice", "zh-CN-XiaoxiaoNeural")
            idx = self.edge_voice_combo.findData(default_voice)
            self.edge_voice_combo.setCurrentIndex(idx if idx != -1 else 0)
    
            self.edge_auto_detect_switch = self.ToggleSwitch()
            self.edge_auto_detect_switch.setChecked(module_states.get("edge_auto_detect", True))
            self.edge_auto_detect_switch.setToolTip("开启后，将自动检测文本语言并选择对应的默认语音。\n关闭后，将始终使用上方选择的语音。")
            self.edge_auto_detect_switch.toggled.connect(self.edge_voice_combo.setDisabled)
            self.edge_voice_combo.setDisabled(self.edge_auto_detect_switch.isChecked())
    
            self.settings_form_layout.addRow("选择语音:", self.edge_voice_combo)
            self.settings_form_layout.addRow("自动检测语音:", self.edge_auto_detect_switch)

        # --- 通用UI部分 ---
        self.output_to_flashcard_switch = self.ToggleSwitch()
        self.output_to_flashcard_switch.stateChanged.connect(self._update_output_ui_state)
        
        self.output_subdir_input = QLineEdit(f"tts_util_{datetime.now().strftime('%Y%m%d')}")
        self.output_subdir_input.setPlaceholderText("例如: my_project_tts")
        self.output_subdir_input.setToolTip("生成的音频文件将被保存在 audio_tts/ 下的这个子文件夹中。")
        
        self.open_output_dir_btn = QPushButton("打开")
        
        # [关键修复] 将此按钮的信号连接移到此处。
        # 这样做可以确保每当这个按钮被重新创建时（例如，在切换TTS引擎后），
        # 它的 `clicked` 信号都会被重新连接。否则，按钮在UI刷新后会失效。
        self.open_output_dir_btn.clicked.connect(self.open_target_output_directory)

        output_dir_layout = QHBoxLayout()
        output_dir_layout.addWidget(self.output_subdir_input, 1); output_dir_layout.addWidget(self.open_output_dir_btn)

        self.settings_form_layout.addRow("输出到速记卡模块:", self.output_to_flashcard_switch)
        self.settings_form_layout.addRow("自定义输出文件夹:", output_dir_layout)
        
        # 重新填充编辑器
        self.editor_table.setRowCount(0)
        if not existing_items:
            # [核心修复] 如果表格为空，不再调用 add_table_row()
            pass
        else:
            for item in existing_items:
                self.add_table_row(item['text'], item['lang'])
        
        # [核心新增] 在所有操作完成后，统一添加占位符行
        self._add_placeholder_row()


    def _toggle_tts_engine(self):
        """
        [v1.1 - Full Refresh] 切换到下一个可用的TTS引擎，保存设置，并请求页面完全刷新。
        """
        available_engines = []
        if GTTS_AVAILABLE:
            available_engines.append("gtts")
        if EDGE_TTS_AVAILABLE:
            available_engines.append("edge-tts")
        
        if len(available_engines) < 2:
            self.log_message("只有一个可用的TTS引擎，无法切换。")
            return

        try:
            current_index = available_engines.index(self.current_engine)
            next_index = (current_index + 1) % len(available_engines)
            new_engine = available_engines[next_index]
        except ValueError:
            new_engine = available_engines[0]

        # 更新内部状态
        self.current_engine = new_engine
        
        # 保存新的引擎选择到配置文件
        main_window = self.parent_window
        module_states = main_window.config.get("module_states", {}).get("tts_utility", {}).copy()
        module_states["tts_engine"] = new_engine
        main_window.update_and_save_module_state('tts_utility', module_states)
        
        # [核心修改] 请求主窗口对本模块进行一次彻底的刷新
        # 这将确保所有UI元素（包括编辑器表格的语言下拉框）都与新引擎同步
        self.parent_window.request_tab_refresh(self)

        # 刷新后的日志消息现在只在控制台打印，因为UI将被重建
        print(f"[TTS Utility] TTS engine switched to: {new_engine.upper()}. Refreshing module...")

    def _connect_signals(self):
        self.load_wordlist_btn.clicked.connect(self.load_wordlist_from_file)
        # [核心新增] 连接 cellClicked 信号
        self.editor_table.cellClicked.connect(self.on_cell_single_clicked)
        self.add_row_btn.clicked.connect(self.add_table_row)
        self.remove_row_btn.clicked.connect(self.remove_selected_table_row)
        self.clear_table_btn.clicked.connect(self.clear_editor_table)
        self.submit_edited_btn.clicked.connect(self.process_edited_list)
        self.start_tts_btn.clicked.connect(self.start_tts_processing)
        self.stop_tts_btn.clicked.connect(self.stop_tts_processing)
        
        # [关键修复] 从此处移除 open_output_dir_btn 的连接，因为它已移至 _update_engine_specific_ui 内部。
        # self.open_output_dir_btn.clicked.connect(self.open_target_output_directory) 
        
        # 此信号连接是在 _update_engine_specific_ui 中创建 switch 后才有效，
        # 但由于 _connect_signals 在 _init_ui 之后调用，所以时序是正确的。
        self.output_to_flashcard_switch.stateChanged.connect(self._update_output_ui_state)


    def update_icons(self):
        self.load_wordlist_btn.setIcon(self.icon_manager.get_icon("open_file"))
        self.add_row_btn.setIcon(self.icon_manager.get_icon("add_row"))
        self.remove_row_btn.setIcon(self.icon_manager.get_icon("remove_row"))
        self.clear_table_btn.setIcon(self.icon_manager.get_icon("delete")) 
        self.submit_edited_btn.setIcon(self.icon_manager.get_icon("submit_process"))
        
        # 检查 open_output_dir_btn 是否存在，因为它在 _update_engine_specific_ui 中创建
        if hasattr(self, 'open_output_dir_btn') and self.open_output_dir_btn:
            self.open_output_dir_btn.setIcon(self.icon_manager.get_icon("open_folder"))
            
        self.start_tts_btn.setIcon(self.icon_manager.get_icon("start_session"))
        self.stop_tts_btn.setIcon(self.icon_manager.get_icon("stop"))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                filepath = urls[0].toLocalFile().lower()
                if filepath.endswith('.json') or filepath.endswith('.fdeck'):
                    event.acceptProposedAction()

    def _update_output_ui_state(self):
        is_for_flashcard = self.output_to_flashcard_switch.isChecked()
        self.output_subdir_input.setEnabled(not is_for_flashcard)
        if is_for_flashcard:
            self.output_subdir_input.blockSignals(True)
            self.output_subdir_input.setText("")
            self.output_subdir_input.setPlaceholderText("将自动输出到卡组缓存目录")
            self.output_subdir_input.blockSignals(False)
        else:
            self.output_subdir_input.setPlaceholderText("例如: my_project_tts")
            if not self.output_subdir_input.text():
                if self.last_loaded_wordlist_name:
                    self.output_subdir_input.setText(self.last_loaded_wordlist_name)
                else:
                    self.output_subdir_input.setText(f"tts_util_{datetime.now().strftime('%Y%m%d')}")

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

    def on_tts_task_finished(self, report_data):
        # --- 步骤1: 通用UI状态恢复 ---
        self.start_tts_btn.setEnabled(True); self.submit_edited_btn.setEnabled(True); self.load_wordlist_btn.setEnabled(True)
        self.stop_tts_btn.setEnabled(False)
        if self.tts_thread and self.tts_thread.isRunning(): 
            self.tts_thread.quit(); self.tts_thread.wait()

        # --- 步骤2: 解析报告数据并生成摘要 ---
        if "error" in report_data: # 处理 worker 启动失败的情况
            summary_message = f"任务出错: {report_data['error']}"
            is_error = True
        else:
            success = report_data.get('success_count', 0)
            total = report_data.get('total_items', 0)
            was_stopped = report_data.get('was_stopped', False)
            is_error = (success != total) and not was_stopped

            if was_stopped:
                summary_message = f"任务被用户中断。已处理 {success}/{total} 个。"
            else:
                summary_message = f"任务完成！成功处理 {success}/{total} 个。"
            if not was_stopped and success < total:
                summary_message += f" 发生 {total - success} 个错误。"

        self.log_message(summary_message)
        self.progress_bar.setValue(100 if not is_error else self.progress_bar.value())
        self.progress_bar.setFormat("任务完成!" if not is_error else "任务出错!")
        self.parent_window.statusBar().showMessage(summary_message, 5000)

        # --- 步骤3: 根据用户设置决定如何报告 ---
        report_style = self.config.get("module_states", {}).get("tts_utility", {}).get("report_style", "simple")

        if report_style == "none":
            return # 无弹窗，直接结束

        # 检查是否可以提供跳转功能
        is_for_flashcard = self.output_to_flashcard_switch.isChecked()
        output_dir_name = self.output_subdir_input.text().strip()
        go_to_callback = None
        if not is_for_flashcard and not is_error and output_dir_name:
            go_to_callback = lambda: self.go_to_project_in_manager(output_dir_name)

        if report_style == "simple":
            report_box = QMessageBox(self)
            report_box.setWindowTitle("TTS 任务报告")
            report_box.setIcon(QMessageBox.Warning if is_error else QMessageBox.Information)
            report_box.setText(f"<b>TTS 转换任务已{'完成' if not was_stopped else '中断'}。</b>")
            report_box.setInformativeText(summary_message)
            
            if go_to_callback:
                go_to_btn = report_box.addButton("前往项目文件夹", QMessageBox.ActionRole)
                go_to_btn.clicked.connect(go_to_callback)
            
            report_box.addButton(QMessageBox.Ok)
            report_box.exec_()
            
        elif report_style == "detailed":
            # 只有在有详细结果时才显示详细报告
            if "results_list" in report_data and report_data["results_list"]:
                dialog = DetailedReportDialog(report_data, self, self.icon_manager, go_to_callback)
                dialog.exec_()

    def go_to_project_in_manager(self, project_name):
        """
        [新增] 导航到音频数据管理器并选中指定的项目文件夹。
        """
        # 1. 导航到音频管理器主标签
        target_page = self.parent_window._navigate_to_tab("资源管理", "音频数据管理器")
        if not target_page:
            QMessageBox.warning(self, "导航失败", "无法找到音频数据管理器模块。")
            return
            
        # 2. 在音频管理器中切换到“TTS工具语音”数据源
        source_name = "TTS 工具语音"
        source_index = target_page.source_combo.findText(source_name)
        if source_index == -1:
            QMessageBox.warning(self, "导航失败", f"在音频管理器中找不到 '{source_name}' 数据源。")
            return
        
        target_page.source_combo.setCurrentIndex(source_index)
        QApplication.processEvents() # 确保项目列表已刷新

        # 3. 在项目列表中找到并选中目标项目
        items = target_page.session_list_widget.findItems(project_name, Qt.MatchFixedString)
        if items:
            target_page.session_list_widget.setCurrentItem(items[0])
            # 确保选中项可见
            target_page.session_list_widget.scrollToItem(items[0], QAbstractItemView.PositionAtCenter)
        else:
            QMessageBox.information(self, "提示", f"在音频管理器中未找到项目 '{project_name}'，可能需要手动刷新。")

    def _add_placeholder_row(self):
        """[新增] 在表格末尾添加一个灰色的、可点击的“添加新行”占位符。"""
        current_rows = self.editor_table.rowCount()
        # 避免重复添加
        if current_rows > 0 and self.editor_table.item(current_rows - 1, 0) and \
           self.editor_table.item(current_rows - 1, 0).data(self.ADD_NEW_ROW_ROLE):
            return

        self.editor_table.insertRow(current_rows)
        add_item = QTableWidgetItem(" 点击此处添加新行...")
        add_item.setData(self.ADD_NEW_ROW_ROLE, True)
        add_item.setForeground(self.palette().color(QPalette.Disabled, QPalette.Text))
        add_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        add_item.setFlags(Qt.ItemIsEnabled)

        self.editor_table.setItem(current_rows, 0, add_item)
        self.editor_table.setSpan(current_rows, 0, 1, self.editor_table.columnCount())

    def _remove_placeholder_row(self):
        """[新增] 安全地移除“添加新行”的占位符行（如果存在）。"""
        last_row = self.editor_table.rowCount() - 1
        if last_row >= 0:
            item = self.editor_table.item(last_row, 0)
            if item and item.data(self.ADD_NEW_ROW_ROLE):
                self.editor_table.removeRow(last_row)

    def on_cell_single_clicked(self, row, column):
        """[新增] 当一个单元格被单击时，检查是否是占位符行。"""
        item = self.editor_table.item(row, 0)
        if item and item.data(self.ADD_NEW_ROW_ROLE):
            # 在占位符行的位置添加一个真正的新行
            self.add_table_row(at_row=row)

    def add_table_row(self, word="", lang_code="", at_row=None):
        """
        [v1.2 - Placeholder Aware] 在表格中添加一个新行。
        """
        # [核心修改] 在添加新行前，先移除占位符
        self._remove_placeholder_row()

        row_pos = at_row if at_row is not None else self.editor_table.rowCount()
        self.editor_table.insertRow(row_pos)
        self.editor_table.setItem(row_pos, 0, QTableWidgetItem(word))
        
        combo = QComboBox()
        combo.setIconSize(QSize(24, 18))
        
        language_map_to_use = LANGUAGE_MAP_TTS
        if self.current_engine == 'edge-tts':
            language_map_to_use = EDGE_TTS_LANGUAGE_MAP

        for name, code in language_map_to_use.items():
            icon_path = os.path.join(self.flags_path, f"{FLAG_CODE_MAP_TTS.get(code, 'auto')}.png")
            combo.addItem(QIcon(icon_path) if os.path.exists(icon_path) else QIcon(), name, code)
        
        idx = combo.findData(lang_code or "")
        combo.setCurrentIndex(idx if idx != -1 else 0)
        self.editor_table.setCellWidget(row_pos, 1, combo)
        
        # [核心修改] 在添加新行后，重新添加占位符
        self._add_placeholder_row()

        # 如果是通过点击占位符添加的，则自动开始编辑
        if at_row is not None:
            self.editor_table.setCurrentCell(at_row, 0)
            self.editor_table.editItem(self.editor_table.item(at_row, 0))
        else:
            self.editor_table.scrollToBottom()

    def remove_selected_table_row(self):
        rows = sorted(list(set(index.row() for index in self.editor_table.selectedIndexes())), reverse=True)
        if not rows: QMessageBox.information(self, "提示", "请先选择要删除的行。"); return
        for r in rows: self.editor_table.removeRow(r)

    def clear_editor_table(self):
        self.editor_table.setRowCount(0)
        # [核心修复] 不再调用 add_table_row()，而是直接添加占位符
        self._add_placeholder_row()

    def load_wordlist_from_file(self, filepath=None):
        if not filepath:
            dialog = WordlistSelectionDialog(self, self.STD_WORD_LIST_DIR, self.icon_manager, pin_handler=None)
            if dialog.exec_() == QDialog.Accepted and dialog.selected_file_relpath:
                filepath = os.path.join(self.STD_WORD_LIST_DIR, dialog.selected_file_relpath)
            else:
                return

        if not filepath: return

        self.current_wordlist_path = filepath
        self.loaded_file_label.setText(os.path.basename(filepath))
        self.log_message(f"已加载文件: {os.path.basename(filepath)}")
        
        try:
            self.editor_table.setRowCount(0)
            words_to_add = []
            file_format = ""
            
            if filepath.lower().endswith('.fdeck'):
                import zipfile
                with zipfile.ZipFile(filepath, 'r') as zf:
                    if 'manifest.json' not in zf.namelist(): raise ValueError(".fdeck 包内缺少 manifest.json 文件。")
                    with zf.open('manifest.json') as manifest_file: data = json.load(manifest_file)
                for card in data.get("cards", []): words_to_add.append({'text': card.get("id", ""), 'lang': ""})
                file_format = "fdeck"
            elif filepath.lower().endswith('.json'):
                with open(filepath, 'r', encoding='utf-8') as f: data = json.load(f)
                meta = data.get("meta", {}); json_format = meta.get("format")
                if json_format == "standard_wordlist":
                    for group in data.get("groups", []):
                        for item in group.get("items", []): words_to_add.append({'text': item.get("text", ""), 'lang': item.get("lang", "")})
                    file_format = "standard_wordlist"
                elif json_format == "visual_wordlist":
                    for item in data.get("items", []): words_to_add.append({'text': item.get("id", ""), 'lang': ''})
                    file_format = "visual_wordlist"
                else: raise ValueError("JSON文件格式未知或不受支持。")
            
            for item in words_to_add:
                if item.get('text'): self.add_table_row(item['text'], item['lang'])
            
            wordlist_name, _ = os.path.splitext(os.path.basename(filepath))
            self.last_loaded_wordlist_name = wordlist_name
            if not self.output_to_flashcard_switch.isChecked(): self.output_subdir_input.setText(wordlist_name)

            if file_format == "fdeck": self.output_to_flashcard_switch.setChecked(True)
            else: self.output_to_flashcard_switch.setChecked(False)
            
            self._update_output_ui_state()
            self.log_message(f"从 {os.path.basename(filepath)} 填充了 {len(words_to_add)} 个词条。")
        except Exception as e:
            QMessageBox.critical(self, "加载错误", f"加载文件失败: {e}"); self.loaded_file_label.setText("加载失败"); self.current_wordlist_path = None; self.last_loaded_wordlist_name = None

    def get_items_from_editor(self):
        items = []
        for r in range(self.editor_table.rowCount()):
            text_item = self.editor_table.item(r, 0)
            
            # --- 核心修复在这里 ---
            # 检查这一行是不是那个“添加新行”的占位符，如果是，就直接跳过
            if text_item and text_item.data(self.ADD_NEW_ROW_ROLE):
                continue
            
            text = text_item.text().strip() if text_item else ""
            lang_combo = self.editor_table.cellWidget(r, 1)
            lang_code = lang_combo.currentData() if lang_combo else ""
            
            # 确保只有非空文本行才被添加
            if text:
                items.append({'text': text, 'lang': lang_code})
        return items

    def process_edited_list(self):
        self.current_wordlist_path = None ; self.loaded_file_label.setText("<当前编辑列表>")
        self.start_tts_processing()

    def start_tts_processing(self):
        items_to_process = self.get_items_from_editor()
        if not items_to_process:
            QMessageBox.information(self, "无内容", "没有有效的词条进行TTS转换。"); return

        is_for_flashcard = self.output_to_flashcard_switch.isChecked()
        target_dir = ""

        if is_for_flashcard:
            if not self.current_wordlist_path or not self.current_wordlist_path.lower().endswith('.fdeck'):
                QMessageBox.warning(self, "模式错误", "“输出到速记卡”模式需要先加载一个 .fdeck 文件。"); return
            try:
                import zipfile, hashlib
                with zipfile.ZipFile(self.current_wordlist_path, 'r') as zf: manifest_data = json.load(zf.open('manifest.json'))
                deck_id = manifest_data.get("meta", {}).get("deck_id")
                if not deck_id: deck_id = hashlib.sha256(self.current_wordlist_path.encode('utf-8')).hexdigest()[:16]
                if "audio" in manifest_data.get("meta", {}).get("capabilities", []):
                    if QMessageBox.question(self, "警告", "该卡组似乎已包含音频文件。\n是否继续生成并覆盖现有音频？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.No: return
                cache_dir = os.path.join(self.base_path_module, "flashcards", "cache", deck_id)
                target_dir = os.path.join(cache_dir, "audio")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法解析 .fdeck 文件或确定缓存目录：\n{e}"); return
        elif self.current_wordlist_path:
            wordlist_name = os.path.splitext(os.path.basename(self.current_wordlist_path))[0]
            target_dir = os.path.join(self.AUDIO_TTS_DIR_ROOT, wordlist_name)
            self.output_subdir_input.setText(wordlist_name)
        else:
            subdir_name = self.output_subdir_input.text().strip()
            if not subdir_name: subdir_name = f"tts_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}"; self.output_subdir_input.setText(subdir_name)
            safe_subdir_name = re.sub(r'[\\/*?:"<>|]', "_", subdir_name)
            target_dir = os.path.join(self.AUDIO_TTS_DIR_ROOT, safe_subdir_name)
        
        if not os.path.exists(target_dir):
            try: os.makedirs(target_dir)
            except Exception as e: QMessageBox.critical(self, "创建目录失败", f"无法创建输出目录 '{target_dir}':\n{e}"); return

        source_desc = os.path.basename(self.current_wordlist_path) if self.current_wordlist_path else "<当前编辑列表>"
        self.log_message(f"开始TTS转换任务 ({source_desc})... 输出到: {target_dir}")
        self.progress_bar.setValue(0); self.progress_bar.setFormat("准备中... (0%)")
        self.start_tts_btn.setEnabled(False); self.submit_edited_btn.setEnabled(False); self.load_wordlist_btn.setEnabled(False); self.stop_tts_btn.setEnabled(True)
        self.stop_tts_event.clear()
        
        tts_settings = {'engine': self.current_engine}
        if self.current_engine == 'gtts':
            tts_settings.update({'default_lang': self.default_lang_combo.currentData(), 'auto_detect': self.auto_detect_lang_switch.isChecked(), 'slow': self.slow_speed_switch.isChecked()})
        elif self.current_engine == 'edge-tts':
            module_states = self.parent_window.config.get("module_states", {}).get("tts_utility", {})
            
            # [核心修改] 从档位索引转换为实际值
            rate_steps = [-100, -75, -50, -25, 0, 25, 50, 75, 100]
            volume_steps = [-100, -75, -50, -25, 0, 25, 50, 75, 100]
            pitch_steps = [-50, -38, -25, -12, 0, 12, 25, 38, 50]

            rate_val = rate_steps[module_states.get("edge_rate_step", 4)]
            volume_val = volume_steps[module_states.get("edge_volume_step", 4)]
            pitch_val = pitch_steps[module_states.get("edge_pitch_step", 4)]

            rate_str = f"{'+' if rate_val >= 0 else ''}{rate_val}%"
            volume_str = f"{'+' if volume_val >= 0 else ''}{volume_val}%"
            pitch_str = f"{'+' if pitch_val >= 0 else ''}{pitch_val}Hz"

            tts_settings.update({
                'voice': self.edge_voice_combo.currentData(), 
                'auto_detect': self.edge_auto_detect_switch.isChecked(),
                'rate': rate_str,
                'volume': volume_str,
                'pitch': pitch_str
            })
        
        self.tts_thread = QThread(); self.tts_worker = self.Worker(self._perform_tts_task, items_to_process, target_dir, tts_settings, self.stop_tts_event, is_for_flashcard)
        self.tts_worker.moveToThread(self.tts_thread); self.tts_worker.progress.connect(self.update_progress) 
        self.tts_worker.finished.connect(self.task_finished_signal.emit); self.tts_worker.error.connect(lambda e_msg: self.task_finished_signal.emit(f"TTS任务出错: {e_msg}"))
        self.tts_thread.started.connect(self.tts_worker.run); self.tts_worker.finished.connect(self.tts_thread.quit) 
        self.tts_thread.start()

    def stop_tts_processing(self):
        if self.tts_thread and self.tts_thread.isRunning():
            self.stop_tts_event.set(); self.log_message("已发送停止请求..."); self.stop_tts_btn.setEnabled(False) 

    def _perform_tts_task(self, worker_instance, items, target_dir, tts_settings, stop_event, is_for_flashcard):
        start_time = time.time()
        results_list = []
        success_count = 0
        total_items = len(items)
        engine = tts_settings.get('engine', 'gtts')
        
        worker_instance.progress.emit(0, "准备开始...") 

        # --- gTTS 逻辑分支 ---
        if engine == 'gtts':
            if not GTTS_AVAILABLE: # ... (错误处理逻辑不变)
                return {"results_list": [], "error": "gTTS 库未安装。"}
            for i, item_data in enumerate(items):
                # ... (文件名处理、进度更新等逻辑不变)
                if stop_event.is_set(): break
                text_to_speak_original = item_data['text']; lang_code = item_data['lang']
                text_to_speak_processed = text_to_speak_original.replace('_', ' ')
                if not lang_code: 
                    if tts_settings['auto_detect']: lang_code = self.detect_language(text_to_speak_processed) or tts_settings['default_lang']
                    else: lang_code = tts_settings['default_lang']
                if not lang_code: lang_code = "en-us" 
                
                # [核心修复] 使用更宽容的正则表达式来保留标点符号，同时移除真正的非法字符
                text_for_filename = text_to_speak_original if 'text_to_speak_original' in locals() else text_to_speak
                if is_for_flashcard:
                    safe_filename_base = text_for_filename
                else:
                    # 移除非法字符: \ / : * ? " < > |
                    temp_name = re.sub(r'[\\/*?:"<>|]', '', text_for_filename)
                    # 将空格替换为下划线
                    safe_filename_base = temp_name.strip().replace(' ', '_')
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
                
                success = False; error_message = ""
                for attempt in range(3):
                    if stop_event.is_set(): break
                    try:
                        tts = gTTS(text=text_to_speak_processed, lang=lang_code, slow=tts_settings['slow'])
                        tts.save(output_filepath)
                        success = True; break
                    except gTTSError as e:
                        error_message = f"网络错误 (尝试 {attempt+1}/3): {e}"
                        self.log_message_signal.emit(f"处理 '{text_to_speak_original}': {error_message}")
                        if attempt < 2: time.sleep(1.5)
                    except Exception as e:
                        error_message = f"未知错误: {type(e).__name__}"
                        self.log_message_signal.emit(f"处理 '{text_to_speak_original}': {error_message}"); break
                
                if success:
                    success_count += 1
                    results_list.append({'text': text_to_speak_original, 'status': 'success', 'error_message': None})
                else:
                    results_list.append({'text': text_to_speak_original, 'status': 'failure', 'error_message': error_message or "超时或未知错误"})
        
        # --- Edge-TTS 逻辑分支 ---
        elif engine == 'edge-tts':
            if not EDGE_TTS_AVAILABLE: # ... (错误处理逻辑不变)
                return {"results_list": [], "error": "edge-tts 库未安装。"}
            async def communicate_edge(text, voice, rate, volume, pitch, filepath):
                communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch)
                await communicate.save(filepath)

            rate = tts_settings.get('rate', '+0%')
            volume = tts_settings.get('volume', '+0%')
            pitch = tts_settings.get('pitch', '+0Hz')

            for i, item_data in enumerate(items):
                if stop_event.is_set(): break
                # ... (文件名处理、进度更新、语音选择等逻辑不变)
                text_to_speak = item_data['text']
                # [核心修复] 使用更宽容的正则表达式来保留标点符号，同时移除真正的非法字符
                text_for_filename = text_to_speak_original if 'text_to_speak_original' in locals() else text_to_speak
                if is_for_flashcard:
                    safe_filename_base = text_for_filename
                else:
                    # 移除非法字符: \ / : * ? " < > |
                    temp_name = re.sub(r'[\\/*?:"<>|]', '', text_for_filename)
                    # 将空格替换为下划线
                    safe_filename_base = temp_name.strip().replace(' ', '_')
                if not safe_filename_base: safe_filename_base = f"item_{i+1}"
                output_filepath = os.path.join(target_dir, f"{safe_filename_base}.mp3")
                
                final_voice = tts_settings['voice']
                if tts_settings.get('auto_detect', True):
                    detected_lang_code = detect_language_for_edge_tts(text_to_speak)
                    default_voice_for_lang = EDGE_TTS_DEFAULT_VOICES.get(detected_lang_code)
                    if default_voice_for_lang: final_voice = default_voice_for_lang
                
                progress_percent = int(((i + 1) / total_items) * 100)
                progress_text_format = f"处理中 ({i+1}/{total_items}): {text_to_speak[:20]}..."
                worker_instance.progress.emit(progress_percent, progress_text_format)
                
                try:
                    asyncio.run(communicate_edge(text_to_speak, final_voice, rate, volume, pitch, output_filepath))
                    success_count += 1
                    results_list.append({'text': text_to_speak, 'status': 'success', 'error_message': None})
                except Exception as e:
                    error_message = f"{type(e).__name__} - {e}"
                    self.log_message_signal.emit(f"Edge-TTS 错误处理 '{text_to_speak}': {error_message}")
                    results_list.append({'text': text_to_speak, 'status': 'failure', 'error_message': error_message})
        
        end_time = time.time()
        
        return {
            "start_time": start_time,
            "end_time": end_time,
            "total_items": total_items,
            "success_count": success_count,
            "failure_count": total_items - success_count,
            "was_stopped": stop_event.is_set(),
            "results_list": results_list
        }

    def _on_persistent_setting_changed(self, key, value):
        self.parent_window.update_and_save_module_state('tts_utility', key, value)

class SettingsDialog(QDialog):
    def __init__(self, parent_page):
        super().__init__(parent_page)
        self.parent_page = parent_page
        self.setWindowTitle("TTS 工具设置")
        self.setWindowIcon(self.parent_page.parent_window.windowIcon())
        self.setStyleSheet(self.parent_page.parent_window.styleSheet())
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)
        
        # --- 通用设置 ---
        general_group = QGroupBox("通用设置")
        general_layout = QFormLayout(general_group)
        
        self.report_style_combo = QComboBox()
        # [核心修改 1] 添加带图标的选项
        self.report_style_combo.addItem(self.parent_page.icon_manager.get_icon("hidden"), "无弹窗", "none")
        self.report_style_combo.addItem(self.parent_page.icon_manager.get_icon("popup_simple"), "简略弹窗", "simple") # 假设有这些图标
        self.report_style_combo.addItem(self.parent_page.icon_manager.get_icon("popup_detailed"), "详细弹窗", "detailed")
        self.report_style_combo.setToolTip("选择TTS任务完成后，如何进行结果汇报。")
        general_layout.addRow("完成报告样式:", self.report_style_combo)
        layout.addWidget(general_group)

        # --- 引擎设置 ---
        engine_group = QGroupBox("TTS 引擎设置")
        form_layout = QFormLayout(engine_group)
        self.engine_combo = QComboBox()
        # [核心修改 2] 为引擎添加图标
        if GTTS_AVAILABLE: 
            self.engine_combo.addItem(self.parent_page.icon_manager.get_icon("gtts_logo"), "gTTS (在线, 速度快)", "gtts") # 假设有 gtts_logo.svg
        if EDGE_TTS_AVAILABLE: 
            self.engine_combo.addItem(self.parent_page.icon_manager.get_icon("edge_logo"), "Edge-TTS (在线, 高质量)", "edge-tts") # 假设有 edge_logo.svg
        form_layout.addRow("选择默认引擎:", self.engine_combo)
        layout.addWidget(engine_group)

        # --- Edge-TTS 参数设置 ---
        self.edge_settings_group = QGroupBox("Edge-TTS 参数设置")
        edge_form_layout = QFormLayout(self.edge_settings_group)
        self.edge_rate_slider, self.edge_rate_label = self._create_stepped_slider([-100, -75, -50, -25, 0, 25, 50, 75, 100], "%")
        edge_form_layout.addRow("语速:", self._create_slider_layout(self.edge_rate_slider, self.edge_rate_label))
        self.edge_volume_slider, self.edge_volume_label = self._create_stepped_slider([-100, -75, -50, -25, 0, 25, 50, 75, 100], "%")
        edge_form_layout.addRow("音量:", self._create_slider_layout(self.edge_volume_slider, self.edge_volume_label))
        self.edge_pitch_slider, self.edge_pitch_label = self._create_stepped_slider([-50, -38, -25, -12, 0, 12, 25, 38, 50], "Hz")
        edge_form_layout.addRow("音调:", self._create_slider_layout(self.edge_pitch_slider, self.edge_pitch_label))
        layout.addWidget(self.edge_settings_group)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(self.button_box)

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.engine_combo.currentIndexChanged.connect(self._update_visibility)
        
        self.load_settings()
        self._update_visibility()

    # ... (所有 _create... 和 _update... 辅助方法保持不变) ...
    def _create_stepped_slider(self, steps, suffix):
        slider = QSlider(Qt.Horizontal); slider.setRange(0, len(steps) - 1)
        slider.setTickPosition(QSlider.TicksBelow); slider.setTickInterval(1); slider.setSingleStep(1)
        slider.steps = steps; slider.suffix = suffix
        label = QLabel()
        slider.valueChanged.connect(lambda value, s=slider, l=label: self._update_slider_label(s, l))
        return slider, label
    def _create_slider_layout(self, slider, label):
        hbox = QHBoxLayout(); hbox.addWidget(slider, 1); hbox.addWidget(label)
        hbox.setContentsMargins(0, 0, 0, 0); container_widget = QWidget(); container_widget.setLayout(hbox)
        return container_widget
    def _update_slider_label(self, slider, label):
        value = slider.steps[slider.value()]; label.setText(f"{'+' if value >= 0 else ''}{value}{slider.suffix}")
    def _update_visibility(self):
        is_edge_tts = self.engine_combo.currentData() == "edge-tts"
        self.edge_settings_group.setVisible(is_edge_tts)

    def load_settings(self):
        module_states = self.parent_page.config.get("module_states", {}).get("tts_utility", {})
        
        # [核心修改] 加载报告样式设置，默认值为 "simple"
        report_style = module_states.get("report_style", "simple")
        idx_report = self.report_style_combo.findData(report_style)
        if idx_report != -1: 
            self.report_style_combo.setCurrentIndex(idx_report)
        else: # 如果配置文件中的值无效，也回退到默认
            default_idx = self.report_style_combo.findData("simple")
            if default_idx != -1:
                self.report_style_combo.setCurrentIndex(default_idx)

        default_engine = "gtts" if GTTS_AVAILABLE else "edge-tts"
        current_engine = module_states.get("tts_engine", default_engine)
        idx = self.engine_combo.findData(current_engine)
        if idx != -1: self.engine_combo.setCurrentIndex(idx)
        self.edge_rate_slider.setValue(module_states.get("edge_rate_step", 4))
        self.edge_volume_slider.setValue(module_states.get("edge_volume_step", 4))
        self.edge_pitch_slider.setValue(module_states.get("edge_pitch_step", 4))
        self._update_slider_label(self.edge_rate_slider, self.edge_rate_label)
        self._update_slider_label(self.edge_volume_slider, self.edge_volume_label)
        self._update_slider_label(self.edge_pitch_slider, self.edge_pitch_label)

    def save_settings(self):
        main_window = self.parent_page.parent_window
        module_states = main_window.config.get("module_states", {}).get("tts_utility", {}).copy()
        
        if hasattr(self.parent_page, 'default_lang_combo'): module_states['gtts_default_lang'] = self.parent_page.default_lang_combo.currentData()
        if hasattr(self.parent_page, 'auto_detect_lang_switch'): module_states['gtts_auto_detect'] = self.parent_page.auto_detect_lang_switch.isChecked()
        if hasattr(self.parent_page, 'slow_speed_switch'): module_states['gtts_slow'] = self.parent_page.slow_speed_switch.isChecked()
        if hasattr(self.parent_page, 'edge_voice_combo'): module_states['edge_voice'] = self.parent_page.edge_voice_combo.currentData()
        if hasattr(self.parent_page, 'edge_auto_detect_switch'): module_states['edge_auto_detect'] = self.parent_page.edge_auto_detect_switch.isChecked()

        settings_to_save = {
            "report_style": self.report_style_combo.currentData(), # [核心修改] 保存报告样式
            "tts_engine": self.engine_combo.currentData(),
            "edge_rate_step": self.edge_rate_slider.value(),
            "edge_volume_step": self.edge_volume_slider.value(),
            "edge_pitch_step": self.edge_pitch_slider.value(),
        }
        module_states.update(settings_to_save)
        main_window.update_and_save_module_state('tts_utility', module_states)

    def accept(self):
        self.save_settings()
        super().accept()
class DetailedReportDialog(QDialog):
    """显示详细TTS任务报告的自定义对话框。"""
    def __init__(self, report_data, parent=None, icon_manager=None, go_to_callback=None):
        super().__init__(parent)
        self.report_data = report_data
        self.icon_manager = icon_manager
        self.go_to_callback = go_to_callback

        self.setWindowTitle("TTS 任务详细报告")
        self.setMinimumSize(600, 450)
        
        self._init_ui()
        self._populate_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
    
        self.results_list = QListWidget()
        self.results_list.setAlternatingRowColors(True)
    
        summary_group = QGroupBox("任务总结")
        # [核心修改] 使用垂直布局作为 group 的主布局
        summary_v_layout = QVBoxLayout(summary_group)
    
        # --- 创建第一行：统计数据 ---
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(15) # 增加各项之间的间距
    
        # 总计
        self.total_label = QLabel("总计: <b>N/A</b>")
        # 成功
        self.success_label = QLabel("成功: <b>N/A</b>")
        # 失败
        self.failed_label = QLabel("失败: <b>N/A</b>")
    
        stats_layout.addWidget(self.total_label)
        stats_layout.addWidget(self.success_label)
        stats_layout.addWidget(self.failed_label)
        stats_layout.addStretch() # 将所有项推到左侧
    
        # --- 创建第二行：总耗时 ---
        time_layout = QFormLayout()
        time_layout.setContentsMargins(0, 5, 0, 0) # 增加与上一行的间距
        self.time_label = QLabel()
        time_layout.addRow("总耗时:", self.time_label)

        # 将两行布局添加到 group 的主布局中
        summary_v_layout.addLayout(stats_layout)
        summary_v_layout.addLayout(time_layout)

        # --- 后续按钮布局保持不变 ---
        self.button_box = QDialogButtonBox()
        self.ok_button = self.button_box.addButton(QDialogButtonBox.Ok)

        if self.go_to_callback:
            self.go_to_btn = self.button_box.addButton("前往项目文件夹", QDialogButtonBox.ActionRole)
            self.go_to_btn.clicked.connect(self.go_to_callback)
            self.go_to_btn.clicked.connect(self.accept)

        self.ok_button.clicked.connect(self.accept)

        layout.addWidget(self.results_list)
        layout.addWidget(summary_group)
        layout.addWidget(self.button_box)
        
    def _populate_data(self):
        # 填充列表
        success_icon = self.icon_manager.get_icon("success") # 假设有 success.svg
        error_icon = self.icon_manager.get_icon("error")     # 假设有 error.svg

        for item in self.report_data.get('results_list', []):
            text = item.get('text', 'N/A')
            status = item.get('status', 'failure')
            
            list_item = QListWidgetItem(text)
            if status == 'success':
                list_item.setIcon(success_icon)
            else:
                list_item.setIcon(error_icon)
                error_msg = item.get('error_message', '未知错误')
                list_item.setToolTip(f"错误: {error_msg}")
            
            self.results_list.addItem(list_item)
            
        # 填充总结信息
        total = self.report_data.get('total_items', 0)
        success = self.report_data.get('success_count', 0)
        failed = self.report_data.get('failure_count', 0)
        start_time = self.report_data.get('start_time', 0)
        end_time = self.report_data.get('end_time', 0)
    
        # [核心修改] 更新合并后的一行式标签
        self.total_label.setText(f"总计: <b>{total}</b>")
        self.success_label.setText(f"成功: <b style='color: green;'>{success}</b>")
        self.failed_label.setText(f"失败: <b style='color: red;'>{failed}</b>")
        self.time_label.setText(f"<b>{end_time - start_time:.2f}</b> 秒")