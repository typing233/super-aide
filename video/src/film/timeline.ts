// 整部片子的时间表（帧号，30 fps）。配乐 120 BPM，一小节 = 60 帧，每一章都从小节线开始。
// 节奏：一章只讲一件事，一句标题至少停留 3 秒，关键画面讲完再停一下。
export const CH = {
  cold: 0, //        ① 开场：按一个键就问（8 秒）
  reveal: 240, //    ② 名字和一句话定位（6 秒）
  see: 420, //       ③ 看得见：一个窗口一个窗口地读（18 秒）
  ask: 960, //       ④ 一句话串起几个窗口（14 秒）
  act: 1380, //      ⑤ 操作（18 秒）
  guide: 1920, //    ⑥ 指引（12 秒）
  better: 2280, //   ⑦ "而且越用越好"（6 秒）
  route: 2460, //    ⑧ 路由：挑选、在线学习、证明一样好才省（24 秒）
  exp: 3180, //      ⑨ 经验：记得踩过的坑、只在相似时想起（24 秒）
  improve: 3900, //  ⑩ 自我改进：你的反馈塑造你的应用（20 秒）
  community: 4500, //⑪ 社区共建（20 秒）
  recap: 5100, //    ⑫ 总结 + 下载（14 秒）
  end: 5520,
};

const c = CH;

export const T = {
  // ① 开场
  coldKeys: c.cold + 40,
  coldBar: c.cold + 50,
  coldType: c.cold + 62,
  coldEnter: c.cold + 108,
  coldStream: c.cold + 128,
  coldStreamDur: 70,

  // ③ 看得见
  seeScan: c.see + 50,
  scanSpeed: 24, // 每帧扫过的桌面像素
  spotTerm: c.see + 106,
  spotChat: c.see + 226,
  spotNotes: c.see + 346,
  unroll: c.see + 366,
  spotOff: c.see + 460,
  seeChips: c.see + 464,

  // ④ 串起几个窗口
  askKeys: c.ask + 26,
  askBar: c.ask + 36,
  askType: c.ask + 48,
  askEnter: c.ask + 100,
  askStream: c.ask + 120,
  askStreamDur: 90,
  askSources: [c.ask + 236, c.ask + 266, c.ask + 296],

  // ⑤ 操作
  actKeys: c.act + 26,
  actBar: c.act + 36,
  actType: c.act + 48,
  actEnter: c.act + 94,
  pill: c.act + 96,
  pillOpen: c.act + 124,
  pillSteps: [c.act + 134, c.act + 174, c.act + 214, c.act + 254],
  pillClose: c.act + 282,
  actToast: c.act + 290,
  rerun: c.act + 320,
  montage: [c.act + 396, c.act + 426, c.act + 456],

  // ⑥ 指引
  printOpen: c.guide + 10,
  guideBar: c.guide + 30,
  guideType: c.guide + 36,
  guideEnter: c.guide + 74,
  guideBoxes: [c.guide + 114, c.guide + 124],
  click1: c.guide + 186,
  click2: c.guide + 220,
};
