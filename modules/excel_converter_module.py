# --- 模块元数据 ---
MODULE_NAME = "Excel转换器"
MODULE_DESCRIPTION = "支持标准词表（Standard Wordlist）与图文词表（Visual Wordlist）之间的双向转换，并能处理CSV格式。内置多种模板，方便用户创建新词表，是连接程序内部数据与外部表格工具的桥梁。"
import os
import sys
import pandas as pd
from datetime import datetime
import json

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                             QFileDialog, QMessageBox, QComboBox, QGroupBox,
                             QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem,
                             QHeaderView, QApplication, QFormLayout, QDialogButtonBox, QDialog, QCheckBox)
from PyQt5.QtCore import Qt, QMimeData, QSize
from PyQt5.QtGui import QIcon

def get_base_path():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def create_page(parent_window, WORD_LIST_DIR, MODULES_REF, icon_manager):
    return ConverterPage(parent_window, WORD_LIST_DIR, icon_manager)

# --- 模板定义 (更新，包含新的词表和更详细的描述) ---
templates = {
    'standard_simple': { # 原有的 simple 模板
        'filename': "1_标准词表_单语言通用模板.xlsx",
        'description': "<b>类型：</b>标准词表<br><b>用途：</b>最基础的词表格式，适用于单语言的通用词汇或短语采集。<br><b>字段：</b>'组别', '单词', 'IPA', 'Language'。",
        'data': { '组别': [1, 1, 2, 2], '单词': ['hello', 'world', 'apple', 'banana'], 'IPA': ['həˈloʊ', 'wɜːrld', 'ˈæpəl', 'bəˈnænə'], 'Language': ['en-us', 'en-us', 'en-us', 'en-us'] }
    },
    'mandarin_tone_pairs': { # 新增：普通话声调测试
        'filename': "2_标准词表_普通话声调对测试.xlsx",
        'description': "<b>类型：</b>标准词表<br><b>用途：</b>专为普通话声调辨识与发音设计。包含声调组合的“最小音对”，非常适合语音学实验或教学。<br><b>示例：</b>如 '飞机' (1-1) 对比 '飞贼' (1-2)。",
        'data': {
            '组别': [1, 1, 1, 2, 2, 2],
            '单词': ['飞机', '飞贼', '飞艇', '银行', '语言', '雨伞'],
            'IPA': ['fēi jī (1-1)', 'fēi zéi (1-2)', 'fēi tǐng (1-3)', 'yín háng (2-2)', 'yǔ yán (3-2)', 'yǔ sǎn (3-3)'],
            'Language': ['zh-cn', 'zh-cn', 'zh-cn', 'zh-cn', 'zh-cn', 'zh-cn']
        }
    },
    'english_vowel_space': { # 新增：英语元音空间提取
        'filename': "3_标准词表_英语元音空间提取.xlsx",
        'description': "<b>类型：</b>标准词表<br><b>用途：</b>用于提取和绘制英语元音F1/F2共振峰的经典hVd词表（如'heed', 'hid', 'hayed'）。每个词都嵌入句法框架，减少协同发音影响。<br><b>示例：</b>'Say heed again.'",
        'data': {
            '组别': [1, 1, 1, 2, 2, 2],
            '单词': ["Say heed again.", "Say hid again.", "Say head again.", "Say hawed again.", "Say hoed again.", "Say who'd again."],
            'IPA': ["/hid/", "/hɪd/", "/hɛd/", "/hɔd/", "/hoʊd/", "/hud/"],
            'Language': ["en-us", "en-us", "en-us", "en-us", "en-us", "en-us"]
        }
    },
    'english_accent_diagnostic': { # 新增：英语口音诊断
        'filename': "4_标准词表_英语口音诊断.xlsx",
        'description': "<b>类型：</b>标准词表<br><b>用途：</b>通过精心设计的句子，系统性覆盖区分不同英语口音（如美式、英式）的关键音变现象（如/r/音、元音合并、T-glottalization等）。<br><b>示例：</b>'The farmer's car is far from the barn.'",
        'data': {
            '组别': [1, 1, 2, 2],
            '单词': ["The farmer's car is far from the barn.", "I caught the cot in the corner.", "Mary, merry, and marry sound different.", "How now, brown cow?"],
            'IPA': ["R-lessness test", "Cot-caught merger test", "Mary-marry-merry merger test", "Diphthong analysis"],
            'Language': ["en-us", "en-us", "en-us", "en-us"]
        }
    },
    'multilingual_pangrams': { # 新增：多语种全字母句
        'filename': "5_标准词表_多语种全字母句.xlsx",
        'description': "<b>类型：</b>标准词表<br><b>用途：</b>包含多种语言的“全字母句”（Pangram），每句包含该语言的所有字母。非常适合TTS引擎测试、字体显示测试或跨语言音素频率分析。<br><b>示例：</b>英语, 法语, 德语, 俄语, 日语, 韩语。",
        'data': {
            '组别': [1, 1, 1, 2, 2, 2],
            '单词': ["The quick brown fox jumps over the lazy dog.", "Portez ce vieux whisky au juge blond qui fume.", "Съешь ещё этих мягких французских булок, да выпей же чаю.", "いろはにほへとちりぬるを", "키스의 고유조건은 입술끼리 만나야 하고 특별한 기술은 필요치 않다.", "도서관은 조용한 공부 장소입니다."],
            'IPA': ["English Pangram", "French Pangram", "Russian Pangram", "Japanese Iroha", "Korean Sentence", "Korean Sentence"],
            'Language': ["en-us", "fr-fr", "ru", "ja", "ko", "ko"]
        }
    },
    'visual_image_description': { # 新增：图文采集示例
        'filename': "6_图文词表_农家生活图文采集.xlsx",
        'description': "<b>类型：</b>图文词表<br><b>用途：</b>为“方言图文采集”功能设计，主题为农家生活场景。引导被试者描述图片内容，以收集相关的名词、动词、量词和方言特有表达。<br><b>字段：</b>'id', 'image_path', 'prompt_text', 'notes'。",
        'data': {
            'id': ['chicken_group', 'rice_field_harvest', 'vegetable_garden', 'old_farmhouse', 'drying_grains'],
            'image_path': ['sample_farm_life/chicken_group', 'sample_farm_life/rice_field_harvest', 'sample_farm_life/vegetable_garden', 'sample_farm_life/old_farmhouse', 'sample_farm_life/drying_grains'],
            'prompt_text': ['请用您的方言说说图片里的这些动物是什么，它们在做什么？', '描述一下这个场景。现在是农忙的什么季节？人们在做什么？', '图中的这些蔬菜，用你们那儿的话都叫什么名字？', '请描述一下这座老房子。它有什么特点？这种房子现在还常见吗？', '粮食丰收后，你们通常怎么晾晒和储存谷物？有什么特别的工具或说法吗？'],
            'notes': ['目标词汇：鸡、公鸡、母鸡、小鸡、喂食、啄米等。', '目标词汇：稻田、收割、稻谷、镰刀等。', '目标：多种常见蔬菜的方言名称。', '目标：房屋结构、材料的方言词汇。', '考察与粮食处理相关的动词和名词。']
        }
    }
}


