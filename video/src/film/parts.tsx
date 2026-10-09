// 片子的公共部件：背景、标题、装着桌面的"屏幕"、按键、章节大字
import React from "react";
import { clamp, colorTrack, easeIn, easeOut, lerp, ramp } from "../lib/anim";
import { accent, C, FONT, type Lang, type Mode } from "../lib/theme";
import { deskCamera, DesktopShow } from "../desktop/DesktopShow";
import { CH } from "./timeline";

// ---------- 背景：深色底 + 两团随章节换色的光 ----------

const NOISE =
  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' seed='7'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.55 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>\")";

export const Backdrop: React.FC<{ f: number }> = ({ f }) => {
  const a = colorTrack(f, [
    [0, C.askA],
    [CH.act, C.askA],
    [CH.act + 30, C.actA],
    [CH.guide, C.actA],
    [CH.guide + 30, C.askA],
  ]);
  const b = colorTrack(f, [
    [0, C.askB],
    [CH.act, C.askB],
    [CH.act + 30, C.actB],
    [CH.guide, C.actB],
    [CH.guide + 30, C.askB],
    [CH.route, C.askB],
    [CH.route + 30, C.actB],
    [CH.exp, C.actB],
    [CH.exp + 30, C.askB],
    [CH.community, C.askB],
    [CH.community + 30, C.actB],
    [CH.recap, C.actB],
    [CH.recap + 30, C.askB],
  ]);
  const lift = (start: number, end: number) => ramp(f, start - 6, 20) * (1 - ramp(f, end - 20, 30));
  const boost = 0.72 + 0.28 * Math.max(lift(CH.reveal, CH.see), lift(CH.better, CH.route), ramp(f, CH.recap + 200, 30));
  const drift = Math.sin(f / 95) * 40;
  return (
    <div style={{ position: "absolute", inset: 0, background: C.bg, overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          opacity: boost,
          background: [
            `radial-gradient(900px 640px at ${22 + drift / 40}% ${14 + drift / 60}%, color-mix(in srgb, ${a} 34%, transparent), transparent 70%)`,
            `radial-gradient(1000px 720px at ${84 - drift / 50}% 92%, color-mix(in srgb, ${b} 30%, transparent), transparent 70%)`,
          ].join(","),
        }}
      />
      <div style={{ position: "absolute", inset: 0, backgroundImage: NOISE, opacity: 0.05, mixBlendMode: "overlay" }} />
      <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse at 50% 45%, transparent 55%, rgba(0,0,0,0.55) 100%)" }} />
    </div>
  );
};

// ---------- 标题：逐词（中文逐字）浮现；可以先在中间大字出现，再缩到顶上 ----------

type Token = { t: string; em: boolean };

