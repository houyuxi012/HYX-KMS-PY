# 部署与配置

本文按当前 `hyx_kms_py/` 源码、Flask/Gunicorn 网站和共享 SQLite 数据库编写。所有构建命令在项目根目录执行。已有服务先核对实际容器名称、镜像、端口和数据卷；下面统一用 `HYX-KMS-PY`、`hyx-kms-py:latest` 和 `HYX-KMS-PY-data` 作为示例名称，不要覆盖已有实例。

生产离线交付必须使用包含固定版本镜像、TLS 准备脚本、启动脚本、校验文件和文档的完整部署包，不能只交付 Docker 镜像 TAR。生成、校验、首装和升级步骤见[离线生产部署包](Offline-Deployment.md)。

## 完整版与精简版

| 方式 | 启动内容 | 使用场景 |
| --- | --- | --- |
| 完整镜像，`SQLITE=true` | KMS、SQLite 客户端记录、Gunicorn 网站 | 需要首页记录、激活脚本和产品列表 |
| 完整镜像，`SQLITE=false`（默认） | 仅 KMS | 不需要网站与客户端记录 |
| 精简镜像 | 仅 KMS 运行依赖 | 不提供 Flask/Gunicorn 网站，不应设置 `SQLITE=true` |

基础镜像由仓库 Dockerfile 指定为 `python:3.14.7-alpine`。Dockerfile 的架构后缀不会自行切换 CPU 架构；本机构建使用 Docker 选择的平台，交叉构建需要显式指定 `--platform` 并在目标环境验收。

网站强制 HTTPS。执行前先阅读 [HTTPS 与本地证书](HTTPS.md)，准备访问域名对应的证书和私钥；下例使用 SAN 包含 `localhost` 的证书。

## 本机新建完整实例

```bash
docker build -t hyx-kms-py:latest -f docker/hyx-kms-py/Dockerfile.amd64 .
# 先准备 SAN 包含 localhost 的本地证书，替换以下绝对路径
bash docker/hyx-kms-py/prepare-tls.sh /absolute/fullchain.pem /absolute/privkey.pem
docker run -d --name HYX-KMS-PY \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --pids-limit=256 \
  --memory=512m \
  --cpus=1.0 \
  --ulimit nofile=1024:1024 \
  --stop-timeout 20 \
  --restart unless-stopped \
  -p 127.0.0.1:1688:1688 \
  -p 127.0.0.1:443:8080 \
  -e KMS_ALLOWED_NETWORKS=127.0.0.0/8 \
  -e SQLITE=true \
  -e WEB_TLS_CERT_FILE=/run/tls/current/fullchain.pem \
  -e WEB_TLS_KEY_FILE=/run/tls/current/privkey.pem \
  -e WEB_TLS_SERVER_NAME=localhost \
  -v HYX-KMS-PY-tls:/run/tls:ro \
  -e LOGFILE=STDOUT \
  -v HYX-KMS-PY-data:/data \
  hyx-kms-py:latest
```

