import asyncio
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from agents.business_analytics import choose_language
from scripts.fetch_architect_materials import MATERIALS

from .config import Settings
from .engine_models import Execution, RunInput, Usage
from .errors import APIError

SLUG = "architect-sa-mentor"
VERSION = "1.1.0"
REPOSITORY_PATH = "/bigfigboy/architect-ai-systems-business-analyst"
ROOT = Path(__file__).resolve().parents[2] / ".run" / "architect"
LANGUAGES = {"ru": "Russian", "en": "English"}
CAPABILITIES = ["Проверка требований", "Спецификации и user stories", "UML, BPMN и Mermaid"]


def matches_repository(url: str | None) -> bool:
    try:
        parsed = urlsplit(url or "")
    except ValueError:
        return False
    return (parsed.scheme == "https" and parsed.netloc.lower() == "github.com"
            and parsed.path.lower().rstrip("/").removesuffix(".git") == REPOSITORY_PATH
            and not parsed.query and not parsed.fragment)


@lru_cache(maxsize=1)
def instructions() -> str:
    try:
        return "\n\n".join((ROOT / name).read_text(encoding="utf-8") for name in MATERIALS)
    except (OSError, UnicodeError):
        raise APIError(503, "architect_materials_missing", "Материалы ARCHITECT пока не установлены на сервере.") from None


def require_configured(settings: Settings):
    if not settings.architect_gemini_api_key:
        raise APIError(503, "architect_not_configured", "Для ARCHITECT требуется ключ Gemini в настройках Render.")


def metadata() -> dict:
    return {"slug": SLUG, "version": VERSION, "supported_languages": list(LANGUAGES),
            "capabilities": CAPABILITIES, "accepted_file_purposes": [],
            "input_schema": {"type": "object", "required": ["message"], "properties": {
                "message": {"type": "string", "maxLength": 8000},
                "language": {"enum": ["auto", *LANGUAGES]},
            }}, "output_schema": {"type": "string"}}


def validate_input(body: RunInput):
    if body.dataset is not None or body.file_ids:
        raise APIError(422, "architect_attachments_not_supported", "Вставьте требования или описание задачи в текст запроса.")
    if body.options or not body.message.strip() or body.language == "kk":
        raise APIError(422, "architect_invalid_input", "Введите текст запроса и выберите русский, английский или авто.")
    language = choose_language(body.message, body.language)
    if language not in LANGUAGES:
        raise APIError(422, "architect_language_not_supported", "ARCHITECT поддерживает русский и английский.")
    return language


async def run(body: RunInput, run_id: UUID, settings: Settings, client: httpx.AsyncClient) -> Execution:
    require_configured(settings)
    started = perf_counter()
    language = validate_input(body)
    system_text = f"{instructions()}\n\nAnswer in {LANGUAGES[language]}."
    contents = [{"role": "model" if item.role == "assistant" else "user", "parts": [{"text": item.content}]}
                for item in body.history]
    contents.append({"role": "user", "parts": [{"text": body.message}]})
    try:
        async with asyncio.timeout(28):
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{settings.architect_gemini_model}:generateContent",
                headers={"x-goog-api-key": settings.architect_gemini_api_key.get_secret_value()},
                json={"systemInstruction": {"parts": [{"text": system_text}]}, "contents": contents,
                      "generationConfig": {"temperature": 0.4, "maxOutputTokens": 4000}},
            )
    except (TimeoutError, httpx.TimeoutException):
        raise APIError(504, "architect_model_timeout", "Gemini не успел ответить. Повторите запрос позже.") from None
    except httpx.RequestError:
        raise APIError(503, "architect_model_unavailable", "Не удалось связаться с Gemini.") from None
    if response.status_code == 429:
        raise APIError(429, "architect_model_quota", "Лимит Gemini исчерпан. Повторите запрос позже.")
    if not response.is_success:
        raise APIError(503, "architect_model_unavailable", "Gemini не принял запрос. Проверьте ключ и настройки модели.")
    try:
        data = response.json()
        candidate = (data.get("candidates") or [{}])[0]
        finish_reason = candidate.get("finishReason")
        blocked = bool((data.get("promptFeedback") or {}).get("blockReason")) or finish_reason in {
            "SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION",
        }
        answer = "\n".join(part.get("text", "") for part in candidate.get("content", {}).get("parts", [])
                           if not part.get("thought")).strip()
        usage = data.get("usageMetadata") or {}
        inputs = usage.get("promptTokenCount", 0)
        outputs = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
        tokens = Usage(input_tokens=inputs, output_tokens=outputs, total_tokens=inputs + outputs, currency="USD")
    except (AttributeError, IndexError, TypeError, ValueError):
        raise APIError(502, "architect_model_invalid_response", "Gemini вернул несовместимый ответ.") from None
    if not answer and not blocked:
        raise APIError(502, "architect_model_empty_response", "Gemini вернул пустой ответ.")
    if blocked:
        answer = "Модель не может обработать этот запрос." if language == "ru" else "The model cannot process this request."
    return Execution(run_id=run_id, agent=SLUG, agent_version=VERSION, status="blocked" if blocked else "success",
        response=answer, language=language, sources=[], usage=tokens, execution_time_ms=int((perf_counter() - started) * 1000),
        mode="gemini", model=settings.architect_gemini_model, data=None,
        warnings=["output_truncated"] if finish_reason == "MAX_TOKENS" else [])


async def verify(settings: Settings, client: httpx.AsyncClient):
    reply = await run(RunInput(
        message="Объясни одним предложением, зачем нужны критерии приёмки. Это проверка запуска.", language="ru",
    ), UUID(int=0), settings, client)
    if reply.status != "success" or reply.warnings:
        raise APIError(503, "architect_probe_failed", "Проверка ARCHITECT не получила полный ответ Gemini.")
