# Chess Insights Hub

Build a production-ready, highly polished, interactive Chess Analysis & Game Review web application using React, TypeScript, Tailwind CSS, Lucide icons, and `chess.js` / `react-chessboard`.

DESIGN & THEME SYSTEM:

- Sleek, modern Dark Mode UI inspired by Chess.com and Lichess analysis tools.

- Color Palette: Deep Slate background (#0F172A), Slate card containers (#1E293B), Electric Blue primary buttons (#2563EB), Vibrant Cyan accents (#38BDF8), and crisp high-contrast white text (#FFFFFF).

- Fully responsive layout for both Desktop and Mobile screens.

CORE PAGES & ROUTING STRUCTURE:

1. HOME PAGE (`/`):

   - Header with glowing title "ChessReview Analytics" and a sleek subtitle.

   - Centered interactive preview chessboard.

   - Input Card on the right/bottom featuring a styled textarea to paste PGN or FEN strings, with example placeholder text.

   - Primary "Analyze Game" button that parses the input and navigates to the `/review` page using Router state.

2. GAME REVIEW PAGE (`/review`):

   - Header with a "Back to Import" button and "Game Review & Analysis" title.

   - Split-view layout:

     * LEFT/CENTER: Responsive Chessboard (~460px constrained) with active move highlights. Below the board, include interactive playback control buttons: First (|<), Previous (<), Auto-Play/Pause, Next (>), Last (>|), and support Keyboard Arrow Keys (Left/Right) for move navigation.

     * RIGHT PANEL (Multi-Tabbed or Stacked Layout):

       a) Move Notation List: Display standard algebraic notation (1. e4 e5 2. Nf3 Nc6...). Highlight the active move. Clicking any move in the list updates the board instantly.

       b) Engine Evaluation Panel: Includes a styled Evaluation Bar (-5.0 to +5.0) and numerical position score indicator (e.g., +0.8 or -1.4).

       c) Move Classification Badges: Show move quality badges next to notation (Brilliant, Best Move, Inaccuracy, Mistake, Blunder).

       d) Game Summary Card: Displays overall White vs Black Accuracy percentages (e.g., White 88.5% - Black 74.2%) and a brief evaluation text.

TECHNICAL CONSTRAINTS:

- Use clean TypeScript types throughout the codebase.

- Implement smooth state management using React hooks for active move index navigation.

- Ensure all components render gracefully even if no PGN is provided (fallback to starting position).

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/4af973b2-48de-4083-95a9-8bb682308a83).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
