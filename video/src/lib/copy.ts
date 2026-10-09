// 片子里的全部文字（中英各一份）。标题里用 *…* 标出强调（渐变色）
import type { Lang } from "./theme";

type Run = { t: string; b?: boolean; code?: boolean };
export type Block = { kind: "p" | "li" | "pre"; runs: Run[]; n?: number; muted?: boolean };

const en = {
  hookHead: "To get AI's help, you first…",
  hookChips: ["Copy the error", "Screenshot it", "Explain your screen"],
  hookTail: "Every. Single. Time.",

  seeHead: "Super Aide already *sees your screen.*",
  seeSub: "The exact text of every window — even what's scrolled out of view.",
  seeChips: ["Exact text · 3 windows", "Screenshot", "What you select"],
  unrolled: "Scrolled out of view — still read",

  askHead: "Press *Alt+Q.* Ask anything.",
  askSub: "Read-only: it looks and explains, and never changes your PC.",
  askQuestion: "Why does this script fail?",
  askPlaceholder: "What's causing this error?",
  modeAsk: "Ask",
  modeAct: "Act",
  askStatus: ["Looking at your screen…", "Checking the Python environment…"],
  answer: [
    { kind: "p", runs: [{ t: "The Python environment running this script doesn't have " }, { t: "pandas", b: true }, { t: " installed." }] },
    { kind: "li", n: 1, runs: [{ t: "Install it into the same environment:" }] },
    { kind: "pre", runs: [{ t: "python -m pip install pandas" }] },
    { kind: "li", n: 2, runs: [{ t: "Run the script again." }] },
    { kind: "p", muted: true, runs: [{ t: "Still failing? You probably have several Pythons, and pandas went into another one." }] },
  ] as Block[],
  followup: "Ask a follow-up…",
  followupHint: "Tab to let me do it",

  actHead: "Press *Alt+W.* It does the work.",
  actSub: "Terminal, files, desktop apps, web pages. Press Esc to stop it anytime.",
  actTask: "Fix it for me",
  actPlaceholder: "Fix it for me",
  pill: ["Understanding the task…", "Finding the Python this script uses", "Installing pandas", "Running the script again"],
  pillNote: "You can keep using your PC without disturbing the assistant",
  toast: "Installed pandas — the script runs fine",
  toastLinks: ["Show steps", "Follow up"],
  montage: ["Renamed 128 photos by the date taken", "Filled in the expense form on the web", "Exported report.docx as a PDF"],

  guideHead: "Rather do it yourself? It *shows you where to click.*",
  guideSub: "Numbered marks, drawn right on your screen.",
  guideQuestion: "How do I save this as a PDF?",
  guideAnswer: [
    { kind: "p", runs: [{ t: "Set " }, { t: "Destination", b: true }, { t: " to " }, { t: "Save as PDF", b: true }, { t: ", then click " }, { t: "Save", b: true }, { t: ". I've marked both on your screen." }] },
  ] as Block[],
  guideLabels: ["Choose “Save as PDF”", "Then click Save"],
  print: {
    title: "Print", sheets: "1 sheet of paper", rows: ["Destination", "Pages", "Layout", "Color"],
    values: ["Office printer", "All", "Portrait", "Color"], pdf: "Save as PDF", print: "Print", save: "Save", cancel: "Cancel",
    more: "More settings", doc: "Q3 sales report",
  },

  routeHead: "Claude Code and Codex, *picked for you.*",
  routeSub: "Engine, model and effort chosen per request. Success first; cheaper only when proven just as good.",
  requests: ["What's causing this error?", "Rename these photos by date", "Summarize this thread"],
  router: "Auto-routing",
  efforts: ["low", "med", "high", "max"],
  cheaper: "Cheaper · proven just as good",

  evolveHead: "When it slips up, it *improves itself.*",
  evolveSub: "It fixes its own code, runs the tests, gets a second review — and waits for your OK.",
  stopped: "Stopped · did the assistant get something wrong?",
  stopChips: ["Did it wrong", "Too slow / stuck", "Misunderstood me", "Not the assistant's fault"],
  thanks: "Thanks, the assistant will use this to improve itself",
  evolveTitle: "Self-improvement",
  evolveNote: "Finds the cause and improves itself; you confirm before it applies",
  job: "Give focus back to your window after Esc",
  trigger: "You stopped it: Tidy up my desktop",
  evolveSteps: ["Found the cause", "Changed its own code", "All tests passed", "Independent review passed"],
  ready: "Ready, waiting for you to apply",
  apply: "Apply",
  applied: "Applied",

  outroName: "Super Aide",
  outroAlt: "超级助手",
  tagline: "Press a key. Say one thing. Done.",
  facts: ["Free & open source", "Windows 10 / 11", "100 KB installer"],
  url: "typing233.github.io/super-aide",

  clock: ["10:24 AM", "10/9/2026"],
  lang: "ENG",
  search: "Search",
  terminalTab: "PowerShell",
  chat: {
    title: "Team chat", channel: "# reports",
    msgs: [
      ["Lena", "Can you get analysis.py running? I need the sales report by 3 pm."],
      ["You", "On it — it's throwing an import error."],
      ["Lena", "Thanks! The data is in sales.csv, same folder."],
    ],
    input: "Message #reports",
  },
  notes: {
    title: "Notes", head: "Q3 sales report",
    lines: [
      "Pull sales.csv from the shared drive",
      "Run analysis.py to build report.xlsx",
      "Check totals against last quarter",
      "Region East: +12% vs Q2",
      "Region West: flat, new store opened late",
      "Online: +31%, biggest jump in September",
      "Returns down to 2.1%",
      "Ask Lena about the holiday forecast",
      "Send the report before 3 pm",
      "Charts: revenue by month, by region",
      "Top 10 products by margin",
      "Note the currency change in August",
      "Draft summary for the Monday meeting",
      "Archive last quarter's files",
    ],
  },
};

