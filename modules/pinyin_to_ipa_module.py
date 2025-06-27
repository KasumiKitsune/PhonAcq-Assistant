# --- 模块元数据 ---
MODULE_NAME = "拼音转IPA"
MODULE_DESCRIPTION = "将汉字转换为国际音标，支持多种方案和音变规则。"
# ---

import os
import sys
import re
import html
import inspect
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                             QMessageBox, QComboBox, QFormLayout, QGroupBox, QPlainTextEdit, QTextBrowser,
                             QTableWidget, QTableWidgetItem, QHeaderView, QSplitter)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor # 导入 QFont

try:
    import pypinyin
    import pypinyin.style._utils as pypinyin_utils
except ImportError:
    class MockPypinyin:
        def pinyin(self, *args, **kwargs):
            QMessageBox.critical(None, "依赖库缺失", "错误: `pypinyin` 库未安装。\n\n请运行: pip install pypinyin")
            return [[]]
    pypinyin = MockPypinyin()
import inspect

# ===== 修正/FIX: 重构版本检查和备用类逻辑 =====
SUPPORTS_NEUTRAL_TONE_WITH_5 = False
try:
    import pypinyin
    import pypinyin.style._utils as pypinyin_utils

    # 只有当 pypinyin 成功导入时，才进行版本检查
    try:
        sig = inspect.signature(pypinyin.pinyin)
        if 'neutral_tone_with_5' in sig.parameters:
            SUPPORTS_NEUTRAL_TONE_WITH_5 = True
            print("INFO: pypinyin supports 'neutral_tone_with_5'.")
        else:
            print("提示: 本地的 pypinyin 版本不支持 'neutral_tone_with_5'，“普通话音变”可能有误。")
    except Exception as e:
        print(f"WARN: Could not inspect pypinyin signature, assuming older version. Error: {e}")

except ImportError:
    # 只有当 pypinyin 导入失败时，才定义并使用 MockPypinyin
    print("ERROR: pypinyin library not found. Using mock object.")
    class MockPypinyin:
        def pinyin(self, *args, **kwargs):
            # 这里的 QMessageBox 需要在 UI 线程中调用，但模块加载时可能还不是
            # 更安全的方式是让 create_page 返回一个错误提示页面
            print("CRITICAL: pypinyin is not installed!")
            return [[]]
    pypinyin = MockPypinyin()
    # 如果 pypinyin 导入失败，pypinyin_utils 肯定也不存在，定义一个假的
    class MockPypinyinUtils:
        def get_final(self, pinyin): return pinyin
    pypinyin_utils = MockPypinyinUtils()

# --- 模块的创建入口 ---
def create_page(parent_window, ToggleSwitchClass):
    return PinyinToIpaPage(parent_window, ToggleSwitchClass)

# ==================== IPA 转换核心逻辑 ====================

TONE_MARKS = {'1':'⁵⁵','2':'³⁵','3':'²¹⁴','4':'⁵¹','5':'', '3s':'²¹'}

