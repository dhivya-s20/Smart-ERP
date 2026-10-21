"""
ocr_service.py - SMART ERP Complete Multi-Certificate OCR Engine
Text extraction (PDF / image) + 17 Certificate Parsers + Validation + Batch Isolation.
All 17 supported document types:
  1.  state_board_10th          (Tamil Nadu State Board 10th Marksheet)
  2.  state_board_12th          (Tamil Nadu State Board 12th Marksheet)
  3.  state_board_10th_tc       (Tamil Nadu State Board 10th Transfer Certificate)
  4.  state_board_12th_tc       (Tamil Nadu State Board 12th Transfer Certificate)
  5.  cbse_10th_marksheet       (CBSE Class 10 Marksheet / Passing Certificate)
  6.  cbse_12th_marksheet       (CBSE Class 12 Marksheet / Passing Certificate)
  7.  cbse_10th_tc              (CBSE Class 10 Transfer Certificate)
  8.  cbse_12th_tc              (CBSE Class 12 Transfer Certificate)
  9.  birth_certificate         (Birth Certificate)
  10. income_certificate        (Income Certificate)
  11. community_certificate     (Community Certificate)
  12. nativity_certificate      (Nativity Certificate)
  13. aadhaar_card              (Aadhaar Card)
  14. diploma_certificate       (Diploma Certificate)
  15. diploma_semester_marksheet (Diploma Marksheet)
  16. degree_certificate        (Degree Certificate)
  17. degree_marksheet          (Degree Marksheet)
"""

import copy
import hashlib
import io
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import cv2
import numpy as np
import pymupdf as fitz
import pytesseract
from dotenv import load_dotenv
from PIL import Image, ImageOps

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_TESSDATA = BASE_DIR / "tessdata"
if LOCAL_TESSDATA.exists():
    os.environ["TESSDATA_PREFIX"] = str(LOCAL_TESSDATA)

TESS_LANG = (os.getenv("OCR_LANGUAGES") or os.getenv("TESS_LANG") or "eng+tam").replace(",", "+").replace(" ", "")
MIN_PDF_TEXT_CHARS = 80
PDF_DPI = 300

# Windows Tesseract path
_DEFAULT_TESS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_tess_cmd = (os.getenv("TESSERACT_CMD") or "").strip().strip('"')
if not _tess_cmd and os.path.exists(_DEFAULT_TESS):
    _tess_cmd = _DEFAULT_TESS
if _tess_cmd:
    pytesseract.pytesseract.tesseract_cmd = _tess_cmd

TEXT, DATE, INT, NUM = "text", "date", "int", "num"
MAX_PIXELS = 60_000_000
LOW_WORD_CONF = 60.0
DETECT_MIN_SCORE = 3.5
DETECT_MIN_MARGIN = 1.2


# ============================================================================
# 1. Image Preprocessing & OCR Layer
# ============================================================================

def _clean(text: str) -> str:
    """Normalize whitespace and linebreaks."""
    text = (text or "").replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_tamil(text: str) -> str:
    """Remove Tamil Unicode script chars (U+0B80 to U+0BFF and ZWNJ/ZWJ) for clean English field processing."""
    return re.sub(r"[\u0B80-\u0BFF\u200c\u200d]+", " ", text or "")


def _osd_rotate(img: Image.Image) -> Tuple[Image.Image, int]:
    """Detect page rotation using Tesseract OSD and correct it."""
    try:
        osd = pytesseract.image_to_osd(img, config="--psm 0 -c min_characters_to_try=20", output_type=pytesseract.Output.DICT)
        rot, conf = int(osd.get("rotate", 0)), float(osd.get("orientation_conf", 0))
        if rot in (90, 180, 270) and conf >= 1.5:
            return img.rotate(-rot, expand=True, fillcolor="white"), rot
    except Exception:
        pass
    return img, 0


