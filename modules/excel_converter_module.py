# --- START OF FILE modules/excel_converter_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "Excel/Python 转换器"
MODULE_DESCRIPTION = "智能识别Excel和Python词表文件，支持标准词表与图文词表的双向转换。"
# ---

import os
import sys
import pandas as pd
from datetime import datetime
import importlib.util

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                             QFileDialog, QMessageBox, QComboBox, QGroupBox,
                             QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem,
                             QHeaderView, QApplication, QFormLayout)
from PyQt5.QtCore import Qt, QMimeData, QSize
from PyQt5.QtGui import QIcon # [新增] QIcon 导入，为了类型提示和通用性

def get_base_path():
    """获取项目根目录的辅助函数"""
    if getattr(sys, 'frozen', False): return os.path.dirname(sys.executable)
    else: return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# [修改] 接收 icon_manager
def create_page(parent_window, WORD_LIST_DIR, MODULES_REF, icon_manager):
    """模块的入口函数，用于创建页面。"""
    return ConverterPage(parent_window, WORD_LIST_DIR, icon_manager)


# --- 模板定义 (保持不变) ---
templates = {
    'simple': {
        'filename': "1_标准词表_单语言模板.xlsx",
        'description': "最基础的格式，用于标准“口音采集”。\n\n- '组别'列用于分组。\n- '单词'和'IPA'列一一对应。",
        'data': { '组别': [1, 1, 2, 2], '单词': ['hello', 'world', 'apple', 'banana'], 'IPA': ['həˈloʊ', 'wɜːrld', 'ˈæpəl', 'bəˈnænə'] }
    },
    'multi': {
        'filename': "2_标准词表_多语言模板.xlsx",
        'description': "推荐的标准词表格式，功能全面。\n\n- 支持在同一行内放置多个不同语言的词条。\n- 'Language'列用于指定TTS语言。",
        'data': {
            '组别': [1, 2], '词1': ['an apple', "don't you"], '备注 (IPA)': ['/ən ˈæpəl/', '/ˈdoʊntʃu/'], 'Language': ['en-us', 'en-uk'],
            '词2': ['こんにちは', '石头'], '备注 (IPA).1': ['konnichiwa', 'shí tou'], 'Language.1': ['ja', 'zh-cn']
        }
    },
    'contrast': {
        'filename': "3_标准词表_音素对比模板.xlsx",
        'description': "专为语音学中的“最小音对”实验设计。\n\n- 使用'单语言'格式。\n- 将发音相似但意义不同的词（如 ship/sheep）放在同一组别下。",
        'data': {
            '组别': [1, 1, 2, 2, 3, 3],
            '单词': ['ship', 'sheep', 'sit', 'seat', 'cat', 'cart'],
            'IPA': ['ʃɪp', 'ʃiːp', 'sɪt', 'siːt', 'kæt', 'kɑːrt']
        }
    },
    'dialect': {
        'filename': "4_标准词表_方言适应性模板.xlsx",
        'description': "针对特定方言背景学习者的发音难点设计。\n\n- 示例为吴语区常见的难点音（如齿间音/θ/, /ð/）。",
        'data': {
            '组别': [1, 1, 1, 2, 2, 3, 3],
            '单词': ['think', 'this', 'three', 'very', 'voice', 'lazy', 'zeal'],
            'IPA': ['θɪŋk', 'ðɪs', 'θriː', 'ˈvɛri', 'vɔɪs', 'ˈleɪzi', 'ziːl']
        }
    },
    'phrase': {
        'filename': "5_标准词表_短语与连读模板.xlsx",
        'description': "用于测试语流中的语音现象，而非单个词汇。\n\n- 包含常见的连读、省音、同化等例子。",
        'data': {
            '组别': [1, 1, 2, 2],
            '单词': ['read it', 'an apple', "what's up", 'give me'],
            'IPA': ['/ˈriːd_ɪt/', '/ən_ˈæpəl/', '/wʌtsˈʌp/', '/ˈɡɪmi/']
        }
    },
    'visual': {
        'filename': "6_图文词表模板.xlsx",
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
    # [修改] 接收 icon_manager
    def __init__(self, parent_window, WORD_LIST_DIR, icon_manager):
        super().__init__()
        self.parent_window = parent_window
        self.WORD_LIST_DIR = WORD_LIST_DIR
        self.BASE_PATH = get_base_path()
        self.icon_manager = icon_manager # [新增] 保存 icon_manager

        self.source_path = None
        self.detected_format = None
        self.preview_df = None

        self.setAcceptDrops(True)
        self._init_ui()
        self.update_icons() # [新增] 首次加载时更新图标

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_splitter = QSplitter(Qt.Vertical)
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)

        left_panel = QWidget(); left_layout = QVBoxLayout(left_panel); left_panel.setFixedWidth(300)
        self.select_file_btn = QPushButton("选择文件 或 拖拽至此\n (.py / .xlsx)");
        # [修改] 更新tooltip
        self.select_file_btn.setToolTip("选择一个Python词表 (.py) 或 Excel文件 (.xlsx, .xls) 进行转换。\n您也可以直接将文件拖拽到此窗口。")
        self.select_file_btn.setIconSize(QSize(32, 32)) # 将图标大小设置为 32x32 像素
        templates_group = QGroupBox("生成Excel模板")
        templates_layout = QVBoxLayout(templates_group)
        self.template_combo = QComboBox()
        self.template_combo.setToolTip("选择一个预设的Excel模板格式。\n下方的描述会解释该模板的用途和结构。") # [新增] tooltip
        
        self.generate_template_btn = QPushButton("生成选中模板")
        self.generate_template_btn.setToolTip("在程序的'word_lists'文件夹中生成选定格式的空白Excel模板文件。") # [新增] tooltip
        
        templates_layout.addWidget(self.template_combo); templates_layout.addWidget(self.generate_template_btn)
        self.template_description_label = QLabel("请从上方选择一个模板以查看其详细说明。"); self.template_description_label.setWordWrap(True); self.template_description_label.setObjectName("DescriptionLabel")
        templates_layout.addWidget(self.template_description_label, 1)
        left_layout.addWidget(self.select_file_btn); left_layout.addWidget(templates_group, 1); left_layout.addStretch()

        right_panel = QGroupBox("预览与转换")
        right_layout = QVBoxLayout(right_panel)
        self.preview_label = QLabel("请先从左侧选择一个文件");
        self.preview_label.setToolTip("在此区域预览转换前的文件内容。") # [新增] tooltip
        
        self.preview_table = QTableWidget(); self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers); self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setWordWrap(True); self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.preview_table.setToolTip("预览文件的表格内容。\n转换操作将基于此表格内容进行。") # [新增] tooltip
        
        self.conversion_controls_widget = QWidget(); conversion_controls_layout = QFormLayout(self.conversion_controls_widget); conversion_controls_layout.setContentsMargins(0, 10, 0, 0)
        self.destination_combo = QComboBox();
        self.destination_combo.setToolTip("选择转换后文件的保存位置。\n程序会根据检测到的文件类型推荐一个最佳位置。") # [新增] tooltip
        
        self.confirm_btn = QPushButton("确认并开始转换"); self.confirm_btn.setObjectName("AccentButton")
        self.confirm_btn.setToolTip("确认转换设置，并开始执行文件格式转换操作。") # [新增] tooltip
        
        conversion_controls_layout.addRow("选择保存位置:", self.destination_combo); conversion_controls_layout.addRow("", self.confirm_btn)
        self.conversion_controls_widget.hide()
        right_layout.addWidget(self.preview_label); right_layout.addWidget(self.preview_table, 1); right_layout.addWidget(self.conversion_controls_widget)

        top_layout.addWidget(left_panel); top_layout.addWidget(right_panel, 1)
        log_group = QGroupBox("操作日志")
        log_layout = QVBoxLayout(log_group)
        self.log_display = QPlainTextEdit(); self.log_display.setReadOnly(True); self.log_display.setPlaceholderText("此处将显示操作日志和结果...")
        self.log_display.setToolTip("显示文件加载、转换过程和结果的详细日志信息。") # [新增] tooltip
        log_layout.addWidget(self.log_display)

        main_splitter.addWidget(top_widget); main_splitter.addWidget(log_group)
        main_splitter.setStretchFactor(0, 3); main_splitter.setStretchFactor(1, 1)
        main_layout.addWidget(main_splitter)

        self.select_file_btn.clicked.connect(self.select_file_dialog)
        self.generate_template_btn.clicked.connect(self.generate_template)
        self.template_combo.currentIndexChanged.connect(self.update_template_description)
        self.confirm_btn.clicked.connect(self.run_conversion)
        
        self.populate_template_combo()

    # --- [新增] 更新图标的方法 ---
    def update_icons(self):
        """从IconManager获取并设置所有图标。"""
        self.select_file_btn.setIcon(self.icon_manager.get_icon("open_file"))
        self.generate_template_btn.setIcon(self.icon_manager.get_icon("auto_detect"))
        self.confirm_btn.setIcon(self.icon_manager.get_icon("convert"))

    # --- [新增] 拖放事件处理 ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                filepath = urls[0].toLocalFile()
                if filepath.lower().endswith(('.py', '.xlsx', '.xls')):
                    event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            filepath = event.mimeData().urls()[0].toLocalFile()
            self.select_and_preview_file(filepath)

    def log(self, message):
        self.log_display.appendPlainText(f"[{datetime.now():%H:%M:%S}] {message}")

    def populate_template_combo(self):
        self.template_combo.clear()
        for key, info in templates.items():
            display_name = os.path.splitext(info['filename'])[0].split('_', 1)[1]
            self.template_combo.addItem(display_name, key)

    def update_template_description(self, index):
        if index == -1:
            self.template_description_label.setText("请从上方选择一个模板以查看其详细说明。"); return
        template_type = self.template_combo.currentData()
        description = templates.get(template_type, {}).get('description', '无可用描述。')
        self.template_description_label.setText(description)

    def generate_template(self):
        template_type = self.template_combo.currentData()
        success, msg = generate_template(self.WORD_LIST_DIR, template_type=template_type)
        self.log(msg)
        if not success: QMessageBox.warning(self, "生成失败", msg)

    def select_file_dialog(self):
        """打开文件选择对话框"""
        filepath, _ = QFileDialog.getOpenFileName(self, "选择要转换的文件", self.WORD_LIST_DIR, "Python 或 Excel 文件 (*.py *.xlsx *.xls)")
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
            self.update_conversion_ui()
        except Exception as e:
            self.log(f"错误: 加载文件失败 - {e}")
            self.preview_label.setText(f"加载失败: {os.path.basename(filepath)}")
            self.conversion_controls_widget.hide()
            QMessageBox.critical(self, "加载失败", f"无法加载或解析文件:\n{e}")

    def load_data_into_preview(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext in ['.xlsx', '.xls']:
            df = pd.read_excel(path, sheet_name=0, dtype=str).fillna('')
            self.detected_format = _detect_excel_format(df.columns)
            if self.detected_format is None: raise ValueError("无法识别的Excel格式。")
            self.preview_df = df
        elif ext == '.py':
            module_name = f"temp_module_{os.path.basename(path).replace('.', '_')}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.detected_format = _detect_py_format(module)
            if self.detected_format is None: raise ValueError("Python文件中未找到 'ITEMS' 或 'WORD_GROUPS'。")
            if self.detected_format == 'visual':
                self.preview_df = pd.DataFrame(module.ITEMS)
            elif self.detected_format == 'standard':
                data_for_df = []
                for i, group in enumerate(module.WORD_GROUPS, 1):
                    for word, value in group.items():
                        ipa, lang = value if isinstance(value, tuple) and len(value) == 2 else (str(value), '')
                        data_for_df.append({'组别': i, '单词': word, 'IPA': ipa, 'Language': lang})
                self.preview_df = pd.DataFrame(data_for_df)
        else:
            raise ValueError(f"不支持的文件类型: {ext}")

    def populate_preview_table(self):
        if self.preview_df is None: return
        self.preview_table.clear(); df = self.preview_df
        self.preview_table.setRowCount(df.shape[0]); self.preview_table.setColumnCount(df.shape[1])
        self.preview_table.setHorizontalHeaderLabels(df.columns)
        for i, row in df.iterrows():
            for j, val in enumerate(row):
                self.preview_table.setItem(i, j, QTableWidgetItem(str(val)))
        self.preview_table.resizeRowsToContents()

    def update_conversion_ui(self):
        self.destination_combo.clear()
        
        desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')
        destinations = {
            "桌面 (Desktop)": desktop_path,
            "标准词表 (主)": os.path.join(self.BASE_PATH, "word_lists"),
            "图文词表 (主)": os.path.join(self.BASE_PATH, "dialect_visual_wordlists"),
            "标准词表 (速记卡)": os.path.join(self.BASE_PATH, "flashcards", "common_wordlists"),
            "图文词表 (速记卡)": os.path.join(self.BASE_PATH, "flashcards", "visual_wordlists")
        }

        for name, path in destinations.items():
            self.destination_combo.addItem(name, path)
            
        # --- CFE-5: 智能格式推荐逻辑 ---
        recommended_index = -1
        if self.detected_format == 'visual':
            for i in range(self.destination_combo.count()):
                if "图文词表" in self.destination_combo.itemText(i):
                    recommended_index = i; break
        elif self.detected_format in ['standard', 'simple', 'multi']:
            for i in range(self.destination_combo.count()):
                if "标准词表" in self.destination_combo.itemText(i):
                    recommended_index = i; break
        if recommended_index != -1:
            self.destination_combo.setCurrentIndex(recommended_index)
            self.log(f"提示：已根据文件格式自动推荐保存位置。")

        source_ext = os.path.splitext(self.source_path)[1].lower()
        target_ext = ".py" if source_ext in ['.xlsx', '.xls'] else ".xlsx"
        self.preview_label.setText(f"预览: {os.path.basename(self.source_path)} -> (新文件{target_ext})")
        self.conversion_controls_widget.show()

    def run_conversion(self):
        if self.preview_df is None or self.source_path is None: self.log("错误: 没有可转换的数据。"); return
        dest_dir = self.destination_combo.currentData()
        if not dest_dir: self.log("错误: 请选择一个保存位置。"); return
        source_basename = os.path.splitext(os.path.basename(self.source_path))[0]
        source_ext = os.path.splitext(self.source_path)[1].lower()
        target_ext = ".py" if source_ext in ['.xlsx', '.xls'] else ".xlsx"
        output_filename = f"{source_basename}{target_ext}"; output_path = os.path.join(dest_dir, output_filename)
        if os.path.exists(output_path):
            reply = QMessageBox.question(self, '文件已存在', f"文件 '{output_filename}' 已存在于目标位置。\n您想覆盖它吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No: self.log("操作取消：用户选择不覆盖现有文件。"); return
        self.log(f"开始转换 -> {output_path}"); QApplication.processEvents()
        success = False; msg = ""
        try:
            if target_ext == ".py":
                py_code, warnings = _process_df_to_py_code(self.preview_df, self.detected_format)
                if py_code is None: raise ValueError(warnings[0] if warnings else "无法从DataFrame生成代码。")
                header = f"# Auto-generated from: {os.path.basename(self.source_path)}\n"
                header += f"# Conversion date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                with open(output_path, 'w', encoding='utf-8') as f: f.write(header + py_code)
                success = True; msg = f"成功转换！文件已保存至: {output_path}"
                if warnings: msg += "\n警告:\n" + "\n".join([f"- {w}" for w in warnings])
            else:
                self.preview_df.to_excel(output_path, index=False); success = True
                msg = f"成功转换！文件已保存至: {output_path}"
        except Exception as e: success = False; msg = f"转换失败: {e}"
        self.log(msg)
        if not success: QMessageBox.critical(self, "错误", msg)
        else: QMessageBox.information(self, "成功", msg)

# --- 内部辅助函数 (无重大修改，保持健壮性) ---
def _detect_excel_format(columns):
    cols = set(columns)
    if 'id' in cols and 'image_path' in cols: return 'visual'
    if '组别' in cols and '词1' in cols: return 'multi'
    if '组别' in cols and '单词' in cols: return 'simple'
    return None

def _detect_py_format(module):
    if hasattr(module, 'ITEMS'): return 'visual'
    if hasattr(module, 'WORD_GROUPS'): return 'standard'
    return None

def _process_df_to_py_code(df, file_format):
    if file_format == 'visual':
        return _process_excel_to_visual_py(df)
    elif file_format in ['simple', 'multi', 'standard']:
        return _process_excel_to_standard_py(df, _detect_excel_format(df.columns) or 'simple')
    return None, ["未知的内部数据格式。"]

def _process_excel_to_visual_py(df):
    items_list = []; warnings = []
    if 'id' not in df.columns: return None, ["Excel缺少 'id' 列。"]
    for index, row in df.iterrows():
        item_id = str(row['id']).strip()
        if not item_id: warnings.append(f"第 {index + 2} 行：'id'字段为空，已跳过。"); continue
        item_data = {'id': item_id, 'image_path': str(row.get('image_path', '')).strip(), 'prompt_text': str(row.get('prompt_text', '')).strip(), 'notes': str(row.get('notes', '')).strip()}
        items_list.append(item_data)
    if not items_list: return None, ["未在Excel中找到有效数据。"]
    py_code = "ITEMS = [\n";
    for item in items_list:
        py_code += "    {\n"
        for key, value in item.items():
            escaped_value = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
            py_code += f"        '{key}': '{escaped_value}',\n"
        py_code += "    },\n"
    py_code += "]\n"; return py_code, warnings

def _process_excel_to_standard_py(df, file_format):
    word_groups_list = []; warnings = []
    if file_format == 'simple':
        word_groups_map = {}
        for index, row in df.iterrows():
            try:
                group_id = int(row['组别']); word = str(row['单词']).strip(); ipa = str(row.get('IPA', '')).strip(); lang = str(row.get('Language', '')).strip()
                if not word: warnings.append(f"行 {index + 2}: '单词'为空，已跳过。"); continue
                if group_id not in word_groups_map: word_groups_map[group_id] = {}
                word_groups_map[group_id][word] = (ipa, lang)
            except (ValueError, TypeError): warnings.append(f"行 {index + 2}: '组别'非整数，已跳过。"); continue
        word_groups_list = [v for k, v in sorted(word_groups_map.items())]
    elif file_format == 'multi':
        for index, row in df.iterrows():
            group_dict = {}
            for i in range(1, (len(df.columns) // 3) * 3 + 1, 3):
                word_col, ipa_col, lang_col = df.columns[i-1], df.columns[i], df.columns[i+1]; word = row.get(word_col)
                if pd.isna(word) or str(word).strip() == '': break
                word = str(word).strip(); ipa = str(row.get(ipa_col)) if pd.notna(row.get(ipa_col)) else ''; lang = str(row.get(lang_col)).strip() if pd.notna(row.get(lang_col)) else ''
                group_dict[word] = (ipa, lang)
            if group_dict: word_groups_list.append(group_dict)
    if not word_groups_list: return None, ["未在Excel中找到有效数据。"]
    py_code = "WORD_GROUPS = [\n";
    for group in word_groups_list:
        py_code += "    {\n"
        for word, (ipa, lang) in group.items():
            word_escaped = word.replace("'", "\\'"); ipa_escaped = ipa.replace("'", "\\'")
            py_code += f"        '{word_escaped}': ('{ipa_escaped}', '{lang}'),\n"
        py_code += "    },\n"
    py_code += "]\n"; return py_code, warnings
    
def generate_template(output_dir, template_type='simple'):
    if template_type not in templates: return False, f"未知的模板类型: {template_type}"
    template_info = templates[template_type]; template_path = os.path.join(output_dir, template_info['filename'])
    try:
        df = pd.DataFrame(template_info['data']); df.to_excel(template_path, index=False)
        return True, f"成功！模板 '{template_info['filename']}' 已生成至: {output_dir}"
    except Exception as e: return False, f"生成模板文件时出错: {e}"