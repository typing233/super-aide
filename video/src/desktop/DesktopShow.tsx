// 桌面上发生的一切（看得见屏幕 → 问答 → 操作 → 指引），按片子的帧号连续演下去
import React from "react";
import { COPY } from "../lib/copy";
import { clamp, easeIn, easeInOut, lerp, ramp, track } from "../lib/anim";
import { C, FONT, UI, type Lang } from "../lib/theme";
import { AnswerCard, appearStyle, Cursor, GuideBox, InputBar, Pill, Toast, totalChars } from "../ui/AppUI";
import { T } from "../film/timeline";
import { ScanBeam, ScanProvider, Taskbar, Wallpaper } from "./Desktop";
import { Chat, DEST_RECT, Notes, NotesGhost, notesExtent, NOTES, PrintDialog, SAVE_RECT, Terminal, TERM } from "./apps";

const BAR_X = TERM.x + TERM.w / 2 - 300; // 输入框出现在正在看的窗口下面、居中
const BAR_Y = TERM.y + TERM.h + 30;
const GUIDE_X = 660;
const GUIDE_Y = 680;

/** 桌面里的镜头：对准 (fx, fy)，放大 z 倍（1 = 整个桌面） */
export function deskCamera(f: number) {
  const keys: [number, number, number, number][] = [
    // 帧, fx, fy, z
    [T.dock, 960, 540, 1],
    [T.scan, 960, 540, 1],
    [T.seeChips + 40, 960, 560, 1.06],
    [T.askBar + 6, 1000, 560, 1.3],
    [T.askEnter + 14, 1000, 650, 1.36],
    [T.act, 1000, 650, 1.36],
    [T.actBar + 10, 1000, 560, 1.3],
    [T.pillSteps[0] + 16, 1560, 880, 1.75],
    [T.pillSteps[2] + 4, 1560, 880, 1.75],
    [T.actToast - 4, 1400, 760, 1.42],
    [T.actToast + 10, 1400, 760, 1.42],
    [T.rerun + 10, 1240, 640, 1.22],
    [T.montage[0] + 10, 1420, 680, 1.32],
    [T.guide + 6, 1420, 680, 1.32],
    [T.printOpen + 20, 960, 470, 1.18],
    [T.guideEnter + 10, 960, 460, 1.3],
    [T.route, 960, 460, 1.3],
  ];
  const at = (i: number) => track(f, keys.map((k) => [k[0], k[i]] as [number, number]), easeInOut);
  return { fx: at(1), fy: at(2), z: at(3) };
}

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

/** 三枚"读到了什么"的小标签；按下 Alt+Q 时飞进输入框的光点 */
const SeeChips: React.FC<{ f: number; labels: string[] }> = ({ f, labels }) => {
  if (f < T.seeChips || f > T.askBar + 10) return null;
  const orbX = BAR_X + 20 + 5;
  const orbY = BAR_Y + 28;
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: BAR_Y + 2, height: 52 }}>
      <div style={{ position: "absolute", left: TERM.x + TERM.w / 2, top: 0, transform: "translateX(-50%)", display: "flex", gap: 12 }}>
        {labels.map((label, i) => {
          const a = ramp(f, T.seeChips + i * 6, 12);
          const fly = ramp(f, T.askKeys + 2 + i * 2, 10, easeIn);
          // 飞向光点：用相对自身中心的位移（近似，标签宽度按 220 估）
          const cx = TERM.x + TERM.w / 2 + (i - 1) * 232;
          const dx = (orbX - cx) * fly;
          const dy = (orbY - (BAR_Y + 28)) * fly;
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
                transform: `translate(${dx}px, ${dy + 10 * (1 - a)}px) scale(${lerp(1, 0.2, fly)})`,
              }}
            >
              <ChipIcon kind={i} />
              {label}
            </div>
          );
        })}
      </div>
    </div>
  );
};

