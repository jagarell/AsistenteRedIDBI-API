"""Generación de la propuesta técnica a partir de las respuestas.

Motor de reglas determinista (no depende de un LLM). El seam de IA/Flowise se
resuelve en engine.py; aquí vive la lógica base que también sirve de fallback.
"""
from typing import Dict, List, Optional

from app.chat.schemas import ChatProposal, EquipmentRecommendation
from app.chat.topology import ap_coverage_m2, ap_count_for_zone, build_topology, topology_to_text

# --- Umbrales de ingeniería de red usados para el diagnóstico AS-IS ---
# Son valores estándar de industria, ajustables; no reemplazan un estudio de
# sitio real, pero permiten razonar sobre los datos del chat en vez de solo
# contar equipos.
BANDWIDTH_MBPS_PER_POS = 2
BANDWIDTH_MBPS_PER_CAMERA = 4
BANDWIDTH_MBPS_PER_WIFI_CLIENT = 5
BANDWIDTH_HEADROOM = 0.7  # el plan contratado debería cubrir la demanda con holgura

MAX_CABLE_RUN_M = 100  # límite de cobre TIA/EIA-568
CABLE_WARNING_M = 90   # margen de seguridad antes del límite

POE_BUDGET_W = 130  # presupuesto típico de un switch PoE de gama media
CAMERA_POE_W = 7
AP_POE_W = 15

REDUNDANCY_POS_THRESHOLD = 3  # a partir de aquí, un solo enlace es un riesgo real


def _to_int(value: str, default: int = 0) -> int:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return int(digits) if digits else default


def _is_yes(value: str) -> bool:
    return str(value or "").strip().lower() in {"sí", "si", "yes", "true", "1"}


def _split_zones(value: str) -> List[str]:
    return [z.strip() for z in (value or "").split(",") if z.strip()]


