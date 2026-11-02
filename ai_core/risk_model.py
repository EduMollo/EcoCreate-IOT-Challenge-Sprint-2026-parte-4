"""
C2 — Modelo preditivo de risco (scikit-learn)

Dois modelos, dois papéis:

  IsolationForest (não supervisionado)
      Treinado só com telemetria NORMAL. Aprende "como é o normal" e
      pontua o quanto a janela recente foge disso. Não precisa de rótulo
      — funciona desde o primeiro dia (cold start honesto).

  RandomForest (supervisionado)
      Treinado em episódios rotulados (sintéticos, seed fixa) para estimar
      P(precisa de atenção veterinária em 7 dias). Comparado a uma
      Regressão Logística como baseline. Explicável via feature importance.

  risk_score = 100 * (0.65 * P_atenção + 0.35 * anomalia)

Por que não LLM aqui: dado tabular, saída calibrada, reproduzível e
auditável. Um LLM seria caro, lento, não determinístico e impossível de
avaliar com matriz de confusão.

Uso:  python -m ai_core.risk_model train
"""

import json
import hashlib
import sklearn
import os
import sys
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURE_LABELS, FEATURE_ORDER, TELEMETRY_FEATURES, to_vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAINED_DIR = os.path.join(ROOT, "ai_core", "trained")
MODEL_PATH = os.path.join(TRAINED_DIR, "risk_model.joblib")
METRICS_PATH = os.path.join(TRAINED_DIR, "metrics.json")
DATASET_PATH = os.path.join(ROOT, "data", "training_dataset.csv")
LABEL = "needs_attention_7d"

W_PROB, W_ANOM = 0.65, 0.35
LEVELS = [(80, "Crítico"), (60, "Alto"), (30, "Moderado"), (0, "Baixo")]


def risk_level(score: float) -> str:
    for cut, name in LEVELS:
        if score >= cut:
            return name
    return "Baixo"


# ─── Treino ───────────────────────────────────────────────────────────────────
def _metrics(y_true, y_pred, y_prob) -> dict:
    cm = confusion_matrix(y_true, y_pred).tolist()
    return {
        "accuracy": round(accuracy_score(y_true, y_pred), 4),
        "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
        "recall": round(recall_score(y_true, y_pred, zero_division=0), 4),
        "f1": round(f1_score(y_true, y_pred, zero_division=0), 4),
        "roc_auc": round(roc_auc_score(y_true, y_prob), 4),
        "confusion_matrix": {"tn": cm[0][0], "fp": cm[0][1], "fn": cm[1][0], "tp": cm[1][1]},
    }


