"""
    COH out-of-scope fixture: temporal cohesion — every method reads the
    same shared config, so this is not a disjoint-attribute split, but the
    three methods are grouped only because they all run once at startup,
    not because they share one purpose. Not a bundled-concerns case in the
    item-1 sense (item 1 is about concerns that operate on separate data;
    here all three lean on the same self._config), not disjoint methods
    (they all touch the same attribute), not a grab-bag module (this is a
    class, and it groups only three closely-related-by-timing steps), and
    no method ignores self — a real but weaker form of low cohesion
    outside the four in-scope categories.
"""


class ApplicationBootstrapper:
    def __init__(self, config: dict) -> None:
        self._config = config

    def setup_logging(self) -> None:
        print(f"logging configured with level={self._config.get('log_level')}")

    def warm_cache(self) -> None:
        print(f"cache warmed with size={self._config.get('cache_size')}")

    def load_feature_flags(self) -> None:
        print(f"feature flags loaded from {self._config.get('flags_source')}")
