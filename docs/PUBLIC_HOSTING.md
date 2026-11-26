# Публичный сайт Keme AI на Render

Сайт и Backend 2 опубликованы 22 ноября 2026 года одним Docker Web Service: **https://keme-ai-platform.onrender.com**.

Render service: `srv-dc1ej6qjnfac738icr1g`; workspace: My Workspace аккаунта Kirosu (`tea-dc1eesqjnfac738i0p8g`). Первый успешный деплой: `dep-dc1ej7ajnfac738icsr0`, commit `c599d50fbfd8941e6de95582020c8244f60c0eee`. AI Engine остаётся отдельным сервисом друга, данные платформы — в Supabase. Работа публичного сайта не зависит от включённого локального компьютера.

## Подготовленная конфигурация

- Имя: `keme-ai-platform` (точный URL определяется Render при создании).
- Runtime: Docker; Dockerfile `./Dockerfile`; build context `.`; branch `main`.
- Тариф: Free для публичного демо; регион Frankfurt.
- Порт: 8001; Health Check: `/health`.
- Текущий сервис создан через официальный CLI. Автодеплой подготовлен через GitHub Actions. Он запускает Render после проверок и привязывает деплой к проверенному коммиту. Для настройки используйте раздел ниже.
- Blueprint: `render.yaml`. Секретные значения в нём отсутствуют.

Render Free засыпает после простоя; первое открытие может занять около минуты. Для постоянного производственного сервиса потребуется отдельно выбрать подходящий тариф. Два Free-сервиса в одном workspace используют общую квоту часов, поэтому лимит нужно учитывать, если размещать платформу и движок в одном аккаунте.

## Переменные сервера

Следующие значения взять из локального корневого `.env` и передать только в закрытые Environment Variables Render:

- `SUPABASE_PUBLISHABLE_KEY`;
- `SUPABASE_SECRET_KEY`;
- `ENGINE_JWT_SECRET` — тот же секрет, что `JWT_SECRET` движка.

Остальные переменные задаёт Blueprint. Браузер обращается к `/api/*` на том же домене, поэтому отдельный CORS-origin не нужен. Не переносить серверные ключи в `VITE_*`, исходники, Dockerfile, Git или чат.

При ручном создании: Render Dashboard → New → Blueprint → `Lipstickbot/marketplace-backend-2`, branch `main` → заполнить три запрошенных значения → создать сервис. Если используется Web Service вручную, выбрать Docker и перенести поля из Blueprint. Для сохранения новых переменных нужен **Save and deploy**; **Restart service** использует прежний набор переменных.

## Проверка после развёртывания

1. Дождаться статуса Live и получить фактический HTTPS-адрес Render.
2. Проверить `/`, `/catalog/`, `/account/`, `/api/health`, `/api/agents` (12 карточек).
3. Проверить `/api/engine/health`: движок доступен, текущий провайдер mock.
4. В Supabase Auth настроить Site URL и Redirect URLs для подтверждения почты на фактическом публичном домене. Эти настройки не меняют модель ролей или RLS.
5. Проверить вход, выход и подтверждение почты на пользовательском аккаунте; одобренное подключение по-прежнему требуется для исполнения.

Одна лишь публикация не включает оплату, реальную LLM или автоматическое одобрение подключений. Платформенный администратор назначается доверенным оператором базы.

Docker-образ успешно собран на Render, деплой получил статус Live. Проверены публичные страницы, 12 карточек API, связь с движком и отказ без авторизации. Через опубликованный HTTPS Backend прошли 37 проверок: настоящий Supabase Auth/Storage/PostgreSQL, три вымышленных файла, четыре успешных запуска и одна ожидаемая ошибка HR, журнал и очистка. В Supabase тестовых аккаунтов, профилей и файлов не осталось; каталог из 12 карточек сохранён. Технический журнал тестов и вымышленные tenant остаются у движка, где нет API их удаления.

Запуск повторной проверки с разрешёнными временными данными: `python scripts/check_cloud_engine_integration.py --backend-url https://keme-ai-platform.onrender.com`. Подтверждение почты и фактические Site URL/Redirect URLs через доступные средства автоматически не проверены и не изменялись; для пользовательского signup нужно проверить их в Supabase Dashboard.

## Автодеплой бизнес-аналитика

1. Проверьте карточку из заявки разработчика со slug `keme-business-analytics` и ID `40466f5f-1e54-4b52-bf63-5f280b79933a`. Публичный адрес карточки `/catalog/?agent=keme-business-analytics`. Карточка-заготовка `business-analytics` архивируется, её адрес ведёт к карточке из заявки. Миграция `20261126190000_agent_purchases.sql` нужна перед отдельным включением продажи агентов.
2. Проверьте, что оба сервиса Render привязаны к ветке `main` репозитория платформы через GitHub. В Render оставьте **Auto-Deploy → Off** для обоих сервисов. Точный коммит развернёт GitHub Actions.
3. В GitHub создайте окружение **production** для ветки `main`. В его secrets задайте `RENDER_API_KEY` с правами на деплой двух сервисов и `SUPABASE_SECRET_KEY`. В variables задайте `RENDER_BACKEND_SERVICE_ID`, `RENDER_FRONTEND_SERVICE_ID`, `RENDER_BACKEND_URL` (HTTPS без `/api`), `SUPABASE_URL` и `SUPABASE_PUBLISHABLE_KEY`. В переменных самого репозитория задайте `RENDER_ANALYTICS_DEPLOY=true`.
4. После слияния в `main` GitHub Actions проверит фронтенд, базу, API и 37 тестов агента. Затем скрипт развернёт бэкенд и проверит его по `/api/health/business-analytics`. Проверка выполнит текстовый запрос и расчёт прибыли на небольшой таблице и сверит SHA. При успехе скрипт обновит существующую карточку и развернёт фронтенд. При ошибке проверки шаг активации завершится ошибкой до изменения карточки.
5. Войдите под тестовой бизнес-учётной записью, подключите «Бизнес-аналитика» и откройте запуск в кабинете. Проверьте текстовый запрос и UTF-8 таблицу из `agents/business_analytics/example.csv`. Проверьте запуск Marketing через внешний AI Engine.

[Деплой точного коммита в Render](https://render.com/docs/deploys) · [Настройки Blueprint](https://render.com/docs/blueprint-spec) · [Покупка агентов](PAYMENTS.md)

Документация: https://render.com/docs/blueprint-spec, https://render.com/docs/free, https://render.com/docs/configure-environment-variables.
