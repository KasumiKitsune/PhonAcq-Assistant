# --- START OF FILE modules/voicebank_recorder_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "提示音录制"
MODULE_DESCRIPTION = "为标准词表录制高质量的真人提示音，以替代在线TTS。"
# ---

import os
import sys
import threading
import queue
import time
import json
from collections import deque
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget,
                             QTableWidgetItem, QMessageBox, QComboBox, QFormLayout,
                             QGroupBox, QProgressBar, QStyle, QHeaderView, QAbstractItemView,
                             QLineEdit, QDialog, QSlider, QDialogButtonBox, QCheckBox) # [新增] 导入 QLineEdit
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, pyqtProperty
from PyQt5.QtGui import QIcon, QPainter, QPen, QPalette, QColor
from modules.custom_widgets_module import WordlistSelectionDialog
try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
    DEPENDENCIES_MISSING = False
except ImportError as e:
    DEPENDENCIES_MISSING = True
    MISSING_ERROR_MESSAGE = str(e)

# --- 波形预览控件 (无变动) ---
class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(40)
        self._waveform_data = None
        self._waveformColor = self.palette().color(QPalette.Highlight)
        self._cursorColor = QColor("red")
        self._selectionColor = QColor(0, 100, 255, 60)
    @pyqtProperty(QColor)
    def waveformColor(self): return self._waveformColor
    @waveformColor.setter
    def waveformColor(self, color):
        if self._waveformColor != color: self._waveformColor = color; self.update()
    @pyqtProperty(QColor)
    def cursorColor(self): return self._cursorColor
    @cursorColor.setter
    def cursorColor(self, color):
        if self._cursorColor != color: self._cursorColor = color; self.update()
    @pyqtProperty(QColor)
    def selectionColor(self): return self._selectionColor
    @selectionColor.setter
    def selectionColor(self, color):
        if self._selectionColor != color: self._selectionColor = color; self.update()
    def set_waveform_data(self, audio_filepath):
        self._waveform_data = None
        if not (audio_filepath and os.path.exists(audio_filepath)): self.update(); return
        try:
            data, sr = sf.read(audio_filepath, dtype='float32')
            if data.ndim > 1: data = data.mean(axis=1)
            num_samples = len(data); target_points = self.width() * 2 if self.width() > 0 else 400
            if num_samples <= target_points: self._waveform_data = data
            else:
                step = num_samples // target_points
                peak_data = [np.max(np.abs(data[i:i+step])) for i in range(0, num_samples, step)]
                self._waveform_data = np.array(peak_data)
        except Exception as e: self._waveform_data = None
        self.update()
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.palette().color(QPalette.Base))
        if self._waveform_data is None or len(self._waveform_data) == 0: return
        pen = QPen(self._waveformColor, 1); painter.setPen(pen)
        h, w, num_points = self.height(), self.width(), len(self._waveform_data)
        half_h = h / 2; max_val = np.max(self._waveform_data)
        if max_val == 0: max_val = 1.0
        for i, val in enumerate(self._waveform_data):
            x = int(i * w / num_points); y_offset = (val / max_val) * half_h
            painter.drawLine(x, int(half_h - y_offset), x, int(half_h + y_offset))

# --- 模块入口函数 (无变动) ---
def create_page(parent_window, WORD_LIST_DIR, AUDIO_RECORD_DIR, ToggleSwitchClass, WorkerClass, LoggerClass, icon_manager, resolve_device_func):
    if DEPENDENCIES_MISSING:
        error_page = QWidget(); layout = QVBoxLayout(error_page)
        label = QLabel(f"提示音录制模块加载失败：\n缺少必要的依赖库。\n\n错误: {MISSING_ERROR_MESSAGE}\n\n请运行: pip install sounddevice soundfile numpy")
        label.setAlignment(Qt.AlignCenter); label.setWordWrap(True); layout.addWidget(label)
        return error_page
    return VoicebankRecorderPage(parent_window, WORD_LIST_DIR, AUDIO_RECORD_DIR, ToggleSwitchClass, WorkerClass, LoggerClass, icon_manager, resolve_device_func)


