import os
import sqlite3
import uuid
from functools import wraps
from flask import (
    Flask, g, render_template, request, jsonify,
    redirect, url_for, send_from_directory, session, abort
)
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps

from shipping import calculate_shipping, SPECIAL_ZONES, CONCENTRIC_ZONES

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Pasta de dados persistentes (banco + uploads).
# Na VPS, apontamos DATA_DIR para um volume do EasyPanel para que os dados
# sobrevivam aos deploys. No PC, usa a própria pasta do projeto.
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "royal.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}

# Todas as fotos de produto são padronizadas para este tamanho (quadrado)
# ao serem enviadas pelo painel admin, garantindo o mesmo enquadramento
# em qualquer card ou modal do site.
PRODUCT_IMAGE_SIZE = 800

# Telefone do dono da loja (formato internacional, apenas dígitos)
# CONFIRME: celular brasileiro tem 9 dígitos após o DDD (começa com 9).
WHATSAPP_PHONE = "5598985086085"

# Senha do painel admin.
# Na VPS, defina a variável de ambiente ADMIN_PASSWORD para não deixar a senha no código.
# Se não definir, usa a senha padrão abaixo (só para testes no seu PC).
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "386121")

# Textos padrão usados ao criar um novo bloco promocional (ex: "+ Novo Bloco").
PROMO_BLOCK_TEXT_DEFAULTS = {
    "eyebrow": "PARA LOJISTAS E REVENDEDORES",
    "title": "Compre no atacado com preços exclusivos",
    "subtitle": "Faça seu pedido em poucos segundos e receba condições especiais para revenda.",
    "bg_word": "ATACADO",
    "item_1": "Descontos progressivos",
    "item_2": "Atendimento rápido",
    "item_3": "Compra simplificada",
    "item_4": "Condições para lojistas",
    "btn_primary": "Solicitar pedido atacado",
    "btn_secondary": "Falar com um consultor",
    "btn_primary_msg": "Olá! Quero fazer um pedido no atacado.",
    "btn_secondary_msg": "Olá! Quero falar com um consultor sobre atacado.",
}

