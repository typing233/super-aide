"""宣传片的配乐和音效：全部用代码合成（没有采样、没有版权问题），按 src/film/timeline.ts 的帧号对齐。

120 BPM，一小节 2 秒（60 帧），每一章都从小节线开始，整片 92 小节（184 秒）。
前半段（演示）和弦 Fmaj7 → G6 → Em7 → Am7；后半段（越用越好）换成 Am7 → Fmaj7 → C → G，更亮一些；结尾落到 Cmaj9。

    uv run --no-project --with numpy --with scipy python audio/score.py out/score.wav
"""

from __future__ import annotations

import sys
import wave

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

SR = 48000
FPS = 30
BAR = 2.0  # 秒
BARS = 92
DUR = BARS * BAR
N = int(SR * DUR)
rng = np.random.default_rng(7)

# 和 timeline.ts 的 CH 一致（帧号）
CH = dict(cold=0, reveal=240, see=420, ask=960, act=1380, guide=1920, better=2280,
          route=2460, exp=3180, improve=3900, community=4500, recap=5100, end=5520)


def sec(frame: float) -> float:
    return frame / FPS


def bar_of(frame: int) -> int:
    return frame // 60


def midi(n: float) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


def buf() -> np.ndarray:
    return np.zeros((N, 2))


def place(dst: np.ndarray, sig: np.ndarray, t: float, gain: float = 1.0, pan: float = 0.0) -> None:
    """把单声道 sig 放到 t 秒处，pan -1（左）… 1（右）"""
    i = int(t * SR)
    if i >= N or i + len(sig) <= 0:
        return
    s = sig[max(0, -i): N - i]
    i = max(0, i)
    left = np.cos((pan + 1) * np.pi / 4)
    right = np.sin((pan + 1) * np.pi / 4)
    dst[i:i + len(s), 0] += s * gain * left * np.sqrt(2)
    dst[i:i + len(s), 1] += s * gain * right * np.sqrt(2)


def lowpass(x: np.ndarray, hz: float, order: int = 2) -> np.ndarray:
    return sosfilt(butter(order, hz, "low", fs=SR, output="sos"), x, axis=0)


def highpass(x: np.ndarray, hz: float, order: int = 2) -> np.ndarray:
    return sosfilt(butter(order, hz, "high", fs=SR, output="sos"), x, axis=0)


def bandpass(x: np.ndarray, lo: float, hi: float, order: int = 2) -> np.ndarray:
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x, axis=0)


