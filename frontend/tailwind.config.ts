import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    colors: {
      "sf-bg-deep": "#0f0f0f",
      "sf-bg": "#171717",
      "sf-surface": "#1c1c1c",
      "sf-green": "#3ecf8e",
      "sf-green-link": "#00c573",
      "sf-text": "#fafafa",
      "sf-text-secondary": "#b4b4b4",
      "sf-text-muted": "#898989",
      "sf-border": "#242424",
      "sf-border-standard": "#2e2e2e",
      "sf-border-strong": "#363636",
      "sf-amber": "#f59e0b",
      "sf-blue": "#3b82f6",
      "sf-red": "#ef4444",
      "sf-purple": "#a855f7",
      "sf-gray": "#6b7280",
    },
    fontFamily: {
      sans: ["Inter", "system-ui", "sans-serif"],
      mono: ["JetBrains Mono", "Fira Code", "monospace"],
    },
    borderRadius: {
      pill: "9999px",
      card: "8px",
      btn: "6px",
    },
  },
  plugins: [],
} satisfies Config;
