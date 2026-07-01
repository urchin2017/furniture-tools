import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      // 主题 token 接缝：等 Claude Design 交付后，改这里的 CSS 变量即可整套换皮
      colors: {
        bg: "var(--bg)",
        surface: "var(--surface)",
        border: "var(--border)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        brand: "var(--brand)",
        "brand-ink": "var(--brand-ink)",
        accent: "var(--accent)",
      },
    },
  },
  plugins: [],
};
export default config;
