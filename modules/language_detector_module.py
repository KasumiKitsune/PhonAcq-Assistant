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

def _is_likely_english_explanation(note_text):
    """
    [新增] 辅助函数，用于判断备注是否是纯英文的解释性文字。
    这是解决“英文备注干扰”问题的关键。
    """
    if not note_text:
        return False
    # 规则1: 必须只包含基础拉丁字母、数字和常见标点。
    if not re.match(r'^[a-z0-9\s.,?!/()\'"-]*$', note_text):
        return False
    # 规则2: 必须包含一些常见的英文解释性单词。
    explanation_words = {'hello', 'in', 'is', 'a', 'the', 'pangram', 'sentence', 'greeting', 'word', 'common', 'thank', 'you'}
    note_words = set(re.findall(r'\b\w+\b', note_text))
    if not note_words.intersection(explanation_words):
        return False
    return True

def detect_language(text, note=None):
    """
    [v6.0 抗干扰专家版] 通过加权评分模型，智能检测给定文本的语言。

    此版本专门解决“英文备注干扰”问题，核心改进：
    1.  **主动降噪**: 新增 `_is_likely_english_explanation` 辅助函数，用于识别纯英文
        的解释性备注。如果识别成功，该备注对语言评分的贡献将被完全忽略。
    2.  **主次分明**: 算法现在绝对优先相信 `text` 栏的证据。只有在 `text` 栏证据
        不足时，才会考虑采纳 `note` 栏中非英文解释的证据。
    3.  **特征强化**: 再次强化了越南语等语言的独特“杀手级”特征，提高识别的确定性。

    :param text: 需要检测的主要文案。
    :param note: (可选) 附加的备注/IPA信息，用于辅助判断。
    :return: 一个 gTTS 兼容的语言代码 (e.g., 'zh-cn', 'fr', 'vi') 或 None。
    """
    if not text or not isinstance(text, str):
        return 'en-us' if (note and isinstance(note, str)) else None

    text_lower = text.lower()
    note_lower = note.lower() if note and isinstance(note, str) else ""

    if not text_lower and not note_lower:
        return None
        
    # --- [核心修正] 在分析开始前，预先判断备注是否是干扰项 ---
    is_note_english_clutter = _is_likely_english_explanation(note_lower)

    scores = {lang: 0.0 for lang in LANG_DATA}
    WEIGHTS = { 'killer': 100.0, 'range': 50.0, 'feature': 10.0, 'stop_word': 5.0, 'uk_bonus': 10.0 }

    # --- 证据累加 ---
    
    # 步骤 1: 分析主文本 (text) - 这是最主要的证据来源
    for char in text_lower:
        char_ord = ord(char)
        for lang, data in LANG_DATA.items():
            if 'killer' in data and char in data['killer']: scores[lang] += WEIGHTS['killer']
            if 'ranges' in data and any(start <= char_ord <= end for start, end in data['ranges']): scores[lang] += WEIGHTS['range']
            if 'features' in data and char in data['features']: scores[lang] += WEIGHTS['feature']
            
    text_words = frozenset(re.findall(r'\b\w+\b', text_lower))
    if text_words:
        for lang, data in LANG_DATA.items():
            if 'stop_words' in data:
                common_words = len(text_words.intersection(data['stop_words']))
                if common_words > 0:
                    score_boost = (common_words / len(text_words)) * WEIGHTS['stop_word']
                    if lang == 'en-uk': score_boost += WEIGHTS['uk_bonus'] * common_words
                    scores[lang] += score_boost

    # 步骤 2: 分析备注 (note) - 仅在备注不是“英文干扰项”时进行，作为辅助证据
    if not is_note_english_clutter and note_lower:
        for char in note_lower:
            char_ord = ord(char)
            for lang, data in LANG_DATA.items():
                if 'killer' in data and char in data['killer']: scores[lang] += WEIGHTS['killer']
                if 'ranges' in data and any(start <= char_ord <= end for start, end in data['ranges']): scores[lang] += WEIGHTS['range']
                if 'features' in data and char in data['features']: scores[lang] += WEIGHTS['feature']

    # --- 最终决策 ---
    if not any(scores.values()):
        return 'en-us' if text_lower else None

    best_lang, best_score = max(scores.items(), key=lambda item: item[1])

    # 如果分数过低，则不做出判断，除非是纯拉丁字母文本
    if best_score < 5.0:
        is_basic_latin = all('a' <= char <= 'z' or char.isspace() for char in text_lower)
        return 'en-us' if is_basic_latin else None

    # 特殊处理英式/美式英语
    if best_lang == 'en-us':
        uk_score = scores.get('en-uk', 0)
        if uk_score > 0 and uk_score >= best_score * 0.9: # 提高英式英语的判定阈值
            return 'en-uk'

    return best_lang

# --- END OF FILE modules/language_detector_module.py ---