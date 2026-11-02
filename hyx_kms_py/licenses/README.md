# 来源与许可材料

本目录随源码及镜像交付，保留源文件中的第三方版权头。项目服务端声称 Unlicense；GUI 和 Etrigan 声称 MIT。以下正文依据源码声明的上游取得，不能将它们合并为单一项目许可。

| 组件 | 随附正文 | 来源 |
|---|---|---|
| 项目基础实现 | Project-Unlicense.txt | https://github.com/SystemRage/py-kms/blob/master/LICENSE |
| structure、dcerpc | Impacket-0.9.17.txt | https://github.com/fortra/impacket/blob/impacket_0_9_17/LICENSE |
| SlowAES 修改实现 | Apache-2.0.txt | https://www.apache.org/licenses/LICENSE-2.0.txt |
| multiprocessing logging 派生代码 | LGPL-3.0.txt、GPL-3.0.txt | https://github.com/jruere/multiprocessing-logging/blob/master/LICENSE 、https://www.gnu.org/licenses/gpl-3.0.txt |
| Etrigan | Etrigan-MIT.txt | https://github.com/SystemRage/Etrigan/blob/master/LICENSE |
| GUI | 原文件 MIT 声明；Etrigan 同作者 MIT 正文供参考 | 精确来源修订仍需核实 |
| FILETIME | Filetime-BSD.txt | hyx_kms_filetimes.py 原版权与条款 |
| Bulma 0.9.4 | Bulma-MIT.txt | https://github.com/jgthms/bulma/blob/0.9.4/LICENSE |

重要边界：当前导入源码没有保存上游 commit。Impacket 0.9.17 正文与头部所述修改版 Apache 许可相符，但不能据此证明每段派生源码的精确历史版本；GUI、XML 数据的精确来源及发行责任仍需维护者核实。补齐正文不等同于法律审批通过。Python 依赖的许可正文由锁定安装包的 dist-info 随镜像交付，发行时还需交付锁文件、组件清单与本项目相应源码。
