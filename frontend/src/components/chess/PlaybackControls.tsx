import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import { cn } from "@/lib/utils";

interface PlaybackControlsProps {
  onFirst: () => void;
  onPrev: () => void;
  onNext: () => void;
  onLast: () => void;
  onTogglePlay: () => void;
  isPlaying: boolean;
  canPrev: boolean;
  canNext: boolean;
}

function ControlButton({
  label,
  onClick,
  disabled,
  primary,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex size-11 items-center justify-center rounded-lg border transition-all disabled:cursor-not-allowed disabled:opacity-35",
        primary
          ? "border-transparent bg-primary text-primary-foreground shadow-[var(--glow-accent)] hover:brightness-110"
          : "border-border bg-secondary text-foreground hover:bg-primary/25 hover:text-accent",
      )}
    >
      {children}
    </button>
  );
}

export function PlaybackControls({
  onFirst,
  onPrev,
  onNext,
  onLast,
  onTogglePlay,
  isPlaying,
  canPrev,
  canNext,
}: PlaybackControlsProps) {
  return (
    <div className="flex items-center justify-center gap-2">
      <ControlButton label="First move" onClick={onFirst} disabled={!canPrev}>
        <ChevronFirst className="size-5" />
      </ControlButton>
      <ControlButton label="Previous move" onClick={onPrev} disabled={!canPrev}>
        <ChevronLeft className="size-5" />
      </ControlButton>
      <ControlButton
        label={isPlaying ? "Pause auto-play" : "Auto-play"}
        onClick={onTogglePlay}
        primary
        disabled={!canNext && !isPlaying}
      >
        {isPlaying ? <Pause className="size-5" /> : <Play className="size-5" />}
      </ControlButton>
      <ControlButton label="Next move" onClick={onNext} disabled={!canNext}>
        <ChevronRight className="size-5" />
      </ControlButton>
      <ControlButton label="Last move" onClick={onLast} disabled={!canNext}>
        <ChevronLast className="size-5" />
      </ControlButton>
    </div>
  );
}
