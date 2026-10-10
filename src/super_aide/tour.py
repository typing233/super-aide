"""新手指引：像游戏的新手指引。一步一个小气泡，指着真实的界面，只写要按的键和一两个词；
你真的按了、做了，就自动到下一步。第一次准备完就打开，托盘菜单、设置里随时能再打开。

外壳报来的事（shell/controller.py 的 happened）：
- summon:ask / summon:act：按了快捷键，输入框出来了；submit:ask / submit:act：发出了
- answer:ask：问答答完了（出错、被停下也算）；done:act / failed:act / stopped：操作做完、没办成、按 Esc 停下
- view:<视图>：回答界面换了样子（input / card / pill / toast / dock）；dismiss：收起来了；dock：分步骤的回答贴到了边上
- tray_menu：托盘菜单打开了（app.py 接的）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .i18n import tr


@dataclass(frozen=True)
class Step:
    key: str
    #: 气泡指着谁：center（屏幕下方正中）、input、card、pill、tray；空 = 这一步不打扰（等回答的时候）
    target: str = ""
    keys: str = ""        # 要按的键：ask / act 是你设的快捷键，别的照写（↵、Esc）
    label: str = ""
    alt: str = ""         # 目标收起来了时换这一句（托盘图标收在 ^ 里）
    mode: str = "ask"     # 模式色
    advance: tuple[str, ...] = ()
    #: 发生这件事就跳到哪一步：召唤了又没发出就收起来了 → 回到"按快捷键"重来
    jump: dict[str, str] = field(default_factory=dict)
    stage: int = 0        # 第几段（气泡上的小圆点）


STAGES = 3  # 问答、操作、托盘


def steps() -> tuple[Step, ...]:
    """按当前界面语言写（语言随时能换，用的时候再调）。"""
    return (
        Step("ask", "center", "ask", tr("提问"), advance=("summon:ask",)),
        Step("send", "input", "↵", tr("发送"), advance=("submit:ask",), jump={"dismiss": "ask", "submit:act": "stop"}),
        Step("read", advance=("answer:ask",), jump={"dismiss": "act"}),
        Step("close", "card", "Esc", tr("关闭"), advance=("dismiss", "dock"), jump={"submit:act": "stop"}),
        Step("act", "center", "act", tr("让它动手"), mode="act", advance=("summon:act",), stage=1),
        Step("go", "input", "↵", tr("开始"), mode="act", advance=("submit:act",), jump={"dismiss": "act"}, stage=1),
        Step("stop", "pill", "Esc", tr("随时停下"), mode="act", advance=("done:act", "failed:act", "stopped"), stage=1),
        Step("tray", "tray", label=tr("右键 ● 打开设置"), alt=tr("点 ^，再右键 ●"), advance=("tray_menu",), stage=2),
    )


def practice() -> str:
    """操作那几步输入框里的练习任务：快、看得见它在动手、不留下文件（实测"在记事本里写一句"要一分半，还新建了文件）。"""
    return tr("打开计算器")


class Tour:
    """进行到哪：欢迎 → 一步一步 → 都会了。"""

    def __init__(self) -> None:
        self.stage = "welcome"  # welcome | step | done
        self.index = 0

    @property
    def step(self) -> Step | None:
        return steps()[self.index] if self.stage == "step" else None

    def start(self) -> None:
        self.stage, self.index = "step", 0

    def finish(self) -> None:
        self.stage = "done"

    def handle(self, event: str) -> bool:
        """外壳报来的一件事。返回换没换步。"""
        step = self.step
        if step is None:
            return False
        if event in step.jump:
            self.index = next(i for i, s in enumerate(steps()) if s.key == step.jump[event])
            return True
        if event not in step.advance:
            return False
        if self.index + 1 < len(steps()):
            self.index += 1
        else:
            self.finish()
        return True

    def suggest(self) -> dict[str, str]:
        """召唤时输入框里换上的推荐问题：操作那几步是练习任务。"""
        step = self.step
        return {"act": practice()} if step is not None and step.mode == "act" else {}

    def state(self, ask: str, act: str, hidden: bool = False) -> dict:
        """hidden：目标收起来了（托盘图标收在 ^ 里），换另一句。"""
        step = self.step
        data = {"stage": self.stage, "stages": STAGES}
        if step is not None:
            keys = {"ask": ask, "act": act}.get(step.keys, step.keys)
            data["step"] = {"key": step.key, "target": step.target, "keys": keys.split("+") if keys else [],
                            "label": step.alt if hidden and step.alt else step.label, "mode": step.mode, "dot": step.stage,
                            "last": self.index == len(steps()) - 1}
        return data
