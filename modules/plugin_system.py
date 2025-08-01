# --- START OF FILE modules/plugin_system.py (v1.2 with Pin & Manual) ---

import os
import sys
import json
import shutil
import zipfile
import importlib.util
import traceback
from abc import ABC, abstractmethod

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                             QTextBrowser, QPushButton, QDialogButtonBox, QWidget,
                             QLabel, QSplitter, QMessageBox, QFileDialog, QMenu)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon

# 尝试导入 Markdown 库，并设置一个全局标志
try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False
    print("[插件系统警告] 'markdown' 库未安装，插件手册功能将不可用。请运行: pip install markdown", file=sys.stderr)

# ==============================================================================
# 部分一: 插件API定义 (Plugin API Definition)
# ==============================================================================
class BasePlugin(ABC):
    """
    所有 PhonAcq 插件的基类。
    每个插件都必须继承此类并实现其所有抽象方法。
    """
    def __init__(self, main_window, plugin_manager):
        self.main_window = main_window
        self.plugin_manager = plugin_manager

    @abstractmethod
    def setup(self):
        """
        当插件被启用时调用。插件应在此处执行其初始化逻辑。
        如果成功则返回 True，失败则返回 False。
        """
        pass

    @abstractmethod
    def teardown(self):
        """当插件被禁用或程序退出时调用。负责清理所有资源。"""
        pass
    
    @abstractmethod
    def execute(self, **kwargs):
        """当用户通过UI（菜单或快捷按钮）执行此插件时调用。"""
        pass


