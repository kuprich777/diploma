"""Tests for the classical risk operator — two-mechanism design.

Design rules under test:
  1. Node binarisation:   y_i = I(x_i >= theta_node)
  2. Cascade propagation: topology-based, edge fires iff A[i][j] > 0.0
                          (NOT filtered by theta_node)

These two mechanisms are DELIBERATELY SEPARATED so that:
  - theta_node can be tuned to avoid pre-shock saturation, AND
  - the classical topology remains fully connected through all nonzero edges.

Old design (SUPERSEDED): A[i][j] >= theta_node filtered BOTH binarisation AND
edge activation. At theta_node=0.25 all sectors were pre-saturated (K_cl=0.0).
At theta_node=0.5 the topology was disconnected (1 edge only). Both problems
are resolved by the separation.

These tests are self-contained (no DB / SQLAlchemy required) — they inline the
pure-function logic of apply_dependencies_classical so they run locally and
inside containers alike.
"""

# Matrix A v1.0 — matches config.py DEPENDENCY_MATRIX and live snapshot.
# A[i][j] = influence of sector j (source) on sector i (destination).
# Sectors order: [energy=0, water=1, transport=2]
A_V1 = [
    [0.0, 0.2, 0.3],  # energy depends on water(0.2), transport(0.3)
    [0.4, 0.0, 0.2],  # water depends on energy(0.4), transport(0.2)
    [0.5, 0.3, 0.0],  # transport depends on energy(0.5), water(0.3)
]

SECTORS = ["energy", "water", "transport"]

# Baseline pre-shock quantitative risks observed in S1_energy_outage experiments.
BASELINE_RISKS = {"energy": 0.667, "water": 0.267, "transport": 0.333}
THETA_NODE_DEFAULT = 0.70  # system default: just above max baseline risk (0.667)


def _apply_classical(energy_risk: float, water_risk: float, transport_risk: float,
                     theta_node: float, matrix=None) -> dict:
    """Pure-function replica of apply_dependencies_classical from routers/risk.py.

    Two-mechanism design:
      1. Binarisation:   y_i = I(x_i >= theta_node)
      2. Propagation:    edge fires iff A[i][j] > 0.0  (topology, not threshold)

    Kept in sync with the service implementation to test topology logic without
    needing the full FastAPI/SQLAlchemy import chain.
    """
    if matrix is None:
        matrix = A_V1

    y = [
        1.0 if float(energy_risk) >= theta_node else 0.0,
        1.0 if float(water_risk) >= theta_node else 0.0,
        1.0 if float(transport_risk) >= theta_node else 0.0,
    ]
    y_next = y.copy()
    for i in range(3):
        if y_next[i] >= 1.0:
            continue
        for j in range(3):
            if y[j] >= 1.0 and float(matrix[i][j]) > 0.0:   # topology-based
                y_next[i] = 1.0
                break
    return {"energy": y_next[0], "water": y_next[1], "transport": y_next[2]}


def _topology_edges(matrix) -> list[tuple[str, str, float]]:
    """Return list of (dest, src, weight) for all nonzero directed edges."""
    active = []
    for i, dest in enumerate(SECTORS):
        for j, src in enumerate(SECTORS):
            if i == j:
                continue
            v = float(matrix[i][j])
            if v > 0.0:
                active.append((dest, src, v))
    return active


# ---------------------------------------------------------------------------
# Pre-shock saturation tests (core acceptance criterion for Issue #3 follow-up)
# ---------------------------------------------------------------------------

def test_pre_shock_not_saturated_at_theta_node_default() -> None:
    """At theta_node=0.70, baseline pre-shock risks produce classical state {0,0,0}.

    Baseline risks: energy≈0.667, water≈0.267, transport≈0.333.
    All are below 0.70, so no sector is binarised to 1 before any shock.
    This ensures K_cl is not degenerate (was K_cl=0.0 with old theta_bin=0.25).
    """
    result = _apply_classical(
        BASELINE_RISKS["energy"],
        BASELINE_RISKS["water"],
        BASELINE_RISKS["transport"],
        theta_node=THETA_NODE_DEFAULT,
    )
    assert result["energy"] == 0.0, (
        f"energy={result['energy']} — should be 0 at baseline (0.667 < 0.70)"
    )
    assert result["water"] == 0.0, (
        f"water={result['water']} — should be 0 at baseline (0.267 < 0.70)"
    )
    assert result["transport"] == 0.0, (
        f"transport={result['transport']} — should be 0 at baseline (0.333 < 0.70)"
    )


