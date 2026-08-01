import orkio_platform.infrastructure.database as database_module
from orkio_platform.infrastructure.database import (
    create_database_engine,
    database_driver_descriptor,
    normalize_database_url,
)


def test_railway_postgresql_url_selects_psycopg3():
    normalized = normalize_database_url(
        "postgresql://user:password@host:5432/database"
    )
    assert normalized == (
        "postgresql+psycopg://"
        "user:password@host:5432/database"
    )


def test_legacy_postgres_url_selects_psycopg3():
    normalized = normalize_database_url(
        "postgres://user:password@host/database"
    )
    assert normalized.startswith("postgresql+psycopg://")


def test_explicit_psycopg_url_is_preserved():
    value = "postgresql+psycopg://user:password@host/database"
    assert normalize_database_url(value) == value


def test_sqlite_url_is_preserved():
    value = "sqlite+pysqlite:///:memory:"
    assert normalize_database_url(value) == value


def test_create_database_engine_forwards_psycopg3_url(monkeypatch):
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(
        database_module,
        "create_engine",
        fake_create_engine,
    )
    engine = create_database_engine(
        "postgresql://user:password@localhost:5432/database"
    )
    assert engine is not None
    assert captured["url"].startswith("postgresql+psycopg://")
    assert captured["kwargs"]["pool_pre_ping"] is True


def test_driver_descriptor_never_contains_credentials():
    descriptor = database_driver_descriptor(
        "postgresql://private_user:private_password@host/database"
    )
    assert descriptor == {
        "drivername": "postgresql+psycopg",
        "backend": "postgresql",
        "driver": "psycopg",
    }
    serialized = repr(descriptor)
    assert "private_user" not in serialized
    assert "private_password" not in serialized
