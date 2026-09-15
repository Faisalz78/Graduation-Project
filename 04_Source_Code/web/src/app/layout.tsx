import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "واصل | تدقيق الفواتير والمشاريع", template: "%s | واصل" },
  description: "منصة واصل للتدقيق الذكي في الفواتير ومصاريف المشاريع.",
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ar" dir="rtl">
      <body>{children}</body>
    </html>
  );
}
