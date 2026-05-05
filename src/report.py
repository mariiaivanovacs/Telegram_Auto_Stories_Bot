import io
import logging

logger = logging.getLogger(__name__)

# Try to import openpyxl at module level
try:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except ImportError as e:
    logger.warning("openpyxl not available for Excel export: %s", e)
    HAS_OPENPYXL = False


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

    lines: list[str] = [f"📊 Отчёт запуска — {ts}", ""]

    lines.append(f"✅ Найдено цен: {len(found)} / {len(price_results)}")
    if missing:
        lines.append("❌ Отсутствуют: " + ", ".join(r["canonical_name"] for r in missing))

    lines.append("")
    for ch in all_channel_names:
        status = "НЕДОСТУПЕН ⚠️" if ch in unavailable_channels else "ОК"
        lines.append(f"Канал: {ch} — {status}")

    if found:
        lines.append("")
        lines.append("Изменения цен:")
        for r in found:
            old = r.get("old_price")
            new = r.get("calculated_price")
            delta = r.get("price_delta", 0)

            if old is None:
                line = f"• {r['canonical_name']}: {_fmt(new)} RUB (первый запуск)"
            elif delta == 0:
                line = f"• {r['canonical_name']}: {_fmt(new)} RUB (без изменений)"
            else:
                sign = "−" if delta < 0 else "+"
                line = f"• {r['canonical_name']}: {_fmt(old)} → {_fmt(new)} ({sign}{_fmt(abs(delta))})"

            if r.get("is_large_change"):
                line += " ⚠️ БОЛЬШОЕ ИЗМЕНЕНИЕ"
            lines.append(line)

    lines.append("")
    if errors:
        lines.append("Ошибки:")
        for e in errors:
            lines.append(f"  • {e}")
    else:
        lines.append("Ошибки: нет")

    return "\n".join(lines)


def build_competition_report_excel(run: dict, rows: list[dict]) -> bytes:
    """
    Generate an Excel (.xlsx) competition price report.

    run:  dict with started_at, products_found, products_missing
    rows: from db.get_competition_report_data(run_id)
    """
    if not HAS_OPENPYXL:
        raise RuntimeError("openpyxl is required for Excel export. Install it with: pip install openpyxl")

    wb = openpyxl.Workbook()

    # ── Sheet 1: Summary ──────────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Сводка"

    run_date = (run.get("started_at") or "")[:16].replace("T", " ")
    total = (run.get("products_found") or 0) + (run.get("products_missing") or 0)

    summary_rows = [
        ("Дата запуска", run_date),
        ("Найдено цен", f"{run.get('products_found', 0)} / {total}"),
        ("Пропущено", run.get("products_missing", 0)),
    ]
    for label, value in summary_rows:
        ws1.append([label, value])
        ws1.cell(row=ws1.max_row, column=1).font = Font(bold=True)

    # ── Sheet 2: Competitor details ────────────────────────────────────────────
    ws2 = wb.create_sheet("Конкуренты")

    headers = ["Товар", "Категория", "Наша цена (₽)", "Цена конкурента (₽)", "Канал", "Разница (₽)", "Статус"]
    ws2.append(headers)

    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    for cell in ws2[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for r in rows:
        if r.get("price_kept"):
            status = "Нет данных"
        elif r.get("is_large_change"):
            status = "Крупное изменение ⚠️"
        else:
            status = "OK ✅"

        ws2.append([
            r.get("display_name", ""),
            r.get("category", ""),
            r.get("calculated_price") or "—",
            r.get("competitor_price") or "—",
            f"@{r['source_channel']}" if r.get("source_channel") else "—",
            r.get("price_delta") or "—",
            status,
        ])
        # Highlight large changes
        if r.get("is_large_change"):
            warn_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
            for cell in ws2[ws2.max_row]:
                cell.fill = warn_fill

    # Auto-fit column widths
    for ws in (ws1, ws2):
        for col in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=10) + 2
            ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len, 40)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _fmt(n: int | None) -> str:
    if n is None:
        return "—"
    return f"{n:,}".replace(",", " ")
