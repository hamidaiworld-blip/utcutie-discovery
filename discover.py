import re
import time
from pathlib import Path
from urllib.parse import quote_plus

import requests


# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

MAX_RESULTS_PER_QUERY = 20

SEARCH_QUERIES = [
    'site:x.com "funny dog" "status"',
    'site:x.com "cute dog" "status"',
    'site:x.com "funny cat" "status"',
    'site:x.com "cute cat" "status"',
    'site:x.com "funny puppy" "status"',
    'site:x.com "cute puppy" "status"',
    'site:x.com "funny kitten" "status"',
    'site:x.com "cute kitten" "status"',
    'site:x.com "funny pet" "status"',
    'site:x.com "cute pet" "status"',
    'site:x.com "funny animal" "status"',
    'site:x.com "cute animal" "status"',
    'site:x.com "wholesome animal" "status"',
    'site:x.com "heartwarming animal" "status"',
    'site:x.com "animal friendship" "status"',
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
# X URL EXTRACTION
# ------------------------------------------------------------

X_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?x\.com/"
    r"[A-Za-z0-9_]+/status/\d+"
)


def extract_x_urls(text):
    """
    Extract unique X status URLs from arbitrary HTML/text.
    """

    if not text:
        return []

    matches = X_URL_PATTERN.findall(text)

    urls = []

    for url in matches:
        clean_url = url.rstrip(".,);]}>\"'")

        if clean_url not in urls:
            urls.append(clean_url)

    return urls


# ------------------------------------------------------------
# BING SEARCH
# ------------------------------------------------------------

def search_bing(query):
    """
    Search Bing's public HTML results.

    This is NOT the Bing API.
    It uses the public search page and therefore remains
    best-effort.
    """

    print("\n" + "=" * 70)
    print("BING SEARCH")
    print("=" * 70)
    print(query)

    url = (
        "https://www.bing.com/search?q="
        + quote_plus(query)
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

    print(f"Found {len(urls)} X URLs")

    return urls


# ------------------------------------------------------------
# GOOGLE SEARCH
# ------------------------------------------------------------

def search_google(query):
    """
    Search Google's public HTML endpoint.

    This is also best-effort and may return fewer results
    depending on Google's anti-automation behavior.
    """

    print("\n" + "=" * 70)
    print("GOOGLE SEARCH")
    print("=" * 70)
    print(query)

    url = (
        "https://www.google.com/search?q="
        + quote_plus(query)
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

    print(f"Found {len(urls)} X URLs")

    return urls


# ------------------------------------------------------------
# URL NORMALIZATION
# ------------------------------------------------------------

def normalize_x_url(url):
    """
    Normalize an X status URL so the same post is not
    counted multiple times.
    """

    match = re.search(
        r"https?://(?:www\.)?x\.com/"
        r"([A-Za-z0-9_]+)/status/(\d+)",
        url
    )

    if not match:
        return None

    username = match.group(1)
    status_id = match.group(2)

    return f"https://x.com/{username}/status/{status_id}"


# ------------------------------------------------------------
# COLLECT CANDIDATES
# ------------------------------------------------------------

def collect_candidates():
    """
    Run all discovery queries against both search engines.
    """

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

        # ----------------------------
        # Bing
        # ----------------------------

        bing_urls = search_bing(query)

        for url in bing_urls:

            normalized = normalize_x_url(url)

            if normalized and normalized not in candidates:
                candidates.append(normalized)

        time.sleep(2)

        # ----------------------------
        # Google
        # ----------------------------

        google_urls = search_google(query)

        for url in google_urls:

            normalized = normalize_x_url(url)

            if normalized and normalized not in candidates:
                candidates.append(normalized)

        time.sleep(2)

    return candidates


# ------------------------------------------------------------
# SAVE RESULTS
# ------------------------------------------------------------

def save_candidates(urls):
    """
    Save candidate URLs for the next pipeline stage.
    """

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
