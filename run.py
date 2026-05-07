# -*- coding: utf-8 -*-
"""
run.py — Start uvicorn with production-friendly settings.

Usage:
    .\.venv\Scripts\python.exe run.py
    .\.venv\Scripts\python.exe run.py --reload   # dev mode
"""

import argparse
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tender Analyzer API server")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    uvicorn.run(
        "app.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        # Keep connections alive for long-running pipeline requests
        timeout_keep_alive=620,
        # Graceful shutdown wait — let in-flight pipeline finish
        timeout_graceful_shutdown=30,
        # Increase h11 buffer for large PDF uploads
        h11_max_incomplete_event_size=10 * 1024 * 1024,  # 10 MB
        log_level="info",
    )
