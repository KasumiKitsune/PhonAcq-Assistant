# --- START OF FILE modules/flashcard_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "速记卡"
MODULE_DESCRIPTION = "使用图文、音频结合的方式进行学习和记忆，并自动记录学习进度。"
# 声明模块内容的推荐尺寸，用于“在新窗口中打开”功能
MODULE_CONTENT_PREFERRED_SIZE = (1250, 900) 

# --- 导入必要的库 ---
import os
import sys
import random
import threading
import json
import zipfile 
from datetime import datetime, timedelta
import shutil 
import hashlib # 用于为没有 deck_id 的 .fdeck 文件生成哈希ID

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QMessageBox, QComboBox, QFormLayout, QGroupBox, QRadioButton, QLineEdit,
                             QListWidgetItem, QSizePolicy, QShortcut, QScrollArea, QGridLayout, QButtonGroup, QFrame, QCheckBox, QSpacerItem, QStyle, QStyleOptionButton, QMenu) 
from PyQt5.QtCore import Qt, QTimer, QUrl, QSize, QRect
from PyQt5.QtGui import QPixmap, QImageReader, QIcon, QTextDocument, QColor, QFontMetrics, QKeySequence, QPainter, QDesktopServices
from custom_widgets_module import AnimatedListWidget
# 动态导入多媒体和模糊匹配库
try:
    import sounddevice as sd
    import soundfile as sf
    from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
    from thefuzz import process, fuzz 
    DEPENDENCIES_MISSING = False
except ImportError as e:
    print(f"CRITICAL: flashcard_module.py - Missing dependencies: {e}")
    DEPENDENCIES_MISSING = True
    MISSING_ERROR_MESSAGE = str(e)

# --- 模块的创建入口函数 ---
def create_page(parent_window, ToggleSwitchClass, ScalableImageLabelClass, BASE_PATH, GLOBAL_TTS_DIR, GLOBAL_RECORD_DIR, icon_manager):
    """
    Flashcard 模块的入口函数。
    负责检查依赖并初始化 FlashcardPage。
    """
    if DEPENDENCIES_MISSING:
        error_page = QWidget()
        layout = QVBoxLayout(error_page)
        label = QLabel(f"速记卡模块加载失败：\n缺少必要的依赖库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install sounddevice soundfile PyQt5.QtMultimedia thefuzz python-Levenshtein")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        return error_page
    
    # 定义模块内部的专属目录
    base_flashcard_dir = os.path.join(BASE_PATH, "flashcards")
    
    # 模块内部生成的媒体和进度目录
    tts_dir = os.path.join(base_flashcard_dir, "audio_tts")
    progress_dir = os.path.join(base_flashcard_dir, "progress")
    cache_dir = os.path.join(base_flashcard_dir, "cache") 

    for path in [base_flashcard_dir, tts_dir, progress_dir, cache_dir]: # 这里的 visual_wordlists 和 common_wordlists 不再需要单独创建，因为 populate_wordlists 会扫描
        os.makedirs(path, exist_ok=True)
    
    return FlashcardPage(parent_window, ToggleSwitchClass, ScalableImageLabelClass, 
                         base_flashcard_dir, tts_dir, progress_dir, cache_dir, 
                         GLOBAL_TTS_DIR, GLOBAL_RECORD_DIR, icon_manager)

