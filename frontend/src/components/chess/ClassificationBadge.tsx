import type { MoveClassification } from "@/lib/chess-api";
import { cn } from "@/lib/utils";
import { MoveEvaluationSymbol } from "./MoveEvaluationSymbol";

interface Meta {
  label: string;
  description: string;
  text: string;
  ring: string;
  bg: string;
}

export const CLASSIFICATION_META: Record<MoveClassification, Meta> = {
  brilliant: {
    label: "Brilliant",
    description:
      "A highly strong move that initially looks like a bad idea, usually involving a piece sacrifice, but fundamentally improves or winningly alters the position after deep engine calculation.",
    text: "text-brilliant",
    ring: "ring-brilliant/40",
    bg: "bg-brilliant/12",
  },
  great: {
    label: "Great",
    description:
      "The single, unique move required to maintain a winning advantage, hold a difficult draw, or navigate a sharp, critical position where all other choices fail.",
    text: "text-accent",
    ring: "ring-accent/40",
    bg: "bg-accent/12",
  },
  best: {
    label: "Best",
    description: "The engine's top-recommended move at the analyzed depth.",
    text: "text-best",
    ring: "ring-best/40",
    bg: "bg-best/12",
  },
  excellent: {
    label: "Excellent",
    description:
      "Not the absolute top engine choice, but still highly accurate, keeping the evaluation steady and fully maintaining the player's strategic advantage or defense.",
    text: "text-accent",
    ring: "ring-accent/40",
    bg: "bg-accent/12",
  },
  good: {
    label: "Good",
    description:
      "A standard, acceptable and safe move that does not ruin the position, though it may slightly miss a sharper or more punishing line.",
    text: "text-good",
    ring: "ring-good/40",
    bg: "bg-good/12",
  },
  book: {
    label: "Book",
    description:
      "A move that perfectly follows established, recognized opening theory and historical grandmaster databases.",
    text: "text-best",
    ring: "ring-best/40",
    bg: "bg-best/12",
  },
  inaccuracy: {
    label: "Inaccuracy",
    description:
      "A suboptimal choice that does not completely throw away the game, but noticeably drops the evaluation score and gives the opponent a slight advantage or an easier path forward.",
    text: "text-inaccuracy",
    ring: "ring-inaccuracy/40",
    bg: "bg-inaccuracy/12",
  },
  mistake: {
    label: "Mistake",
    description:
      "A clear error resulting in a significant loss of material, positional control, or a completely vanished winning advantage.",
    text: "text-mistake",
    ring: "ring-mistake/40",
    bg: "bg-mistake/12",
  },
  miss: {
    label: "Miss",
    description:
      "A failure to notice a direct, forcing tactical opportunity such as an immediate checkmate pattern, a free piece, or an instant winning combination.",
    text: "text-blunder",
    ring: "ring-blunder/40",
    bg: "bg-blunder/12",
  },
  blunder: {
    label: "Blunder",
    description:
      "A disastrous error that immediately turns a winning or equal game into a completely lost one, usually by hanging a major piece or allowing a forced tactical sequence.",
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

  return (
    <span
      title={`${meta.label}: ${meta.description}`}
      aria-label={`${meta.label}: ${meta.description}`}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1",
        meta.bg,
        meta.text,
        meta.ring,
        className,
      )}
    >
      <MoveEvaluationSymbol classification={classification} className="size-3" />
      {!compact && meta.label}
    </span>
  );
}
