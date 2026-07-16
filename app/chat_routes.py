"""Compatibilidad: el router del chat se movió a app.chat.router.
Se reexporta aquí para no romper imports existentes."""
from app.chat.router import router  # noqa: F401
