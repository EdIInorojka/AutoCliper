"""ASR helpers built on faster-whisper."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.config import AppConfig
from app.highlight_detector import HighlightSegment
from app.utils.console import get_console
from app.utils.helpers import cpu_thread_budget, ffmpeg_exe, ffprobe_exe

console = get_console()

try:
    from rich.console import Console as RichConsole
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    _RICH_CONSOLE = RichConsole()
    _HAS_RICH_PROGRESS = True
except ImportError:
    _RICH_CONSOLE = None
    _HAS_RICH_PROGRESS = False


_LEGACY_ASR_CACHE_VERSION = 6
_DISCOVERY_ASR_CACHE_VERSION = 1
_DISCOVERY_ASR_CHUNK_CACHE_VERSION = 1
_SUBTITLE_ASR_CACHE_VERSION = 1
_LANGUAGE_CACHE_VERSION = 1
_ASR_CHUNK_THRESHOLD_SEC = 900.0
_ASR_CHUNK_SEC = 300.0
_ASR_CHUNK_OVERLAP_SEC = 2.0
_MODEL_CACHE: dict[tuple[str, str, int, int, str], Any] = {}


@dataclass
class DiscoveryASRResult:
    language: str
    model: str
    segments: list[dict]
    mode: str = "two_pass_discovery"
    timings: str = "segment"


@dataclass
class SubtitleASRSession:
    language: str
    model_size: str
    cpu_threads: int
    compute_type: str = "int8"
    num_workers: int = 1
    model: Any | None = None


def run_asr(
    video_path: str,
    temp_dir: str,
    config: AppConfig,
) -> list[dict]:
    """
    Legacy full-input word timestamp ASR.

    This remains available for compatibility and benchmark comparison,
    but the production pipeline now uses discovery ASR + per-clip subtitle ASR.
    """
    from app.cache import load_json_cache, save_json_cache

    requested_language = (getattr(config, "language", "auto") or "auto").strip().lower()
    cache_extra = {
        "requested_language": requested_language,
        "env_model": os.environ.get("STREAMCUTER_WHISPER_MODEL", "").strip(),
        "word_timestamps": True,
        "vad": True,
        "version": _LEGACY_ASR_CACHE_VERSION,
    }
    cached = load_json_cache(config, "asr", video_path, cache_extra)
    if cached and isinstance(cached.get("words"), list):
        cached_lang = str(cached.get("language") or "").lower()
        if requested_language == "auto" and cached_lang in {"ru", "en"}:
            config.language = cached_lang
        words = cached["words"]
        console.print(f"[green]ASR cache hit: {len(words)} words[/green]")
        return words

    console.print("[cyan]Running legacy full-word ASR...[/cyan]")

    audio_wav = os.path.join(temp_dir, "asr_audio.wav")
    if not _extract_audio_for_asr(video_path, audio_wav):
        console.print("[yellow]Audio extraction for ASR failed[/yellow]")
        return []

    audio_duration = _get_audio_duration(audio_wav)
    lang = _resolve_requested_or_detected_language(
        video_path,
        audio_wav,
        audio_duration,
        config,
        requested_language,
    )

    model_size = _select_model(audio_duration, config, lang, requested_language=requested_language)
    cpu_threads = cpu_thread_budget()
    _configure_cpu_env(cpu_threads)
    console.print(f"[cyan]Transcribing {audio_duration:.0f}s of audio...[/cyan]")
    console.print(f"[dim]Whisper CPU budget: {cpu_threads} threads, 1 worker(s)[/dim]")

    def _run(progress=None, task=None):
        model = _load_whisper_model(
            model_size,
            config,
            cpu_threads=cpu_threads,
            compute_type="int8",
            num_workers=1,
        )
        transcribe_fn = (
            _transcribe_words_chunked
            if _should_chunk_asr(audio_duration)
            else _transcribe_words_monolithic
        )
        return transcribe_fn(
            model=model,
            audio_wav=audio_wav,
            video_path=video_path,
            lang=lang,
            progress=progress,
            task=task,
            audio_duration=audio_duration,
            config=config,
            model_size=model_size,
        )

    words = _run_with_asr_progress(
        description=f"Loading Whisper ({model_size})...",
        total=max(audio_duration, 1.0),
        work=_run,
        progress_description="Transcribing...",
    )
    if words is None:
        return []

    save_json_cache(
        config,
        "asr",
        video_path,
        {"language": lang, "model": model_size, "words": words},
        cache_extra,
    )
    return words


def run_discovery_asr(
    video_path: str,
    temp_dir: str,
    config: AppConfig,
) -> Optional[DiscoveryASRResult]:
    """Transcribe the whole selected input with segment timings only."""
    from app.cache import load_json_cache, save_json_cache

    requested_language = (getattr(config, "language", "auto") or "auto").strip().lower()
    cache_extra = {
        "requested_language": requested_language,
        "env_model": os.environ.get("STREAMCUTER_WHISPER_MODEL", "").strip(),
        "word_timestamps": False,
        "vad": True,
        "version": _DISCOVERY_ASR_CACHE_VERSION,
    }
    cached = load_json_cache(config, "asr_discovery", video_path, cache_extra)
    if cached and isinstance(cached.get("segments"), list):
        lang = str(cached.get("language") or requested_language or "auto")
        if requested_language == "auto" and lang in {"ru", "en"}:
            config.language = lang
        segments = _deduplicate_segment_rows(cached["segments"])
        console.print(f"[green]Discovery ASR cache hit: {len(segments)} segments[/green]")
        return DiscoveryASRResult(
            language=lang,
            model=str(cached.get("model") or ""),
            segments=segments,
        )

    console.print("[cyan]Running discovery ASR...[/cyan]")

    audio_wav = os.path.join(temp_dir, "asr_audio.wav")
    if not _extract_audio_for_asr(video_path, audio_wav):
        console.print("[yellow]Audio extraction for discovery ASR failed[/yellow]")
        return None

    audio_duration = _get_audio_duration(audio_wav)
    lang = _resolve_requested_or_detected_language(
        video_path,
        audio_wav,
        audio_duration,
        config,
        requested_language,
    )

    model_size = _select_model(audio_duration, config, lang, requested_language=requested_language)
    cpu_threads = cpu_thread_budget()
    _configure_cpu_env(cpu_threads)
    console.print(f"[cyan]Analyzing {audio_duration:.0f}s of speech for highlights...[/cyan]")
    console.print(f"[dim]Whisper CPU budget: {cpu_threads} threads, 1 worker(s)[/dim]")

    def _run(progress=None, task=None):
        model = _load_whisper_model(
            model_size,
            config,
            cpu_threads=cpu_threads,
            compute_type="int8",
            num_workers=1,
        )
        transcribe_fn = (
            _transcribe_segment_rows_chunked
            if _should_chunk_asr(audio_duration)
            else _transcribe_segment_rows_monolithic
        )
        return transcribe_fn(
            model=model,
            audio_wav=audio_wav,
            video_path=video_path,
            lang=lang,
            progress=progress,
            task=task,
            audio_duration=audio_duration,
            config=config,
            model_size=model_size,
        )

    segments = _run_with_asr_progress(
        description=f"Loading Whisper ({model_size})...",
        total=max(audio_duration, 1.0),
        work=_run,
        progress_description="Analyzing speech...",
    )
    if segments is None:
        return None

    result = DiscoveryASRResult(language=lang, model=model_size, segments=segments)
    save_json_cache(
        config,
        "asr_discovery",
        video_path,
        {
            "language": result.language,
            "model": result.model,
            "mode": result.mode,
            "timings": result.timings,
            "segments": result.segments,
        },
        cache_extra,
    )
    return result


def run_clip_subtitle_asr(
    video_path: str,
    segment: HighlightSegment,
    temp_dir: str,
    config: AppConfig,
    *,
    discovery_asr: DiscoveryASRResult | None = None,
    session: SubtitleASRSession | None = None,
) -> tuple[list[dict], SubtitleASRSession | None]:
    """Word-level ASR for one final clip window only."""
    from app.cache import load_json_cache, save_json_cache

    if not config.subtitles_enabled:
        return [], session

    language = _normalize_language_for_subtitles(discovery_asr.language if discovery_asr else config.language)
    requested_language = (language or "auto").strip().lower()
    duration = max(0.05, float(segment.end_sec - segment.start_sec))
    model_size = _select_model(duration, config, language, requested_language=requested_language)

    cache_extra = {
        "version": _SUBTITLE_ASR_CACHE_VERSION,
        "language": language,
        "model": model_size,
        "start_sec": round(float(segment.start_sec), 3),
        "end_sec": round(float(segment.end_sec), 3),
        "env_model": os.environ.get("STREAMCUTER_WHISPER_MODEL", "").strip(),
    }
    cached = load_json_cache(config, "asr_clip_words", video_path, cache_extra)
    if cached and isinstance(cached.get("words"), list):
        words = _deduplicate_words(cached["words"])
        console.print(f"[dim]Subtitle ASR cache hit: {len(words)} words[/dim]")
        return words, session

    if session is None or session.language != language or session.model_size != model_size:
        cpu_threads = cpu_thread_budget()
        _configure_cpu_env(cpu_threads)
        session = SubtitleASRSession(
            language=language,
            model_size=model_size,
            cpu_threads=cpu_threads,
        )
    if session.model is None:
        session.model = _load_whisper_model(
            session.model_size,
            config,
            cpu_threads=session.cpu_threads,
            compute_type=session.compute_type,
            num_workers=session.num_workers,
        )

    clip_key = f"{int(round(segment.start_sec * 1000))}_{int(round(segment.end_sec * 1000))}"
    audio_wav = os.path.join(temp_dir, f"subtitle_asr_{clip_key}.wav")
    if not _extract_audio_for_asr(
        video_path,
        audio_wav,
        start_sec=float(segment.start_sec),
        duration_sec=duration,
    ):
        console.print("[yellow]Subtitle ASR extraction failed; rendering clip without subtitles[/yellow]")
        return [], session

    console.print(
        f"[dim]Subtitle ASR: {duration:.1f}s window with {session.model_size}[/dim]"
    )
    try:
        segments, info, used_word_timestamps = _transcribe_segments(
            session.model,
            audio_wav,
            language,
            word_timestamps=True,
        )
    except Exception as exc:
        console.print(f"[yellow]Subtitle ASR failed, clip will render without subtitles: {exc}[/yellow]")
        return [], session

    words: list[dict] = []
    for whisper_segment in segments:
        words.extend(
            _segment_to_words(
                whisper_segment,
                used_word_timestamps=used_word_timestamps,
                absolute_offset=float(segment.start_sec),
            )
        )

    words = _deduplicate_words(words)
    save_json_cache(
        config,
        "asr_clip_words",
        video_path,
        {
            "language": str(getattr(info, "language", language) or language),
            "model": session.model_size,
            "words": words,
        },
        cache_extra,
    )
    return words, session


def benchmark_legacy_full_word_asr(
    video_path: str,
    temp_dir: str,
    config: AppConfig,
) -> dict[str, Any]:
    started = time.perf_counter()
    words = run_asr(video_path, temp_dir, config)
    return {
        "mode": "legacy_full_words",
        "seconds": round(time.perf_counter() - started, 3),
        "items": len(words),
        "timings": "word",
    }


def benchmark_discovery_asr(
    video_path: str,
    temp_dir: str,
    config: AppConfig,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = run_discovery_asr(video_path, temp_dir, config)
    return {
        "mode": "two_pass_discovery",
        "seconds": round(time.perf_counter() - started, 3),
        "items": len(result.segments) if result else 0,
        "timings": result.timings if result else "segment",
        "language": result.language if result else "unknown",
        "model": result.model if result else "",
    }


def _extract_audio_for_asr(
    video_path: str,
    out_path: str,
    *,
    start_sec: float | None = None,
    duration_sec: float | None = None,
) -> bool:
    cmd = [ffmpeg_exe(), "-y"]
    if start_sec is not None:
        cmd.extend(["-ss", f"{float(start_sec):.3f}"])
    cmd.extend(["-i", video_path])
    if duration_sec is not None:
        cmd.extend(["-t", f"{float(duration_sec):.3f}"])
    cmd.extend(
        [
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            out_path,
        ]
    )
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 0 and os.path.exists(out_path)


def _run_with_asr_progress(
    *,
    description: str,
    total: float,
    work,
    progress_description: str,
):
    if _HAS_RICH_PROGRESS and _RICH_CONSOLE is not None:
        try:
            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=None),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=_RICH_CONSOLE,
            ) as progress:
                task = progress.add_task(progress_description or description, total=max(total, 1.0))
                return work(progress, task)
        except Exception as exc:
            console.print(f"[yellow]ASR failed: {exc}[/yellow]")
            console.print("[dim]Continuing without subtitles[/dim]")
            return None

    try:
        return work()
    except Exception as exc:
        console.print(f"[yellow]ASR failed: {exc}[/yellow]")
        console.print("[dim]Continuing without subtitles[/dim]")
        return None


def _transcribe_words_monolithic(
    model,
    audio_wav: str,
    video_path: str,
    lang: str,
    progress,
    task,
    audio_duration: float,
    config: AppConfig,
    model_size: str,
) -> list[dict]:
    segments, info, used_word_timestamps = _transcribe_segments(
        model,
        audio_wav,
        lang,
        word_timestamps=True,
    )

    words = []
    last_completed = 0.0
    last_reported_pct = -1
    for segment in segments:
        if audio_duration > 0:
            completed = min(float(segment.end or 0.0), audio_duration)
            if completed < last_completed:
                completed = last_completed
            last_completed = completed
            pct = int(round((completed / audio_duration) * 100))
            _update_asr_progress(
                progress,
                task,
                completed,
                audio_duration,
                f"Transcribing... {pct}%",
                last_reported_pct,
            )
            last_reported_pct = pct

        words.extend(
            _segment_to_words(
                segment,
                used_word_timestamps=used_word_timestamps,
                absolute_offset=0.0,
            )
        )

    return _finalize_asr_words(
        words,
        getattr(info, "language", lang) if info else lang,
        progress,
        task,
        audio_duration,
    )


def _transcribe_words_chunked(
    model,
    audio_wav: str,
    video_path: str,
    lang: str,
    progress,
    task,
    audio_duration: float,
    config: AppConfig,
    model_size: str,
) -> list[dict]:
    from app.cache import load_json_cache, save_json_cache

    try:
        import soundfile as sf
    except ImportError:
        console.print("[yellow]soundfile unavailable, falling back to a single long ASR pass[/yellow]")
        return _transcribe_words_monolithic(
            model=model,
            audio_wav=audio_wav,
            video_path=video_path,
            lang=lang,
            progress=progress,
            task=task,
            audio_duration=audio_duration,
            config=config,
            model_size=model_size,
        )

    chunk_plan = _build_asr_chunk_plan(audio_duration)
    console.print(
        f"[dim]Chunked ASR enabled: {len(chunk_plan)} chunk(s) of ~{_ASR_CHUNK_SEC:.0f}s[/dim]"
    )

    all_words: list[dict] = []
    detected_lang = lang
    last_reported_pct = -1

    with sf.SoundFile(audio_wav) as audio_file:
        sample_rate = float(audio_file.samplerate or 16000)

        for index, chunk in enumerate(chunk_plan, start=1):
            core_start = chunk["core_start"]
            core_end = chunk["core_end"]
            load_start = chunk["load_start"]
            load_end = chunk["load_end"]
            chunk_extra = {
                "version": _LEGACY_ASR_CACHE_VERSION,
                "chunk_version": 2,
                "language": lang,
                "model": model_size,
                "chunk_index": index,
                "chunk_count": len(chunk_plan),
                "core_start": round(core_start, 3),
                "core_end": round(core_end, 3),
                "load_start": round(load_start, 3),
                "load_end": round(load_end, 3),
                "env_model": os.environ.get("STREAMCUTER_WHISPER_MODEL", "").strip(),
            }

            cached = load_json_cache(config, "asr_chunks", video_path, chunk_extra)
            if cached and isinstance(cached.get("words"), list):
                chunk_words = cached["words"]
                all_words.extend(chunk_words)
                detected_lang = str(cached.get("language") or detected_lang)
                _update_asr_progress(
                    progress,
                    task,
                    min(core_end, audio_duration),
                    audio_duration,
                    f"Transcribing chunk {index}/{len(chunk_plan)} (cache)",
                    last_reported_pct,
                )
                last_reported_pct = int(round((min(core_end, audio_duration) / max(audio_duration, 1.0)) * 100))
                continue

            console.print(
                f"[cyan]ASR chunk {index}/{len(chunk_plan)}: {core_start:.1f}s - {core_end:.1f}s[/cyan]"
            )
            chunk_audio = _read_audio_chunk(audio_file, sample_rate, load_start, load_end)
            segments, info, used_word_timestamps = _transcribe_segments(
                model,
                chunk_audio,
                lang,
                word_timestamps=True,
            )
            if info and getattr(info, "language", None):
                detected_lang = str(info.language)

            chunk_words: list[dict] = []
            local_completed = load_start
            for whisper_segment in segments:
                segment_end = float(getattr(whisper_segment, "end", 0.0) or 0.0)
                absolute_completed = min(load_start + segment_end, audio_duration)
                if absolute_completed < local_completed:
                    absolute_completed = local_completed
                local_completed = absolute_completed
                overall_completed = min(max(core_start, absolute_completed), audio_duration)
                pct = int(round((overall_completed / max(audio_duration, 1.0)) * 100))
                _update_asr_progress(
                    progress,
                    task,
                    overall_completed,
                    audio_duration,
                    f"Transcribing chunk {index}/{len(chunk_plan)}... {pct}%",
                    last_reported_pct,
                )
                last_reported_pct = pct

                chunk_words.extend(
                    _segment_to_words(
                        whisper_segment,
                        used_word_timestamps=used_word_timestamps,
                        absolute_offset=load_start,
                        keep_start=core_start,
                        keep_end=core_end,
                        keep_end_inclusive=index == len(chunk_plan),
                    )
                )

            chunk_words = _deduplicate_words(chunk_words)
            save_json_cache(
                config,
                "asr_chunks",
                video_path,
                {
                    "language": detected_lang,
                    "model": model_size,
                    "words": chunk_words,
                },
                chunk_extra,
            )
            all_words.extend(chunk_words)
            _update_asr_progress(
                progress,
                task,
                min(core_end, audio_duration),
                audio_duration,
                f"Transcribing chunk {index}/{len(chunk_plan)} done",
                last_reported_pct,
            )
            last_reported_pct = int(round((min(core_end, audio_duration) / max(audio_duration, 1.0)) * 100))

    return _finalize_asr_words(
        all_words,
        detected_lang,
        progress,
        task,
        audio_duration,
    )


def _transcribe_segment_rows_monolithic(
    model,
    audio_wav: str,
    video_path: str,
    lang: str,
    progress,
    task,
    audio_duration: float,
    config: AppConfig,
    model_size: str,
) -> list[dict]:
    segments, info, _ = _transcribe_segments(
        model,
        audio_wav,
        lang,
        word_timestamps=False,
    )

    rows: list[dict] = []
    last_completed = 0.0
    last_reported_pct = -1
    for whisper_segment in segments:
        if audio_duration > 0:
            completed = min(float(whisper_segment.end or 0.0), audio_duration)
            if completed < last_completed:
                completed = last_completed
            last_completed = completed
            pct = int(round((completed / audio_duration) * 100))
            _update_asr_progress(
                progress,
                task,
                completed,
                audio_duration,
                f"Analyzing speech... {pct}%",
                last_reported_pct,
            )
            last_reported_pct = pct

        rows.extend(_segment_to_rows(whisper_segment, absolute_offset=0.0))

    return _finalize_discovery_segments(
        rows,
        getattr(info, "language", lang) if info else lang,
        progress,
        task,
        audio_duration,
    )


def _transcribe_segment_rows_chunked(
    model,
    audio_wav: str,
    video_path: str,
    lang: str,
    progress,
    task,
    audio_duration: float,
    config: AppConfig,
    model_size: str,
) -> list[dict]:
    from app.cache import load_json_cache, save_json_cache

    try:
        import soundfile as sf
    except ImportError:
        console.print("[yellow]soundfile unavailable, falling back to single discovery ASR pass[/yellow]")
        return _transcribe_segment_rows_monolithic(
            model=model,
            audio_wav=audio_wav,
            video_path=video_path,
            lang=lang,
            progress=progress,
            task=task,
            audio_duration=audio_duration,
            config=config,
            model_size=model_size,
        )

    chunk_plan = _build_asr_chunk_plan(audio_duration)
    console.print(
        f"[dim]Chunked discovery ASR enabled: {len(chunk_plan)} chunk(s) of ~{_ASR_CHUNK_SEC:.0f}s[/dim]"
    )

    all_segments: list[dict] = []
    detected_lang = lang
    last_reported_pct = -1

    with sf.SoundFile(audio_wav) as audio_file:
        sample_rate = float(audio_file.samplerate or 16000)

        for index, chunk in enumerate(chunk_plan, start=1):
            core_start = chunk["core_start"]
            core_end = chunk["core_end"]
            load_start = chunk["load_start"]
            load_end = chunk["load_end"]
            chunk_extra = {
                "version": _DISCOVERY_ASR_CACHE_VERSION,
                "chunk_version": _DISCOVERY_ASR_CHUNK_CACHE_VERSION,
                "language": lang,
                "model": model_size,
                "chunk_index": index,
                "chunk_count": len(chunk_plan),
                "core_start": round(core_start, 3),
                "core_end": round(core_end, 3),
                "load_start": round(load_start, 3),
                "load_end": round(load_end, 3),
                "env_model": os.environ.get("STREAMCUTER_WHISPER_MODEL", "").strip(),
            }

            cached = load_json_cache(config, "asr_discovery_chunks", video_path, chunk_extra)
            if cached and isinstance(cached.get("segments"), list):
                chunk_rows = _deduplicate_segment_rows(cached["segments"])
                all_segments.extend(chunk_rows)
                detected_lang = str(cached.get("language") or detected_lang)
                _update_asr_progress(
                    progress,
                    task,
                    min(core_end, audio_duration),
                    audio_duration,
                    f"Analyzing chunk {index}/{len(chunk_plan)} (cache)",
                    last_reported_pct,
                )
                last_reported_pct = int(round((min(core_end, audio_duration) / max(audio_duration, 1.0)) * 100))
                continue

            console.print(
                f"[cyan]Discovery chunk {index}/{len(chunk_plan)}: {core_start:.1f}s - {core_end:.1f}s[/cyan]"
            )
            chunk_audio = _read_audio_chunk(audio_file, sample_rate, load_start, load_end)
            segments, info, _ = _transcribe_segments(
                model,
                chunk_audio,
                lang,
                word_timestamps=False,
            )
            if info and getattr(info, "language", None):
                detected_lang = str(info.language)

            chunk_rows: list[dict] = []
            local_completed = load_start
            for whisper_segment in segments:
                segment_end = float(getattr(whisper_segment, "end", 0.0) or 0.0)
                absolute_completed = min(load_start + segment_end, audio_duration)
                if absolute_completed < local_completed:
                    absolute_completed = local_completed
                local_completed = absolute_completed
                overall_completed = min(max(core_start, absolute_completed), audio_duration)
                pct = int(round((overall_completed / max(audio_duration, 1.0)) * 100))
                _update_asr_progress(
                    progress,
                    task,
                    overall_completed,
                    audio_duration,
                    f"Analyzing chunk {index}/{len(chunk_plan)}... {pct}%",
                    last_reported_pct,
                )
                last_reported_pct = pct

                chunk_rows.extend(
                    _segment_to_rows(
                        whisper_segment,
                        absolute_offset=load_start,
                        keep_start=core_start,
                        keep_end=core_end,
                        keep_end_inclusive=index == len(chunk_plan),
                    )
                )

            chunk_rows = _deduplicate_segment_rows(chunk_rows)
            save_json_cache(
                config,
                "asr_discovery_chunks",
                video_path,
                {
                    "language": detected_lang,
                    "model": model_size,
                    "segments": chunk_rows,
                },
                chunk_extra,
            )
            all_segments.extend(chunk_rows)
            _update_asr_progress(
                progress,
                task,
                min(core_end, audio_duration),
                audio_duration,
                f"Analyzing chunk {index}/{len(chunk_plan)} done",
                last_reported_pct,
            )
            last_reported_pct = int(round((min(core_end, audio_duration) / max(audio_duration, 1.0)) * 100))

    return _finalize_discovery_segments(
        all_segments,
        detected_lang,
        progress,
        task,
        audio_duration,
    )


def _resolve_requested_or_detected_language(
    video_path: str,
    audio_wav: str,
    audio_duration: float,
    config: AppConfig,
    requested_language: str,
) -> str:
    if requested_language in {"ru", "en"}:
        config.language = requested_language
        return requested_language

    detected = _load_or_detect_language(video_path, audio_wav, config)
    if detected in {"ru", "en"}:
        config.language = detected
        return detected
    if audio_duration > 0 and requested_language == "auto":
        return "en"
    return requested_language or "en"


def _load_or_detect_language(video_path: str, audio_wav: str, config: AppConfig) -> str:
    from app.cache import load_json_cache, save_json_cache

    cache_extra = {
        "version": _LANGUAGE_CACHE_VERSION,
        "env_model": os.environ.get("STREAMCUTER_WHISPER_MODEL", "").strip(),
    }
    cached = load_json_cache(config, "asr_language", video_path, cache_extra)
    if cached and cached.get("language"):
        return str(cached["language"]).lower()

    detected = _detect_language(audio_wav, config)
    save_json_cache(
        config,
        "asr_language",
        video_path,
        {"language": detected},
        cache_extra,
    )
    return detected


def _configure_cpu_env(cpu_threads: int) -> None:
    thread_text = str(max(1, int(cpu_threads)))
    os.environ["OMP_NUM_THREADS"] = thread_text
    os.environ["MKL_NUM_THREADS"] = thread_text
    os.environ["OPENBLAS_NUM_THREADS"] = thread_text


def _load_whisper_model(
    model_size: str,
    config: AppConfig,
    *,
    cpu_threads: int,
    compute_type: str,
    num_workers: int,
):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("faster-whisper not installed")

    cache_dir = _whisper_cache_dir(config)
    key = (model_size, compute_type, int(cpu_threads), int(num_workers), cache_dir)
    model = _MODEL_CACHE.get(key)
    if model is not None:
        return model

    model = WhisperModel(
        model_size,
        device="cpu",
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        num_workers=num_workers,
        download_root=cache_dir,
    )
    _MODEL_CACHE[key] = model
    return model


def _transcribe_segments(
    model,
    audio_input,
    lang: str,
    *,
    word_timestamps: bool,
) -> tuple[Any, Any, bool]:
    transcribe_kwargs = dict(
        language=lang if lang != "auto" else None,
        beam_size=5,
        condition_on_previous_text=False,
        word_timestamps=word_timestamps,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
        ),
    )

    def _run_transcribe(kwargs: dict) -> tuple[Any, Any]:
        try:
            return model.transcribe(audio_input, **kwargs)
        except TypeError:
            kwargs = dict(kwargs)
            kwargs.pop("condition_on_previous_text", None)
            return model.transcribe(audio_input, **kwargs)

    try:
        segments, info = _run_transcribe(transcribe_kwargs)
        return segments, info, bool(word_timestamps)
    except Exception as exc:
        if not word_timestamps:
            raise
        fallback_kwargs = dict(transcribe_kwargs)
        fallback_kwargs["word_timestamps"] = False
        fallback_kwargs["beam_size"] = 3
        console.print(
            f"[yellow]Word-level ASR failed ({exc}); retrying with segment timing only[/yellow]"
        )
        segments, info = _run_transcribe(fallback_kwargs)
        return segments, info, False


def _segment_to_words(
    segment,
    used_word_timestamps: bool,
    absolute_offset: float,
    keep_start: float | None = None,
    keep_end: float | None = None,
    keep_end_inclusive: bool = False,
) -> list[dict]:
    words: list[dict] = []
    segment_words = getattr(segment, "words", None) if used_word_timestamps else None
    if segment_words:
        for word in segment.words:
            text = str(word.word or "").strip()
            if not text:
                continue
            word_start = absolute_offset + float(word.start or 0.0)
            word_end = absolute_offset + float(word.end or word.start or 0.0)
            if _word_within_core(word_start, word_end, keep_start, keep_end, keep_end_inclusive):
                words.append({"word": text, "start": word_start, "end": word_end})
        return words

    segment_text = str(getattr(segment, "text", "") or "").strip()
    if not segment_text:
        return words

    segment_start = absolute_offset + float(getattr(segment, "start", 0.0) or 0.0)
    segment_end = absolute_offset + float(getattr(segment, "end", getattr(segment, "start", 0.0)) or 0.0)
    segment_tokens = [token for token in segment_text.split() if token]
    if not segment_tokens:
        return words

    duration = max(0.0, segment_end - segment_start)
    step = duration / len(segment_tokens) if duration > 0 else 0.0
    for token_index, token in enumerate(segment_tokens):
        token_start = segment_start + (token_index * step)
        token_end = segment_start + ((token_index + 1) * step) if step > 0 else segment_end
        if _word_within_core(token_start, token_end, keep_start, keep_end, keep_end_inclusive):
            words.append({"word": token, "start": token_start, "end": token_end})
    return words


def _segment_to_rows(
    segment,
    absolute_offset: float,
    keep_start: float | None = None,
    keep_end: float | None = None,
    keep_end_inclusive: bool = False,
) -> list[dict]:
    text = str(getattr(segment, "text", "") or "").strip()
    if not text:
        return []

    start = absolute_offset + float(getattr(segment, "start", 0.0) or 0.0)
    end = absolute_offset + float(getattr(segment, "end", getattr(segment, "start", 0.0)) or 0.0)
    if not _word_within_core(start, end, keep_start, keep_end, keep_end_inclusive):
        return []
    if end < start:
        end = start
    return [{"text": text, "start": start, "end": end}]


def _word_within_core(
    word_start: float,
    word_end: float,
    keep_start: float | None,
    keep_end: float | None,
    keep_end_inclusive: bool,
) -> bool:
    if keep_start is None or keep_end is None:
        return True
    midpoint = (word_start + max(word_start, word_end)) / 2.0
    if midpoint < keep_start:
        return False
    if keep_end_inclusive:
        return midpoint <= keep_end
    return midpoint < keep_end


def _build_asr_chunk_plan(audio_duration: float) -> list[dict[str, float]]:
    chunks: list[dict[str, float]] = []
    core_start = 0.0
    while core_start < audio_duration:
        core_end = min(audio_duration, core_start + _ASR_CHUNK_SEC)
        chunks.append(
            {
                "core_start": core_start,
                "core_end": core_end,
                "load_start": max(0.0, core_start - _ASR_CHUNK_OVERLAP_SEC),
                "load_end": min(audio_duration, core_end + _ASR_CHUNK_OVERLAP_SEC),
            }
        )
        core_start = core_end
    return chunks


def _read_audio_chunk(audio_file, sample_rate: float, start_sec: float, end_sec: float):
    import numpy as np

    start_frame = max(0, int(round(start_sec * sample_rate)))
    frame_count = max(1, int(round((end_sec - start_sec) * sample_rate)))
    audio_file.seek(start_frame)
    data = audio_file.read(frames=frame_count, dtype="float32", always_2d=False)
    if data is None:
        return np.zeros(1, dtype=np.float32)
    array = np.asarray(data, dtype=np.float32)
    if array.ndim > 1:
        array = array.mean(axis=1, dtype=np.float32)
    if array.size == 0:
        return np.zeros(1, dtype=np.float32)
    return array


def _deduplicate_words(words: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for word in sorted(
        words,
        key=lambda item: (
            float(item.get("start", 0.0)),
            float(item.get("end", 0.0)),
            str(item.get("word") or ""),
        ),
    ):
        text = str(word.get("word") or "").strip()
        if not text:
            continue
        start = float(word.get("start", 0.0) or 0.0)
        end = float(word.get("end", start) or start)
        if end < start:
            end = start
        normalized = {
            "word": text,
            "start": round(start, 3),
            "end": round(end, 3),
        }
        if cleaned:
            prev = cleaned[-1]
            if (
                prev["word"] == normalized["word"]
                and abs(prev["start"] - normalized["start"]) <= 0.05
                and abs(prev["end"] - normalized["end"]) <= 0.05
            ):
                continue
        cleaned.append(normalized)
    return cleaned


def _deduplicate_segment_rows(rows: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for row in sorted(
        rows,
        key=lambda item: (
            float(item.get("start", 0.0)),
            float(item.get("end", 0.0)),
            str(item.get("text") or ""),
        ),
    ):
        text = " ".join(str(row.get("text") or "").split()).strip()
        if not text:
            continue
        start = float(row.get("start", 0.0) or 0.0)
        end = float(row.get("end", start) or start)
        if end < start:
            end = start
        normalized = {
            "text": text,
            "start": round(start, 3),
            "end": round(end, 3),
        }
        if cleaned:
            prev = cleaned[-1]
            if (
                prev["text"] == normalized["text"]
                and abs(prev["start"] - normalized["start"]) <= 0.05
                and abs(prev["end"] - normalized["end"]) <= 0.05
            ):
                continue
        cleaned.append(normalized)
    return cleaned


def _finalize_asr_words(
    words: list[dict],
    detected_lang: str,
    progress,
    task,
    total_duration: float,
) -> list[dict]:
    words = _deduplicate_words(words)
    if progress is not None and task is not None:
        progress.update(
            task,
            completed=max(total_duration, 1.0),
            description=f"Done ({detected_lang})",
        )
        progress.remove_task(task)
    console.print(f"[green]ASR complete: {len(words)} words[/green]")
    return words


def _finalize_discovery_segments(
    rows: list[dict],
    detected_lang: str,
    progress,
    task,
    total_duration: float,
) -> list[dict]:
    rows = _deduplicate_segment_rows(rows)
    if progress is not None and task is not None:
        progress.update(
            task,
            completed=max(total_duration, 1.0),
            description=f"Done ({detected_lang})",
        )
        progress.remove_task(task)
    console.print(f"[green]Discovery ASR complete: {len(rows)} segments[/green]")
    return rows


def _update_asr_progress(
    progress,
    task,
    completed: float,
    total: float,
    description: str,
    last_reported_pct: int,
) -> None:
    if progress is not None and task is not None:
        progress.update(task, completed=min(completed, total), description=description)
        return
    pct = int(round((min(completed, total) / max(total, 1.0)) * 100))
    if pct // 10 > last_reported_pct // 10:
        console.print(f"[dim]{description}[/dim]")


def _should_chunk_asr(audio_duration_sec: float) -> bool:
    return audio_duration_sec >= _ASR_CHUNK_THRESHOLD_SEC


def _select_model(
    audio_duration_sec: float,
    config: AppConfig,
    language: str | None = None,
    requested_language: str | None = None,
) -> str:
    env_model = os.environ.get("STREAMCUTER_WHISPER_MODEL", "").strip()
    if env_model:
        return env_model

    lang = (language or getattr(config, "language", "auto") or "auto").strip().lower()
    if lang == "en":
        return "medium.en"
    if lang == "ru":
        return "medium"

    if audio_duration_sec < 300:
        return "small"
    if audio_duration_sec < 1800:
        return "base"
    return "small"


def _whisper_num_workers(cpu_threads: int) -> int:
    return 1


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
        cpu_threads = cpu_thread_budget()
        _configure_cpu_env(cpu_threads)
        model = _load_whisper_model(
            "small",
            config,
            cpu_threads=cpu_threads,
            compute_type="int8",
            num_workers=1,
        )

        _segments, info = model.transcribe(
            audio_wav,
            beam_size=1,
            language=None,
            word_timestamps=False,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
            ),
        )

        detected = str(getattr(info, "language", "") or "").lower()
        return detected if detected in {"en", "ru"} else "en"

    except Exception as e:
        console.print(f"[yellow]Language detection failed: {e}[/yellow]")
        return "en"


def _get_audio_duration(audio_wav: str) -> float:
    import json

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


def _normalize_language_for_subtitles(language: str | None) -> str:
    lang = str(language or "auto").strip().lower()
    if lang in {"ru", "en"}:
        return lang
    return "en"
