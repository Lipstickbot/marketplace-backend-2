"""A multilingual intent classifier trained from the bundled labeled examples."""

from collections import Counter
from functools import lru_cache
from heapq import nlargest
import json
from math import log, sqrt
from pathlib import Path
import re
import unicodedata

WORDS = re.compile(r"[^\W\d_]+")
CLAUSE_BREAK = re.compile(
    r"[;!?\n]+|(?<!\.)\.(?!\.)|\b(?:а\s+также|почему\s+ещ[её]|затем|плюс|потом|но|и|а|"
    r"сонымен\s+қатар|содан\s+кейін|сосын|бірақ|және|"
    r"as\s+well\s+as|and\s+then|also|then|but|and(?!\s+(?:targets?|goals?)\b))\b",
    re.I,
)
CONTEXT_QUESTION = re.compile(r"^(?:what|how|why|can|could|как|почему|что|қалай|неге|не)\b.*\b(?:it|that|this|them|это|этим|осы|бұл)$", re.I)
EXCLUDED_CLAUSE = re.compile(
    r"^(?:please\s+)?(?:ignore|skip|exclude|do\s+not\s+(?:calculate|include)|"
    r"исключи|пропусти|не\s+(?:считай|учитывай|за))\b|"
    r"\bне\s+(?:нуж\w*|требуется)\s*,?$|\b(?:есептеме\w*|қажет\s+емес)\s*,?$",
    re.I,
)
DIRECT_REVENUE = re.compile(
    r"^(?:(?:рассчитай|посчитай|покажи|сколько|total|calculate|show|түсімді\s+есепте)\s+)?"
    r"(?:общ\w*\s+)?(?:выручк\w*|revenue|түсім\w*)\s*[.!?]*$",
    re.I,
)

