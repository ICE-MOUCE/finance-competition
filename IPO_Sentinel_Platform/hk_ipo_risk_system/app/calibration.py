from __future__ import annotations

import numpy as np


class PriorShiftCalibratedClassifier:
    """Calibrate the probability level without reversing model ranking."""

    def __init__(self, estimator, epsilon: float = 1e-6):
        self.estimator = estimator
        self.epsilon = epsilon

    def fit(self, features, labels):
        probability = np.clip(self.estimator.predict_proba(features)[:, 1], self.epsilon, 1 - self.epsilon)
        logits = np.log(probability / (1 - probability))
        target = float(np.asarray(labels, dtype=float).mean())
        low, high = -20.0, 20.0
        for _ in range(100):
            midpoint = (low + high) / 2
            calibrated_mean = float((1 / (1 + np.exp(-(logits + midpoint)))).mean())
            if calibrated_mean < target:
                low = midpoint
            else:
                high = midpoint
        self.intercept_ = (low + high) / 2
        self.classes_ = np.array([0, 1])
        self.calibration_sample_count_ = len(labels)
        return self

    def predict_proba(self, features):
        probability = np.clip(self.estimator.predict_proba(features)[:, 1], self.epsilon, 1 - self.epsilon)
        logits = np.log(probability / (1 - probability)) + self.intercept_
        calibrated = 1 / (1 + np.exp(-logits))
        return np.column_stack((1 - calibrated, calibrated))
