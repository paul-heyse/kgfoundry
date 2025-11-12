"""Run import-linter against the generated tooling contracts."""

from __future__ import annotations

from pathlib import Path

# make_importlinter module removed - import-linter config is now static
# See importlinter.cfg and tools/lint/importlinter.typing.ini


def run() -> Path:
    """Return path to static import-linter configuration.

    Returns
    -------
    Path
        Path to the import-linter configuration file.
    """
    # Static config file location
    return Path("importlinter.cfg")


if __name__ == "__main__":  # pragma: no cover
    run()