TERMS = {
    "profit": (
        r"марж\w*|прибыл\w*|рентабельност\w*|себестоимост\w*|издерж\w*|"
        r"валов\w*\s+доход\w*|"
        r"пайда(?:ның|ны|ға|сы|сын|сынан|мен|дан|да|лар)?|пайдалылы\w*|табыстылық\w*|өзіндік\s+құн\w*|"
        r"margins?|profit\w*|unit\s+economics|cost\s+of\s+goods|earnings"
    ),
    "sales": (
        r"aov|средн\w*\s+чек\w*|объ[её]м\w*\s+(?:продаж\w*|покуп\w*|заказ\w*)|ассортимент\w*|"
        r"орташа\s+чек\w*|сатып\s+алу\w*\s+көлем\w*|тауар\s+құрам\w*|"
        r"order\s+values?|basket\s+(?:mix|size|value)|per\s+(?:order|basket|purchase)"
    ),
    "conversion": (
        r"конверси\w*|воронк\w*|до\s+оплат\w*|на\s+странице\s+оплат\w*|"
        r"оформлени\w*\s+заказ\w*|оплачива\w*\s+заказ\w*|"
        r"тапсырыс\w*\s+өту\w*|төлем\w*\s+(?:дейін|бет\w*|жет\w*)|"
        r"conversions?|funnels?|checkout|drop[ -]?off|before\s+payment|(?:cart|basket)\s+abandon\w*"
    ),
    "marketing": (
        r"roas|атрибуц\w*|рекламн\w*\s+(?:сет\w*|кампани\w*|объявлен\w*|расход\w*)|"
        r"окупаемост\w*\s+реклам\w*|от\s+реклам\w*|"
        r"атрибуци\w*|жарнама\w*\s+(?:шығын\w*|жұмса\w*|арна\w*|жел\w*)|"
        r"ad\s+(?:spend|returns?|network\w*|platform\w*)|paid\s+campaign\w*|attribut\w*\s+(?:sales|revenue)"
    ),
    "quality": (
        r"дубл\w*|дубликат\w*|пуст\w*\s+(?:пол\w*|запис\w*|значен\w*|ячей\w*)|"
        r"свер\w*\s+(?:данны\w*|строк\w*|сумм\w*)|"
        r"қайталан\w*\s+(?:жол\w*|операци\w*)|валюта\w*\s+аралас\w*|бастапқы\s+жүйе\w*|"
        r"duplicates?|repeated\s+(?:transactions?|invoices?|order\s+ids?|records?)|"
        r"(?:transaction|order|record)\s+(?:ids?|identifiers?)\b[^.!?;]{0,35}\b(?:both|across)|"
        r"missing\s+(?:values?|records?|entries)|reconcil\w*|source\s+(?:system|ledger)"
    ),
    "report": (
        r"дашборд\w*|структур\w*\s+сводк\w*|отч[её]т\w*\s+(?:для\s+)?руководител\w*|"
        r"басқару\s+панел\w*|апталық\s+есеп\w*|"
        r"dashboard\w*|scorecard\w*|executive\s+(?:brief\w*|summary|report\w*)"
    ),
    "periods": (
        r"сезонност\w*|неполн\w*\s+(?:месяц\w*|период\w*|недел\w*)|"
        r"баз\w*\s+(?:сравнен\w*|для\s+(?:месяц\w*|недел\w*|период\w*)|для\s+\w+\s+недел\w*)|"
        r"сопоставим\w*\s+период\w*|"
        r"маусымдық|толық\s+емес\s+(?:ай\w*|кезең\w*|қаңтар\w*|ақпан\w*|қазан\w*|қараша\w*|желтоқсан\w*)|"
        r"seasonalit\w*|partial\s+(?:month\w*|period\w*|week\w*|january|february|march|april|may|june|july|august|september|october|november|december)|"
        r"year[ -]over[ -]year|month[ -]over[ -]month"
    ),
    "retention": (
        r"когорт\w*|отток\w*|удержани\w*|повторн\w*\s+покуп\w*|возврат\w*\s+клиент\w*|"
        r"(?:втор\w*|повторн\w*)\s+(?:заказ\w*|оплат\w*)|"
        r"клиент\w*\s+(?:сақтал\w*|қайту\w*|кету\w*)|жазылым\w*\s+(?:тоқтат\w*|ұзарт\w*)|"
        r"churn\w*|retention|cohorts?|(?:sign[ -]?up|registration)\s+groups?|repeat\s+purchase\w*|"
        r"(?:subscriber|customer)\s+attrition"
    ),
    "inventory": (
        r"оборачиваемост\w*\s+(?:запас\w*|товар\w*)|(?:складск\w*|товарн\w*)\s+остатк\w*|"
        r"страхов\w*\s+запас\w*|неликвид\w*|дефицит\w*\s+товар\w*|хватит\s+(?:товар\w*|запас\w*)|"
        r"тауар\w*\s+қор\w*|қойма\w*\s+қалдық\w*|(?:артық|сақтандыру)\s+қор\w*|"
        r"inventory\s+(?:turnover|days?|levels?|coverage|on\s+hand)|stockouts?|out\s+of\s+stock|dead\s+stock|replenish\w*"
    ),
    "plan": (
        r"план[ /–-]факт\w*|планов\w*\s+объ[её]м\w*|бюджетн\w*\s+отклонени\w*|"
        r"фактическ\w*\s+(?:продаж\w*|выручк\w*|расход\w*)\s+с\s+бюджет\w*|"
        r"(?:выполнени\w*|отклонени\w*\s+от|перерасход\w*|сверх|ниже|выше)\s+бюджет\w*|"
        r"жоспар[ /–-]факт\w*|бюджет\w*\s+(?:ауытқу\w*|асы\w*)|жоспар\w*\s+орындал\w*|"
        r"budget\s+variance|over\s+budget|actual\s+(?:versus|vs\.?)\s+(?:plan|budget)|"
        r"target\s+attainment|spending\s+targets?|actual\s+\w+\s+and\s+target"
    ),
    "experiment": (
        r"(?:a|а)\s*[/–-]\s*(?:b|б)\s*(?:тест\w*|сына\w*|experiment\w*|test\w*)?|"
        r"рандомизац\w*|статистическ\w*\s+значим\w*|доверительн\w*\s+интервал\w*|"
        r"контрольн\w*\s+групп\w*|сенімділік\s+аралы\w*|бақылау\s+тоб\w*|"
        r"random(?:ly\s+assigned|ized|ised)|control\s+group\w*|statistical\s+significance|"
        r"sample\s+size|minimum\s+detectable\s+effect"
    ),
    "unit_economics": (
        r"юнит[ -]экономик\w*|безубыточност\w*|безубыточн\w*\s+объ[её]м\w*|"
        r"маржинальн\w*\s+доход\w*|стоимост\w*\s+привлечени\w*|"
        r"шығынсыздық\w*|клиент\w*\s+тарту\s+(?:құн\w*|шығын\w*)|"
        r"break[ -]even|cac|ltv|acquisition\s+cost\w*|cac\s+payback|contribution\s+per\s+(?:order|unit)"
    ),
    "operations": (
        r"sla|срок\w*\s+доставк\w*|доставк\w*\s+вовремя|опаздыва\w*\s+с\s+доставк\w*|"
        r"опоздани\w*\s+\w*\s*доставк\w*|задерж\w*\s+(?:доставк\w*|курьер\w*)|"
        r"комплектаци\w*|просрочен\w*\s+отправ\w*|жеткізу\w*\s+(?:кешіг\w*|мерзім\w*|жиіліг\w*)|"
        r"уақытында\s+жеткіз\w*|on[ -]time\s+deliver\w*|late\s+(?:deliver\w*|shipment\w*)|"
        r"promised\s+(?:delivery|dates?|deadline\w*)|delivery\s+(?:delay\w*|deadline\w*)"
    ),
    "other": (
        r"(?:хочу|дай|посоветуй|подскажи)\s+(?:мне\s+)?рецепт\w*|"
        r"(?:напиши|сочини|расскажи|придумай)(?:\s+\w+){0,2}\s+(?:сказк\w*|анекдот\w*|песн\w*)|"
        r"переведи\b[^.!?]{0,80}\bслоган\w*|ертегі|"
        r"translate\b[^.!?]{0,80}\b(?:taglines?|slogans?|ad\s+copy)|"
        r"bedtime\s+stor\w*|pancake\w*|fairy\s+tal\w*|regardless\s+of\s+the\s+numbers|"
        r"(?:какие|какую)\s+акци\w*\s+(?:покуп\w*|куп\w*)|(?:which|what)\s+(?:stock\w*|shares?)\s+should\s+i\s+buy"
    ),
}
TERM_PATTERNS = {topic: re.compile(r"\b(?:" + terms + r")\b", re.I) for topic, terms in TERMS.items()}


