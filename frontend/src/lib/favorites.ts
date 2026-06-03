"use client";

import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "event-favorites";
const EVENT_NAME = "event-favorites-changed";

function readFavorites(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : [];
  } catch {
    return [];
  }
}

function writeFavorites(ids: string[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  window.dispatchEvent(new CustomEvent(EVENT_NAME));
}

// Cache the snapshot reference so getSnapshot is stable until favorites change.
let cachedSnapshot: string[] = [];
let cachedKey = "";

function getSnapshot(): string[] {
  const current = readFavorites();
  const key = current.join("|");
  if (key !== cachedKey) {
    cachedKey = key;
    cachedSnapshot = current;
  }
  return cachedSnapshot;
}

// Stable reference required by useSyncExternalStore — returning a fresh []
// each call would trigger React's "infinite loop" guard.
const SERVER_SNAPSHOT: string[] = [];

function getServerSnapshot(): string[] {
  return SERVER_SNAPSHOT;
}

function subscribe(callback: () => void): () => void {
  window.addEventListener(EVENT_NAME, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(EVENT_NAME, callback);
    window.removeEventListener("storage", callback);
  };
}

export function useFavorites() {
  const favorites = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const isFavorite = useCallback((id: string) => favorites.includes(id), [favorites]);

  const toggle = useCallback((id: string) => {
    const current = readFavorites();
    const next = current.includes(id) ? current.filter((x) => x !== id) : [...current, id];
    writeFavorites(next);
  }, []);

  return { favorites, isFavorite, toggle };
}
