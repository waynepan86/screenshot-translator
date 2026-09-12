import urllib.request
import urllib.parse
import urllib.error
import json
import html
import re
import time
import uuid
import random
import hashlib
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from collections import OrderedDict
import threading
import copy

_cache = OrderedDict()
_cache_lock = threading.Lock()
_errors = threading.local()

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'

# Once Google times out (typically a blocked network), skip it for the rest of
# the session so later translations don't stall for the full timeout each time.
_google_unavailable = False

# Engine chosen in Settings, plus the API credentials for every engine.
# configure() fills these in; until then only the key-free engines are used.
_engine = "auto"
_creds = {}

# Last engine-level failure, surfaced by the Settings "test" button.
_last_error = ""

# (id, label) in the order they appear in the Settings dropdown.
ENGINE_LABELS = [
    ("auto", "自动（谷歌 → MyMemory，无需密钥）"),
    ("azure", "微软 Azure 翻译器"),
    ("llm", "大模型（OpenAI 兼容接口）"),
    ("baidu", "百度翻译"),
    ("youdao", "有道智云"),
    ("deepl", "DeepL"),
]

# Credential fields per engine: (id, label, placeholder, is_secret).
# The Settings dialog builds its input rows straight from this table, and
# engine_ready() uses it to check that nothing was left blank.
ENGINE_FIELDS = {
    "azure": [
        ("key", "订阅密钥", "Azure 门户 → 密钥和终结点", True),
        ("region", "区域", "global 或 eastasia", False),
    ],
    "llm": [
        ("base_url", "接口地址", "https://api.deepseek.com/v1", False),
        ("key", "API Key", "sk-...", True),
        ("model", "模型名", "deepseek-chat", False),
    ],
    "baidu": [
        ("appid", "APP ID", "百度翻译开放平台", False),
        ("secret", "密钥", "", True),
    ],
    "youdao": [
        ("appid", "应用 ID", "有道智云控制台", False),
        ("secret", "应用密钥", "", True),
    ],
    "deepl": [
        ("key", "Auth Key", "免费版密钥以 :fx 结尾", True),
    ],
}

# Our internal codes ("zh-CN"/"en") mapped to what each provider expects.
_LANG_MAPS = {
    "azure": {"zh-CN": "zh-Hans", "en": "en", "ja": "ja", "ko": "ko"},
    "baidu": {"zh-CN": "zh", "en": "en", "ja": "jp", "ko": "kor"},
    "youdao": {"zh-CN": "zh-CHS", "en": "en", "ja": "ja", "ko": "ko"},
    "deepl": {"zh-CN": "ZH", "en": "EN-US", "ja": "JA", "ko": "KO"},
    "llm": {"zh-CN": "Simplified Chinese", "en": "English", "ja": "Japanese", "ko": "Korean"},
}


def configure(engine, api_creds):
    """Selects the active engine. `api_creds` maps engine ids to credential
    dicts shaped like ENGINE_FIELDS. Call this at startup and whenever the
    user saves the Settings dialog."""
    global _engine, _creds
    known = [e for e, _ in ENGINE_LABELS]
    _engine = engine if engine in known else "auto"
    _creds = copy.deepcopy(api_creds or {})
    with _cache_lock:
        _cache.clear()


def active_engine():
    return _engine


def last_error():
    return _last_error


def engine_ready(engine):
    """True when every credential field of `engine` has been filled in."""
    if engine == "auto":
        return True
    fields = ENGINE_FIELDS.get(engine)
    if not fields:
        return False
    cred = _creds.get(engine) or {}
    return all((cred.get(f[0]) or "").strip() for f in fields)


def _lang(engine, code, default=None):
    table = _LANG_MAPS.get(engine, {})
    if code in table:
        return table[code]
    return code if default is None else default


def _describe(exc):
    """One-line error text that keeps the provider's own message, which is
    what actually tells you whether a key is wrong or a quota is spent."""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8", "replace").strip()[:200]
        except Exception:
            body = ""
        return f"HTTP {exc.code} {body}".strip()
    return f"{type(exc).__name__}: {exc}"


def _fail(tag, exc):
    global _last_error
    _last_error = f"{tag} 调用失败 - {_describe(exc)}"
    _errors.message = _last_error
    print(_last_error)
    return None


def _reject(tag, message):
    global _last_error
    _last_error = f"{tag} 拒绝请求 - {message}"
    _errors.message = _last_error
    print(_last_error)
    return None


def _post(url, body, headers, timeout):
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _form_headers():
    return {
        'User-Agent': USER_AGENT,
        'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
    }


