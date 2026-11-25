from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.core.config import get_settings
from app.deps import get_auth_store
from app.security.auth import (
    AUTH_COOKIE_NAME,
    AuthUser,
    ChangePasswordRequest,
    CreateUserRequest,
    LoginRequest,
    get_current_user,
    issue_access_token,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.post("/login")
def login(payload: LoginRequest, response: Response) -> dict:
    settings = get_settings()
    try:
        user = get_auth_store().authenticate(payload.email, payload.password)
    except PermissionError as exc:
        raise HTTPException(
            status_code=429,
            detail={"code": "account_locked", "message_ar": "تم تعليق محاولات الدخول مؤقتًا. حاول بعد 15 دقيقة."},
        ) from exc
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_credentials", "message_ar": "البريد الإلكتروني أو كلمة المرور غير صحيحة."},
        )
    if not settings.jwt_secret_key:
        raise HTTPException(status_code=503, detail="Authentication signing key is not configured")

    token = issue_access_token(user, settings.jwt_secret_key, settings.auth_token_ttl_minutes)
    secure_cookie = settings.environment.strip().lower() in {"production", "prod"}
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.auth_token_ttl_minutes * 60,
        httponly=True,
        secure=secure_cookie,
        samesite="strict",
        path="/",
    )
    return {"authenticated": True, "user": user.public_dict()}


@router.post("/logout")
def logout(response: Response) -> dict:
    settings = get_settings()
    secure_cookie = settings.environment.strip().lower() in {"production", "prod"}
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        httponly=True,
        secure=secure_cookie,
        samesite="strict",
        path="/",
    )
    return {"authenticated": False}


@router.get("/me")
def me(request: Request) -> dict:
    user = get_current_user(request, required=False)
    return {"authenticated": user is not None, "user": user.public_dict() if user else None}


@router.get("/users")
def list_users(request: Request) -> dict:
    actor = get_current_user(request)
    if actor is None or actor.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_role", "message_ar": "إدارة الحسابات تتطلب صلاحية المالك أو المدير."},
        )
    return {"users": [user.public_dict() for user in get_auth_store().list_users()]}


@router.post("/users", status_code=201)
def create_user(payload: CreateUserRequest, request: Request) -> dict:
    actor = get_current_user(request)
    if actor is None or actor.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_role", "message_ar": "إدارة الحسابات تتطلب صلاحية المالك أو المدير."},
        )
    if actor.role == "admin" and payload.role == "admin":
        raise HTTPException(
            status_code=403,
            detail={"code": "owner_role_required", "message_ar": "إنشاء مدير آخر يتطلب صلاحية المالك."},
        )
    try:
        user = get_auth_store().create_user(
            email=payload.email,
            display_name=payload.display_name,
            password=payload.password,
            role=payload.role,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "user_conflict", "message_ar": str(exc)},
        ) from exc
    return {"user": user.public_dict()}


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, request: Request) -> dict:
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "authentication_required", "message_ar": "سجّل الدخول أولاً."})
    if not get_auth_store().change_password(user, payload.current_password, payload.new_password):
        raise HTTPException(
            status_code=400,
            detail={"code": "current_password_invalid", "message_ar": "كلمة المرور الحالية غير صحيحة."},
        )
    return {"changed": True}
