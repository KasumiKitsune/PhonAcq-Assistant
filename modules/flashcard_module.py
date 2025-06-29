# --- START OF FILE modules/flashcard_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "速记卡"
MODULE_DESCRIPTION = "使用图文、音频结合的方式进行学习和记忆，并自动记录学习进度。"
# ---

import os
import sys
import random
import threading
import importlib.util
import json
from datetime import datetime

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QMessageBox, QComboBox, QFormLayout, QGroupBox, QRadioButton, QLineEdit,
                             QStyle, QListWidgetItem, QApplication, QSpacerItem, QSizePolicy)
from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QPixmap, QImageReader, QIcon

try:
    import sounddevice as sd
    import soundfile as sf
    from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
    from thefuzz import fuzz
    DEPENDENCIES_MISSING = False
except ImportError as e:
    print(f"CRITICAL: flashcard_module.py - Missing dependencies: {e}")
    DEPENDENCIES_MISSING = True
    MISSING_ERROR_MESSAGE = str(e)

# --- 模块的创建入口 ---
def create_page(parent_window, ToggleSwitchClass, ScalableImageLabelClass, BASE_PATH, GLOBAL_TTS_DIR, GLOBAL_RECORD_DIR):
    if DEPENDENCIES_MISSING:
        error_page = QWidget()
        layout = QVBoxLayout(error_page)
        label = QLabel(f"速记卡模块加载失败：\n缺少必要的依赖库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install sounddevice soundfile PyQt5.QtMultimedia thefuzz")
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
                         GLOBAL_TTS_DIR, GLOBAL_RECORD_DIR)

