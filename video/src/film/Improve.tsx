// ⑩ 自我改进：四种反馈 → 它改进自己的代码（你点"生效"）→ 你的应用由你塑造
import React from "react";
import { COPY } from "../lib/copy";
import { easeIn, easeInOut, lerp, ramp } from "../lib/anim";
import { C, FONT, UI, type Lang } from "../lib/theme";
import { AnswerCard, Cursor, Orb, Reasons, Rich, surface, Toast, typing } from "../ui/AppUI";
import { Headline, panel } from "./parts";
import { CH } from "./timeline";

const S = CH.improve;
const B = S + 210; // 第二拍：改自己的代码
const P = S + 450; // 第三拍：由你塑造

// 用户的建议改的是助手的回答规则（src/super_aide/workspace/AGENTS.md 里真实的那一行）
const DIFF: [string, string?][] = [
  ["--- a/src/super_aide/workspace/AGENTS.md", "meta"],
  ["+++ b/src/super_aide/workspace/AGENTS.md", "meta"],
  ["@@ -18,2 +18,2 @@", "hunk"],
  ["  - 第一句就是结论。"],
  ["- - 能短则短：简单问题 1～3 句；需要步骤时用编号列表，每步一行，最多 7 步。", "del"],
  ["+ - 能短则短：简单问题 1～2 句；需要步骤时用编号列表，每步一行，最多 5 步。", "add"],
];

const StepIcon: React.FC<{ state: "todo" | "doing" | "done"; f: number }> = ({ state, f }) => {
  if (state === "done")
    return (
      <span style={{ width: 24, height: 24, borderRadius: "50%", display: "grid", placeItems: "center", background: `color-mix(in srgb, ${C.ok} 20%, transparent)` }}>
        <svg viewBox="0 0 20 20" width={15} height={15} style={{ fill: "none", stroke: C.ok, strokeWidth: 2.2, strokeLinecap: "round", strokeLinejoin: "round" }}>
          <path d="M5 10.5l3.2 3.2L15 7" />
        </svg>
      </span>
    );
  if (state === "doing")
    return (
      <span
        style={{
          width: 24,
          height: 24,
          borderRadius: "50%",
          background: `conic-gradient(from ${f * 12}deg, transparent 0deg, ${C.askA} 200deg, ${C.askB} 300deg, transparent 360deg)`,
          WebkitMask: "radial-gradient(circle, transparent 8px, #000 8.5px)",
        }}
      />
    );
  return <span style={{ width: 24, height: 24, borderRadius: "50%", border: "2px solid rgba(255,255,255,0.16)" }} />;
};

// ---------- 第一拍：四种反馈 ----------

