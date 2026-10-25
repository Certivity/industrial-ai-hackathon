"""Stage 0 (only when the case has an image): read a drawing, an exploded view or a labelled photo, into facts about the product.

Two model calls, both Sonnet with images, both generic (nothing here knows what product is drawn):

  1. read: every piece of text of the drawing with a normalised box and a role (title, component label, value note, legend entry, balloon number,
     dimension). A big drawing is sent as the whole picture, downscaled to what the API reads (2576 px on the long edge, 3.75 MP), and as tiles cut from
     the original pixels (a grid of overlapping crops, about 1500 px each, so that small print stays legible).
  2. map: the whole picture and the text of step 1: which component does each text belong to (leader line, arrow, numbered balloon plus legend
     table, or plain proximity), what it says about the component (quantity, value, unit, verbatim), which drawn parts carry no text.

The result is `vision.json` of the run; `profile.py` merges it into the profile and `components.py` uses it for the component map. The request is
deterministic (same image bytes, same prompt), so the replay cache of `llm.py` answers a repeated run for free.
"""

from __future__ import annotations

import base64
import io
import math
from pathlib import Path

from .llm import LLM

try:  # PIL is optional: without it the file goes to the API as it is
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

MAX_EDGE = 2576  # long edge the API reads at full resolution for Sonnet 5.x
MAX_PIXELS = 3_750_000
TILE_EDGE = 1500  # a tile is about this many pixels on its long side
OVERLAP = 0.12  # fraction of a tile shared with its neighbour
MAX_BYTES = 4_500_000  # the API refuses an image above 5 MB

MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}

_STR = {"type": "string"}


def _obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_BOX = _obj({"x0": {"type": "number"}, "y0": {"type": "number"}, "x1": {"type": "number"}, "y1": {"type": "number"}})
ROLES = ["title", "component_label", "value_note", "legend_entry", "balloon_number", "dimension", "other"]
KINDS = ["exploded_view", "assembly_drawing", "numbered_balloons_with_legend", "labelled_photo", "schematic", "table_or_text_only", "other"]

READ_SCHEMA = _obj({
    "drawing_kind": {"type": "string", "enum": KINDS},
    "title": {"type": "string", "description": "The drawing's own title, or empty."},
    "text_blocks": {"type": "array", "items": _obj({
        "id": {"type": "string", "description": "T1, T2 ..."},
        "text": {"type": "string", "description": "Verbatim, one callout or label per block; keep numbers, units and symbols exactly."},
        "role": {"type": "string", "enum": ROLES},
        "box": _BOX,
    })},
})

MAP_SCHEMA = _obj({
    "components": {"type": "array", "items": _obj({
        "key": {"type": "string", "description": "C1, C2 ..."},
        "name": {"type": "string", "description": "The component as a short noun phrase: what the callout points at."},
        "callout_text": {"type": "string", "description": "The text tied to this component, verbatim (join the lines of one callout)."},
        "text_ids": {"type": "array", "items": _STR, "description": "ids of the text blocks that belong to the component"},
        "values": {"type": "array", "items": _obj({
            "quantity": {"type": "string", "description": "What is measured or required, e.g. luminous intensity, visibility angle, test."},
            "value": {"type": "string", "description": "The value or range as written, e.g. 4 to 17, <= 45, red."},
            "unit": {"type": "string", "description": "Unit or condition as written (cd, deg, ...), or empty."},
            "raw": {"type": "string", "description": "The words of the callout this entry comes from."},
        })},
        "function_hint": {"type": "string", "description": "The function or requirement the callout attaches to the component, in a few words."},
        "linked_by": {"type": "string", "enum": ["leader_line", "arrow", "balloon_legend", "proximity", "text_only"]},
        "region": _BOX,
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    })},
    "unlabelled_parts": {"type": "array", "items": _obj({"description": _STR, "region": _BOX})},
    "legend": {"type": "array", "items": _obj({"marker": _STR, "text": _STR})},
    "notes": {"type": "array", "items": _STR, "description": "Anything else the drawing states about the product as a whole (title block, general notes)."},
})

