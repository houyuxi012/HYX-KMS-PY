# 离线生产部署包

Docker 镜像归档是运行载荷，不等于完整的首次部署交付物。生产部署包必须同时包含镜像、校验信息、SBOM、TLS 准备脚本、启动脚本和部署文档。仅复制镜像 TAR 时，管理员还需要自行拼接一次性容器和启动命令，无法作为受控离线交付。

本项目的 `scripts/build_deployment_bundle.sh` 会生成一个 `hyx-kms-py-<版本>-linux-amd64-deployment.tar.gz`。解压后的目录结构如下：

在源码根目录生成部署包：

```bash
chmod +x scripts/build_deployment_bundle.sh
sh scripts/build_deployment_bundle.sh
```

```text
hyx-kms-py-<版本>-linux-amd64-deployment/
├── DEPLOYMENT.md
├── LICENSE
├── SHA256SUMS
├── VERSION
├── docker/hyx-kms-py/
│   ├── prepare-tls.sh
│   └── run.sh
├── docs/
└── image/
    ├── hyx-kms-py-<版本>-linux-amd64.bundle.json
    ├── hyx-kms-py-<版本>-linux-amd64.tar
    ├── hyx-kms-py-<版本>-linux-amd64.tar.sha256
    └── hyx-kms-py-<版本>-sbom.cdx.json
```

## 首次部署

以下命令在解压后的部署包根目录执行。先核验部署包与镜像：

```bash
sha256sum -c SHA256SUMS
cd image
sha256sum -c hyx-kms-py-<版本>-linux-amd64.tar.sha256
cd ..
docker load -i image/hyx-kms-py-<版本>-linux-amd64.tar
```

macOS 没有 `sha256sum` 时可将命令换成 `shasum -a 256 -c SHA256SUMS`。

确认版本并使用固定镜像标签。以下示例以 `2026.11.02-rc.3` 和 `kms.example.com` 为占位值：

```bash
VERSION=$(head -n 1 VERSION)
IMAGE="hyx-kms-py:${VERSION}-amd64"
docker image inspect "$IMAGE" --format '{{.Id}}'
```

准备 TLS 证书。证书必须是包含实际访问名称的完整 PEM 证书链，私钥必须与证书匹配：

```bash
bash docker/hyx-kms-py/prepare-tls.sh \
  /etc/hyx-kms/fullchain.pem \
  /etc/hyx-kms/privkey.pem \
  "$IMAGE" HYX-KMS-PY-tls
```

启动生产实例。`HYX_KMS_IMAGE` 固定到本次交付版本；`KMS_ALLOWED_NETWORKS` 必须替换为目标客户端实际来源，不能使用不受控的全网段：

```bash
HYX_KMS_IMAGE="$IMAGE" \
WEB_TLS_VOLUME=HYX-KMS-PY-tls \
WEB_TLS_SERVER_NAME=kms.example.com \
WEB_PUBLISH_ADDRESS=0.0.0.0 \
WEB_PUBLISH_PORT=443 \
KMS_PUBLISH_ADDRESS=0.0.0.0 \
KMS_PUBLISH_PORT=1688 \
KMS_ALLOWED_NETWORKS='192.168.10.0/24' \
KMS_PUBLIC_HOST=kms.example.com \
KMS_PUBLIC_PORT=1688 \
bash docker/hyx-kms-py/run.sh
```

检查容器、端口和 HTTPS：

```bash
docker ps --filter name=HYX-KMS-PY
docker logs --tail 100 HYX-KMS-PY
docker port HYX-KMS-PY
curl --fail --cacert /etc/hyx-kms/fullchain.pem \
  https://kms.example.com/livez
```

公开 CA 证书通常不需要 `--cacert`。本地自签名证书必须先由受控客户端安装信任根，不能通过关闭浏览器或客户端证书校验规避。

网站不启用用户登录或 HTTP Basic 认证，启动后内网客户端可直接访问激活页面。访问范围应由 `WEB_PUBLISH_ADDRESS`、宿主机防火墙和内网路由限制；不能因为取消登录认证就将 `443` 或 KMS `1688` 直接暴露到公网。

需要在受控内网启用 IPv6 时，再增加 `KMS_IPV6=true`、`WEB_IPV6=true` 和经过确认的 `KMS_IPV6_PUBLISH_ADDRESS`、`WEB_IPV6_PUBLISH_ADDRESS`。不要用 `::` 代替网络边界；完整 DNS、防火墙、Docker NAT 和客户端验收见[IPv6 双栈部署](IPv6.md)。

## 升级与回滚

升级前生成一致性备份，并记录当前镜像 ID、容器配置和 TLS 卷。加载新部署包后，先使用新镜像运行 TLS 准备工具，再重建同名容器，继续挂载原有 `HYX-KMS-PY-data` 和 `HYX-KMS-PY-tls` 卷。旧部署中的 `HYX-KMS-PY-auth` 卷不再读取，也不应传给新容器。

不要删除数据卷完成升级。回滚时恢复上一固定镜像标签，并按照[发布与运维](Operations.md)验证数据库 Schema、首页、健康端点和真实客户端；不能假定旧镜像可以读取新版本数据库。

## 交付边界

部署包中的自动化检查通过只能证明本地或隔离环境验收通过。正式生产上线仍需完成证书 SAN 与信任链检查、目标网络准入、真实 Windows/Windows Server/Office 激活与续期、备份恢复演练和容器资源监控。
