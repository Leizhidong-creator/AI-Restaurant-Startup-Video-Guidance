from typing import Protocol

import httpx

from yongge_online.core.errors import ExternalServiceError
from yongge_online.tools.schemas import Competitor, MapSearchResult


class MapProviderPort(Protocol):
    async def nearby_competitors(
        self,
        *,
        longitude: float,
        latitude: float,
        category: str,
        radius_m: int,
    ) -> MapSearchResult: ...


class UnavailableMapProvider:
    def __init__(self, reason: str):
        self.reason = reason

    async def nearby_competitors(
        self,
        *,
        longitude: float,
        latitude: float,
        category: str,
        radius_m: int,
    ) -> MapSearchResult:
        del longitude, latitude, category
        return MapSearchResult(
            available=False,
            reason=self.reason,
            radius_m=radius_m,
            competitors=[],
        )


class AmapWebServiceProvider:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def nearby_competitors(
        self,
        *,
        longitude: float,
        latitude: float,
        category: str,
        radius_m: int,
    ) -> MapSearchResult:
        try:
            async with httpx.AsyncClient(
                base_url="https://restapi.amap.com",
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.get(
                    "/v3/place/around",
                    params={
                        "key": self.api_key,
                        "location": f"{longitude:.6f},{latitude:.6f}",
                        "keywords": category,
                        "radius": radius_m,
                        "sortrule": "distance",
                        "offset": 25,
                        "page": 1,
                        "extensions": "all",
                    },
                )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "1":
                raise ExternalServiceError(
                    "Amap",
                    str(payload.get("info") or "unknown upstream error"),
                    retryable=False,
                )
            competitors = [self._competitor(item) for item in payload.get("pois", [])]
            return MapSearchResult(
                available=True,
                radius_m=radius_m,
                competitors=competitors,
            )
        except ExternalServiceError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise ExternalServiceError("Amap", str(exc)) from exc

    @staticmethod
    def _competitor(item: dict) -> Competitor:
        raw_address = item.get("address")
        address = ", ".join(raw_address) if isinstance(raw_address, list) else raw_address
        raw_distance = item.get("distance")
        try:
            distance = int(float(raw_distance)) if raw_distance not in (None, "") else None
        except (TypeError, ValueError):
            distance = None
        return Competitor(
            name=str(item.get("name") or "未命名门店"),
            category=item.get("type"),
            distance_m=distance,
            address=address,
        )