def test_post_shock_cascade_reaches_all_sectors() -> None:
    """After energy outage (energy_risk→1.0), cascade reaches water AND transport.

    With topology-based propagation (A[i][j] > 0):
      - y_energy = 1 (1.0 >= 0.70)
      - A[water][energy]=0.4 > 0  → water activates
      - A[transport][energy]=0.5 > 0 → transport activates
    Both non-initiator sectors must be active after one propagation step.
    """
    result = _apply_classical(1.0, BASELINE_RISKS["water"], BASELINE_RISKS["transport"],
                              theta_node=THETA_NODE_DEFAULT)
    assert result["energy"] >= 1.0, "energy should be 1 after outage"
    assert result["water"] >= 1.0, (
        f"water={result['water']} — topology propagation must activate water "
        f"(A[water][energy]=0.4 > 0)"
    )
    assert result["transport"] >= 1.0, (
        f"transport={result['transport']} — topology propagation must activate transport "
        f"(A[transport][energy]=0.5 > 0)"
    )


# ---------------------------------------------------------------------------
# Topology propagation independence from theta_node
# ---------------------------------------------------------------------------

def test_topology_propagation_independent_of_theta_node() -> None:
    """Edge activation is based on A[i][j] > 0, NOT on theta_node magnitude.

    Regardless of whether theta_node=0.25 or theta_node=0.9, once a node is
    binarised to 1, it cascades through ALL nonzero edges.
    We test with a high theta_node to confirm the edge activation path is the same.
    """
    for theta_node in (0.25, 0.5, 0.70, 0.90):
        # energy risk = 0.95 → above every theta_node tested
        result = _apply_classical(0.95, 0.05, 0.05, theta_node=theta_node)
        assert result["water"] >= 1.0, (
            f"At theta_node={theta_node}: water must activate via A[water][energy]=0.4>0, "
            f"got water={result['water']}"
        )
        assert result["transport"] >= 1.0, (
            f"At theta_node={theta_node}: transport must activate via A[transport][energy]=0.5>0, "
            f"got transport={result['transport']}"
        )


def test_cascade_respects_nonzero_topology() -> None:
    """Edges with weight=0 never propagate; nonzero edges always do.

    Verifying that the propagation logic is: A[i][j] > 0.0, not A[i][j] >= anything.
    """
    # Diagonal is 0 — no self-loops
    # A[energy][water]=0.2 > 0: energy can receive from water
    result_water_to_energy = _apply_classical(0.05, 0.95, 0.05, theta_node=0.70)
    assert result_water_to_energy["energy"] >= 1.0, (
        "energy must activate when water=1 (A[energy][water]=0.2>0)"
    )

    # A[energy][transport]=0.3 > 0: energy can receive from transport
    result_transport_to_energy = _apply_classical(0.05, 0.05, 0.95, theta_node=0.70)
    assert result_transport_to_energy["energy"] >= 1.0, (
        "energy must activate when transport=1 (A[energy][transport]=0.3>0)"
    )

    # A[water][transport]=0.2 > 0: water can receive from transport
    result_transport_to_water = _apply_classical(0.05, 0.05, 0.95, theta_node=0.70)
    assert result_transport_to_water["water"] >= 1.0, (
        "water must activate when transport=1 (A[water][transport]=0.2>0)"
    )


def test_no_cascade_when_all_below_theta_node() -> None:
    """If all input risks are below theta_node, classical state stays {0,0,0}."""
    result = _apply_classical(0.3, 0.2, 0.25, theta_node=0.70)
    assert result["energy"] == 0.0
    assert result["water"] == 0.0
    assert result["transport"] == 0.0


