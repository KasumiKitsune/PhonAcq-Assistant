# --- START OF FILE modules/language_detector_module.py ---

import re

# --- 模块元数据 ---
MODULE_NAME = "语言检测器"
MODULE_DESCRIPTION = "提供一个独立的、可复用的语言检测算法函数，支持备注驱动的智能识别，并覆盖全面的语言列表。"

# --- 核心数据定义区 (v6.0 专家知识库) ---
# 强化了越南语的 'killer' 特征，以提高其识别优先级
LANG_DATA = {
    # === 拉丁语系 ===
    'en-us': { 'stop_words': frozenset({'the', 'a', 'is', 'to', 'in', 'it', 'of', 'and', 'for', 'on'}) },
    'en-uk': { 'stop_words': frozenset({'whilst', 'amongst', 'colour', 'flavour', 'centre', 'theatre', 'analyse'}) },
    'fr':    { 'features': frozenset('àâæçéèêëîïôœùûü'), 'stop_words': frozenset({'le', 'la', 'de', 'et', 'est'}) },
    'es':    { 'features': frozenset('áéíóúüñ'), 'killer': frozenset('¿¡'), 'stop_words': frozenset({'el', 'la', 'de', 'y', 'es'}) },
    'de':    { 'features': frozenset('äöü'), 'killer': frozenset('ß'), 'stop_words': frozenset({'der', 'die', 'das', 'und', 'ist'}) },
    'pt':    { 'features': frozenset('áàâãéêíóôõúç'), 'stop_words': frozenset({'o', 'a', 'de', 'e', 'é', 'um', 'uma'}) },
    'it':    { 'features': frozenset('àèéìòù'), 'stop_words': frozenset({'il', 'la', 'di', 'e', 'è'}) },
    'nl':    { 'features': frozenset('äëïöü'), 'stop_words': frozenset({'de', 'het', 'een', 'en', 'van'}) },
    'pl':    { 'features': frozenset('ąćęłńóśźż'), 'stop_words': frozenset({'i', 'w', 'z', 'na', 'się'}) },
    'tr':    { 'features': frozenset('çğıöşü'), 'stop_words': frozenset({'ve', 'bir', 'bu', 'da', 'de'}) },
    'id':    { 'stop_words': frozenset({'dan', 'di', 'ini', 'itu', 'yang', 'ada', 'ke'}) },
    'vi':    {
        'killer': frozenset('đơư'), # 'đ', 'ơ', 'ư' 在此列表中是越南语独有的强特征
        'features': frozenset('àáạảãăằắặẳẵâầấậẩẫèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹ'),
    },
    # === 非拉丁语系 ===
    'ru':    { 'ranges': frozenset({(0x0400, 0x04FF)}) },
    'zh-cn': { 'ranges': frozenset({(0x4E00, 0x9FFF)}) },
    'ja':    { 'ranges': frozenset({(0x3040, 0x309F), (0x30A0, 0x30FF)}) },
    'ko':    { 'ranges': frozenset({(0xAC00, 0xD7A3), (0x1100, 0x11FF)}) },
    'hi':    { 'ranges': frozenset({(0x0900, 0x097F)}) },
    'ar':    { 'ranges': frozenset({(0x0600, 0x06FF)}) },
    'th':    { 'ranges': frozenset({(0x0E00, 0x0E7F)}) },
}

def detect_language(text, note=None):
    if not text and not note:
        return None
        
    text_lower = str(text).lower().strip() if text else ""
    note_lower = str(note).lower().strip() if note and isinstance(note, str) else ""

    if not text_lower:
        return None # 如果主文本为空，直接不进行判断

    # --- 权重和数据定义保持不变 ---
    WEIGHTS = { 'killer': 100.0, 'range': 50.0, 'feature': 10.0, 'stop_word': 5.0, 'uk_bonus': 10.0 }

    # --- 核心分析流程 (只分析主文本) ---
    scores = {lang: 0.0 for lang in LANG_DATA}
    
    # 字符级分析 (killer, range, feature)
    for char in text_lower:
        char_ord = ord(char)
        for lang, data in LANG_DATA.items():
            if 'killer' in data and char in data['killer']:
                scores[lang] += WEIGHTS['killer']
            if 'ranges' in data and any(start <= char_ord <= end for start, end in data['ranges']):
                scores[lang] += WEIGHTS['range']
            if 'features' in data and char in data['features']:
                scores[lang] += WEIGHTS['feature']
    
    # 词汇级分析 (stop words)
    words = frozenset(re.findall(r'\b\w+\b', text_lower))
    if words:
        for lang, data in LANG_DATA.items():
            if 'stop_words' in data:
                common_words_count = len(words.intersection(data['stop_words']))
                if common_words_count > 0:
                    score_boost = (common_words_count / len(words)) * WEIGHTS['stop_word'] * 10
                    if lang == 'en-uk':
                        score_boost += WEIGHTS['uk_bonus'] * common_words_count
                    scores[lang] += score_boost

    # --- 决策 ---
    if not any(s > 0 for s in scores.values()):
        # 如果没有任何分数，回退到默认英文
        return 'en-us'

    best_lang, best_score = max(scores.items(), key=lambda item: item[1])

    # --- [核心修正] 特殊规则应用 ---
    # 1. 对日语的特殊处理：如果主文本最可能是日语，检查备注中是否有假名来确认
    if best_lang == 'ja' and note_lower:
        ja_ranges = LANG_DATA['ja']['ranges']
        # 如果备注中含有任何假名，则确认是日语
        if any(start <= ord(char) <= end for char in note_lower for start, end in ja_ranges):
            return 'ja'

    # 2. 对英语的特殊处理 (英式/美式)
    if best_lang == 'en-us':
        uk_score = scores.get('en-uk', 0)
        # 仅当英式英语证据非常强时才判定为英式
        if uk_score > 0 and uk_score >= best_score:
            return 'en-uk'

    # 对于所有其他情况，只返回基于主文本的最高分结果
    return best_lang
# --- END OF FILE modules/language_detector_module.py ---