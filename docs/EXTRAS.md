# 可选屏幕、按钮和软键盘

本节不是核心安装步骤，普通 USB AI 使用不需要执行。

## LCD HAT 按钮

extras/lcd-buttons 提供 GPIO 到 Linux uinput 鼠标/键盘的完整源码和安装测试。BCM 定义：上 6、下 19、左 5、右 26、中心 13；侧键 21/20/16。代码已包含针对旋转 180 度屏幕的方向设置；安装前阅读按钮参数和你的屏幕接线，不能把 BCM 当成排针物理编号。

依赖 RPi.GPIO 和 Linux uinput。安装器只适用于已经接好上述模块、确认没有 GPIO 冲突的 Pi：

```sh
sudo apt-get install python3-rpi.gpio
sudo python3 extras/lcd-buttons/install.py
```

方向移动、中心左键，侧键分别右键、回车、返回。驱动后台服务为 lcd-hat-buttons。

## 屏幕唤醒

extras/lcd-wake 是对 Waveshare_fbcp 的输入唤醒适配：动态识别 HAT 的鼠标和键盘输入，空闲等待时继续检查唤醒。它不是通用显示驱动，也不替代厂商构建配置。应由熟悉该屏幕驱动的开发者阅读并合并 patch-main.py / keyboard.cpp，保持原有 SPI、分辨率、旋转和背光设置；不要给其它型号直接刷入作者的二进制。

## 实验软键盘

extras/keyboard-experimental/greeter-keyboard.py 是实验代码，能够在部分 X11 greeter 会话中显示 Onboard，但真实登录框输入尚未通过验收。它没有被核心安装器启用，不提供无需物理键盘的可靠保证。核心安装器也不会自动登录桌面或移除密码。
