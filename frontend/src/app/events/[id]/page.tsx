import { promises as fs } from "fs";
import path from "path";
import { EventDetailClient } from "@/components/EventDetailClient";

// Static export needs the set of [id] pages up front. We read the committed
// snapshot at build time and emit one shell per current event (plus a "_"
// fallback). The body is client-rendered and looks the event up in the snapshot
// it loads, so it stays decoupled from per-event data fetching.
export async function generateStaticParams(): Promise<{ id: string }[]> {
  try {
    const file = path.join(process.cwd(), "public", "data", "events.json");
    const raw = await fs.readFile(file, "utf-8");
    const snap = JSON.parse(raw) as { events?: Array<{ id?: number }> };
    const ids = new Set<string>(["_"]);
    for (const e of snap.events ?? []) {
      if (e?.id != null) ids.add(String(e.id));
    }
    return Array.from(ids).map((id) => ({ id }));
  } catch {
    return [{ id: "_" }];
  }
}

export default function EventDetailPage() {
  return <EventDetailClient />;
}
