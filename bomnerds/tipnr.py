"""Reads STEPBible's TIPNR: every person, place, and other name in the Bible, with family links and the verses each name form appears in."""

import re
from dataclasses import dataclass, field

from .sources import fetch

RECORD = re.compile(r"^([^\s–@$#]+)@(\S+)=([HG]\d+\w*)$")
REFERENCE = re.compile(r"(\w+)\.(\d+)\.(\d+)")


@dataclass
class NameForm:
    kind: str
    strongs: str
    kjv: str | None
    refs: list[tuple[str, int, int]]
    name: str = ""


@dataclass
class Record:
    unique: str
    # TIPNR's unified Strong's number, such as H0175: its identifier for this person or place.
    ustrong: str
    section: str
    type: str
    fields: list[str]
    forms: list[NameForm] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    brief: str = ""
    briefest: str = ""

    @property
    def name(self) -> str:
        return self.unique.split("@")[0].replace("_", " ")

    def links(self, index: int) -> list[str]:
        """Unique names in a family column, such as "Amram@Exo.6.18-1Ch + Jochebed@Exo.6.20-Num"."""
        return re.findall(r"[^\s,+]+@[^\s,+]+", self.fields[index]) if index < len(self.fields) else []


def records() -> list[Record]:
    found = []
    section = ""
    current = None
    for line in fetch("tipnr.txt").read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.split("\t")]
        first = cells[0]
        if first.startswith("$=========="):
            section = first.strip("$= ")
            current = None
            continue
        record = RECORD.match(first)
        if record and section and not section.startswith("EXCLUDED"):
            current = Record(unique=f"{record.group(1)}@{record.group(2)}", ustrong=record.group(3), section=section, type=cells[8] if len(cells) > 8 else "", fields=cells)
            found.append(current)
        elif current is None:
            continue
        elif first.startswith("– Total"):
            current.names = [n.strip().replace("_", " ") for n in cells[1].split(" or ") if n.strip()] if len(cells) > 1 else []
        elif first.startswith("– ") and "same form with alt" not in first:
            form = name_form(cells)
            if form:
                current.forms.append(form)
        elif first.startswith("@Brief="):
            current.brief = first.removeprefix("@Brief=").strip()
        elif first.startswith("@Briefest="):
            current.briefest = first.removeprefix("@Briefest=").strip()
    return found


def name_form(cells: list[str]) -> NameForm | None:
    index = next((i for i, cell in enumerate(cells) if "«" in cell), None)
    if index is None:
        return None
    rendering = cells[index + 1] if index + 1 < len(cells) else ""
    refs = [(code.upper(), int(chapter), int(verse)) for code, chapter, verse in REFERENCE.findall(cells[index + 2] if index + 2 < len(cells) else "")]
    # A form with a name of its own is filed as "Jews|Judah@Gen.29.35-Rev".
    names = cells[1].split("@")[0].split("|")
    own_name = names[0].replace("_", " ") if len(names) > 1 else ""
    return NameForm(kind=cells[0].removeprefix("– "), strongs=cells[index].split("«")[0], kjv=kjv_rendering(rendering), refs=refs, name=own_name)


def kjv_rendering(text: str) -> str | None:
    """The words the KJV uses for a name form: "Lehi =ESV,NIV; in the jaw =KJV" gives "in the jaw"."""
    parts = [part.strip() for part in text.split(";") if part.strip()]
    for part in parts:
        words, _, versions = part.partition("=")
        if "KJV" in versions:
            return words.strip()
    return parts[0].partition("=")[0].strip() if parts else None
