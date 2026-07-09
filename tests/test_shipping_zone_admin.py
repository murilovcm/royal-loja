"""Testes do CRUD admin de zonas de frete (POST /api/shipping_zone e afins).

Usa o Flask test client contra o royal.db real (mesmo padrão dos outros
testes de API deste projeto, que não tem infra de banco isolado para
testes). Por isso, todo teste que cria uma zona limpa depois de si mesmo
(try/finally) — nunca mexe nas zonas semeadas (Zona 1..5, Bolsão 1..4).
"""
import sqlite3

import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def admin_client(client):
    """Loga como o dono da loja (zonas de frete são owner-only). init_db()
    sempre garante que existe pelo menos uma conta com role='owner'."""
    token = "test-csrf-token"
    db = sqlite3.connect(app_module.DB_PATH)
    db.row_factory = sqlite3.Row
    owner = db.execute("SELECT id FROM users WHERE role = 'owner' LIMIT 1").fetchone()
    db.close()
    with client.session_transaction() as sess:
        sess["user_id"] = owner["id"]
        sess["csrf_token"] = token
    client.environ_base["HTTP_X_ADMIN_TOKEN"] = token
    return client


def test_create_zone_requires_login(client):
    resp = client.post("/api/shipping_zone", json={
        "zone_type": "concentric", "label": "Zona Teste", "lat": -2.5, "lng": -44.25, "radius_m": 1000, "price": 10,
    })
    assert resp.status_code == 401


def test_create_update_delete_concentric_zone(admin_client):
    resp = admin_client.post("/api/shipping_zone", json={
        "zone_type": "concentric", "label": "Zona Teste", "lat": -2.5, "lng": -44.25, "radius_m": 1000, "price": 10,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    zid = data["id"]

    try:
        special, concentric = app_module.get_shipping_zones()
        created = next(z for z in concentric if z["id"] == zid)
        assert created["label"] == "Zona Teste"
        assert created["price"] == 10

        resp = admin_client.post(f"/api/shipping_zone/{zid}", json={"price": 15})
        assert resp.status_code == 200
        _, concentric = app_module.get_shipping_zones()
        updated = next(z for z in concentric if z["id"] == zid)
        assert updated["price"] == 15

        # zona concêntrica não pode ficar sem preço
        resp = admin_client.post(f"/api/shipping_zone/{zid}", json={"price": ""})
        assert resp.status_code == 400
        assert resp.get_json()["ok"] is False
    finally:
        admin_client.delete(f"/api/shipping_zone/{zid}")

    _, concentric = app_module.get_shipping_zones()
    assert not any(z["id"] == zid for z in concentric)


def test_create_special_zone_without_price_is_allowed(admin_client):
    resp = admin_client.post("/api/shipping_zone", json={
        "zone_type": "special", "label": "Bolsão Teste", "lat": -2.6, "lng": -44.3, "radius_m": 500, "price": None,
    })
    assert resp.status_code == 200
    zid = resp.get_json()["id"]
    try:
        special, _ = app_module.get_shipping_zones()
        created = next(z for z in special if z["id"] == zid)
        assert created["price"] is None
    finally:
        admin_client.delete(f"/api/shipping_zone/{zid}")


def test_create_rejects_invalid_zone_type(admin_client):
    resp = admin_client.post("/api/shipping_zone", json={
        "zone_type": "bogus", "label": "X", "lat": -2.5, "lng": -44.25, "radius_m": 1000, "price": 10,
    })
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_create_rejects_missing_price_on_concentric(admin_client):
    resp = admin_client.post("/api/shipping_zone", json={
        "zone_type": "concentric", "label": "X", "lat": -2.5, "lng": -44.25, "radius_m": 1000,
    })
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_create_rejects_out_of_range_lat(admin_client):
    resp = admin_client.post("/api/shipping_zone", json={
        "zone_type": "concentric", "label": "X", "lat": 999, "lng": -44.25, "radius_m": 1000, "price": 10,
    })
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_create_rejects_negative_radius(admin_client):
    resp = admin_client.post("/api/shipping_zone", json={
        "zone_type": "concentric", "label": "X", "lat": -2.5, "lng": -44.25, "radius_m": -5, "price": 10,
    })
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_shipping_calc_reflects_admin_edits(admin_client):
    """Ponta a ponta: criar uma zona pelo admin e confirmar que o
    /api/shipping/calc (rota pública do checkout) já enxerga o novo valor
    na próxima chamada, sem precisar reiniciar nada."""
    lat, lng = -10.0, -50.0  # ponto isolado, não deve colidir com nenhuma zona real
    resp = admin_client.post("/api/shipping_zone", json={
        "zone_type": "concentric", "label": "Zona Isolada Teste", "lat": lat, "lng": lng, "radius_m": 100, "price": 33,
    })
    zid = resp.get_json()["id"]
    try:
        calc = admin_client.post("/api/shipping/calc", json={"lat": lat, "lng": lng})
        data = calc.get_json()
        assert data["ok"] is True
        assert data["zone_label"] == "Zona Isolada Teste"
        assert data["price"] == 33
    finally:
        admin_client.delete(f"/api/shipping_zone/{zid}")
