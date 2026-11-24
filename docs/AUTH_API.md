# Авторизация платформы Backend 2

Базовый локальный адрес — `http://127.0.0.1:8001`. Авторизация использует Supabase Auth и серверную роль из `public.profiles`. Интерактивная спецификация доступна по `/docs`, OpenAPI — `/openapi.json`.

## Регистрация

`POST /auth/signup`, JSON:

```json
{
  "email": "user@example.com",
  "password": "your-unique-password",
  "role": "business",
  "display_name": "Алия",
  "company_name": "Моя компания"
}
```

Роль — `business` (по умолчанию) или `developer`. Пароль — 12–128 символов; Supabase также может применять свои требования. `display_name` — до 120, `company_name` — до 200 символов. Лишние поля, включая `company_id`/`user_id`, запрещены. Для CAPTCHA можно передать дополнительное поле `captcha_token`; токен передаётся в Supabase без хранения на сервере.

Обычный ответ при включённом подтверждении почты, HTTP 201:

```json
{"status": "confirmation_required", "session": null}
```

Фронтенд предлагает открыть ссылку из письма или ввести код. Кнопка повторной отправки доступна на экране подтверждения. Ответ на регистрацию не раскрывает, был ли пользователь зарегистрирован раньше, и не подтверждает доставку письма. Для обычных адресов настройте [свой SMTP в Supabase](https://supabase.com/docs/guides/auth/auth-smtp), оставьте подтверждение почты включённым и разрешите `https://keme-ai.onrender.com/account/**` в Redirect URLs.

`POST /auth/email/resend` принимает `{"email":"user@example.com"}` и запрашивает повторное письмо для незавершённой регистрации. `POST /auth/email/verify` принимает `{"email":"user@example.com","code":"012345"}` и возвращает сессию после проверки кода в Supabase. Обе операции используют ограничения частоты запросов Auth.

Шаблон **Confirm sign up** в Supabase может включать и ссылку, и код. После подключения SMTP установите тему `Подтвердите почту для Keme AI` и добавьте в шаблон:

```html
<h2>Подтвердите почту для Keme AI</h2>
<p><a href="{{ .ConfirmationURL }}">Подтвердить почту</a></p>
<p>Или введите на сайте код <strong>{{ .Token }}</strong>.</p>
<p>Если вы не регистрировались в Keme AI, просто пропустите это письмо.</p>
```

Если сам проект Supabase настроен на регистрацию с немедленным входом, ответ имеет `status: "signed_in"`, а `session` содержит объект ответа входа ниже. Автоматически назначить роль `admin` через регистрацию нельзя.

## Вход и обновление

`POST /auth/login`:

```json
{"email": "user@example.com", "password": "your-unique-password"}
```

Ответ HTTP 200:

```json
{
  "session": {
    "access_token": "<supabase-access-token>",
    "refresh_token": "<supabase-refresh-token>",
    "token_type": "bearer",
    "expires_in": 3600,
    "expires_at": 1795220000
  },
  "profile": {
    "user_id": "<user-uuid>",
    "email": "user@example.com",
    "role": "business",
    "company_id": "<same-user-uuid>",
    "display_name": "Алия",
    "company_name": "Моя компания"
  }
}
```

`expires_in` и `expires_at` приходят от Supabase; время в примере условное. Для `developer`/`admin` поле `company_id` равно `null`: исполнительные права бизнеса им автоматически не выдаются.

Обновление: `POST /auth/refresh` с JSON `{"refresh_token":"<current-refresh-token>"}`. Ответ имеет ту же форму. Фронтенд заменяет **оба** токена значениями из последнего ответа и не отправляет несколько refresh-запросов одновременно для одной сессии. Сервер не сохраняет токены между запросами. Повторять неуспешный refresh бесконечно нельзя: при HTTP 401 нужно очистить клиентскую сессию и показать вход.

## Защищённые запросы и профиль

Передавать заголовок:

```text
Authorization: Bearer <access_token>
```

`GET /auth/me` возвращает объект `profile` без внешней обёртки. Проверяется JWT через сетевой вызов Supabase Auth, наличие сессии через безопасный RPC и соответствие профиля ID проверенного пользователя. Роль читается из базы при каждом запросе; `user_metadata`, роль Postgres `authenticated` и поля тела запроса не определяют платформенные права.

`PATCH /auth/me` принимает одно или оба поля `display_name`, `company_name`. Пустой объект, `null`, поля роли и идентичности отклоняются. Ответ — обновлённый профиль. Изменение названия компании не меняет `company_id`.

Зависимость `require_roles("business")` / `require_roles("developer")` / `require_roles("admin")` в `backend/app/auth.py` предназначена для следующих API каталога и модерации. Роль администратора назначается доверенным оператором отдельно.

## Выход

`POST /auth/logout` с access token возвращает HTTP 204 без тела. Выход затрагивает текущую сессию (`scope=local`). Фронтенд удаляет локальные access/refresh tokens.

Backend 2 проверяет наличие `session_id` в `auth.sessions` через RPC, поэтому старый access token перестаёт работать в этом API после выхода. Прямые обращения к другим сервисам Supabase продолжают следовать их собственным правилам проверки JWT и могут принимать ещё не истёкший токен. Эти настройки и политики не изменяются данным API. Проверка RPC учитывает `not_after`; настройки inactivity timeout и ограничения количества сессий остаются ответственностью Supabase Auth.

## Ошибки и эксплуатация

```json
{"error":{"code":"invalid_credentials","message":"Требуется действующая сессия.","request_id":"<id>"}}
```

| HTTP | Код | Действие фронтенда |
| --- | --- | --- |
| 401 | `auth_required`, `invalid_credentials`, `invalid_session` | Показать вход или сообщение о неверных данных |
| 401 | `invalid_refresh_token`, `session_revoked` | Очистить клиентскую сессию |
| 403 | `email_not_confirmed` | Предложить подтвердить почту |
| 403 | `role_forbidden`, `profile_missing` | Показать отсутствие доступа/профиля |
| 422 | `validation_error` и ошибки регистрации | Проверить ввод; массив `issues` не содержит значения полей |
| 429 | `auth_rate_limited` | Соблюдать `Retry-After` |
| 502/503 | `supabase_contract_error`, `supabase_unavailable` | Показать временную недоступность |

У каждого ответа есть `X-Request-ID`; у ответов `/auth/*` — `Cache-Control: no-store`. Пароли/токены не записываются в БД Backend 2 и не возвращаются в тексте ошибок. Токены возвращаются только в успешном ответе сессии. На фронтенде требуется защищённое управление сессией и защита от XSS; в продакшене API должен работать через HTTPS.

Лимит по умолчанию — 10 запросов в минуту на IP для signup/login/refresh, общий для этих трёх endpoints в процессе. Дополнительно действуют лимиты Supabase. При нескольких репликах нужен общий лимит в reverse proxy/Redis. CORS разрешает только адреса из `CORS_ORIGINS`, без cookies; по умолчанию `http://localhost:3000`. Не доверять произвольным proxy headers на публичном сервере.

`GET /health` проверяет работу процесса; это не проверка доступности Supabase. Backend 2 использует publishable key и пользовательские токены. `SUPABASE_SECRET_KEY`, `SUPABASE_SERVICE_ROLE_KEY` и секрет движка не нужны этому этапу и не должны попадать во фронтенд.

## Проверки

29 сценариев Auth API проверяют контракты, изоляцию идентичности, роли, истёкшие/отозванные сессии, ошибочные ответы провайдера, CORS и лимиты; общий набор платформы содержит 97 API-тестов. 20 сценариев PostgreSQL проверяют миграции, RLS, RPC и каталог. На реальном Supabase пройдены 13 проверок с временным предварительно подтверждённым аккаунтом; аккаунт и его сессии/профиль/identity удалены. Письма не отправлялись: полный signup с доставкой и подтверждением email требует отдельной пользовательской проверки после подключения фронтенда.

Основа протокола — [официальная спецификация Supabase Auth](https://github.com/supabase/auth/blob/master/openapi.yaml). Проверка отозванной сессии следует разделу [User sessions](https://supabase.com/docs/guides/auth/sessions#how-to-ensure-an-access-token-jwt-cannot-be-used-after-a-user-signs-out).
