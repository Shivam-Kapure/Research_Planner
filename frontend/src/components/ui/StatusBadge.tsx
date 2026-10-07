import type { RunStatus } from "@/lib/api/types";
import { STATUS_META, type Tone } from "@/lib/runs/status";
import { AlertIcon, CheckIcon, ClockIcon, CrossIcon, DotIcon, MinusIcon } from "./icons";

const ICONS: Record<RunStatus, (p: { className?: string }) => React.ReactNode> = {
  queued: ClockIcon,
  running: DotIcon,
  completed: CheckIcon,
  completed_with_limitations: AlertIcon,
  partial: AlertIcon,
  failed: CrossIcon,
  cancelled: MinusIcon,
};

/** Status is conveyed by the label and icon; colour only reinforces it. */
export function StatusBadge({ status }: { status: RunStatus }) {
  const meta = STATUS_META[status];
  const Icon = ICONS[status];
  return (
    <span className={`badge tone-${meta.tone}`} data-status={status}>
      <Icon className="badge__icon" />
      {meta.label}
    </span>
  );
}

export function ToneBadge({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  const Icon = tone === "positive" ? CheckIcon : tone === "negative" ? CrossIcon : tone === "caution" ? AlertIcon : DotIcon;
  return (
    <span className={`badge tone-${tone}`}>
      <Icon className="badge__icon" />
      {children}
    </span>
  );
}
