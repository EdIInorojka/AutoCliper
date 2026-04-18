"""Background music mixing with ducking."""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Optional

from app.utils.console import get_console

from app.config import AppConfig

console = get_console()


def find_music_files(music_folder: str) -> list[str]:
    """Find all MP3/WAV files in music folder."""
    p = Path(music_folder)
    if not p.exists() and not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / music_folder
    if not p.exists():
        return []
    files = []
    for ext in ("*.mp3", "*.wav", "*.ogg", "*.flac"):
        files.extend(p.glob(ext))
    return [str(f.resolve()) for f in files]


def pick_random_track(music_folder: str, config: AppConfig) -> Optional[str]:
    """Pick a random music track."""
    files = find_music_files(music_folder)
    if not files:
        console.print(f"[yellow]No music files found in music folder: {music_folder}[/yellow]")
        return None
    if config.variation.enabled and config.variation.bgm_random_pick:
        return random.choice(files)
    return files[0]


def build_music_mix_filter(
    clip_duration: float,
    music_path: str,
    config: AppConfig,
    has_speech: bool = True,
) -> Optional[str]:
    """
    Build ffmpeg filter for background music.

    Returns filter string or None if music should not be added.
    """
    if not music_path or not os.path.exists(music_path):
        return None

    volume = (config.music.volume_min + config.music.volume_max) / 2

    # Build filter:
    # 1. Loop/trim music to clip duration
    # 2. Apply volume
    # 3. Optional: duck under speech

    # Use amix to mix with original audio
    # Music input will be [2:a] or similar

    duck_filter = ""
    if config.music.duck_under_speech and has_speech:
        # Simple duck: reduce music volume by additional 50% during speech
        # For simplicity, we apply a constant reduced volume
        volume *= 0.5

    # Build the music processing filter
    # -loop 1 -t clip_duration to loop music, then trim
    filter_str = (
        f"[2:a]aloop=loop=-1:size=2e+09,"  # infinite loop
        f"atrim=0:{clip_duration:.3f},"
        f"asetpts=N/SR/TB,"
        f"volume={volume:.2f}"
    )

    return filter_str


def build_final_audio_mix(
    clip_duration: float,
    music_path: Optional[str],
    config: AppConfig,
    video_input_idx: int = 0,
    music_input_idx: Optional[int] = None,
    voice_input_idx: Optional[int] = None,
    voice_start_sec: float = 0.0,
    voice_volume: float = 1.0,
    has_original_audio: bool = True,
    final_duration_sec: Optional[float] = None,
    cta_insert_start_sec: Optional[float] = None,
    cta_insert_duration_sec: float = 0.0,
    music_volume: Optional[float] = None,
) -> str:
    """
    Build the final audio mix filter.
    Mixes original audio with background music.
    """
    has_music = bool(music_path and os.path.exists(music_path) and music_input_idx is not None)
    has_voice = bool(voice_input_idx is not None)
    final_duration = float(final_duration_sec or clip_duration)
    final_duration = max(0.1, final_duration)

    parts: list[str] = []

    if has_original_audio:
        parts.append(
            f"[{video_input_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"atrim=0:{clip_duration:.3f},"
            f"apad=whole_dur={clip_duration:.3f},"
            f"atrim=0:{clip_duration:.3f},"
            "asetpts=PTS-STARTPTS[orig_full]"
        )
        cta_start = cta_insert_start_sec
        cta_dur = max(0.0, float(cta_insert_duration_sec))
        if cta_start is not None and cta_dur > 0:
            cta_start = max(0.0, min(float(cta_start), clip_duration))
            parts.extend(
                [
                    "[orig_full]asplit=2[orig_pre_src][orig_post_src]",
                    f"[orig_pre_src]atrim=0:{cta_start:.3f},asetpts=PTS-STARTPTS[orig_pre]",
                    f"anullsrc=r=44100:cl=stereo,atrim=0:{cta_dur:.3f},asetpts=N/SR/TB[orig_silence]",
                    f"[orig_post_src]atrim=start={cta_start:.3f}:end={clip_duration:.3f},"
                    "asetpts=PTS-STARTPTS[orig_post]",
                    "[orig_pre][orig_silence][orig_post]concat=n=3:v=0:a=1[orig]",
                ]
            )
        else:
            parts.append(
                "[orig_full]anull[orig]"
            )
    else:
        parts.append(
            f"anullsrc=r=44100:cl=stereo,atrim=0:{final_duration:.3f},"
            "asetpts=N/SR/TB[orig]"
        )

    mix_inputs = "[orig]"
    input_count = 1

    if has_music:
        if music_volume is None:
            volume = (config.music.volume_min + config.music.volume_max) / 2
        else:
            volume = float(music_volume)
        volume = max(0.0, min(1.0, volume))
        if music_volume is None and config.music.duck_under_speech:
            volume *= 0.5
        parts.append(
            f"[{music_input_idx}:a]aloop=loop=-1:size=2e+09,"
            f"atrim=0:{final_duration:.3f},"
            "asetpts=N/SR/TB,"
            f"volume={volume:.3f},"
            "aformat=sample_rates=44100:channel_layouts=stereo[music]"
        )
        mix_inputs += "[music]"
        input_count += 1

    if has_voice:
        # Delay voice to CTA start (ms), then trim to clip duration.
        delay_ms = int(max(0.0, voice_start_sec) * 1000)
        vv = float(voice_volume)
        vv = max(0.05, min(2.0, vv))
        parts.append(
            f"[{voice_input_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms},"
            f"atrim=0:{final_duration:.3f},"
            "asetpts=N/SR/TB,"
            f"volume={vv:.3f}[voice]"
        )
        mix_inputs += "[voice]"
        input_count += 1

    if input_count == 1:
        # No extra tracks.
        return ";".join(parts + ["[orig]anull[audio_out]"])

    parts.append(
        f"{mix_inputs}amix=inputs={input_count}:duration=first:dropout_transition=2[audio_out]"
    )
    return ";".join(parts)
