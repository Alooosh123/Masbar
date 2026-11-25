from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.core.config import get_settings
from app.security.auth import AuthStore, get_auth_store, get_current_user, issue_token

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class InitializeRequest(BaseModel):
    setup_token: str = Field(..., min_length=16, max_length=256)
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=12, max_length=256)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=256)


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=12, max_length=256)
    role: Literal["manager", "engineer", "technician", "viewer"]


def _require_owner(user: dict | None = Depends(get_current_user)):
    if user is None and not get_settings().auth_enabled:
        return None
    if user is None or user.get("role") != "owner":
        raise HTTPException(
            status_code=403,
            detail={"code": "owner_required", "message_ar": "هذه العملية متاحة لمالك النظام فقط."},
        )
    return user


def _token_result(user: dict, store: AuthStore) -> dict:
    settings = get_settings()
    return {
        "access_token": issue_token(user),
        "token_type": "bearer",
        "expires_in": settings.auth_token_ttl_hours * 3600,
        "user": store.public_user(user),
    }


@router.get("/status")
def auth_status(store: AuthStore = Depends(get_auth_store)) -> dict:
    initialized = store.count() > 0
    settings = get_settings()
    return {
        "auth_enabled": settings.auth_enabled,
        "initialized": initialized,
        "initial_setup_required": settings.auth_enabled and not initialized,
    }


@router.post("/initialize", status_code=status.HTTP_201_CREATED)
def initialize_owner(
    payload: InitializeRequest,
    store: AuthStore = Depends(get_auth_store),
) -> dict:
    settings = get_settings()
    if not settings.auth_enabled:
        raise HTTPException(status_code=409, detail="Authentication is disabled.")
    try:
        user = store.create_first_owner(
            email=str(payload.email),
            full_name=payload.full_name,
            password=payload.password,
            setup_token=payload.setup_token,
            expected_setup_token=settings.auth_setup_token,
        )
    except ValueError as exc:
        code = str(exc)
        status_code = {
            "already_initialized": 409,
            "invalid_setup_token": 403,
            "password_too_short": 422,
        }.get(code, 422)
        message = {
            "already_initialized": "تم إنشاء حساب المالك مسبقًا. استخدم تسجيل الدخول.",
            "invalid_setup_token": "رمز التهيئة غير صحيح.",
            "password_too_short": "يجب أن تتكون كلمة المرور من 12 حرفًا على الأقل.",
        }.get(code, "بيانات الحساب غير صالحة.")
        raise HTTPException(
            status_code=status_code,
            detail={"code": code, "message_ar": message},
        ) from exc
    return _token_result(user, store)


@router.post("/login")
def login(
    payload: LoginRequest,
    store: AuthStore = Depends(get_auth_store),
) -> dict:
    user = store.authenticate(str(payload.email), payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credentials", "message_ar": "البريد الإلكتروني أو كلمة المرور غير صحيحة."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _token_result(user, store)


@router.get("/me")
def me(user: dict | None = Depends(get_current_user)) -> dict:
    if user is None:
        return {"authenticated": False, "user": None}
    return {"authenticated": True, "user": user}


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    _: dict | None = Depends(_require_owner),
    store: AuthStore = Depends(get_auth_store),
) -> dict:
    try:
        user = store.create_user(
            email=str(payload.email),
            full_name=payload.full_name,
            password=payload.password,
            role=payload.role,
        )
    except ValueError as exc:
        code = str(exc)
        status_code = 409 if code == "email_already_exists" else 422
        raise HTTPException(
            status_code=status_code,
            detail={"code": code, "message_ar": "تعذر إنشاء الحساب. تحقق من البيانات."},
        ) from exc
    return {"user": user}
