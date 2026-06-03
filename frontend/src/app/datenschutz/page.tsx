import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";

export const metadata = {
  title: "Datenschutz - Event-App Essen",
  description: "Hinweise zu Drittanbietern und Datenverarbeitung der Event-App Essen",
};

export default function DatenschutzPage() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-slate-900">
      <header className="bg-white dark:bg-slate-800 shadow-sm border-b border-gray-100 dark:border-slate-700">
        <div className="mx-auto max-w-3xl px-4 py-4 sm:px-6">
          <Link
            href="/"
            className="inline-flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 hover:text-blue-600 transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Zurück zur Übersicht
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6 sm:px-6">
        <article className="rounded-xl bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 shadow-sm p-6 space-y-6">
          <header>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Datenschutz und Transparenz</h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Diese App ist eine private Single-User-Anwendung. Es findet keine Nutzerregistrierung,
              kein Tracking und keine Übertragung personenbezogener Daten an Dritte statt.
            </p>
          </header>

          <Section title="Verantwortlich">
            <p>Privater Betrieb. Kontakt: awidev22@gmail.com</p>
          </Section>

          <Section title="Verarbeitete Daten">
            <ul className="list-disc list-inside space-y-1">
              <li>
                <strong>Eventdaten</strong> – Titel, Zeit, Ort, Kurzbeschreibung, Link auf die Original-Quelle.
                Keine vollständigen Artikel oder Bilder werden gespeichert.
              </li>
              <li>
                <strong>Favoriten</strong> – ausschließlich lokal im <code>localStorage</code> deines Browsers.
                Keine Übertragung an einen Server.
              </li>
              <li>
                <strong>Filter- und Sortier-Einstellungen</strong> – in der URL-Query, nicht persistent gespeichert.
              </li>
            </ul>
          </Section>

          <Section title="Drittanbieter (Auftragsverarbeitung / Drittland)">
            <p>
              Beim Betrieb der App werden externe Dienste angefragt. Die App selbst sendet keine
              persönlichen Daten an diese Dienste; die Anfragen enthalten lediglich Adressen, Datumsangaben
              oder Koordinaten zu Events.
            </p>
            <ul className="space-y-3 mt-3">
              <ListItem
                name="Open-Meteo"
                purpose="Wetterprognose für Essen (Standortkoordinaten, Datum)"
                country="Bregenz, Österreich (EU)"
                url="https://open-meteo.com/en/privacy"
              />
              <ListItem
                name="OpenStreetMap (Nominatim)"
                purpose="Geocoding von Veranstaltungsorten (Adresse oder Venue-Name)"
                country="Großbritannien (UK GDPR / DSGVO-äquivalent)"
                url="https://wiki.osmfoundation.org/wiki/Privacy_Policy"
              />
              <ListItem
                name="OpenStreetMap Tile Server"
                purpose="Kartenkacheln für die Leaflet-Karte"
                country="OSM Foundation (UK)"
                url="https://wiki.osmfoundation.org/wiki/Privacy_Policy"
              />
              <ListItem
                name="Event-Quellen (Crawler)"
                purpose="Abruf öffentlicher Veranstaltungslisten - keine Übergabe von Nutzerdaten"
                country="Hauptsächlich Deutschland"
              />
            </ul>
          </Section>

          <Section title="Keine Tracker, kein Google">
            <p>
              Diese App verwendet keine Google Fonts (lokale Systemschriften), keine Tracker, keine Analytics,
              keine Werbe-SDKs und keine Cookies. Schriftarten werden aus dem Betriebssystem geladen.
            </p>
          </Section>

          <Section title="Crawling und Quellen-Compliance">
            <p>
              Die App ruft Daten ausschließlich aus öffentlich erreichbaren Quellen ab. Robots.txt-Hinweise
              und Nutzungsbedingungen wurden vor Aufnahme jeder Quelle manuell geprüft. Es werden nur
              Metadaten (Titel, Zeit, Ort, Kurzbeschreibung) übernommen; Volltexte oder Bilder werden
              nicht dauerhaft gespeichert. Jede Event-Karte enthält einen direkten Link auf die
              Original-Quelle. Bei Nominatim wird der nach Usage Policy geforderte User-Agent mit
              Kontakt gesendet (
              <code>Event-App-Essen/1.0 (+Kontakt)</code>
              ).
            </p>
          </Section>

          <Section title="Speicherdauer">
            <p>
              Events werden in einer lokalen PostgreSQL-Datenbank gespeichert und nach Ablauf des
              Veranstaltungsdatums automatisch archiviert (markiert). Geocoding-Cache wird 180 Tage
              positiv / 14 Tage negativ vorgehalten. Wetterdaten 24 Stunden (heute 3h).
            </p>
          </Section>
        </article>
      </main>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white">{title}</h2>
      <div className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">{children}</div>
    </section>
  );
}

function ListItem({
  name,
  purpose,
  country,
  url,
}: {
  name: string;
  purpose: string;
  country: string;
  url?: string;
}) {
  return (
    <li className="rounded-lg bg-gray-50 dark:bg-slate-900/50 p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-gray-900 dark:text-white">{name}</span>
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline inline-flex items-center gap-1 text-xs"
          >
            <ExternalLink className="h-3 w-3" />
            Policy
          </a>
        )}
      </div>
      <p className="text-gray-600 dark:text-gray-400 mt-1">{purpose}</p>
      <p className="text-xs text-gray-500 dark:text-gray-500 mt-1">Sitz: {country}</p>
    </li>
  );
}
