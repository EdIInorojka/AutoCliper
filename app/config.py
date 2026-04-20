"""Configuration model and loader (stdlib: dataclasses; YAML optional via PyYAML)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class ExportConfig:
    render_preset: str = "quality"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    codec: str = "libx264"
    bitrate: str = "8M"
    crf: Optional[int] = 22
    preset: str = "slow"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"


@dataclass
class CacheConfig:
    enabled: bool = True
    dir: str = "cache"
    asr: bool = True
    highlights: bool = True
    layout: bool = True


@dataclass
class CTAConfig:
    enabled: bool = True
    trigger_range_sec: List[float] = field(default_factory=lambda: [7.0, 10.0])
    freeze_duration_sec: float = 4.0
    grayscale_strength: float = 1.0
    text_mode: str = "file"  # file | custom | variants
    text: str = "THE GAME IN BIO"
    text_en: str = "THE GAME IN BIO"
    text_ru: str = "ИГРА В ОПИСАНИИ"
    custom_text: Optional[str] = None
    text_file_path: str = ""
    text_file_path_en: str = "cta_texts/en.txt"
    text_file_path_ru: str = "cta_texts/ru.txt"
    language: str = "auto"
    font_name: str = "Impact"
    font_path: str = "fonts/cta.ttf"
    font_size: int = 78
    min_font_size: int = 34
    max_text_width_ratio: float = 0.86
    max_text_lines: int = 3
    font_color: str = "0xFFD200"
    border_color: str = "black"
    shadow_color: str = "red@0.85"
    typewriter_enabled: bool = True
    typewriter_speed: float = 0.16
    voice_mp3_path: Optional[str] = None


@dataclass
class MusicConfig:
    enabled: bool = False
    folder: str = "sounds/music"
    volume_min: float = 0.10
    volume_max: float = 0.20
    duck_under_speech: bool = True


@dataclass
class CinemaMusicConfig:
    enabled: bool = True
    folder: str = "musiccinema"
    volume: float = 0.05
    ending_enabled: bool = True
    ending_duration_sec: float = 4.5
    ending_volume: float = 0.60


@dataclass
class VariationConfig:
    enabled: bool = True
    intro_trim_randomization: float = 1.5
    clip_duration_variation: bool = True
    clip_duration_step_min_sec: float = 2.0
    clip_duration_step_max_sec: float = 4.0
    clip_duration_max_same_sec: int = 2
    cta_time_randomization: bool = True
    slight_zoom_variants: float = 0.05
    subtitle_style_variants: bool = True
    bgm_random_pick: bool = True
    cta_text_variants: List[str] = field(
        default_factory=lambda: [
            "THE GAME IN BIO",
            "BIO FOR MORE",
            "CHECK BIO",
            "MORE IN BIO",
        ]
    )
    cta_text_variants_ru: List[str] = field(
        default_factory=lambda: [
            "ИГРА В ОПИСАНИИ",
            "ССЫЛКА В ОПИСАНИИ",
        ]
    )


@dataclass
class BotPresetFields:
    available_themes: List[str] = field(
        default_factory=lambda: ["red", "purple", "black", "yellow"]
    )
    available_cta_texts: List[str] = field(
        default_factory=lambda: [
            "THE GAME IN BIO",
            "BIO FOR MORE",
            "CHECK BIO",
            "MORE IN BIO",
        ]
    )
    available_cta_texts_ru: List[str] = field(
        default_factory=lambda: [
            "ИГРА В ОПИСАНИИ",
            "ССЫЛКА В ОПИСАНИИ",
        ]
    )
    available_languages: List[str] = field(
        default_factory=lambda: ["auto", "ru", "en"]
    )


@dataclass
class AppConfig:
    input: str = ""
    input_start_sec: Optional[float] = None
    input_end_sec: Optional[float] = None
    output_dir: str = "output"
    temp_dir: str = "temp"
    language: str = "auto"
    subtitles_enabled: bool = True
    subtitles_mode: str = "word_by_word"
    subtitles_position: str = "between_webcam_and_game"
    subtitles_theme: str = "red"
    subtitles_max_words_per_group: int = 1
    subtitles_font_name: str = "Arial Black"
    subtitles_font_path: str = "fonts/subtitles.ttf"
    subtitles_template_ru: str = "subtitles/ru.ass"
    subtitles_template_en: str = "subtitles/en.ass"
    subtitles_between_y_ratio: float = 0.42
    whisper_model_cache_dir: str = "models/whisper"
    layout_mode: str = "auto"
    webcam_detection: str = "auto"
    webcam_edge_margin_ratio: float = 0.15
    manual_webcam_crop: Optional[List[int]] = None
    manual_slot_crop: Optional[List[int]] = None
    manual_cinema_crop: Optional[List[int]] = None
    layout_preview_enabled: bool = False
    layout_preview_time_sec: Optional[float] = None
    layout_preview_autofill: bool = True
    layout_debug_preview: str = "layout_debug_preview.jpg"
    layout_preview_save_path: str = "layout_selection.json"
    layout_annotation_dataset_enabled: bool = True
    layout_annotation_dataset_path: str = "layout_dataset/annotations.jsonl"
    webcam_top_ratio: float = 0.33
    content_bottom_ratio: float = 0.67
    highlight_target_count_per_hour: int = 15
    min_clip_duration_sec: int = 20
    preferred_clip_duration_sec: int = 45
    max_clip_duration_sec: int = 60
    hard_max_clip_duration_sec: int = 75
    cta: CTAConfig = field(default_factory=CTAConfig)
    music: MusicConfig = field(default_factory=MusicConfig)
    cinema_music: CinemaMusicConfig = field(default_factory=CinemaMusicConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    cleanup_temp_files: bool = True
    delete_input_after_success: bool = False
    render_resume_enabled: bool = True
    highlight_report_path: str = "highlight_report.json"
    export: ExportConfig = field(default_factory=ExportConfig)
    variation: VariationConfig = field(default_factory=VariationConfig)
    bot_preset_fields: BotPresetFields = field(default_factory=BotPresetFields)
    debug: bool = False
    clips_override: Optional[int] = None


def _merge_dataclass(dc_type: type, raw: Any):
    base = dc_type()
    if raw is None:
        return base
    if isinstance(raw, dc_type):
        return raw
    if not isinstance(raw, dict):
        return base
    allowed = {f.name for f in fields(dc_type)}
    kwargs = {k: v for k, v in raw.items() if k in allowed}
    return replace(base, **kwargs)


def app_config_from_dict(data: Optional[dict]) -> AppConfig:
    """Build AppConfig from a nested mapping (e.g. YAML/JSON)."""
    data = dict(data or {})
    nested = {
        "cta": _merge_dataclass(CTAConfig, data.pop("cta", None)),
        "music": _merge_dataclass(MusicConfig, data.pop("music", None)),
        "cinema_music": _merge_dataclass(
            CinemaMusicConfig, data.pop("cinema_music", None)
        ),
        "cache": _merge_dataclass(CacheConfig, data.pop("cache", None)),
        "export": _merge_dataclass(ExportConfig, data.pop("export", None)),
        "variation": _merge_dataclass(VariationConfig, data.pop("variation", None)),
        "bot_preset_fields": _merge_dataclass(
            BotPresetFields, data.pop("bot_preset_fields", None)
        ),
    }
    data.pop("quick_preview", None)
    base = AppConfig()
    allowed = {f.name for f in fields(AppConfig)}
    flat = {k: v for k, v in data.items() if k in allowed}
    return replace(replace(base, **nested), **flat)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_mapping_file(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "Reading .yaml/.yml requires PyYAML. Install it (pip install pyyaml) "
                "or use example_config.json / --config path\\to\\file.json"
            ) from e
        with open(path, "r", encoding="utf-8-sig") as f:
            return yaml.safe_load(f) or {}
    if suffix == ".json":
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    # Unknown extension: try JSON first, then YAML
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                f"Could not parse {path} as JSON and PyYAML is not installed."
            ) from e
        with open(path, "r", encoding="utf-8-sig") as f:
            return yaml.safe_load(f) or {}


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load config from file, or example_config.yaml / example_config.json in project root."""
    root = _project_root()
    data: dict = {}

    if path is not None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        data = _read_mapping_file(p)
    else:
        y = root / "example_config.yaml"
        j = root / "example_config.json"
        if y.exists():
            try:
                data = _read_mapping_file(y)
            except RuntimeError:
                data = {}
        if not data and j.exists():
            data = _read_mapping_file(j)

    return app_config_from_dict(data)


