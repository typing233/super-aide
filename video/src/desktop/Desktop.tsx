// 一台 Windows 桌面（1920×1080）：壁纸、任务栏、窗口外框，以及"它在读这一行"的扫描高亮
import React, { createContext, useContext } from "react";
import { easeIn, ramp } from "../lib/anim";
import { accent, C, FONT, type Mode } from "../lib/theme";

export const DESK_W = 1920;
export const DESK_H = 1080;
export const TASKBAR_H = 48;

export const Wallpaper: React.FC = () => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      background: [
        "radial-gradient(1100px 760px at 12% 8%, rgba(91, 140, 255, 0.32), transparent 62%)",
        "radial-gradient(900px 700px at 62% 42%, rgba(155, 107, 255, 0.20), transparent 66%)",
        "radial-gradient(1000px 820px at 96% 104%, rgba(255, 122, 69, 0.16), transparent 62%)",
        "linear-gradient(135deg, #131A33 0%, #1C1A36 48%, #26182D 100%)",
      ].join(","),
    }}
  />
);

const TbIcon: React.FC<{ children: React.ReactNode; active?: boolean }> = ({ children, active }) => (
  <div style={{ position: "relative", width: 40, height: 40, borderRadius: 6, display: "grid", placeItems: "center", background: active ? "rgba(255,255,255,0.07)" : undefined }}>
    {children}
    {active ? <div style={{ position: "absolute", bottom: 1, width: 14, height: 3, borderRadius: 2, background: "#7FA8FF" }} /> : null}
  </div>
);

