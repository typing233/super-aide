// 应用界面的复刻：尺寸、颜色、圆角、阴影、动效都照 src/super_aide/ui/web/style.css（深色主题）
import React from "react";
import type { Block, Run } from "../lib/copy";
import { blink, clamp, easeIn, easeOut, ramp } from "../lib/anim";
import { accent, C, FONT, UI, type Mode } from "../lib/theme";

const surface = (extra: React.CSSProperties = {}): React.CSSProperties => ({
  position: "absolute",
  background: UI.surface,
  border: `1px solid ${UI.stroke}`,
  boxShadow: UI.shadow,
  backdropFilter: "blur(28px) saturate(1.5)",
  color: UI.text,
  fontFamily: FONT.ui,
  ...extra,
});

/** 出现：0.98 → 1、下移 4px → 0；离开：淡出、略缩小（照 style.css 的 appear / leave） */
export function appearStyle(f: number, start: number, end = Infinity): React.CSSProperties {
  const a = ramp(f, start, 8);
  const l = ramp(f, end, 6, easeIn);
  const scale = (0.98 + 0.02 * a) * (1 - 0.015 * l);
  return {
    opacity: a * (1 - l),
    transform: `translateY(${4 * (1 - a)}px) scale(${scale})`,
  };
}

export const Orb: React.FC<{ mode: Mode; f: number; breathe?: boolean; size?: number }> = ({ mode, f, breathe, size = 10 }) => {
  const [a, b] = accent(mode);
  const phase = breathe ? (1 - Math.cos((f / 48) * Math.PI * 2)) / 2 : 0; // 1.6 秒一呼吸
  return (
    <span
      style={{
        flex: "none",
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: "50%",
        background: `linear-gradient(135deg, ${a}, ${b})`,
        boxShadow: `0 0 0 ${size * 0.3}px color-mix(in srgb, ${a} 16%, transparent), 0 0 ${size * 1.4}px color-mix(in srgb, ${b} 50%, transparent)`,
        transform: `scale(${1 - 0.28 * phase})`,
        opacity: 1 - 0.35 * phase,
      }}
    />
  );
};

/** 思考中：模式色的光沿描边流动（2.4 秒一圈） */
export const ThinkingGlow: React.FC<{ mode: Mode; f: number; opacity?: number }> = ({ mode, f, opacity = 1 }) => {
  const [a, b] = accent(mode);
  const angle = (f * 5) % 360;
  return (
    <div
      style={{
        position: "absolute",
        inset: -1,
        padding: 1.5,
        borderRadius: "inherit",
        background: `conic-gradient(from ${angle}deg, transparent 0deg, transparent 150deg, ${a} 220deg, ${b} 280deg, transparent 340deg)`,
        WebkitMask: "linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)",
        WebkitMaskComposite: "xor",
        maskComposite: "exclude",
        opacity,
        pointerEvents: "none",
      }}
    />
  );
};

const Caret: React.FC<{ mode: Mode; f: number; thin?: boolean }> = ({ mode, f, thin }) => {
  const [a, b] = accent(mode);
  return (
    <span
      style={{
        display: "inline-block",
        width: thin ? 1.5 : 2,
        height: "1.05em",
        marginLeft: thin ? 1 : 2,
        verticalAlign: "-0.16em",
        borderRadius: 1,
        background: thin ? a : `linear-gradient(${a}, ${b})`,
        opacity: blink(f),
      }}
    />
  );
};

const Chip: React.FC<{ mode: Mode; label: string }> = ({ mode, label }) => {
  const [a] = accent(mode);
  return (
    <span
      style={{
        flex: "none",
        fontSize: 12,
        lineHeight: 1,
        padding: "6px 10px",
        borderRadius: 999,
        color: `color-mix(in srgb, ${a} 70%, ${UI.text})`,
        background: `color-mix(in srgb, ${a} 13%, transparent)`,
      }}
    >
      {label}
    </span>
  );
};

// ---------- ① 输入框 ----------

