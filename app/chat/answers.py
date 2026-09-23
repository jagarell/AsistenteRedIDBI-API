"""Parseo centralizado de las respuestas crudas del chat (siempre strings,
sin importar el InputType — ver ChatEngine.answer). Antes existían 4 copias
casi idénticas de estas mismas funciones en proposal.py, checklist.py,
analysis.py y topology.py; se consolidan acá para que un ajuste (ej. aceptar
otro valor afirmativo) no tenga que repetirse en 4 lugares.
"""
from typing import List


def to_int(value: str, default: int = 0) -> int:
    """Extrae dígitos de una respuesta NUMBER — cualquier texto no numérico
    (ej. "muchos") cae silenciosamente al default en vez de fallar."""
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return int(digits) if digits else default


def is_yes(value: str) -> bool:
    """Interpreta una respuesta YES_NO — sea cual sea el string exacto que
    mande el cliente ("Sí", "si", "true", "1")."""
    return str(value or "").strip().lower() in {"sí", "si", "yes", "true", "1"}


def split_multi(value: str) -> List[str]:
    """Separa una respuesta MULTI_SELECT (opciones unidas por coma) en una
    lista real — usar siempre esto para MULTI_SELECT, nunca comparar el
    string crudo con `in` (ver el bug histórico de `services` en proposal.py)."""
    return [v.strip() for v in str(value or "").split(",") if v.strip()]
