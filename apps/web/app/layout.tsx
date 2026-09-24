import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Codentry",
  description: "Evidence-first GitHub pull-request analysis with measured, differential static analysis.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
