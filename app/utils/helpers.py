"""Utility helpers."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

# Кэшируем только успешный поиск (после winget установка может завершиться позже).
_discovered_ff: Optional[Tuple[str, str]] = None


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _local_tools_bin_dir() -> Path:
    # tools/ffmpeg/bin/{ffmpeg,ffprobe}.exe
    return project_root() / "tools" / "ffmpeg" / "bin"


def _discover_winget_ffmpeg() -> Optional[Tuple[str, str]]:
    """Find ffmpeg/ffprobe after `winget install Gyan.FFmpeg` (often not on PATH until new shell)."""
    global _discovered_ff
    if _discovered_ff:
        return _discovered_ff
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return None
    pkg_root = Path(local) / "Microsoft" / "WinGet" / "Packages"
    if not pkg_root.is_dir():
        return None
    for child in pkg_root.iterdir():
        if "ffmpeg" not in child.name.lower():
            continue
        for ff in child.rglob("ffmpeg.exe"):
            fp = ff.parent / "ffprobe.exe"
            if fp.is_file():
                _discovered_ff = (str(ff), str(fp))
                return _discovered_ff
    return None


def ffmpeg_exe() -> str:
    p = _local_tools_bin_dir() / "ffmpeg.exe"
    if p.exists():
        return str(p)
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    pair = _discover_winget_ffmpeg()
    if pair:
        return pair[0]
    return "ffmpeg"


def ffprobe_exe() -> str:
    p = _local_tools_bin_dir() / "ffprobe.exe"
    if p.exists():
        return str(p)
    if shutil.which("ffprobe"):
        return "ffprobe"
    pair = _discover_winget_ffmpeg()
    if pair:
        return pair[1]
    return "ffprobe"


def ensure_ffmpeg() -> bool:
    """Check that ffmpeg and ffprobe are available."""
    p1 = _local_tools_bin_dir() / "ffmpeg.exe"
    p2 = _local_tools_bin_dir() / "ffprobe.exe"
    if p1.exists() and p2.exists():
        return True
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True
    pair = _discover_winget_ffmpeg()
    return pair is not None


def run_cmd(cmd: list[str], cwd: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a subprocess and return result."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        check=check,
    )


def safe_filename(name: str) -> str:
    """Make a filename safe for Windows."""
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name[:200]


def file_md5(path: str | Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def cpu_thread_budget(
    default_scale: float = 0.85,
    override_env: str = "STREAMCUTER_CPU_THREADS",
    scale_env: str = "STREAMCUTER_CPU_SCALE",
    reserve_one_core: bool = True,
) -> int:
    """Return a conservative CPU thread budget for local processing.

    The budget defaults to roughly 85% of logical cores and can be overridden
    with STREAMCUTER_CPU_THREADS or STREAMCUTER_CPU_SCALE.
    """
    raw_override = os.environ.get(override_env, "").strip()
    if raw_override and raw_override.lower() != "auto":
        try:
            value = int(raw_override)
            if value > 0:
                return value
        except ValueError:
            pass

    raw_scale = os.environ.get(scale_env, "").strip()
    try:
        scale = float(raw_scale) if raw_scale else float(default_scale)
    except ValueError:
        scale = float(default_scale)

    cpu_count = os.cpu_count() or 1
    budget = max(1, int(round(cpu_count * scale)))
    if reserve_one_core and cpu_count > 2:
        budget = min(budget, cpu_count - 1)
    return max(1, budget)


def remove_tree(path: str | Path) -> None:
    p = Path(path)
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)


def remove_file(path: str | Path) -> None:
    p = Path(path)
    if p.exists():
        p.unlink(missing_ok=True)


def fmt_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"
