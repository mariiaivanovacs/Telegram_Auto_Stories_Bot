import re

# ── Transliteration table ──────────────────────────────────────────────────────
# Patterns are applied in order — longer/more-specific patterns first.
# All patterns match against lowercased text with word boundaries.
_TRANSLIT: list[tuple[str, str]] = [
    # Multi-syllable brand words first
    (r'\bмакбук\w*', 'macbook'),
    (r'\bаирподс\w*', 'airpods'),
    (r'\bаирпадс\w*', 'airpods'),
    (r'\bплейстейшн\w*', 'playstation'),
    (r'\bприставк\w*', 'playstation'),
    (r'\bгигабайт\w*', 'gb'),
    (r'\bтерабайт\w*', 'tb'),
    (r'\bрублей\b', 'rub'),
    (r'\bрубля\b', 'rub'),
    (r'\bруб\.?', 'rub'),
    # "р" (or "р.") directly after digits with no space — must come AFTER руб patterns
    (r'(?<=\d)\s*р\.?(?=\W|$)', ' rub'),
    (r'\bтысяч\w*', '000'),
    (r'\bтыс\.?', '000'),
    # Short brand/model words
    (r'\bайфон\w*', 'iphone'),
    (r'\bмакс\b', 'max'),
    (r'\bмак\b', 'mac'),
    (r'\bэппл\b', 'apple'),
    (r'\bэпл\b', 'apple'),
    (r'\bапл\b', 'apple'),
    (r'\bвотч\w*', 'watch'),
    (r'\bподс\b', 'pods'),
    (r'\bпро\b', 'pro'),
    (r'\bаир\b', 'air'),
    (r'\bгб\b', 'gb'),
    (r'\bтб\b', 'tb'),
    # пс before digit (пс5) or standalone — \b doesn't work between Cyrillic and digit
    (r'\bпс(?=\d|\W|$)', 'ps'),
    # "С11" / "с 11" — Cyrillic С before digits → Latin S (Series)
    (r'\bс\s*(\d+)\b', r's\1'),
]

_TRANSLIT_RE: list[tuple[re.Pattern, str]] = [
    (re.compile(pat, re.IGNORECASE), repl) for pat, repl in _TRANSLIT
]

# к-shorthand: 85к → 85000, 18.5к → 18500
_K_RE = re.compile(r'(\d+(?:[.,]\d+)?)\s*к\b', re.IGNORECASE)

# Markup: HTML tags + common Markdown bold/italic/code markers
_MARKUP_RE = re.compile(r'<[^>]+>|[*_`~]')

# Collapse whitespace
_WS_RE = re.compile(r'[ \t]+')


def normalize(text: str) -> tuple[str, list[str]]:
    """
    Normalize a Telegram message for product matching.

    Returns:
        (full_normalized_string, list_of_line_segments)

    The full string has newlines collapsed to spaces.
    The segment list preserves one entry per original non-empty line.
    Both are fully transliterated (Russian brand/model terms → Latin).
    """
    if not text:
        return "", []

    # 1. Strip HTML / Markdown markup
    text = _MARKUP_RE.sub(' ', text)

    # 2. Lowercase
    text = text.lower()

    # 3. Expand к-shorthand before transliteration (к is Cyrillic)
    text = _K_RE.sub(_expand_k, text)

    # 4. Transliterate Cyrillic brand/product terms
    for pattern, repl in _TRANSLIT_RE:
        text = pattern.sub(repl, text)

    # 5. Collect line segments (before collapsing newlines)
    segments = [_WS_RE.sub(' ', s).strip() for s in text.splitlines() if s.strip()]

    # 6. Collapse all whitespace to single spaces
    text = re.sub(r'\s+', ' ', text).strip()

    # 7. Remove zero-width / invisible characters
    text = re.sub(r'[​‌‍­﻿]', '', text)

    return text, segments


def _expand_k(m: re.Match) -> str:
    raw = m.group(1).replace(',', '.')
    return str(int(float(raw) * 1000))
