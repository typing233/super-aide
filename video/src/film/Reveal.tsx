// ② 名字和一句话定位：看完开场的那一问，告诉观众这是什么
import React from "react";
import { COPY } from "../lib/copy";
import { easeIn, easeOut, pop, ramp } from "../lib/anim";
import { C, FONT, type Lang } from "../lib/theme";
import { CH } from "./timeline";

const Crossed: React.FC<{ kind: number }> = ({ kind }) => (
  <svg width={26} height={26} viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
    {kind === 0 ? (
      <>
        <rect x="7" y="7" width="11" height="13" rx="2" />
        <path d="M5 16V5.5A1.5 1.5 0 0 1 6.5 4H14" />
      </>
    ) : null}
    {kind === 1 ? (
      <>
        <rect x="3.5" y="6" width="17" height="13" rx="2.5" />
        <circle cx="12" cy="12.5" r="3.2" />
        <path d="M9 6l1.3-2h3.4L15 6" />
      </>
    ) : null}
    {kind === 2 ? <path d="M5 6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v7a2.5 2.5 0 0 1-2.5 2.5H11l-4 3.5V16h-.5A2.5 2.5 0 0 1 4 13.5z" /> : null}
    <path d="M4 20L20 4" stroke={C.err} strokeWidth={2} />
  </svg>
);

export const Reveal: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const s = CH.reveal;
  if (f < s || f > CH.see + 4) return null;
  const copy = COPY[lang];
  const out = ramp(f, CH.see - 18, 16, easeIn);
  const orb = pop(f, s + 2, 18); // 光点和冲击波落在小节线上，和配乐的重音对齐
  const ring = ramp(f, s + 4, 34, easeOut);
  const rise = (at: number, d = 16) => {
    const a = ramp(f, at, d);
    return { opacity: a, transform: `translateY(${14 * (1 - a)}px)`, filter: a < 1 ? `blur(${6 * (1 - a)}px)` : undefined };
  };
  return (
    <div style={{ position: "absolute", inset: 0, opacity: 1 - out, filter: out > 0 ? `blur(${8 * out}px)` : undefined }}>
      {ring > 0 && ring < 1 ? (
        <div
          style={{
            position: "absolute",
            left: 960 - 560 * ring,
            top: 300 - 560 * ring,
            width: 1120 * ring,
            height: 1120 * ring,
            borderRadius: "50%",
            border: `2px solid color-mix(in srgb, ${C.askB} ${Math.round(60 * (1 - ring))}%, transparent)`,
          }}
        />
      ) : null}
      <div
        style={{
          position: "absolute",
          left: 960 - 40,
          top: 300 - 40,
          width: 80,
          height: 80,
          borderRadius: "50%",
          background: `linear-gradient(135deg, ${C.askA}, ${C.askB})`,
          boxShadow: `0 0 0 14px color-mix(in srgb, ${C.askA} 13%, transparent), 0 0 100px color-mix(in srgb, ${C.askB} 75%, transparent)`,
          transform: `scale(${Math.max(0, orb)})`,
        }}
      />
      <div style={{ position: "absolute", left: 0, right: 0, top: 376, textAlign: "center", fontFamily: FONT.display(lang), fontSize: lang === "en" ? 120 : 112, fontWeight: 700, letterSpacing: lang === "en" ? "-0.035em" : "0.04em", color: C.text, lineHeight: 1.1, ...rise(s + 12, 18) }}>
        {copy.name}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 516, textAlign: "center", fontFamily: FONT.display(lang === "en" ? "zh" : "en"), fontSize: 30, fontWeight: 500, letterSpacing: "0.08em", color: C.text3, ...rise(s + 24) }}>
        {copy.altName}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 588, textAlign: "center", fontFamily: FONT.display(lang), fontSize: lang === "en" ? 46 : 44, fontWeight: 600, letterSpacing: lang === "en" ? "-0.015em" : "0.03em", ...rise(s + 40) }}>
        <span style={{ background: `linear-gradient(90deg, ${C.askA}, ${C.askB} 60%, ${C.actB})`, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>{copy.revealLine}</span>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 710, display: "flex", justifyContent: "center", gap: 20 }}>
        {copy.revealNo.map((t, i) => (
          <div
            key={t}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              height: 60,
              padding: "0 26px 0 18px",
              borderRadius: 999,
              background: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.10)",
              fontFamily: FONT.display(lang),
              fontSize: 25,
              color: C.text2,
              ...rise(s + 76 + i * 12),
            }}
          >
            <Crossed kind={i} />
            {t}
          </div>
        ))}
      </div>
    </div>
  );
};
