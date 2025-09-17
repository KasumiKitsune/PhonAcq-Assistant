# --- START OF FILE modules/accent_collection_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "标准朗读采集"
MODULE_DESCRIPTION = "进行标准的文本到语音实验，适用于朗读任务、最小音对测试、句子复述等场景。"
# ---

import os
import threading
import queue
import time
import random
import sys
import json
import subprocess
from collections import deque
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget,
                             QTableWidgetItem, QMessageBox, QComboBox, QFormLayout,
                             QGroupBox, QProgressBar, QStyle, QLineEdit, QHeaderView,
                             QAbstractItemView, QMenu, QToolButton, QWidgetAction, QDialogButtonBox, QDialog, QCheckBox, QSlider, QSpinBox)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, pyqtProperty, QPoint
from PyQt5.QtGui import QPainter, QPen, QColor, QPalette
from modules.custom_widgets_module import WordlistSelectionDialog

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
# --- [新增] 本地化的波形可视化控件 ---
class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(40)
        self._waveform_data = None
        
        # [新增] 为QSS定义颜色属性和默认值
        self._waveformColor = self.palette().color(QPalette.Highlight)
        self._cursorColor = QColor("red") # 虽然QSS会覆盖，但提供一个默认值
        self._selectionColor = QColor(0, 100, 255, 60) # 同上

    # --- [新增] 定义pyqtProperty，暴露给QSS ---
    @pyqtProperty(QColor)
    def waveformColor(self):
        return self._waveformColor

    @waveformColor.setter
    def waveformColor(self, color):
        if self._waveformColor != color:
            self._waveformColor = color
            self.update()

    @pyqtProperty(QColor)
    def cursorColor(self):
        return self._cursorColor

    @cursorColor.setter
    def cursorColor(self, color):
        if self._cursorColor != color:
            self._cursorColor = color
            self.update()

    @pyqtProperty(QColor)
    def selectionColor(self):
        return self._selectionColor

    @selectionColor.setter
    def selectionColor(self, color):
        if self._selectionColor != color:
            self._selectionColor = color
            self.update()
    # --- 结束新增 ---

    def set_waveform_data(self, audio_filepath):
        # ... 此方法保持原样，无需修改 ...
        self._waveform_data = None
        if not (audio_filepath and os.path.exists(audio_filepath)):
            self.update()
            return

        try:
            data, sr = sf.read(audio_filepath, dtype='float32')
            if data.ndim > 1: data = data.mean(axis=1)
            num_samples = len(data)
            target_points = self.width() * 2 if self.width() > 0 else 400
            if num_samples <= target_points: self._waveform_data = data
            else:
                step = num_samples // target_points
                peak_data = [np.max(np.abs(data[i:i+step])) for i in range(0, num_samples, step)]
                self._waveform_data = np.array(peak_data)
        except Exception as e:
            print(f"Error loading waveform for {os.path.basename(audio_filepath)}: {e}")
            self._waveform_data = None
        self.update()

    def paintEvent(self, event):
        # ... 此方法也需要更新以使用新属性 ...
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        bg_color = self.palette().color(QPalette.Base)
        painter.fillRect(self.rect(), bg_color)
        
        if self._waveform_data is None or len(self._waveform_data) == 0:
            return

        # [修改] 使用新的颜色属性进行绘制
        pen = QPen(self._waveformColor, 1)
        painter.setPen(pen)

        h = self.height(); half_h = h / 2; w = self.width(); num_points = len(self._waveform_data)
        max_val = np.max(self._waveform_data)
        if max_val == 0: max_val = 1.0
        for i, val in enumerate(self._waveform_data):
            x = int(i * w / num_points); y_offset = (val / max_val) * half_h
            painter.drawLine(x, int(half_h - y_offset), x, int(half_h + y_offset))

# ===== 标准化模块入口函数 =====
def create_page(parent_window, config, ToggleSwitchClass, WorkerClass, LoggerClass,
                detect_language_func, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH, icon_manager, resolve_device_func): # <-- 新增 resolve_device_func
    if DEPENDENCIES_MISSING:
        # ... (错误页面逻辑不变) ...
        error_page = QWidget(); layout = QVBoxLayout(error_page)
        label = QLabel(f"标准朗读采集模块加载失败：\n缺少必要的依赖库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install sounddevice soundfile numpy gtts")
        label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); layout.addWidget(label)
        return error_page

    # [修改] 将 resolve_device_func 传递给构造函数
    return AccentCollectionPage(parent_window, config, ToggleSwitchClass, WorkerClass, LoggerClass,
                                detect_language_func, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH, icon_manager, resolve_device_func)


