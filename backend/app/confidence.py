"""Confidence gate: learns from engineers' reviews which fails are misreads.

The checks still decide every result. This only answers "is this fail real, or did we misread the
drawing?" and can turn a fail into can't tell. It never creates a fail and never touches a pass,
a conflict, or a can't tell.

Red lines:
- Trained only on engineers' Accept / Reject / Correct decisions, never on its own predictions.
- Simulated labels are flagged `synthetic`, left out of training unless explicitly allowed, and
  named in every note the model writes.
- Until there are MIN_LABELS labels, a fixed rule applies: low reading confidence gives can't tell.
"""
from __future__ import annotations

import json
import os
import pickle
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .logreg import NumpyLogReg
from .models import Fact, Finding, SourceKind, Status
from .store import FactStore

TAU = 0.7
COLD_START_MIN_CONFIDENCE = 0.7
MIN_LABELS = 30
RETRAIN_EVERY = 5
CONFIDENCE_SCORE = {"high": 0.9, "medium": 0.7, "low": 0.4}
SOURCE_KINDS = [kind.value for kind in SourceKind]
NUMERIC_FEATURES = ["extraction_confidence", "margin", "scale_known", "n_sources_agree",
                    "value_is_stated", "unit_converted", "has_unit_text",
                    # How the drawing reader got the value (backend/app/drawing.py); 0 for other readers.
                    "reader_vector", "pairing_gap_in", "ambiguous_pairing", "ocr_text", "from_table"]
FEATURE_NAMES = NUMERIC_FEATURES + [f"source_{kind}" for kind in SOURCE_KINDS]
DECISION_LABEL = {"accept": 1, "reject": 0, "correct": 0}
LENGTH_AGREE_MM = 10.0
_UNIT_TEXT = re.compile(r"(\d\s*(mm|cm|m|in|inch|ft|feet)\b|[\"'″′])", re.IGNORECASE)
_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}


# ---------- features ----------

def extraction_confidence(finding: Finding) -> float:
    facts = finding.evidence.facts if finding.evidence else []
    return min((CONFIDENCE_SCORE.get(f.confidence, 0.4) for f in facts), default=0.4)


def _agrees(a: Fact, b: Fact) -> bool:
    try:
        if a.unit.lower() in _TO_MM and b.unit.lower() in _TO_MM:
            return abs(float(a.value) * _TO_MM[a.unit.lower()] - float(b.value) * _TO_MM[b.unit.lower()]) <= LENGTH_AGREE_MM
        return float(a.value) == float(b.value)
    except (TypeError, ValueError):
        return str(a.value).strip().lower() == str(b.value).strip().lower()


def features(finding: Finding, store: FactStore | None = None) -> dict[str, float]:
    """One row for one fail. Needs the evidence the check attached."""
    evidence = finding.evidence
    if evidence is None or not evidence.facts or evidence.limit == 0:
        raise ValueError(f"No evidence on {finding.rule_id} {finding.subject}")
    basis = evidence.facts[0]
    quote = basis.source.quote or ""
    stated = bool(re.search(r"\d", quote))
    same = store.get(basis.subject, basis.property) if store else [basis]
    meta = basis.meta or {}
    # A picture with no dimension text was read off the drawing, so its scale matters.
    scale_known = 0.0 if basis.source.kind == SourceKind.IMAGE and not stated else 1.0
    row = {
        "extraction_confidence": extraction_confidence(finding),
        "margin": abs(evidence.measured - evidence.limit) / abs(evidence.limit),
        "scale_known": float(meta.get("scale_known", scale_known)),
        "n_sources_agree": float(max(1, sum(_agrees(basis, other) for other in same)) + bool(meta.get("readers_agree"))),
        "value_is_stated": float(stated),
        "unit_converted": float(bool(evidence.limit_unit) and basis.unit.lower() != evidence.limit_unit.lower()),
        "has_unit_text": float(meta.get("unit_written", bool(_UNIT_TEXT.search(quote)))),
        "reader_vector": float(meta.get("reader") == "vector"),
        "pairing_gap_in": float(meta.get("pairing_gap_in", 0.0)),
        "ambiguous_pairing": float(bool(meta.get("ambiguous_pairing"))),
        "ocr_text": float(bool(meta.get("ocr_text"))),
        "from_table": float(bool(meta.get("from_table"))),
    }
    for kind in SOURCE_KINDS:
        row[f"source_{kind}"] = float(basis.source.kind.value == kind)
    return row