export const InputBar: React.FC<{
  mode: Mode;
  f: number;
  x: number;
  y: number;
  appear: number;
  leave?: number;
  text: string;
  placeholder: string;
  chip: string;
  focused?: boolean;
}> = ({ mode, f, x, y, appear, leave, text, placeholder, chip, focused = true }) => {
  if (f < appear) return null;
  return (
    <div
      style={surface({
        left: x,
        top: y,
        width: 600,
        height: 56,
        borderRadius: 14,
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "0 14px 0 20px",
        ...appearStyle(f, appear, leave),
      })}
    >
      <Orb mode={mode} f={f} />
      <span style={{ flex: 1, minWidth: 0, fontSize: 16, whiteSpace: "nowrap", overflow: "hidden" }}>
        {text ? (
          <span style={{ color: UI.text }}>{text}</span>
        ) : (
          <span style={{ color: UI.text3 }}>{placeholder}</span>
        )}
        {focused && text ? <Caret mode={mode} f={f} thin /> : null}
      </span>
      <Chip mode={mode} label={chip} />
    </div>
  );
};

// ---------- ② 回答卡片 ----------

function sliceRuns(runs: Run[], budget: number): [Run[], number] {
  const out: Run[] = [];
  for (const r of runs) {
    if (budget <= 0) break;
    const chars = Array.from(r.t);
    out.push({ ...r, t: chars.slice(0, budget).join("") });
    budget -= chars.length;
  }
  return [out, budget];
}

/** 按字数预算渲染回答（流式输出）；budget = Infinity 表示全部显示 */
export const Rich: React.FC<{ blocks: Block[]; budget: number; mode: Mode; f: number; streaming: boolean; fontSize?: number }> = ({
  blocks,
  budget,
  mode,
  f,
  streaming,
  fontSize = 15,
}) => {
  const rendered: React.ReactNode[] = [];
  let left = budget;
  let caretPlaced = false;
  blocks.forEach((block, i) => {
    if (left <= 0) return;
    const total = block.runs.reduce((s, r) => s + Array.from(r.t).length, 0);
    const [runs, rest] = sliceRuns(block.runs, left);
    left = rest;
    const isLast = left <= 0 || i === blocks.length - 1;
    const showCaret = streaming && isLast && !caretPlaced;
    if (showCaret) caretPlaced = true;
    const content = (
      <>
        {runs.map((r, k) => (
          <span key={k} style={{ fontWeight: r.b ? 600 : undefined }}>
            {r.t}
          </span>
        ))}
        {showCaret && Array.from(runs.map((r) => r.t).join("")).length <= total ? <Caret mode={mode} f={f} /> : null}
      </>
    );
    if (block.kind === "pre") {
      rendered.push(
        <div
          key={i}
          style={{
            margin: "8px 0 10px",
            marginLeft: "1.6em",
            padding: "11px 44px 11px 14px",
            borderRadius: 10,
            background: UI.codeBg,
            color: UI.codeText,
            fontFamily: FONT.mono,
            fontSize: fontSize * 0.9,
            lineHeight: 1.55,
            whiteSpace: "pre",
          }}
        >
          {content}
        </div>,
      );
    } else if (block.kind === "li") {
      rendered.push(
        <div key={i} style={{ display: "flex", margin: "4px 0" }}>
          <span style={{ width: "1.6em", flex: "none", color: UI.text3, paddingLeft: 2 }}>{block.n}.</span>
          <span>{content}</span>
        </div>,
      );
    } else {
      rendered.push(
        <div key={i} style={{ margin: "0 0 10px", color: block.muted ? UI.text2 : undefined }}>
          {content}
        </div>,
      );
    }
  });
  return <div style={{ fontSize, lineHeight: 1.7 }}>{rendered}</div>;
};

export const totalChars = (blocks: Block[]) =>
  blocks.reduce((s, b) => s + b.runs.reduce((t, r) => t + Array.from(r.t).length, 0), 0);

