# Uptime Monitoring System — Architecture Overview

## Компоненты
- **API (FastAPI)**: HTTP-интерфейс (REST, Web UI backend), аутентификация/авторизация, валидация входных данных, делегирование бизнес-логики в сервисы. Без фоновых задач.
- **Domain/Services**: Чистая бизнес-логика (targets, checks, incidents, metrics, notifications). Инкапсулирует правила, работает через репозитории/ORM. Без HTTP и I/O деталей.
- **DB Layer (SQLAlchemy 2.0 async + PostgreSQL)**: ORM-модели, репозитории, единая фабрика сессий, Alembic для миграций. TIMESTAMPTZ (UTC), UUID, индексы по временным полям и target_id.
- **Worker** (отдельный процесс):
  - **Scheduler**: планирование проверок per-target (priority queue по next_run_at), ограничение concurrency (Semaphore), учёт индивидуальных интервалов.
  - **Checker**: выполнение HTTP/HTTPS проверок (httpx), таймауты, retry с backoff, вычисление статуса UP/DOWN, фиксация CheckResult.
  - **Incident Manager**: обновление/закрытие инцидентов (start_ts/end_ts), дедупликация активных инцидентов.
  - **Notification Producer**: постановка событий уведомлений при сменах статуса/инцидента.
- **Alerts subsystem**:
  - **Notification Consumer** (может быть в том же worker-пуле как отдельная задача): обработка очереди уведомлений, идемпотентная отправка, канал Telegram (первый), расширяемость под другие каналы.
  - **Channel adapters**: Telegram sender с таймаутами/retry, backpressure/ограничение частоты.
- **Config (ENV-only)**: все настройки через переменные окружения; единый config объект.
- **Logging/Observability**: структурированные логи, технический healthcheck API, метрики (допустимо добавить Prometheus позже), трассировка по желанию.

## Потоки данных и взаимодействие
1. **CRUD Targets**: клиент → API → сервис targets → БД (targets). Настройки интервалов/таймаутов/ретраев управляются здесь.
2. **Планирование проверок**: Worker Scheduler читает активные targets, поддерживает min-heap по next_run_at, будит задачи с учётом concurrency.
3. **Проверка**: Checker выполняет HTTP GET с таймаутом и retry, фиксирует CheckResult в БД.
4. **Инциденты**: Incident Manager на основании нового CheckResult открывает/обновляет/закрывает инциденты (start_ts/end_ts, resolved).
5. **Уведомления**: при смене статуса/инцидента создаётся NotificationEvent → Consumer отправляет в Telegram (и др.), отмечает статус отправки.
6. **Метрики**: сервис metrics агрегирует uptime/downtime/SLA за окна (24h/7d); может кешировать/материализовывать представления.
7. **Чтение состояния**: клиент → API → сервисы (targets, incidents, history, metrics) → БД. API не содержит бизнес-логики.

## Принципы и ограничения
- Без фоновых задач в API (никаких BackgroundTasks, threading).
- Только PostgreSQL, async ORM, без raw SQL.
- Чёткое разделение: API — транспорт, Services — доменная логика, DB — инфраструктура, Worker — асинхронные проверки/уведомления.
- Конфигурация только через ENV; без хардкода.
- Типизация, явная обработка ошибок, таймауты и retry на внешних вызовах.
- Масштабирование: горизонтально API и worker; worker-конкурентность на уровне задач; уведомления отделены очередью/шиной событий (можно начать с табличной очереди).

## Database (логическая модель)
- **targets**: id (UUID PK), name, url (уникальный), check_interval_sec, timeout_ms, retry_count, retry_backoff_ms, sla_target (‰), is_active, created_at (timestamptz), updated_at (timestamptz); индексы: uniq(url), idx(is_active), idx(updated_at).
- **check_results**: id (UUID PK), target_id (FK → targets.id, cascade), status (enum: UP/DOWN), http_status, latency_ms, error (text), checked_at (timestamptz); индексы: idx(target_id, checked_at DESC), idx(checked_at).
- **incidents**: id (UUID PK), target_id (FK → targets.id, cascade), start_ts (timestamptz), end_ts (timestamptz nullable), last_status (enum), resolved (bool); индексы: idx(target_id, resolved), idx(start_ts), idx(end_ts).
- **notification_channels**: id (UUID PK), type (e.g., telegram), config (jsonb), is_active, created_at (timestamptz); индексы: idx(type, is_active).
- **notification_events**: id (UUID PK), incident_id (FK → incidents.id, cascade), channel_id (FK → notification_channels.id, cascade), status (queued/sent/failed), error (text), sent_at (timestamptz nullable), created_at (timestamptz); индексы: idx(status), idx(channel_id), idx(incident_id).
- **scheduler_state** (опционально для нескольких воркеров): id (UUID PK), target_id (unique FK), next_run_at (timestamptz), lease_owner (text), lease_expires_at (timestamptz); индексы: uniq(target_id), idx(next_run_at), idx(lease_expires_at).
- **materialized views / rollups (позже)**: агрегаты uptime/downtime/SLA за окна (24h/7d/30d); обновление по расписанию или при вставке batch.

### Связи и инварианты
- targets 1→N check_results; targets 1→N incidents.
- incidents 1→N notification_events; notification_events N→1 notification_channels.
- Один незакрытый инцидент per target: resolved=false уникален на уровне бизнес-логики (валидируется сервисом, можно добавить partial unique index target_id WHERE resolved=false).
- Notification events идемпотентны: при повторной отправке статус обновляется, запись не дублируется для одного события.
- Все временные поля в UTC (timestamptz); все идентификаторы — UUID.