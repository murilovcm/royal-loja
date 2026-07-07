"""Teste da rota pública POST /api/shipping/calc (usa o Flask test client,
sem precisar subir o servidor)."""
import pytest

import app as app_module
from shipping import CONCENTRIC_ZONES


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def test_calc_returns_price_for_zone_center(client):
    zona1 = next(z for z in CONCENTRIC_ZONES if z["label"] == "Zona 1")
    resp = client.post("/api/shipping/calc", json={"lat": zona1["lat"], "lng": zona1["lng"]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["zone_label"] == "Zona 1"
    assert data["price"] == 8


def test_calc_outside_all_zones(client):
    resp = client.post("/api/shipping/calc", json={"lat": -2.30, "lng": -44.50})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is False
    assert data["message"] == "Fora da área de entrega padrão. Frete calculado à parte."


def test_calc_rejects_invalid_coordinates(client):
    resp = client.post("/api/shipping/calc", json={"lat": "abc", "lng": -44.50})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_calc_rejects_out_of_range_coordinates(client):
    resp = client.post("/api/shipping/calc", json={"lat": 999, "lng": -44.50})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