def train(dataset_path: str = DATASET_PATH, out_dir: str = TRAINED_DIR, seed: int = 42) -> dict:
    df = pd.read_csv(dataset_path)
    X = df[FEATURE_ORDER].to_numpy(dtype=float)
    y = df[LABEL].to_numpy(dtype=int)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, stratify=y, random_state=seed)

    # Baseline linear
    logreg = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced"))
    logreg.fit(X_tr, y_tr)
    lr_prob = logreg.predict_proba(X_te)[:, 1]

    # Modelo principal
    clf = RandomForestClassifier(n_estimators=300, max_depth=8, min_samples_leaf=5,
                                 class_weight="balanced", random_state=seed, n_jobs=-1)
    clf.fit(X_tr, y_tr)
    rf_prob = clf.predict_proba(X_te)[:, 1]

    # Detector de anomalia: só telemetria, só linhas normais do treino
    tel_idx = [FEATURE_ORDER.index(f) for f in TELEMETRY_FEATURES]
    X_tel_normal = X_tr[y_tr == 0][:, tel_idx]
    iso = IsolationForest(n_estimators=200, contamination=0.05, random_state=seed)
    iso.fit(X_tel_normal)
    # Normalização: mediana do NORMAL vira 0; percentil 99 de todo o treino vira 1
    raw_normal = -iso.score_samples(X_tel_normal)
    raw_all = -iso.score_samples(X_tr[:, tel_idx])
    q01, q99 = float(np.quantile(raw_normal, 0.50)), float(np.quantile(raw_all, 0.99))
    anom_te = np.clip((-iso.score_samples(X_te[:, tel_idx]) - q01) / max(q99 - q01, 1e-9), 0, 1)

    importances = {f: round(float(w), 4) for f, w in zip(FEATURE_ORDER, clf.feature_importances_)}
    metrics = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": os.path.relpath(dataset_path, ROOT),
        "n_rows": int(len(df)), "n_train": int(len(y_tr)), "n_test": int(len(y_te)),
        "positive_rate": round(float(y.mean()), 4),
        "random_forest": _metrics(y_te, (rf_prob >= 0.5).astype(int), rf_prob),
        "logistic_regression": _metrics(y_te, (lr_prob >= 0.5).astype(int), lr_prob),
        "isolation_forest": {"roc_auc_as_detector": round(roc_auc_score(y_te, anom_te), 4),
                             "contamination": 0.05, "trained_on": int(len(X_tel_normal))},
        "feature_importance": dict(sorted(importances.items(), key=lambda kv: -kv[1])),
        "score_formula": f"risk_score = 100 * ({W_PROB} * P_atencao_7d + {W_ANOM} * anomalia)",
    }

    metrics['dataset_sha256'] = hashlib.sha256(open(dataset_path, 'rb').read()).hexdigest()
    metrics['sklearn_version'] = sklearn.__version__
    metrics['data_origin'] = 'synthetic'
    metrics['seed'] = seed
    metrics['validation_scope'] = 'holdout synthetic episodes; not clinical validation'
    os.makedirs(out_dir, exist_ok=True)
    joblib.dump({"clf": clf, "iso": iso, "feature_order": FEATURE_ORDER, "tel_idx": tel_idx,
                 "anom_q": (q01, q99), "importances": importances, "trained_at": metrics["trained_at"]},
                os.path.join(out_dir, "risk_model.joblib"))
    with open(os.path.join(out_dir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    return metrics


# ─── Explicabilidade ──────────────────────────────────────────────────────────
def _value_text(feature: str, v: float) -> str:
    if feature.endswith("_z"):
        return f"{v:+.1f}σ"
    if feature.endswith("_slope"):
        return f"{v:+.1f}σ na janela"
    if feature == "age_years":
        return f"{v:.1f} anos"
    if feature == "weight_kg":
        return f"{v:.1f} kg"
    if feature == "is_cat":
        return "gato" if v else "cão"
    if feature in ("days_since_last_consult", "vaccine_overdue_days"):
        return f"{v:.0f} dias"
    if feature == "med_adherence_pct":
        return f"{v:.0f}%"
    return f"{v:.2f}"


def _normalized_magnitude(feature: str, v: float) -> float:
    """Quanto o valor 'puxa' para risco, em 0..1 (independente da importância)."""
    if feature.endswith("_z"):
        return min(abs(v), 4.0) / 4.0
    if feature.endswith("_slope"):
        return min(abs(v), 2.0) / 2.0
    if feature == "vaccine_overdue_days":
        return min(v, 120.0) / 120.0
    if feature == "med_adherence_pct":
        return max(0.0, 100.0 - v) / 100.0
    if feature == "days_since_last_consult":
        return min(v, 730.0) / 730.0
    if feature == "age_years":
        return 1.0 if v >= 8 else 0.5 if v < 1 else 0.0
    return 0.0


def explain(features: dict, importances: dict, k: int = 4) -> list[dict]:
    rows = []
    for f in FEATURE_ORDER:
        v = float(features.get(f, 0.0) or 0.0)
        mag = _normalized_magnitude(f, v)
        contrib = importances.get(f, 1.0 / len(FEATURE_ORDER)) * mag
        if contrib > 0.01:
            rows.append({"feature": f, "label": FEATURE_LABELS[f], "value": round(v, 3),
                         "value_text": _value_text(f, v), "weight": round(contrib, 4)})
    rows.sort(key=lambda r: -r["weight"])
    return rows[:k]


# ─── Inferência ───────────────────────────────────────────────────────────────
class RiskModel:
    def __init__(self, bundle: dict):
        self.clf = bundle["clf"]
        self.iso = bundle["iso"]
        self.tel_idx = bundle["tel_idx"]
        self.q01, self.q99 = bundle["anom_q"]
        self.importances = bundle["importances"]
        self.trained_at = bundle.get("trained_at")

    @classmethod
    def load(cls, path: str = MODEL_PATH) -> "RiskModel":
        return cls(joblib.load(path))

    def predict(self, features: dict) -> dict:
        x = np.array([to_vector(features)])
        prob = float(self.clf.predict_proba(x)[0][1])
        raw = float(-self.iso.score_samples(x[:, self.tel_idx])[0])
        anom = float(np.clip((raw - self.q01) / max(self.q99 - self.q01, 1e-9), 0, 1))
        score = round(100 * (W_PROB * prob + W_ANOM * anom), 1)
        return {
            "risk_score": score,
            "risk_level": risk_level(score),
            "prob_attention_7d": round(prob, 3),
            "anomaly_score": round(anom, 3),
            "top_factors": explain(features, self.importances),
            "mode": "model",
        }


def heuristic_predict(features: dict) -> dict:
    """Fallback sem modelo treinado: só z-scores e regras simples. Explícito e conservador."""
    zs = [abs(float(features.get(f, 0.0) or 0.0)) for f in ("temp_z", "hr_z", "spo2_z", "act_z")]
    zmax = max(zs) if zs else 0.0
    n_alt = sum(1 for z in zs if z >= 1.5)
    score = min(100.0, 30 * zmax / 2.5 + 12 * n_alt)
    score += min(15.0, float(features.get("vaccine_overdue_days", 0) or 0) / 6)
    score += min(15.0, max(0.0, 100 - float(features.get("med_adherence_pct", 100) or 100)) / 4)
    score = round(min(100.0, score), 1)
    uniform = {f: 1.0 / len(FEATURE_ORDER) for f in FEATURE_ORDER}
    return {
        "risk_score": score, "risk_level": risk_level(score),
        "prob_attention_7d": round(score / 100, 3), "anomaly_score": round(min(1.0, zmax / 4), 3),
        "top_factors": explain(features, uniform), "mode": "heuristic",
    }


def load_or_none() -> RiskModel | None:
    try:
        return RiskModel.load()
    except (FileNotFoundError, OSError, KeyError):
        return None


def load_metrics() -> dict | None:
    try:
        with open(METRICS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "train":
        m = train()
        rf = m["random_forest"]
        print(f"RandomForest  acc={rf['accuracy']:.3f}  prec={rf['precision']:.3f}  "
              f"rec={rf['recall']:.3f}  f1={rf['f1']:.3f}  auc={rf['roc_auc']:.3f}")
        lr = m["logistic_regression"]
        print(f"LogReg (base) acc={lr['accuracy']:.3f}  f1={lr['f1']:.3f}  auc={lr['roc_auc']:.3f}")
        print(f"IsolationForest AUC como detector: {m['isolation_forest']['roc_auc_as_detector']:.3f}")
        print("Top features:", list(m["feature_importance"].items())[:5])
        print(f"Salvo em {MODEL_PATH}")
    else:
        print("Uso: python -m ai_core.risk_model train")
