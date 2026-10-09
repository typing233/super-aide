// ⑪ 社区共建：你的改进 → 提交到主版本（只有代码）→ 审核合并 → 下次更新到每个人手里 → 越用越好
import React from "react";
import { COPY } from "../lib/copy";
import { bezier, easeIn, easeInOut, easeOut, lerp, ramp } from "../lib/anim";
import { C, FONT, UI, type Lang } from "../lib/theme";
import { Headline, panel } from "./parts";
import { CH } from "./timeline";

const S = CH.community;
const M = S + 220; // 第二拍：审核、合并、推送
const W = S + 420; // 第三拍：飞轮

const CENTER = { x: 960, y: 620 };
const RX = 560;
const RY = 268;
const N = 18;
const YOU = 13;

function node(i: number, rot: number) {
  const th = ((-90 + (i * 360) / N + rot) * Math.PI) / 180;
  return { x: CENTER.x + RX * Math.cos(th), y: CENTER.y + RY * Math.sin(th) };
}

// 第三拍里谁在什么时候交了改进（固定的顺序，每次渲染都一样）
const SENDERS = [3, 8, 15, 1, 11, 6, 16, 4, 9, 13];

export const Community: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  if (f < S || f > CH.recap + 10) return null;
  const copy = COPY[lang];
  const out = ramp(f, CH.recap - 16, 14, easeIn);
  const rot = f >= W ? (f - W) * 0.06 : 0;
  const nodes = Array.from({ length: N }, (_, i) => node(i, rot));
  const you = nodes[YOU];

  // 第一拍：你的改进变成一个 PR，飞向主版本
  const prA = ramp(f, S + 50, 16);
  const fly = ramp(f, S + 124, 40, easeInOut);
  const prPath = [[410, 810], [410, 660], [CENTER.x - 260, CENTER.y], [CENTER.x, CENTER.y]]; // 卡片中心走的路线
  const [prX, prY] = bezier(prPath, fly);
  const arrive = f >= S + 164 ? Math.max(0, 1 - (f - S - 164) / 22) : 0;

  // 第二拍：合并后一圈涟漪推到每个人
  const ripple = ramp(f, M + 80, 44, easeOut);
  const lit = (i: number) => {
    if (f < M + 80) return i === YOU ? 0.6 : 0;
    const d = Math.hypot((nodes[i].x - CENTER.x) / RX, (nodes[i].y - CENTER.y) / RY);
    return ramp(f, M + 80 + d * 40, 10);
  };
  const merged = ramp(f, M + 64, 12, easeOut);

  // 第三拍：不停有人交改进进来，主版本不停推出去
  const wheel = f >= W ? (f - W) % 48 : -1;
  const wavePulse = f >= W ? Math.max(0, 1 - wheel / 30) : 0;
  const centerPulse = Math.max(arrive, merged > 0 && f < M + 110 ? 1 - ramp(f, M + 80, 30) : 0, wavePulse * 0.8);

  return (
    <div style={{ position: "absolute", inset: 0, opacity: 1 - out, fontFamily: FONT.ui }}>
      <Headline f={f} lang={lang} text={copy.comHead} sub={copy.comSub} start={S + 6} end={M - 12} />
      <Headline f={f} lang={lang} text={copy.mergeHead} sub={copy.mergeSub} start={M + 6} end={W - 12} />
      <Headline f={f} lang={lang} text={copy.flyHead} sub={copy.flySub} start={W + 6} end={CH.recap - 12} tone="duo" />

      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {/* 每个人都连着主版本 */}
        {nodes.map((n, i) => (
          <line key={i} x1={CENTER.x} y1={CENTER.y} x2={n.x} y2={n.y} stroke={`rgba(155,107,255,${0.07 + 0.18 * lit(i)})`} strokeWidth={1.5} opacity={ramp(f, S + 14 + i, 12)} />
        ))}
        {/* 涟漪 */}
        {ripple > 0 && ripple < 1 ? (
          <ellipse cx={CENTER.x} cy={CENTER.y} rx={RX * 1.05 * ripple} ry={RY * 1.05 * ripple} fill="none" stroke={C.askB} strokeOpacity={0.7 * (1 - ripple)} strokeWidth={3} />
        ) : null}
        {f >= W
          ? [0, 1].map((k) => {
              const t = ((f - W + k * 24) % 48) / 48;
              return <ellipse key={k} cx={CENTER.x} cy={CENTER.y} rx={RX * 1.05 * t} ry={RY * 1.05 * t} fill="none" stroke={C.askB} strokeOpacity={0.45 * (1 - t)} strokeWidth={2} />;
            })
          : null}
        {/* 第三拍：从各处飞来的改进 */}
        {f >= W
          ? SENDERS.map((who, k) => {
              const at = W + k * 16;
              const t = ramp(f, at, 22, easeInOut);
              if (t <= 0 || t >= 1) return null;
              const n = nodes[who];
              return <circle key={k} cx={lerp(n.x, CENTER.x, t)} cy={lerp(n.y, CENTER.y, t)} r={6} fill="#fff" />;
            })
          : null}
      </svg>

      {/* 用户 */}
      {nodes.map((n, i) => {
        const a = ramp(f, S + 14 + i, 12);
        const isYou = i === YOU;
        const l = Math.max(lit(i), f >= W && SENDERS.indexOf(i) >= 0 && (f - W - SENDERS.indexOf(i) * 16) % 999 >= 0 ? 0.9 : 0);
        const r = isYou ? 19 : 14;
        return (
          <React.Fragment key={i}>
            <div
              style={{
                position: "absolute",
                left: n.x - r,
                top: n.y - r,
                width: r * 2,
                height: r * 2,
                borderRadius: "50%",
                background: l > 0 ? `linear-gradient(135deg, ${C.askA}, ${C.askB})` : "#262B3D",
                border: `1.5px solid ${isYou ? C.askA : "rgba(255,255,255,0.16)"}`,
                boxShadow: l > 0 ? `0 0 ${18 * l}px ${C.askB}` : undefined,
                opacity: a,
                transform: `scale(${0.6 + 0.4 * a})`,
              }}
            />
            {isYou ? (
              <div style={{ position: "absolute", left: n.x - 60, top: n.y + 26, width: 120, textAlign: "center", fontSize: 19, fontWeight: 600, color: UI.text, opacity: a }}>{copy.you}</div>
            ) : null}
          </React.Fragment>
        );
      })}

      {/* 主版本 */}
      <div style={{ position: "absolute", left: CENTER.x - 70, top: CENTER.y - 70, width: 140, height: 140, opacity: ramp(f, S + 20, 14) }}>
        <div
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: "50%",
            background: "radial-gradient(circle at 35% 30%, #2A2C36, #15161B)",
            border: "1px solid rgba(255,255,255,0.14)",
            boxShadow: `0 20px 50px rgba(0,0,0,0.5), 0 0 ${36 + 60 * centerPulse}px color-mix(in srgb, ${C.askB} ${Math.round(35 + 45 * centerPulse)}%, transparent)`,
            display: "grid",
            placeItems: "center",
          }}
        >
          <div style={{ width: 52, height: 52, borderRadius: "50%", background: `linear-gradient(135deg, ${C.askA}, ${C.askB})`, boxShadow: `0 0 34px ${C.askB}`, transform: `scale(${1 + 0.2 * centerPulse})` }} />
        </div>
        <div style={{ position: "absolute", left: -100, right: -100, top: 152, textAlign: "center", fontSize: 21, fontWeight: 600, color: UI.text }}>{copy.mainVersion}</div>
      </div>

      {/* 第一拍：PR 卡片 */}
      {f >= S + 50 && fly < 1 ? (
        <div
          style={{
            ...panel({ left: prX - 280, top: prY - 64, width: 560, padding: "18px 22px", borderRadius: 16 }),
            border: `1px solid color-mix(in srgb, ${C.askA} 50%, transparent)`,
            opacity: prA * (1 - ramp(f, S + 150, 14)),
            transform: `scale(${lerp(1, 0.25, fly)})`,
            transformOrigin: "50% 50%",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 19, fontWeight: 600 }}>
            <svg width={20} height={20} viewBox="0 0 20 20" fill="none" stroke={C.askA} strokeWidth={1.7} strokeLinecap="round">
              <circle cx="5" cy="4.5" r="2" />
              <circle cx="5" cy="15.5" r="2" />
              <circle cx="15" cy="15.5" r="2" />
              <path d="M5 6.5v7M15 13.5V9a3 3 0 0 0-3-3H9M10.5 4.5L9 6l1.5 1.5" />
            </svg>
            {copy.prTitle}
          </div>
          <div style={{ marginTop: 8, fontSize: 15, color: UI.text2 }}>{copy.prFrom}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12, fontSize: 15 }}>
            <span style={{ fontFamily: FONT.mono, color: UI.text3 }}>{copy.prStat}</span>
            <span style={{ flex: 1 }} />
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, height: 28, padding: "0 10px", borderRadius: 999, color: "#B9F3D2", border: `1px solid color-mix(in srgb, ${C.ok} 55%, transparent)`, opacity: ramp(f, S + 76, 12) }}>
              <svg width={14} height={14} viewBox="0 0 20 20" fill="none" stroke={C.ok} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
                <path d="M10 2.5l6 2.5v4.5c0 4-2.6 6.6-6 8-3.4-1.4-6-4-6-8V5z" />
                <path d="M7 10l2 2 4-4" />
              </svg>
              {copy.codeOnly}
            </span>
          </div>
        </div>
      ) : null}

      {/* 第二拍：审核三项 + 已合并 */}
      {f >= M ? (
        <div style={{ ...panel({ left: 1110, top: 470, width: 300, padding: "18px 22px", borderRadius: 16 }), opacity: ramp(f, M + 10, 12) * (1 - ramp(f, W - 10, 14)) }}>
          {copy.checks.map((t, i) => {
            const a = ramp(f, M + 16 + i * 14, 10);
            return (
              <div key={t} style={{ display: "flex", alignItems: "center", gap: 12, height: 40, fontSize: 19, opacity: a, transform: `translateX(${8 * (1 - a)}px)` }}>
                <span style={{ width: 24, height: 24, borderRadius: "50%", display: "grid", placeItems: "center", background: `color-mix(in srgb, ${C.ok} 20%, transparent)` }}>
                  <svg viewBox="0 0 20 20" width={15} height={15} style={{ fill: "none", stroke: C.ok, strokeWidth: 2.2, strokeLinecap: "round", strokeLinejoin: "round" }}>
                    <path d="M5 10.5l3.2 3.2L15 7" />
                  </svg>
                </span>
                {t}
              </div>
            );
          })}
        </div>
      ) : null}
      {/* PR 到了主版本：先是"审核中"，合并后换成"已合并" */}
      {f >= S + 166 && f < M + 70 ? (
        <div style={{ position: "absolute", left: CENTER.x - 100, top: CENTER.y - 150, width: 200, display: "flex", justifyContent: "center", opacity: ramp(f, S + 166, 12) * (1 - ramp(f, M + 60, 8)) }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8, height: 40, padding: "0 18px", borderRadius: 999, fontSize: 19, fontWeight: 600, color: UI.text, background: "rgba(255,255,255,0.08)", border: `1px solid color-mix(in srgb, ${C.askA} 55%, transparent)` }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: C.askA, opacity: 0.5 + 0.5 * Math.abs(Math.sin(f / 8)) }} />
            {copy.inReview}
          </span>
        </div>
      ) : null}
      {f >= M + 64 ? (
        <div style={{ position: "absolute", left: CENTER.x - 100, top: CENTER.y - 150, width: 200, display: "flex", justifyContent: "center", opacity: merged * (1 - ramp(f, W - 10, 14)), transform: `scale(${lerp(1.3, 1, merged)})` }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8, height: 40, padding: "0 18px", borderRadius: 999, fontSize: 19, fontWeight: 650, color: "#fff", background: `color-mix(in srgb, ${C.ok} 80%, #12301F)`, boxShadow: `0 0 30px color-mix(in srgb, ${C.ok} 45%, transparent)` }}>
            ✓ {copy.mergedLabel}
          </span>
        </div>
      ) : null}
      <div style={{ position: "absolute", left: 0, right: 0, top: 968, display: "flex", justifyContent: "center", opacity: ramp(f, M + 120, 16) * (1 - ramp(f, W - 10, 14)) }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 12, height: 52, padding: "0 24px", borderRadius: 999, fontSize: 21, color: UI.text, background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.10)" }}>
          <span style={{ color: C.askB }}>✦</span>
          {copy.proof}
        </span>
      </div>
    </div>
  );
};
