# HYX-KMS-PY

HYX-KMS-PY 是基于 Python 的 KMS 协议模拟服务，网站显示名称为「密钥管理服务平台」。当前实现包含 KMS TCP 服务、客户端模拟工具、SQLite 客户端记录，以及 Flask/Gunicorn 网站；支持 KMS v4、v5、v6，项目使用 Python 3.14.7 验证。

网站提供首页、激活、产品和使用说明四个导航入口。激活页按 Windows、Windows Server、Office 分类，发行版本分组并从新到旧排列；Office 可选择 64 位或 32 位。界面支持简体中文、繁體中文、English、日本語、Français 切换并记住选择。网站生成可复制、可下载的客户端脚本，不在服务器上执行激活操作。

网站面向受控内网匿名开放，不启用用户登录或 HTTP Basic 认证。部署时仍必须使用 HTTPS，并通过宿主机监听地址、防火墙和 KMS 来源 CIDR 限制可访问网络；不能把这个匿名网站直接暴露到公网。

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [架构说明](docs/Documentation.md) | 模块职责、请求与数据流、端口、存储和运行边界 |
| [离线生产部署包](docs/Offline-Deployment.md) | 镜像、TLS 初始化脚本、启动脚本、校验与固定版本发布 |
| [部署与配置](docs/Getting%20Started.md) | Docker、本地启动、配置参数、指定域名、DNS、更新和备份 |
| [发布与运维](docs/Operations.md) | 上线检查、网络准入、证书轮换、备份恢复、身份归档、监控和发布门禁 |
| [使用说明](docs/Usage.md) | 网站操作、Office 架构、CLI 参数和验收 |
| [故障排查](docs/Troubleshooting.md) | 域名不显示、域名可解析但连接失败、数据库与脚本问题 |
| [GVLK 参考](docs/Keys.md) | 产品与密钥对照 |
| [Windows 版本核对](docs/Windows版本核对.md) | 微软官方清单核对结果、显示映射和未纳入范围 |
| [整体复核](docs/整体复核.md) | 产品、体验、安全、算法、企业级、演进、实施与运维的复核结论和改进优先级 |
| [整改与验收边界](docs/整改验收.md) | 连接预算、匿名访问边界、迁移、依赖与真实环境门禁 |
| [开发与文档维护](docs/Contributing.md) | 本地检查、文档构建和修改约定 |

## 快速启动完整网站

以下命令在项目根目录执行，供新实例使用。已有实例请先确认容器、镜像和数据卷名称，避免与现有服务争用端口。默认仅绑定本机，局域网部署与域名配置见部署文档。

生产离线交付应使用完整部署包。单独的 Docker 镜像 TAR 只包含运行载荷，首次部署还需要 TLS 初始化脚本、启动脚本和可信证书；打包与验收步骤见[离线生产部署包](docs/Offline-Deployment.md)。

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

访问 [本机网站](https://localhost/activate)。完整镜像只有在 `SQLITE=true` 时才同时启动数据库记录和网站；默认 `SQLITE=false` 只启动 KMS 服务。

页面「KMS 服务器」可通过 `KMS_PUBLIC_HOST=kms.example.com` 指定默认域名。这个参数只控制页面及生成脚本的默认地址；还需要独立设置 DNS 解析、TCP 端口映射和网络放行。完整步骤见[指定 KMS 域名](docs/Getting%20Started.md#指定-kms-域名)。

网站强制 HTTPS；本地证书、组织 CA、权限、轮换及健康检查配置见 [HTTPS 与本地证书](docs/HTTPS.md)。

完整容器默认使用单来源 KMS 连接准入和受控审计文件权限；`run.sh` 使用 `STDOUT`，并以只读根文件系统、`cap-drop=ALL`、`no-new-privileges`、非 root 用户和 PID/内存/CPU/文件描述符上限运行。网站对外默认发布到宿主机 HTTPS `443`，容器内部仍监听 `8080`；KMS 和网站默认都把发布地址限制在宿主机回环地址，局域网部署需显式设置发布地址并同步核对网络 ACL。

## 支持范围与验证边界

- Windows 客户端网页列表使用已对照微软通用 GVLK 清单的名称和既有 SKU，Windows 10/11 共用密钥的版本分别展示。旧嵌入式和专用条目保留于底层数据库，不混入通用脚本选择。
- Windows Server、Office 的协议标识与密钥来自 `hyx_kms_py/KmsDataBase.xml`，网站按 `activation_catalog.json` 的复审目录展示；Office 包含 2010、2013、2016、2019、LTSC 2021 和 LTSC 2024。列出产品或协议模拟通过，不等于所有版本已在真实设备上验收。
- `hyx_kms_client.py` 是协议模拟客户端；真实 Windows/Office 激活结果应在目标设备使用相应工具核实。GVLK 不替代软件使用授权。
- 原生运行入口位于 `hyx_kms_py/`，Docker 完整版位于 `docker/hyx-kms-py/`。

## 来源与许可

项目源自 py-kms / node-kms 技术谱系，早期实现涉及 cyrozap、CODYQX4 和 SystemRage 等贡献者。服务端声明 Unlicense，GUI 声明 MIT；部分底层模块另有 Apache、BSD 类及 LGPL 来源声明。随附许可正文与来源说明位于 `hyx_kms_py/licenses/`，商业分发前仍需核实精确来源修订和履行条件，不能用统一声明替代第三方条款。应保留原作者与上游版权信息。修改记录见 [变更记录](CHANGELOG.md)。
