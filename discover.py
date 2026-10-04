import json
import subprocess
import sys
from pathlib import Path


REPO_URL = "https://github.com/ythx-101/x-tweet-fetcher.git"

FETCHER_DIR = Path("/tmp/x-tweet-fetcher")

SEARCH_QUERIES = [
    "funny dog",
    "cute dog",
    "funny cat",
    "cute cat",
]


def run_command(command, timeout=300, cwd=None):
    print("\nRunning:")
    print(" ".join(command))

    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print(result.stderr)

    return result


def install_fetcher():
    print("=" * 70)
    print("INSTALLING X-TWEET-FETCHER")
    print("=" * 70)

    if FETCHER_DIR.exists():
        subprocess.run(
            ["rm", "-rf", str(FETCHER_DIR)],
            check=False,
        )

    result = run_command(
        [
            "git",
            "clone",
            "--depth",
            "1",
            REPO_URL,
            str(FETCHER_DIR),
        ],
        timeout=180,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Could not clone x-tweet-fetcher."
        )

    print("Repository cloned successfully.")

    # IMPORTANT:
    # Install the repository itself, not the GitHub
    # Actions working directory.
    result = run_command(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            ".",
        ],
        timeout=300,
        cwd=FETCHER_DIR,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Could not install x-tweet-fetcher."
        )

    print("x-tweet-fetcher installed successfully.")


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
                        if item not in urls:
                            urls.append(item)

                walk(item)

        elif isinstance(value, list):

            for item in value:
                walk(item)

    walk(data)

    return urls


def search_x(query):

    print("\n")
    print("=" * 70)
    print("X SEARCH TEST")
    print("=" * 70)

    print(f"Query: {query}")

    script = (
        FETCHER_DIR
        / "scripts"
        / "fetch_tweet.py"
    )

    result = run_command(
        [
            sys.executable,
            str(script),
            "--search",
            query,
            "--limit",
            "10",
        ],
        timeout=180,
    )

    print(
        f"Exit code: {result.returncode}"
    )

    if result.returncode != 0:
        print("Search failed.")

        return []

    output = result.stdout.strip()

    if not output:
        print("Search returned no stdout.")

        return []

    try:
        data = json.loads(output)

    except json.JSONDecodeError:
        print(
            "Search output was not valid JSON."
        )

        print(
            "Raw output:"
        )

        print(output)

        return []

    urls = extract_urls(data)

    print(
        f"Extracted X URLs: {len(urls)}"
    )

    return urls


def main():

    print("=" * 70)
    print("UTCUTIE X DISCOVERY ADAPTER TEST")
    print("=" * 70)

    print(
        "Testing x-tweet-fetcher directly."
    )

    print(
        "No X login."
    )

    print(
        "No API key."
    )

    install_fetcher()

    all_urls = []

    for query in SEARCH_QUERIES:

        try:

            urls = search_x(query)

            for url in urls:

                if url not in all_urls:
                    all_urls.append(url)

        except subprocess.TimeoutExpired:

            print(
                "Search timed out."
            )

        except Exception as error:

            print(
                f"Search error: {error}"
            )

    print("\n")
    print("=" * 70)
    print("ADAPTER TEST COMPLETE")
    print("=" * 70)

    print(
        f"TOTAL UNIQUE X URLS: {len(all_urls)}"
    )

    for index, url in enumerate(
        all_urls,
        start=1,
    ):
        print(
            f"{index}. {url}"
        )

    Path(
        "candidate_urls.txt"
    ).write_text(
        "\n".join(all_urls),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
