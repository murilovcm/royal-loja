"""Testes do back-end do painel de atendimento (Etapa 1).

Cobre a leitura da localização colada (atendimento.py), a conta do pedido
(mesma regra do checkout do site) e as rotas /api/atendimento/*, com as
permissões. Mesmo padrão dos outros testes: Flask test client contra o
royal.db real, cada teste restaurando o que alterou (try/finally).
"""
import base64
import json
import re
import sqlite3
import time
from decimal import Decimal
from pathlib import Path

import pytest

import app as app_module
import atendimento

TOKEN = "test-csrf-token"


# ---------------------------------------------------------------------------
# Localização
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("texto, esperado", [
    # Link REAL copiado do WhatsApp Web (enviado pelo Murilo em 16/11/2026).
    ("https://maps.google.com/maps?q=-2.505058526992798%2C-44.249568939208984&z=17&hl=pt-BR",
     (-2.505058526992798, -44.249568939208984)),
    ("https://maps.google.com/maps?q=-2.5006266%2C-44.2499112&z=17&hl=pt-BR", (-2.5006266, -44.2499112)),
    ("https://maps.google.com/maps?q=-2.5006266,-44.2499112", (-2.5006266, -44.2499112)),
    ("https://www.google.com/maps/search/?api=1&query=-2.53,-44.30", (-2.53, -44.30)),
    ("https://www.google.com/maps/@-2.5310,-44.2950,17z", (-2.5310, -44.2950)),
    # /place/: o pino (!3d/!4d) ganha do centro da tela (@).
    ("https://www.google.com/maps/place/Rua+X/@-2.5000,-44.2000,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d-2.5123!4d-44.2456",
     (-2.5123, -44.2456)),
    ("-2.5310, -44.2950", (-2.5310, -44.2950)),
    ("cliente mandou: -2.531045,-44.295012 obrigado", (-2.531045, -44.295012)),
])
def test_extrair_latlng(texto, esperado):
    assert atendimento.extrair_latlng(texto) == pytest.approx(esperado)


@pytest.mark.parametrize("texto", [
    "", "rua das flores 123", "R$ 134,39", "às 14.30, 15.45",
    "https://maps.google.com/maps?q=Rua+Grande", "-95.123, -44.123",
])
def test_extrair_latlng_sem_coordenada(texto):
    assert atendimento.extrair_latlng(texto) is None


def test_link_curto_segue_redirect_do_google():
    saltos = []

    def buscar(url):
        saltos.append(url)
        return "https://maps.google.com/?q=-2.5310,-44.2950&ftid=0x0"

    coords = atendimento.ler_localizacao("olha https://maps.app.goo.gl/AbC123 aí", buscar=buscar)
    assert coords == pytest.approx((-2.5310, -44.2950))
    assert saltos == ["https://maps.app.goo.gl/AbC123"]


def test_link_curto_nao_sai_do_google():
    saltos = []

    def buscar(url):
        saltos.append(url)
        return "https://site-qualquer.com/x"

    assert atendimento.ler_localizacao("https://maps.app.goo.gl/AbC123", buscar=buscar) is None
    # Parou no primeiro salto: o host de fora nunca é pedido.
    assert saltos == ["https://maps.app.goo.gl/AbC123"]


def test_link_curto_limite_de_saltos():
    def buscar(url):
        return "https://maps.app.goo.gl/outro"

    assert atendimento.resolver_link_curto("https://maps.app.goo.gl/x", buscar=buscar) is None


# ---------------------------------------------------------------------------
# Conta do pedido
# ---------------------------------------------------------------------------
REGRAS = {"enabled": True, "min": "250", "max_zone": "22"}


def _zona(preco, label="Zona 1"):
    return {"ok": True, "special": False, "zone_label": label, "price": preco, "message": None}


def test_exemplo_do_planejamento_da_134_39():
    """S200 Icy Mint (R$ 119,99) + frete R$ 8 + crédito = R$ 134,39
    (a atendente tinha dito R$ 134,40)."""
    conta = atendimento.calcular_total(
        [{"preco": 119.99, "qty": 1}], "credito", frete_info=_zona(8), regras=REGRAS,
    )
    assert conta["status"] == "ok"
    assert conta["acrescimo"] == Decimal("6.40")
    assert conta["total"] == Decimal("134.39")


def test_frete_gratis_no_limite_exato():
    conta = atendimento.calcular_total(
        [{"preco": 125, "qty": 2}], "pix", frete_info=_zona(16), regras=REGRAS,
    )
    assert conta["frete_gratis"] is True
    assert conta["frete"] == 0
    assert conta["total"] == Decimal("250.00")


