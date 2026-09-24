"""
    Union-find (disjoint-set) over hashable keys, with path compression
    and union by size.
"""
from typing import Generic, TypeVar

T = TypeVar("T")


class DisjointSet(Generic[T]):
    """Groups keys into sets via union(), finds each key's group via find()."""

    def __init__(self) -> None:
        self._parent: dict[T, T] = {}
        self._size: dict[T, int] = {}

    def find(self, key: T) -> T:
        self._register(key)
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, first: T, second: T) -> None:
        first_root, second_root = self.find(first), self.find(second)
        if first_root == second_root:
            return
        smaller_root, larger_root = sorted((first_root, second_root), key=lambda root: self._size[root])
        self._parent[smaller_root] = larger_root
        self._size[larger_root] += self._size[smaller_root]

    def _register(self, key: T) -> None:
        if key not in self._parent:
            self._parent[key] = key
            self._size[key] = 1
