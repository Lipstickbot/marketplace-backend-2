"""Offline business analyst for operational KPIs and CSV reports."""

import csv
from dataclasses import dataclass
import re
from typing import Literal

from .guide import DETAILED_TOPICS, explain
from .intent import active_question, trained_classifier
from .metrics import DatasetError, analyze_csv
from .report import language_index, next_steps, render_report, requested_metrics

Language = Literal["auto", "ru", "kk", "en"]
FENCE = re.compile(r"^```(?:csv|tsv)[ \t]*\r?\n(.*?)^[ \t]*```[ \t]*\r?$", re.M | re.S | re.I)

FOCUS = {
    "profit": ("profit", "margin_pct", "revenue", "cost"),
    "sales": ("revenue", "orders", "average_order"),
    "conversion": ("conversion_pct", "visits", "conversions"),
    "marketing": ("roas", "ad_spend", "ad_revenue"),
}


@dataclass(frozen=True)
class Analysis:
    language: str
    intent: str | None
    answer: str
    data: dict | None = None
    topics: tuple[str, ...] = ()


def choose_language(question: str, language: Language) -> str:
    if language != "auto":
        language_index(language)
        return language
    if re.search(r"[әғқңөұүһі]", question, re.I):
        return "kk"
    return "ru" if re.search(r"[а-яё]", question, re.I) or not re.search(r"[a-z]", question, re.I) else "en"


def analyze(question: str = "", *, csv_text: str | None = None, language: Language = "auto",
            group_by: str | None = None) -> Analysis:
    """Analyze one question and an optional CSV/TSV, supplied directly or in a fenced block."""
    if len(question) > 8000:
        raise DatasetError("question_size")
    blocks = list(FENCE.finditer(question))
    if len(blocks) > 1 or (blocks and csv_text is not None):
        raise DatasetError("multiple")
    if blocks:
        csv_text = blocks[0][1]
        question = FENCE.sub("", question)
    question = question.strip()
    lang = choose_language(question, language)
    topics = trained_classifier().predict_topics(question) if question else ()
    intent = topics[0] if topics else None
    if csv_text is None:
        if group_by is not None:
            raise DatasetError("group_requires_data")
        return Analysis(lang, intent, explain(topics, language_index(lang)), topics=topics)
    scoped_question, _ = active_question(question)
    try:
        data = analyze_csv(csv_text, question=scoped_question, group_by=group_by)
    except csv.Error as error:
        raise DatasetError("format") from error
    requested = requested_metrics(scoped_question)
    findings = next_steps(data, lang, topics=topics, requested=requested)
    focus = tuple(dict.fromkeys((*requested, *(metric for topic in topics for metric in FOCUS.get(topic, ())))))
    answer = render_report(data, lang, focus=focus, findings=findings)
    detailed = tuple(topic for topic in topics if topic in DETAILED_TOPICS)
    if detailed:
        answer += "\n\n" + explain(detailed, language_index(lang))
    return Analysis(lang, intent, answer, data, topics)
