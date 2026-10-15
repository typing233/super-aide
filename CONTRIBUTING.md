# 参与贡献 / Contributing

[中文](#中文) · [English](#english)

## 中文

超级助手欢迎两种贡献：你自己写的改动，和超级助手**自我改进**后自动提交的改动（社区共建）。

### 自我改进自动提交的 PR

在 **设置 → 高级 → 参与社区共建** 里用 GitHub 账号登录（设备码登录，权限 `public_repo`）后，在你电脑上生效、稳定运行一天的改进，会以你的账号向本仓库提交 PR：

- 标题以 `[aide]` 开头，说明里只有"改了什么、为什么、怎么测的"、版本号和用到的模型，末尾带一个问题指纹（`aide-sig:…`）。
- PR 里**只有代码改动**，不带你的问题、回答、屏幕内容和日志。提交前会扫描新增的内容，发现疑似个人信息（本机路径、计算机名、邮箱、手机号、令牌、对话里的原文）就不自动提交，先在设置里问你。
- 同一个问题已经有人提交过（指纹相同）时，不会重复开 PR，只在那个 PR 上点 👍——遇到的人越多，越优先处理。
- 可以随时在设置里关掉，或者在 GitHub 的 **Settings → Applications** 里撤销授权。

### 维护者怎么处理

- CI 照常跑全部测试。
- 维护者的超级助手只读地审每个 `[aide]` PR（不运行 PR 里的代码）：对不对、范围、安全、隐私、是否和别的 PR 重复，给出"建议合并 / 有问题 / 重复"。
- **由维护者决定合并**，从不自动合并。合并以后自动发一个补丁版本（维护者不想发的，合并前打上 `skip-release` 标签）。大家更新时，本地那份改进会被认出"已包含"，自动丢掉。

### 许可

按 [GitHub 服务条款 D.6](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#6-contributions-under-repository-license)（inbound = outbound），向本仓库提交的内容按本仓库的 [MIT 许可](LICENSE) 授权，不需要另签贡献者协议。

### 自己写改动

- 界面文字以中文为准：Python 里用 `tr("中文")`，英文写在 `src/super_aide/locales/en_*.py`；网页里用 `data-i18n` 或 `I18N.t("中文")`，英文写在 `src/super_aide/ui/web/i18n-en.js`。
- 不为某个应用写特殊代码；踩坑的经验不往常驻指令里堆。设计和原则见 [docs/design.md](docs/design.md)。
- 提交前跑 `uv run python -m pytest -q`。

## English

Super Aide welcomes two kinds of contributions: changes you write yourself, and changes Super Aide submits automatically after **improving itself** (community contributions).

### Pull requests from self-improvement

After you sign in with GitHub in **Settings → Advanced → Contribute to the community** (device-code sign-in, `public_repo` scope), improvements that were applied on your PC and ran stably for a day are submitted to this repository as pull requests under your account:

- The title starts with `[aide]`. The description only says what changed, why and how it was tested, plus the version and model used, and ends with a problem fingerprint (`aide-sig:…`).
- The PR contains **code changes only**, never your questions, answers, screen content or logs. Before submitting, the added lines are scanned; anything that looks like personal info (local paths, computer name, email, phone number, tokens, text from the conversation) is not submitted automatically, and Settings asks you first.
- If the same problem was already submitted (same fingerprint), no duplicate PR is opened; it adds a 👍 to the existing one instead, so the most common problems get attention first.
- You can turn it off in Settings any time, or revoke access in GitHub **Settings → Applications**.

### How the maintainer handles them

- CI runs the full test suite as usual.
- The maintainer's Super Aide reviews every `[aide]` PR read-only (it never runs the PR's code): correctness, scope, security, privacy, duplicates — and suggests merge, problems or duplicate.
- **The maintainer decides what gets merged**; nothing is merged automatically. A merged PR is published as a patch release automatically (the maintainer can add the `skip-release` label before merging to opt out). When people update, their local copy of that improvement is recognized as included and dropped.

### License

Under [section D.6 of the GitHub Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service#6-contributions-under-repository-license) (inbound = outbound), anything you submit to this repository is licensed under its [MIT license](LICENSE); no separate contributor agreement is needed.

### Writing changes yourself

- UI text is written in Chinese first: `tr("中文")` in Python with English in `src/super_aide/locales/en_*.py`; `data-i18n` or `I18N.t("中文")` in the web UI with English in `src/super_aide/ui/web/i18n-en.js`.
- No app-specific code; don't pile lessons into always-loaded instructions. See [docs/design.md](docs/design.md) for the design and principles.
- Run `uv run python -m pytest -q` before submitting.
