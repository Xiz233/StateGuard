"""Milestone 2: DependencyGraph parents/children/ancestors/descendants,
topological order, acyclic validation (指引.txt §11/29)."""

import pytest

from stateguard.core.dependency_graph import DependencyGraph, DependencyError

# S1 -> S2, S3 ; S2, S3 -> S4 ; S5 independent
ADJ = {"S1": [], "S2": ["S1"], "S3": ["S1"], "S4": ["S2", "S3"], "S5": []}


@pytest.fixture
def g():
    return DependencyGraph(ADJ)


def test_parents_children(g):
    assert g.parents("S4") == ["S2", "S3"]
    assert g.parents("S1") == []
    assert g.children("S1") == ["S2", "S3"]
    assert g.children("S4") == []


def test_ancestors(g):
    assert g.ancestors("S4") == ["S1", "S2", "S3"]
    assert g.ancestors("S1") == []
    assert g.ancestors("S5") == []


def test_descendants(g):
    assert g.descendants("S1") == ["S2", "S3", "S4"]
    assert g.descendants("S3") == ["S4"]
    assert g.descendants("S5") == []


def test_topological_order_is_total_and_respects_deps(g):
    order = g.topological_order()
    assert sorted(order) == ["S1", "S2", "S3", "S4", "S5"]
    assert order.index("S2") > order.index("S1")
    assert order.index("S3") > order.index("S1")
    assert order.index("S4") > order.index("S2")
    assert order.index("S4") > order.index("S3")


def test_affected_set(g):
    assert g.affected_set("S1") == ["S1", "S2", "S3", "S4"]
    assert g.affected_set("S3") == ["S3", "S4"]


def test_validate_acyclic_ok(g):
    g.validate_acyclic()


def test_cycle_detected():
    with pytest.raises(DependencyError):
        DependencyGraph({"S1": ["S2"], "S2": ["S1"]}).validate_acyclic()


def test_missing_dependency_raises():
    with pytest.raises(DependencyError):
        DependencyGraph({"S1": ["S2"]})


def test_unknown_node_raises(g):
    with pytest.raises(KeyError):
        g.parents("nope")
