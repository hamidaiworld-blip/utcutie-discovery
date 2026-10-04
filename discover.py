import html
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests


# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

MAX_RESULTS_PER_QUERY = 20

SEARCH_QUERIES = [
    'site:x.com "funny dog"',
    'site:x.com "cute dog"',
    'site:x.com "funny cat"',
    'site:x.com "cute cat"',
    'site:x.com "funny puppy"',
    'site:x.com "cute puppy"',
    'site:x.com "funny kitten"',
    'site:x.com "cute kitten"',
    'site:x.com "funny pet"',
    'site:x.com "cute pet"',
    'site:x.com "funny animal"',
    'site:x.com "cute animal"',
    'site:x.com "wholesome animal"',
    'site:x.com "heartwarming animal"',
    'site:x.com "animal friendship"',
]


OUTPUT_FILE = Path("candidate_urls.txt")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)


# ------------------------------------------------------------
# HTTP SESSION
# ------------------------------------------------------------

session = requests.Session()

session.headers.update(
    {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
    }
)


# ------------------------------------------------------------
# X URL REGEX
# ------------------------------------------------------------

X_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?x\.com/"
    r"[A-Za-z0-9_]+/status/\d+",
    re.IGNORECASE
)


# ------------------------------------------------------------
# TEXT CLEANING
# ------------------------------------------------------------

def decode_text(text):
    """
    Repeatedly decode common HTML and URL encodings.
    """

    if not text:
        return ""

    result = text

    for _ in range(3):
        result = html.unescape(result)
        result = unquote(result)

    return result


# ------------------------------------------------------------
# URL NORMALIZATION
# ------------------------------------------------------------

def normalize_x_url(url):
    """
    Convert different representations of an X status URL
    into one canonical URL.
    """

    if not url:
        return None

    value = decode_text(url)

    match = X_URL_PATTERN.search(value)

    if not match:
        return None

    matched = match.group(0)

    parsed = urlparse(matched)

    if not parsed.netloc:
        return None

    path_parts = parsed.path.strip("/").split("/")

    if len(path_parts) < 3:
        return None

    username = path_parts[0]
    status_word = path_parts[1]
    status_id = path_parts[2]

    if status_word.lower() != "status":
        return None

    if not status_id.isdigit():
        return None

    return (
        f"https://x.com/"
        f"{username}/status/{status_id}"
    )


# ------------------------------------------------------------
# EXTRACT FROM HTML
# ------------------------------------------------------------

def extract_x_urls(html_text):
    """
    Extract X status URLs from:

    1. raw HTML
    2. href attributes
    3. encoded/escaped URLs
    4. search-engine redirect URLs
    """

    if not html_text:
        return []

    candidates = []

    def add_candidate(value):
        if not value:
            return

        decoded = decode_text(value)

        # Direct X URL
        direct = normalize_x_url(decoded)

        if direct:
            if direct not in candidates:
                candidates.append(direct)

        # Look inside the decoded string
        matches = X_URL_PATTERN.findall(decoded)

        for match in matches:
            normalized = normalize_x_url(match)

            if normalized and normalized not in candidates:
                candidates.append(normalized)

        # Try query parameters such as:
        # ?url=https%3A%2F%2Fx.com%2F...
        try:
            parsed = urlparse(decoded)

            query = parse_qs(parsed.query)

            for values in query.values():
                for value in values:
                    normalized = normalize_x_url(value)

                    if (
                        normalized
                        and normalized not in candidates
                    ):
                        candidates.append(normalized)

        except Exception:
            pass

    # --------------------------------------------------------
    # Entire HTML
    # --------------------------------------------------------

    add_candidate(html_text)

    # --------------------------------------------------------
    # href attributes
    # --------------------------------------------------------

    href_pattern = re.compile(
        r'''href\s*=\s*["']([^"']+)["']''',
        re.IGNORECASE
    )

    for match in href_pattern.finditer(html_text):
        add_candidate(match.group(1))

    # --------------------------------------------------------
    # Quoted strings
    # --------------------------------------------------------

    quoted_pattern = re.compile(
        r'''["']([^"']{0,2000})["']'''
    )

    for match in quoted_pattern.finditer(html_text):
        value = match.group(1)

        if (
            "x.com" in value.lower()
            or "twitter.com" in value.lower()
            or "status" in value.lower()
        ):
            add_candidate(value)

    return candidates