IPA_SCHEME_Standard = {
    "initials": {'b':'p','p':'pʰ','m':'m','f':'f','d':'t','t':'tʰ','n':'n','l':'l','g':'k','k':'kʰ','h':'x','j':'tɕ','q':'tɕʰ','x':'ɕ','zh':'tʂ','ch':'tʂʰ','sh':'ʂ','r':'ɻ','z':'ts','c':'tsʰ','s':'s'},
    "finals": {'a':'a','o':'o','e':'ɤ','i':'i','u':'u','ü':'y','ê':'ɛ','er':'ɚ','ai':'aɪ','ei':'eɪ','ao':'ɑʊ','ou':'oʊ','an':'an','en':'ən','in':'in','ün':'yn','ang':'ɑŋ','eng':'ɤŋ','ing':'iŋ','ong':'ʊŋ','ia':'ia','iao':'iɑʊ','ie':'ie','iu':'ioʊ','ian':'iɛn','iang':'iɑŋ','iong':'iʊŋ','ua':'ua','uo':'uo','uai':'uaɪ','ui':'ueɪ','uan':'uan','un':'uən','uang':'wɑŋ','ueng':'wɤŋ','üe':'ye','üan':'yɛn', 'iou':'ioʊ','uei':'ueɪ','uen':'uən', 've': 'ye', 'van': 'yɛn', 'vn': 'yn'},
    "syllables": {'zi':'tsɹ̩','ci':'tsʰɹ̩','si':'sɹ̩','zhi':'tʂɻ̍','chi':'tʂʰɻ̍','shi':'ʂɻ̍','ri':'ɻ̍','yi':'i','wu':'u','yu':'y','ye':'ie','yin':'in','yun':'yn','yuan':'yɛn','ying':'iŋ', 'm':'m̩','n':'n̩','ng':'ŋ̍','hm':'hm̩','hng':'hŋ̍'}
}
IPA_SCHEME_Yanshi = {
    "initials": {'b':'p','p':'pʰ','m':'m','f':'f','d':'t','t':'tʰ','n':'n','l':'l','g':'k','k':'kʰ','h':'x','j':'tɕ','q':'tɕʰ','x':'ɕ','zh':'tʂ','ch':'tʂʰ','sh':'ʂ','r':'ʐ','z':'ts','c':'tsʰ','s':'s'},
    "finals": {'a':'Ą','o':'o','e':'ɣ','i':'i','u':'u','ü':'y','er':'ɚ','ai':'aɪ','ei':'eɪ','ao':'ɑʊ','ou':'oʊ','an':'an','en':'ən','in':'in','ün':'yn','ang':'ɑŋ','eng':'əŋ','ing':'iŋ','ong':'ʊŋ','ua':'uĄ','uo':'uo','uai':'uaɪ','ui':'ueɪ','uei':'ueɪ','uan':'uan','un':'uən','uen':'uən','uang':'uɑŋ','ueng':'uəŋ','ia':'iĄ','ie':'iE','iao':'iɑʊ','iu':'ioʊ','iou':'ioʊ','ian':'iæn','iang':'iɑŋ','iong':'yŋ','üe':'yE','üan':'yæn','ng':'ŋ̍'},
    "syllabic_vowels": {'zi':'ɿ','ci':'ɿ','si':'ɿ','zhi':'ʅ','chi':'ʅ','shi':'ʅ','ri':'ʅ'}
}
IPA_SCHEME_Kuanshi = {
    "initials": {'b':'p','p':'pʰ','m':'m','f':'f','d':'t','t':'tʰ','n':'n','l':'l','g':'k','k':'kʰ','h':'x','j':'tɕ','q':'tɕʰ','x':'ɕ','zh':'tʂ','ch':'tʂʰ','sh':'ʂ','r':'ʐ','z':'ts','c':'tsʰ','s':'s'},
    "finals": {'a':'a','o':'o','e':'e','i':'i','u':'u','ü':'y','er':'ɚ','ai':'ai','ei':'ei','ao':'ɑu','ou':'ou','an':'an','en':'ən','in':'in','ün':'yn','ang':'ɑŋ','eng':'əŋ','ing':'iŋ','ong':'uŋ','ua':'ua','uo':'uo','uai':'uai','ui':'uei','uei':'uei','uan':'uan','un':'uən','uen':'uən','uang':'uɑŋ','ueng':'uəŋ','ia':'ia','ie':'iɛ','iao':'iɑu','iu':'iou','iou':'iou','ian':'iɛn','iang':'iɑŋ','iong':'yŋ','üe':'yɛ','üan':'yɛn','ng':'ŋ'},
    "syllabic_vowels": {'zi':'ɿ','ci':'ɿ','si':'ɿ','zhi':'ʅ','chi':'ʅ','shi':'ʅ','ri':'ʅ'}
}

def get_tone(pinyin_with_tone):
    tone = re.search(r'([1-5])$', pinyin_with_tone)
    return tone.group(1) if tone else '5'

