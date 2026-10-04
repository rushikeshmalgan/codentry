import type { Metadata } from "next";
import { Nav } from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Codentry",
  description: "Evidence-first GitHub pull-request analysis with measured, differential static analysis.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <Nav />
          {children}
          <footer className="sitefoot">
            codentry — evidence-first pull request analysis · local demo build
          </footer>
        </div>
      </body>
    </html>
  );
}
