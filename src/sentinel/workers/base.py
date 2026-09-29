"""Shared helpers for long-running worker processes."""

import asyncio
import os
import signal
import socket


def stop_on_signals() -> asyncio.Event:
    """Return an event that is set on SIGTERM/SIGINT, for a graceful shutdown."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    return stop


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"
