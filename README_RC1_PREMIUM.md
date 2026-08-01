# ORKIO Backend — RC1 Premium Hardening R0.3

## Local validation

```bash
python -m pip install -e '.[test]'
python -m pytest -q
python -m alembic upgrade head --sql
python -m alembic downgrade head:base --sql
```

## Required test-environment variables

Copy `.env.example` to a local `.env` and provide an isolated `DATABASE_URL`.

## Safety status

```text
production_ready=false
automatic_recovery=false
remote_migration_not_authorized=true
```

This package includes execution leases, heartbeats, terminal cancellation,
recovery-decision audit records and structured execution logs. It does not
introduce real authentication, a production model provider or production
deployment authorization.

## R0.3.1 P0 database-driver hotfix

Railway-style `postgresql://` and legacy `postgres://` URLs are normalized to
`postgresql+psycopg://`, matching the installed Psycopg 3 dependency.

The same normalizer is used by the application engine and Alembic.

The startup observation records only:

```text
drivername
backend
driver
```

It never records the database URL, username, password, host or database name.

This hotfix changes no database schema and runs no migration automatically.
