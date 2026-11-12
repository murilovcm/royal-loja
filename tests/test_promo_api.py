"""Promoção com hora marcada, ponta a ponta no servidor: catálogo, cotação do
carrinho, cupom combinado, painel e migração.

Mesmo padrão dos outros testes de API: Flask test client contra o royal.db
real, cada teste limpando o que cria.
"""
import sqlite3
from datetime import timedelta

import pytest

import app as app_module
import pricing


def _fim(delta):
    return pricing.formata_utc(pricing.agora_utc() + delta)


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
def loja():
    """Marca com um modelo principal (2 sabores), uma versão dele (1 sabor) e
    um segundo modelo sem promoção. Remove tudo ao final."""
    db = sqlite3.connect(app_module.DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    bid = db.execute("INSERT INTO brands (name) VALUES ('MarcaTestePromo')").lastrowid
    principal = db.execute(
        "INSERT INTO vape_models (brand_id, name, catalog_pos) VALUES (?, 'PromoPrincipal', -50)", (bid,)
    ).lastrowid
    versao = db.execute(
        "INSERT INTO vape_models (brand_id, name, parent_id, variant_label) VALUES (?, 'PromoSlim', ?, 'Slim')",
        (bid, principal),
    ).lastrowid
    outro = db.execute(
        "INSERT INTO vape_models (brand_id, name, catalog_pos) VALUES (?, 'SemPromo', -49)", (bid,)
    ).lastrowid
    ins = "INSERT INTO products (model_id, name, price) VALUES (?, ?, ?)"
    f1 = db.execute(ins, (principal, "Uva", 129.99)).lastrowid
    f2 = db.execute(ins, (principal, "Menta", 139.99)).lastrowid
    fv = db.execute(ins, (versao, "Uva Slim", 119.99)).lastrowid
    fo = db.execute(ins, (outro, "Melancia", 99.99)).lastrowid
    db.commit()
    db.close()
    yield {"bid": bid, "principal": principal, "versao": versao, "outro": outro,
           "f1": f1, "f2": f2, "fv": fv, "fo": fo}
    db = sqlite3.connect(app_module.DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("DELETE FROM brands WHERE id = ?", (bid,))
    db.commit()
    db.close()


def _set_promo(mid, desconto, fim):
    db = sqlite3.connect(app_module.DB_PATH)
    db.execute("UPDATE vape_models SET desconto_valor = ?, promo_fim = ? WHERE id = ?", (desconto, fim, mid))
    db.commit()
    db.close()


def _card(mid):
    with app_module.app.app_context():
        return next(m for m in app_module.build_catalog() if m["id"] == mid)


def _quote(client, *ids):
    r = client.post("/api/cart/quote", json={"items": [{"flavor_id": i} for i in ids]})
    assert r.status_code == 200
    return {it["flavor_id"]: it for it in r.get_json()["items"]}


# ---------------- catálogo ----------------

def test_catalogo_sem_promo_nao_muda_nada(loja):
    card = _card(loja["principal"])
    assert card["min_price"] == 119.99
    assert card["promo_fim"] is None and card["promo_desconto"] == 0
    for f in card["flavors"]:
        assert f["price"] == f["price_original"]
        assert f["promo_fim"] is None


def test_catalogo_com_promo_ativa_e_versao_herda(loja):
    fim = _fim(timedelta(hours=5))
    _set_promo(loja["principal"], 20, fim)
    card = _card(loja["principal"])
    precos = {f["id"]: f for f in card["flavors"]}
    assert precos[loja["f1"]]["price"] == 109.99
    assert precos[loja["f1"]]["price_original"] == 129.99
    assert precos[loja["f2"]]["price"] == 119.99
    # A versão (Slim) não tem promoção própria: herda a do principal.
    assert precos[loja["fv"]]["price"] == 99.99
    assert precos[loja["fv"]]["promo_fim"] == fim
    assert card["min_price"] == 99.99
    assert card["min_price_original"] == 119.99
    assert card["promo_desconto"] == 20.0
    assert card["promo_fim"] == fim
    # O outro modelo não é afetado.
    assert _card(loja["outro"])["promo_fim"] is None


def test_catalogo_com_promo_expirada_volta_ao_normal(loja):
    _set_promo(loja["principal"], 20, _fim(timedelta(seconds=-1)))
    card = _card(loja["principal"])
    assert card["min_price"] == 119.99
    assert card["promo_fim"] is None
    assert all(f["price"] == f["price_original"] for f in card["flavors"])


def test_ofertas_ordenadas_pelo_fim_mais_proximo(loja):
    _set_promo(loja["principal"], 20, _fim(timedelta(hours=5)))
    _set_promo(loja["outro"], 10, _fim(timedelta(hours=1)))
    with app_module.app.app_context():
        ofertas = app_module.ofertas_do_catalogo(app_module.build_catalog())
    ids = [m["id"] for m in ofertas if m["id"] in (loja["principal"], loja["outro"])]
    assert ids == [loja["outro"], loja["principal"]]


def test_home_renderiza_com_e_sem_promo(client, loja):
    html = client.get("/").get_data(as_text=True)
    assert "PromoPrincipal" in html
    assert 'id="ofertas"' not in html or "PromoPrincipal" not in html.split('id="ofertas"')[1].split("</section>")[0]
    fim = _fim(timedelta(hours=5))
    _set_promo(loja["principal"], 20, fim)
    html = client.get("/").get_data(as_text=True)
    assert 'id="ofertas"' in html
    assert f'data-promo-fim="{fim}"' in html
    assert "serverNow" in html


# ---------------- cotação do carrinho ----------------

def test_cotacao_devolve_preco_oficial(client, loja):
    _set_promo(loja["principal"], 20, _fim(timedelta(hours=5)))
    q = _quote(client, loja["f1"], loja["fv"], loja["fo"], 999999999)
    assert q[loja["f1"]]["price"] == 109.99 and q[loja["f1"]]["price_original"] == 129.99
    assert q[loja["fv"]]["price"] == 99.99            # versão herda
    assert q[loja["fo"]]["price"] == 99.99 and q[loja["fo"]]["promo_fim"] is None
    assert q[999999999]["found"] is False


def test_cotacao_apos_expirar_devolve_preco_cheio(client, loja):
    """O caso do checkout: promo acabou entre adicionar ao carrinho e finalizar."""
    _set_promo(loja["principal"], 20, _fim(timedelta(hours=5)))
    assert _quote(client, loja["f1"])[loja["f1"]]["price"] == 109.99
    _set_promo(loja["principal"], 20, _fim(timedelta(seconds=-1)))
    depois = _quote(client, loja["f1"])[loja["f1"]]
    assert depois["price"] == 129.99
    assert depois["promo_fim"] is None and depois["promo_desconto"] == 0


def test_cotacao_ignora_lixo(client):
    r = client.post("/api/cart/quote", json={"items": [{"flavor_id": "cable"}, {"x": 1}, "a", None]})
    assert r.status_code == 200 and r.get_json()["items"] == []
    assert client.post("/api/cart/quote", data="não é json").get_json()["items"] == []


# ---------------- cupom + promoção ----------------

def test_cupom_fixo_usa_preco_do_servidor_ja_com_promo(admin_client, client, loja):
    """Cupom fixo de R$ 120 restrito ao modelo: sem promo o sabor custa 129,99
    e o cupom cabe; com a promo de R$ 20 ele passa a custar 109,99 e o cupom é
    recusado — mesmo que o navegador minta o preço."""
    resp = admin_client.post("/api/coupon", json={
        "code": "PROMOFIXO120", "type": "fixed", "value": 120, "model_ids": [loja["principal"]],
    })
    cid = resp.get_json()["id"]
    try:
        item = {"flavor_id": loja["f1"], "price": 9999, "qty": 1}
        assert client.post("/api/coupon/apply", json={"code": "PROMOFIXO120", "items": [item]}).status_code == 200
        _set_promo(loja["principal"], 20, _fim(timedelta(hours=5)))
        assert client.post("/api/coupon/apply", json={"code": "PROMOFIXO120", "items": [item]}).status_code == 400
    finally:
        admin_client.delete(f"/api/coupon/{cid}")


def test_cupom_percentual_segue_valendo_com_promo(admin_client, client, loja):
    resp = admin_client.post("/api/coupon", json={"code": "PROMOPCT10", "type": "percent", "value": 10})
    cid = resp.get_json()["id"]
    try:
        _set_promo(loja["principal"], 20, _fim(timedelta(hours=5)))
        r = client.post("/api/coupon/apply", json={
            "code": "PROMOPCT10", "items": [{"flavor_id": loja["f1"], "price": 109.99, "qty": 1}],
        })
        assert r.status_code == 200 and r.get_json()["value"] == 10
    finally:
        admin_client.delete(f"/api/coupon/{cid}")


# ---------------- painel ----------------

def test_painel_grava_promo_em_utc(admin_client, loja):
    amanha = (pricing.agora_utc() + timedelta(days=1)).astimezone(pricing.FUSO_LOJA)
    r = admin_client.post(f"/api/model/{loja['principal']}", json={
        "promo": {"desconto": "20", "fim": amanha.strftime("%Y-%m-%dT%H:%M")},
    })
    assert r.status_code == 200, r.get_json()
    db = sqlite3.connect(app_module.DB_PATH)
    desconto, fim = db.execute(
        "SELECT desconto_valor, promo_fim FROM vape_models WHERE id = ?", (loja["principal"],)
    ).fetchone()
    db.close()
    assert desconto == 20.0
    assert fim.endswith("Z")
    assert pricing.utc_para_local(fim) == amanha.strftime("%Y-%m-%dT%H:%M")
    assert _card(loja["principal"])["promo_desconto"] == 20.0


def test_painel_remove_promo_com_campos_vazios(admin_client, loja):
    _set_promo(loja["principal"], 20, _fim(timedelta(hours=5)))
    r = admin_client.post(f"/api/model/{loja['principal']}", json={"promo": {"desconto": "", "fim": ""}})
    assert r.status_code == 200
    assert _card(loja["principal"])["promo_fim"] is None


def test_painel_valida_promo(admin_client, loja):
    futuro = (pricing.agora_utc() + timedelta(days=1)).astimezone(pricing.FUSO_LOJA).strftime("%Y-%m-%dT%H:%M")
    passado = (pricing.agora_utc() - timedelta(hours=1)).astimezone(pricing.FUSO_LOJA).strftime("%Y-%m-%dT%H:%M")
    post = lambda mid, promo: admin_client.post(f"/api/model/{mid}", json={"promo": promo})
    assert post(loja["principal"], {"desconto": "20", "fim": passado}).status_code == 400
    assert post(loja["principal"], {"desconto": "0", "fim": futuro}).status_code == 400
    assert post(loja["principal"], {"desconto": "20", "fim": ""}).status_code == 400
    # O sabor mais barato do card é o da versão (119,99): o desconto não pode alcançá-lo.
    assert post(loja["principal"], {"desconto": "119.99", "fim": futuro}).status_code == 400
    assert post(loja["principal"], {"desconto": "119.98", "fim": futuro}).status_code == 200
    # Versão não tem promoção própria.
    assert post(loja["versao"], {"desconto": "10", "fim": futuro}).status_code == 400
    assert _card(loja["principal"])["promo_desconto"] == 119.98


def test_painel_promo_exige_login(client, loja):
    r = client.post(f"/api/model/{loja['principal']}", json={"promo": {"desconto": "20", "fim": "2099-01-01T10:00"}})
    assert r.status_code in (401, 403)


def test_black_friday_liga_e_desliga_so_o_hero(admin_client, loja):
    """O botão troca só o hero: entra o letreiro, o CSS e a fonte dele. A seção
    de ofertas NÃO depende do botão."""
    with app_module.app.app_context():
        antes = app_module.get_config().get("bf_tema_ativo")
    _set_promo(loja["principal"], 20, _fim(timedelta(hours=5)))
    try:
        assert admin_client.post("/api/black_friday", json={"bf_tema_ativo": True}).status_code == 200
        html = admin_client.get("/").get_data(as_text=True)
        assert 'data-tema="blackfriday"' in html and "tema-blackfriday.css" in html
        assert 'class="bf-letreiro"' in html and "fonts.googleapis.com" in html
        assert 'id="ofertas"' in html and 'class="promo-next"' in html

        admin_client.post("/api/black_friday", json={"bf_tema_ativo": False})
        html = admin_client.get("/").get_data(as_text=True)
        assert "data-tema=" not in html.split("<head>")[0]
        assert "tema-blackfriday" not in html and "bf-letreiro" not in html
        assert "fonts.googleapis.com" not in html
        # Com o botão desligado as ofertas continuam todas lá.
        assert 'id="ofertas"' in html and 'class="promo-next"' in html
        assert 'class="promo-economia"' in html

        assert admin_client.post("/api/black_friday", json={}).status_code == 400
    finally:
        admin_client.post("/api/black_friday", json={"bf_tema_ativo": antes == "1"})


def test_black_friday_exige_dono(client):
    assert client.post("/api/black_friday", json={"bf_tema_ativo": True}).status_code in (401, 403)


def test_acima_de_24h_o_tempo_restante_e_fixo_em_dias():
    """Mais de 24h: texto parado em dias inteiros, arredondado para baixo. A
    contagem só aparece nas últimas 24 horas."""
    resta = app_module.filtro_promo_resta
    assert resta(_fim(timedelta(days=2, hours=21))) == "2 dias"
    assert resta(_fim(timedelta(days=1, minutes=5))) == "1 dia"
    hms = resta(_fim(timedelta(hours=23, minutes=59, seconds=30)))
    assert len(hms) == 8 and hms.startswith("23:59:")
    assert resta(_fim(timedelta(seconds=-5))) == "00:00:00"
    assert resta("lixo") == ""


# ---------------- seção "Mais Vendidos" ----------------

def _marca_estrela(mid, valor):
    db = sqlite3.connect(app_module.DB_PATH)
    db.execute("UPDATE vape_models SET is_best_seller = ? WHERE id = ?", (valor, mid))
    db.commit()
    db.close()


def test_secao_mais_vendidos_ocultar_e_renomear(admin_client, loja):
    with app_module.app.app_context():
        cfg = app_module.get_config()
        antes = {"best_enabled": cfg.get("best_enabled", "1") == "1", "best_title": cfg.get("best_title", "Mais Vendidos")}
    _marca_estrela(loja["principal"], 1)
    corpo = lambda: admin_client.get("/").get_data(as_text=True).split("</head>")[1].split('id="catalogData"')[0]
    try:
        admin_client.post("/api/best_section", json={"best_enabled": True, "best_title": "Mais Vendidos"})
        html = corpo()
        assert 'id="best"' in html and "Mais Vendidos</h2>" in html

        r = admin_client.post("/api/best_section", json={"best_title": "  Queridinhos   da   casa  "})
        assert r.status_code == 200 and r.get_json()["best_title"] == "Queridinhos da casa"
        html = corpo()
        assert "Queridinhos da casa</h2>" in html
        assert "Mais Vendidos" not in html

        admin_client.post("/api/best_section", json={"best_enabled": False})
        html = corpo()
        assert 'id="best"' not in html
        # A estrela e o filtro continuam: só a faixa some.
        assert 'data-filter="best">Queridinhos da casa<' in html

        # Nome vazio volta ao padrão; texto longo é cortado; HTML é escapado.
        assert admin_client.post("/api/best_section", json={"best_title": "   "}).get_json()["best_title"] == "Mais Vendidos"
        assert len(admin_client.post("/api/best_section", json={"best_title": "x" * 200}).get_json()["best_title"]) == 40
        admin_client.post("/api/best_section", json={"best_enabled": True, "best_title": "<b>Top</b>"})
        html = corpo()
        assert "&lt;b&gt;Top&lt;/b&gt;</h2>" in html and "<b>Top</b></h2>" not in html
        assert admin_client.post("/api/best_section", json={}).status_code == 400
    finally:
        admin_client.post("/api/best_section", json=antes)
        _marca_estrela(loja["principal"], 0)


def test_secao_mais_vendidos_exige_login(client):
    assert client.post("/api/best_section", json={"best_enabled": False}).status_code in (401, 403)


# ---------------- migração ----------------

def test_migracao_idempotente_em_banco_antigo(tmp_path, monkeypatch):
    """Banco com o schema ANTIGO (sem as colunas de promoção) e dados: o
    init_db acrescenta as colunas sem perder nada, e rodar de novo é inofensivo."""
    caminho = tmp_path / "antigo.db"
    db = sqlite3.connect(caminho)
    db.executescript(
        """
        CREATE TABLE brands (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
        CREATE TABLE vape_models (
            id INTEGER PRIMARY KEY AUTOINCREMENT, brand_id INTEGER NOT NULL, name TEXT NOT NULL,
            puff_count TEXT, image_url TEXT, is_best_seller INTEGER DEFAULT 0
        );
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT, model_id INTEGER NOT NULL, name TEXT NOT NULL,
            price REAL DEFAULT 0, is_in_stock INTEGER DEFAULT 1
        );
        INSERT INTO brands (name) VALUES ('Antiga');
        INSERT INTO vape_models (brand_id, name) VALUES (1, 'ModeloAntigo');
        INSERT INTO products (model_id, name, price) VALUES (1, 'Sabor', 89.99);
        """
    )
    db.commit()
    db.close()
    monkeypatch.setattr(app_module, "DB_PATH", str(caminho))
    for _ in range(2):   # duas vezes: a segunda não pode falhar nem duplicar
        app_module.init_db()
    db = sqlite3.connect(caminho)
    cols = [r[1] for r in db.execute("PRAGMA table_info(vape_models)")]
    assert cols.count("desconto_valor") == 1 and cols.count("promo_fim") == 1
    assert db.execute("SELECT name, desconto_valor, promo_fim FROM vape_models").fetchall() == [("ModeloAntigo", None, None)]
    assert db.execute("SELECT price FROM products").fetchone()[0] == 89.99
    assert db.execute("SELECT value FROM site_config WHERE key = 'bf_tema_ativo'").fetchone()[0] == "0"
    assert db.execute("SELECT value FROM site_config WHERE key = 'best_enabled'").fetchone()[0] == "1"
    assert db.execute("SELECT value FROM site_config WHERE key = 'best_title'").fetchone()[0] == "Mais Vendidos"
    db.close()
