"""Deterministic calculations for the business analyst."""

from calendar import monthrange
import csv
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from io import StringIO
import re

from .dimensions import DIMENSION_ALIASES, requested_dimensions
from .periods import PeriodSelectionError, select_months

MAX_CSV_BYTES = 128 * 1024
MAX_ROWS = 5000
MAX_COLUMNS = 64

# Canonical fields also serve as the machine-readable metric names.
ALIASES = {
    "period": "date month day дата месяц период күн ай кезең",
    "revenue": "sales turnover выручка продажи оборот түсім табыс",
    "cost": "costs expenses затраты расходы себестоимость шығын шығындар",
    "orders": "order_count заказы заказов тапсырыс тапсырыстар",
    "visits": "sessions traffic визиты сеансы посещения трафик кірулер",
    "conversions": "conversion_count конверсии конверсиялар",
    "ad_spend": "advertising_cost расходы_на_рекламу рекламные_расходы жарнама_шығыны",
    "ad_revenue": "advertising_revenue выручка_от_рекламы жарнама_түсімі",
    "currency": "валюта валюта_коды",
}
FIELDS = {alias: key for key, aliases in (ALIASES | DIMENSION_ALIASES).items() for alias in (key, *aliases.split())}
BASE_METRICS = tuple(key for key in ALIASES if key not in {"period", "currency"})
METRIC_INPUTS = {
    "profit": ("revenue", "cost"),
    "margin_pct": ("revenue", "cost"),
    "average_order": ("revenue", "orders"),
    "conversion_pct": ("conversions", "visits"),
    "roas": ("ad_revenue", "ad_spend"),
}
RATIO_DENOMINATORS = {
    "margin_pct": "revenue", "average_order": "orders", "conversion_pct": "visits", "roas": "ad_spend",
}
NONNEGATIVE = {"orders", "visits", "conversions", "ad_spend"}
MISSING = {"", "-", "—", "n/a", "na", "null"}
NUMBER = re.compile(r"[+-]?[0-9]{1,15}(?:[.,][0-9]{1,6})?")
MONTH = re.compile(r"[0-9]{4}-[0-9]{2}")
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class DatasetError(ValueError):
    def __init__(self, code: str, row: int | None = None, *, field: str | None = None):
        super().__init__(code)
        self.code, self.row, self.field = code, row, field


@dataclass
class Aggregate:
    rows: int = 0
    totals: dict[str, Decimal] = field(default_factory=dict)
    present: dict[str, int] = field(default_factory=dict)

    def add(self, values: dict[str, Decimal]) -> None:
        self.rows += 1
        for key, value in values.items():
            self.totals[key] = self.totals.get(key, Decimal(0)) + value
            self.present[key] = self.present.get(key, 0) + 1

    def include(self, other: "Aggregate") -> None:
        self.rows += other.rows
        for key, count in other.present.items():
            self.present[key] = self.present.get(key, 0) + count
            self.totals[key] = self.totals.get(key, Decimal(0)) + other.totals[key]

    def report(self, fields: list[str]) -> dict:
        metrics = {}
        for key in fields:
            count = self.present.get(key, 0)
            metrics[key] = {
                "value": self.totals[key] if count else None,
                "valid_rows": count,
                "missing_rows": self.rows - count,
            }
        for name, formula in {
            "profit": lambda revenue, cost: revenue - cost,
            "margin_pct": lambda revenue, cost: ratio((revenue - cost) * 100, revenue),
            "average_order": ratio,
            "conversion_pct": lambda conversions, visits: ratio(conversions * 100, visits),
            "roas": ratio,
        }.items():
            operands = METRIC_INPUTS[name]
            if all(key in fields for key in operands):
                complete = all(self.present.get(key) == self.rows for key in operands)
                metrics[name] = {"value": formula(*(self.totals[key] for key in operands)) if complete else None}
        return {"rows": self.rows, "metrics": metrics}


def decimal_text(value: Decimal) -> str:
    # Preserve tiny nonzero ratios rather than making them look undefined or zero.
    places = min(-6, value.adjusted() - 2) if value else -6
    value = value.quantize(Decimal(1).scaleb(places), rounding=ROUND_HALF_UP)
    return format(value, "f").rstrip("0").rstrip(".") if value else "0"


def ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return numerator / denominator if denominator > 0 else None


