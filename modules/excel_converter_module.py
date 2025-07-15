import os
import sys
import pandas as pd
from datetime import datetime
import json

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                             QFileDialog, QMessageBox, QComboBox, QGroupBox,
                             QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem,
                             QHeaderView, QApplication, QFormLayout)
from PyQt5.QtCore import Qt, QMimeData, QSize
from PyQt5.QtGui import QIcon

def get_base_path():
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def create_page(parent_window, WORD_LIST_DIR, MODULES_REF, icon_manager):
    return ConverterPage(parent_window, WORD_LIST_DIR, icon_manager)

# --- 模板定义 (保持不变) ---
templates = {
    'simple': {
        'filename': "1_标准词表_单语言模板.xlsx",
        'description': "最基础的格式，用于标准“口音采集”。\n\n- '组别'列用于分组。\n- '单词'和'IPA'列一一对应。",
        'data': { '组别': [1, 1, 2, 2], '单词': ['hello', 'world', 'apple', 'banana'], 'IPA': ['həˈloʊ', 'wɜːrld', 'ˈæpəl', 'bəˈnænə'] }
    },
    'contrast': {
        'filename': "2_标准词表_音素对比模板.xlsx",
        'description': "专为语音学中的“最小音对”实验设计。\n\n- 使用'单语言'格式。\n- 将发音相似但意义不同的词（如 ship/sheep）放在同一组别下。",
        'data': {
            '组别': [1, 1, 2, 2, 3, 3],
            '单词': ['ship', 'sheep', 'sit', 'seat', 'cat', 'cart'],
            'IPA': ['ʃɪp', 'ʃiːp', 'sɪt', 'siːt', 'kæt', 'kɑːrt']
        }
    },
    'dialect': {
        'filename': "3_标准词表_方言适应性模板.xlsx",
        'description': "针对特定方言背景学习者的发音难点设计。\n\n- 示例为吴语区常见的难点音（如齿间音/θ/, /ð/）。",
        'data': {
            '组别': [1, 1, 1, 2, 2, 3, 3],
            '单词': ['think', 'this', 'three', 'very', 'voice', 'lazy', 'zeal'],
            'IPA': ['θɪŋk', 'ðɪs', 'θriː', 'ˈvɛri', 'vɔɪs', 'ˈleɪzi', 'ziːl']
        }
    },
    'phrase': {
        'filename': "4_标准词表_短语与连读模板.xlsx",
        'description': "用于测试语流中的语音现象，而非单个词汇。\n\n- 包含常见的连读、省音、同化等例子。",
        'data': {
            '组别': [1, 1, 2, 2],
            '单词': ['read it', 'an apple', "what's up", 'give me'],
            'IPA': ['/ˈriːd_ɪt/', '/ən_ˈæpəl/', '/wʌtsˈʌp/', '/ˈɡɪmi/']
        }
    },
    'visual': {
        'filename': "5_图文词表模板.xlsx",
        'description': "专为“方言图文采集”功能设计。\n\n- 'id'列是项目的唯一标识符。\n- 'image_path'填写不带后缀的文件名，程序会自动查找图片。\n- 'prompt_text'是展示给被试者的提示文字。\n- 'notes'是仅研究者可见的备注。",
        'data': {
            'id': ['chicken_group', 'rice_field_harvest', 'vegetable_garden', 'old_farmhouse', 'drying_grains'],
            'image_path': ['sample_farm_life/chicken_group', 'sample_farm_life/rice_field_harvest', 'sample_farm_life/vegetable_garden', 'sample_farm_life/old_farmhouse', 'sample_farm_life/drying_grains'],
            'prompt_text': ['请用您的方言说说图片里的这些动物是什么，它们在做什么？', '描述一下这个场景。现在是农忙的什么季节？人们在做什么？', '图中的这些蔬菜，用你们那儿的话都叫什么名字？', '请描述一下这座老房子。它有什么特点？这种房子现在还常见吗？', '粮食丰收后，你们通常怎么晾晒和储存谷物？有什么特别的工具或说法吗？'],
            'notes': ['目标词汇：鸡、公鸡、母鸡、小鸡、喂食、啄米等。观察量词和动态描述。', '目标词汇：稻田、收割、稻谷、镰刀、打谷等。注意时态和场景描述。', '目标：多种常见蔬菜的方言名称。如：白菜、萝卜、茄子、辣椒、黄瓜等。', '目标：房屋结构、材料的方言词汇，以及相关的文化背景讨论。', '考察与与粮食处理相关的动词和名词。']
        }
    }
}


