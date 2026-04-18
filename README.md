# StreamCuter

Windows-first local CLI for turning horizontal streams, downloaded videos, and supported YouTube/Kick VOD URLs into vertical 9:16 clips for TikTok, YouTube Shorts, and Instagram Reels.

Use it only with content that you have the right to process. StreamCuter does not implement algorithm bypassing, authorship spoofing, fake metadata, or similar deceptive mechanics. The built-in variation is limited to legitimate visual/editorial variants: clip entry points, CTA text from a whitelist, subtitle themes, safe crop/zoom variants, and background music choice.

## What Works

- Local MP4 input as the primary path.
- YouTube/Kick URL ingest through `yt-dlp` when the URL is supported by yt-dlp.
- `ffprobe` metadata analysis: duration, FPS, resolution, audio streams.
- Webcam detection with MediaPipe when available, OpenCV Haar fallback, and edge/contrast/stability heuristics across the full left/right stream rails.
- Manual layout preview selector with a timeline slider when auto-detection needs correction.
- Vertical layout:
  - webcam detected: webcam panel on top, main content below;
  - no webcam: full vertical smart crop/fill path.
- Highlight detection from audio RMS, spectral centroid, onset strength, and ASR word density.
- Word-by-word ASS subtitles from faster-whisper word timestamps, positioned by default between webcam and gameplay.
- CTA freeze/gray/typewriter pause at 7-10 seconds with RU/EN text selection.
- CRF-based H.264 export by default for smaller files at near-identical visual quality.
- Optional CTA voice MP3 from `sounds/voice/cta.mp3`.
- Apply Cinema background music from `musiccinema`, capped at 10% volume. Normal webcam/slot modes never use background music.
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

`generate_clips.cmd` and `run_local.bat` are ASCII-only wrappers to avoid Windows CMD encoding bugs. The Russian step-by-step wizard runs in Python:

```cmd
python -m app.wizard
```

Double-click launcher:

```cmd
build_launcher_exe.cmd
StreamCuter.exe
```

`StreamCuter.exe` is a small launcher for this project folder. It opens the same CMD wizard and still uses `run_local.bat` to activate/install the Python video stack.

Useful feature toggles:

