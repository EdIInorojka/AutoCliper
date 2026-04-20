"""Highlight detection using audio energy, transcript density, and hook optimization."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.utils.console import get_console

from app.config import AppConfig
from app.probe import VideoInfo
from app.utils.helpers import ffmpeg_exe

console = get_console()


@dataclass
class HighlightCandidate:
    start_sec: float
    end_sec: float
    score: float
    peak_sec: float | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class HighlightSegment:
    start_sec: float
    end_sec: float
    score: float
    reasons: list[str] = field(default_factory=list)
    source: str = "scored"
    peak_sec: float | None = None
    hook_mode: str | None = None
    hook_reason: str | None = None
    hook_intro_score: float | None = None
    hook_text_preview: str | None = None
    question_like: bool = False


_STREAM_HOOK_KEYWORDS_EN = {
    "look", "wait", "watch", "stop", "now", "seriously", "actually", "crazy", "insane",
    "win", "won", "lose", "lost", "hit", "drop", "spin", "bro", "damn", "fuck", "shit",
}
_STREAM_HOOK_KEYWORDS_RU = {
    "смотри", "стой", "подожди", "сейчас", "реально", "серьезно", "жесть", "пиздец",
    "ебать", "выиграл", "слил", "занос", "спин", "смотрите", "нет",
}
_MOVIE_HOOK_KEYWORDS_EN = {
    "what", "why", "who", "how", "where", "when", "don't", "run", "look", "listen",
    "truth", "secret", "door", "kill", "dead", "hide", "please", "remember", "wait",
}
_MOVIE_HOOK_KEYWORDS_RU = {
    "что", "почему", "кто", "как", "где", "когда", "неужели", "разве", "беги", "стой",
    "смотри", "слушай", "правда", "тайна", "дверь", "убей", "мертв", "прячься", "подожди",
}
_QUESTION_WORDS_EN = {
    "what", "why", "how", "who", "where", "when", "is", "are", "do", "does", "did", "can",
    "will", "would", "should", "could", "was", "were", "am",
}
_QUESTION_WORDS_RU = {
    "что", "почему", "зачем", "как", "кто", "где", "когда", "неужели", "разве", "ли",
}


def _extract_audio_wav(video_path: str, temp_dir: str) -> str:
    """Extract audio from video as WAV for analysis."""
    out_path = os.path.join(temp_dir, "audio_analysis.wav")
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
        "8000",
        "-ac",
        "1",
        out_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_path


def _load_audio_samples(audio_path: str):
    """Load mono audio samples for analysis without librosa."""
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise ImportError("soundfile/numpy unavailable") from exc

    samples, sr = sf.read(audio_path, dtype="float32", always_2d=True)
    if samples.size == 0:
        return np.zeros(0, dtype=np.float32), 8000.0

    mono = samples.mean(axis=1, dtype=np.float32)
    return mono.astype(np.float32, copy=False), float(sr)


def _compute_audio_feature_bundle(audio_path: str) -> tuple[Any, Any, Any, float]:
    """Compute energy, brightness proxy, and onset proxy in one pass."""
    import numpy as np

    samples, sr = _load_audio_samples(audio_path)
    if samples.size == 0:
        zeros = np.zeros(1, dtype=np.float32)
        return zeros, zeros, zeros, sr

    frame_length = max(1024, int(round(sr * 2.0)))
    hop_length = max(512, int(round(sr * 1.0)))

    if samples.size < frame_length:
        samples = np.pad(samples, (0, frame_length - samples.size))

    starts = np.arange(0, samples.size - frame_length + 1, hop_length, dtype=np.int64)
    if starts.size == 0:
        starts = np.array([0], dtype=np.int64)

    squares = np.square(samples, dtype=np.float32)
    cumulative = np.concatenate(
        (np.zeros(1, dtype=np.float32), np.cumsum(squares, dtype=np.float32))
    )
    energy = cumulative[starts + frame_length] - cumulative[starts]
    rms = np.sqrt(energy / float(frame_length)).astype(np.float32)

    diffs = np.abs(np.diff(samples)).astype(np.float32, copy=False)
    if diffs.size == 0:
        brightness = np.zeros_like(rms)
    else:
        diff_cumulative = np.concatenate(
            (np.zeros(1, dtype=np.float32), np.cumsum(diffs, dtype=np.float32))
        )
        diff_starts = np.minimum(starts, diffs.size)
        diff_ends = np.minimum(starts + max(1, frame_length - 1), diffs.size)
        diff_energy = diff_cumulative[diff_ends] - diff_cumulative[diff_starts]
        brightness = (diff_energy / np.maximum(1, diff_ends - diff_starts)).astype(np.float32)

    rms_delta = np.maximum(0.0, np.diff(rms, prepend=rms[0]))
    brightness_delta = np.maximum(0.0, np.diff(brightness, prepend=brightness[0]))
    onset = (rms_delta + 0.5 * brightness_delta).astype(np.float32)

    return rms, brightness, onset, sr


def compute_audio_energy(audio_path: str) -> tuple[Any, float]:
    rms, _, _, sr = _compute_audio_feature_bundle(audio_path)
    return rms, sr


def compute_spectral_centroid(audio_path: str) -> Any:
    _, brightness, _, _ = _compute_audio_feature_bundle(audio_path)
    return brightness


def compute_onset_strength(audio_path: str) -> Any:
    _, _, onset, _ = _compute_audio_feature_bundle(audio_path)
    return onset


def _highlight_stage(step: int, total: int, message: str) -> None:
    console.print(f"[cyan][{step}/{total}] {message}[/cyan]")


def _highlight_feature_cache_extra(video_info: VideoInfo) -> dict[str, Any]:
    return {
        "version": 1,
        "duration": round(float(video_info.duration_sec or 0.0), 3),
        "analysis_rate": 8000,
        "frame_sec": 2.0,
        "hop_sec": 1.0,
    }


def find_highlights(
    video_path: str,
    video_info: VideoInfo,
    config: AppConfig,
    temp_dir: str,
    asr_segments: Optional[list[dict]] = None,
) -> list[HighlightSegment]:
    """
    Find highlight segments in the video.

    Uses multi-signal scoring:
    - Audio energy peaks
    - Spectral centroid spikes
    - Onset strength
    - Discovery transcript density (if available)

    Returns top-N segments sorted by score.
    """
    from app.cache import load_json_cache, save_json_cache

    cache_extra = _highlight_cache_extra(video_info, config, asr_segments)
    cached = load_json_cache(config, "highlights", video_path, cache_extra)
    if cached and isinstance(cached.get("segments"), list):
        segments = [_segment_from_dict(item) for item in cached["segments"]]
        if segments:
            console.print(f"[green]Highlight cache hit: {len(segments)} segments[/green]")
            return segments

    feature_cache_extra = _highlight_feature_cache_extra(video_info)
    audio_path = None
    rms = centroid = onset = sr = None

    _highlight_stage(1, 6, "Loading cached audio features...")
    feature_cached = load_json_cache(config, "highlight_features", video_path, feature_cache_extra)
    if feature_cached:
        try:
            import numpy as np

            rms = np.asarray(feature_cached.get("rms") or [], dtype=np.float32)
            centroid = np.asarray(feature_cached.get("centroid") or [], dtype=np.float32)
            onset = np.asarray(feature_cached.get("onset") or [], dtype=np.float32)
            sr = float(feature_cached.get("sr") or 0.0)
            if rms.size and centroid.size and onset.size and sr > 0:
                console.print(
                    f"[green]Highlight feature cache hit: {len(rms)} frames at {sr:.0f} Hz[/green]"
                )
            else:
                rms = centroid = onset = sr = None
        except Exception:
            rms = centroid = onset = sr = None

    if rms is None or centroid is None or onset is None or sr is None:
        _highlight_stage(2, 6, "Extracting audio for highlight analysis...")
        try:
            audio_path = _extract_audio_wav(video_path, temp_dir)
        except Exception as e:
            console.print(f"[yellow]Audio extraction failed, using fallback highlights: {e}[/yellow]")
            return _finalize_fallback_segments(video_path, video_info, config, cache_extra)

        if not os.path.exists(audio_path):
            console.print("[yellow]Audio extraction failed, using fallback highlights[/yellow]")
            return _finalize_fallback_segments(video_path, video_info, config, cache_extra)

        _highlight_stage(3, 6, "Computing audio features...")
        try:
            import numpy as np
            from scipy.ndimage import uniform_filter1d

            rms, centroid, onset, sr = _compute_audio_feature_bundle(audio_path)
            console.print(
                f"[dim]Audio features ready: {len(rms)} frames at {sr:.0f} Hz analysis rate[/dim]"
            )
            save_json_cache(
                config,
                "highlight_features",
                video_path,
                {
                    "rms": rms.tolist(),
                    "centroid": centroid.tolist(),
                    "onset": onset.tolist(),
                    "sr": sr,
                },
                feature_cache_extra,
            )
        except ImportError:
            console.print("[yellow]soundfile/scipy not installed; using fallback highlights[/yellow]")
            return _finalize_fallback_segments(video_path, video_info, config, cache_extra)
        except Exception as e:
            console.print(f"[yellow]Audio analysis failed, using fallback highlights: {e}[/yellow]")
            return _finalize_fallback_segments(video_path, video_info, config, cache_extra)
    else:
        import numpy as np
        from scipy.ndimage import uniform_filter1d

    def normalize(x):
        mx = np.max(x)
        if mx == 0:
            return np.zeros_like(x)
        return x / mx

    rms_norm = normalize(rms)
    centroid_norm = normalize(centroid)
    onset_norm = normalize(onset)

    min_len = min(len(rms_norm), len(centroid_norm), len(onset_norm))
    rms_norm = rms_norm[:min_len]
    centroid_norm = centroid_norm[:min_len]
    onset_norm = onset_norm[:min_len]

    hop_duration = 1.0 if sr <= 0 else (max(512, int(round(sr * 1.0))) / sr)
    combined = 0.4 * rms_norm + 0.3 * centroid_norm + 0.3 * onset_norm

    window_frames = max(3, int(5.0 / hop_duration))
    combined_smooth = uniform_filter1d(combined, size=window_frames)

    _highlight_stage(4, 6, "Merging ASR density...")
    if asr_segments:
        asr_density = np.zeros_like(combined_smooth)
        for segment_info in asr_segments:
            seg_start = float(segment_info.get("start", 0.0) or 0.0)
            seg_end = float(segment_info.get("end", seg_start) or seg_start)
            if seg_end <= seg_start:
                continue
            tokens = _tokenize_hook_text(str(segment_info.get("text", "") or ""))
            token_count = max(1, len(tokens))
            start_frame = max(0, int(seg_start / hop_duration))
            end_frame = min(len(asr_density), max(start_frame + 1, int(seg_end / hop_duration) + 1))
            asr_density[start_frame:end_frame] += token_count / max(1, end_frame - start_frame)
        if np.max(asr_density) > 0:
            asr_density = normalize(asr_density)
            combined_smooth = 0.7 * combined_smooth + 0.3 * asr_density

    _highlight_stage(5, 6, "Finding peaks...")
    threshold = np.mean(combined_smooth) + 0.5 * np.std(combined_smooth)
    peaks = _find_peaks(combined_smooth, threshold, min_distance_sec=8.0, hop_duration=hop_duration)

    _highlight_stage(6, 6, "Scoring candidates...")
    candidates: list[HighlightCandidate] = []
    preferred_dur = min(
        config.preferred_clip_duration_sec,
        config.max_clip_duration_sec,
        config.hard_max_clip_duration_sec,
    )
    max_dur = min(config.max_clip_duration_sec, config.hard_max_clip_duration_sec)
    min_dur = min(config.min_clip_duration_sec, max(1.0, video_info.duration_sec))

    for peak_frame in peaks:
        peak_sec = peak_frame * hop_duration
        half = preferred_dur / 2
        start = max(0, peak_sec - half)
        end = min(video_info.duration_sec, peak_sec + half)

        dur = end - start
        if dur < min_dur:
            expand = (min_dur - dur) / 2
            start = max(0, start - expand)
            end = min(video_info.duration_sec, end + expand)
            dur = end - start

        if dur > max_dur:
            end = start + max_dur
            dur = max_dur

        if dur < min_dur:
            continue

        start_frame = int(start / hop_duration)
        end_frame = int(end / hop_duration)
        window_score = float(np.mean(combined_smooth[start_frame:end_frame]))

        reasons = ["audio_energy"]
        if asr_segments:
            reasons.append("speech_density")

        candidates.append(
            HighlightCandidate(
                start_sec=start,
                end_sec=end,
                score=window_score,
                peak_sec=peak_sec,
                reasons=reasons,
            )
        )

    if not candidates:
        console.print("[yellow]No strong peaks found, using fallback highlights[/yellow]")
        return _finalize_fallback_segments(
            video_path,
            video_info,
            config,
            cache_extra,
            combined_smooth=combined_smooth,
            rms_norm=rms_norm,
            centroid_norm=centroid_norm,
            onset_norm=onset_norm,
            hop_duration=hop_duration,
            asr_segments=asr_segments,
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    segments = _deduplicate(candidates, min_gap=2.0)
    if not segments:
        console.print("[yellow]All candidates overlapped, using fallback highlights[/yellow]")
        return _finalize_fallback_segments(
            video_path,
            video_info,
            config,
            cache_extra,
            combined_smooth=combined_smooth,
            rms_norm=rms_norm,
            centroid_norm=centroid_norm,
            onset_norm=onset_norm,
            hop_duration=hop_duration,
            asr_segments=asr_segments,
        )

    target_count = _target_count(video_info, config)
    segments = segments[:target_count]
    if len(segments) < target_count:
        fallback = _fallback_highlights(video_info, config, emit_log=False)
        before = len(segments)
        segments = _fill_missing_segments(segments, fallback, target_count, min_gap=2.0)
        added = len(segments) - before
        if added:
            console.print(
                f"[yellow]Requested {target_count} clips; filled {added} extra "
                "non-overlapping fallback windows after strong highlights[/yellow]"
            )
        if len(segments) < target_count:
            console.print(
                f"[yellow]Requested {target_count} clips, but only {len(segments)} "
                "non-overlapping windows fit this video[/yellow]"
            )

    segments = _apply_duration_variation(segments, video_info, config)
    segments = _apply_hook_optimization(
        segments,
        combined_smooth,
        rms_norm,
        centroid_norm,
        onset_norm,
        hop_duration,
        asr_segments,
        video_path,
        video_info,
        config,
    )
    console.print(f"[green]Found {len(segments)} highlight segments[/green]")
    _save_highlight_cache(config, video_path, cache_extra, segments)
    return segments


def write_highlight_report(
    video_info: VideoInfo,
    segments: list[HighlightSegment],
    config: AppConfig,
    asr_metadata: Optional[dict[str, Any]] = None,
) -> Optional[Path]:
    """Write a JSON report explaining selected highlight windows."""
    report_name = getattr(config, "highlight_report_path", "") or "highlight_report.json"
    out_path = Path(report_name)
    if not out_path.is_absolute():
        out_path = Path(config.output_dir) / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "video": {
            "path": video_info.path,
            "duration_sec": video_info.duration_sec,
            "fps": video_info.fps,
            "width": video_info.width,
            "height": video_info.height,
        },
        "target_count": _target_count(video_info, config),
        "asr": asr_metadata or {},
        "segments": [_segment_to_dict(segment, index=i + 1) for i, segment in enumerate(segments)],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[cyan]Highlight report: {out_path}[/cyan]")
    return out_path


def _highlight_cache_extra(
    video_info: VideoInfo,
    config: AppConfig,
    asr_segments: Optional[list[dict]],
) -> dict[str, Any]:
    hook = getattr(config, "hook", None)
    return {
        "version": 5,
        "duration": round(float(video_info.duration_sec or 0.0), 3),
        "clips": config.clips_override,
        "target_per_hour": config.highlight_target_count_per_hour,
        "min": config.min_clip_duration_sec,
        "preferred": config.preferred_clip_duration_sec,
        "max": config.max_clip_duration_sec,
        "hard_max": config.hard_max_clip_duration_sec,
        "layout_mode": str(getattr(config, "layout_mode", "auto") or "auto").lower(),
        "duration_variation": bool(
            getattr(getattr(config, "variation", None), "enabled", False)
            and getattr(getattr(config, "variation", None), "clip_duration_variation", True)
        ),
        "duration_step_min": getattr(getattr(config, "variation", None), "clip_duration_step_min_sec", 2.0),
        "duration_step_max": getattr(getattr(config, "variation", None), "clip_duration_step_max_sec", 4.0),
        "duration_max_same": getattr(getattr(config, "variation", None), "clip_duration_max_same_sec", 2),
        "hook_enabled": bool(getattr(hook, "enabled", True)),
        "hook_strict_factual": bool(getattr(hook, "strict_factual", True)),
        "hook_intro_window_sec": float(getattr(hook, "intro_window_sec", 2.0)),
        "hook_search_backtrack_sec": float(getattr(hook, "search_backtrack_sec", 4.0)),
        "hook_search_forward_sec": float(getattr(hook, "search_forward_sec", 1.0)),
        "hook_question_bias": bool(getattr(hook, "question_bias", True)),
        "asr_segments": len(asr_segments or []),
        "asr_first": (asr_segments or [{}])[0].get("text") if asr_segments else "",
        "asr_last": (asr_segments or [{}])[-1].get("text") if asr_segments else "",
    }


def _save_highlight_cache(
    config: AppConfig,
    video_path: str,
    cache_extra: dict[str, Any],
    segments: list[HighlightSegment],
) -> None:
    from app.cache import save_json_cache

    save_json_cache(
        config,
        "highlights",
        video_path,
        {"segments": [_segment_to_dict(segment) for segment in segments]},
        cache_extra,
    )


def _segment_to_dict(segment: HighlightSegment, index: Optional[int] = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "start_sec": round(float(segment.start_sec), 3),
        "end_sec": round(float(segment.end_sec), 3),
        "duration_sec": round(float(segment.end_sec - segment.start_sec), 3),
        "score": round(float(segment.score), 6),
        "reasons": list(getattr(segment, "reasons", []) or []),
        "source": getattr(segment, "source", "scored"),
        "peak_sec": None if segment.peak_sec is None else round(float(segment.peak_sec), 3),
        "hook_mode": segment.hook_mode,
        "hook_reason": segment.hook_reason,
        "hook_intro_score": None if segment.hook_intro_score is None else round(float(segment.hook_intro_score), 6),
        "hook_text_preview": segment.hook_text_preview,
        "question_like": bool(segment.question_like),
    }
    if index is not None:
        payload["index"] = index
    return payload


def _segment_from_dict(item: Any) -> HighlightSegment:
    if not isinstance(item, dict):
        return HighlightSegment(0.0, 0.0, 0.0, [], "cache_invalid")
    return HighlightSegment(
        start_sec=float(item.get("start_sec", 0.0)),
        end_sec=float(item.get("end_sec", 0.0)),
        score=float(item.get("score", 0.0)),
        reasons=list(item.get("reasons") or []),
        source=str(item.get("source") or "cache"),
        peak_sec=float(item.get("peak_sec")) if item.get("peak_sec") is not None else None,
        hook_mode=item.get("hook_mode"),
        hook_reason=item.get("hook_reason"),
        hook_intro_score=float(item.get("hook_intro_score")) if item.get("hook_intro_score") is not None else None,
        hook_text_preview=item.get("hook_text_preview"),
        question_like=bool(item.get("question_like", False)),
    )


def _target_count(video_info: VideoInfo, config: AppConfig) -> int:
    target = config.clips_override or max(
        config.highlight_target_count_per_hour * (video_info.duration_sec / 3600),
        5,
    )
    return max(1, int(target))


def _find_peaks(
    signal: Any,
    threshold: float,
    min_distance_sec: float,
    hop_duration: float,
) -> list[int]:
    """Find local maxima above threshold with minimum distance."""
    min_distance_frames = max(1, int(min_distance_sec / max(hop_duration, 1e-6)))

    try:
        from scipy.signal import find_peaks as scipy_find_peaks

        peaks, _ = scipy_find_peaks(signal, height=threshold, distance=min_distance_frames)
        return [int(p) for p in peaks.tolist()]
    except Exception:
        pass

    peaks: list[int] = []
    last_peak = -min_distance_frames
    for idx in range(1, len(signal) - 1):
        value = signal[idx]
        if value <= threshold:
            continue
        if value < signal[idx - 1] or value < signal[idx + 1]:
            continue
        if idx - last_peak < min_distance_frames:
            if peaks and value > signal[peaks[-1]]:
                peaks[-1] = idx
                last_peak = idx
            continue
        peaks.append(idx)
        last_peak = idx

    if len(signal) == 1 and signal[0] > threshold:
        return [0]
    return peaks


def _deduplicate(
    candidates: list[HighlightCandidate],
    min_gap: float = 2.0,
) -> list[HighlightSegment]:
    """Remove overlapping candidates, keep highest scoring."""
    selected: list[HighlightSegment] = []
    for candidate in candidates:
        overlap = False
        for segment in selected:
            if candidate.start_sec < segment.end_sec + min_gap and candidate.end_sec > segment.start_sec - min_gap:
                overlap = True
                break
        if not overlap:
            selected.append(
                HighlightSegment(
                    start_sec=candidate.start_sec,
                    end_sec=candidate.end_sec,
                    score=candidate.score,
                    reasons=list(candidate.reasons),
                    source="scored",
                    peak_sec=candidate.peak_sec,
                )
            )
    return selected


def _fill_missing_segments(
    selected: list[HighlightSegment],
    fallback: list[HighlightSegment],
    target_count: int,
    min_gap: float = 2.0,
) -> list[HighlightSegment]:
    filled = selected[:]
    for candidate in fallback:
        if len(filled) >= target_count:
            break
        if _segment_overlaps(candidate, filled, min_gap=min_gap):
            continue
        filled.append(candidate)
    return filled


def _segment_overlaps(
    candidate: HighlightSegment,
    selected: list[HighlightSegment],
    min_gap: float = 2.0,
) -> bool:
    for segment in selected:
        if candidate.start_sec < segment.end_sec + min_gap and candidate.end_sec > segment.start_sec - min_gap:
            return True
    return False


def _apply_duration_variation(
    segments: list[HighlightSegment],
    video_info: VideoInfo,
    config: AppConfig,
) -> list[HighlightSegment]:
    """Shorten selected clips so batches do not all render with the same length."""
    variation = getattr(config, "variation", None)
    if (
        len(segments) <= 2
        or not getattr(variation, "enabled", False)
        or not getattr(variation, "clip_duration_variation", True)
    ):
        return segments

    max_same = max(1, int(getattr(variation, "clip_duration_max_same_sec", 2) or 2))
    if max_same >= len(segments):
        return segments

    step_min = max(0.5, float(getattr(variation, "clip_duration_step_min_sec", 2.0) or 2.0))
    step_max = max(step_min, float(getattr(variation, "clip_duration_step_max_sec", 4.0) or 4.0))
    step_mid = round((step_min + step_max) / 2.0, 2)
    step_pattern = [step_min, step_mid, step_max]

    min_duration = max(1.0, float(min(config.min_clip_duration_sec, config.hard_max_clip_duration_sec)))
    max_duration = max(
        min_duration,
        float(min(config.max_clip_duration_sec, config.hard_max_clip_duration_sec)),
    )
    current_durations = [max(0.0, float(segment.end_sec - segment.start_sec)) for segment in segments]
    if not current_durations:
        return segments

    base_duration = min(max(current_durations), max_duration)
    if base_duration < min_duration + step_min:
        return segments

    varied: list[HighlightSegment] = []
    duration_counts: dict[int, int] = {}
    cumulative_drop = 0.0
    changed = False

    for index, segment in enumerate(segments):
        current_duration = max(0.0, float(segment.end_sec - segment.start_sec))
        if current_duration <= 0:
            varied.append(segment)
            continue

        if index < max_same:
            target_duration = min(current_duration, base_duration)
        else:
            cumulative_drop += step_pattern[(index - max_same) % len(step_pattern)]
            target_duration = min(current_duration, base_duration - cumulative_drop)

        target_duration = max(min_duration, min(target_duration, current_duration, max_duration))
        rounded_duration = int(round(target_duration))
        while duration_counts.get(rounded_duration, 0) >= max_same and target_duration - step_min >= min_duration:
            target_duration -= step_min
            rounded_duration = int(round(target_duration))

        new_end = min(float(video_info.duration_sec), float(segment.start_sec + target_duration))
        actual_duration = max(0.0, new_end - segment.start_sec)
        if actual_duration < min_duration and current_duration >= min_duration:
            new_end = min(float(video_info.duration_sec), float(segment.start_sec + min_duration))
            actual_duration = max(0.0, new_end - segment.start_sec)

        rounded_actual = int(round(actual_duration))
        duration_counts[rounded_actual] = duration_counts.get(rounded_actual, 0) + 1

        if abs(actual_duration - current_duration) >= 0.25:
            changed = True
            reasons = list(getattr(segment, "reasons", []) or [])
            reasons.append(f"duration_variation_{current_duration:.1f}_to_{actual_duration:.1f}s")
            varied.append(
                HighlightSegment(
                    start_sec=segment.start_sec,
                    end_sec=new_end,
                    score=segment.score,
                    reasons=reasons,
                    source=segment.source,
                    peak_sec=segment.peak_sec,
                    hook_mode=segment.hook_mode,
                    hook_reason=segment.hook_reason,
                    hook_intro_score=segment.hook_intro_score,
                    hook_text_preview=segment.hook_text_preview,
                    question_like=segment.question_like,
                )
            )
        else:
            varied.append(segment)

    if changed:
        durations = ", ".join(f"{segment.end_sec - segment.start_sec:.1f}s" for segment in varied)
        console.print(f"[cyan]Clip duration variation: {durations}[/cyan]")
    return varied


def _apply_hook_optimization(
    segments: list[HighlightSegment],
    combined_smooth: Any,
    rms_norm: Any,
    centroid_norm: Any,
    onset_norm: Any,
    hop_duration: float | None,
    asr_segments: Optional[list[dict]],
    video_path: str,
    video_info: VideoInfo,
    config: AppConfig,
) -> list[HighlightSegment]:
    hook = getattr(config, "hook", None)
    if hook is None or not bool(getattr(hook, "enabled", True)):
        return segments

    hook_mode = _hook_mode(config)
    visual_signal = _load_visual_hook_signal(video_path, video_info, config) if hook_mode == "movie" else None
    optimized: list[HighlightSegment] = []
    changed = False

    for segment in segments:
        updated = _optimize_segment_hook(
            segment,
            combined_smooth,
            rms_norm,
            centroid_norm,
            onset_norm,
            hop_duration,
            asr_segments,
            visual_signal,
            video_info,
            config,
            hook_mode,
        )
        if abs(updated.start_sec - segment.start_sec) >= 0.05:
            changed = True
        optimized.append(updated)

    if changed:
        console.print(f"[cyan]Hook optimizer adjusted {sum(abs(a.start_sec - b.start_sec) >= 0.05 for a, b in zip(optimized, segments))} clip starts[/cyan]")
    return optimized


def _optimize_segment_hook(
    segment: HighlightSegment,
    combined_smooth: Any,
    rms_norm: Any,
    centroid_norm: Any,
    onset_norm: Any,
    hop_duration: float | None,
    asr_segments: Optional[list[dict]],
    visual_signal: Optional[dict[str, Any]],
    video_info: VideoInfo,
    config: AppConfig,
    hook_mode: str,
) -> HighlightSegment:
    hook = getattr(config, "hook", None)
    duration = max(0.1, float(segment.end_sec - segment.start_sec))
    peak_sec = float(segment.peak_sec if segment.peak_sec is not None else segment.start_sec + min(2.0, duration / 2.0))
    intro_window_sec = float(getattr(hook, "intro_window_sec", 2.0) or 2.0)
    search_backtrack_sec = float(getattr(hook, "search_backtrack_sec", 4.0) or 4.0)
    search_forward_sec = float(getattr(hook, "search_forward_sec", 1.0) or 1.0)

    earliest_start = max(0.0, peak_sec - search_backtrack_sec)
    latest_start = min(float(video_info.duration_sec) - duration, peak_sec + search_forward_sec)
    if latest_start < earliest_start:
        latest_start = earliest_start

    grid = _float_grid(earliest_start, latest_start, 0.25)
    if round(float(segment.start_sec), 3) not in {round(value, 3) for value in grid}:
        grid.append(float(segment.start_sec))

    best_score = -1e9
    best_start = float(segment.start_sec)
    best_reason = segment.hook_reason or "keep_original"
    best_preview = segment.hook_text_preview or ""
    best_question_like = bool(segment.question_like)

    for candidate_start in sorted(set(round(value, 3) for value in grid)):
        if candidate_start < 0:
            continue
        if candidate_start + duration > float(video_info.duration_sec) + 1e-6:
            continue
        if not (candidate_start <= peak_sec <= candidate_start + duration):
            continue

        intro_end = min(float(video_info.duration_sec), candidate_start + intro_window_sec)
        speech_preview = _hook_text_preview(asr_segments, candidate_start, candidate_start + 4.0)
        question_like = _is_question_like(speech_preview)

        intro_audio = _window_mean(combined_smooth, candidate_start, intro_end, hop_duration)
        early_burst = _window_mean(onset_norm, candidate_start, min(candidate_start + 1.0, intro_end), hop_duration)
        intro_energy = _window_mean(rms_norm, candidate_start, intro_end, hop_duration)
        transcript_density = _transcript_density(asr_segments, candidate_start, intro_end)
        keyword_bonus = _keyword_bonus(speech_preview, hook_mode)
        dead_air_penalty = 0.35 if intro_energy < 0.08 and transcript_density < 0.08 else 0.0

        visual_bonus = 0.0
        if hook_mode == "movie":
            visual_bonus = _visual_hook_score(visual_signal, candidate_start, intro_end)

        question_bonus = 0.0
        if getattr(hook, "question_bias", True) and question_like:
            question_bonus = 0.14 if hook_mode == "movie" else 0.08

        if getattr(hook, "strict_factual", True) and getattr(hook, "question_bias", True) and not question_like:
            question_bonus = 0.0

        shift_bonus = 0.0
        if candidate_start < segment.start_sec:
            shift_bonus = min(0.08, (float(segment.start_sec) - candidate_start) / max(search_backtrack_sec, 1.0) * 0.08)

        if hook_mode == "movie":
            score = (
                0.30 * intro_audio
                + 0.18 * early_burst
                + 0.20 * transcript_density
                + 0.16 * keyword_bonus
                + 0.16 * visual_bonus
                + question_bonus
                + shift_bonus
                - dead_air_penalty * 0.5
            )
        else:
            score = (
                0.34 * intro_audio
                + 0.26 * early_burst
                + 0.20 * transcript_density
                + 0.14 * keyword_bonus
                + question_bonus
                + shift_bonus
                - dead_air_penalty
            )

        reason = _hook_reason(
            question_like=question_like,
            visual_bonus=visual_bonus,
            keyword_bonus=keyword_bonus,
            dead_air_penalty=dead_air_penalty,
            original_start=float(segment.start_sec),
            candidate_start=candidate_start,
            hook_mode=hook_mode,
        )

        if score > best_score + 1e-6 or (abs(score - best_score) <= 1e-6 and candidate_start < best_start):
            best_score = score
            best_start = candidate_start
            best_reason = reason
            best_preview = speech_preview
            best_question_like = question_like

    return HighlightSegment(
        start_sec=best_start,
        end_sec=min(float(video_info.duration_sec), best_start + duration),
        score=segment.score,
        reasons=list(getattr(segment, "reasons", []) or []),
        source=segment.source,
        peak_sec=peak_sec,
        hook_mode=hook_mode,
        hook_reason=best_reason,
        hook_intro_score=best_score,
        hook_text_preview=best_preview,
        question_like=best_question_like,
    )


def _hook_reason(
    *,
    question_like: bool,
    visual_bonus: float,
    keyword_bonus: float,
    dead_air_penalty: float,
    original_start: float,
    candidate_start: float,
    hook_mode: str,
) -> str:
    if question_like:
        return "question_lead"
    if hook_mode == "movie" and visual_bonus >= 0.18:
        return "visual_tension"
    if keyword_bonus >= 0.18:
        return "dialogue_hook"
    if candidate_start + 0.25 < original_start and dead_air_penalty >= 0.2:
        return "dead_air_trim"
    return "cold_open_strength"


def _float_grid(start: float, end: float, step: float) -> list[float]:
    if end < start:
        return [start]
    values = []
    current = start
    while current <= end + 1e-6:
        values.append(round(current, 3))
        current += step
    return values


def _window_mean(signal: Any, start_sec: float, end_sec: float, hop_duration: float | None) -> float:
    if signal is None or hop_duration is None or hop_duration <= 0:
        return 0.0
    total = len(signal)
    if total <= 0:
        return 0.0
    start_index = max(0, int(start_sec / hop_duration))
    end_index = min(total, max(start_index + 1, int(end_sec / hop_duration) + 1))
    if end_index <= start_index:
        return 0.0
    return float(sum(float(v) for v in signal[start_index:end_index]) / max(1, end_index - start_index))


def _normalize_hook_text(text: str) -> str:
    value = str(text or "").replace("\n", " ").replace("\r", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _tokenize_hook_text(text: str) -> list[str]:
    normalized = _normalize_hook_text(text).lower()
    return re.findall(r"[A-Za-zА-Яа-яЁё0-9']+", normalized)


def _hook_text_preview(
    asr_segments: Optional[list[dict]],
    start_sec: float,
    end_sec: float,
) -> str:
    if not asr_segments:
        return ""
    parts: list[str] = []
    for segment in asr_segments:
        seg_start = float(segment.get("start", 0.0) or 0.0)
        seg_end = float(segment.get("end", seg_start) or seg_start)
        if seg_end < start_sec or seg_start > end_sec:
            continue
        text = _normalize_hook_text(segment.get("text", ""))
        if text:
            parts.append(text)
        if len(" ".join(parts)) >= 90:
            break
    return _normalize_hook_text(" ".join(parts))[:120]


def _is_question_like(text: str) -> bool:
    normalized = _normalize_hook_text(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    if "?" in normalized:
        return True
    tokens = _tokenize_hook_text(lowered)
    if not tokens:
        return False
    first = tokens[0]
    return first in _QUESTION_WORDS_EN or first in _QUESTION_WORDS_RU


def _keyword_bonus(text: str, hook_mode: str) -> float:
    tokens = _tokenize_hook_text(text)
    if not tokens:
        return 0.0
    if hook_mode == "movie":
        matches = sum(token in _MOVIE_HOOK_KEYWORDS_EN or token in _MOVIE_HOOK_KEYWORDS_RU for token in tokens)
        return min(1.0, matches / 3.0)
    matches = sum(token in _STREAM_HOOK_KEYWORDS_EN or token in _STREAM_HOOK_KEYWORDS_RU for token in tokens)
    return min(1.0, matches / 3.0)


def _transcript_density(
    asr_segments: Optional[list[dict]],
    start_sec: float,
    end_sec: float,
) -> float:
    if not asr_segments or end_sec <= start_sec:
        return 0.0
    total = 0.0
    for segment in asr_segments:
        seg_start = float(segment.get("start", 0.0) or 0.0)
        seg_end = float(segment.get("end", seg_start) or seg_start)
        overlap = max(0.0, min(seg_end, end_sec) - max(seg_start, start_sec))
        if overlap <= 0:
            continue
        tokens = _tokenize_hook_text(segment.get("text", ""))
        total += max(1, len(tokens)) * (overlap / max(0.1, seg_end - seg_start))
    density = total / max(1.0, end_sec - start_sec)
    return min(1.0, density / 4.0)


def _hook_mode(config: AppConfig) -> str:
    layout_mode = str(getattr(config, "layout_mode", "auto") or "auto").lower()
    return "movie" if layout_mode == "cinema" else "stream"


def _load_visual_hook_signal(
    video_path: str,
    video_info: VideoInfo,
    config: AppConfig,
) -> Optional[dict[str, Any]]:
    from app.cache import load_json_cache, save_json_cache

    cache_extra = {
        "version": 1,
        "duration": round(float(video_info.duration_sec or 0.0), 3),
        "step_sec": 1.0,
    }
    cached = load_json_cache(config, "highlight_visual", video_path, cache_extra)
    if cached and isinstance(cached.get("motion"), list):
        return {
            "motion": cached.get("motion") or [],
            "luma": cached.get("luma") or [],
            "step_sec": float(cached.get("step_sec") or 1.0),
        }

    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    sample_times = _float_grid(0.0, max(0.0, float(video_info.duration_sec) - 1.0), 1.0)
    motion: list[float] = []
    luma: list[float] = []
    prev_gray = None
    try:
        for sample_time in sample_times:
            cap.set(cv2.CAP_PROP_POS_MSEC, sample_time * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                motion.append(motion[-1] if motion else 0.0)
                luma.append(luma[-1] if luma else 0.0)
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (160, 90))
            luma_value = float(np.mean(small) / 255.0)
            if prev_gray is None:
                motion_value = 0.0
            else:
                motion_value = float(np.mean(cv2.absdiff(small, prev_gray)) / 255.0)
            motion.append(motion_value)
            luma.append(luma_value)
            prev_gray = small
    finally:
        cap.release()

    payload = {"motion": motion, "luma": luma, "step_sec": 1.0}
    save_json_cache(config, "highlight_visual", video_path, payload, cache_extra)
    return payload


def _visual_hook_score(
    signal: Optional[dict[str, Any]],
    start_sec: float,
    end_sec: float,
) -> float:
    if not signal:
        return 0.0
    step_sec = float(signal.get("step_sec") or 1.0)
    motion = signal.get("motion") or []
    luma = signal.get("luma") or []
    if not motion or not luma:
        return 0.0

    start_index = max(0, int(start_sec / max(step_sec, 0.1)))
    end_index = min(len(motion), max(start_index + 1, int(end_sec / max(step_sec, 0.1)) + 1))
    if end_index <= start_index:
        return 0.0

    motion_mean = sum(float(v) for v in motion[start_index:end_index]) / max(1, end_index - start_index)
    luma_slice = [float(v) for v in luma[start_index:end_index]]
    luma_delta = max(luma_slice) - min(luma_slice) if luma_slice else 0.0
    return min(1.0, motion_mean * 3.0 + luma_delta * 1.5)


def _finalize_fallback_segments(
    video_path: str,
    video_info: VideoInfo,
    config: AppConfig,
    cache_extra: dict[str, Any],
    *,
    combined_smooth: Any = None,
    rms_norm: Any = None,
    centroid_norm: Any = None,
    onset_norm: Any = None,
    hop_duration: float | None = None,
    asr_segments: Optional[list[dict]] = None,
) -> list[HighlightSegment]:
    segments = _fallback_highlights(video_info, config)
    segments = _apply_duration_variation(segments, video_info, config)
    segments = _apply_hook_optimization(
        segments,
        combined_smooth,
        rms_norm,
        centroid_norm,
        onset_norm,
        hop_duration,
        asr_segments,
        video_path,
        video_info,
        config,
    )
    _save_highlight_cache(config, video_path, cache_extra, segments)
    return segments


def _fallback_highlights(
    video_info: VideoInfo,
    config: AppConfig,
    emit_log: bool = True,
) -> list[HighlightSegment]:
    """Fallback: evenly spaced segments across the video."""
    if emit_log:
        console.print("[yellow]Using fallback highlight detection (even spacing)[/yellow]")
    duration = video_info.duration_sec
    preferred = min(
        config.preferred_clip_duration_sec,
        config.max_clip_duration_sec,
        config.hard_max_clip_duration_sec,
        duration,
    )
    min_duration = min(config.min_clip_duration_sec, duration)
    target = _target_count(video_info, config)

    segments: list[HighlightSegment] = []
    step = duration / max(target, 1)
    for index in range(int(target)):
        start = index * step
        end = min(start + preferred, duration)
        if end - start >= min_duration:
            peak_sec = min(end, start + min(2.0, (end - start) / 2.0))
            segments.append(
                HighlightSegment(
                    start_sec=start,
                    end_sec=end,
                    score=0.5,
                    reasons=["fallback_even_spacing"],
                    source="fallback",
                    peak_sec=peak_sec,
                )
            )
    if not segments and duration > 0:
        segments.append(
            HighlightSegment(
                start_sec=0.0,
                end_sec=duration,
                score=0.25,
                reasons=["fallback_full_video"],
                source="fallback",
                peak_sec=min(duration, 2.0),
            )
        )
    return segments
