"""Lo que ChatGPT devuelve como relleno no entra al borrador de la minuta (ver extraer._valor_ia_valido)."""
from app.asistente.extraer import _valor_ia_valido


def test_la_razon_social_no_puede_ser_el_ruc():
    assert not _valor_ia_valido("razon", "RUC 20512345678", "20512345678")
    assert not _valor_ia_valido("razon", "20512345678", None)
    assert not _valor_ia_valido("razon", "ruc: 20512345678", None)
    assert _valor_ia_valido("razon", "Cevichería Mar Azul SAC", "20512345678")


def test_se_descartan_vacios_y_no_indica():
    for v in (None, "", "  ", "null", "No indica", "N/A", "—"):
        assert not _valor_ia_valido("encargado", v)
    assert _valor_ia_valido("encargado", "Rosa Díaz")
