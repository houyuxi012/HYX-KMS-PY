# 发布与运维

本文定义当前单机 SQLite 版本的日常运维、故障恢复和发布门禁。示例容器名、卷名和地址均为占位值，执行前必须替换并与实际部署核对。当前源码测试通过不等于生产环境、真实设备、高可用或商业交付已经验收。

## 部署检查表

上线前逐项记录实际值，并由非开发人员按清单复核：

1. KMS 网站使用有效 TLS 证书，证书 SAN 与访问名称匹配；私钥只允许服务账号读取且不是符号链接。
2. 网站匿名开放范围已由 `WEB_PUBLISH_ADDRESS`、宿主机防火墙、反向代理和上游 ACL 限制在受控内网，`443` 未直接暴露到公网。
3. KMS 监听非回环地址时已设置 `KMS_ALLOWED_NETWORKS`，且没有使用不受控的 `0.0.0.0/0` 或 `::/0`。
4. 宿主机防火墙、Docker 端口发布和上游 NAT 都只放通业务所需来源；TCP 1688 与网站 HTTPS 端口分别验证。
5. 宿主机和客户端均使用可靠时间源；KMS 只接受与服务端相差不超过 4 小时的请求。
6. `/data` 位于持久卷，数据库、TLS 私钥、日志和备份的权限符合安全策略。
7. 容器使用非 root 用户、只读根文件系统、`cap-drop=ALL`、`no-new-privileges`、受限 tmpfs，以及明确的 PID、内存、CPU 和文件描述符上限。
8. `KMS_MAX_CLIENTS`、连接上限和每个来源新身份预算已按容量评估。
9. `/livez`、匿名 `/readyz`、真实 RPC bind 探测和目标网络连接均通过。
10. 发布产物记录版本、镜像 digest、SBOM、源码清单和配置差异；旧镜像与恢复点可回退。
11. 在隔离环境完成一次备份、恢复和目标版本升级演练，记录 RPO、RTO、数据行数与服务探测结果。
12. 完成部署所需的真实 Windows、Windows Server 和 Office 授权设备验收，并保留脱敏证据。

## 容器运行边界

推荐运行参数以 `docker/hyx-kms-py/run.sh` 为准：根文件系统只读，`/tmp` 使用 `noexec,nosuid,nodev` 的受限 tmpfs，丢弃全部 Linux capabilities，禁止提权，并限制 PID、内存、CPU 与文件描述符。`/data` 是唯一持久写卷；TLS 卷以只读方式挂载。若额外插件需要新写路径，应审查其数据后仅增加最小 tmpfs 或卷，不能直接取消只读根文件系统。

`run.sh` 默认只把网站和 KMS 发布到宿主机 `127.0.0.1`：网站使用 HTTPS `443` 映射到容器内 `8080`，KMS 使用 `1688`。局域网部署应显式设置 `KMS_PUBLISH_ADDRESS`，同时核对 `KMS_ALLOWED_NETWORKS`、宿主机防火墙和上游 NAT；`KMS_PUBLISH_PORT`、`WEB_PUBLISH_ADDRESS`、`WEB_PUBLISH_PORT` 控制其余发布位置。默认资源限额可通过 `KMS_PIDS_LIMIT`、`KMS_MEMORY_LIMIT`、`KMS_CPU_LIMIT`、`KMS_NOFILE_LIMIT` 覆盖，调整前要记录容量依据。

## 网络准入与 NAT

`KMS_ALLOWED_NETWORKS` 接收逗号分隔的 IPv4/IPv6 CIDR，最多 64 项。程序总会加入 `127.0.0.0/8` 和 `::1/128` 以保留本机健康探测。非回环监听缺少该变量时服务拒绝启动。

准入检查使用 KMS 进程实际看到的 TCP 来源地址，不是 `X-Forwarded-For`，也不是客户端自报地址。Docker bridge、云负载均衡或 NAT 可能把多个客户端显示为上游网关；此时白名单应填写实际观察到的上游 CIDR，并同时确认上游已经实施来源限制。不要为了绕过连通性问题放通全部地址。可通过受控连接和 INFO 日志核对实际来源，日志不得包含不必要的客户端数据。

