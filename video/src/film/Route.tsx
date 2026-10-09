// 自动路由：每个请求自己挑引擎、模型和思考强度
import React from "react";
import { COPY } from "../lib/copy";
import { bezier, bezierLength, easeIn, easeInOut, easeOut, ramp } from "../lib/anim";
import { accent, C, FONT, UI, type Lang, type Mode } from "../lib/theme";
import { Orb } from "../ui/AppUI";
import { Headline } from "./parts";
import { T } from "./timeline";

const REQ = { x: 150, w: 470, h: 64, ys: [452, 586, 720] };
const HUB = { x: 960, y: 586, r: 74 };
const ENG = { x: 1290, w: 480, tops: [300, 610], rowH: 72, head: 74 };
const ENGINES = [
  { name: "Claude Code", models: ["claude-opus-5-5", "claude-sonnet-5-5"] },
  { name: "Codex", models: ["gpt-6-astra", "gpt-6.1-sol"] },
];
const rowY = (e: number, r: number) => ENG.tops[e] + ENG.head + r * ENG.rowH + ENG.rowH / 2;

// 三个请求各自去哪：[请求, 引擎, 模型行, 思考强度, 是否"更省"]
const PLAN: [number, number, number, number, boolean][] = [
  [0, 0, 0, 2, false],
  [1, 1, 0, 2, false],
  [2, 0, 1, 1, true],
];
const MODES: Mode[] = ["ask", "act", "ask"];

const pathIn = (i: number) => [[REQ.x + REQ.w, REQ.ys[i]], [760, REQ.ys[i]], [800, HUB.y], [HUB.x - HUB.r, HUB.y]];
const pathOut = (y: number) => [[HUB.x + HUB.r, HUB.y], [1150, HUB.y], [1170, y], [ENG.x, y]];

const Wire: React.FC<{ p: number[][]; t: number; keep: number; color: string }> = ({ p, t, keep, color }) => {
  const len = bezierLength(p);
  const d = `M${p[0][0]} ${p[0][1]} C${p[1][0]} ${p[1][1]} ${p[2][0]} ${p[2][1]} ${p[3][0]} ${p[3][1]}`;
  const [x, y] = bezier(p, Math.min(1, t));
  return (
    <>
      <path d={d} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={2} />
      <path d={d} fill="none" stroke={color} strokeWidth={2.5} strokeDasharray={len} strokeDashoffset={len * (1 - t)} opacity={keep} strokeLinecap="round" />
      {t > 0 && t < 1 ? (
        <>
          <circle cx={x} cy={y} r={14} fill={color} opacity={0.25} />
          <circle cx={x} cy={y} r={6} fill="#fff" />
        </>
      ) : null}
    </>
  );
};

