"""Supported CSV columns for grouped reports."""

import re


DIMENSION_ALIASES = {
    "region": "регион регионы область өңір өңірі аймақ аймағы",
    "channel": "traffic_channel sales_channel канал каналы канал_продаж источник_трафика арна арнасы",
    "product": "item product_name товар товары продукт название_товара тауар тауар_атауы өнім",
    "category": "product_category item_category категория категории категория_товара санат тауар_санаты",
    "sku": "артикул артикулы тауар_коды код_товара",
}
DIMENSION_WORDS = {
    "category": r"(?:product\s+)?categor(?:y|ies)|категориям(?:\s+товаров)?|категории|(?:тауар\s+)?санат(?:тар)?",
    "region": r"регионам|региону|областям|regions?|өңір(?:лер)?|аймақ(?:тар)?",
    "channel": r"каналам|каналу|channels?|арна(?:лар)?",
    "product": r"товарам|товару|продуктам|products?|тауар(?:лар)?|өнім(?:дер)?",
    "sku": r"артикулам|артикулу|sku(?:s)?",
}
NAMES = "|".join(DIMENSION_WORDS.values())
PREFIXED = re.compile(r"\b(?:по|by)\s+((?:" + NAMES + r")(?:(?:\s*,\s*|\s+(?:и|and)\s+)(?:" + NAMES + r"))*)\b", re.I)
SUFFIXED = re.compile(r"\b((?:" + NAMES + r")(?:\s+және\s+(?:" + NAMES + r"))*)\s+бойынша\b", re.I)
NAMED_DIMENSION = re.compile("|".join(rf"(?P<{key}>\b(?:{words})\b)" for key, words in DIMENSION_WORDS.items()), re.I)


def requested_dimensions(question: str) -> set[str]:
    phrases = [match[1] for pattern in (PREFIXED, SUFFIXED) for match in pattern.finditer(question)]
    return {key for phrase in phrases for match in NAMED_DIMENSION.finditer(phrase) if (key := match.lastgroup)}
