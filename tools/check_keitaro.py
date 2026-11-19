"""Проверка связи с Keitaro — только чтение, ничего не создаёт.

    uv run python -m tools.check_keitaro            # сводка
    uv run python -m tools.check_keitaro --campaign 12   # плюс потоки кампании как JSON

Показывает, доступен ли трекер с ключом из .env, сколько офферов/доменов/групп/источников,
и сверяет значения из .env (действие редиректа, имя фильтра страны) со справочниками трекера.
"""

import argparse
import json
import sys

from app.config import get_settings
from app.keitaro import KeitaroClient, KeitaroError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=int, help="показать потоки этой кампании (сырые данные Keitaro)")
    args = parser.parse_args()

    s = get_settings()
    kt = KeitaroClient(s)
    print(f"Keitaro: {s.keitaro_url}/admin_api/v1")
    try:
        offers = kt.list_offers()
        print(f"  офферов: {len(offers)}")
        print(f"  доменов: {len(kt.list_domains())}")
        print(f"  групп кампаний: {len(kt.list_groups('campaigns'))}")
        print(f"  источников: {len(kt.list_traffic_sources())}")
        print(f"  кампаний: {len(kt.list_campaigns())}")
    except KeitaroError as exc:
        print(f"ОШИБКА: {exc}")
        return 1

    for title, call, key, wanted in (
        ("действия потоков", kt.list_stream_actions, "key", [s.redirect_action_type, s.offers_stream_action_type]),
        ("фильтры потоков", kt.list_stream_filters, "value", [s.country_filter_name]),
    ):
        try:
            items = call() or []
            keys = {str(i.get(key)) for i in items if isinstance(i, dict)}
            for w in dict.fromkeys(wanted):
                mark = "OK " if w in keys else "НЕТ"
                print(f"  [{mark}] {title}: '{w}'")
            if any(w not in keys for w in wanted):
                print(f"        доступно: {sorted(keys)}")
        except KeitaroError as exc:
            print(f"  не удалось прочитать {title}: {exc}")

    if args.campaign:
        print(json.dumps(kt.list_streams(args.campaign), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
