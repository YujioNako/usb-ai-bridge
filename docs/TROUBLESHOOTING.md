# 故障排查

## USB 没有串口 / 页面打不开

1. 使用 Pi 的 USB 数据口和数据线，等待系统启动。仅供电线无法通信。
2. 查看设备管理器的端口编号，关闭其它串口终端和旧客户端。
3. 先运行 Start-Serial.cmd，保持窗口不关闭，再打开 http://127.0.0.1:18766/ 。这不是 Pi 的 Wi-Fi IP。
4. 端口 18766 已占用时，关闭旧客户端，或运行旧目录中的 Stop-Serial.cmd；不要禁用安全软件来抢端口。
5. 仍失败运行 Check-Connection.cmd。分享诊断前检查是否含个人信息，不要附上 device.json。

## 管理密钥错误 / pair 失败

使用本设备安装时生成的密钥，它不是 Pi 登录密码。已有电脑可从自己的 device.json 迁移。仍能 SSH 到 Pi 时，可在自己的终端查看：

```sh
sudo python3 -c 'import json; print(json.load(open("/etc/usb-ai-bridge/settings.json"))["admin_token"])'
```

这条命令会显示秘密，请勿录屏公开。不要为了解決配对问题删除 Pi 的 settings.json；它还保存其它服务配置。

## Wi-Fi 页面超时

Zero 2 W 使用 2.4 GHz。先把手机热点设置为兼容的 2.4 GHz、WPA2，检查信号、Wi-Fi 国家/地区和供电。显示“已保存”只说明有配置，不等于关联或 DHCP 已成功。

USB 维护终端中可以只读检查：

```sh
sudo wpa_cli -i wlan0 status
ip address show wlan0
ip route
rfkill list
sudo journalctl -b -u wpa_supplicant --no-pager -n 80
```

不要贴出 Wi-Fi 配置文件或密码。Bookworm/Trixie 的 NetworkManager 不在当前支持范围。原项目出现过特定现场热点关联超时，尚不能确认所有原因，本发布不宣称已普遍解决。

## Pi 安装器下载失败

初次安装必须有外网。检查域名解析、时间、磁盘空间，以及 GitHub 和系统软件源是否可达。系统软件包和 Mihomo 下载发生在本地代理启动之前；不能指望尚未安装的代理帮助下载自己。

若必须借助现有网络代理，请在首次安装网络上完成准备；不要公开代理账号。校验摘要缺失或不符时不要跳过校验。

此安装器留下 install-incomplete 标记时，可修正问题后执行：

```sh
sudo python3 pi/install.py --resume
```

若原先使用 --api-only，恢复时也保留该参数。恢复不是卸载：部分软件包/服务可能已安装，管理密钥会保留。如果是旧版完整部署，查看 UPGRADE.md，不能用 --resume 强制接管。

## AI 连不上，但 USB 终端能用

分别检查 Pi 的网络、代理节点、模型账号状态。ChatGPT 设备码过期或服务重启后应重新生成。API 地址、API 密钥和模型名是另一套配置。安装 API-only 的 Pi 没有套餐运行组件，不能仅通过切换下拉框完成安装。

```sh
systemctl is-active usb-ai-manager usb-ai-mihomo usb-ai-codex
sudo journalctl -u usb-ai-manager -u usb-ai-codex --no-pager -n 60
```

日志可能包含任务信息；分享前脱敏。不要上传 /etc/usb-ai-bridge 或 /var/lib/usb-ai-codex 的内容。

## 黑屏和软键盘

核心功能不需要桌面、屏幕或按钮。LCD 驱动由具体屏幕厂商提供；不要直接套用其它屏幕的 GPIO 配置。实验软键盘仍有登录界面无法输入的问题，因此保留 SSH、USB 维护或读卡器作为恢复途径。安装器不会删除开屏密码或开启桌面自动登录。
