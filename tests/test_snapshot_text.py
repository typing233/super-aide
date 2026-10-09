import pytest

from super_aide.snapshot.content import classify, placeholders
from super_aide.snapshot.redact import MASK, redact


@pytest.mark.parametrize(("text", "kind"), [
    ("Traceback (most recent call last):\n  File \"a.py\"\nModuleNotFoundError: No module named 'pandas'", "error"),
    ("安装失败：错误代码 0x80070643", "error"),
    ("def main():\n    return 1\n\nclass A:\n    pass", "code"),
    ("The quick brown fox jumps over the lazy dog. This paragraph is entirely in English.", "foreign"),
    ("今天天气很好，我们去公园散步吧。", "text"),
])
def test_classify_selection(text, kind):
    assert classify(text, source="selection") == kind


def test_window_text_is_never_foreign():
    english_ui = "File Edit Selection View Go Run Terminal Help Explorer Search Source Control Extensions " * 3
    assert classify(english_ui, source="window") == "text"


def test_dialog_class():
    assert classify("确定要继续吗？", source="window", window_class="#32770") == "dialog"


def test_placeholders_fallback():
    assert placeholders("error")["ask"] == "这个报错是什么原因？"
    assert placeholders("unknown") == placeholders("text")


@pytest.mark.parametrize("secret", [
    "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
    "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
    "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ab",  # 拼起来写：免得被当成真的令牌（推送时的密钥扫描）
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
])
def test_redact_tokens(secret):
    out = redact(f"key: {secret} end")
    assert secret not in out and MASK in out


def test_redact_key_values_keeps_key():
    assert redact("password=hunter2!") == f"password={MASK}"
    assert redact('api_key: "abcd1234"') == f'api_key: "{MASK}"'
    assert redact("普通文字不受影响") == "普通文字不受影响"
