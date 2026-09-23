"""Construcción de la topología de red a partir de las respuestas del chat.

Genera un diagrama jerárquico (Internet → Router → Switch → equipos) con las
conexiones clasificadas por tipo (Cable de red / WiFi / USB-Bluetooth), tal como
exige el diseño (HU11). Es determinista: mismas respuestas ⇒ misma topología.
"""
import math
from typing import Dict, List

from app.chat.answers import is_yes, split_multi, to_int
from app.chat.schemas import (
    ConnectionType,
    LinkStatus,
    Topology,
    TopologyLink,
    TopologyNode,
)

# Cobertura útil estimada de un access point indoor, en m² (valores estándar
# de industria, ajustables): el concreto/ladrillo atenúa la señal WiFi mucho
# más que el drywall, la madera o el vidrio.
AP_COVERAGE_M2_OPEN = 150
AP_COVERAGE_M2_CONCRETE = 80


def ap_coverage_m2(wall_type: str) -> int:
    """Cobertura útil (m²) de un access point según el material de las paredes."""
    return AP_COVERAGE_M2_CONCRETE if "concreto" in (wall_type or "").lower() else AP_COVERAGE_M2_OPEN


def ap_count_for_zone(area_per_zone: float, wall_type: str) -> int:
    """Cuántos access points hacen falta para cubrir una zona de cierta área."""
    if not area_per_zone:
        return 1
    coverage = ap_coverage_m2(wall_type)
    return max(1, math.ceil(area_per_zone / coverage))


def build_topology(answers: Dict[str, str]) -> Topology:
    nodes: List[TopologyNode] = []
    links: List[TopologyLink] = []

    def add_node(node_id: str, label: str, type_: str, level: int) -> str:
        nodes.append(TopologyNode(id=node_id, label=label, type=type_, level=level))
        return node_id

    def add_link(src: str, dst: str, conn: ConnectionType) -> None:
        links.append(TopologyLink(
            source=src, target=dst, connectionType=conn, status=LinkStatus.OPERATIVO
        ))

    # Nivel 0: Internet
    provider = answers.get("internet_provider", "Proveedor de Internet")
    internet_id = add_node("internet", f"Internet ({provider})", "internet", 0)

    # Nivel 1: Router / Firewall
    router_label = answers.get("router_model") or "Router / Firewall"
    router_id = add_node("router", router_label, "router", 1)
    add_link(internet_id, router_id, ConnectionType.CABLE_RED)

    # Nivel 2: Switch (si existe). Es el "padre" de los equipos si está presente.
    has_switch = is_yes(answers.get("has_switches", "")) or to_int(answers.get("switch_ports", "0")) > 0
    if has_switch:
        ports = to_int(answers.get("switch_ports", "0"))
        label = f"Switch administrable ({ports} puertos)" if ports else "Switch administrable"
        parent_id = add_node("switch", label, "switch", 2)
        add_link(router_id, parent_id, ConnectionType.CABLE_RED)
    else:
        parent_id = router_id

    endpoint_level = 3

    # POS (cableados)
    pos_ids: List[str] = []
    for i in range(1, to_int(answers.get("pos_count", "0")) + 1):
        pid = add_node(f"pos_{i}", f"POS {i}", "pos", endpoint_level)
        add_link(parent_id, pid, ConnectionType.CABLE_RED)
        pos_ids.append(pid)

    # Impresoras: USB (cuelgan de un POS) o puerto de red (cuelgan del switch/router)
    printer_conn = answers.get("printer_connection", "Puerto de red").lower()
    for i in range(1, to_int(answers.get("printer_count", "0")) + 1):
        pid = add_node(f"printer_{i}", f"Impresora {i}", "printer", endpoint_level)
        if "usb" in printer_conn and pos_ids:
            host = pos_ids[(i - 1) % len(pos_ids)]
            add_link(host, pid, ConnectionType.USB_BLUETOOTH)
        else:
            add_link(parent_id, pid, ConnectionType.CABLE_RED)

    # Cámaras (cableadas / PoE)
    for i in range(1, to_int(answers.get("camera_count", "0")) + 1):
        cid = add_node(f"camera_{i}", f"Cámara {i}", "camera", endpoint_level)
        add_link(parent_id, cid, ConnectionType.CABLE_RED)

    # Computadoras (cableadas)
    for i in range(1, to_int(answers.get("computer_count", "0")) + 1):
        cid = add_node(f"computer_{i}", f"PC {i}", "computer", endpoint_level)
        add_link(parent_id, cid, ConnectionType.CABLE_RED)

    # Access Points por zona WiFi: backhaul cableado + clientes por WiFi.
    # Si el área por zona excede la cobertura útil de un AP (según el material
    # de las paredes), se agregan APs adicionales para esa zona.
    zones = split_multi(answers.get("wifi_zones", ""))
    if zones:
        clients_id = add_node("wifi_clients", "Dispositivos WiFi", "computer", endpoint_level + 1)
        area = to_int(answers.get("establishment_area_m2", "0"))
        wall_type = answers.get("wall_type", "")
        area_per_zone = area / len(zones) if area else 0
        aps_per_zone = ap_count_for_zone(area_per_zone, wall_type)
        ap_counter = 0
        for zone in zones:
            for i in range(aps_per_zone):
                ap_counter += 1
                label = f"Access Point {zone}" if aps_per_zone == 1 else f"Access Point {zone} ({i + 1})"
                ap_id = add_node(f"ap_{ap_counter}", label, "access_point", endpoint_level)
                add_link(parent_id, ap_id, ConnectionType.CABLE_RED)      # backhaul cableado
                add_link(ap_id, clients_id, ConnectionType.WIFI)          # cobertura inalámbrica

    return Topology(nodes=nodes, links=links)


def topology_to_text(topology: Topology) -> str:
    """Texto resumido de la topología (compatibilidad con topologyText)."""
    if not topology.nodes:
        return "Topología no disponible."
    levels: Dict[int, List[str]] = {}
    for node in topology.nodes:
        levels.setdefault(node.level, []).append(node.label)
    ordered = [", ".join(levels[lvl]) for lvl in sorted(levels)]
    return " → ".join(ordered)
