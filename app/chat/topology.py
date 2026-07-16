"""Construcción de la topología de red a partir de las respuestas del chat.

Genera un diagrama jerárquico (Internet → Router → Switch → equipos) con las
conexiones clasificadas por tipo (Cable de red / WiFi / USB-Bluetooth), tal como
exige el diseño (HU11). Es determinista: mismas respuestas ⇒ misma topología.
"""
from typing import Dict, List

from app.chat.schemas import (
    ConnectionType,
    LinkStatus,
    Topology,
    TopologyLink,
    TopologyNode,
)


def _to_int(value: str, default: int = 0) -> int:
    if value is None:
        return default
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else default


def _is_yes(value: str) -> bool:
    return str(value).strip().lower() in {"sí", "si", "yes", "true", "1"}


def _split_multi(value: str) -> List[str]:
    if not value:
        return []
    return [v.strip() for v in str(value).split(",") if v.strip()]


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
    has_switch = _is_yes(answers.get("has_switches", "")) or _to_int(answers.get("switch_ports", "0")) > 0
    if has_switch:
        ports = _to_int(answers.get("switch_ports", "0"))
        label = f"Switch administrable ({ports} puertos)" if ports else "Switch administrable"
        parent_id = add_node("switch", label, "switch", 2)
        add_link(router_id, parent_id, ConnectionType.CABLE_RED)
    else:
        parent_id = router_id

    endpoint_level = 3

    # POS (cableados)
    pos_ids: List[str] = []
    for i in range(1, _to_int(answers.get("pos_count", "0")) + 1):
        pid = add_node(f"pos_{i}", f"POS {i}", "pos", endpoint_level)
        add_link(parent_id, pid, ConnectionType.CABLE_RED)
        pos_ids.append(pid)

    # Impresoras: USB (cuelgan de un POS) o puerto de red (cuelgan del switch/router)
    printer_conn = answers.get("printer_connection", "Puerto de red").lower()
    for i in range(1, _to_int(answers.get("printer_count", "0")) + 1):
        pid = add_node(f"printer_{i}", f"Impresora {i}", "printer", endpoint_level)
        if "usb" in printer_conn and pos_ids:
            host = pos_ids[(i - 1) % len(pos_ids)]
            add_link(host, pid, ConnectionType.USB_BLUETOOTH)
        else:
            add_link(parent_id, pid, ConnectionType.CABLE_RED)

    # Cámaras (cableadas / PoE)
    for i in range(1, _to_int(answers.get("camera_count", "0")) + 1):
        cid = add_node(f"camera_{i}", f"Cámara {i}", "camera", endpoint_level)
        add_link(parent_id, cid, ConnectionType.CABLE_RED)

    # Computadoras (cableadas)
    for i in range(1, _to_int(answers.get("computer_count", "0")) + 1):
        cid = add_node(f"computer_{i}", f"PC {i}", "computer", endpoint_level)
        add_link(parent_id, cid, ConnectionType.CABLE_RED)

    # Access Points por zona WiFi: backhaul cableado + clientes por WiFi
    zones = _split_multi(answers.get("wifi_zones", ""))
    if zones:
        clients_id = add_node("wifi_clients", "Dispositivos WiFi", "computer", endpoint_level + 1)
        for idx, zone in enumerate(zones, start=1):
            ap_id = add_node(f"ap_{idx}", f"Access Point {zone}", "access_point", endpoint_level)
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