function tokenize(text: string, lang: Lang): Token[] {
  const out: Token[] = [];
  text.split("*").forEach((seg, i) => {
    const em = i % 2 === 1;
    const parts = lang === "zh" ? seg.match(/[A-Za-z0-9+.'\-]+\s*|\s+|[^\sA-Za-z0-9]/g) : seg.match(/\S+\s*|\s+/g);
    for (const p of parts || []) {
      // 中文标点并到前一个字上，不单独出现在行首
      if (lang === "zh" && /^[，。、？！：；”’）》…]+$/.test(p) && out.length) out[out.length - 1].t += p;
      else out.push({ t: p, em });
    }
  });
  return out;
}

export const BIG = (lang: Lang) => (lang === "en" ? 84 : 78);
export const DOCK_SCALE = 0.6;
export const DOCK_TOP = 52;

export const Headline: React.FC<{
  f: number;
  lang: Lang;
  text: string;
  sub?: string;
  start: number;
  end: number;
  dockAt?: number;
  centerY?: number;
  tone?: Mode | "duo";
  scale?: number;
}> = ({ f, lang, text, sub, start, end, dockAt, centerY = 560, tone = "ask", scale: fixedScale }) => {
  if (f < start || f > end + 12) return null;
  const size = BIG(lang);
  const lineH = size * 1.16;
  const docked = dockAt === undefined ? 1 : ramp(f, dockAt, 26, easeOut);
  const scale = fixedScale ?? lerp(1, DOCK_SCALE, docked);
  const top = lerp(centerY - lineH / 2, DOCK_TOP, docked);
  const out = ramp(f, end, 10, easeIn);
  const tokens = tokenize(text, lang);
  const [a, b] = tone === "duo" ? [C.askA, C.actB] : accent(tone);
  const ems = tokens.filter((t) => t.em).length;
  let emIndex = 0;
  const stagger = lang === "en" ? 3 : 1.6;
  const subStart = (dockAt ?? start) + (dockAt === undefined ? 12 : 18);
  const subA = ramp(f, subStart, 16);
  const mix = (k: number) => `color-mix(in srgb, ${b} ${Math.round(clamp(k, 0, 1) * 100)}%, ${a})`;
  return (
    <div style={{ position: "absolute", inset: 0, opacity: 1 - out, filter: out > 0 ? `blur(${8 * out}px)` : undefined, transform: `translateY(${-14 * out}px)` }}>
      <div
        style={{
          position: "absolute",
          left: "50%",
          top,
          transform: `translateX(-50%) scale(${scale})`,
          transformOrigin: "50% 0",
          whiteSpace: "nowrap",
          fontFamily: FONT.display(lang),
          fontSize: size,
          lineHeight: `${lineH}px`,
          fontWeight: 700,
          letterSpacing: lang === "en" ? "-0.025em" : "0.01em",
          color: C.text,
        }}
      >
        {tokens.map((tok, i) => {
          const t = ramp(f, start + i * stagger, 18, easeOut);
          let style: React.CSSProperties = {};
          if (tok.em) {
            const k0 = ems > 1 ? emIndex / ems : 0;
            const k1 = ems > 1 ? (emIndex + 1) / ems : 1;
            emIndex++;
            style = { background: `linear-gradient(90deg, ${mix(k0)}, ${mix(k1)})`, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" };
          }
          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                whiteSpace: "pre",
                opacity: t,
                transform: `translateY(${(1 - t) * 0.38}em)`,
                filter: t < 1 ? `blur(${(1 - t) * 10}px)` : undefined,
                ...style,
              }}
            >
              {tok.t}
            </span>
          );
        })}
      </div>
      {sub ? (
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: DOCK_TOP + lineH * DOCK_SCALE + 10,
            textAlign: "center",
            fontFamily: FONT.display(lang),
            fontSize: lang === "en" ? 27 : 26,
            fontWeight: 400,
            letterSpacing: lang === "en" ? "-0.005em" : "0.02em",
            color: C.text2,
            opacity: subA,
            transform: `translateY(${8 * (1 - subA)}px)`,
            whiteSpace: "nowrap",
          }}
        >
          {sub}
        </div>
      ) : null}
    </div>
  );
};

/** 章节大字：画面正中两行（大标题 + 一句副标题） */
export const TitleCard: React.FC<{ f: number; lang: Lang; text: string; sub: string; start: number; end: number; tone?: Mode | "duo" }> = ({ f, lang, text, sub, start, end, tone = "duo" }) => {
  if (f < start || f > end + 12) return null;
  const out = ramp(f, end, 10, easeIn);
  const subA = ramp(f, start + 26, 18);
  return (
    <>
      <Headline f={f} lang={lang} text={text} start={start} end={end} dockAt={99999} centerY={500} tone={tone} scale={1.15} />
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: 600,
          textAlign: "center",
          fontFamily: FONT.display(lang),
          fontSize: lang === "en" ? 40 : 38,
          fontWeight: 500,
          color: C.text2,
          opacity: subA * (1 - out),
          transform: `translateY(${10 * (1 - subA) - 14 * out}px)`,
          filter: out > 0 ? `blur(${8 * out}px)` : undefined,
        }}
      >
        {sub}
      </div>
    </>
  );
};

// ---------- 装着桌面的"屏幕"：升上来、里面的镜头推拉、最后沉下去 ----------

export const CARD = { x: 199, y: 196, w: 1522, h: 856 };

export const DesktopViewport: React.FC<{ f: number; lang: Lang; w: number; h: number; cam?: { fx: number; fy: number; z: number } }> = ({ f, lang, w, h, cam }) => {
  const c = cam ?? deskCamera(f);
  const s = (w / 1920) * c.z;
  const tx = clamp(w / 2 - c.fx * s, w - 1920 * s, 0);
  const ty = clamp(h / 2 - c.fy * s, h - 1080 * s, 0);
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <div style={{ position: "absolute", left: 0, top: 0, transformOrigin: "0 0", transform: `translate(${tx}px, ${ty}px) scale(${s})` }}>
        <DesktopShow f={f} lang={lang} />
      </div>
    </div>
  );
};

