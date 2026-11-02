# 使用说明

## 网站操作

网站标题为「密钥管理服务平台」，导航包含首页、激活、产品、使用说明，软件许可位于页脚。完整镜像需要 `SQLITE=true` 才会启动网站；部署、域名和端口配置见[部署与配置](Getting%20Started.md)。

### 语言切换

导航右侧提供简体中文、繁體中文、English、日本語、Français。手动选择优先于浏览器语言，并通过受保护的 Cookie 记住一年；未选择时按浏览器语言匹配，`zh-TW`、`zh-HK`、`zh-MO`、`zh-Hant` 等繁体标签匹配繁体中文，简体标签匹配简体中文，未匹配时默认简体中文。导航、页面标题、使用说明、字段、复制和校验提示以及日期显示随语言切换。产品名称、GVLK、许可原文与下载脚本的命令保持不变。切换语言会重新加载当前页面。

### 首页

首页从 SQLite 读取客户端请求记录，显示机器名、产品、许可状态、最近请求时间和请求次数。记录来自客户端请求，不等同于设备资产清单或独立验证后的许可证明。数据库不记录请求 IP，页面已移除对应空列。访问次数与运行时间保存在网站进程内，重启后重新计数。

### 激活页面

1. 选择产品类型：Windows、Windows Server 或 Office。
2. 选择发行版本与具体版本。下拉框使用分类标题，按新版本到旧版本排列；Windows 目录的核对范围见 [Windows 版本核对](Windows版本核对.md)。
3. Office 另选系统架构：按已安装 **Office 的位数**选择 x64 或 x86。64 位 Windows 上也可能安装 32 位 Office；架构不会改变产品密钥。
4. 展开「高级设置」核对「KMS 服务器」和端口。普通使用时页面会自动使用当前网站主机名与 TCP 1688，无需修改；仅当管理员配置了其他对外域名或端口时再调整。已配置的非默认端口及端口错误会自动展开，便于核对和修正。管理员可用 `KMS_PUBLIC_HOST` 与 `KMS_PUBLIC_PORT` 设置默认值，用户仍可手动修改。
5. 查看命令，复制或下载 BAT 脚本。在目标机器运行前核对产品、密钥、域名和端口，并确认已有相应使用授权。

Office 已安装套件时应选择相应 Professional Plus 或 Standard；单独安装的 Project、Visio 或其他应用才选择对应单品。默认选择 Windows 11 Pro、Windows Server 2025 Standard、Office LTSC Professional Plus 2024。

页面只在浏览器生成脚本，不会自动连接目标 Windows 设备或执行激活。BAT 使用 ASCII 和 Windows 换行格式。运行需要目标设备的管理员权限；脚本会安装所选 GVLK 并改变 KMS 主机设置，执行前应保留原配置。

Windows 脚本使用 `slmgr.vbs`；Office 脚本按所选架构查找 `OSPP.VBS`，先检查 `Microsoft Office\root\OfficeXX`，再检查 `Microsoft Office\OfficeXX`。Office 2010 对应 `Office14`，2013 对应 `Office15`，2016 及之后对应 `Office16`。找不到脚本时停止，不会自动安装 Office。

