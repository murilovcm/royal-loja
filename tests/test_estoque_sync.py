"""Sincronização do estoque com o xFood (POST /api/estoque/sync) e a rota
auxiliar GET /api/estoque/ligacoes.

Mesmo padrão dos outros testes de API: Flask test client contra o royal.db
real, cada teste limpando o que cria. As travas olham o banco inteiro; o
royal.db de desenvolvimento não tem códigos xFood fora destes fixtures.
"""
import sqlite3

import pytest

import app as app_module

TOKEN = "token-de-teste-estoque"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ESTOQUE_SYNC_TOKEN", TOKEN)
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


def _db():
    db = sqlite3.connect(app_module.DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


@pytest.fixture
def sabores():
    """Modelo ativo com 10 sabores ligados, cada um com o código ES-<n>.
    O sabor 0 tem um segundo código (ES-0B). 10 ligados = trava em 2."""
    db = _db()
    bid = db.execute("INSERT INTO brands (name) VALUES ('MarcaTesteEstoque')").lastrowid
    mid = db.execute(
        "INSERT INTO vape_models (brand_id, name, active) VALUES (?, 'ES Modelo', 1)", (bid,)
    ).lastrowid
    ids = []
    for n in range(10):
        pid = db.execute(
            "INSERT INTO products (model_id, name, price, is_in_stock) VALUES (?, ?, 10, 1)",
            (mid, f"ES Sabor {n}"),
        ).lastrowid
        db.execute("INSERT INTO product_xfood_codes (product_id, xfood_codigo) VALUES (?, ?)", (pid, f"ES-{n}"))
        ids.append(pid)
    db.execute("INSERT INTO product_xfood_codes (product_id, xfood_codigo) VALUES (?, 'ES-0B')", (ids[0],))
    db.commit()
    db.close()
    yield {"brand": bid, "model": mid, "ids": ids}
    db = _db()
    db.execute(f"DELETE FROM estoque_sync_log WHERE product_id IN ({','.join('?' * len(ids))})", ids)
    db.execute("DELETE FROM brands WHERE id = ?", (bid,))  # CASCADE até os códigos
    db.commit()
    db.close()


def _corpo(saldos, simular=False, enchimento=300):
    """Corpo com os saldos dados + itens de outros produtos do xFood para
    passar da trava dos 300 itens."""
    itens = [{"codigo": c, "saldo": s} for c, s in saldos.items()]
    itens += [{"codigo": f"OUTRO-{i}", "saldo": 1} for i in range(enchimento)]
    return {"lido_em": "2026-11-20T11:00:00-03:00", "simular": simular, "itens": itens}


def _todos_com_saldo(n=10):
    return {f"ES-{i}": 5 for i in range(n)}


def _sync(client, corpo, token=TOKEN):
    return client.post("/api/estoque/sync", json=corpo, headers={"Authorization": f"Bearer {token}"})


def _em_estoque(pid):
    db = _db()
    try:
        return db.execute("SELECT is_in_stock FROM products WHERE id = ?", (pid,)).fetchone()[0]
    finally:
        db.close()


def _log(pid):
    db = _db()
    try:
        return [dict(r) for r in db.execute(
            "SELECT de, para, saldo, simulado FROM estoque_sync_log WHERE product_id = ? ORDER BY id", (pid,))]
    finally:
        db.close()


# ---- Autenticação ----

def test_sem_token_configurado_responde_503(client, sabores, monkeypatch):
    monkeypatch.delenv("ESTOQUE_SYNC_TOKEN")
    saldos = _todos_com_saldo()
    saldos["ES-1"] = 0
    r = _sync(client, _corpo(saldos))
    assert r.status_code == 503
    assert _em_estoque(sabores["ids"][1]) == 1
    assert client.get("/api/estoque/ligacoes").status_code == 503


def test_token_errado_ou_ausente_responde_401(client, sabores):
    saldos = _todos_com_saldo()
    saldos["ES-1"] = 0
    assert _sync(client, _corpo(saldos), token="errado").status_code == 401
    assert client.post("/api/estoque/sync", json=_corpo(saldos)).status_code == 401
    assert _em_estoque(sabores["ids"][1]) == 1
    r = client.get("/api/estoque/ligacoes", headers={"Authorization": "Bearer errado"})
    assert r.status_code == 401
    assert TOKEN not in r.get_data(as_text=True)


# ---- Lógica ----

def test_desliga_sabor_sem_saldo_e_registra(client, sabores):
    pid = sabores["ids"][1]
    saldos = _todos_com_saldo()
    saldos["ES-1"] = 0
    r = _sync(client, _corpo(saldos))
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and d["simulado"] is False
    assert d["alterados"] == [{"product_id": pid, "sabor": "ES Modelo · ES Sabor 1", "de": 1, "para": 0, "saldo": 0}]
    assert _em_estoque(pid) == 0
    assert _log(pid) == [{"de": 1, "para": 0, "saldo": 0, "simulado": 0}]
    # De novo com o mesmo dado: nada muda nem é registrado.
    assert _sync(client, _corpo(saldos)).get_json()["alterados"] == []
    assert len(_log(pid)) == 1


def test_simular_nao_grava(client, sabores):
    pid = sabores["ids"][1]
    saldos = _todos_com_saldo()
    saldos["ES-1"] = 0
    d = _sync(client, _corpo(saldos, simular=True)).get_json()
    assert d["simulado"] is True
    assert [a["product_id"] for a in d["alterados"]] == [pid]
    assert _em_estoque(pid) == 1
    assert _log(pid) == [{"de": 1, "para": 0, "saldo": 0, "simulado": 1}]


def test_sabor_com_dois_codigos_soma_saldo(client, sabores):
    pid = sabores["ids"][0]
    saldos = _todos_com_saldo()
    # Um código zerado, o outro com saldo: continua ligado.
    saldos["ES-0"], saldos["ES-0B"] = 0, 3
    assert _sync(client, _corpo(saldos)).get_json()["alterados"] == []
    assert _em_estoque(pid) == 1
    # Os dois zerados: desliga, com o saldo somado.
    saldos["ES-0B"] = 0
    d = _sync(client, _corpo(saldos)).get_json()
    assert d["alterados"][0]["product_id"] == pid and d["alterados"][0]["saldo"] == 0
    assert _em_estoque(pid) == 0
    # Volta: um código com saldo religa.
    saldos["ES-0"] = 2
    d = _sync(client, _corpo(saldos)).get_json()
    assert d["alterados"] == [{"product_id": pid, "sabor": "ES Modelo · ES Sabor 0", "de": 0, "para": 1, "saldo": 2}]
    assert _em_estoque(pid) == 1


def test_sabor_manual_e_ignorado(client, sabores):
    pid = sabores["ids"][1]
    db = _db()
    db.execute("UPDATE products SET estoque_manual = 1 WHERE id = ?", (pid,))
    db.commit()
    db.close()
    saldos = _todos_com_saldo()
    saldos["ES-1"] = 0
    d = _sync(client, _corpo(saldos)).get_json()
    assert d["alterados"] == []
    assert d["ignorados_manual"] == 1
    assert _em_estoque(pid) == 1


def test_sabor_sem_dado_fica_como_esta(client, sabores):
    ligado, desligado = sabores["ids"][1], sabores["ids"][2]
    db = _db()
    db.execute("UPDATE products SET is_in_stock = 0 WHERE id = ?", (desligado,))
    db.commit()
    db.close()
    saldos = _todos_com_saldo()
    del saldos["ES-1"], saldos["ES-2"]
    d = _sync(client, _corpo(saldos)).get_json()
    assert d["sem_dado"] == 2
    assert d["alterados"] == []
    assert _em_estoque(ligado) == 1 and _em_estoque(desligado) == 0


def test_campo_estoque_manual_no_admin(admin_client, sabores):
    pid = sabores["ids"][3]
    assert admin_client.post(f"/api/product/{pid}", json={"estoque_manual": True}).get_json()["ok"]
    db = _db()
    assert db.execute("SELECT estoque_manual FROM products WHERE id = ?", (pid,)).fetchone()[0] == 1
    db.close()
    html = admin_client.get("/admin").get_data(as_text=True)
    assert f"toggleManual({pid}, this)" in html
    assert "Última sincronização do estoque" in html


# ---- Modo so_desligar ----

def _modo_log(pid):
    db = _db()
    try:
        return [r[0] for r in db.execute(
            "SELECT modo FROM estoque_sync_log WHERE product_id = ? ORDER BY id", (pid,))]
    finally:
        db.close()


def test_so_desligar_adia_ligar_e_desliga_esgotado(client, sabores):
    esgotado, disponivel = sabores["ids"][1], sabores["ids"][2]
    db = _db()
    db.execute("UPDATE products SET is_in_stock = 0 WHERE id = ?", (esgotado,))
    db.commit()
    db.close()
    saldos = _todos_com_saldo()
    saldos["ES-1"] = 4    # esgotado no site, com saldo: ligaria
    saldos["ES-2"] = 0    # disponível no site, sem saldo: desliga
    corpo = _corpo(saldos)
    corpo["so_desligar"] = True
    r = _sync(client, corpo)
    assert r.status_code == 200
    d = r.get_json()
    assert d["so_desligar"] is True
    assert d["alterados"] == [{"product_id": disponivel, "sabor": "ES Modelo · ES Sabor 2", "de": 1, "para": 0, "saldo": 0}]
    assert d["adiados_ligar"] == [{"product_id": esgotado, "sabor": "ES Modelo · ES Sabor 1", "saldo": 4}]
    assert _em_estoque(esgotado) == 0
    assert _em_estoque(disponivel) == 0
    assert _log(esgotado) == []
    assert _modo_log(disponivel) == ["so_desligar"]
    # Modo completo (padrão): agora religa e registra como completo.
    d = _sync(client, _corpo(saldos)).get_json()
    assert d["adiados_ligar"] == []
    assert [a["product_id"] for a in d["alterados"]] == [esgotado]
    assert _em_estoque(esgotado) == 1
    assert _modo_log(esgotado) == ["completo"]


def test_so_desligar_respeita_as_travas(client, sabores):
    saldos = _todos_com_saldo()
    saldos["ES-1"] = saldos["ES-2"] = saldos["ES-3"] = 0   # 30%
    corpo = _corpo(saldos)
    corpo["so_desligar"] = True
    assert _sync(client, corpo).status_code == 409
    corpo = _corpo({"ES-1": 0}, enchimento=10)
    corpo["so_desligar"] = True
    assert _sync(client, corpo).status_code == 409
    assert all(_em_estoque(p) == 1 for p in sabores["ids"])


# ---- Travas ----

def test_trava_corpo_com_menos_de_300_itens(client, sabores):
    pid = sabores["ids"][1]
    saldos = _todos_com_saldo()
    saldos["ES-1"] = 0
    r = _sync(client, _corpo(saldos, enchimento=50))
    assert r.status_code == 409
    assert r.get_json()["ok"] is False
    assert _em_estoque(pid) == 1
    assert _log(pid) == []


def test_trava_desligar_mais_de_20_por_cento(client, sabores):
    ids = sabores["ids"]
    saldos = _todos_com_saldo()
    saldos["ES-1"] = saldos["ES-2"] = saldos["ES-3"] = 0   # 3 de 10 = 30%
    r = _sync(client, _corpo(saldos))
    assert r.status_code == 409
    assert len(r.get_json()["alterados"]) == 3
    assert all(_em_estoque(p) == 1 for p in ids)
    assert all(_log(p) == [] for p in ids)
    # Também trava em modo simular (e não registra a simulação).
    assert _sync(client, _corpo(saldos, simular=True)).status_code == 409
    # 2 de 10 = 20%: no limite, passa.
    saldos["ES-3"] = 5
    assert _sync(client, _corpo(saldos)).status_code == 200
    assert _em_estoque(ids[1]) == 0 and _em_estoque(ids[2]) == 0


# ---- Sem cache: site e painel de atendimento já mostram o novo status ----

def test_catalogo_reflete_a_sincronizacao(admin_client, sabores):
    pid = sabores["ids"][1]

    def em_estoque_no_catalogo():
        cat = admin_client.get("/api/atendimento/catalogo").get_json()
        return next(s["em_estoque"] for m in cat["modelos"] for s in m["sabores"] if s["id"] == pid)

    assert em_estoque_no_catalogo() is True
    saldos = _todos_com_saldo()
    saldos["ES-1"] = 0
    assert _sync(admin_client, _corpo(saldos)).status_code == 200
    assert em_estoque_no_catalogo() is False
    with app_module.app.app_context():
        sabor = next(f for m in app_module.build_catalog() for f in m["flavors"] if f["id"] == pid)
    assert not sabor["is_in_stock"]


# ---- Rota auxiliar ----

def test_ligacoes_lista_codigos_por_sabor(client, sabores):
    r = client.get("/api/estoque/ligacoes", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    por_id = {x["product_id"]: x for x in r.get_json()}
    assert por_id[sabores["ids"][0]] == {
        "product_id": sabores["ids"][0], "modelo": "ES Modelo", "sabor": "ES Sabor 0", "codigos": ["ES-0", "ES-0B"],
    }
    assert por_id[sabores["ids"][5]]["codigos"] == ["ES-5"]
