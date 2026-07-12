import hmac
import os
import re
import secrets
import sqlite3
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import timedelta
from functools import wraps
from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException
from flask import (
    Flask, g, render_template, request, jsonify,
    redirect, url_for, send_from_directory, session, abort
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps, ImageChops

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

# Logos (navbar/footer) aceitam PNG e SVG e não passam pelo recorte quadrado
# usado nas fotos de produto — preservam a proporção original.
LOGO_ALLOWED_EXT = {"png", "svg"}
LOGO_SLOTS = {"main": "logo_main_url", "footer": "logo_footer_url"}
LOGO_MAX_DIM = 600

# Favicon enviado pelo painel: recortado ao centro em quadrado e reduzido a
# 64x64 PNG, auto-hospedado em /static/uploads (mesma origem da loja).
FAVICON_ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}
FAVICON_SIZE = 64

# Elementos e atributos removidos de qualquer SVG enviado pelo admin, para
# impedir que um arquivo "logo.svg" carregue <script>, handlers de evento
# (onload, onerror...) ou referências javascript:/data:text/html — SVGs são
# servidos na mesma origem do site (/static/uploads/...), então script
# embutido executaria com a mesma sessão/cookies do painel admin.
SVG_DISALLOWED_TAGS = {
    "script", "foreignobject", "iframe", "embed", "object", "audio", "video",
    "animate", "animatetransform", "animatemotion", "set", "handler", "listener",
}
SVG_URI_ATTRS = {"href", "xlink:href", "src"}
SVG_DANGEROUS_URI_SCHEMES = ("javascript:", "data:text/html", "vbscript:")
SVG_DANGEROUS_STYLE_RE = re.compile(r"expression\s*\(|-moz-binding|behavior\s*:", re.IGNORECASE)


def sanitize_svg(raw_bytes):
    """Analisa e limpa um SVG enviado pelo admin, removendo qualquer coisa que
    possa executar JavaScript. Retorna os bytes limpos, ou None se o arquivo
    não for um SVG válido (nesse caso o upload deve ser rejeitado)."""
    try:
        root = DefusedET.fromstring(raw_bytes)
    except (ET.ParseError, DefusedXmlException, ValueError):
        return None

    root_tag = root.tag.rsplit("}", 1)[-1].lower() if isinstance(root.tag, str) else ""
    if root_tag != "svg":
        return None

    def clean_attrs(el):
        for attr in list(el.attrib):
            attr_local = attr.rsplit("}", 1)[-1].lower()
            value = el.attrib[attr]
            if attr_local.startswith("on"):
                del el.attrib[attr]
            elif attr_local in SVG_URI_ATTRS and value.strip().lower().startswith(SVG_DANGEROUS_URI_SCHEMES):
                del el.attrib[attr]
            elif attr_local == "style" and SVG_DANGEROUS_STYLE_RE.search(value):
                del el.attrib[attr]

    def clean(el):
        clean_attrs(el)
        for child in list(el):
            tag = child.tag.rsplit("}", 1)[-1].lower() if isinstance(child.tag, str) else ""
            if tag in SVG_DISALLOWED_TAGS:
                el.remove(child)
                continue
            clean(child)

    clean(root)

    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)

# Todas as fotos de produto são padronizadas para este tamanho (quadrado)
# ao serem enviadas pelo painel admin, garantindo o mesmo enquadramento
# em qualquer card ou modal do site.
PRODUCT_IMAGE_SIZE = 800

# Telefone do dono da loja (formato internacional, apenas dígitos)
# CONFIRME: celular brasileiro tem 9 dígitos após o DDD (começa com 9).
WHATSAPP_PHONE = "5598985086085"