def test_no_cascade_without_active_source() -> None:
    """If no sector is initially above theta_node, propagation produces no cascade."""
    result = _apply_classical(0.69, 0.69, 0.69, theta_node=0.70)
    # All below 0.70 → no activation → no propagation
    assert result["energy"] == 0.0
    assert result["water"] == 0.0
    assert result["transport"] == 0.0


# ---------------------------------------------------------------------------
# Full topology coverage
# ---------------------------------------------------------------------------

def test_matrix_has_six_nonzero_edges() -> None:
    """Matrix A v1.0 has exactly 6 nonzero directed edges (fully connected)."""
    edges = _topology_edges(A_V1)
    assert len(edges) == 6, (
        f"Expected 6 topology edges in A v1.0, got {len(edges)}: {edges}"
    )


def test_graph_connected_via_topology() -> None:
    """All 3 sectors are reachable from any starting sector via topology edges."""
    adj: dict[str, set[str]] = {s: set() for s in SECTORS}
    for i, dest in enumerate(SECTORS):
        for j, src in enumerate(SECTORS):
            if i != j and float(A_V1[i][j]) > 0.0:
                adj[src].add(dest)

    for start in SECTORS:
        visited = {start}
        frontier = list(adj[start])
        while frontier:
            node = frontier.pop()
            if node not in visited:
                visited.add(node)
                frontier.extend(adj[node] - visited)
        assert len(visited) == 3, (
            f"Starting from '{start}', only {visited} reachable — graph not fully connected"
        )


def test_water_to_energy_cascade() -> None:
    """Verify water → energy cascade (A[energy][water]=0.2 > 0)."""
    result = _apply_classical(0.05, 0.95, 0.05, theta_node=0.70)
    assert result["water"] >= 1.0
    assert result["energy"] >= 1.0, "energy must receive cascade from water"


def test_transport_to_water_cascade() -> None:
    """Verify transport → water cascade (A[water][transport]=0.2 > 0)."""
    result = _apply_classical(0.05, 0.05, 0.95, theta_node=0.70)
    assert result["transport"] >= 1.0
    assert result["water"] >= 1.0, "water must receive cascade from transport"


def test_transport_to_energy_cascade() -> None:
    """Verify transport → energy cascade (A[energy][transport]=0.3 > 0)."""
    result = _apply_classical(0.05, 0.05, 0.95, theta_node=0.70)
    assert result["transport"] >= 1.0
    assert result["energy"] >= 1.0, "energy must receive cascade from transport"


# ---------------------------------------------------------------------------
# Regression: document superseded theta=0.5 behavior for historical reference
# ---------------------------------------------------------------------------

def test_old_threshold_design_would_disconnect_water(monkeypatch) -> None:
    """HISTORICAL regression: the OLD design (edge filter = threshold) at theta=0.5
    would NOT activate water from energy (A[water][energy]=0.4 < 0.5).

    This is documented here as a regression guard: the new design must NOT replicate
    this behavior. The new test confirms water IS activated under the new design.
    (Uses inline OLD logic — does not test production code.)
    """
    def _old_apply_classical(energy_risk, water_risk, transport_risk, threshold):
        y = [
            1.0 if float(energy_risk) >= threshold else 0.0,
            1.0 if float(water_risk) >= threshold else 0.0,
            1.0 if float(transport_risk) >= threshold else 0.0,
        ]
        y_next = y.copy()
        for i in range(3):
            if y_next[i] >= 1.0:
                continue
            for j in range(3):
                if y[j] >= 1.0 and float(A_V1[i][j]) >= threshold:  # OLD: >= threshold
                    y_next[i] = 1.0
                    break
        return {"energy": y_next[0], "water": y_next[1], "transport": y_next[2]}

    # Old design at theta=0.5: energy(1.0) does NOT cascade to water(0.4 < 0.5)
    old_result = _old_apply_classical(1.0, 0.05, 0.05, threshold=0.5)
    assert old_result["water"] == 0.0, "OLD design: water should NOT activate at theta=0.5"

    # New design at theta_node=0.70: energy(1.0) DOES cascade to water (topology)
    new_result = _apply_classical(1.0, 0.05, 0.05, theta_node=0.70)
    assert new_result["water"] >= 1.0, "NEW design: water MUST activate (A[water][energy]=0.4>0)"
