// ⑨ 经验：走了弯路才总结 → 相似的合并、没用的淘汰 → 只在情况相符时想起（说"你好"一条也不带）
import React from "react";
import { COPY } from "../lib/copy";
import { bezier, clamp, easeIn, easeInOut, easeOut, lerp, ramp } from "../lib/anim";
import { C, FONT, UI, type Lang } from "../lib/theme";
import { AnswerCard, InputBar, Orb, totalChars, typing } from "../ui/AppUI";
import { Headline, panel } from "./parts";
import { CH } from "./timeline";

const S = CH.exp;
const B = S + 240; // 第二拍：不是越堆越多
const R = S + 480; // 第三拍：只在相似时想起

const CONVO = { x: 170, y: 300, w: 760, h: 520 };
const LESSON = { x: 1010, y: 320, w: 740, h: 470 };
const GRID = { x: 164, y: 300, cw: 380, ch: 96, gx: 24, gy: 20 };
const LESSON_SLOT = 5;
const DROP_SLOT = 11;
const slotXY = (i: number) => ({ x: GRID.x + (i % 4) * (GRID.cw + GRID.gx), y: GRID.y + Math.floor(i / 4) * (GRID.ch + GRID.gy) });
// 第三拍：左边是放大的输入框和回答（1.3 倍），右边是缩小的经验库
const Q = { x: 110, y: 330, s: 1.3 };
const LIB_S = 0.55;
const LIB_X = 960;
const LIB_Y = 360;

const RoleIcon: React.FC<{ role: string; f: number }> = ({ role, f }) => {
  if (role === "aide") return <Orb mode="ask" f={f} size={12} />;
  if (role === "fail")
    return (
      <span style={{ width: 22, height: 22, borderRadius: "50%", display: "grid", placeItems: "center", background: `color-mix(in srgb, ${C.err} 18%, transparent)` }}>
        <svg viewBox="0 0 20 20" width={14} height={14} style={{ fill: "none", stroke: C.err, strokeWidth: 2.2, strokeLinecap: "round" }}>
          <path d="M10 5.5v5.5M10 14.2v.3" />
        </svg>
      </span>
    );
  return (
    <span style={{ width: 22, height: 22, borderRadius: "50%", display: "grid", placeItems: "center", background: "rgba(255,255,255,0.10)" }}>
      <svg viewBox="0 0 20 20" width={13} height={13} style={{ fill: "none", stroke: "rgba(255,255,255,0.8)", strokeWidth: 1.7, strokeLinecap: "round" }}>
        <circle cx="10" cy="7" r="3.2" />
        <path d="M4 17c1-3.2 3.3-4.8 6-4.8s5 1.6 6 4.8" />
      </svg>
    </span>
  );
};

// ---------- 第一拍：走了弯路的对话 → 一条经验 ----------

const Convo: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  const a = ramp(f, S + 10, 16) * (1 - ramp(f, B - 16, 18, easeIn));
  if (a <= 0) return null;
  const rowsAt = [S + 20, S + 46, S + 70, S + 100, S + 128];
  const detour = ramp(f, S + 84, 14);
  return (
    <div style={{ ...panel({ left: CONVO.x, top: CONVO.y, width: CONVO.w, height: CONVO.h, padding: "26px 28px" }), opacity: a }}>
      {copy.convo.map(([role, text], i) => {
        const r = ramp(f, rowsAt[i], 12);
        const mono = role === "fail" || i === 0;
        return (
          <div key={i} style={{ position: "relative", display: "flex", alignItems: "center", gap: 14, minHeight: 74, opacity: r, transform: `translateY(${8 * (1 - r)}px)` }}>
            {i === 1 || i === 2 ? (
              <div style={{ position: "absolute", left: -14, right: -14, top: 4, bottom: 4, borderRadius: 12, background: `color-mix(in srgb, ${C.err} ${Math.round(9 * detour)}%, transparent)` }} />
            ) : null}
            <span style={{ position: "relative", flex: "none", width: 24, display: "grid", placeItems: "center" }}>
              <RoleIcon role={role} f={f} />
            </span>
            <span
              style={{
                position: "relative",
                fontFamily: mono ? FONT.mono : FONT.ui,
                fontSize: mono ? 18 : 20,
                color: role === "fail" || i === 0 ? "#FF8A8A" : i === 4 ? "#9BE9B9" : UI.text,
              }}
            >
              {text}
            </span>
          </div>
        );
      })}
      <div
        style={{
          position: "absolute",
          right: 22,
          top: 26 + 74 + 22,
          height: 30,
          padding: "0 12px",
          borderRadius: 999,
          display: "flex",
          alignItems: "center",
          fontSize: 15,
          color: "#FFB1B1",
          border: `1px solid color-mix(in srgb, ${C.err} 60%, transparent)`,
          opacity: detour,
        }}
      >
        {copy.detour}
      </div>
    </div>
  );
};