def test_frete_gratis_nao_vale_acima_do_teto_de_zona():
    conta = atendimento.calcular_total(
        [{"preco": 300, "qty": 1}], "pix", frete_info=_zona(30, "Longe"), regras=REGRAS,
    )
    assert conta["frete_gratis"] is False
    assert conta["total"] == Decimal("330.00")


def test_frete_gratis_desligado():
    conta = atendimento.calcular_total(
        [{"preco": 300, "qty": 1}], "pix", frete_info=_zona(8),
        regras={**REGRAS, "enabled": False},
    )
    assert conta["frete_gratis"] is False
    assert conta["total"] == Decimal("308.00")


def test_retirada_sem_frete():
    conta = atendimento.calcular_total([{"preco": 100, "qty": 1}], "credito", retirada=True, regras=REGRAS)
    assert conta["zona"] == "Retirada"
    assert conta["total"] == Decimal("105.00")


@pytest.mark.parametrize("frete_info, status", [
    (None, "sem_localizacao"),
    ({"ok": True, "special": True, "zone_label": "Bolsão 1", "price": None}, "a_combinar"),
    ({"ok": False, "special": False, "zone_label": None, "price": None}, "fora_da_area"),
])
def test_sem_total_quando_frete_desconhecido(frete_info, status):
    conta = atendimento.calcular_total([{"preco": 100, "qty": 1}], "pix", frete_info=frete_info, regras=REGRAS)
    assert conta["status"] == status
    assert conta["total"] is None


