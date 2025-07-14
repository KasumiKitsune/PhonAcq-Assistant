# --- 模块元数据 ---
MODULE_NAME = "图标管理器"
MODULE_DESCRIPTION = "管理和提供应用程序的自定义和默认图标。"
# ---

import os
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtSvg import QSvgRenderer

class IconManager:
    def __init__(self, default_icon_dir):
        """
        初始化图标管理器。
        :param default_icon_dir: 存放默认图标的目录路径。
        """
        if not os.path.isdir(default_icon_dir):
            try:
                os.makedirs(default_icon_dir, exist_ok=True)
            except OSError as e:
                print(f"错误: 无法创建默认图标目录: {e}")
        
        self.default_icon_dir = default_icon_dir
        self.theme_icon_dir = None
        self.theme_override_color = None # [新增] 用于存储主题的覆盖颜色
        self._icon_cache = {}

    def set_theme_icon_path(self, theme_icon_dir):
        """
        设置当前主题的图标目录路径。
        :param theme_icon_dir: 主题指定的图标目录。
        """
        if theme_icon_dir and os.path.isdir(theme_icon_dir):
            self.theme_icon_dir = theme_icon_dir
        else:
            self.theme_icon_dir = None
        self.clear_cache()

    def set_theme_override_color(self, color):
        """
        [新增] 设置主题指定的图标覆盖颜色。
        :param color: 一个 QColor 对象，或 None。
        """
        if self.theme_override_color != color:
            self.theme_override_color = color
            self.clear_cache()

    def get_icon(self, icon_name):
        """
        获取一个图标，实现分层回退逻辑。
        优先级：主题图标包 > 自动取色 > 默认图标包。
        :param icon_name: 图标的名称，不带扩展名。
        :return: QIcon 对象，如果找不到则返回一个空的 QIcon。
        """
        # [修改] 缓存键现在需要考虑覆盖颜色
        cache_key = f"{icon_name}_{self.theme_override_color.name() if self.theme_override_color else 'default'}"
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]

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
            default_svg_path = os.path.join(self.default_icon_dir, f"{icon_name}.svg")
            
            # [新增] 检查是否存在默认SVG文件并且主题设置了覆盖颜色
            if os.path.exists(default_svg_path) and self.theme_override_color:
                try:
                    # 尝试进行颜色覆盖
                    pixmap = self._colorize_svg(default_svg_path, self.theme_override_color)
                    icon = QIcon(pixmap)
                    self._icon_cache[cache_key] = icon
                    return icon
                except Exception as e:
                    print(f"图标 '{icon_name}' 颜色覆盖失败: {e}")

            # 如果无法进行颜色覆盖，则按原逻辑查找
            for ext in possible_extensions:
                path = os.path.join(self.default_icon_dir, f"{icon_name}{ext}")
                if os.path.exists(path):
                    icon_path = path
                    break

        icon = QIcon(icon_path) if icon_path else QIcon()
        self._icon_cache[cache_key] = icon
        return icon

    def _colorize_svg(self, svg_path, color):
        """
        [新增] 将SVG文件渲染为指定颜色的QPixmap。
        :param svg_path: SVG文件的路径。
        :param color: 目标 QColor。
        :return: 渲染后的 QPixmap。
        """
        renderer = QSvgRenderer(svg_path)
        if not renderer.isValid():
            return QPixmap() # 返回空Pixmap如果SVG无效

        # 创建一个与SVG原始大小相同的空白Pixmap
        size = renderer.defaultSize()
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent) # 用透明色填充

        # 使用QPainter进行绘制
        painter = QPainter(pixmap)
        renderer.render(painter) # 1. 首先将原始SVG（作为蒙版）绘制到pixmap上

        # 2. 设置混合模式为SourceIn，这会保留目标（pixmap）的alpha通道，
        #    但使用源（我们指定的颜色）的颜色信息。
        #    效果是：只在原始图标有内容的地方填充我们指定的颜色。
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)

        # 3. 用目标颜色填充整个区域
        painter.fillRect(pixmap.rect(), color)
        painter.end()

        return pixmap

    def clear_cache(self):
        """清空图标缓存，在切换主题时调用。"""
        self._icon_cache.clear()