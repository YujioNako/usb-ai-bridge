# v0.4.0-rc.1 — 首个整理后的源码预发布

包含 Pi 管理端、Windows 文件/文档/浏览器执行端、离线网页控制台和 USB SSH 维护终端的完整自有源码。整理后的安装器默认纯 USB 串口，不启用 USB 网卡；首次生成独立密钥，保留下载摘要校验，并支持失败恢复。

提供 Windows 完整离线包、Pi 安装源码包和 SHA-256 清单。README 分别说明系统版本、首次联网准备、Pi/Windows 安装、三种密码、模型登录、维护和故障排查。

适用基线是 Zero 2 W + Raspberry Pi OS Bullseye arm64 + Windows 11 x64。新安装器尚未在一张全新 TF 卡上完整验收，因此本次标记为预发布；Bookworm/Trixie/NetworkManager 尚未适配。具体测试结果随发布前校验更新。

不包含账号凭据、代理订阅、Wi-Fi 密码、私人文件或整卡镜像。已部署的 Pi 不需要为取得 Windows 完整包而重新刷卡。

验证结果：13 组 Pi 业务回归、7 项安装器单元测试、Windows 鉴权/维护路由/登录恢复测试均通过；从发行 ZIP 解压后，内置 Node、XLS/XLSX、DOCX、PDF、ZIP 解析及网页资源离线自检通过。源码未检出原设备凭据。Linux PTY 在本次 Windows 构建环境未重跑，之前已在 Pi 上验证。

- Windows 用户下载 `USB-AI-Windows-v0.4.0-rc.1-Full.zip`，无需旧包或增量更新。
- Pi 新装下载 `USB-AI-Pi-v0.4.0-rc.1-Source.tar.gz` 并按 README 操作；首次安装需要外网。
- `USB-AI-v0.4.0-rc.1-Source.zip` 是独立完整源码归档。
- 校验值见 `SHA256SUMS.txt`。管理密钥和账号信息需要自行配置，未随包提供。
