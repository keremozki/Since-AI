import { useEffect, useState } from "react";
import { Decision, Finding } from "./api";
import { STATUS_LABEL, StatusIcon } from "./shared";

export default function FindingDetail({ finding, onClose, onAnswer, onReview }: {
  finding: Finding;
  onClose: () => void;
  onAnswer: (question: string) => void;
  onReview: (finding: Finding, decision: Decision, value?: number, unit?: string) => void;
}) {
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("mm");

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows: [string, string][] = [
    ["Where", finding.where],
    ["Rule", finding.rule_source],
    ["Why it applies", finding.why],
    ["Confidence", finding.confidence.charAt(0).toUpperCase() + finding.confidence.slice(1)],
    ["P(real fail)", finding.p_real !== null ? finding.p_real.toFixed(2) : ""],
  ];

  return (
    <section className="detail" aria-label="Selected result">
      <header>
        <h2><StatusIcon status={finding.status} size={16} /> {finding.label}<small>{STATUS_LABEL[finding.status]}</small></h2>
        <button type="button" className="ghost" onClick={onClose} aria-label="Close details">✕</button>
      </header>

      <div className="compare">
        <div><span>Found</span><p>{finding.measured}</p></div>
        <div><span>Required</span><p>{finding.required}</p></div>
        {finding.gap && <div className="gap"><span>Gap</span><p>{finding.gap}</p></div>}
      </div>

      {finding.status === "cant_tell" && finding.question && (
        <div className="callout">
          <p><strong>Needed:</strong> {finding.question}</p>
          <button type="button" className="primary" onClick={() => onAnswer(finding.question)}>Answer this</button>
        </div>
      )}
      {finding.status === "conflict" && (
        <div className="callout">
          <p><strong>To resolve:</strong> correct the wrong source, then add it again under Inputs. Or remove the wrong source there.</p>
        </div>
      )}
      {finding.unconfirmed_label && <p className="unconfirmed-note">{finding.unconfirmed_label}.</p>}
      {finding.gate_note && <p className="unconfirmed-note">{finding.gate_note}</p>}

      {finding.reviewable && (
        <div className="review" aria-label="Engineer review">
          <p>Is this fail real? Your answer trains the confidence model.</p>
          <button type="button" onClick={() => onReview(finding, "accept")}>Accept: real fail</button>
          <button type="button" onClick={() => onReview(finding, "reject")}>Reject: misread</button>
          <span>
            <input type="number" value={value} onChange={(e) => setValue(e.target.value)} placeholder="Correct value" aria-label="Correct value" />
            <select value={unit} onChange={(e) => setUnit(e.target.value)} aria-label="Unit">
              <option>mm</option><option>in</option><option>m</option><option>ft</option>
            </select>
            <button type="button" disabled={!value} onClick={() => { onReview(finding, "correct", Number(value), unit); setValue(""); }}>Correct</button>
          </span>
        </div>
      )}

      <dl>
        {rows.filter(([, value]) => value).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}
        {finding.sources.length > 0 && (
          <div><dt>Source</dt><dd>{finding.sources.map((source) => <span key={source} className="line-item">{source}</span>)}</dd></div>
        )}
        {finding.assumptions.length > 0 && (
          <div><dt>Assumptions</dt><dd>{finding.assumptions.map((text) => <span key={text} className="line-item">{text}</span>)}</dd></div>
        )}
      </dl>
    </section>
  );
}
