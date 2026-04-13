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
        self.assertFalse(config.music.enabled)
        self.assertEqual(config.subtitles_position, "between_webcam_and_game")
        self.assertEqual(config.export.crf, 22)
        self.assertEqual(config.cta.freeze_duration_sec, 4.0)
        self.assertEqual(config.cta.typewriter_speed, 0.16)
        self.assertEqual(config.whisper_model_cache_dir, "models/whisper")
        self.assertEqual(config.webcam_edge_margin_ratio, 0.15)

    def test_load_example_config(self):
        from app.config import load_config, AppConfig
        root = Path(__file__).resolve().parent.parent
        j = root / "example_config.json"
        if j.exists():
            config = load_config(j)
            self.assertIsInstance(config, AppConfig)

    def test_subtitle_themes(self):
        from app.config import SUBTITLE_THEMES
        for name in ("red", "purple", "black", "yellow"):
            self.assertIn(name, SUBTITLE_THEMES)
            theme = SUBTITLE_THEMES[name]
            self.assertIn("primary_colour", theme)
            self.assertIn("font_size", theme)
            self.assertEqual(theme["font_size"], 44)


class TestHelpers(unittest.TestCase):
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
            [{"word": "Hello,", "start": 0.0, "end": 0.4}],
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
        self.assertNotIn("Hello,", content)

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
        from app.cta_pause import pick_cta_text
        from app.config import AppConfig

        config = AppConfig()
        config.variation.enabled = False
        config.cta.language = "ru"
        self.assertEqual(pick_cta_text(config), "ИГРА В ОПИСАНИИ")
        config.cta.language = "en"
        self.assertEqual(pick_cta_text(config), "THE GAME IN BIO")

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
        self.assertIn("22", args)
        self.assertIn("slow", args)

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

    def test_profile_content_candidates_cover_user_layouts(self):
        from app.content_detector import _content_candidates

        refs = [
            (1182, 664, (0, 288, 314, 176), "profile_left_webcam_slot"),
            (1181, 663, (965, 3, 213, 150), "profile_small_top_right_overlay"),
            (1177, 666, (782, 18, 381, 216), "profile_large_top_right_rail"),
            (1176, 660, (913, 196, 263, 160), "profile_mid_right_overlay"),
            (1181, 665, (817, 431, 361, 215), "profile_bottom_right_webcam_slot"),
        ]

        for frame_w, frame_h, webcam, reason_prefix in refs:
            candidates = _content_candidates(frame_w, frame_h, webcam)
            raw = next((crop for crop, reason in candidates if reason == reason_prefix), None)
            self.assertIsNotNone(raw, reason_prefix)

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


class TestDownloader(unittest.TestCase):
    def test_is_url(self):
        from app.downloader import is_url
        self.assertTrue(is_url("https://youtube.com/watch"))
        self.assertFalse(is_url("D:\\video.mp4"))


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
