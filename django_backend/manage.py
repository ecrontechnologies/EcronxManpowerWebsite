#!/usr/bin/env python
"""Django management entry point for the Ecronx Manpower backend."""

import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ecronx.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Django is not installed or not on your PYTHONPATH. Activate the "
            "project virtual environment (.venv) and try again."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
