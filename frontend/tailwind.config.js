/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ast: {
          bg: "#020617",
          navy: "#020617",
          blue: "#3b82f6",
          "dark-blue": "#1d4ed8",
          tint: "#0b1220",
          card: "#020617",
          "card-elevated": "#020617",
          "border-subtle": "rgba(148, 163, 184, 0.25)",
          "border-strong": "rgba(148, 163, 184, 0.45)",
          "text-muted": "#9ca3af",
          "text-soft": "#6b7280",
        },
      },
      fontFamily: {
        sans: [
          "Segoe UI",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
