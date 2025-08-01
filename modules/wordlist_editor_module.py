# --- START OF FILE modules/wordlist_editor_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "通用词表编辑器"
MODULE_DESCRIPTION = "在程序内直接创建、编辑和保存单词/词语列表。"
# ---

import os
import sys
from datetime import datetime
import json
import shutil
import subprocess
from modules.custom_widgets_module import AnimatedListWidget # 确保 AnimatedListWidget 正确导入
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QFileDialog, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QComboBox, QShortcut,
    QUndoStack, QUndoCommand, QApplication, QMenu, QDialog,
    QStyledItemDelegate, QTabWidget, QStyle # [核心新增] 导入 QStyledItemDelegate
)
from PyQt5.QtCore import Qt, QSize, QEvent, QTimer, QRect
from PyQt5.QtGui import QKeySequence, QIcon, QPainter, QFontMetrics, QPixmap, QPalette # [核心新增] 导入 QPainter, QFontMetrics, QPixmap

# --- 全局常量和辅助函数 ---

# 语言映射：用于语言选择下拉框的显示名称和 gTTS 语言代码
LANGUAGE_MAP = {
    "自动检测": "", "英语 (美国)": "en-us", "英语 (英国)": "en-uk", "中文 (普通话）": "zh-cn", "日语": "ja", "韩语": "ko",
    "法语 (法国)": "fr", "德语": "de", "西班牙语": "es", "葡萄牙语": "pt", "意大利语": "it", "俄语": "ru",
    "荷兰语": "nl", "波兰语": "pl", "土耳其语": "tr", "越南语": "vi", "印地语": "hi", "阿拉伯语": "ar", "泰语": "th", "印尼语": "id",
}

# 旗帜代码映射：用于根据语言代码选择对应的国家旗帜图标
FLAG_CODE_MAP = {
    "": "auto", "en-us": "us", "en-uk": "gb", "zh-cn": "cn", "ja": "jp", "ko": "kr", "fr": "fr", "de": "de", "es": "es", "pt": "pt",
    "it": "it", "ru": "ru", "nl": "nl", "pl": "pl", "tr": "tr", "vi": "vn", "hi": "in", "ar": "sa", "th": "th", "id": "id",
}

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

# --- 动态导入依赖 ---
# BasePlugin 的导入，确保插件系统能够找到
try:
    from plugin_system import BasePlugin
except ImportError:
    # 如果导入失败，将 'modules' 目录添加到 sys.path 以便找到 plugin_system.py
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'modules')))
    from plugin_system import BasePlugin

def create_page(parent_window, WORD_LIST_DIR, icon_manager, detect_language_func):
    """
    创建并返回词表编辑器页面的工厂函数。
    被主程序调用以实例化模块。
    """
    return WordlistEditorPage(parent_window, WORD_LIST_DIR, icon_manager, detect_language_func)

# ==============================================================================
# QUndoCommand - 撤销/重做操作定义
# ==============================================================================

class WordlistChangeCellCommand(QUndoCommand):
    """撤销/重做单个表格单元格内容变化的命令。"""
    def __init__(self, editor, row, col, old_text, new_text, description):
        super().__init__(description)
        self.editor = editor
        self.table = editor.table_widget
        self.row, self.col = row, col
        self.old_text, self.new_text = old_text, new_text
        
        # [核心修复] 在 __init__ 方法中正确定义 _id 属性
        self._id = 1001 

    def id(self):
        """返回命令的ID，用于合并连续的编辑操作。"""
        return self._id

    def mergeWith(self, other):
        """
        合并逻辑：如果新命令和当前命令是同一个类型，且操作的是同一个单元格，
        则将它们合并为一个操作，避免产生过多的撤销步骤。
        """
        if other.id() == self.id() and other.row == self.row and other.col == self.col:
            # 只更新最终的文本状态，保留最初的旧文本
            self.new_text = other.new_text
            return True
        return False

    def redo(self):
        """执行重做操作：将单元格内容设为新文本。"""
        self.editor._is_programmatic_change = True
        item = self.table.item(self.row, self.col)
        if not item:
            item = QTableWidgetItem()
            self.table.setItem(self.row, self.col, item)
        item.setText(self.new_text)
        self.editor._is_programmatic_change = False

    def undo(self):
        """执行撤销操作：将单元格内容恢复为旧文本。"""
        self.editor._is_programmatic_change = True
        item = self.table.item(self.row, self.col)
        if not item:
            item = QTableWidgetItem()
            self.table.setItem(self.row, self.col, item)
        item.setText(self.old_text)
        self.editor._is_programmatic_change = False


class WordlistChangeLanguageCommand(QUndoCommand):
    """撤销/重做语言选择下拉框变化的命令。"""
    def __init__(self, editor, row, old_lang_code, new_lang_code, description):
        super().__init__(description)
        self.editor = editor
        self.table = editor.table_widget
        self.row = row
        self.old_lang, self.new_lang = old_lang_code, new_lang_code

    def _set_language(self, lang_code):
        """辅助方法：设置指定行的语言下拉框值。"""
        self.editor._is_programmatic_change = True # [核心] 加锁
        
        item = self.table.item(self.row, 3)
        if item:
            item.setData(Qt.UserRole, lang_code)
            display_name = next((name for name, code in LANGUAGE_MAP.items() if code == lang_code), "自动检测")
            item.setText(display_name)
            
            model = self.table.model()
            if model:
                start_index = model.index(self.row, 3)
                model.dataChanged.emit(start_index, start_index)
        
        self.editor._is_programmatic_change = False # [核心] 解锁

    def redo(self):
        """执行重做操作：设置新语言。"""
        self._set_language(self.new_lang)

    def undo(self):
        """执行撤销操作：恢复旧语言。"""
        self._set_language(self.old_lang)

class WordlistRowOperationCommand(QUndoCommand):
    """撤销/重做表格行添加、删除或移动的命令。"""
    def __init__(self, editor, start_row, rows_data, operation_type, move_offset=0, description=""):
        super().__init__(description)
        self.editor = editor
        self.table = editor.table_widget
        self.start_row, self.rows_data = start_row, rows_data
        self.type = operation_type # 'add', 'remove', 'move'
        self.move_offset = move_offset

    def _insert_rows(self, at_row, data):
        """[重构] 辅助方法：在指定位置插入多行数据。"""
        for i, row_data in enumerate(data):
            self.table.insertRow(at_row + i)
            # [核心修复] 调用 populate_row 来正确地创建所有单元格和委托数据
            self.editor.populate_row(at_row + i, row_data)

    def _remove_rows(self, at_row, count):
        """辅助方法：从指定位置移除多行。"""
        for _ in range(count):
            self.table.removeRow(at_row)

    def redo(self):
        """执行重做操作。"""
        self.editor._is_programmatic_change = True # [核心] 加锁
        self.editor._remove_placeholder_row()
        
        self.table.blockSignals(True)
        if self.type == 'remove':
            self._remove_rows(self.start_row, len(self.rows_data))
        elif self.type == 'add':
            self._insert_rows(self.start_row, self.rows_data)
        elif self.type == 'move':
            self._remove_rows(self.start_row, len(self.rows_data))
            self._insert_rows(self.start_row + self.move_offset, self.rows_data)
        self.table.blockSignals(False)
        
        self.editor._add_placeholder_row()
        self.editor._is_programmatic_change = False # [核心] 解锁

    def undo(self):
        """执行撤销操作。"""
        self.editor._is_programmatic_change = True # [核心] 加锁
        self.editor._remove_placeholder_row()

        self.table.blockSignals(True)
        if self.type == 'remove':
            self._insert_rows(self.start_row, self.rows_data)
        elif self.type == 'add':
            self._remove_rows(self.start_row, len(self.rows_data))
        elif self.type == 'move':
            self._remove_rows(self.start_row + self.move_offset, len(self.rows_data))
            self._insert_rows(self.start_row, self.rows_data)
        self.table.blockSignals(False)

        self.editor._add_placeholder_row()
        self.editor._is_programmatic_change = False # [核心] 解锁

