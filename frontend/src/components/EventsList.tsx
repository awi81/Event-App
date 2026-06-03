"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { Event, SortMode } from "@/lib/api";
import { applyClientFilters, ClientFilters } from "@/lib/filterEvents";
import { EventCard } from "./EventCard";
import { TopPicks } from "./TopPicks";
import { useFavorites } from "@/lib/favorites";
import {
  Calendar,
  Home,
  Trees,
  FilterX,
  Map,
  List,
  Grid,
  Clock,
  Heart,
  SlidersHorizontal,
  Eye,
  EyeOff,
  Search,
  X,
} from "lucide-react";

const EventsMap = dynamic(() => import("./EventsMap").then((m) => ({ default: m.EventsMap })), {
  ssr: false,
  loading: () => <MapLoadingSkeleton />,
});

function MapLoadingSkeleton() {
  return (
    <div className="h-[500px] w-full rounded-xl bg-gray-100 dark:bg-slate-800 animate-pulse flex items-center justify-center">
      <div className="text-center">
        <Map className="h-12 w-12 text-gray-300 dark:text-slate-600 mx-auto mb-2" />
        <p className="text-gray-400 dark:text-gray-500">Karte wird geladen...</p>
      </div>
    </div>
  );
}

type DateFilter = "all" | "today" | "tomorrow" | "weekend";
type IndoorFilter = "all" | "indoor" | "outdoor";
type TimeOfDay = "all" | "vormittags" | "nachmittags" | "abends";
type ViewMode = "grid" | "list" | "map";

interface FilterState {
  dateFilter: DateFilter;
  kidsOnly: boolean;
  categoryFilter: string;
  excludedCategories: string[];
  indoorFilter: IndoorFilter;
  timeOfDay: TimeOfDay;
  maxTravelTime: number; // 0 = no filter
  sort: SortMode;
  favoritesOnly: boolean;
  showMiniMap: boolean;
  viewMode: ViewMode;
  search: string;
}

const DEFAULTS: FilterState = {
  dateFilter: "today",
  kidsOnly: false,
  categoryFilter: "all",
  excludedCategories: [],
  indoorFilter: "all",
  timeOfDay: "all",
  maxTravelTime: 30,
  sort: "smart",
  favoritesOnly: false,
  showMiniMap: true,
  viewMode: "grid",
  search: "",
};

function parseFiltersFromUrl(params: URLSearchParams): FilterState {
  const sortRaw = params.get("sort") || DEFAULTS.sort;
  const sort: SortMode = ["smart", "quality", "travel", "start_at"].includes(sortRaw)
    ? (sortRaw as SortMode)
    : DEFAULTS.sort;
  const viewRaw = params.get("view") || DEFAULTS.viewMode;
  const view: ViewMode = ["grid", "list", "map"].includes(viewRaw) ? (viewRaw as ViewMode) : DEFAULTS.viewMode;

  const xcatRaw = params.get("xcat");
  const excludedCategories = xcatRaw
    ? xcatRaw.split(",").map((s) => decodeURIComponent(s.trim())).filter(Boolean)
    : DEFAULTS.excludedCategories;

  return {
    dateFilter: (params.get("date") as DateFilter) || DEFAULTS.dateFilter,
    kidsOnly: params.get("kids") === "1",
    categoryFilter: params.get("cat") || DEFAULTS.categoryFilter,
    excludedCategories,
    indoorFilter: (params.get("io") as IndoorFilter) || DEFAULTS.indoorFilter,
    timeOfDay: (params.get("tod") as TimeOfDay) || DEFAULTS.timeOfDay,
    maxTravelTime: (() => { const raw = params.get("tt"); if (raw === null) return DEFAULTS.maxTravelTime; const n = Number(raw); return Number.isFinite(n) ? n : DEFAULTS.maxTravelTime; })(),
    sort,
    favoritesOnly: params.get("fav") === "1",
    showMiniMap: params.get("minimap") !== "0",
    viewMode: view,
    search: params.get("q") || "",
  };
}

