"""Regras do painel de atendimento (pedido manual pelo WhatsApp).

Funções puras, sem Flask: ler a localização que a atendente cola, e fazer a
conta do pedido. As rotas em app.py só buscam os dados no banco e chamam isto.

Por que a conta mora no servidor: no pedido manual a atendente calculava frete
e total de cabeça. Com o total vindo daqui, ela só copia e cola — não erra o
centavo e não tem como inflar o frete.
"""
import re
import urllib.error
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import unquote, urlsplit

# Acréscimo do cartão de crédito. TEM que ser igual ao CREDIT_SURCHARGE_RATE
# do static/app.js (o checkout do site) — tests/test_atendimento.py confere.
CREDITO_PCT = Decimal("5")

PAGAMENTOS = {
    "pix": "Pix",
    "dinheiro": "Dinheiro",
    "debito": "Débito",
    "credito": "Crédito",
}

CENTAVO = Decimal("0.01")


def dinheiro(valor):
    """float/str/Decimal -> Decimal em centavos (arredonda meio para cima)."""
    return Decimal(str(valor or 0)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Configuração: chaves do site_config e textos padrão
# ---------------------------------------------------------------------------
# Textos das mensagens (seção 7 do planejamento). Variáveis entre chaves.
TEXTOS_PADRAO = {
    "atd_tpl_sabores": (
        "🛒 *{loja}*\n"
        "━━━━━━━━━━━━━━\n"
        "*_{marca} {modelo} – {puffs} Puffs_*\n"
        "Sabores disponíveis:\n"
        "\n"
        "{sabores}\n"
        "\n"
        "{preco_de} *{preco} 🔥*"
    ),
    "atd_tpl_catalogo": (
        "🛒 *{loja} – Catálogo de hoje*\n"
        "━━━━━━━━━━━━━━\n"
        "{catalogo_por_marca}\n"
        "━━━━━━━━━━━━━━\n"
        "🚚 Entregamos em toda São Luís · {horario}\n"
        "🌐 {site}"
    ),
    "atd_tpl_padrao": (
        "Pra eu já separar seu pedido, me manda:\n"
        "1️⃣ Sabor + modelo\n"
        "2️⃣ Localização fixa 📍 ou retirada\n"
        "3️⃣ Forma de pagamento (Pix, dinheiro ou cartão)"
    ),
    "atd_tpl_resumo": (
        "🧾 *Resumo do pedido*\n"
        "{itens}\n"
        "🚚 Frete ({zona}): {frete}\n"
        "💳 Crédito (+5%): {acrescimo}\n"
        "💰 *Total: {total}*\n"
        "\n"
        "Pode confirmar?"
    ),
    "atd_tpl_pix": (
        "💨 CHAVE PIX – {loja}\n"
        "\n"
        "💻 Chave Pix ({pix_tipo}): {pix_chave}\n"
        "👤 Nome: {pix_titular}\n"
        "\n"
        "💰 Valor: *{total}*\n"
        "Assim que pagar, me manda o comprovante, por favor."
    ),
    "atd_tpl_confirmacao": (
        "Tudo bem, confirmei seu pedido! 🚀\n"
        "💰 *Total: {total}* – {pagamento} na entrega.\n"
        "O motoboy já vai sair em rota."
    ),
    "atd_tpl_agradecimento": (
        "Agradecemos a sua compra, seu pedido logo sairá para entrega! 💨😃\n"
        "\n"
        "• Prazo de entrega: {prazo} (pode variar conforme a demanda).\n"
        "• Atenção: confira o sabor e o modelo do vape no momento do recebimento, "
        "antes de abrir a embalagem.\n"
        "• Garantia: troca em até 24 horas para defeitos de fabricação "
        "(não cobre mau uso do aparelho).\n"
        "\n"
        "📞 Motoboy: {motoboy} – {motoboy_tel}"
    ),
}

# Dados da loja usados nas mensagens. Pix começa VAZIO de propósito: cada loja
# cai numa conta diferente, e só o dono preenche (rota só do dono, com histórico).
CONFIG_PADRAO = {
    "atd_nome": "",          # vazio = usa o store_name
    "atd_site": "",
    "atd_grupo_vip": "",
    "atd_pix_chave": "",
    "atd_pix_tipo": "",
    "atd_pix_titular": "",
    "atd_prazo": "até 60 minutos",
    "atd_horario": "10h às 23h",
    **TEXTOS_PADRAO,
}

# Tamanho máximo de cada valor (textos das mensagens são maiores).
LIMITE_TEXTO = 2000
LIMITE_CAMPO = 200


# ---------------------------------------------------------------------------
# Localização colada pela atendente
# ---------------------------------------------------------------------------
_NUM = r"(-?\d{1,3}\.\d+)"
# Ordem importa: o pino exato (!3d/!4d) vem antes do centro do mapa (@lat,lng),
# que num link de /place/ é só para onde a tela está apontando.
_PADROES = [
    re.compile(r"!3d" + _NUM + r"!4d" + _NUM),
    re.compile(r"[?&](?:q|query|ll|sll|destination|daddr|center)=(?:loc:)?" + _NUM + r"\s*,\s*" + _NUM),
    re.compile(r"@" + _NUM + r"\s*,\s*" + _NUM),
    # "lat, lng" solto (com pelo menos 3 casas, para não casar com preço/hora).
    re.compile(r"(?<![\d.])(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{1,3}\.\d{3,})(?![\d.])"),
]

_LINK_CURTO = re.compile(r"https?://(?:maps\.app\.goo\.gl|goo\.gl/maps)/[^\s]+", re.IGNORECASE)

# Para onde o link curto pode redirecionar. Qualquer outro host aborta: o
# servidor não pode virar um "abridor de URL" para quem estiver logado.
_HOSTS_PERMITIDOS = ("google.com", "goo.gl", "google.com.br")


def extrair_latlng(texto):
    """(lat, lng) a partir de um link do Google Maps ou de "lat, lng" solto.
    None se não achar coordenadas válidas."""
    if not texto:
        return None
    texto = unquote(unquote(str(texto)))  # %2C e links aninhados (continue=...)
    for padrao in _PADROES:
        for m in padrao.finditer(texto):
            try:
                lat, lng = float(m.group(1)), float(m.group(2))
            except ValueError:
                continue
            if -90 <= lat <= 90 and -180 <= lng <= 180 and not (lat == 0 and lng == 0):
                return lat, lng
    return None


def _host_permitido(url):
    parts = urlsplit(url)
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _HOSTS_PERMITIDOS)