def _compute_as_is(
    answers: Dict[str, str],
    detected_equipment: Optional[Dict[str, dict]] = None,
) -> List[str]:
    """Diagnóstico del estado actual (AS-IS): describe lo que existe hoy con
    los datos del chat, sin proponer soluciones (eso vive en `recommendations`,
    el TO-BE). `detected_equipment` son hallazgos reales extraídos por visión
    de las fotos de evidencia (ej. {"router": {"brand": "TP-Link", "model":
    "Archer C6"}}) — cuando existen, se agregan y se contrastan contra lo
    autorreportado en el chat en vez de confiar solo en el texto del técnico."""
    findings: List[str] = []

    pos_count = _to_int(answers.get("pos_count", "0"))
    camera_count = _to_int(answers.get("camera_count", "0"))
    computer_count = _to_int(answers.get("computer_count", "0"))
    zones = _split_zones(answers.get("wifi_zones", ""))
    wifi_clients = max(computer_count, len(zones) * 3)

    # --- Ancho de banda: demanda estimada vs plan contratado ---
    speed = _to_int(answers.get("internet_speed", "0"))
    if speed:
        demand = (
            pos_count * BANDWIDTH_MBPS_PER_POS
            + camera_count * BANDWIDTH_MBPS_PER_CAMERA
            + wifi_clients * BANDWIDTH_MBPS_PER_WIFI_CLIENT
        )
        findings.append(
            f"Internet contratado: {speed} Mbps para una demanda estimada de "
            f"~{demand} Mbps ({pos_count} POS, {camera_count} cámaras, "
            f"~{wifi_clients} clientes WiFi concurrentes)."
        )
        if demand > speed * BANDWIDTH_HEADROOM:
            findings.append(
                "La demanda estimada está cerca o supera el ancho de banda "
                "contratado; es probable que se sature en horas pico."
            )

    # --- Distancia de cableado vs límite de cobre ---
    distance = _to_int(answers.get("router_to_farthest_distance_m", "0"))
    if distance >= MAX_CABLE_RUN_M:
        findings.append(
            f"El punto más alejado está a {distance}m del router, superando "
            f"el límite de {MAX_CABLE_RUN_M}m del cableado de cobre "
            "(TIA/EIA-568); hoy ese punto no puede cablearse de forma confiable."
        )
    elif distance >= CABLE_WARNING_M:
        findings.append(
            f"El punto más alejado está a {distance}m del router, cerca del "
            f"límite de {MAX_CABLE_RUN_M}m del cableado de cobre (TIA/EIA-568)."
        )

    # --- Cobertura WiFi vs área y material de paredes ---
    area = _to_int(answers.get("establishment_area_m2", "0"))
    wall_type = answers.get("wall_type", "")
    if area and zones:
        coverage = ap_coverage_m2(wall_type)
        area_per_zone = area / len(zones)
        if area_per_zone > coverage:
            findings.append(
                f"Local de {area}m² repartido en {len(zones)} zona(s) "
                f"(~{int(area_per_zone)}m² c/u) con paredes de "
                f"{(wall_type or 'material no indicado').lower()}; un solo "
                f"access point por zona (cobertura útil ~{coverage}m²) no "
                "alcanza a cubrir el área de forma confiable."
            )

    # --- Switch / cableado estructurado ---
    has_switch = _is_yes(answers.get("has_switches", "")) or _to_int(answers.get("switch_ports", "0")) > 0
    if not has_switch:
        findings.append(
            "No hay switch administrable: las conexiones cableadas dependen "
            "directamente del router."
        )

    # --- Presupuesto PoE para cámaras y access points ---
    ap_estimate = max(1, len(zones))
    poe_demand = camera_count * CAMERA_POE_W + ap_estimate * AP_POE_W
    if poe_demand > POE_BUDGET_W:
        findings.append(
            f"Cámaras y access points demandarían ~{poe_demand}W de PoE, por "
            f"encima del presupuesto típico de un switch PoE estándar "
            f"(~{POE_BUDGET_W}W)."
        )

    # --- Tomacorrientes junto a cada punto de red ---
    if not _is_yes(answers.get("power_outlets", "")):
        findings.append(
            "No hay tomacorrientes adyacentes a cada punto de red (norma TIA/EIA-568)."
        )

    # --- Redundancia de enlace ---
    services = (answers.get("services", "") or "").lower()
    if pos_count >= REDUNDANCY_POS_THRESHOLD and "respaldo" not in services:
        findings.append(
            f"El negocio depende de {pos_count} POS sobre un único enlace de "
            "internet, sin respaldo ante una caída del proveedor."
        )

    # --- Equipos confirmados por foto (visión) ---
    # Los nombres de nodo autorreportados que contrastar por categoría.
    self_reported_keys = {"router": "router_model", "switch": None}
    for category, detected in (detected_equipment or {}).items():
        brand = (detected or {}).get("brand")
        model = (detected or {}).get("model")
        if not brand and not model:
            continue
        detected_label = " ".join(part for part in (brand, model) if part)
        self_reported_key = self_reported_keys.get(category)
        self_reported = (answers.get(self_reported_key) or "").strip() if self_reported_key else ""
        if self_reported and self_reported.lower() not in detected_label.lower():
            findings.append(
                f"El técnico reportó '{self_reported}' para {category}, pero la "
                f"foto muestra '{detected_label}' — verificar cuál es el equipo real."
            )
        else:
            findings.append(f"Foto confirma el equipo en {category}: {detected_label}.")

    if not findings:
        findings.append(
            "No se detectaron limitaciones críticas en la infraestructura "
            "actual con los datos disponibles."
        )

    return findings


def _compute_score(answers: Dict[str, str]) -> int:
    """Puntaje 0-100 de la infraestructura actual (heurístico)."""
    score = 50
    speed = _to_int(answers.get("internet_speed", "0"))
    if speed >= 200:
        score += 20
    elif speed >= 100:
        score += 12
    elif speed >= 50:
        score += 6

    if _is_yes(answers.get("has_switches", "")) or _to_int(answers.get("switch_ports", "0")) > 0:
        score += 10
    if _is_yes(answers.get("power_outlets", "")):
        score += 8
    else:
        score -= 8

    services = (answers.get("services", "") or "").lower()
    if "firewall" in services:
        score += 6
    if "vlan" in services:
        score += 4
    if "respaldo" in services:
        score += 4

    return max(0, min(100, score))


