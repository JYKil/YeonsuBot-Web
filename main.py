"""진입점 — FastAPI 웹 서버 실행."""

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("web_server:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