def test_credito_igual_ao_do_site():
    js = (Path(app_module.BASE_DIR) / "static" / "app.js").read_text(encoding="utf-8")
    m = re.search(r"CREDIT_SURCHARGE_RATE\s*=\s*([\d.]+)", js)
    assert m, "CREDIT_SURCHARGE_RATE sumiu do static/app.js"
    assert Decimal(m.group(1)) * 100 == atendimento.CREDITO_PCT


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def _db():
    db = sqlite3.connect(app_module.DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def _logar(client, uid):
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["csrf_token"] = TOKEN
    client.environ_base["HTTP_X_ADMIN_TOKEN"] = TOKEN
    return client


@pytest.fixture
def owner_client(client):
    db = _db()
    owner = db.execute("SELECT id FROM users WHERE role = 'owner' LIMIT 1").fetchone()
    db.close()
    return _logar(client, owner["id"])


@pytest.fixture
def staff():
    """Dois funcionários: um com can_atendimento, outro sem."""
    db = _db()
    ids = {}
    for nome, pode in (("atd_teste_sim", 1), ("atd_teste_nao", 0)):
        ids[nome] = db.execute(
            "INSERT INTO users (username, password_hash, role, can_atendimento, created_at) "
            "VALUES (?, 'x', 'staff', ?, ?)",
            (nome, pode, time.time()),
        ).lastrowid
    db.commit()
    db.close()
    yield ids
    db = _db()
    db.execute("DELETE FROM users WHERE username IN ('atd_teste_sim', 'atd_teste_nao')")
    db.commit()
    db.close()


@pytest.fixture
def produto():
    """Uma marca, um modelo e dois sabores (um esgotado)."""
    db = _db()
    brand = db.execute("INSERT INTO brands (name) VALUES ('MarcaTesteAtd')").lastrowid
    model = db.execute(
        "INSERT INTO vape_models (brand_id, name, puff_count) VALUES (?, 'S200Teste', '20000')", (brand,)
    ).lastrowid
    ok = db.execute(
        "INSERT INTO products (model_id, name, price, is_in_stock) VALUES (?, 'Icy Mint', 119.99, 1)", (model,)
    ).lastrowid
    esgotado = db.execute(
        "INSERT INTO products (model_id, name, price, is_in_stock) VALUES (?, 'Uva', 119.99, 0)", (model,)
    ).lastrowid
    db.commit()
    db.close()
    yield {"model": model, "ok": ok, "esgotado": esgotado}
    db = _db()
    db.execute("DELETE FROM brands WHERE id = ?", (brand,))
    db.commit()
    db.close()


def test_rotas_exigem_login(client):
    assert client.get("/api/atendimento/catalogo").status_code == 401
    assert client.get("/api/atendimento/config").status_code == 401
    assert client.post("/api/atendimento/cotacao", json={}).status_code == 401


def test_staff_sem_permissao_recebe_403(client, staff):
    _logar(client, staff["atd_teste_nao"])
    assert client.get("/api/atendimento/config").status_code == 403
    assert client.get("/api/atendimento/catalogo").status_code == 403


def test_staff_com_permissao_le_mas_nao_grava(client, staff):
    _logar(client, staff["atd_teste_sim"])
    r = client.get("/api/atendimento/config")
    assert r.status_code == 200
    assert "pix_chave" in r.get_json()["loja"]
    assert r.get_json()["pode_editar"] is False
    r = client.post("/api/atendimento/config", json={"valores": {"atd_pix_chave": "golpe@x.com"}})
    assert r.status_code == 403
    assert client.post("/api/atendimento/motoboy", json={"nome": "X", "telefone": "1"}).status_code == 403


def test_catalogo_traz_sabores_com_estoque(owner_client, produto):
    r = owner_client.get("/api/atendimento/catalogo")
    assert r.status_code == 200
    modelo = next(m for m in r.get_json()["modelos"] if m["id"] == produto["model"])
    assert modelo["marca"] == "MarcaTesteAtd"
    assert modelo["em_estoque"] == 1
    estoque = {s["nome"]: s["em_estoque"] for s in modelo["sabores"]}
    assert estoque == {"Icy Mint": True, "Uva": False}


def test_frete_le_link_e_usa_zonas_do_banco(owner_client):
    r = owner_client.post("/api/atendimento/frete", json={"texto": "https://maps.google.com/maps?q=-2.5006266%2C-44.2499112"})
    assert r.status_code == 200
    d = r.get_json()
    special, concentric = None, None
    with app_module.app.app_context():
        special, concentric = app_module.get_shipping_zones()
    esperado = app_module.calculate_shipping(-2.5006266, -44.2499112, special, concentric)
    assert d["zona"] == esperado["zone_label"]
    assert d["preco"] == esperado["price"]


def test_frete_texto_ilegivel(owner_client):
    r = owner_client.post("/api/atendimento/frete", json={"texto": "perto da praça"})
    assert r.status_code == 400
    assert "localização" in r.get_json()["error"]


def test_cotacao_com_credito_e_retirada(owner_client, produto):
    r = owner_client.post("/api/atendimento/cotacao", json={
        "itens": [{"flavor_id": produto["ok"], "qty": 1}],
        "retirada": True, "pagamento": "credito",
    })
    d = r.get_json()
    assert r.status_code == 200, d
    assert d["status"] == "ok"
    assert d["itens"][0]["sabor"] == "Icy Mint"
    assert d["subtotal"] == 119.99
    assert d["acrescimo"] == 6.0
    assert d["total"] == 125.99


def test_cotacao_entrega_bate_com_a_zona(owner_client, produto):
    link = "https://maps.google.com/maps?q=-2.5006266,-44.2499112"
    with app_module.app.app_context():
        special, concentric = app_module.get_shipping_zones()
        cfg = app_module.get_config()
    info = app_module.calculate_shipping(-2.5006266, -44.2499112, special, concentric)
    r = owner_client.post("/api/atendimento/cotacao", json={
        "itens": [{"flavor_id": produto["ok"], "qty": 1}],
        "localizacao": link, "pagamento": "credito",
    })
    d = r.get_json()
    esperado = atendimento.calcular_total(
        [{"preco": 119.99, "qty": 1}], "credito", frete_info=info,
        regras=app_module._atd_regras_frete(cfg),
    )
    assert d["status"] == esperado["status"]
    assert d["zona"] == esperado["zona"]
    if esperado["total"] is not None:
        assert Decimal(str(d["total"])) == esperado["total"]


def test_cotacao_sem_localizacao_nao_fecha_total(owner_client, produto):
    r = owner_client.post("/api/atendimento/cotacao", json={
        "itens": [{"flavor_id": produto["ok"], "qty": 2}], "pagamento": "pix",
    })
    d = r.get_json()
    assert d["status"] == "sem_localizacao"
    assert d["total"] is None
    assert d["subtotal"] == 239.98


def test_cotacao_recusa_esgotado_e_ignora_preco_enviado(owner_client, produto):
    r = owner_client.post("/api/atendimento/cotacao", json={
        "itens": [{"flavor_id": produto["esgotado"], "qty": 1}], "retirada": True,
    })
    assert r.status_code == 400
    assert "esgotado" in r.get_json()["error"]

    r = owner_client.post("/api/atendimento/cotacao", json={
        "itens": [{"flavor_id": produto["ok"], "qty": 1, "preco": 1}],
        "retirada": True, "pagamento": "pix", "total": 1,
    })
    assert r.get_json()["total"] == 119.99


def test_cotacao_pagamento_invalido(owner_client, produto):
    r = owner_client.post("/api/atendimento/cotacao", json={
        "itens": [{"flavor_id": produto["ok"], "qty": 1}], "retirada": True, "pagamento": "fiado",
    })
    assert r.status_code == 400


def test_config_recusa_chave_desconhecida(owner_client):
    r = owner_client.post("/api/atendimento/config", json={"valores": {"store_name": "X"}})
    assert r.status_code == 400


def test_update_config_generico_nao_mexe_no_pix(owner_client):
    r = owner_client.post("/api/update_config", json={"key": "atd_pix_chave", "value": "x"})
    assert r.status_code == 400


def test_motoboy_criar_editar_desativar(owner_client, staff, client):
    db = _db()
    ultimo_log = db.execute("SELECT COALESCE(MAX(id), 0) FROM atendimento_config_log").fetchone()[0]
    db.close()
    mid = None
    try:
        r = owner_client.post("/api/atendimento/motoboy", json={"nome": "Zé Teste", "telefone": "98 99999-0000"})
        mid = r.get_json()["id"]
        assert owner_client.post(f"/api/atendimento/motoboy/{mid}", json={"telefone": "98 98888-0000"}).get_json()["ok"]
        assert owner_client.delete(f"/api/atendimento/motoboy/{mid}").get_json()["ok"]

        # A atendente só vê os ativos.
        _logar(client, staff["atd_teste_sim"])
        nomes = [m["nome"] for m in client.get("/api/atendimento/config").get_json()["motoboys"]]
        assert "Zé Teste" not in nomes

        db = _db()
        logs = db.execute(
            "SELECT chave FROM atendimento_config_log WHERE id > ? ORDER BY id", (ultimo_log,)
        ).fetchall()
        db.close()
        assert [l["chave"] for l in logs] == [f"motoboy:{mid}"] * 3
    finally:
        db = _db()
        if mid:
            db.execute("DELETE FROM motoboys WHERE id = ?", (mid,))
        db.execute("DELETE FROM atendimento_config_log WHERE id > ?", (ultimo_log,))
        db.commit()
        db.close()


# ---------------------------------------------------------------------------
# Página do painel (Etapa 2)
# ---------------------------------------------------------------------------
def test_pagina_sem_login_vai_para_o_login(client):
    r = client.get("/atendimento")
    assert r.status_code == 302
    assert "/admin/login" in r.headers["Location"]


def test_pagina_staff_sem_permissao(client, staff):
    _logar(client, staff["atd_teste_nao"])
    r = client.get("/atendimento")
    assert r.status_code == 403
    assert "Sem acesso ao atendimento" in r.get_data(as_text=True)


def test_pagina_staff_com_permissao(client, staff):
    _logar(client, staff["atd_teste_sim"])
    r = client.get("/atendimento")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert TOKEN in html
    assert "js/atendimento.js" in html
    assert "--primary-yellow" in html          # cores da loja (_tema.html)
    assert 'id="abaAj"' not in html             # Ajustes é só do dono
    assert "atendimento-ajustes.js" not in html
    assert r.headers.get("X-Robots-Tag") == "noindex, nofollow"


def test_pagina_dono_ve_ajustes(owner_client):
    html = owner_client.get("/atendimento").get_data(as_text=True)
    assert 'id="abaAj"' in html and 'id="ajSenha"' in html
    assert "atendimento-ajustes.js" in html


def test_pagina_tem_pedido_e_mensagens(client, staff):
    """Etapa 3: abas Pedido e Mensagens, com nome do cliente, local colado,
    pagamento e a lista "Em espera". Nenhum campo de preço/total digitável."""
    _logar(client, staff["atd_teste_sim"])
    html = client.get("/atendimento").get_data(as_text=True)
    for id_ in ("abaCat", "abaPed", "abaMsg", "cliente", "local", "segPag",
                "btnGuardar", "btnNovo", "btnEspera", "espera", "btnResumo", "msgLista", "barraPedido"):
        assert f'id="{id_}"' in html, id_
    for pag in ("pix", "dinheiro", "debito", "credito"):
        assert f'data-pag="{pag}"' in html
    assert 'type="number"' not in html


def test_painel_nao_refaz_a_conta():
    """A conta do pedido é do servidor (/cotacao). O JS do painel não pode ter
    a própria regra de crédito: se tivesse, os dois poderiam divergir."""
    js = (Path(app_module.__file__).parent / "static" / "js" / "atendimento.js").read_text(encoding="utf-8")
    assert "/api/atendimento/cotacao" in js
    assert "0.05" not in js and "1.05" not in js
    assert "CREDIT_SURCHARGE_RATE" not in js


def test_cotacao_segue_o_preco_atual_do_cadastro(owner_client, produto):
    """Pedido guardado no navegador guarda só o id: se o preço mudar no
    cadastro, a próxima cotação já vem com o preço novo."""
    corpo = {"itens": [{"flavor_id": produto["ok"], "qty": 2}], "retirada": True, "pagamento": "pix"}
    assert owner_client.post("/api/atendimento/cotacao", json=corpo).get_json()["total"] == 239.98
    db = _db()
    db.execute("UPDATE products SET price = 99.9 WHERE id = ?", (produto["ok"],))
    db.commit()
    db.close()
    d = owner_client.post("/api/atendimento/cotacao", json=corpo).get_json()
    assert d["total"] == 199.8
    assert d["itens"][0]["total"] == 199.8


def test_loja_continua_com_as_cores_do_tema(client):
    html = client.get("/").get_data(as_text=True)
    assert "<style>:root{" in html and "--primary-yellow:" in html


# ---------------------------------------------------------------------------
# Aba Ajustes (Etapa 4)
# ---------------------------------------------------------------------------
SENHA_DONO = "senha-do-dono-teste"


@pytest.fixture
def restaura_config():
    """Guarda as chaves atd_*, o log e os motoboys; devolve tudo no fim."""
    db = _db()
    antes = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM site_config WHERE key LIKE 'atd_%'")}
    ultimo_log = db.execute("SELECT COALESCE(MAX(id), 0) FROM atendimento_config_log").fetchone()[0]
    ultimo_moto = db.execute("SELECT COALESCE(MAX(id), 0) FROM motoboys").fetchone()[0]
    motos = [dict(r) for r in db.execute("SELECT id, telefone, ativo FROM motoboys")]
    ultimo_audit = db.execute("SELECT COALESCE(MAX(id), 0) FROM audit_log").fetchone()[0]
    db.close()
    yield {"ultimo_audit": ultimo_audit}
    db = _db()
    db.execute("DELETE FROM site_config WHERE key LIKE 'atd_%'")
    db.executemany("INSERT INTO site_config (key, value) VALUES (?, ?)", antes.items())
    db.execute("DELETE FROM atendimento_config_log WHERE id > ?", (ultimo_log,))
    db.execute("DELETE FROM motoboys WHERE id > ?", (ultimo_moto,))
    for m in motos:
        db.execute("UPDATE motoboys SET telefone = ?, ativo = ? WHERE id = ?", (m["telefone"], m["ativo"], m["id"]))
    db.commit()
    db.close()
    app_module.LOGIN_ATTEMPTS.clear()


@pytest.fixture
def dono_com_senha(owner_client):
    """O dono com uma senha conhecida (a original volta no fim)."""
    db = _db()
    dono = db.execute("SELECT id, password_hash FROM users WHERE role = 'owner' LIMIT 1").fetchone()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
               (app_module.generate_password_hash(SENHA_DONO), dono["id"]))
    db.commit()
    db.close()
    yield owner_client
    db = _db()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (dono["password_hash"], dono["id"]))
    db.commit()
    db.close()