class ConverterPage(QWidget):
    def __init__(self, parent_window, WORD_LIST_DIR, icon_manager):
        super().__init__()
        self.parent_window = parent_window
        self.config = self.parent_window.config
        self.WORD_LIST_DIR = WORD_LIST_DIR
        self.BASE_PATH = get_base_path()
        self.icon_manager = icon_manager
        self.source_path = None
        self.preview_df = None
        self.detected_format = None
        
        self.setAcceptDrops(True)
        self._init_ui()
        self.update_icons()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_splitter = QSplitter(Qt.Vertical)
        
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        
        # --- Left Panel ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setFixedWidth(300)
        
        self.select_file_btn = QPushButton("  选择文件 或 拖拽至此\n (.json/.csv/.xlsx)") # 移除 .py
        self.select_file_btn.setToolTip("选择一个词表文件 (.json, .xlsx, .xls, .csv) 进行转换。\n您也可以直接将文件拖拽到此窗口。") # 移除 .py
        self.select_file_btn.setIconSize(QSize(32, 32))
        
        templates_group = QGroupBox("生成/预览Excel模板")
        templates_layout = QVBoxLayout(templates_group)
        self.template_combo = QComboBox()
        self.template_combo.setToolTip("选择一个预设的Excel模板格式进行预览或生成。\n下方的描述会解释该模板的用途和结构。")
        self.generate_template_btn = QPushButton("生成选中模板文件")
        self.generate_template_btn.setToolTip("在程序的'word_lists'文件夹中生成选定格式的空白Excel模板文件。")
        templates_layout.addWidget(self.template_combo)
        templates_layout.addWidget(self.generate_template_btn)
        
        self.template_description_label = QLabel("请从上方选择一个模板以查看其详细说明。")
        self.template_description_label.setWordWrap(True)
        self.template_description_label.setObjectName("DescriptionLabel")
        templates_layout.addWidget(self.template_description_label, 1)
        
        left_layout.addWidget(self.select_file_btn)
        left_layout.addWidget(templates_group, 1)
        left_layout.addStretch()
        
        # --- Right Panel ---
        right_panel = QGroupBox("预览与转换")
        right_layout = QVBoxLayout(right_panel)
        
        self.preview_label = QLabel("请先从左侧选择一个文件或模板")
        self.preview_label.setToolTip("在此区域预览转换前的文件或模板内容。")
        
        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setWordWrap(True)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.preview_table.setToolTip("预览文件的表格内容。\n转换操作将基于此表格内容进行。")
        
        self.confirm_btn = QPushButton("转换为其他格式...")
        self.confirm_btn.setObjectName("AccentButton")
        self.confirm_btn.setToolTip("将上方预览的表格内容转换为其他格式。")
        self.confirm_btn.setEnabled(False)
        
        right_layout.addWidget(self.preview_label)
        right_layout.addWidget(self.preview_table, 1)
        right_layout.addWidget(self.confirm_btn)
        
        top_layout.addWidget(left_panel)
        top_layout.addWidget(right_panel, 1)
        
        # --- Bottom Panel (Log) ---
        log_group = QGroupBox("操作日志")
        log_layout = QVBoxLayout(log_group)
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setPlaceholderText("此处将显示操作日志和结果...")
        self.log_display.setToolTip("显示文件加载、转换过程和结果的详细日志信息。")
        log_layout.addWidget(self.log_display)
        
        main_splitter.addWidget(top_widget)
        main_splitter.addWidget(log_group)
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 1)
        main_layout.addWidget(main_splitter)
        
        # --- Connect Signals ---
        self.select_file_btn.clicked.connect(self.select_file_dialog)
        self.generate_template_btn.clicked.connect(self.generate_template)
        self.template_combo.currentIndexChanged.connect(self.on_template_selected)
        self.confirm_btn.clicked.connect(self.run_conversion)
        
        self.populate_template_combo()

    def update_icons(self):
        self.select_file_btn.setIcon(self.icon_manager.get_icon("open_file"))
        self.generate_template_btn.setIcon(self.icon_manager.get_icon("auto_detect"))
        self.confirm_btn.setIcon(self.icon_manager.get_icon("convert"))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                filepath = urls[0].toLocalFile()
                if filepath.lower().endswith(('.json', '.xlsx', '.xls', '.csv')): # 移除 .py
                    event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            filepath = event.mimeData().urls()[0].toLocalFile()
            self.select_and_preview_file(filepath)

    def log(self, message):
        self.log_display.appendPlainText(f"[{datetime.now():%H:%M:%S}] {message}")

    def populate_template_combo(self):
        self.template_combo.clear()
        self.template_combo.addItem("请选择一个模板...", None) # Add a placeholder
        # 按照文件名中序号排序，以确保有序显示
        sorted_templates = sorted(templates.items(), key=lambda item: item[1]['filename'])
        for key, info in sorted_templates:
            display_name = os.path.splitext(info['filename'])[0].split('_', 1)[1] # 提取 '1_前缀_名称.xlsx' 中的 '前缀_名称'
            # 如果是图文词表，显示不同的名称以示区分
            if 'visual' in key:
                display_name = f"{display_name} (图文词表)"
            else:
                display_name = f"{display_name} (标准词表)"
            self.template_combo.addItem(display_name, key) # itemData 存储原始key

    def on_template_selected(self, index):
        template_key = self.template_combo.currentData()
        if not template_key or index <= 0:
            self.template_description_label.setText("请从上方选择一个模板以查看其详细说明。")
            self.preview_table.clear()
            self.preview_table.setRowCount(0)
            self.preview_table.setColumnCount(0)
            self.preview_label.setText("请先从左侧选择一个文件或模板")
            self.confirm_btn.setEnabled(False)
            return

        template_info = templates.get(template_key, {})
        # [核心修改] 使用 QTextBrowser 来显示富文本描述
        self.template_description_label.setText(template_info.get('description', '无可用描述。'))
        self.template_description_label.setTextFormat(Qt.RichText) # 确保 QLabel 支持富文本

        template_data = template_info.get('data')
        if not template_data:
            self.log(f"警告: 模板 '{template_key}' 没有可预览的数据。")
            return
            
        try:
            self.preview_df = pd.DataFrame(template_data)
            self.detected_format = _detect_excel_format(self.preview_df.columns)
        except Exception as e:
            self.log(f"错误: 从模板创建预览时失败 - {e}")
            QMessageBox.critical(self, "模板预览失败", f"无法为模板 '{template_key}' 创建预览:\n{e}")
            return

        self.populate_preview_table()
        
        self.source_path = None 
        template_filename = template_info.get('filename', '未知模板')
        self.preview_label.setText(f"模板预览: {template_filename} (格式: {self.detected_format or '未知'})")
        self.confirm_btn.setEnabled(True)
        self.log(f"已加载模板预览: {template_filename}")

    def generate_template(self):
        template_type = self.template_combo.currentData()
        if not template_type:
            QMessageBox.information(self, "提示", "请先从下拉列表中选择一个要生成的模板。")
            return
        
        success, msg = generate_template(self.WORD_LIST_DIR, template_type=template_type)
        self.log(msg)
        
        if not success:
            QMessageBox.warning(self, "生成失败", msg)
        else:
            QMessageBox.information(self, "生成成功", msg)
            
            # --- [核心修改] ---
            # 检查是否需要自动打开文件
            module_states = self.config.get("module_states", {}).get("excel_converter", {})
            if module_states.get("auto_open_after_generate", True):
                template_info = templates[template_type]
                generated_path = os.path.join(self.WORD_LIST_DIR, template_info['filename'])
                if os.path.exists(generated_path):
                    self._open_path_in_explorer(generated_path)
            # --- [修改结束] ---

    def select_file_dialog(self):
        filters = "支持的词表文件 (*.json *.xlsx *.xls *.csv);;JSON 文件 (*.json);;Excel 文件 (*.xlsx *.xls);;CSV 文件 (*.csv)" # 移除 .py
        filepath, _ = QFileDialog.getOpenFileName(self, "选择要转换的文件", self.WORD_LIST_DIR, filters)
        self.select_and_preview_file(filepath)

    def select_and_preview_file(self, filepath):
        if not filepath:
            self.log("操作取消。")
            return
        self.source_path = filepath
        self.log(f"已选择文件: {os.path.basename(filepath)}")
        self.preview_label.setText(f"正在加载预览: {os.path.basename(filepath)}...")
        QApplication.processEvents()
        try:
            self.load_data_into_preview(filepath)
            self.populate_preview_table()
            self.confirm_btn.setEnabled(True)
            self.preview_label.setText(f"预览: {os.path.basename(filepath)} (格式: {self.detected_format or '未知'})")
            # 当加载文件成功后，重置模板选择，避免混淆
            self.template_combo.setCurrentIndex(0)
        except Exception as e:
            self.log(f"错误: 加载文件失败 - {e}")
            self.preview_label.setText(f"加载失败: {os.path.basename(filepath)}")
            self.confirm_btn.setEnabled(False)
            QMessageBox.critical(self, "加载失败", f"无法加载或解析文件:\n{e}")

    def load_data_into_preview(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext in ['.xlsx', '.xls']:
            df = pd.read_excel(path, sheet_name=0, dtype=str).fillna('')
            self.detected_format = _detect_excel_format(df.columns)
            if self.detected_format is None: raise ValueError("无法识别的Excel格式。请参考模板文件。")
            self.preview_df = df
        elif ext == '.csv':
            df = pd.read_csv(path, dtype=str).fillna('')
            self.detected_format = _detect_excel_format(df.columns)
            if self.detected_format is None: raise ValueError("无法识别的CSV格式。请参考模板文件。")
            self.preview_df = df
        elif ext == '.json':
            self.preview_df, self.detected_format = _json_to_dataframe(path)
        # 移除了对 .py 文件的支持
        else:
            raise ValueError(f"不支持的文件类型: {ext}")

    def populate_preview_table(self):
        if self.preview_df is None: return
        self.preview_table.clear()
        df = self.preview_df
        self.preview_table.setRowCount(df.shape[0])
        self.preview_table.setColumnCount(df.shape[1])
        self.preview_table.setHorizontalHeaderLabels(df.columns)
        for i, row in df.iterrows():
            for j, val in enumerate(row):
                self.preview_table.setItem(i, j, QTableWidgetItem(str(val)))
        self.preview_table.resizeRowsToContents()

    def run_conversion(self):
        if self.preview_df is None:
            self.log("错误: 没有可转换的数据。")
            QMessageBox.warning(self, "操作失败", "没有可用于转换的数据。请先选择一个文件或模板。")
            return
        
        # 1. 确定默认输出文件名
        if self.source_path:
            source_basename = os.path.splitext(os.path.basename(self.source_path))[0]
        else: # 如果是基于模板的
            template_key = self.template_combo.currentData()
            template_info = templates.get(template_key, {})
            template_filename = template_info.get('filename', 'template')
            source_basename = os.path.splitext(template_filename)[0]

        default_filename = f"{source_basename}_converted"
        
        # 2. 根据配置智能地设置文件保存对话框的默认过滤器
        module_states = self.config.get("module_states", {}).get("excel_converter", {})
        default_filter_index = module_states.get("default_output_format_index", 0)

        all_filters = "JSON 词表 (*.json);;Excel 文件 (*.xlsx);;CSV 文件 (*.csv)"
        filters_list = all_filters.split(';;')
        
        default_filter = ""
        # "智能选择" 逻辑
        if default_filter_index == 0:
            if self.detected_format and "json" in self.detected_format.lower():
                # 如果输入是JSON，默认输出Excel
                default_filter = filters_list[1]
            else: # 如果输入是Excel/CSV/模板，默认输出JSON
                default_filter = filters_list[0]
        else:
            # 用户指定了默认格式 (索引需要-1，因为我们的选项是从1开始的)
            if 0 < default_filter_index <= len(filters_list):
                 default_filter = filters_list[default_filter_index - 1]
        
        # 重新组合过滤器字符串，把计算出的默认格式放在最前面，以便对话框默认选中它
        final_filters = default_filter + ";;" + ";;".join(f for f in filters_list if f != default_filter)

        output_path, selected_filter = QFileDialog.getSaveFileName(self, "保存为", default_filename, final_filters)
        
        if not output_path:
            self.log("保存操作已取消。")
            return
            
        self.log(f"开始转换 -> {output_path}")
        QApplication.processEvents()
        success, msg = False, ""
        try:
            # 3. 根据用户选择的过滤器执行相应的转换操作
            if "(*.json)" in selected_filter:
                # 确保保存时加上 .json 后缀
                if not output_path.lower().endswith('.json'):
                    output_path += '.json'
                json_str = _dataframe_to_json(self.preview_df, self.detected_format)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(json_str)
            elif "(*.xlsx)" in selected_filter:
                # 确保保存时加上 .xlsx 后缀
                if not output_path.lower().endswith('.xlsx'):
                    output_path += '.xlsx'
                self.preview_df.to_excel(output_path, index=False)
            elif "(*.csv)" in selected_filter:
                # 确保保存时加上 .csv 后缀
                if not output_path.lower().endswith('.csv'):
                    output_path += '.csv'
                # 根据配置选择CSV编码
                csv_encoding_index = module_states.get("csv_encoding_index", 0)
                encoding = 'utf-8-sig' if csv_encoding_index == 0 else 'utf-8'
                self.preview_df.to_csv(output_path, index=False, encoding=encoding)
            else:
                raise ValueError("未知的保存格式。")
                
            success, msg = True, f"成功转换！文件已保存至: {output_path}"
        except Exception as e:
            success, msg = False, f"转换失败: {e}"
            
        self.log(msg)
        if not success:
            QMessageBox.critical(self, "错误", msg)
        else:
            QMessageBox.information(self, "成功", msg)
            
            # 4. 根据配置决定是否在转换成功后自动打开文件
            if module_states.get("auto_open_after_convert", True):
                if os.path.exists(output_path):
                    self._open_path_in_explorer(output_path)
    def _open_path_in_explorer(self, path):
        """
        [新增] 跨平台地在文件浏览器中打开指定路径（文件或文件夹）。
        """
        try:
            if sys.platform == 'win32':
                os.startfile(os.path.realpath(path))
            elif sys.platform == 'darwin':
                subprocess.check_call(['open', path])
            else: # Linux
                subprocess.check_call(['xdg-open', path])
        except Exception as e:
            QMessageBox.critical(self, "操作失败", f"无法打开路径: {path}\n错误: {e}")

    def open_settings_dialog(self):
        """
        [新增] 打开此模块的设置对话框。
        """
        dialog = SettingsDialog(self)
        # 这个模块的设置不影响核心渲染，所以刷新不是必须的，
        # 但为了保持一致性，我们依然可以在OK后刷新。
        if dialog.exec_() == QDialog.Accepted:
            # 刷新可以确保主配置 self.config 对象是最新的
            self.parent_window.request_tab_refresh(self)
# --- 内部辅助函数 ---
def _detect_excel_format(columns):
    cols = set(columns);
    if 'id' in cols and 'image_path' in cols: return 'visual';
    if '组别' in cols and '词1' in cols: return 'multi';
    if '组别' in cols and '单词' in cols: return 'simple';
    return None

def _json_to_dataframe(filepath):
    with open(filepath, 'r', encoding='utf-8') as f: data = json.load(f)
    meta = data.get('meta', {}); file_format = meta.get('format')
    if file_format == 'visual_wordlist':
        return pd.DataFrame(data.get('items', [])), 'visual'
    elif file_format == 'standard_wordlist':
        flat_data = []
        for group in data.get('groups', []):
            group_id = group.get('id')
            for item in group.get('items', []):
                # 确保所有必需的列都存在
                text = item.get('text', '')
                note = item.get('note', '')
                lang = item.get('lang', '')
                flat_data.append({'组别': group_id, '单词': text, 'IPA': note, 'Language': lang})
        return pd.DataFrame(flat_data), 'standard'
    else:
        raise ValueError("无法识别的JSON词表格式。")

def _dataframe_to_json(df, detected_format):
    if detected_format == 'visual':
        items_list = df.to_dict('records')
        json_structure = {"meta": {"format": "visual_wordlist", "version": "1.0"}, "items": items_list}
    elif detected_format in ['simple', 'standard', 'multi']:
        groups_map = {}
        for _, row in df.iterrows():
            try:
                group_id = int(row['组别'])
                if group_id not in groups_map: groups_map[group_id] = []
                # 确保所有必需的字段都从 DataFrame 中正确获取
                text = str(row.get('单词', ''))
                note = str(row.get('IPA', ''))
                lang = str(row.get('Language', ''))
                groups_map[group_id].append({'text': text, 'note': note, 'lang': lang})
            except (ValueError, KeyError) as e: 
                print(f"警告: 转换过程中跳过无效行 (组别: {row.get('组别')}, 错误: {e})", file=sys.stderr)
                continue # Skip rows with invalid group id
        
        groups_list = [{"id": gid, "items": items} for gid, items in sorted(groups_map.items())]
        json_structure = {"meta": {"format": "standard_wordlist", "version": "1.0"}, "groups": groups_list}
    else:
        raise ValueError(f"不支持从格式 '{detected_format}' 转换为JSON。")
    return json.dumps(json_structure, indent=4, ensure_ascii=False)

def _dataframe_to_py(df, detected_format): # 这个函数已经没用了，但保留在这里以防万一
    header = f"# Auto-generated by PhonAcq Converter\n# Conversion date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    if detected_format == 'visual':
        items_list_str = "ITEMS = [\n"
        for _, row in df.iterrows():
            items_list_str += "    {\n"
            for col in df.columns: items_list_str += f"        '{col}': '''{row[col]}''',\n"
            items_list_str += "    },\n"
        items_list_str += "]\n"
        return header + items_list_str
    elif detected_format in ['simple', 'standard', 'multi']:
        groups_map = {}
        for _, row in df.iterrows():
            try:
                group_id = int(row['组别'])
                if group_id not in groups_map: groups_map[group_id] = {}
                word = str(row['单词']).replace("'", "\\'"); ipa = str(row.get('IPA', '')).replace("'", "\\'"); lang = str(row.get('Language', ''))
                groups_map[group_id][word] = (ipa, lang)
            except (ValueError, KeyError): continue
        
        py_code = "WORD_GROUPS = [\n"
        for _, group in sorted(groups_map.items()):
            py_code += "    {\n"
            for word, (ipa, lang) in group.items(): py_code += f"        '{word}': ('{ipa}', '{lang}'),\n"
            py_code += "    },\n"
        py_code += "]\n"
        return header + py_code
    else:
        raise ValueError(f"不支持从格式 '{detected_format}' 转换为Python脚本。")
    
def generate_template(output_dir, template_type='simple'):
    if template_type not in templates: return False, f"未知的模板类型: {template_type}"
    template_info = templates[template_type]; template_path = os.path.join(output_dir, template_info['filename'])
    try:
        df = pd.DataFrame(template_info['data']); df.to_excel(template_path, index=False)
        return True, f"成功！模板 '{template_info['filename']}' 已生成至: {output_dir}"
    except Exception as e: return False, f"生成模板文件时出错: {e}"
# --- [核心新增] ---
# 为 Excel 转换器模块定制的设置对话框
class SettingsDialog(QDialog):
    """
    一个专门用于配置“Excel转换器”模块的对话框。
    """
    def __init__(self, parent_page):
        super().__init__(parent_page)
        
        self.parent_page = parent_page
        self.setWindowTitle("Excel转换器设置")
        self.setWindowIcon(self.parent_page.parent_window.windowIcon())
        self.setStyleSheet(self.parent_page.parent_window.styleSheet())
        self.setMinimumWidth(500)
        
        # 主布局
        layout = QVBoxLayout(self)
        
        # --- 组1: 转换设置 ---
        conversion_group = QGroupBox("转换设置")
        conversion_form = QFormLayout(conversion_group)
        
        self.default_output_combo = QComboBox()
        self.default_output_combo.addItems([
            "智能选择 (Excel -> JSON, JSON -> Excel)",
            "JSON (标准或图文)",
            "Excel (.xlsx)",
            "CSV"
        ])
        self.default_output_combo.setToolTip("预设点击“转换为...”按钮时，文件保存对话框默认选中的格式。")

        self.csv_encoding_combo = QComboBox()
        self.csv_encoding_combo.addItems([
            "UTF-8 with BOM (推荐，兼容Excel)",
            "UTF-8 (标准，无BOM)"
        ])
        self.csv_encoding_combo.setToolTip("选择导出为.csv文件时的编码格式，以解决中文乱码问题。")
        
        self.auto_open_after_convert_check = QCheckBox("转换成功后自动打开文件")
        
        conversion_form.addRow("默认输出格式:", self.default_output_combo)
        conversion_form.addRow("CSV 文件编码:", self.csv_encoding_combo)
        conversion_form.addRow(self.auto_open_after_convert_check)
        layout.addWidget(conversion_group)

        # --- 组2: 模板设置 ---
        template_group = QGroupBox("模板设置")
        template_form = QFormLayout(template_group)

        self.auto_open_after_generate_check = QCheckBox("生成模板后自动打开")

        template_form.addRow(self.auto_open_after_generate_check)
        layout.addWidget(template_group)
        
        # OK 和 Cancel 按钮
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addStretch()
        layout.addWidget(self.button_box)
        
        # 连接信号
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        self.load_settings()

    def load_settings(self):
        """从主配置加载所有设置并更新UI。"""
        module_states = self.parent_page.config.get("module_states", {}).get("excel_converter", {})
        
        self.default_output_combo.setCurrentIndex(module_states.get("default_output_format_index", 0))
        self.csv_encoding_combo.setCurrentIndex(module_states.get("csv_encoding_index", 0))
        self.auto_open_after_convert_check.setChecked(module_states.get("auto_open_after_convert", True))
        self.auto_open_after_generate_check.setChecked(module_states.get("auto_open_after_generate", True))

    def save_settings(self):
        """将UI上的所有设置保存回主配置。"""
        main_window = self.parent_page.parent_window
        
        settings_to_save = {
            "default_output_format_index": self.default_output_combo.currentIndex(),
            "csv_encoding_index": self.csv_encoding_combo.currentIndex(),
            "auto_open_after_convert": self.auto_open_after_convert_check.isChecked(),
            "auto_open_after_generate": self.auto_open_after_generate_check.isChecked(),
        }
        
        current_settings = main_window.config.get("module_states", {}).get("excel_converter", {})
        current_settings.update(settings_to_save)
        main_window.update_and_save_module_state('excel_converter', settings_to_save)

    def accept(self):
        """重写 accept 方法，在关闭对话框前先保存设置。"""
        self.save_settings()
        super().accept()