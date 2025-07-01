# --- START OF FILE wordlist_editor_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "词表编辑器"
MODULE_DESCRIPTION = "在程序内直接创建、编辑和保存单词/词语列表。"
# ---

import os
import sys
import importlib.util
from datetime import datetime
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QFileDialog, QMessageBox, QTableWidget,
                             QTableWidgetItem, QHeaderView, QComboBox, QShortcut,
                             QUndoStack, QUndoCommand, QApplication, QMenu)
from PyQt5.QtCore import Qt, QSize, QEvent
from PyQt5.QtGui import QKeySequence, QIcon

# 数据定义
LANGUAGE_MAP = {
    "自动 (默认)": "", "美式英语": "en-us", "英式英语": "en-uk", "中文普通话": "zh-cn",
    "日语": "ja", "法语": "fr-fr", "德语": "de-de", "西班牙语": "es-es",
    "俄语": "ru", "韩语": "ko"
}
FLAG_CODE_MAP = {
    "": "auto", "en-us": "us", "en-uk": "gb", "zh-cn": "cn", "ja": "jp",
    "fr-fr": "fr", "de-de": "de", "es-es": "es", "ru": "ru", "ko": "kr"
}

def get_base_path_for_module():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def create_page(parent_window, WORD_LIST_DIR):
    return WordlistEditorPage(parent_window, WORD_LIST_DIR)

# Undo/Redo 命令类 (省略，保持不变)
class WordlistChangeCellCommand(QUndoCommand):
    def __init__(self, editor, row, col, old_text, new_text, description):
        super().__init__(description)
        self.editor = editor
        self.table = editor.table_widget
        self.row, self.col = row, col
        self.old_text, self.new_text = old_text, new_text
    def redo(self):
        item = self.table.item(self.row, self.col)
        if not item: item = QTableWidgetItem(); self.table.setItem(self.row, self.col, item)
        item.setText(self.new_text)
    def undo(self):
        item = self.table.item(self.row, self.col)
        if not item: item = QTableWidgetItem(); self.table.setItem(self.row, self.col, item)
        item.setText(self.old_text)

class WordlistChangeLanguageCommand(QUndoCommand):
    def __init__(self, editor, row, old_lang_code, new_lang_code, description):
        super().__init__(description)
        self.editor = editor
        self.table = editor.table_widget
        self.row = row
        self.old_lang, self.new_lang = old_lang_code, new_lang_code
    def _set_language(self, lang_code):
        widget = self.table.cellWidget(self.row, 3)
        if isinstance(widget, QComboBox):
            index = widget.findData(lang_code)
            if index != -1: widget.setCurrentIndex(index)
    def redo(self): self._set_language(self.new_lang)
    def undo(self): self._set_language(self.old_lang)

class WordlistRowOperationCommand(QUndoCommand):
    def __init__(self, editor, start_row, rows_data, operation_type, move_offset=0, description=""):
        super().__init__(description)
        self.editor = editor
        self.table = editor.table_widget
        self.start_row, self.rows_data, self.type, self.move_offset = start_row, rows_data, operation_type, move_offset
    def _insert_rows(self, at_row, data):
        for i, row_data in enumerate(data):
            self.table.insertRow(at_row + i)
            self.editor.populate_row(at_row + i, row_data)
    def _remove_rows(self, at_row, count):
        for _ in range(count): self.table.removeRow(at_row)
    def redo(self):
        self.table.blockSignals(True)
        if self.type == 'remove': self._remove_rows(self.start_row, len(self.rows_data))
        elif self.type == 'add': self._insert_rows(self.start_row, self.rows_data)
        elif self.type == 'move':
            self._remove_rows(self.start_row, len(self.rows_data)); self._insert_rows(self.start_row + self.move_offset, self.rows_data)
        self.table.blockSignals(False)
    def undo(self):
        self.table.blockSignals(True)
        if self.type == 'remove': self._insert_rows(self.start_row, self.rows_data)
        elif self.type == 'add': self._remove_rows(self.start_row, len(self.rows_data))
        elif self.type == 'move':
            self._remove_rows(self.start_row + self.move_offset, len(self.rows_data)); self._insert_rows(self.start_row, self.rows_data)
        self.table.blockSignals(False)