READ_SYSTEM = """You read engineering drawings. Your job in this step is transcription only: list every piece of text on the drawing, exactly as printed, \
with where it sits and what role it plays. Do not interpret and do not merge unrelated texts.

The picture comes first as a whole, then as tiles cut from the original pixels (small print is easier to read in the tiles). The tiles overlap: list a \
text once. Boxes are normalised to the whole picture, x to the right and y downwards, both from 0 to 1.

Roles: title (drawing title, title block entries), component_label (the name of a part), value_note (a requirement, a value, a range, a test or a \
condition), legend_entry (a row of a legend or bill-of-materials table, with its marker), balloon_number (a number or letter in a circle or box that \
points at a part), dimension (a measure on the drawing), other. A callout that holds a name and a value on one line is one block; use the role that \
carries the most information (value_note if it states a requirement). Keep symbols as printed (degrees, plus-minus, superscripts, cd, lm, mm)."""

MAP_SYSTEM = """You understand which part of a product each text of a drawing is about. You get the whole drawing and the transcription of its text (ids, \
text, role, box).

Follow how the drawing itself links text and part: a leader line or arrow from the text to a drawn part; a numbered balloon on a part plus the legend or \
bill-of-materials table that explains the number; or, when there is nothing else, proximity. Look at the drawing, not only at the boxes: follow each line \
to the part it ends on. A callout of the form "<part> - <statement>" names the part before the dash and states a requirement or a property of the \
product after it; the part named is the component, but check where the line ends.

Return:
- components: one entry per component that has text tied to it. name is the part (short noun phrase); callout_text is the text of the callout, \
verbatim; values are the measurable statements in it (quantity, value as written, unit as written); function_hint says in a few words which \
function or requirement the callout attaches to that part; linked_by says how you linked them; region is the box of the drawn part; confidence is low \
when you are guessing which part a line ends on.
- unlabelled_parts: drawn parts that have no text tied to them.
- legend: the rows of a legend or BOM table, if the drawing has one.
- notes: general statements of the drawing (title block, notes, scale) that describe the product as a whole.
Do not invent text or values. A value that is not printed does not belong in `values`."""


# --------------------------------------------------------------------------------------------------------------------------------------
def _encode(image) -> tuple[str, str]:
    """PNG when it fits the API's size limit, else JPEG (deterministic: the same pixels give the same bytes)."""
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=False)
    if buffer.tell() <= MAX_BYTES:
        return "image/png", base64.b64encode(buffer.getvalue()).decode("ascii")
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=92)
    return "image/jpeg", base64.b64encode(buffer.getvalue()).decode("ascii")


def _block(media: str, data: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


def _fit(image, max_edge: int = MAX_EDGE, max_pixels: int = MAX_PIXELS):
    w, h = image.size
    scale = min(1.0, max_edge / max(w, h), math.sqrt(max_pixels / (w * h)))
    if scale < 1.0:
        image = image.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    return image


def prepare(path: Path) -> dict:
    """The image as content blocks: {'whole': block, 'tiles': [(block, (x0, y0, x1, y1) normalised)], 'info': {...}}.
    Without PIL (or for a format PIL cannot open) the file is sent as it is and there are no tiles."""
    raw = Path(path).read_bytes()
    if Image is None:
        return {"whole": _block(MEDIA.get(Path(path).suffix.lower(), "image/png"), base64.b64encode(raw).decode("ascii")), "tiles": [],
                "info": {"pil": False, "bytes": len(raw)}}
    image = Image.open(io.BytesIO(raw))
    image.load()
    if image.mode not in ("RGB", "L"):
        background = Image.new("RGB", image.size, "white")  # transparent drawings are black lines on nothing
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[3])
        image = background
    width, height = image.size
    whole = _fit(image)
    info = {"pil": True, "size": [width, height], "sent_whole": list(whole.size), "bytes": len(raw)}
    tiles = []
    cols, rows = min(3, math.ceil(width / TILE_EDGE)), min(3, math.ceil(height / TILE_EDGE))
    if cols * rows > 1:
        tw, th = width / (cols - (cols - 1) * OVERLAP), height / (rows - (rows - 1) * OVERLAP)  # tile size so that the grid covers the picture
        for r in range(rows):
            for c in range(cols):
                x0 = 0 if cols == 1 else c * (width - tw) / (cols - 1)
                y0 = 0 if rows == 1 else r * (height - th) / (rows - 1)
                crop = image.crop((round(x0), round(y0), round(x0 + tw), round(y0 + th)))
                box = (round(x0 / width, 3), round(y0 / height, 3), round((x0 + tw) / width, 3), round((y0 + th) / height, 3))
                tiles.append((_block(*_encode(_fit(crop))), box))
        info["tiles"] = [list(box) for _, box in tiles]
    return {"whole": _block(*_encode(whole)), "tiles": tiles, "info": info}


