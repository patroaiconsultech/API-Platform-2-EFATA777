from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_mock_engine
from sqlalchemy.schema import DropTable

from orkio_platform.infrastructure.database import metadata


def render_sql(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    statements: list[str] = []

    def dump(sql, *multiparams, **params) -> None:
        compiled = sql.compile(dialect=engine.dialect)
        statements.append(str(compiled).rstrip() + ";")

    engine = create_mock_engine("postgresql+psycopg://", dump)
    metadata.create_all(engine, checkfirst=False)

    upgrade_path = output_dir / "upgrade.sql"
    upgrade_path.write_text(
        "\n\n".join(statements) + "\n",
        encoding="utf-8",
    )

    downgrade_statements = [
        str(DropTable(table).compile(dialect=engine.dialect)).rstrip() + ";"
        for table in reversed(metadata.sorted_tables)
    ]
    downgrade_path = output_dir / "downgrade.sql"
    downgrade_path.write_text(
        "\n\n".join(downgrade_statements) + "\n",
        encoding="utf-8",
    )
    return upgrade_path, downgrade_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render deterministic PostgreSQL schema SQL.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "migration_dry_run",
    )
    args = parser.parse_args()
    upgrade_path, downgrade_path = render_sql(args.output_dir)
    print(
        "rendered "
        f"{upgrade_path} and {downgrade_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
