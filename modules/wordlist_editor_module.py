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

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QFileDialog, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QComboBox, QShortcut,
    QUndoStack, QUndoCommand, QApplication, QMenu, QDialog,
    QTableWidget, QTableWidgetItem, QTabWidget # 重复导入，已合并
)
from PyQt5.QtCore import Qt, QSize, QEvent, QTimer
from PyQt5.QtGui import QKeySequence, QIcon

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

    def redo(self):
        """执行重做操作：将单元格内容设为新文本。"""
        item = self.table.item(self.row, self.col)
        if not item:
            item = QTableWidgetItem()
            self.table.setItem(self.row, self.col, item)
        item.setText(self.new_text)

    def undo(self):
        """执行撤销操作：将单元格内容恢复为旧文本。"""
        item = self.table.item(self.row, self.col)
        if not item:
            item = QTableWidgetItem()
            self.table.setItem(self.row, self.col, item)
        item.setText(self.old_text)

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
        widget = self.table.cellWidget(self.row, 3) # 语言下拉框在第3列
        if isinstance(widget, QComboBox):
            index = widget.findData(lang_code)
            if index != -1:
                widget.setCurrentIndex(index)

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
        self.move_offset = move_offset # 仅用于 'move' 操作

    def _insert_rows(self, at_row, data):
        """辅助方法：在指定位置插入多行数据。"""
        for i, row_data in enumerate(data):
            self.table.insertRow(at_row + i)
            # data 中包含所有列的数据，包括语言代码和状态列的空位
            self.editor.populate_row(at_row + i, row_data) 

    def _remove_rows(self, at_row, count):
        """辅助方法：从指定位置移除多行。"""
        for _ in range(count):
            self.table.removeRow(at_row)

    def redo(self):
        """执行重做操作。"""
        self.table.blockSignals(True) # 阻止信号，避免在操作过程中触发不必要的更新
        if self.type == 'remove':
            self._remove_rows(self.start_row, len(self.rows_data))
        elif self.type == 'add':
            self._insert_rows(self.start_row, self.rows_data)
        elif self.type == 'move':
            # 移动操作：先移除旧位置的行，再在目标位置插入
            self._remove_rows(self.start_row, len(self.rows_data))
            self._insert_rows(self.start_row + self.move_offset, self.rows_data)
        self.table.blockSignals(False) # 解除信号阻止

    def undo(self):
        """执行撤销操作。"""
        self.table.blockSignals(True) # 阻止信号
        if self.type == 'remove':
            self._insert_rows(self.start_row, self.rows_data) # 撤销删除，即重新插入
        elif self.type == 'add':
            self._remove_rows(self.start_row, len(self.rows_data)) # 撤销添加，即删除
        elif self.type == 'move':
            # 撤销移动：先移除新位置的行，再在旧位置插入
            self._remove_rows(self.start_row + self.move_offset, len(self.rows_data))
            self._insert_rows(self.start_row, self.rows_data)
        self.table.blockSignals(False) # 解除信号阻止

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
    def __init__(self, parent_window, WORD_LIST_DIR, icon_manager, detect_language_func):
        super().__init__()
        self.parent_window = parent_window
        self.WORD_LIST_DIR = WORD_LIST_DIR
        self.icon_manager = icon_manager
        self.detect_language_func = detect_language_func

        self.current_wordlist_path = None # 当前加载的词表文件路径
        self.old_text_before_edit = None  # 用于撤销/重做：单元格旧文本
        self.old_lang_before_edit = None  # 用于撤销/重做：语言下拉框旧值

        self.undo_stack = QUndoStack(self) # 撤销/重做栈
        self.undo_stack.setUndoLimit(100) # 设置撤销步数限制

        self.base_path = get_base_path_for_module() # 获取项目根目录
        self.flags_path = os.path.join(self.base_path, 'assets', 'flags') # 旗帜图标路径
        self.tts_utility_hook = None

        self.status_thread = None # 用于音频状态检查的QThread实例
        self.status_worker = None # 用于音频状态检查的QObject工作器实例

        self._init_ui() # 初始化用户界面
        self.setup_connections_and_shortcuts() # 设置信号槽和快捷键
        self.update_icons() # 更新按钮图标
        self.apply_layout_settings() # 应用布局设置
        self.refresh_file_list() # 刷新词表文件列表

    def _init_ui(self):
        """构建页面的用户界面布局。"""
        main_layout = QHBoxLayout(self)

        # --- 左侧面板：文件列表和操作按钮 ---
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        
        left_layout.addWidget(QLabel("单词表文件:"))
        self.file_list_widget = QListWidget()
        self.file_list_widget.setContextMenuPolicy(Qt.CustomContextMenu) # 启用自定义上下文菜单
        self.file_list_widget.setToolTip("所有可编辑的单词表文件。\n右键单击可进行更多操作。")
        left_layout.addWidget(self.file_list_widget)

        self.new_btn = QPushButton("新建单词表")
        left_layout.addWidget(self.new_btn)
        
        file_btn_layout = QHBoxLayout() # 文件操作按钮布局
        self.save_btn = QPushButton("保存")
        self.save_as_btn = QPushButton("另存为...")
        file_btn_layout.addWidget(self.save_btn)
        file_btn_layout.addWidget(self.save_as_btn)
        left_layout.addLayout(file_btn_layout)

        # --- 右侧面板：词表编辑表格和操作按钮 ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(5) # 5列: 组别, 单词/短语, 备注(IPA), 语言(可选), 状态
        self.table_widget.setHorizontalHeaderLabels(["组别", "单词/短语", "备注 (IPA)", "语言 (可选)", ""])
        self.table_widget.setToolTip("在此表格中编辑单词/词语。\n'状态'列显示相关音频资源的可用性。")
        
        # 调整列的拉伸模式和宽度
        header = self.table_widget.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive) # 组别列可手动调整
        header.setSectionResizeMode(1, QHeaderView.Stretch)     # 单词/短语列拉伸
        header.setSectionResizeMode(2, QHeaderView.Stretch)     # 备注/IPA列拉伸
        header.setSectionResizeMode(3, QHeaderView.Interactive) # 语言列可手动调整
        header.setSectionResizeMode(4, QHeaderView.Fixed)       # 状态列固定宽度
        
        self.table_widget.setColumnWidth(4, 50) # 状态列的固定宽度
        
        self.table_widget.verticalHeader().setVisible(True) # 显示行号
        self.table_widget.setAlternatingRowColors(True) # 启用交替行颜色，提高可读性
        right_layout.addWidget(self.table_widget)

        table_btn_layout = QHBoxLayout() # 表格操作按钮布局
        self.undo_btn = QPushButton("撤销")
        self.redo_btn = QPushButton("重做")
        self.auto_detect_lang_btn = QPushButton("自动检测语言")
        self.add_row_btn = QPushButton("添加行")
        self.remove_row_btn = QPushButton("移除选中行")
        
        table_btn_layout.addWidget(self.undo_btn)
        table_btn_layout.addWidget(self.redo_btn)
        table_btn_layout.addStretch() # 弹簧，将中间按钮推开
        table_btn_layout.addWidget(self.auto_detect_lang_btn)
        table_btn_layout.addStretch() # 弹簧，将右侧按钮推开
        table_btn_layout.addWidget(self.add_row_btn)
        table_btn_layout.addWidget(self.remove_row_btn)
        
        right_layout.addLayout(table_btn_layout)

        # 将左右面板添加到主布局
        main_layout.addWidget(self.left_panel)
        main_layout.addWidget(right_panel, 1) # 右侧面板占据更多空间

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
        self.save_btn.setIcon(self.icon_manager.get_icon("save"))
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
        """应用从全局配置中读取的UI布局设置，如侧边栏宽度和列宽。"""
        config = self.parent_window.config
        ui_settings = config.get("ui_settings", {})
        
        # 应用侧边栏宽度
        width = ui_settings.get("editor_sidebar_width", 280)
        self.left_panel.setFixedWidth(width)
        
        # 应用表格列宽。默认值包含 组别, 拉伸1, 拉伸2, 语言, 状态
        # 列表中有5个元素，对应5列
        col_widths = ui_settings.get("wordlist_editor_col_widths", [80, -1, -1, 150, 50])
        if len(col_widths) != 5: # 确保长度匹配列数
            col_widths = [80, -1, -1, 150, 50] # 如果配置有误，重置为新的默认值

        # 应用固定或可交互列的宽度
        self.table_widget.setColumnWidth(0, col_widths[0]) # 组别
        self.table_widget.setColumnWidth(3, col_widths[3]) # 语言
        self.table_widget.setColumnWidth(4, col_widths[4]) # 状态 (固定宽度)

    def on_column_resized(self, logical_index, old_size, new_size):
        """
        当表格列大小被用户调整时，保存新的列宽到配置文件中。
        只保存 '组别' (0), '语言' (3), '状态' (4) 列的宽度，拉伸列不需保存具体宽度。
        """
        # 只有特定的列才需要保存其宽度
        if logical_index not in [0, 3, 4]:
            return
            
        config = self.parent_window.config
        # 获取当前的列宽配置，如果不存在则使用默认值
        current_widths = config.setdefault("ui_settings", {}).get("wordlist_editor_col_widths", [80, -1, -1, 150, 50])
        
        # 更新相应列的宽度
        if logical_index == 0:
            current_widths[0] = new_size
        elif logical_index == 3:
            current_widths[3] = new_size
        elif logical_index == 4:
            current_widths[4] = new_size

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
        # 确保在刷新前应用最新的布局设置和图标，防止UI错位
        if hasattr(self, 'parent_window'):
            self.apply_layout_settings()
            self.update_icons()

        current_selection = self.file_list_widget.currentItem().text() if self.file_list_widget.currentItem() else ""
        self.file_list_widget.clear() # 清空当前列表
        
        if os.path.exists(self.WORD_LIST_DIR):
            # 过滤出所有 .json 文件并按名称排序
            files = sorted([f for f in os.listdir(self.WORD_LIST_DIR) if f.endswith('.json')])
            self.file_list_widget.addItems(files)
            
            # 尝试重新选中之前的文件
            for i in range(len(files)):
                if files[i] == current_selection:
                    self.file_list_widget.setCurrentRow(i)
                    break

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

        # 表格右键菜单
        self.table_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_widget.customContextMenuRequested.connect(self.show_context_menu)
        
        # 撤销栈状态更新，控制保存按钮的启用状态
        self.undo_stack.cleanChanged.connect(lambda is_clean: self.save_btn.setEnabled(not is_clean))
        
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
        使用 undo/redo 机制包装所有更改。
        """
        detected_count = 0
        self.undo_stack.beginMacro("自动检测语言") # 开启宏操作

        gtts_settings = self.parent_window.config.get("gtts_settings", {})
        default_lang = gtts_settings.get("default_lang", "en-us") # 获取默认语言

        for row in range(self.table_widget.rowCount()):
            word_item = self.table_widget.item(row, 1)    # "单词/短语" 在第1列
            note_item = self.table_widget.item(row, 2)    # "备注 (IPA)" 在第2列
            lang_combo = self.table_widget.cellWidget(row, 3) # 语言下拉框在第3列

            # 确保词条和语言下拉框都存在且词条文本不为空
            if word_item and lang_combo:
                current_lang = lang_combo.currentData() # 获取当前语言代码
                
                # 只对语言设置为“自动检测”的行进行操作
                if current_lang == "":
                    text = word_item.text().strip()
                    # 获取备注文本，如果单元格不存在则为空字符串
                    note = note_item.text().strip() if note_item else ""
                    
                    # --- [核心修正] ---
                    # 同时传递 text 和 note 两个参数给语言检测函数
                    detected_lang = self.detect_language_func(text, note) or default_lang
                    # --------------------

                    # 如果检测到的语言与当前不同，则创建并推送撤销命令
                    if detected_lang != current_lang:
                        cmd = WordlistChangeLanguageCommand(self, row, current_lang, detected_lang, "自动填充语言")
                        self.undo_stack.push(cmd)
                        detected_count += 1
                        
        self.undo_stack.endMacro() # 结束宏操作
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
        
        # --- [新增] 检查钩子是否存在，如果存在则添加“发送到TTS”菜单项 ---
        if self.tts_utility_hook:
            menu.addSeparator()
            send_to_tts_action = menu.addAction(self.icon_manager.get_icon("tts"), "发送到TTS工具")
            send_to_tts_action.setToolTip("将此词表加载到TTS工具中进行批量转换。")
            send_to_tts_action.triggered.connect(lambda: self.send_to_tts(item))

        # 检查是否有分割器插件的钩子 (此部分逻辑不变)
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
        """
        将当前选中的词表文件路径发送到 TTS 批量分割器插件。
        此方法通过插件管理器提供的钩子进行调用。
        """
        if not item:
            return
        
        splitter_plugin = getattr(self, 'tts_splitter_plugin_active', None)
        if splitter_plugin:
            wordlist_path = os.path.join(self.WORD_LIST_DIR, item.text())
            # 通过插件的 execute 方法传递词表路径
            splitter_plugin.execute(wordlist_path=wordlist_path)

    def _show_in_explorer(self, item):
        """
        在系统文件浏览器中显示选中的词表文件。
        :param item: QListWidgetItem 实例，代表要显示的文件。
        """
        if not item:
            return
        filepath = os.path.join(self.WORD_LIST_DIR, item.text())
        
        # 检查文件是否存在
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
        src_path = os.path.join(self.WORD_LIST_DIR, item.text())
        
        if not os.path.exists(src_path):
            QMessageBox.warning(self, "文件不存在", "无法创建副本，源文件可能已被移动或删除。")
            self.refresh_file_list()
            return

        # 生成新的文件名，避免与现有文件冲突
        base, ext = os.path.splitext(item.text())
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
        删除当前选中词表文件。
        :param item: QListWidgetItem 实例，代表要删除的文件。
        """
        if not item:
            return
        filepath = os.path.join(self.WORD_LIST_DIR, item.text())
        
        reply = QMessageBox.question(self, "确认删除", f"您确定要永久删除文件 '{item.text()}' 吗？\n此操作不可撤销。",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            try:
                os.remove(filepath)
                # 如果删除的是当前正在编辑的文件，则清空表格和撤销栈
                if filepath == self.current_wordlist_path:
                    self.current_wordlist_path = None
                    self.table_widget.setRowCount(0)
                    self.undo_stack.clear()
                self.refresh_file_list() # 刷新文件列表
            except Exception as e:
                QMessageBox.critical(self, "删除失败", f"无法删除文件: {e}")

    def _configure_metadata(self, item):
        """
        打开元数据配置对话框，允许用户编辑词表的元信息。
        :param item: QListWidgetItem 实例，代表要配置元数据的文件。
        """
        if not item:
            return
        filepath = os.path.join(self.WORD_LIST_DIR, item.text())
        
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
                    self.load_file_to_table()

        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"处理元数据时发生错误: {e}")

    # --- 文件加载和保存 ---

    def on_file_selected(self, current, previous):
        """
        当用户在文件列表中选择不同的文件时触发。
        检查是否有未保存的更改，并加载新文件。
        """
        # 检查是否有未保存的更改
        if not self.undo_stack.isClean() and previous:
            reply = QMessageBox.question(self, "未保存的更改", "您有未保存的更改，确定要切换吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                # 如果用户选择不切换，则恢复之前的选中状态
                self.file_list_widget.currentItemChanged.disconnect(self.on_file_selected)
                self.file_list_widget.setCurrentItem(previous)
                self.file_list_widget.currentItemChanged.connect(self.on_file_selected)
                return

        if current:
            self.current_wordlist_path = os.path.join(self.WORD_LIST_DIR, current.text())
            self.load_file_to_table() # 加载选中的文件到表格
        else:
            # 如果没有文件被选中，清空表格
            self.current_wordlist_path = None
            self.table_widget.setRowCount(0)
            self.undo_stack.clear() # 清空撤销栈

    def load_file_to_table(self):
        """
        加载当前选中词表文件 (self.current_wordlist_path) 的内容到表格中。
        """
        # 增加文件存在性检查
        if not self.current_wordlist_path or not os.path.exists(self.current_wordlist_path):
            QMessageBox.information(self, "文件不存在", f"词表文件 '{os.path.basename(str(self.current_wordlist_path))}' 不存在，可能已被删除或移动。")
            self.current_wordlist_path = None
            self.table_widget.setRowCount(0)
            self.undo_stack.clear()
            self.refresh_file_list() # 刷新列表以移除不存在的文件
            return
            
        self.table_widget.blockSignals(True) # 阻止信号，避免在加载过程中触发 itemChanged
        self.table_widget.setRowCount(0) # 清空现有表格内容
        
        try:
            with open(self.current_wordlist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 验证 JSON 文件结构
            if "meta" not in data or "groups" not in data or not isinstance(data["groups"], list):
                raise ValueError("JSON文件格式无效，缺少 'meta' 或 'groups' 键，或 'groups' 不是列表。")

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
                    self.populate_row(row_index, [str(group_id), text, note, lang, ""])
                    row_index += 1
            
            self.undo_stack.clear() # 加载新文件后，清空撤销栈，标记为干净状态
            
            # 加载完成后，启动后台线程检查所有词条的音频状态
            self.check_all_audio_statuses()

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            QMessageBox.critical(self, "加载失败", f"无法解析JSON词表文件 '{os.path.basename(self.current_wordlist_path)}':\n{e}")
        finally:
            self.table_widget.blockSignals(False) # 解除信号阻止

    def populate_row(self, row, data):
        """
        填充表格的指定行。
        :param row: 要填充的行号。
        :param data: 包含 [group_id, text, note, lang_code, status_placeholder] 的列表。
        """
        # 设置 '组别', '单词/短语', '备注 (IPA)' 列
        self.table_widget.setItem(row, 0, QTableWidgetItem(data[0]))
        self.table_widget.setItem(row, 1, QTableWidgetItem(data[1]))
        self.table_widget.setItem(row, 2, QTableWidgetItem(data[2]))
        
        # 设置 '语言 (可选)' 列为 QComboBox
        combo = QComboBox(self.table_widget)
        combo.setIconSize(QSize(24, 18)) # 旗帜图标大小
        for display_name, lang_code in LANGUAGE_MAP.items():
            icon_path = os.path.join(self.flags_path, f"{FLAG_CODE_MAP.get(lang_code, 'auto')}.png")
            # 添加带有图标和数据的项
            combo.addItem(QIcon(icon_path) if os.path.exists(icon_path) else QIcon(), display_name, lang_code)
        
        # 设置默认选中语言
        index = combo.findData(data[3]) # data[3] 是语言代码
        if index != -1:
            combo.setCurrentIndex(index)
        
        # 连接语言下拉框的信号
        combo.view().pressed.connect(lambda _, r=row: self.on_language_combo_pressed(r)) # 在下拉框被按下时记录旧值
        combo.activated.connect(lambda idx, r=row: self.on_language_manually_changed(idx, r)) # 在语言被手动选择时触发
        self.table_widget.setCellWidget(row, 3, combo)

        # 状态列 (第4列) 初始化为空，待后台检查后更新
        # 初始时设置一个空的QWidget作为占位符，或直接留空
        self.table_widget.setItem(row, 4, QTableWidgetItem("")) # 设置一个空的 QTableWidgetItem，后续会被 cellWidget 替换

    def new_wordlist(self):
        """
        创建新的空单词表。
        如果当前有未保存的更改，会提示用户。
        """
        if not self.undo_stack.isClean():
            reply = QMessageBox.question(self, "未保存的更改", "您有未保存的更改，确定要新建吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return
        
        # 清空表格，重置当前文件路径和撤销栈
        self.table_widget.setRowCount(0)
        self.current_wordlist_path = None
        self.file_list_widget.setCurrentItem(None) # 取消文件列表选中状态
        self.undo_stack.clear()
        
        self.add_row() # 默认添加一行

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
        for row in range(self.table_widget.rowCount()):
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
                
                lang_combo = self.table_widget.cellWidget(row, 3)
                lang = lang_combo.currentData() if lang_combo else "" # 获取语言代码

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
            
            self.undo_stack.setClean() # 保存成功后，标记撤销栈为干净状态
            QMessageBox.information(self, "成功", f"单词表已成功保存至:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法保存文件:\n{e}")

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
        """
        在单元格内容改变后触发，将变化推送到撤销栈。
        """
        # 确保旧文本已记录且与新文本不同，并且列不为语言列（语言列有独立处理）
        if self.old_text_before_edit is not None and \
           self.old_text_before_edit != item.text() and \
           item.column() != 3: # 语言列有自己的处理逻辑
            
            cmd = WordlistChangeCellCommand(self, item.row(), item.column(), self.old_text_before_edit, item.text(), "修改单元格")
            self.undo_stack.push(cmd)
            
        self.old_text_before_edit = None # 重置旧文本

    def on_language_combo_pressed(self, row):
        """
        在语言下拉框被按下时触发，记录其旧语言代码用于撤销。
        """
        combo = self.table_widget.cellWidget(row, 3)
        if isinstance(combo, QComboBox):
            self.old_lang_before_edit = combo.currentData()

    def on_language_manually_changed(self, index, row):
        """
        在语言下拉框手动选择语言后触发，将变化推送到撤销栈。
        """
        combo = self.table_widget.cellWidget(row, 3)
        if not isinstance(combo, QComboBox):
            return
        
        new_lang_code = combo.itemData(index)
        
        # 如果旧语言已记录且与新语言不同，则推送到撤销栈
        if self.old_lang_before_edit is not None and self.old_lang_before_edit != new_lang_code:
            cmd = WordlistChangeLanguageCommand(self, row, self.old_lang_before_edit, new_lang_code, "改变语言")
            self.undo_stack.push(cmd)
        self.old_lang_before_edit = None # 重置旧语言

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

    # --- 剪贴板和行操作逻辑 ---

    def get_selected_rows_indices(self):
        """获取当前表格中所有选中行的索引列表，并按升序排序。"""
        # 使用 set 避免重复行，然后转换为 list 并排序
        return sorted(list(set(index.row() for index in self.table_widget.selectedIndexes())))

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
            # 获取语言下拉框的当前数据
            lang_combo = self.table_widget.cellWidget(row, 3)
            row_data.append(lang_combo.currentData() if lang_combo else "")
            
            # 为状态列预留空位，因为它是动态生成的
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
            # 只清空组别、单词/短语、备注列的内容，不触碰语言和状态列
            if item.column() < 3 and item.text():
                cmd = WordlistChangeCellCommand(self, item.row(), item.column(), item.text(), "", "清空单元格")
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
        cols = sorted(list(set(index.column() for index in self.table_widget.selectedIndexes())))
        
        table_str_rows = []
        for r in rows:
            row_data = []
            for c in cols:
                # 特别处理语言下拉框的复制：复制其数据而非显示文本
                if c == 3 and self.table_widget.cellWidget(r, c):
                    row_data.append(self.table_widget.cellWidget(r, c).currentData())
                else:
                    item = self.table_widget.item(r, c)
                    row_data.append(item.text() if item else "")
            table_str_rows.append("\t".join(row_data))
        
        table_str = "\n".join(table_str_rows)
        QApplication.clipboard().setText(table_str)

    def paste_selection(self):
        """
        将系统剪贴板中的内容粘贴到表格的当前选中位置。
        内容按制表符和换行符解析。
        """
        selection = self.table_widget.selectedRanges()
        if not selection:
            return
        
        start_row, start_col = selection[0].topRow(), selection[0].leftColumn()
        text = QApplication.clipboard().text()
        rows = text.strip('\n').split('\n') # 按行分割
        
        self.undo_stack.beginMacro("粘贴") # 开启宏操作
        for i, row_text in enumerate(rows):
            cells = row_text.split('\t') # 按制表符分割单元格
            for j, cell_text in enumerate(cells):
                target_row, target_col = start_row + i, start_col + j
                
                # 确保目标位置在表格范围内
                if target_row < self.table_widget.rowCount() and target_col < self.table_widget.columnCount():
                    if target_col == 3: # 处理语言列的粘贴
                        combo = self.table_widget.cellWidget(target_row, target_col)
                        if combo and combo.currentData() != cell_text:
                            cmd = WordlistChangeLanguageCommand(self, target_row, combo.currentData(), cell_text, "粘贴语言")
                            self.undo_stack.push(cmd)
                    else: # 处理其他列的粘贴
                        item = self.table_widget.item(target_row, target_col)
                        old_text = item.text() if item else ""
                        if old_text != cell_text:
                            cmd = WordlistChangeCellCommand(self, target_row, target_col, old_text, cell_text, "粘贴单元格")
                            self.undo_stack.push(cmd)
        self.undo_stack.endMacro() # 结束宏操作

    def duplicate_rows(self):
        """复制选中的行，并将其插入到选中行的下方。"""
        rows_to_duplicate = self.get_selected_rows_indices()
        if not rows_to_duplicate:
            # 如果没有选中行，则复制当前活动行
            current_row = self.table_widget.currentRow()
            if current_row == -1:
                return # 没有可复制的行
            else:
                rows_to_duplicate = [current_row]
        
        rows_data = self._get_rows_data(rows_to_duplicate) # 获取选中行的数据
        insert_at = rows_to_duplicate[-1] + 1 # 插入到选中行的最后一行下方
        
        # 推送复制行的撤销命令
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
           (offset == 1 and selected_rows[-1] == self.table_widget.rowCount() - 1):
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
        if at_row is None:
            at_row = self.table_widget.rowCount()
        
        last_group = "1" # 默认组别ID
        if at_row > 0:
            last_item = self.table_widget.item(at_row - 1, 0)
            # 如果上一行的组别是数字，则沿用
            if last_item and last_item.text().isdigit():
                last_group = last_item.text()
        
        # 新行的数据，包括组别、空文本、空备注、空语言代码和状态列的空位
        new_row_data = [[last_group, "", "", "", ""]]
        
        cmd = WordlistRowOperationCommand(self, at_row, new_row_data, 'add', description="添加新行")
        self.undo_stack.push(cmd)
        
        QApplication.processEvents() # 强制UI刷新，确保新行可见
        
        # 滚动到新行并选中它
        self.table_widget.scrollToItem(self.table_widget.item(at_row, 0), QTableWidget.ScrollHint.EnsureVisible)
        self.table_widget.selectRow(at_row)

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

    # --- 音频状态检查功能 ---

    def check_all_audio_statuses(self):
        """
        启动一个后台线程来检查所有词条的音频文件状态。
        在启动新线程前会安全地停止并清理旧线程。
        """
        self._stop_previous_status_check() # 确保停止任何正在运行的旧检查

        if self.table_widget.rowCount() == 0 or not self.current_wordlist_path:
            return # 如果没有词条或未选择词表，则不执行检查

        wordlist_name = os.path.splitext(os.path.basename(self.current_wordlist_path))[0]
        items_to_check = []
        for row in range(self.table_widget.rowCount()):
            word_item = self.table_widget.item(row, 1)
            lang_combo = self.table_widget.cellWidget(row, 3)
            if word_item and lang_combo:
                # 收集需要检查的词条信息
                items_to_check.append({
                    "row": row,
                    "text": word_item.text(),
                    "lang": lang_combo.currentData()
                })

        # --- StatusWorker 内部类定义 ---
        from PyQt5.QtCore import QThread, QObject, pyqtSignal

        class StatusWorker(QObject):
            """
            后台工作器，用于在不阻塞UI的情况下检查词条的音频文件状态。
            """
            # 定义信号：(行号, 是否有真人录音, 是否有TTS录音, 真人录音路径, TTS录音路径)
            status_checked = pyqtSignal(int, bool, bool, str, str)
            finished = pyqtSignal() # 任务完成信号

            def __init__(self, items, current_wordlist_name, parent=None):
                super().__init__(parent)
                self.items = items # 待检查的词条列表
                self.wordlist_name = current_wordlist_name
                
                base_path = get_base_path_for_module() # 获取项目根目录
                # 构建真人录音和TTS录音的预期路径
                self.record_dir = os.path.join(base_path, 'audio_record', self.wordlist_name)
                self.tts_dir = os.path.join(base_path, 'audio_tts', self.wordlist_name)

            def run(self):
                """执行状态检查任务。"""
                for item_info in self.items:
                    text = item_info['text']
                    lang = item_info['lang'] # 虽然这里没用，但保持一致
                    
                    # 检查真人录音文件 (.wav 和 .mp3)
                    record_path_wav = os.path.join(self.record_dir, f"{text}.wav")
                    record_path_mp3 = os.path.join(self.record_dir, f"{text}.mp3")
                    has_record = os.path.exists(record_path_wav) or os.path.exists(record_path_mp3)
                    final_record_path = record_path_wav if os.path.exists(record_path_wav) else record_path_mp3 if has_record else ""

                    # 检查 TTS 录音文件 (.wav 和 .mp3)
                    tts_path_wav = os.path.join(self.tts_dir, f"{text}.wav")
                    tts_path_mp3 = os.path.join(self.tts_dir, f"{text}.mp3")
                    has_tts = os.path.exists(tts_path_wav) or os.path.exists(tts_path_mp3)
                    final_tts_path = tts_path_wav if os.path.exists(tts_path_wav) else tts_path_mp3 if has_tts else ""
                    
                    # 发射信号，通知UI更新单行状态
                    self.status_checked.emit(item_info['row'], has_record, has_tts, final_record_path, final_tts_path)
                
                self.finished.emit() # 任务完成后发射结束信号
        
        # --- 启动线程逻辑 ---
        self.status_thread = QThread() # 创建新线程
        self.status_worker = StatusWorker(items_to_check, wordlist_name) # 实例化工作器
        self.status_worker.moveToThread(self.status_thread) # 将工作器移动到新线程

        # 连接信号和槽
        self.status_thread.started.connect(self.status_worker.run) # 线程启动时执行工作器
        self.status_worker.status_checked.connect(self.update_row_status) # 工作器检查完一行后更新UI
        
        # 任务完成后，退出线程事件循环，不删除对象 (由Python的GC处理)
        self.status_worker.finished.connect(self.status_thread.quit)
        
        self.status_thread.start() # 启动线程

    def update_row_status(self, row, has_record, has_tts, record_path, tts_path):
        """
        根据后台线程返回的结果，更新指定行的状态图标和Tooltip。
        :param row: 要更新的行号。
        :param has_record: 布尔值，表示是否存在真人录音。
        :param has_tts: 布尔值，表示是否存在 TTS 录音。
        :param record_path: 真人录音的路径 (如果存在)。
        :param tts_path: TTS 录音的路径 (如果存在)。
        """
        if row >= self.table_widget.rowCount():
            return # 防止行号越界

        # 创建一个 QWidget 作为单元格的容器，以实现图标居中显示
        cell_widget = QWidget()
        layout = QHBoxLayout(cell_widget)
        layout.setAlignment(Qt.AlignCenter) # 居中对齐
        layout.setContentsMargins(0, 0, 0, 0) # 移除边距，让图标更紧凑
        
        icon_label = QLabel() # 用于显示状态图标的 QLabel

        tooltip_parts = ["<b>音频资源状态:</b><hr>"] # 构建Tooltip的HTML内容
        
        # 根据真人录音和TTS录音的存在状态，设置不同的图标和Tooltip文本
        if has_record and has_tts:
            icon_label.setPixmap(self.icon_manager.get_icon("checked").pixmap(24, 24)) # 绿色对勾
            tooltip_parts.append(f"<font color='green'>〇 真人录音: 存在</font>")
            tooltip_parts.append(f"<font color='blue'>〇 TTS录音: 存在</font>")
        elif has_record:
            icon_label.setPixmap(self.icon_manager.get_icon("checked").pixmap(24, 24)) # 绿色对勾
            tooltip_parts.append(f"<font color='green'>〇 真人录音: 存在</font>")
            tooltip_parts.append(f"<font color='gray'>× TTS录音: 缺失</font>")
        elif has_tts:
            icon_label.setPixmap(self.icon_manager.get_icon("success").pixmap(24, 24)) # 蓝色对勾 (表示成功生成，但不一定是真人录音)
            tooltip_parts.append(f"<font color='gray'>× 真人录音: 缺失</font>")
            tooltip_parts.append(f"<font color='blue'>〇 TTS录音: 存在</font>")
        else:
            icon_label.setPixmap(self.icon_manager.get_icon("missing").pixmap(24, 24)) # 缺失图标
            tooltip_parts.append(f"<font color='gray'>× 真人录音: 缺失</font>")
            tooltip_parts.append(f"<font color='gray'>× TTS录音: 缺失</font>")

        tooltip_parts.append("<hr>右键单击可进行操作。")
        cell_widget.setToolTip("<br>".join(tooltip_parts)) # 设置Tooltip
        
        layout.addWidget(icon_label) # 将图标添加到容器布局
        self.table_widget.setCellWidget(row, 4, cell_widget) # 将容器Widget设置到单元格中

    def _stop_previous_status_check(self):
        """
        安全地停止并等待任何正在运行的旧状态检查线程。
        这确保在启动新检查前，旧的后台任务已完全结束，避免资源竞争和UI更新问题。
        """
        if self.status_thread and self.status_thread.isRunning():
            self.status_thread.quit() # 请求线程的事件循环退出
            # 等待线程真正结束。这是一个关键的同步点。
            # 如果在规定时间内线程没有结束，可能需要更强力的干预 (例如 terminate)，
            # 但通常 quit() + wait() 是最安全的。
            if not self.status_thread.wait(500): # 等待最多500毫秒
                print("警告：状态检查线程在500ms内未能正常停止，可能存在问题。", file=sys.stderr)
                # self.status_thread.terminate() # 强制终止是最后的手段，通常应避免

        # 清理对旧线程和工作器的引用，允许Python的垃圾回收器回收它们
        self.status_thread = None
        self.status_worker = None
    def send_to_tts(self, item):
        """
        [新增] 将选中的词表路径发送到TTS工具模块。
        """
        if not item: return
        
        # 确保钩子仍然有效
        if self.tts_utility_hook and hasattr(self.tts_utility_hook, 'load_wordlist_from_file'):
            wordlist_path = os.path.join(self.WORD_LIST_DIR, item.text())
            
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