def apply_sandhi(words, pinyin_list):
    if len(words) != len(pinyin_list): return [(p, False) for p in pinyin_list]
    pinyins = list(pinyin_list); sandhi_flags = [False] * len(pinyins); original_tones = [get_tone(p) for p in pinyins]
    for i in range(len(pinyins)):
        if words[i] == '啊' and pinyins[i].startswith('a') and i > 0:
            prev_pinyin_no_tone = pinyins[i-1][:-1]
            prev_final = pypinyin_utils.get_final(prev_pinyin_no_tone) if prev_pinyin_no_tone else ''
            tone = get_tone(pinyins[i]); new_final = ''
            if prev_final.endswith(('a', 'o', 'e', 'ê', 'i', 'ü')): new_final = f"ya{tone}"
            elif prev_final.endswith('u'): new_final = f"wa{tone}"
            elif prev_final.endswith('n'): new_final = f"na{tone}"
            elif prev_final.endswith('ng'): new_final = f"nga{tone}"
            if new_final: pinyins[i] = new_final; sandhi_flags[i] = True
    for i in range(len(pinyins)):
        word, pinyin = words[i], pinyins[i]
        if word == '一' and original_tones[i] == '1':
            is_sandhi = True
            if i > 0 and i + 1 < len(words) and words[i-1] == words[i+1]: pinyins[i] = 'yi5'
            elif i + 1 < len(pinyins):
                next_tone = get_tone(pinyins[i+1])
                if next_tone == '4': pinyins[i] = 'yi2'
                elif next_tone in ['1', '2', '3']: pinyins[i] = 'yi4'
            else: is_sandhi = False
            if is_sandhi: sandhi_flags[i] = True
        if word == '不' and original_tones[i] == '4':
            is_sandhi = True
            if i > 0 and i + 1 < len(words) and words[i-1] == words[i+1]: pinyins[i] = 'bu5'
            elif i + 1 < len(pinyins) and get_tone(pinyins[i+1]) == '4': pinyins[i] = 'bu2'
            else: is_sandhi = False
            if is_sandhi: sandhi_flags[i] = True
    temp_pinyins_for_3rd_tone = list(pinyins)
    i = len(temp_pinyins_for_3rd_tone) - 2
    while i >= 0:
        if get_tone(temp_pinyins_for_3rd_tone[i]) == '3' and get_tone(temp_pinyins_for_3rd_tone[i+1]) == '3':
            pinyins[i] = temp_pinyins_for_3rd_tone[i][:-1] + '2'; sandhi_flags[i] = True
        i -= 1
    for i in range(len(pinyins)):
        if original_tones[i] == '3' and get_tone(pinyins[i]) == '3':
            is_last = (i == len(pinyins) - 1)
            if not is_last and get_tone(pinyins[i+1]) != '3':
                pinyins[i] = pinyins[i][:-1] + '3s'; sandhi_flags[i] = True
    return list(zip(pinyins, sandhi_flags))

def convert_pinyin_to_ipa(pinyin_sandhi_list, scheme):
    ipa_list = []
    for pinyin, is_sandhi in pinyin_sandhi_list:
        match = re.match(r'([a-z-üv]+)(3s|\d)?', pinyin)
        pinyin_no_tone, tone_mark_str = match.groups() if match else (pinyin, '5')
        if tone_mark_str is None: tone_mark_str = '5'
        tone_ipa = TONE_MARKS.get('3_sandhi_half' if tone_mark_str == '3s' else tone_mark_str, '')
        if is_sandhi and tone_ipa.strip(): tone_ipa = f'<span style="color: red;">{tone_ipa}</span>'
        ipa_syllable = ""
        if pinyin_no_tone in scheme.get("syllables", {}): ipa_syllable = scheme["syllables"][pinyin_no_tone]
        elif pinyin_no_tone in scheme.get("syllabic_vowels", {}):
            initial_part = pinyin_no_tone[:-1] if len(pinyin_no_tone)>1 else ""; vowel_part = scheme["syllabic_vowels"][pinyin_no_tone]
            initial_ipa = scheme["initials"].get(initial_part, ""); ipa_syllable = f"{initial_ipa}{vowel_part}"
        elif pinyin_no_tone == 'fu': ipa_syllable = 'fʋ̩'
        else:
            initial = ""; final = pinyin_no_tone
            for i in ['zh','ch','sh','b','p','m','f','d','t','n','l','g','k','h','j','q','x','r','z','c','s','y','w']:
                if pinyin_no_tone.startswith(i): initial = i; final = pinyin_no_tone[len(i):]; break
            initial_ipa = scheme["initials"].get(initial, "")
            final = final.replace('v', 'ü')
            if initial in ['j', 'q', 'x', 'y'] and final.startswith('u'): final = 'ü' + final[1:]
            if final == 'iu': final = 'iou'
            if final == 'ui': final = 'uei'
            if final == 'un' and initial not in ['j', 'q', 'x', 'y']: final = 'uen'
            if initial == 'y': final = 'i' + final if final else 'i'
            elif initial == 'w': final = 'u' + final if final else 'u'
            final_ipa = scheme["finals"].get(final, f"<{final}?>")
            ipa_syllable = f"{initial_ipa}{final_ipa}"
        ipa_list.append(f"[{ipa_syllable}]{tone_ipa}")
    return " ".join(ipa_list).replace("] [", "][")

