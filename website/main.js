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
        ask: "An answer that connects three windows: the terminal error, a line in the notes, and the deadline in a chat",
        act: "The expanded progress pill shows each step while the assistant works",
        guide: "Numbered marks on a print dialog: choose Save as PDF, then click Save",
        learn: "Learning signals flow into the router while a background duel compares the current setup with a cheaper one",
        gate: "Two small charts: the success rate holds steady while the cost per task steps down each time a cheaper setup is proven",
        lesson: "A conversation that took a wrong turn becomes a lesson: check the module name's spelling first",
        recall: "Days later, a question in other words recalls exactly one lesson; saying hi recalls none",
        improve: "The self-improvement panel: cause found, code changed, tests and an independent review passed, applied",
        personal: "Before and after a suggestion to keep answers shorter",
        community: "An improvement merged into the main version reaches every user",
      },
    },
    zh: {
      title: "超级助手 — 看得见屏幕的 Windows 助手",
      desc: "按一个快捷键、说一句话：超级助手看着你的屏幕回答，或者直接动手做完。免费开源，背后是 Claude Code 和 Codex。",
      film: "超级助手宣传片",
      alt: {
        see: "超级助手逐字读到桌面上每个窗口的文字，包括笔记里滚动出去的部分",
        ask: "一句回答串起三个窗口：终端里的报错、笔记里的一行、聊天里的截止时间",
        act: "展开的操作胶囊里能看到助手正在做的每一步",
        guide: "打印对话框上的编号标记：先选“另存为 PDF”，再点保存",
        learn: "学习信号流进路由，后台对比在比较现在用的配置和更省的配置",
        gate: "两个小图：成功率一直不降，每证明一次更省的配置，每次的花费就降一档",
        lesson: "一段走了弯路的对话，总结成一条经验：先核对模块名拼写",
        recall: "几天后换个说法问，只想起那一条经验；说一句你好，一条也不带",
        improve: "自我改进面板：找到原因、改好代码、测试和复核都通过、已生效",
        personal: "按“回答再短一点”的建议改进前后的对比",
        community: "合进主版本的改进，推送到每一位用户",
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

  // 首屏先循环播放 14 秒的预告（静音、文件小）；点"看宣传片"或"打开声音"才换成整部片子
  let full = false;

  function setFilm() {
    const l = lang();
    const src = full ? video.dataset[l] : video.dataset[l === "zh" ? "teaserZh" : "teaserEn"];
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
      full = true;
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
