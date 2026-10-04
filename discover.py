import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# UTCUTIE PROFESSIONAL VALIDATION ENGINE
# ============================================================

MIN_DURATION = 15
MAX_DURATION = 180

MAX_FILE_SIZE_MB = 48
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

MAX_SELECTED = 20

CANDIDATE_FILE = Path("candidate_urls.txt")
VALIDATED_FILE = Path("validated_candidates.json")
SELECTED_FILE = Path("selected_candidates.json")


# ============================================================
# CONTROLLED TEST SEEDS
# ============================================================
# These are ONLY engineering test candidates.
# They are not the final daily discovery mechanism.

SEED_URLS = [
    "https://x.com/garibansipsi/status/2054157848670605453"
]


# ============================================================
# PET / ANIMAL VOCABULARY
# ============================================================

PET_KEYWORDS = {
    # English
    "dog",
    "dogs",
    "puppy",
    "puppies",
    "doggo",
    "doggy",
    "pup",
    "cat",
    "cats",
    "kitten",
    "kittens",
    "kitty",
    "kitties",
    "pet",
    "pets",
    "animal",
    "animals",
    "bird",
    "birds",
    "parrot",
    "parrots",
    "rabbit",
    "rabbits",
    "bunny",
    "bunnies",
    "hamster",
    "hamsters",
    "guinea",
    "pig",
    "horse",
    "horses",
    "pony",
    "ponies",
    "duck",
    "ducks",
    "goose",
    "geese",
    "chicken",
    "chickens",
    "goat",
    "goats",
    "sheep",
    "cow",
    "cows",
    "calf",
    "calves",
    "monkey",
    "monkeys",
    "panda",
    "pandas",
    "otter",
    "otters",
    "fox",
    "foxes",
    "bear",
    "bears",
    "penguin",
    "penguins",
    "seal",
    "seals",
    "dolphin",
    "dolphins",
    "turtle",
    "turtles",
    "snake",
    "snakes",
    "lizard",
    "lizards",

    # Turkish
    "kedi",
    "kediler",
    "kediyi",
    "kedileri",
    "kediye",
    "köpek",
    "köpekler",
    "köpeği",
    "köpekleri",
    "yavru",
    "hayvan",
    "hayvanlar",
    "kuş",
    "kuşlar",
    "tavşan",
    "tavşanlar",
    "at",
    "atlar",
    "ördek",
    "ördekler",
    "maymun",
    "panda",

    # Persian
    "گربه",
    "گربه‌ها",
    "گربهها",
    "بچه‌گربه",
    "بچه گربه",
    "سگ",
    "سگ‌ها",
    "سگها",
    "توله",
    "توله‌سگ",
    "حیوان",
    "حیوانات",
    "پرنده",
    "پرندگان",
    "طوطی",
    "خرگوش",
    "همستر",
    "اسب",
    "اردک",
    "میمون",
    "پاندا",

    # Spanish / Portuguese common terms
    "gato",
    "gatos",
    "gatito",
    "gatitos",
    "perro",
    "perros",
    "cachorro",
    "cachorros",
    "animal",
    "animales",
    "mascota",
    "mascotas",

    # French
    "chat",
    "chats",
    "chaton",
    "chatons",
    "chien",
    "chiens",
    "chiot",
    "chiots",
    "animal",
    "animaux",
    "animaux",
    "lapin",
    "lapins",
    "oiseau",
    "oiseaux",

    # German
    "katze",
    "katzen",
    "kätzchen",
    "hund",
    "hunde",
    "welpe",
    "welpen",
    "tier",
    "tiere",
    "kaninchen",
    "vogel",
    "vögel",
}


# Stronger terms receive more relevance weight.
STRONG_PET_KEYWORDS = {
    "cat",
    "cats",
    "kitten",
    "kittens",
    "kitty",
    "dog",
    "dogs",
    "puppy",
    "puppies",
    "doggo",
    "kedi",
    "kediler",
    "kedileri",
    "köpek",
    "köpekler",
    "گربه",
    "گربه‌ها",
    "بچه‌گربه",
    "سگ",
    "توله‌سگ",
    "gato",
    "gatito",
    "perro",
    "cachorro",
    "chat",
    "chaton",
    "chien",
    "chiot",
    "katze",
    "kätzchen",
    "hund",
    "welpe",
}


# ============================================================
# CONTENT / NEGATIVE SIGNALS
# ============================================================

LOW_VALUE_KEYWORDS = {
    "politics",
    "political",
    "crypto",
    "bitcoin",
    "forex",
    "casino",
    "gambling",
    "porn",
    "nsfw",
    "adult",
    "onlyfans",
    "giveaway",
    "betting",
    "sportsbook",
}


# ============================================================
# HELPERS
# ============================================================

def normalize_text(value):
    if value is None:
        return ""

    value = str(value).lower()

    # Normalize common Unicode punctuation.
    replacements = {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "\u200c": " ",
        "\u200d": " ",
        "\ufeff": " ",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    # Keep Unicode letters/numbers.
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def keyword_matches(text, keywords):
    """
    Unicode-friendly keyword matching.

    We intentionally use substring matching because some languages
    attach suffixes to the base word, e.g. Turkish:
    kedi -> kedileri
    """

    normalized = normalize_text(text)

    matches = []

    for keyword in keywords:
        keyword_normalized = normalize_text(keyword)

        if keyword_normalized and keyword_normalized in normalized:
            matches.append(keyword)

    return sorted(set(matches))


def safe_number(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def calculate_engagement_score(data):
    views = safe_number(data.get("view_count"))
    likes = safe_number(data.get("like_count"))
    comments = safe_number(data.get("comment_count"))
    reposts = safe_number(data.get("repost_count"))

    score = (
        math.log10(views + 1) * 10
        + math.log10(likes + 1) * 8
        + math.log10(comments + 1) * 5
        + math.log10(reposts + 1) * 6
    )

    return