def features(text: str) -> Counter:
    counts = Counter()
    words = WORDS.findall(unicodedata.normalize("NFKC", text).casefold().replace("ё", "е"))
    for word in words:
        if len(word) < 2:
            continue
        counts["word:" + word] += 3
        padded = "^" + word + "$"
        for size in (3, 4):
            counts.update(padded[i:i + size] for i in range(len(padded) - size + 1))
    counts.update({f"{left} {right}": 2 for left, right in zip(words, words[1:])})
    return counts


def unit(vector: dict) -> dict:
    length = sqrt(sum(weight * weight for weight in vector.values()))
    return {key: value / length for key, value in vector.items()} if length else {}


def similarity(query: dict, target: dict) -> float:
    return sum(weight * target.get(key, 0) for key, weight in query.items())


def literal_topics(text: str) -> dict[str, int]:
    return {topic: len(matches) for topic, pattern in TERM_PATTERNS.items() if (matches := pattern.findall(text))}


def question_clauses(text: str) -> list[str]:
    clauses = []
    for fragment in CLAUSE_BREAK.split(text):
        pieces = [piece.strip() for piece in fragment.split(",") if piece.strip()]
        if len(pieces) > 1 and all(literal_topics(piece) or EXCLUDED_CLAUSE.search(piece) for piece in pieces):
            clauses.extend(pieces)
        elif fragment.strip():
            clauses.append(fragment.strip())
    return clauses


def active_question(question: str) -> tuple[str, list[str]]:
    clauses = question_clauses(question)
    active = [clause for clause in clauses
              if not EXCLUDED_CLAUSE.search(clause) and "other" not in literal_topics(clause)]
    return (question if len(active) == len(clauses) else " ".join(active)), active


