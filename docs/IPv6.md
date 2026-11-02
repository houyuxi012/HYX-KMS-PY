# IPv6 双栈部署

HYX-KMS-PY 支持 KMS TCP 服务和网站的 IPv6 访问。默认配置继续只监听 IPv4，升级不会因为宿主机未启用 IPv6 而突然启动失败。启用双栈后，同一容器同时保留 IPv4 和 IPv6 访问路径。

## 配置对应关系

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `KMS_IPV6=true` | `false` | 在 `KMS_BIND_ADDRESS` 之外增加另一个地址族的 KMS 监听 |
| `KMS_BIND_ADDRESS` | `0.0.0.0` | 容器内首个 KMS 监听地址 |
| `KMS_IPV6_PUBLISH_ADDRESS` | `::1` | 宿主机 KMS IPv6 发布地址，可写 `::1` 或具体 ULA/公网地址 |
| `WEB_IPV6=true` | `false` | 增加网站 HTTPS 的宿主机 IPv6 端口发布 |
| `WEB_IPV6_PUBLISH_ADDRESS` | `::1` | 宿主机网站 IPv6 发布地址，可写 `::1` 或具体 ULA/公网地址 |
| `KMS_HEALTH_HOST` | 空 | 健康探测地址；空值按 `KMS_BIND_ADDRESS` 选择 IPv4 或 IPv6 回环 |
| `KMS_ALLOWED_NETWORKS` | 必填 | KMS 来源 CIDR，可同时填写 IPv4 和 IPv6，以逗号分隔 |

`KMS_IPV6=true` 且 `KMS_BIND_ADDRESS=0.0.0.0` 时，容器同时监听 `0.0.0.0:1688` 和 `[::]:1688`。设置 `KMS_BIND_ADDRESS=::` 会以 IPv6 为首要监听地址，并增加 IPv4 监听；健康检查随后自动连接 `::1`。原生 IPv6-only 部署可设置 `KMS_BIND_ADDRESS=::` 和 `KMS_IPV6=false`，但 Docker bridge 后端固定并使用 IPv4 时仍应保留容器 IPv4 监听，不能只凭宿主机存在 IPv6 映射判断容器内协议栈可用。

两个 IPv6 发布地址默认都是回环 `::1`。这保证显式开启 IPv6 不会意外把网站或 KMS 暴露到所有 IPv6 接口。面向局域网时必须填写宿主机实际 ULA 或全局单播地址；只有网络边界已单独完成后，才可有意使用 `::` 监听全部 IPv6 接口。

## 原生 KMS 双栈

不通过 Docker 直接启动时，把 IPv6 监听作为首个地址，再追加 IPv4 监听：

```bash
cd hyx_kms_py
KMS_ALLOWED_NETWORKS='2001:db8:10::/64,192.168.10.0/24' \
python3.14 hyx_kms_server.py :: 1688 \
  -s ./HYX-KMS-PY_database.db \
  -V INFO -F STDOUT \
  connect -n 0.0.0.0,1688
```

该进程同时监听 `[::]:1688` 和 `0.0.0.0:1688`。手动执行健康检查时，应设置 `IP=::`、`PORT=1688` 和所需的 `KMS_ALLOWED_NETWORKS`；健康检查会自动连接 `::1`。原生 IPv6-only 可只监听 `::`，但此时客户端、路由、防火墙和监控都必须具备 IPv6 路径。

## Docker 启动

以下示例假设宿主机的内网 IPv6 地址是 `fd12:3456:789a:10::12`。启动前必须完成证书准备，并保留原数据卷：

```bash
HYX_KMS_IMAGE=hyx-kms-py:2026.11.02-rc.3-amd64 \
WEB_TLS_VOLUME=HYX-KMS-PY-tls \
WEB_TLS_SERVER_NAME=kms.example.com \
WEB_PUBLISH_ADDRESS=0.0.0.0 \
WEB_PUBLISH_PORT=443 \
WEB_IPV6=true \
WEB_IPV6_PUBLISH_ADDRESS=fd12:3456:789a:10::12 \
KMS_PUBLISH_ADDRESS=0.0.0.0 \
KMS_PUBLISH_PORT=1688 \
KMS_IPV6=true \
KMS_IPV6_PUBLISH_ADDRESS=fd12:3456:789a:10::12 \
KMS_ALLOWED_NETWORKS='10.0.0.0/8,fd12:3456:789a::/64' \
KMS_PUBLIC_HOST=kms.example.com \
KMS_PUBLIC_PORT=1688 \
bash docker/hyx-kms-py/run.sh
```

IPv6 发布地址会自动补充方括号，因此变量值写 `::1` 或 `2001:db8::10` 即可，不需要手工写成 `[2001:db8::10]`；传入已带方括号的地址也保持兼容。

如果 KMS 客户端通过 Docker 默认 IPv4 网络进入已发布的 IPv6 端口，KMS 进程可能看到 Docker 网桥网关而不是客户端原始 IPv6 地址。此时 `KMS_ALLOWED_NETWORKS` 必须包含实际观察到的网关网段，常见值是 `172.17.0.0/16`。这属于 Docker NAT 的来源改写；应继续由宿主机防火墙和上游 ACL 限制 IPv6 来源，不能改用 `::/0` 放开全部地址。

## DNS 与防火墙

网站和 KMS 使用相同域名时，需要同时维护 A 和 AAAA 记录：

```text
kms.example.com.  A     10.10.10.18
kms.example.com.  AAAA  fd12:3456:789a:10::12
```

A 记录填写宿主机实际 IPv4 地址，AAAA 填写实际 ULA 或全局单播地址。双栈客户端可能优先选择 AAAA；先分别验证两条路径，再验证域名自动选择，不能只验证 A 记录。

宿主机防火墙必须分别确认 TCP `443` 和 TCP `1688` 可从目标 IPv6 网段访问。KMS 只使用 TCP，不需要开放 UDP `1688`。同时检查上游路由器、安全组、Docker 的 IPv6 端口发布能力和宿主机 IPv6 路由。

## 验收

在 Docker 宿主机检查实际发布结果：

```bash
docker port HYX-KMS-PY
ss -lntp | grep -E ':(443|1688)\b'
```

输出应同时包含 IPv4 和 IPv6 监听。随后在目标 Windows 设备执行：

```powershell
Resolve-DnsName kms.example.com -Type AAAA
Test-NetConnection -ComputerName fd12:3456:789a:10::12 -Port 1688
```

`TcpTestSucceeded` 必须为 `True`。使用域名激活时仍执行：

```bat
cscript //nologo %SystemRoot%\System32\slmgr.vbs /ckms
cscript //nologo %SystemRoot%\System32\slmgr.vbs /skms kms.example.com:1688
cscript //nologo %SystemRoot%\System32\slmgr.vbs /ato
```

直接使用 IPv6 字面地址时，生成的脚本会使用 `[IPv6地址]:1688` 形式，例如 `[fd12:3456:789a:10::12]:1688`。建议优先使用带 AAAA 的 DNS 域名，便于后续迁移并避免证书名称与应用地址不一致。

当前页面和协议脚本不使用带 `%` 作用域的链路本地地址。跨网段激活应使用 ULA、全局单播 IPv6 或可解析的 DNS 名称。