def _valor(chave):
    db = _db()
    r = db.execute("SELECT value FROM site_config WHERE key = ?", (chave,)).fetchone()
    db.close()
    return r["value"] if r else None


def _codigo(dados):
    return "ATD1:" + base64.b64encode(json.dumps(dados).encode()).decode()


def test_dono_grava_config_com_historico(owner_client, restaura_config):
    antes = _valor("atd_prazo")
    r = owner_client.post("/api/atendimento/config", json={"valores": {"atd_prazo": "até 45 minutos"}})
    assert r.get_json() == {"ok": True, "alterados": ["atd_prazo"]}
    assert owner_client.get("/api/atendimento/config").get_json()["loja"]["prazo"] == "até 45 minutos"
    hist = owner_client.get("/api/atendimento/historico").get_json()["itens"]
    assert hist[0]["chave"] == "atd_prazo"
    assert hist[0]["valor_anterior"] == antes and hist[0]["valor_novo"] == "até 45 minutos"
    assert hist[0]["username"]


def test_pix_so_muda_com_a_senha_do_dono(dono_com_senha, restaura_config):
    antes = _valor("atd_pix_chave")
    corpo = {"valores": {"atd_pix_chave": "chave-nova-teste"}}
    r = dono_com_senha.post("/api/atendimento/config", json=corpo)
    assert r.status_code == 403 and r.get_json()["senha"] is True
    r = dono_com_senha.post("/api/atendimento/config", json={**corpo, "senha": "errada"})
    assert r.status_code == 403
    assert _valor("atd_pix_chave") == antes

    r = dono_com_senha.post("/api/atendimento/config", json={**corpo, "senha": SENHA_DONO})
    assert r.get_json()["ok"]
    assert _valor("atd_pix_chave") == "chave-nova-teste"
    # Mandar o mesmo Pix de novo (nada muda) não pede senha.
    assert dono_com_senha.post("/api/atendimento/config", json=corpo).get_json()["ok"]