打开 [激活页面](https://localhost/activate)。上述两个端口仅允许宿主机访问，适合本机检查；另一台设备不能用它连接 KMS。面向局域网客户端的设置见下一节。

网站导航为首页、激活、产品、使用说明，页脚保留软件许可链接。`/data/HYX-KMS-PY_database.db` 是当前完整镜像的固定数据库路径。不要省略数据卷来保存重要客户端记录。

构建精简镜像：

```bash
docker build -t hyx-kms-py:minimal -f docker/hyx-kms-py-minimal/Dockerfile.amd64 .
```

ARM64 交叉构建示例：

```bash
docker buildx build --platform linux/arm64 --load \
  -t hyx-kms-py:latest-arm64 \
  -f docker/hyx-kms-py/Dockerfile.arm64v8 .
```

## 指定 KMS 域名

### 四层配置的区别

| 配置层 | 示例 | 影响 |
| --- | --- | --- |
| 页面默认地址 | `KMS_PUBLIC_HOST=kms.example.com` | 页面「KMS 服务器」与生成脚本的默认主机名 |
| DNS | `kms.example.com` 的 A 记录指向宿主机可达 IPv4 | 客户端将域名解析为连接地址 |
| 宿主机端口映射 | `-p 1688:1688` | 将宿主机 TCP 1688 转发到容器 TCP 1688 |
| 容器监听 | `IP=0.0.0.0`、`PORT=1688` | KMS 进程在容器内部监听的地址与端口 |

`KMS_PUBLIC_HOST` 只负责显示和脚本默认值，不会创建 DNS 记录、修改路由、防火墙或容器端口。不要将容器监听参数 `IP` 改成宿主机的外部域名或外部 IP；该地址通常不属于容器接口。

### 设置 DNS 与网络

1. 在实际使用的 DNS 中添加 A 记录，例如 `kms.example.com` → `192.168.10.20`。需要 IPv6 时，同时添加指向宿主机 ULA 或全局单播地址的 AAAA 记录。示例地址需要替换为客户端可达的真实地址；跨网访问需有对应路由或 VPN。
2. 按客户端来源范围放通宿主机和上游网络的 TCP 1688。宿主机经过 NAT 时，配置到宿主机 KMS 端口的 TCP 转发。
3. 使用 IPv6 前，按[IPv6 双栈部署](IPv6.md)验证 AAAA 记录、服务监听、Docker 发布、防火墙和端到端路由。不要仅凭添加 AAAA 记录就认为 IPv6 可用。
4. KMS 是 TCP 协议，不是 HTTP。仅提供 HTTP/HTTPS 的域名代理或反向代理不能直接承载此端口。

本文使用保留示例域名 `kms.example.com`，请替换为你控制的真实域名。只填写主机名，不带 `http://`、`https://`、斜杠、路径或空格；端口使用单独参数。

### 新实例指定页面默认域名

先完成镜像构建，然后在尚未创建同名容器的宿主机执行：

```bash
docker run -d --name HYX-KMS-PY \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --pids-limit=256 \
  --memory=512m \
  --cpus=1.0 \
  --ulimit nofile=1024:1024 \
  --stop-timeout 20 \
  --restart unless-stopped \
  -p 1688:1688 \
  -p 127.0.0.1:443:8080 \
  -e IP=0.0.0.0 \
  -e PORT=1688 \
  -e KMS_ALLOWED_NETWORKS=192.168.10.0/24 \
  -e SQLITE=true \
  -e WEB_TLS_CERT_FILE=/run/tls/current/fullchain.pem \
  -e WEB_TLS_KEY_FILE=/run/tls/current/privkey.pem \
  -e WEB_TLS_SERVER_NAME=localhost \
  -v HYX-KMS-PY-tls:/run/tls:ro \
  -e LOGFILE=STDOUT \
  -e KMS_PUBLIC_HOST=kms.example.com \
  -e KMS_PUBLIC_PORT=1688 \
  -v HYX-KMS-PY-data:/data \
  hyx-kms-py:latest
```

页面默认显示 `kms.example.com`。用户仍可在页面手动修改地址；该配置不是锁定字段。KMS 端口面向网络客户端发布，网站仍仅绑定宿主机本机。若宿主机有多块网卡，可将 `-p 1688:1688` 收窄为 `-p 宿主机内网IP:1688:1688`，并配置来源访问控制。

### 修改已有实例

Docker 容器的环境变量不能通过一次 `docker restart` 修改。应先备份并记录原实例的镜像、数据卷、端口与其他配置，再按新的环境变量重建容器，挂载原数据卷。使用 Compose 时修改 `environment` 后执行 `docker compose up -d`；不要使用删除数据卷的选项。

仓库的 `docker/hyx-kms-py/run.sh` 要求 `WEB_TLS_VOLUME`、`WEB_TLS_SERVER_NAME` 和 `KMS_ALLOWED_NETWORKS`，不会自动删除现有同名容器。`HYX_KMS_IMAGE` 可指定固定版本镜像；未设置时仍使用开发默认值 `hyx-kms-py:latest`。脚本默认只把网站和 KMS 发布到宿主机 `127.0.0.1`；网站外部端口默认为 HTTPS `443`，KMS 外部端口默认为 `1688`，容器内网站端口仍为 `8080`。局域网部署应显式设置 `KMS_PUBLISH_ADDRESS`；`WEB_PUBLISH_ADDRESS`、`KMS_PUBLISH_PORT`、`WEB_PUBLISH_PORT` 可分别控制另一个发布地址和外部端口。`KMS_IPV6=true`、`WEB_IPV6=true` 增加宿主 IPv6 发布，未显式设置对应 IPv6 地址时默认只绑定 `::1`；具体配置见[IPv6 双栈部署](IPv6.md)。资源限制可由 `KMS_PIDS_LIMIT`、`KMS_MEMORY_LIMIT`、`KMS_CPU_LIMIT`、`KMS_NOFILE_LIMIT` 覆盖。页面默认域名和端口分别读取 `KMS_PUBLIC_HOST`、`KMS_PUBLIC_PORT`。已有实例应按已核实参数管理升级。

### 外部端口与网站域名

如果客户端通过宿主机 TCP 1689 访问，而容器仍监听 1688，将前述命令的 KMS 映射改为 `-p 1689:1688`，并设置 `KMS_PUBLIC_PORT=1689`。容器内 `PORT=1688` 保持不变；DNS A 记录不携带端口。

网站可以继续用本机地址，也可以由组织现有的 HTTPS 反向代理通过 HTTPS 转发到默认外部地址 `127.0.0.1:443` 并校验上游证书。网站本身不启用用户认证，因此反向代理、防火墙和上游网络必须承担访问边界；网站域名与 `KMS_PUBLIC_HOST` 可以不同。域名解析到宿主机并不要求将网站直接暴露到公网。

需要让组织客户端自动发现 KMS 时，可另行配置 `_vlmcs._tcp` SRV 记录；本网站生成的是显式指定主机的脚本，不自动管理 SRV 记录。自动发现属于独立 DNS 配置流程，参见 [Microsoft Learn：KMS DNS 故障排查](https://learn.microsoft.com/en-us/windows-server/get-started/common-troubleshooting-procedures-kms-dns)。

### 域名验收

在目标 Windows 客户端使用 PowerShell：

```powershell
Resolve-DnsName kms.example.com
Test-NetConnection kms.example.com -Port 1688
```

解析结果应为预期宿主机地址，`TcpTestSucceeded` 应为 `True`。非默认外部端口按实际值替换。TCP 可达不等于协议和产品激活已成功。

在宿主机核对容器配置及网站：

```bash
docker exec HYX-KMS-PY python3 -c "import os; print(os.getenv('KMS_PUBLIC_HOST')); print(os.getenv('KMS_PUBLIC_PORT'))"
curl --fail --cacert /absolute/fullchain.pem https://localhost/livez
```

浏览器打开激活页，确认「KMS 服务器」和端口默认值正确，并核对生成的 Windows `/skms` 或 Office `/sethst`、`/setprt` 参数。真实设备验收见[使用说明](Usage.md#验收层次)。

## Compose 部署示例

以下 YAML 是供放在项目根目录的示例；构建上下文 `.` 指项目根目录。仓库当前未提供默认 `compose.yaml`。示例中的域名需替换；升级已有实例时必须使用原有数据卷，而不是新建空卷。

```yaml
services:
  kms:
    build:
      context: .
      dockerfile: docker/hyx-kms-py/Dockerfile.amd64
    image: hyx-kms-py:latest
    container_name: HYX-KMS-PY
    restart: unless-stopped
    read_only: true
    tmpfs:
      - "/tmp:rw,noexec,nosuid,nodev,size=16m"
    cap_drop:
      - ALL
    security_opt:
      - "no-new-privileges:true"
    pids_limit: 256
    mem_limit: 512m
    cpus: 1.0
    stop_grace_period: 20s
    ulimits:
      nofile:
        soft: 1024
        hard: 1024
    ports:
      - "1688:1688"
      - "127.0.0.1:443:8080"
    environment:
      IP: "0.0.0.0"
      PORT: "1688"
      KMS_ALLOWED_NETWORKS: "192.168.10.0/24"
      SQLITE: "true"
      WEB_TLS_CERT_FILE: /run/tls/current/fullchain.pem
      WEB_TLS_KEY_FILE: /run/tls/current/privkey.pem
      WEB_TLS_SERVER_NAME: localhost
      LOGFILE: "STDOUT"
      KMS_PUBLIC_HOST: "kms.example.com"
      KMS_PUBLIC_PORT: "1688"
    volumes:
      - kms-data:/data
      - kms-tls:/run/tls:ro
volumes:
  kms-tls:
    external: true
    name: HYX-KMS-PY-tls
  kms-data:
    name: HYX-KMS-PY-data
```

```bash
docker compose config
docker compose up -d --build
docker compose logs --tail 100 kms
```

不要同时启动手工创建的同名/同端口容器。`docker compose down` 不加 `-v` 才会保留此命名卷。

## Docker 环境变量

本表是完整镜像和启动脚本的当前配置入口。精简镜像的部分默认值不同，且不安装网站依赖。容器配置与直接运行 CLI 的默认值也不完全相同。

| 变量 | 完整镜像默认值 | 用途 |
| --- | --- | --- |
| `IP` | `0.0.0.0` | 容器内 KMS 监听地址 |
| `PORT` | `1688` | 容器内 KMS 监听端口 |
| `KMS_BIND_ADDRESS` | `0.0.0.0` | `run.sh` 传给容器 `IP` 的首个 KMS 监听地址，可设为 IPv6 字面地址 |
| `KMS_IPV6` | `false` | `true` 时在首个监听地址外增加另一个地址族的 KMS 监听 |
| `KMS_IPV6_PUBLISH_ADDRESS` | `::1` | 启用宿主 IPv6 KMS 发布且未指定地址时的回环地址 |
| `KMS_ALLOWED_NETWORKS` | 未设置 | 非回环监听时必填；逗号分隔 IPv4/IPv6 CIDR，程序始终加入本机回环 |
| `KMS_HEALTH_HOST` | 空 | 健康探测地址；空值按 `IP` 地址族选择 `127.0.0.1` 或 `::1` |
| `SQLITE` | `false` | 仅字面值 `true` 启用客户端数据库与网站 |
| `WEB_IPV6` | `false` | `true` 时增加网站 HTTPS 的宿主机 IPv6 端口发布 |
| `WEB_IPV6_PUBLISH_ADDRESS` | `::1` | 启用网站 IPv6 发布且未指定地址时的回环地址 |
| `WEB_HOST` | `0.0.0.0` | 网站监听地址；Docker 发布端口时不要改为容器内 `127.0.0.1` |
| `WEB_PORT` | `8080` | 容器内 HTTPS 端口，修改后需同步端口映射 |
| `WEB_TLS_CERT_FILE` | 必填 | PEM 证书链绝对路径 |
| `WEB_TLS_KEY_FILE` | 必填 | PEM 私钥绝对路径 |
| `WEB_TLS_SERVER_NAME` | `localhost` | 健康检查校验的证书 SAN 名称 |
| `WEB_TLS_CA_FILE` | 未设置 | 可选的健康检查根 CA 文件 |
| `WEB_HEALTH_HOST` | `127.0.0.1` | HTTPS 健康检查连接地址 |
| `WEB_THREADS` | `4` | Gunicorn `gthread` 线程数，范围 1..16 |
| `KMS_PUBLIC_HOST` | 未设置 | 页面默认 KMS 主机；为空时浏览器使用当前网站主机名 |
| `KMS_PUBLIC_PORT` | 未设置 | 页面默认 KMS 外部端口；未设置时读取 `PORT`，再回退到 `1688` |
| `EPID` | 空 | 指定 ePID；为空则由 KMS 服务生成 |
| `LCID` | `1033` | 生成 ePID 时使用的语言区域编号 |
| `CLIENT_COUNT` | `26` | 传给服务端的模拟响应客户端数量设置，非网站真实记录数 |
| `ACTIVATION_INTERVAL` | `120` | 激活失败后的重试间隔，单位分钟 |
| `RENEWAL_INTERVAL` | `10080` | 续期间隔，单位分钟 |
| `HWID` | `364F463A8863D35F` | 硬件标识；可设为 `RANDOM` |
| `LOGLEVEL` | `ERROR` | KMS 日志级别 |
| `LOGFILE` | `/var/log/HYX-KMS-PY_server.log` | KMS 日志目标，推荐容器部署显式设置 `STDOUT` |
| `LOGSIZE` | 空 | 文件轮转大小，MB，每单位 `1024 × 1024` 字节；空值不传给 CLI |
| `KMS_NEW_IDENTITY_PER_MIN` | `60` | 全局新客户端身份每分钟创建预算 |
| `KMS_NEW_IDENTITY_PER_SOURCE_PER_MIN` | `10` | 单一来源 IP 的新身份每分钟预算 |
| `KMS_MAX_CONNECTIONS_PER_SOURCE` | `16` | 单一来源同时打开的 KMS 连接上限 |
| `KMS_MAX_CONNECTIONS` | `64` | KMS 全局活动连接上限，范围 1..4096 |
| `KMS_MAX_CLIENTS` | `10000` | SQLite 审计身份容量；满额只允许已有身份续期 |
| `KMS_IO_TIMEOUT` | `5` | 单次 RPC 收发的秒数，由启动脚本传给 `-t1` |
| `KMS_CONNECTION_LIFETIME` | `30` | 单连接总期限秒数，范围 `(0,300]` |

入口脚本自动向网站导出 `PYKMS_SQLITE_DB_PATH=/data/HYX-KMS-PY_database.db`。仅在独立运行网站时手动设置此变量。`PYKMS_LICENSE_PATH`、`PYKMS_VERSION_PATH` 可指定网站读取的许可文本和版本元数据文件，未提供相应文件时使用代码内的回退信息。`/data` 必须由容器 `hyx` 用户持有，入口会设置为 `0700`；数据库与文件日志分别为 `0600`。

若修改 `KMS_PUBLIC_*`，重建容器后刷新页面；不要只重启旧容器。若不设置域名而通过 IP 访问网站，页面默认显示这个 IP，这是当前设计行为。

推荐以只读根文件系统、`cap-drop=ALL`、`no-new-privileges`、PID/内存/CPU/文件描述符上限启动容器。`/data` 是唯一持久写卷，证书卷只读挂载；若应用因额外插件需要新写路径，应在审查和测试后增加最小卷或 tmpfs，不能直接移除整个只读边界。

## 原生 Python 运行

建议使用 Python 3.14.7 和虚拟环境。从项目根目录创建环境，安装现有运行依赖：

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install tzlocal 'Flask>=3.1,<4' 'gunicorn>=23,<24'
```

在终端一中启动 KMS 并写入数据库：

```bash
cd hyx_kms_py
KMS_ALLOWED_NETWORKS=192.168.10.0/24 \
../.venv/bin/python hyx_kms_server.py 0.0.0.0 1688 -s ./HYX-KMS-PY_database.db -V INFO -F STDOUT
```

终端二中启动网站；先确认终端一已成功创建数据库：

```bash
cd hyx_kms_py
PYKMS_SQLITE_DB_PATH="$PWD/HYX-KMS-PY_database.db" \
KMS_PUBLIC_HOST=kms.example.com KMS_PUBLIC_PORT=1688 \
WEB_HOST=127.0.0.1 WEB_TLS_CERT_FILE=/absolute/fullchain.pem \
WEB_TLS_KEY_FILE=/absolute/privkey.pem WEB_TLS_SERVER_NAME=localhost \
../.venv/bin/gunicorn -c python:hyx_kms_gunicorn hyx_kms_webui:app
```

以上为 Unix 类系统命令。Gunicorn 不适用于原生 Windows；Windows 本地页面开发可用已安装 Flask 的 Python 执行 `python -m flask --app hyx_kms_webui run --host 127.0.0.1 --port 8080 --cert /absolute/fullchain.pem --key /absolute/privkey.pem`，并在当前终端设置 `PYKMS_SQLITE_DB_PATH`。Flask 开发服务器只用于本地预览。

原生 GUI 需要 Tkinter、图形环境及 Pillow；相关进程管理选项可查看 `python3.14 hyx_kms_server.py etrigan --help`。`-g` 不是服务端根命令的选项；容器示例不提供 GUI。

## Linux 服务管理

完整网站优先使用前述 Docker 部署。仅原生 KMS 进程可以交由 systemd 管理，网站如需单独运行则需另设服务和数据库路径。

下面是仅 KMS 的 unit 示例，假定项目位于 `/opt/HYX-KMS-PY`，虚拟环境已安装依赖，`hyx` 服务账号已创建且 `/var/lib/hyx-kms-py` 可写。需由管理员按实际路径完成这些前置条件。

```ini
[Unit]
Description=HYX-KMS-PY KMS Service
After=network.target

[Service]
Type=simple
User=hyx
Group=hyx
WorkingDirectory=/opt/HYX-KMS-PY/hyx_kms_py
Environment=KMS_ALLOWED_NETWORKS=192.168.10.0/24
ExecStart=/opt/HYX-KMS-PY/.venv/bin/python hyx_kms_server.py 0.0.0.0 1688 -s /var/lib/hyx-kms-py/HYX-KMS-PY_database.db -V INFO -F STDOUT
Restart=on-failure
NoNewPrivileges=true
UMask=0077

[Install]
WantedBy=multi-user.target
```

安装到 `/etc/systemd/system/HYX-KMS-PY.service` 后，通过 `systemd-analyze verify` 检查，再执行 `systemctl daemon-reload` 和 `systemctl enable --now HYX-KMS-PY`；日志使用 `journalctl -u HYX-KMS-PY`。旧 Upstart 示例不再作为当前部署方式。

## 更新备份与回滚

### 更新

更新前记录当前容器使用的镜像 ID、数据卷与配置，使用[发布与运维](Operations.md)的备份工具生成带 SHA256 清单的一致性副本，并为旧镜像保留独立标签。按原部署方式构建新镜像并替换容器，继续挂载同一数据卷。更新后检查首页、激活脚本默认域名、健康端点和模拟协议请求。

启动脚本会初始化表与索引；重复身份的原始行先保存到迁移备份表，再合并最新状态与累计次数。先在数据库副本验证升级和恢复，不提供任意历史 Schema 的自动兼容保证。详见[整改验收](整改验收.md)。

### 在线一致性备份

以下命令在线创建 SQLite 一致性备份并生成校验清单，再把数据库和清单复制到宿主机受控目录：

```bash
backup_name="HYX-KMS-PY_$(date +%Y%m%d-%H%M%S).db"
docker exec HYX-KMS-PY mkdir -p /data/backups
docker exec HYX-KMS-PY python3 /opt/HYX-KMS-PY/scripts/backup_database.py \
  /data/HYX-KMS-PY_database.db "/data/backups/$backup_name"
docker cp "HYX-KMS-PY:/data/backups/$backup_name" ./backups/
docker cp "HYX-KMS-PY:/data/backups/$backup_name.json" ./backups/
```

工具会执行 `PRAGMA integrity_check`、核对行数和 SHA256。备份可能包含机器名、客户端 ID 等信息，存放到受控位置；完整性清单不能替代加密、访问控制与实际恢复演练。

### 恢复与回滚

先备份当前数据并停止服务，再将数据库及同名 `.json` 清单复制回数据卷。使用镜像内的恢复工具校验清单、SHA256、完整性和行数；工具会先生成预恢复备份，再以原子替换恢复。默认要求显式确认服务停止：

```bash
docker stop HYX-KMS-PY
docker cp ./backups/HYX-KMS-PY_YYYYMMDD-HHMMSS.db HYX-KMS-PY:/data/restore.db
docker cp ./backups/HYX-KMS-PY_YYYYMMDD-HHMMSS.db.json HYX-KMS-PY:/data/restore.db.json
docker run --rm --user hyx \
  -v HYX-KMS-PY-data:/data \
  --entrypoint python3 \
  hyx-kms-py:latest \
  /opt/HYX-KMS-PY/scripts/restore_database.py \
  /data/restore.db /data/HYX-KMS-PY_database.db --service-stopped
docker start HYX-KMS-PY
```

回滚使用保留的旧镜像标签与原部署配置，先确认该版本能读取当前数据库；若不能，使用与旧版本配套的备份。不要仅回滚镜像后假定数据兼容。恢复、sidecar 处理、身份归档与演练记录见[发布与运维](Operations.md)。

## 安全配置与升级门禁

新增连接、容量、访问边界、健康检查及迁移行为以[整改验收](整改验收.md)和[发布与运维](Operations.md)为准。网站不启用用户登录或 Basic 认证，所有页面在受控内网内匿名开放，但仍必须使用 HTTPS。部署者应把网站发布地址限制在内网接口，配置宿主机防火墙和反向代理访问边界；KMS 则使用 `KMS_ALLOWED_NETWORKS`、宿主机防火墙和上游 ACL 控制来源。不要把匿名网站或 KMS TCP 端口直接暴露到公网。KMS 会拒绝与服务端相差超过 4 小时的请求，因此宿主机和目标设备应启用可靠时间同步。生产升级需先备份、验证副本和回滚。
