"""Run the rules in scope against the facts and build the plain-text result."""
from __future__ import annotations

from collections import Counter

from .checks import CHECKS, check_consistency, input_findings, unusable_facts
from .models import Finding, Rule, RunResult, ShipProfile, Status
from .rules import decide_scope
from .store import FactStore

STATUS_ORDER = {Status.FAIL: 0, Status.CONFLICT: 1, Status.CANT_TELL: 2, Status.PASS: 3}


def run(store: FactStore, rules: list[Rule], profile: ShipProfile, gate=None) -> RunResult:
    """`gate` is an optional ConfidenceGate. It can only turn a fail into can't tell."""
    scope = [decide_scope(rule, profile) for rule in rules]
    bad = unusable_facts(store)
    findings: list[Finding] = input_findings(bad)
    if bad:
        dropped = {id(fact) for fact, _ in bad}
        store = FactStore([f for f in store.facts if id(f) not in dropped])
    for rule, decision in zip(rules, scope):
        if decision.applies:
            try:
                findings.extend(CHECKS[rule.check](rule, store, profile))
            except Exception as error:  # a crash must never look like a pass, or hide the other checks
                findings.append(_crashed(rule, error))
    findings.extend(check_consistency(store))
    if gate is not None:
        findings = gate.apply(findings, store)
    findings.sort(key=lambda f: (STATUS_ORDER[f.status], f.area, f.label))
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


def _summary(counts: dict[str, int], scope) -> str:
    in_scope = [d.title for d in scope if d.applies]
    total = sum(counts.values())
    if not total:
        return "No checks ran: no rules in scope produced a result."
    if counts["fail"] == counts["conflict"] == counts["cant_tell"] == 0:
        return (f"No issues found in {total} checks. Rules checked: {', '.join(in_scope)}. "
                "This covers only these rules, and class and the flag state make the final call.")
    parts = []
    if counts["fail"]:
        parts.append(f"{counts['fail']} failed")
    if counts["conflict"]:
        parts.append(f"{counts['conflict']} conflicting")
    if counts["cant_tell"]:
        parts.append(f"{counts['cant_tell']} can't tell, more information needed")
    if counts["pass"]:
        parts.append(f"{counts['pass']} passed")
    return f"{total} checks: " + ", ".join(parts) + "."


STATUS_TITLES = {Status.FAIL: "FAILED", Status.CONFLICT: "CONFLICTS", Status.CANT_TELL: "CAN'T TELL", Status.PASS: "PASSED"}


def report_text(result: RunResult) -> str:
    """The plain-text report. Everything in it comes from the deterministic checks."""
    lines = [f"Compliance report: {result.profile.name}", result.summary]
    if result.profile.note:
        lines.append(result.profile.note)
    for status in (Status.FAIL, Status.CONFLICT, Status.CANT_TELL, Status.PASS):
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
            if finding.gate_note:
                lines.append(f"  Held back: {finding.gate_note}")
            if finding.question:
                lines.append(f"  Needed: {finding.question}")
            for assumption in finding.assumptions:
                lines.append(f"  Assumption: {assumption}")
            if finding.unconfirmed_label:
                lines.append(f"  Note: {finding.unconfirmed_label}.")
            lines.append(f"  Source: {'; '.join(finding.sources) or 'none'}")
    out_of_scope = [d for d in result.scope if not d.applies]
    if out_of_scope:
        lines += ["", "NOT IN SCOPE"]
        lines += [f"- {d.title} [{d.source}]: {d.reason}" for d in out_of_scope]
    return "\n".join(lines)
