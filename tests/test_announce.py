"""Testes da faixa rotativa de avisos do topo.

parse_announce() é a única porta entre o texto livre do painel e o HTML da
loja: é ela que decide o que vira trecho colorido. Como a cor sai num
style="color: ..." no template, o que importa aqui é que SÓ hex válido passe
como cor e todo o resto continue sendo texto (escapado pelo Jinja).

Mesmo padrão dos outros testes do projeto: Flask test client contra o
royal.db real, restaurando o que foi alterado.
"""
import sqlite3

import pytest

import app as app_module
from app import parse_announce


def msgs(texto):
    return parse_announce({"announce_messages": texto})


def test_plain_lines_become_single_segment():
    assert msgs("Frete grátis\nEntrega hoje") == [
        [{"text": "Frete grátis", "color": None}],
        [{"text": "Entrega hoje", "color": None}],
    ]


def test_colored_word_is_split_out():
    assert msgs("Frete grátis acima de [#FF3B30]R$ 250[/] hoje") == [[
        {"text": "Frete grátis acima de ", "color": None},
        {"text": "R$ 250", "color": "#FF3B30"},
        {"text": " hoje", "color": None},
    ]]


def test_several_colors_in_one_line_and_short_hex():
    assert msgs("[#fff]Entrega[/] no [#25D366]mesmo dia[/]") == [[
        {"text": "Entrega", "color": "#fff"},
        {"text": " no ", "color": None},
        {"text": "mesmo dia", "color": "#25D366"},
    ]]


@pytest.mark.parametrize("texto", [
    "[red]R$ 250[/]",                      # nome de cor não é hex
    "[#FF3B30;background:url(x)]R$ 250[/]",  # tentativa de injetar CSS
    "[#FF3B30]R$ 250",                     # sem fechamento
    "R$ 250[/]",                           # fechamento solto
    "[#FF3B30][/]",                        # trecho vazio
])
def test_invalid_markup_stays_literal_text(texto):
    resultado = msgs(texto)
    assert resultado == [[{"text": texto, "color": None}]]


def test_blank_lines_are_skipped_and_capped_at_six():
    texto = "\n".join(f"Mensagem {n}" for n in range(1, 9)) + "\n\n   \n"
    resultado = msgs(texto)
    assert len(resultado) == app_module.ANNOUNCE_MAX == 6
    assert resultado[-1] == [{"text": "Mensagem 6", "color": None}]


def test_empty_config():
    assert msgs("") == []
    assert parse_announce({}) == []


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def _set_config(values):
    db = sqlite3.connect(app_module.DB_PATH)
    saved = {
        k: (row[0] if row else None)
        for k in values
        for row in [db.execute("SELECT value FROM site_config WHERE key = ?", (k,)).fetchone()]
    }
    for k, v in values.items():
        db.execute(
            "INSERT INTO site_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (k, v),
        )
    db.commit()
    db.close()
    return saved


def _restore_config(saved):
    db = sqlite3.connect(app_module.DB_PATH)
    for k, v in saved.items():
        if v is None:
            db.execute("DELETE FROM site_config WHERE key = ?", (k,))
        else:
            db.execute("UPDATE site_config SET value = ? WHERE key = ?", (v, k))
    db.commit()
    db.close()


def test_storefront_renders_colored_word_and_rotation_markup(client):
    saved = _set_config({
        "announce_enabled": "1",
        "announce_messages": "Frete acima de [#FF3B30]R$ 250[/]\n<b>Entrega</b> hoje",
    })
    try:
        html = client.get("/").get_data(as_text=True)
    finally:
        _restore_config(saved)
    assert '<span class="announce-color" style="color: #FF3B30">R$ 250</span>' in html
    # Texto do painel continua escapado: nada de HTML cru na faixa.
    assert "&lt;b&gt;Entrega&lt;/b&gt; hoje" in html
    # Duas mensagens: gira, então tem traços (um por mensagem), seta e foco.
    assert html.count('class="announce-msg') == 2
    assert 'class="announce-segs"' in html
    assert html.count("<i></i>", html.index('class="announce-segs"')) >= 2
    assert "#i-chevron-right" in html
    assert 'id="announceBar"' in html and 'tabindex="0"' in html


def test_single_message_has_no_rotation_controls(client):
    saved = _set_config({"announce_enabled": "1", "announce_messages": "Só uma mensagem"})
    try:
        html = client.get("/").get_data(as_text=True)
    finally:
        _restore_config(saved)
    assert "announce-single" in html
    assert 'class="announce-segs"' not in html
    assert "announce-rotates" not in html


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


def test_admin_has_word_color_tools(admin_client):
    """Os ids são o contrato com initAnnounceColors() no admin.html: se sumirem,
    a barra de cores para de funcionar sem erro visível."""
    html = admin_client.get("/admin").get_data(as_text=True)
    for el_id in ("cfgAnnounceMsgs", "cfgAnnounceCustom", "cfgAnnounceClear", "cfgAnnouncePreview"):
        assert f'id="{el_id}"' in html, f"{el_id} sumiu do painel"
    assert html.count('class="acb-swatch"') >= 5