# ==============================================================================
# 部分二: 插件管理器 (Plugin Manager)
# ==============================================================================
class PluginManager:
    """插件系统的核心控制器，负责插件的生命周期管理。"""
    def __init__(self, main_window, plugins_dir):
        self.main_window = main_window
        self.plugins_dir = plugins_dir
        self.available_plugins = {}
        self.active_plugins = {}

    def scan_plugins(self):
        self.available_plugins.clear()
        if not os.path.isdir(self.plugins_dir):
            try:
                os.makedirs(self.plugins_dir)
            except OSError as e:
                print(f"[插件错误] 无法创建插件目录: {e}", file=sys.stderr)
                return

        for plugin_id_dir in os.listdir(self.plugins_dir):
            plugin_path = os.path.join(self.plugins_dir, plugin_id_dir)
            if not os.path.isdir(plugin_path):
                continue
            
            manifest_path = os.path.join(plugin_path, 'plugin.json')
            if not os.path.isfile(manifest_path):
                continue

            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                
                required_keys = ["id", "name", "version", "main_file", "entry_class"]
                if not all(key in meta for key in required_keys):
                    print(f"[插件警告] 插件 '{plugin_id_dir}' 的 plugin.json 缺少必要字段，已跳过。", file=sys.stderr)
                    continue

                meta['path'] = plugin_path
                self.available_plugins[meta['id']] = meta
            except Exception as e:
                print(f"[插件错误] 加载插件 '{plugin_id_dir}' 的元数据失败: {e}", file=sys.stderr)

    def load_enabled_plugins(self):
        plugin_settings = self.main_window.config.get("plugin_settings", {})
        enabled_plugins = plugin_settings.get("enabled", [])
        for plugin_id in enabled_plugins:
            if plugin_id in self.available_plugins:
                self.enable_plugin(plugin_id)

    def enable_plugin(self, plugin_id):
        if plugin_id in self.active_plugins: return True
        if plugin_id not in self.available_plugins: return False

        meta = self.available_plugins[plugin_id]
        try:
            module_path = os.path.join(meta['path'], meta['main_file'])
            spec = importlib.util.spec_from_file_location(f"plugins.{meta['id']}", module_path)
            plugin_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(plugin_module)
            
            PluginClass = getattr(plugin_module, meta['entry_class'])
            plugin_instance = PluginClass(self.main_window, self)
            
            # [核心修改] 对 setup() 方法也进行 try...except 包裹
            if plugin_instance.setup() is False:
                 # 这是插件主动返回失败，不视为异常，但要记录
                 print(f"[插件错误] 插件 '{meta['name']}' 的 setup() 方法返回 False，已中止加载。", file=sys.stderr)
                 QMessageBox.warning(self.main_window, "插件启用失败", 
                                     f"插件 '{meta['name']}' 初始化失败。\n\n"
                                     "其 setup() 方法明确返回了失败信号，请检查插件逻辑或联系开发者。")
                 return False

            self.active_plugins[plugin_id] = plugin_instance
            return True
        except Exception as e:
            # [核心修改] 捕获所有在导入和实例化过程中可能发生的异常
            # 使用 traceback 模块获取详细的错误堆栈信息
            error_details = traceback.format_exc()
            print(f"[插件错误] 启用插件 '{meta['name']}' 失败: {e}\n{error_details}", file=sys.stderr)
            
            # 显示一个非模态的、内容更丰富的错误对话框
            error_msg_box = QMessageBox(self.main_window)
            error_msg_box.setIcon(QMessageBox.Critical)
            error_msg_box.setWindowTitle("插件启用错误")
            error_msg_box.setText(f"<b>启用插件 '{meta['name']}' 时发生严重错误。</b>")
            error_msg_box.setInformativeText("该插件将保持禁用状态，以防止主程序不稳定。")
            error_msg_box.setDetailedText(f"错误类型: {type(e).__name__}\n"
                                        f"错误信息: {e}\n\n"
                                        f"详细堆栈信息:\n{error_details}")
            # [关键] 设置为非模态，这样它不会阻塞主窗口
            error_msg_box.setWindowModality(Qt.NonModal)
            error_msg_box.show()
            
            return False # 明确返回失败

    def disable_plugin(self, plugin_id):
        if plugin_id not in self.active_plugins: return
        meta = self.available_plugins.get(plugin_id, {'name': plugin_id})
        try:
            self.active_plugins[plugin_id].teardown()
            del self.active_plugins[plugin_id]
        except Exception as e:
            print(f"[插件错误] 禁用插件 '{meta['name']}' 时出错: {e}", file=sys.stderr)

    def execute_plugin(self, plugin_id, **kwargs):
        if plugin_id not in self.active_plugins:
             QMessageBox.warning(self.main_window, "插件未启用", f"插件 '{self.available_plugins.get(plugin_id, {}).get('name', plugin_id)}' 未启用，无法执行。")
             return
        meta = self.available_plugins.get(plugin_id, {'name': plugin_id})
        try:
            self.active_plugins[plugin_id].execute(**kwargs)
        except Exception as e:
            # [核心修改] 捕获插件执行期间的所有异常
            error_details = traceback.format_exc()
            print(f"[插件错误] 执行插件 '{meta['name']}' 时出错: {e}\n{error_details}", file=sys.stderr)

            # 同样使用非阻塞的、带详细信息的错误对话框
            error_msg_box = QMessageBox(self.main_window)
            error_msg_box.setIcon(QMessageBox.Critical)
            error_msg_box.setWindowTitle("插件执行错误")
            error_msg_box.setText(f"<b>执行插件 '{meta['name']}' 时发生错误。</b>")
            error_msg_box.setInformativeText("请检查您的操作或插件配置。")
            error_msg_box.setDetailedText(f"错误类型: {type(e).__name__}\n"
                                        f"错误信息: {e}\n\n"
                                        f"详细堆栈信息:\n{error_details}")
            error_msg_box.setWindowModality(Qt.NonModal)
            error_msg_box.show()

    def teardown_all_plugins(self):
        for plugin_id in list(self.active_plugins.keys()):
            self.disable_plugin(plugin_id)

