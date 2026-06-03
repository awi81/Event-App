import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export const metadata = {
  title: "Seite nicht gefunden – Event-App Essen",
};

export default function NotFound() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900 flex flex-col">
      <header className="bg-white dark:bg-slate-800 shadow-sm border-b border-gray-100 dark:border-slate-700">
        <div className="mx-auto max-w-3xl px-4 py-4 sm:px-6">
          <Link
            href="/"
            className="inline-flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 hover:text-blue-600 transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Zur Startseite
          </Link>
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-12">
        <div className="text-center">
          <p className="text-6xl font-bold text-blue-600">404</p>
          <h1 className="mt-4 text-2xl font-semibold text-gray-900 dark:text-white">
            Seite nicht gefunden
          </h1>
          <p className="mt-2 text-gray-500 dark:text-gray-400">
            Das Event oder diese Seite existiert nicht mehr.
          </p>
          <Link
            href="/"
            className="mt-6 inline-block rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
          >
            Zurück zur Übersicht
          </Link>
        </div>
      </main>
    </div>
  );
}
