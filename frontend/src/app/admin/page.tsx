"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  RefreshCw,
  Loader2,
  Database,
  BarChart3,
  AlertTriangle,
  ExternalLink,
  ShieldCheck,
  Activity,
} from "lucide-react";
import { API_BASE, syncEvents } from "@/lib/api";

interface AdminStats {
  total_events: number;
  active_events: number;
  archived_events: number;
  average_quality: number | null;
  sources: Record<string, number>;
  data_quality: {
    ohne_koordinaten: number;
    ohne_kategorie: number;
    ohne_datum: number;
    ohne_beschreibung: number;
  };
  categories: Record<string, number>;
  crawl_history: Array<{
    source: string;
    started_at: string | null;
    finished_at: string | null;
    status: string;
    items_found: number;
    items_created: number;
    items_updated: number;
    items_merged: number;
    error: string | null;
  }>;
}

interface ProblemEvent {
  id: number;
  canonical_id: string;
  title: string;
  source_name: string | null;
  source_url: string | null;
  venue_name: string | null;
  city: string | null;
  start_at: string | null;
  category: string | null;
  lat: number | null;
  lon: number | null;
  quality_score: number | null;
}

type ProblemKind = "no_coords" | "no_date" | "no_category" | "no_desc";

interface RobotsResult {
  source: string;
  base_url: string;
  robots_url: string | null;
  fetched: boolean;
  allowed: boolean | null;
  crawl_delay: number | null;
  excerpt: string | null;
  error: string | null;
}

interface SourceHealth {
  source: string;
  base_url: string;
  source_type: string;
  status: "green" | "yellow" | "red" | "stale" | "unknown";
  active_events: number;
  last_run_at: string | null;
  last_run_status: string | null;
  last_run_found: number | null;
  last_run_error: string | null;
  last_success_at: string | null;
  last_success_found: number | null;
  trend_found: number[];
}

const PROBLEM_LABELS: Record<ProblemKind, string> = {
  no_coords: "Ohne Koordinaten",
  no_date: "Ohne Datum",
  no_category: "Ohne Kategorie",
  no_desc: "Ohne Beschreibung",
};