def _deskew(img: Image.Image, max_angle: float = 5.0) -> Tuple[Image.Image, float]:
    """Projection profile variance deskewing for skewed certificate scans."""
    try:
        rgb = np.array(img.convert("RGB"))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape
        scale = 0.5 if w > 1600 else 1.0
        small = cv2.resize(gray, None, fx=scale, fy=scale) if scale != 1.0 else gray
        bw = cv2.threshold(cv2.GaussianBlur(small, (5, 5), 0), 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        sh, sw = bw.shape

        def score(a):
            m = cv2.getRotationMatrix2D((sw / 2, sh / 2), a, 1.0)
            r = cv2.warpAffine(bw, m, (sw, sh), flags=cv2.INTER_NEAREST)
            return float(np.var(r.sum(axis=1)))

        angles = np.arange(-max_angle, max_angle + 0.01, 0.5)
        coarse = max(angles, key=score)
        fine_angles = np.arange(coarse - 0.4, coarse + 0.41, 0.1)
        best = max(fine_angles, key=score)

        if abs(best) < 0.25:
            return img, 0.0

        M = cv2.getRotationMatrix2D((w / 2, h / 2), best, 1.0)
        out = cv2.warpAffine(rgb, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
        return Image.fromarray(out), round(float(best), 2)
    except Exception:
        return img, 0.0


def _variants(img: Image.Image) -> Dict[str, np.ndarray]:
    """
    Multiple contrast and binarization variants:
      plain: normalized grayscale
      otsu: Gaussian blur + Otsu threshold
      adaptive: adaptive gaussian threshold (handles shadows and uneven lighting)
      ink: minimum of RGB channels (intensifies colored stamps and red certificate serial numbers)
      clahe: Contrast Limited Adaptive Histogram Equalization (recovers faint dot-matrix marks)
    """
    img = ImageOps.exif_transpose(img).convert("RGB")
    rgb = np.array(img)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    ink = np.ascontiguousarray(np.min(rgb, axis=2))

    h, w = gray.shape
    if w < 1800:
        scale = 1800 / w
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        ink = cv2.resize(ink, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_CUBIC)

    plain = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    ink = cv2.normalize(ink, None, 0, 255, cv2.NORM_MINMAX)

    # CLAHE
    clahe_obj = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    clahe = clahe_obj.apply(plain)

    # Otsu
    _, otsu = cv2.threshold(cv2.GaussianBlur(plain, (3, 3), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Adaptive
    adaptive = cv2.adaptiveThreshold(plain, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)

    pad = lambda a: cv2.copyMakeBorder(a, 35, 35, 35, 35, cv2.BORDER_CONSTANT, value=255)
    return {
        "plain": pad(plain),
        "otsu": pad(otsu),
        "adaptive": pad(adaptive),
        "ink": pad(ink),
        "clahe": pad(clahe)
    }


def ocr_words(img: Image.Image, lang: Optional[str] = None) -> List[Dict[str, Any]]:
    """Word bounding boxes with Tesseract confidence scores: [{text, conf, x, y, w, h}]."""
    try:
        d = pytesseract.image_to_data(
            img,
            lang=lang or TESS_LANG,
            config="--oem 3 --psm 6",
            output_type=pytesseract.Output.DICT
        )
        words = []
        for i, t in enumerate(d["text"]):
            t = t.strip()
            try:
                c = float(d["conf"][i])
            except (TypeError, ValueError):
                continue
            if t and c >= 0:
                words.append({
                    "text": t,
                    "conf": c,
                    "x": int(d["left"][i]),
                    "y": int(d["top"][i]),
                    "w": int(d["width"][i]),
                    "h": int(d["height"][i])
                })
        return words
    except Exception:
        return []


def _serial_crop_ocr(variants: Dict[str, np.ndarray]) -> Optional[str]:
    """Specialized high-resolution crop OCR for red/colored certificate serial numbers (HSS / SEC)."""
    anchor_arr = variants.get("ink", variants.get("plain"))
    if anchor_arr is None:
        return None
    h, w = anchor_arr.shape
    top = anchor_arr[: int(h * 0.35), :]
    try:
        d = pytesseract.image_to_data(
            Image.fromarray(top),
            lang="eng",
            config="--oem 3 --psm 6",
            output_type=pytesseract.Output.DICT
        )
    except Exception:
        return None

    anchor_x, anchor_y, anchor_h = None, None, None
    for i, t in enumerate(d["text"]):
        t = t.strip().upper()
        if re.match(r"^(?:H[S5]{2}|SEC|SL\.?NO|CERTIFICATE)", t):
            anchor_x = d["left"][i] - 15
            anchor_y = d["top"][i]
            anchor_h = d["height"][i]
            break

    if anchor_x is None:
        return None

    pad = int(anchor_h * 1.0) + 15
    y0, y1 = max(0, anchor_y - pad), min(h, anchor_y + anchor_h + pad + 10)
    x0, x1 = max(0, anchor_x), min(w, anchor_x + int(w * 0.40))
    if y1 <= y0 or x1 <= x0:
        return None

    candidates = {}
    for arr in (variants["ink"], variants["plain"], variants["clahe"]):
        strip = arr[y0:y1, x0:x1]
        if strip.size == 0:
            continue
        for scale in (2, 3):
            s = cv2.resize(strip, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            for psm in (7, 8):
                try:
                    raw = pytesseract.image_to_string(
                        Image.fromarray(s),
                        lang="eng",
                        config=f"--oem 3 --psm {psm} -c tessedit_char_whitelist=HSEC0123456789"
                    )
                    cleaned = re.sub(r"[^A-Z0-9]", "", raw.upper())
                    m12 = re.search(r"H[S5]{2}(\d{7,8})", cleaned)
                    if m12:
                        val = f"HSS {m12.group(1)}"
                        candidates[val] = candidates.get(val, 0) + 1
                    m10 = re.search(r"SEC(\d{8})", cleaned)
                    if m10:
                        val = f"SEC {m10.group(1)}"
                        candidates[val] = candidates.get(val, 0) + 1
                except Exception:
                    continue

    if candidates:
        best = max(candidates.items(), key=lambda kv: kv[1])[0]
        return best
    return None


def _ocr_image(img: Image.Image) -> str:
    """Multi-pass OCR with score-based variant selection."""
    variants = _variants(img)
    best_score = -1
    best_text = ""
    best_variant = "plain"

    for name in ("plain", "otsu", "clahe", "adaptive"):
        arr = variants[name]
        for psm in (6, 3):
            cfg = f"--oem 3 --psm {psm}"
            try:
                data = pytesseract.image_to_data(
                    Image.fromarray(arr), lang=TESS_LANG, config=cfg, output_type=pytesseract.Output.DICT
                )
                score = sum(len(w) for w, c in zip(data["text"], data["conf"]) if w.strip() and float(c) >= 55)
                if score > best_score:
                    best_score = score
                    best_variant = name
                    best_text = pytesseract.image_to_string(Image.fromarray(arr), lang=TESS_LANG, config=cfg)
            except Exception:
                continue

    if not best_text:
        best_text = pytesseract.image_to_string(Image.fromarray(variants["plain"]), lang=TESS_LANG, config="--oem 3 --psm 6")

    # If TN certificate serial number wasn't read cleanly, attempt targeted crop OCR
    if re.search(r"GOVERNMENT\s+EXAMINATIONS|STATE\s+BOARD\s+OF\s+SCHOOL|SECONDARY\s+SCHOOL\s+LEAVING|SECOND\s+YEAR\s+MARK", best_text, re.I):
        if not re.search(r"\b(?:HSS\s*\d{7,8}|SEC\s*\d{8})\b", best_text):
            serial = _serial_crop_ocr(variants)
            if serial:
                best_text += f"\nSERIAL_HINT: {serial}"

    return best_text


def extract_text(content: bytes, filename: str) -> str:
    """PDF -> extract embedded text if >= 80 chars; fallback to rendering pages and OCR. Image -> OCR."""
    if not content:
        return ""
    if filename.lower().endswith(".pdf"):
        doc = fitz.open(stream=content, filetype="pdf")
        try:
            parts = []
            for page in doc:
                t = page.get_text("text")
                if len(t.strip()) >= MIN_PDF_TEXT_CHARS:
                    parts.append(t)
                else:
                    zoom = PDF_DPI / 72
                    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    img, _ = _osd_rotate(img)
                    img, _ = _deskew(img)
                    parts.append(_ocr_image(img))
            return _clean("\n".join(parts))
        finally:
            doc.close()

    try:
        img = Image.open(io.BytesIO(content))
        img, _ = _osd_rotate(img)
        img, _ = _deskew(img)
        return _clean(_ocr_image(img))
    except Exception as e:
        raise ValueError(f"Failed to process image: {e}")


def mask_sensitive(text: str) -> str:
    """Mask 12-digit Aadhaar and 16-digit VID while keeping EMIS IDs intact."""
    out = []
    for line in (text or "").split("\n"):
        if re.search(r"\bEMIS\b", line, re.I):
            out.append(line)
            continue
        line = re.sub(r"VID\s*:?\s*(?:\d{4}[ \t]?){4}", "VID: XXXX XXXX XXXX XXXX", line, flags=re.I)
        line = re.sub(r"(?<!\d)\d{4}[ \t]?\d{4}[ \t]?\d{4}[ \t]?\d{4}(?!\d)", "XXXX XXXX XXXX XXXX", line)
        line = re.sub(r"(?<!\d)\d{4}[ \t]?\d{4}[ \t]?(\d{4})(?![ \t]?\d)", r"XXXX XXXX \1", line)
        out.append(line)
    return "\n".join(out)


# ============================================================================
# 2. Generalized Helpers & Zero-Hardcoding Name Cleaners
# ============================================================================

_DATE_FORMATS = [
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d",
    "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y",
    "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
]
_DATE_RX = re.compile(
    r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}"
)


def to_date(s: Optional[str]) -> Optional[str]:
    """Parse Indian or ISO date string into standard YYYY-MM-DD."""
    if not s:
        return None
    m = _DATE_RX.search(str(s))
    if not m:
        return None
    cand = re.sub(r"\s+", " ", m.group(0).replace(",", "")).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cand, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def to_num(s: Optional[str]) -> Optional[float]:
    """Extract first numeric value."""
    if not s:
        return None
    m = re.search(r"\d[\d,]*\.?\d*", str(s))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def to_year(s: Optional[str]) -> Optional[int]:
    """Extract 4-digit year (1950 - 2099)."""
    if not s:
        return None
    m = re.search(r"\b(?:19|20)\d{2}\b", str(s))
    return int(m.group(0)) if m else None


def clean_name(s: Optional[str]) -> Optional[str]:
    """
    Generalized student/parent name extraction with ZERO hardcoding:
      - Strips OCR artifacts, symbols, noise words
      - Separates fused initials dynamically (e.g. 'DEEPIKAV S' -> 'DEEPIKA V S', 'KOKILAS' -> 'KOKILA S')
      - Formats properly in uppercase
    """
    if not s:
        return None
    s = _strip_tamil(s)
    # Remove unwanted punctuation and symbols
    s = re.sub(r"[\$§#_!*~|?\"';:<>=+\\/\[\]{}()]+", " ", s)
    tokens = s.strip().split()
    cleaned_tokens = []
    stopwords = {
        "NAME", "CANDIDATE", "STUDENT", "PUPIL", "FATHER", "MOTHER", "GUARDIAN", "CHILD",
        "PERSON", "OF", "THE", "DATE", "BIRTH", "SEX", "GENDER", "ROLL", "REG", "REGISTER",
        "NO", "NUMBER", "CERTIFICATE", "STANDARD", "SCHOOL", "COLLEGE", "COMMUNITY", "CASTE"
    }

    for tok in tokens:
        t = re.sub(r"[^A-Za-z.]", "", tok).upper().strip(".")
        if not t or t in stopwords:
            continue
        # Split fused single-letter consonant initial at end of name token if length >= 3
        # e.g., 'DEEPIKAV' (ends in V without vowel preceding) -> 'DEEPIKA', 'V'
        # e.g., 'KOKILAS' -> 'KOKILA', 'S'
        m_split = re.match(r"^([A-Z]{3,}[AEIOU][A-Z]*?)([BCDFGHJKLMNPQRSTVWXYZ])$", t)
        if m_split and len(m_split.group(1)) >= 3:
            cleaned_tokens.append(m_split.group(1))
            cleaned_tokens.append(m_split.group(2))
        else:
            cleaned_tokens.append(t)

    if not cleaned_tokens or len(cleaned_tokens) > 6:
        return None
    res = " ".join(cleaned_tokens)
    return res if len(res) >= 2 else None


def normalize_name(s: Optional[str]) -> str:
    """Letters only, uppercase for person comparison."""
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def names_match(a: Optional[str], b: Optional[str]) -> bool:
    """True when two names match ignoring spacing, dots, and initials ordering."""
    na, nb = normalize_name(a), normalize_name(b)
    return bool(na) and na == nb


_LABEL_WORDS = re.compile(
    r"\b(Name|Father|Mother|Guardian|Date|Birth|Sex|Gender|Religion|Nationality|Community|Caste|Address|"
    r"Class|Standard|School|Roll|Register|Number|Certificate|Admission|Leaving|Conduct|EMIS|Issue|Place|"
    r"Occupation|Income|Course|Department|Degree|Scholarship|Medical|Identification)\b",
    re.I
)
_KEY_COLON = re.compile(r"^([A-Za-z .'/()&]{2,40}?)\s*:")


def looks_like_label(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    if s.endswith(":"):
        return True
    m = _KEY_COLON.match(s)
    return bool(m and len(m.group(1).split()) <= 4 and _LABEL_WORDS.search(m.group(1)))


def safe_find_field(text: str, labels: List[str]) -> Optional[str]:
    """Extract text after first matching label; if next line is used, ensure it is not a label."""
    lines = text.split("\n")
    for lab in labels:
        rx = re.compile(rf"(?:{lab})[ \t]*[:\-–—.]*[ \t]*(.*)", re.I)
        for i, line in enumerate(lines):
            m = rx.search(line)
            if not m:
                continue
            val = m.group(1).strip(" :-–—.\t")
            if not val and i + 1 < len(lines) and not looks_like_label(lines[i + 1]):
                val = lines[i + 1].strip(" :-–—.\t")
            if val:
                return val
    return None

find_field = safe_find_field


def block_after(text: str, label_rx: str, max_lines: int = 1) -> List[str]:
    """Collect lines starting after a label until next field label."""
    lines = text.split("\n")
    rx = re.compile(rf"(?:{label_rx})[ \t]*[:\-–—.]*[ \t]*(.*)", re.I)
    for i, line in enumerate(lines):
        m = rx.search(line)
        if not m:
            continue
        out = [m.group(1).strip()] if m.group(1).strip() else []
        for nxt in lines[i + 1: i + 1 + max_lines]:
            if looks_like_label(nxt):
                break
            if nxt.strip():
                out.append(nxt.strip())
        return out
    return []


def _convert(raw: Optional[str], kind: str) -> Any:
    if raw is None:
        return None
    if kind == DATE:
        return to_date(raw)
    if kind == INT:
        return to_year(raw)
    if kind == NUM:
        return to_num(raw)
    return re.sub(r"\s+", " ", raw).strip()[:255] or None


def apply_specs(text: str, specs: List[Tuple[str, str, List[str]]]) -> Dict[str, Any]:
    return {col: _convert(safe_find_field(text, labels), kind) for col, kind, labels in specs}


def detect_result(text: str) -> Optional[str]:
    m = re.search(r"\b(PASS(?:ED)?|FAIL(?:ED)?|PROMOTED|ABSENT|COMPARTMENT)\b", text or "", re.I)
    return m.group(1).upper() if m else None


def _split_list(items: List[str]) -> List[str]:
    joined = " ".join(items)
    parts = re.split(r"\s*(?:\(?[ivx]+\)|\(?\d+\)|\d+\.|;|,)\s*", joined)
    return [p.strip(" .") for p in parts if p and p.strip(" .")]


# Common label definitions
_DELIM = r"(?=\s*[:\-–—])"
L_NAME = [
    r"Name\s+of\s+the\s+(?:Candidate|Student|Pupil|Child)",
    r"(?:Candidate|Student|Pupil|Child)'?s?\s+Name",
    r"(?<!College )(?<!School )(?<!Course )(?<!Degree )(?<!University )(?<!'s )\bName\b" + _DELIM,
]
L_FATHER = [
    r"Father'?s?\s*(?:/\s*Guardian'?s?)?\s*Name",
    r"Name\s+of\s+(?:the\s+)?Father(?:\s*/\s*Guardian)?",
    r"\bFather\b" + _DELIM,
]
L_MOTHER = [
    r"Mother'?s?\s*Name",
    r"Name\s+of\s+(?:the\s+)?Mother",
    r"\bMother\b" + _DELIM,
]
L_DOB = [r"Date\s+of\s+Birth", r"\bD\.?O\.?B\.?\b", r"பிறந்த\s*தேதி"]
L_ISSUER = [r"Issuing\s+Authority", r"Issued\s+By", r"Tahsildar", r"Registrar"]
L_ISSUE_DATE = [r"Date\s+of\s+Issue", r"Issue\s+Date", r"Date\s+of\s+Registration", r"\bDate\b" + _DELIM]
L_CERT_NO = [r"Certificate\s*(?:No|Number)\.?", r"Serial\s*(?:No|Number)\.?", r"Reference\s*(?:No|Number)\.?"]
L_ADDRESS = [r"Permanent\s+Residential\s+Address", r"Permanent\s+Address", r"Address"]
L_ROLL = [r"Roll\s*(?:No|Number)\.?"]
L_SCHOOL = [r"Name\s+of\s+(?:the\s+)?School", r"School\s+Name", r"\bSchool\b" + _DELIM]
L_COLLEGE = [r"Name\s+of\s+(?:the\s+)?(?:College|Institution|Polytechnic)", r"College\s+Name"]
L_EMIS = [r"\bEMIS\s*(?:ID|No|Number)?"]


# ============================================================================
# 3. Document-Specific Parsers (All 17 Types)
# ============================================================================

# ----------------------------------------------------------------------------
# 1. State Board 10th Marksheet (Tamil Nadu SSLC)
# ----------------------------------------------------------------------------
_S10_MONTH = r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*"
_S10_LANGS = ("ENGLISH", "TAMIL", "HINDI", "TELUGU", "MALAYALAM", "KANNADA", "URDU")


def parse_state_board_10th(ocr_text: str) -> Dict[str, Any]:
    text = ocr_text or ""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    flat = "\n".join(lines)
    flat_upper = flat.upper()
    ascii_upper = _strip_tamil(flat_upper)

    # 1. Candidate Name
    candidate = None
    for l in lines:
        a = _strip_tamil(l)
        m = re.search(r"^(.*?)\s*MARK\s+CERTIFICATE", a, re.I)
        if m:
            candidate = clean_name(m.group(1))
            if candidate:
                break
    if not candidate:
        for l in lines:
            a = _strip_tamil(l)
            m = re.search(rf"^(.*?)\b{_S10_MONTH}\s*\d{{4}}\b", a, re.I)
            if m:
                candidate = clean_name(m.group(1))
                if candidate:
                    break

    # 2. Parents Name
    father, mother = None, None
    for i, l in enumerate(lines):
        if re.search(r"FATHER|MOTHER|GUARDIAN", l, re.I):
            for nxt in lines[i + 1: i + 5]:
                if re.search(r"CERTIFIED|STANDARD|ROLL", nxt, re.I):
                    break
                a = _strip_tamil(nxt)
                if not re.search(r"\d", a):
                    parts = a.split()
                    if len(parts) >= 4:
                        # Parents typically listed side by side, e.g. 'VADIVEL P SHANMUGA SUNDARI V'
                        mid = len(parts) // 2
                        father = clean_name(" ".join(parts[:mid]))
                        mother = clean_name(" ".join(parts[mid:]))
                        break

    # 3. Register & Permanent Register Number
    s_clean = re.sub(r"[\s:|]", "", ascii_upper)
    m_reg = re.search(r"X[MN]([0-9OIL]{2})R([0-9OIL]{6,14})", s_clean)
    register = None
    if m_reg:
        fix = lambda x: x.replace("O", "0").replace("I", "1").replace("L", "1")
        register = f"XM{fix(m_reg.group(1))}R{fix(m_reg.group(2))}"

    # 4. DOB & Roll Number & Medium
    dob, roll, medium = None, None, None
    for i, l in enumerate(lines):
        if re.search(r"DATE\s+OF\s+BIRTH", l, re.I):
            window = " ".join(lines[i: i + 4])
            dob = to_date(window)
            m_roll = re.search(r"\b(\d{6,8})\b", re.sub(r"\d{1,2}[./-]\d{1,2}[./-]\d{4}", " ", _strip_tamil(window)))
            if m_roll:
                roll = m_roll.group(1)
            m_med = re.search(rf"\b({'|'.join(_S10_LANGS)})\b", window.upper())
            if m_med:
                medium = m_med.group(1)
            break

    # 5. Session & Exam Year
    sm = re.search(rf"\b({_S10_MONTH})[ \t]*[-/]?[ \t]*(\d{{4}})\b", ascii_upper)
    session = f"{sm.group(1)[:3].upper()} {sm.group(2)}" if sm else None
    exam_year = int(sm.group(2)) if sm else None

    # 6. School Name
    school = None
    for l in lines:
        a = _strip_tamil(l).upper()
        if re.search(r"MATRIC|\bHR\.?\s*SEC|HIGHER\s+SECONDARY|HIGH\s+SCHOOL", a):
            if not re.search(r"EXAMINATION|CERTIFICATE|AUTHORITY|LEAVING", a):
                cand = re.sub(r"^[A-Z]{1,2}\s+", "", a.strip(" -.,"))
                cand = re.sub(r"\s+[A-Z]{1,2}$", "", cand)
                if len(cand) >= 8:
                    school = cand
                    break

    # 7. Serial Number (SEC ########)
    serial = None
    m_sec = re.search(r"\bSEC\s*(\d{8})\b", ascii_upper)
    if m_sec:
        serial = f"SEC {m_sec.group(1)}"
    elif re.search(r"SERIAL_HINT:\s*SEC\s*(\d{8})", text):
        serial = re.search(r"SERIAL_HINT:\s*(SEC\s*\d{8})", text).group(1)

    # 8. EMIS ID & TMR Code
    emis = None
    m_emis = re.search(r"EMIS[ \t]*(?:ID)?[ \t]*(?:NO\.?)?[ \t]*[:|.-]?[ \t]*(\d{8,20})", ascii_upper)
    if m_emis:
        emis = m_emis.group(1)

    tmr_code, tmr_date = None, None
    for i, l in enumerate(lines):
        cm = re.search(r"(?<![A-Z0-9])([RZ]\d{6,10})(?![A-Z0-9])", l.upper())
        if cm:
            tmr_code = cm.group(1)
            tmr_date = to_date(" ".join(lines[i: i + 3]))
            break

    # 9. Subject Marks
    subjects = {
        "subject_1_name": "Tamil", "subject_1_marks": None,
        "subject_2_name": "English", "subject_2_marks": None,
        "subject_3_name": "Mathematics", "subject_3_marks": None,
        "subject_4_name": "Science", "subject_4_marks": None,
        "subject_4_theory_marks": None, "subject_4_practical_marks": None,
        "subject_5_name": "Social Science", "subject_5_marks": None,
    }

    sub_patterns = [
        ("subject_5", r"SOCIAL\s*SCIENCES?|சமூக\s*அறிவியல்"),
        ("subject_4", r"(?<!SOCIAL )SCIENCE|அறிவியல்"),
        ("subject_3", r"MATHEMATICS|MATHS?|கணிதம்"),
        ("subject_2", r"ENGLISH|ஆங்கிலம்"),
        ("subject_1", r"TAMIL(?![\s*NADU])|தமிழ்(?!நாடு)"),
    ]

    for line in lines:
        for key, rx in sub_patterns:
            if re.search(rx, line, re.I) and subjects[f"{key}_marks"] is None:
                nums = [int(x) for x in re.findall(r"(?<![\d.])\d{2,3}(?![\d.])", line) if int(x) <= 100]
                if nums:
                    subjects[f"{key}_marks"] = nums[-1]
                    if key == "subject_4" and len(nums) >= 3:
                        subjects["subject_4_theory_marks"] = nums[-3]
                        subjects["subject_4_practical_marks"] = nums[-2]

    # Total & Result
    m_tot = re.search(r"TOTAL[ \t]+MARKS[ \t]*[:\-]?[ \t]*0*(\d{2,3})\b", ascii_upper)
    total = float(m_tot.group(1)) if m_tot and int(m_tot.group(1)) <= 500 else None

    # Fallback to sum of 5 subjects if total marks not printed clearly
    subj_marks_list = [subjects[f"subject_{i}_marks"] for i in range(1, 6) if subjects[f"subject_{i}_marks"] is not None]
    if total is None and len(subj_marks_list) == 5:
        total = float(sum(subj_marks_list))

    percentage = round(total * 100 / 500.0, 2) if total is not None else None
    result = "PASS" if re.search(r"\bPASS\b", ascii_upper) else ("FAIL" if re.search(r"\bFAIL\b", ascii_upper) else None)

    d = {
        "certificate_serial_number": serial,
        "examination_board": "Directorate of Government Examinations, Tamil Nadu",
        "certificate_name": "Secondary School Leaving Certificate",
        "standard": "10th",
        "candidate_name": candidate,
        "date_of_birth": dob,
        "roll_number": roll,
        "register_number": register,
        "permanent_register_number": register,
        "medium_of_instruction": medium,
        "session": session,
        "exam_year": exam_year,
        "school_name": school,
        "school_address": None,
        "tmr_code_number": tmr_code,
        "tmr_code_date": tmr_date,
        "emis_id": emis,
        "total_marks": total,
        "maximum_total_marks": 500.0,
        "percentage": percentage,
        "result": result,
    }
    d.update(subjects)
    return d

parse_state_10th = parse_state_board_10th
parse_tn_10th = parse_state_board_10th


# ----------------------------------------------------------------------------
# 2. State Board 12th Marksheet (Tamil Nadu HSC)
# ----------------------------------------------------------------------------
_HSS_SUBJECTS = [
    ("tamil", r"TAMIL"),
    ("english", r"ENGLISH"),
    ("mathematics", r"MATH\w*|\w*(?:EMATICS|EMARICS)"),
    ("physics", r"PHYSICS"),
    ("chemistry", r"CHEMISTRY"),
    ("computer_science", r"COMPUTER\s+SCIENCE"),
    ("biology", r"BIOLOGY"),
    ("botany", r"BOTANY"),
    ("zoology", r"ZOOLOGY"),
    ("commerce", r"COMMERCE"),
    ("accountancy", r"ACCOUNTANCY"),
    ("economics", r"ECONOMICS"),
    ("history", r"HISTORY"),
]


def parse_state_12th(ocr_text: str) -> Dict[str, Any]:
    text = ocr_text or ""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    flat = "\n".join(lines)
    ascii_upper = _strip_tamil(flat.upper())

    # Candidate Name
    candidate = None
    for l in lines:
        a = _strip_tamil(l)
        m = re.search(r"(?:^|\s)([A-Z][A-Z .]{1,40}?)\s+MARK\s+CERTIFICATE", a, re.I)
        if m:
            candidate = clean_name(m.group(1))
            if candidate:
                break
    if not candidate:
        candidate = clean_name(safe_find_field(text, L_NAME))

    # Serial Number (HSS #######)
    serial = None
    m_hss = re.search(r"\bHSS\s*(\d{7,8})\b", ascii_upper)
    if m_hss:
        serial = f"HSS {m_hss.group(1)}"
    elif re.search(r"SERIAL_HINT:\s*HSS\s*(\d{7,8})", text):
        serial = re.search(r"SERIAL_HINT:\s*(HSS\s*\d{7,8})", text).group(1)

    # Date of Birth, Permanent Register Number, Session
    dob, perm_reg, session = None, None, None
    m_head = re.search(rf"(\d{{2}}[/.\-]\d{{2}}[/.\-]\d{{4}})\s+(\d{{8,12}})\s+({_S10_MONTH}\s+\d{{4}})", ascii_upper)
    if m_head:
        dob = to_date(m_head.group(1))
        perm_reg = m_head.group(2)
        session = m_head.group(3)
    else:
        dob = to_date(safe_find_field(text, L_DOB))
        m_s = re.search(rf"\b({_S10_MONTH}\s+\d{{4}})\b", ascii_upper)
        session = m_s.group(1) if m_s else None

    # Roll & Register Number
    m_reg = re.search(rf"\b(\d{{7}})\s+{_S10_MONTH}\s+\d{{4}}", ascii_upper)
    reg_no = m_reg.group(1) if m_reg else None

    # School Name
    school = None
    for i, l in enumerate(lines):
        if re.search(r"NAME\s+OF\s+THE\s+SCHOOL", l, re.I):
            for nxt in lines[i + 1: i + 4]:
                if re.search(r"MATRIC|\bHR\.?\s*SEC|HIGHER\s+SECONDARY", nxt, re.I):
                    cand = re.sub(r"^[A-Z]{1,2}\s+", "", nxt.strip(" -.,"))
                    school = re.sub(r"\s+[A-Z]{1,2}$", "", cand)
                    break
            if school:
                break

    # Group Code & Name
    group_code, group_name, medium = None, None, None
    for i, l in enumerate(lines):
        if re.search(r"GROUP\s+CODE", l, re.I):
            for b in lines[i + 1: i + 4]:
                m_code = re.search(r"\b(\d{4})\b", b)
                if m_code and not group_code:
                    group_code = m_code.group(1)
                m_g = re.search(rf"/\s*([A-Z][A-Z ,&]+?)\s+({'|'.join(_S10_LANGS)})\b", b, re.I)
                if m_g:
                    group_name = m_g.group(1).strip()
                    medium = m_g.group(2).upper()
            break

    # EMIS ID
    emis = None
    m_emis = re.search(r"EMIS\s*ID\s*No\.?\s*[:\-]?\s*(\d{6,})", ascii_upper)
    if m_emis:
        emis = m_emis.group(1)

    # Subject Marks
    sub_data = {}
    for prefix, _ in _HSS_SUBJECTS:
        sub_data[f"{prefix}_marks"] = None
        sub_data[f"{prefix}_theory_marks"] = None
        sub_data[f"{prefix}_internal_marks"] = None
        sub_data[f"{prefix}_practical_marks"] = None

    claimed_lines = set()
    totals_found = []
    for prefix, rx in _HSS_SUBJECTS:
        pat = re.compile(rf"\b(?:{rx})\b", re.I)
        for i, line in enumerate(lines):
            if i in claimed_lines or not pat.search(line):
                continue
            # Extract numbers on this line or line above
            nums = [int(x) for x in re.findall(r"(?<![\d.])\d{2,3}(?![\d.])", line) if int(x) <= 100]
            if len(nums) < 2 and i > 0 and (i - 1) not in claimed_lines:
                nums = [int(x) for x in re.findall(r"(?<![\d.])\d{2,3}(?![\d.])", lines[i - 1]) if int(x) <= 100]
            if len(nums) >= 2:
                claimed_lines.add(i)
                sub_data[f"{prefix}_marks"] = nums[-1]
                totals_found.append(nums[-1])
                if len(nums) >= 4:
                    sub_data[f"{prefix}_theory_marks"] = nums[0]
                    sub_data[f"{prefix}_practical_marks"] = nums[1]
                    sub_data[f"{prefix}_internal_marks"] = nums[2]
                elif len(nums) == 3:
                    sub_data[f"{prefix}_theory_marks"] = nums[0]
                    sub_data[f"{prefix}_internal_marks"] = nums[1]
                break

    # Total Marks & Result
    m_tot = re.search(r"TOTAL\s+MARKS\s*[:\-]?\s*0*(\d{2,4})", ascii_upper)
    total = float(m_tot.group(1)) if m_tot and int(m_tot.group(1)) <= 600 else None
    if total is None and len(totals_found) >= 5:
        total = float(sum(totals_found))

    percentage = round(total * 100 / 600.0, 2) if total is not None else None
    result = detect_result(text)

    d = {
        "certificate_serial_number": serial,
        "examination_board": "Directorate of Government Examinations, Tamil Nadu",
        "certificate_name": "Higher Secondary Second Year Mark Certificate",
        "standard": "12th",
        "candidate_name": candidate,
        "date_of_birth": dob,
        "roll_number": reg_no,
        "register_number": reg_no,
        "permanent_register_number": perm_reg,
        "medium_of_instruction": medium or "ENGLISH",
        "session": session,
        "exam_year": to_year(session),
        "school_name": school,
        "school_address": None,
        "emis_id": emis,
        "group_code": group_code,
        "group_name": group_name,
        "total_marks": total,
        "maximum_total_marks": 600.0,
        "percentage": percentage,
        "result": result,
    }
    d.update(sub_data)
    return d


# ----------------------------------------------------------------------------
# 3 & 4. Transfer Certificates (State Board 10th & 12th)
# ----------------------------------------------------------------------------
TC_SPECS = [
    ("tc_number", TEXT, [r"T\.?\s?C\.?\s*(?:No|Number)", r"Transfer\s+Certificate\s*(?:No|Number)", r"Serial\s*(?:No|Number)"]),
    ("emis_number", TEXT, L_EMIS),
    ("admission_number", TEXT, [r"Admission\s*(?:No|Number)"]),
    ("school_name", TEXT, L_SCHOOL),
    ("school_address", TEXT, [r"School\s+Address"]),
    ("student_name", TEXT, L_NAME),
    ("father_name", TEXT, L_FATHER),
    ("mother_name", TEXT, L_MOTHER),
    ("nationality", TEXT, [r"Nationality"]),
    ("religion", TEXT, [r"Religion"]),
    ("community", TEXT, [r"Community(?:\s*(?:&|and)\s*Caste)?", r"Caste"]),
    ("gender", TEXT, [r"\bSex\b", r"\bGender\b"]),
    ("date_of_birth", DATE, L_DOB),
    ("date_of_admission", DATE, [r"Date\s+of\s+Admission", r"Admission\s+Date"]),
    ("scholarship_details", TEXT, [r"Scholarship"]),
    ("medical_inspection", TEXT, [r"Medical\s+Inspection"]),
    ("date_of_leaving", DATE, [r"Date\s+of\s+(?:Leaving|Relieving)"]),
    ("character_conduct", TEXT, [r"Character\s*(?:and|&)\s*Conduct", r"Conduct"]),
    ("date_of_tc", DATE, [r"Date\s+of\s+(?:Issue\s+of\s+)?T\.?C\.?", r"Date\s+of\s+Issue"]),
    ("course_of_study", TEXT, [r"Course\s+of\s+Study", r"Group"]),
]


def _parse_tc_generic(text: str, standard: str, with_subjects: bool = False, with_edu: bool = False) -> Dict[str, Any]:
    d = apply_specs(text, TC_SPECS)
    d["standard"] = standard

    # Dynamic Student Name cleanup
    if d.get("student_name"):
        d["student_name"] = clean_name(d["student_name"])
    if d.get("father_name"):
        d["father_name"] = clean_name(d["father_name"])
    if d.get("mother_name"):
        d["mother_name"] = clean_name(d["mother_name"])

    # Identification marks
    marks = block_after(text, r"Identification\s+Marks?(?:\s+of\s+the\s+(?:Pupil|Student))?", 2)
    d["identification_marks"] = _split_list(marks)

    if with_edu:
        d["education_type"] = _convert(safe_find_field(text, [r"Education\s+Type", r"Type\s+of\s+Education"]), TEXT)
    if with_subjects:
        subs = block_after(text, r"Subjects?\s*(?:Studied|Offered)", 2)
        d["subjects_offered"] = _split_list(subs)

    return d


def parse_state_10th_tc(text: str) -> Dict[str, Any]:
    return _parse_tc_generic(text, "10th", with_subjects=False, with_edu=False)


def parse_state_12th_tc(text: str) -> Dict[str, Any]:
    return _parse_tc_generic(text, "12th", with_subjects=True, with_edu=True)


# ----------------------------------------------------------------------------
# 5 & 6. CBSE Marksheets (Class 10 & Class 12)
# ----------------------------------------------------------------------------
CBSE_COMMON = [
    ("candidate_name", TEXT, L_NAME),
    ("father_name", TEXT, L_FATHER),
    ("mother_name", TEXT, L_MOTHER),
    ("roll_number", TEXT, L_ROLL),
    ("school_name", TEXT, L_SCHOOL),
    ("school_affiliation_number", TEXT, [r"Affiliation\s*(?:No|Number)"]),
    ("date_of_birth", DATE, L_DOB),
    ("examination_year", INT, [r"Examination\s*Year", r"Year\s+of\s+Examination"]),
    ("total_marks", NUM, [r"Total\s*Marks", r"Grand\s*Total"]),
    ("maximum_marks", NUM, [r"Maximum\s*Marks"]),
    ("percentage", NUM, [r"Percentage"]),
    ("overall_grade", TEXT, [r"Overall\s+Grade"]),
]

CBSE_10_SUBJECTS = [
    ("english", r"English"), ("hindi", r"Hindi"), ("tamil", r"Tamil"),
    ("sanskrit", r"Sanskrit"), ("mathematics", r"Mathematics"),
    ("science", r"Science"), ("social_science", r"Social\s+Science"),
    ("information_technology", r"Information\s+Technology"),
    ("computer_applications", r"Computer\s+Applications"),
    ("artificial_intelligence", r"Artificial\s+Intelligence"),
]

CBSE_12_SUBJECTS = CBSE_10_SUBJECTS[:5] + [
    ("applied_mathematics", r"Applied\s+Mathematics"),
    ("physics", r"Physics"), ("chemistry", r"Chemistry"), ("biology", r"Biology"),
    ("computer_science", r"Computer\s+Science"),
    ("informatics_practices", r"Informatics\s+Practices"),
    ("biotechnology", r"Biotechnology"), ("accountancy", r"Accountancy"),
    ("business_studies", r"Business\s+Studies"), ("economics", r"Economics"),
    ("entrepreneurship", r"Entrepreneurship"), ("history", r"History"),
    ("geography", r"Geography"), ("political_science", r"Political\s+Science"),
    ("sociology", r"Sociology"), ("psychology", r"Psychology"),
    ("philosophy", r"Philosophy"), ("physical_education", r"Physical\s+Education"),
    ("home_science", r"Home\s+Science"), ("fine_arts", r"Fine\s+Arts"),
    ("legal_studies", r"Legal\s+Studies"),
]


def _cbse_subject(text: str, name_rx: str) -> Tuple[Optional[float], Optional[str]]:
    """Extract (marks, grade) from CBSE table line like '041 MATHEMATICS 092 NINETY TWO A1'."""
    m = re.search(rf"^[ \t]*(?:\d{{3}}[ \t]+)?(?:{name_rx})\b(?P<rest>.*)$", text, re.I | re.M)
    if not m:
        return None, None
    rest = m.group("rest")
    nums = [float(x) for x in re.findall(r"\b\d{2,3}\b", rest) if float(x) <= 100]
    marks = nums[0] if nums else None

    # Grade
    g = re.search(r"\b([A-E])([12lLiI|!]?)\s*$", rest.strip(), re.I)
    grade = None
    if g:
        dg = g.group(2)
        grade = g.group(1).upper() + ("" if not dg else ("2" if dg == "2" else "1"))
    return marks, grade


def _parse_cbse(text: str, subjects: List[Tuple[str, str]], with_stream: bool) -> Dict[str, Any]:
    d = apply_specs(text, CBSE_COMMON)
    d["candidate_name"] = clean_name(d.get("candidate_name"))
    d["father_name"] = clean_name(d.get("father_name"))
    d["mother_name"] = clean_name(d.get("mother_name"))

    s = re.search(r"\b(Main|Supplementary|Compartment|Improvement)\b", text, re.I)
    d["examination_session"] = s.group(1).title() if s else None
    if with_stream:
        d["stream"] = _convert(safe_find_field(text, [r"Stream"]), TEXT)

    marks_collected = []
    for prefix, rx in subjects:
        marks, grade = _cbse_subject(text, rx)
        d[f"{prefix}_marks"] = marks
        d[f"{prefix}_grade"] = grade
        d[f"{prefix}_5_marks"] = None
        if marks is not None:
            marks_collected.append(marks)

    d["result"] = detect_result(text)
    if d.get("total_marks") is None and len(marks_collected) >= 4:
        d["total_marks"] = float(sum(marks_collected))
    if d.get("maximum_marks") is None and d.get("total_marks"):
        d["maximum_marks"] = float(len(marks_collected) * 100)
    if d.get("percentage") is None and d.get("total_marks") and d.get("maximum_marks"):
        d["percentage"] = round(d["total_marks"] * 100 / d["maximum_marks"], 2)

    return d


def parse_cbse_10th(text: str) -> Dict[str, Any]:
    return _parse_cbse(text, CBSE_10_SUBJECTS, with_stream=False)


def parse_cbse_12th(text: str) -> Dict[str, Any]:
    return _parse_cbse(text, CBSE_12_SUBJECTS, with_stream=True)


# ----------------------------------------------------------------------------
# 7 & 8. CBSE Transfer Certificates (Class 10 & Class 12)
# ----------------------------------------------------------------------------
CBSE_TC_SPECS = [
    ("tc_number", TEXT, [r"T\.?\s?C\.?\s*(?:No|Number)", r"Transfer\s+Certificate\s*(?:No|Number)", r"Serial\s*(?:No|Number)"]),
    ("admission_number", TEXT, [r"Admission\s*(?:No|Number)"]),
    ("emis_number", TEXT, L_EMIS),
    ("school_name", TEXT, L_SCHOOL),
    ("school_affiliation_number", TEXT, [r"Affiliation\s*(?:No|Number)"]),
    ("school_address", TEXT, [r"School\s+Address"]),
    ("student_name", TEXT, L_NAME),
    ("father_name", TEXT, L_FATHER),
    ("mother_name", TEXT, L_MOTHER),
    ("nationality", TEXT, [r"Nationality"]),
    ("religion", TEXT, [r"Religion"]),
    ("community", TEXT, [r"Community", r"Caste"]),
    ("gender", TEXT, [r"\bSex\b", r"\bGender\b"]),
    ("date_of_birth", DATE, L_DOB),
    ("date_of_admission", DATE, [r"Date\s+of\s+Admission"]),
    ("scholarship_details", TEXT, [r"Scholarship"]),
    ("medical_inspection", TEXT, [r"Medical\s+Inspection"]),
    ("date_of_leaving", DATE, [r"Date\s+of\s+(?:Leaving|Relieving)"]),
    ("character_conduct", TEXT, [r"Character\s*(?:and|&)\s*Conduct", r"Conduct"]),
    ("date_of_tc", DATE, [r"Date\s+of\s+Issue"]),
    ("course_of_study", TEXT, [r"Course\s+of\s+Study", r"Class\s+Studied"]),
]


def parse_cbse_10th_tc(text: str) -> Dict[str, Any]:
    d = apply_specs(text, CBSE_TC_SPECS)
    d["standard"] = "10th"
    d["student_name"] = clean_name(d.get("student_name"))
    d["father_name"] = clean_name(d.get("father_name"))
    d["mother_name"] = clean_name(d.get("mother_name"))
    marks = block_after(text, r"Identification\s+Marks?", 2)
    d["identification_marks"] = _split_list(marks)
    return d


def parse_cbse_12th_tc(text: str) -> Dict[str, Any]:
    d = apply_specs(text, CBSE_TC_SPECS)
    d["standard"] = "12th"
    d["student_name"] = clean_name(d.get("student_name"))
    d["father_name"] = clean_name(d.get("father_name"))
    d["mother_name"] = clean_name(d.get("mother_name"))
    d["education_type"] = _convert(safe_find_field(text, [r"Education\s+Type"]), TEXT)
    subs = block_after(text, r"Subjects?\s*(?:Studied|Offered)", 2)
    d["subjects_offered"] = _split_list(subs)
    marks = block_after(text, r"Identification\s+Marks?", 2)
    d["identification_marks"] = _split_list(marks)
    return d


# ----------------------------------------------------------------------------
# 9. Birth Certificate (Handles both inline and Form 5 column block layouts)
# ----------------------------------------------------------------------------
def parse_birth_certificate(text: str) -> Dict[str, Any]:
    d = {
        "certificate_number": None,
        "student_name": None,
        "gender": None,
        "date_of_birth": None,
        "place_of_birth": None,
        "father_name": None,
        "mother_name": None,
        "permanent_address": None,
        "issuing_authority": None,
        "issue_date": None
    }

    # Clean lines and remove Tamil glyphs for field matching
    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    ascii_lines = [_strip_tamil(l).strip(" \t:/-”“\"'") for l in lines]

    # 1. Inline lookups
    d["certificate_number"] = safe_find_field(text, [r"Registration\s*(?:No|Number)\.?", r"Certificate\s*(?:No|Number)\.?"])
    d["student_name"] = clean_name(safe_find_field(text, [r"Name\s+of\s+Child", r"Child'?s?\s+Name", r"\bName\b" + _DELIM]))
    d["gender"] = safe_find_field(text, [r"\bSex\b", r"\bGender\b"])
    d["date_of_birth"] = to_date(safe_find_field(text, L_DOB))
    d["place_of_birth"] = safe_find_field(text, [r"Place\s+of\s+Birth"])
    d["father_name"] = clean_name(safe_find_field(text, L_FATHER))
    d["mother_name"] = clean_name(safe_find_field(text, L_MOTHER))
    d["permanent_address"] = safe_find_field(text, L_ADDRESS)
    d["issuing_authority"] = safe_find_field(text, L_ISSUER)
    d["issue_date"] = to_date(safe_find_field(text, L_ISSUE_DATE))

    # 2. Positional Form 5 handling (Tamil Nadu Municipal / e-District format)
    # Collect dates and authority
    dates = []
    for l in ascii_lines:
        for dm in re.finditer(r"(?<!\d)(\d{1,2}[./-]\d{1,2}[./-]\d{4})(?!\d)", l):
            dates.append(dm.group(1))
        if not d["issuing_authority"]:
            m_auth = re.search(r"\b([A-Za-z ]+(?:MUNICIPAL\s+CORPORATION|CORPORATION|MUNICIPALITY|TOWNSHIP|PANCHAYAT))\b", l, re.I)
            if m_auth:
                d["issuing_authority"] = m_auth.group(1).strip()

    for l in ascii_lines:
        if not d["certificate_number"]:
            m_cn = re.search(r"\b(\d{2,8}/\d{4}/\d{1,4})\b", l)
            if m_cn:
                d["certificate_number"] = m_cn.group(1)
        if not d["gender"]:
            m_g = re.search(r"\b(FEMALE|MALE|TRANSGENDER)\b", l, re.I)
            if m_g:
                d["gender"] = m_g.group(1).upper()

    if dates:
        parsed_dates = []
        for dt_str in dates:
            for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
                try:
                    p = datetime.strptime(dt_str, fmt).date()
                    parsed_dates.append(p)
                    break
                except ValueError:
                    pass
        if parsed_dates:
            parsed_dates.sort()
            if not d["date_of_birth"]:
                d["date_of_birth"] = parsed_dates[0].isoformat()
            if len(parsed_dates) > 1 and not d["issue_date"]:
                d["issue_date"] = parsed_dates[-1].isoformat()

    # Form 5 Father & Mother names on value lines starting with ':'
    for l in ascii_lines:
        m_parent = re.search(r"^:\s*([A-Z]\.[A-Z\s]+)", l)
        if m_parent:
            cand = clean_name(m_parent.group(1))
            if cand and not d["father_name"] and cand != d["student_name"]:
                d["father_name"] = cand
            elif cand and not d["mother_name"] and cand != d["father_name"] and cand != d["student_name"]:
                d["mother_name"] = cand

    # Form 5 Hospital place of birth
    if not d["place_of_birth"]:
        for i, l in enumerate(ascii_lines):
            if re.search(r"\bHOSPITAL\b", l, re.I):
                d["place_of_birth"] = l.lstrip(": ")
                break

    return d


# ----------------------------------------------------------------------------
# 10. Income Certificate
# ----------------------------------------------------------------------------
def parse_income_certificate(text: str) -> Dict[str, Any]:
    d = apply_specs(text, [
        ("certificate_number", TEXT, L_CERT_NO),
        ("candidate_name", TEXT, L_NAME),
        ("annual_income", NUM, [r"Annual\s+(?:Family\s+)?Income", r"\bIncome\b" + _DELIM, r"வருமானம்"]),
        ("occupation", TEXT, [r"Occupation", r"Profession"]),
        ("address", TEXT, L_ADDRESS),
        ("issuing_authority", TEXT, L_ISSUER),
        ("issue_date", DATE, L_ISSUE_DATE),
    ])

    # Narrative extraction fallback (Tamil Nadu e-District)
    _TITLES = r"(?:Thiru|Thirumathi|Tmt|Selvi|Selvan|Kumari|Kum|Mr|Mrs|Ms|Shri|Sri|Smt)"
    m_name = re.search(rf"certify\s+that\s+(?:{_TITLES}\.?\s+)?([A-Za-z][A-Za-z .'$§_-]{{1,60}}?)\s*,?\s+(?:son|daughter|wife|ward)\s+(?:son\s+)?of\b", text, re.I)
    if m_name and not d.get("candidate_name"):
        d["candidate_name"] = clean_name(m_name.group(1))

    m_addr = re.search(r"(?:residing|resident)\s+(?:at|in|of)\s+([^,.\n]+?)(?:,\s*and|\s+has|\s+having)", text, re.I)
    if m_addr and not d.get("address"):
        d["address"] = m_addr.group(1).strip()

    m_inc = re.search(r"(?:annual\s+income\s+is\s+Rs\.?|Rupees)\s*(\d[\d,]*)", text, re.I)
    if m_inc and not d.get("annual_income"):
        d["annual_income"] = to_num(m_inc.group(1))

    d["candidate_name"] = clean_name(d.get("candidate_name"))
    return d


# ----------------------------------------------------------------------------
# 11. Community Certificate
# ----------------------------------------------------------------------------
def parse_community_certificate(text: str) -> Dict[str, Any]:
    d = apply_specs(text, [
        ("certificate_number", TEXT, [r"Community\s+Certificate\s*(?:No|Number)"] + L_CERT_NO),
        ("candidate_name", TEXT, L_NAME),
        ("father_name", TEXT, L_FATHER),
        ("community_name", TEXT, [r"Community(?!\s+Certificate)", r"Community\b"]),
        ("caste_name", TEXT, [r"Caste\b"]),
        ("address", TEXT, L_ADDRESS),
        ("issuing_authority", TEXT, L_ISSUER),
        ("issue_date", DATE, L_ISSUE_DATE),
    ])

    # Tamil Nadu e-District narrative extraction
    _TITLES = r"(?:Thiru|Thirumathi|Tmt|Selvi|Selvan|Kumari|Kum|Mr|Mrs|Ms|Shri|Sri|Smt)"
    m_name = re.search(rf"certify\s+that\s+(?:{_TITLES}\.?\s+)?([A-Za-z][A-Za-z .'$§_-]{{1,60}}?)\s*,?\s+(?:son|daughter|wife|ward)\s+(?:son\s+)?of\b", text, re.I)
    if m_name:
        d["candidate_name"] = clean_name(m_name.group(1))

    m_father = re.search(rf"(?:son|daughter|wife|ward)\s+(?:son\s+)?of\s+(?:{_TITLES}\.?\s+)?([A-Za-z][A-Za-z .'$§_-]{{1,60}}?)\s*(?:residing|,)", text, re.I)
    if m_father:
        d["father_name"] = clean_name(m_father.group(1))

    m_addr = re.search(r"(?:residing\s+at|reside\(s\)\s+at)\s+(.+?)(?:,\s*SORAPUTHUR|\s*belongs\s+to|\s*Village)", text, re.I)
    if m_addr and not d.get("address"):
        d["address"] = m_addr.group(1).strip()

    m_caste = re.search(r"belongs\s+to\s+(?:the\s+)?([A-Za-z0-9\s\-]+?)\s+Community", text, re.I)
    if m_caste:
        d["caste_name"] = m_caste.group(1).strip()

    m_comm = re.search(r"\b(Most\s+Backward\s+Class|Backward\s+Class|Scheduled\s+Caste|Scheduled\s+Tribe|MBC|BC|SC|ST|OC)\b", text, re.I)
    if m_comm:
        d["community_name"] = m_comm.group(1).strip()

    # e-District Certificate Number (e.g. F6AA6C6C6A687C86 or TN-320...)
    m_sec_num = re.search(r"(?:unique\s+certificate\s+number|certificate\s+number)\s+([A-Z0-9]{12,24})", text, re.I)
    if m_sec_num:
        d["certificate_number"] = m_sec_num.group(1)

    # Authority & Date
    m_auth = re.search(r"(?:Designation\s*:\s*|பதவி\s*:\s*)([^\n]+(?:Tahsildar|Deputy\s+Tahsildar))", text, re.I)
    if m_auth:
        d["issuing_authority"] = m_auth.group(1).strip()

    d["candidate_name"] = clean_name(d.get("candidate_name"))
    d["father_name"] = clean_name(d.get("father_name"))
    return d


# ----------------------------------------------------------------------------
# 12. Nativity Certificate
# ----------------------------------------------------------------------------
def parse_nativity_certificate(text: str) -> Dict[str, Any]:
    d = apply_specs(text, [
        ("certificate_number", TEXT, L_CERT_NO),
        ("candidate_name", TEXT, L_NAME),
        ("address", TEXT, L_ADDRESS),
        ("issuing_authority", TEXT, L_ISSUER),
        ("issue_date", DATE, L_ISSUE_DATE),
    ])

    _TITLES = r"(?:Thiru|Thirumathi|Tmt|Selvi|Selvan|Kumari|Kum|Mr|Mrs|Ms|Shri|Sri|Smt)"
    m_name = re.search(rf"certify\s+that\s+(?:{_TITLES}\.?\s+)?([A-Za-z][A-Za-z .'$§_-]{{1,60}}?)\s*,?\s+(?:son|daughter|wife|ward|residing)\b", text, re.I)
    if m_name and not d.get("candidate_name"):
        d["candidate_name"] = clean_name(m_name.group(1))

    m_addr = re.search(r"(?:residing|native)\s+(?:at|in|of)\s+([^,.\n]+?)(?:,\s*State|\s+is\s+a\s+native)", text, re.I)
    if m_addr and not d.get("address"):
        d["address"] = m_addr.group(1).strip()

    d["candidate_name"] = clean_name(d.get("candidate_name"))
    return d


# ----------------------------------------------------------------------------
# 13. Aadhaar Card
# ----------------------------------------------------------------------------
NUM_RE = re.compile(r"(?<!\d)(?<!\d[ \t])\d{4}[ \t]?\d{4}[ \t]?\d{4}(?![ \t]?\d)")


def parse_aadhaar(text: str) -> Dict[str, Any]:
    d = {
        "name_on_card": None,
        "date_of_birth": None,
        "father_name": None,
        "address": None,
        "aadhaar_last_four": None
    }
    m = NUM_RE.search(text or "")
    if m:
        d["aadhaar_last_four"] = re.sub(r"\D", "", m.group())[-4:]

    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    for i, line in enumerate(lines):
        if re.search(r"\bDOB\b|Date\s+of\s+Birth|Year\s+of\s+Birth", line, re.I):
            d["date_of_birth"] = to_date(line)
            # Candidate name sits right above DOB line
            for j in range(i - 1, -1, -1):
                clean_cand = clean_name(lines[j])
                if clean_cand and not re.search(r"government|india|authority|unique|aadhaar|sample|card", lines[j], re.I):
                    d["name_on_card"] = clean_cand
                    break
            break

    rel = safe_find_field(text, [r"S/O", r"C/O", r"D/O", r"W/O"])
    d["father_name"] = clean_name(rel)

    addr_lines = block_after(text, r"Address", 4)
    addr = " ".join(addr_lines)
    addr = re.split(r"\b\d{4}\s?\d{4}\s?\d{4}\b", addr)[0]
    addr = re.split(r"SAMPLE DOCUMENT|VID\s*:", addr, flags=re.I)[0]
    d["address"] = re.sub(r"\s+", " ", addr).strip(" ,-")[:500] or None
    return d


def process_multi_aadhaar(text: str) -> Dict[str, Any]:
    """Parse multiple cards from one batch upload without cross-contamination."""
    raw_blocks = text.split("---") if "---" in text else [text]
    cards = []
    for b in raw_blocks:
        card = parse_aadhaar(b)
        if card.get("aadhaar_last_four") or card.get("name_on_card"):
            cards.append(card)
    if not cards:
        cards.append(parse_aadhaar(text))
    return {
        "doc_type": "aadhaar_card",
        "count": len(cards),
        "cards": cards,
        "extracted_text": mask_sensitive(text)
    }


# ----------------------------------------------------------------------------
# 14. Diploma Certificate
# ----------------------------------------------------------------------------
def parse_diploma_certificate(text: str) -> Dict[str, Any]:
    d = apply_specs(text, [
        ("certificate_number", TEXT, L_CERT_NO),
        ("college_name", TEXT, L_COLLEGE),
        ("emis_number", TEXT, L_EMIS),
        ("candidate_name", TEXT, L_NAME),
        ("register_number", TEXT, [r"Register\s*(?:No|Number)\.?", r"Reg\.?\s*No\.?"]),
        ("date_of_birth", DATE, L_DOB),
        ("course_name", TEXT, [r"Course(?:\s+Name)?", r"Diploma\s+in\s+([A-Za-z ]+)"]),
        ("department", TEXT, [r"Department", r"Branch"]),
        ("completion_year", INT, [r"Year\s+of\s+(?:Passing|Completion)", r"Month\s+and\s+Year"]),
        ("classification", TEXT, [r"Classification", r"Class\s+Obtained", r"Division"]),
    ])

    # Narrative extraction fallback
    m_cand = re.search(r"certify\s+that\s+([A-Za-z .]+?)\s*(?:,|\shas\b|\sReg)", text, re.I)
    if m_cand and not d.get("candidate_name"):
        d["candidate_name"] = clean_name(m_cand.group(1))

    m_reg = re.search(r"Reg(?:ister|\.)?\s*(?:No|Number)\.?\s*[:\-]?\s*([A-Za-z0-9]+)", text, re.I)
    if m_reg and not d.get("register_number"):
        d["register_number"] = m_reg.group(1)

    m_course = re.search(r"\b(Diploma\s+in\s+[A-Za-z ]+?)(?:,|\shas\b|\sheld\b)", text, re.I)
    if m_course and not d.get("course_name"):
        d["course_name"] = m_course.group(1).strip()

    d["candidate_name"] = clean_name(d.get("candidate_name"))
    d["result"] = detect_result(text)
    return d


# ----------------------------------------------------------------------------
# 15. Diploma Marksheet (Diploma Semester Marksheet)
# ----------------------------------------------------------------------------
def parse_diploma_semester(text: str) -> Dict[str, Any]:
    d = apply_specs(text, [
        ("college_name", TEXT, L_COLLEGE),
        ("emis_number", TEXT, L_EMIS),
        ("candidate_name", TEXT, L_NAME),
        ("register_number", TEXT, [r"Register\s*(?:No|Number)\.?", r"Reg\.?\s*No\.?"]),
        ("date_of_birth", DATE, L_DOB),
        ("course_name", TEXT, [r"Course(?:\s+Name)?", r"Diploma\s+in"]),
        ("department", TEXT, [r"Department", r"Branch"]),
        ("semester", INT, [r"Semester(?=\s*:)", r"\bSemester\s+(\d+)"]),
        ("exam_month", TEXT, [r"Month\s+of\s+Examination", r"Exam(?:ination)?\s+Month"]),
        ("exam_year", INT, [r"Year\s+of\s+Examination", r"Month\s+and\s+Year"]),
        ("total_marks", NUM, [r"Grand\s+Total", r"Total\s+Marks"]),
        ("maximum_marks", NUM, [r"Maximum\s+Marks"]),
        ("percentage", NUM, [r"Percentage"]),
        ("overall_grade", TEXT, [r"Overall\s+Grade", r"\bCGPA\b"]),
    ])

    # Subject table line parsing: e.g. "4041 Engineering Mathematics 25 60 85 A"
    _SEM_ROW = re.compile(
        r"^[ \t]*(?P<code>[A-Z0-9]{3,8})[ \t]+(?P<name>[A-Za-z &,\-()/]+?)[ \t]+"
        r"(?P<nums>(?:\d{1,3}(?:\.\d+)?[ \t]*)+?)(?P<grade>[A-Z]\+?)?[ \t]*$",
        re.M
    )
    totals = []
    for i, m in enumerate(_SEM_ROW.finditer(text), start=1):
        if i > 8:
            break
        nums = [float(x) for x in m.group("nums").split()]
        p = f"subject_{i}"
        d[f"{p}_name"] = m.group("name").strip()
        d[f"{p}_code"] = m.group("code")
        d[f"{p}_total_marks"] = nums[-1]
        if len(nums) >= 3:
            d[f"{p}_internal_marks"] = nums[0]
            d[f"{p}_external_marks"] = nums[1]
        if len(nums) >= 4:
            d[f"{p}_practical_marks"] = nums[2]
        d[f"{p}_maximum_marks"] = 100.0
        d[f"{p}_grade"] = m.group("grade")
        totals.append(nums[-1])

    if d.get("total_marks") is None and totals:
        d["total_marks"] = float(sum(totals))
        d["maximum_marks"] = float(len(totals) * 100)
    if d.get("percentage") is None and d.get("total_marks") and d.get("maximum_marks"):
        d["percentage"] = round(d["total_marks"] * 100 / d["maximum_marks"], 2)

    d["candidate_name"] = clean_name(d.get("candidate_name"))
    d["result"] = detect_result(text)
    return d


# ----------------------------------------------------------------------------
# 16. Degree Certificate
# ----------------------------------------------------------------------------
def parse_degree_certificate(text: str) -> Dict[str, Any]:
    d = apply_specs(text, [
        ("certificate_number", TEXT, L_CERT_NO),
        ("college_name", TEXT, L_COLLEGE),
        ("university_name", TEXT, [r"University\s+Name", r"\bUniversity\b" + _DELIM]),
        ("candidate_name", TEXT, L_NAME),
        ("register_number", TEXT, [r"Register\s*(?:No|Number)\.?", r"Reg\.?\s*No\.?"]),
        ("date_of_birth", DATE, L_DOB),
        ("degree_name", TEXT, [r"Degree\s+Name", r"\bDegree\b" + _DELIM, r"degree\s+of\s+([A-Za-z ]+)"]),
        ("department", TEXT, [r"Department", r"Branch"]),
        ("graduation_year", INT, [r"Year\s+of\s+(?:Passing|Graduation)", r"held\s+in\s+(?:[A-Za-z]+\s+)?((?:19|20)\d{2})"]),
        ("classification", TEXT, [r"Classification", r"Class\s+Obtained", r"Division"]),
    ])

    m_cand = re.search(r"certify\s+that\s+([A-Za-z .]+?)\s*(?:,|\shas\b|\sReg)", text, re.I)
    if m_cand and not d.get("candidate_name"):
        d["candidate_name"] = clean_name(m_cand.group(1))

    m_deg = re.search(r"degree\s+of\s+((?:Bachelor|Master|Doctor)[A-Za-z .]+?)(?=\s+in\s|\sheld|\swith|,|\.|$)", text, re.I)
    if m_deg and not d.get("degree_name"):
        d["degree_name"] = m_deg.group(1).strip()

    m_dept = re.search(r"degree\s+of\s+(?:Bachelor|Master|Doctor)[A-Za-z .]+?\s+in\s+([A-Za-z .&]+?)(?=\sheld|\swith|,|\.|$)", text, re.I)
    if m_dept and not d.get("department"):
        d["department"] = m_dept.group(1).strip()

    m_class = re.search(r"\b((?:First|Second|Third)\s+Class(?:\s+with\s+(?:Distinction|Honours))?|Distinction)\b", text, re.I)
    if m_class and not d.get("classification"):
        d["classification"] = m_class.group(1).strip()

    d["candidate_name"] = clean_name(d.get("candidate_name"))
    d["result"] = detect_result(text)
    return d


# ----------------------------------------------------------------------------
# 17. Degree Marksheet (Degree Semester / Cumulative Marksheet)
# ----------------------------------------------------------------------------
def parse_degree_marksheet(text: str) -> Dict[str, Any]:
    d = apply_specs(text, [
        ("university_name", TEXT, [r"University\s+Name", r"\bUniversity\b" + _DELIM]),
        ("college_name", TEXT, L_COLLEGE),
        ("candidate_name", TEXT, L_NAME),
        ("register_number", TEXT, [r"Register\s*(?:No|Number)\.?", r"Reg\.?\s*No\.?"]),
        ("degree_name", TEXT, [r"Degree\s+Name", r"\bDegree\b" + _DELIM, r"Branch\s*/\s*Degree"]),
        ("department", TEXT, [r"Department", r"Branch"]),
        ("semester", INT, [r"Semester(?=\s*:)", r"\bSemester\s+(\d+)"]),
        ("exam_month", TEXT, [r"Month\s+of\s+Examination", r"Exam(?:ination)?\s+Month", r"Session"]),
        ("exam_year", INT, [r"Year\s+of\s+Examination", r"Exam(?:ination)?\s+Year"]),
        ("total_marks", NUM, [r"Grand\s+Total", r"Total\s+Marks"]),
        ("maximum_marks", NUM, [r"Maximum\s+Marks"]),
        ("cgpa", NUM, [r"\bCGPA\b", r"Cumulative\s+Grade\s+Point\s+Average"]),
        ("sgpa", NUM, [r"\bSGPA\b", r"\bGPA\b"]),
        ("percentage", NUM, [r"Percentage"]),
        ("classification", TEXT, [r"Classification", r"Class\s+Obtained", r"Division"]),
    ])

    _DEG_ROW = re.compile(
        r"^[ \t]*(?P<code>[A-Z0-9]{4,10})[ \t]+(?P<name>[A-Za-z &,\-()/]+?)[ \t]+"
        r"(?P<nums>(?:\d{1,3}(?:\.\d+)?[ \t]*)+?)(?P<grade>[A-Z]\+?)?[ \t]*$",
        re.M
    )
    totals = []
    for i, m in enumerate(_DEG_ROW.finditer(text), start=1):
        if i > 10:
            break
        nums = [float(x) for x in m.group("nums").split()]
        p = f"subject_{i}"
        d[f"{p}_name"] = m.group("name").strip()
        d[f"{p}_code"] = m.group("code")
        d[f"{p}_total_marks"] = nums[-1]
        if len(nums) >= 3:
            d[f"{p}_internal_marks"] = nums[0]
            d[f"{p}_external_marks"] = nums[1]
        d[f"{p}_grade"] = m.group("grade")
        totals.append(nums[-1])

    if d.get("total_marks") is None and totals:
        d["total_marks"] = float(sum(totals))
        d["maximum_marks"] = float(len(totals) * 100)
    if d.get("percentage") is None and d.get("total_marks") and d.get("maximum_marks"):
        d["percentage"] = round(d["total_marks"] * 100 / d["maximum_marks"], 2)

    d["candidate_name"] = clean_name(d.get("candidate_name"))
    d["result"] = detect_result(text)
    return d


# ============================================================================
# 4. Scored Document Type Detection (Calibrated for All 17 Document Types)
# ============================================================================

_CBSE_PAT = r"\bCBSE\b|CENTRAL\s+BOARD\s+OF\s+SECONDARY"
_TC_PAT = r"TRANSFER\s+CERTIFICATE|SCHOOL\s+LEAVING|மாற்றுச்?\s*சான்றிதழ்"
_CLS12_PAT = r"(?:STANDARD|CLASS|STUDYING|STUDIED|COURSE)[^\n]{0,60}\b(?:XII|12TH|TWELFTH|PLUS\s*TWO|\+2|HIGHER\s+SECONDARY|HSC)\b"
_CLS10_PAT = r"(?:STANDARD|CLASS|STUDYING|STUDIED)[^\n]{0,60}\b(?:X|10TH|TENTH|10|SSLC|SECONDARY)\b"
_SEM_PAT = r"\bSEMESTER\b|\bSEM\b"

RULES: Dict[str, List[Tuple[str, int]]] = {
    "state_board_10th": [
        (r"SECONDARY\s+SCHOOL\s+LEAVING\s+CERTIFICATE", 5), (r"\bSEC\s*\d{8}\b", 4),
        (r"STATE\s+BOARD\s+OF\s+SCHOOL\s+EXAMINATIONS", 3), (r"GOVERNMENT\s+EXAMINATIONS", 2),
        (r"X\s+STANDARD|10TH\s+STANDARD", 2), (_TC_PAT, -8), (_CBSE_PAT, -6), (r"HIGHER\s+SECONDARY", -5)
    ],
    "state_board_12th": [
        (r"SECOND\s+YEAR\s+MARK\s+CERTIFICATE|HIGHER\s+SECONDARY\s+COURSE", 5), (r"\bHSS\s*\d{7,8}\b", 4),
        (r"STATE\s+BOARD\s+OF\s+SCHOOL\s+EXAMINATIONS", 3), (r"GOVERNMENT\s+EXAMINATIONS", 2),
        (r"HIGHER\s+SECONDARY", 2), (_TC_PAT, -8), (_CBSE_PAT, -6)
    ],
    "state_board_10th_tc": [
        (_TC_PAT, 5), (_CLS10_PAT, 3), (r"HIGH\s+SCHOOL|SECONDARY", 1),
        (_CLS12_PAT, -4), (_CBSE_PAT, -5)
    ],
    "state_board_12th_tc": [
        (_TC_PAT, 5), (r"HIGHER\s+SECONDARY|HSC|PLUS\s*TWO", 4), (_CLS12_PAT, 3),
        (_CLS10_PAT, -3), (_CBSE_PAT, -5)
    ],
    "cbse_10th_marksheet": [
        (_CBSE_PAT, 4), (r"SECONDARY\s+SCHOOL\s+EXAMINATION", 4), (r"CLASS\s*(?:X|10)\b", 3),
        (r"MARKS?\s+STATEMENT|STATEMENT\s+OF\s+MARKS|PASS\s+CERTIFICATE", 2), (_TC_PAT, -8), (r"SENIOR\s+SCHOOL", -6)
    ],
    "cbse_12th_marksheet": [
        (_CBSE_PAT, 4), (r"SENIOR\s+SCHOOL\s+CERTIFICATE\s+EXAMINATION", 4), (r"CLASS\s*(?:XII|12)\b", 3),
        (r"MARKS?\s+STATEMENT|STATEMENT\s+OF\s+MARKS|PASS\s+CERTIFICATE", 2), (_TC_PAT, -8)
    ],
    "cbse_10th_tc": [
        (_TC_PAT, 5), (_CBSE_PAT, 4), (_CLS10_PAT, 3), (_CLS12_PAT, -4)
    ],
    "cbse_12th_tc": [
        (_TC_PAT, 5), (_CBSE_PAT, 4), (_CLS12_PAT, 4), (_CLS10_PAT, -3)
    ],
    "birth_certificate": [
        (r"BIRTH\s+CERTIFICATE|CERTIFICATE\s+OF\s+BIRTH|பிறப்பு\s*சான்றிதழ்", 6),
        (r"PLACE\s+OF\s+BIRTH|பிறந்த\s*இடம்", 2), (r"REGISTRATION\s+OF\s+BIRTHS|REGISTRAR", 2)
    ],
    "income_certificate": [
        (r"INCOME\s+CERTIFICATE|வருமானச்?\s*சான்றிதழ்", 6), (r"ANNUAL\s+(?:FAMILY\s+)?INCOME|வருமானம்", 3),
        (r"TAHSILDAR|வட்டாட்சியர்", 2)
    ],
    "community_certificate": [
        (r"COMMUNITY\s+CERTIFICATE|சாதிச்?\s*சான்றிதழ்|சமுதாயச்?\s*சான்றிதழ்", 6),
        (r"\bCASTE\b|சாதி", 2), (r"MOST\s+BACKWARD|BACKWARD\s+CLASS|SCHEDULED\s+CASTE", 2)
    ],
    "nativity_certificate": [
        (r"NATIVITY\s+CERTIFICATE|பூர்வீகச்?\s*சான்றிதழ்|பிறப்பிடச்?\s*சான்றிதழ்|\bNATIVITY\b", 6),
        (r"NATIVE\s+OF|RESIDENCE", 2)
    ],
    "aadhaar_card": [
        (r"AADHAAR|ஆதார்", 5), (r"UNIQUE\s+IDENTIFICATION|UIDAI", 4),
        (r"\bVID\s*:", 3), (r"GOVERNMENT\s+OF\s+INDIA", 2), (r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)", 2)
    ],
    "diploma_certificate": [
        (r"DIPLOMA\s+CERTIFICATE|DIPLOMA\s+IN\b", 5),
        (r"DIRECTORATE\s+OF\s+TECHNICAL\s+EDUCATION|STATE\s+BOARD\s+OF\s+TECHNICAL", 3),
        (r"POLYTECHNIC", 2), (_SEM_PAT, -4), (r"MARKS?\s+SHEET", -3)
    ],
    "diploma_semester_marksheet": [
        (r"DIPLOMA|POLYTECHNIC", 4), (_SEM_PAT, 4), (r"\bMARKS?\b|STATEMENT\s+OF\s+MARKS", 2),
        (r"SUBJECT\s+CODE|INTERNAL|EXTERNAL", 2), (r"CONVOCATION", -3)
    ],
    "degree_certificate": [
        (r"DEGREE\s+CERTIFICATE|CONVOCATION|HAS\s+BEEN\s+CONFERRED|DEGREE\s+OF", 5),
        (r"\bUNIVERSITY\b", 3), (r"BACHELOR\s+OF|MASTER\s+OF|DOCTOR\s+OF", 3),
        (_SEM_PAT, -4), (r"GRADE\s+SHEET|MARKS\s+STATEMENT", -3), (r"POLYTECHNIC|DIPLOMA", -4)
    ],
    "degree_marksheet": [
        (r"\bUNIVERSITY\b", 3), (_SEM_PAT, 3), (r"STATEMENT\s+OF\s+MARKS|GRADE\s+SHEET|GRADE\s+CARD", 4),
        (r"CGPA|SGPA|CREDITS|GRADE\s+POINT", 3), (r"SUBJECT\s+CODE", 1), (r"POLYTECHNIC|DIPLOMA", -5)
    ],
}


def detect_scored(text: str) -> Dict[str, Any]:
    """Score all 17 document types against OCR text and return winner with confidence metrics."""
    t = text or ""
    scores = {}
    evidence = {}
    for dt, rlist in RULES.items():
        s = 0.0
        ev = []
        for rx, wt in rlist:
            if re.search(rx, t, re.I):
                s += wt
                ev.append(f"{wt:+d} {rx[:40]}")
        # Enforce mandatory patterns for TC
        if dt.endswith("_tc") and not re.search(_TC_PAT, t, re.I):
            s = 0.0
        if dt.startswith("cbse_") and dt.endswith("_tc") and not re.search(_CBSE_PAT, t, re.I):
            s = 0.0
        scores[dt] = s
        evidence[dt] = ev

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (best_type, best_score), (second_type, second_score) = ranked[0], ranked[1]

    ok = best_score >= DETECT_MIN_SCORE and (best_score - second_score) >= DETECT_MIN_MARGIN
    conf = round(max(0.0, min(1.0, best_score / 8.0)), 2)

    return {
        "type": best_type if best_score > 0 else None,
        "ok": ok,
        "score": best_score,
        "confidence": conf,
        "runner_up": {"type": second_type, "score": second_score},
        "evidence": evidence.get(best_type, [])
    }


def detect_doc_type(text: str) -> Optional[str]:
    """Return top document type if confident, else None."""
    res = detect_scored(text)
    return res["type"] if res["ok"] else None


# ============================================================================
# 5. Validation Layer
# ============================================================================

def validate_state_10th(d: Dict[str, Any], text: str = "") -> List[str]:
    warns = []
    got = [d.get(f"subject_{i}_marks") for i in range(1, 6) if d.get(f"subject_{i}_marks") is not None]
    if len(got) < 5:
        warns.append(f"only {len(got)} of 5 subject marks read")
    tot = d.get("total_marks")
    if tot is not None and got and sum(got) != tot:
        warns.append(f"subject marks sum to {sum(got)}, but total is {tot}")
    if not d.get("date_of_birth"):
        warns.append("date of birth missing or invalid")
    serial = d.get("certificate_serial_number") or ""
    if not re.fullmatch(r"SEC \d{8}", serial):
        warns.append("serial number not in 'SEC ########' format")
    return warns


def validate_state_12th(d: Dict[str, Any], text: str = "") -> List[str]:
    warns = []
    tot = d.get("total_marks")
    sub_totals = []
    for prefix, _ in _HSS_SUBJECTS:
        t = d.get(f"{prefix}_marks")
        if t is not None:
            sub_totals.append(t)
    if tot is not None and len(sub_totals) >= 5 and sum(sub_totals) != tot:
        warns.append(f"subject totals sum to {sum(sub_totals)}, but total_marks is {tot}")
    serial = d.get("certificate_serial_number") or ""
    if not re.fullmatch(r"HSS \d{7,8}", serial):
        warns.append(f"serial number '{serial}' not in 'HSS #######' format")
    return warns


def validate_generic(doc_type: str, d: Dict[str, Any]) -> List[str]:
    warns = []
    # Key fields required
    req = {
        "state_board_10th_tc": ["student_name", "date_of_birth", "tc_number"],
        "state_board_12th_tc": ["student_name", "date_of_birth", "tc_number"],
        "cbse_10th_marksheet": ["candidate_name", "roll_number", "total_marks"],
        "cbse_12th_marksheet": ["candidate_name", "roll_number", "total_marks"],
        "cbse_10th_tc": ["student_name", "date_of_birth", "tc_number"],
        "cbse_12th_tc": ["student_name", "date_of_birth", "tc_number"],
        "birth_certificate": ["student_name", "date_of_birth", "certificate_number"],
        "income_certificate": ["candidate_name", "annual_income", "certificate_number"],
        "community_certificate": ["candidate_name", "community_name", "certificate_number"],
        "nativity_certificate": ["candidate_name", "certificate_number"],
        "aadhaar_card": ["name_on_card", "date_of_birth", "aadhaar_last_four"],
        "diploma_certificate": ["candidate_name", "register_number"],
        "diploma_semester_marksheet": ["candidate_name", "register_number", "total_marks"],
        "degree_certificate": ["candidate_name", "register_number"],
        "degree_marksheet": ["candidate_name", "register_number", "total_marks"],
    }
    for col in req.get(doc_type, []):
        if not d.get(col):
            warns.append(f"{col} missing - verify manually")
    return warns


VALIDATORS = {
    "state_board_10th": validate_state_10th,
    "state_board_12th": validate_state_12th,
}


def validate_document(
    doc_type: str,
    fields: Dict[str, Any],
    text: str = "",
    saved_name: Optional[str] = None,
    saved_dob: Optional[str] = None
) -> List[str]:
    """Validate extracted fields without modifying values."""
    warns = []
    if doc_type in VALIDATORS:
        warns.extend(VALIDATORS[doc_type](fields, text))
    else:
        warns.extend(validate_generic(doc_type, fields))

    name = fields.get("candidate_name") or fields.get("student_name") or fields.get("name_on_card")
    if saved_name and name and not names_match(name, saved_name):
        warns.append(f"Name differs from saved student record: '{saved_name}' vs '{name}'")
    if saved_dob and fields.get("date_of_birth") and str(saved_dob) != str(fields["date_of_birth"]):
        warns.append(f"DOB differs from saved record: {saved_dob} vs {fields['date_of_birth']}")

    return warns


# ============================================================================
# 6. Tolerant Multi-Pass Parser (`parse_with_notes`)
# ============================================================================

def parse_with_notes(doc_type: str, text: str) -> Tuple[Dict[str, Any], List[str]]:
    """Primary parser execution with tolerant recovery for missing fields and notes."""
    if doc_type not in DOC_TYPES:
        raise ValueError(f"Unsupported document type: {doc_type}")

    # Pure copy to ensure zero cross-document contamination
    fields = copy.deepcopy(DOC_TYPES[doc_type]["parser"](text))
    notes = []

    # Flag missing key fields
    for k in ("candidate_name", "student_name", "name_on_card"):
        if k in fields and not fields[k]:
            notes.append(f"{k}: unreadable or not printed on document - verify manually")

    return fields, notes


# ============================================================================
# 7. Word Box Table Analysis & Field Status
# ============================================================================

def rows_from_words(words: List[Dict[str, Any]], tol: float = 0.6) -> List[Dict[str, Any]]:
    """Group OCR words into visual rows by vertical center."""
    rows = []
    for w in sorted(words, key=lambda w: w["y"] + w["h"] / 2):
        cy = w["y"] + w["h"] / 2
        if rows and abs(cy - rows[-1]["cy"]) <= tol * max(w["h"], rows[-1]["h"]):
            r = rows[-1]
            r["words"].append(w)
            r["cy"] = sum(x["y"] + x["h"] / 2 for x in r["words"]) / len(r["words"])
            r["h"] = max(r["h"], w["h"])
        else:
            rows.append({"cy": cy, "h": w["h"], "words": [w]})
    for r in rows:
        r["words"].sort(key=lambda w: w["x"])
        r["text"] = " ".join(w["text"] for w in r["words"])
    return rows


def cross_check_marks(doc_type: str, fields: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[str]:
    """Cross-check extracted subject marks against visual table row numbers."""
    warns = []
    if doc_type == "state_board_10th":
        targets = [
            ("subject_1_marks", r"\bTAMIL\b(?!\s*NADU)"),
            ("subject_2_marks", r"\bENGLISH\b"),
            ("subject_3_marks", r"\b(?:MATHEMATICS|MATHS?)\b"),
            ("subject_4_marks", r"(?<!SOCIAL )\bSCIENCE\b"),
            ("subject_5_marks", r"\bSOCIAL\s+SCIENCES?\b"),
        ]
        for col, rx in targets:
            val = fields.get(col)
            if val is None:
                continue
            row = next((r for r in rows if re.search(rx, r["text"].upper())), None)
            if row:
                nums = [int(x) for x in re.findall(r"(?<![\d.])\d{2,3}(?![\d.])", row["text"]) if int(x) <= 100]
                if nums and int(val) not in nums:
                    warns.append(f"{col}: extracted {int(val)} but row reads {nums} - please verify")
    return warns


def field_confidence(value: Any, words: List[Dict[str, Any]]) -> Optional[float]:
    """Compute average Tesseract OCR confidence of word boxes composing `value`."""
    if value in (None, "", []) or not words:
        return None
    s = str(value).upper()
    toks = re.findall(r"[A-Z0-9]+", s)
    if not toks:
        return None
    pool = {}
    for w in words:
        k = re.sub(r"[^A-Z0-9]", "", w["text"].upper())
        if k:
            pool.setdefault(k, []).append(w["conf"])
    confs = []
    for t in toks:
        if t in pool:
            confs.append(max(pool[t]))
    return round(sum(confs) / len(confs), 1) if confs else None


def build_field_status(fields: Dict[str, Any], notes: List[str], warnings: List[str], words: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    mentioned = set(re.findall(r"^([a-z0-9_]+):", "\n".join(list(notes) + list(warnings)), re.M))
    status_map = {}
    for col, val in fields.items():
        if val in (None, "", []):
            status_map[col] = {"status": "blank", "confidence": None}
            continue
        conf = field_confidence(val, words)
        needs_review = col in mentioned or (conf is not None and conf < LOW_WORD_CONF)
        status_map[col] = {
            "status": "review" if needs_review else "ok",
            "confidence": conf
        }
    return status_map


# ============================================================================
# 8. Single Document & Batch Isolated Processing
# ============================================================================

def process_document(
    filename: str,
    content: bytes,
    forced_type: Optional[str] = None,
    saved_name: Optional[str] = None,
    saved_dob: Optional[str] = None
) -> Dict[str, Any]:
    """
    End-to-end processing for a single document with guaranteed isolation:
      - Multi-page rendering / image deskewing and OSD orientation
      - Scored document-type detection with review flag
      - Dedicated certificate parser execution
      - Visual table cross-check and field status
    """
    env = {
        "file": filename,
        "sha256": hashlib.sha256(content or b"").hexdigest(),
        "status": "error",
        "doc_type": None,
        "detection": None,
        "fields": None,
        "field_status": {},
        "warnings": [],
        "raw_text": "",
        "pages": 1,
        "error": None
    }
    try:
        text = extract_text(content, filename)
        env["raw_text"] = mask_sensitive(text)
        words = []
        try:
            img = Image.open(io.BytesIO(content))
            img, _ = _osd_rotate(img)
            img, _ = _deskew(img)
            words = ocr_words(img)
        except Exception:
            pass

        det = detect_scored(text)
        env["detection"] = det

        doc_type = forced_type or (det["type"] if det["ok"] else None)
        if not doc_type:
            env["status"] = "review"
            env["warnings"].append("Document type not recognized confidently - manual selection required")
            return env

        env["doc_type"] = doc_type
        if doc_type not in DOC_TYPES:
            env["status"] = "review"
            env["warnings"].append(f"No parser implemented for '{doc_type}'")
            return env

        fields, notes = parse_with_notes(doc_type, text)
        warns = list(notes) + validate_document(doc_type, fields, text, saved_name, saved_dob)
        if words:
            warns += cross_check_marks(doc_type, fields, rows_from_words(words))

        env["fields"] = fields
        env["warnings"] = warns
        env["field_status"] = build_field_status(fields, notes, warns, words)

        if doc_type == "aadhaar_card":
            multi = process_multi_aadhaar(text)
            if multi["count"] > 1:
                env["cards"] = multi["cards"]

        has_review = any(s["status"] == "review" for s in env["field_status"].values())
        env["status"] = "review" if warns or has_review else "ok"

    except Exception as e:
        env["status"] = "error"
        env["error"] = f"{type(e).__name__}: {str(e)}"

    return env


def process_batch_isolated(files: List[Tuple[str, bytes]], **kwargs) -> List[Dict[str, Any]]:
    """Process multiple documents in a batch ensuring absolute isolation and zero state pollution."""
    out = []
    seen_hashes = {}
    for filename, content in files:
        env = process_document(filename, content, **kwargs)
        file_hash = env["sha256"]
        if file_hash in seen_hashes:
            env["warnings"].append(f"Duplicate file upload: matches '{seen_hashes[file_hash]}'")
            env["status"] = "review"
        else:
            seen_hashes[file_hash] = filename
        out.append(env)
    return out


# ============================================================================
# 9. Registry of All 17 Supported Document Types
# ============================================================================

def _cfg(table: str, parser, extracted_text: bool = True, verification: bool = True) -> Dict[str, Any]:
    return {
        "table": table,
        "parser": parser,
        "extracted_text": extracted_text,
        "verification": verification,
    }


DOC_TYPES: Dict[str, Dict[str, Any]] = {
    # 1. State Board 10th Marksheet
    "state_board_10th": _cfg("state_board_10th", parse_state_board_10th, False, False),
    # 2. State Board 12th Marksheet
    "state_board_12th": _cfg("state_board_12th", parse_state_12th, False, False),
    # 3. State Board 10th Transfer Certificate
    "state_board_10th_tc": _cfg("state_board_10th_tc", parse_state_10th_tc),
    # 4. State Board 12th Transfer Certificate
    "state_board_12th_tc": _cfg("state_board_12th_tc", parse_state_12th_tc),
    # 5. CBSE 10th Marksheet
    "cbse_10th_marksheet": _cfg("cbse_10th_marksheet", parse_cbse_10th, False, True),
    # 6. CBSE 12th Marksheet
    "cbse_12th_marksheet": _cfg("cbse_12th_marksheet", parse_cbse_12th, False, True),
    # 7. CBSE 10th Transfer Certificate
    "cbse_10th_tc": _cfg("cbse_10th_tc", parse_cbse_10th_tc),
    # 8. CBSE 12th Transfer Certificate
    "cbse_12th_tc": _cfg("cbse_12th_tc", parse_cbse_12th_tc),
    # 9. Birth Certificate
    "birth_certificate": _cfg("birth_certificate", parse_birth_certificate),
    # 10. Income Certificate
    "income_certificate": _cfg("income_certificate", parse_income_certificate),
    # 11. Community Certificate
    "community_certificate": _cfg("community_certificate", parse_community_certificate),
    # 12. Nativity Certificate
    "nativity_certificate": _cfg("nativity_certificate", parse_nativity_certificate),
    # 13. Aadhaar Card
    "aadhaar_card": _cfg("aadhaar_card", parse_aadhaar),
    # 14. Diploma Certificate
    "diploma_certificate": _cfg("diploma_certificate", parse_diploma_certificate),
    # 15. Diploma Marksheet
    "diploma_semester_marksheet": _cfg("diploma_semester_marksheet", parse_diploma_semester, False, True),
    # 16. Degree Certificate
    "degree_certificate": _cfg("degree_certificate", parse_degree_certificate),
    # 17. Degree Marksheet
    "degree_marksheet": _cfg("degree_marksheet", parse_degree_marksheet, False, True),
}


def parse_document(doc_type: str, text: str) -> Dict[str, Any]:
    """Execute the configured parser for the given document type."""
    if doc_type not in DOC_TYPES:
        raise ValueError(f"Unsupported document type: {doc_type}")
    return copy.deepcopy(DOC_TYPES[doc_type]["parser"](text))