def test_senha_errada_demais_bloqueia(dono_com_senha, restaura_config):
    corpo = {"valores": {"atd_pix_chave": "x"}, "senha": "errada"}
    for _ in range(app_module.LOGIN_MAX_ATTEMPTS):
        dono_com_senha.post("/api/atendimento/config", json=corpo)
    r = dono_com_senha.post("/api/atendimento/config", json={**corpo, "senha": SENHA_DONO})
    assert r.status_code == 429


def test_audit_log_nunca_guarda_senha(dono_com_senha, restaura_config):
    dono_com_senha.post("/api/atendimento/config",
                        json={"valores": {"atd_pix_chave": "y"}, "senha": SENHA_DONO})
    db = _db()
    detalhes = [r["detail"] for r in db.execute(
        "SELECT detail FROM audit_log WHERE id > ?", (restaura_config["ultimo_audit"],))]
    db.execute("DELETE FROM audit_log WHERE id > ?", (restaura_config["ultimo_audit"],))
    db.commit()
    db.close()
    assert detalhes and not any(SENHA_DONO in (d or "") for d in detalhes)


def test_ajustes_e_historico_so_do_dono(client, staff):
    _logar(client, staff["atd_teste_sim"])
    assert client.get("/api/atendimento/config").get_json()["ajustes"] is None
    assert client.get("/api/atendimento/historico").status_code == 403
    assert client.get("/api/atendimento/exportar").status_code == 403
    assert client.post("/api/atendimento/importar", json={"codigo": "ATD1:"}).status_code == 403


