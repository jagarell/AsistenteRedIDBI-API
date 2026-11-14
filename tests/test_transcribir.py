"""Dictado por voz: transcripción del audio en el servidor (sin llamar a OpenAI de verdad)."""
import base64
import sys
import types

from fastapi.testclient import TestClient

from app.chat.config import settings
from app.main import app

client = TestClient(app)


def _audio(n: int = 4000) -> str:
    return base64.b64encode(b"\x00" * n).decode()


def test_sin_clave_avisa_que_el_dictado_no_esta_disponible(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    r = client.post("/transcribir", json={"audioBase64": _audio()}).json()
    assert r["text"] == "" and "no está disponible" in r["error"]


def test_audio_muy_corto_o_muy_largo(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "k")
    assert "muy corto" in client.post("/transcribir", json={"audioBase64": _audio(100)}).json()["error"]
    from app import transcribir as t
    monkeypatch.setattr(t, "MAX_AUDIO_BYTES", 1000)
    assert "muy largo" in client.post("/transcribir", json={"audioBase64": _audio(4000)}).json()["error"]


def _falso_openai(monkeypatch, comportamiento):
    llamadas = []

    class Trans:
        def create(self, **kw):
            llamadas.append(kw)
            return comportamiento(kw)

    class OpenAI:
        def __init__(self, **kw):
            self.audio = types.SimpleNamespace(transcriptions=Trans())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=OpenAI))
    monkeypatch.setattr(settings, "openai_api_key", "k")
    return llamadas


def test_devuelve_el_texto_en_espanol_con_el_vocabulario_del_oficio(monkeypatch):
    llamadas = _falso_openai(monkeypatch, lambda kw: types.SimpleNamespace(text="  La caja uno tiene AnyDesk  "))
    r = client.post("/transcribir", json={"audioBase64": _audio(), "mime": "audio/mp4"}).json()
    assert r == {"text": "La caja uno tiene AnyDesk", "error": None}
    assert llamadas[0]["language"] == "es" and "AnyDesk" in llamadas[0]["prompt"]
    assert llamadas[0]["file"][0] == "audio.m4a"


def test_si_el_primer_modelo_falla_usa_el_de_respaldo(monkeypatch):
    def comp(kw):
        if kw["model"] != "whisper-1":
            raise RuntimeError("modelo no disponible")
        return types.SimpleNamespace(text="hola")
    llamadas = _falso_openai(monkeypatch, comp)
    assert client.post("/transcribir", json={"audioBase64": _audio()}).json()["text"] == "hola"
    assert [c["model"] for c in llamadas][-1] == "whisper-1"


def test_si_todo_falla_da_un_mensaje_claro(monkeypatch):
    def comp(kw):
        raise RuntimeError("sin red")
    _falso_openai(monkeypatch, comp)
    r = client.post("/transcribir", json={"audioBase64": _audio()}).json()
    assert r["text"] == "" and "No se pudo transcribir" in r["error"]


def test_audio_sin_voz_pide_repetir(monkeypatch):
    _falso_openai(monkeypatch, lambda kw: types.SimpleNamespace(text=" "))
    assert "No se entendió" in client.post("/transcribir", json={"audioBase64": _audio()}).json()["error"]
