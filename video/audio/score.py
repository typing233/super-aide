"""宣传片的配乐和音效：全部用代码合成（没有采样、没有版权问题），按 src/film/timeline.ts 的帧号对齐。

120 BPM，一小节 2 秒（60 帧），整片 30 小节。和弦 Fmaj7 → G6 → Em7 → Am7 循环，结尾落到 Cmaj9。

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
DUR = 60.0
N = int(SR * DUR)
rng = np.random.default_rng(7)


def sec(frame: float) -> float:
    return frame / FPS


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
    e = np.concatenate([
        np.linspace(0, 1, max(1, na), endpoint=False),
        np.linspace(1, s, max(1, nd), endpoint=False),
        np.full(max(0, n - na - nd), s),
        np.linspace(s, 0, max(1, nr)),
    ])
    return e


def saw(freq: float, n: int, cutoff: float = 3200.0, phase: float = 0.0) -> np.ndarray:
    """带限锯齿波（只叠加到 cutoff 以下的谐波，天然柔和）"""
    t = np.arange(n) / SR
    out = np.zeros(n)
    k = 1
    while k * freq < cutoff and k < 40:
        out += np.sin(2 * np.pi * k * freq * t + phase * k) / k * (1 - (k * freq / cutoff) ** 2)
        k += 1
    return out * 0.6


# ---------- 和弦 ----------

PROG = {  # 每小节的和弦：pad 音、低音根音
    "F": ([53, 57, 60, 64], 41),
    "G": ([55, 59, 62, 64], 43),
    "Em": ([52, 55, 59, 62], 40),
    "Am": ([57, 60, 64, 67], 45),
    "Fmaj9": ([53, 57, 60, 64, 67], 41),
    "Gsus": ([55, 60, 62, 67], 43),
    "Cmaj9": ([48, 55, 59, 62, 64], 36),
    "Am9": ([57, 60, 64, 67, 71], 45),
}
LOOP = ["F", "G", "Em", "Am"]


def chord_at(bar: int) -> str:
    if bar < 2:
        return "Am9"
    if bar == 27:
        return "Fmaj9"
    if bar == 28:
        return "Gsus"
    if bar >= 29:
        return "Cmaj9"
    return LOOP[(bar - 2) % 4]


# 段落：哪些小节有鼓、有低音、亮度
def section(bar: int) -> str:
    if bar < 2:
        return "intro"
    if bar < 10:
        return "a"       # 看得见屏幕、问答
    if bar < 16:
        return "b"       # 操作：更满一点
    if bar < 19:
        return "break"   # 指引：抽掉鼓和低音
    if bar < 23:
        return "a"       # 自动路由
    if bar < 27:
        return "b"       # 自我改进
    return "outro"


# ---------- 乐器 ----------

def pad_bus() -> np.ndarray:
    out = buf()
    for bar in range(30):
        name = chord_at(bar)
        notes, _ = PROG[name]
        if bar >= 29:
            length = DUR - bar * BAR  # 最后一个和弦一直响到结束
        else:
            length = BAR
        n = int(length * SR)
        sec_name = section(bar)
        cutoff = {"intro": 900 + 900 * (bar / 2), "a": 2400, "b": 3000, "break": 1800, "outro": 2600}[sec_name]
        level = {"intro": 0.6, "a": 0.7, "b": 0.72, "break": 1.0, "outro": 0.85}[sec_name]
        for j, nt in enumerate(notes):
            for detune, pan in ((-0.07, -0.55), (0.07, 0.55), (0.0, 0.0)):
                f0 = midi(nt + detune)
                tone = saw(f0, n + int(0.9 * SR), cutoff, phase=j * 1.3 + detune * 9)
                e = env_adsr(n, 0.35 if bar > 1 else 1.2, 0.4, 0.85, 0.9)[: len(tone)]
                tone = tone[: len(e)] * e
                place(out, tone, bar * BAR, 0.06 * level, pan)
    lfo = 1 + 0.06 * np.sin(2 * np.pi * 0.25 * np.arange(N) / SR)
    return lowpass(out, 5200) * lfo[:, None]


def bass_bus() -> np.ndarray:
    out = buf()
    for bar in range(30):
        sname = section(bar)
        if sname in ("intro", "break"):
            continue
        _, root = PROG[chord_at(bar)]
        if sname == "outro":
            if bar == 27 or bar == 28:
                hits = [(0.0, 1.9)]
            elif bar == 29:
                hits = [(0.0, 3.5)]
            else:
                hits = []
        else:
            hits = [(0.0, 0.9), (1.0, 0.65), (1.75, 0.22)]  # 一拍、三拍，四拍后半拍点一下
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
    for bar in range(30):
        sname = section(bar)
        if sname == "intro":
            continue
        notes, _ = PROG[chord_at(bar)]
        tones = sorted(set(n % 12 for n in notes))
        root = notes[0] % 12
        # 从根音往上排两个八度内的和弦音
        ladder = []
        for octv in (60, 72):
            for pc in sorted(tones, key=lambda x: (x - root) % 12):
                ladder.append(octv + pc if octv + pc >= 62 else octv + pc + 12)
        ladder = sorted(ladder)[:6]
        step = 0.25
        for k in range(8):
            if sname == "outro" and bar >= 29 and k > 3:
                break
            nt = ladder[pattern[k] % len(ladder)] + (12 if sname == "b" and k % 4 == 3 else 0)
            f0 = midi(nt)
            n = int(0.7 * SR)
            t = np.arange(n) / SR
            tone = np.sin(2 * np.pi * f0 * t) + 0.35 * np.sin(2 * np.pi * 2 * f0 * t) * np.exp(-t / 0.06) + 0.12 * np.sin(2 * np.pi * 3 * f0 * t) * np.exp(-t / 0.03)
            e = np.exp(-t / (0.18 if sname != "break" else 0.3)) * np.minimum(1, t / 0.003)
            vel = 0.8 + 0.2 * (k % 2 == 0)
            pan = -0.35 if k % 2 == 0 else 0.35
            place(out, tone * e, bar * BAR + k * step, (0.15 if sname == "break" else 0.11) * vel, pan)
    # 附点八分的回声
    delay = int(0.375 * SR)
    wet = np.zeros_like(out)
    src = out.copy()
    for rep in range(1, 5):
        g = 0.38 ** rep
        shifted = np.zeros_like(out)
        shifted[delay * rep:] = src[: N - delay * rep]
        if rep % 2:
            shifted = shifted[:, ::-1]  # 左右来回
        wet += shifted * g
    return lowpass(out + 0.6 * lowpass(wet, 3000), 7000)


def kick(n_sec: float = 0.5) -> np.ndarray:
    n = int(n_sec * SR)
    t = np.arange(n) / SR
    f = 46 + 110 * np.exp(-t / 0.035)
    phase = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(phase) * np.exp(-t / 0.22)
    click = highpass(rng.standard_normal(n), 3000) * np.exp(-t / 0.004) * 0.25
    return np.tanh(1.6 * (body + click))


def snare() -> np.ndarray:
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    noise = bandpass(rng.standard_normal(n), 1400, 7000) * np.exp(-t / 0.11)
    body = np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.05)
    return 0.7 * noise + 0.5 * body


def hat(open_: bool = False) -> np.ndarray:
    n = int((0.25 if open_ else 0.08) * SR)
    t = np.arange(n) / SR
    return highpass(rng.standard_normal(n), 7000, 4) * np.exp(-t / (0.08 if open_ else 0.022))


KICK, SNARE, HAT, OHAT = kick(), snare(), hat(), hat(True)


def drums_bus() -> tuple[np.ndarray, list[float]]:
    out = buf()
    kicks: list[float] = []
    for bar in range(30):
        sname = section(bar)
        t0 = bar * BAR
        if sname == "intro":
            # 只有很轻的八分 hi-hat，第二小节渐强
            for k in range(8):
                place(out, HAT, t0 + k * 0.25, 0.05 + 0.05 * bar + 0.03 * (k % 2), 0.3)
            continue
        if sname == "break":
            for k in range(8):
                place(out, HAT, t0 + k * 0.25, 0.06 + 0.02 * (k % 2), 0.3)
            continue
        if sname == "outro":
            if bar == 27:
                kicks.append(t0)
                place(out, KICK, t0, 0.6)
            continue
        for kt in (0.0, 0.75 if bar % 2 else None):
            if kt is None:
                continue
            kicks.append(t0 + kt)
            place(out, KICK, t0 + kt, 0.55 if kt == 0 else 0.35)
        place(out, SNARE, t0 + 1.0, 0.36, -0.08)
        for k in range(8):
            v = 0.12 + 0.07 * (k % 2)
            place(out, HAT, t0 + k * 0.25, v, 0.32)
        if sname == "b":  # 十六分、反拍开镲
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
    noise = bandpass(rng.standard_normal(n), 1500, 6000 * bright) * np.exp(-t / 0.006)
    thock = np.sin(2 * np.pi * 320 * t) * np.exp(-t / 0.012) * 0.6
    return noise + thock


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


def sfx_whoosh(dur: float = 0.55, lo: float = 300, hi: float = 4000, rise: bool = True) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    # 分段带通扫频
    out = np.zeros(n)
    seg = 1024
    for i in range(0, n, seg):
        p = i / n if rise else 1 - i / n
        c = lo * (hi / lo) ** p
        chunk = bandpass(noise[max(0, i - 2048): i + seg], c * 0.7, min(c * 1.4, SR / 2 - 100))
        out[i: i + seg] = chunk[-len(out[i: i + seg]):]
    e = np.sin(np.pi * np.minimum(1, t / dur)) ** 1.5
    return out * e


def sfx_riser(dur: float = 2.0) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    w = sfx_whoosh(dur, 200, 6000, True)
    e = (t / dur) ** 2.2
    tone = np.sin(2 * np.pi * np.cumsum(220 * 2 ** (2 * t / dur)) / SR) * 0.15
    return (w / (np.abs(w).max() + 1e-9) + tone) * e


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
        f0 = midi(nt)
        out += np.sin(2 * np.pi * f0 * t + k) * np.exp(-t / 0.9) * (0.5 + 0.5 * np.sin(2 * np.pi * (3 + k) * t))
    return out * np.minimum(1, t / 0.05)


def sfx_bus() -> np.ndarray:
    out = buf()
    s = sec
    # 开场：三个标签弹出
    for i, fr in enumerate([10, 24, 38]):
        place(out, sfx_pop(700 + 150 * i, 1100 + 200 * i), s(fr), 0.10, -0.3 + 0.3 * i)
    # 收拢 → 光点（第 3 小节强拍）
    place(out, sfx_riser(1.9), s(120) - 1.9, 0.20)
    place(out, sfx_impact(), s(120), 0.55)
    place(out, sfx_shimmer(2.2), s(120), 0.05)
    # 屏幕升上来、扫描
    place(out, sfx_whoosh(0.7, 200, 2500), s(168), 0.10)
    place(out, sfx_whoosh(1.9, 800, 7000), s(205), 0.05, 0.2)
    for i, fr in enumerate([296, 302, 308]):
        place(out, sfx_pop(1000, 1500), s(fr), 0.06, -0.3 + 0.3 * i)

    def typing(start: int, end: int, every: float = 2.6, gain: float = 0.05) -> None:
        fr = float(start)
        k = 0
        while fr < end:
            place(out, sfx_key(0.9 + 0.2 * (k % 3) / 2), s(fr), gain * (0.8 + 0.4 * ((k * 7) % 5) / 5), 0.15)
            fr += every + ((k * 13) % 5) * 0.35
            k += 1

    # 问答
    place(out, sfx_key(), s(368), 0.16)
    place(out, sfx_key(1.2), s(373), 0.16)
    place(out, sfx_pop(880, 1320), s(378), 0.08)
    typing(392, 426)
    place(out, sfx_key(0.8), s(432), 0.12)
    # 操作
    place(out, sfx_key(), s(608), 0.16)
    place(out, sfx_key(1.2), s(613), 0.16)
    place(out, sfx_pop(660, 990), s(618), 0.08)
    typing(628, 652)
    place(out, sfx_key(0.8), s(660), 0.12)
    place(out, sfx_pop(500, 750), s(662), 0.07, 0.5)
    for fr in (690, 722, 762):
        place(out, sfx_pop(1200, 1300, 0.05), s(fr), 0.035, 0.5)
    place(out, sfx_chime([88, 95]), s(806), 0.10, 0.4)
    typing(826, 846, 1.6, 0.035)
    for i, fr in enumerate([872, 898, 924]):
        place(out, sfx_chime([86 + 2 * i, 93 + 2 * i], 0.07), s(fr), 0.05, 0.45)
    # 指引
    place(out, sfx_whoosh(0.45, 400, 3000), s(962), 0.07)
    place(out, sfx_pop(880, 1320), s(984), 0.07)
    typing(990, 1018)
    place(out, sfx_key(0.8), s(1022), 0.11)
    for i, fr in enumerate([1040, 1048]):
        place(out, sfx_chime([91 + 4 * i], 0.0), s(fr), 0.06)
    for fr in (1088, 1116):
        place(out, sfx_click(), s(fr), 0.13)
    # 自动路由
    place(out, sfx_whoosh(0.8, 3000, 200, True), s(1138), 0.09)
    for fr in (1196, 1248, 1300):
        place(out, sfx_whoosh(0.5, 600, 5000), s(fr), 0.045, -0.4)
        place(out, sfx_pop(1400, 1700, 0.07), s(fr + 16), 0.05)
        place(out, sfx_whoosh(0.5, 600, 5000), s(fr + 18), 0.045, 0.4)
        place(out, sfx_chime([93], 0.0), s(fr + 34), 0.05, 0.4)
    # 自我改进
    place(out, sfx_pop(700, 1000), s(1392), 0.07, -0.4)
    place(out, sfx_click(), s(1426), 0.13, -0.4)
    for i, fr in enumerate([1452, 1474, 1496, 1516]):
        place(out, sfx_pop(900 + 120 * i, 1300 + 160 * i, 0.06), s(fr), 0.05, 0.4)
    place(out, sfx_chime([84, 91]), s(1530), 0.06, 0.4)
    place(out, sfx_click(), s(1582), 0.13, 0.4)
    place(out, sfx_chime([88, 92, 95, 100], 0.07), s(1584), 0.09, 0.4)
    # 结尾
    place(out, sfx_riser(1.6), s(1620) - 1.6, 0.14)
    place(out, sfx_impact(), s(1620), 0.45)
    place(out, sfx_shimmer(3.0), s(1622), 0.07)
    return out


def reverb(x: np.ndarray, rt: float = 2.3, pre: float = 0.02) -> np.ndarray:
    n = int(rt * SR)
    t = np.arange(n) / SR
    ir = np.zeros((n + int(pre * SR), 2))
    for ch in range(2):
        noise = rng.standard_normal(n) * np.exp(-6.9 * t / rt)
        ir[int(pre * SR):, ch] = lowpass(noise, 5500 - 2000 * ch * 0.2)
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
    # 开头淡入、结尾淡出
    t = np.arange(N) / SR
    fade = np.minimum(1, t / 0.4) * np.clip((DUR - t) / 1.6, 0, 1)
    mix *= fade[:, None]
    mix = highpass(mix, 30)
    mix = mix - 0.35 * lowpass(mix, 110)  # 低频收一点，笔记本扬声器上不发闷
    peak = np.abs(mix).max()
    mix = np.tanh(mix / peak * 1.1) / np.tanh(1.1) * 0.89
    data = (mix * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
    print(path, f"{DUR:.0f}s")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out/score.wav")
