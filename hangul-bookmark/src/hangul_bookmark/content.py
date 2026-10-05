from pathlib import Path
from .errors import WriterError
from .latex import convert, validate_script

def normalize(blocks):
    if not isinstance(blocks, list) or not blocks or len(blocks) > 2000:
        raise WriterError("INVALID_CONTENT", "1~2,000개의 내용 블록을 전달하세요.")
    result = []
    for b in blocks:
        if not isinstance(b, dict): raise WriterError("INVALID_CONTENT", "블록은 객체여야 합니다.")
        if b.get("uncertain"):
            raise WriterError("UNCERTAIN_CONTENT", b.get("reason") or "불확실한 기호를 사용자에게 확인하세요.")
        kind = b.get("type")
        if kind == "text":
            s = b.get("text")
            if not isinstance(s, str) or "\x00" in s: raise WriterError("INVALID_CONTENT", "올바른 본문 문자열이 필요합니다.")
            lines = s.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            for i, line in enumerate(lines):
                if i: result.append({"type": "paragraph_break"})
                if line: result.append({"type": "text", "text": line})
        elif kind == "paragraph_break": result.append({"type": kind})
        elif kind == "equation":
            fmt = b.get("format", "hwp")
            if fmt not in ("hwp", "latex"): raise WriterError("INVALID_EQUATION", "format은 hwp 또는 latex입니다.")
            display = b.get("display", "inline")
            if display not in ("inline", "block"): raise WriterError("INVALID_EQUATION", "display는 inline 또는 block입니다.")
            value = b.get("script")
            result.append({"type": kind, "script": convert(value) if fmt == "latex" else validate_script(value), "display": display})
        elif kind == "image":
            from PIL import Image
            path = Path(b.get("path", "")).expanduser().resolve()
            if not path.is_file(): raise WriterError("IMAGE_MISSING", "이미지 파일을 찾을 수 없습니다.")
            try:
                with Image.open(path) as im:
                    w, h = im.size
                    if w * h > 40_000_000: raise WriterError("INVALID_IMAGE", "이미지가 너무 큽니다.")
                    crop = b.get("crop", [0, 0, w, h])
                    if len(crop) != 4 or any(type(x) is not int for x in crop): raise ValueError()
                    l, t, r, bt = crop
                    if not (0 <= l < r <= w and 0 <= t < bt <= h): raise ValueError()
                    dpi = im.info.get("dpi", (96, 96))[0]
            except WriterError: raise
            except Exception: raise WriterError("INVALID_IMAGE", "이미지 형식 또는 crop 영역이 잘못되었습니다.") from None
            result.append({"type": kind, "path": str(path), "crop": list(crop), "dpi": max(36, min(float(dpi), 600))})
        else: raise WriterError("INVALID_CONTENT", f"지원하지 않는 블록: {kind}")
    if not result: raise WriterError("INVALID_CONTENT", "작성할 내용이 없습니다.")
    if sum(len(x.get("text", "")) + len(x.get("script", "")) for x in result) > 200000:
        raise WriterError("INVALID_CONTENT", "한 번에 작성할 내용이 너무 깁니다.")
    return result

def counts(blocks):
    return {"text_blocks": sum(b["type"] == "text" for b in blocks),
            "paragraph_breaks": sum(b["type"] == "paragraph_break" for b in blocks),
            "equations": sum(b["type"] == "equation" for b in blocks),
            "images": sum(b["type"] == "image" for b in blocks)}