def env_adsr(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    """n 个采样的持续段 + r 秒释放"""
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    return np.concatenate([
        np.linspace(0, 1, max(1, na), endpoint=False),
        np.linspace(1, s, max(1, nd), endpoint=False),
        np.full(max(0, n - na - nd), s),
        np.linspace(s, 0, max(1, nr)),
    ])


def saw(freq: float, n: int, cutoff: float = 3200.0, phase: float = 0.0) -> np.ndarray:
    """带限锯齿波（只叠加到 cutoff 以下的谐波，天然柔和）"""
    t = np.arange(n) / SR
    out = np.zeros(n)
    k = 1
    while k * freq < cutoff and k < 40:
        out += np.sin(2 * np.pi * k * freq * t + phase * k) / k * (1 - (k * freq / cutoff) ** 2)
        k += 1
    return out * 0.6


# ---------- 段落和和弦 ----------

PROG = {  # pad 音、低音根音
    "F": ([53, 57, 60, 64], 41),
    "G": ([55, 59, 62, 64], 43),
    "Em": ([52, 55, 59, 62], 40),
    "Am": ([57, 60, 64, 67], 45),
    "C": ([55, 60, 64, 67], 48),
    "G2": ([55, 59, 62, 67], 43),
    "Fmaj9": ([53, 57, 60, 64, 67], 41),
    "Gsus": ([55, 60, 62, 67], 43),
    "Cmaj9": ([48, 55, 59, 62, 64], 36),
    "Am9": ([57, 60, 64, 67, 71], 45),
}
FIRST = ["F", "G", "Em", "Am"]
SECOND = ["Am", "F", "C", "G2"]


def section(bar: int) -> str:
    b = bar
    if b < bar_of(CH["reveal"]):
        return "intro"      # 开场：演示，安静
    if b < bar_of(CH["see"]):
        return "reveal"     # 名字：只有铺底和亮音
    if b < bar_of(CH["act"]):
        return "a"          # 看得见、串起几个窗口
    if b < bar_of(CH["guide"]):
        return "b"          # 操作：更满一点
    if b < bar_of(CH["better"]):
        return "break"      # 指引：抽掉鼓和低音
    if b < bar_of(CH["route"]):
        return "lift"       # "越用越好"：渐强
    if b < bar_of(CH["improve"]):
        return "a2"         # 路由、经验
    if b < bar_of(CH["community"]):
        return "b2"         # 自我改进
    if b < bar_of(CH["recap"]):
        return "peak"       # 社区共建：最满
    return "outro"


def chord_at(bar: int) -> str:
    sname = section(bar)
    if sname in ("intro", "reveal"):
        return "Am9" if bar < bar_of(CH["reveal"]) else ["Fmaj9", "G", "Am9"][min(2, bar - bar_of(CH["reveal"]))]
    logo = bar_of(CH["recap"]) + 3  # 名字出来的那一小节
    if sname == "outro":
        if bar < logo:
            return SECOND[(bar - bar_of(CH["route"])) % 4]
        return ["Fmaj9", "Gsus", "Cmaj9", "Cmaj9"][min(3, bar - logo)]
    if bar >= bar_of(CH["better"]):
        return SECOND[(bar - bar_of(CH["better"])) % 4]
    return FIRST[(bar - bar_of(CH["see"])) % 4]


# ---------- 乐器 ----------

LEVEL = {"intro": 0.55, "reveal": 0.85, "a": 0.7, "b": 0.72, "break": 1.0, "lift": 0.9, "a2": 0.72, "b2": 0.74, "peak": 0.78, "outro": 0.85}
CUTOFF = {"intro": 1300, "reveal": 2600, "a": 2400, "b": 3000, "break": 1800, "lift": 2800, "a2": 2600, "b2": 3000, "peak": 3300, "outro": 2600}


def pad_bus() -> np.ndarray:
    out = buf()
    for bar in range(BARS):
        notes, _ = PROG[chord_at(bar)]
        sname = section(bar)
        length = BAR if bar < BARS - 2 else DUR - bar * BAR
        n = int(length * SR)
        for j, nt in enumerate(notes):
            for detune, pan in ((-0.07, -0.55), (0.07, 0.55), (0.0, 0.0)):
                tone = saw(midi(nt + detune), n + int(0.9 * SR), CUTOFF[sname], phase=j * 1.3 + detune * 9)
                e = env_adsr(n, 0.35 if bar else 1.4, 0.4, 0.85, 0.9)[: len(tone)]
                place(out, tone[: len(e)] * e, bar * BAR, 0.06 * LEVEL[sname], pan)
    lfo = 1 + 0.06 * np.sin(2 * np.pi * 0.25 * np.arange(N) / SR)
    return lowpass(out, 5200) * lfo[:, None]


def bass_bus() -> np.ndarray:
    out = buf()
    for bar in range(BARS):
        sname = section(bar)
        if sname in ("intro", "reveal", "break"):
            continue
        _, root = PROG[chord_at(bar)]
        if sname == "lift":
            hits = [(0.0, 1.9)]
        elif sname == "outro":
            hits = [(0.0, 1.9)] if bar < BARS - 2 else [(0.0, 3.6)] if bar == BARS - 2 else []
        else:
            hits = [(0.0, 0.9), (1.0, 0.65), (1.75, 0.22)]
        for off, length in hits:
            n = int(length * SR)
            t = np.arange(n + int(0.12 * SR)) / SR
            f0 = midi(root + (12 if off == 1.75 else 0))
            tone = np.sin(2 * np.pi * f0 * t) + 0.22 * np.sin(2 * np.pi * 2 * f0 * t) + 0.08 * np.sin(2 * np.pi * 3 * f0 * t)
            e = env_adsr(n, 0.006, 0.15, 0.7, 0.12)[: len(tone)]
            place(out, np.tanh(1.4 * tone[: len(e)] * e), bar * BAR + off, 0.13)
    return highpass(lowpass(out, 900), 38)


def pluck_bus() -> np.ndarray:
    out = buf()
    pattern = [0, 1, 2, 3, 4, 3, 2, 1]
    for bar in range(BARS):
        sname = section(bar)
        if sname == "intro" and bar < 2:
            continue
        notes, _ = PROG[chord_at(bar)]
        tones = sorted(set(n % 12 for n in notes))
        root = notes[0] % 12
        ladder = []
        for octv in (60, 72):
            for pc in sorted(tones, key=lambda x: (x - root) % 12):
                ladder.append(octv + pc if octv + pc >= 62 else octv + pc + 12)
        ladder = sorted(ladder)[:6]
        bright = sname in ("b", "b2", "peak")
        for k in range(8):
            if sname == "outro" and bar >= BARS - 2 and k > 3:
                break
            if sname in ("intro", "reveal") and k % 2:
                continue  # 开场和名字那几小节只弹一半，留白
            nt = ladder[pattern[k] % len(ladder)] + (12 if bright and k % 4 == 3 else 0)
            f0 = midi(nt)
            n = int(0.7 * SR)
            t = np.arange(n) / SR
            tone = np.sin(2 * np.pi * f0 * t) + 0.35 * np.sin(2 * np.pi * 2 * f0 * t) * np.exp(-t / 0.06) + 0.12 * np.sin(2 * np.pi * 3 * f0 * t) * np.exp(-t / 0.03)
            e = np.exp(-t / (0.3 if sname == "break" else 0.18)) * np.minimum(1, t / 0.003)
            vel = 0.8 + 0.2 * (k % 2 == 0)
            gain = 0.15 if sname == "break" else 0.11
            place(out, tone * e, bar * BAR + k * 0.25, gain * vel, -0.35 if k % 2 == 0 else 0.35)
    delay = int(0.375 * SR)
    wet = np.zeros_like(out)
    for rep in range(1, 5):
        shifted = np.zeros_like(out)
        shifted[delay * rep:] = out[: N - delay * rep]
        if rep % 2:
            shifted = shifted[:, ::-1]  # 左右来回
        wet += shifted * 0.38 ** rep
    return lowpass(out + 0.6 * lowpass(wet, 3000), 7000)


def kick(n_sec: float = 0.5) -> np.ndarray:
    n = int(n_sec * SR)
    t = np.arange(n) / SR
    f = 46 + 110 * np.exp(-t / 0.035)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.22)
    click = highpass(rng.standard_normal(n), 3000) * np.exp(-t / 0.004) * 0.25
    return np.tanh(1.6 * (body + click))