def to_matrix(rows: list[dict]) -> np.ndarray:
    return np.array([[float(row[name]) for name in FEATURE_NAMES] for row in rows], dtype=float)


def review_key(finding: Finding) -> str:
    return f"{finding.rule_id}|{finding.subject}|{finding.measured}"


# ---------- policy ----------

def shown_status(status: Status, confidence: float, p_real: float | None, tau: float = TAU) -> tuple[Status, str]:
    """What the engineer sees. Only a fail can change, and only to can't tell."""
    if status != Status.FAIL:
        return status, ""
    if confidence < COLD_START_MIN_CONFIDENCE:
        return Status.CANT_TELL, f"Reading confidence is low ({confidence:.2f}), so this fail isn't shown until the value is confirmed."
    if p_real is not None and p_real < tau:
        return Status.CANT_TELL, f"Looks like earlier misreads: P(real) = {p_real:.2f}, under the {tau:.2f} threshold."
    return Status.FAIL, ""


# ---------- labels ("the pool") ----------

class LabelPool:
    def __init__(self, path: Path):
        self.path = path

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def add(self, row: dict) -> None:
        """A second review of the same finding replaces the first, so one finding counts once."""
        rows = [r for r in self.rows() if r["key"] != row["key"]] + [row]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def make_label(finding: Finding, store: FactStore, decision: str, *, synthetic: bool = False,
               corrected_value: float | None = None, corrected_unit: str = "", note: str = "") -> dict:
    if decision not in DECISION_LABEL:
        raise ValueError(f"Unknown decision: {decision}. Use accept, reject, or correct.")
    if decision == "correct" and corrected_value is None:
        raise ValueError("A correction needs the corrected value.")
    return {
        "key": review_key(finding), "label": DECISION_LABEL[decision], "decision": decision,
        "features": features(finding, store), "rule_id": finding.rule_id, "subject": finding.subject,
        "measured": finding.measured, "corrected_value": corrected_value, "corrected_unit": corrected_unit,
        "note": note, "synthetic": synthetic, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------- model ----------

def new_model():
    """scikit-learn by default; CONFIDENCE_ENGINE=numpy uses the from-scratch version (same optimum, C = 1/lambda)."""
    if os.environ.get("CONFIDENCE_ENGINE") == "numpy":
        return NumpyLogReg(C=0.5, class_weight="balanced")
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, class_weight="balanced", max_iter=1000))


