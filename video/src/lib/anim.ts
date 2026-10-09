// 动画的时间工具：所有画面都是帧号的纯函数（不用 CSS 动画、计时器），逐帧渲染才稳定
import { Easing, interpolate, interpolateColors } from "remotion";

export const FPS = 30;
export const BEAT = 15; // 配乐 120 BPM：一拍 15 帧，一小节 60 帧
export const BAR = 60;

export const easeOut = Easing.bezier(0.16, 1, 0.3, 1);
export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);
export const easeIn = Easing.bezier(0.55, 0, 1, 0.45);
export const linear = (t: number) => t;

/** 从 start 开始、用 dur 帧从 0 走到 1（两头夹住） */
export function ramp(f: number, start: number, dur: number, easing: (t: number) => number = easeOut) {
  if (!Number.isFinite(start)) return 0; // 没有设定的时间（Infinity）= 永远不发生
  if (dur <= 0) return f >= start ? 1 : 0;
  return interpolate(f, [start, start + dur], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing,
  });
}

/** 进场、停留、退场：start 起 fadeIn 帧淡入，end 起 fadeOut 帧淡出 */
export function life(f: number, start: number, end: number, fadeIn = 8, fadeOut = 8) {
  return Math.min(ramp(f, start, fadeIn), 1 - ramp(f, end, fadeOut, easeIn));
}

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** 关键帧轨道：[[帧, 值], …]，两帧之间按 easing 过渡 */
export function track(f: number, keys: [number, number][], easing: (t: number) => number = easeInOut) {
  if (f <= keys[0][0]) return keys[0][1];
  for (let i = 1; i < keys.length; i++) {
    const [f1, v1] = keys[i];
    if (f <= f1) {
      const [f0, v0] = keys[i - 1];
      return lerp(v0, v1, easing((f - f0) / Math.max(1, f1 - f0)));
    }
  }
  return keys[keys.length - 1][1];
}

export function colorTrack(f: number, keys: [number, string][]) {
  return interpolateColors(f, keys.map((k) => k[0]), keys.map((k) => k[1]));
}

/** 打字：start 起每秒 cps 个字 */
export function typed(f: number, start: number, text: string, cps: number) {
  const chars = Array.from(text);
  const n = Math.max(0, Math.floor(((f - start) * cps) / FPS));
  return chars.slice(0, n).join("");
}

/** 弹性出现（略带回弹）：0→1，可能稍超过 1 */
export function pop(f: number, start: number, dur = 14) {
  const t = clamp((f - start) / dur, 0, 1);
  if (t <= 0) return 0;
  // easeOutBack
  const c1 = 1.4;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
}

/** 闪烁的光标：每半秒亮灭一次 */
export const blink = (f: number) => (Math.floor(f / 15) % 2 === 0 ? 1 : 0);

/** 三次贝塞尔上的点 */
export function bezier(p: number[][], t: number): [number, number] {
  const u = 1 - t;
  const a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t;
  return [a * p[0][0] + b * p[1][0] + c * p[2][0] + d * p[3][0], a * p[0][1] + b * p[1][1] + c * p[2][1] + d * p[3][1]];
}

export function bezierLength(p: number[][]) {
  let len = 0;
  let prev = bezier(p, 0);
  for (let i = 1; i <= 48; i++) {
    const cur = bezier(p, i / 48);
    len += Math.hypot(cur[0] - prev[0], cur[1] - prev[1]);
    prev = cur;
  }
  return len;
}