# Conta "dono" do painel admin (acesso completo, único que pode criar/editar
# funcionários). É semeada no banco só na primeíssima vez que a loja roda
# (tabela users vazia) — depois disso, a senha real mora só no banco (com
# hash), então trocar essas variáveis de ambiente não muda mais nada.
# Na VPS, defina ADMIN_USERNAME/ADMIN_PASSWORD antes do primeiro start para
# não deixar a senha do dono no código-fonte.
_DEFAULT_ADMIN_USERNAME = "admin"
_DEFAULT_ADMIN_PASSWORD = "386121"
_DEFAULT_SECRET_KEY = "royal-troque-esta-chave-secreta-na-vps-2026"
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", _DEFAULT_ADMIN_USERNAME)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD)

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
app.secret_key = os.environ.get("SECRET_KEY", _DEFAULT_SECRET_KEY)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Sinaliza se a senha e/ou a chave de sessão ainda são as padrão do código-fonte
# (públicas no repositório) em vez de terem sido definidas via variável de
# ambiente — usado para avisar bem alto no log de inicialização (mais abaixo)
# e não deixar isso passar despercebido numa VPS real.
USING_DEFAULT_SECRETS = (
    ADMIN_PASSWORD == _DEFAULT_ADMIN_PASSWORD or app.secret_key == _DEFAULT_SECRET_KEY
)
if USING_DEFAULT_SECRETS:
    app.logger.warning(
        "\n"
        + "  " + "=" * 68 + "\n"
        + "  ATENCAO: ADMIN_PASSWORD e/ou SECRET_KEY nao foram definidos por\n"
        + "  variavel de ambiente - a loja esta usando os valores padrao do\n"
        + "  codigo-fonte, que sao PUBLICOS para quem tiver acesso ao repositorio.\n"
        + "  Isso permite login por senha fraca e ate forjar sessao de admin.\n"
        + "  Defina ADMIN_PASSWORD e SECRET_KEY antes de publicar a loja -\n"
        + "  veja deploy/GUIA_DEPLOY_VPS.md.\n"
        + "  " + "=" * 68
    )

# Atrás do Nginx (deploy/nginx-royal.conf), a conexão real chega via socket/porta
# local — sem isso, request.remote_addr veria sempre o IP do proxy, e não do
# cliente, quebrando o bloqueio de força-bruta e o log de auditoria por IP.
# x_for=1 confia em exatamente um hop de proxy (o Nginx da própria VPS).
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0)

# Tamanho máximo de qualquer requisição (uploads de logo/produto inclusos).
# Evita que alguém com sessão válida (ou via CSRF numa rota sem token) mande
# um corpo gigante e esgote memória/disco antes de qualquer validação rodar.
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB

# Cookie de sessão: HttpOnly (padrão do Flask) evita leitura via JS; SameSite=Lax
# barra a maioria dos ataques CSRF cross-site; Secure impede que o cookie
# trafegue em HTTP puro (exige HTTPS já configurado via Nginx/Certbot na VPS —
# ver deploy/GUIA_DEPLOY_VPS.md, Fase 6).
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "1") != "0"
# Sessão expira em 7 dias em vez do padrão de 31 dias do Flask — reduz a janela
# em que um cookie de sessão vazado/roubado continua valendo.
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)

# Versão dos assets estáticos (evita o navegador servir style.css/app.js antigos do cache
# depois de um deploy/edição, já que o Flask não versiona esses arquivos por padrão).
ASSET_VERSION = str(int(max(
    os.path.getmtime(os.path.join(BASE_DIR, "static", "style.css")),
    os.path.getmtime(os.path.join(BASE_DIR, "static", "app.js")),
)))


@app.context_processor
def inject_asset_version():
    return {"asset_v": ASSET_VERSION}


@app.context_processor
def inject_config():
    """Deixa a config da loja (site_config) disponível em TODOS os templates
    como `config.*` — inclusive login.html, que não recebe config pela rota.
    Rotas que passam config=get_config() explicitamente continuam funcionando
    (o kwarg explícito do render_template tem prioridade sobre o processor)."""
    return {"config": get_config()}


@app.after_request
def set_security_headers(response):
    """Headers de defesa-em-profundidade contra clickjacking, MIME-sniffing e
    XSS. A CSP permite 'unsafe-inline' em script/style porque os templates
    usam onclick=... e <style> inline hoje — bloqueia carregar script/estilo
    de outra origem e qualquer enquadramento do site em <iframe>, o que já
    cobre o principal risco (ex.: um SVG malicioso plantado via upload não
    consegue puxar recursos externos nem ser enquadrado)."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    return response


# ---------------------------------------------------------------------------
# Autenticação do painel admin
# ---------------------------------------------------------------------------
# Bloqueio simples por IP contra força-bruta em /admin/login. Em memória
# (reseta se o processo reiniciar) — suficiente para 1 único processo/worker;
# como o gunicorn roda com múltiplos workers (Procfile/royal.service), o
# bloqueio é por worker, não global, mas ainda reduz bastante a velocidade
# de um ataque de força-bruta.
LOGIN_ATTEMPTS = {}
LOGIN_MAX_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW_SECONDS = 5 * 60
LOGIN_LOCKOUT_SECONDS = 5 * 60

# Hash "de mentira" usado quando o username digitado não existe, só para o
# tempo de resposta do login não denunciar se um usuário existe ou não.
_DUMMY_PASSWORD_HASH = generate_password_hash("dummy-timing-safety")


def _client_ip():
    return request.remote_addr or "desconhecido"


def _login_lockout_remaining(ip):
    entry = LOGIN_ATTEMPTS.get(ip)
    if not entry:
        return 0
    locked_until = entry.get("locked_until", 0)
    remaining = locked_until - time.time()
    return int(remaining) if remaining > 0 else 0


def _register_failed_login(ip):
    now = time.time()
    entry = LOGIN_ATTEMPTS.setdefault(ip, {"count": 0, "first_failure": now})
    if now - entry["first_failure"] > LOGIN_ATTEMPT_WINDOW_SECONDS:
        entry["count"] = 0
        entry["first_failure"] = now
    entry["count"] += 1
    if entry["count"] >= LOGIN_MAX_ATTEMPTS:
        entry["locked_until"] = now + LOGIN_LOCKOUT_SECONDS


def _clear_login_attempts(ip):
    LOGIN_ATTEMPTS.pop(ip, None)


def _is_safe_redirect_target(path):
    """Só permite redirecionar para caminhos internos (evita open redirect
    via 'next=//evil.com' ou 'next=https://evil.com')."""
    return bool(path) and path.startswith("/") and not path.startswith("//") and "://" not in path


def login_required(view):
    """Protege páginas HTML do painel: se não estiver logado (ou a conta foi
    desativada), manda para a tela de senha."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _current_user():
            session.clear()
            return redirect(url_for("admin_login", next=request.path))
        # Sessões que já existiam antes do token CSRF ser introduzido não têm
        # essa chave ainda — gera aqui para não deixar o admin "preso" tendo
        # que deslogar/logar de novo manualmente.
        if not session.get("csrf_token"):
            session["csrf_token"] = secrets.token_hex(32)
        return view(*args, **kwargs)
    return wrapped