def test_config_do_dono_traz_valores_crus(owner_client, restaura_config):
    owner_client.post("/api/atendimento/config", json={"valores": {"atd_nome": ""}})
    aj = owner_client.get("/api/atendimento/config").get_json()["ajustes"]
    assert aj["valores"]["atd_nome"] == ""          # vazio continua vazio
    assert aj["nome_da_loja"]
    assert aj["textos_padrao"]["resumo"] == atendimento.TEXTOS_PADRAO["atd_tpl_resumo"]


def test_copiar_configuracao_nao_leva_pix(owner_client, restaura_config):
    codigo = owner_client.get("/api/atendimento/exportar").get_json()["codigo"]
    dados = json.loads(base64.b64decode(codigo[len("ATD1:"):]))
    assert not any(k.startswith(("atd_pix", "atd_nome", "atd_site")) for k in dados["config"])
    assert "atd_tpl_resumo" in dados["config"] and "atd_prazo" in dados["config"]


def test_colar_configuracao_previa_e_aplica(owner_client, restaura_config):
    pix_antes = _valor("atd_pix_chave")
    codigo = _codigo({
        "config": {"atd_prazo": "até 40 minutos", "atd_pix_chave": "PIX-DE-OUTRA-LOJA"},
        "motoboys": [{"nome": "Motoboy Colado", "telefone": "98 90000-1111", "ativo": 1}],
    })
    previa = owner_client.post("/api/atendimento/importar", json={"codigo": codigo}).get_json()
    assert previa["previa"] is True
    assert previa["config"] == ["atd_prazo"]               # o Pix do código é ignorado
    assert previa["motoboys_novos"] == ["Motoboy Colado"]
    assert _valor("atd_prazo") != "até 40 minutos"         # a prévia não grava

    r = owner_client.post("/api/atendimento/importar", json={"codigo": codigo, "aplicar": True}).get_json()
    assert r["ok"] and r["previa"] is False
    assert _valor("atd_prazo") == "até 40 minutos"
    assert _valor("atd_pix_chave") == pix_antes
    nomes = [m["nome"] for m in owner_client.get("/api/atendimento/config").get_json()["motoboys"]]
    assert "Motoboy Colado" in nomes
    # Colar de novo não duplica o motoboy nem muda nada.
    de_novo = owner_client.post("/api/atendimento/importar", json={"codigo": codigo}).get_json()
    assert de_novo["motoboys_novos"] == [] and de_novo["config"] == []


