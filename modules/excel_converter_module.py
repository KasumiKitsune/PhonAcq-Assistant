# --- START OF FILE excel_converter_module.py ---

# --- 模块元数据 ---
MODULE_NAME = "Excel/Python 转换器"
MODULE_DESCRIPTION = "智能识别Excel和Python词表文件，支持标准词表与图文词表的双向转换。"
# ---

import os
import pandas as pd
from datetime import datetime
import importlib.util

# ===== 新增/NEW: 导入必要的PyQt5控件 =====
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                             QFileDialog, QMessageBox, QComboBox, QGroupBox,
                             QPlainTextEdit)
from PyQt5.QtCore import Qt

# ===== 新增/NEW: 标准化模块入口函数 =====
def create_page(parent_window, WORD_LIST_DIR, MODULES_REF):
    """模块的入口函数，用于创建页面。"""
    return ConverterPage(parent_window, WORD_LIST_DIR, MODULES_REF)


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


# ===== 新增/NEW: 将 ConverterPage 类从主文件迁移至此 =====
class ConverterPage(QWidget):
    # ===== 修改/MODIFIED: 构造函数接收依赖项 =====
    def __init__(self, parent_window, WORD_LIST_DIR, MODULES_REF):
        super().__init__()
        self.parent_window = parent_window
        # ===== 修改/MODIFIED: 保存传入的依赖项 =====
        self.WORD_LIST_DIR = WORD_LIST_DIR
        self.MODULES = MODULES_REF

        main_layout=QHBoxLayout(self); left_layout=QVBoxLayout()
        self.convert_btn=QPushButton("选择Excel文件并转换"); self.convert_btn.setObjectName("AccentButton")
        templates_group=QGroupBox("生成模板"); templates_layout=QVBoxLayout(templates_group)
        template_selection_layout = QHBoxLayout()
        self.template_combo = QComboBox()
        self.generate_template_btn = QPushButton("生成选中模板")
        template_selection_layout.addWidget(self.template_combo, 1); template_selection_layout.addWidget(self.generate_template_btn)
        self.template_description_label = QLabel("请从上方选择一个模板以查看其详细说明。")
        self.template_description_label.setWordWrap(True); self.template_description_label.setAlignment(Qt.AlignTop)
        self.template_description_label.setObjectName("DescriptionLabel")
        templates_layout.addLayout(template_selection_layout); templates_layout.addWidget(self.template_description_label, 1)
        left_layout.addWidget(self.convert_btn); left_layout.addWidget(templates_group, 1); left_layout.addStretch()
        self.log_display=QPlainTextEdit(); self.log_display.setReadOnly(True)
        self.log_display.setPlaceholderText("此处将显示操作日志和结果..."); self.log_display.setObjectName("LogDisplay")
        main_layout.addLayout(left_layout,1); main_layout.addWidget(self.log_display,3)
        self.convert_btn.clicked.connect(self.run_conversion)
        self.generate_template_btn.clicked.connect(self.generate_template)
        self.template_combo.currentIndexChanged.connect(self.update_template_description);
        # 初始化时立即检查状态
        self.update_module_status()

    def log(self,message): self.log_display.appendPlainText(f"[{datetime.now():%H:%M:%S}] {message}")

    def update_module_status(self):
        # ===== 修改/MODIFIED: 使用 self.MODULES 进行判断 =====
        is_enabled = 'excel_converter_module' in self.MODULES
        self.convert_btn.setEnabled(is_enabled)
        self.template_combo.setEnabled(is_enabled)
        self.generate_template_btn.setEnabled(is_enabled)
        if not is_enabled:
            self.log("警告: Excel转换模块 (excel_converter_module.py) 未加载，相关功能已禁用。")
        else:
            self.populate_template_combo()

    def populate_template_combo(self):
        self.template_combo.clear()
        # 模板数据现在是本文件内的全局变量，可以直接使用
        for key, info in templates.items():
            display_name = os.path.splitext(info['filename'])[0][2:]
            self.template_combo.addItem(display_name, key)

    def update_template_description(self, index):
        if index == -1:
            self.template_description_label.setText("请从上方选择一个模板以查看其详细说明。"); return
        template_type = self.template_combo.currentData()
        description = templates.get(template_type, {}).get('description', '无可用描述。')
        self.template_description_label.setText(description)

    def generate_template(self):
        template_type = self.template_combo.currentData()
        # ===== 修改/MODIFIED: 调用本文件内的 generate_template 函数，并传入依赖 =====
        success, msg = generate_template(self.WORD_LIST_DIR, template_type=template_type)
        self.log(msg)
        if not success:
            QMessageBox.warning(self, "生成失败", msg)

    def run_conversion(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "选择Excel文件", "", "Excel 文件 (*.xlsx *.xls)")
        if not filepath:
            self.log("操作取消。"); return

        self.log(f"正在读取文件: {os.path.basename(filepath)}...")
        
        default_py_name = os.path.splitext(os.path.basename(filepath))[0] + ".py"
        # ===== 修改/MODIFIED: 使用 self.WORD_LIST_DIR =====
        default_save_path = os.path.join(self.WORD_LIST_DIR, default_py_name)

        output_filename, _ = QFileDialog.getSaveFileName(self, "保存为Python文件", default_save_path, "Python 文件 (*.py)")
        if not output_filename:
            self.log("操作取消。"); return

        # ===== 修改/MODIFIED: 调用本文件内的 convert_file 函数 =====
        success, msg = convert_file(filepath, output_filename)
        self.log(msg)
        if not success:
            QMessageBox.critical(self, "错误", msg)


