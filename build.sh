#!/usr/bin/env bash
# Genera sesiones.html a partir de los logs en ~/.claude/projects/
#
#   ./build.sh            genera sesiones.html
#   ./build.sh --open     genera y abre en el navegador
#
# El HTML que sale es autocontenido: los datos y las transcripciones van
# embebidos adentro, no necesita red ni servidor. Se abre con doble clic.

set -euo pipefail

cd "$(dirname "$0")"

# El CLI es la única implementación del parseo; el HTML consume su --json.
./claude-sesiones --json > data.json

python3 - <<'PY'
import json

template = open("template.html").read()
raw = open("data.json").read()

# El payload vive dentro de un <script type="application/json">, que el parser
# de HTML corta en el primer "</script". Escapamos "</" como "<\/" — es un
# escape válido de JSON, así que JSON.parse lo devuelve intacto.
payload = raw.replace("</", "<\\/")

# Ojo: no se puede verificar buscando __DATA__ en la salida. Estas mismas
# sesiones incluyen conversaciones sobre este script, así que el payload
# contiene el marcador como texto. Validamos el template antes de sustituir.
if template.count("__DATA__") != 1:
    raise SystemExit("error: el template debe tener exactamente un __DATA__")

html = template.replace("__DATA__", payload)

open("sesiones.html", "w").write(html)

s = json.loads(raw)
print(f"{len(s)} sesiones · "
      f"{len({x['p'] for x in s})} proyectos · "
      f"{sum(x['u'] for x in s)} mensajes · "
      f"{sum(len(x['c']) for x in s)} bloques de transcripción → sesiones.html")
PY

if [[ "${1:-}" == "--open" ]]; then
  xdg-open sesiones.html >/dev/null 2>&1 &
fi
