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
                             QAbstractItemView, QMenu, QToolButton, QWidgetAction, QDialogButtonBox, QDialog, QCheckBox, QSlider)
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
        self.update_timer = None 
        self.prompt_mode = 'tts' # 默认提示音模式
        self.pinned_wordlists = []
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
        left_layout.addWidget(QLabel("测试词语列表:"))
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

    # [核心新增] 打开词表选择对话框的槽函数
    def open_wordlist_selector(self):
        dialog = WordlistSelectionDialog(self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_file_relpath:
            selected_file = dialog.selected_file_relpath
            self.current_wordlist_name = selected_file
            base_name = os.path.basename(selected_file)
            display_name, _ = os.path.splitext(base_name)
            self.word_list_select_btn.setText(display_name)
            self.word_list_select_btn.setToolTip(f"当前选择: {selected_file}")

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
        [v2.1 - 省略后缀版]
        此方法不再填充列表，而是根据配置设置默认的单词表，
        并在按钮上显示不带'.json'后缀的名称。
        """
        self.current_wordlist_name = ""
        default_list = self.config['file_settings'].get('word_list_file', '')
        
        if default_list:
            # 兼容旧配置可能存在的 .py 后缀
            if not default_list.endswith('.json') and default_list.endswith('.py'):
                 default_list = os.path.splitext(default_list)[0] + '.json'
            
            full_path = os.path.join(self.WORD_LIST_DIR, default_list)
            if os.path.exists(full_path):
                self.current_wordlist_name = default_list
                
                # [核心修改] 从完整路径中提取不带后缀的文件名用于显示
                base_name = os.path.basename(default_list)
                display_name, _ = os.path.splitext(base_name)
                
                self.word_list_select_btn.setText(display_name)
                self.word_list_select_btn.setToolTip(f"当前选择: {default_list}")
            else:
                self.word_list_select_btn.setText("请选择单词表...")
                self.word_list_select_btn.setToolTip("点击选择一个用于本次采集任务的单词表文件。")
        else:
            self.word_list_select_btn.setText("请选择单词表...")
            self.word_list_select_btn.setToolTip("点击选择一个用于本次采集任务的单词表文件。")

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
        self.pre_session_widget.show(); self.in_session_widget.hide(); self.record_btn.setEnabled(False); self.replay_btn.setEnabled(False); self.record_btn.setText("开始录制下一个")
        self.list_widget.setRowCount(0); self.status_label.setText("状态：准备就绪"); self.progress_bar.setVisible(False); self.progress_bar.setValue(0)
        
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
            
        # 2. 智能检测是否存在 'Record' 源 (不变)
        wordlist_name, _ = os.path.splitext(wordlist_file)
        record_source_path = os.path.join(self.AUDIO_RECORD_DIR, wordlist_name)
        record_source_exists = os.path.exists(record_source_path) and any(
            f.lower().endswith(('.wav', '.mp3')) for f in os.listdir(record_source_path)
        )
        
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
            create_menu_item(
                self.icon_manager.get_icon("play_audio"),
                "使用已有录音作为提示音",
                f"优先使用 '{wordlist_name}' 文件夹内已录制的人声\n作为提示音，这通常比TTS质量更高。",
                partial(self.start_session, prompt_mode='record')
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
        会检查所有支持的录音格式。
        """
        # [核心修复] 将所有可能的录音格式添加到一个列表中
        supported_formats = ['.wav', '.mp3', '.flac', '.ogg'] 
        
        # 优先在当前会话的录音文件夹中查找
        if self.recordings_folder:
            for ext in supported_formats:
                path = os.path.join(self.recordings_folder, f"{word}{ext}")
                if os.path.exists(path):
                    return path

        # 如果在会话文件夹中找不到，可以考虑在一个更通用的地方查找（此部分为可选扩展）
        # wordlist_name, _ = os.path.splitext(self.current_wordlist_name)
        # record_path_base = os.path.join(self.AUDIO_RECORD_DIR, wordlist_name)
        # for ext in supported_formats:
        #    path = os.path.join(record_path_base, f"{word}{ext}")
        #    if os.path.exists(path):
        #        return path
                
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
        if not self.is_recording:
            self.current_word_index=self.list_widget.currentRow()
            if self.current_word_index==-1: QMessageBox.information(self, "提示", "请先在左侧列表中选择一个词条。"); return
            word_to_record = self.current_word_list[self.current_word_index]['word']
            if self.logger: self.logger.log(f"[RECORDING_START] Word: '{word_to_record}'")
            self.is_recording=True; self.record_btn.setText("停止录制"); self.record_btn.setIcon(self.icon_manager.get_icon("stop")); self.record_btn.setToolTip("点击停止当前录音。")
            self.list_widget.setEnabled(False); self.random_switch.setEnabled(False);self.full_list_switch.setEnabled(False)
            self.status_label.setText(f"状态：正在录制 '{word_to_record}'..."); self.play_audio_logic(); self._start_recording_logic()
        else:
            self.is_recording=False; self._stop_recording_logic(); self.record_btn.setText("准备就绪"); self.record_btn.setIcon(self.icon_manager.get_icon("record"))
            self.record_btn.setToolTip("点击开始录制当前选中的词语。"); self.record_btn.setEnabled(False); self.status_label.setText("状态：正在保存录音...")
            
    def on_recording_saved(self, result):
        self.status_label.setText("状态：录音已保存。")
        self.list_widget.setEnabled(True)
        self.replay_btn.setEnabled(True)
        self.random_switch.setEnabled(True)
        self.full_list_switch.setEnabled(True)
    
        if result == "save_failed_mp3_encoder":
            QMessageBox.critical(self, "MP3 编码器缺失", "无法将录音保存为 MP3 格式。...")
            self.status_label.setText("状态：MP3保存失败！")
            return
        
        if self.current_word_index < 0 or self.current_word_index >= len(self.current_word_list):
            if self.logger: self.logger.log(f"[ERROR] current_word_index ({self.current_word_index}) out of bounds in on_recording_saved.")
            self.record_btn.setEnabled(True)
            return
        
        item_data = self.current_word_list[self.current_word_index]
        item_data['recorded'] = True
    
        list_item = self.list_widget.item(self.current_word_index, 0)
        filepath = self._find_existing_audio(item_data['word'])

        waveform_widget = self.list_widget.cellWidget(self.current_word_index, 2)
        if isinstance(waveform_widget, WaveformWidget):
            if filepath:
                waveform_widget.set_waveform_data(filepath)

        # 确保这里调用了质量分析插件的回调
        analyzer_plugin = getattr(self, 'quality_analyzer_plugin', None)
        if analyzer_plugin and filepath:
            analyzer_plugin.analyze_and_update_ui('accent_collection', filepath, self.current_word_index)
        else:
            # 如果插件不存在或文件路径无效，仍然需要更新为成功图标
            if list_item: list_item.setIcon(self.icon_manager.get_icon("success"))
            list_item.setToolTip(item_data['word']) # 确保Tooltip也被重置为原始词语
    
        waveform_widget = self.list_widget.cellWidget(self.current_word_index, 2)
        if isinstance(waveform_widget, WaveformWidget):
            if filepath:
                waveform_widget.set_waveform_data(filepath)
    
        # =================================================================
        # --- [核心修改] 在此处添加钩子调用 ---
        # =================================================================
        # 检查质量分析器插件的钩子是否存在
        analyzer_plugin = getattr(self, 'quality_analyzer_plugin', None)
        if analyzer_plugin and filepath:
            # 调用插件的API，传递模块ID、文件路径和行号
            analyzer_plugin.analyze_and_update_ui('accent_collection', filepath, self.current_word_index)
        # =================================================================
        # --- [核心修改] 结束 ---
        # =================================================================

        all_recorded = all(item['recorded'] for item in self.current_word_list)
        if all_recorded:
            self.handle_session_completion()
            return
        
        # ... (后续寻找下一个词条的逻辑保持不变) ...
        next_index = -1
        indices = list(range(len(self.current_word_list)))
        for i in indices[self.current_word_index+1:] + indices[:self.current_word_index]:
            if not self.current_word_list[i]['recorded']:
                next_index = i
                break
            
        if next_index != -1:
            self.list_widget.setCurrentCell(next_index, 0)
            self.record_btn.setEnabled(True)
            self.record_btn.setToolTip("点击开始录制当前选中的词语。")
            recorded_count = sum(1 for item in self.current_word_list if item['recorded'])
            self.record_btn.setText(f"开始录制 ({recorded_count + 1}/{len(self.current_word_list)})")
        else:
            self.handle_session_completion()

    def handle_session_completion(self):
        unrecorded_count=sum(1 for item in self.current_word_list if not item['recorded'])
        if self.current_word_list: QMessageBox.information(self,"会话结束",f"本次会话已结束。\n总共录制了 {len(self.current_word_list)-unrecorded_count} 个词语。")
        self.end_session()
        
    def on_list_item_changed(self):
        row = self.list_widget.currentRow()
        if row!=-1 and not self.is_recording: self.replay_btn.setEnabled(True)
        
    def replay_audio(self, item=None):
        self.play_audio_logic()
    
    def play_audio_logic(self, index=None):
        # [vNext 新增] 如果是静默模式，则不播放任何提示音
        if self.prompt_mode == 'silent':
            return

        if not self.session_active:
            return
        if index is None:
            index = self.list_widget.currentRow()
        if index == -1 or index >= len(self.current_word_list):
            return

        word = self.current_word_list[index]['word']
        wordlist_name, _ = os.path.splitext(self.current_wordlist_name)
        
        # 搜索路径逻辑保持不变，它会自动优先查找录音
        search_paths = [
            (os.path.join(self.AUDIO_RECORD_DIR, wordlist_name), ['.wav', '.mp3']),
            (os.path.join(self.AUDIO_TTS_DIR, wordlist_name), ['.wav', '.mp3'])
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
            
    def _audio_callback(self, indata, frames, time_info, status):
        if status and (status.input_overflow or status.output_overflow or status.priming_output):
            current_time = time.monotonic()
            if current_time - self.last_warning_log_time > 5:
                self.last_warning_log_time = current_time
                warning_msg = f"Audio callback status: {status}"
                print(warning_msg, file=sys.stderr)
                if self.logger: self.logger.log(f"[WARNING] {warning_msg}")
 
        # --- START OF FIX ---
        # 1. 将原始、未经修改的数据放入录音队列，用于最终保存。
        if self.is_recording:
            try:
                self.audio_queue.put(indata.copy())
            except queue.Full:
                pass
 
        # 2. 创建一个临时副本，应用增益，然后放入音量条队列，用于UI实时反馈。
        gain = self.config.get('audio_settings', {}).get('recording_gain', 1.0)
        
        # 如果增益不为1.0，则处理数据；否则直接使用原始数据以提高效率
        processed_for_meter = indata
        if gain != 1.0:
            # 使用 np.clip 防止应用增益后数据超出范围，这对于音量条的准确性很重要
            processed_for_meter = np.clip(indata * gain, -1.0, 1.0)
 
        try:
            # 将处理过的数据放入音量条队列
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
        recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower(); word = self.current_word_list[self.current_word_index]['word']; filename = f"{word}.{recording_format}"
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
        
    def load_word_list_logic(self):
        filename = self.current_wordlist_name
        filepath = os.path.join(self.WORD_LIST_DIR, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"找不到单词表文件: {filename}")

        # [修改] 使用 json.load() 读取并解析
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"词表文件 '{filename}' 不是有效的JSON格式: {e}")

        # 验证文件格式并转换为内部使用的 WORD_GROUPS 格式
        if "meta" not in data or data.get("meta", {}).get("format") != "standard_wordlist" or "groups" not in data:
            raise ValueError(f"词表文件 '{filename}' 格式不正确或不受支持。")

        word_groups = []
        for group_data in data.get("groups", []):
            group_dict = {}
            group_items = group_data.get("items", [])
            for item in group_items:
                # 兼容新旧格式，note 和 lang 都是可选的
                text = item.get("text")
                if text:
                    note = item.get("note", "")
                    lang = item.get("lang", "")
                    group_dict[text] = (note, lang)
            if group_dict:
                word_groups.append(group_dict)
        
        return word_groups
        
    def _proceed_to_start_session(self):
        """封装了开始录音会话的核心逻辑。"""
        self.session_stop_event.clear()
        self.recording_thread = threading.Thread(target=self._persistent_recorder_task, daemon=True)
        self.recording_thread.start()
        self.update_timer.start()
        
        self.status_label.setText("状态：音频准备就绪。")
        self.pre_session_widget.hide()
        self.in_session_widget.show()
        self.record_btn.setEnabled(True)
        self.session_active = True
        
        self.prepare_word_list()
        if self.current_word_list:
            recorded_count = sum(1 for item in self.current_word_list if item['recorded'])
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
        wordlist_name, _ = os.path.splitext(self.current_wordlist_name)
        tts_audio_folder = os.path.join(self.AUDIO_TTS_DIR, wordlist_name)
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
                wordlist_record_dir = os.path.join(self.AUDIO_RECORD_DIR, wordlist_name)
                user_recorded_exists = any(os.path.exists(os.path.join(wordlist_record_dir, f"{word}{ext}")) for ext in ['.wav', '.mp3', '.flac', '.ogg'])
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
    [v2.0] 一个专门用于配置“标准朗读采集”模块的对话框。
    包含多种控件类型作为未来模块的参考。
    """
    def __init__(self, parent_page):
        # parent_page 是 AccentCollectionPage 的实例
        super().__init__(parent_page)
        
        self.parent_page = parent_page
        self.setWindowTitle("标准朗读采集设置")
        self.setWindowIcon(self.parent_page.parent_window.windowIcon())
        self.setStyleSheet(self.parent_page.parent_window.styleSheet())
        self.setMinimumWidth(400) # 稍微加宽以容纳更多内容
        
        # 主布局
        layout = QVBoxLayout(self)
        
        # --- 组1: 会话默认行为 ---
        session_group = QGroupBox("会话默认行为")
        session_form_layout = QFormLayout(session_group)
        
        self.random_checkbox = QCheckBox("默认以随机顺序开始会话")
        self.random_checkbox.setToolTip("勾选后，新会使话用默认会打乱词表顺序。")
        
        self.full_list_checkbox = QCheckBox("默认使用完整词表")
        self.full_list_checkbox.setToolTip("勾选后，新会话默认会使用词表中的所有词条。")
        
        # [新增] ToggleSwitch 用于配置启动按钮行为
        start_button_behavior_layout = QHBoxLayout()
        self.start_button_toggle = self.parent_page.ToggleSwitch()
        start_button_behavior_layout.addWidget(QLabel("默认"))
        start_button_behavior_layout.addWidget(self.start_button_toggle)
        start_button_behavior_layout.addWidget(QLabel("弹窗"))
        
        session_form_layout.addRow(self.random_checkbox)
        session_form_layout.addRow(self.full_list_checkbox)
        session_form_layout.addRow("开始按钮行为:", start_button_behavior_layout)
        
        layout.addWidget(session_group)
        
        # --- 组2: 界面与性能 ---
        ui_perf_group = QGroupBox("界面与性能")
        ui_perf_form_layout = QFormLayout(ui_perf_group)
        
        # [新增] 波形图显隐 Checkbox
        self.show_waveform_checkbox = QCheckBox("显示波形预览列")
        self.show_waveform_checkbox.setToolTip("取消勾选可隐藏波形图列，有助于在词表非常大时提升性能。")
        # [新增] 单击/双击选择模式的 Checkbox
        self.single_click_select_checkbox = QCheckBox("单击选择词表 (默认为双击)")
        self.single_click_select_checkbox.setToolTip("勾选后，在词表选择对话框中单击即可选定文件。")
        
        # [新增] 音量计刷新率 Slider
        volume_slider_layout = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(10, 100) # 10ms - 100ms
        self.volume_slider.setTickInterval(10)
        self.volume_slider.setTickPosition(QSlider.TicksBelow)
        self.volume_slider_label = QLabel("16 ms") # 默认值
        self.volume_slider.valueChanged.connect(lambda v: self.volume_slider_label.setText(f"{v} ms"))
        
        volume_slider_layout.addWidget(self.volume_slider)
        volume_slider_layout.addWidget(self.volume_slider_label)
        
        ui_perf_form_layout.addRow(self.show_waveform_checkbox)
        ui_perf_form_layout.addRow("音量计刷新间隔:", volume_slider_layout)
        
        layout.addWidget(ui_perf_group)

        # --- 组3: 高级选项 ---
        advanced_group = QGroupBox("高级选项")
        advanced_form_layout = QFormLayout(advanced_group)
        
        self.default_note_input = QLineEdit()
        self.default_note_input.setPlaceholderText("例如: 清晰、快速")
        self.default_note_input.setToolTip("在这里输入的文本将作为词表中“备注”为空时的默认值。")
        
        # [新增] 自动清理空文件夹的 Checkbox
        self.cleanup_empty_folder_checkbox = QCheckBox("自动清理未录音的会话文件夹")
        self.cleanup_empty_folder_checkbox.setToolTip("勾选后，如果一个会话结束时没有录制任何音频，\n其对应的结果文件夹将被自动删除。")
        
        advanced_form_layout.addRow("默认备注内容:", self.default_note_input)
        advanced_form_layout.addRow(self.cleanup_empty_folder_checkbox) # 添加到布局中

        layout.addWidget(advanced_group)
        
        # OK 和 Cancel 按钮
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        layout.addWidget(self.button_box)
        
        self.load_settings()

    def load_settings(self):
        """从主配置加载所有设置并更新UI。"""
        # 使用父页面的 config 对象来获取状态
        module_states = self.parent_page.config.get("module_states", {}).get("accent_collection", {})
        
        # 会话设置
        self.random_checkbox.setChecked(module_states.get("is_random", False))
        self.full_list_checkbox.setChecked(module_states.get("is_full_list", False))
        # start_button_action: "popup" (弹窗) 或 "default" (默认TTS)
        self.start_button_toggle.setChecked(module_states.get("start_button_action", "popup") == "popup")
        
        # 界面与性能设置
        self.show_waveform_checkbox.setChecked(module_states.get("show_waveform", True))
        self.volume_slider.setValue(module_states.get("volume_meter_interval", 16))
        self.volume_slider_label.setText(f"{self.volume_slider.value()} ms")
        
        # 高级设置
        self.default_note_input.setText(module_states.get("default_note", ""))
        self.cleanup_empty_folder_checkbox.setChecked(module_states.get("cleanup_empty_folder", True)) # 默认启用


    def save_settings(self):
        """将UI上的所有设置保存回主配置。"""
        # 使用父页面的主窗口引用来调用保存API
        main_window = self.parent_page.parent_window
        
        # 准备要保存的设置字典
        settings_to_save = {
            "is_random": self.random_checkbox.isChecked(),
            "is_full_list": self.full_list_checkbox.isChecked(),
            "start_button_action": "popup" if self.start_button_toggle.isChecked() else "default",
            "show_waveform": self.show_waveform_checkbox.isChecked(),
            "volume_meter_interval": self.volume_slider.value(),
            "default_note": self.default_note_input.text().strip(),
            "cleanup_empty_folder": self.cleanup_empty_folder_checkbox.isChecked(),
        }
        
        # 调用主窗口的API来更新并保存
        main_window.update_and_save_module_state('accent_collection', settings_to_save)

    def accept(self):
        """重写 accept 方法，在关闭对话框前先保存设置。"""
        self.save_settings()
        super().accept()