# ------------------------------------------------------------
# BING SEARCH
# ------------------------------------------------------------

def search_bing(query):
    print("\n" + "=" * 70)
    print("BING SEARCH")
    print("=" * 70)
    print(query)

    url = (
        "https://www.bing.com/search?q="
        + requests.utils.quote(query)
        + "&count="
        + str(MAX_RESULTS_PER_QUERY)
    )

    try:
        response = session.get(
            url,
            timeout=30
        )

    except requests.RequestException as error:
        print(f"Bing request failed: {error}")
        return []

    print(f"HTTP status: {response.status_code}")

    if response.status_code != 200:
        return []

    urls = extract_x_urls(response.text)

    print(
        f"Bing extracted {len(urls)} X URLs"
    )

    return urls


# ------------------------------------------------------------
# GOOGLE SEARCH
# ------------------------------------------------------------

def search_google(query):
    print("\n" + "=" * 70)
    print("GOOGLE SEARCH")
    print("=" * 70)
    print(query)

    url = (
        "https://www.google.com/search?q="
        + requests.utils.quote(query)
        + "&num="
        + str(MAX_RESULTS_PER_QUERY)
    )

    try:
        response = session.get(
            url,
            timeout=30
        )

    except requests.RequestException as error:
        print(f"Google request failed: {error}")
        return []

    print(f"HTTP status: {response.status_code}")

    if response.status_code != 200:
        return []

    urls = extract_x_urls(response.text)

    print(
        f"Google extracted {len(urls)} X URLs"
    )

    return urls


# ------------------------------------------------------------
# COLLECT CANDIDATES
# ------------------------------------------------------------

def collect_candidates():
    candidates = []

    for index, query in enumerate(
        SEARCH_QUERIES,
        start=1
    ):

        print("\n")
        print("#" * 70)
        print(
            f"QUERY {index}/{len(SEARCH_QUERIES)}"
        )
        print("#" * 70)

        # ----------------------------------------------------
        # Bing
        # ----------------------------------------------------

        bing_urls = search_bing(query)

        for url in bing_urls:

            if url not in candidates:
                candidates.append(url)

        time.sleep(2)

        # ----------------------------------------------------
        # Google
        # ----------------------------------------------------

        google_urls = search_google(query)

        for url in google_urls:

            if url not in candidates:
                candidates.append(url)

        time.sleep(2)

    return candidates


# ------------------------------------------------------------
# SAVE
# ------------------------------------------------------------

def save_candidates(urls):

    OUTPUT_FILE.write_text(
        "\n".join(urls),
        encoding="utf-8"
    )

    print("\n")
    print("=" * 70)
    print("DISCOVERY COMPLETE")
    print("=" * 70)

    print(
        f"TOTAL UNIQUE X POSTS: {len(urls)}"
    )

    print(
        f"Saved to: {OUTPUT_FILE}"
    )

    print("\nCandidates:")

    for index, url in enumerate(
        urls,
        start=1
    ):
        print(
            f"{index}. {url}"
        )


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():

    print("=" * 70)
    print("UTCUTIE X DISCOVERY")
    print("=" * 70)

    print(
        "Mode: Best-effort public web discovery"
    )

    print(
        "Authentication: NONE"
    )

    print(
        f"Queries: {len(SEARCH_QUERIES)}"
    )

    candidates = collect_candidates()

    save_candidates(candidates)


if __name__ == "__main__":
    main()
