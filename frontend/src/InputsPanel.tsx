import { DragEvent, useRef, useState } from "react";
import { api, Inputs, RunResult, UpdateResponse } from "./api";
import { originsOf } from "./shared";

const MAX_LISTED_FACTS = 5;

export default function InputsPanel({ profileId, inputs, result, note, onDone, onError, onStartOver }: {
  profileId: string;
  inputs: Inputs | null;
  result: RunResult | null;
  note: string;
  onDone: (update: UpdateResponse, intro: string) => void;
  onError: (text: string) => void;
  onStartOver: () => void;
}) {
  const [busy, setBusy] = useState("");
  const [pages, setPages] = useState("");
  const [dragging, setDragging] = useState(false);
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
    if (!file || busy) return;
    if (file.name.toLowerCase().endsWith(".nwd")) {
      act("Uploading the 3D model.", () => api.importModel(profileId, file, (fraction) => {
        setBusy(fraction < 1 ? `Uploading the 3D model: ${Math.round(fraction * 100)}%` : "Reading the 3D model.");
      }), (u) => `${file.name} imported: ${u.inputs.model.parts} parts.`);
    } else {
      act("Reading the file.", () => api.upload(profileId, file, pages),
        (u) => `${file.name} read${u.cached ? " from saved results, at no cost" : ""}: ${u.recorded.length} new fact(s).`);
    }
  };

  const drop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    addFile(event.dataTransfer.files[0]);
  };

  const removeGroup = (group: "measurements" | "chat", label: string) => {
    if (window.confirm(`Remove all ${label}? You can't undo this.`)) {
      act(`Removing ${label}.`, () => api.removeGroup(profileId, group), () => `${label.charAt(0).toUpperCase()}${label.slice(1)} removed.`);
    }
  };

  const resultsFrom = (name: string) => (result?.findings ?? []).filter((f) => originsOf(f, inputs).includes(name)).length;
  const disabled = Boolean(busy);
  const current = inputs?.model;
  const hasAdded = Boolean(inputs?.files.length || inputs?.measurements || inputs?.chat);

  return (
    <div className="inputs">
      <label className={dragging ? "dropzone over" : "dropzone"} onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)} onDrop={drop}>
        <strong>Add a file</strong>
        <span>Drop it here, or click to choose</span>
        <small>3D model: .nwd{current?.active ? " (replaces the current one)" : ""}<br />Drawing or document: PDF, PNG, JPG, WEBP, MD, TXT</small>
        <input ref={picker} className="visually-hidden" type="file" accept=".nwd,.pdf,.png,.jpg,.jpeg,.webp,.md,.txt"
          disabled={disabled} onChange={(e) => addFile(e.target.files?.[0])} />
      </label>
      <label className="pages">PDF pages to read <small>(optional)</small>
        <input placeholder="All, or like 3,4" value={pages} onChange={(e) => setPages(e.target.value)} />
      </label>
      {busy && <p className="status-line" role="status">{busy}</p>}
      {!busy && note && <p className="status-line done" role="status">{note}</p>}

      <h2>In this check</h2>
      <ul>
        {current?.active && (
          <li>
            <span><strong>{current.name}</strong><small>3D model · {current.parts} parts · {resultsFrom(current.name)} result(s){current.has_view ? "" : " · no 3D view"}</small></span>
            <button type="button" disabled={disabled} aria-label={`Remove ${current.name}`}
              onClick={() => {
                if (window.confirm(`Remove ${current.name}? Any measurements taken on it are deleted too. To use the model again, you'll need to upload the file.`)) {
                  act("Removing the model.", () => api.removeModel(profileId), () => `${current.name} removed.`);
                }
              }}>Remove</button>
          </li>
        )}
        {current && !current.active && (
          <li>
            <span><strong>No 3D model</strong><small>Add a .nwd file above to include one.</small></span>
          </li>
        )}
        {inputs?.files.map((file) => (
          <li key={file.name}>
            <span>
              <strong>{file.name}</strong>
              <small>{file.facts} fact(s) read · {resultsFrom(file.name)} result(s)</small>
              {file.facts > 0 && resultsFrom(file.name) === 0 && (
                <>
                  {file.read.slice(0, MAX_LISTED_FACTS).map((text) => <small key={text}>{text}</small>)}
                  {file.read.length > MAX_LISTED_FACTS && <small>And {file.read.length - MAX_LISTED_FACTS} more.</small>}
                  <small className="unused">Not in a result yet. A check may still need other values, or may not apply to this ship. Values are also compared across files.</small>
                </>
              )}
            </span>
            <button type="button" disabled={disabled} aria-label={`Remove ${file.name}`}
              onClick={() => act("Removing the file.", () => api.removeFile(profileId, file.name), () => `${file.name} removed.`)}>Remove</button>
          </li>
        ))}
        {Boolean(inputs?.measurements) && (
          <li>
            <span><strong>3D measurements</strong><small>{inputs!.measurements} saved</small></span>
            <button type="button" disabled={disabled} aria-label="Remove 3D measurements" onClick={() => removeGroup("measurements", "3D measurements")}>Remove</button>
          </li>
        )}
        {Boolean(inputs?.chat) && (
          <li>
            <span><strong>Chat answers</strong><small>{inputs!.chat} fact(s) recorded</small></span>
            <button type="button" disabled={disabled} aria-label="Remove chat answers" onClick={() => removeGroup("chat", "chat answers")}>Remove</button>
          </li>
        )}
      </ul>
      {hasAdded && (
        <button type="button" className="link-button" disabled={disabled} onClick={() => {
          if (window.confirm("Remove all added files, measurements, and chat answers? The 3D model stays.")) onStartOver();
        }}>Remove everything except the 3D model</button>
      )}
    </div>
  );
}
