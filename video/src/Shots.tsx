// 官网和 README 用的静态图：和宣传片同一套画面，换成适合网页的取景（圆角、透明底）
import React from "react";
import { AbsoluteFill } from "remotion";
import { COPY } from "./lib/copy";
import { C, FONT, GLOBAL_CSS, type Lang } from "./lib/theme";
import { DesktopViewport } from "./film/parts";
import { FilmFrame } from "./film/Film";
import { CH, T } from "./film/timeline";
import { AnswerCard, totalChars } from "./ui/AppUI";

type Desk = { kind: "desk"; w: number; h: number; f: number; cam: { fx: number; fy: number; z: number } };
type Crop = { kind: "crop"; w: number; h: number; f: number; x: number; y: number };

export const SHOTS: Record<string, Desk | Crop> = {
  see: { kind: "desk", w: 1600, h: 900, f: T.seeChips + 40, cam: { fx: 960, fy: 540, z: 1 } },
  ask: { kind: "desk", w: 1600, h: 900, f: T.askSources[2] + 50, cam: { fx: 960, fy: 540, z: 1 } },
  act: { kind: "desk", w: 1600, h: 1000, f: T.pillSteps[3] + 14, cam: { fx: 1400, fy: 760, z: 1.4 } },
  guide: { kind: "desk", w: 1600, h: 1000, f: T.guideBoxes[1] + 14, cam: { fx: 960, fy: 470, z: 1.5 } },
  route: { kind: "crop", w: 1720, h: 660, f: CH.route + 230, x: 100, y: 250 },
  learn: { kind: "crop", w: 1780, h: 660, f: CH.route + 450, x: 70, y: 256 },
  gate: { kind: "crop", w: 1320, h: 740, f: CH.route + 700, x: 300, y: 262 },
  lesson: { kind: "crop", w: 1640, h: 560, f: CH.exp + 224, x: 140, y: 280 },
  recall: { kind: "crop", w: 1790, h: 420, f: CH.exp + 630, x: 76, y: 290 },
  improve: { kind: "crop", w: 880, h: 760, f: CH.improve + 410, x: 520, y: 236 },
  personal: { kind: "crop", w: 1640, h: 420, f: CH.improve + 560, x: 140, y: 300 },
  community: { kind: "crop", w: 1320, h: 760, f: CH.community + 390, x: 300, y: 270 },
};

export const Shot: React.FC<{ name: string; lang: Lang }> = ({ name, lang }) => {
  const s = SHOTS[name];
  return (
    <AbsoluteFill style={{ background: "transparent" }}>
      <style>{GLOBAL_CSS}</style>
      <div style={{ position: "absolute", inset: 0, borderRadius: 28, overflow: "hidden", background: C.bg }}>
        {s.kind === "desk" ? (
          <DesktopViewport f={s.f} lang={lang} w={s.w} h={s.h} cam={s.cam} />
        ) : (
          <div style={{ position: "absolute", left: -s.x, top: -s.y, width: 1920, height: 1080 }}>
            <FilmFrame f={s.f} lang={lang} />
          </div>
        )}
        <div style={{ position: "absolute", inset: 0, borderRadius: 28, boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.10)" }} />
      </div>
    </AbsoluteFill>
  );
};

/** 分享链接时的预览图（1200×630） */
export const OgCard: React.FC<{ lang: Lang }> = ({ lang }) => {
  const copy = COPY[lang];
  return (
    <AbsoluteFill style={{ background: C.bg, overflow: "hidden" }}>
      <style>{GLOBAL_CSS}</style>
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: [
            `radial-gradient(620px 460px at 18% 12%, color-mix(in srgb, ${C.askA} 30%, transparent), transparent 70%)`,
            `radial-gradient(640px 520px at 92% 100%, color-mix(in srgb, ${C.askB} 28%, transparent), transparent 70%)`,
          ].join(","),
        }}
      />
      <div style={{ position: "absolute", left: 72, top: 92, display: "flex", alignItems: "center", gap: 18 }}>
        <div style={{ width: 40, height: 40, borderRadius: "50%", background: `linear-gradient(135deg, ${C.askA}, ${C.askB})`, boxShadow: `0 0 0 8px color-mix(in srgb, ${C.askA} 14%, transparent), 0 0 50px ${C.askB}` }} />
        <div style={{ fontFamily: FONT.display(lang), fontSize: 40, fontWeight: 700, color: C.text, letterSpacing: lang === "en" ? "-0.02em" : "0.04em" }}>{copy.name}</div>
      </div>
      <div style={{ position: "absolute", left: 72, top: 186, width: 560, fontFamily: FONT.display(lang), fontSize: lang === "en" ? 58 : 54, lineHeight: 1.12, fontWeight: 700, color: C.text, letterSpacing: lang === "en" ? "-0.03em" : "0.02em" }}>
        {lang === "en" ? (
          <>
            Press a key.
            <br />
            Say one thing.
            <br />
          </>
        ) : (
          <>
            按一个键，
            <br />
            说一句话，
            <br />
          </>
        )}
        <span style={{ background: `linear-gradient(90deg, ${C.askA}, ${C.askB} 60%, ${C.actB})`, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>
          {lang === "en" ? "Done." : "就办好。"}
        </span>
      </div>
      <div style={{ position: "absolute", left: 72, bottom: 70, fontFamily: FONT.display(lang), fontSize: 22, color: C.text2 }}>{copy.facts.join("  ·  ")}</div>
      <div style={{ position: "absolute", left: 600, top: 150, transform: "scale(0.92)", transformOrigin: "0 0" }}>
        <AnswerCard
          mode="ask"
          f={0}
          x={0}
          y={0}
          appear={-100}
          question={copy.coldQuestion}
          blocks={copy.coldAnswer}
          budget={totalChars(copy.coldAnswer)}
          thinking={false}
          followup={copy.followup}
          followupHint={copy.followupHint}
        />
      </div>
    </AbsoluteFill>
  );
};
