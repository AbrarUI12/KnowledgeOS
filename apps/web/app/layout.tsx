import type { Metadata } from "next";
import { IBM_Plex_Mono, Instrument_Sans, Source_Serif_4 } from "next/font/google";

import { Providers } from "@/components/providers";
import { SkipLink } from "@/components/shell/skip-link";

import "./globals.css";

// Self-hosted at build time by next/font (no runtime requests to Google). Fallback stacks in
// styles/tokens.css keep the app usable if a font fails to load.
const instrumentSans = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-instrument-sans",
  display: "swap",
});
const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  variable: "--font-source-serif",
  display: "swap",
});
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "KnowledgeOS", template: "%s · KnowledgeOS" },
  description: "Permission-aware enterprise knowledge with verifiable citations.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${instrumentSans.variable} ${sourceSerif.variable} ${plexMono.variable}`}
    >
      <body className="min-h-dvh">
        <SkipLink />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
