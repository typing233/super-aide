// 桌面上发生的一切（开场 → 看得见 → 串起几个窗口 → 操作 → 指引），按片子的帧号连续演下去。
// 一次只让观众看一处：聚光（其余变暗）+ 镜头推近 + 标签。
import React from "react";
import { COPY } from "../lib/copy";
import { bezier, bezierLength, clamp, easeIn, easeInOut, easeOut, lerp, ramp, track } from "../lib/anim";
import { C, FONT, UI, type Lang } from "../lib/theme";
import { AnswerCard, Cursor, GuideBox, InputBar, Pill, Toast, totalChars, typing } from "../ui/AppUI";
import { CH, T } from "../film/timeline";
import { ScanBeam, ScanProvider, Taskbar, Wallpaper } from "./Desktop";
import {
  Chat, CHAT, chatMsgY, DEST_RECT, Notes, NOTES, notesExtent, NotesGhost, notesLineY, PrintDialog, SAVE_RECT, Terminal, TERM, termLineY,
} from "./apps";

const BAR_X = TERM.x + TERM.w / 2 - 300; // 输入框出现在正在看的窗口下面、居中
const BAR_Y = TERM.y + TERM.h + 30;
const GUIDE_X = 660;
const GUIDE_Y = 680;

type Rect = { x: number; y: number; w: number; h: number };
const pad = (r: Rect, p: number): Rect => ({ x: r.x - p, y: r.y - p, w: r.w + 2 * p, h: r.h + 2 * p });

/** 桌面里的镜头：对准 (fx, fy)，放大 z 倍（1 = 整个桌面） */
export function deskCamera(f: number) {
  const keys: [number, number, number, number][] = [
    // 帧, fx, fy, z
    [CH.cold, 1000, 575, 1.42],
    [CH.see, 960, 540, 1],
    [T.seeScan + 40, 960, 540, 1],
    [T.spotTerm + 24, 1000, 430, 1.5],
    [T.spotChat - 6, 1000, 430, 1.5],
    [T.spotChat + 26, 1658, 380, 1.55],
    [T.spotNotes - 6, 1658, 380, 1.55],
    [T.spotNotes + 30, 330, 490, 1.32],
    [T.spotOff - 4, 330, 490, 1.32],
    [T.spotOff + 30, 960, 560, 1.06],
    [T.askKeys, 960, 560, 1.06],
    [T.askBar + 12, 1000, 650, 1.32],
    [T.askStream + T.askStreamDur + 6, 1000, 650, 1.32],
    [T.askSources[0] - 4, 960, 540, 1],
    [T.actKeys, 960, 540, 1],
    [T.actBar + 12, 1000, 570, 1.3],
    [T.pill + 22, 1700, 900, 2.0],
    [T.actToast + 24, 1700, 900, 2.0],
    [T.rerun + 10, 1240, 620, 1.22],
    [T.montage[0] - 6, 1240, 620, 1.22],
    [T.montage[0] + 14, 1420, 690, 1.32],
    [CH.guide + 4, 1420, 690, 1.32],
    [T.printOpen + 24, 960, 470, 1.18],
    [T.guideEnter + 10, 960, 460, 1.3],
    [CH.better, 960, 460, 1.3],
  ];
  const at = (i: number) => track(f, keys.map((k) => [k[0], k[i]] as [number, number]), easeInOut);
  return { fx: at(1), fy: at(2), z: at(3) };
}

// ---------- 聚光：目标之外都变暗，目标描一圈光 ----------

function spotlight(f: number, copy: ReturnType<typeof notesTargets>) {
  const cold = pad({ x: TERM.x, y: TERM.y, w: TERM.w, h: 690 }, 14);
  const term = pad(TERM, 12);
  const chat = pad(CHAT, 12);
  const notes = copy;
  const keys: [number, Rect][] = [
    [CH.cold, cold],
    [T.spotTerm - 20, cold],
    [T.spotTerm, term],
    [T.spotChat, term],
    [T.spotChat + 22, chat],
    [T.spotNotes, chat],
    [T.spotNotes + 24, notes],
  ];
  const k = (sel: (r: Rect) => number) => track(f, keys.map(([fr, r]) => [fr, sel(r)] as [number, number]), easeInOut);
  const rect = { x: k((r) => r.x), y: k((r) => r.y), w: k((r) => r.w), h: k((r) => r.h) };
  // 开场聚光，一进第 ③ 章换成逐个窗口，最后放开
  const amount =
    f < CH.reveal ? 1 - ramp(f, CH.reveal - 10, 10) : Math.min(ramp(f, T.spotTerm - 8, 14), 1 - ramp(f, T.spotOff, 16, easeIn));
  return { rect, amount };
}

