import type { Metadata } from "next";
import { Inter, Source_Serif_4 } from "next/font/google";
import NavBar from "@/components/NavBar";
import "./globals.css";

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
  title: "The Follow Up",
  description: "Calm, factual follow-up on public promises",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-4178327340523784" crossorigin="anonymous"></script>
      </head>
      <body className={`${inter.variable} ${sourceSerif.variable} font-sans bg-background text-foreground antialiased`}>
        <NavBar />
        <div className="pt-12">{children}</div>
      </body>
    </html>
  );
}
