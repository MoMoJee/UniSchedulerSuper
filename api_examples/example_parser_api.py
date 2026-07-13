"""Public speech-to-text API example."""

import argparse
from pathlib import Path

import requests

from client import BASE_URL, ApiError


def speech_to_text(path: Path) -> dict:
    with path.open("rb") as stream:
        response = requests.post(
            f"{BASE_URL}/api/agent/speech-to-text/",
            files={"audio": (path.name, stream)},
            timeout=90,
        )
    if not response.ok:
        raise ApiError(response)
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path, help="≤15MB、≤60秒的受支持音频文件")
    args = parser.parse_args()
    print(speech_to_text(args.audio))


if __name__ == "__main__":
    main()
