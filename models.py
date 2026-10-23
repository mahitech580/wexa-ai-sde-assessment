"""SQLAlchemy entities for organizations, settings, users, and inventory."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    users: Mapped[list["User"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    products: Mapped[list["Product"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    settings: Mapped["OrganizationSettings | None"] = relationship(
        back_populates="organization", cascade="all, delete-orphan", uselist=False, single_parent=True
    )

    @property
    def default_low_stock_threshold(self) -> int:
        return self.settings.default_low_stock_threshold if self.settings is not None else 5

    @default_low_stock_threshold.setter
    def default_low_stock_threshold(self, value: int) -> None:
        if self.settings is None:
            self.settings = OrganizationSettings(default_low_stock_threshold=value)
        else:
            self.settings.default_low_stock_threshold = value
            self.settings.updated_at = utc_now()


class OrganizationSettings(Base):
    __tablename__ = "organization_settings"
    __table_args__ = (CheckConstraint("default_low_stock_threshold >= 0", name="ck_settings_threshold_nonnegative"),)

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    default_low_stock_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    organization: Mapped[Organization] = relationship(back_populates="settings")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_organization_id", "organization_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    organization: Mapped[Organization] = relationship(back_populates="users")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("organization_id", "sku", name="uq_product_org_sku"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_product_quantity_nonnegative"),
        CheckConstraint("cost_price IS NULL OR cost_price >= 0", name="ck_product_cost_nonnegative"),
        CheckConstraint("selling_price IS NULL OR selling_price >= 0", name="ck_product_selling_nonnegative"),
        CheckConstraint("low_stock_threshold IS NULL OR low_stock_threshold >= 0", name="ck_product_threshold_nonnegative"),
        Index("ix_products_organization_id", "organization_id"),
        Index("ix_products_organization_updated", "organization_id", "updated_at"),
        Index("ix_products_organization_name", "organization_id", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    selling_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_stock_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    last_updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_stock_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    organization: Mapped[Organization] = relationship(back_populates="products")
