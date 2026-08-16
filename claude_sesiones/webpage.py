"""Genera la página HTML autocontenida a partir de las sesiones.

El resultado no necesita red ni servidor: los datos y las transcripciones van
embebidos adentro y se abre con doble clic.
"""

import json
from importlib import resources

MARKER = "__DATA__"

TEMPLATE_NAME = "template.html"


class TemplateError(Exception):
    """El template no tiene la forma que espera el generador."""


def template_text(path=None):
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read()
    return (resources.files(__package__) / TEMPLATE_NAME).read_text(encoding="utf-8")


def encode_payload(records):
    """Serializa los registros para meterlos en un <script type=application/json>.

    El parser de HTML corta ese bloque en el primer "</script", y las
    transcripciones tienen HTML adentro. Escapamos "</" como "<\\/", que es un
    escape válido de JSON: JSON.parse lo devuelve intacto.
    """
    raw = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    return raw.replace("</", "<\\/")


def render(records, template=None):
    """Devuelve el HTML completo con los datos ya embebidos."""
    html = template if template is not None else template_text()
    # No se puede verificar el resultado buscando el marcador: estas mismas
    # sesiones incluyen conversaciones sobre este script, así que el payload lo
    # contiene como texto. Validamos el template antes de sustituir.
    if html.count(MARKER) != 1:
        raise TemplateError(
            f"el template debe tener exactamente un {MARKER} "
            f"(encontrados: {html.count(MARKER)})")
    return html.replace(MARKER, encode_payload(records))


def write(records, out_path, template=None):
    """Escribe la página y devuelve un resumen de lo que quedó adentro."""
    html = render(records, template=template)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return summary(records)


def summary(records):
    return {
        "sesiones": len(records),
        "proyectos": len({r["p"] for r in records}),
        "mensajes": sum(r["u"] for r in records),
        "bloques": sum(len(r["c"]) for r in records),
    }
