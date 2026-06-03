"use client";

import { WeatherToday } from "@/lib/api";
import { Cloud, CloudRain, Sun, Snowflake, Zap, CloudDrizzle } from "lucide-react";

function WeatherIcon({ code, className }: { code?: number | null; className?: string }) {
  if (code == null) return <Cloud className={className} />;
  if (code >= 95) return <Zap className={className} />;
  if (code >= 71) return <Snowflake className={className} />;
  if (code >= 61) return <CloudRain className={className} />;
  if (code >= 51) return <CloudDrizzle className={className} />;
  if (code <= 1) return <Sun className={className} />;
  return <Cloud className={className} />;
}

/** Build a local-date string "YYYY-MM-DD" from the visitor's clock — NOT
 *  toISOString() which would give the UTC date and can differ by ±1 day. */
function localTodayString(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// Reads today's forecast from the snapshot wrapper (weather_today) instead of a
// live /weather/today call.
export function WeatherBanner({ weather }: { weather?: WeatherToday | null }) {
  if (!weather || !weather.available) return null;

  // Don't show yesterday's (or tomorrow's) cached forecast as "today"
  if (weather.date && weather.date !== localTodayString()) return null;

  const temp = weather.temp_max != null ? `${Math.round(weather.temp_max)}°C` : "–";
  const rain = weather.rain_probability != null ? `${weather.rain_probability}% Regen` : null;

  return (
    <div className="rounded-xl border border-blue-200 dark:border-blue-900/40 bg-gradient-to-r from-blue-50 to-sky-50 dark:from-blue-950/30 dark:to-slate-800 p-4 flex items-center gap-4">
      <div className="rounded-full bg-white/70 dark:bg-slate-700/70 p-3 shadow-sm">
        <WeatherIcon code={weather.weather_code} className="h-7 w-7 text-blue-600 dark:text-blue-300" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-3 flex-wrap">
          <span className="text-2xl font-bold text-gray-900 dark:text-white">{temp}</span>
          {weather.temp_min != null && (
            <span className="text-sm text-gray-500 dark:text-gray-400">min {Math.round(weather.temp_min)}°C</span>
          )}
          {rain && <span className="text-sm text-gray-500 dark:text-gray-400">{rain}</span>}
        </div>
        {weather.hint && <p className="text-sm text-gray-700 dark:text-gray-300 mt-0.5">{weather.hint}</p>}
      </div>
    </div>
  );
}
