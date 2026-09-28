from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import pandas as pd

from .models import Contributor, Probabilities


HORIZONS = {
    "p_1d_break": "y_1d_break",
    "p_5d_drop": "y_5d_drop",
    "p_20d_drop": "y_20d_drop",
    "p_60d_drop": "y_60d_drop",
}


class ModelRegistry:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def versions(self) -> list[str]:
        versions = []
        for item in self.root.iterdir():
            metadata_path = item / "metadata.json"
            if not item.is_dir() or not metadata_path.exists() or not (item / "bundle.joblib").exists():
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if metadata.get("registration_status") == "passed":
                versions.append(item.name)
        return sorted(versions)

    def status(self) -> dict:
        versions = self.versions()
        return {
            "available": bool(versions),
            "versions": versions,
            "latest": versions[-1] if versions else None,
            "policy": "未注册且校准通过的模型时，概率必须为 null。",
        }

    def predict(self, features: dict[str, float], requested_version: str | None = None):
        versions = self.versions()
        if not versions:
            return None
        version = requested_version or versions[-1]
        model_dir = self.root / version
        if version not in versions:
            return None
        metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
        bundle = joblib.load(model_dir / "bundle.joblib")
        feature_names = metadata["feature_names"]
        if any(name not in features for name in feature_names):
            return None
        raw_values = [float(features[name]) for name in feature_names]
        row = pd.DataFrame([raw_values], columns=feature_names)
        values = {}
        for probability_name in HORIZONS:
            estimator = bundle[probability_name]
            values[probability_name] = float(estimator.predict_proba(row)[0, 1])
        probabilities = Probabilities(**values)
        primary = probabilities.p_5d_drop
        level = next(
            item["name"]
            for item in metadata["calibration_policy"]["levels"]
            if float(item["minimum"]) <= primary < float(item["maximum"])
        )
        contributors: list[Contributor] = []
        estimator = bundle["p_5d_drop"]
        base = getattr(estimator, "estimator", estimator)
        contribution_values = [raw_values]
        coefficient_model = base
        if hasattr(base, "steps"):
            transformer = base[:-1]
            coefficient_model = base.steps[-1][1]
            contribution_values = transformer.transform(row)
        coefficients = getattr(coefficient_model, "coef_", None)
        if coefficients is not None:
            pairs = sorted(
                zip(feature_names, raw_values, contribution_values[0], coefficients[0]),
                key=lambda item: abs(item[2] * item[3]),
                reverse=True,
            )[:8]
            contributors = [
                Contributor(feature=name, value=raw_value, contribution=float(model_value * coefficient))
                for name, raw_value, model_value, coefficient in pairs
            ]
        snapshot = hashlib.sha256(json.dumps(features, sort_keys=True).encode("utf-8")).hexdigest()
        return {
            "version": version,
            "calibration_version": metadata["calibration_version"],
            "probabilities": probabilities,
            "risk_score": round(primary * 100, 2),
            "risk_level": level,
            "contributors": contributors,
            "feature_snapshot_id": f"feature_{snapshot}",
        }


def assert_frozen_prediction(original: dict, proposed: dict) -> None:
    immutable = ("prediction_as_of", "feature_snapshot_id", "model_version", "probabilities")
    changed = [key for key in immutable if original.get(key) != proposed.get(key)]
    if changed:
        raise ValueError(f"frozen prediction fields cannot be modified in EVALUATE: {changed}")
