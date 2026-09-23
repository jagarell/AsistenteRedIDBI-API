"""Definición del flujo conversacional de nodos.

Cada nodo captura un dato técnico del levantamiento de red. El flujo reemplaza
el checklist manual de IDBI y garantiza la completitud de la información
necesaria para el análisis, la propuesta y la topología.
"""
from enum import Enum
from typing import Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from app.chat.answers import is_yes, to_int


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
    model_config = ConfigDict(arbitrary_types_allowed=True)

    key: str
    question: str
    input_type: InputType
    options: Optional[List[str]] = None
    unit: Optional[str] = None
    required: bool = True
    help_text: Optional[str] = None
    # Nodos que el motor resuelve solo (ej. geocodificar el local a partir de
    # nombre+dirección) sin mostrarle una pregunta al técnico.
    auto: bool = False
    # Se salta el nodo (sin preguntarlo) si esta función, evaluada contra las
    # respuestas ya dadas, devuelve True — ej. no preguntar cuántos puertos
    # tiene el switch si el técnico ya dijo que no tiene switch. Ver
    # ChatEngine.answer, mismo mecanismo que usan los nodos `auto`.
    skip_if: Optional[Callable[[Dict[str, str]], bool]] = None


# Flujo de nodos (ver TOTAL_NODES). El orden define la secuencia de la conversación.
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
         question="Coordenadas GPS del local (calculadas automáticamente a partir del nombre y la dirección).",
         input_type=InputType.LOCATION,
         auto=True,
         required=False),
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
    Node(key="establishment_area_m2",
         question="¿Cuántos metros cuadrados tiene el local?",
         input_type=InputType.NUMBER,
         unit="m²"),
    Node(key="router_to_farthest_distance_m",
         question="¿Qué distancia aproximada hay entre el router y el punto de red más alejado (cocina, terraza, etc.)?",
         input_type=InputType.NUMBER,
         unit="metros",
         help_text="El cableado de cobre (TIA/EIA-568) tiene un límite de 100m; "
                    "más allá de eso la señal se degrada y hace falta fibra o "
                    "un rack intermedio."),
    Node(key="has_switches",
         question="¿El local cuenta con switches de red?",
         input_type=InputType.YES_NO),
    Node(key="switch_ports",
         question="¿Cuántos puertos tiene el switch en total?",
         input_type=InputType.NUMBER,
         unit="puertos",
         required=False,
         skip_if=lambda a: not is_yes(a.get("has_switches", ""))),
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
         help_text="Dato clave: determina si la impresora cuelga del POS (USB) o del switch (red).",
         skip_if=lambda a: to_int(a.get("printer_count", "0")) == 0),
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
    Node(key="wall_type",
         question="¿De qué material son las paredes principales del local?",
         input_type=InputType.CHOICE,
         options=["Drywall/madera", "Concreto/ladrillo", "Vidrio/mixto"],
         help_text="El material de las paredes afecta el alcance real del WiFi: "
                    "el concreto/ladrillo atenúa mucho más la señal que el "
                    "drywall, madera o vidrio."),
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
]

TOTAL_NODES = len(NODES)


def node_at(step: int) -> Optional[Node]:
    if 0 <= step < TOTAL_NODES:
        return NODES[step]
    return None
