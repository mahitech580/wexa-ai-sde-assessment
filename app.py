"""StockFlow FastAPI application: auth, multi-tenant inventory, dashboard, and settings."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import or_, select, text, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import create_access_token, get_current_user, hash_password, verify_password
from db import BASE_DIR, Base, STOCKFLOW_API_MODE, get_db, init_db
from models import Organization, Product, User, utc_now
from schemas import LoginIn, ProductCreate, ProductUpdate, SettingsUpdate, SignupIn, StockAdjustmentIn

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if APP_ENV in {"production", "prod"} and "*" in CORS_ORIGINS:
    raise RuntimeError("Production CORS_ORIGINS must list explicit origins; wildcard CORS is not allowed.")

SUPABASE_API_ORIGIN = os.getenv(
    "SUPABASE_API_ORIGIN", "https://citireafvqtqkuxvmail.supabase.co"
).strip().rstrip("/")
if STOCKFLOW_API_MODE == "supabase":
    parsed_origin = urlsplit(SUPABASE_API_ORIGIN)
    if (
        parsed_origin.scheme != "https"
        or not parsed_origin.netloc
        or parsed_origin.path
        or parsed_origin.query
        or parsed_origin.fragment
        or parsed_origin.username
        or parsed_origin.password
    ):
        raise RuntimeError("SUPABASE_API_ORIGIN must be an HTTPS origin without a path or credentials.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Supabase mode serves the UI only; its authenticated API and persistent
    # tenant data live in the Supabase Edge Function/Postgres project.
    if STOCKFLOW_API_MODE == "fastapi":
        init_db()
    yield


app = FastAPI(
    title="StockFlow API",
    description="A lightweight, organization-isolated inventory management MVP.",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return useful validation errors without echoing sensitive submitted values."""
    safe_errors = [
        {"loc": error.get("loc", []), "msg": error.get("msg", "Invalid input"), "type": error.get("type", "value_error")}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": safe_errors})


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    # Do not accidentally serve a second, empty inventory backend when deployed
    # in Supabase mode. The frontend uses its explicit Supabase API URL instead.
    if STOCKFLOW_API_MODE == "supabase" and request.url.path.startswith("/api/"):
        if request.method == "GET" and request.url.path == "/api/health":
            response = JSONResponse(
                status_code=200,
                content={"status": "ok", "service": "stockflow", "api_mode": "supabase"},
            )
        else:
            response = JSONResponse(
                status_code=503,
                content={"detail": "This deployment uses the configured Supabase Edge Function for the API."},
            )
    else:
        response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    # FastAPI's Swagger UI uses inline initialization scripts and its own CDN assets.
    # Keep the strict policy on the app and API while allowing the built-in docs to work.
    if request.url.path != "/api/docs" and not request.url.path.startswith("/api/docs/"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://images.unsplash.com; "
            "connect-src 'self'"
            + (f" {SUPABASE_API_ORIGIN}" if STOCKFLOW_API_MODE == "supabase" else "")
            + "; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'none'",
        )
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(BASE_DIR / "index.html", media_type="text/html")


@app.get("/style.css", include_in_schema=False)
def stylesheet() -> FileResponse:
    return FileResponse(BASE_DIR / "style.css", media_type="text/css")


@app.get("/script.js", include_in_schema=False)
def javascript() -> FileResponse:
    return FileResponse(BASE_DIR / "script.js", media_type="application/javascript")


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "stockflow", "database": "ok"}


def _organization(db: Session, user: User) -> Organization:
    organization = db.get(Organization, user.organization_id)
    if organization is None:
        raise HTTPException(status_code=401, detail="Organization not found")
    return organization


def _effective_threshold(product: Product, organization: Organization) -> int:
    return product.low_stock_threshold if product.low_stock_threshold is not None else organization.default_low_stock_threshold


def _product_json(product: Product, organization: Organization) -> dict[str, Any]:
    threshold = _effective_threshold(product, organization)
    return {
        "id": product.id,
        "organization_id": product.organization_id,
        "name": product.name,
        "sku": product.sku,
        "description": product.description,
        "quantity_on_hand": product.quantity_on_hand,
        "cost_price": product.cost_price,
        "selling_price": product.selling_price,
        "low_stock_threshold": product.low_stock_threshold,
        "effective_low_stock_threshold": threshold,
        "is_low_stock": product.quantity_on_hand <= threshold,
        "created_at": product.created_at.isoformat() if product.created_at else None,
        "updated_at": product.updated_at.isoformat() if product.updated_at else None,
        "last_stock_note": product.last_stock_note,
    }


def _user_json(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "organization_id": user.organization_id,
        "organization_name": user.organization.name if user.organization else "StockFlow",
    }


def _product_by_org(db: Session, product_id: int, organization_id: int) -> Product:
    product = db.scalar(select(Product).where(Product.id == product_id, Product.organization_id == organization_id))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.post("/api/auth/signup", status_code=201)