const notesTargets = (lang: Lang) => {
  const ext = notesExtent(COPY[lang]);
  return { x: NOTES.x - 12, y: ext.top - 26, w: NOTES.w + 24, h: ext.bottom - ext.top + 52 };
};

const Spotlight: React.FC<{ rect: Rect; amount: number }> = ({ rect, amount }) => {
  if (amount <= 0) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: rect.x,
        top: rect.y,
        width: rect.w,
        height: rect.h,
        borderRadius: 16,
        pointerEvents: "none",
        boxShadow: [
          `0 0 0 2px color-mix(in srgb, ${C.askA} ${Math.round(70 * amount)}%, transparent)`,
          `0 0 46px 6px color-mix(in srgb, ${C.askB} ${Math.round(32 * amount)}%, transparent)`,
          `0 0 0 4000px rgba(5, 6, 11, ${0.64 * amount})`,
        ].join(","),
      }}
    />
  );
};

/** 聚光旁边的说明标签 */
const Label: React.FC<{ f: number; x: number; y: number; text: string; appear: number; leave: number; size?: number }> = ({ f, x, y, text, appear, leave, size = 19 }) => {
  if (f < appear || f > leave + 12) return null;
  const a = ramp(f, appear, 12) * (1 - ramp(f, leave, 10, easeIn));
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        display: "flex",
        alignItems: "center",
        gap: 10,
        height: size * 2,
        padding: `0 ${size * 0.85}px 0 ${size * 0.7}px`,
        borderRadius: 999,
        background: "rgba(22, 23, 30, 0.94)",
        border: `1px solid color-mix(in srgb, ${C.askA} 55%, transparent)`,
        boxShadow: `0 10px 30px rgba(0,0,0,0.45), 0 0 24px color-mix(in srgb, ${C.askB} 30%, transparent)`,
        fontFamily: FONT.ui,
        fontSize: size,
        fontWeight: 500,
        color: UI.text,
        whiteSpace: "nowrap",
        opacity: a,
        transform: `translateY(${8 * (1 - ramp(f, appear, 12, easeOut))}px)`,
      }}
    >
      <span style={{ width: size * 0.45, height: size * 0.45, borderRadius: "50%", background: `linear-gradient(135deg, ${C.askA}, ${C.askB})`, boxShadow: `0 0 10px ${C.askB}` }} />
      {text}
    </div>
  );
};

// ---------- ③ 读到了什么：三枚标签；按 Alt+Q 时飞进输入框的光点 ----------

const ChipIcon: React.FC<{ kind: number }> = ({ kind }) => (
  <svg width={16} height={16} viewBox="0 0 20 20" fill="none" stroke={C.askA} strokeWidth={1.6} strokeLinecap="round">
    {kind === 0 ? <path d="M3.5 5h13M3.5 10h13M3.5 15h8" /> : null}
    {kind === 1 ? (
      <>
        <rect x="3" y="4" width="14" height="12" rx="2" />
        <circle cx="10" cy="10" r="2.6" />
      </>
    ) : null}
    {kind === 2 ? <rect x="3.5" y="3.5" width="13" height="13" rx="1.5" strokeDasharray="2.6 2.4" /> : null}
  </svg>
);

const SeeChips: React.FC<{ f: number; labels: string[] }> = ({ f, labels }) => {
  if (f < T.seeChips || f > T.askBar + 12) return null;
  const orbX = BAR_X + 25;
  return (
    <div style={{ position: "absolute", left: TERM.x + TERM.w / 2, top: BAR_Y + 2, transform: "translateX(-50%)", display: "flex", gap: 12 }}>
      {labels.map((label, i) => {
        const a = ramp(f, T.seeChips + i * 8, 14);
        const fly = ramp(f, T.askKeys + 2 + i * 2, 10, easeIn);
        const cx = TERM.x + TERM.w / 2 + (i - 1) * 232;
        return (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              height: 40,
              padding: "0 16px 0 13px",
              borderRadius: 999,
              background: UI.surface,
              border: `1px solid color-mix(in srgb, ${C.askA} 35%, ${UI.stroke})`,
              boxShadow: `${UI.shadow}, 0 0 22px color-mix(in srgb, ${C.askB} 22%, transparent)`,
              fontFamily: FONT.ui,
              fontSize: 14,
              color: UI.text,
              whiteSpace: "nowrap",
              opacity: a * (1 - fly) * (1 - fly),
              transform: `translate(${(orbX - cx) * fly}px, ${10 * (1 - a)}px) scale(${lerp(1, 0.2, fly)})`,
            }}
          >
            <ChipIcon kind={i} />
            {label}
          </div>
        );
      })}
    </div>
  );
};

