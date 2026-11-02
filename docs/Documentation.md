# 架构说明

## 当前运行结构

项目名称是 HYX-KMS-PY，网站品牌为「密钥管理服务平台」。完整 Docker 镜像在一个容器中运行 KMS 和网站两个进程，使用同一个挂载数据卷；精简镜像只启动 KMS。

| 组件 | 当前实现 | 职责 |
| --- | --- | --- |
| KMS 服务 | `hyx_kms_py/hyx_kms_server.py` 及 RPC、v4/v5/v6 模块 | 监听 TCP 1688，处理协议请求并按配置记录客户端 |
| 模拟客户端 | `hyx_kms_py/hyx_kms_client.py` | 模拟产品请求，验证协议往返；不会激活本机操作系统 |
| 数据库写入 | `hyx_kms_py/hyx_kms_sql.py` | 记录客户端身份、持久化新身份预算，并提供身份归档表 |
| 网站 | `hyx_kms_py/hyx_kms_webui.py`、`templates/`、`static/` | Flask 路由与渲染，Gunicorn 在容器中直接提供 HTTPS 服务 |
| 产品目录 | `hyx_kms_py/hyx_kms_catalog.py` | 协议数据库经展示映射筛选，校验并缓存可展示版本 |
| 私钥校验 | `hyx_kms_py/hyx_kms_secrets.py` | 校验 TLS 私钥不是符号链接，并限制 Unix/Windows 文件权限 |
| 多语言 | `hyx_kms_py/hyx_kms_i18n.py` | `translate()` 统一取词；模板与守卫提示共用同一目录 |
| 预算工具 | `hyx_kms_py/hyx_kms_budget.py` | 每分钟令牌桶与启动时的预算配置校验 |
| 健康检查 | `hyx_kms_py/hyx_kms_health.py` | `python3 -m hyx_kms_health` 供 Docker HEALTHCHECK 统一调用 |
| 运维工具 | `scripts/` | TLS 准备、一致性备份、校验恢复、身份归档、产品矩阵与 SBOM |
| 脚本生成 | `static/js/activation.js` | 在浏览器中根据产品、GVLK、服务器、端口和 Office 位数生成脚本 |
| 产品数据 | `KmsDataBase.xml`、`windows_client_catalog.json` | XML 保存协议产品数据和 GVLK；JSON 保存核对后的 Windows 显示名与 SKU 映射；`activation_catalog.json` 限定 Server / Office 的展示目录 |
| 进程入口 | `docker/hyx-kms-py/start.sh` | 从环境变量构造命令，初始化数据库，启动并监控子进程 |

当前 Docker 构建复制 `hyx_kms_py/`、运维脚本和启动脚本。镜像 TAR 是运行载荷；生产交付还需镜像外部的 TLS 初始化、启动、校验和升级脚本，完整边界见[离线生产部署包](Offline-Deployment.md)。

## 两条独立访问路径

1. 浏览器通过 HTTPS 访问网站，查看客户端记录或生成脚本。默认网站监听容器内 `0.0.0.0:8080`，`run.sh` 和文档示例将容器端口映射到宿主机回环地址的 HTTPS `443`。
2. 目标 Windows/Office 设备直接通过 TCP 连接 KMS 地址和端口，默认容器内为 `0.0.0.0:1688`。这条连接不经过网站的 HTTP 路由。

网站域名和 KMS 域名可以相同，也可以不同；它们可以解析到同一宿主机。HTTPS 反向代理处理网站请求，不会自动转发 KMS TCP 流量。设置网站 HTTPS 证书也不会改变 KMS 协议。