# ==================== UI 类定义 ====================
class PinyinToIpaPage(QWidget):
    def __init__(self, parent_window, ToggleSwitchClass):
        super().__init__()
        self.parent_window = parent_window
        self.ToggleSwitch = ToggleSwitchClass
        self.schemes = {"标准方案": IPA_SCHEME_Standard, "严式音标": IPA_SCHEME_Yanshi, "宽式音标": IPA_SCHEME_Kuanshi}
        self._init_ui()
        self.on_scheme_changed(0) # 初始化时加载一次规则

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        left_panel = QWidget(); left_layout = QVBoxLayout(left_panel)

        io_group = QGroupBox("文本转换"); io_layout = QVBoxLayout(io_group)
        self.input_text = QPlainTextEdit(); self.input_text.setPlaceholderText("在此处输入或粘贴汉字，支持换行...")
        self.output_text = QTextBrowser(); self.output_text.setReadOnly(True); self.output_text.setOpenExternalLinks(False)
        self.output_text.setPlaceholderText("转换后的IPA将显示在这里...")
        io_layout.addWidget(QLabel("输入文本:")); io_layout.addWidget(self.input_text)
        io_layout.addWidget(QLabel("输出IPA:")); io_layout.addWidget(self.output_text)

        control_group = QGroupBox("转换选项"); control_layout = QFormLayout(control_group)
        self.scheme_combo = QComboBox(); self.scheme_combo.addItems(self.schemes.keys())
        self.sandhi_switch = self.ToggleSwitch(); self.sandhi_switch.setChecked(True)
        sandhi_layout = QHBoxLayout(); sandhi_layout.addWidget(self.sandhi_switch); sandhi_layout.addStretch()
        self.convert_button = QPushButton("转换"); self.convert_button.setObjectName("AccentButton")
        control_layout.addRow("转换方案:", self.scheme_combo)
        control_layout.addRow("考虑普通话音变:", sandhi_layout)
        
        left_layout.addWidget(io_group); left_layout.addWidget(control_group)
        left_layout.addWidget(self.convert_button, 0, Qt.AlignRight)

        right_panel = QSplitter(Qt.Vertical); right_panel.setFixedWidth(400)
        scheme_rules_group = QGroupBox("当前方案规则")
        scheme_rules_layout = QVBoxLayout(scheme_rules_group); scheme_rules_layout.setContentsMargins(5, 5, 5, 5)
        self.scheme_rules_table = QTableWidget()
        self.scheme_rules_table.setColumnCount(4); self.scheme_rules_table.setHorizontalHeaderLabels(["拼音", "IPA", "拼音", "IPA"])
        self.scheme_rules_table.verticalHeader().setVisible(False); self.scheme_rules_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.scheme_rules_table.setSelectionBehavior(QTableWidget.SelectRows); self.scheme_rules_table.setAlternatingRowColors(True)
        header = self.scheme_rules_table.horizontalHeader()
        for i in range(4): header.setSectionResizeMode(i, QHeaderView.Stretch)
        scheme_rules_layout.addWidget(self.scheme_rules_table)
        
        sandhi_rules_group = QGroupBox("普通话主要音变规则")
        sandhi_rules_layout = QVBoxLayout(sandhi_rules_group); sandhi_rules_layout.setContentsMargins(5, 5, 5, 5)
        self.sandhi_rules_table = QTableWidget()
        self.sandhi_rules_table.setColumnCount(2); self.sandhi_rules_table.setHorizontalHeaderLabels(["规则", "示例"])
        self.sandhi_rules_table.verticalHeader().setVisible(False); self.sandhi_rules_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.sandhi_rules_table.setWordWrap(True)
        header = self.sandhi_rules_table.horizontalHeader(); header.setSectionResizeMode(0, QHeaderView.Stretch); header.setSectionResizeMode(1, QHeaderView.Stretch)
        sandhi_rules_layout.addWidget(self.sandhi_rules_table)

        right_panel.addWidget(scheme_rules_group); right_panel.addWidget(sandhi_rules_group)
        right_panel.setStretchFactor(0, 2); right_panel.setStretchFactor(1, 1)

        main_layout.addWidget(left_panel, 1); main_layout.addWidget(right_panel)
        
        self.convert_button.clicked.connect(self.on_convert_clicked)
        self.scheme_combo.currentIndexChanged.connect(self.on_scheme_changed)
        
        # ===== 新增/NEW: 连接鼠标悬停事件以显示Tooltip =====
        self.sandhi_rules_table.setMouseTracking(True) # 必须开启才能实时捕捉鼠标进入
        self.sandhi_rules_table.cellEntered.connect(self.on_sandhi_cell_entered)

        self.populate_sandhi_table()

    def on_scheme_changed(self, index):
        scheme_name = self.scheme_combo.currentText()
        scheme = self.schemes.get(scheme_name)
        if not scheme: return
        self.populate_scheme_table(scheme)

    def populate_scheme_table(self, scheme):
        # ... (此方法保持不变)
        self.scheme_rules_table.setRowCount(0); all_items = []
        all_items.append(("声母 (Initials)", None))
        for p, ipa in scheme.get('initials', {}).items(): all_items.append((p, ipa))
        all_items.append(("韵母 (Finals)", None))
        for p, ipa in scheme.get('finals', {}).items():
            if p in ['iou', 'uei', 'uen', 've', 'van', 'vn']: continue
            all_items.append((p, ipa))
        syllabics = {**scheme.get("syllables", {}), **scheme.get("syllabic_vowels", {})}
        if syllabics:
            all_items.append(("整体认读 / 舌尖元音", None))
            for p, ipa in sorted(syllabics.items()): all_items.append((p, ipa))
        row = 0; i = 0
        while i < len(all_items):
            self.scheme_rules_table.insertRow(row); p1, ipa1 = all_items[i]
            if ipa1 is None:
                title_item = QTableWidgetItem(p1); title_item.setTextAlignment(Qt.AlignCenter)
                font = title_item.font(); font.setBold(True); title_item.setFont(font)
                self.scheme_rules_table.setItem(row, 0, title_item); self.scheme_rules_table.setSpan(row, 0, 1, 4); i += 1
            else:
                p_item1 = QTableWidgetItem(p1); ipa_item1 = QTableWidgetItem(f"[{ipa1}]"); ipa_item1.setFont(QFont("Doulos SIL", 10))
                self.scheme_rules_table.setItem(row, 0, p_item1); self.scheme_rules_table.setItem(row, 1, ipa_item1); i += 1
                if i < len(all_items):
                    p2, ipa2 = all_items[i]
                    if ipa2 is not None:
                        p_item2 = QTableWidgetItem(p2); ipa_item2 = QTableWidgetItem(f"[{ipa2}]"); ipa_item2.setFont(QFont("Doulos SIL", 10))
                        self.scheme_rules_table.setItem(row, 2, p_item2); self.scheme_rules_table.setItem(row, 3, ipa_item2); i += 1
            row += 1
        self.scheme_rules_table.resizeRowsToContents()


    def populate_sandhi_table(self):
        # ... (此方法保持不变)
        sandhi_data = [("“一”和“不”的变调",None),("在去声(⁵¹)前","一(yī) → 阳平(³⁵) 例: 一样 yí yàng\n不(bù) → 阳平(³⁵) 例: 不怕 bú pà"),("“一”在非去声前","一(yī) → 去声(⁵¹) 例: 一天 yì tiān"),("“不”在非去声前","不(bù) → 原调去声(⁵¹) 例: 不好 bù hǎo"),("在重叠词中","读轻声 例: 看一看 kàn yi kan"),("上声(²¹⁴)的变调",None),("上 + 上","前一个变阳平(³⁵) 例: 你好 nǐ hǎo → ní hǎo"),("上 + 非上","变为半上(²¹) 例: 很好 hěn hǎo (hěn读半上)"),("多上相连","从右向左两两变调 例: 小组长 → xiáo zú zhǎng"),("“啊”的变读",None),("前韵尾 a,o,e,ê,i,ü","啊(a) → 呀(ya)"),("前韵尾 u(ao,iao)","啊(a) → 哇(wa)"),("前韵尾 n","啊(a) → 哪(na)"),("前韵尾 ng","啊(a) → 啊(nga)")]
        self.sandhi_rules_table.setRowCount(0)
        for rule, example in sandhi_data:
            row = self.sandhi_rules_table.rowCount(); self.sandhi_rules_table.insertRow(row)
            if example is None:
                title_item = QTableWidgetItem(rule); font = title_item.font(); font.setBold(True); title_item.setFont(font)
                title_item.setForeground(QColor("#788C67")); self.sandhi_rules_table.setItem(row, 0, title_item); self.sandhi_rules_table.setSpan(row, 0, 1, 2)
            else:
                rule_item = QTableWidgetItem(rule); example_item = QTableWidgetItem(example)
                rule_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft); example_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self.sandhi_rules_table.setItem(row, 0, rule_item); self.sandhi_rules_table.setItem(row, 1, example_item)
        self.sandhi_rules_table.resizeRowsToContents()

    def get_sandhi_rules_html(self): # 这个方法现在不再被使用，但保留也无妨
        pass

    # ===== 新增/NEW: 用于显示悬停提示的槽函数 =====
    def on_sandhi_cell_entered(self, row, column):
        """当鼠标进入音变规则表格的单元格时，检查是否需要显示Tooltip。"""
        item = self.sandhi_rules_table.item(row, column)
        if not item: return

        # 获取单元格的字体信息以准确计算文本宽度
        font_metrics = self.sandhi_rules_table.fontMetrics()
        text_width = font_metrics.horizontalAdvance(item.text())
        
        # 获取列宽，减去一些内边距作为缓冲
        column_width = self.sandhi_rules_table.columnWidth(column) - 15 

        if text_width > column_width:
            item.setToolTip(item.text())
        else:
            item.setToolTip("") # 如果内容完整显示，则清除提示

    # ===== 修改/MODIFIED: 彻底重构 on_convert_clicked 以支持标点和换行 =====
    def on_convert_clicked(self):
        input_text = self.input_text.toPlainText()
        if not input_text.strip():
            self.output_text.clear(); return

        try:
            output_lines_html = []
            # 1. 按行处理
            for line in input_text.splitlines():
                if not line.strip():
                    output_lines_html.append("")
                    continue

                # 2. 将每一行分割成“汉字串”和“非汉字串”
                # re.split with a capturing group keeps the delimiters
                segments = re.split(r'([^\u4e00-\u9fff]+)', line)
                
                ipa_segments_for_line = []
                for segment in segments:
                    if not segment: continue

                    # 3. 判断片段类型并分别处理
                    if re.search(r'[\u4e00-\u9fff]', segment): # 如果是汉字串
                        pinyin_kwargs = {'style': pypinyin.Style.TONE3, 'heteronym': False}
                        if SUPPORTS_NEUTRAL_TONE_WITH_5:
                            pinyin_kwargs['neutral_tone_with_5'] = True
                        
                        pinyin_list = [p[0] for p in pypinyin.pinyin(segment, **pinyin_kwargs)]
                        words_list = [w[0] for w in pypinyin.pinyin(segment, style=pypinyin.Style.NORMAL, heteronym=False)]
                        
                        processed_pinyin_list_with_info = []
                        if self.sandhi_switch.isChecked():
                            processed_pinyin_list_with_info = apply_sandhi(words_list, pinyin_list)
                        else:
                            processed_pinyin_list_with_info = [(p, False) for p in pinyin_list]
                        
                        selected_scheme = self.schemes.get(self.scheme_combo.currentText())
                        ipa_part = convert_pinyin_to_ipa(processed_pinyin_list_with_info, selected_scheme)
                        ipa_segments_for_line.append(ipa_part)

                    else: # 如果是非汉字串（标点、字母、数字等）
                        # 进行HTML转义，防止< >等被当作标签
                        escaped_segment = html.escape(segment)
                        ipa_segments_for_line.append(escaped_segment)
                
                output_lines_html.append("".join(ipa_segments_for_line))
            
            # 4. 用 <br> 连接各行，并设置最终的HTML
            final_html = "<p style='line-height: 1.6;'>" + "<br>".join(output_lines_html) + "</p>"
            self.output_text.setHtml(final_html)

        except Exception as e:
            import traceback
            error_info = f"发生错误: {e}\n\n详细信息:\n{traceback.format_exc()}"
            QMessageBox.critical(self, "转换失败", error_info)