import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Accuracy, api, ConfidenceStatus, Decision, Finding, Inputs, MeasureTarget, Profile, QueueItem, RunResult, Spend, Status, UpdateResponse } from "./api";
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
  const [inputs, setInputs] = useState<Inputs | null>(null);
  const [learning, setLearning] = useState<ConfidenceStatus | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [reviewer, setReviewer] = useState(() => { try { return localStorage.getItem("reviewer") ?? ""; } catch { return ""; } });

  const refreshLearning = useCallback(async (id: string) => {
    try {
      const [status, next] = await Promise.all([api.confidence(), api.reviewQueue(id)]);
      setLearning(status);
      setQueue(next);
    } catch { /* the panel just stays as it was */ }
  }, []);

  const refresh = useCallback(async (id: string) => {
    setError("");
    try {
      const [{ result: next, spend: nextSpend }, nextInputs] = await Promise.all([api.run(id), api.inputs()]);
      setResult(next);
      setSpend(nextSpend);
      setInputs(nextInputs);
      refreshLearning(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The checks couldn't run.");
    }
  }, [refreshLearning]);

  useEffect(() => { api.profiles().then(setProfiles).catch(() => setError("Can't reach the backend. Is it running?")); }, []);
  useEffect(() => { setSelected(null); refresh(profileId); }, [profileId, refresh]);

  const applyUpdate = useCallback((update: UpdateResponse, intro: string) => {
    setResult(update.result);
    setSpend(update.spend);
    setInputs(update.inputs);
    // The selected result may no longer exist, so look it up again.
    setSelected((current) => current && (update.result.findings.find((f) => f.rule_id === current.rule_id && f.subject === current.subject) ?? null));
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
    refreshLearning(profileId);
  }, [profileId, refreshLearning]);

  const review = useCallback(async (finding: Finding, decision: Decision, value?: number, unit?: string) => {
    setError("");
    try {
      const update = await api.feedback(profileId, { rule_id: finding.rule_id, subject: finding.subject, decision,
                                                     corrected_value: value, corrected_unit: unit, reviewer });
      const said = { accept: "read correctly", reject: "misread", unsure: "not sure (not used for training)" }[decision];
      applyUpdate(update, `Answer saved for ${finding.label}: ${said}.${update.retrained ? " The confidence model was retrained." : ""}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The answer couldn't be saved.");
    }
  }, [profileId, applyUpdate, reviewer]);

  const undo = useCallback(async (key: string) => {
    setError("");
    try {
      applyUpdate(await api.undoFeedback(profileId, key), "Answer taken back. The model refits without it.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "The answer couldn't be taken back.");
    }
  }, [profileId, applyUpdate]);

  const nameReviewer = (name: string) => {
    setReviewer(name);
    try { localStorage.setItem("reviewer", name); } catch { /* not saved, still used */ }
  };
  const pick = (item: QueueItem) =>
    setSelected(result?.findings.find((f) => f.rule_id === item.rule_id && f.subject === item.subject) ?? null);

  const reset = async () => {
    await api.reset();
    setLines([]);
    setMeasurement(null);
    setMeasuring(false);
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
      {learning?.mode === "simulated" && (
        <p className="simulated" role="status">
          SIMULATED LABELS: the confidence model running now learned from {learning.model?.n_synthetic} simulated answers, not from engineers.
        </p>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <main className="layout">
        <Results result={result} selected={selected} onSelect={setSelected} filter={filter} onFilter={setFilter} />
        <div className="middle">
          <ShipViewer findings={result?.findings ?? []} selected={selected} onSelect={setSelected} measuring={measuring}
            onMeasured={setMeasurement} modelVisible={inputs?.model.has_view ?? null} modelActive={inputs?.model.active ?? true} />
          {selected && <FindingDetail finding={selected} onReview={review} />}
        </div>
        <aside className="side">
          <LearningPanel status={learning} queue={queue} reviewer={reviewer} onReviewer={nameReviewer} onPick={pick} onUndo={undo} />
          <InputsPanel profileId={profileId} inputs={inputs} onDone={(update, intro) => { setMeasuring(false); applyUpdate(update, intro); }} onError={setError} />
          <MeasurePanel profileId={profileId} measuring={measuring} onToggle={setMeasuring} measurement={measurement}
            available={inputs?.model.has_view ?? false} onSaved={(u) => applyUpdate(u, "Measurement saved.")} onError={setError} />
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
                    <small>{finding.unconfirmed_label || finding.rule_source}</small>
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
        <li><strong>Seeded faults:</strong> {doors.caught + stairs.caught} of {doors.faults + stairs.faults} flagged, one at a time on the real data.</li>
        <li><strong>Missing data:</strong> {missing.false_passes} false passes across {missing.checks} checks with all dimensions removed.</li>
      </ul>
    </div>
  );
}

type Review = (finding: Finding, decision: Decision, value?: number, unit?: string) => void;

const TO_MM: Record<string, number> = { mm: 1, in: 25.4, m: 1000, ft: 304.8 };

function FindingDetail({ finding, onReview }: { finding: Finding; onReview: Review }) {
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("mm");
  const [misread, setMisread] = useState(false);
  const [cropOk, setCropOk] = useState(true);
  useEffect(() => { setMisread(false); setValue(""); setCropOk(true); }, [finding.rule_id, finding.subject]);
  const number = Number(value);
  const inMm = value && Number.isFinite(number) ? number * TO_MM[unit] : null;
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
        {finding.unconfirmed_label && <div><dt>Note</dt><dd>{finding.unconfirmed_label}</dd></div>}
        {finding.gate_note && <div><dt>Held back</dt><dd>{finding.gate_note}</dd></div>}
        {finding.p_real !== null && <div><dt>P(real fail)</dt><dd>{finding.p_real.toFixed(2)}</dd></div>}
      </dl>
      {finding.reviewable && (
        <div className="review" aria-label="Engineer review">
          <p><strong>Was this value read correctly from the drawing?</strong> You judge the reading, not the ship. Your answer trains the confidence model.</p>
          {(finding.read_quote || finding.read_file) && (
            <p className="read-from">Read from {finding.read_file || "the input"}{finding.read_locator ? `, ${finding.read_locator}` : ""}
              {finding.read_quote && <>: <q>{finding.read_quote}</q></>}</p>
          )}
          {finding.read_file.toLowerCase().endsWith(".pdf") && finding.read_locator && cropOk && (
            <img className="evidence" alt={`The drawing where ${finding.measured} was read`} onError={() => setCropOk(false)}
              src={api.evidenceUrl(finding.read_file, finding.read_locator)} />
          )}
          <div className="review-actions">
            <button type="button" onClick={() => onReview(finding, "accept")}>Read correctly</button>
            <button type="button" aria-expanded={misread} onClick={() => setMisread(!misread)}>Misread</button>
            <button type="button" onClick={() => onReview(finding, "unsure")}>Not sure</button>
          </div>
          {misread && (
            <div className="misread">
              <label>Right value (optional)
                <input type="number" value={value} onChange={(e) => setValue(e.target.value)} placeholder="Leave empty if unknown" />
              </label>
              <select value={unit} onChange={(e) => setUnit(e.target.value)} aria-label="Unit">
                <option>mm</option><option>in</option><option>m</option><option>ft</option>
              </select>
              {inMm !== null && unit !== "mm" && <small>= {inMm.toFixed(1)} mm</small>}
              <button type="button" onClick={() => onReview(finding, "reject", inMm !== null ? number : undefined, inMm !== null ? unit : undefined)}>
                {inMm !== null ? "Save misread and the right value" : "Save misread"}
              </button>
            </div>
          )}
          <p className="muted">Not sure? Choose "Not sure": it is logged and never used for training.</p>
        </div>
      )}
    </section>
  );
}

function LearningPanel({ status, queue, reviewer, onReviewer, onPick, onUndo }: {
  status: ConfidenceStatus | null;
  queue: QueueItem[];
  reviewer: string;
  onReviewer: (name: string) => void;
  onPick: (item: QueueItem) => void;
  onUndo: (key: string) => void;
}) {
  if (!status) return null;
  const said = { accept: "read correctly", reject: "misread", unsure: "not sure" };
  const mode = { cold_start: "Fixed rule", model: `Model v${status.model?.version ?? ""}`, simulated: `Model v${status.model?.version ?? ""} (SIMULATED labels)` }[status.mode];
  return (
    <section className="panel learning">
      <h2>Learning from reviews</h2>
      <p><strong>{mode}</strong>{status.reason && <> · {status.reason}</>}</p>
      <p className="muted">
        {status.labels_used} of {status.min_labels} answers · read correctly {status.labels_read_correctly} · misread {status.labels_misread} of {status.min_per_class} needed
        {status.labels_unsure ? ` · not sure ${status.labels_unsure}` : ""}
      </p>
      <p className="muted">AI reader lessons from misreads: {status.lessons.length}</p>
      <label>Your name <input value={reviewer} onChange={(e) => onReviewer(e.target.value)} placeholder="Saved with each answer" /></label>
      {queue.length > 0 && (
        <>
          <h3>Review next</h3>
          <ol className="queue">
            {queue.map((item) => (
              <li key={`${item.rule_id}|${item.subject}`}>
                <button type="button" onClick={() => onPick(item)}><strong>{item.label}</strong> <span>{item.measured}</span><small>{item.why_now}</small></button>
              </li>
            ))}
          </ol>
        </>
      )}
      {status.recent.length > 0 && (
        <>
          <h3>Recent answers</h3>
          <ul className="recent">
            {status.recent.map((answer) => (
              <li key={answer.key}>
                <span>{answer.subject}: {said[answer.decision] ?? answer.decision}
                  {answer.corrected_value !== null ? `, right value ${answer.corrected_value} ${answer.corrected_unit}` : ""}
                  {answer.reviewer ? ` (${answer.reviewer})` : ""}{answer.synthetic ? " SIMULATED" : ""}</span>
                <button type="button" onClick={() => onUndo(answer.key)}>Undo</button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function distance(m: Measurement, direction: Direction): number {
  const dx = m.a.x - m.b.x, dy = m.a.y - m.b.y, dz = m.a.z - m.b.z;
  if (direction === "vertical") return Math.abs(dz);
  if (direction === "horizontal") return Math.hypot(dx, dy);
  return Math.hypot(dx, dy, dz);
}

function MeasurePanel({ profileId, measuring, onToggle, measurement, available, onSaved, onError }: {
  profileId: string;
  measuring: boolean;
  onToggle: (on: boolean) => void;
  measurement: Measurement | null;
  available: boolean;
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
      <button type="button" disabled={!available} aria-pressed={measuring} onClick={() => onToggle(!measuring)}>{measuring ? "Stop measuring" : "Start measuring"}</button>
      {!available && <p className="muted">Needs a 3D model with a 3D view.</p>}
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

function InputsPanel({ profileId, inputs, onDone, onError }: {
  profileId: string;
  inputs: Inputs | null;
  onDone: (update: UpdateResponse, intro: string) => void;
  onError: (text: string) => void;
}) {
  const [busy, setBusy] = useState("");
  const [pages, setPages] = useState("");
  const picker = useRef<HTMLInputElement>(null);

  const act = async (status: string, action: () => Promise<UpdateResponse>, intro: (update: UpdateResponse) => string) => {
    setBusy(status);
    onError("");
    try {
      const update = await action();
      onDone(update, intro(update));
    } catch (e) {
      onError(e instanceof Error ? e.message : "That didn't work.");
    } finally {
      setBusy("");
      if (picker.current) picker.current.value = "";
    }
  };

  /** One picker for everything: the file's type decides how it's read. */
  const addFile = (file: File | undefined) => {
    if (!file) return;
    if (file.name.toLowerCase().endsWith(".nwd")) {
      act("Reading the 3D model. A large file can take a minute.", () => api.importModel(profileId, file),
        (u) => `${file.name} imported: ${u.inputs.model.parts} parts.`);
    } else {
      act("Reading the file.", () => api.upload(profileId, file, pages),
        (u) => `${file.name} read${u.cached ? " from saved results, at no cost" : ""}. ${u.recorded.length} new fact(s).`);
    }
  };
  const disabled = Boolean(busy);
  const current = inputs?.model;

  return (
    <section className="panel inputs">
      <h2>Inputs</h2>
      <ul>
        {current?.active && (
          <li>
            <span><strong>{current.name}</strong><small>3D model, {current.parts} parts{current.has_view ? "" : ", no 3D view"}</small></span>
            <button type="button" disabled={disabled} aria-label={`Remove ${current.name}`}
              onClick={() => act("Removing the model.", () => api.removeModel(profileId), () => `${current.name} removed.`)}>Remove</button>
          </li>
        )}
        {current && !current.active && (
          <li>
            <span><strong>No 3D model</strong>{current.restorable && <small>The removed model can be restored.</small>}</span>
            {current.restorable && <button type="button" disabled={disabled}
              onClick={() => act("Restoring the model.", () => api.restoreModel(profileId), (u) => `${u.inputs.model.name} restored.`)}>Restore</button>}
          </li>
        )}
        {inputs?.files.map((file) => (
          <li key={file.name}>
            <span><strong>{file.name}</strong><small>{file.facts} fact(s) read</small></span>
            <button type="button" disabled={disabled} aria-label={`Remove ${file.name}`}
              onClick={() => act("Removing the file.", () => api.removeFile(profileId, file.name), () => `${file.name} removed.`)}>Remove</button>
          </li>
        ))}
        {Boolean(inputs?.measurements) && (
          <li>
            <span><strong>3D measurements</strong><small>{inputs!.measurements} saved</small></span>
            <button type="button" disabled={disabled} aria-label="Remove 3D measurements"
              onClick={() => act("Removing the measurements.", () => api.removeGroup(profileId, "measurements"), () => "3D measurements removed.")}>Remove</button>
          </li>
        )}
        {Boolean(inputs?.chat) && (
          <li>
            <span><strong>Chat answers</strong><small>{inputs!.chat} fact(s) recorded</small></span>
            <button type="button" disabled={disabled} aria-label="Remove chat answers"
              onClick={() => act("Removing the chat answers.", () => api.removeGroup(profileId, "chat"), () => "Chat answers removed.")}>Remove</button>
          </li>
        )}
      </ul>
      <label>Add a file
        <input ref={picker} type="file" accept=".nwd,.pdf,.png,.jpg,.jpeg,.webp,.md,.txt" disabled={disabled} onChange={(e) => addFile(e.target.files?.[0])} />
      </label>
      <p className="hint">3D model: .nwd{current?.active ? " (replaces the current one)" : ""}. Drawing or document: PDF, PNG, JPG, WEBP, MD, or TXT.</p>
      <label>PDF pages <input placeholder="All, or like 3,4" value={pages} onChange={(e) => setPages(e.target.value)} /></label>
      {busy && <p className="muted" role="status">{busy}</p>}
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
