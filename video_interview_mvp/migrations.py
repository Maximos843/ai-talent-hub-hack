"""Идемпотентные миграции схемы для SQLite.

Проект принципиально не делает разрушительных миграций: новые сущности живут в
отдельных таблицах и создаются через ``create_all``. Но часть полей обязана
лежать на существующих таблицах, иначе воронка кандидата размазывается по двум
источникам правды. SQLite умеет ``ALTER TABLE ADD COLUMN``, поэтому такие поля
добавляются здесь — безопасно и повторяемо.
"""
from sqlalchemy import inspect, text

from database import engine

# (таблица, колонка, DDL-тип со значением по умолчанию)
_ADDITIVE_COLUMNS = [
    ("vacancies", "status", "VARCHAR DEFAULT 'draft'"),
    ("vacancies", "closed_at", "DATETIME"),
    ("interview_sessions", "invited_at", "DATETIME"),
    ("interview_sessions", "consent_at", "DATETIME"),
    ("interview_sessions", "consent_version", "VARCHAR"),
    ("interview_sessions", "expires_at", "DATETIME"),
    ("candidate_profiles", "email", "VARCHAR"),
    ("candidate_profiles", "telegram_username", "VARCHAR"),
    ("candidate_profiles", "telegram_chat_id", "VARCHAR"),
    ("candidate_profiles", "telegram_linked_at", "DATETIME"),
]


def ensure_columns() -> list[str]:
    """Добавляет недостающие колонки. Возвращает список применённых изменений."""
    applied: list[str] = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, column, ddl in _ADDITIVE_COLUMNS:
            if table not in existing_tables:
                continue
            columns = {item["name"] for item in inspector.get_columns(table)}
            if column in columns:
                continue
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            applied.append(f"{table}.{column}")

        # Существующие вакансии с утверждённым пулом вопросов уже не черновики.
        if "vacancies" in existing_tables and "vacancies.status" in applied:
            connection.execute(
                text(
                    """
                    UPDATE vacancies SET status = 'active'
                    WHERE status = 'draft' AND id IN (
                        SELECT DISTINCT vacancy_id FROM session_questions WHERE is_approved = 1
                    )
                    """
                )
            )
            # Ссылка считалась отправленной в момент создания — сохраняем факт для
            # уже существующих кандидатов, чтобы канбан не сбросил их в первую колонку.
            connection.execute(
                text("UPDATE interview_sessions SET invited_at = created_at WHERE invited_at IS NULL")
            )
    return applied
