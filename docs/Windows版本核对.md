# Windows 客户端版本核对

核对日期：2026-10-28。范围：网站产品类型「Windows」，不包含 Windows Server、Office。
依据：[Microsoft Learn：KMS 客户端激活和产品密钥](https://learn.microsoft.com/en-us/windows-server/get-started/kms-client-activation-keys)。

## 结论

- 原列表 47 条，36 条 GVLK 与本次微软官方通用清单一致，未发现这些密钥抄录错误。
- 以微软正式产品名称和发布分支整理为 52 个可选版本，使用 36 个既有 SKU；Windows 11 与 Windows 10 的共用密钥不再靠前端字符串猜测版本。
- 补齐 Windows 11 Pro for Workstations、Pro Education、Enterprise G，以及 LTSC 2024/2021 的显示映射；Pro/Professional、Workstations、N 及 LTSB 年份顺序以当前官方清单为准。
- 11 条未列入该通用清单的旧嵌入式或专用版本退出通用脚本选择，底层 XML 记录保留。没有在本次参考页找到对应的官方密钥对照，不据此判断这些产品本身是否支持 KMS。
- 官方清单中的 Windows IoT Enterprise LTSC 2024/2021 尚无本项目对应 SKU，未以其他产品密钥冒充支持。
- 这是名称、GVLK 和展示映射的文档/源码核对；不是微软服务验收、实际设备激活或生命周期支持承诺。

## 原有条目逐项结果

| 原条目 | 核对结果 | 网站展示处理 |
| --- | --- | --- |
| Windows 10 Enterprise LTSC 2019 | GVLK 一致 | Windows 11 Enterprise LTSC 2024；Windows 10 Enterprise LTSC 2021；Windows 10 Enterprise LTSC 2019 |
| Windows 10 Enterprise LTSC 2019 N | GVLK 一致 | Windows 11 Enterprise N LTSC 2024；Windows 10 Enterprise N LTSC 2021；Windows 10 Enterprise N LTSC 2019 |
| Windows 10 Enterprise G | GVLK 一致 | Windows 11 Enterprise G；Windows 10 Enterprise G |
| Windows 10 Enterprise G N | GVLK 一致 | Windows 11 Enterprise G N；Windows 10 Enterprise G N |
| Windows 10 Enterprise 2016 LTSB | GVLK 一致 | Windows 10 Enterprise LTSB 2016 |
| Windows 10 Enterprise 2016 LTSB N | GVLK 一致 | Windows 10 Enterprise N LTSB 2016 |
| Windows 10 Education | GVLK 一致 | Windows 11 Education；Windows 10 Education |
| Windows 10 Education N | GVLK 一致 | Windows 11 Education N；Windows 10 Education N |
| Windows 10 Enterprise | GVLK 一致 | Windows 11 Enterprise；Windows 10 Enterprise |
| Windows 10 Enterprise 2015 LTSB | GVLK 一致 | Windows 10 Enterprise LTSB 2015 |
| Windows 10 Enterprise 2015 LTSB N | GVLK 一致 | Windows 10 Enterprise N LTSB 2015 |
| Windows 10 Enterprise N | GVLK 一致 | Windows 11 Enterprise N；Windows 10 Enterprise N |
| Windows 10 Professional Workstation | GVLK 一致 | Windows 11 Pro for Workstations；Windows 10 Pro for Workstations |
| Windows 10 Professional Workstation N | GVLK 一致 | Windows 11 Pro for Workstations N；Windows 10 Pro for Workstations N |
| Windows 10 Professional | GVLK 一致 | Windows 11 Pro；Windows 10 Pro |
| Windows 10 Professional Education | GVLK 一致 | Windows 11 Pro Education；Windows 10 Pro Education |
| Windows 10 Professional Education N | GVLK 一致 | Windows 11 Pro Education N；Windows 10 Pro Education N |
| Windows 10 Professional N | GVLK 一致 | Windows 11 Pro N；Windows 10 Pro N |
| Windows 10 Enterprise for Virtual Desktops | 该参考页未列出 | 暂不在通用 Windows 列表展示，保留数据库记录 |
| Windows 10 Remote Server | 该参考页未列出 | 暂不在通用 Windows 列表展示，保留数据库记录 |
| Windows 10 S (Lean) | 该参考页未列出 | 暂不在通用 Windows 列表展示，保留数据库记录 |
| Windows 7 Enterprise | GVLK 一致 | Windows 7 Enterprise |
| Windows 7 Enterprise E | GVLK 一致 | Windows 7 Enterprise E |
| Windows 7 Enterprise N | GVLK 一致 | Windows 7 Enterprise N |
| Windows 7 Professional | GVLK 一致 | Windows 7 Professional |
| Windows 7 Professional E | GVLK 一致 | Windows 7 Professional E |
| Windows 7 Professional N | GVLK 一致 | Windows 7 Professional N |
| Windows 7 Embedded POSReady | 该参考页未列出 | 暂不在通用 Windows 列表展示，保留数据库记录 |
| Windows 7 Embedded Standard | 该参考页未列出 | 暂不在通用 Windows 列表展示，保留数据库记录 |
| Windows 7 ThinPC | 该参考页未列出 | 暂不在通用 Windows 列表展示，保留数据库记录 |
| Windows 8 Embedded Industry Professional | 该参考页未列出 | 暂不在通用 Windows 列表展示，保留数据库记录 |
| Windows 8 Embedded Industry Enterprise | 该参考页未列出 | 暂不在通用 Windows 列表展示，保留数据库记录 |
| Windows 8 Enterprise | GVLK 一致 | Windows 8 Enterprise |
| Windows 8 Enterprise N | GVLK 一致 | Windows 8 Enterprise N |
| Windows 8 Professional | GVLK 一致 | Windows 8 Pro |
| Windows 8 Professional N | GVLK 一致 | Windows 8 Pro N |
| Windows 8.1 Enterprise | GVLK 一致 | Windows 8.1 Enterprise |
| Windows 8.1 Enterprise N | GVLK 一致 | Windows 8.1 Enterprise N |
| Windows 8.1 Professional | GVLK 一致 | Windows 8.1 Pro |
| Windows 8.1 Professional N | GVLK 一致 | Windows 8.1 Pro N |
| Windows 8.1 Embedded Industry Professional | 该参考页未列出 | 暂不在通用 Windows 列表展示，保留数据库记录 |
| Windows 8.1 Embedded Industry Automotive | 该参考页未列出 | 暂不在通用 Windows 列表展示，保留数据库记录 |
| Windows 8.1 Embedded Industry Enterprise | 该参考页未列出 | 暂不在通用 Windows 列表展示，保留数据库记录 |
| Windows Vista Business | GVLK 一致 | Windows Vista Business |
| Windows Vista Business N | GVLK 一致 | Windows Vista Business N |
| Windows Vista Enterprise | GVLK 一致 | Windows Vista Enterprise |
| Windows Vista Enterprise N | GVLK 一致 | Windows Vista Enterprise N |

## 实现与复核

- `hyx_kms_py/windows_client_catalog.json` 仅保存官方产品名、分组和既有 SKU ID，实际 GVLK 仍从 `KmsDataBase.xml` 读取。
- `tests/fixtures/microsoft_windows_gvlks.json` 保存此次从官方表格提取的独立核对快照，供回归测试检查每个可选版本的名称与 GVLK。
- 共享 SKU 的版本使用独立下拉选项值，避免 Windows 10/11、LTSC 共用 ID 时选错显示版本。
- 后续修改产品数据库或映射后，运行 `python3 -B -m unittest discover -s tests -p 'test_webui.py'` 与 `node tests/test_activation.cjs`。官方来源变化时应重新获取清单并审阅快照差异。

## 下拉列表顺序

发行版本使用带分类标题的滚动下拉。Windows 依次为 11、11 LTSC 2024、10、10 LTSC 2021/2019、10 LTSB 2016/2015、8.1、8、7、Vista。Windows Server 与 Office 按版本年份倒序排列。可用方向键、Home/End 浏览，Enter 选择，Esc 关闭。
