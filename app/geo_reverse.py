"""Geocodificación inversa para la ubicación GPS del local (docs/0.0.7/03-gps-direccion.md y 04-geocodificacion.md).

Proveedor: OpenStreetMap Nominatim (gratis, sin clave). Si el equipo prefiere Google Geocoding/Places, solo cambia
`_reverse` y `_cerca`; el contrato de `reverse()` no cambia.
"""
import logging
import math
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("idbi.geo_reverse")

_URL = "https://nominatim.openstreetmap.org"
_HEADERS = {"User-Agent": "idbi-network-assistant/1.0", "Accept-Language": "es"}
_RADIO_M = 100
_SIMILITUD = 0.8


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def _limpia(s: Optional[str]) -> str:
    """Quita «Provincia de» / «Departamento de» que Nominatim antepone en Perú."""
    return re.sub(r"^(provincia|departamento|distrito)\s+de(l)?\s+", "", (s or "").strip(), flags=re.I)


def _metros(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def mapa_url(lat: float, lng: float) -> str:
    return f"https://www.google.com/maps?q={lat:.6f},{lng:.6f}"


def _reverse(lat: float, lng: float) -> Optional[Dict[str, Any]]:
    r = httpx.get(f"{_URL}/reverse", headers=_HEADERS, timeout=8.0,
                  params={"lat": lat, "lon": lng, "format": "jsonv2", "addressdetails": 1, "zoom": 18, "accept-language": "es"})
    r.raise_for_status()
    j = r.json()
    return j if isinstance(j, dict) and j.get("address") else None


def _cerca(nombre: str, lat: float, lng: float) -> List[Dict[str, Any]]:
    d = 0.0015  # ≈ 165 m
    r = httpx.get(f"{_URL}/search", headers=_HEADERS, timeout=8.0,
                  params={"q": nombre, "format": "jsonv2", "limit": 5, "bounded": 1, "accept-language": "es",
                          "viewbox": f"{lng - d},{lat + d},{lng + d},{lat - d}"})
    r.raise_for_status()
    j = r.json()
    return j if isinstance(j, list) else []


def _coincidencia(nombre: str, lat: float, lng: float) -> Optional[Dict[str, Any]]:
    n = _norm(nombre)
    if not n:
        return None
    mejor = None
    for p in _cerca(nombre, lat, lng):
        try:
            m = _metros(lat, lng, float(p["lat"]), float(p["lon"]))
        except (KeyError, ValueError, TypeError):
            continue
        titulo = p.get("name") or (p.get("display_name") or "").split(",")[0]
        t = _norm(titulo)
        sim = SequenceMatcher(None, n, t).ratio()
        if m <= _RADIO_M and (sim >= _SIMILITUD or n in t or t in n and len(t) >= 4):
            if mejor is None or m < mejor["distancia_m"]:
                mejor = {"nombre": titulo, "distancia_m": round(m)}
    return mejor


def reverse(lat: float, lng: float, precision_m: Optional[float] = None, nombre_local: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"direccion": None, "calle": None, "distrito": None, "provincia": None, "departamento": None,
                           "coincidencia": None, "mapa_url": mapa_url(lat, lng)}
    try:
        j = _reverse(lat, lng)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Geocodificación inversa falló (%s,%s): %s", lat, lng, exc)
        j = None
    if j:
        a = j["address"]
        via = a.get("road") or a.get("pedestrian") or a.get("footway") or a.get("path") or ""
        num = a.get("house_number") or ""
        calle = f"{via} {num}".strip() or (j.get("name") or "")
        distrito = _limpia(a.get("city_district") or a.get("suburb") or a.get("town") or a.get("village")
                           or a.get("municipality") or a.get("city") or "")
        provincia = _limpia(a.get("county") or a.get("city") or "")
        depto = _limpia(a.get("state") or a.get("region") or "")
        out.update({"calle": calle or None, "distrito": distrito or None, "provincia": provincia or None,
                    "departamento": depto or None,
                    "direccion": ", ".join(x for x in (calle, distrito) if x) or None})
    if nombre_local and str(nombre_local).strip():
        try:
            out["coincidencia"] = _coincidencia(str(nombre_local), lat, lng)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Búsqueda de coincidencia falló: %s", exc)
    return out


# --- Distrito → departamento para direcciones escritas a mano (sin GPS); misma tabla que el simulador (LIMA13, CALLAO13, DEP13) ---
_LIMA = ['Ancón', 'Ate', 'Barranco', 'Breña', 'Carabayllo', 'Chaclacayo', 'Chorrillos', 'Cieneguilla', 'Comas', 'El', 'Agustino', 'Independencia', 'Jesús', 'María', 'La', 'Molina', 'La', 'Victoria', 'Lince', 'Los', 'Olivos', 'Lurigancho', 'Lurín', 'Magdalena del', 'Mar', 'Miraflores', 'Pachacámac', 'Pucusana', 'Pueblo', 'Libre', 'Puente', 'Piedra', 'Punta', 'Hermosa', 'Punta', 'Negra', 'Rímac', 'San', 'Bartolo', 'San', 'Borja', 'San', 'Isidro', 'San', 'Juan de', 'Lurigancho', 'San', 'Juan de', 'Miraflores', 'San', 'Luis', 'San', 'Martín de', 'Porres', 'San', 'Miguel', 'Santa', 'Anita', 'Santa', 'María del', 'Mar', 'Santa', 'Rosa', 'Santiago de', 'Surco', 'Surco', 'Surquillo', 'Villa', 'El', 'Salvador', 'Villa', 'María del', 'Triunfo', 'Cercado de', 'Lima', 'Lima', 'Chancay', 'Huaral', 'Huacho', 'Huaura', 'Barranca', 'Cañete', 'San', 'Vicente de', 'Cañete', 'Mala', 'Asia', 'Chilca', 'Canta', 'Matucana', 'Supe', 'Paramonga']
_CALLAO = ['Callao', 'Bellavista', 'Carmen de la', 'Legua', 'La', 'Perla', 'La', 'Punta', 'Ventanilla', 'Mi', 'Perú']
_DEP = {'Arequipa': 'Arequipa', 'Trujillo': 'La Libertad', 'Chiclayo': 'Lambayeque', 'Piura': 'Piura', 'Cusco': 'Cusco', 'Ica': 'Ica', 'Chincha': 'Ica', 'Pisco': 'Ica', 'Huancayo': 'Junín', 'Tacna': 'Tacna', 'Puno': 'Puno', 'Juliaca': 'Puno', 'Iquitos': 'Loreto', 'Pucallpa': 'Ucayali', 'Chimbote': 'Áncash', 'Huaraz': 'Áncash', 'Cajamarca': 'Cajamarca', 'Ayacucho': 'Ayacucho', 'Tumbes': 'Tumbes', 'Moquegua': 'Moquegua', 'Ilo': 'Moquegua', 'Tarapoto': 'San Martín', 'Huánuco': 'Huánuco', 'Puerto Maldonado': 'Madre de Dios', 'Abancay': 'Apurímac', 'Huancavelica': 'Huancavelica', 'Chachapoyas': 'Amazonas'}


def departamento_de(distrito: Optional[str]) -> str:
    d = _norm(distrito or "")
    if not d:
        return ""
    if any(_norm(x) == d for x in _LIMA):
        return "Lima"
    if any(_norm(x) == d for x in _CALLAO):
        return "Callao"
    for k, v in _DEP.items():
        if _norm(k) == d:
            return v
    return ""