def csv_rows(text: str):
    candidates = []
    invalid_csv = False
    for delimiter in (",", ";", "\t"):
        reader = csv.reader(StringIO(text, newline=""), delimiter=delimiter, strict=True)
        try:
            header = next((row for row in reader if any(cell.strip() for cell in row)), [])
        except csv.Error:
            invalid_csv = True
            continue
        fields = [FIELDS.get(re.sub(r"[\s-]+", "_", item.strip().casefold())) for item in header]
        if any(key in BASE_METRICS for key in fields):
            known = len(fields) - fields.count(None)
            candidates.append(((known, len(fields) > 1, -fields.count(None)), reader, fields))
    if not candidates:
        raise DatasetError("format" if invalid_csv else "columns")
    score, reader, fields = max(candidates, key=lambda candidate: candidate[0])
    if any(candidate_score == score and alternative != fields for candidate_score, _, alternative in candidates):
        raise DatasetError("format")
    return reader, fields


def parse_number(value: str, key: str, row: int) -> Decimal | None:
    value = value.strip()
    if value.casefold() in MISSING:
        return None
    # Spaces can group thousands. Require groups of three so a malformed '1 2' is not 12.
    grouped = r"[+-]?[0-9]{1,3}(?:[ \u00a0\u202f][0-9]{3})+(?:[.,][0-9]{1,6})?"
    if re.fullmatch(grouped, value):
        value = re.sub(r"[ \u00a0\u202f]", "", value)
    if not NUMBER.fullmatch(value):
        raise DatasetError("number", row)
    number = Decimal(value.replace(",", "."))
    if key in NONNEGATIVE and number < 0:
        raise DatasetError("number", row)
    return number


def analyze_csv(raw: str, *, question: str = "", group_by: str | None = None) -> dict:
    if len(raw.encode("utf-8", errors="surrogatepass")) > MAX_CSV_BYTES:
        raise DatasetError("size")
    if "\x00" in raw or re.search(r"[\ud800-\udfff]", raw):
        raise DatasetError("format")
    dimensions = requested_dimensions(question)
    if group_by is not None:
        if group_by not in DIMENSION_ALIASES:
            raise DatasetError("group_dimension")
        dimensions.add(group_by)
    if len(dimensions) > 1:
        raise DatasetError("group_multiple")
    with localcontext(prec=56):
        return aggregate_csv(raw, question, next(iter(dimensions), None))


def aggregate_csv(raw: str, question: str, group_by: str | None) -> dict:
    reader, fields = csv_rows(raw.removeprefix("\ufeff"))
    recognized = [key for key in fields if key]
    if len(fields) > MAX_COLUMNS or len(set(recognized)) != len(recognized):
        raise DatasetError("columns")
    if group_by and group_by not in recognized:
        raise DatasetError("group_missing", field=group_by)
    metrics = [key for key in BASE_METRICS if key in recognized]
    total = Aggregate()
    periods: dict[str, Aggregate] = {}
    dates: dict[str, set[str]] = {}
    kinds: set[str] = set()
    currencies: set[str] = set()
    missing_periods = missing_currency = duplicate_rows = 0
    seen: set[tuple] = set()
    grouped_rows: list[tuple[str | None, str | None, dict[str, Decimal]]] = []
    for row in reader:
        if not any(item.strip() for item in row):
            continue
        if len(row) != len(fields):
            raise DatasetError("width", reader.line_num)
        if total.rows >= MAX_ROWS:
            raise DatasetError("rows")
        row_key = tuple(item.strip() for item in row)
        duplicate_rows += row_key in seen
        seen.add(row_key)
        record = {key: value for key, value in zip(fields, row_key) if key}
        values = {}
        for key in metrics:
            value = parse_number(record[key], key, reader.line_num)
            if value is not None:
                values[key] = value
        total.add(values)
        currency = record.get("currency", "").upper()
        if currency and currency.casefold() not in MISSING:
            if not re.fullmatch(r"[A-Z]{3}", currency):
                raise DatasetError("currency", reader.line_num)
            currencies.add(currency)
        elif "currency" in record:
            missing_currency += 1
        period = record.get("period", "")
        if period.casefold() in MISSING:
            missing_periods += "period" in record
            month = None
        else:
            try:
                if MONTH.fullmatch(period):
                    day = date.fromisoformat(period + "-01")
                    kinds.add("month")
                elif DAY.fullmatch(period):
                    day = date.fromisoformat(period)
                    kinds.add("day")
                else:
                    raise ValueError
            except ValueError:
                raise DatasetError("date", reader.line_num) from None
            month = day.isoformat()[:7]
            periods.setdefault(month, Aggregate()).add(values)
            dates.setdefault(month, set()).add(period)
        if group_by:
            label = record[group_by]
            grouped_rows.append((period if month else None, label or None, values))

    if not total.rows or not total.present:
        raise DatasetError("empty")
    if len(currencies) > 1 or (currencies and missing_currency):
        raise DatasetError("mixed_currency")
    if len(kinds) > 1:
        raise DatasetError("mixed_dates")
    monthly = []
    for month, aggregate in sorted(periods.items()):
        year, number = map(int, month.split("-"))
        complete = "day" not in kinds or len(dates[month]) == monthrange(year, number)[1]
        monthly.append({"period": month, "complete_calendar_month": complete, **aggregate.report(metrics)})
    quality = {
        "duplicate_rows": duplicate_rows, "missing_period_rows": missing_periods,
        "ignored_columns": sum(key is None or (key in DIMENSION_ALIASES and key != group_by) for key in fields),
        "missing_currency_rows": missing_currency,
    }
    try:
        selection = select_months(question, sorted(periods))
    except PeriodSelectionError as error:
        raise DatasetError(str(error)) from None
    scope = {}
    selected = set(selection.months) if selection else set()
    if selection:
        subtotal = Aggregate()
        for month in selection.months:
            subtotal.include(periods[month])
        summary = subtotal.report(metrics)
        monthly = [period for period in monthly if period["period"] in selected]
        scope = {"scope": {"periods": list(selection.months), "dataset_rows": total.rows}}
        if selection.start is not None:
            scope["scope"]["range"] = {
                "start": selection.start, "end": selection.end, "missing_months": selection.missing_months,
                "partial_months": sum(not period["complete_calendar_month"] for period in monthly),
            }
    else:
        summary = total.report(metrics)
    comparison = None if selection and selection.start is not None else compare_months(
        monthly, missing_periods, require_adjacent=not selected)
    breakdown = {}
    groups = []
    if group_by:
        groups = summarize_groups(grouped_rows, metrics, selected, comparison if selected else None, "day" in kinds)
        breakdown = {"breakdown": {"dimension": group_by, "groups": groups}}
    for group in (summary, *monthly, *groups):
        for metric in group["metrics"].values():
            if metric["value"] is not None:
                metric["value"] = decimal_text(metric["value"])
    return {**summary, **scope, **breakdown, "currency": next(iter(currencies), None), "quality": quality,
            "periods": monthly, "comparison": comparison}


