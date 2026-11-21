from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class OemModelFamily(BaseModel):
    model: str = Field(..., min_length=1)
    category_ar: str = Field(..., min_length=2)
    category_en: str = Field(..., min_length=2)


class OemManufacturer(BaseModel):
    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]*$")
    name_ar: str = Field(..., min_length=2)
    name_en: str = Field(..., min_length=2)
    country_ar: str = Field(..., min_length=2)
    official_url: HttpUrl
    service_url: HttpUrl | None = None
    parts_url: HttpUrl | None = None
    data_access: Literal[
        "public_catalog",
        "dealer_portal",
        "subscription",
        "manual_required",
    ] = "manual_required"
    verification_status: Literal["official_domain_reference"] = (
        "official_domain_reference"
    )
    verified_at: str
    notes_ar: str = ""
    model_families: list[OemModelFamily] = Field(..., min_length=1)


class OemRegistryFile(BaseModel):
    schema_version: str = "1.0"
    compiled_at: str
    disclaimer_ar: str
    manufacturers: list[OemManufacturer] = Field(..., min_length=1)