GVLK 是公开的批量许可客户端安装密钥，不代表已购买许可，也不是 KMS 主机密钥。Office 的此流程面向支持批量激活的版本，不适用于 Microsoft 365 订阅版。参见 [Microsoft Office GVLK 文档](https://learn.microsoft.com/en-us/office/volume-license-activation/gvlks)及 [Office 激活管理工具](https://learn.microsoft.com/en-us/office/volume-license-activation/tools-to-manage-volume-activation-of-office)。

### 产品页面

产品页与激活页使用同一份筛选目录：数据来自内置 XML，Windows 显示名称再由 JSON 映射。XML 中的旧版或特殊 SKU 不一定在页面展示。目录由网站进程缓存，更新数据文件后需重启网站进程。

## 原生服务端参数

以下命令在 `hyx_kms_py/` 目录执行。完整参数以本版本帮助为准：

```bash
python3.14 hyx_kms_server.py --help
python3.14 hyx_kms_server.py connect --help
python3.14 hyx_kms_server.py etrigan --help
```

(server-parameters)=
### 常用配置

| 参数 | CLI 默认值 | 说明 |
| --- | --- | --- |
| 位置参数 `ip`、`port` | `0.0.0.0`、`1688` | 本机监听地址和 TCP 端口 |
| `-e` / `--epid` | 未指定 | 固定响应 ePID；否则生成 |
| `-l` / `--lcid` | `1033` | 生成 ePID 时使用的区域编号 |
| `-c` / `--client-count` | 未指定 | 模拟响应客户端数，不是 SQLite 唯一设备数 |
| `-a` / `--activation-interval` | `120` | 激活重试间隔，分钟 |
| `-r` / `--renewal-interval` | `10080` | 续期间隔，分钟 |
| `-s` / `--sqlite [路径]` | 关闭 | 启用客户端记录；省略路径时用当前目录的 `HYX-KMS-PY_database.db` |
| `-w` / `--hwid` | `364F463A8863D35F` | 16 位十六进制字符；`RANDOM` 表示生成 |
| `-t0` / `--timeout-idle` | 无限制 | 服务端空闲等待超时，秒 |
| `-t1` / `--timeout-sndrcv` | 未指定时有效值 5 秒 | 单个连接收发超时，秒 |
| `-y` / `--async-msg` | 关闭 | 异步输出消息 |
| `-V` / `--loglevel` | `ERROR` | CRITICAL、ERROR、WARNING、INFO、DEBUG 或 MININFO |
| `-F` / `--logfile` | `./HYX-KMS-PY_server.log` | 日志文件或输出模式；容器建议 `STDOUT` |
| `-S` / `--logsize` | `0` | 轮转大小，MB，每单位为 `1024 × 1024` 字节；0 表示不限制 |

例如，仅监听本机并开启记录和标准输出：

```bash
python3.14 hyx_kms_server.py 127.0.0.1 1688 -s ./HYX-KMS-PY_database.db -V INFO -F STDOUT
```

`connect` 子命令支持重复 `-n IP,PORT` 添加监听地址、`-b` 调整 backlog、`-u` 关闭端口复用、`-d` 启用双栈监听。IPv6 是否可用还取决于系统、容器发布和网络，不应只靠参数推断。

`etrigan` 提供原生进程管理功能；容器已有入口脚本和 Docker 重启策略，不需要在容器中再启动守护进程。GUI 依赖图形环境及可选组件，不属于完整镜像的网站。

(docker-environment)=
### 容器环境变量

环境变量的完整表格统一维护在[部署与配置](Getting%20Started.md#docker-环境变量)，避免与 CLI 默认值混淆。

## 模拟客户端

`hyx_kms_client.py` 用于协议开发检查，不会激活运行它的操作系统。先启动测试服务，再在另一个终端执行：

```bash
cd hyx_kms_py
python3.14 hyx_kms_client.py 127.0.0.1 1688 -m Windows11 -V INFO -F STDOUT
python3.14 hyx_kms_client.py 127.0.0.1 1688 -m WindowsServer2025 -V INFO -F STDOUT
python3.14 hyx_kms_client.py 127.0.0.1 1688 -m Office2021 -V INFO -F STDOUT
python3.14 hyx_kms_client.py 127.0.0.1 1688 -m Office2024 -V INFO -F STDOUT
```

支持的模式为 WindowsVista、Windows7、Windows8、Windows8.1、Windows10、Windows11、WindowsServer2025、Office2010、Office2013、Office2016、Office2019、Office2021、Office2024；默认 Windows8.1。建议显式指定服务器地址，避免依赖默认地址。

Windows11 模式默认模拟 Enterprise，复用 Windows 10 批量许可标识，服务端可能显示 Windows 10 名称。WindowsServer2025 默认模拟 Standard；Office2021/2024 默认模拟 LTSC Professional Plus。不能据此宣称同一系列全部 SKU 都已完成真实激活验收。

| 参数 | 作用 |
| --- | --- |
| `ip`、`port` | 目标服务地址与 TCP 端口，端口默认 1688 |
| `-m` / `--mode` | 模拟产品 |
| `-c` / `--cmid` | 客户端 UUID；未指定时随机生成 |
| `-n` / `--name` | ASCII 机器名；未指定时生成 |
| `-t0`、`-t1` | 连接与收发超时，默认无限制 |
| `-V`、`-F`、`-S`、`-y` | 日志级别、目标、轮转大小、异步输出 |

## 验收层次

| 层次 | 检查内容 | 能证明什么 |
| --- | --- | --- |
| 静态与数据检查 | 配置、官方 GVLK 快照、产品映射、文档构建 | 当前已覆盖规则和示例的一致性 |
| 本地回归 | Python 测试、浏览器脚本测试、v4/v5/v6 模拟往返 | 实现之间的本地一致性 |
| 部署验证 | 域名解析、TCP 可达、容器启动、数据库持久化、脚本默认值 | 指定环境中的连接和运行情况 |
| 真实设备验收 | 有授权的目标 Windows/Server/Office，管理员执行并查看状态 | 该设备、产品、版本与网络组合的实际结果 |

Windows 可用 `cscript //nologo %windir%\system32\slmgr.vbs /dlv` 和 `/xpr` 核对状态；Office 使用实际安装路径的 `cscript //nologo OSPP.VBS /dstatus`。保留产品版本、许可通道、架构、时间、错误码和脱敏日志。真实设备、负载、故障恢复和目标架构镜像应分别验收；本地模拟测试不能替代这些步骤。

本次全部展示产品的逐项检查见[产品可用性复审](产品可用性复审.md)及[逐项矩阵](产品可用性矩阵.csv)。
