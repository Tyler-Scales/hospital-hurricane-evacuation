"""Fixed scaling constants for the FSIP models.

Continuous predictors are divided by the standard deviation observed in the primary
analysis sample (2004-2025 sheltering pairs outside levee protection, complete data),
so one unit means the same thing in every model and subset: for hospital size
(log(1+beds)) one unit is exp(SD) ~ 2.5-fold in beds; for storm intensity one unit is
SD_VM knots. Centering uses each sample's own mean, which does not change odds ratios.
"""
import numpy as np, pandas as pd

def primary_scales(base):
    """base: DataFrame of the primary sample with columns lb, vm and optionally lr, age, el."""
    out = {}
    for c in ('lb', 'vm', 'lr', 'age', 'el'):
        if c in base.columns:
            v = pd.to_numeric(base[c], errors='coerce').dropna()
            if len(v) > 2: out[c] = float(v.std())
    return out

def standardize(X, preds, scales):
    for c in preds:
        if X[c].nunique() > 2:
            X[c] = (X[c] - X[c].mean()) / scales.get(c, X[c].std())
    return X
