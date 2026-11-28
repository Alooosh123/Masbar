from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.core.config import get_settings
from app.deps import get_auth_store
from app.security.auth import (
    AUTH_COOKIE_NAME,
    AuthUser,
    GoogleLoginRequest,
    ChangePasswordRequest,
    CreateCustomerRequest,
    CreateUserRequest,
    LoginRequest,
    SetCustomerActiveRequest,
    UpdateCustomerRequest,
    get_current_user,
    issue_access_token,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

def verify_google_id_token(token: str, client_id: str) -> dict:
    claims = google_id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
    if claims.get("aud") != client_id or claims.get("email_verified") is not True:
        raise ValueError("Google identity is not verified for this application")
    email = claims.get("email", "")
    if not isinstance(email, str) or not email:
        raise ValueError("Google identity has no email")
    return claims


@router.post("/google")
def google_login(payload: GoogleLoginRequest, response: Response) -> dict:
    settings = get_settings()
    client_id = settings.google_client_id
    credential = payload.credential
    if not client_id:
        raise HTTPException(status_code=503, detail={"code": "google_auth_unconfigured", "message_ar": "تسجيل Google غير مهيأ بعد."})
    if not isinstance(credential, str) or not credential:
        raise HTTPException(status_code=422, detail={"code": "google_credential_missing", "message_ar": "تعذر استلام إثبات تسجيل Google."})
    try:
        claims = verify_google_id_token(credential, client_id)
        user = get_auth_store().get_or_create_google_user(email=claims["email"], display_name=claims.get("name", ""))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "account_inactive", "message_ar": "الحساب معطل. تواصل مع مسؤول النظام."}) from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail={"code": "google_verification_failed", "message_ar": "فشل التحقق من حساب Google. حاول مرة أخرى."}) from exc
    if not settings.jwt_secret_key:
        raise HTTPException(status_code=503, detail={"code": "auth_signing_unconfigured", "message_ar": "خدمة المصادقة غير مهيأة."})
    token = issue_access_token(user, settings.jwt_secret_key, settings.auth_token_ttl_minutes)
    secure_cookie = settings.environment.strip().lower() in {"production", "prod"}
    response.set_cookie(key=AUTH_COOKIE_NAME, value=token, max_age=settings.auth_token_ttl_minutes * 60,
        httponly=True, secure=secure_cookie, samesite="lax", path="/")
    return {"authenticated": True, "user": user.public_dict()}



@router.post("/login")
def login(payload: LoginRequest, response: Response) -> dict:
    settings = get_settings()
    if settings.google_client_id:
        raise HTTPException(status_code=403, detail={"code": "google_login_required", "message_ar": "تسجيل الدخول عبر Google هو الطريقة المعتمدة لهذا التطبيق."})
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


@router.post("/users/customers", status_code=201)
def create_customer(payload: CreateCustomerRequest, request: Request) -> dict:
    actor = get_current_user(request)
    if actor is None or actor.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_role", "message_ar": "إنشاء حسابات العملاء يتطلب صلاحية المالك أو المدير."},
        )
    try:
        user, temporary_password = get_auth_store().create_customer_account(
            email=payload.email,
            display_name=payload.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "customer_conflict", "message_ar": str(exc)}) from exc
    return {
        "user": user.public_dict(),
        "temporary_password": temporary_password,
        "must_change_password": True,
    }


@router.get("/users/customers")
def list_customers(request: Request) -> dict:
    actor = get_current_user(request)
    if actor is None or actor.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_role", "message_ar": "إدارة العملاء تتطلب صلاحية المالك أو المدير."},
        )
    return {"customers": [user.public_dict() for user in get_auth_store().list_customers()]}


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
            must_change_password=payload.role == "customer",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "user_conflict", "message_ar": str(exc)},
        ) from exc
    return {"user": user.public_dict()}


@router.patch("/users/{user_id}")
def update_customer(user_id: str, payload: UpdateCustomerRequest, request: Request) -> dict:
    actor = get_current_user(request)
    if actor is None or actor.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_role", "message_ar": "تعديل العملاء يتطلب صلاحية المالك أو المدير."},
        )
    if "email" not in payload.model_fields_set and "display_name" not in payload.model_fields_set:
        raise HTTPException(
            status_code=422,
            detail={"code": "empty_update", "message_ar": "أدخل الاسم أو البريد الإلكتروني لتحديث الحساب."},
        )
    try:
        user = get_auth_store().update_customer(
            user_id,
            email=payload.email,
            display_name=payload.display_name,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "customer_not_found", "message_ar": "حساب العميل غير موجود."}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "customer_conflict", "message_ar": str(exc)}) from exc
    return {"user": user.public_dict()}


@router.post("/users/{user_id}/activation")
def set_customer_activation(user_id: str, payload: SetCustomerActiveRequest, request: Request) -> dict:
    actor = get_current_user(request)
    if actor is None or actor.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_role", "message_ar": "تغيير حالة العملاء يتطلب صلاحية المالك أو المدير."},
        )
    try:
        user = get_auth_store().set_customer_active(user_id, payload.is_active)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "customer_not_found", "message_ar": "حساب العميل غير موجود."}) from exc
    return {"user": user.public_dict()}


@router.post("/users/{user_id}/reset-password")
def reset_customer_password(user_id: str, request: Request) -> dict:
    actor = get_current_user(request)
    if actor is None or actor.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_role", "message_ar": "إعادة تعيين كلمات المرور تتطلب صلاحية المالك أو المدير."},
        )
    try:
        user, temporary_password = get_auth_store().reset_customer_password(user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "customer_not_found", "message_ar": "حساب العميل غير موجود."}) from exc
    return {
        "user": user.public_dict(),
        "temporary_password": temporary_password,
        "must_change_password": True,
    }


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, request: Request, response: Response) -> dict:
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "authentication_required", "message_ar": "سجّل الدخول أولاً."})
    store = get_auth_store()
    if not store.change_password(user, payload.current_password, payload.new_password):
        raise HTTPException(
            status_code=400,
            detail={"code": "current_password_invalid", "message_ar": "كلمة المرور الحالية غير صحيحة."},
        )
    updated_user = store.get_user(user.id)
    if updated_user is None:
        raise HTTPException(status_code=401, detail={"code": "account_unavailable", "message_ar": "تعذر تحديث جلسة الحساب."})
    settings = get_settings()
    if not settings.jwt_secret_key:
        raise HTTPException(status_code=503, detail="Authentication signing key is not configured")
    token = issue_access_token(updated_user, settings.jwt_secret_key, settings.auth_token_ttl_minutes)
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
    return {"changed": True, "user": updated_user.public_dict()}
