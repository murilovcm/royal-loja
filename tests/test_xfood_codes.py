"""Ligação sabor do site <-> código do xFood (tabela product_xfood_codes).

Cobre o campo "Códigos xFood" (cadastro e edição do sabor pela API do painel),
a regra "um código pertence a um só sabor" e o aviso de sabores ATIVOS sem
código no admin. Mesmo padrão dos outros testes de API: Flask test client
contra o royal.db real, cada teste limpando o que cria.
"""
import sqlite3

import pytest

import app as app_module


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
def catalogo():
    """Marca com um modelo ativo (2 sabores) e um inativo (1 sabor)."""
    db = sqlite3.connect(app_module.DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    bid = db.execute("INSERT INTO brands (name) VALUES ('MarcaTesteXfood')").lastrowid
    ativo = db.execute("INSERT INTO vape_models (brand_id, name, active) VALUES (?, 'XF Ativo', 1)", (bid,)).lastrowid
    inativo = db.execute("INSERT INTO vape_models (brand_id, name, active) VALUES (?, 'XF Inativo', 0)", (bid,)).lastrowid
    s1 = db.execute("INSERT INTO products (model_id, name, price) VALUES (?, 'XF Uva', 10)", (ativo,)).lastrowid
    s2 = db.execute("INSERT INTO products (model_id, name, price) VALUES (?, 'XF Menta', 10)", (ativo,)).lastrowid
    s3 = db.execute("INSERT INTO products (model_id, name, price) VALUES (?, 'XF Kiwi', 10)", (inativo,)).lastrowid
    db.commit()
    db.close()
    yield {"brand": bid, "ativo": ativo, "inativo": inativo, "s1": s1, "s2": s2, "s3": s3}
    db = sqlite3.connect(app_module.DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("DELETE FROM brands WHERE id = ?", (bid,))  # CASCADE até os códigos
    db.commit()
    db.close()


def _codigos(pid):
    db = sqlite3.connect(app_module.DB_PATH)
    try:
        return [r[0] for r in db.execute(
            "SELECT xfood_codigo FROM product_xfood_codes WHERE product_id = ? ORDER BY id", (pid,))]
    finally:
        db.close()


def _sem_codigo_ids():
    with app_module.app.app_context():
        return {s["id"] for s in app_module.sabores_ativos_sem_xfood(app_module.get_db())}


def test_parse_separa_por_virgula_e_tira_repetidos():
    assert app_module.parse_xfood_codigos(" 0500, 0602 ;0500  ") == ["0500", "0602"]
    assert app_module.parse_xfood_codigos("") == []
    # zero à esquerda importa: o código é texto
    assert app_module.parse_xfood_codigos("0500") != app_module.parse_xfood_codigos("500")


def test_editar_sabor_grava_e_troca_codigos(admin_client, catalogo):
    r = admin_client.post(f"/api/product/{catalogo['s1']}", json={"xfood_codigos": "TXF-1, TXF-2"})
    assert r.get_json() == {"ok": True, "xfood_codigos": "TXF-1, TXF-2"}
    assert _codigos(catalogo["s1"]) == ["TXF-1", "TXF-2"]
    # trocar substitui (não acumula) e vazio remove tudo
    admin_client.post(f"/api/product/{catalogo['s1']}", json={"xfood_codigos": "TXF-2"})
    assert _codigos(catalogo["s1"]) == ["TXF-2"]
    admin_client.post(f"/api/product/{catalogo['s1']}", json={"xfood_codigos": ""})
    assert _codigos(catalogo["s1"]) == []


def test_codigo_de_outro_sabor_e_recusado(admin_client, catalogo):
    admin_client.post(f"/api/product/{catalogo['s1']}", json={"xfood_codigos": "TXF-9"})
    r = admin_client.post(f"/api/product/{catalogo['s2']}", json={"xfood_codigos": "TXF-8, TXF-9"})
    assert r.status_code == 400
    assert "TXF-9" in r.get_json()["error"]
    # nada foi gravado no segundo sabor, nem o código livre
    assert _codigos(catalogo["s2"]) == []
    assert _codigos(catalogo["s1"]) == ["TXF-9"]


def test_editar_outros_campos_nao_mexe_nos_codigos(admin_client, catalogo):
    admin_client.post(f"/api/product/{catalogo['s1']}", json={"xfood_codigos": "TXF-5"})
    admin_client.post(f"/api/product/{catalogo['s1']}", json={"price": 12})
    assert _codigos(catalogo["s1"]) == ["TXF-5"]


def test_cadastrar_sabor_com_codigo(admin_client, catalogo):
    r = admin_client.post("/api/product", json={
        "model_id": catalogo["ativo"], "name": "XF Novo", "price": 10, "xfood_codigos": "TXF-20",
    })
    assert r.get_json()["ok"]
    assert _codigos(r.get_json()["id"]) == ["TXF-20"]


def test_cadastrar_sabor_com_codigo_ocupado_desfaz_o_cadastro(admin_client, catalogo):
    admin_client.post(f"/api/product/{catalogo['s1']}", json={"xfood_codigos": "TXF-30"})
    r = admin_client.post("/api/product", json={
        "model_id": catalogo["ativo"], "name": "XF Duplicado", "price": 10, "xfood_codigos": "TXF-30",
    })
    assert r.status_code == 400
    db = sqlite3.connect(app_module.DB_PATH)
    assert db.execute("SELECT 1 FROM products WHERE name = 'XF Duplicado'").fetchone() is None
    db.close()


def test_aviso_lista_so_sabores_ativos_sem_codigo(admin_client, catalogo):
    sem = _sem_codigo_ids()
    assert {catalogo["s1"], catalogo["s2"]} <= sem
    assert catalogo["s3"] not in sem          # modelo inativo não entra
    admin_client.post(f"/api/product/{catalogo['s1']}", json={"xfood_codigos": "TXF-40"})
    sem = _sem_codigo_ids()
    assert catalogo["s1"] not in sem and catalogo["s2"] in sem


def test_admin_mostra_campo_e_aviso(admin_client, catalogo):
    admin_client.post(f"/api/product/{catalogo['s1']}", json={"xfood_codigos": "TXF-50, TXF-51"})
    html = admin_client.get("/admin").get_data(as_text=True)
    assert 'id="xfAlert"' in html
    assert f'<li data-fid="{catalogo["s2"]}">' in html       # sem código: no aviso
    assert f'<li data-fid="{catalogo["s1"]}">' not in html   # com código: fora
    assert 'value="TXF-50, TXF-51"' in html                   # campo preenchido


def test_excluir_sabor_libera_os_codigos(admin_client, catalogo):
    admin_client.post(f"/api/product/{catalogo['s2']}", json={"xfood_codigos": "TXF-60"})
    admin_client.delete(f"/api/product/{catalogo['s2']}")
    r = admin_client.post(f"/api/product/{catalogo['s1']}", json={"xfood_codigos": "TXF-60"})
    assert r.get_json()["ok"]
