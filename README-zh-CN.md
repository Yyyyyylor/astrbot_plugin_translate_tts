# AstrBot 翻译 TTS

简体中文 | [English](README.md)

Translate TTS 只改写“原有 AstrBot 链路已经决定送入 TTS”的文本：界面仍保留原语言回答，原链路选中的 TTS provider 接收目标语言译文。默认目标语言为日语。

本插件不会新增语音触发条件，不会改写主聊天回答，不会替换 TTS provider 或音色，也不会修改 AstrBot 或主动聊天插件的磁盘源码。

## 兼容性与当前验证结论

| 组件 | 支持基线 | 当前证据 |
| --- | --- | --- |
| AstrBot | `>=4.27.5,<4.28`，按 4.27.5 实现 | 单元测试，以及使用假翻译服务和假 TTS provider 的 4.27.5 只读源码/集成探针 |
| 平台 | `qq_official` | 本机配置快照中只有一个已启用的 `qq_official` 平台；尚未验证真实 QQ 送达和播放 |
| 回答模式 | 非流式 | 已做单元测试；流式结果会主动透传 |
| `astrbot_plugin_proactive_chat` | 仅 v1.2.5；参考 commit `d1203524f29be248a4975bac1f7586e9557434ee` | 本机磁盘源码全部匹配固定指纹；当前没有可核验的已加载运行实例 |
| LLM/TTS provider | AstrBot 中已配置的 provider | 仅使用假 provider 验证；尚未联调真实模型翻译和目标语言语音 |

精确运行状态、源码探针和真实环境验收清单见[兼容性与诊断](docs/compatibility.md)。

以上本机检查是 2026-09-06 的离线快照：未发现 AstrBot/Python/uvicorn 后端进程，Translate TTS 也尚未安装到实际插件目录。因此，它不能证明运行时包装已启用，更不能证明 QQ、模型或 TTS 的实际行为。

## 行为说明

- 上游未调用 TTS 时，本插件不会调用翻译模型。
- 上游调用 TTS 时，原文保留一份，译文由原 TTS provider 合成。
- 翻译使用独立、无聊天历史的 `llm_generate` 请求，不调用工具，也不把译文追加到会话历史。
- 翻译异常、超时、输出无效或超过限制时，使用完整原文合成，不截断回答。
- 译文合成异常或没有返回音频时，最多再用原文尝试一次。任务取消会向上传播，不启动回退。
- 普通回答沿用既有 TTS 概率和开关。
- 主动聊天沿用既有 TTS 开关、分段、装饰钩子、发送间隔和历史逻辑；插件只复制本次配置并强制发送原文，不修改会话数据。

用户看到的仍是原语言文本，不显示译文。文本与语音的先后顺序由原链路决定。

## 安装

1. 停止 AstrBot，或在维护窗口使用插件管理器。
2. 创建 `AstrBot/data/plugins/astrbot_plugin_translate_tts`，再复制运行所需的 `__init__.py`、`main.py`、`config.py`、`scope.py`、`translation.py`、`tts_proxy.py`、`metadata.yaml`、`_conf_schema.json`、`.astrbot-plugin` 和 `compat` 目录。
3. 不要把本开发工作区中的 `data`、`temp`、缓存、数据库或配置产物复制到生产环境；文档和测试文件不是运行必需项。
4. 启动 AstrBot，或在 **WebUI > 插件** 中重载。
5. 在插件配置中选择翻译 LLM 与目标语言，保存后再重载一次。

设置面板支持简体中文和英文。使用 AstrBot WebUI 的语言选择按钮选择 **中文** 或 **English**，插件名称、设置说明、提示和目标语言选项会随之切换。首次安装或更新 `.astrbot-plugin/i18n` 文件后请重载插件。

本插件没有额外第三方 Python 依赖。AstrBot 必须已有可用的 LLM 和 TTS provider。主动消息还需单独安装受支持版本的主动聊天插件。

## 配置

| 字段 | 默认值 | 可接受值与作用 |
| --- | --- | --- |
| `enabled` | `true` | 总开关；关闭时两条适配链路均透传。 |
| `translation_provider_id` | 空 | WebUI LLM 选择器。留空时解析当前会话 provider；明确选择的 provider 不可用时回退原文 TTS。 |
| `target_language` | `ja` | `ja`、`en`、`ko`、`zh-CN`、`zh-TW`、`fr`、`de`、`es` 或 `custom`。 |
| `custom_target_language` | 空 | 目标为 `custom` 时必须填写非空语言名称。 |
| `translation_timeout_seconds` | `15` | 包括等待并发名额的总超时；范围 1–120 秒。 |
| `max_input_chars` | `4000` | 范围 1–100000；超限时完整原文绕过翻译。 |
| `max_output_chars` | `12000` | 范围 1–200000；超长模型输出会被拒绝。 |
| `max_concurrent_translations` | `2` | 范围 1–100；仅限制本插件实例。 |
| `enable_proactive_compat` | `true` | 启用主动聊天 v1.2.5 运行时适配。 |

AstrBot 生成配置示例（优先在 WebUI 中编辑）：

```json
{
  "enabled": true,
  "translation_provider_id": "",
  "target_language": "ja",
  "custom_target_language": "",
  "translation_timeout_seconds": 15,
  "max_input_chars": 4000,
  "max_output_chars": 12000,
  "max_concurrent_translations": 2,
  "enable_proactive_compat": true
}
```

留空翻译 provider 时，AstrBot 必须能为会话解析出当前聊天 provider。所选 TTS 模型和音色必须支持目标语言；仅翻译文本不能让单语音色获得新语言能力。

## 重载、禁用与升级

- <strong>重载：</strong> 保存配置后从 WebUI 重载。运行时包装带安装代次；新代次会停用旧代次，不叠加调用。
- <strong>禁用：</strong> 将 `enabled=false` 后重载，或在 WebUI 禁用/卸载。本插件只在属性仍指向自己的包装时恢复它，不覆盖后来安装的第三方包装。
- <strong>仅禁用主动兼容：</strong> 将 `enable_proactive_compat=false` 后重载；普通非流式回答仍可工作。
- <strong>升级：</strong> 停止插件后替换文件，再启动/重载并检查兼容日志；在 WebUI 核对旧的自定义语言配置。

升级到支持范围外时，对应适配器会以 `incompatible` 关闭该路径，不猜测变更后的内部 API。

## 诊断与故障排查

在日志中搜索 `Translate TTS normal compatibility` 和 `Translate TTS proactive compatibility`。正常运行状态是 `signature_compatible_unverified`：所需签名匹配，但不证明特定源码 commit，也不证明 QQ 已实际收到或播放。

- <strong>没有译文语音，也没有翻译请求：</strong> 确认上游 TTS 确实触发、结果为非流式、本插件在会话启用，并已选择 TTS provider。
- <strong>仍播放原语言：</strong> 检查附近的 `TTS translation fallback` 日志，并核对 provider、超时、长度上限和自定义目标语言。
- <strong>译文合成后又尝试原文：</strong> 音色可能不支持目标语言，或 provider 返回空结果。
- <strong>看不到原文：</strong> 确认适配器不是 `incompatible`；主动聊天元数据必须恰为 `1.2.5`。
- <strong>主动适配为 `not_installed`：</strong> 加载/启用主动聊天，必要时重载本插件。
- <strong>重载后语音重复：</strong> 依次卸载两个插件，先加载主动聊天，再加载本插件；保留 `superseded`/签名日志。

本插件只记录来源类别、回退原因、异常类型和兼容状态，不主动记录原文、译文或密钥；AstrBot 本体和 provider 可能有各自日志策略。

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
