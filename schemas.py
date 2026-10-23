"""Pydantic request schemas and server-side validation rules."""
from __future__ import annotations

import re
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignupIn(RequestSchema):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    organization_name: str = Field(min_length=2, max_length=80)

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password cannot be blank")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("organization_name")
    @classmethod
    def clean_org_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Organization name must contain at least 2 characters")
        return value


class LoginIn(RequestSchema):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password cannot be blank")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class ProductCreate(RequestSchema):
    name: str = Field(min_length=1, max_length=120)
    sku: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    quantity_on_hand: int = Field(default=0, ge=0, le=2_000_000_000, strict=True)
    cost_price: float | None = Field(default=None, ge=0, le=1_000_000_000)
    selling_price: float | None = Field(default=None, ge=0, le=1_000_000_000)
    low_stock_threshold: int | None = Field(default=None, ge=0, le=2_000_000_000, strict=True)

    @field_validator("cost_price", "selling_price", mode="before")
    @classmethod
    def reject_boolean_prices(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("Price must be a number, not a boolean")
        return value

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Product name is required")
        return value

    @field_validator("sku")
    @classmethod
    def normalize_sku(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]*", value):
            raise ValueError("SKU may contain letters, numbers, dots, underscores, slashes and hyphens")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            return value or None
        return value


class ProductUpdate(RequestSchema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    quantity_on_hand: int | None = Field(default=None, ge=0, le=2_000_000_000, strict=True)
    cost_price: float | None = Field(default=None, ge=0, le=1_000_000_000)
    selling_price: float | None = Field(default=None, ge=0, le=1_000_000_000)
    low_stock_threshold: int | None = Field(default=None, ge=0, le=2_000_000_000, strict=True)

    @field_validator("cost_price", "selling_price", mode="before")
    @classmethod
    def reject_boolean_prices(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("Price must be a number, not a boolean")
        return value

    @field_validator("name")
    @classmethod
    def validate_optional_name(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Product name cannot be empty")
        return value

    @field_validator("sku")
    @classmethod
    def normalize_optional_sku(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip().upper()
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]*", value):
                raise ValueError("Enter a valid SKU")
        return value

    @field_validator("description")
    @classmethod
    def clean_optional_description(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        return value


class StockAdjustmentIn(RequestSchema):
    delta: int = Field(ge=-2_000_000_000, le=2_000_000_000, strict=True)
    note: str = Field(min_length=3, max_length=300)

    @field_validator("delta")
    @classmethod
    def reject_zero_delta(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Adjustment must change the quantity")
        return value

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Add a short reason for this adjustment")
        return value


class SettingsUpdate(RequestSchema):
    default_low_stock_threshold: int = Field(ge=0, le=2_000_000_000, strict=True)
