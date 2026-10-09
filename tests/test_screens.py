"""多显示器、混合缩放下的坐标换算。

模拟的布局（物理像素）：主屏 1920×1080 缩放 125% 在 (0,0)；右边 2560×1440 缩放 100%、上沿高出 200；
左边 3840×2160 缩放 150%。Qt 里每块屏幕的逻辑左上角等于物理左上角，大小按各自缩放比缩小。
"""

from PySide6.QtCore import QRect

from super_aide.shell.screens import ScreenMap

PRIMARY = ScreenMap((0, 0, 1920, 1080), QRect(0, 0, 1536, 864), QRect(0, 0, 1536, 816), 1.25)
RIGHT = ScreenMap((1920, -200, 4480, 1240), QRect(1920, -200, 2560, 1440), QRect(1920, -200, 2560, 1400), 1.0)
LEFT = ScreenMap((-3840, 0, 0, 2160), QRect(-3840, 0, 2560, 1440), QRect(-3840, 0, 2560, 1400), 1.5)
VIRTUAL_ORIGIN = (-3840, -200)


def test_primary_scaled():
    assert PRIMARY.to_logical((100, 100, 1060, 640)) == QRect(80, 80, 768, 432)


def test_secondary_unscaled_with_offset():
    assert RIGHT.to_logical((2020, -100, 2520, 400)) == QRect(2020, -100, 500, 500)


def test_negative_coordinates_and_150_percent():
    assert LEFT.to_logical((-3540, 150, -2940, 750)) == QRect(-3640, 100, 400, 400)


def test_round_trip_within_a_pixel():
    for screen, rect in ((PRIMARY, (13, 27, 1001, 777)), (RIGHT, (2000, -150, 3000, 900)),
                         (LEFT, (-3001, 33, -1500, 2000))):
        back = screen.to_physical(screen.to_logical(rect))
        assert all(abs(a - b) <= 1 for a, b in zip(back, rect, strict=True)), (rect, back)


def test_clamp_window_spanning_two_screens():
    window = (1800, 0, 2100, 500)
    assert PRIMARY.clamp(window) == (1800, 0, 1920, 500)
    assert RIGHT.clamp(window) == (1920, 0, 2100, 500)
    assert LEFT.clamp(window) is None


def test_crop_box_in_virtual_desktop_capture():
    assert PRIMARY.crop_box(VIRTUAL_ORIGIN) == (3840, 200, 1920, 1080)
    assert RIGHT.crop_box(VIRTUAL_ORIGIN) == (5760, 0, 2560, 1440)
    assert LEFT.crop_box(VIRTUAL_ORIGIN) == (0, 200, 3840, 2160)


def test_single_screen_matches_old_behaviour():
    """单屏时和原来的换算（只除以主屏缩放比）一致。"""
    r = (387, 211, 1500, 1003)
    dpr = 1.25
    old = QRect(round(r[0] / dpr), round(r[1] / dpr), round((r[2] - r[0]) / dpr), round((r[3] - r[1]) / dpr))
    assert PRIMARY.to_logical(r) == old