class _SemRedirect(urllib.request.HTTPRedirectHandler):
    """Não segue redirect sozinho: cada salto é conferido antes."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _proximo_salto(url, timeout=5):
    """Faz UM pedido ao link e devolve o Location do redirect (ou None)."""
    opener = urllib.request.build_opener(_SemRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.headers.get("Location")
    except urllib.error.HTTPError as e:
        return e.headers.get("Location") if 300 <= e.code < 400 else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def resolver_link_curto(url, buscar=_proximo_salto, max_saltos=3):
    """Segue um link maps.app.goo.gl até achar coordenadas (até 3 saltos, só
    em hosts do Google). `buscar` é injetável para os testes não usarem rede."""
    atual = url
    for _ in range(max_saltos):
        if not _host_permitido(atual):
            return None
        destino = buscar(atual)
        if not destino:
            return None
        coords = extrair_latlng(destino)
        if coords:
            return coords
        atual = destino
    return None


def ler_localizacao(texto, buscar=_proximo_salto):
    """Coordenadas a partir do que a atendente colou. None se não der."""
    coords = extrair_latlng(texto)
    if coords:
        return coords
    m = _LINK_CURTO.search(texto or "")
    if m:
        return resolver_link_curto(m.group(0), buscar=buscar)
    return None


# ---------------------------------------------------------------------------
# Conta do pedido
# ---------------------------------------------------------------------------
def calcular_total(itens, pagamento, frete_info=None, retirada=False, regras=None):
    """Conta do pedido manual, com a MESMA regra do checkout do site
    (static/app.js, computeTotals):

      - frete grátis: subtotal >= mínimo E a zona tem preço numérico até o
        teto (bolsão "a combinar" e fora da área nunca entram);
      - crédito: +5% sobre (subtotal + frete).

    `itens`: [{"preco": num, "qty": int}]. `frete_info`: o dict de
    shipping.calculate_shipping (ou None se ainda sem localização).
    `regras`: {"enabled": bool, "min": num, "max_zone": num}.

    Devolve `status`:
      ok              -> total fechado
      sem_localizacao -> entrega sem localização ainda (total None)
      a_combinar      -> zona especial sem preço (total None)
      fora_da_area    -> fora das zonas (total None)
    """
    regras = regras or {}
    subtotal = sum((dinheiro(it["preco"]) * int(it["qty"]) for it in itens), Decimal("0"))

    zona = None
    frete_cheio = Decimal("0")
    status = "ok"
    if retirada:
        zona = "Retirada"
    elif frete_info is None:
        status = "sem_localizacao"
    elif not frete_info.get("ok"):
        status = "fora_da_area"
    elif frete_info.get("price") is None:
        status = "a_combinar"
        zona = frete_info.get("zone_label")
    else:
        zona = frete_info.get("zone_label")
        frete_cheio = dinheiro(frete_info["price"])

    minimo = dinheiro(regras.get("min") or 0)
    frete_gratis = bool(
        status == "ok" and not retirada
        and regras.get("enabled") and minimo > 0
        and subtotal >= minimo
        and frete_cheio <= dinheiro(regras.get("max_zone") or 0)
    )
    frete = Decimal("0") if frete_gratis else frete_cheio

    acrescimo = Decimal("0")
    total = None
    if status == "ok":
        base = subtotal + frete
        if pagamento == "credito":
            acrescimo = (base * CREDITO_PCT / 100).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        total = base + acrescimo

    return {
        "status": status,
        "subtotal": subtotal,
        "zona": zona,
        "frete_cheio": frete_cheio,
        "frete": frete,
        "frete_gratis": frete_gratis,
        "acrescimo": acrescimo,
        "total": total,
    }
