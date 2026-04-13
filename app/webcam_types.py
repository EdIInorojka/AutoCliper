"""Webcam detection result types (no OpenCV import)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class WebcamRegion:
    x: int
    y: int
    w: int
    h: int
    confidence: float  # 0..1


@dataclass
class WebcamDetectionResult:
    has_webcam: bool
    region: Optional[WebcamRegion] = None
    confidence: float = 0.0
