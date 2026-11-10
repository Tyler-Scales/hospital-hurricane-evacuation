"""Firth's penalized-likelihood logistic regression (Jeffreys-prior penalty).

Reduces small-sample bias in maximum-likelihood odds ratios. Maximizes the
penalized log-likelihood  l(b) + 0.5 * log det I(b)  by Newton-Raphson on the
modified score (Firth 1993, Biometrika 80:27-38), with step halving on the
penalized objective. Standard errors are Wald standard errors from the inverse
Fisher information X'WX evaluated at the penalized estimates, the convention of
the logistf implementation (Heinze & Schemper 2002); they are NOT derived from
the Hessian of the penalized objective and are not profile penalized-likelihood
intervals. Raises if the iteration does not converge.
"""
import numpy as np


def _penalized_loglik(y, X, beta):
    eta = X @ beta
    p = 1.0 / (1.0 + np.exp(-eta))
    W = p * (1.0 - p)
    ll = float(np.sum(y * eta - np.log1p(np.exp(eta))))
    sign, logdet = np.linalg.slogdet(X.T @ (X * W[:, None]))
    return ll + 0.5 * logdet


def firth_logit(y, X, max_iter=200, tol=1e-8, return_info=False):
    y = np.asarray(y, dtype=float); X = np.asarray(X, dtype=float)
    n, k = X.shape
    beta = np.zeros(k)
    converged = False
    obj = _penalized_loglik(y, X, beta)
    for it in range(1, max_iter + 1):
        eta = X @ beta
        p = 1.0 / (1.0 + np.exp(-eta))
        W = p * (1.0 - p)
        XtWX = X.T @ (X * W[:, None])
        XtWX_inv = np.linalg.pinv(XtWX)
        h = np.einsum("ij,jk,ik->i", X * np.sqrt(W)[:, None], XtWX_inv, X * np.sqrt(W)[:, None])
        U = X.T @ (y - p + h * (0.5 - p))          # modified score
        step = XtWX_inv @ U
        # step halving until the penalized objective does not decrease
        new_obj = _penalized_loglik(y, X, beta + step)
        halvings = 0
        while new_obj < obj - 1e-12 and halvings < 30:
            step /= 2; halvings += 1
            new_obj = _penalized_loglik(y, X, beta + step)
        beta_new = beta + step
        done = np.max(np.abs(beta_new - beta)) < tol
        beta, obj = beta_new, new_obj
        if done:
            converged = True
            break
    if not converged:
        raise RuntimeError(f"Firth iteration did not converge in {max_iter} steps (max |step| {np.max(np.abs(step)):.2e})")
    eta = X @ beta; p = 1.0 / (1.0 + np.exp(-eta)); W = p * (1.0 - p)
    cov = np.linalg.pinv(X.T @ (X * W[:, None]))    # inverse Fisher information at the penalized estimate
    se = np.sqrt(np.diag(cov))
    if return_info:
        return beta, se, {"converged": converged, "iterations": it, "penalized_loglik": obj}
    return beta, se