const LessonCard: React.FC<{ f: number; lang: Lang; compact?: number }> = ({ f, lang }) => {
  const copy = COPY[lang];
  const field = (at: number) => ({ opacity: ramp(f, at, 12), transform: `translateY(${8 * (1 - ramp(f, at, 12))}px)` });
  return (
    <div style={{ padding: "28px 32px" }}>
      <span style={{ display: "inline-flex", height: 30, alignItems: "center", padding: "0 14px", borderRadius: 999, fontSize: 15, fontWeight: 600, color: "#fff", background: `linear-gradient(135deg, ${C.askA}, ${C.askB})` }}>{copy.lessonTag}</span>
      <div style={{ marginTop: 18, fontSize: 27, fontWeight: 650, lineHeight: 1.3 }}>{copy.lessonTitle}</div>
      <div style={{ marginTop: 24, display: "grid", gridTemplateColumns: "78px 1fr", rowGap: 16, columnGap: 14, fontSize: 19, lineHeight: 1.45 }}>
        <span style={{ color: UI.text3, ...field(S + 168) }}>{copy.lessonWhenL}</span>
        <span style={field(S + 168)}>{copy.lessonWhen}</span>
        <span style={{ color: UI.text3, ...field(S + 180) }}>{copy.lessonDoL}</span>
        <span style={field(S + 180)}>{copy.lessonDo}</span>
        <span style={{ color: UI.text3, ...field(S + 192) }}>{copy.lessonCuesL}</span>
        <span style={{ display: "flex", flexWrap: "wrap", gap: 8, ...field(S + 192) }}>
          {copy.lessonCues.map((c) => (
            <span key={c} style={{ fontFamily: FONT.mono, fontSize: 15, padding: "4px 10px", borderRadius: 7, background: "rgba(255,255,255,0.07)" }}>
              {c}
            </span>
          ))}
        </span>
      </div>
    </div>
  );
};

// ---------- 经验库：一格一条 ----------

