import React from "react";
import { Composition, Still } from "remotion";
import { Film } from "./film/Film";
import { T } from "./film/timeline";
import { FPS } from "./lib/anim";
import type { Lang } from "./lib/theme";
import { OgCard, Shot, SHOTS } from "./Shots";

const LANGS: Lang[] = ["en", "zh"];

export const Root: React.FC = () => (
  <>
    {LANGS.map((lang) => (
      <Composition key={`film-${lang}`} id={`film-${lang}`} component={Film} durationInFrames={T.end} fps={FPS} width={1920} height={1080} defaultProps={{ lang }} />
    ))}
    {LANGS.flatMap((lang) =>
      Object.entries(SHOTS).map(([name, s]) => (
        <Still key={`shot-${name}-${lang}`} id={`shot-${name}-${lang}`} component={Shot} width={s.w} height={s.h} defaultProps={{ name, lang }} />
      )),
    )}
    {LANGS.map((lang) => (
      <Still key={`og-${lang}`} id={`og-${lang}`} component={OgCard} width={1200} height={630} defaultProps={{ lang }} />
    ))}
  </>
);
