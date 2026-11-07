export type Status = "pass" | "fail" | "conflict" | "cant_tell";

export interface Point {
  x: number;
  y: number;
  z: number;
}

export interface Finding {
  rule_id: string;
  rule_title: string;
  area: string;
  rule_source: string;
  status: Status;
  subject: string;
  label: string;
  where: string;
  measured: string;
  required: string;
  gap: string;
  why: string;
  sources: string[];
  confidence: string;
  question: string;
  assumptions: string[];
  location: Point | null;
  provisional: boolean;
  unconfirmed_label: string;
}

export interface ScopeDecision {
  rule_id: string;
  title: string;
  area: string;
  source: string;
  applies: boolean;
  reason: string;
}

export interface Profile {
  id: string;
  name: string;
  ship_type: string;
  note: string;
  use_demo_faults: boolean;
}

export interface RunResult {
  profile: Profile;
  findings: Finding[];
  scope: ScopeDecision[];
  counts: Record<Status, number>;
  summary: string;
  fact_count: number;
}

export interface Spend {
  spent_usd: number;
  cap_usd: number;
  calls: number;
}

export interface RecordedFact {
  subject: string;
  property: string;
  value: number | string;
  unit: string;
  source: { kind: string; file: string; quote: string };
  confidence: string;
}

export interface Inputs {
  model: { name: string; parts: number; has_view: boolean; active: boolean };
  files: { name: string; facts: number }[];
  measurements: number;
  chat: number;
}

export interface UpdateResponse {
  recorded: RecordedFact[];
  recorded_text: string[];
  changes: string[];
  result: RunResult;
  spend: Spend;
  inputs: Inputs;
  reply?: string;
  cached?: boolean;
  dropped?: number;
}

export interface MeasureTarget {
  subject: string;
  property: string;
  kind: string;
  meaning: string;
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed (${response.status})`);
  }
  return response.json();
}

const jsonPost = (url: string, body: unknown) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

interface SeededFaults {
  faults: number;
  caught: number;
  missed: number;
  changes_outside_the_rule: number;
}

export interface Accuracy {
  hand_checked: { total: number; correct: number; false_passes: number; false_fails: number };
  seeded_door_faults: SeededFaults;
  seeded_stair_faults: SeededFaults;
  missing_data: { checks: number; false_passes: number };
}

export const api = {
  profiles: () => fetch("/api/profiles").then((r) => parse<Profile[]>(r)),
  accuracy: () => fetch("/api/accuracy").then((r) => parse<Accuracy | null>(r)),
  run: (profile: string) => fetch(`/api/run/${profile}`).then((r) => parse<{ result: RunResult; spend: Spend }>(r)),
  vocabulary: () => fetch("/api/vocabulary").then((r) => parse<MeasureTarget[]>(r)),
  chat: (profile: string, message: string) => jsonPost("/api/chat", { profile, message }).then((r) => parse<UpdateResponse>(r)),
  upload: (profile: string, file: File, pages: string) => {
    const form = new FormData();
    form.append("profile", profile);
    form.append("file", file);
    form.append("pages", pages);
    return fetch("/api/upload", { method: "POST", body: form }).then((r) => parse<UpdateResponse>(r));
  },
  measure: (profile: string, body: unknown) =>
    jsonPost(`/api/measure?profile=${encodeURIComponent(profile)}`, body).then((r) => parse<UpdateResponse>(r)),
  reset: () => fetch("/api/reset", { method: "POST" }).then((r) => parse<{ ok: boolean }>(r)),
  inputs: () => fetch("/api/inputs").then((r) => parse<Inputs>(r)),
  removeModel: (profile: string) =>
    fetch(`/api/inputs/model?profile=${encodeURIComponent(profile)}`, { method: "DELETE" }).then((r) => parse<UpdateResponse>(r)),
  /** Uses XMLHttpRequest because fetch can't report upload progress. */
  importModel: (profile: string, file: File, onUploaded: (fraction: number) => void) =>
    new Promise<UpdateResponse>((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open("POST", `/api/inputs/model?profile=${encodeURIComponent(profile)}&name=${encodeURIComponent(file.name)}`);
      request.upload.onprogress = (event) => { if (event.lengthComputable) onUploaded(event.loaded / event.total); };
      request.onerror = () => reject(new Error("The upload failed. Is the backend running?"));
      request.onload = () => {
        let body: { detail?: string } | null = null;
        try { body = JSON.parse(request.responseText); } catch { /* Handled below. */ }
        if (request.status >= 200 && request.status < 300 && body) resolve(body as UpdateResponse);
        else reject(new Error(body?.detail ?? `Request failed (${request.status})`));
      };
      request.send(file);
    }),
  removeFile: (profile: string, name: string) =>
    fetch(`/api/inputs/files?profile=${encodeURIComponent(profile)}&name=${encodeURIComponent(name)}`, { method: "DELETE" }).then((r) => parse<UpdateResponse>(r)),
  removeGroup: (profile: string, group: "measurements" | "chat") =>
    fetch(`/api/inputs/group/${group}?profile=${encodeURIComponent(profile)}`, { method: "DELETE" }).then((r) => parse<UpdateResponse>(r)),
};
