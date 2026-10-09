// ⑧ 路由：每次挑引擎 × 模型 × 思考强度 → 从每次结果里学（含后台对比）→ 证明一样好才换更省的
import React from "react";
import { COPY } from "../lib/copy";
import { bezier, bezierLength, clamp, easeIn, easeInOut, easeOut, lerp, ramp } from "../lib/anim";
import { accent, C, FONT, UI, type Lang, type Mode } from "../lib/theme";
import { Orb } from "../ui/AppUI";
import { Headline, panel } from "./parts";
import { CH } from "./timeline";

const S = CH.route;
const B = S + 240; // 第二拍：在线学习
const G = S + 510; // 第三拍：证明一样好才省
const COST = "#E8662F"; // 图表里"花费"那条线（深色底上通过配色检查的橙色）

const REQ = { x: 150, w: 470, h: 64, ys: [452, 586, 720] };
const HUB = { x: 960, y: 586, r: 74 };
const HUB2 = { x: 560, y: 600 };
const ENG = { x: 1290, w: 480, tops: [300, 610], rowH: 72, head: 74 };
const ENGINES = [
  { name: "Claude Code", models: ["claude-opus-5-5", "claude-sonnet-5-5"] },
  { name: "Codex", models: ["gpt-6-astra", "gpt-6.1-sol"] },
];
const rowY = (e: number, r: number) => ENG.tops[e] + ENG.head + r * ENG.rowH + ENG.rowH / 2;
// 三个请求各自去哪：[请求, 引擎, 模型行, 思考强度]
const PLAN: [number, number, number, number][] = [
  [0, 0, 0, 2],
  [1, 1, 0, 2],
  [2, 0, 1, 1],
];
const MODES: Mode[] = ["ask", "act", "ask"];
const ROUTES = [S + 80, S + 130, S + 180];

const pathIn = (i: number) => [[REQ.x + REQ.w, REQ.ys[i]], [760, REQ.ys[i]], [800, HUB.y], [HUB.x - HUB.r, HUB.y]];
const pathOut = (y: number) => [[HUB.x + HUB.r, HUB.y], [1150, HUB.y], [1170, y], [ENG.x, y]];

const Wire: React.FC<{ p: number[][]; t: number; color: string }> = ({ p, t, color }) => {
  const len = bezierLength(p);
  const d = `M${p[0][0]} ${p[0][1]} C${p[1][0]} ${p[1][1]} ${p[2][0]} ${p[2][1]} ${p[3][0]} ${p[3][1]}`;
  const [x, y] = bezier(p, Math.min(1, t));
  return (
    <>
      <path d={d} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={2} />
      <path d={d} fill="none" stroke={color} strokeWidth={2.5} strokeDasharray={len} strokeDashoffset={len * (1 - t)} strokeLinecap="round" />
      {t > 0 && t < 1 ? (
        <>
          <circle cx={x} cy={y} r={14} fill={color} opacity={0.25} />
          <circle cx={x} cy={y} r={6} fill="#fff" />
        </>
      ) : null}
    </>
  );
};