def scores_at(y: np.ndarray, p: np.ndarray, tau: float) -> dict:
    shown = p >= tau
    tp, fp = int(np.sum(shown & (y == 1))), int(np.sum(shown & (y == 0)))
    fn, tn = int(np.sum(~shown & (y == 1))), int(np.sum(~shown & (y == 0)))
    return {"tau": tau, "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
            "false_alarm_rate": fp / (fp + tn) if fp + tn else None, "coverage": float(shown.mean()) if len(p) else None,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def cross_validated(X: np.ndarray, y: np.ndarray, seed: int = 0) -> np.ndarray | None:
    """Out-of-fold P(real) for every label, or None when a class has too few labels to split."""
    smallest = int(min(np.sum(y == 0), np.sum(y == 1)))
    if smallest < 2:
        return None
    folds = StratifiedKFold(n_splits=min(5, smallest), shuffle=True, random_state=seed)
    return cross_val_predict(new_model(), X, y, cv=folds, method="predict_proba")[:, 1]


class ConfidenceGate:
    def __init__(self, directory: Path, tau: float = TAU, min_labels: int = MIN_LABELS,
                 retrain_every: int = RETRAIN_EVERY, allow_synthetic: bool = False):
        self.directory = directory
        self.tau, self.min_labels, self.retrain_every = tau, min_labels, retrain_every
        self.allow_synthetic = allow_synthetic
        self.pool = LabelPool(directory / "labels.jsonl")
        self.meta_file = directory / "meta.json"
        self.meta: dict | None = None
        self.model = None
        self._load()

    def _load(self) -> None:
        if not self.meta_file.exists():
            return
        meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
        # A model fitted on simulated labels must not run once they are no longer allowed.
        if meta.get("n_synthetic") and not self.allow_synthetic:
            return
        self.meta = meta
        self.model = pickle.loads((self.directory / meta["model_file"]).read_bytes())

    def training_rows(self) -> list[dict]:
        return [r for r in self.pool.rows() if self.allow_synthetic or not r.get("synthetic")]

    def record(self, row: dict) -> bool:
        """Store one engineer decision, then retrain if it's time. Returns whether it retrained."""
        self.pool.add(row)
        return self.maybe_retrain()

    def maybe_retrain(self) -> bool:
        rows = self.training_rows()
        if len(rows) < self.min_labels:
            return False
        if self.meta and len(rows) - self.meta["n_labels"] < self.retrain_every:
            return False
        return self.train(rows)

    def train(self, rows: list[dict]) -> bool:
        y = np.array([r["label"] for r in rows])
        if len(set(y.tolist())) < 2:
            return False  # all accepts or all rejects: nothing to separate yet
        X = to_matrix([r["features"] for r in rows])
        model = new_model().fit(X, y)
        p_oof = cross_validated(X, y)
        version = (self.meta or {}).get("version", 0) + 1
        model_file = f"models/v{version}.pkl"
        (self.directory / "models").mkdir(parents=True, exist_ok=True)
        (self.directory / model_file).write_bytes(pickle.dumps(model))
        coefs = model[-1].coef_[0]
        self.meta = {
            "version": version, "model_file": model_file, "n_labels": len(rows),
            "n_synthetic": sum(bool(r.get("synthetic")) for r in rows), "n_real": sum(r["label"] == 1 for r in rows),
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tau": self.tau,
            "features": FEATURE_NAMES, "weights": dict(zip(FEATURE_NAMES, map(float, coefs))),
            "cv": None if p_oof is None else [scores_at(y, p_oof, t) for t in (0.5, 0.6, 0.7, 0.8, 0.9)],
        }
        self.meta_file.write_text(json.dumps(self.meta, indent=2), encoding="utf-8")
        self.model = model
        return True

    def p_real(self, row: dict) -> float | None:
        if self.model is None:
            return None
        return float(self.model.predict_proba(to_matrix([row]))[0, 1])

    def _source_note(self) -> str:
        if not self.meta:
            return ""
        note = f"model v{self.meta['version']}, {self.meta['n_labels']} labels"
        if self.meta["n_synthetic"]:
            note += f", {self.meta['n_synthetic']} of them SIMULATED"
        return f" ({note})"

    def apply(self, findings: list[Finding], store: FactStore) -> list[Finding]:
        gated = []
        for finding in findings:
            if finding.status != Status.FAIL or finding.evidence is None or not finding.evidence.facts:
                gated.append(finding)
                continue
            row = features(finding, store)
            p = self.p_real(row)
            status, reason = shown_status(finding.status, row["extraction_confidence"], p, self.tau)
            update = {"original_status": Status.FAIL, "p_real": p, "reviewable": True}
            if status != finding.status:
                update.update(status=status, gate_note=reason + (self._source_note() if p is not None else ""),
                              question=f"Check {finding.measured} against the drawing. Is this fail real?")
            gated.append(finding.model_copy(update=update))
        return gated

    def status(self) -> dict:
        rows = self.pool.rows()
        used = self.training_rows()
        return {
            "mode": "model" if self.model is not None else "cold_start",
            "tau": self.tau, "min_labels": self.min_labels, "retrain_every": self.retrain_every,
            "labels_total": len(rows), "labels_synthetic": sum(bool(r.get("synthetic")) for r in rows),
            "labels_used": len(used), "allow_synthetic": self.allow_synthetic,
            "labels_until_model": max(0, self.min_labels - len(used)) if self.model is None else 0,
            "model": self.meta,
        }
