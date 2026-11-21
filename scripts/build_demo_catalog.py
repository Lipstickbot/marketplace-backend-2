"""Read real local engine metadata and build the catalog data migration."""
import json
from pathlib import Path
from uuid import UUID

import httpx

from backend.app.config import Settings
from backend.app.engine_client import EngineClient
from backend.app.models import Principal


def main():
    root = Path(__file__).resolve().parents[1]
    settings = Settings.from_env()
    principal = Principal(user_id=UUID("11111111-1111-4111-8111-111111111111"), email=None,
        role="business", company_id=UUID("11111111-1111-4111-8111-111111111111"),
        display_name="Metadata Reader", company_name="Local Metadata Test")
    token = EngineClient(settings, None).token(principal)
    with httpx.Client(base_url=settings.engine_url, timeout=30, trust_env=False) as client:
        health = client.get("/health")
        health.raise_for_status()
        assert health.json()["llm_provider"] == "mock"
        response = client.get("/agents", headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        metadata = response.json()["agents"]
    assert {row["slug"] for row in metadata} == {"marketing", "support", "hr"}
    copy = {
        "marketing": ("AI Marketing — демо", "Черновики постов, контент-планы и маркетинговые идеи. Локальное демо работает в mock-режиме: ответы демонстрационные, не результат реальной модели."),
        "support": ("AI Support — демо", "Ответы по загруженной базе знаний и подготовка обращения менеджеру. Локальное демо работает в mock-режиме; отправки в CRM нет."),
        "hr": ("AI HR — демо", "Сводка одного резюме, факты о навыках и вопросы для интервью. Без рейтингов и решений о найме. Локальное демо работает в mock-режиме."),
    }
    rows = []
    for row in metadata:
        name, description = copy[row["slug"]]
        rows.append({key: row[key] for key in ("slug", "category", "version", "supported_languages", "capabilities",
                                              "accepted_file_purposes", "input_schema", "output_schema")})
        rows[-1].update(name=name, description=description, status="published", engine_slug=row["slug"])
        rows[-1]["input_schema"]["properties"]["file_ids"]["description"] = "Platform file UUIDs from POST /files/upload; Backend 2 maps them to engine IDs."
    soon = [
        ("sales-assistant", "Помощник продаж", "sales", "Подготовка черновиков коммерческих предложений. Скоро; исполнитель ещё не подключён."),
        ("invoice-reader", "Разбор счетов", "finance", "Извлечение реквизитов и сумм для проверки сотрудником. Скоро."),
        ("meeting-notes", "Итоги встреч", "productivity", "Черновики итогов встреч и списков задач. Скоро."),
        ("document-translator", "Перевод документов", "documents", "Черновой перевод рабочих документов. Скоро."),
        ("business-analytics", "Бизнес-аналитик", "analytics", "Объяснение показателей бизнеса и подготовка сводок. Скоро."),
        ("procurement-assistant", "Помощник закупок", "operations", "Структурирование требований и предложений поставщиков. Скоро."),
        ("crm-assistant", "Помощник CRM", "sales", "Черновики заметок и последующих действий по сделкам. Скоро."),
        ("onboarding-assistant", "Адаптация сотрудников", "hr", "Поиск по инструкциям и планы адаптации сотрудников. Скоро."),
        ("inventory-planner", "Планирование запасов", "operations", "Сводки по остаткам и подготовка предложений для проверки менеджером. Скоро."),
    ]
    for slug, name, category, description in soon:
        rows.append(dict(slug=slug,name=name,category=category,description=description,status="coming_soon",
            engine_slug=None,version=None,supported_languages=["ru","kk","en"],capabilities=[],
            accepted_file_purposes=[],input_schema={},output_schema={}))
    data = json.dumps(rows, ensure_ascii=False, indent=2)
    assert "$catalog$" not in data
    # Future exports are review candidates; never rewrite an applied migration.
    migration = root / ".run" / "demo-catalog.candidate.sql"
    sql = """-- Three local mock demos and nine clearly marked future cards.
-- Uses engine metadata from upstream 0224719c29cc47cde7607a376c8b511a1ee05da2.
begin;
insert into public.agents(slug,name,description,category,status,engine_slug,version,supported_languages,
  capabilities,accepted_file_purposes,input_schema,output_schema)
select slug,name,description,category,status,engine_slug,version,supported_languages,
  capabilities,accepted_file_purposes,input_schema,output_schema
from jsonb_to_recordset($catalog$""" + data + """$catalog$::jsonb) as seed(
  slug text,name text,description text,category text,status public.agent_status,engine_slug text,version text,
  supported_languages text[],capabilities text[],accepted_file_purposes public.file_purpose[],
  input_schema jsonb,output_schema jsonb)
on conflict (slug) do nothing;
commit;
"""
    migration.write_text(sql, encoding="utf-8")
    print({"cards": len(rows), "published_demos": 3, "coming_soon": len(soon)})


if __name__ == "__main__":
    main()