# ==============================================================================
# LanguageDelegate - 语言列的自定义委托
# ==============================================================================
class LanguageDelegate(QStyledItemDelegate):
    """
    一个专门用于绘制和编辑语言列的自定义委托。
    v1.1: 修复了文本与图标重叠绘制的BUG。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.icon_cache = {}
        base_path = get_base_path_for_module()
        flags_path = os.path.join(base_path, 'assets', 'flags')
        
        for code, flag_name in FLAG_CODE_MAP.items():
            icon_path = os.path.join(flags_path, f"{flag_name}.png")
            if os.path.exists(icon_path):
                self.icon_cache[code] = QIcon(icon_path)
            else:
                self.icon_cache[code] = QIcon()

    def paint(self, painter, option, index):
        """[重构] 绘制单元格的外观（非编辑状态），完全手动控制。"""
        painter.save()

        # 1. 绘制背景
        # [核心修复] 我们不再调用 super().paint()，而是自己处理背景绘制。
        if option.state & QStyle.State_Selected:
            # 如果是选中状态，使用高亮背景色填充
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            # 否则，使用正常的背景色（这通常是透明的，会显示出表格的隔行变色）
            painter.fillRect(option.rect, option.palette.base())

        # 2. 获取数据
        lang_code = index.model().data(index, Qt.UserRole) or ""
        display_name = next((name for name, code in LANGUAGE_MAP.items() if code == lang_code), "自动检测")
        icon = self.icon_cache.get(lang_code, self.icon_cache[""])

        # 3. 绘制图标
        icon_size = QSize(24, 18)
        # 垂直居中计算图标的Y坐标
        icon_y = option.rect.top() + (option.rect.height() - icon_size.height()) // 2
        icon_rect = QRect(option.rect.left() + 5, icon_y, icon_size.width(), icon_size.height())
        icon.paint(painter, icon_rect, Qt.AlignCenter)
        
        # 4. 绘制文本
        text_rect = option.rect.adjusted(34, 2, -5, -2) # 为文本留出边距

        # 根据选中状态决定文本颜色
        if option.state & QStyle.State_Selected:
            text_color = option.palette.highlightedText().color()
        else:
            text_color = option.palette.text().color()
        painter.setPen(text_color)
        
        # 计算省略号文本并绘制
        fm = QFontMetrics(painter.font())
        elided_text = fm.elidedText(display_name, Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_text)
        
        painter.restore()

    def createEditor(self, parent, option, index):
        """当用户开始编辑单元格时，创建 QComboBox 编辑器。"""
        editor = QComboBox(parent)
        editor.setIconSize(QSize(24, 18))
        for display_name, lang_code in LANGUAGE_MAP.items():
            editor.addItem(self.icon_cache.get(lang_code, self.icon_cache[""]), display_name, lang_code)
        
        # 确保编辑器在创建时就应用主题样式
        editor.setStyleSheet(self.parent().styleSheet())
        
        return editor

    def setEditorData(self, editor, index):
        """将模型中的数据设置到编辑器中。"""
        lang_code = index.model().data(index, Qt.UserRole) or ""
        idx = editor.findData(lang_code)
        if idx != -1:
            editor.setCurrentIndex(idx)

    def setModelData(self, editor, model, index):
        editor_page = self.parent()
        # [核心修复] 增加对程序性更改的检查
        if not isinstance(editor_page, WordlistEditorPage) or editor_page._is_programmatic_change:
            return

        new_lang_code = editor.currentData()
        old_lang_code = model.data(index, Qt.UserRole)
        
        if new_lang_code != old_lang_code:
            cmd = WordlistChangeLanguageCommand(editor_page, index.row(), old_lang_code, new_lang_code, "改变语言")
            editor_page.undo_stack.push(cmd)
            
        # [修改] 即使没有变化，也需要更新模型数据，因为用户可能只是重新选择了同一个值
        model.setData(index, new_lang_code, Qt.UserRole)
        model.setData(index, editor.currentText(), Qt.DisplayRole)

    def updateEditorGeometry(self, editor, option, index):
        """设置编辑器的位置和大小。"""
        editor.setGeometry(option.rect)

# ==============================================================================
# MetadataDialog - 词表元数据编辑对话框
# ==============================================================================

class MetadataDialog(QDialog):
    """
    用于编辑词表元数据的独立对话框。
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
        
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["键 (Key)", "值 (Value)"])
        # 伸展值列以填充可用空间
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch) 
        self.table.setToolTip("编辑词表的元信息。\n核心的 'format' 和 'version' 键不可编辑。")
        
        button_layout = QHBoxLayout() # 水平布局，容纳所有按钮
        
        self.add_btn = QPushButton("添加元数据项")
        if self.icon_manager:
            self.add_btn.setIcon(self.icon_manager.get_icon("add_row"))
            
        self.remove_btn = QPushButton("移除选中项")
        if self.icon_manager:
            self.remove_btn.setIcon(self.icon_manager.get_icon("delete"))
        
        self.save_btn = QPushButton("保存") # 新的保存按钮
        if self.icon_manager:
            self.save_btn.setIcon(self.icon_manager.get_icon("save"))
        self.save_btn.setDefault(True) # 让回车键默认触发此按钮

        # 将所有按钮添加到新的水平布局中
        button_layout.addWidget(self.add_btn)
        button_layout.addWidget(self.remove_btn)
        button_layout.addStretch() # 添加一个弹簧，将“保存”按钮推到右侧
        button_layout.addWidget(self.save_btn)
        
        layout.addWidget(self.table)
        layout.addLayout(button_layout) # 将新的按钮栏添加到主布局
        
        # 连接信号
        self.add_btn.clicked.connect(self.add_item)
        self.remove_btn.clicked.connect(self.remove_item)
        self.save_btn.clicked.connect(self.accept) # 将保存按钮连接到 QDialog 的 accept() 槽

    def populate_table(self):
        """用传入的元数据填充表格。"""
        self.table.setRowCount(0)
        for key, value in self.metadata.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            key_item = QTableWidgetItem(key)
            val_item = QTableWidgetItem(str(value))
            
            # 核心键 (如 format, version) 不可编辑
            if key in ['format', 'version']:
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

# ==============================================================================
# WordlistEditorPage - 词表编辑器主页面
# ==============================================================================

