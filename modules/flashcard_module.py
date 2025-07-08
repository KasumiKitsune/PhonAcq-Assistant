# --- START OF FILE modules/flashcard_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "速记卡"
MODULE_DESCRIPTION = "使用图文、音频结合的方式进行学习和记忆，并自动记录学习进度。"
# ---

import os
import sys
import random
import threading
import json
from datetime import datetime, timedelta

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QMessageBox, QComboBox, QFormLayout, QGroupBox, QRadioButton, QLineEdit,
                             QListWidgetItem, QSizePolicy, QShortcut)
from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QPixmap, QImageReader, QIcon, QTextDocument, QColor, QKeySequence

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

# --- 模块的创建入口 ---
def create_page(parent_window, ToggleSwitchClass, ScalableImageLabelClass, BASE_PATH, GLOBAL_TTS_DIR, GLOBAL_RECORD_DIR, icon_manager):
    if DEPENDENCIES_MISSING:
        error_page = QWidget(); layout = QVBoxLayout(error_page)
        label = QLabel(f"速记卡模块加载失败：\n缺少必要的依赖库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install sounddevice soundfile PyQt5.QtMultimedia thefuzz python-Levenshtein")
        label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); layout.addWidget(label)
        return error_page
    
    base_flashcard_dir = os.path.join(BASE_PATH, "flashcards")
    visual_dir = os.path.join(base_flashcard_dir, "visual_wordlists")
    common_dir = os.path.join(base_flashcard_dir, "common_wordlists")
    tts_dir = os.path.join(base_flashcard_dir, "audio_tts")
    progress_dir = os.path.join(base_flashcard_dir, "progress")
    for path in [base_flashcard_dir, visual_dir, common_dir, tts_dir, progress_dir]:
        os.makedirs(path, exist_ok=True)
    
    return FlashcardPage(parent_window, ToggleSwitchClass, ScalableImageLabelClass, 
                         visual_dir, common_dir, tts_dir, progress_dir, 
                         GLOBAL_TTS_DIR, GLOBAL_RECORD_DIR, icon_manager)

