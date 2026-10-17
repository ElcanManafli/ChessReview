import type { CSSProperties } from "react";
import type { MoveClassification } from "@/lib/chess-api";
import { cn } from "@/lib/utils";

const QUALITY_ICONS: Record<MoveClassification, string> = {
  brilliant: "brilliant.png",
  great: "great.png",
  best: "best.png",
  excellent: "excellent.png",
  good: "good.png",
  book: "book.png",
  inaccuracy: "inaccuracy.png",
  mistake: "mistake.png",
  blunder: "blunder.png",
  miss: "miss.png",
};

const QUALITY_LABELS: Record<MoveClassification, string> = {
  brilliant: "Brilliant",
  great: "Great",
  best: "Best",
  excellent: "Excellent",
  good: "Good",
  book: "Book",
  inaccuracy: "Inaccuracy",
  mistake: "Mistake",
  blunder: "Blunder",
  miss: "Miss",
};

export function MoveEvaluationSymbol({
  classification,
  className,
  style,
}: {
  classification: MoveClassification;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <span
      role="img"
      aria-label={`${QUALITY_LABELS[classification]} move`}
      title={`${QUALITY_LABELS[classification]} move`}
      className={cn("move-evaluation-symbol", className)}
      style={style}
    >
      <img
        src={`${import.meta.env.BASE_URL}move-quality/${QUALITY_ICONS[classification]}`}
        alt=""
        draggable={false}
      />
    </span>
  );
}
