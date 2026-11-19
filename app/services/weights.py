"""Пересчёт долей офферов в потоке.

Правила (как в видео):
- удалённый (removed) оффер получает 0%;
- запиненные активные офферы сохраняют свою долю;
- остаток 100 - сумма_запиненных делится поровну между незапиненными активными;
- доли целые, остаток от деления по +1 получают первые по порядку (75 на двоих -> 38/37,
  100 на троих -> 34/33/33).
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
    for link, share in zip(free, split_evenly(TOTAL - fixed, len(free)), strict=True):
        link.share = share


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
