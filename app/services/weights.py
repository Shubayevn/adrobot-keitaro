"""Пересчёт долей офферов в потоке.

Правила (как в видео):
- удалённый (removed) оффер получает 0%;
- запиненные активные офферы сохраняют свою долю;
- остаток 100 - сумма_запиненных делится поровну между незапиненными активными;
- доли целые; остаток от деления по +1 получают офферы с большей опубликованной долей,
  при равенстве — первые по порядку (75 на двоих -> 38/37, 100 на троих -> 34/33/33).
  Так пересчёт опубликованного 33/33/34 из Keitaro даёт те же 33/33/34, и поток
  не желтеет без настоящих изменений.
"""

from collections.abc import Sequence
from typing import Protocol

from app.models import ACTIVE

TOTAL = 100


class WeightError(ValueError):
    pass


class _Link(Protocol):
    status: str
    share: int
    pinned: bool
    published_share: int


def split_evenly(total: int, n: int) -> list[int]:
    if n <= 0:
        return []
    base, rem = divmod(total, n)
    return [base + 1 if i < rem else base for i in range(n)]


def pinned_sum(links: Sequence[_Link]) -> int:
    return sum(link.share for link in links if link.status == ACTIVE and link.pinned)


def recalculate(links: Sequence[_Link]) -> None:
    """Пересчитывает share на месте. links — в порядке отображения."""
    active = [link for link in links if link.status == ACTIVE]
    for link in links:
        if link.status != ACTIVE:
            link.share = 0
            link.pinned = False

    fixed = pinned_sum(active)
    if fixed > TOTAL:
        raise WeightError(f"Сумма запиненных долей {fixed}% больше 100%")

    free = [link for link in active if not link.pinned]
    # кому достанется +1 от остатка: сначала тем, у кого опубликованная доля больше
    order = sorted(range(len(free)), key=lambda i: (-getattr(free[i], "published_share", 0), i))
    for rank, share in zip(order, split_evenly(TOTAL - fixed, len(free)), strict=True):
        free[rank].share = share


def validate_for_publish(links: Sequence[_Link]) -> None:
    """Проверка перед отправкой в Keitaro."""
    active = [link for link in links if link.status == ACTIVE]
    if not active:
        raise WeightError("В потоке не осталось активных офферов — Keitaro будет некуда слать трафик")
    total = sum(link.share for link in active)
    if total != TOTAL:
        raise WeightError(f"Сумма долей {total}%, а должна быть 100% (проверьте запиненные доли)")
    if any(link.share < 0 for link in active):
        raise WeightError("Отрицательная доля")
