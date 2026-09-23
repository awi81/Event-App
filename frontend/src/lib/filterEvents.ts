// Pure, client-side replica of the server's GET /events filtering + sorting.
//
// The static snapshot ships ALL upcoming + permanent events; this module applies
// every filter the FastAPI endpoint used to apply, but against the visitor's
// clock (`now`) so "past/today/tomorrow/weekend" are evaluated at view time.
//
// Parity model (must match events.py exactly, or the list drifts):
//  - Non-time filters (category, kids, indoor/outdoor, travel, search, favorites)
//    are production-level attributes shared by all occurrences -> applied to the
//    group.
//  - Time filters (past-hide `end >= now`, date-range overlap, time-of-day) are per-row on the
//    server, which filters rows THEN groups -> here a group survives if ANY of its
//    occurrences passes the active time filters.
//  - The headline start_at is recomputed as the earliest *qualifying* occurrence
//    (never trust the baked start_at; it goes stale on day 2 of a snapshot).
import { Event, Occurrence, SortMode } from "./api";

export interface ClientFilters {
  dateFilter: "all" | "today" | "tomorrow" | "weekend";
  kidsOnly: boolean;
  category: string; // "all" or a concrete category
  excludedCategories: string[]; // categories to hide
  indoorOutdoor: "all" | "indoor" | "outdoor";
  timeOfDay: "all" | "vormittags" | "nachmittags" | "abends";
  maxTravelTime: number; // 0 = no filter
  sort: SortMode;
  favoritesOnly: boolean;
  favorites: string[];
  search: string;
}

/** Parse a local-naive ISO string ("2026-06-02T19:30:00") as local time.
 *  Returns null for missing/blank/date-only values (we never time-filter those). */
function parseLocal(s?: string | null): Date | null {
  if (!s) return null;
  // Our start_at always carries a time component; date-only would parse as UTC.
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

/** When an occurrence stops being worth showing — mirrors cleanup.effective_end:
 *  explicit end after the start, else end of day for all-day/00:00 rows, else the start. */
export function occurrenceEnd(occ: Pick<Occurrence, "start_at" | "end_at" | "is_all_day">): Date | null {
  const start = parseLocal(occ.start_at);
  if (start === null) return null;
  const end = parseLocal(occ.end_at);
  if (end !== null && end > start) return end;
  if (occ.is_all_day || (start.getHours() === 0 && start.getMinutes() === 0)) return localEndOfDay(start);
  return start;
}

function localMidnight(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0, 0);
}
function localEndOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 23, 59, 59, 999);
}

/** Date range for today/tomorrow/weekend from the visitor's clock — mirrors the
 *  server's combine(start_date, min)/combine(end_date, max). null = no range. */
function computeRange(dateFilter: ClientFilters["dateFilter"], now: Date): { start: Date; end: Date } | null {
  if (dateFilter === "all") return null;
  if (dateFilter === "today") return { start: localMidnight(now), end: localEndOfDay(now) };
  if (dateFilter === "tomorrow") {
    const t = new Date(now);
    t.setDate(now.getDate() + 1);
    return { start: localMidnight(t), end: localEndOfDay(t) };
  }
  // weekend (Sat–Sun) — identical logic to the old page.tsx dateRange()
  const dow = now.getDay();
  const start = new Date(now);
  if (dow === 0) start.setDate(now.getDate() - 1); // Sunday -> Saturday
  else if (dow !== 6) start.setDate(now.getDate() + (6 - dow)); // weekday -> upcoming Saturday
  const end = new Date(start);
  end.setDate(start.getDate() + 1); // Sunday
  return { start: localMidnight(start), end: localEndOfDay(end) };
}

function hourMatchesTod(d: Date, tod: ClientFilters["timeOfDay"]): boolean {
  const h = d.getHours();
  if (tod === "vormittags") return h < 12;
  if (tod === "nachmittags") return h >= 12 && h < 18;
  if (tod === "abends") return h >= 18;
  return true;
}

/** Render a Date back to a local-naive ISO string so EventCard's parseISO and its
 *  occurrence string-equality both behave like the snapshot's own values. */