def snare() -> np.ndarray:
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    return 0.7 * bandpass(rng.standard_normal(n), 1400, 7000) * np.exp(-t / 0.11) + 0.5 * np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.05)


def hat(open_: bool = False) -> np.ndarray:
    n = int((0.25 if open_ else 0.08) * SR)
    t = np.arange(n) / SR
    return highpass(rng.standard_normal(n), 7000, 4) * np.exp(-t / (0.08 if open_ else 0.022))


KICK, SNARE, HAT, OHAT = kick(), snare(), hat(), hat(True)


def drums_bus() -> tuple[np.ndarray, list[float]]:
    out = buf()
    kicks: list[float] = []
    for bar in range(BARS):
        sname = section(bar)
        t0 = bar * BAR
        if sname in ("intro", "reveal", "break"):
            for k in range(8):
                place(out, HAT, t0 + k * 0.25, (0.05 if sname != "break" else 0.07) + 0.02 * (k % 2), 0.3)
            continue
        if sname == "lift":
            # 渐强：最后一小节十六分的 hi-hat 越来越密
            for k in range(16 if bar == bar_of(CH["route"]) - 1 else 8):
                step = 0.125 if bar == bar_of(CH["route"]) - 1 else 0.25
                place(out, HAT, t0 + k * step, 0.06 + 0.005 * k, 0.3)
            continue
        if sname == "outro":
            if bar == bar_of(CH["recap"]) + 3:
                kicks.append(t0)
                place(out, KICK, t0, 0.6)
            elif bar < bar_of(CH["recap"]) + 3:
                for k in range(8):
                    place(out, HAT, t0 + k * 0.25, 0.06 + 0.02 * (k % 2), 0.3)
            continue
        for kt in (0.0, 0.75 if bar % 2 else None):
            if kt is None:
                continue
            kicks.append(t0 + kt)
            place(out, KICK, t0 + kt, 0.55 if kt == 0 else 0.35)
        place(out, SNARE, t0 + 1.0, 0.34, -0.08)
        for k in range(8):
            place(out, HAT, t0 + k * 0.25, 0.12 + 0.07 * (k % 2), 0.32)
        if sname in ("b", "b2", "peak"):
            for k in range(16):
                if k % 2:
                    place(out, HAT, t0 + k * 0.125, 0.06, 0.4)
            place(out, OHAT, t0 + 1.75, 0.10, 0.4)
    return out, kicks


