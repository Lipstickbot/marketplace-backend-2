"""Render a computed report in Russian, Kazakh or English."""

from decimal import Decimal, ROUND_HALF_UP
import re

from .metrics import METRIC_INPUTS, RATIO_DENOMINATORS

MONEY_METRICS = {"revenue", "cost", "profit", "average_order", "ad_spend", "ad_revenue"}
GROUP_NAMES = {
    "region": ("регионам", "өңірлер", "region"),
    "channel": ("каналам", "арналар", "channel"),
    "product": ("товарам", "тауарлар", "product"),
    "category": ("категориям товаров", "тауар санаттары", "product category"),
    "sku": ("артикулам", "артикулдар", "SKU"),
}
GROUP_PREVIEW = 12
METRIC_MENTIONS = {
    "revenue": r"(?<!от\s)\bвыручк\w*\b(?!\s+от рекламы)|\brevenue\b(?!\s+per\b)|\bтүсім\w*\b",
    "profit": r"\b(?:прибыл\w*|profit|пайда(?:ны|сы|ның)?)\b",
    "margin_pct": r"\b(?:марж\w*|margins?)\b",
    "average_order": r"\b(?:средн\w*\s+чек\w*|орташа\s+чек\w*|aov|average\s+order\s+value|revenue\s+per\s+order)\b",
    "conversion_pct": r"\b(?:конверси\w*|conversion\s+rate|конверсия\s+деңгей\w*)\b",
    "roas": r"\b(?:roas|return\s+on\s+ad\s+spend)\b",
}
DEFAULT_METRIC = {"profit": "margin_pct", "sales": "average_order", "conversion": "conversion_pct", "marketing": "roas"}
METRIC_NAMES = {
    "revenue": ("Выручка", "Түсім", "Revenue"),
    "cost": ("Затраты", "Шығын", "Costs"),
    "profit": ("Прибыль (выручка минус затраты)", "Пайда (түсім минус шығын)", "Profit (revenue minus costs)"),
    "margin_pct": ("Маржа", "Пайда маржасы", "Profit margin"),
    "orders": ("Заказы", "Тапсырыстар", "Orders"),
    "average_order": ("Средний чек", "Орташа чек", "Average order value"),
    "visits": ("Визиты", "Кірулер", "Visits"),
    "conversions": ("Конверсии", "Конверсиялар", "Conversions"),
    "conversion_pct": ("Конверсия", "Конверсия деңгейі", "Conversion rate"),
    "ad_spend": ("Расходы на рекламу", "Жарнама шығыны", "Ad spend"),
    "ad_revenue": ("Выручка от рекламы", "Жарнама түсімі", "Ad revenue"),
    "roas": ("ROAS", "ROAS", "ROAS"),
}
COPY = {
    "summary": ("Сводка · строк: {rows}", "Қорытынды · жол саны: {rows}", "Summary · {rows} rows"),
    "scope": ("Выбранные месяцы: {months}. Строк в сводке: {rows} из {total}.",
              "Таңдалған айлар: {months}. Қорытындыдағы жол: {rows} / {total}.",
              "Selected months: {months}. Rows in this summary: {rows} of {total}."),
    "range": ("Сводка за {start}–{end} · строк: {rows} из {total}.",
              "{start}–{end} аралығы · жол саны: {rows} / {total}.",
              "{start}–{end} summary · {rows} of {total} rows."),
    "range_missing": ("Месяцев без данных в диапазоне: {n}. Итог охватывает только имеющиеся строки.",
                      "Аралықта дерегі жоқ ай саны: {n}. Қорытындыға бар жолдар ғана кірді.",
                      "Months without data in the range: {n}. The total covers available rows."),
    "range_partial": ("Неполных месяцев в диапазоне: {n}. Учтены только имеющиеся дни.",
                      "Аралықтағы толық емес ай саны: {n}. Бар күндер ғана есептелді.",
                      "Partial months in the range: {n}. Only available days are included."),
    "partial": (" · строк с данными: {valid}/{rows}", " · дерегі бар жолдар: {valid}/{rows}", " · rows with data: {valid}/{rows}"),
    "no_value": ("данных недостаточно", "дерек жеткіліксіз", "insufficient data"),
    "currency_missing": ("Валюта не указана. Значения приведены в единицах источника.", "Валюта көрсетілмеген. Мәндер бастапқы деректің бірлігінде берілді.", "Currency is unspecified. Values are in source units."),
    "duplicates": ("Повторяющиеся строки: {n}. Проверьте их перед принятием решения.", "Қайталанған жолдар: {n}. Шешім қабылдамас бұрын тексеріңіз.", "Repeated rows: {n}. Review them before making a decision."),
    "missing_period": ("Строки без периода: {n}. Они вошли только в общую сводку.", "Кезеңі жоқ жолдар: {n}. Олар тек жалпы қорытындыда есептелді.", "Rows without a period: {n}. They contribute to the overall summary only."),
    "excluded_undated": ("Строк без периода во всём файле: {n}. Они исключены из выбранных месяцев.",
                         "Файлдағы кезеңі жоқ жол саны: {n}. Олар таңдалған айларға кірмейді.",
                         "The file contains {n} undated rows. They are excluded from the selected months."),
    "ignored_columns": ("Колонок вне расчёта: {n}. Итоги не разбиты по этим колонкам.",
                        "Есепке кірмеген баған саны: {n}. Қорытындылар бұл бағандар бойынша бөлінбейді.",
                        "Columns excluded from calculations: {n}. Totals are not broken down by these columns."),
    "months": ("Месячные итоги (последние 6 периодов)", "Айлық қорытындылар (соңғы 6 кезең)", "Monthly totals (last 6 periods)"),
    "groups": ("Итоги по {dimension}", "{dimension} бойынша қорытынды", "Totals by {dimension}"),
    "group_row": ("{label} · строк: {rows}", "{label} · жол саны: {rows}", "{label} · {rows} rows"),
    "group_blank": ("Без значения", "Мәні жоқ", "Missing label"),
    "group_more": ("Показано {shown} из {total} групп. Полная разбивка доступна с --json.",
                   "{total} топтың {shown} тобы көрсетілді. Толық нәтиже --json арқылы қолжетімді.",
                   "Showing {shown} of {total} groups. Use --json for the full breakdown."),
    "group_incomplete": ("Для сравнения этой группы нужны полные данные за оба месяца.",
                         "Бұл топты салыстыру үшін екі айдың да толық дерегі қажет.",
                         "This group needs complete data for both months to compare them."),
    "partial_month": (" · неполный месяц", " · толық емес ай", " · partial month"),
    "comparison": ("Изменение · {previous} → {current}", "Өзгеріс · {previous} → {current}", "Change · {previous} → {current}"),
    "incomparable": ("Для сравнения нужны два соседних полных месяца и даты во всех строках.", "Салыстыру үшін қатар тұрған екі толық ай және барлық жолдарда күн қажет.", "A comparison needs two consecutive complete months and dates for every row."),
    "incomparable_scope": ("Для сравнения указанных месяцев нужны полные данные за каждый месяц и даты во всех строках.",
                           "Таңдалған айларды салыстыру үшін толық айлық дерек және барлық жолда күн қажет.",
                           "The selected comparison needs complete months and dates for every row."),
    "no_change": ("Для расчёта изменений недостаточно сопоставимых значений.", "Өзгерісті есептеуге салыстырмалы мәндер жеткіліксіз.", "There are too few comparable values to calculate changes."),
    "pp": (" п. п.", " п. т.", " pp"),
    "absolute": (" · изменение в единицах показателя", " · көрсеткіш бірлігіндегі өзгеріс", " · change in the metric's units"),
    "commentary": ("Выводы и следующие шаги", "Тұжырымдар және келесі қадамдар", "Findings and next steps"),
    "margin_check": (
        "Выручка выросла, а маржа снизилась. Сравните долю затрат в выручке по товарам и каналам, затем проверьте скидки и возвраты.",
        "Түсім өсті, ал маржа төмендеді. Тауарлар мен арналар бойынша шығынның түсімдегі үлесін салыстырып, жеңілдіктер мен қайтарымдарды тексеріңіз.",
        "Revenue rose while margin fell. Compare the cost share of revenue by product and channel, then check discounts and returns.",
    ),
    "conversion_check": (
        "Конверсия снизилась. Разбейте визиты и конверсии по источникам трафика и найдите этап воронки с наибольшим падением.",
        "Конверсия төмендеді. Кірулер мен конверсияларды трафик көздері бойынша бөліп, ең көп төмендеген сату кезеңін табыңыз.",
        "Conversion fell. Break visits and conversions down by traffic source and find the funnel step with the largest drop.",
    ),
    "roas_check": (
        "ROAS снизился. Сравните расходы и выручку по кампаниям с одинаковым окном атрибуции.",
        "ROAS төмендеді. Атрибуция кезеңі бірдей науқандардың шығыны мен түсімін салыстырыңыз.",
        "ROAS fell. Compare campaign spend and attributed revenue over the same attribution window.",
    ),
    "order_value_check": (
        "Средний чек снизился. Сравните цены, число товаров в заказе и долю скидок по категориям.",
        "Орташа чек төмендеді. Санаттар бойынша бағаны, тапсырыстағы тауар санын және жеңілдіктер үлесін салыстырыңыз.",
        "Average order value fell. Check prices, items per order and discount share by category.",
    ),
    "quality_check": (
        "Совпадающих строк: {duplicates}. Пропуски указаны рядом с каждым показателем.",
        "Дәл қайталанған жолдар: {duplicates}. Бос мәндер әр көрсеткіштің жанында берілген.",
        "Identical rows: {duplicates}. Missing values are reported beside each metric.",
    ),
    "missing_inputs": (
        "Для «{metric}» добавьте в таблицу колонки {fields}.",
        "«{metric}» үшін кестеге {fields} бағандарын қосыңыз.",
        "To calculate {metric}, add the following columns: {fields}.",
    ),
    "missing_values": ("Для «{metric}» заполните пропуски в колонках {fields}.",
                       "«{metric}» үшін {fields} бағандарындағы бос мәндерді толтырыңыз.",
                       "To calculate {metric}, fill missing values in {fields}."),
    "nonpositive_denominator": (
        "Для «{metric}» итог по колонке {field} должен быть больше нуля.",
        "«{metric}» үшін {field} бағанының жиынтығы нөлден үлкен болуы керек.",
        "To calculate {metric}, the total in {field} must be greater than zero.",
    ),
    "missing_period_column": (
        "Для сравнения заполните колонку period. Укажите соседние месяцы или даты с одинаковым охватом.",
        "Салыстыру үшін period бағанын толтырыңыз. Қатар тұрған айларды немесе қамтуы бірдей күндерді көрсетіңіз.",
        "Provide a period column with consecutive months or daily data with comparable coverage.",
    ),
}