```cmd
python -m app.main --input "video.mp4" --no-webcam
python -m app.main --input "video.mp4" --layout-mode cinema
python -m app.main --input "video.mp4" --layout-mode cinema --no-music
python -m app.main --input "video.mp4" --no-cta
python -m app.main --input "video.mp4" --no-subs
python -m app.main --input "video.mp4" --subtitle-lang ru --cta-lang ru --cta-voice "sounds\voice\cta.mp3"
python -m app.main --input "video.mp4" --cta-text "МОЯ НАДПИСЬ"
python -m app.main --input "video.mp4" --cta-text-file "cta_texts\ru.txt"
python -m app.main --input "video.mp4" --render-preset quality
python -m app.main --input "video.mp4" --input-start 05:00 --input-end 35:00
python -m app.main --input "video.mp4" --layout-mode slot_only
python -m app.main --input "video.mp4" --layout-mode cinema
python -m app.main --input "video.mp4" --force-render
python -m app.main --input "video.mp4" --no-cache
python -m app.main --input "video.mp4" --delete-input-after-success
python -m app.main --input "video.mp4" --preview-layout
python -m app.main --input "video.mp4" --preview-layout --preview-time 03:00
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
- `input_start_sec`, `input_end_sec`: optional slice bounds; the selected slice becomes the working source for ASR, highlights, layout preview and rendering.
- `output_dir`, `temp_dir`.
- `language`: `auto`, `ru`, or `en`.
- `subtitles_enabled`, `subtitles_mode`, `subtitles_position`, `subtitles_theme`, `subtitles_font_name`, `subtitles_font_path`, `subtitles_template_ru`, `subtitles_template_en`.
- `whisper_model_cache_dir`: persistent faster-whisper model cache; default `models/whisper`.
- `layout_mode`: `auto`, `slot_only`, or `cinema`.
- `webcam_detection`, `webcam_edge_margin_ratio`, `manual_webcam_crop`, `manual_slot_crop`, `layout_preview_enabled`, `layout_preview_time_sec`, `layout_debug_preview`, `layout_preview_save_path`, `webcam_top_ratio`, `content_bottom_ratio`.
- `layout_preview_autofill`: preselect auto-detected webcam/slot boxes in the preview window so you can just fix them if needed.
- `layout_annotation_dataset_enabled`, `layout_annotation_dataset_path`: saves manual preview selections as JSONL and uses them later as learned layout candidates.
- `highlight_target_count_per_hour`, `min_clip_duration_sec`, `preferred_clip_duration_sec`, `max_clip_duration_sec`, `hard_max_clip_duration_sec`.
- `highlight_report_path`: JSON report with selected windows, scores and reasons.
- `cta.enabled`, `cta.trigger_range_sec`, `cta.freeze_duration_sec`, `cta.text_mode`, `cta.custom_text`, `cta.text_file_path_en`, `cta.text_file_path_ru`, `cta.text_en`, `cta.text_ru`, `cta.language`, `cta.font_path`, `cta.font_size`, `cta.min_font_size`, `cta.max_text_width_ratio`, `cta.max_text_lines`, `cta.voice_mp3_path`.
- When `cta.voice_mp3_path` points to an existing audio file, the CTA freeze duration follows that file's duration; if the file is missing, `cta.freeze_duration_sec` is used.
- Default CTA file variants are limited to: `THE GAME IN BIO`, `LINK IN BIO`, `BIO FOR MORE`, `CHECK BIO`, `MORE IN BIO`, `ИГРА В ОПИСАНИИ`, `ССЫЛКА В ОПИСАНИИ`.
- `music.enabled`, `music.folder`, `music.volume_min`, `music.volume_max`, `music.duck_under_speech`; legacy normal-mode music remains disabled and is not used by the renderer.
- `cinema_music.enabled`, `cinema_music.folder`, `cinema_music.volume`: Apply Cinema background music only; default folder is `musiccinema`, volume is capped at `0.10`.
- `cache.enabled`, `cache.dir`, `cache.asr`, `cache.highlights`, `cache.layout`: persistent cache for repeated runs.
- `variation.enabled`, `variation.cta_text_variants`, `variation.cta_text_variants_ru`, `variation.subtitle_style_variants`, `variation.bgm_random_pick`.
- `cleanup_temp_files`, `delete_input_after_success`, `render_resume_enabled`.
- `export.render_preset`, `export.width`, `export.height`, `export.fps`, `export.codec`, `export.crf`, `export.preset`, `export.bitrate`, `export.audio_codec`.
- `bot_preset_fields` for future Telegram UI options.

## Render Presets

- `fast`: quick local checks, `libx264`, CRF 23, `veryfast`.
- `quality`: default, slower but cleaner output, `libx264`, CRF 19, `slower`.
- `balanced`: good quality and size, `libx264`, CRF 22, `slow`.
- `small`: smaller files, still sane quality, `libx264`, CRF 24, `slow`.
- `nvenc_fast`: NVIDIA GPU path, `h264_nvenc`, CQ 22. Use it only when your ffmpeg build has NVENC support.

Use `custom` if you want to control `export.codec`, `export.crf`, `export.preset`, and `export.bitrate` directly.

## Cache And Resume

StreamCuter caches expensive ASR, highlight and layout analysis in `cache/`. The cache key includes the source file path, size, mtime and important config values, so repeated runs on the same stream can skip work.

Output rendering has resume enabled by default. Existing valid clips are kept and skipped. Use `--force-render` when you want to overwrite everything.

Manual layout selections are appended to `layout_dataset/annotations.jsonl`. Future auto-detection uses those records as extra candidates, so the detector gradually gets better for layouts you have corrected.

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
  musiccinema/
    *.mp3              optional, Apply Cinema only
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
- `kick.com` returns HTTP 403 during ingest: the site may block anonymous requests. This project now enables `yt-dlp` impersonation support by default; if Kick still blocks a video, export cookies to a Netscape cookie file and point `STREAMCUTER_COOKIES_FILE` at it.
- First ASR run is slow: faster-whisper downloads the model once.
- Apply Cinema can add quiet background music from `musiccinema` at max 10% volume. If the folder is empty, it renders without music. Other layout modes never use background music.
- Word-by-word subtitles use `subtitles/ru.ass` or `subtitles/en.ass` as the ASS style template depending on the selected language.
- Subtitle cleanup is language-aware: English subtitles keep English words only, Russian subtitles keep Cyrillic words only, and obvious ASR punctuation/CJK/mojibake noise is dropped without extra slow spellchecking.
- CTA pause text uses `cta_texts/ru.txt` or `cta_texts/en.txt` by default. Use `--cta-text "..."` for a custom one-off phrase, or edit those files for the standard phrase pool. Long CTA text is wrapped and font-fitted so it stays inside the 9:16 frame.
- If webcam is not detected, the main content uses the best active slot crop with a blurred fill and subtitles move to the top-safe position.
- Use `--preview-layout` when you want to manually mark the stream layout. The window opens on the middle frame by default and includes a timeline slider so you can switch to another moment before selecting. `--preview-time 03:00` or `layout_preview_time_sec` changes the initial frame. `Apply` keeps the normal behavior. `Apply slot only` builds an explicit no-webcam slot layout. `Apply cinema` builds a zoomed no-webcam cinema layout with blurred fill and top subtitles.
- Set `debug: true` to save a layout preview with a green webcam box and red slot box. If a rare stream still needs correction, set `manual_webcam_crop` or `manual_slot_crop` to `[x, y, width, height]` in source-video pixels.
- `--delete-input-after-success` removes the source video only after output clips are created. Use it carefully for local files.
- No music files with music enabled: the pipeline logs it and continues without background music.
- No CTA voice file: the pipeline continues without voiceover.
- No webcam found: the pipeline falls back to the no-webcam vertical crop. You can force it with `--no-webcam`.
- Very short/silent videos: highlight detection falls back to best available windows.
