import importlib


def test_development_config_respects_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@localhost:5432/testdb")

    config_module = importlib.reload(importlib.import_module("config"))
    db_uri = config_module.DevelopmentConfig.SQLALCHEMY_DATABASE_URI

    assert db_uri.startswith("postgresql://user:pass@localhost:5432/testdb")
    assert "sqlite:///assessment.db" not in db_uri
