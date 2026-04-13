"""ASR (Automatic Speech Recognition) using faster-whisper."""

from __future__ import annotations

import os
from pathlib import Path
from app.config import AppConfig
from app.utils.console import get_console
from app.utils.helpers import ffmpeg_exe, ffprobe_exe

console = get_console()

try:
    from rich.console import Console as RichConsole
    from rich.progress import (
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    _RICH_CONSOLE = RichConsole()
    _HAS_RICH_PROGRESS = True
except ImportError:
    _RICH_CONSOLE = None
    _HAS_RICH_PROGRESS = False


def run_asr(
    video_path: str,
    temp_dir: str,
    config: AppConfig,
) -> list[dict]:
    """
    Run speech recognition on video audio.
    Returns list of word-level timing dicts.

    Each dict: {"word": str, "start": float, "end": float}
    """
    console.print("[cyan]Running ASR on video audio...[/cyan]")

    audio_wav = os.path.join(temp_dir, "asr_audio.wav")
    import subprocess

    cmd = [
        ffmpeg_exe(),
        "-y",
        "-i",
        video_path,
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        audio_wav,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not os.path.exists(audio_wav):
        console.print("[yellow]Audio extraction for ASR failed[/yellow]")
        return []

    audio_duration = _get_audio_duration(audio_wav)

    lang = config.language
    if lang == "auto":
        lang = _detect_language(audio_wav, config)
        console.print(f"[dim]Detected language: {lang}[/dim]")

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        console.print("[yellow]faster-whisper not installed, skipping ASR[/yellow]")
        console.print("[dim]Install with: pip install faster-whisper[/dim]")
        return []

    model_size = _select_model(audio_duration, config)
    device = "cpu"
    compute_type = "int8"

    def _load_model():
        return WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=_whisper_cache_dir(config),
        )

    if _HAS_RICH_PROGRESS and _RICH_CONSOLE is not None:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=_RICH_CONSOLE,
        ) as progress:
            task = progress.add_task(f"Loading Whisper ({model_size})...", total=None)
            try:
                model = _load_model()
            except Exception as e:
                progress.remove_task(task)
                console.print(f"[yellow]Failed to load Whisper model: {e}[/yellow]")
                console.print("[dim]Falling back to no-subtitle mode[/dim]")
                return []
            progress.remove_task(task)
    else:
        console.print(f"[dim]Loading Whisper ({model_size})...[/dim]")
        try:
            model = _load_model()
        except Exception as e:
            console.print(f"[yellow]Failed to load Whisper model: {e}[/yellow]")
            console.print("[dim]Falling back to no-subtitle mode[/dim]")
            return []

    console.print(f"[cyan]Transcribing {audio_duration:.0f}s of audio...[/cyan]")

    if _HAS_RICH_PROGRESS and _RICH_CONSOLE is not None:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=_RICH_CONSOLE,
        ) as progress:
            task = progress.add_task("Transcribing...", total=None)
            try:
                return _transcribe_words(model, audio_wav, lang, progress, task)
            except Exception as e:
                progress.remove_task(task)
                console.print(f"[yellow]ASR transcription failed: {e}[/yellow]")
                console.print("[dim]Continuing without subtitles[/dim]")
                return []
    try:
        return _transcribe_words(model, audio_wav, lang, None, None)
    except Exception as e:
        console.print(f"[yellow]ASR transcription failed: {e}[/yellow]")
        console.print("[dim]Continuing without subtitles[/dim]")
        return []


def _transcribe_words(model, audio_wav: str, lang: str, progress, task) -> list[dict]:
    segments, info = model.transcribe(
        audio_wav,
        language=lang if lang != "auto" else None,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
        ),
    )

    detected_lang = info.language if info else lang
    if progress is not None and task is not None:
        progress.update(task, description=f"Done ({detected_lang})")
        progress.remove_task(task)

    words = []
    for segment in segments:
        if segment.words:
            for word in segment.words:
                w = word.word.strip()
                if w:
                    words.append(
                        {
                            "word": w,
                            "start": word.start,
                            "end": word.end,
                        }
                    )

    console.print(f"[green]ASR complete: {len(words)} words[/green]")
    return words


def _select_model(audio_duration_sec: float, config: AppConfig) -> str:
    env_model = os.environ.get("STREAMCUTER_WHISPER_MODEL", "").strip()
    if env_model:
        return env_model
    if audio_duration_sec < 300:
        return "small"
    elif audio_duration_sec < 1800:
        return "base"
    else:
        return "tiny"


def _whisper_cache_dir(config: AppConfig) -> str:
    env_cache = os.environ.get("STREAMCUTER_WHISPER_CACHE", "").strip()
    cache_dir = env_cache or getattr(config, "whisper_model_cache_dir", "models/whisper")
    path = Path(cache_dir)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _detect_language(audio_wav: str, config: AppConfig) -> str:
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8",
            download_root=_whisper_cache_dir(config),
        )

        segments, info = model.transcribe(
            audio_wav,
            beam_size=1,
            language=None,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
            ),
        )

        detected = info.language
        lang_map = {
            "en": "en",
            "ru": "ru",
            "es": "es",
            "fr": "fr",
            "de": "de",
            "zh": "zh",
            "ja": "ja",
            "ko": "ko",
        }
        return lang_map.get(detected, "en")

    except Exception as e:
        console.print(f"[yellow]Language detection failed: {e}[/yellow]")
        return "en"


def _get_audio_duration(audio_wav: str) -> float:
    import json
    import subprocess

    cmd = [
        ffprobe_exe(),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        audio_wav,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0))
    except Exception:
        return 0.0
