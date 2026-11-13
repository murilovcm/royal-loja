"""Mostrar/ocultar os dois textos do hero (painel → Identidade Visual → Topo
da loja).

- Título oculto: continua no HTML como <h1 class="sr-only"> (o Google lê).
- Frase de apoio oculta: não é renderizada.
- Sem a chave no banco (loja antiga), os dois aparecem: publicar não muda nada.

Mesmo padrão dos outros testes: Flask test client contra o royal.db real,
restaurando o que foi alterado.
"""
import sqlite3

import pytest

import app as app_module
from app import parse_hero
from tests.test_announce import _restore_config, _set_config


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def test_missing_keys_mean_visible():
    hero = parse_hero({})
    assert hero["title_visible"] is True
    assert hero["subtitle_visible"] is True


def test_zero_hides():
    hero = parse_hero({"hero_title_visible": "0", "hero_subtitle_visible": "0"})
    assert hero["title_visible"] is False
    assert hero["subtitle_visible"] is False


def test_bf_sign_defaults_to_store_name():
    assert parse_hero({"store_name": "Royal"})["bf_sign"] == "Royal"
    assert parse_hero({"store_name": "Royal", "bf_assinatura": "  Pods   Ilha "})["bf_sign"] == "Pods Ilha"


def test_bf_sign_is_capped():
    sign = parse_hero({"bf_assinatura": "Nome comprido demais para caber"})["bf_sign"]
    assert len(sign) <= 16
    assert sign == sign.strip()


def test_bf_sign_rendered_with_black_friday(client):
    html = _render(client, {"bf_tema_ativo": "1", "bf_assinatura": "Pods Ilha"})
    assert '<span class="sr-only">Pods Ilha</span>' in html
    assert "<i style=\"--i:4.0\">P</i>" in html
    assert "&nbsp;</i>" in html


def _render(client, values):
    saved = _set_config({"hero_subtitle": "Frase de teste do hero", **values})
    try:
        return client.get("/").get_data(as_text=True)
    finally:
        _restore_config(saved)


def test_both_visible_by_default(client):
    html = _render(client, {"hero_title_visible": "1", "hero_subtitle_visible": "1"})
    assert '<h1 class="sr-only">' not in html
    assert '<p class="hero-subhead">Frase de teste do hero</p>' in html


def test_hidden_title_stays_in_html_for_google(client):
    html = _render(client, {"hero_title_visible": "0", "hero_subtitle_visible": "1"})
    assert '<h1 class="sr-only">' in html
    assert "Frase de teste do hero" in html


def test_hidden_subtitle_is_not_rendered(client):
    html = _render(client, {"hero_title_visible": "1", "hero_subtitle_visible": "0"})
    assert "Frase de teste do hero" not in html
    assert 'class="hero-subhead"' not in html


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


def test_admin_identity_blocks_and_switches(admin_client):
    """Os ids são o contrato com as funções saveHero/saveBrand/... do admin."""
    html = admin_client.get("/admin").get_data(as_text=True)
    for el_id in ("idHero", "idBrand", "idColors", "idFooter", "idSeo",
                  "heroTitleSwitch", "heroSubtitleSwitch", "bfSwitch",
                  "saveHeroBtn", "saveBrandBtn", "saveColorsBtn", "saveFooterBtn", "saveSeoBtn"):
        assert f'id="{el_id}"' in html, f"{el_id} sumiu do painel"
