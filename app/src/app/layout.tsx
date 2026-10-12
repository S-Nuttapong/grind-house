import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { FitQueryProvider } from "@/features/shell/fit-query-provider";
import { SiteHeader } from "@/features/shell/site-header";
import { ThemeProvider } from "@/features/shell/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

import "./globals.css";

const inter = Inter({ variable: "--font-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Job Hunt",
  description: "Personal job board: search, shortlist, and track applications.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`} suppressHydrationWarning>
      <body className="flex min-h-full flex-col">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <TooltipProvider delayDuration={300}>
            <FitQueryProvider>
              <SiteHeader />
              <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 lg:px-6">{children}</main>
              <Toaster position="bottom-right" />
            </FitQueryProvider>
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
