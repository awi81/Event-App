"use client";

import { Event } from "@/lib/api";
import Link from "next/link";
import { Star, MapPin, Clock } from "lucide-react";

interface TopPicksProps {
  events: Event[];
}

export function TopPicks({ events }: TopPicksProps) {
  const picks = events
    .filter((e) => (e.quality_score ?? 0) >= 0.6)
    .slice()
    .sort((a, b) => (b.quality_score ?? 0) - (a.quality_score ?? 0))
    .slice(0, 3);

  if (picks.length < 2) return null;

  return (
    <div className="rounded-xl border border-amber-200 dark:border-amber-900/40 bg-gradient-to-br from-amber-50 to-orange-50 dark:from-amber-950/30 dark:to-slate-800 p-4">
      <div className="flex items-center gap-2 mb-3">
        <Star className="h-5 w-5 text-amber-600 fill-amber-400" />
        <h2 className="font-semibold text-gray-900 dark:text-white">Top-Picks für dich</h2>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {picks.map((e) => (
          <Link
            key={e.canonical_id}
            href={`/events/${e.id}`}
            className="block rounded-lg bg-white dark:bg-slate-700/50 p-3 shadow-sm hover:shadow-md transition-shadow"
          >
            <h3 className="font-medium text-gray-900 dark:text-white text-sm line-clamp-2">{e.title}</h3>
            {e.venue_name && (
              <p className="mt-1 inline-flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
                <MapPin className="h-3 w-3" />
                {e.venue_name}
              </p>
            )}
            {e.travel_time_minutes != null && (
              <p className="mt-0.5 inline-flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
                <Clock className="h-3 w-3" />
                ~{e.travel_time_minutes} Min
              </p>
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}
