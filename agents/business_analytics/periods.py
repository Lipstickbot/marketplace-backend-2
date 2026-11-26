"""Resolve months explicitly named in a question against a CSV's available periods."""

import re
from dataclasses import dataclass

# Inflected Kazakh month names have a finite set of case endings.
# A prefix match would also read words like «маусымдық» (seasonal) as June.
KAZAKH_CASE = (
    r"(?:да|де|та|те|дан|ден|тан|тен|нан|нен|ға|ге|қа|ке|дың|дің|тың|тің|ның|нің|"
    r"ды|ді|ты|ті|ны|ні|ы|і|ына|іне|ында|інде|ымен|імен|мен|бен|пен)?"
)
MONTH_NAMES = tuple(f"{russian}|{kazakh}{KAZAKH_CASE}|{english}" for russian, kazakh, english in (
    (r"январ(?:ь|я|е|ю|[её]м)", "қаңтар", r"jan(?:uary)?"),
    (r"феврал(?:ь|я|е|ю|[её]м)", "ақпан", r"feb(?:ruary)?"),
    (r"март(?:а|е|у|ом)?", "наурыз", r"mar(?:ch)?"),
    (r"апрел(?:ь|я|е|ю|[её]м)", "сәуір", r"apr(?:il)?"),
    (r"ма(?:й|я|е|ю|ем)", "мамыр", "may"),
    (r"июн(?:ь|я|е|ю|ем)", "маусым", r"jun(?:e)?"),
    (r"июл(?:ь|я|е|ю|ем)", "шілде", r"jul(?:y)?"),
    (r"август(?:а|е|у|ом)?", "тамыз", r"aug(?:ust)?"),
    (r"сентябр(?:ь|я|е|ю|[её]м)", "қыркүйек", r"sep(?:t(?:ember)?)?"),
    (r"октябр(?:ь|я|е|ю|[её]м)", "қазан", r"oct(?:ober)?"),
    (r"ноябр(?:ь|я|е|ю|[её]м)", "қараша", r"nov(?:ember)?"),
    (r"декабр(?:ь|я|е|ю|[её]м)", "желтоқсан", r"dec(?:ember)?"),
))
MONTH_BY_NAME = tuple(re.compile(name, re.I) for name in MONTH_NAMES)
NAMED_MONTH = re.compile(
    r"\b(?:(?P<leading_year>[0-9]{4})\s+(?:жыл(?:ғы)?\s+)?)?(?P<name>" + "|".join(MONTH_NAMES)
    + r")\b(?:\.(?!\.))?(?:\s+(?P<trailing_year>[0-9]{4})(?![0-9]|-[0-9]|\s+жыл(?:ғы)?\b))?",
    re.I,
)
ISO_PERIOD = re.compile(r"(?<!\w)([0-9]{4})-([0-9]{2})(?:-([0-9]{2}))?(?![\w-])")
ISO_DASH_RANGE = re.compile(r"(?<![\w-])([0-9]{4}-[0-9]{2})-([0-9]{4}-[0-9]{2})(?![\w-])")
TIME_PREPOSITION = re.compile(r"\b(?:in|for|from|to|with|against|during|through)\s+$", re.I)
MONTH_PAIR = re.compile(r"^\s*(?:(?:and|with|vs\.?|to|through|және|мен|бен|пен)\s+|[–—-]\s*|\.\.\s*)", re.I)
LIST_SEPARATOR = re.compile(r"\s*(?:,|and|with|vs\.?|және|мен|бен|пен)\s*", re.I)
MONTH_TAIL = re.compile(r"^\s*(?:$|[,.!?;]|(?:by|for|revenue|sales|margin|results|figures)\b)", re.I)
MONTH_METRIC = re.compile(
    r"^\s+(?:(?:total|gross|net)\s+)?(?:revenue|sales|margin|results|figures|profit|orders)\b"
    r"(?=\s*(?:$|[,.!?;]|\b(?:by|in|for|report|summary|vs\.?)\b))",
    re.I,
)
RANGE_CONNECTOR = re.compile(r"\s*(?:по|до|to|through|\.\.|[–—-])\s*", re.I)
COMPARE_CUE = re.compile(r"\b(?:compare|comparison|difference)\b", re.I)
AMBIGUOUS_ENGLISH = {"may", "mar", "march", "aug", "august"}
AMBIGUOUS_KAZAKH = {"маусым", "қазан"}
AMBIGUOUS_MONTHS = AMBIGUOUS_ENGLISH | AMBIGUOUS_KAZAKH
MonthReference = tuple[int, int, str | None, str]


