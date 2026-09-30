"""Shared helpers for long-running worker processes."""

import asyncio
import os
import signal
import socket
import uuid


def stop_on_signals() -> asyncio.Event:
    """Return an event that is set on SIGTERM/SIGINT, for a graceful shutdown."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    return stop


_INSTANCE = uuid.uuid4().hex[:6]


def worker_id() -> str:
    """Unique per process start. A restarted container reuses hostname and PID 1, and
    must not be mistaken for its dead predecessor when leases are checked."""
    return f"{socket.gethostname()}:{os.getpid()}:{_INSTANCE}"
