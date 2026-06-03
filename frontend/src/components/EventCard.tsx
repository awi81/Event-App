"use client";

import { Event, Occurrence } from "@/lib/api";
import { useFavorites } from "@/lib/favorites";
import { format, parseISO, isToday, isTomorrow, isSaturday, isSunday, isSameDay } from "date-fns";
import { de } from "date-fns/locale";
import {
  Calendar,
  MapPin,
  Clock,
  Users,
  ExternalLink,
  Home,
  Trees,
  Heart,
  CheckCircle2,
  Layers,
  CalendarDays,
} from "lucide-react";
import Link from "next/link";

interface EventCardProps {
  event: Event;
  /** View-time clock, used to suppress past occurrences in the badge row. */
  now?: Date;
}

export function EventCard({ event, now }: EventCardProps) {
  const { isFavorite, toggle } = useFavorites();
  const favorite = isFavorite(event.canonical_id);

  const formatEventDate = (dateStr?: string) => {
    if (!dateStr) return null;
    try {
      const date = parseISO(dateStr);
      let label = "";
      if (isToday(date)) label = "Heute";
      else if (isTomorrow(date)) label = "Morgen";
      else if (isSaturday(date) || isSunday(date)) label = "Wochenende";
      return { label, time: format(date, "EEEE, d. MMM • HH:mm", { locale: de }) };
    } catch {
      return null;
    }
  };

  const dateInfo = formatEventDate(event.start_at);

  // Only show "additional" occurrences (i.e. drop the one that's already in the
  // date header) and strip any occurrences that are already in the past.
  const nowMs = now ? now.getTime() : Date.now();
  const additionalOccurrences: Occurrence[] = (event.occurrences || [])
    .filter((o) => {
      if (!o.start_at) return false;
      if (event.start_at && o.start_at === event.start_at) return false;
      // parseLocal equivalent: treat the string as local time (no Z suffix)
      const d = new Date(o.start_at);
      if (isNaN(d.getTime())) return false;
      return d.getTime() >= nowMs;
    })
    .slice(0, 8);

  const formatOcc = (occ: Occurrence): string => {
    if (!occ.start_at) return "?";
    try {
      const d = parseISO(occ.start_at);
      const head = event.start_at ? parseISO(event.start_at) : null;
      // If same day as the headline, just show the time
      if (head && isSameDay(d, head)) {
        return format(d, "HH:mm", { locale: de });
      }
      return format(d, "EEE, d. MMM HH:mm", { locale: de });
    } catch {
      return occ.start_at;
    }
  };

  const kidsBadge = () => {
    if (event.kids_suitable === "yes") {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-green-100 dark:bg-green-900/30 px-2 py-1 text-xs font-medium text-green-800 dark:text-green-300">
          <Users className="h-3 w-3" /> Kinderfreundlich
        </span>
      );
    }
    if (event.kids_suitable === "likely") {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-lime-100 dark:bg-lime-900/30 px-2 py-1 text-xs font-medium text-lime-800 dark:text-lime-300">
          <Users className="h-3 w-3" /> Wahrscheinlich
        </span>
      );
    }
    if (event.kids_suitable === "unknown") {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 dark:bg-gray-800 px-2 py-1 text-xs font-medium text-gray-500 dark:text-gray-400">
          <Users className="h-3 w-3" /> Alter unbekannt
        </span>
      );
    }
    return null;
  };

  const categoryBadge = () =>
    event.category ? (
      <span className="rounded-full bg-gray-100 dark:bg-slate-700 px-2 py-1 text-xs font-medium text-gray-600 dark:text-gray-300">
        {event.category}
      </span>
    ) : null;

  const indoorOutdoorBadge = () => {
    if (event.indoor_outdoor === "indoor") {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 dark:bg-blue-900/30 px-2 py-1 text-xs font-medium text-blue-800 dark:text-blue-300">
          <Home className="h-3 w-3" /> Indoor
        </span>
      );
    }
    if (event.indoor_outdoor === "outdoor") {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-green-100 dark:bg-green-900/30 px-2 py-1 text-xs font-medium text-green-800 dark:text-green-300">
          <Trees className="h-3 w-3" /> Outdoor
        </span>
      );
    }
    if (event.indoor_outdoor === "both") {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-purple-100 dark:bg-purple-900/30 px-2 py-1 text-xs font-medium text-purple-800 dark:text-purple-300">
          Indoor & Outdoor
        </span>
      );
    }
    return null;
  };

  const multiSourceBadge = () => {
    if ((event.source_count ?? 0) > 1) {
      return (
        <span
          className="inline-flex items-center gap-1 rounded-full bg-emerald-100 dark:bg-emerald-900/30 px-2 py-1 text-xs font-medium text-emerald-800 dark:text-emerald-300"
          title={event.sources_list || ""}
        >
          <Layers className="h-3 w-3" /> Auf {event.source_count} Quellen
        </span>
      );
    }
    return null;
  };

  const qualityBadge = () => {
    const q = event.quality_score;
    if (typeof q !== "number" || q < 0.75) return null;
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-amber-100 dark:bg-amber-900/30 px-2 py-1 text-xs font-medium text-amber-800 dark:text-amber-300"
        title={`Qualität: ${(q * 100).toFixed(0)}%`}
      >
        <CheckCircle2 className="h-3 w-3" /> Top-Pick
      </span>
    );
  };

  const noLocationBadge = () => {
    const hasVenue = !!(event.venue_name || event.address_text);
    const hasCoords = event.lat != null && event.lon != null;
    if (!hasVenue && !hasCoords) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 dark:bg-slate-700 px-2 py-1 text-xs font-medium text-gray-500 dark:text-gray-400">
          Ort unbekannt
        </span>
      );
    }
    if (hasVenue && !hasCoords) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 dark:bg-slate-700 px-2 py-1 text-xs font-medium text-gray-500 dark:text-gray-400">
          Nicht auf Karte
        </span>
      );
    }
    return null;
  };

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-sm transition-shadow hover:shadow-md dark:hover:shadow-slate-900/50 overflow-hidden">
      {event.image_url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={event.image_url}
          alt={event.title}
          loading="lazy"
          className="w-full h-40 object-cover bg-gray-100 dark:bg-slate-700"
          onError={(e) => {
            // Hide broken images so the layout doesn't break
            (e.target as HTMLImageElement).style.display = "none";
          }}
        />
      )}
      <div className="flex flex-col gap-3 p-4">
      {dateInfo && (
        <div className="flex items-center gap-2 text-sm">
          <Calendar className="h-4 w-4 text-gray-500 dark:text-gray-400" />
          {dateInfo.label && <span className="font-semibold text-blue-600">{dateInfo.label}</span>}
          <span className="text-gray-600 dark:text-gray-300">{dateInfo.time}</span>
        </div>
      )}

      <div className="flex items-start justify-between gap-2">
        <Link href={`/events/${event.id}`} className="hover:text-blue-600 transition-colors">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{event.title}</h3>
        </Link>
        <button
          onClick={() => toggle(event.canonical_id)}
          className="shrink-0 p-1 rounded-full hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
          title={favorite ? "Aus Favoriten entfernen" : "Zu Favoriten hinzufügen"}
        >
          <Heart className={`h-5 w-5 ${favorite ? "fill-red-500 text-red-500" : "text-gray-300 dark:text-gray-600"}`} />
        </button>
      </div>

      {(event.venue_name || event.city) && (
        <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
          <MapPin className="h-4 w-4" />
          <span>
            {event.venue_name}
            {event.city && `, ${event.city}`}
          </span>
        </div>
      )}

      {event.travel_time_minutes != null && (
        <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
          <Clock className="h-4 w-4" />
          <span>~{event.travel_time_minutes} Min ab Werden</span>
          {event.distance_km != null && (
            <span className="text-gray-400 dark:text-gray-500">({event.distance_km} km)</span>
          )}
        </div>
      )}

      {!event.start_at && !event.is_permanent_offer && (
        <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
          <Clock className="h-4 w-4" />
          <span>Zeit auf Anfrage</span>
        </div>
      )}

      {additionalOccurrences.length > 0 && (
        <div className="flex items-start gap-2 text-xs text-gray-600 dark:text-gray-300">
          <CalendarDays className="h-4 w-4 mt-0.5 shrink-0 text-blue-500" />
          <div className="flex flex-wrap gap-1.5">
            <span className="text-gray-500 dark:text-gray-400">Weitere Termine:</span>
            {additionalOccurrences.map((occ) => (
              <span
                key={occ.id}
                className="rounded-md bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 px-2 py-0.5"
              >
                {formatOcc(occ)}
              </span>
            ))}
            {(event.occurrences?.length || 0) > additionalOccurrences.length + 1 && (
              <Link href={`/events/${event.id}`} className="text-blue-600 hover:underline">
                +{(event.occurrences?.length || 0) - additionalOccurrences.length - 1} mehr
              </Link>
            )}
          </div>
        </div>
      )}

      {event.short_description && (
        <p className="line-clamp-2 text-sm text-gray-600 dark:text-gray-300">{event.short_description}</p>
      )}

      {/* Heute-Events: das WeatherBanner oben zeigt denselben Hinweis bereits —
          nur bei zukünftigen Events trägt die Notiz (Forecast des Event-Tags)
          echte Zusatzinfo. */}
      {event.weather_note && !(event.start_at && isToday(parseISO(event.start_at))) && (
        <p className="text-sm text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/20 rounded-md px-2 py-1">
          {event.weather_note}
        </p>
      )}

      {event.price_text && (
        <p className="text-sm font-medium text-gray-900 dark:text-white">{event.price_text}</p>
      )}

      <div className="flex flex-wrap gap-2">
        {event.is_permanent_offer && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 dark:bg-amber-900/30 px-2 py-1 text-xs font-medium text-amber-800 dark:text-amber-300">
            Dauerangebot
          </span>
        )}
        {qualityBadge()}
        {multiSourceBadge()}
        {indoorOutdoorBadge()}
        {kidsBadge()}
        {noLocationBadge()}
        {categoryBadge()}
      </div>

      <div className="flex items-center justify-between text-sm">
        {event.source_url ? (
          <a
            href={event.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400 hover:underline"
          >
            <ExternalLink className="h-3 w-3" />
            Mehr Infos
          </a>
        ) : null}
        {event.source_name && (
          <span className="text-xs text-gray-400 dark:text-gray-500">via {event.source_name}</span>
        )}
      </div>
      </div>
    </div>
  );
}
