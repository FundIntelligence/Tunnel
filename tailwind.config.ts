import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: 'class',
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ['IBM Plex Sans', 'var(--font-sans)', 'system-ui', 'sans-serif'],
        body: ['IBM Plex Sans', 'var(--font-sans)', 'system-ui', 'sans-serif'],
        sans: ['IBM Plex Sans', 'var(--font-sans)', 'system-ui', 'sans-serif'],
        mono: ['IBM Plex Mono', 'var(--font-mono)', 'Courier New', 'monospace'],
      },
      colors: {
        base: {
          900: '#0f172a', // Dark Slate
          950: '#020617', // Deep Midnight
        },
        accent: {
          cyan: '#22d3ee', // Cyber Cyan
        },
        teal: {
          DEFAULT: '#14B8A6',
          hover: '#0D9488',
          dark: '#0A7068',
        },
        navy: {
          DEFAULT: '#080C18',
        },
        primary: {
          50: '#f0f9ff',
          100: '#e0f2fe',
          200: '#bae6fd',
          300: '#7dd3fc',
          400: '#38bdf8',
          500: '#0ea5e9',
          600: '#0284c7',
          700: '#0369a1',
          800: '#075985',
          900: '#0c4a6e',
        },
        dark: {
          bg: '#0D0F12',
          card: '#1B1E23',
          cardHover: '#23272E',
        },
      },
      boxShadow: {
        'inner-dark': 'inset 0 2px 4px 0 rgba(0, 0, 0, 0.6)',
        'glow-teal': '0 0 20px rgba(20, 184, 166, 0.5)',
        'glow-cyan': '0 0 20px rgba(34, 211, 238, 0.5)',
      },
      backgroundImage: {
        'gradient-cyan-green': 'linear-gradient(to right, #22d3ee, #4ade80)',
      },
    },
  },
  plugins: [],
};
export default config;