class PeriodSelectionError(ValueError):
    """An explicit period could not be matched without guessing."""


@dataclass(frozen=True)
class MonthSelection:
    months: tuple[str, ...]
    start: str | None = None
    end: str | None = None
    missing_months: int = 0


def month_index(month: str) -> int:
    year, number = map(int, month.split("-"))
    return year * 12 + number


def is_range_connector(question: str, left: MonthReference, right: MonthReference) -> bool:
    connector = question[left[1]:right[0]]
    if connector.strip().casefold() == "to":
        before = question[:left[0]]
        if COMPARE_CUE.search(before) and not re.search(r"\bfrom\s+$", before, re.I):
            return False
    return bool(RANGE_CONNECTOR.fullmatch(connector)
                or (not connector.strip() and re.match(r"\s+дейін\b", question[right[1]:], re.I)))


def select_months(question: str, available: list[str]) -> MonthSelection | None:
    question = ISO_DASH_RANGE.sub(r"\1 – \2", question)
    references: list[MonthReference] = []
    for match in ISO_PERIOD.finditer(question):
        year, month, day = match.groups()
        if day is not None or year == "0000" or not 1 <= int(month) <= 12:
            raise PeriodSelectionError("period_format")
        references.append((*match.span(), year, month))
    for match in NAMED_MONTH.finditer(question):
        leading, name, trailing = match.groups()
        year = leading or trailing
        word = name.casefold()
        if word in AMBIGUOUS_MONTHS and year is None:
            before, after = question[:match.start()], question[match.end():]
            paired = MONTH_PAIR.match(after)
            follows_month = any(
                end <= match.start() and (LIST_SEPARATOR.fullmatch(question[end:match.start()])
                                          or RANGE_CONNECTOR.fullmatch(question[end:match.start()]))
                for _, end, _, _ in references
            )
            has_neighbor = (paired and NAMED_MONTH.match(after, paired.end())) or (follows_month and MONTH_TAIL.match(after))
            if word in AMBIGUOUS_ENGLISH:
                has_context = TIME_PREPOSITION.search(before) or MONTH_METRIC.match(after)
            else:
                has_context = re.match(r"\s+ай\w*\b", after, re.I)
            if not (has_neighbor or has_context):
                continue
        month = next(index for index, pattern in enumerate(MONTH_BY_NAME, 1) if pattern.fullmatch(name))
        if year == "0000":
            raise PeriodSelectionError("period_format")
        references.append((*match.span(), year, f"{month:02d}"))

    references.sort()
    if not references:
        return None
    ranges = sum(is_range_connector(question, left, right) for left, right in zip(references, references[1:]))
    if ranges and len(references) != 2:
        raise PeriodSelectionError("period_limit")
    selections = []
    for _, _, year, number in references:
        if ranges and year is not None:
            selections.append(f"{year}-{number}")
            continue
        candidates = [month for month in available if month[5:] == number and (year is None or month[:4] == year)]
        if not candidates:
            raise PeriodSelectionError("period_missing")
        if len(candidates) > 1:
            raise PeriodSelectionError("period_ambiguous")
        selections.append(candidates[0])
    if ranges:
        start, end = selections
        if start > end:
            raise PeriodSelectionError("period_order")
        covered = tuple(sorted(month for month in available if start <= month <= end))
        if not covered:
            raise PeriodSelectionError("period_missing")
        return MonthSelection(covered, start, end, month_index(end) - month_index(start) + 1 - len(covered))
    selections = set(selections)
    if len(selections) > 2:
        raise PeriodSelectionError("period_limit")
    return MonthSelection(tuple(sorted(selections)))
