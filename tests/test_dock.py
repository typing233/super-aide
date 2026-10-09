"""哪些回答点别处后会缩到屏幕边上：有两步以上的编号步骤（Markdown 编号列表）。"""

from super_aide.shell.controller import STEP_ITEM


def steps(markdown: str) -> int:
    return len(STEP_ITEM.findall(markdown))


def test_numbered_steps_dock():
    answer = "把默认浏览器改成 Edge：\n\n1. 打开**设置**。\n2. 点 **默认应用**。\n3) 点**设为默认值**。\n"
    assert steps(answer) == 3


def test_plain_answers_and_bullets_do_not_dock():
    assert steps("这是 Windows 的默认应用设置页。") == 0
    assert steps("原因有两个：\n\n- 环境不对\n- 没装 pandas\n") == 0
    assert steps("版本号是 1.2，发布于 2024 年。") == 0


def test_chinese_enumeration_is_not_a_markdown_list():
    assert steps("1、打开设置\n2、点默认应用") == 0


def test_single_step_is_not_a_guide():
    assert steps("1. 运行 `pip install pandas` 就好。") == 1