/** 右下角的结果提示：新的从下面进来，旧的往上让 */
const ToastStack: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  const items = [
    { at: T.actToast, title: copy.toast },
    ...copy.montage.map((title, i) => ({ at: T.montage[i], title })),
  ];
  return (
    <>
      {items.map((it, k) => {
        if (f < it.at) return null;
        const pushed = items.slice(k + 1).reduce((s, later) => s + ramp(f, later.at, 12) * 88, 0);
        return (
          <Toast
            key={k}
            f={f}
            right={24}
            y={930 - pushed}
            width={372}
            appear={it.at}
            leave={T.guide + 2 + (items.length - k) * 2}
            title={it.title}
            links={copy.toastLinks}
          />
        );
      })}
    </>
  );
};

export const DesktopShow: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  const ext = notesExtent(copy);

  // 召唤时，被看着的窗口描一圈模式色
  const askOutline = Math.min(ramp(f, T.askBar, 6), 1 - ramp(f, T.act, 8));
  const actOutline = Math.min(ramp(f, T.actBar, 6), 1 - ramp(f, T.actEnter + 8, 10));
  const outline = actOutline > 0 ? { mode: "act" as const, amount: actOutline } : { mode: "ask" as const, amount: askOutline };
  const dim = ramp(f, T.guide, 14);

  // 问答
  const askCps = (Array.from(copy.askQuestion).length / 34) * 30;
  const askText = Array.from(copy.askQuestion).slice(0, Math.max(0, Math.floor(((f - T.askType) * askCps) / 30))).join("");
  const answerTotal = totalChars(copy.answer);
  const streamT = clamp((f - T.askStream) / T.askStreamDur, 0, 1);
  const askStatus = f < T.askStatus2 ? copy.askStatus[0] : f < T.askStream ? copy.askStatus[1] : undefined;

  // 操作
  const actCps = (Array.from(copy.actTask).length / 24) * 30;
  const actText = Array.from(copy.actTask).slice(0, Math.max(0, Math.floor(((f - T.actType) * actCps) / 30))).join("");
  const step = T.pillSteps.filter((s) => f >= s).length - 1;
  const secs = Math.max(0, Math.floor(((f - T.pillSteps[0]) / 30) * 2.6));

  // 指引
  const gCps = (Array.from(copy.guideQuestion).length / 28) * 30;
  const gText = Array.from(copy.guideQuestion).slice(0, Math.max(0, Math.floor(((f - T.guideType) * gCps) / 30))).join("");
  const gTotal = totalChars(copy.guideAnswer);
  const gStream = clamp((f - (T.guideEnter + 8)) / 22, 0, 1);
  const printA = ramp(f, T.printOpen, 10);
  const cur = cursorPath(f);

  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 1080, overflow: "hidden", fontFamily: FONT.ui }}>
      <Wallpaper />
      <ScanProvider value={{ f, start: T.scan, speed: T.scanSpeed, top: 40, end: T.askBar, enabled: true }}>
        <NotesGhost copy={copy} amount={ramp(f, T.unroll, 22) * (1 - ramp(f, T.askBar, 10, easeIn))} />
        <Notes copy={copy} dim={dim} />
        <Chat copy={copy} dim={dim} />
        <Terminal f={f} copy={copy} rerunAt={T.rerun} outline={outline} dim={dim} />
      </ScanProvider>

      {/* 滚出去的部分：标注 */}
      {f >= T.unroll + 10 && f < T.askBar + 12 ? (
        <div
          style={{
            position: "absolute",
            left: NOTES.x + 16,
            top: ext.bottom + 30,
            display: "flex",
            alignItems: "center",
            gap: 8,
            height: 32,
            padding: "0 14px",
            borderRadius: 999,
            background: `color-mix(in srgb, ${C.askA} 22%, rgba(20,20,26,0.9))`,
            border: `1px solid color-mix(in srgb, ${C.askA} 50%, transparent)`,
            fontSize: 14,
            color: UI.text,
            opacity: ramp(f, T.unroll + 10, 10) * (1 - ramp(f, T.askBar, 10)),
            transform: `translateY(${6 * (1 - ramp(f, T.unroll + 10, 10))}px)`,
          }}
        >
          <span style={{ fontSize: 13 }}>↕</span>
          {copy.unrolled}
        </div>
      ) : null}

      <ScanBeam f={f} start={T.scan} speed={T.scanSpeed} top={40} bottom={1032} />
      <SeeChips f={f} labels={copy.seeChips} />

      {/* 问答 */}
      <InputBar mode="ask" f={f} x={BAR_X} y={BAR_Y} appear={T.askBar} leave={T.askEnter} text={askText} placeholder={copy.askPlaceholder} chip={copy.modeAsk} />
      <AnswerCard
        mode="ask"
        f={f}
        x={BAR_X}
        y={BAR_Y}
        appear={T.askEnter + 1}
        leave={T.act + 2}
        question={copy.askQuestion}
        status={askStatus}
        blocks={copy.answer}
        budget={streamT * answerTotal}
        thinking={streamT < 1}
        streaming={streamT > 0 && streamT < 1}
        followup={copy.followup}
        followupHint={copy.followupHint}
      />

      {/* 操作 */}
      <InputBar mode="act" f={f} x={BAR_X} y={BAR_Y} appear={T.actBar} leave={T.actEnter} text={actText} placeholder={copy.actPlaceholder} chip={copy.modeAct} />
      <Pill mode="act" f={f} right={24} y={936} appear={T.pillSteps[0]} leave={T.actToast - 2} text={copy.pill[Math.max(0, step)]} time={`0:${String(secs).padStart(2, "0")}`} note={copy.pillNote} noteFade={T.pillSteps[3] + 10} />
      <ToastStack f={f} lang={lang} />

      {/* 指引：打印对话框 */}
      {f >= T.printOpen ? (
        <PrintDialog
          copy={copy}
          pdf={f >= T.click1 + 2}
          style={{ opacity: printA, transform: `translateY(${10 * (1 - printA)}px) scale(${0.98 + 0.02 * printA})` }}
        />
      ) : null}
      <InputBar mode="ask" f={f} x={GUIDE_X} y={GUIDE_Y} appear={T.guideBar} leave={T.guideEnter} text={gText} placeholder={copy.askPlaceholder} chip={copy.modeAsk} />
      <AnswerCard
        mode="ask"
        f={f}
        x={GUIDE_X}
        y={GUIDE_Y}
        appear={T.guideEnter + 1}
        question={copy.guideQuestion}
        status={gStream <= 0 ? copy.askStatus[0] : undefined}
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

      <Taskbar clock={copy.clock} lang={copy.lang} search={copy.search} active="terminal" trayGlow={Math.max(pulse(f, T.askKeys + 5), pulse(f, T.actKeys + 5))} />
    </div>
  );
};

const pulse = (f: number, at: number) => (f < at ? 0 : Math.max(0, 1 - (f - at) / 20));

function cursorPath(f: number) {
  const start = T.click1 - 26;
  if (f < start || f > T.route + 4) return null;
  const p1 = { x: DEST_RECT.x + DEST_RECT.w * 0.55, y: DEST_RECT.y + DEST_RECT.h * 0.55 };
  const p2 = { x: SAVE_RECT.x + SAVE_RECT.w * 0.5, y: SAVE_RECT.y + SAVE_RECT.h * 0.55 };
  const t1 = ramp(f, start, 22, easeInOut);
  const t2 = ramp(f, T.click1 + 6, 20, easeInOut);
  const x = lerp(lerp(1330, p1.x, t1), p2.x, t2);
  const y = lerp(lerp(940, p1.y, t1), p2.y, t2);
  return { x, y, o: ramp(f, start, 6) * (1 - ramp(f, T.route - 6, 8)) };
}

export { appearStyle };
