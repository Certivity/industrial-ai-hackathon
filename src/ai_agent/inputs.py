"""What a case folder holds: a text spec, an image (exploded view / drawing), or both.

    inputs = find_inputs("cases/dev-rear-lamp")              # spec.md + exploded_view.png
    inputs = find_inputs(dir, use_image=False)               # text only, whatever else is there
    inputs = find_inputs(dir, image="drawings/rear.png")     # an explicit image

Text: `spec.md`, else `technical_spec.md`, else the one *.md that is not a README. Image: `exploded_view.png`, else the only *.png / *.jpg / *.jpeg /
*.webp of the folder (several: the first by name, the others are reported). Nothing else is read; in particular not expected.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

TEXT_NAMES = ("spec.md", "technical_spec.md")
IMAGE_NAMES = ("exploded_view.png",)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


class NoInput(RuntimeError):
    pass


@dataclass
class CaseInputs:
    text_path: Path | None = None
    image_path: Path | None = None
    other_images: list[Path] = field(default_factory=list)

    def describe(self) -> str:
        parts = [f"text {self.text_path.name}" if self.text_path else "no text", f"image {self.image_path.name}" if self.image_path else "no image"]
        return ", ".join(parts)

    def read_text(self) -> str | None:
        return self.text_path.read_text(encoding="utf-8") if self.text_path else None


def find_text(case_dir: Path) -> Path | None:
    for name in TEXT_NAMES:
        if (case_dir / name).is_file():
            return case_dir / name
    others = sorted(p for p in case_dir.glob("*.md") if p.is_file() and not p.name.lower().startswith("readme"))
    return others[0] if len(others) == 1 else None


def find_image(case_dir: Path) -> tuple[Path | None, list[Path]]:
    for name in IMAGE_NAMES:
        if (case_dir / name).is_file():
            return case_dir / name, []
    images = sorted(p for p in case_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    return (images[0], images[1:]) if images else (None, [])


def find_inputs(case_dir: str | Path, use_text: bool = True, use_image: bool = True, image: str | Path | None = None) -> CaseInputs:
    """`use_image=False` ignores any image; `image` names one explicitly (a path, or a file name inside the case folder)."""
    case_dir = Path(case_dir)
    if not case_dir.is_dir():
        raise NoInput(f"{case_dir} is not a folder")
    inputs = CaseInputs()
    if use_text:
        inputs.text_path = find_text(case_dir)
    if image:
        path = Path(image)
        path = path if path.is_file() else case_dir / path
        if not path.is_file():
            raise NoInput(f"image {image} not found")
        inputs.image_path = path
    elif use_image:
        inputs.image_path, inputs.other_images = find_image(case_dir)
    if inputs.text_path is None and inputs.image_path is None:
        raise NoInput(f"{case_dir} has no input: give a text spec (spec.md or technical_spec.md) and/or an image "
                      f"({', '.join('*' + s for s in IMAGE_SUFFIXES)}); check the --no-image flag")
    return inputs
