"""Generación de la propuesta técnica a partir de las respuestas.

Motor de reglas determinista (no depende de un LLM). El seam de IA/Flowise se
resuelve en engine.py; aquí vive la lógica base que también sirve de fallback.
"""
from typing import Dict, List

from app.chat.schemas import ChatProposal, EquipmentRecommendation
from app.chat.topology import build_topology, topology_to_text


def _to_int(value: str, default: int = 0) -> int:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return int(digits) if digits else default


def _is_yes(value: str) -> bool:
    return str(value or "").strip().lower() in {"sí", "si", "yes", "true", "1"}


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


def generate_proposal(answers: Dict[str, str]) -> ChatProposal:
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

    zones = [z for z in (answers.get("wifi_zones", "") or "").split(",") if z.strip()]
    if zones:
        recommendations.append(
            "Instalar access points administrables para cubrir: "
            + ", ".join(z.strip() for z in zones) + "."
        )
        equipment.append(EquipmentRecommendation(
            name="Access Point WiFi 6",
            description="Punto de acceso administrable para ampliar cobertura.",
            quantity=max(1, len(zones)),
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
        recommendations=recommendations,
        equipment=equipment,
        topologyText=topology_to_text(topology),
        topology=topology,
        score=score,
    )