class WordlistEditorPage(QWidget):
    def __init__(self, parent_window, WORD_LIST_DIR):
        super().__init__()
        self.parent_window = parent_window
        self.WORD_LIST_DIR = WORD_LIST_DIR
        self.current_wordlist_path = None
        self.old_text_before_edit = None
        self.old_lang_before_edit = None
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)
        
        self.base_path = get_base_path_for_module()
        self.flags_path = os.path.join(self.base_path, 'assets', 'flags')

        self._init_ui()
        self.setup_connections_and_shortcuts()
        self.apply_layout_settings()
        self.refresh_file_list()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        self.left_panel = QWidget() # 保存为成员变量
        left_layout = QVBoxLayout(self.left_panel)
        # left_panel.setFixedWidth(250) # 移除硬编码

        self.file_list_widget = QListWidget()
        self.new_btn = QPushButton("新建单词表")
        file_btn_layout = QHBoxLayout(); self.save_btn = QPushButton("保存"); self.save_as_btn = QPushButton("另存为...")
        file_btn_layout.addWidget(self.save_btn); file_btn_layout.addWidget(self.save_as_btn)
        left_layout.addWidget(QLabel("单词表文件:")); left_layout.addWidget(self.file_list_widget); left_layout.addWidget(self.new_btn); left_layout.addLayout(file_btn_layout)

        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel)
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(4); self.table_widget.setHorizontalHeaderLabels(["组别", "单词/短语", "备注 (IPA)", "语言 (可选)"])
        self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_widget.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_widget.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

        table_btn_layout = QHBoxLayout(); self.add_row_btn = QPushButton("添加行"); self.remove_row_btn = QPushButton("移除选中行")
        table_btn_layout.addStretch(); table_btn_layout.addWidget(self.add_row_btn); table_btn_layout.addWidget(self.remove_row_btn)
        right_layout.addWidget(self.table_widget); right_layout.addLayout(table_btn_layout)
        
        main_layout.addWidget(self.left_panel)
        main_layout.addWidget(right_panel, 1)

    def apply_layout_settings(self):
        config = self.parent_window.config 
        ui_settings = config.get("ui_settings", {})
        width = ui_settings.get("editor_sidebar_width", 280)
        self.left_panel.setFixedWidth(width)
        
    def refresh_file_list(self):
        if hasattr(self, 'parent_window'):
            self.apply_layout_settings()
        current_selection = self.file_list_widget.currentItem().text() if self.file_list_widget.currentItem() else ""
        self.file_list_widget.clear()
        if os.path.exists(self.WORD_LIST_DIR):
            files = sorted([f for f in os.listdir(self.WORD_LIST_DIR) if f.endswith('.py')])
            self.file_list_widget.addItems(files)
            for i in range(len(files)):
                if files[i] == current_selection: self.file_list_widget.setCurrentRow(i); break

    # ... (其余所有方法保持不变) ...
    def setup_connections_and_shortcuts(self):
        self.file_list_widget.currentItemChanged.connect(self.on_file_selected)
        self.new_btn.clicked.connect(self.new_wordlist); self.save_btn.clicked.connect(self.save_wordlist); self.save_as_btn.clicked.connect(self.save_wordlist_as)
        self.add_row_btn.clicked.connect(lambda: self.add_row()); self.remove_row_btn.clicked.connect(self.remove_row)
        self.table_widget.itemPressed.connect(self.on_item_pressed); self.table_widget.itemChanged.connect(self.on_item_changed_for_undo)
        self.table_widget.setContextMenuPolicy(Qt.CustomContextMenu); self.table_widget.customContextMenuRequested.connect(self.show_context_menu)
        self.undo_stack.cleanChanged.connect(lambda is_clean: self.save_btn.setEnabled(not is_clean))
        self.table_widget.viewport().installEventFilter(self)
        self.undo_action = self.undo_stack.createUndoAction(self, "撤销"); self.undo_action.setShortcut(QKeySequence.Undo)
        self.redo_action = self.undo_stack.createRedoAction(self, "重做"); self.redo_action.setShortcut(QKeySequence.Redo)
        self.addAction(self.undo_action); self.addAction(self.redo_action)
        QShortcut(QKeySequence.Save, self, self.save_wordlist); QShortcut(QKeySequence("Ctrl+Shift+S"), self, self.save_wordlist_as)
        QShortcut(QKeySequence.New, self, self.new_wordlist); QShortcut(QKeySequence.Copy, self, self.copy_selection)
        QShortcut(QKeySequence.Cut, self, self.cut_selection); QShortcut(QKeySequence.Paste, self, self.paste_selection)
        QShortcut(QKeySequence("Ctrl+D"), self, self.duplicate_rows); QShortcut(QKeySequence(Qt.ALT | Qt.Key_Up), self, lambda: self.move_rows(-1))
        QShortcut(QKeySequence(Qt.ALT | Qt.Key_Down), self, lambda: self.move_rows(1)); QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Minus), self, self.remove_row)
    def eventFilter(self, source, event):
        if source is self.table_widget.viewport() and event.type() == QEvent.Wheel and self.table_widget.itemAt(event.pos()) and self.table_widget.itemAt(event.pos()).column() == 0:
            item = self.table_widget.itemAt(event.pos())
            try:
                old_value_str = item.text()
                if not old_value_str.isdigit(): return super().eventFilter(source, event)
                new_value = int(old_value_str) + (1 if event.angleDelta().y() > 0 else -1)
                if new_value < 1: new_value = 1
                new_value_str = str(new_value)
                if old_value_str != new_value_str:
                    cmd = WordlistChangeCellCommand(self, item.row(), 0, old_value_str, new_value_str, "修改组别")
                    self.undo_stack.push(cmd)
                return True
            except (ValueError, TypeError): pass
        return super().eventFilter(source, event)
    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace) and self.table_widget.selectedItems():
             self.clear_selection_contents(); event.accept()
        else: super().keyPressEvent(event)
    def on_item_pressed(self, item):
        if item: self.old_text_before_edit = item.text()
    def on_item_changed_for_undo(self, item):
        if self.old_text_before_edit is not None and self.old_text_before_edit != item.text():
            cmd = WordlistChangeCellCommand(self, item.row(), item.column(), self.old_text_before_edit, item.text(), "修改单元格")
            self.undo_stack.push(cmd)
        self.old_text_before_edit = None
    def on_language_combo_pressed(self, row):
        combo = self.table_widget.cellWidget(row, 3)
        if isinstance(combo, QComboBox): self.old_lang_before_edit = combo.currentData()
    def on_language_manually_changed(self, index, row):
        combo = self.table_widget.cellWidget(row, 3)
        if not isinstance(combo, QComboBox): return
        new_lang_code = combo.itemData(index)
        if self.old_lang_before_edit is not None and self.old_lang_before_edit != new_lang_code:
            cmd = WordlistChangeLanguageCommand(self, row, self.old_lang_before_edit, new_lang_code, "改变语言")
            self.undo_stack.push(cmd)
        self.old_lang_before_edit = None
    def show_context_menu(self, position):
        menu = QMenu(); selection = self.table_widget.selectedRanges()
        cut_action = menu.addAction("剪切 (Ctrl+X)"); copy_action = menu.addAction("复制 (Ctrl+C)"); paste_action = menu.addAction("粘贴 (Ctrl+V)")
        menu.addSeparator(); duplicate_action = menu.addAction("创建副本/重制行 (Ctrl+D)"); menu.addSeparator()
        add_row_action = menu.addAction("在下方插入新行"); remove_row_action = menu.addAction("删除选中行")
        menu.addSeparator(); clear_contents_action = menu.addAction("清空内容 (Delete)")
        if not selection: cut_action.setEnabled(False); copy_action.setEnabled(False); clear_contents_action.setEnabled(False)
        action = menu.exec_(self.table_widget.mapToGlobal(position))
        if action == cut_action: self.cut_selection()
        elif action == copy_action: self.copy_selection()
        elif action == paste_action: self.paste_selection()
        elif action == duplicate_action: self.duplicate_rows()
        elif action == add_row_action:
            current_row = self.table_widget.currentRow(); self.add_row(current_row + 1 if current_row != -1 else self.table_widget.rowCount())
        elif action == remove_row_action: self.remove_row()
        elif action == clear_contents_action: self.clear_selection_contents()
    def get_selected_rows_indices(self): return sorted(list(set(index.row() for index in self.table_widget.selectedIndexes())))
    def _get_rows_data(self, row_indices):
        data = []
        for row in row_indices:
            row_data = [self.table_widget.item(row, col).text() if self.table_widget.item(row, col) else "" for col in range(3)]
            lang_combo = self.table_widget.cellWidget(row, 3); row_data.append(lang_combo.currentData() if lang_combo else "")
            data.append(row_data)
        return data
    def clear_selection_contents(self):
        selected_items = self.table_widget.selectedItems()
        if not selected_items: return
        self.undo_stack.beginMacro("清空内容")
        for item in selected_items:
            if item.column() < 3 and item.text():
                cmd = WordlistChangeCellCommand(self, item.row(), item.column(), item.text(), "", "清空单元格"); self.undo_stack.push(cmd)
        self.undo_stack.endMacro()
    def cut_selection(self): self.copy_selection(); self.clear_selection_contents()
    def copy_selection(self):
        selection = self.table_widget.selectedRanges();
        if not selection: return
        rows = sorted(list(set(index.row() for index in self.table_widget.selectedIndexes()))); cols = sorted(list(set(index.column() for index in self.table_widget.selectedIndexes())))
        table_str = "\n".join(["\t".join([self.table_widget.cellWidget(r, c).currentData() if c == 3 and self.table_widget.cellWidget(r, c) else (self.table_widget.item(r, c).text() if self.table_widget.item(r, c) else "") for c in cols]) for r in rows])
        QApplication.clipboard().setText(table_str)
    def paste_selection(self):
        selection = self.table_widget.selectedRanges();
        if not selection: return
        start_row, start_col = selection[0].topRow(), selection[0].leftColumn()
        text = QApplication.clipboard().text(); rows = text.strip('\n').split('\n')
        self.undo_stack.beginMacro("粘贴")
        for i, row in enumerate(rows):
            cells = row.split('\t')
            for j, cell_text in enumerate(cells):
                target_row, target_col = start_row + i, start_col + j
                if target_row < self.table_widget.rowCount() and target_col < self.table_widget.columnCount():
                    if target_col == 3:
                        combo = self.table_widget.cellWidget(target_row, target_col)
                        if combo and combo.currentData() != cell_text:
                            cmd = WordlistChangeLanguageCommand(self, target_row, combo.currentData(), cell_text, "粘贴语言"); self.undo_stack.push(cmd)
                    else:
                        item = self.table_widget.item(target_row, target_col); old_text = item.text() if item else ""
                        if old_text != cell_text:
                            cmd = WordlistChangeCellCommand(self, target_row, target_col, old_text, cell_text, "粘贴单元格"); self.undo_stack.push(cmd)
        self.undo_stack.endMacro()
    def duplicate_rows(self):
        rows_to_duplicate = self.get_selected_rows_indices()
        if not rows_to_duplicate:
            current_row = self.table_widget.currentRow()
            if current_row == -1: return
            rows_to_duplicate = [current_row]
        rows_data = self._get_rows_data(rows_to_duplicate); insert_at = rows_to_duplicate[-1] + 1
        cmd = WordlistRowOperationCommand(self, insert_at, rows_data, 'add', description="创建副本/重制行"); self.undo_stack.push(cmd)
    def move_rows(self, offset):
        selected_rows = self.get_selected_rows_indices();
        if not selected_rows: return
        if (offset == -1 and selected_rows[0] == 0) or (offset == 1 and selected_rows[-1] == self.table_widget.rowCount() - 1): return
        start_row = selected_rows[0]; rows_data = self._get_rows_data(selected_rows)
        cmd = WordlistRowOperationCommand(self, start_row, rows_data, 'move', offset, "移动行"); self.undo_stack.push(cmd)
        self.table_widget.clearSelection()
        new_start_row = start_row + offset
        for i in range(len(selected_rows)): self.table_widget.selectRow(new_start_row + i)
    def add_row(self, at_row=None):
        if at_row is None: at_row = self.table_widget.rowCount()
        last_group = "1"
        if at_row > 0:
            last_item = self.table_widget.item(at_row - 1, 0)
            if last_item and last_item.text().isdigit(): last_group = last_item.text()
        cmd = WordlistRowOperationCommand(self, at_row, [[last_group, "", "", ""]], 'add', description="添加新行"); self.undo_stack.push(cmd)
        QApplication.processEvents() # 确保item被创建
        self.table_widget.scrollToItem(self.table_widget.item(at_row, 0), QTableWidget.ScrollHint.EnsureVisible)
        self.table_widget.selectRow(at_row)
    def remove_row(self):
        selected_rows = self.get_selected_rows_indices()
        if not selected_rows: QMessageBox.warning(self, "提示", "请先选择要移除的整行。"); return
        rows_data = self._get_rows_data(selected_rows); start_row = selected_rows[0]
        cmd = WordlistRowOperationCommand(self, start_row, rows_data, 'remove', description="移除选中行"); self.undo_stack.push(cmd)
    def on_file_selected(self, current, previous):
        if not self.undo_stack.isClean() and previous:
            reply = QMessageBox.question(self, "未保存的更改", "您有未保存的更改，确定要切换吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                self.file_list_widget.currentItemChanged.disconnect(self.on_file_selected)
                self.file_list_widget.setCurrentItem(previous); self.file_list_widget.currentItemChanged.connect(self.on_file_selected)
                return
        if current: self.current_wordlist_path = os.path.join(self.WORD_LIST_DIR, current.text()); self.load_file_to_table()
        else: self.current_wordlist_path = None; self.table_widget.setRowCount(0); self.undo_stack.clear()
    def load_file_to_table(self):
        self.table_widget.blockSignals(True); self.table_widget.setRowCount(0)
        if not self.current_wordlist_path: self.table_widget.blockSignals(False); return
        try:
            spec = importlib.util.spec_from_file_location("temp_wordlist", self.current_wordlist_path)
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            word_groups = getattr(module, 'WORD_GROUPS', []); row = 0
            for i, group in enumerate(word_groups, 1):
                for word, value in group.items():
                    ipa, lang_code = value if isinstance(value, tuple) and len(value) == 2 else (str(value), '')
                    self.table_widget.insertRow(row); self.populate_row(row, [str(i), word, ipa, lang_code]); row += 1
            self.undo_stack.clear()
        except Exception as e: QMessageBox.critical(self, "加载失败", f"无法解析单词表文件 '{os.path.basename(self.current_wordlist_path)}':\n{e}")
        finally: self.table_widget.blockSignals(False)
    def populate_row(self, row, data):
        self.table_widget.setItem(row, 0, QTableWidgetItem(data[0])); self.table_widget.setItem(row, 1, QTableWidgetItem(data[1])); self.table_widget.setItem(row, 2, QTableWidgetItem(data[2]))
        combo = QComboBox(self.table_widget); combo.setIconSize(QSize(24, 18))
        for display_name, lang_code in LANGUAGE_MAP.items():
            icon_path = os.path.join(self.flags_path, f"{FLAG_CODE_MAP.get(lang_code, 'auto')}.png")
            combo.addItem(QIcon(icon_path) if os.path.exists(icon_path) else QIcon(), display_name, lang_code)
        index = combo.findData(data[3])
        if index != -1: combo.setCurrentIndex(index)
        combo.view().pressed.connect(lambda _, r=row: self.on_language_combo_pressed(r))
        combo.activated.connect(lambda idx, r=row: self.on_language_manually_changed(idx, r))
        self.table_widget.setCellWidget(row, 3, combo)
    def new_wordlist(self):
        if not self.undo_stack.isClean():
            reply = QMessageBox.question(self, "未保存的更改", "您有未保存的更改，确定要新建吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No: return
        self.table_widget.setRowCount(0); self.current_wordlist_path = None
        self.file_list_widget.setCurrentItem(None); self.undo_stack.clear(); self.add_row()
    def save_wordlist(self):
        if self.current_wordlist_path: self._write_to_file(self.current_wordlist_path)
        else: self.save_wordlist_as()
    def save_wordlist_as(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "另存为单词表", self.WORD_LIST_DIR, "Python 文件 (*.py)")
        if filepath:
            if not filepath.endswith('.py'): filepath += '.py'
            self._write_to_file(filepath); self.current_wordlist_path = filepath; self.refresh_file_list()
            for i in range(self.file_list_widget.count()):
                if self.file_list_widget.item(i).text() == os.path.basename(filepath): self.file_list_widget.setCurrentRow(i); break
    def _write_to_file(self, filepath):
        word_groups_map = {}
        for row in range(self.table_widget.rowCount()):
            try:
                group_item = self.table_widget.item(row, 0); word_item = self.table_widget.item(row, 1)
                if not group_item or not word_item or not group_item.text().isdigit() or not word_item.text().strip(): continue
                group_id = int(group_item.text()); word = word_item.text().strip()
                ipa_item = self.table_widget.item(row, 2); ipa = ipa_item.text().strip() if ipa_item else ''
                lang_combo = self.table_widget.cellWidget(row, 3); lang_code = lang_combo.currentData() if lang_combo else ''
                if group_id not in word_groups_map: word_groups_map[group_id] = {}
                word_groups_map[group_id][word] = (ipa, lang_code)
            except (ValueError, AttributeError): continue
        word_groups_list = [v for k, v in sorted(word_groups_map.items())]
        py_code = f"# Auto-generated by PhonAcq Assistant Wordlist Editor\n# Save date: {datetime.now():%Y-%m-%d %H:%M:%S}\n\nWORD_GROUPS = [\n"
        for group in word_groups_list:
            if not group: continue
            py_code += "    {\n";
            for word, (ipa, lang) in group.items():
                word_escaped = word.replace("'", "\\'"); ipa_escaped = ipa.replace("'", "\\'")
                py_code += f"        '{word_escaped}': ('{ipa_escaped}', '{lang}'),\n"
            py_code += "    },\n"
        py_code += "]\n"
        try:
            with open(filepath, 'w', encoding='utf-8') as f: f.write(py_code)
            self.undo_stack.setClean(); QMessageBox.information(self, "成功", f"单词表已成功保存至:\n{filepath}")
        except Exception as e: QMessageBox.critical(self, "保存失败", f"无法保存文件:\n{e}")