def _write_api_guard(permission_check=None):
    """Fábrica dos decorators usados por toda API de escrita do painel.

    Sempre exige estar logado (com a conta ainda ativa) e o token CSRF da
    sessão (header X-Admin-Token). Se `permission_check` for passado, o dono
    sempre passa; um funcionário só passa se `permission_check(user)` for
    verdadeiro — é assim que Identidade Visual e Frete ficam travados pra
    funcionário (permission_check=lambda u: False) e Catálogo/Cupons
    respeitam o que o dono liberou para cada um.

    A permissão é checada consultando o banco a cada request (não confiando
    em dado guardado na sessão) — assim, se o dono desativar alguém ou tirar
    um poder, isso vale já na próxima ação daquela pessoa, sem esperar a
    sessão expirar.
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = _current_user()
            if not user:
                session.clear()
                return jsonify({"ok": False, "error": "não autorizado"}), 401
            if permission_check is not None and user["role"] != "owner" and not permission_check(user):
                return jsonify({"ok": False, "error": "você não tem permissão para isso — fale com o dono da loja"}), 403
            expected = session.get("csrf_token")
            provided = request.headers.get("X-Admin-Token", "")
            if not expected or not hmac.compare_digest(provided, expected):
                return jsonify({"ok": False, "error": "token CSRF inválido — recarregue a página e faça login novamente"}), 403
            detail = ""
            if request.method != "GET" and request.is_json:
                detail = request.get_json(silent=True) or ""
            result = view(*args, **kwargs)
            log_audit(f"{request.method} {request.path}", detail, username=user["username"])
            return result
        return wrapped
    return decorator


# Qualquer conta logada (dono ou funcionário) pode chamar.
api_login_required = _write_api_guard()
# Só passa quem tem can_catalog=1 (ou é dono).
api_catalog_required = _write_api_guard(lambda u: u["can_catalog"])
# Só passa quem tem can_coupons=1 (ou é dono).
api_coupons_required = _write_api_guard(lambda u: u["can_coupons"])
# Nunca passa pra quem não é dono — usado em Identidade Visual, Frete e
# gestão de funcionários, que não têm toggle: são sempre exclusivos do dono.
api_owner_required = _write_api_guard(lambda u: False)


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


def _current_user():
    """Usuário logado nesta sessão, buscado no banco a cada request (não
    confia em papel/permissão guardado na sessão). Retorna None se não há
    sessão, o usuário foi excluído, ou a conta foi desativada pelo dono."""
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute(
        "SELECT * FROM users WHERE id = ? AND is_active = 1", (uid,)
    ).fetchone()


def log_audit(action, detail="", username=None):
    """Registra uma ação administrativa (login, logout, criação/edição/exclusão
    de dados) para dar rastreabilidade caso algo precise ser investigado
    depois. Nunca deixa uma falha de log derrubar a ação em si."""
    try:
        db = get_db()
        db.execute(
            "INSERT INTO audit_log (ts, ip, action, detail, username) VALUES (?, ?, ?, ?, ?)",
            (time.time(), _client_ip(), action, str(detail)[:500], username),
        )
        db.commit()
    except Exception:
        pass


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
            color       TEXT,                -- cor do ponto (•) do sabor no card; NULL = usa a paleta padrão
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

        CREATE TABLE IF NOT EXISTS audit_log (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            ts     REAL NOT NULL,
            ip     TEXT,
            action TEXT NOT NULL,
            detail TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'staff',  -- 'owner' ou 'staff'
            can_catalog   INTEGER NOT NULL DEFAULT 1,     -- pode mexer em marcas/modelos/sabores/estoque
            can_coupons   INTEGER NOT NULL DEFAULT 1,     -- pode mexer em cupons de desconto
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    REAL NOT NULL
        );
        """
    )
    db.commit()

    # Migração: audit_log ganhou a coluna username depois de já existir em
    # bancos antigos — ALTER TABLE ADD COLUMN é seguro de rodar sempre que
    # a coluna ainda não existir.
    audit_cols = {row["name"] for row in db.execute("PRAGMA table_info(audit_log)").fetchall()}
    if "username" not in audit_cols:
        db.execute("ALTER TABLE audit_log ADD COLUMN username TEXT")
        db.commit()

    # Migração: products ganhou a coluna color (cor do ponto do sabor no card)
    # para bancos que já existiam antes dessa feature.
    prod_cols = {row["name"] for row in db.execute("PRAGMA table_info(products)").fetchall()}
    if "color" not in prod_cols:
        db.execute("ALTER TABLE products ADD COLUMN color TEXT")
        db.commit()

    # Semeia a conta "dono" (acesso completo) só na primeiríssima vez que a
    # loja roda — depois disso, a senha real mora hasheada no banco, e essas
    # variáveis de ambiente não têm mais efeito nenhum sobre o login.
    owner_exists = db.execute("SELECT 1 FROM users WHERE role = 'owner' LIMIT 1").fetchone()
    if not owner_exists:
        db.execute(
            "INSERT OR IGNORE INTO users "
            "(username, password_hash, role, can_catalog, can_coupons, is_active, created_at) "
            "VALUES (?, ?, 'owner', 1, 1, 1, ?)",
            (ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD), time.time()),
        )
        db.commit()

    # Config padrão
    defaults = {
        "theme_primary_color": "#FFD60A",
        # Segunda parada do degradê dos botões + ângulo do gradiente. Editáveis
        # no painel ("Gradiente dos botões"); alimentam --yellow-soft/--btn-grad-angle.
        "theme_primary_grad_end": "#ffe45e",
        "theme_grad_angle": "120",
        "theme_text_on_primary_color": "#000000",
        "theme_bg_color": "#0d0d1a",
        "theme_card_bg_color": "#1a1a2e",
        "theme_text_color": "#ffffff",
        # Paleta completa (superfícies, bordas, destaque roxo, texto secundário).
        "theme_surface_color": "#17151c",
        "theme_surface_2_color": "#1e1b26",
        "theme_border_color": "#29262f",
        "theme_accent_color": "#7c3aed",
        "theme_accent_soft_color": "#a855f7",
        "theme_text_dim_color": "#9a97a5",
        "logo_main_url": "",
        "logo_footer_url": "",
        "hero_title": "Sabor que reina. Qualidade Royal.",
        "hero_subtitle": "Os melhores pods descartáveis com a curadoria mais premium do Brasil.",
        "store_name": "Royal",
        "store_city": "São Luís",
        # Número do WhatsApp usado no checkout / links wa.me. Fica editável no
        # painel; o valor inicial vem da env var WHATSAPP_PHONE.
        "whatsapp_phone": os.environ.get("WHATSAPP_PHONE", ""),
        # Identidade / SEO da loja — editáveis em "Configurações Gerais" no
        # painel; valores iniciais vêm das env vars correspondentes.
        "favicon_url": os.environ.get("FAVICON_URL", ""),
        "meta_description": os.environ.get("META_DESCRIPTION", ""),
        "meta_keywords": os.environ.get("META_KEYWORDS", ""),
        "instagram_url": os.environ.get("INSTAGRAM_URL", ""),
        # Pop-up de promoção do site (gerenciado na aba Cupons do painel).
        "promo_popup_enabled": "0",
        "promo_popup_badge": "OFERTA ESPECIAL",
        "promo_popup_title": "Ganhe um desconto no seu pedido",
        "promo_popup_message": "Use o cupom abaixo no checkout e aproveite.",
        "promo_popup_coupon": "",
        "promo_popup_cta_label": "Ver catálogo",
        "promo_popup_cta_link": "#catalogo",
    }
    for k, v in defaults.items():
        db.execute(
            "INSERT OR IGNORE INTO site_config (key, value) VALUES (?, ?)", (k, v)
        )
    db.commit()

    # O bloco "Atacado" foi descontinuado: nunca é semeado automaticamente.
    # Só limpamos eventuais chaves legadas (atacado_*/show_atacado) que tenham
    # sobrado de versões antigas, para não deixar lixo no site_config. Blocos
    # promocionais continuam podendo ser criados manualmente no painel.
    db.execute("DELETE FROM site_config WHERE key LIKE 'atacado_%' OR key = 'show_atacado'")
    db.commit()

    # Limpeza única (uma vez por banco): remove o bloco "Atacado" que versões
    # antigas semeavam automaticamente e ficou gravado em promo_blocks nas lojas
    # já publicadas (vapor-loja, pods-ilha, etc.). Identifica pelo bg_word padrão
    # "ATACADO" — não toca em blocos promocionais criados/renomeados pelo lojista.
    # A flag garante que roda só uma vez, então blocos legítimos futuros ficam a salvo.
    if db.execute("SELECT 1 FROM site_config WHERE key = 'atacado_block_purged'").fetchone() is None:
        for r in db.execute("SELECT id FROM promo_blocks").fetchall():
            pid = r["id"]
            bg = db.execute(
                "SELECT value FROM site_config WHERE key = ?", (f"promo_{pid}_bg_word",)
            ).fetchone()
            if bg and (bg["value"] or "").strip().upper() == "ATACADO":
                db.execute("DELETE FROM promo_blocks WHERE id = ?", (pid,))
                db.execute("DELETE FROM site_config WHERE key LIKE ?", (f"promo_{pid}_%",))
        db.execute(
            "INSERT OR IGNORE INTO site_config (key, value) VALUES ('atacado_block_purged', '1')"
        )
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
        ip = _client_ip()
        remaining = _login_lockout_remaining(ip)
        if remaining > 0:
            error = f"Muitas tentativas erradas. Tente novamente em {max(1, remaining // 60 + 1)} min."
        else:
            username = request.form.get("username", "").strip()
            pwd = request.form.get("password", "")
            user = get_db().execute(
                "SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)
            ).fetchone()
            if user:
                password_ok = check_password_hash(user["password_hash"], pwd)
            else:
                # Roda um hash mesmo sem usuário encontrado, só pra não dar
                # pra perceber (pelo tempo de resposta) se um username existe
                # ou não.
                check_password_hash(_DUMMY_PASSWORD_HASH, pwd)
                password_ok = False
            if user and password_ok:
                _clear_login_attempts(ip)
                session["user_id"] = user["id"]
                session["csrf_token"] = secrets.token_hex(32)
                session.permanent = True
                log_audit("login_success", username=user["username"])
                nxt = request.args.get("next") or url_for("admin")
                if not _is_safe_redirect_target(nxt):
                    nxt = url_for("admin")
                return redirect(nxt)
            _register_failed_login(ip)
            log_audit("login_failed", username=username or "(vazio)")
            error = "Usuário ou senha incorretos."
    return render_template("login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    user = _current_user()
    if user:
        log_audit("logout", username=user["username"])
    session.clear()
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
    user = _current_user()
    is_owner = user["role"] == "owner"
    employees = []
    if is_owner:
        employees = [
            dict(u) for u in db.execute(
                "SELECT * FROM users WHERE role = 'staff' ORDER BY username"
            ).fetchall()
        ]
    return render_template(
        "admin.html",
        tree=tree,
        config=get_config(),
        coupons=get_coupons(),
        special_zones=special_zones,
        concentric_zones=concentric_zones,
        csrf_token=session.get("csrf_token", ""),
        current_user=dict(user),
        is_owner=is_owner,
        can_catalog=is_owner or bool(user["can_catalog"]),
        can_coupons=is_owner or bool(user["can_coupons"]),
        employees=employees,
    )


# ---------------------------------------------------------------------------
# Gestão de funcionários — só o dono cria, edita poderes ou exclui logins.
# ---------------------------------------------------------------------------
@app.route("/api/user", methods=["POST"])
@api_owner_required
def api_create_user():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username:
        return jsonify({"ok": False, "error": "digite um nome de usuário"}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "a senha precisa ter pelo menos 6 caracteres"}), 400
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return jsonify({"ok": False, "error": "esse nome de usuário já existe"}), 400
    can_catalog = 1 if data.get("can_catalog", True) else 0
    can_coupons = 1 if data.get("can_coupons", True) else 0
    cur = db.execute(
        "INSERT INTO users (username, password_hash, role, can_catalog, can_coupons, is_active, created_at) "
        "VALUES (?, ?, 'staff', ?, ?, 1, ?)",
        (username, generate_password_hash(password), can_catalog, can_coupons, time.time()),
    )
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid, "username": username})