const Feedback: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  const out = ramp(f, B - 18, 18, easeIn);
  if (out >= 1) return null;
  const at = [S + 16, S + 32, S + 48, S + 64];
  // 收尾时四个都朝中间收，交给下一拍
  const gather = ramp(f, B - 26, 22, easeInOut);
  const toward = (x: number, y: number) => `translate(${(960 - x) * gather * 0.35}px, ${(600 - y) * gather * 0.35}px) scale(${1 - 0.12 * gather})`;
  const show = (i: number, x: number, y: number) => ({ opacity: ramp(f, at[i], 14), transform: `${toward(x, y)} translateY(${12 * (1 - ramp(f, at[i], 14))}px)` });
  const suggestion = typing(f, S + 90, copy.suggestText, 30);
  const submitted = f >= S + 132;
  return (
    <div style={{ position: "absolute", inset: 0, opacity: 1 - out, fontFamily: FONT.ui }}>
      {/* 任务没办成 */}
      <div style={{ position: "absolute", left: 160, top: 300, ...show(0, 500, 360) }}>
        <div style={{ transform: "scale(1.3)", transformOrigin: "0 0" }}>
          <Toast f={f} left={0} y={0} width={480} appear={at[0]} title={copy.failedToast} links={copy.toastLinks} tone="failed" />
        </div>
      </div>
      {/* 按 Esc 停下，说明原因 */}
      <div style={{ position: "absolute", left: 1000, top: 300, ...show(1, 1360, 380) }}>
        <div style={{ transform: "scale(1.3)", transformOrigin: "0 0" }}>
          <Toast f={f} left={0} y={0} width={520} appear={at[1]} title={copy.stopped} links={copy.toastLinks} tone="stopped" reasons={copy.stopChips} chosen={0} chosenAt={S + 76} thanks={copy.thanks} />
        </div>
      </div>
      {/* 👎 */}
      <div style={{ position: "absolute", left: 160, top: 560, ...show(2, 500, 680) }}>
        <div style={{ transform: "scale(1.22)", transformOrigin: "0 0" }}>
          <AnswerCard mode="ask" f={f} x={0} y={0} width={560} appear={at[2]} question={copy.badQuestion} thinking={false} rated="bad" followup={copy.followup} followupHint={copy.followupHint}>
            <Reasons f={f} reasons={copy.badChips} chosen={0} chosenAt={S + 86} prompt={copy.badPrompt} />
          </AnswerCard>
        </div>
      </div>
      {/* 设置里写一句建议 */}
      <div style={{ ...panel({ left: 1000, top: 580, width: 720, padding: "24px 26px" }), ...show(3, 1360, 700) }}>
        <div style={{ fontSize: 21 }}>{copy.suggestTitle}</div>
        <div style={{ marginTop: 14, height: 84, borderRadius: 12, padding: "14px 16px", background: "rgba(255,255,255,0.06)", border: `1px solid ${f >= S + 86 && !submitted ? `color-mix(in srgb, ${C.askA} 60%, transparent)` : "rgba(255,255,255,0.1)"}`, fontSize: 20 }}>
          {suggestion}
          {f >= S + 86 && !submitted ? <span style={{ display: "inline-block", width: 2, height: 22, marginLeft: 2, verticalAlign: -4, background: C.askA, opacity: Math.floor(f / 15) % 2 ? 0 : 1 }} /> : null}
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 14, marginTop: 14 }}>
          {submitted ? <span style={{ fontSize: 17, color: UI.text2, opacity: ramp(f, S + 136, 10) }}>{copy.thanks}</span> : null}
          <span
            style={{
              height: 42,
              padding: "0 20px",
              borderRadius: 10,
              display: "grid",
              placeItems: "center",
              fontSize: 18,
              fontWeight: 600,
              color: "#fff",
              background: `linear-gradient(135deg, ${C.askA}, ${C.askB})`,
              transform: `scale(${f >= S + 128 && f < S + 134 ? 0.95 : 1})`,
            }}
          >
            {copy.submit}
          </span>
        </div>
      </div>
      {f >= S + 104 && f < S + 150 ? <Cursor f={f} x={lerp(1500, 1650, ramp(f, S + 104, 22, easeInOut))} y={lerp(800, 780, ramp(f, S + 104, 22, easeInOut))} clicks={[S + 128]} /> : null}
    </div>
  );
};

// ---------- 第二拍：改进自己的代码（设置 → 高级 的样子） ----------

const PANEL = { x: 560, y: 262, w: 800, h: 700 };
const APPLY_W = 112;
const APPLY = { x: PANEL.x + PANEL.w - 28 - APPLY_W / 2, y: PANEL.y + 402 };