// ---------- ④ 回答的每一处都连回它出自哪个窗口 ----------

const SourceLinks: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  if (f < T.askSources[0] - 2 || f > CH.act + 10) return null;
  const out = 1 - ramp(f, CH.act - 10, 12, easeIn);
  const cardL = BAR_X;
  const cardR = BAR_X + 600;
  // 回答里三行的位置（卡片内：问题行 26 + 间距，正文 15px × 1.7）
  const lineY = [683, 756, 790];
  const errW = lang === "en" ? 410 : 410;
  const items = [
    { at: T.askSources[0], from: [cardL + 120, BAR_Y - 2], to: [TERM.x + 22 + errW / 2, termLineY(4) + 26], box: { x: TERM.x + 14, y: termLineY(4) - 2, w: errW, h: 28 }, tag: copy.sources[0], line: 0 },
    { at: T.askSources[1], from: [cardL - 4, lineY[1]], to: [NOTES.x + 360, notesLineY(1) + 13], box: { x: NOTES.x + 44, y: notesLineY(1) - 4, w: 316, h: 30 }, tag: copy.sources[1], line: 1 },
    { at: T.askSources[2], from: [cardR + 4, lineY[2]], to: [CHAT.x + 64, chatMsgY(0) + 18], box: { x: CHAT.x + 60, y: chatMsgY(0) - 4, w: 372, h: 50 }, tag: copy.sources[2], line: 2 },
  ];
  return (
    <div style={{ position: "absolute", inset: 0, opacity: out, pointerEvents: "none" }}>
      {items.map((it, i) => {
        const a = ramp(f, it.at, 18, easeInOut);
        if (f < it.at) return null;
        const [x0, y0] = it.from;
        const [x1, y1] = it.to;
        const p = i === 0 ? [[x0, y0], [x0, y0 - 80], [x1, y1 + 80], [x1, y1]] : [[x0, y0], [x0 + (x1 - x0) * 0.45, y0], [x1 + (x0 - x1) * 0.3, y1], [x1, y1]];
        const len = bezierLength(p);
        const [dx, dy] = bezier(p, a);
        const boxA = ramp(f, it.at + 14, 10);
        const pulse = f >= it.at + 14 ? Math.max(0, 1 - (f - it.at - 14) / 24) : 0;
        const [mx, my] = bezier(p, 0.5);
        return (
          <React.Fragment key={i}>
            <svg width={1920} height={1080} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
              <path
                d={`M${p[0][0]} ${p[0][1]} C${p[1][0]} ${p[1][1]} ${p[2][0]} ${p[2][1]} ${p[3][0]} ${p[3][1]}`}
                fill="none"
                stroke={`url(#src${i})`}
                strokeWidth={3}
                strokeLinecap="round"
                strokeDasharray={len}
                strokeDashoffset={len * (1 - a)}
              />
              <defs>
                <linearGradient id={`src${i}`} x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor={C.askA} />
                  <stop offset="1" stopColor={C.askB} />
                </linearGradient>
              </defs>
              <circle cx={x0} cy={y0} r={5} fill={C.askA} />
              {a < 1 ? <circle cx={dx} cy={dy} r={7} fill="#fff" /> : <circle cx={x1} cy={y1} r={5} fill={C.askB} />}
            </svg>
            <div
              style={{
                position: "absolute",
                left: it.box.x,
                top: it.box.y,
                width: it.box.w,
                height: it.box.h,
                borderRadius: 8,
                border: `2px solid ${C.askB}`,
                background: `color-mix(in srgb, ${C.askA} 18%, transparent)`,
                boxShadow: `0 0 ${16 + 30 * pulse}px color-mix(in srgb, ${C.askB} ${Math.round(45 + 40 * pulse)}%, transparent)`,
                opacity: boxA,
              }}
            />
            <Label f={f} x={mx + 14} y={my - 18} text={it.tag} appear={it.at + 16} leave={CH.act - 12} size={17} />
          </React.Fragment>
        );
      })}
    </div>
  );
};

/** 右下角的结果提示：新的从下面进来，旧的往上让 */
const ToastStack: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  const items = [{ at: T.actToast, title: copy.actToast }, ...copy.montage.map((title, i) => ({ at: T.montage[i], title }))];
  return (
    <>
      {items.map((it, k) => {
        if (f < it.at) return null;
        const pushed = items.slice(k + 1).reduce((s, later) => s + ramp(f, later.at, 14) * 88, 0);
        return (
          <Toast key={k} f={f} right={24} y={930 - pushed} width={380} appear={it.at} leave={CH.guide + 4 + (items.length - k) * 3} title={it.title} links={copy.toastLinks} />
        );
      })}
    </>
  );
};