export const AnswerCard: React.FC<{
  mode: Mode;
  f: number;
  x: number;
  y: number;
  appear: number;
  leave?: number;
  question: string;
  status?: string;
  blocks?: Block[];
  budget?: number;
  thinking: boolean;
  streaming?: boolean;
  followup: string;
  followupHint: string;
  width?: number;
  children?: React.ReactNode;
}> = ({ mode, f, x, y, appear, leave, question, status, blocks, budget = 0, thinking, streaming, followup, followupHint, width = 600, children }) => {
  if (f < appear) return null;
  const shimmerPos = 100 - ((f % 54) / 54) * 200;
  return (
    <div style={surface({ left: x, top: y, width, borderRadius: 16, padding: "16px 20px 14px", ...appearStyle(f, appear, leave) })}>
      {thinking ? <ThinkingGlow mode={mode} f={f} /> : null}
      <div style={{ display: "flex", alignItems: "center", minHeight: 26 }}>
        <span style={{ flex: 1, minWidth: 0, fontSize: 13, color: UI.text2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {question}
        </span>
      </div>
      {children}
      {status ? (
        <div
          style={{
            marginTop: 8,
            fontSize: 13,
            minHeight: 20,
            background: `linear-gradient(90deg, ${UI.text3} 0%, ${UI.text} 45%, ${UI.text3} 90%)`,
            backgroundSize: "200% 100%",
            backgroundPosition: `${shimmerPos}% 0`,
            WebkitBackgroundClip: "text",
            backgroundClip: "text",
            color: "transparent",
          }}
        >
          {status}
        </div>
      ) : null}
      {blocks && budget > 0 ? (
        <div style={{ marginTop: 8 }}>
          <Rich blocks={blocks} budget={budget} mode={mode} f={f} streaming={Boolean(streaming)} />
        </div>
      ) : null}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12, paddingTop: 12, borderTop: `1px solid ${UI.divider}` }}>
        <Orb mode={mode} f={f} />
        <span style={{ flex: 1, fontSize: 15, color: UI.text3 }}>{followup}</span>
        <span style={{ fontSize: 12, color: UI.text3, whiteSpace: "nowrap" }}>{followupHint}</span>
      </div>
    </div>
  );
};

// ---------- ③ 操作中的胶囊 ----------

export const Pill: React.FC<{
  mode: Mode;
  f: number;
  right: number;
  y: number;
  appear: number;
  leave?: number;
  text: string;
  time: string;
  note?: string;
  noteFade?: number;
}> = ({ mode, f, right, y, appear, leave, text, time, note, noteFade = Infinity }) => {
  if (f < appear) return null;
  return (
    <div style={{ position: "absolute", right, top: y, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8, ...appearStyle(f, appear, leave) }}>
      <div
        style={surface({
          position: "relative",
          display: "inline-flex",
          alignItems: "center",
          gap: 10,
          height: 40,
          padding: "0 16px 0 15px",
          borderRadius: 999,
          fontSize: 13.5,
          whiteSpace: "nowrap",
        })}
      >
        <Orb mode={mode} f={f} breathe />
        <span style={{ maxWidth: 420, overflow: "hidden", textOverflow: "ellipsis" }}>{text}</span>
        <span style={{ color: UI.text3, fontVariantNumeric: "tabular-nums" }}>{time}</span>
      </div>
      {note ? (
        <div
          style={surface({
            position: "relative",
            padding: "6px 12px",
            borderRadius: 999,
            fontSize: 12.5,
            color: UI.text2,
            whiteSpace: "nowrap",
            opacity: 1 - ramp(f, noteFade, 12),
          })}
        >
          {note}
        </div>
      ) : null}
    </div>
  );
};

// ---------- ④ 结果提示 ----------

export const Toast: React.FC<{
  f: number;
  right?: number;
  left?: number;
  y: number;
  appear: number;
  leave?: number;
  title: string;
  links: string[];
  failed?: boolean;
  stopped?: boolean;
  width?: number;
  reasons?: string[];
  chosen?: number;
  chosenAt?: number;
  thanks?: string;
}> = ({ f, right, left, y, appear, leave, title, links, stopped, width = 340, reasons, chosen = -1, chosenAt = Infinity, thanks }) => {
  if (f < appear) return null;
  const tone = stopped ? UI.text2 : C.ok;
  const answered = f >= chosenAt + 10;
  return (
    <div
      style={surface({
        left,
        right,
        top: y,
        width,
        display: "flex",
        alignItems: "flex-start",
        gap: 12,
        padding: "14px 18px 14px 14px",
        borderRadius: 16,
        ...appearStyle(f, appear, leave),
      })}
    >
      <span
        style={{
          flex: "none",
          width: 24,
          height: 24,
          display: "grid",
          placeItems: "center",
          borderRadius: "50%",
          color: tone,
          background: stopped ? UI.hover : `color-mix(in srgb, ${C.ok} 16%, transparent)`,
        }}
      >
        {stopped ? (
          <span style={{ width: 7, height: 7, border: `1.5px solid ${UI.text2}`, borderRadius: 1.5 }} />
        ) : (
          <svg viewBox="0 0 20 20" width={16} height={16} style={{ fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" }}>
            <path d="M5 10.5l3.2 3.2L15 7" />
          </svg>
        )}
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 14, lineHeight: "24px" }}>{answered && thanks ? thanks : title}</div>
        <div style={{ display: "flex", gap: 6, marginTop: 2, fontSize: 12.5, color: UI.text3 }}>
          <span style={{ color: UI.text2 }}>{links[0]}</span>
          <span>·</span>
          <span style={{ color: UI.text2 }}>{links[1]}</span>
        </div>
        {reasons && !answered ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
            {reasons.map((r, i) => {
              const on = i === chosen && f >= chosenAt;
              return (
                <span
                  key={i}
                  style={{
                    fontSize: 13,
                    padding: "5px 12px",
                    borderRadius: 999,
                    background: on ? `color-mix(in srgb, ${C.askA} 22%, transparent)` : UI.hover,
                    color: on ? UI.text : UI.text2,
                    boxShadow: on ? `inset 0 0 0 1px color-mix(in srgb, ${C.askA} 55%, transparent)` : undefined,
                  }}
                >
                  {r}
                </span>
              );
            })}
          </div>
        ) : null}
      </div>
    </div>
  );
};

