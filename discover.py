import json
import re
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


REPO_URL = (
    "https://github.com/ythx-101/x-tweet-fetcher.git"
)

FETCHER_DIR = Path("/tmp/x-tweet-fetcher")


def run_command(command, timeout=300):
    print("\nRunning:")
    print(" ".join(command))

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout
    )

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print(result.stderr)

    return result


def install_fetcher():
    print("Cloning x-tweet-fetcher...")

    if FETCHER_DIR.exists():
        subprocess.run(
            ["rm", "-rf", str(FETCHER_DIR)],
            check=False
        )

    result = run_command(
        [
            "git",
            "clone",
            "--depth",
            "1",
            REPO_URL,
            str(FETCHER_DIR)
        ],
        timeout=180
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Could not clone x-tweet-fetcher."
        )

    print("Installing x-tweet-fetcher from source...")

    result = run_command(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "."
        ],
        timeout=300
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Could not install x-tweet-fetcher from source."
        )


def install_browser():
    print("Installing Playwright...")

    result = run_command(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "playwright"
        ],
        timeout=300
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Could not install Playwright."
        )

    print("Installing Chromium...")

    result = run_command(
        [
            sys.executable,
            "-m",
            "playwright",
            "install",
            "--with-deps",
            "chromium"
        ],
        timeout=600
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Could not install Chromium."
        )


def extract_urls(data):
    urls = []

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():

                if isinstance(item, str):
                    if (
                        "x.com/" in item
                        and "/status/" in item
                    ):
                        match = re.search(
                            r"https?://(?:www\.)?x\.com/[^/\s]+/status/\d+",
                            item
                        )

                        if match:
                            url = match.group(0)

                            if url not in urls:
                                urls.append(url)

                walk(item)

        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)

    return urls


def search_x(query):
    print("\n" + "-" * 60)
    print(f"Searching X for: {query}")
    print("-" * 60)

    script = str(
        FETCHER_DIR / "scripts" / "fetch_tweet.py"
    )

    result = run_command(
        [
            sys.executable,
            script,
            "--search",
            query,
            "--limit",
            "10",
            "--backend",
            "browser"
        ],
        timeout=300
    )

    if result.returncode != 0:
        print(
            f"Search returned exit code "
            f"{result.returncode}"
        )

        return []

    output = result.stdout.strip()

    if not output:
        return []

    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        print(
            "Output was not JSON. "
            "Showing it above for diagnosis."
        )

        return []

    return extract_urls(data)


def main():
    install_fetcher()

    install_browser()

    all_urls = []

    for query in SEARCH_QUERIES:

        try:
            urls = search_x(query)

            print(
                f"Extracted {len(urls)} X URLs"
            )

            for url in urls:
                if url not in all_urls:
                    all_urls.append(url)

        except subprocess.TimeoutExpired:
            print("Search timed out.")

        except Exception as error:
            print(
                f"Search error: {error}"
            )

    print("\n" + "=" * 60)
    print(
        f"TOTAL UNIQUE X POSTS: "
        f"{len(all_urls)}"
    )
    print("=" * 60)

    for index, url in enumerate(
        all_urls,
        start=1
    ):
        print(
            f"{index}. {url}"
        )

    Path(
        "candidate_urls.txt"
    ).write_text(
        "\n".join(all_urls),
        encoding="utf-8"
    )

    print(
        "\nSaved candidates to "
        "candidate_urls.txt"
    )


if __name__ == "__main__":
    main()