class FlashcardPage(QWidget):
    def __init__(self, parent_window, ToggleSwitchClass, ScalableImageLabelClass, 
                 VISUAL_DIR, COMMON_DIR, TTS_DIR, PROGRESS_DIR, 
                 GLOBAL_TTS_DIR, GLOBAL_RECORD_DIR, icon_manager):
        super().__init__()
        self.parent_window = parent_window; self.ToggleSwitch = ToggleSwitchClass; self.ScalableImageLabel = ScalableImageLabelClass
        self.VISUAL_DIR = VISUAL_DIR; self.COMMON_DIR = COMMON_DIR; self.TTS_DIR = TTS_DIR; self.PROGRESS_DIR = PROGRESS_DIR
        self.GLOBAL_TTS_DIR = GLOBAL_TTS_DIR; self.GLOBAL_RECORD_DIR = GLOBAL_RECORD_DIR
        self.icon_manager = icon_manager # [新增] 保存 icon_manager
        
        self.session_active = False; self.all_loaded_cards = []; self.cards = []
        self.current_card_index = -1; self.is_answer_shown = False; self.current_wordlist_path = ""; self.current_wordlist_name_no_ext = ""
        self.current_wordlist_type = ""; self.progress_data = {}; self.selected_mode_id = ""
        self.player = QMediaPlayer()
        self._init_ui()
        self._connect_signals()
        self.update_icons() # [新增] 首次加载时更新图标
        self.update_mode_options()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        left_panel = QWidget(); left_layout = QVBoxLayout(left_panel); left_panel.setFixedWidth(240)
        left_layout.addWidget(QLabel("项目列表:"))
        self.list_widget = QListWidget(); self.list_widget.setWordWrap(True); self.list_widget.setSortingEnabled(False); self.list_widget.setToolTip("当前学习会话中的所有卡片列表。\n单击可跳转，已掌握的卡片会有标记。")
        left_layout.addWidget(self.list_widget, 1)
        self.mark_mastered_btn = QPushButton("标记/取消掌握"); self.mark_mastered_btn.setToolTip("将当前卡片标记为“已掌握”或取消标记 (快捷键: Ctrl+G)。\n已掌握的卡片在“智能随机”模式下出现的频率会大大降低。")
        left_layout.addWidget(self.mark_mastered_btn)
        
        center_panel = QWidget(); center_layout = QVBoxLayout(center_panel)
        self.card_question_area = self.ScalableImageLabel("请从右侧加载词表开始学习"); self.card_question_area.setObjectName("FlashcardQuestionArea")
        self.card_question_area.setStyleSheet("QLabel#FlashcardQuestionArea { font-size: 20pt; font-weight: bold; padding: 10px; }")
        
        self.card_answer_area = self.ScalableImageLabel(""); self.card_answer_area.setObjectName("FlashcardAnswerArea"); self.card_answer_area.setAlignment(Qt.AlignCenter); self.card_answer_area.setWordWrap(True)
        self.card_answer_area.setStyleSheet("QLabel#FlashcardAnswerArea { font-size: 18pt; padding: 10px; }")

        self.progress_label = QLabel("卡片: - / -"); self.progress_label.setAlignment(Qt.AlignCenter); self.progress_label.setToolTip("显示当前会话中卡片的学习进度。") # [新增]
        self.answer_input = QLineEdit(); self.answer_input.setPlaceholderText("在此输入答案..."); self.answer_input.setToolTip("在此输入您认为正确的答案，然后按Enter键或点击“提交”按钮。")
        self.answer_submit_btn = QPushButton("提交答案"); self.answer_submit_btn.setToolTip("提交您的答案进行检查。")
        self.answer_input_widget = QWidget(); answer_input_layout = QHBoxLayout(self.answer_input_widget)
        answer_input_layout.setContentsMargins(0,0,0,0); answer_input_layout.addWidget(self.answer_input); answer_input_layout.addWidget(self.answer_submit_btn)
        self.answer_input_widget.hide()
        center_bottom_bar = QWidget(); center_bottom_layout = QHBoxLayout(center_bottom_bar)
        self.prev_btn = QPushButton("上一个"); self.prev_btn.setToolTip("显示上一张卡片 (快捷键: ← 左方向键)。")
        self.show_answer_btn = QPushButton("显示/隐藏答案"); self.show_answer_btn.setObjectName("AccentButton"); self.show_answer_btn.setToolTip("显示或隐藏当前卡片的答案 (快捷键: 空格键)。")
        self.next_btn = QPushButton("下一个"); self.next_btn.setToolTip("显示下一张卡片 (快捷键: → 右方向键)。")
        self.play_audio_btn = QPushButton("播放音频"); self.play_audio_btn.setToolTip("播放当前卡片关联的音频 (快捷键: P)。")
        center_bottom_layout.addStretch(); center_bottom_layout.addWidget(self.prev_btn); center_bottom_layout.addWidget(self.show_answer_btn); center_bottom_layout.addWidget(self.next_btn); center_bottom_layout.addWidget(self.play_audio_btn); center_bottom_layout.addStretch()
        center_layout.addWidget(self.card_question_area, 1); center_layout.addWidget(self.card_answer_area); center_layout.addWidget(self.answer_input_widget); center_layout.addWidget(self.progress_label); center_layout.addWidget(center_bottom_bar)
        
        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel); right_panel.setFixedWidth(300)
        source_group = QGroupBox("1. 选择词表"); source_layout = QFormLayout(source_group); self.wordlist_combo = QComboBox(); self.wordlist_combo.setToolTip("从速记卡模块的词表文件夹中选择一个要学习的词表。")
        source_layout.addRow("词表文件:", self.wordlist_combo)
        mode_group = QGroupBox("2. 选择模式"); self.mode_layout = QVBoxLayout(mode_group)
        options_group = QGroupBox("3. 学习选项"); options_layout = QVBoxLayout(options_group)
        module_states = self.parent_window.config.get("module_states", {}).get("flashcard", {})
        # --- 卡片顺序 ---
        self.order_mode_group = QGroupBox("卡片顺序")
        order_layout = QVBoxLayout()
        self.smart_random_radio = QRadioButton("智能随机 (推荐)")
        self.random_radio = QRadioButton("完全随机")
        self.sequential_radio = QRadioButton("按列表顺序")
        
        # 加载已保存的顺序模式
        saved_order_mode = module_states.get('order_mode', 'smart_random')
        if saved_order_mode == 'random':
            self.random_radio.setChecked(True)
        elif saved_order_mode == 'sequential':
            self.sequential_radio.setChecked(True)
        else: # 默认为 smart_random
            self.smart_random_radio.setChecked(True)
            
        # ... (设置 tooltips 的代码不变) ...
        self.smart_random_radio.setToolTip("优先展示未掌握、易错和到期应复习的卡片，是最高效的学习模式。")
        self.random_radio.setToolTip("在所有卡片中（包括已掌握的）纯粹随机抽取。")
        self.sequential_radio.setToolTip("严格按照词表文件中的原始顺序显示所有卡片。")
        
        order_layout.addWidget(self.smart_random_radio)
        order_layout.addWidget(self.random_radio)
        order_layout.addWidget(self.sequential_radio)
        self.order_mode_group.setLayout(order_layout)
        
        # --- 其他开关 ---
        autoplay_layout = QHBoxLayout()
        autoplay_layout.addWidget(QLabel("自动播放音频:"))
        self.autoplay_audio_switch = self.ToggleSwitch()
        self.autoplay_audio_switch.setChecked(module_states.get('autoplay_audio', True)) # 默认开启
        self.autoplay_audio_switch.setToolTip("开启后，在“学习模式”下切换到新卡片时，会自动显示答案，无需手动点击。")
        autoplay_layout.addWidget(self.autoplay_audio_switch)
        autoplay_layout.addStretch()
        
        hide_list_layout = QHBoxLayout()
        hide_list_layout.addWidget(QLabel("隐藏项目列表:"))
        self.hide_list_switch = self.ToggleSwitch()
        self.hide_list_switch.setChecked(module_states.get('hide_list', True)) # 默认开启
        self.hide_list_switch.setToolTip("开启后，开始学习时将隐藏左侧的卡片列表，以减少干扰，专注于当前卡片。")
        hide_list_layout.addWidget(self.hide_list_switch)
        hide_list_layout.addStretch()
        
        auto_show_answer_layout = QHBoxLayout()
        auto_show_answer_layout.addWidget(QLabel("自动显示答案:"))
        self.auto_show_answer_switch = self.ToggleSwitch()
        self.auto_show_answer_switch.setChecked(module_states.get('auto_show_answer', False)) # 默认关闭
        self.auto_show_answer_switch.setToolTip("开启后，在“学习模式”下切换到新卡片时，会自动显示答案，无需手动点击。")
        auto_show_answer_layout.addWidget(self.auto_show_answer_switch)
        auto_show_answer_layout.addStretch()
        
        options_layout.addWidget(self.order_mode_group)
        options_layout.addLayout(autoplay_layout)
        options_layout.addLayout(hide_list_layout)
        options_layout.addLayout(auto_show_answer_layout)
        self.clear_progress_btn = QPushButton("清空当前词表学习记录"); self.clear_progress_btn.setObjectName("ActionButton_Delete"); self.clear_progress_btn.setToolTip("警告：将永久删除当前选中词表的所有学习记录（如掌握状态、复习次数等）。")
        self.start_reset_btn = QPushButton("加载词表并开始学习"); self.start_reset_btn.setObjectName("AccentButton"); self.start_reset_btn.setFixedHeight(40); self.start_reset_btn.setToolTip("加载选中的词表和模式，开始一个新的学习会话。/ 结束当前会话并返回选择界面。")
        right_layout.addWidget(source_group); right_layout.addWidget(mode_group); right_layout.addWidget(options_group); right_layout.addStretch()
        right_layout.addWidget(self.clear_progress_btn); right_layout.addWidget(self.start_reset_btn)
        
        main_layout.addWidget(left_panel); main_layout.addWidget(center_panel, 1); main_layout.addWidget(right_panel)
        self.populate_wordlists()

    def _connect_signals(self):
        self.wordlist_combo.currentIndexChanged.connect(self.update_mode_options)
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
        # [新增] 连接持久化设置的信号
        # QRadioButton 的 toggled 信号在选中时会发出 True
        self.smart_random_radio.toggled.connect(
            lambda checked: self._on_persistent_setting_changed('order_mode', 'smart_random') if checked else None
        )
        self.random_radio.toggled.connect(
            lambda checked: self._on_persistent_setting_changed('order_mode', 'random') if checked else None
        )
        self.sequential_radio.toggled.connect(
            lambda checked: self._on_persistent_setting_changed('order_mode', 'sequential') if checked else None
        )
        
        # ToggleSwitch 的 stateChanged 信号发出的是状态值 (0 或 2)
        self.autoplay_audio_switch.stateChanged.connect(
            lambda state: self._on_persistent_setting_changed('autoplay_audio', bool(state))
        )
        self.hide_list_switch.stateChanged.connect(
            lambda state: self._on_persistent_setting_changed('hide_list', bool(state))
        )
        self.auto_show_answer_switch.stateChanged.connect(
            lambda state: self._on_persistent_setting_changed('auto_show_answer', bool(state))
        )
        
        QShortcut(QKeySequence(Qt.Key_Left), self, self.show_prev_card)
        QShortcut(QKeySequence(Qt.Key_Right), self, self.show_next_card)
        QShortcut(QKeySequence(Qt.Key_P), self, self.play_current_audio)
        QShortcut(QKeySequence(Qt.Key_Space), self, self.toggle_answer)
        QShortcut(QKeySequence("Ctrl+G"), self, self.toggle_mastered_status)

    # --- [新增] 更新图标的方法 ---
    def update_icons(self):
        """从IconManager获取并设置所有图标。"""
        # start_reset_btn 动态图标
        if self.session_active:
            self.start_reset_btn.setIcon(self.icon_manager.get_icon("end_session_dark"))
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
                is_mastered = self.progress_data.get(card['id'], {}).get("mastered", False)
                self.update_list_item_icon(i, is_mastered)


    def populate_wordlists(self):
        self.wordlist_combo.clear()
        self.wordlist_combo.addItem("--- 请选择一个词表 ---", userData=None)
        
        # [修改] 扫描 .json 文件
        if os.path.exists(self.COMMON_DIR):
            for f in sorted(os.listdir(self.COMMON_DIR)):
                 if f.endswith('.json'): self.wordlist_combo.addItem(f"[标准] {f}", userData=("common", f))
        if os.path.exists(self.VISUAL_DIR):
            for f in sorted(os.listdir(self.VISUAL_DIR)):
                if f.endswith('.json'): self.wordlist_combo.addItem(f"[图文] {f}", userData=("visual", f))

    def update_mode_options(self, index=0):
        while self.mode_layout.count():
            child = self.mode_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        self.mode_buttons = []
        user_data = self.wordlist_combo.currentData()
        if not user_data: return
        list_type, _ = user_data
        if list_type == "common":
            self.add_mode_button("看词记音 (学习)", "word_to_sound", "学习模式：看到单词，回忆其发音。")
            self.add_mode_button("听音记词 (自检)", "sound_to_word", "自检模式：听到发音，输入对应的单词。")
        elif list_type == "visual":
            self.add_mode_button("看词记图 (学习)", "text_to_image", "学习模式：看到单词/描述，回忆其对应的图片。")
            self.add_mode_button("看图记词 (自检)", "image_to_text", "自检模式：看到图片，输入对应的单词/ID。")
        if self.mode_buttons: self.mode_buttons[0].setChecked(True)

    def add_mode_button(self, text, mode_id, tooltip=""):
        radio_btn = QRadioButton(text); radio_btn.setProperty("mode_id", mode_id)
        if tooltip: radio_btn.setToolTip(tooltip)
        self.mode_layout.addWidget(radio_btn); self.mode_buttons.append(radio_btn)
        
    def handle_start_reset(self):
        if not self.session_active: self.start_session()
        else: self.reset_session()
            
    def start_session(self):
        user_data = self.wordlist_combo.currentData()
        if not user_data: QMessageBox.warning(self, "错误", "请先选择一个有效的词表文件。"); return
        self.current_wordlist_type, wordlist_file = user_data; self.selected_mode_id = next((btn.property("mode_id") for btn in self.mode_buttons if btn.isChecked()), None)
        if not self.selected_mode_id: QMessageBox.warning(self, "错误", "请选择一个学习模式。"); return
        try:
            self.load_and_adapt_data(wordlist_file); self.load_progress(wordlist_file)
        except Exception as e: QMessageBox.critical(self, "加载失败", f"无法加载或解析词表文件:\n{e}"); return
        if not self.all_loaded_cards: QMessageBox.information(self, "无内容", "词表中没有可用的学习项目。"); return
        self.session_active = True; self.current_wordlist_name_no_ext = os.path.splitext(wordlist_file)[0]
        self._generate_card_order(); self.update_list_widget()
        
        self.start_reset_btn.setText("结束学习会话")
        self.update_icons() # [新增] 切换状态后更新按钮图标
        
        self.wordlist_combo.setEnabled(False); self.order_mode_group.setEnabled(False); self.hide_list_switch.setEnabled(False); self.clear_progress_btn.setEnabled(False)
        self.auto_show_answer_switch.setEnabled(False)
        if self.hide_list_switch.isChecked(): self.list_widget.hide()
        if self.cards: self.current_card_index = -1; self.list_widget.setCurrentRow(0)
        else: self.card_question_area.set_pixmap(None); self.card_question_area.setText("所有卡片均已掌握并通过筛选！\n请尝试其他模式或重置进度。"); self.progress_label.setText("太棒了！")

    def reset_session(self):
        if self.session_active: self.save_progress()
        self.session_active = False; self.cards.clear(); self.all_loaded_cards.clear(); self.list_widget.clear()
        self.card_question_area.set_pixmap(None); self.card_question_area.setText("请从右侧加载词表开始学习"); self.card_answer_area.set_pixmap(None); self.card_answer_area.setText("")
        self.progress_label.setText("卡片: - / -"); self.progress_data.clear()
        self.list_widget.show(); self.start_reset_btn.setText("加载词表并开始学习")
        self.update_icons() # [新增] 切换状态后更新按钮图标
        self.wordlist_combo.setEnabled(True); self.order_mode_group.setEnabled(True); self.hide_list_switch.setEnabled(True); self.clear_progress_btn.setEnabled(True)
        self.auto_show_answer_switch.setEnabled(True); self.answer_input_widget.hide()

    def load_and_adapt_data(self, filename):
        self.all_loaded_cards.clear()
        base_dir = self.VISUAL_DIR if self.current_wordlist_type == "visual" else self.COMMON_DIR
        self.current_wordlist_path = os.path.join(base_dir, filename)

        try:
            # [修改] 使用 json.load()
            with open(self.current_wordlist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            meta = data.get("meta", {})
            file_format = meta.get("format")

            if self.current_wordlist_type == "visual" and file_format == "visual_wordlist":
                items = data.get("items", [])
                for item in items:
                    self.all_loaded_cards.append({
                        'id': item.get('id', ''), 
                        'image_path': item.get('image_path', ''), 
                        'text': item.get('prompt_text', ''), 
                        'notes': item.get('notes', ''), 
                        'correct_answer': item.get('id', '')
                    })
            elif self.current_wordlist_type == "common" and file_format == "standard_wordlist":
                groups = data.get("groups", [])
                for group in groups:
                    for item in group.get("items", []):
                        word = item.get("text")
                        if word:
                            self.all_loaded_cards.append({
                                'id': word, 
                                'text': word, 
                                'notes': item.get('note', ''), 
                                'correct_answer': word
                            })
            else:
                raise ValueError(f"词表类型 '{self.current_wordlist_type}' 与文件格式 '{file_format}' 不匹配。")

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # 向上抛出异常，由调用者处理
            raise Exception(f"加载或解析词表文件 '{filename}' 失败: {e}")
        
    def _generate_card_order(self):
        source_cards = list(self.all_loaded_cards); now_ts = datetime.now().timestamp()
        if self.smart_random_radio.isChecked():
            def get_weight(card):
                card_id = card.get('id'); progress = self.progress_data.get(card_id, {})
                if progress.get("mastered", False):
                    next_review_ts = progress.get("next_review_ts", now_ts); return 50 + (now_ts - next_review_ts) / (3600*24) if now_ts >= next_review_ts else 0.1
                else:
                    views = progress.get("views", 0); errors = progress.get("errors", 0); return 100 + errors * 50 - views * 2
            weighted_cards = [(card, get_weight(card)) for card in source_cards]; self.cards = [card for card, weight in weighted_cards if weight > 0.5]
            if len(self.cards) < 5 and len(source_cards) > len(self.cards): self.cards = source_cards
            self.cards.sort(key=lambda c: get_weight(c), reverse=True)
        elif self.random_radio.isChecked(): random.shuffle(source_cards); self.cards = source_cards
        else: self.cards = source_cards

    def update_card_display(self):
        if not self.session_active or self.current_card_index < 0 or self.current_card_index >= len(self.cards): return
        card = self.cards[self.current_card_index]; self.is_answer_shown = False; card_content = self.get_card_content(card)
        self.display_content(self.card_question_area, card_content['question']); self.card_answer_area.set_pixmap(None); self.card_answer_area.setText(""); self.card_answer_area.hide()
        is_self_test_mode = "to_word" in self.selected_mode_id or "to_text" in self.selected_mode_id
        self.answer_input_widget.setVisible(is_self_test_mode); self.show_answer_btn.setVisible(not is_self_test_mode)
        if is_self_test_mode: self.answer_input.clear(); self.answer_input.setFocus()
        self.progress_label.setText(f"卡片: {self.current_card_index + 1} / {len(self.cards)}"); self.update_progress_on_view(card.get('id'))
        if self.auto_show_answer_switch.isChecked() and not is_self_test_mode: QTimer.singleShot(50, self.toggle_answer)
        if self.autoplay_audio_switch.isChecked(): self.play_current_audio()
            
    def get_card_content(self, card):
        content = {};
        if self.selected_mode_id == "word_to_sound": content['question'], content['answer'] = card['text'], card['notes']
        elif self.selected_mode_id == "sound_to_word": content['question'], content['answer'] = "听音，写出单词...", f"{card['text']}\n({card['notes']})"
        elif self.selected_mode_id == "text_to_image": content['question'], content['answer'] = card['text'], card['image_path']
        elif self.selected_mode_id == "image_to_text": content['question'], content['answer'] = card['image_path'], f"答案: {card['id']}\n({card['text']})"
        return content

    def display_content(self, widget, content):
        is_path = isinstance(content, str) and (content.lower().endswith(('.png', '.jpg', '.jpeg'))); widget.setWordWrap(not is_path)
        if is_path:
            widget.setText(""); base_dir = os.path.dirname(self.current_wordlist_path); full_path = os.path.join(base_dir, content)
            pixmap = QPixmap(full_path) if os.path.exists(full_path) else QPixmap()
            if not pixmap.isNull(): widget.set_pixmap(pixmap)
            else: widget.set_pixmap(None); widget.setText(f"图片未找到:\n{content}")
        else: widget.set_pixmap(None); widget.setText(str(content))
            
    def toggle_answer(self):
        if not self.session_active or self.current_card_index < 0: return
        is_self_test_mode = "to_word" in self.selected_mode_id or "to_text" in self.selected_mode_id
        if is_self_test_mode and self.answer_input_widget.isVisible(): return
        self.is_answer_shown = not self.is_answer_shown
        if self.is_answer_shown:
            card = self.cards[self.current_card_index]; answer_data = self.get_card_content(card).get('answer', '')
            self.display_content(self.card_answer_area, answer_data); self.card_answer_area.show()
        else: self.card_answer_area.hide()

    def _normalize_string(self, text):
        return str(text).lower().replace("_", "").replace(" ", "").strip()

    def check_answer(self):
        if not self.session_active or self.current_card_index < 0: return
        card = self.cards[self.current_card_index]; user_input = self.answer_input.text().strip(); correct_answer = card.get('correct_answer', '').strip()
        if not user_input: QMessageBox.warning(self, "输入为空", "请输入您的答案。"); return
        similarity = fuzz.ratio(self._normalize_string(user_input), self._normalize_string(correct_answer)); auto_advance_delay = -1
        if similarity >= 90:
            is_mastered, next_review = self.update_progress_on_correct(card.get('id')); self.show_feedback("正确!", f"太棒了！下次复习: {next_review.strftime('%Y-%m-%d')}", auto_close_delay=1200); auto_advance_delay = 0
        elif similarity >= 70:
            self.update_progress_on_wrong(card.get('id')); feedback_text = f"拼写稍有偏差 (相似度: {similarity}%)。<br>正确答案是: <b>{correct_answer}</b>"; self.show_feedback("基本正确", feedback_text); auto_advance_delay = 500
        else: self.update_progress_on_wrong(card.get('id')); self.show_feedback("再想想？", f"答案似乎不太对哦 (相似度: {similarity}%)。"); self.answer_input.clear(); self.answer_input.setFocus(); return
        self.answer_input_widget.hide(); self.card_answer_area.show(); self.display_content(self.card_answer_area, self.get_card_content(card).get('answer', ''));
        if auto_advance_delay >= 0: QTimer.singleShot(auto_advance_delay, self.show_next_card)

    def show_feedback(self, title, text, auto_close_delay=-1):
        msg_box = QMessageBox(self)
        if "正确" in title or "太棒了" in title: msg_box.setIcon(QMessageBox.Information)
        else: msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle(title); msg_box.setText(text); msg_box.setTextFormat(Qt.RichText)
        if auto_close_delay > 0: msg_box.setStandardButtons(QMessageBox.NoButton); QTimer.singleShot(auto_close_delay, msg_box.accept)
        else: msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec_()

    def play_current_audio(self):
        if not self.session_active or self.current_card_index < 0: return
        card = self.cards[self.current_card_index]; audio_key = card.get('id'); paths_to_check = []
        for ext in ['.wav', '.mp3']: paths_to_check.append(os.path.join(self.GLOBAL_RECORD_DIR, self.current_wordlist_name_no_ext, f"{audio_key}{ext}"))
        paths_to_check.append(os.path.join(self.TTS_DIR, self.current_wordlist_name_no_ext, f"{audio_key}.mp3")); paths_to_check.append(os.path.join(self.GLOBAL_TTS_DIR, self.current_wordlist_name_no_ext, f"{audio_key}.mp3"))
        final_path = next((path for path in paths_to_check if os.path.exists(path)), None)
        if final_path: self.player.setMedia(QMediaContent(QUrl.fromLocalFile(final_path))); self.player.play()
        else: self.parent_window.statusBar().showMessage(f"找不到 '{audio_key}' 的音频文件", 2000)

    def show_prev_card(self):
        if not self.session_active or self.current_card_index <= 0: return
        self.list_widget.setCurrentRow(self.current_card_index - 1)

    def show_next_card(self):
        if not self.session_active or self.current_card_index >= len(self.cards) - 1: QMessageBox.information(self, "完成", "您已完成本轮所有卡片的学习！"); self.reset_session(); return
        self.list_widget.setCurrentRow(self.current_card_index + 1)
        
    def jump_to_card(self, row):
        if not self.session_active or row == -1 or row == self.current_card_index: return
        self.current_card_index = row; self.update_card_display()

    def toggle_mastered_status(self):
        if not self.session_active or self.current_card_index == -1: return
        card_id = self.cards[self.current_card_index].get('id');
        if not card_id: return
        progress = self.progress_data.setdefault(card_id, {"views": 0, "mastered": False, "errors": 0, "level": 0, "last_viewed_ts": 0, "next_review_ts": 0})
        new_status = not progress.get("mastered", False); progress["mastered"] = new_status
        if new_status:
             progress["level"] = progress.get("level", 0) or 1; progress["next_review_ts"] = (datetime.now() + timedelta(days=self.get_review_interval(progress["level"]))).timestamp()
        else: progress["level"] = 0
        self.update_list_item_icon(self.current_card_index, new_status); self.save_progress()
        if self.hide_list_switch.isChecked() and not self.list_widget.isVisible():
            status_text = "已标记为“已掌握”" if new_status else "已取消“已掌握”标记"; msg_box = QMessageBox(self); msg_box.setIcon(QMessageBox.Information); msg_box.setText(f"<b>{card_id}</b><br>{status_text}"); msg_box.setWindowTitle("状态更新")
            msg_box.setStandardButtons(QMessageBox.NoButton); msg_box.setWindowModality(Qt.NonModal); msg_box.show(); QTimer.singleShot(1200, msg_box.accept)

    def clear_current_progress(self):
        user_data = self.wordlist_combo.currentData()
        if not user_data: QMessageBox.warning(self, "操作无效", "请先选择一个词表。"); return
        _, wordlist_file = user_data; progress_file = os.path.join(self.PROGRESS_DIR, f"{os.path.splitext(wordlist_file)[0]}.json")
        reply = QMessageBox.question(self, "清空学习记录", f"您确定要清空词表 '{wordlist_file}' 的所有学习记录吗？\n此操作不可撤销！", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes and os.path.exists(progress_file):
            try: os.remove(progress_file); self.progress_data = {}; QMessageBox.information(self, "成功", f"词表 '{wordlist_file}' 的学习记录已清空。");
            except Exception as e: QMessageBox.critical(self, "错误", f"清空学习记录失败: {e}")
            if self.session_active: self.reset_session()

    def update_list_widget(self):
        self.list_widget.clear()
        for i, card in enumerate(self.cards):
            item = QListWidgetItem(card['id']); self.list_widget.addItem(item); self.update_list_item_icon(i, self.progress_data.get(card['id'], {}).get("mastered", False))

    def update_list_item_icon(self, row, is_mastered):
        item = self.list_widget.item(row)
        if item: item.setIcon(self.icon_manager.get_icon("success") if is_mastered else QIcon()) # [修改] 使用IconManager

    def load_progress(self, wordlist_file):
        progress_file = os.path.join(self.PROGRESS_DIR, f"{os.path.splitext(wordlist_file)[0]}.json")
        if os.path.exists(progress_file):
            try:
                with open(progress_file, 'r', encoding='utf-8') as f: self.progress_data = json.load(f)
            except (json.JSONDecodeError, IOError): self.progress_data = {}
        else: self.progress_data = {}

    def save_progress(self):
        if not self.session_active: return
        user_data = self.wordlist_combo.currentData();
        if not user_data: return
        _, wordlist_file = user_data; progress_file = os.path.join(self.PROGRESS_DIR, f"{os.path.splitext(wordlist_file)[0]}.json")
        try:
            with open(progress_file, 'w', encoding='utf-8') as f: json.dump(self.progress_data, f, indent=4, ensure_ascii=False)
        except IOError as e: print(f"无法保存进度文件 '{progress_file}': {e}")
        
    def get_review_interval(self, level):
        intervals = [1, 2, 4, 7, 15, 30, 60]; return intervals[min(level, len(intervals) - 1)]

    def update_progress_on_view(self, card_id):
        if not card_id: return
        progress = self.progress_data.setdefault(card_id, {"views": 0, "mastered": False, "errors": 0, "level": 0, "last_viewed_ts": 0, "next_review_ts": 0})
        progress["views"] = progress.get("views", 0) + 1; progress["last_viewed_ts"] = datetime.now().timestamp(); self.save_progress()

    def update_progress_on_correct(self, card_id):
        if not card_id: return False, datetime.now()
        progress = self.progress_data.setdefault(card_id, {"views": 0, "mastered": False, "errors": 0, "level": 0, "last_viewed_ts": 0, "next_review_ts": 0})
        progress["mastered"] = True; progress["level"] = progress.get("level", 0) + 1
        next_review_date = datetime.now() + timedelta(days=self.get_review_interval(progress["level"])); progress["next_review_ts"] = next_review_date.timestamp()
        self.update_list_item_icon(self.current_card_index, True); self.save_progress(); return True, next_review_date

    def update_progress_on_wrong(self, card_id):
        if not card_id: return
        progress = self.progress_data.setdefault(card_id, {"views": 0, "mastered": False, "errors": 0, "level": 0, "last_viewed_ts": 0, "next_review_ts": 0})
        progress["mastered"] = False; progress["errors"] = progress.get("errors", 0) + 1; progress["level"] = 0; progress["next_review_ts"] = 0
        self.update_list_item_icon(self.current_card_index, False); self.save_progress()
    def _on_persistent_setting_changed(self, key, value):
        """当用户更改任何可记忆的设置时，调用此方法以保存状态。"""
        self.parent_window.update_and_save_module_state('flashcard', key, value)