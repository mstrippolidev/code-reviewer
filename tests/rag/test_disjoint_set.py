from code_reviewer.rag.disjoint_set import DisjointSet


def test_find_on_an_unseen_key_returns_itself() -> None:
    disjoint_set: DisjointSet[str] = DisjointSet()

    assert disjoint_set.find("a") == "a"


def test_union_makes_two_keys_share_a_root() -> None:
    disjoint_set: DisjointSet[str] = DisjointSet()

    disjoint_set.union("a", "b")

    assert disjoint_set.find("a") == disjoint_set.find("b")


def test_transitively_connected_keys_share_a_root() -> None:
    disjoint_set: DisjointSet[str] = DisjointSet()
    disjoint_set.union("a", "b")

    disjoint_set.union("b", "c")

    assert disjoint_set.find("a") == disjoint_set.find("c")


def test_unconnected_keys_do_not_share_a_root() -> None:
    disjoint_set: DisjointSet[str] = DisjointSet()
    disjoint_set.union("a", "b")
    disjoint_set.union("c", "d")

    assert disjoint_set.find("a") != disjoint_set.find("c")


def test_union_of_already_merged_keys_is_a_no_op() -> None:
    disjoint_set: DisjointSet[str] = DisjointSet()
    disjoint_set.union("a", "b")
    root_before = disjoint_set.find("a")

    disjoint_set.union("a", "b")

    assert disjoint_set.find("a") == root_before
