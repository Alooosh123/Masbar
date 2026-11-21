from __future__ import annotations

from app.adapters.vision.base import VisionResult
from app.core.arabic import normalize_arabic, term_in_text
from app.knowledge.loader import KnowledgeBase


class MockVisionAdapter:
    """
    Deterministic stand-in for the VLM + SAM-2 pipeline.

    It never invents a part number: it can only return a component that already
    exists in the knowledge base for the selected equipment. This keeps the demo
    useful while the real vision provider is being wired.
    """

    def __init__(self, kb: KnowledgeBase, confidence: float = 0.93):
        self.kb = kb
        self.confidence = confidence

    async def identify(
        self,
        image_base64: str | None,
        equipment_model: str,
        hint: str | None = None,
    ) -> VisionResult:
        components = self.kb.components_for(equipment_model)
        if not components:
            return VisionResult(
                part_number=None,
                confidence=0.0,
                provider="mock",
                error="no_components_for_equipment",
            )

        chosen = components[0]
        if hint:
            normalized_hint = normalize_arabic(hint)
            for component in components:
                if (
                    normalize_arabic(component.part_number) in normalized_hint
                    or term_in_text(hint, component.arabic_name)
                    or term_in_text(hint, component.english_name)
                ):
                    chosen = component
                    break

        # A plausible centered bounding box for the AR overlay demo.
        return VisionResult(
            part_number=chosen.part_number,
            confidence=self.confidence,
            bounding_box=(0.34, 0.30, 0.66, 0.58),
            label=chosen.arabic_name,
            provider="mock",
        )
