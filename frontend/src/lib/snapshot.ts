// Static snapshot loaded by the client instead of hitting a live API.
// The build/cron writes frontend/public/data/events.json via
// backend/app/scripts/export_snapshot.py; this module describes its shape and
// where to fetch it from.
import { Event, WeatherToday } from "./api";

export interface Snapshot {
  /** ISO-8601 UTC timestamp of when the snapshot was generated. */
  generated_at: string;
  /** Today's Essen forecast, same shape as the old GET /weather/today. */
  weather_today: WeatherToday;
  /** Pre-grouped events (one entry per production, with occurrences[]). */
  events: Event[];
}

// basePath is "" in local dev and "/REPO" on GitHub Pages. The prefix is
// mandatory: a bare "/data/events.json" would 404 under the project subpath.
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || "";

export const SNAPSHOT_URL = `${BASE_PATH}/data/events.json`;

/** Prefix an internal absolute path with the basePath (for plain <a> hrefs;
 *  next/link already prefixes basePath itself). */
export function withBasePath(path: string): string {
  return `${BASE_PATH}${path}`;
}
