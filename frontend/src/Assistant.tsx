import { FormEvent, useEffect, useRef, useState } from "react";
import { api, UpdateResponse } from "./api";

export interface ChatLine {
  role: "engineer" | "assistant" | "system";
  text: string;
}

const SUGGESTIONS = [
  "What are the most important issues?",
  "What information do you still need from me?",
  "Why isn't this rule in scope?",
];

export default function Assistant({ profileId, lines, setLines, onDone, question, onClearQuestion }: {
  profileId: string;
  lines: ChatLine[];
  setLines: React.Dispatch<React.SetStateAction<ChatLine[]>>;
  onDone: (update: UpdateResponse, intro: string) => void;
  question: string;
  onClearQuestion: () => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const log = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { log.current?.scrollTo(0, log.current.scrollHeight); }, [lines, busy]);
  useEffect(() => { if (question) input.current?.focus(); }, [question]);

  const send = async (message: string) => {
    if (!message.trim() || busy) return;
    const shown = message.trim();
    const sent = question ? `Question from the tool: ${question}\nEngineer's answer: ${shown}` : shown;
    setText("");
    onClearQuestion();
    setLines((current) => [...current, { role: "engineer", text: shown }]);
    setBusy(true);
    try {
      onDone(await api.chat(profileId, sent), "");
    } catch (e) {
      setLines((current) => [...current, { role: "system", text: e instanceof Error ? e.message : "The message couldn't be sent." }]);
    } finally {
      setBusy(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    send(text);
  };

  return (
    <div className="assistant">
      <div className="chat-log" ref={log} aria-live="polite">
        {lines.length === 0 && (
          <div className="chat-empty">
            <p>Ask about a result, or give a missing value, like "Each liferaft is rated for 16 persons". The checks rerun by themselves.</p>
            <div className="suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <button type="button" key={suggestion} disabled={busy} onClick={() => send(suggestion)}>{suggestion}</button>
              ))}
            </div>
          </div>
        )}
        {lines.map((line, index) => <p key={index} className={`line ${line.role}`}>{line.text}</p>)}
        {busy && <p className="line system" role="status">Working on it.</p>}
      </div>
      {question && (
        <div className="answering">
          <span><strong>Answering:</strong> {question}</span>
          <button type="button" className="ghost" onClick={onClearQuestion} aria-label="Stop answering this question">✕</button>
        </div>
      )}
      <form onSubmit={submit}>
        <input ref={input} aria-label="Message" value={text} onChange={(e) => setText(e.target.value)}
          placeholder={question ? "Type your answer" : "Ask or add information"} />
        <button type="submit" className="primary" disabled={busy || !text.trim()}>Send</button>
      </form>
    </div>
  );
}