@app.route("/api/user/<int:uid>", methods=["POST"])
@api_owner_required
def api_update_user(uid):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not target:
        return jsonify({"ok": False, "error": "usuário não encontrado"}), 404
    if target["role"] == "owner":
        return jsonify({"ok": False, "error": "não é possível alterar a conta do dono por aqui"}), 400

    data = request.get_json(force=True) or {}
    fields, vals = [], []
    if "can_catalog" in data:
        fields.append("can_catalog = ?"); vals.append(1 if data["can_catalog"] else 0)
    if "can_coupons" in data:
        fields.append("can_coupons = ?"); vals.append(1 if data["can_coupons"] else 0)
    if "is_active" in data:
        fields.append("is_active = ?"); vals.append(1 if data["is_active"] else 0)
    if data.get("password"):
        if len(data["password"]) < 6:
            return jsonify({"ok": False, "error": "a senha precisa ter pelo menos 6 caracteres"}), 400
        fields.append("password_hash = ?"); vals.append(generate_password_hash(data["password"]))
    if not fields:
        return jsonify({"ok": False, "error": "nada para atualizar"}), 400

    vals.append(uid)
    db.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", vals)
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/user/<int:uid>", methods=["DELETE"])
@api_owner_required
def api_delete_user(uid):
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not target:
        return jsonify({"ok": False, "error": "usuário não encontrado"}), 404
    if target["role"] == "owner":
        return jsonify({"ok": False, "error": "não é possível excluir a conta do dono"}), 400
    db.execute("DELETE FROM users WHERE id = ?", (uid,))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
