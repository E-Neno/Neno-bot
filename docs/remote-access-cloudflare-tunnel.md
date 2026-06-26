# 远程访问 — Cloudflare Tunnel

让手机从**任何网络**(流量 / 任意 WiFi,**不用 VPN/Tailscale,梯子开着也行**)连到你电脑上的
Neno + Hermes。走 Cloudflare Tunnel:电脑**主动外连** Cloudflare,**不开任何入站端口**,
公网只暴露白名单路径,免 ICP 备案(不落地国内 IP)。

## 架构

```
手机 ──https──► neno.neno-xuanye.work   ─┐
     ──https──► hermes.neno-xuanye.work ─┤► Cloudflare 边缘 ──隧道──► 电脑 cloudflared ─┬─► localhost:8000  Neno  (只放 /mobile)
                                                                                      └─► localhost:8642  Hermes(只放 /v1 /api)
```

- 传输走 HTTPS(Cloudflare 自动签证书)
- 公网只通白名单路径;`/chat`、`/test`、`/debug` 一律 **404**
- 鉴权:Neno 用 `MOBILE_TOKEN`(强随机);Hermes 用它自己的 API key

## 暴露映射

| 公网地址 | 转发到 | 放行路径 | 鉴权 |
| --- | --- | --- | --- |
| `https://neno.neno-xuanye.work` | `localhost:8000` | `/mobile/*`(含 WebSocket `/mobile/ws`) | `MOBILE_TOKEN` |
| `https://hermes.neno-xuanye.work` | `localhost:8642` | `/v1/*`、`/api/*` | Hermes API key |
| 其它路径 / 其它主机 | — | — | 404 |

## App 设置(长按设置页「设置」标题 → 高级连接设置)

| | 服务器地址 | 访问令牌 |
| --- | --- | --- |
| Neno | `https://neno.neno-xuanye.work` | `.env` 里的 `MOBILE_TOKEN` |
| Hermes | `https://hermes.neno-xuanye.work` | 你的 Hermes API key(不变) |

> 令牌**不写进文档**(仓库公开)。Neno 的看 `.env` 的 `MOBILE_TOKEN`;Hermes 的是你自己配的那把 key。
> 同一 WiFi 下仍可直连本机:`http://<电脑局域网IP>:8000`(Neno)/ `:8642`(Hermes)。

## 三个进程(电脑得开着;**PC 重启后要重新起这三个**)

| 进程 | 端口 | 启动 |
| --- | --- | --- |
| Neno 后端 | 8000 | 仓库根目录下:`python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`(读 `.env`) |
| Hermes | 8642 | 见 Hermes 服务自己的启动方式 |
| 隧道 | — | `%USERPROFILE%\cloudflared\cloudflared.exe --config %USERPROFILE%\.cloudflared\config.yml tunnel run neno` |

想免手动重启 → 把 cloudflared 装成 Windows 服务开机自启:`cloudflared service install`
(uvicorn / Hermes 也可各自做成自启)。

## 文件位置

- cloudflared 客户端:`%USERPROFILE%\cloudflared\cloudflared.exe`
- 隧道配置:`%USERPROFILE%\.cloudflared\config.yml`
- 授权证书 / 隧道凭据:`%USERPROFILE%\.cloudflared\cert.pem`、`<tunnel-id>.json` —— **保密,别提交**
- 隧道:名字 `neno`,id `faa7156e-7174-493c-a721-95d9b415247c`
- 隧道日志:`%USERPROFILE%\.cloudflared\run.err.log`

## 改隧道配置后

编辑 `config.yml` → 重启 cloudflared(停掉旧进程,再 `tunnel run neno`)。
加新子域还要先 `cloudflared tunnel route dns neno <子域>.neno-xuanye.work`。

## 排错

- **手机连不上**:① 三个进程都在跑?② Cloudflare 里域名还是 Active?③ App 地址/令牌对不对?④ 看隧道日志 `run.err.log` 有没有报错。
- **域名 521 / 522**:cloudflared 没在跑,或后端 8000 / Hermes 8642 没起。
- **hermes 返回 401**:正常(没带 key);带对 key 就通。
- **/chat 等返回 404**:正常,白名单按设计挡住了。

## 安全

- 公网只放白名单路径,危险路由(`/chat`、`/test`、`/debug`)公网碰不到。
- `MOBILE_TOKEN` 是强随机、存 `.env`(gitignored)。换 token:改 `.env` → 重启 uvicorn → 改 App。
- `~/.cloudflared/` 下的证书和凭据**不入库**,泄露等于把隧道控制权交出去。
