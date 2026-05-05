import logging

logger = logging.getLogger(__name__)


def build_price_list(price_results: list[dict], template: str) -> str:
    """
    Fill the price list template placeholders with current prices.
    Missing prices render as '—'.
    """
    values: dict[str, str] = {}
    for r in price_results:
        price = r.get("calculated_price")
        values[r["template_key"]] = _fmt(price) if price is not None else "—"

    try:
        return template.format(**values)
    except KeyError as e:
        logger.warning("Template placeholder %s not found in pricing results", e)
        return template


def build_report(
    price_results: list[dict],
    unavailable_channels: list[str],
    all_channel_names: list[str],
    started_at: str,
    errors: list[str],
) -> str:
    """
    Build the run report Telegram message.

    Args:
        price_results:       output of pricing.calculate_prices()
        unavailable_channels: channel usernames that could not be fetched
        all_channel_names:   all configured channel usernames
        started_at:          ISO-8601 timestamp of run start
        errors:              list of error strings collected during the run
    """
    ts = started_at[:16].replace("T", " ")

    found = [r for r in price_results if not r.get("price_kept")]
    missing = [r for r in price_results if r.get("price_kept")]

    lines: list[str] = [f"📊 Run Report — {ts}", ""]

    lines.append(f"✅ Found prices: {len(found)} / {len(price_results)}")
    if missing:
        lines.append("❌ Missing: " + ", ".join(r["canonical_name"] for r in missing))

    lines.append("")
    for ch in all_channel_names:
        status = "UNAVAILABLE ⚠️" if ch in unavailable_channels else "OK"
        lines.append(f"Channel: {ch} — {status}")

    if found:
        lines.append("")
        lines.append("Price changes:")
        for r in found:
            old = r.get("old_price")
            new = r.get("calculated_price")
            delta = r.get("price_delta", 0)

            if old is None:
                line = f"• {r['canonical_name']}: {_fmt(new)} RUB (first run)"
            elif delta == 0:
                line = f"• {r['canonical_name']}: {_fmt(new)} RUB (no change)"
            else:
                sign = "−" if delta < 0 else "+"
                line = f"• {r['canonical_name']}: {_fmt(old)} → {_fmt(new)} ({sign}{_fmt(abs(delta))})"

            if r.get("is_large_change"):
                line += " ⚠️ LARGE CHANGE"
            lines.append(line)

    lines.append("")
    if errors:
        lines.append("Errors:")
        for e in errors:
            lines.append(f"  • {e}")
    else:
        lines.append("Errors: none")

    return "\n".join(lines)


def _fmt(n: int | None) -> str:
    if n is None:
        return "—"
    return f"{n:,}".replace(",", " ")
