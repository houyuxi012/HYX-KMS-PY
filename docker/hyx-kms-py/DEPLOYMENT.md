# HYX-KMS-PY 离线生产部署包

本目录包含固定版本 Docker 镜像、镜像校验信息、SBOM、TLS 初始化脚本、生产启动脚本和部署文档。镜像 TAR 不是完整部署包，不能脱离这些运维脚本独立完成受控首装。

- 完整步骤：[离线生产部署包](docs/Offline-Deployment.md)
- 发布与恢复：[发布与运维](docs/Operations.md)
- 证书配置：[HTTPS 与本地证书](docs/HTTPS.md)
- 排障：[故障排查](docs/Troubleshooting.md)

解压后先执行：

```bash
sha256sum -c SHA256SUMS
```

随后按完整步骤加载镜像、准备 TLS 卷，并使用 `HYX_KMS_IMAGE` 固定本次生产版本启动。网站面向受控内网匿名开放，不创建认证文件或认证卷。
