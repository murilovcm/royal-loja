"""Testes da ordem manual do catálogo (POST /api/catalog/order e catalog_pos).

Mesmo padrão dos outros testes de API do projeto: Flask test client contra o
royal.db real. Por isso todo teste guarda a ordem original e a devolve no
finally — nenhum teste pode deixar a vitrine reordenada.
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


def _conn():
    db = sqlite3.connect(app_module.DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def _ordem_atual():
    """Ids dos cards do catálogo, na ordem em que a loja os mostra."""
    db = _conn()
    ids = [r["id"] for r in db.execute(
        "SELECT id FROM vape_models WHERE parent_id IS NULL AND active = 1 "
        "ORDER BY catalog_pos, id DESC"
    ).fetchall()]
    db.close()
    return ids


@pytest.fixture
def ordem_preservada():
    """Devolve o catalog_pos de todos os modelos ao valor original."""
    db = _conn()
    antes = [(r["id"], r["catalog_pos"], r["active"]) for r in db.execute(
        "SELECT id, catalog_pos, active FROM vape_models"
    ).fetchall()]
    db.close()
    yield
    db = _conn()
    for mid, pos, ativo in antes:
        db.execute(
            "UPDATE vape_models SET catalog_pos = ?, active = ? WHERE id = ?",
            (pos, ativo, mid),
        )
    db.commit()
    db.close()


def test_reordenar_exige_login(client):
    resp = client.post("/api/catalog/order", json={"ids": _ordem_atual()})
    assert resp.status_code == 401


def test_ordem_enviada_vira_a_ordem_da_vitrine(admin_client, ordem_preservada):
    invertida = list(reversed(_ordem_atual()))
    resp = admin_client.post("/api/catalog/order", json={"ids": invertida})
    assert resp.status_code == 200 and resp.get_json()["ok"] is True

    # O que a loja renderiza tem que seguir exatamente a lista enviada.
    with app_module.app.app_context():
        assert [m["id"] for m in app_module.build_catalog()] == invertida

    # E a coluna fica renumerada em 0..n, sem buraco nem empate.
    db = _conn()
    posicoes = [r["catalog_pos"] for r in db.execute(
        "SELECT catalog_pos FROM vape_models WHERE id IN (%s) ORDER BY catalog_pos"
        % ",".join("?" * len(invertida)), invertida
    ).fetchall()]
    db.close()
    assert posicoes == list(range(len(invertida)))


def test_estrela_nao_manda_mais_na_posicao(admin_client, ordem_preservada):
    """A ★ virou só selo: um produto marcado como Mais Vendido pode ficar por
    último se o lojista quiser, o que a regra antiga (is_best_seller DESC)
    tornava impossível."""
    db = _conn()
    estrelado = db.execute(
        "SELECT id FROM vape_models WHERE parent_id IS NULL AND active = 1 "
        "AND is_best_seller = 1 LIMIT 1"
    ).fetchone()
    db.close()
    if not estrelado:
        pytest.skip("catálogo sem nenhum produto marcado como Mais Vendido")

    ids = [i for i in _ordem_atual() if i != estrelado["id"]] + [estrelado["id"]]
    assert admin_client.post("/api/catalog/order", json={"ids": ids}).status_code == 200
    with app_module.app.app_context():
        assert app_module.build_catalog()[-1]["id"] == estrelado["id"]


def test_lista_desatualizada_e_recusada(admin_client, ordem_preservada):
    """Faltando um ativo, gravar apagaria a posição de quem ficou de fora."""
    ids = _ordem_atual()
    antes = ids[:]
    resp = admin_client.post("/api/catalog/order", json={"ids": ids[:-1]})
    assert resp.status_code == 409
    assert "recarregue" in resp.get_json()["error"]
    assert _ordem_atual() == antes  # nada foi gravado


def test_id_invalido_ou_repetido_nao_corrompe(admin_client, ordem_preservada):
    ids = _ordem_atual()
    # Lixo e repetição são descartados; sobra menos que o catálogo -> 409.
    resp = admin_client.post(
        "/api/catalog/order", json={"ids": ids + [999999, "abc", ids[0]]}
    )
    assert resp.status_code == 200
    with app_module.app.app_context():
        assert [m["id"] for m in app_module.build_catalog()] == ids


def test_modelo_novo_entra_no_topo(admin_client, ordem_preservada):
    db = _conn()
    marca = db.execute("SELECT id FROM brands LIMIT 1").fetchone()["id"]
    db.close()
    resp = admin_client.post(
        "/api/model", json={"brand_id": marca, "name": "ZZ Teste Ordem", "puff_count": "1"}
    )
    novo = resp.get_json()["id"]
    try:
        with app_module.app.app_context():
            assert app_module.build_catalog()[0]["id"] == novo
    finally:
        admin_client.delete("/api/model/%d" % novo)


def test_religado_volta_pelo_topo(admin_client, ordem_preservada):
    """Esgotado some da lista de ordem e seu catalog_pos envelhece; ao voltar
    ao site ele precisa de posição nova, senão cairia num ponto imprevisível."""
    ultimo = _ordem_atual()[-1]
    assert admin_client.post("/api/model/%d" % ultimo, json={"active": 0}).status_code == 200
    with app_module.app.app_context():
        assert ultimo not in [m["id"] for m in app_module.build_catalog()]

    assert admin_client.post("/api/model/%d" % ultimo, json={"active": 1}).status_code == 200
    with app_module.app.app_context():
        assert app_module.build_catalog()[0]["id"] == ultimo


def test_salvar_sem_mexer_no_active(admin_client, ordem_preservada):
    """Editar outro campo não pode reposicionar o card (só o 0 -> 1 reposiciona)."""
    ids = _ordem_atual()
    alvo = ids[-1]
    assert admin_client.post("/api/model/%d" % alvo, json={"active": 1}).status_code == 200
    assert _ordem_atual() == ids