# --- 内部辅助函数 (保持不变) ---
def _detect_excel_format(columns):
    """根据Excel的列名检测其格式类型。"""
    cols = set(columns)
    if 'id' in cols: return 'visual'
    if '组别' in cols and '词1' in cols: return 'multi'
    if '组别' in cols and '单词' in cols: return 'simple'
    return None

def _detect_py_format(module):
    """根据Python模块中的变量名检测其词表类型。"""
    if hasattr(module, 'ITEMS'): return 'visual'
    if hasattr(module, 'WORD_GROUPS'): return 'standard'
    return None

def _process_excel_to_visual_py(df):
    """处理DataFrame，生成图文词表的Python代码。"""
    items_list = []
    warnings = []
    if 'id' not in df.columns: return None, ["Excel缺少 'id' 列。"]

    for index, row in df.iterrows():
        item_id = str(row['id']).strip()
        if not item_id:
            warnings.append(f"第 {index + 2} 行：'id'字段为空，已跳过。")
            continue
        
        image_path_val = str(row.get('image_path', '')).strip()
        
        item_data = {
            'id': item_id,
            'image_path': image_path_val,
            'prompt_text': str(row.get('prompt_text', '')).strip(),
            'notes': str(row.get('notes', '')).strip()
        }
        items_list.append(item_data)
    
    if not items_list: return None, ["未在Excel中找到有效数据。"]

    py_code = "ITEMS = [\n"
    for item in items_list:
        py_code += "    {\n"
        for key, value in item.items():
            escaped_value = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
            py_code += f"        '{key}': '{escaped_value}',\n"
        py_code += "    },\n"
    py_code += "]\n"
    return py_code, warnings

def _process_excel_to_standard_py(df, file_format):
    """处理DataFrame，生成标准词表的Python代码。"""
    word_groups_list = []
    warnings = []

    if file_format == 'simple':
        word_groups_map = {}
        for index, row in df.iterrows():
            try:
                group_id = int(row['组别']); word = str(row['单词']).strip(); ipa = str(row.get('IPA', '')).strip()
                if not word: warnings.append(f"行 {index + 2}: '单词'为空，已跳过。"); continue
                if group_id not in word_groups_map: word_groups_map[group_id] = {}
                word_groups_map[group_id][word] = (ipa, '')
            except (ValueError, TypeError): warnings.append(f"行 {index + 2}: '组别'非整数，已跳过。"); continue
        word_groups_list = [v for k, v in sorted(word_groups_map.items())]
    
    elif file_format == 'multi':
        for index, row in df.iterrows():
            group_dict = {}
            for i in range(1, len(df.columns), 3):
                if i + 2 >= len(df.columns): break
                word_col, ipa_col, lang_col = df.columns[i], df.columns[i+1], df.columns[i+2]
                word = row[word_col]
                if pd.isna(word) or str(word).strip() == '': break
                word = str(word).strip()
                ipa = str(row[ipa_col]) if pd.notna(row[ipa_col]) else ''
                lang = str(row[lang_col]).strip() if pd.notna(row[lang_col]) else ''
                group_dict[word] = (ipa, lang)
            if group_dict: word_groups_list.append(group_dict)

    if not word_groups_list: return None, ["未在Excel中找到有效数据。"]

    py_code = "WORD_GROUPS = [\n"
    for group in word_groups_list:
        py_code += "    {\n"
        for word, (ipa, lang) in group.items():
            word_escaped = word.replace("'", "\\'"); ipa_escaped = ipa.replace("'", "\\'")
            py_code += f"        '{word_escaped}': ('{ipa_escaped}', '{lang}'),\n"
        py_code += "    },\n"
    py_code += "]\n"
    return py_code, warnings


