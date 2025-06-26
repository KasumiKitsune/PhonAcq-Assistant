# --- START OF FILE dialect_visual_editor_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "图文词表编辑器"
MODULE_DESCRIPTION = "在程序内直接创建、编辑和保存用于方言图文采集的词表。"
# ---

import os
import importlib.util
from datetime import datetime
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QCheckBox, QShortcut, QUndoStack, 
                             QUndoCommand, QApplication, QMenu)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence, QColor, QBrush

try:
    from thefuzz import fuzz
except ImportError:
    class MockFuzz:
        def ratio(self, s1, s2):
            print("警告: thefuzz 库未安装，智能检测功能不可用。")
            return 0
    fuzz = MockFuzz()

WORD_LIST_DIR_FOR_DIALECT_VISUAL = ""

def create_page(parent_window, word_list_dir_visual):
    global WORD_LIST_DIR_FOR_DIALECT_VISUAL
    WORD_LIST_DIR_FOR_DIALECT_VISUAL = word_list_dir_visual
    return DialectVisualEditorPage(parent_window)

# Undo/Redo 命令类 (省略，保持不变)
class ChangeCellCommand(QUndoCommand):
    def __init__(self, editor, row, col, old_text, new_text, description):
        super().__init__(description)
        self.editor = editor; self.table = editor.table_widget
        self.row, self.col = row, col
        self.old_text, self.new_text = old_text, new_text
    def _set_text(self, text):
        item = self.table.item(self.row, self.col)
        if not item: item = QTableWidgetItem(); self.table.setItem(self.row, self.col, item)
        item.setText(text)
        if self.col == 0: self.editor.validate_all_ids()
    def redo(self): self._set_text(self.new_text)
    def undo(self): self._set_text(self.old_text)

class RowOperationCommand(QUndoCommand):
    def __init__(self, editor, start_row, rows_data, operation_type, move_offset=0, description=""):
        super().__init__(description)
        self.editor = editor; self.table = editor.table_widget
        self.start_row, self.rows_data, self.type, self.move_offset = start_row, rows_data, operation_type, move_offset
    def _insert_rows(self, at_row, data):
        for i, row_data in enumerate(data):
            self.table.insertRow(at_row + i)
            for j, cell_text in enumerate(row_data):
                self.table.setItem(at_row + i, j, QTableWidgetItem(cell_text))
        self.editor.validate_all_ids()
    def _remove_rows(self, at_row, count):
        for _ in range(count): self.table.removeRow(at_row)
        self.editor.validate_all_ids()
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

