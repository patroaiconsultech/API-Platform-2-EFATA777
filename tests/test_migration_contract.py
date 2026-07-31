from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def render_migration_sql(root: Path, output_dir: Path) -> tuple[str, str]:
    env = os.environ.copy()
    source_dir = str(root / "src")
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        source_dir
        if not previous
        else source_dir + os.pathsep + previous
    )
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "render_migration_sql.py"),
            "--output-dir",
            str(output_dir),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    upgrade = (output_dir / "upgrade.sql").read_text(encoding="utf-8")
    downgrade = (output_dir / "downgrade.sql").read_text(encoding="utf-8")
    return upgrade, downgrade


def test_offline_schema_is_generated_self_contained(tmp_path):
    root = Path(__file__).resolve().parents[1]
    upgrade, downgrade = render_migration_sql(root, tmp_path)

    assert "CREATE TABLE threads" in upgrade
    assert "CREATE TABLE executions" in upgrade
    assert "CREATE TABLE messages" in upgrade
    assert "CREATE TABLE recovery_decisions" in upgrade
    assert "lease_owner" in upgrade
    assert "lease_expires_at" in upgrade
    assert "heartbeat_at" in upgrade
    assert "PRIMARY KEY (tenant_id, request_id)" in upgrade
    assert "UNIQUE (tenant_id, execution_id)" in upgrade
    assert "UNIQUE (tenant_id, execution_id, role)" in upgrade
    assert "FOREIGN KEY(tenant_id, thread_id)" in upgrade
    assert "DROP TABLE recovery_decisions" in downgrade
    assert "DROP TABLE messages" in downgrade
    assert "DROP TABLE executions" in downgrade
    assert "DROP TABLE threads" in downgrade


def test_alembic_premium_migration_declares_expected_revision():
    root = Path(__file__).resolve().parents[1]
    migration = (
        root
        / "migrations"
        / "versions"
        / "003_premium_execution_control.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "003_premium_execution_control"' in migration
    assert 'down_revision = "002_rc1_execution_idempotency"' in migration
    assert "ix_executions_lease_expiry" in migration
    assert "pk_recovery_decisions" in migration