function filtersToUrl(filters: FilterState): URLSearchParams {
  const out = new URLSearchParams();
  if (filters.dateFilter !== DEFAULTS.dateFilter) out.set("date", filters.dateFilter);
  if (filters.kidsOnly) out.set("kids", "1");
  if (filters.categoryFilter !== DEFAULTS.categoryFilter) out.set("cat", filters.categoryFilter);
  if (filters.excludedCategories.length > 0)
    out.set("xcat", filters.excludedCategories.map(encodeURIComponent).join(","));
  if (filters.indoorFilter !== DEFAULTS.indoorFilter) out.set("io", filters.indoorFilter);
  if (filters.timeOfDay !== DEFAULTS.timeOfDay) out.set("tod", filters.timeOfDay);
  if (filters.maxTravelTime !== DEFAULTS.maxTravelTime) out.set("tt", String(filters.maxTravelTime));
  if (filters.sort !== DEFAULTS.sort) out.set("sort", filters.sort);
  if (filters.favoritesOnly) out.set("fav", "1");
  if (!filters.showMiniMap) out.set("minimap", "0");
  if (filters.viewMode !== DEFAULTS.viewMode) out.set("view", filters.viewMode);
  if (filters.search) out.set("q", filters.search);
  return out;
}

interface EventsListProps {
  /** All upcoming + permanent events from the static snapshot. */
  events: Event[];
}