class FlashcardPage(QWidget):
    def __init__(self, parent_window, ToggleSwitchClass, ScalableImageLabelClass, 
                 BASE_FLASHCARD_DIR, TTS_DIR, PROGRESS_DIR, CACHE_DIR, 
                 GLOBAL_TTS_DIR, GLOBAL_RECORD_DIR, icon_manager):
        super().__init__()
        self.parent_window = parent_window
        self.ToggleSwitch = ToggleSwitchClass
        self.ScalableImageLabel = ScalableImageLabelClass
        
        self.BASE_FLASHCARD_DIR = BASE_FLASHCARD_DIR 
        self.TTS_DIR = TTS_DIR 
        self.PROGRESS_DIR = PROGRESS_DIR 
        self.CACHE_DIR = CACHE_DIR 

        self.GLOBAL_TTS_DIR = GLOBAL_TTS_DIR 
        self.GLOBAL_RECORD_DIR = GLOBAL_RECORD_DIR 
        self.icon_manager = icon_manager 
        
        # --- 核心状态变量 ---
        self.session_active = False
        self.all_loaded_cards = [] 
        self.cards = [] 
        self.current_card_index = -1
        self.is_answer_shown = False
        self.current_wordlist_path = "" 
        self.current_wordlist_name_no_ext = "" 
        self.current_wordlist_type = "" 
        self.current_cache_dir = None 
        self.current_deck_capabilities = []
        self.progress_data = {} 
        self.session_config = {}
        self.wordlist_data_map = {}

        # --- 多媒体状态变量 ---
        self.player = QMediaPlayer()
        # [新增] 音频播放队列和例句模式状态
        self.playback_queue = []
        self.has_sentence_audio = False
        
        self.audio_mc_queue = []
        self.audio_mc_button_map = {}
        self.is_in_autoplay_sequence = False

        # --- 初始化 ---
        self.player.stateChanged.connect(self._on_player_state_changed)
        self._init_ui()
        self._connect_signals()
        self.update_icons() 
        self.populate_wordlists() 
        self._update_ui_for_selection()



    def _init_ui(self):
        """
        [v1.9 - 最终健壮美学版]
        - 精确采纳 v1.4 的 QScrollArea 技术，实现无视觉滚动条但具备滚动能力的右侧面板。
        - 融合 v1.7 的三栏布局（词表列表在左侧）。
        - 确保在任何屏幕缩放或字体大小下，UI 均不会被截断。
        """
        main_layout = QHBoxLayout(self)

        # ==============================================================================
        # 左侧面板：词表选择、会话列表与关键操作 (保持最新布局)
        # ==============================================================================
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setFixedWidth(280)

        left_layout.addWidget(QLabel("可用词表:"))
        self.wordlist_list = AnimatedListWidget()
        self.wordlist_list.setToolTip("从 'flashcards' 文件夹中选择一个卡组文件 (.fdeck 或 .json)。\n右键可查看更多操作。")
        self.wordlist_list.setContextMenuPolicy(Qt.CustomContextMenu)
        left_layout.addWidget(self.wordlist_list, 1)

        self.start_reset_btn = QPushButton("加载词表并开始学习")
        self.start_reset_btn.setObjectName("AccentButton")
        self.start_reset_btn.setFixedHeight(40)
        self.start_reset_btn.setToolTip("加载选中的词表和模式，开始一个新的学习会话。\n在会话开始后，此按钮将变为“结束学习会话”。")
        left_layout.addWidget(self.start_reset_btn)

        left_layout.addSpacing(10)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        left_layout.addWidget(line)
        left_layout.addSpacing(10)

        left_layout.addWidget(QLabel("会话卡片顺序:"))
        self.list_widget = AnimatedListWidget()
        self.list_widget.setToolTip("当前学习会话中的所有卡片列表。\n- 单击可跳转到指定卡片。\n- 已掌握的卡片会有绿色对勾标记。")
        left_layout.addWidget(self.list_widget, 2)

        self.mark_mastered_btn = QPushButton("标记/取消掌握")
        self.mark_mastered_btn.setToolTip("将当前卡片标记为“已掌握”或取消标记 (快捷键: Ctrl+G)。\n已掌握的卡片在“智能随机”模式下出现的频率会大大降低。")
        left_layout.addWidget(self.mark_mastered_btn)

        self.clear_progress_btn = QPushButton("清空学习记录")
        self.clear_progress_btn.setObjectName("ActionButton_Delete")
        self.clear_progress_btn.setToolTip("警告：将永久删除当前选中词表的所有学习记录（如掌握状态、复习次数等）。")
        left_layout.addWidget(self.clear_progress_btn)

        # ==============================================================================
        # 中间面板：卡片核心显示区 (保持最新布局)
        # ==============================================================================
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)

        self.card_question_area = self.ScalableImageLabel("请从左侧选择词表并加载")
        self.card_question_area.setObjectName("FlashcardQuestionArea")
        self.card_question_area.setToolTip("这里将显示卡片的图片提示物。")
        self.card_question_area.setStyleSheet("QLabel#FlashcardQuestionArea { font-size: 20pt; font-weight: bold; padding: 10px; }")

        self.card_question_text_label = QLabel("")
        self.card_question_text_label.setObjectName("FlashcardQuestionTextLabel")
        self.card_question_text_label.setAlignment(Qt.AlignCenter)
        self.card_question_text_label.setWordWrap(True)
        self.card_question_text_label.setToolTip("这里将显示卡片的文字提示物。")
        self.card_question_text_label.setStyleSheet("QLabel#FlashcardQuestionTextLabel { font-size: 16pt; padding: 10px; }")

        self.card_answer_area = self.ScalableImageLabel("")
        self.card_answer_area.setObjectName("FlashcardAnswerArea")
        self.card_answer_area.setAlignment(Qt.AlignCenter)
        self.card_answer_area.setWordWrap(True)
        self.card_answer_area.setToolTip("这里将显示卡片的答案。")
        self.card_answer_area.setStyleSheet("QLabel#FlashcardAnswerArea { font-size: 18pt; padding: 10px; }")

        self.multiple_choice_widget = QWidget()
        self.multiple_choice_layout = QGridLayout(self.multiple_choice_widget)
        self.multiple_choice_widget.hide()

        self.progress_label = QLabel("卡片: - / -")
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setToolTip("显示当前会话中卡片的学习进度。")

        self.answer_input = QLineEdit()
        self.answer_input.setPlaceholderText("在此输入答案...")
        self.answer_input.setToolTip("在此输入您认为正确的答案，然后按Enter键或点击“提交”按钮。")

        self.answer_submit_btn = QPushButton("提交答案")
        self.answer_submit_btn.setToolTip("提交您的答案进行检查。")

        self.answer_input_widget = QWidget()
        answer_input_layout = QHBoxLayout(self.answer_input_widget)
        answer_input_layout.setContentsMargins(0,0,0,0)
        answer_input_layout.addWidget(self.answer_input)
        answer_input_layout.addWidget(self.answer_submit_btn)
        self.answer_input_widget.hide()

        center_bottom_bar = QWidget()
        center_bottom_layout = QHBoxLayout(center_bottom_bar)
        self.prev_btn = QPushButton("上一个")
        self.prev_btn.setToolTip("显示上一张卡片 (快捷键: ← 左方向键)。")
        self.show_answer_btn = QPushButton("显示答案")
        self.show_answer_btn.setObjectName("AccentButton")
        self.show_answer_btn.setToolTip("显示或隐藏当前卡片的答案 (快捷键: 空格键)。")
        self.next_btn = QPushButton("下一个")
        self.next_btn.setToolTip("显示下一张卡片 (快捷键: → 右方向键)。")
        self.play_audio_btn = QPushButton("播放音频")
        self.play_audio_btn.setToolTip("播放当前卡片关联的音频 (快捷键: P)。")

        center_bottom_layout.addStretch()
        center_bottom_layout.addWidget(self.prev_btn)
        center_bottom_layout.addWidget(self.show_answer_btn)
        center_bottom_layout.addWidget(self.next_btn)
        center_bottom_layout.addWidget(self.play_audio_btn)
        center_bottom_layout.addStretch()

        center_layout.addWidget(self.card_question_area, 1)
        center_layout.addWidget(self.card_question_text_label)
        center_layout.addWidget(self.card_answer_area)
        center_layout.addWidget(self.multiple_choice_widget)
        center_layout.addWidget(self.answer_input_widget)
        center_layout.addWidget(self.progress_label)
        center_layout.addWidget(center_bottom_bar)

        # ==============================================================================
        # 右侧面板：[最终方案] 应用 v1.4 的 QScrollArea 技术
        # ==============================================================================
        right_scroll_area = QScrollArea()
        right_scroll_area.setFixedWidth(320)
        right_scroll_area.setWidgetResizable(True) # 关键：让内部控件自动填充宽度
        right_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff) # 关键：强制禁用横向滚动条
        right_scroll_area.setObjectName("FlashcardSettingsScrollArea")
        # 关键：通过样式表将纵向滚动条的宽度设为0，使其在视觉上消失
        right_scroll_area.setStyleSheet("""
            QScrollArea#FlashcardSettingsScrollArea {
                border: none;
            }
            QScrollArea#FlashcardSettingsScrollArea QScrollBar:vertical {
                width: 0px;
            }
        """)

        right_panel_content = QWidget() # 真正承载内容的Widget
        right_scroll_area.setWidget(right_panel_content)

        right_layout = QVBoxLayout(right_panel_content)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(15)

        # --- 右侧面板的所有 GroupBox 和控件 (保持不变) ---
        paradigm_group = QGroupBox("1. 学习范式")
        paradigm_group.setToolTip("选择学习的核心方式。")
        paradigm_layout = QVBoxLayout(paradigm_group)
        self.memory_radio = QRadioButton("记忆模式 (学习)")
        self.memory_radio.setToolTip("直接显示卡片的所有信息，用于学习和回顾。")
        self.test_radio = QRadioButton("考核模式 (自检)")
        self.test_radio.setToolTip("隐藏答案并进行测验，您可以自定义题目的构成和回答方式。")
        paradigm_layout.addWidget(self.memory_radio)
        paradigm_layout.addWidget(self.test_radio)
        self.memory_radio.setChecked(True)

        self.prompt_group = QGroupBox("2. 提示物 (构成题目)")
        self.prompt_group.setToolTip("在“考核模式”下，选择用哪些元素来构成题目。")
        prompt_layout = QVBoxLayout(self.prompt_group)
        self.prompt_text_check = QCheckBox("题目文字")
        self.prompt_text_check.setToolTip("使用卡片的文字作为提示。")
        self.prompt_text_check.setChecked(True)
        self.prompt_image_check = QCheckBox("图片")
        self.prompt_image_check.setToolTip("使用卡片的图片作为提示。")
        self.prompt_audio_check = QCheckBox("音频")
        self.prompt_audio_check.setToolTip("使用卡片的音频作为提示。")
        prompt_layout.addWidget(self.prompt_text_check)
        prompt_layout.addWidget(self.prompt_image_check)
        prompt_layout.addWidget(self.prompt_audio_check)

        self.test_type_group = QGroupBox("3. 考核类型")
        self.test_type_group.setToolTip("在“考核模式”下，选择回答问题的方式。")
        test_type_layout = QVBoxLayout(self.test_type_group)
        self.test_type_input_radio = QRadioButton("输入答案")
        self.test_type_input_radio.setToolTip("通过键盘输入文本答案进行考核。")
        self.test_type_mc_image_radio = QRadioButton("四选一 (图片)")
        self.test_type_mc_image_radio.setToolTip("从四个图片选项中选择正确的答案。")
        self.test_type_mc_audio_radio = QRadioButton("四选一 (音频)")
        self.test_type_mc_audio_radio.setToolTip("从四个音频选项中选择正确的答案。")
        self.test_type_mc_text_radio = QRadioButton("四选一 (文字)")
        self.test_type_mc_text_radio.setToolTip("从四个文本选项中选择正确的答案。")
        test_type_layout.addWidget(self.test_type_input_radio)
        test_type_layout.addWidget(self.test_type_mc_image_radio)
        test_type_layout.addWidget(self.test_type_mc_audio_radio)
        test_type_layout.addWidget(self.test_type_mc_text_radio)
        self.test_type_button_group = QButtonGroup(self)
        self.test_type_button_group.addButton(self.test_type_input_radio)
        self.test_type_button_group.addButton(self.test_type_mc_image_radio)
        self.test_type_button_group.addButton(self.test_type_mc_audio_radio)
        self.test_type_button_group.addButton(self.test_type_mc_text_radio)
        self.test_type_input_radio.setChecked(True)

        options_group = QGroupBox("4. 通用选项")
        options_group.setToolTip("适用于所有模式的通用学习设置。")
        options_layout = QVBoxLayout(options_group)
        module_states = self.parent_window.config.get("module_states", {}).get("flashcard", {})
        self.order_mode_group = QGroupBox("卡片顺序")
        self.order_mode_group.setToolTip("决定卡片在学习会话中的出现顺序。")
        order_layout = QVBoxLayout()
        self.smart_random_radio = QRadioButton("智能随机 (推荐)")
        self.smart_random_radio.setToolTip("优先展示未掌握、易错和到期应复习的卡片，是最高效的学习模式。")
        self.random_radio = QRadioButton("完全随机")
        self.random_radio.setToolTip("在所有卡片中（包括已掌握的）纯粹随机抽取。")
        self.sequential_radio = QRadioButton("按列表顺序")
        self.sequential_radio.setToolTip("严格按照词表文件中的原始顺序显示所有卡片。")
        saved_order_mode = module_states.get('order_mode', 'smart_random')
        if saved_order_mode == 'random': self.random_radio.setChecked(True)
        elif saved_order_mode == 'sequential': self.sequential_radio.setChecked(True)
        else: self.smart_random_radio.setChecked(True)
        order_layout.addWidget(self.smart_random_radio)
        order_layout.addWidget(self.random_radio)
        order_layout.addWidget(self.sequential_radio)
        self.order_mode_group.setLayout(order_layout)
        autoplay_layout = QHBoxLayout()
        autoplay_layout.addWidget(QLabel("自动播放音频:"))
        self.autoplay_audio_switch = self.ToggleSwitch()
        self.autoplay_audio_switch.setToolTip("开启后，在切换到新卡片时，会自动播放其关联的音频。")
        self.autoplay_audio_switch.setChecked(module_states.get('autoplay_audio', True))
        autoplay_layout.addWidget(self.autoplay_audio_switch)
        hide_list_layout = QHBoxLayout()
        hide_list_layout.addWidget(QLabel("隐藏项目列表:"))
        self.hide_list_switch = self.ToggleSwitch()
        self.hide_list_switch.setToolTip("开启后，开始学习时将隐藏左侧的卡片列表，以减少干扰，专注于当前卡片。")
        self.hide_list_switch.setChecked(module_states.get('hide_list', True))
        hide_list_layout.addWidget(self.hide_list_switch)
        auto_show_answer_layout = QHBoxLayout()
        auto_show_answer_layout.addWidget(QLabel("自动显示答案:"))
        self.auto_show_answer_switch = self.ToggleSwitch()
        self.auto_show_answer_switch.setToolTip("开启后，在“记忆模式”下切换到新卡片时，会自动显示答案，无需手动点击。")
        self.auto_show_answer_switch.setChecked(module_states.get('auto_show_answer', False))
        auto_show_answer_layout.addWidget(self.auto_show_answer_switch)
        # --- [新增] 例句播放开关 ---
        play_sentence_layout = QHBoxLayout()
        play_sentence_layout.addWidget(QLabel("播放例句音频:"))
        self.play_sentence_switch = self.ToggleSwitch()
        self.play_sentence_switch.setToolTip("开启后，在“记忆模式”下，播放完单词音频后将自动播放例句音频。")
        self.play_sentence_switch.setChecked(module_states.get('play_sentence', False))
        self.play_sentence_switch.setEnabled(False) # 默认禁用，直到加载了带例句的卡组
        play_sentence_layout.addWidget(self.play_sentence_switch)
        # --- 新增结束 ---
        
        options_layout.addWidget(self.order_mode_group)
        options_layout.addLayout(autoplay_layout)
        # [新增] 将例句开关添加到布局中
        options_layout.addLayout(play_sentence_layout)
        options_layout.addLayout(hide_list_layout)
        options_layout.addLayout(auto_show_answer_layout)
    
        right_layout.addWidget(paradigm_group)
        right_layout.addWidget(self.prompt_group)
        right_layout.addWidget(self.test_type_group)
        right_layout.addWidget(options_group)
        right_layout.addStretch(1)

        # --- 将左右中三栏添加到主布局 ---
        main_layout.addWidget(left_panel)
        main_layout.addWidget(center_panel, 1)
        main_layout.addWidget(right_scroll_area)


    def _connect_signals(self):
        """连接所有UI元素的信号到槽函数。"""
        # [修改] 连接新的 QListWidget 的信号
        self.wordlist_list.currentItemChanged.connect(self._update_ui_for_selection)
        self.wordlist_list.customContextMenuRequested.connect(self._show_wordlist_context_menu)
    
        # 连接顶级模式切换的信号
        self.memory_radio.toggled.connect(self._update_ui_for_selection)
        self.test_radio.toggled.connect(self._update_ui_for_selection)
    
        # 连接提示物复选框，确保至少有一个被选中
        self.prompt_text_check.clicked.connect(self._validate_prompt_selection)
        self.prompt_image_check.clicked.connect(self._validate_prompt_selection)
        self.prompt_audio_check.clicked.connect(self._validate_prompt_selection)
    
        # [关键修复] 将信号连接到新的、更智能的槽函数
        self.test_type_button_group.buttonToggled.connect(self._on_test_type_changed)
    
        self.start_reset_btn.clicked.connect(self.handle_start_reset)
        self.list_widget.currentRowChanged.connect(self.jump_to_card)
        self.show_answer_btn.clicked.connect(self.toggle_answer)
        self.play_audio_btn.clicked.connect(lambda: self.play_current_audio())
        self.prev_btn.clicked.connect(self.show_prev_card)
        self.next_btn.clicked.connect(self.show_next_card)
        self.mark_mastered_btn.clicked.connect(self.toggle_mastered_status)
        self.clear_progress_btn.clicked.connect(self.clear_current_progress)
        self.answer_submit_btn.clicked.connect(self.check_answer)
        self.answer_input.returnPressed.connect(self.check_answer)
    
        # 持久化设置的信号连接 (QRadioButton.toggled 发出 bool)
        self.smart_random_radio.toggled.connect(
            lambda checked: self._on_persistent_setting_changed('order_mode', 'smart_random') if checked else None
        )
        self.random_radio.toggled.connect(
            lambda checked: self._on_persistent_setting_changed('order_mode', 'random') if checked else None
        )
        self.sequential_radio.toggled.connect(
            lambda checked: self._on_persistent_setting_changed('order_mode', 'sequential') if checked else None
        )
    
        # 持久化设置的信号连接 (ToggleSwitch.stateChanged 发出 int，转换为 bool)
        self.autoplay_audio_switch.stateChanged.connect(
            lambda state: self._on_persistent_setting_changed('autoplay_audio', bool(state))
        )
        self.hide_list_switch.stateChanged.connect(
            lambda state: self._on_persistent_setting_changed('hide_list', bool(state))
        )
        self.auto_show_answer_switch.stateChanged.connect(
            lambda state: self._on_persistent_setting_changed('auto_show_answer', bool(state))
        )
        self.play_sentence_switch.stateChanged.connect(lambda state: self._on_persistent_setting_changed('play_sentence', bool(state)))
    
        # 快捷键设置
        QShortcut(QKeySequence(Qt.Key_Left), self, self.show_prev_card)
        QShortcut(QKeySequence(Qt.Key_Right), self, self.show_next_card)
        QShortcut(QKeySequence(Qt.Key_P), self, self.play_current_audio)
        QShortcut(QKeySequence(Qt.Key_Space), self, self.toggle_answer)
        QShortcut(QKeySequence("Ctrl+G"), self, self.toggle_mastered_status)

    def _on_test_type_changed(self, button, checked):
        """
        [新增] 当考核类型单选按钮被切换时调用的槽函数。
        它首先更新UI的启用状态，然后智能地预设“提示物”选项。
        """
        # 步骤 1: 无论如何，都先调用通用的UI更新函数，以确保所有控件的启用/禁用状态是最新的。
        self._update_ui_for_selection()

        # 步骤 2: 只有当一个按钮被 *选中* 时，才执行智能预设逻辑。
        if checked:
            # 暂时阻塞“提示物”复选框的信号，以防止在程序化地修改它们时触发不必要的事件。
            self.prompt_text_check.blockSignals(True)
            self.prompt_image_check.blockSignals(True)
            self.prompt_audio_check.blockSignals(True)

            # --- 根据被选中的考核类型，应用不同的预设 ---

            if button == self.test_type_mc_image_radio:
                # 考核方式是“四选一(图片)”，那么题目最可能是“文字”或“音频”。
                if self.prompt_text_check.isEnabled(): self.prompt_text_check.setChecked(True)
                if self.prompt_audio_check.isEnabled(): self.prompt_audio_check.setChecked(True)
                # 同时，取消勾选“图片”作为提示物，因为图片现在是答案选项。
                if self.prompt_image_check.isEnabled(): self.prompt_image_check.setChecked(False)

            elif button == self.test_type_mc_audio_radio:
                # 考核方式是“四选一(音频)”，那么题目最可能是“文字”或“图片”。
                if self.prompt_text_check.isEnabled(): self.prompt_text_check.setChecked(True)
                if self.prompt_image_check.isEnabled(): self.prompt_image_check.setChecked(True)
                # 取消勾选“音频”作为提示物。
                if self.prompt_audio_check.isEnabled(): self.prompt_audio_check.setChecked(False)

            elif button == self.test_type_mc_text_radio:
                # 考核方式是“四选一(文字)”，那么题目最可能是“图片”或“音频”。
                if self.prompt_image_check.isEnabled(): self.prompt_image_check.setChecked(True)
                if self.prompt_audio_check.isEnabled(): self.prompt_audio_check.setChecked(True)
                # 取消勾选“文字”作为提示物。
                if self.prompt_text_check.isEnabled(): self.prompt_text_check.setChecked(False)

            # 恢复所有“提示物”复选框的信号。
            self.prompt_text_check.blockSignals(False)
            self.prompt_image_check.blockSignals(False)
            self.prompt_audio_check.blockSignals(False)

            # 手动触发一次验证，以防智能预设导致所有提示物都被取消勾选（例如，当卡组能力非常有限时）。
            self._validate_prompt_selection()

    def _show_wordlist_context_menu(self, position):
        """
        [v1.1 - 主题感知版]
        在词表列表上显示一个完全遵循主题样式和动画的右键菜单。
        """
        item = self.wordlist_list.itemAt(position)
        if not item:
            return

        # 检查 AnimationManager 是否可用
        if not hasattr(self.parent_window, 'animation_manager'):
            # 简单回退，不做任何事
            return

        self.wordlist_list.setCurrentItem(item)
    
        menu = QMenu(self.wordlist_list)
        menu.setEnabled(not self.session_active)

        im = self.icon_manager # 此模块已有 icon_manager 的引用

        start_action = menu.addAction(im.get_icon("play"), "开始学习")
        menu.addSeparator()
        open_dir_action = menu.addAction(im.get_icon("show_in_explorer"), "打开所在目录")
        clear_progress_action = menu.addAction(im.get_icon("delete"), "清空学习记录")
    
        # 直接连接信号到槽函数
        start_action.triggered.connect(self.handle_start_reset)
        open_dir_action.triggered.connect(self._open_wordlist_directory)
        clear_progress_action.triggered.connect(self.clear_current_progress)

        # 将显示委托给 AnimationManager
        global_pos = self.wordlist_list.mapToGlobal(position)
        self.parent_window.animation_manager.animate_menu(menu, global_pos)

    def _open_wordlist_directory(self):
        """[新增] 打开当前选中词表所在的文件目录。"""
        user_data = self._get_current_wordlist_data()
        if user_data:
            _, full_path = user_data
            directory = os.path.dirname(full_path)
            if os.path.isdir(directory):
                QDesktopServices.openUrl(QUrl.fromLocalFile(directory))
            else:
                QMessageBox.warning(self, "错误", f"目录不存在: {directory}")

    def update_icons(self):
        """从 IconManager 获取并设置所有按钮的图标。"""
        if self.session_active:
            self.start_reset_btn.setIcon(self.icon_manager.get_icon("end_session"))
        else:
            self.start_reset_btn.setIcon(self.icon_manager.get_icon("start_session"))
        
        self.mark_mastered_btn.setIcon(self.icon_manager.get_icon("check"))
        self.prev_btn.setIcon(self.icon_manager.get_icon("prev"))
        self.show_answer_btn.setIcon(self.icon_manager.get_icon("show_answer"))
        self.next_btn.setIcon(self.icon_manager.get_icon("next"))
        self.play_audio_btn.setIcon(self.icon_manager.get_icon("play_audio"))
        self.clear_progress_btn.setIcon(self.icon_manager.get_icon("delete"))
        self.answer_submit_btn.setIcon(self.icon_manager.get_icon("submit"))

        # 刷新列表中的图标（主要是已掌握的对勾）
        if self.session_active:
            for i, card in enumerate(self.cards):
                card_id = card.get('id')
                is_mastered = False
                if card_id: 
                    is_mastered = self.progress_data.get(card_id, {}).get("mastered", False)
                self.update_list_item_icon(i, is_mastered)


    def populate_wordlists(self):
        """
        [v1.5 - AnimatedList版]
        - 递归扫描词表目录。
        - 构建显示文本列表和数据映射字典。
        - 使用 addItemsWithAnimation 动画化地填充列表。
        """
        self.wordlist_list.clear()
        self.wordlist_data_map.clear()
    
        base_flashcard_dir = self.BASE_FLASHCARD_DIR
        found_files = []
        # ... (扫描文件的 os.walk 逻辑保持不变) ...
        for root, _, files in os.walk(base_flashcard_dir):
            if any(internal_dir in root for internal_dir in ["progress", "cache", "audio_tts"]):
                continue
            for file in files:
                if file.endswith('.json') or file.endswith('.fdeck'):
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, base_flashcard_dir).replace("\\", "/")
                    found_files.append((relative_path, full_path))
        found_files.sort()

        display_texts = []
        for display_name, full_path in found_files:
            final_display_text = ""
            data_tuple = None
        
            if full_path.endswith('.json'):
                prefix = "[旧]" # 简洁前缀
                final_display_text = f"{prefix} {display_name}"
                data_tuple = ("json", full_path)
            elif full_path.endswith('.fdeck'):
                prefix = "[卡组]"
                final_display_text = f"{prefix} {display_name}"
                data_tuple = ("fdeck", full_path)
        
            if final_display_text:
                display_texts.append(final_display_text)
                self.wordlist_data_map[final_display_text] = data_tuple

        self.wordlist_list.addItemsWithAnimation(display_texts)

        # 填充后，选中第一项（如果存在）
        if self.wordlist_list.count() > 0:
            self.wordlist_list.setCurrentRow(0)
        else:
            self._update_ui_for_selection()

    def _get_current_wordlist_data(self):
        """[v1.1 - Map版] 通过映射字典获取当前选中词表的数据。"""
        current_item = self.wordlist_list.currentItem()
        if current_item:
            display_text = current_item.text()
            return self.wordlist_data_map.get(display_text)
        return None

    def _update_ui_for_selection(self, current_item=None, previous_item=None):
        """
        [v1.2 - QListWidget 版]
        核心UI更新函数。在选择新词表或切换学习范式时调用。
        它会读取卡组能力，并动态启用/禁用/显示/隐藏右侧栏的选项。
        """
        user_data = self._get_current_wordlist_data()
    
        # 卫兵语句：如果未选择有效词表，则禁用所有选项并立即返回
        if not user_data:
            self.prompt_group.setEnabled(False)
            self.test_type_group.setEnabled(False)
            self.memory_radio.setEnabled(False)
            self.test_radio.setEnabled(False)
            self.prompt_group.setVisible(False)
            self.test_type_group.setVisible(False)
            # 确保开始按钮也被禁用
            self.start_reset_btn.setEnabled(False)
            return

        # 如果有有效词表，则启用顶级模式选择和开始按钮
        self.start_reset_btn.setEnabled(True)
        self.memory_radio.setEnabled(True)
        self.test_radio.setEnabled(True)

        # 1. 确定当前卡组的能力 (用于启用/禁用选项)
        list_type, full_path = user_data
        self.current_deck_capabilities = self._infer_capabilities(list_type, full_path)
    
        # 2. 根据顶级模式（记忆/考核）显示/隐藏详细配置
        is_test_mode = self.test_radio.isChecked()
        self.prompt_group.setVisible(is_test_mode)
        self.test_type_group.setVisible(is_test_mode)
    
        # 3. 根据卡组能力，启用/禁用提示物复选框
        self.prompt_group.setEnabled(is_test_mode) # 只有在考核模式下才启用
        self.prompt_text_check.setEnabled("text" in self.current_deck_capabilities)
        self.prompt_image_check.setEnabled("image" in self.current_deck_capabilities)
        self.prompt_audio_check.setEnabled("audio" in self.current_deck_capabilities)
    
        if is_test_mode:
            # 确保至少有一个提示物被选中
            if not any([self.prompt_text_check.isChecked(), self.prompt_image_check.isChecked(), self.prompt_audio_check.isChecked()]):
                if "text" in self.current_deck_capabilities: self.prompt_text_check.setChecked(True)
                elif "image" in self.current_deck_capabilities: self.prompt_image_check.setChecked(True)
                elif "audio" in self.current_deck_capabilities: self.prompt_audio_check.setChecked(True)

        # 4. 根据能力和卡片数量，启用/禁用考核类型单选按钮
        can_mc = self.get_card_count(full_path) >= 4
        self.test_type_input_radio.setEnabled("text_input" in self.current_deck_capabilities)
        self.test_type_mc_image_radio.setEnabled("image" in self.current_deck_capabilities and can_mc)
        self.test_type_mc_audio_radio.setEnabled("audio" in self.current_deck_capabilities and can_mc)
        self.test_type_mc_text_radio.setEnabled("text_input" in self.current_deck_capabilities and can_mc)

        if is_test_mode:
            current_checked = self.test_type_button_group.checkedButton()
            if not current_checked or not current_checked.isEnabled():
                for rb in [self.test_type_input_radio, self.test_type_mc_text_radio, self.test_type_mc_image_radio, self.test_type_mc_audio_radio]:
                    if rb.isEnabled():
                        rb.setChecked(True)
                        break

    def handle_start_reset(self):
        """处理“开始/结束学习会话”按钮的点击事件。"""
        if not self.session_active:
            user_data = self._get_current_wordlist_data()
            if user_data:
                list_type, full_path = user_data
                if list_type == 'fdeck':
                    if not self._prepare_fdeck_cache(full_path):
                        return 
            self.start_session() 
        else:
            self.reset_session()
        
    def clear_current_progress(self):
        """清空当前选中词表的所有学习记录。"""
        user_data = self._get_current_wordlist_data()
        if not user_data:
            QMessageBox.warning(self, "操作无效", "请先从左侧列表选择一个词表。")
            return
        
        _, full_path = user_data
        wordlist_filename = os.path.basename(full_path)
    
        progress_filename_base = os.path.splitext(wordlist_filename)[0]
        progress_file_path = os.path.join(self.PROGRESS_DIR, f"{progress_filename_base}.json")

        reply = QMessageBox.question(self, "清空学习记录", f"您确定要清空词表 '{wordlist_filename}' 的所有学习记录吗？\n此操作不可撤销！", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    
        if reply == QMessageBox.Yes:
            if os.path.exists(progress_file_path):
                try:
                    os.remove(progress_file_path)
                    self.progress_data = {} 
                    QMessageBox.information(self, "成功", f"词表 '{wordlist_filename}' 的学习记录已清空。")
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"清空学习记录失败: {e}")
            else:
                QMessageBox.information(self, "提示", "该词表没有学习记录可清空。")
        
            if self.session_active:
                self.reset_session()
            
    def _infer_capabilities(self, list_type, full_path):
        """[新增] 推断或读取卡组的能力。"""
        if list_type == "fdeck":
            try:
                with zipfile.ZipFile(full_path, 'r') as zf:
                    with zf.open('manifest.json') as mf:
                        manifest = json.load(mf)
                        capabilities = manifest.get("meta", {}).get("capabilities", [])
                        # [核心修复 2.1] 自动推断 "text" 能力：如果卡片中存在 question 字段，就认为有文本能力
                        if "text" not in capabilities:
                            if any(card.get("question") for card in manifest.get("cards", [])):
                                capabilities.append("text")
                        # 自动推断 "text_input" 能力：如果卡片中存在 answer 字段，就认为有文本输入能力
                        if "text_input" not in capabilities:
                            if any(card.get("answer") for card in manifest.get("cards", [])):
                                capabilities.append("text_input")
                        
                        return capabilities
            except Exception as e:
                print(f"Error inferring capabilities from fdeck {full_path}: {e}")
                return []
        else: # 旧 .json 格式
            caps = ["text", "text_input"] 
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                if "items" in data: # 图文词表 (旧)
                    for item in data["items"]:
                        if item.get("image_path"):
                            caps.append("image")
                            break
                # 音频能力：旧格式默认有音频能力，但播放时在全局目录搜索
                caps.append("audio")

            except Exception as e:
                print(f"Error inferring capabilities from json {full_path}: {e}")
            return caps

    def get_card_count(self, full_path):
        """[新增] 快速获取卡组中的卡片数量，用于判断是否能进行四选一。"""
        count = 0 
        try:
            if full_path.endswith('.fdeck'):
                with zipfile.ZipFile(full_path, 'r') as zf:
                    with zf.open('manifest.json') as mf:
                        count = len(json.load(mf).get("cards", []))
            else: # .json
                 with open(full_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if "items" in data: count = len(data["items"])
                    elif "groups" in data: count = sum(len(g.get("items", [])) for g in data["groups"])
        except Exception as e:
            print(f"Error getting card count for {full_path}: {e}")
            return 0
        return count

    def _validate_prompt_selection(self):
        """[新增] 确保至少有一个提示物被选中。"""
        if not any([self.prompt_text_check.isChecked(), self.prompt_image_check.isChecked(), self.prompt_audio_check.isChecked()]):
            QMessageBox.warning(self, "选择无效", "至少需要选择一个提示物来构成题目。")
            sender = self.sender()
            if sender and sender.isEnabled():
                sender.setChecked(True)
            elif self.prompt_text_check.isEnabled():
                self.prompt_text_check.setChecked(True)
            elif self.prompt_image_check.isEnabled():
                self.prompt_image_check.setChecked(True)
            elif self.prompt_audio_check.isEnabled():
                self.prompt_audio_check.setChecked(True)


    def start_session(self):
        """开始一个新的学习会话。"""
        user_data = self._get_current_wordlist_data()
        if not user_data:
            QMessageBox.warning(self, "错误", "请先从左侧列表选择一个有效的词表文件。")
            return
    
        self.current_wordlist_type, wordlist_full_path = user_data
    
        self.session_config = {}
        if self.memory_radio.isChecked():
            self.session_config['paradigm'] = 'memory'
        else:
            self.session_config['paradigm'] = 'test'
            self.session_config['prompt'] = []
            if self.prompt_text_check.isChecked(): self.session_config['prompt'].append('text')
            if self.prompt_image_check.isChecked(): self.session_config['prompt'].append('image')
            if self.prompt_audio_check.isChecked(): self.session_config['prompt'].append('audio')
        
            checked_test_type_button = self.test_type_button_group.checkedButton()
            if checked_test_type_button:
                if checked_test_type_button == self.test_type_input_radio: self.session_config['test_type'] = 'input'
                elif checked_test_type_button == self.test_type_mc_image_radio: self.session_config['test_type'] = 'mc_image'
                elif checked_test_type_button == self.test_type_mc_audio_radio: self.session_config['test_type'] = 'mc_audio'
                elif checked_test_type_button == self.test_type_mc_text_radio: self.session_config['test_type'] = 'mc_text'
            else:
                QMessageBox.warning(self, "错误", "请选择一个考核类型。"); return

        try:
            self.load_and_adapt_data(wordlist_full_path)
            self.load_progress()
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"无法加载或解析词表文件:\n{e}")
            return
    
        if not self.all_loaded_cards:
            QMessageBox.information(self, "无内容", "词表中没有可用的学习项目。")
            return
    
        self.session_active = True
    
        self._generate_card_order()
        self.update_list_widget()
    
        self.start_reset_btn.setText("结束学习会话")
        self.update_icons() 
    
        # 禁用设置面板
        self.wordlist_list.setEnabled(False); self.memory_radio.setEnabled(False); self.test_radio.setEnabled(False)
        self.prompt_group.setEnabled(False); self.test_type_group.setEnabled(False) 
        self.order_mode_group.setEnabled(False); self.hide_list_switch.setEnabled(False)
        self.clear_progress_btn.setEnabled(False)

        # [新增] 根据卡组是否有例句音频来启用/禁用开关
        self.play_sentence_switch.setEnabled(self.has_sentence_audio)

        if self.hide_list_switch.isChecked(): self.list_widget.hide()
        else: self.list_widget.show()

        if self.cards:
            self.current_card_index = -1 
            self.list_widget.setCurrentRow(0) 
            self.prev_btn.setEnabled(True)
            self.next_btn.setEnabled(True)
            self.play_audio_btn.setEnabled("audio" in self.current_deck_capabilities) 
            self.mark_mastered_btn.setEnabled(True) 
            self.show_answer_btn.setEnabled(self.session_config['paradigm'] == 'memory' or self.session_config['test_type'] == 'input')
        else:
            self.card_question_area.set_pixmap(None)
            self.card_question_area.setText("所有卡片均已掌握并通过筛选！\n请尝试其他模式或重置进度。")
            self.progress_label.setText("太棒了！")
            self.multiple_choice_widget.hide()
            self.answer_input_widget.hide()
            self.play_audio_btn.setEnabled(False) 
            self.prev_btn.setEnabled(False) 
            self.next_btn.setEnabled(False)
            self.mark_mastered_btn.setEnabled(False) 
            self.show_answer_btn.setEnabled(False)
        self._set_tooltips_enabled(False)

    def reset_session(self):
        if self.session_active:
            self.save_progress(); self._cleanup_fdeck_cache()
        
        self.session_active = False; self.cards.clear(); self.all_loaded_cards.clear()
        self.list_widget.clear(); self.card_question_area.set_pixmap(None)
        self.card_question_area.setText("请从左侧选择词表并加载")
        self.card_question_text_label.setText(""); self.card_question_text_label.hide()
        self.card_answer_area.set_pixmap(None); self.card_answer_area.setText("")
        self.progress_label.setText("卡片: - / -"); self.progress_data.clear()
        self.session_config = {}; self.current_cache_dir = None
        
        # [新增] 重置例句音频状态
        self.has_sentence_audio = False
        self.play_sentence_switch.setEnabled(False)

        self.list_widget.show(); self.start_reset_btn.setText("加载词表并开始学习"); self.update_icons()
        
        # 启用设置面板
        self.wordlist_list.setEnabled(True); self.memory_radio.setEnabled(True); self.test_radio.setEnabled(True)
        self.prompt_group.setEnabled(True); self.test_type_group.setEnabled(True)
        self.order_mode_group.setEnabled(True); self.hide_list_switch.setEnabled(True)
        self.clear_progress_btn.setEnabled(True)
        
        self.multiple_choice_widget.hide(); self.answer_input_widget.hide()
        self.prev_btn.setEnabled(False); self.show_answer_btn.setEnabled(False)
        self.next_btn.setEnabled(False); self.play_audio_btn.setEnabled(False)
        self.mark_mastered_btn.setEnabled(False)
        self._update_ui_for_selection()
        self._set_tooltips_enabled(True)


    def _prepare_fdeck_cache(self, fdeck_path):
        """
        [新增] 准备 .fdeck 文件的缓存。如果需要，则解压媒体文件。
        解压到以 deck_id (或其哈希) 命名的子目录中，并检查文件修改时间以避免重复解压。
        """
        try:
            with zipfile.ZipFile(fdeck_path, 'r') as zf:
                if 'manifest.json' not in zf.namelist():
                    raise ValueError("卡组包内缺少 manifest.json 文件。")
                
                with zf.open('manifest.json') as manifest_file:
                    manifest_data = json.load(manifest_file)
                
                deck_id = manifest_data.get("meta", {}).get("deck_id")
                if not deck_id:
                    # 如果没有 deck_id，用文件路径的哈希作为 ID
                    print(f"Warning: .fdeck file '{os.path.basename(fdeck_path)}' missing deck_id. Using hash for cache.", file=sys.stderr)
                    deck_id = hashlib.sha256(fdeck_path.encode('utf-8')).hexdigest()[:16] 

            self.current_cache_dir = os.path.join(self.CACHE_DIR, deck_id)
            os.makedirs(self.current_cache_dir, exist_ok=True)
            
            fdeck_mtime = os.path.getmtime(fdeck_path)
            cache_mtime_file = os.path.join(self.current_cache_dir, '.mtime')
            
            should_extract = True
            if os.path.exists(cache_mtime_file):
                with open(cache_mtime_file, 'r') as f:
                    try:
                        cached_mtime = float(f.read())
                        if fdeck_mtime <= cached_mtime:
                            should_extract = False 
                    except ValueError: 
                        should_extract = True
            
            if should_extract:
                if os.path.exists(self.current_cache_dir) and os.path.isdir(self.current_cache_dir):
                    shutil.rmtree(self.current_cache_dir); os.makedirs(self.current_cache_dir) 
                with zipfile.ZipFile(fdeck_path, 'r') as zf:
                    # [修改] 确保 sentence 文件夹也被解压
                    for member in zf.namelist():
                        if member.startswith(('images/', 'audio/', 'sentence/', 'manifest.json')):
                            zf.extract(member, self.current_cache_dir)
                with open(cache_mtime_file, 'w') as f: f.write(str(fdeck_mtime))
            
            # [新增] 在准备好缓存后，检查是否存在 sentence 文件夹
            sentence_dir = os.path.join(self.current_cache_dir, "sentence")
            self.has_sentence_audio = os.path.isdir(sentence_dir)
            
            return True
        except Exception as e:
            QMessageBox.critical(self, "卡组错误", f"处理 .fdeck 文件失败:\n{e}"); return False

    def _set_tooltips_enabled(self, enabled):
        """
        [新增] 启用或禁用此模块中所有关键UI元素的工具提示。
        :param enabled: True to show tooltips, False to hide them.
        """
        # 定义一个包含所有需要管理工具提示的控件的列表
        widgets_with_tooltips = [
            self.wordlist_list, self.start_reset_btn, self.list_widget,
            self.mark_mastered_btn, self.clear_progress_btn,
            self.card_question_area, self.card_question_text_label,
            self.card_answer_area, self.progress_label, self.answer_input,
            self.answer_submit_btn, self.prev_btn, self.show_answer_btn,
            self.next_btn, self.play_audio_btn,
            # 右侧栏
            self.memory_radio, self.test_radio, self.prompt_text_check,
            self.prompt_image_check, self.prompt_audio_check,
            self.test_type_input_radio, self.test_type_mc_image_radio,
            self.test_type_mc_audio_radio, self.test_type_mc_text_radio,
            self.smart_random_radio, self.random_radio, self.sequential_radio,
            self.autoplay_audio_switch, self.play_sentence_switch,
            self.hide_list_switch, self.auto_show_answer_switch
        ]
        
        # 遍历列表，为每个控件设置工具提示
        for widget in widgets_with_tooltips:
            if enabled:
                # 恢复工具提示。我们从一个临时属性中读取原始提示，
                # 如果不存在，则保持为空，让控件自己处理。
                original_tooltip = getattr(widget, '_original_tooltip', '')
                widget.setToolTip(original_tooltip)
            else:
                # 隐藏工具提示。我们先保存原始提示，然后再将其设置为空字符串。
                # 这样可以确保在恢复时能够找到原始文本。
                setattr(widget, '_original_tooltip', widget.toolTip())
                widget.setToolTip('')


    def _cleanup_fdeck_cache(self):
        """
        [新增] 清理当前会话使用的 .fdeck 缓存。
        目前暂时不实际删除文件，只清空引用。
        可以根据需要实现更复杂的 LRU 或引用计数策略进行定期清理。
        """
        if self.current_cache_dir and os.path.exists(self.current_cache_dir) and os.path.isdir(self.current_cache_dir):
            try:
                pass 
            except Exception as e:
                print(f"Error cleaning up fdeck cache: {e}", file=sys.stderr)
        self.current_cache_dir = None 

    def load_and_adapt_data(self, full_path):
        """
        [重构] 根据文件类型（.json 或 .fdeck）加载并适配卡片数据。
        """
        self.all_loaded_cards.clear()
        self.current_wordlist_path = full_path

        if full_path.endswith('.fdeck'):
            self._load_fdeck_data(full_path)
            self.current_wordlist_type = "fdeck" 
        elif full_path.endswith('.json'):
            self._load_json_data(full_path)
            self.current_wordlist_type = "json" 
        else:
            raise ValueError(f"不支持的文件类型: {full_path}")

    def _load_json_data(self, json_full_path):
        """
        [新增] 从旧的 .json 格式词表加载数据。
        """
        filename = os.path.basename(json_full_path)
        self.current_wordlist_name_no_ext = os.path.splitext(filename)[0]
        
        try:
            with open(json_full_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            meta = data.get("meta", {})
            file_format = meta.get("format")

            is_visual_path = "visual_wordlists" in json_full_path 
            
            if is_visual_path and file_format == "visual_wordlist":
                items = data.get("items", [])
                for item in items:
                    self.all_loaded_cards.append({
                        'id': item.get('id', ''), 
                        'question': item.get('prompt_text', ''), 
                        'answer': item.get('id', ''), 
                        'hint': item.get('notes', ''), 
                        'image_path': item.get('image_path', ''), 
                        'text': item.get('prompt_text', ''), 
                        'notes': item.get('notes', ''), 
                        'correct_answer': item.get('id', '') 
                    })
            elif not is_visual_path and file_format == "standard_wordlist":
                groups = data.get("groups", [])
                for group in groups:
                    for item in group.get("items", []):
                        word = item.get("text")
                        if word:
                            self.all_loaded_cards.append({
                                'id': word, 
                                'question': word, 
                                'answer': word, 
                                'hint': item.get('note', ''), 
                                'text': word, 
                                'notes': item.get('note', ''), 
                                'correct_answer': word 
                            })
            else:
                raise ValueError(f"旧格式词表文件 '{filename}' 格式不正确或不受支持。")

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            raise Exception(f"加载或解析旧格式JSON文件 '{filename}' 失败: {e}")

    def _load_fdeck_data(self, fdeck_path):
        """
        [新增] 从 .fdeck 文件中加载卡片数据。
        """
        manifest_path_in_cache = os.path.join(self.current_cache_dir, 'manifest.json')
        
        if not os.path.exists(manifest_path_in_cache):
            raise FileNotFoundError("缓存目录中缺少 manifest.json 文件，缓存可能损坏。")

        with open(manifest_path_in_cache, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)

        self.current_wordlist_name_no_ext = os.path.splitext(os.path.basename(fdeck_path))[0]
        
        for card in manifest_data.get("cards", []):
            answer = card.get("answer")
            if not answer:
                answer = card.get("id")

            self.all_loaded_cards.append({
                'id': card.get('id'),
                'question': card.get('question'),
                'answer': answer, 
                'hint': card.get('hint', ''),
                'image_path': card.get('image_path', ''), 
                'correct_answer': answer 
            })

    def _generate_card_order(self):
        """根据选择的学习顺序模式生成卡片序列。"""
        source_cards = list(self.all_loaded_cards)
        now_ts = datetime.now().timestamp()

        if self.smart_random_radio.isChecked():
            def get_weight(card):
                card_id = card.get('id')
                progress = self.progress_data.get(card_id, {})
                if progress.get("mastered", False):
                    next_review_ts = progress.get("next_review_ts", now_ts)
                    return 50 + (now_ts - next_review_ts) / (3600*24) if now_ts >= next_review_ts else 0.1
                else:
                    views = progress.get("views", 0)
                    errors = progress.get("errors", 0)
                    return 100 + errors * 50 - views * 2
            
            weighted_cards = [(card, get_weight(card)) for card in source_cards]
            self.cards = [card for card, weight in weighted_cards if weight > 0.5]
            
            if len(self.cards) < 5 and len(source_cards) > len(self.cards):
                self.cards = source_cards
            
            self.cards.sort(key=lambda c: get_weight(c), reverse=True)

        elif self.random_radio.isChecked():
            random.shuffle(source_cards)
            self.cards = source_cards
        else: # sequential_radio.isChecked()
            self.cards = source_cards

        # 启用/禁用导航和标记按钮
        can_navigate = bool(self.cards)
        self.prev_btn.setEnabled(can_navigate)
        self.next_btn.setEnabled(can_navigate)
        self.mark_mastered_btn.setEnabled(can_navigate)
        self.show_answer_btn.setEnabled(can_navigate)
        
        # [核心修复] 移除对 show_answer_btn 的错误控制
        # self.show_answer_btn.setEnabled(can_navigate and self.session_config['paradigm'] == 'memory') <-- 删除这一行
        
        self.play_audio_btn.setEnabled(can_navigate and "audio" in self.current_deck_capabilities)


    def update_card_display(self):
        """
        [v1.6 - 最终修复版]
        根据当前会话配置和卡片索引更新UI显示。这是模块中核心的UI调度函数。
        """
        if not self.session_active or self.current_card_index < 0 or self.current_card_index >= len(self.cards):
            return
            
        card = self.cards[self.current_card_index]
        self.is_answer_shown = False # 切换卡片时，总是重置为答案隐藏状态
        
        # --- 1. 重置所有动态显示区域 ---
        self._stop_autoplay_sequence() # 停止任何可能正在进行的播放或自动播放
        
        # 清空并隐藏所有问答相关的UI元素
        self.card_question_area.hide()
        self.card_question_area.set_pixmap(None)
        
        self.card_question_text_label.hide()
        self.card_question_text_label.setText("")
        
        self.card_answer_area.hide()
        self.card_answer_area.set_pixmap(None)
        self.card_answer_area.setText("")

        self.answer_input_widget.hide()
        self.multiple_choice_widget.hide()
        self._clear_multiple_choice_options() # 确保清除旧的四选一按钮

        # --- 2. 根据学习范式决定显示逻辑 ---
        if self.session_config.get('paradigm') == 'memory':
            # --- 记忆模式 ---
            # 在记忆模式下，答案按钮总是可见的，并重置其文本
            self.show_answer_btn.show()
            self.show_answer_btn.setText("显示答案")

            # a. 显示题目文字和图片
            question_text = card.get('question', '')
            if question_text:
                self.card_question_text_label.setText(question_text)
                self.card_question_text_label.show()
            
            image_path = card.get('image_path', '')
            if image_path and "image" in self.current_deck_capabilities:
                self.display_content(self.card_question_area, image_path)
                self.card_question_area.show()
            else:
                # 如果没有图片，可以显示一个占位符，但仅在没有文字提示时
                if not self.card_question_text_label.text():
                    self.card_question_area.setText("...")
                    self.card_question_area.show()

            # b. 根据“自动显示答案”开关决定答案区域的初始状态
            if self.auto_show_answer_switch.isChecked():
                # 如果开启了自动显示，则立即调用 toggle_answer 来显示答案
                QTimer.singleShot(0, self.toggle_answer)
            else:
                # 否则，确保答案区域是隐藏的
                self.card_answer_area.hide()

            # c. 自动播放音频
            if self.autoplay_audio_switch.isChecked():
                self.play_current_audio()

        else: # --- 考核模式 ---
            # 在考核模式下，答案按钮总是隐藏的
            self.show_answer_btn.hide()
            
            # 根据 prompt 组合题目
            if 'text' in self.session_config.get('prompt', []):
                question_text = card.get('question', '')
                if question_text:
                    self.card_question_text_label.setText(question_text)
                    self.card_question_text_label.show()
            
            if 'image' in self.session_config.get('prompt', []) and card.get('image_path'):
                self.display_content(self.card_question_area, card.get('image_path'))
                self.card_question_area.show()
            
            if 'audio' in self.session_config.get('prompt', []):
                self.play_current_audio()

            # 根据 test_type 准备回答区域
            test_type = self.session_config.get('test_type')
            if test_type == 'input':
                self.answer_input_widget.show()
                self.answer_input.clear()
                self.answer_input.setFocus()
            elif test_type in ['mc_image', 'mc_audio', 'mc_text']:
                self.multiple_choice_widget.show()
                self._prepare_multiple_choice_options(card, test_type)
                
                # 如果是音频四选一，则启动自动播放序列
                if test_type == 'mc_audio':
                    self.audio_mc_queue = [btn.card_id for btn in self.mc_buttons]
                    self.audio_mc_button_map = {btn.card_id: btn.play_button for btn in self.mc_buttons}
                    self.is_in_autoplay_sequence = True
                    QTimer.singleShot(200, self._play_next_in_mc_queue)
            
        # --- 3. 更新通用UI元素 ---
        self.progress_label.setText(f"卡片: {self.current_card_index + 1} / {len(self.cards)}")
        self.update_progress_on_view(card.get('id'))
        
    def _prepare_multiple_choice_options(self, current_card, test_type):
        """[vFinal] 为四选一模式准备选项按钮。"""
        self._clear_multiple_choice_options() 

        correct_option_data = None
        distractor_pool_key = None 
        widget_factory_func = None 

        if test_type == 'mc_image':
            correct_option_data = current_card.get('image_path')
            distractor_pool_key = 'image_path'
            widget_factory_func = self._create_image_mc_label
        elif test_type == 'mc_audio':
            correct_option_data = current_card.get('id') 
            distractor_pool_key = 'id'
            widget_factory_func = self._create_audio_mc_widget 
        elif test_type == 'mc_text':
            correct_option_data = current_card.get('answer')
            distractor_pool_key = 'answer'
            widget_factory_func = self._create_text_mc_button

        if not correct_option_data:
            self.card_question_area.setText("此卡片缺少必要的多选数据，请联系制作者。")
            self.multiple_choice_widget.hide()
            return
            
        distractors = self._get_distractors(current_card, distractor_pool_key, num_distractors=3)
        options_data = [(correct_option_data, True)] + [(d, False) for d in distractors]
        random.shuffle(options_data)

        self.mc_buttons = [] 
        for i, (option_data, is_correct) in enumerate(options_data):
            display_data = option_data
            if test_type == 'mc_text' and isinstance(display_data, str):
                display_data = display_data.replace("||", ", ")

            widget = widget_factory_func(display_data)
            
            # [关键修复] 在设置 tooltip 之前，检查会话是否处于活动状态
            if not self.session_active:
                if isinstance(widget, QLabel): # 图片模式
                    widget.setToolTip(f"选择此项: {str(display_data)[:50]}...")
                elif hasattr(widget, 'select_button'): # 音频复合小部件
                    widget.setToolTip(f"选择音频: {option_data}")
                # 对于文字按钮 (QPushButton)，其 tooltip 已在 _create_text_mc_button 中设置

            if isinstance(widget, QLabel):
                widget.setMinimumSize(240, 180)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                widget.setFrameShape(QFrame.Box)
                widget.setFrameShadow(QFrame.Raised)
                widget.mousePressEvent = lambda event, data=option_data, correct=is_correct: self._handle_mc_click(data, correct)
                widget.setCursor(Qt.PointingHandCursor) 
                self.mc_buttons.append(widget)
            elif isinstance(widget, QPushButton):
                widget.clicked.connect(lambda checked, data=option_data, correct=is_correct: self._handle_mc_click(data, correct))
                self.mc_buttons.append(widget)
            elif hasattr(widget, 'select_button'):
                widget.select_button.clicked.connect(lambda checked, data=option_data, correct=is_correct: self._handle_mc_click(data, correct))
                self.mc_buttons.append(widget)

            self.multiple_choice_layout.addWidget(widget, i // 2, i % 2)

    def _create_text_mc_button(self, text):
        """
        [v1.2 - 长文本处理版] 
        为四选一文字模式创建 QPushButton。
        - 优雅地截断过长的文本。
        - 将完整文本放入 ToolTip。
        - 优化尺寸策略以防止布局被破坏。
        """
        btn = QPushButton()
        
        # 完整的原始文本总是用于 ToolTip
        full_text = str(text)
        btn.setToolTip(full_text)

        # 文本截断逻辑
        MAX_CHARS_DISPLAY = 40 # 可以根据需要调整这个阈值
        if len(full_text) > MAX_CHARS_DISPLAY:
            display_text = full_text[:MAX_CHARS_DISPLAY] + "..."
        else:
            display_text = full_text
        
        btn.setText(display_text)
        
        # 尺寸策略优化
        btn.setMinimumHeight(50) # 设置一个稍大的最小高度，以容纳两行左右的文本
        # 允许水平扩展，但垂直高度是固定的或有上限的，防止破坏布局
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed) 

        return btn

    def _create_image_mc_label(self, image_path):
        """为四选一图片模式创建 ScalableImageLabel。"""
        label = self.ScalableImageLabel()
        full_path = ""
        if self.current_wordlist_type == 'fdeck':
            if self.current_cache_dir:
                full_path = os.path.join(self.current_cache_dir, image_path)
        elif self.current_wordlist_type == 'json':
            base_dir = os.path.dirname(self.current_wordlist_path)
            full_path = os.path.join(base_dir, image_path)
            
        if full_path and os.path.exists(full_path):
            pixmap = QPixmap(full_path)
            if not pixmap.isNull():
                label.set_pixmap(pixmap)
            else:
                label.setText("图片加载失败")
        else:
            label.setText("图片未找到")
        return label

    def _play_next_in_mc_queue(self):
        """[新增] 播放队列中的下一个音频。"""
        self._unhighlight_all_mc_buttons() # 清除上一个高亮

        if not self.audio_mc_queue or not self.is_in_autoplay_sequence:
            self.is_in_autoplay_sequence = False # 播放完毕或被中断，关闭标志
            return

        card_id = self.audio_mc_queue.pop(0) # 从队列头部取出一个ID
        button_to_highlight = self.audio_mc_button_map.get(card_id)
        
        if button_to_highlight:
            self._highlight_mc_button(button_to_highlight)

        self.play_current_audio(force_card_id=card_id)

    def _on_player_state_changed(self, state):
        """当播放器状态改变时调用，用于串联播放。"""
        # --- 逻辑1: 处理四选一音频的自动播放队列 ---
        if state == QMediaPlayer.StoppedState and self.is_in_autoplay_sequence:
            # 稍作延迟后播放下一个，给用户反应时间
            QTimer.singleShot(300, self._play_next_in_mc_queue)
            return # 处理完毕，退出

        # --- [新增] 逻辑2: 处理单词->例句的播放队列 ---
        if state == QMediaPlayer.StoppedState and self.playback_queue:
            # 如果队列中还有待播放项（即例句）
            # 延迟1秒后，播放队列中的下一个项目
            QTimer.singleShot(100, self._play_next_in_queue)

    def _find_audio_path(self, card_id, audio_type='word'):
        """
        [新增] 在缓存目录中查找指定类型的音频文件。
        :param card_id: 卡片的唯一ID。
        :param audio_type: 'word' 或 'sentence'。
        :return: 找到的音频文件完整路径，或 None。
        """
        if not self.current_cache_dir or not card_id:
            return None
            
        # 根据类型确定要搜索的子目录
        subdir = "audio" if audio_type == 'word' else "sentence"
        search_dir = os.path.join(self.current_cache_dir, subdir)

        if not os.path.isdir(search_dir):
            return None

        # 遍历常用音频格式
        common_audio_exts = ['.wav', '.mp3', '.flac', '.ogg']
        for ext in common_audio_exts:
            path_to_check = os.path.join(search_dir, f"{card_id}{ext}")
            if os.path.exists(path_to_check):
                return path_to_check
        return None

    def _play_next_in_queue(self):
        """[新增] 播放 self.playback_queue 队列中的下一个音频。"""
        if self.playback_queue:
            filepath = self.playback_queue.pop(0) # 从队列头部取出一个路径
            if filepath and os.path.exists(filepath):
                self.player.setMedia(QMediaContent(QUrl.fromLocalFile(filepath)))
                self.player.play()

    def _stop_autoplay_sequence(self):
        """[新增] 立即停止自动播放序列，通常由用户手动操作触发。"""
        self.is_in_autoplay_sequence = False
        self.audio_mc_queue.clear()
        self.player.stop()
        self._unhighlight_all_mc_buttons()

    def _highlight_mc_button(self, button):
        """[新增] 高亮指定的按钮。"""
        if button:
            button.setProperty("playing", True)
            # 刷新样式
            button.style().unpolish(button)
            button.style().polish(button)

    def _unhighlight_all_mc_buttons(self):
        """[新增] 取消所有音频选项按钮的高亮。"""
        for btn in self.audio_mc_button_map.values():
            if btn:
                btn.setProperty("playing", False)
                # 刷新样式
                btn.style().unpolish(btn)
                btn.style().polish(btn)

    def _create_audio_mc_widget(self, card_id):
        """
        [v1.5 - 动态高亮版] 
        """
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignCenter)

        select_btn = QPushButton()
        select_btn.setIcon(self.icon_manager.get_icon("show_answer"))
        select_btn.setToolTip(f"选择此项作为答案")
        select_btn.setObjectName("AccentButton")

        # [核心修改] 创建一个自定义的 Button 类，以便重写 paintEvent
        class HoverButton(QPushButton):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._is_playing_highlight = False

            def setPlayingHighlight(self, playing):
                if self._is_playing_highlight != playing:
                    self._is_playing_highlight = playing
                    self.update() # 强制重绘

            def paintEvent(self, event):
                if self._is_playing_highlight:
                    # 如果需要高亮，则模拟悬停状态进行绘制
                    option = QStyleOptionButton()
                    self.initStyleOption(option)
                    option.state |= QStyle.State_MouseOver # 添加悬停状态标志
                    painter = QPainter(self)
                    self.style().drawControl(QStyle.CE_PushButton, option, painter, self)
                else:
                    # 否则，正常绘制
                    super().paintEvent(event)

        play_btn = HoverButton(f"播放音频") # 使用我们新的 HoverButton
        play_btn.setToolTip(f"播放音频")
        play_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        play_btn.clicked.connect(lambda: (self._stop_autoplay_sequence(), self._play_mc_audio(card_id)))

        layout.addWidget(select_btn)
        layout.addWidget(play_btn)

        widget.select_button = select_btn
        widget.play_button = play_btn
        widget.card_id = card_id
        return widget

    # 替换旧的 _highlight_mc_button 和 _unhighlight_all_mc_buttons 方法
    def _highlight_mc_button(self, button):
        """[重构] 高亮指定的按钮，通过调用其自定义方法。"""
        if button and hasattr(button, 'setPlayingHighlight'):
            button.setPlayingHighlight(True)

    def _unhighlight_all_mc_buttons(self):
        """[重构] 取消所有音频选项按钮的高亮。"""
        for btn in self.audio_mc_button_map.values():
            if btn and hasattr(btn, 'setPlayingHighlight'):
                btn.setPlayingHighlight(False)
        
    def _play_mc_audio(self, card_id):
        """播放四选一音频选项的音频。"""
        self.play_current_audio(force_card_id=card_id)

    def _handle_mc_click(self, selected_data, is_correct):
        """[重构] 处理四选一选项的点击。"""
        if is_correct:
            self._disable_mc_buttons() 
            is_mastered, next_review = self.update_progress_on_correct(self.cards[self.current_card_index].get('id'))
            self.show_feedback("正确!", f"太棒了！下次复习: {next_review.strftime('%Y-%m-%d')}", auto_close_delay=1200)
            QTimer.singleShot(500, self.show_next_card) 
        else:
            self.update_progress_on_wrong(self.cards[self.current_card_index].get('id'))
            self.show_feedback("错误", "请再试一次。")
            # 选错时，不禁用按钮，允许用户重试
            # [可选] 可以在此添加视觉反馈，比如让选错的按钮闪烁红色或改变边框颜色

    def _disable_mc_buttons(self):
        """[修改] 禁用所有四选一按钮，兼容新的音频复合小部件。"""
        for btn_or_widget in self.mc_buttons:
            if hasattr(btn_or_widget, 'select_button'): # 是音频复合小部件
                btn_or_widget.select_button.setEnabled(False)
            else: # 是 QLabel
                btn_or_widget.setEnabled(False)

    def _clear_multiple_choice_options(self):
        """清除四选一控件中的所有按钮/标签。"""
        for i in reversed(range(self.multiple_choice_layout.count())): 
            widget = self.multiple_choice_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        self.mc_buttons = [] 

    def _get_distractors(self, current_card, key, num_distractors=3):
        """
        [v1.1 - 去重版] 
        从除当前卡片外的所有卡片中随机选择独一无二的干扰项。
        """
        # 1. 获取当前卡片的正确答案/值
        correct_value = current_card.get(key)
        if correct_value is None:
            return [] # 如果当前卡片没有有效值，无法生成干扰项

        # 2. 收集所有其他卡片中，对应键的值
        all_other_values = [
            c.get(key) for c in self.all_loaded_cards 
            if c.get('id') != current_card.get('id') and c.get(key) is not None
        ]
        
        # 3. [核心修复] 使用集合 (set) 来获取所有独一无二的候选干扰项
        unique_candidates = set(all_other_values)
        
        # 4. [核心修复] 从候选集合中移除当前卡片的正确答案
        #    这可以处理 correct_value 是字符串、数字等多种情况
        if correct_value in unique_candidates:
            unique_candidates.remove(correct_value)

        # 5. 将集合转换回列表，以便随机取样
        final_distractor_pool = list(unique_candidates)
        
        # 6. 安全地进行随机取样
        if len(final_distractor_pool) < num_distractors:
            # 如果独一无二的干扰项不足，则返回所有可用的
            return random.sample(final_distractor_pool, len(final_distractor_pool))
        else:
            # 否则，返回所需数量的干扰项
            return random.sample(final_distractor_pool, num_distractors)


    def get_card_content(self, card):
        """
        [v2 - 健壮版]
        根据当前学习模式获取卡片的问答内容，兼容新旧两种数据结构。
        此函数现在只负责从卡片数据中提取原始信息，不再关心显示方式。
        """
        content = {
            'question': card.get('question', card.get('text', '')), # 题目文字
            'answer': card.get('answer', card.get('notes', '')), # 答案文字
            'hint': card.get('hint', ''), # 提示文字
            'image_path': card.get('image_path', ''), # 图片路径
            'id': card.get('id', '') # 卡片ID，用于音频
        }
        return content

    def display_content(self, widget, content):
        """
        [修改] 智能显示卡片内容（文本或图片），并根据词表类型解析图片路径。
        """
        is_path = isinstance(content, str) and (content.lower().endswith(('.png', '.jpg', '.jpeg')))
        widget.setWordWrap(not is_path) 
        
        if is_path:
            widget.setText("")
            full_path = ""
            if self.current_wordlist_type == 'fdeck':
                if self.current_cache_dir:
                    full_path = os.path.join(self.current_cache_dir, content)
            elif self.current_wordlist_type == 'json':
                base_dir = os.path.dirname(self.current_wordlist_path)
                full_path = os.path.join(base_dir, content)
            
            pixmap = QPixmap(full_path) if os.path.exists(full_path) else QPixmap()
            if not pixmap.isNull():
                widget.set_pixmap(pixmap)
            else:
                widget.set_pixmap(None)
                widget.setText(f"图片未找到:\n{os.path.basename(content)}") 
        else:
            widget.set_pixmap(None)
            widget.setText(str(content))

    def toggle_answer(self):
        """
        [vFinal-Fix-2] 显示或隐藏当前卡片的答案。
        此版本将答案和提示文本设置为左对齐以提高可读性。
        """
        if not self.session_active or self.current_card_index < 0:
            return
        
        self.is_answer_shown = not self.is_answer_shown
        
        if self.is_answer_shown:
            # --- 显示答案的逻辑 ---
            self.show_answer_btn.setText("隐藏答案")
            card = self.cards[self.current_card_index]
            
            # [关键修复] 设置为左对齐和顶部对齐
            self.card_answer_area.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            
            # 1. 准备要显示的文本内容
            answer_text = card.get('answer', '').replace("||", ", ")
            hint_text = card.get('hint', '')
            
            full_answer_display = []
            if answer_text: full_answer_display.append(f"<b>答案:</b> {answer_text}")
            if hint_text: full_answer_display.append(f"<b>提示:</b>\n{hint_text}")
            
            full_text_to_display = "\n\n".join(full_answer_display)
            
            # 2. 根据文本总长度动态计算字体大小
            text_length = len(full_text_to_display)
            font_size = 14

            if text_length > 250:
                font_size = 10
            elif text_length > 120:
                font_size = 12
            
            # 3. 将纯文本的换行符 (\n) 转换成 HTML 的换行符 (<br>)
            html_text_to_display = full_text_to_display.replace('\n', '<br>')
            
            # 4. 应用新的样式并设置处理过的 HTML 文本
            self.card_answer_area.setStyleSheet(f"font-size: {font_size}pt; padding: 10px;")
            self.card_answer_area.setText(html_text_to_display)
            
            # 5. 显示答案区域
            self.card_answer_area.show()
        else:
            # --- 隐藏答案的逻辑 ---
            self.show_answer_btn.setText("显示答案")
            # [关键修复] 恢复为居中对齐，以防将来需要在此区域显示其他居中内容
            self.card_answer_area.setAlignment(Qt.AlignCenter)
            self.card_answer_area.hide()

    def _normalize_string(self, text):
        """对字符串进行标准化处理，以便进行模糊匹配。"""
        return str(text).lower().replace("_", "").replace(" ", "").strip()

    def check_answer(self):
        """检查用户输入的答案是否正确。"""
        if not self.session_active or self.current_card_index < 0:
            return
            
        card = self.cards[self.current_card_index]
        user_input = self.answer_input.text().strip()
        
        correct_answers_raw = card.get('correct_answer', '').strip()
        correct_answers_list = [self._normalize_string(ans) for ans in correct_answers_raw.split('||')]

        if not user_input:
            QMessageBox.warning(self, "输入为空", "请输入您的答案。")
            return
        
        normalized_user_input = self._normalize_string(user_input)

        best_similarity = 0
        for correct_ans in correct_answers_list:
            similarity = fuzz.ratio(normalized_user_input, correct_ans)
            if similarity > best_similarity:
                best_similarity = similarity

        if best_similarity >= 90:
            is_mastered, next_review = self.update_progress_on_correct(card.get('id'))
            self.show_feedback("正确!", f"太棒了！下次复习: {next_review.strftime('%Y-%m-%d')}", auto_close_delay=1200)
            QTimer.singleShot(500, self.show_next_card) 
        elif best_similarity >= 70:
            self.update_progress_on_wrong(card.get('id'))
            feedback_text = f"拼写稍有偏差 (相似度: {best_similarity}%)。<br>正确答案是: <b>{correct_answers_list[0].title()}</b>" 
            self.show_feedback("基本正确", feedback_text)
        else:
            self.update_progress_on_wrong(card.get('id'))
            self.show_feedback("再想想？", f"答案似乎不太对哦 (相似度: {best_similarity}%)。")
            self.answer_input.clear() 
            self.answer_input.setFocus() 
            return 

        self.answer_input_widget.hide() 
        self.card_answer_area.show() 
        answer_text = card.get('answer', '')
        hint_text = card.get('hint', '')
        full_answer_display = []
        if answer_text: full_answer_display.append(f"答案: {answer_text}")
        if hint_text: full_answer_display.append(f"提示: {hint_text}")
        self.card_answer_area.setText("\n".join(full_answer_display))
        
    def show_feedback(self, title, text, auto_close_delay=-1):
        """显示一个带自动关闭或手动确认的反馈信息框。"""
        msg_box = QMessageBox(self)
        if "正确" in title or "太棒了" in title:
            msg_box.setIcon(QMessageBox.Information)
        else:
            msg_box.setIcon(QMessageBox.Warning)
        
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        msg_box.setTextFormat(Qt.RichText) 
        
        if auto_close_delay > 0:
            msg_box.setStandardButtons(QMessageBox.NoButton) 
            QTimer.singleShot(auto_close_delay, msg_box.accept) 
        else:
            msg_box.setStandardButtons(QMessageBox.Ok) 
        
        msg_box.exec_() 

    def play_current_audio(self, force_card_id=None):
        """
        [vFinal] 播放当前卡片关联的音频。
        此方法现在是一个播放队列的构建器和启动器。
        """
        if not self.session_active: return

        # 停止任何正在播放的音频
        self.player.stop()
        self.playback_queue.clear() # 清空旧的播放队列

        audio_key = force_card_id if force_card_id else self.cards[self.current_card_index].get('id')
        if not audio_key: return

        # --- 构建新的播放队列 ---
        # 1. 添加单词音频
        word_audio_path = self._find_audio_path(audio_key, 'word')
        if word_audio_path:
            self.playback_queue.append(word_audio_path)
        
        # 2. 如果启用了例句模式，并且是学习模式，则添加例句音频
        if self.play_sentence_switch.isChecked() and self.session_config.get('paradigm') == 'memory':
            sentence_audio_path = self._find_audio_path(audio_key, 'sentence')
            if sentence_audio_path:
                self.playback_queue.append(sentence_audio_path)
        
        # --- 启动播放队列 ---
        if self.playback_queue:
            self._play_next_in_queue()
        else:
            self.parent_window.statusBar().showMessage(f"找不到 '{audio_key}' 的音频文件", 2000)

    def show_prev_card(self):
        """显示上一张卡片。"""
        if not self.session_active or self.current_card_index <= 0:
            return
        self.list_widget.setCurrentRow(self.current_card_index - 1)

    def show_next_card(self):
        """显示下一张卡片或结束会话。"""
        if not self.session_active or self.current_card_index >= len(self.cards) - 1:
            QMessageBox.information(self, "完成", "您已完成本轮所有卡片的学习！")
            self.reset_session()
            return
        self.list_widget.setCurrentRow(self.current_card_index + 1)
        
    def jump_to_card(self, row):
        """根据列表选择跳转到指定卡片。"""
        if not self.session_active or row == -1 or row == self.current_card_index:
            return
        self.current_card_index = row
        self.update_card_display()

    def toggle_mastered_status(self):
        """切换当前卡片的掌握状态。"""
        if not self.session_active or self.current_card_index == -1:
            return
        card_id = self.cards[self.current_card_index].get('id')
        if not card_id:
            return
        
        progress = self.progress_data.setdefault(card_id, {"views": 0, "mastered": False, "errors": 0, "level": 0, "last_viewed_ts": 0, "next_review_ts": 0})
        
        new_status = not progress.get("mastered", False) 
        progress["mastered"] = new_status
        
        if new_status:
             progress["level"] = progress.get("level", 0) + 1 
             if progress["level"] == 0: progress["level"] = 1 
             next_review_date = datetime.now() + timedelta(days=self.get_review_interval(progress["level"]))
             progress["next_review_ts"] = next_review_date.timestamp()
        else:
            progress["level"] = 0
            progress["next_review_ts"] = 0
            
        self.update_list_item_icon(self.current_card_index, new_status) 
        self.save_progress() 

        if self.hide_list_switch.isChecked() and not self.list_widget.isVisible():
            status_text = "已标记为“已掌握”" if new_status else "已取消“已掌握”标记"
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setText(f"<b>{card_id}</b><br>{status_text}")
            msg_box.setWindowTitle("状态更新")
            msg_box.setStandardButtons(QMessageBox.NoButton)
            msg_box.setWindowModality(Qt.NonModal) 
            msg_box.show()
            QTimer.singleShot(1200, msg_box.accept) 


    def update_list_widget(self):
        """
        [v1.1 - AnimatedList版]
        使用动画更新左侧的会话卡片列表。
        """
        card_ids = [card.get('id', '未知ID') for card in self.cards]
        self.list_widget.addItemsWithAnimation(card_ids)

        # 由于 addItemsWithAnimation 是异步的，我们延迟更新图标
        QTimer.singleShot(250, self._update_all_list_item_icons)

    def _update_all_list_item_icons(self):
        """[新增] 在列表项动画完成后，遍历并更新所有图标。"""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item: continue
        
            card_id = item.text()
            is_mastered = self.progress_data.get(card_id, {}).get("mastered", False)
            self.update_list_item_icon(i, is_mastered)

    def update_list_item_icon(self, row, is_mastered):
        """更新指定行号的列表项的掌握图标。"""
        item = self.list_widget.item(row)
        if item:
            item.setIcon(self.icon_manager.get_icon("success") if is_mastered else QIcon()) 

    def load_progress(self):
        """
        加载当前词表的学习进度。
        进度文件命名基于词表文件名（不含扩展名）。
        """
        if not self.current_wordlist_path:
            self.progress_data = {}
            return

        progress_file = os.path.join(self.PROGRESS_DIR, f"{self.current_wordlist_name_no_ext}.json")
        
        if os.path.exists(progress_file):
            try:
                with open(progress_file, 'r', encoding='utf-8') as f:
                    self.progress_data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"无法读取或解析进度文件 '{progress_file}': {e}", file=sys.stderr)
                self.progress_data = {} 

        else:
            self.progress_data = {} 

    def save_progress(self):
        """保存当前会话的词表学习进度。"""
        if not self.session_active:
            return 
            
        progress_file = os.path.join(self.PROGRESS_DIR, f"{self.current_wordlist_name_no_ext}.json")
        
        try:
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(self.progress_data, f, indent=4, ensure_ascii=False)
        except IOError as e:
            print(f"无法保存进度文件 '{progress_file}': {e}", file=sys.stderr)
        
    def get_review_interval(self, level):
        """根据学习等级返回对应的复习间隔天数。"""
        intervals = [1, 2, 4, 7, 15, 30, 60]
        return intervals[min(level - 1, len(intervals) - 1)] 

    def update_progress_on_view(self, card_id):
        """更新卡片被查看时的学习进度数据（如查看次数、最后查看时间）。"""
        if not card_id:
            return
            
        progress = self.progress_data.setdefault(card_id, {"views": 0, "mastered": False, "errors": 0, "level": 0, "last_viewed_ts": 0, "next_review_ts": 0})
        
        progress["views"] = progress.get("views", 0) + 1
        progress["last_viewed_ts"] = datetime.now().timestamp()
        
        self.save_progress()

    def update_progress_on_correct(self, card_id):
        """当答案正确时更新卡片的学习进度。"""
        if not card_id:
            return False, datetime.now()
            
        progress = self.progress_data.setdefault(card_id, {"views": 0, "mastered": False, "errors": 0, "level": 0, "last_viewed_ts": 0, "next_review_ts": 0})
        
        progress["mastered"] = True 
        progress["level"] = progress.get("level", 0) + 1 
        if progress["level"] == 0: progress["level"] = 1 
        
        next_review_date = datetime.now() + timedelta(days=self.get_review_interval(progress["level"]))
        progress["next_review_ts"] = next_review_date.timestamp() 

        self.update_list_item_icon(self.current_card_index, True) 
        self.save_progress()
        
        return True, next_review_date 

    def update_progress_on_wrong(self, card_id):
        """当答案错误时更新卡片的学习进度。"""
        if not card_id:
            return
            
        progress = self.progress_data.setdefault(card_id, {"views": 0, "mastered": False, "errors": 0, "level": 0, "last_viewed_ts": 0, "next_review_ts": 0})
        
        progress["mastered"] = False 
        progress["errors"] = progress.get("errors", 0) + 1 
        progress["level"] = 0 
        progress["next_review_ts"] = 0 

        self.update_list_item_icon(self.current_card_index, False) 
        self.save_progress()

    def _on_persistent_setting_changed(self, key, value):
        """
        当用户更改任何可记忆的设置时，调用此方法以保存状态。
        这会通过主窗口的 API 将设置持久化到 settings.json。
        """
        self.parent_window.update_and_save_module_state('flashcard', key, value) 

# --- END OF FILE modules/flashcard_module.py ---