# Campos do pop-up de promoção. É gerenciado por quem pode mexer em cupons
# (mesma permissão), já que é a "cara" promocional do site.
PROMO_POPUP_TEXT_KEYS = {
    "promo_popup_badge",
    "promo_popup_title",
    "promo_popup_message",
    "promo_popup_coupon",
    "promo_popup_cta_label",
    "promo_popup_cta_link",
}


def _sanitize_promo_link(raw):
    """Só permite âncora interna, caminho interno ou http(s) — evita href com
    javascript:/data: vindo de um funcionário. Fallback seguro: #catalogo."""
    link = (raw or "").strip()
    if link.startswith(("#", "/", "http://", "https://")):
        return link[:300]
    return "#catalogo"


@app.route("/api/promo_popup", methods=["POST"])
@api_coupons_required
def api_promo_popup():
    d = request.get_json(force=True) or {}
    db = get_db()
    updates = {}
    if "promo_popup_enabled" in d:
        updates["promo_popup_enabled"] = "1" if d["promo_popup_enabled"] in (True, 1, "1", "true", "on") else "0"
    for key in PROMO_POPUP_TEXT_KEYS:
        if key not in d:
            continue
        if key == "promo_popup_cta_link":
            updates[key] = _sanitize_promo_link(d[key])
        elif key == "promo_popup_coupon":
            updates[key] = str(d[key] or "").strip().upper()[:30]
        else:
            updates[key] = str(d[key] or "").strip()[:300]
    if not updates:
        return jsonify({"ok": False, "error": "nada para salvar"}), 400
    for key, val in updates.items():
        db.execute(
            "INSERT INTO site_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, val),
        )
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/update_config", methods=["POST"])
@api_owner_required
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


