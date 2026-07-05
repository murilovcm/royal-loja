import os
import sqlite3
import uuid
from functools import wraps
from flask import (
    Flask, g, render_template, request, jsonify,
    redirect, url_for, send_from_directory, session, abort
)
from werkzeug.utils import secure_filename

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

# Telefone do dono da loja (formato internacional, apenas dígitos)
# CONFIRME: celular brasileiro tem 9 dígitos após o DDD (começa com 9).
WHATSAPP_PHONE = "5598985086085"

# Senha do painel admin.
# Na VPS, defina a variável de ambiente ADMIN_PASSWORD para não deixar a senha no código.
# Se não definir, usa a senha padrão abaixo (só para testes no seu PC).
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "386121")

app = Flask(__name__)
app.config["UPLOAD_DIR"] = UPLOAD_DIR
# Chave usada para assinar a sessão de login (troque por qualquer texto aleatório na VPS)
app.secret_key = os.environ.get("SECRET_KEY", "royal-troque-esta-chave-secreta-na-vps-2026")
os.makedirs(UPLOAD_DIR, exist_ok=True)


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
        """
    )
    db.commit()

    # Config padrão
    defaults = {
        "theme_primary_color": "#FFD60A",
        "show_warning_bar": "1",
        "warning_bar_text": "🔥 FRETE GRÁTIS ACIMA DE R$300 • ENTREGA DISCRETA • VENDA PROIBIDA PARA MENORES DE 18 ANOS 🔥",
        "hero_title": "Sabor que reina. Qualidade Royal.",
        "hero_subtitle": "Os melhores pods descartáveis com a curadoria mais premium do Brasil.",
        "store_name": "Royal",
        # ---- Seção Atacado (liga/desliga + textos editáveis) ----
        "show_atacado": "1",
        "atacado_eyebrow": "PARA LOJISTAS E REVENDEDORES",
        "atacado_title": "Compre no atacado com preços exclusivos",
        "atacado_subtitle": "Faça seu pedido em poucos segundos e receba condições especiais para revenda.",
        "atacado_bg_word": "ATACADO",
        "atacado_item_1": "Descontos progressivos",
        "atacado_item_2": "Atendimento rápido",
        "atacado_item_3": "Compra simplificada",
        "atacado_item_4": "Condições para lojistas",
        "atacado_btn_primary": "Solicitar pedido atacado",
        "atacado_btn_secondary": "Falar com um consultor",
    }
    for k, v in defaults.items():
        db.execute(
            "INSERT OR IGNORE INTO site_config (key, value) VALUES (?, ?)", (k, v)
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
# Live Editor
# ---------------------------------------------------------------------------
@app.route("/admin/editor")
@login_required
def live_editor():
    return render_template(
        "index.html",
        config=get_config(),
        catalog=build_catalog(),
        brands=[dict(b) for b in get_db().execute("SELECT * FROM brands ORDER BY name").fetchall()],
        whatsapp=WHATSAPP_PHONE,
        editor=True,
    )


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
    return render_template("admin.html", tree=tree, config=get_config())


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
    fname = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(app.config["UPLOAD_DIR"], secure_filename(fname))
    file.save(path)
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
