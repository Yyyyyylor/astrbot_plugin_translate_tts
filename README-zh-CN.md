# AstrBot 翻译 TTS

简体中文 | [English](README.md)

Translate TTS 只改写“原有 AstrBot 链路已经决定送入 TTS”的文本：界面仍保留原语言回答，真实 AstrBot TTS provider 实例接收目标语言译文。默认目标语言为日语；基础情感默认开启，并在 Fish 选择明确时优先使用 `s2.1-pro-free`。

本插件不会新增语音触发条件，不会改写主聊天回答，不会修改共享 TTS provider 的音色/设置，也不会修改 AstrBot 或主动聊天插件的磁盘源码。

## 兼容性与当前验证结论

| 组件 | 支持基线 | 当前证据 |
| --- | --- | --- |
| AstrBot | `>=4.27.5,<4.28`，按 4.27.5 实现 | 单元测试，以及使用假翻译服务和假 TTS provider 的 4.27.5 只读源码/集成探针 |
| 平台 | `qq_official` | 本机配置快照中只有一个已启用的 `qq_official` 平台；尚未验证真实 QQ 送达和播放 |
| 回答模式 | 非流式 | 已做单元测试；流式结果会主动透传 |
| `astrbot_plugin_proactive_chat` | 仅 v1.2.5；参考 commit `d1203524f29be248a4975bac1f7586e9557434ee` | 本机磁盘源码全部匹配固定指纹；当前没有可核验的已加载运行实例 |
| LLM/TTS provider | AstrBot 已配置实例；Fish、ElevenLabs v3、MiniMax Speech 02/2.6、Gemini TTS 情感适配 | 已用假 transport 对真实 4.27.5 provider 序列化离线验证；尚未真实合成和试听 |

精确运行状态、源码探针和真实环境验收清单见[兼容性与诊断](docs/compatibility.md)。

以上本机检查是 2026-09-06 的离线快照：未发现 AstrBot/Python/uvicorn 后端进程，Translate TTS 也尚未安装到实际插件目录。因此，它不能证明运行时包装已启用，更不能证明 QQ、模型或 TTS 的实际行为。

## 行为说明

- 上游未调用 TTS 时，本插件不会调用翻译模型。
- 上游调用 TTS 时，原文保留一份，译文由原 TTS provider 合成。
- 情感开启时，翻译与基础情感通过同一次严格 JSON `llm_generate` 请求完成，不调用工具，也不向会话历史追加内容。
- provider 控制仅存在于本次调用；未知 provider/型号只接收纯译文，不虚构请求参数。
- 翻译异常、超时、输出无效或超过限制时，使用完整原文合成，不截断回答。
- 译文合成异常或没有返回音频时，最多再用原文尝试一次。任务取消会向上传播，不启动回退。
- 普通回答沿用既有 TTS 概率和开关。
- 主动聊天沿用既有 TTS 开关、分段、装饰钩子、发送间隔和历史逻辑；插件只复制本次配置并强制发送原文，不修改会话数据。

用户看到的仍是原语言文本，不显示译文。文本与语音的先后顺序由原链路决定。

## 安装

