"""Smoke tests for StreamCuter modules."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestConfig(unittest.TestCase):
    def test_default_config(self):
        from app.config import AppConfig
        config = AppConfig()
        self.assertEqual(config.export.width, 1080)
        self.assertEqual(config.export.height, 1920)
        self.assertTrue(config.subtitles_enabled)
        self.assertTrue(config.cta.enabled)
        self.assertEqual(config.cta.text_mode, "file")
        self.assertEqual(config.cta.text_file_path_en, "cta_texts/en.txt")
        self.assertEqual(config.cta.text_file_path_ru, "cta_texts/ru.txt")
        self.assertEqual(config.cta.max_text_lines, 3)
        self.assertFalse(config.music.enabled)
        self.assertEqual(config.subtitles_position, "between_webcam_and_game")
        self.assertEqual(config.export.crf, 22)
        self.assertEqual(config.cta.freeze_duration_sec, 4.0)
        self.assertEqual(config.cta.typewriter_speed, 0.16)
        self.assertEqual(config.whisper_model_cache_dir, "models/whisper")
        self.assertTrue(config.cinema_music.enabled)
        self.assertEqual(config.cinema_music.folder, "musiccinema")
        self.assertEqual(config.cinema_music.volume, 0.05)
        self.assertTrue(config.cinema_music.ending_enabled)
        self.assertEqual(config.cinema_music.ending_duration_sec, 4.5)
        self.assertEqual(config.cinema_music.ending_volume, 0.60)
        self.assertTrue(config.hook.enabled)
        self.assertTrue(config.hook.strict_factual)
        self.assertEqual(config.hook.intro_window_sec, 2.0)
        self.assertEqual(config.hook.search_backtrack_sec, 4.0)
        self.assertEqual(config.hook.search_forward_sec, 1.0)
        self.assertTrue(config.hook.question_bias)
        self.assertEqual(config.layout_mode, "auto")
        self.assertEqual(config.webcam_edge_margin_ratio, 0.15)
        self.assertIsNone(config.manual_webcam_crop)
        self.assertIsNone(config.manual_slot_crop)
        self.assertIsNone(config.manual_cinema_crop)
        self.assertFalse(config.layout_preview_enabled)
        self.assertIsNone(config.layout_preview_time_sec)
        self.assertTrue(config.layout_preview_autofill)
        self.assertEqual(config.layout_debug_preview, "layout_debug_preview.jpg")
        self.assertEqual(config.layout_preview_save_path, "layout_selection.json")
        self.assertTrue(config.layout_annotation_dataset_enabled)
        self.assertEqual(config.layout_annotation_dataset_path, "layout_dataset/annotations.jsonl")
        self.assertTrue(config.cache.enabled)
        self.assertEqual(config.cache.dir, "cache")
        self.assertIsNone(config.input_start_sec)
        self.assertIsNone(config.input_end_sec)
        self.assertFalse(hasattr(config, "quick_preview"))
        self.assertEqual(config.export.render_preset, "quality")
        self.assertTrue(config.render_resume_enabled)
        self.assertTrue(config.variation.clip_duration_variation)
        self.assertEqual(config.variation.clip_duration_step_min_sec, 2.0)
        self.assertEqual(config.variation.clip_duration_step_max_sec, 4.0)
        self.assertEqual(config.variation.clip_duration_max_same_sec, 2)
        self.assertEqual(config.highlight_report_path, "highlight_report.json")
        self.assertEqual(
            config.variation.cta_text_variants,
            [
                "THE GAME IN BIO",
                "BIO FOR MORE",
                "CHECK BIO",
                "MORE IN BIO",
            ],
        )
        self.assertEqual(
            config.variation.cta_text_variants_ru,
            ["ИГРА В ОПИСАНИИ", "ССЫЛКА В ОПИСАНИИ"],
        )
        self.assertEqual(
            config.bot_preset_fields.available_cta_texts,
            [
                "THE GAME IN BIO",
                "BIO FOR MORE",
                "CHECK BIO",
                "MORE IN BIO",
            ],
        )
        self.assertEqual(
            config.bot_preset_fields.available_cta_texts_ru,
            ["ИГРА В ОПИСАНИИ", "ССЫЛКА В ОПИСАНИИ"],
        )

    def test_load_example_config(self):
        from app.config import load_config, AppConfig
        root = Path(__file__).resolve().parent.parent
        j = root / "example_config.json"
        if j.exists():
            config = load_config(j)
            self.assertIsInstance(config, AppConfig)

    def test_load_json_config_with_utf8_bom(self):
        from app.config import load_config

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text('\ufeff{"input": "video.mp4"}', encoding="utf-8")

            config = load_config(path)

        self.assertEqual(config.input, "video.mp4")

    def test_subtitle_themes(self):
        from app.config import SUBTITLE_THEMES
        for name in ("red", "purple", "black", "yellow"):
            self.assertIn(name, SUBTITLE_THEMES)
            theme = SUBTITLE_THEMES[name]
            self.assertIn("primary_colour", theme)
            self.assertIn("font_size", theme)
            self.assertEqual(theme["font_size"], 44)


class TestHelpers(unittest.TestCase):
    def test_parse_preview_time(self):
        from app.cli import _parse_time_sec

        self.assertEqual(_parse_time_sec("03:00"), 180.0)
        self.assertEqual(_parse_time_sec("01:02:03"), 3723.0)
        self.assertEqual(_parse_time_sec("12.5"), 12.5)

    def test_safe_filename(self):
        from app.utils.helpers import safe_filename
        # <>:" are 4 chars each replaced with _
        self.assertEqual(safe_filename('test<>:"file'), 'test____file')

    def test_asr_model_selection_prefers_stronger_models_for_english(self):
        from app.asr import _select_model
        from app.config import AppConfig

        config = AppConfig()

        self.assertEqual(_select_model(120.0, config, "en", requested_language="en"), "medium.en")
        self.assertEqual(_select_model(2400.0, config, "en", requested_language="en"), "medium.en")
        self.assertEqual(_select_model(120.0, config, "en", requested_language="auto"), "medium.en")
        self.assertEqual(_select_model(120.0, config, "ru", requested_language="ru"), "medium")
        self.assertEqual(_select_model(1200.0, config, "ru", requested_language="ru"), "medium")

    def test_run_with_asr_progress_does_not_execute_work_twice(self):
        from app import asr

        calls = []

        def _work(progress=None, task=None):
            calls.append((progress is not None, task is not None))
            return "ok"

        result = asr._run_with_asr_progress(
            description="Loading",
            total=10.0,
            work=_work,
            progress_description="Running",
        )

        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], (True, True))

    def test_asr_model_selection_respects_env_override(self):
        from app.asr import _select_model
        from app.config import AppConfig

        config = AppConfig()
        previous = os.environ.get("STREAMCUTER_WHISPER_MODEL")
        os.environ["STREAMCUTER_WHISPER_MODEL"] = "custom-model"
        try:
            self.assertEqual(_select_model(120.0, config, "en", requested_language="en"), "custom-model")
        finally:
            if previous is None:
                os.environ.pop("STREAMCUTER_WHISPER_MODEL", None)
            else:
                os.environ["STREAMCUTER_WHISPER_MODEL"] = previous

    def test_input_range_normalization(self):
        from app.downloader import _normalize_selected_range

        self.assertIsNone(_normalize_selected_range(120.0, None, None))
        self.assertEqual(_normalize_selected_range(120.0, 10.0, None), (10.0, 120.0))
        self.assertEqual(_normalize_selected_range(120.0, None, 30.0), (0.0, 30.0))

        with self.assertRaises(RuntimeError):
            _normalize_selected_range(120.0, 60.0, 10.0)

        with self.assertRaises(RuntimeError):
            _normalize_selected_range(120.0, 130.0, None)

    def test_download_ranges_callback_emits_numeric_time_range(self):
        from app.downloader import _download_ranges_callback

        class _DummyYdl:
            def to_screen(self, _message):
                return None

        callback = _download_ranges_callback(10.5, 25.0)
        sections = tuple(callback({"id": "vid", "duration": 100.0}, _DummyYdl()))

        self.assertEqual(sections, ({"start_time": 10.5, "end_time": 25.0},))

    def test_range_output_template_uses_unique_filename(self):
        from app.downloader import _range_output_template

        path = _range_output_template("temp", 530.0, 1375.0)

        self.assertIn("__range_530000_1375000", path)
        self.assertTrue(path.endswith(".%(ext)s"))

    def test_range_output_path_uses_real_extension(self):
        from app.downloader import _range_output_path

        path = _range_output_path("temp", "Dp5pvB6giJQ", 1339.0, 1870.0, "mp4")

        self.assertIn("Dp5pvB6giJQ__range_1339000_1870000.mp4", path)

    def test_range_partial_output_path_keeps_media_extension(self):
        from app.downloader import _range_partial_output_path

        path = _range_partial_output_path("temp\\Dp5pvB6giJQ__range_1339000_1870000.mp4")

        self.assertTrue(path.endswith("Dp5pvB6giJQ__range_1339000_1870000.part.mp4"))

    def test_range_progress_line_renders_byte_progress(self):
        from app.downloader import _format_range_progress_line

        line = _format_range_progress_line(512, total_bytes=1024, tick=0)

        self.assertIn("Range download [", line)
        self.assertIn(" 50%", line)
        self.assertIn("512 B/1.0 KiB", line)

    def test_range_progress_line_renders_indeterminate_bar(self):
        from app.downloader import _format_range_progress_line

        line = _format_range_progress_line(2 * 1024 * 1024, tick=3)

        self.assertIn("Range download [", line)
        self.assertIn("2.0 MiB", line)

    def test_range_progress_line_shows_elapsed_when_no_bytes_visible_yet(self):
        from app.downloader import _format_range_progress_line

        line = _format_range_progress_line(0, tick=2, elapsed_sec=12.0)

        self.assertIn("Range download [", line)
        self.assertIn("12s", line)

    def test_remote_extract_error_mapping_detects_stale_cookies(self):
        from app.downloader import _friendly_remote_extract_error_message

        message = _friendly_remote_extract_error_message(
            RuntimeError("Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies.")
        )

        self.assertIsNotNone(message)
        self.assertIn("cookies.txt", message)

    def test_remote_extract_error_mapping_detects_age_gate(self):
        from app.downloader import _friendly_remote_extract_error_message

        message = _friendly_remote_extract_error_message(
            RuntimeError("Sign in to confirm your age. This video may be inappropriate for some users.")
        )

        self.assertIsNotNone(message)
        self.assertIn("age-restricted", message.lower())

    def test_validate_remote_url_rejects_malformed_youtube_id(self):
        from app.downloader import _validate_remote_url

        with self.assertRaises(RuntimeError) as ctx:
            _validate_remote_url("https://www.youtube.com/watch?v=8jAluLqCezcv")

        self.assertIn("11-character video id", str(ctx.exception))

    def test_range_download_prefers_hls_formats(self):
        from app.downloader import _range_download_format_selector

        selector = _range_download_format_selector()

        self.assertIn("m3u8_native", selector)

    def test_build_remote_range_ffmpeg_cmd_maps_requested_formats(self):
        from app.downloader import _build_remote_range_ffmpeg_cmd

        class _DummyCookieJar:
            def get_cookies_for_url(self, _url):
                return []

        cmd = _build_remote_range_ffmpeg_cmd(
            "ffmpeg",
            [
                {
                    "url": "https://video.example/stream.m3u8",
                    "http_headers": {"User-Agent": "UA"},
                    "manifest_stream_number": 0,
                },
                {
                    "url": "https://audio.example/stream.m3u8",
                    "http_headers": {"User-Agent": "UA"},
                    "manifest_stream_number": 0,
                },
            ],
            _DummyCookieJar(),
            "temp\\clip.mp4",
            10.0,
            25.0,
        )

        joined = " ".join(cmd)
        self.assertIn("-progress pipe:1", joined)
        self.assertEqual(cmd.count("-i"), 2)
        self.assertIn("-map 0:0", joined)
        self.assertIn("-map 1:0", joined)
        self.assertIn("temp\\clip.mp4", joined)

    def test_asr_chunk_plan_covers_full_duration(self):
        from app.asr import _build_asr_chunk_plan

        chunks = _build_asr_chunk_plan(610.0)

        self.assertEqual(chunks[0]["core_start"], 0.0)
        self.assertEqual(chunks[-1]["core_end"], 610.0)
        self.assertGreaterEqual(len(chunks), 3)

    def test_browser_cookie_env_parsing(self):
        from app.downloader import _browser_cookie_spec_from_env

        previous = os.environ.get("STREAMCUTER_COOKIES_FROM_BROWSER")
        os.environ["STREAMCUTER_COOKIES_FROM_BROWSER"] = "chrome:Default"
        try:
            self.assertEqual(
                _browser_cookie_spec_from_env(),
                ("chrome", "Default", None, None),
            )
        finally:
            if previous is None:
                os.environ.pop("STREAMCUTER_COOKIES_FROM_BROWSER", None)
            else:
                os.environ["STREAMCUTER_COOKIES_FROM_BROWSER"] = previous

    def test_yt_dlp_js_runtime_prefers_node_when_available(self):
        from app.downloader import _detect_js_runtime

        with patch("app.downloader.shutil.which", side_effect=lambda name: "/tmp/node" if name == "node" else None):
            self.assertEqual(_detect_js_runtime(), {"node": {}})

    def test_yt_dlp_js_runtime_env_override(self):
        from app.downloader import _detect_js_runtime

        previous = os.environ.get("STREAMCUTER_YTDLP_JS_RUNTIME")
        os.environ["STREAMCUTER_YTDLP_JS_RUNTIME"] = "node"
        try:
            self.assertEqual(_detect_js_runtime(), {"node": {}})
        finally:
            if previous is None:
                os.environ.pop("STREAMCUTER_YTDLP_JS_RUNTIME", None)
            else:
                os.environ["STREAMCUTER_YTDLP_JS_RUNTIME"] = previous

    def test_fmt_time(self):
        from app.utils.helpers import fmt_time
        self.assertEqual(fmt_time(65), "01:05")
        self.assertEqual(fmt_time(0), "00:00")

    def test_ensure_dir(self):
        from app.utils.helpers import ensure_dir
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = ensure_dir(os.path.join(td, "sub", "dir"))
            self.assertTrue(p.exists())

    def test_cpu_thread_budget_uses_scale_and_override(self):
        from app.utils.helpers import cpu_thread_budget

        with patch("app.utils.helpers.os.cpu_count", return_value=16):
            previous_scale = os.environ.get("STREAMCUTER_CPU_SCALE")
            previous_threads = os.environ.get("STREAMCUTER_CPU_THREADS")
            os.environ["STREAMCUTER_CPU_SCALE"] = "0.7"
            os.environ.pop("STREAMCUTER_CPU_THREADS", None)
            try:
                self.assertEqual(cpu_thread_budget(), 11)
                os.environ["STREAMCUTER_CPU_THREADS"] = "6"
                self.assertEqual(cpu_thread_budget(), 6)
            finally:
                if previous_scale is None:
                    os.environ.pop("STREAMCUTER_CPU_SCALE", None)
                else:
                    os.environ["STREAMCUTER_CPU_SCALE"] = previous_scale
                if previous_threads is None:
                    os.environ.pop("STREAMCUTER_CPU_THREADS", None)
                else:
                    os.environ["STREAMCUTER_CPU_THREADS"] = previous_threads


class TestCli(unittest.TestCase):
    def test_cli_parses_input_range_flags(self):
        from app.cli import cli_entry
        from app.config import AppConfig

        captured = {}

        def _capture(config):
            captured["config"] = config

        with patch.object(
            sys,
            "argv",
            [
                "streamcuter",
                "--input",
                "video.mp4",
                "--input-start",
                "05:00",
                "--input-end",
                "35:00",
            ],
        ), patch("app.config.load_config", return_value=AppConfig()), patch(
            "app.main.run_pipeline",
            side_effect=_capture,
        ):
            cli_entry()

        self.assertEqual(captured["config"].input, "video.mp4")
        self.assertEqual(captured["config"].input_start_sec, 300.0)
        self.assertEqual(captured["config"].input_end_sec, 2100.0)

    def test_cli_rejects_reversed_input_range(self):
        from app.cli import cli_entry
        from app.config import AppConfig

        with patch.object(
            sys,
            "argv",
            [
                "streamcuter",
                "--input",
                "video.mp4",
                "--input-start",
                "60",
                "--input-end",
                "10",
            ],
        ), patch("app.config.load_config", return_value=AppConfig()):
            with self.assertRaises(SystemExit) as ctx:
                cli_entry()

        self.assertEqual(ctx.exception.code, 2)

    def test_cli_parses_layout_mode(self):
        from app.cli import cli_entry
        from app.config import AppConfig

        captured = {}

        def _capture(config):
            captured["config"] = config

        with patch.object(
            sys,
            "argv",
            [
                "streamcuter",
                "--input",
                "video.mp4",
                "--layout-mode",
                "cinema",
            ],
        ), patch("app.config.load_config", return_value=AppConfig()), patch(
            "app.main.run_pipeline",
            side_effect=_capture,
        ):
            cli_entry()

        self.assertEqual(captured["config"].layout_mode, "cinema")
        self.assertEqual(captured["config"].webcam_detection, "off")
        self.assertEqual(captured["config"].subtitles_position, "slot_top")


class TestWizard(unittest.TestCase):
    def test_wizard_standard_text_uses_selected_english_language(self):
        from app.wizard import WizardOptions, _build_cli_args

        args = _build_cli_args(
            WizardOptions(
                input_path="D:\\video.mp4",
                language="en",
                output_dir="output\\generated",
                clips=3,
                render_preset="quality",
            )
        )

        self.assertIn("--subtitle-lang", args)
        self.assertEqual(args[args.index("--subtitle-lang") + 1], "en")
        self.assertEqual(args[args.index("--cta-lang") + 1], "en")
        self.assertIn("--cta-text-mode", args)
        self.assertIn("file", args)
        self.assertNotIn("--no-music", args)
        self.assertNotIn("--music", args)
        self.assertIn("--preview-layout", args)
        self.assertNotIn("--quick-preview", args)

    def test_wizard_custom_cta_and_voice_args(self):
        from app.wizard import WizardOptions, _build_cli_args

        args = _build_cli_args(
            WizardOptions(
                input_path="video.mp4",
                language="ru",
                output_dir="out",
                clips=1,
                render_preset="balanced",
                input_start_sec=15.0,
                input_end_sec=90.0,
                cta_text_mode="custom",
                cta_text="MY CTA",
                cta_voice="voice.wav",
                preview_time="03:00",
                preview_layout=True,
                delete_source=True,
            )
        )

        self.assertIn("--cta-text", args)
        self.assertEqual(args[args.index("--cta-text") + 1], "MY CTA")
        self.assertIn("--cta-voice", args)
        self.assertEqual(args[args.index("--cta-voice") + 1], "voice.wav")
        self.assertIn("--input-start", args)
        self.assertEqual(args[args.index("--input-start") + 1], "15.000")
        self.assertIn("--input-end", args)
        self.assertEqual(args[args.index("--input-end") + 1], "90.000")
        self.assertIn("--preview-time", args)
        self.assertIn("--delete-input-after-success", args)

    def test_wizard_summary_does_not_print_quick_preview(self):
        from io import StringIO
        from contextlib import redirect_stdout
        from app.wizard import WizardOptions, _print_summary

        buf = StringIO()
        with redirect_stdout(buf):
            _print_summary(
                WizardOptions(
                    input_path="video.mp4",
                    language="ru",
                    output_dir="out",
                    clips=2,
                    render_preset="quality",
                    input_start_sec=10.0,
                    input_end_sec=50.0,
                ),
                ["-m", "app.main"],
            )

        text = buf.getvalue()
        self.assertIn("Диапазон входа", text)
        self.assertNotIn("quick preview", text.lower())

    def test_windows_batch_launchers_are_ascii_wrappers(self):
        root = Path(__file__).resolve().parent.parent
        for name in ("generate_clips.cmd", "run_local.bat"):
            data = (root / name).read_bytes()
            self.assertTrue(all(byte < 128 for byte in data), name)


class TestLayoutSelector(unittest.TestCase):
    def test_apply_selection_with_both_crops_uses_split_layout(self):
        from app.config import AppConfig
        from app.layout_selector import LayoutSelection, apply_layout_selection

        config = AppConfig()
        selection = LayoutSelection(
            webcam_crop=(10, 20, 300, 168),
            slot_crop=(400, 120, 1200, 700),
            source_size=(1920, 1080),
            preview_time_sec=120.0,
        )

        mode = apply_layout_selection(config, selection)

        self.assertEqual(mode, "manual_split")
        self.assertEqual(config.layout_mode, "auto")
        self.assertEqual(config.manual_webcam_crop, [10, 20, 300, 168])
        self.assertEqual(config.manual_slot_crop, [400, 120, 1200, 700])
        self.assertEqual(config.webcam_detection, "auto")

    def test_initial_preview_time_prefers_config_time(self):
        from app.config import AppConfig
        from app.layout_selector import _fmt_timestamp, _initial_preview_time
        from app.probe import VideoInfo

        config = AppConfig()
        config.layout_preview_time_sec = 777.0
        info = VideoInfo("test.mp4", 1200.0, 30.0, 1920, 1080, [])

        self.assertEqual(_initial_preview_time(info, config), 777.0)
        self.assertEqual(_fmt_timestamp(777.0), "12:57")

    def test_initial_preview_time_clamps_to_duration(self):
        from app.config import AppConfig
        from app.layout_selector import _initial_preview_time
        from app.probe import VideoInfo

        config = AppConfig()
        config.layout_preview_time_sec = 999.0
        info = VideoInfo("test.mp4", 120.0, 30.0, 1920, 1080, [])

        self.assertEqual(_initial_preview_time(info, config), 120.0)

    def test_apply_selection_split_restores_between_subtitles(self):
        from app.config import AppConfig
        from app.layout_selector import LayoutSelection, apply_layout_selection

        config = AppConfig()
        config.subtitles_position = "slot_top"
        selection = LayoutSelection(
            webcam_crop=(10, 20, 300, 168),
            slot_crop=(400, 120, 1200, 700),
            source_size=(1920, 1080),
            preview_time_sec=120.0,
        )

        apply_layout_selection(config, selection)

        self.assertEqual(config.subtitles_position, "between_webcam_and_game")

    def test_apply_selection_with_one_crop_uses_no_webcam_top_subtitles(self):
        from app.config import AppConfig
        from app.layout_selector import LayoutSelection, apply_layout_selection

        config = AppConfig()
        selection = LayoutSelection(
            webcam_crop=(100, 50, 500, 280),
            slot_crop=None,
            source_size=(1920, 1080),
            preview_time_sec=120.0,
        )

        mode = apply_layout_selection(config, selection)

        self.assertEqual(mode, "single_crop_no_webcam")
        self.assertIsNone(config.manual_webcam_crop)
        self.assertEqual(config.manual_slot_crop, [100, 50, 500, 280])
        self.assertEqual(config.webcam_detection, "off")
        self.assertEqual(config.subtitles_position, "slot_top")

    def test_apply_selection_slot_only_mode_sets_explicit_layout_mode(self):
        from app.config import AppConfig
        from app.layout_selector import LayoutSelection, apply_layout_selection

        config = AppConfig()
        selection = LayoutSelection(
            webcam_crop=None,
            slot_crop=(240, 160, 1240, 760),
            source_size=(1920, 1080),
            preview_time_sec=120.0,
            apply_mode="slot_only",
        )

        mode = apply_layout_selection(config, selection)

        self.assertEqual(mode, "slot_only_no_webcam")
        self.assertEqual(config.layout_mode, "slot_only")
        self.assertIsNone(config.manual_webcam_crop)
        self.assertEqual(config.manual_slot_crop, [240, 160, 1240, 760])
        self.assertEqual(config.webcam_detection, "off")
        self.assertEqual(config.subtitles_position, "slot_top")

    def test_apply_selection_cinema_mode_works_without_manual_crop(self):
        from app.config import AppConfig
        from app.layout_selector import LayoutSelection, apply_layout_selection

        config = AppConfig()
        selection = LayoutSelection(
            webcam_crop=None,
            slot_crop=None,
            source_size=(1920, 1080),
            preview_time_sec=120.0,
            apply_mode="cinema",
        )

        mode = apply_layout_selection(config, selection)

        self.assertEqual(mode, "cinema_no_webcam")
        self.assertEqual(config.layout_mode, "cinema")
        self.assertIsNone(config.manual_webcam_crop)
        self.assertIsNone(config.manual_slot_crop)
        self.assertEqual(config.webcam_detection, "off")
        self.assertEqual(config.subtitles_position, "slot_top")

    def test_apply_selection_cinema_mode_can_keep_optional_webcam(self):
        from app.config import AppConfig
        from app.layout_selector import LayoutSelection, apply_layout_selection

        config = AppConfig()
        selection = LayoutSelection(
            webcam_crop=(100, 80, 480, 270),
            slot_crop=None,
            source_size=(1920, 1080),
            preview_time_sec=120.0,
            cinema_crop=(520, 140, 860, 620),
            apply_mode="cinema",
        )

        mode = apply_layout_selection(config, selection)

        self.assertEqual(mode, "cinema_with_webcam")
        self.assertEqual(config.layout_mode, "cinema")
        self.assertEqual(config.manual_webcam_crop, [100, 80, 480, 270])
        self.assertIsNone(config.manual_slot_crop)
        self.assertEqual(config.manual_cinema_crop, [520, 140, 860, 620])
        self.assertEqual(config.webcam_detection, "auto")
        self.assertEqual(config.subtitles_position, "between_webcam_and_game")

    def test_save_selection_appends_dataset(self):
        from app.config import AppConfig
        from app.layout_selector import LayoutSelection, save_layout_selection

        with tempfile.TemporaryDirectory() as td:
            config = AppConfig(output_dir=td)
            config.layout_preview_save_path = "layout_selection.json"
            config.layout_annotation_dataset_path = str(Path(td) / "annotations.jsonl")
            selection = LayoutSelection(
                webcam_crop=(10, 20, 300, 168),
                slot_crop=(400, 120, 1200, 700),
                source_size=(1920, 1080),
                preview_time_sec=120.0,
            )

            save_layout_selection(config, selection, "manual_split", video_path="video.mp4")

            dataset = Path(config.layout_annotation_dataset_path)
            self.assertTrue(dataset.exists())
            self.assertIn("manual_split", dataset.read_text(encoding="utf-8"))

    def test_preview_autofill_helpers_read_detection_results(self):
        from app.layout_selector import _crop_from_content_result, _crop_from_webcam_result
        from app.content_detector import ContentDetectionResult
        from app.webcam_types import WebcamDetectionResult, WebcamRegion

        webcam = WebcamDetectionResult(
            has_webcam=True,
            region=WebcamRegion(10, 20, 300, 168, 0.9),
            confidence=0.9,
        )
        content = ContentDetectionResult(True, (400, 120, 1200, 700), 0.8, "test")

        self.assertEqual(_crop_from_webcam_result(webcam), (10, 20, 300, 168))
        self.assertEqual(_crop_from_content_result(content), (400, 120, 1200, 700))


class TestSubtitles(unittest.TestCase):
    def test_ass_time_format(self):
        from app.subtitles import ass_time
        self.assertEqual(ass_time(0), "0:00:00.00")
        self.assertEqual(ass_time(65.5), "0:01:05.50")

    def test_clean_text(self):
        from app.subtitles import clean_text
        self.assertEqual(clean_text("[music] hello [laughter]"), "hello")
        self.assertEqual(clean_text("um hello uh world"), "hello world")
        self.assertEqual(clean_text("hello,"), "hello")
        self.assertEqual(clean_text("he,llo"), "hello")
        self.assertEqual(clean_text("ну,"), "ну")
        self.assertEqual(clean_text(","), "")

    def test_clean_text_filters_english_subtitles(self):
        from app.subtitles import clean_text

        self.assertEqual(clean_text("hello,", "en"), "hello")
        self.assertEqual(clean_text("helloПривет你好", "en"), "hello")
        self.assertEqual(clean_text("don't", "en"), "don't")
        self.assertEqual(clean_text("Привет", "en"), "")
        self.assertEqual(clean_text("你好", "en"), "")

    def test_clean_text_filters_russian_subtitles(self):
        from app.subtitles import clean_text

        self.assertEqual(clean_text("Приветhello你好", "ru"), "Привет")
        self.assertEqual(clean_text("щас", "ru"), "сейчас")
        self.assertEqual(clean_text("hello", "ru"), "")

    def test_generate_ass_empty(self):
        from app.subtitles import generate_ass_file
        from app.config import AppConfig
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.ass")
            generate_ass_file([], path, AppConfig())
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("[Script Info]", content)

    def test_generate_ass_between_webcam_and_game_position(self):
        from app.subtitles import SubtitleEvent, WordTiming, generate_ass_file
        from app.config import AppConfig

        config = AppConfig()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.ass")
            generate_ass_file(
                [SubtitleEvent(1.0, 2.0, "GAME", [WordTiming("GAME", 1.0, 2.0)])],
                path,
                config,
            )
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

        self.assertIn("FOX_ONE_WORD", content)
        self.assertIn(r"{\an5\pos(540,806)}GAME", content)

    def test_generate_ass_uses_language_template_and_strips_comma(self):
        from app.subtitles import generate_ass_file, generate_word_subtitles
        from app.config import AppConfig

        config = AppConfig()
        config.language = "ru"
        events = generate_word_subtitles(
            [{"word": "Привет,", "start": 0.0, "end": 0.4}],
            config,
        )

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "ru.ass")
            generate_ass_file(events, path, config)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

        self.assertIn("Style: FOX_ONE_WORD", content)
        self.assertIn("FOX_ONE_WORD,ru", content)
        self.assertIn("Привет", content)
        self.assertNotIn("Привет,", content)
        self.assertNotIn("Dialogue: 0,0:00:00.00,0:00:00.38,FOX_ONE_WORD,ru,0,0,0,,Просто", content)

    def test_generate_ass_uses_english_template(self):
        from app.subtitles import generate_ass_file, generate_word_subtitles
        from app.config import AppConfig

        config = AppConfig()
        config.language = "en"
        events = generate_word_subtitles(
            [
                {"word": "Hello,", "start": 0.0, "end": 0.4},
                {"word": "Привет", "start": 0.5, "end": 0.7},
                {"word": "你好", "start": 0.8, "end": 1.0},
                {"word": "world", "start": 1.1, "end": 1.3},
            ],
            config,
        )

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "en.ass")
            generate_ass_file(events, path, config)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

        self.assertIn("Title: FOX One Word EN", content)
        self.assertIn("FOX_ONE_WORD,en", content)
        self.assertIn("Hello", content)
        self.assertIn("world", content)
        self.assertNotIn("Hello,", content)
        self.assertNotIn("Привет", content)
        self.assertNotIn("你好", content)

    def test_generate_ass_slot_top_position(self):
        from app.subtitles import SubtitleEvent, WordTiming, generate_ass_file
        from app.config import AppConfig

        config = AppConfig()
        config.subtitles_position = "slot_top"
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "top.ass")
            generate_ass_file(
                [SubtitleEvent(1.0, 2.0, "TOP", [WordTiming("TOP", 1.0, 2.0)])],
                path,
                config,
            )
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

        self.assertIn(r"{\an8\pos(540,268)}TOP", content)

    def test_word_subtitles_hold_until_next_word_or_three_seconds(self):
        from app.subtitles import generate_word_subtitles
        from app.config import AppConfig

        words = [
            {"word": "hello", "start": 10.0, "end": 10.2},
            {"word": "world", "start": 11.25, "end": 11.5},
            {"word": "again", "start": 16.0, "end": 16.2},
        ]
        events = generate_word_subtitles(words, AppConfig(), clip_start=10.0)

        self.assertEqual([e.text for e in events], ["hello", "world", "again"])
        self.assertAlmostEqual(events[0].start, 0.0)
        self.assertAlmostEqual(events[0].end, 1.25)
        self.assertAlmostEqual(events[1].end, 4.25)
        self.assertAlmostEqual(events[2].end, 9.0)

    def test_word_subtitles_shift_after_cta_and_skip_freeze_overlap(self):
        from app.subtitles import generate_word_subtitles
        from app.config import AppConfig

        words = [
            {"word": "before", "start": 6.8, "end": 7.0},
            {"word": "after", "start": 8.0, "end": 8.2},
        ]
        events = generate_word_subtitles(
            words,
            AppConfig(),
            clip_start=0.0,
            cta_insert_start=7.0,
            cta_insert_duration=1.5,
        )

        self.assertAlmostEqual(events[0].end, 7.0)
        self.assertAlmostEqual(events[1].start, 9.5)

    def test_word_subtitles_do_not_overlap_duplicate_asr_starts(self):
        from app.subtitles import generate_word_subtitles
        from app.config import AppConfig

        words = [
            {"word": "one", "start": 2.0, "end": 2.1},
            {"word": "two", "start": 2.0, "end": 2.2},
            {"word": "three", "start": 2.0, "end": 2.3},
        ]
        events = generate_word_subtitles(words, AppConfig(), clip_start=0.0)

        self.assertLessEqual(events[0].end, events[1].start)
        self.assertLessEqual(events[1].end, events[2].start)
        self.assertGreater(events[2].start, events[0].start)


class TestCTAPause(unittest.TestCase):
    def test_pick_cta_text(self):
        from app.cta_pause import pick_cta_text
        from app.config import AppConfig
        config = AppConfig()
        text = pick_cta_text(config)
        self.assertIsInstance(text, str)
        self.assertTrue(len(text) > 0)

    def test_pick_cta_text_language(self):
        from app.cta_pause import effective_cta_language, pick_cta_text
        from app.config import AppConfig

        config = AppConfig()
        config.variation.enabled = False
        config.cta.language = "ru"
        self.assertEqual(pick_cta_text(config), "ИГРА В ОПИСАНИИ")
        self.assertEqual(effective_cta_language(config), "ru")
        config.cta.language = "en"
        self.assertEqual(pick_cta_text(config), "THE GAME IN BIO")
        self.assertEqual(effective_cta_language(config), "en")

    def test_pick_cta_text_follows_selected_subtitle_language_when_cta_auto(self):
        from app.cta_pause import effective_cta_language, pick_cta_text
        from app.config import AppConfig

        config = AppConfig()
        config.variation.enabled = False
        config.cta.language = "auto"
        config.language = "en"
        self.assertEqual(effective_cta_language(config), "en")
        self.assertEqual(pick_cta_text(config), "THE GAME IN BIO")

        config.language = "ru"
        self.assertEqual(effective_cta_language(config), "ru")
        self.assertEqual(pick_cta_text(config), "ИГРА В ОПИСАНИИ")

    def test_pick_cta_text_custom_mode(self):
        from app.cta_pause import pick_cta_text
        from app.config import AppConfig

        config = AppConfig()
        config.cta.text_mode = "custom"
        config.cta.custom_text = "МОЯ ИГРА ТУТ"

        self.assertEqual(pick_cta_text(config), "МОЯ ИГРА ТУТ")

    def test_prepare_cta_text_layout_wraps_long_text(self):
        from app.cta_pause import prepare_cta_text_layout
        from app.config import AppConfig

        config = AppConfig()
        lines, font_size = prepare_cta_text_layout(
            "ПОЛНОЕ ВИДЕО И САМАЯ ДЛИННАЯ НАДПИСЬ В ОПИСАНИИ",
            config,
            output_width=1080,
        )

        self.assertLessEqual(len(lines), config.cta.max_text_lines)
        self.assertLessEqual(font_size, config.cta.font_size)
        self.assertGreaterEqual(font_size, config.cta.min_font_size)

    def test_pick_cta_time(self):
        from app.cta_pause import pick_cta_trigger_time
        from app.config import AppConfig
        config = AppConfig()
        t = pick_cta_trigger_time(30.0, config)
        self.assertGreaterEqual(t, 7.0)
        self.assertLessEqual(t, 10.0)

    def test_pick_cta_time_accepts_freeze_override(self):
        from app.cta_pause import pick_cta_trigger_time
        from app.config import AppConfig

        config = AppConfig()
        config.variation.enabled = False
        config.cta.trigger_range_sec = [7.0, 10.0]

        t = pick_cta_trigger_time(12.0, config, freeze_duration_sec=8.0)

        self.assertLessEqual(t + 8.0, 12.0)

    def test_typewriter_filters_do_not_stack_partials_until_end(self):
        from app.cta_pause import build_cta_segment_filter
        from app.config import AppConfig
        config = AppConfig()
        config.cta.freeze_duration_sec = 1.5
        config.cta.typewriter_speed = 0.1

        filter_str, _, _ = build_cta_segment_filter(
            clip_duration=30.0,
            cta_text="ABC",
            config=config,
            cta_start_sec=7.0,
        )

        self.assertIn("text='A'", filter_str)
        self.assertIn("enable='between(t,0.150,0.250)'", filter_str)
        self.assertIn("text='ABC'", filter_str)
        self.assertIn("enable='between(t,0.350,1.500)'", filter_str)

    def test_cta_segment_filter_uses_freeze_override(self):
        from app.cta_pause import build_cta_segment_filter
        from app.config import AppConfig

        config = AppConfig()
        config.cta.freeze_duration_sec = 4.0

        filter_str, cta_start, cta_end = build_cta_segment_filter(
            clip_duration=30.0,
            cta_text="ABC",
            config=config,
            cta_start_sec=7.0,
            freeze_duration_sec=1.25,
        )

        self.assertAlmostEqual(cta_start, 7.0)
        self.assertAlmostEqual(cta_end, 8.25)
        self.assertIn("tpad=stop_duration=1.250", filter_str)


class TestAudioMix(unittest.TestCase):
    def test_find_music_files_empty(self):
        from app.audio_mix import find_music_files
        with tempfile.TemporaryDirectory() as td:
            files = find_music_files(td)
            self.assertEqual(files, [])

    def test_final_audio_mix_accepts_explicit_music_volume(self):
        from app.audio_mix import build_final_audio_mix
        from app.config import AppConfig

        config = AppConfig()
        config.music.duck_under_speech = True
        with tempfile.TemporaryDirectory() as td:
            track = Path(td) / "track.mp3"
            track.write_bytes(b"fake")
            filter_str = build_final_audio_mix(
                clip_duration=10.0,
                music_path=str(track),
                config=config,
                music_input_idx=1,
                has_original_audio=True,
                music_volume=0.10,
            )

        self.assertIn("volume=0.100", filter_str)

    def test_final_audio_mix_can_boost_music_ending(self):
        from app.audio_mix import build_final_audio_mix
        from app.config import AppConfig

        config = AppConfig()
        with tempfile.TemporaryDirectory() as td:
            track = Path(td) / "track.mp3"
            track.write_bytes(b"fake")
            filter_str = build_final_audio_mix(
                clip_duration=30.0,
                music_path=str(track),
                config=config,
                music_input_idx=1,
                has_original_audio=True,
                final_duration_sec=30.0,
                music_volume=0.05,
                music_ending_volume=0.60,
                music_ending_duration_sec=4.5,
            )

        self.assertIn("if(gte(t\\,25.500)\\,0.600\\,0.050)", filter_str)
        self.assertIn(":eval=frame", filter_str)


class TestCleanup(unittest.TestCase):
    def test_delete_input_after_success_removes_video_only_after_outputs_exist(self):
        from app.cleanup import delete_input_after_success

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.mp4"
            output = Path(td) / "clip.mp4"
            source.write_bytes(b"source")
            output.write_bytes(b"clip")

            self.assertTrue(delete_input_after_success(str(source), [str(output)]))
            self.assertFalse(source.exists())

    def test_delete_input_after_success_skips_when_output_missing(self):
        from app.cleanup import delete_input_after_success

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.mp4"
            source.write_bytes(b"source")

            self.assertFalse(delete_input_after_success(str(source), [str(Path(td) / "missing.mp4")]))
            self.assertTrue(source.exists())


class TestRenderer(unittest.TestCase):
    def test_video_encode_args_use_crf(self):
        from app.renderer import _video_encode_args
        from app.config import AppConfig

        config = AppConfig()
        args = _video_encode_args(config)
        self.assertIn("-crf", args)
        self.assertIn("19", args)
        self.assertIn("slower", args)

    def test_video_encode_args_presets(self):
        from app.renderer import _video_encode_args
        from app.config import AppConfig

        config = AppConfig()
        config.export.render_preset = "fast"
        fast_args = _video_encode_args(config)
        self.assertIn("veryfast", fast_args)
        self.assertIn("23", fast_args)

        config.export.render_preset = "balanced"
        balanced_args = _video_encode_args(config)
        self.assertIn("medium", balanced_args)
        self.assertIn("21", balanced_args)

        config.export.render_preset = "nvenc_fast"
        nvenc_args = _video_encode_args(config)
        self.assertIn("h264_nvenc", nvenc_args)
        self.assertIn("-cq", nvenc_args)

    def test_cinema_music_only_applies_to_cinema_layout(self):
        from app.config import AppConfig
        from app.layout import LayoutSpec
        from app.renderer import _select_cinema_music

        config = AppConfig()
        config.music.enabled = True
        with tempfile.TemporaryDirectory() as td:
            track = Path(td) / "cinema.mp3"
            track.write_bytes(b"fake")
            config.cinema_music.folder = td

            slot_layout = LayoutSpec(
                has_webcam=False,
                mode="slot_only",
                content_src=(0, 0, 1920, 1080),
                content_out=(0, 0, 1080, 1920),
                output_size=(1080, 1920),
            )
            music_path, music_volume, ending_volume, ending_duration = _select_cinema_music(slot_layout, config)
            self.assertIsNone(music_path)
            self.assertIsNone(music_volume)
            self.assertIsNone(ending_volume)
            self.assertEqual(ending_duration, 0.0)

            cinema_layout = LayoutSpec(
                has_webcam=False,
                mode="cinema",
                content_src=(0, 0, 1920, 1080),
                content_out=(0, 0, 1080, 1920),
                output_size=(1080, 1920),
            )
            config.cinema_music.volume = 0.50
            music_path, music_volume, ending_volume, ending_duration = _select_cinema_music(cinema_layout, config)

        self.assertEqual(Path(music_path).name, "cinema.mp3")
        self.assertEqual(music_volume, 0.10)
        self.assertEqual(ending_volume, 0.60)
        self.assertEqual(ending_duration, 4.5)

    def test_cta_freeze_duration_prefers_voice_duration(self):
        from app.renderer import _cta_freeze_duration
        from app.config import AppConfig

        config = AppConfig()
        config.cta.freeze_duration_sec = 4.0

        self.assertEqual(_cta_freeze_duration(config, 1.75), 1.75)
        self.assertEqual(_cta_freeze_duration(config, None), 4.0)


class TestASR(unittest.TestCase):
    def test_whisper_cache_dir_is_project_persistent_by_default(self):
        from app.asr import _whisper_cache_dir
        from app.config import AppConfig

        config = AppConfig()
        path = Path(_whisper_cache_dir(config))

        self.assertEqual(path.name, "whisper")
        self.assertEqual(path.parent.name, "models")
        self.assertNotIn("temp", path.parts)


class TestCache(unittest.TestCase):
    def test_json_cache_roundtrip(self):
        from app.cache import load_json_cache, save_json_cache
        from app.config import AppConfig

        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "video.mp4"
            video.write_bytes(b"fake")
            config = AppConfig()
            config.cache.dir = str(Path(td) / "cache")

            save_json_cache(config, "asr", video, {"words": [{"word": "ok"}]}, {"lang": "en"})
            cached = load_json_cache(config, "asr", video, {"lang": "en"})

            self.assertEqual(cached["words"][0]["word"], "ok")


class TestLayoutDataset(unittest.TestCase):
    def test_scaled_layout_crops(self):
        from app.config import AppConfig
        from app.layout_dataset import append_layout_annotation, load_scaled_layout_crops

        with tempfile.TemporaryDirectory() as td:
            config = AppConfig()
            config.layout_annotation_dataset_path = str(Path(td) / "annotations.jsonl")
            append_layout_annotation(
                config,
                mode="manual_split",
                source_size=(1000, 500),
                preview_time_sec=10.0,
                webcam_crop=(800, 0, 200, 100),
                slot_crop=(100, 50, 700, 350),
                video_path="video.mp4",
            )

            rows = load_scaled_layout_crops(config, 2000, 1000)

            self.assertEqual(rows[0]["webcam_crop"], (1600, 0, 400, 200))
            self.assertEqual(rows[0]["slot_crop"], (200, 100, 1400, 700))


class TestWebcamDetector(unittest.TestCase):
    def _iou(self, a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ix1 = max(ax, bx)
        iy1 = max(ay, by)
        ix2 = min(ax + aw, bx + bw)
        iy2 = min(ay + ah, by + bh)
        if ix1 >= ix2 or iy1 >= iy2:
            return 0.0
        inter = (ix2 - ix1) * (iy2 - iy1)
        return inter / float(aw * ah + bw * bh - inter)

    def test_webcam_candidates_cover_edges_with_inset(self):
        from app.webcam_detector import _generate_webcam_candidates

        candidates = _generate_webcam_candidates(1920, 1080, edge_margin_ratio=0.15)

        self.assertTrue(any(x == 0 and y == 0 for x, y, _, _ in candidates))
        self.assertTrue(any(x > 0 and x <= 288 for x, _, _, _ in candidates))
        self.assertTrue(any(x + w == 1920 for x, _, w, _ in candidates))
        self.assertTrue(any(y + h == 1080 for _, y, _, h in candidates))

    def test_webcam_candidates_cover_user_reference_layouts(self):
        from app.webcam_detector import _generate_webcam_candidates

        refs = [
            (1182, 664, (0, 288, 314, 176)),
            (1181, 663, (965, 3, 213, 150)),
            (1177, 666, (782, 18, 381, 216)),
            (1176, 660, (913, 196, 263, 160)),
            (1179, 671, (801, 55, 343, 189)),
            (1181, 665, (817, 431, 361, 215)),
        ]

        for frame_w, frame_h, expected in refs:
            candidates = _generate_webcam_candidates(frame_w, frame_h, 0.15)
            best_iou = max(self._iou(c, expected) for c in candidates)
            self.assertGreater(best_iou, 0.45, (frame_w, frame_h, expected, best_iou))

    def test_webcam_candidates_scan_full_left_and_right_sides(self):
        from app.webcam_detector import _generate_webcam_candidates

        candidates = _generate_webcam_candidates(1920, 1080, 0.15)
        side_y_centers = [
            y + h / 2
            for x, y, w, h in candidates
            if x <= 1920 * 0.24 or x + w >= 1920 * 0.76
        ]

        self.assertTrue(any(cy < 1080 * 0.20 for cy in side_y_centers))
        self.assertTrue(any(1080 * 0.40 <= cy <= 1080 * 0.60 for cy in side_y_centers))
        self.assertTrue(any(cy > 1080 * 0.80 for cy in side_y_centers))

    def test_webcam_manual_override_has_priority(self):
        from unittest.mock import patch
        import numpy as np
        from app.config import AppConfig
        from app.webcam_detector import detect_webcam

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        config = AppConfig()
        config.manual_webcam_crop = [101, 203, 321, 181]

        with (
            patch("app.webcam_detector._ensure_opencv", return_value=True),
            patch("app.webcam_detector._extract_frames", return_value=[frame, frame, frame]),
        ):
            result = detect_webcam("dummy.mp4", config)

        self.assertTrue(result.has_webcam)
        self.assertEqual((result.region.x, result.region.y, result.region.w, result.region.h), (101, 203, 320, 180))

    def test_webcam_detection_can_select_right_top_overlay(self):
        from unittest.mock import patch
        import numpy as np
        from app.config import AppConfig
        from app.webcam_detector import detect_webcam

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        faces = [(1030, 80, 70, 70)]

        with (
            patch("app.webcam_detector._ensure_opencv", return_value=True),
            patch("app.webcam_detector._extract_frames", return_value=[frame, frame, frame]),
            patch("app.webcam_detector._detect_face_boxes", return_value=faces),
            patch("app.webcam_detector._find_stable_regions", return_value={}),
            patch("app.webcam_detector._compute_edge_density_scores", return_value=np.zeros((11, 20))),
            patch("app.webcam_detector._webcam_boundary_contrast_score", return_value=0.0),
        ):
            result = detect_webcam("dummy.mp4", AppConfig())

        self.assertTrue(result.has_webcam)
        self.assertGreater(result.region.x, 1280 * 0.55)
        self.assertLess(result.region.y, 720 * 0.20)

    def test_webcam_detection_can_select_left_bottom_overlay(self):
        from unittest.mock import patch
        import numpy as np
        from app.config import AppConfig
        from app.webcam_detector import detect_webcam

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        faces = [(75, 575, 70, 70)]

        with (
            patch("app.webcam_detector._ensure_opencv", return_value=True),
            patch("app.webcam_detector._extract_frames", return_value=[frame, frame, frame]),
            patch("app.webcam_detector._detect_face_boxes", return_value=faces),
            patch("app.webcam_detector._find_stable_regions", return_value={}),
            patch("app.webcam_detector._compute_edge_density_scores", return_value=np.zeros((11, 20))),
            patch("app.webcam_detector._webcam_boundary_contrast_score", return_value=0.0),
        ):
            result = detect_webcam("dummy.mp4", AppConfig())

        self.assertTrue(result.has_webcam)
        self.assertLess(result.region.x, 1280 * 0.20)
        self.assertGreater(result.region.y, 720 * 0.50)

    def test_webcam_refinement_trims_slot_and_bottom_ui_strips(self):
        import numpy as np
        from app.webcam_detector import _refine_webcam_region

        frame = np.zeros((320, 540, 3), dtype=np.uint8)
        frame[:290, :518] = (130, 130, 130)
        frame[:290, 480:518] = (15, 15, 220)
        frame[267:290, :480] = (28, 28, 28)
        roi = (0, 0, 518, 290)
        faces = [(220, 150, 70, 70)]

        refined = _refine_webcam_region([frame] * 3, roi, faces, 1920, 1080, 0.15)

        self.assertLessEqual(refined[2], 490)
        self.assertGreaterEqual(refined[2], 470)
        self.assertLessEqual(refined[3], 274)
        self.assertGreaterEqual(refined[3], 258)

    def test_webcam_refinement_keeps_clean_panel(self):
        import numpy as np
        from app.webcam_detector import _refine_webcam_region

        frame = np.zeros((320, 540, 3), dtype=np.uint8)
        frame[:270, :480] = (120, 120, 120)
        roi = (0, 0, 480, 270)
        faces = [(210, 145, 70, 70)]

        refined = _refine_webcam_region([frame] * 3, roi, faces, 1920, 1080, 0.15)

        self.assertEqual(refined, roi)

    def test_webcam_refinement_trims_inner_bottom_corner_bleed(self):
        import numpy as np
        from app.webcam_detector import _refine_webcam_region

        frame = np.zeros((320, 540, 3), dtype=np.uint8)
        frame[:270, :480] = (120, 120, 120)
        frame[265:270, 404:480] = (10, 10, 220)
        roi = (0, 0, 480, 270)
        faces = [(210, 145, 70, 70)]

        refined = _refine_webcam_region([frame] * 3, roi, faces, 1920, 1080, 0.15)

        self.assertEqual(refined[0], 0)
        self.assertEqual(refined[2], 480)
        self.assertLessEqual(refined[3], 266)
        self.assertGreaterEqual(refined[3], 258)

    def test_edge_proximity_penalizes_interior(self):
        from app.webcam_detector import _edge_proximity_score

        edge_score, _ = _edge_proximity_score((40, 40, 320, 180), 1920, 1080, 0.15)
        interior_score, _ = _edge_proximity_score((760, 420, 320, 180), 1920, 1080, 0.15)

        self.assertGreater(edge_score, 0)
        self.assertLess(interior_score, 0)

    def test_left_edge_roi_ignores_faces_on_inner_side(self):
        from app.webcam_detector import _count_faces_in_roi

        roi = (76, 162, 691, 388)
        faces = [
            (730, 197, 55, 55),  # slot false-positive on the inner side
            (220, 626, 69, 69),  # below this ROI, not inside it
        ]

        self.assertEqual(_count_faces_in_roi(roi, faces, 1920, 1080, 0.15), 0)

    def test_webcam_not_selected_without_face_evidence(self):
        from unittest.mock import patch
        import numpy as np
        from app.config import AppConfig
        from app.webcam_detector import detect_webcam

        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        with (
            patch("app.webcam_detector._ensure_opencv", return_value=True),
            patch("app.webcam_detector._extract_frames", return_value=[frame, frame, frame]),
            patch("app.webcam_detector._detect_face_boxes", return_value=[]),
            patch("app.webcam_detector._find_stable_regions", return_value={}),
            patch("app.webcam_detector._compute_edge_density_scores", return_value=np.zeros((16, 30))),
            patch("app.webcam_detector._get_edge_score_in_roi", return_value=0.0),
        ):
            result = detect_webcam("dummy.mp4", AppConfig())

        self.assertFalse(result.has_webcam)


class TestContentDetector(unittest.TestCase):
    def test_centered_content_crop_for_no_webcam(self):
        from app.content_detector import centered_content_crop

        crop = centered_content_crop(1920, 1080)

        self.assertEqual(crop[0], 38)
        self.assertEqual(crop[2], 1844)
        self.assertGreater(crop[1], 0)

    def test_adjust_crop_for_webcam_overlap_trims_left_side(self):
        from app.content_detector import _adjust_crop_for_webcam_overlap

        crop, reason = _adjust_crop_for_webcam_overlap(
            (0, 0, 1920, 1080),
            (0, 420, 360, 220),
            1920,
            1080,
            safe_margin=20,
        )

        self.assertEqual(reason, "trim_left_overlap")
        self.assertGreaterEqual(crop[0], 380)

    def test_adjust_crop_no_webcam_keeps_crop(self):
        from app.content_detector import _adjust_crop_for_webcam_overlap

        crop, reason = _adjust_crop_for_webcam_overlap(
            (38, 42, 1842, 994),
            None,
            1920,
            1080,
        )

        self.assertEqual(crop, (38, 42, 1842, 994))
        self.assertEqual(reason, "")

    def test_detect_content_area_without_webcam_returns_centered_crop(self):
        from app.content_detector import detect_content_area, centered_content_crop
        from app.config import AppConfig
        from app.probe import VideoInfo
        from app.webcam_types import WebcamDetectionResult

        info = VideoInfo(
            path="test.mp4",
            duration_sec=60,
            fps=30,
            width=1920,
            height=1080,
            audio_streams=[],
        )
        result = detect_content_area(
            "missing.mp4",
            info,
            WebcamDetectionResult(has_webcam=False),
            AppConfig(),
        )

        self.assertEqual(result.crop, centered_content_crop(1920, 1080))
        self.assertEqual(result.reason, "centered")

    def test_content_candidates_do_not_cut_slot_around_webcam(self):
        from app.content_detector import _content_candidates

        candidates = _content_candidates(1182, 664, (0, 288, 314, 176))

        self.assertFalse(any(reason in {"right_of_webcam", "profile_left_webcam_slot"} for _, reason in candidates))
        self.assertTrue(any(reason.startswith("profile_ref_") for _, reason in candidates))

    def test_reference_profiles_cover_annotated_layouts(self):
        from app.content_detector import _reference_profile_candidates

        refs = [
            (1087, 588, (0, 264, 288, 165), "profile_ref_stake_left_overlay"),
            (1279, 719, (1043, 2, 236, 165), "profile_ref_fixa_small_top_right"),
            (1284, 724, (891, 469, 393, 235), "profile_ref_vavada_bottom_right"),
            (1277, 723, (850, 23, 414, 233), "profile_ref_right_rail_top_webcam"),
            (1279, 724, (874, 53, 369, 206), "profile_ref_ezugi_top_right"),
            (1272, 720, (968, 466, 304, 254), "profile_ref_chat_right_bottom_webcam"),
            (1281, 723, (2, 516, 311, 205), "profile_ref_bottom_left_webcam"),
            (1280, 722, (760, 442, 344, 278), "profile_ref_mendigo_bottom_overlay"),
        ]

        for frame_w, frame_h, webcam, reason in refs:
            candidates = _reference_profile_candidates(frame_w, frame_h, webcam)
            self.assertTrue(any(candidate_reason == reason for _, candidate_reason in candidates), reason)

    def test_reference_profiles_keep_full_slot_even_when_webcam_overlaps(self):
        from app.content_detector import _reference_profile_candidates

        frame_w, frame_h = 1087, 588
        webcam = (0, 264, 288, 165)
        candidates = _reference_profile_candidates(frame_w, frame_h, webcam)
        slot = next(crop for crop, reason in candidates if reason == "profile_ref_stake_left_overlay")

        self.assertLess(slot[0], webcam[0] + webcam[2])

    def test_active_content_candidates_can_shift_left_or_right(self):
        import numpy as np
        from app.content_detector import _active_content_candidates

        activity = np.zeros((12, 20), dtype=np.float32)
        activity[2:9, 1:9] = 1.0
        left_candidate = _active_content_candidates(1920, 1080, activity)[0][0]

        activity = np.zeros((12, 20), dtype=np.float32)
        activity[2:9, 11:19] = 1.0
        right_candidate = _active_content_candidates(1920, 1080, activity)[0][0]

        self.assertLess(left_candidate[0], 1920 * 0.20)
        self.assertGreater(right_candidate[0], 1920 * 0.40)

    def test_frame_content_candidates_extract_large_game_frame(self):
        import cv2
        import numpy as np
        from app.content_detector import _frame_content_candidates

        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        cv2.rectangle(frame, (58, 217), (1182, 893), (255, 255, 255), 5)
        cv2.rectangle(frame, (1243, 25), (1864, 392), (255, 255, 255), 5)

        candidates = _frame_content_candidates(cv2, np, [frame])
        game_candidates = [crop for crop, reason in candidates if reason.startswith("frame_rect_")]

        self.assertTrue(any(crop[0] < 80 and crop[1] < 240 and crop[2] > 1100 for crop in game_candidates))

    def test_content_manual_override_has_priority(self):
        from app.content_detector import detect_content_area
        from app.config import AppConfig
        from app.probe import VideoInfo
        from app.webcam_types import WebcamDetectionResult

        config = AppConfig()
        config.manual_slot_crop = [11, 22, 333, 222]
        info = VideoInfo("test.mp4", 60, 30, 1280, 720, [])

        result = detect_content_area("missing.mp4", info, WebcamDetectionResult(False), config)

        self.assertEqual(result.crop, (11, 22, 332, 222))
        self.assertEqual(result.reason, "manual_slot_crop")


class TestHighlightDetector(unittest.TestCase):
    def test_fallback_highlights(self):
        from app.highlight_detector import _fallback_highlights
        from app.config import AppConfig
        from app.probe import VideoInfo

        info = VideoInfo(
            path="test.mp4",
            duration_sec=300,
            fps=30,
            width=1920,
            height=1080,
            audio_streams=[],
        )
        config = AppConfig(clips_override=3)
        segments = _fallback_highlights(info, config)
        self.assertEqual(len(segments), 3)
        for s in segments:
            self.assertGreaterEqual(s.end_sec - s.start_sec, config.min_clip_duration_sec)

    def test_audio_feature_bundle_runs_without_librosa(self):
        import numpy as np
        import soundfile as sf

        from app.highlight_detector import _compute_audio_feature_bundle

        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "audio.wav"
            sr = 22050
            silence = np.zeros(sr, dtype=np.float32)
            t = np.linspace(0, 1, sr, endpoint=False, dtype=np.float32)
            tone = 0.5 * np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
            samples = np.concatenate([silence, tone, silence])
            sf.write(audio_path, samples, sr)

            rms, brightness, onset, out_sr = _compute_audio_feature_bundle(str(audio_path))

            self.assertGreater(len(rms), 0)
            self.assertEqual(len(rms), len(brightness))
            self.assertEqual(len(rms), len(onset))
            self.assertGreater(out_sr, 0)

    def test_fill_missing_segments_avoids_clones(self):
        from app.highlight_detector import HighlightSegment, _fill_missing_segments

        selected = [HighlightSegment(start_sec=10, end_sec=55, score=0.9)]
        fallback = [
            HighlightSegment(start_sec=12, end_sec=57, score=0.5),
            HighlightSegment(start_sec=100, end_sec=145, score=0.5),
            HighlightSegment(start_sec=200, end_sec=245, score=0.5),
        ]
        filled = _fill_missing_segments(selected, fallback, target_count=3, min_gap=2.0)

        self.assertEqual(len(filled), 3)
        self.assertEqual(filled[1].start_sec, 100)
        self.assertEqual(filled[2].start_sec, 200)

    def test_duration_variation_allows_only_two_same_lengths_then_steps_down(self):
        from app.highlight_detector import HighlightSegment, _apply_duration_variation
        from app.config import AppConfig
        from app.probe import VideoInfo

        info = VideoInfo("video.mp4", 600, 30, 1280, 720, [])
        config = AppConfig(clips_override=5)
        segments = [
            HighlightSegment(i * 80, i * 80 + 45, 0.8, ["test"], "scored")
            for i in range(5)
        ]

        varied = _apply_duration_variation(segments, info, config)
        durations = [round(segment.end_sec - segment.start_sec) for segment in varied]

        self.assertEqual(durations, [45, 45, 43, 40, 36])
        self.assertLessEqual(max(durations.count(duration) for duration in set(durations)), 2)

    def test_duration_variation_respects_min_duration(self):
        from app.highlight_detector import HighlightSegment, _apply_duration_variation
        from app.config import AppConfig
        from app.probe import VideoInfo

        info = VideoInfo("video.mp4", 600, 30, 1280, 720, [])
        config = AppConfig(clips_override=5)
        config.min_clip_duration_sec = 40
        segments = [
            HighlightSegment(i * 80, i * 80 + 45, 0.8, ["test"], "scored")
            for i in range(5)
        ]

        varied = _apply_duration_variation(segments, info, config)
        durations = [round(segment.end_sec - segment.start_sec) for segment in varied]

        self.assertEqual(durations, [45, 45, 43, 40, 40])

    def test_highlight_report_writes_reasons(self):
        from app.highlight_detector import HighlightSegment, write_highlight_report
        from app.config import AppConfig
        from app.probe import VideoInfo
        import json

        with tempfile.TemporaryDirectory() as td:
            config = AppConfig(output_dir=td, clips_override=1)
            info = VideoInfo("video.mp4", 60, 30, 1280, 720, [])
            write_highlight_report(
                info,
                [
                    HighlightSegment(
                        1,
                        11,
                        0.75,
                        ["audio_energy"],
                        "scored",
                        peak_sec=3.0,
                        hook_mode="stream",
                        hook_reason="question_lead",
                        hook_intro_score=0.88,
                        hook_text_preview="What did you do?",
                        question_like=True,
                    )
                ],
                config,
                asr_metadata={"mode": "two_pass"},
            )

            report = Path(td) / "highlight_report.json"
            self.assertTrue(report.exists())
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["asr"]["mode"], "two_pass")
            self.assertIn("audio_energy", payload["segments"][0]["reasons"])
            self.assertEqual(payload["segments"][0]["hook_reason"], "question_lead")
            self.assertTrue(payload["segments"][0]["question_like"])

    def test_hook_optimizer_prefers_question_led_opening_when_supported(self):
        import numpy as np

        from app.config import AppConfig
        from app.highlight_detector import HighlightSegment, _apply_hook_optimization
        from app.probe import VideoInfo

        config = AppConfig(language="en", clips_override=1)
        info = VideoInfo("video.mp4", 60.0, 30.0, 1280, 720, [])
        segment = HighlightSegment(10.0, 30.0, 0.9, ["audio_energy"], "scored", peak_sec=15.0)
        asr_segments = [
            {"start": 11.0, "end": 12.0, "text": "What did you do?"},
            {"start": 15.0, "end": 16.0, "text": "run now"},
        ]

        signal = np.zeros(80, dtype=np.float32)
        rms = np.zeros(80, dtype=np.float32)
        centroid = np.zeros(80, dtype=np.float32)
        onset = np.zeros(80, dtype=np.float32)
        signal[11:14] = 0.75
        signal[15:18] = 0.50
        rms[11:14] = 0.55
        rms[15:18] = 0.35
        centroid[11:14] = 0.30
        centroid[15:18] = 0.20
        onset[11:14] = 0.80
        onset[15:18] = 0.55

        optimized = _apply_hook_optimization(
            [segment],
            signal,
            rms,
            centroid,
            onset,
            1.0,
            asr_segments,
            "video.mp4",
            info,
            config,
        )[0]

        self.assertLessEqual(optimized.start_sec, 11.25)
        self.assertTrue(optimized.question_like)
        self.assertEqual(optimized.hook_reason, "question_lead")
        self.assertIn("What did you do", optimized.hook_text_preview)
        self.assertTrue(optimized.start_sec <= optimized.peak_sec <= optimized.end_sec)

    def test_hook_optimizer_uses_non_question_cold_open_when_transcript_is_weak(self):
        import numpy as np

        from app.config import AppConfig
        from app.highlight_detector import HighlightSegment, _apply_hook_optimization
        from app.probe import VideoInfo

        config = AppConfig(language="en", clips_override=1)
        info = VideoInfo("video.mp4", 60.0, 30.0, 1280, 720, [])
        segment = HighlightSegment(10.0, 30.0, 0.9, ["audio_energy"], "scored", peak_sec=15.0)
        asr_segments = [
            {"start": 13.0, "end": 14.0, "text": "come on now"},
            {"start": 15.0, "end": 16.0, "text": "run run run"},
        ]

        signal = np.zeros(80, dtype=np.float32)
        rms = np.zeros(80, dtype=np.float32)
        centroid = np.zeros(80, dtype=np.float32)
        onset = np.zeros(80, dtype=np.float32)
        signal[15:18] = 0.90
        rms[15:18] = 0.70
        centroid[15:18] = 0.35
        onset[15:18] = 0.95

        optimized = _apply_hook_optimization(
            [segment],
            signal,
            rms,
            centroid,
            onset,
            1.0,
            asr_segments,
            "video.mp4",
            info,
            config,
        )[0]

        self.assertFalse(optimized.question_like)
        self.assertIn(optimized.hook_reason, {"cold_open_strength", "dialogue_hook", "dead_air_trim"})
        self.assertTrue(optimized.start_sec <= optimized.peak_sec <= optimized.end_sec)

    def test_hook_optimizer_distinguishes_movie_from_stream_mode(self):
        import numpy as np

        from app.config import AppConfig
        from app.highlight_detector import HighlightSegment, _apply_hook_optimization
        from app.probe import VideoInfo

        info = VideoInfo("video.mp4", 60.0, 30.0, 1280, 720, [])
        segment = HighlightSegment(10.0, 30.0, 0.9, ["audio_energy"], "scored", peak_sec=15.0)
        asr_segments = [
            {"start": 11.0, "end": 12.0, "text": "What did you see?"},
            {"start": 15.0, "end": 16.0, "text": "look over there"},
        ]

        signal = np.zeros(80, dtype=np.float32)
        rms = np.zeros(80, dtype=np.float32)
        centroid = np.zeros(80, dtype=np.float32)
        onset = np.zeros(80, dtype=np.float32)
        signal[11:14] = [0.50, 0.45, 0.40]
        signal[15:18] = [0.95, 0.95, 0.95]
        rms[11:14] = [0.30, 0.25, 0.20]
        rms[15:18] = [0.90, 0.80, 0.70]
        centroid[11:14] = [0.10, 0.10, 0.10]
        centroid[15:18] = [0.40, 0.40, 0.40]
        onset[11:14] = [0.30, 0.20, 0.10]
        onset[15:18] = [1.00, 0.80, 0.50]

        movie_config = AppConfig(language="en", layout_mode="cinema", clips_override=1)
        stream_config = AppConfig(language="en", layout_mode="auto", clips_override=1)

        visual_payload = {"motion": [0.0] * 80, "luma": [0.4] * 80, "step_sec": 1.0}
        for idx in range(11, 14):
            visual_payload["motion"][idx] = 0.45
        visual_payload["luma"][11:14] = [0.2, 0.7, 0.3]

        with patch("app.highlight_detector._load_visual_hook_signal", return_value=visual_payload):
            movie_segment = _apply_hook_optimization(
                [segment],
                signal,
                rms,
                centroid,
                onset,
                1.0,
                asr_segments,
                "video.mp4",
                info,
                movie_config,
            )[0]

        stream_segment = _apply_hook_optimization(
            [segment],
            signal,
            rms,
            centroid,
            onset,
            1.0,
            asr_segments,
            "video.mp4",
            info,
            stream_config,
        )[0]

        self.assertNotEqual(movie_segment.start_sec, stream_segment.start_sec)
        self.assertEqual(movie_segment.hook_mode, "movie")
        self.assertEqual(stream_segment.hook_mode, "stream")
        self.assertTrue(movie_segment.start_sec < stream_segment.start_sec)


class TestDownloader(unittest.TestCase):
    def test_is_url(self):
        from app.downloader import is_url
        self.assertTrue(is_url("https://youtube.com/watch"))
        self.assertFalse(is_url("D:\\video.mp4"))

    def test_curl_cert_error_detection(self):
        from app.downloader import _looks_like_curl_cert_error

        err = RuntimeError(
            "curl: (77) error setting certificate verify locations: "
            "CAfile: C:\\Users\\Name\\Lib\\site-packages\\certifi\\cacert.pem"
        )

        self.assertTrue(_looks_like_curl_cert_error(err))
        self.assertFalse(_looks_like_curl_cert_error(RuntimeError("regular network error")))

    def test_configure_yt_dlp_tls_returns_existing_ascii_path(self):
        from app.downloader import configure_yt_dlp_tls

        ca_bundle = configure_yt_dlp_tls()

        if ca_bundle is not None:
            self.assertTrue(Path(ca_bundle).exists())
            ca_bundle.encode("ascii")


class TestAsrTwoPass(unittest.TestCase):
    def test_run_discovery_asr_skips_language_detection_for_explicit_language(self):
        from app.asr import DiscoveryASRResult, run_discovery_asr
        from app.config import AppConfig

        config = AppConfig(language="en")

        with tempfile.TemporaryDirectory() as td:
            video_path = str(Path(td) / "video.mp4")
            Path(video_path).write_bytes(b"fake")

            with (
                patch("app.asr._extract_audio_for_asr", return_value=True),
                patch("app.asr._get_audio_duration", return_value=30.0),
                patch("app.asr._load_or_detect_language", side_effect=AssertionError("language detection should be skipped")),
                patch("app.asr._load_whisper_model", return_value=object()),
                patch("app.asr._should_chunk_asr", return_value=False),
                patch("app.asr._run_with_asr_progress", side_effect=lambda **kwargs: kwargs["work"]()),
                patch("app.asr._transcribe_segment_rows_monolithic", return_value=[{"text": "Hello there", "start": 0.0, "end": 1.0}]),
            ):
                result = run_discovery_asr(video_path, td, config)

        self.assertIsInstance(result, DiscoveryASRResult)
        self.assertEqual(result.language, "en")
        self.assertEqual(result.model, "medium.en")

    def test_run_discovery_asr_uses_segment_timings_only(self):
        from app.asr import run_discovery_asr
        from app.config import AppConfig

        config = AppConfig(language="en")

        with tempfile.TemporaryDirectory() as td:
            video_path = str(Path(td) / "video.mp4")
            Path(video_path).write_bytes(b"fake")

            class _Segment:
                def __init__(self, start, end, text):
                    self.start = start
                    self.end = end
                    self.text = text

            calls = []

            def _fake_transcribe(_model, _audio, _lang, *, word_timestamps):
                calls.append(word_timestamps)
                return iter([_Segment(0.0, 1.0, "What happened?")]), type("Info", (), {"language": "en"})(), False

            with (
                patch("app.asr._extract_audio_for_asr", return_value=True),
                patch("app.asr._get_audio_duration", return_value=30.0),
                patch("app.asr._load_whisper_model", return_value=object()),
                patch("app.asr._should_chunk_asr", return_value=False),
                patch("app.asr._run_with_asr_progress", side_effect=lambda **kwargs: kwargs["work"]()),
                patch("app.asr._transcribe_segments", side_effect=_fake_transcribe),
            ):
                result = run_discovery_asr(video_path, td, config)

        self.assertEqual(calls, [False])
        self.assertEqual(result.segments[0]["text"], "What happened?")

    def test_run_clip_subtitle_asr_requests_word_timestamps(self):
        from app.asr import DiscoveryASRResult, run_clip_subtitle_asr
        from app.config import AppConfig
        from app.highlight_detector import HighlightSegment

        config = AppConfig(language="en")
        segment = HighlightSegment(10.0, 20.0, 0.9)
        discovery = DiscoveryASRResult(language="en", model="medium.en", segments=[])

        with tempfile.TemporaryDirectory() as td:
            video_path = str(Path(td) / "video.mp4")
            Path(video_path).write_bytes(b"fake")

            class _Word:
                def __init__(self, word, start, end):
                    self.word = word
                    self.start = start
                    self.end = end

            class _SegmentObj:
                def __init__(self):
                    self.start = 0.0
                    self.end = 1.0
                    self.text = "What happened"
                    self.words = [_Word("What", 0.0, 0.4), _Word("happened", 0.4, 1.0)]

            calls = []

            def _fake_transcribe(_model, _audio, _lang, *, word_timestamps):
                calls.append(word_timestamps)
                return iter([_SegmentObj()]), type("Info", (), {"language": "en"})(), True

            with (
                patch("app.asr._extract_audio_for_asr", return_value=True),
                patch("app.asr._load_whisper_model", return_value=object()),
                patch("app.asr._transcribe_segments", side_effect=_fake_transcribe),
            ):
                words, session = run_clip_subtitle_asr(
                    video_path,
                    segment,
                    td,
                    config,
                    discovery_asr=discovery,
                    session=None,
                )

        self.assertEqual(calls, [True])
        self.assertEqual(session.model_size, "medium.en")
        self.assertEqual(words[0]["start"], 10.0)
        self.assertEqual(words[0]["word"], "What")


class TestCtaPolicy(unittest.TestCase):
    def test_cinema_disables_cta_effectively(self):
        from app.config import AppConfig
        from app.cta_pause import cta_disabled_reason, cta_effectively_enabled

        config = AppConfig()
        config.layout_mode = "cinema"

        self.assertFalse(cta_effectively_enabled(config))
        self.assertEqual(cta_disabled_reason(config), "cinema mode")

    def test_slot_only_keeps_cta_enabled(self):
        from app.config import AppConfig
        from app.cta_pause import cta_disabled_reason, cta_effectively_enabled

        config = AppConfig()
        config.layout_mode = "slot_only"

        self.assertTrue(cta_effectively_enabled(config))
        self.assertIsNone(cta_disabled_reason(config))


class TestRendererPolicy(unittest.TestCase):
    def test_build_filter_chain_skips_cta_in_cinema(self):
        from app.config import AppConfig
        from app.highlight_detector import HighlightSegment
        from app.layout import LayoutSpec
        from app.probe import VideoInfo
        from app.renderer import _build_filter_chain

        config = AppConfig()
        config.layout_mode = "cinema"
        segment = HighlightSegment(10.0, 40.0, 0.9)
        layout = LayoutSpec(
            has_webcam=False,
            mode="cinema",
            content_src=(0, 0, 1920, 1080),
            content_out=(0, 300, 1080, 1320),
            output_size=(1080, 1920),
        )
        video_info = VideoInfo("video.mp4", 60.0, 30.0, 1920, 1080, [])

        with (
            patch("app.renderer.build_composite_filter", return_value=("[0:v]null[composed]", "composed")),
            patch("app.renderer.build_cta_segment_filter") as cta_filter,
            patch("app.renderer.build_final_audio_mix", return_value="") as audio_mix,
        ):
            _build_filter_chain(
                video_path="video.mp4",
                video_info=video_info,
                segment=segment,
                layout=layout,
                config=config,
                ass_path=None,
                music_path=None,
                voice_path=None,
                clip_index=0,
                cta_text="FOLLOW",
                cta_start_sec=5.0,
                cta_freeze_duration_sec=4.0,
            )

        cta_filter.assert_not_called()
        self.assertEqual(audio_mix.call_args.kwargs["final_duration_sec"], 30.0)
        self.assertEqual(audio_mix.call_args.kwargs["cta_insert_duration_sec"], 0.0)

    def test_build_filter_chain_keeps_cta_for_slot_only(self):
        from app.config import AppConfig
        from app.highlight_detector import HighlightSegment
        from app.layout import LayoutSpec
        from app.probe import VideoInfo
        from app.renderer import _build_filter_chain

        config = AppConfig()
        config.layout_mode = "slot_only"
        segment = HighlightSegment(10.0, 40.0, 0.9)
        layout = LayoutSpec(
            has_webcam=False,
            mode="slot_only",
            content_src=(0, 0, 1920, 1080),
            content_out=(0, 0, 1080, 1920),
            output_size=(1080, 1920),
        )
        video_info = VideoInfo("video.mp4", 60.0, 30.0, 1920, 1080, [])

        with (
            patch("app.renderer.build_composite_filter", return_value=("[0:v]null[composed]", "composed")),
            patch("app.renderer.build_cta_segment_filter", return_value=("[composed]null[cta_out]", 5.0, 9.0)) as cta_filter,
            patch("app.renderer.build_final_audio_mix", return_value="") as audio_mix,
        ):
            _build_filter_chain(
                video_path="video.mp4",
                video_info=video_info,
                segment=segment,
                layout=layout,
                config=config,
                ass_path=None,
                music_path=None,
                voice_path=None,
                clip_index=0,
                cta_text="FOLLOW",
                cta_start_sec=5.0,
                cta_freeze_duration_sec=4.0,
            )

        cta_filter.assert_called_once()
        self.assertEqual(audio_mix.call_args.kwargs["final_duration_sec"], 34.0)
        self.assertEqual(audio_mix.call_args.kwargs["cta_insert_duration_sec"], 4.0)


class TestLayout(unittest.TestCase):
    def test_layout_no_webcam(self):
        from app.layout import compute_layout
        from app.webcam_types import WebcamDetectionResult
        from app.config import AppConfig

        config = AppConfig()
        result = WebcamDetectionResult(has_webcam=False)
        layout = compute_layout(1920, 1080, 1080, 1920, result, config)

        self.assertFalse(layout.has_webcam)
        self.assertIsNotNone(layout.content_src)
        self.assertIsNotNone(layout.content_out)
        self.assertLess(layout.subtitle_safe_y, 400)

    def test_layout_with_webcam(self):
        from app.layout import compute_layout
        from app.content_detector import ContentDetectionResult
        from app.webcam_types import WebcamDetectionResult, WebcamRegion
        from app.config import AppConfig

        config = AppConfig()
        region = WebcamRegion(x=10, y=10, w=320, h=240, confidence=0.8)
        result = WebcamDetectionResult(has_webcam=True, region=region, confidence=0.8)
        content = ContentDetectionResult(True, (400, 120, 1400, 800), 0.8, "test")
        layout = compute_layout(1920, 1080, 1080, 1920, result, config, content)

        self.assertTrue(layout.has_webcam)
        self.assertIsNotNone(layout.webcam_src)
        self.assertIsNotNone(layout.webcam_out)
        self.assertIsNotNone(layout.content_src)
        self.assertEqual(layout.content_src, (400, 120, 1400, 800))

    def test_layout_uses_detected_slot_crop(self):
        from app.layout import compute_layout
        from app.content_detector import ContentDetectionResult
        from app.webcam_types import WebcamDetectionResult, WebcamRegion
        from app.config import AppConfig

        config = AppConfig()
        region = WebcamRegion(x=0, y=464, w=480, h=270, confidence=0.9)
        result = WebcamDetectionResult(has_webcam=True, region=region, confidence=0.9)
        content = ContentDetectionResult(True, (506, 64, 1340, 908), 0.9, "trim_left_overlap")
        layout = compute_layout(1920, 1080, 1080, 1920, result, config, content)

        self.assertTrue(layout.has_webcam)
        self.assertEqual(layout.webcam_src[0], 0)
        self.assertEqual(layout.content_src, (506, 64, 1340, 908))

    def test_layout_slot_only_mode_uses_centered_no_webcam_compose(self):
        from app.layout import compute_layout
        from app.webcam_types import WebcamDetectionResult
        from app.config import AppConfig

        config = AppConfig()
        config.layout_mode = "slot_only"
        config.manual_slot_crop = [240, 160, 1240, 760]
        result = WebcamDetectionResult(has_webcam=True)
        layout = compute_layout(1920, 1080, 1080, 1920, result, config)

        self.assertFalse(layout.has_webcam)
        self.assertEqual(layout.mode, "slot_only")
        self.assertEqual(layout.content_src, (240, 160, 1240, 760))
        self.assertEqual(layout.content_out, (0, 0, 1080, 1920))

    def test_layout_cinema_mode_uses_zoomed_center_box(self):
        from app.layout import compute_layout
        from app.webcam_types import WebcamDetectionResult
        from app.config import AppConfig

        config = AppConfig()
        config.layout_mode = "cinema"
        result = WebcamDetectionResult(has_webcam=True)
        layout = compute_layout(1920, 1080, 1080, 1920, result, config)

        self.assertFalse(layout.has_webcam)
        self.assertEqual(layout.mode, "cinema")
        self.assertEqual(layout.output_size, (1080, 1920))
        self.assertLess(layout.content_src[2], 1920)
        self.assertGreaterEqual(layout.content_out[3], 1200)
        self.assertLessEqual(layout.content_out[2], 1080)

    def test_layout_cinema_mode_can_stack_optional_webcam(self):
        from app.layout import compute_layout
        from app.webcam_types import WebcamDetectionResult, WebcamRegion
        from app.config import AppConfig

        config = AppConfig()
        config.layout_mode = "cinema"
        config.manual_cinema_crop = [400, 120, 1120, 760]
        region = WebcamRegion(x=10, y=10, w=320, h=180, confidence=0.8)
        result = WebcamDetectionResult(has_webcam=True, region=region, confidence=0.8)

        layout = compute_layout(1920, 1080, 1080, 1920, result, config)

        self.assertTrue(layout.has_webcam)
        self.assertEqual(layout.mode, "cinema")
        self.assertIsNotNone(layout.webcam_src)
        self.assertEqual(layout.webcam_out[1], 0)
        self.assertGreater(layout.content_out[1], 0)
        self.assertEqual(layout.content_out[1], layout.webcam_out[3])


if __name__ == "__main__":
    unittest.main()