class AccentCollectionPage(QWidget):
    recording_device_error_signal = pyqtSignal(str)

    def __init__(self, parent_window, config, ToggleSwitchClass, WorkerClass, LoggerClass,
                 detect_language_func, WORD_LIST_DIR, AUDIO_RECORD_DIR, AUDIO_TTS_DIR, BASE_PATH, icon_manager, resolve_device_func): # <-- 新增 resolve_device_func
        super().__init__()
        self.parent_window = parent_window; self.config = config; self.ToggleSwitch = ToggleSwitchClass; self.Worker = WorkerClass
        self.Logger = LoggerClass; self.icon_manager = icon_manager; self.detect_language = detect_language_func
        self.resolve_device_func = resolve_device_func # [新增] 保存解析函数
        self.WORD_LIST_DIR = WORD_LIST_DIR; self.AUDIO_RECORD_DIR = AUDIO_RECORD_DIR; self.AUDIO_TTS_DIR = AUDIO_TTS_DIR; self.BASE_PATH = BASE_PATH
        self.session_active = False; self.is_recording = False; self.current_word_list = []; self.current_word_index = -1
        self.current_wordlist_name = "" 
        self.settings_dialog = None
        self.audio_queue = queue.Queue(); self.volume_meter_queue = queue.Queue(maxsize=2)
        self.volume_history = deque(maxlen=5)
        self.recording_thread = None
        self.session_stop_event = threading.Event(); self.logger = None
        self.is_follow_up_active = False # 当前词条是否处于跟读模式
        self.follow_up_repetitions_left = 0
        self.last_audio_chunk_time = 0
        self.is_speaking = False
        # --- [新增] 用于会话中的临时跟读设置 ---
        self.session_follow_up_enabled = False
        self.session_repetition_count = 5
        self.update_timer = None 
        self.prompt_mode = 'tts' # 默认提示音模式
        self.pinned_wordlists = []
        self.beep_sound_path = os.path.join(self.BASE_PATH, "assets", "audio", "beep_prompt.wav")
        self.next_word_sound_path = os.path.join(self.BASE_PATH, "assets", "audio", "next_word_prompt.wav")
        self._init_ui(); self._connect_signals(); self.update_icons(); self.reset_ui(); self.apply_layout_settings()
        self.load_config_and_prepare()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        left_layout = QVBoxLayout()
        
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)

        # [修改] 使用 QTableWidget 替换 QListWidget
        self.list_widget = QTableWidget()
        self.list_widget.setColumnCount(3)
        self.list_widget.setHorizontalHeaderLabels(["词语", "IPA/备注", "波形预览"])
        self.list_widget.verticalHeader().setVisible(False)
        self.list_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setWordWrap(True)
        
        header = self.list_widget.horizontalHeader()
        # [修改] 设置为 Interactive 以允许用户自由拖动
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        
        # [新增] 使用 setStretchLastSection 来确保表格填满宽度
        # 这通常是默认行为，但明确设置一下更保险
        self.list_widget.horizontalHeader().setStretchLastSection(True)

        # [修改] 在拥有有效宽度后设置初始比例
        # 我们不能在_init_ui中立即设置，因为此时控件宽度可能为0。
        # 一个好的做法是在第一次显示或调整大小时设置。
        # 为了简单起见，我们可以在这里设置一个初始的、非零的宽度，
        # 或者更好地，在 resizeEvent 中处理。但对于初始比例，直接设置宽度是可行的。
        # 我们将在`resizeEvent`中处理，这里先移除旧代码。

        self.list_widget.setToolTip("当前会话需要录制的所有词语。\n绿色对勾表示已录制。\n双击可重听提示音。")
        self.status_label = QLabel("状态：准备就绪")
        self.progress_bar = QProgressBar(); self.progress_bar.setVisible(False)
        # [核心修改] 将 QLabel 赋值给 self.list_label
        self.list_label = QLabel("测试词语列表:")
        
        # [核心修改] 使用 self.list_label 添加到布局中
        left_layout.addWidget(self.list_label)
        left_layout.addWidget(self.list_widget)
        left_layout.addWidget(self.status_label)
        left_layout.addWidget(self.progress_bar)

        right_panel_group = QGroupBox("控制面板")
        self.right_layout_container = QVBoxLayout(right_panel_group)

        self.pre_session_widget = QWidget()
        # [核心修改] 不再使用 QFormLayout，改用更灵活的 QVBoxLayout
        pre_session_layout = QVBoxLayout(self.pre_session_widget)
        pre_session_layout.setContentsMargins(11, 0, 11, 0)
        pre_session_layout.setSpacing(10) # 增加垂直间距

        # --- 词表选择部分 ---
        wordlist_label = QLabel("选择单词表:")
        self.word_list_select_btn = QPushButton("请选择单词表...")
        self.word_list_select_btn.setToolTip("点击选择一个用于本次采集任务的单词表文件。")
        self.word_list_select_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        
        # --- 被试者名称部分 ---
        participant_label = QLabel("被试者名称:")
        self.participant_input = QLineEdit()
        self.participant_input.setToolTip("输入被试者的唯一标识符。\n此名称将用于创建结果文件夹，例如 'participant_1'。")
        
        # --- 开始会话按钮 ---
        self.start_session_btn = QPushButton("开始新会话")
        self.start_session_btn.setObjectName("AccentButton")
        self.start_session_btn.setToolTip("加载选定的单词表，检查/生成提示音，并开始一个新的采集会话。")
        
        # [核心修改] 将控件按新的布局方式添加到 QVBoxLayout 中
        pre_session_layout.addWidget(wordlist_label)
        pre_session_layout.addWidget(self.word_list_select_btn)
        pre_session_layout.addWidget(participant_label)
        pre_session_layout.addWidget(self.participant_input)
        pre_session_layout.addStretch() # 添加一个弹簧，将开始按钮推到底部
        pre_session_layout.addWidget(self.start_session_btn)

        self.in_session_widget = QWidget()
        in_session_layout = QVBoxLayout(self.in_session_widget)
        mode_group = QGroupBox("会话模式")
        mode_layout = QFormLayout(mode_group)
        self.random_switch = self.ToggleSwitch(); self.random_switch.setToolTip("开启后，将打乱词表中所有词语的顺序进行呈现。")
        self.full_list_switch = self.ToggleSwitch(); self.full_list_switch.setToolTip("开启后，将使用词表中的所有词语。\n关闭后，将只从每个组别中随机抽取一个词语。")
        random_layout = QHBoxLayout(); random_layout.addWidget(QLabel("顺序")); random_layout.addWidget(self.random_switch); random_layout.addWidget(QLabel("随机"))
        full_list_layout = QHBoxLayout(); full_list_layout.addWidget(QLabel("部分")); full_list_layout.addWidget(self.full_list_switch); full_list_layout.addWidget(QLabel("完整"))
        mode_layout.addRow(random_layout); mode_layout.addRow(full_list_layout)
        self.end_session_btn = QPushButton("结束当前会话")
        self.end_session_btn.setObjectName("ActionButton_Delete")
        self.end_session_btn.setToolTip("提前结束当前的采集会话。")
        in_session_layout.addWidget(mode_group)
        in_session_layout.addWidget(self.end_session_btn)
        # --- [新增] 智能跟读的临时设置面板 ---
        self.session_follow_up_group = QGroupBox("智能跟读 (临时设置)")
        session_follow_up_layout = QFormLayout(self.session_follow_up_group)
        
        # 使用 ToggleSwitch 保持UI一致性
        self.session_follow_up_switch = self.ToggleSwitch()
        self.session_follow_up_switch.setToolTip("临时开启或关闭本会话的智能跟读功能。")
        
        # [核心修改] 将 QSpinBox 替换为 QSlider
        slider_layout = QHBoxLayout()
        self.session_repetition_slider = QSlider(Qt.Horizontal)
        self.session_repetition_slider.setRange(2, 30) # 设置范围为 2-30
        
        self.session_repetition_label = QLabel("5 次") # 用于显示滑块当前值
        self.session_repetition_label.setFixedWidth(40) # 固定宽度防止布局跳动
        self.session_repetition_label.setAlignment(Qt.AlignCenter)
        
        slider_layout.addWidget(self.session_repetition_slider)
        slider_layout.addWidget(self.session_repetition_label)
        
        session_follow_up_layout.addRow("启用跟读:", self.session_follow_up_switch)
        session_follow_up_layout.addRow("跟读次数:", slider_layout)
        
        in_session_layout.addWidget(self.session_follow_up_group)
        # --- 新增结束 ---
        self.skip_repetitions_btn = QPushButton("完成本词跟读")
        self.skip_repetitions_btn.setObjectName("AccentButton_Alternative")
        self.skip_repetitions_btn.setToolTip("提前结束当前词语的跟读循环，并进入下一个词。")
        self.skip_repetitions_btn.hide() # 默认隐藏
        in_session_layout.addWidget(self.skip_repetitions_btn)
        
        self.right_layout_container.addWidget(self.pre_session_widget)
        self.right_layout_container.addWidget(self.in_session_widget)

        self.recording_status_panel = QGroupBox("录音状态")
        status_panel_layout = QVBoxLayout(self.recording_status_panel)
        self.recording_indicator = QLabel("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_label = QLabel("当前音量:")
        self.volume_meter = QProgressBar(); self.volume_meter.setRange(0, 100); self.volume_meter.setValue(0); self.volume_meter.setTextVisible(False)
        status_panel_layout.addWidget(self.recording_indicator); status_panel_layout.addWidget(self.volume_label); status_panel_layout.addWidget(self.volume_meter)
        self.update_timer = QTimer(); self.update_timer.timeout.connect(self.update_volume_meter)
        
        self.record_btn = QPushButton("开始录制下一个")
        self.replay_btn = QPushButton("重听当前音频")
        self.replay_btn.setToolTip("重新播放当前选中词语的提示音 (可双击列表项触发)。")
        
        right_layout.addWidget(right_panel_group)
        right_layout.addStretch()
        right_layout.addWidget(self.recording_status_panel)
        right_layout.addWidget(self.record_btn)
        right_layout.addWidget(self.replay_btn)
        
        main_layout.addLayout(left_layout, 2)
        main_layout.addWidget(self.right_panel, 1)

    def _show_placeholder_message(self, text):
        """
        [新增] 清空表格并显示一条居中的、非交互的提示信息。
        """
        self.list_widget.setRowCount(0)
        self.list_widget.setRowCount(1)

        placeholder_item = QTableWidgetItem(text)
        placeholder_item.setTextAlignment(Qt.AlignCenter)
        placeholder_item.setForeground(self.palette().color(QPalette.Disabled, QPalette.Text))
        # 设置为不可选中、不可编辑
        placeholder_item.setFlags(Qt.ItemIsEnabled)

        self.list_widget.setItem(0, 0, placeholder_item)
        # 将单元格横跨所有列
        self.list_widget.setSpan(0, 0, 1, self.list_widget.columnCount())
        # 对于占位符，隐藏行号
        self.list_widget.verticalHeader().setVisible(False)
        # 自动调整行高以适应可能换行的文本
        self.list_widget.resizeRowsToContents()

    def _preview_wordlist(self, wordlist_rel_path):
        """
        [v1.1 - Fix] 加载指定的词表文件，并在左侧表格中显示其内容的预览。
        现在将文件名作为参数直接传递给加载逻辑。
        """
        try:
            # [核心修复] 将接收到的 wordlist_rel_path 直接传递给加载函数
            word_groups = self.load_word_list_logic(filename=wordlist_rel_path)
            
            # --- (后续的预览列表填充逻辑保持不变) ---
            preview_list = []
            for group in word_groups:
                for word, value in group.items():
                    ipa_or_note = value[0] if isinstance(value, tuple) else str(value)
                    preview_list.append({'word': word, 'ipa': ipa_or_note})
            
            self.list_widget.setRowCount(0)
            self.list_widget.setRowCount(len(preview_list))
            for i, item_data in enumerate(preview_list):
                word_item = QTableWidgetItem(item_data['word'])
                ipa_item = QTableWidgetItem(item_data['ipa'])
                word_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                ipa_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.list_widget.setItem(i, 0, word_item)
                self.list_widget.setItem(i, 1, ipa_item)
                self.list_widget.setCellWidget(i, 2, None)

            self.list_widget.resizeRowsToContents()
            self.list_widget.verticalHeader().setVisible(True)
            self.list_label.setText("测试词语列表: (预览)")

        except Exception as e:
            self._show_placeholder_message(f"加载词表预览失败:\n{e}")
            self.list_label.setText("测试词语列表:")

    def resizeEvent(self, event):
        """
        在窗口大小改变时，重新计算并设置列宽以保持2:1:1的比例。
        """
        super().resizeEvent(event)
        
        # 减去垂直滚动条和表头的宽度，以获得可用的内容区域宽度
        header_width = self.list_widget.verticalHeader().width()
        scrollbar_width = self.list_widget.verticalScrollBar().width() if self.list_widget.verticalScrollBar().isVisible() else 0
        available_width = self.list_widget.viewport().width() - header_width - scrollbar_width
        
        if available_width > 0:
            # 分配宽度，确保总和等于可用宽度
            width1 = int(available_width * 0.5)
            width2 = int(available_width * 0.25)
            # 最后一列使用剩余的所有空间，避免四舍五入导致空隙
            width3 = available_width - width1 - width2
            
            self.list_widget.setColumnWidth(0, width1)
            self.list_widget.setColumnWidth(1, width2)
            self.list_widget.setColumnWidth(2, width3)

    def _connect_signals(self):
        self.word_list_select_btn.clicked.connect(self.open_wordlist_selector)
        self.word_list_select_btn.customContextMenuRequested.connect(self.show_wordlist_button_context_menu)
        self.start_session_btn.clicked.connect(self.handle_start_session_click)
        self.end_session_btn.clicked.connect(self.end_session)
        self.record_btn.clicked.connect(self.handle_record_button)
        self.replay_btn.clicked.connect(self.replay_audio)
        self.list_widget.itemSelectionChanged.connect(self.on_list_item_changed)
        self.list_widget.cellDoubleClicked.connect(self.on_cell_double_clicked)
        
        # [修改] 将原始连接重定向到新的持久化槽函数
        # self.random_switch.stateChanged.connect(self.on_session_mode_changed) # 旧连接
        # self.full_list_switch.stateChanged.connect(self.on_session_mode_changed) # 旧连接
        self.random_switch.stateChanged.connect(self.on_session_mode_changed)
        self.full_list_switch.stateChanged.connect(self.on_session_mode_changed)
        self.recording_device_error_signal.connect(self.show_recording_device_error)
        self.skip_repetitions_btn.clicked.connect(self.skip_repetitions)
        # --- [新增] 连接临时设置控件的信号 ---
        self.session_repetition_slider.valueChanged.connect(self._on_session_settings_changed)
        self.session_follow_up_switch.stateChanged.connect(self._on_session_settings_changed)

    def show_wordlist_button_context_menu(self, position):
        """
        [新增] 为词表选择按钮显示一个上下文菜单。
        """
        # 只有在当前已选中一个词表时，才显示“清空”选项
        if not self.current_wordlist_name:
            return

        menu = QMenu(self)
        clear_action = menu.addAction(self.icon_manager.get_icon("clear"), "清空当前选择")
        
        # 将菜单显示在按钮的全局位置上
        action = menu.exec_(self.word_list_select_btn.mapToGlobal(position))

        if action == clear_action:
            self.current_wordlist_name = ""
            self.word_list_select_btn.setText("请选择单词表...")
            self.word_list_select_btn.setToolTip("点击选择一个用于本次采集任务的单词表文件。\n右键可清空当前选择。")
            
            # 调用新方法显示提示信息
            self._show_placeholder_message("请从右侧选择一个单词表以加载预览...")
            self.list_label.setText("测试词语列表:")
            
            # 同时清除配置文件中记住的选择
            self.parent_window.update_and_save_module_state(
                'accent_collection',
                'last_selected_wordlist',
                ""
            )

    def open_wordlist_selector(self):
        """
        [v1.2 - Final & Corrected] 打开词表选择对话框，并在选择后实时更新预览。
        """
        dialog = WordlistSelectionDialog(self, self.WORD_LIST_DIR, self.icon_manager, pin_handler=self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_file_relpath:
            selected_file = dialog.selected_file_relpath
            
            # 只有在用户选择了与当前不同的文件时，才执行更新
            if self.current_wordlist_name != selected_file:
                self.current_wordlist_name = selected_file
                base_name = os.path.basename(selected_file)
                display_name, _ = os.path.splitext(base_name)
                
                # 更新UI
                self.word_list_select_btn.setText(display_name)
                self.word_list_select_btn.setToolTip(f"当前选择: {selected_file}")

                # [核心功能] 立即调用预览方法来刷新左侧表格
                self._preview_wordlist(selected_file)
                
                # [UX优化] 将焦点设置到下一个合乎逻辑的控件上
                self.start_session_btn.setFocus()
                
                # 保存选择以便下次启动时记住 (逻辑不变)
                module_states = self.config.get("module_states", {}).get("accent_collection", {})
                if module_states.get("remember_last_wordlist", True):
                    self.parent_window.update_and_save_module_state(
                        'accent_collection',
                        'last_selected_wordlist',
                        selected_file
                    )

    def _on_session_settings_changed(self):
        """当会话中的临时设置（开关、滑块）改变时，更新内部状态变量。"""
        # 更新滑块旁边的标签
        new_count = self.session_repetition_slider.value()
        self.session_repetition_label.setText(f"{new_count} 次")
        
        # 更新内部的临时状态变量
        self.session_follow_up_enabled = self.session_follow_up_switch.isChecked()
        self.session_repetition_count = new_count


    def skip_repetitions(self):
        """用户点击“完成本词”按钮，提前结束当前词的跟读循环。"""
        if self.is_follow_up_active:
            self.follow_up_repetitions_left = 0
            # 无论合并还是分离，都停止录音，因为本词条的采集结束了
            if self.is_recording:
                self._stop_recording_logic()

    def on_cell_double_clicked(self, row, column):
        # 无论双击哪一列，都视为重听
        self.replay_audio()

    def update_icons(self):
        self.start_session_btn.setIcon(self.icon_manager.get_icon("start_session")); self.end_session_btn.setIcon(self.icon_manager.get_icon("end_session")); self.replay_btn.setIcon(self.icon_manager.get_icon("play_audio"))
        if self.is_recording: self.record_btn.setIcon(self.icon_manager.get_icon("stop"))
        else: self.record_btn.setIcon(self.icon_manager.get_icon("record"))
        if self.session_active:
            for i, item_data in enumerate(self.current_word_list):
                if item_data.get('recorded', False):
                    # [修改] 图标设置到第一列的item上
                    list_item = self.list_widget.item(i, 0)
                    if list_item: list_item.setIcon(self.icon_manager.get_icon("success"))

    def apply_layout_settings(self):
        ui_settings = self.config.get("ui_settings", {}); width = ui_settings.get("collector_sidebar_width", 320); self.right_panel.setFixedWidth(width)

    def load_config_and_prepare(self):
        self.config = self.parent_window.config
        self.apply_layout_settings()

        module_states = self.config.get("module_states", {}).get("accent_collection", {})
        self.pinned_wordlists = module_states.get("pinned_wordlists", [])
        # 在设置初始状态时阻塞信号
        self.random_switch.blockSignals(True)
        self.full_list_switch.blockSignals(True)
        self.random_switch.setChecked(module_states.get("is_random", False))
        
        # --- 再次确认修复此处的笔误 ---
        self.full_list_switch.setChecked(module_states.get("is_full_list", False)) 
        
        self.random_switch.blockSignals(False)
        self.full_list_switch.blockSignals(False)
        
        # [新增] 应用波形图显隐设置
        show_waveform = module_states.get("show_waveform", True)
        self.list_widget.setColumnHidden(2, not show_waveform) # Column 2 is the waveform
        
        # [新增] 应用音量计刷新率
        interval = module_states.get("volume_meter_interval", 16)
        # 如果 QTimer 存在，则更新它的间隔；如果不存在，则创建它
        if self.update_timer:
            self.update_timer.setInterval(interval)
        else:
            self.update_timer = QTimer()
            self.update_timer.setInterval(interval)
            self.update_timer.timeout.connect(self.update_volume_meter)

        if not self.session_active:
            self.populate_word_lists()
            self.participant_input.setText(self.config['file_settings'].get('participant_base_name', 'participant'))
    
    def show_recording_device_error(self, error_message):
        QMessageBox.critical(self, "录音设备错误", error_message); self.status_label.setText("状态：录音设备错误，请检查设置。"); self.record_btn.setEnabled(False)
        if self.session_active: self.end_session(force=True)

    def is_wordlist_pinned(self, rel_path):
        """检查一个词表是否已被固定。"""
        return rel_path in self.pinned_wordlists

    def toggle_pin_wordlist(self, rel_path):
        """固定或取消固定一个词表。"""
        if self.is_wordlist_pinned(rel_path):
            self.pinned_wordlists.remove(rel_path)
        else:
            # 限制最多只能固定3个
            if len(self.pinned_wordlists) >= 3:
                QMessageBox.warning(self, "固定已达上限", "最多只能固定3个单词表。")
                return
            self.pinned_wordlists.append(rel_path)
        
        # 保存更改到配置文件
        self._save_pinned_wordlists()

    def _save_pinned_wordlists(self):
        """将当前的固定列表保存到 settings.json。"""
        self.parent_window.update_and_save_module_state(
            'accent_collection', 
            'pinned_wordlists', 
            self.pinned_wordlists
        )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if self.list_widget.hasFocus() and self.replay_btn.isEnabled(): self.replay_audio(); event.accept()
        else: super().keyPressEvent(event)

    def update_volume_meter(self):
        # --- START OF REFACTOR (V3) ---
        raw_target_value = 0
        try:
            data_chunk = self.volume_meter_queue.get_nowait()
            if data_chunk is not None:
                rms = np.linalg.norm(data_chunk) / np.sqrt(len(data_chunk)) if data_chunk.any() else 0
                dbfs = 20 * np.log10(rms + 1e-7)
                raw_target_value = max(0, min(100, (dbfs + 60) * (100 / 60)))
        except queue.Empty:
            raw_target_value = 0
        except Exception as e:
            print(f"Error calculating volume: {e}")
            raw_target_value = 0
        
        self.volume_history.append(raw_target_value)
        smoothed_target_value = sum(self.volume_history) / len(self.volume_history)
 
        current_value = self.volume_meter.value()
        smoothing_factor = 0.4
        new_value = int(current_value * (1 - smoothing_factor) + smoothed_target_value * smoothing_factor)
        
        if abs(new_value - smoothed_target_value) < 2:
            new_value = int(smoothed_target_value)
            
        self.volume_meter.setValue(new_value)
            
    def _start_recording_logic(self):
        self.recording_indicator.setText("● 正在录音"); self.recording_indicator.setStyleSheet("color: red;")
        while not self.audio_queue.empty():
            try: self.audio_queue.get_nowait()
            except queue.Empty: break
        self.is_recording = True

    def _stop_recording_logic(self):
        self.is_recording = False; self.recording_indicator.setText("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.run_task_in_thread(self.save_recording_task)

    def populate_word_lists(self):
        """
        [v3.2 - State Sync Fix] 管理预会话UI状态。
        修复了程序启动时未同步内部词表状态 (self.current_wordlist_name) 的BUG。
        """
        default_list_to_load = ""

        # 1. 检查并获取默认加载的词表路径 (逻辑不变)
        module_states = self.config.get("module_states", {}).get("accent_collection", {})
        should_remember = module_states.get("remember_last_wordlist", True)

        if should_remember:
            default_list_to_load = module_states.get("last_selected_wordlist", "")
        if not default_list_to_load:
            default_list_to_load = self.config['file_settings'].get('word_list_file', '')

        # 2. 根据是否存在默认词表，更新整个预会话UI
        if default_list_to_load and os.path.exists(os.path.join(self.WORD_LIST_DIR, default_list_to_load)):
            # --- 状态A: 找到了有效的默认词表 ---
            
            # [核心修复] 在更新UI之前，首先同步内部状态变量！
            self.current_wordlist_name = default_list_to_load
            
            # 更新UI按钮的显示 (逻辑不变)
            base_name = os.path.basename(default_list_to_load)
            display_name, _ = os.path.splitext(base_name)
            self.word_list_select_btn.setText(display_name)
            self.word_list_select_btn.setToolTip(f"当前选择: {default_list_to_load}")
            
            # 调用方法加载并显示预览 (逻辑不变)
            self._preview_wordlist(default_list_to_load)
        else:
            # --- 状态B: 没有找到默认词表 ---
            self.current_wordlist_name = "" # 确保在没有选择时，内部状态也是空的
            self.word_list_select_btn.setText("请选择单词表...")
            self.word_list_select_btn.setToolTip("点击选择一个用于本次采集任务的单词表文件。")

            # 调用方法显示提示信息 (逻辑不变)
            self._show_placeholder_message("请从右侧选择一个单词表以加载预览...")
            self.list_label.setText("测试词语列表:")

    def on_session_mode_changed(self):
        # [修改] 此方法现在只在会话激活时刷新列表，不再保存任何东西
        if not self.session_active: return
        self.prepare_word_list()
        if self.current_word_list: 
            recorded_count = sum(1 for item in self.current_word_list if item['recorded'])
            self.record_btn.setText(f"开始录制 ({recorded_count + 1}/{len(self.current_word_list)})")
    # 修改 open_settings_dialog 方法，实现设置后自动刷新
    def open_settings_dialog(self):
        """
        [v2.0] 打开此模块的设置对话框，并在确认后请求主窗口进行彻底刷新。
        """
        if self.settings_dialog and self.settings_dialog.isVisible():
            self.settings_dialog.activateWindow()
            self.settings_dialog.raise_()
            return
            
        self.settings_dialog = SettingsDialog(self)
        
        # 对话框关闭后，如果用户点击了"OK"
        if self.settings_dialog.exec_() == QDialog.Accepted:
            # --- 核心修改 ---
            # 直接调用主窗口提供的公共API来刷新自己
            self.parent_window.request_tab_refresh(self)


    # [新增] 新的“开始会话”按钮点击处理器
    def handle_start_session_click(self):
        """
        根据配置决定是显示菜单还是直接开始。
        """
        module_states = self.config.get("module_states", {}).get("accent_collection", {})
        action = module_states.get("start_button_action", "popup")

        if action == "popup":
            self.show_start_session_menu()
        else: # action == "default"
            # 直接使用 TTS 模式开始，这是最安全的默认行为
            self.start_session(prompt_mode='tts')


    def reset_ui(self):
        self.pre_session_widget.show()
        self.in_session_widget.hide()
        self.record_btn.setEnabled(False)
        self.replay_btn.setEnabled(False)
        self.record_btn.setText("开始录制下一个")
        
        # [核心修改] 不再手动清空表格，而是调用 load_config_and_prepare，
        # 它会进一步调用 populate_word_lists 来恢复正确的预会话状态。
        self.load_config_and_prepare()

        self.status_label.setText("状态：准备就绪")
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
        
    def end_session(self, force=False):
        if not force:
            reply = QMessageBox.question(self, '结束会话', '您确定要结束当前的口音采集会话吗？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes: return

        if self.logger:
            recorded_count = sum(1 for item in self.current_word_list if item.get('recorded', False))
            total_count = len(self.current_word_list)
            self.logger.log(f"[SESSION_END] Session ended by user. Recorded {recorded_count}/{total_count} items.")
        
        # 停止所有后台活动
        self.update_timer.stop()
        self.volume_meter.setValue(0)
        self.session_stop_event.set()
        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=1.0)
        
        # --- [核心修改] ---
        # 在重置UI和内部状态之前，调用清理函数
        self._cleanup_empty_session_folder()
        # --- [修改结束] ---

        # 重置所有会话相关的状态
        self.recording_thread = None
        self.session_active = False
        self.is_recording = False
        self.current_word_list = []
        self.current_word_index = -1
        self.logger = None
        
        # 重置UI到初始状态
        self.skip_repetitions_btn.hide()
        self.session_follow_up_group.hide()
        self.reset_ui()
        self.load_config_and_prepare()

    # 修改 _cleanup_empty_session_folder 方法，使其受配置控制
    def _cleanup_empty_session_folder(self):
        """
        [v2.0 - Configurable] 在会话结束时，根据设置检查并清理空会话文件夹。
        """
        # [新增] 从配置中读取是否启用此功能
        module_states = self.config.get("module_states", {}).get("accent_collection", {})
        is_cleanup_enabled = module_states.get("cleanup_empty_folder", True) # 默认启用
        
        # 如果功能被禁用，则直接返回
        if not is_cleanup_enabled:
            return

        # 安全检查：确保文件夹路径存在且是一个目录
        if not hasattr(self, 'recordings_folder') or not os.path.isdir(self.recordings_folder):
            return

        try:
            # 获取文件夹内的所有项目
            items_in_folder = os.listdir(self.recordings_folder)
            
            # 定义哪些是音频文件（应该保留文件夹）
            audio_extensions = ('.wav', '.mp3', '.flac', '.ogg', '.m4a')
            
            # 检查是否存在任何音频文件
            has_audio_files = any(item.lower().endswith(audio_extensions) for item in items_in_folder)
            
            # 如果存在任何音频文件，则立即停止，不做任何操作
            if has_audio_files:
                return

            # 如果代码执行到这里，说明没有音频文件。
            # 现在我们检查剩下的文件是否只有 log.txt 或者文件夹为空。
            # 找出所有非音频文件（和非文件夹）
            other_files = [
                item for item in items_in_folder 
                if not item.lower().endswith(audio_extensions) and os.path.isfile(os.path.join(self.recordings_folder, item))
            ]
            
            # 决策：如果文件夹是空的，或者只包含一个 log.txt 文件，则删除
            if not other_files or (len(other_files) == 1 and other_files[0] == 'log.txt'):
                # 记录即将被删除的文件夹路径，以防 self.logger 被置空
                folder_to_delete = self.recordings_folder
                
                # 在状态栏给用户一个清晰的反馈
                self.status_label.setText("状态：会话结束。已自动清理空的结果文件夹。")
                if self.logger:
                    self.logger.log(f"[CLEANUP] Session folder '{os.path.basename(folder_to_delete)}' contains no audio. Deleting.")
                
                # 使用 shutil.rmtree 来安全地删除整个文件夹及其内容
                import shutil
                shutil.rmtree(folder_to_delete)
                
                print(f"[INFO] Cleaned up empty session folder: {folder_to_delete}")

        except Exception as e:
            # 如果出现任何错误（如权限问题），则打印错误信息，但不要让程序崩溃
            print(f"[ERROR] Failed to cleanup empty session folder '{self.recordings_folder}': {e}")

    def show_start_session_menu(self):
        """
        [v2.4 修复] 菜单项在点击后立即自动关闭。
        """
        # 1. 前置检查 (不变)
        wordlist_file = self.current_wordlist_name
        if not wordlist_file:
            QMessageBox.warning(self, "选择错误", "请先选择一个单词表。")
            return
        base_name = self.participant_input.text().strip()
        if not base_name:
            QMessageBox.warning(self, "输入错误", "请输入被试者名称。")
            return
            
        # 2. 智能检测是否存在 'Record' 源
        wordlist_name_with_subdir, _ = os.path.splitext(wordlist_file)
        wordlist_basename, _ = os.path.splitext(os.path.basename(wordlist_file))

        # [新增] 定义两个可能的搜索路径
        primary_record_path = os.path.join(self.AUDIO_RECORD_DIR, wordlist_name_with_subdir)
        fallback_record_path = os.path.join(self.AUDIO_RECORD_DIR, wordlist_basename)
        
        # [修改] 现在检查两个可能的路径
        primary_exists = os.path.exists(primary_record_path) and any(
            f.lower().endswith(('.wav', '.mp3')) for f in os.listdir(primary_record_path)
        )
        fallback_exists = os.path.exists(fallback_record_path) and any(
            f.lower().endswith(('.wav', '.mp3')) for f in os.listdir(fallback_record_path)
        )
        
        record_source_exists = primary_exists or fallback_exists
        
        # 3. 构建菜单
        menu = QMenu(self)
        menu.setStyleSheet(self.parent_window.styleSheet())
        
        from functools import partial

        # 辅助函数
        def create_menu_item(icon, text, tooltip, callback_func):
            button = QToolButton(menu)
            button.setText(text)
            button.setIcon(icon)
            button.setToolTip(tooltip)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setAutoRaise(True)
            button.setFixedWidth(250)
            button.setObjectName("PluginMenuItemToolButton")
            
            # --- [核心修改] ---
            # 创建一个 lambda 函数，它首先关闭菜单，然后调用原始的回调函数。
            # 这确保了点击后菜单会立即消失。
            button.clicked.connect(lambda: (menu.close(), callback_func()))
            
            widget_action = QWidgetAction(menu)
            widget_action.setDefaultWidget(button)
            menu.addAction(widget_action)

        # 创建菜单项
        create_menu_item(
            self.icon_manager.get_icon("tts"), 
            "使用 TTS 提示音",
            "程序将检查并自动生成缺失的TTS音频作为提示音。\n推荐用于没有真人录音的情况。",
            partial(self.start_session, prompt_mode='tts')
        )
        
        if record_source_exists:
            # [核心修复] 使用 wordlist_basename 变量，它现在总是存在且不含路径和后缀
            display_name_for_tooltip = wordlist_basename 
            
            create_menu_item(
                self.icon_manager.get_icon("play_audio"),
                "使用已有录音作为提示音",
                f"优先使用 '{display_name_for_tooltip}' 文件夹内已录制的人声\n作为提示音，这通常比TTS质量更高。",
                partial(self.start_session, prompt_mode='record')
            )

        menu.addSeparator()
        
        create_menu_item(
            self.icon_manager.get_icon("beep_mode"), # 假设有一个表示声音的图标
            "使用'哔'声提示",
            "在智能跟读模式下，用'哔'声提示每次重复。\n单个词条完成后，用另一种声音提示进入下一词。",
            partial(self.start_session, prompt_mode='beep') # <-- 关键
        )
        
        menu.addSeparator()
        
        create_menu_item(
            self.icon_manager.get_icon("mute"),
            "无提示音直接开始",
            "开始一个静默录制会话，不会播放任何提示音。\n适用于跟读、复述等任务。",
            partial(self.start_session, prompt_mode='silent')
        )
        
        # 5. 显示菜单 (不变)
        menu.exec_(self.start_session_btn.mapToGlobal(QPoint(0, self.start_session_btn.height())))

    def start_session(self, prompt_mode='tts'):
        """
        [v2.1 修复] 此方法只应在用户从菜单中做出选择后被调用。
        它是所有会话准备工作的真正入口。
        :param prompt_mode: 'tts', 'record', 或 'silent'
        """
        self.prompt_mode = prompt_mode

        wordlist_file = self.current_wordlist_name
        base_name = self.participant_input.text().strip()
        
        results_dir = self.config['file_settings'].get("results_dir", os.path.join(self.BASE_PATH, "Results"))
        common_results_dir = os.path.join(results_dir, "common"); os.makedirs(common_results_dir, exist_ok=True)
        i = 1; folder_name = base_name
        while os.path.exists(os.path.join(common_results_dir, folder_name)): i += 1; folder_name = f"{base_name}_{i}"
        self.recordings_folder = os.path.join(common_results_dir, folder_name); os.makedirs(self.recordings_folder)
        
        self.logger = None
        if self.config.get("app_settings", {}).get("enable_logging", True): self.logger = self.Logger(os.path.join(self.recordings_folder, "log.txt"))

        try:
            self.current_wordlist_name = wordlist_file
            word_groups = self.load_word_list_logic()
            if not word_groups:
                QMessageBox.warning(self, "词表错误", f"单词表 '{wordlist_file}' 为空或无法解析。")
                if self.logger: self.logger.log(f"[ERROR] Wordlist is empty.")
                return

            if self.logger:
                mode = "Random" if self.random_switch.isChecked() else "Sequential"
                scope = "Full List" if self.full_list_switch.isChecked() else "Partial"
                self.logger.log(f"[SESSION_START] Participant: '{base_name}', Folder: '{folder_name}'")
                self.logger.log(f"[SESSION_CONFIG] Wordlist: '{wordlist_file}', Prompt Mode: '{prompt_mode}', Order: {mode}, Scope: {scope}")
                module_states = self.config.get("module_states", {}).get("accent_collection", {})
            
                # 1. 从永久配置中读取
                permanent_enabled = module_states.get("enable_smart_follow_up", False)
                permanent_count = module_states.get("follow_up_repetitions", 5)
            
                # 2. 初始化临时状态变量
                self.session_follow_up_enabled = permanent_enabled
                self.session_repetition_count = permanent_count
            
                # 3. 将临时控件的状态同步为初始值
                self.session_follow_up_switch.blockSignals(True)
                self.session_repetition_slider.blockSignals(True)
            
                self.session_follow_up_switch.setChecked(permanent_enabled)
                # [关键修复] 强制同步 ToggleSwitch 的视觉状态！
                if hasattr(self.session_follow_up_switch, 'sync_visual_state_to_checked_state'):
                    self.session_follow_up_switch.sync_visual_state_to_checked_state()

                self.session_repetition_slider.setValue(permanent_count)
                self.session_repetition_label.setText(f"{permanent_count} 次")
            
                self.session_follow_up_switch.blockSignals(False)
                self.session_repetition_slider.blockSignals(False)
            
            if self.prompt_mode == 'tts':
                self.progress_bar.setVisible(True)
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
                self.run_task_in_thread(self.check_and_generate_audio_logic, word_groups)
            else:
                self._proceed_to_start_session()

        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载单词表失败: {e}")
            if self.logger: self.logger.log(f"[ERROR] Failed to load wordlist: {e}")
            
    def update_tts_progress(self, percentage, text):
        self.progress_bar.setValue(percentage)
        
        # [新增] 截断过长的状态文本
        max_len = 50 
        if len(text) > max_len:
            display_text = text[:max_len] + "..."
        else:
            display_text = text
            
        self.status_label.setText(f"状态：{display_text}")
        # [新增] 同时，将完整文本设置到状态标签的工具提示中，方便用户查看
        self.status_label.setToolTip(text)
        
    def on_tts_finished(self, result):
        self.progress_bar.setVisible(False)
        
        status = result.get('status')
        tts_folder = result.get('tts_folder')

        if status == 'success':
            self._proceed_to_start_session()
        elif status == 'partial_failure':
            missing_files = result.get('missing_files', [])
            error_details = result.get('error_details', [])
            
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("TTS 音频生成不完整")
            msg_box.setText("部分提示音自动生成失败，可能是网络问题或不支持的语言。")
            
            details = "以下词条的提示音缺失:\n\n"
            details += "\n".join(f"- {word}" for word in missing_files[:10])
            if len(missing_files) > 10:
                details += f"\n...等共 {len(missing_files)} 个。"

            if error_details:
                details += "\n\n错误摘要:\n" + "\n".join(error_details)

            msg_box.setInformativeText(details)
            
            prepare_btn = msg_box.addButton("准备音频 (打开文件夹)", QMessageBox.AcceptRole)
            ignore_btn = msg_box.addButton("忽略并继续", QMessageBox.DestructiveRole)
            msg_box.setStandardButtons(QMessageBox.Cancel)
            
            msg_box.exec_()
            
            if msg_box.clickedButton() == prepare_btn:
                self._open_tts_folder(tts_folder)
                self.reset_ui()
            elif msg_box.clickedButton() == ignore_btn:
                if self.logger: self.logger.log("[WARNING] User chose to ignore missing TTS files and continue session.")
                self._proceed_to_start_session()
            else: # Cancel
                self.reset_ui()

        else: # Handle other generic errors
            error_msg = result.get('error', '未知错误')
            QMessageBox.critical(self, "准备失败", f"无法开始会话: {error_msg}")
            self.reset_ui()

    def update_item_quality_status(self, row, warnings):
        """
        由质量分析器插件在分析完成后调用。
        此方法负责更新内部状态并触发UI刷新。
        """
        if not (0 <= row < len(self.current_word_list)):
            return

        # 获取对应的QTableWidgetItem
        list_item = self.list_widget.item(row, 0) # 词语列的QTableWidgetItem
        if not list_item:
            return

        original_tooltip_text = self.current_word_list[row]['word'] # 获取原始词语文本作为Tooltip基础

        analyzer_plugin = getattr(self, 'quality_analyzer_plugin', None)
        if not analyzer_plugin: # 如果插件不存在，则默认显示成功图标
            list_item.setIcon(self.icon_manager.get_icon("success"))
            list_item.setToolTip(original_tooltip_text)
            return

        if not warnings:
            list_item.setIcon(self.icon_manager.get_icon("success"))
            list_item.setToolTip(original_tooltip_text)
        else:
            # 根据警告类型设置不同图标
            has_critical = any(w['type'] in analyzer_plugin.critical_warnings for w in warnings)
            list_item.setIcon(analyzer_plugin.warning_icon if has_critical else analyzer_plugin.info_icon)
            
            # 构建详细的Tooltip
            html = f"<b>{original_tooltip_text}</b><hr>"
            html += "<b>质量报告:</b><br>"
            warning_list_html = [
                f"• <b>{analyzer_plugin.warning_type_map.get(w['type'], w['type'])}:</b> {w['details']}"
                for w in warnings
            ]
            html += "<br>".join(warning_list_html)
            list_item.setToolTip(html)
        
    def _find_existing_audio(self, word):
        """
        辅助函数，用于查找给定单词的已存在音频文件。
        在智能跟读模式下，会寻找带编号的最新文件。
        """
        supported_formats = ['.wav', '.mp3', '.flac', '.ogg'] 
        
        if self.recordings_folder:
            # [核心修改] 检查是否处于跟读模式
            if self.is_follow_up_active and self.current_word_index != -1:
                module_states = self.config.get("module_states", {}).get("accent_collection", {})
                total_reps = module_states.get("follow_up_repetitions", 5)
                # 找到刚刚保存的那个文件
                current_rep_number = total_reps - self.follow_up_repetitions_left
                for ext in supported_formats:
                    path = os.path.join(self.recordings_folder, f"{word}_{current_rep_number}{ext}")
                    if os.path.exists(path):
                        return path
            else:
                # 正常模式
                for ext in supported_formats:
                    path = os.path.join(self.recordings_folder, f"{word}{ext}")
                    if os.path.exists(path):
                        return path
                
        return None

    def prepare_word_list(self):
        """
        [v3.0 - Config-Aware]
        根据会话模式（随机/顺序，完整/部分）和模块设置（默认备注）来准备要录制的词语列表，
        并填充UI表格。
        """
        word_groups = self.load_word_list_logic()
        is_random = self.random_switch.isChecked()
        is_full = self.full_list_switch.isChecked()
        temp_list = []
        
        # [新增] 从主配置中获取此模块的特定设置
        module_states = self.config.get("module_states", {}).get("accent_collection", {})
        default_note = module_states.get("default_note", "")

        # 根据“完整/部分”模式筛选词条
        if not is_full:
            for group in word_groups:
                if group:
                    temp_list.append(random.choice(list(group.items())))
        else:
            for group in word_groups:
                temp_list.extend(group.items())
        
        # 根据“随机/顺序”模式打乱列表
        if is_random:
            random.shuffle(temp_list)
            
        # 构建最终的内部数据结构 (self.current_word_list)
        self.current_word_list = []
        for word, value in temp_list:
            # 提取备注，并应用默认备注逻辑
            ipa_or_note = value[0] if isinstance(value, tuple) else str(value)
            if not ipa_or_note and default_note:
                ipa_or_note = default_note
            
            self.current_word_list.append({'word': word, 'ipa': ipa_or_note, 'recorded': False})
        
        # --- UI 更新部分 ---
        
        # 在更新前禁用排序，可以提高填充大量数据时的性能
        self.list_widget.setSortingEnabled(False)
        self.list_widget.setRowCount(0) # 清空表格

        for i, item_data in enumerate(self.current_word_list):
            self.list_widget.insertRow(i)
            
            # --- 第0列: 词语 ---
            word_text = item_data['word']
            word_item = QTableWidgetItem(word_text)
            word_item.setToolTip(word_text) # 设置工具提示
            self.list_widget.setItem(i, 0, word_item)
            
            # --- 第1列: IPA/备注 ---
            ipa_text = item_data['ipa']
            ipa_item = QTableWidgetItem(ipa_text)
            ipa_item.setToolTip(ipa_text) # 设置工具提示
            self.list_widget.setItem(i, 1, ipa_item)

            # --- 第2列: 波形图控件 ---
            # 即使列被隐藏，也创建控件，以保持数据结构一致性
            waveform_widget = WaveformWidget(self)
            self.list_widget.setCellWidget(i, 2, waveform_widget)
            
            # --- 检查并更新已录制状态 ---
            filepath = self._find_existing_audio(item_data['word'])
            if filepath:
                item_data['recorded'] = True
                word_item.setIcon(self.icon_manager.get_icon("success"))
                waveform_widget.set_waveform_data(filepath)

        # 调整行高以适应内容
        self.list_widget.resizeRowsToContents()
        
        # 重新启用排序
        self.list_widget.setSortingEnabled(True)

        # 如果列表不为空，则默认选中第一行
        if self.current_word_list:
            self.list_widget.setCurrentCell(0, 0)
        
    def handle_record_button(self):
        """
        处理主录制按钮的点击事件。
        根据当前是否处于智能跟读模式，执行不同的操作。
        """
        # --- 模式1：如果正处于智能跟读模式，此按钮的功能是“完成本词跟读” ---
        if self.is_follow_up_active:
            self.skip_repetitions()
            return

        # --- 模式2：如果不在录音中，则启动一个新的录制任务 ---
        if not self.is_recording:
            # a. 检查是否已选择词条
            self.current_word_index = self.list_widget.currentRow()
            if self.current_word_index == -1:
                QMessageBox.information(self, "提示", "请先在左侧列表中选择一个词条。")
                return

            word_to_record = self.current_word_list[self.current_word_index]['word']
            if self.logger: self.logger.log(f"[RECORDING_START] Word: '{word_to_record}'")

            # b. [核心] 从会话的临时变量中读取是否启用智能跟读
            is_follow_up_enabled = self.session_follow_up_enabled
            
            if is_follow_up_enabled:
                # 如果启用，设置跟读模式的状态
                self.is_follow_up_active = True
                total_reps = self.session_repetition_count # 使用临时设置的次数
                self.follow_up_repetitions_left = total_reps
                
                # 更新按钮的UI，变为“完成本词”状态
                self.record_btn.setText(f"完成本词跟读 (剩余 {total_reps})")
                self.record_btn.setIcon(self.icon_manager.get_icon("success_dark"))
                self.record_btn.setToolTip("提前结束当前词语的跟读循环，并进入下一个词。")
            else:
                # 如果不启用，设置为正常的录制模式
                self.is_follow_up_active = False
                self.record_btn.setText("停止录制")
                self.record_btn.setIcon(self.icon_manager.get_icon("stop"))
                self.record_btn.setToolTip("点击停止当前录音。")

            # c. 禁用其他UI控件，开始录制
            self.is_recording = True
            self.list_widget.setEnabled(False)
            self.random_switch.setEnabled(False)
            self.full_list_switch.setEnabled(False)
            
            # d. 更新状态标签文本
            if self.is_follow_up_active:
                status_text = f"状态：请朗读 '{word_to_record}' (1/{total_reps})"
            else:
                status_text = f"状态：正在录制 '{word_to_record}'..."
            self.status_label.setText(status_text)
            
            # e. 播放提示音并开始录音
            self.play_audio_logic()
            self._start_recording_logic()
            
        # --- 模式3：如果正在录音中（且非跟读模式），则手动停止录制 ---
        else:
            if not self.is_follow_up_active:
                self._stop_recording_logic()
            
    def on_recording_saved(self, result):
        """
        在录音文件成功保存后被调用。
        负责更新UI、处理跟读循环或准备下一个词条。
        """
        # 启用在录制时被禁用的UI控件
        self.list_widget.setEnabled(True)
        self.replay_btn.setEnabled(True)
        self.random_switch.setEnabled(True)
        self.full_list_switch.setEnabled(True)
    
        # 1. 处理文件保存失败的特殊情况
        if result == "save_failed_mp3_encoder":
            QMessageBox.critical(self, "MP3 编码器缺失", "无法将录音保存为 MP3 格式。请确保已安装LAME编码器。")
            self.status_label.setText("状态：MP3保存失败！")
            # 即使失败，也要重置跟读状态以避免卡死
            if self.is_follow_up_active:
                self.is_follow_up_active = False
                self.record_btn.setText("开始录制下一个")
                self.record_btn.setIcon(self.icon_manager.get_icon("record"))
            return
        
        # 2. 检查索引是否有效，防止意外错误
        if self.current_word_index < 0 or self.current_word_index >= len(self.current_word_list):
            if self.logger: self.logger.log(f"[ERROR] current_word_index ({self.current_word_index}) out of bounds in on_recording_saved.")
            self.record_btn.setEnabled(True)
            return
        
        # 3. 更新UI（将词条标记为已录制，并更新图标和波形图）
        item_data = self.current_word_list[self.current_word_index]
        item_data['recorded'] = True
    
        list_item = self.list_widget.item(self.current_word_index, 0)
        if list_item: # 确保 item 存在
            list_item.setIcon(self.icon_manager.get_icon("success"))
        
        filepath = self._find_existing_audio(item_data['word'])
        waveform_widget = self.list_widget.cellWidget(self.current_word_index, 2)
        if isinstance(waveform_widget, WaveformWidget) and filepath:
            waveform_widget.set_waveform_data(filepath)

        # 调用质量分析插件（如果存在）
        analyzer_plugin = getattr(self, 'quality_analyzer_plugin', None)
        if analyzer_plugin and filepath:
            analyzer_plugin.analyze_and_update_ui('accent_collection', filepath, self.current_word_index)
    
        # 4. [核心] 处理不同的会话模式
        # a. 如果是用户点击“完成本词跟读”按钮触发的保存
        if self.is_follow_up_active and self.follow_up_repetitions_left == 0:
            self.is_follow_up_active = False
            self.record_btn.setText("开始录制下一个")
            self.record_btn.setIcon(self.icon_manager.get_icon("record"))
            self.record_btn.setToolTip("点击开始录制当前选中的词语。")
            self.handle_session_completion(check_all_recorded=True)
            return

        # b. 如果是“分离文件”跟读模式下，一次自动跟读完成
        module_states = self.config.get("module_states", {}).get("accent_collection", {})
        merge_recordings = module_states.get("merge_follow_up_recordings", True)
        if self.is_follow_up_active and not merge_recordings:
            self.prepare_next_repetition()
            return
        
        # c. 默认情况：
        #    - 非跟读模式的录音保存
        #    - “合并文件”跟读模式的最终保存
        self.handle_session_completion(check_all_recorded=True)

    def prepare_next_repetition(self):
        """准备并触发下一次的跟读。此方法现在是两种模式的核心驱动。"""
        if not self.session_active or not self.is_follow_up_active: return

        # 1. 减少剩余次数
        self.follow_up_repetitions_left -= 1
        
        # 2. 检查是否还有剩余次数
        if self.follow_up_repetitions_left > 0:
            if self.prompt_mode == 'beep':
                # 检查文件是否存在，防止因文件缺失导致崩溃
                if os.path.exists(self.beep_sound_path):
                    threading.Thread(target=self.play_sound_task, args=(self.beep_sound_path,), daemon=True).start()
                else:
                    print(f"[WARNING] Beep sound file not found at: {self.beep_sound_path}")
            # --- 如果还有次数，准备下一次跟读 ---
            module_states = self.config.get("module_states", {}).get("accent_collection", {})
            total_reps = self.session_repetition_count
            merge_recordings = module_states.get("merge_follow_up_recordings", True)
            
            # a. 更新UI状态
            current_rep = total_reps - self.follow_up_repetitions_left + 1
            self.record_btn.setText(f"完成本词跟读 (剩余 {self.follow_up_repetitions_left})")
            word_to_record = self.current_word_list[self.current_word_index]['word']
            self.status_label.setText(f"状态：请跟读 '{word_to_record}' ({current_rep}/{total_reps})")

            # b. 播放提示音
            self.play_audio_logic()

            # c. 如果是“分离模式”，需要在播放提示音后重新开始录音
            if not merge_recordings:
                # 延迟启动，给提示音播放时间
                QTimer.singleShot(1200, self._start_recording_logic)
        
        else:
            # --- 如果次数用完，结束本词条的跟读循环 ---
            self.is_follow_up_active = False # 标记跟读模式结束
            
            module_states = self.config.get("module_states", {}).get("accent_collection", {})
            merge_recordings = module_states.get("merge_follow_up_recordings", True)

            if merge_recordings:
                # 在“合并模式”下，在这里才停止录音
                if self.is_recording:
                    self._stop_recording_logic() # 这会触发 on_recording_saved
            else:
                # 在“分离模式”下，录音已经停止了。
                # 我们需要手动调用 handle_session_completion 来跳转到下一个词条。
                QTimer.singleShot(100, lambda: self.handle_session_completion(check_all_recorded=True))

    def handle_session_completion(self, check_all_recorded=True):
        """
        处理会话完成或单个词条完成的逻辑。
        :param check_all_recorded: 如果为True，则检查是否所有词都录完，并可能结束会话。
                                   如果为False，则无条件寻找下一个未录制的词。
        """
        # [新增] 如果是哔声模式，且不是因为会话全部完成而调用，则播放下一词提示音
        if self.prompt_mode == 'beep':
            all_recorded_now = all(item.get('recorded', False) for item in self.current_word_list)
            if not all_recorded_now: # 只有在还有词要录的情况下才播放
                if os.path.exists(self.next_word_sound_path):
                    threading.Thread(target=self.play_sound_task, args=(self.next_word_sound_path,), daemon=True).start()
                else:
                    print(f"[WARNING] Next word sound file not found at: {self.next_word_sound_path}")
        # 重置主录制按钮状态
        self.record_btn.setText("开始录制下一个")
        self.record_btn.setIcon(self.icon_manager.get_icon("record"))
        self.record_btn.setEnabled(True)

        if check_all_recorded:
            all_recorded = all(item.get('recorded', False) for item in self.current_word_list)
            if all_recorded:
                unrecorded_count = sum(1 for item in self.current_word_list if not item.get('recorded', False))
                if self.current_word_list:
                    QMessageBox.information(self, "会话结束", f"本次会话已结束。\n总共录制了 {len(self.current_word_list) - unrecorded_count} 个词语。")
                self.end_session()
                return

        # 寻找下一个未录制的词条
        next_index = -1
        indices = list(range(len(self.current_word_list)))
        start_search_index = 0 if self.current_word_index == -1 else self.current_word_index + 1
        
        for i in indices[start_search_index:] + indices[:start_search_index]:
            if not self.current_word_list[i].get('recorded', False):
                next_index = i
                break
            
        if next_index != -1:
            self.list_widget.setCurrentCell(next_index, 0)
            recorded_count = sum(1 for item in self.current_word_list if item.get('recorded', False))
            self.record_btn.setText(f"开始录制 ({recorded_count + 1}/{len(self.current_word_list)})")
            
            # --- [核心修复] 在这里新增一行，立即更新状态标签 ---
            next_word = self.current_word_list[next_index]['word']
            self.status_label.setText(f"状态：准备就绪，请录制 '{next_word}'")
            # --- 修复结束 ---
            
        else:
            # 如果没找到下一个，也视为会话结束
            if not check_all_recorded: # 如果是从skip调用的，这里也需要检查并结束
                self.handle_session_completion(check_all_recorded=True)
        
    def on_list_item_changed(self):
        row = self.list_widget.currentRow()
        if row!=-1 and not self.is_recording: self.replay_btn.setEnabled(True)
        
    def replay_audio(self, item=None):
        self.play_audio_logic()
    
    def play_audio_logic(self, index=None):
        # [vNext 新增] 如果是静默模式，则不播放任何提示音
        if self.prompt_mode == 'silent':
            return
        if self.prompt_mode == 'beep':
            return

        if not self.session_active:
            return
        if index is None:
            index = self.list_widget.currentRow()
        if index == -1 or index >= len(self.current_word_list):
            return

        word = self.current_word_list[index]['word']
        # [新增] 获取带子目录的路径和不带子目录的基本名
        wordlist_name_with_subdir, _ = os.path.splitext(self.current_wordlist_name)
        wordlist_basename, _ = os.path.splitext(os.path.basename(self.current_wordlist_name))

        # [修改] 扩展搜索路径列表，增加备用路径
        search_paths = [
            # 优先搜索：与词表结构相同的路径
            (os.path.join(self.AUDIO_RECORD_DIR, wordlist_name_with_subdir), ['.wav', '.mp3']),
            # 备用搜索：在 audio_record 根目录下的同名文件夹
            (os.path.join(self.AUDIO_RECORD_DIR, wordlist_basename), ['.wav', '.mp3']),
            # TTS 路径也同样处理，以保持一致性
            (os.path.join(self.AUDIO_TTS_DIR, wordlist_name_with_subdir), ['.wav', '.mp3']),
            (os.path.join(self.AUDIO_TTS_DIR, wordlist_basename), ['.wav', '.mp3']),
        ]

        final_path = None
        for folder, extensions in search_paths:
            if not folder: continue
            for ext in extensions:
                path_to_check = os.path.join(folder, f"{word}{ext}")
                if os.path.exists(path_to_check):
                    final_path = path_to_check
                    break
            if final_path:
                break

        if final_path:
            threading.Thread(target=self.play_sound_task, args=(final_path,), daemon=True).start()
        else:
            # 如果在 'record' 模式下找不到音频，给予用户明确提示
            if self.prompt_mode == 'record':
                self.status_label.setText(f"状态：在录音库中找不到 '{word}' 的提示音！")
            else:
                self.status_label.setText(f"状态：找不到 '{word}' 的提示音！")
                
    def play_sound_task(self,path):
        try:data,sr=sf.read(path,dtype='float32');sd.play(data,sr);sd.wait()
        except Exception as e: 
            if self.logger: self.logger.log(f"[ERROR] playing sound '{path}': {e}")
            self.parent_window.statusBar().showMessage(f"播放音频失败: {os.path.basename(path)}", 3000)

    def _persistent_recorder_task(self):
        try:
            # [修改] 调用解析函数来获取设备索引
            device_index = self.resolve_device_func(self.config)
            
            with sd.InputStream(device=device_index,samplerate=self.config['audio_settings']['sample_rate'],channels=self.config['audio_settings']['channels'],callback=self._audio_callback):
                self.session_stop_event.wait()
        except Exception as e:
            error_msg = f"无法启动录音，请检查录音设备设置或权限。\n错误详情: {e}"; print(f"持久化录音线程错误: {error_msg}")
            if self.logger: self.logger.log(f"[ERROR] Persistent recorder task failed: {error_msg}")
            self.recording_device_error_signal.emit(error_msg)
    def _handle_repetition_logic(self):
        """
        处理一次跟读结束后的核心逻辑。
        根据设置决定是停止录音（分离模式）还是仅准备下一次重复（合并模式）。
        """
        module_states = self.config.get("module_states", {}).get("accent_collection", {})
        merge_recordings = module_states.get("merge_follow_up_recordings", True)

        if merge_recordings:
            # 合并模式：不停止录音，直接准备下一次重复
            self.prepare_next_repetition()
        else:
            # 分离模式：停止录音，后续逻辑由 on_recording_saved 处理
            self._stop_recording_logic()
            
    def _audio_callback(self, indata, frames, time_info, status):
        """
        音频输入流的回调函数，在独立的音频线程中执行。
        负责将音频数据分发到录音队列和音量计队列，并根据设置执行静音检测。
        """
        # 1. 检查音频流状态，记录潜在的缓冲区溢出等问题
        if status and (status.input_overflow or status.output_overflow or status.priming_output):
            current_time = time.monotonic()
            if not hasattr(self, 'last_warning_log_time') or current_time - self.last_warning_log_time > 5:
                self.last_warning_log_time = current_time
                warning_msg = f"Audio callback status: {status}"
                print(warning_msg, file=sys.stderr)
                if self.logger: self.logger.log(f"[WARNING] {warning_msg}")
 
        # 2. 如果正在录音，则将原始音频数据放入录音队列（确保只执行一次）
        if self.is_recording:
            try:
                self.audio_queue.put(indata.copy())
            except queue.Full:
                pass
 
            # 3. [核心] 智能跟读的静音检测逻辑
            if self.is_follow_up_active:
                # 在两种模式下都需要进行静音检测，以触发下一次重复
                rms = np.linalg.norm(indata) / np.sqrt(len(indata)) if indata.any() else 0
                
                SILENCE_THRESHOLD = 0.008
                SPEAKING_RESET_THRESHOLD = 0.015
                SILENCE_DURATION_TRIGGER = 0.7

                if rms > SPEAKING_RESET_THRESHOLD:
                    self.is_speaking = True
                    self.last_audio_chunk_time = 0
                elif self.is_speaking and rms < SILENCE_THRESHOLD:
                    if self.last_audio_chunk_time == 0:
                        self.last_audio_chunk_time = time.monotonic()
                    elif time.monotonic() - self.last_audio_chunk_time > SILENCE_DURATION_TRIGGER:
                        self.is_speaking = False
                        self.last_audio_chunk_time = 0
                        
                        # 调用新的、更智能的处理函数
                        QTimer.singleShot(0, self._handle_repetition_logic)

        # 4. 将音频数据（应用增益后）放入音量计队列，用于UI实时反馈
        gain = self.config.get('audio_settings', {}).get('recording_gain', 1.0)
        
        if gain != 1.0:
            processed_for_meter = np.clip(indata * gain, -1.0, 1.0)
        else:
            processed_for_meter = indata
 
        try:
            self.volume_meter_queue.put_nowait(processed_for_meter.copy())
        except queue.Full:
            pass
        
    def save_recording_task(self, worker):
        if self.audio_queue.empty(): return None 
        data_frames = [];
        while not self.audio_queue.empty():
            try: data_frames.append(self.audio_queue.get_nowait())
            except queue.Empty: break
        if not data_frames: return None
        rec = np.concatenate(data_frames, axis=0); gain = self.config['audio_settings'].get('recording_gain', 1.0)
        if gain != 1.0: rec = np.clip(rec * gain, -1.0, 1.0)
        if self.current_word_index < 0 or self.current_word_index >= len(self.current_word_list):
            if self.logger: self.logger.log(f"[ERROR] Invalid current_word_index ({self.current_word_index}) in save_recording_task.")
            return "save_failed_invalid_index"
        recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower()
        word = self.current_word_list[self.current_word_index]['word']

        # [核心修复] 根据是否处于智能跟读模式，生成不同的文件名
        if self.is_follow_up_active:
            module_states = self.config.get("module_states", {}).get("accent_collection", {})
            total_reps = module_states.get("follow_up_repetitions", 5)
            # 计算当前是第几次录音
            current_rep_number = total_reps - self.follow_up_repetitions_left
            filename = f"{word}_{current_rep_number}.{recording_format}"
        else:
            filename = f"{word}.{recording_format}"
        filepath = os.path.join(self.recordings_folder, filename)
        if self.logger: self.logger.log(f"[RECORDING_SAVE_ATTEMPT] Word: '{word}', Format: '{recording_format}', Path: '{filepath}'")
        try:
            sf.write(filepath, rec, self.config['audio_settings']['sample_rate'])
            if self.logger: self.logger.log(f"[RECORDING_SAVE_SUCCESS] File saved successfully.")
            return "save_successful"
        except Exception as e:
            if self.logger: self.logger.log(f"[ERROR] Failed to save recording '{filepath}': {e}")
            if recording_format == 'mp3' and 'format not understood' in str(e).lower():
                 error_msg = "MP3 save failed: LAME encoder is likely missing.";
                 if self.logger: self.logger.log(f"[FATAL] {error_msg}"); return f"save_failed_mp3_encoder"
            return f"save_failed_exception: {e}"

    def run_task_in_thread(self,task_func,*args):
        self.thread=QThread();self.worker=self.Worker(task_func,*args);self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit); self.worker.finished.connect(self.worker.deleteLater); self.thread.finished.connect(self.thread.deleteLater)
        self.worker.progress.connect(self.update_tts_progress); self.worker.error.connect(lambda msg:QMessageBox.critical(self,"后台错误",msg))
        if task_func==self.check_and_generate_audio_logic:self.worker.finished.connect(self.on_tts_finished)
        elif task_func==self.save_recording_task:self.worker.finished.connect(self.on_recording_saved)
        self.thread.start()
        
    def load_word_list_logic(self, filename=None):
        """
        [v1.1 - Fix] 加载并解析一个标准的JSON词表文件。
        现在接受一个可选的 filename 参数，使其行为更明确。
        如果未提供 filename，则回退到使用 self.current_wordlist_name。
        """
        # [核心修复] 如果未提供文件名，则使用实例变量作为后备
        if filename is None:
            filename = self.current_wordlist_name

        if not filename:
            raise FileNotFoundError("没有提供或选择任何词表文件。")

        filepath = os.path.join(self.WORD_LIST_DIR, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"找不到单词表文件: {filename}")

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"词表文件 '{filename}' 不是有效的JSON格式: {e}")

        if "meta" not in data or data.get("meta", {}).get("format") != "standard_wordlist" or "groups" not in data:
            raise ValueError(f"词表文件 '{filename}' 格式不正确或不受支持。")

        word_groups = []
        for group_data in data.get("groups", []):
            group_dict = {}
            group_items = group_data.get("items", [])
            for item in group_items:
                text = item.get("text")
                if text:
                    note = item.get("note", "")
                    lang = item.get("lang", "")
                    group_dict[text] = (note, lang)
            if group_dict:
                word_groups.append(group_dict)
        
        return word_groups
        
    def _proceed_to_start_session(self):
        """
        [v1.1] 封装了开始录音会话的核心逻辑。
        现在会在会话开始时更新左侧列表的标签为 "(录制中)"。
        """
        # 1. 清理并启动后台录音线程和UI更新定时器
        self.session_stop_event.clear()
        self.recording_thread = threading.Thread(target=self._persistent_recorder_task, daemon=True)
        self.recording_thread.start()
        self.update_timer.start()
        
        # 2. 更新UI状态，切换到“会话中”的视图
        self.status_label.setText("状态：音频准备就绪。")
        self.pre_session_widget.hide()
        self.in_session_widget.show()
        
        # 3. [核心修改] 更新左侧列表的标签以反映“录制中”状态
        self.list_label.setText("测试词语列表: (录制中)")
        # 确保行号在进入会话时是可见的
        self.list_widget.verticalHeader().setVisible(True)

        # 4. 根据会话的初始临时设置，决定是否显示跟读设置面板
        if self.session_follow_up_enabled:
            self.session_follow_up_group.show()
        else:
            self.session_follow_up_group.hide()
            
        self.record_btn.setEnabled(True)
        self.session_active = True
        
        # 5. 准备并填充词语列表（应用随机化等设置）
        self.prepare_word_list()
        
        # 6. 更新录制按钮的文本，显示词条总数
        if self.current_word_list:
            recorded_count = sum(1 for item in self.current_word_list if item.get('recorded', False))
            self.record_btn.setText(f"开始录制 ({recorded_count + 1}/{len(self.current_word_list)})")

    def _open_tts_folder(self, folder_path):
        """跨平台地在文件浏览器中打开指定文件夹。"""
        if not folder_path or not os.path.exists(folder_path):
            QMessageBox.warning(self, "无法打开", "目标文件夹不存在。")
            return
        
        try:
            if sys.platform == 'win32':
                os.startfile(os.path.realpath(folder_path))
            elif sys.platform == 'darwin':
                subprocess.check_call(['open', folder_path])
            else: # Linux
                subprocess.check_call(['xdg-open', folder_path])
        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"无法打开文件夹: {e}")

    def check_and_generate_audio_logic(self, worker, word_groups):
        wordlist_name_with_subdir, _ = os.path.splitext(self.current_wordlist_name)
        wordlist_basename, _ = os.path.splitext(os.path.basename(self.current_wordlist_name))
        # [核心修复] 使用 wordlist_name_with_subdir 来创建TTS文件夹，以保持目录结构一致
        tts_audio_folder = os.path.join(self.AUDIO_TTS_DIR, wordlist_name_with_subdir)
        os.makedirs(tts_audio_folder, exist_ok=True)
        
        result = {'status': 'success', 'tts_folder': tts_audio_folder}

        gtts_settings = self.config.get("gtts_settings", {})
        gtts_default_lang = gtts_settings.get("default_lang", "en-us")
        gtts_auto_detect = gtts_settings.get("auto_detect", True)
        
        missing_items = []
        
        for group in word_groups:
            if not isinstance(group, dict):
                continue
            for word, value in group.items():
                supported_formats = ['.wav', '.mp3', '.flac', '.ogg']
                primary_record_dir = os.path.join(self.AUDIO_RECORD_DIR, wordlist_name_with_subdir)
                fallback_record_dir = os.path.join(self.AUDIO_RECORD_DIR, wordlist_basename)

                primary_exists = any(os.path.exists(os.path.join(primary_record_dir, f"{word}{ext}")) for ext in supported_formats)
                fallback_exists = any(os.path.exists(os.path.join(fallback_record_dir, f"{word}{ext}")) for ext in supported_formats)
                
                user_recorded_exists = primary_exists or fallback_exists
                
                tts_exists = any(os.path.exists(os.path.join(tts_audio_folder, f"{word}{ext}")) for ext in ['.wav', '.mp3'])
                
                if not user_recorded_exists and not tts_exists:
                    lang = value[1] if isinstance(value, tuple) and len(value) > 1 and value[1] else None
                    if not lang and gtts_auto_detect:
                        # =================== [核心修改] ===================
                        # 从词表数据 value 元组中提取备注信息 (value[0])
                        note = value[0] if isinstance(value, tuple) else ""
                        # 调用新的、需要两个参数的检测函数
                        lang = self.detect_language(word, note)
                        # ================================================
                    if not lang:
                        lang = gtts_default_lang
                    
                    missing_items.append({"word": word, "lang": lang})

        if not missing_items:
            if self.logger: self.logger.log("[INFO] No missing TTS audio files to generate.")
            return result

        if self.logger: self.logger.log(f"[INFO] Found {len(missing_items)} missing TTS files. Starting generation...")
    
        total_missing = len(missing_items)
        errors_occurred = []
        failed_words = []
        for i, item in enumerate(missing_items):
            word = item["word"]
            lang = item["lang"]
            
            percentage = int(((i + 1) / total_missing) * 100)
            progress_text = f"正在生成TTS ({i+1}/{total_missing}): {word}"
            
            worker.progress.emit(percentage, progress_text)
            
            filepath = os.path.join(tts_audio_folder, f"{word}.mp3")
            try:
                gTTS(text=word, lang=lang, slow=False).save(filepath)
                if self.logger: self.logger.log(f"[TTS_SUCCESS] Generated '{word}.mp3' with lang '{lang}'.")
                time.sleep(0.3)
            except Exception as e:
                error_detail = f"for '{word}': {str(e)[:100]}..."
                errors_occurred.append(error_detail)
                failed_words.append(word)
                if self.logger: self.logger.log(f"[TTS_ERROR] Failed to generate TTS {error_detail}")
    
        if errors_occurred:
            result['status'] = 'partial_failure'
            result['missing_files'] = failed_words
            result['error_details'] = errors_occurred[:3]
    
        return result

