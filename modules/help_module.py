# --- START OF FILE help_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "帮助文档"
MODULE_DESCRIPTION = "提供详细的程序使用指南和常见问题解答。"
# ---

import os
import sys
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser, QListWidget, QListWidgetItem, QSplitter, QMenu
from PyQt5.QtCore import Qt, QUrl, QFileInfo
from PyQt5.QtGui import QPalette, QColor

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
        self.image_search_path = QUrl.fromLocalFile(os.path.join(self.base_path, "assets", "help")).toString() + "/"


        main_splitter = QSplitter(Qt.Horizontal, self)
        
        self.toc_list_widget = QListWidget()
        self.toc_list_widget.setFixedWidth(250)
        self.toc_list_widget.setObjectName("HelpTOC")
        self.populate_toc()

        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True)
        
        fi = QFileInfo(self.help_file_path)
        self.text_browser.setSearchPaths([fi.absolutePath()])


        light_palette = QPalette()
        light_palette.setColor(QPalette.Base, QColor("#FFF8F6")) 
        light_palette.setColor(QPalette.Text, QColor("#2C160D")) 
        self.text_browser.setPalette(light_palette)
        
        self.text_browser.setContextMenuPolicy(Qt.CustomContextMenu)
        self.text_browser.customContextMenuRequested.connect(self.show_text_browser_context_menu)

        main_splitter.addWidget(self.toc_list_widget)
        main_splitter.addWidget(self.text_browser)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(main_splitter)

        self.toc_list_widget.currentItemChanged.connect(self.on_toc_item_selected)
        self.load_and_display_help() 

    def show_text_browser_context_menu(self, position):
        menu = QMenu()
        copy_action = menu.addAction("复制")
        select_all_action = menu.addAction("全选")
        action = menu.exec_(self.text_browser.mapToGlobal(position))
        if action == copy_action: self.text_browser.copy()
        elif action == select_all_action: self.text_browser.selectAll()
        
    def on_toc_item_selected(self, current_item, previous_item):
        if current_item:
            anchor = current_item.data(Qt.UserRole)
            if anchor: self.text_browser.scrollToAnchor(anchor)

    def populate_toc(self):
        toc_data = [
            ("欢迎使用", "welcome", 0),
            ("一、核心工作流程", "workflow", 0),
            ("二、功能模块详解", "features", 0),
            ("口音采集会话", "feature-accent", 1),
            ("语音包录制", "feature-voicebank", 1),
            ("方言图文采集", "feature-dialect-visual", 1),
            ("语料管理与编辑", "feature-corpus-mgmt", 1),
            ("系统设置", "feature-settings", 1),
            ("三、高级技巧与最佳实践", "advanced", 0),
            ("设计高效的词表", "tip-wordlist", 1),
            ("数据备份与迁移", "tip-backup", 1),
            ("自定义主题", "tip-theme", 1),
            ("四、常见问题 (FAQ)", "faq", 0),
            ("安装与环境问题", "faq-install", 1),
            ("功能使用问题", "faq-usage", 1),
            ("五、关于与致谢", "about", 0),
        ]
        for text, anchor, level in toc_data:
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, anchor)
            if level == 1: item.setText("    " + text)
            self.toc_list_widget.addItem(item)
            
    def load_and_display_help(self):
        # ===== 修改/MODIFIED: 调整 img 标签的 CSS 样式 =====
        fixed_light_css = """
            body { font-family: "Microsoft YaHei", sans-serif; font-size: 18px; line-height: 1.8; color: #2C160D; background-color: #FFF8F6; padding: 10px 25px; }
            h1, h2, h3, h4 { color: #2C160D; }
            h1 { font-size: 32px; border-bottom: 3px solid #FCEAE4; padding-bottom: 15px; margin-bottom: 25px;}
            h2 { font-size: 26px; border-bottom: 2px solid #FCEAE4; padding-bottom: 10px; margin-top: 50px;}
            h3 { font-size: 22px; color: #8F4C33; margin-top: 35px; border-left: 4px solid #FFDBCF; padding-left: 15px;}
            h4 { font-size: 20px; margin-top: 20px; }
            p, li { margin: 15px 0; }
            ul, ol { padding-left: 25px; }
            code { background-color: #f2f2f2; border: 1px solid #e1e1e1; padding: 3px 6px; border-radius: 4px; font-family: "Consolas", "Courier New", monospace; color: #c7254e; }
            strong, b { color: #8F4C33; }
            a { color: #8F4C33; text-decoration: none; }
            a:hover { text-decoration: underline; }
            img { 
                max-width: 90%; /* 图片最大宽度为其容器的90% */
                max-height: 450px; /* 图片最大高度为450像素 */
                height: auto; /* 高度自动，保持宽高比 */
                width: auto; /* 宽度自动，以应用max-width和max-height */
                border: 1px solid #ddd; 
                border-radius: 4px; 
                padding: 5px; 
                margin-top: 10px; 
                margin-bottom: 10px; 
                display: block; 
                margin-left: auto; 
                margin-right: auto;
            }
            .note { background-color: #fdf7f5; border-left: 5px solid #FFDBCF; padding: 15px 20px; margin: 20px 0; border-radius: 0 8px 8px 0; }
            .tip { background-color: #f0fff0; border-left: 5px solid #a3d9a3; padding: 15px 20px; margin: 20px 0; border-radius: 0 8px 8px 0; }
        """
        # ======================================================
        
        html_content = ""
        if MARKDOWN_AVAILABLE:
            try:
                with open(self.help_file_path, 'r', encoding='utf-8') as f:
                    md_text = f.read()
                html_body = markdown.markdown(md_text, extensions=['extra', 'attr_list', 'md_in_html', 'fenced_code'])
                html_content = f"""
                    <html><head><style>{fixed_light_css}</style></head>
                    <body>{html_body}</body></html>
                """
            except FileNotFoundError:
                html_content = f"<p>错误：帮助文件 main_help.md 未找到于 {self.help_file_path}</p>"
            except Exception as e:
                html_content = f"<p>解析帮助文件时出错: {e}</p>"
        else:
            html_content = "<p>错误：Markdown 库未安装。无法显示帮助文档。请运行 'pip install markdown'。</p>"
        self.text_browser.setHtml(html_content)

    def update_help_content(self):
        self.load_and_display_help()