class DialectVisualEditorPage(QWidget):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.current_wordlist_path = None
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)
        self.old_text_before_edit = None
        self.id_widgets = {}

        self._init_ui()
        self.setup_connections_and_shortcuts()
        self.apply_layout_settings()
        self.refresh_file_list()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        self.left_panel = QWidget() # 保存为成员变量
        left_layout = QVBoxLayout(self.left_panel)
        # left_panel.setFixedWidth(280) # 移除硬编码
        
        self.file_list_widget = QListWidget()
        self.new_btn = QPushButton("新建图文词表"); self.save_btn = QPushButton("保存"); self.save_as_btn = QPushButton("另存为...")
        file_btn_layout = QHBoxLayout(); file_btn_layout.addWidget(self.save_btn); file_btn_layout.addWidget(self.save_as_btn)
        left_layout.addWidget(QLabel("图文词表文件:")); left_layout.addWidget(self.file_list_widget); left_layout.addWidget(self.new_btn); left_layout.addLayout(file_btn_layout)

        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel)
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(4); self.table_widget.setHorizontalHeaderLabels(["项目ID (必须唯一)", "图片文件路径 (可选)", "提示文字 (可选)", "备注 (可选)"])
        self.table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive); self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table_widget.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch); self.table_widget.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_widget.setColumnWidth(0, 200); self.table_widget.setColumnWidth(1, 200)
        
        table_btn_layout = QHBoxLayout()
        self.auto_detect_btn = QPushButton("自动检测图片"); self.auto_detect_btn.setToolTip("遍历所有行，为ID有值但图片为空的项，\n自动查找并填充图片文件。")
        self.smart_detect_checkbox = QCheckBox("智能检测"); self.smart_detect_checkbox.setToolTip("启用后，将忽略大小写、下划线和空格，\n并尝试为项目ID匹配最相似的图片名。")
        self.add_row_btn = QPushButton("添加项目"); self.remove_row_btn = QPushButton("移除选中项目")
        table_btn_layout.addStretch(); table_btn_layout.addWidget(self.auto_detect_btn); table_btn_layout.addWidget(self.smart_detect_checkbox)
        table_btn_layout.addWidget(self.add_row_btn); table_btn_layout.addWidget(self.remove_row_btn)
        
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
        if WORD_LIST_DIR_FOR_DIALECT_VISUAL and os.path.exists(WORD_LIST_DIR_FOR_DIALECT_VISUAL):
            files = sorted([f for f in os.listdir(WORD_LIST_DIR_FOR_DIALECT_VISUAL) if f.endswith('.py')])
            self.file_list_widget.addItems(files)
            for i in range(len(files)):
                if files[i] == current_selection: self.file_list_widget.setCurrentRow(i); break

    # ... (其余所有方法保持不变) ...
    # (setup_connections_and_shortcuts, keyPressEvent, on_clean_changed, etc.)
    def setup_connections_and_shortcuts(self):
        self.file_list_widget.currentItemChanged.connect(self.on_file_selected); self.new_btn.clicked.connect(self.new_wordlist)
        self.save_btn.clicked.connect(self.save_wordlist); self.save_as_btn.clicked.connect(self.save_wordlist_as)
        self.add_row_btn.clicked.connect(lambda: self.add_row()); self.remove_row_btn.clicked.connect(self.remove_row)
        self.auto_detect_btn.clicked.connect(self.auto_detect_images)
        self.table_widget.itemPressed.connect(self.on_item_pressed); self.table_widget.itemChanged.connect(self.on_item_changed_for_undo)
        self.table_widget.cellDoubleClicked.connect(self.on_cell_double_clicked); self.table_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_widget.customContextMenuRequested.connect(self.show_context_menu); self.undo_stack.cleanChanged.connect(self.on_clean_changed)
        self.undo_action = self.undo_stack.createUndoAction(self, "撤销"); self.undo_action.setShortcut(QKeySequence.Undo)
        self.redo_action = self.undo_stack.createRedoAction(self, "重做"); self.redo_action.setShortcut(QKeySequence.Redo)
        self.addAction(self.undo_action); self.addAction(self.redo_action)
        QShortcut(QKeySequence.Save, self, self.save_wordlist); QShortcut(QKeySequence("Ctrl+Shift+S"), self, self.save_wordlist_as)
        QShortcut(QKeySequence.New, self, self.new_wordlist); QShortcut(QKeySequence.Copy, self, self.copy_selection)
        QShortcut(QKeySequence.Cut, self, self.cut_selection); QShortcut(QKeySequence.Paste, self, self.paste_selection)
        QShortcut(QKeySequence("Ctrl+D"), self, self.duplicate_rows); QShortcut(QKeySequence(Qt.ALT | Qt.Key_Up), self, lambda: self.move_rows(-1))
        QShortcut(QKeySequence(Qt.ALT | Qt.Key_Down), self, lambda: self.move_rows(1)); QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Plus), self, lambda: self.add_row())
        QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Equal), self, lambda: self.add_row()); QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Minus), self, self.remove_row)
    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace) and self.table_widget.selectedItems():
            self.clear_selection_contents(); event.accept()
        else: super().keyPressEvent(event)
    def on_clean_changed(self, is_clean): self.save_btn.setEnabled(not is_clean)
    def on_item_pressed(self, item):
        if item: self.old_text_before_edit = item.text()
    def on_item_changed_for_undo(self, item):
        if self.old_text_before_edit is not None and self.old_text_before_edit != item.text():
            command = ChangeCellCommand(self, item.row(), item.column(), self.old_text_before_edit, item.text(), "修改单元格")
            self.undo_stack.push(command)
            if item.column() == 0: self.validate_id_uniqueness(item)
        self.old_text_before_edit = None
    def validate_id_uniqueness(self, changed_item):
        old_text = self.old_text_before_edit
        if old_text and old_text in self.id_widgets:
            if changed_item in self.id_widgets[old_text]: self.id_widgets[old_text].remove(changed_item)
            if not self.id_widgets[old_text]: del self.id_widgets[old_text]
            if old_text in self.id_widgets and len(self.id_widgets[old_text]) == 1: self.id_widgets[old_text][0].setBackground(QBrush(Qt.white))
        new_text = changed_item.text().strip()
        if not new_text: changed_item.setBackground(QBrush(Qt.white)); return
        if new_text not in self.id_widgets: self.id_widgets[new_text] = []
        if changed_item not in self.id_widgets[new_text]: self.id_widgets[new_text].append(changed_item)
        if len(self.id_widgets[new_text]) > 1:
            for item in self.id_widgets[new_text]: item.setBackground(QBrush(QColor("#FFCCCC")))
        else: changed_item.setBackground(QBrush(Qt.white))
    def validate_all_ids(self):
        self.id_widgets.clear(); self.table_widget.blockSignals(True)
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, 0)
            if item:
                item_text = item.text().strip()
                if not item_text: continue
                if item_text not in self.id_widgets: self.id_widgets[item_text] = []
                self.id_widgets[item_text].append(item)
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, 0)
            if item:
                item_text = item.text().strip()
                is_duplicate = item_text and len(self.id_widgets.get(item_text, [])) > 1
                item.setBackground(QBrush(QColor("#FFCCCC")) if is_duplicate else QBrush(Qt.white))
        self.table_widget.blockSignals(False)
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
    def _get_rows_data(self, row_indices): return [[self.table_widget.item(row, col).text() if self.table_widget.item(row, col) else "" for col in range(self.table_widget.columnCount())] for row in row_indices]
    def clear_selection_contents(self):
        selected_items = self.table_widget.selectedItems()
        if not selected_items: return
        self.undo_stack.beginMacro("清空内容")
        for item in selected_items:
            if item.text():
                cmd = ChangeCellCommand(self, item.row(), item.column(), item.text(), "", "清空单元格"); self.undo_stack.push(cmd)
        self.undo_stack.endMacro()
    def cut_selection(self): self.copy_selection(); self.clear_selection_contents()
    def copy_selection(self):
        selection = self.table_widget.selectedRanges();
        if not selection: return
        rows = sorted(list(set(index.row() for index in self.table_widget.selectedIndexes()))); cols = sorted(list(set(index.column() for index in self.table_widget.selectedIndexes())))
        table_str = "\n".join(["\t".join([self.table_widget.item(r, c).text() if self.table_widget.item(r, c) else "" for c in cols]) for r in rows])
        QApplication.clipboard().setText(table_str)
    def paste_selection(self):
        selection = self.table_widget.selectedRanges();
        if not selection: return
        start_row = selection[0].topRow(); start_col = selection[0].leftColumn()
        text = QApplication.clipboard().text(); rows = text.strip('\n').split('\n')
        self.undo_stack.beginMacro("粘贴")
        for i, row in enumerate(rows):
            cells = row.split('\t')
            for j, cell_text in enumerate(cells):
                target_row, target_col = start_row + i, start_col + j
                if target_row < self.table_widget.rowCount() and target_col < self.table_widget.columnCount():
                    item = self.table_widget.item(target_row, target_col); old_text = item.text() if item else ""
                    if old_text != cell_text:
                        cmd = ChangeCellCommand(self, target_row, target_col, old_text, cell_text, "粘贴单元格"); self.undo_stack.push(cmd)
        self.undo_stack.endMacro()
    def duplicate_rows(self):
        rows_to_duplicate = self.get_selected_rows_indices()
        if not rows_to_duplicate:
            current_row = self.table_widget.currentRow()
            if current_row == -1: return
            rows_to_duplicate = [current_row]
        rows_data = self._get_rows_data(rows_to_duplicate); insert_at = rows_to_duplicate[-1] + 1
        for row_data in rows_data:
            if row_data[0]: row_data[0] += "_copy"
        cmd = RowOperationCommand(self, insert_at, rows_data, 'add', description="创建副本/重制行"); self.undo_stack.push(cmd)
    def move_rows(self, offset):
        selected_rows = self.get_selected_rows_indices()
        if not selected_rows: return
        if (offset == -1 and selected_rows[0] == 0) or (offset == 1 and selected_rows[-1] == self.table_widget.rowCount() - 1): return
        start_row = selected_rows[0]; rows_data = self._get_rows_data(selected_rows)
        cmd = RowOperationCommand(self, start_row, rows_data, 'move', offset, "移动行"); self.undo_stack.push(cmd)
        self.table_widget.clearSelection(); new_start_row = start_row + offset
        for i in range(len(selected_rows)): self.table_widget.selectRow(new_start_row + i)
    def add_row(self, at_row=None):
        if at_row is None: at_row = self.table_widget.rowCount()
        cmd = RowOperationCommand(self, at_row, [["", "", "", ""]], 'add', description="添加新行"); self.undo_stack.push(cmd)
        QApplication.processEvents()
        self.table_widget.scrollToItem(self.table_widget.item(at_row, 0), QTableWidget.ScrollHint.EnsureVisible)
        self.table_widget.selectRow(at_row)
    def remove_row(self):
        selected_rows = self.get_selected_rows_indices()
        if not selected_rows: QMessageBox.warning(self, "提示", "请先选择要移除的整行。"); return
        rows_data = self._get_rows_data(selected_rows); start_row = selected_rows[0]
        cmd = RowOperationCommand(self, start_row, rows_data, 'remove', description="移除选中行"); self.undo_stack.push(cmd)
    def _normalize_string(self, text): return text.lower().replace("_", "").replace(" ", "")
    def auto_detect_images(self):
        if not self.current_wordlist_path: QMessageBox.warning(self, "操作无效", "请先加载一个图文词表。"); return
        wordlist_dir = os.path.dirname(self.current_wordlist_path)
        wordlist_name = os.path.splitext(os.path.basename(self.current_wordlist_path))[0]
        image_folder = os.path.join(wordlist_dir, wordlist_name)
        if not os.path.isdir(image_folder): QMessageBox.information(self, "提示", f"未找到对应的图片文件夹:\n{image_folder}"); return
        is_smart = self.smart_detect_checkbox.isChecked(); detected_count = 0
        image_files = [f for f in os.listdir(image_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        norm_map = {self._normalize_string(os.path.splitext(f)[0]): f for f in image_files}; used_images = set()
        self.undo_stack.beginMacro("自动检测图片")
        try:
            for row in range(self.table_widget.rowCount()):
                id_item = self.table_widget.item(row, 0); image_item = self.table_widget.item(row, 1)
                if id_item and id_item.text().strip() and (not image_item or not image_item.text().strip()):
                    item_id = id_item.text().strip(); best_match = None
                    if not is_smart:
                        for ext in ['.png', '.jpg', '.jpeg']:
                            if os.path.exists(os.path.join(image_folder, item_id + ext)): best_match = item_id + ext; break
                    else:
                        norm_id = self._normalize_string(item_id); best_score = 0; best_name = None
                        for norm_name in norm_map:
                            if norm_name in used_images: continue
                            score = fuzz.ratio(norm_id, norm_name)
                            if score > best_score: best_score = score; best_name = norm_name
                        if best_score >= 70 and best_name: best_match = norm_map[best_name]; used_images.add(best_name)
                    if best_match:
                        display_path = f"{wordlist_name}/{best_match}".replace("\\", "/")
                        old_text = image_item.text() if image_item else ""
                        cmd = ChangeCellCommand(self, row, 1, old_text, display_path, "自动填充图片路径"); self.undo_stack.push(cmd); detected_count += 1
        finally: self.undo_stack.endMacro()
        QMessageBox.information(self, "检测完成", f"成功检测并填充了 {detected_count} 个图片文件。" if detected_count > 0 else "没有找到可以自动填充的新图片文件。")
    def on_cell_double_clicked(self, row, column):
        if column != 1: return
        if not self.current_wordlist_path: QMessageBox.warning(self, "操作无效", "请先加载或保存词表以确定图片基准路径。"); return
        wordlist_dir = os.path.dirname(self.current_wordlist_path)
        wordlist_name = os.path.splitext(os.path.basename(self.current_wordlist_path))[0]
        image_folder = os.path.join(wordlist_dir, wordlist_name); os.makedirs(image_folder, exist_ok=True)
        filepath, _ = QFileDialog.getOpenFileName(self, "选择图片文件", image_folder, "图片文件 (*.png *.jpg *.jpeg)")
        if filepath:
            try: relative_path = os.path.relpath(filepath, wordlist_dir); display_path = relative_path.replace("\\", "/")
            except ValueError: display_path = os.path.basename(filepath)
            old_item = self.table_widget.item(row, 1); old_text = old_item.text() if old_item else ""
            cmd = ChangeCellCommand(self, row, 1, old_text, display_path, "选择图片文件"); self.undo_stack.push(cmd)
    def on_file_selected(self, current, previous):
        if not self.undo_stack.isClean() and previous:
            reply = QMessageBox.question(self, "未保存的更改", "您有未保存的更改，确定要切换吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                self.file_list_widget.currentItemChanged.disconnect(self.on_file_selected)
                self.file_list_widget.setCurrentItem(previous); self.file_list_widget.currentItemChanged.connect(self.on_file_selected)
                return
        if current: self.current_wordlist_path = os.path.join(WORD_LIST_DIR_FOR_DIALECT_VISUAL, current.text()); self.load_file_to_table()
        else: self.current_wordlist_path = None; self.table_widget.setRowCount(0); self.undo_stack.clear()
    def load_file_to_table(self):
        self.table_widget.blockSignals(True); self.table_widget.setRowCount(0)
        if not self.current_wordlist_path: self.table_widget.blockSignals(False); return
        try:
            module_name = f"temp_dialect_data_{os.path.splitext(os.path.basename(self.current_wordlist_path))[0]}"
            spec = importlib.util.spec_from_file_location(module_name, self.current_wordlist_path)
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            items_list = getattr(module, 'ITEMS', [])
            for row, item_data in enumerate(items_list):
                self.table_widget.insertRow(row)
                self.table_widget.setItem(row, 0, QTableWidgetItem(item_data.get('id', '')))
                self.table_widget.setItem(row, 1, QTableWidgetItem(item_data.get('image_path', '')))
                self.table_widget.setItem(row, 2, QTableWidgetItem(item_data.get('prompt_text', '')))
                self.table_widget.setItem(row, 3, QTableWidgetItem(item_data.get('notes', '')))
            self.table_widget.resizeRowsToContents(); self.undo_stack.clear(); self.validate_all_ids()
        except Exception as e: QMessageBox.critical(self, "加载失败", f"无法解析图文词表文件 '{os.path.basename(self.current_wordlist_path)}':\n{e}")
        finally: self.table_widget.blockSignals(False)
    def new_wordlist(self):
        if not self.undo_stack.isClean():
            reply = QMessageBox.question(self, "未保存的更改", "您有未保存的更改，确定要新建吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No: return
        self.table_widget.setRowCount(0); self.current_wordlist_path = None
        self.file_list_widget.setCurrentItem(None); self.undo_stack.clear(); self.add_row()
    def save_wordlist(self):
        if any(len(widgets) > 1 for widgets in self.id_widgets.values()):
            QMessageBox.warning(self, "保存失败", "存在重复的项目ID (已用红色高亮显示)。\n请修正后再保存。"); return
        if self.current_wordlist_path: self._write_to_file(self.current_wordlist_path)
        else: self.save_wordlist_as()
    def save_wordlist_as(self):
        if any(len(widgets) > 1 for widgets in self.id_widgets.values()):
            QMessageBox.warning(self, "保存失败", "存在重复的项目ID (已用红色高亮显示)。\n请修正后再保存。"); return
        filepath, _ = QFileDialog.getSaveFileName(self, "另存为图文词表", WORD_LIST_DIR_FOR_DIALECT_VISUAL, "Python 文件 (*.py)")
        if filepath:
            if not filepath.endswith('.py'): filepath += '.py'
            self._write_to_file(filepath); self.current_wordlist_path = filepath; self.refresh_file_list()
            for i in range(self.file_list_widget.count()):
                if self.file_list_widget.item(i).text() == os.path.basename(filepath): self.file_list_widget.setCurrentRow(i); break
    def _write_to_file(self, filepath):
        items_list = []
        for row in range(self.table_widget.rowCount()):
            item_data = {}
            id_item = self.table_widget.item(row, 0)
            if not id_item or not id_item.text().strip(): continue
            item_data['id'] = id_item.text().strip()
            item_data['image_path'] = self.table_widget.item(row, 1).text().strip() if self.table_widget.item(row, 1) else ''
            item_data['prompt_text'] = self.table_widget.item(row, 2).text().strip() if self.table_widget.item(row, 2) else ''
            item_data['notes'] = self.table_widget.item(row, 3).text().strip() if self.table_widget.item(row, 3) else ''
            items_list.append(item_data)
        py_code = f"# Auto-generated by PhonAcq Assistant Dialect Visual Editor\n# Save date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nITEMS = [\n"
        for item in items_list:
            py_code += "    {\n"
            for key, value in item.items():
                py_code += f"        '{key}': '''{value}''',\n"
            py_code += "    },\n"
        py_code += "]\n"
        try:
            with open(filepath, 'w', encoding='utf-8') as f: f.write(py_code)
            self.undo_stack.setClean(); QMessageBox.information(self, "成功", f"图文词表已成功保存至:\n{filepath}")
        except Exception as e: QMessageBox.critical(self, "保存失败", f"无法保存文件:\n{e}")