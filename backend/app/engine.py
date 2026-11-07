"""Run the rules in scope against the facts and build the plain-text result."""
from __future__ import annotations

from collections import Counter

from typing import Callable

from .checks import CHECKS, check_consistency, check_drawing_scales, input_findings, unusable_facts
from .models import Finding, Rule, RunResult, ScopeDecision, ShipProfile, Status
from .rules import decide_scope
from .store import FactStore
from .tiers import gate as tier_gate

STATUS_ORDER = {Status.FAIL: 0, Status.CONFLICT: 1, Status.CANT_TELL: 2, Status.NEEDS_REVIEW: 3, Status.PASS: 4,
                Status.NOT_APPLICABLE: 5}


def _rank(finding: Finding) -> tuple:
    # Among "can't tell" results, one that would fail once its reading is confirmed comes first.
    held_fail = finding.status == Status.CANT_TELL and finding.gate.startswith("Would fail")
    return STATUS_ORDER[finding.status], 0 if held_fail else 1, finding.area, finding.label


def run(store: FactStore, rules: list[Rule], profile: ShipProfile,
        scope_fn: Callable[[Rule, ShipProfile], ScopeDecision] | None = None, gate=None) -> RunResult:
    """Run every rule in scope. `scope_fn` lets a design basis decide applicability from the ship card.

    Results then pass two gates, neither of which can create a fail or turn anything into a pass.
    `gate`, an optional ConfidenceGate, can turn a fail into can't tell when it looks like a misread.
    The tier gate then holds back any pass or fail resting on an unconfirmed reading, and names it.
    """
    decide = scope_fn or decide_scope
    scope = [decide(rule, profile) for rule in rules]
    bad = unusable_facts(store)
    findings: list[Finding] = input_findings(bad)
    if bad:
        dropped = {id(fact) for fact, _ in bad}
        store = FactStore([f for f in store.facts if id(f) not in dropped])
    for rule, decision in zip(rules, scope):
        if not decision.applies:
            continue
        try:
            found = CHECKS[rule.check](rule, store, profile)
        except Exception as error:  # a crash must never look like a pass, or hide the other checks
            found = [_crashed(rule, error)]
        if decision.status == "cant_tell":
            # Show what would follow, and ask what settles whether the rule applies at all.
            note = f"Assumes this rule applies, which isn't settled yet: {decision.reason}"
            found = [f.model_copy(update={"assumptions": [*f.assumptions, note]}) for f in found]
            found.append(_applicability_question(rule, decision))
        findings.extend(found)
    findings.extend(check_consistency(store))
    findings.extend(check_drawing_scales(store))
    if gate is not None:
        findings = gate.apply(findings, store)
    findings = [tier_gate(f) for f in findings]
    findings.sort(key=_rank)
    counts = Counter(f.status.value for f in findings)
    all_counts = {status.value: counts.get(status.value, 0) for status in Status}
    return RunResult(profile=profile, findings=findings, scope=scope, counts=all_counts,
                     summary=_summary(all_counts, scope), fact_count=len(store.facts))


def _crashed(rule: Rule, error: Exception) -> Finding:
    return Finding(rule_id=rule.id, rule_title=rule.title, area=rule.area, rule_source=rule.source,
                   status=Status.CANT_TELL, subject=rule.id, label=rule.title, provisional=not rule.verified,
                   measured=f"This check stopped on an input it couldn't use ({type(error).__name__}: {error}).",
                   why="A check that can't run gives no pass and no fail.",
                   question="Check the values this rule uses (units, numbers), then run the checks again.")


def _applicability_question(rule: Rule, decision: ScopeDecision) -> Finding:
    return Finding(rule_id=rule.id, rule_title=rule.title, area=rule.area, rule_source=rule.source, status=Status.CANT_TELL,
                   subject=f"applicability:{rule.id}", label=f"Does {rule.title.lower()} apply?",
                   measured=decision.reason, required=decision.clause or rule.source,
                   why="Which rules apply depends on the ship's type, size, persons, voyage and dates.",
                   question=" ".join(decision.questions) or f"Does {rule.source} apply to this ship?",
                   provisional=not rule.verified, unconfirmed_label=rule.unconfirmed_label())


def _summary(counts: dict[str, int], scope) -> str:
    in_scope = [d.title for d in scope if d.applies]
    total = sum(counts.values())
    if not total:
        return "No checks ran: no rules in scope produced a result."
    if counts["fail"] == counts["conflict"] == counts["cant_tell"] == counts["needs_review"] == 0:
        return (f"No issues found in {total} checks. Rules checked: {', '.join(in_scope)}. "
                "This covers only these rules, and class and the flag state make the final call.")
    parts = []
    if counts["fail"]:
        parts.append(f"{counts['fail']} failed")
    if counts["conflict"]:
        parts.append(f"{counts['conflict']} conflicting")
    if counts["cant_tell"]:
        parts.append(f"{counts['cant_tell']} can't tell, more information needed")
    if counts["needs_review"]:
        parts.append(f"{counts['needs_review']} waiting for an engineer's review")
    if counts["pass"]:
        parts.append(f"{counts['pass']} passed")
    if counts["not_applicable"]:
        parts.append(f"{counts['not_applicable']} not applicable")
    return f"{total} checks: " + ", ".join(parts) + "."


STATUS_TITLES = {Status.FAIL: "FAILED", Status.CONFLICT: "CONFLICTS", Status.CANT_TELL: "CAN'T TELL",
                 Status.NEEDS_REVIEW: "NEEDS AN ENGINEER'S REVIEW", Status.PASS: "PASSED", Status.NOT_APPLICABLE: "NOT APPLICABLE"}


def report_text(result: RunResult) -> str:
    """The plain-text report. Everything in it comes from the deterministic checks."""
    lines = [f"Compliance report: {result.profile.name}", result.summary]
    if result.profile.note:
        lines.append(result.profile.note)
    for status in STATUS_TITLES:
        group = [f for f in result.findings if f.status == status]
        if not group:
            continue
        lines += ["", f"{STATUS_TITLES[status]} ({len(group)})"]
        for finding in group:
            lines.append(f"- {finding.label}: {finding.rule_title} [{finding.rule_source}]")
            if finding.where:
                lines.append(f"  Where: {finding.where}")
            if finding.measured:
                lines.append(f"  Found: {finding.measured}")
            if finding.required:
                lines.append(f"  Required: {finding.required}")
            if finding.gap:
                lines.append(f"  Gap: {finding.gap}")
            if finding.gate:
                lines.append(f"  Held back: {finding.gate}")
            if finding.gate_note:
                lines.append(f"  Held back: {finding.gate_note}")
            if finding.question:
                lines.append(f"  Needed: {finding.question}")
            for assumption in finding.assumptions:
                lines.append(f"  Assumption: {assumption}")
            if finding.unconfirmed_label:
                lines.append(f"  Note: {finding.unconfirmed_label}.")
            if finding.fix:
                lines.append(f"  Suggested fix: {finding.fix}")
            lines.append(f"  Source: {'; '.join(finding.sources) or 'none'}")
    out_of_scope = [d for d in result.scope if not d.applies]
    if out_of_scope:
        lines += ["", "NOT IN SCOPE"]
        lines += [f"- {d.title} [{d.source}]: {d.reason}" for d in out_of_scope]
    return "\n".join(lines)
