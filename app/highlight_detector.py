"""Highlight detection using audio energy, scene changes, and ASR signals."""

from __future__ import annotations

import os
import json
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
    reasons: list[str] = field(default_factory=list)


@dataclass
class HighlightSegment:
    start_sec: float
    end_sec: float
    score: float
    reasons: list[str] = field(default_factory=list)
    source: str = "scored"


def _extract_audio_wav(video_path: str, temp_dir: str) -> str:
    """Extract audio from video as WAV for analysis."""
    out_path = os.path.join(temp_dir, "audio_analysis.wav")
    import subprocess
    cmd = [
        ffmpeg_exe(), "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "8000", "-ac", "1",
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

    # Coarse windows keep the analysis responsive on very long clips.
    frame_length = max(1024, int(round(sr * 2.0)))
    hop_length = max(512, int(round(sr * 1.0)))

    if samples.size < frame_length:
        samples = np.pad(samples, (0, frame_length - samples.size))

    starts = np.arange(0, samples.size - frame_length + 1, hop_length, dtype=np.int64)
    if starts.size == 0:
        starts = np.array([0], dtype=np.int64)

    squares = np.square(samples, dtype=np.float32)
    cumulative = np.concatenate((
        np.zeros(1, dtype=np.float32),
        np.cumsum(squares, dtype=np.float32),
    ))
    energy = cumulative[starts + frame_length] - cumulative[starts]
    rms = np.sqrt(energy / float(frame_length)).astype(np.float32)

    diffs = np.abs(np.diff(samples)).astype(np.float32, copy=False)
    if diffs.size == 0:
        brightness = np.zeros_like(rms)
    else:
        diff_cumulative = np.concatenate((
            np.zeros(1, dtype=np.float32),
            np.cumsum(diffs, dtype=np.float32),
        ))
        diff_starts = np.minimum(starts, diffs.size)
        diff_ends = np.minimum(starts + max(1, frame_length - 1), diffs.size)
        diff_energy = diff_cumulative[diff_ends] - diff_cumulative[diff_starts]
        brightness = (diff_energy / np.maximum(1, diff_ends - diff_starts)).astype(np.float32)

    rms_delta = np.maximum(0.0, np.diff(rms, prepend=rms[0]))
    brightness_delta = np.maximum(0.0, np.diff(brightness, prepend=brightness[0]))
    onset = (rms_delta + 0.5 * brightness_delta).astype(np.float32)

    return rms, brightness, onset, sr


def compute_audio_energy(audio_path: str) -> tuple[Any, float]:
    """Compute per-frame audio energy."""
    rms, _, _, sr = _compute_audio_feature_bundle(audio_path)
    return rms, sr


def compute_spectral_centroid(audio_path: str) -> Any:
    """Spectral centroid as brightness/emotion proxy."""
    _, brightness, _, _ = _compute_audio_feature_bundle(audio_path)
    return brightness


def compute_onset_strength(audio_path: str) -> Any:
    """Onset strength envelope for beat/transient detection."""
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
    asr_words: Optional[list[dict]] = None,
) -> list[HighlightSegment]:
    """
    Find highlight segments in the video.

    Uses multi-signal scoring:
    - Audio energy peaks
    - Spectral centroid spikes
    - Onset strength
    - ASR word density (if available)

    Returns top-N segments sorted by score.
    """
    from app.cache import load_json_cache, save_json_cache

    cache_extra = _highlight_cache_extra(video_info, config, asr_words)
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
            segments = _fallback_highlights(video_info, config)
            segments = _apply_duration_variation(segments, video_info, config)
            _save_highlight_cache(config, video_path, cache_extra, segments)
            return segments

        if not os.path.exists(audio_path):
            console.print("[yellow]Audio extraction failed, using fallback highlights[/yellow]")
            segments = _fallback_highlights(video_info, config)
            segments = _apply_duration_variation(segments, video_info, config)
            _save_highlight_cache(config, video_path, cache_extra, segments)
            return segments

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
            segments = _fallback_highlights(video_info, config)
            segments = _apply_duration_variation(segments, video_info, config)
            _save_highlight_cache(config, video_path, cache_extra, segments)
            return segments
        except Exception as e:
            console.print(f"[yellow]Audio analysis failed, using fallback highlights: {e}[/yellow]")
            segments = _fallback_highlights(video_info, config)
            segments = _apply_duration_variation(segments, video_info, config)
            _save_highlight_cache(config, video_path, cache_extra, segments)
            return segments
    else:
        import numpy as np
        from scipy.ndimage import uniform_filter1d

    # Normalize all features to 0-1
    def normalize(x):
        mx = np.max(x)
        if mx == 0:
            return np.zeros_like(x)
        return x / mx

    rms_norm = normalize(rms)
    centroid_norm = normalize(centroid)
    onset_norm = normalize(onset)

    # Align lengths
    min_len = min(len(rms_norm), len(centroid_norm), len(onset_norm))
    rms_norm = rms_norm[:min_len]
    centroid_norm = centroid_norm[:min_len]
    onset_norm = onset_norm[:min_len]

    # Composite energy score per frame. The analysis now uses coarse 1s hops
    # so long videos stay responsive.
    hop_duration = 1.0 if sr <= 0 else (max(512, int(round(sr * 1.0))) / sr)
    combined = 0.4 * rms_norm + 0.3 * centroid_norm + 0.3 * onset_norm

    # Smooth with a short moving average window.
    window_frames = max(3, int(5.0 / hop_duration))
    combined_smooth = uniform_filter1d(combined, size=window_frames)

    _highlight_stage(4, 6, "Merging ASR density...")

    # ASR word density bonus
    if asr_words:
        asr_density = np.zeros_like(combined_smooth)
        total_duration = video_info.duration_sec
        for word_info in asr_words:
            t = word_info.get("start", 0)
            if 0 <= t < total_duration:
                frame_idx = int(t / hop_duration)
                if frame_idx < len(asr_density):
                    # Spread word presence over a couple of frames.
                    spread = max(1, int(2.0 / hop_duration))
                    start = max(0, frame_idx - spread // 2)
                    end = min(len(asr_density), frame_idx + spread // 2 + 1)
                    asr_density[start:end] += 1.0
        if np.max(asr_density) > 0:
            asr_density = normalize(asr_density)
            combined_smooth = 0.7 * combined_smooth + 0.3 * asr_density

    _highlight_stage(5, 6, "Finding peaks...")

    # Find peaks
    threshold = np.mean(combined_smooth) + 0.5 * np.std(combined_smooth)
    peaks = _find_peaks(combined_smooth, threshold, min_distance_sec=8.0, hop_duration=hop_duration)

    _highlight_stage(6, 6, "Scoring candidates...")

    # Create candidate windows around peaks
    candidates = []
    preferred_dur = min(
        config.preferred_clip_duration_sec,
        config.max_clip_duration_sec,
        config.hard_max_clip_duration_sec,
    )
    max_dur = min(config.max_clip_duration_sec, config.hard_max_clip_duration_sec)
    min_dur = min(config.min_clip_duration_sec, max(1.0, video_info.duration_sec))

    for peak_frame in peaks:
        peak_sec = peak_frame * hop_duration

        # Window: prefer preferred_dur, centered on peak
        half = preferred_dur / 2
        start = max(0, peak_sec - half)
        end = min(video_info.duration_sec, peak_sec + half)

        dur = end - start
        if dur < min_dur:
            # Expand window
            expand = (min_dur - dur) / 2
            start = max(0, start - expand)
            end = min(video_info.duration_sec, end + expand)
            dur = end - start

        if dur > max_dur:
            end = start + max_dur
            dur = max_dur

        if dur < min_dur:
            continue

        # Score = average combined in window
        start_frame = int(start / hop_duration)
        end_frame = int(end / hop_duration)
        window_score = float(np.mean(combined_smooth[start_frame:end_frame]))

        reasons = ["audio_energy"]
        if asr_words:
            reasons.append("speech_density")

        candidates.append(HighlightCandidate(
            start_sec=start,
            end_sec=end,
            score=window_score,
            reasons=reasons,
        ))

    # Deduplicate: remove overlapping candidates, keep higher score
    if not candidates:
        console.print("[yellow]No strong peaks found, using fallback highlights[/yellow]")
        segments = _fallback_highlights(video_info, config)
        segments = _apply_duration_variation(segments, video_info, config)
        _save_highlight_cache(config, video_path, cache_extra, segments)
        return segments

    candidates.sort(key=lambda c: c.score, reverse=True)
    segments = _deduplicate(candidates, min_gap=2.0)
    if not segments:
        console.print("[yellow]All candidates overlapped, using fallback highlights[/yellow]")
        segments = _fallback_highlights(video_info, config)
        segments = _apply_duration_variation(segments, video_info, config)
        _save_highlight_cache(config, video_path, cache_extra, segments)
        return segments

    # Limit to target count. If the user asks for more clips than strong
    # highlights found, fill the remainder with non-overlapping fallback windows.
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
    console.print(f"[green]Found {len(segments)} highlight segments[/green]")
    _save_highlight_cache(config, video_path, cache_extra, segments)
    return segments


def write_highlight_report(
    video_info: VideoInfo,
    segments: list[HighlightSegment],
    config: AppConfig,
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
        "segments": [_segment_to_dict(segment, index=i + 1) for i, segment in enumerate(segments)],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[cyan]Highlight report: {out_path}[/cyan]")
    return out_path


def _highlight_cache_extra(
    video_info: VideoInfo,
    config: AppConfig,
    asr_words: Optional[list[dict]],
) -> dict[str, Any]:
    return {
        "version": 4,
        "duration": round(float(video_info.duration_sec or 0.0), 3),
        "clips": config.clips_override,
        "target_per_hour": config.highlight_target_count_per_hour,
        "min": config.min_clip_duration_sec,
        "preferred": config.preferred_clip_duration_sec,
        "max": config.max_clip_duration_sec,
        "hard_max": config.hard_max_clip_duration_sec,
        "duration_variation": bool(
            getattr(getattr(config, "variation", None), "enabled", False)
            and getattr(getattr(config, "variation", None), "clip_duration_variation", True)
        ),
        "duration_step_min": getattr(getattr(config, "variation", None), "clip_duration_step_min_sec", 2.0),
        "duration_step_max": getattr(getattr(config, "variation", None), "clip_duration_step_max_sec", 4.0),
        "duration_max_same": getattr(getattr(config, "variation", None), "clip_duration_max_same_sec", 2),
        "asr_words": len(asr_words or []),
        "asr_first": (asr_words or [{}])[0].get("word") if asr_words else "",
        "asr_last": (asr_words or [{}])[-1].get("word") if asr_words else "",
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
    selected = []
    for c in candidates:
        overlap = False
        for s in selected:
            if c.start_sec < s.end_sec + min_gap and c.end_sec > s.start_sec - min_gap:
                overlap = True
                break
        if not overlap:
            selected.append(HighlightSegment(
                start_sec=c.start_sec,
                end_sec=c.end_sec,
                score=c.score,
                reasons=c.reasons,
                source="scored",
            ))
    return selected


def _fill_missing_segments(
    selected: list[HighlightSegment],
    fallback: list[HighlightSegment],
    target_count: int,
    min_gap: float = 2.0,
) -> list[HighlightSegment]:
    """Append fallback windows without cloning or overlapping existing moments."""
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
        if (
            candidate.start_sec < segment.end_sec + min_gap
            and candidate.end_sec > segment.start_sec - min_gap
        ):
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
    current_durations = [
        max(0.0, float(segment.end_sec - segment.start_sec))
        for segment in segments
    ]
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
        while (
            duration_counts.get(rounded_duration, 0) >= max_same
            and target_duration - step_min >= min_duration
        ):
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
                )
            )
        else:
            varied.append(segment)

    if changed:
        durations = ", ".join(f"{segment.end_sec - segment.start_sec:.1f}s" for segment in varied)
        console.print(f"[cyan]Clip duration variation: {durations}[/cyan]")
    return varied


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

    segments = []
    step = duration / max(target, 1)
    for i in range(int(target)):
        start = i * step
        end = min(start + preferred, duration)
        if end - start >= min_duration:
            segments.append(HighlightSegment(
                start_sec=start,
                end_sec=end,
                score=0.5,
                reasons=["fallback_even_spacing"],
                source="fallback",
            ))
    if not segments and duration > 0:
        segments.append(
            HighlightSegment(
                start_sec=0.0,
                end_sec=duration,
                score=0.25,
                reasons=["fallback_full_video"],
                source="fallback",
            )
        )
    return segments
