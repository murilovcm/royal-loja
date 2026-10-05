"""Testes do acessório cabo USB-C oferecido no carrinho.

A REGRA de quando a oferta "alavanca" aparece (0 < falta <= preço do cabo) roda
no navegador, em shouldShowLever() no static/app.js — o servidor nunca calcula
o total do pedido. O que dá para cobrir aqui é a camada de que o JS depende: o
saneamento de get_cable(), o salvamento pelo painel e a injeção dos valores no
HTML. Se qualquer uma quebrar, o cabo some da loja (ou aparece sem preço) sem
erro visível.

Mesmo padrão dos outros testes de API do projeto: Flask test client contra o
royal.db real, com cada teste restaurando o que alterou (try/finally).
"""
import sqlite3

import pytest

import app as app_module

CABLE_KEYS = ("cable_enabled", "cable_name", "cable_price", "cable_image")


def get_config():
    """get_config() usa flask.g, então precisa de um app context próprio."""
    with app_module.app.app_context():
        return app_module.get_config()


def set_keys(values):
    db = sqlite3.connect(app_module.DB_PATH)
    for key, value in values.items():
        db.execute(
            "INSERT INTO site_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    db.commit()
    db.close()


def snapshot():
    cfg = get_config()
    return {k: cfg.get(k) for k in CABLE_KEYS}


def restore(saved):
    db = sqlite3.connect(app_module.DB_PATH)
    for key, value in saved.items():
        if value is None:
            db.execute("DELETE FROM site_config WHERE key = ?", (key,))
        else:
            db.execute(
                "INSERT INTO site_config (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
    db.commit()
    db.close()


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def admin_client(client):
    """Loga como dono da loja. /api/cable exige permissão de catálogo, que o
    dono tem por definição."""
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


# ---------------------------------------------------------------------------
# get_cable(): o saneamento que decide se a loja mostra a oferta
# ---------------------------------------------------------------------------
def test_cable_disabled_by_default_when_unset():
    """Config vazia não pode ligar a oferta: um cabo sem nome por R$ 0,00 na
    loja é pior do que nenhum cabo."""
    assert app_module.get_cable({})["enabled"] is False


def test_cable_enabled_requires_name_and_price():
    base = {"cable_enabled": "1", "cable_name": "Cabo USB-C 2 m", "cable_price": "25.00"}
    assert app_module.get_cable(base)["enabled"] is True

    # Sem nome, sem preço ou com preço zero, a oferta fica desligada mesmo com
    # a chave cable_enabled marcada.
    assert app_module.get_cable({**base, "cable_name": "   "})["enabled"] is False
    assert app_module.get_cable({**base, "cable_price": "0"})["enabled"] is False
    assert app_module.get_cable({**base, "cable_price": ""})["enabled"] is False


def test_cable_price_garbage_does_not_crash_the_store():
    """Um valor não numérico em site_config não pode derrubar a home inteira."""
    cable = app_module.get_cable(
        {"cable_enabled": "1", "cable_name": "Cabo", "cable_price": "vinte e cinco"}
    )
    assert cable["price"] == 0.0
    assert cable["enabled"] is False


def test_cable_switch_off_keeps_the_data():
    """Desligar a oferta não apaga nome/preço: o lojista religa sem redigitar."""
    cable = app_module.get_cable(
        {"cable_enabled": "0", "cable_name": "Cabo USB-C 2 m", "cable_price": "25.00"}
    )
    assert cable["enabled"] is False
    assert cable["name"] == "Cabo USB-C 2 m"
    assert cable["price"] == 25.0


# ---------------------------------------------------------------------------
# /api/cable
# ---------------------------------------------------------------------------
def test_cable_api_requires_login(client):
    saved = snapshot()
    try:
        resp = client.post("/api/cable", json={"enabled": True, "name": "X", "price": 9})
        assert resp.status_code == 401
        assert get_config().get("cable_name") != "X"
    finally:
        restore(saved)


def test_owner_can_save_cable(admin_client):
    saved = snapshot()
    try:
        resp = admin_client.post(
            "/api/cable",
            json={"enabled": True, "name": "Cabo USB-C 2 m", "price": 25, "image": ""},
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

        cfg = get_config()
        assert cfg["cable_enabled"] == "1"
        assert cfg["cable_name"] == "Cabo USB-C 2 m"
        # Gravado com 2 casas: o JS lê este valor direto como preço exibido.
        assert cfg["cable_price"] == "25.00"
    finally:
        restore(saved)


def test_cable_rejects_negative_price(admin_client):
    saved = snapshot()
    try:
        resp = admin_client.post(
            "/api/cable", json={"enabled": True, "name": "Cabo", "price": -5}
        )
        assert resp.status_code == 400
        assert get_config().get("cable_price") != "-5.00"
    finally:
        restore(saved)


def test_cable_rejects_external_image_url(admin_client):
    """A URL vai para um <img> da loja: só aceitamos caminho do nosso uploader."""
    saved = snapshot()
    try:
        resp = admin_client.post(
            "/api/cable",
            json={
                "enabled": True,
                "name": "Cabo",
                "price": 25,
                "image": "https://exemplo.invalido/cabo.png",
            },
        )
        assert resp.status_code == 400
        assert "https://exemplo.invalido/cabo.png" not in (get_config().get("cable_image") or "")
    finally:
        restore(saved)


def test_cable_accepts_uploaded_image_path(admin_client):
    saved = snapshot()
    try:
        resp = admin_client.post(
            "/api/cable",
            json={
                "enabled": True,
                "name": "Cabo",
                "price": 25,
                "image": "/static/uploads/abc123.png",
            },
        )
        assert resp.status_code == 200
        assert get_config()["cable_image"] == "/static/uploads/abc123.png"
    finally:
        restore(saved)


# ---------------------------------------------------------------------------
# Injeção no HTML — é daqui que o app.js lê a config
# ---------------------------------------------------------------------------
def test_home_injects_cable_config(client):
    saved = snapshot()
    try:
        set_keys({
            "cable_enabled": "1",
            "cable_name": "Cabo USB-C 2 m",
            "cable_price": "25.00",
            "cable_image": "/static/uploads/cabo.png",
        })
        html = client.get("/").get_data(as_text=True)
        assert '"Cabo USB-C 2 m"' in html
        assert "25.0" in html
        assert "/static/uploads/cabo.png" in html
    finally:
        restore(saved)


def test_home_renders_with_cable_off(client):
    """A home não pode quebrar quando o cabo nunca foi configurado."""
    saved = snapshot()
    try:
        set_keys({"cable_enabled": "0", "cable_name": "", "cable_price": "", "cable_image": ""})
        resp = client.get("/")
        assert resp.status_code == 200
        assert "enabled: false" in resp.get_data(as_text=True)
    finally:
        restore(saved)


def test_cable_name_with_quote_does_not_break_the_script(client):
    """O nome é texto livre do painel. Saindo por tojson, uma aspa dentro dele
    vira \\" em vez de fechar a string e derrubar o <script> inteiro."""
    saved = snapshot()
    try:
        set_keys({
            "cable_enabled": "1",
            "cable_name": 'Cabo "turbo" 2 m',
            "cable_price": "25.00",
            "cable_image": "",
        })
        html = client.get("/").get_data(as_text=True)
        assert r"Cabo \"turbo\" 2 m" in html
        # A aspa crua seguida do fechamento do objeto indicaria string quebrada.
        assert 'name: "Cabo "turbo" 2 m"' not in html
    finally:
        restore(saved)


def test_admin_page_shows_cable_form(admin_client):
    html = admin_client.get("/admin").get_data(as_text=True)
    assert 'id="cableName"' in html
    assert 'id="cablePrice"' in html
    assert 'id="cableEnabled"' in html
    assert 'id="cableImgInput"' in html