# ---- Identidade Visual (logos + cores do tema) ----
# Chaves que carregam uma cor hex. São injetadas dentro de um bloco
# <style>:root{...}</style> no index.html, então TODAS passam por
# clean_hex_color() antes de gravar — evita injeção de CSS via painel.
THEME_COLOR_KEYS = {
    "theme_primary_color",
    "theme_primary_grad_end",
    "theme_text_on_primary_color",
    "theme_bg_color",
    "theme_card_bg_color",
    "theme_text_color",
    "theme_surface_color",
    "theme_surface_2_color",
    "theme_border_color",
    "theme_accent_color",
    "theme_accent_soft_color",
    "theme_text_dim_color",
}


@app.route("/api/update_theme_colors", methods=["POST"])
@api_owner_required
def api_update_theme_colors():
    data = request.get_json(force=True) or {}
    db = get_db()
    for key in THEME_COLOR_KEYS:
        if key in data:
            color = clean_hex_color(data[key])
            if color is None:
                continue  # ignora valores fora do formato hex
            db.execute(
                "INSERT INTO site_config (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, color),
            )
    # Ângulo do degradê dos botões: só um inteiro 0–360 (vai para o CSS).
    if "theme_grad_angle" in data:
        try:
            angle = int(float(str(data["theme_grad_angle"]).strip()))
        except (TypeError, ValueError):
            angle = None
        if angle is not None:
            angle = max(0, min(360, angle))
            db.execute(
                "INSERT INTO site_config (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("theme_grad_angle", str(angle)),
            )
    db.commit()
    return jsonify({"ok": True})


