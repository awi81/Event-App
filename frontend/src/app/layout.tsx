import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Event-App Essen - Events und Aktivitäten",
  description: "Entdecke Events und Aktivitäten in Essen Werden - Heute, Morgen und am Wochenende",
  // The manifest <link> is injected automatically from app/manifest.ts (basePath-aware).
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Events Essen",
  },
};

export const viewport: Viewport = {
  themeColor: "#2563eb",
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="de">
      <body className="antialiased">{children}</body>
    </html>
  );
}
