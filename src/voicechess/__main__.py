"""Local application entry point."""

from __future__ import annotations

import argparse

import uvicorn

from voicechess.api import create_app
from voicechess.config import Settings, get_settings


def main() -> None:
    """Run the local Adaptive Chess Teacher server."""
    configured = get_settings()
    parser = argparse.ArgumentParser(description="Run the local Adaptive Chess Teacher server.")
    parser.add_argument(
        "--host",
        choices=("127.0.0.1", "localhost", "::1"),
        default=configured.app_host,
        help="Local interface to bind.",
    )
    parser.add_argument("--port", type=int, default=configured.app_port, help="Port to bind.")
    args = parser.parse_args()

    runtime_settings = Settings(
        **{
            **configured.model_dump(),
            "app_host": args.host,
            "app_port": args.port,
        }
    )
    uvicorn.run(
        create_app(settings=runtime_settings),
        host=runtime_settings.app_host,
        port=runtime_settings.app_port,
    )


if __name__ == "__main__":
    main()
