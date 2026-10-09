// 桌面上的几个应用窗口：终端、团队聊天、笔记、打印对话框（都是普通窗口，助手不需要专门适配）
import React from "react";
import type { Copy } from "../lib/copy";
import { blink, typed } from "../lib/anim";
import { C, FONT, type Mode } from "../lib/theme";
import { Glyph, ScanLine, Win } from "./Desktop";

// ---------- 终端 ----------

export const TERM = { x: 590, y: 250, w: 820, h: 340 };
const TERM_LINE = 24;
const termLineY = (i: number) => TERM.y + 36 + 18 + i * TERM_LINE;

type TermLine = { text: string; color?: string; prompt?: boolean };

export const Terminal: React.FC<{
  f: number;
  copy: Copy;
  rerunAt: number;
  outline?: { mode: Mode; amount: number };
  dim?: number;
}> = ({ f, copy, rerunAt, outline, dim }) => {
  const red = "#FF6B6B";
  const lines: TermLine[] = [
    { text: "python analysis.py", prompt: true },
    { text: "Traceback (most recent call last):", color: red },
    { text: '  File "C:\\work\\analysis.py", line 3, in <module>', color: red },
    { text: "    import pandas as pd", color: red },
    { text: "ModuleNotFoundError: No module named 'pandas'", color: red },
  ];
  // 修好之后，你自己再跑一遍
  const cmd = typed(f, rerunAt, "python analysis.py", 34);
  const out1 = f >= rerunAt + 26;
  const out2 = f >= rerunAt + 34;
  const done = f >= rerunAt + 42;
  lines.push({ text: cmd, prompt: true });
  if (out1) lines.push({ text: "Loaded 12,480 rows from sales.csv", color: "#7EE2A8" });
  if (out2) lines.push({ text: "Saved report.xlsx  (3 sheets, 1.2 MB)", color: "#7EE2A8" });
  if (done) lines.push({ text: "", prompt: true });
  const cursorLine = lines.length - 1;
  return (
    <Win {...TERM} title={copy.terminalTab} icon={Glyph.terminal} bodyBg="#0E0F13" titleBg="#202127" outline={outline} dim={dim}>
      <div style={{ padding: "18px 22px", fontFamily: FONT.mono, fontSize: 16, lineHeight: `${TERM_LINE}px`, color: "#E9EAEE", whiteSpace: "pre" }}>
        {lines.map((l, i) => (
          <div key={i}>
            <ScanLine absY={termLineY(i)}>
              {l.prompt ? <span style={{ color: "rgba(255,255,255,0.55)" }}>PS C:\work&gt; </span> : null}
              <span style={{ color: l.color }}>{l.text}</span>
              {i === cursorLine ? <span style={{ display: "inline-block", width: 9, height: 18, verticalAlign: -3, marginLeft: 1, background: "#E9EAEE", opacity: blink(f) }} /> : null}
            </ScanLine>
          </div>
        ))}
      </div>
    </Win>
  );
};

// ---------- 团队聊天 ----------

export const CHAT = { x: 1436, y: 110, w: 444, h: 520 };

