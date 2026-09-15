"""Semilla del checklist de evidencias (áreas + equipos a fotografiar) a
partir de las respuestas reales del chat — a diferencia de
`generate_proposal().equipment` (que es la lista de COMPRA recomendada,
TO-BE), esto es lo que YA EXISTE y hay que fotografiar como evidencia
(AS-IS), a partir de las cantidades reportadas.
"""
from typing import Dict, List

from pydantic import BaseModel


class ChecklistArea(BaseModel):
    name: str


class ChecklistEquipment(BaseModel):
    equipmentType: str
    label: str


class EvidenceChecklistSeed(BaseModel):
    areas: List[ChecklistArea]
    equipment: List[ChecklistEquipment]


def _to_int(value: str, default: int = 0) -> int:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return int(digits) if digits else default


def _is_yes(value: str) -> bool:
    return str(value or "").strip().lower() in {"sí", "si", "yes", "true", "1"}


def build_evidence_checklist(answers: Dict[str, str]) -> EvidenceChecklistSeed:
    zones = [z.strip() for z in (answers.get("wifi_zones", "") or "").split(",") if z.strip()]

    areas: List[ChecklistArea] = [
        ChecklistArea(name="Rack / Router"),
        # Área fija reservada para el plano del local y el diagrama de
        # topología — no es una zona física, pero necesita su propio ítem
        # con foto(s) igual que cualquier área real (ver EvidenceFragment).
        ChecklistArea(name="Plano y Topología"),
    ]
    areas.extend(ChecklistArea(name=zone) for zone in zones)

    equipment: List[ChecklistEquipment] = [
        ChecklistEquipment(equipmentType="router", label=answers.get("router_model") or "Router")
    ]

    has_switch = _is_yes(answers.get("has_switches", "")) or _to_int(answers.get("switch_ports", "0")) > 0
    if has_switch:
        equipment.append(ChecklistEquipment(equipmentType="switch", label="Switch"))

    if _to_int(answers.get("pos_count", "0")) > 0:
        equipment.append(ChecklistEquipment(
            equipmentType="pos", label=f"POS (x{_to_int(answers.get('pos_count', '0'))})"
        ))

    if _to_int(answers.get("printer_count", "0")) > 0:
        equipment.append(ChecklistEquipment(
            equipmentType="printer", label=f"Impresora/ticketera (x{_to_int(answers.get('printer_count', '0'))})"
        ))

    if _to_int(answers.get("camera_count", "0")) > 0:
        equipment.append(ChecklistEquipment(
            equipmentType="camera", label=f"Cámara de seguridad (x{_to_int(answers.get('camera_count', '0'))})"
        ))

    if _to_int(answers.get("computer_count", "0")) > 0:
        equipment.append(ChecklistEquipment(
            equipmentType="computer", label=f"Computadora/laptop (x{_to_int(answers.get('computer_count', '0'))})"
        ))

    if zones:
        equipment.append(ChecklistEquipment(
            equipmentType="access_point", label=f"Access point (x{len(zones)} zona(s))"
        ))

    return EvidenceChecklistSeed(areas=areas, equipment=equipment)