export const DesktopShow: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  const ext = notesExtent(copy);
  const spot = spotlight(f, notesTargets(lang));

  // 召唤时，被看着的窗口描一圈模式色
  const askOutline = Math.max(
    Math.min(ramp(f, T.coldEnter - 58, 6), 1 - ramp(f, CH.reveal - 10, 10)),
    Math.min(ramp(f, T.askBar, 6), 1 - ramp(f, T.askSources[0] - 20, 10)),
  );
  const actOutline = Math.min(ramp(f, T.actBar, 6), 1 - ramp(f, T.actEnter + 8, 10));
  const outline = actOutline > 0 ? { mode: "act" as const, amount: actOutline } : { mode: "ask" as const, amount: askOutline };
  const dim = ramp(f, CH.guide, 14);

  // ① 开场
  const coldText = typing(f, T.coldType, copy.coldQuestion, 38);
  const coldTotal = totalChars(copy.coldAnswer);
  const coldT = clamp((f - T.coldStream) / T.coldStreamDur, 0, 1);

  // ④ 串起几个窗口
  const askText = typing(f, T.askType, copy.askQuestion, 44);
  const askTotal = totalChars(copy.askAnswer);
  const askT = clamp((f - T.askStream) / T.askStreamDur, 0, 1);

  // ⑤ 操作
  const actText = typing(f, T.actType, copy.actTask, 38);
  const step = T.pillSteps.filter((s) => f >= s).length - 1;
  const secs = Math.max(0, Math.floor(((f - T.pill) / 30) * 2.4));
  const steps = copy.actSteps.slice(0, step + 1).map((text, i) => ({ text, state: (i < step ? "done" : "now") as "done" | "now" }));
  const pillOpen = Math.min(ramp(f, T.pillOpen, 18, easeOut), 1 - ramp(f, T.pillClose, 10, easeIn));

  // ⑥ 指引
  const gText = typing(f, T.guideType, copy.guideQuestion, 32);
  const gTotal = totalChars(copy.guideAnswer);
  const gStream = clamp((f - (T.guideEnter + 8)) / 22, 0, 1);
  const printA = ramp(f, T.printOpen, 10);
  const cur = cursorPath(f);

  // 笔记滚出去的部分：第 ③ 章展开，第 ④ 章连线时再露出来
  const ghost = Math.max(ramp(f, T.unroll, 22) * (1 - ramp(f, T.askKeys, 12, easeIn)), ramp(f, T.askSources[1] - 12, 14) * (1 - ramp(f, CH.act - 10, 12, easeIn)));

  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 1080, overflow: "hidden", fontFamily: FONT.ui }}>
      <Wallpaper />
      <ScanProvider value={{ f, start: T.seeScan, speed: T.scanSpeed, top: 40, end: T.askKeys, enabled: f >= CH.see }}>
        <NotesGhost copy={copy} amount={ghost} />
        <Notes copy={copy} dim={dim} />
        <Chat copy={copy} dim={dim} />
        <Terminal f={f} copy={copy} rerunAt={T.rerun} outline={outline} dim={dim} />
      </ScanProvider>

      <ScanBeam f={f} start={T.seeScan} speed={T.scanSpeed} top={40} bottom={1032} />

      {/* ① 开场：问一句 */}
      <InputBar mode="ask" f={f} x={BAR_X} y={BAR_Y} appear={T.coldBar} leave={T.coldEnter} text={coldText} placeholder={copy.askPlaceholder} chip={copy.modeAsk} />
      <AnswerCard
        mode="ask"
        f={f}
        x={BAR_X}
        y={BAR_Y}
        appear={T.coldEnter + 1}
        leave={CH.reveal + 30}
        question={copy.coldQuestion}
        status={f < T.coldStream ? copy.thinking : undefined}
        blocks={copy.coldAnswer}
        budget={coldT * coldTotal}
        thinking={coldT < 1}
        streaming={coldT > 0 && coldT < 1}
        followup={copy.followup}
        followupHint={copy.followupHint}
      />

      <Spotlight rect={spot.rect} amount={spot.amount} />

      {/* ③ 一个窗口一个窗口地读 */}
      <Label f={f} x={TERM.x} y={TERM.y - 56} text={copy.seeLabels[0]} appear={T.spotTerm + 16} leave={T.spotChat} />
      <Label f={f} x={CHAT.x} y={CHAT.y + CHAT.h + 18} text={copy.seeLabels[1]} appear={T.spotChat + 30} leave={T.spotNotes} />
      <Label f={f} x={NOTES.x} y={ext.bottom + 36} text={copy.seeLabels[2]} appear={T.unroll + 20} leave={T.spotOff} />
      <SeeChips f={f} labels={copy.seeChips} />

      {/* ④ 一句话串起几个窗口 */}
      <InputBar mode="ask" f={f} x={BAR_X} y={BAR_Y} appear={T.askBar} leave={T.askEnter} text={askText} placeholder={copy.askPlaceholder} chip={copy.modeAsk} />
      <AnswerCard
        mode="ask"
        f={f}
        x={BAR_X}
        y={BAR_Y}
        appear={T.askEnter + 1}
        leave={CH.act + 2}
        question={copy.askQuestion}
        status={f < T.askStream ? copy.thinking : undefined}
        blocks={copy.askAnswer}
        budget={askT * askTotal}
        thinking={askT < 1}
        streaming={askT > 0 && askT < 1}
        followup={copy.followup}
        followupHint={copy.followupHint}
      />
      <SourceLinks f={f} lang={lang} />

      {/* ⑤ 操作 */}
      <InputBar mode="act" f={f} x={BAR_X} y={BAR_Y} appear={T.actBar} leave={T.actEnter} text={actText} placeholder={copy.actPlaceholder} chip={copy.modeAct} />
      <Pill
        mode="act"
        f={f}
        right={24}
        bottom={60}
        appear={T.pill}
        leave={T.actToast - 2}
        text={step >= 0 ? copy.actSteps[step] : copy.thinking}
        time={`0:${String(secs).padStart(2, "0")}`}
        note={copy.pillNote}
        noteFade={T.pillClose - 6}
        open={pillOpen}
        task={copy.actTask}
        steps={steps}
        escHint={copy.escHint}
      />
      <ToastStack f={f} lang={lang} />

      {/* ⑥ 指引：打印对话框 */}
      {f >= T.printOpen ? (
        <PrintDialog copy={copy} pdf={f >= T.click1 + 2} style={{ opacity: printA, transform: `translateY(${10 * (1 - printA)}px) scale(${0.98 + 0.02 * printA})` }} />
      ) : null}
      <InputBar mode="ask" f={f} x={GUIDE_X} y={GUIDE_Y} appear={T.guideBar} leave={T.guideEnter} text={gText} placeholder={copy.askPlaceholder} chip={copy.modeAsk} />
      <AnswerCard
        mode="ask"
        f={f}
        x={GUIDE_X}
        y={GUIDE_Y}
        appear={T.guideEnter + 1}
        question={copy.guideQuestion}
        status={gStream <= 0 ? copy.thinking : undefined}
        blocks={copy.guideAnswer}
        budget={gStream * gTotal}
        thinking={gStream < 1}
        streaming={gStream > 0 && gStream < 1}
        followup={copy.followup}
        followupHint={copy.followupHint}
      />
      <GuideBox f={f} {...DEST_RECT} n={1} label={copy.guideLabels[0]} appear={T.guideBoxes[0]} leave={T.click1 + 4} />
      <GuideBox f={f} {...SAVE_RECT} n={2} label={copy.guideLabels[1]} appear={T.guideBoxes[1]} leave={T.click2 + 4} />
      {cur ? <Cursor f={f} x={cur.x} y={cur.y} clicks={[T.click1, T.click2]} opacity={cur.o} /> : null}

      <Taskbar clock={copy.clock} lang={copy.lang} search={copy.search} active="terminal" trayGlow={Math.max(pulse(f, T.coldKeys + 5), pulse(f, T.askKeys + 5), pulse(f, T.actKeys + 5))} />
    </div>
  );
};

const pulse = (f: number, at: number) => (f < at ? 0 : Math.max(0, 1 - (f - at) / 20));

function cursorPath(f: number) {
  const start = T.click1 - 30;
  if (f < start || f > CH.better + 4) return null;
  const p1 = { x: DEST_RECT.x + DEST_RECT.w * 0.55, y: DEST_RECT.y + DEST_RECT.h * 0.55 };
  const p2 = { x: SAVE_RECT.x + SAVE_RECT.w * 0.5, y: SAVE_RECT.y + SAVE_RECT.h * 0.55 };
  const t1 = ramp(f, start, 26, easeInOut);
  const t2 = ramp(f, T.click1 + 8, 22, easeInOut);
  const x = lerp(lerp(1330, p1.x, t1), p2.x, t2);
  const y = lerp(lerp(940, p1.y, t1), p2.y, t2);
  return { x, y, o: ramp(f, start, 6) * (1 - ramp(f, CH.better - 8, 8)) };
}