const Fix: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  if (f < B - 10 || f > P + 10) return null;
  const a = ramp(f, B, 18) * (1 - ramp(f, P - 14, 16, easeIn));
  const steps = [B + 26, B + 52, B + 78, B + 104];
  const ready = f >= B + 120;
  const readyA = ramp(f, B + 120, 12);
  const applyClick = B + 196;
  const applied = f >= applyClick + 2;
  const t = ramp(f, applyClick - 30, 26, easeInOut);
  return (
    <div style={{ position: "absolute", inset: 0, opacity: a, fontFamily: FONT.ui }}>
      <div style={{ ...panel({ left: PANEL.x, top: PANEL.y, width: PANEL.w, height: PANEL.h, borderRadius: 20 }), transform: `translateY(${16 * (1 - ramp(f, B, 18))}px)` }}>
        <div style={{ position: "absolute", left: 28, right: 28, top: 26, height: 40, display: "flex", alignItems: "center", gap: 14 }}>
          <Orb mode="ask" f={f} size={12} />
          <span style={{ flex: 1, fontSize: 25, fontWeight: 600 }}>{copy.evolveTitle}</span>
          <span style={{ width: 50, height: 28, borderRadius: 14, background: `linear-gradient(135deg, ${C.askA}, ${C.askB})`, position: "relative" }}>
            <span style={{ position: "absolute", right: 3, top: 3, width: 22, height: 22, borderRadius: 11, background: "#fff" }} />
          </span>
        </div>
        <div style={{ position: "absolute", left: 28, right: 28, top: 72, fontSize: 15, color: UI.text2, whiteSpace: "nowrap" }}>{copy.evolveNote}</div>
        <div style={{ position: "absolute", left: 0, right: 0, top: 116, height: 1, background: UI.divider }} />
        <div style={{ position: "absolute", left: 28, right: 28, top: 136, display: "flex", alignItems: "baseline", gap: 12 }}>
          <span style={{ flex: 1, fontSize: 21, fontWeight: 500, opacity: ready ? 1 : 0.5 }}>{ready ? copy.job : "…"}</span>
          <span style={{ fontSize: 14, color: UI.text3 }}>10:31</span>
        </div>
        <div style={{ position: "absolute", left: 28, right: 28, top: 170, fontSize: 15, color: UI.text2 }}>{copy.trigger}</div>
        <div style={{ position: "absolute", left: 28, right: 28, top: 206 }}>
          {copy.evolveSteps.map((label, i) => {
            const startAt = i === 0 ? B + 10 : steps[i - 1];
            const state = f >= steps[i] ? "done" : f >= startAt ? "doing" : "todo";
            return (
              <div key={i} style={{ height: 40, display: "flex", alignItems: "center", gap: 14, fontSize: 17, color: state === "todo" ? UI.text3 : UI.text }}>
                <StepIcon state={state} f={f} />
                {label}
              </div>
            );
          })}
        </div>
        <div style={{ position: "absolute", left: 28, right: 28, top: 380, height: 44, display: "flex", alignItems: "center", gap: 12, opacity: readyA }}>
          <span style={{ width: 9, height: 9, borderRadius: "50%", background: applied ? C.ok : C.askA, boxShadow: `0 0 12px ${applied ? C.ok : C.askA}` }} />
          <span style={{ fontSize: 17, color: applied ? "#B9F3D2" : `color-mix(in srgb, ${C.askA} 60%, #fff)` }}>{applied ? copy.applied : copy.ready}</span>
          <span style={{ fontFamily: FONT.mono, fontSize: 14, padding: "4px 9px", borderRadius: 6, background: UI.hover, color: UI.text2 }}>0.3.0+aide.1</span>
          <span style={{ flex: 1 }} />
          <span
            style={{
              width: APPLY_W,
              height: 44,
              borderRadius: 11,
              display: "grid",
              placeItems: "center",
              fontSize: 17,
              fontWeight: 600,
              color: "#fff",
              background: applied ? `color-mix(in srgb, ${C.ok} 75%, #1B1C20)` : `linear-gradient(135deg, ${C.askA}, ${C.askB})`,
              transform: `scale(${f >= applyClick && f < applyClick + 6 ? 0.95 : 1})`,
            }}
          >
            {applied ? `✓ ${copy.applied}` : copy.apply}
          </span>
        </div>
        <div style={{ position: "absolute", left: 28, right: 28, top: 444, padding: "12px 16px", borderRadius: 12, background: UI.codeBg, fontFamily: FONT.mono, fontSize: 14, lineHeight: "24px", whiteSpace: "pre", overflow: "hidden", opacity: readyA }}>
          {DIFF.map(([line, kind], i) => {
            const la = ramp(f, B + 126 + i * 4, 8);
            const color = kind === "meta" ? UI.text3 : kind === "hunk" ? "#8FB0FF" : kind === "add" ? "#9BE9B9" : kind === "del" ? "#FF9C9C" : UI.codeText;
            const bg = kind === "add" ? "rgba(60, 203, 127, 0.14)" : kind === "del" ? "rgba(255, 93, 93, 0.12)" : undefined;
            return (
              <div key={i} style={{ opacity: la, color, margin: "0 -16px", padding: "0 16px", background: bg }}>
                {line}
              </div>
            );
          })}
        </div>
        <div style={{ position: "absolute", left: 28, right: 28, top: 644, fontSize: 16, color: UI.text2, opacity: ramp(f, B + 152, 12) }}>{copy.diffGloss}</div>
      </div>
      {f >= applyClick - 32 && f < P - 10 ? <Cursor f={f} x={lerp(1240, APPLY.x, t)} y={lerp(930, APPLY.y, t)} clicks={[applyClick]} /> : null}
    </div>
  );
};