def _read_content(prepared: dict) -> list:
    content: list = [{"type": "text", "text": "The whole drawing:"}, prepared["whole"]]
    for index, (block, (x0, y0, x1, y1)) in enumerate(prepared["tiles"], 1):
        content += [{"type": "text", "text": f"Tile {index} of {len(prepared['tiles'])}, cut from the original pixels; it covers x {x0:.2f} to {x1:.2f} "
                                             f"and y {y0:.2f} to {y1:.2f} of the whole drawing:"}, block]
    content.append({"type": "text", "text": "Transcribe all the text of the drawing."})
    return content


def transcription_text(read: dict) -> str:
    rows = []
    for b in read["text_blocks"]:
        x = b["box"]
        rows.append(f"{b['id']} [{b['role']}] ({x['x0']:.2f},{x['y0']:.2f})-({x['x1']:.2f},{x['y1']:.2f}) {b['text']}")
    return "\n".join(rows)


def read_drawing(llm: LLM, image_path: Path, settings=None, run_dir: Path | None = None, log=print) -> dict:
    """Read and map a drawing; returns the facts (also the shape of vision.json)."""
    prepared = prepare(image_path)
    info = prepared["info"]
    log(f"[vision] {Path(image_path).name}: {info.get('size', '?')} -> whole {info.get('sent_whole', 'as is')}, {len(prepared['tiles'])} tiles")
    read = llm.complete_json(stage="vision", label="read", system=READ_SYSTEM, user=_read_content(prepared), schema=READ_SCHEMA, max_tokens=24_000)
    mapping_user = [{"type": "text", "text": "The drawing:"}, prepared["whole"],
                    {"type": "text", "text": f"Drawing kind: {read['drawing_kind']}. Title: {read['title'] or '(none)'}\n\nTranscription "
                                             f"(id [role] box text):\n{transcription_text(read)}\n\nMap the text to the components."}]
    mapped = llm.complete_json(stage="vision", label="map", system=MAP_SYSTEM, user=mapping_user, schema=MAP_SCHEMA, max_tokens=24_000)
    facts = {"image": Path(image_path).name, "info": info, "drawing_kind": read["drawing_kind"], "title": read["title"],
             "text_blocks": read["text_blocks"], **mapped}
    log(f"[vision] {len(read['text_blocks'])} text blocks, {len(facts['components'])} components, {len(facts['unlabelled_parts'])} unlabelled parts")
    return facts


# --------------------------------------------------------------------------------------------------------------------------------------
def facts_for_prompt(facts: dict) -> str:
    """The facts as the profile step reads them: compact lines, no boxes."""
    lines = [f"Drawing: {facts['drawing_kind']}" + (f", titled \"{facts['title']}\"" if facts["title"] else "")]
    for c in facts["components"]:
        values = "; ".join(f"{v['quantity']}: {v['value']}{(' ' + v['unit']) if v['unit'] else ''}" for v in c["values"])
        lines.append(f"- {c['name']} | callout: \"{c['callout_text']}\"" + (f" | values: {values}" if values else "")
                     + (f" | function: {c['function_hint']}" if c["function_hint"] else "") + f" | linked by {c['linked_by']}, {c['confidence']} confidence")
    if facts["unlabelled_parts"]:
        lines.append("Parts drawn without text: " + "; ".join(p["description"] for p in facts["unlabelled_parts"]))
    if facts["legend"]:
        lines.append("Legend: " + "; ".join(f"{r['marker']} {r['text']}" for r in facts["legend"]))
    lines += [f"Note: {n}" for n in facts["notes"]]
    return "\n".join(lines)


def callouts_text(facts: dict) -> str:
    """The 'Annotated requirements from the drawing' block of profile.md: the callout values, verbatim, by component."""
    rows, seen = [], set()
    for c in facts["components"]:
        if not c["callout_text"].strip():
            continue
        row = f"{c['name']}: {c['callout_text'].strip()}" + (f" [{c['function_hint']}]" if c["function_hint"] else "")
        if c["confidence"] == "low":
            row += " (link uncertain)"
        if row not in seen:
            seen.add(row)
            rows.append(row)
    return "; ".join(rows)