# ==============================================================================
# [新增] 手册查看器对话框
# ==============================================================================
class ManualViewerDialog(QDialog):
    """一个用于显示插件手册的简单对话框。"""
    def __init__(self, manual_path, plugin_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{plugin_name} - 使用手册")
        self.setMinimumSize(600, 700)
        self.resize(700, 800)

        layout = QVBoxLayout(self)
        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True)
        layout.addWidget(self.text_browser)
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        self._load_manual(manual_path)

    def _load_manual(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                md_content = f.read()
            html_content = markdown.markdown(md_content, extensions=['fenced_code', 'tables'])
            self.text_browser.setHtml(html_content)
        except Exception as e:
            self.text_browser.setHtml(f"<h1>错误</h1><p>无法读取或解析手册文件: {e}</p>")

# ==============================================================================
# 部分三: 插件管理对话框 (v1.2 with Pin & Manual)
# ==============================================================================
class PluginManagementDialog(QDialog):
    def __init__(self, plugin_manager, parent=None):
        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self.icon_manager = self.plugin_manager.main_window.icon_manager
        
        self.setWindowTitle("插件管理")
        self.setMinimumSize(800, 500)
        self._init_ui()
        self._connect_signals()
        self.populate_plugin_list()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.addWidget(QLabel("已发现的插件:"))
        self.plugin_list = QListWidget()
        self.plugin_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.plugin_list.setSpacing(2)
        self.plugin_list.setToolTip("所有在 'plugins' 文件夹中找到的插件。\n- 右键单击可进行操作，查看帮助等。")
        self.plugin_list.setContextMenuPolicy(Qt.CustomContextMenu)
        left_layout.addWidget(self.plugin_list)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.addWidget(QLabel("插件详情:"))
        self.plugin_details = QTextBrowser()
        self.plugin_details.setToolTip("显示当前选中插件的详细信息。")
        self.plugin_details.setOpenExternalLinks(True)
        right_layout.addWidget(self.plugin_details)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        
        main_layout.addWidget(splitter)

        bottom_layout = QHBoxLayout()
        self.add_btn = QPushButton("添加插件(.zip)...")
        # [核心修改] 为按钮设置 objectName
        self.add_btn.setObjectName("AccentButton") 
        self.add_btn.setToolTip("从一个 .zip 压缩包安装新插件。\n压缩包的根目录应只包含一个插件文件夹。")
        
        self.remove_btn = QPushButton("移除选中插件")
        # [核心修改] 为按钮设置 objectName
        self.remove_btn.setObjectName("ActionButton_Delete") 
        self.remove_btn.setToolTip("永久删除磁盘上选中的插件文件夹。")
        
        # [核心修改] 移除旧的 action_btn，因为它将被 add_btn 的新逻辑替代
        # self.action_btn = QPushButton() 
        
        self.open_folder_btn = QPushButton("打开插件文件夹")
        self.open_folder_btn.setToolTip("在系统的文件浏览器中打开 'plugins' 文件夹。")
        self.close_btn = QPushButton("关闭")
        self.close_btn.setToolTip("关闭此管理对话框。")

        bottom_layout.addWidget(self.add_btn)
        bottom_layout.addWidget(self.remove_btn)
        # bottom_layout.addWidget(self.action_btn) # [核心修改] 移除
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.open_folder_btn)
        bottom_layout.addWidget(self.close_btn)
        main_layout.addLayout(bottom_layout)

    def _connect_signals(self):
        self.plugin_list.currentItemChanged.connect(self.update_details_view)
        self.plugin_list.customContextMenuRequested.connect(self.show_plugin_context_menu)
        self.remove_btn.clicked.connect(self.remove_plugin)
        
        # [核心修改] action_btn 的信号连接现在是动态的，在 update_button_states 中处理
        # self.action_btn.clicked.connect(...) 
        
        self.open_folder_btn.clicked.connect(self.open_plugins_folder)
        self.close_btn.clicked.connect(self.accept)

    def update_button_states(self):
        is_item_selected = len(self.plugin_list.selectedItems()) > 0
        self.remove_btn.setEnabled(is_item_selected)
        
        # [核心修改] 动态设置 add_btn 的文本、图标、功能和状态
        
        # 1. 断开 add_btn 旧的信号连接
        try: self.add_btn.clicked.disconnect()
        except TypeError: pass

        # 2. 检查插件市场是否已安装并启用
        nexus_plugin_id = "com.phonacq.plugin_nexus"
        if nexus_plugin_id in self.plugin_manager.active_plugins:
            # 如果市场已启用，按钮变为“在线获取插件”
            self.add_btn.setText("添加插件(在线)...")
            self.add_btn.setIcon(self.icon_manager.get_icon("cloud_download"))
            self.add_btn.setToolTip("打开插件市场，发现并安装更多插件。")
            self.add_btn.clicked.connect(
                lambda: self.plugin_manager.execute_plugin(nexus_plugin_id, parent_dialog=self)
            )
        else:
            # 如果市场未启用，按钮恢复为“添加插件(.zip)...”
            self.add_btn.setText("添加插件(.zip)...")
            self.add_btn.setToolTip("从一个 .zip 压缩包安装新插件。\n压缩包的根目录应只包含一个插件文件夹。")
            self.add_btn.clicked.connect(self.add_plugin)

    def populate_plugin_list(self):
        current_id = self.plugin_list.currentItem().data(Qt.UserRole) if self.plugin_list.currentItem() else None
        self.plugin_list.clear()
        for plugin_id, meta in sorted(self.plugin_manager.available_plugins.items()):
            display_name = meta['name']
            if self.is_plugin_pinned(plugin_id):
                display_name += " 📌"
            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, plugin_id); item.setSizeHint(QSize(0, 40))
            if plugin_id in self.plugin_manager.active_plugins:
                item.setIcon(self.icon_manager.get_icon("success")); font = item.font(); font.setBold(True); item.setFont(font)
            else:
                icon_path = os.path.join(meta.get('path', ''), meta.get('icon', ''))
                if os.path.exists(icon_path): item.setIcon(QIcon(icon_path))
            self.plugin_list.addItem(item)
        if current_id:
            for i in range(self.plugin_list.count()):
                if self.plugin_list.item(i).data(Qt.UserRole) == current_id: self.plugin_list.setCurrentRow(i); break
        elif self.plugin_list.count() > 0: self.plugin_list.setCurrentRow(0)

    def update_details_view(self, current, previous):
        if not current: self.plugin_details.clear(); self.update_button_states(); return
        plugin_id = current.data(Qt.UserRole); meta = self.plugin_manager.available_plugins.get(plugin_id)
        if not meta: self.plugin_details.clear(); return
        details_html = f"<h3>{meta.get('name', 'N/A')}</h3><p><strong>版本:</strong> {meta.get('version', 'N/A')}<br><strong>作者:</strong> {meta.get('author', 'N/A')}</p><hr><p>{meta.get('description', '无详细描述。')}</p><p><i>ID: {meta.get('id')}</i></p>"
        self.plugin_details.setHtml(details_html); self.update_button_states()

    def show_plugin_context_menu(self, position):
        selected_items = self.plugin_list.selectedItems()
        if not selected_items: return

        # [核心修改] 获取所有选中项的ID
        selected_ids = [item.data(Qt.UserRole) for item in selected_items]
        
        # 判断选中项的共同状态
        all_enabled = all(pid in self.plugin_manager.active_plugins for pid in selected_ids)
        all_disabled = all(pid not in self.plugin_manager.active_plugins for pid in selected_ids)
        
        menu = QMenu(self)
        
        # --- 批量启用/禁用 ---
        if all_disabled:
            # 如果所有选中的都是禁用的，则显示“启用”
            menu.addAction(self.icon_manager.get_icon("play_audio"), f"启用选中的 {len(selected_ids)} 个插件").triggered.connect(
                lambda: self.toggle_selection_state(selected_ids, True))
        elif all_enabled:
            # 如果所有选中的都是启用的，则显示“禁用”
            menu.addAction(self.icon_manager.get_icon("end_session_dark"), f"禁用选中的 {len(selected_ids)} 个插件").triggered.connect(
                lambda: self.toggle_selection_state(selected_ids, False))
        else:
            # 如果选中项状态混合，则禁用批量操作
            mixed_action = menu.addAction("启用/禁用 (状态混合)")
            mixed_action.setEnabled(False)

        # --- [核心修改] 调整菜单布局 ---
        # 只有在单选时，才显示固定和查看帮助选项
        if len(selected_ids) == 1:
            plugin_id = selected_ids[0]
            is_enabled = plugin_id in self.plugin_manager.active_plugins
            is_pinned = self.is_plugin_pinned(plugin_id)

            # [核心修改] 禁用、固定、帮助之间不再有分隔线
            
            # 固定/取消固定
            if is_enabled:
                if is_pinned: 
                    menu.addAction(self.icon_manager.get_icon("unpin"), "取消固定").triggered.connect(
                        lambda: self.toggle_pin_state(plugin_id, False))
                else: 
                    menu.addAction(self.icon_manager.get_icon("pin"), "固定到工具栏").triggered.connect(
                        lambda: self.toggle_pin_state(plugin_id, True))
            
            # 查看帮助手册
            meta = self.plugin_manager.available_plugins.get(plugin_id, {})
            manual_file = meta.get('manual_file')
            if manual_file and os.path.exists(os.path.join(meta.get('path', ''), manual_file)):
                action_help = menu.addAction(self.icon_manager.get_icon("help"), "查看帮助手册")
                action_help.setEnabled(MARKDOWN_AVAILABLE)
                # [核心修改] 这里的 show_manual_for_current_plugin 需要微调
                action_help.triggered.connect(lambda: self.show_manual_for_item(self.plugin_list.currentItem()))

        # --- 批量移除 ---
        # 移除操作始终放在最后，并用分隔线隔开
        menu.addSeparator()
        menu.addAction(self.icon_manager.get_icon("delete"), f"移除选中的 {len(selected_ids)} 个插件...").triggered.connect(
            self.remove_plugin) # remove_plugin 方法将被修改以处理多选
        
        menu.exec_(self.plugin_list.mapToGlobal(position))

    def show_manual_for_current_plugin(self):
        if not MARKDOWN_AVAILABLE: QMessageBox.warning(self, "功能缺失", "无法显示帮助手册，'markdown' 库未安装。"); return
        current_item = self.plugin_list.currentItem();
        if not current_item: return
        plugin_id = current_item.data(Qt.UserRole); meta = self.plugin_manager.available_plugins.get(plugin_id)
        if not meta or not meta.get('manual_file'): return
        manual_path = os.path.join(meta['path'], meta['manual_file'])
        if os.path.exists(manual_path): ManualViewerDialog(manual_path, meta['name'], self).exec_()
        else: QMessageBox.warning(self, "文件未找到", f"插件 '{meta['name']}' 的手册文件 '{meta['manual_file']}' 未找到。")
    
    def toggle_plugin_state(self, plugin_id, enable):
        if enable: self.plugin_manager.enable_plugin(plugin_id)
        else:
            if self.is_plugin_pinned(plugin_id): self.toggle_pin_state(plugin_id, False) # 禁用时自动取消固定
            self.plugin_manager.disable_plugin(plugin_id)
        self.save_config(); self.populate_plugin_list()
        self.plugin_manager.main_window.update_pinned_plugins_ui()

    def toggle_pin_state(self, plugin_id, pin):
        """
        切换一个插件的固定状态，并立即刷新所有相关的UI。
        
        :param plugin_id: 要操作的插件ID。
        :param pin: True 表示固定，False 表示取消固定。
        """
        config = self.plugin_manager.main_window.config
        
        # 使用 setdefault 确保键总是存在，避免 KeyError
        plugin_settings = config.setdefault("plugin_settings", {})
        pinned_plugins = plugin_settings.setdefault("pinned", [])

        if pin:
            # 检查是否已达上限
            if len(pinned_plugins) >= 3:
                QMessageBox.warning(self, "固定数量已达上限", "工具栏最多只能固定3个插件。")
                return
            # 添加到列表（如果不存在）
            if plugin_id not in pinned_plugins:
                pinned_plugins.append(plugin_id)
        else:
            # 从列表中移除（如果存在）
            if plugin_id in pinned_plugins:
                pinned_plugins.remove(plugin_id)
        
        # 1. 保存配置
        self.save_config(config)
        
        # 2. 刷新本对话框内的插件列表（为了显示/隐藏 📌 图标）
        self.populate_plugin_list()
        
        # 3. [核心修复] 主动通知并调用主窗口的方法，来刷新右上角的固定插件栏
        self.plugin_manager.main_window.update_pinned_plugins_ui()

    def is_plugin_pinned(self, plugin_id):
        return plugin_id in self.plugin_manager.main_window.config.get("plugin_settings", {}).get("pinned", [])

    def save_config(self, config_to_save=None):
        config = config_to_save if config_to_save is not None else self.plugin_manager.main_window.config
        plugin_settings = config.setdefault("plugin_settings", {})
        plugin_settings["enabled"] = list(self.plugin_manager.active_plugins.keys())
        try:
            with open(self.plugin_manager.main_window.SETTINGS_FILE, 'w', encoding='utf-8') as f: json.dump(config, f, indent=4)
        except Exception as e: print(f"保存插件配置失败: {e}", file=sys.stderr)

    def add_plugin(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "选择插件压缩包", "", "ZIP 压缩包 (*.zip)");
        if not filepath: return
        try:
            with zipfile.ZipFile(filepath, 'r') as zip_ref:
                top_level_dirs = {os.path.normpath(f).split(os.sep)[0] for f in zip_ref.namelist() if f}
                if len(top_level_dirs) != 1: raise ValueError("ZIP压缩包格式不正确，根目录应只包含一个插件文件夹。")
                plugin_folder_name = list(top_level_dirs)[0]; target_path = os.path.join(self.plugin_manager.plugins_dir, plugin_folder_name)
                if os.path.exists(target_path): raise FileExistsError(f"插件目录 '{plugin_folder_name}' 已存在。请先移除旧版本。")
                zip_ref.extractall(self.plugin_manager.plugins_dir)
            QMessageBox.information(self, "成功", f"插件 '{plugin_folder_name}' 已成功添加。"); self.plugin_manager.scan_plugins(); self.populate_plugin_list()
        except Exception as e: QMessageBox.critical(self, "添加失败", f"添加插件时发生错误:\n{e}")

    def toggle_selection_state(self, plugin_ids, enable):
        for pid in plugin_ids:
            # 调用已有的单项切换方法，但暂时不保存配置和刷新UI
            if enable:
                self.plugin_manager.enable_plugin(pid)
            else:
                if self.is_plugin_pinned(pid):
                    self.toggle_pin_state(pid, False) # 禁用时自动取消固定
                self.plugin_manager.disable_plugin(pid)
        
        # 所有操作完成后，进行一次性的配置保存和UI刷新
        self.save_config()
        self.populate_plugin_list()
        self.plugin_manager.main_window.update_pinned_plugins_ui()

    def remove_plugin(self):
        selected_items = self.plugin_list.selectedItems()
        if not selected_items: return
        
        # 收集要删除的插件信息
        plugins_to_remove = []
        for item in selected_items:
            plugin_id = item.data(Qt.UserRole)
            meta = self.plugin_manager.available_plugins.get(plugin_id)
            if meta:
                plugins_to_remove.append(meta)

        if not plugins_to_remove: return

        # 构建确认信息
        count = len(plugins_to_remove)
        names_preview = "\n".join([f"- {meta['name']}" for meta in plugins_to_remove[:5]])
        if count > 5:
            names_preview += "\n- ..."

        reply = QMessageBox.warning(self, "确认移除", 
                                     f"您确定要永久删除选中的 {count} 个插件吗？\n\n{names_preview}\n\n"
                                     "此操作将从磁盘上删除它们的文件夹及其所有内容。",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            error_happened = False
            for meta in plugins_to_remove:
                plugin_id = meta['id']
                try:
                    # 在删除前先禁用
                    if plugin_id in self.plugin_manager.active_plugins:
                        self.plugin_manager.disable_plugin(plugin_id)
                    # 删除文件夹
                    shutil.rmtree(meta['path'])
                except Exception as e:
                    QMessageBox.critical(self, "移除失败", f"移除插件 '{meta['name']}' 时发生错误:\n{e}")
                    error_happened = True
                    break # 发生错误时停止后续操作

            if not error_happened:
                QMessageBox.information(self, "成功", f"{count} 个插件已被移除。")
            
            # 统一处理配置保存和UI刷新
            self.save_config()
            self.plugin_manager.scan_plugins()
            self.populate_plugin_list()
            self.plugin_manager.main_window.update_pinned_plugins_ui()

    # [重构] 修改 show_manual_for_current_plugin 使其更通用
    def show_manual_for_item(self, item):
        if not MARKDOWN_AVAILABLE: 
            QMessageBox.warning(self, "功能缺失", "无法显示帮助手册，'markdown' 库未安装。")
            return
        if not item: return

        plugin_id = item.data(Qt.UserRole)
        meta = self.plugin_manager.available_plugins.get(plugin_id)
        if not meta or not meta.get('manual_file'): return
        
        manual_path = os.path.join(meta['path'], meta['manual_file'])
        if os.path.exists(manual_path):
            ManualViewerDialog(manual_path, meta['name'], self).exec_()
        else:
            QMessageBox.warning(self, "文件未找到", f"插件 '{meta['name']}' 的手册文件 '{meta['manual_file']}' 未找到。")
                
    def open_plugins_folder(self):
        path = self.plugin_manager.plugins_dir;
        if not os.path.isdir(path): os.makedirs(path)
        try:
            if sys.platform == 'win32': os.startfile(os.path.realpath(path))
            elif sys.platform == 'darwin': os.system(f'open "{path}"')
            else: os.system(f'xdg-open "{path}"')
        except Exception as e: QMessageBox.critical(self, "打开失败", f"无法打开插件文件夹: {e}")