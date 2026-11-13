"""Regra de preço (pricing.py): fonte única da verdade do desconto com hora
marcada. Módulo puro, então estes testes não tocam em banco nem em Flask."""
from datetime import datetime, timedelta, timezone

import pricing

AGORA = datetime(2026, 11, 27, 15, 0, 0, tzinfo=timezone.utc)
FUTURO = "2026-11-28T02:59:00Z"
PASSADO = "2026-11-27T14:59:59Z"


def test_sem_promo_devolve_preco_cheio():
    pe = pricing.preco_efetivo(129.99, None, None, AGORA)
    assert pe == {"original": 129.99, "final": 129.99, "desconto": 0.0, "fim": None,
                  "ativa": False, "relampago": False, "depois": None}


def test_promo_ativa_desconta_valor_fixo():
    pe = pricing.preco_efetivo(129.99, 20, FUTURO, AGORA)
    assert pe["ativa"] is True
    assert pe["original"] == 129.99
    assert pe["final"] == 109.99
    assert pe["desconto"] == 20.0
    assert pe["fim"] == FUTURO


def test_promo_expirada_volta_ao_preco_cheio():
    pe = pricing.preco_efetivo(129.99, 20, PASSADO, AGORA)
    assert pe["ativa"] is False
    assert pe["final"] == 129.99
    assert pe["desconto"] == 0.0
    assert pe["fim"] is None


def test_borda_exata_do_fim_ja_esta_expirada():
    fim = pricing.formata_utc(AGORA)
    assert pricing.preco_efetivo(100, 10, fim, AGORA)["ativa"] is False
    # Um segundo antes do fim ainda vale.
    um_antes = AGORA - timedelta(seconds=1)
    assert pricing.preco_efetivo(100, 10, fim, um_antes)["ativa"] is True
    assert pricing.preco_efetivo(100, 10, fim, um_antes)["final"] == 90.0


def test_desconto_sem_data_ou_data_sem_desconto_nao_e_promo():
    assert pricing.preco_efetivo(100, 10, None, AGORA)["ativa"] is False
    assert pricing.preco_efetivo(100, None, FUTURO, AGORA)["ativa"] is False
    assert pricing.preco_efetivo(100, 0, FUTURO, AGORA)["ativa"] is False
    assert pricing.preco_efetivo(100, -5, FUTURO, AGORA)["ativa"] is False


def test_desconto_maior_ou_igual_ao_preco_nao_se_aplica():
    """Um sabor mais barato que o desconto do modelo não pode sair de graça."""
    assert pricing.preco_efetivo(20, 20, FUTURO, AGORA)["final"] == 20.0
    assert pricing.preco_efetivo(15, 20, FUTURO, AGORA)["final"] == 15.0
    assert pricing.preco_efetivo(20.01, 20, FUTURO, AGORA)["final"] == 0.01


def test_conta_em_centavos_sem_erro_de_ponto_flutuante():
    # 114.99 - 15.5 em float dá 99.48999999999999; o resultado tem que ser 99.49.
    assert pricing.preco_efetivo(114.99, 15.5, FUTURO, AGORA)["final"] == 99.49
    assert pricing.preco_efetivo(159.99, 30, FUTURO, AGORA)["final"] == 129.99


def test_data_invalida_no_banco_vira_sem_promo():
    assert pricing.preco_efetivo(100, 10, "isso não é data", AGORA)["ativa"] is False
    assert pricing.preco_efetivo(100, 10, "", AGORA)["ativa"] is False


def test_data_sem_fuso_no_banco_e_lida_como_utc():
    assert pricing.preco_efetivo(100, 10, "2026-11-27T15:00:01", AGORA)["ativa"] is True
    assert pricing.preco_efetivo(100, 10, "2026-11-27T14:59:59", AGORA)["ativa"] is False


def test_cupom_percentual_acumula_sobre_o_preco_com_desconto():
    """Regra definida: o cupom incide sobre o preço JÁ com a promoção."""
    pe = pricing.preco_efetivo(129.99, 20, FUTURO, AGORA)
    com_cupom = round(pe["final"] * (1 - 10 / 100), 2)
    assert com_cupom == 98.99          # 109,99 - 10%
    assert com_cupom < round(129.99 * 0.9, 2)


def test_fuso_de_sao_luis_ida_e_volta():
    # 23:59 em São Luís (UTC-3) = 02:59 do dia seguinte em UTC.
    assert pricing.local_para_utc("2026-11-27T23:59") == "2026-11-28T02:59:00Z"
    assert pricing.utc_para_local("2026-11-28T02:59:00Z") == "2026-11-27T23:59"
    assert pricing.utc_para_local(None) == ""
    assert pricing.local_para_utc("amanhã") is None


def test_valida_promo_aceita_e_converte():
    desconto, fim, erro = pricing.valida_promo("20", "2026-11-27T23:59", 99.99, AGORA)
    assert (desconto, fim, erro) == (20.0, "2026-11-28T02:59:00Z", None)
    # Vírgula decimal digitada no painel.
    assert pricing.valida_promo("15,50", "2026-11-27T23:59", 99.99, AGORA)[0] == 15.5


def test_valida_promo_dois_vazios_remove():
    assert pricing.valida_promo("", "", 99.99, AGORA) == (None, None, None)
    assert pricing.valida_promo(None, None, 99.99, AGORA) == (None, None, None)


def test_valida_promo_recusa_entradas_ruins():
    erro = lambda *a: pricing.valida_promo(*a, agora=AGORA)[2]
    assert erro("20", "", 99.99)                      # falta a data
    assert erro("", "2026-11-27T23:59", 99.99)        # falta o valor
    assert erro("0", "2026-11-27T23:59", 99.99)       # zero
    assert erro("-5", "2026-11-27T23:59", 99.99)      # negativo
    assert erro("abc", "2026-11-27T23:59", 99.99)     # não é número
    assert erro("99.99", "2026-11-27T23:59", 99.99)   # igual ao menor preço
    assert erro("120", "2026-11-27T23:59", 99.99)     # maior que o menor preço
    assert erro("20", "2026-11-27T11:59", 99.99)      # 14:59 UTC: já passou
    assert erro("20", "não é data", 99.99)
