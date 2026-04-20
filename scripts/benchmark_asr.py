r"""Benchmark legacy full-word ASR vs two-pass discovery ASR.

Usage:
    venv\Scripts\python.exe scripts\benchmark_asr.py --input path\to\video.mp4 --language en
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.asr import (  # noqa: E402
    _extract_audio_for_asr,
    benchmark_discovery_asr,
    benchmark_legacy_full_word_asr,
)
from app.config import AppConfig, load_config  # noqa: E402
from app.utils.helpers import ffmpeg_exe  # noqa: E402


def _load_app_config(args: argparse.Namespace) -> AppConfig:
    if args.config:
        config = load_config(Path(args.config))
    else:
        config = AppConfig()
    config.input = args.input
    if args.language:
        config.language = args.language
    config.subtitles_enabled = True
    config.output_dir = args.output_dir or config.output_dir
    if args.temp_dir:
        config.temp_dir = args.temp_dir
    return config


def _run_whispercpp_baseline(
    *,
    whispercpp_exe: str,
    whispercpp_model: str,
    input_video: str,
    language: str,
    temp_dir: str,
) -> dict:
    audio_wav = str(Path(temp_dir) / "benchmark_whispercpp.wav")
    if not _extract_audio_for_asr(input_video, audio_wav):
        raise RuntimeError("Failed to extract audio for whisper.cpp benchmark")

    exe_path = shutil.which(whispercpp_exe) or whispercpp_exe
    if not Path(exe_path).exists():
        raise RuntimeError(f"whisper.cpp executable not found: {whispercpp_exe}")

    cmd = [exe_path, "-m", whispercpp_model, "-f", audio_wav]
    if language in {"en", "ru"}:
        cmd.extend(["-l", language])
    cmd.append("-nt")

    started = time.perf_counter()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = round(time.perf_counter() - started, 3)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "whisper.cpp failed")

    return {
        "mode": "whisper.cpp",
        "seconds": elapsed,
        "timings": "segment",
        "language": language,
        "model": whispercpp_model,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark StreamCuter ASR modes")
    parser.add_argument("--input", required=True, help="Video file to benchmark")
    parser.add_argument("--config", help="Optional JSON/YAML config path")
    parser.add_argument("--language", choices=["auto", "en", "ru"], default="auto")
    parser.add_argument("--output", dest="output_path", help="Optional JSON report path")
    parser.add_argument("--output-dir", default="output", help="Working output directory for config")
    parser.add_argument("--temp-dir", help="Optional temp directory override")
    parser.add_argument("--skip-legacy", action="store_true", help="Skip legacy full-word ASR benchmark")
    parser.add_argument("--skip-discovery", action="store_true", help="Skip discovery ASR benchmark")
    parser.add_argument("--whispercpp-exe", help="Optional whisper.cpp CLI executable")
    parser.add_argument("--whispercpp-model", help="Optional whisper.cpp model path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input video not found: {input_path}")

    config = _load_app_config(args)
    results: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="streamcuter_asr_bench_") as td:
        temp_dir = args.temp_dir or td

        if not args.skip_legacy:
            results.append(benchmark_legacy_full_word_asr(str(input_path), temp_dir, config))

        if not args.skip_discovery:
            results.append(benchmark_discovery_asr(str(input_path), temp_dir, config))

        if args.whispercpp_exe and args.whispercpp_model:
            results.append(
                _run_whispercpp_baseline(
                    whispercpp_exe=args.whispercpp_exe,
                    whispercpp_model=args.whispercpp_model,
                    input_video=str(input_path),
                    language=config.language,
                    temp_dir=temp_dir,
                )
            )

    payload = {
        "input": str(input_path),
        "language": config.language,
        "ffmpeg": ffmpeg_exe(),
        "results": results,
    }

    if args.output_path:
        output_path = Path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote benchmark report: {output_path}")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
