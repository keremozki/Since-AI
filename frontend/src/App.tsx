import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Accuracy, api, Finding, MeasureTarget, Profile, RunResult, Spend, Status, UpdateResponse } from "./api";
import ShipViewer, { Measurement, STATUS_COLOR } from "./ShipViewer";

const STATUS_ORDER: Status[] = ["fail", "conflict", "cant_tell", "pass"];
const STATUS_LABEL: Record<Status, string> = { fail: "Failed", conflict: "Conflict", cant_tell: "Can't tell", pass: "Passed" };
const INCHES_PER_METRE = 39.3701;
type Direction = "straight" | "vertical" | "horizontal";

interface ChatLine {
  role: "engineer" | "assistant" | "system";
  text: string;
}

export default function App() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profileId, setProfileId] = useState("rcrv");
  const [result, setResult] = useState<RunResult | null>(null);
  const [spend, setSpend] = useState<Spend | null>(null);
  const [selected, setSelected] = useState<Finding | null>(null);
  const [filter, setFilter] = useState<Status | "all">("all");
  const [error, setError] = useState("");
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [measuring, setMeasuring] = useState(false);
  const [measurement, setMeasurement] = useState<Measurement | null>(null);

  const refresh = useCallback(async (id: string) => {
    setError("");
    try {
      const { result: next, spend: nextSpend } = await api.run(id);
      setResult(next);
      setSpend(nextSpend);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The checks couldn't run.");
    }
  }, []);

  useEffect(() => { api.profiles().then(setProfiles).catch(() => setError("Can't reach the backend. Is it running?")); }, []);
  useEffect(() => { setSelected(null); refresh(profileId); }, [profileId, refresh]);

  const applyUpdate = useCallback((update: UpdateResponse, intro: string) => {
    setResult(update.result);
    setSpend(update.spend);
    const notes: ChatLine[] = [];
    if (update.reply) notes.push({ role: "assistant", text: update.reply });
    if (intro) notes.push({ role: "system", text: intro });
    if (update.recorded.length) {
      const list = update.recorded.map((f) => `${f.subject} ${f.property.replaceAll("_", " ")}: ${f.value} ${f.unit}`.trim());
      notes.push({ role: "system", text: `Recorded: ${list.join("; ")}` });
    }
    if (update.dropped) notes.push({ role: "system", text: `${update.dropped} value(s) were rejected because they didn't fit a known fact.` });
    if (update.changes.length) notes.push({ role: "system", text: `Tests rerun. Changed:\n${update.changes.join("\n")}` });
    setLines((current) => [...current, ...notes]);
  }, []);

  const reset = async () => {
    await api.reset();
    setLines([]);
    setMeasurement(null);
    setSelected(null);
    refresh(profileId);
  };

  return (
    <div className="app">
      <header className="topbar">
        <h1>Ship Compliance Checker</h1>
        <label className="profile">
          Ship profile
          <select value={profileId} onChange={(e) => setProfileId(e.target.value)}>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <div className="topbar-actions">
          <a href={`/api/report/${profileId}`} target="_blank" rel="noreferrer">Text report</a>
          <button type="button" onClick={reset}>Clear added facts</button>
          {spend && <span className="spend" title={`${spend.calls} AI calls`}>AI spend ${spend.spent_usd.toFixed(2)} of ${spend.cap_usd.toFixed(2)}</span>}
        </div>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      <main className="layout">
        <Results result={result} selected={selected} onSelect={setSelected} filter={filter} onFilter={setFilter} />
        <div className="middle">
          <ShipViewer findings={result?.findings ?? []} selected={selected} onSelect={setSelected} measuring={measuring} onMeasured={setMeasurement} />
          {selected && <FindingDetail finding={selected} />}
        </div>
        <aside className="side">
          <MeasurePanel profileId={profileId} measuring={measuring} onToggle={setMeasuring} measurement={measurement}
            onSaved={(u) => applyUpdate(u, "Measurement saved.")} onError={setError} />
          <UploadPanel profileId={profileId} onDone={applyUpdate} onError={setError} />
          <Chat profileId={profileId} lines={lines} setLines={setLines} onDone={applyUpdate} />
        </aside>
      </main>
    </div>
  );
}

