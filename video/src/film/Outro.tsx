// ⑫ 总结 + 下载：八个亮点一屏看完，然后是名字、一句话和下载地址
import React from "react";
import { COPY } from "../lib/copy";
import { easeIn, easeOut, pop, ramp } from "../lib/anim";
import { C, FONT, UI, type Lang } from "../lib/theme";
import { Headline, panel } from "./parts";
import { CH } from "./timeline";

const S = CH.recap;
const L = S + 180; // 名字和下载地址（落在小节线上）

const ICONS = [
  // 看得见屏幕
  <path key="0" d="M3 5.5A1.5 1.5 0 0 1 4.5 4h15A1.5 1.5 0 0 1 21 5.5v10a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 15.5zM9 20h6M7 8.5h7M7 11.5h10" />,
  // 问答
  <path key="1" d="M5 6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v6a2.5 2.5 0 0 1-2.5 2.5H11l-4 3.5V15h-.5A2.5 2.5 0 0 1 4 12.5zM10 8.2a2 2 0 1 1 2.6 1.9c-.4.2-.6.5-.6.9M12 12.5v.2" />,
  // 操作
  <path key="2" d="M13 3L5 13.5h6L10 21l8-10.5h-6z" />,
  // 指引
  <path key="3" d="M4 4l7 16 2.2-6.8L20 11z" />,
  // 路由
  <path key="4" d="M5 6h4l3 6-3 6H5M12 12h7M16 9l3 3-3 3" />,
  // 经验
  <path key="5" d="M12 3.5a5.5 5.5 0 0 0-3.2 10v2.5h6.4v-2.5A5.5 5.5 0 0 0 12 3.5zM9.5 19.5h5" />,
  // 自我改进
  <path key="6" d="M19 12a7 7 0 1 1-2.1-5M19 4v4h-4" />,
  // 社区共建
  <path key="7" d="M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM16.5 10a2.5 2.5 0 1 0 0-5M3 19c.8-3 2.8-4.5 5-4.5s4.2 1.5 5 4.5M15 14.5c2 .2 3.5 1.6 4.2 4" />,
];

export const Outro: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  if (f < S - 2) return null;
  const copy = COPY[lang];

  // 第一拍：八个亮点
  const tilesOut = ramp(f, L - 16, 16, easeIn);
  // 第二拍：名字
  const orb = pop(f, L + 4, 18);
  const ring = ramp(f, L + 6, 34, easeOut);
  const fadeAll = ramp(f, CH.end - 18, 18, easeIn);
  const rise = (at: number, d = 16) => {
    const a = ramp(f, at, d);
    return { opacity: a, transform: `translateY(${14 * (1 - a)}px)`, filter: a < 1 ? `blur(${6 * (1 - a)}px)` : undefined };
  };
  const nameSize = lang === "en" ? 112 : 108;
  return (
    <div style={{ position: "absolute", inset: 0, opacity: 1 - fadeAll }}>
      <Headline f={f} lang={lang} text={copy.recapHead} start={S + 6} end={L - 16} />
      {f < L ? (
        <div style={{ position: "absolute", inset: 0, opacity: 1 - tilesOut, fontFamily: FONT.display(lang) }}>
          {copy.recapTiles.map(([title, sub], i) => {
            const a = ramp(f, S + 24 + i * 7, 14);
            const x = 164 + (i % 4) * (380 + 24);
            const y = 350 + Math.floor(i / 4) * (200 + 24);
            const warm = i === 2;
            return (
              <div key={title} style={{ ...panel({ left: x, top: y, width: 380, height: 200, padding: "26px 26px" }), opacity: a, transform: `translateY(${14 * (1 - a)}px)` }}>
                <svg width={34} height={34} viewBox="0 0 24 24" fill="none" stroke={warm ? C.actB : C.askA} strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
                  {ICONS[i]}
                </svg>
                <div style={{ marginTop: 18, fontSize: 25, fontWeight: 650 }}>{title}</div>
                <div style={{ marginTop: 8, fontSize: 18, color: UI.text2 }}>{sub}</div>
              </div>
            );
          })}
        </div>
      ) : null}

      {f >= L ? (
        <>
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
          <div style={{ position: "absolute", left: 0, right: 0, top: 418, textAlign: "center", fontFamily: FONT.display(lang), fontSize: nameSize, fontWeight: 700, letterSpacing: lang === "en" ? "-0.03em" : "0.04em", color: C.text, lineHeight: 1.1, ...rise(L + 12, 18) }}>
            {copy.name}
          </div>
          <div style={{ position: "absolute", left: 0, right: 0, top: 548, textAlign: "center", fontFamily: FONT.display(lang === "en" ? "zh" : "en"), fontSize: 30, fontWeight: 500, letterSpacing: "0.08em", color: C.text3, ...rise(L + 22) }}>
            {copy.altName}
          </div>
          <div style={{ position: "absolute", left: 0, right: 0, top: 618, textAlign: "center", fontFamily: FONT.display(lang), fontSize: 40, fontWeight: 600, letterSpacing: lang === "en" ? "-0.015em" : "0.03em", ...rise(L + 34) }}>
            <span style={{ background: `linear-gradient(90deg, ${C.askA}, ${C.askB} 55%, ${C.actB})`, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>{copy.tagline}</span>
          </div>
          <div style={{ position: "absolute", left: 0, right: 0, top: 726, display: "flex", justifyContent: "center", gap: 18, fontFamily: FONT.display(lang), fontSize: 24, color: C.text2 }}>
            {copy.facts.map((fact, i) => (
              <React.Fragment key={fact}>
                {i > 0 ? <span style={{ color: C.text3, ...rise(L + 52 + i * 6) }}>·</span> : null}
                <span style={rise(L + 52 + i * 6)}>{fact}</span>
              </React.Fragment>
            ))}
          </div>
          <div style={{ position: "absolute", left: 0, right: 0, top: 806, display: "flex", justifyContent: "center", ...rise(L + 76) }}>
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
        </>
      ) : null}
    </div>
  );
};
