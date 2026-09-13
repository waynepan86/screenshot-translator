import asyncio
import os
import threading

_engine_lock = threading.RLock()

# ---------------- RapidOCR (primary engine) ----------------
# PaddleOCR models running on ONNX Runtime: far better accuracy than Windows
# OCR for Chinese and small text, still lightweight and fully offline.

_RAPID_ENGINE = None
_rapid_checked = False
_rapid_available = False
_rapid_flavor = None  # "new" = rapidocr (PP-OCRv6) / "legacy" = rapidocr_onnxruntime


def is_rapidocr_available():
    global _rapid_checked, _rapid_available, _rapid_flavor
    if not _rapid_checked:
        _rapid_checked = True
        try:
            import rapidocr  # noqa: F401
            _rapid_available = True
            _rapid_flavor = "new"
        except Exception:
            try:
                import rapidocr_onnxruntime  # noqa: F401
                _rapid_available = True
                _rapid_flavor = "legacy"
            except Exception:
                _rapid_available = False
    return _rapid_available


def _get_rapid_engine_unlocked():
    global _RAPID_ENGINE
    if _RAPID_ENGINE is None:
        if _rapid_flavor == "new":
            from rapidocr import RapidOCR
            _RAPID_ENGINE = RapidOCR(params={
                # Never skip detection for wide/thin crops (default treats
                # w/h > 8 images as a single text line, breaking wide selections)
                "Global.width_height_ratio": -1,
                # Default preprocessing shrinks anything above 2000px; we
                # upscale to 2400px ourselves, so raise the cap to match
                "Global.max_side_len": 2400,
                # Detection resizes down to this cap only, never up
                "Det.limit_side_len": 2400,
                "Det.limit_type": "max",
            })
        else:
            from rapidocr_onnxruntime import RapidOCR
            _RAPID_ENGINE = RapidOCR(
                width_height_ratio=-1,
                det_model_path="",
                det_limit_side_len=2400,
                det_limit_type="max",
            )
    return _RAPID_ENGINE


def _get_rapid_engine():
    with _engine_lock:
        return _get_rapid_engine_unlocked()



def warm_up():
    """Preloads the OCR engine (call in a background thread at app start so
    the first capture doesn't pay the model-loading cost)."""
    if is_rapidocr_available():
        try:
            _get_rapid_engine()
        except Exception as e:
            print(f"RapidOCR warm-up failed: {e}")


def run_ocr_rapid(image_path, scale_factor=1.0):
    with _engine_lock:
        return _run_ocr_rapid(image_path, scale_factor)


def _run_ocr_rapid(image_path, scale_factor=1.0):
    engine = _get_rapid_engine()
    if _rapid_flavor == "new":
        output = engine(image_path)
        if output is None or output.boxes is None or not len(output.txts):
            return {"text": "", "lines": []}
        result = list(zip(output.boxes.tolist(), output.txts, output.scores))
    else:
        result, _ = engine(image_path)

    ocr_result = {"text": "", "lines": []}
    if not result:
        return ocr_result

    lines = []
    for box, text, score in result:
        text = text.strip()
        if not text:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x = min(xs) / scale_factor
        y = min(ys) / scale_factor
        w = (max(xs) - min(xs)) / scale_factor
        h = (max(ys) - min(ys)) / scale_factor
        # RapidOCR returns whole detected lines; treat each as a single "word"
        lines.append({
            "text": text, "x": x, "y": y, "w": w, "h": h,
            "confidence": float(score),
            "polygon": [[px / scale_factor, py / scale_factor] for px, py in box],
            "original_text": text,
            "words": [{"text": text, "x": x, "y": y, "w": w, "h": h, "whole_fragment": True}],
        })

    lines = merge_line_fragments(lines)
    ocr_result["lines"] = lines
    ocr_result["text"] = "\n".join(l["text"] for l in lines)
    return ocr_result



def _is_cjk(ch):
    return ('\u2e80' <= ch <= '\u9fff') or ('\u3000' <= ch <= '\u303f') or ('\uff00' <= ch <= '\uffef')


