// 开场：想让 AI 帮忙，得先复制、截图、解释……然后这些都缩进一个光点里
import React from "react";
import { COPY } from "../lib/copy";
import { easeIn, easeOut, lerp, pop, ramp } from "../lib/anim";
import { C, FONT, type Lang } from "../lib/theme";
import { Headline } from "./parts";
import { T } from "./timeline";

const Cap: React.FC<{ k: string }> = ({ k }) => (
  <span
    style={{
      height: 40,
      minWidth: 40,
      padding: "0 10px",
      borderRadius: 9,
      display: "inline-grid",
      placeItems: "center",
      fontSize: 18,
      fontWeight: 600,
      color: "#E9EBF0",
      background: "linear-gradient(180deg, #2E2F36, #202126)",
      border: "1px solid rgba(255,255,255,0.12)",
      boxShadow: "0 3px 0 #0D0E11",
      fontFamily: FONT.display("en"),
    }}
  >
    {k}
  </span>
);

const Bubble: React.FC<{ f: number }> = ({ f }) => (
  <span style={{ position: "relative", width: 52, height: 40, borderRadius: 12, background: "rgba(255,255,255,0.10)", display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 5 }}>
    {[0, 1, 2].map((i) => (
      <span key={i} style={{ width: 6, height: 6, borderRadius: 3, background: "#E9EBF0", opacity: 0.35 + 0.65 * Math.max(0, Math.sin((f - i * 4) / 4)) }} />
    ))}
  </span>
);

export const Hook: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  if (f > T.dock + 30) return null;
  const copy = COPY[lang];
  const implode = ramp(f, T.implode, 22, easeIn);
  const caps = [["Ctrl", "C"], ["⊞", "Shift", "S"], null];
  // 向中心收拢
  const toCenter = (x: number, y: number) => ({ dx: (960 - x) * implode, dy: (540 - y) * implode });
  const orbIn = pop(f, T.implode + 18, 16);
  const ring = ramp(f, T.implode + 20, 30, easeOut);
  const orbUp = ramp(f, T.reveal - 4, 24, easeOut);
  const orbOut = ramp(f, T.dock, 14, easeIn);
  return (
    <>
      {f < T.implode + 24 ? (
        <div style={{ position: "absolute", inset: 0, opacity: 1 - ramp(f, T.implode + 14, 8), filter: implode > 0 ? `blur(${implode * 6}px)` : undefined }}>
          <div style={{ position: "absolute", inset: 0, transform: `translate(${toCenter(960, 330).dx}px, ${toCenter(960, 330).dy}px) scale(${1 - 0.8 * implode})` }}>
            <Headline f={f} lang={lang} text={copy.hookHead} start={4} end={9999} dockAt={9999} centerY={330} />
          </div>
          <div style={{ position: "absolute", left: 0, right: 0, top: 500, display: "flex", justifyContent: "center", gap: 22 }}>
            {copy.hookChips.map((label, i) => {
              const a = pop(f, T.hookChips[i], 14);
              const cx = 960 + (i - 1) * 420;
              const { dx, dy } = toCenter(cx, 540);
              return (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 16,
                    height: 80,
                    padding: "0 30px 0 18px",
                    borderRadius: 24,
                    background: "rgba(30, 30, 34, 0.86)",
                    border: "1px solid rgba(255,255,255,0.10)",
                    boxShadow: "0 18px 40px rgba(0,0,0,0.45)",
                    fontFamily: FONT.display(lang),
                    fontSize: 27,
                    color: C.text,
                    opacity: Math.min(1, a) * (1 - implode),
                    transform: `translate(${dx}px, ${dy + 18 * (1 - Math.min(1, a))}px) scale(${(0.9 + 0.1 * a) * (1 - 0.85 * implode)})`,
                  }}
                >
                  <span style={{ display: "flex", gap: 6 }}>{caps[i] ? caps[i]!.map((k) => <Cap key={k} k={k} />) : <Bubble f={f} />}</span>
                  {label}
                </div>
              );
            })}
          </div>
          <div style={{ position: "absolute", inset: 0, transform: `translate(${toCenter(960, 700).dx}px, ${toCenter(960, 700).dy}px) scale(${1 - 0.8 * implode})` }}>
            <div
              style={{
                position: "absolute",
                left: 0,
                right: 0,
                top: 668,
                textAlign: "center",
                fontFamily: FONT.display(lang),
                fontSize: 40,
                fontWeight: 600,
                letterSpacing: lang === "en" ? "-0.01em" : "0.04em",
                color: C.text2,
                opacity: ramp(f, T.hookTail, 14),
                transform: `translateY(${10 * (1 - ramp(f, T.hookTail, 14))}px)`,
              }}
            >
              {copy.hookTail}
            </div>
          </div>
        </div>
      ) : null}

      {/* 光点 + 冲击波 */}
      {f >= T.implode + 16 ? (
        <div style={{ position: "absolute", inset: 0, opacity: 1 - orbOut }}>
          {ring > 0 && ring < 1 ? (
            <div
              style={{
                position: "absolute",
                left: 960 - 700 * ring,
                top: 540 - 700 * ring,
                width: 1400 * ring,
                height: 1400 * ring,
                borderRadius: "50%",
                border: `2px solid color-mix(in srgb, ${C.askB} ${Math.round(70 * (1 - ring))}%, transparent)`,
                boxShadow: `0 0 60px color-mix(in srgb, ${C.askA} ${Math.round(40 * (1 - ring))}%, transparent)`,
              }}
            />
          ) : null}
          <div
            style={{
              position: "absolute",
              left: 960 - 34,
              top: lerp(540, 380, orbUp) - 34,
              width: 68,
              height: 68,
              borderRadius: "50%",
              background: `linear-gradient(135deg, ${C.askA}, ${C.askB})`,
              boxShadow: `0 0 0 14px color-mix(in srgb, ${C.askA} 14%, transparent), 0 0 90px color-mix(in srgb, ${C.askB} 70%, transparent)`,
              transform: `scale(${Math.max(0, orbIn) * (1 - 0.6 * orbOut)})`,
            }}
          />
        </div>
      ) : null}
    </>
  );
};
