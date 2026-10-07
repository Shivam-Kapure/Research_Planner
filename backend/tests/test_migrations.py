import pytest
from alembic import command
from alembic.script import ScriptDirectory
from fastapi import FastAPI

from tests.conftest import alembic_config, scalar

TABLES = ("users", "sessions", "user_provider_credentials")


@pytest.mark.anyio
async def test_migrated_schema_exists_at_head(app: FastAPI, migrated_database: str) -> None:
    cfg = alembic_config(migrated_database)
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert await scalar(app, "SELECT version_num FROM alembic_version") == head
    for table in TABLES:
        assert await scalar(app, "SELECT to_regclass(:t) IS NOT NULL", t=table) is True


def test_models_match_migrations(migrated_database: str) -> None:
    # Raises if autogenerate would detect any difference between models and the schema.
    command.check(alembic_config(migrated_database))


def test_downgrade_and_upgrade_round_trip(migrated_database: str) -> None:
    cfg = alembic_config(migrated_database)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # idempotent at head
    command.check(cfg)