app = Flask(__name__)
app.config["UPLOAD_DIR"] = UPLOAD_DIR
# Chave usada para assinar a sessão de login (troque por qualquer texto aleatório na VPS)
app.secret_key = os.environ.get("SECRET_KEY", "royal-troque-esta-chave-secreta-na-vps-2026")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Versão dos assets estáticos (evita o navegador servir style.css/app.js antigos do cache
# depois de um deploy/edição, já que o Flask não versiona esses arquivos por padrão).
ASSET_VERSION = str(int(max(
    os.path.getmtime(os.path.join(BASE_DIR, "static", "style.css")),
    os.path.getmtime(os.path.join(BASE_DIR, "static", "app.js")),
)))


@app.context_processor
def inject_asset_version():
    return {"asset_v": ASSET_VERSION}


# ---------------------------------------------------------------------------
# Autenticação do painel admin
# ---------------------------------------------------------------------------
def login_required(view):
    """Protege rotas: se não estiver logado, manda para a tela de senha."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def api_login_required(view):
    """Protege as APIs de escrita: bloqueia quem não está logado."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"ok": False, "error": "não autorizado"}), 401
        return view(*args, **kwargs)
    return wrapped




# ---------------------------------------------------------------------------
# Banco de Dados
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS site_config (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS brands (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS vape_models (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_id       INTEGER NOT NULL,
            name           TEXT NOT NULL,
            puff_count     TEXT,
            image_url      TEXT,
            is_best_seller INTEGER DEFAULT 0,
            FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS products (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id    INTEGER NOT NULL,
            name        TEXT NOT NULL,
            price       REAL DEFAULT 0,
            is_in_stock INTEGER DEFAULT 1,
            FOREIGN KEY (model_id) REFERENCES vape_models(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS promo_blocks (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            position       INTEGER NOT NULL DEFAULT 0,
            active         INTEGER NOT NULL DEFAULT 1,
            bg_color_1     TEXT NOT NULL DEFAULT '#FFD60A',
            bg_color_2     TEXT NOT NULL DEFAULT '#ffe45e',
            text_theme     TEXT NOT NULL DEFAULT 'light',
            btn_bg_color   TEXT NOT NULL DEFAULT '#ffffff',
            btn_text_color TEXT NOT NULL DEFAULT '#0a0a0c'
        );

        CREATE TABLE IF NOT EXISTS coupons (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            code   TEXT NOT NULL UNIQUE,
            type   TEXT NOT NULL DEFAULT 'percent',
            value  REAL NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS shipping_zones (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            zone_type TEXT NOT NULL,     -- 'special' ou 'concentric'
            label     TEXT NOT NULL,
            lat       REAL NOT NULL,
            lng       REAL NOT NULL,
            radius_m  REAL NOT NULL,
            price     REAL                -- NULL = placeholder ("frete a combinar"), só permitido em zona especial
        );
        """
    )
    db.commit()

    # Config padrão
    defaults = {
        "theme_primary_color": "#FFD60A",
        "hero_title": "Sabor que reina. Qualidade Royal.",
        "hero_subtitle": "Os melhores pods descartáveis com a curadoria mais premium do Brasil.",
        "store_name": "Royal",
    }
    for k, v in defaults.items():
        db.execute(
            "INSERT OR IGNORE INTO site_config (key, value) VALUES (?, ?)", (k, v)
        )
    db.commit()

    # Migração: bloco único "Atacado" -> primeiro item da lista replicável de
    # promo_blocks. Roda uma única vez (quando a tabela promo_blocks está vazia).
    if db.execute("SELECT COUNT(*) AS c FROM promo_blocks").fetchone()[0] == 0:
        old = {
            r["key"]: r["value"]
            for r in db.execute(
                "SELECT key, value FROM site_config WHERE key LIKE 'atacado_%' OR key = 'show_atacado'"
            ).fetchall()
        }
        cur = db.execute(
            "INSERT INTO promo_blocks (position, active, bg_color_1, bg_color_2, text_theme, btn_bg_color, btn_text_color) "
            "VALUES (1, ?, '#FFD60A', '#ffe45e', 'light', '#ffffff', '#0a0a0c')",
            (1 if old.get("show_atacado", "1") == "1" else 0,),
        )
        pid = cur.lastrowid
        texts = {
            "eyebrow": old.get("atacado_eyebrow", PROMO_BLOCK_TEXT_DEFAULTS["eyebrow"]),
            "title": old.get("atacado_title", PROMO_BLOCK_TEXT_DEFAULTS["title"]),
            "subtitle": old.get("atacado_subtitle", PROMO_BLOCK_TEXT_DEFAULTS["subtitle"]),
            "bg_word": old.get("atacado_bg_word", PROMO_BLOCK_TEXT_DEFAULTS["bg_word"]),
            "item_1": old.get("atacado_item_1", PROMO_BLOCK_TEXT_DEFAULTS["item_1"]),
            "item_2": old.get("atacado_item_2", PROMO_BLOCK_TEXT_DEFAULTS["item_2"]),
            "item_3": old.get("atacado_item_3", PROMO_BLOCK_TEXT_DEFAULTS["item_3"]),
            "item_4": old.get("atacado_item_4", PROMO_BLOCK_TEXT_DEFAULTS["item_4"]),
            "btn_primary": old.get("atacado_btn_primary", PROMO_BLOCK_TEXT_DEFAULTS["btn_primary"]),
            "btn_secondary": old.get("atacado_btn_secondary", PROMO_BLOCK_TEXT_DEFAULTS["btn_secondary"]),
            "btn_primary_msg": PROMO_BLOCK_TEXT_DEFAULTS["btn_primary_msg"],
            "btn_secondary_msg": PROMO_BLOCK_TEXT_DEFAULTS["btn_secondary_msg"],
        }
        for field, value in texts.items():
            db.execute(
                "INSERT OR IGNORE INTO site_config (key, value) VALUES (?, ?)",
                (f"promo_{pid}_{field}", value),
            )
        db.execute("DELETE FROM site_config WHERE key LIKE 'atacado_%' OR key = 'show_atacado'")
        db.commit()

    # Semeia shipping_zones com os valores de shipping.py na primeira execução.
    # Depois disso, o banco manda — editar shipping.py não muda mais nada em produção.
    if db.execute("SELECT COUNT(*) AS c FROM shipping_zones").fetchone()[0] == 0:
        for z in SPECIAL_ZONES:
            db.execute(
                "INSERT INTO shipping_zones (zone_type, label, lat, lng, radius_m, price) VALUES ('special', ?, ?, ?, ?, ?)",
                (z["label"], z["lat"], z["lng"], z["radius_m"], z["price"]),
            )
        for z in CONCENTRIC_ZONES:
            db.execute(
                "INSERT INTO shipping_zones (zone_type, label, lat, lng, radius_m, price) VALUES ('concentric', ?, ?, ?, ?, ?)",
                (z["label"], z["lat"], z["lng"], z["radius_m"], z["price"]),
            )
        db.commit()

    # Seed de exemplo se vazio
    count = db.execute("SELECT COUNT(*) AS c FROM brands").fetchone()[0]
    if count == 0:
        seed(db)
    db.close()


def seed(db):
    data = {
        "Ignite": [
            {
                "name": "V150",
                "puff": "15.000 puffs",
                "best": 1,
                "flavors": [
                    ("Blue Razz Ice", 89.90, 1),
                    ("Grape Ice", 89.90, 1),
                    ("Watermelon Mint", 89.90, 1),
                    ("Peach Mango", 89.90, 0),
                ],
            },
            {
                "name": "V80",
                "puff": "8.000 puffs",
                "best": 0,
                "flavors": [
                    ("Lush Ice", 69.90, 1),
                    ("Mango Ice", 69.90, 1),
                    ("Cool Mint", 69.90, 1),
                ],
            },
        ],
        "Elfbar": [
            {
                "name": "BC25000",
                "puff": "25.000 puffs",
                "best": 1,
                "flavors": [
                    ("Strawberry Ice", 119.90, 1),
                    ("Grape Ice", 119.90, 1),
                    ("Cherry Cola", 119.90, 1),
                    ("Blueberry", 119.90, 1),
                    ("Kiwi Passion", 119.90, 0),
                ],
            },
            {
                "name": "BC18000",
                "puff": "18.000 puffs",
                "best": 0,
                "flavors": [
                    ("Watermelon", 99.90, 1),
                    ("Peach Ice", 99.90, 1),
                    ("Mint", 99.90, 1),
                ],
            },
        ],
        "Lost Mary": [
            {
                "name": "MO20000",
                "puff": "20.000 puffs",
                "best": 1,
                "flavors": [
                    ("Blue Cotton Candy", 109.90, 1),
                    ("Triple Berry Ice", 109.90, 1),
                    ("Sakura Grape", 109.90, 1),
                ],
            },
        ],
    }
    for brand_name, models in data.items():
        cur = db.execute("INSERT INTO brands (name) VALUES (?)", (brand_name,))
        bid = cur.lastrowid
        for m in models:
            cur = db.execute(
                "INSERT INTO vape_models (brand_id, name, puff_count, image_url, is_best_seller) VALUES (?,?,?,?,?)",
                (bid, m["name"], m["puff"], "", m["best"]),
            )
            mid = cur.lastrowid
            for fname, price, stock in m["flavors"]:
                db.execute(
                    "INSERT INTO products (model_id, name, price, is_in_stock) VALUES (?,?,?,?)",
                    (mid, fname, price, stock),
                )
    db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_config():
    rows = get_db().execute("SELECT key, value FROM site_config").fetchall()
    return {r["key"]: r["value"] for r in rows}


def get_promo_blocks(only_active=False):
    """Monta a lista de blocos promocionais (ex: Atacado), na ordem definida.

    Os campos estruturais (cor, tema, posição, ligado/desligado) vêm da tabela
    promo_blocks. Os textos (título, botões, etc.) vêm do site_config, com
    chave prefixada `promo_<id>_<campo>` — assim o Editor Visual (que só sabe
    salvar por chave de texto) continua funcionando sem mudanças.
    """
    db = get_db()
    config = get_config()
    rows = db.execute("SELECT * FROM promo_blocks ORDER BY position, id").fetchall()
    blocks = []
    for r in rows:
        if only_active and not r["active"]:
            continue
        pid = r["id"]
        block = {
            "id": pid,
            "position": r["position"],
            "active": r["active"],
            "bg_color_1": r["bg_color_1"],
            "bg_color_2": r["bg_color_2"],
            "text_theme": r["text_theme"],
            "btn_bg_color": r["btn_bg_color"],
            "btn_text_color": r["btn_text_color"],
        }
        for field, default in PROMO_BLOCK_TEXT_DEFAULTS.items():
            block[field] = config.get(f"promo_{pid}_{field}", default)
        blocks.append(block)
    return blocks


def create_promo_block(duplicate_from=None):
    """Cria um novo bloco promocional, opcionalmente clonando outro existente."""
    db = get_db()
    max_pos = db.execute("SELECT COALESCE(MAX(position), 0) AS p FROM promo_blocks").fetchone()["p"]

    source = None
    if duplicate_from:
        source = db.execute("SELECT * FROM promo_blocks WHERE id = ?", (duplicate_from,)).fetchone()

    cur = db.execute(
        "INSERT INTO promo_blocks (position, active, bg_color_1, bg_color_2, text_theme, btn_bg_color, btn_text_color) "
        "VALUES (?, 1, ?, ?, ?, ?, ?)",
        (
            max_pos + 1,
            source["bg_color_1"] if source else "#FFD60A",
            source["bg_color_2"] if source else "#ffe45e",
            source["text_theme"] if source else "light",
            source["btn_bg_color"] if source else "#ffffff",
            source["btn_text_color"] if source else "#0a0a0c",
        ),
    )
    pid = cur.lastrowid

    texts = dict(PROMO_BLOCK_TEXT_DEFAULTS)
    if duplicate_from:
        config = get_config()
        for field in texts:
            texts[field] = config.get(f"promo_{duplicate_from}_{field}", texts[field])

    for field, value in texts.items():
        db.execute(
            "INSERT INTO site_config (key, value) VALUES (?, ?)",
            (f"promo_{pid}_{field}", value),
        )
    db.commit()
    return pid


def get_coupons():
    """Lista os cupons com um campo `value_display` já formatado para a tabela do admin."""
    rows = get_db().execute("SELECT * FROM coupons ORDER BY id DESC").fetchall()
    coupons = []
    for r in rows:
        c = dict(r)
        if c["type"] == "percent":
            v = c["value"]
            c["value_display"] = (f"{v:.0f}%" if v == int(v) else f"{v:.2f}%".replace(".", ","))
        else:
            c["value_display"] = "R$ " + f"{c['value']:.2f}".replace(".", ",")
        coupons.append(c)
    return coupons


def get_shipping_zones():
    """Lê as zonas de frete do banco (fonte da verdade em produção, editável
    pelo painel admin). Retorna (special_zones, concentric_zones), no
    formato de dict que shipping.calculate_shipping() espera.
    """
    rows = get_db().execute(
        "SELECT * FROM shipping_zones ORDER BY zone_type DESC, radius_m ASC"
    ).fetchall()
    special = [dict(r) for r in rows if r["zone_type"] == "special"]
    concentric = [dict(r) for r in rows if r["zone_type"] == "concentric"]
    return special, concentric


def build_catalog():
    """Monta a lista de modelos com seus sabores e metadados agregados."""
    db = get_db()
    models = db.execute(
        """
        SELECT m.*, b.name AS brand_name
        FROM vape_models m JOIN brands b ON b.id = m.brand_id
        ORDER BY m.is_best_seller DESC, m.id DESC
        """
    ).fetchall()

    catalog = []
    for m in models:
        flavors = db.execute(
            "SELECT * FROM products WHERE model_id = ? ORDER BY id", (m["id"],)
        ).fetchall()
        flavors = [dict(f) for f in flavors]
        in_stock = [f for f in flavors if f["is_in_stock"]]
        prices = [f["price"] for f in in_stock] or [f["price"] for f in flavors]
        min_price = min(prices) if prices else 0
        catalog.append(
            {
                "id": m["id"],
                "brand_id": m["brand_id"],
                "brand_name": m["brand_name"],
                "name": m["name"],
                "puff_count": m["puff_count"],
                "image_url": m["image_url"],
                "is_best_seller": m["is_best_seller"],
                "flavors": flavors,
                "flavor_names": [f["name"] for f in flavors],
                "min_price": min_price,
            }
        )
    return catalog


# ---------------------------------------------------------------------------
# Rotas públicas
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    return render_template(
        "index.html",
        config=get_config(),
        catalog=build_catalog(),
        brands=[dict(b) for b in get_db().execute("SELECT * FROM brands ORDER BY name").fetchall()],
        whatsapp=WHATSAPP_PHONE,
        editor=False,
        promo_blocks=get_promo_blocks(only_active=True),
    )


@app.route("/static/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_DIR"], filename)


# ---------------------------------------------------------------------------
# Login / Logout do painel
# ---------------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == ADMIN_PASSWORD:
            session["is_admin"] = True
            session.permanent = True
            nxt = request.args.get("next") or url_for("admin")
            # segurança: só redireciona para caminhos internos
            if not nxt.startswith("/"):
                nxt = url_for("admin")
            return redirect(nxt)
        error = "Senha incorreta. Tente novamente."
    return render_template("login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


# ---------------------------------------------------------------------------
# Live Editor (desativado — edição é feita direto pelo Painel Admin)
# ---------------------------------------------------------------------------
@app.route("/admin/editor")
@login_required
def live_editor():
    return redirect(url_for("admin"))


# ---------------------------------------------------------------------------
# Painel Admin tradicional
# ---------------------------------------------------------------------------
@app.route("/admin")
@login_required
def admin():
    db = get_db()
    brands = db.execute("SELECT * FROM brands ORDER BY name").fetchall()
    tree = []
    for b in brands:
        models = db.execute(
            "SELECT * FROM vape_models WHERE brand_id = ? ORDER BY id", (b["id"],)
        ).fetchall()
        mlist = []
        for m in models:
            flavors = db.execute(
                "SELECT * FROM products WHERE model_id = ? ORDER BY id", (m["id"],)
            ).fetchall()
            mlist.append({"model": dict(m), "flavors": [dict(f) for f in flavors]})
        tree.append({"brand": dict(b), "models": mlist})
    special_zones, concentric_zones = get_shipping_zones()
    return render_template(
        "admin.html",
        tree=tree,
        config=get_config(),
        coupons=get_coupons(),
        special_zones=special_zones,
        concentric_zones=concentric_zones,
    )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.route("/api/update_config", methods=["POST"])
@api_login_required
def api_update_config():
    data = request.get_json(force=True)
    key = data.get("key")
    value = data.get("value")
    if not key:
        return jsonify({"ok": False, "error": "missing key"}), 400
    db = get_db()
    db.execute(
        "INSERT INTO site_config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    db.commit()
    return jsonify({"ok": True})


# ---- Blocos promocionais (ex: Atacado) ----
@app.route("/api/promo_block", methods=["POST"])
@api_login_required
def api_create_promo_block():
    d = request.get_json(force=True) or {}
    pid = create_promo_block(duplicate_from=d.get("duplicate_from"))
    return jsonify({"ok": True, "id": pid})


@app.route("/api/promo_block/<int:pid>", methods=["POST"])
@api_login_required
def api_update_promo_block(pid):
    d = request.get_json(force=True)
    db = get_db()
    fields = []
    vals = []
    for f in ("active", "bg_color_1", "bg_color_2", "text_theme", "btn_bg_color", "btn_text_color", "position"):
        if f in d:
            fields.append(f"{f} = ?")
            vals.append(d[f])
    if not fields:
        return jsonify({"ok": False}), 400
    vals.append(pid)
    db.execute(f"UPDATE promo_blocks SET {', '.join(fields)} WHERE id = ?", vals)
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/promo_block/<int:pid>", methods=["DELETE"])
@api_login_required
def api_delete_promo_block(pid):
    db = get_db()
    db.execute("DELETE FROM promo_blocks WHERE id = ?", (pid,))
    db.execute("DELETE FROM site_config WHERE key LIKE ?", (f"promo_{pid}_%",))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/promo_block/<int:pid>/move", methods=["POST"])
@api_login_required
def api_move_promo_block(pid):
    direction = (request.get_json(force=True) or {}).get("direction")
    db = get_db()
    rows = db.execute("SELECT id, position FROM promo_blocks ORDER BY position, id").fetchall()
    ids = [r["id"] for r in rows]
    if pid not in ids:
        return jsonify({"ok": False}), 404
    idx = ids.index(pid)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(rows):
        return jsonify({"ok": True})  # já está na ponta, nada a fazer
    a, b = rows[idx], rows[swap_idx]
    db.execute("UPDATE promo_blocks SET position = ? WHERE id = ?", (b["position"], a["id"]))
    db.execute("UPDATE promo_blocks SET position = ? WHERE id = ?", (a["position"], b["id"]))
    db.commit()
    return jsonify({"ok": True})


# ---- Cupons de desconto ----
def _validate_coupon_fields(ctype, value):
    """Retorna None se válido, ou uma mensagem de erro."""
    if ctype not in ("percent", "fixed"):
        return "Tipo de desconto inválido"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "Valor inválido"
    if ctype == "percent" and not (1 <= value <= 100):
        return "A porcentagem deve estar entre 1 e 100"
    if ctype == "fixed" and value <= 0:
        return "O valor fixo deve ser maior que zero"
    return None


@app.route("/api/coupon", methods=["POST"])
@api_login_required
def api_create_coupon():
    d = request.get_json(force=True) or {}
    code = (d.get("code") or "").strip().upper()
    ctype = d.get("type")
    value = d.get("value")
    if not code:
        return jsonify({"ok": False, "error": "Código do cupom é obrigatório"}), 400
    err = _validate_coupon_fields(ctype, value)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    db = get_db()
    if db.execute("SELECT id FROM coupons WHERE code = ?", (code,)).fetchone():
        return jsonify({"ok": False, "error": "Já existe um cupom com este código"}), 400
    cur = db.execute(
        "INSERT INTO coupons (code, type, value, active) VALUES (?,?,?,1)",
        (code, ctype, float(value)),
    )
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid})


@app.route("/api/coupon/<int:cid>", methods=["POST"])
@api_login_required
def api_update_coupon(cid):
    d = request.get_json(force=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM coupons WHERE id = ?", (cid,)).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "Cupom não encontrado"}), 404

    fields = []
    vals = []
    if "active" in d:
        fields.append("active = ?")
        vals.append(1 if d["active"] else 0)
    if "code" in d:
        code = (d["code"] or "").strip().upper()
        if not code:
            return jsonify({"ok": False, "error": "Código do cupom é obrigatório"}), 400
        if db.execute("SELECT id FROM coupons WHERE code = ? AND id != ?", (code, cid)).fetchone():
            return jsonify({"ok": False, "error": "Já existe um cupom com este código"}), 400
        fields.append("code = ?")
        vals.append(code)
    if "type" in d or "value" in d:
        ctype = d.get("type", row["type"])
        value = d.get("value", row["value"])
        err = _validate_coupon_fields(ctype, value)
        if err:
            return jsonify({"ok": False, "error": err}), 400
        fields.append("type = ?")
        vals.append(ctype)
        fields.append("value = ?")
        vals.append(float(value))
    if not fields:
        return jsonify({"ok": False}), 400
    vals.append(cid)
    db.execute(f"UPDATE coupons SET {', '.join(fields)} WHERE id = ?", vals)
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/coupon/<int:cid>", methods=["DELETE"])
@api_login_required
def api_delete_coupon(cid):
    db = get_db()
    db.execute("DELETE FROM coupons WHERE id = ?", (cid,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/coupon/apply", methods=["POST"])
def api_apply_coupon():
    """Valida um cupom digitado no checkout (rota pública, sem login).

    Recebe o total atual do carrinho para poder recusar cupons de valor fixo
    maiores que o pedido (regra de negócio pedida: cupom fixo não pode
    ultrapassar o total). O desconto em si é aplicado no front-end.
    """
    d = request.get_json(force=True) or {}
    code = (d.get("code") or "").strip().upper()
    try:
        order_total = float(d.get("total") or 0)
    except (TypeError, ValueError):
        order_total = 0

    generic_error = "Cupom inválido ou inativo"
    if not code:
        return jsonify({"ok": False, "error": generic_error}), 400

    row = get_db().execute(
        "SELECT * FROM coupons WHERE code = ? AND active = 1", (code,)
    ).fetchone()
    if not row:
        return jsonify({"ok": False, "error": generic_error}), 404
    if row["type"] == "fixed" and row["value"] > order_total:
        return jsonify({"ok": False, "error": generic_error}), 400

    return jsonify({"ok": True, "code": row["code"], "type": row["type"], "value": row["value"]})


@app.route("/api/shipping/calc", methods=["POST"])
def api_calculate_shipping():
    """Calcula o frete por zona circular a partir da geolocalização do
    cliente (rota pública, sem login — chamada direto do checkout).
    """
    d = request.get_json(force=True) or {}
    try:
        lat = float(d.get("lat"))
        lng = float(d.get("lng"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Coordenadas inválidas"}), 400
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return jsonify({"ok": False, "error": "Coordenadas inválidas"}), 400

    special, concentric = get_shipping_zones()
    return jsonify(calculate_shipping(lat, lng, special_zones=special, concentric_zones=concentric))


# ---- Zonas de frete (admin) ----
def _parse_zone_latlng_radius(lat, lng, radius_m):
    """Converte e valida lat/lng/radius_m. Retorna (lat, lng, radius_m, None)
    ou (None, None, None, mensagem_de_erro)."""
    try:
        lat = float(lat)
        lng = float(lng)
        radius_m = float(radius_m)
    except (TypeError, ValueError):
        return None, None, None, "Latitude, longitude e raio precisam ser números"
    if not (-90 <= lat <= 90):
        return None, None, None, "Latitude precisa estar entre -90 e 90"
    if not (-180 <= lng <= 180):
        return None, None, None, "Longitude precisa estar entre -180 e 180"
    if radius_m <= 0:
        return None, None, None, "O raio precisa ser maior que zero"
    return lat, lng, radius_m, None


def _parse_zone_price(price, zone_type):
    """Converte e valida o preço (pode ser vazio só em zona especial —
    fica como placeholder de 'frete a combinar'). Retorna (price_ou_None, None)
    ou (None, mensagem_de_erro)."""
    if price is None or price == "":
        if zone_type == "concentric":
            return None, "Zona concêntrica precisa de um preço definido"
        return None, None
    try:
        price_val = float(price)
    except (TypeError, ValueError):
        return None, "Preço inválido"
    if price_val < 0:
        return None, "Preço não pode ser negativo"
    return price_val, None


@app.route("/api/shipping_zone", methods=["POST"])
@api_login_required
def api_create_shipping_zone():
    d = request.get_json(force=True) or {}
    zone_type = d.get("zone_type")
    label = (d.get("label") or "").strip()

    if zone_type not in ("special", "concentric"):
        return jsonify({"ok": False, "error": "Tipo de zona inválido"}), 400
    if not label:
        return jsonify({"ok": False, "error": "Nome da zona é obrigatório"}), 400

    lat, lng, radius_m, err = _parse_zone_latlng_radius(d.get("lat"), d.get("lng"), d.get("radius_m"))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    price_val, err = _parse_zone_price(d.get("price"), zone_type)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    db = get_db()
    cur = db.execute(
        "INSERT INTO shipping_zones (zone_type, label, lat, lng, radius_m, price) VALUES (?,?,?,?,?,?)",
        (zone_type, label, lat, lng, radius_m, price_val),
    )
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid})


@app.route("/api/shipping_zone/<int:zid>", methods=["POST"])
@api_login_required
def api_update_shipping_zone(zid):
    d = request.get_json(force=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM shipping_zones WHERE id = ?", (zid,)).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "Zona não encontrada"}), 404

    fields = []
    vals = []
    if "label" in d:
        label = (d["label"] or "").strip()
        if not label:
            return jsonify({"ok": False, "error": "Nome da zona é obrigatório"}), 400
        fields.append("label = ?")
        vals.append(label)
    if "lat" in d or "lng" in d or "radius_m" in d:
        lat, lng, radius_m, err = _parse_zone_latlng_radius(
            d.get("lat", row["lat"]), d.get("lng", row["lng"]), d.get("radius_m", row["radius_m"])
        )
        if err:
            return jsonify({"ok": False, "error": err}), 400
        if "lat" in d:
            fields.append("lat = ?"); vals.append(lat)
        if "lng" in d:
            fields.append("lng = ?"); vals.append(lng)
        if "radius_m" in d:
            fields.append("radius_m = ?"); vals.append(radius_m)
    if "price" in d:
        price_val, err = _parse_zone_price(d.get("price"), row["zone_type"])
        if err:
            return jsonify({"ok": False, "error": err}), 400
        fields.append("price = ?")
        vals.append(price_val)

    if not fields:
        return jsonify({"ok": False}), 400
    vals.append(zid)
    db.execute(f"UPDATE shipping_zones SET {', '.join(fields)} WHERE id = ?", vals)
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/shipping_zone/<int:zid>", methods=["DELETE"])
@api_login_required
def api_delete_shipping_zone(zid):
    db = get_db()
    db.execute("DELETE FROM shipping_zones WHERE id = ?", (zid,))
    db.commit()
    return jsonify({"ok": True})


# ---- Brands ----
@app.route("/api/brand", methods=["POST"])
@api_login_required
def api_create_brand():
    name = (request.get_json(force=True).get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "nome vazio"}), 400
    db = get_db()
    cur = db.execute("INSERT INTO brands (name) VALUES (?)", (name,))
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid, "name": name})


@app.route("/api/brand/<int:bid>", methods=["DELETE"])
@api_login_required
def api_delete_brand(bid):
    db = get_db()
    db.execute("DELETE FROM brands WHERE id = ?", (bid,))
    db.commit()
    return jsonify({"ok": True})


# ---- Models ----
@app.route("/api/model", methods=["POST"])
@api_login_required
def api_create_model():
    d = request.get_json(force=True)
    brand_id = d.get("brand_id")
    name = (d.get("name") or "").strip()
    puff = (d.get("puff_count") or "").strip()
    if not brand_id or not name:
        return jsonify({"ok": False, "error": "dados incompletos"}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO vape_models (brand_id, name, puff_count, image_url, is_best_seller) VALUES (?,?,?,?,0)",
        (brand_id, name, puff, ""),
    )
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid})


@app.route("/api/model/<int:mid>", methods=["POST"])
@api_login_required
def api_update_model(mid):
    d = request.get_json(force=True)
    db = get_db()
    fields = []
    vals = []
    for f in ("name", "puff_count", "is_best_seller", "image_url"):
        if f in d:
            fields.append(f"{f} = ?")
            vals.append(d[f])
    if not fields:
        return jsonify({"ok": False}), 400
    vals.append(mid)
    db.execute(f"UPDATE vape_models SET {', '.join(fields)} WHERE id = ?", vals)
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/model/<int:mid>", methods=["DELETE"])
@api_login_required
def api_delete_model(mid):
    db = get_db()
    db.execute("DELETE FROM vape_models WHERE id = ?", (mid,))
    db.commit()
    return jsonify({"ok": True})


# ---- Products (Flavors) ----
@app.route("/api/product", methods=["POST"])
@api_login_required
def api_create_product():
    d = request.get_json(force=True)
    model_id = d.get("model_id")
    name = (d.get("name") or "").strip()
    if not model_id or not name:
        return jsonify({"ok": False, "error": "dados incompletos"}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO products (model_id, name, price, is_in_stock) VALUES (?,?,?,1)",
        (model_id, name, float(d.get("price") or 0)),
    )
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid})


@app.route("/api/product/<int:pid>", methods=["POST"])
@api_login_required
def api_update_product(pid):
    d = request.get_json(force=True)
    db = get_db()
    fields = []
    vals = []
    if "name" in d:
        fields.append("name = ?")
        vals.append((d["name"] or "").strip())
    if "price" in d:
        fields.append("price = ?")
        vals.append(float(d["price"] or 0))
    if "is_in_stock" in d:
        fields.append("is_in_stock = ?")
        vals.append(1 if d["is_in_stock"] else 0)
    if not fields:
        return jsonify({"ok": False}), 400
    vals.append(pid)
    db.execute(f"UPDATE products SET {', '.join(fields)} WHERE id = ?", vals)
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/product/<int:pid>", methods=["DELETE"])
@api_login_required
def api_delete_product(pid):
    db = get_db()
    db.execute("DELETE FROM products WHERE id = ?", (pid,))
    db.commit()
    return jsonify({"ok": True})


# ---- Upload de imagem ----
def process_product_image(file_storage, size=PRODUCT_IMAGE_SIZE):
    """Recorta ao centro em proporção 1:1 e redimensiona para `size`x`size`.

    Garante que toda foto de produto salva no site tenha exatamente o mesmo
    enquadramento quadrado, independente do tamanho/proporção enviado pelo admin.
    """
    img = Image.open(file_storage)
    img = ImageOps.exif_transpose(img)  # corrige rotação de fotos tiradas por celular

    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA") if has_alpha else img.convert("RGB")

    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = img.resize((size, size), Image.LANCZOS)
    return img


@app.route("/api/upload_image", methods=["POST"])
@api_login_required
def api_upload_image():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "sem arquivo"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "nome vazio"}), 400
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"ok": False, "error": "formato inválido"}), 400

    try:
        processed = process_product_image(file)
    except Exception:
        return jsonify({"ok": False, "error": "não foi possível processar a imagem"}), 400

    # Salva sempre a versão processada (nunca o arquivo bruto enviado).
    out_ext = "png" if processed.mode == "RGBA" else "jpg"
    fname = f"{uuid.uuid4().hex}.{out_ext}"
    path = os.path.join(app.config["UPLOAD_DIR"], secure_filename(fname))
    if out_ext == "jpg":
        processed.save(path, "JPEG", quality=88, optimize=True)
    else:
        processed.save(path, "PNG", optimize=True)
    image_url = url_for("uploaded_file", filename=fname)

    model_id = request.form.get("model_id")
    if model_id:
        db = get_db()
        db.execute("UPDATE vape_models SET image_url = ? WHERE id = ?", (image_url, model_id))
        db.commit()
    return jsonify({"ok": True, "image_url": image_url})


# Garante que o banco existe quando rodando via Gunicorn (produção)
with app.app_context():
    init_db()

if __name__ == "__main__":
    # Rodar localmente (no seu PC): python app.py
    # DEBUG só liga se a variável de ambiente FLASK_DEBUG=1 estiver setada.
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(debug=debug, host="0.0.0.0", port=5000)
