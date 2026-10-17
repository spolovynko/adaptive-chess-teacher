"""Local application entry point."""

from __future__ import annotations

import argparse
from importlib import import_module
from typing import Any, cast


def main() -> None:
    """Run the local Voice Chess Coach server once its API is implemented."""
    parser = argparse.ArgumentParser(description="Run the local Voice Chess Coach server.")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind.")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind.")
    args = parser.parse_args()

    try:
        api_module = import_module("voicechess.api")
    except ModuleNotFoundError as exc:
        if exc.name == "voicechess.api":
            parser.error(
                "The web API has not been implemented yet; it is scheduled for Phase 0 Step 10."
            )
        raise

    import uvicorn

    app: Any = cast(Any, api_module).app
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
