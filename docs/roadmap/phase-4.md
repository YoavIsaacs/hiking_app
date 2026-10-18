# Phase 4 — Extend and decide checklist

4.1–4.5 are a menu: pick what you want. 4.6 is required. Accounts, cloud trips and the community features are no longer optional; they moved to Phase 3.

## 4.1 Saved trips and history

- [ ] `/trips` list: name, date, distance, status (upcoming / past), sorted upcoming first
- [ ] Search by name; filter upcoming / past
- [ ] "Same hike, new date" → copies route and options, opens `/plan` prefilled with today's date
- [ ] Signed in: `POST /v1/trips/{trip_id}/duplicate` returns the new trip; signed out: duplicated in Dexie
- [ ] Test: search and filter logic
- [ ] Test: duplicate copies route and options but not ticks or feedback
- [ ] Playwright: duplicate a saved trip and build its checklist
- [ ] Count taps to re-plan (≤ 3)

## 4.2 Gear inventory

- [ ] `GearItem` model: `id`, `name`, `generic_key` (matches a rule item `key`), `weight_g`, `notes`
- [ ] `GET /v1/gear`, `POST /v1/gear`, `PUT /v1/gear/{gear_id}`, `DELETE /v1/gear/{gear_id}` for signed-in users (Dexie only when signed out)
- [ ] `/gear` screen: list, add, edit, delete; pick the generic item from a dropdown of known keys
- [ ] Checklist shows your gear name under the generic name when mapped
- [ ] Pack weight total (quantities included; water counted at 1 kg/L)
- [ ] Unmapped items listed so you can add gear for them
- [ ] Tests: mapping, multiple gear for one key (pick the default), unmapped fallback
- [ ] Tests: weight total with quantities
- [ ] Verify: ≥ 80% of a typical checklist maps; weigh your packed bag and compare (within 5%)

## 4.3 Group profiles

- [ ] Extend `TripOptions`: `kids: list[{age_years}]`, `dog: bool`, `solo: bool`, `pace_factor: float`
- [ ] `GET /v1/profiles`, `PUT /v1/profiles` — stored defaults for signed-in users (Dexie only when signed out)
- [ ] Kid rules: extra layer, extra snacks, comfort item, slower pace factor by age
- [ ] Dog rules: extra water for the dog, bowl, leash, paw-heat warning above a temperature
- [ ] Solo rules: share your route and ETA with someone, emergency whistle/beacon
- [ ] Plan screen: profile toggles prefilled from defaults
- [ ] Tests: ≥ 3 per rule (triggers / doesn't / threshold); pace factor reaches the duration estimate

## 4.4 Trail search from OpenStreetMap

- [ ] `app/trails/overpass.py` — Overpass client with timeout and a polite User-Agent
- [ ] Query hiking relations (`route=hiking`) by name within a bounding box, or near a point
- [ ] Assemble ways into one ordered line; handle gaps and reversed ways
- [ ] Convert to `RouteSummary` (elevation via 1.3 backfill)
- [ ] `GET /v1/trails/search?q=&lat=&lon=&radius_km=` → list of `{osm_relation_id, name, distance_m, from, to}`
- [ ] `GET /v1/trails/{osm_relation_id}` → `RouteSummary`
- [ ] Cache results (24 h) to respect Overpass usage policy
- [ ] Search UI on `/plan` as an alternative to GPX upload; use device location if permitted
- [ ] Tests: recorded Overpass responses; way assembly with gaps and reversed ways; empty results
- [ ] Add one Overpass call to the weekly `live-weather` workflow (rename it `live-apis`)
- [ ] Verify: ≥ 8 of 10 known regional hikes found by name; < 3 s
- [ ] Attribution: "© OpenStreetMap contributors" shown wherever OSM data appears

## 4.5 Water sources

- [ ] Overpass query: `amenity=drinking_water`, `natural=spring`, `man_made=water_tap` within the route's bounding box
- [ ] Keep sources within 100 m of the route; compute each one's distance along the route
- [ ] Add `water_sources: list[{lat, lon, kind, dist_along_m}]` and `longest_dry_stretch_m` to `RouteSummary`
- [ ] Water rule uses the longest dry stretch instead of total time when sources exist
- [ ] Show sources on the elevation profile as markers
- [ ] Tests: point-to-line distance; along-route distance; dry-stretch calculation
- [ ] Tests: water rule with and without sources
- [ ] Verify on 3 routes you know

## 4.6 Decision gate: go native?

- [ ] `docs/decisions/0001-native-app.md` (ADR format)
- [ ] List every wanted next feature, including community ones (e.g. push notifications when your hike is rated or planned)
- [ ] For each: can a PWA do it on iOS and Android? (yes / partly / no, with reason)
- [ ] Mark which are must-haves
- [ ] Decision: go native if ≥ 1 must-have is "no"
- [ ] Date and commit the decision