// ---------- 第三拍：以前 / 按你的建议改进后 ----------

const Personal: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  if (f < P - 4) return null;
  const out = ramp(f, CH.community - 16, 14, easeIn);
  const card = (i: number) => ({ opacity: ramp(f, P + 12 + i * 30, 16), transform: `translateY(${14 * (1 - ramp(f, P + 12 + i * 30, 16))}px)` });
  const Tag: React.FC<{ text: string; strong?: boolean }> = ({ text, strong }) => (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        height: 34,
        padding: "0 16px",
        borderRadius: 999,
        fontSize: 17,
        fontWeight: 600,
        color: strong ? "#fff" : UI.text2,
        background: strong ? `linear-gradient(135deg, ${C.askA}, ${C.askB})` : "rgba(255,255,255,0.07)",
      }}
    >
      {text}
    </span>
  );
  const Box: React.FC<{ x: number; blocks: typeof copy.longAnswer; dim?: boolean }> = ({ x, blocks, dim }) => (
    <div style={surface({ left: x, top: 380, width: 760, borderRadius: 18, padding: "20px 26px 18px", opacity: dim ? 0.78 : 1 })}>
      <div style={{ fontSize: 15, color: UI.text2 }}>{copy.badQuestion}</div>
      <div style={{ marginTop: 10 }}>
        <Rich blocks={blocks} budget={Infinity} mode="ask" f={f} streaming={false} fontSize={18} />
      </div>
    </div>
  );
  return (
    <div style={{ position: "absolute", inset: 0, opacity: 1 - out, fontFamily: FONT.ui }}>
      <div style={{ position: "absolute", left: 170, top: 320, ...card(0) }}>
        <Tag text={copy.before} />
      </div>
      <div style={card(0)}>
        <Box x={170} blocks={copy.longAnswer} dim />
      </div>
      <div style={{ position: "absolute", left: 990, top: 320, ...card(1) }}>
        <Tag text={copy.after} strong />
      </div>
      <div style={card(1)}>
        <Box x={990} blocks={copy.shortAnswer} />
      </div>
      <div style={{ position: "absolute", left: 990, top: 560, display: "flex", alignItems: "center", gap: 10, fontSize: 18, color: UI.text2, ...card(1) }}>
        <span style={{ fontFamily: FONT.mono, fontSize: 15, padding: "4px 10px", borderRadius: 7, background: "rgba(255,255,255,0.07)", color: UI.text }}>0.3.0+aide.1</span>
        {copy.trigger}
      </div>
    </div>
  );
};

export const Improve: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  if (f < S || f > CH.community + 10) return null;
  const copy = COPY[lang];
  return (
    <>
      <Headline f={f} lang={lang} text={copy.fbHead} sub={copy.fbSub} start={S + 6} end={B - 12} />
      <Headline f={f} lang={lang} text={copy.fixHead} sub={copy.fixSub} start={B + 6} end={P - 12} />
      <Headline f={f} lang={lang} text={copy.personalHead} sub={copy.personalSub} start={P + 6} end={CH.community - 12} />
      <Feedback f={f} lang={lang} />
      <Fix f={f} lang={lang} />
      <Personal f={f} lang={lang} />
    </>
  );
};
