import hashlib
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "sources"

SCRIPTURES_JSON = "https://raw.githubusercontent.com/bcbooks/scriptures-json/3bda76e40add4582165340ea6b1198dc6ad26ae1/"
MACULA_HEBREW = "47db250bd55d0d8577f2a94fba114ef16c35b23c"
MACULA_GREEK = "8423afe47b9e8f24b7772e808af45c7159a6fe7e"
STEPBIBLE = "https://raw.githubusercontent.com/STEPBible/STEPBible-Data/b99716b0cddb648ddb95cc786a197180f2f97d48/"

# The text is frozen once tagging starts, so every download is pinned by hash.
# eBible and OpenBible republish in place, so a changed hash means new data, not an update.
FILES = {
    "book-of-mormon.json": (SCRIPTURES_JSON + "book-of-mormon.json", "7987cacbbbf3d53a22da8d5b82023001b97467c642f4baa0d962365a536f5c60"),
    "doctrine-and-covenants.json": (SCRIPTURES_JSON + "doctrine-and-covenants.json", "eb28b47e915f2843e14cffc6b850da7566104b17dc6e0d73daaf2577647cf62d"),
    "pearl-of-great-price.json": (SCRIPTURES_JSON + "pearl-of-great-price.json", "b62759b46d7e7daee20f4cb494dcb101ef32a8a62ab4021edbfd6a805b81e909"),
    "eng-kjv2006_usfm.zip": ("https://ebible.org/Scriptures/eng-kjv2006_usfm.zip", "2e698d1c6e865341c4193c719079f9767c8db09a488fffe18c24e51978a4f9c3"),
    "macula-hebrew.tsv": (f"https://media.githubusercontent.com/media/Clear-Bible/macula-hebrew/{MACULA_HEBREW}/WLC/tsv/macula-hebrew.tsv", "965cb0599beed2fe31283b615bcc369178141c0e718a66d97518d94309cfc124"),
    "macula-greek-SBLGNT.tsv": (f"https://raw.githubusercontent.com/Clear-Bible/macula-greek/{MACULA_GREEK}/SBLGNT/tsv/macula-greek-SBLGNT.tsv", "7f71504fdee8659bdd9f85342e4103d645864c2851b8205915bb298f0c004cc5"),
    "tipnr.txt": (STEPBIBLE + "Proper%20Nouns/TIPNR%20-%20Translators%20Individualised%20Proper%20Names%20with%20all%20References%20-%20STEPBible.org%20CC%20BY.txt", "63a129dac8c341772bdc5b6604b97542ad36a8821d61334d824f8efc2cd88fa8"),
    "tvtms.txt": (STEPBIBLE + "Versification/TVTMS%20-%20Translators%20Versification%20Traditions%20with%20Methodology%20for%20Standardisation%20for%20Eng+Heb+Lat+Grk+Others%20-%20STEPBible.org%20CC%20BY.txt", "63058e0f20201af4bdaa7d830da5be8f493455d947c5f147d84840b33db9ddf8"),
    "openbible-ancient.jsonl": ("https://raw.githubusercontent.com/openbibleinfo/Bible-Geocoding-Data/7eb18a5ee62f27b9b93bd6689ea272d76dd23b8f/data/ancient.jsonl", "b8187aa4737e8517ccc090f765d2be11da4c548cd2a59d3cdcb62e952cb8c0f2"),
    "cross-references.zip": ("https://a.openbible.info/data/cross-references.zip", "224f28aae59812b7c0866534133578661fbcbcf04e432e24af8c47044e93782e"),
    "morphadorner-2.0.1.zip": ("https://morphadorner.northwestern.edu/morphadorner/download/morphadorner-2.0.1.zip", "2d5f74c1d6b00252a2e13eb390f1d111cfb475518b53302495ad2819a3be2bb7"),
}

# Syntax trees are hundreds of files, so they are pinned by commit instead of by hash.
CHECKOUTS = {
    "macula-hebrew": ("https://github.com/Clear-Bible/macula-hebrew", MACULA_HEBREW, "WLC/lowfat"),
    "macula-greek": ("https://github.com/Clear-Bible/macula-greek", MACULA_GREEK, "SBLGNT/lowfat"),
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


def checkout(name: str) -> Path:
    url, commit, folder = CHECKOUTS[name]
    path = CACHE / name
    if not path.exists():
        git = ["git", "-C", str(path)]
        path.mkdir(parents=True)
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "remote", "add", "origin", url], check=True)
        subprocess.run([*git, "sparse-checkout", "set", "--no-cone", f"/{folder}/"], check=True)
        subprocess.run([*git, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", commit], check=True)
        subprocess.run([*git, "-c", "advice.detachedHead=false", "checkout", "-q", commit], check=True)
    head = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    if head != commit:
        raise SystemExit(f"{path} is at {head}, not the pinned {commit}. Delete it to check it out again.")
    return path / folder