def detect_lang(text):
    """Best-effort script-based language detection.

    MyMemory requires an explicit source language ("auto" is not supported),
    so we guess from the character scripts present in the text.
    """
    if re.search(r'[\u3040-\u30ff]', text):
        return "ja"
    if re.search(r'[\uac00-\ud7af]', text):
        return "ko"
    if re.search(r'[\u4e00-\u9fff]', text):
        return "zh-CN"
    return "en"


def auto_target_lang(text):
    """Pick the translation direction: mostly-Chinese text goes to English,
    everything else (English/Japanese/Korean/...) goes to Chinese."""
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    total = len(re.sub(r'\s', '', text))
    if total and cjk / total > 0.4:
        return "en"
    return "zh-CN"


def _azure_translate(text, from_lang, to_lang, timeout=8.0):
    """Microsoft Azure Translator (2M chars/month free, reachable from China)."""
    cred = _creds.get("azure") or {}
    key = (cred.get("key") or "").strip()
    if not key:
        return None
    region = (cred.get("region") or "global").strip()

    params = {"api-version": "3.0", "to": _lang("azure", to_lang, "zh-Hans")}
    if from_lang and from_lang != "auto":
        params["from"] = _lang("azure", from_lang)
    url = "https://api.cognitive.microsofttranslator.com/translate?" + urllib.parse.urlencode(params)

    headers = {
        'User-Agent': USER_AGENT,
        'Content-Type': 'application/json; charset=utf-8',
        'Ocp-Apim-Subscription-Key': key,
    }
    if region and region.lower() != "global":
        headers['Ocp-Apim-Subscription-Region'] = region

    body = json.dumps([{"Text": text}], ensure_ascii=False).encode("utf-8")
    try:
        data = _post(url, body, headers, timeout)
        return data[0]["translations"][0]["text"]
    except Exception as e:
        return _fail("Azure", e)


def _baidu_translate(text, from_lang, to_lang, timeout=8.0):
    """Baidu Translate open platform. Signed with md5(appid+q+salt+secret)."""
    cred = _creds.get("baidu") or {}
    appid = (cred.get("appid") or "").strip()
    secret = (cred.get("secret") or "").strip()
    if not (appid and secret):
        return None

    salt = str(random.randint(10000, 99999999))
    sign = hashlib.md5((appid + text + salt + secret).encode("utf-8")).hexdigest()
    body = urllib.parse.urlencode({
        "q": text,
        "from": "auto" if (not from_lang or from_lang == "auto") else _lang("baidu", from_lang),
        "to": _lang("baidu", to_lang, "zh"),
        "appid": appid,
        "salt": salt,
        "sign": sign,
    }).encode("utf-8")

    url = "https://fanyi-api.baidu.com/api/trans/vip/translate"
    try:
        data = _post(url, body, _form_headers(), timeout)
    except Exception as e:
        return _fail("百度翻译", e)

    if data.get("error_code"):
        return _reject("百度翻译", f"{data.get('error_code')} {data.get('error_msg', '')}")
    # Baidu splits the input on newlines and returns one segment per line.
    segments = [seg.get("dst", "") for seg in data.get("trans_result") or []]
    return "\n".join(segments) if segments else None


def _youdao_sign_body(text):
    """Youdao signs a truncated form of the query: the first 10 chars, the
    total length, then the last 10 chars (the whole string when short)."""
    if len(text) <= 20:
        return text
    return text[:10] + str(len(text)) + text[-10:]


def _youdao_translate(text, from_lang, to_lang, timeout=8.0):
    """Youdao Zhiyun API. Signed with sha256(appid+truncate(q)+salt+curtime+secret)."""
    cred = _creds.get("youdao") or {}
    appid = (cred.get("appid") or "").strip()
    secret = (cred.get("secret") or "").strip()
    if not (appid and secret):
        return None

    salt = str(uuid.uuid4())
    curtime = str(int(time.time()))
    raw = appid + _youdao_sign_body(text) + salt + curtime + secret
    sign = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    body = urllib.parse.urlencode({
        "q": text,
        "from": "auto" if (not from_lang or from_lang == "auto") else _lang("youdao", from_lang),
        "to": _lang("youdao", to_lang, "zh-CHS"),
        "appKey": appid,
        "salt": salt,
        "sign": sign,
        "signType": "v3",
        "curtime": curtime,
    }).encode("utf-8")

    try:
        data = _post("https://openapi.youdao.com/api", body, _form_headers(), timeout)
    except Exception as e:
        return _fail("有道智云", e)

    if str(data.get("errorCode", "0")) != "0":
        return _reject("有道智云", f"errorCode {data.get('errorCode')}")
    segments = data.get("translation") or []
    return "\n".join(segments) if segments else None


