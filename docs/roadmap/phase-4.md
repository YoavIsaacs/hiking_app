# Phase 4 — Migrate to React Native checklist

No backend endpoints change in this phase. Every item here is frontend, shared code or CI.

## 4.0 Extract shared code

- [ ] Create `packages/core` with its own `package.json`, `tsconfig.json` (no DOM lib), Vitest config
- [ ] Move: generated `schema.d.ts` and the openapi-fetch client (base URL injected, not read from `import.meta.env`)
- [ ] Move: TanStack Query hooks (`useParseRoute`, `useChecklist`, `useTrips`, `useRefreshTrip`, etc.)
- [ ] Move: `TripRepository` interface and its contract test suite
- [ ] Move: `diffChecklists`, formatters (distance, duration, temperature), sunset-margin logic, Zustand trip store
- [ ] Update `gen:api` to write into `packages/core`
- [ ] Web app imports everything from `@hikeprep/core`
- [ ] ESLint in core: `no-restricted-globals` for `window`, `document`, `localStorage`; `no-restricted-imports` for `react-dom`
- [ ] TypeScript `lib: ["ES2022"]` only in core, so DOM types fail to compile
- [ ] CI: `core-test` job (lint, `tsc`, Vitest, coverage ≥ 85%)
- [ ] Verify: full web suite and Playwright green after the move

## 4.1 Expo app scaffold

- [ ] `pnpm create expo-app mobile` with the TypeScript template
- [ ] Expo Router with routes: `(tabs)/index` (plan), `(tabs)/trips`, `trip/[id]`, `settings`
- [ ] Metro configured for the pnpm monorepo (watch folders, `node-linker` settings as Expo's monorepo guide describes)
- [ ] `app.config.ts` with build profiles: development, preview, production; `API_URL` per profile
- [ ] Bundle identifier / package name chosen (e.g. `com.yourname.hikeprep`)
- [ ] App icon and splash screen
- [ ] Jest (jest-expo preset) + React Native Testing Library + MSW for React Native
- [ ] Test: home screen renders the API version from mocked `/health`
- [ ] CI: `mobile-test` job — ESLint, `tsc`, Jest, `npx expo-doctor`
- [ ] Verify: Expo Go on your phone shows the deployed API version

## 4.2 Data layer

- [ ] TanStack Query provider with React Native focus and online managers (AppState, NetInfo)
- [ ] expo-sqlite implementation of `TripRepository` with the same schema as Dexie's v2
- [ ] SQLite migrations runner (version table)
- [ ] Run core's `TripRepository` contract tests against the SQLite implementation
- [ ] Persist the trip store with the SQLite repository
- [ ] Verify: 0 changes to core hooks were needed; trips survive app restarts

## 4.3 Plan screen

- [ ] expo-document-picker with `type: '*/*'`, `copyToCacheDirectory: true`
- [ ] Upload the picked file to `POST /v1/routes/parse` as multipart from its local URI
- [ ] Native date picker (limited range) and time picker (@react-native-community/datetimepicker)
- [ ] Options toggles; keyboard-safe layout
- [ ] Same error messages as the web app (shared mapping from core)
- [ ] Component tests for validation and errors
- [ ] `mobile/.maestro/plan_flow.yaml`: pick fixture → date → build → checklist visible
- [ ] Push fixture GPX files onto the emulator in the Maestro setup step
- [ ] CI: `e2e-mobile` workflow — build a debug APK, start an Android emulator (reactivecircus/android-emulator-runner), run Maestro, upload recordings on failure
- [ ] Verify on a real iPhone and Android: pick from Files and Downloads; all 10 fixtures accepted

## 4.4 Route summary screen

- [ ] Stat cards, finish-vs-sunset margin, warnings banner
- [ ] Elevation chart (victory-native or react-native-gifted-charts; pick one)
- [ ] Weather strip as a horizontal list
- [ ] Component tests: renders all fixture responses
- [ ] Test: numbers match the web app's for each fixture (same formatter from core)
- [ ] Maestro screenshot step for 2 fixtures
- [ ] Verify: 60 fps scrolling (React Native performance monitor)

## 4.5 Checklist screen

- [ ] `SectionList` grouped by category
- [ ] Item row: checkbox, name, quantity, priority badge, reason, your gear name if mapped
- [ ] Haptic feedback on tick (expo-haptics)
- [ ] "More ideas" collapsed section
- [ ] Progress header
- [ ] Tests: tick/untick, counts, every item has a reason
- [ ] `mobile/.maestro/ticks_persist.yaml`: tick 3 → kill app → relaunch → 3 still ticked
- [ ] Verify: 40-item list at 60 fps; tick < 100 ms

## 4.6 Trip migration from the PWA

- [ ] Import screen in settings: pick the PWA's JSON export
- [ ] Validate against `export.schema.json` (shared from core)
- [ ] Merge rule for duplicates (same trip id → newer `updatedAt` wins)
- [ ] If accounts exist: signing in syncs instead, and the import screen is hidden
- [ ] Tests: valid file, invalid file, duplicate handling, round-trip (export from web → import to native → identical)
- [ ] Verify: 100% of your PWA trips import

## 4.7 Parity check and development build

- [ ] `eas.json` with development, preview and production profiles
- [ ] EAS development build installed on your phone
- [ ] `docs/parity.md`: table of every PWA feature with native status
- [ ] For every Playwright flow, a matching Maestro flow exists
- [ ] CI: EAS preview build on merge to `main` (expo/expo-github-action with `EXPO_TOKEN` secret)
- [ ] Make `e2e-mobile` a required check
- [ ] Use the native app on 2 real hikes; log them in `field-notes.md`
- [ ] Verify: parity table 100% green
