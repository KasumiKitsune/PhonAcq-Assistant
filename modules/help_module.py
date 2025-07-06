# --- START OF FILE modules/help_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "帮助文档"
MODULE_DESCRIPTION = "提供详细的程序使用指南和常见问题解答。"
# ---

import os
import sys
import re
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser, QListWidget, QListWidgetItem, QSplitter, QMenu
from PyQt5.QtCore import Qt, QUrl, QFileInfo
from PyQt5.QtGui import QPalette, QColor, QFont

try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False
    print("警告: markdown 库未安装，帮助文档可能无法正确显示。请运行: pip install markdown")

def get_base_path_for_help_module():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def create_page(parent_window):
    """模块的入口函数，用于创建帮助页面。"""
    return HelpPage(parent_window)

class HelpPage(QWidget):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.base_path = get_base_path_for_help_module()
        self.help_file_path = os.path.join(self.base_path, "assets", "help", "main_help.md")

        main_splitter = QSplitter(Qt.Horizontal, self)
        
        self.toc_list_widget = QListWidget()
        self.toc_list_widget.setFixedWidth(250)
        self.toc_list_widget.setObjectName("HelpTOC")
        self.populate_toc()

        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True)
        
        fi = QFileInfo(self.help_file_path)
        self.text_browser.setSearchPaths([fi.absolutePath()])

        self.text_browser.setContextMenuPolicy(Qt.CustomContextMenu)
        self.text_browser.customContextMenuRequested.connect(self.show_text_browser_context_menu)

        main_splitter.addWidget(self.toc_list_widget)
        main_splitter.addWidget(self.text_browser)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)
        
        layout = QHBoxLayout(self)
        # [修改] 为整个页面布局增加左右外边距，上下边距保持较小
        # (左, 上, 右, 下)
        layout.setContentsMargins(100, 10, 100, 10) 
        layout.addWidget(main_splitter)

        self.toc_list_widget.currentItemChanged.connect(self.on_toc_item_selected)
        # 初始加载由 on_sub_tab_changed -> update_help_content 触发

    def show_text_browser_context_menu(self, position):
        menu = QMenu(self.text_browser)
        
        # --- 编辑相关 ---
        copy_action = menu.addAction("复制")
        copy_action.setEnabled(self.text_browser.textCursor().hasSelection()) # 只有选中了内容才能复制
        
        select_all_action = menu.addAction("全选")
        menu.addSeparator()
        
        # --- 导航相关 ---
        go_to_top_action = menu.addAction("返回顶部")
        go_to_bottom_action = menu.addAction("滚动到底部")
        
        menu.addSeparator()
        
        # --- 内容刷新 ---
        reload_action = menu.addAction("重新加载文档")
        
        # --- 执行菜单并处理动作 ---
        action = menu.exec_(self.text_browser.mapToGlobal(position))
        
        if action == copy_action:
            self.text_browser.copy()
        elif action == select_all_action:
            self.text_browser.selectAll()
        elif action == go_to_top_action:
            self.text_browser.verticalScrollBar().setValue(0)
        elif action == go_to_bottom_action:
            self.text_browser.verticalScrollBar().setValue(self.text_browser.verticalScrollBar().maximum())
        elif action == reload_action:
            self.update_help_content()
        
    def on_toc_item_selected(self, current_item, previous_item):
        if current_item:
            anchor = current_item.data(Qt.UserRole)
            if anchor: self.text_browser.scrollToAnchor(anchor)

    def populate_toc(self):
        self.toc_list_widget.clear()
        
        welcome_item = QListWidgetItem("欢迎使用")
        welcome_item.setData(Qt.UserRole, "welcome")
        self.toc_list_widget.addItem(welcome_item)

        try:
            with open(self.help_file_path, 'r', encoding='utf-8') as f:
                h2_counter = 0
                h3_counter = 0
                for line in f:
                    match_h2 = re.match(r'^\s*##\s+(.+)', line)
                    if match_h2:
                        h2_counter += 1
                        h3_counter = 0
                        title = match_h2.group(1).strip()
                        anchor = f"h2-{h2_counter}"
                        item = QListWidgetItem(title)
                        item.setData(Qt.UserRole, anchor)
                        font = item.font(); font.setBold(True); item.setFont(font)
                        self.toc_list_widget.addItem(item)
                        continue

                    match_h3 = re.match(r'^\s*###\s+(.+)', line)
                    if match_h3:
                        h3_counter += 1
                        title = match_h3.group(1).strip()
                        anchor = f"h2-{h2_counter}-h3-{h3_counter}"
                        item = QListWidgetItem("    " + title)
                        item.setData(Qt.UserRole, anchor)
                        self.toc_list_widget.addItem(item)

        except FileNotFoundError:
            self.toc_list_widget.addItem(QListWidgetItem("帮助文件未找到!"))
        except Exception as e:
            self.toc_list_widget.addItem(QListWidgetItem(f"解析目录出错: {e}"))

    def _preprocess_markdown(self, md_text):
        lines = md_text.split('\n')
        processed_lines = []
        h2_counter = 0
        h3_counter = 0
        for line in lines:
            match_h2 = re.match(r'^(\s*##\s+)(.+)', line)
            if match_h2:
                h2_counter += 1
                h3_counter = 0
                anchor = f"h2-{h2_counter}"
                processed_lines.append(f'<a id="{anchor}"></a>')
                processed_lines.append(line)
                continue

            match_h3 = re.match(r'^(\s*###\s+)(.+)', line)
            if match_h3:
                h3_counter += 1
                anchor = f"h2-{h2_counter}-h3-{h3_counter}"
                processed_lines.append(f'<a id="{anchor}"></a>')
                processed_lines.append(line)
                continue
            
            if re.match(r'^#\s+欢迎使用', line):
                 processed_lines.append('<a id="welcome"></a>')
            
            processed_lines.append(line)
        return '\n'.join(processed_lines)

    def load_and_display_help(self):
        palette = self.text_browser.palette()
        bg_color = palette.color(QPalette.Base).name()
        text_color = palette.color(QPalette.Text).name()
        
        bg_qcolor = QColor(bg_color)
        luminance = (0.299 * bg_qcolor.red() + 0.587 * bg_qcolor.green() + 0.114 * bg_qcolor.blue()) / 255
        
        if luminance > 0.5: # 亮色主题
            h_color = "#2c3e50"; h_border_color = "#eaecef"; link_color = "#0366d6"; strong_color = "#24292e"
            code_bg_color = "#f6f8fa"; code_text_color = "#393A34"; tip_bg_color = "#f0fff0"; tip_border_color = "#a3d9a3"
            note_bg_color = "#fff8f0"; note_border_color = "#ffdccf"; img_border_color = "#ddd"
        else: # 暗色主题
            h_color = "#c9d1d9"; h_border_color = "#30363d"; link_color = "#58a6ff"; strong_color = "#c9d1d9"
            code_bg_color = "#161b22"; code_text_color = "#a9b1d6"; tip_bg_color = "#122117"; tip_border_color = "#2ea043"
            note_bg_color = "#211c12"; note_border_color = "#ffa657"; img_border_color = "#444"

        dynamic_css = f"""
            body {{ font-family: "Microsoft YaHei", sans-serif; font-size: 18px; line-height: 1.8; color: {text_color}; background-color: {bg_color}; padding: 10px 25px; }}
            h1, h2, h3, h4 {{ color: {h_color}; }}
            h1 {{ font-size: 32px; border-bottom: 2px solid {h_border_color}; padding-bottom: 15px; margin-bottom: 25px; }}
            h2 {{ font-size: 26px; border-bottom: 1px solid {h_border_color}; padding-bottom: 10px; margin-top: 50px; }}
            h3 {{ font-size: 22px; color: {h_color}; margin-top: 35px; border-left: 4px solid {h_border_color}; padding-left: 15px; }}
            p, li {{ margin: 15px 0; }}
            ul, ol {{ padding-left: 25px; }}
            code {{ background-color: {code_bg_color}; border: 1px solid {h_border_color}; padding: 3px 6px; border-radius: 4px; font-family: "Consolas", "Courier New", monospace; color: {code_text_color}; }}
            strong, b {{ color: {strong_color}; font-weight: bold; }}
            a {{ color: {link_color}; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            img {{ max-width: 90%; max-height: 450px; height: auto; width: auto; border: 1px solid {img_border_color}; border-radius: 4px; padding: 5px; margin: 20px auto; display: block; }}
            .note {{ background-color: {note_bg_color}; border-left: 5px solid {note_border_color}; padding: 15px 20px; margin: 20px 0; border-radius: 0 8px 8px 0; }}
            .tip {{ background-color: {tip_bg_color}; border-left: 5px solid {tip_border_color}; padding: 15px 20px; margin: 20px 0; border-radius: 0 8px 8px 0; }}
        """
        
        html_content = ""
        if MARKDOWN_AVAILABLE:
            try:
                with open(self.help_file_path, 'r', encoding='utf-8') as f:
                    md_text = f.read()
                
                preprocessed_md = self._preprocess_markdown(md_text)
                
                html_body = markdown.markdown(preprocessed_md, extensions=['extra', 'attr_list', 'md_in_html', 'fenced_code'])
                html_content = f'<html><head><style>{dynamic_css}</style></head><body>{html_body}</body></html>'
            except FileNotFoundError:
                html_content = f"<p>错误：帮助文件 main_help.md 未找到于 {self.help_file_path}</p>"
            except Exception as e:
                html_content = f"<p>解析帮助文件时出错: {e}</p>"
        else:
            html_content = "<p>错误：Markdown 库未安装。无法显示帮助文档。请运行 'pip install markdown'。</p>"
            
        self.text_browser.setHtml(html_content)

    def update_help_content(self):
        """当主题或其他可能影响帮助内容显示的设置更改时调用。"""
        self.populate_toc()
        self.load_and_display_help()