export function EventsList({ events }: EventsListProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { favorites } = useFavorites();

  const [filters, setFilters] = useState<FilterState>(() =>
    parseFiltersFromUrl(new URLSearchParams(searchParams.toString()))
  );
  const [filtersExpanded, setFiltersExpanded] = useState(false);

  // View-time clock: captured once on mount so toggling filters doesn't re-run
  // the date math against a moving target (and the map view isn't reset). A
  // reload re-evaluates "today/tomorrow/weekend" against the fresh clock.
  const [now] = useState(() => new Date());

  // Re-sync filter state with the URL on browser back/forward.
  useEffect(() => {
    setFilters(parseFiltersFromUrl(new URLSearchParams(searchParams.toString())));
  }, [searchParams]);

  // Write filter state to the URL whenever it changes (replaceState, no scroll jump).
  const lastUrlRef = useRef<string>("");
  useEffect(() => {
    const next = filtersToUrl(filters).toString();
    if (next === lastUrlRef.current) return;
    lastUrlRef.current = next;
    router.replace(`/?${next}`, { scroll: false });
  }, [filters, router]);

  const update = useCallback(<K extends keyof FilterState>(key: K, value: FilterState[K]) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }, []);

  const clearFilters = () => setFilters({ ...DEFAULTS, viewMode: filters.viewMode, showMiniMap: filters.showMiniMap });

  // The visible list: pure client-side filter + sort replicating the old API.
  const visibleEvents = useMemo(() => {
    const cf: ClientFilters = {
      dateFilter: filters.dateFilter,
      kidsOnly: filters.kidsOnly,
      category: filters.categoryFilter,
      excludedCategories: filters.excludedCategories,
      indoorOutdoor: filters.indoorFilter,
      timeOfDay: filters.timeOfDay,
      maxTravelTime: filters.maxTravelTime,
      sort: filters.sort,
      favoritesOnly: filters.favoritesOnly,
      favorites,
      search: filters.search,
    };
    return applyClientFilters(events, cf, now);
  }, [events, filters, favorites, now]);

  // Category chips are derived dynamically: only show categories that actually
  // yield events under the *other* active filters (date, time-of-day, location,
  // travel, search, favorites). We run the same filter pipeline but with the
  // category filter neutralised, so picking a category doesn't make the rest of
  // the chips disappear. Currently included/excluded categories are always kept
  // visible so they never become un-clickable (no dead state).
  const availableCategories = useMemo(() => {
    const cf: ClientFilters = {
      dateFilter: filters.dateFilter,
      kidsOnly: filters.kidsOnly,
      category: "all",
      excludedCategories: [],
      indoorOutdoor: filters.indoorFilter,
      timeOfDay: filters.timeOfDay,
      maxTravelTime: filters.maxTravelTime,
      sort: filters.sort,
      favoritesOnly: filters.favoritesOnly,
      favorites,
      search: filters.search,
    };
    const cats = new Set<string>();
    applyClientFilters(events, cf, now).forEach((e) => e.category && cats.add(e.category));
    // Keep the active selection visible regardless of the other filters.
    if (filters.categoryFilter !== "all") cats.add(filters.categoryFilter);
    filters.excludedCategories.forEach((c) => cats.add(c));
    return Array.from(cats).sort();
  }, [events, filters, favorites, now]);

  const hasActiveFilters =
    filters.dateFilter !== DEFAULTS.dateFilter ||
    filters.kidsOnly ||
    filters.categoryFilter !== "all" ||
    filters.excludedCategories.length > 0 ||
    filters.indoorFilter !== "all" ||
    filters.timeOfDay !== "all" ||
    filters.maxTravelTime !== DEFAULTS.maxTravelTime ||
    filters.favoritesOnly ||
    filters.search.length > 0 ||
    filters.sort !== "smart";

  return (
    <div className="flex flex-col gap-6">
      <TopPicks events={visibleEvents} />

      {/* Filter Bar */}
      <div className="flex flex-col gap-4 rounded-xl bg-white dark:bg-slate-800 p-4 shadow-sm border border-gray-100 dark:border-slate-700">
        {/* Search */}
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="search"
            value={filters.search}
            onChange={(e) => update("search", e.target.value)}
            placeholder="Suchen (Titel, Ort, Beschreibung)..."
            className="w-full rounded-lg border border-gray-300 dark:border-slate-600 dark:bg-slate-700 dark:text-gray-200 pl-9 pr-9 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200 focus:outline-none"
          />
          {filters.search && (
            <button
              onClick={() => update("search", "")}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md hover:bg-gray-100 dark:hover:bg-slate-600"
              title="Suche löschen"
            >
              <X className="h-4 w-4 text-gray-400" />
            </button>
          )}
        </div>

        {/* Row 1: Date filters */}
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Calendar className="h-5 w-5 text-blue-600" />
            <span className="font-medium text-gray-700 dark:text-gray-300">Datum:</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {(["all", "today", "tomorrow", "weekend"] as const).map((f) => (
              <button
                key={f}
                onClick={() => update("dateFilter", f)}
                className={`rounded-full px-4 py-2 text-sm font-medium transition-all ${
                  filters.dateFilter === f
                    ? "bg-blue-600 text-white shadow-md"
                    : "bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-slate-600"
                }`}
              >
                {f === "all" && "Alle"}
                {f === "today" && "Heute"}
                {f === "tomorrow" && "Morgen"}
                {f === "weekend" && "Wochenende"}
              </button>
            ))}
          </div>

          {/* Favorites toggle */}
          <button
            onClick={() => update("favoritesOnly", !filters.favoritesOnly)}
            className={`ml-auto flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-all ${
              filters.favoritesOnly
                ? "bg-red-500 text-white shadow-md"
                : "bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-slate-600"
            }`}
            title="Nur Favoriten zeigen"
          >
            <Heart className={`h-4 w-4 ${filters.favoritesOnly ? "fill-current" : ""}`} />
            Favoriten {favorites.length > 0 && `(${favorites.length})`}
          </button>
        </div>

        {/* Toggle for additional filters on mobile */}
        <button
          onClick={() => setFiltersExpanded((v) => !v)}
          className="md:hidden inline-flex items-center gap-2 text-sm text-blue-600 dark:text-blue-400"
        >
          <SlidersHorizontal className="h-4 w-4" />
          {filtersExpanded ? "Weniger Filter" : "Mehr Filter"}
        </button>

        <div className={`flex flex-col gap-4 ${filtersExpanded ? "" : "hidden md:flex"}`}>
          {/* Row 2: Category, Indoor/Outdoor, Kids */}
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300 shrink-0">Kategorie:</span>
              {/* "Alle"-Chip — active when no positive category filter AND no exclusions */}
              <button
                onClick={() => setFilters((prev) => ({ ...prev, categoryFilter: "all", excludedCategories: [] }))}
                className={`rounded-full px-3 py-1.5 text-sm font-medium transition-all ${
                  filters.categoryFilter === "all" && filters.excludedCategories.length === 0
                    ? "bg-blue-600 text-white shadow-md"
                    : "bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-slate-600"
                }`}
              >
                Alle
              </button>
              {availableCategories.map((cat) => {
                const isIncluded = filters.categoryFilter === cat;
                const isExcluded = filters.excludedCategories.includes(cat);
                // Cycle: neutral → included → excluded → neutral
                const handleClick = () => {
                  if (isIncluded) {
                    // included → excluded: clear positive filter, add to exclusions
                    setFilters((prev) => ({
                      ...prev,
                      categoryFilter: "all",
                      excludedCategories: [...prev.excludedCategories.filter((c) => c !== cat), cat],
                    }));
                  } else if (isExcluded) {
                    // excluded → neutral
                    setFilters((prev) => ({
                      ...prev,
                      excludedCategories: prev.excludedCategories.filter((c) => c !== cat),
                    }));
                  } else {
                    // neutral → included: also remove from exclusions if present
                    setFilters((prev) => ({
                      ...prev,
                      categoryFilter: cat,
                      excludedCategories: prev.excludedCategories.filter((c) => c !== cat),
                    }));
                  }
                };
                return (
                  <button
                    key={cat}
                    onClick={handleClick}
                    title={
                      isIncluded
                        ? `Nur „${cat}" — klicken zum Ausschließen`
                        : isExcluded
                        ? `„${cat}" ausgeblendet — klicken zum Zurücksetzen`
                        : `„${cat}" einblenden oder ausschließen`
                    }
                    className={`rounded-full px-3 py-1.5 text-sm font-medium transition-all select-none ${
                      isIncluded
                        ? "bg-blue-600 text-white shadow-md"
                        : isExcluded
                        ? "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 line-through ring-1 ring-red-300 dark:ring-red-700"
                        : "bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-slate-600"
                    }`}
                  >
                    {isExcluded ? (
                      <span className="flex items-center gap-1">
                        <X className="h-3 w-3 shrink-0 no-underline" style={{ textDecoration: "none" }} />
                        <span>{cat}</span>
                      </span>
                    ) : (
                      cat
                    )}
                  </button>
                );
              })}
            </div>

            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Ort:</span>
              <div className="flex gap-1">
                <button
                  onClick={() => update("indoorFilter", "all")}
                  className={`flex items-center gap-1 rounded-lg px-3 py-2 text-sm font-medium transition-all ${
                    filters.indoorFilter === "all"
                      ? "bg-gray-200 dark:bg-slate-600 text-gray-900 dark:text-white shadow-sm"
                      : "bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-slate-600"
                  }`}
                >
                  Alle
                </button>
                <button
                  onClick={() => update("indoorFilter", "indoor")}
                  className={`flex items-center gap-1 rounded-lg px-3 py-2 text-sm font-medium transition-all ${
                    filters.indoorFilter === "indoor"
                      ? "bg-blue-600 text-white shadow-md"
                      : "bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-slate-600"
                  }`}
                >
                  <Home className="h-4 w-4" />
                  Indoor
                </button>
                <button
                  onClick={() => update("indoorFilter", "outdoor")}
                  className={`flex items-center gap-1 rounded-lg px-3 py-2 text-sm font-medium transition-all ${
                    filters.indoorFilter === "outdoor"
                      ? "bg-green-600 text-white shadow-md"
                      : "bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-slate-600"
                  }`}
                >
                  <Trees className="h-4 w-4" />
                  Outdoor
                </button>
              </div>
            </div>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={filters.kidsOnly}
                onChange={(e) => update("kidsOnly", e.target.checked)}
                className="h-5 w-5 rounded border-gray-300 dark:border-slate-500 dark:bg-slate-700 text-blue-600 focus:ring-blue-500 focus:ring-2"
              />
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Kinderfreundlich</span>
            </label>
          </div>

          {/* Row 3: Time of day */}
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <Clock className="h-5 w-5 text-blue-600" />
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Tageszeit:</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {(["all", "vormittags", "nachmittags", "abends"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => update("timeOfDay", f)}
                  className={`rounded-full px-3 py-1.5 text-sm font-medium transition-all ${
                    filters.timeOfDay === f
                      ? "bg-blue-600 text-white shadow-md"
                      : "bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-slate-600"
                  }`}
                >
                  {f === "all" && "Alle"}
                  {f === "vormittags" && "Vormittags"}
                  {f === "nachmittags" && "Nachmittags"}
                  {f === "abends" && "Abends"}
                </button>
              ))}
            </div>
          </div>

          {/* Row 4: Travel time */}
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <Map className="h-5 w-5 text-blue-600" />
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Fahrzeit:</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {[0, 15, 30, 45, 60].map((mins) => (
                <button
                  key={mins}
                  onClick={() => update("maxTravelTime", mins)}
                  className={`rounded-full px-3 py-1.5 text-sm font-medium transition-all ${
                    filters.maxTravelTime === mins
                      ? "bg-blue-600 text-white shadow-md"
                      : "bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-slate-600"
                  }`}
                >
                  {mins === 0 ? "Alle" : `≤${mins} Min`}
                </button>
              ))}
            </div>
          </div>

          {/* Row 5: Sort */}
          <div className="flex flex-wrap items-center gap-4">
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Sortierung:</span>
            <select
              value={filters.sort}
              onChange={(e) => update("sort", e.target.value as SortMode)}
              className="rounded-lg border border-gray-300 dark:border-slate-600 dark:bg-slate-700 dark:text-gray-200 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200 focus:outline-none"
            >
              <option value="smart">Smart (Datum + Qualität)</option>
              <option value="start_at">Nach Datum</option>
              <option value="quality">Nach Qualität</option>
              <option value="travel">Nach Fahrzeit</option>
            </select>
          </div>
        </div>

        {/* Row 6: View controls */}
        <div className="flex flex-wrap items-center gap-4 border-t dark:border-slate-700 pt-4">
          <div className="ml-auto flex items-center gap-2">
            <div className="flex items-center gap-1 rounded-lg bg-gray-100 dark:bg-slate-700 p-1">
              <button
                onClick={() => update("viewMode", "grid")}
                className={`flex items-center gap-1 rounded-md px-3 py-2 text-sm font-medium transition-all ${
                  filters.viewMode === "grid"
                    ? "bg-white dark:bg-slate-600 shadow-sm text-gray-900 dark:text-white"
                    : "text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                }`}
                title="Rasteransicht"
              >
                <Grid className="h-4 w-4" />
              </button>
              <button
                onClick={() => update("viewMode", "list")}
                className={`flex items-center gap-1 rounded-md px-3 py-2 text-sm font-medium transition-all ${
                  filters.viewMode === "list"
                    ? "bg-white dark:bg-slate-600 shadow-sm text-gray-900 dark:text-white"
                    : "text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                }`}
                title="Listenansicht"
              >
                <List className="h-4 w-4" />
              </button>
              <button
                onClick={() => update("viewMode", "map")}
                className={`flex items-center gap-1 rounded-md px-3 py-2 text-sm font-medium transition-all ${
                  filters.viewMode === "map"
                    ? "bg-white dark:bg-slate-600 shadow-sm text-gray-900 dark:text-white"
                    : "text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                }`}
                title="Kartenansicht"
              >
                <Map className="h-4 w-4" />
              </button>
            </div>

            {filters.viewMode !== "map" && (
              <button
                onClick={() => update("showMiniMap", !filters.showMiniMap)}
                className="flex items-center gap-1 rounded-lg px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                title={filters.showMiniMap ? "Mini-Karte ausblenden" : "Mini-Karte einblenden"}
              >
                {filters.showMiniMap ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                Karte
              </button>
            )}

            {hasActiveFilters && (
              <button
                onClick={clearFilters}
                className="flex items-center gap-1 rounded-lg px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
              >
                <FilterX className="h-4 w-4" />
                Reset
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="text-sm text-gray-500 dark:text-gray-400">
        <span>{visibleEvents.length} Events gefunden</span>
      </div>

      <div className="flex flex-col gap-4">
        {visibleEvents.length === 0 ? (
          <div className="rounded-xl bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 py-16 text-center">
            <Map className="mx-auto h-12 w-12 text-gray-400 dark:text-gray-500 mb-4" />
            <p className="text-lg font-medium text-gray-900 dark:text-white">Keine Events gefunden</p>
            <p className="text-gray-500 dark:text-gray-400 mt-1 px-4">
              {filters.favoritesOnly && favorites.length === 0
                ? "Markiere Events mit dem Herz, um sie hier zu sehen."
                : filters.search
                ? `Keine Treffer für „${filters.search}". Versuche einen anderen Begriff.`
                : filters.dateFilter === "today"
                ? "Heute ist nichts mehr drin. Schau es dir morgen an oder erweitere den Zeitraum."
                : "Versuche die Filter anzupassen oder erweitere den Zeitraum."}
            </p>
            <div className="mt-4 flex justify-center gap-3 flex-wrap">
              {filters.dateFilter === "today" && (
                <button
                  onClick={() => update("dateFilter", "tomorrow")}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
                >
                  Morgen anzeigen
                </button>
              )}
              <button onClick={clearFilters} className="text-blue-600 hover:underline self-center">
                Filter zurücksetzen
              </button>
            </div>
          </div>
        ) : filters.viewMode === "map" ? (
          <EventsMap events={visibleEvents} />
        ) : (
          <>
            {filters.showMiniMap && (
              <div className="max-h-[280px] overflow-hidden rounded-xl">
                <EventsMap events={visibleEvents} />
              </div>
            )}
            <div className={`grid gap-4 ${filters.viewMode === "grid" ? "md:grid-cols-2 lg:grid-cols-3" : "grid-cols-1"}`}>
              {visibleEvents.map((event) => (
                <EventCard key={event.canonical_id} event={event} now={now} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
