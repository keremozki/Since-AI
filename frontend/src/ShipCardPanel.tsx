import { useEffect, useState } from "react";
import { api, CardFieldInfo, ShipCardView } from "./api";
import { TierBadge } from "./shared";

function FieldForm({ info, onSave, onCancel, saveLabel }: {
  info: CardFieldInfo;
  onSave: (value: string, unit: string) => void;
  onCancel?: () => void;
  saveLabel: string;
}) {
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("m");
  const label = `Value for ${info.label}`;
  return (
    <form className="card-form" onSubmit={(e) => { e.preventDefault(); if (value.trim()) onSave(value.trim(), info.kind === "length" ? unit : ""); }}>
      {info.choices.length > 0 ? (
        <select aria-label={label} value={value} onChange={(e) => setValue(e.target.value)}>
          <option value="">Choose</option>
          {info.choices.map((choice) => <option key={choice} value={choice}>{choice.replace(/_/g, " ")}</option>)}
        </select>
      ) : (
        <input aria-label={label} type={info.kind === "date" ? "date" : info.kind === "text" ? "text" : "number"} step="any" value={value} onChange={(e) => setValue(e.target.value)} />
      )}
      {info.kind === "length" && (
        <select aria-label="Unit" value={unit} onChange={(e) => setUnit(e.target.value)}>
          <option>m</option><option>ft</option><option>mm</option><option>in</option>
        </select>
      )}
      <button type="submit" className="primary" disabled={!value.trim()}>{saveLabel}</button>
      {onCancel && <button type="button" className="ghost" onClick={onCancel}>Cancel</button>}
    </form>
  );
}

export default function ShipCardPanel({ version, profileId, reviewer, onUseCard, onSaved, onError }: {
  version: number;
  profileId: string;
  reviewer: string;
  onUseCard: () => void;
  onSaved: () => void;
  onError: (text: string) => void;
}) {
  const [view, setView] = useState<ShipCardView | null>(null);
  const [editing, setEditing] = useState("");

  useEffect(() => { api.shipCard().then(setView).catch((e) => onError(e instanceof Error ? e.message : "The ship card couldn't load.")); }, [version, onError]);

  if (!view) return <div className="ship-card"><p className="muted">Loading the ship card.</p></div>;

  const save = async (field: string, value: string, unit: string) => {
    onError("");
    try {
      await api.confirmCard({ field, value, unit, by: reviewer.trim() || "Engineer" });
      setEditing("");
      setView(await api.shipCard());
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : "The value couldn't be saved.");
    }
  };

  const open = view.missing.filter((item) => view.fields[item.field]);
  const known = Object.entries(view.card.fields).filter(([key, field]) => field.value !== null && view.fields[key]);

  return (
    <div className="ship-card">
      <p className="muted">The ship's type, size, persons, voyage and dates decide which rules apply, each with its clause. Nothing is assumed: a missing value stays a question.</p>
      {profileId !== "card" && <button type="button" className="primary" onClick={onUseCard}>Check with this ship card</button>}

      <h3>Questions ({open.length})</h3>
      {open.length === 0 && <p className="muted">Nothing is missing.</p>}
      <ul>
        {open.map((item) => (
          <li key={item.field}>
            <strong>{item.question}</strong>
            <small>Needed by: {item.rules.join(", ")}</small>
            <FieldForm info={view.fields[item.field]} saveLabel="Save" onSave={(value, unit) => save(item.field, value, unit)} />
          </li>
        ))}
      </ul>

      <h3>On the card ({known.length})</h3>
      {known.length === 0 && <p className="muted">Add drawings or a specification under Inputs, or answer the questions above.</p>}
      <ul>
        {known.map(([key, field]) => (
          <li key={key}>
            <span className="card-row">
              <TierBadge tier={field.tier} />
              <span><strong>{view.fields[key].label}: {String(field.value).replace(/_/g, " ")}{field.unit ? ` ${field.unit}` : ""}</strong>
                <small>{field.confirmed ? `Confirmed by ${field.confirmed_by}` : field.source}{field.note ? ` · ${field.note}` : ""}</small></span>
              {editing !== key && <button type="button" onClick={() => setEditing(key)}>Change</button>}
            </span>
            {editing === key && <FieldForm info={view.fields[key]} saveLabel="Save" onCancel={() => setEditing("")} onSave={(value, unit) => save(key, value, unit)} />}
          </li>
        ))}
      </ul>
      {view.card.suggestions.length > 0 && (
        <>
          <h3>Worth checking</h3>
          <ul>{view.card.suggestions.map((s) => <li key={s.field + s.text}><small>{s.text}</small></li>)}</ul>
        </>
      )}
    </div>
  );
}
