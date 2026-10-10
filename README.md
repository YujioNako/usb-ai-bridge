# USB AI Bridge

[下载 v0.4.0-rc.1 完整安装包](https://github.com/YujioNako/usb-ai-bridge/releases/tag/v0.4.0-rc.1) · [安装与故障排查](docs/TROUBLESHOOTING.md)

让 Raspberry Pi Zero 2 W 连接外部 AI，让 Windows 11 通过 **USB 串口**使用对话、文件和浏览器工具。

Pi 负责联网、代理、模型账号和会话；Windows 负责显示本地网页、执行用户允许的文件/浏览器操作。USB 不创建网卡，不更改 Windows 默认网关。项目另带一个离线可用的 Pi SSH 维护终端。

这是独立开发的控制台，不是 OpenAI 官方客户端。只在你有权管理、且组织允许连接此类设备和处理相关文件的电脑上使用。发送给模型的提示词、附件内容和工具结果可能离开本机；选择工作目录和审批方式前，应确认这些内容允许交给相应 AI 服务。

## 先选你要做的事

| 你的情况 | 从哪里开始 |
| --- | --- |
| Pi 已经部署好，只换一台 Windows 电脑 | [Windows 安装](#windows-端约-5-分钟) |
| 一张新 TF 卡、一台新 Pi | [Pi 从零安装](#pi-端从零安装) |
| Wi-Fi 断了，需要修 Pi | [USB SSH 维护终端](#断网时怎么修-pi) |
| 已安装旧版，想更新源码 | [升级与备份](docs/UPGRADE.md) |
| 想自己改代码、构建安装包 | [开发与构建](docs/DEVELOPMENT.md) |

## 能做什么

- ChatGPT/Codex 账号登录，或配置兼容的模型 API；账号可用性、模型和额度取决于服务提供方。
- 会话归档、删除、编辑旧提问后重新生成、换模型生成；保留不同分支。
- 全局模型与审批默认值，以及每个会话的独立设置；思考强度和快速模式按模型支持情况使用。
- Markdown、代码块、工具折叠、生成状态与流式恢复；查看 token 和参考费用。
- 选择、拖放、粘贴图片及文件；Windows 文件剪贴板入口；表格、Word、文字 PDF、ZIP 按需读取。
- 限定工作目录中的文件操作、独立 Edge/Chrome 浏览器，以及按审批方式执行命令。
- 插件/工作流、定时任务、Wi-Fi 扫描与切换、代理订阅管理。
- USB SSH 终端：即使 Wi-Fi 或 AI 管理服务不可用，仍可通过已运行的串口服务登录 Pi 维修。

当前边界：不是完整复刻官方 Codex；扫描 PDF 不内置 OCR，RAR/7z 不内置解压；插件兼容性取决于插件本身。Wi-Fi 管理目前使用 `wpa_supplicant`，没有适配 NetworkManager。登录界面软键盘仍是实验功能，不应把它当作唯一恢复手段。

## 下载哪个文件

打开本仓库右侧 **Releases**，进入目标版本：

| 文件 | 用途 |
| --- | --- |
| `USB-AI-Windows-…-Full.zip` | **Windows 用户下载这个**：完整离线客户端，内置 Node.js、串口程序、文档依赖和网页，无需旧包或 npm |
| `USB-AI-Pi-…-Source.tar.gz` | Pi 安装源码，含安装程序；首次安装仍需联网下载系统依赖和官方运行组件 |
| `SHA256SUMS.txt` | 下载文件的校验值 |
| GitHub 自动生成的 `Source code` | 全部项目源码，开发者使用；不能代替 Windows 完整包直接双击运行 |

发行包没有你的管理密钥、ChatGPT 登录、API 密钥、订阅地址、Wi-Fi 密码或工作文件。Pi 不需要 ESP32，不要求安装屏幕、按钮或蜂鸣器。

## 准备清单

- Raspberry Pi **Zero 2 W**；原版 Zero W 不是本安装器的目标。
- 至少 16 GB 的可靠 TF 卡、读卡器；安装前请备份卡中数据。
- 支持数据传输的 micro-USB 线。Pi 应连接标有 **USB** 的数据口，而不是仅供电的 **PWR IN** 口。
- Windows 11 x64，已有 Edge 或 Chrome。
- Pi 可连接的 2.4 GHz WPA2 Wi-Fi/手机热点；首次安装应在允许外网访问的网络中完成。
- 可用的 AI 账号或 API 服务。需要代理时，准备你自己的 Clash YAML 订阅。

**系统兼容性：**当前实际开发和部署基线是 Raspberry Pi OS **Bullseye 64 位**、Python 3.9、`wpa_supplicant`。这是旧版系统兼容基线，不代表所有 Raspberry Pi OS 均已支持。Bookworm/Trixie 和 NetworkManager 暂不支持，安装器会停止；不要通过强行关闭网络管理器绕过检测。安装器的从零流程经过代码检查与模拟测试，尚未声称在一张全新 TF 卡上完整验收。

## Pi 端：从零安装

### 1. 给 TF 卡写入适配的系统

从 [Raspberry Pi 官方下载站](https://downloads.raspberrypi.com/raspios_arm64/images/) 查找带 `bullseye-arm64` 的系统镜像，用 [Raspberry Pi Imager](https://www.raspberrypi.com/software/) 的自定义镜像选项写入。

在 Imager 的系统设置里，设置你自己的用户名和密码，例如用户名 `piuser`；填写 Wi-Fi 名称、密码和正确的国家/地区，并开启 SSH。本文的 `piuser` 都只是示例，必须换成你实际创建的用户名。不要把密码设为空。

写入后将卡插入 Pi，开机等待数分钟。从路由器/热点的设备列表找到 Pi 的 IP。在 Windows PowerShell 中输入：

```powershell
ssh piuser@你的Pi地址
```

首次连接按 SSH 提示核对并接受设备主机密钥。密码输入时不显示星号，这是正常现象。成功后应看到 Pi 的命令行。无法登录请先解决此步骤，不要继续运行安装器。

在 Pi 中执行：

```sh
uname -m
cat /etc/os-release
```

前者必须是 `aarch64`，后者应包含 `VERSION_CODENAME=bullseye`。

### 2. 把 Pi 安装包复制过去

在 Windows 下载 Release 中的 `USB-AI-Pi-…-Source.tar.gz`，打开文件所在目录的 PowerShell：

```powershell
scp .\USB-AI-Pi-实际版本-Source.tar.gz piuser@你的Pi地址:~/usb-ai-pi.tar.gz
```

然后在 Pi 的 SSH 窗口执行：

```sh
mkdir -p ~/usb-ai-install
tar -xzf ~/usb-ai-pi.tar.gz -C ~/usb-ai-install
cd ~/usb-ai-install/usb-ai-bridge
python3 pi/install.py --check
sudo python3 pi/install.py
```

`--check` 只检查兼容性。正式安装会询问 Clash YAML 订阅；输入不回显，直接回车表示暂时直连。订阅必须是包含内联 `proxies` 的 HTTPS YAML；仅提供 `proxy-providers` 的配置暂不适用。

安装会下载系统依赖、Mihomo 和固定版本的官方 Codex 运行组件，校验下载摘要，配置服务，并生成**本设备独有的管理密钥**。请把最后显示的管理密钥保存到自己的密码管理器，Windows 配对需要它。

仅使用 API、不需要 ChatGPT/Codex 套餐登录，可以改用：

```sh
sudo python3 pi/install.py --api-only
```

不要同时启动多个安装器。安装失败时，先看最后的错误；排除下载/磁盘等问题后，用同样参数加 `--resume` 恢复，已有管理密钥会保留。完整的已有安装请走升级流程，不要重装。

### 3. 重启并接上 USB

确认保存管理密钥后：

```sh
sudo reboot
```

等待 Pi 启动，再将它的 USB **数据口**连接 Windows。安装器不会启用 USB 网卡，也不会修改桌面密码或自动登录设置。

## Windows 端：约 5 分钟

1. 下载 `USB-AI-Windows-…-Full.zip`，**完整解压**到固定目录，例如 `D:\USB-AI`。不要在压缩包预览窗口内直接运行。
2. 可双击 `Verify-Package.cmd` 检查完整性，再运行 `Self-Test.cmd` 做离线自检。
3. 双击 `Setup-Device.cmd`，输入 Pi 安装时显示的管理密钥。已有旧客户端时，也可自行复制原来的 `device.json` 到新目录。
4. 关闭旧版启动窗口；连接 Pi USB 数据口；双击 `Start-Serial.cmd`。
5. 选择你愿意让 AI 操作的工作目录。程序自动识别 Pi 串口；若要求手动填写，到设备管理器“端口 (COM 和 LPT)”查看 `COM4`/`COM5` 等编号。
6. 浏览器会打开 **http://127.0.0.1:18766/**。保持启动窗口运行，关闭后连接也会结束。

纯设备管理可用 `Open-Serial-Panel.cmd`，不选择工作目录时文件/浏览器工具不可用。不要同时开启两个启动器抢占串口。更换目录或电脑后，旧附件引用可能失效，需要重新选择附件。

### 三种密码不要混淆

| 名称 | 在哪里用 |
| --- | --- |
| Pi 系统账号密码 | 最初的 SSH 登录、USB SSH 维护终端 |
| 设备管理密钥 | Windows `Setup-Device.cmd`、控制台登录和配对 |
| ChatGPT 登录 / 模型 API 密钥 | 控制台里的模型服务配置；不能替代前两者 |

## 连接模型

先到“设备与 Wi-Fi”确认 Pi 已联网；如需代理，填入自己的订阅并选择可用节点。Windows 网页显示在线只表示 USB 通了，不代表 Pi 已有外网。

**ChatGPT/Codex 登录：**在全局设置中选择相应账号连接方式，生成设备码，按面板给出的链接在能上网的手机或浏览器完成登录。若提示未启用设备码授权，先在 ChatGPT 安全设置或工作区权限中开启，再生成新码。不要把账号密码填进聊天框。流程参考 [OpenAI 官方认证说明](https://developers.openai.com/codex/auth/#login-on-headless-devices)。本项目固定使用已集成的 Codex `0.155.1`，不保证未来服务端或插件变更始终兼容。

**API：**填写服务地址、API 密钥和模型名，再发一条简单消息验证。API 的账单独立于 ChatGPT 套餐；面板的费用数字是参考估算，不是最终账单。

首次使用建议先选一个专门的测试工作目录和人工审批模式，再测试读取文件、查看网页等操作。工具结果/附件内容会按照当前模型请求发送给模型。

## 断网时怎么修 Pi

打开 **http://127.0.0.1:18766/maintenance**，或点击面板的“USB 维护终端”。沿用管理密钥，填写你实际的 Pi 用户名，点击连接；出现 `password:` 后输入 Pi 系统密码并按回车。

这是 Pi 本机 SSH 终端，支持中文、Tab、方向键、Ctrl+C 和缩放。输入 `exit` 或点击“断开”关闭。15 分钟无输入、USB/页面失联超过 90 秒，或会话达到 2 小时，会关闭连接。

不依赖 Wi-Fi、代理或 AI 服务，但 Pi 必须正常启动，串口服务和 SSH 服务必须运行。它不是 VNC，不能救援完全无法启动的 TF 卡。断线后不要盲目重复可能已执行的命令，应先查看结果。

## 验证安装成功

- Windows 设备管理器出现串口，而不是新增网络适配器。
- 打开控制台正常，`Check-Connection.cmd` 能生成诊断报告。
- Pi 上 `systemctl is-active usb-ai-manager usb-ai-serial usb-ai-mihomo` 返回 `active`；安装了套餐后端时，`usb-ai-codex` 也应为 `active`。
- 维护终端能登录后执行 `whoami`。
- AI 简单对话成功；在专用测试目录内读文件前出现预期的审批行为。

更多问题看 [故障排查](docs/TROUBLESHOOTING.md)。可选 LCD 按钮、屏幕唤醒和实验软键盘见 [附加硬件](docs/EXTRAS.md)。

## 源码在哪里

```text
pi/app/          Pi 管理服务、会话、Wi-Fi、串口协议和 SSH 终端
pi/codex/        官方 Codex app-server 的本机适配服务
pi/install.py    首次安装入口
windows/        Windows 串口面板、文件/文档/浏览器工具、启动器
extras/         可选 LCD 按钮与实验功能
scripts/        构建和发布校验工具
tests/          安装流程和跨平台校验
docs/           安装、升级、故障和开发文档
```

第三方依赖的来源及许可证见 [THIRD_PARTY.md](THIRD_PARTY.md)。本仓库不包含作者账号数据、运行日志或 TF 卡镜像。
