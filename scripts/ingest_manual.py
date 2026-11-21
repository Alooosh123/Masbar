"""Build a local, page-cited text index from an authorized OEM PDF.

No source PDF is copied into Git. Generated indexes are local runtime data and are
ignored by the repository. Scanned pages are reported for a future OCR workflow.

Example:
  python scripts/ingest_manual.py --input .\\manuals\\grundfos-cr5.pdf \\
    --doc-id grundfos-cr-family-model-a --title "Service instructions CR 1, CR 3 and CR 5" \\
    --manufacturer Grundfos --equipment-model "Grundfos CR 5 Model A" \\
    --model-code "CR 5 Model A" --document-number "96546866 0407" \\
    --revision "2007-04" --source-url "https://www.grundfos.com/" \\
    --rights-confirmed --rights-note "Authorized internal project research copy" 

Add --apply to write the index. Without --apply, the command performs a dry run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.knowledge.manual_index import (  # noqa: E402
    ManualIndexError,
    build_manual_index,
    write_manual_index,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest an authorized industrial service manual PDF")
    parser.add_argument("--input", required=True, type=Path, help="Local source PDF")
    parser.add_argument("--doc-id", required=True, help="Stable id, e.g. grundfos-cr5-model-a")
    parser.add_argument("--title", required=True, help="Title exactly as printed in the document")
    parser.add_argument("--manufacturer", required=True, help="OEM/manufacturer name")
    parser.add_argument(
        "--equipment-model",
        action="append",
        required=True,
        help="Exact equipment model/family; repeat for multiple compatible models",
    )
    parser.add_argument("--model-code", action="append", default=[], help="Exact type key; repeat as needed")
    parser.add_argument("--document-number", default=None, help="OEM document number")
    parser.add_argument("--revision", default=None, help="Revision/date exactly as printed")
    parser.add_argument("--language", default="en")
    parser.add_argument("--source-url", default=None, help="Official source URL, when available")
    parser.add_argument(
        "--rights-confirmed",
        action="store_true",
        help="Confirm that you have the right to process this local manual copy",
    )
    parser.add_argument(
        "--rights-note",
        required=True,
        help="Permission/licence basis; do not leave this blank or use a guessed statement",
    )
    parser.add_argument("--max-chunk-chars", type=int, default=1800)
    parser.add_argument("--overlap-chars", type=int, default=180)
    parser.add_argument("--index-dir", type=Path, default=None)
    parser.add_argument("--apply", action="store_true", help="Write the index; default is dry-run")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing index after review")
    args = parser.parse_args()

    settings = get_settings()
    index_dir = args.index_dir or settings.manual_index_dir
    try:
        index = build_manual_index(
            args.input,
            doc_id=args.doc_id,
            title=args.title,
            manufacturer=args.manufacturer,
            equipment_models=args.equipment_model,
            model_codes=args.model_code,
            document_number=args.document_number,
            revision=args.revision,
            language=args.language,
            source_url=args.source_url,
            rights_confirmed=args.rights_confirmed,
            rights_note=args.rights_note,
            max_chunk_chars=args.max_chunk_chars,
            overlap_chars=args.overlap_chars,
        )
    except ManualIndexError as exc:
        print(f"[REFUSED] {exc}")
        return 2

    document = index.document
    print("[VALID] Manual metadata and text extraction passed.")
    print(f"  Document: {document.title}")
    print(f"  OEM: {document.manufacturer}")
    print(f"  Models: {', '.join(document.equipment_models)}")
    print(f"  Document number: {document.document_number or 'not supplied'}")
    print(f"  Revision: {document.revision or 'not supplied'}")
    print(f"  PDF pages: {document.page_count}")
    print(f"  Pages with extractable text: {document.text_pages}")
    print(f"  Pages requiring OCR: {document.pages_requiring_ocr}")
    print(f"  Chunks created: {len(index.chunks)}")
    print(f"  SHA-256: {document.sha256}")
    print(f"  Rights confirmed: {document.rights_confirmed}")
    print(f"  Local index directory: {index_dir}")

    if not args.apply:
        print("[DRY-RUN] Nothing was written. Add --apply after reviewing the metadata.")
        return 0

    try:
        target = write_manual_index(index, index_dir, overwrite=args.overwrite)
    except ManualIndexError as exc:
        print(f"[REFUSED] {exc}")
        return 2
    print(f"[WRITTEN] {target}")
    print("Restart the backend to load the new local manual index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
