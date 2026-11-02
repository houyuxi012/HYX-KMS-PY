# 贡献与维护

## 修改范围

当前运行源码位于 `hyx_kms_py/`；完整和精简镜像分别位于 `docker/hyx-kms-py/` 与 `docker/hyx-kms-py-minimal/`，测试位于 `tests/`，文档位于 `docs/`。不要将旧目录或 `docs/_build/` 当作源文件修改。

修改前追踪入口、调用方与数据契约，遵循目标文件现有风格，避免为格式统一重写无关模块。服务端、网站及数据文件需保持兼容；CLI、环境变量、路由或数据库发生变化时同步更新文档和覆盖相关行为的测试。

## 产品数据

- XML 是协议产品与密钥的现有数据来源；Windows 显示目录 `windows_client_catalog.json` 引用 SKU，不重复存储密钥。
- Windows 官方快照 `tests/fixtures/microsoft_windows_gvlks.json` 用于独立比较，不能为了让测试通过而直接从实现生成期望值。
- 新增或改名时核对官方产品名称、GVLK、SKU、产品分组和年份顺序，同步 [Windows 版本核对](Windows版本核对.md)与必要的[密钥参考](Keys.md)。Office/Server 应分别核对，不能沿用 Windows 已验证结论。
- 仅在已有授权的目标设备完成验收后，才能记录该设备和产品组合的真实结果。

## 本地检查

在项目根目录执行，Python 使用已安装运行依赖的环境；网络往返测试需要允许本机监听。

```bash
python3.14 scripts/build_product_matrix.py   # 重新生成 docs/产品可用性矩阵.csv
python3.14 scripts/generate_sbom.py          # 重新生成 sbom.cdx.json
sh scripts/run_checks.sh
```

统一检查会运行 Python 回归、Node 测试、产品矩阵和 SBOM 的 `--check`、Pyflakes 与 Sphinx 严格构建。Python 回归覆盖产品数据、配置、文件时间、网站、协议、daemon 生命周期、备份恢复与身份归档；测试通过不证明未覆盖的恶意输入、长期运行、真实设备或所有 CPU 架构均可靠。GUI、浏览器交互、目标镜像和容器改动还需相应的实际环境检查。

## 文档检查

Markdown/RST 是文档源，Sphinx 使用 MyST 解析 Markdown。依赖版本统一维护在 `docs/requirements.txt`。

```bash
python3.14 -m venv /tmp/hyx-docs-venv
/tmp/hyx-docs-venv/bin/python -m pip install -r docs/requirements.txt
/tmp/hyx-docs-venv/bin/python -m sphinx -b html -n -W --keep-going docs /tmp/hyx-docs-build
```

新增主文档时更新 `docs/index.rst`；使用相对链接，部署参数仅在主配置文档维护。涉及环境或版本限制时，注明依据和验收边界。构建产物不代替源文件交付。

## 交付说明

交付应包含变更目的、受影响入口、实际执行的验证与结果、未覆盖项、升级兼容性及必要回滚步骤。涉及第三方来源和许可证时保留原有声明，商业分发前核实依赖、源代码来源和许可材料的完整性。不得把模拟协议成功描述为真实设备验收通过。
