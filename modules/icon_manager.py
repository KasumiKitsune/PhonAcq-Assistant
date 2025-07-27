# --- in modules/icon_manager.py ---

import os
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtSvg import QSvgRenderer

class IconManager:
    def __init__(self, default_icon_dir):
        if not os.path.isdir(default_icon_dir):
            try: os.makedirs(default_icon_dir, exist_ok=True)
            except OSError as e: print(f"错误: 无法创建默认图标目录: {e}")
        
        self.default_icon_dir = default_icon_dir
        self.theme_icon_dir = None
        self.theme_override_color = None
        self._icon_cache = {}
        
        # --- [核心修改] 新增一个标志来控制图标是否被主题禁用 ---
        self.icons_globally_disabled_by_theme = False

    def set_theme_icon_path(self, theme_icon_dir, icons_disabled=False):
        """
        设置当前主题的图标路径，并更新禁用状态。
        """
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

    def get_icon(self, icon_name):
        """
        获取一个图标。如果图标被主题禁用，则返回一个空图标。
        """
        # --- [核心修改] 在所有逻辑之前，检查全局禁用标志 ---
        if self.icons_globally_disabled_by_theme:
            return QIcon() # 立即返回一个空QIcon

        # --- 后续的图标查找和缓存逻辑保持不变 ---
        cache_key = f"{icon_name}_{self.theme_override_color.name() if self.theme_override_color else 'default'}"
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]

        icon_path = None
        possible_extensions = ['.svg', '.png', '.ico']

        if self.theme_icon_dir:
            for ext in possible_extensions:
                path = os.path.join(self.theme_icon_dir, f"{icon_name}{ext}")
                if os.path.exists(path): icon_path = path; break
        
        if not icon_path and self.default_icon_dir:
            default_svg_path = os.path.join(self.default_icon_dir, f"{icon_name}.svg")
            
            if os.path.exists(default_svg_path) and self.theme_override_color:
                try:
                    pixmap = self._colorize_svg(default_svg_path, self.theme_override_color)
                    icon = QIcon(pixmap); self._icon_cache[cache_key] = icon
                    return icon
                except Exception as e:
                    print(f"图标 '{icon_name}' 颜色覆盖失败: {e}")

            for ext in possible_extensions:
                path = os.path.join(self.default_icon_dir, f"{icon_name}{ext}")
                if os.path.exists(path): icon_path = path; break

        icon = QIcon(icon_path) if icon_path else QIcon()
        self._icon_cache[cache_key] = icon
        return icon

    # ... (_colorize_svg 和 clear_cache 方法保持不变) ...
    def _colorize_svg(self, svg_path, color):
        renderer = QSvgRenderer(svg_path)
        if not renderer.isValid(): return QPixmap()
        size = renderer.defaultSize()
        pixmap = QPixmap(size); pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap); renderer.render(painter)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), color); painter.end()
        return pixmap

    def clear_cache(self):
        self._icon_cache.clear()