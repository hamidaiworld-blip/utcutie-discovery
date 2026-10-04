import json
import subprocess
import sys
from pathlib import Path


SEARCH_QUERIES = [
    "funny dog video",
    "cute dog video",
    "funny cat video",
    "cute cat video",
    "funny pet video",
    "cute pet video",
    "funny animal video",
    "wholesome animal",
    "heartwarming animal",
    "animal friendship",
]


def install_fetcher():
    print("Installing x-tweet-fetcher...")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "x-tweet-fetcher"
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError(
            "Could not install x-tweet-fetcher."
        )


def search_x(query):
    print(f"\nSearching X: {query}")

    result = subprocess.run(
        [
            "xtf",
            "--search",
            query,
            "--limit",
            "20"
        ],
        capture_output=True,
        text=True,
        timeout=120
    )

    if result.returncode != 0:
        print("Search failed:")
        print(result.stderr)

        return []

    output = result.stdout.strip()

    if not output:
        return []

    try:
        data = json.loads(output)

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            for key in ("tweets", "results", "data"):
                if isinstance(data.get(key), list):
                    return data[key]

    except json.JSONDecodeError:
        print("Could not parse JSON output.")

    return []


def extract_url(tweet):
    if not isinstance(tweet, dict):
        return None

    possible_fields = [
        "url",
        "tweet_url",
        "link",
        "status_url"
    ]

    for field in possible_fields:
        value = tweet.get(field)

        if isinstance(value, str):
            if "x.com/" in value and "/status/" in value:
                return value

            if "twitter.com/" in value and "/status/" in value:
                return value

    tweet_id = (
        tweet.get("id")
        or tweet.get("tweet_id")
        or tweet.get("id_str")
    )

    author = tweet.get("author")

    if isinstance(author, dict):
        username = (
            author.get("username")
            or author.get("screen_name")
            or author.get("handle")
        )

        if username and tweet_id:
            return f"https://x.com/{username}/status/{tweet_id}"

    username = (
        tweet.get("username")
        or tweet.get("screen_name")
    )

    if username and tweet_id:
        return f"https://x.com/{username}/status/{tweet_id}"

    return None


def main():
    install_fetcher()

    all_urls = []

    for query in SEARCH_QUERIES:
        try:
            tweets = search_x(query)

            print(f"Returned {len(tweets)} results")

            for tweet in tweets:
                url = extract_url(tweet)

                if url and url not in all_urls:
                    all_urls.append(url)

        except Exception as error:
            print(f"Search error: {error}")

    print("\n" + "=" * 60)
    print(f"TOTAL UNIQUE X POSTS: {len(all_urls)}")
    print("=" * 60)

    output_file = Path("candidate_urls.txt")

    output_file.write_text(
        "\n".join(all_urls),
        encoding="utf-8"
    )

    for index, url in enumerate(all_urls, start=1):
        print(f"{index}. {url}")

    print("\nSaved candidates to candidate_urls.txt")


if __name__ == "__main__":
    main()