// ---------- 屏幕指引：圈出要点的地方 ----------

export const GuideBox: React.FC<{ f: number; x: number; y: number; w: number; h: number; n: number; label: string; appear: number; leave?: number }> = ({
  f,
  x,
  y,
  w,
  h,
  n,
  label,
  appear,
  leave = Infinity,
}) => {
  if (f < appear) return null;
  const a = ramp(f, appear, 10);
  const out = ramp(f, leave, 8, easeIn);
  const grow = 1 + 0.08 * (1 - ramp(f, appear, 12));
  const labelPop = clamp(ramp(f, appear + 4, 10), 0, 1);
  return (
    <div style={{ position: "absolute", left: x - 3, top: y - 3, width: w + 6, height: h + 6, opacity: a * (1 - out), transform: `scale(${grow})` }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: 8,
          border: `3px solid ${C.askA}`,
          boxShadow: `0 0 0 3px color-mix(in srgb, ${C.askA} 22%, transparent), 0 0 18px color-mix(in srgb, ${C.askA} 55%, transparent)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 0,
          top: -28,
          height: 22,
          padding: "0 8px",
          borderRadius: 11,
          background: "rgba(155, 107, 255, 0.94)",
          color: "#fff",
          fontFamily: '"Microsoft YaHei UI", "Segoe UI", sans-serif',
          fontWeight: 700,
          fontSize: 13,
          lineHeight: "22px",
          whiteSpace: "nowrap",
          transform: `translateY(${6 * (1 - labelPop)}px)`,
          opacity: labelPop,
        }}
      >
        {n}&nbsp;&nbsp;{label}
      </div>
    </div>
  );
};

// ---------- 鼠标指针（用户自己点） ----------

export const Cursor: React.FC<{ f: number; x: number; y: number; clicks?: number[]; opacity?: number }> = ({ f, x, y, clicks = [], opacity = 1 }) => {
  const press = clicks.reduce((m, c) => Math.max(m, f >= c && f < c + 8 ? 1 - Math.abs(f - c - 3) / 5 : 0), 0);
  return (
    <div style={{ position: "absolute", left: x, top: y, opacity, pointerEvents: "none" }}>
      {clicks.map((c, i) => {
        const t = ramp(f, c, 16, easeOut);
        if (f < c || t >= 1) return null;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: -18,
              top: -18,
              width: 36,
              height: 36,
              borderRadius: "50%",
              border: `2px solid ${C.askA}`,
              transform: `scale(${0.3 + 0.9 * t})`,
              opacity: 1 - t,
            }}
          />
        );
      })}
      <svg width={24} height={30} viewBox="0 0 24 30" style={{ transform: `scale(${1 - 0.12 * Math.max(0, press)})`, transformOrigin: "2px 2px", filter: "drop-shadow(0 2px 3px rgba(0,0,0,0.45))" }}>
        <path d="M2 2 L2 23 L7.5 18 L11 26.5 L14.5 25 L11 16.8 L18.5 16.8 Z" fill="#fff" stroke="#111" strokeWidth={1.4} strokeLinejoin="round" />
      </svg>
    </div>
  );
};
