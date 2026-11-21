from fastapi import APIRouter, HTTPException, Query

from app.deps import get_assistant, get_oem_registry
from app.domain.api_models import ComponentSummary, EquipmentSummary, ManufacturerSummary
from app.domain.oem import OemManufacturer

router = APIRouter(prefix="/api/v1", tags=["catalog"])


def _summary(manufacturer: OemManufacturer) -> ManufacturerSummary:
    categories: list[str] = []
    for model in manufacturer.model_families:
        if model.category_ar not in categories:
            categories.append(model.category_ar)
    return ManufacturerSummary(
        id=manufacturer.id,
        name_ar=manufacturer.name_ar,
        name_en=manufacturer.name_en,
        country_ar=manufacturer.country_ar,
        official_url=str(manufacturer.official_url),
        data_access=manufacturer.data_access,
        models_count=len(manufacturer.model_families),
        categories_ar=categories,
        notes_ar=manufacturer.notes_ar,
    )


@router.get("/equipment", response_model=list[EquipmentSummary])
def list_equipment() -> list[EquipmentSummary]:
    return get_assistant().list_equipment()


@router.get("/components", response_model=list[ComponentSummary])
def list_components(
    q: str | None = Query(default=None, description="نص البحث بالعربية أو الإنجليزية"),
    equipment: str | None = Query(default=None, description="اسم المعدة للتصفية"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ComponentSummary]:
    return get_assistant().search_components(q, equipment, limit)


@router.get("/manufacturers", response_model=list[ManufacturerSummary])
def list_manufacturers(
    q: str | None = Query(default=None, description="بحث باسم الشركة أو الموديل"),
) -> list[ManufacturerSummary]:
    registry = get_oem_registry()
    return [_summary(item) for item in registry.search(q or "")]


@router.get("/manufacturers/{manufacturer_id}", response_model=OemManufacturer)
def get_manufacturer(manufacturer_id: str) -> OemManufacturer:
    manufacturer = get_oem_registry().get(manufacturer_id)
    if manufacturer is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "manufacturer_not_found",
                "message_ar": "الشركة غير موجودة في سجل مصادر OEM.",
            },
        )
    return manufacturer
