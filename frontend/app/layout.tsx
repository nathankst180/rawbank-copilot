import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Rawbank Sentient Fraud Investigation Copilot',
  description: 'Evidence-grounded fraud investigation over a synthetic banking dataset. Use Case 02.',
  robots: 'noindex, nofollow',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
