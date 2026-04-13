"""Highlight detection using audio energy, scene changes, and ASR signals."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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


def _extract_audio_wav(video_path: str, temp_dir: str) -> str:
    """Extract audio from video as WAV for analysis."""
    out_path = os.path.join(temp_dir, "audio_analysis.wav")
    import subprocess
    cmd = [
        ffmpeg_exe(), "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "22050", "-ac", "1",
        out_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_path


def compute_audio_energy(audio_path: str) -> tuple[Any, float]:
    """Compute per-frame audio energy."""
    import librosa

    y, sr = librosa.load(audio_path, sr=22050)
    # RMS energy per frame (hop=512 ≈ 23ms)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    return rms, sr


def compute_spectral_centroid(audio_path: str) -> Any:
    """Spectral centroid as brightness/emotion proxy."""
    import librosa

    y, sr = librosa.load(audio_path, sr=22050)
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=512)[0]
    return centroid


def compute_onset_strength(audio_path: str) -> Any:
    """Onset strength envelope for beat/transient detection."""
    import librosa

    y, sr = librosa.load(audio_path, sr=22050)
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
    return onset


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
    console.print("[cyan]Extracting audio for highlight analysis...[/cyan]")

    try:
        audio_path = _extract_audio_wav(video_path, temp_dir)
    except Exception as e:
        console.print(f"[yellow]Audio extraction failed, using fallback highlights: {e}[/yellow]")
        return _fallback_highlights(video_info, config)

    if not os.path.exists(audio_path):
        console.print("[yellow]Audio extraction failed, using fallback highlights[/yellow]")
        return _fallback_highlights(video_info, config)

    console.print("[cyan]Computing audio features...[/cyan]")

    try:
        import numpy as np
    except ImportError:
        console.print("[yellow]numpy not installed; using fallback highlights[/yellow]")
        return _fallback_highlights(video_info, config)

    try:
        import librosa  # noqa: F401
        from scipy.ndimage import uniform_filter1d
    except ImportError:
        console.print("[yellow]librosa/scipy not installed; using fallback highlights[/yellow]")
        return _fallback_highlights(video_info, config)

    rms, sr = compute_audio_energy(audio_path)
    centroid = compute_spectral_centroid(audio_path)
    onset = compute_onset_strength(audio_path)

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

    # Composite energy score per frame
    hop_duration = 512 / 22050  # ~23ms
    combined = 0.4 * rms_norm + 0.3 * centroid_norm + 0.3 * onset_norm

    # Smooth with moving average (1 second window)
    window_frames = max(1, int(1.0 / hop_duration))
    combined_smooth = uniform_filter1d(combined, size=window_frames)

    # ASR word density bonus
    if asr_words:
        asr_density = np.zeros_like(combined_smooth)
        total_duration = video_info.duration_sec
        for word_info in asr_words:
            t = word_info.get("start", 0)
            if 0 <= t < total_duration:
                frame_idx = int(t / hop_duration)
                if frame_idx < len(asr_density):
                    # Spread word presence over ~1 second
                    spread = int(1.0 / hop_duration)
                    start = max(0, frame_idx - spread // 2)
                    end = min(len(asr_density), frame_idx + spread // 2)
                    asr_density[start:end] += 1.0
        if np.max(asr_density) > 0:
            asr_density = normalize(asr_density)
            combined_smooth = 0.7 * combined_smooth + 0.3 * asr_density

    # Find peaks
    threshold = np.mean(combined_smooth) + 0.5 * np.std(combined_smooth)
    peaks = _find_peaks(combined_smooth, threshold, min_distance_sec=8.0, hop_duration=hop_duration)

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
        return _fallback_highlights(video_info, config)

    candidates.sort(key=lambda c: c.score, reverse=True)
    segments = _deduplicate(candidates, min_gap=2.0)
    if not segments:
        console.print("[yellow]All candidates overlapped, using fallback highlights[/yellow]")
        return _fallback_highlights(video_info, config)

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

    console.print(f"[green]Found {len(segments)} highlight segments[/green]")
    return segments


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
    min_distance_frames = int(min_distance_sec / hop_duration)
    peaks = []
    i = 0
    while i < len(signal):
        if signal[i] > threshold:
            # Find local max in neighborhood
            j = i
            while j < len(signal) and signal[j] >= signal[i]:
                j += 1
            # Check left side too
            left = i
            while left > 0 and signal[left - 1] >= signal[i]:
                left -= 1

            peak_idx = i
            peak_val = signal[i]
            for k in range(left, min(j, len(signal))):
                if signal[k] > peak_val:
                    peak_val = signal[k]
                    peak_idx = k

            peaks.append(peak_idx)
            i = peak_idx + min_distance_frames
        else:
            i += 1
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
            ))
    if not segments and duration > 0:
        segments.append(HighlightSegment(start_sec=0.0, end_sec=duration, score=0.25))
    return segments
