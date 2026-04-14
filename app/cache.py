"""Persistent JSON cache helpers for expensive video analysis steps."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from app.config import AppConfig
from app.utils.helpers import ensure_dir, project_root


def cache_enabled(config: AppConfig, kind: str) -> bool:
    cache = getattr(config, "cache", None)
    if cache is None or not getattr(cache, "enabled", True):
        return False
    return bool(getattr(cache, kind, True))


def cache_path(
    config: AppConfig,
    kind: str,
    video_path: str | Path,
    extra: Optional[dict[str, Any]] = None,
) -> Path:
    cache_dir = _cache_dir(config) / kind
    ensure_dir(cache_dir)
    return cache_dir / f"{video_cache_key(video_path, extra)}.json"


def load_json_cache(
    config: AppConfig,
    kind: str,
    video_path: str | Path,
    extra: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not cache_enabled(config, kind):
        return None
    path = cache_path(config, kind, video_path, extra)
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def save_json_cache(
    config: AppConfig,
    kind: str,
    video_path: str | Path,
    payload: dict[str, Any],
    extra: Optional[dict[str, Any]] = None,
) -> Optional[Path]:
    if not cache_enabled(config, kind):
        return None
    path = cache_path(config, kind, video_path, extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
    return path


def video_cache_key(video_path: str | Path, extra: Optional[dict[str, Any]] = None) -> str:
    fingerprint = video_fingerprint(video_path)
    material = {"video": fingerprint, "extra": extra or {}}
    raw = json.dumps(material, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def video_fingerprint(video_path: str | Path) -> dict[str, Any]:
    p = Path(video_path)
    try:
        stat = p.stat()
        return {
            "path": str(p.resolve()),
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }
    except OSError:
        return {"path": str(p)}


def _cache_dir(config: AppConfig) -> Path:
    raw = getattr(getattr(config, "cache", None), "dir", "cache") or "cache"
    path = Path(raw)
    if not path.is_absolute():
        path = project_root() / path
    return path
