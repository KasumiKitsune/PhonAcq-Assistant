# --- START OF FILE modules/dialect_visual_editor_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "图文词表编辑器"
MODULE_DESCRIPTION = "在程序内直接创建、编辑和保存用于“看图说话采集”的词表。"
# ---

import os
import sys
from datetime import datetime
import json
import shutil
import subprocess
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QShortcut, QUndoStack, QUndoCommand,
    QApplication, QMenu, QDialog, QGroupBox, QCheckBox, QFormLayout, QSlider, QDialogButtonBox, QToolTip
)
from modules.custom_widgets_module import AnimatedListWidget # [核心重构] 导入 AnimatedListWidget
from PyQt5.QtCore import Qt, QTimer, QRect, QSize, QEvent, QBuffer, QByteArray # [核心重构] 导入 QTimer, QRect, QSize
from PyQt5.QtGui import QKeySequence, QColor, QBrush, QIcon, QPalette, QPixmap # [核心重构] 导入 QPalette, QPixmap

# [核心重构] 导入 thefuzz 用于智能图片检测
try:
    from thefuzz import fuzz
except ImportError:
    class MockFuzz:
        def ratio(self, s1, s2):
            print("警告: thefuzz 库未安装，智能检测功能不可用。"); return 0
    fuzz = MockFuzz()

# 全局变量
WORD_LIST_DIR_FOR_DIALECT_VISUAL = ""

