// 视觉规范：和应用界面（src/super_aide/ui/web/style.css）同一套颜色、字体、圆角、阴影
export type Lang = "en" | "zh";
export type Mode = "ask" | "act";

export const C = {
  bg: "#07080B",
  text: "#F4F5F7",
  text2: "rgba(244, 245, 247, 0.62)",
  text3: "rgba(244, 245, 247, 0.40)",
  askA: "#5B8CFF",
  askB: "#9B6BFF",
  actA: "#FFB547",
  actB: "#FF7A45",
  ok: "#3CCB7F",
  err: "#FF5D5D",
};

export const accent = (mode: Mode): [string, string] => (mode === "ask" ? [C.askA, C.askB] : [C.actA, C.actB]);

// 应用里的深色界面变量
export const UI = {
  surface: "rgba(30, 30, 32, 0.92)",
  stroke: "rgba(255, 255, 255, 0.09)",
  divider: "rgba(255, 255, 255, 0.07)",
  text: "rgba(255, 255, 255, 0.92)",
  text2: "rgba(255, 255, 255, 0.58)",
  text3: "rgba(255, 255, 255, 0.38)",
  hover: "rgba(255, 255, 255, 0.07)",
  inlineCode: "rgba(255, 255, 255, 0.08)",
  codeBg: "#141518",
  codeText: "#E6E8EC",
  shadow: "0 10px 30px rgba(0, 0, 0, 0.42), 0 1px 3px rgba(0, 0, 0, 0.25)",
};

export const FONT = {
  ui: '"AideCJK", "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", sans-serif',
  mono: 'Consolas, "Cascadia Mono", "Microsoft YaHei UI", monospace',
  display: (lang: Lang) =>
    lang === "zh"
      ? '"Noto Sans SC", "Microsoft YaHei UI", sans-serif'
      : '"Segoe UI Variable Display", "Segoe UI", "Noto Sans SC", sans-serif',
};

// 和应用一样：中文字符和中文标点走雅黑，西文走 Segoe UI Variable
export const GLOBAL_CSS = `
@font-face {
  font-family: "AideCJK";
  font-weight: 100 500;
  src: local("Microsoft YaHei UI"), local("MicrosoftYaHeiUI");
  unicode-range: U+2014, U+2018-2019, U+201C-201D, U+2026, U+3000-303F, U+3400-4DBF, U+4E00-9FFF, U+FF00-FFEF;
}
@font-face {
  font-family: "AideCJK";
  font-weight: 600 900;
  src: local("Microsoft YaHei UI Bold"), local("MicrosoftYaHeiUI-Bold");
  unicode-range: U+2014, U+2018-2019, U+201C-201D, U+2026, U+3000-303F, U+3400-4DBF, U+4E00-9FFF, U+FF00-FFEF;
}
* { box-sizing: border-box; }
body { margin: 0; -webkit-font-smoothing: antialiased; }
`;
