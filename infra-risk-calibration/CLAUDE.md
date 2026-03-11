# Project purpose
This repository calibrates dependency matrix v1.0 and scenario parameters for an infrastructure-risk stand using real outage data.

# Scientific scope
- Preserve the current 3-sector mapping: energy, water, transport.
- Preserve the current research logic: compare a classical threshold baseline vs a quantitative propagation model.
- Do not redefine the research hypothesis unless explicitly asked.
- Treat calibration as a support layer for the existing stand, not as a redesign of the methodology.

# Data policy
- Prefer official or primary data sources.
- Record provenance for every downloaded or derived dataset.
- Never silently impute missing values. Document every imputation rule.
- Mark proxy variables explicitly, especially for water-sector outage estimation.

# Engineering workflow
- For any multi-file task, inspect first, then produce a short plan, then implement.
- After implementation, run focused tests and report what passed and what remains uncertain.
- Save all major outputs in machine-readable form under outputs/ and data/processed/.
- Keep notebooks exploratory; move reusable logic into src/.

# Output requirements
- Code, filenames, commit messages, and tests: English.
- Research notes, summaries, and interpretation: Russian, academic style.
- Every quantitative conclusion must state:
  - formula or metric,
  - units,
  - date range,
  - sample size,
  - limitations.

# Deliverables
Preferred deliverables:
- cleaned parquet/csv datasets
- calibration tables
- figures for the stand
- JSON/YAML export for stand integration
- concise markdown memo with assumptions and limitations