def requested_metrics(question: str) -> tuple[str, ...]:
    found = []
    for key, pattern in METRIC_MENTIONS.items():
        match = re.search(pattern, question, re.I)
        if match:
            found.append((match.start(), key))
    return tuple(key for _, key in sorted(found))


def language_index(language: str) -> int:
    return ("ru", "kk", "en").index(language)


def copy(key: str, lang: str, **kwargs) -> str:
    return COPY[key][language_index(lang)].format(**kwargs)


def metric_label(key: str, lang: str) -> str:
    return METRIC_NAMES[key][language_index(lang)]


def order(keys, focus):
    return dict.fromkeys([*(key for key in focus if key in keys), *keys])


def human_number(value: str, lang: str) -> str:
    whole, mark, fraction = value.partition(".")
    if not mark:
        return value
    if abs(Decimal(value)) < Decimal("0.01"):
        return whole + ("." if lang == "en" else ",") + fraction
    # Bound quantize precision independently of the caller's Decimal context.
    if len(whole) > 24:
        return value if lang == "en" else value.replace(".", ",")
    rounded = format(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
    rounded = rounded.rstrip("0").rstrip(".")
    return rounded if lang == "en" else rounded.replace(".", ",")


def render_metrics(report: dict, lang: str, *, condensed: bool = False, currency: str | None = None,
                   focus: tuple = ()) -> list[str]:
    lines = []
    for key in order(report["metrics"], focus):
        metric = report["metrics"][key]
        value = metric["value"]
        missing = copy("partial", lang, valid=metric["valid_rows"], rows=report["rows"]) if metric.get("missing_rows") else ""
        if value is None:
            label = copy("no_value", lang)
        else:
            unit = "%" if key.endswith("_pct") else "×" if key == "roas" else ""
            if currency and key in MONEY_METRICS:
                unit = " " + currency
            label = human_number(value, lang) + unit
        item = f"{metric_label(key, lang)}: {label}{missing}"
        lines.append(item if condensed else "• " + item)
    return lines


def render_changes(comparison: dict, lang: str, currency: str | None, focus: tuple) -> list[str]:
    lines = []
    for key in order(comparison["changes"], focus):
        change = comparison["changes"][key]
        value = change["value"]
        sign = "-" if value.startswith("-") else "+" if value != "0" else ""
        unit = copy("pp", lang) if change["unit"] == "percentage_points" else "%"
        lines.append(f"{metric_label(key, lang)}: {sign}{human_number(value.lstrip('-'), lang)}{unit}")
    for key in order(comparison["absolute_changes"], focus):
        value = comparison["absolute_changes"][key]
        sign = "+" if Decimal(value) > 0 else ""
        unit = (" " + currency) if currency and key in MONEY_METRICS else "×" if key == "roas" else ""
        lines.append(f"{metric_label(key, lang)}: {sign}{human_number(value, lang)}{unit}{copy('absolute', lang)}")
    return lines


def render_report(report: dict, lang: str, *, focus: tuple = (), findings: str = "") -> str:
    currency = report["currency"]
    scope = report.get("scope")
    interval = scope.get("range") if scope else None
    if interval:
        lines = [copy("range", lang, **interval, rows=report["rows"], total=scope["dataset_rows"])]
        if interval["missing_months"]:
            lines.append(copy("range_missing", lang, n=interval["missing_months"]))
        if interval["partial_months"]:
            lines.append(copy("range_partial", lang, n=interval["partial_months"]))
    elif scope:
        lines = [copy("scope", lang, months=", ".join(scope["periods"]), rows=report["rows"], total=scope["dataset_rows"])]
    else:
        lines = [copy("summary", lang, rows=report["rows"])]
    lines.extend(render_metrics(report, lang, currency=currency, focus=focus))
    quality = report["quality"]
    if not currency and report["metrics"].keys() & {"revenue", "cost", "ad_spend", "ad_revenue"}:
        lines.append(copy("currency_missing", lang))
    if quality["duplicate_rows"]:
        lines.append(copy("duplicates", lang, n=quality["duplicate_rows"]))
    if quality["missing_period_rows"]:
        lines.append(copy("excluded_undated" if scope else "missing_period", lang, n=quality["missing_period_rows"]))
    if quality["ignored_columns"]:
        lines.append(copy("ignored_columns", lang, n=quality["ignored_columns"]))
    if breakdown := report.get("breakdown"):
        groups = breakdown["groups"]
        lines.extend(("", copy("groups", lang, dimension=GROUP_NAMES[breakdown["dimension"]][language_index(lang)])))
        for group in groups[:GROUP_PREVIEW]:
            label = group["label"]
            if label is None:
                label = copy("group_blank", lang)
            else:
                label = "".join(char if char.isprintable() else ascii(char)[1:-1] for char in label)
            heading = copy("group_row", lang, label=label, rows=group["rows"])
            lines.append(" · ".join((heading, *render_metrics(group, lang, condensed=True, currency=currency, focus=focus))))
            if change := group.get("comparison"):
                detail = " · ".join(render_changes(change, lang, currency, focus)) if change["comparable"] else copy("group_incomplete", lang)
                lines.append("  " + copy("comparison", lang, **change) + " · " + (detail or copy("no_change", lang)))
        if len(groups) > GROUP_PREVIEW:
            lines.append(copy("group_more", lang, shown=GROUP_PREVIEW, total=len(groups)))
    if report["periods"]:
        lines.extend(("", copy("months", lang)))
        for period in report["periods"][-6:]:
            label = period["period"] + ("" if period["complete_calendar_month"] else copy("partial_month", lang))
            lines.append(label + " · " + " · ".join(render_metrics(period, lang, condensed=True, currency=currency, focus=focus)))
    if comparison := report["comparison"]:
        lines.extend(("", copy("comparison", lang, **comparison)))
        if not comparison["comparable"]:
            lines.append(copy("incomparable_scope" if scope else "incomparable", lang))
        elif not (comparison["changes"] or comparison["absolute_changes"]):
            lines.append(copy("no_change", lang))
        lines.extend("• " + line for line in render_changes(comparison, lang, currency, focus))
    if findings:
        lines.extend(("", copy("commentary", lang), findings))
    return "\n".join(lines)


def next_steps(report: dict, lang: str, *, topics: tuple[str, ...] = (), requested: tuple[str, ...] = ()) -> str:
    changes = (report["comparison"] or {}).get("changes", {})
    revenue = changes.get("revenue", {}).get("value", "0")
    falls = {key for key, change in changes.items() if change["value"].startswith("-")}
    checks = {
        "profit": ("margin_check", revenue != "0" and not revenue.startswith("-") and "margin_pct" in falls),
        "sales": ("order_value_check", "average_order" in falls),
        "conversion": ("conversion_check", "conversion_pct" in falls),
        "marketing": ("roas_check", "roas" in falls),
    }
    findings = []
    for topic in topics or checks:
        if topic in checks:
            key, applies = checks[topic]
            if applies:
                findings.append(copy(key, lang))
        elif topic == "quality":
            findings.append(copy("quality_check", lang, duplicates=report["quality"]["duplicate_rows"]))
        elif topic == "periods" and not report["periods"]:
            findings.append(copy("missing_period_column", lang))

    metrics = report["metrics"]
    for metric in requested or tuple(DEFAULT_METRIC[topic] for topic in topics if topic in DEFAULT_METRIC):
        fields = METRIC_INPUTS.get(metric, (metric,))
        missing = [field for field in fields if field not in metrics]
        label = metric_label(metric, lang)
        if missing:
            findings.append(copy("missing_inputs", lang, metric=label, fields=", ".join(missing)))
        elif metrics[metric]["value"] is None:
            incomplete = [field for field in fields if metrics[field].get("missing_rows")]
            if incomplete:
                findings.append(copy("missing_values", lang, metric=label, fields=", ".join(incomplete)))
            elif denominator := RATIO_DENOMINATORS.get(metric):
                findings.append(copy("nonpositive_denominator", lang, metric=label, field=denominator))
    return "\n".join("• " + item for item in findings)
