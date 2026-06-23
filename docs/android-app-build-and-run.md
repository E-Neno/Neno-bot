# Neno 安卓 App — 构建与运行

本机后端 + 手机 App 的完整流程：**起后端 → 连手机 → 装 App**。
日常迭代用 **debug**（快），日常使用 / 看真实流畅度用 **release**（慢但顺）。

## 前提

- 电脑装了 Android SDK，`adb` 在 `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`
- 手机：开发者选项 → **无线调试** 打开，且和电脑**同一 WiFi**
- 仓库根目录：`C:\Users\Administrator\Desktop\neno-bot-local`

## 1. 起后端

后端读 `.env`（已配好全部开关 + `MOBILE_TOKEN`），直接起：

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0`：手机要从局域网连，**必须绑 0.0.0.0**（不能是 127.0.0.1）
- 改了 `.env` 要**重启 uvicorn** 才生效
- 首次让手机能连，要放行防火墙（**管理员** PowerShell，一次即可）：

```powershell
New-NetFirewallRule -DisplayName "Neno mobile 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
```

## 2. 连手机（adb）

手机 开发者选项 → 无线调试 里看到 `IP:端口`，电脑上：

```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb connect 192.168.1.5:44043   # 换成你手机显示的 IP:端口（手机重启后端口会变）
& $adb devices                      # 看到 device 就连上了
```

> USB 线插电脑也行，自动认，不用 `connect`。

## 3. 装 App / 切 debug·release

**一条命令搞定**（构建 + 安装 + 启动，全自动，手机不用碰）：

```powershell
# release：慢 ~2min，流畅（真实性能，日常用）
powershell -ExecutionPolicy Bypass -File mobile\android\install.ps1 release

# debug：快 ~12s，开发迭代用
powershell -ExecutionPolicy Bypass -File mobile\android\install.ps1 debug
```

debug 和 release 都用同一个 debug keystore 签名，所以 `install -r` 能互相覆盖、**保留 App 里的设置**。
「切」和「装」是同一个动作——跑完命令手机上就是新包并自动打开了，**没有再单独安装这一步**。

不想用脚本，手动等价命令：

```powershell
.\mobile\android\gradlew.bat -p .\mobile\android :app:assembleRelease   # 或 :app:assembleDebug
& $adb install -r -t .\mobile\android\app\build\outputs\apk\release\app-release.apk
& $adb shell am start -n com.neno.app/.MainActivity
```

## 4. App 里的连接设置

- 默认设置页只显示**连接状态 + 应用信息**，不露服务器地址（不是开发控制台）
- 要改地址 / 令牌：**长按设置页的「设置」标题** → 弹出「连接设置（高级）」
- **服务器地址**：`http://你电脑局域网IP:8000`（现在是 `http://192.168.1.3:8000`；电脑 IP 变了要改，查 IP 用 `ipconfig`）
- **访问令牌**：和 `.env` 里的 `MOBILE_TOKEN` 填一致

## 5. debug vs release 怎么选

|        | debug        | release        |
| ------ | ------------ | -------------- |
| 构建   | ~12 秒       | ~2 分钟        |
| 手感   | 卡（调试底噪） | 顺（真实性能） |
| 用途   | 改代码迭代   | 日常使用 / 验性能 |

debug 包带调试插桩、没优化，动画天生比 release 卡——**那是包的底噪，不是动画写坏了**。

## 6. 常见问题

- **脚本报「没有已连接的设备」**：adb 断了（手机重启 / 换网 / 无线调试超时）。回第 2 步重连，USB 最稳。
- **App 显示未连接**：① 后端没起或没绑 `0.0.0.0`；② 防火墙没放行 8000；③ 设置里地址 / 令牌不对；④ 手机和电脑不在同一 WiFi。
- **改了 `.env` 不生效**：重启 uvicorn。
- **构建失败**：别在编辑器 / codex 写文件写到一半时构建（会撞半成品文件）。