class VoicebankRecorderPage(QWidget):
    recording_device_error_signal = pyqtSignal(str)

    def __init__(self, parent_window, WORD_LIST_DIR, AUDIO_RECORD_DIR, ToggleSwitchClass, WorkerClass, LoggerClass, icon_manager, resolve_device_func):
        super().__init__()
        self.parent_window = parent_window; self.WORD_LIST_DIR = WORD_LIST_DIR; self.AUDIO_RECORD_DIR = AUDIO_RECORD_DIR
        self.ToggleSwitch = ToggleSwitchClass; self.Worker = WorkerClass; self.LoggerClass = LoggerClass
        self.icon_manager = icon_manager
        self.resolve_device_func = resolve_device_func
        self.config = self.parent_window.config
        self.session_active = False; self.is_recording = False
        # [核心修改] 新增或修改以下属性
        self.current_word_list = []
        self.current_word_index = -1
        self.current_wordlist_name = "" # 用于存储当前选中的词表相对路径
        self.pinned_wordlists = []      # 用于支持固定功能
        self.logger = None
        self.audio_folder = None # [新增] 用于存储当前会话的动态文件夹路径
        self.audio_queue = queue.Queue(); self.volume_meter_queue = queue.Queue(maxsize=2)
        self.volume_history = deque(maxlen=5)
        self.recording_thread = None; self.session_stop_event = threading.Event()
        self.last_warning_log_time = 0
        
        self._init_ui()
        self._connect_signals()
        self.update_icons()
        self.setFocusPolicy(Qt.StrongFocus)
        self.apply_layout_settings()
        self.load_config_and_prepare()

    def _init_ui(self):
        main_layout = QHBoxLayout(self); left_layout = QVBoxLayout()
        self.right_panel = QWidget(); right_layout = QVBoxLayout(self.right_panel)
        self.list_widget = QTableWidget()
        self.list_widget.setColumnCount(3)
        self.list_widget.setHorizontalHeaderLabels(["词语", "IPA/备注", "波形预览"])
        self.list_widget.verticalHeader().setVisible(False)
        self.list_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setWordWrap(True)
        header = self.list_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive); header.setSectionResizeMode(1, QHeaderView.Interactive); header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setStretchLastSection(True)
        self.list_widget.setToolTip("当前词表中所有需要录制的词语。\n- 绿色对勾表示已录制。\n- 双击任意行可试听已录制的音频。")
        self.status_label = QLabel("状态：请选择一个单词表开始录制。")
        left_layout.addWidget(QLabel("待录制词语列表:")); left_layout.addWidget(self.list_widget); left_layout.addWidget(self.status_label)
        
        control_group = QGroupBox("控制面板")
        # [核心修改] 使用 QVBoxLayout 替换 QFormLayout
        self.control_layout = QVBoxLayout(control_group) 
        self.control_layout.setSpacing(10) # 增加控件间的垂直间距

        # 创建所有控件...
        wordlist_label = QLabel("选择单词表:") # 创建标签
        self.word_list_select_btn = QPushButton("请选择单词表...")
        self.word_list_select_btn.setToolTip("点击选择一个用于录制提示音的单词表。")
        
        session_name_label = QLabel("录音批次名称:") # 创建标签
        self.session_name_input = QLineEdit()
        self.session_name_input.setToolTip("为本次录制指定一个批次名称...")
        
        self.start_btn = QPushButton("加载词表并开始")
        self.start_btn.setObjectName("AccentButton")
        self.end_session_btn = QPushButton("结束当前会话")
        self.end_session_btn.setObjectName("ActionButton_Delete")
        
        # [核心修改] 按顺序将标签和控件逐个添加到 QVBoxLayout 中
        self.control_layout.addWidget(wordlist_label)
        self.control_layout.addWidget(self.word_list_select_btn)
        self.control_layout.addWidget(session_name_label)
        self.control_layout.addWidget(self.session_name_input)
        self.control_layout.addStretch() # 添加弹簧将按钮推向底部
        self.control_layout.addWidget(self.start_btn)
        self.control_layout.addWidget(self.end_session_btn)

        self.end_session_btn.hide()
        self.recording_status_panel = QGroupBox("录音状态"); status_panel_layout = QVBoxLayout(self.recording_status_panel)
        self.recording_indicator = QLabel("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;")
        self.volume_label = QLabel("当前音量:"); self.volume_meter = QProgressBar(); self.volume_meter.setRange(0, 100); self.volume_meter.setValue(0); self.volume_meter.setTextVisible(False)
        status_panel_layout.addWidget(self.recording_indicator); status_panel_layout.addWidget(self.volume_label); status_panel_layout.addWidget(self.volume_meter)
        self.update_timer = QTimer(); self.update_timer.timeout.connect(self.update_volume_meter)
        
        self.record_btn = QPushButton("按住录音"); self.record_btn.setEnabled(False); self.record_btn.setToolTip("按住此按钮或键盘的回车键，为当前选中的词语录音。")
        
        right_layout.addWidget(control_group); right_layout.addStretch(); right_layout.addWidget(self.recording_status_panel); right_layout.addWidget(self.record_btn)
        main_layout.addLayout(left_layout, 2); main_layout.addWidget(self.right_panel, 1)

    def _connect_signals(self):
        self.word_list_select_btn.clicked.connect(self.open_wordlist_selector)
        self.start_btn.clicked.connect(self.start_session)
        self.end_session_btn.clicked.connect(self.end_session)
        self.record_btn.pressed.connect(self.start_recording)
        self.record_btn.released.connect(self.stop_recording)
        self.recording_device_error_signal.connect(self.show_recording_device_error)
        self.list_widget.cellDoubleClicked.connect(self.on_cell_double_clicked) # 新增连接

    def open_wordlist_selector(self):
        dialog = WordlistSelectionDialog(self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_file_relpath:
            selected_file = dialog.selected_file_relpath
            self.current_wordlist_name = selected_file
            
            base_name = os.path.basename(selected_file)
            display_name, _ = os.path.splitext(base_name)
            
            # 更新按钮文本
            self.word_list_select_btn.setText(display_name)
            self.word_list_select_btn.setToolTip(f"当前选择: {selected_file}")
            
            # [差异点实现] 自动填充批次名称
            self.session_name_input.setText(display_name)

    def on_cell_double_clicked(self, row, column):
        """处理双击事件，用于试听。"""
        self.replay_audio(row)
        
    def replay_audio(self, row):
        """播放指定行号的音频。"""
        if not self.session_active or not (0 <= row < len(self.current_word_list)):
            return
            
        word = self.current_word_list[row]['word']
        filepath = self._find_existing_audio(word)
        if filepath:
            self.log(f"正在试听: {os.path.basename(filepath)}")
            self._robust_play_sound(filepath)
        else:
            self.log(f"提示: '{word}' 尚未录制，无法试听。")

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
            
    def _robust_play_sound(self, path):
        """在一个独立的非守护线程中播放音频，避免UI卡顿。"""
        playback_thread = threading.Thread(target=self._play_sound_task, args=(path,), daemon=False)
        playback_thread.start()

    def _play_sound_task(self, path):
        """实际执行音频播放的线程任务。"""
        try:
            data, sr = sf.read(path)
            sd.play(data, sr)
            sd.wait()
        except Exception as e:
            print(f"播放音频 '{path}' 失败: {e}")

    def start_session(self):
        wordlist_file = self.current_wordlist_name
        if not wordlist_file:
            QMessageBox.warning(self, "错误", "请先选择一个单词表。")
            return

        # [核心重构] 实现带版本控制的文件夹创建逻辑
        session_base_name = self.session_name_input.text().strip()
        if not session_base_name:
            session_base_name, _ = os.path.splitext(wordlist_file) # 如果留空，默认使用词表名

        # 确定最终的、唯一的文件夹名称
        final_folder_name = session_base_name
        i = 1
        while os.path.exists(os.path.join(self.AUDIO_RECORD_DIR, final_folder_name)):
            final_folder_name = f"{session_base_name}_{i}"
            i += 1
        
        self.audio_folder = os.path.join(self.AUDIO_RECORD_DIR, final_folder_name)
        os.makedirs(self.audio_folder)
        
        self.log(f"新录音批次文件夹已创建: {final_folder_name}")

        self.logger = None
        if self.config.get("app_settings", {}).get("enable_logging", True):
            self.logger = self.LoggerClass(os.path.join(self.audio_folder, "log.txt"))
            
        try:
            word_groups = self.load_word_list_logic(wordlist_file)
            self.current_word_list = []
            for group in word_groups:
                for word, value in group.items():
                    ipa = value[0] if isinstance(value, tuple) else str(value)
                    self.current_word_list.append({'word': word, 'ipa': ipa})
            
            self.current_word_index = 0
            if self.logger:
                self.logger.log(f"[SESSION_START] Voicebank recording for wordlist: '{wordlist_file}'")
                self.logger.log(f"[SESSION_CONFIG] Batch Name: '{session_base_name}', Final Output Folder: '{self.audio_folder}'")

            self.session_stop_event.clear()
            self.recording_thread = threading.Thread(target=self._persistent_recorder_task, daemon=True)
            self.recording_thread.start()
            self.update_timer.start()
            
            # [核心修复] 隐藏新的按钮，而不是旧的下拉框
            self.word_list_select_btn.hide()
            self.session_name_input.hide()
            self.start_btn.hide()
            self.end_session_btn.show()

            self.update_list_widget()
            self.record_btn.setEnabled(True)
            self.log("准备就绪，请选择词语并录音。")
            self.session_active = True
        except Exception as e: 
            if self.logger: self.logger.log(f"[ERROR] Failed to start session: {e}")
            QMessageBox.critical(self, "错误", f"加载单词表失败: {e}")
            self.session_active = False
            # 如果启动失败，需要清理已创建的空文件夹
            if os.path.exists(self.audio_folder) and not os.listdir(self.audio_folder):
                os.rmdir(self.audio_folder)

    def reset_ui(self):
        # [核心修复] 将 self.word_list_combo.show() 改为 self.word_list_select_btn.show()
        self.word_list_select_btn.show()
        self.session_name_input.show()
        self.start_btn.show()
        self.end_session_btn.hide()
        
        self.list_widget.setRowCount(0)
        self.record_btn.setEnabled(False)
        self.log("请选择一个单词表开始录制。")
        
        # [核心修复] populate_word_lists 会处理按钮的文本，
        # 但我们仍然需要手动重置批次名称输入框
        self.populate_word_lists()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.list_widget.width() > 0:
            w1 = int(self.list_widget.width() * 0.5); w2 = int(self.list_widget.width() * 0.25)
            self.list_widget.setColumnWidth(0, w1); self.list_widget.setColumnWidth(1, w2); self.list_widget.setColumnWidth(2, self.list_widget.width() - w1 - w2 - 20)
    def update_icons(self):
        self.start_btn.setIcon(self.icon_manager.get_icon("start_session")); self.end_session_btn.setIcon(self.icon_manager.get_icon("end_session"))
        self.record_btn.setIcon(self.icon_manager.get_icon("record")); self.update_list_widget_icons()
    def update_list_widget_icons(self):
        if not self.session_active: return
        for index in range(self.list_widget.rowCount()):
            item = self.list_widget.item(index, 0);
            if not item: continue
            if self._find_existing_audio(item.text()): item.setIcon(self.icon_manager.get_icon("success"))
            else: item.setIcon(QIcon())
    def apply_layout_settings(self):
        self.right_panel.setFixedWidth(self.config.get("ui_settings", {}).get("collector_sidebar_width", 320))
    def load_config_and_prepare(self):
        self.config = self.parent_window.config
        self.apply_layout_settings()

        # [核心新增] 从 accent_collection 的模块状态中加载共享的固定列表
        # 这提供了一致的用户体验
        shared_states = self.config.get("module_states", {}).get("accent_collection", {})
        self.pinned_wordlists = shared_states.get("pinned_wordlists", [])

        # [核心新增] 加载本模块的专属设置并应用
        module_states = self.config.get("module_states", {}).get("voicebank_recorder", {})
        interval = module_states.get("volume_meter_interval", 16)
        if self.update_timer:
            self.update_timer.setInterval(interval)
        # [核心新增] 应用波形图显隐设置
        show_waveform = module_states.get("show_waveform", True)
        # 索引为 2 的列是 "波形预览"
        self.list_widget.setColumnHidden(2, not show_waveform)
        
        if not self.session_active:
            self.populate_word_lists()

    def open_settings_dialog(self):
        """
        打开此模块的设置对话框，并在确认后请求主窗口进行彻底刷新。
        """
        dialog = SettingsDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            # 请求主窗口进行一次彻底的销毁重建，以确保所有设置（特别是定时器间隔）被应用
            self.parent_window.request_tab_refresh(self)

    # [核心新增] 添加这三个方法以支持 WordlistSelectionDialog 的固定功能
    def is_wordlist_pinned(self, rel_path):
        """检查一个词表是否已被固定。"""
        return rel_path in self.pinned_wordlists

    def toggle_pin_wordlist(self, rel_path):
        """固定或取消固定一个词表，并保存状态。"""
        if self.is_wordlist_pinned(rel_path):
            self.pinned_wordlists.remove(rel_path)
        else:
            if len(self.pinned_wordlists) >= 3:
                QMessageBox.warning(self, "固定已达上限", "最多只能固定3个单词表。")
                return
            self.pinned_wordlists.append(rel_path)
        
        self._save_pinned_wordlists()

    def _save_pinned_wordlists(self):
        """将共享的固定列表保存回 accent_collection 的模块状态中。"""
        self.parent_window.update_and_save_module_state(
            'accent_collection', 
            'pinned_wordlists', 
            self.pinned_wordlists
        )
    def _audio_callback(self, indata, frames, time, status):
        if status:
            current_time = time.monotonic()
            if current_time - self.last_warning_log_time > 5:
                self.last_warning_log_time = current_time
                print(f"Audio callback status: {status}", file=sys.stderr)
 
        # --- START OF FIX ---
        # 1. 将原始、未经修改的数据放入录音队列，用于最终保存。
        if self.is_recording:
            try:
                self.audio_queue.put(indata.copy())
            except queue.Full:
                pass
 
        # 2. 创建一个临时副本，应用增益，然后放入音量条队列，用于UI实时反馈。
        gain = self.config.get('audio_settings', {}).get('recording_gain', 1.0)
        
        processed_for_meter = indata
        if gain != 1.0:
            processed_for_meter = np.clip(indata * gain, -1.0, 1.0)
 
        try:
            self.volume_meter_queue.put_nowait(processed_for_meter.copy())
        except queue.Full:
            pass
    def show_recording_device_error(self, error_message):
        QMessageBox.critical(self, "录音设备错误", error_message); self.log("录音设备错误，请检查设置。")
        if self.session_active: self.end_session(force=True)
    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.record_btn.isEnabled(): self.start_recording(); event.accept()
        else: super().keyPressEvent(event)
    def keyReleaseEvent(self, event):
        if (event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter) and not event.isAutoRepeat():
            if self.is_recording: self.stop_recording(); event.accept()
        else: super().keyReleaseEvent(event)
    def update_volume_meter(self):
        # --- START OF REFACTOR (V3) ---
        raw_target_value = 0
        try:
            data_chunk = self.volume_meter_queue.get_nowait()
            rms = np.linalg.norm(data_chunk) / np.sqrt(len(data_chunk)) if data_chunk.any() else 0
            dbfs = 20 * np.log10(rms + 1e-7)
            raw_target_value = max(0, min(100, (dbfs + 60) * (100 / 60)))
        except queue.Empty:
            raw_target_value = 0
        except Exception:
            pass
 
        self.volume_history.append(raw_target_value)
        smoothed_target_value = sum(self.volume_history) / len(self.volume_history)
 
        current_value = self.volume_meter.value()
        smoothing_factor = 0.4
        new_value = int(current_value * (1 - smoothing_factor) + smoothed_target_value * smoothing_factor)
        
        if abs(new_value - smoothed_target_value) < 2:
            new_value = int(smoothed_target_value)
            
        self.volume_meter.setValue(new_value)

    def start_recording(self):
        if not self.session_active or self.is_recording: return
        self.current_word_index = self.list_widget.currentRow()
        if self.current_word_index == -1: self.log("请先在列表中选择一个词！"); return
        while not self.audio_queue.empty():
            try: self.audio_queue.get_nowait()
            except queue.Empty: break
        self.is_recording = True; self.recording_indicator.setText("● 正在录音"); self.recording_indicator.setStyleSheet("color: red;"); self.record_btn.setText("正在录音..."); self.record_btn.setStyleSheet("background-color: #f44336; color: white;")
        word_to_record = self.current_word_list[self.current_word_index]['word']; self.log(f"录制 '{word_to_record}'");
        if self.logger: self.logger.log(f"[RECORD_START] Word: '{word_to_record}'")
    def stop_recording(self):
        if not self.session_active or not self.is_recording: return
        self.is_recording = False; self.recording_indicator.setText("● 未在录音"); self.recording_indicator.setStyleSheet("color: grey;"); self.record_btn.setText("按住录音"); self.record_btn.setStyleSheet(""); self.log("正在保存..."); self.run_task_in_thread(self.save_recording_task)
    def log(self, msg): self.status_label.setText(f"状态: {msg}")
    def populate_word_lists(self):
        """
        [v2.0 重构版] 此方法不再填充列表，而是根据配置设置默认的单词表。
        """
        self.current_wordlist_name = ""
        # 注意：这里我们继续使用 accent_collection 的 file_settings 来获取默认值，以保持体验一致
        default_list = self.config['file_settings'].get('word_list_file', '')
        
        if default_list:
            full_path = os.path.join(self.WORD_LIST_DIR, default_list)
            if os.path.exists(full_path):
                self.current_wordlist_name = default_list
                base_name = os.path.basename(default_list)
                display_name, _ = os.path.splitext(base_name)
                
                self.word_list_select_btn.setText(display_name)
                self.word_list_select_btn.setToolTip(f"当前选择: {default_list}")
                # 同时更新批次名称输入框
                self.session_name_input.setText(display_name)
            else:
                self.word_list_select_btn.setText("请选择单词表...")
                self.session_name_input.setText("")
        else:
            self.word_list_select_btn.setText("请选择单词表...")
            self.session_name_input.setText("")
    def end_session(self, force=False):
        if not force:
            if QMessageBox.question(self, '结束会话', '您确定要结束当前的语音包录制会话吗？', QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        if self.logger: self.logger.log("[SESSION_END] Session ended by user.")
        self.update_timer.stop(); self.volume_meter.setValue(0); self.session_stop_event.set()
        if self.recording_thread and self.recording_thread.is_alive(): self.recording_thread.join(timeout=1.0)
        self._cleanup_empty_session_folder()
        self.recording_thread = None; self.session_active = False; self.current_word_list = []; self.current_word_index = -1; self.logger = None; self.audio_folder = None; self.reset_ui()
    # [核心新增] 添加清理方法
    def _cleanup_empty_session_folder(self):
        """
        在会话结束时，根据设置检查并清理空的录音批次文件夹。
        """
        # 1. 从配置中读取是否启用此功能
        module_states = self.config.get("module_states", {}).get("voicebank_recorder", {})
        is_cleanup_enabled = module_states.get("cleanup_empty_folder", True)
        
        if not is_cleanup_enabled:
            return

        # 2. 安全检查：确保文件夹路径存在且是一个目录
        if not self.audio_folder or not os.path.isdir(self.audio_folder):
            return

        try:
            # 3. 检查文件夹内是否有音频文件
            items_in_folder = os.listdir(self.audio_folder)
            audio_extensions = ('.wav', '.mp3', '.flac', '.ogg', '.m4a')
            has_audio_files = any(item.lower().endswith(audio_extensions) for item in items_in_folder)
            
            # 如果有音频文件，则不做任何操作
            if has_audio_files:
                return

            # 4. 如果没有音频文件，则删除文件夹
            # （我们假设如果只剩下log.txt，也应该删除，因为这是提示音录制，核心是音频）
            folder_to_delete = self.audio_folder
            self.log("会话结束。已自动清理空的结果文件夹。")
            if self.logger:
                self.logger.log(f"[CLEANUP] Session folder '{os.path.basename(folder_to_delete)}' contains no audio. Deleting.")
            
            import shutil
            shutil.rmtree(folder_to_delete)
            print(f"[INFO] Cleaned up empty session folder: {folder_to_delete}")

        except Exception as e:
            print(f"[ERROR] Failed to cleanup empty session folder '{self.audio_folder}': {e}")

    def _find_existing_audio(self, word):
        if not self.audio_folder: return None
        for ext in ['.wav', '.mp3', '.flac', '.ogg']:
             path = os.path.join(self.audio_folder, f"{word}{ext}")
             if os.path.exists(path): return path
        return None
    def update_list_widget(self):
        current_row = self.list_widget.currentRow();
        if current_row == -1 and self.current_word_list: current_row = 0
        self.list_widget.setRowCount(0); self.list_widget.setRowCount(len(self.current_word_list))
        for i, item_data in enumerate(self.current_word_list):
            word_item = QTableWidgetItem(item_data['word']); ipa_item = QTableWidgetItem(item_data['ipa'])
            self.list_widget.setItem(i, 0, word_item); self.list_widget.setItem(i, 1, ipa_item)
            waveform_widget = WaveformWidget(self); self.list_widget.setCellWidget(i, 2, waveform_widget)
            filepath = self._find_existing_audio(item_data['word'])
            if filepath: word_item.setIcon(self.icon_manager.get_icon("success")); waveform_widget.set_waveform_data(filepath)
        self.list_widget.resizeRowsToContents()
        if self.current_word_list and 0 <= current_row < len(self.current_word_list): self.list_widget.setCurrentCell(current_row, 0)
    def on_recording_saved(self, result):
        """
        槽函数：当后台保存录音任务完成后被调用。
        
        Args:
            result (str or None): 保存任务的结果字符串。
        """
        # --- 1. 处理保存失败的情况 ---
        if result == "save_failed_mp3_encoder":
            QMessageBox.critical(self, "MP3 编码器缺失", "无法将录音保存为 MP3 格式。请确保已安装 LAME MP3 编码器。")
            self.log("MP3保存失败！")
            return
        
        # --- 2. 更新UI状态和数据 ---
        self.log("录音已保存.")
        
        # 获取当前录制的词条信息
        word_data = self.current_word_list[self.current_word_index]
        word_text = word_data['word']
        
        # 查找刚刚保存的文件路径
        filepath = self._find_existing_audio(word_text)
        
        # 更新表格中的图标和波形图
        list_item = self.list_widget.item(self.current_word_index, 0)
        waveform_widget = self.list_widget.cellWidget(self.current_word_index, 2)
        
        if isinstance(waveform_widget, WaveformWidget) and filepath:
            waveform_widget.set_waveform_data(filepath)

        # --- 3. 调用质量分析插件钩子 (如果存在) ---
        analyzer_plugin = getattr(self, 'quality_analyzer_plugin', None)
        if analyzer_plugin and filepath:
            # 请求插件异步分析音频并更新UI
            analyzer_plugin.analyze_and_update_ui('voicebank_recorder', filepath, self.current_word_index)
        else:
            # 如果插件不存在，也要确保显示正确的成功图标和工具提示
            if list_item:
                list_item.setIcon(self.icon_manager.get_icon("success"))
                list_item.setToolTip(word_text)

        # --- 4. 决定下一步操作 (核心逻辑) ---
        
        # 从配置中读取“自动前进”设置
        module_states = self.config.get("module_states", {}).get("voicebank_recorder", {})
        auto_advance = module_states.get("auto_advance", True) # 默认启用

        # 检查是否所有词条都已录制
        all_done = all(self._find_existing_audio(item['word']) for item in self.current_word_list)

        if all_done:
            # 如果所有条目都已完成，则结束会话
            if self.logger:
                self.logger.log("[INFO] All items in the list have been recorded.")
            QMessageBox.information(self, "完成", "所有词条已录制完毕！")
            if self.session_active:
                self.end_session()
        elif auto_advance:
            # 如果启用了自动前进，并且尚未全部完成，则跳转到下一个未录制的词条
            # 这是一个更健壮的查找下一个未录制项的逻辑
            next_unrecorded_index = -1
            # 从当前位置向后查找
            for i in range(self.current_word_index + 1, len(self.current_word_list)):
                if not self._find_existing_audio(self.current_word_list[i]['word']):
                    next_unrecorded_index = i
                    break
            # 如果向后没找到，再从头开始查找
            if next_unrecorded_index == -1:
                for i in range(self.current_word_index):
                     if not self._find_existing_audio(self.current_word_list[i]['word']):
                        next_unrecorded_index = i
                        break
            
            if next_unrecorded_index != -1:
                self.list_widget.setCurrentCell(next_unrecorded_index, 0)
    def _persistent_recorder_task(self):
        try:
            device_index = self.resolve_device_func(self.config)
            with sd.InputStream(device=device_index, samplerate=self.config['audio_settings']['sample_rate'], channels=self.config['audio_settings']['channels'], callback=self._audio_callback): self.session_stop_event.wait()
        except Exception as e: self.recording_device_error_signal.emit(f"无法启动录音: {e}")
    def save_recording_task(self, worker_instance):
        if self.audio_queue.empty(): return
        data_chunks = [];
        while not self.audio_queue.empty():
            try: data_chunks.append(self.audio_queue.get_nowait())
            except queue.Empty: break
        if not data_chunks: return
        rec = np.concatenate(data_chunks, axis=0); gain = self.config['audio_settings'].get('recording_gain', 1.0)
        if gain != 1.0: rec = np.clip(rec * gain, -1.0, 1.0)
        word = self.current_word_list[self.current_word_index]['word']; recording_format = self.config['audio_settings'].get('recording_format', 'wav').lower(); filename = f"{word}.{recording_format}"; filepath = os.path.join(self.audio_folder, filename)
        if self.logger: self.logger.log(f"[RECORDING_SAVE_ATTEMPT] Word: '{word}', Format: '{recording_format}', Path: '{filepath}'")
        try: sf.write(filepath, rec, self.config['audio_settings']['sample_rate']);
        except Exception as e:
            if 'format not understood' in str(e).lower() and recording_format == 'mp3': return "save_failed_mp3_encoder"
            try: wav_path = os.path.splitext(filepath)[0] + ".wav"; sf.write(wav_path, rec, self.config['audio_settings']['sample_rate'])
            except Exception as e_wav: print(f"回退保存WAV也失败: {e_wav}")
    def run_task_in_thread(self,task_func,*args):
        self.thread=QThread();self.worker=self.Worker(task_func,*args);self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run);self.worker.finished.connect(self.thread.quit); self.worker.finished.connect(self.worker.deleteLater);self.thread.finished.connect(self.thread.deleteLater); self.worker.error.connect(lambda msg:QMessageBox.critical(self,"后台错误",msg))
        if task_func==self.save_recording_task: self.worker.finished.connect(self.on_recording_saved)
        self.thread.start()
    def load_word_list_logic(self,filename):
        filepath=os.path.join(self.WORD_LIST_DIR,filename)
        if not os.path.exists(filepath): raise FileNotFoundError(f"找不到单词表文件: {filename}")
        try:
            with open(filepath, 'r', encoding='utf-8') as f: data = json.load(f)
        except json.JSONDecodeError as e: raise ValueError(f"词表文件 '{filename}' 不是有效的JSON格式: {e}")
        if "meta" not in data or data.get("meta", {}).get("format") != "standard_wordlist" or "groups" not in data: raise ValueError(f"词表文件 '{filename}' 格式不正确或不受支持。")
        # [核心修改] 应用“默认备注”设置
        module_states = self.config.get("module_states", {}).get("voicebank_recorder", {})
        default_note = module_states.get("default_note", "")

        word_groups = []
        for group_data in data.get("groups", []):
            group_dict = {}
            for item in group_data.get("items", []):
                text = item.get("text")
                if text:
                    note = item.get("note", "")
                    # 如果备注为空，则使用设置中的默认备注
                    if not note and default_note:
                        note = default_note
                    lang = item.get("lang", "")
                    group_dict[text] = (note, lang)
            if group_dict:
                word_groups.append(group_dict)
        return word_groups
# ==============================================================================
#   SettingsDialog - 提示音录制模块专属设置对话框
# ==============================================================================
class SettingsDialog(QDialog):
    """
    一个专门用于配置“提示音录制”模块的对话框。
    """
    def __init__(self, parent_page):
        super().__init__(parent_page)
        
        self.parent_page = parent_page
        self.setWindowTitle("提示音录制设置")
        self.setWindowIcon(self.parent_page.parent_window.windowIcon())
        self.setStyleSheet(self.parent_page.parent_window.styleSheet())
        self.setMinimumWidth(400)
        
        # --- UI 构建 ---
        layout = QVBoxLayout(self)
        
        # --- 组1: 录制流程 ---
        flow_group = QGroupBox("录制流程")
        form_layout = QFormLayout(flow_group)
        
        self.auto_advance_checkbox = QCheckBox("录制后自动前进到下一个")
        self.auto_advance_checkbox.setToolTip("勾选后，成功录制一个词条后会自动选中下一个未录制的词条。")
        
        form_layout.addRow(self.auto_advance_checkbox)
        layout.addWidget(flow_group)
        
        # --- 组2: 界面与性能 ---
        ui_perf_group = QGroupBox("界面与性能")
        ui_perf_form_layout = QFormLayout(ui_perf_group)
        self.show_waveform_checkbox = QCheckBox("显示波形预览列")
        self.show_waveform_checkbox.setToolTip("取消勾选可隐藏波形图列，有助于在词表非常大时提升性能。")
        ui_perf_form_layout.addRow(self.show_waveform_checkbox)
        
        volume_slider_layout = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(10, 100)
        self.volume_slider.setTickInterval(10)
        self.volume_slider.setTickPosition(QSlider.TicksBelow)
        self.volume_slider_label = QLabel("16 ms")
        self.volume_slider.valueChanged.connect(lambda v: self.volume_slider_label.setText(f"{v} ms"))
        
        volume_slider_layout.addWidget(self.volume_slider)
        volume_slider_layout.addWidget(self.volume_slider_label)
        
        ui_perf_form_layout.addRow("音量计刷新间隔:", volume_slider_layout)
        layout.addWidget(ui_perf_group)

        # --- 组3: 数据选项 ---
        data_group = QGroupBox("数据选项")
        data_form_layout = QFormLayout(data_group)
        
        self.default_note_input = QLineEdit()
        self.default_note_input.setPlaceholderText("例如: 清晰、快速")
        self.default_note_input.setToolTip("在这里输入的文本将作为词表中“备注”为空时的默认值。")
        
        self.cleanup_empty_folder_checkbox = QCheckBox("自动清理未录音的会话文件夹")
        self.cleanup_empty_folder_checkbox.setToolTip("勾选后，如果一个录音批次下没有任何音频文件，\n其对应的文件夹将在会话结束时被自动删除。")        
        
        data_form_layout.addRow("默认备注内容:", self.default_note_input)
        
        # --- 核心修复点 ---
        # 将新创建的 CheckBox 添加到布局中
        data_form_layout.addRow(self.cleanup_empty_folder_checkbox)
        
        layout.addWidget(data_group)
        
        # --- OK 和 Cancel 按钮 ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        
        self.load_settings()

    def load_settings(self):
        """从主配置加载设置并更新UI。"""
        # 使用一个独立的键 'voicebank_recorder' 来存储此模块的设置
        module_states = self.parent_page.config.get("module_states", {}).get("voicebank_recorder", {})
        
        self.auto_advance_checkbox.setChecked(module_states.get("auto_advance", True))
        self.show_waveform_checkbox.setChecked(module_states.get("show_waveform", True))
        self.volume_slider.setValue(module_states.get("volume_meter_interval", 16))
        self.volume_slider_label.setText(f"{self.volume_slider.value()} ms")
        self.default_note_input.setText(module_states.get("default_note", ""))
        self.cleanup_empty_folder_checkbox.setChecked(module_states.get("cleanup_empty_folder", True))
    def save_settings(self):
        """将UI上的设置保存回主配置。"""
        main_window = self.parent_page.parent_window
        settings_to_save = {
            "auto_advance": self.auto_advance_checkbox.isChecked(),
            "show_waveform": self.show_waveform_checkbox.isChecked(),
            "volume_meter_interval": self.volume_slider.value(),
            "default_note": self.default_note_input.text().strip(),
            "cleanup_empty_folder": self.cleanup_empty_folder_checkbox.isChecked(),
        }
        main_window.update_and_save_module_state('voicebank_recorder', settings_to_save)

    def accept(self):
        """重写 accept 方法，在关闭对话框前先保存设置。"""
        self.save_settings()
        super().accept()