/** 路由中心：圆盘 + 旋转的虚线圈 */
const Hub: React.FC<{ f: number; x: number; y: number; pulse: number; label: string; scale?: number }> = ({ f, x, y, pulse, label, scale = 1 }) => (
  <div style={{ position: "absolute", left: x - HUB.r, top: y - HUB.r, width: HUB.r * 2, height: HUB.r * 2, transform: `scale(${scale})` }}>
    <svg width={HUB.r * 2 + 40} height={HUB.r * 2 + 40} style={{ position: "absolute", left: -20, top: -20, transform: `rotate(${f * 1.6}deg)` }}>
      <circle cx={HUB.r + 20} cy={HUB.r + 20} r={HUB.r + 12} fill="none" stroke="url(#hubring)" strokeWidth={2} strokeDasharray="6 10" />
      <defs>
        <linearGradient id="hubring" x1="0" y1="0" x2="1" y2="1">
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
        boxShadow: `0 20px 50px rgba(0,0,0,0.5), 0 0 ${30 + 50 * pulse}px color-mix(in srgb, ${C.askB} ${Math.round(30 + 50 * pulse)}%, transparent)`,
        display: "grid",
        placeItems: "center",
      }}
    >
      <div style={{ width: 38, height: 38, borderRadius: "50%", background: `linear-gradient(135deg, ${C.askA}, ${C.askB})`, boxShadow: `0 0 30px ${C.askB}`, transform: `scale(${1 + 0.18 * pulse})` }} />
    </div>
    <div style={{ position: "absolute", left: -80, right: -80, top: HUB.r * 2 + 26, textAlign: "center", fontSize: 18, color: UI.text2, fontFamily: FONT.ui }}>{label}</div>
  </div>
);

// ---------- 第一拍：挑选 ----------

