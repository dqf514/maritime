import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "VoyageOS — Maritime commercial OS",
  description: "VoyageOS product portal — maritime commercial operating system",
  icons: {
    icon: [
      { url: "/branding/favicon.ico" },
      { url: "/branding/mark.svg", type: "image/svg+xml" },
      { url: "/branding/icon.png", type: "image/png" },
    ],
    apple: "/branding/icon.png",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