class WordlistEditorPage(QWidget):
    """
    通用词表编辑器页面。
    允许用户创建、加载、编辑、保存 JSON 格式的单词/词语列表。
    支持撤销/重做、语言自动检测和音频状态显示。
    """
    ADD_NEW_ROW_ROLE = Qt.UserRole + 100
    def __init__(self, parent_window, WORD_LIST_DIR, icon_manager, detect_language_func):
        super().__init__()
        self.parent_window = parent_window
        self.WORD_LIST_DIR = WORD_LIST_DIR
        self.icon_manager = icon_manager
        self.detect_language_func = detect_language_func

        self.current_wordlist_path = None
        self.old_text_before_edit = None

        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)
        self._is_programmatic_change = False
        
        # [核心重构] 新增一个属性，用于存储加载文件时的权威数据快照
        self.original_data_snapshot = None

        self.base_path = get_base_path_for_module()
        self.flags_path = os.path.join(self.base_path, 'assets', 'flags')
        self.tts_utility_hook = None

        # [核心修复] 将 language_delegate 的实例化移到 _init_ui() 调用之前
        self.language_delegate = LanguageDelegate(self)

        self._init_ui() # 现在调用 _init_ui() 是安全的
        self.setup_connections_and_shortcuts()
        self.update_icons()
        self.apply_layout_settings()
        self.refresh_file_list()

    def _init_ui(self):
        """构建页面的用户界面布局。"""
        main_layout = QHBoxLayout(self)

        # --- 左侧面板：文件列表和操作按钮 ---
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        
        left_layout.addWidget(QLabel("单词表文件:"))
        
        self.file_list_widget = AnimatedListWidget()
        
        self.file_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list_widget.setToolTip("所有可编辑的单词表文件。\n右键单击可进行更多操作。")
        left_layout.addWidget(self.file_list_widget)

        self.new_btn = QPushButton("新建单词表")
        left_layout.addWidget(self.new_btn)
        
        file_btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("AccentButton")
        self.save_as_btn = QPushButton("另存为...")
        file_btn_layout.addWidget(self.save_btn)
        file_btn_layout.addWidget(self.save_as_btn)
        left_layout.addLayout(file_btn_layout)

        # --- 右侧面板 ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(4) # 修改为4列
        self.table_widget.setHorizontalHeaderLabels(["组别", "单词/短语", "备注 (IPA)", "语言 (可选)"]) # 修改表头
        self.table_widget.setToolTip("在此表格中编辑单词/词语。") # 移除状态列描述
        
        # [新增] 将新的委托应用到第3列（语言列）
        self.table_widget.setItemDelegateForColumn(3, self.language_delegate)
        
        header = self.table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        
        self.table_widget.verticalHeader().setVisible(True)
        self.table_widget.setAlternatingRowColors(True)
        right_layout.addWidget(self.table_widget)

        table_btn_layout = QHBoxLayout()
        self.undo_btn = QPushButton("撤销")
        self.redo_btn = QPushButton("重做")
        self.auto_detect_lang_btn = QPushButton("自动检测语言")
        self.add_row_btn = QPushButton("添加行")
        self.remove_row_btn = QPushButton("移除选中行")
        self.remove_row_btn.setObjectName("ActionButton_Delete")
        
        table_btn_layout.addWidget(self.undo_btn)
        table_btn_layout.addWidget(self.redo_btn)
        table_btn_layout.addStretch()
        table_btn_layout.addWidget(self.auto_detect_lang_btn)
        table_btn_layout.addStretch()
        table_btn_layout.addWidget(self.add_row_btn)
        table_btn_layout.addWidget(self.remove_row_btn)
        
        right_layout.addLayout(table_btn_layout)

        main_layout.addWidget(self.left_panel)
        main_layout.addWidget(right_panel, 1)

    def load_file_from_path(self, filepath):
        """
        公共API: 从外部（如文件管理器）加载一个指定路径的词表文件。
        如果文件存在于列表中，则选中它；否则刷新列表后尝试再次查找。
        """
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

    def update_icons(self):
        """更新所有按钮和操作的图标。"""
        self.new_btn.setIcon(self.icon_manager.get_icon("new_file"))
        self.save_btn.setIcon(self.icon_manager.get_icon("save_2"))
        self.save_as_btn.setIcon(self.icon_manager.get_icon("save_as"))
        self.add_row_btn.setIcon(self.icon_manager.get_icon("add_row"))
        self.remove_row_btn.setIcon(self.icon_manager.get_icon("remove_row"))
        self.undo_btn.setIcon(self.icon_manager.get_icon("undo"))
        self.redo_btn.setIcon(self.icon_manager.get_icon("redo"))
        self.auto_detect_lang_btn.setIcon(self.icon_manager.get_icon("auto_detect"))
        
        # 撤销/重做操作的图标绑定到 QUndoStack 的 action 上
        self.undo_action.setIcon(self.icon_manager.get_icon("undo"))
        self.redo_action.setIcon(self.icon_manager.get_icon("redo"))

    def apply_layout_settings(self):
        """应用从全局配置中读取的UI布局设置，并强制状态列宽度为40。"""
        config = self.parent_window.config
        ui_settings = config.setdefault("ui_settings", {})
        
        # 应用侧边栏宽度
        width = ui_settings.get("editor_sidebar_width", 280)
        self.left_panel.setFixedWidth(width)
        
        # --- [核心修改] ---
        
        # 1. 获取列宽配置，如果不存在则使用默认值
        # [修改] 默认值中移除了第4列
        col_widths = ui_settings.get("wordlist_editor_col_widths", [80, -1, -1, 150])
        
        # [修改] 确保配置列表长度正确，以防旧配置残留
        if len(col_widths) > 4:
            col_widths = col_widths[:4]
        
        # 2. 应用所有列的宽度
        self.table_widget.setColumnWidth(0, col_widths[0])
        self.table_widget.setColumnWidth(3, col_widths[3])
        
        # 3. 将修正后的配置立即写回 settings.json 文件
        if ui_settings.get("wordlist_editor_col_widths") != col_widths:
            ui_settings["wordlist_editor_col_widths"] = col_widths
            try:
                settings_file_path = os.path.join(get_base_path_for_module(), "config", "settings.json")
                with open(settings_file_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=4)
            except Exception as e:
                print(f"自动保存强制列宽设置失败: {e}", file=sys.stderr)

    def on_column_resized(self, logical_index, old_size, new_size):
        """
        当表格列大小被用户调整时，保存新的列宽到配置文件中。
        只保存 '组别' (0), '语言' (3) 列的宽度，拉伸列不需保存具体宽度。
        """
        # 只有特定的列才需要保存其宽度
        if logical_index not in [0, 3]:
            return
            
        config = self.parent_window.config
        # 获取当前的列宽配置，如果不存在则使用默认值
        current_widths = config.setdefault("ui_settings", {}).get("wordlist_editor_col_widths", [80, -1, -1, 150])
        
        # 更新相应列的宽度
        if logical_index == 0:
            current_widths[0] = new_size
        elif logical_index == 3:
            current_widths[3] = new_size

        # 将更新后的宽度保存回配置
        config.setdefault("ui_settings", {})["wordlist_editor_col_widths"] = current_widths
        
        try:
            settings_file_path = os.path.join(get_base_path_for_module(), "config", "settings.json")
            with open(settings_file_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"保存列宽设置失败: {e}", file=sys.stderr)

    def refresh_file_list(self):
        """
        刷新左侧的词表文件列表。
        保留当前选中项，并在文件列表中重新排序。
        """
        if hasattr(self, 'parent_window'):
            self.apply_layout_settings()
            self.update_icons()

        current_selection = self.file_list_widget.currentItem().text() if self.file_list_widget.currentItem() else ""
        
        # 这里调用 clear() 方法，它已经被 AnimatedListWidget 覆盖，会安全地处理动画
        self.file_list_widget.clear()
        
        if os.path.exists(self.WORD_LIST_DIR):
            files = sorted([f for f in os.listdir(self.WORD_LIST_DIR) if f.endswith('.json')])
            
            # 调用新的动画填充方法
            self.file_list_widget.addItemsWithAnimation(files)
            
            # 尝试重新选中之前的文件
            if current_selection:
                for i in range(self.file_list_widget.count()):
                    if self.file_list_widget.item(i).text() == current_selection:
                        self.file_list_widget.setCurrentRow(i)
                        break

    def check_dirty_state(self):
        """
        [新增] 检查当前的“脏”状态，并相应地更新UI（保存按钮和“*”标记）。
        这是所有状态更新的唯一入口。
        """
        is_dirty = self.is_data_dirty()
        self.save_btn.setEnabled(is_dirty)
        
        current_item = self.file_list_widget.currentItem()
        if not current_item:
            return

        current_text = current_item.text()
        has_indicator = current_text.endswith(" *")

        if is_dirty and not has_indicator:
            current_item.setText(f"{current_text} *")
        elif not is_dirty and has_indicator:
            current_item.setText(current_text[:-2])

    def setup_connections_and_shortcuts(self):
        """设置所有UI控件的信号槽连接和键盘快捷键。"""
        # 文件列表操作
        self.file_list_widget.currentItemChanged.connect(self.on_file_selected)
        self.file_list_widget.itemDoubleClicked.connect(self.on_file_double_clicked)
        self.file_list_widget.customContextMenuRequested.connect(self.show_file_context_menu)
        
        # 文件操作按钮
        self.new_btn.clicked.connect(self.new_wordlist)
        self.save_btn.clicked.connect(self.save_wordlist)
        self.save_as_btn.clicked.connect(self.save_wordlist_as)

        # 表格行操作按钮
        self.add_row_btn.clicked.connect(lambda: self.add_row())
        self.remove_row_btn.clicked.connect(self.remove_row)
        
        # 单元格编辑与撤销/重做
        self.table_widget.itemPressed.connect(self.on_item_pressed) # 在单元格开始编辑前记录旧值
        self.table_widget.itemChanged.connect(self.on_item_changed_for_undo) # 在单元格内容改变后推送到撤销栈
        self.table_widget.cellClicked.connect(self.on_cell_single_clicked)
        # 表格右键菜单
        self.table_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_widget.customContextMenuRequested.connect(self.show_context_menu)
        
        # [核心重构] 将所有可能导致“脏”状态变化的信号，都连接到一个统一的状态检查函数
        self.undo_stack.indexChanged.connect(self.check_dirty_state) # 任何撤销/重做都会触发
        self.table_widget.itemChanged.connect(self.check_dirty_state) # 任何单元格编辑都会触发

        # 组别列滚轮事件过滤器 (用于快速增减组别号)
        self.table_widget.viewport().installEventFilter(self)

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
        
        # 自动检测语言按钮
        self.auto_detect_lang_btn.clicked.connect(self.auto_detect_languages)

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

    def auto_detect_languages(self):
        """
        [修正版] 自动检测词表中所有未指定语言的词条语言，并更新到表格中。
        """
        detected_count = 0
        self.undo_stack.beginMacro("自动检测语言")

        # [核心] 在整个循环外部加锁
        self._is_programmatic_change = True
        
        gtts_settings = self.parent_window.config.get("gtts_settings", {})
        default_lang = gtts_settings.get("default_lang", "en-us")

        # 遍历时要排除最后一行（占位符）
        for row in range(self.table_widget.rowCount() - 1):
            word_item = self.table_widget.item(row, 1)
            note_item = self.table_widget.item(row, 2)
            lang_item = self.table_widget.item(row, 3)
            if word_item and lang_item:
                current_lang = lang_item.data(Qt.UserRole)
                if current_lang == "":
                    text = word_item.text().strip()
                    note = note_item.text().strip() if note_item else ""
                    detected_lang = self.detect_language_func(text, note) or default_lang
                    if detected_lang != current_lang:
                        # 注意：这里创建的Command在执行时自己会加锁，所以这里是安全的
                        cmd = WordlistChangeLanguageCommand(self, row, current_lang, detected_lang, "自动填充语言")
                        self.undo_stack.push(cmd)
                        detected_count += 1
        
        # [核心] 在循环结束后解锁
        self._is_programmatic_change = False

        self.undo_stack.endMacro()
        QMessageBox.information(self, "检测完成", f"成功检测并填充了 {detected_count} 个词条的语言。")
    # --- 文件列表的上下文菜单和操作 ---

    def on_file_double_clicked(self, item):
        """双击文件列表项，在文件浏览器中显示该文件。"""
        self._show_in_explorer(item)

    def show_file_context_menu(self, position):
        item = self.file_list_widget.itemAt(position)
        if not item: return

        menu = QMenu(self.file_list_widget)
        
        config_action = menu.addAction(self.icon_manager.get_icon("settings"), "配置...")
        config_action.setToolTip("编辑词表的元数据，如作者、描述等。")
        menu.addSeparator()

        show_action = menu.addAction(self.icon_manager.get_icon("open_folder"), "在文件浏览器中显示")
        
        # [新增] 检查钩子是否存在，如果存在则添加“发送到TTS”菜单项
        if self.tts_utility_hook:
            menu.addSeparator()
            send_to_tts_action = menu.addAction(self.icon_manager.get_icon("tts"), "发送到TTS工具")
            send_to_tts_action.setToolTip("将此词表加载到TTS工具中进行批量转换。")
            send_to_tts_action.triggered.connect(lambda: self.send_to_tts(item))

        # 检查是否有分割器插件的钩子
        if hasattr(self, 'tts_splitter_plugin_active'):
            menu.addSeparator()
            splitter_action = menu.addAction(self.icon_manager.get_icon("cut"), "发送到批量分割器")
            splitter_action.triggered.connect(lambda: self.send_to_splitter(item))

        menu.addSeparator()
        duplicate_action = menu.addAction(self.icon_manager.get_icon("copy"), "创建副本")
        delete_action = menu.addAction(self.icon_manager.get_icon("delete"), "删除")
        
        action = menu.exec_(self.file_list_widget.mapToGlobal(position))

        if action == config_action:
            self._configure_metadata(item)
        elif action == show_action:
            self._show_in_explorer(item)
        elif action == duplicate_action:
            self._duplicate_file(item)
        elif action == delete_action:
            self._delete_file(item)

    def send_to_splitter(self, item):
        if not item: return
        splitter_plugin = getattr(self, 'tts_splitter_plugin_active', None)
        if splitter_plugin:
            # [核心修复] 清理文件名
            clean_filename = item.text().replace(" *", "")
            wordlist_path = os.path.join(self.WORD_LIST_DIR, clean_filename)
            splitter_plugin.execute(wordlist_path=wordlist_path)

    def _show_in_explorer(self, item):
        if not item: return
        
        # [核心修复] 清理文件名
        clean_filename = item.text().replace(" *", "")
        filepath = os.path.join(self.WORD_LIST_DIR, clean_filename)
        
        if not os.path.exists(filepath):
            QMessageBox.warning(self, "文件不存在", "该文件可能已被移动或删除。")
            self.refresh_file_list()
            return
        
        try:
            # 根据操作系统调用不同的命令打开文件浏览器并选中文件
            if sys.platform == 'win32':
                subprocess.run(['explorer', '/select,', os.path.normpath(filepath)])
            elif sys.platform == 'darwin':
                subprocess.check_call(['open', '-R', filepath])
            else: # Linux
                subprocess.check_call(['xdg-open', os.path.dirname(filepath)]) # Linux 通常只能打开文件夹
        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"无法打开文件所在位置: {e}")

    def _duplicate_file(self, item):
        """
        创建当前选中词表文件的副本。
        :param item: QListWidgetItem 实例，代表要复制的文件。
        """
        if not item:
            return
        clean_filename = item.text().replace(" *", "")
        src_path = os.path.join(self.WORD_LIST_DIR, clean_filename)
        
        if not os.path.exists(src_path):
            QMessageBox.warning(self, "文件不存在", "无法创建副本，源文件可能已被移动或删除。")
            self.refresh_file_list()
            return

        # 生成新的文件名，避免与现有文件冲突
        base, ext = os.path.splitext(clean_filename)
        dest_path = os.path.join(self.WORD_LIST_DIR, f"{base}_copy{ext}")
        i = 1
        while os.path.exists(dest_path):
            dest_path = os.path.join(self.WORD_LIST_DIR, f"{base}_copy_{i}{ext}")
            i += 1
        
        try:
            shutil.copy2(src_path, dest_path) # 复制文件，保留元数据
            self.refresh_file_list() # 刷新列表以显示新副本
        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"无法创建副本: {e}")

    def _delete_file(self, item):
        """
        [vFinal] 删除当前选中词表文件，并正确处理带有“*”标记的文件名。
        """
        if not item:
            return
            
        # [核心修复] 在构建路径前，先清理掉文件名末尾的“ *”
        clean_filename = item.text().replace(" *", "")
        filepath = os.path.join(self.WORD_LIST_DIR, clean_filename)
        
        # 使用清理后的文件名进行用户提示
        reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除文件 '{clean_filename}' 吗？\n此操作不可撤销。",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            try:
                os.remove(filepath) # 使用正确的文件路径进行删除
                
                # 如果删除的是当前正在编辑的文件，则清空UI
                if filepath == self.current_wordlist_path:
                    self.current_wordlist_path = None
                    self.original_data_snapshot = None
                    self.table_widget.setRowCount(0)
                    self._add_placeholder_row()
                    self.undo_stack.clear()
                    self.check_dirty_state()

                # 刷新文件列表
                self.refresh_file_list() 
            except Exception as e:
                QMessageBox.critical(self, "删除失败", f"无法删除文件: {e}")

    def _configure_metadata(self, item):
        if not item: return

        # [核心修复] 清理文件名
        clean_filename = item.text().replace(" *", "")
        filepath = os.path.join(self.WORD_LIST_DIR, clean_filename)
        
        try:
            # 1. 读取 JSON 文件内容
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 确保 'meta' 键存在，如果不存在则添加默认元数据
            if 'meta' not in data:
                data['meta'] = {"format": "standard_wordlist", "version": "1.0"}

            # 2. 创建并显示元数据编辑对话框
            dialog = MetadataDialog(data['meta'], self, self.icon_manager)
            if dialog.exec_() == QDialog.Accepted:
                # 3. 如果用户点击 "保存"，获取更新后的元数据
                updated_meta = dialog.get_metadata()
                data['meta'] = updated_meta
                
                # 4. 将更新后的完整数据结构写回文件
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                
                QMessageBox.information(self, "成功", f"文件 '{item.text()}' 的元数据已更新。")
                
                # 如果配置的是当前打开的文件，则刷新表格以反映任何元数据变化（尽管通常不会直接影响表格内容）
                if filepath == self.current_wordlist_path:
                    # [核心重构] 元数据修改不影响表格内容，但保存后应更新快照以反映文件实际状态
                    self.original_data_snapshot = self._build_data_from_table()
                    self.check_dirty_state()

        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"处理元数据时发生错误: {e}")

    # --- 文件加载和保存 ---

    def on_file_selected(self, current, previous):
        """
        当用户在文件列表中选择不同的文件时触发。
        检查是否有未保存的更改，并加载新文件。
        同时处理“脏”状态（*）标记的移除。
        """
        if previous and previous.text().endswith(" *"):
             previous.setText(previous.text()[:-2])

        # [核心重构] 使用 is_data_dirty() 进行判断
        if self.is_data_dirty() and previous:
            reply = QMessageBox.question(self, "未保存的更改", 
                                         f"文件 '{previous.text()}' 有未保存的更改。\n\n您想先保存吗？",
                                         QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                         QMessageBox.Cancel)
            
            if reply == QMessageBox.Save:
                previous_path = os.path.join(self.WORD_LIST_DIR, previous.text())
                self._write_to_file(previous_path)
                if self.is_data_dirty(): # 如果保存后仍然是脏的（例如保存失败）
                    self.check_dirty_state() # 重新加上星号
                    return
            
            elif reply == QMessageBox.Cancel:
                self.file_list_widget.currentItemChanged.disconnect(self.on_file_selected)
                self.file_list_widget.setCurrentItem(previous)
                self.file_list_widget.currentItemChanged.connect(self.on_file_selected)
                self.check_dirty_state() # 重新加上星号
                return
            
            # 如果是Discard，则不做任何事，继续向下执行

        if current:
            clean_filename = current.text().replace(" *", "")
            self.current_wordlist_path = os.path.join(self.WORD_LIST_DIR, clean_filename)
            self.load_file_to_table()
        else:
            self.current_wordlist_path = None
            self.original_data_snapshot = None
            self.table_widget.setRowCount(0)
            self._add_placeholder_row()
            self.undo_stack.clear()
            self.check_dirty_state()

    def load_file_to_table(self):
        """
        加载当前选中词表文件 (self.current_wordlist_path) 的内容到表格中。
        """
        # 增加文件存在性检查
        if not self.current_wordlist_path or not os.path.exists(self.current_wordlist_path):
            QMessageBox.information(self, "文件不存在", f"词表文件 '{os.path.basename(str(self.current_wordlist_path))}' 不存在，可能已被删除或移动。")
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
        self._remove_placeholder_row() # 移除旧的占位符行，再重新添加
        self.table_widget.setRowCount(0) # 清空现有表格内容
        
        try:
            with open(self.current_wordlist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 验证 JSON 文件结构
            if "meta" not in data or "groups" not in data or not isinstance(data["groups"], list):
                raise ValueError("JSON文件格式无效，缺少 'meta' 或 'groups' 键，或 'groups' 不是列表。")

            # [核心重构] 创建数据快照
            self.original_data_snapshot = []
            for group_data in data.get("groups", []):
                # 只复制必要的数据进行比较
                clean_group = {"id": group_data.get("id"), "items": []}
                for item_data in group_data.get("items", []):
                    clean_group["items"].append({
                        "text": item_data.get("text", ""),
                        "note": item_data.get("note", ""),
                        "lang": item_data.get("lang", "")
                    })
                self.original_data_snapshot.append(clean_group)
            
            row_index = 0
            for group_data in data["groups"]:
                group_id = group_data.get("id", "")
                items = group_data.get("items", [])
                if not isinstance(items, list):
                    continue # 跳过格式不正确的组

                for item_data in items:
                    text = item_data.get("text", "")
                    note = item_data.get("note", "")
                    lang = item_data.get("lang", "")
                    
                    self.table_widget.insertRow(row_index)
                    # 调用 populate_row 填充行，传递所有5列的数据，包括状态列的空位
                    self.populate_row(row_index, [str(group_id), text, note, lang]) # 传递4列数据
                    row_index += 1
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # 加载失败时，重置快照
            self.original_data_snapshot = None
            QMessageBox.critical(self, "加载失败", f"无法解析JSON词表文件 '{os.path.basename(self.current_wordlist_path)}':\n{e}")
        finally:
            self.table_widget.blockSignals(False)
            self._is_programmatic_change = False # [核心] 先解锁
            self.undo_stack.clear() # [核心] 然后清空撤销栈，这会正确地发出 cleanChanged(True) 信号
            self._add_placeholder_row()
            self.check_dirty_state() # 加载后立即检查一次状态（应为干净）

    def populate_row(self, row, data):
        """
        填充表格的指定行。
        :param row: 要填充的行号。
        :param data: 包含 [group_id, text, note, lang_code] 的列表。
        """
        # 设置 '组别', '单词/短语', '备注 (IPA)' 列
        self.table_widget.setItem(row, 0, QTableWidgetItem(data[0]))
        self.table_widget.setItem(row, 1, QTableWidgetItem(data[1]))
        self.table_widget.setItem(row, 2, QTableWidgetItem(data[2]))
        
        # 对于语言列，我们只创建 QTableWidgetItem 并设置数据
        lang_item = QTableWidgetItem()
        lang_code = data[3]
        
        # 显示文本可以是一个友好的名称，但委托的 paint 方法会覆盖它
        display_name = next((name for name, code in LANGUAGE_MAP.items() if code == lang_code), "自动检测")
        lang_item.setText(display_name)
        
        # 将真实的语言代码存储在 UserRole 中，这是委托将读取的数据源
        lang_item.setData(Qt.UserRole, lang_code)
        
        self.table_widget.setItem(row, 3, lang_item)

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
        add_item.setForeground(self.palette().color(QPalette.Disabled, QPalette.Text)) # 设置灰色文字
        add_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        # 将所有单元格设为不可编辑和不可选中
        flags = Qt.ItemIsEnabled
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
        [vFinal] 创建一个新的空单词表。
        在执行前，会检查当前文件是否有未保存的更改。
        """
        # --- 1. 检查是否有未保存的更改 (此逻辑保持不变) ---
        if self.is_data_dirty():
            current_item = self.file_list_widget.currentItem()
            filename = current_item.text().replace(" *", "") if current_item else "未命名文件"
            
            reply = QMessageBox.question(self, "未保存的更改", 
                                         f"文件 '{filename}' 有未保存的更改。\n\n您想先保存吗？",
                                         QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                         QMessageBox.Cancel)
            
            if reply == QMessageBox.Save:
                self.save_wordlist()
                if self.is_data_dirty(): # 如果保存失败，则中止新建操作
                    return
            elif reply == QMessageBox.Cancel:
                return # 用户取消，中止新建操作
            # 如果是 Discard，则继续向下执行

        # --- 2. [核心修复] 执行新建操作 ---

        # 无论之前是否有修改，都先将 undo_stack 标记为干净。
        # 对于 Discard 的情况，这会重置状态；
        # 对于已保存或原本就干净的情况，这没有副作用。
        self.undo_stack.setClean()

        # 同样，移除旧文件（如果有）的 “*” 标记
        previous_item = self.file_list_widget.currentItem()
        if previous_item and previous_item.text().endswith(" *"):
             previous_item.setText(previous_item.text()[:-2])
        
        # 现在可以安全地取消选中，而不会触发 on_file_selected 中的“脏”检查
        self.file_list_widget.setCurrentItem(None)
        
        # 重置所有状态
        self.current_wordlist_path = None
        self.original_data_snapshot = None
        self.table_widget.setRowCount(0)
        self.undo_stack.clear() # 彻底清空撤销历史
        
        # 添加默认行
        self.add_row()
        
        # 将这个初始的空行状态设置为新的“干净”快照
        self.original_data_snapshot = self._build_data_from_table() 
        
        # 立即检查并更新UI（此时应为干净状态）
        self.check_dirty_state()


    def save_wordlist(self):
        """保存当前单词表。如果未曾保存过，则调用另存为。"""
        if self.current_wordlist_path:
            self._write_to_file(self.current_wordlist_path)
        else:
            self.save_wordlist_as()

    def save_wordlist_as(self):
        """将当前单词表另存为新文件。"""
        filepath, _ = QFileDialog.getSaveFileName(self, "另存为单词表", self.WORD_LIST_DIR, "JSON 文件 (*.json)")
        if filepath:
            # 确保文件以 .json 结尾
            if not filepath.lower().endswith('.json'):
                filepath += '.json'
            
            self._write_to_file(filepath) # 写入文件
            self.current_wordlist_path = filepath # 更新当前文件路径
            self.refresh_file_list() # 刷新文件列表
            
            # 选中新保存的文件
            for i in range(self.file_list_widget.count()):
                if self.file_list_widget.item(i).text() == os.path.basename(filepath):
                    self.file_list_widget.setCurrentRow(i)
                    break

    def _write_to_file(self, filepath):
        """
        将表格中的数据转换为 JSON 格式并写入文件。
        :param filepath: 目标文件路径。
        """
        groups_map = {} # 用于按组别ID组织数据
        # 遍历时要排除最后一行（占位符）
        for row in range(self.table_widget.rowCount() - 1):
            try:
                # 获取各个单元格内容
                group_item = self.table_widget.item(row, 0)
                word_item = self.table_widget.item(row, 1)
                
                # 确保组别ID和单词文本有效
                if not group_item or not word_item or not group_item.text().isdigit() or not word_item.text().strip():
                    continue # 跳过无效行

                group_id = int(group_item.text())
                text = word_item.text().strip()
                
                note_item = self.table_widget.item(row, 2)
                note = note_item.text().strip() if note_item else ""
                
                lang_item = self.table_widget.item(row, 3) # 获取语言 item
                lang = lang_item.data(Qt.UserRole) if lang_item else "" # 从 UserRole 获取语言代码

                if group_id not in groups_map:
                    groups_map[group_id] = []
                groups_map[group_id].append({"text": text, "note": note, "lang": lang})
            except (ValueError, AttributeError) as e:
                print(f"写入文件时跳过无效行 {row}: {e}", file=sys.stderr)
                continue # 捕获异常并跳过该行，不中断保存

        # 构建最终的 JSON 数据结构
        final_data_structure = {
            "meta": {
                "format": "standard_wordlist", # 词表格式
                "version": "1.0",
                "author": "PhonAcq Assistant",
                "save_date": datetime.now().isoformat() # 保存时间
            },
            "groups": []
        }
        # 按组别ID排序，并添加到 groups 列表中
        for group_id, items in sorted(groups_map.items()):
            final_data_structure["groups"].append({"id": group_id, "items": items})
        
        try:
            # 写入 JSON 文件，使用 UTF-8 编码和4个空格缩进
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(final_data_structure, f, indent=4, ensure_ascii=False)
            
            # [核心重构] 保存成功后，用当前表格数据更新快照
            self.original_data_snapshot = self._build_data_from_table()
            self.undo_stack.setClean() # 标记为干净，以便下次可以撤销
            self.check_dirty_state() # 立即更新UI状态（应为干净）
            
            QMessageBox.information(self, "成功", f"单词表已成功保存至:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法保存文件:\n{e}")

    def _build_data_from_table(self):
        """
        [新增] 遍历当前表格，将其内容构建成一个与JSON文件结构相同的Python字典。
        这是进行“脏”状态比较的核心。
        """
        groups_map = {}
        # 遍历时要排除最后一行（占位符）
        for row in range(self.table_widget.rowCount() - 1):
            try:
                group_item = self.table_widget.item(row, 0)
                word_item = self.table_widget.item(row, 1)
                if not group_item or not word_item or not group_item.text().isdigit():
                    continue

                group_id = int(group_item.text())
                text = word_item.text().strip()
                note_item = self.table_widget.item(row, 2)
                note = note_item.text().strip() if note_item else ""
                lang_item = self.table_widget.item(row, 3)
                lang = lang_item.data(Qt.UserRole) if lang_item else ""

                if group_id not in groups_map:
                    groups_map[group_id] = []
                groups_map[group_id].append({"text": text, "note": note, "lang": lang})
            except (ValueError, AttributeError):
                continue
        
        groups_list = [{"id": gid, "items": items} for gid, items in sorted(groups_map.items())]
        # 只返回核心的 'groups' 部分，因为 'meta' 通常不通过表格编辑
        return groups_list

    def is_data_dirty(self):
        """
        [vFinal] 通过比较当前表格数据快照和原始快照，权威地判断文件是否被修改。
        """
        if self.original_data_snapshot is None:
            # 对于一个从未保存过的新建文件 (snapshot为None)
            # 只要表格中有任何非空的 "单词/短语" 或 "备注"，就认为是脏的。
            for row in range(self.table_widget.rowCount() - 1): # 排除占位符
                word_item = self.table_widget.item(row, 1)
                note_item = self.table_widget.item(row, 2)
                if (word_item and word_item.text().strip()) or \
                   (note_item and note_item.text().strip()):
                    return True # 发现有内容，是脏的
            return False # 所有行都是空的，认为是干净的

        current_data = self._build_data_from_table()
        return current_data != self.original_data_snapshot


    # --- 事件过滤器和单元格编辑处理 ---

    def eventFilter(self, source, event):
        """
        事件过滤器，用于处理表格视口的滚轮事件，以实现快速修改组别号。
        """
        # 检查是否是表格视口、滚轮事件，并且鼠标在第0列（组别）上
        if source is self.table_widget.viewport() and \
           event.type() == QEvent.Wheel and \
           self.table_widget.itemAt(event.pos()) and \
           self.table_widget.itemAt(event.pos()).column() == 0:
            
            item = self.table_widget.itemAt(event.pos())
            # 排除占位符行
            if item and item.data(self.ADD_NEW_ROW_ROLE):
                return super().eventFilter(source, event)

            try:
                old_value_str = item.text()
                if not old_value_str.isdigit():
                    return super().eventFilter(source, event) # 如果不是数字，则不处理

                new_value = int(old_value_str) + (1 if event.angleDelta().y() > 0 else -1)
                if new_value < 1:
                    new_value = 1 # 组别号最小为1

                new_value_str = str(new_value)
                
                # 如果值发生变化，则推送到撤销栈
                if old_value_str != new_value_str:
                    cmd = WordlistChangeCellCommand(self, item.row(), 0, old_value_str, new_value_str, "修改组别")
                    self.undo_stack.push(cmd)
                return True # 事件已处理
            except (ValueError, TypeError):
                pass # 捕获转换错误
        return super().eventFilter(source, event) # 对于其他事件，传递给基类处理

    def keyPressEvent(self, event):
        """
        重写键盘按下事件，处理 Delete/Backspace 键清空内容。
        """
        # 如果按下 Delete 或 Backspace 且有选中项，则清空内容
        if (event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace) and self.table_widget.selectedItems():
            self.clear_selection_contents()
            event.accept() # 标记事件已处理
        else:
            super().keyPressEvent(event) # 其他键传递给基类

    def on_item_pressed(self, item):
        """
        在单元格内容即将被编辑前触发，记录其旧文本用于撤销。
        """
        if item:
            self.old_text_before_edit = item.text()

    def on_item_changed_for_undo(self, item):
        # [核心修复] 只有在不是程序性更改时才创建 Undo 命令
        if self._is_programmatic_change:
            return
            
        # 排除占位符行
        if item and item.data(self.ADD_NEW_ROW_ROLE):
            return

        if self.old_text_before_edit is not None and \
           self.old_text_before_edit != item.text() and \
           item.column() != 3: # 语言列由 LanguageDelegate 处理其 undo
            
            cmd = WordlistChangeCellCommand(self, item.row(), item.column(), self.old_text_before_edit, item.text(), "修改单元格")
            self.undo_stack.push(cmd)
            
        self.old_text_before_edit = None

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

    def on_cell_single_clicked(self, row, column):
        """
        当一个单元格被单击时，如果它是语言列，则立即进入编辑模式。
        如果它是“添加新行”占位符，则添加一个新行。
        """
        item = self.table_widget.item(row, 0) # 总是检查第一列的 item
        
        # [新增] 检查是否是“添加新行”的占位符
        if item and item.data(self.ADD_NEW_ROW_ROLE):
            # 在占位符行的位置添加一个真正的新行
            self.add_row(at_row=row)
            return # 处理完毕，直接返回

        # 如果不是占位符行，则执行原来的语言列编辑逻辑
        if column == 3:
            lang_item = self.table_widget.item(row, column)
            if lang_item:
                self.table_widget.editItem(lang_item)

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
            # 获取前三列的文本内容
            row_data = [
                self.table_widget.item(row, col).text() if self.table_widget.item(row, col) else ""
                for col in range(3)
            ]
            # 从 UserRole 获取语言代码
            lang_item = self.table_widget.item(row, 3)
            lang_code = lang_item.data(Qt.UserRole) if lang_item else ""
            row_data.append(lang_code)
            
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
            # 只清空组别、单词/短语、备注列的内容 (语言列清空由其委托处理)
            if item.column() < 3 and item.text():
                cmd = WordlistChangeCellCommand(self, item.row(), item.column(), item.text(), "", "清空单元格")
                self.undo_stack.push(cmd)
            elif item.column() == 3 and item.data(Qt.UserRole) != "": # 清空语言列到自动检测
                cmd = WordlistChangeLanguageCommand(self, item.row(), item.data(Qt.UserRole), "", "清空语言")
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
                # 特别处理语言列的复制：复制其数据而非显示文本
                if c == 3 and self.table_widget.item(r, c): # 确保 item 存在
                    row_data.append(self.table_widget.item(r, c).data(Qt.UserRole)) # 从 UserRole 获取语言代码
                else:
                    item = self.table_widget.item(r, c)
                    row_data.append(item.text() if item else "")
            table_str_rows.append("\t".join(row_data))
        
        table_str = "\n".join(table_str_rows)
        QApplication.clipboard().setText(table_str)

    def paste_selection(self):
        """[vFinal] 将剪贴板内容粘贴到表格，并能正确处理超出范围的新行。"""
        selection = self.table_widget.selectedRanges()
        if not selection:
            # 如果没有选中单元格，默认从 (0,0) 开始粘贴
            start_row, start_col = 0, 0
        else:
            start_row, start_col = selection[0].topRow(), selection[0].leftColumn()

        text = QApplication.clipboard().text()
        rows = text.strip('\n').split('\n')

        self.undo_stack.beginMacro("粘贴")
        
        # [修改] 不再移除占位符行，因为新行是动态添加的
        # self._remove_placeholder_row()

        for i, row_text in enumerate(rows):
            cells = row_text.split('\t')
            target_row_abs = start_row + i

            # [核心修复] 如果目标行超出当前行数，则用我们的 add_row 方法创建新行
            if target_row_abs >= self.table_widget.rowCount() -1: # -1 是为了排除占位符
                # 使用 add_row(at_row) 来创建，它会自动处理占位符和undo栈
                # 注意：add_row 自己会推送undo命令，所以我们这里不需要再管
                # 为了简单起见，我们直接插入空行
                self._remove_placeholder_row()
                self.table_widget.insertRow(target_row_abs)
                self.populate_row(target_row_abs, ["1", "", "", ""]) # 用空数据填充
                self._add_placeholder_row()

            for j, cell_text in enumerate(cells):
                # ... (后续的粘贴逻辑保持不变) ...
                target_col = start_col + j
                if target_row_abs < self.table_widget.rowCount() -1 and target_col < self.table_widget.columnCount():
                    if target_col == 3:
                        lang_item = self.table_widget.item(target_row_abs, target_col)
                        old_lang_code = lang_item.data(Qt.UserRole) if lang_item else ""
                        new_lang_code = cell_text if cell_text in LANGUAGE_MAP.values() else ""
                        if old_lang_code != new_lang_code:
                            cmd = WordlistChangeLanguageCommand(self, target_row_abs, old_lang_code, new_lang_code, "粘贴语言")
                            self.undo_stack.push(cmd)
                    else:
                        item = self.table_widget.item(target_row_abs, target_col)
                        old_text = item.text() if item else ""
                        if old_text != cell_text:
                            cmd = WordlistChangeCellCommand(self, target_row_abs, target_col, old_text, cell_text, "粘贴单元格")
                            self.undo_stack.push(cmd)
                            
        self.undo_stack.endMacro()

    def duplicate_rows(self):
        """[vFinal] 复制选中的行，并将其插入到选中行的下方。"""
        rows_to_duplicate = self.get_selected_rows_indices()
        if not rows_to_duplicate:
            # [修改] 如果没有显式选择，则不再隐式复制当前行，而是提示用户
            QMessageBox.information(self, "提示", "请先选择一个或多个要创建副本的行。")
            return
        
        rows_data = self._get_rows_data(rows_to_duplicate)
        insert_at = rows_to_duplicate[-1] + 1
        
        cmd = WordlistRowOperationCommand(self, insert_at, rows_data, 'add', description="创建副本/重制行")
        self.undo_stack.push(cmd)

    def move_rows(self, offset):
        """
        移动选中行。
        :param offset: 移动的距离 (1 为向下，-1 为向上)。
        """
        selected_rows = self.get_selected_rows_indices()
        if not selected_rows:
            return
        
        # 边界检查
        if (offset == -1 and selected_rows[0] == 0) or \
           (offset == 1 and selected_rows[-1] >= self.table_widget.rowCount() - 1): # 考虑占位符行
            return # 无法移动

        start_row = selected_rows[0]
        rows_data = self._get_rows_data(selected_rows) # 获取选中行的数据
        
        # 推送移动行的撤销命令
        cmd = WordlistRowOperationCommand(self, start_row, rows_data, 'move', offset, "移动行")
        self.undo_stack.push(cmd)
        
        # 移动后重新选中这些行
        self.table_widget.clearSelection() # 清除旧的选择
        new_start_row = start_row + offset
        for i in range(len(selected_rows)):
            self.table_widget.selectRow(new_start_row + i) # 选中新位置的行

    def add_row(self, at_row=None):
        """
        在指定位置添加一个新行。
        :param at_row: 插入行的索引。如果为 None，则添加到表格末尾。
        """
        # 在添加新行前移除占位符行
        self._remove_placeholder_row()

        if at_row is None:
            at_row = self.table_widget.rowCount() # 现在 rowCount() 是实际数据行数
        
        last_group = "1" # 默认组别ID
        if at_row > 0:
            last_item = self.table_widget.item(at_row - 1, 0)
            # 如果上一行的组别是数字，则沿用
            if last_item and last_item.text().isdigit():
                last_group = last_item.text()
        
        # 新行的数据，包括组别、空文本、空备注、空语言代码
        new_row_data = [[last_group, "", "", ""]]
        
        cmd = WordlistRowOperationCommand(self, at_row, new_row_data, 'add', description="添加新行")
        self.undo_stack.push(cmd)
        
        # 在添加新行操作完成后，重新添加占位符行
        QApplication.processEvents() # 强制UI刷新，确保新行可见
        self._add_placeholder_row()
        
        # 滚动到新行并选中它
        self.table_widget.scrollToItem(self.table_widget.item(at_row, 0), QTableWidget.ScrollHint.EnsureVisible)
        self.table_widget.selectRow(at_row)
        
        # 自动选中并编辑第二列 (单词/短语)
        self.table_widget.setCurrentCell(at_row, 1)
        self.table_widget.editItem(self.table_widget.item(at_row, 1))

    def remove_row(self):
        """移除所有选中的行。"""
        selected_rows = self.get_selected_rows_indices()
        if not selected_rows:
            QMessageBox.warning(self, "提示", "请先选择要移除的整行。")
            return
        
        rows_data = self._get_rows_data(selected_rows) # 获取选中行的数据用于撤销
        start_row = selected_rows[0] # 记录起始行索引
        
        cmd = WordlistRowOperationCommand(self, start_row, rows_data, 'remove', description="移除选中行")
        self.undo_stack.push(cmd)


    def send_to_tts(self, item):
        """
        [新增] 将选中的词表路径发送到TTS工具模块。
        """
        if not item: return
        
        # 确保钩子仍然有效
        if self.tts_utility_hook and hasattr(self.tts_utility_hook, 'load_wordlist_from_file'):
            clean_filename = item.text().replace(" *", "")
            wordlist_path = os.path.join(self.WORD_LIST_DIR, clean_filename)
            
            # 1. 调用主窗口的API切换到“实用工具”主标签页
            #    (假设TTS工具在“实用工具”下)
            main_tabs = self.parent_window.main_tabs
            for i in range(main_tabs.count()):
                if main_tabs.tabText(i) == "实用工具":
                    main_tabs.setCurrentIndex(i)
                    sub_tabs = main_tabs.widget(i)
                    # 2. 切换到“TTS 工具”子标签页
                    if sub_tabs and isinstance(sub_tabs, QTabWidget):
                         for j in range(sub_tabs.count()):
                            if sub_tabs.tabText(j) == "TTS 工具":
                                sub_tabs.setCurrentIndex(j)
                                break
                    break
            
            # 3. 延时调用TTS工具的加载方法，确保UI已切换完成
            QTimer.singleShot(50, lambda: self.tts_utility_hook.load_wordlist_from_file(wordlist_path))