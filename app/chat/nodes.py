"""Definición del flujo conversacional de 20 nodos.

Cada nodo captura un dato técnico del levantamiento de red. El flujo reemplaza
el checklist manual de IDBI y garantiza la completitud de la información
necesaria para el análisis, la propuesta y la topología.
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class InputType(str, Enum):
    """Los 8 tipos de entrada soportados por el grafo dinámico."""
    TEXT = "TEXT"
    NUMBER = "NUMBER"
    CHOICE = "CHOICE"            # selección única
    MULTI_SELECT = "MULTI_SELECT"  # selección múltiple (respuesta: opciones separadas por coma)
    YES_NO = "YES_NO"
    PHOTO = "PHOTO"
    LOCATION = "LOCATION"        # coordenadas GPS
    CONNECTION_MAP = "CONNECTION_MAP"  # mapa de conexiones entre equipos


class Node(BaseModel):
    key: str
    question: str
    input_type: InputType
    options: Optional[List[str]] = None
    unit: Optional[str] = None
    required: bool = True
    help_text: Optional[str] = None


# Flujo de 20 nodos. El orden define la secuencia de la conversación.
NODES: List[Node] = [
    Node(key="establishment_name",
         question="¿Cuál es el nombre del establecimiento que vamos a evaluar?",
         input_type=InputType.TEXT),
    Node(key="establishment_type",
         question="¿Qué tipo de establecimiento es?",
         input_type=InputType.CHOICE,
         options=["Restaurante", "Cafetería", "Bar", "Comida rápida", "Otro"]),
    Node(key="address",
         question="¿Cuál es la dirección del local?",
         input_type=InputType.TEXT),
    Node(key="location",
         question="Registra las coordenadas GPS del local.",
         input_type=InputType.LOCATION,
         help_text="Si no hay señal GPS, ingresa la ubicación manualmente."),
    Node(key="internet_provider",
         question="¿Qué proveedor de internet utiliza el local?",
         input_type=InputType.TEXT),
    Node(key="internet_speed",
         question="¿Cuál es la velocidad de internet contratada?",
         input_type=InputType.NUMBER,
         unit="Mbps"),
    Node(key="connection_type",
         question="¿Qué tipo de conexión a internet tiene?",
         input_type=InputType.CHOICE,
         options=["Fibra óptica", "Cable", "DSL", "Satelital", "4G/5G"]),
    Node(key="router_model",
         question="¿Qué router o módem tiene actualmente? Indica marca/modelo.",
         input_type=InputType.TEXT),
    Node(key="router_location",
         question="¿Dónde está instalado el router principal?",
         input_type=InputType.TEXT),
    Node(key="has_switches",
         question="¿El local cuenta con switches de red?",
         input_type=InputType.YES_NO),
    Node(key="switch_ports",
         question="Si tiene switch, ¿cuántos puertos tiene en total? (0 si no aplica)",
         input_type=InputType.NUMBER,
         unit="puertos",
         required=False),
    Node(key="pos_count",
         question="¿Cuántos POS (puntos de venta) necesitan conexión?",
         input_type=InputType.NUMBER,
         unit="equipos"),
    Node(key="printer_count",
         question="¿Cuántas impresoras/ticketeras hay?",
         input_type=InputType.NUMBER,
         unit="equipos"),
    Node(key="printer_connection",
         question="¿Cómo se conectan las impresoras/ticketeras?",
         input_type=InputType.CHOICE,
         options=["USB", "Puerto de red", "Ambos"],
         help_text="Dato clave: determina si la impresora cuelga del POS (USB) o del switch (red)."),
    Node(key="camera_count",
         question="¿Cuántas cámaras de seguridad requieren red?",
         input_type=InputType.NUMBER,
         unit="equipos",
         required=False),
    Node(key="computer_count",
         question="¿Cuántas computadoras/laptops necesitan conexión?",
         input_type=InputType.NUMBER,
         unit="equipos",
         required=False),
    Node(key="wifi_zones",
         question="¿En qué áreas necesita cobertura WiFi?",
         input_type=InputType.MULTI_SELECT,
         options=["Caja", "Cocina", "Barra", "Comedor", "Terraza", "Almacén"]),
    Node(key="power_outlets",
         question="¿Hay tomacorrientes cercanos a cada punto de red? (norma TIA/EIA-568)",
         input_type=InputType.YES_NO,
         help_text="Cada punto de telecomunicaciones requiere un tomacorriente adyacente."),
    Node(key="services",
         question="¿Qué servicios adicionales necesita?",
         input_type=InputType.MULTI_SELECT,
         options=["Red de invitados", "VLAN", "Firewall", "Enlace de respaldo"],
         required=False),
    Node(key="photos",
         question="Adjunta fotos de las zonas críticas (caja, cocina, barra, rack).",
         input_type=InputType.PHOTO,
         required=False),
]

TOTAL_NODES = len(NODES)


def node_at(step: int) -> Optional[Node]:
    if 0 <= step < TOTAL_NODES:
        return NODES[step]
    return None
