"""
    CONC violation fixture: async/await misuse. fetch_user_profile is
    declared async but calls the blocking time.sleep instead of
    asyncio.sleep, so it freezes the entire event loop for every other
    task while it waits.
"""
import time


async def fetch_user_profile(user_id: str) -> dict:
    time.sleep(2)
    return {"id": user_id, "name": "loaded profile"}
