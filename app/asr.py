"""ASR (Automatic Speech Recognition) using faster-whisper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from app.config import AppConfig
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


_ASR_CACHE_VERSION = 5
_ASR_CHUNK_CACHE_VERSION = 1
_ASR_CHUNK_THRESHOLD_SEC = 900.0
_ASR_CHUNK_SEC = 300.0
_ASR_CHUNK_OVERLAP_SEC = 2.0


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
    from app.cache import load_json_cache, save_json_cache

    requested_language = (getattr(config, "language", "auto") or "auto").strip().lower()
    cache_extra = {
        "requested_language": requested_language,
        "env_model": os.environ.get("STREAMCUTER_WHISPER_MODEL", "").strip(),
        "word_timestamps": True,
        "vad": True,
        "version": _ASR_CACHE_VERSION,
    }
    cached = load_json_cache(config, "asr", video_path, cache_extra)
    if cached and isinstance(cached.get("words"), list):
        cached_lang = str(cached.get("language") or "").lower()
        if requested_language == "auto" and cached_lang in {"ru", "en"}:
            config.language = cached_lang
        words = cached["words"]
        console.print(f"[green]ASR cache hit: {len(words)} words[/green]")
        return words

    console.print("[cyan]Running ASR on video audio...[/cyan]")

    audio_wav = os.path.join(temp_dir, "asr_audio.wav")
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

    lang = requested_language
    if lang == "auto":
        lang = _detect_language(audio_wav, config)
        console.print(f"[dim]Detected language: {lang}[/dim]")
        if lang in {"ru", "en"}:
            config.language = lang

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        console.print("[yellow]faster-whisper not installed, skipping ASR[/yellow]")
        console.print("[dim]Install with: pip install faster-whisper[/dim]")
        return []

    model_size = _select_model(audio_duration, config, lang, requested_language=requested_language)
    device = "cpu"
    compute_type = "int8"
    cpu_threads = cpu_thread_budget()
    num_workers = _whisper_num_workers(cpu_threads)

    def _load_model():
        return WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            num_workers=num_workers,
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
    console.print(
        f"[dim]Whisper CPU budget: {cpu_threads} threads, {num_workers} worker(s)[/dim]"
    )

    transcribe_fn = (
        _transcribe_words_chunked
        if _should_chunk_asr(audio_duration)
        else _transcribe_words_monolithic
    )

    if _HAS_RICH_PROGRESS and _RICH_CONSOLE is not None:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=_RICH_CONSOLE,
        ) as progress:
            task = progress.add_task("Transcribing...", total=max(audio_duration, 1.0))
            try:
                words = transcribe_fn(
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
                save_json_cache(
                    config,
                    "asr",
                    video_path,
                    {"language": lang, "model": model_size, "words": words},
                    cache_extra,
                )
                return words
            except Exception as e:
                try:
                    progress.remove_task(task)
                except Exception:
                    pass
                console.print(f"[yellow]ASR transcription failed: {e}[/yellow]")
                console.print("[dim]Continuing without subtitles[/dim]")
                return []

    try:
        words = transcribe_fn(
            model=model,
            audio_wav=audio_wav,
            video_path=video_path,
            lang=lang,
            progress=None,
            task=None,
            audio_duration=audio_duration,
            config=config,
            model_size=model_size,
        )
        save_json_cache(
            config,
            "asr",
            video_path,
            {"language": lang, "model": model_size, "words": words},
            cache_extra,
        )
        return words
    except Exception as e:
        console.print(f"[yellow]ASR transcription failed: {e}[/yellow]")
        console.print("[dim]Continuing without subtitles[/dim]")
        return []


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
        info.language if info else lang,
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
    except ImportError as exc:
        console.print(
            "[yellow]soundfile unavailable, falling back to a single long ASR pass[/yellow]"
        )
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
                "version": _ASR_CACHE_VERSION,
                "chunk_version": _ASR_CHUNK_CACHE_VERSION,
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
                console.print(
                    f"[dim]ASR chunk {index}/{len(chunk_plan)} cache hit: {len(chunk_words)} words[/dim]"
                )
                continue

            console.print(
                f"[cyan]ASR chunk {index}/{len(chunk_plan)}: {core_start:.1f}s - {core_end:.1f}s[/cyan]"
            )
            chunk_audio = _read_audio_chunk(audio_file, sample_rate, load_start, load_end)
            segments, info, used_word_timestamps = _transcribe_segments(
                model,
                chunk_audio,
                lang,
            )
            if info and getattr(info, "language", None):
                detected_lang = str(info.language)

            chunk_words: list[dict] = []
            local_completed = load_start
            for segment in segments:
                segment_end = float(getattr(segment, "end", 0.0) or 0.0)
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
                        segment,
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


def _transcribe_segments(model, audio_input, lang: str) -> tuple[Any, Any, bool]:
    transcribe_kwargs = dict(
        language=lang if lang != "auto" else None,
        beam_size=5,
        condition_on_previous_text=False,
        word_timestamps=True,
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
        return segments, info, True
    except Exception as e:
        fallback_kwargs = dict(transcribe_kwargs)
        fallback_kwargs["word_timestamps"] = False
        fallback_kwargs["beam_size"] = 3
        console.print(
            f"[yellow]Word-level ASR failed ({e}); retrying with segment timing only[/yellow]"
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
    for word in sorted(words, key=lambda item: (float(item.get("start", 0.0)), float(item.get("end", 0.0)), str(item.get("word") or ""))):
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
    requested = (requested_language or getattr(config, "language", "auto") or "auto").strip().lower()

    if lang == "en" and requested == "en":
        return "medium.en"
    if lang == "ru":
        return "medium"
    if lang == "en":
        return "medium"

    if audio_duration_sec < 300:
        return "small"
    if audio_duration_sec < 1800:
        return "base"
    return "small"


def _whisper_num_workers(cpu_threads: int) -> int:
    if cpu_threads <= 4:
        return 1
    if cpu_threads <= 8:
        return 2
    return min(4, max(2, cpu_threads // 4))


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
            "small",
            device="cpu",
            compute_type="int8",
            download_root=_whisper_cache_dir(config),
        )

        _segments, info = model.transcribe(
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
