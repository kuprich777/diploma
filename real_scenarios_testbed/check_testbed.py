"""
Шаг 0: Проверка доступности микросервисного стенда.

Проверяет:
  - GET http://localhost:8004/api/v1/risk/state
  - GET http://localhost:8004/api/v1/risk/dependency_matrix
  - GET http://localhost:8004/api/v1/risk/classical_threshold
  - GET http://localhost:8005/api/v1/scenarios/catalog

Выводит текущее состояние и подтверждает готовность к прогону.
"""

from __future__ import annotations

import json
import sys

import requests

BASE_RISK = "http://localhost:8004/api/v1/risk"
BASE_SIM  = "http://localhost:8005/api/v1/simulator"
TIMEOUT   = 10


def check(label: str, url: str) -> dict | None:
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        print(f"  ✓ {label}: OK  ({url})")
        return data
    except requests.ConnectionError:
        print(f"  ✗ {label}: ConnectionError  ({url})")
        return None
    except requests.HTTPError as e:
        print(f"  ✗ {label}: HTTP {e.response.status_code}  ({url})")
        return None
    except Exception as e:
        print(f"  ✗ {label}: {e}  ({url})")
        return None


def main() -> None:
    print("=" * 60)
    print("  Проверка микросервисного стенда")
    print("=" * 60)

    state       = check("risk/current",             f"{BASE_RISK}/current")
    matrix      = check("risk/dependency_matrix",  f"{BASE_RISK}/dependency_matrix")
    threshold   = check("risk/classical_threshold", f"{BASE_RISK}/classical_threshold")
    catalog     = check("simulator/catalog",        f"{BASE_SIM}/catalog")

    print()

    if state is None and matrix is None:
        print("  ✗ Стенд недоступен.")
        print()
        print("  Для запуска стенда выполните:")
        print("    cd diploma")
        print("    docker-compose up -d")
        print("    sleep 30")
        print("    python real_scenarios_testbed/check_testbed.py")
        sys.exit(1)

    # --- Вывод текущего состояния ---
    print("  Текущий вектор рисков (risk_engine):")
    if isinstance(state, dict):
        for k, v in state.items():
            if isinstance(v, (int, float)):
                print(f"    {k}: {v:.4f}")

    if matrix is not None:
        print()
        print("  Матрица A (dependency_matrix):")
        mat = matrix if isinstance(matrix, list) else matrix.get("matrix", matrix)
        if isinstance(mat, list):
            labels = ["energy", "water", "transport"]
            print(f"    {'':>12}" + "".join(f"  {l:>12}" for l in labels))
            for i, row in enumerate(mat):
                if isinstance(row, list):
                    vals = "".join(f"  {v:>12.4f}" for v in row)
                    print(f"    {labels[i]:>12}{vals}")
        # Быстрая проверка совпадения с ожидаемой A v1.0
        expected = [[0.0, 0.2, 0.3], [0.4, 0.0, 0.2], [0.5, 0.3, 0.0]]
        flat_mat = mat if isinstance(mat, list) and isinstance(mat[0], list) else None
        if flat_mat:
            ok = all(
                abs(flat_mat[i][j] - expected[i][j]) < 0.01
                for i in range(3) for j in range(3)
            )
            print()
            print(f"  Матрица соответствует A v1.0: {'✓ ДА' if ok else '✗ НЕТ (ожидается [[0,0.2,0.3],[0.4,0,0.2],[0.5,0.3,0]])'}")

    if threshold is not None:
        # threshold response: {"theta_bin": 0.7, ...} or scalar
        if isinstance(threshold, dict):
            theta = threshold.get("theta_bin", threshold.get("theta", threshold.get("value")))
        else:
            theta = threshold
        print()
        print(f"  θ_node (бинаризация): {theta}")
        if isinstance(theta, (int, float)):
            ok_theta = abs(float(theta) - 0.70) < 0.01
            print(f"  θ_node = 0.70: {'✓' if ok_theta else f'✗ (текущее: {theta}, ожидается 0.70)'}")

    if catalog is not None:
        scenarios = catalog if isinstance(catalog, list) else catalog.get("scenarios", [])
        print()
        print(f"  Каталог сценариев ({len(scenarios)} записей):")
        for sc in scenarios[:6]:
            sid = sc.get("scenario_id", sc.get("id", "?"))
            print(f"    • {sid}")

    print()
    all_ok = all(x is not None for x in [matrix, threshold])
    if all_ok:
        print("  ✓ Стенд готов к прогону.")
        print("    Следующий шаг: python run_on_testbed.py")
    else:
        print("  ✗ Часть сервисов недоступна. Проверьте docker-compose ps.")
        sys.exit(1)


if __name__ == "__main__":
    main()
