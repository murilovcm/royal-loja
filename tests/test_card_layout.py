"""Card de produto reformulado (catálogo da home).

- Faixa da promoção no topo do card (fora da foto): "Oferta" ou "Relâmpago",
  com o prazo num [data-cd data-cd-roll] que o countdown.js anima.
- Puffs logo abaixo do nome; sem a faixa de cima antiga (puffs + "TOP").
- Em oferta: "de R$ X" riscado no lugar do "a partir de"; sem selo "-R$" na
  foto e sem a faixa "Economia".
- Botão "Escolher sabor" no lugar do "+".

Mesmo padrão dos outros testes: Flask test client contra o royal.db real,
fixture `loja` de test_promo_api (limpa o que cria).
"""
import sqlite3
from datetime import timedelta

import app as app_module
from tests.test_promo_api import _fim, _set_promo, client, loja  # noqa: F401
from tests.test_relampago import _set_relampago


def _puffs(mid, texto="18.000 puffs"):
    db = sqlite3.connect(app_module.DB_PATH)
    db.execute("UPDATE vape_models SET puff_count = ? WHERE id = ?", (texto, mid))
    db.commit()
    db.close()


def _article(html, mid):
    """HTML completo do card do catálogo com aquele data-id."""
    start = html.split(f'data-id="{mid}"')[0].rsplit("<article", 1)[0]
    rest = html[len(start):]
    return rest[: rest.index("</article>") + len("</article>")]


def test_card_sem_promocao(client, loja):
    _puffs(loja["outro"])
    html = client.get("/").get_data(as_text=True)
    card = _article(html, loja["outro"])
    assert "deal-cap" not in card and "is-promo" not in card
    assert '<div class="card-puffs"><i class="ico-bolt"></i>18.000 puffs</div>' in card
    assert 'class="from from-base">a partir de<' in card
    assert "Escolher sabor" in card and 'href="#i-arrow-right"' in card
    # Peças que saíram do card.
    for velho in ("card-top", "puff-badge", "best-tag", "card-plus", "promo-off", "promo-cd", "promo-economia"):
        assert velho not in card, velho


def test_card_em_oferta_tem_faixa_e_de_riscado(client, loja):
    fim = _fim(timedelta(days=3))
    _set_promo(loja["principal"], 20, fim)
    _puffs(loja["principal"])
    card = _article(client.get("/").get_data(as_text=True), loja["principal"])
    faixa = card.split('class="deal-cap"')[1].split("</div>")[0]
    assert "data-promo-only" in card.split('class="deal-cap"')[1][:40]
    assert '<span class="deal-cap-lbl">Oferta</span>' in faixa
    assert "data-cd data-cd-roll" in faixa and " dias</b>" in faixa
    # Faixa vem antes da foto; puffs vem depois do nome.
    assert card.index("deal-cap") < card.index("card-img")
    assert card.index("<h3>") < card.index("card-puffs")
    # "de R$ X" riscado (some com a oferta) e o "a partir de" para depois dela.
    assert 'class="from from-was" data-promo-only>de <s class="price-was">R$ 119,99</s>' in card
    assert "from-base" in card
    assert "promo-economia" not in card and "promo-off" not in card


def test_card_relampago_por_cima_vira_oferta_ao_acabar(client, loja):
    _set_promo(loja["principal"], 20, _fim(timedelta(days=3)))
    _set_relampago(loja["principal"], 10, _fim(timedelta(hours=5)))
    card = _article(client.get("/").get_data(as_text=True), loja["principal"])
    faixa = card.split('class="deal-cap"')[1].split("</div>")[0]
    assert "is-relampago" in card
    assert 'href="#i-bolt" data-depois-href="#i-clock"' in faixa
    assert 'data-depois-text="Oferta">Relâmpago<' in faixa
    assert "⚡" not in card  # ícone é SVG, nunca emoji


def test_card_relampago_sozinho_some_ao_acabar(client, loja):
    _set_relampago(loja["principal"], 10, _fim(timedelta(hours=5)))
    card = _article(client.get("/").get_data(as_text=True), loja["principal"])
    faixa = card.split('class="deal-cap"')[1].split("</div>")[0]
    assert ">Relâmpago<" in faixa and "data-depois-text" not in faixa
    assert "data-promo-depois" not in card


def test_card_sem_puffs_cadastrados_nao_mostra_linha_vazia(client, loja):
    _puffs(loja["outro"], "")
    card = _article(client.get("/").get_data(as_text=True), loja["outro"])
    assert "card-puffs" not in card
