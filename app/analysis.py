"""Análisis IA de infraestructura a partir de las respuestas del chat técnico
(ver TOTAL_NODES en app.chat.nodes). Reusa el MISMO motor de reglas que app.chat.proposal (AS-IS/TO-BE)
para el score/diagnóstico/recomendaciones — es una sola fuente de verdad con
la propuesta del chat — y le agrega el desglose por 4 áreas que muestra la
pantalla "Análisis IA" del app (Conectividad, Infraestructura Física,
Equipamiento, Cobertura WiFi), que la propuesta completa no expone.
"""
from typing import Dict, List, Optional

from pydantic import BaseModel

from app.chat.answers import is_yes, split_multi, to_int
from app.chat.proposal import generate_proposal


class AnalysisItem(BaseModel):
    title: str
    status: str
    score: int
    description: str
    color: str


class AnalysisResult(BaseModel):
    globalScore: int
    evaluatedAreas: int
    attentionRequired: int
    results: List[AnalysisItem]
    summary: str
    asIsFindings: List[str] = []
    recommendations: List[str]


def _clamp(score: int) -> int:
    return max(0, min(100, score))


def _status_and_color(score: int) -> tuple[str, str]:
    if score >= 80:
        return "Óptimo", "green"
    if score >= 65:
        return "Buena", "blue"
    if score >= 50:
        return "Regular", "orange"
    return "Deficiente", "red"


def _connectivity_item(answers: Dict[str, str]) -> AnalysisItem:
    speed = to_int(answers.get("internet_speed", "0"))
    conn_type = (answers.get("connection_type", "") or "").strip()

    score = 50
    if speed >= 200:
        score += 30
    elif speed >= 100:
        score += 20
    elif speed >= 50:
        score += 10
    elif speed > 0:
        score -= 10

    if conn_type == "Fibra óptica":
        score += 15
    elif conn_type in {"Cable", "4G/5G"}:
        score += 5
    elif conn_type == "Satelital":
        score -= 10
    elif conn_type == "DSL":
        score -= 5

    score = _clamp(score)
    status, color = _status_and_color(score)
    speed_text = f"{speed} Mbps" if speed else "velocidad no registrada"
    description = f"Conexión {conn_type or 'no especificada'} ({speed_text})."
    return AnalysisItem(title="Conectividad de Red", status=status, score=score, description=description, color=color)


def _physical_infra_item(answers: Dict[str, str]) -> AnalysisItem:
    has_switch = is_yes(answers.get("has_switches", "")) or to_int(answers.get("switch_ports", "0")) > 0
    has_outlets = is_yes(answers.get("power_outlets", ""))
    router = (answers.get("router_model", "") or "").strip()

    score = 50
    score += 20 if has_switch else -15
    score += 15 if has_outlets else -15
    score += 10 if router else -5
    score = _clamp(score)

    status, color = _status_and_color(score)
    parts = []
    parts.append("con switch" if has_switch else "sin switch dedicado")
    parts.append("con tomacorrientes normados" if has_outlets else "sin tomacorrientes junto a los puntos de red")
    description = f"Cableado {parts[0]}, {parts[1]}."
    return AnalysisItem(title="Infraestructura Física", status=status, score=score, description=description, color=color)


def _equipment_item(answers: Dict[str, str]) -> AnalysisItem:
    ports = to_int(answers.get("switch_ports", "0"))
    devices = sum(
        to_int(answers.get(key, "0"))
        for key in ("pos_count", "printer_count", "camera_count", "computer_count")
    )

    score = 70
    if devices > 0:
        if ports == 0:
            score -= 25
        else:
            ratio = devices / ports
            if ratio <= 0.7:
                score += 20
            elif ratio <= 1.0:
                score += 5
            else:
                score -= 25
    score = _clamp(score)

    status, color = _status_and_color(score)
    description = f"{devices} equipo(s) de red requeridos frente a {ports} puerto(s) de switch disponibles."
    return AnalysisItem(title="Equipamiento", status=status, score=score, description=description, color=color)


def _wifi_item(answers: Dict[str, str]) -> AnalysisItem:
    zones = split_multi(answers.get("wifi_zones", ""))
    wall_type = (answers.get("wall_type", "") or "").strip()

    score = _clamp(35 + len(zones) * 13)
    # El concreto/ladrillo atenúa mucho más la señal que drywall/madera/vidrio
    # (mismo criterio que app.chat.topology.ap_coverage_m2): penaliza el
    # score si hay zonas que cubrir y las paredes son de concreto.
    if zones and "concreto" in wall_type.lower():
        score = _clamp(score - 15)

    status, color = _status_and_color(score)
    wall_note = f", paredes de {wall_type.lower()}" if wall_type else ""
    description = (
        f"Cobertura solicitada en {len(zones)} área(s): {', '.join(zones)}{wall_note}."
        if zones else "No se especificaron áreas que requieran cobertura WiFi."
    )
    return AnalysisItem(title="Cobertura WiFi", status=status, score=score, description=description, color=color)


def compute_analysis(
    answers: Dict[str, str],
    establishment_name: str,
    detected_equipment: Optional[Dict[str, dict]] = None,
) -> AnalysisResult:
    """Desglose por 4 áreas (para las tarjetas de la pantalla) + AS-IS/TO-BE
    real, generado por el mismo motor que la propuesta del chat
    (app.chat.proposal.generate_proposal) — una sola fuente de verdad para el
    score, el diagnóstico y las recomendaciones."""
    items = [
        _connectivity_item(answers),
        _physical_infra_item(answers),
        _equipment_item(answers),
        _wifi_item(answers),
    ]
    attention_required = sum(1 for item in items if item.score < 65)

    proposal = generate_proposal(answers, detected_equipment=detected_equipment)

    return AnalysisResult(
        globalScore=proposal.score if proposal.score is not None else round(
            sum(item.score for item in items) / len(items)
        ),
        evaluatedAreas=len(items),
        attentionRequired=attention_required,
        results=items,
        summary=proposal.summary,
        asIsFindings=proposal.asIsFindings,
        recommendations=proposal.recommendations,
    )