def signup(payload: SignupIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    organization = Organization(name=payload.organization_name, default_low_stock_threshold=5)
    user = User(email=payload.email, password_hash=hash_password(payload.password), organization=organization)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
    db.refresh(user)
    return {"access_token": create_access_token(user), "token_type": "bearer", "user": _user_json(user)}


@app.post("/api/auth/login")
def login(payload: LoginIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    return {"access_token": create_access_token(user), "token_type": "bearer", "user": _user_json(user)}


@app.get("/api/me")
def me(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"user": _user_json(user)}


@app.get("/api/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    organization = _organization(db, user)
    products = list(db.scalars(
        select(Product).where(Product.organization_id == user.organization_id)
        .order_by(Product.updated_at.desc(), Product.name.asc())
    ).all())
    low_stock = [p for p in products if p.quantity_on_hand <= _effective_threshold(p, organization)]
    return {
        "total_products": len(products),
        "total_units": sum(p.quantity_on_hand for p in products),
        "low_stock_count": len(low_stock),
        "default_low_stock_threshold": organization.default_low_stock_threshold,
        "low_stock_items": [
            _product_json(p, organization)
            for p in sorted(low_stock, key=lambda p: (p.quantity_on_hand, p.name.lower()))[:8]
        ],
        "recent_products": [_product_json(p, organization) for p in products[:6]],
    }


@app.get("/api/products")
def list_products(
    q: str = Query(default="", max_length=120),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    organization = _organization(db, user)
    statement = select(Product).where(Product.organization_id == user.organization_id)
    term = q.strip()
    if term:
        escaped_term = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_term}%"
        statement = statement.where(or_(
            Product.name.ilike(pattern, escape="\\"),
            Product.sku.ilike(pattern, escape="\\"),
        ))
    products = db.scalars(statement.order_by(Product.updated_at.desc(), Product.name.asc())).all()
    return {"items": [_product_json(p, organization) for p in products], "count": len(products)}


@app.post("/api/products", status_code=201)
def create_product(payload: ProductCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    organization = _organization(db, user)
    product = Product(
        organization_id=user.organization_id,
        name=payload.name,
        sku=payload.sku,
        description=payload.description,
        quantity_on_hand=payload.quantity_on_hand,
        cost_price=payload.cost_price,
        selling_price=payload.selling_price,
        low_stock_threshold=payload.low_stock_threshold,
        last_updated_by=user.id,
    )
    db.add(product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This SKU is already used by your organization") from exc
    db.refresh(product)
    return {"item": _product_json(product, organization)}


@app.get("/api/products/{product_id}")
def get_product(product_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    organization = _organization(db, user)
    return {"item": _product_json(_product_by_org(db, product_id, user.organization_id), organization)}


@app.patch("/api/products/{product_id}")
def update_product(
    product_id: int,
    payload: ProductUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    organization = _organization(db, user)
    product = _product_by_org(db, product_id, user.organization_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    for required_key in ("name", "sku", "quantity_on_hand"):
        if required_key in changes and changes[required_key] is None:
            raise HTTPException(status_code=422, detail=f"{required_key} cannot be null")
    for key, value in changes.items():
        setattr(product, key, value)
    product.last_updated_by = user.id
    product.updated_at = utc_now()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This SKU is already used by your organization") from exc
    db.refresh(product)
    return {"item": _product_json(product, organization)}


@app.post("/api/products/{product_id}/adjust-stock")
def adjust_stock(
    product_id: int,
    payload: StockAdjustmentIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    organization = _organization(db, user)
    product = _product_by_org(db, product_id, user.organization_id)
    next_quantity = product.quantity_on_hand + payload.delta
    if next_quantity < 0:
        raise HTTPException(status_code=422, detail="Stock cannot be reduced below zero")
    if next_quantity > 2_000_000_000:
        raise HTTPException(status_code=422, detail="Resulting stock exceeds the supported limit")
    previous_quantity = product.quantity_on_hand
    result = db.execute(
        sa_update(Product)
        .where(Product.id == product.id, Product.organization_id == user.organization_id,
               Product.quantity_on_hand == previous_quantity)
        .values(quantity_on_hand=next_quantity, last_stock_note=payload.note,
                last_updated_by=user.id, updated_at=utc_now())
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Stock changed in another request. Refresh and try again.")
    db.commit()
    product = _product_by_org(db, product_id, user.organization_id)
    return {"item": _product_json(product, organization), "message": "Stock adjusted successfully"}


@app.delete("/api/products/{product_id}", status_code=204)
def delete_product(product_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    product = _product_by_org(db, product_id, user.organization_id)
    db.delete(product)
    db.commit()


@app.get("/api/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    organization = _organization(db, user)
    return {
        "organization_name": organization.name,
        "default_low_stock_threshold": organization.default_low_stock_threshold,
        "created_at": organization.created_at.isoformat() if organization.created_at else None,
    }


@app.patch("/api/settings")
def update_settings(payload: SettingsUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    organization = _organization(db, user)
    organization.default_low_stock_threshold = payload.default_low_stock_threshold
    db.commit()
    return {
        "organization_name": organization.name,
        "default_low_stock_threshold": organization.default_low_stock_threshold,
        "message": "Settings saved successfully",
    }
