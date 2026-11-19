"""Тонкий клиент Keitaro Admin API v1 (https://admin-api.docs.keitaro.io/).

Все запросы к трекеру собраны здесь, чтобы при расхождении с вашей версией Keitaro
правка была в одном месте.
"""

from functools import lru_cache
from typing import Any

import httpx

from app.config import Settings, get_settings


class KeitaroError(Exception):
    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class KeitaroClient:
    def __init__(self, settings: Settings | None = None, http: httpx.Client | None = None):
        self.settings = settings or get_settings()
        base = self.settings.keitaro_url.rstrip("/") + "/admin_api/v1"
        self._http = http or httpx.Client(timeout=self.settings.keitaro_timeout)
        self._base = base
        self._headers = {"Api-Key": self.settings.keitaro_api_key, "Accept": "application/json"}

    # --- транспорт ---
    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = self._base + path
        try:
            resp = self._http.request(method, url, headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            raise KeitaroError(f"Keitaro недоступен: {exc}") from exc
        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except ValueError:
                payload = resp.text
            message = payload.get("error") if isinstance(payload, dict) else None
            raise KeitaroError(
                f"Keitaro {method} {path} -> {resp.status_code}: {message or payload}",
                status_code=resp.status_code,
                payload=payload,
            )
        if not resp.content:
            return None
        return resp.json()

    # --- справочники ---
    def list_offers(self) -> list[dict]:
        return self._request("GET", "/offers")

    def list_domains(self) -> list[dict]:
        return self._request("GET", "/domains")

    def list_groups(self, type_: str = "campaigns") -> list[dict]:
        return self._request("GET", "/groups", params={"type": type_})

    def create_group(self, name: str, type_: str = "campaigns") -> dict:
        return self._request("POST", "/groups", json={"name": name, "type": type_})

    def list_traffic_sources(self) -> list[dict]:
        return self._request("GET", "/traffic_sources")

    def list_stream_filters(self) -> list[dict]:
        return self._request("GET", "/stream_filters")

    def list_stream_actions(self) -> list[dict]:
        return self._request("GET", "/streams_actions")

    # --- кампании ---
    def list_campaigns(self) -> list[dict]:
        return self._request("GET", "/campaigns")

    def get_campaign(self, campaign_id: int) -> dict:
        return self._request("GET", f"/campaigns/{campaign_id}")

    def create_campaign(self, data: dict) -> dict:
        return self._request("POST", "/campaigns", json=data)

    def delete_campaign(self, campaign_id: int) -> None:
        self._request("DELETE", f"/campaigns/{campaign_id}")

    # --- потоки ---
    def list_streams(self, campaign_id: int) -> list[dict]:
        return self._request("GET", f"/campaigns/{campaign_id}/streams")

    def get_stream(self, stream_id: int) -> dict:
        return self._request("GET", f"/streams/{stream_id}")

    def create_stream(self, data: dict) -> dict:
        return self._request("POST", "/streams", json=data)

    def update_stream(self, stream_id: int, data: dict) -> dict:
        return self._request("PUT", f"/streams/{stream_id}", json=data)


@lru_cache
def get_keitaro() -> KeitaroClient:
    return KeitaroClient()
