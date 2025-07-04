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
                             QGroupBox, QLineEdit, QSlider, QSpacerItem, QSizePolicy)
from PyQt5.QtGui import QIntValidator
from PyQt5.QtCore import Qt

try:
    import sounddevice as sd
except ImportError:
    class MockSoundDevice:
        def query_devices(self): return []
        @property
        def default(self):
            class MockDefault: device = [-1, -1]
            return MockDefault()
    sd = MockSoundDevice()
    print("WARNING: sounddevice library not found. Audio device settings will be unavailable.")

def get_base_path_for_module():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def create_page(parent_window, ToggleSwitchClass, THEMES_DIR, WORD_LIST_DIR):
    return SettingsPage(parent_window, ToggleSwitchClass, THEMES_DIR, WORD_LIST_DIR)

class SettingsPage(QWidget):
    def __init__(self, parent_window, ToggleSwitchClass, THEMES_DIR, WORD_LIST_DIR):
        super().__init__()
        self.parent_window = parent_window
        self.ToggleSwitch = ToggleSwitchClass
        self.THEMES_DIR = THEMES_DIR
        self.WORD_LIST_DIR = WORD_LIST_DIR
        self._init_ui()
        self._connect_signals()
    
    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        columns_layout = QHBoxLayout()
        self.left_column_widget = QWidget(); left_column_layout = QVBoxLayout(self.left_column_widget)
        self.right_column_widget = QWidget(); right_column_layout = QVBoxLayout(self.right_column_widget)
        
        # 界面与外观
        ui_appearance_group = QGroupBox("界面与外观")
        ui_appearance_form_layout = QFormLayout(ui_appearance_group)
        self.collector_width_input = QLineEdit()
        self.collector_width_input.setValidator(QIntValidator(200, 600, self))
        self.collector_width_input.setToolTip("设置采集类页面（如标准朗读采集、看图说话采集）右侧边栏的宽度。范围：200-600像素。")
        self.collector_width_label = QLabel("范围: 200-600 px")
        collector_width_layout = QHBoxLayout(); collector_width_layout.addWidget(self.collector_width_input); collector_width_layout.addWidget(self.collector_width_label)
        ui_appearance_form_layout.addRow("采集类页面侧边栏宽度:", collector_width_layout)
        
        self.editor_width_input = QLineEdit()
        self.editor_width_input.setValidator(QIntValidator(200, 600, self))
        self.editor_width_input.setToolTip("设置管理/编辑类页面（如词表编辑器、数据管理器）左侧边栏的宽度。范围：200-600像素。")
        self.editor_width_label = QLabel("范围: 200-600 px")
        editor_width_layout = QHBoxLayout(); editor_width_layout.addWidget(self.editor_width_input); editor_width_layout.addWidget(self.editor_width_label)
        ui_appearance_form_layout.addRow("管理/编辑类页面侧边栏宽度:", editor_width_layout)
        
        self.theme_combo = QComboBox()
        self.theme_combo.setToolTip("选择应用程序的视觉主题。更改后将立即生效。")
        ui_appearance_form_layout.addRow("主题皮肤:", self.theme_combo)
        
        self.hide_tooltips_switch = self.ToggleSwitch()
        self.hide_tooltips_switch.setToolTip("开启后，将隐藏标签页的工具提示（鼠标悬停时显示的文字）。")
        hide_tooltips_layout = QHBoxLayout(); hide_tooltips_layout.addWidget(self.hide_tooltips_switch); hide_tooltips_layout.addStretch()
        ui_appearance_form_layout.addRow("隐藏Tab文字提示(Tooltip):", hide_tooltips_layout)
        
        # 文件与路径
        file_group = QGroupBox("文件与路径")
        file_layout = QFormLayout(file_group)
        self.results_dir_input = QLineEdit()
        self.results_dir_input.setReadOnly(True)
        self.results_dir_input.setToolTip("所有采集任务（口音采集、看图说话）生成的音频和日志文件将保存在此目录。")
        self.results_dir_btn = QPushButton("...")
        self.results_dir_btn.setToolTip("点击选择结果文件存储的根目录。")
        results_dir_layout = QHBoxLayout(); results_dir_layout.addWidget(self.results_dir_input); results_dir_layout.addWidget(self.results_dir_btn)
        file_layout.addRow("结果文件夹:", results_dir_layout)
        
        self.word_list_combo = QComboBox()
        self.word_list_combo.setToolTip("在'标准朗读采集'模块中，会话开始时将默认加载此单词表。")
        file_layout.addRow("默认单词表 (口音采集):", self.word_list_combo)
        
        self.participant_name_input = QLineEdit()
        self.participant_name_input.setToolTip("设置每次采集会话（口音采集）的默认被试者名称前缀。")
        file_layout.addRow("默认被试者名称:", self.participant_name_input)
        
        self.enable_logging_switch = self.ToggleSwitch()
        self.enable_logging_switch.setToolTip("开启后，所有采集会话（口音、图文、语音包）将生成详细的运行日志文件。")
        enable_logging_layout = QHBoxLayout(); enable_logging_layout.addWidget(self.enable_logging_switch); enable_logging_layout.addStretch()
        file_layout.addRow("启用详细日志记录:", enable_logging_layout)
        
        # gTTS (在线) 设置
        gtts_group = QGroupBox("gTTS (在线) 设置")
        gtts_layout = QFormLayout(gtts_group)
        self.gtts_lang_combo = QComboBox()
        self.gtts_lang_combo.addItems(['en-us','en-uk','en-au','en-in','zh-cn','ja','fr-fr','de-de','es-es','ru','ko'])
        self.gtts_lang_combo.setToolTip("当文本未指定语言时，或自动检测失败时，gTTS将使用此处的默认语言进行转换。")
        gtts_layout.addRow("默认语言 (无指定时):", self.gtts_lang_combo)
        
        self.gtts_auto_detect_switch = self.ToggleSwitch()
        self.gtts_auto_detect_switch.setToolTip("开启后，TTS工具将尝试自动检测文本的语言（如中文、日文），如果检测失败，则使用上面的默认语言。")
        auto_detect_layout = QHBoxLayout(); auto_detect_layout.addWidget(self.gtts_auto_detect_switch); auto_detect_layout.addStretch()
        gtts_layout.addRow("自动检测语言 (中/日等):", auto_detect_layout)

        # 音频与录音
        audio_group = QGroupBox("音频与录音")
        audio_layout = QFormLayout(audio_group)

        # [新增] 简易/专家模式切换
        self.simple_mode_switch = self.ToggleSwitch()
        self.simple_mode_switch.setToolTip("开启后，将提供简化的设备选项，方便非专业用户使用。")
        simple_mode_layout = QHBoxLayout()
        simple_mode_layout.addWidget(QLabel("专家模式"))
        simple_mode_layout.addWidget(self.simple_mode_switch)
        simple_mode_layout.addWidget(QLabel("简易模式"))
        simple_mode_layout.addStretch()
        audio_layout.addRow("录音设备模式:", simple_mode_layout)
        
        self.input_device_combo = QComboBox()
        self.input_device_combo.setToolTip("选择用于录制音频的麦克风设备。")
        audio_layout.addRow("录音设备:", self.input_device_combo)
        
        self.recording_format_switch = self.ToggleSwitch()
        self.recording_format_switch.setToolTip("选择录音文件的保存格式。\nWAV提供最佳质量但文件大，MP3压缩率高但可能需要额外编码器。\n警告：软件的音频文件管理器在播放MP3文件时体验不佳。")
        format_layout = QHBoxLayout(); format_layout.addWidget(QLabel("WAV (高质量，推荐)")); format_layout.addWidget(self.recording_format_switch); format_layout.addWidget(QLabel("MP3 (高压缩)"))
        audio_layout.addRow("录音保存格式:", format_layout)
        
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(["44100 Hz (CD质量, 推荐)","48000 Hz (录音室质量)","22050 Hz (中等质量)","16000 Hz (语音识别常用)"])
        self.sample_rate_combo.setToolTip("设置录音的采样率。通常44100Hz或48000Hz足以满足大多数研究需求。")
        audio_layout.addRow("采样率:", self.sample_rate_combo)
        
        self.channels_combo = QComboBox()
        self.channels_combo.addItems(["1 (单声道, 推荐)","2 (立体声)"])
        self.channels_combo.setToolTip("设置录音通道数。通常单声道(1)对于语言学研究已足够。")
        audio_layout.addRow("通道:", self.channels_combo)
        
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setRange(5, 50)
        self.gain_slider.setValue(10)
        self.gain_slider.setToolTip("调整录音的数字音量增益。请根据麦克风输入水平进行调整，避免过载失真。")
        self.gain_label = QLabel("1.0x")
        gain_layout = QHBoxLayout(); gain_layout.addWidget(self.gain_slider); gain_layout.addWidget(self.gain_label)
        audio_layout.addRow("录音音量增益:", gain_layout)
         # [新增] 音频播放缓存设置
        self.player_cache_slider = QSlider(Qt.Horizontal)
        self.player_cache_slider.setRange(3, 20) # 允许缓存 3 到 20 个音频文件
        self.player_cache_slider.setValue(5) # 默认值
        self.player_cache_slider.setToolTip("设置在“音频数据管理器”中预加载到内存的音频文件数量。\n值越高，顺序播放越流畅，但会占用更多内存。推荐5-10。")
        self.player_cache_label = QLabel("5 个文件")
        cache_layout = QHBoxLayout()
        cache_layout.addWidget(self.player_cache_slider)
        cache_layout.addWidget(self.player_cache_label)
        audio_layout.addRow("播放缓存容量:", cache_layout)
        
        left_column_layout.addWidget(ui_appearance_group); left_column_layout.addWidget(file_group); left_column_layout.addStretch()
        right_column_layout.addWidget(gtts_group); right_column_layout.addWidget(audio_group); right_column_layout.addStretch()
        self.left_column_widget.setMaximumWidth(600); self.right_column_widget.setMaximumWidth(600)
        columns_layout.addWidget(self.left_column_widget); columns_layout.addWidget(self.right_column_widget)
        
        # 配置管理
        config_management_group = QGroupBox("配置管理")
        config_management_layout = QHBoxLayout(config_management_group)
        
        self.restore_defaults_btn = QPushButton("恢复默认设置")
        self.restore_defaults_btn.setObjectName("ActionButton_Delete")
        self.restore_defaults_btn.setToolTip("将所有设置恢复到程序初始状态，此操作将删除您当前的配置文件，且不可撤销。")
        
        self.import_settings_btn = QPushButton("导入配置...")
        self.import_settings_btn.setToolTip("从外部JSON文件导入之前导出的设置。")
        
        self.export_settings_btn = QPushButton("导出配置...")
        self.export_settings_btn.setToolTip("将当前所有设置导出为一个JSON文件，方便备份或在其他设备上使用。")
        
        self.save_btn = QPushButton("保存所有设置")
        self.save_btn.setToolTip("保存并应用所有修改后的设置。")
        self.save_btn.setEnabled(False)

        config_management_layout.addWidget(self.restore_defaults_btn)
        config_management_layout.addStretch()
        config_management_layout.addWidget(self.import_settings_btn)
        config_management_layout.addWidget(self.export_settings_btn)
        config_management_layout.addWidget(self.save_btn)
        
        main_layout.addLayout(columns_layout); main_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding)); main_layout.addWidget(config_management_group)
        
    def _connect_signals(self):
        # UI元素信号连接到通用槽 _on_setting_changed
        self.collector_width_input.textChanged.connect(self._on_setting_changed)
        self.editor_width_input.textChanged.connect(self._on_setting_changed)
        self.theme_combo.currentIndexChanged.connect(self._on_setting_changed)
        self.hide_tooltips_switch.stateChanged.connect(self._on_setting_changed)
        
        self.results_dir_btn.clicked.connect(self.select_results_dir) 

        self.word_list_combo.currentIndexChanged.connect(self._on_setting_changed)
        self.participant_name_input.textChanged.connect(self._on_setting_changed)
        self.enable_logging_switch.stateChanged.connect(self._on_setting_changed)
        
        self.gtts_lang_combo.currentIndexChanged.connect(self._on_setting_changed)
        self.gtts_auto_detect_switch.stateChanged.connect(self._on_setting_changed)
        
        self.simple_mode_switch.stateChanged.connect(self.on_device_mode_toggled)
        self.input_device_combo.currentIndexChanged.connect(self._on_setting_changed)
        self.recording_format_switch.stateChanged.connect(self._on_setting_changed)
        self.sample_rate_combo.currentIndexChanged.connect(self._on_setting_changed)
        self.channels_combo.currentIndexChanged.connect(self._on_setting_changed)
        self.gain_slider.valueChanged.connect(self._on_setting_changed)
        self.gain_slider.valueChanged.connect(lambda v: self.gain_label.setText(f"{v/10.0:.1f}x"))
        self.player_cache_slider.valueChanged.connect(self._on_setting_changed)
        self.player_cache_slider.valueChanged.connect(lambda v: self.player_cache_label.setText(f"{v} 个文件"))
             
        self.save_btn.clicked.connect(self.save_settings)
        self.restore_defaults_btn.clicked.connect(self.restore_defaults)
        self.import_settings_btn.clicked.connect(self.import_settings)
        self.export_settings_btn.clicked.connect(self.export_settings)

    def _on_setting_changed(self):
        """当任何设置被用户修改时，启用保存按钮。"""
        self.save_btn.setEnabled(True)
        
    def on_device_mode_toggled(self, is_simple_mode):
        self.populate_input_devices()
        self._on_setting_changed()

    def populate_all(self):
        self.populate_themes()
        self.populate_word_lists()
        self.populate_input_devices()

    def populate_input_devices(self):
        self.input_device_combo.clear()
        is_simple_mode = self.simple_mode_switch.isChecked()

        if is_simple_mode:
            self.input_device_combo.setToolTip("选择一个简化的录音设备类型。")
            self.input_device_combo.addItem("智能选择 (推荐)", "smart")
            self.input_device_combo.addItem("系统默认", "default")
            self.input_device_combo.addItem("内置麦克风", "internal")
            self.input_device_combo.addItem("外置设备 (USB/蓝牙等)", "external")
            self.input_device_combo.addItem("电脑内部声音", "loopback")
        else: # 专家模式
            self.input_device_combo.setToolTip("选择用于录制音频的物理麦克风设备。")
            try:
                devices = sd.query_devices()
                default_input_idx = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) and len(sd.default.device) > 0 else -1
                
                self.input_device_combo.addItem("系统默认", None) 
                
                for i, device in enumerate(devices):
                    if device['max_input_channels'] > 0:
                        self.input_device_combo.addItem(f"{device['name']}" + (" (推荐)" if i == default_input_idx else ""), i)
            except Exception as e:
                print(f"获取录音设备失败: {e}", file=sys.stderr)
                self.input_device_combo.addItem("无法获取设备列表", -1)

    def select_results_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择结果文件夹", self.results_dir_input.text())
        if directory:
            self.results_dir_input.setText(directory)
            self._on_setting_changed()

    def populate_word_lists(self):
        self.word_list_combo.clear()
        if os.path.exists(self.WORD_LIST_DIR):
            try:
                self.word_list_combo.addItems([f for f in os.listdir(self.WORD_LIST_DIR) if f.endswith('.json')])
            except Exception as e:
                print(f"无法读取单词表目录: {e}")

    def populate_themes(self):
        self.theme_combo.clear()
        if not os.path.exists(self.THEMES_DIR): return
        theme_data = []
        try:
            for item in os.listdir(self.THEMES_DIR):
                item_path = os.path.join(self.THEMES_DIR, item)
                if os.path.isdir(item_path):
                    qss_file_in_dir = f"{item}.qss"
                    if os.path.exists(os.path.join(item_path, qss_file_in_dir)):
                        display_name = item.replace("_", " ").title(); file_path = os.path.join(item, qss_file_in_dir).replace("\\", "/")
                        theme_data.append((display_name, file_path))
                elif item.endswith('.qss') and not item.startswith('_'):
                    display_name = os.path.splitext(item)[0].replace("_", " ").replace("-", " ").title(); file_path = item
                    theme_data.append((display_name, file_path))
        except Exception as e: print(f"扫描主题文件夹时出错: {e}")
        theme_data.sort(key=lambda x: x[0])
        for display_name, file_path in theme_data: self.theme_combo.addItem(display_name, file_path)
    
    def load_settings(self):
        self.populate_all()
        config = self.parent_window.config
        
        ui_settings = config.get("ui_settings", {})
        self.collector_width_input.setText(str(ui_settings.get("collector_sidebar_width", 320)))
        self.editor_width_input.setText(str(ui_settings.get("editor_sidebar_width", 280)))
        self.hide_tooltips_switch.setChecked(ui_settings.get("hide_all_tooltips", False))
        
        saved_theme_path = config.get("theme", "Modern_light_tab.qss")
        if saved_theme_path:
            index = self.theme_combo.findData(saved_theme_path)
            if index >= 0: self.theme_combo.setCurrentIndex(index)
            else:
                try:
                    legacy_display_name = os.path.splitext(os.path.basename(saved_theme_path))[0].replace("_", " ").replace("-", " ").title()
                    legacy_index = self.theme_combo.findText(legacy_display_name, Qt.MatchFixedString)
                    if legacy_index >= 0: self.theme_combo.setCurrentIndex(legacy_index)
                except Exception:
                    if self.theme_combo.count() > 0: self.theme_combo.setCurrentIndex(0)
        elif self.theme_combo.count() > 0: self.theme_combo.setCurrentIndex(0)
        
        file_settings = config.get("file_settings", {}); gtts_settings = config.get("gtts_settings", {}); app_settings = config.get("app_settings", {})
        
        default_wordlist = file_settings.get('word_list_file', '')
        if default_wordlist.endswith('.py'):
            json_equivalent = os.path.splitext(default_wordlist)[0] + '.json'
            if self.word_list_combo.findText(json_equivalent) != -1: self.word_list_combo.setCurrentText(json_equivalent)
            else: self.word_list_combo.setCurrentText(default_wordlist)
        else: self.word_list_combo.setCurrentText(default_wordlist)

        self.participant_name_input.setText(file_settings.get('participant_base_name', ''))        
        self.enable_logging_switch.setChecked(app_settings.get("enable_logging", True))
        base_path = get_base_path_for_module(); self.results_dir_input.setText(file_settings.get("results_dir", os.path.join(base_path, "Results")))
        self.gtts_lang_combo.setCurrentText(gtts_settings.get('default_lang', 'en-us')); self.gtts_auto_detect_switch.setChecked(gtts_settings.get('auto_detect', True))
        
        audio_settings = config.get("audio_settings", {})
        
        device_mode = audio_settings.get("input_device_mode", "manual")
        is_simple = device_mode != "manual"
        
        self.simple_mode_switch.blockSignals(True)
        self.simple_mode_switch.setChecked(is_simple)
        self.simple_mode_switch.blockSignals(False)

        self.populate_input_devices()

        if is_simple:
            index_in_combo = self.input_device_combo.findData(device_mode)
        else:
            saved_device_idx = audio_settings.get("input_device_index", None)
            index_in_combo = self.input_device_combo.findData(saved_device_idx)

        if index_in_combo != -1: self.input_device_combo.setCurrentIndex(index_in_combo)
        elif self.input_device_combo.count() > 0: self.input_device_combo.setCurrentIndex(0)

        self.recording_format_switch.setChecked(audio_settings.get("recording_format", "wav") == "mp3")
        sr_text = next((s for s in [self.sample_rate_combo.itemText(i) for i in range(self.sample_rate_combo.count())] if str(audio_settings.get('sample_rate', 44100)) in s), "44100 Hz (CD质量, 推荐)")
        self.sample_rate_combo.setCurrentText(sr_text)
        ch_text = next((s for s in [self.channels_combo.itemText(i) for i in range(self.channels_combo.count())] if str(audio_settings.get('channels', 1)) in s), "1 (单声道, 推荐)")
        self.channels_combo.setCurrentText(ch_text)
        self.gain_slider.setValue(int(audio_settings.get('recording_gain', 1.0) * 10))
        self.player_cache_slider.setValue(audio_settings.get("player_cache_size", 5))
      
        self.save_btn.setEnabled(False)
        
    def save_settings(self):
        try:
            collector_width = int(self.collector_width_input.text()); editor_width = int(self.editor_width_input.text())
            if not (200 <= collector_width <= 600 and 200 <= editor_width <= 600): raise ValueError("侧边栏宽度必须在 200 到 600 像素之间。")
        except ValueError as e: QMessageBox.warning(self, "输入无效", str(e)); return
        
        config = self.parent_window.config
        config.setdefault("ui_settings", {})["collector_sidebar_width"] = collector_width
        config.setdefault("ui_settings", {})["editor_sidebar_width"] = editor_width
        config.setdefault("ui_settings", {})["hide_all_tooltips"] = self.hide_tooltips_switch.isChecked()
        config['theme'] = self.theme_combo.currentData()
        config['file_settings'] = {"word_list_file": self.word_list_combo.currentText(), "participant_base_name": self.participant_name_input.text(), "results_dir": self.results_dir_input.text()}
        config['gtts_settings'] = {"default_lang": self.gtts_lang_combo.currentText(), "auto_detect": self.gtts_auto_detect_switch.isChecked()}
        config.setdefault("app_settings", {})["enable_logging"] = self.enable_logging_switch.isChecked()
        
        audio_settings = config.setdefault("audio_settings", {})
        if self.simple_mode_switch.isChecked():
            audio_settings["input_device_mode"] = self.input_device_combo.currentData()
            if "input_device_index" in audio_settings:
                del audio_settings["input_device_index"]
        else:
            audio_settings["input_device_mode"] = "manual"
            audio_settings["input_device_index"] = self.input_device_combo.currentData()

        audio_settings["sample_rate"] = int(self.sample_rate_combo.currentText().split(' ')[0])
        audio_settings["channels"] = int(self.channels_combo.currentText().split(' ')[0])
        audio_settings["recording_gain"] = self.gain_slider.value() / 10.0
        audio_settings["recording_format"] = "mp3" if self.recording_format_switch.isChecked() else "wav"
        audio_settings["player_cache_size"] = self.player_cache_slider.value()
        
        if self._write_config_and_apply(config):
            QMessageBox.information(self, "成功", "所有设置已成功保存并应用！")
            self.save_btn.setEnabled(False)

    def _write_config_and_apply(self, config_dict):
        try:
            settings_file_path = os.path.join(get_base_path_for_module(), "config", "settings.json")
            with open(settings_file_path, 'w', encoding='utf-8') as f: json.dump(config_dict, f, indent=4)
            self.parent_window.config = config_dict
            self.parent_window.apply_theme()
            self.parent_window.apply_tooltips()
            
            # 找到所有需要更新布局的页面并调用它们的方法
            pages_to_update = ['accent_collection_page', 'voicebank_recorder_page', 'wordlist_editor_module', 'dialect_visual_editor_module', 'audio_manager_page', 'dialect_visual_collector_module', 'log_viewer_page']
            for page_attr_name in pages_to_update: 
                page = getattr(self.parent_window, page_attr_name, None)
                if page and hasattr(page, 'apply_layout_settings'): page.apply_layout_settings()
            return True
        except Exception as e:
            QMessageBox.critical(self, "错误", f"应用配置失败: {e}")
            return False

    def restore_defaults(self):
        reply = QMessageBox.warning(self, "恢复默认设置", "您确定要将所有设置恢复为出厂默认值吗？\n\n此操作将删除您当前的配置文件，且不可撤销。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                settings_file_path = os.path.join(get_base_path_for_module(), "config", "settings.json")
                if os.path.exists(settings_file_path): os.remove(settings_file_path)
                
                new_config = self.parent_window.setup_and_load_config_external()
                self.parent_window.config = new_config
                self.load_settings()
                self.parent_window.apply_theme()
                self.parent_window.apply_tooltips()
                QMessageBox.information(self, "成功", "已成功恢复默认设置。")
                self.save_btn.setEnabled(False)
            except Exception as e:
                QMessageBox.critical(self, "恢复失败", f"恢复默认设置时出错: {e}")

    def import_settings(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "导入配置文件", "", "JSON 文件 (*.json)")
        if not filepath: return
        try:
            with open(filepath, 'r', encoding='utf-8') as f: new_config = json.load(f)
            if not isinstance(new_config, dict): raise ValueError("配置文件格式无效，必须是一个JSON对象。")
            if self._write_config_and_apply(new_config):
                self.load_settings()
                QMessageBox.information(self, "成功", "配置文件已成功导入并应用。")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"无法导入配置文件:\n{e}")

    def export_settings(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "导出配置文件", "PhonAcq_settings.json", "JSON 文件 (*.json)")
        if not filepath: return
        try:
            with open(filepath, 'w', encoding='utf-8') as f: json.dump(self.parent_window.config, f, indent=4)
            QMessageBox.information(self, "导出成功", f"当前配置已成功导出至:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"无法导出文件:\n{e}")