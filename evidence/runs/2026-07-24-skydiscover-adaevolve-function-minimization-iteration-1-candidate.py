# EVOLVE-BLOCK-START
"""Function minimization example for OpenEvolve"""
import numpy as np
from scipy.optimize import differential_evolution, minimize


def search_algorithm(iterations=1000, bounds=(-5, 5)):
    """
    Global minimization via differential_evolution (robust to many local minima)
    followed by a Nelder-Mead local polish for high-precision refinement.

    Args:
        iterations: Number of DE iterations (upper bound on generations).
        bounds: Bounds for the search space (min, max).

    Returns:
        Tuple of (best_x, best_y, best_value)
    """
    lo, hi = bounds

    def f(p):
        x, y = p
        return evaluate_function(x, y)

    # Differential evolution explores globally and escapes local minima.
    de = differential_evolution(
        f, [(lo, hi), (lo, hi)], maxiter=iterations, tol=1e-12,
        seed=42, polish=False, init='sobol',
    )

    # Local polish for fine convergence.
    res = minimize(f, de.x, method='Nelder-Mead',
                   options={'xatol': 1e-12, 'fatol': 1e-12})
    best_x, best_y = res.x
    best_value = res.fun

    # Clip to bounds in case the polish drifted slightly outside.
    best_x = float(np.clip(best_x, lo, hi))
    best_y = float(np.clip(best_y, lo, hi))
    best_value = float(evaluate_function(best_x, best_y))

    return best_x, best_y, best_value


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
