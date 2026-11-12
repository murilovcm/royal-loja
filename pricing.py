"""Regra de preço da loja — FONTE ÚNICA DA VERDADE.

Todo lugar que mostra ou cobra um preço (card, modal, carrinho, cotação do
checkout, validação de cupom) passa por `preco_efetivo`. Módulo puro, sem
Flask e sem banco, como o `shipping.py`: recebe os valores e a hora, devolve o
resultado. É isso que deixa a regra testável sem subir a aplicação.

A promoção é um DESCONTO EM REAIS por modelo, com data e hora para acabar:
    promo ativa  =  desconto preenchido (> 0)  E  promo_fim no futuro
                    E  o desconto é menor que o preço do sabor

Datas: gravadas sempre em UTC, como texto ISO terminado em "Z"
("2026-11-27T02:59:00Z"). O painel mostra e recebe no horário de São Luís.
"""
from datetime import datetime, timedelta, timezone

# America/Fortaleza (horário de São Luís) é UTC-3 fixo: o Brasil não tem
# horário de verão desde 2019. Offset fixo em vez de zoneinfo para não depender
# do pacote tzdata, que não vem no Windows nem em imagens Docker enxutas.
FUSO_LOJA = timezone(timedelta(hours=-3))

DESCONTO_MAXIMO = 9999.99


def agora_utc():
    return datetime.now(timezone.utc)


def parse_fim(valor):
    """Texto ISO do banco -> datetime com fuso UTC. Qualquer coisa inválida vira
    None (= sem promoção), nunca exceção: um dado ruim no banco não pode
    derrubar a vitrine."""
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    if not valor or not isinstance(valor, str):
        return None
    try:
        dt = datetime.fromisoformat(valor.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def formata_utc(dt):
    """datetime -> texto ISO em UTC com "Z", o formato gravado e enviado ao
    navegador (o JS lê direto com Date.parse)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_para_utc(texto):
    """Valor de um <input type="datetime-local"> ("2026-11-27T23:59"), digitado
    no horário de São Luís -> texto ISO em UTC. None se não for uma data."""
    if not texto or not isinstance(texto, str):
        return None
    try:
        dt = datetime.fromisoformat(texto.strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=FUSO_LOJA)
    return formata_utc(dt)


def utc_para_local(valor):
    """Texto ISO em UTC -> valor para <input type="datetime-local">, no horário
    de São Luís. String vazia se não houver data."""
    dt = parse_fim(valor)
    return dt.astimezone(FUSO_LOJA).strftime("%Y-%m-%dT%H:%M") if dt else ""


def _centavos(valor):
    try:
        return int(round(float(valor) * 100))
    except (TypeError, ValueError):
        return 0


def promo_ativa(desconto_valor, promo_fim, agora=None):
    """A promoção do MODELO está valendo agora? (Ainda sem olhar o preço de
    cada sabor — isso é com `preco_efetivo`.)"""
    fim = parse_fim(promo_fim)
    if fim is None or _centavos(desconto_valor) <= 0:
        return False
    return fim > (agora or agora_utc())


def preco_efetivo(preco, desconto_valor=None, promo_fim=None, agora=None):
    """Preço que vale AGORA para um sabor.

    Retorna um dict:
        original  preço cheio do sabor
        final     preço a cobrar (igual ao original sem promoção ativa)
        desconto  quanto saiu do preço, em reais (0 sem promoção)
        fim       texto ISO UTC do fim da promoção, ou None
        ativa     True se a promoção está valendo para este sabor

    No instante exato do fim a promoção JÁ acabou (comparação estrita).

    Desconto maior ou igual ao preço do sabor não é aplicado: melhor vender
    pelo preço cheio do que por zero ou valor negativo por causa de um sabor
    mais barato que o resto do modelo.
    """
    original = _centavos(preco)
    desconto = _centavos(desconto_valor)
    ativa = promo_ativa(desconto_valor, promo_fim, agora) and 0 < desconto < original
    final = original - desconto if ativa else original
    return {
        "original": original / 100,
        "final": final / 100,
        "desconto": desconto / 100 if ativa else 0.0,
        "fim": formata_utc(parse_fim(promo_fim)) if ativa else None,
        "ativa": ativa,
    }


def valida_promo(desconto_valor, promo_fim_local, menor_preco, agora=None):
    """Valida o que o painel enviou para a promoção de um modelo.

    Retorna (desconto, fim_utc, erro). Campos vazios nos DOIS = remover a
    promoção: (None, None, None).
    """
    vazio_d = desconto_valor in (None, "")
    vazio_f = promo_fim_local in (None, "")
    if vazio_d and vazio_f:
        return None, None, None
    if vazio_d or vazio_f:
        return None, None, "Preencha o valor do desconto e a data de término (ou deixe os dois vazios)"
    try:
        desconto = round(float(str(desconto_valor).replace(",", ".")), 2)
    except (TypeError, ValueError):
        return None, None, "Valor de desconto inválido"
    if not (0 < desconto <= DESCONTO_MAXIMO):
        return None, None, "O desconto deve ser maior que zero"
    if menor_preco is not None and desconto >= menor_preco:
        return None, None, (
            "O desconto precisa ser menor que o preço do sabor mais barato "
            f"(R$ {menor_preco:.2f})".replace(".", ",")
        )
    fim_utc = local_para_utc(promo_fim_local)
    if fim_utc is None:
        return None, None, "Data de término inválida"
    if parse_fim(fim_utc) <= (agora or agora_utc()):
        return None, None, "A data de término precisa estar no futuro"
    return desconto, fim_utc, None
