"""Builds the self-contained HTML page from the sessions.

The result needs neither network nor server: the data and the transcripts are
embedded inside and it opens with a double click.
"""

import json
from importlib import resources

MARKER = "__DATA__"

TEMPLATE_NAME = "template.html"


class TemplateError(Exception):
    """The template does not have the shape the generator expects."""


def template_text(path=None):
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read()
    return (resources.files(__package__) / TEMPLATE_NAME).read_text(encoding="utf-8")


def build_payload(sessions, memories=None):
    """Structure that travels embedded in the page.

    An object rather than a list because the page shows two different things:
    sessions and project memories.
    """
    return {"s": list(sessions), "m": list(memories or ())}


def encode_payload(payload):
    """Serializes the payload to put it inside a <script type=application/json>.

    The HTML parser cuts that block at the first "</script", and transcripts
    contain HTML. "</" is escaped as "<\\/", which is a valid JSON escape:
    JSON.parse returns it intact.
    """
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return raw.replace("</", "<\\/")


def render(records, memories=None, template=None):
    """Returns the full HTML with the data already embedded."""
    html = template if template is not None else template_text()
    # The result cannot be checked by looking for the marker: these same
    # sessions include conversations about this script, so the payload
    # contains it as text. Validate the template before substituting.
    if html.count(MARKER) != 1:
        raise TemplateError(
            f"the template must contain exactly one {MARKER} "
            f"(found: {html.count(MARKER)})")
    return html.replace(MARKER, encode_payload(build_payload(records, memories)))


def write(records, out_path, memories=None, template=None):
    """Writes the page and returns a summary of what went into it."""
    html = render(records, memories=memories, template=template)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return summary(records, memories)


def summary(records, memories=None):
    return {
        "sessions": len(records),
        "projects": len({r["p"] for r in records}),
        "messages": sum(r["u"] for r in records),
        "blocks": sum(len(r["c"]) for r in records),
        "memories": len(memories or ()),
    }
