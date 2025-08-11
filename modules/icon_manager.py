# --- 模块元数据 ---
MODULE_NAME = "图标管理器"
MODULE_DESCRIPTION = "负责应用程序所有图标的加载、缓存和主题化着色管理。"
import os
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QImage
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtSvg import QSvgRenderer

class IconManager:
    def __init__(self, default_icon_dir):
        # __init__ 方法保持不变
        if not os.path.isdir(default_icon_dir):
            try:
                os.makedirs(default_icon_dir, exist_ok=True)
            except OSError as e:
                print(f"错误: 无法创建默认图标目录: {e}")
        
        self.default_icon_dir = default_icon_dir
        self.theme_icon_dir = None
        self.theme_override_color = None
        self.icons_globally_disabled_by_theme = False
        self.is_dark_theme = False
        self._icon_cache = {}
        self.functional_icon_exemptions = {
            "checked", "error", "info", "success", "missing", "saved", 
            "settings", "show", "hidden", "lock", "unlock", "delete",
            "cancel", "warning", "critical"
        }

    # set_theme_icon_path, set_theme_override_color, set_dark_mode 保持不变
    def set_theme_icon_path(self, theme_icon_dir, icons_disabled=False):
        self.icons_globally_disabled_by_theme = icons_disabled
        if theme_icon_dir and os.path.isdir(theme_icon_dir):
            self.theme_icon_dir = theme_icon_dir
        else:
            self.theme_icon_dir = None
        self.clear_cache()

    def set_theme_override_color(self, color):
        if self.theme_override_color != color:
            self.theme_override_color = color
            self.clear_cache()

    def set_dark_mode(self, is_dark):
        if self.is_dark_theme != is_dark:
            self.is_dark_theme = is_dark
            self.clear_cache()

    def get_icon(self, icon_name):
        """
        [v1.2 - PNG着色版]
        获取一个图标，并根据主题类型自动为 SVG 和 PNG 图标着色。
        """
        if self.icons_globally_disabled_by_theme and icon_name not in self.functional_icon_exemptions:
            return QIcon()

        effective_color = self.theme_override_color
        if effective_color is None and self.is_dark_theme:
            effective_color = QColor(Qt.white)

        cache_key = f"{icon_name}_{effective_color.name() if effective_color else 'default'}"
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]

        icon = QIcon() # 创建一个默认的空图标
        icon_path = None
        possible_extensions = ['.svg', '.png', '.ico']

        # 1. 优先查找主题提供的图标文件 (无需着色)
        if self.theme_icon_dir:
            for ext in possible_extensions:
                path = os.path.join(self.theme_icon_dir, f"{icon_name}{ext}")
                if os.path.exists(path):
                    icon_path = path
                    break
        
        if icon_path:
            icon = QIcon(icon_path)

        # 2. 如果主题未提供，则处理默认图标（可能需要着色）
        else:
            found_default_path = None
            # 优先查找SVG，其次是PNG，最后是ICO
            for ext in ['.svg', '.png', '.ico']:
                path = os.path.join(self.default_icon_dir, f"{icon_name}{ext}")
                if os.path.exists(path):
                    found_default_path = path
                    break
            
            if found_default_path:
                # 如果需要着色...
                if effective_color:
                    try:
                        if found_default_path.endswith('.svg'):
                            pixmap = self._colorize_svg(found_default_path, effective_color)
                            if not pixmap.isNull(): icon = QIcon(pixmap)
                        elif found_default_path.endswith('.png'):
                            original_pixmap = QPixmap(found_default_path)
                            if not original_pixmap.isNull():
                                colored_pixmap = self._colorize_pixmap(original_pixmap, effective_color)
                                if not colored_pixmap.isNull(): icon = QIcon(colored_pixmap)
                    except Exception as e:
                        print(f"图标 '{icon_name}' 颜色覆盖失败: {e}")
                        # 如果着色失败，则回退到直接加载
                        icon = QIcon(found_default_path)
                
                # 如果不需要着色，或者着色失败后，icon 仍然是空的
                if icon.isNull():
                    icon = QIcon(found_default_path)

        # 3. 缓存并返回最终结果
        self._icon_cache[cache_key] = icon
        return icon

    # has_icon 方法保持不变
    def has_icon(self, icon_name):
        if self.theme_icon_dir:
            for ext in ['.svg', '.png']:
                if os.path.exists(os.path.join(self.theme_icon_dir, f"{icon_name}{ext}")):
                    return True
        if self.default_icon_dir:
            for ext in ['.svg', '.png']:
                if os.path.exists(os.path.join(self.default_icon_dir, f"{icon_name}{ext}")):
                    return True
        return False

    def get_icon_from_path(self, path):
        """
        [新增] 从一个给定的绝对文件路径加载图标，并应用当前主题的着色和缓存规则。
        这主要用于加载插件等去中心化的图标资源。
        """
        if not path or not os.path.exists(path):
            return QIcon()

        effective_color = self.theme_override_color
        if effective_color is None and self.is_dark_theme:
            effective_color = QColor(Qt.white)

        # 缓存键现在基于路径和颜色
        cache_key = f"path_{path}_{effective_color.name() if effective_color else 'default'}"
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]

        icon = QIcon()
        # 如果需要着色...
        if effective_color:
            try:
                if path.endswith('.svg'):
                    pixmap = self._colorize_svg(path, effective_color)
                    if not pixmap.isNull(): icon = QIcon(pixmap)
                elif path.endswith('.png'):
                    original_pixmap = QPixmap(path)
                    if not original_pixmap.isNull():
                        colored_pixmap = self._colorize_pixmap(original_pixmap, effective_color)
                        if not colored_pixmap.isNull(): icon = QIcon(colored_pixmap)
            except Exception as e:
                print(f"从路径 '{path}' 着色图标失败: {e}")

        # 如果不需要着色，或者着色失败，则直接加载
        if icon.isNull():
            icon = QIcon(path)

        self._icon_cache[cache_key] = icon
        return icon

    def _colorize_svg(self, svg_path, color):
        renderer = QSvgRenderer(svg_path)
        if not renderer.isValid(): return QPixmap()
        size = renderer.defaultSize()
        if size.isEmpty(): size = QSize(24, 24) 
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), color)
        painter.end()
        return pixmap

    def _colorize_pixmap(self, pixmap, color):
        """
        [新增] 将一个光栅图像 (如PNG) 的非透明部分着色。
        """
        # 创建一个支持Alpha通道的QImage作为我们的画布
        image = QImage(pixmap.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent) # 用透明色填充画布

        painter = QPainter(image)
        # 1. 将原始的Pixmap绘制到我们的画布上
        painter.drawPixmap(0, 0, pixmap)
        # 2. 设置混合模式为 SourceIn
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        # 3. 用目标颜色填充整个画布，混合模式会确保颜色只应用在已存在像素的地方
        painter.fillRect(image.rect(), color)
        painter.end()

        # 将着色后的QImage转换回QPixmap并返回
        return QPixmap.fromImage(image)

    def clear_cache(self):
        self._icon_cache.clear()