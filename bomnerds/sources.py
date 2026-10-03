import hashlib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "sources"

SCRIPTURES_JSON = "https://raw.githubusercontent.com/bcbooks/scriptures-json/3bda76e40add4582165340ea6b1198dc6ad26ae1/"

# The text is frozen once tagging starts, so every download is pinned by hash.
# eBible republishes in place, so a changed hash means a new edition, not an update.
FILES = {
    "book-of-mormon.json": (SCRIPTURES_JSON + "book-of-mormon.json", "7987cacbbbf3d53a22da8d5b82023001b97467c642f4baa0d962365a536f5c60"),
    "doctrine-and-covenants.json": (SCRIPTURES_JSON + "doctrine-and-covenants.json", "eb28b47e915f2843e14cffc6b850da7566104b17dc6e0d73daaf2577647cf62d"),
    "pearl-of-great-price.json": (SCRIPTURES_JSON + "pearl-of-great-price.json", "b62759b46d7e7daee20f4cb494dcb101ef32a8a62ab4021edbfd6a805b81e909"),
    "eng-kjv2006_usfm.zip": ("https://ebible.org/Scriptures/eng-kjv2006_usfm.zip", "2e698d1c6e865341c4193c719079f9767c8db09a488fffe18c24e51978a4f9c3"),
}


def fetch(name: str) -> Path:
    url, expected = FILES[name]
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(exist_ok=True)
        with urllib.request.urlopen(url) as response:
            data = response.read()
        path.write_bytes(data)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"{name} does not match its pinned hash.\n  expected {expected}\n  got      {actual}\nDelete {path} to download it again.")
    return path
