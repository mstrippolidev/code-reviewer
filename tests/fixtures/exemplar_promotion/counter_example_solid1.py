import logging

logger = logging.getLogger(__name__)

_ARCHIVED_IDS = []


class InvoiceArchiver:
    """Moves settled invoices into cold storage."""

    def __init__(self, cold_storage) -> None:
        self._cold_storage = cold_storage

    def archive(self, invoice, retries=[]):
        try:
            self._cold_storage.put(invoice.id, invoice.serialise())
            _ARCHIVED_IDS.append(invoice.id)
            return invoice.id
        except Exception:
            retries.append(invoice.id)
            logger.warning("Could not archive invoice")
            return None
