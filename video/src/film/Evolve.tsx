// 自我改进：你停下它、说它做错了 → 它找原因、改自己的代码、跑测试、复核 → 你点"生效"
import React from "react";
import { COPY } from "../lib/copy";
import { easeIn, easeInOut, lerp, ramp } from "../lib/anim";
import { C, FONT, UI, type Lang } from "../lib/theme";
import { Cursor, Orb, Toast } from "../ui/AppUI";
import { Headline } from "./parts";
import { T } from "./timeline";

const TOAST = { x: 150, y: 330, scale: 1.4, w: 500 };
const PANEL = { x: 980, y: 262, w: 760, h: 650 };
const APPLY_W = 112;
const APPLY = { x: PANEL.x + PANEL.w - 28 - APPLY_W / 2, y: PANEL.y + 402 };

const DIFF: [string, string?][] = [
  ["--- a/src/super_aide/shell/controller.py", "meta"],
  ["+++ b/src/super_aide/shell/controller.py", "meta"],
  ["@@ -340,6 +340,7 @@", "hunk"],
  ["     def _on_esc(self) -> None:"],
  ["         self.signals.stop()"],
  ["+        self._return_focus()", "add"],
  ["         if self.hub.is_busy(self.conv_key):"],
];

const StepIcon: React.FC<{ state: "todo" | "doing" | "done"; f: number }> = ({ state, f }) => {
  if (state === "done") {
    return (
      <span style={{ width: 24, height: 24, borderRadius: "50%", display: "grid", placeItems: "center", background: `color-mix(in srgb, ${C.ok} 20%, transparent)` }}>
        <svg viewBox="0 0 20 20" width={15} height={15} style={{ fill: "none", stroke: C.ok, strokeWidth: 2.2, strokeLinecap: "round", strokeLinejoin: "round" }}>
          <path d="M5 10.5l3.2 3.2L15 7" />
        </svg>
      </span>
    );
  }
  if (state === "doing") {
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
  }
  return <span style={{ width: 24, height: 24, borderRadius: "50%", border: "2px solid rgba(255,255,255,0.16)" }} />;
};

