# --- START OF FILE modules/log_viewer_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "日志查看器"
MODULE_DESCRIPTION = "集中查看、解析和导出所有采集会话生成的详细日志文件。"
# ---

import os
import sys
import re
import shutil
from datetime import datetime
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QFileDialog, QMessageBox, QComboBox, QTableWidget, QTableWidgetItem,
                             QHeaderView, QSplitter, QApplication, QStyle, QMenu, QAbstractItemView)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QColor, QBrush

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("WARNING: pandas library not found. Log export to Excel will be unavailable.")

def get_base_path():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def create_page(parent_window, config, ToggleSwitchClass, icon_manager):
    """模块的入口函数，用于创建日志查看器页面。"""
    return LogViewerPage(parent_window, config, ToggleSwitchClass, icon_manager)

TRANSLATION_MAP = {
    "SESSION_START": "会话开始", "SESSION_END": "会话结束", "SESSION_CONFIG": "会话配置",
    "SESSION_CONFIG_CHANGE": "会话设置变更", "RECORD_START": "录音开始", "RECORDING_START": "录音开始",
    "RECORDING_SAVE_ATTEMPT": "尝试保存录音", "RECORDING_SAVE_SUCCESS": "录音保存成功",
    "INFO": "信息", "TTS_SUCCESS": "TTS生成成功", "ERROR": "错误", "FATAL": "致命错误",
    "Participant": "参与者", "Session Folder": "会话文件夹", "Wordlist": "词表",
    "Mode": "模式", "Scope": "范围", "Output folder": "输出文件夹", "Word": "单词",
    "Format": "格式", "Path": "路径", "Item ID": "项目ID", "Order changed to": "顺序变更为",
    "Sequential": "顺序", "Random": "随机", "Partial (One per group)": "部分(每组一个)",
    "Full List": "完整列表", "File saved successfully.": "文件已成功保存。", "Session ended by user.": "用户结束了会话。",
    "Dialect visual collection for wordlist": "图文采集词表", "Voicebank recording for wordlist": "提示音录制词表",
    "No missing TTS audio files to generate.": "TTS文件已全部生成，无需再处理。","All items in the list have been recorded.": "列表中的所有内容都已录制。",
}
LITERAL_VALUE_KEYS = {
    "Participant", "Session Folder", "Wordlist", "Word", "Item ID", "Path", "Format", "Output folder"
}

