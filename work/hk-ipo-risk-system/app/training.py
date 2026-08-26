from __future__ import annotations

from dataclasses import dataclass

from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


@dataclass(frozen=True)
class Candidate:
    name: str
    estimator: object


def model_candidates() -> list[Candidate]:
    output = []
    for c_value in (0.01, 0.1, 1.0, 10.0):
        for class_weight in (None, "balanced"):
            suffix = "plain" if class_weight is None else "balanced"
            output.append(
                Candidate(
                    f"logistic_c{c_value:g}_{suffix}",
                    make_pipeline(
                        StandardScaler(),
                        LogisticRegression(
                            C=c_value,
                            class_weight=class_weight,
                            max_iter=4000,
                            random_state=17,
                        ),
                    ),
                )
            )
    for leaves in (7, 15):
        for regularization in (1.0, 10.0):
            output.append(
                Candidate(
                    f"hist_l{leaves}_r{regularization:g}",
                    HistGradientBoostingClassifier(
                        learning_rate=0.05,
                        max_iter=300,
                        max_leaf_nodes=leaves,
                        l2_regularization=regularization,
                        random_state=17,
                    ),
                )
            )
    output.append(
        Candidate(
            "forest",
            RandomForestClassifier(
                n_estimators=500,
                max_features="sqrt",
                min_samples_leaf=8,
                class_weight="balanced_subsample",
                n_jobs=-1,
                random_state=17,
            ),
        )
    )
    return output
