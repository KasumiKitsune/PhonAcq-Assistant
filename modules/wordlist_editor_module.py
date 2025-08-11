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
    QStyledItemDelegate, QTabWidget, QStyle, QSlider, QGroupBox, QCheckBox, QFormLayout, QLineEdit, QStackedWidget, QFrame, QDialogButtonBox # [核心新增] 导入 QStyledItemDelegate
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
            
            # --- [核心修改] ---
            display_value = str(value) # 默认显示原始值
            if key == 'save_date':
                try:
                    # 尝试将 ISO 格式字符串解析为 datetime 对象
                    dt_object = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                    # 格式化为更友好的本地时间显示
                    display_value = dt_object.strftime('%Y-%m-%d %H:%M')
                except (ValueError, TypeError):
                    # 如果解析失败，安全回退
                    pass 
            
            val_item = QTableWidgetItem(display_value)
            # --- [修改结束] ---
            
            # 核心键 (如 format, version) 不可编辑
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
        self.config = self.parent_window.config
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
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self._perform_autosave)
        # [核心修复] 将 language_delegate 的实例化移到 _init_ui() 调用之前
        self.language_delegate = LanguageDelegate(self)

        self._init_ui() # 现在调用 _init_ui() 是安全的
        self.setup_connections_and_shortcuts()
        self.update_icons()
        self.apply_layout_settings()
        self.refresh_file_list()
        self._apply_autosave_setting()

    def _init_ui(self):
        """构建页面的用户界面布局。"""
        main_layout = QHBoxLayout(self)

        # --- 左侧面板：文件列表和操作按钮 ---
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        
        left_layout.addWidget(QLabel("单词表文件:"))
        self.file_list_widget = AnimatedListWidget(icon_manager=self.icon_manager)
        
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
        self.auto_detect_lang_btn = QPushButton("检测语言")
        # --- [核心修改 v2.0] ---
        # 1. 创建一个新的 QWidget 作为容器，而不是一个简单的 QLabel
        self.autosave_status_container = QWidget()
        status_layout = QHBoxLayout(self.autosave_status_container)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(5) # 图标和文字之间的间距

        # 2. 创建用于显示图标和文本的两个 QLabel
        self.autosave_status_icon = QLabel()
        self.autosave_status_text = QLabel("")
        self.autosave_status_text.setObjectName("SubtleStatusLabel")

        # 3. 将图标和文本标签添加到容器的布局中
        status_layout.addWidget(self.autosave_status_icon)
        status_layout.addWidget(self.autosave_status_text)
        
        # 4. 默认隐藏整个容器
        self.autosave_status_container.hide()
        # --- [修改结束] ---
        self.add_row_btn = QPushButton("添加行")
        self.remove_row_btn = QPushButton("移除选中行")
        self.remove_row_btn.setObjectName("ActionButton_Delete")
        
        table_btn_layout.addWidget(self.undo_btn)
        table_btn_layout.addWidget(self.redo_btn)
        table_btn_layout.addStretch()
        table_btn_layout.addWidget(self.auto_detect_lang_btn)
        table_btn_layout.addWidget(self.autosave_status_container)
        table_btn_layout.addStretch()
        table_btn_layout.addWidget(self.add_row_btn)
        table_btn_layout.addWidget(self.remove_row_btn)
        
        right_layout.addLayout(table_btn_layout)

        main_layout.addWidget(self.left_panel)
        main_layout.addWidget(right_panel, 1)

    def _apply_autosave_setting(self):
        """
        [新增] 根据当前配置，启动或停止自动保存定时器。
        """
        module_states = self.config.get("module_states", {}).get("wordlist_editor", {})
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
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 自动保存: {os.path.basename(path_to_save)}")
            
            self._write_to_file(path_to_save, is_silent=True)

            if not self.is_data_dirty():
                # --- [核心修改] ---
                # 1. 从 IconManager 获取 "success" 图标
                icon = self.icon_manager.get_icon("success")
                # 2. 将图标转换为适合标签显示的 QPixmap (16x16 像素)
                pixmap = icon.pixmap(QSize(24, 24))
                # 3. 设置图标和文本
                self.autosave_status_icon.setPixmap(pixmap)
                time_str = datetime.now().strftime('%H:%M')
                self.autosave_status_text.setText(f"已于 {time_str} 自动保存")
                
                # 4. 显示整个容器
                self.autosave_status_container.show()
                
                # 5. 启动一个4秒后自动隐藏容器的定时器
                QTimer.singleShot(4000, self.autosave_status_container.hide)
                # --- [修改结束] ---

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
        [v2.0 - 层级感知版]
        扫描词表目录，构建层级数据结构，并使用 AnimatedListWidget 显示。
        """
        if hasattr(self, 'parent_window'):
            self.apply_layout_settings()
            self.update_icons()

        base_dir = self.WORD_LIST_DIR
        hierarchical_data = []
        
        try:
            # --- 遍历词表根目录 ---
            for entry in os.scandir(base_dir):
                # 1. 处理根目录下的文件夹
                if entry.is_dir():
                    folder_path = entry.path
                    children = []
                    # 扫描子文件夹内的 .json 文件
                    for sub_entry in os.scandir(folder_path):
                        if sub_entry.is_file() and sub_entry.name.endswith('.json'):
                            children.append({
                                'type': 'item',
                                'text': sub_entry.name,
                                'icon': self.icon_manager.get_icon("document"),
                                'data': {'path': sub_entry.path}
                            })
                    
                    if children:
                        children.sort(key=lambda x: x['text'])
                        hierarchical_data.append({
                            'type': 'folder',
                            'text': entry.name,
                            'icon': self.icon_manager.get_icon("folder"),
                            'children': children
                        })

                # 2. 处理根目录下的 .json 文件
                elif entry.is_file() and entry.name.endswith('.json'):
                    hierarchical_data.append({
                        'type': 'item',
                        'text': entry.name,
                        'icon': self.icon_manager.get_icon("document"),
                        'data': {'path': entry.path}
                    })

            # 对顶层项目进行排序
            hierarchical_data.sort(key=lambda x: (x['type'] != 'folder', x['text']))

            # 使用 AnimatedListWidget 的新API设置数据
            self.file_list_widget.setHierarchicalData(hierarchical_data)

        except Exception as e:
            print(f"Error refreshing file list: {e}", file=sys.stderr)
            QMessageBox.critical(self, "错误", f"扫描词表目录时发生错误: {e}")

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

    def setup_connections_and_shortcuts(self):
        """设置所有UI控件的信号槽连接和键盘快捷键。"""
        # --- [核心修改] 在方法开头加载快捷键配置 ---
        module_states = self.config.get("module_states", {}).get("wordlist_editor", {})
        shortcuts = module_states.get("shortcuts", {})
        
        def get_shortcut(action_name, default):
            return shortcuts.get(action_name, default)
        # --- [修改结束] ---

        # 文件列表操作
        self.file_list_widget.currentItemChanged.connect(self.on_file_selected)
        self.file_list_widget.item_activated.connect(self.on_file_item_activated)
        self.file_list_widget.customContextMenuRequested.connect(self.show_file_context_menu)
        
        # 文件操作按钮
        self.new_btn.clicked.connect(self.new_wordlist)
        self.save_btn.clicked.connect(self.save_wordlist)
        self.save_as_btn.clicked.connect(self.save_wordlist_as)

        # 表格行操作按钮
        self.add_row_btn.clicked.connect(lambda: self.add_row())
        self.remove_row_btn.clicked.connect(self.remove_row)
        
        # 单元格编辑与撤销/重做
        self.table_widget.itemPressed.connect(self.on_item_pressed)
        self.table_widget.itemChanged.connect(self.on_item_changed_for_undo)
        self.table_widget.cellClicked.connect(self.on_cell_single_clicked)
        self.table_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_widget.customContextMenuRequested.connect(self.show_context_menu)
        
        self.undo_stack.indexChanged.connect(self.check_dirty_state)
        self.table_widget.itemChanged.connect(self.check_dirty_state)
        self.table_widget.viewport().installEventFilter(self)

        # 撤销/重做按钮和快捷键 (这些通常是标准的，不建议自定义)
        self.undo_action = self.undo_stack.createUndoAction(self, "撤销")
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.redo_action = self.undo_stack.createRedoAction(self, "重做")
        self.redo_action.setShortcut(QKeySequence.Redo)
        self.addAction(self.undo_action)
        self.addAction(self.redo_action)
        self.undo_btn.clicked.connect(self.undo_action.trigger)
        self.redo_btn.clicked.connect(self.redo_action.trigger)
        
        self.auto_detect_lang_btn.clicked.connect(self.auto_detect_languages)
        self.undo_stack.canUndoChanged.connect(self.undo_btn.setEnabled)
        self.undo_stack.canRedoChanged.connect(self.redo_btn.setEnabled)
        self.undo_btn.setEnabled(False)
        self.redo_btn.setEnabled(False)

        # 标准快捷键 (通常不建议自定义)
        QShortcut(QKeySequence.Save, self, self.save_wordlist)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, self.save_wordlist_as)
        QShortcut(QKeySequence.New, self, self.new_wordlist)
        
        # --- [核心修改] 应用自定义快捷键 ---
        QShortcut(QKeySequence(get_shortcut("copy", "Ctrl+C")), self, self.copy_selection)
        QShortcut(QKeySequence(get_shortcut("cut", "Ctrl+X")), self, self.cut_selection)
        QShortcut(QKeySequence(get_shortcut("paste", "Ctrl+V")), self, self.paste_selection)
        QShortcut(QKeySequence(get_shortcut("duplicate", "Ctrl+D")), self, self.duplicate_rows)
        QShortcut(QKeySequence(get_shortcut("move_up", "Alt+Up")), self, lambda: self.move_rows(-1))
        QShortcut(QKeySequence(get_shortcut("move_down", "Alt+Down")), self, lambda: self.move_rows(1))
        QShortcut(QKeySequence(get_shortcut("remove_row", "Ctrl+-")), self, self.remove_row)
        # --- [修改结束] ---
        
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

    def on_file_item_activated(self, item):
        """
        [已修复] 当一个最终的文件项目被激活时（通过双击或回车），
        打开其元数据配置。
        """
        # 内部逻辑完全不变，因为 AnimatedListWidget 已经确保了
        # 只有 'item' 类型的项目才会触发这个信号。
        self._configure_metadata(item)

    def show_file_context_menu(self, position):
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
            if self.tts_utility_hook:
                menu.addSeparator()
                tts_action = menu.addAction(self.icon_manager.get_icon("tts"), "发送到TTS工具")
                tts_action.triggered.connect(lambda: self.send_to_tts(item))
            menu.addSeparator()
            duplicate_action = menu.addAction(self.icon_manager.get_icon("copy"), "创建副本")
            delete_action = menu.addAction(self.icon_manager.get_icon("delete"), "删除")
            
            action = menu.exec_(self.file_list_widget.mapToGlobal(position))
            if action == config_action: self._configure_metadata(item)
            elif action == show_action: self._show_in_explorer(item)
            elif action == duplicate_action: self._duplicate_file(item)
            elif action == delete_action: self._delete_file(item)

        elif item_type == 'folder':
            # 文件夹菜单
            expand_action = menu.addAction(self.icon_manager.get_icon("open_folder"), "展开")
            # ... (可以添加重命名、删除文件夹等功能) ...
            action = menu.exec_(self.file_list_widget.mapToGlobal(position))
            if action == expand_action: self.file_list_widget._handle_item_activation(item)


    def send_to_splitter(self, item):
        if not item: return
        splitter_plugin = getattr(self, 'tts_splitter_plugin_active', None)
        if splitter_plugin:
            # [核心修复] 清理文件名
            clean_filename = item.text().replace(" *", "")
            wordlist_path = os.path.join(self.WORD_LIST_DIR, clean_filename)
            splitter_plugin.execute(wordlist_path=wordlist_path)

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
        filepath = self._get_path_from_item(item)
        if not filepath: return
        try:
            with open(filepath, 'r', encoding='utf-8') as f: data = json.load(f)
            if 'meta' not in data: data['meta'] = {"format": "standard_wordlist", "version": "1.0"}
            dialog = MetadataDialog(data['meta'], self, self.icon_manager)
            if dialog.exec_() == QDialog.Accepted:
                data['meta'] = dialog.get_metadata()
                with open(filepath, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
                QMessageBox.information(self, "成功", f"文件 '{item.text()}' 的元数据已更新。")
                if filepath == self.current_wordlist_path:
                    self.original_data_snapshot = self._build_data_from_table()
                    self.check_dirty_state()
        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"处理元数据时发生错误: {e}")

    # --- 文件加载和保存 ---

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
        [vFinal - 非破坏性选择版]
        - 点击空白处取消选择时，保留表格内容和编辑状态。
        - 只有在从一个文件切换到另一个文件时，才提示保存。
        - 点击文件夹不会触发状态更改。
        """
        # --- 守卫 1: 如果没有选中项，则什么都不做 ---
        if current is None:
            # 用户取消了选择，我们保留所有UI状态和数据不变。
            # 只需要确保“*”标记是正确的。
            self.check_dirty_state() 
            return

        current_data = current.data(AnimatedListWidget.HIERARCHY_DATA_ROLE)
        
        # --- 守卫 2: 如果选中的不是一个'item' (文件)，则也什么都不做 ---
        if not current_data or current_data.get('type') != 'item':
            # 用户点击了文件夹或返回按钮，我们不改变编辑区的内容。
            return

        # --- 只有当用户确实从一个文件切换到另一个文件时，才执行以下逻辑 ---
        if previous and previous != current:
            # 1. 请求“守卫”函数的许可
            can_proceed = self._confirm_and_handle_dirty_state(previous)

            # 2. 如果“守卫”不允许继续
            if not can_proceed:
                # 恢复之前的选择并中止
                self.file_list_widget.blockSignals(True)
                self.file_list_widget.setCurrentItem(previous)
                self.file_list_widget.blockSignals(False)
                self.check_dirty_state()
                return
        
        # --- 执行加载新文件的逻辑 ---
        
        # 清理旧项目的“*”标记（如果存在）
        if previous and previous.text().endswith(" *"):
             previous.setText(previous.text()[:-2])

        # 加载新文件
        self.current_wordlist_path = current_data.get('data', {}).get('path')
        self.load_file_to_table()
        self._apply_autosave_setting() # 检查是否需要为新文件启动定时器
        self.check_dirty_state() # 加载后检查状态

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
        [已修复] 创建一个新的空单词表。
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
        
        self.add_row()
        self.original_data_snapshot = self._build_data_from_table()
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

    # --- [核心新增] ---
    # 新增一个“守衛”方法，用于统一处理文件删除请求，决定是移入回收站还是永久删除。
    def _request_delete_wordlist(self, filepath):
        """
        [v2.0 - 配置感知版]
        处理单个词表文件的删除请求。
        根据用户设置决定是移入回收站还是永久删除。
        """
        if not filepath:
            return

        # 1. 从配置中读取用户首选的删除方式
        module_states = self.config.get("module_states", {}).get("wordlist_editor", {})
        use_recycle_bin_preference = module_states.get("use_recycle_bin", True)

        # 2. 尝试获取文件管理器插件实例
        file_manager_plugin = self.parent_window.plugin_manager.get_plugin_instance("com.phonacq.file_manager")
        is_plugin_available = file_manager_plugin and hasattr(file_manager_plugin, 'move_to_trash')

        delete_successful = False

        # 3. 决策逻辑：只有在用户首选且插件可用时，才使用回收站
        if use_recycle_bin_preference and is_plugin_available:
            # --- 方案A: 使用插件的回收站功能 ---
            success, message = file_manager_plugin.move_to_trash([filepath])
            if success:
                delete_successful = True
            else:
                QMessageBox.critical(self, "移至回收站失败", message)
        else:
            # --- 方案B: 回退到永久删除 ---
            # (此处的永久删除逻辑保持不变)
            reply = QMessageBox.question(self, "确认永久删除",
                                         f"您确定要永久删除文件 '{os.path.basename(filepath)}' 吗？\n此操作不可撤销！",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    os.remove(filepath)
                    delete_successful = True
                except Exception as e:
                    QMessageBox.critical(self, "删除失败", f"无法删除文件: {e}")

        # 4. 如果删除成功，则更新UI (此部分逻辑保持不变)
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

    def _write_to_file(self, filepath, is_silent=False):
        """
        [v2.0 - 静默模式版]
        将表格中的数据转换为 JSON 格式并写入文件。
        :param filepath: 目标文件路径。
        :param is_silent: 如果为True，则不显示成功提示弹窗。
        """
        groups_map = {}
        for row in range(self.table_widget.rowCount() - 1):
            try:
                group_item = self.table_widget.item(row, 0)
                word_item = self.table_widget.item(row, 1)
                if not group_item or not word_item or not group_item.text().isdigit() or not word_item.text().strip():
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
            except (ValueError, AttributeError) as e:
                print(f"写入文件时跳过无效行 {row}: {e}", file=sys.stderr)
                continue

        final_data_structure = {
            "meta": { "format": "standard_wordlist", "version": "1.0", "author": "PhonAcq Assistant", "save_date": datetime.now().isoformat() },
            "groups": [{"id": group_id, "items": items} for group_id, items in sorted(groups_map.items())]
        }
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(final_data_structure, f, indent=4, ensure_ascii=False)
            
            self.original_data_snapshot = self._build_data_from_table()
            self.undo_stack.setClean()
            self.check_dirty_state()
            
            # --- [核心修改] ---
            # 只有在非静默模式下才显示弹窗
            if not is_silent:
                QMessageBox.information(self, "成功", f"单词表已成功保存至:\n{filepath}")
            # --- [修改结束] ---

        except Exception as e:
            # 无论如何，保存失败的弹窗总是要显示的
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
        """[已修复] 将剪贴板内容粘贴到表格，稳健地处理新行创建。"""
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
            last_group_id = "1"
            if current_data_rows > 0:
                item = self.table_widget.item(current_data_rows - 1, 0)
                if item and item.text().isdigit(): last_group_id = item.text()
            
            # 使用一个循环来推送多个 "add" 命令
            for i in range(rows_to_add):
                new_row_data = [[last_group_id, "", "", ""]]
                cmd = WordlistRowOperationCommand(self, current_data_rows + i, new_row_data, 'add', description="为粘贴添加行")
                self.undo_stack.push(cmd)

        # 3. 逐个单元格进行粘贴
        for i, row_text in enumerate(rows_to_paste):
            cells = row_text.split('\t')
            for j, cell_text in enumerate(cells):
                target_row, target_col = start_row + i, start_col + j
                if target_col < self.table_widget.columnCount():
                    # (粘贴单元格的逻辑保持不变)
                    if target_col == 3:
                        item = self.table_widget.item(target_row, target_col)
                        old_code = item.data(Qt.UserRole) if item else ""
                        new_code = cell_text if cell_text in LANGUAGE_MAP.values() else ""
                        if old_code != new_code:
                            cmd = WordlistChangeLanguageCommand(self, target_row, old_code, new_code, "粘贴语言")
                            self.undo_stack.push(cmd)
                    else:
                        item = self.table_widget.item(target_row, target_col)
                        old_text = item.text() if item else ""
                        if old_text != cell_text:
                            cmd = WordlistChangeCellCommand(self, target_row, target_col, old_text, cell_text, "粘贴单元格")
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
        [已修复] 将选中的词表（无论层级）发送到TTS工具模块。
        """
        if not item: return
        
        # [核心修复] 使用我们之前创建的辅助函数来安全地获取完整路径
        wordlist_path = self._get_path_from_item(item)
        if not wordlist_path:
            QMessageBox.warning(self, "操作无效", "选中的项目不是一个有效的词表文件。")
            return

        # 确保钩子仍然有效
        if self.tts_utility_hook and hasattr(self.tts_utility_hook, 'load_wordlist_from_file'):
            # --- 切换Tab的逻辑保持不变 ---
            main_tabs = self.parent_window.main_tabs
            for i in range(main_tabs.count()):
                if main_tabs.tabText(i) == "实用工具":
                    main_tabs.setCurrentIndex(i)
                    sub_tabs = main_tabs.widget(i)
                    if sub_tabs and isinstance(sub_tabs, QTabWidget):
                         for j in range(sub_tabs.count()):
                            if sub_tabs.tabText(j) == "TTS 工具":
                                sub_tabs.setCurrentIndex(j)
                                break
                    break
            
            # 使用正确的、完整的路径调用TTS工具
            QTimer.singleShot(50, lambda: self.tts_utility_hook.load_wordlist_from_file(wordlist_path))
        else:
            QMessageBox.warning(self, "TTS工具不可用", "无法找到TTS工具或其加载功能。")
# --- [核心新增] ---
# 为“通用词表编辑器”模块定制的设置对话框
# --- [核心新增] ---
# 为“通用词表编辑器”模块定制的设置对话框
# --- [核心重构] 为通用词表编辑器定制的双栏设置对话框 ---
class SettingsDialog(QDialog):
    """
    一个专门用于配置“通用词表编辑器”模块的双栏设置对话框。
    """
    def __init__(self, parent_page, file_manager_available):
        super().__init__(parent_page)
        
        # 将传入的参数保存为实例属性
        self.parent_page = parent_page
        self.file_manager_available = file_manager_available
        
        self.setWindowTitle("通用词表编辑器设置")
        self.setWindowIcon(self.parent_page.parent_window.windowIcon())
        self.setStyleSheet(self.parent_page.parent_window.styleSheet())
        self.setMinimumSize(650, 450)
        
        # --- 1. 主布局：垂直分割，上方为内容，下方为按钮 ---
        dialog_layout = QVBoxLayout(self)
        dialog_layout.setSpacing(10)
        dialog_layout.setContentsMargins(0, 10, 0, 10)

        # 2. 内容区布局：水平分割，左侧为导航，右侧为页面
        content_layout = QHBoxLayout()
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # 3. 左侧导航栏
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(180)
        self.nav_list.setObjectName("SettingsNavList") # 用于QSS样式化
        content_layout.addWidget(self.nav_list)

        # 4. 右侧内容区 (使用 QStackedWidget)
        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1) # 占据剩余空间

        # 5. 将内容区（双栏布局）添加到主垂直布局中
        dialog_layout.addLayout(content_layout, 1)

        # 6. 添加分隔线和按钮栏
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        dialog_layout.addWidget(separator)
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.setContentsMargins(0, 0, 10, 0)
        dialog_layout.addWidget(self.button_box)

        # --- 7. 创建并填充各个设置页面 ---
        self._create_general_page()
        self._create_shortcut_page()

        # --- 8. 连接信号并加载设置 ---
        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        self.load_settings()
        self.nav_list.setCurrentRow(0)

    def _create_general_page(self):
        """创建“通用”设置页面。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # 自动保存组
        autosave_group = QGroupBox("自动保存")
        autosave_form_layout = QFormLayout(autosave_group)
        self.autosave_checkbox = QCheckBox("启用自动保存")
        autosave_interval_layout = QHBoxLayout()
        self.interval_slider = QSlider(Qt.Horizontal)
        self.interval_slider.setRange(1, 30)
        self.interval_label = QLabel("15 分钟")
        self.interval_label.setFixedWidth(60)
        autosave_interval_layout.addWidget(self.interval_slider)
        autosave_interval_layout.addWidget(self.interval_label)
        autosave_form_layout.addRow(self.autosave_checkbox)
        autosave_form_layout.addRow("保存间隔:", autosave_interval_layout)
        layout.addWidget(autosave_group)
        
        # 文件操作组
        file_op_group = QGroupBox("文件操作")
        file_op_form_layout = QFormLayout(file_op_group)
        self.recycle_bin_checkbox = QCheckBox("删除时移至回收站")
        self.recycle_bin_checkbox.setEnabled(self.file_manager_available)
        if not self.file_manager_available:
            self.recycle_bin_checkbox.setToolTip("此选项需要 '文件管理器' 插件被启用。")
        file_op_form_layout.addRow(self.recycle_bin_checkbox)
        layout.addWidget(file_op_group)
        
        layout.addStretch()
        
        self.nav_list.addItem("通用")
        self.stack.addWidget(page)
        
        self.autosave_checkbox.toggled.connect(self.interval_slider.setEnabled)
        self.interval_slider.valueChanged.connect(lambda v: self.interval_label.setText(f"{v} 分钟"))

    def _create_shortcut_page(self):
        """创建“快捷键”设置页面。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        
        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        
        self.shortcut_actions = {
            "copy": ("复制", "Ctrl+C"),
            "cut": ("剪切", "Ctrl+X"),
            "paste": ("粘贴", "Ctrl+V"),
            "duplicate": ("创建副本/重制行", "Ctrl+D"),
            "remove_row": ("删除行", "Ctrl+-"),
            "move_up": ("上移选中行", "Alt+Up"),
            "move_down": ("下移选中行", "Alt+Down"),
        }

        self.shortcut_inputs = {}
        for key, (label, default_shortcut) in self.shortcut_actions.items():
            input_widget = ShortcutLineEdit(default_shortcut=default_shortcut)
            self.shortcut_inputs[key] = input_widget
            form_layout.addRow(f"{label}:", input_widget)
        
        layout.addLayout(form_layout)
        layout.addStretch()

        self.nav_list.addItem("快捷键")
        self.stack.addWidget(page)

    def accept(self):
        """重写 accept，在关闭前保存所有页面的设置并关闭。"""
        self.save_settings()
        super().accept()

    def load_settings(self):
        """从主配置加载所有设置并更新UI。"""
        module_states = self.parent_page.config.get("module_states", {}).get("wordlist_editor", {})
        
        autosave_enabled = module_states.get("autosave_enabled", False)
        self.autosave_checkbox.setChecked(autosave_enabled)
        self.interval_slider.setValue(module_states.get("autosave_interval_minutes", 15))
        self.interval_slider.setEnabled(autosave_enabled)
        self.interval_label.setText(f"{self.interval_slider.value()} 分钟")
        self.recycle_bin_checkbox.setChecked(module_states.get("use_recycle_bin", True))

        saved_shortcuts = module_states.get("shortcuts", {})
        for key, input_widget in self.shortcut_inputs.items():
            default_shortcut = self.shortcut_actions[key][1]
            shortcut_str = saved_shortcuts.get(key, default_shortcut)
            input_widget.setText(shortcut_str)

    def save_settings(self):
        """将UI上的所有设置保存回主配置。"""
        main_window = self.parent_page.parent_window
        
        custom_shortcuts = {}
        for key, input_widget in self.shortcut_inputs.items():
            custom_shortcuts[key] = input_widget.text()

        settings_to_save = {
            "autosave_enabled": self.autosave_checkbox.isChecked(),
            "autosave_interval_minutes": self.interval_slider.value(),
            "use_recycle_bin": self.recycle_bin_checkbox.isChecked(),
            "shortcuts": custom_shortcuts,
        }
        
        current_settings = main_window.config.get("module_states", {}).get("wordlist_editor", {})
        current_settings.update(settings_to_save)
        main_window.update_and_save_module_state('wordlist_editor', current_settings)
# --- [核心新增] 自定义快捷键输入控件 ---
class ShortcutLineEdit(QLineEdit):
    """
    一个专门用于捕捉和显示QKeySequence的自定义输入框。
    它会阻止常规文本输入，并只响应按键组合。
    v1.1: 实现了恢复默认 (Backspace) 和清空 (Delete) 的功能。
    """
    def __init__(self, default_shortcut="", parent=None):
        super().__init__(parent)
        # [核心修改] 存储传入的默认快捷键
        self.default_shortcut = default_shortcut

        self.setReadOnly(True)
        self.setPlaceholderText("点击并按下快捷键...")
        # [核心修改] 更新工具提示以反映新功能
        self.setToolTip(
            "点击此输入框，然后按下您想设置的键盘快捷键组合。\n"
            "• 按 Backspace 键可恢复为默认值。\n"
            "• 按 Delete 键可清空快捷键。"
        )

    def keyPressEvent(self, event):
        """重写此方法以捕捉按键事件，而不是输入字符。"""
        key = event.key()
        
        if key in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta):
            return

        # --- [核心修改] 分别处理 Backspace 和 Delete ---
        if key == Qt.Key_Backspace:
            # Backspace: 恢复为默认值
            self.setText(self.default_shortcut)
            event.accept()
            return
            
        if key == Qt.Key_Delete:
            # Delete: 清空内容
            self.clear()
            event.accept()
            return
        # --- [修改结束] ---
            
        modifiers = event.modifiers()
        if modifiers:
            key_sequence = QKeySequence(modifiers | key)
        else:
            key_sequence = QKeySequence(key)
        
        self.setText(key_sequence.toString(QKeySequence.PortableText))
        event.accept()

    def mousePressEvent(self, event):
        """单击时清空内容，准备接收新输入。"""
        self.clear()
        self.setPlaceholderText("请按下快捷键...")
        super().mousePressEvent(event)

    def focusOutEvent(self, event):
        """失去焦点时恢复占位符文本。"""
        self.setPlaceholderText("点击并按下快捷键...")
        super().focusOutEvent(event)