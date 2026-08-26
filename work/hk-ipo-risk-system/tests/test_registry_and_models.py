from __future__ import annotations

import json

import numpy as np
import pytest

from app.calibration import PriorShiftCalibratedClassifier
from app.model_registry import ModelRegistry
from app.prompts import PromptRegistry


def test_prompt_registry_contains_all_thirteen_agents():
    registry = PromptRegistry()
    public = registry.public_registry()
    assert len(public) == 13
    assert registry.global_system_prompt
    assert all(registry.get(item["name"]).system_prompt for item in public)


def test_report_agent_is_last_in_predict_dag():
    registry = PromptRegistry()
    report = registry.get("REPORT_GENERATION_AGENT")
    assert "RISK_MODEL_AGENT" in report.depends_on


class _LinearProbabilityEstimator:
    def predict_proba(self, features):
        probability = np.asarray(features, dtype=float)[:, 0]
        return np.column_stack((1 - probability, probability))


def test_prior_shift_calibration_preserves_ranking():
    features = np.array([[0.1], [0.2], [0.7], [0.9]])
    calibrator = PriorShiftCalibratedClassifier(_LinearProbabilityEstimator()).fit(
        features, np.array([0, 1, 1, 1])
    )

    calibrated = calibrator.predict_proba(features)[:, 1]

    assert np.all(np.diff(calibrated) > 0)
    assert calibrated.mean() == pytest.approx(0.75, abs=1e-6)


def test_registry_ignores_rejected_model_metadata(tmp_path):
    rejected = tmp_path / "rejected-v1"
    rejected.mkdir()
    (rejected / "metadata.json").write_text(
        json.dumps({"registration_status": "rejected"}), encoding="utf-8"
    )
    (rejected / "bundle.joblib").write_bytes(b"not-loaded")

    assert ModelRegistry(tmp_path).versions() == []
