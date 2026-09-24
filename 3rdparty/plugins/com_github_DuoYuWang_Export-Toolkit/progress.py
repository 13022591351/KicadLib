"""Visible, timed preparation steps; native board calls remain on the GUI thread."""
import time


def prepare(label, action, log=print, heartbeat=None):
    log(f'Preparing: {label}...')
    if heartbeat:
        heartbeat()
    started = time.monotonic()
    result = action()
    log(f'Preparing: {label} completed in {time.monotonic() - started:.2f}s.')
    if heartbeat:
        heartbeat()
    return result
