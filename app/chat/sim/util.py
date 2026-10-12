"""Ayudas para que el código portado se comporte como el JavaScript original."""
import math
import re
import unicodedata
from typing import Any, Iterable, List


class Obj(dict):
    """dict con acceso por atributo; un atributo que no existe vale None (como `undefined` en JS)."""

    def __getattr__(self, key: str) -> Any:
        return self.get(key)

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


def jsround(x: float) -> int:
    """Math.round de JavaScript (la mitad se redondea hacia arriba)."""
    return int(math.floor(x + 0.5))


def fmt(n: Any) -> str:
    """Número como lo escribe JavaScript en una plantilla: 94.0 -> '94', 93.5 -> '93.5'."""
    if isinstance(n, bool) or n is None:
        return "" if n is None else str(n).lower()
    if isinstance(n, float):
        if math.isnan(n):
            return "NaN"
        if n.is_integer():
            return str(int(n))
        return repr(n)
    return str(n)


def num(x: Any) -> float:
    """`+x || 0`: número o 0 si no se puede convertir."""
    try:
        if x is None or x == "":
            return 0
        value = float(x)
        if math.isnan(value):
            return 0
        return int(value) if value.is_integer() else value
    except (TypeError, ValueError):
        return 0


def parse_int(x: Any) -> int | None:
    """parseInt de JavaScript: dígitos iniciales o None."""
    m = re.match(r"\s*[-+]?\d+", str(x if x is not None else ""))
    return int(m.group(0)) if m else None


def uniq(items: Iterable[Any]) -> List[Any]:
    seen: List[Any] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def norm(s: Any) -> str:
    text = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def truthy(x: Any) -> bool:
    """Veracidad de JavaScript: 0, '', None, NaN y False son falsos; [] y {} son verdaderos."""
    if x is None or x is False:
        return False
    if isinstance(x, (int, float)):
        return x != 0 and not (isinstance(x, float) and math.isnan(x))
    if isinstance(x, str):
        return x != ""
    return True


def jsum(items: Iterable[Any], start: float = 0) -> Any:
    """Suma de izquierda a derecha como en JavaScript (sum() de Python 3.12+ compensa los decimales y cambia el redondeo)."""
    total = start
    for item in items:
        total = total + item
    return total