def duck_curve(kicks: list[float], depth: float = 0.45) -> np.ndarray:
    g = np.ones(N)
    t = np.arange(int(0.35 * SR)) / SR
    shape = 1 - depth * np.exp(-t / 0.09)
    for k in kicks:
        i = int(k * SR)
        j = min(N, i + len(shape))
        g[i:j] = np.minimum(g[i:j], shape[: j - i])
    return g


# ---------- 音效 ----------

def sfx_pop(f0: float = 900, f1: float = 1500, dur: float = 0.09) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = f0 + (f1 - f0) * np.minimum(1, t / (dur * 0.5))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / (dur * 0.35)) * np.minimum(1, t / 0.002)


def sfx_key(bright: float = 1.0) -> np.ndarray:
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    return bandpass(rng.standard_normal(n), 1500, 6000 * bright) * np.exp(-t / 0.006) + np.sin(2 * np.pi * 320 * t) * np.exp(-t / 0.012) * 0.6


def sfx_click() -> np.ndarray:
    n = int(0.03 * SR)
    t = np.arange(n) / SR
    return bandpass(rng.standard_normal(n), 2000, 8000) * np.exp(-t / 0.003) + np.sin(2 * np.pi * 1800 * t) * np.exp(-t / 0.004) * 0.4


def sfx_chime(notes: list[float], gap: float = 0.09) -> np.ndarray:
    n = int((1.4 + gap * len(notes)) * SR)
    out = np.zeros(n)
    for i, nt in enumerate(notes):
        f0 = midi(nt)
        m = n - int(i * gap * SR)
        t = np.arange(m) / SR
        tone = np.sin(2 * np.pi * f0 * t) + 0.25 * np.sin(2 * np.pi * 2.76 * f0 * t) * np.exp(-t / 0.15) + 0.1 * np.sin(2 * np.pi * 5.4 * f0 * t) * np.exp(-t / 0.05)
        out[int(i * gap * SR):] += tone * np.exp(-t / 0.55) * np.minimum(1, t / 0.002)
    return out


