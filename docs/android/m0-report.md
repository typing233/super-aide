# 安卓端 M0：真机验证结果

测试机：荣耀 Magic5 至臻版（PGT-AN20），Android 16（API 36），MagicOS 10.0.0.175，讯飞输入法，自带助手 YOYO。
日期：2026-10-19。工具：`scripts/android/device_test.py`（adb 驱动调试版）、`scripts/android/provision.py`（把电脑上已配好的模型服务写进手机）。

## 结论

| 问题 | 结果 | 决定 |
|---|---|---|
| 打字放在哪种窗口里 | 透明 Activity：输入框贴在讯飞键盘上方，正常 | 打字的界面用透明 Activity；默认助手会话窗口只在系统真绑定了我们的服务时用 |
| 能不能当默认数字助手 | 「设置 › 应用 › 默认应用 › 数字助理应用」能选超级助手；但 MagicOS 把语音交互服务锁给 YOYO（「语音输入」里我们是灰的），系统去启动一个不存在的组件，什么都不出来 | `AssistantRoute`：我们是默认助手、服务却没被绑定 → 关掉自己的 VoiceInteractionService；用户再选一次后系统改用透明 Activity（ACTION_ASSIST）。助手键（KEYCODE_ASSIST）实测能打开 |
| 系统打开我们时读不到下面 App 的文字 | 我们的窗口一盖上，下面的 App 就不算"可交互窗口"，无障碍只给状态栏（7 个元素） | 召唤先读文字再开界面（最多等 450 ms）；系统直接打开的，窗口先设成不接触摸，读完再恢复。修好后 51～53 个元素 |
| 读屏速度 | 设置页 50 个元素：首次 204 ms，之后 12～19 ms；桌面 376 个：442 ms | 达标（目标中位数 ≤400 ms） |
| 截图 | 整屏 1312×2848 用时 135 ms；连着截第二张会被限频（code 3） | observe 不连续截图；API 34+ 只截前台 App 的窗口（我们的界面不在上面） |
| 官方 anthropic-java 在正式包（R8）里 | 不加规则会卡死（线程里抛 Error 没接住）；接住后看到 `Unresolved class: Usage$ServiceTier`（R8 去掉了 Kotlin 元数据） | 保留 `com.anthropic.core/errors/models.messages.*` 和 `kotlin.Metadata`；六个模型在混淆包里全部通过（流式、工具、看图） |
| APK 大小 | 混淆后 28 MB（dex 不压缩存放），其中 SDK + kotlin-reflect + Jackson 约 5 MB | `dex.useLegacyPackaging = true`：7.9 MB |
| 无障碍会不会被关掉 | 强行停止（清理后台、划掉最近任务）后，系统把我们从"已开启的无障碍服务"里删了 | `SelfHeal`：电脑上 `adb shell pm grant <包名> android.permission.WRITE_SECURE_SETTINGS` 一次（荣耀不用额外开关），之后 App 一起来就自己加回去，实测恢复 |

## 端到端（真实模型，电脑上的中转服务）

- 问：「这个页面上蓝牙现在是什么状态？」（设置页）→ Claude Opus 5.5 · medium，7.2 秒，不用工具，答对。
- 做：「打开设置里的「关于手机」，告诉我 MagicOS 版本号」→ Opus 5.5 · high，43 秒，4 次工具（打开设置、滚动、点击），答对，主动没念 IMEI。
- 做：「打开时钟 App，看看现在有几个闹钟」→ 25 秒，答对（4 个，2 个开着），什么都没改。
- 模型连通（工具 + 看图）：opus-5-5 首字 4.8 s / sonnet-5-5 2.3 s / haiku-5-5 2.0 s / gpt-6-astra 3.5 s / gpt-6.1-sol 3.0 s / gpt-6-luna 2.4～5.6 s。deepseek-flash 当天中转站上游 503。

## 还没验证（要用户在手机上点）

- 从手机浏览器装正式包（不是 adb 装）时的「允许受限设置」流程（M4）。
- 通知栏快捷开关：要用户在通知栏编辑里加上（安卓 13+ 设置页里有「添加」按钮直接弹系统确认）。
- MagicOS 上哪个手势会触发「数字助理应用」：长按电源键被 YOYO 占着；角落上滑手势待确认。
- 重启手机后无障碍是否还在。

## 改过的系统设置（测试机）

为验证默认助手临时改过 `voice_interaction_service`、`voice_recognition_service`，已改回原值（`com.hihonor.magicvoice/com.hihonor.magicvoice.voiceui.service.MagicVoiceInteractionService`、`com.hihonor.magicvoice/.voiceui.service.MagicVoiceRecognitionService`）。
现在留着的：默认数字助理应用 = 超级助手调试版（`assistant` 指向透明 Activity）。还原 YOYO：设置 › 应用 › 默认应用 › 数字助理应用 › 选 YOYO。
