"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Calendar,
  MapPin,
  Clock,
  Users,
  ExternalLink,
  Home,
  Trees,
  Layers,
  CheckCircle2,
  CalendarDays,
} from "lucide-react";
import { format, parseISO } from "date-fns";
import { de } from "date-fns/locale";
import { useSnapshot } from "@/lib/useSnapshot";
import { Event } from "@/lib/api";

// Leaflet touches `window` at module load, so it must not be imported during the
// static prerender — load it client-only.
const MiniMap = dynamic(() => import("@/components/MiniMap").then((m) => ({ default: m.MiniMap })), {
  ssr: false,
  loading: () => <div className="h-[220px] w-full rounded-lg bg-gray-100 dark:bg-slate-700 animate-pulse" />,
});

function findEvent(events: Event[], id: string): Event | null {
  const n = Number(id);
  if (Number.isNaN(n)) return null;
  return (
    events.find((e) => e.id === n || (e.occurrences || []).some((o) => o.id === n)) || null
  );
}

export function EventDetailClient() {
  const params = useParams<{ id: string }>();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;
  const snap = useSnapshot();

  if (snap.status === "loading") {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-slate-900 flex items-center justify-center">
        <div className="h-8 w-8 rounded-full border-2 border-gray-300 border-t-blue-600 animate-spin" />
      </div>
    );
  }

  const event = snap.status === "ready" ? findEvent(snap.data.events, id) : null;

  if (!event) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-slate-900 flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Event nicht gefunden</h1>
          <Link href="/" className="text-blue-600 hover:underline">
            Zurück zur Übersicht
          </Link>
        </div>
      </div>
    );
  }

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return null;
    try {
      return format(parseISO(dateStr), "EEEE, d. MMMM yyyy • HH:mm 'Uhr'", { locale: de });
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      {/* Header */}
      <header className="bg-white dark:bg-slate-800 shadow-sm border-b border-gray-100 dark:border-slate-700">
        <div className="mx-auto max-w-3xl px-4 py-4 sm:px-6">
          <Link
            href="/"
            className="inline-flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 hover:text-blue-600 transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Zurück zur Übersicht
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6 sm:px-6">
        <div className="rounded-xl bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 shadow-sm overflow-hidden">
          {event.image_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={event.image_url}
              alt={event.title}
              className="w-full h-56 sm:h-72 object-cover bg-gray-100 dark:bg-slate-700"
            />
          )}
          {/* Content */}
          <div className="p-6 space-y-5">
            {/* Title */}
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{event.title}</h1>

            {/* Date / all occurrences */}
            {event.occurrences && event.occurrences.length > 1 ? (
              <div className="rounded-lg border border-blue-200 dark:border-blue-900/40 bg-blue-50 dark:bg-blue-950/30 p-4">
                <div className="flex items-center gap-2 mb-3 text-blue-700 dark:text-blue-300">
                  <CalendarDays className="h-5 w-5" />
                  <span className="font-semibold">{event.occurrences.length} Termine</span>
                </div>
                <ul className="space-y-1.5 max-h-72 overflow-auto">
                  {event.occurrences.map((occ) => (
                    <li
                      key={occ.id}
                      className="flex items-center justify-between text-sm rounded-md bg-white/70 dark:bg-slate-800/60 px-3 py-1.5"
                    >
                      <span className="text-gray-800 dark:text-gray-200">
                        {occ.start_at
                          ? format(parseISO(occ.start_at), "EEE, d. MMM yyyy • HH:mm 'Uhr'", { locale: de })
                          : occ.is_permanent_offer
                          ? "Dauerangebot"
                          : "Zeit unbekannt"}
                      </span>
                      {occ.source_url && (
                        <a
                          href={occ.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="ml-2 text-xs text-blue-600 hover:underline inline-flex items-center gap-1"
                        >
                          <ExternalLink className="h-3 w-3" />
                          Quelle
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ) : event.start_at ? (
              <div className="flex items-center gap-3 text-gray-700 dark:text-gray-300">
                <Calendar className="h-5 w-5 text-blue-600" />
                <span className="text-base">{formatDate(event.start_at)}</span>
              </div>
            ) : (
              <div className="flex items-center gap-3 text-gray-500 dark:text-gray-400">
                <Clock className="h-5 w-5" />
                <span>Zeit auf Anfrage</span>
              </div>
            )}

            {/* Venue */}
            {(event.venue_name || event.address_text) && (
              <div className="flex items-center gap-3 text-gray-700 dark:text-gray-300">
                <MapPin className="h-5 w-5 text-blue-600" />
                <div>
                  {event.venue_name && <span className="font-medium">{event.venue_name}</span>}
                  {event.address_text && <span className="text-gray-500 dark:text-gray-400">, {event.address_text}</span>}
                  {event.city && <span className="text-gray-500 dark:text-gray-400">, {event.city}</span>}
                </div>
              </div>
            )}
            {!event.venue_name && !event.address_text && (
              <div className="flex items-center gap-3 text-gray-400 dark:text-gray-500">
                <MapPin className="h-5 w-5" />
                <span>Ort unbekannt</span>
              </div>
            )}

            {/* Travel time */}
            {event.travel_time_minutes && (
              <div className="flex items-center gap-3 text-gray-700 dark:text-gray-300">
                <Clock className="h-5 w-5 text-blue-600" />
                <span>~{event.travel_time_minutes} Min ab Werden ({event.distance_km} km)</span>
              </div>
            )}

            {/* Mini map if coordinates known */}
            {event.lat != null && event.lon != null && (
              <MiniMap lat={event.lat} lon={event.lon} label={event.venue_name || event.title} />
            )}

            {/* Badges */}
            <div className="flex flex-wrap gap-2">
              {event.is_permanent_offer && (
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 dark:bg-amber-900/30 px-3 py-1 text-sm font-medium text-amber-800 dark:text-amber-300">
                  Dauerangebot
                </span>
              )}
              {typeof event.quality_score === "number" && event.quality_score >= 0.75 && (
                <span
                  className="inline-flex items-center gap-1 rounded-full bg-amber-100 dark:bg-amber-900/30 px-3 py-1 text-sm font-medium text-amber-800 dark:text-amber-300"
                  title={`Qualität: ${(event.quality_score * 100).toFixed(0)}%`}
                >
                  <CheckCircle2 className="h-3.5 w-3.5" /> Top-Pick
                </span>
              )}
              {(event.source_count ?? 0) > 1 && (
                <span
                  className="inline-flex items-center gap-1 rounded-full bg-emerald-100 dark:bg-emerald-900/30 px-3 py-1 text-sm font-medium text-emerald-800 dark:text-emerald-300"
                  title={event.sources_list || ""}
                >
                  <Layers className="h-3.5 w-3.5" /> Auf {event.source_count} Quellen
                </span>
              )}
              {event.indoor_outdoor === "indoor" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 dark:bg-blue-900/30 px-3 py-1 text-sm font-medium text-blue-800 dark:text-blue-300">
                  <Home className="h-3.5 w-3.5" /> Indoor
                </span>
              )}
              {event.indoor_outdoor === "outdoor" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-green-100 dark:bg-green-900/30 px-3 py-1 text-sm font-medium text-green-800 dark:text-green-300">
                  <Trees className="h-3.5 w-3.5" /> Outdoor
                </span>
              )}
              {event.indoor_outdoor === "both" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-purple-100 dark:bg-purple-900/30 px-3 py-1 text-sm font-medium text-purple-800 dark:text-purple-300">
                  Indoor & Outdoor
                </span>
              )}
              {event.kids_suitable === "yes" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-green-100 dark:bg-green-900/30 px-3 py-1 text-sm font-medium text-green-800 dark:text-green-300">
                  <Users className="h-3.5 w-3.5" /> Kinderfreundlich
                </span>
              )}
              {event.kids_suitable === "likely" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-lime-100 dark:bg-lime-900/30 px-3 py-1 text-sm font-medium text-lime-800 dark:text-lime-300">
                  <Users className="h-3.5 w-3.5" /> Wahrscheinlich kinderfreundlich
                </span>
              )}
              {event.kids_suitable === "unknown" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 dark:bg-gray-800 px-3 py-1 text-sm font-medium text-gray-500 dark:text-gray-400">
                  <Users className="h-3.5 w-3.5" /> Alter unbekannt
                </span>
              )}
              {event.category && (
                <span className="rounded-full bg-gray-100 dark:bg-slate-700 px-3 py-1 text-sm font-medium text-gray-600 dark:text-gray-300">
                  {event.category}
                </span>
              )}
            </div>

            {/* Weather hint */}
            {event.weather_note && (
              <div className="rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 p-3 text-sm text-amber-800 dark:text-amber-300">
                {event.weather_note}
              </div>
            )}

            {/* Description */}
            {event.short_description && (
              <div className="border-t dark:border-slate-700 pt-5">
                <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
                  Beschreibung
                </h2>
                <p className="text-gray-700 dark:text-gray-300 leading-relaxed">{event.short_description}</p>
              </div>
            )}

            {/* Price */}
            {event.price_text && (
              <div className="border-t dark:border-slate-700 pt-5">
                <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">Preis</h2>
                <p className="text-gray-900 dark:text-white font-medium">{event.price_text}</p>
              </div>
            )}

            {/* Source */}
            <div className="border-t dark:border-slate-700 pt-5 flex items-center justify-between flex-wrap gap-3">
              {event.source_url && (
                <a
                  href={event.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
                >
                  <ExternalLink className="h-4 w-4" />
                  Originalquelle öffnen
                </a>
              )}
              <span className="text-sm text-gray-400 dark:text-gray-500">
                Quelle: {event.sources_list || event.source_name}
              </span>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
