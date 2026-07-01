import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "家具出口内部工具",
  description: "报价 · 图纸 · 唛头 · 术语表",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
