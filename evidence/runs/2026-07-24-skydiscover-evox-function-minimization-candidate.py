# EVOLVE-BLOCK-START
"""Function minimization example for OpenEvolve"""
import numpy as np
from scipy.optimize import differential_evolution, minimize


def search_algorithm(iterations=1000, bounds=(-5, 5)):
    """Global optimization via differential evolution + multi-start local refinement."""
    bnd = (bounds[0], bounds[1])
    # Global search with differential evolution
    res = differential_evolution(
        lambda p: evaluate_function(p[0], p[1]), [bnd, bnd],
        maxiter=300, seed=42, tol=1e-14, mutation=(0.4, 1.2),
        recombination=0.85, popsize=25, polish=True, init='sobol'
    )
    best_x, best_y, best_val = res.x[0], res.x[1], res.fun
    # Multi-start local refinement from DE result and diverse grid seeds
    starts = [res.x] + [np.array([i, j]) for i in np.linspace(-4, 4, 5)
                        for j in np.linspace(-4, 4, 5)]
    for s in starts:
        try:
            r = minimize(lambda p: evaluate_function(p[0], p[1]), s,
                         method='Nelder-Mead',
                         options={'xatol': 1e-12, 'fatol': 1e-12, 'maxiter': 3000})
            if r.fun < best_val:
                best_x, best_y, best_val = r.x[0], r.x[1], r.fun
        except Exception:
            pass
    return best_x, best_y, best_val


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
