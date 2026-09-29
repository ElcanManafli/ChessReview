import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Crown, Sparkles, ArrowRight, AlertCircle, FileText } from "lucide-react";
import { AnalysisBoard } from "@/components/chess/AnalysisBoard";
import { analyzePgn, ANALYSIS_STORAGE_KEY, SAMPLE_PGN } from "@/lib/chess-api";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "ChessReview Analytics — Free PGN Game Review & Engine Analysis" },
      {
        name: "description",
        content:
          "Paste any PGN or FEN and get an instant chess game review: move-by-move evaluation, blunder detection and accuracy scores for both sides.",
      },
      { property: "og:title", content: "ChessReview Analytics — Chess Game Review" },
      {
        property: "og:description",
        content:
          "Instant move-by-move chess analysis with evaluation bar, move classifications and accuracy percentages.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Home,
});

const PLACEHOLDER = `1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 ...

or a FEN:
rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1`;

function Home() {
  const navigate = useNavigate();
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const handleAnalyze = async () => {
    if (!input.trim() || isAnalyzing) return;
    setIsAnalyzing(true);
    setError(null);
    try {
      const analysis = await analyzePgn(input.trim());
      sessionStorage.setItem(ANALYSIS_STORAGE_KEY, JSON.stringify(analysis));
      navigate({ to: "/review" });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The game could not be analyzed.");
    } finally {
      setIsAnalyzing(false);
    }
  };

  return (
    <main className="hero-glow min-h-screen px-4 py-10 sm:px-8 lg:py-16">
      <div className="mx-auto max-w-6xl">
        <header className="text-center">
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-accent">
            <Sparkles className="size-3.5" />
            Move-by-move game review
          </span>
          <h1 className="text-glow mt-5 text-4xl font-bold sm:text-6xl">ChessReview Analytics</h1>
          <p className="mx-auto mt-4 max-w-xl text-sm text-muted-foreground sm:text-base">
            Drop in a PGN or FEN and replay your game with evaluations, move classifications and
            accuracy scores for both sides.
          </p>
        </header>

        <div className="mt-12 grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="mx-auto w-full max-w-[460px]">
            <AnalysisBoard
              id="preview-board"
              position="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
              animate={false}
            />
            <p className="mt-3 text-center text-xs text-muted-foreground">
              Preview board — starting position
            </p>
          </div>

          <div className="panel p-5 sm:p-6">
            <div className="flex items-center gap-2">
              <FileText className="size-4 shrink-0 text-accent" />
              <h2 className="text-lg font-semibold">Import your game</h2>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              Paste a full PGN (headers optional) or a single FEN string.
            </p>

            <textarea
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                setError(null);
              }}
              spellCheck={false}
              placeholder={PLACEHOLDER}
              className="scroll-slim mt-4 h-56 w-full resize-none rounded-lg border border-input bg-background/60 p-3 font-mono text-sm leading-relaxed text-foreground outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-accent focus:ring-2 focus:ring-ring/40"
            />

            {error && (
              <p className="mt-3 flex items-start gap-2 rounded-md bg-destructive/12 px-3 py-2 text-sm text-destructive">
                <AlertCircle className="mt-0.5 size-4 shrink-0" />
                {error}
              </p>
            )}

            <div className="mt-5 flex flex-col gap-3 sm:flex-row">
              <button
                type="button"
                onClick={handleAnalyze}
                disabled={isAnalyzing || !input.trim()}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground shadow-[var(--glow-accent)] transition-all hover:brightness-110 active:scale-[0.99]"
              >
                {isAnalyzing ? "Analyzing..." : "Analyze Game"}
                <ArrowRight className="size-4" />
              </button>
              <button
                type="button"
                onClick={() => {
                  setInput(SAMPLE_PGN);
                  setError(null);
                }}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-border bg-secondary px-5 py-3 text-sm font-semibold transition-colors hover:border-accent hover:text-accent"
              >
                <Crown className="size-4" />
                Load sample
              </button>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
