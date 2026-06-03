export function EventCardSkeleton() {
  return (
    <div className="animate-pulse rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 shadow-sm">
      {/* Date skeleton */}
      <div className="flex items-center gap-2 mb-3">
        <div className="h-4 w-4 bg-gray-200 dark:bg-slate-700 rounded" />
        <div className="h-4 w-24 bg-gray-200 dark:bg-slate-700 rounded" />
      </div>

      {/* Title skeleton */}
      <div className="h-5 w-3/4 bg-gray-200 dark:bg-slate-700 rounded mb-2" />
      <div className="h-5 w-1/2 bg-gray-200 dark:bg-slate-700 rounded mb-3" />

      {/* Venue skeleton */}
      <div className="flex items-center gap-2 mb-2">
        <div className="h-4 w-4 bg-gray-200 dark:bg-slate-700 rounded" />
        <div className="h-4 w-32 bg-gray-200 dark:bg-slate-700 rounded" />
      </div>

      {/* Description skeleton */}
      <div className="h-4 w-full bg-gray-200 dark:bg-slate-700 rounded mb-1" />
      <div className="h-4 w-2/3 bg-gray-200 dark:bg-slate-700 rounded mb-3" />

      {/* Badges skeleton */}
      <div className="flex gap-2">
        <div className="h-6 w-20 bg-gray-200 dark:bg-slate-700 rounded-full" />
        <div className="h-6 w-24 bg-gray-200 dark:bg-slate-700 rounded-full" />
      </div>
    </div>
  );
}

export function EventsListSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <EventCardSkeleton key={i} />
      ))}
    </div>
  );
}
