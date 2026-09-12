"""Conservative, offline OCR review. Image evidence wins over spelling guesses."""
import re
import time
from difflib import SequenceMatcher

_spell = None


def protected(text):
    return bool(re.search(r'https?://|www\.|[/\\]|\w+\.\w+|\d|[_=<>@{}]|[a-z][A-Z]', text))


def spelling_flags(text):
    global _spell
    if protected(text):
        return []
    try:
        if _spell is None:
            from spellchecker import SpellChecker
            _spell = SpellChecker(language='en', distance=1)
        # Names and abbreviations are not spelling mistakes.
        words = [w for w in re.findall(r'\b[a-zA-Z]{4,}\b', text) if w.islower()]
        return sorted(_spell.unknown(words))
    except ImportError:
        return []


def review_result(result, image_path, scale_factor, recognize, progress=None):
    from PIL import Image, ImageEnhance, ImageOps
    import numpy as np
    lines = result['lines']
    pending = []
    for line in lines:
        line.setdefault('original_text', line['text'])
        flags = spelling_flags(line['text'])
        low = line.get('confidence') is not None and line['confidence'] < .92
        noisy = bool(re.search(r'\ufffd|[|]{2,}|\b[a-z] [a-z]{2,}\b', line['text']))
        line['review_status'] = 'uncertain' if low or flags or noisy else 'ok'
        line['review_note'] = '待核对：' + ('可能拼写异常 ' + ', '.join(flags) if flags else '识别置信度偏低或断词异常') if low or flags or noisy else ''
        if low or flags or noisy:
            pending.append(line)
    started = time.monotonic()
    # Limit additional work; unresolved blocks remain editable in the panel.
    with Image.open(image_path) as image:
        image = image.convert('RGB')
        for i, line in enumerate(pending[:6]):
            if time.monotonic() - started > 4:
                break
            if progress:
                progress(f'正在复核可疑文字 {i + 1}/{min(6, len(pending))}…')
            pad = max(4, round(line['h'] * scale_factor * .2))
            box = (max(0, int(line['x'] * scale_factor) - pad),
                   max(0, int(line['y'] * scale_factor) - pad),
                   min(image.width, int((line['x'] + line['w']) * scale_factor) + pad),
                   min(image.height, int((line['y'] + line['h']) * scale_factor) + pad))
            crop = image.crop(box)
            if crop.width < 2 or crop.height < 2:
                continue
            enlarged = crop.resize((min(crop.width * 2, 2400), max(2, round(crop.height * min(2, 2400 / crop.width)))) )
            enhanced = ImageEnhance.Contrast(ImageOps.grayscale(crop)).enhance(1.5).convert('RGB')
            candidates = []
            try:
                for variant in (enlarged, enhanced):
                    res = recognize(np.asarray(variant)[:, :, ::-1].copy())
                    parts = res['lines']
                    candidate = ' '.join(p['text'] for p in parts).strip()
                    score = min((p.get('confidence', 0) or 0 for p in parts), default=0)
                    candidates.append((candidate, score))
            except Exception:
                continue
            old = line['text']
            candidate, score = candidates[0]
            agreement = candidate == candidates[1][0] and min(score, candidates[1][1]) >= .96
            close = SequenceMatcher(None, old.casefold(), candidate.casefold()).ratio() >= .75
            if agreement and candidate != old and close and not protected(old) and not protected(candidate):
                # Dictionary never generates replacement text. Require a real
                # improvement as well as agreement between two image passes.
                if (line.get('confidence', 1) < .90 or len(spelling_flags(candidate)) < len(spelling_flags(old))):
                    line['text'] = candidate
                    line['confidence'] = min(score, candidates[1][1])
                    line['review_status'] = 'corrected'
                    line['review_note'] = '局部重识别两次一致，已修正；可恢复原始识别'
            elif agreement and candidate == old and not spelling_flags(old):
                line['review_status'] = 'ok'
                line['review_note'] = '局部复核一致'
    result['text'] = '\n'.join(l['text'] for l in lines)
    result['reviewed'] = True
    return result
