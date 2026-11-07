import { Finding, Inputs, Status } from "./api";

export const STATUS_ORDER: Status[] = ["fail", "conflict", "cant_tell", "pass"];

export const STATUS_LABEL: Record<Status, string> = {
  fail: "Failed",
  conflict: "Conflict",
  cant_tell: "Can't tell",
  pass: "Passed",
};

export const STATUS_COLOR: Record<Status, string> = {
  fail: "var(--fail)",
  conflict: "var(--conflict)",
  cant_tell: "var(--cant-tell)",
  pass: "var(--pass)",
};

/** Each result has its own shape, so that colour is never the only signal. */
export function StatusIcon({ status, size = 14 }: { status: Status; size?: number }) {
  const common = { fill: "none", stroke: "#fff", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className="status-icon">
      {status === "conflict"
        ? <path d="M8 1 15.5 14.5H.5Z" fill={STATUS_COLOR[status]} />
        : <circle cx="8" cy="8" r="8" fill={STATUS_COLOR[status]} />}
      {status === "fail" && <path d="m5 5 6 6m0-6-6 6" {...common} />}
      {status === "pass" && <path d="m4.5 8.5 2.5 2.5 4.5-5.5" {...common} />}
      {status === "conflict" && <path d="M8 6v4m0 2.2v.1" {...common} />}
      {status === "cant_tell" && <path d="M6 6.2a2 2 0 1 1 2.8 1.9c-.6.3-.8.7-.8 1.2m0 2.2v.1" {...common} />}
    </svg>
  );
}

export const NO_SOURCE = "No source yet";

/** Where a result's data came from, in the names shown in the Inputs tab. */
export function originsOf(finding: Finding, inputs: Inputs | null): string[] {
  const names = [inputs?.model.name ?? "", ...(inputs?.files.map((file) => file.name) ?? [])].filter(Boolean);
  const origins = new Set<string>();
  for (const source of finding.sources) {
    for (const name of names) if (source.includes(name)) origins.add(name);
    if (source.includes("Engineer in chat")) origins.add("Chat answer");
    if (source.includes("3D measurement")) origins.add("3D measurement");
    if (source.includes("Seeded demo fault")) origins.add("Seeded test fault");
  }
  return [...origins];
}

/** "Main Deck (19.1 ft above baseline)" becomes "Main Deck". */
export const shortDeck = (where: string) => where.split(" (")[0];
