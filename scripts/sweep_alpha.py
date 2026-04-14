"""
sweep_alpha.py
==============
Sweep over degradation parameter α ∈ {0, 1, 2, 3, 5, 8, 10, 15, 20}
for two canonical scenarios in the **marginal** cascade regime:

  S3: transport initiator, load_increase shock (+0.25), T=7 steps
      → K_cl(α=0) ≈ 0.57, K_q(α=0) ≈ 0.89  (non-saturated)

  S4: water initiator, load_increase shock (+0.20), T=7 steps
      → K_cl(α=0) ≈ 0.62, K_q(α=0) ≈ 1.00  (K_cl non-saturated)

The marginal regime is required for the α-effect to be observable:
  * If K=1 for all α, the dampening signal is invisible.
  * At T=7 steps, energy has just reached the C_energy boundary
    stochastically; α attenuates feedback loops right at the decision
    boundary, where small coupling changes shift K measurably.

For each α, runs N=1000 MC simulations with SDEIntegrator and
computes K_cl(α), K_q(α), ΔK(α) = K_q − K_cl.

The sweep addresses the empirical question:
  Does dynamic supply-chain degradation (α>0) dampen or amplify cascades?

Expected mechanism (dampening hypothesis):
  Overloaded supplier j reduces outgoing coupling (φ_j < 1).
  Downstream nodes receive less drift → less likely to cross C_j.
  → K_cl and K_q decrease as α increases (dampening dominates).

Output
------
  results/alpha_sweep.json
  results/alpha_sweep.csv    (for plotting)

Usage
-----
  python scripts/sweep_alpha.py
"""

import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from services.risk_engine.sde_integrator import SDEConfig, SDEIntegrator

# ---------------------------------------------------------------------------
# Model parameters (from data/calibration/)
# ---------------------------------------------------------------------------
A_STATIC = np.array([
    [0.000, 0.350, 0.304],   # energy depends on water, transport
    [0.006, 0.000, 0.001],   # water depends on energy, transport
    [0.500, 0.332, 0.000],   # transport depends on energy, water
])

# Calibrated capacity thresholds (capacity_thresholds.json)
C = np.array([0.8832, 0.6463, 0.9280])   # energy, water, transport

# Volatility (sigma_calibrated.json — ICS median; transport proxied from energy)
SIGMA = np.array([0.259, 0.232, 0.259])  # P4_ST_PO, P3_LIT01, approx

# No mean-reversion (ρ=0 calibration pending)
RHO = np.zeros(3)

# Integration parameters
# T_steps=7: marginal regime — energy reaches C_energy boundary
# stochastically; α effect is visible on cascade probability.
DT      = 0.1
T_STEPS = 7
DELTA   = 0.10

# Monte Carlo settings
N_RUNS  = 1000

# Scenario definitions (marginal regime):
#   S3: transport shock = +0.25 → x_transport = 0.583 (well below C_transport=0.928)
#       Cascade detection horizon T=7: energy reaches ~0.791 deterministically;
#       stochastic noise drives ~57% of runs above C_energy=0.8832.
#   S4: water shock = +0.20 → x_water = 0.600 (just below C_water=0.6463)
#       Stochastic noise drives ~60% of runs' energy above C_energy via
#       A[energy,water]=0.350 drift; water supplier attenuation (α>0) dampens this.
SCENARIOS = {
    "S3_transport": {
        "initiator": 2,
        "shock":     np.array([0.0, 0.0, 0.25]),   # transport load increase
        "x0":        np.array([0.667, 0.400, 0.333]),
    },
    "S4_water": {
        "initiator": 1,
        "shock":     np.array([0.0, 0.20, 0.0]),    # water partial load increase
        "x0":        np.array([0.667, 0.400, 0.333]),
    },
}

ALPHA_VALUES = [0, 1, 2, 3, 5, 8, 10, 15, 20]


# ---------------------------------------------------------------------------

