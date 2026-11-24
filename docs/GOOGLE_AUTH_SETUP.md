# Вход через Google и статический сайт

Основной адрес интерфейса: **https://keme-ai.onrender.com**. Это отдельный статический сайт Render: главная и файлы интерфейса доступны с CDN без страницы пробуждения Python-сервера. Backend: https://keme-ai-platform.onrender.com/api. Первый запрос к бесплатному API после простоя всё ещё может занять около минуты. Перед отправкой операции клиент проверяет `/api/health`; запись, загрузка и запуск агента не повторяются автоматически.

## Настройки Google

В Google Cloud → Google Auth Platform выберите проект и настройте Branding/Audience. Для обычного Google-аккаунта используйте External. В режиме Testing добавьте почты проверяющих в Test users; для входа широкой аудитории переведите приложение в Production.

В Clients создайте OAuth client типа **Web application**:

- Название: Keme AI.
- Authorized JavaScript origins: `https://keme-ai.onrender.com`.
- Authorized redirect URI: `https://qxzhrkchmzmfxvkpnbfr.supabase.co/auth/v1/callback`.
- Запрашиваются только профиль и почта (`openid email profile`).

В Supabase → Authentication → Sign In / Providers → Google включите провайдер, вставьте полученные **Client ID** и **Client Secret**, сохраните. Это OAuth-реквизиты, а не Gemini API key. Client Secret хранится в Supabase, не в исходниках или Vite-переменных.

В Supabase → Authentication → URL Configuration:

- Site URL: `https://keme-ai.onrender.com`.
- Redirect URLs: `https://keme-ai.onrender.com/account/**` и `https://keme-ai-platform.onrender.com/account/**`.
- Для локального теста при необходимости: `http://localhost:3000/account/**` и `http://127.0.0.1:8001/account/**`.

Проверка активации: `GET https://keme-ai-platform.onrender.com/api/auth/providers` должен вернуть `{"google":true}`. Состояние провайдера кэшируется сервером на 30 секунд. До активации кнопка видна с пояснением, а вход по почте доступен.

## Реализация

Браузер создаёт случайные PKCE verifier/challenge и отдельный state. Verifier хранится только в sessionStorage текущей вкладки, попытка истекает через 10 минут. `/auth/google/start` разрешает возврат только в `/account/` настроенных `OAUTH_REDIRECT_ORIGINS`.

После возврата клиент проверяет state, удаляет код из адресной строки и обменивает код через `/auth/google/exchange`. Backend использует Supabase `grant_type=pkce`, проверяет Auth-пользователя и активность сессии. Роль и company_id определяются по профилю БД, не по пользовательским metadata. Новый OAuth-пользователь получает существующую роль по умолчанию «Бизнес»; email-регистрация разработчика остаётся доступной. Сессия Google не даёт права администратора.

После успешного входа или регистрации открывается главная. При email-подтверждении главная показывает подсказку проверить почту. Сессия хранится в `localStorage` этого браузера, восстанавливается после закрытия браузера и удаляется по кнопке «Выйти»; пароль не сохраняется. Временные PKCE-данные остаются в `sessionStorage`. Обновление сессии координируется между вкладками через Web Locks; временный сетевой сбой не стирает сохранённый вход.

Действия разделены: «Подключить агента» использует заявку подключения готового агента для бизнеса, «Добавить своего агента» — заявку публикации разработчика. Для аккаунта разработчика доступна email-регистрация. Сохранённые перед входом заявки остаются во вкладке и требуют явного подтверждения отправки.

## Размещение

Render Static Site `srv-dc2rnd2jnfac73f8lf7g`: корень `frontend`, сборка `npm ci --no-audit --no-fund && npm run build`, каталог `dist`, `VITE_API_BASE=https://keme-ai-platform.onrender.com/api`.

API-сервис `srv-dc1ej6qjnfac738icr1g`: `CORS_ORIGINS=https://keme-ai.onrender.com`, `OAUTH_REDIRECT_ORIGINS` содержит точные origins интерфейса. Серверные ключи остаются только в API-сервисе. Переход на платный план не выполнялся.

Старый адрес `keme-ai-platform.onrender.com` продолжает работать как серверный сервис и может показывать страницу пробуждения Render при прямом открытии. Для пользователей распространяйте новый адрес `keme-ai.onrender.com`.

## Проверки

Автотесты покрывают PKCE, запрет посторонних redirect URL, проверку state/срока попытки, очистку URL, сохранение роли из БД и отсутствие автоматического повтора операций. Реальная авторизация Google требует активации провайдера и входа владельца в браузере: её нельзя считать проверенной только по тестам кода.

Документация: [Google в Supabase](https://supabase.com/docs/guides/auth/social-sign-in/auth-google), [PKCE](https://supabase.com/docs/guides/auth/sessions/pkce-flow), [Render Static Sites](https://render.com/docs/static-sites).
