import { useEffect, useMemo, useRef, useState } from "react";
import { Accuracy, api, Finding, Inputs, RunResult, Status } from "./api";
import { NO_SOURCE, originsOf, shortDeck, STATUS_LABEL, STATUS_ORDER, StatusIcon } from "./shared";

const groupKey = (f: Finding) => `${f.status}|${f.rule_id}`;
const same = (a: Finding | null, b: Finding) => a?.rule_id === b.rule_id && a?.subject === b.subject;

export default function Results({ result, inputs, selected, onSelect }: {
  result: RunResult | null;
  inputs: Inputs | null;
  selected: Finding | null;
  onSelect: (finding: Finding) => void;
}) {
  const [filter, setFilter] = useState<Status | null>(null);
  const [origin, setOrigin] = useState("");
  const [query, setQuery] = useState("");
  const [toggled, setToggled] = useState<Set<string>>(new Set());
  const selectedRow = useRef<HTMLButtonElement>(null);

  // Keep the selected result visible, even when it was picked in the 3D view.
  useEffect(() => {
    if (!selected) return;
    if (filter && selected.status !== filter) setFilter(null);
    if (origin && !fromOrigin(selected, origin, inputs)) setOrigin("");
    setQuery((current) => (matches(selected, current, inputs) ? current : ""));
    setToggled((current) => {
      const key = groupKey(selected);
      if (isOpen(selected.status, current.has(key))) return current;
      const next = new Set(current);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
    const timer = setTimeout(() => selectedRow.current?.scrollIntoView({ block: "nearest" }));
    return () => clearTimeout(timer);
    // Only a new selection should move the list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  // Every input is listed even with no results, so that an unused file is plain to see.
  const originOptions = useMemo(() => {
    const counts = new Map<string, number>();
    if (inputs?.model.active) counts.set(inputs.model.name, 0);
    for (const file of inputs?.files ?? []) counts.set(file.name, 0);
    for (const finding of result?.findings ?? []) {
      const origins = originsOf(finding, inputs);
      for (const name of origins.length ? origins : [NO_SOURCE]) counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    return [...counts.entries()];
  }, [result, inputs]);

  // A removed input can't stay selected.
  useEffect(() => {
    if (origin && !originOptions.some(([name]) => name === origin)) setOrigin("");
  }, [origin, originOptions]);

  const inOrigin = useMemo(
    () => (result?.findings ?? []).filter((f) => !origin || fromOrigin(f, origin, inputs)),
    [result, inputs, origin],
  );

  const groups = useMemo(() => {
    const shown = inOrigin.filter((f) => (!filter || f.status === filter) && matches(f, query, inputs));
    return STATUS_ORDER.map((status) => {
      const rules = new Map<string, Finding[]>();
      for (const finding of shown.filter((f) => f.status === status)) {
        rules.set(finding.rule_id, [...(rules.get(finding.rule_id) ?? []), finding]);
      }
      return { status, rules: [...rules.values()] };
    }).filter((group) => group.rules.length);
  }, [inOrigin, inputs, filter, query]);

  if (!result) return <section className="results"><p className="muted loading">Running the checks.</p></section>;

  const outOfScope = result.scope.filter((d) => !d.applies);
  const searching = query.trim().length > 0;

  return (
    <section className="results" aria-label="Results">
      <div className="tiles" role="group" aria-label="Filter results">
        {STATUS_ORDER.map((status) => (
          <button type="button" key={status} className={`tile ${status}`} aria-pressed={filter === status}
            onClick={() => setFilter(filter === status ? null : status)}>
            <b>{inOrigin.filter((f) => f.status === status).length}</b>
            <span><StatusIcon status={status} size={12} /> {STATUS_LABEL[status]}</span>
          </button>
        ))}
      </div>
      <p className="summary">{origin ? `${inOrigin.length} result(s) from ${origin}.` : result.summary}</p>
      {result.profile.note && <p className={result.profile.use_demo_faults ? "profile-note test-case" : "profile-note"}>{result.profile.note}</p>}
      <div className="finders">
        <input className="search" type="search" aria-label="Search results" placeholder="Search, like door 509 or Main Deck"
          value={query} onChange={(e) => setQuery(e.target.value)} />
        <label className="origin-filter">
          <span>From</span>
          <select value={origin} onChange={(e) => setOrigin(e.target.value)}>
            <option value="">All sources ({result.findings.length})</option>
            {originOptions.map(([name, count]) => <option key={name} value={name}>{name} ({count})</option>)}
          </select>
        </label>
      </div>

      {groups.length === 0 && (
        <p className="muted empty">
          {origin && inOrigin.length === 0
            ? `No results use ${origin} yet. Its facts may have been read, but no check uses them.`
            : "No results match. Try clearing the search or the filter."}
        </p>
      )}

      {groups.map(({ status, rules }) => (
        <div key={status} className="status-group">
          <h2><StatusIcon status={status} /> {STATUS_LABEL[status]}</h2>
          {rules.map((findings) => {
            const first = findings[0];
            const key = groupKey(first);
            const open = searching || isOpen(status, toggled.has(key));
            return (
              <div key={key} className="rule-group">
                <button type="button" className="rule-head" aria-expanded={open} onClick={() => setToggled((current) => {
                  const next = new Set(current);
                  if (next.has(key)) next.delete(key); else next.add(key);
                  return next;
                })}>
                  <span className="chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
                  <span className="rule-title">
                    <strong>{first.rule_title}</strong>
                    <small className={first.unconfirmed_label ? "unconfirmed" : ""}>{first.unconfirmed_label || first.rule_source}</small>
                  </span>
                  <span className="count">{findings.length}</span>
                </button>
                {open && (
                  <ul>
                    {findings.map((finding) => {
                      const on = same(selected, finding);
                      return (
                        <li key={`${finding.rule_id}|${finding.subject}`}>
                          <button type="button" ref={on ? selectedRow : undefined} aria-current={on || undefined}
                            className={on ? "finding on" : "finding"} onClick={() => onSelect(finding)}>
                            <span className="finding-top">
                              <strong>{finding.label}</strong>
                              {finding.where && <small>{shortDeck(finding.where)}</small>}
                            </span>
                            <span className="finding-text">
                              {finding.gap ? <><b>{finding.gap}</b> · {finding.measured}</> : finding.measured}
                            </span>
                            <small className="finding-origin">From: {originsOf(finding, inputs).join(", ") || NO_SOURCE}</small>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      ))}

      {outOfScope.length > 0 && (
        <details className="more">
          <summary>Rules not in scope for this ship ({outOfScope.length})</summary>
          <ul>
            {outOfScope.map((d) => <li key={d.rule_id}><strong>{d.title}</strong><br />{d.reason}</li>)}
          </ul>
        </details>
      )}
      <Scoreboard />
    </section>
  );
}

function isOpen(status: Status, toggled: boolean): boolean {
  const openByDefault = status !== "pass";
  return toggled ? !openByDefault : openByDefault;
}

function fromOrigin(finding: Finding, origin: string, inputs: Inputs | null): boolean {
  const origins = originsOf(finding, inputs);
  return origin === NO_SOURCE ? origins.length === 0 : origins.includes(origin);
}

function matches(finding: Finding, query: string, inputs: Inputs | null): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const text = [finding.label, finding.where, finding.measured, finding.rule_title, finding.rule_source, ...originsOf(finding, inputs)].join(" ").toLowerCase();
  return words.every((word) => text.includes(word));
}

function Scoreboard() {
  const [accuracy, setAccuracy] = useState<Accuracy | null>(null);
  useEffect(() => { api.accuracy().then(setAccuracy).catch(() => undefined); }, []);
  if (!accuracy) return null;
  const { hand_checked: hand, seeded_door_faults: doors, seeded_stair_faults: stairs, missing_data: missing } = accuracy;
  return (
    <details className="more">
      <summary>How we test these checks</summary>
      <ul>
        <li><strong>Hand-checked doors:</strong> {hand.correct} of {hand.total} correct, {hand.false_passes} false passes, {hand.false_fails} false fails.</li>
        <li><strong>Seeded faults:</strong> {doors.caught + stairs.caught} of {doors.faults + stairs.faults} flagged, one at a time on the real data.</li>
        <li><strong>Missing data:</strong> {missing.false_passes} false passes across {missing.checks} checks with all dimensions removed.</li>
      </ul>
    </details>
  );
}
