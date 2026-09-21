import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Luna Realms · 개발 준비",
  description: "AI TRPG 프로젝트 개발 환경",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="ko"><body>{children}</body></html>;
}