function toLocalISO(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(
    d.getMinutes()
  )}:${p(d.getSeconds())}`;
}

/** Group-level (non-time) filters: same attribute for every occurrence. */
function passesGroupFilters(event: Event, f: ClientFilters, favSet: Set<string> | null, search: string): boolean {
  if (favSet && !favSet.has(event.canonical_id)) return false;
  if (f.category !== "all" && event.category !== f.category) return false;
  if (f.excludedCategories.length > 0 && event.category && f.excludedCategories.includes(event.category)) return false;
  if (f.kidsOnly && !(event.kids_suitable === "yes" || event.kids_suitable === "likely")) return false;
  if (f.indoorOutdoor === "indoor" && !(event.indoor_outdoor === "indoor" || event.indoor_outdoor === "both"))
    return false;
  if (f.indoorOutdoor === "outdoor" && !(event.indoor_outdoor === "outdoor" || event.indoor_outdoor === "both"))
    return false;
  // travel <= X OR null (events without coords must not be hidden)
  if (f.maxTravelTime > 0 && event.travel_time_minutes != null && event.travel_time_minutes > f.maxTravelTime)
    return false;
  if (search) {
    const hay = `${event.title || ""} ${event.venue_name || ""} ${event.short_description || ""}`.toLowerCase();
    if (!hay.includes(search)) return false;
  }
  return true;
}

/** Permanent offers that pass every non-time filter but are hidden from the
 *  main list because an active date/time-of-day filter excludes undated rows.
 *  Rendered as a separate "Jederzeit möglich" section. Sorted by quality. */
export function permanentOffersHiddenByTimeFilters(all: Event[], f: ClientFilters, now: Date): Event[] {
  if (computeRange(f.dateFilter, now) === null && f.timeOfDay === "all") return [];
  const favSet = f.favoritesOnly ? new Set(f.favorites) : null;
  const search = f.search.trim().toLowerCase();
  const out = all.filter((e) => e.is_permanent_offer === true && passesGroupFilters(e, f, favSet, search));
  out.sort((a, b) => (b.quality_score ?? 0) - (a.quality_score ?? 0));
  return out;
}

interface Ranked {
  event: Event;
  eff: Date | null; // earliest qualifying occurrence (null = permanent/undated)
  effStr: string | null; // original occurrence string for that occurrence
}

export function applyClientFilters(all: Event[], f: ClientFilters, now: Date): Event[] {
  const range = computeRange(f.dateFilter, now);
  const rangeActive = range !== null;
  const todActive = f.timeOfDay !== "all";
  const nowMs = now.getTime();
  const search = f.search.trim().toLowerCase();
  const favSet = f.favoritesOnly ? new Set(f.favorites) : null;

  const ranked: Ranked[] = [];

  for (const event of all) {
    if (!passesGroupFilters(event, f, favSet, search)) continue;

    // --- occurrence-level (time) filters: keep group if ANY occurrence qualifies ---
    const occs: Occurrence[] = event.occurrences && event.occurrences.length
      ? event.occurrences
      : [{ id: event.id, start_at: event.start_at, end_at: event.end_at, is_all_day: event.is_all_day, is_permanent_offer: event.is_permanent_offer }];
    let anyQualify = false;
    let eff: Date | null = null;
    let effStr: string | null = null;

    for (const occ of occs) {
      const os = parseLocal(occ.start_at);
      const oe = occurrenceEnd(occ);
      // base past-hide: keep null-dated, not-yet-ended (running or future), or permanent offers
      const basePass = os === null || oe!.getTime() >= nowMs || event.is_permanent_offer === true;
      if (!basePass) continue;
      // date range / time-of-day exclude undated rows (NULL fails SQL comparisons);
      // the range matches on overlap, so a fair running Thu-Sun shows up on Saturday
      if (rangeActive) {
        if (os === null) continue;
        if (os > range!.end || oe! < range!.start) continue;
      }
      if (todActive) {
        if (os === null) continue;
        if (!hourMatchesTod(os, f.timeOfDay)) continue;
      }
      anyQualify = true;
      if (os !== null && (eff === null || os < eff)) {
        eff = os;
        effStr = occ.start_at ?? null;
      }
    }

    if (!anyQualify) continue;
    ranked.push({ event, eff, effStr });
  }

  // --- sort on a copy (mirrors events.py sort keys; null start sorts last) ---
  const effMs = (r: Ranked) => (r.eff ? r.eff.getTime() : Infinity);
  const isNull = (r: Ranked) => (r.eff === null ? 1 : 0);
  ranked.sort((a, b) => {
    if (f.sort === "quality") {
      const q = (b.event.quality_score ?? 0) - (a.event.quality_score ?? 0);
      if (q !== 0) return q;
      return effMs(a) - effMs(b);
    }
    if (f.sort === "travel") {
      const at = a.event.travel_time_minutes;
      const bt = b.event.travel_time_minutes;
      const an = at == null ? 1 : 0;
      const bn = bt == null ? 1 : 0;
      if (an !== bn) return an - bn; // null travel last
      const tv = (at ?? 9999) - (bt ?? 9999);
      if (tv !== 0) return tv;
      return effMs(a) - effMs(b);
    }
    if (f.sort === "start_at") {
      if (isNull(a) !== isNull(b)) return isNull(a) - isNull(b);
      return effMs(a) - effMs(b);
    }
    // "smart": next occurrence asc (nulls last), then quality desc
    if (isNull(a) !== isNull(b)) return isNull(a) - isNull(b);
    if (effMs(a) !== effMs(b)) return effMs(a) - effMs(b);
    return (b.event.quality_score ?? 0) - (a.event.quality_score ?? 0);
  });

  // Override start_at with the recomputed next-upcoming occurrence so cards show
  // the soonest future date, not the stale baked one.
  return ranked.map((r) => ({
    ...r.event,
    start_at: r.effStr ?? (r.eff ? toLocalISO(r.eff) : undefined),
  }));
}
