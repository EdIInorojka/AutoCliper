"""Smoke tests for StreamCuter modules."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

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
        self.assertEqual(config.webcam_edge_margin_ratio, 0.15)
        self.assertIsNone(config.manual_webcam_crop)
        self.assertIsNone(config.manual_slot_crop)
        self.assertFalse(config.layout_preview_enabled)
        self.assertIsNone(config.layout_preview_time_sec)
        self.assertTrue(config.layout_preview_autofill)
        self.assertEqual(config.layout_debug_preview, "layout_debug_preview.jpg")
        self.assertEqual(config.layout_preview_save_path, "layout_selection.json")
        self.assertTrue(config.layout_annotation_dataset_enabled)
        self.assertEqual(config.layout_annotation_dataset_path, "layout_dataset/annotations.jsonl")
        self.assertTrue(config.cache.enabled)
        self.assertEqual(config.cache.dir, "cache")
        self.assertTrue(config.quick_preview.only)
        self.assertFalse(config.quick_preview.enabled)
        self.assertEqual(config.export.render_preset, "quality")
        self.assertTrue(config.render_resume_enabled)
        self.assertEqual(config.highlight_report_path, "highlight_report.json")
        self.assertEqual(
            config.variation.cta_text_variants,
            [
                "THE GAME IN BIO",
                "LINK IN BIO",
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
                "LINK IN BIO",
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
        self.assertIn("--no-music", args)

    def test_wizard_custom_cta_and_voice_args(self):
        from app.wizard import WizardOptions, _build_cli_args

        args = _build_cli_args(
            WizardOptions(
                input_path="video.mp4",
                language="ru",
                output_dir="out",
                clips=1,
                render_preset="balanced",
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
        self.assertIn("--preview-time", args)
        self.assertIn("--delete-input-after-success", args)

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

        config.export.render_preset = "nvenc_fast"
        nvenc_args = _video_encode_args(config)
        self.assertIn("h264_nvenc", nvenc_args)
        self.assertIn("-cq", nvenc_args)

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

    def test_highlight_report_writes_reasons(self):
        from app.highlight_detector import HighlightSegment, write_highlight_report
        from app.config import AppConfig
        from app.probe import VideoInfo

        with tempfile.TemporaryDirectory() as td:
            config = AppConfig(output_dir=td, clips_override=1)
            info = VideoInfo("video.mp4", 60, 30, 1280, 720, [])
            write_highlight_report(
                info,
                [HighlightSegment(1, 11, 0.75, ["audio_energy"], "scored")],
                config,
            )

            report = Path(td) / "highlight_report.json"
            self.assertTrue(report.exists())
            text = report.read_text(encoding="utf-8")
            self.assertIn("audio_energy", text)


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


if __name__ == "__main__":
    unittest.main()