def sfx_low(dur: float = 0.5) -> np.ndarray:
    """轻轻的"不对"：两个往下走的低音"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = np.where(t < dur / 2, midi(57), midi(53))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-(t % (dur / 2)) / 0.12) * 0.8


def sfx_whoosh(dur: float = 0.55, lo: float = 300, hi: float = 4000, rise: bool = True) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    out = np.zeros(n)
    seg = 1024
    for i in range(0, n, seg):
        p = i / n if rise else 1 - i / n
        c = lo * (hi / lo) ** p
        chunk = bandpass(noise[max(0, i - 2048): i + seg], c * 0.7, min(c * 1.4, SR / 2 - 100))
        out[i: i + seg] = chunk[-len(out[i: i + seg]):]
    return out * np.sin(np.pi * np.minimum(1, t / dur)) ** 1.5


def sfx_riser(dur: float = 2.0) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    w = sfx_whoosh(dur, 200, 6000, True)
    tone = np.sin(2 * np.pi * np.cumsum(220 * 2 ** (2 * t / dur)) / SR) * 0.15
    return (w / (np.abs(w).max() + 1e-9) + tone) * (t / dur) ** 2.2


def sfx_impact() -> np.ndarray:
    n = int(2.6 * SR)
    t = np.arange(n) / SR
    f = 38 + 50 * np.exp(-t / 0.08)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.7)
    air = lowpass(rng.standard_normal(n), 1200) * np.exp(-t / 0.35) * 0.4
    return np.tanh(1.3 * (boom + air))


def sfx_shimmer(dur: float = 1.8) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k, nt in enumerate([84, 88, 91, 95, 98]):
        out += np.sin(2 * np.pi * midi(nt) * t + k) * np.exp(-t / 0.9) * (0.5 + 0.5 * np.sin(2 * np.pi * (3 + k) * t))
    return out * np.minimum(1, t / 0.05)


def sfx_bus() -> np.ndarray:
    out = buf()
    s = sec

    def typing(start: int, end: int, every: float = 2.6, gain: float = 0.05) -> None:
        fr, k = float(start), 0
        while fr < end:
            place(out, sfx_key(0.9 + 0.1 * (k % 3)), s(fr), gain * (0.8 + 0.4 * ((k * 7) % 5) / 5), 0.15)
            fr += every + ((k * 13) % 5) * 0.35
            k += 1

    def summon(keys: int, bar: int, t0: int, t1: int, enter: int) -> None:
        place(out, sfx_key(), s(keys), 0.16)
        place(out, sfx_key(1.2), s(keys + 5), 0.16)
        place(out, sfx_pop(880, 1320), s(bar), 0.08)
        typing(t0, t1)
        place(out, sfx_key(0.8), s(enter), 0.12)

    # ① 开场
    summon(40, 50, 62, 100, 108)
    # ② 名字（第 5 小节的强拍）
    r = CH["reveal"]
    place(out, sfx_riser(1.6), s(r) - 1.6, 0.16)
    place(out, sfx_impact(), s(r), 0.5)
    place(out, sfx_shimmer(2.4), s(r), 0.06)
    for i in range(3):
        place(out, sfx_pop(700 + 120 * i, 1050 + 160 * i), s(r + 76 + i * 12), 0.06, -0.3 + 0.3 * i)
    # ③ 看得见
    c = CH["see"]
    place(out, sfx_whoosh(0.7, 200, 2500), s(c), 0.10)
    place(out, sfx_whoosh(1.6, 800, 7000), s(c + 50), 0.05, 0.2)
    for at, pan in ((c + 106, -0.1), (c + 226, 0.5), (c + 346, -0.5)):
        place(out, sfx_whoosh(0.45, 500, 2600), s(at), 0.06, pan)
        place(out, sfx_chime([88], 0.0), s(at + 18), 0.035, pan)
    for i in range(3):
        place(out, sfx_pop(1000, 1500), s(c + 464 + i * 8), 0.05, -0.3 + 0.3 * i)
    # ④ 串起几个窗口
    a = CH["ask"]
    summon(a + 26, a + 36, a + 48, a + 92, a + 100)
    for i, at in enumerate((a + 236, a + 266, a + 296)):
        place(out, sfx_chime([86 + 3 * i], 0.0), s(at + 14), 0.06, [0, -0.5, 0.5][i])
    # ⑤ 操作
    t = CH["act"]
    summon(t + 26, t + 36, t + 48, t + 86, t + 94)
    place(out, sfx_pop(500, 750), s(t + 96), 0.07, 0.5)
    place(out, sfx_whoosh(0.4, 600, 3000), s(t + 124), 0.05, 0.5)
    for at in (t + 134, t + 174, t + 214, t + 254):
        place(out, sfx_pop(1200, 1300, 0.05), s(at), 0.035, 0.5)
    place(out, sfx_chime([88, 95]), s(t + 290), 0.10, 0.4)
    typing(t + 320, t + 340, 1.6, 0.035)
    for i, at in enumerate((t + 396, t + 426, t + 456)):
        place(out, sfx_chime([86 + 2 * i, 93 + 2 * i], 0.07), s(at), 0.05, 0.45)
    # ⑥ 指引
    g = CH["guide"]
    place(out, sfx_whoosh(0.45, 400, 3000), s(g + 10), 0.07)
    place(out, sfx_pop(880, 1320), s(g + 30), 0.07)
    typing(g + 36, g + 68)
    place(out, sfx_key(0.8), s(g + 74), 0.11)
    for i, at in enumerate((g + 114, g + 124)):
        place(out, sfx_chime([91 + 4 * i], 0.0), s(at), 0.06)
    for at in (g + 186, g + 220):
        place(out, sfx_click(), s(at), 0.13)
    # ⑦ 越用越好：轻的重音，渐强进第二部分
    b = CH["better"]
    place(out, sfx_impact(), s(b), 0.3)
    place(out, sfx_shimmer(2.6), s(b + 12), 0.07)
    place(out, sfx_riser(2.4), s(CH["route"]) - 2.4, 0.14)
    # ⑧ 路由
    ro = CH["route"]
    for at in (ro + 80, ro + 130, ro + 180):
        place(out, sfx_whoosh(0.5, 600, 5000), s(at), 0.045, -0.4)
        place(out, sfx_pop(1400, 1700, 0.07), s(at + 16), 0.05)
        place(out, sfx_whoosh(0.5, 600, 5000), s(at + 18), 0.045, 0.4)
        place(out, sfx_chime([93], 0.0), s(at + 34), 0.05, 0.4)
    lb = ro + 240
    for i in range(5):
        place(out, sfx_pop(900 + 80 * i, 1250 + 90 * i, 0.06), s(lb + 40 + i * 16 + 36), 0.045, -0.5)
    place(out, sfx_whoosh(0.5, 400, 2600), s(lb + 60), 0.06, 0.5)
    place(out, sfx_chime([88, 92]), s(lb + 136), 0.07, 0.5)
    for k in range(8):
        place(out, sfx_pop(1500 + 40 * k, 1600 + 40 * k, 0.03), s(lb + 150 + k * 8), 0.025, 0.5)
    ga = ro + 510
    for i, step in enumerate((2.6, 5.0, 7.2)):
        place(out, sfx_chime([88 + 3 * i, 95 + 3 * i], 0.06), s(ga + 40 + round((step - 1) / 7 * 120)), 0.06, -0.3 + 0.3 * i)
    # ⑨ 经验
    e = CH["exp"]
    for i, at in enumerate((e + 20, e + 46, e + 70, e + 100, e + 128)):
        if i == 2:
            place(out, sfx_low(), s(at), 0.08)
        elif i == 4:
            place(out, sfx_chime([88, 95]), s(at), 0.07)
        else:
            place(out, sfx_key(), s(at), 0.08)
    place(out, sfx_whoosh(0.6, 500, 4000), s(e + 140), 0.06, 0.4)
    place(out, sfx_pop(800, 1200), s(e + 150), 0.07, 0.4)
    eb = e + 240
    place(out, sfx_shimmer(1.6), s(eb + 4), 0.04)
    place(out, sfx_whoosh(0.6, 600, 3000), s(eb + 60), 0.05)
    place(out, sfx_chime([86, 93]), s(eb + 92), 0.07)
    place(out, sfx_low(), s(eb + 130), 0.06)
    place(out, sfx_whoosh(0.5, 3000, 400, False), s(eb + 156), 0.04)
    er = e + 480
    typing(er + 28, er + 68)
    place(out, sfx_key(0.8), s(er + 74), 0.11)
    place(out, sfx_whoosh(0.5, 800, 5000), s(er + 76), 0.04, 0.5)
    place(out, sfx_chime([93, 100]), s(er + 92), 0.07, 0.5)
    place(out, sfx_key(), s(er + 166), 0.08)
    # ⑩ 自我改进
    im = CH["improve"]
    for i, at in enumerate((im + 16, im + 32, im + 48, im + 64)):
        place(out, sfx_pop(700 + 100 * i, 1000 + 120 * i), s(at), 0.06, [-0.5, 0.5, -0.5, 0.5][i])
    place(out, sfx_click(), s(im + 76), 0.1, 0.5)
    place(out, sfx_click(), s(im + 86), 0.1, -0.5)
    typing(im + 90, im + 120, 2.2, 0.045)
    place(out, sfx_click(), s(im + 128), 0.12, 0.5)
    ib = im + 210
    for i, at in enumerate((ib + 26, ib + 52, ib + 78, ib + 104)):
        place(out, sfx_pop(900 + 120 * i, 1300 + 160 * i, 0.06), s(at), 0.05)
    place(out, sfx_chime([84, 91]), s(ib + 120), 0.06)
    place(out, sfx_click(), s(ib + 196), 0.13)
    place(out, sfx_chime([88, 92, 95, 100], 0.07), s(ib + 198), 0.09)
    ip = im + 450
    place(out, sfx_pop(700, 1000), s(ip + 12), 0.05, -0.4)
    place(out, sfx_chime([91, 98]), s(ip + 42), 0.06, 0.4)
    # ⑪ 社区共建
    cm = CH["community"]
    place(out, sfx_shimmer(1.8), s(cm + 14), 0.04)
    place(out, sfx_pop(800, 1200), s(cm + 50), 0.06, -0.5)
    place(out, sfx_whoosh(1.4, 400, 3000), s(cm + 124), 0.06, -0.2)
    place(out, sfx_pop(1300, 1600, 0.08), s(cm + 164), 0.06)
    cmm = cm + 220
    for i in range(3):
        place(out, sfx_pop(1100 + 150 * i, 1300 + 150 * i, 0.05), s(cmm + 16 + i * 14), 0.04, 0.4)
    place(out, sfx_chime([88, 95, 100], 0.08), s(cmm + 64), 0.08)
    place(out, sfx_whoosh(1.2, 300, 6000), s(cmm + 80), 0.07)
    place(out, sfx_shimmer(2.0), s(cmm + 86), 0.06)
    for k in range(4):
        place(out, sfx_whoosh(0.8, 400, 3500), s(cm + 420 + k * 48), 0.03)
    # ⑫ 总结 + 名字
    rc = CH["recap"]
    for i in range(8):
        place(out, sfx_pop(900 + 60 * i, 1200 + 60 * i, 0.05), s(rc + 24 + i * 7), 0.03, -0.4 + 0.11 * i)
    logo = rc + 180
    place(out, sfx_riser(1.6), s(logo) - 1.6, 0.13)
    place(out, sfx_impact(), s(logo), 0.42)
    place(out, sfx_shimmer(3.0), s(logo + 2), 0.07)
    return out


def reverb(x: np.ndarray, rt: float = 2.3, pre: float = 0.02) -> np.ndarray:
    n = int(rt * SR)
    t = np.arange(n) / SR
    ir = np.zeros((n + int(pre * SR), 2))
    for ch in range(2):
        ir[int(pre * SR):, ch] = lowpass(rng.standard_normal(n) * np.exp(-6.9 * t / rt), 5500 - 400 * ch)
    ir /= np.sqrt((ir ** 2).sum(axis=0))
    out = np.stack([fftconvolve(x[:, ch], ir[:, ch])[:N] for ch in range(2)], axis=1)
    return highpass(out, 180)


def main(path: str) -> None:
    drums, kicks = drums_bus()
    duck = duck_curve(kicks)[:, None]
    pad = pad_bus() * duck
    bass = bass_bus() * duck_curve(kicks, 0.6)[:, None]
    pluck = pluck_bus() * duck
    sfx = sfx_bus()
    dry = pad + bass + pluck + drums + sfx
    send = 0.55 * pad + 0.45 * pluck + 0.25 * drums + 0.5 * sfx
    mix = dry + 0.32 * reverb(send)
    t = np.arange(N) / SR
    mix *= (np.minimum(1, t / 0.4) * np.clip((DUR - t) / 1.6, 0, 1))[:, None]
    mix = highpass(mix, 30)
    mix = mix - 0.35 * lowpass(mix, 110)  # 低频收一点，笔记本扬声器上不发闷
    peak = np.abs(mix).max()
    mix = np.tanh(mix / peak * 1.1) / np.tanh(1.1) * 0.89
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mix * 32767).astype("<i2").tobytes())
    print(path, f"{DUR:.0f}s")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/score.wav")