def run_mc(alpha: float, scenario: dict, sc_name: str) -> dict:
    """Run N_RUNS Monte Carlo simulations and return K_cl, K_q, max_delta."""
    cfg = SDEConfig(
        A       = A_STATIC,
        sigma   = SIGMA,
        rho     = RHO,
        C       = C,
        dt      = DT,
        T_steps = T_STEPS,
        delta   = DELTA,
        alpha   = alpha,
    )
    integrator = SDEIntegrator(cfg)
    initiator  = scenario["initiator"]
    shock      = scenario["shock"]
    x0         = scenario["x0"]

    I_cl_total = 0
    I_q_total  = 0
    deltas: list[float] = []

    for r in range(N_RUNS):
        seed = SDEIntegrator.make_seed(f"{sc_name}_alpha{alpha:.1f}", r)
        traj = integrator.run(x0=x0, shock=shock, seed=seed)
        res  = integrator.detect_cascade(traj, initiator=initiator)
        I_cl_total += res.I_cl
        I_q_total  += res.I_q
        deltas.append(res.max_delta)

    K_cl = I_cl_total / N_RUNS
    K_q  = I_q_total  / N_RUNS

    # Monte Carlo 95% confidence intervals (Wald)
    se_cl = float(np.sqrt(K_cl * (1 - K_cl) / N_RUNS))
    se_q  = float(np.sqrt(K_q  * (1 - K_q)  / N_RUNS))

    return {
        "K_cl":       round(K_cl,     4),
        "K_q":        round(K_q,      4),
        "delta_K":    round(K_q - K_cl, 4),
        "mean_delta": round(float(np.mean(deltas)), 4),
        "se_cl":      round(se_cl,    4),
        "se_q":       round(se_q,     4),
    }


def main() -> None:
    print("=" * 70)
    print(f"Alpha sweep: α ∈ {ALPHA_VALUES}")
    print(f"N = {N_RUNS} runs per point | T = {T_STEPS} steps | δ = {DELTA}")
    print(f"Regime: MARGINAL (shocks calibrated for K_cl ≈ 0.5–0.7 at α=0)")
    print("=" * 70)

    results: dict = {
        "alpha_values": ALPHA_VALUES,
        "T_steps": T_STEPS,
        "N_runs": N_RUNS,
        "delta": DELTA,
        "note": (
            "Marginal regime: T_steps=7, S3 shock=0.25, S4 shock=0.20. "
            "Chosen so K_cl(alpha=0) ∈ [0.5, 0.7] — the range where "
            "supply-chain degradation (alpha>0) has a measurable dampening effect."
        ),
        "scenarios": {},
    }
    rows_csv: list[str] = ["alpha,scenario,K_cl,K_q,delta_K,mean_delta,se_cl,se_q"]

    for sc_name, sc in SCENARIOS.items():
        print(f"\n{'─'*70}")
        print(f"Scenario: {sc_name}  (initiator={sc['initiator']}, "
              f"shock={sc['shock'].tolist()})")
        print(f"{'α':>6}  {'K_cl':>8}  {'K_q':>8}  {'ΔK':>8}  "
              f"{'mean_Δx':>10}  {'SE_cl':>7}")
        print(f"{'─'*6}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*10}  {'─'*7}")

        sc_results: list[dict] = []
        for alpha in ALPHA_VALUES:
            res = run_mc(alpha=float(alpha), scenario=sc, sc_name=sc_name)
            sc_results.append({"alpha": alpha, **res})
            rows_csv.append(
                f"{alpha},{sc_name},{res['K_cl']},"
                f"{res['K_q']},{res['delta_K']},{res['mean_delta']},"
                f"{res['se_cl']},{res['se_q']}"
            )
            print(f"{alpha:>6.0f}  {res['K_cl']:>8.4f}  {res['K_q']:>8.4f}  "
                  f"{res['delta_K']:>8.4f}  {res['mean_delta']:>10.4f}  "
                  f"{res['se_cl']:>7.4f}")

        results["scenarios"][sc_name] = sc_results

    # ---- Save ----
    out_dir = REPO_ROOT / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "alpha_sweep.json"
    csv_path  = out_dir / "alpha_sweep.csv"

    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    csv_path.write_text("\n".join(rows_csv) + "\n", encoding="utf-8")

    print(f"\n[save] {json_path}")
    print(f"[save] {csv_path}")

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("SUMMARY — Effect of dynamic A(t) on cascade probabilities")
    print("=" * 70)
    for sc_name, sc_rows in results["scenarios"].items():
        kcl_alpha0 = sc_rows[0]["K_cl"]
        kq_alpha0  = sc_rows[0]["K_q"]
        kcl_max    = max(r["K_cl"] for r in sc_rows)
        kcl_min    = min(r["K_cl"] for r in sc_rows)
        direction  = "dampens ↓" if kcl_min < kcl_alpha0 else "amplifies ↑"
        # Best dampening: largest reduction at any α
        best_damp = kcl_alpha0 - kcl_min
        print(f"  {sc_name}:")
        print(f"    K_cl(α=0)={kcl_alpha0:.4f}  range=[{kcl_min:.4f}, {kcl_max:.4f}]  "
              f"→ {direction}  (max ΔK_cl = {best_damp:.4f})")
        print(f"    K_q(α=0)={kq_alpha0:.4f}")


if __name__ == "__main__":
    main()
