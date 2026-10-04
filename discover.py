import html
import re
import time
from urllib.parse import quote_plus, unquote

import requests


SEARCH_QUERIES = [
    'funny dog x.com',
    'cute dog x.com',
    'funny cat x.com',
    'cute cat x.com',
    'funny pet video x.com',
    'cute pet video x.com',
    'funny animal video x.com',
    'wholesome animal x.com',
    'heartwarming animal x.com',
    'animal friendship x.com',
    'funny puppy video x.com',
    'funny kitten video x.com',
]


X_STATUS_PATTERN = re.compile(
    r'https?://(?:www\.)?x\.com/[^"\s<>?&]+/status/\d+',
    re.IGNORECASE
)

X_STATUS_PATTERN_ENCODED = re.compile(
    r'https?%3A%2F%2F(?:www\.)?x\.com%2F[^&"\s<>?]+%2Fstatus%2F\d+',
    re.IGNORECASE
)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def search_duckduckgo(query):
    url = (
        "https://html.duckduckgo.com/html/?q="
        + quote_plus(query)
    )

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    return response.text


def extract_x_urls(page):
    page = html.unescape(page)

    urls = []

    encoded_matches = X_STATUS_PATTERN_ENCODED.findall(page)

    for url in encoded_matches:
        url = unquote(url)

        match = X_STATUS_PATTERN.search(url)

        if match:
            clean_url = match.group(0)

            if clean_url not in urls:
                urls.append(clean_url)

    normal_matches = X_STATUS_PATTERN.findall(page)

    for url in normal_matches:
        if url not in urls:
            urls.append(url)

    return urls


def main():
    all_urls = []

    for query in SEARCH_QUERIES:
        print(f"\nSearching: {query}")

        try:
            page = search_duckduckgo(query)

            urls = extract_x_urls(page)

            print(f"Found {len(urls)} X URLs")

            for url in urls:
                if url not in all_urls:
                    all_urls.append(url)

        except Exception as error:
            print(f"Search failed: {error}")

        time.sleep(2)

    print("\n" + "=" * 60)
    print(f"TOTAL UNIQUE X POSTS: {len(all_urls)}")
    print("=" * 60)

    for index, url in enumerate(all_urls, start=1):
        print(f"{index}. {url}")


if __name__ == "__main__":
    main()
