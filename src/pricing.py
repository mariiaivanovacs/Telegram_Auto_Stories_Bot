import logging

logger = logging.getLogger(__name__)


def calculate_prices(
    match_results: dict,
    db_products: list[dict],
    discount: int = 500,
    large_change_threshold: int = 3000,
) -> list[dict]:
    """
    Pure pricing calculation — no DB calls.

    Args:
        match_results: {template_key: {"min_price": int|None, "source_channel": str|None}}
        db_products:   rows from db.get_all_products() — must have id, template_key,
                       canonical_name, display_name, category, current_price
        discount:      RUB subtracted from competitor min price
        large_change_threshold: flag when |delta| exceeds this value

    Returns:
        list of result dicts (one per product, same order as db_products)
    """
    results: list[dict] = []

    for p in db_products:
        pid = p["template_key"]
        match = match_results.get(pid, {})
        competitor_price = match.get("min_price")
        source_channel = match.get("source_channel")
        old_price = p["current_price"]  # None on first ever run

        if competitor_price is not None:
            calculated = competitor_price - discount
            delta = (calculated - old_price) if old_price is not None else 0
            is_large = abs(delta) > large_change_threshold

            results.append({
                "db_id": p["id"],
                "template_key": pid,
                "canonical_name": p["canonical_name"],
                "display_name": p.get("display_name", p["canonical_name"]),
                "category": p.get("category", "Other"),
                "old_price": old_price,
                "competitor_price": competitor_price,
                "source_channel": source_channel,
                "calculated_price": calculated,
                "price_delta": delta,
                "is_large_change": is_large,
                "price_kept": False,
            })
            logger.debug(
                "%s: competitor=%s → %s (delta=%+d%s)",
                pid, competitor_price, calculated, delta, " LARGE" if is_large else "",
            )
        else:
            results.append({
                "db_id": p["id"],
                "template_key": pid,
                "canonical_name": p["canonical_name"],
                "display_name": p.get("display_name", p["canonical_name"]),
                "category": p.get("category", "Other"),
                "old_price": old_price,
                "competitor_price": None,
                "source_channel": None,
                "calculated_price": old_price,
                "price_delta": 0,
                "is_large_change": False,
                "price_kept": True,
            })
            logger.debug("%s: no price found — keeping %s", pid, old_price)

    found = sum(1 for r in results if not r["price_kept"])
    logger.info("Pricing: %d / %d products priced", found, len(results))
    return results