export const Route: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  if (f < T.route || f > T.evolve + 14) return null;
  const copy = COPY[lang];
  const show = ramp(f, T.route + 14, 18) * (1 - ramp(f, T.evolve - 4, 14, easeIn));
  const legs = PLAN.map((_, k) => {
    const r = T.routes[k];
    return { a: ramp(f, r, 16, easeInOut), b: ramp(f, r + 18, 16, easeInOut), hit: ramp(f, r + 34, 10), at: r };
  });
  const hubPulse = Math.max(...legs.map((l) => (f >= l.at + 16 ? Math.max(0, 1 - (f - l.at - 16) / 18) : 0)));
  const spin = f * 1.6;
  return (
    <>
      <Headline f={f} lang={lang} text={copy.routeHead} sub={copy.routeSub} start={T.route + 6} end={T.evolve - 12} tone="duo" />
      <div style={{ position: "absolute", inset: 0, opacity: show, transform: `translateY(${16 * (1 - show)}px)`, fontFamily: FONT.ui }}>
        <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
          {PLAN.map(([req, eng, row], k) => {
            const [a] = accent(MODES[req]);
            const keep = 1 - 0.55 * ramp(f, T.routes[k] + 50, 20);
            return (
              <g key={k}>
                <Wire p={pathIn(req)} t={legs[k].a} keep={keep} color={a} />
                <Wire p={pathOut(rowY(eng, row))} t={legs[k].b} keep={keep} color={a} />
              </g>
            );
          })}
        </svg>

        {/* 请求 */}
        {copy.requests.map((text, i) => {
          const a = ramp(f, T.route + 22 + i * 7, 14);
          const active = legs.findIndex((l, k) => PLAN[k][0] === i && f >= l.at - 2 && f < l.at + 40) >= 0;
          const mode = MODES[i];
          const [ca] = accent(mode);
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: REQ.x,
                top: REQ.ys[i] - REQ.h / 2,
                width: REQ.w,
                height: REQ.h,
                borderRadius: 16,
                background: UI.surface,
                border: `1px solid ${active ? `color-mix(in srgb, ${ca} 60%, transparent)` : UI.stroke}`,
                boxShadow: `${UI.shadow}${active ? `, 0 0 30px color-mix(in srgb, ${ca} 35%, transparent)` : ""}`,
                display: "flex",
                alignItems: "center",
                gap: 14,
                padding: "0 18px 0 22px",
                color: UI.text,
                fontSize: 19,
                opacity: a,
                transform: `translateX(${-24 * (1 - a)}px)`,
              }}
            >
              <Orb mode={mode} f={f} size={12} />
              <span style={{ flex: 1, whiteSpace: "nowrap" }}>{text}</span>
              <span style={{ fontSize: 13, padding: "6px 11px", borderRadius: 999, color: `color-mix(in srgb, ${ca} 70%, ${UI.text})`, background: `color-mix(in srgb, ${ca} 13%, transparent)` }}>
                {mode === "ask" ? copy.modeAsk : copy.modeAct}
              </span>
            </div>
          );
        })}

        {/* 路由中心 */}
        <div style={{ position: "absolute", left: HUB.x - HUB.r, top: HUB.y - HUB.r, width: HUB.r * 2, height: HUB.r * 2, opacity: ramp(f, T.route + 26, 14) }}>
          <svg width={HUB.r * 2 + 40} height={HUB.r * 2 + 40} style={{ position: "absolute", left: -20, top: -20, transform: `rotate(${spin}deg)` }}>
            <circle cx={HUB.r + 20} cy={HUB.r + 20} r={HUB.r + 12} fill="none" stroke="url(#ring)" strokeWidth={2} strokeDasharray="6 10" />
            <defs>
              <linearGradient id="ring" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor={C.askA} />
                <stop offset="1" stopColor={C.actB} />
              </linearGradient>
            </defs>
          </svg>
          <div
            style={{
              position: "absolute",
              inset: 0,
              borderRadius: "50%",
              background: "radial-gradient(circle at 35% 30%, #2A2C36, #15161B)",
              border: "1px solid rgba(255,255,255,0.12)",
              boxShadow: `0 20px 50px rgba(0,0,0,0.5), 0 0 ${30 + 50 * hubPulse}px color-mix(in srgb, ${C.askB} ${Math.round(30 + 50 * hubPulse)}%, transparent)`,
              display: "grid",
              placeItems: "center",
            }}
          >
            <div style={{ width: 38, height: 38, borderRadius: "50%", background: `linear-gradient(135deg, ${C.askA}, ${C.askB})`, boxShadow: `0 0 30px ${C.askB}`, transform: `scale(${1 + 0.18 * hubPulse})` }} />
          </div>
          <div style={{ position: "absolute", left: -60, right: -60, top: HUB.r * 2 + 26, textAlign: "center", fontSize: 18, color: UI.text2, fontFamily: FONT.display(lang) }}>{copy.router}</div>
        </div>

        {/* 引擎和模型 */}
        {ENGINES.map((eng, e) => {
          const a = ramp(f, T.route + 30 + e * 8, 16);
          return (
            <div
              key={eng.name}
              style={{
                position: "absolute",
                left: ENG.x,
                top: ENG.tops[e],
                width: ENG.w,
                height: ENG.head + ENG.rowH * 2 + 14,
                borderRadius: 18,
                background: "rgba(26, 26, 30, 0.9)",
                border: `1px solid ${UI.stroke}`,
                boxShadow: UI.shadow,
                opacity: a,
                transform: `translateX(${24 * (1 - a)}px)`,
              }}
            >
              <div style={{ height: ENG.head, display: "flex", alignItems: "center", padding: "0 24px", fontFamily: FONT.display("en"), fontSize: 27, fontWeight: 650, color: UI.text }}>{eng.name}</div>
              {eng.models.map((m, r) => {
                const k = PLAN.findIndex(([, pe, pr]) => pe === e && pr === r);
                const hit = k >= 0 ? legs[k].hit : 0;
                const [ca, cb] = k >= 0 ? accent(MODES[PLAN[k][0]]) : [C.askA, C.askB];
                const effort = k >= 0 ? PLAN[k][3] : -1;
                return (
                  <div key={m} style={{ position: "relative", height: ENG.rowH, margin: "0 12px", padding: "0 12px", display: "flex", alignItems: "center", gap: 14, borderRadius: 12, background: hit > 0 ? `color-mix(in srgb, ${ca} ${Math.round(12 * hit)}%, transparent)` : undefined, boxShadow: hit > 0 ? `inset 0 0 0 1px color-mix(in srgb, ${ca} ${Math.round(55 * hit)}%, transparent)` : undefined }}>
                    <span style={{ fontFamily: FONT.mono, fontSize: 19, color: UI.text, flex: 1 }}>{m}</span>
                    <span style={{ display: "flex", gap: 4 }}>
                      {copy.efforts.map((lv, j) => {
                        const on = hit > 0 && j <= effort;
                        return (
                          <span key={lv} style={{ fontSize: 12.5, padding: "4px 8px", borderRadius: 6, color: on ? "#fff" : UI.text3, background: on ? `linear-gradient(135deg, ${ca}, ${cb})` : "rgba(255,255,255,0.05)", opacity: on ? 0.55 + 0.45 * hit : 1 }}>
                            {lv}
                          </span>
                        );
                      })}
                    </span>
                    <span style={{ width: 24, height: 24, borderRadius: "50%", display: "grid", placeItems: "center", background: `color-mix(in srgb, ${C.ok} 18%, transparent)`, opacity: hit, transform: `scale(${0.6 + 0.4 * hit})` }}>
                      <svg viewBox="0 0 20 20" width={15} height={15} style={{ fill: "none", stroke: C.ok, strokeWidth: 2.2, strokeLinecap: "round", strokeLinejoin: "round" }}>
                        <path d="M5 10.5l3.2 3.2L15 7" />
                      </svg>
                    </span>
                    {k >= 0 && PLAN[k][4] ? (
                      <span style={{ position: "absolute", right: 0, top: ENG.rowH + 18, fontSize: 14, padding: "4px 10px", borderRadius: 999, background: `color-mix(in srgb, ${C.ok} 20%, #17181C)`, border: `1px solid color-mix(in srgb, ${C.ok} 55%, transparent)`, color: "#B9F3D2", whiteSpace: "nowrap", opacity: ramp(f, T.routes[k] + 40, 10), transform: `translateY(${6 * (1 - ramp(f, T.routes[k] + 40, 10, easeOut))}px)` }}>
                        {copy.cheaper}
                      </span>
                    ) : null}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </>
  );
};
