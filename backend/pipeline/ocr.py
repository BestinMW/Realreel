from pathlib import Path

from PIL import Image

from .config import MIN_WORD_CONFIDENCE, OCR_ENABLED, OCR_LANGUAGE
from .indicators import derive_ocr_indicators, estimate_image_size_from_lines
from .tools import configure_tesseract, resolve_tesseract_path

configure_tesseract()

try:
    import pytesseract
except ImportError:
    pytesseract = None


def empty_ocr_result(error: str | None = None) -> dict:
    lines: list[dict] = []
    return {
        "ok": error is None,
        "text": {"raw": "", "lines": lines, "wordCount": 0},
        "indicators": derive_ocr_indicators(lines=lines, raw=""),
        "confidence": None,
        "error": error,
    }


def analyze_frame(frame_path: Path) -> dict:
    if not OCR_ENABLED:
        return empty_ocr_result("OCR disabled by ENABLE_KEYFRAME_OCR=false.")

    if pytesseract is None:
        return empty_ocr_result(
            "pytesseract is not installed. Install backend requirements and system tesseract-ocr."
        )

    if not resolve_tesseract_path():
        return empty_ocr_result(
            "Tesseract OCR binary not found. Install: winget install UB-Mannheim.TesseractOCR "
            "or set TESSERACT_CMD to tesseract.exe path."
        )

    try:
        image = Image.open(frame_path)
        data = pytesseract.image_to_data(
            image,
            lang=OCR_LANGUAGE,
            config="--psm 11",
            output_type=pytesseract.Output.DICT,
        )

        lines = _collect_lines(data)
        raw_text = _build_raw_text(lines)
        size = estimate_image_size_from_lines(lines)
        indicators = derive_ocr_indicators(
            lines=lines,
            raw=raw_text,
            width=size["width"],
            height=size["height"],
        )
        confidences = [line["confidence"] for line in lines]
        page_confidence = round(sum(confidences) / len(confidences), 2) if confidences else None

        return {
            "ok": True,
            "text": {
                "raw": raw_text,
                "lines": lines,
                "wordCount": sum(len(line["text"].split()) for line in lines),
            },
            "indicators": indicators,
            "confidence": page_confidence,
            "error": None,
        }
    except Exception as exc:
        return empty_ocr_result(str(exc))


def _collect_lines(data: dict) -> list[dict]:
    line_map: dict[tuple[int, int, int], dict] = {}

    count = len(data.get("text", []))
    for index in range(count):
        text = (data["text"][index] or "").strip()
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            confidence = -1.0

        if not text or confidence < MIN_WORD_CONFIDENCE:
            continue

        key = (
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        left = int(data["left"][index])
        top = int(data["top"][index])
        width = int(data["width"][index])
        height = int(data["height"][index])
        box = {
            "x0": left,
            "y0": top,
            "x1": left + width,
            "y1": top + height,
        }

        if key not in line_map:
            line_map[key] = {
                "text": text,
                "confidence": confidence,
                "boundingBox": box,
            }
            continue

        entry = line_map[key]
        entry["text"] = f"{entry['text']} {text}".strip()
        entry["confidence"] = round((entry["confidence"] + confidence) / 2, 2)
        entry["boundingBox"]["x1"] = max(entry["boundingBox"]["x1"], box["x1"])
        entry["boundingBox"]["y1"] = max(entry["boundingBox"]["y1"], box["y1"])

    return sorted(line_map.values(), key=lambda item: (item["boundingBox"]["y0"], item["boundingBox"]["x0"]))


def _build_raw_text(lines: list[dict]) -> str:
    return "\n".join(line["text"] for line in lines).strip()
