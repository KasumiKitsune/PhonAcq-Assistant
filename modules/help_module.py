# --- 模块元数据 ---
MODULE_NAME = "帮助文档"
MODULE_DESCRIPTION = "提供详细的程序使用指南和常见问题解答。"
# ---

import os
import sys
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser, QListWidget, QListWidgetItem, QSplitter, QMenu
from PyQt5.QtCore import Qt, QUrl, QSize
from PyQt5.QtGui import QIcon, QPalette, QColor # 导入 QPalette 和 QColor

def create_page(parent_window):
    """模块的入口函数，用于创建帮助页面。"""
    return HelpPage(parent_window)

class HelpPage(QWidget):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window

        main_splitter = QSplitter(Qt.Horizontal, self)
        
        self.toc_list_widget = QListWidget()
        self.toc_list_widget.setFixedWidth(250)
        self.toc_list_widget.setObjectName("HelpTOC")
        self.populate_toc()

        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True) # 允许打开网页链接
        
        # ===== 修改/MODIFIED: 固定为浅色背景和深色文字 =====
        # 创建一个浅色调色板
        light_palette = QPalette()
        light_palette.setColor(QPalette.Base, QColor("#FFF8F6")) # 米白背景
        light_palette.setColor(QPalette.Text, QColor("#2C160D")) # 深棕文字
        self.text_browser.setPalette(light_palette)
        
        self.text_browser.setHtml(self.get_help_content())

        # ===== 新增/NEW: 为 QTextBrowser 添加右键菜单支持 =====
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
        # 注意：HTML内的锚点跳转不再需要连接到 on_anchor_clicked，因为我们不再需要同步TOC的选中状态
        # self.text_browser.anchorClicked.connect(self.on_anchor_clicked) # 移除或注释掉

    # ===== 新增/NEW: QTextBrowser 的右键菜单 =====
    def show_text_browser_context_menu(self, position):
        menu = QMenu()
        copy_action = menu.addAction("复制")
        select_all_action = menu.addAction("全选")

        action = menu.exec_(self.text_browser.mapToGlobal(position))

        if action == copy_action:
            self.text_browser.copy()
        elif action == select_all_action:
            self.text_browser.selectAll()
        
    def on_toc_item_selected(self, current_item, previous_item):
        if current_item:
            anchor = current_item.data(Qt.UserRole)
            if anchor: self.text_browser.scrollToAnchor(anchor)

    # 移除 on_anchor_clicked 方法，因为不再需要
    # def on_anchor_clicked(self, url): ...

    def populate_toc(self):
        """填充左侧的目录列表。"""
        # 目录结构：(显示文本, 锚点, 缩进级别)
        toc_data = [
            ("欢迎使用", "welcome", 0),
            ("一、核心工作流程", "workflow", 0),
            ("二、功能模块详解", "features", 0),
            ("口音采集会话", "feature-accent", 1),
            ("语音包录制", "feature-voicebank", 1),
            ("方言图文采集", "feature-dialect-visual", 1), # <--- 新增
            ("语料管理与编辑", "feature-corpus-mgmt", 1), # <--- 将三个编辑器合并
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
            if level == 1:
                item.setText("    " + text)
            self.toc_list_widget.addItem(item)
            
    def get_help_content(self):
        """
        返回帮助内容的HTML字符串 (使用固定浅色样式，纯文本)。
        """
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
            .note { background-color: #fdf7f5; border-left: 5px solid #FFDBCF; padding: 15px 20px; margin: 20px 0; border-radius: 0 8px 8px 0; }
            .tip { background-color: #f0fff0; border-left: 5px solid #a3d9a3; padding: 15px 20px; margin: 20px 0; border-radius: 0 8px 8px 0; }
        """
        
        html_body = r"""
            <h1 id="welcome">欢迎使用 PhonAcq Assistant</h1>
            <p><strong>PhonAcq Assistant (音韵习得实验助手)</strong> 是一款专为语言学研究者、教师和语音爱好者设计的集成化桌面应用程序。它致力于将繁琐的语音数据采集、语料构建和数据管理流程变得简单、高效和规范化。</p>
            <p>本手册将详细介绍程序的各项功能和最佳实践，希望能帮助您快速上手并充分利用它的潜力。请使用左侧的目录来导航至您感兴趣的章节。</p>
            
            <h2 id="workflow">一、核心工作流程</h2>
            <p>本程序支持两种核心采集范式：<strong>文本音频采集</strong>和<strong>图文音频采集</strong>。您可以根据研究需求选择合适的流程。</p>
            
            <h4>通用流程</h4>
            <ol>
                <li><b>准备语料</b>: 根据您的研究范式，在 <code>语料管理</code> 或 <code>方言研究</code> 标签页下，创建对应的词表文件。</li>
                <li><b>开始采集</b>: 前往 <code>数据采集</code> 或 <code>方言研究</code> 标签页，选择对应的采集工具，加载词表并开始实验。</li>
                <li><b>管理数据</b>: 在 <code>语料管理 -> 数据管理器</code> 中，统一管理所有采集到的音频数据。</li>
            </ol>
            
            <div class="tip"><strong>语音包提示音 (可选但推荐)</strong>: 对于任何一种采集范式，如果您需要高质量、统一的真人提示音，都可以先前往 <code>数据采集 -> 语音包录制</code> 页面，为您的标准词表录制语音包。在“口音采集会话”中，程序会优先使用您录制的语音包作为提示音。</div>

            <h2 id="features">二、功能模块详解</h2>
            
            <h3 id="feature-accent">口音采集会话</h3>
            <p><strong>路径</strong>: <code>数据采集 -> 口音采集会话</code></p>
            <p>这是进行<strong>文本到语音</strong>实验的核心界面，适用于标准的朗读任务、最小音对测试、句子复述等场景。</p>
            <ul>
                <li><strong>会话前</strong>: 您需要先选择一个 <code>.py</code> 格式的<strong>标准词表</strong>，并为被试者命名。</li>
                <li><strong>会话中</strong>: 程序会逐一呈现词条，被试者根据提示音和屏幕文字进行跟读。您可以随时调整“随机/顺序”和“部分/完整”的呈现模式。</li>
                <li><strong>快捷键</strong>: 选中列表项后，按 <code>Enter</code> 或双击可重听提示音。</li>
                <li><strong>状态保持</strong>: 会话一旦开始，即使切换到其他顶级标签页，其状态（包括词表、被试者信息、录制进度）都会被保留，直到您点击“结束当前会话”。</li>
            </ul>

            <h3 id="feature-voicebank">语音包录制</h3>
            <p><strong>路径</strong>: <code>数据采集 -> 语音包录制</code></p>
            <p>此功能用于研究者自己录制一套标准的、高质量的提示音，以替代在线TTS。</p>
            <ul>
                <li><strong>操作逻辑</strong>: 加载一个标准词表，然后逐一选中词条，通过<strong>按住并松开</strong>“录音”按钮或键盘的 <code>Enter</code> 键来完成录制。</li>
                <li><strong>文件关联</strong>: 录制好的音频会自动与词表关联。当“口音采集会话”使用这个词表时，会优先播放您录制的音频。</li>
                <li><strong>状态保持</strong>: 与口音采集类似，录制会话的状态也会被保留，直到您手动结束。</li>
            </ul>

            <h3 id="feature-dialect-visual">方言图文采集</h3>
            <p><strong>路径</strong>: <code>方言研究 -> 图文采集</code></p>
            <p>这是一个强大的新功能，专为需要**视觉刺激**的方言调查、田野调查或儿童语言习得研究设计。</p>
            <ul>
                <li><strong>核心逻辑</strong>: 向被试者展示一张图片，并根据文字提示，请他们用方言描述图片内容或说出图中物体的名称，然后录下他们的语音。</li>
                <li><strong>图片缩放与拖动</strong>: 您可以使用鼠标滚轮（或触摸板双指手势）对图片进行<strong>缩放</strong>，并用鼠标左键<strong>拖动</strong>图片以查看细节。</li>
                <li><strong>备注显隐</strong>: 每个项目都可以附带研究者可见的“备注”（例如，提示需要关注的语言现象）。这些备注可以通过右侧的开关控制显示或隐藏，不会被被试者看到。</li>
                <li><strong>词表与资源</strong>: 此功能使用专属的“图文词表”。所有图片资源都应放在与图文词表 <code>.py</code> 文件同名的文件夹下。</li>
            </ul>

            <h3 id="feature-corpus-mgmt">语料管理与编辑</h3>
            <p>所有用于创建和编辑语料的工具都集中在这里。</p>
            <h4>Excel 转换器</h4>
            <p><strong>路径</strong>: <code>语料管理 -> Excel 转换器</code></p>
            <p><strong>强烈推荐</strong>使用此功能来创建您的标准词表。它提供多种预设模板，支持多语言，并且有详细的转换报告。</p>
            
            <h4>词表编辑器</h4>
            <p><strong>路径</strong>: <code>语料管理 -> 词表编辑器</code></p>
            <p>用于直接编辑 <code>.py</code> 格式的<strong>标准词表</strong>。它支持带国旗图标的语言选择，并有撤销/重做、删除、保存等全套快捷键支持。</p>
            
            <h4>图文词表编辑器</h4>
            <p><strong>路径</strong>: <code>方言研究 -> 图文词表编辑</code></p>
            <p>这是为“方言图文采集”功能配套的编辑器。您可以在这里创建和管理图文词表的项目列表。</p>
            <ul>
                <li><strong>智能检测</strong>: 核心功能！在您填入“项目ID”后，可以点击“自动检测图片”按钮。如果勾选了“智能检测”，它会忽略大小写和符号差异，模糊匹配并自动填充最相似的图片文件名，极大提高效率。</li>
                <li><strong>文件选择</strong>: 双击“图片文件路径”单元格，可以直接弹出文件管理器让您选择图片。</li>
            </ul>
            
            <h3 id="feature-settings">系统设置</h3>
            <p><strong>路径</strong>: <code>系统设置</code></p>
            <p>在这里，您可以对程序的各方面进行个性化配置，包括UI主题、默认路径、音频参数、TTS语言等。所有设置都会自动保存。</p>
            
            <h2 id="advanced">三、高级技巧与最佳实践</h2>
            <h3 id="tip-wordlist">设计高效的词表</h3>
            <p>无论是标准词表还是图文词表，良好的设计都至关重要。</p>
            <ul>
                <li><strong>ID 命名</strong>: 为您的项目ID（或标准词表中的单词）使用清晰、规范的命名（例如，使用下划线代替空格），因为它们会直接用作音频文件名。</li>
                <li><strong>文件组织</strong>: 对于图文词表，请务必将所有图片资源放在与 <code>.py</code> 文件同名的子文件夹中，这是程序自动查找的基础。</li>
            </ul>

            <h3 id="tip-backup">数据备份与迁移</h3>
            <p>您的所有工作都是以普通文件的形式存储的，备份和迁移非常简单。您只需要定期备份以下文件夹即可：</p>
            <ul>
                <li><code>word_lists/</code> (标准词表)</li>
                <li><code>dialect_visual_wordlists/</code> (图文词表及图片)</li>
                <li><code>audio_record/</code> (所有语音包和方言图文录音)</li>
                <li><code>Results/</code> (所有口音采集会话数据)</li>
                <li><code>config/settings.json</code> (您的个人设置)</li>
            </ul>

            <h3 id="tip-theme">自定义主题</h3>
            <p>您可以参考 <code>themes</code> 文件夹下的 <code>.qss</code> 文件，创建自己的样式表，并放入该文件夹，重启程序后即可在设置中选择。</p>
            
            <h2 id="faq">四、常见问题 (FAQ)</h2>
            <h3 id="faq-install">安装与环境问题</h3>
            <p><strong>问：为什么提示“依赖库缺失”？</strong><br>
            答：请根据提示运行 <code>pip install ...</code> 命令来安装所有必需的Python库。特别是新功能可能需要 <code>thefuzz</code> 和 <code>python-Levenshtein</code>。</p>

            <h3 id="faq-usage">功能使用问题</h3>
            <p><strong>问：为什么图文采集时提示“找不到图片”？</strong><br>
            答：请检查：1. 您的图片是否放在了与图文词表 <code>.py</code> 文件同名的子文件夹中？ 2. 图文词表中的 `image_path` 字段是否正确填写了图片的文件名（含后缀）？</p>
            <p><strong>问：为什么“智能检测”没有反应？</strong><br>
            答：请确保您已经通过 <code>pip install thefuzz python-Levenshtein</code> 安装了模糊匹配库。</p>
            
            <h2 id="about">五、关于与致谢</h2>
            <p><strong>PhonAcq Assistant</strong> 的开发旨在为语言学研究社区提供一个现代化、开源、易用的工具，以促进学术研究的效率和数据的规范性。</p>
            <p>感谢所有为此项目提供建议和反馈的用户！</p>
        """
        
        return rf"""
            <html>
            <head>
                <style>{fixed_light_css}</style>
            </head>
            <body>
                {html_body}
            </body>
            </html>
        """
