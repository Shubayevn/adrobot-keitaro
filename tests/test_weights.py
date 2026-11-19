from dataclasses import dataclass

import pytest

from app.services.weights import WeightError, recalculate, split_evenly, validate_for_publish


@dataclass
class L:
    status: str = "active"
    share: int = 0
    pinned: bool = False


def test_split_evenly_remainder_goes_to_first():
    assert split_evenly(100, 3) == [34, 33, 33]
    assert split_evenly(75, 2) == [38, 37]
    assert split_evenly(100, 4) == [25, 25, 25, 25]
    assert split_evenly(100, 0) == []


def test_removed_get_zero_and_rest_split():
    links = [L(), L(status="removed", share=33), L(), L()]
    recalculate(links)
    assert [x.share for x in links] == [34, 0, 33, 33]


def test_pinned_kept_others_recalculated():
    links = [L(share=25, pinned=True), L(), L()]
    recalculate(links)
    assert [x.share for x in links] == [25, 38, 37]


def test_removed_offer_loses_pin():
    links = [L(status="removed", share=25, pinned=True), L(), L()]
    recalculate(links)
    assert links[0].pinned is False
    assert [x.share for x in links] == [0, 50, 50]


def test_pinned_over_100_rejected():
    with pytest.raises(WeightError):
        recalculate([L(share=70, pinned=True), L(share=40, pinned=True)])


def test_validate_for_publish():
    validate_for_publish([L(share=60), L(share=40), L(status="removed")])
    with pytest.raises(WeightError):
        validate_for_publish([L(status="removed")])
    with pytest.raises(WeightError):  # всё запинено, но сумма не 100
        validate_for_publish([L(share=30, pinned=True), L(share=30, pinned=True)])
