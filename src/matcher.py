import logging
import re
from functools import lru_cache

from src.config import ProductConfig
from src.parser import normalize

logger = logging.getLogger(__name__)

# ── Price extraction ───────────────────────────────────────────────────────────

_PRICE_NUMBER = r'\d{1,3}(?:[\s,.]\d{3})+|\d{4,7}'

# Prefer numbers after a separator on product lines:
# "iPhone 17 Pro 256GB Blue - 99.990₽", "Цена: 35.000₽".
_PRICE_AFTER_SEPARATOR = re.compile(
    rf'[-:—–]\s*({_PRICE_NUMBER})\s*(?:rub|р\.?|₽|руб\.?)?',
    re.IGNORECASE,
)

# Primary: number followed by an explicit currency marker.
# Matches:  "84 500 rub"  →  \d{1,3}(?:[\s,]\d{3})+
#           "84500 rub"   →  \d{4,7}
# Does NOT span across unrelated numbers like "256 87000".
_PRICE_EXPLICIT = re.compile(
    rf'({_PRICE_NUMBER})\s*(?:rub|р\.?|₽|руб\.?)',
    re.IGNORECASE,
)
# Fallback: bare 4-7 digit number on the same segment (likely a price)
_PRICE_BARE = re.compile(r'\b(\d{4,7})\b')
_IPHONE_17_RE = re.compile(r'\b17\b')


def _extract_price(text: str) -> int | None:
    m = _PRICE_AFTER_SEPARATOR.search(text)
    if m:
        val = _parse_price_number(m.group(1))
        if val is not None:
            return val

    m = _PRICE_EXPLICIT.search(text)
    if m:
        val = _parse_price_number(m.group(1))
        if val is not None:
            return val

    m = _PRICE_BARE.search(text)
    if m:
        val = int(m.group(1))
        if 1_000 <= val <= 9_999_999:
            return val
    return None


def _parse_price_number(raw: str) -> int | None:
    val = int(re.sub(r'[\s,.]', '', raw))
    if 1_000 <= val <= 9_999_999:
        return val
    return None


# ── Alias normalisation cache ──────────────────────────────────────────────────

@lru_cache(maxsize=512)
def _norm(text: str) -> str:
    """Normalize an alias string the same way message text is normalized."""
    result, _ = normalize(text)
    return result


# ── Core matching ──────────────────────────────────────────────────────────────

def _matches(segment: str, product: ProductConfig) -> bool:
    """Return True if the (already normalized) segment matches this product."""
    if _is_iphone_product(product) and not _has_iphone_17_generation(segment):
        return False

    # Check exclusions first — prevents e.g. "Pro Max 256" matching "Pro 256"
    for excl in product.exclude_if_contains:
        if excl in segment:
            return False

    if re.search(product.regex, segment, re.IGNORECASE):
        return True

    for alias in product.aliases:
        if _norm(alias) in segment:
            return True

    return False


def _is_iphone_product(product: ProductConfig) -> bool:
    return product.category.lower() == "iphone"


def _has_iphone_17_generation(text: str) -> bool:
    return bool(_IPHONE_17_RE.search(text))


# ── Public API ─────────────────────────────────────────────────────────────────

def match_products(
    messages: list[dict],
    products: list[ProductConfig],
) -> dict[str, dict]:
    """
    Match products to prices across all messages.

    Args:
        messages: list of dicts with keys:
                  channel_username, normalized_text, segments
        products: list of ProductConfig from config

    Returns:
        {product_id: {"min_price": int|None, "average_price": int|None, "source_channel": str|None, "all_prices": list}}
    """
    results: dict[str, dict] = {
        p.id: {
            "min_price": None,
            "average_price": None,
            "source_channel": None,
            "all_prices": [],
            "matched_lines": [],
        }
        for p in products
    }

    for msg in messages:
        channel = msg["channel_username"]
        segments: list[str] = msg["segments"]
        full_text: str = msg["normalized_text"]

        for product in products:
            # Pass 1 — per-line match (handles "Product — price" per line)
            matched_in_pass1 = False
            for seg in segments:
                if _matches(seg, product):
                    price = _extract_price(seg)
                    if price is not None:
                        _record(results, product.id, price, channel, seg)
                        matched_in_pass1 = True

            # Pass 2 — full-text context window (handles dense single-blob price lists)
            if not matched_in_pass1 and not _is_iphone_product(product):
                m = re.search(product.regex, full_text, re.IGNORECASE)
                if m is None:
                    for alias in product.aliases:
                        na = _norm(alias)
                        if na and na in full_text:
                            idx = full_text.index(na)
                            m = _FakeMatch(idx, idx + len(na))
                            break

                if m is not None:
                    start = max(0, m.start() - 80)
                    end = min(len(full_text), m.end() + 80)
                    context = full_text[start:end]

                    # Respect exclusions even in context
                    excluded = any(excl in context for excl in product.exclude_if_contains)
                    if not excluded:
                        price = _extract_price(context)
                        if price is not None:
                            _record(results, product.id, price, channel, context)

    for entry in results.values():
        if entry["all_prices"]:
            entry["average_price"] = round(sum(entry["all_prices"]) / len(entry["all_prices"]))

    found = sum(1 for v in results.values() if v["min_price"] is not None)
    logger.info("match_products: %d / %d products found prices", found, len(products))
    return results


def _record(results: dict, product_id: str, price: int, channel: str, text: str) -> None:
    entry = results[product_id]
    entry["all_prices"].append(price)
    entry["matched_lines"].append({
        "channel": channel,
        "text": text,
        "price": price,
    })
    if entry["min_price"] is None or price < entry["min_price"]:
        entry["min_price"] = price
        entry["source_channel"] = channel


class _FakeMatch:
    """Minimal stand-in for re.Match when we found an alias by string search."""
    def __init__(self, start: int, end: int):
        self._start = start
        self._end = end

    def start(self) -> int:
        return self._start

    def end(self) -> int:
        return self._end