示例仅允许观察到的内网来源：

```bash
-e KMS_ALLOWED_NETWORKS=192.168.10.0/24
```

若使用 IPv6，应同时验证 AAAA 解析、容器监听、宿主机发布、路由和实际来源 CIDR。IPv6 新身份预算按 `/64` 聚合；网络白名单仍应按实际可路由前缀收窄。

## 证书轮换

TLS 轮换使用 `prepare-tls.sh` 原子替换证书卷中的当前版本。新证书必须包含访问域名和健康检查名称，私钥与证书匹配，私钥权限为 `0600`。重启前先验证有效期与信任链；重启后检查 HSTS、证书 SAN、匿名 `/readyz` 和外部客户端。组合容器重启会短暂中断 KMS，应纳入维护窗口。

Windows 原生部署通过 PowerShell 校验文件 DACL。仅服务账号、`SYSTEM` 和 `Administrators` 可以读取 TLS 私钥；ACL 无法验证或私钥为符号链接时程序失败关闭。网站没有用户名、密码文件或健康检查令牌，因此不执行凭据轮换。

## 备份

镜像内提供一致性 SQLite 备份工具。先创建受控备份目录，再从运行中的容器执行：

```bash
docker exec HYX-KMS-PY mkdir -p /data/backups
docker exec HYX-KMS-PY python3 \
  /opt/HYX-KMS-PY/scripts/backup_database.py \
  /data/HYX-KMS-PY_database.db \
  /data/backups/HYX-KMS-PY_$(date +%Y%m%d-%H%M%S).db
```

工具使用 SQLite 在线备份 API，校验 `PRAGMA integrity_check`、`clients` 表与行数，并生成同名 `.json` 清单。数据库与清单权限为 `0600`。将两者复制到不同故障域的受控介质：

```bash
docker cp HYX-KMS-PY:/data/backups/HYX-KMS-PY_YYYYMMDD-HHMMSS.db ./backups/
docker cp HYX-KMS-PY:/data/backups/HYX-KMS-PY_YYYYMMDD-HHMMSS.db.json ./backups/
```

备份包含客户端标识、机器名和统计信息。传输与静态存储应加密，访问应审计。定期检查备份新鲜度、SHA256、完整性和实际恢复，不能只检查文件是否存在。

## 恢复

恢复必须在 KMS 和网站都已停止时进行。工具默认拒绝继续，直到显式传入 `--service-stopped`；它还会拒绝校验失败的清单、错误 SHA256、错误行数以及未确认的 SQLite 残留 sidecar 文件。

先将数据库和清单复制到已停止容器的 `/data`，然后使用同版本镜像启动一次性辅助容器：

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

目标数据库存在时，工具先生成并验证 `pre-restore` 备份，再把副本写入同目录临时文件、再次检查完整性、保留原所有者、强制 `0600` 并原子替换。若已确认服务停止但仍存在 `-wal`、`-shm` 或 `-journal`，核对来源后可显式增加 `--discard-stale-sidecars`。

恢复后必须核对数据库行数、客户端统计、首页、`/readyz`、模拟协议往返和真实授权设备。失败时停止新版本，使用 pre-restore 备份或上一发布点的备份恢复；不得只回滚镜像并假定数据库 Schema 兼容。

## 身份归档

达到 `KMS_MAX_CLIENTS` 时不会自动删除身份。先使用归档工具的预演模式统计将受影响的记录：

```bash
python3 scripts/archive_identities.py /path/to/HYX-KMS-PY_database.db \
  --older-than-days 90 --limit 1000 \
  --operator operator-id --reason "approved retention policy"
```

预演不删除数据。复核数量和保留期后增加 `--confirm`，工具在同一事务内：