@pytest.mark.parametrize("codigo", [
    "", "oi", "ATD1:%%%", "ATD1:e30=",
    _codigo({"config": {}, "motoboys": [{"nome": ""}]}),
])
def test_colar_codigo_invalido(owner_client, codigo):
    r = owner_client.post("/api/atendimento/importar", json={"codigo": codigo, "aplicar": True})
    assert r.status_code == 400


def test_admin_tem_permissao_de_atendimento(owner_client, staff):
    html = owner_client.get("/admin").get_data(as_text=True)
    assert "'can_atendimento'" in html and 'id="newEmpAtendimento"' in html
    r = owner_client.post(f"/api/user/{staff['atd_teste_nao']}", json={"can_atendimento": True})
    assert r.get_json()["ok"]
    db = _db()
    pode = db.execute("SELECT can_atendimento FROM users WHERE id = ?", (staff["atd_teste_nao"],)).fetchone()[0]
    db.close()
    assert pode == 1


# ---------------------------------------------------------------------------
# Imagem dos sabores (Etapa 5)
# ---------------------------------------------------------------------------
def test_catalogo_traz_foto_e_cor_do_sabor(owner_client, produto):
    db = _db()
    db.execute("UPDATE vape_models SET image_url = '/static/uploads/foto-teste.jpg' WHERE id = ?", (produto["model"],))
    db.execute("UPDATE products SET color = '#a855f7' WHERE id = ?", (produto["ok"],))
    db.commit()
    db.close()
    m = next(x for x in owner_client.get("/api/atendimento/catalogo").get_json()["modelos"] if x["id"] == produto["model"])
    assert m["foto"] == "/static/uploads/foto-teste.jpg"
    cores = {s["id"]: s["cor"] for s in m["sabores"]}
    assert cores[produto["ok"]] == "#a855f7"
    assert cores[produto["esgotado"]] == ""


def test_imagem_usa_o_logo_da_propria_loja(owner_client):
    """Cada loja (serviço) manda o logo do cabeçalho do site dela; sem logo
    enviado no admin, o padrão do site."""
    antes = _valor("logo_main_url")
    try:
        db = _db()
        db.execute("UPDATE site_config SET value = '' WHERE key = 'logo_main_url'")
        db.commit()
        db.close()
        assert owner_client.get("/api/atendimento/config").get_json()["loja"]["logo"] == "/static/logo.png"
        db = _db()
        db.execute("UPDATE site_config SET value = '/static/uploads/logo-vapor.png' WHERE key = 'logo_main_url'")
        db.commit()
        db.close()
        assert owner_client.get("/api/atendimento/config").get_json()["loja"]["logo"] == "/static/uploads/logo-vapor.png"
    finally:
        db = _db()
        db.execute("UPDATE site_config SET value = ? WHERE key = 'logo_main_url'", (antes or "",))
        db.commit()
        db.close()


def test_so_o_painel_e_o_login_abrem_na_extensao(client):
    ext = "chrome-extension://" + app_module.ATD_EXTENSAO_ID
    for rota in ("/atendimento", "/admin/login"):
        r = client.get(rota)
        assert f"frame-ancestors 'self' {ext};" in r.headers["Content-Security-Policy"], rota
        assert "X-Frame-Options" not in r.headers, rota
    for rota in ("/", "/admin", "/api/atendimento/catalogo"):
        r = client.get(rota)
        assert "frame-ancestors 'none';" in r.headers["Content-Security-Policy"], rota
        assert r.headers["X-Frame-Options"] == "DENY", rota


def test_manifest_da_extensao_bate_com_o_servidor():
    """O ID da extensão vem da chave pública do manifest; o servidor só deixa
    o painel abrir dentro desse ID. As permissões cobrem as 3 lojas do
    lojas.js, e nada além delas."""
    import hashlib
    pasta = Path(app_module.__file__).parent / "extensao"
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    der = base64.b64decode(man["key"])
    eid = "".join("abcdefghijklmnop"[int(c, 16)] for c in hashlib.sha256(der).hexdigest()[:32])
    assert eid == app_module.ATD_EXTENSAO_ID
    urls = re.findall(r'url: "(https://[^"]+)"', (pasta / "lojas.js").read_text(encoding="utf-8"))
    assert sorted(u + "/*" for u in urls) == sorted(man["host_permissions"])
    assert len(urls) == 3
    assert set(man["permissions"]) == {"sidePanel", "storage"}
    # No WhatsApp, só o script que lê o nome da conversa aberta.
    assert man["content_scripts"] == [{"matches": ["https://web.whatsapp.com/*"], "js": ["whatsapp.js"], "run_at": "document_idle"}]
    wa = (pasta / "whatsapp.js").read_text(encoding="utf-8")
    assert ".click(" not in wa and "dispatchEvent" not in wa and "innerHTML" not in wa