export default function AdminPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<{ synced: number; details: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedProblem, setExpandedProblem] = useState<ProblemKind | null>(null);
  const [robotsResults, setRobotsResults] = useState<RobotsResult[] | null>(null);
  const [robotsLoading, setRobotsLoading] = useState(false);
  const [sourcesHealth, setSourcesHealth] = useState<SourceHealth[] | null>(null);
  const [problemEvents, setProblemEvents] = useState<Record<ProblemKind, ProblemEvent[] | null>>({
    no_coords: null,
    no_date: null,
    no_category: null,
    no_desc: null,
  });

  const fetchStats = async () => {
    try {
      const [statsRes, healthRes] = await Promise.all([
        fetch(`${API_BASE}/admin/stats`),
        fetch(`${API_BASE}/admin/sources-health`),
      ]);
      if (!statsRes.ok) throw new Error("Failed to fetch stats");
      setStats(await statsRes.json());
      if (healthRes.ok) {
        const data = await healthRes.json();
        setSourcesHealth(data.sources);
      }
    } catch {
      setError("Stats konnten nicht geladen werden");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, []);

  const toggleProblem = async (kind: ProblemKind) => {
    if (expandedProblem === kind) {
      setExpandedProblem(null);
      return;
    }
    setExpandedProblem(kind);
    if (problemEvents[kind] === null) {
      try {
        const res = await fetch(`${API_BASE}/admin/events-problems?kind=${kind}&limit=50`);
        if (res.ok) {
          const data = await res.json();
          setProblemEvents((prev) => ({ ...prev, [kind]: data }));
        }
      } catch (e) {
        console.error(e);
      }
    }
  };

  const runRobotsCheck = async () => {
    setRobotsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/admin/robots-check`);
      if (res.ok) {
        const data = await res.json();
        setRobotsResults(data.results);
      }
    } finally {
      setRobotsLoading(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const result = await syncEvents();
      setSyncResult(result);
      // Reset problem caches so they reflect new data on next open
      setProblemEvents({ no_coords: null, no_date: null, no_category: null, no_desc: null });
      await fetchStats();
    } catch {
      setError("Sync fehlgeschlagen");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <header className="bg-white dark:bg-slate-800 shadow-sm border-b border-gray-100 dark:border-slate-700">
        <div className="mx-auto max-w-5xl px-4 py-4 sm:px-6 flex items-center justify-between">
          <div>
            <Link
              href="/"
              className="inline-flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 hover:text-blue-600 mb-2"
            >
              <ArrowLeft className="h-4 w-4" />
              Zurück
            </Link>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Admin / Debug</h1>
          </div>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 shadow-md transition-all"
          >
            {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {syncing ? "Sync läuft..." : "Sync starten"}
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-6 sm:px-6 space-y-6">
        {error && (
          <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 text-red-700 dark:text-red-400">
            {error}
          </div>
        )}

        {syncResult && (
          <div className="rounded-xl bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 p-5">
            <h2 className="font-semibold text-green-800 dark:text-green-300 mb-2">
              Sync abgeschlossen: {syncResult.synced} Events
            </h2>
            <ul className="space-y-1">
              {syncResult.details.map((d, i) => (
                <li key={i} className="text-sm text-green-700 dark:text-green-400 font-mono">
                  {d}
                </li>
              ))}
            </ul>
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-gray-400 dark:text-gray-500" />
          </div>
        ) : stats ? (
          <>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <StatCard label="Aktive Events" value={stats.active_events} icon={<Database className="h-5 w-5" />} color="blue" />
              <StatCard label="Archiviert" value={stats.archived_events} icon={<Database className="h-5 w-5" />} color="gray" />
              <StatCard label="Gesamt" value={stats.total_events} icon={<BarChart3 className="h-5 w-5" />} color="purple" />
              <StatCard
                label="Ø Qualität"
                value={stats.average_quality != null ? `${(stats.average_quality * 100).toFixed(0)}%` : "-"}
                icon={<BarChart3 className="h-5 w-5" />}
                color="amber"
              />
              <StatCard label="Ohne Koordinaten" value={stats.data_quality.ohne_koordinaten} icon={<AlertTriangle className="h-5 w-5" />} color="amber" />
            </div>

            <div className="rounded-xl bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 p-5">
              <h2 className="font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                <Activity className="h-5 w-5 text-blue-600" />
                Quellen-Health
              </h2>
              {sourcesHealth ? (
                <div className="space-y-2">
                  {sourcesHealth.map((s) => (
                    <SourceHealthRow key={s.source} health={s} />
                  ))}
                </div>
              ) : (
                <div className="space-y-3">
                  {Object.entries(stats.sources)
                    .sort(([, a], [, b]) => b - a)
                    .map(([source, count]) => (
                      <div key={source} className="flex items-center justify-between text-sm text-gray-700 dark:text-gray-300">
                        <span>{source}</span>
                        <span className="font-medium text-gray-900 dark:text-white">{count}</span>
                      </div>
                    ))}
                </div>
              )}
            </div>

            <div className="rounded-xl bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 p-5">
              <h2 className="font-semibold text-gray-900 dark:text-white mb-4">Datenqualität (klick für Details)</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {(["no_coords", "no_category", "no_date", "no_desc"] as const).map((kind) => {
                  const value =
                    kind === "no_coords"
                      ? stats.data_quality.ohne_koordinaten
                      : kind === "no_date"
                      ? stats.data_quality.ohne_datum
                      : kind === "no_category"
                      ? stats.data_quality.ohne_kategorie
                      : stats.data_quality.ohne_beschreibung;
                  const pct = stats.active_events > 0 ? Math.round((value / stats.active_events) * 100) : 0;
                  const isGood = pct < 20;
                  return (
                    <button
                      key={kind}
                      onClick={() => toggleProblem(kind)}
                      className={`text-center rounded-lg border p-3 transition-colors ${
                        expandedProblem === kind
                          ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20"
                          : "border-gray-200 dark:border-slate-700 hover:bg-gray-50 dark:hover:bg-slate-700"
                      }`}
                    >
                      <p className={`text-xl font-bold ${isGood ? "text-green-600" : "text-amber-600"}`}>{value}</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">{PROBLEM_LABELS[kind]}</p>
                      <p className="text-xs text-gray-400 dark:text-gray-500">{pct}%</p>
                    </button>
                  );
                })}
              </div>
              {expandedProblem && (
                <div className="mt-4 border-t dark:border-slate-700 pt-4">
                  <h3 className="font-medium text-gray-800 dark:text-gray-200 mb-2">
                    {PROBLEM_LABELS[expandedProblem]}
                  </h3>
                  {problemEvents[expandedProblem] === null ? (
                    <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
                  ) : (problemEvents[expandedProblem] || []).length === 0 ? (
                    <p className="text-sm text-gray-500">Keine Einträge.</p>
                  ) : (
                    <ul className="space-y-2 max-h-96 overflow-auto">
                      {(problemEvents[expandedProblem] || []).map((p) => (
                        <li
                          key={p.id}
                          className="flex items-start gap-3 text-sm rounded-md bg-gray-50 dark:bg-slate-900/50 p-2"
                        >
                          <div className="flex-1 min-w-0">
                            <Link
                              href={`/events/${p.id}`}
                              className="font-medium text-gray-900 dark:text-white hover:text-blue-600 block truncate"
                            >
                              {p.title}
                            </Link>
                            <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                              {p.source_name}
                              {p.venue_name ? ` • ${p.venue_name}` : ""}
                              {p.start_at ? ` • ${new Date(p.start_at).toLocaleString("de-DE")}` : ""}
                            </p>
                          </div>
                          {p.source_url && (
                            <a
                              href={p.source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="shrink-0 text-blue-600 hover:underline text-xs inline-flex items-center gap-1"
                            >
                              <ExternalLink className="h-3 w-3" />
                              Quelle
                            </a>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>

            <div className="rounded-xl bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 p-5">
              <h2 className="font-semibold text-gray-900 dark:text-white mb-4">Kategorien</h2>
              <div className="flex flex-wrap gap-2">
                {Object.entries(stats.categories)
                  .sort(([, a], [, b]) => b - a)
                  .map(([cat, count]) => (
                    <span
                      key={cat}
                      className="rounded-full bg-gray-100 dark:bg-slate-700 px-3 py-1 text-sm text-gray-700 dark:text-gray-300"
                    >
                      {cat} <span className="font-semibold">{count}</span>
                    </span>
                  ))}
              </div>
            </div>

            <div className="rounded-xl bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 p-5">
              <div className="flex items-center justify-between mb-4 gap-3">
                <h2 className="font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                  <ShieldCheck className="h-5 w-5 text-emerald-600" />
                  Robots.txt-Compliance
                </h2>
                <button
                  onClick={runRobotsCheck}
                  disabled={robotsLoading}
                  className="inline-flex items-center gap-1 text-sm rounded-lg bg-emerald-600 px-3 py-1.5 text-white hover:bg-emerald-700 disabled:opacity-50"
                >
                  {robotsLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                  Live prüfen
                </button>
              </div>
              {robotsResults === null ? (
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Noch nicht geprüft. Der Check holt die robots.txt jeder Quelle und prüft, ob unser
                  User-Agent die Basis-URL crawlen darf.
                </p>
              ) : (
                <ul className="space-y-2">
                  {robotsResults.map((r) => (
                    <li
                      key={r.source}
                      className="flex items-center justify-between rounded-md bg-gray-50 dark:bg-slate-900/50 p-2 text-sm"
                    >
                      <div className="flex-1 min-w-0">
                        <p className="font-medium dark:text-gray-200">{r.source}</p>
                        {r.crawl_delay && (
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            Crawl-Delay: {r.crawl_delay}s
                          </p>
                        )}
                        {r.error && <p className="text-xs text-red-600">{r.error}</p>}
                      </div>
                      <span
                        className={`text-xs px-2 py-0.5 rounded font-medium ${
                          r.allowed === true
                            ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                            : r.allowed === false
                            ? "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400"
                            : "bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400"
                        }`}
                      >
                        {r.allowed === true ? "erlaubt" : r.allowed === false ? "blockiert" : "unbekannt"}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="rounded-xl bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 p-5">
              <h2 className="font-semibold text-gray-900 dark:text-white mb-4">Letzte Crawl-Runs</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b dark:border-slate-700 text-left text-gray-500 dark:text-gray-400">
                      <th className="pb-2 pr-4">Quelle</th>
                      <th className="pb-2 pr-4">Status</th>
                      <th className="pb-2 pr-4">Found</th>
                      <th className="pb-2 pr-4">Neu</th>
                      <th className="pb-2 pr-4">Upd</th>
                      <th className="pb-2 pr-4">Merged</th>
                      <th className="pb-2 pr-4">Zeit</th>
                      <th className="pb-2">Fehler</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.crawl_history.map((run, i) => (
                      <tr key={i} className="border-b border-gray-100 dark:border-slate-700">
                        <td className="py-2 pr-4 font-medium dark:text-gray-200">{run.source}</td>
                        <td className="py-2 pr-4">
                          <span
                            className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                              run.status === "success"
                                ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                                : run.status === "error"
                                ? "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400"
                                : "bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400"
                            }`}
                          >
                            {run.status}
                          </span>
                        </td>
                        <td className="py-2 pr-4 dark:text-gray-300">{run.items_found ?? "-"}</td>
                        <td className="py-2 pr-4 dark:text-gray-300">{run.items_created ?? "-"}</td>
                        <td className="py-2 pr-4 dark:text-gray-300">{run.items_updated ?? "-"}</td>
                        <td className="py-2 pr-4 dark:text-gray-300">{run.items_merged ?? "-"}</td>
                        <td className="py-2 pr-4 text-gray-500 dark:text-gray-400">
                          {run.started_at ? new Date(run.started_at).toLocaleString("de-DE") : "-"}
                        </td>
                        <td className="py-2 text-red-600 text-xs max-w-[200px] truncate" title={run.error || ""}>
                          {run.error || ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}

function SourceHealthRow({ health: s }: { health: SourceHealth }) {
  const dot = {
    green: "bg-green-500",
    yellow: "bg-yellow-500",
    red: "bg-red-500",
    stale: "bg-amber-500",
    unknown: "bg-gray-400",
  }[s.status];

  const statusLabel = {
    green: "OK",
    yellow: "leer",
    red: "Fehler",
    stale: "veraltet",
    unknown: "kein Lauf",
  }[s.status];

  // Sparkline: little bars showing recent items_found
  const maxFound = Math.max(1, ...s.trend_found);
  const sparkline = s.trend_found.slice().reverse(); // oldest left, newest right

  return (
    <div className="flex items-center gap-3 rounded-md bg-gray-50 dark:bg-slate-900/50 p-2 text-sm">
      <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} title={statusLabel} />
      <span className="font-medium text-gray-900 dark:text-white min-w-[140px]">{s.source}</span>
      <span className="text-xs text-gray-500 dark:text-gray-400 w-12 text-right shrink-0">
        {s.active_events} aktiv
      </span>
      <div className="flex items-end gap-0.5 h-5 w-16 shrink-0">
        {sparkline.map((v, i) => (
          <span
            key={i}
            className="bg-blue-500 dark:bg-blue-400 rounded-sm w-2"
            style={{ height: `${Math.max(5, (v / maxFound) * 100)}%`, opacity: v === 0 ? 0.3 : 1 }}
            title={`${v} found`}
          />
        ))}
      </div>
      <span className="text-xs text-gray-500 dark:text-gray-400 ml-auto shrink-0 hidden sm:inline">
        {s.last_run_at
          ? `letzter Lauf: ${new Date(s.last_run_at).toLocaleString("de-DE")}`
          : "noch nie gelaufen"}
      </span>
      {s.last_run_error && (
        <span
          className="text-xs text-red-600 truncate max-w-[200px]"
          title={s.last_run_error}
        >
          {s.last_run_error}
        </span>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  icon,
  color,
}: {
  label: string;
  value: number | string;
  icon: React.ReactNode;
  color: string;
}) {
  const colors: Record<string, string> = {
    blue: "bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800",
    gray: "bg-gray-50 dark:bg-slate-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-slate-700",
    purple: "bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400 border-purple-200 dark:border-purple-800",
    amber: "bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-800",
  };
  return (
    <div className={`rounded-xl border p-4 ${colors[color] || colors.gray}`}>
      <div className="flex items-center gap-2 mb-1">
        {icon}
        <span className="text-xs font-medium uppercase">{label}</span>
      </div>
      <p className="text-2xl font-bold">{value}</p>
    </div>
  );
}