def _autocrop_logo(img, pad_ratio=0.04):
    """Recorta as bordas vazias (transparentes ou de cor uniforme) do logo e
    devolve o desenho com uma pequena margem proporcional. Sem isso, um logo
    com muito espaço em volta fica minúsculo quando renderizado com altura
    fixa (navbar/rodapé). Recebe a imagem já em modo RGBA ou RGB."""
    if img.mode == "RGBA":
        bbox = img.getchannel("A").getbbox()
    else:
        bg = Image.new(img.mode, img.size, img.getpixel((0, 0)))
        bbox = ImageChops.difference(img, bg).getbbox()
    if bbox:
        img = img.crop(bbox)
    pad = max(1, round(max(img.size) * pad_ratio))
    fill = (0, 0, 0, 0) if img.mode == "RGBA" else (255, 255, 255)
    return ImageOps.expand(img, border=pad, fill=fill)


@app.route("/api/upload_logo", methods=["POST"])
@api_owner_required
def api_upload_logo():
    slot = request.form.get("slot")
    if slot not in LOGO_SLOTS:
        return jsonify({"ok": False, "error": "slot inválido"}), 400
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "sem arquivo"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "nome vazio"}), 400
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in LOGO_ALLOWED_EXT:
        return jsonify({"ok": False, "error": "envie um arquivo PNG ou SVG"}), 400

    fname = f"logo-{uuid.uuid4().hex}.{ext}"
    path = os.path.join(app.config["UPLOAD_DIR"], secure_filename(fname))

    if ext == "svg":
        raw = file.read()
        sanitized = sanitize_svg(raw)
        if sanitized is None:
            return jsonify({"ok": False, "error": "arquivo SVG inválido ou não permitido"}), 400
        with open(path, "wb") as fp:
            fp.write(sanitized)
    else:
        try:
            img = Image.open(file.stream)
            img.load()
        except Exception:
            return jsonify({"ok": False, "error": "não foi possível processar a imagem"}), 400
        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        img = img.convert("RGBA") if has_alpha else img.convert("RGB")
        img = _autocrop_logo(img)
        w, h = img.size
        if max(w, h) > LOGO_MAX_DIM:
            ratio = LOGO_MAX_DIM / max(w, h)
            img = img.resize((max(1, round(w * ratio)), max(1, round(h * ratio))), Image.LANCZOS)
        img.save(path, "PNG", optimize=True)

    image_url = url_for("uploaded_file", filename=fname)
    db = get_db()
    db.execute(
        "INSERT INTO site_config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (LOGO_SLOTS[slot], image_url),
    )
    db.commit()
    return jsonify({"ok": True, "image_url": image_url})


@app.route("/api/upload_favicon", methods=["POST"])
@api_owner_required
def api_upload_favicon():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "sem arquivo"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "nome vazio"}), 400
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in FAVICON_ALLOWED_EXT:
        return jsonify({"ok": False, "error": "envie um arquivo PNG, JPG ou WEBP"}), 400

    try:
        img = Image.open(file.stream)
        img = ImageOps.exif_transpose(img)  # corrige rotação de fotos de celular
        img.load()
    except Exception:
        return jsonify({"ok": False, "error": "não foi possível processar a imagem"}), 400

    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA") if has_alpha else img.convert("RGB")
    # Recorte quadrado ao centro + reduz para 64x64 (tamanho de favicon).
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = img.resize((FAVICON_SIZE, FAVICON_SIZE), Image.LANCZOS)

    fname = f"favicon-{uuid.uuid4().hex}.png"
    path = os.path.join(app.config["UPLOAD_DIR"], secure_filename(fname))
    img.save(path, "PNG", optimize=True)

    image_url = url_for("uploaded_file", filename=fname)
    db = get_db()
    db.execute(
        "INSERT INTO site_config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        ("favicon_url", image_url),
    )
    db.commit()
    return jsonify({"ok": True, "favicon_url": image_url})


# ---- Blocos promocionais (ex: Atacado) ----
@app.route("/api/promo_block", methods=["POST"])
@api_owner_required
def api_create_promo_block():
    d = request.get_json(force=True) or {}
    pid = create_promo_block(duplicate_from=d.get("duplicate_from"))
    return jsonify({"ok": True, "id": pid})


