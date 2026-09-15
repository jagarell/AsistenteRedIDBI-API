"""Geocodificación automática del local a partir de nombre + dirección, vía
Nominatim (OpenStreetMap) — gratis, sin API key. Reemplaza pedirle al técnico
que ingrese coordenadas GPS a mano (ese nodo no tenía UI real en el chat).
"""
import logging

import httpx

logger = logging.getLogger("idbi.geocoding")

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOT_FOUND = "No se pudo determinar automáticamente"


def geocode(establishment_name: str, address: str | None) -> str:
    query = establishment_name if not address else f"{establishment_name}, {address}"
    if not query.strip():
        return _NOT_FOUND

    try:
        response = httpx.get(
            _NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "idbi-network-assistant/1.0"},
            timeout=8.0,
        )
        response.raise_for_status()
        results = response.json()
        if results:
            return f"{results[0]['lat']},{results[0]['lon']}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo geocodificar '%s': %s", query, exc)

    return _NOT_FOUND
