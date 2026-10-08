# Screenshot Translator · 截图翻译工具

**框选屏幕，将译文显示在原文位置。**

面向 Windows 的截图、OCR 与翻译工具，适合阅读外文网页、软件界面和文档。

![版本](https://img.shields.io/badge/version-2.0.0-2563eb)
![系统](https://img.shields.io/badge/Windows-10%20%2F%2011-0078d4)
![架构](https://img.shields.io/badge/architecture-x64-64748b)

[下载最新版本](https://github.com/waynepan86/screenshot-translator/releases/latest) · [详细使用说明](https://github.com/waynepan86/screenshot-translator/blob/main/USER_GUIDE.md) · [更新记录](https://github.com/waynepan86/screenshot-translator/blob/main/CHANGELOG.md) · [反馈问题](https://github.com/waynepan86/screenshot-translator/issues)

## 下载与安装

支持 **Windows 10 / 11，64 位**。在 [Releases](https://github.com/waynepan86/screenshot-translator/releases/latest) 页面选择：

| 版本 | 下载文件 | 使用方式 |
| --- | --- | --- |
| 安装版，推荐 | `ScreenshotTranslator-2.0.0-Setup.exe` | 双击安装，使用快捷方式启动；支持卸载 |
| 绿色便携版 | `ScreenshotTranslator-2.0.0-Portable.zip` | 完整解压，运行其中的 `ScreenshotTranslator.exe` |

便携版请保留 `_internal`、`portable.flag` 和 `data`，不要只移动 EXE。压缩包根目录的说明文件只有本 README；详细离线帮助可在程序的 **关于 → 使用说明** 中打开。

## 三步开始使用

1. 启动程序，按 **F1**，拖动框选需要翻译的区域。
2. 点击工具栏 **翻译**，等待译文显示在原文位置。
3. 按 **Enter** 复制结果，或点击 **保存**、**贴图**。

新安装默认翻译成**简体中文**。在托盘图标的 **右键 → 设置 → 翻译** 中，可更换源语言、目标语言和翻译引擎。

| 操作 | 快捷键 / 入口 |
| --- | --- |
| 区域截图 / 全屏截图 | F1 / F2，可在设置中修改 |
| 临时查看原图 | 截图窗口中按住空格 |
| 将截图或译文置顶 | F3，或工具栏“贴图” |
| 撤销标注 / 取消截图 | Ctrl+Z / Esc |
| 查看、复制和修改识别文字 | 工具栏“提取文字” |

## 功能

- **原位翻译**：擦除原文字后排版译文，支持原图对照；放不下时保留原图，可在文字面板查看完整译文。
- **本地 OCR**：内置中英识别，英文拼写小幅纠偏自动在后台进行。
- **多种翻译服务**：DeepL、Azure、百度、有道、OpenAI 兼容接口，以及 Google / MyMemory 备用链路。
- **贴图与标注**：置顶、移动、缩放、透明度调整，支持画笔、矩形、箭头、文字和遮盖打码。
- **清晰框选**：窗口悬停高亮、单击选择窗口，也可手动拖动选区。

## 语言与翻译服务

支持简体中文、繁体中文、英语、日语、韩语、法语、德语、西班牙语、葡萄牙语、意大利语和俄语。

中英截图使用内置 OCR。其他语种请在设置中指定**截图语言**，并安装对应的 Windows OCR 语言包；目标翻译语言不需要安装语言包。

配置 DeepL：**托盘右键 → 设置 → 翻译 → DeepL → 填入 Auth Key → 测试连通性 → 保存**。程序自动区分 Free / Pro 接口。

本地 OCR 不上传截图。在线翻译会发送识别文字，DeepL 还会收到截图中的相关文字作为上下文；首选服务失败时可能回退到 Google / MyMemory，文字面板会显示实际引擎。本标准版的翻译需要网络。

## 设置与升级

| 使用方式 | 配置与缓存位置 |
| --- | --- |
| 安装版 | `%LOCALAPPDATA%\ScreenshotTranslator` |
| 便携版 | 程序旁的 `data` 文件夹 |

**设置 → 常规 → 打开数据目录** 可直接定位。截图保存位置由“默认保存路径”决定。

- 安装版更新、卸载会保留用户配置。
- 便携版升级：退出旧程序，完整解压新版，再将旧 `data` 复制到新版目录。
- 1.x 升级：exe 同目录的旧 `config.json` 会在首次启动时迁移；也可使用 **设置 → 常规 → 导入旧版配置**。原文件会保留，原有自动中英互译方向也会保留。

`config.json` 包含设置和 API 密钥，请勿公开分享或提交到仓库。

## 常见问题

**断网能用吗？** 截图、标注、贴图和本地文字识别可离线使用，翻译需要联网。

**为什么安装包较大？** 标准版携带 Qt、OCR 模型、推理运行库及背景修复组件。轻量版属于后续规划。

**译文没覆盖某段文字？** 可能是原文与译文相同、翻译失败、空间不足或背景无法可靠修复。打开“提取文字”查看该块状态和完整译文。

**首次翻译较慢？** OCR 模型需要首次加载；网络失败也可能增加等待时间。可在设置中测试翻译服务连通性。

## 开发与反馈

项目使用 **Python + PySide6**，中英 OCR 采用 RapidOCR，其他语种使用 Windows OCR，原位背景修复使用 OpenCV。

[开发与打包指南](https://github.com/waynepan86/screenshot-translator/blob/main/docs/DEVELOPMENT.md) · [提交问题](https://github.com/waynepan86/screenshot-translator/issues)

当前 2.0.0 为标准版。轻量构建、视觉 AI 增强和完整离线翻译属于后续规划。

Created by Wayne