class SettingsDialog(QDialog):
    """
    [v2.2 - 完整 ToolTips 版]
    一个专门用于配置“标准朗读采集”模块的双栏设置对话框。
    """
    def __init__(self, parent_page):
        super().__init__(parent_page)
        
        self.parent_page = parent_page
        self.setWindowTitle("标准朗读采集设置")
        self.setWindowIcon(self.parent_page.parent_window.windowIcon())
        self.setStyleSheet(self.parent_page.parent_window.styleSheet())
        self.setMinimumSize(650, 500)
        
        # --- 1. 主布局：垂直分割 ---
        dialog_layout = QVBoxLayout(self)
        dialog_layout.setSpacing(10)
        dialog_layout.setContentsMargins(0, 10, 0, 10)

        # 2. 内容区布局：水平分割
        content_layout = QHBoxLayout()
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # 3. 左侧导航栏
        from PyQt5.QtWidgets import QListWidget, QStackedWidget, QFrame
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(180)
        self.nav_list.setObjectName("SettingsNavList")
        content_layout.addWidget(self.nav_list)

        # 4. 右侧内容区
        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)

        dialog_layout.addLayout(content_layout, 1)

        # 5. 分隔线和按钮栏
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        dialog_layout.addWidget(separator)
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.setContentsMargins(0, 0, 10, 0)
        dialog_layout.addWidget(self.button_box)

        # --- 6. 创建并填充页面 ---
        self._create_general_page()
        self._create_advanced_page()

        # --- 7. 连接信号并加载设置 ---
        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        self.load_settings()
        self.nav_list.setCurrentRow(0)

    def _create_general_page(self):
        """创建“常规选项”页面。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # --- 组1: 会话默认行为 ---
        session_group = QGroupBox("会话默认行为")
        session_form_layout = QFormLayout(session_group)
        
        self.random_checkbox = QCheckBox("默认以随机顺序开始会话")
        self.random_checkbox.setToolTip("勾选后，会话将打乱词表中所有词语的顺序进行呈现。")
        
        self.full_list_checkbox = QCheckBox("默认使用完整词表")
        self.full_list_checkbox.setToolTip("勾选后，会话将使用词表中的所有词语。\n取消勾选则只从每个组别中随机抽取一个词语。")
        
        self.remember_wordlist_checkbox = QCheckBox("记住上次选择的单词表")
        self.remember_wordlist_checkbox.setToolTip("勾选后，程序将自动记住您上次使用的单词表，\n并在下次启动时加载它。")

        start_button_behavior_layout = QHBoxLayout()
        self.start_button_toggle = self.parent_page.ToggleSwitch()
        self.start_button_toggle.setToolTip("设置“开始新会话”按钮的默认行为。\n默认: 直接使用TTS提示音开始。\n弹窗: 点击后会弹出一个菜单，让您选择提示音模式。")
        start_button_behavior_layout.addWidget(QLabel("默认"))
        start_button_behavior_layout.addWidget(self.start_button_toggle)
        start_button_behavior_layout.addWidget(QLabel("弹窗"))

        session_form_layout.addRow(self.random_checkbox)
        session_form_layout.addRow(self.full_list_checkbox)
        session_form_layout.addRow(self.remember_wordlist_checkbox)
        session_form_layout.addRow("开始按钮行为:", start_button_behavior_layout)
        
        layout.addWidget(session_group)

        # --- 组2: 智能跟读设置 ---
        follow_up_group = QGroupBox("智能跟读设置")
        follow_up_form_layout = QFormLayout(follow_up_group)

        self.enable_follow_up_checkbox = QCheckBox("启用智能跟读模式")
        self.enable_follow_up_checkbox.setToolTip("勾选后，在采集会话中可以临时启用智能跟读功能。")
        
        self.merge_recordings_checkbox = QCheckBox("将多次跟读合并到单个文件")
        self.merge_recordings_checkbox.setToolTip("勾选后，一个词条的所有跟读录音将连续录制并保存在一个文件中。\n取消勾选则每次跟读都保存为独立的、带编号的文件。")

        repetition_slider_layout = QHBoxLayout()
        self.repetition_slider = QSlider(Qt.Horizontal)
        self.repetition_slider.setRange(2, 30)
        self.repetition_slider.setToolTip("设置智能跟读模式下，每个词条需要跟读的总次数。")
        
        self.repetition_slider_label = QLabel("5 次")
        self.repetition_slider_label.setFixedWidth(40)
        self.repetition_slider_label.setAlignment(Qt.AlignCenter)
        self.repetition_slider.valueChanged.connect(lambda v: self.repetition_slider_label.setText(f"{v} 次"))
        repetition_slider_layout.addWidget(self.repetition_slider)
        repetition_slider_layout.addWidget(self.repetition_slider_label)

        follow_up_form_layout.addRow(self.enable_follow_up_checkbox)
        follow_up_form_layout.addRow(self.merge_recordings_checkbox)
        follow_up_form_layout.addRow("跟读总次数:", repetition_slider_layout)
        
        layout.addWidget(follow_up_group)
        layout.addStretch()

        self.nav_list.addItem("常规选项")
        self.stack.addWidget(page)

    def _create_advanced_page(self):
        """创建“高级”设置页面。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # --- 组1: 界面与性能 ---
        ui_perf_group = QGroupBox("界面与性能")
        ui_perf_form_layout = QFormLayout(ui_perf_group)
        
        self.show_waveform_checkbox = QCheckBox("显示波形预览列")
        self.show_waveform_checkbox.setToolTip("在词语列表中显示一个音频波形预览列。\n关闭此项可以在词条非常多时略微提升性能。")
        
        volume_slider_layout = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(10, 100)
        self.volume_slider.setTickInterval(10)
        self.volume_slider.setTickPosition(QSlider.TicksBelow)
        self.volume_slider.setToolTip("调整右侧音量计的刷新频率。\n值越小刷新越快，但CPU占用会略微增加。")
        
        self.volume_slider_label = QLabel("16 ms")
        self.volume_slider.valueChanged.connect(lambda v: self.volume_slider_label.setText(f"{v} ms"))
        volume_slider_layout.addWidget(self.volume_slider)
        volume_slider_layout.addWidget(self.volume_slider_label)
        
        ui_perf_form_layout.addRow(self.show_waveform_checkbox)
        ui_perf_form_layout.addRow("音量计刷新间隔:", volume_slider_layout)
        
        layout.addWidget(ui_perf_group)

        # --- 组2: 其他高级选项 ---
        other_advanced_group = QGroupBox("其他高级选项")
        advanced_form_layout = QFormLayout(other_advanced_group)
        
        self.default_note_input = QLineEdit()
        self.default_note_input.setPlaceholderText("例如: 清晰、快速")
        self.default_note_input.setToolTip("当词表中的某个词条没有备注信息时，\n将自动使用此处填写的内容。")
        
        self.cleanup_empty_folder_checkbox = QCheckBox("自动清理未录音的会话文件夹")
        self.cleanup_empty_folder_checkbox.setToolTip("勾选后，如果一个会话结束时没有产生任何有效的录音文件，\n程序将自动删除为该会话创建的空文件夹。")
        
        advanced_form_layout.addRow("默认备注内容:", self.default_note_input)
        advanced_form_layout.addRow(self.cleanup_empty_folder_checkbox)

        layout.addWidget(other_advanced_group)
        layout.addStretch()

        self.nav_list.addItem("高级")
        self.stack.addWidget(page)

    def accept(self):
        self.save_settings()
        super().accept()

    def load_settings(self):
        """从主配置加载所有设置并更新UI。"""
        module_states = self.parent_page.config.get("module_states", {}).get("accent_collection", {})
        
        # 常规选项页
        self.random_checkbox.setChecked(module_states.get("is_random", False))
        self.full_list_checkbox.setChecked(module_states.get("is_full_list", False))
        self.remember_wordlist_checkbox.setChecked(module_states.get("remember_last_wordlist", True))
        self.start_button_toggle.setChecked(module_states.get("start_button_action", "popup") == "popup")
        
        self.enable_follow_up_checkbox.setChecked(module_states.get("enable_smart_follow_up", False))
        self.merge_recordings_checkbox.setChecked(module_states.get("merge_follow_up_recordings", True))
        slider_value = module_states.get("follow_up_repetitions", 5)
        self.repetition_slider.setValue(slider_value)
        self.repetition_slider_label.setText(f"{slider_value} 次")

        # 高级页
        self.show_waveform_checkbox.setChecked(module_states.get("show_waveform", True))
        self.volume_slider.setValue(module_states.get("volume_meter_interval", 16))
        self.volume_slider_label.setText(f"{self.volume_slider.value()} ms")
        self.default_note_input.setText(module_states.get("default_note", ""))
        self.cleanup_empty_folder_checkbox.setChecked(module_states.get("cleanup_empty_folder", True))

    def save_settings(self):
        """将UI上的所有设置保存回主配置。"""
        main_window = self.parent_page.parent_window
        
        current_settings = main_window.config.get("module_states", {}).get("accent_collection", {}).copy()

        settings_from_dialog = {
            # 常规选项页
            "is_random": self.random_checkbox.isChecked(),
            "is_full_list": self.full_list_checkbox.isChecked(),
            "remember_last_wordlist": self.remember_wordlist_checkbox.isChecked(),
            "start_button_action": "popup" if self.start_button_toggle.isChecked() else "default",
            "enable_smart_follow_up": self.enable_follow_up_checkbox.isChecked(),
            "merge_follow_up_recordings": self.merge_recordings_checkbox.isChecked(),
            "follow_up_repetitions": self.repetition_slider.value(),
            
            # 高级页
            "show_waveform": self.show_waveform_checkbox.isChecked(),
            "volume_meter_interval": self.volume_slider.value(),
            "default_note": self.default_note_input.text().strip(),
            "cleanup_empty_folder": self.cleanup_empty_folder_checkbox.isChecked(),
        }

        current_settings.update(settings_from_dialog)

        main_window.update_and_save_module_state('accent_collection', current_settings)