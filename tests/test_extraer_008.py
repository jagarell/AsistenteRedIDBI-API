from app.asistente import extraer

TXT = ("Redacta una minuta nueva. El local se llama Sanguchería Don Pepe; la razón social es Inversiones Don Pepe S.A.C. con RUC 20512345678. "
       "El encargado es Luis Ramos, celular 987654321. Tiene 200 Mbps. El router está en la caja. El switch está conectado por cable al router. "
       "La impresora de cocina está conectada por cable al switch. La impresora de bebidas está conectada por cable al switch. "
       "La PC de caja está conectada por cable al router. El repetidor del salón 2 está conectado por WiFi al router. "
       "Se recomienda reservar la IP de las impresoras con el proveedor. El cliente debe enviar la carta.")


def test_datos_del_cliente():
    d = extraer.datos(TXT)
    assert d["ruc"] == "20512345678" and d["razon"].startswith("Inversiones Don Pepe") and d["local"].startswith("Sanguchería Don Pepe")
    assert d["celular"] == "987654321" and d["rubro"] == "Restaurante" and d["internet"] == "200 Mbps"


def test_conexiones_sin_duplicados():
    c = extraer.conexiones(TXT)
    pares = [(x["desde"], x["hacia"], x["medio"]) for x in c]
    assert ("IMP. Cocina", "Switch", "Cable") in pares and ("Repetidor · Salón 2", "Router", "WiFi") in pares
    assert ("Switch", "Router", "Cable") in pares and ("PC Caja", "Router", "Cable") in pares
    assert len(pares) == len(set((a, b) for a, b, _ in pares)) == 5


def test_ultimo_medio_gana():
    c = extraer.conexiones("La impresora de cocina estaba por WiFi y se dejó por cable al switch.")
    assert c == [{"desde": "IMP. Cocina", "hacia": "Switch", "medio": "Cable"}]


def test_borrador_pide_conexiones_y_lista_faltantes(monkeypatch):
    monkeypatch.setenv("ASISTENTE_SIN_IA", "1")
    b = extraer.borrador("Redacta una minuta nueva. El local se llama Chifa Sol.", ["Frontis del local"])
    assert b["pideConexiones"] and "Frontis del local" not in b["faltan"] and "Speedtest" in b["faltan"]
    b = extraer.borrador(TXT)
    assert b["recomendaciones"] and b["pasos"][0]["p"] == "Cliente" and not b["pideConexiones"]
