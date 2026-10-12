# Oráculo del simulador

El simulador (`docs/simulador/simulador.html` del repo Android) es la especificación del chat técnico.
Estos scripts lo cargan en Node con un DOM de mentira y generan los casos "golden" que usa
`tests/test_sim_golden.py` para comprobar que el port a Python (`app/chat/sim/`) calcula lo mismo.

```bash
export SIM_HTML=/ruta/a/docs/simulador/simulador.html
cd tools/sim_oracle
node gen.js 200            # escenarios aleatorios con semilla -> random.json
node export.js             # 5 casos del simulador + 35 aleatorios -> sim_golden.json
cp sim_golden.json ../../tests/golden/
node catalog.js            # catálogos -> catalog.json (copiar a app/chat/sim/catalog.json)
```
