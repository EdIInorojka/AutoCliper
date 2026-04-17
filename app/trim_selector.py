"""Simple Tk input range selector used by the launcher wizard."""

from __future__ import annotations

from typing import Optional


def _fmt_timestamp(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def select_input_range(
    title: str,
    duration_sec: float,
    initial_start_sec: float = 0.0,
    initial_end_sec: Optional[float] = None,
) -> Optional[tuple[float, float]]:
    try:
        import tkinter as tk
    except ImportError as exc:
        raise RuntimeError("Input range selector needs tkinter.") from exc

    duration_sec = max(1.0, float(duration_sec or 0.0))
    resolution = 0.5 if duration_sec <= 180 else 1.0
    min_gap = max(1.0, resolution)
    initial_end = duration_sec if initial_end_sec is None else max(min_gap, min(duration_sec, float(initial_end_sec)))
    initial_start = max(0.0, min(initial_start_sec, initial_end - min_gap))

    root = tk.Tk()
    root.title("StreamCuter Input Range")
    root.configure(bg="#111827")
    root.resizable(False, False)

    result: dict[str, tuple[float, float] | None] = {"value": None}

    shell = tk.Frame(root, bg="#111827", padx=18, pady=16)
    shell.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        shell,
        text="Выберите диапазон входного видео",
        bg="#111827",
        fg="#f8fafc",
        font=("Segoe UI", 15, "bold"),
        anchor="w",
    ).pack(fill=tk.X)
    tk.Label(
        shell,
        text=title,
        bg="#111827",
        fg="#94a3b8",
        font=("Segoe UI", 10),
        anchor="w",
        wraplength=680,
        justify=tk.LEFT,
    ).pack(fill=tk.X, pady=(4, 12))

    summary = tk.StringVar()

    value_panel = tk.Frame(shell, bg="#172033", padx=12, pady=10)
    value_panel.pack(fill=tk.X, pady=(0, 12))
    tk.Label(
        value_panel,
        textvariable=summary,
        bg="#172033",
        fg="#f8fafc",
        font=("Segoe UI", 11, "bold"),
        anchor="w",
    ).pack(fill=tk.X)

    def _update_summary() -> None:
        start_sec = float(start_scale.get())
        end_sec = float(end_scale.get())
        selected = max(0.0, end_sec - start_sec)
        summary.set(
            f"Начало: {_fmt_timestamp(start_sec)}    Конец: {_fmt_timestamp(end_sec)}    "
            f"Длина: {_fmt_timestamp(selected)} / {_fmt_timestamp(duration_sec)}"
        )

    def _sync_start(_value=None) -> None:
        start_sec = float(start_scale.get())
        end_sec = float(end_scale.get())
        if start_sec > end_sec - min_gap:
            start_sec = max(0.0, end_sec - min_gap)
            start_scale.set(start_sec)
        _update_summary()

    def _sync_end(_value=None) -> None:
        start_sec = float(start_scale.get())
        end_sec = float(end_scale.get())
        if end_sec < start_sec + min_gap:
            end_sec = min(duration_sec, start_sec + min_gap)
            end_scale.set(end_sec)
        _update_summary()

    start_block = tk.Frame(shell, bg="#111827")
    start_block.pack(fill=tk.X, pady=(0, 8))
    tk.Label(
        start_block,
        text="Начало",
        bg="#111827",
        fg="#f8fafc",
        font=("Segoe UI", 10, "bold"),
        anchor="w",
    ).pack(fill=tk.X)
    start_scale = tk.Scale(
        start_block,
        from_=0,
        to=duration_sec,
        resolution=resolution,
        orient=tk.HORIZONTAL,
        showvalue=False,
        highlightthickness=0,
        bd=0,
        bg="#172033",
        fg="#f8fafc",
        troughcolor="#334155",
        activebackground="#facc15",
        length=700,
        command=_sync_start,
    )
    start_scale.set(initial_start)
    start_scale.pack(fill=tk.X)

    end_block = tk.Frame(shell, bg="#111827")
    end_block.pack(fill=tk.X, pady=(0, 12))
    tk.Label(
        end_block,
        text="Конец",
        bg="#111827",
        fg="#f8fafc",
        font=("Segoe UI", 10, "bold"),
        anchor="w",
    ).pack(fill=tk.X)
    end_scale = tk.Scale(
        end_block,
        from_=0,
        to=duration_sec,
        resolution=resolution,
        orient=tk.HORIZONTAL,
        showvalue=False,
        highlightthickness=0,
        bd=0,
        bg="#172033",
        fg="#f8fafc",
        troughcolor="#334155",
        activebackground="#facc15",
        length=700,
        command=_sync_end,
    )
    end_scale.set(initial_end)
    end_scale.pack(fill=tk.X)

    buttons = tk.Frame(shell, bg="#111827")
    buttons.pack(fill=tk.X)

    def _apply() -> None:
        start_sec = max(0.0, float(start_scale.get()))
        end_sec = min(duration_sec, float(end_scale.get()))
        if end_sec <= start_sec:
            end_sec = min(duration_sec, start_sec + min_gap)
        result["value"] = (start_sec, end_sec)
        root.destroy()

    def _use_full() -> None:
        result["value"] = (0.0, duration_sec)
        root.destroy()

    def _cancel() -> None:
        result["value"] = None
        root.destroy()

    tk.Button(
        buttons,
        text="Целиком",
        command=_use_full,
        bg="#334155",
        fg="#f8fafc",
        activebackground="#475569",
        activeforeground="#f8fafc",
        relief=tk.FLAT,
        bd=0,
        padx=12,
        pady=8,
        cursor="hand2",
        font=("Segoe UI", 10, "bold"),
    ).pack(side=tk.LEFT)
    tk.Button(
        buttons,
        text="Отмена",
        command=_cancel,
        bg="#172033",
        fg="#f8fafc",
        activebackground="#334155",
        activeforeground="#f8fafc",
        relief=tk.FLAT,
        bd=0,
        padx=12,
        pady=8,
        cursor="hand2",
        font=("Segoe UI", 10, "bold"),
    ).pack(side=tk.RIGHT)
    tk.Button(
        buttons,
        text="Применить",
        command=_apply,
        bg="#facc15",
        fg="#111827",
        activebackground="#eab308",
        activeforeground="#111827",
        relief=tk.FLAT,
        bd=0,
        padx=14,
        pady=8,
        cursor="hand2",
        font=("Segoe UI", 10, "bold"),
    ).pack(side=tk.RIGHT, padx=(0, 8))

    root.protocol("WM_DELETE_WINDOW", _cancel)
    _update_summary()
    root.mainloop()
    return result["value"]
