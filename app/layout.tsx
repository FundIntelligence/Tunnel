import type { Metadata } from "next";
import "./globals.css";
import { plexSans, plexMono } from "./fonts";
import { ThemeProvider } from "next-themes";
import { AuthProvider } from "@/components/AuthProvider";
import ReactQueryProvider from '@/components/ReactQueryProvider'

export const metadata: Metadata = {
  title: "Parity PDS - Deal Analysis",
  description: "Deterministic v1 deal analysis and snapshot export",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning className={`${plexSans.variable} ${plexMono.variable}`}>
      <body className="font-body bg-[var(--bg)] text-[var(--t0)] antialiased">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange={false}
        >
          <ReactQueryProvider>
            <AuthProvider>
              {children}
            </AuthProvider>
          </ReactQueryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}


