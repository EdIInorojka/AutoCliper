# StreamCuter

Windows-first local CLI for turning horizontal streams, downloaded videos, and supported YouTube/Kick VOD URLs into vertical 9:16 clips for TikTok, YouTube Shorts, and Instagram Reels.

Use it only with content that you have the right to process. StreamCuter does not implement algorithm bypassing, authorship spoofing, fake metadata, or similar deceptive mechanics. The built-in variation is limited to legitimate visual/editorial variants: clip entry points, CTA text from a whitelist, subtitle themes, safe crop/zoom variants, and background music choice.

## What Works

- Local MP4 input as the primary path.
- YouTube/Kick URL ingest through `yt-dlp` when the URL is supported by yt-dlp.
- `ffprobe` metadata analysis: duration, FPS, resolution, audio streams.
- Webcam detection with OpenCV Haar face cascades plus stability/edge heuristics.
- Vertical layout:
  - webcam detected: webcam panel on top, main content below;
  - no webcam: full vertical smart crop/fill path.
- Highlight detection from audio RMS, spectral centroid, onset strength, and ASR word density.
- Word-by-word ASS subtitles from faster-whisper word timestamps, positioned by default between webcam and gameplay.
- CTA freeze/gray/typewriter pause at 7-10 seconds with RU/EN text selection.
- CRF-based H.264 export by default for smaller files at near-identical visual quality.
- Optional CTA voice MP3 from `sounds/voice/cta.mp3`.
- Optional background music from `sounds/music`, disabled by default and enabled with `--music` or config.
- Safe temp cleanup that keeps final `output` files.
- Windows CMD/PowerShell CLI and `run_local.bat`.
- Telegram-bot-ready config presets in `AppConfig.bot_preset_fields`.

## System Requirements

- Windows 10/11.
- Python 3.11+.
- ffmpeg and ffprobe in PATH, or bundled under `tools/ffmpeg/bin`.
- Internet access for first faster-whisper model download and for URL downloads.

Check ffmpeg:

```cmd
ffmpeg -version
ffprobe -version
```

## Install

