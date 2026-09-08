"""
    SOLID2 out-of-scope fixture, deliberately distinct from the worked
    example now in the prompt (isinstance special-casing a concrete
    subclass): ReportWriter depends on the Storage abstraction through
    constructor injection (satisfying DIP on paper), but blindly forwards
    **backend_options into it, so this class is implicitly coupled to
    whatever keyword arguments the concrete backend happens to accept —
    not itself an LSP override, an ISP-forced meaningless method, or a
    concretely-constructed dependency, so it must land outside the four
    in-scope categories.
"""
from abc import ABC, abstractmethod


class Storage(ABC):
    @abstractmethod
    def configure(self, **options: object) -> None: ...

    @abstractmethod
    def write(self, data: str) -> None: ...


class ReportWriter:
    def __init__(self, storage: Storage, **backend_options: object) -> None:
        self._storage = storage
        self._storage.configure(**backend_options)

    def write(self, report: str) -> None:
        self._storage.write(report)
