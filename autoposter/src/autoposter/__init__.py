"""Autoposter — Semi-automated TLA+ monthly development update generator."""

from pathlib import Path

__version__ = "0.1.0"


def _find_project_root() -> Path:
    """Walk up from this file to find the directory containing config.yaml."""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / "config.yaml").exists():
            return current
        current = current.parent
    # Fallback: assume src/autoposter/ layout
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _find_project_root()
