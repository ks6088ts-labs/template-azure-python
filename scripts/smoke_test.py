"""Read-only HTTP probes suitable for local and container deployments."""

import argparse
import http.client
import sys
import time
from collections.abc import Sequence
from urllib.parse import urlsplit


def check_health(base_url: str, *, timeout: float = 3.0) -> None:
    url = urlsplit(base_url)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise ValueError("Provide an HTTP(S) origin without credentials, path, query, or fragment.")
    if timeout <= 0:
        raise ValueError("Timeout must be positive.")
    connection_type = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    for endpoint in ("/healthz", "/readyz"):
        connection = connection_type(url.hostname, url.port, timeout=timeout)
        try:
            connection.request("GET", endpoint)
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError(f"{endpoint} returned HTTP {response.status}.")
        finally:
            connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--attempts", type=int, default=30)
    parser.add_argument("--interval", "--delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args(argv)
    if args.attempts < 1 or args.interval < 0 or args.timeout <= 0:
        parser.error("attempts and timeout must be positive; interval must be non-negative")
    for attempt in range(args.attempts):
        try:
            check_health(args.base_url, timeout=args.timeout)
        except (OSError, http.client.HTTPException, RuntimeError, ValueError) as error:
            if attempt == args.attempts - 1:
                print(f"Health probes failed: {error}", file=sys.stderr)
                return 1
            time.sleep(args.interval)
        else:
            print("GET /healthz and /readyz succeeded.")
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