class LogViewerPage(QWidget):
    def __init__(self, parent_window, config, ToggleSwitchClass, icon_manager):
        super().__init__()
        self.parent_window = parent_window
        self.config = config
        self.ToggleSwitch = ToggleSwitchClass
        self.icon_manager = icon_manager
        self.BASE_PATH = get_base_path()
        self.parsed_data = []

        self._update_data_sources()
        self._init_ui()
        self.apply_layout_settings()
        self.update_icons()

        self.source_combo.currentTextChanged.connect(self.populate_session_list)
        self.session_list.itemSelectionChanged.connect(self.on_session_selection_changed)
        self.session_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self.open_session_context_menu)
        self.export_btn.clicked.connect(self.export_to_excel)
        self.chinese_mode_switch.stateChanged.connect(self.on_language_mode_changed)

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.addWidget(QLabel("选择数据源:"))
        self.source_combo = QComboBox()
        self.source_combo.addItems(self.DATA_SOURCES.keys())
        self.source_combo.setToolTip("选择要查看的日志来源：\n- 标准朗读采集: 来自'标准朗读采集'模块的会话日志。\n- 语音包与图文采集: 来自'提示音录制'和'看图说话采集'的日志。")
        left_layout.addWidget(self.source_combo)
        left_layout.addWidget(QLabel("包含日志的会话:"))
        self.session_list = QListWidget()
        self.session_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.session_list.setToolTip("此处列出所有包含日志文件的会话文件夹。\n支持按住Ctrl或Shift进行多选，然后右键进行批量删除。")
        left_layout.addWidget(self.session_list, 1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.table_label = QLabel("请从左侧选择一个会话以查看日志")
        self.log_table = QTableWidget()
        self.log_table.setColumnCount(4)
        self.log_table.setHorizontalHeaderLabels(["时间", "状态", "事件类型", "详情"])
        self.log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.log_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.log_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.log_table.setColumnWidth(0, 180)
        self.log_table.setColumnWidth(1, 80)
        self.log_table.setColumnWidth(2, 220)
        self.log_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setWordWrap(True)

        bottom_bar_layout = QHBoxLayout()
        bottom_bar_layout.addStretch(1)
        bottom_bar_layout.addWidget(QLabel("中文模式:"))
        self.chinese_mode_switch = self.ToggleSwitch()
        self.chinese_mode_switch.setToolTip("开启后，将事件类型和部分详情翻译为中文显示。")
        bottom_bar_layout.addWidget(self.chinese_mode_switch)
        bottom_bar_layout.addSpacing(20)
        self.export_btn = QPushButton("将会话日志导出为Excel")
        self.export_btn.setEnabled(False)
        bottom_bar_layout.addWidget(self.export_btn)

        right_layout.addWidget(self.table_label)
        right_layout.addWidget(self.log_table, 1)
        right_layout.addLayout(bottom_bar_layout)

        splitter.addWidget(self.left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        main_layout.addWidget(splitter)
        
    def update_icons(self):
        """从IconManager获取并设置所有图标。"""
        self.export_btn.setIcon(self.icon_manager.get_icon("export"))
        if not PANDAS_AVAILABLE:
            self.export_btn.setToolTip("功能不可用，请安装 pandas 库 (pip install pandas)")
        else:
            self.export_btn.setToolTip("将当前表格中显示的日志内容导出为一个Excel文件。")

    def apply_layout_settings(self):
        """应用来自全局配置的布局设置。"""
        config = self.parent_window.config
        ui_settings = config.get("ui_settings", {})
        width = ui_settings.get("editor_sidebar_width", 280)
        self.left_panel.setFixedWidth(width)
        
    def load_and_refresh(self):
        """当标签页被选中时，从主窗口调用的方法。"""
        self.config = self.parent_window.config
        self.apply_layout_settings()
        self.update_icons() # 确保切换回来时图标也是最新的
        self._update_data_sources()
        self.populate_session_list()

    def populate_session_list(self):
        source_name = self.source_combo.currentText()
        source_info = self.DATA_SOURCES.get(source_name)
        self.session_list.clear()
        self.log_table.setRowCount(0)
        self.table_label.setText("请从左侧选择一个会话以查看日志")
        self.export_btn.setEnabled(False)
        self.parsed_data.clear()
        if not source_info or not os.path.exists(source_info['path']):
            return

        base_path = source_info['path']
        try:
            sessions_with_logs = [d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d)) and os.path.exists(os.path.join(base_path, d, "log.txt"))]
            sessions_with_logs.sort(key=lambda s: os.path.getmtime(os.path.join(base_path, s)), reverse=True)
            self.session_list.addItems(sessions_with_logs)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法扫描日志文件夹: {e}")

    def on_session_selection_changed(self):
        selected_items = self.session_list.selectedItems()
        if not selected_items:
            self.table_label.setText("请从左侧选择一个会话以查看日志")
            self.log_table.setRowCount(0)
            self.export_btn.setEnabled(False)
            return
        
        session_name = selected_items[0].text()
        source_path = self.DATA_SOURCES[self.source_combo.currentText()]['path']
        log_path = os.path.join(source_path, session_name, 'log.txt')

        self.table_label.setText(f"正在查看日志: {session_name}")
        self.parsed_data = self.parse_log_file(log_path)
        self.populate_log_table()
        self.export_btn.setEnabled(PANDAS_AVAILABLE and bool(self.parsed_data))

    def parse_log_file(self, filepath):
        parsed = []
        log_pattern = re.compile(r'^\[(.*?)\] - \[([^\]]+)\] (.*)$')
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('---'): continue
                    match = log_pattern.match(line)
                    if match:
                        timestamp, event_type, details = match.groups()
                        parsed.append({"timestamp": timestamp, "event_type": event_type, "details": details})
                    else:
                        parsed.append({"timestamp": "N/A", "event_type": "UNPARSED_LINE", "details": line})
        except Exception as e:
            QMessageBox.critical(self, "日志读取错误", f"无法读取或解析日志文件:\n{filepath}\n\n错误: {e}")
        return parsed

    def populate_log_table(self):
        self.log_table.setRowCount(0)
        if not self.parsed_data: return
        
        self.log_table.setRowCount(len(self.parsed_data))
        for i, entry in enumerate(self.parsed_data):
            self.log_table.setItem(i, 0, QTableWidgetItem(entry['timestamp']))
            
            status_widget = QWidget()
            status_layout = QHBoxLayout(status_widget)
            status_layout.setAlignment(Qt.AlignCenter)
            status_layout.setContentsMargins(0,0,0,0)
            status_icon_label = QLabel()
            
            event_type = entry['event_type']
            icon_name = "info"
            if "SUCCESS" in event_type or "START" in event_type: icon_name = "success"
            elif "ERROR" in event_type or "FAIL" in event_type or "FATAL" in event_type: icon_name = "error"

            icon = self.icon_manager.get_icon(icon_name)
            if icon.isNull():
                if icon_name == "success": icon = self.style().standardIcon(QStyle.SP_DialogOkButton)
                elif icon_name == "error": icon = self.style().standardIcon(QStyle.SP_DialogCancelButton)
                else: icon = self.style().standardIcon(QStyle.SP_MessageBoxInformation)
            
            status_icon_label.setPixmap(icon.pixmap(24,24)) # Adjusted size for better visuals
            status_layout.addWidget(status_icon_label)
            self.log_table.setCellWidget(i, 1, status_widget)
            
            translated_event = self._translate(event_type, is_event_type=True)
            event_item = QTableWidgetItem(translated_event)
            if "SUCCESS" in event_type: event_item.setForeground(QBrush(QColor("#2E7D32")))
            elif "ERROR" in event_type: event_item.setForeground(QBrush(QColor("#C62828")))
            self.log_table.setItem(i, 2, event_item)

            translated_details = self._translate(entry['details'], is_event_type=False)
            self.log_table.setItem(i, 3, QTableWidgetItem(translated_details))
        
        self.log_table.resizeRowsToContents()
    
    def open_session_context_menu(self, position):
        selected_items = self.session_list.selectedItems()
        if not selected_items: return
        menu = QMenu()
        delete_action = menu.addAction(f"删除选中的 {len(selected_items)} 个会话")
        delete_action.setIcon(self.icon_manager.get_icon("delete")) # [新增] 添加图标
        action = menu.exec_(self.session_list.mapToGlobal(position))
        if action == delete_action: self.delete_selected_sessions()

    def delete_selected_sessions(self):
        selected_items = self.session_list.selectedItems()
        if not selected_items: return
        count = len(selected_items)
        reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除这 {count} 个会话文件夹及其所有内容吗？\n\n此操作不可撤销！", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes: return
        source_path = self.DATA_SOURCES[self.source_combo.currentText()]['path']
        for item in selected_items:
            session_folder_name = item.text()
            full_path = os.path.join(source_path, session_folder_name)
            try: shutil.rmtree(full_path)
            except Exception as e:
                QMessageBox.critical(self, "删除失败", f"删除文件夹 '{session_folder_name}' 时出错:\n{e}")
                break
        self.populate_session_list()

    def on_language_mode_changed(self): self.populate_log_table()
    
    def _translate(self, text, is_event_type=False):
        if not self.chinese_mode_switch.isChecked(): return text.replace("_", " ").title() if is_event_type else text
        return TRANSLATION_MAP.get(text, text.replace("_", " ").title()) if is_event_type else self._translate_details(text)
            
    def _translate_details(self, text):
        if text in TRANSLATION_MAP: return TRANSLATION_MAP[text]
        match_generated = re.match(r"Generated '(.*?)' with lang '(.*?)'", text)
        if match_generated: return f"已生成 '{match_generated.group(1)}'，语言: '{match_generated.group(2)}'"
        match_recorded = re.match(r"Session ended by user. Recorded (\d+)/(\d+) items.", text)
        if match_recorded: return f"用户结束了会话。已录制 {match_recorded.group(1)}/{match_recorded.group(2)} 项。"
        match_found_tts = re.match(r"Found (\d+) missing TTS files. Starting generation...", text)
        if match_found_tts: return f"发现 {match_found_tts.group(1)} 个缺失的TTS文件，开始生成..."
        translated_parts = []
        parts = re.split(r",\s*(?=[A-Za-z\s]+:\s*['\w])", text)
        for part in parts:
            match_kv = re.match(r"([^:]+):\s*['\"]?(.*?)['\"]?$", part.strip())
            if match_kv:
                key, value = match_kv.groups(); key_strip = key.strip()
                translated_key = TRANSLATION_MAP.get(key_strip, key_strip)
                translated_value = TRANSLATION_MAP.get(value.strip(), value.strip()) if key_strip not in LITERAL_VALUE_KEYS else value
                translated_parts.append(f"{translated_key}: '{translated_value}'")
            else: translated_parts.append(TRANSLATION_MAP.get(part.strip(), part.strip()))
        reconstructed_text = ", ".join(translated_parts)
        return reconstructed_text if reconstructed_text != text else text

    def export_to_excel(self):
        if not self.parsed_data: QMessageBox.warning(self, "无数据", "没有可导出的日志数据。"); return
        session_name = self.session_list.currentItem().text(); default_filename = f"log_{session_name}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        filepath, _ = QFileDialog.getSaveFileName(self, "将会话日志导出为Excel", default_filename, "Excel 文件 (*.xlsx)")
        if not filepath: return
        try:
            export_data = [{"时间": entry['timestamp'],"事件类型": self._translate(entry['event_type'], is_event_type=True),"详情": self._translate(entry['details'], is_event_type=False)} for entry in self.parsed_data]
            df = pd.DataFrame(export_data); df.to_excel(filepath, index=False)
            QMessageBox.information(self, "导出成功", f"日志已成功导出至:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"无法将日志导出到Excel文件:\n{e}")

    def _update_data_sources(self):
        self.DATA_SOURCES = {
            "标准朗读采集": { "path": self.config.get('file_settings', {}).get('results_dir', os.path.join(self.BASE_PATH, "Results")) },
            "语音包与图文采集": { "path": os.path.join(self.BASE_PATH, "audio_record") }
        }