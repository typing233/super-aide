# 宣传片和官网用图

用 [Remotion](https://www.remotion.dev)（React 逐帧渲染成视频）做的。画面里的输入框、回答卡片、操作胶囊、结果提示、屏幕指引、自我改进面板都照
`src/super_aide/ui/web` 的样式复刻（同样的尺寸、颜色、文字），桌面上的终端、聊天、笔记、打印对话框是演示用的普通窗口。
配乐和音效也是代码合成的（`audio/score.py`），没有用任何素材。

片子约 3 分钟，12 章，一章只讲一件事：按一个键就问 → 名字 → 看得见（一个窗口一个窗口地聚光）→ 一句话串起几个窗口 → 操作 → 指引 →
"而且越用越好" → 会学习的路由 → 经验 → 自我改进和个性化 → 社区共建 → 总结和下载。时间表在 `src/film/timeline.ts`。

成品放在 `website/assets/`：`film-en.mp4` / `film-zh.mp4`（整部，1080p，带声音）、`teaser-*.mp4`（首屏循环的前 14 秒，无声）、
海报 `film-*.jpg`、功能截图 `shots/*.webp`、分享预览图 `og-*.png`。README 里的视频是 720p 的版本（GitHub 免费账号上传视频最大 10 MB），
用 `gh issue comment --attach` 传到 issue #1 得到的链接。

## 渲染

需要 Node.js 22 以上、ffmpeg、uv；在 Windows 上渲染（用的是系统自带字体：Segoe UI Variable、微软雅黑、Noto Sans SC、Consolas）。

```powershell
cd video
npm install
npx remotion browser ensure                       # 下载渲染用的 Chrome（连不上就先设 HTTPS_PROXY）
npx remotion studio src/index.ts                  # 在浏览器里预览、拖时间轴
node render.mjs frames film-en 700,1290           # 渲染几帧看看（out/frames/）
node render.mjs film                              # 两种语言的整部片子（无声，out/film-*.mp4；两部共约两小时）
node render.mjs shots                             # 截图和分享预览图（out/shots/）
uv run --no-project --with numpy --with scipy python audio/score.py out/score.wav
```

合成成品（第 0 帧换成封面：GitHub 的播放器拿第一帧当预览；响度统一到 -16 LUFS）：

```bash
for l in en zh; do
  m=out/film-$l.mp4
  ffmpeg -y -i $m -vf "select=eq(n\,200)" -frames:v 1 out/cover-$l.png
  ffmpeg -y -i $m -i out/cover-$l.png -i out/score.wav \
    -filter_complex "[0:v][1:v]overlay=enable='eq(n,0)'[v]" -map "[v]" -map 2:a \
    -c:v libx264 -preset slow -crf 23 -tune animation -pix_fmt yuv420p -movflags +faststart \
    -c:a aac -b:a 160k -af "loudnorm=I=-16:TP=-1.5:LRA=11" -ar 48000 -shortest ../website/assets/film-$l.mp4
  ffmpeg -y -i $m -t 14 -an -c:v libx264 -preset slow -crf 22 -tune animation -pix_fmt yuv420p -movflags +faststart ../website/assets/teaser-$l.mp4
  ffmpeg -y -i out/cover-$l.png -vf scale=1600:-2 -q:v 3 ../website/assets/film-$l.jpg
  # README 用：720p，控制在 10 MB 以内
  ffmpeg -y -i $m -i out/cover-$l.png -i out/score.wav \
    -filter_complex "[0:v][1:v]overlay=enable='eq(n,0)',scale=1280:-2:flags=lanczos[v]" -map "[v]" -map 2:a \
    -c:v libx264 -preset slow -crf 27 -tune animation -pix_fmt yuv420p -movflags +faststart \
    -c:a aac -b:a 96k -af "loudnorm=I=-16:TP=-1.5:LRA=11" -ar 48000 -shortest out/readme-$l.mp4
done
```

截图转成 WebP：`out/shots/shot-<名字>-<语言>.png` → `../website/assets/shots/<名字>-<语言>.webp`（质量 88，保留透明圆角）。

## 改内容

- 文字（中英两份）：`src/lib/copy.ts`
- 时间表（帧号，30 fps，配乐 120 BPM，一小节 60 帧）：`src/film/timeline.ts`；音效的时间点在 `audio/score.py` 里同步改
- 应用界面的复刻：`src/ui/AppUI.tsx`；桌面和窗口：`src/desktop/`；各章：`src/film/`
- 截图的取景：`src/Shots.tsx`

Remotion 对个人和 3 人以内的团队免费，更大的公司要买授权（https://www.remotion.dev/license）。
