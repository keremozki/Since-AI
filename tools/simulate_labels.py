"""SIMULATED engineer reviews, to test the confidence model before real labels exist.

Nothing here is a real result. The rows come from a made-up story of how misreads happen, so the
numbers show that the pipeline learns, not how well it will do on Meyer's drawings.

    .venv/Scripts/python tools/simulate_labels.py                  # learning curve + tau table
    .venv/Scripts/python tools/simulate_labels.py --seed-pool ship-data/confidence --n 60
        # writes 60 labels flagged synthetic; the app uses them only with CONFIDENCE_ALLOW_SYNTHETIC=1
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.confidence import (COLD_START_MIN_CONFIDENCE, FEATURE_NAMES, MIN_LABELS, SOURCE_KINDS, TAU,  # noqa: E402
                            LabelPool, cross_validated, new_model, scores_at, to_matrix)

# Made-up story: chance that a fail from this source is a misread, and how sure the reader says it is.
SOURCES = {  # kind: (share of fails, base misread chance, typical confidence)
    "3d_model": (0.35, 0.10, 0.9),
    "document": (0.30, 0.20, 0.85),
    "image": (0.20, 0.50, 0.65),
    "3d_measurement": (0.10, 0.30, 0.7),
    "chat": (0.05, 0.05, 0.9),
}
LABEL_NOISE = 0.05  # engineers sometimes press the wrong button


def simulate(n: int, rng: np.random.Generator) -> list[dict]:
    kinds = list(SOURCES)
    shares = np.array([SOURCES[k][0] for k in kinds])
    rows = []
    for _ in range(n):
        kind = kinds[rng.choice(len(kinds), p=shares / shares.sum())]
        _, base, conf = SOURCES[kind]
        stated = rng.random() < (0.3 if kind == "image" else 0.9)
        scale_known = 1.0 if stated or kind != "image" else float(rng.random() < 0.4)
        unit_text = stated and rng.random() < 0.8
        converted = rng.random() < 0.3
        p_misread = base + (0.0 if stated else 0.25) + (0.0 if scale_known else 0.2) + (0.1 if converted and not unit_text else 0.0)
        misread = rng.random() < min(p_misread, 0.95)
        # A misread mostly lands just under the limit; a real fault is spread further out.
        margin = rng.exponential(0.03) if misread else rng.exponential(0.12) + 0.005
        confidence = float(np.clip(conf + rng.normal(0, 0.1) - (0.15 if misread else 0.0), 0.3, 1.0))
        agree = 1.0 if misread else float(1 + (rng.random() < 0.3))
        label = int(not misread)
        if rng.random() < LABEL_NOISE:
            label = 1 - label
        vector = kind == "document" and rng.random() < 0.7
        ambiguous = vector and rng.random() < (0.5 if misread else 0.05)
        gap = float(rng.exponential(0.4 if misread else 0.15)) if vector else 0.0
        row = {"extraction_confidence": confidence, "margin": float(margin), "scale_known": scale_known,
               "n_sources_agree": agree, "value_is_stated": float(stated), "unit_converted": float(converted),
               "has_unit_text": float(unit_text), "reader_vector": float(vector), "pairing_gap_in": gap,
               "ambiguous_pairing": float(ambiguous), "ocr_text": float(vector and rng.random() < 0.1),
               "from_table": float(vector and rng.random() < 0.2)}
        row.update({f"source_{k}": float(k == kind) for k in SOURCE_KINDS})
        rows.append({"features": row, "label": label})
    return rows


def shown_mask(rows, model, tau):
    """Policy on a batch: low confidence never shown; with a model, P(real) must reach tau."""
    X = to_matrix([r["features"] for r in rows])
    confident = X[:, FEATURE_NAMES.index("extraction_confidence")] >= COLD_START_MIN_CONFIDENCE
    if model is None:
        return confident
    return confident & (model.predict_proba(X)[:, 1] >= tau)


def learning_curve(max_n: int, repeats: int, tau: float, seed: int = 0) -> list[dict]:
    points = {n: [] for n in range(10, max_n + 1, 5)}
    for r in range(repeats):
        rng = np.random.default_rng(seed + r)
        train, test = simulate(max_n, rng), simulate(500, rng)
        y_test = np.array([t["label"] for t in test])
        for n in points:
            rows = train[:n]
            y = np.array([t["label"] for t in rows])
            model = None
            if n >= MIN_LABELS and len(set(y)) == 2:
                model = new_model().fit(to_matrix([t["features"] for t in rows]), y)
            shown = shown_mask(test, model, tau)
            points[n].append(scores_at(y_test, shown.astype(float), 0.5))
    return [{"labels": n, "mode": "model" if n >= MIN_LABELS else "cold_start",
             **{k: float(np.mean([s[k] for s in runs if s[k] is not None])) for k in ("precision", "recall", "false_alarm_rate", "coverage")}}
            for n, runs in points.items()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=60)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--seed-pool", type=Path, help="write --n simulated labels to this confidence folder")
    args = parser.parse_args()

    rng = np.random.default_rng(7)
    rows = simulate(args.n, rng)
    y = np.array([r["label"] for r in rows])
    p_oof = cross_validated(to_matrix([r["features"] for r in rows]), y)
    tau_table = [scores_at(y, p_oof, t) for t in (0.5, 0.6, 0.7, 0.8, 0.9)]
    curve = learning_curve(args.n, args.repeats, TAU)
    model = new_model().fit(to_matrix([r["features"] for r in rows]), y)
    report = {"SIMULATED": True, "warning": "Made-up data. Shows the pipeline learns, not real accuracy.",
              "n_labels": args.n, "real_share": float(y.mean()),
              "tau_cross_validated": tau_table, "learning_curve": curve,
              "weights": dict(zip(FEATURE_NAMES, map(float, model[-1].coef_[0])))}
    out = ROOT / "data" / "reports" / "confidence_simulated.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"SIMULATED: {args.n} labels, {y.mean():.0%} real fails\n")
    print("5-fold CV on the simulated labels (threshold choice):")
    print("  tau  precision  recall  false-alarm  coverage")
    for s in tau_table:
        print(f"  {s['tau']:.1f}  {s['precision'] or 0:9.2f}  {s['recall'] or 0:6.2f}  {s['false_alarm_rate'] or 0:11.2f}  {s['coverage']:8.2f}")
    print(f"\nLearning curve (tau {TAU}, mean of {args.repeats} runs, 500 test fails each):")
    print("  labels  mode        precision  false-alarm  recall")
    for p in curve:
        print(f"  {p['labels']:6d}  {p['mode']:10s}  {p['precision']:9.2f}  {p['false_alarm_rate']:11.2f}  {p['recall']:6.2f}")
    print("\nWeights (scaled features):")
    for name, w in sorted(report["weights"].items(), key=lambda kv: -abs(kv[1])):
        print(f"  {name:24s} {w:+.2f}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        n = [p["labels"] for p in curve]
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.plot(n, [p["false_alarm_rate"] for p in curve], marker="o", label="false-alarm rate")
        ax.plot(n, [p["precision"] for p in curve], marker="s", label="precision")
        ax.plot(n, [p["recall"] for p in curve], marker="^", label="recall")
        ax.axvline(MIN_LABELS, color="grey", linestyle="--", linewidth=1)
        ax.text(MIN_LABELS + 0.5, 0.05, "model starts", color="grey")
        ax.set(xlabel="engineer labels", ylim=(0, 1), title="Confidence gate learning curve (SIMULATED data)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(ROOT / "data" / "reports" / "confidence_learning_curve_SIMULATED.png", dpi=120)
        print("\nChart: data/reports/confidence_learning_curve_SIMULATED.png")
    except ImportError:
        print("\n(matplotlib not installed: no chart)")

    if args.seed_pool:
        pool = LabelPool(args.seed_pool / "labels.jsonl")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for i, r in enumerate(rows):
            pool.add({"key": f"simulated|{i}", "label": r["label"], "decision": "accept" if r["label"] else "reject",
                      "features": r["features"], "rule_id": "SIMULATED", "subject": f"simulated:{i}", "measured": "",
                      "corrected_value": None, "corrected_unit": "", "note": "simulated", "synthetic": True, "created": now})
        print(f"\nWrote {len(rows)} SIMULATED labels to {pool.path}. The app uses them only with CONFIDENCE_ALLOW_SYNTHETIC=1.")


if __name__ == "__main__":
    main()