域名展示、DNS、宿主机端口映射和容器监听是四个独立配置层。具体示例集中在[部署与配置](Getting%20Started.md#指定-kms-域名)，这里不重复维护命令。

## 请求与数据流

KMS 客户端发送 RPC 请求，服务端按协议版本处理后返回响应；启用 SQLite 时，同时更新客户端记录。网站以 SQLite 只读连接查询客户端表，展示统计与记录，不负责写入激活记录。

激活页面把产品数据输出到浏览器，浏览器根据选择生成 CMD 文本。复制或下载仅导出脚本；只有用户在目标设备运行脚本后，该设备才会连接 KMS 服务。因此下载脚本不会立即增加首页的客户端数量。

Windows、Windows Server 和 Office 是网站产品分类。Windows Server 与 Windows 客户端的协议应用同属 Windows，首页 Windows 客户端计数并不再次按服务器系统拆分。

## 启动、退出与健康检查

- 完整镜像默认 `SQLITE=false`，此时入口直接启动 KMS，没有网站。
- 设置 `SQLITE=true` 后，入口先校验本地 TLS 证书与私钥，再初始化 `/data/HYX-KMS-PY_database.db`，启动 KMS，并以单 worker、默认 4 线程的 Gunicorn `gthread` 运行 `hyx_kms_webui:app`。
- 入口监视两个子进程。收到停止信号时清理子进程；发现受监视进程意外退出时，清理其他进程并退出，交由 Docker 的重启策略处理。
- `/livez` 表示网站进程存活。`/readyz` 在 HTTPS 下匿名开放，验证数据库可读、clients 表及 KMS RPC bind 响应，失败返回 503；成功结果缓存 5 秒，不验证完整协议响应或真实激活成功。
- 首页访问次数和网站启动时间存于网站进程内存，重启后重置，不是持久化审计记录。完整镜像已配置 Docker `HEALTHCHECK`。

部署验收应同时检查首页、模拟协议请求和目标网络访问；不能只凭一个健康端点返回 200 判断完整服务可用。

## 存储与恢复边界

客户端数据库位于 `/data`，应使用命名数据卷或由服务账号持有、权限为 `0700` 的宿主机目录持久化。数据库文件运行时强制为 `0600`。只持久化容器可写层会在删除容器时丢失记录。默认示例使用 `LOGFILE=STDOUT`，不写容器可写层。当前 `run.sh` 还启用只读根文件系统、仅可写的受限 `/tmp`、`cap-drop=ALL`、`no-new-privileges`、非 root 用户以及 PID、内存、CPU 和文件描述符上限。

网站使用 `mode=ro` 读取既有数据库，缺失数据库会显示错误，不会静默创建新库。数据库不采集请求 IP，首页不再展示该列。新身份创建预算持久化在 `identity_admission_budget`；显式归档会把旧身份原记录和操作审计保留在 `identity_archive` 与 `identity_archive_manifest`。当前身份索引升级会保留原始重复记录备份并在事务内合并；没有通用版本化迁移框架或多节点一致性机制。

这是单机、共享 SQLite 的实现。多副本运行、共享网络文件系统、大量并发写入及高可用切换不在已验证架构内。更新前应生成带 SHA256 清单的一致性备份并保留旧镜像；备份、恢复、身份归档和回滚步骤见[发布与运维](Operations.md)。

## 安全边界与运维要求

- 网站不启用用户登录或 HTTP Basic 认证，面向受控内网匿名开放；所有页面强制 HTTPS，包括本机和 VPN 访问。网站访问边界由发布地址、宿主机防火墙、反向代理和上游网络 ACL 承担，不能直接把匿名站点暴露到公网。详见[整改验收](整改验收.md)。
- KMS 非回环监听必须设置 `KMS_ALLOWED_NETWORKS`。全局连接上限之外，单来源默认最多同时占用 16 个 KMS 连接；仍须按实际客户端来源配置宿主机和上游网络 ACL，公网/NAT 场景单独验证观察到的来源和 TCP 转发。
- KMS 拒绝与服务端相差超过 4 小时的客户端请求；宿主机和目标设备应使用可靠时间源。TLS 私钥必须只允许服务账号读取，并禁止符号链接。
- 静态 CSS/JS 使用同源缓存，动态页面禁止缓存并使用 CSP。
- 浏览器脚本生成对主机名、IP、端口和 GVLK 进行校验，阻止命令符号被拼入脚本。Office 的位数决定安装目录探测范围，不改变同一产品的 GVLK。
- 产品 XML 与展示目录在进程内缓存，每次激活不再重复解析 XML。更新 XML 或 Windows 显示映射后需要重新构建并替换容器，或重启独立网站进程。
- 协议模拟、脚本内容验证与真实 Windows/Office 验收属于不同检查层次。功能边界与验收步骤见[使用说明](Usage.md)。

网站 TLS 配置与证书部署见 [HTTPS 与本地证书](HTTPS.md)。网站不再提供 HTTP。
