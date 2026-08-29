import httpx
import pytest

from yongge_online.core.errors import ExternalServiceError
from yongge_online.tools.map_provider import AmapWebServiceProvider


@pytest.mark.asyncio
async def test_amap_provider_maps_nearby_pois_without_leaking_key() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["location"] = request.url.params["location"]
        captured["keywords"] = request.url.params["keywords"]
        captured["radius"] = request.url.params["radius"]
        assert request.url.params["key"] == "amap-secret"
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "pois": [
                    {
                        "name": "隔壁奶茶",
                        "type": "餐饮服务;冷饮店;冷饮店",
                        "distance": "320",
                        "address": "测试路 1 号",
                    }
                ],
            },
        )

    provider = AmapWebServiceProvider(
        api_key="amap-secret",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.nearby_competitors(
        longitude=114.4,
        latitude=30.5,
        category="奶茶",
        radius_m=1000,
    )

    assert result.available is True
    assert result.competitors[0].name == "隔壁奶茶"
    assert result.competitors[0].distance_m == 320
    assert captured == {
        "path": "/v3/place/around",
        "location": "114.400000,30.500000",
        "keywords": "奶茶",
        "radius": "1000",
    }


@pytest.mark.asyncio
async def test_amap_provider_normalizes_upstream_error() -> None:
    provider = AmapWebServiceProvider(
        api_key="amap-secret",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"status": "0", "info": "INVALID_USER_KEY"},
            )
        ),
    )

    with pytest.raises(ExternalServiceError) as error:
        await provider.nearby_competitors(
            longitude=114.4,
            latitude=30.5,
            category="奶茶",
            radius_m=1000,
        )

    assert "INVALID_USER_KEY" in error.value.message
    assert "amap-secret" not in error.value.message