1. 从 [v1.2.1 Release](https://github.com/Yyyyyylor/astrbot_plugin_translate_tts/releases/tag/v1.2.1) 下载 `astrbot_plugin_translate_tts-v1.2.1.zip`。
2. 在 AstrBot WebUI 的插件管理器中安装该 ZIP，或将 ZIP 根目录中的文件解压到 `AstrBot/data/plugins/astrbot_plugin_translate_tts`。
3. 不要把本开发工作区中的 `data`、`temp`、缓存、数据库或配置产物复制到生产环境；文档和测试文件不是运行必需项。
4. 启动 AstrBot，或在 **WebUI > 插件** 中重载。
5. 在插件配置中选择翻译 LLM 与目标语言，保存后再重载一次。

设置面板支持简体中文和英文。使用 AstrBot WebUI 的语言选择按钮选择 **中文** 或 **English**，插件名称、设置说明、提示和目标语言选项会随之切换。首次安装或更新 `.astrbot-plugin/i18n` 文件后请重载插件。

本插件没有额外第三方 Python 依赖。AstrBot 必须已有可用的 LLM 和 TTS provider。主动消息还需单独安装受支持版本的主动聊天插件。

## 配置

### 1.2 新增高级控制

原生设置页现已提供翻译/情感提示词模式、全部预处理规则、清理保留期与周期、试听默认值以及回复级情感连续性。自定义提示词只接受 `{target_language}`、`{emotion_options}`、`{fish_cues}` 这三个受控占位符。未知占位符或空的“完全替换”提示词会产生配置错误并安全停用插件。不可替换的输出契约及原有 JSON/文本、拒答、工具调用、枚举和长度校验始终生效。

**Translate TTS 控制台** 插件 Page 承载 Schema 不能安全表达的操作：分别恢复翻译/情感默认提示词、只做本地处理的预处理预览、清理状态、二次确认的立即清理，以及管理员认证的 TTS 试听。试听第一步只显示 provider 类型、实例 ID、模型、音色、目标语言、情感协议和可能产生费用的提示；第二次确认后才合成。页面支持取消和短时认证下载。聊天管理员也可使用 `/tts_preview [文本]`，随后执行 `/tts_preview_confirm <令牌>`，或用 `/tts_preview_cancel` 取消。

预处理始终保留未经处理的原文，用于界面显示和原文 TTS 回退。预处理结果为空时，不调用翻译或新增 TTS。连续性只保存在当前 `TranslationScope`，支持 `off`、`conservative`、`allow_transition`、`fixed_first`，并可设置 neutral 继承及最大分段数；原文回退和第二次合成始终使用不带动态情感的原文。

自动清理默认关闭；启用后的默认保留期为 30 天。只有本插件真实返回、位于 AstrBot 临时目录且写入私有清单的本地音频才可能被删除。HTTP URL、目录、符号链接、未登记文件、目录外文件和刚登记文件都会被排除；清理仅逐个删除目标文件，绝不递归清空共享目录。

| 字段 | 默认值 | 可接受值与作用 |
| --- | --- | --- |
| `enabled` | `true` | 总开关；关闭时两条适配链路均透传。 |
| `emotion_enabled` | `true` | 启用结构化情感判断和已适配 provider 控制；关闭后仍保留翻译与 provider 选择。 |
| `tts_provider_id` | 空 | 原生 TTS 选择器；有效 ID 优先，无效显式 ID 保持原上游链路。 |
| `tts_selection_mode` | `prefer_fish` | 空 ID 时优先原 Fish 或唯一 Fish；`follow_upstream` 沿用上游。 |
| `fish_model` | `s2.1-pro-free` | Fish 严格白名单型号；真实 HTTP header 显式携带，失败不回退付费型号。 |
| `translation_provider_id` | 空 | WebUI LLM 选择器。留空时解析当前会话 provider；明确选择的 provider 不可用时回退原文 TTS。 |
| `target_language` | `ja` | `ja`、`en`、`ko`、`zh-CN`、`zh-TW`、`fr`、`de`、`es` 或 `custom`。 |
| `custom_target_language` | 空 | 目标为 `custom` 时必须填写非空语言名称。 |
| `translation_timeout_seconds` | `60` | 获取并发名额后的 LLM 调用截止时间；范围 1–300 秒，不覆盖 provider 自身的 HTTP/SDK 超时。 |
| `translation_queue_timeout_seconds` | `10` | 等待插件翻译并发名额的最长时间；范围 1–60 秒。 |
| `max_input_chars` | `4000` | 范围 1–100000；超限时完整原文绕过翻译。 |
| `max_output_chars` | `12000` | 范围 1–200000；超长模型输出会被拒绝。 |
| `max_concurrent_translations` | `2` | 范围 1–100；仅限制本插件实例。 |
| `enable_proactive_compat` | `true` | 启用主动聊天 v1.2.5 运行时适配。 |
| `diagnostic_log_level` | `normal` | `minimal`、`normal` 或 `verbose`；绝不包含消息、译文、endpoint/代理地址或凭据。 |
| `diagnostic_event_buffer_size` | `100` | 在内存中保留 20–500 条管理员安全事件；重载即清空。 |
| `slow_phase_warning_seconds` | `15` | 翻译或 TTS 超过该时长时记录警告。 |

AstrBot 生成配置示例（优先在 WebUI 中编辑）：

```json
{
  "enabled": true,
  "emotion_enabled": true,
  "tts_provider_id": "",
  "tts_selection_mode": "prefer_fish",
  "fish_model": "s2.1-pro-free",
  "translation_provider_id": "",
  "target_language": "ja",
  "custom_target_language": "",
  "translation_timeout_seconds": 60,
  "translation_queue_timeout_seconds": 10,
  "max_input_chars": 4000,
  "max_output_chars": 12000,
  "max_concurrent_translations": 2,
  "enable_proactive_compat": true
}
```

留空翻译 provider 时，AstrBot 必须能为会话解析出当前聊天 provider。所选 TTS 模型和音色必须支持目标语言；仅翻译文本不能让单语音色获得新语言能力。

Fish 免费开发档应在适合当前账户时把 Fish provider 配置为官方 `https://api.fish.audio/v1` endpoint。本插件保留原 endpoint，绝不会把凭据擅自转发到另一域名。

### 情感适配矩阵

| AstrBot provider 类型 | 已适配模型 | 请求控制 |
| --- | --- | --- |
| `fishaudio_tts_api` | `s2.1-pro-free`、`s2.1-pro`、`s2-pro`、`s1` | 完整文档集合：49 个情感、6 个语气、11 个声音效果、5 个特殊效果；最多组合 3 个；S2 方括号或 S1 固定圆括号 |
| `elevenlabs_tts_api` | 仅 `eleven_v3` | 白名单 v3 audio tag |
| `minimax_tts_api` | `speech-02-hd/turbo`、`speech-2.6-hd/turbo` | 调用副本的 `voice_setting.emotion` |
| `gemini_tts` | Gemini 2.5 Flash/Pro Preview TTS、3.1 Flash TTS Preview | 调用副本的语气指令与明确 transcript |
| 其他类型/型号 | 仅翻译 | 不发送、也不宣称情感控制 |

Fish 路径会在同一次翻译调用中返回白名单 `fish_cues` 和可选 `fish_segments`。分段可实现逐句转场和短语级 emphasis，但所有分段正文必须逐字拼回纯译文。插件只接受 [Fish 情感控制官方参考](https://docs.fish.audio/developer-guide/core-features/emotions)列出的精确标签；未知、重复或超过三个的标签会被丢弃，声音效果仅在原文明示时选择。S1 会自动拒绝仅 S2 支持的 `emphasis` 与 `clear throat`。

## 重载、禁用与升级

- <strong>重载：</strong> 保存配置后从 WebUI 重载。运行时包装带安装代次；新代次会停用旧代次，不叠加调用。
- <strong>禁用：</strong> 将 `enabled=false` 后重载，或在 WebUI 禁用/卸载。本插件只在属性仍指向自己的包装时恢复它，不覆盖后来安装的第三方包装。
- <strong>仅禁用主动兼容：</strong> 将 `enable_proactive_compat=false` 后重载；普通非流式回答仍可工作。
- <strong>升级：</strong> 停止插件后替换文件，再启动/重载并检查兼容日志；在 WebUI 核对旧的自定义语言配置。

升级到支持范围外时，对应适配器会以 `incompatible` 关闭该路径，不猜测变更后的内部 API。

## 诊断与故障排查

在日志中搜索 `Translate TTS normal compatibility` 和 `Translate TTS proactive compatibility`。正常运行状态是 `signature_compatible_unverified`：所需签名匹配，但不证明特定源码 commit，也不证明 QQ 已实际收到或播放。

- <strong>没有译文语音，也没有翻译请求：</strong> 确认上游 TTS 确实触发、结果为非流式、本插件在会话启用，并已选择 TTS provider。
- <strong>`reason=queue_timeout`：</strong> 插件未能取得翻译并发名额；可谨慎提高 `translation_queue_timeout_seconds` 或 `max_concurrent_translations`。
- <strong>`reason=plugin_deadline`：</strong> 插件设置的 LLM 调用截止时间已到；可提高 `translation_timeout_seconds`，或选择更快的专用翻译 provider。
- <strong>`reason=provider_timeout`：</strong> 所选 LLM provider 自身的 HTTP/SDK 超时；必须调整该 provider 的 timeout/代理，仅提高插件 timeout 无法解决。
- <strong>Docker 代理：</strong> 翻译 provider 必须能从容器内部访问代理。宿主机代理若写为 `127.0.0.1`，实际指向容器本身；请改用容器可访问的主机名/地址，并先在 AstrBot WebUI 测试 provider。
- <strong>QQ Official `APIReturnNoneError`：</strong> 这是 botpy 返回 `None` 后由 AstrBot QQ 适配器抛出的重试异常，与翻译异常分离。若随后出现 `Websocket session starting`，说明 QQ 连接发生波动；请检查容器出口、全局代理和 QQ 凭据，并在禁用本插件时测试普通纯文本回复。
- <strong>译文合成后又尝试原文：</strong> 音色可能不支持目标语言，或 provider 返回空结果。
- <strong>看不到原文：</strong> 确认适配器不是 `incompatible`；主动聊天元数据必须恰为 `1.2.5`。
- <strong>主动适配为 `not_installed`：</strong> 加载/启用主动聊天，必要时重载本插件。
- <strong>重载后语音重复：</strong> 依次卸载两个插件，先加载主动聊天，再加载本插件；保留 `superseded`/签名日志。

管理员可使用 `/tts_diagnostics`，或打开控制台中的“诊断”卡片，查看当前不可变 timeout、provider 哈希引用、provider 类型和内部 timeout、代理来源是否存在、各阶段耗时与最近结果。`diagnostic_log_level=verbose` 会把全部安全阶段事件写入 AstrBot 日志；内存事件有数量上限，重载即清空。

插件绝不记录原文、译文、提示词、响应内容、endpoint、代理地址、令牌或凭据。异常只记录类型链，不记录异常消息；AstrBot 本体和 provider 可能有各自日志策略。

## 隐私与安全

原链路选中用于 TTS 的文本会发送给翻译 LLM provider；译文（或回退原文）会发送给 TTS provider。请检查两者的留存和网络策略。翻译请求不带聊天历史、图片、音频、工具或人格，但原文本身仍可能敏感。

本插件不持久化译文，只安装运行时包装，不修改 AstrBot、主动聊天源码或共享会话配置字典。

## 开发与测试

在包含 `translate_tts` 包的父目录运行：

```powershell
python -m pytest translate_tts\tests
ruff check translate_tts
ruff format --check translate_tts
```

显式运行的只读源码探针及其边界见[兼容性与诊断](docs/compatibility.md)。单元测试与探针都不会访问真实 LLM、TTS 服务或 QQ。

## 许可证

MIT，详见 [LICENSE](LICENSE)。
