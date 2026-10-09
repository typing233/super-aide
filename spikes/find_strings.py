"""在大二进制文件里搜索 ASCII 字符串片段（类似 strings | grep），打印命中处附近的可读文本。"""

import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
needles = [n.encode() for n in sys.argv[2:]]
data = path.read_bytes()
printable = re.compile(rb"[\x20-\x7e]{4,}")
seen = set()
for needle in needles:
    for m in re.finditer(re.escape(needle), data):
        start = max(0, m.start() - 200)
        chunk = data[start:m.end() + 200]
        for s in printable.findall(chunk):
            if needle in s and s not in seen:
                seen.add(s)
                print(s.decode(errors="replace")[:300])
