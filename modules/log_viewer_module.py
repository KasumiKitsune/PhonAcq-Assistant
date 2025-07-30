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
from modules.custom_widgets_module import AnimatedListWidget
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
    "INFO": "信息", 
    # [修改] 新增和细化翻译
    "TTS_SUCCESS": "TTS生成成功", 
    "TTS_ERROR": "TTS生成失败", 
    "WARNING": "警告",
    "ERROR": "错误", "FATAL": "致命错误",
    "Participant": "参与者", "Session Folder": "会话文件夹", "Wordlist": "词表",
    "Mode": "模式", "Scope": "范围", "Output folder": "输出文件夹", "Word": "单词",
    "Format": "格式", "Path": "路径", "Item ID": "项目ID", "Order changed to": "顺序变更为",
    "Sequential": "顺序", "Random": "随机", "Partial (One per group)": "部分(每组一个)",
    "Full List": "完整列表", "File saved successfully.": "文件已成功保存。", "Session ended by user.": "用户结束了会话。",
    "Dialect visual collection for wordlist": "图文采集词表", "Voicebank recording for wordlist": "提示音录制词表",
    "No missing TTS audio files to generate.": "TTS文件已全部生成，无需再处理。",
    "All items in the list have been recorded.": "列表中的所有内容都已录制。",
    # [新增] 新的完整句子翻译
    "User chose to ignore missing TTS files and continue session.": "用户选择忽略缺失的TTS文件并继续会话。"
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
        self.session_list = AnimatedListWidget()
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
        
        # [修改] 定义新的、更详细的数据源
        results_dir_base = self.config.get('file_settings', {}).get('results_dir', os.path.join(self.BASE_PATH, "Results"))
        self.LOG_DATA_SOURCES = {
            "标准朗读采集 (common)": {
                "path": os.path.join(results_dir_base, "common")
            },
            "看图说话采集 (visual)": {
                "path": os.path.join(results_dir_base, "visual")
            },
            "语音包录制": {
                "path": os.path.join(self.BASE_PATH, "audio_record")
            }
        }
        
        # 更新数据源并重新填充
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItems(self.LOG_DATA_SOURCES.keys())
        self.source_combo.blockSignals(False)
        
        # 手动触发一次列表填充
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

    def load_log_file_from_path(self, filepath):
        """公共API: 从外部（如文件管理器）加载一个指定的日志文件。"""
        
        # --- [核心修复] ---
        # 1. 在执行任何操作前，强制调用一次 load_and_refresh。
        #    这将确保 _build_data_sources() 被执行，self.LOG_DATA_SOURCES 属性被正确创建和填充。
        self.load_and_refresh()
        # --- [修复结束] ---

        dir_path = os.path.dirname(filepath)
        log_name = os.path.basename(dir_path) # 日志的标识是其父文件夹的名称
        
        # 2. 切换到正确的日志源
        found_source = False
        # 现在 self.LOG_DATA_SOURCES 可以被安全地访问
        for source_name, source_info in self.LOG_DATA_SOURCES.items():
            # 使用 os.path.realpath 确保路径比较的健壮性
            if os.path.realpath(source_info['path']) == os.path.realpath(os.path.dirname(dir_path)):
                self.source_combo.setCurrentText(source_name)
                found_source = True
                break
        
        if not found_source:
             QMessageBox.warning(self, "数据源不匹配", f"日志文件 '{log_name}' 不属于任何已知的数据源。")
             return

        # 3. 在列表中找到并选中该会话
        items = self.session_list.findItems(log_name, Qt.MatchExactly)
        if items:
            self.session_list.setCurrentItem(items[0])
        else:
            QMessageBox.warning(self, "会话未找到", f"会话 '{log_name}' 不在当前加载的列表中。")

    def populate_session_list(self):
        self.session_list.clear()
        self.log_table.setRowCount(0)
        self.table_label.setText("请从左侧选择一个项目以查看详情")
        self.export_btn.setEnabled(False)
        self.parsed_data.clear()

        if self.current_mode == 'log':
            source_name = self.source_combo.currentText()
            if not source_name: return
            
            # [修改] 从实例属性 LOG_DATA_SOURCES 获取路径
            source_info = self.LOG_DATA_SOURCES.get(source_name)
            if not source_info or not os.path.exists(source_info['path']):
                return
            base_path = source_info['path']
            # ... (后续的 try-except 块保持不变) ...
            try:
                sessions_with_logs = [d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d)) and os.path.exists(os.path.join(base_path, d, "log.txt"))]
                sessions_with_logs.sort(key=lambda s: os.path.getmtime(os.path.join(base_path, s)), reverse=True)
                self.session_list.addItemsWithAnimation(sessions_with_logs)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法扫描日志文件夹: {e}")
        else:
            progress_dir = os.path.join(self.BASE_PATH, "flashcards", "progress")
            if not os.path.exists(progress_dir): return
            try:
                progress_files = [f for f in os.listdir(progress_dir) if f.endswith('.json')]
                progress_files.sort(key=lambda f: os.path.getmtime(os.path.join(progress_dir, f)), reverse=True)
                self.session_list.addItemsWithAnimation(progress_files)
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
            source_name = self.source_combo.currentText()
            source_info = self.LOG_DATA_SOURCES.get(source_name)
            if not source_info: return
            
            source_path = source_info['path']
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
        self.log_table.setRowCount(0) # Clear rows first
        self.log_table.setColumnCount(6)
        
        is_chinese = self.chinese_mode_switch.isChecked()
        headers = ["单词/ID", "掌握状态", "学习次数", "错误次数", "复习等级", "下次复习"] if is_chinese else \
                  ["Word/ID", "Mastered", "Views", "Errors", "Level", "Next Review"]
        self.log_table.setHorizontalHeaderLabels(headers)
        
        if not self.parsed_data: return
        self.log_table.setRowCount(len(self.parsed_data))
        
        for i, entry in enumerate(self.parsed_data):
            # Word/ID
            word_text = entry.get('word', 'N/A')
            word_item = QTableWidgetItem(word_text)
            word_item.setToolTip(word_text)
            self.log_table.setItem(i, 0, word_item)
            
            # Mastered Status
            mastered = entry.get('mastered', False)
            mastered_text = (("是" if is_chinese else "Yes") if mastered else ("否" if is_chinese else "No"))
            mastered_item = QTableWidgetItem(mastered_text)
            mastered_item.setIcon(self.icon_manager.get_icon("success") if mastered else self.icon_manager.get_icon("error"))
            mastered_item.setTextAlignment(Qt.AlignCenter)
            mastered_item.setToolTip(mastered_text)
            self.log_table.setItem(i, 1, mastered_item)
            
            # Views
            views_text = str(entry.get('views', 0))
            views_item = QTableWidgetItem(views_text)
            views_item.setToolTip(views_text)
            self.log_table.setItem(i, 2, views_item)

            # Errors
            errors_text = str(entry.get('errors', 0))
            errors_item = QTableWidgetItem(errors_text)
            errors_item.setToolTip(errors_text)
            self.log_table.setItem(i, 3, errors_item)

            # Level
            level_text = str(entry.get('level', 0))
            level_item = QTableWidgetItem(level_text)
            level_item.setToolTip(level_text)
            self.log_table.setItem(i, 4, level_item)

            # Next Review
            next_review_ts = entry.get('next_review_ts', 0)
            if next_review_ts > 0:
                dt_object = datetime.fromtimestamp(next_review_ts)
                review_date_str = dt_object.strftime('%Y-%m-%d')
                review_item = QTableWidgetItem(review_date_str)
                if dt_object.date() < datetime.now().date():
                    review_item.setForeground(QBrush(QColor("#C62828")))
                    review_item.setToolTip(f"{review_date_str} (已到期，应立即复习！)")
                else:
                    review_item.setToolTip(review_date_str)
            else:
                review_date_str = "N/A"
                review_item = QTableWidgetItem(review_date_str)
                review_item.setToolTip(review_date_str)
            self.log_table.setItem(i, 5, review_item)

        # [修改] 应用列宽策略
        # 先自适应内容，让Qt计算出最佳宽度
        self.log_table.resizeColumnsToContents()
        # 然后设置为可交互，用户可以在自适应的基础上再调整
        for col in range(self.log_table.columnCount()):
            self.log_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Interactive)
        # 最后，让第一列（通常是内容最多的）拉伸以填充剩余空间
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
            QMessageBox.warning(self, "无数据", "没有可导出的日志数据。")
            return

        # [修复] 健壮地获取会话/文件名以用于默认文件名
        session_name = ""
        current_item = self.session_list.currentItem()
        if current_item:
            session_name = current_item.text()
        else:
            # 如果没有当前项（例如全选），则使用选择的第一个项目
            selected_items = self.session_list.selectedItems()
            if selected_items:
                session_name = selected_items[0].text()
            else:
                # 理论上不应该发生，因为按钮在无选择时禁用，但作为保险
                QMessageBox.warning(self, "无选择", "请先从左侧选择一个项目。")
                return
        
        # 从文件名中移除扩展名（主要针对速记卡模式的.json）
        session_name_base = os.path.splitext(session_name)[0]
        
        default_filename = f"export_{session_name_base}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        filepath, _ = QFileDialog.getSaveFileName(self, "导出为Excel", default_filename, "Excel 文件 (*.xlsx)")
        
        if not filepath:
            return
        
        try:
            # [修改] 数据准备逻辑保持不变，但移到 try-except 块内
            if self.current_mode == 'log':
                export_data = [
                    {
                        "时间": entry['timestamp'],
                        "事件类型": self._translate(entry['event_type'], is_event_type=True),
                        "详情": self._translate(entry['details'], is_event_type=False)
                    } 
                    for entry in self.parsed_data
                ]
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
        self.log_table.setRowCount(0) # Clear rows first
        self.log_table.setColumnCount(4)
        self.log_table.setHorizontalHeaderLabels(["时间", "状态", "事件类型", "详情"])

        if not self.parsed_data: return
        self.log_table.setRowCount(len(self.parsed_data))
        
        for i, entry in enumerate(self.parsed_data):
            # Timestamp Item
            timestamp_item = QTableWidgetItem(entry['timestamp'])
            timestamp_item.setToolTip(entry['timestamp'])
            self.log_table.setItem(i, 0, timestamp_item)
            
            # Status Widget (no changes needed here)
            # ... (original status widget creation logic) ...
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
            
            # Event Type Item
            translated_event = self._translate(entry['event_type'], is_event_type=True)
            event_item = QTableWidgetItem(translated_event)
            event_item.setToolTip(translated_event) # Add tooltip
            if "SUCCESS" in event_type: event_item.setForeground(QBrush(QColor("#2E7D32")))
            elif "ERROR" in event_type: event_item.setForeground(QBrush(QColor("#C62828")))
            self.log_table.setItem(i, 2, event_item)

            # Details Item
            translated_details = self._translate(entry['details'], is_event_type=False)
            details_item = QTableWidgetItem(translated_details)
            details_item.setToolTip(translated_details) # Add tooltip
            self.log_table.setItem(i, 3, details_item)
        
        # [修改] 应用列宽策略
        self.log_table.resizeColumnsToContents()
        self.log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.log_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents) # Status column should be tight
        self.log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.log_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch) # Stretch last column
        self.log_table.resizeRowsToContents()
    
    def on_language_mode_changed(self):
        if self.current_mode == 'log':
            self.populate_log_table()
        else:
            self.populate_flashcard_table()
            
    def open_session_context_menu(self, position):
        selected_items = self.session_list.selectedItems()
        if not selected_items: return
        menu = QMenu(self.session_list)
        
        item_text = "会话" if self.current_mode == 'log' else "进度文件"
        delete_action = menu.addAction(f"删除选中的 {len(selected_items)} 个{item_text}")
        delete_action.setIcon(self.icon_manager.get_icon("delete"))
        action = menu.exec_(self.session_list.mapToGlobal(position))
        
        if action == delete_action: self.delete_selected_sessions()

    def delete_selected_sessions(self):
        # [修复-1] 将 selected_items 的定义移到方法开头
        selected_items = self.session_list.selectedItems()
        if not selected_items:
            return

        count = len(selected_items)
        item_text = "会话文件夹" if self.current_mode == 'log' else "进度文件"
        reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除这 {count} 个{item_text}吗？\n此操作不可撤销！", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply != QMessageBox.Yes:
            return
        
        if self.current_mode == 'log':
            # [修复-2] 统一从 LOG_DATA_SOURCES 获取正确的、绝对的基准路径
            source_name = self.source_combo.currentText()
            source_info = self.LOG_DATA_SOURCES.get(source_name)
            if not source_info:
                QMessageBox.critical(self, "错误", "无法确定数据源路径。")
                return
            base_path = source_info['path']
            
            for item in selected_items:
                session_folder_name = item.text()
                # 构造绝对路径进行删除
                full_path = os.path.join(base_path, session_folder_name)
                try:
                    if os.path.exists(full_path):
                        shutil.rmtree(full_path)
                    else:
                        # 如果路径已经不存在，也算作“成功”，避免报错
                        print(f"Warning: Path to delete does not exist, skipping: {full_path}")
                except Exception as e:
                    QMessageBox.critical(self, "删除失败", f"删除文件夹 '{session_folder_name}' 时出错:\n{e}")
                    # 出错后立即停止，防止后续更多错误弹窗
                    break
        else: # Flashcard mode
            base_path = os.path.join(self.BASE_PATH, "flashcards", "progress")
            for item in selected_items:
                progress_file_name = item.text()
                full_path = os.path.join(base_path, progress_file_name)
                try:
                    if os.path.exists(full_path):
                        os.remove(full_path)
                except Exception as e:
                    QMessageBox.critical(self, "删除失败", f"删除文件 '{progress_file_name}' 时出错:\n{e}")
                    break

        # 无论成功失败，都刷新列表以反映当前状态
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
        if text in TRANSLATION_MAP:
            return TRANSLATION_MAP[text]
        
        # 匹配 TTS_ERROR 详情
        match_tts_error = re.match(r"Failed to generate TTS for '(.*?)': (.*)", text)
        if match_tts_error:
            word = match_tts_error.group(1)
            error_msg = match_tts_error.group(2)
            return f"词条: '{word}'，错误: {error_msg}"
        
        # [新增] 匹配 "Failed to load wordlist" 格式的日志
        match_load_failed = re.match(r"Failed to load wordlist '(.*?)': (.*)", text)
        if match_load_failed:
            wordlist_name = match_load_failed.group(1)
            error_details = match_load_failed.group(2)
            # 对错误详情本身进行一次尝试性翻译，以处理嵌套的错误信息
            translated_error_details = self._translate_details_impl(error_details)
            return f"加载词表 '{wordlist_name}' 失败: {translated_error_details}"

        match_generated = re.match(r"Generated '(.*?)' with lang '(.*?)'", text)
        if match_generated: 
            return f"已生成 '{match_generated.group(1)}'，语言: '{match_generated.group(2)}'"
        
        match_recorded = re.match(r"Session ended by user. Recorded (\d+)/(\d+) items.", text)
        if match_recorded: 
            return f"用户结束了会话。已录制 {match_recorded.group(1)}/{match_recorded.group(2)} 项。"
        
        match_found_tts = re.match(r"Found (\d+) missing TTS files. Starting generation...", text)
        if match_found_tts: 
            return f"发现 {match_found_tts.group(1)} 个缺失的TTS文件，开始生成..."
        
        # --- 原有的键值对解析逻辑 ---
        translated_parts = []
        parts = re.split(r",\s*(?=[A-Za-z\s]+:\s*['\w])", text)
        for part in parts:
            match_kv = re.match(r"([^:]+):\s*['\"]?(.*?)['\"]?$", part.strip())
            if match_kv:
                key, value = match_kv.groups()
                key_strip = key.strip()
                translated_key = TRANSLATION_MAP.get(key_strip, key_strip)
                translated_value = TRANSLATION_MAP.get(value.strip(), value.strip()) if key_strip not in LITERAL_VALUE_KEYS else value
                translated_parts.append(f"{translated_key}: '{translated_value}'")
            else:
                translated_parts.append(TRANSLATION_MAP.get(part.strip(), part.strip()))
        
        reconstructed_text = ", ".join(translated_parts)
        return reconstructed_text if reconstructed_text != text else text