"use client";

import { useEffect, useState } from "react";
import { Snapshot, SNAPSHOT_URL } from "./snapshot";

export type SnapshotState =
  | { status: "loading"; data: null; error: null }
  | { status: "ready"; data: Snapshot; error: null }
  | { status: "error"; data: null; error: string };

// Module-level cache so navigating between pages (/ and /events/[id]) reuses the
// same fetch instead of re-downloading. Reset to null on failure so a remount
// can retry.
let cache: Promise<Snapshot> | null = null;

function loadSnapshot(): Promise<Snapshot> {
  if (!cache) {
    // Cache-bust + no-store so the 2x/day data refresh is picked up promptly
    // and never served stale from a CDN/browser cache.
    const url = `${SNAPSHOT_URL}?t=${Date.now()}`;
    cache = fetch(url, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(`Snapshot HTTP ${res.status}`);
        return res.json() as Promise<Snapshot>;
      })
      .catch((err) => {
        cache = null; // allow a later retry
        throw err;
      });
  }
  return cache;
}

export function useSnapshot(): SnapshotState {
  const [state, setState] = useState<SnapshotState>({ status: "loading", data: null, error: null });

  useEffect(() => {
    let cancelled = false;
    loadSnapshot().then(
      (data) => {
        if (!cancelled) setState({ status: "ready", data, error: null });
      },
      (err) => {
        if (!cancelled) setState({ status: "error", data: null, error: String(err?.message || err) });
      }
    );
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
