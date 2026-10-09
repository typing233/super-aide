// 官网的小脚本：切换语言、最新版本信息、宣传片播放、滚动时浮现
(() => {
  "use strict";
  const root = document.documentElement;
  clearTimeout(window.__revealFallback);

  const TEXT = {
    en: {
      title: "Super Aide — the Windows assistant that sees your screen",
      desc: "Press a hotkey and say one sentence: Super Aide reads what's on your screen and answers, or does the work for you. Free and open source, powered by Claude Code and Codex.",
      film: "Super Aide promo film",
      alt: {
        see: "Super Aide reading the exact text of every window on a Windows desktop, including notes scrolled out of view",
        ask: "An answer card under a terminal: the script's Python environment doesn't have pandas installed, and how to fix it",
        act: "After Alt+W the script runs fine; result notifications stack up in the corner",
        guide: "Numbered marks on a print dialog: choose Save as PDF, then click Save",
        route: "Requests routed to Claude Code or Codex, each with its own model and reasoning effort",
        evolve: "The self-improvement panel: cause found, code changed, tests and an independent review passed, applied",
      },
    },
    zh: {
      title: "超级助手 — 看得见屏幕的 Windows 助手",
      desc: "按一个快捷键、说一句话：超级助手看着你的屏幕回答，或者直接动手做完。免费开源，背后是 Claude Code 和 Codex。",
      film: "超级助手宣传片",
      alt: {
        see: "超级助手逐字读到桌面上每个窗口的文字，包括笔记里滚动出去的部分",
        ask: "终端下方的回答卡片：运行脚本的 Python 环境里没有安装 pandas，以及怎么解决",
        act: "按 Alt+W 之后脚本跑通了，右下角是一条条完成提示",
        guide: "打印对话框上的编号标记：先选“另存为 PDF”，再点保存",
        route: "每个请求被分到 Claude Code 或 Codex，各自选好模型和思考强度",
        evolve: "自我改进面板：找到原因、改好代码、测试和复核都通过、已生效",
      },
    },
  };

  const lang = () => (root.dataset.lang === "zh" ? "zh" : "en");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const video = document.getElementById("film-video");
  const stage = video && video.closest(".stage");

  const play = () => {
    const p = video.play();
    if (p && p.catch) p.catch(() => {});
  };

  function setFilm() {
    const l = lang();
    const src = video.dataset[l];
    if (video.dataset.current === src) return;
    video.dataset.current = src;
    video.src = src;
    play();
  }

  function applyLang() {
    const l = lang();
    const t = TEXT[l];
    document.title = t.title;
    const desc = document.querySelector('meta[name="description"]');
    if (desc) desc.content = t.desc;
    document.querySelectorAll("img[data-shot]").forEach((img) => {
      const src = `assets/shots/${img.dataset.shot}-${l}.webp`;
      if (img.getAttribute("src") !== src) img.src = src;
      img.alt = t.alt[img.dataset.shot] || "";
    });
    if (video) {
      video.poster = l === "zh" ? video.dataset.posterZh : video.dataset.posterEn;
      video.setAttribute("aria-label", t.film);
      if (video.dataset.started) setFilm();
    }
  }

  // ---------- 语言 ----------

  document.querySelectorAll("[data-toggle-lang]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const l = lang() === "zh" ? "en" : "zh";
      root.dataset.lang = l;
      root.lang = l === "zh" ? "zh-CN" : "en";
      try {
        localStorage.setItem("lang", l);
      } catch (e) {}
      const url = new URL(location.href);
      if (url.searchParams.has("lang")) {
        url.searchParams.set("lang", l);
        history.replaceState(null, "", url);
      }
      applyLang();
    }),
  );
  applyLang();

  // ---------- 最新版本（发布网站时写进 latest.json，安装器也一起放在网站上） ----------

  fetch("latest.json", { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null))
    .then((info) => {
      if (!info || !info.version) return;
      document.querySelectorAll("[data-version]").forEach((el) => (el.textContent = `v${info.version}`));
      if (info.size) document.querySelectorAll("[data-size]").forEach((el) => (el.textContent = `${Math.round(info.size / 1024)} KB`));
      if (info.file) {
        document.querySelectorAll("a[data-download]").forEach((a) => (a.href = info.file));
        if (info.github) document.querySelectorAll("a[data-github-download]").forEach((a) => (a.href = info.github));
        const mirror = document.querySelector("[data-mirror]");
        if (mirror) mirror.hidden = false;
      }
    })
    .catch(() => {});

  // ---------- 宣传片：进入视野才加载播放（静音），离开就暂停 ----------

  if (video && stage) {
    const startWithSound = () => {
      video.dataset.started = "1";
      setFilm();
      video.muted = false;
      video.currentTime = 0;
      stage.classList.add("sound");
      play();
    };

    if ("IntersectionObserver" in window) {
      new IntersectionObserver(
        (entries) =>
          entries.forEach((e) => {
            if (e.isIntersecting) {
              if (reduce && !video.dataset.started) return; // 减少动态效果时，不自动播放
              video.dataset.started = "1";
              setFilm();
              play();
            } else if (!video.paused) {
              video.pause();
            }
          }),
        { threshold: 0.3 },
      ).observe(video);
    }

    video.addEventListener("click", () => {
      if (!video.dataset.started) return startWithSound();
      video.paused ? play() : video.pause();
    });

    stage.querySelector("[data-sound]").addEventListener("click", () => {
      if (video.muted || !video.dataset.started) startWithSound();
      else {
        video.muted = true;
        stage.classList.remove("sound");
      }
    });

    document.querySelectorAll("[data-play-film]").forEach((a) =>
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        stage.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
        startWithSound();
      }),
    );
  }

  // ---------- 滚动时浮现 ----------

  const items = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !reduce) {
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        }),
      { rootMargin: "0px 0px -6% 0px" },
    );
    items.forEach((el) => io.observe(el));
  } else {
    items.forEach((el) => el.classList.add("in"));
  }
})();
