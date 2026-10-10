"""新手指引：一步一个气泡，真的做了才往下走；召唤了又没发出、回答到一半就关了也走得通；操作那几步换上练习任务；
气泡摆在目标旁边、尾巴指着它；老用户不自动打开；看完了以后设置页改不回去。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRect, QSize

from super_aide import app, config, i18n, tour
from super_aide.shell import controller, tour_window
from super_aide.tour import Tour


@pytest.fixture(autouse=True)
def chinese_afterwards():
    yield
    i18n.set_language("zh")


def walk(*events: str) -> Tour:
    t = Tour()
    t.start()
    for event in events:
        t.handle(event)
    return t


def at(t: Tour) -> str:
    return t.step.key if t.step is not None else t.stage


# ---------- 往下走 ----------

def test_the_whole_way_through():
    t = walk("summon:ask", "view:input", "submit:ask", "view:card", "answer:ask", "dismiss",
             "summon:act", "submit:act", "view:pill", "done:act", "dismiss")
    assert at(t) == "tray"
    assert t.handle("tray_menu")
    assert t.stage == "done" and t.step is None


def test_only_the_expected_action_moves_on():
    t = walk()
    assert not t.handle("summon:act")  # 这一步要的是 Alt+Q
    assert not t.handle("answer:ask")
    assert at(t) == "ask"


def test_closing_the_input_without_asking_goes_back_a_step():
    assert at(walk("summon:ask", "dismiss")) == "ask"
    assert at(walk("summon:ask", "submit:ask", "answer:ask", "dismiss", "summon:act", "dismiss")) == "act"


def test_closing_the_answer_while_it_is_still_coming_skips_the_close_step():
    t = walk("summon:ask", "submit:ask", "dismiss")
    assert at(t) == "act"
    assert not t.handle("answer:ask")  # 被停下的那一轮这时才结束：不再算


def test_starting_an_action_from_the_answer_jumps_to_stopping_it():
    assert at(walk("summon:ask", "submit:ask", "answer:ask", "submit:act")) == "stop"


def test_stopping_or_failing_the_practice_task_still_moves_on():
    for end in ("stopped", "failed:act", "done:act"):
        assert at(walk("summon:ask", "submit:ask", "answer:ask", "dismiss", "summon:act", "submit:act", end)) == "tray"


# ---------- 给网页的 ----------

def test_bubble_shows_the_keys_and_a_word():
    t = walk()
    s = t.state("Ctrl+Alt+A", "Alt+W")["step"]
    assert s["keys"] == ["Ctrl", "Alt", "A"] and s["label"] == "提问" and s["target"] == "center" and s["dot"] == 0
    t.handle("summon:ask")
    assert t.state("Alt+Q", "Alt+W")["step"]["keys"] == ["↵"]
    last = walk("summon:ask", "submit:ask", "answer:ask", "dismiss", "summon:act", "submit:act", "done:act")
    s = last.state("Alt+Q", "Alt+W")["step"]
    assert s["keys"] == [] and s["last"] and "●" in s["label"]


def test_every_step_is_a_word_or_two():
    for lang in ("zh", "en"):
        i18n.set_language(lang)
        for step in tour.steps():
            assert len(step.label.replace(" ", "")) <= (8 if lang == "zh" else 24), step.label
            assert lang == "zh" or not any("一" <= ch <= "鿿" for ch in step.label)


def test_practice_task_only_during_the_action_steps():
    assert walk().suggest() == {}
    t = walk("summon:ask", "submit:ask", "answer:ask", "dismiss")
    assert at(t) == "act" and "计算器" in t.suggest()["act"]
    i18n.set_language("en")
    assert "Calculator" in t.suggest()["act"]


def test_tray_step_says_to_open_the_overflow_when_the_icon_is_hidden():
    t = walk("summon:ask", "submit:ask", "answer:ask", "dismiss", "summon:act", "submit:act", "done:act")
    assert t.state("Alt+Q", "Alt+W")["step"]["label"] == "右键 ● 打开设置"
    assert t.state("Alt+Q", "Alt+W", hidden=True)["step"]["label"] == "点 ^，再右键 ●"


class FakeElement:
    def __init__(self, name: str, automation_id: str, rect: tuple[int, int, int, int]) -> None:
        self.CachedName, self.CachedAutomationId = name, automation_id
        self.CachedBoundingRectangle = SimpleNamespace(left=rect[0], top=rect[1], right=rect[2], bottom=rect[3])


def tray_with(*buttons: FakeElement):
    found = SimpleNamespace(Length=len(buttons), GetElement=lambda i: buttons[i])
    root = SimpleNamespace(FindAllBuildCache=lambda *args: found)
    request = SimpleNamespace(AddProperty=lambda pid: None)
    return SimpleNamespace(_uia=SimpleNamespace(CreateCacheRequest=lambda: request, ElementFromHandle=lambda h: root,
                                                CreatePropertyCondition=lambda *args: None))


def test_finds_our_tray_icon_or_the_overflow_button(monkeypatch):
    from super_aide.snapshot import uia

    monkeypatch.setattr(uia.win32gui, "FindWindow", lambda *args: 1)
    chevron = FakeElement("显示隐藏的图标", "SystemTrayIcon", (1463, 1020, 1503, 1080))
    other = FakeElement("荣耀超级工作台", "NotifyItemIcon", (1503, 1020, 1543, 1080))
    ime = FakeElement("托盘输入指示器 中文模式", "SystemTrayIcon", (1583, 1020, 1623, 1080))
    ours = FakeElement("超级助手 · Alt+Q 问答 / Alt+W 操作", "NotifyItemIcon", (1543, 1020, 1583, 1080))
    names = ("超级助手", "Super Aide")
    assert uia.tray_icon(tray_with(chevron, other, ours, ime), names) == ((1543, 1020, 1583, 1080), False)
    assert uia.tray_icon(tray_with(chevron, other, ime), names) == ((1463, 1020, 1503, 1080), True)  # 收在 ^ 里
    unnamed = FakeElement("Mostrar iconos ocultos", "SystemTrayIcon", (1463, 1020, 1503, 1080))  # 别的语言
    assert uia.tray_icon(tray_with(unnamed, other, ime), names) == ((1463, 1020, 1503, 1080), True)
    assert uia.tray_icon(tray_with(other), names) is None


def test_outcome_of_a_turn():
    assert controller.outcome("ask", {"ok": False}) == "answer:ask"
    assert controller.outcome("act", {"ok": True}) == "done:act"
    assert controller.outcome("act", {"ok": False, "stopped": True}) == "stopped"
    assert controller.outcome("act", {"ok": False, "error": "没完成：x", "reason": "reported"}) == "failed:act"
    assert controller.outcome("act", {"ok": True, "hint": "浏览器操作没接通"}) == "failed:act"


# ---------- 气泡摆在哪 ----------

AVAIL = QRect(0, 0, 1536, 816)
SIZE = QSize(260, 84)  # 连着四周的透明边


def test_bubble_goes_below_the_input_with_the_tail_pointing_up():
    target = QRect(468, 500, 600, 56)
    pos, tail, at_ = tour_window.place_bubble(target, SIZE, AVAIL, ("below", "above"))
    assert tail == "up"
    assert pos.y() + tour_window.PAD == target.bottom() + 1 + tour_window.TIP  # 气泡上沿离输入框 TIP
    assert pos.x() + at_ == target.center().x()                                 # 尾巴尖对着输入框正中


def test_bubble_flips_above_when_there_is_no_room_below():
    pos, tail, _ = tour_window.place_bubble(QRect(468, 740, 600, 56), SIZE, AVAIL, ("below", "above"))
    assert tail == "down" and pos.y() + SIZE.height() - tour_window.PAD == 740 - tour_window.TIP


def test_bubble_stays_on_screen_near_the_corner():
    pill = QRect(1200, 756, 316, 40)  # 右下角的胶囊
    pos, tail, at_ = tour_window.place_bubble(pill, SIZE, AVAIL, ("above", "left"))
    assert tail == "down"
    assert pos.x() + SIZE.width() - tour_window.PAD <= AVAIL.right() + 1 - tour_window.EDGE
    assert pos.x() + at_ == pill.center().x()


def test_prompt_sits_at_the_bottom_center():
    pos = tour_window.center_bubble(SIZE, AVAIL)
    assert pos.x() + SIZE.width() // 2 == AVAIL.center().x()
    assert pos.y() + SIZE.height() - tour_window.PAD == AVAIL.bottom() + 1 - tour_window.CENTER_LIFT


# ---------- 什么时候打开、关掉以后 ----------

def test_existing_users_do_not_get_the_tour_but_new_ones_do():
    assert config.from_dict({"setup": {"done": True}}).tour_done            # 有新手指引之前就准备过
    assert not config.from_dict({}).tour_done                               # 全新
    assert not config.from_dict({"setup": {"done": True}, "tour": {"done": False}}).tour_done
    cfg = config.Config()
    cfg.tour_done = True
    assert config.from_dict(config.to_dict(cfg)).tour_done


def test_settings_page_cannot_undo_a_finished_tour(monkeypatch):
    monkeypatch.setattr(config, "save", lambda cfg, path=None: None)
    a = app.SuperAide.__new__(app.SuperAide)
    a.cfg = config.Config()
    a.cfg.tour_done = a.cfg.setup_done = True
    a.hotkeys = SimpleNamespace(active=True, unregister_all=lambda: None, register=lambda *args: True)
    a.collector = SimpleNamespace(blocked=set())
    a.hub = a.evolve = a.tray = SimpleNamespace(reconfigure=lambda *a, **k: None, set_enabled=lambda on: None,
                                               refresh=lambda cfg: None)
    a.ctrl = SimpleNamespace(panel=SimpleNamespace(call=lambda *args: None), theme=lambda: "dark")
    a.settings = a.tour = None
    stale = config.from_dict(config.to_dict(config.Config()))  # 设置页打开时拿到的旧值
    stale.theme = "light"
    assert a.apply_settings(stale) == []
    assert a.cfg.tour_done and a.cfg.setup_done and a.cfg.theme == "light"


def test_closing_the_tour_marks_it_done(monkeypatch):
    saved, shown = [], []
    monkeypatch.setattr(config, "save", lambda cfg, path=None: saved.append(cfg.tour_done))
    a = app.SuperAide.__new__(app.SuperAide)
    a.cfg = config.Config()
    a.tray = SimpleNamespace(showMessage=lambda *args: shown.append(args[1]))
    a.tour_closed("closed")
    assert a.cfg.tour_done and saved == [True] and shown == []
    a.tour_closed("skipped")  # 欢迎页上跳过：告诉一声在哪能再打开
    assert len(shown) == 1 and "新手指引" in shown[0] and saved == [True]