export const Chat: React.FC<{ copy: Copy; dim?: number }> = ({ copy, dim }) => {
  const colors = ["#E9775D", "#5B8CFF", "#E9775D"];
  let y = CHAT.y + 36 + 64;
  return (
    <Win {...CHAT} title={copy.chat.title} icon={Glyph.chat} bodyBg="#1C1B22" titleBg="#25242D" dim={dim}>
      <div style={{ height: 50, display: "flex", alignItems: "center", padding: "0 20px", borderBottom: "1px solid rgba(255,255,255,0.07)", fontSize: 15, fontWeight: 600 }}>
        <ScanLine absY={CHAT.y + 36 + 14}>{copy.chat.channel}</ScanLine>
      </div>
      <div style={{ padding: "14px 20px", display: "flex", flexDirection: "column", gap: 18 }}>
        {copy.chat.msgs.map(([who, text], i) => {
          const top = y;
          y += 92;
          return (
            <div key={i} style={{ display: "flex", gap: 12 }}>
              <div style={{ flex: "none", width: 34, height: 34, borderRadius: "50%", background: colors[i], display: "grid", placeItems: "center", fontSize: 14, fontWeight: 600 }}>
                {who.slice(0, 1)}
              </div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 3 }}>
                  <ScanLine absY={top}>
                    {who} <span style={{ fontWeight: 400, color: "rgba(255,255,255,0.4)", marginLeft: 6 }}>{["9:41", "9:43", "9:44"][i]}</span>
                  </ScanLine>
                </div>
                <ScanLine absY={top + 22} block>
                  <span style={{ fontSize: 14, lineHeight: "22px", color: "rgba(255,255,255,0.84)" }}>{text}</span>
                </ScanLine>
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", left: 18, right: 18, bottom: 16, height: 40, borderRadius: 8, background: "rgba(255,255,255,0.06)", display: "flex", alignItems: "center", padding: "0 14px", fontSize: 13, color: "rgba(255,255,255,0.4)" }}>
        {copy.chat.input}
      </div>
    </Win>
  );
};

// ---------- 笔记：内容比窗口长，有一截滚动到了窗口外 ----------

export const NOTES = { x: 70, y: 330, w: 500, h: 300 };
const NOTE_SCROLL = 128;
const NOTE_LINE = 32;
const notesTop = NOTES.y + 36 + 16 - NOTE_SCROLL; // 笔记内容（含滚出去的部分）在桌面上的顶端
export const notesExtent = (copy: Copy) => ({ top: notesTop, bottom: notesTop + 50 + copy.notes.lines.length * NOTE_LINE + 10 });

const NotesDoc: React.FC<{ copy: Copy; ghost?: boolean }> = ({ copy, ghost }) => (
  <div style={{ padding: "0 26px", fontFamily: FONT.ui, color: ghost ? "rgba(255,255,255,0.85)" : "rgba(255,255,255,0.88)" }}>
    <div style={{ height: 50, fontSize: 21, fontWeight: 600 }}>
      <ScanLine absY={notesTop + 6}>{copy.notes.head}</ScanLine>
    </div>
    {copy.notes.lines.map((l, i) => (
      <div key={i} style={{ height: NOTE_LINE, fontSize: 15, display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ width: 13, height: 13, flex: "none", borderRadius: 3, border: "1.5px solid rgba(255,255,255,0.35)", background: i < 3 ? "#5B8CFF" : undefined, borderColor: i < 3 ? "#5B8CFF" : undefined }} />
        <ScanLine absY={notesTop + 50 + i * NOTE_LINE + 4}>{l}</ScanLine>
      </div>
    ))}
  </div>
);

export const Notes: React.FC<{ copy: Copy; dim?: number }> = ({ copy, dim }) => (
  <Win {...NOTES} title={copy.notes.title} icon={Glyph.notes} bodyBg="#202024" titleBg="#29292E" dim={dim}>
    <div style={{ position: "absolute", left: 0, right: 0, top: 16 - NOTE_SCROLL }}>
      <NotesDoc copy={copy} />
    </div>
    {/* 滚动条：说明还有内容在外面 */}
    <div style={{ position: "absolute", right: 4, top: 46, width: 4, height: 110, borderRadius: 2, background: "rgba(255,255,255,0.22)" }} />
  </Win>
);

/** 笔记滚出窗口的部分：画在窗口后面，窗口上下露出来（amount 0→1 展开） */
export const NotesGhost: React.FC<{ copy: Copy; amount: number }> = ({ copy, amount }) => {
  if (amount <= 0) return null;
  const ext = notesExtent(copy);
  return (
    <div style={{ position: "absolute", left: NOTES.x, top: ext.top - 14, width: NOTES.w, height: ext.bottom - ext.top + 28 }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: 12,
          border: `1.5px dashed color-mix(in srgb, ${C.askA} 70%, transparent)`,
          background: "rgba(20, 22, 34, 0.55)",
          opacity: amount,
        }}
      />
      <div style={{ position: "absolute", left: 0, right: 0, top: 14, opacity: amount, clipPath: `inset(${(1 - amount) * 45}% 0 ${(1 - amount) * 45}% 0)` }}>
        <NotesDoc copy={copy} ghost />
      </div>
    </div>
  );
};

// ---------- 打印对话框（"教我怎么做"那一段） ----------

export const PRINT = { x: 560, y: 90, w: 800, h: 560 };
const PANEL_X = PRINT.x + 420 + 24;
export const DEST_RECT = { x: PANEL_X + 120, y: PRINT.y + 36 + 96 + 10, w: 212, h: 34 };
export const SAVE_RECT = { x: PRINT.x + PRINT.w - 24 - 96 - 10 - 96, y: PRINT.y + PRINT.h - 24 - 36, w: 96, h: 36 };

const Select: React.FC<{ value: string }> = ({ value }) => (
  <div
    style={{
      width: 212,
      height: 34,
      borderRadius: 6,
      background: "#2B2C33",
      border: "1px solid rgba(255,255,255,0.10)",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "0 12px",
      fontSize: 13.5,
    }}
  >
    <span>{value}</span>
    <svg width={10} height={10} viewBox="0 0 10 10" fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth={1.3}>
      <path d="M1.5 3.5L5 7l3.5-3.5" />
    </svg>
  </div>
);

export const PrintDialog: React.FC<{ copy: Copy; pdf: boolean; style?: React.CSSProperties }> = ({ copy, pdf, style }) => {
  const p = copy.print;
  const values = [pdf ? p.pdf : p.values[0], ...p.values.slice(1)];
  return (
    <Win {...PRINT} title={p.doc} icon={Glyph.doc} bodyBg="#1F2026" titleBg="#27282F" style={style}>
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 420, background: "#2A2B32", display: "grid", placeItems: "center" }}>
        <div style={{ width: 290, height: 376, background: "#FBFBFC", borderRadius: 3, boxShadow: "0 8px 24px rgba(0,0,0,0.35)", padding: "26px 24px", color: "#1D1F26", fontFamily: FONT.ui }}>
          <div style={{ fontSize: 15, fontWeight: 700 }}>{p.doc}</div>
          <div style={{ height: 6, width: 120, background: "#D9DCE3", borderRadius: 3, marginTop: 10 }} />
          <div style={{ display: "flex", alignItems: "flex-end", gap: 12, height: 120, marginTop: 24, padding: "0 8px", borderBottom: "1.5px solid #C9CCD5" }}>
            {[52, 70, 61, 88, 79, 104].map((h, i) => (
              <div key={i} style={{ flex: 1, height: h, borderRadius: "3px 3px 0 0", background: i === 5 ? "#5B8CFF" : "#AFC4F2" }} />
            ))}
          </div>
          {[200, 230, 170, 215, 140].map((w, i) => (
            <div key={i} style={{ height: 6, width: w, background: "#E1E3E9", borderRadius: 3, marginTop: 12 }} />
          ))}
        </div>
      </div>
      <div style={{ position: "absolute", left: 420, right: 0, top: 0, bottom: 0, padding: 24 }}>
        <div style={{ fontSize: 21, fontWeight: 600 }}>{p.title}</div>
        <div style={{ fontSize: 13, color: "rgba(255,255,255,0.55)", marginTop: 4 }}>{p.sheets}</div>
        <div style={{ marginTop: 18 }}>
          {p.rows.map((label, i) => (
            <div key={i} style={{ height: 54, display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ width: 110, fontSize: 13.5, color: "rgba(255,255,255,0.7)" }}>{label}</span>
              <Select value={values[i]} />
            </div>
          ))}
        </div>
        <div style={{ marginTop: 10, fontSize: 13.5, color: "#8FB0FF" }}>{p.more} ⌄</div>
        <div style={{ position: "absolute", right: 24, bottom: 24, display: "flex", gap: 10 }}>
          <div style={{ width: 96, height: 36, borderRadius: 6, background: "#4C8DFF", display: "grid", placeItems: "center", fontSize: 14, fontWeight: 600, color: "#fff" }}>
            {pdf ? p.save : p.print}
          </div>
          <div style={{ width: 96, height: 36, borderRadius: 6, background: "#33343C", display: "grid", placeItems: "center", fontSize: 14 }}>{p.cancel}</div>
        </div>
      </div>
    </Win>
  );
};
