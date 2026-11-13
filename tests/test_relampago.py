"""Oferta relâmpago: desconto extra de 24h por cima da oferta do modelo.

Regra (pricing.py): para o cliente é um preço só; por dentro é uma
hierarquia. Relâmpago ativo -> oferta + extra. Quando ele acaba, volta a
oferta normal até o fim dela; depois, o preço cheio.

Mesmo padrão dos outros testes: Flask test client contra o royal.db real,
cada teste limpando o que cria (fixture `loja` de test_promo_api).
"""
import sqlite3
from datetime import datetime, timedelta, timezone

import app as app_module
import pricing
from tests.test_promo_api import _card, _fim, _quote, _set_promo, admin_client, client, loja  # noqa: F401

AGORA = datetime(2026, 11, 27, 15, 0, 0, tzinfo=timezone.utc)
FIM_BF = "2026-11-30T02:59:00Z"


def _set_relampago(mid, valor, fim):
    db = sqlite3.connect(app_module.DB_PATH)
    db.execute("UPDATE vape_models SET relampago_valor = ?, relampago_fim = ? WHERE id = ?", (valor, fim, mid))
    db.commit()
    db.close()


# ---------------- regra pura (pricing.py) ----------------

def test_relampago_soma_ao_desconto_e_aponta_a_oferta_depois():
    pe = pricing.preco_efetivo(89.90, 20, FIM_BF, AGORA, 10, "2026-11-28T15:00:00Z")
    assert pe["relampago"] is True
    assert pe["final"] == 59.90 and pe["desconto"] == 30.0
    assert pe["fim"] == "2026-11-28T15:00:00Z"
    assert pe["depois"] == {"final": 69.90, "desconto": 20.0, "fim": FIM_BF}


def test_relampago_vencido_volta_a_oferta_normal():
    pe = pricing.preco_efetivo(89.90, 20, FIM_BF, AGORA, 10, "2026-11-27T14:59:59Z")
    assert pe["relampago"] is False and pe["final"] == 69.90 and pe["depois"] is None


def test_relampago_sem_oferta_nao_vale():
    pe = pricing.preco_efetivo(89.90, None, None, AGORA, 10, "2026-11-28T15:00:00Z")
    assert pe["ativa"] is False and pe["relampago"] is False and pe["final"] == 89.90


def test_relampago_nunca_passa_do_fim_da_oferta():
    pe = pricing.preco_efetivo(89.90, 20, "2026-11-27T20:00:00Z", AGORA, 10, "2026-11-28T15:00:00Z")
    assert pe["fim"] == "2026-11-27T20:00:00Z"


def test_relampago_que_zeraria_o_sabor_nao_e_aplicado():
    pe = pricing.preco_efetivo(29.90, 20, FIM_BF, AGORA, 10, "2026-11-28T15:00:00Z")
    assert pe["relampago"] is False and pe["final"] == 9.90


def test_valida_relampago_dura_24h_ou_ate_a_oferta():
    assert pricing.valida_relampago("10", 20, FIM_BF, 89.90, AGORA) == (10.0, "2026-11-28T15:00:00Z", None)
    curta = "2026-11-27T20:00:00Z"
    assert pricing.valida_relampago("10", 20, curta, 89.90, AGORA)[1] == curta


def test_valida_relampago_erros():
    assert pricing.valida_relampago("", 20, FIM_BF, 89.90, AGORA) == (None, None, None)
    assert pricing.valida_relampago("10", None, None, 89.90, AGORA)[2]          # sem oferta
    assert pricing.valida_relampago("0", 20, FIM_BF, 89.90, AGORA)[2]           # zero
    assert pricing.valida_relampago("abc", 20, FIM_BF, 89.90, AGORA)[2]         # lixo
    assert pricing.valida_relampago("69.90", 20, FIM_BF, 89.90, AGORA)[2]       # soma = preço


# ---------------- catálogo, loja e cotação ----------------

def test_catalogo_com_relampago_e_versao_herda(loja):
    bf_fim = _fim(timedelta(days=3))
    rel_fim = _fim(timedelta(hours=24))
    _set_promo(loja["principal"], 20, bf_fim)
    _set_relampago(loja["principal"], 10, rel_fim)
    card = _card(loja["principal"])
    assert card["promo_relampago"] is True
    assert card["min_price"] == 89.99 and card["promo_desconto"] == 30.0 and card["promo_fim"] == rel_fim
    assert card["promo_depois"] == {"min_price": 99.99, "promo_desconto": 20.0, "promo_fim": bf_fim}
    fv = next(f for f in card["flavors"] if f["id"] == loja["fv"])   # versão Slim
    assert fv["price"] == 89.99 and fv["promo_depois"]["price"] == 99.99


