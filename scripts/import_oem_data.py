"""Import OEM-verified maintenance data into the knowledge base.

The importer refuses to write anything unless the export explicitly states that
it came from an OEM manual and includes a document id, page number, and a
verification flag. This is the boundary between the public OEM registry and
safety-critical maintenance data.

Usage:
    python scripts/import_oem_data.py --input export.json
    python scripts/import_oem_data.py --input export.json --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain.kb import EquipmentFile  # noqa: E402
from pydantic import ValidationError  # noqa: E402


def _fail(message: str) -> None:
    print(f"[REFUSED] {message}")
    raise SystemExit(2)


def _require_source(payload: dict) -> tuple[str, int]:
    if payload.get("verified_from_manual") is not True:
        _fail("الحقل verified_from_manual يجب أن يكون true صراحةً.")
    document_id = str(payload.get("source_document_id") or "").strip()
    if not document_id:
        _fail("source_document_id مطلوب.")
    try:
        page = int(payload.get("source_page") or 0)
    except (TypeError, ValueError):
        page = 0
    if page < 1:
        _fail("source_page يجب أن يكون رقم صفحة صحيحًا (1 أو أكثر).")
    return document_id, page


def _prepare(payload: dict) -> dict:
    document_id, page = _require_source(payload)
    family = str(payload.get("equipment_family") or "").strip()
    manufacturer = str(payload.get("manufacturer") or "").strip()
    if not family or not manufacturer:
        _fail("equipment_family وmanufacturer مطلوبان.")

    components = payload.get("components")
    if not isinstance(components, list) or not components:
        _fail("components مطلوبة ويجب ألا تكون فارغة.")

    prepared = []
    for index, raw in enumerate(components, start=1):
        if not isinstance(raw, dict):
            _fail(f"القطعة رقم {index} ليست كائن JSON.")
        component = dict(raw)
        component.setdefault("manual_doc_id", document_id)
        component.setdefault("manual_page", page)
        component["verification_status"] = "verified"
        if component.get("manual_doc_id") != document_id:
            _fail(
                f"القطعة {component.get('part_number', index)} تحمل manual_doc_id "
                "مختلفًا عن المستند المصرح به."
            )
        if component.get("torque_nm") is None and any(
            step.get("requires_torque") for step in component.get("steps", [])
        ):
            _fail(
                f"القطعة {component.get('part_number', index)} تطلب عزمًا دون قيمة "
                "موثقة."
            )
        prepared.append(component)

    return {
        "schema_version": "1.0",
        "equipment_family": family,
        "manufacturer": manufacturer,
        "data_status": "verified",
        "disclaimer_ar": payload.get(
            "disclaimer_ar",
            "بيانات مستوردة من كتيب خدمة OEM معتمد. راجع رقم المستند والصفحة "
            "قبل الاستخدام الميداني.",
        ),
        "components": prepared,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import OEM-verified knowledge data")
    parser.add_argument("--input", required=True, type=Path, help="OEM export JSON")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Target file under data/kb (default: data/kb/<family>.json)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the file. Without this flag the import is a dry run.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        _fail(f"ملف الإدخال غير موجود: {args.input}")

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"JSON غير صالح: {exc}")

    prepared = _prepare(payload)
    try:
        equipment = EquipmentFile.model_validate(prepared)
    except ValidationError as exc:
        print("[INVALID] الملف لا يطابق مخطط قاعدة المعرفة:")
        print(exc)
        return 2

    output = args.output
    if output is None:
        slug = "".join(
            ch if ch.isalnum() or ch in "-_" else "_"
            for ch in equipment.equipment_family.lower().replace(" ", "_")
        )
        output = ROOT / "data" / "kb" / f"{slug}.json"

    print("[OK] التحقق نجح")
    print(f"  الشركة: {equipment.manufacturer}")
    print(f"  المعدة: {equipment.equipment_family}")
    print(f"  القطع: {len(equipment.components)}")
    print(f"  المستند: {payload['source_document_id']} صفحة {payload['source_page']}")
    print(f"  الحالة: {equipment.data_status}")
    print(f"  تاريخ التحقق: {payload.get('verified_at', date.today().isoformat())}")
    print(f"  الهدف: {output}")

    if not args.apply:
        print("[DRY-RUN] لم يُكتب أي ملف. أعد الأمر مع --apply للكتابة.")
        return 0

    if not output.parent.exists():
        _fail(f"مجلد الهدف غير موجود: {output.parent}")
    output.write_text(
        json.dumps(prepared, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[WRITTEN] {output}")
    print("أعد تشغيل الخادم لتحميل الملف الجديد.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
