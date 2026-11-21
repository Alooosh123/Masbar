from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VisionResult:
    part_number: str | None
    confidence: float
    bounding_box: tuple[float, float, float, float] | None = None
    label: str | None = None
    provider: str = "mock"
    error: str | None = None


def clamp_box(box: list[float] | tuple[float, ...] | None) -> tuple[float, float, float, float] | None:
    if not box or len(box) != 4:
        return None
    x1, y1, x2, y2 = (min(1.0, max(0.0, float(v))) for v in box)
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)
