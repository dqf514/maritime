import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "MariOS — Maritime commercial OS",
  description: "MariOS product portal — maritime commercial operating system",
  icons: {
    icon: [
      { url: "/branding/favicon.ico" },
      { url: "/branding/mark.svg", type: "image/svg+xml" },
      { url: "/branding/icon.png", type: "image/png" },
    ],
    apple: "/branding/icon.png",
  },
};

// Density bootstrap — runs before paint to avoid flash
const densityScript = `try{var d=localStorage.getItem('marios_density')||'compact';document.documentElement.dataset.density=d}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: densityScript }} />
      </head>
      <body suppressHydrationWarning>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
