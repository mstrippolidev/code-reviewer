"""
    CONC false-positive fixture: time.sleep inside a plain synchronous
    function. Should NOT be flagged as async misuse — item 3 targets a
    blocking call placed directly inside an async def, freezing the event
    loop; there is no event loop here for a sync function to block.
"""
import time


def wait_for_cooldown(seconds: float) -> None:
    time.sleep(seconds)
