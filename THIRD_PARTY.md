# 第三方来源与许可证

- Node.js 24.21.0：Windows 完整包包含官方二进制，许可证在 runtime/LICENSE。来源 https://nodejs.org/ 。
- xterm.js 5.5.0 / addon-fit 0.10.0：MIT，许可证在前端目录的 xterm.LICENSE、xterm-fit.LICENSE；来源 https://github.com/xtermjs/xterm.js 。
- markdown-it：许可证在前端目录 markdown-it.LICENSE；来源 https://github.com/markdown-it/markdown-it 。
- 文档解析依赖（pdfjs-dist、xlsx、word-extractor、yauzl、dommatrix 及传递依赖）：确切版本和下载摘要见 windows/documents/package-lock.json，Windows 完整包随依赖保留各自 LICENSE/NOTICE。主要项目采用各自 MIT/Apache 等许可证，不能用本项目统一替代。
- Mihomo：来源 https://github.com/MetaCubeX/mihomo ，按其 GPL-3.0 等上游声明提供。安装器从官方 Release 下载并校验，不在本仓库复制其源码或二进制。
- Codex、code-mode-host、bwrap：安装器使用 openai/codex 官方 0.155.1 Release 附件及其摘要，来源 https://github.com/openai/codex/releases/tag/rust-v0.155.1 。Codex 与捆绑组件各自的许可以上游仓库、发行说明和 notices 为准。
- 可选 GPIO 功能运行时依赖 Raspberry Pi 的 RPi.GPIO、Linux uinput；屏幕唤醒代码用于适配厂商 Waveshare_fbcp 工程，并非完整显示驱动。

对第三方组件的修改、再分发或独立使用，需保留其要求的版权和许可文件。本仓库未为自有代码额外指定统一开源许可证；公开可见不代表自动授予额外许可，后续可由仓库所有者选择。
