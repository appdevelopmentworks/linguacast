import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "linguacast",
  description: "外国語の一次情報を、日本語の音声で。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