def rebuild_line_text(words):
    """Rebuild a line's text from word boxes.

    Windows OCR joins every word with a space, which breaks Chinese
    ("你 好 世 界") and also splits words when it mis-segments English
    ("Home page", "a ny"). Using the geometry: adjacent boxes with a gap far
    smaller than a real space are glued back together, and CJK characters are
    always joined without spaces.
    """
    if not words:
        return ""
    parts = [words[0]["text"]]
    for prev, cur in zip(words, words[1:]):
        gap = cur["x"] - (prev["x"] + prev["w"])
        prev_ch = parts[-1][-1] if parts[-1] else ""
        cur_ch = cur["text"][0] if cur["text"] else ""
        # A real inter-word space is ~0.25x the glyph height; anything much
        # tighter is a mis-segmented word ("exa mple") and gets glued back.
        pair_h = min(prev["h"], cur["h"])
        if _is_cjk(prev_ch) or _is_cjk(cur_ch) or (gap < pair_h * 0.2 and not (prev.get('whole_fragment') or cur.get('whole_fragment'))):
            parts[-1] += cur["text"]
        else:
            parts.append(cur["text"])
    return " ".join(parts)


def merge_line_fragments(lines):
    """Merge OCR line objects that sit on the same visual text row.

    Windows OCR often splits one row into several "lines" when styled inline
    elements (code chips, links) interrupt it. Those fragments then break
    paragraph grouping and get translated out of context, so we merge lines
    whose vertical spans overlap significantly back into a single row.
    """
    if not lines:
        return []
        
    groups = []
    for line in sorted(lines, key=lambda l: l["y"]):
        target = None
        for g in groups:
            g_top = min(l["y"] for l in g)
            g_bottom = max(l["y"] + l["h"] for l in g)
            top = max(g_top, line["y"])
            bottom = min(g_bottom, line["y"] + line["h"])
            left = min(l['x'] for l in g)
            right = max(l['x'] + l['w'] for l in g)
            gap = max(left - line['x'] - line['w'], line['x'] - right, 0)
            height_ratio = max(line['h'], g_bottom - g_top) / max(1, min(line['h'], g_bottom - g_top))
            if ((bottom - top) > 0.65 * min(line["h"], g_bottom - g_top)
                    and gap <= min(line['h'], g_bottom - g_top) * .65
                    and height_ratio <= 1.6):
                target = g
                break
        if target is not None:
            target.append(line)
        else:
            groups.append([line])
            
    # A later fragment can bridge two groups created earlier. Join them
    # transitively so inline chips do not separate the left/right sentence.
    changed = True
    while changed:
        changed = False
        for i, first in enumerate(groups):
            a = dict(x=min(l['x'] for l in first),y=min(l['y'] for l in first))
            a['w'] = max(l['x']+l['w'] for l in first)-a['x']
            a['h'] = max(l['y']+l['h'] for l in first)-a['y']
            for j in range(i+1,len(groups)):
                second = groups[j]
                x = min(l['x'] for l in second); y = min(l['y'] for l in second)
                w = max(l['x']+l['w'] for l in second)-x
                h = max(l['y']+l['h'] for l in second)-y
                overlap = min(a['y']+a['h'],y+h)-max(a['y'],y)
                gap = max(a['x']-x-w,x-a['x']-a['w'],0)
                if overlap > .65*min(a['h'],h) and gap <= .65*min(a['h'],h) and max(a['h'],h)/max(1,min(a['h'],h)) <= 1.6:
                    first.extend(second); groups.pop(j); changed = True; break
            if changed:
                break
    merged = []
    for g in groups:
        words = []
        for frag in sorted(g, key=lambda l: l["x"]):
            words.extend(frag["words"])
        words.sort(key=lambda w: w["x"])
        
        min_x = min(l["x"] for l in g)
        min_y = min(l["y"] for l in g)
        max_x = max(l["x"] + l["w"] for l in g)
        max_y = max(l["y"] + l["h"] for l in g)
        merged.append({
            "text": rebuild_line_text(words),
            "original_text": rebuild_line_text(words),
            "confidence": min((l['confidence'] for l in g if l.get('confidence') is not None), default=None),
            "regions": [dict(l) for l in g],
            "x": min_x,
            "y": min_y,
            "w": max_x - min_x,
            "h": max_y - min_y,
            "words": words,
        })
    return merged


