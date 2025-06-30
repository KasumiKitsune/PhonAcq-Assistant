# --- START OF FILE modules/settings_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "程序设置"
MODULE_DESCRIPTION = "调整应用的各项参数，包括UI布局、音频设备、TTS默认设置和主题皮肤等。"
# ---

import os
import sys
import json
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
                             QFileDialog, QMessageBox, QComboBox, QFormLayout, 
                             QGroupBox, QLineEdit, QSlider)
from PyQt5.QtGui import QIntValidator
from PyQt5.QtCore import Qt

try:
    import sounddevice as sd
except ImportError:
    class MockSoundDevice:
        def query_devices(self): return []
        @property
        def default(self):
            class MockDefault:
                device = [-1, -1]
            return MockDefault()
    sd = MockSoundDevice()
    print("WARNING: sounddevice library not found. Audio device settings will be unavailable.")

def get_base_path_for_module():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# ===== 标准化模块入口函数 =====
def create_page(parent_window, ToggleSwitchClass, THEMES_DIR, WORD_LIST_DIR):
    """模块的入口函数，用于创建页面。"""
    return SettingsPage(parent_window, ToggleSwitchClass, THEMES_DIR, WORD_LIST_DIR)


class SettingsPage(QWidget):
    """The settings page for the application."""
    def __init__(self, parent_window, ToggleSwitchClass, THEMES_DIR, WORD_LIST_DIR):
        super().__init__()
        self.parent_window = parent_window
        self.ToggleSwitch = ToggleSwitchClass
        self.THEMES_DIR = THEMES_DIR
        self.WORD_LIST_DIR = WORD_LIST_DIR
        
        main_layout = QVBoxLayout(self)
        columns_layout = QHBoxLayout()

        self.left_column_widget = QWidget()
        left_column_layout = QVBoxLayout(self.left_column_widget)
        
        self.right_column_widget = QWidget()
        right_column_layout = QVBoxLayout(self.right_column_widget)

        ui_appearance_group = QGroupBox("界面与外观")
        ui_appearance_form_layout = QFormLayout(ui_appearance_group)
        self.collector_width_input = QLineEdit(); self.collector_width_input.setValidator(QIntValidator(200, 600, self)); self.collector_width_label = QLabel("范围: 200-600 px")
        collector_width_layout = QHBoxLayout(); collector_width_layout.addWidget(self.collector_width_input); collector_width_layout.addWidget(self.collector_width_label)
        ui_appearance_form_layout.addRow("采集类页面侧边栏宽度:", collector_width_layout)
        self.editor_width_input = QLineEdit(); self.editor_width_input.setValidator(QIntValidator(200, 600, self)); self.editor_width_label = QLabel("范围: 200-600 px")
        editor_width_layout = QHBoxLayout(); editor_width_layout.addWidget(self.editor_width_input); editor_width_layout.addWidget(self.editor_width_label)
        ui_appearance_form_layout.addRow("管理/编辑类页面侧边栏宽度:", editor_width_layout)
        self.theme_combo = QComboBox(); ui_appearance_form_layout.addRow("主题皮肤:", self.theme_combo)
        self.hide_tooltips_switch = self.ToggleSwitch()
        hide_tooltips_layout = QHBoxLayout(); hide_tooltips_layout.addWidget(self.hide_tooltips_switch); hide_tooltips_layout.addStretch()
        ui_appearance_form_layout.addRow("隐藏所有文字提示(Tooltip):", hide_tooltips_layout)
        
        file_group = QGroupBox("文件与路径")
        file_layout = QFormLayout(file_group)
        self.results_dir_input = QLineEdit(); self.results_dir_btn = QPushButton("...")
        results_dir_layout = QHBoxLayout(); results_dir_layout.addWidget(self.results_dir_input); results_dir_layout.addWidget(self.results_dir_btn)
        self.word_list_combo = QComboBox(); self.participant_name_input = QLineEdit()
        file_layout.addRow("结果文件夹:", results_dir_layout); file_layout.addRow("默认单词表 (口音采集):", self.word_list_combo); file_layout.addRow("默认被试者名称:", self.participant_name_input)
        
        # --- [新增] 日志开关 ---
        self.enable_logging_switch = self.ToggleSwitch()
        enable_logging_layout = QHBoxLayout(); enable_logging_layout.addWidget(self.enable_logging_switch); enable_logging_layout.addStretch()
        file_layout.addRow("启用详细日志记录:", enable_logging_layout)
        # --- 结束新增 ---
        
        gtts_group = QGroupBox("gTTS (在线) 设置"); gtts_layout = QFormLayout(gtts_group)
        self.gtts_lang_combo = QComboBox(); self.gtts_lang_combo.addItems(['en-us','en-uk','en-au','en-in','zh-cn','ja','fr-fr','de-de','es-es','ru','ko'])
        self.gtts_auto_detect_switch = self.ToggleSwitch(); auto_detect_layout = QHBoxLayout(); auto_detect_layout.addWidget(self.gtts_auto_detect_switch); auto_detect_layout.addStretch()
        gtts_layout.addRow("默认语言 (无指定时):", self.gtts_lang_combo); gtts_layout.addRow("自动检测语言 (中/日等):", auto_detect_layout)

        audio_group = QGroupBox("音频与录音"); audio_layout = QFormLayout(audio_group)
        self.input_device_combo = QComboBox(); audio_layout.addRow("录音设备:", self.input_device_combo)
        self.recording_format_switch = self.ToggleSwitch()
        format_layout = QHBoxLayout(); format_layout.addWidget(QLabel("WAV (高质量)")); format_layout.addWidget(self.recording_format_switch); format_layout.addWidget(QLabel("MP3 (高压缩)"))
        audio_layout.addRow("录音保存格式:", format_layout)
        self.sample_rate_combo = QComboBox(); self.sample_rate_combo.addItems(["44100 Hz (CD质量, 推荐)","48000 Hz (录音室质量)","22050 Hz (中等质量)","16000 Hz (语音识别常用)"])
        self.channels_combo = QComboBox(); self.channels_combo.addItems(["1 (单声道, 推荐)","2 (立体声)"])
        self.gain_slider = QSlider(Qt.Horizontal); self.gain_label = QLabel("1.0x"); self.gain_slider.setRange(5, 50); self.gain_slider.setValue(10)
        gain_layout = QHBoxLayout(); gain_layout.addWidget(self.gain_slider); gain_layout.addWidget(self.gain_label)
        audio_layout.addRow("采样率:", self.sample_rate_combo); audio_layout.addRow("通道:", self.channels_combo); audio_layout.addRow("录音音量增益:", gain_layout)
        
        left_column_layout.addWidget(ui_appearance_group); left_column_layout.addWidget(file_group); left_column_layout.addStretch()
        right_column_layout.addWidget(gtts_group); right_column_layout.addWidget(audio_group); right_column_layout.addStretch()
        self.left_column_widget.setMaximumWidth(600); self.right_column_widget.setMaximumWidth(600)
        columns_layout.addWidget(self.left_column_widget); columns_layout.addWidget(self.right_column_widget)
        button_layout = QHBoxLayout(); self.save_btn = QPushButton("保存所有设置"); self.save_btn.setObjectName("AccentButton"); button_layout.addStretch(); button_layout.addWidget(self.save_btn)
        main_layout.addLayout(columns_layout); main_layout.addLayout(button_layout)
        
        self.gain_slider.valueChanged.connect(lambda v: self.gain_label.setText(f"{v/10.0:.1f}x")); self.save_btn.clicked.connect(self.save_settings)
        self.results_dir_btn.clicked.connect(self.select_results_dir); self.theme_combo.currentTextChanged.connect(self.preview_theme)

    def populate_all(self):
        self.populate_themes(); self.populate_word_lists(); self.populate_input_devices()

    def populate_input_devices(self):
        self.input_device_combo.clear()
        try:
            devices = sd.query_devices(); default_input_idx = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) and len(sd.default.device) > 0 else -1
            self.input_device_combo.addItem("系统默认", None) 
            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    device_name = f"{device['name']}" + (" (推荐)" if i == default_input_idx else "")
                    self.input_device_combo.addItem(device_name, i)
        except Exception as e:
            print(f"获取录音设备失败: {e}", file=sys.stderr)
            self.input_device_combo.addItem("无法获取设备列表", -1)

    def select_results_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择结果文件夹", self.results_dir_input.text())
        if directory: self.results_dir_input.setText(directory)

    def populate_word_lists(self):
        self.word_list_combo.clear()
        if os.path.exists(self.WORD_LIST_DIR): self.word_list_combo.addItems([f for f in os.listdir(self.WORD_LIST_DIR) if f.endswith('.py')])

    def populate_themes(self):
        self.theme_combo.clear()
        themes_dir_path = self.THEMES_DIR
        if os.path.exists(themes_dir_path): self.theme_combo.addItems([f for f in os.listdir(themes_dir_path) if f.endswith('.qss') and not f.startswith('_')])

    def load_settings(self):
        self.populate_all()
        config = self.parent_window.config
        
        ui_settings = config.get("ui_settings", {})
        self.collector_width_input.setText(str(ui_settings.get("collector_sidebar_width", 320))); self.editor_width_input.setText(str(ui_settings.get("editor_sidebar_width", 280)))
        self.hide_tooltips_switch.setChecked(ui_settings.get("hide_all_tooltips", False))
        self.theme_combo.setCurrentText(config.get("theme", "Modern_light_tab.qss"))
        file_settings = config.get("file_settings", {}); gtts_settings = config.get("gtts_settings", {}); audio_settings = config.get("audio_settings", {})
        
        # --- [修改] 加载日志开关设置 ---
        app_settings = config.get("app_settings", {})
        self.enable_logging_switch.setChecked(app_settings.get("enable_logging", True))
        
        self.word_list_combo.setCurrentText(file_settings.get('word_list_file', '')); self.participant_name_input.setText(file_settings.get('participant_base_name', ''))
        base_path = get_base_path_for_module()
        self.results_dir_input.setText(file_settings.get("results_dir", os.path.join(base_path, "Results")))
        self.gtts_lang_combo.setCurrentText(gtts_settings.get('default_lang', 'en-us')); self.gtts_auto_detect_switch.setChecked(gtts_settings.get('auto_detect', True))
        self.recording_format_switch.setChecked(audio_settings.get("recording_format", "wav") == "mp3")
        saved_device_idx = audio_settings.get("input_device_index", None)
        if saved_device_idx is None: index_in_combo = self.input_device_combo.findData(None)
        else: index_in_combo = self.input_device_combo.findData(saved_device_idx)
        if index_in_combo != -1: self.input_device_combo.setCurrentIndex(index_in_combo)
        else:
            default_idx = self.input_device_combo.findData(None)
            if default_idx != -1: self.input_device_combo.setCurrentIndex(default_idx)
        sr_text = next((s for s in [self.sample_rate_combo.itemText(i) for i in range(self.sample_rate_combo.count())] if str(audio_settings.get('sample_rate', 44100)) in s), "44100 Hz (CD质量, 推荐)")
        self.sample_rate_combo.setCurrentText(sr_text)
        ch_text = next((s for s in [self.channels_combo.itemText(i) for i in range(self.channels_combo.count())] if str(audio_settings.get('channels', 1)) in s), "1 (单声道, 推荐)")
        self.channels_combo.setCurrentText(ch_text)
        self.gain_slider.setValue(int(audio_settings.get('recording_gain', 1.0) * 10))

    def preview_theme(self, theme_file):
        if not theme_file: return
        theme_path = os.path.join(self.THEMES_DIR, theme_file)
        if os.path.exists(theme_path):
            with open(theme_path, "r", encoding="utf-8") as f: self.parent_window.setStyleSheet(f.read())
            
    def save_settings(self):
        try:
            collector_width = int(self.collector_width_input.text()); editor_width = int(self.editor_width_input.text())
            if not (200 <= collector_width <= 600 and 200 <= editor_width <= 600): raise ValueError("侧边栏宽度必须在 200 到 600 像素之间。")
        except ValueError as e:
            QMessageBox.warning(self, "输入无效", str(e))
            config = self.parent_window.config
            ui_settings = config.get("ui_settings", {}); self.collector_width_input.setText(str(ui_settings.get("collector_sidebar_width", 320))); self.editor_width_input.setText(str(ui_settings.get("editor_sidebar_width", 280)))
            return

        config = self.parent_window.config
        config.setdefault("ui_settings", {})["collector_sidebar_width"] = collector_width
        config.setdefault("ui_settings", {})["editor_sidebar_width"] = editor_width
        config.setdefault("ui_settings", {})["hide_all_tooltips"] = self.hide_tooltips_switch.isChecked()
        config['theme'] = self.theme_combo.currentText()
        config['file_settings'] = {"word_list_file": self.word_list_combo.currentText(), "participant_base_name": self.participant_name_input.text(), "results_dir": self.results_dir_input.text()}
        config['gtts_settings'] = {"default_lang": self.gtts_lang_combo.currentText(), "auto_detect": self.gtts_auto_detect_switch.isChecked()}
        
        # --- [修改] 保存日志开关设置 ---
        config.setdefault("app_settings", {})["enable_logging"] = self.enable_logging_switch.isChecked()
        
        audio_settings = config.setdefault("audio_settings", {})
        audio_settings["sample_rate"] = int(self.sample_rate_combo.currentText().split(' ')[0])
        audio_settings["channels"] = int(self.channels_combo.currentText().split(' ')[0])
        audio_settings["recording_gain"] = self.gain_slider.value() / 10.0
        audio_settings["input_device_index"] = self.input_device_combo.currentData()
        audio_settings["recording_format"] = "mp3" if self.recording_format_switch.isChecked() else "wav"
        
        try:
            settings_file_path = os.path.join(get_base_path_for_module(), "config", "settings.json")
            with open(settings_file_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
            
            self.parent_window.config = config
            self.parent_window.apply_theme()
            self.parent_window.apply_tooltips()
            
            for page_attr_name in ['accent_collection_page', 'voicebank_recorder_page', 'wordlist_editor_page', 'dialect_visual_editor_page', 'audio_manager_page', 'dialect_visual_collector_page']: 
                page = getattr(self.parent_window, page_attr_name, None)
                if page and hasattr(page, 'apply_layout_settings'): page.apply_layout_settings()
            
            QMessageBox.information(self, "成功", "所有设置已成功保存并应用！")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")