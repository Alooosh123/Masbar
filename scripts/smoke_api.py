"""End-to-end smoke test against a running backend.

Usage:
    python scripts/smoke_api.py
    python scripts/smoke_api.py --base-url http://192.168.1.10:8010

Exit code 0 means the full safety-gated flow works.
"""

from __future__ import annotations

import argparse
import sys

import httpx

EQUIPMENT = "Caterpillar C15 ACERT"
PART_NUMBER = "312-5620"


def step(title: str) -> None:
    print(f"\n=== {title} ===")


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8010")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    with httpx.Client(base_url=base, timeout=20.0) as client:
        step("1. Health")
        health = client.get("/health")
        health.raise_for_status()
        body = health.json()
        print(body)
        if body.get("status") != "online":
            fail("health status is not online")

        step("2. Create session")
        created = client.post(
            "/api/v1/sessions", json={"equipment_model": EQUIPMENT}
        )
        created.raise_for_status()
        session = created.json()
        session_id = session["session_id"]
        print(f"session={session_id} state={session['state']}")

        step("3. Identify part by number")
        identified = client.post(
            f"/api/v1/sessions/{session_id}/identify",
            json={"part_number": PART_NUMBER},
        )
        identified.raise_for_status()
        data = identified.json()
        print(
            f"part={data['identified_component']['part_number']} "
            f"state={data['state']}"
        )
        checklist = [item["id"] for item in data["safety_lockout"]["checklist"]]
        print(f"LOTO checklist={checklist}")
        if data["state"] != "AWAITING_LOTO":
            fail("expected AWAITING_LOTO after identification")

        step("4. Server must block steps before LOTO")
        blocked = client.post(
            f"/api/v1/sessions/{session_id}/step", json={"action": "next"}
        )
        print(f"status={blocked.status_code} body={blocked.json()}")
        if blocked.status_code != 409:
            fail("server did not block procedure before LOTO")

        step("5. Partial LOTO must be rejected")
        partial = client.post(
            f"/api/v1/sessions/{session_id}/loto",
            json={"confirmed_item_ids": checklist[:1]},
        )
        print(f"status={partial.status_code} body={partial.json()}")
        if partial.status_code != 409:
            fail("partial LOTO confirmation was accepted")

        step("6. Full LOTO confirmation")
        loto = client.post(
            f"/api/v1/sessions/{session_id}/loto",
            json={"confirmed_item_ids": checklist, "technician_note": "smoke test"},
        )
        loto.raise_for_status()
        ready = loto.json()
        print(f"state={ready['state']} message={ready['assistant_message_ar']}")
        if ready["state"] != "READY":
            fail("session did not become READY after full LOTO")

        step("7. Go to the torque step")
        torque_step = client.post(
            f"/api/v1/sessions/{session_id}/step",
            json={"action": "goto", "step_index": 4},
        )
        torque_step.raise_for_status()
        step_body = torque_step.json()
        torque = step_body["current_step"]["torque_spec"]
        print(f"torque={torque}")
        if torque is None or torque["value_nm"] != 45.0:
            fail("expected 45 N·m from the knowledge base")
        if torque["source_document_id"] != "SENR9834-08":
            fail("torque source document missing")

        step("8. Ask about torque in Arabic")
        answer = client.post(
            f"/api/v1/sessions/{session_id}/ask",
            json={"transcript": "كم العزم؟"},
        )
        answer.raise_for_status()
        reply = answer.json()
        print(f"intent={reply['last_intent']} message={reply['assistant_message_ar']}")
        if "45" not in reply["assistant_message_ar"]:
            fail("torque answer does not contain the verified value")

        step("9. Audit trail")
        audit = client.get(f"/api/v1/sessions/{session_id}/audit")
        audit.raise_for_status()
        events = [entry["event"] for entry in audit.json()["entries"]]
        print(events)
        for required in ("component_identified", "loto_confirmed", "step_viewed"):
            if required not in events:
                fail(f"audit is missing event: {required}")

        step("10. Unknown part number must be rejected")
        unknown = client.post(
            f"/api/v1/sessions/{session_id}/identify",
            json={"part_number": "000-0000"},
        )
        print(f"status={unknown.status_code} body={unknown.json()}")
        if unknown.status_code != 404:
            fail("unknown part number was not rejected")

    print("\n[PASS] Full safety-gated flow completed successfully.")


if __name__ == "__main__":
    main()
