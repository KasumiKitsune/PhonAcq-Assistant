# --- START OF FILE modules/wordlist_editor_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "通用词表编辑器"
MODULE_DESCRIPTION = "在程序内直接创建、编辑和保存单词/词语列表。"
# ---

import os
import sys
from datetime import datetime
import json
import shutil # [新增] 用于文件复制
import subprocess # [新增] 用于打开文件浏览器

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QFileDialog, QMessageBox, QTableWidget,
                             QTableWidgetItem, QHeaderView, QComboBox, QShortcut,
                             QUndoStack, QUndoCommand, QApplication, QMenu)
from PyQt5.QtCore import Qt, QSize, QEvent
from PyQt5.QtGui import QKeySequence, QIcon

# ... (LANGUAGE_MAP, FLAG_CODE_MAP, get_base_path_for_module, create_page, Command classes 不变) ...
LANGUAGE_MAP = {
    "自动检测": "", "英语 (美国)": "en-us", "英语 (英国)": "en-uk", "中文 (普通话）": "zh-cn", "日语": "ja", "韩语": "ko",
    "法语 (法国)": "fr", "德语": "de", "西班牙语": "es", "葡萄牙语": "pt", "意大利语": "it", "俄语": "ru",
    "荷兰语": "nl", "波兰语": "pl", "土耳其语": "tr", "越南语": "vi", "印地语": "hi", "阿拉伯语": "ar", "泰语": "th", "印尼语": "id",
}
FLAG_CODE_MAP = {
    "": "auto", "en-us": "us", "en-uk": "gb", "zh-cn": "cn", "ja": "jp", "ko": "kr", "fr": "fr", "de": "de", "es": "es", "pt": "pt",
    "it": "it", "ru": "ru", "nl": "nl", "pl": "pl", "tr": "tr", "vi": "vn", "hi": "in", "ar": "sa", "th": "th", "id": "id",
}
def get_base_path_for_module():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
def create_page(parent_window, WORD_LIST_DIR, icon_manager, detect_language_func):
    return WordlistEditorPage(parent_window, WORD_LIST_DIR, icon_manager, detect_language_func)
class WordlistChangeCellCommand(QUndoCommand):
    def __init__(self, editor, row, col, old_text, new_text, description):
        super().__init__(description); self.editor = editor; self.table = editor.table_widget; self.row, self.col = row, col; self.old_text, self.new_text = old_text, new_text
    def redo(self):
        item = self.table.item(self.row, self.col);
        if not item: item = QTableWidgetItem(); self.table.setItem(self.row, self.col, item)
        item.setText(self.new_text)
    def undo(self):
        item = self.table.item(self.row, self.col);
        if not item: item = QTableWidgetItem(); self.table.setItem(self.row, self.col, item)
        item.setText(self.old_text)
class WordlistChangeLanguageCommand(QUndoCommand):
    def __init__(self, editor, row, old_lang_code, new_lang_code, description):
        super().__init__(description); self.editor = editor; self.table = editor.table_widget; self.row = row; self.old_lang, self.new_lang = old_lang_code, new_lang_code
    def _set_language(self, lang_code):
        widget = self.table.cellWidget(self.row, 3);
        if isinstance(widget, QComboBox):
            index = widget.findData(lang_code);
            if index != -1: widget.setCurrentIndex(index)
    def redo(self): self._set_language(self.new_lang)
    def undo(self): self._set_language(self.old_lang)
class WordlistRowOperationCommand(QUndoCommand):
    def __init__(self, editor, start_row, rows_data, operation_type, move_offset=0, description=""):
        super().__init__(description); self.editor = editor; self.table = editor.table_widget; self.start_row, self.rows_data, self.type, self.move_offset = start_row, rows_data, operation_type, move_offset
    def _insert_rows(self, at_row, data):
        for i, row_data in enumerate(data): self.table.insertRow(at_row + i); self.editor.populate_row(at_row + i, row_data)
    def _remove_rows(self, at_row, count):
        for _ in range(count): self.table.removeRow(at_row)
    def redo(self):
        self.table.blockSignals(True)
        if self.type == 'remove': self._remove_rows(self.start_row, len(self.rows_data))
        elif self.type == 'add': self._insert_rows(self.start_row, self.rows_data)
        elif self.type == 'move': self._remove_rows(self.start_row, len(self.rows_data)); self._insert_rows(self.start_row + self.move_offset, self.rows_data)
        self.table.blockSignals(False)
    def undo(self):
        self.table.blockSignals(True)
        if self.type == 'remove': self._insert_rows(self.start_row, self.rows_data)
        elif self.type == 'add': self._remove_rows(self.start_row, len(self.rows_data))
        elif self.type == 'move': self._remove_rows(self.start_row + self.move_offset, len(self.rows_data)); self._insert_rows(self.start_row, self.rows_data)
        self.table.blockSignals(False)


