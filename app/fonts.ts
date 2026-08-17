import { IBM_Plex_Sans, IBM_Plex_Mono } from 'next/font/google';

// IBM Plex Sans for headings/body
export const plexSans = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['400', '600'],
  variable: '--font-sans',
  display: 'swap',
});

// IBM Plex Mono for values/hashes
export const plexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-mono',
  display: 'swap',
});
