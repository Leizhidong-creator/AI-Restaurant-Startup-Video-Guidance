from decimal import Decimal

from fastapi.testclient import TestClient

from yongge_online.core.config import Settings
from yongge_online.main import create_app


def build_client(tmp_path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'profiles.db'}",
        upload_dir=tmp_path / "uploads",
    )
    return TestClient(create_app(settings))


def test_create_user_and_store_persists_financial_profile(tmp_path) -> None:
    with build_client(tmp_path) as client:
        user_response = client.post(
            "/api/v1/users",
            json={"display_name": "小勇", "experience_level": "novice"},
        )
        assert user_response.status_code == 201
        user_id = user_response.json()["id"]

        store_response = client.post(
            f"/api/v1/users/{user_id}/stores",
            json={
                "name": "小勇奶茶店",
                "brand": "自创品牌",
                "category": "奶茶",
                "stage": "operating",
                "address": "武汉市洪山区",
                "area_sqm": "45",
                "initial_investment": "260000",
                "monthly_revenue": "36000",
                "monthly_rent": "12000",
                "monthly_labor_cost": "11000",
                "monthly_other_fixed_cost": "3000",
                "ingredient_cost_rate": "0.35",
                "operating_days_per_month": 30,
            },
        )

        assert store_response.status_code == 201
        store = store_response.json()
        assert store["user_id"] == user_id
        assert Decimal(store["monthly_revenue"]) == Decimal("36000.00")
        assert Decimal(store["ingredient_cost_rate"]) == Decimal("0.3500")

        get_response = client.get(f"/api/v1/stores/{store['id']}")
        assert get_response.status_code == 200
        assert get_response.json()["name"] == "小勇奶茶店"


def test_store_rejects_negative_financial_values(tmp_path) -> None:
    with build_client(tmp_path) as client:
        user_id = client.post(
            "/api/v1/users",
            json={"display_name": "店主", "experience_level": "intermediate"},
        ).json()["id"]

        response = client.post(
            f"/api/v1/users/{user_id}/stores",
            json={
                "name": "错误门店",
                "category": "快餐",
                "stage": "operating",
                "monthly_revenue": "-1",
            },
        )

        assert response.status_code == 422


def test_store_creation_for_unknown_user_returns_not_found(tmp_path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/v1/users/missing-user/stores",
            json={"name": "无主门店", "category": "咖啡", "stage": "planning"},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


