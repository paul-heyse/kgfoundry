"""CLI helpers for inspecting canonical error codes.

Usage
-----
To list all known error codes:

```
uv run python -m tools.error_codes list
```

To show a single code:

```
uv run python -m tools.error_codes show KGF-DOC-BLD-001
```
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from tools._shared.error_codes import CANONICAL_ERROR_CODES, get_error_code


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for error codes CLI.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments to parse. Defaults to sys.argv if None.

    Returns
    -------
    argparse.Namespace
        Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Inspect canonical error codes.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List all known error codes")

    show_parser = subparsers.add_parser("show", help="Show details for a single code")
    show_parser.add_argument("code", help="Error code to display")
    show_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text)",
    )

    return parser.parse_args(argv)


def _cmd_list() -> int:
    """Print all known error codes in tab-separated format.

    Returns
    -------
    int
        Exit code: 0 on success.
    """
    for code in sorted(CANONICAL_ERROR_CODES):
        info = CANONICAL_ERROR_CODES[code]
        sys.stdout.write(f"{info.code}\t{info.title}\t{info.domain}/{info.category}\n")
    return 0


def _cmd_show(code: str, *, output_format: str) -> int:
    """Display metadata for a single error code.

    Parameters
    ----------
    code : str
        Error code to display.
    output_format : str
        Output format ('json' or 'text').

    Returns
    -------
    int
        Exit code: 0 on success, 1 on failure.
    """
    try:
        info = get_error_code(code)
    except KeyError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    if output_format == "json":
        json.dump(asdict(info), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    sys.stdout.write(f"Code      : {info.code}\n")
    sys.stdout.write(f"Title     : {info.title}\n")
    sys.stdout.write(f"Summary   : {info.summary}\n")
    sys.stdout.write(f"Domain    : {info.domain}\n")
    sys.stdout.write(f"Category  : {info.category}\n")
    sys.stdout.write(f"Severity  : {info.severity}\n")
    if info.remediation:
        sys.stdout.write(f"Remediate : {info.remediation}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the error code inspection CLI.

    Parameters
    ----------
    argv : list[str] | None
        Command-line arguments (None uses sys.argv).

    Returns
    -------
    int
        Exit code: 0 on success, 1 on failure.
    """
    args = _parse_args(argv)
    if args.command == "list":
        return _cmd_list()
    if args.command == "show":
        return _cmd_show(args.code, output_format=args.format)
    sys.stderr.write(f"Unknown command: {args.command}\n")
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
