# WhatsApp Multi-Account

基于 Python、PyQt6 和 Qt WebEngine 的 WhatsApp Web 多账号桌面客户端。程序在一个主界面内管理多个账号，为每个账号保存独立的浏览器资料、登录状态和代理设置。

> 本项目不是 WhatsApp 官方客户端。使用时应遵守 WhatsApp 服务条款以及所在地法律法规。

## 主要功能

- 多账号管理：添加账号，并以通讯录式列表单击切换当前账号。
- 主窗口内嵌：macOS 不打开账号独立窗口，WhatsApp 页面显示在主界面右侧。
- 登录持久化：Cookie、Local Storage、IndexedDB、Service Worker、缓存和站点权限按账号隔离并保存。
- 全账号运行：当前账号在主窗口显示，其他账号由各自后台进程持续保持连接。
- 多开隔离：可以同时启动多个主程序，每个程序实例拥有完全独立的配置、账号和浏览器资料。
- 账号自动命名：登录成功后从 WhatsApp 页面获取手机号，移除 `+`、空格及其他非数字字符后作为账号名称。
- 独立代理：每个账号可选择无代理、系统代理、全局代理或自己的自定义代理。
- HTTP、HTTPS、SOCKS5：支持带用户名和密码的代理地址。
- 出口国家识别：通过账号代理查询真实出口 IP 的国家，而不是根据代理服务器地址猜测国家。
- 本地代理网关：解决 Qt WebEngine 对 SOCKS5 认证、DNS 和 WebSocket 支持不一致的问题。
- 通知聚合：将 WhatsApp 浏览器通知、未读数量和最近通知展示在账号列表中。
- 页面刷新：顶部“刷新当前”会重建当前账号的代理连接并完整重新加载页面。
- 配置持久化：账号、代理选择、全局设置以及最近选择的账号都会在下次启动时恢复。

## 界面和平台行为

### macOS

macOS 使用单个主窗口，账号页面直接内嵌在右侧内容区，不创建可见的独立窗口。当前账号在主程序中内嵌显示，其他账号分别由隐藏的后台进程持续运行，以维持连接、未读数和浏览器通知。切换账号时程序会先停止目标账号的后台进程，等待其释放 Profile，再由主窗口接管并显示；离开该账号后，它会重新进入后台进程。各账号的浏览器 Profile、登录数据和进程级代理均独立。

### Windows

Windows 启动后会为所有账号创建独立的 WebEngine 工作进程，但所有页面共用一个可见的主窗口。工作窗口在屏幕外以不激活方式创建，随后嵌入主窗口右侧内容区，不显示额外账号窗口或任务栏窗口。所有账号持续运行并各自使用独立代理，用户单击左侧账号即可在同一内容区切换。

## 代理工作原理

代理模式包括：

| 模式 | 行为 |
| --- | --- |
| 无代理 | 不设置应用代理，使用操作系统当前网络路由 |
| 系统代理 / VPN | 读取系统代理配置；系统 VPN 路由仍由操作系统处理 |
| 全局代理 | 使用程序设置中的共享代理地址 |
| 自定义代理 | 使用该账号单独保存的代理地址，新账号默认使用此模式 |

支持以下格式：

```text
http://host:port
http://username:password@host:port
https://username:password@host:port
socks5://username:password@host:port
```

### 本地网关链路

对于全局代理和自定义代理，实际请求链路为：

```text
Qt WebEngine / Chromium
        ↓ HTTP CONNECT（仅监听 127.0.0.1 随机端口）
程序内置本地代理网关
        ↓ 使用当前账号的 HTTP / HTTPS / SOCKS5 代理及认证信息
上游代理
        ↓
WhatsApp Web
```

本地网关只绑定回环地址，不对局域网开放。它先通过本机网络环境解析目标域名，再把目标 IP 交给上游代理，兼容拒绝 SOCKS5 域名地址类型但允许 IP 地址连接的代理服务。程序同时禁用 Chromium QUIC，避免 UDP/443 绕过账号代理。

系统 VPN 和账号代理可以同时存在：系统 VPN 是宿主机到上游代理服务器的网络路径，账号代理决定 WhatsApp 的最终出口。若 VPN 使用分流规则，应确保代理服务器地址可达。

### 出口国家检测

程序通过账号配置的上游代理访问 `ipwho.is`，以服务看到的实际出口 IP 返回国家代码和国家名称。检测请求不会使用系统直连结果，也不会仅查询代理主机 IP 的地理位置。

## 数据持久化

每个账号使用独立的 `QWebEngineProfile`。配置文件采用临时文件写入后原子替换，降低异常退出导致 JSON 损坏的风险。

macOS 数据目录：

```text
~/Library/Application Support/WhatsAppClient/
```

第一个实例为兼容旧版本继续使用上述目录，后续实例使用：

```text
~/Library/Application Support/WhatsAppClient/instances/instance-2/
~/Library/Application Support/WhatsAppClient/instances/instance-3/
```

Windows 数据目录：

```text
%APPDATA%\whatsapp-pyqt\
```

后续 Windows 实例同样保存在根目录的 `instances/<实例名>/` 下。

