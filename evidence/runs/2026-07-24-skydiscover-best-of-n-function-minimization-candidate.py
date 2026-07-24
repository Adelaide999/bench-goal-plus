# EVOLVE-BLOCK-START
"""Function minimization example for OpenEvolve"""
import numpy as np


def search_algorithm(iterations=1000, bounds=(-5, 5)):
    """Use a dense deterministic scan followed by bounded multistart refinement."""
    from scipy.optimize import minimize

    lo, hi = float(bounds[0]), float(bounds[1])
    # A grid avoids the unlucky sampling variance of pure random search.
    n = max(25, min(81, int(np.sqrt(max(625, iterations * 4)))))
    axis = np.linspace(lo, hi, n)
    xx, yy = np.meshgrid(axis, axis, indexing="ij")
    values = np.sin(xx) * np.cos(yy) + np.sin(xx * yy) + (xx * xx + yy * yy) / 20
    flat = values.ravel()
    starts = np.argpartition(flat, -min(24, flat.size))[-min(24, flat.size):]

    best = (float("inf"), lo, lo)
    box = [(lo, hi), (lo, hi)]

    for index in starts:
        i, j = np.unravel_index(index, values.shape)
        result = minimize(
            lambda p: evaluate_function(p[0], p[1]),
            (axis[i], axis[j]),
            method="L-BFGS-B",
            bounds=box,
            options={"maxiter": max(80, iterations // 4), "ftol": 1e-14},
        )
        x, y = float(result.x[0]), float(result.x[1])
        value = float(evaluate_function(x, y))
        if value < best[0]:
            best = (value, x, y)

    return best[1], best[2], best[0]


# EVOLVE-BLOCK-END


# This part remains fixed (not evolved)
def evaluate_function(x, y):
    """The complex function we're trying to minimize"""
    return np.sin(x) * np.cos(y) + np.sin(x * y) + (x**2 + y**2) / 20


def run_search():
    x, y, value = search_algorithm()
    return x, y, value


if __name__ == "__main__":
    x, y, value = run_search()
    print(f"Found minimum at ({x}, {y}) with value {value}")