type Copy = typeof en;

const zh: Copy = {
  hookHead: "想让 AI 帮忙，你得先……",
  hookChips: ["复制报错", "截个图", "解释你的屏幕"],
  hookTail: "每次都要来一遍。",

  seeHead: "超级助手，本来就*看得见你的屏幕。*",
  seeSub: "每个窗口的文字都逐字读到，连滚动出去的部分也在。",
  seeChips: ["3 个窗口的文字 · 逐字", "截图", "你框选的区域"],
  unrolled: "滚动出去的部分，也读到了",

  askHead: "按 *Alt+Q*，想问就问。",
  askSub: "只读：看、解释，不会动你的电脑。",
  askQuestion: "这个脚本为什么跑不起来？",
  askPlaceholder: "这个报错是什么原因？",
  modeAsk: "问答",
  modeAct: "操作",
  askStatus: ["正在看你的屏幕…", "正在查看 Python 环境…"],
  answer: [
    { kind: "p", runs: [{ t: "运行这个脚本的 Python 环境里没有安装 " }, { t: "pandas", b: true }, { t: "。" }] },
    { kind: "li", n: 1, runs: [{ t: "在同一个环境里安装：" }] },
    { kind: "pre", runs: [{ t: "python -m pip install pandas" }] },
    { kind: "li", n: 2, runs: [{ t: "重新运行脚本。" }] },
    { kind: "p", muted: true, runs: [{ t: "如果装了还报错，多半是电脑上有好几个 Python，pandas 装到了别的环境里。" }] },
  ],
  followup: "继续问…",
  followupHint: "Tab 让我来做",

  actHead: "按 *Alt+W*，它直接动手。",
  actSub: "命令行、文件、桌面软件、网页都行。随时按 Esc 停下。",
  actTask: "帮我修好它",
  actPlaceholder: "帮我修好它",
  pill: ["正在理解任务…", "正在确认脚本用的是哪个 Python", "正在安装 pandas", "正在重新运行脚本"],
  pillNote: "你可以继续用电脑，不会打扰助手",
  toast: "已安装 pandas，脚本运行正常",
  toastLinks: ["查看过程", "继续问"],
  montage: ["按拍摄日期重命名了 128 张照片", "在网页上填好了报销单", "把 report.docx 导出成了 PDF"],

  guideHead: "想自己来？它把*要点的地方*圈给你看。",
  guideSub: "带编号，直接画在你的屏幕上。",
  guideQuestion: "怎么把这个存成 PDF？",
  guideAnswer: [
    { kind: "p", runs: [{ t: "把" }, { t: "目标打印机", b: true }, { t: "改成" }, { t: "另存为 PDF", b: true }, { t: "，再点" }, { t: "保存", b: true }, { t: "。两处我都在屏幕上标出来了。" }] },
  ],
  guideLabels: ["选“另存为 PDF”", "再点保存"],
  print: {
    title: "打印", sheets: "共 1 张纸", rows: ["目标打印机", "页面", "布局", "颜色"],
    values: ["办公室打印机", "全部", "纵向", "彩色"], pdf: "另存为 PDF", print: "打印", save: "保存", cancel: "取消",
    more: "更多设置", doc: "第三季度销售报表",
  },

  routeHead: "Claude Code + Codex，*自动挑最合适的。*",
  routeSub: "每次自动选引擎、模型和思考强度。先保证办成，证明一样好才换更省的。",
  requests: ["这个报错是什么原因？", "把这些照片按日期重命名", "总结一下这段讨论"],
  router: "自动路由",
  efforts: ["低", "中", "高", "最高"],
  cheaper: "更省 · 已证明一样好",

  evolveHead: "做得不好，它会*自己改进。*",
  evolveSub: "改自己的代码、跑完测试、另开会话复核，你点“生效”才换上。",
  stopped: "已停止 · 是助手哪里没做好吗？",
  stopChips: ["做错了", "太慢 / 卡住了", "没懂我的意思", "不是助手的问题"],
  thanks: "谢谢，助手会据此改进自己",
  evolveTitle: "自我改进",
  evolveNote: "分析原因、改进自己；测试和复核都通过后，等你确认生效",
  job: "Esc 停下后把焦点还给原来的窗口",
  trigger: "你停下了：帮我整理桌面",
  evolveSteps: ["找到原因", "改好自己的代码", "测试全部通过", "另开会话复核通过"],
  ready: "改好了，等你确认生效",
  apply: "生效",
  applied: "已生效",

  outroName: "超级助手",
  outroAlt: "Super Aide",
  tagline: "按一个键，说一句话，就办好。",
  facts: ["免费开源", "Windows 10 / 11", "安装器只有 100 KB"],
  url: "typing233.github.io/super-aide",

  clock: ["10:24", "2026/10/9"],
  lang: "中",
  search: "搜索",
  terminalTab: "PowerShell",
  chat: {
    title: "团队聊天", channel: "# 报表",
    msgs: [
      ["林娜", "analysis.py 能跑起来吗？下午三点前要销售报表。"],
      ["我", "在弄了，报了个导入错误。"],
      ["林娜", "辛苦！数据在同一个文件夹的 sales.csv 里。"],
    ],
    input: "发消息到 # 报表",
  },
  notes: {
    title: "笔记", head: "第三季度销售报表",
    lines: [
      "从共享盘拿 sales.csv",
      "跑 analysis.py 生成 report.xlsx",
      "和上季度核对总数",
      "华东：比二季度 +12%",
      "华西：持平，新店开得晚",
      "线上：+31%，九月涨得最多",
      "退货率降到 2.1%",
      "问林娜节假日的预测",
      "下午三点前发出报表",
      "图表：按月、按区域的收入",
      "毛利最高的 10 个产品",
      "注明八月的币种变化",
      "周一例会的总结草稿",
      "归档上季度的文件",
    ],
  },
};

export const COPY: Record<Lang, Copy> = { en, zh };
export type { Copy, Run };
