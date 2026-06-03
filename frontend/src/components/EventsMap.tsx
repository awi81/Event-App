"use client";

import { useEffect, useSyncExternalStore } from "react";
import { Event } from "@/lib/api";
import { withBasePath } from "@/lib/snapshot";
import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import "leaflet/dist/leaflet.css";
import L from "leaflet";

// Mount-Guard via useSyncExternalStore - avoids the ESLint
// react-hooks/set-state-in-effect rule but still defers Leaflet's TileLayer
// initialization until after the DOM container exists (otherwise React's HMR
// re-renders can hit Leaflet before its container ref is attached, throwing
// "Cannot read properties of undefined (reading 'appendChild')").
const emptySubscribe = () => () => {};
const getClientSnapshot = () => true;
const getServerSnapshot = () => false;
function useIsMounted(): boolean {
  return useSyncExternalStore(emptySubscribe, getClientSnapshot, getServerSnapshot);
}

// Category → color mapping
const CATEGORY_COLORS: Record<string, string> = {
  "Familie & Kinder": "#22c55e",       // green
  "Kultur & Sonstiges": "#a855f7",     // purple
  "Museum & Ausstellung": "#3b82f6",   // blue
  "Freizeitorte & Attraktionen": "#f97316", // orange
  "Food & Street-Food": "#ef4444",     // red
  "Märkte": "#eab308",                 // yellow
  "Feste & Festivals": "#ec4899",      // pink
  "Workshops & Mitmachen": "#8b5cf6",  // violet
};
const DEFAULT_COLOR = "#6b7280"; // gray

function createColoredIcon(color: string): L.DivIcon {
  return L.divIcon({
    className: "",
    iconSize: [28, 36],
    iconAnchor: [14, 36],
    popupAnchor: [0, -36],
    html: `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="36" viewBox="0 0 28 36">
      <path d="M14 0C6.3 0 0 6.3 0 14c0 10.5 14 22 14 22s14-11.5 14-22C28 6.3 21.7 0 14 0z" fill="${color}" stroke="#fff" stroke-width="1.5"/>
      <circle cx="14" cy="14" r="5" fill="#fff"/>
    </svg>`,
  });
}

const iconCache = new Map<string, L.DivIcon>();
function getIconForCategory(category?: string): L.DivIcon {
  const color = (category && CATEGORY_COLORS[category]) || DEFAULT_COLOR;
  if (!iconCache.has(color)) {
    iconCache.set(color, createColoredIcon(color));
  }
  return iconCache.get(color)!;
}

interface EventsMapProps {
  events: Event[];
}

// Essen Werden center coordinates
const ESSEN_WERDEN = [51.3833, 7.0333] as [number, number];

// Keeps the viewport in sync with the (filtered) markers: fits the map to the
// bounding box of all visible points whenever that set changes. Without this the
// map stayed locked on Werden/zoom 13 and markers further north were off-screen.
function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  // Stable signature so we only re-fit when the actual set of points changes,
  // not on every parent re-render (which hands us a fresh array reference).
  const key = points
    .map((p) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`)
    .sort()
    .join("|");
  useEffect(() => {
    if (points.length === 0) {
      map.setView(ESSEN_WERDEN, 12);
      return;
    }
    if (points.length === 1) {
      map.setView(points[0], 14);
      return;
    }
    map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 15 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map]);
  return null;
}

export function EventsMap({ events }: EventsMapProps) {
  const isMounted = useIsMounted();

  const eventsWithCoords = events.filter(
    (e) => e.lat !== null && e.lon !== null && e.lat !== undefined && e.lon !== undefined
  );

  if (!isMounted) {
    return (
      <div className="h-[500px] w-full rounded-xl bg-gray-100 dark:bg-slate-800 animate-pulse flex items-center justify-center">
        <p className="text-gray-500 dark:text-gray-400">Karte wird geladen...</p>
      </div>
    );
  }

  // Collect used categories for legend
  const usedCategories = new Set(eventsWithCoords.map((e) => e.category).filter(Boolean));

  return (
    <div className="space-y-2">
    <div className="h-[500px] w-full rounded-xl overflow-hidden shadow-lg border border-gray-200 dark:border-slate-700">
      <MapContainer
        center={ESSEN_WERDEN}
        zoom={13}
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds points={eventsWithCoords.map((e) => [e.lat!, e.lon!] as [number, number])} />
        <MarkerClusterGroup
          chunkedLoading
          maxClusterRadius={40}
          spiderfyOnMaxZoom
          showCoverageOnHover={false}
        >
          {eventsWithCoords.map((event) => (
            <Marker
              key={event.canonical_id}
              position={[event.lat!, event.lon!]}
              icon={getIconForCategory(event.category)}
            >
              <Popup>
                <div className="min-w-[220px]">
                  <a href={withBasePath(`/events/${event.id}/`)} className="font-semibold text-sm text-blue-700 hover:underline">
                    {event.title}
                  </a>
                  {event.venue_name && (
                    <p className="text-xs text-gray-600 mt-1">{event.venue_name}</p>
                  )}
                  {event.start_at && (
                    <p className="text-xs text-gray-500 mt-1">
                      {new Date(event.start_at).toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-1 mt-1">
                    {event.category && (
                      <span className="text-xs px-1.5 py-0.5 rounded" style={{ backgroundColor: (CATEGORY_COLORS[event.category] || DEFAULT_COLOR) + "22", color: CATEGORY_COLORS[event.category] || DEFAULT_COLOR }}>
                        {event.category}
                      </span>
                    )}
                    {event.kids_suitable === "yes" && (
                      <span className="text-xs text-green-700 bg-green-50 px-1.5 py-0.5 rounded">Kinderfreundlich</span>
                    )}
                  </div>
                  {event.travel_time_minutes && (
                    <p className="text-xs text-gray-400 mt-1">~{event.travel_time_minutes} Min ab Werden</p>
                  )}
                </div>
              </Popup>
            </Marker>
          ))}
        </MarkerClusterGroup>
      </MapContainer>
    </div>
    {/* Legend */}
    <div className="flex flex-wrap items-center gap-3 px-1 text-xs text-gray-500 dark:text-gray-400">
      <span className="font-medium">Legende:</span>
      {Array.from(usedCategories).sort().map((cat) => (
        <span key={cat} className="inline-flex items-center gap-1">
          <span className="inline-block w-3 h-3 rounded-full" style={{ backgroundColor: CATEGORY_COLORS[cat!] || DEFAULT_COLOR }} />
          {cat}
        </span>
      ))}
      <span className="inline-flex items-center gap-1">
        <span className="inline-block w-3 h-3 rounded-full" style={{ backgroundColor: DEFAULT_COLOR }} />
        Sonstige
      </span>
      <span className="ml-auto">{eventsWithCoords.length} von {events.length} Events auf Karte</span>
    </div>
    </div>
  );
}