def _deepl_translate(text, from_lang, to_lang, timeout=10.0):
    """DeepL API. Free keys end with ":fx" and use a different host."""
    cred = _creds.get("deepl") or {}
    key = (cred.get("key") or "").strip()
    if not key:
        return None

    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    payload = {"text": [text], "target_lang": _lang("deepl", to_lang, "ZH")}
    if from_lang and from_lang != "auto":
        # DeepL source languages carry no region suffix.
        payload["source_lang"] = from_lang.split("-")[0].upper()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        'User-Agent': USER_AGENT,
        'Content-Type': 'application/json; charset=utf-8',
        'Authorization': 'DeepL-Auth-Key ' + key,
    }

    try:
        data = _post(f"https://{host}/v2/translate", body, headers, timeout)
        return data["translations"][0]["text"]
    except Exception as e:
        return _fail("DeepL", e)


_LLM_PROMPT = (
    "You are a translation engine. Translate the user's text into {lang}. "
    "Reply with the translation only: no quotes, no code fences, no "
    "explanations, no pronunciation guides. Preserve the original line "
    "breaks. If the text is already in {lang}, repeat it unchanged."
)


def _strip_llm_wrapper(out):
    """Even with an explicit prompt some models wrap the answer in a code
    fence or quotation marks; strip those so the overlay renders clean text."""
    out = out.strip()
    if out.startswith("```"):
        out = re.sub(r'^```[a-zA-Z]*\n?', '', out)
        out = re.sub(r'\n?```$', '', out).strip()
    if len(out) >= 2 and out[0] in '"\u201c\u2018\'' and out[-1] in '"\u201d\u2019\'':
        out = out[1:-1].strip()
    return out


def _llm_translate(text, from_lang, to_lang, timeout=30.0):
    """Any OpenAI-compatible chat endpoint (DeepSeek, Qwen, Zhipu, ...).
    Slower than a dedicated MT API but noticeably better on prose."""
    cred = _creds.get("llm") or {}
    key = (cred.get("key") or "").strip()
    base = (cred.get("base_url") or "").strip().rstrip("/")
    model = (cred.get("model") or "").strip()
    if not (key and base and model):
        return None

    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    lang = _lang("llm", to_lang, "Simplified Chinese")
    body = json.dumps({
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _LLM_PROMPT.format(lang=lang)},
            {"role": "user", "content": text},
        ],
    }, ensure_ascii=False).encode("utf-8")
    headers = {
        'User-Agent': USER_AGENT,
        'Content-Type': 'application/json; charset=utf-8',
        'Authorization': 'Bearer ' + key,
    }

    try:
        data = _post(url, body, headers, timeout)
        out = data["choices"][0]["message"]["content"]
    except Exception as e:
        return _fail("大模型接口", e)
    return _strip_llm_wrapper(out or "") or None


_ENGINE_FUNCS = {
    "azure": _azure_translate,
    "llm": _llm_translate,
    "baidu": _baidu_translate,
    "youdao": _youdao_translate,
    "deepl": _deepl_translate,
}


