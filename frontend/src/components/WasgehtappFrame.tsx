"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ExternalLink, MapPinned } from "lucide-react";

// wasgehtapp.de licenses its event data (paid JSON-API, no storage allowed), so
// the app does not crawl it. What they offer for free is this iFrame with the
// events around a city (max. 20 km, one embed per domain). It is loaded only
// after a click: the frame is served by wasgehtapp.de and sees the visitor's IP.
const ORIGIN = "https://www.wasgehtapp.de";
const PARAMS =
  "location_id=&kat=konzert,disco,literatur,comedy,theater,vortrag,sport,sonstige,kunst" +
  "&geo_id=16348&ort=Essen&x=7.00865&y=51.4625&select_ort=1&radius=20";

export function WasgehtappFrame() {
  const [open, setOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const [height, setHeight] = useState(600);
  const frameRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    if (!open) return;
    // The frame reports its content height via postMessage (their embed snippet).
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== ORIGIN) return;
      const h = (event.data as { FrameHeight?: unknown } | null)?.FrameHeight;
      if (typeof h === "number" && h > 0) setHeight(h);
    };
    const ask = () => frameRef.current?.contentWindow?.postMessage("FrameHeight", ORIGIN);
    window.addEventListener("message", onMessage);
    window.addEventListener("resize", ask);
    return () => {
      window.removeEventListener("message", onMessage);
      window.removeEventListener("resize", ask);
    };
  }, [open]);

  const load = () => {
    setDark(window.matchMedia("(prefers-color-scheme: dark)").matches);
    setOpen(true);
  };

  return (
    <div className="flex flex-col gap-4 border-t border-gray-200 dark:border-slate-700 pt-6">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-white">
          <MapPinned className="h-5 w-5 text-blue-600" />
          Mehr Termine in der Region
        </h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Konzerte, Partys, Bühne und mehr im Umkreis von 20 km – live von{" "}
          <a href={ORIGIN} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
            wasgehtapp.de
          </a>
          . Diese Termine sind nicht in Filtern, Karte und Favoriten enthalten.
        </p>
      </div>

      {open ? (
        <iframe
          ref={frameRef}
          src={`${ORIGIN}/iframe.php?${PARAMS}&style=${dark ? "dark" : ""}`}
          title="Veranstaltungen in der Region von wasgehtapp.de"
          onLoad={() => frameRef.current?.contentWindow?.postMessage("FrameHeight", ORIGIN)}
          scrolling="no"
          className="w-full rounded-xl border-0"
          style={{ height }}
        />
      ) : (
        <div className="rounded-xl border border-dashed border-gray-300 dark:border-slate-600 p-5 text-center">
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Beim Laden wird eine Verbindung zu wasgehtapp.de hergestellt und deine IP-Adresse dorthin
            übertragen.{" "}
            <Link href="/datenschutz" className="text-blue-600 hover:underline">
              Mehr dazu
            </Link>
          </p>
          <button
            onClick={load}
            className="mt-3 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
          >
            <ExternalLink className="h-4 w-4" />
            Termine von wasgehtapp.de laden
          </button>
        </div>
      )}
    </div>
  );
}
