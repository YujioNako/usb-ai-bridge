# 开发与构建

## 源码与发行包

仓库包含全部自有应用代码和必要的前端发行库；不提交 node.exe、SerialWorker.exe、node_modules、用户配置或模型账号。第三方依赖保留锁文件、版本与许可。仓库不是开发时临时文件和历史补丁的堆积。

Pi app 中包含可读的 workbench.js、workbench-view.js、workbench-sync.js。Windows 发行包把这些文件和 markdown-it 拼为一个入口，以兼容已有静态资源路由。请改 Pi app 中的可读源文件，再构建。

## Windows 完整包

构建环境：Python 3.11+、Windows 11、Node.js 24.21.0（文档依赖基线）。普通用户直接下载 Release，不需要这些开发工具。

`python scripts/build_windows.py` 接收一个已校验的完整包作为**依赖种子**，只复用 runtime、node_modules 和串口执行文件；业务代码和前端均来自当前仓库。种子只能使用项目已验证的 Release 附件，并对照 SHA256SUMS.txt，不要随意输入未知 ZIP。

```powershell
python scripts/build_windows.py --seed D:\Downloads\旧的完整包.zip --seed-sha256 该文件的SHA256值 --version v0.4.0-rc.1
```

输出在 dist/。这是脱网重打包路径，不是从源码编译 Node.js 或第三方库。

要重新构建串口程序，运行 `powershell -File scripts/build_serial.ps1`；源码位于 windows/SerialWorker.cs。改过 C# 后必须把 `--serial-worker build/serial/SerialWorker.exe` 传给构建器，以替换种子中的串口二进制。

文档依赖可在联网的开发电脑中执行 `npm ci --ignore-scripts --prefix windows/documents` 安装，锁文件列出来源和完整性摘要。新版依赖需重新验证 XLS/XLSX/DOCX/PDF/ZIP 功能后才能发布。不要在内网用户电脑上依赖实时 npm 安装。

## 测试

Pi 业务单元测试多数不需要真实设备：在 Linux Python 3.9+ 环境中，安装 PyYAML 后运行 pi/app/test-*.py。`test-terminal.py` 使用 Linux PTY；`test-serial.py` 使用协议 fixture。运行测试不会启动真实 AI 对话。

```sh
python3 -m unittest discover -s tests -v
python3 pi/app/test-serial.py
python3 pi/app/test-terminal.py
```

Windows 发行包内的 `Self-Test.cmd` 验证解析依赖、文件格式和页面资源，不连接 Pi 或模型。`Verify-Package.cmd` 检查清单中的大小与 SHA-256。

新安装器采用固定 Codex 0.155.1 接口。升级官方运行组件前应重新验证登录、会话、动态工具与审批，不要把运行组件单独替换为 latest 后宣称兼容。

## 发布前

只在干净的源码目录建 Git 仓库。不要从开发工作目录、运行目录或 TF 卡镜像直接 git add 。

排除 device.json、auth.json、settings.json、model.json、代理订阅、SSH 私钥、日志、浏览器资料与 Workspace。新增附件、截图或测试数据也应检查真实身份和文件内容。Release 附件生成 SHA-256 清单，Windows 包应通过 manifest 校验和 Self-Test。

目前硬件回归基线来自既有 Zero 2 W 部署；新卡从零安装尚待硬件验收，首个源码发行应标为预发布。不要将模拟测试称为真实新卡安装成功。

## 无旧发行包，从依赖开始构建

1. 从 https://nodejs.org/dist/v24.21.0/ 下载 Windows x64 ZIP，对照官方 SHASUMS256.txt 校验，再解压；该目录包含 node.exe 和 LICENSE。
2. 安装 Node/npm 到开发环境 PATH，执行 `npm ci --ignore-scripts --prefix windows/documents`。
3. 运行 `powershell -File scripts/build_serial.ps1` 编译自有串口源码。
4. 把以下示例中的 Node 目录替换为实际路径：

```powershell
python scripts/build_windows.py --runtime-dir C:\node-v24.21.0-win-x64 --dependencies-dir windows/documents/node_modules --serial-worker build/serial/SerialWorker.exe --version v0.4.0-rc.1
```

构建后解压产物，运行 Verify-Package.cmd 和 Self-Test.cmd，再做真实串口回归。新依赖下载和编译只在开发电脑进行，最终用户使用单个完整 ZIP。
