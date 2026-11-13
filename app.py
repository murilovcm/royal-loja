import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from functools import wraps
from urllib.parse import urljoin
from xml.sax.saxutils import escape as xml_escape
from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException
from flask import (
    Flask, g, render_template, request, jsonify,
    redirect, url_for, send_from_directory, session, abort, Response
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps, ImageChops

from shipping import calculate_shipping, SPECIAL_ZONES, CONCENTRIC_ZONES
import pricing

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
# Os arquivos do countdown e do hero de Black Friday entram na conta: sem isso,
# um deploy que só mexesse neles manteria o ?v= antigo e o navegador do cliente
# continuaria com a versão em cache.
_VERSIONED_ASSETS = (
    ("static", "style.css"),
    ("static", "app.js"),
    ("static", "js", "countdown.js"),
    ("static", "css", "tema-blackfriday.css"),
)
ASSET_VERSION = str(int(max(
    os.path.getmtime(os.path.join(BASE_DIR, *parts))
    for parts in _VERSIONED_ASSETS
    if os.path.exists(os.path.join(BASE_DIR, *parts))
)))


@app.context_processor
def inject_asset_version():
    # current_year alimenta o "©" do rodapé. Antes o ano estava escrito à mão no
    # template (junto do nome de marca fixo), então envelhecia sozinho a cada
    # virada de ano em todas as lojas.
    return {"asset_v": ASSET_VERSION, "current_year": datetime.now().year}


@app.context_processor
def inject_config():
    """Deixa a config da loja (site_config) disponível em TODOS os templates
    como `config.*` — inclusive login.html, que não recebe config pela rota.
    Rotas que passam config=get_config() explicitamente continuam funcionando
    (o kwarg explícito do render_template tem prioridade sobre o processor)."""
    return {"config": get_config()}


@app.context_processor
def inject_site_urls():
    """URLs absolutas derivadas do HOST DA REQUISIÇÃO — nunca de domínio fixo.

    O mesmo código roda em royalpodsslz.com, vaporstoreslz.com e podsaoluis.com,
    cada um num serviço próprio do EasyPanel. Um domínio escrito no código faria
    duas das três lojas apontarem canonical/og:url para a terceira, que é a
    forma mais rápida de sumir do índice do Google.

    `request.url_root` já sai correto atrás do proxy porque o ProxyFix está com
    x_proto=1 (respeita X-Forwarded-Proto, então detecta https) — ver a
    configuração do wsgi_app mais acima.
    """
    root = request.url_root

    def abs_url(path):
        """Caminho do banco (ex: /static/uploads/logo-x.png) -> URL absoluta.
        Deixa passar quem já é absoluto: o painel permite colar uma URL pronta
        no favicon, e og:image/JSON-LD exigem URL absoluta de qualquer forma."""
        if not path:
            return ""
        if path.startswith(("http://", "https://")):
            return path
        return urljoin(root, path)

    return {"site_url": root, "abs_url": abs_url}


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
        # Google Fonts: única origem externa liberada, e só para estilo e
        # arquivo de fonte (o letreiro do hero de Black Friday vem de lá).
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data:; "
        "font-src 'self' https://fonts.gstatic.com; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    # Painel e API nunca devem aparecer em busca. O robots.txt pede para não
    # rastrear, mas robots.txt só barra o RASTREIO: uma URL descoberta por link
    # externo ainda pode ser indexada só pelo endereço. O X-Robots-Tag é o que
    # de fato tira da indexação.
    if request.path.startswith("/admin") or request.path.startswith("/api/"):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
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


def _write_api_guard(permission_check=None, audit=True):
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
            if audit:
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
# Leitura só do dono SEM gravar no audit_log: a aba Métricas consulta o
# "online agora" a cada 30 s, e isso afogaria o log de ações de verdade.
api_owner_read = _write_api_guard(lambda u: False, audit=False)


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
            -- Versões do MESMO produto (Slim, geração anterior). Um modelo com
            -- parent_id preenchido não ganha card próprio no catálogo: os sabores
            -- dele entram na lista do principal, marcados com variant_label.
            -- SET NULL e não CASCADE: excluir o principal devolve a versão ao
            -- catálogo como produto independente, em vez de apagar os sabores dela.
            parent_id      INTEGER REFERENCES vape_models(id) ON DELETE SET NULL,
            variant_label  TEXT,     -- etiqueta curta dentro do pill: "Slim", "Antiga"
            variant_note   TEXT,     -- aviso ao cliente ao escolher o sabor
            variant_pos    INTEGER NOT NULL DEFAULT 0,
            -- Ordem MANUAL do card no catálogo, definida na aba "Ordem do
            -- catálogo" do painel. Menor = mais perto do começo da grade.
            catalog_pos    INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS products (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id    INTEGER NOT NULL,
            name        TEXT NOT NULL,
            price       REAL DEFAULT 0,
            is_in_stock INTEGER DEFAULT 1,
            color       TEXT,                -- cor do ponto (•) do sabor no card; NULL = usa a paleta padrão
            -- Aviso do SABOR, mostrado quando o cliente clica no pill dele. É
            -- irmão de variant_note (que é da versão do aparelho) e não o
            -- substitui: um sabor de versão com aviso próprio mostra os dois.
            note        TEXT,
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

        -- Avaliações do Google, cadastradas à mão no painel (sem API do
        -- Google: a loja escolhe quais mostrar e não depende de chave/cobrança).
        -- avatar_url = foto de perfil do cliente; photo_url = foto que ele
        -- postou junto da avaliação (opcional; sem ela o card fica só texto).
        CREATE TABLE IF NOT EXISTS google_reviews (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            position   INTEGER NOT NULL DEFAULT 0,
            active     INTEGER NOT NULL DEFAULT 1,
            author     TEXT NOT NULL DEFAULT '',
            avatar_url TEXT NOT NULL DEFAULT '',
            photo_url  TEXT NOT NULL DEFAULT '',
            rating     INTEGER NOT NULL DEFAULT 5,
            text       TEXT NOT NULL DEFAULT '',
            when_label TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS coupons (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            code   TEXT NOT NULL UNIQUE,
            type   TEXT NOT NULL DEFAULT 'percent',
            value  REAL NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        );

        -- Restrição opcional de um cupom a modelos específicos. Um cupom SEM
        -- nenhuma linha aqui vale para o catálogo inteiro (comportamento padrão);
        -- com linhas, o desconto só incide sobre os sabores desses modelos.
        CREATE TABLE IF NOT EXISTS coupon_models (
            coupon_id INTEGER NOT NULL,
            model_id  INTEGER NOT NULL,
            PRIMARY KEY (coupon_id, model_id),
            FOREIGN KEY (coupon_id) REFERENCES coupons(id) ON DELETE CASCADE,
            FOREIGN KEY (model_id)  REFERENCES vape_models(id) ON DELETE CASCADE
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

        -- Métricas de visita (aba Métricas, só o dono). Um resumo por dia,
        -- guardado para sempre; nada pessoal fica nele.
        CREATE TABLE IF NOT EXISTS metrics_daily (
            day       TEXT PRIMARY KEY,           -- 'AAAA-MM-DD' no horário da loja
            visitors  INTEGER NOT NULL DEFAULT 0, -- visitantes únicos no dia
            pageviews INTEGER NOT NULL DEFAULT 0,
            wa_clicks INTEGER NOT NULL DEFAULT 0, -- visitantes que enviaram o pedido no WhatsApp
            mobile    INTEGER NOT NULL DEFAULT 0, -- visitantes únicos no celular
            desktop   INTEGER NOT NULL DEFAULT 0  -- visitantes únicos no PC
        );

        -- Código anônimo de quem já foi contado HOJE (hash de IP + navegador +
        -- data, sem o IP). Só serve para não contar a mesma pessoa duas vezes;
        -- dias anteriores são apagados na primeira visita do dia seguinte.
        CREATE TABLE IF NOT EXISTS metrics_seen (
            day       TEXT NOT NULL,
            vid       TEXT NOT NULL,
            pageviews INTEGER NOT NULL DEFAULT 0,
            wa        INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (day, vid)
        );

        -- Quem está com a loja aberta agora (último sinal). Linhas velhas são
        -- apagadas a cada sinal; nunca passa de alguns minutos de dados.
        CREATE TABLE IF NOT EXISTS metrics_online (
            vid       TEXT PRIMARY KEY,
            last_seen REAL NOT NULL
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
    # Migração: products ganhou `note`, o aviso por sabor. Nasce NULL em todo
    # sabor antigo, então nenhum deles passa a mostrar aviso nenhum.
    if "note" not in prod_cols:
        db.execute("ALTER TABLE products ADD COLUMN note TEXT")
        db.commit()

    # Migração: vape_models ganhou a coluna `active` (permite desativar/ocultar
    # um modelo esgotado do site sem excluí-lo). Bancos antigos recebem a coluna
    # com DEFAULT 1, então todo modelo já existente continua visível.
    model_cols = {row["name"] for row in db.execute("PRAGMA table_info(vape_models)").fetchall()}
    if "active" not in model_cols:
        db.execute("ALTER TABLE vape_models ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        db.commit()

    # Migração: vape_models ganhou as colunas de VERSÃO. Um modelo com parent_id
    # preenchido é uma variação do mesmo produto (Slim, geração anterior): ele
    # some do catálogo como card e seus sabores passam a aparecer na lista do
    # principal, marcados com a etiqueta variant_label.
    #
    # parent_id entra sem default (ou seja, NULL), que é o único jeito de o
    # SQLite aceitar ADD COLUMN com cláusula REFERENCES. Como todo modelo antigo
    # nasce com parent_id NULL, o catálogo continua exatamente como estava.
    if "parent_id" not in model_cols:
        db.execute(
            "ALTER TABLE vape_models ADD COLUMN parent_id INTEGER "
            "REFERENCES vape_models(id) ON DELETE SET NULL"
        )
        db.commit()
    if "variant_label" not in model_cols:
        db.execute("ALTER TABLE vape_models ADD COLUMN variant_label TEXT")
        db.commit()
    if "variant_note" not in model_cols:
        db.execute("ALTER TABLE vape_models ADD COLUMN variant_note TEXT")
        db.commit()
    if "variant_pos" not in model_cols:
        db.execute("ALTER TABLE vape_models ADD COLUMN variant_pos INTEGER NOT NULL DEFAULT 0")
        db.commit()

    # Migração: catalog_pos guarda a ORDEM MANUAL do catálogo, escolhida na aba
    # "Ordem do catálogo". Ela SUBSTITUI a antiga regra automática (mais
    # vendidos primeiro, depois o mais novo), e por isso a estrela ★ deixa de
    # ordenar: ela continua sendo o selo do card e a fonte da seção "Mais
    # Vendidos", mas quem decide a posição agora é o lojista.
    #
    # A semeadura copia exatamente a ordem que a loja já exibia. Assim publicar
    # esta versão não reordena nada na frente do cliente: a vitrine só muda no
    # primeiro arrasto dentro do painel.
    if "catalog_pos" not in model_cols:
        db.execute("ALTER TABLE vape_models ADD COLUMN catalog_pos INTEGER NOT NULL DEFAULT 0")
        atuais = db.execute(
            "SELECT id FROM vape_models WHERE parent_id IS NULL "
            "ORDER BY is_best_seller DESC, id DESC"
        ).fetchall()
        for pos, row in enumerate(atuais):
            db.execute("UPDATE vape_models SET catalog_pos = ? WHERE id = ?", (pos, row["id"]))
        db.commit()
    db.execute("CREATE INDEX IF NOT EXISTS idx_models_parent ON vape_models(parent_id)")
    db.commit()

    # Migração: PROMOÇÃO COM HORA MARCADA, por modelo. `desconto_valor` é o
    # desconto em reais aplicado a cada sabor do modelo (e aos das versões
    # dele); `promo_fim` é o fim em UTC, texto ISO ("2026-11-27T02:59:00Z").
    # As duas nascem NULL em todo modelo existente, ou seja, sem promoção:
    # publicar esta versão não altera nenhum preço. Ver pricing.py.
    if "desconto_valor" not in model_cols:
        db.execute("ALTER TABLE vape_models ADD COLUMN desconto_valor REAL")
        db.commit()
    if "promo_fim" not in model_cols:
        db.execute("ALTER TABLE vape_models ADD COLUMN promo_fim TEXT")
        db.commit()
    # Migração: OFERTA RELÂMPAGO, degrau extra por cima da promoção.
    # `relampago_valor` é o desconto EXTRA em reais (somado a desconto_valor);
    # `relampago_fim` é o fim em UTC (salvar + 24h, nunca além de promo_fim).
    # Nascem NULL: publicar não altera preço nenhum. Ver pricing.py.
    if "relampago_valor" not in model_cols:
        db.execute("ALTER TABLE vape_models ADD COLUMN relampago_valor REAL")
        db.commit()
    if "relampago_fim" not in model_cols:
        db.execute("ALTER TABLE vape_models ADD COLUMN relampago_fim TEXT")
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
    else:
        # A loja já existia antes deste boot (o dono já foi semeado num boot
        # anterior). Marca-a como já-semeada para que o setup_loja.py NÃO
        # reaplique as env vars por cima de edições feitas no painel a cada
        # redeploy (era o que fazia o WhatsApp voltar ao valor da env var).
        # Em loja nova (owner recém-criado acima) a flag NÃO é setada aqui: o
        # setup_loja aplica as env vars uma vez e então grava a flag.
        db.execute(
            "INSERT OR IGNORE INTO site_config (key, value) VALUES ('env_config_seeded', '1')"
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
        # Cor dos preços (cards + modal) e da seta dos cards. Padrão = cor
        # primária, para lojas antigas manterem a aparência atual.
        "theme_price_color": "#FFD60A",
        "theme_arrow_color": "#FFD60A",
        # Cor do anel animado dos botões ("+" dos cards e CTAs). Padrão = primária.
        "theme_ring_color": "#FFD60A",
        # Cor do nome da marca (ex: "LOST MARY") e do "+x sabores" nos cards.
        # Padrão = destaque suave (roxo), para não mudar lojas já publicadas.
        # Para deixar o card com uma cor de destaque só (a do preço), basta
        # apontar as duas para um cinza neutro no painel.
        "theme_brand_label_color": "#a855f7",
        "theme_flavor_more_color": "#a855f7",
        "logo_main_url": "",
        "logo_footer_url": "",
        # Hero editável por loja (campos "Hero" em Configurações Gerais).
        # Vazio = o texto derivado de store_city que a loja já mostrava quando
        # o hero era fixo no template — ver parse_hero(). Começam vazios de
        # propósito: é o que garante que ligar o campo não muda a aparência de
        # nenhuma loja antes de o dono escrever a versão dele.
        "hero_title": "",
        "hero_subtitle": "",
        # Mostrar/ocultar os dois textos do hero (aba Identidade Visual, bloco
        # "Topo da loja"). Valem sempre, com ou sem Black Friday. Começam em
        # "1" (mostrando) para publicar sem mudar loja nenhuma. Título oculto
        # continua no HTML como <h1> visualmente escondido: é o título da
        # página para o Google. Frase oculta sai da página.
        "hero_title_visible": "1",
        "hero_subtitle_visible": "1",
        # O que fica abaixo do título: "steps" (passo a passo Escolha → Envie
        # → Receba) ou "text" (a frase de apoio de hero_subtitle). Padrão
        # "steps": o passo a passo substituiu a frase nas três lojas, e a frase
        # continua no painel caso alguma precise voltar a ela.
        "hero_support": "steps",
        # Assinatura embaixo do letreiro "Black Friday", entre dois fios
        # dourados (painel → Topo da loja). Vazio = nome da loja (store_name),
        # então cada uma das três lojas já sai com o próprio nome sem mexer em
        # nada. Ver parse_hero() e BF_SIGN_MAX.
        "bf_assinatura": "",
        "store_name": "Royal",
        "store_city": "São Luís",
        # Complemento do título da aba quando `page_title` está vazio. Antes o
        # texto "Premium Vapes" estava fixo no index.html, então as três lojas
        # herdavam a mesma assinatura. Agora cada uma edita a sua no painel.
        "store_tagline": "Pods e Vapes",
        # Número do WhatsApp usado no checkout / links wa.me. Fica editável no
        # painel; o valor inicial vem da env var WHATSAPP_PHONE.
        "whatsapp_phone": os.environ.get("WHATSAPP_PHONE", ""),
        # Identidade / SEO da loja — editáveis em "Configurações Gerais" no
        # painel; valores iniciais vêm das env vars correspondentes.
        "favicon_url": os.environ.get("FAVICON_URL", ""),
        # Título da aba do navegador. Vazio usa "<nome da loja> — Premium Vapes".
        "page_title": os.environ.get("PAGE_TITLE", ""),
        "meta_description": os.environ.get("META_DESCRIPTION", ""),
        "meta_keywords": os.environ.get("META_KEYWORDS", ""),
        "instagram_url": os.environ.get("INSTAGRAM_URL", ""),
        # Mensagens pré-preenchidas nos links do WhatsApp (aba "Redes Sociais"
        # do painel). Cada botão da loja abre o WhatsApp já com um texto — todos
        # editáveis aqui. Vazio faz o index.html cair no texto padrão do template.
        "wa_msg_header": "Olá! Vim pelo site e quero fazer um pedido.",
        "wa_msg_attendant": "Olá! Vim pelo site e preciso de atendimento.",
        "wa_msg_hero": "Olá! Vim pelo site e quero saber mais sobre os produtos.",
        # Perguntas frequentes. Uma por linha, no formato "Pergunta | Resposta".
        # O pipe foi escolhido como separador por não aparecer em texto corrido
        # em português, então o funcionário não precisa escapar nada.
        "faq_enabled": "1",
        # A barra separa a parte branca da parte na cor da marca no título.
        # Sem barra, o título inteiro sai branco.
        "faq_eyebrow": "Ficou com dúvida?",
        "faq_title": "Perguntas | frequentes",
        "faq_items": (
            "Quanto tempo leva a entrega? | Na maior parte de São Luís entregamos no mesmo dia. "
            "O prazo exato a gente confirma no WhatsApp assim que o pedido chega.\n"
            "Como faço o pedido? | Escolha os produtos, toque em finalizar e o pedido vai montado "
            "para o nosso WhatsApp. Não precisa criar cadastro nem cartão no site.\n"
            "Os produtos são originais? | Sim. Trabalhamos apenas com produtos lacrados e originais, "
            "comprados de distribuidores autorizados.\n"
            "Posso pagar na entrega? | Pode. Aceitamos Pix, dinheiro e cartão na hora da entrega. "
            "No cartão de crédito há acréscimo de 5%.\n"
            "E se o produto vier com defeito? | Chame no WhatsApp em até 7 dias. Produto com defeito "
            "de fábrica, sem sinal de uso e na embalagem original, a gente troca."
        ),
        # Rodapé de confiança. São as perguntas que um comprador brasileiro faz
        # antes de fechar pedido em loja que não conhece: até onde entrega, que
        # horas atende, como paga e o que acontece se vier errado. Tudo
        # editável em "Configurações Gerais".
        "footer_delivery_area": "Entregamos em toda São Luís e região metropolitana.",
        "footer_hours": "Todos os dias, das 10h às 23h.",
        "footer_payment": "Pix, dinheiro, cartão de crédito e débito na entrega.",
        "footer_exchange": (
            "Troca em até 7 dias para produto com defeito de fábrica, "
            "sem sinal de uso e na embalagem original."
        ),
        # Linha de avisos rotativos na faixa do topo, logo abaixo do aviso
        # legal. Uma mensagem por linha; o site alterna entre elas. Editável
        # pelos funcionários em "Configurações Gerais".
        "announce_enabled": "1",
        "announce_messages": (
            "Frete grátis nos pedidos acima de R$ 250\n"
            "Entrega no mesmo dia para toda São Luís\n"
            "Pague no Pix, cartão ou dinheiro na entrega"
        ),
        # Frete grátis por valor do pedido. O benefício só vale nas zonas com
        # preço numérico até free_ship_max_zone — bolsão ("a combinar") e
        # endereço fora da área continuam como estão, porque nesses casos o
        # custo real da entrega ainda não é conhecido. Editável na aba "Frete".
        "free_ship_enabled": "1",
        "free_ship_min": "250",
        "free_ship_max_zone": "22",
        # Abaixo deste valor a economia NÃO é exibida em reais — o cliente vê
        # só "frete grátis". Nas zonas mais próximas o frete é tão barato que
        # anunciar "economia de R$ 8,00" encolhe a percepção do benefício em
        # vez de reforçá-la.
        "free_ship_min_saving": "12",
        # Avaliações do Google (aba "Informações do site"). Começa OCULTO em
        # todas as lojas: o dono cadastra, confere e só então liga. Oculto
        # some com a seção "Quem compra, recomenda" e com a linha da nota no
        # hero. Nota e total são texto livre do painel ("4,9" / "312"), porque
        # vêm de olho no perfil do Google, não de uma API.
        "reviews_enabled": "0",
        "reviews_rating": "",
        "reviews_count": "",
        "reviews_url": "",
        # Pop-up de promoção do site (gerenciado na aba Cupons do painel).
        "promo_popup_enabled": "0",
        "promo_popup_badge": "OFERTA ESPECIAL",
        "promo_popup_title": "Ganhe um desconto no seu pedido",
        "promo_popup_message": "Use o cupom abaixo no checkout e aproveite.",
        "promo_popup_coupon": "",
        "promo_popup_cta_label": "Ver catálogo",
        "promo_popup_cta_link": "#catalogo",
        # Hero de Black Friday (aba "Identidade Visual"). Começa DESLIGADO em
        # todas as lojas: ligar é decisão do dono, loja por loja. Troca só o
        # hero (entra o letreiro "Black Friday"). As ofertas com hora marcada
        # dos modelos NÃO dependem disto: são do sistema e funcionam com este
        # botão ligado ou desligado.
        "bf_tema_ativo": "0",
        # Seção "Mais Vendidos" da loja: pode ser ocultada e renomeada no
        # painel (aba "Ordem do catálogo"). Os padrões reproduzem a loja como
        # ela sempre foi, então publicar esta versão não muda nada.
        "best_enabled": "1",
        "best_title": "Mais Vendidos",
        # Seção de ofertas da loja: nome e ícone do título, editáveis no painel
        # (aba Catálogo). O ícone é "clock" (relógio) ou "bolt" (raio, para
        # promoção relâmpago). Os padrões são o que a seção sempre mostrou.
        "offers_title": "Ofertas com hora marcada",
        "offers_icon": "clock",
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

    # Limpeza única (uma vez por banco): `hero_title`/`hero_subtitle` existiam
    # no site_config mas nenhum template os lia — um redesign passado fixou o
    # hero no index.html e deixou as chaves órfãs, congeladas no texto semeado
    # ("Sabor que reina. Qualidade Royal."). Agora que os campos voltaram a
    # alimentar o hero, esse valor precisa sair: sem isto, Vapor Store e Pods
    # Ilha passariam a exibir "Qualidade Royal" no <h1> no primeiro deploy.
    # Só apaga se o valor for EXATAMENTE o legado — texto que o lojista tenha
    # escrito fica intacto. A flag garante uma passada só, então o dono pode
    # apagar o campo de propósito depois sem que isto o reescreva.
    if db.execute("SELECT 1 FROM site_config WHERE key = 'hero_legacy_cleared'").fetchone() is None:
        for key, legado in (
            ("hero_title", "Sabor que reina. Qualidade Royal."),
            ("hero_subtitle", "Os melhores pods descartáveis com a curadoria mais premium do Brasil."),
        ):
            db.execute(
                "UPDATE site_config SET value = '' WHERE key = ? AND value = ?",
                (key, legado),
            )
        db.execute(
            "INSERT OR IGNORE INTO site_config (key, value) VALUES ('hero_legacy_cleared', '1')"
        )
        db.commit()

    # Correção única (uma vez por banco): o ticker do topo foi semeado
    # anunciando "frete grátis acima de R$ 200", mas o valor virou R$ 250 e
    # agora existe regra de verdade aplicando isso no carrinho. Bancos já
    # publicados continuariam prometendo R$ 200 na faixa enquanto o checkout
    # exige R$ 250 — contradição que chega ao cliente. Só reescreve se o texto
    # for EXATAMENTE o semeado; mensagem que o lojista tenha personalizado
    # fica intacta, e a flag garante uma passada só.
    if db.execute("SELECT 1 FROM site_config WHERE key = 'announce_freeship_250'").fetchone() is None:
        db.execute(
            "UPDATE site_config SET value = REPLACE(value, ?, ?) "
            "WHERE key = 'announce_messages' AND value LIKE ?",
            (
                "Frete grátis nos pedidos acima de R$ 200",
                "Frete grátis nos pedidos acima de R$ 250",
                "%Frete grátis nos pedidos acima de R$ 200%",
            ),
        )
        db.execute(
            "INSERT OR IGNORE INTO site_config (key, value) VALUES ('announce_freeship_250', '1')"
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


REVIEWS_MAX = 12


def get_google_reviews(only_active=False):
    """Avaliações do Google na ordem escolhida no painel.

    Na loja (only_active=True) só entram as ativas e com texto, até
    REVIEWS_MAX: um carrossel com 30 cards ninguém percorre, e o cliente
    precisa de uma amostra boa, não do arquivo inteiro.
    """
    rows = get_db().execute(
        "SELECT * FROM google_reviews ORDER BY position, id"
    ).fetchall()
    reviews = [dict(r) for r in rows]
    if only_active:
        reviews = [r for r in reviews if r["active"] and r["text"].strip() and r["author"].strip()]
        reviews = reviews[:REVIEWS_MAX]
    return reviews


def parse_reviews_summary(config):
    """Resumo da nota para a linha do hero. Devolve None quando o recurso está
    oculto ou a nota não foi preenchida — e o template simplesmente não
    desenha a linha."""
    if config.get("reviews_enabled") != "1":
        return None
    rating = (config.get("reviews_rating") or "").strip()
    if not rating:
        return None
    count = (config.get("reviews_count") or "").strip()
    return {"rating": rating, "count": count, "url": (config.get("reviews_url") or "").strip()}


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
    """Lista os cupons com um campo `value_display` já formatado para a tabela do admin.

    Cada cupom também traz `model_ids` (lista dos modelos aos quais está restrito)
    e `scope_display` (rótulo pronto para a coluna "Aplica a"). Cupom sem modelos
    associados vale para o catálogo inteiro.
    """
    db = get_db()
    rows = db.execute("SELECT * FROM coupons ORDER BY id DESC").fetchall()
    # Agrupa os modelos de cada cupom em uma só consulta (com nome de marca/modelo
    # para o rótulo do admin), evitando uma query por cupom.
    links = db.execute(
        """
        SELECT cm.coupon_id, cm.model_id, m.name AS model_name, b.name AS brand_name
        FROM coupon_models cm
        JOIN vape_models m ON m.id = cm.model_id
        JOIN brands b ON b.id = m.brand_id
        ORDER BY b.name, m.name
        """
    ).fetchall()
    models_by_coupon = {}
    for l in links:
        models_by_coupon.setdefault(l["coupon_id"], []).append(l)

    coupons = []
    for r in rows:
        c = dict(r)
        if c["type"] == "percent":
            v = c["value"]
            c["value_display"] = (f"{v:.0f}%" if v == int(v) else f"{v:.2f}%".replace(".", ","))
        else:
            c["value_display"] = "R$ " + f"{c['value']:.2f}".replace(".", ",")
        clinks = models_by_coupon.get(c["id"], [])
        c["model_ids"] = [l["model_id"] for l in clinks]
        if clinks:
            names = [f"{l['brand_name']} {l['model_name']}" for l in clinks]
            c["scope_display"] = names[0] if len(names) == 1 else f"{names[0]} +{len(names) - 1}"
            c["scope_title"] = ", ".join(names)
        else:
            c["scope_display"] = "Todos os produtos"
            c["scope_title"] = "Vale para o catálogo inteiro"
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


def _promo_of(model, parent=None):
    """(desconto_valor, promo_fim, relampago_valor, relampago_fim) que vale
    para os sabores de um modelo.
    Versões (Slim, geração anterior) herdam a promoção do produto principal:
    para o cliente é o mesmo card, com um relógio só — a mesma regra pela qual
    o cupom do principal já alcança as versões."""
    dono = parent if parent is not None else model
    return (dono["desconto_valor"], dono["promo_fim"],
            dono["relampago_valor"], dono["relampago_fim"])


def _depois(pe):
    """`depois` do pricing no formato dos sabores/itens do carrinho."""
    d = pe["depois"]
    if not d:
        return None
    return {"price": d["final"], "promo_desconto": d["desconto"], "promo_fim": d["fim"]}


def _flavors_of(db, model, promo=(None, None, None, None), agora=None):
    """Sabores de UM modelo, já carimbados com os dados da versão a que pertencem.

    O carimbo é o que permite achatar várias versões numa lista só: o sabor sabe
    de qual aparelho ele é, então o modal troca foto/puffs/título e mostra o aviso
    sem precisar de um segundo eixo de seleção.

    `version_label` vazio significa "é da versão principal" — é essa string vazia
    que o front usa para decidir se desenha a etiqueta e o aviso.
    """
    rows = db.execute(
        "SELECT * FROM products WHERE model_id = ? ORDER BY id", (model["id"],)
    ).fetchall()
    flavors = []
    for r in rows:
        f = dict(r)
        f["version_name"] = model["name"]                      # vai para o carrinho / WhatsApp
        f["version_label"] = (model["variant_label"] or "").strip()
        f["version_note"] = (model["variant_note"] or "").strip()
        f["version_puffs"] = model["puff_count"]
        f["version_image"] = model["image_url"]
        # Normalizado aqui, igual a version_note: o front só testa se a string
        # está vazia, sem precisar lidar com NULL vindo do banco.
        f["note"] = (f.get("note") or "").strip()
        # `price` passa a ser o preço QUE VALE AGORA (regra única em
        # pricing.preco_efetivo). O cheio vai em `price_original`, e o front
        # usa `promo_fim` para voltar a ele sozinho quando o relógio zera.
        pe = pricing.preco_efetivo(f["price"], promo[0], promo[1], agora, promo[2], promo[3])
        f["price_original"] = pe["original"]
        f["price"] = pe["final"]
        f["promo_desconto"] = pe["desconto"]
        f["promo_fim"] = pe["fim"]
        # Relâmpago: `promo_depois` é o preço da promoção normal, que volta a
        # valer quando o relâmpago zera (o navegador troca sozinho).
        f["promo_relampago"] = pe["relampago"]
        f["promo_depois"] = _depois(pe)
        flavors.append(f)
    return flavors


def build_catalog(agora=None):
    """Monta a lista de modelos com seus sabores e metadados agregados.

    Só os modelos PRINCIPAIS (parent_id NULL) viram card. As versões (Slim,
    geração anterior) não aparecem no catálogo: os sabores delas são concatenados
    na lista do principal, com o principal sempre primeiro.

    Como `min_price`, `flavor_names` e a contagem de sabores do card já são
    calculados sobre `flavors`, todos passam a considerar as versões sem
    nenhuma mudança no template.

    A ORDEM é a manual (`catalog_pos`), definida na aba "Ordem do catálogo" do
    painel — a estrela ★ não ordena mais, só marca o card e alimenta a seção
    "Mais Vendidos", que é derivada desta mesma lista e portanto herda a ordem.
    O desempate por `id DESC` só entra em cena entre posições iguais, o que
    acontece de forma passageira quando um modelo entra no catálogo pelo topo.
    """
    db = get_db()
    models = db.execute(
        """
        SELECT m.*, b.name AS brand_name
        FROM vape_models m JOIN brands b ON b.id = m.brand_id
        WHERE m.active = 1 AND m.parent_id IS NULL
        ORDER BY m.catalog_pos, m.id DESC
        """
    ).fetchall()

    agora = agora or pricing.agora_utc()
    catalog = []
    for m in models:
        promo = _promo_of(m)
        flavors = _flavors_of(db, m, promo, agora)
        # Versões ativas, na ordem definida no painel. Uma versão desativada some
        # do seletor sem que os sabores dela precisem ser apagados.
        versions = db.execute(
            """
            SELECT * FROM vape_models
            WHERE parent_id = ? AND active = 1
            ORDER BY variant_pos, id
            """,
            (m["id"],),
        ).fetchall()
        for v in versions:
            flavors.extend(_flavors_of(db, v, promo, agora))

        in_stock = [f for f in flavors if f["is_in_stock"]]
        vitrine = in_stock or flavors
        # O sabor mais barato À VENDA define o "a partir de". Com promoção, o
        # card mostra o de/por desse mesmo sabor.
        barato = min(vitrine, key=lambda f: f["price"]) if vitrine else None
        min_price = barato["price"] if barato else 0
        # O card só entra em promoção se ela vale para algum sabor à venda.
        em_promo = [f for f in vitrine if f["promo_fim"]]
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
                # Texto extra que a busca do catálogo procura junto do nome do
                # modelo. Sem isto, uma versão perderia a busca ao deixar de ter
                # card próprio: quem digita "slim" hoje acha o card "V150 Slim",
                # e passaria a não achar nada.
                "version_search": " ".join(
                    [v["name"] for v in versions]
                    + [v["variant_label"] for v in versions if v["variant_label"]]
                ),
                "min_price": min_price,
                # Promoção do card (0/None = sem promoção). `promo_fim` é o
                # texto ISO em UTC que alimenta o data-promo-fim do countdown.
                "min_price_original": barato["price_original"] if barato else 0,
                "promo_desconto": em_promo[0]["promo_desconto"] if em_promo else 0,
                "promo_fim": em_promo[0]["promo_fim"] if em_promo else None,
                # Relâmpago do card e o que vale depois dele (preço "a partir
                # de" e desconto da promoção normal), para o card trocar sozinho.
                "promo_relampago": bool(em_promo and em_promo[0]["promo_relampago"]),
                "promo_depois": (
                    {"min_price": barato["promo_depois"]["price"],
                     "promo_desconto": barato["promo_depois"]["promo_desconto"],
                     "promo_fim": barato["promo_depois"]["promo_fim"]}
                    if em_promo and em_promo[0]["promo_relampago"] and barato and barato["promo_depois"]
                    else None
                ),
            }
        )
    return catalog


def ofertas_do_catalogo(catalog):
    """Modelos com promoção ativa, do que acaba primeiro para o que acaba por
    último. Alimenta a seção de ofertas e o destaque "próxima oferta" do topo.
    Lista vazia faz os dois sumirem do HTML."""
    return sorted((m for m in catalog if m["promo_fim"]), key=lambda m: m["promo_fim"])


def destaques_do_hero(ofertas):
    """Entradas do card "Acaba primeiro" embaixo do hero, em ordem de término.

    Um modelo em relâmpago entra DUAS vezes: a entrada do relâmpago (acaba
    primeiro) e a da promoção normal dele, mais adiante na fila. Quando o
    relâmpago zera, o countdown.js remove a primeira e revela a próxima da
    fila, sem nenhuma lógica nova no navegador."""
    out = []
    for m in ofertas:
        out.append({"m": m, "fim": m["promo_fim"], "price": m["min_price"],
                    "relampago": m["promo_relampago"]})
        if m["promo_depois"]:
            out.append({"m": m, "fim": m["promo_depois"]["promo_fim"],
                        "price": m["promo_depois"]["min_price"], "relampago": False})
    return sorted(out, key=lambda e: e["fim"])


# Ícone de cada pergunta frequente, escolhido pelo QUE A PERGUNTA DIZ.
#
# Não dá para amarrar ícone à posição ("a terceira pergunta é a do frete"): o
# texto vem do painel e é diferente em cada loja, então bastaria o lojista
# reordenar ou reescrever uma pergunta para todos os ícones saírem errados.
#
# A ordem das regras é a precedência, e ela importa. "Posso pagar na entrega?"
# casa com pagamento E com entrega — e o ícone certo é o de pagamento, que é o
# assunto da pergunta. Por isso i-truck fica por último: é a regra mais ampla.
#
# A comparação é por PREFIXO DE PALAVRA INTEIRA, nunca por trecho solto:
# "hora" precisa pegar "horário" e "horas" sem pegar "agora".
FAQ_ICON_RULES = (
    ("i-card",    ("pagar", "pagamento", "paga", "pix", "cartao", "dinheiro", "credito", "debito", "parcel")),
    ("i-refresh", ("defeito", "troca", "trocar", "devolv", "arrepend", "estragou")),
    ("i-shield",  ("origina", "lacrad", "garantia", "procedencia", "autentic", "falsific", "seguro")),
    ("i-cart",    ("pedido", "pedir", "comprar", "compra", "cadastro", "carrinho", "finalizar", "encomend")),
    ("i-grid",    ("estoque", "disponiv", "catalogo", "variedade")),
    ("i-clock",   ("horario", "hora", "atendimento", "atende", "aberto", "abre", "fecha", "domingo", "feriado")),
    ("i-home",    ("retirar", "retirada", "retiro", "balcao")),
    ("i-truck",   ("entrega", "entregar", "entregam", "chega", "prazo", "frete", "bairro", "demora", "receb", "envio")),
)
FAQ_ICON_FALLBACK = "i-help"


def _palavras(texto):
    """Quebra o texto em palavras sem acento e em minúsculas, para o
    mapeamento de ícone não depender de o lojista digitar "cartão" ou
    "cartao", "horário" ou "horario"."""
    decomposto = unicodedata.normalize("NFKD", (texto or "").lower())
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", sem_acento)


def faq_icon(pergunta):
    """Id do <symbol> do sprite que ilustra esta pergunta."""
    palavras = _palavras(pergunta)
    for icone, prefixos in FAQ_ICON_RULES:
        for prefixo in prefixos:
            if any(p.startswith(prefixo) for p in palavras):
                return icone
    return FAQ_ICON_FALLBACK


def parse_faq(config):
    """Lê `faq_items` ("Pergunta | Resposta", uma por linha) e devolve a lista
    de {q, a}. Fonte única: alimenta ao mesmo tempo a seção visível do site e o
    JSON-LD de FAQPage, que precisam bater exatamente — o Google exige que o
    conteúdo marcado esteja visível na página.

    O pipe foi escolhido como separador por não aparecer em texto corrido em
    português; se a RESPOSTA contiver um, ele é preservado (só o primeiro pipe
    separa pergunta de resposta).
    """
    faq = []
    for linha in (config.get("faq_items") or "").split("\n"):
        partes = linha.split("|")
        # Mesma regra que o index.html aplicava inline antes desta função
        # existir: precisa de pergunta e de um primeiro trecho de resposta não
        # vazios. Mantida igual de propósito, para nenhuma loja perder ou ganhar
        # uma pergunta na tela por causa desta refatoração.
        if len(partes) < 2 or not partes[0].strip() or not partes[1].strip():
            continue
        pergunta = partes[0].strip()
        faq.append({
            "q": pergunta,
            "a": "|".join(partes[1:]).strip(),
            "icon": faq_icon(pergunta),
        })
    return faq


# Máximo de caracteres da assinatura do letreiro de Black Friday. Cabe
# "PODS ILHA" com folga; acima disso a fonte já teria de encolher demais.
BF_SIGN_MAX = 16


def parse_hero(config):
    """Título e subtítulo do hero, editáveis por loja.

    O título usa a MESMA convenção de pipe que `faq_title` já usa no painel: os
    trechos em posição ímpar (entre pipes) ganham a pílula na cor da marca, o
    resto sai em texto normal.

        "Pods de qualidade em | São Luís | você encontra aqui"
                                ^^^^^^^^ vira a pílula amarela

    Sem pipe nenhum, o título inteiro sai sem pílula — é uma escolha válida.

    Campo vazio reproduz exatamente o texto que a loja mostrava quando o hero
    era fixo no template, montado com store_city. Ou seja: destravar o campo
    não muda a aparência de loja nenhuma; ele só passa a poder ser mudado.
    """
    city = (config.get("store_city") or "").strip() or "São Luís"

    raw = (config.get("hero_title") or "").strip()
    if not raw:
        raw = f"Pods de qualidade em | {city} | você encontra aqui"

    segments = []
    for i, parte in enumerate(raw.split("|")):
        parte = parte.strip()
        if not parte:
            continue
        # A paridade vem do índice ORIGINAL, então um pipe sobrando no texto
        # não inverte quem recebe a pílula.
        segments.append({"text": parte, "accent": i % 2 == 1})

    subtitle = (config.get("hero_subtitle") or "").strip()
    if not subtitle:
        subtitle = (
            f"Entrega rápida em toda {city}. "
            "Produtos originais, pedido direto pelo WhatsApp."
        )

    # Assinatura do letreiro de Black Friday. Espaços repetidos viram um só
    # (cada caractere vira uma letra espaçada no template) e o texto é cortado
    # em BF_SIGN_MAX: o app.js encolhe a fonte para caber entre os fios, e
    # o limite garante que mesmo o nome mais longo continue legível.
    bf_sign = " ".join((config.get("bf_assinatura") or "").split())
    if not bf_sign:
        bf_sign = " ".join((config.get("store_name") or "").split())
    bf_sign = bf_sign[:BF_SIGN_MAX].strip()

    return {
        "segments": segments,
        "subtitle": subtitle,
        "bf_sign": bf_sign,
        "title_visible": config.get("hero_title_visible") != "0",
        "subtitle_visible": config.get("hero_subtitle_visible") != "0",
        # Qualquer valor que não seja "text" cai no passo a passo, o padrão.
        "support": "text" if config.get("hero_support") == "text" else "steps",
    }


# Marcador de cor dos avisos rotativos: "[#FF3B30]R$ 250[/]". Só casa com hex
# válido e com o par completo; qualquer outra coisa (colchete solto, cor
# inventada, "[/]" sem abertura) fica como texto literal na faixa. A cor sai
# num style="color: ..." no template, então aceitar SÓ hex é o que impede
# injeção de CSS pelo painel — mesma regra do clean_hex_color().
_ANNOUNCE_COLOR_RE = re.compile(r"\[(#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}))\](.+?)\[/\]")
# Teto de composição, não técnico: uma faixa girando entre dez frases vira
# ruído e ninguém lê nenhuma.
ANNOUNCE_MAX = 6


def parse_announce(config):
    """Mensagens da faixa rotativa, uma por linha de `announce_messages`, cada
    uma quebrada em trechos {text, color}. `color` é None no texto normal (sai
    na cor da marca) ou o hex que o lojista escolheu no painel para aquele
    trecho.

        "Frete grátis acima de [#FF3B30]R$ 250[/]"
        -> [{"text": "Frete grátis acima de ", "color": None},
            {"text": "R$ 250", "color": "#FF3B30"}]

    O painel monta o marcador sozinho (seleciona a palavra, clica na cor), mas
    ele também pode ser digitado à mão.
    """
    msgs = []
    for linha in (config.get("announce_messages") or "").split("\n"):
        linha = linha.strip()
        if not linha:
            continue
        segments = []
        pos = 0
        for m in _ANNOUNCE_COLOR_RE.finditer(linha):
            if m.start() > pos:
                segments.append({"text": linha[pos:m.start()], "color": None})
            segments.append({"text": m.group(2), "color": m.group(1)})
            pos = m.end()
        if pos < len(linha):
            segments.append({"text": linha[pos:], "color": None})
        msgs.append(segments)
        if len(msgs) == ANNOUNCE_MAX:
            break
    return msgs


def build_seo(config):
    """Título, descrição e imagem da página, tudo derivado de site_config.

    Nada aqui pode ser fixo por loja: o mesmo código serve os três domínios.
    Onde o painel está vazio, deriva-se de store_name/store_city/store_tagline.
    """
    store = (config.get("store_name") or "").strip() or "Loja"
    city = (config.get("store_city") or "").strip()
    tagline = (config.get("store_tagline") or "").strip() or "Pods e Vapes"

    title = (config.get("page_title") or "").strip() or f"{store} | {tagline}"

    description = (config.get("meta_description") or "").strip()
    if not description:
        # Rede de segurança para a loja nunca ficar SEM descrição: era com o
        # campo vazio que o Google montava o snippet sozinho e escolhia o aviso
        # de idade. Por ser derivado, sai parecido entre as três lojas —
        # preencher "Meta description" no painel de cada uma substitui isto e é
        # o que realmente diferencia uma da outra.
        onde = f" em {city}" if city else ""
        description = (
            f"{store}: {tagline.lower()}{onde}. Veja o catálogo com preços e "
            "sabores disponíveis e faça seu pedido direto pelo WhatsApp."
        )

    # og:image. O logo da loja é o que o painel garante existir; vira absoluto
    # no template (abs_url), porque redes sociais e WhatsApp ignoram caminho
    # relativo.
    image = (config.get("logo_main_url") or "").strip() or url_for(
        "static", filename="logo.png"
    )

    return {"title": title, "description": description, "image": image}


def build_jsonld(config, faq):
    """Dados estruturados da home: Organization + FAQPage.

    Organization, e não LocalBusiness/Store, porque não publicamos endereço
    físico — e LocalBusiness sem `address` é marcação fraca, que o Google
    costuma simplesmente descartar. Se um dia o endereço for publicado no site,
    trocar o @type e acrescentar `address` é o único ajuste necessário.

    FAQPage só entra quando a seção de perguntas está mesmo VISÍVEL na página
    (mesma condição e mesmo limite de 10 que o template usa): marcar conteúdo
    que o visitante não vê é violação das diretrizes de dados estruturados.
    """
    root = request.url_root

    def _abs(path):
        if not path:
            return ""
        if path.startswith(("http://", "https://")):
            return path
        return urljoin(root, path)

    store = (config.get("store_name") or "").strip() or "Loja"
    city = (config.get("store_city") or "").strip()
    logo = _abs(
        (config.get("logo_main_url") or "").strip()
        or url_for("static", filename="logo.png")
    )

    org = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": store,
        "url": root,
        "logo": logo,
        "image": logo,
    }
    if city:
        org["areaServed"] = city
    instagram = (config.get("instagram_url") or "").strip()
    if instagram:
        org["sameAs"] = [instagram]
    # Mesmo fallback de telefone que o template usa nos links wa.me, para o
    # dado estruturado nunca divergir do botão que o cliente clica.
    phone = "".join(
        ch for ch in (config.get("whatsapp_phone") or WHATSAPP_PHONE) if ch.isdigit()
    )
    if phone:
        org["contactPoint"] = {
            "@type": "ContactPoint",
            "contactType": "sales",
            "telephone": f"+{phone}",
            "availableLanguage": "Portuguese",
        }

    blocks = [org]

    if config.get("faq_enabled") == "1" and faq:
        blocks.append(
            {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["q"],
                        "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
                    }
                    for item in faq[:10]
                ],
            }
        )

    return blocks


# ---------------------------------------------------------------------------
# Rotas públicas
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Acessório: cabo USB-C
#
# O cabo é um produto ÚNICO (todos iguais), então mora em site_config, junto
# das demais configurações de instância — e NÃO em `products`, que exige um
# model_id e o colocaria dentro da árvore marca > modelo > sabor, obrigando a
# escondê-lo da grade, do "a partir de", dos mais vendidos e da lista de
# modelos dos cupons. No carrinho ele entra com o id reservado "cable"
# (string), que nunca colide com os ids numéricos dos sabores.
# ---------------------------------------------------------------------------
def get_cable(config):
    """Config do cabo pronta para o template.

    Preço inválido ou nome vazio DESLIGAM a oferta em vez de virarem 0/""
    silenciosamente: melhor não oferecer nada do que oferecer um cabo sem
    nome por R$ 0,00 porque o lojista salvou o formulário pela metade."""
    try:
        price = round(float(config.get("cable_price") or 0), 2)
    except (TypeError, ValueError):
        price = 0.0
    name = (config.get("cable_name") or "").strip()
    return {
        "enabled": config.get("cable_enabled") == "1" and price > 0 and bool(name),
        "name": name,
        "price": price,
        "image": config.get("cable_image") or "",
    }


# ---------------------------------------------------------------------------
# Horário de funcionamento por dia da semana
# ---------------------------------------------------------------------------
# Mora em site_config["store_hours"] como JSON: lista de 7 itens indexada como
# o Date.getDay() do JS (0 = domingo ... 6 = sábado), cada um
# {"closed": bool, "open": "HH:MM", "close": "HH:MM"}. Fechar às "00:00"
# significa até a meia-noite; fechar ANTES da abertura (ex. 18:00 → 02:00)
# significa virar a noite e fechar no dia seguinte. Alimenta só o selo
# "Loja aberta agora" (app.js); o texto do rodapé (footer_hours) é livre e
# independente. Editável na aba "Informações do site" do painel.
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DEFAULT_DAY_HOURS = {"closed": False, "open": "10:00", "close": "23:00"}
# Ordem de exibição (segunda primeiro) com o índice getDay() correspondente.
WEEK_DAYS = [
    (1, "Segunda", "seg"), (2, "Terça", "ter"), (3, "Quarta", "qua"),
    (4, "Quinta", "qui"), (5, "Sexta", "sex"), (6, "Sábado", "sáb"),
    (0, "Domingo", "dom"),
]


def get_store_hours(config):
    """Lista de 7 dias já validada. Qualquer dia malformado (JSON quebrado,
    hora inválida) cai no padrão 10h–23h em vez de derrubar a página."""
    try:
        raw = json.loads(config.get("store_hours") or "[]")
    except (TypeError, ValueError):
        raw = []
    if not isinstance(raw, list):
        raw = []
    days = []
    for i in range(7):
        d = raw[i] if i < len(raw) and isinstance(raw[i], dict) else {}
        opn, cls = str(d.get("open", "")), str(d.get("close", ""))
        if _HHMM_RE.match(opn) and _HHMM_RE.match(cls):
            days.append({"closed": bool(d.get("closed")), "open": opn, "close": cls})
        else:
            days.append(dict(_DEFAULT_DAY_HOURS))
    return days


@app.route("/api/cable", methods=["POST"])
@api_catalog_required
def api_cable():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()[:80]
    image = (data.get("image") or "").strip()
    try:
        price = round(float(data.get("price") or 0), 2)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "preço inválido"}), 400
    if price < 0:
        return jsonify({"ok": False, "error": "preço não pode ser negativo"}), 400
    # A URL vai parar num <img> da loja: só aceitamos caminho gerado pelo
    # próprio uploader, nunca um endereço externo digitado à mão.
    if image and not image.startswith("/static/uploads/"):
        return jsonify({"ok": False, "error": "imagem inválida"}), 400

    db = get_db()
    for key, value in (
        ("cable_enabled", "1" if data.get("enabled") else "0"),
        ("cable_name", name),
        ("cable_price", f"{price:.2f}"),
        ("cable_image", image),
    ):
        db.execute(
            "INSERT INTO site_config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    db.commit()
    return jsonify({"ok": True})


@app.route("/")
def home():
    config = get_config()
    faq = parse_faq(config)
    reviews_on = config.get("reviews_enabled") == "1"
    hours = get_store_hours(config)
    agora = pricing.agora_utc()
    catalog = build_catalog(agora)
    return render_template(
        "index.html",
        config=config,
        # Hora do servidor em milissegundos: o countdown calcula o desvio do
        # relógio do cliente a partir dela (ver static/js/countdown.js).
        server_now_ms=int(agora.timestamp() * 1000),
        ofertas=ofertas_do_catalogo(catalog),
        destaques=destaques_do_hero(ofertas_do_catalogo(catalog)),
        ofertas_secao=offers_section(config),
        bf_ativo=config.get("bf_tema_ativo") == "1",
        reviews=get_google_reviews(only_active=True) if reviews_on else [],
        reviews_summary=parse_reviews_summary(config),
        cable=get_cable(config),
        store_hours=hours,
        catalog=catalog,
        brands=[dict(b) for b in get_db().execute("SELECT * FROM brands ORDER BY name").fetchall()],
        whatsapp=WHATSAPP_PHONE,
        editor=False,
        promo_blocks=get_promo_blocks(only_active=True),
        seo=build_seo(config),
        faq=faq,
        hero=parse_hero(config),
        announce=parse_announce(config),
        jsonld=build_jsonld(config, faq),
    )


@app.route("/robots.txt")
def robots_txt():
    """Servido pelo Flask (e não como arquivo em /static) de propósito: assim a
    linha Sitemap: sai com o domínio de QUEM PEDIU, e as três lojas apontam
    cada uma para o próprio sitemap sem nenhuma configuração por loja."""
    linhas = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Disallow: /api/",
        "",
        f"Sitemap: {urljoin(request.url_root, url_for('sitemap_xml'))}",
        "",
    ]
    return Response("\n".join(linhas), mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    """Sitemap com a única URL pública da loja: a home.

    `lastmod` vem da data de modificação do banco, que é o que muda quando o
    lojista mexe em produto, preço ou texto — é a informação mais honesta de
    "quando esta página mudou" que existe aqui, já que a página é montada
    inteira a partir do SQLite.
    """
    try:
        lastmod = datetime.fromtimestamp(os.path.getmtime(DB_PATH)).strftime("%Y-%m-%d")
    except OSError:
        lastmod = datetime.now().strftime("%Y-%m-%d")

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url>\n"
        f"    <loc>{xml_escape(request.url_root)}</loc>\n"
        f"    <lastmod>{lastmod}</lastmod>\n"
        "    <changefreq>weekly</changefreq>\n"
        "  </url>\n"
        "</urlset>\n"
    )
    return Response(xml, mimetype="application/xml")


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

    def _node(m):
        flavors = db.execute(
            "SELECT * FROM products WHERE model_id = ? ORDER BY id", (m["id"],)
        ).fetchall()
        return {"model": dict(m), "flavors": [dict(f) for f in flavors]}

    agora = pricing.agora_utc()

    def _promo_admin(node):
        """Promoção do modelo pronta para o formulário do painel: valor, fim
        no horário de São Luís (para o datetime-local), fim em UTC (para a
        coluna de tempo restante, calculada no navegador) e o menor preço do
        card, que alimenta a prévia e o limite do desconto."""
        m = node["model"]
        precos = [f["price"] for f in node["flavors"]]
        for v in node.get("versions", []):
            precos += [f["price"] for f in v["flavors"]]
        fim = pricing.parse_fim(m.get("promo_fim"))
        return {
            "desconto": m.get("desconto_valor") or "",
            "fim_local": pricing.utc_para_local(m.get("promo_fim")),
            "fim_utc": pricing.formata_utc(fim) if fim else "",
            "ativa": pricing.promo_ativa(m.get("desconto_valor"), m.get("promo_fim"), agora),
            "menor_preco": min(precos) if precos else 0,
            # Relâmpago (degrau por cima da oferta). O painel decide se está
            # ativo comparando o fim com a hora, igual à oferta.
            "relampago_valor": m.get("relampago_valor") or "",
            "relampago_fim_utc": m.get("relampago_fim") or "",
        }

    tree = []
    for b in brands:
        # Só os principais entram na lista; as versões ficam aninhadas dentro do
        # próprio pai. A aba Cupons percorre esta mesma árvore, então ela passa a
        # listar só os principais sem nenhuma mudança naquele template.
        models = db.execute(
            "SELECT * FROM vape_models WHERE brand_id = ? AND parent_id IS NULL ORDER BY id",
            (b["id"],),
        ).fetchall()
        mlist = []
        for m in models:
            node = _node(m)
            versions = db.execute(
                "SELECT * FROM vape_models WHERE parent_id = ? ORDER BY variant_pos, id",
                (m["id"],),
            ).fetchall()
            node["versions"] = [_node(v) for v in versions]
            node["promo"] = _promo_admin(node)
            mlist.append(node)
        tree.append({"brand": dict(b), "models": mlist})

    # Lista PLANA da aba "Ordem do catálogo": os mesmos cards que a loja mostra,
    # na mesma sequência. É por isso que ela ignora as versões (não viram card)
    # e os esgotados (não aparecem na loja) — a aba é um espelho da grade, não
    # um segundo inventário.
    catalog_order = [
        dict(r)
        for r in db.execute(
            """
            SELECT m.id, m.name, m.image_url, m.is_best_seller, b.name AS brand_name
            FROM vape_models m JOIN brands b ON b.id = m.brand_id
            WHERE m.parent_id IS NULL AND m.active = 1
            ORDER BY m.catalog_pos, m.id DESC
            """
        ).fetchall()
    ]
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
    admin_config = get_config()
    admin_hours = get_store_hours(admin_config)
    return render_template(
        "admin.html",
        tree=tree,
        catalog_order=catalog_order,
        config=admin_config,
        store_hours=admin_hours,
        week_days=WEEK_DAYS,
        google_reviews=get_google_reviews() if is_owner else [],
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


@app.route("/api/black_friday", methods=["POST"])
@api_owner_required
def api_black_friday():
    """Liga/desliga o hero de Black Friday. Só o dono, como o resto da
    Identidade Visual. O botão troca apenas o hero da loja; as ofertas com hora
    marcada são cadastradas por modelo, na aba Catálogo, e não dependem dele."""
    d = request.get_json(force=True) or {}
    if "bf_tema_ativo" not in d:
        return jsonify({"ok": False, "error": "nada para salvar"}), 400
    valor = "1" if d["bf_tema_ativo"] in (True, 1, "1", "true", "on") else "0"
    db = get_db()
    _upsert_config(db, "bf_tema_ativo", valor)
    db.commit()
    return jsonify({"ok": True, "bf_tema_ativo": valor})


BEST_TITLE_DEFAULT = "Mais Vendidos"
BEST_TITLE_MAX = 40


@app.route("/api/best_section", methods=["POST"])
@api_catalog_required
def api_best_section():
    """Seção "Mais Vendidos" da loja: mostrar/ocultar e renomear.

    Quem cuida do catálogo pode mexer (é a mesma pessoa que marca a estrela
    dos modelos). Ocultar tira só a faixa da página: a estrela continua
    marcando os cards e o filtro por ela continua existindo. Nome vazio volta
    para o padrão, em vez de deixar a seção sem título.
    """
    d = request.get_json(force=True) or {}
    updates = {}
    if "best_enabled" in d:
        updates["best_enabled"] = "1" if d["best_enabled"] in (True, 1, "1", "true", "on") else "0"
    if "best_title" in d:
        titulo = " ".join(str(d["best_title"] or "").split())[:BEST_TITLE_MAX]
        updates["best_title"] = titulo or BEST_TITLE_DEFAULT
    if not updates:
        return jsonify({"ok": False, "error": "nada para salvar"}), 400
    db = get_db()
    for key, val in updates.items():
        _upsert_config(db, key, val)
    db.commit()
    return jsonify({"ok": True, **updates})


OFFERS_TITLE_DEFAULT = "Ofertas com hora marcada"
OFFERS_TITLE_MAX = 40
# Ícones que o título da seção de ofertas aceita -> id no sprite (_icons.html).
# Lista fechada: o valor vai para um href="#..." no HTML da loja, então nada
# fora daqui é gravado.
OFFERS_ICONS = {"clock": "i-clock", "bolt": "i-bolt"}


def offers_section(config):
    """Título e ícone da seção de ofertas, já validados, para o template.
    Valor estranho no banco cai no padrão em vez de quebrar a página."""
    titulo = " ".join((config.get("offers_title") or "").split()) or OFFERS_TITLE_DEFAULT
    icone = config.get("offers_icon")
    return {"title": titulo, "icon": OFFERS_ICONS.get(icone, OFFERS_ICONS["clock"])}


@app.route("/api/offers_section", methods=["POST"])
@api_catalog_required
def api_offers_section():
    """Seção de ofertas da loja: renomear e trocar o ícone do título.

    Mesma permissão de quem cadastra as ofertas (catálogo). Nome vazio volta
    para o padrão. O ícone só aceita os da lista OFFERS_ICONS.
    """
    d = request.get_json(force=True) or {}
    updates = {}
    if "offers_title" in d:
        titulo = " ".join(str(d["offers_title"] or "").split())[:OFFERS_TITLE_MAX]
        updates["offers_title"] = titulo or OFFERS_TITLE_DEFAULT
    if "offers_icon" in d:
        if d["offers_icon"] not in OFFERS_ICONS:
            return jsonify({"ok": False, "error": "ícone inválido"}), 400
        updates["offers_icon"] = d["offers_icon"]
    if not updates:
        return jsonify({"ok": False, "error": "nada para salvar"}), 400
    db = get_db()
    for key, val in updates.items():
        _upsert_config(db, key, val)
    db.commit()
    return jsonify({"ok": True, **updates})


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
    "theme_price_color",
    "theme_arrow_color",
    "theme_ring_color",
    "theme_brand_label_color",
    "theme_flavor_more_color",
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


# ---- Avaliações do Google ----
_REVIEWS_RATING_RE = re.compile(r"^[0-5](?:[.,]\d)?$")


def _upsert_config(db, key, value):
    db.execute(
        "INSERT INTO site_config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


@app.route("/api/reviews/settings", methods=["POST"])
@api_owner_required
def api_reviews_settings():
    """Liga/oculta o recurso e grava o resumo (nota, total, link do perfil).

    Cada campo é opcional no corpo: o botão Ativo/Oculto manda só `enabled`,
    e o "Salvar resumo" manda os outros três."""
    d = request.get_json(force=True) or {}
    db = get_db()
    if "enabled" in d:
        _upsert_config(db, "reviews_enabled", "1" if d["enabled"] in (True, 1, "1", "true", "on") else "0")
    if "rating" in d:
        rating = str(d["rating"] or "").strip().replace(".", ",")
        if rating and not _REVIEWS_RATING_RE.match(rating):
            return jsonify({"ok": False, "error": "Nota inválida. Use algo como 4,9 (de 0 a 5)."}), 400
        if rating and float(rating.replace(",", ".")) > 5:
            return jsonify({"ok": False, "error": "A nota vai até 5."}), 400
        _upsert_config(db, "reviews_rating", rating)
    if "count" in d:
        raw = str(d["count"] or "").strip().replace(".", "")
        if raw and not raw.isdigit():
            return jsonify({"ok": False, "error": "Total de avaliações deve ser um número."}), 400
        _upsert_config(db, "reviews_count", raw[:7])
    if "url" in d:
        url = str(d["url"] or "").strip()
        # O link vai para um <a href> público: só http(s), nunca javascript:.
        if url and not url.startswith(("https://", "http://")):
            return jsonify({"ok": False, "error": "O link do Google deve começar com https://"}), 400
        _upsert_config(db, "reviews_url", url[:500])
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/review", methods=["POST"])
@api_owner_required
def api_create_review():
    db = get_db()
    max_pos = db.execute("SELECT COALESCE(MAX(position), 0) AS p FROM google_reviews").fetchone()["p"]
    cur = db.execute("INSERT INTO google_reviews (position) VALUES (?)", (max_pos + 1,))
    db.commit()
    row = db.execute("SELECT * FROM google_reviews WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify({"ok": True, "review": dict(row)})


@app.route("/api/review/<int:rid>", methods=["POST"])
@api_owner_required
def api_update_review(rid):
    d = request.get_json(force=True) or {}
    fields, vals = [], []
    if "author" in d:
        fields.append("author = ?")
        vals.append(str(d["author"] or "").strip()[:60])
    if "text" in d:
        # Uma avaliação é um trecho, não a resenha inteira: o card mostra até
        # 4 linhas, então o teto evita colar um texto enorme sem perceber.
        fields.append("text = ?")
        vals.append(re.sub(r"\s+", " ", str(d["text"] or "")).strip()[:400])
    if "when_label" in d:
        fields.append("when_label = ?")
        vals.append(str(d["when_label"] or "").strip()[:30])
    if "rating" in d:
        try:
            rating = int(d["rating"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "estrelas inválidas"}), 400
        fields.append("rating = ?")
        vals.append(max(1, min(5, rating)))
    if "active" in d:
        fields.append("active = ?")
        vals.append(1 if d["active"] in (True, 1, "1", "true", "on") else 0)
    for key in ("avatar_url", "photo_url"):
        if key in d:
            # Só aceita vazio (remover) ou caminho gerado pelo próprio uploader.
            url = str(d[key] or "").strip()
            if url and not url.startswith("/static/uploads/"):
                return jsonify({"ok": False, "error": "imagem inválida"}), 400
            fields.append(f"{key} = ?")
            vals.append(url)
    if not fields:
        return jsonify({"ok": False, "error": "nada para salvar"}), 400
    db = get_db()
    vals.append(rid)
    db.execute(f"UPDATE google_reviews SET {', '.join(fields)} WHERE id = ?", vals)
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/review/<int:rid>", methods=["DELETE"])
@api_owner_required
def api_delete_review(rid):
    db = get_db()
    db.execute("DELETE FROM google_reviews WHERE id = ?", (rid,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/review/<int:rid>/move", methods=["POST"])
@api_owner_required
def api_move_review(rid):
    direction = (request.get_json(force=True) or {}).get("direction")
    db = get_db()
    rows = db.execute("SELECT id, position FROM google_reviews ORDER BY position, id").fetchall()
    ids = [r["id"] for r in rows]
    if rid not in ids:
        return jsonify({"ok": False}), 404
    idx = ids.index(rid)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(ids):
        return jsonify({"ok": True})
    # Renumera tudo em sequência antes de trocar: avaliações criadas com a
    # mesma posição (ou após exclusões) não ficariam presas no lugar.
    ids[idx], ids[swap_idx] = ids[swap_idx], ids[idx]
    for pos, i in enumerate(ids):
        db.execute("UPDATE google_reviews SET position = ? WHERE id = ?", (pos, i))
    db.commit()
    return jsonify({"ok": True})


def _crop_to_ratio(img, ratio_w, ratio_h, out_w):
    """Recorte central na proporção pedida e redimensiona para `out_w` de largura."""
    w, h = img.size
    target = ratio_w / ratio_h
    if w / h > target:
        new_w = int(h * target)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    out_h = round(out_w * ratio_h / ratio_w)
    return img.resize((out_w, out_h), Image.LANCZOS)


@app.route("/api/upload_review_image", methods=["POST"])
@api_owner_required
def api_upload_review_image():
    """Foto de perfil (quadrada, 160px) ou foto da avaliação (4:3, 900px) de
    uma avaliação. Grava direto na linha da avaliação e devolve a URL."""
    kind = request.form.get("kind")
    if kind not in ("avatar", "photo"):
        return jsonify({"ok": False, "error": "tipo inválido"}), 400
    try:
        rid = int(request.form.get("review_id") or 0)
    except ValueError:
        rid = 0
    db = get_db()
    if not db.execute("SELECT 1 FROM google_reviews WHERE id = ?", (rid,)).fetchone():
        return jsonify({"ok": False, "error": "avaliação não encontrada"}), 404
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "sem arquivo"}), 400
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"ok": False, "error": "formato inválido"}), 400
    try:
        img = ImageOps.exif_transpose(Image.open(file)).convert("RGB")
        if kind == "avatar":
            img = _crop_to_ratio(img, 1, 1, 160)
        else:
            img = _crop_to_ratio(img, 4, 3, 900)
    except Exception:
        return jsonify({"ok": False, "error": "não foi possível processar a imagem"}), 400
    fname = f"review-{kind}-{uuid.uuid4().hex}.jpg"
    img.save(os.path.join(app.config["UPLOAD_DIR"], secure_filename(fname)), "JPEG", quality=86, optimize=True)
    url = url_for("uploaded_file", filename=fname)
    col = "avatar_url" if kind == "avatar" else "photo_url"
    db.execute(f"UPDATE google_reviews SET {col} = ? WHERE id = ?", (url, rid))
    db.commit()
    return jsonify({"ok": True, "url": url})


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


def _clean_model_ids(raw):
    """Normaliza o `model_ids` recebido do painel: mantém só inteiros que
    correspondem a modelos existentes. Lista vazia = cupom vale para tudo."""
    if not isinstance(raw, list):
        return []
    ids = []
    for x in raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []
    rows = get_db().execute(
        "SELECT id FROM vape_models WHERE id IN (%s)" % ",".join("?" * len(ids)), ids
    ).fetchall()
    valid = {r["id"] for r in rows}
    # Preserva a ordem de chegada, sem duplicatas.
    seen = set()
    return [i for i in ids if i in valid and not (i in seen or seen.add(i))]


def _set_coupon_models(db, coupon_id, model_ids):
    """Substitui o conjunto de modelos associados a um cupom."""
    db.execute("DELETE FROM coupon_models WHERE coupon_id = ?", (coupon_id,))
    if model_ids:
        db.executemany(
            "INSERT INTO coupon_models (coupon_id, model_id) VALUES (?, ?)",
            [(coupon_id, mid) for mid in model_ids],
        )


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
    _set_coupon_models(db, cur.lastrowid, _clean_model_ids(d.get("model_ids")))
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
    if "model_ids" in d:
        _set_coupon_models(db, cid, _clean_model_ids(d.get("model_ids")))
    if not fields:
        # Só os modelos mudaram — ainda é uma atualização válida.
        if "model_ids" in d:
            db.commit()
            return jsonify({"ok": True})
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

    Recebe os itens do carrinho (`items`: lista de {flavor_id, price, qty}) para:
      - descobrir o subtotal elegível quando o cupom é restrito a modelos
        específicos (o desconto só incide sobre os sabores desses modelos);
      - recusar cupons de valor fixo maiores que esse subtotal (cupom fixo não
        pode ultrapassar o valor sobre o qual ele incide).
    Devolve `product_ids` (ids dos sabores elegíveis) quando o cupom é restrito,
    ou null quando vale para o catálogo inteiro. O desconto em si é aplicado no
    front-end sobre esses itens.
    """
    d = request.get_json(force=True) or {}
    code = (d.get("code") or "").strip().upper()
    items = d.get("items") if isinstance(d.get("items"), list) else []

    generic_error = "Cupom inválido ou inativo"
    if not code:
        return jsonify({"ok": False, "error": generic_error}), 400

    db = get_db()
    row = db.execute(
        "SELECT * FROM coupons WHERE code = ? AND active = 1", (code,)
    ).fetchone()
    if not row:
        return jsonify({"ok": False, "error": generic_error}), 404

    # Sabores permitidos: expande os modelos do cupom para os ids de produto.
    model_rows = db.execute(
        "SELECT model_id FROM coupon_models WHERE coupon_id = ?", (row["id"],)
    ).fetchall()
    restricted = len(model_rows) > 0
    allowed_product_ids = None
    if restricted:
        model_ids = [r["model_id"] for r in model_rows]
        ph = ",".join("?" * len(model_ids))
        # O cupom marcado no modelo principal alcança também as VERSÕES dele
        # (Slim, geração anterior): para o cliente é o mesmo produto, então
        # restringir o desconto ao aparelho "certo" seria arbitrário.
        prods = db.execute(
            "SELECT id FROM products WHERE model_id IN (%s) "
            "   OR model_id IN (SELECT id FROM vape_models WHERE parent_id IN (%s))"
            % (ph, ph),
            model_ids + model_ids,
        ).fetchall()
        allowed_product_ids = {p["id"] for p in prods}

    # Subtotal elegível a partir dos itens enviados pelo carrinho.
    def _fid(it):
        try:
            return int(it.get("flavor_id"))
        except (TypeError, ValueError, AttributeError):
            return None

    # O preço de cada linha vem do SERVIDOR (pricing.preco_efetivo), não do
    # `price` que o navegador mandou: é o preço que vale agora, já com a
    # promoção do modelo se ela estiver ativa. Item sem id numérico conhecido
    # (o cabo, ou um sabor que não existe mais) não entra na base do cupom —
    # a mesma exclusão que o carrinho já faz em couponBase() no app.js.
    oficiais = precos_dos_sabores([_fid(it) for it in items if isinstance(it, dict)])

    def _line_total(it):
        oficial = oficiais.get(_fid(it))
        if not oficial:
            return 0.0
        try:
            return oficial["final"] * float(it.get("qty") or 0)
        except (TypeError, ValueError, AttributeError):
            return 0.0

    if restricted:
        eligible_subtotal = sum(
            _line_total(it) for it in items if _fid(it) in allowed_product_ids
        )
        if eligible_subtotal <= 0:
            return jsonify({
                "ok": False,
                "error": "Este cupom não vale para os produtos do seu carrinho",
            }), 400
    else:
        eligible_subtotal = sum(_line_total(it) for it in items)

    if row["type"] == "fixed" and row["value"] > eligible_subtotal:
        return jsonify({"ok": False, "error": generic_error}), 400

    return jsonify({
        "ok": True,
        "code": row["code"],
        "type": row["type"],
        "value": row["value"],
        "product_ids": sorted(allowed_product_ids) if restricted else None,
    })


# ---- Preço oficial dos sabores (cotação do carrinho) ----
def precos_dos_sabores(ids, agora=None):
    """{id do sabor: preco_efetivo + is_in_stock} para os ids pedidos.

    Uma consulta só, com a promoção já resolvida: sabor de uma VERSÃO usa o
    desconto e o fim do modelo principal. Ids desconhecidos simplesmente não
    aparecem no resultado.
    """
    ids = sorted({i for i in ids if isinstance(i, int)})
    if not ids:
        return {}
    rows = get_db().execute(
        """
        SELECT p.id, p.price, p.is_in_stock,
               COALESCE(pai.active, m.active)  AS visivel,
               m.active                        AS versao_ativa,
               CASE WHEN m.parent_id IS NULL THEN m.desconto_valor ELSE pai.desconto_valor END AS desconto_valor,
               CASE WHEN m.parent_id IS NULL THEN m.promo_fim      ELSE pai.promo_fim      END AS promo_fim,
               CASE WHEN m.parent_id IS NULL THEN m.relampago_valor ELSE pai.relampago_valor END AS relampago_valor,
               CASE WHEN m.parent_id IS NULL THEN m.relampago_fim   ELSE pai.relampago_fim   END AS relampago_fim
        FROM products p
        JOIN vape_models m ON m.id = p.model_id
        LEFT JOIN vape_models pai ON pai.id = m.parent_id
        WHERE p.id IN (%s)
        """ % ",".join("?" * len(ids)),
        ids,
    ).fetchall()
    agora = agora or pricing.agora_utc()
    out = {}
    for r in rows:
        pe = pricing.preco_efetivo(r["price"], r["desconto_valor"], r["promo_fim"], agora,
                                   r["relampago_valor"], r["relampago_fim"])
        pe["is_in_stock"] = bool(r["is_in_stock"]) and bool(r["visivel"]) and bool(r["versao_ativa"])
        out[r["id"]] = pe
    return out


@app.route("/api/cart/quote", methods=["POST"])
def api_cart_quote():
    """Cotação do carrinho (rota pública, sem login e sem estado).

    O pedido desta loja é montado no navegador e enviado pelo WhatsApp: não
    existe "pedido" no servidor para revalidar. Esta rota é a revalidação —
    o checkout pergunta aqui quanto custa cada sabor AGORA, antes de montar a
    mensagem. Se uma promoção acabou entre o cliente pôr o item no carrinho e
    finalizar, o preço devolvido já é o cheio, e o app.js avisa e recalcula.

    Recebe só ids (`items`: [{flavor_id}]). Nunca recebe nem confia em preço.
    """
    d = request.get_json(silent=True) or {}
    items = d.get("items") if isinstance(d.get("items"), list) else []
    ids = []
    for it in items[:200]:
        try:
            ids.append(int(it.get("flavor_id")))
        except (TypeError, ValueError, AttributeError):
            continue
    agora = pricing.agora_utc()
    oficiais = precos_dos_sabores(ids, agora)
    return jsonify({
        "ok": True,
        "now_ms": int(agora.timestamp() * 1000),
        "items": [
            {
                "flavor_id": fid,
                "found": fid in oficiais,
                **(
                    {
                        "price": oficiais[fid]["final"],
                        "price_original": oficiais[fid]["original"],
                        "promo_desconto": oficiais[fid]["desconto"],
                        "promo_fim": oficiais[fid]["fim"],
                        "promo_relampago": oficiais[fid]["relampago"],
                        "promo_depois": _depois(oficiais[fid]),
                        "is_in_stock": oficiais[fid]["is_in_stock"],
                    }
                    if fid in oficiais else {}
                ),
            }
            for fid in sorted(set(ids))
        ],
    })


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
def _pos_de_entrada(db):
    """Posição de quem ENTRA no catálogo: sempre à frente do primeiro card.

    Vale para os dois casos em que um card aparece do nada na loja — o modelo
    recém-criado e o que volta do estoque (`active` 0 → 1). Nenhum dos dois
    estava na lista da aba de ordem, então precisam de um destino definido;
    entrar pelo topo é o que os torna visíveis na hora, e descer é um arrasto.
    Também preserva o comportamento antigo, em que o mais novo vinha primeiro.

    Valor negativo aqui é esperado e inofensivo: o próximo salvamento da aba
    renumera a coluna inteira em 0..n.
    """
    row = db.execute(
        "SELECT MIN(catalog_pos) AS menor FROM vape_models "
        "WHERE parent_id IS NULL AND active = 1"
    ).fetchone()
    return (row["menor"] - 1) if row and row["menor"] is not None else 0


@app.route("/api/catalog/order", methods=["POST"])
@api_catalog_required
def api_catalog_order():
    """Grava a ordem manual do catálogo inteira, de uma vez só.

    O painel manda a lista completa de ids já na ordem final e o servidor
    renumera 0..n. Reescrever tudo — em vez de trocar dois vizinhos como fazem
    os blocos promo — é o que mantém a coluna sem buracos nem empates depois de
    um modelo ter entrado pelo topo com posição negativa.
    """
    ids = (request.get_json(force=True) or {}).get("ids") or []
    db = get_db()
    validos = {
        r["id"]
        for r in db.execute(
            "SELECT id FROM vape_models WHERE parent_id IS NULL AND active = 1"
        ).fetchall()
    }
    ordem = []
    for bruto in ids:
        try:
            mid = int(bruto)
        except (TypeError, ValueError):
            continue
        # Só produtos principais ativos, e sem repetir: a lista vem da tela, e
        # a API é chamável direto.
        if mid in validos and mid not in ordem:
            ordem.append(mid)

    # Faltou algum ativo? A tela está velha — outra aba (ou outro funcionário)
    # criou ou religou um modelo depois que esta página carregou. Recusar é
    # melhor do que gravar: gravar zeraria a posição de quem ficou de fora.
    if len(ordem) != len(validos):
        return jsonify({
            "ok": False,
            "error": "a lista mudou em outro lugar — recarregue a página",
        }), 409

    for pos, mid in enumerate(ordem):
        db.execute("UPDATE vape_models SET catalog_pos = ? WHERE id = ?", (pos, mid))
    db.commit()
    return jsonify({"ok": True})


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
        "INSERT INTO vape_models "
        "(brand_id, name, puff_count, image_url, is_best_seller, catalog_pos) "
        "VALUES (?,?,?,?,0,?)",
        (brand_id, name, puff, "", _pos_de_entrada(db)),
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
    # `active` controla se o modelo aparece no site (0 = esgotado/oculto).
    # Normalizado para 0/1 para nunca gravar lixo na coluna.
    if "active" in d:
        ativo = 1 if d["active"] else 0
        fields.append("active = ?")
        vals.append(ativo)
        # Enquanto esteve esgotado, o modelo ficou FORA da aba de ordem e os
        # ativos foram renumerados sem ele — seu catalog_pos envelheceu e hoje
        # empata com algum vizinho. Religar sem reposicionar jogaria o card num
        # ponto imprevisível do meio da grade, então ele volta pelo topo.
        if ativo:
            antes = db.execute(
                "SELECT active, parent_id FROM vape_models WHERE id = ?", (mid,)
            ).fetchone()
            if antes and not antes["active"] and antes["parent_id"] is None:
                fields.append("catalog_pos = ?")
                vals.append(_pos_de_entrada(db))

    # Etiqueta e aviso da versão. Texto livre, mas guardado limpo: a etiqueta é
    # curta porque cabe dentro do pill do sabor.
    for f in ("variant_label", "variant_note"):
        if f in d:
            fields.append(f"{f} = ?")
            vals.append((d[f] or "").strip()[:80 if f == "variant_label" else 200])
    if "variant_pos" in d:
        fields.append("variant_pos = ?")
        try:
            vals.append(int(d["variant_pos"] or 0))
        except (TypeError, ValueError):
            vals.append(0)

    # `parent_id` transforma o modelo numa VERSÃO de outro (Slim, geração
    # anterior). Vazio desfaz o vínculo e devolve o modelo ao catálogo como card
    # próprio. As regras abaixo valem no servidor, não só na interface: a API é
    # chamável direto.
    if "parent_id" in d:
        raw = d["parent_id"]
        if raw in (None, "", 0, "0"):
            fields.append("parent_id = ?")
            vals.append(None)
        else:
            try:
                pid = int(raw)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "versão inválida"}), 400
            if pid == mid:
                return jsonify({"ok": False, "error": "um modelo não pode ser versão de si mesmo"}), 400
            me = db.execute("SELECT brand_id FROM vape_models WHERE id = ?", (mid,)).fetchone()
            parent = db.execute(
                "SELECT brand_id, parent_id FROM vape_models WHERE id = ?", (pid,)
            ).fetchone()
            if not me or not parent:
                return jsonify({"ok": False, "error": "modelo não encontrado"}), 404
            # Um nível só: o pai não pode ser, ele mesmo, versão de outro.
            if parent["parent_id"] is not None:
                return jsonify({
                    "ok": False,
                    "error": "esse modelo já é uma versão — escolha o produto principal",
                }), 400
            # Quem já tem versões penduradas não pode virar versão de ninguém,
            # senão as dele ficariam num segundo nível.
            has_children = db.execute(
                "SELECT 1 FROM vape_models WHERE parent_id = ? LIMIT 1", (mid,)
            ).fetchone()
            if has_children:
                return jsonify({
                    "ok": False,
                    "error": "este modelo já tem versões; solte-as antes de torná-lo uma versão",
                }), 400
            if me["brand_id"] != parent["brand_id"]:
                return jsonify({"ok": False, "error": "a versão precisa ser da mesma marca"}), 400
            fields.append("parent_id = ?")
            vals.append(pid)

    # Promoção com hora marcada. Os dois campos chegam JUNTOS (`promo`), porque
    # um sem o outro não é uma promoção: desconto sem fim nunca acabaria, fim
    # sem desconto não faz nada. Os dois vazios removem a promoção.
    # A data chega no horário de São Luís (datetime-local) e é gravada em UTC.
    promo_info = None
    if "promo" in d:
        promo_in = d["promo"] if isinstance(d["promo"], dict) else {}
        alvo = db.execute(
            "SELECT * FROM vape_models WHERE id = ?", (mid,)
        ).fetchone()
        if not alvo:
            return jsonify({"ok": False, "error": "modelo não encontrado"}), 404
        if alvo["parent_id"] is not None:
            return jsonify({
                "ok": False,
                "error": "a promoção é definida no produto principal e vale para as versões dele",
            }), 400
        # O desconto precisa caber no sabor mais barato do card inteiro
        # (principal + versões), senão algum sabor ficaria de graça.
        menor = db.execute(
            "SELECT MIN(price) AS p FROM products WHERE model_id = ? "
            "OR model_id IN (SELECT id FROM vape_models WHERE parent_id = ?)",
            (mid, mid),
        ).fetchone()["p"]
        desconto, fim_utc, erro = pricing.valida_promo(
            promo_in.get("desconto"), promo_in.get("fim"), menor
        )
        if erro:
            return jsonify({"ok": False, "error": erro}), 400
        # Relâmpago SOZINHO valendo: criar uma oferta agora faria ele somar
        # por cima sem ninguém pedir. Bloqueia e explica a ordem certa.
        agora_p = pricing.agora_utc()
        rel_fim = pricing.parse_fim(alvo["relampago_fim"])
        bf_ativa = pricing.promo_ativa(alvo["desconto_valor"], alvo["promo_fim"], agora_p)
        if desconto is not None and not bf_ativa and alvo["relampago_valor"] and rel_fim and rel_fim > agora_p:
            hora = rel_fim.astimezone(pricing.FUSO_LOJA).strftime("%d/%m às %H:%M")
            return jsonify({
                "ok": False,
                "error": f"Há um relâmpago valendo até {hora}. Encerre ou espere ele acabar para criar a oferta.",
            }), 400
        fields.append("desconto_valor = ?")
        vals.append(desconto)
        fields.append("promo_fim = ?")
        vals.append(fim_utc)
        promo_info = {"desconto": desconto, "fim": fim_utc}
        # Remover a oferta leva junto o relâmpago que estava POR CIMA dela.
        # Um relâmpago sozinho (sem oferta) não é tocado.
        if desconto is None and alvo["desconto_valor"] is not None:
            fields += ["relampago_valor = ?", "relampago_fim = ?"]
            vals += [None, None]

    # Oferta relâmpago (`relampago`: {valor, horas}). Começa agora e dura as
    # horas escolhidas (1 a 24). Com oferta ativa o valor soma por cima dela e
    # o fim não passa do fim dela; sem oferta, vale sozinho. Valor vazio
    # encerra. Mudar o valor de um relâmpago já ativo NÃO reinicia o relógio.
    relampago_info = None
    if "relampago" in d:
        rel_in = d["relampago"] if isinstance(d["relampago"], dict) else {}
        alvo = db.execute("SELECT * FROM vape_models WHERE id = ?", (mid,)).fetchone()
        if not alvo:
            return jsonify({"ok": False, "error": "modelo não encontrado"}), 404
        if alvo["parent_id"] is not None:
            return jsonify({
                "ok": False,
                "error": "o relâmpago é definido no produto principal e vale para as versões dele",
            }), 400
        menor = db.execute(
            "SELECT MIN(price) AS p FROM products WHERE model_id = ? "
            "OR model_id IN (SELECT id FROM vape_models WHERE parent_id = ?)",
            (mid, mid),
        ).fetchone()["p"]
        agora = pricing.agora_utc()
        valor, fim_utc, erro = pricing.valida_relampago(
            rel_in.get("valor"), rel_in.get("horas"), alvo["desconto_valor"], alvo["promo_fim"], menor, agora
        )
        if erro:
            return jsonify({"ok": False, "error": erro}), 400
        fim_atual = pricing.parse_fim(alvo["relampago_fim"])
        if valor is not None and fim_atual and fim_atual > agora and alvo["relampago_valor"]:
            fim_utc = pricing.formata_utc(fim_atual)
        fields += ["relampago_valor = ?", "relampago_fim = ?"]
        vals += [valor, fim_utc]
        relampago_info = {"valor": valor, "fim": fim_utc}

    if not fields:
        return jsonify({"ok": False}), 400
    vals.append(mid)
    db.execute(f"UPDATE vape_models SET {', '.join(fields)} WHERE id = ?", vals)
    db.commit()
    # (A auditoria da alteração já é feita pelo guard de escrita da rota.)
    out = {"ok": True}
    if promo_info is not None:
        out["promo"] = promo_info
    if relampago_info is not None:
        out["relampago"] = relampago_info
    return jsonify(out)


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


@app.template_filter("reais")
def filtro_reais(value):
    """129.99 -> '129,99' (sem o 'R$', que cada lugar posiciona do seu jeito)."""
    try:
        return f"{float(value):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return "0,00"


@app.template_filter("desconto_curto")
def filtro_desconto_curto(value):
    """Valor do selo de desconto: 20.0 -> '20', 15.5 -> '15,50'. Centavos só
    aparecem quando existem, porque o selo é pequeno."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "0"
    return f"{v:.0f}" if v == int(v) else f"{v:.2f}".replace(".", ",")


@app.template_filter("promo_resta")
def filtro_promo_resta(fim_iso):
    """Tempo restante já formatado no momento em que a página
    é gerada. O countdown.js assume a partir daí; sair preenchido do servidor
    evita o texto 'pular' na tela quando o JS carrega."""
    fim = pricing.parse_fim(fim_iso)
    if not fim:
        return ""
    s = max(int((fim - pricing.agora_utc()).total_seconds()), 0)
    d, h, m, sec = s // 86400, (s % 86400) // 3600, (s % 3600) // 60, s % 60
    # Mesmo formato do countdown.js: acima de 24h o texto é fixo em dias
    # inteiros; a contagem só aparece nas últimas 24 horas.
    if d:
        return f"{d} dia" if d == 1 else f"{d} dias"
    return f"{h:02d}:{m:02d}:{sec:02d}"


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
    # Aviso do sabor. Mesmo teto de 200 do aviso da versão: é uma frase que
    # divide espaço com ela dentro do modal, não um parágrafo.
    if "note" in d:
        fields.append("note = ?")
        vals.append((d["note"] or "").strip()[:200])
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


# ---------------------------------------------------------------------------
# Métricas de visita
#
# A loja manda três sinais (static/js/metrics.js): "hit" ao abrir a página,
# "ping" a cada 30 s enquanto a aba está visível (alimenta o "online agora") e
# "wa" quando o pedido é enviado para o WhatsApp. Nenhum cookie: o visitante é
# um hash de IP + navegador + data, que muda todo dia e não guarda o IP.
# Robôs e quem está logado no painel não contam.
# ---------------------------------------------------------------------------
METRICS_ONLINE_WINDOW = 120      # segundos sem sinal até sair do "online agora"
METRICS_PAGEVIEW_CAP = 200       # teto de páginas por visitante por dia (anti-F5 infinito)
METRICS_PERIODS = (1, 7, 30, 365)
METRICS_MAX_RANGE = 3 * 366      # "Selecionar o período": até ~3 anos
METRICS_DAILY_BARS_MAX = 92      # acima disso o gráfico agrupa por semana

_BOT_UA = re.compile(
    r"bot|crawl|spider|slurp|facebookexternalhit|facebookcatalog|whatsapp|telegram|"
    r"preview|headless|lighthouse|pingdom|uptime|monitor|curl|wget|python|httpclient|"
    r"okhttp|java/|go-http|axios|node-fetch|scrapy",
    re.I,
)
_MOBILE_UA = re.compile(r"mobi|android|iphone|ipad|ipod|windows phone", re.I)


def _metrics_today():
    return pricing.agora_utc().astimezone(pricing.FUSO_LOJA).date()


def _metrics_visitor():
    """(dia, código anônimo, é_celular) de quem fez a request, ou None quando
    ela não deve contar: sem navegador, robô ou alguém logado no painel."""
    ua = request.headers.get("User-Agent", "")
    if not ua or _BOT_UA.search(ua) or _current_user():
        return None
    day = _metrics_today().isoformat()
    raw = f"{app.secret_key}|{day}|{_client_ip()}|{ua}".encode()
    return day, hashlib.sha256(raw).hexdigest()[:32], bool(_MOBILE_UA.search(ua))


def _metrics_touch_online(db, vid):
    now = time.time()
    db.execute(
        "INSERT INTO metrics_online (vid, last_seen) VALUES (?, ?) "
        "ON CONFLICT(vid) DO UPDATE SET last_seen = excluded.last_seen",
        (vid, now),
    )
    db.execute("DELETE FROM metrics_online WHERE last_seen < ?", (now - 5 * METRICS_ONLINE_WINDOW,))


def _metrics_register(db, visitor, pageview):
    """Conta o visitante no dia (só na primeira vez) e, se `pageview`, mais uma
    página vista. Devolve a linha de metrics_seen dele."""
    day, vid, mobile = visitor
    # Os códigos de ontem para trás já não servem para nada: some com eles.
    db.execute("DELETE FROM metrics_seen WHERE day < ?", (day,))
    new = db.execute(
        "INSERT OR IGNORE INTO metrics_seen (day, vid) VALUES (?, ?)", (day, vid)
    ).rowcount == 1
    seen = db.execute(
        "SELECT pageviews, wa FROM metrics_seen WHERE day = ? AND vid = ?", (day, vid)
    ).fetchone()
    pv = 1 if pageview and seen["pageviews"] < METRICS_PAGEVIEW_CAP else 0
    if pv:
        db.execute(
            "UPDATE metrics_seen SET pageviews = pageviews + 1 WHERE day = ? AND vid = ?", (day, vid)
        )
    db.execute("INSERT INTO metrics_daily (day) VALUES (?) ON CONFLICT(day) DO NOTHING", (day,))
    db.execute(
        "UPDATE metrics_daily SET visitors = visitors + ?, pageviews = pageviews + ?, "
        "mobile = mobile + ?, desktop = desktop + ? WHERE day = ?",
        (int(new), pv, int(new and mobile), int(new and not mobile), day),
    )
    return seen


@app.route("/api/m/hit", methods=["POST"])
def metrics_hit():
    visitor = _metrics_visitor()
    if visitor:
        db = get_db()
        _metrics_register(db, visitor, pageview=True)
        _metrics_touch_online(db, visitor[1])
        db.commit()
    return "", 204


@app.route("/api/m/ping", methods=["POST"])
def metrics_ping():
    visitor = _metrics_visitor()
    if visitor:
        db = get_db()
        _metrics_touch_online(db, visitor[1])
        db.commit()
    return "", 204


@app.route("/api/m/wa", methods=["POST"])
def metrics_wa():
    """Pedido enviado para o WhatsApp. Conta uma vez por visitante por dia, para
    a conversão (cliques ÷ visitantes) nunca passar de 100%."""
    visitor = _metrics_visitor()
    if visitor:
        db = get_db()
        seen = _metrics_register(db, visitor, pageview=False)
        if not seen["wa"]:
            day, vid, _ = visitor
            db.execute("UPDATE metrics_seen SET wa = 1 WHERE day = ? AND vid = ?", (day, vid))
            db.execute("UPDATE metrics_daily SET wa_clicks = wa_clicks + 1 WHERE day = ?", (day,))
        db.commit()
    return "", 204


def _metrics_online_count(db):
    return db.execute(
        "SELECT COUNT(*) FROM metrics_online WHERE last_seen >= ?",
        (time.time() - METRICS_ONLINE_WINDOW,),
    ).fetchone()[0]


@app.route("/api/metrics", methods=["GET"])
@api_owner_read
def metrics_summary():
    """Números da aba Métricas para o período pedido, o período anterior de
    mesmo tamanho e a série do gráfico.

    Período: ?days=1|7|30|365 (terminando hoje) ou ?from=AAAA-MM-DD&to=AAAA-MM-DD
    (o "Selecionar o período" do painel, datas inclusivas, até hoje)."""
    today = _metrics_today()
    if request.args.get("from") or request.args.get("to"):
        try:
            start = date.fromisoformat(request.args.get("from", ""))
            end = date.fromisoformat(request.args.get("to", ""))
        except ValueError:
            return jsonify({"ok": False, "error": "data inválida"}), 400
        if start > end:
            return jsonify({"ok": False, "error": "a data inicial é depois da final"}), 400
        if end > today:
            return jsonify({"ok": False, "error": "a data final não pode passar de hoje"}), 400
        days = (end - start).days + 1
        if days > METRICS_MAX_RANGE:
            return jsonify({"ok": False, "error": "escolha um período de até 3 anos"}), 400
        custom = True
    else:
        try:
            days = int(request.args.get("days", 30))
        except ValueError:
            days = 0
        if days not in METRICS_PERIODS:
            return jsonify({"ok": False, "error": "período inválido"}), 400
        end, start = today, today - timedelta(days=days - 1)
        custom = False

    db = get_db()
    prev_start = start - timedelta(days=days)
    # Um dia só desenha a semana que termina nele, então precisa dela também.
    first = min(prev_start, end - timedelta(days=6))
    rows = {
        r["day"]: dict(r)
        for r in db.execute(
            "SELECT * FROM metrics_daily WHERE day BETWEEN ? AND ?",
            (first.isoformat(), end.isoformat()),
        )
    }
    keys = ("visitors", "pageviews", "wa_clicks", "mobile", "desktop")

    def total(a, b):
        out = dict.fromkeys(keys, 0)
        d = a
        while d <= b:
            r = rows.get(d.isoformat())
            if r:
                for k in keys:
                    out[k] += r[k]
            d += timedelta(days=1)
        return out

    def visitors_on(d):
        r = rows.get(d.isoformat())
        return r["visitors"] if r else 0

    if days > METRICS_DAILY_BARS_MAX:
        # Período longo vai por semana (365 barrinhas não se leem): blocos de
        # 7 dias terminando em `end`; o primeiro absorve a sobra (até 13 dias).
        weeks = days // 7
        series = []
        for i in range(weeks):
            we = end - timedelta(days=7 * (weeks - 1 - i))
            ws = start if i == 0 else we - timedelta(days=6)
            series.append({"day": ws.isoformat(), "visitors": total(ws, we)["visitors"]})
        kind = "week"
    else:
        n = 7 if days == 1 else days
        series = [
            {"day": (end - timedelta(days=n - 1 - i)).isoformat(),
             "visitors": visitors_on(end - timedelta(days=n - 1 - i))}
            for i in range(n)
        ]
        kind = "day"

    return jsonify({
        "ok": True,
        "days": days,
        "custom": custom,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "today": today.isoformat(),
        "current": total(start, end),
        "previous": total(prev_start, start - timedelta(days=1)),
        "series": series,
        "series_kind": kind,
        "online": _metrics_online_count(db),
    })


@app.route("/api/metrics/online", methods=["GET"])
@api_owner_read
def metrics_online():
    return jsonify({"ok": True, "online": _metrics_online_count(get_db())})


# Garante que o banco existe quando rodando via Gunicorn (produção)
with app.app_context():
    init_db()

if __name__ == "__main__":
    # Rodar localmente (no seu PC): python app.py
    # DEBUG só liga se a variável de ambiente FLASK_DEBUG=1 estiver setada.
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(debug=debug, host="0.0.0.0", port=5000)
