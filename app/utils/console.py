from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Any


@dataclass
class _Console:
    """
    Minimal console wrapper that falls back to print() when rich isn't installed.
    Supports console.print("text") calls used across the project.
    """

    def print(self, *args: Any, **kwargs: Any) -> None:
        # If rich is available, use it for markup; otherwise plain print.
        try:
            from rich.console import Console as RichConsole  # type: ignore

            RichConsole(legacy_windows=False).print(*args, **kwargs)
        except Exception:
            # Strip basic rich markup tags if present.
            msg = " ".join(str(a) for a in args)
            for token in ("[bold cyan]", "[/bold cyan]", "[bold green]", "[/bold green]", "[cyan]", "[/cyan]", "[red]", "[/red]", "[yellow]", "[/yellow]", "[dim]", "[/dim]"):
                msg = msg.replace(token, "")
            encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
            print(msg.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def get_console() -> _Console:
    return _Console()
