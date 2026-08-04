from __future__ import annotations

import html
import json
import math
import re
import unicodedata
from typing import Any


_TOKEN_PATTERN = re.compile(r"[A-Za-z]+")
_ENGLISH_WORDS = {
    "a", "about", "accessory", "adjustable", "after", "all", "and",
    "anti", "automatic", "battery", "black", "blue", "box", "brand",
    "cable", "car", "case", "charger", "charging", "changed", "compact",
    "configure", "configured",
    "compatible", "content", "converter", "cord", "cover", "current", "design",
    "description", "device", "digital", "durable", "easy", "electric",
    "existing", "fast",
    "for", "from", "grade", "green", "holder", "home", "in", "included",
    "kit", "light", "material", "metal", "mini", "model", "new", "of",
    "one", "original", "pack", "phone", "portable", "power", "premium",
    "product", "protective", "red", "replacement", "set", "size", "smart",
    "snapshot", "standard", "strong", "support", "template", "the", "title",
    "to", "tool", "type", "upgraded", "usb", "value", "version", "voltage",
    "wall", "warranty", "waterproof", "white", "with", "wireless", "year",
}
_ENGLISH_WORDS.update(
    """
    adapter adhesive air aluminum ankle apparel arm audio bag base bass
    action anime
    bathroom belt bicycle bluetooth board bottle bracelet breathable brush
    button camera camping cap ceramic clip clipper clock clothing coffee cosplay costume
    cancelling collar collectible controller cooking cotton cordless cushion cutter daily demon desk
    decoration desktop display double dress drill earphone elastic ergonomic fabric fan fashion
    filter fitness floral foldable food furniture gaming garden glass gloves
    earbuds figure figurine gift halloween handmade handle handbag hat headphone heavy hood hooded indoor insulated jacket
    keyboard kitchen lamp laptop leather lightweight lock magnetic men mesh
    man marvel microphone model mount mouse necklace noise non slip office outdoor pants plastic
    party pocket rack rain rechargeable remote resistant ring rubber running
    safety screen shirt shoes silicone slayer sleeve solar speaker speed spider sports statue stereo
    stainless stand steel storage strap straw summer table travel trousers resin
    toy universal vacuum watch water weather women wood wooden
    """.split()
)
_NON_ENGLISH_MARKERS = {
    # French
    "au", "aux", "avec", "ce", "ces", "dans", "de", "des", "du", "elle",
    "en", "est", "et", "la", "le", "les", "mais", "ou", "pour", "sans",
    "sur", "telephone", "une", "voiture",
    # Spanish
    "coche", "con", "del", "el", "en", "es", "la", "las", "los", "para",
    "pero", "por", "sin", "soporte", "telefono", "una", "y",
    # Common Latin placeholder text
    "amet", "dolor", "ipsum", "lorem",
}
_VOWELS = set("aeiouy")
_ALLOWED_VOWELLESS_CODES = {
    "abs", "dc", "gps", "hd", "led", "pvc", "sku", "tv", "usb", "xl",
}


def _is_known_english_token(token: str) -> bool:
    if token in _ENGLISH_WORDS:
        return True
    candidates: list[str] = []
    if len(token) > 4 and token.endswith("ies"):
        candidates.append(f"{token[:-3]}y")
    if len(token) > 3 and token.endswith("s"):
        candidates.append(token[:-1])
    if len(token) > 4 and token.endswith("es"):
        candidates.append(token[:-2])
    if len(token) > 4 and token.endswith("ed"):
        candidates.extend((token[:-2], token[:-1]))
    if len(token) > 5 and token.endswith("ing"):
        candidates.extend((token[:-3], f"{token[:-3]}e"))
    if len(token) > 4 and token.endswith("ly"):
        candidates.append(token[:-2])
    if len(token) > 4 and token.endswith("er"):
        candidates.extend((token[:-2], f"{token[:-1]}e"))
    return any(candidate in _ENGLISH_WORDS for candidate in candidates)


def _natural_language_text(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith(("{", "[")):
        try:
            decoded = json.loads(stripped)
        except (TypeError, ValueError):
            decoded = None
        if decoded is not None:
            leaves: list[str] = []

            def collect(item: Any) -> None:
                if isinstance(item, str) and item.strip():
                    leaves.append(item.strip())
                elif isinstance(item, list):
                    for child in item:
                        collect(child)
                elif isinstance(item, dict):
                    for child in item.values():
                        collect(child)

            collect(decoded)
            if leaves:
                stripped = " ".join(leaves)
    if "<" in stripped and ">" in stripped:
        stripped = re.sub(r"<[^>]+>", " ", stripped)
    return html.unescape(stripped)


def detect_english(value: Any) -> str:
    """Conservative, dependency-free English gate for save-bound text.

    This deliberately returns UNKNOWN for ambiguous Latin-script text. E2 has
    no approved language-model dependency, so a false negative is safer than
    allowing French, Spanish, placeholder Latin, or pronounceability-free
    text to reach a frozen save plan.
    """

    if not isinstance(value, str):
        return "UNKNOWN"
    normalized = unicodedata.normalize(
        "NFC",
        _natural_language_text(value),
    ).strip()
    if not normalized:
        return "UNKNOWN"
    for character in normalized:
        if character.isalpha() and character not in (
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        ):
            return "UNKNOWN"
        if (
            not character.isalpha()
            and not character.isdigit()
            and not character.isspace()
            and not unicodedata.category(character).startswith(("P", "S"))
        ):
            return "UNKNOWN"

    tokens = [token.casefold() for token in _TOKEN_PATTERN.findall(normalized)]
    if len(tokens) < 2 or any(token in _NON_ENGLISH_MARKERS for token in tokens):
        return "UNKNOWN"
    for token in tokens:
        if token in _ALLOWED_VOWELLESS_CODES:
            continue
        if not (_VOWELS & set(token)):
            return "UNKNOWN"
        if re.search(r"[^aeiouy]{5,}", token) is not None:
            return "UNKNOWN"

    known_count = sum(
        token in _ALLOWED_VOWELLESS_CODES
        or _is_known_english_token(token)
        for token in tokens
    )
    minimum_known = max(2, math.ceil(len(tokens) * 0.5))
    allowed_unknown = 1 if len(tokens) <= 5 else math.floor(len(tokens) * 0.25)
    if (
        known_count < minimum_known
        or len(tokens) - known_count > allowed_unknown
    ):
        return "UNKNOWN"
    return "en"