def test_painel_so_aceita_aviso_da_extensao(client, staff):
    _logar(client, staff["atd_teste_sim"])
    html = client.get("/atendimento").get_data(as_text=True)
    assert f'extensao: "chrome-extension://{app_module.ATD_EXTENSAO_ID}"' in html
    js = (Path(app_module.__file__).parent / "static" / "js" / "atendimento.js").read_text(encoding="utf-8")
    assert "e.origin !== CFG.extensao" in js and "e.source !== window.parent" in js


def test_confere_dono_para_trocar_a_loja(dono_com_senha, client, restaura_config):
    anon = app_module.app.test_client()
    assert anon.post("/api/atendimento/confere-dono", json={"senha": "errada"}).status_code == 403
    assert anon.post("/api/atendimento/confere-dono", json={}).status_code == 403
    r = anon.post("/api/atendimento/confere-dono", json={"senha": SENHA_DONO})
    assert r.get_json() == {"ok": True}
    with anon.session_transaction() as sess:
        assert "user_id" not in sess                 # não loga ninguém


def test_confere_dono_bloqueia_apos_erros(dono_com_senha, restaura_config):
    anon = app_module.app.test_client()
    for _ in range(app_module.LOGIN_MAX_ATTEMPTS):
        anon.post("/api/atendimento/confere-dono", json={"senha": "errada"})
    assert anon.post("/api/atendimento/confere-dono", json={"senha": SENHA_DONO}).status_code == 429


def test_pagina_carrega_a_imagem_dos_sabores(client, staff):
    _logar(client, staff["atd_teste_sim"])
    html = client.get("/atendimento").get_data(as_text=True)
    assert "js/atendimento-imagem.js" in html and 'id="imgFundo"' in html


# ---------------------------------------------------------------------------
# Local da retirada (botão "Retirada" do Catálogo e último passo da retirada)
# ---------------------------------------------------------------------------
# Link e referência REAIS enviados pelo Murilo em 16/11/2026.
MAPA_RETIRADA = "https://maps.google.com/maps?q=-2.5010952949523926%2C-44.24929428100586&z=17&hl=pt-BR"
LOCAL_RETIRADA = "Prédio Cinza Athenas Office - ao lado do Nunes Auto Estética"


def test_local_da_retirada_grava_e_chega_no_painel(owner_client, restaura_config):
    r = owner_client.post("/api/atendimento/config", json={"valores": {
        "atd_retirada_local": LOCAL_RETIRADA, "atd_retirada_mapa": MAPA_RETIRADA}})
    assert r.get_json()["ok"]
    cfg = owner_client.get("/api/atendimento/config").get_json()
    assert cfg["loja"]["retirada_local"] == LOCAL_RETIRADA
    assert cfg["loja"]["retirada_mapa"] == MAPA_RETIRADA
    assert "{local}" in cfg["textos"]["retirada"] and "{mapa}" in cfg["textos"]["retirada"]


@pytest.mark.parametrize("mapa", ["Rua das Flores 123", "maps.google.com/x", "javascript:alert(1)"])
def test_mapa_da_retirada_so_aceita_link(owner_client, restaura_config, mapa):
    r = owner_client.post("/api/atendimento/config", json={"valores": {"atd_retirada_mapa": mapa}})
    assert r.status_code == 400
    assert "https://" in r.get_json()["error"]


def test_copiar_configuracao_nao_leva_local_da_retirada(owner_client, restaura_config):
    owner_client.post("/api/atendimento/config", json={"valores": {"atd_retirada_local": LOCAL_RETIRADA}})
    codigo = owner_client.get("/api/atendimento/exportar").get_json()["codigo"]
    dados = json.loads(base64.b64decode(codigo[len("ATD1:"):]))
    assert not any(k.startswith("atd_retirada") for k in dados["config"])
    assert "atd_tpl_retirada" in dados["config"]  # o TEXTO vai; o local não
