// Event types matching backend API
export interface Occurrence {
  id: number;
  start_at?: string;
  venue_name?: string;
  source_url?: string;
  is_permanent_offer?: boolean;
}

export interface Event {
  id: number;
  canonical_id: string;
  title: string;
  short_description?: string;
  start_at?: string;
  end_at?: string;
  category?: string;
  venue_name?: string;
  address_text?: string;
  city?: string;
  lat?: number;
  lon?: number;
  indoor_outdoor?: "indoor" | "outdoor" | "both" | "unknown";
  kids_suitable?: "yes" | "likely" | "unknown" | "no";
  price_text?: string;
  source_url?: string;
  source_name?: string;
  is_permanent_offer?: boolean;
  is_all_day?: boolean;
  distance_km?: number;
  travel_time_minutes?: number;
  age_note?: string;
  weather_note?: string;
  image_url?: string;
  quality_score?: number;
  source_count?: number;
  sources_list?: string;
  created_at?: string;
  occurrences?: Occurrence[];
}

export type SortMode = "smart" | "quality" | "travel" | "start_at";

export interface EventQuery {
  start_date?: string;
  end_date?: string;
  category?: string;
  kids_only?: boolean;
  indoor_outdoor?: string;
  max_travel_time?: number;
  limit?: number;
  time_of_day?: string;
  favorites?: string;
  q?: string;
  sort?: SortMode;
}

// Server-side uses INTERNAL_API_URL (localhost), browser uses NEXT_PUBLIC_API_URL (LAN IP)
const isServer = typeof window === "undefined";
export const API_BASE = isServer
  ? (process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1")
  : (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1");

export async function fetchEvents(params: EventQuery = {}): Promise<Event[]> {
  const searchParams = new URLSearchParams();

  if (params.start_date) searchParams.set("start_date", params.start_date);
  if (params.end_date) searchParams.set("end_date", params.end_date);
  if (params.category && params.category !== "all") searchParams.set("category", params.category);
  if (params.kids_only) searchParams.set("kids_only", "true");
  if (params.indoor_outdoor && params.indoor_outdoor !== "all") searchParams.set("indoor_outdoor", params.indoor_outdoor);
  if (params.max_travel_time) searchParams.set("max_travel_time", params.max_travel_time.toString());
  if (params.limit) searchParams.set("limit", params.limit.toString());
  if (params.time_of_day && params.time_of_day !== "all") searchParams.set("time_of_day", params.time_of_day);
  if (params.favorites) searchParams.set("favorites", params.favorites);
  if (params.q && params.q.trim()) searchParams.set("q", params.q.trim());
  if (params.sort && params.sort !== "smart") searchParams.set("sort", params.sort);

  const url = `${API_BASE}/events?${searchParams.toString()}`;
  const res = await fetch(url);

  if (!res.ok) {
    throw new Error(`Failed to fetch events: ${res.statusText}`);
  }

  return res.json();
}

export async function syncEvents(): Promise<{ synced: number; details: string[] }> {
  // Full sync pulls 12 sources with Playwright + Nominatim and can take
  // several minutes. Use a 10-minute abort signal so the browser doesn't
  // give up before the backend is done.
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10 * 60 * 1000);
  try {
    const res = await fetch(`${API_BASE}/events/sync`, {
      method: "POST",
      signal: controller.signal,
    });
    if (!res.ok) {
      throw new Error(`Failed to sync events: ${res.statusText}`);
    }
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

export interface WeatherToday {
  available: boolean;
  date?: string;
  temp_max?: number | null;
  temp_min?: number | null;
  rain_probability?: number | null;
  weather_code?: number | null;
  hint?: string | null;
}

export async function fetchWeatherToday(): Promise<WeatherToday> {
  try {
    const res = await fetch(`${API_BASE}/weather/today`);
    if (!res.ok) return { available: false };
    return await res.json();
  } catch {
    return { available: false };
  }
}