export const Glyph = {
  folder: (
    <svg width={22} height={22} viewBox="0 0 24 24">
      <path d="M2.5 6.5a2 2 0 0 1 2-2h4.6l2 2h8.4a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2z" fill="#F3C24D" />
      <path d="M2.5 9h19v9a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2z" fill="#FFD866" />
    </svg>
  ),
  globe: (
    <svg width={22} height={22} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9.5" fill="#2E9BF0" />
      <path d="M2.5 12h19M12 2.5c3 3.2 3 15.8 0 19M12 2.5c-3 3.2-3 15.8 0 19" stroke="#D6EEFF" strokeWidth={1.3} />
    </svg>
  ),
  terminal: (
    <svg width={22} height={22} viewBox="0 0 24 24" fill="none">
      <rect x="2" y="3.5" width="20" height="17" rx="3" fill="#2B2D34" stroke="#5C6070" />
      <path d="M6.5 9l3 3-3 3M11.5 15.5h5" stroke="#E8EAF0" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  chat: (
    <svg width={22} height={22} viewBox="0 0 24 24">
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4h0A2.5 2.5 0 0 1 4 13.5z" fill="#8B7CF6" />
      <path d="M8 8.5h8M8 11.5h5" stroke="#fff" strokeWidth={1.5} strokeLinecap="round" />
    </svg>
  ),
  notes: (
    <svg width={22} height={22} viewBox="0 0 24 24">
      <rect x="4" y="2.5" width="16" height="19" rx="2.5" fill="#F7D774" />
      <path d="M7.5 8h9M7.5 11.5h9M7.5 15h6" stroke="#9A7A1E" strokeWidth={1.4} strokeLinecap="round" />
    </svg>
  ),
  gear: (
    <svg width={22} height={22} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="8.5" fill="#6B7280" />
      <circle cx="12" cy="12" r="3.2" fill="#E5E7EB" />
      <path d="M12 2v3.5M12 18.5V22M2 12h3.5M18.5 12H22M4.9 4.9l2.5 2.5M16.6 16.6l2.5 2.5M4.9 19.1l2.5-2.5M16.6 7.4l2.5-2.5" stroke="#6B7280" strokeWidth={2.6} strokeLinecap="round" />
    </svg>
  ),
  doc: (
    <svg width={22} height={22} viewBox="0 0 24 24">
      <path d="M6 2.5h8l5 5V20a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 20V4A1.5 1.5 0 0 1 6 2.5z" fill="#4F8EF7" />
      <path d="M14 2.5V7.5h5" fill="#A9C8FF" />
      <path d="M8 12h8M8 15h8M8 18h5" stroke="#fff" strokeWidth={1.3} strokeLinecap="round" />
    </svg>
  ),
};

export const Taskbar: React.FC<{ clock: string[]; lang: string; search: string; active?: string; trayGlow?: number }> = ({ clock, lang, search, active, trayGlow = 0 }) => (
  <div
    style={{
      position: "absolute",
      left: 0,
      right: 0,
      bottom: 0,
      height: TASKBAR_H,
      background: "rgba(24, 24, 30, 0.86)",
      borderTop: "1px solid rgba(255,255,255,0.07)",
      backdropFilter: "blur(30px)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 6,
      fontFamily: FONT.ui,
      color: "rgba(255,255,255,0.88)",
    }}
  >
    <div style={{ height: 34, width: 190, borderRadius: 17, background: "rgba(255,255,255,0.08)", display: "flex", alignItems: "center", gap: 10, padding: "0 14px", marginRight: 8, fontSize: 13, color: "rgba(255,255,255,0.55)" }}>
      <svg width={15} height={15} viewBox="0 0 20 20" fill="none" stroke="rgba(255,255,255,0.75)" strokeWidth={1.7}>
        <circle cx="8.5" cy="8.5" r="5.5" />
        <path d="M13 13l4 4" strokeLinecap="round" />
      </svg>
      {search}
    </div>
    <TbIcon>{Glyph.folder}</TbIcon>
    <TbIcon>{Glyph.globe}</TbIcon>
    <TbIcon active={active === "terminal"}>{Glyph.terminal}</TbIcon>
    <TbIcon active={active === "chat"}>{Glyph.chat}</TbIcon>
    <TbIcon active={active === "notes"}>{Glyph.notes}</TbIcon>
    <TbIcon>{Glyph.gear}</TbIcon>
    <div style={{ position: "absolute", right: 14, display: "flex", alignItems: "center", gap: 14, fontSize: 12.5 }}>
      <span style={{ color: "rgba(255,255,255,0.6)", fontSize: 11 }}>⌃</span>
      <span
        style={{
          width: 10,
          height: 10,
          borderRadius: "50%",
          background: `linear-gradient(135deg, ${C.askA}, ${C.askB})`,
          boxShadow: `0 0 ${6 + 14 * trayGlow}px rgba(155,107,255,${0.5 + 0.5 * trayGlow})`,
        }}
      />
      <span>{lang}</span>
      <svg width={16} height={16} viewBox="0 0 20 20" fill="none" stroke="rgba(255,255,255,0.85)" strokeWidth={1.5} strokeLinecap="round">
        <path d="M2.5 7.5a11 11 0 0 1 15 0M5 10.5a7 7 0 0 1 10 0M7.6 13.4a3 3 0 0 1 4.8 0" />
        <circle cx="10" cy="16" r="0.9" fill="rgba(255,255,255,0.85)" />
      </svg>
      <svg width={16} height={16} viewBox="0 0 20 20" fill="none" stroke="rgba(255,255,255,0.85)" strokeWidth={1.5} strokeLinejoin="round">
        <path d="M3 8h3l4-3.5v11L6 12H3z" />
        <path d="M13 7.5a3.5 3.5 0 0 1 0 5M15.5 5a7 7 0 0 1 0 10" strokeLinecap="round" />
      </svg>
      <div style={{ textAlign: "right", lineHeight: 1.35, fontSize: 12 }}>
        <div>{clock[0]}</div>
        <div>{clock[1]}</div>
      </div>
    </div>
  </div>
);

/** 窗口外框：标题栏 + 三个按钮；outline 表示"助手正在看的窗口"（召唤时出现，模式色） */
export const Win: React.FC<{
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  icon?: React.ReactNode;
  bodyBg?: string;
  titleBg?: string;
  dim?: number;
  outline?: { mode: Mode; amount: number };
  style?: React.CSSProperties;
  children?: React.ReactNode;
}> = ({ x, y, w, h, title, icon, bodyBg = "#1B1C21", titleBg = "#24252B", dim = 0, outline, style, children }) => {
  const [a, b] = outline ? accent(outline.mode) : ["", ""];
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: h,
        borderRadius: 9,
        overflow: "hidden",
        background: bodyBg,
        boxShadow: "0 22px 60px rgba(0,0,0,0.48), 0 0 0 1px rgba(255,255,255,0.07)",
        fontFamily: FONT.ui,
        color: "rgba(255,255,255,0.9)",
        ...style,
      }}
    >
      <div style={{ height: 36, background: titleBg, display: "flex", alignItems: "center", gap: 9, padding: "0 0 0 13px", fontSize: 12.5, color: "rgba(255,255,255,0.72)" }}>
        {icon ? <span style={{ display: "grid", transform: "scale(0.72)", transformOrigin: "left center", width: 16 }}>{icon}</span> : null}
        <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden" }}>{title}</span>
        {["min", "max", "close"].map((k) => (
          <span key={k} style={{ width: 44, height: 36, display: "grid", placeItems: "center" }}>
            <svg width={10} height={10} viewBox="0 0 10 10" fill="none" stroke="rgba(255,255,255,0.7)" strokeWidth={1}>
              {k === "min" ? <path d="M0 5.5h10" /> : k === "max" ? <rect x="0.5" y="0.5" width="9" height="9" rx="1" /> : <path d="M0.5 0.5l9 9M9.5 0.5l-9 9" />}
            </svg>
          </span>
        ))}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 36, bottom: 0, overflow: "hidden" }}>{children}</div>
      {dim > 0 ? <div style={{ position: "absolute", inset: 0, background: `rgba(10,10,14,${0.45 * dim})` }} /> : null}
      {outline && outline.amount > 0 ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            borderRadius: 9,
            boxShadow: `inset 0 0 0 2px ${a}, 0 0 24px color-mix(in srgb, ${b} 45%, transparent)`,
            opacity: outline.amount,
          }}
        />
      ) : null}
    </div>
  );
};