```cmd
cd C:\Users\Алексей\Desktop\StreamCuter
python -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

For local-file-only usage without `yt-dlp`:

```cmd
python -m pip install -r requirements-local.txt
```

## Run

```cmd
python -m app.main --input "D:\video.mp4"
python -m app.main --input "https://youtube.com/watch?v=..."
python -m app.main --config example_config.yaml
python -m app.main --input "video.mp4" --clips 15
python -m app.main --input "video.mp4" --lang auto --theme red
python -m app.main --input "video.mp4" --subtitle-lang ru --cta-lang ru
python -m app.main --input "video.mp4" --dry-run
```

Batch helper:

```cmd
run_local.bat --input "D:\video.mp4" --clips 3
```

Interactive CMD wizard:

```cmd
generate_clips.cmd
```

Useful feature toggles:

```cmd
python -m app.main --input "video.mp4" --no-webcam
python -m app.main --input "video.mp4" --music
python -m app.main --input "video.mp4" --no-music
python -m app.main --input "video.mp4" --no-cta
python -m app.main --input "video.mp4" --no-subs
python -m app.main --input "video.mp4" --subtitle-lang ru --cta-lang ru --cta-voice "sounds\voice\cta.mp3"
python -m app.main --input "video.mp4" --delete-input-after-success
```

For a fast ASR smoke test, use a smaller faster-whisper model:

```cmd
set STREAMCUTER_WHISPER_MODEL=tiny
python -m app.main --input "video.mp4" --lang en --clips 1
```

## Config

Main config files:

- `example_config.yaml`
- `example_config.json`

Important fields:

- `input`: local path or URL.
- `output_dir`, `temp_dir`.
- `language`: `auto`, `ru`, or `en`.
- `subtitles_enabled`, `subtitles_mode`, `subtitles_position`, `subtitles_theme`, `subtitles_font_name`, `subtitles_font_path`, `subtitles_template_ru`, `subtitles_template_en`.
- `whisper_model_cache_dir`: persistent faster-whisper model cache; default `models/whisper`.
- `webcam_detection`, `webcam_edge_margin_ratio`, `webcam_top_ratio`, `content_bottom_ratio`.
- `highlight_target_count_per_hour`, `min_clip_duration_sec`, `preferred_clip_duration_sec`, `max_clip_duration_sec`, `hard_max_clip_duration_sec`.
- `cta.enabled`, `cta.trigger_range_sec`, `cta.freeze_duration_sec`, `cta.text_en`, `cta.text_ru`, `cta.language`, `cta.font_path`, `cta.voice_mp3_path`.
- When `cta.voice_mp3_path` points to an existing audio file, the CTA freeze duration follows that file's duration; if the file is missing, `cta.freeze_duration_sec` is used.
- `music.enabled`, `music.folder`, `music.volume_min`, `music.volume_max`, `music.duck_under_speech`; default `music.enabled` is `false`.
- `variation.enabled`, `variation.cta_text_variants`, `variation.cta_text_variants_ru`, `variation.subtitle_style_variants`, `variation.bgm_random_pick`.
- `cleanup_temp_files`, `delete_input_after_success`.
- `export.width`, `export.height`, `export.fps`, `export.codec`, `export.crf`, `export.preset`, `export.bitrate`, `export.audio_codec`.
- `bot_preset_fields` for future Telegram UI options.

## Highlight Logic

StreamCuter scores candidate windows by audio energy, onset strength, spectral changes, ASR speech density, and spacing rules. It sorts high-score candidates, removes overlapping windows, then renders the requested number of clips.

If `--clips` asks for more clips than strong highlights found, the pipeline keeps the strong moments and fills the rest with non-overlapping fallback windows across the source video. If the video is too short to fit that many non-overlapping clips, it logs the actual number it can render instead of cloning the same moment.

## Project Structure

```text
StreamCuter/
  app/
    main.py
    cli.py
    config.py
    downloader.py
    probe.py
    webcam_detector.py
    webcam_types.py
    layout.py
    highlight_detector.py
    subtitles.py
    asr.py
    cta_pause.py
    audio_mix.py
    renderer.py
    cleanup.py
    utils/
      console.py
      helpers.py
  sounds/
    voice/
      cta.mp3          optional
    music/
      *.mp3            optional
  output/
  temp/
  tests/
  example_config.yaml
  example_config.json
  requirements.txt
  requirements-local.txt
  pyproject.toml
  run_local.bat
```

## Test

```cmd
python -m compileall app tests
python -m unittest tests.test_smoke -q
python -m pytest -q
python -m app.main --input test_input.mp4 --clips 1 --no-subs
```

The full ASR path needs a video with speech and an available faster-whisper model:

```cmd
set STREAMCUTER_WHISPER_MODEL=tiny
python -m app.main --input temp\speech_test.mp4 --clips 1 --lang en
```

## Vercel

Do not run the video renderer inside Vercel/serverless. ffmpeg rendering and ASR are CPU-heavy, can run for minutes, and need local binaries and model files. Vercel is only a reasonable future option for a control panel or frontend that sends jobs to a local worker, VPS, or queue worker.

## Troubleshooting

- `ffmpeg not found`: install ffmpeg or run `run_local.bat`, which attempts the local bootstrap path.
- `yt-dlp is not installed`: install `requirements.txt`, not `requirements-local.txt`.
- First ASR run is slow: faster-whisper downloads the model once.
- Background music is disabled by default. Use `--music` or set `music.enabled: true` to opt in.
- Word-by-word subtitles use `subtitles/ru.ass` or `subtitles/en.ass` as the ASS style template depending on the selected language.
- If webcam is not detected, the main content is centered with a blurred fill and subtitles move to the top-safe position.
- `--delete-input-after-success` removes the source video only after output clips are created. Use it carefully for local files.
- No music files with music enabled: the pipeline logs it and continues without background music.
- No CTA voice file: the pipeline continues without voiceover.
- No webcam found: the pipeline falls back to the no-webcam vertical crop. You can force it with `--no-webcam`.
- Very short/silent videos: highlight detection falls back to best available windows.