const LibCard: React.FC<{ text: string; meta?: string; style?: React.CSSProperties; highlight?: number; red?: number }> = ({ text, meta, style, highlight = 0, red = 0 }) => (
  <div
    style={{
      ...panel({ width: GRID.cw, height: GRID.ch, borderRadius: 14, padding: "14px 18px", boxShadow: "0 10px 30px rgba(0,0,0,0.35)" }),
      border: `1px solid ${red > 0 ? `color-mix(in srgb, ${C.err} ${Math.round(70 * red)}%, rgba(255,255,255,0.09))` : highlight > 0 ? `color-mix(in srgb, ${C.askA} ${Math.round(80 * highlight)}%, rgba(255,255,255,0.09))` : "rgba(255,255,255,0.09)"}`,
      boxShadow: highlight > 0 ? `0 0 ${36 * highlight}px color-mix(in srgb, ${C.askB} ${Math.round(55 * highlight)}%, transparent)` : "0 10px 30px rgba(0,0,0,0.35)",
      ...style,
    }}
  >
    <div style={{ fontSize: 17, lineHeight: 1.35, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{text}</div>
    {meta ? <div style={{ position: "absolute", left: 18, bottom: 10, fontSize: 13, color: red > 0 ? "#FFB1B1" : `color-mix(in srgb, ${C.askA} 60%, #fff)` }}>{meta}</div> : null}
  </div>
);

export const Experience: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  if (f < S || f > CH.improve + 10) return null;
  const copy = COPY[lang];
  const out = ramp(f, CH.improve - 16, 14, easeIn);

  // 第一拍 → 第二拍：经验卡缩小、放进经验库的一格
  const lessonIn = ramp(f, S + 150, 18, easeOut);
  const toSlot = ramp(f, B, 36, easeInOut);
  const slot = slotXY(LESSON_SLOT);
  // 第二拍 → 第三拍：整个经验库缩小移到右边
  const shrink = ramp(f, R - 10, 30, easeInOut);
  const gridScale = lerp(1, LIB_S, shrink);
  const gridX = lerp(0, LIB_X - GRID.x * LIB_S, shrink);
  const gridY = lerp(0, LIB_Y - GRID.y * LIB_S, shrink);

  const merged = f >= B + 92;
  const mergePulse = f >= B + 92 ? Math.max(0, 1 - (f - B - 92) / 24) : 0;
  const dropRed = ramp(f, B + 130, 12);
  const dropGone = ramp(f, B + 156, 24, easeIn);

  // 第三拍：想起来
  const qText = typing(f, R + 28, copy.recallQuestion, 40);
  const lit = ramp(f, R + 92, 10) * (1 - ramp(f, R + 160, 16));
  const scanX = lerp(-200, GRID.cw * 4 + 200, ramp(f, R + 76, 16, easeInOut));
  const answerT = clamp((f - (R + 122)) / 24, 0, 1);
  const hiText = typing(f, R + 166, copy.hi, 6);

  const cards = copy.libCards.slice(0, 15);
  const slots = Array.from({ length: 16 }, (_, i) => i).filter((i) => i !== LESSON_SLOT);

  return (
    <div style={{ position: "absolute", inset: 0, opacity: 1 - out, fontFamily: FONT.ui }}>
      <Headline f={f} lang={lang} text={copy.expHead} sub={copy.expSub} start={S + 6} end={B - 12} />
      <Headline f={f} lang={lang} text={copy.libHead} sub={copy.libSub} start={B + 6} end={R - 12} />
      <Headline f={f} lang={lang} text={copy.recallHead} sub={copy.recallSub} start={R + 6} end={CH.improve - 12} />

      <Convo f={f} lang={lang} />

      {/* 对话 → 经验：一串光点 */}
      {f >= S + 140 && f < S + 190
        ? Array.from({ length: 6 }, (_, k) => {
            const t = ramp(f, S + 140 + k * 4, 22, easeInOut);
            const [x, y] = bezier([[930, 560], [960, 470], [990, 640], [LESSON.x + 4, 540]], t);
            return t > 0 && t < 1 ? <div key={k} style={{ position: "absolute", left: x - 5, top: y - 5, width: 10, height: 10, borderRadius: "50%", background: "#fff", boxShadow: `0 0 14px ${C.askB}` }} /> : null;
          })
        : null}

      {/* 经验库 */}
      {f >= B - 4 ? (
        <div style={{ position: "absolute", inset: 0, transformOrigin: "0 0", transform: `translate(${gridX}px, ${gridY}px) scale(${gridScale})` }}>
          {cards.map((text, k) => {
            const i = slots[k];
            const { x, y } = slotXY(i);
            const a = ramp(f, B + 4 + k * 3, 12);
            const isDrop = i === DROP_SLOT;
            const dim = shrink > 0 ? 1 - 0.45 * shrink * (lit > 0 ? 1 : 0.6) : 1;
            if (isDrop && dropGone >= 1) {
              return <div key={k} style={{ position: "absolute", left: x, top: y, width: GRID.cw, height: GRID.ch, borderRadius: 14, border: "1.5px dashed rgba(255,255,255,0.12)" }} />;
            }
            return (
              <LibCard
                key={k}
                text={text}
                meta={isDrop && dropRed > 0 ? copy.libDropped : undefined}
                red={isDrop ? dropRed : 0}
                style={{ left: x, top: y, opacity: a * 0.72 * dim * (isDrop ? 1 - dropGone : 1), transform: `scale(${isDrop ? 1 - 0.1 * dropGone : 1})` }}
              />
            );
          })}
          {/* 刚学到的那条：从右边的大卡片缩进这一格 */}
          {f >= B ? (
            <LibCard
              text={copy.lessonTitle}
              meta={merged ? copy.libMerged : undefined}
              highlight={Math.max(0.6 * (1 - shrink), lit, mergePulse)}
              style={{ left: slot.x, top: slot.y, opacity: toSlot, transform: `scale(${1 + 0.06 * mergePulse + 0.04 * lit})` }}
            />
          ) : null}
          {/* 一条相似的经验飞进来，合并成一条 */}
          {f >= B + 50 && f < B + 96 ? (
            (() => {
              const t = ramp(f, B + 60, 32, easeInOut);
              const x = lerp(1400, slot.x, t);
              const y = lerp(820, slot.y, t);
              return (
                <LibCard
                  text={copy.lessonVariant}
                  meta={copy.similar}
                  highlight={0.7}
                  style={{ left: x, top: y, opacity: ramp(f, B + 50, 10) * (1 - ramp(f, B + 88, 8)), transform: `scale(${lerp(1, 0.9, t)})` }}
                />
              );
            })()
          ) : null}
          {/* 扫描：找这次的情况对得上的经验 */}
          {f >= R + 76 && f < R + 94 ? (
            <div style={{ position: "absolute", left: GRID.x + scanX - 60, top: GRID.y - 10, width: 120, height: 4 * GRID.ch + 3 * GRID.gy + 20, background: `linear-gradient(90deg, transparent, color-mix(in srgb, ${C.askA} 30%, transparent), transparent)` }} />
          ) : null}
        </div>
      ) : null}

      {/* 第一拍里的大经验卡（缩进经验库后就不画了） */}
      {f >= S + 150 && f < B + 36 ? (
        <div
          style={{
            ...panel({ left: lerp(LESSON.x, slot.x, toSlot), top: lerp(LESSON.y, slot.y, toSlot), width: lerp(LESSON.w, GRID.cw, toSlot), height: lerp(LESSON.h, GRID.ch, toSlot), overflow: "hidden" }),
            border: `1px solid color-mix(in srgb, ${C.askA} 55%, transparent)`,
            boxShadow: `0 30px 80px rgba(0,0,0,0.55), 0 0 40px color-mix(in srgb, ${C.askB} 25%, transparent)`,
            opacity: lessonIn * (1 - toSlot),
            transform: `scale(${0.94 + 0.06 * lessonIn})`,
          }}
        >
          <LessonCard f={f} lang={lang} />
        </div>
      ) : null}

      {/* 上限说明 */}
      <div style={{ position: "absolute", left: 0, right: 0, top: 790, textAlign: "center", fontSize: 21, color: UI.text2, opacity: ramp(f, B + 176, 14) * (1 - ramp(f, R - 10, 12)) }}>{copy.libCap}</div>

      {/* 第三拍：换个说法问，只亮起那一条 */}
      <div style={{ position: "absolute", left: Q.x, top: Q.y, transformOrigin: "0 0", transform: `scale(${Q.s})` }}>
        <InputBar mode="ask" f={f} x={0} y={0} appear={R + 20} leave={R + 74} text={qText} placeholder={copy.askPlaceholder} chip={copy.modeAsk} />
        <AnswerCard
          mode="ask"
          f={f}
          x={0}
          y={0}
          appear={R + 75}
          question={copy.recallQuestion}
          status={f >= R + 104 ? copy.recalled : f >= R + 75 ? copy.thinking : undefined}
          statusTone={f >= R + 104 ? "recall" : "shimmer"}
          blocks={copy.recallAnswer}
          budget={answerT * totalChars(copy.recallAnswer)}
          thinking={answerT < 1}
          streaming={answerT > 0 && answerT < 1}
          followup={copy.followup}
          followupHint={copy.followupHint}
        />
        {/* 说"你好"：一条也不带 */}
        <InputBar mode="ask" f={f} x={0} y={300} appear={R + 160} text={hiText} placeholder="" chip={copy.modeAsk} />
      </div>
      {/* 亮起的那条连到回答卡片的"想起以前的经验"那一行 */}
      {f >= R + 94 && f < R + 160
        ? (() => {
            const from = { x: LIB_X + (slot.x - GRID.x) * LIB_S, y: LIB_Y + (slot.y - GRID.y) * LIB_S + (GRID.ch * LIB_S) / 2 };
            const to = { x: Q.x + 600 * Q.s + 6, y: Q.y + 62 * Q.s };
            const p = [[from.x, from.y], [from.x - 90, from.y], [to.x + 70, to.y], [to.x, to.y]];
            const t = ramp(f, R + 94, 14, easeInOut);
            const [x, y] = bezier(p, t);
            return (
              <svg width={1920} height={1080} style={{ position: "absolute", inset: 0, opacity: 1 - ramp(f, R + 146, 14) }}>
                <path d={`M${p[0][0]} ${p[0][1]} C${p[1][0]} ${p[1][1]} ${p[2][0]} ${p[2][1]} ${p[3][0]} ${p[3][1]}`} fill="none" stroke={C.askB} strokeWidth={2.5} strokeDasharray="5 6" />
                {t < 1 ? <circle cx={x} cy={y} r={7} fill="#fff" /> : null}
              </svg>
            );
          })()
        : null}
      <div style={{ position: "absolute", left: LIB_X, top: LIB_Y + 4 * GRID.ch * LIB_S + 3 * GRID.gy * LIB_S + 26, fontSize: 22, color: UI.text, opacity: ramp(f, R + 100, 12) * (1 - ramp(f, R + 160, 12)) }}>
        <span style={{ color: `color-mix(in srgb, ${C.askA} 60%, #fff)` }}>●</span> {copy.oneRecalled}
      </div>
      <div style={{ position: "absolute", left: Q.x + 600 * Q.s + 30, top: Q.y + 300 * Q.s + 16, fontSize: 22, color: UI.text2, opacity: ramp(f, R + 176, 12) }}>
        <span style={{ color: UI.text3 }}>○</span> {copy.noneRecalled}
      </div>
    </div>
  );
};
