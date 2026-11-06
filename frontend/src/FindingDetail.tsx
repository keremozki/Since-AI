import { useEffect } from "react";
import { Finding } from "./api";
import { STATUS_LABEL, StatusIcon } from "./shared";

export default function FindingDetail({ finding, onClose, onAnswer }: {
  finding: Finding;
  onClose: () => void;
  onAnswer: (question: string) => void;
}) {
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
