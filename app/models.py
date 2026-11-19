"""Локальное состояние обёртки.

Keitaro хранит только то, что опубликовано. У нас для каждой привязки «поток — оффер»
лежат две версии: черновик (status/share/pinned) и опубликованная (published_*).
Поток «жёлтый» (не опубликован), если хотя бы у одной привязки черновик расходится
с опубликованным или привязка ещё ни разу не публиковалась (is_new).
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

ACTIVE = "active"
REMOVED = "removed"


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str | None] = mapped_column(String(255))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    streams: Mapped[list["Stream"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="Stream.position",
    )


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str | None] = mapped_column(String(32))
    schema: Mapped[str | None] = mapped_column(String(32))
    # Поток без офферов в Keitaro: показываем строкой, содержимое не разбираем
    has_offers: Mapped[bool] = mapped_column(Boolean, default=False)

    campaign: Mapped[Campaign] = relationship(back_populates="streams")
    offers: Mapped[list["StreamOffer"]] = relationship(
        back_populates="stream",
        cascade="all, delete-orphan",
        order_by="StreamOffer.id",
    )


class Offer(Base):
    """Справочник офферов Keitaro (имя для отображения)."""

    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(512))


class StreamOffer(Base):
    __tablename__ = "stream_offers"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id", name="uq_stream_offer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), index=True)

    # черновик
    status: Mapped[str] = mapped_column(String(16), default=ACTIVE)
    share: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    # то, что сейчас лежит в Keitaro
    is_new: Mapped[bool] = mapped_column(Boolean, default=True)
    published_status: Mapped[str] = mapped_column(String(16), default=REMOVED)
    published_share: Mapped[int] = mapped_column(Integer, default=0)
    published_pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    stream: Mapped[Stream] = relationship(back_populates="offers")
    offer: Mapped[Offer] = relationship(lazy="joined")

    @property
    def is_dirty(self) -> bool:
        return (
            self.is_new
            or self.status != self.published_status
            or (self.status == ACTIVE and self.share != self.published_share)
        )
