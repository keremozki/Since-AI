import { useCallback, useEffect, useState } from "react";
import { api, ConfidenceStatus, Decision, Finding, Inputs, Profile, QueueItem, RunResult, Spend, UpdateResponse } from "./api";
import Assistant, { ChatLine } from "./Assistant";
import FindingDetail from "./FindingDetail";
import InputsPanel from "./InputsPanel";
import MeasurePanel from "./MeasurePanel";
import Results from "./Results";
import ReviewPanel from "./ReviewPanel";
import ShipCardPanel from "./ShipCardPanel";
import ShipViewer, { Measurement } from "./ShipViewer";

type Tab = "assistant" | "inputs" | "review" | "card";

const SAID: Record<Decision, string> = { accept: "read correctly", reject: "misread", unsure: "not sure (not used for training)" };

export default function App() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profileId, setProfileId] = useState("rcrv");
  const [result, setResult] = useState<RunResult | null>(null);
  const [spend, setSpend] = useState<Spend | null>(null);
  const [selected, setSelected] = useState<Finding | null>(null);
  const [error, setError] = useState("");
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [measuring, setMeasuring] = useState(false);
  const [measurement, setMeasurement] = useState<Measurement | null>(null);
  const [inputs, setInputs] = useState<Inputs | null>(null);
  const [tab, setTab] = useState<Tab>("assistant");
  const [question, setQuestion] = useState("");
  const [inputsNote, setInputsNote] = useState("");
  const [learning, setLearning] = useState<ConfidenceStatus | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [reviewer, setReviewer] = useState(() => { try { return localStorage.getItem("reviewer") ?? ""; } catch { return ""; } });
  const [cardVersion, setCardVersion] = useState(0);

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
    // The selected result may have changed or gone, so look it up again.
    setSelected((current) => current && (update.result.findings.find((f) => f.rule_id === current.rule_id && f.subject === current.subject) ?? null));
    const notes: ChatLine[] = [];
    if (update.reply) notes.push({ role: "assistant", text: update.reply });
    if (update.recorded_text.length) notes.push({ role: "system", text: `Recorded:\n${update.recorded_text.join("\n")}` });
    if (update.dropped) notes.push({ role: "system", text: `${update.dropped} value(s) were rejected because they didn't fit a known fact.` });
    if (update.changes.length) notes.push({ role: "system", text: `Checks rerun. What changed:\n${update.changes.join("\n")}` });
    setLines((current) => [...current, ...notes]);
    setCardVersion((version) => version + 1);  // new facts can fill the ship card
    refreshLearning(profileId);
  }, [profileId, refreshLearning]);

  const onInputsDone = useCallback((update: UpdateResponse, intro: string) => {
    setMeasuring(false);
    setInputsNote(intro);
    applyUpdate(update, intro);
  }, [applyUpdate]);

  const review = useCallback(async (finding: Finding, decision: Decision, value?: number, unit?: string) => {
    setError("");
    try {
      const update = await api.feedback(profileId, { rule_id: finding.rule_id, subject: finding.subject, decision,
                                                     corrected_value: value, corrected_unit: unit, reviewer });
      applyUpdate(update, "");
      const retrained = update.retrained ? " The confidence model was retrained." : "";
      setLines((current) => [...current, { role: "system", text: `Answer saved for ${finding.label}: ${SAID[decision]}.${retrained}` }]);
      setTab("review");
    } catch (e) {
      setError(e instanceof Error ? e.message : "The answer couldn't be saved.");
    }
  }, [profileId, applyUpdate, reviewer]);

  const undo = useCallback(async (key: string) => {
    setError("");
    try {
      applyUpdate(await api.undoFeedback(profileId, key), "");
      setLines((current) => [...current, { role: "system", text: "Answer taken back. The model refits without it." }]);
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

  const startOver = async () => {
    await api.reset();
    setLines([]);
    setMeasurement(null);
    setMeasuring(false);
    setSelected(null);
    setQuestion("");
    setInputsNote("Added files, measurements, chat answers, and ship card answers removed.");
    setCardVersion((version) => version + 1);
    refresh(profileId);
  };

  const answer = useCallback((text: string) => {
    setQuestion(text);
    setTab("assistant");
  }, []);
  const closeDetail = useCallback(() => setSelected(null), []);
  const onCardSaved = useCallback(() => { refresh(profileId); }, [profileId, refresh]);
  const aiMode = spend?.ai_mode ?? "";

  return (
    <div className="app">
      <header className="topbar">
        <h1>Dynamis SCC</h1>
        <label className="profile">
          <span>Checking as</span>
          <select value={profileId} onChange={(e) => setProfileId(e.target.value)}>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <div className="topbar-actions">
          {aiMode && <span className="ai-mode" title={aiMode === "offline" ? "No request leaves this machine. AI steps replay saved answers or wait." : "AI requests go to the Claude API."}>AI: {aiMode === "offline" ? "offline" : "live"}</span>}
          {spend && <span className="spend" title={`${spend.calls} AI calls. AI features stop at the cap.`}>AI spend ${spend.spent_usd.toFixed(2)} of ${spend.cap_usd.toFixed(2)}</span>}
          <a className="button" href={`/api/report/${profileId}`} target="_blank" rel="noreferrer">Text report</a>
          <a className="button" href={`/api/proof/${profileId}`} title="A zip with the rules, facts, results and hashes, which tools/verify_proof.py can check." download>Proof file</a>
        </div>
      </header>
      {learning?.mode === "simulated" && (
        <p className="simulated" role="status">
          SIMULATED LABELS: the confidence model running now learned from {learning.model?.n_synthetic} simulated answers, not from engineers.
        </p>
      )}
      {error && (
        <div className="error" role="alert">
          <span>{error}</span>
          <button type="button" className="ghost" onClick={() => setError("")} aria-label="Dismiss">✕</button>
        </div>
      )}
      <main className="layout">
        <Results result={result} inputs={inputs} selected={selected} onSelect={setSelected} />
        <div className="middle">
          <ShipViewer findings={result?.findings ?? []} selected={selected} onSelect={setSelected} measuring={measuring}
            onMeasured={setMeasurement} modelVisible={inputs?.model.has_view ?? null} modelActive={inputs?.model.active ?? true}
            onToggleMeasure={() => setMeasuring((on) => !on)}>
            {measuring && (
              <MeasurePanel profileId={profileId} measurement={measurement} onError={setError} onClose={() => setMeasuring(false)}
                onSaved={(update) => { setMeasuring(false); applyUpdate(update, "Measurement saved."); setTab("assistant"); }} />
            )}
          </ShipViewer>
          {selected && <FindingDetail key={`${selected.rule_id}|${selected.subject}`} finding={selected} onClose={closeDetail} onAnswer={answer} onReview={review} onUndo={undo} />}
        </div>
        <aside className="side">
          <div className="tabs" role="tablist" aria-label="Side panel">
            <button type="button" role="tab" aria-selected={tab === "assistant"} onClick={() => setTab("assistant")}>Assistant</button>
            <button type="button" role="tab" aria-selected={tab === "inputs"} onClick={() => setTab("inputs")}>
              Inputs{inputs ? ` (${(inputs.model.active ? 1 : 0) + inputs.files.length})` : ""}
            </button>
            <button type="button" role="tab" aria-selected={tab === "review"} onClick={() => setTab("review")}>Review</button>
            <button type="button" role="tab" aria-selected={tab === "card"} onClick={() => setTab("card")}>Ship card</button>
          </div>
          <div className="tab-body" hidden={tab !== "assistant"}>
            <Assistant profileId={profileId} lines={lines} setLines={setLines} onDone={applyUpdate}
              question={question} onClearQuestion={() => setQuestion("")} />
          </div>
          <div className="tab-body" hidden={tab !== "inputs"}>
            <InputsPanel profileId={profileId} inputs={inputs} result={result} note={inputsNote} onDone={onInputsDone} onError={setError} onStartOver={startOver} />
          </div>
          <div className="tab-body" hidden={tab !== "review"}>
            <ReviewPanel status={learning} queue={queue} reviewer={reviewer} onReviewer={nameReviewer} onPick={pick} onUndo={undo} />
          </div>
          <div className="tab-body" hidden={tab !== "card"}>
            <ShipCardPanel version={cardVersion} profileId={profileId} reviewer={reviewer} onUseCard={() => setProfileId("card")} onSaved={onCardSaved} onError={setError} />
          </div>
        </aside>
      </main>
    </div>
  );
}