### 多开方式

macOS 同时打开多个程序实例：

```bash
open -n "dist/WhatsAppClient.app"
open -n "dist/WhatsAppClient.app"
```

程序会自动选择第一个未被占用的 `instance-N`。窗口标题会显示当前实例名。实例退出后，对应槽位可以再次使用，并恢复该槽位原有配置和登录状态。

也可以使用固定实例名称，方便明确区分不同业务：

```bash
open -n "dist/WhatsAppClient.app" --args --instance sales
open -n "dist/WhatsAppClient.app" --args --instance support
```

源码模式：

```bash
python main.py --instance sales
python main.py --instance support
```

实例名称只允许字母、数字、下划线和短横线。同名实例正在运行时不能再次启动，以避免两个程序同时写入同一份 Profile 和配置。每个实例启动的账号后台工作进程会继承实例名，但不会重复占用主实例锁。

Windows 可以重复双击 `启动新实例.bat`，每次自动打开一个隔离实例。也可以在命令提示符中指定固定名称：

```bat
启动新实例.bat sales
启动新实例.bat support
```

打包版本也可以直接多开：

```bat
start "" "dist\WhatsAppClient.exe"
start "" "dist\WhatsAppClient.exe"
```

主要内容：

```text
accounts.json       账号、代理模式和代理地址
settings.json       全局代理及界面设置
<profile_name>/     对应账号的 Cookie、缓存和站点数据
crash.log           Python 层异常日志
```

代理凭据以本地配置形式保存。请保护操作系统用户账号及应用数据目录，不要公开 `accounts.json` 和 `settings.json`。

## 刷新和故障处理

页面加载不完整时，先点击顶部“刷新当前”。该操作不是普通 DOM 刷新，而是：

1. 取消尚未结束的加载和检测任务；
2. 停止当前 WebEngine 页面并切换到空白页；
3. 关闭旧的本地代理网关及连接；
4. 重新应用当前账号代理；
5. 检测代理并重新打开 WhatsApp Web。

如果仍无法加载：

- 确认相同代理能连接 `web.whatsapp.com:443`；
- 检查代理用户名、密码、IP 白名单和并发连接限制；
- 完全退出旧版本后再启动新构建；
- 查看数据目录下的 `crash.log`；
- VPN 分流环境下确认上游代理服务器没有被错误路由。

## 开发环境

- Python 3.9–3.14
- PyQt6 6.10
- PyQt6-WebEngine 6.10
- PyInstaller 6.19

安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

从源码启动：

```bash
python main.py
```

## macOS 构建和启动

首次准备环境：

```bash
make mac-setup
```

从源码启动：

```bash
make mac-run
```

打包并打开：

```bash
make mac-build
make mac-open
```

生成文件：

```text
dist/WhatsAppClient.app
```

也可以直接运行脚本：

```bash
bash scripts/setup_mac.sh
bash scripts/start_mac.sh
bash scripts/build_mac.sh
open dist/WhatsAppClient.app
```

构建架构跟随 `.venv` 使用的 Python：Apple Silicon 为 `arm64`，Intel Mac 为 `x86_64`。当前应用未使用 Developer ID 签名和公证；首次运行若被 Gatekeeper 阻止，可在 Finder 中右键应用并选择“打开”。正式分发时应完成签名和公证。

## Windows 安装、启动和打包

首次安装依赖，双击：

```bat
setup_windows.bat
```

从源码启动：

```bat
启动.bat
```

启动指定实例：

```bat
启动.bat --instance sales
```

打包：

```bat
build.bat
```

生成文件位于：

```text
dist\WhatsAppClient.exe
```

Windows 使用 PyInstaller 单文件模式，分发时只需复制 `dist\WhatsAppClient.exe`。Qt WebEngine 运行库会在启动时解压到临时目录，因此首次启动会比目录版稍慢。

## Linux AppImage

构建：

```bash
bash scripts/build_appimage.sh
```

运行：

```bash
chmod +x WhatsAppClient-x86_64.AppImage
./WhatsAppClient-x86_64.AppImage
```

遇到 FUSE 问题时：

```bash
./WhatsAppClient-x86_64.AppImage --appimage-extract-and-run
```

## 项目结构

```text
main.py                    应用入口、Chromium 参数和 Windows 工作进程入口
app/window.py              主界面、账号列表、当前账号操作和页面切换
app/account.py             WebEngine Profile、WhatsApp 页面、通知和号码识别
app/mac_account.py         macOS 前台内嵌与后台账号进程交接
app/proxy_extension.py     代理解析、检测、本地网关和上游隧道
app/country.py             真实代理出口国家检测
app/config.py              路径、配置读取和原子持久化
app/windows_account.py     Windows 独立账号进程及嵌入逻辑
scripts/setup_mac.sh       macOS 虚拟环境安装
scripts/start_mac.sh       macOS 源码启动
scripts/build_mac.sh       macOS .app 打包
setup_windows.bat          Windows 虚拟环境和依赖安装
启动.bat                   Windows 源码启动，可传递 --instance
启动新实例.bat             Windows 自动或命名多开入口
build.bat                  Windows PyInstaller 打包
```