# --- 主转换逻辑 (保持不变) ---
def _convert_excel_to_py(excel_path, output_py_path):
    """内部函数：将Excel文件转换为Python词表文件。"""
    try:
        df = pd.read_excel(excel_path, sheet_name=0, dtype=str).fillna('') # 读取所有列为字符串并填充空值
        file_format = _detect_excel_format(df.columns)

        if file_format is None:
            return False, "转换失败: 无法识别的Excel文件格式。请确保列名符合模板规范。"

        if file_format == 'visual':
            py_code, warnings = _process_excel_to_visual_py(df)
        else: # 'simple' or 'multi'
            py_code, warnings = _process_excel_to_standard_py(df, file_format)
        
        if py_code is None:
            return False, f"转换失败: {warnings[0] if warnings else '未知错误'}"
            
        header = f"# Auto-generated from: {os.path.basename(excel_path)}\n"
        header += f"# Conversion date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        with open(output_py_path, 'w', encoding='utf-8') as f:
            f.write(header + py_code)
        
        total_items = len(df)
        success_message = (f"转换成功！文件已保存至: {output_py_path}\n\n"
                           f"--- 转换报告 ---\n"
                           f"来源文件: {os.path.basename(excel_path)}\n"
                           f"成功转换 {total_items} 行数据。")
        if warnings:
            success_message += f"\n发现 {len(warnings)} 条警告:\n" + "\n".join([f"- {w}" for w in warnings])
        
        return True, success_message
    except Exception as e:
        return False, f"转换时发生未知错误: {e}"

def _convert_py_to_excel(py_path, output_excel_path):
    """内部函数：将Python词表文件转换为Excel文件。"""
    try:
        module_name = f"temp_module_{os.path.basename(py_path).replace('.', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, py_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        file_format = _detect_py_format(module)

        if file_format == 'visual':
            df = pd.DataFrame(module.ITEMS)
        elif file_format == 'standard':
            data_for_df = []
            for i, group in enumerate(module.WORD_GROUPS, 1):
                for word, value in group.items():
                    ipa, lang = value if isinstance(value, tuple) and len(value) == 2 else (str(value), '')
                    data_for_df.append({'组别': i, '单词': word, 'IPA': ipa, 'Language': lang})
            df = pd.DataFrame(data_for_df)
        else:
            return False, "转换失败: Python文件中未找到 'ITEMS' 或 'WORD_GROUPS' 变量。"
            
        df.to_excel(output_excel_path, index=False)
        return True, f"转换成功！Excel文件已保存至: {output_excel_path}"

    except Exception as e:
        return False, f"转换Python文件时出错: {e}"


# --- 供UI调用的公共接口 ---
def convert_file(input_path, output_path):
    """
    智能转换文件。根据输入和输出文件扩展名决定转换方向。
    """
    input_ext = os.path.splitext(input_path)[1].lower()
    output_ext = os.path.splitext(output_path)[1].lower()
    
    if input_ext in ['.xlsx', '.xls'] and output_ext == '.py':
        return _convert_excel_to_py(input_path, output_path)
    elif input_ext == '.py' and output_ext in ['.xlsx', '.xls']:
        return _convert_py_to_excel(input_path, output_path)
    else:
        return False, "转换方向无效。仅支持 'Excel -> .py' 或 '.py -> Excel'。"

def generate_template(output_dir, template_type='simple'):
    """
    根据指定的类型生成一个Excel模板文件。
    """
    if template_type not in templates:
        return False, f"未知的模板类型: {template_type}"
        
    template_info = templates[template_type]
    template_path = os.path.join(output_dir, template_info['filename'])
    
    try:
        df = pd.DataFrame(template_info['data'])
        df.to_excel(template_path, index=False)
        return True, f"成功！模板 '{template_info['filename']}' 已生成至: {output_dir}"
    except Exception as e:
        return False, f"生成模板文件时出错: {e}"