class IntentClassifier:
    def __init__(self, examples: dict[str, dict[str, list[str]]]):
        samples = [(intent, features(text)) for intent, languages in examples.items()
                   for prompts in languages.values() for text in prompts]
        frequencies = Counter(key for _, sample in samples for key in sample)
        self.weights = {key: 1 + log((1 + len(samples)) / (1 + count))
                        for key, count in frequencies.items()}
        self.samples: dict[str, list[dict]] = {intent: [] for intent in examples}
        prototypes = {intent: Counter() for intent in examples}
        for intent, sample in samples:
            vector = self.vector(sample)
            self.samples[intent].append(vector)
            prototypes[intent].update(vector)
        self.prototypes = {intent: unit(values) for intent, values in prototypes.items()}

    def vector(self, counts: Counter) -> dict:
        return unit({key: sqrt(count) * self.weights[key]
                     for key, count in counts.items() if key in self.weights})

    def rank(self, question: str, terms: dict[str, int] | None = None) -> list[tuple[float, str]]:
        terms = literal_topics(question) if terms is None else terms
        counts = features(question)
        query = self.vector(counts)
        recognized = sum(count for key, count in counts.items() if key in query)
        if not terms and (recognized < 4 or recognized < sum(counts.values()) * 0.2):
            return []
        scores = []
        for intent, prototype in self.prototypes.items():
            closest = nlargest(3, (similarity(query, example) for example in self.samples[intent]))
            local_score = 0.60 * closest[0] + 0.40 * sum(closest) / len(closest)
            global_score = similarity(query, prototype)
            term_score = 0.08 + 0.03 * min(terms[intent] - 1, 2) if intent in terms else 0
            scores.append((0.65 * local_score + 0.35 * global_score + term_score, intent))
        return sorted(scores, reverse=True)

    def predict(self, question: str) -> str | None:
        """Return the leading topic for callers that need a single label."""
        topics = self.predict_topics(question)
        return topics[0] if topics else None

    def predict_topics(self, question: str) -> tuple[str, ...]:
        question, clauses = active_question(question)
        if DIRECT_REVENUE.fullmatch(question):
            return ("sales",)
        terms = literal_topics(question)
        scores = self.rank(question, terms)
        if not scores or scores[0][1] == "other" or "other" in terms:
            return ()
        best, primary = scores[0]
        first = primary if best >= 0.12 and best - scores[1][0] >= 0.012 else None
        full_scores = {label: score for score, label in scores}

        labels = []
        if len(clauses) > 1:
            for clause in clauses:
                hints = literal_topics(clause)
                if not hints and (len(WORDS.findall(clause)) < 4 or CONTEXT_QUESTION.fullmatch(clause)):
                    continue
                ranked = self.rank(clause, hints)
                if not ranked:
                    continue
                score, label = ranked[0]
                # A single domain phrase can disambiguate a closely ranked paraphrase.
                named = [topic for topic in hints if topic != "other"]
                if label not in hints and len(named) == 1:
                    explicit = named[0]
                    explicit_score = next(value for value, topic in ranked if topic == explicit)
                    if label != "other" and explicit_score >= 0.18 and score - explicit_score <= 0.035:
                        labels.append(explicit)
                        continue
                if len(named) == 1 and hints[named[0]] == 1 and len(WORDS.findall(clause)) <= 2:
                    labels.append(named[0])
                    continue
                named_topic = label in hints and score >= 0.14 and score - ranked[1][0] >= 0.012
                inferred_topic = score >= 0.22 and score - ranked[1][0] >= 0.055 and full_scores[label] >= best * 0.55
                if label != "other" and (named_topic or inferred_topic):
                    labels.append(label)

        distinct = tuple(dict.fromkeys(labels))
        if len(distinct) < 2:
            if first:
                return (first,)
            return distinct if distinct and full_scores[distinct[0]] >= best * 0.8 else ()
        lead = first if first in distinct else distinct[0]
        return (lead, *(label for label in distinct if label != lead))


@lru_cache(maxsize=1)
def trained_classifier() -> IntentClassifier:
    source = Path(__file__).with_name("training.json")
    return IntentClassifier(json.loads(source.read_text(encoding="utf-8")))
