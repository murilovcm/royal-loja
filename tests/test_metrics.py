"""Contador de visitas e aba Métricas.

Diferente dos outros testes, estes rodam num banco TEMPORÁRIO: as métricas
gravam a cada request e não devem sujar o royal.db local.
"""
import sqlite3
import time
from datetime import date, timedelta

import pytest

import app as app_module

CEL = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 Safari/604.1"
PC = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
BOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
WA_PREVIEW = "WhatsApp/2.23.20.0 A"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "metrics.db")
    monkeypatch.setattr(app_module, "DB_PATH", path)
    with app_module.app.app_context():
        app_module.init_db()
    return path


@pytest.fixture
def client(db_path):
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def _login(client, db_path, role="owner"):
    db = sqlite3.connect(db_path)
    if role == "owner":
        uid = db.execute("SELECT id FROM users WHERE role = 'owner' LIMIT 1").fetchone()[0]
    else:
        uid = db.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES ('func', 'x', 'staff', ?)",
            (time.time(),),
        ).lastrowid
        db.commit()
    db.close()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["csrf_token"] = "tok"
    client.environ_base["HTTP_X_ADMIN_TOKEN"] = "tok"
    return client


def _visit(client, path="/api/m/hit", ua=CEL, ip="10.0.0.1"):
    r = client.post(path, headers={"User-Agent": ua}, environ_base={"REMOTE_ADDR": ip})
    assert r.status_code == 204


def _daily(db_path):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute("SELECT * FROM metrics_daily")]
    db.close()
    return rows


def test_same_visitor_counts_once_but_every_page(client, db_path):
    _visit(client)
    _visit(client)
    _visit(client, ua=PC, ip="10.0.0.2")
    [d] = _daily(db_path)
    assert d["visitors"] == 2
    assert d["pageviews"] == 3
    assert (d["mobile"], d["desktop"]) == (1, 1)


def test_bots_and_link_previews_are_ignored(client, db_path):
    _visit(client, ua=BOT)
    _visit(client, ua=WA_PREVIEW)
    _visit(client, ua="")
    assert _daily(db_path) == []


def test_logged_in_admin_is_not_counted(client, db_path):
    _login(client, db_path)
    _visit(client)
    _visit(client, path="/api/m/ping")
    assert _daily(db_path) == []
    assert client.get("/api/metrics/online").get_json()["online"] == 0


def test_whatsapp_click_counts_once_per_visitor_per_day(client, db_path):
    _visit(client)
    _visit(client, path="/api/m/wa")
    _visit(client, path="/api/m/wa")
    [d] = _daily(db_path)
    assert d["wa_clicks"] == 1
    assert d["visitors"] == 1
    assert d["pageviews"] == 1  # o clique no WhatsApp não é página vista


def test_pageviews_are_capped_per_visitor(client, db_path, monkeypatch):
    monkeypatch.setattr(app_module, "METRICS_PAGEVIEW_CAP", 3)
    for _ in range(5):
        _visit(client)
    assert _daily(db_path)[0]["pageviews"] == 3


def test_old_visitor_codes_are_deleted_next_day(client, db_path, monkeypatch):
    _visit(client)
    amanha = app_module._metrics_today() + timedelta(days=1)
    monkeypatch.setattr(app_module, "_metrics_today", lambda: amanha)
    _visit(client)
    db = sqlite3.connect(db_path)
    days = [r[0] for r in db.execute("SELECT DISTINCT day FROM metrics_seen")]
    db.close()
    assert days == [amanha.isoformat()]
    # O mesmo aparelho volta a contar como visitante no dia seguinte.
    assert sorted(d["visitors"] for d in _daily(db_path)) == [1, 1]


def test_online_now_counts_recent_pings_only(client, db_path):
    _visit(client, path="/api/m/ping", ip="10.0.0.1")
    _visit(client, path="/api/m/ping", ip="10.0.0.2")
    _visit(client, path="/api/m/ping", ip="10.0.0.2")
    db = sqlite3.connect(db_path)
    db.execute("INSERT INTO metrics_online (vid, last_seen) VALUES ('sumiu', ?)", (time.time() - 300,))
    db.commit()
    db.close()
    _login(client, db_path)
    assert client.get("/api/metrics/online").get_json()["online"] == 2


