import { ConfidenceStatus, QueueItem } from "./api";

const SAID = { accept: "read correctly", reject: "misread", unsure: "not sure" };

export default function ReviewPanel({ status, queue, reviewer, onReviewer, onPick, onUndo }: {
  status: ConfidenceStatus | null;
  queue: QueueItem[];
  reviewer: string;
  onReviewer: (name: string) => void;
  onPick: (item: QueueItem) => void;
  onUndo: (key: string) => void;
}) {
  if (!status) return <div className="learning"><p className="muted">Loading the reviews.</p></div>;
  const version = `Model v${status.model?.version ?? ""}`;
  const mode = { cold_start: "Fixed rule", model: version, simulated: `${version} (SIMULATED labels)` }[status.mode];
  return (
    <div className="learning">
      <p><strong>{mode}</strong>{status.reason && <> · {status.reason}</>}</p>
      <p className="muted">
        {status.labels_used} of {status.min_labels} answers · read correctly {status.labels_read_correctly} · misread {status.labels_misread} of {status.min_per_class} needed
        {status.labels_unsure ? ` · not sure ${status.labels_unsure}` : ""}
      </p>
      <p className="muted">AI reader lessons from misreads: {status.lessons.length}</p>
      <label>Your name <input value={reviewer} onChange={(e) => onReviewer(e.target.value)} placeholder="Saved with each answer" /></label>

      <h3>Review next</h3>
      {queue.length === 0 && <p className="muted">Nothing to review right now.</p>}
      {queue.length > 0 && (
        <ol className="queue">
          {queue.map((item) => (
            <li key={`${item.rule_id}|${item.subject}`}>
              <button type="button" onClick={() => onPick(item)}><strong>{item.label}</strong> <span>{item.measured}</span><small>{item.why_now}</small></button>
            </li>
          ))}
        </ol>
      )}

      {status.recent.length > 0 && (
        <>
          <h3>Recent answers</h3>
          <ul className="recent">
            {status.recent.map((answer) => (
              <li key={answer.key}>
                <span>{answer.subject}: {SAID[answer.decision] ?? answer.decision}
                  {answer.corrected_value !== null ? `, right value ${answer.corrected_value} ${answer.corrected_unit}` : ""}
                  {answer.reviewer ? ` (${answer.reviewer})` : ""}{answer.synthetic ? " SIMULATED" : ""}</span>
                <button type="button" onClick={() => onUndo(answer.key)}>Undo</button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