SUBTITLE_THEMES = {
    "red": {
        "primary_colour": "&H00FFFFFF",
        "secondary_colour": "&H00FFFFFF",
        "outline_colour": "&H000000FF",
        "back_colour": "&H00000080",
        "font_name": "Arial",
        "font_size": 44,
        "bold": 1,
        "italic": 0,
        "underline": 0,
        "strike_out": 0,
        "scale_x": 100,
        "scale_y": 100,
        "spacing": 1,
        "angle": 0,
        "border_style": 1,
        "outline": 3,
        "shadow": 2,
        "alignment": 2,
        "margin_l": 40,
        "margin_r": 40,
        "margin_v": 80,
    },
    "purple": {
        "primary_colour": "&H00FFFFFF",
        "secondary_colour": "&H00FFFFFF",
        "outline_colour": "&H008000FF",
        "back_colour": "&H00200060",
        "font_name": "Arial",
        "font_size": 44,
        "bold": 1,
        "italic": 0,
        "underline": 0,
        "strike_out": 0,
        "scale_x": 100,
        "scale_y": 100,
        "spacing": 1,
        "angle": 0,
        "border_style": 1,
        "outline": 3,
        "shadow": 2,
        "alignment": 2,
        "margin_l": 40,
        "margin_r": 40,
        "margin_v": 80,
    },
    "black": {
        "primary_colour": "&H00FFFFFF",
        "secondary_colour": "&H00FFFFFF",
        "outline_colour": "&H00000000",
        "back_colour": "&H000000CC",
        "font_name": "Arial",
        "font_size": 44,
        "bold": 1,
        "italic": 0,
        "underline": 0,
        "strike_out": 0,
        "scale_x": 100,
        "scale_y": 100,
        "spacing": 1,
        "angle": 0,
        "border_style": 1,
        "outline": 2,
        "shadow": 3,
        "alignment": 2,
        "margin_l": 40,
        "margin_r": 40,
        "margin_v": 80,
    },
    "yellow": {
        "primary_colour": "&H00FFFF00",
        "secondary_colour": "&H00FFFF00",
        "outline_colour": "&H00000000",
        "back_colour": "&H000000AA",
        "font_name": "Arial",
        "font_size": 44,
        "bold": 1,
        "italic": 0,
        "underline": 0,
        "strike_out": 0,
        "scale_x": 100,
        "scale_y": 100,
        "spacing": 1,
        "angle": 0,
        "border_style": 1,
        "outline": 3,
        "shadow": 2,
        "alignment": 2,
        "margin_l": 40,
        "margin_r": 40,
        "margin_v": 80,
    },
}

