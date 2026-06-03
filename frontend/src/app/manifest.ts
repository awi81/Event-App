import type { MetadataRoute } from "next";

// Generated at build into manifest.webmanifest. Next injects the (basePath-aware)
// <link rel="manifest">, but the paths INSIDE the manifest are not prefixed
// automatically, so we add the basePath ourselves.
// Force static generation so the manifest route is emitted as a file under
// `output: export` (it reads an env var, which Next otherwise treats as dynamic).
export const dynamic = "force-static";

const base = process.env.NEXT_PUBLIC_BASE_PATH || "";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Event-App Essen",
    short_name: "Events Essen",
    description: "Events und Aktivitäten in Essen Werden",
    start_url: `${base}/`,
    scope: `${base}/`,
    display: "standalone",
    orientation: "portrait",
    background_color: "#0f172a",
    theme_color: "#2563eb",
    icons: [
      { src: `${base}/icon.svg`, sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: `${base}/apple-icon.png`, sizes: "180x180", type: "image/png" },
    ],
  };
}
