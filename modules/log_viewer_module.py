# --- START OF FILE modules/log_viewer_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "日志查看器"
MODULE_DESCRIPTION = "集中查看、解析和导出所有采集会话生成的详细日志文件，或切换模式以分析速记卡学习进度。"
# ---

import os
import sys
import re
import shutil
import json
from datetime import datetime
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QFileDialog, QMessageBox, QComboBox, QTableWidget, QTableWidgetItem,
                             QHeaderView, QSplitter, QApplication, QStyle, QMenu, QAbstractItemView,
                             QLineEdit)
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

# ... (TRANSLATION_MAP 和 LITERAL_VALUE_KEYS 保持不变) ...
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
        self.current_mode = 'log' # 'log' or 'flashcard'

        self._init_ui()
        self.apply_layout_settings()
        self.update_icons()

        self.mode_switch.stateChanged.connect(self.on_mode_switched)
        self.source_combo.currentTextChanged.connect(self.populate_session_list)
        self.session_list.itemSelectionChanged.connect(self.on_session_selection_changed)
        self.session_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self.open_session_context_menu)
        self.export_btn.clicked.connect(self.export_to_excel)
        self.chinese_mode_switch.stateChanged.connect(self.on_language_mode_changed)
        self.filter_input.textChanged.connect(self.filter_table)

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        
        # --- [新增] 模式切换开关 ---
        mode_switch_layout = QHBoxLayout()
        mode_switch_layout.addWidget(QLabel("模式:"))
        mode_switch_layout.addStretch()
        mode_switch_layout.addWidget(QLabel("会话日志"))
        self.mode_switch = self.ToggleSwitch()
        self.mode_switch.setToolTip("切换查看模式：\n- 会话日志: 查看标准采集任务生成的详细日志。\n- 速记卡进度: 查看速记卡模块记录的学习进度。")
        mode_switch_layout.addWidget(self.mode_switch)
        mode_switch_layout.addWidget(QLabel("速记卡进度"))
        left_layout.addLayout(mode_switch_layout)
        left_layout.addSpacing(10)
        # --- 结束新增 ---
        
        self.source_combo_label = QLabel("选择数据源:")
        left_layout.addWidget(self.source_combo_label)
        self.source_combo = QComboBox()
        self.source_combo.setToolTip("选择要查看的日志来源。")
        left_layout.addWidget(self.source_combo)
        
        self.session_list_label = QLabel("包含日志的会话:")
        left_layout.addWidget(self.session_list_label)
        self.session_list = QListWidget()
        self.session_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.session_list.setToolTip("此处列出所有包含日志文件的会话文件夹。")
        left_layout.addWidget(self.session_list, 1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.table_label = QLabel("请从左侧选择一个项目以查看详情")
        
        # --- [新增] 筛选输入框 ---
        filter_layout = QHBoxLayout()
        self.filter_label = QLabel("筛选详情:")
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("输入关键词筛选日志...")
        self.filter_input.setClearButtonEnabled(True)
        filter_layout.addWidget(self.filter_label)
        filter_layout.addWidget(self.filter_input)
        right_layout.addLayout(filter_layout)
        # --- 结束新增 ---

        self.log_table = QTableWidget()
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
        self.export_btn = QPushButton("导出为Excel")
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
        self.export_btn.setIcon(self.icon_manager.get_icon("export"))
        if not PANDAS_AVAILABLE:
            self.export_btn.setToolTip("功能不可用，请安装 pandas 库 (pip install pandas)")
        else:
            self.export_btn.setToolTip("将当前表格中显示的内容导出为一个Excel文件。")
        self.filter_label.setPixmap(self.icon_manager.get_icon("filter").pixmap(16, 16))

    def apply_layout_settings(self):
        config = self.parent_window.config
        ui_settings = config.get("ui_settings", {})
        width = ui_settings.get("editor_sidebar_width", 280)
        self.left_panel.setFixedWidth(width)
        
    def load_and_refresh(self):
        self.config = self.parent_window.config
        self.apply_layout_settings()
        self.update_icons()
        self.on_mode_switched(self.mode_switch.isChecked())

    def on_mode_switched(self, is_flashcard_mode):
        self.current_mode = 'flashcard' if is_flashcard_mode else 'log'
        self.log_table.clearContents()
        self.log_table.setRowCount(0)
        self.parsed_data.clear()
        self.table_label.setText("请从左侧选择一个项目以查看详情")
        self.export_btn.setEnabled(False)
        self.filter_input.clear()
        
        if self.current_mode == 'log':
            self._setup_log_mode()
        else:
            self._setup_flashcard_mode()
            
    def _setup_log_mode(self):
        self.source_combo.show()
        self.source_combo_label.show()
        self.filter_input.show()
        self.filter_label.show()
        
        self.session_list_label.setText("包含日志的会话:")
        self.session_list.setToolTip("此处列出所有包含日志文件的会话文件夹。")
        
        # 更新数据源并重新填充
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        log_sources = {
            "标准朗读采集": self.config.get('file_settings', {}).get('results_dir', os.path.join(self.BASE_PATH, "Results")),
            "语音包与图文采集": os.path.join(self.BASE_PATH, "audio_record")
        }
        self.source_combo.addItems(log_sources.keys())
        self.source_combo.blockSignals(False)
        self.populate_session_list()

    def _setup_flashcard_mode(self):
        self.source_combo.hide()
        self.source_combo_label.hide()
        self.filter_input.hide()
        self.filter_label.hide()
        
        self.session_list_label.setText("速记卡进度文件:")
        self.session_list.setToolTip("此处列出所有速记卡学习进度文件 (.json)。")
        
        # 直接填充列表，因为数据源是固定的
        self.populate_session_list()

    def populate_session_list(self):
        self.session_list.clear()
        if self.current_mode == 'log':
            source_name = self.source_combo.currentText()
            if not source_name: return
            
            log_sources = {
                "标准朗读采集": self.config.get('file_settings', {}).get('results_dir', os.path.join(self.BASE_PATH, "Results")),
                "语音包与图文采集": os.path.join(self.BASE_PATH, "audio_record")
            }
            base_path = log_sources.get(source_name)
            
            if not base_path or not os.path.exists(base_path): return
            try:
                sessions_with_logs = [d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d)) and os.path.exists(os.path.join(base_path, d, "log.txt"))]
                sessions_with_logs.sort(key=lambda s: os.path.getmtime(os.path.join(base_path, s)), reverse=True)
                self.session_list.addItems(sessions_with_logs)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法扫描日志文件夹: {e}")
        else: # Flashcard mode
            progress_dir = os.path.join(self.BASE_PATH, "flashcards", "progress")
            if not os.path.exists(progress_dir): return
            try:
                progress_files = [f for f in os.listdir(progress_dir) if f.endswith('.json')]
                progress_files.sort(key=lambda f: os.path.getmtime(os.path.join(progress_dir, f)), reverse=True)
                self.session_list.addItems(progress_files)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法扫描速记卡进度文件夹: {e}")

    def on_session_selection_changed(self):
        selected_items = self.session_list.selectedItems()
        if not selected_items:
            self.table_label.setText("请从左侧选择一个项目以查看详情")
            self.log_table.setRowCount(0)
            self.export_btn.setEnabled(False)
            return

        item_name = selected_items[0].text()
        self.table_label.setText(f"正在查看: {item_name}")
        
        if self.current_mode == 'log':
            source_path = self.source_combo.currentData()
            if self.source_combo.currentText() == "标准朗读采集":
                source_path = self.config.get('file_settings', {}).get('results_dir')
            else:
                source_path = os.path.join(self.BASE_PATH, "audio_record")
            
            log_path = os.path.join(source_path, item_name, 'log.txt')
            self.parsed_data = self.parse_log_file(log_path)
            self.populate_log_table()
        else: # Flashcard mode
            progress_dir = os.path.join(self.BASE_PATH, "flashcards", "progress")
            progress_path = os.path.join(progress_dir, item_name)
            self.parsed_data = self.parse_flashcard_progress(progress_path)
            self.populate_flashcard_table()

        self.export_btn.setEnabled(PANDAS_AVAILABLE and bool(self.parsed_data))

    def parse_flashcard_progress(self, filepath):
        parsed = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for word, stats in data.items():
                stats['word'] = word
                parsed.append(stats)
            # Sort by mastered status (unmastered first), then by last viewed
            parsed.sort(key=lambda x: (x.get('mastered', False), -x.get('last_viewed_ts', 0)))
        except (json.JSONDecodeError, IOError) as e:
            QMessageBox.critical(self, "文件读取错误", f"无法读取或解析速记卡进度文件:\n{filepath}\n\n错误: {e}")
        return parsed
        
    def populate_flashcard_table(self):
        self.log_table.setSortingEnabled(False)
        self.log_table.clearContents()
        self.log_table.setColumnCount(6)
        
        is_chinese = self.chinese_mode_switch.isChecked()
        headers = ["单词/ID", "掌握状态", "学习次数", "错误次数", "复习等级", "下次复习"] if is_chinese else \
                  ["Word/ID", "Mastered", "Views", "Errors", "Level", "Next Review"]
        self.log_table.setHorizontalHeaderLabels(headers)
        
        if not self.parsed_data: return
        self.log_table.setRowCount(len(self.parsed_data))
        
        for i, entry in enumerate(self.parsed_data):
            self.log_table.setItem(i, 0, QTableWidgetItem(entry.get('word', 'N/A')))
            
            mastered = entry.get('mastered', False)
            mastered_text = (("是" if is_chinese else "Yes") if mastered else ("否" if is_chinese else "No"))
            mastered_item = QTableWidgetItem(mastered_text)
            mastered_item.setIcon(self.icon_manager.get_icon("success") if mastered else self.icon_manager.get_icon("error"))
            mastered_item.setTextAlignment(Qt.AlignCenter)  # <-- 新增这一行
            self.log_table.setItem(i, 1, mastered_item)
            
            self.log_table.setItem(i, 2, QTableWidgetItem(str(entry.get('views', 0))))
            self.log_table.setItem(i, 3, QTableWidgetItem(str(entry.get('errors', 0))))
            self.log_table.setItem(i, 4, QTableWidgetItem(str(entry.get('level', 0))))

            next_review_ts = entry.get('next_review_ts', 0)
            if next_review_ts > 0:
                dt_object = datetime.fromtimestamp(next_review_ts)
                review_date_str = dt_object.strftime('%Y-%m-%d')
                if dt_object.date() < datetime.now().date():
                    review_item = QTableWidgetItem(review_date_str)
                    review_item.setForeground(QBrush(QColor("#C62828"))) # Red for overdue
                    review_item.setToolTip("此卡片已到期，应立即复习！")
                else:
                    review_item = QTableWidgetItem(review_date_str)
            else:
                review_item = QTableWidgetItem("N/A")
            self.log_table.setItem(i, 5, review_item)

        self.log_table.resizeColumnsToContents()
        self.log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

    def filter_table(self, text):
        if self.current_mode != 'log': return
        search_term = text.lower()
        for i in range(self.log_table.rowCount()):
            event_item = self.log_table.item(i, 2)
            details_item = self.log_table.item(i, 3)
            event_text = event_item.text().lower() if event_item else ""
            details_text = details_item.text().lower() if details_item else ""
            
            if search_term in event_text or search_term in details_text:
                self.log_table.setRowHidden(i, False)
            else:
                self.log_table.setRowHidden(i, True)

    def export_to_excel(self):
        if not self.parsed_data:
            QMessageBox.warning(self, "无数据", "没有可导出的数据。")
            return

        item_name = self.session_list.currentItem().text()
        default_filename = f"{os.path.splitext(item_name)[0]}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        filepath, _ = QFileDialog.getSaveFileName(self, "导出为Excel", default_filename, "Excel 文件 (*.xlsx)")
        if not filepath: return
        
        try:
            if self.current_mode == 'log':
                export_data = [{"时间": entry['timestamp'],"事件类型": self._translate(entry['event_type'], True),"详情": self._translate(entry['details'], False)} for entry in self.parsed_data]
            else: # Flashcard mode
                is_chinese = self.chinese_mode_switch.isChecked()
                headers_key = ["单词/ID", "掌握状态", "学习次数", "错误次数", "复习等级", "下次复习"] if is_chinese else ["Word/ID", "Mastered", "Views", "Errors", "Level", "Next Review"]
                export_data = []
                for entry in self.parsed_data:
                    mastered_text = (("是" if is_chinese else "Yes") if entry.get('mastered', False) else ("否" if is_chinese else "No"))
                    next_review_ts = entry.get('next_review_ts', 0)
                    review_date_str = datetime.fromtimestamp(next_review_ts).strftime('%Y-%m-%d') if next_review_ts > 0 else "N/A"
                    export_data.append({
                        headers_key[0]: entry.get('word', 'N/A'),
                        headers_key[1]: mastered_text,
                        headers_key[2]: entry.get('views', 0),
                        headers_key[3]: entry.get('errors', 0),
                        headers_key[4]: entry.get('level', 0),
                        headers_key[5]: review_date_str
                    })
            
            df = pd.DataFrame(export_data)
            df.to_excel(filepath, index=False)
            QMessageBox.information(self, "导出成功", f"数据已成功导出至:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"无法将数据导出到Excel文件:\n{e}")

    # --- Methods from original implementation, slightly adapted for clarity ---
    def populate_log_table(self):
        self.log_table.setSortingEnabled(False)
        self.log_table.clearContents()
        self.log_table.setColumnCount(4)
        self.log_table.setHorizontalHeaderLabels(["时间", "状态", "事件类型", "详情"])

        if not self.parsed_data: return
        self.log_table.setRowCount(len(self.parsed_data))
        for i, entry in enumerate(self.parsed_data):
            # ... (the rest of the original populate_log_table logic remains here, unchanged)
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
            
            status_icon_label.setPixmap(icon.pixmap(24,24))
            status_layout.addWidget(status_icon_label)
            self.log_table.setCellWidget(i, 1, status_widget)
            
            translated_event = self._translate(event_type, is_event_type=True)
            event_item = QTableWidgetItem(translated_event)
            if "SUCCESS" in event_type: event_item.setForeground(QBrush(QColor("#2E7D32")))
            elif "ERROR" in event_type: event_item.setForeground(QBrush(QColor("#C62828")))
            self.log_table.setItem(i, 2, event_item)

            translated_details = self._translate(entry['details'], is_event_type=False)
            self.log_table.setItem(i, 3, QTableWidgetItem(translated_details))
        
        self.log_table.resizeColumnsToContents()
        self.log_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
    
    def on_language_mode_changed(self):
        if self.current_mode == 'log':
            self.populate_log_table()
        else:
            self.populate_flashcard_table()
            
    def open_session_context_menu(self, position):
        selected_items = self.session_list.selectedItems()
        if not selected_items: return
        menu = QMenu()
        
        item_text = "会话" if self.current_mode == 'log' else "进度文件"
        delete_action = menu.addAction(f"删除选中的 {len(selected_items)} 个{item_text}")
        delete_action.setIcon(self.icon_manager.get_icon("delete"))
        action = menu.exec_(self.session_list.mapToGlobal(position))
        
        if action == delete_action: self.delete_selected_sessions()

    def delete_selected_sessions(self):
        selected_items = self.session_list.selectedItems()
        if not selected_items: return
        
        count = len(selected_items)
        item_text = "会话文件夹" if self.current_mode == 'log' else "进度文件"
        reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除这 {count} 个{item_text}及其所有内容吗？\n此操作不可撤销！", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes: return
        
        if self.current_mode == 'log':
            source_path = self.source_combo.currentData()
            if self.source_combo.currentText() == "标准朗读采集":
                 source_path = self.config.get('file_settings', {}).get('results_dir')
            else:
                 source_path = os.path.join(self.BASE_PATH, "audio_record")
            for item in selected_items:
                full_path = os.path.join(source_path, item.text())
                try: shutil.rmtree(full_path)
                except Exception as e: QMessageBox.critical(self, "删除失败", f"删除文件夹 '{item.text()}' 时出错:\n{e}"); break
        else: # Flashcard mode
            source_path = os.path.join(self.BASE_PATH, "flashcards", "progress")
            for item in selected_items:
                full_path = os.path.join(source_path, item.text())
                try: os.remove(full_path)
                except Exception as e: QMessageBox.critical(self, "删除失败", f"删除文件 '{item.text()}' 时出错:\n{e}"); break

        self.populate_session_list()
    
    def parse_log_file(self, filepath): return super(LogViewerPage, self).parse_log_file(filepath) if hasattr(super(LogViewerPage, self), 'parse_log_file') else self._parse_log_file_impl(filepath)

    def _parse_log_file_impl(self, filepath):
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
    
    def _translate(self, text, is_event_type=False): return super(LogViewerPage, self)._translate(text, is_event_type) if hasattr(super(LogViewerPage, self), '_translate') else self._translate_impl(text, is_event_type)

    def _translate_impl(self, text, is_event_type=False):
        if not self.chinese_mode_switch.isChecked(): return text.replace("_", " ").title() if is_event_type else text
        return TRANSLATION_MAP.get(text, text.replace("_", " ").title()) if is_event_type else self._translate_details_impl(text)
            
    def _translate_details_impl(self, text):
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