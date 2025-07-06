# --- START OF FILE modules/dialect_visual_editor_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "图文词表编辑器"
MODULE_DESCRIPTION = "在程序内直接创建、编辑和保存用于“看图说话采集”的词表。"
# ---

import os
import sys
from datetime import datetime
import json
import shutil # [新增] 用于文件复制
import subprocess # [新增] 用于打开文件浏览器
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
                             QListWidgetItem, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QShortcut, QUndoStack, 
                             QUndoCommand, QApplication, QMenu)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence, QColor, QBrush, QIcon

try:
    from thefuzz import fuzz
except ImportError:
    class MockFuzz:
        def ratio(self, s1, s2): print("警告: thefuzz 库未安装，智能检测功能不可用。"); return 0
    fuzz = MockFuzz()

WORD_LIST_DIR_FOR_DIALECT_VISUAL = ""

def create_page(parent_window, word_list_dir_visual, ToggleSwitchClass, icon_manager):
    global WORD_LIST_DIR_FOR_DIALECT_VISUAL
    WORD_LIST_DIR_FOR_DIALECT_VISUAL = word_list_dir_visual
    return DialectVisualEditorPage(parent_window, ToggleSwitchClass, icon_manager)

class ChangeCellCommand(QUndoCommand):
    def __init__(self, editor, row, col, old_text, new_text, description):
        super().__init__(description); self.editor = editor; self.table = editor.table_widget; self.row, self.col = row, col; self.old_text, self.new_text = old_text, new_text
    def _set_text(self, text):
        item = self.table.item(self.row, self.col)
        if not item: item = QTableWidgetItem(); self.table.setItem(self.row, self.col, item)
        if self.col == 1:
            item.setData(Qt.DisplayRole, os.path.basename(text)); item.setData(Qt.EditRole, text)
        else:
            item.setText(text)
        if self.col == 0: self.editor.validate_all_ids()
    def redo(self): self._set_text(self.new_text)
    def undo(self): self._set_text(self.old_text)

class RowOperationCommand(QUndoCommand):
    def __init__(self, editor, start_row, rows_data, operation_type, move_offset=0, description=""):
        super().__init__(description); self.editor = editor; self.table = editor.table_widget; self.start_row, self.rows_data, self.type, self.move_offset = start_row, rows_data, operation_type, move_offset
    def _insert_rows(self, at_row, data):
        for i, row_data in enumerate(data): self.table.insertRow(at_row + i); self.editor.populate_row(at_row + i, row_data)
        self.editor.validate_all_ids()
    def _remove_rows(self, at_row, count):
        for _ in range(count): self.table.removeRow(at_row)
        self.editor.validate_all_ids()
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