# Unified entry: RapidOCR first, Windows OCR as fallback
def run_ocr_sync(image_path, language_code=None, scale_factor=1.0, review=True, progress=None):
    if is_rapidocr_available():
        try:
            result = run_ocr_rapid(image_path, scale_factor)
            if result["lines"]:
                if review:
                    from ocr_review import review_result
                    try:
                        result = review_result(result, image_path, scale_factor, run_ocr_rapid, progress)
                    except Exception as exc:
                        result['review_error'] = str(exc)
                return result
            print("RapidOCR found no text, falling back to Windows OCR...")
        except Exception as e:
            print(f"RapidOCR failed, falling back to Windows OCR: {e}")
            
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(ocr_image_async(image_path, language_code, scale_factor))
    finally:
        loop.close()

async def ocr_image_async(image_path, language_code=None, scale_factor=1.0):
    from winrt.windows.storage import StorageFile
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.globalization import Language

    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found at {image_path}")

    # Load file and decode image
    file = await StorageFile.get_file_from_path_async(os.path.abspath(image_path))
    stream = await file.open_async(0) # Read access
    decoder = await BitmapDecoder.create_async(stream)
    software_bitmap = await decoder.get_software_bitmap_async()

    # Initialize Default OCR Engine (System profile, e.g. zh-CN)
    if language_code:
        try:
            lang = Language(language_code)
            engine = OcrEngine.try_create_from_language(lang)
        except Exception:
            engine = OcrEngine.try_create_from_user_profile_languages()
    else:
        engine = OcrEngine.try_create_from_user_profile_languages()

    if not engine:
        raise RuntimeError("Failed to initialize Windows OCR Engine.")

    result = await engine.recognize_async(software_bitmap)
    
    # Optimize: Auto-detect English screenshots and switch to en-US engine
    # (en-US engine has much higher accuracy for code, variables, and technical fonts)
    chinese_chars = 0
    total_chars = len(result.text)
    for char in result.text:
        if '\u4e00' <= char <= '\u9fff':
            chinese_chars += 1
            
    # If the text is English-heavy (less than 2% Chinese characters)
    # and the user did not explicitly override the language
    if not language_code and total_chars > 0 and (chinese_chars / total_chars) < 0.02:
        try:
            en_lang = Language("en-US")
            if OcrEngine.is_language_supported(en_lang):
                en_engine = OcrEngine.try_create_from_language(en_lang)
                if en_engine:
                    result = await en_engine.recognize_async(software_bitmap)
        except Exception as e:
            print(f"Failed to switch to en-US engine: {e}")
            
    # Process results
    ocr_result = {
        "text": result.text,
        "lines": []
    }

    for line in result.lines:
        words_list = []
        for word in line.words:
            r = word.bounding_rect
            words_list.append({
                "text": word.text,
                "x": r.x / scale_factor,
                "y": r.y / scale_factor,
                "w": r.width / scale_factor,
                "h": r.height / scale_factor
            })
        
        if not words_list:
            continue
            
        # Compute line bounding box from words
        min_x = min(w["x"] for w in words_list)
        min_y = min(w["y"] for w in words_list)
        max_x = max(w["x"] + w["w"] for w in words_list)
        max_y = max(w["y"] + w["h"] for w in words_list)
        
        ocr_result["lines"].append({
            "text": rebuild_line_text(words_list),
            "x": min_x,
            "y": min_y,
            "w": max_x - min_x,
            "h": max_y - min_y,
            "words": words_list
        })
        
    # Merge same-row fragments, then rebuild the flat text from the
    # geometry-corrected lines
    ocr_result["lines"] = merge_line_fragments(ocr_result["lines"])
    ocr_result["text"] = "\n".join(l["text"] for l in ocr_result["lines"])
        
    return ocr_result
