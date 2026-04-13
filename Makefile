.PHONY: up down build test mc optimize plots calibrate

# ── Docker ────────────────────────────────────────────────────────────────────
up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose up -d --build

# ── Tests ──────────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v --tb=short

# ── Calibration ───────────────────────────────────────────────────────────────
calibrate-sigma:
	python scripts/calibrate_sigma.py

calibrate-capacity:
	python scripts/calibrate_capacity.py

calibrate-A:
	python scripts/calibrate_A.py

calibrate: calibrate-A calibrate-sigma calibrate-capacity

# ── Monte Carlo ────────────────────────────────────────────────────────────────
mc:
	python scripts/run_monte_carlo.py

# ── Optimization ──────────────────────────────────────────────────────────────
optimize:
	python scripts/run_optimization.py

# ── Plots ─────────────────────────────────────────────────────────────────────
plots:
	python scripts/generate_plots.py

# ── Validation ────────────────────────────────────────────────────────────────
validate:
	python scripts/validate_historical.py

# ── Baselines ─────────────────────────────────────────────────────────────────
compare:
	python scripts/compare_methods.py
