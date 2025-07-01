# --- START OF FILE modules/icon_manager.py ---

# --- 模块元数据 ---
MODULE_NAME = "图标管理器"
MODULE_DESCRIPTION = "管理和提供应用程序的自定义和默认图标。"
# ---

import os
from PyQt5.QtGui import QIcon

class IconManager:
    def __init__(self, default_icon_dir):
        """
        初始化图标管理器。
        :param default_icon_dir: 存放默认图标的目录路径。
        """
        if not os.path.isdir(default_icon_dir):
            print(f"警告: 默认图标目录不存在: {default_icon_dir}")
            # 创建目录以避免后续错误
            try:
                os.makedirs(default_icon_dir, exist_ok=True)
            except OSError as e:
                print(f"错误: 无法创建默认图标目录: {e}")
        
        self.default_icon_dir = default_icon_dir
        self.theme_icon_dir = None
        self._icon_cache = {}

    def set_theme_icon_path(self, theme_icon_dir):
        """
        设置当前主题的图标目录路径。
        :param theme_icon_dir: 主题指定的图标目录，可以是相对路径或绝对路径。
        """
        if theme_icon_dir and os.path.isdir(theme_icon_dir):
            self.theme_icon_dir = theme_icon_dir
        else:
            if theme_icon_dir:
                print(f"警告: 主题图标目录不存在: {theme_icon_dir}")
            self.theme_icon_dir = None
        self.clear_cache() # 切换主题时清空缓存

    def get_icon(self, icon_name):
        """
        获取一个图标，实现分层回退逻辑。
        优先从主题图标目录查找，然后是默认图标目录。
        :param icon_name: 图标的名称，不带扩展名 (例如: 'save', 'delete')。
        :return: QIcon 对象，如果找不到则返回一个空的 QIcon。
        """
        if icon_name in self._icon_cache:
            return self._icon_cache[icon_name]

        icon_path = None
        possible_extensions = ['.svg', '.png', '.ico']

        # 1. 在主题图标目录中查找
        if self.theme_icon_dir:
            for ext in possible_extensions:
                path = os.path.join(self.theme_icon_dir, f"{icon_name}{ext}")
                if os.path.exists(path):
                    icon_path = path
                    break
        
        # 2. 如果主题目录中没有，则在默认图标目录中查找
        if not icon_path and self.default_icon_dir:
            for ext in possible_extensions:
                path = os.path.join(self.default_icon_dir, f"{icon_name}{ext}")
                if os.path.exists(path):
                    icon_path = path
                    break
        
        icon = QIcon(icon_path) if icon_path else QIcon()
        self._icon_cache[icon_name] = icon
        return icon

    def clear_cache(self):
        """清空图标缓存，在切换主题时调用。"""
        self._icon_cache.clear()