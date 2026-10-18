# Phase 2 — Real PWA checklist

## 2.1 Installable app

- [ ] Add vite-plugin-pwa to `vite.config.ts` with `registerType: 'prompt'` (user chooses when to update)
- [ ] Manifest: `name`, `short_name`, `description`, `start_url`, `scope`, `display: standalone`, `theme_color`, `background_color`, `orientation: portrait`
- [ ] Icons: 192 px, 512 px, 512 px maskable (check in a maskable-icon preview tool)
- [ ] `apple-touch-icon` 180 px; `apple-mobile-web-app-capable` and status-bar meta tags in `index.html`
- [ ] iOS splash behaviour checked (background colour matches the app)
- [ ] "Install" hint on Android (`beforeinstallprompt`) and an "Add to Home Screen" instruction card on iOS
- [ ] "New version available" toast that reloads on tap
- [ ] Test: generated manifest has every required field and icon size
- [ ] Test: update toast appears when a new service worker is waiting (mock the register hook)
- [ ] CI: Lighthouse CI assertion for installability
- [ ] Verify: install and launch standalone on an iPhone
- [ ] Verify: install and launch standalone on an Android phone

## 2.2 Offline app shell

- [ ] Workbox precache of all built assets (`globPatterns` for js, css, html, svg, png, woff2)
- [ ] Navigation fallback to `index.html` for client routes
- [ ] API calls are network-only (never serve a stale checklist as if fresh)
- [ ] Online/offline indicator in the header (`navigator.onLine` + events)
- [ ] Offline screen for actions that need the network ("Build checklist", "Refresh forecast")
- [ ] Saved trips and their checklists fully usable offline
- [ ] Playwright: load, `context.setOffline(true)`, reload, app renders
- [ ] Playwright: offline → "Build checklist" shows the offline message
- [ ] Playwright: offline → open a saved trip and tick an item
- [ ] Verify: airplane mode cold open < 2 s on your phone

## 2.3 Local persistence

- [ ] Add Dexie; `web/src/db/schema.ts` with version 1
- [ ] Table `trips`: `id` (uuid), `name`, `date`, `startTime`, `options`, `route`, `checklist` (full response), `ticks` (item keys), `createdAt`, `updatedAt`, `rulesVersion`
- [ ] Table `feedback`: `tripId`, `missing[]`, `unneeded[]`, `actualDurationMin`, `notes`, `createdAt`
- [ ] `TripRepository` interface: `list`, `get`, `save`, `delete`, `setTicks` (this interface is reused by the native app in Phase 5)
- [ ] Dexie implementation of `TripRepository`
- [ ] "Save trip" automatically after a checklist is built
- [ ] Ticks written on every change (debounced ≤ 200 ms)
- [ ] Trips list screen (`/trips`) with delete (with confirm)
- [ ] Ask for persistent storage (`navigator.storage.persist()`) so the browser doesn't evict data
- [ ] Write a v1 → v2 schema migration (even a trivial one) to prove migrations work
- [ ] Tests (fake-indexeddb): save, get, list order, delete, setTicks
- [ ] Test: migration from v1 data to v2
- [ ] Playwright: tick items → reload → ticks restored
- [ ] Verify: kill the app mid-checklist on the phone → 100% ticks survive
- [ ] Measure: storage used by 20 trips < 5 MB (`navigator.storage.estimate()`)

## 2.4 Forecast refresh with diff

- [ ] `diffChecklists(old, new) → {added, removed, changed}` pure function (changed = priority or quantity)
- [ ] "Refresh forecast" button on a saved trip (disabled offline)
- [ ] Re-send the stored route + date + options to `POST /v1/checklist`
- [ ] Show a diff summary: added (highlighted), removed (struck through, then dropped), changed (old → new)
- [ ] Keep ticks for unchanged and changed items; drop ticks for removed ones
- [ ] Store the new response and `updatedAt`
- [ ] Unit tests: added, removed, priority changed, quantity changed, no change
- [ ] Test: ticks preserved correctly after refresh
- [ ] Component test: diff highlights render

## 2.5 Mobile UX pass

- [ ] All interactive elements ≥ 44 × 44 px
- [ ] Primary actions in a bottom bar within thumb reach
- [ ] Dark mode via `prefers-color-scheme` plus a manual toggle
- [ ] High-contrast theme for bright sunlight
- [ ] Font sizes respect the system setting (rem units)
- [ ] Safe-area insets for notched phones (`env(safe-area-inset-*)`)
- [ ] No horizontal scroll at 360 px width
- [ ] Playwright screenshots: light, dark, high-contrast on `/plan`, `/trip`, `/trips`
- [ ] axe checks on every route
- [ ] Lighthouse CI accessibility budget ≥ 90
- [ ] Contrast check of every colour pair against WCAG AA

## 2.6 Feedback log

- [ ] "How did it go?" form on a trip after its date: missing items (free text + pick from list), unneeded items (pick from checklist), actual duration, notes
- [ ] Saved to the `feedback` table
- [ ] "Export all" button → JSON file download (trips + feedback)
- [ ] JSON schema for the export in `docs/schemas/export.schema.json`
- [ ] Test: form validation and save
- [ ] Test: export validates against the schema (ajv)
- [ ] Verify: logging a hike takes < 2 minutes

## 2.7 Field testing

- [ ] `docs/field-notes.md` template: date, route, conditions, missed, unneeded, actual vs estimated time, rule changes made
- [ ] Hike 1 — hot day
- [ ] Hike 2 — cold or windy day
- [ ] Hike 3 — long day (5+ hours)
- [ ] Hike 4 — finish close to sunset
- [ ] Hike 5 — with a companion (kid, dog, or group)
- [ ] After each hike: export its `TripContext` to `api/tests/fixtures/trips/hike-N.json`
- [ ] After each hike: add a regression test asserting the corrected checklist
- [ ] After each hike: adjust rules or thresholds; note each change in `field-notes.md`
- [ ] Count missed must-haves per hike; confirm ≤ 1 on the last 2

## 2.8 Duration calibration

- [ ] Table in `field-notes.md`: estimated vs actual minutes per hike, error %
- [ ] Update default pace factor and rest allowance in `rules.yaml` / settings
- [ ] Test: over all logged hikes, mean absolute error < 15% with the current settings
- [ ] Verify the phase exit checkpoint on the last 3 hikes