// ---------- 扫描：一道光从上往下扫过桌面，扫到的每一行文字都被"读到"（高亮） ----------

type Scan = { f: number; start: number; speed: number; top: number; end: number; enabled: boolean };
const ScanCtx = createContext<Scan>({ f: 0, start: 0, speed: 1, top: 0, end: 0, enabled: false });
export const ScanProvider = ScanCtx.Provider;

/** 光扫到 absY 的那一帧 */
export const scanHit = (s: Scan, absY: number) => s.start + (absY - s.top) / s.speed;

export const ScanLine: React.FC<{ absY: number; children: React.ReactNode; style?: React.CSSProperties; block?: boolean }> = ({ absY, children, style, block }) => {
  const s = useContext(ScanCtx);
  let glow = 0;
  if (s.enabled) {
    const hit = scanHit(s, absY);
    if (s.f >= hit) {
      const since = s.f - hit;
      glow = since < 4 ? since / 4 : Math.max(0.42, 1 - (since - 4) / 22);
      glow *= 1 - ramp(s.f, s.end, 14, easeIn);
    }
  }
  return (
    <span style={{ position: "relative", display: block ? "block" : "inline-block", ...style }}>
      {glow > 0 ? (
        <span
          style={{
            position: "absolute",
            left: -5,
            right: -5,
            top: 1,
            bottom: 1,
            borderRadius: 5,
            background: `linear-gradient(90deg, color-mix(in srgb, ${C.askA} 38%, transparent), color-mix(in srgb, ${C.askB} 30%, transparent))`,
            boxShadow: `0 0 0 1px color-mix(in srgb, ${C.askA} 30%, transparent)`,
            opacity: glow,
          }}
        />
      ) : null}
      <span style={{ position: "relative" }}>{children}</span>
    </span>
  );
};

/** 扫描的那道光 */
export const ScanBeam: React.FC<{ f: number; start: number; speed: number; top: number; bottom: number }> = ({ f, start, speed, top, bottom }) => {
  const y = top + (f - start) * speed;
  if (f < start || y > bottom + 80) return null;
  const fade = Math.min(1, (bottom + 80 - y) / 80);
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: y - 140, height: 142, pointerEvents: "none", opacity: fade }}>
      <div style={{ position: "absolute", inset: 0, background: `linear-gradient(180deg, transparent, color-mix(in srgb, ${C.askA} 10%, transparent) 70%, color-mix(in srgb, ${C.askB} 22%, transparent))` }} />
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 2, background: `linear-gradient(90deg, transparent, ${C.askA} 20%, ${C.askB} 80%, transparent)`, boxShadow: `0 0 18px 3px color-mix(in srgb, ${C.askB} 60%, transparent)` }} />
    </div>
  );
};
