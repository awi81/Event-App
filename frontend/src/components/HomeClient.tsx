"use client";

import { useSnapshot } from "@/lib/useSnapshot";
import { WeatherBanner } from "./WeatherBanner";
import { EventsList } from "./EventsList";
import { EventsListSkeleton } from "./EventCardSkeleton";

export function HomeClient() {
  const snap = useSnapshot();

  if (snap.status === "error") {
    return (
      <div className="rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-6 text-center">
        <p className="text-red-700 dark:text-red-400 font-medium">Events konnten nicht geladen werden</p>
        <p className="text-red-600 dark:text-red-400 text-sm mt-1">Bitte lade die Seite später neu.</p>
      </div>
    );
  }

  if (snap.status !== "ready") {
    return (
      <div className="space-y-6">
        <div className="h-20 rounded-xl bg-gray-100 dark:bg-slate-800 animate-pulse" />
        <EventsListSkeleton />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <WeatherBanner weather={snap.data.weather_today} />
      <EventsList events={snap.data.events} />
    </div>
  );
}
