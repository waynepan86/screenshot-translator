"""Translation records with explicit engine/failure state and bounded caching."""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import translator as api


def _record(text='', engine='', error='', fallback=False, cached=False, ok=True):
    return dict(text=text, engine=engine, error=error, fallback=fallback, cached=cached, ok=ok)


def _fallback(text, target, cause):
    out = api._google_translate(text, 'auto', target)
    if out:
        return _record(out.strip(), 'Google', cause, api._engine != 'auto')
    out = api.translate_mymemory(text, 'auto', target)
    if out:
        return _record(out.strip(), 'MyMemory', cause, True)
    return _record(error=cause or 'Google 与 MyMemory 均未返回可用译文', ok=False)


def _single(text, target):
    if api._engine != 'auto' and api.engine_ready(api._engine):
        api._errors.message = ''
        out = api._ENGINE_FUNCS[api._engine](text, 'auto', target)
        if out:
            return _record(out.strip(), api._engine)
        return _fallback(text, target, getattr(api._errors, 'message', '') or '首选翻译引擎失败')
    return _fallback(text, target, '首选引擎密钥未配置' if api._engine != 'auto' else '')


def _deepl(texts, target, context):
    key = api._creds['deepl']['key'].strip()
    host = 'api-free.deepl.com' if key.endswith(':fx') else 'api.deepl.com'
    payload = dict(text=texts, target_lang=api._lang('deepl', target, 'ZH'), context=context)
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    if len(body) > 128 * 1024:
        raise ValueError('单个文本块超过 DeepL 请求大小限制')
    headers = {'Content-Type': 'application/json', 'Authorization': 'DeepL-Auth-Key ' + key, 'User-Agent': api.USER_AGENT}
    for attempt in range(2):
        try:
            data = api._post(f'https://{host}/v2/translate', body, headers, 10)
            results = data['translations']
            if len(results) != len(texts) or any(not r.get('text', '').strip() for r in results):
                raise ValueError('DeepL 返回的文本块数量或内容异常')
            return [_record(r['text'].strip(), 'DeepL') for r in results]
        except api.urllib.error.HTTPError as exc:
            if attempt == 0 and (exc.code == 429 or exc.code >= 500):
                time.sleep(.4)
                continue
            raise


def translate(texts, target, progress=None, force=False, context_text=None):
    context = (context_text if context_text is not None else '\n'.join(texts))[:6000]
    results = [None] * len(texts)
    pending = {}
    done = 0
    for i, text in enumerate(texts):
        key = (api._engine, target, text.strip(), context if api._engine == 'deepl' else '')
        # Keep code/URLs and numeric-only labels intact, without an API call.
        literal = not re.search(r'[A-Za-z\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]', text) or bool(re.fullmatch(r'(?:https?://\S+|[\w.-]+[/\\][\w./\\-]+)', text.strip()))
        with api._cache_lock:
            cached = None if force else api._cache.get(key)
        if literal:
            results[i] = _record(text, '原样保留')
        elif cached:
            results[i] = dict(cached, cached=True)
        else:
            pending.setdefault(key, []).append(i)
            continue
        done += 1
    if progress:
        progress(done, len(texts))

    def finish(keys, records):
        nonlocal done
        for key, record in zip(keys, records):
            if record['ok'] and not record['fallback']:
                with api._cache_lock:
                    api._cache[key] = dict(record)
                    while len(api._cache) > 256:
                        api._cache.popitem(last=False)
            for i in pending[key]:
                results[i] = dict(record)
                done += 1
            if progress:
                progress(done, len(texts))

    keys = list(pending)
    if api._engine == 'deepl' and api.engine_ready('deepl'):
        batches, batch, size = [], [], len(context.encode('utf-8')) + 1024
        for key in keys:
            addition = len(json.dumps(key[2], ensure_ascii=False).encode('utf-8')) + 4
            if batch and (len(batch) >= 50 or size + addition > 120 * 1024):
                batches.append(batch)
                batch, size = [], len(context.encode('utf-8')) + 1024
            batch.append(key)
            size += addition
        if batch:
            batches.append(batch)
        def run_batch(batch):
            try:
                return _deepl([k[2] for k in batch], target, context)
            except Exception as exc:
                cause = 'DeepL: ' + api._describe(exc)
                with ThreadPoolExecutor(max_workers=4) as pool:
                    return list(pool.map(lambda k: _fallback(k[2], target, cause), batch))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(run_batch, b): b for b in batches}
            for future in as_completed(futures):
                finish(futures[future], future.result())
    else:
        with ThreadPoolExecutor(max_workers=3 if api._engine == 'llm' else 6) as pool:
            futures = {pool.submit(_single, k[2], target): k for k in keys}
            for future in as_completed(futures):
                try:
                    record = future.result()
                except Exception as exc:
                    record = _record(error=type(exc).__name__, ok=False)
                finish([futures[future]], [record])
    return results