def _google_translate(text, from_lang, to_lang, timeout=3.0):
    """Google web translate endpoint via POST (no URL length limit).
    Returns the translated string, or None on failure."""
    global _google_unavailable
    if _google_unavailable:
        return None

    url = "https://translate.googleapis.com/translate_a/single"
    body = urllib.parse.urlencode({
        "client": "gtx",
        "sl": from_lang,
        "tl": to_lang,
        "dt": "t",
        "q": text,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=body, headers={
            'User-Agent': USER_AGENT,
            'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
        })
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data and data[0]:
                return "".join(part[0] for part in data[0] if part[0])
    except Exception as e:
        print(f"Google translation failed: {e}")
        # Network-level failures usually mean Google is unreachable; don't retry
        # this session. Parse errors and HTTP errors are left retryable.
        if isinstance(e, (urllib.error.URLError, TimeoutError, OSError)):
            _google_unavailable = True
    return None


_SENTENCE_SPLIT = re.compile(r'(?<=[。！？；.!?;])\s*')


def _split_chunks(text, limit=450):
    """Split text into chunks below MyMemory's ~500 characters per-request cap,
    preferring sentence boundaries."""
    if len(text) <= limit:
        return [text]

    chunks = []
    current = ""
    for piece in _SENTENCE_SPLIT.split(text):
        if not piece:
            continue
        if len(current) + len(piece) <= limit:
            current += piece
        else:
            if current:
                chunks.append(current)
            while len(piece) > limit:
                chunks.append(piece[:limit])
                piece = piece[limit:]
            current = piece
    if current:
        chunks.append(current)
    return chunks


def translate_mymemory(text, from_lang="auto", to_lang="zh-CN"):
    """Fallback engine using the MyMemory API (reachable from mainland China).
    Returns the translated string, or None on failure."""
    if not text.strip():
        return ""

    if not from_lang or from_lang == "auto":
        from_lang = detect_lang(text)
    if from_lang == to_lang:
        return text

    langpair = f"{from_lang}|{to_lang}"
    results = []
    for chunk in _split_chunks(text):
        # The "de" (contact email) parameter raises MyMemory's anonymous
        # rate limit from 5000 to 50000 chars/day per the API docs.
        url = "https://api.mymemory.translated.net/get?q={}&langpair={}&de={}".format(
            urllib.parse.quote(chunk), urllib.parse.quote(langpair),
            urllib.parse.quote("screenshot.tool.user@gmail.com")
        )
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=6) as response:
                data = json.loads(response.read().decode('utf-8'))
                translated = (data or {}).get("responseData") or {}
                translated = translated.get("translatedText")
                status = (data or {}).get("responseStatus", 200)
                if not translated or str(status) != "200":
                    print(f"MyMemory rejected request: status={status}")
                    return None
                results.append(html.unescape(translated).strip())
        except Exception as e:
            print(f"MyMemory translation error: {e}")
            return None

    joiner = "" if to_lang.startswith("zh") else " "
    return joiner.join(results)


def translate_single(text, from_lang="auto", to_lang=None):
    """Translates a single string.

    The engine picked in Settings goes first; the key-free Google/MyMemory
    chain stays behind it as a fallback, so a mistyped key or an exhausted
    quota degrades quality instead of breaking translation outright.
    Returns the original text if every engine fails.
    """
    if not text.strip():
        return ""
    if to_lang is None:
        to_lang = auto_target_lang(text)

    if _engine != "auto" and engine_ready(_engine):
        result = _ENGINE_FUNCS[_engine](text, from_lang, to_lang)
        if result and result.strip():
            return result.strip()

    result = _google_translate(text, from_lang, to_lang)
    if result:
        return result.strip()

    result = translate_mymemory(text, from_lang, to_lang)
    if result:
        return result

    return text


def test_engine(engine):
    """Validates credentials by translating a probe string.
    Returns (ok, message) for the Settings dialog to display."""
    global _last_error
    _last_error = ""

    if engine == "auto":
        out = _google_translate("Hello, world.", "en", "zh-CN")
        source = "谷歌"
        if not out:
            out = translate_mymemory("Hello, world.", "en", "zh-CN")
            source = "MyMemory"
        if out:
            return True, f"{source}可用，返回：{out.strip()}"
        return False, "谷歌与 MyMemory 均不可用，请检查网络连接。"

    if not engine_ready(engine):
        return False, "请先把上面的密钥信息填写完整。"

    func = _ENGINE_FUNCS.get(engine)
    if func is None:
        return False, "未知的翻译引擎。"

    out = func("Hello, world.", "en", "zh-CN")
    if out and out.strip():
        return True, f"调用成功，返回：{out.strip()}"
    return False, _last_error or "调用失败，请检查密钥、网络与账户额度。"


def translate_batch(texts, from_lang="auto", to_lang=None):
    """Translates a list of paragraph strings.

    Each paragraph is translated independently and concurrently. Joining
    paragraphs with newlines into one request lets the engine flow sentences
    across paragraph boundaries (content bleeding between lines), and a serial
    fallback is slow — parallel independent requests fix both.
    """
    if not texts:
        return []

    texts_clean = [t.strip() for t in texts]
    active_indices = [i for i, t in enumerate(texts_clean) if t]
    if not active_indices:
        return texts_clean

    if to_lang is None:
        to_lang = auto_target_lang("\n".join(texts_clean[i] for i in active_indices))

    # LLM endpoints are far more rate-limit sensitive than dedicated MT APIs.
    cap = 3 if _engine == "llm" else 8
    results = list(texts_clean)
    with ThreadPoolExecutor(max_workers=min(cap, len(active_indices))) as pool:
        futures = {
            pool.submit(translate_single, texts_clean[i], from_lang, to_lang): i
            for i in active_indices
        }
        for future, idx in futures.items():
            try:
                results[idx] = future.result()
            except Exception as e:
                print(f"Paragraph translation failed: {e}")
    return results
