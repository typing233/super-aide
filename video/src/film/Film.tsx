// 整部宣传片（约 3 分钟）：
// ① 按一个键就问 ② 名字和定位 ③ 看得见 ④ 串起几个窗口 ⑤ 操作 ⑥ 指引
// ⑦ 越用越好 ⑧ 路由会学习 ⑨ 经验 ⑩ 自我改进与个性化 ⑪ 社区共建 ⑫ 总结和下载
import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { COPY } from "../lib/copy";
import { ramp } from "../lib/anim";
import { GLOBAL_CSS, type Lang } from "../lib/theme";
import { Community } from "./Community";
import { Experience } from "./Experience";
import { Improve } from "./Improve";
import { Learning } from "./Learning";
import { Outro } from "./Outro";
import { Backdrop, Headline, Keycaps, ScreenCard, TitleCard } from "./parts";
import { Reveal } from "./Reveal";
import { CH, T } from "./timeline";

export const FilmFrame: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <style>{GLOBAL_CSS}</style>
      <Backdrop f={f} />
      <ScreenCard f={f} lang={lang} spans={[[-60, CH.reveal], [CH.see, CH.better]]} />

      <Headline f={f} lang={lang} text={copy.coldHead} start={8} end={CH.reveal - 14} />
      <Headline f={f} lang={lang} text={copy.seeHead} sub={copy.seeSub} start={CH.see + 6} end={CH.ask - 10} />
      <Headline f={f} lang={lang} text={copy.askHead} sub={copy.askSub} start={CH.ask + 6} end={CH.act - 10} />
      <Headline f={f} lang={lang} text={copy.actHead} sub={copy.actSub} start={CH.act + 6} end={CH.guide - 10} tone="act" />
      <Headline f={f} lang={lang} text={copy.guideHead} sub={copy.guideSub} start={CH.guide + 6} end={CH.better - 10} />
      <Keycaps f={f} keys={["Alt", "Q"]} at={T.coldKeys - 10} press={T.coldKeys} mode="ask" />
      <Keycaps f={f} keys={["Alt", "Q"]} at={T.askKeys - 10} press={T.askKeys} mode="ask" />
      <Keycaps f={f} keys={["Alt", "W"]} at={T.actKeys - 10} press={T.actKeys} mode="act" />

      <Reveal f={f} lang={lang} />
      <TitleCard f={f} lang={lang} text={copy.betterHead} sub={copy.betterSub} start={CH.better + 12} end={CH.route - 14} />
      <Learning f={f} lang={lang} />
      <Experience f={f} lang={lang} />
      <Improve f={f} lang={lang} />
      <Community f={f} lang={lang} />
      <Outro f={f} lang={lang} />

      {/* 开头从黑里淡入 */}
      {f < 16 ? <div style={{ position: "absolute", inset: 0, background: "#000", opacity: 1 - ramp(f, 0, 14) }} /> : null}
    </AbsoluteFill>
  );
};

export const Film: React.FC<{ lang: Lang }> = ({ lang }) => {
  const f = useCurrentFrame();
  return <FilmFrame f={f} lang={lang} />;
};
