// 整部片子的时间表（帧号，30 fps；配乐 120 BPM，一小节 = 60 帧，段落都落在小节线上）
export const T = {
  // 开场：说痛点
  hookChips: [10, 24, 38],
  hookTail: 56,
  implode: 100, // 光点在 118 帧出现、冲击波正好落在第 3 小节的强拍（120 帧）
  // 看得见屏幕
  reveal: 120,
  dock: 168,
  scan: 205,
  scanSpeed: 17, // 每帧扫过的桌面像素
  unroll: 262,
  seeChips: 296,
  // 问答
  ask: 360,
  askKeys: 368,
  askBar: 378,
  askType: 392,
  askEnter: 432,
  askStatus2: 450,
  askStream: 468,
  askStreamDur: 92,
  // 操作
  act: 600,
  actKeys: 608,
  actBar: 618,
  actType: 628,
  actEnter: 660,
  pillSteps: [662, 690, 722, 762],
  actToast: 806,
  rerun: 826,
  montage: [872, 898, 924],
  // 指引
  guide: 960,
  printOpen: 966,
  guideBar: 984,
  guideType: 990,
  guideEnter: 1022,
  guideBoxes: [1040, 1048],
  click1: 1088,
  click2: 1116,
  // 自动路由
  route: 1140,
  routes: [1196, 1248, 1300],
  // 自我改进
  evolve: 1380,
  stopToast: 1392,
  stopClick: 1426,
  evolvePanel: 1436,
  evolveSteps: [1452, 1474, 1496, 1516],
  evolveReady: 1530,
  applyClick: 1582,
  // 结尾
  outro: 1620,
  end: 1800,
};
