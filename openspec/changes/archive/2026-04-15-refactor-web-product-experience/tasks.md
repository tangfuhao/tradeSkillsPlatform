## 1. Frontend architecture foundation

- [x] 1.1 Add route-based app bootstrapping and the new frontend file structure needed for product pages and the console split
- [x] 1.2 Extract the current monolithic dashboard into a dedicated `ConsolePage` with shared helper utilities preserved

## 2. Product-facing shell

- [x] 2.1 Implement a Neon Noir design-token layer and a reusable product layout with navigation between the home experience, replay theater, and console
- [x] 2.2 Build the new product home route as a direct experience-first landing page with replay entry points and operator-console access

## 3. Replay theater skeleton

- [x] 3.1 Extend frontend types and API helpers so replay pages can consume traces, portfolio context, and symbol-level run information
- [x] 3.2 Implement the `/replays/:runId` experience with run overview, multi-symbol switching, and chart-ready visualization regions

## 4. Verification and follow-up charting

- [x] 4.1 Verify the refactored app builds successfully and that the main routes render correctly on desktop and mobile breakpoints
- [x] 4.2 Integrate `lightweight-charts` with candle data and Agent trade markers for selected replay symbols