function Results({ result, selected, onSelect, filter, onFilter }: {
  result: RunResult | null;
  selected: Finding | null;
  onSelect: (finding: Finding) => void;
  filter: Status | "all";
  onFilter: (status: Status | "all") => void;
}) {
  const groups = useMemo(() => {
    const findings = result?.findings ?? [];
    return STATUS_ORDER.filter((s) => filter === "all" || filter === s)
      .map((status) => ({ status, items: findings.filter((f) => f.status === status) }))
      .filter((group) => group.items.length);
  }, [result, filter]);
  if (!result) return <section className="results"><p className="muted">Running the checks.</p></section>;
  const outOfScope = result.scope.filter((d) => !d.applies);
  return (
    <section className="results" aria-label="Results">
      <p className="summary">{result.summary}</p>
      {result.profile.note && <p className="muted note">{result.profile.note}</p>}
      <div className="filters" role="group" aria-label="Filter by result">
        <button type="button" aria-pressed={filter === "all"} onClick={() => onFilter("all")}>All</button>
        {STATUS_ORDER.map((status) => (
          <button type="button" key={status} aria-pressed={filter === status} onClick={() => onFilter(status)}>
            <i style={{ background: STATUS_COLOR[status] }} />{STATUS_LABEL[status]} {result.counts[status]}
          </button>
        ))}
      </div>
      {groups.map(({ status, items }) => (
        <div key={status} className="group">
          <h2 style={{ color: STATUS_COLOR[status] }}>{STATUS_LABEL[status]} ({items.length})</h2>
          <ul>
            {items.map((finding) => {
              const on = selected?.rule_id === finding.rule_id && selected?.subject === finding.subject;
              return (
                <li key={`${finding.rule_id}|${finding.subject}`}>
                  <button type="button" className={on ? "finding on" : "finding"} onClick={() => onSelect(finding)}>
                    <strong>{finding.label}</strong>
                    <span>{finding.measured}{finding.gap ? `: ${finding.gap}` : ""}</span>
                    <small>{finding.rule_source}{finding.provisional ? " (limit not yet confirmed)" : ""}</small>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
      {outOfScope.length > 0 && (
        <div className="group">
          <h2>Not in scope ({outOfScope.length})</h2>
          <ul className="scope">
            {outOfScope.map((d) => <li key={d.rule_id}><strong>{d.title}</strong> {d.reason}</li>)}
          </ul>
        </div>
      )}
      <Scoreboard />
    </section>
  );
}

function Scoreboard() {
  const [accuracy, setAccuracy] = useState<Accuracy | null>(null);
  useEffect(() => { api.accuracy().then(setAccuracy).catch(() => undefined); }, []);
  if (!accuracy) return null;
  const { hand_checked: hand, seeded_door_faults: doors, seeded_stair_faults: stairs, missing_data: missing } = accuracy;
  return (
    <div className="group">
      <h2>How we test the checks</h2>
      <ul className="scope">
        <li><strong>Hand-checked doors:</strong> {hand.correct} of {hand.total} correct, {hand.false_passes} false passes, {hand.false_fails} false fails.</li>
        <li><strong>Seeded faults:</strong> {doors.caught + stairs.caught} of {doors.faults + stairs.faults} caught, one at a time on the real data.</li>
        <li><strong>Missing data:</strong> {missing.false_passes} false passes across {missing.checks} checks with all dimensions removed.</li>
      </ul>
    </div>
  );
}

function FindingDetail({ finding }: { finding: Finding }) {
  const rows: [string, string][] = [
    ["Where", finding.where], ["Found", finding.measured], ["Required", finding.required], ["Gap", finding.gap],
    ["Rule", finding.rule_source], ["Why it applies", finding.why], ["Confidence", finding.confidence],
    ["Needed", finding.question], ["Source", finding.sources.join("; ")],
  ];
  return (
    <section className="detail" aria-label="Selected finding">
      <h2><span style={{ color: STATUS_COLOR[finding.status] }}>{STATUS_LABEL[finding.status]}</span> {finding.label}</h2>
      <dl>
        {rows.filter(([, value]) => value).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}
        {finding.assumptions.map((text) => <div key={text}><dt>Assumption</dt><dd>{text}</dd></div>)}
        {finding.provisional && <div><dt>Note</dt><dd>This limit isn't confirmed against the rule text yet.</dd></div>}
      </dl>
    </section>
  );
}

function distance(m: Measurement, direction: Direction): number {
  const dx = m.a.x - m.b.x, dy = m.a.y - m.b.y, dz = m.a.z - m.b.z;
  if (direction === "vertical") return Math.abs(dz);
  if (direction === "horizontal") return Math.hypot(dx, dy);
  return Math.hypot(dx, dy, dz);
}

function MeasurePanel({ profileId, measuring, onToggle, measurement, onSaved, onError }: {
  profileId: string;
  measuring: boolean;
  onToggle: (on: boolean) => void;
  measurement: Measurement | null;
  onSaved: (update: UpdateResponse) => void;
  onError: (text: string) => void;
}) {
  const [targets, setTargets] = useState<MeasureTarget[]>([]);
  const [target, setTarget] = useState(0);
  const [direction, setDirection] = useState<Direction>("straight");
  const [doorNumber, setDoorNumber] = useState("");
  useEffect(() => { api.vocabulary().then((all) => setTargets(all.filter((t) => !t.subject.startsWith("door-type")))).catch(() => undefined); }, []);
  const chosen = targets[target];
  const needsDoor = chosen?.subject.startsWith("door-number");
  const inches = measurement ? distance(measurement, direction) : 0;
  const save = async () => {
    if (!measurement || !chosen) return;
    try {
      const update = await api.measure(profileId, {
        subject: needsDoor ? `door-number:${doorNumber}` : chosen.subject,
        property: chosen.property,
        value: Number((inches / INCHES_PER_METRE).toFixed(3)),
        unit: "m",
        a: measurement.a,
        b: measurement.b,
        note: `${direction} distance`,
      });
      onSaved(update);
      onToggle(false);
    } catch (e) {
      onError(e instanceof Error ? e.message : "The measurement couldn't be saved.");
    }
  };
  return (
    <section className="panel">
      <h2>Measure in 3D</h2>
      <button type="button" aria-pressed={measuring} onClick={() => onToggle(!measuring)}>{measuring ? "Stop measuring" : "Start measuring"}</button>
      {measuring && !measurement && <p className="muted">Click two points on the model. Use the cut height to see inside.</p>}
      {measurement && (
        <div className="measure-form">
          <label>Direction
            <select value={direction} onChange={(e) => setDirection(e.target.value as Direction)}>
              <option value="straight">Straight line</option>
              <option value="vertical">Vertical only</option>
              <option value="horizontal">Horizontal only</option>
            </select>
          </label>
          <p className="measure-value">{(inches / INCHES_PER_METRE).toFixed(3)} m ({inches.toFixed(1)} in)</p>
          <label>Save as
            <select value={target} onChange={(e) => setTarget(Number(e.target.value))}>
              {targets.map((t, i) => <option key={`${t.subject}${t.property}`} value={i}>{t.meaning}</option>)}
            </select>
          </label>
          {needsDoor && <label>Door number <input value={doorNumber} onChange={(e) => setDoorNumber(e.target.value.replace(/\D/g, ""))} /></label>}
          <button type="button" disabled={needsDoor && !doorNumber} onClick={save}>Save and rerun tests</button>
        </div>
      )}
    </section>
  );
}

function UploadPanel({ profileId, onDone, onError }: {
  profileId: string;
  onDone: (update: UpdateResponse, intro: string) => void;
  onError: (text: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [pages, setPages] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const send = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const update = await api.upload(profileId, file, pages);
      onDone(update, `${file.name} read${update.cached ? " from saved results, at no cost" : ""}. ${update.recorded.length} new fact(s).`);
    } catch (e) {
      onError(e instanceof Error ? e.message : "The file couldn't be read.");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  return (
    <section className="panel">
      <h2>Add a drawing or document</h2>
      <input ref={input} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.md,.txt" disabled={busy} onChange={(e) => send(e.target.files?.[0])} />
      <label>PDF pages <input placeholder="All, or like 3,4" value={pages} onChange={(e) => setPages(e.target.value)} /></label>
      {busy && <p className="muted">Reading the file.</p>}
    </section>
  );
}

function Chat({ profileId, lines, setLines, onDone }: {
  profileId: string;
  lines: ChatLine[];
  setLines: React.Dispatch<React.SetStateAction<ChatLine[]>>;
  onDone: (update: UpdateResponse, intro: string) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const log = useRef<HTMLDivElement>(null);
  useEffect(() => { log.current?.scrollTo(0, log.current.scrollHeight); }, [lines]);
  const send = async (event: FormEvent) => {
    event.preventDefault();
    const message = text.trim();
    if (!message || busy) return;
    setText("");
    setLines((current) => [...current, { role: "engineer", text: message }]);
    setBusy(true);
    try {
      onDone(await api.chat(profileId, message), "");
    } catch (e) {
      setLines((current) => [...current, { role: "system", text: e instanceof Error ? e.message : "The message couldn't be sent." }]);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel chat">
      <h2>Ask or add information</h2>
      <div className="chat-log" ref={log} aria-live="polite">
        {lines.length === 0 && <p className="muted">Ask about a result, or answer a "can't tell", for example: "Each liferaft is rated for 16 persons."</p>}
        {lines.map((line, index) => <p key={index} className={`line ${line.role}`}>{line.text}</p>)}
        {busy && <p className="muted">Thinking.</p>}
      </div>
      <form onSubmit={send}>
        <input aria-label="Message" value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a message" />
        <button type="submit" disabled={busy || !text.trim()}>Send</button>
      </form>
    </section>
  );
}
