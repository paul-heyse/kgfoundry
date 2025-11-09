"""Overview of migrate.

This module bundles migrate logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

import argparse
import pathlib
from contextlib import closing
from typing import cast

from kgfoundry_common.errors import RegistryError
from kgfoundry_common.navmap_loader import load_nav_metadata
from registry import duckdb_helpers
from registry.duckdb_helpers import DuckDBQueryOptions

__all__ = [
    "apply",
    "main",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor apply]
def apply(db: str, migrations_dir: str) -> None:
    """Apply migration SQL files to a DuckDB database.

    Reads all SQL files from the migrations directory in sorted order
    and executes them against the database. Skips errors related to
    missing Parquet table functions.

    Parameters
    ----------
    db : str
        Path to DuckDB database file.
    migrations_dir : str
        Directory containing migration SQL files.

    Raises
    ------
    RegistryError
        If migrations directory does not exist or migration execution fails.
    """
    path = pathlib.Path(migrations_dir)
    if not path.exists():
        error_message = "Migrations directory does not exist"
        raise RegistryError(
            error_message,
            context={"migrations_dir": str(path.resolve())},
        )

    with closing(duckdb_helpers.connect(db, pragmas={"threads": 4})) as con:
        for migration in sorted(path.glob("*.sql")):
            sql = migration.read_text()
            statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
            for statement in statements:
                try:
                    duckdb_helpers.execute(
                        con,
                        statement,
                        params=None,
                        options=DuckDBQueryOptions(
                            operation=f"registry.migrate.{migration.stem}",
                            require_parameterized=False,
                        ),
                    )
                except RegistryError as err:
                    message = err.message.lower()
                    if "read_parquet" in message and "table function" in message:
                        continue
                    raise


# [nav:anchor main]
def main() -> None:
    """CLI entrypoint for registry migration operations.

    Parses command-line arguments and executes the apply command to run migrations against a DuckDB
    database.
    """
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("apply")
    a.add_argument("--db", required=True)
    a.add_argument("--migrations", required=True)
    ns = ap.parse_args()
    db_arg = cast("str", ns.db)
    migrations_arg = cast("str", ns.migrations)
    cmd = cast("str", ns.cmd)
    if cmd == "apply":
        apply(db_arg, migrations_arg)


if __name__ == "__main__":
    main()