class FlashcardPage(QWidget):
    def __init__(self, parent_window, ToggleSwitchClass, ScalableImageLabelClass, 
                 VISUAL_DIR, COMMON_DIR, TTS_DIR, PROGRESS_DIR, 
                 GLOBAL_TTS_DIR, GLOBAL_RECORD_DIR):
        super().__init__()
        self.parent_window = parent_window
        self.ToggleSwitch = ToggleSwitchClass
        self.ScalableImageLabel = ScalableImageLabelClass
        self.VISUAL_DIR = VISUAL_DIR; self.COMMON_DIR = COMMON_DIR
        self.TTS_DIR = TTS_DIR; self.PROGRESS_DIR = PROGRESS_DIR
        self.GLOBAL_TTS_DIR = GLOBAL_TTS_DIR; self.GLOBAL_RECORD_DIR = GLOBAL_RECORD_DIR
        self.session_active = False
        self.all_loaded_cards = []; self.cards = []
        self.current_card_index = -1; self.is_answer_shown = False
        self.current_wordlist_path = ""; self.current_wordlist_name_no_ext = ""
        self.current_wordlist_type = ""; self.progress_data = {}
        self.selected_mode_id = ""
        self.player = QMediaPlayer()
        self._init_ui()
        self._connect_signals()
        self.update_mode_options()

    def _init_ui(self):
        # [修改] 主布局现在是三栏式
        main_layout = QHBoxLayout(self)

        # =============================================
        # 第一栏 (左): 列表区
        # =============================================
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setFixedWidth(240)
        
        left_layout.addWidget(QLabel("项目列表:"))
        self.list_widget = QListWidget()
        self.list_widget.setWordWrap(True)
        self.list_widget.setSortingEnabled(False)
        left_layout.addWidget(self.list_widget, 1)

        # [修改] “标记掌握”按钮回到左侧布局底部
        self.mark_mastered_btn = QPushButton("标记/取消掌握")
        left_layout.addWidget(self.mark_mastered_btn)

        # =============================================
        # 第二栏 (中): 卡片展示区
        # =============================================
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)

        self.card_question_area = self.ScalableImageLabel("请从右侧加载词表开始学习")
        self.card_question_area.setObjectName("FlashcardQuestionArea")
        self.card_answer_area = self.ScalableImageLabel("")
        self.card_answer_area.setObjectName("FlashcardAnswerArea")
        self.card_answer_area.setAlignment(Qt.AlignCenter)
        self.card_answer_area.setWordWrap(True)
        self.progress_label = QLabel("卡片: - / -")
        self.progress_label.setAlignment(Qt.AlignCenter)
        
        self.answer_input = QLineEdit()
        self.answer_input.setPlaceholderText("在此输入答案...")
        self.answer_submit_btn = QPushButton("提交答案")
        self.answer_input_widget = QWidget()
        answer_input_layout = QHBoxLayout(self.answer_input_widget)
        answer_input_layout.setContentsMargins(0,0,0,0)
        answer_input_layout.addWidget(self.answer_input)
        answer_input_layout.addWidget(self.answer_submit_btn)
        self.answer_input_widget.hide()

        # [修改] 中间底部导航/操作栏
        center_bottom_bar = QWidget()
        center_bottom_layout = QHBoxLayout(center_bottom_bar)
        self.prev_btn = QPushButton("上一个")
        self.show_answer_btn = QPushButton("显示/隐藏答案")
        self.next_btn = QPushButton("下一个")
        self.play_audio_btn = QPushButton("播放音频")
        
        center_bottom_layout.addStretch() # 左侧弹簧
        center_bottom_layout.addWidget(self.prev_btn)
        center_bottom_layout.addWidget(self.show_answer_btn)
        center_bottom_layout.addWidget(self.next_btn)
        center_bottom_layout.addWidget(self.play_audio_btn)
        center_bottom_layout.addStretch() # 右侧弹簧，实现居中

        center_layout.addWidget(self.card_question_area, 1)
        center_layout.addWidget(self.card_answer_area)
        center_layout.addWidget(self.answer_input_widget)
        center_layout.addWidget(self.progress_label)
        center_layout.addWidget(center_bottom_bar) # 添加居中的底部操作栏

        # =============================================
        # 第三栏 (右): 控制区
        # =============================================
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_panel.setFixedWidth(300)

        source_group = QGroupBox("1. 选择词表")
        source_layout = QFormLayout(source_group)
        self.wordlist_combo = QComboBox()
        source_layout.addRow("词表文件:", self.wordlist_combo)
        
        mode_group = QGroupBox("2. 选择模式")
        self.mode_layout = QVBoxLayout(mode_group)
        
        options_group = QGroupBox("3. 学习选项")
        options_layout = QVBoxLayout(options_group)
        
        self.order_mode_group = QGroupBox("卡片顺序")
        order_layout = QVBoxLayout()
        self.smart_random_radio = QRadioButton("智能随机 (推荐)")
        self.smart_random_radio.setChecked(True)
        self.random_radio = QRadioButton("完全随机")
        self.sequential_radio = QRadioButton("按列表顺序")
        order_layout.addWidget(self.smart_random_radio)
        order_layout.addWidget(self.random_radio)
        order_layout.addWidget(self.sequential_radio)
        self.order_mode_group.setLayout(order_layout)
        
        autoplay_layout = QHBoxLayout()
        autoplay_layout.addWidget(QLabel("自动播放音频:"))
        self.autoplay_audio_switch = self.ToggleSwitch()
        self.autoplay_audio_switch.setChecked(True)
        autoplay_layout.addWidget(self.autoplay_audio_switch)
        autoplay_layout.addStretch()

        hide_list_layout = QHBoxLayout()
        hide_list_layout.addWidget(QLabel("学习时隐藏列表:"))
        self.hide_list_switch = self.ToggleSwitch()
        self.hide_list_switch.setChecked(True)
        hide_list_layout.addWidget(self.hide_list_switch)
        hide_list_layout.addStretch()

        options_layout.addWidget(self.order_mode_group)
        options_layout.addLayout(autoplay_layout)
        options_layout.addLayout(hide_list_layout)
        
        self.clear_progress_btn = QPushButton("清空当前词表学习记录")
        self.clear_progress_btn.setObjectName("ActionButton_Delete")
        self.start_reset_btn = QPushButton("加载词表并开始学习")
        self.start_reset_btn.setObjectName("AccentButton")
        self.start_reset_btn.setFixedHeight(40)
        
        right_layout.addWidget(source_group)
        right_layout.addWidget(mode_group)
        right_layout.addWidget(options_group)
        right_layout.addStretch()
        right_layout.addWidget(self.clear_progress_btn)
        right_layout.addWidget(self.start_reset_btn)

        # 组装三栏布局
        main_layout.addWidget(left_panel)
        main_layout.addWidget(center_panel, 1)
        main_layout.addWidget(right_panel)
        
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

    def populate_wordlists(self):
        self.wordlist_combo.clear(); self.wordlist_combo.addItem("--- 请选择一个词表 ---", userData=None)
        if os.path.exists(self.VISUAL_DIR):
            for f in sorted(os.listdir(self.VISUAL_DIR)):
                if f.endswith('.py'): self.wordlist_combo.addItem(f"[图文] {f}", userData=("visual", f))
        if os.path.exists(self.COMMON_DIR):
            for f in sorted(os.listdir(self.COMMON_DIR)):
                 if f.endswith('.py'): self.wordlist_combo.addItem(f"[标准] {f}", userData=("common", f))

    def update_mode_options(self, index=0):
        while self.mode_layout.count():
            child = self.mode_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        self.mode_buttons = []
        user_data = self.wordlist_combo.currentData()
        if not user_data: return
        list_type, _ = user_data
        if list_type == "visual":
            self.add_mode_button("看图记词", "image_to_text"); self.add_mode_button("看词记图", "text_to_image")
        elif list_type == "common":
            self.add_mode_button("看词记音", "word_to_sound"); self.add_mode_button("听音记词", "sound_to_word")
        if self.mode_buttons: self.mode_buttons[0].setChecked(True)

    def add_mode_button(self, text, mode_id):
        radio_btn = QRadioButton(text); radio_btn.setProperty("mode_id", mode_id)
        self.mode_layout.addWidget(radio_btn); self.mode_buttons.append(radio_btn)
        
    def handle_start_reset(self):
        if not self.session_active: self.start_session()
        else: self.reset_session()
            
    def start_session(self):
        user_data = self.wordlist_combo.currentData()
        if not user_data: QMessageBox.warning(self, "错误", "请先选择一个有效的词表文件。"); return
        self.current_wordlist_type, wordlist_file = user_data
        self.selected_mode_id = next((btn.property("mode_id") for btn in self.mode_buttons if btn.isChecked()), None)
        if not self.selected_mode_id: QMessageBox.warning(self, "错误", "请选择一个学习模式。"); return
        try:
            self.load_and_adapt_data(wordlist_file, self.selected_mode_id)
            self.load_progress(wordlist_file)
        except Exception as e: QMessageBox.critical(self, "加载失败", f"无法加载或解析词表文件:\n{e}"); return
        if not self.all_loaded_cards: QMessageBox.information(self, "无内容", "词表中没有可用的学习项目。"); return
        self.session_active = True
        self.current_wordlist_name_no_ext = os.path.splitext(wordlist_file)[0]
        self._generate_card_order()
        self.update_list_widget()
        self.start_reset_btn.setText("结束学习会话"); self.wordlist_combo.setEnabled(False); self.order_mode_group.setEnabled(False); self.hide_list_switch.setEnabled(False); self.clear_progress_btn.setEnabled(False)
        if self.hide_list_switch.isChecked(): self.list_widget.hide()
        if self.cards:
            self.current_card_index = -1; self.list_widget.setCurrentRow(0)
        else:
            self.card_question_area.set_pixmap(None); self.card_question_area.setText("所有卡片均已掌握并通过筛选！\n请尝试其他模式或重置进度。"); self.progress_label.setText("太棒了！")

    def reset_session(self):
        if self.session_active: self.save_progress()
        self.session_active = False; self.cards.clear(); self.all_loaded_cards.clear(); self.list_widget.clear()
        self.card_question_area.set_pixmap(None); self.card_question_area.setText("请从左侧加载词表开始学习")
        self.card_answer_area.set_pixmap(None); self.card_answer_area.setText("")
        self.progress_label.setText("卡片: - / -"); self.progress_data.clear()
        self.list_widget.show(); self.start_reset_btn.setText("加载词表并开始学习"); self.wordlist_combo.setEnabled(True); self.order_mode_group.setEnabled(True); self.hide_list_switch.setEnabled(True); self.clear_progress_btn.setEnabled(True)
        self.answer_input_widget.hide()

    def load_and_adapt_data(self, filename, mode):
        self.all_loaded_cards.clear()
        base_dir = self.VISUAL_DIR if self.current_wordlist_type == "visual" else self.COMMON_DIR
        self.current_wordlist_path = os.path.join(base_dir, filename)
        spec = importlib.util.spec_from_file_location("flashcard_data", self.current_wordlist_path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

        if self.current_wordlist_type == "visual":
            for item in module.ITEMS:
                correct_answer_text = item.get('id', '') # [修复] 正确答案是id
                card = {'id': item.get('id', ''), 'image_path': item.get('image_path', ''), 'text': item.get('prompt_text', ''), 'notes': item.get('notes', ''), 'correct_answer': correct_answer_text}
                if mode == "image_to_text": card['question'], card['answer'] = card['image_path'], f"答案: {card['id']}\n({card['text']})"
                else: card['question'], card['answer'] = card['text'], card['image_path']
                self.all_loaded_cards.append(card)
        else:
            for group in module.WORD_GROUPS:
                for word, value in group.items():
                    ipa = value[0] if isinstance(value, tuple) else str(value)
                    correct_answer_text = word
                    card = {'id': word, 'text': word, 'notes': ipa, 'correct_answer': correct_answer_text}
                    if mode == "word_to_sound": card['question'], card['answer'] = word, ipa
                    else: card['question'], card['answer'] = "???" , f"{word}\n({ipa})"
                    self.all_loaded_cards.append(card)
    
    def _generate_card_order(self):
        source_cards = list(self.all_loaded_cards)
        if self.smart_random_radio.isChecked():
            remaining_cards = []
            for card in source_cards:
                progress = self.progress_data.get(card.get('id'), {}); views = progress.get("views", 0); mastered = progress.get("mastered", False)
                if mastered:
                    disappear_prob = min(0.95, views / 20.0)
                    if random.random() < disappear_prob: continue
                remaining_cards.append(card)
            if not remaining_cards: self.cards = []; return
            weights = [1 if self.progress_data.get(card.get('id'), {}).get("mastered", False) else 10 + self.progress_data.get(card.get('id'), {}).get("views", 0) * 2 for card in remaining_cards]
            temp_cards = list(remaining_cards); temp_weights = list(weights); sorted_cards = []
            while temp_cards:
                total_weight = sum(temp_weights)
                if total_weight == 0: chosen_index = random.randrange(len(temp_cards))
                else:
                    r = random.uniform(0, total_weight); chosen_index = 0
                    for i, w in enumerate(temp_weights):
                        r -= w
                        if r <= 0: chosen_index = i; break
                sorted_cards.append(temp_cards.pop(chosen_index)); temp_weights.pop(chosen_index)
            self.cards = sorted_cards
        elif self.random_radio.isChecked():
            random.shuffle(source_cards); self.cards = source_cards
        else: self.cards = source_cards

    def update_card_display(self):
        if not self.session_active or self.current_card_index < 0 or self.current_card_index >= len(self.cards): return
        card = self.cards[self.current_card_index]
        self.is_answer_shown = False 
        question_data = card.get('question', '')
        self.display_content(self.card_question_area, question_data)
        
        self.card_answer_area.set_pixmap(None); self.card_answer_area.setText(""); self.card_answer_area.hide()
        
        # [修复] 根据模式切换答案输入框和“显示答案”按钮的可见性
        if self.selected_mode_id in ["sound_to_word", "image_to_text"]:
            self.answer_input.clear(); self.answer_input_widget.show(); self.answer_input.setFocus(); self.show_answer_btn.hide()
        else:
            self.answer_input_widget.hide(); self.show_answer_btn.show()

        self.progress_label.setText(f"卡片: {self.current_card_index + 1} / {len(self.cards)}")
        card_id = card.get('id')
        if card_id:
            if card_id not in self.progress_data: self.progress_data[card_id] = {"views": 0, "mastered": False}
            self.progress_data[card_id]["views"] += 1
            self.save_progress()
        if self.autoplay_audio_switch.isChecked(): self.play_current_audio()
            
    def display_content(self, widget, content):
        is_path = isinstance(content, str) and (content.lower().endswith(('.png', '.jpg', '.jpeg')))
        if is_path:
            base_dir = os.path.dirname(self.current_wordlist_path)
            full_path = os.path.join(base_dir, content)
            pixmap = QPixmap(full_path) if os.path.exists(full_path) else QPixmap()
            if isinstance(widget, self.ScalableImageLabel):
                if not pixmap.isNull(): widget.set_pixmap(pixmap)
                else: widget.set_pixmap(None); widget.setText(f"图片未找到:\n{content}")
            else:
                if not pixmap.isNull(): widget.setPixmap(pixmap.scaled(widget.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                else: widget.setText(f"图片未找到:\n{content}")
        else:
            if isinstance(widget, self.ScalableImageLabel): widget.set_pixmap(None)
            widget.setText(str(content))
            
    def toggle_answer(self):
        if not self.session_active or self.current_card_index < 0: return
        self.is_answer_shown = not self.is_answer_shown
        if self.is_answer_shown:
            card = self.cards[self.current_card_index]; answer_data = card.get('answer', '')
            self.display_content(self.card_answer_area, answer_data); self.card_answer_area.show()
        else: self.card_answer_area.hide()

    def _normalize_string(self, text): return str(text).lower().replace("_", "").replace(" ", "").strip()
            
    def check_answer(self):
        if not self.session_active or self.current_card_index < 0: return
        card = self.cards[self.current_card_index]
        user_input = self.answer_input.text().strip()
        correct_answer = card.get('correct_answer', '').strip()
        if not user_input: QMessageBox.warning(self, "输入为空", "请输入您的答案。"); return
        
        similarity = fuzz.ratio(self._normalize_string(user_input), self._normalize_string(correct_answer))
        
        is_mastered_by_check = False
        auto_advance_delay = -1

        if similarity >= 90:
            QMessageBox.information(self, "答案正确", f"完美匹配！相似度 {similarity}%。")
            is_mastered_by_check = True; auto_advance_delay = 800 # 0.8秒后自动跳转
        elif similarity >= 70:
            QMessageBox.information(self, "答案检查结果", f"非常接近！相似度 {similarity}%。\n正确答案是：{correct_answer}")
            is_mastered_by_check = True; auto_advance_delay = 0 # 点击确定后立即跳转
        else:
            QMessageBox.warning(self, "答案不正确", f"答案不正确。相似度 {similarity}%。\n正确答案是：{correct_answer}")

        self.is_answer_shown = True
        self.display_content(self.card_answer_area, card.get('answer', '')); self.card_answer_area.show()
        
        card_id = card.get('id')
        if card_id:
            if card_id not in self.progress_data: self.progress_data[card_id] = {"views": 0, "mastered": False}
            if is_mastered_by_check: self.progress_data[card_id]["mastered"] = True
            self.update_list_item_icon(self.current_card_index, self.progress_data[card_id]["mastered"])
            self.save_progress()
        
        self.answer_input.clear()
        if auto_advance_delay >= 0:
            QTimer.singleShot(auto_advance_delay, self.show_next_card)

    def play_current_audio(self):
        if not self.session_active or self.current_card_index < 0: return
        card = self.cards[self.current_card_index]; audio_key = card.get('id')
        paths_to_check = []
        for ext in ['.wav', '.mp3']: paths_to_check.append(os.path.join(self.GLOBAL_RECORD_DIR, self.current_wordlist_name_no_ext, f"{audio_key}{ext}"))
        paths_to_check.append(os.path.join(self.TTS_DIR, self.current_wordlist_name_no_ext, f"{audio_key}.mp3"))
        paths_to_check.append(os.path.join(self.GLOBAL_TTS_DIR, self.current_wordlist_name_no_ext, f"{audio_key}.mp3"))
        final_path = next((path for path in paths_to_check if os.path.exists(path)), None)
        if final_path:
            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(final_path))); self.player.play()
        else: self.parent_window.statusBar().showMessage(f"找不到 '{audio_key}' 的音频文件", 2000)

    def show_prev_card(self):
        if not self.session_active or self.current_card_index <= 0: return
        self.list_widget.setCurrentRow(self.current_card_index - 1)

    def show_next_card(self):
        if not self.session_active or self.current_card_index >= len(self.cards) - 1:
            QMessageBox.information(self, "完成", "您已完成本轮所有卡片的学习！")
            self.reset_session()
            return
        self.list_widget.setCurrentRow(self.current_card_index + 1)
        
    def jump_to_card(self, row):
        if not self.session_active or row == -1 or row == self.current_card_index: return
        self.current_card_index = row; self.update_card_display()

    def toggle_mastered_status(self):
        if not self.session_active or self.current_card_index == -1: return
        card_id = self.cards[self.current_card_index].get('id')
        if not card_id: return
        if card_id not in self.progress_data: self.progress_data[card_id] = {"views": 0, "mastered": False}
        is_mastered = self.progress_data[card_id].get("mastered", False)
        self.progress_data[card_id]["mastered"] = not is_mastered
        self.update_list_item_icon(self.current_card_index, not is_mastered)
        self.save_progress()

    def clear_current_progress(self):
        user_data = self.wordlist_combo.currentData()
        if not user_data: QMessageBox.warning(self, "操作无效", "请先选择一个词表。"); return
        _, wordlist_file = user_data
        progress_file = os.path.join(self.PROGRESS_DIR, f"{wordlist_file}.json")
        reply = QMessageBox.question(self, "清空学习记录", f"您确定要清空词表 '{wordlist_file}' 的所有学习记录吗？\n此操作不可撤销！", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            if os.path.exists(progress_file):
                try:
                    os.remove(progress_file)
                    self.progress_data = {}
                    QMessageBox.information(self, "成功", f"词表 '{wordlist_file}' 的学习记录已清空。")
                    if self.session_active: self.reset_session()
                except Exception as e: QMessageBox.critical(self, "错误", f"清空学习记录失败: {e}")
            else: QMessageBox.information(self, "提示", f"词表 '{wordlist_file}' 尚无学习记录。")

    def update_list_widget(self):
        self.list_widget.clear()
        for i, card in enumerate(self.cards):
            item = QListWidgetItem(card['id'])
            self.list_widget.addItem(item)
            is_mastered = self.progress_data.get(card['id'], {}).get("mastered", False)
            self.update_list_item_icon(i, is_mastered)

    def update_list_item_icon(self, row, is_mastered):
        item = self.list_widget.item(row)
        if item:
            if is_mastered: item.setIcon(QApplication.style().standardIcon(QStyle.SP_DialogApplyButton))
            else: item.setIcon(QIcon())

    def load_progress(self, wordlist_file):
        progress_file = os.path.join(self.PROGRESS_DIR, f"{wordlist_file}.json")
        if os.path.exists(progress_file):
            try:
                with open(progress_file, 'r', encoding='utf-8') as f: self.progress_data = json.load(f)
            except (json.JSONDecodeError, IOError): self.progress_data = {}
        else: self.progress_data = {}

    def save_progress(self):
        if not self.session_active: return
        user_data = self.wordlist_combo.currentData()
        if not user_data: return
        _, wordlist_file = user_data
        progress_file = os.path.join(self.PROGRESS_DIR, f"{wordlist_file}.json")
        try:
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(self.progress_data, f, indent=4, ensure_ascii=False)
        except IOError as e: print(f"无法保存进度文件 '{progress_file}': {e}")