export const Evolve: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  if (f < T.evolve - 4 || f > T.outro + 10) return null;
  const copy = COPY[lang];
  const out = ramp(f, T.outro - 10, 14, easeIn);
  const toastA = ramp(f, T.stopToast, 12);
  const panelA = ramp(f, T.evolvePanel, 16);
  const ready = f >= T.evolveReady;
  const readyA = ramp(f, T.evolveReady, 12);
  const applied = f >= T.applyClick + 2;

  // 鼠标：先点"做错了"，再点"生效"
  const chipX = TOAST.x + (lang === "en" ? 100 : 82) * TOAST.scale;
  const chipY = TOAST.y + 86 * TOAST.scale;
  const t1 = ramp(f, T.stopClick - 22, 20, easeInOut);
  const t2 = ramp(f, T.applyClick - 30, 28, easeInOut);
  const cx = lerp(lerp(560, chipX, t1), APPLY.x, t2);
  const cy = lerp(lerp(780, chipY, t1), APPLY.y, t2);
  const cursorO = ramp(f, T.stopClick - 24, 6) * (1 - ramp(f, T.applyClick + 22, 8));

  return (
    <>
      <Headline f={f} lang={lang} text={copy.evolveHead} sub={copy.evolveSub} start={T.evolve + 4} end={T.outro - 12} tone="ask" />
      <div style={{ position: "absolute", inset: 0, opacity: 1 - out, fontFamily: FONT.ui }}>
        {/* 停下后问原因 */}
        <div style={{ position: "absolute", left: TOAST.x, top: TOAST.y, transformOrigin: "0 0", transform: `scale(${TOAST.scale}) translateY(${8 * (1 - toastA)}px)`, opacity: toastA }}>
          <Toast
            f={f}
            left={0}
            y={0}
            width={TOAST.w}
            appear={T.stopToast}
            title={copy.stopped}
            links={copy.toastLinks}
            stopped
            reasons={copy.stopChips}
            chosen={0}
            chosenAt={T.stopClick}
            thanks={copy.thanks}
          />
        </div>

        {/* 连线：从提示到自我改进面板 */}
        <svg width={1920} height={1080} style={{ position: "absolute", inset: 0, opacity: panelA }}>
          <path
            d={`M ${TOAST.x + TOAST.w * TOAST.scale + 12} ${TOAST.y + 60} C 920 ${TOAST.y + 60}, 900 ${PANEL.y + 160}, ${PANEL.x - 12} ${PANEL.y + 160}`}
            fill="none"
            stroke={`url(#evo)`}
            strokeWidth={2}
            strokeDasharray="5 8"
            strokeDashoffset={-f * 1.2}
          />
          <defs>
            <linearGradient id="evo" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor={C.askA} stopOpacity={0.2} />
              <stop offset="1" stopColor={C.askB} stopOpacity={0.9} />
            </linearGradient>
          </defs>
        </svg>

        {/* 自我改进面板（设置 → 高级 的样子） */}
        <div
          style={{
            position: "absolute",
            left: PANEL.x,
            top: PANEL.y,
            width: PANEL.w,
            height: PANEL.h,
            borderRadius: 20,
            background: "rgba(28, 28, 31, 0.95)",
            border: `1px solid ${UI.stroke}`,
            boxShadow: "0 30px 80px rgba(0,0,0,0.55)",
            color: UI.text,
            opacity: panelA,
            transform: `translateX(${36 * (1 - panelA)}px)`,
          }}
        >
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
              const startAt = i === 0 ? T.evolvePanel + 6 : T.evolveSteps[i - 1];
              const state = f >= T.evolveSteps[i] ? "done" : f >= startAt ? "doing" : "todo";
              return (
                <div key={i} style={{ height: 40, display: "flex", alignItems: "center", gap: 14, fontSize: 17, color: state === "todo" ? UI.text3 : UI.text }}>
                  <StepIcon state={state} f={f} />
                  {label}
                </div>
              );
            })}
          </div>

          <div style={{ position: "absolute", left: 28, right: 28, top: 380, height: 44, display: "flex", alignItems: "center", gap: 12, opacity: readyA, transform: `translateY(${6 * (1 - readyA)}px)` }}>
            <span style={{ width: 9, height: 9, borderRadius: "50%", background: applied ? C.ok : C.askA, boxShadow: `0 0 12px ${applied ? C.ok : C.askA}` }} />
            <span style={{ fontSize: 17, color: applied ? "#B9F3D2" : `color-mix(in srgb, ${C.askA} 60%, #fff)` }}>{applied ? copy.applied : copy.ready}</span>
            <span style={{ fontFamily: FONT.mono, fontSize: 14, padding: "4px 9px", borderRadius: 6, background: UI.hover, color: UI.text2 }}>0.2.0+aide.1</span>
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
                boxShadow: applied ? undefined : `0 6px 20px color-mix(in srgb, ${C.askB} 45%, transparent)`,
                transform: `scale(${f >= T.applyClick && f < T.applyClick + 6 ? 0.95 : 1})`,
              }}
            >
              {applied ? `✓ ${copy.applied}` : copy.apply}
            </span>
          </div>

          <div
            style={{
              position: "absolute",
              left: 28,
              right: 28,
              top: 444,
              padding: "12px 16px",
              borderRadius: 12,
              background: UI.codeBg,
              fontFamily: FONT.mono,
              fontSize: 14,
              lineHeight: "22px",
              whiteSpace: "pre",
              opacity: readyA,
            }}
          >
            {DIFF.map(([line, kind], i) => {
              const a = ramp(f, T.evolveReady + 6 + i * 3, 8);
              const color = kind === "meta" ? UI.text3 : kind === "hunk" ? "#8FB0FF" : kind === "add" ? "#9BE9B9" : UI.codeText;
              return (
                <div key={i} style={{ opacity: a, color, margin: "0 -16px", padding: "0 16px", background: kind === "add" ? "rgba(60, 203, 127, 0.14)" : undefined }}>
                  {line}
                </div>
              );
            })}
          </div>
        </div>

        {cursorO > 0 ? <Cursor f={f} x={cx} y={cy} clicks={[T.stopClick, T.applyClick]} opacity={cursorO} /> : null}
      </div>
    </>
  );
};