def get_base_path_for_module():
    """
    获取 PhonAcq Assistant 项目的根目录路径。
    此函数兼容程序被 PyInstaller 打包后运行和从源代码直接运行两种情况。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        # 当前文件位于 '项目根目录/modules/'，需要向上返回一级目录
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# 模块入口函数
def create_page(parent_window, word_list_dir_visual, ToggleSwitchClass, icon_manager):
    global WORD_LIST_DIR_FOR_DIALECT_VISUAL
    WORD_LIST_DIR_FOR_DIALECT_VISUAL = word_list_dir_visual
    return DialectVisualEditorPage(parent_window, ToggleSwitchClass, icon_manager)
class DroppableTableWidget(QTableWidget):
    def __init__(self, parent_page):
        super().__init__(parent_page)
        self.parent_page = parent_page
        self.setAcceptDrops(True)
        
        # 1. 启用鼠标跟踪，这是让 mouseMoveEvent 生效的关键
        self.setMouseTracking(True)

    def mouseMoveEvent(self, event):
        """
        当鼠标在表格上移动时实时触发。这是实现精确悬停效果的核心。
        """
        # --- [核心修改] 增加“守卫”逻辑 ---
        # 1. 从配置中读取 tooltip 是否启用
        module_states = self.parent_page.config.get("module_states", {}).get("dialect_visual_editor", {})
        tooltip_enabled = module_states.get("show_image_tooltip", True) # 默认启用

        # 2. 如果未启用，则确保隐藏任何可能的 tooltip 并立即返回
        if not tooltip_enabled:
            QToolTip.hideText()
            super().mouseMoveEvent(event)
            return
        # --- [修改结束] ---

        # 3. 如果已启用，则执行原有的预览逻辑
        pos = event.pos()
        item = self.itemAt(pos)

        if item and item.column() == 1:
            image_path_relative = item.data(Qt.EditRole)
            if image_path_relative:
                if self.parent_page.current_wordlist_path:
                    base_dir = os.path.dirname(self.parent_page.current_wordlist_path)
                else:
                    base_dir = WORD_LIST_DIR_FOR_DIALECT_VISUAL
                
                full_image_path = os.path.join(base_dir, image_path_relative)

                if os.path.exists(full_image_path):
                    tooltip_html = self.parent_page._tooltip_for_image(full_image_path)
                    QToolTip.showText(self.viewport().mapToGlobal(pos), tooltip_html, self)
                    return

        QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        """
        当鼠标离开整个表格控件时触发。
        """
        # 确保在鼠标离开时，Tooltip一定会被隐藏。
        QToolTip.hideText()
        super().leaveEvent(event)

    # --- 以下是拖放功能的代码，保持不变 ---
    def dragEnterEvent(self, event):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            supported_formats = ('.png', '.jpg', '.jpeg', '.webp')
            if any(url.isLocalFile() and url.toLocalFile().lower().endswith(supported_formats) for url in mime_data.urls()):
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        """
        [v3.0 - 规范化重命名版]
        当图片被释放时触发。此版本实现了将图片物理复制并重命名为与“项目ID”
        关联的规范化名称的完整工作流。
        """
        if not self.parent_page.current_wordlist_path:
            QMessageBox.warning(self.parent_page, "操作无效", "请先加载或保存一个词表，以便为图片创建专属存放目录。")
            event.ignore(); return
            
        item = self.itemAt(event.pos())
        if not (item and item.column() == 1):
            event.ignore(); return

        target_row = item.row()
        
        urls = event.mimeData().urls()
        supported_formats = ('.png', '.jpg', '.jpeg', '.webp')
        image_paths = [url.toLocalFile() for url in urls if url.isLocalFile() and url.toLocalFile().lower().endswith(supported_formats)]
        if not image_paths:
            event.ignore(); return

        wordlist_dir = os.path.dirname(self.parent_page.current_wordlist_path)
        wordlist_name_no_ext = os.path.splitext(os.path.basename(self.parent_page.current_wordlist_path))[0]
        destination_folder = os.path.join(wordlist_dir, wordlist_name_no_ext)
        os.makedirs(destination_folder, exist_ok=True)

        self.parent_page.undo_stack.beginMacro("拖入并重命名图片")

        for i, source_path in enumerate(image_paths):
            current_target_row = target_row + i
            if current_target_row >= self.rowCount() - 1: break
            
            # --- [核心重命名逻辑] ---
            # 1. 获取目标行的项目ID
            id_item = self.item(current_target_row, 0)
            item_id = id_item.text().strip() if id_item and id_item.text().strip() else None
            
            # 2. 获取原始文件的扩展名
            _, extension = os.path.splitext(source_path)
            
            # 3. 构建新的规范化文件名
            if item_id:
                # 如果ID存在，新文件名为 "[ID].[扩展名]"
                new_filename = f"{item_id}{extension}"
            else:
                # 如果ID为空，安全回退到使用原始文件名
                new_filename = os.path.basename(source_path)
            # --- [重命名逻辑结束] ---

            destination_path = os.path.join(destination_folder, new_filename)

            if os.path.exists(destination_path):
                # [核心修改] 将 new_filename 传递给冲突处理器
                final_dest_path = self._handle_file_conflict(destination_path, proposed_filename=new_filename)
                if final_dest_path is None: continue
                if final_dest_path == 'cancel_all': break
                destination_path = final_dest_path
            
            try:
                shutil.copy2(source_path, destination_path)
            except Exception as e:
                QMessageBox.critical(self.parent_page, "复制失败", f"无法将图片 '{os.path.basename(source_path)}' 复制到目标文件夹。\n\n错误: {e}"); continue

            new_relative_path = os.path.relpath(destination_path, wordlist_dir).replace("\\", "/")
            
            old_item = self.item(current_target_row, 1)
            old_text = old_item.data(Qt.EditRole) if old_item else ""
            
            cmd = ChangeCellCommand(self.parent_page, current_target_row, 1, old_text, new_relative_path, "拖入图片")
            self.parent_page.undo_stack.push(cmd)

        self.parent_page.undo_stack.endMacro()
        event.acceptProposedAction()

    def _handle_file_conflict(self, dest_path, proposed_filename):
        """
        [v2.0 - 增强版] 当目标文件名已存在时，弹出对话框让用户决策。
        
        Args:
            dest_path (str): 完整的目标文件路径。
            proposed_filename (str): 用于在对话框中显示的、我们想要创建的文件名。
        
        Returns:
            str or None: 返回最终有效的目标路径；如果用户选择跳过，则返回 None；
                         如果用户选择全部取消，则返回 'cancel_all'。
        """
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("文件冲突")
        # [核心修改] 使用 proposed_filename 提供更清晰的上下文
        msg_box.setText(f"目标文件名 '{proposed_filename}' 已存在于文件夹中。")
        msg_box.setInformativeText("您想如何操作？")
        msg_box.setIcon(QMessageBox.Question)

        overwrite_btn = msg_box.addButton("覆盖", QMessageBox.DestructiveRole)
        rename_btn = msg_box.addButton("重命名后复制", QMessageBox.AcceptRole)
        skip_btn = msg_box.addButton("跳过此文件", QMessageBox.RejectRole)
        cancel_all_btn = msg_box.addButton("取消所有", QMessageBox.RejectRole)
        
        msg_box.setDefaultButton(rename_btn)
        msg_box.exec_()
        
        clicked_button = msg_box.clickedButton()

        if clicked_button == overwrite_btn:
            return dest_path
        elif clicked_button == rename_btn:
            base, ext = os.path.splitext(dest_path)
            i = 1
            while True:
                new_path = f"{base}_copy_{i}{ext}"
                if not os.path.exists(new_path):
                    return new_path
                i += 1
        elif clicked_button == cancel_all_btn:
            return 'cancel_all'
        else:
            return None
# --- QUndoCommand 类 ---
class ChangeCellCommand(QUndoCommand):
    """撤销/重做单个表格单元格内容变化的命令。"""
    def __init__(self, editor, row, col, old_text, new_text, description):
        super().__init__(description)
        self.editor = editor
        self.table = editor.table_widget
        self.row, self.col = row, col
        self.old_text, self.new_text = old_text, new_text

    def _set_text(self, text):
        item = self.table.item(self.row, self.col)
        if not item:
            item = QTableWidgetItem()
            self.table.setItem(self.row, self.col, item)
        
        # 对于图片文件列，实际存储完整路径在 EditRole，显示 basename 在 DisplayRole
        if self.col == 1:
            item.setData(Qt.DisplayRole, os.path.basename(text))
            item.setData(Qt.EditRole, text)
        else:
            item.setText(text)
        
        # 如果是ID列，需要重新验证所有ID的唯一性
        if self.col == 0:
            self.editor.validate_all_ids()

    def redo(self):
        """执行重做操作：将单元格内容设为新文本。"""
        self.editor._is_programmatic_change = True
        self._set_text(self.new_text)
        self.editor._is_programmatic_change = False

    def undo(self):
        """执行撤销操作：将单元格内容恢复为旧文本。"""
        self.editor._is_programmatic_change = True
        self._set_text(self.old_text)
        self.editor._is_programmatic_change = False

class RowOperationCommand(QUndoCommand):
    """撤销/重做表格行添加、删除或移动的命令。"""
    def __init__(self, editor, start_row, rows_data, operation_type, move_offset=0, description=""):
        super().__init__(description)
        self.editor = editor
        self.table = editor.table_widget
        self.start_row, self.rows_data = start_row, rows_data
        self.type = operation_type # 'add', 'remove', 'move'
        self.move_offset = move_offset

    def _insert_rows(self, at_row, data):
        """辅助方法：在指定位置插入多行数据。"""
        for i, row_data in enumerate(data):
            self.table.insertRow(at_row + i)
            self.editor.populate_row(at_row + i, row_data)
        self.editor.validate_all_ids()

    def _remove_rows(self, at_row, count):
        """辅助方法：从指定位置移除多行。"""
        for _ in range(count):
            self.table.removeRow(at_row)
        self.editor.validate_all_ids()

    def redo(self):
        """执行重做操作。"""
        self.editor._is_programmatic_change = True # [核心] 加锁
        self.editor._remove_placeholder_row() # 移除占位符行
        self.table.blockSignals(True)
        if self.type == 'remove':
            self._remove_rows(self.start_row, len(self.rows_data))
        elif self.type == 'add':
            self._insert_rows(self.start_row, self.rows_data)
        elif self.type == 'move':
            self._remove_rows(self.start_row, len(self.rows_data))
            self._insert_rows(self.start_row + self.move_offset, self.rows_data)
        self.table.blockSignals(False)
        self.editor._add_placeholder_row() # 重新添加占位符行
        self.editor._is_programmatic_change = False # [核心] 解锁

    def undo(self):
        """执行撤销操作。"""
        self.editor._is_programmatic_change = True # [核心] 加锁
        self.editor._remove_placeholder_row() # 移除占位符行
        self.table.blockSignals(True)
        if self.type == 'remove':
            self._insert_rows(self.start_row, self.rows_data)
        elif self.type == 'add':
            self._remove_rows(self.start_row, len(self.rows_data))
        elif self.type == 'move':
            self._remove_rows(self.start_row + self.move_offset, len(self.rows_data))
            self._insert_rows(self.start_row, self.rows_data)
        self.table.blockSignals(False)
        self.editor._add_placeholder_row() # 重新添加占位符行
        self.editor._is_programmatic_change = False # [核心] 解锁

# --- MetadataDialog 类 ---
class MetadataDialog(QDialog):
    """
    用于编辑图文词表元数据的独立对话框。
    允许用户修改词表的名称、作者、描述等信息。
    """
    def __init__(self, metadata, parent=None, icon_manager=None):
        super().__init__(parent)
        self.metadata = metadata
        self.icon_manager = icon_manager
        
        self.setWindowTitle("配置词表元数据")
        self.setMinimumWidth(500)
        self._init_ui()
        self.populate_table()

    def _init_ui(self):
        """构建对话框的用户界面。"""
        layout = QVBoxLayout(self)
        
        # --- [核心修复] 以下是 MetadataDialog 唯一需要的UI组件 ---
        
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["键 (Key)", "值 (Value)"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setToolTip("编辑词表的元信息。\n核心的 'format' 和 'version' 键不可编辑。")
        
        button_layout = QHBoxLayout()
        
        self.add_btn = QPushButton("添加元数据项")
        if self.icon_manager:
            self.add_btn.setIcon(self.icon_manager.get_icon("add_row"))
            
        self.remove_btn = QPushButton("移除选中项")
        if self.icon_manager:
            self.remove_btn.setIcon(self.icon_manager.get_icon("delete"))
        
        self.save_btn = QPushButton("保存")
        if self.icon_manager:
            self.save_btn.setIcon(self.icon_manager.get_icon("save"))
        self.save_btn.setDefault(True)

        button_layout.addWidget(self.add_btn)
        button_layout.addWidget(self.remove_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.save_btn)
        
        layout.addWidget(self.table)
        layout.addLayout(button_layout)
        
        # --- [核心修复] 连接此对话框自身的信号 ---
        self.add_btn.clicked.connect(self.add_item)
        self.remove_btn.clicked.connect(self.remove_item)
        self.save_btn.clicked.connect(self.accept)


    def populate_table(self, parent=None):
        """用传入的元数据填充表格。"""
        self.table.setRowCount(0)
        for key, value in self.metadata.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            key_item = QTableWidgetItem(key)
            
            # --- [核心修改] ---
            display_value = str(value) # 默认显示原始值
            if key == 'save_date':
                try:
                    # 尝试将 ISO 格式字符串解析为 datetime 对象
                    # fromisoformat 支持带有时区信息（如Z或+00:00）和微秒的格式
                    dt_object = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                    # 格式化为更友好的本地时间显示
                    display_value = dt_object.strftime('%Y-%m-%d %H:%M')
                except (ValueError, TypeError):
                    # 如果解析失败（例如值不是有效的日期字符串），则安全回退，显示原始值
                    pass 
            
            val_item = QTableWidgetItem(display_value)
            # --- [修改结束] ---
            
            # 核心键不可编辑
            if key in ['format', 'version', 'save_date']: # 将 save_date 也设为不可编辑
                key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
                val_item.setFlags(val_item.flags() & ~Qt.ItemIsEditable)

            self.table.setItem(row, 0, key_item)
            self.table.setItem(row, 1, val_item)
            
    def add_item(self):
        """在表格中添加一个空的新行，供用户输入键值对。"""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem("新键"))
        self.table.setItem(row, 1, QTableWidgetItem("新值"))

    def remove_item(self):
        """移除当前选中的行。"""
        current_row = self.table.currentRow()
        if current_row != -1:
            key_item = self.table.item(current_row, 0)
            if key_item and key_item.text() in ['format', 'version']:
                QMessageBox.warning(self, "操作禁止", f"核心元数据键 '{key_item.text()}' 不可删除。")
                return
            self.table.removeRow(current_row)

    def get_metadata(self):
        """从表格中收集数据并返回更新后的元数据字典。"""
        new_meta = {}
        for i in range(self.table.rowCount()):
            key_item = self.table.item(i, 0)
            val_item = self.table.item(i, 1)
            # 确保键不为空，避免添加空键
            if key_item and val_item and key_item.text().strip():
                new_meta[key_item.text().strip()] = val_item.text()
        return new_meta

class DialectVisualEditorPage(QWidget):
    """
    图文词表编辑器页面。
    允许用户创建、加载、编辑、保存 JSON 格式的图文词表。
    支持撤销/重做、自动图片检测、元数据编辑和自动保存。
    """
    ADD_NEW_ROW_ROLE = Qt.UserRole + 101 # [核心重构] 新增占位符行角色

    def __init__(self, parent_window, ToggleSwitchClass, icon_manager):
        super().__init__()
        self.parent_window = parent_window
        self.config = self.parent_window.config # [核心重构] 初始化对主配置的引用
        self.ToggleSwitch = ToggleSwitchClass
        self.icon_manager = icon_manager
        
        self.current_wordlist_path = None
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)
        self.old_text_before_edit = None
        self.id_widgets = {} # 用于存储ID列单元格的引用，方便高亮重复ID
        self._is_programmatic_change = False # [核心重构] 防止信号循环和无限撤销

        # [核心重构] 新增数据快照，用于“脏”状态检测
        self.original_data_snapshot = None
        
        # [新增] 自动保存定时器
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._perform_autosave)

        self._init_ui()
        self.setup_connections_and_shortcuts()
        self.update_icons()
        self.apply_layout_settings()
        self.refresh_file_list()
        self._apply_autosave_setting() # [新增] 应用初始自动保存设置

    def _init_ui(self):
        """构建页面的用户界面布局。"""
        main_layout = QHBoxLayout(self)

        # --- 左侧面板：文件列表和操作按钮 ---
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        
        left_layout.addWidget(QLabel("图文词表文件:"))
        
        # 1. 文件列表
        self.file_list_widget = AnimatedListWidget(icon_manager=self.icon_manager)
        self.file_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list_widget.setToolTip("所有可编辑的图文词表文件。\n右键单击可进行更多操作。")
        left_layout.addWidget(self.file_list_widget)

        # 2. 自动保存状态提示 (位于列表下方，新建按钮上方)
        self.autosave_status_container = QWidget()
        status_layout = QHBoxLayout(self.autosave_status_container)
        status_layout.setContentsMargins(5, 5, 5, 5)
        status_layout.setSpacing(5)
        status_layout.setAlignment(Qt.AlignCenter) # 居中对齐
        self.autosave_status_icon = QLabel()
        self.autosave_status_text = QLabel("")
        self.autosave_status_text.setObjectName("SubtleStatusLabel")
        status_layout.addWidget(self.autosave_status_icon)
        status_layout.addWidget(self.autosave_status_text)
        self.autosave_status_container.hide()
        left_layout.addWidget(self.autosave_status_container) # <-- 正确的位置

        # 3. 新建按钮 (位于提示下方)
        self.new_btn = QPushButton("新建图文词表")
        left_layout.addWidget(self.new_btn)
        
        # 4. 保存/另存为按钮 (位于最下方)
        file_btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("AccentButton")
        self.save_as_btn = QPushButton("另存为...")
        file_btn_layout.addWidget(self.save_btn)
        file_btn_layout.addWidget(self.save_as_btn)
        left_layout.addLayout(file_btn_layout)

        # --- 右侧面板 (此部分代码保持不变) ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.table_widget = DroppableTableWidget(self)
        self.table_widget.setColumnCount(4)
        self.table_widget.setHorizontalHeaderLabels(["项目ID (必须唯一)", "图片文件", "提示文字 (可选)", "备注 (可选)"])
        
        header = self.table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        
        self.table_widget.setColumnWidth(0, 250)
        self.table_widget.setColumnWidth(1, 250)
        
        table_btn_layout = QHBoxLayout()
        self.undo_btn = QPushButton("撤销")
        self.redo_btn = QPushButton("重做")
        
        self.auto_detect_btn = QPushButton("检测图片")
        self.smart_detect_switch = self.ToggleSwitch()
        self.smart_detect_switch.setToolTip("启用后，将忽略大小写、下划线和空格，\n并尝试为项目ID匹配最相似的图片名。\n(需要安装 thefuzz 库)")
        
        self.add_row_btn = QPushButton("添加行")
        self.remove_row_btn = QPushButton("移除")
        self.remove_row_btn.setObjectName("ActionButton_Delete")
        
        table_btn_layout.addWidget(self.undo_btn)
        table_btn_layout.addWidget(self.redo_btn)
        table_btn_layout.addSpacing(20)
        table_btn_layout.addWidget(self.auto_detect_btn)
        table_btn_layout.addWidget(QLabel("智能检测:"))
        table_btn_layout.addWidget(self.smart_detect_switch)
        table_btn_layout.addStretch()
        table_btn_layout.addWidget(self.add_row_btn)
        table_btn_layout.addWidget(self.remove_row_btn)
        
        right_layout.addWidget(self.table_widget)
        right_layout.addLayout(table_btn_layout)
        
        main_layout.addWidget(self.left_panel)
        main_layout.addWidget(right_panel, 1)

    def _tooltip_for_image(self, path):
        """
        [新增] 为图片文件生成高质量的缩略图 Tooltip。
        通过在 Python 中预先使用 Qt.SmoothTransformation 缩放图片，解决锯齿问题。
        """
        try:
            # 1. 加载原始图片到 QPixmap
            pixmap = QPixmap(path)
            if pixmap.isNull():
                return f"[无法加载图片: {os.path.basename(path)}]"

            # 2. 使用高质量算法，将图片平滑地缩放到适合 Tooltip 的宽度
            scaled_pixmap = pixmap.scaledToWidth(250, Qt.SmoothTransformation)

            # 3. 将高质量的缩略图转换为 Base64 Data URI
            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            buffer.open(QBuffer.WriteOnly)
            scaled_pixmap.save(buffer, "PNG")
            base64_data = byte_array.toBase64().data().decode()
            uri = f"data:image/png;base64,{base64_data}"

            # 4. 获取文件元信息
            try:
                stat = os.stat(path)
                size_str = f"{stat.st_size / 1024:.1f} KB" if stat.st_size >= 1024 else f"{stat.st_size} B"
            except FileNotFoundError:
                size_str = "未知大小"
            
            # 5. 构建最终的 HTML
            html = f"""
            <div style='max-width: 300px;'>
                <b>{os.path.basename(path)}</b><br>
                ({pixmap.width()}x{pixmap.height()}, {size_str})<hr>
                <img src='{uri}'>
            </div>
            """
            return html
        except Exception as e:
            return f"[图片预览失败: {e}]"

    # --- [核心重构] 新增的公开方法，用于打开设置页面 ---
    def open_settings_dialog(self):
        """
        [新增] 打开此模块的设置对话框，并在确认后请求刷新以应用设置。
        """
        # 1. 检查文件管理器插件是否可用
        file_manager_plugin = self.parent_window.plugin_manager.get_plugin_instance("com.phonacq.file_manager")
        is_plugin_available = file_manager_plugin is not None and hasattr(file_manager_plugin, 'move_to_trash')

        # 2. 实例化对话框，并传入插件可用状态
        dialog = SettingsDialog(self, file_manager_available=is_plugin_available)
        
        # 3. 如果用户点击 "OK"，则刷新整个模块
        if dialog.exec_() == QDialog.Accepted:
            self.parent_window.request_tab_refresh(self)

    def update_icons(self):
        """更新所有按钮和操作的图标。"""
        self.new_btn.setIcon(self.icon_manager.get_icon("new_file"))
        self.save_btn.setIcon(self.icon_manager.get_icon("save_2"))
        self.save_as_btn.setIcon(self.icon_manager.get_icon("save_as"))
        self.add_row_btn.setIcon(self.icon_manager.get_icon("add_row"))
        self.remove_row_btn.setIcon(self.icon_manager.get_icon("remove_row"))
        self.auto_detect_btn.setIcon(self.icon_manager.get_icon("auto_detect")) # auto_detect 图标

        # Undo/Redo 按钮图标
        self.undo_btn.setIcon(self.icon_manager.get_icon("undo"))
        self.redo_btn.setIcon(self.icon_manager.get_icon("redo"))
        
        # 更新 Undo/Redo 动作的图标
        self.undo_action.setIcon(self.icon_manager.get_icon("undo"))
        self.redo_action.setIcon(self.icon_manager.get_icon("redo"))

    def apply_layout_settings(self):
        """应用从全局配置中读取的UI布局设置。"""
        config = self.parent_window.config
        ui_settings = config.setdefault("ui_settings", {})
        
        # 应用侧边栏宽度
        width = ui_settings.get("editor_sidebar_width", 280)
        self.left_panel.setFixedWidth(width)
        
        # 获取列宽配置，如果不存在则使用默认值
        col_widths = ui_settings.get("visual_editor_col_widths", [200, 200, -1, -1])
        
        # 确保配置列表长度正确
        if len(col_widths) > 4:
            col_widths = col_widths[:4]
        
        # 应用所有列的宽度
        self.table_widget.setColumnWidth(0, col_widths[0])
        self.table_widget.setColumnWidth(1, col_widths[1])
        # 拉伸列不需要手动设置宽度，但保存时会保持-1标记

        # 将修正后的配置立即写回 settings.json 文件，以防不必要的 -1 保存
        if ui_settings.get("visual_editor_col_widths") != col_widths:
            ui_settings["visual_editor_col_widths"] = col_widths
            try:
                settings_file_path = os.path.join(get_base_path_for_module(), "config", "settings.json")
                with open(settings_file_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=4)
            except Exception as e:
                print(f"自动保存强制列宽设置失败: {e}", file=sys.stderr)

    def on_column_resized(self, logical_index, old_size, new_size):
        """
        当表格列大小被用户调整时，保存新的列宽到配置文件中。
        只保存 '项目ID' (0) 和 '图片文件' (1) 列的宽度，拉伸列不需保存具体宽度。
        """
        if logical_index not in [0, 1]:
            return
            
        config = self.parent_window.config
        current_widths = config.setdefault("ui_settings", {}).get("visual_editor_col_widths", [200, 200, -1, -1])
        
        if logical_index == 0:
            current_widths[0] = new_size
        elif logical_index == 1:
            current_widths[1] = new_size

        config.setdefault("ui_settings", {})["visual_editor_col_widths"] = current_widths
        
        try:
            settings_file_path = os.path.join(get_base_path_for_module(), "config", "settings.json")
            with open(settings_file_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"保存列宽设置失败: {e}", file=sys.stderr)

    # --- [核心重构] 刷新文件列表以支持 AnimatedListWidget ---
    def refresh_file_list(self):
        """
        [v2.0 - 层级感知版]
        扫描图文词表目录及其子目录，构建层级数据结构，并使用 AnimatedListWidget 显示。
        """
        if hasattr(self, 'parent_window'):
            self.apply_layout_settings()
            self.update_icons()

        base_dir = WORD_LIST_DIR_FOR_DIALECT_VISUAL
        if not (base_dir and os.path.exists(base_dir)):
            self.file_list_widget.setHierarchicalData([])
            return

        # 使用一个字典来按文件夹路径组织文件
        folder_map = {}
        root_files = []

        try:
            # 使用 os.walk 遍历所有子目录
            for root, _, files in os.walk(base_dir):
                for filename in files:
                    if not filename.endswith('.json'):
                        continue
                    
                    full_path = os.path.join(root, filename)
                    item_data = {
                        'type': 'item',
                        'text': filename,
                        'icon': self.icon_manager.get_icon("document"),
                        'data': {'path': full_path}
                    }
                    
                    if root == base_dir:
                        # 如果是根目录下的文件，直接添加到列表
                        root_files.append(item_data)
                    else:
                        # 如果是子目录下的文件，添加到 folder_map 中
                        if root not in folder_map:
                            folder_map[root] = []
                        folder_map[root].append(item_data)

            # --- 组装最终的层级数据 ---
            hierarchical_data = []
            
            # 1. 添加根目录下的文件 (排序后)
            root_files.sort(key=lambda x: x['text'])
            hierarchical_data.extend(root_files)

            # 2. 添加子文件夹及其内容 (排序后)
            for folder_path in sorted(folder_map.keys()):
                children = sorted(folder_map[folder_path], key=lambda x: x['text'])
                hierarchical_data.append({
                    'type': 'folder',
                    'text': os.path.basename(folder_path),
                    'icon': self.icon_manager.get_icon("folder"),
                    'children': children
                })
            
            # 对顶层项目进行最终排序 (文件夹总是在文件之前)
            hierarchical_data.sort(key=lambda x: (x['type'] != 'folder', x['text']))

            self.file_list_widget.setHierarchicalData(hierarchical_data)

        except Exception as e:
            print(f"Error refreshing visual file list: {e}", file=sys.stderr)
            QMessageBox.critical(self, "错误", f"扫描图文词表目录时发生错误: {e}")

    # --- 文件列表的上下文菜单和操作 ---
    def on_file_double_clicked(self, item):
        """
        当一个最终的文件项目被激活时（通过双击或回车），
        打开其元数据配置。
        """
        # 内部逻辑完全不变，因为 AnimatedListWidget 已经确保了
        # 只有 'item' 类型的项目才会触发这个信号。
        self._configure_metadata(item)

    def show_file_context_menu(self, position):
        """显示文件列表的右键上下文菜单。"""
        item = self.file_list_widget.itemAt(position)
        if not item: return

        self.file_list_widget.setCurrentItem(item)
        item_data = item.data(AnimatedListWidget.HIERARCHY_DATA_ROLE)
        if not item_data: return

        item_type = item_data.get('type')
        menu = QMenu(self.file_list_widget)
        
        if item_type == 'item':
            # 文件菜单
            config_action = menu.addAction(self.icon_manager.get_icon("settings"), "配置元数据...")
            menu.addSeparator()
            show_action = menu.addAction(self.icon_manager.get_icon("open_folder"), "在文件浏览器中显示")
            menu.addSeparator()
            duplicate_action = menu.addAction(self.icon_manager.get_icon("copy"), "创建副本")
            delete_action = menu.addAction(self.icon_manager.get_icon("delete"), "删除")
            
            action = menu.exec_(self.file_list_widget.mapToGlobal(position))
            if action == config_action: self._configure_metadata(item)
            elif action == show_action: self._show_in_explorer(item)
            elif action == duplicate_action: self._duplicate_file(item)
            elif action == delete_action: self._delete_file(item)

        # elif item_type == 'folder':
        #     # 图文词表模块目前不支持文件夹结构，这部分代码保留作为未来扩展的示例
        #     expand_action = menu.addAction(self.icon_manager.get_icon("open_folder"), "展开")
        #     action = menu.exec_(self.file_list_widget.mapToGlobal(position))
        #     if action == expand_action: self.file_list_widget._handle_item_activation(item)

    def _get_path_from_item(self, item):
        """[新增] 统一的辅助函数，从item安全地获取文件路径。"""
        if not item: return None
        item_data = item.data(AnimatedListWidget.HIERARCHY_DATA_ROLE)
        if item_data and item_data.get('type') == 'item':
            return item_data.get('data', {}).get('path')
        return None

    def _show_in_explorer(self, item):
        filepath = self._get_path_from_item(item)
        if not filepath or not os.path.exists(filepath):
            QMessageBox.warning(self, "文件不存在", "该文件可能已被移动或删除。")
            self.refresh_file_list()
            return
        try:
            if sys.platform == 'win32': subprocess.run(['explorer', '/select,', os.path.normpath(filepath)])
            elif sys.platform == 'darwin': subprocess.check_call(['open', '-R', filepath])
            else: subprocess.check_call(['xdg-open', os.path.dirname(filepath)])
        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"无法打开文件所在位置: {e}")

    def _duplicate_file(self, item):
        src_path = self._get_path_from_item(item)
        if not src_path or not os.path.exists(src_path):
            QMessageBox.warning(self, "文件不存在", "无法创建副本，源文件可能已被移动或删除。")
            self.refresh_file_list(); return
        
        base, ext = os.path.splitext(os.path.basename(src_path))
        
        # --- [核心修复] 使用源文件的目录，而不是全局根目录 ---
        dest_dir = os.path.dirname(src_path)
        
        dest_path = os.path.join(dest_dir, f"{base}_copy{ext}")
        i = 1
        while os.path.exists(dest_path):
            dest_path = os.path.join(dest_dir, f"{base}_copy_{i}{ext}")
            i += 1
        try:
            shutil.copy2(src_path, dest_path)
            self.refresh_file_list()
        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"无法创建副本: {e}")

    def _configure_metadata(self, item):
        """
        [新增] 打开元数据配置对话框并处理结果。
        """
        filepath = self._get_path_from_item(item)
        if not filepath: return
        try:
            with open(filepath, 'r', encoding='utf-8') as f: data = json.load(f)
            if 'meta' not in data: data['meta'] = {"format": "visual_wordlist", "version": "1.0"}
            dialog = MetadataDialog(data['meta'], self, self.icon_manager)
            if dialog.exec_() == QDialog.Accepted:
                data['meta'] = dialog.get_metadata()
                with open(filepath, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
                QMessageBox.information(self, "成功", f"文件 '{item.text()}' 的元数据已更新。")
                if filepath == self.current_wordlist_path:
                    # 更新当前数据快照，标记为干净
                    self.original_data_snapshot = self._build_data_from_table()
                    self.check_dirty_state()
        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"处理元数据时发生错误: {e}")

    def load_file_from_path(self, filepath):
        """公共API: 从外部（如文件管理器）加载一个指定路径的图文词表文件。"""
        filename = os.path.basename(filepath)
        items = self.file_list_widget.findItems(filename, Qt.MatchExactly)
        if items:
            self.file_list_widget.setCurrentItem(items[0])
        else:
            self.refresh_file_list() # 刷新列表以确保文件存在
            items = self.file_list_widget.findItems(filename, Qt.MatchExactly)
            if items:
                self.file_list_widget.setCurrentItem(items[0])
            else:
                QMessageBox.warning(self, "文件未找到", f"文件 '{filename}' 不在当前列表中，或无法加载。")

    # --- [核心重构] 文件加载和保存，包括“脏”状态处理 ---

    def _confirm_and_handle_dirty_state(self, previous_item):
        """
        [新增] 这是一个“守卫”函数。在状态切换前，检查并处理未保存的更改。
        
        Returns:
            bool: True 如果可以继续进行状态切换 (已保存或已丢弃)。
                  False 如果用户取消了操作，状态切换应被中止。
        """
        if not self.is_data_dirty() or not previous_item:
            return True # 如果数据是干净的，或者没有前一个项目，则直接允许继续

        # 从 item data 中安全地获取前一个文件的路径
        prev_data = previous_item.data(AnimatedListWidget.HIERARCHY_DATA_ROLE)
        previous_path = prev_data.get('data', {}).get('path') if prev_data and prev_data.get('type') == 'item' else None

        # 弹出对话框
        reply = QMessageBox.question(self, "未保存的更改",
                                     f"文件 '{previous_item.text().replace(' *', '')}' 有未保存的更改。\n\n您想先保存吗？",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                     QMessageBox.Cancel)

        if reply == QMessageBox.Save:
            if previous_path:
                self._write_to_file(previous_path)
                # 再次检查，如果保存后数据仍然是脏的（例如保存失败），则认为操作被取消
                if self.is_data_dirty():
                    return False 
                return True
            else:
                QMessageBox.warning(self, "保存失败", "无法确定要保存的文件路径。")
                return False # 无法确定路径，取消操作

        elif reply == QMessageBox.Discard:
            return True # 用户选择丢弃，允许继续

        elif reply == QMessageBox.Cancel:
            return False # 用户取消，中止操作
            
        return False # 默认情况下，中止操作

    def on_file_selected(self, current, previous):
        """
        [vFinal - 健壮版]
        处理文件列表中的选择变化。此版本采用两步逻辑，确保在任何情况下都不会崩溃：
        1. 首先处理“离开”前一个项目的逻辑（如果前一个是文件，则检查未保存的更改）。
        2. 然后处理“进入”当前项目的逻辑（如果当前是文件，则加载；如果是文件夹，则忽略）。
        """
        # --- 步骤 1: 处理离开 'previous' 项目 ---
        # 只有当上一个选中的确实是一个文件项时，我们才需要关心未保存的更改。
        if previous:
            prev_data = previous.data(AnimatedListWidget.HIERARCHY_DATA_ROLE)
            if prev_data and prev_data.get('type') == 'item':
                # 上一个项目是文件，调用“守卫”函数检查。
                can_proceed = self._confirm_and_handle_dirty_state(previous)
                
                if not can_proceed:
                    # 如果用户在对话框中选择了“取消”，则中止切换。
                    # 我们需要阻塞信号，手动将选择恢复到 'previous'，然后解除阻塞。
                    self.file_list_widget.blockSignals(True)
                    self.file_list_widget.setCurrentItem(previous)
                    self.file_list_widget.blockSignals(False)
                    return # 中断整个切换操作

        # --- 步骤 2: 处理进入 'current' 项目 ---
        # 如果代码执行到这里，意味着切换是允许的。

        # 清理上一个文件项可能存在的“*”标记。
        if previous and previous.text().endswith(" *"):
             previous.setText(previous.text()[:-2])

        if current:
            current_data = current.data(AnimatedListWidget.HIERARCHY_DATA_ROLE)
            # 只有当新选中的是文件时，才加载内容。
            if current_data and current_data.get('type') == 'item':
                self.current_wordlist_path = current_data.get('data', {}).get('path')
                self.load_file_to_table()
                self._apply_autosave_setting()
                self.check_dirty_state()
            # else:
                # 如果新选中的是文件夹或返回按钮，则什么都不做。
                # 编辑器将继续显示上一个文件的内容，直到用户选择另一个文件。
                # 这是预期的、安全的设计。
                pass
        else:
            # 如果没有当前选中项（例如，用户点击了列表的空白区域），
            # 则清空编辑器。
            self.current_wordlist_path = None
            self.original_data_snapshot = None
            self.table_widget.setRowCount(0)
            self._add_placeholder_row()
            self.undo_stack.clear()
            self.check_dirty_state()

    def load_file_to_table(self):
        """
        加载当前选中图文词表文件 (self.current_wordlist_path) 的内容到表格中。
        """
        # 增加文件存在性检查
        if not self.current_wordlist_path or not os.path.exists(self.current_wordlist_path):
            QMessageBox.information(self, "文件不存在", f"图文词表文件 '{os.path.basename(str(self.current_wordlist_path))}' 不存在，可能已被删除或移动。")
            self.current_wordlist_path = None
            self.original_data_snapshot = None # [核心重构] 重置快照
            self.table_widget.setRowCount(0)
            self._add_placeholder_row() # 重新添加占位符行
            self.undo_stack.clear()
            self.refresh_file_list() # 刷新列表以移除不存在的文件
            self.check_dirty_state() # 检查状态
            return

        self._is_programmatic_change = True # <--- 加锁    
        self.table_widget.blockSignals(True) # 阻止信号，避免在加载过程中触发 itemChanged
        self._remove_placeholder_row() # 移除旧的占位符行
        self.table_widget.setRowCount(0) # 清空现有表格内容
        
        try:
            with open(self.current_wordlist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 验证 JSON 文件结构
            if "meta" not in data or "items" not in data or not isinstance(data["items"], list):
                raise ValueError("JSON文件格式无效，缺少 'meta' 或 'items' 键，或 'items' 不是列表。")

            # [核心重构] 创建数据快照
            self.original_data_snapshot = []
            for item_data in data.get("items", []):
                self.original_data_snapshot.append({
                    "id": item_data.get("id", ""),
                    "image_path": item_data.get("image_path", ""),
                    "prompt_text": item_data.get("prompt_text", ""),
                    "notes": item_data.get("notes", "")
                })
            
            for row, item_data in enumerate(data.get("items", [])):
                self.table_widget.insertRow(row)
                self.populate_row(row, [
                    item_data.get('id', ''),
                    item_data.get('image_path', ''),
                    item_data.get('prompt_text', ''),
                    item_data.get('notes', '')
                ])
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # 加载失败时，重置快照
            self.original_data_snapshot = None
            QMessageBox.critical(self, "加载失败", f"无法解析JSON图文词表文件 '{os.path.basename(self.current_wordlist_path)}':\n{e}")
        finally:
            self.table_widget.blockSignals(False)
            self._is_programmatic_change = False # [核心] 先解锁
            self.undo_stack.clear() # [核心] 然后清空撤销栈，这会正确地发出 cleanChanged(True) 信号
            self._add_placeholder_row()
            self.validate_all_ids() # 加载后验证ID
            self.check_dirty_state() # 加载后立即检查一次状态（应为干净）

    def populate_row(self, row, data):
        """
        填充表格的指定行。
        :param row: 要填充的行号。
        :param data: 包含 [id, image_path, prompt_text, notes] 的列表。
        """
        self.table_widget.setItem(row, 0, QTableWidgetItem(data[0])) # ID

        # 图片文件列需要特殊处理，DisplayRole 存文件名，EditRole 存完整路径
        image_path_item = QTableWidgetItem()
        full_path = data[1]
        image_path_item.setData(Qt.DisplayRole, os.path.basename(full_path))
        image_path_item.setData(Qt.EditRole, full_path)
        self.table_widget.setItem(row, 1, image_path_item)

        self.table_widget.setItem(row, 2, QTableWidgetItem(data[2])) # 提示文字
        self.table_widget.setItem(row, 3, QTableWidgetItem(data[3])) # 备注

    # [新增] 创建“添加新行”的占位符行
    def _add_placeholder_row(self):
        """在表格末尾添加一个灰色的、可点击的“添加新行”占位符。"""
        current_rows = self.table_widget.rowCount()
        # 避免重复添加占位符行
        if current_rows > 0 and self.table_widget.item(current_rows - 1, 0) and \
           self.table_widget.item(current_rows - 1, 0).data(self.ADD_NEW_ROW_ROLE):
            return

        self.table_widget.insertRow(current_rows)

        # 创建第一列的特殊单元格
        add_item = QTableWidgetItem(" 点击此处添加新行...")
        add_item.setData(self.ADD_NEW_ROW_ROLE, True) # 设置特殊标记
        # 使用当前调色板的禁用文本颜色，确保主题兼容性
        add_item.setForeground(self.palette().color(QPalette.Disabled, QPalette.Text))
        add_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        # 将所有单元格设为不可编辑和不可选中
        flags = Qt.ItemIsEnabled # 仅允许启用，不允许选中和编辑
        add_item.setFlags(flags)

        self.table_widget.setItem(current_rows, 0, add_item)

        # 合并所有列，让提示文本横跨整行
        self.table_widget.setSpan(current_rows, 0, 1, self.table_widget.columnCount())

    def _remove_placeholder_row(self):
        """安全地移除“添加新行”的占位符行（如果存在）。"""
        last_row = self.table_widget.rowCount() - 1
        if last_row >= 0:
            item = self.table_widget.item(last_row, 0)
            if item and item.data(self.ADD_NEW_ROW_ROLE):
                self.table_widget.removeRow(last_row)

    def new_wordlist(self):
        """
        [已修复] 创建一个新的空图文词表。
        在执行前，必须自己调用“守卫”函数检查是否有未保存的更改。
        """
        # --- [核心修改] 在执行前调用“守卫” ---
        can_proceed = self._confirm_and_handle_dirty_state(self.file_list_widget.currentItem())
        if not can_proceed:
            return # 如果用户取消，则中止新建操作

        # --- 后续逻辑与之前类似，但更安全 ---
        self.undo_stack.setClean()
        previous_item = self.file_list_widget.currentItem()
        if previous_item and previous_item.text().endswith(" *"):
             previous_item.setText(previous_item.text()[:-2])
        
        self.file_list_widget.setCurrentItem(None)
        
        self.current_wordlist_path = None
        self.original_data_snapshot = None
        self.table_widget.setRowCount(0)
        self.undo_stack.clear()
        
        self.add_row() # 默认添加一个空行
        self.original_data_snapshot = self._build_data_from_table() # 标记为干净
        self.check_dirty_state()

    def _delete_file(self, item):
        """
        [v2.0 - 重构版]
        启动文件删除流程。首先检查未保存的更改，然后将删除请求传递给 _request_delete_wordlist 方法处理。
        """
        filepath = self._get_path_from_item(item)
        if not filepath: return
        
        # 1. 删除前的“守卫”：检查被删除的文件是否就是当前正在编辑且有未保存更改的文件
        if self.is_data_dirty() and filepath == self.current_wordlist_path:
            reply = QMessageBox.question(self, "警告", 
                                         f"文件 '{os.path.basename(filepath)}' 有未保存的更改。\n\n"
                                         "如果继续删除，这些更改将丢失。是否继续？",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return # 用户取消删除，中止操作

        # 2. [核心修改] 将实际的删除操作委托给新的请求处理方法
        self._request_delete_wordlist(filepath)

    def _request_delete_wordlist(self, filepath):
        """
        [v2.1 - 文件夹同步版]
        处理单个图文词表文件的删除请求。
        根据用户设置决定是移入回收站还是永久删除，并同步删除其关联的图片文件夹。
        """
        if not filepath:
            return

        # --- [核心新增] 1. 计算关联的图片文件夹路径 ---
        wordlist_dir = os.path.dirname(filepath)
        wordlist_name_no_ext = os.path.splitext(os.path.basename(filepath))[0]
        image_folder_path = os.path.join(wordlist_dir, wordlist_name_no_ext)
        
        # --- 2. 准备要删除的路径列表 ---
        paths_to_delete = [filepath]
        # 只有当图片文件夹确实存在时，才将其加入待删除列表
        if os.path.isdir(image_folder_path):
            paths_to_delete.append(image_folder_path)

        # 3. 从配置中读取用户首选的删除方式
        module_states = self.config.get("module_states", {}).get("dialect_visual_editor", {})
        use_recycle_bin_preference = module_states.get("use_recycle_bin", True)

        # 4. 尝试获取文件管理器插件实例
        file_manager_plugin = self.parent_window.plugin_manager.get_plugin_instance("com.phonacq.file_manager")
        is_plugin_available = file_manager_plugin and hasattr(file_manager_plugin, 'move_to_trash')

        delete_successful = False

        # 5. 决策逻辑：只有在用户首选且插件可用时，才使用回收站
        if use_recycle_bin_preference and is_plugin_available:
            # --- 方案A: 使用插件的回收站功能 ---
            # [核心修改] 将包含文件和文件夹的整个列表传递给插件
            success, message = file_manager_plugin.move_to_trash(paths_to_delete)
            if success:
                delete_successful = True
            else:
                QMessageBox.critical(self, "移至回收站失败", message)
        else:
            # --- 方案B: 回退到永久删除 ---
            # [核心修改] 更新确认对话框的文本
            items_desc = f"文件 '{os.path.basename(filepath)}'"
            if len(paths_to_delete) > 1:
                items_desc += f" 及其关联的图片文件夹"
            
            reply = QMessageBox.question(self, "确认永久删除",
                                         f"您确定要永久删除 {items_desc} 吗？\n此操作不可撤销！",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    # [核心修改] 遍历并删除所有路径
                    for path in paths_to_delete:
                        if os.path.isfile(path):
                            os.remove(path)
                        elif os.path.isdir(path):
                            shutil.rmtree(path) # 使用 shutil.rmtree 删除文件夹
                    delete_successful = True
                except Exception as e:
                    QMessageBox.critical(self, "删除失败", f"删除文件或文件夹时出错: {e}")

        # 6. 如果删除成功，则更新UI (此部分逻辑保持不变)
        if delete_successful:
            if filepath == self.current_wordlist_path:
                self.current_wordlist_path = None
                self.original_data_snapshot = None
                self.table_widget.setRowCount(0)
                self._add_placeholder_row()
                self.undo_stack.clear()
                self.check_dirty_state()
            self.refresh_file_list()

    def save_wordlist(self):
        """保存当前图文词表。如果未曾保存过，则调用另存为。"""
        if any(len(widgets) > 1 for widgets in self.id_widgets.values()):
            QMessageBox.warning(self, "保存失败", "存在重复的项目ID (已用红色高亮显示)。\n请修正后再保存。")
            return
        if self.current_wordlist_path:
            self._write_to_file(self.current_wordlist_path)
        else:
            self.save_wordlist_as()

    def save_wordlist_as(self):
        """将当前图文词表另存为新文件。"""
        if any(len(widgets) > 1 for widgets in self.id_widgets.values()):
            QMessageBox.warning(self, "保存失败", "存在重复的项目ID (已用红色高亮显示)。\n请修正后再保存。")
            return
        
        filepath, _ = QFileDialog.getSaveFileName(self, "另存为图文词表", WORD_LIST_DIR_FOR_DIALECT_VISUAL, "JSON 文件 (*.json)")
        if filepath:
            # 确保文件以 .json 结尾
            if not filepath.lower().endswith('.json'):
                filepath += '.json'
            
            self._write_to_file(filepath) # 写入文件
            self.current_wordlist_path = filepath # 更新当前文件路径
            self.refresh_file_list() # 刷新文件列表
            
            # 选中新保存的文件
            items = self.file_list_widget.findItems(os.path.basename(filepath), Qt.MatchExactly)
            if items:
                self.file_list_widget.setCurrentItem(items[0])

    def _write_to_file(self, filepath, is_silent=False):
        """
        [v2.0 - 静默模式版]
        将表格中的数据转换为 JSON 格式并写入文件。
        :param filepath: 目标文件路径。
        :param is_silent: 如果为True，则不显示成功提示弹窗。
        """
        items_list = self._build_data_from_table()
        
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
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(final_data_structure, f, indent=4, ensure_ascii=False)
            
            self.original_data_snapshot = self._build_data_from_table()
            self.undo_stack.setClean() # 标记撤销栈为干净状态
            self.check_dirty_state() # 更新UI的脏状态指示
            
            # 只有在非静默模式下才显示弹窗
            if not is_silent:
                QMessageBox.information(self, "成功", f"图文词表已成功保存至:\n{filepath}")

        except Exception as e:
            # 无论如何，保存失败的弹窗总是要显示的
            QMessageBox.critical(self, "保存失败", f"无法保存文件:\n{e}")

    def _build_data_from_table(self):
        """
        [新增] 遍历当前表格，将其内容构建成一个与JSON文件结构相同的Python字典。
        这是进行“脏”状态比较的核心。
        """
        items_list = []
        # 遍历时要排除最后一行（占位符）
        for row in range(self.table_widget.rowCount() - 1):
            try:
                id_item = self.table_widget.item(row, 0)
                # 跳过没有ID的行，认为它们是无效行
                if not id_item or not id_item.text().strip():
                    continue

                image_item = self.table_widget.item(row, 1)
                # 从 EditRole 获取完整路径
                image_path = image_item.data(Qt.EditRole) if image_item else ''

                prompt_item = self.table_widget.item(row, 2)
                notes_item = self.table_widget.item(row, 3)

                items_list.append({
                    "id": id_item.text().strip(),
                    "image_path": image_path.strip() if image_path else "",
                    "prompt_text": prompt_item.text().strip() if prompt_item else "",
                    "notes": notes_item.text().strip() if notes_item else ""
                })
            except (ValueError, AttributeError):
                continue
        return items_list

    def is_data_dirty(self):
        """
        [vFinal] 通过比较当前表格数据快照和原始快照，权威地判断文件是否被修改。
        """
        if self.original_data_snapshot is None:
            # 对于一个从未保存过的新建文件 (snapshot为None)
            # 只要表格中有任何非空的 "项目ID"、"图片文件"、"提示文字"、"备注"，就认为是脏的。
            for row in range(self.table_widget.rowCount() - 1): # 排除占位符
                for col in range(self.table_widget.columnCount()):
                    item = self.table_widget.item(row, col)
                    if item:
                        # 对于图片路径，检查 EditRole
                        if col == 1:
                            if item.data(Qt.EditRole) and item.data(Qt.EditRole).strip():
                                return True
                        # 对于其他列，检查文本
                        else:
                            if item.text().strip():
                                return True
            return False # 所有行都是空的，认为是干净的

        current_data = self._build_data_from_table()
        return current_data != self.original_data_snapshot

    def check_dirty_state(self):
        """
        [修改] 检查当前的“脏”状态，并相应地更新UI及自动保存定时器。
        """
        is_dirty = self.is_data_dirty()
        self.save_btn.setEnabled(is_dirty)
        
        current_item = self.file_list_widget.currentItem()
        if not current_item:
            self.autosave_timer.stop() # 没有文件打开，停止定时器
            return

        current_text = current_item.text()
        has_indicator = current_text.endswith(" *")

        if is_dirty and not has_indicator:
            current_item.setText(f"{current_text} *")
        elif not is_dirty and has_indicator:
            current_item.setText(current_text[:-2])
            
        # --- [新增] 每次状态变化时，重新评估是否启动/停止定时器 ---
        self._apply_autosave_setting()

    # --- [核心重构] 自动保存逻辑 ---
    def _apply_autosave_setting(self):
        """
        [新增] 根据当前配置，启动或停止自动保存定时器。
        """
        module_states = self.config.get("module_states", {}).get("dialect_visual_editor", {})
        is_enabled = module_states.get("autosave_enabled", False)
        
        if is_enabled and self.current_wordlist_path and self.is_data_dirty():
            interval_minutes = module_states.get("autosave_interval_minutes", 15)
            interval_ms = interval_minutes * 60 * 1000
            self.autosave_timer.start(interval_ms)
        else:
            self.autosave_timer.stop()

    def _perform_autosave(self):
        """
        [v2.1 - 带图标版]
        定时器触发时执行的自动保存槽函数。
        保存成功后，在UI上显示一个带图标的、短暂的状态提示。
        """
        if self.current_wordlist_path and self.is_data_dirty():
            path_to_save = self.current_wordlist_path
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 自动保存 (图文): {os.path.basename(path_to_save)}")
            
            self._write_to_file(path_to_save, is_silent=True)

            if not self.is_data_dirty():
                icon = self.icon_manager.get_icon("success")
                pixmap = icon.pixmap(QSize(24, 24))
                self.autosave_status_icon.setPixmap(pixmap)
                time_str = datetime.now().strftime('%H:%M')
                self.autosave_status_text.setText(f"已于 {time_str} 自动保存")
                
                self.autosave_status_container.show()
                QTimer.singleShot(4000, self.autosave_status_container.hide)

    def setup_connections_and_shortcuts(self):
        """设置所有UI控件的信号槽连接和键盘快捷键。"""
        # 文件列表操作
        self.file_list_widget.item_activated.connect(self.on_file_double_clicked)
        self.file_list_widget.customContextMenuRequested.connect(self.show_file_context_menu)
        self.file_list_widget.currentItemChanged.connect(self.on_file_selected)
        
        # 文件操作按钮
        self.new_btn.clicked.connect(self.new_wordlist)
        self.save_btn.clicked.connect(self.save_wordlist)
        self.save_as_btn.clicked.connect(self.save_wordlist_as)

        # 表格行操作按钮
        self.add_row_btn.clicked.connect(lambda: self.add_row())
        self.remove_row_btn.clicked.connect(self.remove_row)
        self.auto_detect_btn.clicked.connect(self.auto_detect_images)
        
        # 单元格编辑与撤销/重做
        self.table_widget.itemPressed.connect(self.on_item_pressed) # 在单元格开始编辑前记录旧值
        self.table_widget.itemChanged.connect(self.on_item_changed_for_undo) # 在单元格内容改变后推送到撤销栈
        self.table_widget.itemChanged.connect(self._resize_row_on_change) # 新增连接
        self.table_widget.cellDoubleClicked.connect(self.on_cell_double_clicked) # 图片列双击打开文件选择
        self.table_widget.cellClicked.connect(self.on_cell_clicked) # 用于处理占位符行点击
        # 表格右键菜单
        self.table_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_widget.customContextMenuRequested.connect(self.show_context_menu)
        
        # [核心重构] 将所有可能导致“脏”状态变化的信号，都连接到一个统一的状态检查函数
        self.undo_stack.indexChanged.connect(self.check_dirty_state) # 任何撤销/重做都会触发
        self.table_widget.itemChanged.connect(self.check_dirty_state) # 任何单元格编辑都会触发

        # 撤销/重做按钮和快捷键
        self.undo_action = self.undo_stack.createUndoAction(self, "撤销")
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.redo_action = self.undo_stack.createRedoAction(self, "重做")
        self.redo_action.setShortcut(QKeySequence.Redo)
        
        # 将撤销/重做动作添加到页面，使其可以通过快捷键触发
        self.addAction(self.undo_action)
        self.addAction(self.redo_action)
        
        # 连接撤销/重做按钮到动作
        self.undo_btn.clicked.connect(self.undo_action.trigger)
        self.redo_btn.clicked.connect(self.redo_action.trigger)
        
        # 撤销/重做按钮的启用/禁用状态
        self.undo_stack.canUndoChanged.connect(self.undo_btn.setEnabled)
        self.undo_stack.canRedoChanged.connect(self.redo_btn.setEnabled)
        self.undo_btn.setEnabled(False) # 初始禁用
        self.redo_btn.setEnabled(False) # 初始禁用

        # 其他页面级快捷键
        QShortcut(QKeySequence.Save, self, self.save_wordlist)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, self.save_wordlist_as)
        QShortcut(QKeySequence.New, self, self.new_wordlist)
        
        # 剪贴板操作快捷键
        QShortcut(QKeySequence.Copy, self, self.copy_selection)
        QShortcut(QKeySequence.Cut, self, self.cut_selection)
        QShortcut(QKeySequence.Paste, self, self.paste_selection)
        
        # 行操作快捷键
        QShortcut(QKeySequence("Ctrl+D"), self, self.duplicate_rows)
        QShortcut(QKeySequence(Qt.ALT | Qt.Key_Up), self, lambda: self.move_rows(-1)) # Alt+Up 向上移动
        QShortcut(QKeySequence(Qt.ALT | Qt.Key_Down), self, lambda: self.move_rows(1)) # Alt+Down 向下移动
        QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Minus), self, self.remove_row) # Ctrl+- 删除行
        
        # 表头列宽调整信号
        self.table_widget.horizontalHeader().sectionResized.connect(self.on_column_resized)

    def _resize_row_on_change(self, item):
        """
        [新增] 当单元格内容改变时，自动调整行高以适应内容。
        """
        if item and not self._is_programmatic_change:
            # 调用 resizeRowsToContents 会检查所有行，确保布局正确
            self.table_widget.resizeRowsToContents()

    def keyPressEvent(self, event):
        """
        重写键盘按下事件，处理 Delete/Backspace 键清空内容。
        """
        if (event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace) and self.table_widget.selectedItems():
            self.clear_selection_contents()
            event.accept() # 标记事件已处理
        else:
            super().keyPressEvent(event) # 其他键传递给基类

    def on_item_pressed(self, item):
        """
        在单元格内容即将被编辑前触发，记录其旧文本用于撤销。
        对于图片文件，记录 EditRole 的完整路径。
        """
        if item:
            # 对于图片路径，记录 EditRole 的数据，否则记录文本
            if item.column() == 1:
                self.old_text_before_edit = item.data(Qt.EditRole)
            else:
                self.old_text_before_edit = item.text()

    def on_item_changed_for_undo(self, item):
        # [核心修复] 只有在不是程序性更改时才创建 Undo 命令
        if self._is_programmatic_change:
            return
            
        # 排除占位符行
        if item and item.data(self.ADD_NEW_ROW_ROLE):
            return

        # 获取新文本/新数据
        if item.column() == 1:
            new_data = item.data(Qt.EditRole) # 图片路径获取 EditRole
        else:
            new_data = item.text()

        if self.old_text_before_edit is not None and \
           self.old_text_before_edit != new_data:
            
            cmd = ChangeCellCommand(self, item.row(), item.column(), self.old_text_before_edit, new_data, "修改单元格")
            self.undo_stack.push(cmd)
            
            if item.column() == 0: # 如果是ID列，验证唯一性
                self.validate_all_ids()
        
        self.old_text_before_edit = None

    def validate_all_ids(self):
        """
        遍历所有行，检查“项目ID”列的唯一性，并高亮重复项。
        """
        self.id_widgets.clear() # 清空旧的ID缓存
        self.table_widget.blockSignals(True) # 阻止信号，避免在设置背景色时触发 itemChanged

        # 收集所有ID及其对应的单元格
        # 遍历时排除最后一行（占位符）
        for row in range(self.table_widget.rowCount() - 1): 
            item = self.table_widget.item(row, 0) # 获取ID列的单元格
            if item:
                item_text = item.text().strip()
                if not item_text: # 空ID不参与重复检查，但会保留高亮
                    continue
                if item_text not in self.id_widgets:
                    self.id_widgets[item_text] = []
                self.id_widgets[item_text].append(item)

        # 遍历并设置背景色
        for row in range(self.table_widget.rowCount() - 1):
            item = self.table_widget.item(row, 0)
            if item:
                item_text = item.text().strip()
                is_duplicate = item_text and len(self.id_widgets.get(item_text, [])) > 1
                
                # 使用当前主题的背景色作为正常颜色
                normal_bg_color = self.palette().color(QPalette.Base)
                
                if is_duplicate:
                    item.setBackground(QBrush(QColor("#FFCCCC"))) # 红色背景表示重复
                else:
                    item.setBackground(QBrush(normal_bg_color)) # 恢复正常背景色

        self.table_widget.blockSignals(False) # 解除信号阻止

    def show_context_menu(self, position):
        """显示表格的右键上下文菜单。"""
        menu = QMenu(self.file_list_widget) # 菜单属于文件列表，但用于表格操作
        selection = self.table_widget.selectedRanges() # 获取当前选中的区域

        # 剪贴板操作
        cut_action = menu.addAction(self.icon_manager.get_icon("cut"), "剪切 (Ctrl+X)")
        cut_action.setToolTip("剪切选中的单元格内容。")
        copy_action = menu.addAction(self.icon_manager.get_icon("copy"), "复制 (Ctrl+C)")
        copy_action.setToolTip("复制选中的单元格内容。")
        paste_action = menu.addAction(self.icon_manager.get_icon("paste"), "粘贴 (Ctrl+V)")
        paste_action.setToolTip("将剪贴板内容粘贴到当前位置。")
        
        menu.addSeparator()

        # 行级操作
        duplicate_action = menu.addAction(self.icon_manager.get_icon("duplicate_row"), "创建副本/重制行 (Ctrl+D)")
        duplicate_action.setToolTip("复制选中行并插入到下方。")
        
        menu.addSeparator()
        
        add_row_action = menu.addAction(self.icon_manager.get_icon("add_row"), "在下方插入新行")
        add_row_action.setToolTip("在当前选中行下方插入一个新行。")
        remove_row_action = menu.addAction(self.icon_manager.get_icon("remove_row"), "删除选中行")
        remove_row_action.setToolTip("删除表格中所有选中的行。")
        
        menu.addSeparator()
        
        clear_contents_action = menu.addAction(self.icon_manager.get_icon("clear_contents"), "清空内容 (Delete)")
        clear_contents_action.setToolTip("清空选中单元格中的内容。")
        
        menu.addSeparator()
        
        move_up_action = menu.addAction(self.icon_manager.get_icon("move_up"), "上移选中行 (Alt+Up)")
        move_up_action.setToolTip("将选中的行向上移动一个位置。")
        move_down_action = menu.addAction(self.icon_manager.get_icon("move_down"), "下移选中行 (Alt+Down)")
        move_down_action.setToolTip("将选中的行向下移动一个位置。")
        
        # 根据是否有选中区域禁用/启用剪贴板和清空操作
        if not selection:
            cut_action.setEnabled(False)
            copy_action.setEnabled(False)
            clear_contents_action.setEnabled(False)
        
        # 执行选中的动作
        action = menu.exec_(self.table_widget.mapToGlobal(position))
        
        if action == cut_action:
            self.cut_selection()
        elif action == copy_action:
            self.copy_selection()
        elif action == paste_action:
            self.paste_selection()
        elif action == duplicate_action:
            self.duplicate_rows()
        elif action == add_row_action:
            current_row = self.table_widget.currentRow()
            # 在当前行下方添加，如果无选中行则添加到末尾
            self.add_row(current_row + 1 if current_row != -1 else self.table_widget.rowCount())
        elif action == remove_row_action:
            self.remove_row()
        elif action == clear_contents_action:
            self.clear_selection_contents()
        elif action == move_up_action:
            self.move_rows(-1)
        elif action == move_down_action:
            self.move_rows(1)

    def on_cell_clicked(self, row, column):
        """
        当一个单元格被单击时，如果它是“添加新行”占位符，则添加一个新行。
        """
        item = self.table_widget.item(row, 0) # 总是检查第一列的 item
        
        # 检查是否是“添加新行”的占位符
        if item and item.data(self.ADD_NEW_ROW_ROLE):
            # 在占位符行的位置添加一个真正的新行
            self.add_row(at_row=row)
            return # 处理完毕，直接返回

    def on_cell_double_clicked(self, row, column):
        """
        双击图片文件列时，打开文件选择对话框。
        """
        if column != 1: return # 只处理图片文件列 (索引1)
        
        if not self.current_wordlist_path:
            QMessageBox.warning(self, "操作无效", "请先加载或保存图文词表，以确定图片文件的基准路径。")
            return

        # 获取当前词表所在的目录，并构建图片文件夹路径
        wordlist_dir = os.path.dirname(self.current_wordlist_path)
        wordlist_name = os.path.splitext(os.path.basename(self.current_wordlist_path))[0]
        image_folder = os.path.join(wordlist_dir, wordlist_name)
        
        # 确保图片文件夹存在，如果不存在则创建
        os.makedirs(image_folder, exist_ok=True)

        filepath, _ = QFileDialog.getOpenFileName(self, "选择图片文件", image_folder, "图片文件 (*.png *.jpg *.jpeg)")
        if filepath:
            try:
                # 尝试获取相对于词表所在目录的相对路径
                # 如果图片在词表同级目录下，或者同名子文件夹内，则生成相对路径
                relative_path = os.path.relpath(filepath, wordlist_dir)
                display_path = relative_path.replace("\\", "/") # 统一路径分隔符
            except ValueError:
                # 如果图片在其他地方，则只保存文件名
                display_path = os.path.basename(filepath)
            
            old_item = self.table_widget.item(row, 1)
            old_text = old_item.data(Qt.EditRole) if old_item else ""
            
            cmd = ChangeCellCommand(self, row, 1, old_text, display_path, "选择图片文件")
            self.undo_stack.push(cmd)
            
    def _normalize_string(self, text):
        """标准化字符串，用于模糊匹配：转小写，移除下划线和空格。"""
        return text.lower().replace("_", "").replace(" ", "")

    def auto_detect_images(self):
        """
        自动检测词表中所有未指定图片路径的词条，并尝试根据ID匹配图片文件。
        """
        if not self.current_wordlist_path:
            QMessageBox.warning(self, "操作无效", "请先加载或保存图文词表。")
            return

        wordlist_dir = os.path.dirname(self.current_wordlist_path)
        wordlist_name = os.path.splitext(os.path.basename(self.current_wordlist_path))[0]
        image_folder = os.path.join(wordlist_dir, wordlist_name)
        
        if not os.path.isdir(image_folder):
            QMessageBox.information(self, "提示", f"未找到对应的图片文件夹:\n{image_folder}")
            return

        is_smart = self.smart_detect_switch.isChecked()
        detected_count = 0
        
        # 获取图片文件列表及其标准化名称
        image_files = [f for f in os.listdir(image_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
        # {标准化图片名（无后缀）: 原始图片文件名}
        norm_map = {self._normalize_string(os.path.splitext(f)[0]): f for f in image_files}
        
        used_images = set() # 记录已被匹配的图片，避免重复分配

        self.undo_stack.beginMacro("自动检测图片")
        try:
            # 遍历表格中的每一行 (排除占位符行)
            for row in range(self.table_widget.rowCount() - 1):
                id_item = self.table_widget.item(row, 0)
                image_item = self.table_widget.item(row, 1)

                # 只处理有ID但没有图片路径的项
                if id_item and id_item.text().strip() and (not image_item or not image_item.data(Qt.EditRole).strip()):
                    item_id = id_item.text().strip()
                    best_match_filename = None

                    if not is_smart:
                        # 简单模式：精确匹配文件名 (不区分大小写，尝试常见后缀)
                        for ext in ['.png', '.jpg', '.jpeg', '.webp']:
                            potential_filename = item_id + ext
                            if os.path.exists(os.path.join(image_folder, potential_filename)):
                                best_match_filename = potential_filename
                                break
                    else:
                        # 智能模式：模糊匹配
                        norm_id = self._normalize_string(item_id)
                        best_score = 0
                        best_norm_name = None

                        for norm_name, original_filename in norm_map.items():
                            if original_filename in used_images: # 忽略已被使用的图片
                                continue
                            
                            score = fuzz.ratio(norm_id, norm_name)
                            if score > best_score:
                                best_score = score
                                best_norm_name = norm_name
                        
                        # 设置一个阈值，避免误匹配
                        if best_score >= 70 and best_norm_name:
                            best_match_filename = norm_map[best_norm_name]
                            used_images.add(best_match_filename) # 标记为已使用
                    
                    if best_match_filename:
                        # 构造相对路径，如 "my_wordlist/image.png"
                        relative_path = os.path.join(wordlist_name, best_match_filename).replace("\\", "/")
                        old_text = image_item.data(Qt.EditRole) if image_item else ""
                        cmd = ChangeCellCommand(self, row, 1, old_text, relative_path, "自动填充图片路径")
                        self.undo_stack.push(cmd)
                        detected_count += 1
        finally:
            self.undo_stack.endMacro()
        
        QMessageBox.information(self, "检测完成", f"成功检测并填充了 {detected_count} 个图片文件。" if detected_count > 0 else "没有找到可以自动填充的新图片文件。")

    # --- 剪贴板和行操作逻辑 ---

    def get_selected_rows_indices(self):
        """获取当前表格中所有选中行的索引列表，并按升序排序。"""
        # 使用 set 避免重复行，然后转换为 list 并排序
        selected_rows = sorted(list(set(index.row() for index in self.table_widget.selectedIndexes())))
        # 过滤掉占位符行
        if selected_rows and self.table_widget.item(selected_rows[-1], 0) and \
           self.table_widget.item(selected_rows[-1], 0).data(self.ADD_NEW_ROW_ROLE):
            selected_rows.pop()
        return selected_rows

    def _get_rows_data(self, row_indices):
        """
        获取指定行索引的完整数据。
        :param row_indices: 要获取数据的行索引列表。
        :return: 包含每行数据的列表的列表。
        """
        data = []
        for row in row_indices:
            row_data = []
            for col in range(self.table_widget.columnCount()):
                item = self.table_widget.item(row, col)
                if item:
                    # 对于图片文件列，获取 EditRole 的完整路径
                    if col == 1:
                        row_data.append(item.data(Qt.EditRole) or "")
                    else:
                        row_data.append(item.text())
                else:
                    row_data.append("")
            data.append(row_data)
        return data

    def clear_selection_contents(self):
        """清空所有选中单元格的内容。"""
        selected_items = self.table_widget.selectedItems()
        if not selected_items:
            return
        
        self.undo_stack.beginMacro("清空内容") # 开启宏操作
        for item in selected_items:
            # 排除占位符行
            if item and item.data(self.ADD_NEW_ROW_ROLE):
                continue

            # 根据列类型获取旧值和设置新值
            old_value = None
            if item.column() == 1:
                old_value = item.data(Qt.EditRole)
            else:
                old_value = item.text()

            if old_value: # 只有当有旧内容时才创建撤销命令
                cmd = ChangeCellCommand(self, item.row(), item.column(), old_value, "", "清空单元格")
                self.undo_stack.push(cmd)
        self.undo_stack.endMacro() # 结束宏操作

    def cut_selection(self):
        """剪切选中的单元格内容。"""
        self.copy_selection() # 先复制
        self.clear_selection_contents() # 再清空

    def copy_selection(self):
        """
        复制选中的单元格内容到系统剪贴板。
        内容以制表符分隔，行为换行符分隔。
        """
        selection = self.table_widget.selectedRanges()
        if not selection:
            return
        
        # 获取选中行的索引和选中列的索引
        rows = sorted(list(set(index.row() for index in self.table_widget.selectedIndexes())))
        # 过滤掉占位符行
        if rows and self.table_widget.item(rows[-1], 0) and self.table_widget.item(rows[-1], 0).data(self.ADD_NEW_ROW_ROLE):
            rows.pop()
        
        cols = sorted(list(set(index.column() for index in self.table_widget.selectedIndexes())))
        
        table_str_rows = []
        for r in rows:
            row_data = []
            for c in cols:
                item = self.table_widget.item(r, c)
                if item:
                    # 对于图片文件列，复制 EditRole 的完整路径
                    if c == 1:
                        row_data.append(item.data(Qt.EditRole) or "")
                    else:
                        row_data.append(item.text())
                else:
                    row_data.append("")
            table_str_rows.append("\t".join(row_data))
        
        table_str = "\n".join(table_str_rows)
        QApplication.clipboard().setText(table_str)

    def paste_selection(self):
        """将剪贴板内容粘贴到表格，稳健地处理新行创建。"""
        selection = self.table_widget.selectedRanges()
        start_row = selection[0].topRow() if selection else 0
        start_col = selection[0].leftColumn() if selection else 0

        text = QApplication.clipboard().text()
        rows_to_paste = text.strip('\n').split('\n')
        if not rows_to_paste: return

        self.undo_stack.beginMacro("粘贴")

        # 1. 预计算需要添加多少新行
        current_data_rows = self.table_widget.rowCount() - 1 # 减去占位符行
        required_rows = start_row + len(rows_to_paste)
        rows_to_add = required_rows - current_data_rows
        
        # 2. 如果需要，一次性添加所有新行
        if rows_to_add > 0:
            for i in range(rows_to_add):
                new_row_data = [["", "", "", ""]] # 默认空数据
                cmd = RowOperationCommand(self, current_data_rows + i, new_row_data, 'add', description="为粘贴添加行")
                self.undo_stack.push(cmd)

        # 3. 逐个单元格进行粘贴
        for i, row_text in enumerate(rows_to_paste):
            cells = row_text.split('\t')
            for j, cell_text in enumerate(cells):
                target_row, target_col = start_row + i, start_col + j
                # 确保粘贴位置在表格范围内，且不是占位符行
                if target_row < self.table_widget.rowCount() - 1 and target_col < self.table_widget.columnCount():
                    item = self.table_widget.item(target_row, target_col)
                    if not item: # 如果单元格不存在，创建它 (通常不会发生，因为前面已经添加了行)
                        item = QTableWidgetItem()
                        self.table_widget.setItem(target_row, target_col, item)
                    
                    old_value = None
                    if target_col == 1: # 图片路径
                        old_value = item.data(Qt.EditRole)
                        new_value = cell_text
                    else:
                        old_value = item.text()
                        new_value = cell_text
                    
                    if (old_value or "").strip() != new_value.strip():
                        cmd = ChangeCellCommand(self, target_row, target_col, old_value, new_value, "粘贴单元格")
                        self.undo_stack.push(cmd)
                            
        self.undo_stack.endMacro()

    def duplicate_rows(self):
        """[vFinal] 复制选中的行，并将其插入到选中行的下方。"""
        rows_to_duplicate = self.get_selected_rows_indices()
        if not rows_to_duplicate:
            # 如果没有显式选择，则检查当前焦点行
            current_focused_row = self.table_widget.currentRow()
            if current_focused_row != -1 and current_focused_row < self.table_widget.rowCount() -1: # 排除占位符行
                rows_to_duplicate = [current_focused_row]
            else:
                QMessageBox.information(self, "提示", "请先选择一个或多个要创建副本的行。")
                return
        
        rows_data = self._get_rows_data(rows_to_duplicate)
        
        # 添加 "_copy" 到 ID 以保持唯一性
        for row_data in rows_data:
            if row_data[0]: # 检查项目ID列 (索引0) 是否有值
                row_data[0] += "_copy"

        insert_at = rows_to_duplicate[-1] + 1
        
        cmd = RowOperationCommand(self, insert_at, rows_data, 'add', description="创建副本/重制行")
        self.undo_stack.push(cmd)

    def move_rows(self, offset):
        """
        移动选中行。
        :param offset: 移动的距离 (1 为向下，-1 为向上)。
        """
        selected_rows = self.get_selected_rows_indices()
        if not selected_rows:
            return
        
        # 边界检查 (考虑占位符行)
        if (offset == -1 and selected_rows[0] == 0) or \
           (offset == 1 and selected_rows[-1] >= self.table_widget.rowCount() - 2): # 倒数第二行是实际数据的最后一行
            return # 无法移动

        start_row = selected_rows[0]
        rows_data = self._get_rows_data(selected_rows) # 获取选中行的数据
        
        # 推送移动行的撤销命令
        cmd = RowOperationCommand(self, start_row, rows_data, 'move', offset, "移动行")
        self.undo_stack.push(cmd)
        
        # 移动后重新选中这些行
        self.table_widget.clearSelection() # 清除旧的选择
        new_start_row = start_row + offset
        for i in range(len(selected_rows)):
            self.table_widget.selectRow(new_start_row + i) # 选中新位置的行

    def add_row(self, at_row=None):
        """
        在指定位置添加一个新行。
        :param at_row: 插入行的索引。如果为 None，则添加到表格末尾（在占位符之前）。
        """
        # 在添加新行前移除占位符行
        self._remove_placeholder_row()

        if at_row is None:
            at_row = self.table_widget.rowCount() # 现在 rowCount() 是实际数据行数
        
        # 新行的数据
        new_row_data = [["", "", "", ""]] # 默认空数据
        
        cmd = RowOperationCommand(self, at_row, new_row_data, 'add', description="添加新行")
        self.undo_stack.push(cmd)
        
        # 在添加新行操作完成后，重新添加占位符行
        QApplication.processEvents() # 强制UI刷新，确保新行可见
        self._add_placeholder_row()
        
        # 滚动到新行并选中它
        self.table_widget.scrollToItem(self.table_widget.item(at_row, 0), QTableWidget.ScrollHint.EnsureVisible)
        self.table_widget.selectRow(at_row)
        
        # 自动选中并编辑第一列 (项目ID)
        self.table_widget.setCurrentCell(at_row, 0)
        self.table_widget.editItem(self.table_widget.item(at_row, 0))

    def remove_row(self):
        """移除所有选中的行。"""
        selected_rows = self.get_selected_rows_indices()
        if not selected_rows:
            QMessageBox.warning(self, "提示", "请先选择要移除的整行。")
            return
        
        rows_data = self._get_rows_data(selected_rows) # 获取选中行的数据用于撤销
        start_row = selected_rows[0] # 记录起始行索引
        
        cmd = RowOperationCommand(self, start_row, rows_data, 'remove', description="移除选中行")
        self.undo_stack.push(cmd)

# --- [核心新增] 与 wordlist_editor_module 对齐的设置对话框 ---
class SettingsDialog(QDialog):
    """
    一个专门用于配置“图文词表编辑器”模块的对话框。
    """
    def __init__(self, parent_page, file_manager_available):
        super().__init__(parent_page)
        
        self.parent_page = parent_page
        self.setWindowTitle("图文词表编辑器设置")
        self.setWindowIcon(self.parent_page.parent_window.windowIcon())
        self.setStyleSheet(self.parent_page.parent_window.styleSheet())
        self.setMinimumWidth(450)
        
        # 主布局
        layout = QVBoxLayout(self)
        
        # --- 组1: 自动保存 ---
        autosave_group = QGroupBox("自动保存")
        autosave_form_layout = QFormLayout(autosave_group)
        
        self.autosave_checkbox = QCheckBox("启用自动保存")
        self.autosave_checkbox.setToolTip("勾选后，编辑器将在指定的时间间隔内自动保存当前打开的文件。")
        
        autosave_interval_layout = QHBoxLayout()
        self.interval_slider = QSlider(Qt.Horizontal)
        self.interval_slider.setRange(1, 30) # 1到30分钟
        self.interval_slider.setToolTip("设置自动保存的时间间隔（分钟）。")
        self.interval_label = QLabel("15 分钟")
        self.interval_label.setFixedWidth(60)
        autosave_interval_layout.addWidget(self.interval_slider)
        autosave_interval_layout.addWidget(self.interval_label)
        
        autosave_form_layout.addRow(self.autosave_checkbox)
        autosave_form_layout.addRow("保存间隔:", autosave_interval_layout)
        
        layout.addWidget(autosave_group)

        # --- 组2: 文件操作 ---
        file_op_group = QGroupBox("文件操作")
        file_op_form_layout = QFormLayout(file_op_group)
        
        self.recycle_bin_checkbox = QCheckBox("删除时移至回收站")
        self.recycle_bin_checkbox.setToolTip("勾选后，删除的文件将进入回收站（如果可用）。\n取消勾选则会直接永久删除。")
        self.recycle_bin_checkbox.setEnabled(file_manager_available)
        if not file_manager_available:
            self.recycle_bin_checkbox.setToolTip("此选项需要 '文件管理器' 插件被启用。")
        file_op_form_layout.addRow(self.recycle_bin_checkbox)
        layout.addWidget(file_op_group)

        # --- [核心新增] 组3: 界面设置 ---
        ui_group = QGroupBox("界面设置")
        ui_form_layout = QFormLayout(ui_group)
        
        self.show_tooltip_checkbox = QCheckBox("鼠标悬停时显示图片预览")
        self.show_tooltip_checkbox.setToolTip("启用后，当鼠标悬停在“图片文件”单元格上时，会显示该图片的预览图。")
        
        ui_form_layout.addRow(self.show_tooltip_checkbox)
        layout.addWidget(ui_group)
        # --- [新增结束] ---
        
        # OK 和 Cancel 按钮
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        
        layout.addWidget(self.button_box)
        
        # 连接信号
        self.autosave_checkbox.toggled.connect(self.interval_slider.setEnabled)
        self.interval_slider.valueChanged.connect(lambda v: self.interval_label.setText(f"{v} 分钟"))
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        self.load_settings()

    def load_settings(self):
        """从主配置加载所有设置并更新UI。"""
        module_states = self.parent_page.config.get("module_states", {}).get("dialect_visual_editor", {})
        
        # 加载自动保存设置
        autosave_enabled = module_states.get("autosave_enabled", False)
        self.autosave_checkbox.setChecked(autosave_enabled)
        self.interval_slider.setValue(module_states.get("autosave_interval_minutes", 15))
        self.interval_slider.setEnabled(autosave_enabled)
        self.interval_label.setText(f"{self.interval_slider.value()} 分钟")
        
        # 加载删除方式设置
        self.recycle_bin_checkbox.setChecked(module_states.get("use_recycle_bin", True))
        self.show_tooltip_checkbox.setChecked(module_states.get("show_image_tooltip", True)) # 默认启用

    def save_settings(self):
        """将UI上的所有设置保存回主配置。"""
        main_window = self.parent_page.parent_window
        settings_to_save = {
            "autosave_enabled": self.autosave_checkbox.isChecked(),
            "autosave_interval_minutes": self.interval_slider.value(),
            "use_recycle_bin": self.recycle_bin_checkbox.isChecked(),
            "show_image_tooltip": self.show_tooltip_checkbox.isChecked(), # [核心新增] 保存新设置
        }
        
        current_settings = main_window.config.get("module_states", {}).get("dialect_visual_editor", {})
        current_settings.update(settings_to_save)
        main_window.update_and_save_module_state('dialect_visual_editor', current_settings)

    def accept(self):
        """重写 accept 方法，在关闭对话框前先保存设置。"""
        self.save_settings()
        super().accept()