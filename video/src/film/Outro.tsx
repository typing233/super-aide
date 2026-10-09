// 结尾：光点、名字、一句话、下载地址
import React from "react";
import { COPY } from "../lib/copy";
import { easeIn, easeOut, pop, ramp } from "../lib/anim";
import { C, FONT, type Lang } from "../lib/theme";
import { T } from "./timeline";

export const Outro: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  if (f < T.outro - 2) return null;
  const copy = COPY[lang];
  const o = T.outro;
  const orb = pop(f, o + 2, 18);
  const ring = ramp(f, o + 4, 34, easeOut);
  const fadeAll = ramp(f, T.end - 16, 16, easeIn);
  const rise = (at: number, d = 16) => {
    const a = ramp(f, at, d);
    return { opacity: a, transform: `translateY(${14 * (1 - a)}px)`, filter: a < 1 ? `blur(${6 * (1 - a)}px)` : undefined };
  };
  const nameSize = lang === "en" ? 112 : 108;
  return (
    <div style={{ position: "absolute", inset: 0, opacity: 1 - fadeAll }}>
      {ring > 0 && ring < 1 ? (
        <div
          style={{
            position: "absolute",
            left: 960 - 520 * ring,
            top: 330 - 520 * ring,
            width: 1040 * ring,
            height: 1040 * ring,
            borderRadius: "50%",
            border: `2px solid color-mix(in srgb, ${C.askB} ${Math.round(60 * (1 - ring))}%, transparent)`,
          }}
        />
      ) : null}
      <div
        style={{
          position: "absolute",
          left: 960 - 46,
          top: 330 - 46,
          width: 92,
          height: 92,
          borderRadius: "50%",
          background: `linear-gradient(135deg, ${C.askA}, ${C.askB})`,
          boxShadow: `0 0 0 16px color-mix(in srgb, ${C.askA} 13%, transparent), 0 0 110px color-mix(in srgb, ${C.askB} 75%, transparent)`,
          transform: `scale(${Math.max(0, orb)})`,
        }}
      />
      <div style={{ position: "absolute", left: 0, right: 0, top: 418, textAlign: "center", fontFamily: FONT.display(lang), fontSize: nameSize, fontWeight: 700, letterSpacing: lang === "en" ? "-0.03em" : "0.04em", color: C.text, lineHeight: 1.1, ...rise(o + 10, 18) }}>
        {copy.outroName}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 548, textAlign: "center", fontFamily: FONT.display(lang === "en" ? "zh" : "en"), fontSize: 30, fontWeight: 500, letterSpacing: "0.08em", color: C.text3, ...rise(o + 20) }}>
        {copy.outroAlt}
      </div>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: 618,
          textAlign: "center",
          fontFamily: FONT.display(lang),
          fontSize: 40,
          fontWeight: 600,
          letterSpacing: lang === "en" ? "-0.015em" : "0.03em",
          ...rise(o + 32),
        }}
      >
        <span style={{ background: `linear-gradient(90deg, ${C.askA}, ${C.askB} 55%, ${C.actB})`, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>{copy.tagline}</span>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 726, display: "flex", justifyContent: "center", gap: 18, fontFamily: FONT.display(lang), fontSize: 24, color: C.text2 }}>
        {copy.facts.map((fact, i) => (
          <React.Fragment key={fact}>
            {i > 0 ? <span style={{ color: C.text3, ...rise(o + 52 + i * 6) }}>·</span> : null}
            <span style={rise(o + 52 + i * 6)}>{fact}</span>
          </React.Fragment>
        ))}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 806, display: "flex", justifyContent: "center", ...rise(o + 76) }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            height: 64,
            padding: "0 30px 0 22px",
            borderRadius: 999,
            background: "rgba(255,255,255,0.06)",
            border: "1px solid rgba(255,255,255,0.14)",
            fontFamily: FONT.display("en"),
            fontSize: 27,
            fontWeight: 500,
            color: C.text,
          }}
        >
          <svg width={26} height={26} viewBox="0 0 24 24" fill="none" stroke={C.askA} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 4v11M7 10.5l5 5 5-5M5 19.5h14" />
          </svg>
          {copy.url}
        </div>
      </div>
    </div>
  );
};
