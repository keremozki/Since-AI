import { Finding, Inputs, Status } from "./api";

export const STATUS_ORDER: Status[] = ["fail", "conflict", "cant_tell", "needs_review", "pass", "not_applicable"];

export const STATUS_LABEL: Record<Status, string> = {
  fail: "Failed",
  conflict: "Conflict",
  cant_tell: "Can't tell",
  needs_review: "Needs review",
  pass: "Passed",
  not_applicable: "Not applicable",
};

export const STATUS_COLOR: Record<Status, string> = {
  fail: "var(--fail)",
  conflict: "var(--conflict)",
  cant_tell: "var(--cant-tell)",
  needs_review: "var(--needs-review)",
  pass: "var(--pass)",
  not_applicable: "var(--not-applicable)",
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
      {status === "needs_review" && <path d="M5 8h6M8 5v6" {...common} />}
      {status === "not_applicable" && <path d="M5 8h6" {...common} />}
    </svg>
  );
}

const TIER_MEANING: Record<string, string> = {
  A: "Exact data, or confirmed by an engineer. Can back a result.",
  B: "Two independent readings agree. Can back a result.",
  C: "One reading only. Can't back a result until an engineer confirms it.",
  D: "A problem: the readings disagree or the value is unusable. Can't back a result.",
};

/** How far a value can be trusted, always with a letter, so colour is never the only signal. */
export function TierBadge({ tier }: { tier: string }) {
  if (!tier) return null;
  return <span className={`tier tier-${tier}`} title={TIER_MEANING[tier] ?? ""} aria-label={`Trust level ${tier}: ${TIER_MEANING[tier] ?? ""}`}>{tier}</span>;
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
