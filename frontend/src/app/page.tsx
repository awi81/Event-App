import { Suspense } from "react";
import Link from "next/link";
import { HomeClient } from "@/components/HomeClient";
import { EventsListSkeleton } from "@/components/EventCardSkeleton";

export default function Home() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <header className="bg-white dark:bg-slate-800 shadow-sm border-b border-gray-100 dark:border-slate-700">
        <div className="mx-auto max-w-7xl px-4 py-5 sm:px-6 lg:px-8">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white tracking-tight">
            Event-App <span className="text-blue-600">Essen</span>
          </h1>
          <p className="mt-1.5 text-base text-gray-500 dark:text-gray-400">
            Entdecke Events und Aktivitäten in Essen Werden
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8 space-y-6">
        {/* Suspense is mandatory: EventsList uses useSearchParams(), which a
            static export refuses to build outside a Suspense boundary. */}
        <Suspense fallback={<EventsListSkeleton />}>
          <HomeClient />
        </Suspense>
      </main>

      <footer className="mt-auto border-t border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-800 py-6">
        <div className="mx-auto max-w-7xl px-4 text-center text-sm text-gray-500 dark:text-gray-400">
          <p>
            Event-App Essen • 19 Quellen aus Essen und Umgebung
            {process.env.NEXT_PUBLIC_STATIC_BUILD !== "true" && (
              <>
                {" • "}
                <Link href="/admin" className="text-blue-600 hover:underline">
                  Admin
                </Link>
              </>
            )}
            {" • "}
            <Link href="/datenschutz" className="text-blue-600 hover:underline">
              Datenschutz
            </Link>
          </p>
        </div>
      </footer>
    </div>
  );
}
