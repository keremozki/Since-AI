import { useCallback, useEffect, useState } from "react";
import { api, Finding, Inputs, Profile, RunResult, Spend, UpdateResponse } from "./api";
import Assistant, { ChatLine } from "./Assistant";
import FindingDetail from "./FindingDetail";
import InputsPanel from "./InputsPanel";
import MeasurePanel from "./MeasurePanel";
import Results from "./Results";
import ShipViewer, { Measurement } from "./ShipViewer";

type Tab = "assistant" | "inputs";

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

  const refresh = useCallback(async (id: string) => {
    setError("");
    try {
      const [{ result: next, spend: nextSpend }, nextInputs] = await Promise.all([api.run(id), api.inputs()]);
      setResult(next);
      setSpend(nextSpend);
      setInputs(nextInputs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The checks couldn't run.");
    }
  }, []);

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
  }, []);

  const onInputsDone = useCallback((update: UpdateResponse, intro: string) => {
    setMeasuring(false);
    setInputsNote(intro);
    applyUpdate(update, intro);
  }, [applyUpdate]);

  const startOver = async () => {
    await api.reset();
    setLines([]);
    setMeasurement(null);
    setMeasuring(false);
    setSelected(null);
    setQuestion("");
    setInputsNote("Added files, measurements, and chat answers removed.");
    refresh(profileId);
  };

  const answer = useCallback((text: string) => {
    setQuestion(text);
    setTab("assistant");
  }, []);
  const closeDetail = useCallback(() => setSelected(null), []);

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
          {spend && <span className="spend" title={`${spend.calls} AI calls. AI features stop at the cap.`}>AI spend ${spend.spent_usd.toFixed(2)} of ${spend.cap_usd.toFixed(2)}</span>}
          <a className="button" href={`/api/report/${profileId}`} target="_blank" rel="noreferrer">Text report</a>
        </div>
      </header>
      {error && (
        <div className="error" role="alert">
          <span>{error}</span>
          <button type="button" className="ghost" onClick={() => setError("")} aria-label="Dismiss">✕</button>
        </div>
      )}
      <main className="layout">
        <Results result={result} selected={selected} onSelect={setSelected} />
        <div className="middle">
          <ShipViewer findings={result?.findings ?? []} selected={selected} onSelect={setSelected} measuring={measuring}
            onMeasured={setMeasurement} modelVisible={inputs?.model.has_view ?? null} modelActive={inputs?.model.active ?? true}
            onToggleMeasure={() => setMeasuring((on) => !on)}>
            {measuring && (
              <MeasurePanel profileId={profileId} measurement={measurement} onError={setError} onClose={() => setMeasuring(false)}
                onSaved={(update) => { setMeasuring(false); applyUpdate(update, "Measurement saved."); setTab("assistant"); }} />
            )}
          </ShipViewer>
          {selected && <FindingDetail finding={selected} onClose={closeDetail} onAnswer={answer} />}
        </div>
        <aside className="side">
          <div className="tabs" role="tablist" aria-label="Side panel">
            <button type="button" role="tab" aria-selected={tab === "assistant"} onClick={() => setTab("assistant")}>Assistant</button>
            <button type="button" role="tab" aria-selected={tab === "inputs"} onClick={() => setTab("inputs")}>
              Inputs{inputs ? ` (${(inputs.model.active ? 1 : 0) + inputs.files.length})` : ""}
            </button>
          </div>
          <div className="tab-body" hidden={tab !== "assistant"}>
            <Assistant profileId={profileId} lines={lines} setLines={setLines} onDone={applyUpdate}
              question={question} onClearQuestion={() => setQuestion("")} />
          </div>
          <div className="tab-body" hidden={tab !== "inputs"}>
            <InputsPanel profileId={profileId} inputs={inputs} note={inputsNote} onDone={onInputsDone} onError={setError} onStartOver={startOver} />
          </div>
        </aside>
      </main>
    </div>
  );
}
