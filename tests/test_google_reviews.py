"""Testes das avaliações do Google (seção "Quem compra, recomenda" + linha da
nota no hero).

O que mais importa aqui é o botão Ativo/Oculto do painel: o recurso nasce
OCULTO e, oculto, nada pode vazar para o cliente (nem a seção nem a nota).

Mesmo padrão dos outros testes de API do projeto: Flask test client contra o
royal.db real, com cada teste restaurando o que alterou (try/finally).
"""
import io
import sqlite3

import pytest
from PIL import Image

import app as app_module

REVIEW_KEYS = ("reviews_enabled", "reviews_rating", "reviews_count", "reviews_url")


def _db():
    db = sqlite3.connect(app_module.DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def snapshot():
    db = _db()
    cfg = {r["key"]: r["value"] for r in db.execute(
        "SELECT key, value FROM site_config WHERE key IN (%s)" % ",".join("?" * len(REVIEW_KEYS)),
        REVIEW_KEYS,
    )}
    ids = {r["id"] for r in db.execute("SELECT id FROM google_reviews")}
    db.close()
    return cfg, ids


def restore(saved):
    cfg, ids = saved
    db = _db()
    for key in REVIEW_KEYS:
        if key in cfg:
            db.execute("UPDATE site_config SET value = ? WHERE key = ?", (cfg[key], key))
        else:
            db.execute("DELETE FROM site_config WHERE key = ?", (key,))
    # Apaga só as avaliações criadas pelo teste.
    for row in db.execute("SELECT id FROM google_reviews").fetchall():
        if row["id"] not in ids:
            db.execute("DELETE FROM google_reviews WHERE id = ?", (row["id"],))
    db.commit()
    db.close()


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def admin_client(client):
    token = "test-csrf-token"
    db = _db()
    owner = db.execute("SELECT id FROM users WHERE role = 'owner' LIMIT 1").fetchone()
    db.close()
    with client.session_transaction() as sess:
        sess["user_id"] = owner["id"]
        sess["csrf_token"] = token
    client.environ_base["HTTP_X_ADMIN_TOKEN"] = token
    return client


@pytest.fixture
def saved():
    s = snapshot()
    try:
        yield s
    finally:
        restore(s)


def _new_review(c, **fields):
    rid = c.post("/api/review", json={}).get_json()["review"]["id"]
    body = {"author": "Ana Paula", "rating": 5, "when_label": "há 2 semanas",
            "text": "Chegou rápido e original.", "active": True}
    body.update(fields)
    assert c.post(f"/api/review/{rid}", json=body).get_json()["ok"]
    return rid


def test_reviews_default_is_hidden():
    """Banco novo: o recurso começa oculto em todas as lojas."""
    db = _db()
    row = db.execute("SELECT value FROM site_config WHERE key = 'reviews_enabled'").fetchone()
    db.close()
    assert row is not None


def test_hidden_shows_nothing_to_customers(admin_client, saved):
    c = admin_client
    _new_review(c)
    c.post("/api/reviews/settings", json={"enabled": False, "rating": "4,9", "count": "312"})
    html = c.get("/").get_data(as_text=True)
    assert 'id="avaliacoes"' not in html
    assert 'id="heroRating"' not in html


def test_active_shows_section_and_rating_once(admin_client, saved):
    c = admin_client
    _new_review(c, author="Rafael Costa", text="Melhor loja de São Luís.")
    c.post("/api/reviews/settings", json={"enabled": True, "rating": "4.9", "count": "312",
                                          "url": "https://g.page/r/exemplo"})
    html = c.get("/").get_data(as_text=True)
    assert 'id="avaliacoes"' in html
    assert 'id="heroRating"' in html
    assert "312 avaliações no Google" in html
    # A nota é gravada com vírgula e aparece uma única vez na página.
    assert html.count("<b>4,9</b>") == 1
    if 'id="faq"' in html:
        assert html.index('id="avaliacoes"') < html.index('id="faq"')


def test_inactive_review_is_not_rendered(admin_client, saved):
    c = admin_client
    c.post("/api/reviews/settings", json={"enabled": True, "rating": "4,9"})
    rid = _new_review(c, author="Pessoa Oculta Zq", text="Não deveria aparecer.")
    c.post(f"/api/review/{rid}", json={"active": False})
    html = c.get("/").get_data(as_text=True)
    assert "Pessoa Oculta Zq" not in html


def test_review_text_is_escaped(admin_client, saved):
    c = admin_client
    c.post("/api/reviews/settings", json={"enabled": True, "rating": "4,9"})
    _new_review(c, text="<script>alert(1)</script> bom")
    html = c.get("/").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html


def test_settings_validation(admin_client, saved):
    c = admin_client
    assert c.post("/api/reviews/settings", json={"rating": "7"}).status_code == 400
    assert c.post("/api/reviews/settings", json={"rating": "abc"}).status_code == 400
    assert c.post("/api/reviews/settings", json={"count": "muitos"}).status_code == 400
    assert c.post("/api/reviews/settings", json={"url": "javascript:alert(1)"}).status_code == 400


def test_image_urls_must_come_from_uploader(admin_client, saved):
    c = admin_client
    rid = _new_review(c)
    r = c.post(f"/api/review/{rid}", json={"photo_url": "https://evil.example/x.png"})
    assert r.status_code == 400


def test_upload_crops_photo_and_avatar(admin_client, saved):
    c = admin_client
    rid = _new_review(c)

    def png(w, h):
        buf = io.BytesIO()
        Image.new("RGB", (w, h), "purple").save(buf, "PNG")
        buf.seek(0)
        return buf

    for kind, size in (("photo", (900, 675)), ("avatar", (160, 160))):
        r = c.post("/api/upload_review_image",
                   data={"kind": kind, "review_id": str(rid), "file": (png(1300, 700), "x.png")},
                   content_type="multipart/form-data").get_json()
        assert r["ok"], r
        path = app_module.os.path.join(app_module.app.config["UPLOAD_DIR"], r["url"].rsplit("/", 1)[1])
        try:
            assert Image.open(path).size == size
        finally:
            app_module.os.remove(path)


def test_write_requires_csrf(client):
    assert client.post("/api/reviews/settings", json={"enabled": True}).status_code in (401, 403)
    assert client.post("/api/review", json={}).status_code in (401, 403)


def test_hero_has_no_brand_chips(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="heroChips"' not in html