class DialectVisualEditorPage(QWidget):
    def __init__(self, parent_window, ToggleSwitchClass, icon_manager):
        super().__init__(); self.parent_window = parent_window; self.ToggleSwitch = ToggleSwitchClass; self.icon_manager = icon_manager
        self.current_wordlist_path = None; self.undo_stack = QUndoStack(self); self.undo_stack.setUndoLimit(100); self.old_text_before_edit = None; self.id_widgets = {}
        self._init_ui(); self.setup_connections_and_shortcuts(); self.update_icons(); self.apply_layout_settings(); self.refresh_file_list()

    def _init_ui(self):
        main_layout = QHBoxLayout(self); self.left_panel = QWidget(); left_layout = QVBoxLayout(self.left_panel)
        self.file_list_widget = QListWidget(); self.file_list_widget.setToolTip("所有可编辑的图文词表文件。")
        self.new_btn = QPushButton("新建图文词表"); self.save_btn = QPushButton("保存"); self.save_as_btn = QPushButton("另存为...")
        file_btn_layout = QHBoxLayout(); file_btn_layout.addWidget(self.save_btn); file_btn_layout.addWidget(self.save_as_btn)
        left_layout.addWidget(QLabel("图文词表文件:")); left_layout.addWidget(self.file_list_widget); left_layout.addWidget(self.new_btn); left_layout.addLayout(file_btn_layout)
        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel)
        self.table_widget = QTableWidget(); self.table_widget.setColumnCount(4); self.table_widget.setHorizontalHeaderLabels(["项目ID (必须唯一)", "图片文件", "提示文字 (可选)", "备注 (可选)"])
        self.table_widget.setToolTip("在此表格中编辑图文词表内容。\n- 项目ID必须唯一，重复的ID将以红色高亮显示。\n- 双击“图片文件”列可打开文件选择对话框。")
        self.table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive); self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive); self.table_widget.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch); self.table_widget.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_widget.setColumnWidth(0, 200); self.table_widget.setColumnWidth(1, 200)
        self.file_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list_widget.setToolTip("所有可编辑的图文词表文件。\n右键单击可进行更多操作。")        
        table_btn_layout = QHBoxLayout()
        # [新增] Undo/Redo 按钮
        self.undo_btn = QPushButton("撤销"); self.undo_btn.setToolTip("撤销上一步操作 (快捷键: Ctrl+Z)。")
        self.redo_btn = QPushButton("重做"); self.redo_btn.setToolTip("重做上一步已撤销的操作 (快捷键: Ctrl+Y)。")
        table_btn_layout.addWidget(self.undo_btn); table_btn_layout.addWidget(self.redo_btn); table_btn_layout.addSpacing(20) # 增加间距
        
        self.auto_detect_btn = QPushButton("自动检测图片"); self.auto_detect_btn.setToolTip("遍历所有行，为ID有值但图片为空的项，\n自动查找并填充图片文件。")
        self.smart_detect_switch = self.ToggleSwitch(); self.smart_detect_switch.setToolTip("启用后，将忽略大小写、下划线和空格，\n并尝试为项目ID匹配最相似的图片名。")
        self.add_row_btn = QPushButton("添加项目"); self.remove_row_btn = QPushButton("移除选中项目")
        
        table_btn_layout.addWidget(self.auto_detect_btn); table_btn_layout.addWidget(QLabel("智能检测:")); table_btn_layout.addWidget(self.smart_detect_switch)
        table_btn_layout.addStretch() # 移动到右侧，以平衡布局
        table_btn_layout.addWidget(self.add_row_btn); table_btn_layout.addWidget(self.remove_row_btn)
        
        right_layout.addWidget(self.table_widget); right_layout.addLayout(table_btn_layout)
        main_layout.addWidget(self.left_panel); main_layout.addWidget(right_panel, 1)

    def update_icons(self):
        self.new_btn.setIcon(self.icon_manager.get_icon("new_file")); self.save_btn.setIcon(self.icon_manager.get_icon("save")); self.save_as_btn.setIcon(self.icon_manager.get_icon("save_as"))
        # [修改] 使用正确的图标名称
        self.add_row_btn.setIcon(self.icon_manager.get_icon("add_row")); self.remove_row_btn.setIcon(self.icon_manager.get_icon("remove_row"))
        self.auto_detect_btn.setIcon(self.icon_manager.get_icon("auto_detect")) # auto_detect 图标

        # [新增] Undo/Redo 按钮图标
        self.undo_btn.setIcon(self.icon_manager.get_icon("undo")); self.redo_btn.setIcon(self.icon_manager.get_icon("redo"))
        
        # [修改] 更新 Undo/Redo 动作的图标
        self.undo_action.setIcon(self.icon_manager.get_icon("undo"))
        self.redo_action.setIcon(self.icon_manager.get_icon("redo"))

    def apply_layout_settings(self):
        config = self.parent_window.config; ui_settings = config.get("ui_settings", {}); width = ui_settings.get("editor_sidebar_width", 280); self.left_panel.setFixedWidth(width)
    def refresh_file_list(self):
        if hasattr(self, 'parent_window'): self.apply_layout_settings()
        current_selection = self.file_list_widget.currentItem().text() if self.file_list_widget.currentItem() else ""
        self.file_list_widget.clear()
        if WORD_LIST_DIR_FOR_DIALECT_VISUAL and os.path.exists(WORD_LIST_DIR_FOR_DIALECT_VISUAL):
            # [修改] 只查找 .json 文件
            files = sorted([f for f in os.listdir(WORD_LIST_DIR_FOR_DIALECT_VISUAL) if f.endswith('.json')])
            self.file_list_widget.addItems(files)
            for i in range(len(files)):
                if files[i] == current_selection: self.file_list_widget.setCurrentRow(i); break
    def on_file_double_clicked(self, item):
        self._show_in_explorer(item)

    def show_file_context_menu(self, position):
        item = self.file_list_widget.itemAt(position)
        if not item: return

        menu = QMenu(self.file_list_widget)
        show_action = menu.addAction(self.icon_manager.get_icon("open_folder"), "在文件浏览器中显示")
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

    def _show_in_explorer(self, item):
        if not item: return
        filepath = os.path.join(WORD_LIST_DIR_FOR_DIALECT_VISUAL, item.text())
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
        src_path = os.path.join(WORD_LIST_DIR_FOR_DIALECT_VISUAL, item.text())
        if not os.path.exists(src_path):
            QMessageBox.warning(self, "文件不存在", "无法创建副本，源文件可能已被移动或删除。"); self.refresh_file_list(); return

        base, ext = os.path.splitext(item.text())
        dest_path = os.path.join(WORD_LIST_DIR_FOR_DIALECT_VISUAL, f"{base}_copy{ext}")
        i = 1
        while os.path.exists(dest_path):
            dest_path = os.path.join(WORD_LIST_DIR_FOR_DIALECT_VISUAL, f"{base}_copy_{i}{ext}")
            i += 1
        
        try:
            shutil.copy2(src_path, dest_path)
            self.refresh_file_list()
        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"无法创建副本: {e}")

    def _delete_file(self, item):
        if not item: return
        filepath = os.path.join(WORD_LIST_DIR_FOR_DIALECT_VISUAL, item.text())
        
        reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除文件 '{item.text()}' 吗？\n此操作不可撤销。",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            try:
                os.remove(filepath)
                if filepath == self.current_wordlist_path:
                    self.current_wordlist_path = None
                    self.table_widget.setRowCount(0)
                    self.undo_stack.clear()
                self.refresh_file_list()
            except Exception as e:
                QMessageBox.critical(self, "删除失败", f"无法删除文件: {e}")

    def setup_connections_and_shortcuts(self):
        self.file_list_widget.itemDoubleClicked.connect(self.on_file_double_clicked)
        self.file_list_widget.customContextMenuRequested.connect(self.show_file_context_menu)
        self.file_list_widget.currentItemChanged.connect(self.on_file_selected); self.new_btn.clicked.connect(self.new_wordlist); self.save_btn.clicked.connect(self.save_wordlist); self.save_as_btn.clicked.connect(self.save_wordlist_as)
        self.add_row_btn.clicked.connect(lambda: self.add_row()); self.remove_row_btn.clicked.connect(self.remove_row); self.auto_detect_btn.clicked.connect(self.auto_detect_images); self.table_widget.itemPressed.connect(self.on_item_pressed); self.table_widget.itemChanged.connect(self.on_item_changed_for_undo)
        self.table_widget.cellDoubleClicked.connect(self.on_cell_double_clicked); self.table_widget.setContextMenuPolicy(Qt.CustomContextMenu); self.table_widget.customContextMenuRequested.connect(self.show_context_menu); self.undo_stack.cleanChanged.connect(self.on_clean_changed)
        
        # [新增] 连接 Undo/Redo 按钮
        self.undo_btn.clicked.connect(self.undo_stack.undo)
        self.redo_btn.clicked.connect(self.undo_stack.redo)
        # [新增] 控制 Undo/Redo 按钮的启用/禁用状态
        self.undo_stack.canUndoChanged.connect(self.undo_btn.setEnabled)
        self.undo_stack.canRedoChanged.connect(self.redo_btn.setEnabled)

        # 确保初始状态正确（因为信号在连接时通常不会立即发出）
        self.undo_btn.setEnabled(self.undo_stack.canUndo())
        self.redo_btn.setEnabled(self.undo_stack.canRedo())        
        self.undo_action = self.undo_stack.createUndoAction(self, "撤销"); self.undo_action.setShortcut(QKeySequence.Undo); self.undo_action.setToolTip("撤销上一步操作。"); self.redo_action = self.undo_stack.createRedoAction(self, "重做"); self.redo_action.setShortcut(QKeySequence.Redo); self.redo_action.setToolTip("重做上一步已撤销的操作。")
        self.addAction(self.undo_action); self.addAction(self.redo_action)
        QShortcut(QKeySequence.Save, self, self.save_wordlist); QShortcut(QKeySequence("Ctrl+Shift+S"), self, self.save_wordlist_as); QShortcut(QKeySequence.New, self, self.new_wordlist); QShortcut(QKeySequence.Copy, self, self.copy_selection); QShortcut(QKeySequence.Cut, self, self.cut_selection); QShortcut(QKeySequence.Paste, self, self.paste_selection)
        QShortcut(QKeySequence("Ctrl+D"), self, self.duplicate_rows); QShortcut(QKeySequence(Qt.ALT | Qt.Key_Up), self, lambda: self.move_rows(-1)); QShortcut(QKeySequence(Qt.ALT | Qt.Key_Down), self, lambda: self.move_rows(1)); QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Plus), self, lambda: self.add_row()); QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Equal), self, lambda: self.add_row()); QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Minus), self, self.remove_row)
    def keyPressEvent(self, event):
        if (event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace) and self.table_widget.selectedItems(): self.clear_selection_contents(); event.accept()
        else: super().keyPressEvent(event)
    def on_clean_changed(self, is_clean): self.save_btn.setEnabled(not is_clean)
    def on_item_pressed(self, item):
        if item: self.old_text_before_edit = item.data(Qt.EditRole)
    def on_item_changed_for_undo(self, item):
        new_text = item.data(Qt.EditRole) 
        if self.old_text_before_edit is not None and self.old_text_before_edit != new_text:
            command = ChangeCellCommand(self, item.row(), item.column(), self.old_text_before_edit, new_text, "修改单元格"); self.undo_stack.push(command)
            if item.column() == 0: self.validate_all_ids()
        self.old_text_before_edit = None
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
                item_text = item.text().strip(); is_duplicate = item_text and len(self.id_widgets.get(item_text, [])) > 1
                item.setBackground(QBrush(QColor("#FFCCCC")) if is_duplicate else QBrush(Qt.white))
        self.table_widget.blockSignals(False)
    def show_context_menu(self, position):
        menu = QMenu(self.file_list_widget); selection = self.table_widget.selectedRanges()
        cut_action = menu.addAction(self.icon_manager.get_icon("cut"), "剪切 (Ctrl+X)"); copy_action = menu.addAction(self.icon_manager.get_icon("copy"), "复制 (Ctrl+C)"); paste_action = menu.addAction(self.icon_manager.get_icon("paste"), "粘贴 (Ctrl+V)")
        menu.addSeparator(); duplicate_action = menu.addAction(self.icon_manager.get_icon("duplicate_row"), "创建副本/重制行 (Ctrl+D)"); menu.addSeparator()
        add_row_action = menu.addAction(self.icon_manager.get_icon("add_row"), "在下方插入新行"); remove_row_action = menu.addAction(self.icon_manager.get_icon("remove_row"), "删除选中行")
        menu.addSeparator(); clear_contents_action = menu.addAction(self.icon_manager.get_icon("clear_contents"), "清空内容 (Delete)")
        menu.addSeparator(); move_up_action = menu.addAction(self.icon_manager.get_icon("move_up"), "上移选中行 (Alt+Up)")
        move_down_action = menu.addAction(self.icon_manager.get_icon("move_down"), "下移选中行 (Alt+Down)")
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
        data = []
        for row in row_indices:
            row_data = [];
            for col in range(self.table_widget.columnCount()):
                item = self.table_widget.item(row, col)
                if item: row_data.append(item.data(Qt.EditRole) or "")
                else: row_data.append("")
            data.append(row_data)
        return data
    def clear_selection_contents(self):
        selected_items = self.table_widget.selectedItems();
        if not selected_items: return
        self.undo_stack.beginMacro("清空内容")
        for item in selected_items:
            old_text = item.data(Qt.EditRole);
            if old_text: cmd = ChangeCellCommand(self, item.row(), item.column(), old_text, "", "清空单元格"); self.undo_stack.push(cmd)
        self.undo_stack.endMacro()
    def cut_selection(self): self.copy_selection(); self.clear_selection_contents()
    def copy_selection(self):
        selection = self.table_widget.selectedRanges();
        if not selection: return
        rows = sorted(list(set(index.row() for index in self.table_widget.selectedIndexes()))); cols = sorted(list(set(index.column() for index in self.table_widget.selectedIndexes())))
        table_str = "\n".join(["\t".join([self.table_widget.item(r, c).data(Qt.EditRole) if self.table_widget.item(r, c) else "" for c in cols]) for r in rows]); QApplication.clipboard().setText(table_str)
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
                    item = self.table_widget.item(target_row, target_col); old_text = item.data(Qt.EditRole) if item else ""
                    if old_text != cell_text: cmd = ChangeCellCommand(self, target_row, target_col, old_text, cell_text, "粘贴单元格"); self.undo_stack.push(cmd)
        self.undo_stack.endMacro()
    def duplicate_rows(self):
        selected_rows_indices = self.get_selected_rows_indices() # 获取用户显式选择的行

        if not selected_rows_indices: # 如果用户没有显式选择任何行
            current_focused_row = self.table_widget.currentRow() # 获取当前表格焦点所在的行

            if current_focused_row == -1: # 如果连焦点行都没有 (例如表格是空的，或未点击过)
                QMessageBox.information(self, "提示", "请选择要创建副本的行。")
                return # 没有任何行可供复制，直接返回
            else:
                selected_rows_indices = [current_focused_row] # 否则，将焦点行作为要复制的行

        # 从这里开始，selected_rows_indices 保证包含至少一个有效行索引
        rows_data = self._get_rows_data(selected_rows_indices)
        
        # 添加 "_copy" 到 ID 以保持唯一性
        for row_data in rows_data:
            if row_data[0]: # 检查项目ID列 (索引0) 是否有值
                row_data[0] += "_copy"

        # 确定插入新行的位置：在最后一个选中行的下方
        insert_at = selected_rows_indices[-1] + 1
        
        cmd = RowOperationCommand(self, insert_at, rows_data, 'add', description="创建副本/重制行")
        self.undo_stack.push(cmd)
    def move_rows(self, offset):
        selected_rows = self.get_selected_rows_indices();
        if not selected_rows: return
        if (offset == -1 and selected_rows[0] == 0) or (offset == 1 and selected_rows[-1] == self.table_widget.rowCount() - 1): return
        start_row = selected_rows[0]; rows_data = self._get_rows_data(selected_rows); cmd = RowOperationCommand(self, start_row, rows_data, 'move', offset, "移动行"); self.undo_stack.push(cmd)
        self.table_widget.clearSelection(); new_start_row = start_row + offset
        for i in range(len(selected_rows)): self.table_widget.selectRow(new_start_row + i)
    def add_row(self, at_row=None):
        if at_row is None: at_row = self.table_widget.rowCount()
        cmd = RowOperationCommand(self, at_row, [["", "", "", ""]], 'add', description="添加新行"); self.undo_stack.push(cmd); QApplication.processEvents()
        self.table_widget.scrollToItem(self.table_widget.item(at_row, 0), QTableWidget.ScrollHint.EnsureVisible); self.table_widget.selectRow(at_row)
    def remove_row(self):
        selected_rows = self.get_selected_rows_indices()
        if not selected_rows: QMessageBox.warning(self, "提示", "请先选择要移除的整行。"); return
        rows_data = self._get_rows_data(selected_rows); start_row = selected_rows[0]; cmd = RowOperationCommand(self, start_row, rows_data, 'remove', description="移除选中行"); self.undo_stack.push(cmd)
    def _normalize_string(self, text): return text.lower().replace("_", "").replace(" ", "")
    def auto_detect_images(self):
        if not self.current_wordlist_path: QMessageBox.warning(self, "操作无效", "请先加载一个图文词表。"); return
        wordlist_dir = os.path.dirname(self.current_wordlist_path); wordlist_name = os.path.splitext(os.path.basename(self.current_wordlist_path))[0]
        image_folder = os.path.join(wordlist_dir, wordlist_name);
        if not os.path.isdir(image_folder): QMessageBox.information(self, "提示", f"未找到对应的图片文件夹:\n{image_folder}"); return
        is_smart = self.smart_detect_switch.isChecked(); detected_count = 0; image_files = [f for f in os.listdir(image_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        norm_map = {self._normalize_string(os.path.splitext(f)[0]): f for f in image_files}; used_images = set(); self.undo_stack.beginMacro("自动检测图片")
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
                        display_path = f"{wordlist_name}/{best_match}".replace("\\", "/"); old_text = image_item.data(Qt.EditRole) if image_item else ""
                        cmd = ChangeCellCommand(self, row, 1, old_text, display_path, "自动填充图片路径"); self.undo_stack.push(cmd); detected_count += 1
        finally: self.undo_stack.endMacro()
        QMessageBox.information(self, "检测完成", f"成功检测并填充了 {detected_count} 个图片文件。" if detected_count > 0 else "没有找到可以自动填充的新图片文件。")
    def on_cell_double_clicked(self, row, column):
        if column != 1: return
        if not self.current_wordlist_path: QMessageBox.warning(self, "操作无效", "请先加载或保存词表以确定图片基准路径。"); return
        wordlist_dir = os.path.dirname(self.current_wordlist_path); wordlist_name = os.path.splitext(os.path.basename(self.current_wordlist_path))[0]
        image_folder = os.path.join(wordlist_dir, wordlist_name); os.makedirs(image_folder, exist_ok=True)
        filepath, _ = QFileDialog.getOpenFileName(self, "选择图片文件", image_folder, "图片文件 (*.png *.jpg *.jpeg)")
        if filepath:
            try: relative_path = os.path.relpath(filepath, wordlist_dir); display_path = relative_path.replace("\\", "/")
            except ValueError: display_path = os.path.basename(filepath)
            old_item = self.table_widget.item(row, 1); old_text = old_item.data(Qt.EditRole) if old_item else ""; cmd = ChangeCellCommand(self, row, 1, old_text, display_path, "选择图片文件"); self.undo_stack.push(cmd)
            
    def on_file_selected(self, current, previous):
        if not self.undo_stack.isClean() and previous:
            reply = QMessageBox.question(self, "未保存的更改", "您有未保存的更改，确定要切换吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No: self.file_list_widget.currentItemChanged.disconnect(self.on_file_selected); self.file_list_widget.setCurrentItem(previous); self.file_list_widget.currentItemChanged.connect(self.on_file_selected); return
        if current: self.current_wordlist_path = os.path.join(WORD_LIST_DIR_FOR_DIALECT_VISUAL, current.text()); self.load_file_to_table()
        else: self.current_wordlist_path = None; self.table_widget.setRowCount(0); self.undo_stack.clear()
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
            with open(self.current_wordlist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if "meta" not in data or "items" not in data or not isinstance(data["items"], list):
                raise ValueError("JSON文件格式无效，缺少 'meta' 或 'items' 键。")

            items_list = data.get('items', [])
            for row, item_data in enumerate(items_list):
                self.table_widget.insertRow(row)
                self.populate_row(row, [
                    item_data.get('id', ''),
                    item_data.get('image_path', ''),
                    item_data.get('prompt_text', ''),
                    item_data.get('notes', '')
                ])
            
            self.table_widget.resizeRowsToContents()
            self.undo_stack.clear()
            self.validate_all_ids()
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            QMessageBox.critical(self, "加载失败", f"无法解析JSON图文词表文件 '{os.path.basename(self.current_wordlist_path)}':\n{e}")
        finally:
            self.table_widget.blockSignals(False)
    def populate_row(self, row, data):
        self.table_widget.setItem(row, 0, QTableWidgetItem(data[0]))
        image_path_item = QTableWidgetItem(); full_path = data[1]
        image_path_item.setData(Qt.DisplayRole, os.path.basename(full_path)); image_path_item.setData(Qt.EditRole, full_path); self.table_widget.setItem(row, 1, image_path_item)
        self.table_widget.setItem(row, 2, QTableWidgetItem(data[2])); self.table_widget.setItem(row, 3, QTableWidgetItem(data[3]))
    def new_wordlist(self):
        if not self.undo_stack.isClean():
            reply = QMessageBox.question(self, "未保存的更改", "您有未保存的更改，确定要新建吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No: return
        self.table_widget.setRowCount(0); self.current_wordlist_path = None; self.file_list_widget.setCurrentItem(None); self.undo_stack.clear(); self.add_row()
    def save_wordlist(self):
        if any(len(widgets) > 1 for widgets in self.id_widgets.values()): QMessageBox.warning(self, "保存失败", "存在重复的项目ID (已用红色高亮显示)。\n请修正后再保存。"); return
        if self.current_wordlist_path: self._write_to_file(self.current_wordlist_path)
        else: self.save_wordlist_as()
    def save_wordlist_as(self):
        if any(len(widgets) > 1 for widgets in self.id_widgets.values()):
            QMessageBox.warning(self, "保存失败", "存在重复的项目ID (已用红色高亮显示)。\n请修正后再保存。")
            return
        
        # [修改] 文件过滤器和默认扩展名
        filepath, _ = QFileDialog.getSaveFileName(self, "另存为图文词表", WORD_LIST_DIR_FOR_DIALECT_VISUAL, "JSON 文件 (*.json)")
        if filepath:
            if not filepath.lower().endswith('.json'):
                filepath += '.json'
            self._write_to_file(filepath)
            self.current_wordlist_path = filepath
            self.refresh_file_list()
            for i in range(self.file_list_widget.count()):
                if self.file_list_widget.item(i).text() == os.path.basename(filepath):
                    self.file_list_widget.setCurrentRow(i)
                    break
    def _write_to_file(self, filepath):
        items_list = []
        for row in range(self.table_widget.rowCount()):
            item_data = {}
            id_item = self.table_widget.item(row, 0)
            
            # 跳过没有ID的行
            if not id_item or not id_item.text().strip():
                continue

            image_item = self.table_widget.item(row, 1)
            image_path = image_item.data(Qt.EditRole) if image_item else ''

            item_data['id'] = id_item.text().strip()
            item_data['image_path'] = image_path.strip() if image_path else ""
            item_data['prompt_text'] = self.table_widget.item(row, 2).text().strip() if self.table_widget.item(row, 2) else ''
            item_data['notes'] = self.table_widget.item(row, 3).text().strip() if self.table_widget.item(row, 3) else ''
            items_list.append(item_data)
        
        # 构建最终的 JSON 结构
        final_data_structure = {
            "meta": {
                "format": "visual_wordlist",
                "version": "1.0",
                "author": "PhonAcq Assistant",
                "save_date": datetime.now().isoformat()
            },
            "items": items_list
        }

        try:
            # 使用 json.dump 写入文件
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(final_data_structure, f, indent=4, ensure_ascii=False)
            
            self.undo_stack.setClean()
            QMessageBox.information(self, "成功", f"图文词表已成功保存至:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法保存文件:\n{e}")