- 将原记录完整移动到 `identity_archive`；
- 保存请求次数、归档时间、原因和操作编号；
- 在 `identity_archive_manifest` 写入操作人、截止时间、数量和总请求次数；
- 只删除 `clients` 中的对应行，使新身份可以重新准入。
- 在提交事务前确认数据库可收紧为 `0600`；权限调整失败会回滚，不会出现“命令报失败但归档已提交”。

归档不是匿名化或删除。数据库和日志的最终保留期限、访问审批、导出与删除责任必须由组织策略确定。归档前应先做可恢复备份，归档后在隔离副本验证新身份准入、旧身份重新出现和审计追溯。

## 监控、容量与告警

建议至少监控：

| 指标 | 建议来源 | 告警条件 |
| --- | --- | --- |
| 网站进程存活 | `/livez` | 连续 3 次失败 |
| 依赖就绪 | 匿名 `/readyz` | 连续 3 次失败或持续 90 秒 |
| KMS 协议 | 受控 RPC bind 探测 | 端口不可连、绑定失败或额度耗尽 |
| TLS 到期 | 证书检查 | 少于 30 天提醒，少于 7 天升级 |
| 客户端容量 | `clients` 行数和写入日志 | 达到 80%、90%，满额立即告警 |
| SQLite 与磁盘 | 数据库文件、备份卷、日志卷 | 可用空间不足、I/O 错误、备份过期 |
| 进程与重启 | 容器状态和编排事件 | 非计划重启、OOM、启动失败 |

`/readyz` 缓存 5 秒以限制重复探测成本；它是就绪信号，不证明完整激活成功。完整镜像使用单 Gunicorn worker 和默认 4 个 `gthread` 线程，`WEB_THREADS` 上限为 16。线程只能提高有限并发，不能替代内网访问边界、数据库容量评估或外部负载均衡。

## 发布门禁

在源码根目录运行：

```bash
python3 scripts/build_product_matrix.py --check
python3 scripts/generate_sbom.py --check
python3 -m sphinx -b html -n -W --keep-going docs /tmp/hyx-docs-build
sh scripts/run_checks.sh
```

镜像发布前还应构建完整和精简版本，以非 root 用户、只读根文件系统和上述运行时限制启动，检查 HEALTHCHECK，并记录绝对镜像 digest。`VERSION`、`sbom.cdx.json`、产品矩阵和源码清单必须对应同一构建；当前目录若不包含版本库元数据，应另存源码归档哈希，不能把工作区路径当作可追溯提交。

2026-11-02 的 `2026.11.02-rc.2` linux/amd64 完整镜像归档载入后内容 ID 为 `sha256:317abb5e05a394912173c0e9c1c1cfa40bb379a2e06c6fdc22dcfa87afe48965`，精简镜像本机构建标识为 `sha256:aae5512ac60596ddaa40be368caa7f2431bc1599aac805accbf71d952656c24a`。镜像归档 SHA256 为 `ab349ee5633f884e2953ce7136eb5046e43982d2d42ed6610b152810e1aa308b`。这些是本机归档与镜像标识，不是 registry RepoDigest；正式发布仍须绑定并保存推送后的绝对 digest。

依赖锁定文件包含哈希，SBOM 由锁定文件确定性生成。发布时仍需执行依赖漏洞查询并保存查询时间与数据库来源；未发现漏洞只代表查询时点结果。

## 尚未完成的验收

以下项目必须在目标环境单独完成：

- 真实 Windows、Windows Server、Office 两种位数、IPv6 和自定义端口激活与续期；
- 负荷、并发、长时间运行、故障注入、RPO/RTO 与周期恢复演练；
- Windows ACL、ARM 各架构镜像、GUI 图形环境和外部反向代理；
- 多节点、高可用、共享存储或故障切换；
- 第三方源码精确上游修订、许可证义务与商业分发法律审核；
- 对当前最终源码重新执行完整安全扫描并封存报告。

在上述证据完成前，本项目只能声明为当前测试实例和本地回归通过，不能声明生产就绪、企业级高可用或商业交付完成。
