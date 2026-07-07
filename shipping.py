"""Cálculo de frete por zonas circulares (distância Haversine).

Edite as listas abaixo para ajustar centros, raios (em metros) e preços —
a lógica de cálculo não precisa ser tocada.

Zonas especiais (bolsões isolados) são testadas ANTES das concêntricas.
Zonas concêntricas são testadas da menor para a maior (a lista é reordenada
por segurança dentro de calculate_shipping, então a ordem aqui não importa).
"""
import math

SPECIAL_ZONES = [
    # Bolsões isolados fora do raio das zonas concêntricas.
    # "price": None é placeholder — defina o valor do frete quando decidir.
    {"label": "Bolsão 1", "lat": -2.5045132, "lng": -44.180938, "radius_m": 847, "price": None},
    {"label": "Bolsão 2", "lat": -2.5458547, "lng": -44.1833806, "radius_m": 470, "price": None},
    {"label": "Bolsão 3", "lat": -2.5635447, "lng": -44.2670185, "radius_m": 1005, "price": None},
    {"label": "Bolsão 4", "lat": -2.534387, "lng": -44.3276612, "radius_m": 1272, "price": None},
]

CONCENTRIC_ZONES = [
    {"label": "Zona 1", "lat": -2.5006266, "lng": -44.2499112, "radius_m": 2462, "price": 8},
    {"label": "Zona 2", "lat": -2.4994346, "lng": -44.2511602, "radius_m": 3699, "price": 12},
    {"label": "Zona 3", "lat": -2.500324, "lng": -44.2525603, "radius_m": 4908, "price": 16},
    {"label": "Zona 4", "lat": -2.4971016, "lng": -44.2577978, "radius_m": 6658, "price": 18},
    {"label": "Zona 5", "lat": -2.5078223, "lng": -44.2507875, "radius_m": 9058, "price": 22},
]

FORA_DA_AREA_MSG = "Fora da área de entrega padrão. Frete calculado à parte."

EARTH_RADIUS_M = 6371000


def haversine_distance_m(lat1, lng1, lat2, lng2):
    """Distância em metros entre dois pontos (lat/lng em graus) numa esfera."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c


def calculate_shipping(lat, lng):
    """Retorna o frete para um ponto (lat, lng), testando zonas especiais
    primeiro e depois as concêntricas (da menor para a maior).

    Retorna um dict:
      - zona concêntrica: {"ok": True, "special": False, "zone_label": ..., "price": <num>, "message": None}
      - zona especial (preço placeholder): {"ok": True, "special": True, "zone_label": ..., "price": None, "message": "..."}
      - fora de tudo: {"ok": False, "special": False, "zone_label": None, "price": None, "message": FORA_DA_AREA_MSG}
    """
    for zone in SPECIAL_ZONES:
        dist = haversine_distance_m(lat, lng, zone["lat"], zone["lng"])
        if dist <= zone["radius_m"]:
            message = (
                None
                if zone["price"] is not None
                else f"Endereço em zona especial ({zone['label']}) — frete a combinar."
            )
            return {
                "ok": True,
                "special": True,
                "zone_label": zone["label"],
                "price": zone["price"],
                "distance_m": round(dist),
                "message": message,
            }

    for zone in sorted(CONCENTRIC_ZONES, key=lambda z: z["radius_m"]):
        dist = haversine_distance_m(lat, lng, zone["lat"], zone["lng"])
        if dist <= zone["radius_m"]:
            return {
                "ok": True,
                "special": False,
                "zone_label": zone["label"],
                "price": zone["price"],
                "distance_m": round(dist),
                "message": None,
            }

    return {
        "ok": False,
        "special": False,
        "zone_label": None,
        "price": None,
        "distance_m": None,
        "message": FORA_DA_AREA_MSG,
    }
