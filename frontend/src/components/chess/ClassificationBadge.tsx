import {
  Sparkles,
  Check,
  ThumbsUp,
  AlertTriangle,
  XCircle,
  Skull,
  BookOpen,
  type LucideIcon,
} from "lucide-react";
import type { MoveClassification } from "@/lib/chess-api";
import { cn } from "@/lib/utils";

interface Meta {
  label: string;
  icon: LucideIcon;
  text: string;
  ring: string;
  bg: string;
}

export const CLASSIFICATION_META: Record<MoveClassification, Meta> = {
  book: {
    label: "Book",
    icon: BookOpen,
    text: "text-best",
    ring: "ring-best/40",
    bg: "bg-best/12",
  },
  brilliant: {
    label: "Brilliant",
    icon: Sparkles,
    text: "text-brilliant",
    ring: "ring-brilliant/40",
    bg: "bg-brilliant/12",
  },
  great: {
    label: "Great",
    icon: Sparkles,
    text: "text-accent",
    ring: "ring-accent/40",
    bg: "bg-accent/12",
  },
  best: {
    label: "Best Move",
    icon: Check,
    text: "text-best",
    ring: "ring-best/40",
    bg: "bg-best/12",
  },
  good: {
    label: "Good",
    icon: ThumbsUp,
    text: "text-good",
    ring: "ring-good/40",
    bg: "bg-good/12",
  },
  inaccuracy: {
    label: "Inaccuracy",
    icon: AlertTriangle,
    text: "text-inaccuracy",
    ring: "ring-inaccuracy/40",
    bg: "bg-inaccuracy/12",
  },
  mistake: {
    label: "Mistake",
    icon: XCircle,
    text: "text-mistake",
    ring: "ring-mistake/40",
    bg: "bg-mistake/12",
  },
  blunder: {
    label: "Blunder",
    icon: Skull,
    text: "text-blunder",
    ring: "ring-blunder/40",
    bg: "bg-blunder/12",
  },
  missed_win: {
    label: "Missed Win",
    icon: XCircle,
    text: "text-blunder",
    ring: "ring-blunder/40",
    bg: "bg-blunder/12",
  },
};

export function ClassificationBadge({
  classification,
  compact = false,
  className,
}: {
  classification: MoveClassification;
  compact?: boolean;
  className?: string;
}) {
  const meta = CLASSIFICATION_META[classification];
  const Icon = meta.icon;

  return (
    <span
      title={meta.label}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1",
        meta.bg,
        meta.text,
        meta.ring,
        className,
      )}
    >
      <Icon className="size-3" strokeWidth={2.5} />
      {!compact && meta.label}
    </span>
  );
}
