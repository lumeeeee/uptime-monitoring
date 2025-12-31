# Uptime Monitoring

## Что это за проект
Система мониторинга доступности веб-сайтов: проверяет HTTP/HTTPS, сохраняет историю статусов, фиксирует инциденты, отдаёт REST API и простой read-only web UI. Проверки выполняет отдельный worker-процесс.

## Архитектура (кратко)
- **API (FastAPI)**: CRUD сайтов, чтение инцидентов, метрик, health, web UI (Jinja2). Бизнес-логика в сервисах.
- **Worker**: планирует и выполняет проверки, пишет результаты, открывает/закрывает инциденты.
- **База данных (PostgreSQL)**: хранит сайты, результаты проверок, инциденты, состояние планировщика.
- **Система алертов**: абстракция AlertSender + TelegramNotifier (httpx); интеграция с worker не подключена.

## Стек технологий
- Python 3.12+
- FastAPI, Starlette/Jinja2 (UI)
- Pydantic
- SQLAlchemy 2.0 async, asyncpg
- Alembic
- httpx
- Uvicorn (запуск API)
- PostgreSQL

## Структура проекта
- `app/api` — FastAPI приложение, зависимости, схемы (DTO), роутеры (`sites`, `incidents`, `metrics`, `health`, `ui`).
- `app/services` — сервисы работы с БД и доменные расчёты (sites, status_history, incidents, metrics, checker).
- `app/workers` — worker-процесс (`runner.py`).
- `app/db` — ORM-модели и сессия.
- `app/alerts` — абстракция алертов и Telegram notifier.
- `app/web/templates` — Jinja2 шаблоны UI.
- `alembic/` — миграции, конфигурация Alembic.
- `deploy/systemd` — unit-файлы для API и worker.
- `docker-compose.yml` — compose с Postgres, API, worker.
- `.env.example` — пример переменных окружения.

## Конфигурация
Все настройки — через переменные окружения (см. `.env.example`). Ключевые:
- `DATABASE_URL` — строка подключения PostgreSQL (asyncpg).
- `API_HOST`, `API_PORT` — адрес/порт API.
- `CHECKER_CONCURRENCY`, `POLL_INTERVAL_SEC`, `LEASE_TIMEOUT_SEC`, `FETCH_BATCH_SIZE` — параметры worker.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_PARSE_MODE` — для TelegramNotifier. Подписки пользователей хранятся в БД (командами бота `/start`/`/subscribe`/`/unsubscribe`).

## Запуск
- Применить миграции: `alembic upgrade head` (нужен `DATABASE_URL`).
- Локальный API: `uvicorn app.api.main:app --host 0.0.0.0 --port 8000`.
- Локальный worker: `python -m app.workers.runner`.
- Docker Compose: `docker-compose up --build` (требуется Dockerfile, которого нет в репозитории).
- systemd: unit-файлы в `deploy/systemd/` (предполагается код в `/opt/uptime-monitoring` и env-файл `/etc/uptime-monitoring.env`).

## API
Основные endpoints (JSON, если не указано иное):
- `GET /health` — проверка доступности БД.
- `GET /sites` — список сайтов; `POST /sites` — создать; `GET /sites/{id}` — получить; `PATCH /sites/{id}` — обновить; `DELETE /sites/{id}` — удалить.
- `GET /incidents?target_id=...` — список инцидентов по сайту; `GET /incidents/{id}` — инцидент по id.
- `GET /metrics/uptime?target_id=...&window_hours=...` — uptime/downtime/availability за окно.
- `GET /ui` — HTML дашборд (read-only); `GET /ui/sites/{id}` — детали сайта.

## Мониторинг и инциденты
- Worker выбирает активные сайты по `scheduler_state.next_run_at` (skip locked, lease), ограничивает параллелизм семафором.
- Проверки выполняются через `httpx.AsyncClient` с таймаутом, retry и backoff; статус UP если HTTP 2xx/3xx, иначе DOWN.
- Каждая проверка сохраняется в `check_results` с латентностью, HTTP-кодом, ошибкой.
- Инцидент открывается при первом DOWN (если нет открытого), обновляется при следующих DOWN, закрывается при UP (end_ts, resolved=true).

## Алерты
- Реализован `AlertSender` и `TelegramNotifier` (HTTP API Telegram). Подписки пользователей хранятся в таблице `notification_channels` (type=`telegram`).
- Бот поддерживает команды `/start` и `/subscribe` для подписки, `/unsubscribe` для отписки. Добавлен webhook-роутер в API: `POST /telegram/webhook` — требуется настроить webhook в Telegram на этот URL или запустить polling proxy.

## Ограничения текущей реализации
- Нет аутентификации/авторизации в API и UI.
- Алерты не вызываются из worker (только реализация отправителя).
- Нет Dockerfile, поэтому compose потребует его добавить перед сборкой.
- Нет тестов.
- Метрики вычисляются на лету по `check_results` (без агрегаций/materialized views).
- UI read-only, без управления конфигурацией.
