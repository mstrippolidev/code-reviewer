import threading
import time

_stock_cache = {}
_last_refresh = 0


def load_stock_from_warehouse(sku):
    time.sleep(0.2)
    return 100


def get_stock(sku):
    if sku not in _stock_cache:
        _stock_cache[sku] = load_stock_from_warehouse(sku)
    return _stock_cache[sku]


def reserve(sku, quantity):
    available = get_stock(sku)
    if available >= quantity:
        time.sleep(0.01)
        _stock_cache[sku] = available - quantity
        return True
    return False


def refresh_all():
    global _last_refresh
    for sku in list(_stock_cache.keys()):
        _stock_cache[sku] = load_stock_from_warehouse(sku)
    _last_refresh = time.time()


def handle_checkout_burst(sku, orders):
    threads = []
    for quantity in orders:
        thread = threading.Thread(target=reserve, args=(sku, quantity))
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()
    return _stock_cache[sku]
