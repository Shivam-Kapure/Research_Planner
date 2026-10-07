import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Instrument_Sans, Newsreader } from "next/font/google";
import "./globals.css";
import "../styles/chrome.css";
import "../styles/landing.css";
import "../styles/workspace.css";
import "../styles/run.css";
import "../styles/review.css";

// Self-hosted by next/font at build time: no requests to Google from the browser.
const newsreader = Newsreader({
  subsets: ["latin"],
  style: ["normal", "italic"],
  axes: ["opsz"],
  variable: "--font-newsreader",
  display: "swap",
});
const instrument = Instrument_Sans({ subsets: ["latin"], variable: "--font-instrument", display: "swap" });
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "ResearchPilot", template: "%s · ResearchPilot" },
  description:
    "From research question to evidence-backed review: coordinated AI agents plan, search, analyse, synthesise and write a cited literature review.",
};

export const viewport: Viewport = { themeColor: "#f5f2eb" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${newsreader.variable} ${instrument.variable} ${plexMono.variable}`}>
      <body>
        {children}
      </body>
    </html>
  );
}
