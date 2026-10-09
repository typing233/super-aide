// 整部宣传片（约 60 秒）：痛点 → 看得见屏幕 → 问答 → 操作 → 指引 → 自动路由 → 自我改进 → 下载
import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { COPY } from "../lib/copy";
import { GLOBAL_CSS, type Lang } from "../lib/theme";
import { Evolve } from "./Evolve";
import { Hook } from "./Hook";
import { Outro } from "./Outro";
import { Backdrop, Headline, Keycaps, ScreenCard } from "./parts";
import { Route } from "./Route";
import { T } from "./timeline";

export const FilmFrame: React.FC<{ f: number; lang: Lang }> = ({ f, lang }) => {
  const copy = COPY[lang];
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <style>{GLOBAL_CSS}</style>
      <Backdrop f={f} />
      <Hook f={f} lang={lang} />
      <Headline f={f} lang={lang} text={copy.seeHead} sub={copy.seeSub} start={T.reveal} dockAt={T.dock} end={T.ask - 8} />
      <Headline f={f} lang={lang} text={copy.askHead} sub={copy.askSub} start={T.ask + 4} end={T.act - 8} />
      <Headline f={f} lang={lang} text={copy.actHead} sub={copy.actSub} start={T.act + 4} end={T.guide - 8} tone="act" />
      <Headline f={f} lang={lang} text={copy.guideHead} sub={copy.guideSub} start={T.guide + 4} end={T.route - 8} />
      <ScreenCard f={f} lang={lang} enter={T.dock} exit={T.route} />
      <Keycaps f={f} keys={["Alt", "Q"]} at={T.askKeys - 8} press={T.askKeys} mode="ask" />
      <Keycaps f={f} keys={["Alt", "W"]} at={T.actKeys - 8} press={T.actKeys} mode="act" />
      <Route f={f} lang={lang} />
      <Evolve f={f} lang={lang} />
      <Outro f={f} lang={lang} />
    </AbsoluteFill>
  );
};

export const Film: React.FC<{ lang: Lang }> = ({ lang }) => {
  const f = useCurrentFrame();
  return <FilmFrame f={f} lang={lang} />;
};
