"""Testes dos cupons restritos a produtos (modelos) específicos.

Cobre a criação via painel (POST /api/coupon com model_ids) e a rota pública
/api/coupon/apply, que passou a receber os itens do carrinho para calcular o
subtotal elegível e devolver os sabores permitidos (product_ids).

Segue o mesmo padrão dos outros testes de API do projeto: Flask test client
contra o royal.db real, cada teste limpando o que cria (try/finally).
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


@pytest.fixture
def catalog():
    """Cria uma marca com dois modelos e sabores, para restringir cupons.
    Retorna ids úteis e remove tudo ao final (CASCADE limpa produtos)."""
    db = sqlite3.connect(app_module.DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    brand_id = db.execute("INSERT INTO brands (name) VALUES ('MarcaTesteCupom')").lastrowid
    model_a = db.execute(
        "INSERT INTO vape_models (brand_id, name) VALUES (?, 'ModeloA')", (brand_id,)
    ).lastrowid
    model_b = db.execute(
        "INSERT INTO vape_models (brand_id, name) VALUES (?, 'ModeloB')", (brand_id,)
    ).lastrowid
    fa1 = db.execute(
        "INSERT INTO products (model_id, name, price) VALUES (?, 'A-Uva', 100)", (model_a,)
    ).lastrowid
    fa2 = db.execute(
        "INSERT INTO products (model_id, name, price) VALUES (?, 'A-Menta', 100)", (model_a,)
    ).lastrowid
    fb1 = db.execute(
        "INSERT INTO products (model_id, name, price) VALUES (?, 'B-Melancia', 100)", (model_b,)
    ).lastrowid
    db.commit()
    db.close()
    info = {
        "brand_id": brand_id, "model_a": model_a, "model_b": model_b,
        "fa1": fa1, "fa2": fa2, "fb1": fb1,
    }
    yield info
    db = sqlite3.connect(app_module.DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("DELETE FROM brands WHERE id = ?", (brand_id,))  # CASCADE -> models -> products
    db.commit()
    db.close()


def _delete_coupon(admin_client, cid):
    admin_client.delete(f"/api/coupon/{cid}")


def test_create_coupon_restricted_to_model(admin_client, catalog):
    resp = admin_client.post("/api/coupon", json={
        "code": "SOMODELOA", "type": "percent", "value": 10,
        "model_ids": [catalog["model_a"]],
    })
    assert resp.status_code == 200
    cid = resp.get_json()["id"]
    try:
        coupon = next(c for c in app_module.get_coupons() if c["id"] == cid)
        assert coupon["model_ids"] == [catalog["model_a"]]
        assert coupon["scope_display"] == "MarcaTesteCupom ModeloA"
    finally:
        _delete_coupon(admin_client, cid)


def test_create_coupon_without_models_is_unrestricted(admin_client):
    resp = admin_client.post("/api/coupon", json={
        "code": "GERALTESTE", "type": "percent", "value": 5,
    })
    cid = resp.get_json()["id"]
    try:
        coupon = next(c for c in app_module.get_coupons() if c["id"] == cid)
        assert coupon["model_ids"] == []
        assert coupon["scope_display"] == "Todos os produtos"
    finally:
        _delete_coupon(admin_client, cid)


def test_apply_restricted_returns_only_allowed_products(admin_client, client, catalog):
    resp = admin_client.post("/api/coupon", json={
        "code": "APPLYMODELOA", "type": "percent", "value": 10,
        "model_ids": [catalog["model_a"]],
    })
    cid = resp.get_json()["id"]
    try:
        # Carrinho com um sabor do ModeloA (elegível) e um do ModeloB (não).
        r = client.post("/api/coupon/apply", json={
            "code": "APPLYMODELOA",
            "items": [
                {"flavor_id": catalog["fa1"], "price": 100, "qty": 1},
                {"flavor_id": catalog["fb1"], "price": 100, "qty": 1},
            ],
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        # Só os sabores do ModeloA são elegíveis (fa1, fa2), nunca fb1.
        assert set(data["product_ids"]) == {catalog["fa1"], catalog["fa2"]}
    finally:
        _delete_coupon(admin_client, cid)


def test_apply_restricted_rejected_when_no_eligible_item(admin_client, client, catalog):
    resp = admin_client.post("/api/coupon", json={
        "code": "SOMODELOB", "type": "percent", "value": 10,
        "model_ids": [catalog["model_b"]],
    })
    cid = resp.get_json()["id"]
    try:
        # Carrinho só com sabor do ModeloA — cupom é do ModeloB.
        r = client.post("/api/coupon/apply", json={
            "code": "SOMODELOB",
            "items": [{"flavor_id": catalog["fa1"], "price": 100, "qty": 1}],
        })
        assert r.status_code == 400
        assert r.get_json()["ok"] is False
    finally:
        _delete_coupon(admin_client, cid)


def test_apply_fixed_rejected_above_eligible_subtotal(admin_client, client, catalog):
    """Cupom fixo de R$150 restrito ao ModeloA: com só R$100 elegível no
    carrinho (mesmo havendo R$500 no total), deve ser recusado."""
    resp = admin_client.post("/api/coupon", json={
        "code": "FIXOMODELOA", "type": "fixed", "value": 150,
        "model_ids": [catalog["model_a"]],
    })
    cid = resp.get_json()["id"]
    try:
        r = client.post("/api/coupon/apply", json={
            "code": "FIXOMODELOA",
            "items": [
                {"flavor_id": catalog["fa1"], "price": 100, "qty": 1},   # elegível: 100
                {"flavor_id": catalog["fb1"], "price": 400, "qty": 1},   # não elegível
            ],
        })
        assert r.status_code == 400
        assert r.get_json()["ok"] is False

        # Com 2x do sabor elegível (200 > 150), passa.
        r2 = client.post("/api/coupon/apply", json={
            "code": "FIXOMODELOA",
            "items": [{"flavor_id": catalog["fa1"], "price": 100, "qty": 2}],
        })
        assert r2.status_code == 200
        assert r2.get_json()["ok"] is True
    finally:
        _delete_coupon(admin_client, cid)


def test_apply_unrestricted_returns_null_product_ids(admin_client, client):
    resp = admin_client.post("/api/coupon", json={
        "code": "GERALAPPLY", "type": "percent", "value": 10,
    })
    cid = resp.get_json()["id"]
    try:
        r = client.post("/api/coupon/apply", json={
            "code": "GERALAPPLY",
            "items": [{"flavor_id": 999999, "price": 50, "qty": 1}],
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["product_ids"] is None
    finally:
        _delete_coupon(admin_client, cid)