def test_home_mostra_relampago_e_fila_do_destaque(client, loja):
    bf_fim = _fim(timedelta(days=3))
    rel_fim = _fim(timedelta(hours=24))
    _set_promo(loja["principal"], 20, bf_fim)
    _set_relampago(loja["principal"], 10, rel_fim)
    html = client.get("/").get_data(as_text=True)
    assert f'data-promo-depois="{bf_fim}"' in html
    assert 'data-depois-href="#i-clock"' in html
    assert "is-relampago" in html
    # Destaque do hero: a entrada do relâmpago e, na fila, a da oferta normal.
    hero = html.split('class="promo-next"')[1].split("</div>")[0]
    assert f'data-promo-fim="{rel_fim}"' in hero and f'data-promo-fim="{bf_fim}"' in hero
    assert hero.index(rel_fim) < hero.index(bf_fim)
    assert "⚡" not in html                     # ícone é SVG, nunca emoji


def test_cotacao_com_relampago_e_depois_dele(client, loja):
    bf_fim = _fim(timedelta(days=3))
    _set_promo(loja["principal"], 20, bf_fim)
    _set_relampago(loja["principal"], 10, _fim(timedelta(hours=24)))
    q = _quote(client, loja["f1"])[loja["f1"]]
    assert q["price"] == 99.99 and q["promo_relampago"] is True
    assert q["promo_depois"] == {"price": 109.99, "promo_desconto": 20.0, "promo_fim": bf_fim}
    _set_relampago(loja["principal"], 10, _fim(timedelta(seconds=-1)))
    q = _quote(client, loja["f1"])[loja["f1"]]
    assert q["price"] == 109.99 and q["promo_relampago"] is False and q["promo_fim"] == bf_fim


# ---------------- painel ----------------

def test_painel_comeca_relampago_por_24h(admin_client, loja):
    _set_promo(loja["principal"], 20, _fim(timedelta(days=3)))
    r = admin_client.post(f"/api/model/{loja['principal']}", json={"relampago": {"valor": "10"}})
    assert r.status_code == 200, r.get_json()
    rel = r.get_json()["relampago"]
    fim = pricing.parse_fim(rel["fim"])
    assert rel["valor"] == 10.0
    assert timedelta(hours=23, minutes=59) < fim - pricing.agora_utc() <= timedelta(hours=24)
    # Mudar o valor com o relâmpago ativo não reinicia o relógio.
    r2 = admin_client.post(f"/api/model/{loja['principal']}", json={"relampago": {"valor": "12"}})
    assert r2.get_json()["relampago"] == {"valor": 12.0, "fim": rel["fim"]}
    # Encerrar.
    r3 = admin_client.post(f"/api/model/{loja['principal']}", json={"relampago": {"valor": ""}})
    assert r3.get_json()["relampago"] == {"valor": None, "fim": None}


def test_painel_relampago_exige_oferta_e_respeita_preco(admin_client, loja):
    r = admin_client.post(f"/api/model/{loja['principal']}", json={"relampago": {"valor": "10"}})
    assert r.status_code == 400 and "oferta" in r.get_json()["error"]
    _set_promo(loja["principal"], 20, _fim(timedelta(days=3)))
    # Sabor mais barato do card é 119,99 (versão Slim): 20 + 100 passa do limite.
    r = admin_client.post(f"/api/model/{loja['principal']}", json={"relampago": {"valor": "100"}})
    assert r.status_code == 400
    r = admin_client.post(f"/api/model/{loja['versao']}", json={"relampago": {"valor": "5"}})
    assert r.status_code == 400


def test_remover_oferta_remove_relampago(admin_client, loja):
    _set_promo(loja["principal"], 20, _fim(timedelta(days=3)))
    _set_relampago(loja["principal"], 10, _fim(timedelta(hours=24)))
    r = admin_client.post(f"/api/model/{loja['principal']}", json={"promo": {"desconto": "", "fim": ""}})
    assert r.status_code == 200
    db = sqlite3.connect(app_module.DB_PATH)
    row = db.execute("SELECT relampago_valor, relampago_fim FROM vape_models WHERE id = ?",
                     (loja["principal"],)).fetchone()
    db.close()
    assert row == (None, None)


def test_painel_mostra_linha_do_relampago(admin_client, loja):
    html = admin_client.get("/admin").get_data(as_text=True)
    assert f'id="relampago-{loja["principal"]}"' in html
    assert f'id="relampago-{loja["versao"]}"' not in html     # versão herda do principal