def test_summary_period_previous_and_series(client, db_path, monkeypatch):
    hoje = date(2026, 11, 13)
    monkeypatch.setattr(app_module, "_metrics_today", lambda: hoje)
    db = sqlite3.connect(db_path)
    ins = "INSERT INTO metrics_daily (day, visitors, pageviews, wa_clicks, mobile, desktop) VALUES (?, ?, ?, ?, ?, ?)"
    db.execute(ins, (hoje.isoformat(), 10, 25, 2, 8, 2))
    db.execute(ins, ((hoje - timedelta(days=6)).isoformat(), 5, 9, 1, 4, 1))
    db.execute(ins, ((hoje - timedelta(days=7)).isoformat(), 4, 6, 0, 2, 2))  # já é o período anterior
    db.commit()
    db.close()
    _login(client, db_path)

    d = client.get("/api/metrics?days=7").get_json()
    assert d["current"] == {"visitors": 15, "pageviews": 34, "wa_clicks": 3, "mobile": 12, "desktop": 3}
    assert d["previous"]["visitors"] == 4
    assert len(d["series"]) == 7 and d["series"][-1] == {"day": "2026-11-13", "visitors": 10}

    hoje_only = client.get("/api/metrics?days=1").get_json()
    assert hoje_only["current"]["visitors"] == 10
    assert len(hoje_only["series"]) == 7  # o gráfico de "Hoje" mostra a semana

    ano = client.get("/api/metrics?days=365").get_json()
    assert ano["series_kind"] == "week" and len(ano["series"]) == 52
    assert ano["series"][-1]["visitors"] == 15  # última semana = hoje-6 .. hoje
    assert ano["series"][-2]["visitors"] == 4


def test_custom_range(client, db_path, monkeypatch):
    hoje = date(2026, 11, 13)
    monkeypatch.setattr(app_module, "_metrics_today", lambda: hoje)
    db = sqlite3.connect(db_path)
    ins = "INSERT INTO metrics_daily (day, visitors, pageviews, wa_clicks, mobile, desktop) VALUES (?, ?, 0, 0, 0, 0)"
    for d, v in (("2026-11-01", 3), ("2026-11-05", 7), ("2026-11-06", 100), ("2026-10-30", 2)):
        db.execute(ins, (d, v))
    db.commit()
    db.close()
    _login(client, db_path)

    d = client.get("/api/metrics?from=2026-11-01&to=2026-11-05").get_json()
    assert d["custom"] and d["days"] == 5
    assert d["current"]["visitors"] == 10          # 06/11 fica de fora
    assert d["previous"]["visitors"] == 2          # 27/10 a 31/10
    assert [s["day"] for s in d["series"]][0] == "2026-11-01" and len(d["series"]) == 5

    um_dia = client.get("/api/metrics?from=2026-11-05&to=2026-11-05").get_json()
    assert um_dia["current"]["visitors"] == 7
    assert um_dia["series"][-1] == {"day": "2026-11-05", "visitors": 7}

    longo = client.get("/api/metrics?from=2026-01-01&to=2026-11-13").get_json()
    assert longo["series_kind"] == "week"
    assert sum(s["visitors"] for s in longo["series"]) == longo["current"]["visitors"] == 112
    assert longo["series"][0]["day"] == "2026-01-01"


@pytest.mark.parametrize("qs", [
    "from=2026-11-10&to=2026-11-01",   # invertido
    "from=2026-11-01&to=2026-11-14",   # depois de hoje
    "from=2020-01-01&to=2026-11-13",   # mais de 3 anos
    "from=ontem&to=2026-11-13",        # data inválida
])
def test_custom_range_rejects_bad_dates(client, db_path, monkeypatch, qs):
    monkeypatch.setattr(app_module, "_metrics_today", lambda: date(2026, 11, 13))
    _login(client, db_path)
    assert client.get("/api/metrics?" + qs).status_code == 400


def test_summary_rejects_unknown_period(client, db_path):
    _login(client, db_path)
    assert client.get("/api/metrics?days=12").status_code == 400


def test_metrics_are_owner_only(client, db_path):
    assert client.get("/api/metrics").status_code == 401
    _login(client, db_path, role="staff")
    assert client.get("/api/metrics").status_code == 403
    assert client.get("/api/metrics/online").status_code == 403


def test_metrics_reads_do_not_fill_audit_log(client, db_path):
    _login(client, db_path)
    client.get("/api/metrics")
    client.get("/api/metrics/online")
    db = sqlite3.connect(db_path)
    n = db.execute("SELECT COUNT(*) FROM audit_log WHERE action LIKE '%metrics%'").fetchone()[0]
    db.close()
    assert n == 0


def test_admin_shows_metrics_tab_only_to_owner(client, db_path):
    _login(client, db_path)
    assert b'data-tab="metrics"' in client.get("/admin").data
    client2 = app_module.app.test_client()
    _login(client2, db_path, role="staff")
    assert b'data-tab="metrics"' not in client2.get("/admin").data


def test_store_page_loads_metrics_script(client):
    assert b"js/metrics.js" in client.get("/", headers={"User-Agent": CEL}).data