const Picking: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  const show = ramp(f, S + 18, 18) * (1 - ramp(f, B - 16, 18, easeIn));
  const legs = PLAN.map((_, k) => ({ a: ramp(f, ROUTES[k], 16, easeInOut), b: ramp(f, ROUTES[k] + 18, 16, easeInOut), hit: ramp(f, ROUTES[k] + 34, 10), at: ROUTES[k] }));
  return (
    <div style={{ position: "absolute", inset: 0, opacity: show, transform: `translateY(${14 * (1 - ramp(f, S + 18, 18))}px)`, fontFamily: FONT.ui }}>
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {PLAN.map(([req, eng, row], k) => {
          const [a] = accent(MODES[req]);
          return (
            <g key={k} opacity={1 - 0.55 * ramp(f, ROUTES[k] + 56, 20)}>
              <Wire p={pathIn(req)} t={legs[k].a} color={a} />
              <Wire p={pathOut(rowY(eng, row))} t={legs[k].b} color={a} />
            </g>
          );
        })}
      </svg>
      {copy.requests.map((text, i) => {
        const a = ramp(f, S + 26 + i * 8, 14);
        const active = legs.findIndex((l, k) => PLAN[k][0] === i && f >= l.at - 2 && f < l.at + 40) >= 0;
        const mode = MODES[i];
        const [ca] = accent(mode);
        return (
          <div
            key={i}
            style={{
              ...panel({ left: REQ.x, top: REQ.ys[i] - REQ.h / 2, width: REQ.w, height: REQ.h, borderRadius: 16 }),
              border: `1px solid ${active ? `color-mix(in srgb, ${ca} 60%, transparent)` : UI.stroke}`,
              boxShadow: `${UI.shadow}${active ? `, 0 0 30px color-mix(in srgb, ${ca} 35%, transparent)` : ""}`,
              display: "flex",
              alignItems: "center",
              gap: 14,
              padding: "0 18px 0 22px",
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
      {ENGINES.map((eng, e) => {
        const a = ramp(f, S + 34 + e * 8, 16);
        return (
          <div key={eng.name} style={{ ...panel({ left: ENG.x, top: ENG.tops[e], width: ENG.w, height: ENG.head + ENG.rowH * 2 + 14 }), opacity: a, transform: `translateX(${24 * (1 - a)}px)` }}>
            <div style={{ height: ENG.head, display: "flex", alignItems: "center", padding: "0 24px", fontFamily: FONT.display("en"), fontSize: 27, fontWeight: 650 }}>{eng.name}</div>
            {eng.models.map((m, r) => {
              const k = PLAN.findIndex(([, pe, pr]) => pe === e && pr === r);
              const hit = k >= 0 ? legs[k].hit : 0;
              const [ca, cb] = k >= 0 ? accent(MODES[PLAN[k][0]]) : [C.askA, C.askB];
              const effort = k >= 0 ? PLAN[k][3] : -1;
              return (
                <div
                  key={m}
                  style={{
                    height: ENG.rowH,
                    margin: "0 12px",
                    padding: "0 12px",
                    display: "flex",
                    alignItems: "center",
                    gap: 14,
                    borderRadius: 12,
                    background: hit > 0 ? `color-mix(in srgb, ${ca} ${Math.round(12 * hit)}%, transparent)` : undefined,
                    boxShadow: hit > 0 ? `inset 0 0 0 1px color-mix(in srgb, ${ca} ${Math.round(55 * hit)}%, transparent)` : undefined,
                  }}
                >
                  <span style={{ fontFamily: FONT.mono, fontSize: 19, flex: 1 }}>{m}</span>
                  <span style={{ display: "flex", gap: 4 }}>
                    {copy.efforts.map((lv, j) => {
                      const on = hit > 0 && j <= effort;
                      return (
                        <span key={lv} style={{ fontSize: 12.5, padding: "4px 8px", borderRadius: 6, color: on ? "#fff" : UI.text3, background: on ? `linear-gradient(135deg, ${ca}, ${cb})` : "rgba(255,255,255,0.05)" }}>
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
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
};

// ---------- 第二拍：从每次结果里学；空闲时的后台对比 ----------

const SIG_Y = [410, 505, 600, 695, 790];

const Learning2: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  if (f < B - 20 || f > G + 24) return null;
  const out = ramp(f, G - 10, 20, easeIn);
  const duelA = ramp(f, B + 60, 18);
  const streamT = clamp((f - (B + 80)) / 40, 0, 1);
  const verdict = ramp(f, B + 136, 12);
  const filled = 30 + Math.min(8, Math.max(0, Math.floor((f - (B + 150)) / 8) + 1));
  const arrivals = copy.signals.map((_, i) => B + 40 + i * 16 + 36);
  const pulse = Math.max(0, ...arrivals.map((at) => (f >= at ? Math.max(0, 1 - (f - at) / 16) : 0)));
  const Skeleton: React.FC<{ widths: number[]; t: number; color: string }> = ({ widths, t, color }) => (
    <div style={{ marginTop: 14 }}>
      {widths.map((w, i) => (
        <div key={i} style={{ height: 10, borderRadius: 5, marginTop: 10, width: `${w * clamp(t * widths.length - i, 0, 1)}%`, background: i === 0 ? `color-mix(in srgb, ${color} 55%, rgba(255,255,255,0.3))` : "rgba(255,255,255,0.16)" }} />
      ))}
    </div>
  );
  return (
    <div style={{ position: "absolute", inset: 0, opacity: 1 - out, fontFamily: FONT.ui }}>
      {/* 学习信号：从左边飞进路由中心 */}
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {copy.signals.map((_, i) => {
          const at = B + 40 + i * 16;
          const p = [[380, SIG_Y[i]], [450, SIG_Y[i]], [HUB2.x - 140, HUB2.y], [HUB2.x - HUB.r, HUB2.y]];
          const t = ramp(f, at + 18, 18, easeInOut);
          if (f < at + 18) return null;
          const [x, y] = bezier(p, t);
          return (
            <g key={i} opacity={1 - 0.6 * ramp(f, at + 40, 20)}>
              <path d={`M${p[0][0]} ${p[0][1]} C${p[1][0]} ${p[1][1]} ${p[2][0]} ${p[2][1]} ${p[3][0]} ${p[3][1]}`} fill="none" stroke="rgba(155,107,255,0.35)" strokeWidth={2} strokeDasharray="4 6" />
              {t < 1 ? <circle cx={x} cy={y} r={7} fill="#fff" /> : null}
            </g>
          );
        })}
      </svg>
      {copy.signals.map((text, i) => {
        const at = B + 40 + i * 16;
        const a = ramp(f, at, 12);
        return (
          <div
            key={i}
            style={{
              ...panel({ left: 110, top: SIG_Y[i] - 26, height: 52, borderRadius: 999, padding: "0 22px", display: "flex", alignItems: "center", fontSize: 19, whiteSpace: "nowrap" }),
              opacity: a,
              transform: `translateX(${-20 * (1 - a)}px)`,
            }}
          >
            {text}
          </div>
        );
      })}

      {/* 后台对比 */}
      <div style={{ ...panel({ left: 860, top: 286, width: 920, height: 600, padding: "26px 30px" }), opacity: duelA, transform: `translateY(${16 * (1 - duelA)}px)` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 18, color: UI.text2 }}>
          <svg width={18} height={18} viewBox="0 0 20 20" fill="none" stroke={C.askB} strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
            <path d="M15.5 12.5A6.5 6.5 0 0 1 7.5 4.5a6.5 6.5 0 1 0 8 8z" />
          </svg>
          {copy.duelTitle}
        </div>
        <div style={{ marginTop: 16, display: "inline-flex", alignItems: "center", gap: 10, height: 44, padding: "0 18px", borderRadius: 999, background: "rgba(255,255,255,0.06)", fontSize: 18 }}>
          <Orb mode="ask" f={f} size={10} />
          <span style={{ color: UI.text2 }}>{copy.duelSame}:</span>
          {copy.requests[0]}
        </div>
        <div style={{ display: "flex", gap: 20, marginTop: 22 }}>
          {[
            { label: copy.duelA, model: "claude-opus-5-5 · high", color: C.askA },
            { label: copy.duelB, model: "claude-sonnet-5-5 · med", color: C.ok },
          ].map((side, i) => (
            <div key={i} style={{ flex: 1, padding: "16px 18px 20px", borderRadius: 14, background: "rgba(255,255,255,0.04)", border: `1px solid ${i === 1 ? `color-mix(in srgb, ${C.ok} ${Math.round(50 * verdict)}%, rgba(255,255,255,0.08))` : "rgba(255,255,255,0.08)"}` }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontSize: 16, color: UI.text2 }}>{side.label}</span>
                <span style={{ fontFamily: FONT.mono, fontSize: 14, color: UI.text2 }}>{side.model}</span>
              </div>
              <Skeleton widths={[92, 80, 86, 58]} t={streamT} color={side.color} />
            </div>
          ))}
        </div>
        <div style={{ marginTop: 22, display: "flex", alignItems: "center", gap: 12, fontSize: 19, opacity: verdict, transform: `translateY(${8 * (1 - verdict)}px)` }}>
          <span style={{ width: 30, height: 30, borderRadius: "50%", display: "grid", placeItems: "center", background: `color-mix(in srgb, ${C.ok} 20%, transparent)` }}>
            <svg viewBox="0 0 20 20" width={17} height={17} style={{ fill: "none", stroke: C.ok, strokeWidth: 2.2, strokeLinecap: "round", strokeLinejoin: "round" }}>
              <path d="M5 10.5l3.2 3.2L15 7" />
            </svg>
          </span>
          {copy.judge}
        </div>
        <div style={{ marginTop: 22, opacity: ramp(f, B + 146, 10) }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 15, color: UI.text2 }}>
            <span>{copy.evidence}</span>
            <span style={{ fontVariantNumeric: "tabular-nums", color: UI.text }}>{filled} / 40</span>
          </div>
          <div style={{ display: "flex", gap: 4, marginTop: 10 }}>
            {Array.from({ length: 40 }, (_, i) => (
              <span key={i} style={{ flex: 1, height: 10, borderRadius: 3, background: i < filled ? (i >= 30 ? C.ok : `color-mix(in srgb, ${C.ok} 55%, rgba(255,255,255,0.1))`) : "rgba(255,255,255,0.08)" }} />
            ))}
          </div>
        </div>
      </div>
      {f >= B + 6 ? <Hub f={f} x={HUB2.x} y={HUB2.y} pulse={pulse} label={copy.router} /> : null}
    </div>
  );
};

// ---------- 第三拍：证明一样好才换更省的（两个小图共用横轴，不用双纵轴） ----------

const CHART = { x: 330, w: 1260, top: 280 };
const PLOT = { x0: 400, x1: 1540 };
const STEPS = [2.6, 5.0, 7.2]; // 第几周证明了更省的配置
const COST_LEVELS = [0, 70, 125, 168]; // 每次下一个台阶后的高度（像素，往下）
const wx = (w: number) => lerp(PLOT.x0, PLOT.x1, (w - 1) / 7);

const Gate: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  if (f < G - 10) return null;
  const a = ramp(f, G + 10, 20);
  const draw = ramp(f, G + 40, 120, easeInOut); // 线从左往右画出来
  const week = 1 + 7 * draw;
  const out = ramp(f, CH.exp - 16, 14, easeIn);
  // 成功率：贴着上面、几乎不动
  const successY = (w: number) => 372 - 4 * Math.sin(w * 1.7) - 2 * Math.sin(w * 3.1);
  const successPts = Array.from({ length: 57 }, (_, i) => 1 + (7 * i) / 56).map((w) => [wx(w), successY(w)]);
  // 花费：每次证明后下一个台阶
  const costY = (w: number) => 620 + COST_LEVELS[STEPS.filter((s) => w >= s).length];
  const costPts: number[][] = [[wx(1), costY(1)]];
  STEPS.forEach((s, i) => {
    costPts.push([wx(s), 620 + COST_LEVELS[i]]);
    costPts.push([wx(s), 620 + COST_LEVELS[i + 1]]);
  });
  costPts.push([wx(8), costY(8)]);
  const clipX = lerp(PLOT.x0, PLOT.x1, draw);
  const pathOf = (pts: number[][]) => pts.map((p, i) => `${i ? "L" : "M"}${p[0]} ${p[1]}`).join(" ");
  return (
    <div style={{ position: "absolute", inset: 0, opacity: a * (1 - out), fontFamily: FONT.ui }}>
      <div style={panel({ left: CHART.x, top: CHART.top, width: CHART.w, height: 640 })} />
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        <defs>
          <clipPath id="draw">
            <rect x={0} y={0} width={clipX} height={1080} />
          </clipPath>
          <linearGradient id="costfill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={COST} stopOpacity={0.22} />
            <stop offset="1" stopColor={COST} stopOpacity={0} />
          </linearGradient>
        </defs>
        {/* 网格：很淡 */}
        {[350, 420, 490].map((y) => (
          <line key={y} x1={PLOT.x0} x2={PLOT.x1} y1={y} y2={y} stroke="rgba(255,255,255,0.06)" strokeDasharray="4 6" />
        ))}
        {[640, 710, 780].map((y) => (
          <line key={y} x1={PLOT.x0} x2={PLOT.x1} y1={y} y2={y} stroke="rgba(255,255,255,0.06)" strokeDasharray="4 6" />
        ))}
        <line x1={PLOT.x0} x2={PLOT.x1} y1={830} y2={830} stroke="rgba(255,255,255,0.18)" />
        {Array.from({ length: 8 }, (_, i) => (
          <text key={i} x={wx(i + 1)} y={862} fill={UI.text3} fontSize={17} textAnchor="middle" fontFamily="Segoe UI Variable Text, sans-serif">
            {i + 1}
          </text>
        ))}
        <g clipPath="url(#draw)">
          <path d={pathOf(successPts)} fill="none" stroke={C.askA} strokeWidth={3} strokeLinejoin="round" strokeLinecap="round" />
          <path d={`${pathOf(costPts)} L${wx(8)} 830 L${wx(1)} 830 Z`} fill="url(#costfill)" />
          <path d={pathOf(costPts)} fill="none" stroke={COST} strokeWidth={3} strokeLinejoin="round" strokeLinecap="round" />
        </g>
        {/* 现在画到哪：两条线的端点 */}
        {draw > 0 && draw < 1 ? (
          <>
            <circle cx={clipX} cy={successY(week)} r={6} fill={C.askA} stroke="#18191E" strokeWidth={2} />
            <circle cx={clipX} cy={costY(week)} r={6} fill={COST} stroke="#18191E" strokeWidth={2} />
          </>
        ) : null}
      </svg>
      {/* 两个小图的标题（文字用正文色，旁边的色块标明是哪条线） */}
      {[
        { y: 300, color: C.askA, text: copy.chartSuccess },
        { y: 560, color: COST, text: copy.chartCost },
      ].map((t) => (
        <div key={t.text} style={{ position: "absolute", left: PLOT.x0, top: t.y, display: "flex", alignItems: "center", gap: 10, fontSize: 21, color: UI.text }}>
          <span style={{ width: 18, height: 4, borderRadius: 2, background: t.color }} />
          {t.text}
        </div>
      ))}
      <div style={{ position: "absolute", left: 0, right: 0, top: 884, textAlign: "center", fontSize: 17, color: UI.text3 }}>{copy.chartX}</div>
      {/* 证明更省的配置一样好的那几处 */}
      {STEPS.map((s, i) => {
        const at = G + 40 + Math.round(((s - 1) / 7) * 120);
        const p = ramp(f, at, 12, easeOut);
        if (f < at) return null;
        const y = 620 + COST_LEVELS[i + 1];
        return (
          <div key={i} style={{ position: "absolute", left: wx(s) + 10, top: y - 48, opacity: p, transform: `translateY(${8 * (1 - p)}px)` }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, height: 30, padding: "0 12px", borderRadius: 999, fontSize: 15, color: UI.text, background: `color-mix(in srgb, ${C.ok} 22%, #18191E)`, border: `1px solid color-mix(in srgb, ${C.ok} 55%, transparent)` }}>
              {copy.gatePass}
            </span>
          </div>
        );
      })}
      <div style={{ position: "absolute", left: 0, right: 0, top: 952, display: "flex", justifyContent: "center", opacity: ramp(f, G + 150, 16) }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 10, fontSize: 21, color: UI.text2 }}>
          <svg width={20} height={20} viewBox="0 0 20 20" fill="none" stroke={C.askB} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
            <path d="M10 16V4M5 9l5-5 5 5" />
          </svg>
          {copy.escalate}
        </span>
      </div>
    </div>
  );
};

export const Learning: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  if (f < S || f > CH.exp + 10) return null;
  const copy = COPY[lang];
  // 第一拍的路由中心移到左边，变成第二拍"学习"的中心
  const move = ramp(f, B - 14, 26, easeInOut);
  const hubOut = 1 - ramp(f, B + 6, 1);
  const legsAt = [S + 96, S + 146, S + 196];
  const pulse = Math.max(0, ...legsAt.map((at) => (f >= at ? Math.max(0, 1 - (f - at) / 18) : 0)));
  return (
    <>
      <Headline f={f} lang={lang} text={copy.routeHead} sub={copy.routeSub} start={S + 6} end={B - 12} tone="duo" />
      <Headline f={f} lang={lang} text={copy.learnHead} sub={copy.learnSub} start={B + 6} end={G - 12} tone="duo" />
      <Headline f={f} lang={lang} text={copy.gateHead} sub={copy.gateSub} start={G + 6} end={CH.exp - 12} tone="duo" />
      <Picking f={f} lang={lang} />
      {hubOut > 0 && f >= S + 20 ? (
        <div style={{ opacity: ramp(f, S + 30, 14) }}>
          <Hub f={f} x={lerp(HUB.x, HUB2.x, move)} y={lerp(HUB.y, HUB2.y, move)} pulse={pulse} label={copy.router} />
        </div>
      ) : null}
      <Learning2 f={f} lang={lang} />
      <Gate f={f} lang={lang} />
    </>
  );
};
