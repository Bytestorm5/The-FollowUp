import type { Metadata } from "next";
import { Inter, Source_Serif_4 } from "next/font/google";
import NavBar from "@/components/NavBar";
import Script from "next/script";
import "./globals.css";
import { getSiteUrl } from "@/lib/seo";

/* Fonts: Inter (sans) for UI/body, Source Serif for headlines */
const inter = Inter({
  variable: "--font-sans",
  subsets: ["latin"],
  display: "swap",
});

const sourceSerif = Source_Serif_4({
  variable: "--font-serif",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(getSiteUrl()),
  title: {
    default: "The Follow Up",
    template: "%s · The Follow Up",
  },
  description: "Calm, factual follow-up on public promises",
  applicationName: "The Follow Up",
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    siteName: "The Follow Up",
    title: "The Follow Up",
    description: "Calm, factual follow-up on public promises",
    url: "/",
  },
  twitter: {
    card: "summary_large_image",
    site: "@",
    creator: "@",
  },
  robots: {
    index: true,
    follow: true,
  },
  themeColor: "#ffffff",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <Script
          src="https://www.googletagmanager.com/gtag/js?id=G-JMWHH2LNGZ"
          strategy="afterInteractive"
        />
        <Script id="gtag-init" strategy="afterInteractive">{`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          gtag('js', new Date());

          gtag('config', 'G-JMWHH2LNGZ');
        `}</Script>

        <Script
          src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-4178327340523784"
          crossOrigin="anonymous"
          strategy="afterInteractive"
        />
      </head>
      <body className={`${inter.variable} ${sourceSerif.variable} font-sans bg-background text-foreground antialiased`}>
        <NavBar />
        <div className="pt-16">{children}</div>
      </body>
    </html>
  );
}
