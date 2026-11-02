# HTTPS 与本地证书

网站必须使用 HTTPS，包括本机访问和健康检查。完整镜像启用网站（`SQLITE=true`）时，缺少证书、私钥不可读、私钥对其他用户开放或证书与私钥不匹配都会启动失败；不回退到 HTTP。不启用网站的 KMS 服务不需要证书，TCP 1688 协议不受影响。

## 证书要求

支持本地 PEM 格式证书链与未加密 PEM 私钥，包括组织 CA、公开 CA 和本地自签名证书。证书 SAN 必须包含实际访问的域名或 IP；只填写 CN 不足以满足现代客户端校验。证书文件可以含完整中间证书链，私钥需匹配。运行账号必须可读，私钥权限必须为 `600`（组内与其他用户不可读），父目录也应受控。私钥不得放入源码、镜像或日志。

自签名或组织 CA 证书需在客户端按组织流程安装对应信任根。服务读取证书不会自动建立浏览器信任。不要跳过浏览器证书错误或关闭客户端证书验证。

## Docker 准备与配置

构建新镜像后，显式将已选证书复制到专用卷。以下两个绝对路径替换为本地已有文件；不会修改原文件，也不会生成证书：

```bash
bash docker/hyx-kms-py/prepare-tls.sh /absolute/fullchain.pem /absolute/privkey.pem
```

脚本将证书交给容器 `hyx` 账号，以 `600` 保存至独立版本目录，并原子切换 `current`。运行时只读挂载；旧版本保留，回滚与清理由管理员处理。证书轮换后必须重启网站进程，Docker 部署可重启容器（同时短暂中断 KMS）。启动时会再次校验证书配对。

所有完整网站示例都需加入以下配置，`localhost` 替换为证书 SAN 中的实际名称：

```bash
-e WEB_TLS_CERT_FILE=/run/tls/current/fullchain.pem \
-e WEB_TLS_KEY_FILE=/run/tls/current/privkey.pem \
-e WEB_TLS_SERVER_NAME=localhost \
-v HYX-KMS-PY-tls:/run/tls:ro
```

健康检查连接本地 `127.0.0.1`，使用 `WEB_TLS_SERVER_NAME` 校验证书名称，不依赖域名在容器内解析到本机。默认同时使用系统信任库与证书文件，适合公开 CA 和自签名叶证书。组织 CA 或特殊证书链可显式提供根 CA：

```bash
bash docker/hyx-kms-py/prepare-tls.sh /absolute/fullchain.pem /absolute/privkey.pem hyx-kms-py:latest HYX-KMS-PY-tls /absolute/root-ca.pem
# 运行容器时额外添加：
# -e WEB_TLS_CA_FILE=/run/tls/current/ca.pem
```

`run.sh` 要求 `WEB_TLS_VOLUME=HYX-KMS-PY-tls`、`WEB_TLS_SERVER_NAME` 和 `KMS_ALLOWED_NETWORKS`。直接挂载本地证书目录也受支持，设置对应绝对容器路径并保证 `hyx` 可读；不要通过给组或其他用户读权限来解决 UID 差异。

## 原生运行

在 `hyx_kms_py/` 下使用已安装依赖的虚拟环境启动：

```bash
export WEB_TLS_CERT_FILE=/absolute/fullchain.pem
export WEB_TLS_KEY_FILE=/absolute/privkey.pem
export WEB_TLS_SERVER_NAME=localhost
export WEB_HOST=127.0.0.1
export WEB_PORT=8080
# 同时按部署文档设置数据库与 KMS 参数
../.venv/bin/gunicorn -c python:hyx_kms_gunicorn hyx_kms_webui:app
```

Unix 下使用 Gunicorn。Windows 本地开发可以使用 Flask 的 `--cert` 和 `--key` 参数提供 HTTPS，开发服务器不能用于正式部署。

## 访问与验收

容器对外默认使用 `-p 127.0.0.1:443:8080`：浏览器访问 `https://证书中的域名/activate`，容器内 Gunicorn 仍监听 `8080`，由 Docker 将其映射到标准 HTTPS 端口 `443`。原生运行可以先监听回环 `8080`，再由受控 HTTPS 代理或端口映射对外提供 `443`。HTTP 请求不会获得网站内容；服务不监听额外的 HTTP 跳转端口。

```bash
# 本机自签名示例，证书 SAN 需包含 localhost
curl --fail --cacert /absolute/fullchain.pem https://localhost/livez
# 容器内同时验证 HTTPS、证书名称、数据库和 KMS 就绪状态
docker exec HYX-KMS-PY sh -c 'cd /opt/HYX-KMS-PY/hyx_kms_py && python3 -c "from hyx_kms_tls import probe_web; probe_web()"'
```

证书过期、名称错误或信任链不完整时，客户端和就绪检查会失败。TLS 最低版本为 1.2，安全响应包含 HSTS。若使用反向代理，上游也必须连接 HTTPS 并校验证书，应用不信任任意客户端提供的 `X-Forwarded-Proto`。网站不启用用户登录；HTTPS 负责传输机密性和完整性，访问范围仍由内网发布地址、防火墙和上游 ACL 限制。