@app.route("/api/promo_block/<int:pid>", methods=["POST"])
@api_owner_required
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
@api_owner_required
def api_delete_promo_block(pid):
    db = get_db()
    db.execute("DELETE FROM promo_blocks WHERE id = ?", (pid,))
    db.execute("DELETE FROM site_config WHERE key LIKE ?", (f"promo_{pid}_%",))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/promo_block/<int:pid>/move", methods=["POST"])
@api_owner_required
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
@api_coupons_required
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
@api_coupons_required
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
@api_coupons_required
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
@api_owner_required
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
@api_owner_required
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
@api_owner_required
def api_delete_shipping_zone(zid):
    db = get_db()
    db.execute("DELETE FROM shipping_zones WHERE id = ?", (zid,))
    db.commit()
    return jsonify({"ok": True})


# ---- Brands ----
@app.route("/api/brand", methods=["POST"])
@api_catalog_required
def api_create_brand():
    name = (request.get_json(force=True).get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "nome vazio"}), 400
    db = get_db()
    cur = db.execute("INSERT INTO brands (name) VALUES (?)", (name,))
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid, "name": name})


@app.route("/api/brand/<int:bid>", methods=["POST"])
@api_catalog_required
def api_update_brand(bid):
    name = (request.get_json(force=True).get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "nome vazio"}), 400
    db = get_db()
    brand = db.execute("SELECT id FROM brands WHERE id = ?", (bid,)).fetchone()
    if not brand:
        return jsonify({"ok": False, "error": "marca não encontrada"}), 404
    db.execute("UPDATE brands SET name = ? WHERE id = ?", (name, bid))
    db.commit()
    return jsonify({"ok": True, "name": name})


@app.route("/api/brand/<int:bid>", methods=["DELETE"])
@api_catalog_required
def api_delete_brand(bid):
    db = get_db()
    brand = db.execute("SELECT name FROM brands WHERE id = ?", (bid,)).fetchone()
    if not brand:
        return jsonify({"ok": False, "error": "marca não encontrada"}), 404
    # Exclusão em cascata (apaga todos os modelos/sabores da marca junto) —
    # exige repetir o nome exato como confirmação, porque um clique de
    # "OK" no confirm() do navegador não protege nada contra uma chamada
    # direta à API (sessão roubada, por exemplo).
    confirm_name = (request.get_json(silent=True) or {}).get("confirm_name", "").strip()
    if confirm_name != brand["name"]:
        return jsonify({"ok": False, "error": "digite o nome exato da marca para confirmar a exclusão"}), 400
    db.execute("DELETE FROM brands WHERE id = ?", (bid,))
    db.commit()
    return jsonify({"ok": True})


# ---- Models ----
@app.route("/api/model", methods=["POST"])
@api_catalog_required
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
@api_catalog_required
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
@api_catalog_required
def api_delete_model(mid):
    db = get_db()
    db.execute("DELETE FROM vape_models WHERE id = ?", (mid,))
    db.commit()
    return jsonify({"ok": True})


# ---- Products (Flavors) ----
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def clean_hex_color(value):
    """Só aceita cor hex (#rgb ou #rrggbb); qualquer outra coisa vira None.
    Evita injeção de CSS já que a cor é usada em style="background: ..."."""
    v = (value or "").strip()
    return v if _HEX_COLOR_RE.match(v) else None


@app.template_filter("hex_to_rgb")
def hex_to_rgb(value):
    """Converte '#rrggbb' (ou '#rgb') em 'r, g, b' para uso em
    rgba(var(--...-rgb), alpha). Sanitiza antes, então valores fora do
    formato hex caem no cinza neutro — nunca quebram o CSS injetado."""
    v = clean_hex_color(value)
    if not v:
        return "154, 151, 165"
    v = v.lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    r, g, b = int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    return f"{r}, {g}, {b}"


@app.route("/api/product", methods=["POST"])
@api_catalog_required
def api_create_product():
    d = request.get_json(force=True)
    model_id = d.get("model_id")
    name = (d.get("name") or "").strip()
    if not model_id or not name:
        return jsonify({"ok": False, "error": "dados incompletos"}), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO products (model_id, name, price, is_in_stock, color) VALUES (?,?,?,1,?)",
        (model_id, name, float(d.get("price") or 0), clean_hex_color(d.get("color"))),
    )
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid})


@app.route("/api/product/<int:pid>", methods=["POST"])
@api_catalog_required
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
    if "color" in d:
        fields.append("color = ?")
        vals.append(clean_hex_color(d["color"]))
    if not fields:
        return jsonify({"ok": False}), 400
    vals.append(pid)
    db.execute(f"UPDATE products SET {', '.join(fields)} WHERE id = ?", vals)
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/product/<int:pid>", methods=["DELETE"])
@api_catalog_required
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
@api_catalog_required
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
