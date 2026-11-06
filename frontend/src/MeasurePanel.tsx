import { useEffect, useState } from "react";
import { api, MeasureTarget, UpdateResponse } from "./api";
import { Measurement } from "./ShipViewer";

const INCHES_PER_METRE = 39.3701;
type Direction = "straight" | "vertical" | "horizontal";

function distance(m: Measurement, direction: Direction): number {
  const dx = m.a.x - m.b.x, dy = m.a.y - m.b.y, dz = m.a.z - m.b.z;
  if (direction === "vertical") return Math.abs(dz);
  if (direction === "horizontal") return Math.hypot(dx, dy);
  return Math.hypot(dx, dy, dz);
}

export default function MeasurePanel({ profileId, measurement, onSaved, onError, onClose }: {
  profileId: string;
  measurement: Measurement | null;
  onSaved: (update: UpdateResponse) => void;
  onError: (text: string) => void;
  onClose: () => void;
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
      onSaved(await api.measure(profileId, {
        subject: needsDoor ? `door-number:${doorNumber}` : chosen.subject,
        property: chosen.property,
        value: Number((inches / INCHES_PER_METRE).toFixed(3)),
        unit: "m",
        a: measurement.a,
        b: measurement.b,
        note: `${direction} distance`,
      }));
    } catch (e) {
      onError(e instanceof Error ? e.message : "The measurement couldn't be saved.");
    }
  };

  return (
    <div className="measure-panel" role="group" aria-label="Measure in 3D">
      <header>
        <strong>Measure</strong>
        <button type="button" className="ghost" onClick={onClose} aria-label="Stop measuring">✕</button>
      </header>
      {!measurement && <p>Click two points on the ship. Slice the ship by deck to see inside.</p>}
      {measurement && (
        <>
          <p className="measure-value">{(inches / INCHES_PER_METRE).toFixed(3)} m <small>{inches.toFixed(1)} in</small></p>
          <div className="segments" role="group" aria-label="Direction">
            {(["straight", "vertical", "horizontal"] as Direction[]).map((d) => (
              <button type="button" key={d} aria-pressed={direction === d} onClick={() => setDirection(d)}>
                {d.charAt(0).toUpperCase() + d.slice(1)}
              </button>
            ))}
          </div>
          <label>What did you measure?
            <select value={target} onChange={(e) => setTarget(Number(e.target.value))}>
              {targets.map((t, i) => <option key={`${t.subject}${t.property}`} value={i}>{t.meaning}</option>)}
            </select>
          </label>
          {needsDoor && (
            <label>Door number
              <input inputMode="numeric" value={doorNumber} onChange={(e) => setDoorNumber(e.target.value.replace(/\D/g, ""))} />
            </label>
          )}
          <button type="button" className="primary" disabled={needsDoor && !doorNumber} onClick={save}>Save and rerun checks</button>
          <p className="muted small">Click again to start a new measurement.</p>
        </>
      )}
    </div>
  );
}
