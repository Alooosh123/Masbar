"""Authenticated, read-only QA probes for the production MISBAR manual RAG API.

The script asks for credentials interactively, never stores them, and only
performs login plus GET/POST read operations (no manual import or data mutation).

Run from the repository root:
    python scripts/manual_quality_eval.py
    python scripts/manual_quality_eval.py --base-url https://your-frontend-domain

The default target is the current MISBAR production frontend.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://frontend-production-9dd137e1.up.railway.app"
DEFAULT_REPORT = Path("docs/test-results/manual-quality-latest.json")

EXPECTED_MANUALS = {
    "grundfos-cr-135-model-a": {
        "document_number": "96546866 0407",
        "manufacturer": "Grundfos",
        "model": "Grundfos CR 5 Model A",
        "page_count": 19,
    },
    "siemens-s7-1200-system-manual-v47": {
        "document_number": "A5E02486680-AQ",
        "manufacturer": "Siemens AG",
        "model": "Siemens S7-1200 Control Panel",
        "page_count": 1323,
    },
}

SEARCH_CASES = [
    {
        "name": "Grundfos Arabic query",
        "query": "مانع التسرب position 105",
        "model": "Grundfos CR 5 Model A",
        "doc_id": "grundfos-cr-135-model-a",
        "pdf_page": 9,
        "printed_page": 9,
    },
    {
        "name": "Grundfos English query",
        "query": "shaft seal position 105",
        "model": "Grundfos CR 5 Model A",
        "doc_id": "grundfos-cr-135-model-a",
        "pdf_page": 9,
        "printed_page": 9,
    },
    {
        "name": "Siemens Arabic query",
        "query": "مواصفات وحدة المعالجة المركزية CPU 1214C",
        "model": "Siemens S7-1200 Control Panel",
        "doc_id": "siemens-s7-1200-system-manual-v47",
        "pdf_page": 1132,
        "printed_page": None,
    },
    {
        "name": "Siemens English query",
        "query": "CPU 1214C technical specifications",
        "model": "Siemens S7-1200 Control Panel",
        "doc_id": "siemens-s7-1200-system-manual-v47",
        "pdf_page": 1132,
        "printed_page": None,
    },
]

CHAT_CASES = [
    {
        "name": "Arabic source-cited Grundfos answer",
        "message": "ابحث في الكتيبات عن مانع التسرب position 105",
        "document_number": "96546866 0407",
        "page": "9",
    },
    {
        "name": "English request with Siemens source citation",
        "message": "Search manuals for CPU 1214C technical specifications",
        "document_number": "A5E02486680-AQ",
        "page": "1132",
    },
]


class Evaluator:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.checks: list[dict[str, Any]] = []
        self.client = httpx.Client(base_url=self.base_url, timeout=60.0, follow_redirects=True)

    def check(self, name: str, ok: bool, detail: Any = None) -> None:
        entry = {"name": name, "ok": bool(ok), "detail": detail}
        self.checks.append(entry)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail is not None else ""))

    def request_json(self, method: str, path: str, **kwargs) -> tuple[int, dict[str, Any] | list]:
        response = self.client.request(method, path, **kwargs)
        try:
            payload = response.json()
        except ValueError:
            payload = {"non_json_response": response.text[:500]}
        if not isinstance(payload, (dict, list)):
            payload = {"response": payload}
        return response.status_code, payload

    def login(self, email: str, password: str) -> bool:
        status, body = self.request_json(
            "POST",
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        user = body.get("user", {}) if isinstance(body, dict) else {}
        ok = status == 200 and body.get("authenticated") is True
        self.check(
            "Authenticated production session",
            ok,
            {"http_status": status, "role": user.get("role"), "email": user.get("email")},
        )
        return ok

    def run(self) -> dict[str, Any]:
        started = datetime.now(timezone.utc).isoformat()
        manuals_status, manuals_payload = self.request_json("GET", "/api/v1/manuals")
        manuals = manuals_payload if isinstance(manuals_payload, list) else []
        by_id = {item.get("doc_id"): item for item in manuals if isinstance(item, dict)}

        self.check(
            "Both expected manuals are listed",
            manuals_status == 200 and set(EXPECTED_MANUALS).issubset(by_id),
            {"http_status": manuals_status, "manual_count": len(manuals), "doc_ids": sorted(by_id)},
        )

        for doc_id, expected in EXPECTED_MANUALS.items():
            actual = by_id.get(doc_id, {})
            metadata_ok = (
                actual.get("document_number") == expected["document_number"]
                and actual.get("manufacturer") == expected["manufacturer"]
                and expected["model"] in actual.get("equipment_models", [])
                and actual.get("page_count") == expected["page_count"]
            )
            self.check(
                f"Metadata and model scope: {doc_id}",
                metadata_ok,
                {
                    "document_number": actual.get("document_number"),
                    "manufacturer": actual.get("manufacturer"),
                    "equipment_models": actual.get("equipment_models"),
                    "page_count": actual.get("page_count"),
                },
            )

        search_results: dict[str, dict[str, Any]] = {}
        for case in SEARCH_CASES:
            status, body = self.request_json(
                "GET",
                "/api/v1/manuals/search",
                params={"q": case["query"], "equipment_model": case["model"], "limit": 5},
            )
            hits = body.get("hits", []) if isinstance(body, dict) else []
            first = hits[0] if hits else {}
            ok = (
                status == 200
                and body.get("retrieval_method") == "bm25_lexical"
                and body.get("vector_search_enabled") is False
                and first.get("document_id") == case["doc_id"]
                and first.get("pdf_page_number") == case["pdf_page"]
                and first.get("printed_page_number") == case["printed_page"]
            )
            detail = {
                "http_status": status,
                "query": case["query"],
                "requested_model": case["model"],
                "top_document": first.get("document_id"),
                "pdf_page": first.get("pdf_page_number"),
                "printed_page": first.get("printed_page_number"),
                "retrieval_method": body.get("retrieval_method") if isinstance(body, dict) else None,
            }
            self.check(case["name"], ok, detail)
            search_results[case["name"]] = detail

        # A query from one manual must not leak a result from the other model.
        isolation_cases = [
            ("Grundfos query excluded from Siemens", "shaft seal position 105", "Siemens S7-1200 Control Panel"),
            ("Siemens query excluded from Grundfos", "CPU 1214C technical specifications", "Grundfos CR 5 Model A"),
        ]
        for name, query, model in isolation_cases:
            status, body = self.request_json(
                "GET",
                "/api/v1/manuals/search",
                params={"q": query, "equipment_model": model, "limit": 5},
            )
            hits = body.get("hits", []) if isinstance(body, dict) else []
            self.check(name, status == 200 and hits == [], {"http_status": status, "hit_count": len(hits)})

        # No unrelated evidence should be returned for an invented identifier.
        status, body = self.request_json(
            "GET",
            "/api/v1/manuals/search",
            params={
                "q": "zzqvxx 999998877",
                "equipment_model": "Siemens S7-1200 Control Panel",
            },
        )
        unknown_hits = body.get("hits", []) if isinstance(body, dict) else []
        self.check(
            "Unknown identifiers return no evidence",
            status == 200 and unknown_hits == [],
            {"http_status": status, "hit_count": len(unknown_hits)},
        )

        chat_results: dict[str, dict[str, Any]] = {}
        for case in CHAT_CASES:
            status, body = self.request_json(
                "POST",
                "/api/v1/chat",
                json={"message": case["message"]},
            )
            message = body.get("message_ar", "") if isinstance(body, dict) else ""
            citation_ok = (
                status == 200
                and body.get("source") in {"general", "system"}
                and case["document_number"] in message
                and case["page"] in message
                and re.search(r"\[S[1-5]\]", message) is not None
            )
            detail = {
                "http_status": status,
                "source": body.get("source") if isinstance(body, dict) else None,
                "expected_document_present": case["document_number"] in message,
                "expected_page_present": case["page"] in message,
                "citation_marker_present": re.search(r"\[S[1-5]\]", message) is not None,
                "answer_excerpt": message[:700],
            }
            self.check(case["name"], citation_ok, detail)
            chat_results[case["name"]] = detail

        # Torque is a restricted operational request: it must return source
        # snippets only and must not be answered by the generative RAG path.
        status, body = self.request_json(
            "POST",
            "/api/v1/chat",
            json={"message": "ابحث في الكتيبات عن عزم شد shaft seal"},
        )
        safety_text = body.get("message_ar", "") if isinstance(body, dict) else ""
        safety_ok = (
            status == 200
            and body.get("source") == "system"
            and "المقتطف:" in safety_text
            and "لا تعتمد" in safety_text
        )
        self.check(
            "Torque request remains retrieval-only",
            safety_ok,
            {
                "http_status": status,
                "source": body.get("source") if isinstance(body, dict) else None,
                "snippet_present": "المقتطف:" in safety_text,
                "safety_warning_present": "لا تعتمد" in safety_text,
            },
        )

        return {
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "base_url": self.base_url,
            "retrieval_method": "bm25_lexical",
            "manual_count": len(manuals),
            "checks": self.checks,
            "summary": {
                "total": len(self.checks),
                "passed": sum(1 for item in self.checks if item["ok"]),
                "failed": sum(1 for item in self.checks if not item["ok"]),
            },
            "search_results": search_results,
            "chat_results": chat_results,
            "limitations": [
                "This checks evidence retrieval, metadata, source/page references, and server safety routing.",
                "It does not independently certify the engineering correctness of every generated sentence.",
                "Manual search is BM25 lexical retrieval, not vector/semantic search.",
                "A PDF page number is not presented as a printed page number unless that number was verified.",
            ],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="MISBAR bilingual manual quality evaluation")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    email = input("MISBAR account email: ").strip()
    password = getpass.getpass("MISBAR password (not saved): ")
    evaluator = Evaluator(args.base_url)

    try:
        if not evaluator.login(email, password):
            print("Authentication failed; no protected tests were run.")
            return 2
        report = evaluator.run()
    except httpx.HTTPError as exc:
        print(f"[ERROR] Production API request failed: {type(exc).__name__}: {exc}")
        return 2
    finally:
        evaluator.client.close()

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = report["summary"]
    print(
        f"\nSummary: {summary['passed']}/{summary['total']} passed, "
        f"{summary['failed']} failed."
    )
    print(f"Report: {args.report}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