def generate_proposal(
    answers: Dict[str, str],
    detected_equipment: Optional[Dict[str, dict]] = None,
) -> ChatProposal:
    recommendations: List[str] = []
    equipment: List[EquipmentRecommendation] = []

    speed = _to_int(answers.get("internet_speed", "0"))
    if speed and speed < 100:
        recommendations.append(
            f"La velocidad contratada ({speed} Mbps) es baja para un local con "
            "POS y WiFi; evaluar un plan de mayor ancho de banda."
        )

    has_switch = _is_yes(answers.get("has_switches", "")) or _to_int(answers.get("switch_ports", "0")) > 0
    if not has_switch:
        recommendations.append(
            "Centralizar las conexiones cableadas en un switch administrable."
        )
        equipment.append(EquipmentRecommendation(
            name="Switch administrable",
            description="Switch de 24 puertos con soporte VLAN.",
            quantity=1,
        ))

    zones = _split_zones(answers.get("wifi_zones", ""))
    if zones:
        area = _to_int(answers.get("establishment_area_m2", "0"))
        wall_type = answers.get("wall_type", "")
        area_per_zone = area / len(zones) if area else 0
        aps_per_zone = ap_count_for_zone(area_per_zone, wall_type)
        recommendations.append(
            "Instalar access points administrables para cubrir: "
            + ", ".join(zones) + "."
        )
        equipment.append(EquipmentRecommendation(
            name="Access Point WiFi 6",
            description="Punto de acceso administrable para ampliar cobertura.",
            quantity=aps_per_zone * len(zones),
        ))

    if _to_int(answers.get("camera_count", "0")) > 0:
        recommendations.append(
            "Usar un switch PoE para alimentar cámaras y access points por el mismo cable."
        )
        equipment.append(EquipmentRecommendation(
            name="Switch PoE administrable",
            description="Switch PoE para cámaras y access points.",
            quantity=1,
        ))

    if _to_int(answers.get("pos_count", "0")) > 0:
        recommendations.append(
            "Separar el tráfico de POS/cajas en una VLAN exclusiva."
        )

    services = (answers.get("services", "") or "").lower()
    if "invitados" in services:
        recommendations.append("Crear una red WiFi de invitados aislada de la red administrativa.")
    if "firewall" in services or "vlan" in services:
        recommendations.append("Implementar firewall y segmentación por VLAN.")
    if "respaldo" in services:
        recommendations.append("Implementar un segundo enlace de internet con failover automático.")

    if not _is_yes(answers.get("power_outlets", "")):
        recommendations.append(
            "Habilitar tomacorrientes adyacentes a cada punto de red (norma TIA/EIA-568)."
        )

    if not recommendations:
        recommendations.append("La infraestructura actual cubre los requisitos mínimos; mantener monitoreo.")

    if not any(e.name.startswith("Router") for e in equipment):
        equipment.insert(0, EquipmentRecommendation(
            name="Router empresarial",
            description="Router con firewall y administración centralizada.",
            quantity=1,
        ))

    topology = build_topology(answers)
    score = _compute_score(answers)
    establishment = answers.get("establishment_name", "el establecimiento")

    if score >= 80:
        quality = "óptima"
    elif score >= 60:
        quality = "aceptable"
    else:
        quality = "deficiente"

    summary = (
        f"Para {establishment} se recomienda una infraestructura segmentada, "
        f"administrable y preparada para crecimiento. Evaluación de la "
        f"infraestructura actual: {quality} ({score}/100)."
    )

    return ChatProposal(
        summary=summary,
        asIsFindings=_compute_as_is(answers, detected_equipment),
        recommendations=recommendations,
        equipment=equipment,
        topologyText=topology_to_text(topology),
        topology=topology,
        score=score,
    )
