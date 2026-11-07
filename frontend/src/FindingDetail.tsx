import { useEffect, useState } from "react";
import { api, Decision, Finding } from "./api";
import { STATUS_LABEL, StatusIcon } from "./shared";

const TO_MM: Record<string, number> = { mm: 1, in: 25.4, m: 1000, ft: 304.8 };

export default function FindingDetail({ finding, onClose, onAnswer, onReview }: {
  finding: Finding;
  onClose: () => void;
  onAnswer: (question: string) => void;
  onReview: (finding: Finding, decision: Decision, value?: number, unit?: string) => void;
}) {
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("mm");
  const [misread, setMisread] = useState(false);
  const [cropOk, setCropOk] = useState(true);
  const number = Number(value);
  const inMm = value && Number.isFinite(number) ? number * TO_MM[unit] : null;

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
                <input type="number" value={value} onChange={(e) => setValue(e.target.value)} placeholder="If known" />
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
