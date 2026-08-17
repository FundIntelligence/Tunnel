"""
currency_detector.py
Deterministic currency detection from bank document text.
Layer 1 of the 3-layer currency detection system.

Returns ISO 4217 currency code or None.
Never raises. Never guesses. Never defaults to KES.
"""
import re
from typing import Optional

# Priority 1: explicit currency declarations
# These are the most reliable — the bank explicitly states the currency
_EXPLICIT = [
    (re.compile(
        r'(?:Currency|Account\s+Currency|Currency\s+of\s+Account|'
        r'Statement\s+Currency|Ccy)[:\s]+([A-Z]{3})\b',
        re.IGNORECASE
    ), 'code'),
    (re.compile(
        r'All\s+amounts?\s+(?:are\s+)?in\s+([A-Z]{3})\b',
        re.IGNORECASE
    ), 'code'),
    (re.compile(
        r'Amounts?\s+in\s+([A-Z]{3})\b',
        re.IGNORECASE
    ), 'code'),
]

# Priority 2: ISO codes in document header (first 300 chars of text)
# Only check header zone — ISO codes appear everywhere in amounts later
_ISO_CODES = {
    'KES', 'UGX', 'RWF', 'TZS', 'NGN', 'GHS', 'ETB', 'ZAR',
    'XOF', 'XAF', 'ZMW', 'CDF', 'MWK', 'SDG', 'BIF', 'DJF',
    'USD', 'EUR', 'GBP',
}

# Priority 3: local symbols and abbreviations → definitive ISO code
# Order matters: more specific patterns before shorter ones
_SYMBOLS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bKShs?\b|\bKshs?\b|\bK\.Shs?\b'), 'KES'),
    (re.compile(r'\bUShs\b|\bU\.Shs\b|\bUsh\b'), 'UGX'),
    (re.compile(r'\bRFw\b|\bFRw\b|\bFrw\b|\bRWF\b'), 'RWF'),
    (re.compile(r'GH[₵¢]|\bGH[Cc]\b'), 'GHS'),
    (re.compile(r'\bBirr\b'), 'ETB'),
    (re.compile(r'₦|\bNaira\b'), 'NGN'),
    # ZAR: "R" is very short — only match if followed by space+digits to avoid false positives
    (re.compile(r'\bR\s+\d[\d,]+'), 'ZAR'),
    # CFA/FCFA is ambiguous between XOF and XAF — do NOT resolve here, return None
    # Caller must use country (L2) to disambiguate
]

# Priority 4: inline amount patterns (scan first 10 transaction rows)
_INLINE = re.compile(
    r'\b(KES|UGX|RWF|TZS|NGN|GHS|ETB|ZAR|XOF|XAF|ZMW|USD|EUR|GBP)'
    r'\s+[\d,]+',
    re.IGNORECASE
)

# Codes that, when found via P2 header scan, indicate ambiguous CFA zones.
# These are valid ISO codes but require country context to distinguish XOF vs XAF.
_CFA_CODES = {'XOF', 'XAF'}


def detect(text: str, header_chars: int = 500) -> Optional[str]:
    """
    Detect currency from extracted document text.

    Args:
        text: Full extracted text from first 2-3 pages (pdfplumber or docai output)
        header_chars: How many chars to treat as the "header zone" for ISO code scan

    Returns:
        ISO 4217 currency code (str) or None if not determinable.
        Never raises. None means: use L2 (country lookup).
    """
    if not text or not text.strip():
        return None

    # P1: explicit declaration anywhere in the text
    for pattern, _ in _EXPLICIT:
        m = pattern.search(text)
        if m:
            code = m.group(1).upper()
            if code in _ISO_CODES:
                return code

    # P2: ISO code in header zone only (first N chars)
    header = text[:header_chars]
    for code in _ISO_CODES:
        if re.search(r'\b' + code + r'\b', header):
            # CFA codes in header without explicit declaration need L2 for disambiguation
            if code in _CFA_CODES:
                continue
            return code

    # P3: local symbols
    for pattern, code in _SYMBOLS:
        if pattern.search(text):
            return code

    # P4: inline amounts in first 2000 chars
    m = _INLINE.search(text[:2000])
    if m:
        return m.group(1).upper()

    return None


def detect_from_pages(pages_text: list[str], header_chars: int = 500) -> Optional[str]:
    """
    Convenience wrapper: detect from a list of page text strings.
    Concatenates first 3 pages with a space separator.
    """
    combined = ' '.join(p for p in pages_text[:3] if p)
    return detect(combined, header_chars)
