import logging
from time import perf_counter
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from agents.business_analytics import analyze, choose_language
from agents.business_analytics.__main__ import ERRORS
from agents.business_analytics.metrics import DatasetError, MAX_CSV_BYTES
from agents.business_analytics.report import language_index

from .engine_models import Execution, RunInput, Usage
from .errors import APIError


SLUG = "business-analytics"
VERSION = "1.0.0"
logger = logging.getLogger(__name__)


async def run_local(body: RunInput, run_id: UUID) -> Execution:
    started = perf_counter()
    dataset = body.dataset
    language = choose_language(body.message, body.language)
    try:
        if dataset:
            try:
                size = len(dataset.text.encode("utf-8"))
            except UnicodeError:
                raise DatasetError("format") from None
            if size > MAX_CSV_BYTES:
                raise DatasetError("size")
        result = await run_in_threadpool(analyze, body.message, csv_text=dataset.text if dataset else None,
                                         language=language)
    except DatasetError as error:
        message = ERRORS.get(error.code, ERRORS["format"])[language_index(language)].format(field=error.field)
        if error.row:
            row_label = ("Строка", "Жол", "Row")[language_index(language)]
            message = f"{row_label} {error.row}. {message}"
        raise APIError(413 if error.code == "size" else 422, f"dataset_{error.code}", message) from None
    except Exception as error:
        logger.error("business_analytics_failed error_type=%s", type(error).__name__)
        raise APIError(500, "analytics_failed", "Не удалось составить отчёт. Попробуйте повторить запрос.") from None
    return Execution(run_id=run_id, agent=SLUG, agent_version=VERSION, status="success", response=result.answer,
        language=result.language, sources=[], usage=Usage(input_tokens=0, output_tokens=0, total_tokens=0,
        estimated_cost=0, currency="USD"), execution_time_ms=int((perf_counter() - started) * 1000),
        mode="none", model=None, data=result.data, warnings=[])


async def smoke():
    run_id = UUID(int=0)
    text = await run_local(RunInput(message="Как рассчитать прибыль?", language="ru"), run_id)
    table = await run_local(RunInput(message="Посчитай прибыль", language="ru",
        dataset={"filename": "smoke.csv", "text": "revenue,cost\n100,40\n"}), run_id)
    if not text.response or not table.data or table.data.get("metrics", {}).get("profit", {}).get("value") != "60":
        raise RuntimeError("Business analytics smoke test failed")


async def activate(store):
    # Leave the existing catalog row untouched unless both local smoke requests pass.
    await smoke()
    rows = await store.request("GET", "/rest/v1/agents",
        params={"slug": f"eq.{SLUG}", "select": "id,engine_slug,status"})
    if not isinstance(rows, list) or len(rows) != 1:
        raise RuntimeError("Expected one existing business-analytics catalog card")
    card = rows[0]
    agent_id = card["id"]
    if card["engine_slug"] is None and card["status"] == "coming_soon":
        bound = await store.request("PATCH", "/rest/v1/agents",
            params={"id": f"eq.{agent_id}", "slug": f"eq.{SLUG}", "status": "eq.coming_soon", "engine_slug": "is.null"},
            body={"engine_slug": SLUG})
        if not isinstance(bound, list) or len(bound) != 1:
            raise RuntimeError("The catalog card changed before binding")
    elif card["engine_slug"] != SLUG or card["status"] not in {"coming_soon", "published"}:
        raise RuntimeError("Unexpected binding or status on the business-analytics card")
    rows = await store.request("PATCH", "/rest/v1/agents",
        params={"id": f"eq.{agent_id}", "slug": f"eq.{SLUG}", "engine_slug": f"eq.{SLUG}",
                "status": "in.(coming_soon,published)"},
        body={"status": "published", "version": VERSION, "auto_connect": True,
              "accepted_file_purposes": [], "capabilities": ["csv", "tsv", "business_kpis"]})
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("id") != agent_id:
        raise RuntimeError("Unable to activate the existing business-analytics card")
