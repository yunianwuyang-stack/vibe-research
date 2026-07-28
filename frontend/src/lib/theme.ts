/** Theme system utilities for the Vibe Research workbench. */

export type ThemePreset = "warm" | "bright" | "bean" | "custom";
export type ThemeColors = { background: string; text: string; accent: string };

const THEME_COLORS: Record<Exclude<ThemePreset, "custom">, ThemeColors> = {
  warm: { background: "#f7f1e6", text: "#342f29", accent: "#9a6b3f" },
  bright: { background: "#f6f8fa", text: "#102b3b", accent: "#00a99d" },
  bean: { background: "#edf4eb", text: "#1e3524", accent: "#2e7d32" },
};

export const safeThemeColor = (value: string, fallback: string) =>
  /^#[0-9a-f]{6}$/i.test(value) ? value : fallback;

export function applyTheme(preset: ThemePreset, custom?: ThemeColors) {
  if (typeof document === "undefined") return;
  const colors =
    preset === "custom"
      ? {
          background: safeThemeColor(custom?.background || "", "#c7e6c9"),
          text: safeThemeColor(custom?.text || "", "#1e3524"),
          accent: safeThemeColor(custom?.accent || "", "#2e7d32"),
        }
      : THEME_COLORS[preset];
  const root = document.documentElement;
  root.dataset.theme = preset;
  root.style.colorScheme = "light";
  root.style.setProperty("--canvas", colors.background);
  root.style.setProperty("--ink", colors.text);
  root.style.setProperty("--teal", colors.accent);
  root.style.setProperty("--teal-dark", colors.accent);
  root.style.setProperty(
    "--surface",
    preset === "bright"
      ? "#ffffff"
      : `color-mix(in srgb, ${colors.background} 30%, white)`,
  );
  root.style.setProperty(
    "--navy",
    preset === "warm" ? "#302a25" : preset === "bright" ? "#071827" : colors.text,
  );
}

export function restoreLocalTheme() {
  if (typeof window === "undefined") return;
  const preset = (window.localStorage.getItem("vibe-theme-preset") || "bright") as ThemePreset;
  let custom: ThemeColors | undefined;
  try {
    custom = JSON.parse(window.localStorage.getItem("vibe-theme-custom") || "null") || undefined;
  } catch {
    custom = undefined;
  }
  applyTheme(
    ["warm", "bright", "bean", "custom"].includes(preset) ? preset : "bright",
    custom,
  );
}
