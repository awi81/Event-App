// Canonical category taxonomy — mirrors CATEGORY_RULES in
// backend/app/services/classifier.py. Order = chip order in the filter bar.
export const CATEGORY_ORDER: string[] = [
  "Familie & Kinder",
  "Theater & Bühne",
  "Comedy & Kabarett",
  "Musik & Konzerte",
  "Film & Kino",
  "Literatur & Vorträge",
  "Museum & Ausstellung",
  "Führungen & Touren",
  "Feste & Festivals",
  "Märkte & Messen",
  "Food & Street-Food",
  "Workshops & Mitmachen",
  "Freizeitorte & Attraktionen",
];

export const CATEGORY_COLORS: Record<string, string> = {
  "Familie & Kinder": "#22c55e", // green
  "Theater & Bühne": "#a855f7", // purple
  "Comedy & Kabarett": "#d946ef", // fuchsia
  "Musik & Konzerte": "#6366f1", // indigo
  "Film & Kino": "#0ea5e9", // sky
  "Literatur & Vorträge": "#78716c", // stone
  "Museum & Ausstellung": "#3b82f6", // blue
  "Führungen & Touren": "#14b8a6", // teal
  "Feste & Festivals": "#ec4899", // pink
  "Märkte & Messen": "#eab308", // yellow
  "Food & Street-Food": "#ef4444", // red
  "Workshops & Mitmachen": "#8b5cf6", // violet
  "Freizeitorte & Attraktionen": "#f97316", // orange
};

export const DEFAULT_CATEGORY_COLOR = "#6b7280"; // gray

/** Sort categories in taxonomy order; unknown labels go last, alphabetically. */
export function sortCategories(cats: Iterable<string>): string[] {
  const rank = new Map(CATEGORY_ORDER.map((c, i) => [c, i]));
  return Array.from(cats).sort((a, b) => {
    const ra = rank.get(a) ?? CATEGORY_ORDER.length;
    const rb = rank.get(b) ?? CATEGORY_ORDER.length;
    return ra !== rb ? ra - rb : a.localeCompare(b, "de");
  });
}
