"""Shared source/target catalogue. UI language is independent of translation."""
LANGUAGES = [
    ("zh-CN", "简体中文", "Simplified Chinese", "zh-CN"),
    ("zh-TW", "繁体中文", "Traditional Chinese", "zh-TW"),
    ("en", "英语", "English", "en-US"),
    ("ja", "日语", "Japanese", "ja-JP"),
    ("ko", "韩语", "Korean", "ko-KR"),
    ("fr", "法语", "French", "fr-FR"),
    ("de", "德语", "German", "de-DE"),
    ("es", "西班牙语", "Spanish", "es-ES"),
    ("pt", "葡萄牙语", "Portuguese", "pt-BR"),
    ("it", "意大利语", "Italian", "it-IT"),
    ("ru", "俄语", "Russian", "ru-RU"),
]
LANGUAGE_CODES = {row[0] for row in LANGUAGES}


def label(code):
    return next((row[1] for row in LANGUAGES if row[0] == code), code)


def ocr_tag(code):
    if code in (None, "auto"):
        return None
    return next((row[3] for row in LANGUAGES if row[0] == code), code)


def valid_language(code, default="auto"):
    return code if code == "auto" or code in LANGUAGE_CODES else default
