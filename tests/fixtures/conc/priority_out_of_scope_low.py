"""
    CONC out-of-scope fixture: unbounded concurrency. process_all spawns
    one asyncio task per item with no semaphore, pool, or other limit, so
    nothing bounds how many tasks run at once regardless of how large
    items is. Not unprotected shared state (each task only touches its
    own item), not a check-then-act race, not a blocking call inside
    async (each task correctly awaits), and not a non-atomic multi-step
    resource operation, so it sits outside the four in-scope categories —
    but it is still dangerous concurrent behavior.
"""
import asyncio


async def handle_item(item: str) -> None:
    await asyncio.sleep(0.1)
    print(f"handled {item}")


async def process_all(items: list[str]) -> None:
    tasks = [asyncio.create_task(handle_item(item)) for item in items]
    await asyncio.gather(*tasks)
