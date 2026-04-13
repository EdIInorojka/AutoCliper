"""E2E: обрезка входного MP4 + полный StreamCuter-пайплайн (реальные клипы в output)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Чтобы работал `python -m unittest tests.test_integration_e2e`
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _pick_test_video() -> Path | None:
    env = os.environ.get("STREAMCUTER_TEST_VIDEO", "").strip()
    if env:
        p = Path(env)
        return p if p.is_file() else None
    for pattern in ("*Slot*Wins*.mp4", "*slot*win*.mp4"):
        for p in ROOT.glob(pattern):
            if p.is_file():
                return p
    t = ROOT / "test_input.mp4"
    if t.is_file():
        return t
    return None


def _media_duration_sec(ffmpeg_bin: str, ffprobe_bin: str, video: Path) -> float:
    r = subprocess.run(
        [ffprobe_bin, "-v", "quiet", "-print_format", "json", "-show_format", str(video)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(json.loads(r.stdout).get("format", {}).get("duration", 0) or 0)


def _trim_video(ffmpeg_bin: str, src: Path, dest: Path, seconds: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # stream copy — быстро; если упадёт на некоторых файлах, перекодируем
    r = subprocess.run(
        [ffmpeg_bin, "-y", "-i", str(src), "-t", str(seconds), "-c", "copy", str(dest)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                str(src),
                "-t",
                str(seconds),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(dest),
            ],
            capture_output=True,
            check=True,
            text=True,
        )


@unittest.skipUnless(
    os.environ.get("STREAMCUTER_RUN_E2E", "").strip() in ("1", "true", "yes"),
    "Тяжёлый E2E: задайте STREAMCUTER_RUN_E2E=1 (и установите ffmpeg + pip install -r requirements-local.txt)",
)
class TestIntegrationE2E(unittest.TestCase):
    """Полный прогон CLI на укороченном фрагменте выбранного MP4."""

    def test_pipeline_on_short_slice_of_slot_wins(self) -> None:
        from app.utils.helpers import ensure_ffmpeg, ffmpeg_exe, ffprobe_exe, project_root

        self.assertTrue(
            ensure_ffmpeg(),
            "Нужны ffmpeg и ffprobe (PATH или tools/ffmpeg/bin). "
            "Установите через winget: winget install Gyan.FFmpeg",
        )

        video = _pick_test_video()
        self.assertIsNotNone(video, "Нет MP4: положите ролик в корень проекта или STREAMCUTER_TEST_VIDEO=путь")
        assert video is not None

        pr = project_root()
        ffmpeg_bin = ffmpeg_exe()
        ffprobe_bin = ffprobe_exe()

        dur = _media_duration_sec(ffmpeg_bin, ffprobe_bin, video)
        trim_sec = int(os.environ.get("STREAMCUTER_E2E_TRIM_SEC", "180"))
        if dur > trim_sec * 2:
            trimmed = pr / "temp" / "_e2e_trim_input.mp4"
            _trim_video(ffmpeg_bin, video, trimmed, trim_sec)
            work_input = trimmed
        else:
            work_input = video

        out_dir = pr / "output" / "_e2e_test"
        tmp_dir = pr / "temp" / "_e2e_run"
        shutil.rmtree(out_dir, ignore_errors=True)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            "-m",
            "app.main",
            "--input",
            str(work_input.resolve()),
            "--clips",
            "2",
            "--no-subs",
            "--no-music",
            "--output-dir",
            str(out_dir),
            "--temp-dir",
            str(tmp_dir),
        ]
        env = os.environ.copy()
        # Стабильный CTA для проверок
        env["STREAMCUTER_E2E"] = "1"
        r = subprocess.run(cmd, cwd=str(pr), env=env, capture_output=True, text=True)
        self.assertEqual(
            r.returncode,
            0,
            f"CLI failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}",
        )

        clips = list(out_dir.glob("*.mp4"))
        self.assertGreaterEqual(len(clips), 1, "Нет ни одного выходного .mp4")

        hard_max = 75.0 + 1.0  # небольшой зазор на контейнер
        for c in clips:
            d = _media_duration_sec(ffmpeg_bin, ffprobe_bin, c)
            self.assertLessEqual(
                d,
                hard_max,
                f"{c.name}: длительность {d}s > hard_max ~{hard_max}s",
            )
            self.assertGreater(d, 5.0, f"{c.name}: слишком короткий клип")


if __name__ == "__main__":
    unittest.main()
