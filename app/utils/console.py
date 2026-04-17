from __future__ import annotations

from dataclasses import dataclass
import re
import sys
from typing import Any

_RICH_CONSOLE = None


@dataclass
class _Console:
    """
    Minimal console wrapper that falls back to print() when rich isn't installed.
    Supports console.print("text") calls used across the project.
    """

    def print(self, *args: Any, **kwargs: Any) -> None:
        # If rich is available, use it for markup; otherwise plain print.
        try:
            global _RICH_CONSOLE
            if _RICH_CONSOLE is None:
                from rich.console import Console as RichConsole  # type: ignore

                _RICH_CONSOLE = RichConsole(legacy_windows=False)
            _RICH_CONSOLE.print(*args, **kwargs)
        except Exception:
            # Strip basic rich markup tags if present.
            msg = " ".join(str(a) for a in args)
            msg = re.sub(r"\[/?[^\]]+\]", "", msg)
            encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
            print(msg.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def get_console() -> _Console:
    return _Console()
