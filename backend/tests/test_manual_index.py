from datetime import datetime, timezone

import pytest

from app.knowledge.manual_index import (
    ManualChunk,
    ManualDocument,
    ManualIndex,
    ManualIndexError,
    ManualLibrary,
    _printed_page_number,
    _split_page,
    write_manual_index,
)


def _make_index(index_dir, doc_id="grundfos-cr5", model="Grundfos CR 5 Model A"):
    document = ManualDocument(
        doc_id=doc_id,
        title="Service instructions CR 1, CR 3 and CR 5",
        manufacturer="Grundfos",
        equipment_models=[model],
        model_codes=["CR 5 Model A"],
        document_number="96546866 0407",
        revision="2007-04",
        language="en",
        source_url="https://www.grundfos.com/",
        sha256="a" * 64,
        page_count=19,
        text_pages=1,
        pages_requiring_ocr=18,
        indexed_at=datetime.now(timezone.utc),
        rights_confirmed=True,
        rights_note="Authorized test fixture for automated tests",
    )
    chunks = [
        ManualChunk(
            chunk_id="1" * 64,
            doc_id=doc_id,
            pdf_page_number=4,
            printed_page_number=4,
            chunk_index=0,
            section_title="Tightening torques and lubricants",
            text=(
                "Tightening torques and lubricants. Shaft seal position 105 has a "
                "specified service torque. Check the exact model and revision."
            ),
        ),
        ManualChunk(
            chunk_id="2" * 64,
            doc_id=doc_id,
            pdf_page_number=9,
            printed_page_number=9,
            chunk_index=0,
            section_title="Replacement of shaft seal",
            text=(
                "Replacement of shaft seal. The shaft seal is identified as position "
                "105. Refer to the torque table and applicable model revision."
            ),
        ),
    ]
    return write_manual_index(ManualIndex(document=document, chunks=chunks), index_dir)


def test_manual_search_returns_page_and_document_citation(tmp_path):
    _make_index(tmp_path)
    library = ManualLibrary.load(tmp_path)

    hits = library.search("shaft seal replacement", limit=5)

    assert hits
    assert hits[0].document_id == "grundfos-cr5"
    assert hits[0].document_number == "96546866 0407"
    assert hits[0].pdf_page_number == 9
    assert hits[0].printed_page_number == 9
    assert hits[0].section_title == "Replacement of shaft seal"
    assert "position 105" in hits[0].excerpt


def test_manual_search_can_be_scoped_to_exact_equipment_model(tmp_path):
    _make_index(tmp_path)
    library = ManualLibrary.load(tmp_path)

    assert library.search("shaft seal", equipment_model="Grundfos CR 5 Model A")
    assert library.search("shaft seal", equipment_model="Caterpillar C15 ACERT") == []


def test_local_index_lists_manual_metadata_without_pdf_content(tmp_path):
    _make_index(tmp_path)
    library = ManualLibrary.load(tmp_path)

    documents = library.list_documents()

    assert len(documents) == 1
    assert documents[0].manufacturer == "Grundfos"
    assert documents[0].page_count == 19
    assert documents[0].pages_requiring_ocr == 18


def test_write_manual_index_refuses_overwrite_without_explicit_flag(tmp_path):
    _make_index(tmp_path)
    _make_index(tmp_path, doc_id="grundfos-cr5")
    with pytest.raises(ManualIndexError, match="already exists"):
        _make_index(tmp_path)


def test_printed_page_footer_is_detected():
    assert _printed_page_number("Some page text\n4 / 19\nGRUNDFOS") == 4
    assert _printed_page_number("Some page text without a page footer") is None


def test_long_page_is_split_with_overlap():
    text = "\n".join(f"Line {index}: service information." for index in range(120))
    chunks = _split_page(text, max_chars=360, overlap_chars=80)

    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 360 for chunk in chunks)
    assert set(chunks[0].splitlines()) & set(chunks[1].splitlines())


def test_pdf_ingestion_requires_rights_confirmation(tmp_path):
    fake_pdf = tmp_path / "manual.pdf"
    fake_pdf.write_bytes(b"not a real pdf")

    from app.knowledge.manual_index import build_manual_index

    with pytest.raises(ManualIndexError, match="Rights confirmation"):
        build_manual_index(
            fake_pdf,
            doc_id="test-manual",
            title="Test service manual",
            manufacturer="Example OEM",
            equipment_models=["Example Model"],
            rights_confirmed=False,
            rights_note="Permission not checked",
        )
