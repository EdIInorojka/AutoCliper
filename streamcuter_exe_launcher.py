"""Tiny Windows EXE launcher for StreamCuter.

The heavy video stack stays in the project/venv; this executable only gives a
double-click entrypoint that starts the existing CMD wizard.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _project_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main() -> int:
    project_dir = _project_dir()
    wizard = project_dir / "generate_clips.cmd"
    runner = project_dir / "run_local.bat"

    if "--launcher-self-test" in sys.argv:
        print(f"ProjectDir: {project_dir}")
        print(f"Wizard: {'OK' if wizard.exists() else 'MISSING'} {wizard}")
        print(f"Runner: {'OK' if runner.exists() else 'MISSING'} {runner}")
        return 0 if wizard.exists() and runner.exists() else 1

    if not wizard.exists():
        print("ERROR: generate_clips.cmd was not found next to StreamCuter.exe.")
        print(f"Expected: {wizard}")
        input("Press Enter to close...")
        return 1

    if not runner.exists():
        print("ERROR: run_local.bat was not found next to StreamCuter.exe.")
        print(f"Expected: {runner}")
        input("Press Enter to close...")
        return 1

    if len(sys.argv) > 1:
        cmd = ["cmd.exe", "/c", str(runner), *sys.argv[1:]]
    else:
        cmd = ["cmd.exe", "/c", str(wizard)]

    exit_code = subprocess.call(cmd, cwd=str(project_dir))
    print()
    print(f"StreamCuter launcher finished with exit code {exit_code}.")
    input("Press Enter to close...")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