/** spans：屏幕出现的时间段 [升起, 沉下]；升起帧小于 0 表示一开始就在 */
export const ScreenCard: React.FC<{ f: number; lang: Lang; spans: [number, number][] }> = ({ f, lang, spans }) => {
  const span = spans.find(([enter, exit]) => f >= enter && f <= exit + 30);
  if (!span) return null;
  const [enter, exit] = span;
  const p = ramp(f, enter, 34, easeOut);
  const e = ramp(f, exit, 26, easeIn);
  return (
    <div style={{ position: "absolute", inset: 0, perspective: 2200 }}>
      <div
        style={{
          position: "absolute",
          left: CARD.x,
          top: CARD.y,
          width: CARD.w,
          height: CARD.h,
          borderRadius: 18,
          overflow: "hidden",
          boxShadow: "0 40px 120px rgba(0,0,0,0.65), 0 0 0 1px rgba(255,255,255,0.10)",
          transformOrigin: "50% 100%",
          transform: `translateY(${(1 - p) * 760 + e * 120}px) rotateX(${(1 - p) * 16}deg) scale(${1 - 0.08 * e})`,
          opacity: Math.min(1, p * 2.5) * (1 - e),
          filter: e > 0 ? `blur(${10 * e}px)` : undefined,
        }}
      >
        <DesktopViewport f={f} lang={lang} w={CARD.w} h={CARD.h} />
        <div style={{ position: "absolute", inset: 0, borderRadius: 18, boxShadow: "inset 0 1px 0 rgba(255,255,255,0.08)", pointerEvents: "none" }} />
      </div>
    </div>
  );
};

// ---------- 按键：Alt + Q / Alt + W ----------

export const Keycaps: React.FC<{ f: number; keys: string[]; at: number; press: number; mode: Mode; y?: number; scale?: number }> = ({
  f,
  keys,
  at,
  press,
  mode,
  y = 900,
  scale = 1,
}) => {
  const leave = press + 26;
  if (f < at || f > leave + 12) return null;
  const a = ramp(f, at, 8);
  const out = ramp(f, leave, 10, easeIn);
  const [ca, cb] = accent(mode);
  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: y,
        display: "flex",
        alignItems: "center",
        gap: 18,
        transform: `translateX(-50%) translateY(${10 * (1 - a) + 10 * out}px) scale(${scale * (0.92 + 0.08 * a)})`,
        opacity: a * (1 - out),
        fontFamily: FONT.display("en"),
      }}
    >
      {keys.map((k, i) => {
        const down = f >= press + i * 5 && f < press + 16;
        const glow = f >= press + i * 5 ? Math.max(0, 1 - (f - press - i * 5) / 24) : 0;
        return (
          <React.Fragment key={k}>
            {i > 0 ? <span style={{ fontSize: 34, color: C.text3 }}>+</span> : null}
            <div
              style={{
                height: 96,
                minWidth: 96,
                padding: "0 30px",
                borderRadius: 20,
                display: "grid",
                placeItems: "center",
                fontSize: 36,
                fontWeight: 600,
                color: "#EEF0F4",
                background: "linear-gradient(180deg, #2C2D34, #1D1E23)",
                border: "1px solid rgba(255,255,255,0.13)",
                transform: `translateY(${down ? 6 : 0}px)`,
                boxShadow: [
                  down ? "0 1px 0 #0D0E11" : "0 7px 0 #0D0E11",
                  "0 16px 34px rgba(0,0,0,0.5)",
                  `0 0 0 ${2 * glow}px ${ca}`,
                  `0 0 ${40 * glow}px color-mix(in srgb, ${cb} 70%, transparent)`,
                ].join(","),
              }}
            >
              {k}
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
};

/** 画面里的玻璃面板（深色、细边、柔和阴影），各章的示意图都用它 */
export const panel = (extra: React.CSSProperties = {}): React.CSSProperties => ({
  position: "absolute",
  borderRadius: 18,
  background: "rgba(24, 25, 30, 0.92)",
  border: "1px solid rgba(255,255,255,0.09)",
  boxShadow: "0 24px 70px rgba(0,0,0,0.5)",
  color: "rgba(255,255,255,0.92)",
  fontFamily: FONT.ui,
  ...extra,
});