def summarize_groups(rows: list, metrics: list[str], selected: set[str], comparison: dict | None,
                     daily: bool) -> list[dict]:
    totals: dict[str | None, Aggregate] = {}
    periods: dict[tuple[str | None, str], Aggregate] = {}
    days: dict[tuple[str | None, str], set[str]] = {}
    pair = (comparison["previous"], comparison["current"]) if comparison else ()
    for period, label, values in rows:
        month = period[:7] if period else None
        if selected and month not in selected:
            continue
        totals.setdefault(label, Aggregate()).add(values)
        if month in pair:
            key = (label, month)
            periods.setdefault(key, Aggregate()).add(values)
            days.setdefault(key, set()).add(period)
    groups = []
    for label in sorted(totals, key=lambda item: (item is None, (item or "").casefold(), item or "")):
        group = {"label": label, **totals[label].report(metrics)}
        if comparison:
            months = []
            for month in pair:
                key = (label, month)
                year, number = map(int, month.split("-"))
                if key in periods:
                    complete = comparison["comparable"] and (not daily or len(days[key]) == monthrange(year, number)[1])
                    months.append({"period": month, "complete_calendar_month": complete, **periods[key].report(metrics)})
            group["comparison"] = compare_months(months, 0, require_adjacent=False) or {
                "previous": pair[0], "current": pair[1], "comparable": False, "changes": {}, "absolute_changes": {},
            }
        groups.append(group)
    return groups


def compare_months(periods: list[dict], missing_period_rows: int, *, require_adjacent: bool = True) -> dict | None:
    if len(periods) < 2:
        return None
    previous, current = periods[-2:]
    before, after = (date.fromisoformat(row["period"] + "-01") for row in (previous, current))
    adjacent = (after.year - before.year) * 12 + after.month - before.month == 1
    comparable = (adjacent or not require_adjacent) and not missing_period_rows and all(
        row["complete_calendar_month"] for row in (previous, current)
    )
    changes = {}
    absolute_changes = {}
    if comparable:
        for key, last in current["metrics"].items():
            first = previous["metrics"][key]
            if first["value"] is None or last["value"] is None or first.get("missing_rows") or last.get("missing_rows"):
                continue
            start, end = first["value"], last["value"]
            if key.endswith("_pct"):
                changes[key] = {"value": decimal_text(end - start), "unit": "percentage_points"}
            elif start > 0:
                changes[key] = {"value": decimal_text((end - start) / start * 100), "unit": "percent"}
            else:
                absolute_changes[key] = decimal_text(end - start)
    return {"previous": previous["period"], "current": current["period"], "comparable": comparable, "changes": changes,
            "absolute_changes": absolute_changes}
