"""Testes do cálculo de frete por zonas circulares (shipping.py).

Coordenadas de borda são calculadas dinamicamente dentro dos testes
(mesma fórmula de deslocamento norte-sul numa esfera) em vez de
hardcoded, porque arredondar manualmente um lat/lng costuma jogar o
ponto alguns milímetros para dentro ou fora do raio exato.
"""
import math

import pytest

from shipping import (
    CONCENTRIC_ZONES,
    SPECIAL_ZONES,
    FORA_DA_AREA_MSG,
    EARTH_RADIUS_M,
    calculate_shipping,
    haversine_distance_m,
)


def zone_by_label(zones, label):
    return next(z for z in zones if z["label"] == label)


def point_due_north(lat, lng, distance_m):
    """Ponto a `distance_m` metros exatamente ao norte de (lat, lng).

    Deslocamento norte-sul numa esfera é exato (não é uma aproximação):
    1 grau de latitude vale sempre R * (pi/180) metros, em qualquer
    latitude.
    """
    dlat = (distance_m / EARTH_RADIUS_M) * (180 / math.pi)
    return lat + dlat, lng


# ---------------------------------------------------------------------------
# Haversine puro
# ---------------------------------------------------------------------------
def test_haversine_same_point_is_zero():
    assert haversine_distance_m(-2.5, -44.25, -2.5, -44.25) == 0


def test_haversine_is_symmetric():
    a = (-2.5006266, -44.2499112)
    b = (-2.4994346, -44.2511602)
    assert haversine_distance_m(*a, *b) == pytest.approx(haversine_distance_m(*b, *a))


# ---------------------------------------------------------------------------
# Caso 1: centro exato da menor zona concêntrica
# ---------------------------------------------------------------------------
def test_center_of_smallest_zone_returns_its_price():
    zona1 = zone_by_label(CONCENTRIC_ZONES, "Zona 1")
    result = calculate_shipping(zona1["lat"], zona1["lng"])
    assert result["ok"] is True
    assert result["special"] is False
    assert result["zone_label"] == "Zona 1"
    assert result["price"] == 8
    assert result["distance_m"] == 0


# ---------------------------------------------------------------------------
# Caso 2: borda entre duas zonas — "menor para maior" tem que vencer
# ---------------------------------------------------------------------------
def test_point_just_inside_smallest_zone_wins_over_larger_overlapping_zones():
    zona1 = zone_by_label(CONCENTRIC_ZONES, "Zona 1")
    # 1m dentro do raio da Zona 1 (evita flakiness de ponto flutuante
    # de testar exatamente em cima do raio — ver test_inclusive_boundary abaixo).
    lat, lng = point_due_north(zona1["lat"], zona1["lng"], zona1["radius_m"] - 1)

    result = calculate_shipping(lat, lng)

    assert result["zone_label"] == "Zona 1"
    assert result["price"] == 8
    # Confirma que esse ponto também cai dentro de zonas maiores
    # (prova que o "menor primeiro" realmente importa aqui).
    for other_label in ("Zona 2", "Zona 3", "Zona 4", "Zona 5"):
        other = zone_by_label(CONCENTRIC_ZONES, other_label)
        assert haversine_distance_m(lat, lng, other["lat"], other["lng"]) <= other["radius_m"]


def test_point_just_outside_smallest_zone_falls_to_next_zone():
    zona1 = zone_by_label(CONCENTRIC_ZONES, "Zona 1")
    lat, lng = point_due_north(zona1["lat"], zona1["lng"], zona1["radius_m"] + 1)

    result = calculate_shipping(lat, lng)

    assert result["zone_label"] != "Zona 1"
    assert result["ok"] is True


def test_inclusive_boundary_exact_radius_counts_as_match(monkeypatch):
    """Prova que a comparação é `<=` (inclusiva), sem depender de
    round-trip de ponto flutuante em coordenadas geográficas reais.
    """
    zona1 = zone_by_label(CONCENTRIC_ZONES, "Zona 1")

    def fake_distance(lat1, lng1, lat2, lng2):
        return float(zona1["radius_m"])  # exatamente em cima do raio

    monkeypatch.setattr("shipping.haversine_distance_m", fake_distance)
    result = calculate_shipping(zona1["lat"], zona1["lng"])
    assert result["zone_label"] == "Zona 1"


# ---------------------------------------------------------------------------
# Caso 3: zona especial (bolsão) tem prioridade sobre as concêntricas
# ---------------------------------------------------------------------------
def test_special_zone_center_wins_even_though_inside_a_concentric_zone():
    bolsao1 = zone_by_label(SPECIAL_ZONES, "Bolsão 1")
    zona5 = zone_by_label(CONCENTRIC_ZONES, "Zona 5")

    # Pré-condição do teste: o centro do bolsão realmente cai dentro da
    # maior zona concêntrica — é isso que torna esse teste significativo
    # (sem essa sobreposição real, a ordem de checagem não seria testada).
    dist_to_zona5 = haversine_distance_m(bolsao1["lat"], bolsao1["lng"], zona5["lat"], zona5["lng"])
    assert dist_to_zona5 <= zona5["radius_m"]

    result = calculate_shipping(bolsao1["lat"], bolsao1["lng"])

    assert result["ok"] is True
    assert result["special"] is True
    assert result["zone_label"] == "Bolsão 1"
    assert result["price"] is None
    assert "Bolsão 1" in result["message"]
    assert "frete a combinar" in result["message"]


# ---------------------------------------------------------------------------
# Caso 4: fora de todas as zonas
# ---------------------------------------------------------------------------
def test_point_outside_all_zones_returns_exact_fallback_message():
    result = calculate_shipping(-2.30, -44.50)

    assert result["ok"] is False
    assert result["price"] is None
    assert result["zone_label"] is None
    assert result["message"] == FORA_DA_AREA_MSG == "Fora da área de entrega padrão. Frete calculado à parte."
