from __future__ import annotations

from dataclasses import dataclass

from app.core.arabic import normalize_arabic, term_in_text, tokenize
from app.domain.kb import ComponentRecord
from app.knowledge.lexicon import ExpandedQuery, expand_query
from app.knowledge.loader import KnowledgeBase


@dataclass(frozen=True)
class RetrievalHit:
    record: ComponentRecord
    score: float
    reasons: tuple[str, ...]


class HybridRetriever:
    """
    Deterministic hybrid retrieval over the verified knowledge base.

    This is intentionally dependency-free for Milestone 1. It combines:
      * exact part-number matching,
      * Arabic dialect concept expansion (lexicon),
      * bilingual name / symptom / section matching,
      * equipment scoping.

    A vector-store adapter can be added behind the same `search` signature
    without changing the safety layer.
    """

    def __init__(self, kb: KnowledgeBase):
        self.kb = kb
        self._index: dict[str, dict[str, str]] = {}
        for part_number, record in kb.components.items():
            related_ar = " ".join(p.name_ar for p in record.related_parts)
            related_en = " ".join(p.name_en for p in record.related_parts)
            self._index[part_number] = {
                "ar": normalize_arabic(
                    " ".join(
                        [
                            record.arabic_name,
                            *record.symptoms_ar,
                            related_ar,
                            record.notes_ar or "",
                        ]
                    )
                ),
                "en": normalize_arabic(
                    " ".join(
                        [
                            record.english_name,
                            record.section_title,
                            *record.symptoms,
                            related_en,
                        ]
                    )
                ),
                "part": normalize_arabic(record.part_number),
            }

    def search(
        self,
        text: str,
        equipment_model: str | None = None,
        limit: int = 5,
    ) -> list[RetrievalHit]:
        if not text or not text.strip():
            return []

        expanded = expand_query(text)
        query_norm = normalize_arabic(text)
        query_tokens = [token for token in tokenize(text) if len(token) >= 3]

        hits: list[RetrievalHit] = []
        for part_number, record in self.kb.components.items():
            if equipment_model and equipment_model not in record.equipment_models:
                continue

            index = self._index[part_number]
            score = 0.0
            reasons: list[str] = []

            if index["part"] and (
                index["part"] in query_norm
                or index["part"].replace("-", "") in query_norm.replace("-", "")
            ):
                score += 100
                reasons.append("part_number_exact")

            name_ar_norm = normalize_arabic(record.arabic_name)
            name_en_norm = normalize_arabic(record.english_name)
            if name_ar_norm and (name_ar_norm in query_norm or query_norm in name_ar_norm):
                score += 14
                reasons.append("arabic_name")
            if name_en_norm and name_en_norm in query_norm:
                score += 14
                reasons.append("english_name")

            for concept in expanded.concepts:
                if concept.canonical_en and term_in_text(index["en"], concept.canonical_en):
                    score += 6
                    reasons.append(f"concept:{concept.key}")
                if concept.canonical_ar and term_in_text(index["ar"], concept.canonical_ar):
                    score += 6
                    reasons.append(f"concept_ar:{concept.key}")

            for token in query_tokens:
                if token in index["ar"] or token in index["en"]:
                    score += 2
                    reasons.append(f"token:{token}")

            if score > 0 and equipment_model:
                score += 1
                reasons.append("equipment_scope")

            if score > 0:
                hits.append(
                    RetrievalHit(
                        record=record,
                        score=score,
                        reasons=tuple(dict.fromkeys(reasons)),
                    )
                )

        hits.sort(key=lambda hit: (-hit.score, hit.record.part_number))
        return hits[:limit]

    def expand(self, text: str) -> ExpandedQuery:
        return expand_query(text)
