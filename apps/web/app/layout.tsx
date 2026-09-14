import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Codentry",
  description: "AI-powered GitHub code review assistant — Phase 1 foundation.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
