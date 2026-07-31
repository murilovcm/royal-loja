"""Testes da configuração de frete grátis por valor de pedido.

A REGRA em si (zerar o frete acima do mínimo, só nas zonas até o teto) roda no
navegador, dentro de computeOrderTotals() no static/app.js — o servidor nunca
calcula o total do pedido. O que dá para cobrir aqui é a camada de que o JS
depende: os defaults semeados, o salvamento pelo painel e a injeção dos valores
no HTML. Se qualquer uma delas quebrar, o app.js cai no fallback e o benefício
some da loja sem erro visível.

Mesmo padrão dos outros testes de API do projeto: Flask test client contra o
royal.db real, com cada teste restaurando o que alterou (try/finally).
"""
import sqlite3

import pytest

import app as app_module

FREE_SHIP_KEYS = (
    "free_ship_enabled", "free_ship_min", "free_ship_max_zone", "free_ship_min_saving",
)


def get_config():
    """get_config() usa flask.g, então precisa de um app context próprio."""
    with app_module.app.app_context():
        return app_module.get_config()


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def admin_client(client):
    """Loga como dono da loja: /api/update_config é owner-only."""
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


def test_defaults_are_seeded():
    """Sem essas chaves o app.js desliga o frete grátis silenciosamente."""
    cfg = get_config()
    for key in FREE_SHIP_KEYS:
        assert key in cfg, f"chave {key} não foi semeada em site_config"
    assert float(cfg["free_ship_min"]) > 0
    assert float(cfg["free_ship_max_zone"]) > 0


def test_update_config_requires_owner(client):
    resp = client.post("/api/update_config", json={"key": "free_ship_min", "value": "1"})
    assert resp.status_code == 401
    assert get_config()["free_ship_min"] != "1"


def test_owner_can_change_minimum(admin_client):
    original = get_config()["free_ship_min"]
    try:
        resp = admin_client.post(
            "/api/update_config", json={"key": "free_ship_min", "value": "300.00"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert get_config()["free_ship_min"] == "300.00"
    finally:
        admin_client.post(
            "/api/update_config", json={"key": "free_ship_min", "value": original}
        )
    assert get_config()["free_ship_min"] == original


def test_storefront_injects_freeship_config(client):
    """O app.js lê window.ROYAL.freeShip. Os números precisam sair do Jinja já
    como literais numéricos — `min: "250"` com aspas faria a comparação
    `discountedTotal >= fs.min` virar comparação entre número e string."""
    html = client.get("/").get_data(as_text=True)
    cfg = get_config()
    assert "freeShip" in html
    assert f"min: {float(cfg['free_ship_min'])}" in html
    assert f"maxZone: {float(cfg['free_ship_max_zone'])}" in html
    assert f"minSaving: {float(cfg['free_ship_min_saving'])}" in html


def test_storefront_survives_missing_freeship_keys(client):
    """Banco antigo, migração ainda não rodou: a loja tem que abrir mesmo assim,
    com o benefício desligado, em vez de estourar erro de template."""
    slots = ", ".join("?" * len(FREE_SHIP_KEYS))
    db = sqlite3.connect(app_module.DB_PATH)
    saved = db.execute(
        f"SELECT key, value FROM site_config WHERE key IN ({slots})", FREE_SHIP_KEYS
    ).fetchall()
    db.execute(f"DELETE FROM site_config WHERE key IN ({slots})", FREE_SHIP_KEYS)
    db.commit()
    db.close()
    try:
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "enabled: false" in html
        assert "min: 0.0" in html
    finally:
        db = sqlite3.connect(app_module.DB_PATH)
        for key, value in saved:
            db.execute(
                "INSERT INTO site_config (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        db.commit()
        db.close()


def test_admin_shipping_tab_has_freeship_card(admin_client):
    """O card fica na aba Frete e é o único jeito de o lojista mexer nesses
    valores — se os ids sumirem, saveFreeShipSettings() quebra em silêncio."""
    html = admin_client.get("/admin").get_data(as_text=True)
    for el_id in ("cfgFreeShipSwitch", "cfgFreeShipMin", "cfgFreeShipMaxZone",
                  "cfgFreeShipMinSaving", "saveFreeShipBtn"):
        assert f'id="{el_id}"' in html, f"{el_id} sumiu do painel"
    assert "saveFreeShipSettings()" in html


def test_announce_ticker_no_longer_promises_200():
    """A faixa do topo não pode anunciar um mínimo diferente do que o carrinho
    exige — a migração guardada em init_db() corrige bancos já publicados."""
    assert "acima de R$ 200" not in get_config().get("announce_messages", "")