class WordlistEditorPage(QWidget):
    def __init__(self, parent_window, WORD_LIST_DIR, icon_manager, detect_language_func):
        super().__init__()
        self.parent_window = parent_window; self.WORD_LIST_DIR = WORD_LIST_DIR; self.icon_manager = icon_manager
        self.detect_language_func = detect_language_func
        self.current_wordlist_path = None; self.old_text_before_edit = None; self.old_lang_before_edit = None
        self.undo_stack = QUndoStack(self); self.undo_stack.setUndoLimit(100)
        self.base_path = get_base_path_for_module(); self.flags_path = os.path.join(self.base_path, 'assets', 'flags')

        self._init_ui()
        self.setup_connections_and_shortcuts()
        self.update_icons()
        self.apply_layout_settings()
        self.refresh_file_list()

    def _init_ui(self):
        main_layout = QHBoxLayout(self); self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        # [修改] 启用自定义上下文菜单
        self.file_list_widget = QListWidget()
        self.file_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list_widget.setToolTip("所有可编辑的单词表文件。\n右键单击可进行更多操作。")
        self.new_btn = QPushButton("新建单词表");
        file_btn_layout = QHBoxLayout(); self.save_btn = QPushButton("保存"); self.save_as_btn = QPushButton("另存为...")
        file_btn_layout.addWidget(self.save_btn); file_btn_layout.addWidget(self.save_as_btn)
        left_layout.addWidget(QLabel("单词表文件:")); left_layout.addWidget(self.file_list_widget); left_layout.addWidget(self.new_btn); left_layout.addLayout(file_btn_layout)

        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel)
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(4); self.table_widget.setHorizontalHeaderLabels(["组别", "单词/短语", "备注 (IPA)", "语言 (可选)"])
        self.table_widget.setToolTip("在此表格中编辑单词/词语。\n'组别'列可用鼠标滚轮快速调整数字。\n右键单击可进行行操作。")
        self.table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch); self.table_widget.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch); self.table_widget.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_widget.verticalHeader().setVisible(True); self.table_widget.setAlternatingRowColors(True)

        table_btn_layout = QHBoxLayout()
        self.undo_btn = QPushButton("撤销"); self.redo_btn = QPushButton("重做")
        self.auto_detect_lang_btn = QPushButton("自动检测语言")
        self.add_row_btn = QPushButton("添加行"); self.remove_row_btn = QPushButton("移除选中行")
        table_btn_layout.addWidget(self.undo_btn); table_btn_layout.addWidget(self.redo_btn)
        table_btn_layout.addStretch()
        table_btn_layout.addWidget(self.auto_detect_lang_btn)
        table_btn_layout.addStretch()
        table_btn_layout.addWidget(self.add_row_btn); table_btn_layout.addWidget(self.remove_row_btn)
        
        right_layout.addWidget(self.table_widget); right_layout.addLayout(table_btn_layout)
        main_layout.addWidget(self.left_panel); main_layout.addWidget(right_panel, 1)

    # --- [vNext 新增] 外部调用API ---
    def load_file_from_path(self, filepath):
        """公共API: 从外部（如文件管理器）加载一个指定路径的词表文件。"""
        # 查找文件列表中的对应项
        filename = os.path.basename(filepath)
        items = self.file_list_widget.findItems(filename, Qt.MatchExactly)
        if items:
            # 找到了，模拟用户选择
            self.file_list_widget.setCurrentItem(items[0])
        else:
            # 如果文件不在列表中，尝试刷新列表并再次查找
            self.refresh_file_list()
            items = self.file_list_widget.findItems(filename, Qt.MatchExactly)
            if items:
                self.file_list_widget.setCurrentItem(items[0])
            else:
                QMessageBox.warning(self, "文件未找到", f"文件 '{filename}' 不在当前列表中，或无法加载。")

    def update_icons(self):
        self.new_btn.setIcon(self.icon_manager.get_icon("new_file")); self.save_btn.setIcon(self.icon_manager.get_icon("save")); self.save_as_btn.setIcon(self.icon_manager.get_icon("save_as"))
        self.add_row_btn.setIcon(self.icon_manager.get_icon("add_row")); self.remove_row_btn.setIcon(self.icon_manager.get_icon("remove_row"))
        self.undo_btn.setIcon(self.icon_manager.get_icon("undo")); self.redo_btn.setIcon(self.icon_manager.get_icon("redo"))
        self.auto_detect_lang_btn.setIcon(self.icon_manager.get_icon("auto_detect"))
        self.undo_action.setIcon(self.icon_manager.get_icon("undo")); self.redo_action.setIcon(self.icon_manager.get_icon("redo"))

    def apply_layout_settings(self):
        config = self.parent_window.config; ui_settings = config.get("ui_settings", {}); width = ui_settings.get("editor_sidebar_width", 280); self.left_panel.setFixedWidth(width); col_widths = ui_settings.get("wordlist_editor_col_widths", [80, -1, -1, -1]);
        if 0 < self.table_widget.columnCount() and col_widths[0] != -1: self.table_widget.setColumnWidth(0, col_widths[0])

    def on_column_resized(self, logical_index, old_size, new_size):
        config = self.parent_window.config; current_widths = config.setdefault("ui_settings", {}).get("wordlist_editor_col_widths", [80, -1, -1, -1])
        if logical_index == 0: current_widths[0] = new_size
        config.setdefault("ui_settings", {})["wordlist_editor_col_widths"] = current_widths
        try:
            settings_file_path = os.path.join(get_base_path_for_module(), "config", "settings.json");
            with open(settings_file_path, 'w', encoding='utf-8') as f: json.dump(config, f, indent=4)
        except Exception as e: print(f"保存列宽设置失败: {e}")

    def refresh_file_list(self):
        if hasattr(self, 'parent_window'): self.apply_layout_settings()
        current_selection = self.file_list_widget.currentItem().text() if self.file_list_widget.currentItem() else ""
        self.file_list_widget.clear();
        if os.path.exists(self.WORD_LIST_DIR):
            files = sorted([f for f in os.listdir(self.WORD_LIST_DIR) if f.endswith('.json')]); self.file_list_widget.addItems(files)
            for i in range(len(files)):
                if files[i] == current_selection: self.file_list_widget.setCurrentRow(i); break

    def setup_connections_and_shortcuts(self):
        self.file_list_widget.currentItemChanged.connect(self.on_file_selected)
        # [新增] 连接新信号
        self.file_list_widget.itemDoubleClicked.connect(self.on_file_double_clicked)
        self.file_list_widget.customContextMenuRequested.connect(self.show_file_context_menu)
        
        self.new_btn.clicked.connect(self.new_wordlist); self.save_btn.clicked.connect(self.save_wordlist); self.save_as_btn.clicked.connect(self.save_wordlist_as)
        self.add_row_btn.clicked.connect(lambda: self.add_row()); self.remove_row_btn.clicked.connect(self.remove_row)
        self.table_widget.itemPressed.connect(self.on_item_pressed); self.table_widget.itemChanged.connect(self.on_item_changed_for_undo)
        self.table_widget.setContextMenuPolicy(Qt.CustomContextMenu); self.table_widget.customContextMenuRequested.connect(self.show_context_menu)
        self.undo_stack.cleanChanged.connect(lambda is_clean: self.save_btn.setEnabled(not is_clean))
        self.table_widget.viewport().installEventFilter(self)
        self.undo_action = self.undo_stack.createUndoAction(self, "撤销"); self.undo_action.setShortcut(QKeySequence.Undo); self.redo_action = self.undo_stack.createRedoAction(self, "重做"); self.redo_action.setShortcut(QKeySequence.Redo)
        self.addAction(self.undo_action); self.addAction(self.redo_action)
        self.undo_btn.clicked.connect(self.undo_action.trigger); self.redo_btn.clicked.connect(self.redo_action.trigger)
        self.auto_detect_lang_btn.clicked.connect(self.auto_detect_languages)
        self.undo_stack.canUndoChanged.connect(self.undo_btn.setEnabled); self.undo_stack.canRedoChanged.connect(self.redo_btn.setEnabled)
        self.undo_btn.setEnabled(False); self.redo_btn.setEnabled(False)
        QShortcut(QKeySequence.Save, self, self.save_wordlist); QShortcut(QKeySequence("Ctrl+Shift+S"), self, self.save_wordlist_as); QShortcut(QKeySequence.New, self, self.new_wordlist); QShortcut(QKeySequence.Copy, self, self.copy_selection)
        QShortcut(QKeySequence.Cut, self, self.cut_selection); QShortcut(QKeySequence.Paste, self, self.paste_selection); QShortcut(QKeySequence("Ctrl+D"), self, self.duplicate_rows); QShortcut(QKeySequence(Qt.ALT | Qt.Key_Up), self, lambda: self.move_rows(-1)); QShortcut(QKeySequence(Qt.ALT | Qt.Key_Down), self, lambda: self.move_rows(1))
        QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Minus), self, self.remove_row)
        self.table_widget.horizontalHeader().sectionResized.connect(self.on_column_resized)


    def auto_detect_languages(self):
        detected_count = 0
        self.undo_stack.beginMacro("自动检测语言")
        gtts_settings = self.parent_window.config.get("gtts_settings", {})
        default_lang = gtts_settings.get("default_lang", "en-us")
        
        for row in range(self.table_widget.rowCount()):
            word_item = self.table_widget.item(row, 1)    # "单词/短语" 在第1列
            note_item = self.table_widget.item(row, 2)    # "备注 (IPA)" 在第2列
            lang_combo = self.table_widget.cellWidget(row, 3)

            if word_item and word_item.text().strip() and lang_combo:
                current_lang = lang_combo.currentData()
                
                # 只对语言设置为“自动检测”的行进行操作
                if current_lang == "":
                    text = word_item.text()
                    # =================== [核心修改] ===================
                    # 获取备注文本，如果备注单元格不存在则为空字符串
                    note = note_item.text() if note_item else ""
                    # 调用新的、需要两个参数的检测函数
                    detected_lang = self.detect_language_func(text, note) or default_lang
                    # ================================================

                    if detected_lang != current_lang:
                        cmd = WordlistChangeLanguageCommand(self, row, current_lang, detected_lang, "自动填充语言")
                        self.undo_stack.push(cmd)
                        detected_count += 1
                        
        self.undo_stack.endMacro()
        QMessageBox.information(self, "检测完成", f"成功检测并填充了 {detected_count} 个词条的语言。")

    # --- [新增] 文件列表的上下文菜单和操作 ---
    def on_file_double_clicked(self, item):
        self._show_in_explorer(item)

    def show_file_context_menu(self, position):
        item = self.file_list_widget.itemAt(position)
        if not item: return

        menu = QMenu(self.file_list_widget)
        show_action = menu.addAction(self.icon_manager.get_icon("open_folder"), "在文件浏览器中显示")
        # --- [新增] 分割器集成 ---
        # 检查是否有分割器插件的钩子
        if hasattr(self, 'tts_splitter_plugin_active'):
            menu.addSeparator()
            splitter_action = menu.addAction(self.icon_manager.get_icon("cut"), "发送到批量分割器")
            splitter_action.triggered.connect(lambda: self.send_to_splitter(item))

        menu.addSeparator()
        duplicate_action = menu.addAction(self.icon_manager.get_icon("copy"), "创建副本")
        delete_action = menu.addAction(self.icon_manager.get_icon("delete"), "删除")
        
        action = menu.exec_(self.file_list_widget.mapToGlobal(position))

        if action == show_action:
            self._show_in_explorer(item)
        elif action == duplicate_action:
            self._duplicate_file(item)
        elif action == delete_action:
            self._delete_file(item)

    # [新增] 发送到分割器的辅助方法
    def send_to_splitter(self, item):
        if not item: return
        
        # 获取插件实例
        splitter_plugin = getattr(self, 'tts_splitter_plugin_active', None)
        if splitter_plugin:
            wordlist_path = os.path.join(self.WORD_LIST_DIR, item.text())
            # 通过 execute 方法传递词表路径
            splitter_plugin.execute(wordlist_path=wordlist_path)

    def _show_in_explorer(self, item):
        if not item: return
        filepath = os.path.join(self.WORD_LIST_DIR, item.text())
        if not os.path.exists(filepath):
            QMessageBox.warning(self, "文件不存在", "该文件可能已被移动或删除。")
            self.refresh_file_list()
            return
        
        try:
            if sys.platform == 'win32':
                subprocess.run(['explorer', '/select,', os.path.normpath(filepath)])
            elif sys.platform == 'darwin':
                subprocess.check_call(['open', '-R', filepath])
            else: # Linux
                subprocess.check_call(['xdg-open', os.path.dirname(filepath)])
        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"无法打开文件所在位置: {e}")

    def _duplicate_file(self, item):
        if not item: return
        src_path = os.path.join(self.WORD_LIST_DIR, item.text())
        if not os.path.exists(src_path):
            QMessageBox.warning(self, "文件不存在", "无法创建副本，源文件可能已被移动或删除。"); self.refresh_file_list(); return

        base, ext = os.path.splitext(item.text())
        dest_path = os.path.join(self.WORD_LIST_DIR, f"{base}_copy{ext}")
        i = 1
        while os.path.exists(dest_path):
            dest_path = os.path.join(self.WORD_LIST_DIR, f"{base}_copy_{i}{ext}")
            i += 1
        
        try:
            shutil.copy2(src_path, dest_path)
            self.refresh_file_list()
        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"无法创建副本: {e}")

    def _delete_file(self, item):
        if not item: return
        filepath = os.path.join(self.WORD_LIST_DIR, item.text())
        
        reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除文件 '{item.text()}' 吗？\n此操作不可撤销。",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            try:
                os.remove(filepath)
                # 如果删除的是当前打开的文件，则重置编辑器
                if filepath == self.current_wordlist_path:
                    self.current_wordlist_path = None
                    self.table_widget.setRowCount(0)
                    self.undo_stack.clear()
                self.refresh_file_list()
            except Exception as e:
                QMessageBox.critical(self, "删除失败", f"无法删除文件: {e}")
    # --- 结束新增 ---

    # ... (其他方法保持不变, 仅修改 load_file_to_table) ...
    def on_file_selected(self, current, previous):
        if not self.undo_stack.isClean() and previous:
            reply = QMessageBox.question(self, "未保存的更改", "您有未保存的更改，确定要切换吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No: self.file_list_widget.currentItemChanged.disconnect(self.on_file_selected); self.file_list_widget.setCurrentItem(previous); self.file_list_widget.currentItemChanged.connect(self.on_file_selected); return
        if current:
            self.current_wordlist_path = os.path.join(self.WORD_LIST_DIR, current.text())
            self.load_file_to_table()
        else:
            self.current_wordlist_path = None
            self.table_widget.setRowCount(0)
            self.undo_stack.clear()

    def load_file_to_table(self):
        # [修复] 增加文件存在性检查
        if not self.current_wordlist_path or not os.path.exists(self.current_wordlist_path):
            QMessageBox.information(self, "文件不存在", f"词表文件 '{os.path.basename(str(self.current_wordlist_path))}' 不存在，可能已被删除或移动。")
            self.current_wordlist_path = None
            self.table_widget.setRowCount(0)
            self.undo_stack.clear()
            self.refresh_file_list() # 刷新列表以移除不存在的文件
            return
            
        self.table_widget.blockSignals(True)
        self.table_widget.setRowCount(0)
        
        try:
            with open(self.current_wordlist_path, 'r', encoding='utf-8') as f: data = json.load(f)
            if "meta" not in data or "groups" not in data or not isinstance(data["groups"], list): raise ValueError("JSON文件格式无效，缺少 'meta' 或 'groups' 键。")
            row_index = 0
            for group_data in data["groups"]:
                group_id = group_data.get("id", ""); items = group_data.get("items", [])
                if not isinstance(items, list): continue
                for item_data in items:
                    text = item_data.get("text", ""); note = item_data.get("note", ""); lang = item_data.get("lang", "")
                    self.table_widget.insertRow(row_index); self.populate_row(row_index, [str(group_id), text, note, lang]); row_index += 1
            self.undo_stack.clear()
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            QMessageBox.critical(self, "加载失败", f"无法解析JSON词表文件 '{os.path.basename(self.current_wordlist_path)}':\n{e}")
        finally:
            self.table_widget.blockSignals(False)

    def populate_row(self, row, data):
        self.table_widget.setItem(row, 0, QTableWidgetItem(data[0])); self.table_widget.setItem(row, 1, QTableWidgetItem(data[1])); self.table_widget.setItem(row, 2, QTableWidgetItem(data[2]))
        combo = QComboBox(self.table_widget); combo.setIconSize(QSize(24, 18))
        for display_name, lang_code in LANGUAGE_MAP.items():
            icon_path = os.path.join(self.flags_path, f"{FLAG_CODE_MAP.get(lang_code, 'auto')}.png"); combo.addItem(QIcon(icon_path) if os.path.exists(icon_path) else QIcon(), display_name, lang_code)
        index = combo.findData(data[3]);
        if index != -1: combo.setCurrentIndex(index)
        combo.view().pressed.connect(lambda _, r=row: self.on_language_combo_pressed(r)); combo.activated.connect(lambda idx, r=row: self.on_language_manually_changed(idx, r)); self.table_widget.setCellWidget(row, 3, combo)

    def new_wordlist(self):
        if not self.undo_stack.isClean():
            reply = QMessageBox.question(self, "未保存的更改", "您有未保存的更改，确定要新建吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No: return
        self.table_widget.setRowCount(0); self.current_wordlist_path = None; self.file_list_widget.setCurrentItem(None); self.undo_stack.clear(); self.add_row()

    def save_wordlist(self):
        if self.current_wordlist_path: self._write_to_file(self.current_wordlist_path)
        else: self.save_wordlist_as()

    def save_wordlist_as(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "另存为单词表", self.WORD_LIST_DIR, "JSON 文件 (*.json)")
        if filepath:
            if not filepath.lower().endswith('.json'): filepath += '.json'
            self._write_to_file(filepath); self.current_wordlist_path = filepath; self.refresh_file_list()
            for i in range(self.file_list_widget.count()):
                if self.file_list_widget.item(i).text() == os.path.basename(filepath): self.file_list_widget.setCurrentRow(i); break

    def _write_to_file(self, filepath):
        groups_map = {}
        for row in range(self.table_widget.rowCount()):
            try:
                group_item = self.table_widget.item(row, 0); word_item = self.table_widget.item(row, 1)
                if not group_item or not word_item or not group_item.text().isdigit() or not word_item.text().strip(): continue
                group_id = int(group_item.text()); text = word_item.text().strip()
                note_item = self.table_widget.item(row, 2); note = note_item.text().strip() if note_item else ""
                lang_combo = self.table_widget.cellWidget(row, 3); lang = lang_combo.currentData() if lang_combo else ""
                if group_id not in groups_map: groups_map[group_id] = []
                groups_map[group_id].append({"text": text, "note": note, "lang": lang})
            except (ValueError, AttributeError): continue
        final_data_structure = {"meta": {"format": "standard_wordlist", "version": "1.0", "author": "PhonAcq Assistant", "save_date": datetime.now().isoformat()}, "groups": []}
        for group_id, items in sorted(groups_map.items()): final_data_structure["groups"].append({"id": group_id, "items": items})
        try:
            with open(filepath, 'w', encoding='utf-8') as f: json.dump(final_data_structure, f, indent=4, ensure_ascii=False)
            self.undo_stack.setClean(); QMessageBox.information(self, "成功", f"单词表已成功保存至:\n{filepath}")
        except Exception as e: QMessageBox.critical(self, "保存失败", f"无法保存文件:\n{e}")

    # ... (eventFilter, keyPressEvent, on_item_pressed, etc. remain unchanged) ...
    def eventFilter(self, source, event):
        if source is self.table_widget.viewport() and event.type() == QEvent.Wheel and self.table_widget.itemAt(event.pos()) and self.table_widget.itemAt(event.pos()).column() == 0:
            item = self.table_widget.itemAt(event.pos());
            try:
                old_value_str = item.text();
                if not old_value_str.isdigit(): return super().eventFilter(source, event)
                new_value = int(old_value_str) + (1 if event.angleDelta().y() > 0 else -1);
                if new_value < 1: new_value = 1
                new_value_str = str(new_value);
                if old_value_str != new_value_str: cmd = WordlistChangeCellCommand(self, item.row(), 0, old_value_str, new_value_str, "修改组别"); self.undo_stack.push(cmd)
                return True
            except (ValueError, TypeError): pass
        return super().eventFilter(source, event)
    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace) and self.table_widget.selectedItems(): self.clear_selection_contents(); event.accept()
        else: super().keyPressEvent(event)
    def on_item_pressed(self, item):
        if item: self.old_text_before_edit = item.text()
    def on_item_changed_for_undo(self, item):
        if self.old_text_before_edit is not None and self.old_text_before_edit != item.text():
            cmd = WordlistChangeCellCommand(self, item.row(), item.column(), self.old_text_before_edit, item.text(), "修改单元格"); self.undo_stack.push(cmd)
        self.old_text_before_edit = None
    def on_language_combo_pressed(self, row):
        combo = self.table_widget.cellWidget(row, 3);
        if isinstance(combo, QComboBox): self.old_lang_before_edit = combo.currentData()
    def on_language_manually_changed(self, index, row):
        combo = self.table_widget.cellWidget(row, 3);
        if not isinstance(combo, QComboBox): return
        new_lang_code = combo.itemData(index);
        if self.old_lang_before_edit is not None and self.old_lang_before_edit != new_lang_code:
            cmd = WordlistChangeLanguageCommand(self, row, self.old_lang_before_edit, new_lang_code, "改变语言"); self.undo_stack.push(cmd)
        self.old_lang_before_edit = None
    def show_context_menu(self, position):
        menu = QMenu(self.file_list_widget); selection = self.table_widget.selectedRanges()
        cut_action = menu.addAction(self.icon_manager.get_icon("cut"), "剪切 (Ctrl+X)"); cut_action.setToolTip("剪切选中的单元格内容。"); copy_action = menu.addAction(self.icon_manager.get_icon("copy"), "复制 (Ctrl+C)"); copy_action.setToolTip("复制选中的单元格内容。"); paste_action = menu.addAction(self.icon_manager.get_icon("paste"), "粘贴 (Ctrl+V)"); paste_action.setToolTip("将剪贴板内容粘贴到当前位置。"); menu.addSeparator()
        duplicate_action = menu.addAction(self.icon_manager.get_icon("duplicate_row"), "创建副本/重制行 (Ctrl+D)"); duplicate_action.setToolTip("复制选中行并插入到下方。"); menu.addSeparator()
        add_row_action = menu.addAction(self.icon_manager.get_icon("add_row"), "在下方插入新行"); add_row_action.setToolTip("在当前选中行下方插入一个新行。"); remove_row_action = menu.addAction(self.icon_manager.get_icon("remove_row"), "删除选中行"); remove_row_action.setToolTip("删除表格中所有选中的行。"); menu.addSeparator()
        clear_contents_action = menu.addAction(self.icon_manager.get_icon("clear_contents"), "清空内容 (Delete)"); clear_contents_action.setToolTip("清空选中单元格中的内容。"); menu.addSeparator(); move_up_action = menu.addAction(self.icon_manager.get_icon("move_up"), "上移选中行 (Alt+Up)"); move_up_action.setToolTip("将选中的行向上移动一个位置。")
        move_down_action = menu.addAction(self.icon_manager.get_icon("move_down"), "下移选中行 (Alt+Down)"); move_down_action.setToolTip("将选中的行向下移动一个位置。");
        if not selection: cut_action.setEnabled(False); copy_action.setEnabled(False); clear_contents_action.setEnabled(False)
        action = menu.exec_(self.table_widget.mapToGlobal(position));
        if action == cut_action: self.cut_selection()
        elif action == copy_action: self.copy_selection()
        elif action == paste_action: self.paste_selection()
        elif action == duplicate_action: self.duplicate_rows()
        elif action == add_row_action: current_row = self.table_widget.currentRow(); self.add_row(current_row + 1 if current_row != -1 else self.table_widget.rowCount())
        elif action == remove_row_action: self.remove_row()
        elif action == clear_contents_action: self.clear_selection_contents()
        elif action == move_up_action: self.move_rows(-1)
        elif action == move_down_action: self.move_rows(1)
    def get_selected_rows_indices(self): return sorted(list(set(index.row() for index in self.table_widget.selectedIndexes())))
    def _get_rows_data(self, row_indices):
        data = [];
        for row in row_indices:
            row_data = [self.table_widget.item(row, col).text() if self.table_widget.item(row, col) else "" for col in range(3)]
            lang_combo = self.table_widget.cellWidget(row, 3); row_data.append(lang_combo.currentData() if lang_combo else ""); data.append(row_data)
        return data
    def clear_selection_contents(self):
        selected_items = self.table_widget.selectedItems();
        if not selected_items: return
        self.undo_stack.beginMacro("清空内容")
        for item in selected_items:
            if item.column() < 3 and item.text(): cmd = WordlistChangeCellCommand(self, item.row(), item.column(), item.text(), "", "清空单元格"); self.undo_stack.push(cmd)
        self.undo_stack.endMacro()
    def cut_selection(self): self.copy_selection(); self.clear_selection_contents()
    def copy_selection(self):
        selection = self.table_widget.selectedRanges();
        if not selection: return
        rows = sorted(list(set(index.row() for index in self.table_widget.selectedIndexes()))); cols = sorted(list(set(index.column() for index in self.table_widget.selectedIndexes())))
        table_str = "\n".join(["\t".join([self.table_widget.cellWidget(r, c).currentData() if c == 3 and self.table_widget.cellWidget(r, c) else (self.table_widget.item(r, c).text() if self.table_widget.item(r, c) else "") for c in cols]) for r in rows]); QApplication.clipboard().setText(table_str)
    def paste_selection(self):
        selection = self.table_widget.selectedRanges();
        if not selection: return
        start_row, start_col = selection[0].topRow(), selection[0].leftColumn(); text = QApplication.clipboard().text(); rows = text.strip('\n').split('\n')
        self.undo_stack.beginMacro("粘贴")
        for i, row in enumerate(rows):
            cells = row.split('\t')
            for j, cell_text in enumerate(cells):
                target_row, target_col = start_row + i, start_col + j
                if target_row < self.table_widget.rowCount() and target_col < self.table_widget.columnCount():
                    if target_col == 3:
                        combo = self.table_widget.cellWidget(target_row, target_col)
                        if combo and combo.currentData() != cell_text: cmd = WordlistChangeLanguageCommand(self, target_row, combo.currentData(), cell_text, "粘贴语言"); self.undo_stack.push(cmd)
                    else: item = self.table_widget.item(target_row, target_col); old_text = item.text() if item else "";
                    if old_text != cell_text: cmd = WordlistChangeCellCommand(self, target_row, target_col, old_text, cell_text, "粘贴单元格"); self.undo_stack.push(cmd)
        self.undo_stack.endMacro()
    def duplicate_rows(self):
        rows_to_duplicate = self.get_selected_rows_indices()
        if not rows_to_duplicate:
            current_row = self.table_widget.currentRow()
            if current_row == -1: return
            else: rows_to_duplicate = [current_row]
        rows_data = self._get_rows_data(rows_to_duplicate)
        insert_at = rows_to_duplicate[-1] + 1
        cmd = WordlistRowOperationCommand(self, insert_at, rows_data, 'add', description="创建副本/重制行")
        self.undo_stack.push(cmd)
    def move_rows(self, offset):
        selected_rows = self.get_selected_rows_indices();
        if not selected_rows: return
        if (offset == -1 and selected_rows[0] == 0) or (offset == 1 and selected_rows[-1] == self.table_widget.rowCount() - 1): return
        start_row = selected_rows[0]; rows_data = self._get_rows_data(selected_rows); cmd = WordlistRowOperationCommand(self, start_row, rows_data, 'move', offset, "移动行"); self.undo_stack.push(cmd)
        self.table_widget.clearSelection(); new_start_row = start_row + offset
        for i in range(len(selected_rows)): self.table_widget.selectRow(new_start_row + i)
    def add_row(self, at_row=None):
        if at_row is None: at_row = self.table_widget.rowCount()
        last_group = "1"
        if at_row > 0:
            last_item = self.table_widget.item(at_row - 1, 0)
            if last_item and last_item.text().isdigit(): last_group = last_item.text()
        cmd = WordlistRowOperationCommand(self, at_row, [[last_group, "", "", ""]], 'add', description="添加新行"); self.undo_stack.push(cmd); QApplication.processEvents()
        self.table_widget.scrollToItem(self.table_widget.item(at_row, 0), QTableWidget.ScrollHint.EnsureVisible); self.table_widget.selectRow(at_row)
    def remove_row(self):
        selected_rows = self.get_selected_rows_indices()
        if not selected_rows: QMessageBox.warning(self, "提示", "请先选择要移除的整行。"); return
        rows_data = self._get_rows_data(selected_rows); start_row = selected_rows[0]; cmd = WordlistRowOperationCommand(self, start_row, rows_data, 'remove', description="移除选中行"); self.undo_stack.push(cmd)