class ConverterPage(QWidget):
    def __init__(self, parent_window, WORD_LIST_DIR, icon_manager):
        super().__init__()
        self.parent_window = parent_window
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
        
        self.select_file_btn = QPushButton("  选择文件 或 拖拽至此\n (.py/.json/.csv/.xslx)")
        self.select_file_btn.setToolTip("选择一个词表文件 (.json, .xlsx, .xls, .csv, .py) 进行转换。\n您也可以直接将文件拖拽到此窗口。")
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
                if filepath.lower().endswith(('.json', '.xlsx', '.xls', '.csv', '.py')):
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
        for key, info in templates.items():
            display_name = os.path.splitext(info['filename'])[0].split('_', 1)[1]
            self.template_combo.addItem(display_name, key)

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
        self.template_description_label.setText(template_info.get('description', '无可用描述。'))

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

    def select_file_dialog(self):
        filters = "支持的词表文件 (*.json *.xlsx *.xls *.csv *.py);;JSON 文件 (*.json);;Excel 文件 (*.xlsx *.xls);;CSV 文件 (*.csv);;Python 脚本 (*.py)"
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
        elif ext == '.py':
            self.preview_df, self.detected_format = _py_to_dataframe(path)
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
        
        if self.source_path:
            source_basename = os.path.splitext(os.path.basename(self.source_path))[0]
        else:
            template_key = self.template_combo.currentData()
            template_info = templates.get(template_key, {})
            template_filename = template_info.get('filename', 'template')
            source_basename = os.path.splitext(template_filename)[0]

        default_filename = f"{source_basename}_converted"
        
        filters = "JSON 词表 (*.json);;Excel 文件 (*.xlsx);;CSV 文件 (*.csv);;Python 脚本 (旧版, *.py)"
        output_path, selected_filter = QFileDialog.getSaveFileName(self, "保存为", default_filename, filters)
        
        if not output_path:
            self.log("保存操作已取消。")
            return
            
        self.log(f"开始转换 -> {output_path}")
        QApplication.processEvents()
        success, msg = False, ""
        try:
            if "(*.json)" in selected_filter:
                json_str = _dataframe_to_json(self.preview_df, self.detected_format)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(json_str)
            elif "(*.xlsx)" in selected_filter:
                self.preview_df.to_excel(output_path, index=False)
            elif "(*.csv)" in selected_filter:
                self.preview_df.to_csv(output_path, index=False, encoding='utf-8-sig')
            elif "(*.py)" in selected_filter:
                py_code = _dataframe_to_py(self.preview_df, self.detected_format)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(py_code)
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
                flat_data.append({'组别': group_id, '单词': item.get('text'), 'IPA': item.get('note'), 'Language': item.get('lang')})
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
                groups_map[group_id].append({'text': str(row['单词']), 'note': str(row.get('IPA', '')), 'lang': str(row.get('Language', ''))})
            except (ValueError, KeyError): continue # Skip rows with invalid group id
        
        groups_list = [{"id": gid, "items": items} for gid, items in sorted(groups_map.items())]
        json_structure = {"meta": {"format": "standard_wordlist", "version": "1.0"}, "groups": groups_list}
    else:
        raise ValueError(f"不支持从格式 '{detected_format}' 转换为JSON。")
    return json.dumps(json_structure, indent=4, ensure_ascii=False)

def _dataframe_to_py(df, detected_format):
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
def _py_to_dataframe(filepath):
    """
    加载旧版的 .py 词表文件并将其转换为 DataFrame。
    这是一个向后兼容的函数。
    """
    # 动态加载 .py 文件需要 importlib
    import importlib.util

    module_name = f"temp_legacy_module_{os.path.basename(filepath).replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    if spec is None:
        raise ImportError(f"无法为 '{filepath}' 创建模块规范。")
    
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    if hasattr(module, 'ITEMS'): # 检测图文词表
        return pd.DataFrame(module.ITEMS), 'visual'
    elif hasattr(module, 'WORD_GROUPS'): # 检测标准词表
        flat_data = []
        for i, group in enumerate(module.WORD_GROUPS, 1):
            for word, value in group.items():
                ipa, lang = value if isinstance(value, tuple) and len(value) == 2 else (str(value), '')
                flat_data.append({'组别': i, '单词': word, 'IPA': ipa, 'Language': lang})
        return pd.DataFrame(flat_data), 'standard'
    else:
        raise ValueError("旧版 Python 词表文件中未找到 'ITEMS' 或 'WORD_GROUPS' 变量。")