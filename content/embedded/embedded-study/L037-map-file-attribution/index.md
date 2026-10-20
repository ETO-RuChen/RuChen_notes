+++
title = "Map 文件——把链接布局变成可审计的内存预算"
date = "2026-10-20T21:44:13+08:00"
lastmod = "2026-10-20T21:44:13+08:00"
summary = "从同一次构建的链接脚本、Map 与 ELF 追溯 STM32F407xx 固件的 Flash/RAM 静态占用与增长来源，建立可复核的预算和运行期证据边界。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 37
tags = ["map-file", "memory-budget", "gnu-ld", "stm32f407", "build-evidence"]
source_ids = ["GNU-LD-247", "GNU-BINUTILS-247", "GNU-GCC-LINK", "GNU-GCC-OPT", "ST-RM0090", "ST-DS8626", "ST-UM1725", "ST-PM0214", "ST-CUBEF4", "ST-PM0253", "ST-PM0264", "ST-RM0433"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L037"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# L037：Map 文件——把链接布局变成可审计的内存预算

> 阶段：调试与验证（`debugging-verification`）；主题：`map-file`。建议 75 分钟，可分两次完成。
> 本课状态：已通过 Reviewer 内容审查；不代表学习者已掌握。`hardware_verified=false`。
> 证据分层：本次有 GNU **Windows PE/COFF 主机链接**和主机 C 测试；没有 GNU ELF 主机执行记录，没有 Arm 目标构建、烧录或测量记录。STM32 代码均为**参考实现，待目标工程编译**。

## 1. 本节目标

**一个核心目标：**从同一次构建的链接脚本、Map 与 ELF 追溯 STM32F407xx 固件的 Flash/RAM 静态占用与增长来源，建立可复核的预算和运行期证据边界。

**新核心概念仅两个，与本次 `plan.json` 一致：**

1. **Map 的链接归因链**：把一个字节的来源追到构建选项、目标文件的输入节、链接规则、输出节和符号，而不是只报一个总数。
2. **静态内存预算的证据边界**：分别核算装载和运行所占的地址区间，明确哪些是内容、填充或预留，哪些必须另用运行期证据回答。

完成练习后，应能提交一张“来源—输入节—输出节—地址—长度—预算归属”表；指出一次增长的直接贡献者；拒绝把旧 Map、新 ELF 或静态栈预留拼成运行期结论。其他术语只是完成这两项判断的工具。

## 2. 它解决什么问题

“加一个 256 字节缓冲区，为什么固件文件没长 256 字节？”“`size` 看起来还有 RAM，为什么仍可能栈溢出？”这两个问题都不能靠一个总数回答。

先把问题拆开：

- 你在比较**哪个构建**？优化级别、链接脚本、库版本、节回收选项一致吗？
- 你说的“大”，是对象有效字节、输出节长度、文件大小、Flash 装载跨度，还是 RAM 运行占用？
- 你问的是链接器已经安排好的区间，还是某次中断嵌套时实际使用的峰值？

Map（链接映射报告）描述一次链接，不是处理器运行日志。GNU `ld` 可以报告输入目标文件如何映射到内存、符号值以及被抽取的静态库成员；具体格式和功能取决于链接器版本与目标格式。[GNU-LD-247，Options]

本课不重写链接器，不开发通用 Map 解析器，不改布局“挤出空间”，不加入新 UART、定时器或 DMA 实验。先获得可审核的结论，再决定是否需要优化。

| 本次证据 | 能回答 | 不能回答 |
| --- | --- | --- |
| 本机 PE 的 Map、`objdump`、符号表 | 此工具链在三次主机链接中放置/回收了什么 | STM32 的 ELF、Flash/SRAM 布局 |
| Host Fake（主机替身）预算测试 | 在人工约定的输入下，算式、阈值、错误码是否正确 | GNU 链接器是否真的产生该布局 |
| `budget_probe.c` 的主机逻辑测试 | 指针/长度传递、初值检查与重复调用反例 | MCU 启动文件是否正确执行、板上 SRAM 是否可用 |
| 将来目标 ELF + Map + 实际脚本 | 该目标链接安排的静态区间 | 动态栈峰值、DMA 可达性、启动复制已经成功 |
| 将来复位后的调试观察 | 那次固件运行到观察点时的特定内存值 | 所有负载、所有异常路径、长期最坏情况 |

## 3. 必要前置知识

学习状态记录已授 `compiler`、`linker-script`、`elf-map`、`startup`、`stack-heap`、`memory-layout`、`clock-tree`、`register-view`、`stack`，但 mastery 仍是 0；“授过”不等于你已经掌握。

只唤回三件事：

1. `../L015-elf-map/README.md`：ELF（Executable and Linkable Format，可执行与可链接格式）保存结构化产物；Map 是这一次链接的文字报告。
2. `../L014-linker-script/README.md`：链接脚本规定输入节如何进入输出节与命名存储区。
3. `../L036-stack-evidence/README.md`：栈的静态边界和运行中的 SP（栈指针）不是同一种证据。

若还不能说清 `.data` 为何既需要初值又要可写，先看第 4 节的双地址例子，再做增长归因。若实际生成工程尚不存在，先完成主机轨道；目标轨道仍按参考代码与待执行步骤交付，绝不将主机报告改名为目标报告。

## 4. 核心原理

### 4.1 概念一：Map 的链接归因链

从最直观的提问开始：“这 256 个字节是谁带进来的？”

```text
源文件 + 宏定义 + 编译选项
    → .o（目标文件）/ .a（静态库中的成员）
    → 输入节
    → 本次链接脚本的匹配规则 + 库抽取 + 节回收
    → 输出节：地址、长度、填充
    → MEMORY 区域与符号
    → ELF/Map 交叉核对
    → 需要时再看复位后的真实内存
```

一个 C 对象可能被优化掉，一个库文件只有部分成员被抽取，一个输入节也可能被回收；不能从源文件列表直接求最终占用。`--gc-sections` 根据根及其符号/重定位引用关系保留可达输入节；`KEEP` 可以保护脚本中指定的输入节。静态库“成员是否被抽出”和抽出后“哪些节被回收”是两个阶段，不要混为一谈。[GNU-LD-247，Options、Input Section Keep]

| 机制对象 | 在哪里定义 | 谁持有 | 谁配置/注入 | 如何流动 |
| --- | --- | --- | --- | --- |
| C 缓冲区、常量、计数器 | 应用 `.c` 中的定义 | 本例模块静态存储期对象 | 编译宏配置长度；调用者借用地址和长度 | 编译产生输入节，链接安排地址，启动初始化后由应用访问 |
| 输出节与 MEMORY 区域 | 本次实际 `.ld` | 构建工程的版本化配置 | 链接命令通过 `-T` 指定；不要猜脚本文件名 | 输入节匹配到输出节，再映射到区域 |
| Map | 链接器按 `-Map` 生成 | 该构建的证据目录 | 构建脚本提供输出路径和选项 | 人/审计程序读取；不会被 MCU “实例化”或调用 |
| 静态预算 | 预算表或检查函数 | 应用团队/审计脚本 | 调用者提供容量、边界与实际节区间 | 算术检查得到静态结论，再决定是否需要运行期验证 |

声明、实现、实例化、组装、使用在本例中各有位置：`.h` 声明检查函数；`.c` 实现算法；静态数组定义产生存储对象；构建文件组装目标文件及脚本；`main` 调用检查函数。**链接器放置对象不是运行期依赖注入，Map 更不是运行期句柄。**

### 4.2 概念二：静态内存预算的证据边界

对一个节至少问两个地址：

- VMA（Virtual Memory Address，运行地址）：程序按什么地址使用它。
- LMA（Load Memory Address，装载地址）：初始化内容从什么地址提供。GNU 脚本可通过 `AT` 或 `AT>` 指定；没有指定时也有规则，不能一律假定 VMA 等于 LMA。[GNU-LD-247，Basic Script Concepts、Output Section LMA]

常见的 F407 Flash 启动布局中，带初值的可写对象运行在 RAM，初值放在 Flash；启动代码复制它。零初始化对象需要 RAM 区间，通常不需要同长度 Flash 初值；启动代码清零它。**这是待核对的脚本/启动约定，不是节名自动施加的魔法。**[GNU-LD-247，Output Section LMA；ST-RM0090，§2；ST-PM0214，处理器复位模型]

下面完全是**手工构造的教学区间，不是本次 STM32 ELF/Map 输出**：

| 项目 | VMA 半开区间（含起点、不含终点） | LMA/初值 | 静态归属 |
| --- | --- | --- | --- |
| `.text` 1024 B | `[0x08000000,0x08000400)` | 同 VMA | Flash 1024 B |
| `.rodata` 64 B | `[0x08000400,0x08000440)` | 同 VMA | Flash 64 B |
| `.data` 16 B | `[0x20000000,0x20000010)` | `[0x08000440,0x08000450)` | RAM 16 B，另需 Flash 初值 16 B |
| `.bss` 256 B | `[0x20000010,0x20000110)` | 不提供同长度初值 | RAM 256 B |
| 明确预留 512 B | `[0x20000110,0x20000310)` | 无 | RAM 512 B，**不是实测栈峰值** |

因此这个人工模型中 Flash = 1024 + 64 + 16 = **1104 B**，RAM = 16 + 256 + 512 = **784 B**。给 `.bss` 加 256 B，只使 RAM 算式变成 1040 B；给 `.data` 加 128 B，则 Flash、RAM 分别变成 1232 B、912 B。第 8 节的 Fake 实际运行过这些**算术断言**，但没有声称目标链接产生过这些区间。

真实审计不能只背这两个加法。按存储区整理**区间的并集**：

1. Flash：计入需要装载到该 Flash 区的内容；常见还有向量表、异常索引、初始化数组和 `.data` 初值。
2. RAM：计入运行时在该区域分配的节及明确保留的区间，包括符合本构建语义的零初始化/NOLOAD 节。
3. 对齐产生的 `*fill*` 或节内尾部填充计入对应输出节；不要又把输入节之和、输出节总长各算一次。
4. 相邻地址间的洞要单独记账：有效内容之和、链接器区域预算和打包镜像跨度是不同指标。平坦二进制文件可能包含洞的填充，ELF 文件又含调试信息和文件头，均不能用文件字节数直接代替 Flash 有效内容。
5. 若有别名、重叠装载、保留升级槽，先说明物理区域与镜像约定，不能无条件相加。本课不设置重叠布局。
6. 用 `uint64_t` 等足够宽的中间值做求和，先检查再缩窄；32 位预算检查本身不应因相加回绕而误判。[GNU-LD-247，MEMORY、Output Section Address、Output Section LMA；GNU-BINUTILS-247，readelf、objdump]

`NOLOAD`（不作为普通装载内容的输出节属性）也不等于“不占 RAM”，更不等于“上电自动清零”或“跨复位保留”。GNU 2.47 手册专门说明 ELF 与其他输出格式的运行时空间行为差异，并提示其 ELF 行为可能变化；必须看**实际输出节类型、ALLOC 属性、程序头和启动处理范围**，不能跨版本/格式机械套用。[GNU-LD-247，Output Section Type]

### 4.3 栈与堆：预算表只能到哪一步

- `_estack` 等符号是地址，不会仅因有一个符号就自动分配一段可见输出节。
- `_Min_Stack_Size`/`_Min_Heap_Size` 若在 `.ld` 中用于推进位置计数器，会形成最小空间检查/预留；实际 SP 的起点和增长方向仍要查向量表与启动文件。
- 某些生成脚本把最小堆栈量放在静态数据之后，而真实初始 MSP 位于 RAM 顶部。应同时检查静态末端、堆策略、RAM 顶部和要求的栈边界，不能把脚本尾部的最小检查块直接当成实际栈底。
- Map 不能给出函数调用深度、嵌套 IRQ、局部变量存活峰值、动态分配峰值或堆碎片。本课没有动态内存调用；若链接进了库的堆支持，仍需查实际引用和保留区，而非猜测运行期发生过分配。[GNU-LD-247，Location Counter、MEMORY；ST-PM0214，栈、异常与复位]

## 5. 关键术语与直观模型

| 辅助术语 | 本课只用来回答什么 |
| --- | --- |
| 输入节 / 输出节 | 哪个 `.o` 贡献字节，脚本把它合并到哪里 |
| 符号 | 对象/函数或边界的链接名称与值；符号值不总是可解引用对象 |
| 对齐填充 | 为满足地址对齐插入/预留的空隙；也消耗区间 |
| 孤儿节（orphan section） | 脚本没有显式安置的输入节，链接器仍可能为它选择/新建输出节 |
| 节回收（section garbage collection） | 从链接根沿引用关系保留输入节，不等于按源文件删除函数 |
| 构建身份 | 工具版本、输入、命令、脚本、产物哈希共同界定的一次构建 |
| `readelf` / `objdump` / `nm` | 结构化交叉查看 ELF、节/装载信息、符号；能力和选项要匹配工具版本 |
| `size` | 总量或按节快速查看工具；不是内存拓扑和运行峰值证明 |

这些词不是新的课程目标。直观模型只有一个：“先找货单是哪一批，再找箱子来源、箱子落点，最后查仓库里的剩余位置；不能用货单推断工人某时刻拿了多少东西。”[GNU-LD-247；GNU-BINUTILS-247]

## 6. 从输入到结果的完整流程

### 6.1 审计顺序

1. **锁定构建**：保留源版本、编译宏、优化级别、工具路径/版本、完整编译链接命令、实际 `-T` 脚本、启动文件、库与目标文件哈希。
2. **先确认格式**：看文件头/`objdump -f`。Windows MinGW 产物不能仅改成 `.elf` 后交给 `readelf` 当成 ELF。
3. **从 Map 找来源**：先区分正常布局与 `Discarded input sections`（被丢弃输入节）区域，再记录目标对象/库成员、输入节、输出节、地址和长度。
4. **交叉结构化产物**：ELF 用 `readelf -S -l -W` 看节头、程序头，用 `objdump -h` 看节的 VMA/LMA，用 `nm -n -S` 看符号；Windows PE 本课用 `objdump`，不假装存在对应的 ELF 程序头。
5. **核对预算**：按区域核算内容、初值、预留和填充；再与真实器件容量、脚本区域及项目保留策略交叉核对。
6. **写有限结论**：标明证据支持到哪里，再列下一项需要的运行期证据。[GNU-LD-247，Options；GNU-BINUTILS-247，objdump、nm、readelf；ST-DS8626，§2、§8]

GNU GCC 的 `-Wl,` 把逗号分隔的选项转交链接器。两份不同 `-Map` 设置、混用其他工程的 `.ld`，或脚本路径未记录都会破坏可复核性。实际 Arm 工具链版本尚未选定，不能把本机 GCC 16.2 的版本号写成目标版本。[GNU-GCC-LINK]

### 6.2 本次真实主机归因，不是模拟 STM32 地址

本机工具：GCC `16.2.0`（MSYS2 Rev3），GNU Binutils `2.47.20260726`，链接器支持 `i386pep/i386pe`；产物是 `pei-x86-64`。本机随包的官方 GNU ld Info 手册声明版本为 2.47，语义据该手册与实际输出交叉验证，不冒充旧 GNU 2.9.1 手册或精确同日源码快照。

`host/attribution.c` 有一个静态工作数组，一个带初值计数器，一个只读表，一个未引用函数。`host/run_host.py` 用相同工具和选项做：

- A：`WORK_BYTES=64`，开启节回收。
- B：`WORK_BYTES=320`，开启节回收。
- C：`WORK_BYTES=64`，不启用节回收。

A/B 的实际 Map 片段（完整命令与哈希见随课证据）：

```text
A: 输出 .data 长度 0x60
   .data$boot_counter  0x0000000140002000  0x10  a.o
   *fill*             0x0000000140002010  0x10
   .data$work         0x0000000140002020  0x40  a.o
B: 输出 .data 长度 0x160
   .data$work         0x0000000140002020  0x140 b.o
```

以上是摘录并缩短了目标文件路径，不是完整 Map 格式规范。这里的 `$` 命名属于该工具链/格式；**不要替换成 ELF 的 `.bss.work` 后说是实际输出**。

归因表应这样写：

| 比较项 | A | B | 可审计结论 |
| --- | --- | --- | --- |
| 数组源码请求 | 64 B | 320 B | 编译宏增加 256 B |
| `.data$work` 输入贡献 | `0x40` | `0x140` | 输入节增加 `0x100` = 256 B |
| `.data` 输出节 | `0x60` | `0x160` | 本例输出节也增加 256 B |
| 数组起点 | `0x140002020` | 相同 | 本次其他前置贡献/对齐未使它移动 |
| 数组前计数器输入节 | `0x10` | `0x10` | C 计数器本身仅 4 B，但输入节长度含其布局成本 |
| 计数器后填充 | `0x10` | `0x10` | 不能漏算，也不能再重复加到输出总长 |

A 的 `.data` 区间为 `[0x140002000,0x140002060)`；B 为 `[0x140002000,0x140002160)`。这只说明 **PE 输出节** 的区间变化，没有任何 STM32 Flash/RAM 预算含义。本例还反驳“未显式初始化数组必然能在此工具链 Map 的 `.bss` 中找到”这种跨平台推断。

C 的 `.text` 为 `0x80`，A 为 `0x60`；未引用函数在 C 中有已定义 `T` 符号，在 A 中被回收。C 的 `.rdata` 也从 A 的 `0x30` 变为 `0x60`，因此不能把“关节回收导致文件总增长”全部算到那个函数名下。PE 文件对齐、头部/其他节也会影响文件大小。

**反例：Map 里搜到名字不等于它被保留。** A 的丢弃区域里仍列出 `.text$unused_marker`，`nm` 还可能出现 `U unused_marker`；`U` 是未定义标记，不是一个已保留的函数定义。驱动脚本检查 `T/t` 定义，并结合 Map 的丢弃区域和链接器回收日志，而不是简单做字符串包含判断。GNU 手册把 COFF/PE 的节回收实现标为实验性质；这些观察只对本次工具/输入负责。[GNU-LD-247，Options；GNU-BINUTILS-247，nm]

### 6.3 两次构建的差分，不是两个总数相减就结束

把 A、B 的区域表按“输出节—输入对象—输入节”对齐，再追溯变更：数组扩大、对象对齐、库成员抽取、格式化输出依赖、链接器填充或优化变化各有不同证据。

本次最简单的直接来源是编译宏；目标 F407 的相同实验则必须等真实 Arm ELF/Map 后重新归因。即使目标数组声明增加 256 B，也只能预测“有效对象容量增加”，不能提前宣布 Flash 或输出节恰好增加 256 B。

旧 Map 配新 ELF 的反例也不能靠文件修改时间来排除。主机脚本先验证 A 的哈希集合，再将 B 的映像作为 A 的候选映像交给同一验证函数，确认它被拒绝。哈希证明“等于先前记录的文件”，但不自动证明清单最初就是诚实的同一次链接；仍要同时保存单次构建命令和输出目录。

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

这里的“能力”是**链接布局与预算审计能力**，不是一个叫 Map 的硬件外设。

| 层级 | 工作机制与路径 | 配置/观察入口 | 本课落点与后续实验 |
| --- | --- | --- | --- |
| 基础 | `.o` 输入节被脚本汇入输出节，符号取得链接地址 | Map 布局区、ELF 节头、实际 `.ld` | 本课逐字节归因一个工作数组 |
| 进阶 | Flash 初值→启动复制→RAM；对齐使输入有效量与输出长度不完全相等 | VMA/LMA、启动复制边界、`*fill*`、两构建差分 | 本课分别核算 RAM 运行与 Flash 装载，主机验证增长反例 |
| 高级：节回收/保留 | 从链接入口/引用根沿重定位关系标记输入节；未引用节可能消失，向量等硬件入口通常需脚本保护 | `--gc-sections`、回收日志、`KEEP`、向量节匹配 | 本课 A/C 反例；后续 `host-test` 为保留入口和预算门槛写回归测试，不宣称本课已验证目标向量保留 |
| 高级：孤儿节 | 新输入节未被脚本显式匹配，链接器按属性选位置或新增输出节；普通 `.bss` 规则未必覆盖它 | Map 新增输出节、`--orphan-handling=warn`（工具支持时）、完整 ELF 节表 | 本课解释“只求熟悉节名之和”会漏账；后续 `unit-test` 在选定 GNU ELF 版本上制造一个自定义节，核对警告和区域再设门槛 |
| 高级：库/弱符号/断言 | 未定义引用促使库成员被抽取；弱/强定义选择改变实现和成本；链接断言拒绝违反地址约束的产物 | 链接命令库顺序、Map 库抽取说明、`--cref` 交叉引用、脚本 `ASSERT` | 本课按对象归因，不引入库设计；后续 `host-test` 比较链接入格式化输出前后的成员贡献，核对弱回调到底用了哪个定义 |
| 高级：保留区/多镜像 | 普通段布局不自动为升级元数据、第二镜像或保留 RAM 划界；装载位置和运行位置可不同 | `MEMORY`、输出节属性、镜像打包规则、启动初始化表 | 本课指出 NOLOAD 与真实保留语义边界；`boot-update-security/memory-map` 再验证镜像槽、元数据、地址冲突及复位后保留条件 |
| 跨外设联动 | 既有定时器触发 ADC→DMA 写缓冲区→IRQ 发布结果；链接只安排缓冲区地址，不执行触发或搬运 | 已授 L031/L032 的缓冲区定义、目标 Map、对应 RM 的总线访问路径 | 本课不重新启动外设。后续 `dma-coherency` 检查 DMA 能否访问该区、缓存维护是否正确；`bus-matrix` 再核对并发通路 |
| 跨外设联动：栈 | 外设事件→异常入口→IRQ 代码→共享栈/任务栈；静态向量和函数可见，动态嵌套不可由 Map 还原 | 向量/函数符号、静态边界；真实 SP、异常现场另取证 | 承接 L036，不从 IRQ 函数尺寸推断栈深度；后续调试/并发课程补实际路径 |

链接器机制依据 [GNU-LD-247]。F407 的 CCM（Core Coupled Memory，内核耦合存储器）由 CPU 的 D-bus 访问；把 DMA 缓冲区放入某个“有空闲的 RAM”并不能自动证明 DMA 可用。[ST-RM0090，§2.3]

**系列迁移清单，不把 F4 数值横向复制：**

| 系列 | 本课可迁移的机制 | 必须重查什么 | 后续可证伪实验 |
| --- | --- | --- | --- |
| F4，本课 F407VGT6 | 对象→节→区域→预算→运行观察 | 具体密度、SRAM1/2 与 CCM、启动初始化、保留区；不同 F4 也不能只看家族名 | 此处真实目标 A/B 构建，逐节核对 |
| F7，后续另选准确型号 | 同一构建的双地址与区域核算 | 先选具体器件及 RM/DS/勘误和 CubeF7 包，再确认 TCM（紧耦合存储器）、缓存及总线可达性；处理器手册不是器件容量证据 | `cache`/`dma-coherency`：比较“地址放得下”与“CPU/DMA 看到一致数据”两种证据 [ST-PM0253] |
| H5，后续另选准确型号 | 来源归因和不混构建的原则 | 器件具体安全配置、Secure/Non-secure（安全/非安全）内存归属、各镜像脚本、别名、启动初始化；本课不假定已启用安全扩展 | `boot-update-security/trustzone`、`memory-map`：按选定目标分别审计安全与非安全镜像，避免把同一物理资源算两次 [ST-PM0264，§1.3.2、§2.3.4] |
| H7，迁移文档以 H743 所属 RM0433 范围为例 | Map 只证明链接安排 | 不同 SRAM、TCM 与总线/时钟域的容量和访问方；实际订货密度另用 DS；不把 H743 单核资料当全部 H7 或双核结论 | `bus-matrix`/`dma-coherency`：给候选缓冲区逐项证明 CPU、DMA、域时钟和缓存路径 [ST-RM0433，§2.3.2、§2.4；ST-PM0253] |

以上是明确的后续核查路径，不表示 F7/H5/H7 工程已经创建或验证，也不把资料未覆盖的系列具体地址/请求映射写成事实。

### 7.2 参考目标与时钟/复位链

#### 参考器件与容量上界

本课为 STM32F407xx 选择一个**文档参考订货料号 STM32F407VGT6**：不表示用户拥有该芯片或任何对应开发板。DS8626 的 §8 中 `V` 对应 100 引脚、`G` 对应 1024 Kbytes Flash、`T` 对应 LQFP 封装；容量/分区仍与 RM0090 和生成脚本一起核对。[ST-DS8626，§2、§8]

| 物理区 | 本参考器件文档容量/半开区间 | 本课使用策略 |
| --- | --- | --- |
| 内部 Flash | 1024 KiB，`[0x08000000,0x08100000)` | Flash 启动参考；项目若有保留槽/头部，脚本可用范围要减去，不能按物理上限直接报余量 |
| 主 SRAM，SRAM1 + SRAM2 | 112 + 16 = 128 KiB，`[0x20000000,0x20020000)` | 放本课普通 `.data`、`.bss` 和栈；这只是设备上界对照，不替换实际脚本 |
| CCM data RAM | 64 KiB，`[0x10000000,0x10010000)` | 本课不放对象、不启用新复制/清零表，不与主 SRAM 连成“192 KiB 连续 RAM” |
| Backup SRAM（备份 SRAM） | 另有 4 KiB，存在独立供电/访问约束 | 不加进普通 `.bss` 或默认栈预算，本课不用 |

KiB 为 1024 字节。这里给出的是真实器件资料约束，不是测得的板上可访问性。若生成脚本写了 `RAM LENGTH=192K` 且从 `0x20000000` 连续覆盖，不应因“总 SRAM 192K”而接受它；首先查区域拆分和器件选择。[ST-RM0090，§2.3；ST-DS8626，器件特性与框图]

#### 参考时钟方案：只用内部 HSI，不猜板载晶振

为使参考实现不依赖未提供的外部晶振，本课从**真实复位状态**选择 HSI（High-Speed Internal，高速内部 RC 振荡器）的标称 16 MHz 路径，PLL（Phase-Locked Loop，锁相环）关闭。这是待工程编译/目标验证的**明确配置**，不是板上实测频率。[ST-RM0090，**第 7 章 F405/407 的 RCC**，§7.2.2、§7.2.6；ST-DS8626]

```text
复位：确认实际启动映射、向量表首项/复位入口、MSP
  → 实际 Reset_Handler
  → SystemInit 与 .data 复制 / .bss 清零（相对次序查所选启动文件）
  → C 运行库初始化（若启动文件调用）
  → main
  → HAL_Init：默认 SysTick 毫秒时基
  → BudgetClock_HSI：HSI 就绪，PLL 关闭，SYSCLK 选择 HSI
  → AHB /1：HCLK 与 CPU 标称 16 MHz
  → APB1 /1：PCLK1 标称 16 MHz
  → APB2 /1：PCLK2 标称 16 MHz
  → BudgetProbe_Run → 观察点
```

- `RCC_CR.HSION/HSIRDY` 表示启用/稳定；`RCC_CFGR.SW` 是选择，`SWS` 才是实际切换状态；HPRE、PPRE1、PPRE2 对应总线预分频。[ST-RM0090，§7.3.1、§7.3.3]
- 本课不启用新数据采集/输出外设，没有为本课新增的外设内核时钟、APB 门控、外设复位或定时器倍频/波特率字段需要设置；这些项目明确**不适用**，不能造出“Map 时钟使能位”。保留的 `HAL_MspInit` 若使能 SYSCFG/PWR 等系统支持，仍须逐项核对生成代码的门控，不把它们省略为“HAL 什么时钟都不碰”。SRAM/Flash 访问与处理器/总线时钟相关，但**Map 的链接地址与长度不由运行频率改变**。
- 唯一常规异常时基是 HAL 默认 SysTick；标称 HCLK=16 MHz 且选择内核时钟时，1 ms 对应 16000 个计数周期，重装值为 15999。实际应读 `SysTick->CTRL` 的时钟源和 `LOAD`，并核查是否覆写了 `HAL_InitTick`。软件 `HAL_RCC_GetHCLKFreq()` 的返回值不是频率测量。[ST-UM1725，§6.1；ST-PM0214，SysTick]
- `FLASH_LATENCY_0` 只用于本例低频 HSI 方案，仍须满足实际供电与 Flash 时序约束。若换为 168 MHz，不可保留本例所有字段；需重新设计电压、PLL、分频和 Flash wait states（等待周期）。[ST-RM0090，§3、§7；ST-DS8626，电气特性]
- 不手工覆盖 `SystemCoreClock` 来伪装时钟切换成功。检查实际 `SWS`、分频和 HAL/CMSIS 计算路径后，再使用软件频率值。

复位源与启动映射也要分开：RCC_CSR 的复位标志有历史/清除语义；仅在记录前读、不为本课无故清标志。选择 Flash 启动仍需实际板的启动脚/选项与调试器复位方式配合。仅直接跳到 `main` 不能当成“已执行启动复制/清零”。[ST-RM0090，§2.4、§7.1、§7.3.21；ST-PM0214，复位与向量表]

#### 文档/固件版本边界

已核对封面：RM0090 Rev 22（2026-05）、DS8626 Rev 12（2026-03）、UM1725 Rev 8（2023-03）、PM0214 Rev 10（2020-03）。注意 RM0090 同时覆盖多个子系列：本例 RCC 查**第 7 章**，不能把第 6 章 F42/F43 的总线限制搬来。

STM32CubeF4 官方版本页列出基础包 **1.28.0** 及 **Patch-CubeF4 1.28.3**。本课选“按官方适用说明组合至 1.28.3”作为将来参考工程的包边界，但本次**没有下载或检查固件包源码/补丁组合、没有 CubeMX 工程、没有确认该包中的具体 HAL 组件版本**。UM1725 的 API 结构已核对，不能用其 2023 日期冒充 1.28.3 的源码验证。生成前必须记录真实包版本、补丁说明、HAL/CMSIS 版本宏、所选启动文件和链接脚本哈希；不匹配则重新核对代码后构建。[ST-CUBEF4；ST-UM1725]

### 7.3 CubeMX、HAL、LL 与寄存器对照

#### CubeMX 配置清单——仅目标工程局部设置

下列是生成步骤，不是本次已执行的配置记录：

| 项目 | 参考选择 | 仍需实际记录/核查 |
| --- | --- | --- |
| 工具 | STM32CubeMX；按实际版本操作，不假定 CubeMX2 菜单相同 | 完整版本、工程 `.ioc` 与代码生成日志；本次未运行 |
| MCU Selector | `STM32F407VGT6`，不选一个假想开发板模板 | 实际芯片若不同，重查 DS/RM/勘误及全部容量 |
| Firmware Package | CubeF4 组合至 1.28.3 的参考边界 | 本机实际包目录、基础包/补丁适用说明、组件版本 |
| RCC | HSI 开；不依赖 HSE/LSE；主 PLL 不用于系统时钟 | 外部晶振频率本课不填、不引用；不要沿用其他板模板的 HSE 值 |
| Clock Configuration | SYSCLK=HSI；AHB/APB1/APB2 均 `/1` | 图上标称 16 MHz；实际供电、容差、寄存器、软件频率与测量边界 |
| SYS | 调试选择 Serial Wire（串行线调试）；默认 SysTick 时基 | 实际探针、接线、供电、复位方式由用户给出；不虚构引脚连接图 |
| 其他外设 | 全不新增；不分配 UART/ADC/TIM/DMA | 若添加观测输出，必须另交该外设时钟/门控/引脚与回调，超出本课范围 |
| Project Manager | 选择实际版本支持的 GNU Makefile 工程；记录工程名 | 若只支持其他构建系统，用其真实链接命令，不抄不存在的菜单 |
| 代码生成 | 保留生成 startup、system、HAL、异常入口和实际 `.ld` | 本课只替换应用 `main`、加入 probe/clock；不改全局 CubeMX/IDE 配置 |
| 链接 | 确认唯一 `-T`，输出同次 `.elf` / `.map`，可附 `--cref` | 脚本 MEMORY 与 F407VG 容量、栈/堆和保留区；保留向量等入口 |

#### 字段、对象所有权和调用顺序

`RCC_OscInitTypeDef` 和 `RCC_ClkInitTypeDef` 是 **HAL 的配置数据结构，不是长期持有外设的句柄**。本例在 `BudgetClock_HSI()` 栈帧内定义并零初始化，HAL 同步读取；函数结束后不保存其指针。[ST-UM1725，§54.1、§54.2]

| 字段 | 本例值 | 控制含义 |
| --- | --- | --- |
| `OscillatorType` | `RCC_OSCILLATORTYPE_HSI` | 指定本次处理 HSI；未选择的振荡器不凭零值猜成“都已配置” |
| `HSIState` | `RCC_HSI_ON` | 启用并等待 HSI 就绪 |
| `HSICalibrationValue` | `RCC_HSICALIBRATION_DEFAULT` | 使用库定义的默认微调，不做本课未实施的频率校准 |
| `PLL.PLLState` | `RCC_PLL_OFF` | 复位入口参考方案关闭主 PLL；PLL M/N/P/Q 字段在此不参与配置 |
| `ClockType` | SYSCLK/HCLK/PCLK1/PCLK2 的位掩码 | 明确四类时钟都要配置 |
| `SYSCLKSource` | `RCC_SYSCLKSOURCE_HSI` | 系统时钟选择 HSI |
| `AHBCLKDivider` | `RCC_SYSCLK_DIV1` | HCLK = SYSCLK /1 |
| `APB1CLKDivider`、`APB2CLKDivider` | `RCC_HCLK_DIV1` | 两条 APB = HCLK /1 |
| `HAL_RCC_ClockConfig` 第二参数 | `FLASH_LATENCY_0` | 本低频方案的 Flash 延迟参数，不是按 Map 占用自动推导 |

本课没有外设 `xxx_HandleTypeDef`，也没有 Map 的 HAL 句柄。静态存储区由链接器安排，启动代码初始化；HAL_RCC 不替你分配缓冲区。

调用顺序为 `HAL_Init()`→`BudgetClock_HSI()`→`BudgetProbe_Run()`。如果从 Bootloader（引导程序）跳入且 PLL 正在作系统时钟，直接要求关闭 PLL 可能失败；本例只承诺**真实复位入口**。需要通用时钟切换协议时另按实际前置状态设计，不能掩盖 `HAL_ERROR/HAL_TIMEOUT`。[ST-UM1725，§54.2.5]

#### HAL → CMSIS/LL 层职责或关键寄存器

CMSIS 是 Cortex 微控制器软件接口标准；这里使用厂商提供的处理器头和内建接口，不自行定义内核寄存器。LL（Low Layer，低层驱动）可提供较薄的寄存器封装，但本课不为展示名字而拼凑第二套初始化；用下表核对 HAL 背后的实际硬件事件即可。[ST-UM1725；ST-PM0214]

| 上层动作 | 底层/关键状态 | 审计重点 |
| --- | --- | --- |
| `HAL_RCC_OscConfig(&osc)` | `RCC_CR.HSION/HSIRDY`、`HSITRIM`；主 PLL 的 `PLLON/PLLRDY` | 请求与就绪分开，超时/错误返回必须处理；复位前置状态 |
| `HAL_RCC_ClockConfig(&clocks, ...)` | `RCC_CFGR.SW/SWS`、`HPRE/PPRE1/PPRE2`；`FLASH_ACR.LATENCY` | 先满足 Flash 时序与源就绪，再切换并验证；遵循该 HAL 实现的顺序 |
| `HAL_RCC_GetHCLKFreq()` | HAL/CMSIS 依据时钟配置计算的软件值 | 计算值不能代替示波器测量或真实 HSI 精度 |
| 生成工程的 `HAL_MspInit()`（依实际实现） | 可能涉及 `RCC_APB2ENR.SYSCFGEN` / `RCC_APB1ENR.PWREN` 等系统支持门控 | 查实际生成代码；本例 APB 标称 16 MHz，未设计新的外设数据路径 [ST-RM0090，§7.3.13、§7.3.14] |
| `HAL_Init()`/`HAL_InitTick()` | SysTick 的 `CTRL/LOAD/VAL`、异常优先级等 | 保留正常异常入口；时钟改变后时基仍要正确 |
| `SysTick_Handler`→`HAL_IncTick()` | SysTick 异常→HAL tick 计数 | 服务 HAL 轮询超时，不搬运本课数据 |
| 复位后的入口和 MSP | 实际启动映射、向量首项、MSP、`SCB->VTOR` | 用实际 ELF 向量与调试读数核对；Map 不会设置 MSP |
| `.data` 复制、`.bss` 清零 | 启动文件加载边界符号并读写内存 | 没有 HAL 内存布局 API；ELF/LMA 是输入，启动代码才执行复制 |
| 外设门控/复位、DMA 回调 | **本课不适用** | 没有启用新外设，不造 DMA IRQ 或完成回调来装饰流程 |

寄存器依据 [ST-RM0090，§3.9.1、§7.3.1、§7.3.3]；SysTick、MSP、VTOR 依据 [ST-PM0214]；HAL 入口依据 [ST-UM1725，§6、§54]。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

**可直接运行的文件**在 `host/`，不需要第三方 Python 包；需已有 Python 和上述 GNU Windows 工具。它们只在指定的新输出目录写文件，不安装工具、不触碰目标板。

从仓库根目录运行，输出目录和摘要文件必须尚不存在；可换成自己新的审计名：

```powershell
python lessons/L037-map-file-attribution/host/run_host.py `
  --output .state/tmp/L037-host-repeat `
  --summary .state/tmp/L037-host-repeat-summary.txt
```

脚本工作顺序：确认工具→记录版本/默认链接脚本→真实 PE A/B/C 链接→节表/符号表→编译并运行 Fake→编译并运行 probe 的主机逻辑→验证构建身份正例与错配反例→记录命令、退出码和 SHA-256。SHA-256 是用于核对文件内容的摘要，不是证明物理硬件行为的签名。

`attribution.c` 的三份入口映像没有运行，不能作为一般 Windows 应用执行：它们使用自定义入口、无运行库且故意停在循环。仅 `budget-fake.exe` 与 `probe-logic.exe` 是主机测试程序并实际执行。

本次最终证据：

- `evidence/host-run-final.txt`：版本、真实 Map 摘录、节表、测试结果与明确的硬件未执行声明。
- `evidence/host-manifest.json`：输入/脚本/对象/映像/Map 的哈希、完整 argv 和退出码；完整可再生构建输出在所记的 `.state/tmp` 目录，临时目录不作为长期板级证据。
- `evidence/source-verification.json`：文档版本、官方来源位置、核对位置和文件摘要，不复制第三方源码。

算术测试的实际输出：

```text
base flash=1104 ram=784 code=0
grow-bss flash=1104 ram=1040 code=2
grow-data flash=1232 ram=912 code=1
boundary-and-wide-sum PASS
```

错误码位 0 表示 Flash 超限，位 1 表示 RAM 超限；另有刚好等于上限、超 1 字节和宽位累加反例。输入结构由测试调用者持有；检查函数只借用输入和两个输出指针，本课测试始终传有效指针，不声称它是能接受任意空指针的公共库。

`probe-logic.exe` 还实际得到：`target-payload-host PASS first=0 checksum=30464 second=3`。它只把 `target/budget_probe.c` 当普通 C 模块运行：第一次检验 C 进程初值，第二次不复位重用会报错。这不能证明 Cortex-M 的 Reset_Handler 已复制/清零；那需要目标轨道。

**想做真正 GNU ELF 主机链接时**：在已有 Linux GNU ELF 环境中执行随课 `host/run-elf.sh`，给一个不存在的输出目录，例如 `bash lessons/L037-map-file-attribution/host/run-elf.sh /tmp/l037-elf-repeat`。脚本保存 A/B/C 的 ELF、Map、默认脚本、`readelf -h -S -l -W`、`objdump -h`、`nm -n -S` 和哈希。它同样不运行自定义入口映像。**本次没有可用的 GNU ELF 主机环境，该脚本未执行，不能把预期 `.bss.work` 当实测结果。**

### 8.2 STM32 参考实现轨道

#### 交付文件与直接使用边界

| 文件 | 层、依赖方向与生命周期 | 用法/状态 |
| --- | --- | --- |
| `target/budget_probe.h` | 应用接口声明；固定宽度返回值，不依赖 HAL | 加入生成工程的头文件搜索路径 |
| `target/budget_probe.c` | 应用实现；静态缓冲区/表/计数器由该模块持有；同步借用指针 | C11 逻辑已在主机测试；**目标未编译**，段归属仍要查目标产物 |
| `target/budget_clock.h/.c` | 参考系统初始化；应用→HAL RCC→器件寄存器 | API 对照 UM1725；**待真实 Cube 包编译** |
| `target/main_reference.c` | 应用入口组装与使用；应用→上述接口/HAL | 替代生成工程的一个 `main.c`，不能与其并存造成双重 `main` |
| 生成工程 startup/system/`.ld`/HAL/IRQ | 平台启动和链接配置；应用依赖平台，不反向包含应用 | 使用真实生成版本，不在教程仓库复制第三方完整源码 |

参考实现不使用动态分配、函数指针、RTOS，也不启动新外设。无需板级 GPIO 引脚。**仍然依赖实际目标供电、调试连接、启动模式、工具链和正确的生成工程**，这些待用户提供或执行时记录。

#### 生成、集成、构建：待执行，不是虚构结果

1. 按第 7.3 节在独立目标工程中生成 Makefile 工程，保存 `.ioc`、工具/包版本、实际器件和生成日志。核对 `.ld`、startup 与器件，不改 IDE/CubeMX 全局设置。
2. 将本课应用文件加入工程的真实源/头搜索列表。若工程使用 `Core/Src`、`Core/Inc`，可分别放在那里；若不是，按生成布局加入，**这些是条件示例而非本仓库已有目标路径**。以 `main_reference.c` 内容替代唯一应用入口；保留实际生成的 `stm32f4xx_it.c` 和 `stm32f4xx_hal_msp.c`。
3. 检查 Makefile：三个应用 `.c` 只编译一次；器件宏实际为 `STM32F407xx`，HAL 配置启用所需 HAL/RCC/Flash/Cortex 支持；startup 文件、`system_stm32f4xx.c`、HAL 库、C 运行库与工程一致。保留生成的 ABI/FPU/CPU 选项，不自行混入其他工程的 `.o`。
4. 保留唯一的 `-T`。核对现有 `-Map`，没有时在**链接选项**加入 `-Wl,-Map=$(BUILD_DIR)/$(TARGET).map`，已有时改其路径而非再加第二份；可加 `-Wl,--cref` 和经版本核对的 `--print-memory-usage`。`-ffunction-sections -fdata-sections` 是编译选项，`--gc-sections` 是链接选项。保留向量等必要 `KEEP`。[GNU-GCC-LINK；GNU-GCC-OPT；GNU-LD-247]
5. 本次归因基线使用 `-O0`、不启用 LTO（Link-Time Optimization，链接时优化），便于观察只读表/对象；这不是优化建议。更换优化/LTO 后建立**另一份构建身份**，不要强求每个源级对象仍有独立符号。
6. 用下方交互式命令定位真实工程并完整重建；没有可用工具就停止，写“待执行”，不编造输出。

```powershell
# 只在你准备好的真实目标工程中手动执行；本次未执行。
$project = (Resolve-Path -LiteralPath (Read-Host '输入含 Makefile 的目标工程绝对路径')).Path
$gcc = Get-Command arm-none-eabi-gcc -ErrorAction Stop
$make = Get-Command make -ErrorAction Stop
& $gcc.Source --version
& arm-none-eabi-ld --version
Push-Location -LiteralPath $project
try {
    # -B 重新构建，不靠删除目录排除陈旧对象；生成工程需有正确依赖。
    & $make.Source -B -j1 2>&1 | Tee-Object -FilePath l037-target-build.log
    if ($LASTEXITCODE -ne 0) { throw '目标构建失败，不进入预算结论' }
} finally { Pop-Location }
```

`make` 命令和输出路径必须以实际生成工程为准；本课不保证所有 CubeMX 版本都生成同一个 Makefile。工具不存在、包/头文件不匹配、重复定义、中断入口缺失、链接溢出均应停在失败证据，不能悄悄换脚本扩容来“通过”。

#### 用真实 ELF/Map 做独立取证

构建成功后，再交互选择**同一个构建目录**的产物，不硬编码一个从未存在的目标路径。输出到新的证据目录，避免覆盖旧证据：

```powershell
$elf = (Resolve-Path -LiteralPath (Read-Host '本次构建 ELF 绝对路径')).Path
$map = (Resolve-Path -LiteralPath (Read-Host '同次链接 Map 绝对路径')).Path
$ldscript = (Resolve-Path -LiteralPath (Read-Host '链接命令实际 -T 脚本绝对路径')).Path
$startup = (Resolve-Path -LiteralPath (Read-Host '本次实际 startup 文件绝对路径')).Path
$buildlog = (Resolve-Path -LiteralPath (Read-Host '本次完整构建日志绝对路径')).Path
$dest = Read-Host '输入一个尚不存在的证据目录绝对路径'
if (Test-Path -LiteralPath $dest) { throw '不要覆盖旧证据' }
New-Item -ItemType Directory -Path $dest -ErrorAction Stop | Out-Null
$jobs = @(
    @('arm-none-eabi-readelf', @('-h','-S','-l','-W',$elf), 'elf-structure.txt'),
    @('arm-none-eabi-objdump', @('-h',$elf), 'sections-vma-lma.txt'),
    @('arm-none-eabi-nm', @('-n','-S',$elf), 'symbols.txt'),
    @('arm-none-eabi-size', @('-A',$elf), 'section-sizes.txt')
)
foreach ($job in $jobs) {
    $tool = Get-Command $job[0] -ErrorAction Stop
    $toolArgs = $job[1]
    & $tool.Source @toolArgs 2>&1 | Set-Content -Encoding utf8 (Join-Path $dest $job[2])
    if ($LASTEXITCODE -ne 0) { throw ('取证工具失败：' + $job[0]) }
}
Get-FileHash -Algorithm SHA256 -LiteralPath $elf,$map,$ldscript,$startup,$buildlog |
    Select-Object Path,Hash | ConvertTo-Json |
    Set-Content -Encoding utf8 (Join-Path $dest 'artifact-hashes.json')
```

这段命令只生成报告/摘要，不烧录。产物哈希只是底线；还须补录工具版本、`.ioc`、构建选项/宏、链接响应文件、**实际参与链接的**所有 `.o/.a` 以及相关源/头依赖摘要。不要把构建目录里所有旧 `.o` 无差别算成参与者。完整链接命令应能与这些输入逐项对应。

接着手填以下目标审计表；**当前没有执行产物，所以不填虚构的地址/总量**：

| 必须找到的证据 | 当前状态 | 执行后的判定方法 |
| --- | --- | --- |
| 实际 `MEMORY` 的 Flash/主 RAM/其他区域 | 待目标工程生成 | 不越过第 7.2 节的物理边界；扣除项目保留区 |
| `work` 的输入节、输出节、地址、长度、对齐 | 待目标链接 | A 为声明 256 B；B 改为 512 B；输出长度和其他增量按产物取值 |
| `signature` 的只读内容和归属 | 待目标链接 | 本例源码 4×4=16 B，不把预期 `.rodata` 名称当链接证据；确认未被优化掉 |
| `boot_counter` 的 RAM 地址与初值装载位置 | 待目标链接/运行 | 源码对象为 4 B，段可能有填充；同时追 Flash 初值与 RAM 运行 |
| 所有其他装载/运行节 | 待目标链接 | 包括向量、异常表、HAL、运行库、对齐和孤儿节，不只统计 probe |
| 栈/堆最小预留与实际 MSP 上界 | 待目标链接/调试 | 读取脚本表达式/符号、向量首项；另做运行期栈证据 |
| 预算余量、启动后观察 | 待执行 | 预算按区域算，动态峰值仍不能由此推出 |

GNU `readelf` 的节头地址主要用于查看节的运行地址；LMA 不应只从这个字段猜。交叉使用程序头、节到段映射、`objdump -h`、Map 的 load address 与脚本 `AT/AT>`，按本次嵌入式链接器的具体输出核对。[GNU-BINUTILS-247；GNU-LD-247，Output Section LMA]

#### 调试/烧录/观察步骤：只提供，绝不代执行

1. 先记录真实板、订货料号、探针、供电、接线、复位/启动设置。核对供电和调试连接；没有这些信息不能宣称已验证。
2. 静态预算、器件范围、启动向量和目标构建通过后，**由用户明确确认**再在自己的目标工具中烧录该 ELF；记录工具版本、操作日志和映像哈希。本次没有执行烧录，也没有给出会自动烧录的命令。
3. 用真实复位运行，在 `BudgetProbe_Run` 入口和最终循环设断点。入口检查 `boot_counter=0x12345678`、`work` 全零；最终检查 `g_probe_phase=2`、`g_probe_error=0`、计数器加一。不要用调试器预先写入预期值。
4. 在 GDB 中加载真实 ELF 后，可用 `info address work`、`p/x &boot_counter`、`p/x boot_counter`、`p g_probe_phase`、`p/x g_probe_error`、`p g_probe_checksum`，以及 `info registers sp` 看对象/状态。若静态名字歧义，用实际编译单元限定名；不要用另一个构建的符号。
5. 用实际脚本存在的边界符号和向量读取结果核对 `.data` 源/目的、`.bss` 清零范围、初始 MSP；边界符号名称不同就按实际替换，不承诺 `_sidata/_sdata/_edata/_sbss/_ebss` 在所有模板都存在。
6. 读取 RCC 的 HSI/切换/分频状态、SysTick 时钟源/重装值。`g_hclk_nominal_hz` 只反映 HAL 软件计算。没有频率计/波形，不记录“测得 16 MHz”。
7. 保存每个观察点的运行方式、寄存器/变量值与固件哈希。入口值不对时，先查复位路径、错误镜像、startup/脚本配对、调试器加载行为；不要先怪 HAL 或给缓冲区再加一次软件清零来掩盖问题。

以上变量值是**待验证的预期**，不是本次读到的 STM32 值。只有目标板、构建、烧录、复位和观察证据齐全并经独立审核后，才有讨论提高硬件验证状态的基础；本次始终为 `false`。

## 9. 最小代码示例

### 9.1 先跑主机，再搬到目标

完整主机代码是 `host/attribution.c`、`host/budget_fake.c`、`host/probe_logic_test.c` 与 `host/run_host.py`，不是从第三方工程复制的驱动源码。`attribution.c` 仅做真实链接归因；`budget_fake.c` 用调用者持有的输入结构和 `uint64_t` 中间求和验证预算/边界；`probe_logic_test.c` 调用下方同一个 probe 模块。公开计数/错误接口用固定宽度整数，默认无动态内存。

预算模型不是 ELF 解析器：输入数字由测试给定。模型返回 0 只表示**按这些输入/上限**没有算术越界，不代表芯片内存已足够，也不代表实际链接满足该模型。

### 9.2 STM32 的完整应用源文件

以下五个文件与随课 `target/` 内容一致，按第 8.2 节加入真实生成工程；它们不是独立可烧录固件，仍需真实 HAL/CMSIS、启动、链接脚本和异常入口。**参考实现，待目标工程编译；未烧录、未测量。**

对象归属先看清：`work`、`signature`、`boot_counter` 在 probe 模块中定义并拥有静态存储期；`BudgetProbe_Run` 将地址与长度同步交给私有 `fill_and_fold`。后者只在调用期间借用，不保存指针，不接入 IRQ/DMA。初始化参数结构在 clock 函数中是自动存储期，只在 HAL 调用中有效。应用 `main` 负责组装/调用，不持有外设句柄。

**target/budget_probe.h**

```c
#ifndef BUDGET_PROBE_H
#define BUDGET_PROBE_H
#include <stdint.h>
#ifndef PROBE_WORK_BYTES
#define PROBE_WORK_BYTES 256U
#endif
/* Application owns all storage. Returns bit 0 for .data, bit 1 for .bss. */
uint32_t BudgetProbe_Run(void);
#endif

```

**target/budget_probe.c**

```c
#include "budget_probe.h"

_Static_assert(PROBE_WORK_BYTES > 0U, "work must not be empty");
_Static_assert(PROBE_WORK_BYTES <= UINT32_MAX, "public length is uint32_t");

static volatile uint8_t work[PROBE_WORK_BYTES];
static const uint32_t signature[4] = {
    UINT32_C(0x4d415021), UINT32_C(0x11223344),
    UINT32_C(0x55667788), UINT32_C(0x90abcdef)
};
static volatile uint32_t boot_counter = UINT32_C(0x12345678);

/* Debugger observation only. No IRQ or DMA accesses these objects. */
volatile uint32_t g_probe_phase;
volatile uint32_t g_probe_error;
volatile uint32_t g_probe_initial_counter;
volatile uint32_t g_probe_checksum;

static uint32_t fill_and_fold(volatile uint8_t *buffer, uint32_t count,
                              const uint32_t *table, uint32_t table_words)
{
    uint32_t i;
    uint32_t sum = 0U;
    for (i = 0U; i < count; ++i) {
        buffer[i] = (uint8_t)(table[i % table_words] & UINT32_C(0xff));
        sum += buffer[i];
    }
    return sum;
}

uint32_t BudgetProbe_Run(void)
{
    uint32_t i;
    uint32_t errors = 0U;
    g_probe_phase = 1U;
    g_probe_initial_counter = boot_counter;
    if (boot_counter != UINT32_C(0x12345678)) { errors |= 1U; }
    for (i = 0U; i < (uint32_t)PROBE_WORK_BYTES; ++i) {
        if (work[i] != 0U) { errors |= 2U; }
    }
    /* Borrowed pointers/lengths are valid only for this synchronous call. */
    g_probe_checksum = fill_and_fold(work, (uint32_t)PROBE_WORK_BYTES,
                                     signature, 4U);
    boot_counter += 1U;
    g_probe_error = errors;
    g_probe_phase = 2U;
    return errors;
}

```

**target/budget_clock.h**

```c
#ifndef BUDGET_CLOCK_H
#define BUDGET_CLOCK_H
#include <stdint.h>
/* Reset-state reference path: 0=OK, 1=oscillator error, 2=bus/Flash error. */
uint32_t BudgetClock_HSI(void);
#endif

```

**target/budget_clock.c**

```c
#include "stm32f4xx_hal.h"
#include "budget_clock.h"

uint32_t BudgetClock_HSI(void)
{
    RCC_OscInitTypeDef osc = {0};
    RCC_ClkInitTypeDef clocks = {0};
    osc.OscillatorType = RCC_OSCILLATORTYPE_HSI;
    osc.HSIState = RCC_HSI_ON;
    osc.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
    osc.PLL.PLLState = RCC_PLL_OFF;
    if (HAL_RCC_OscConfig(&osc) != HAL_OK) { return 1U; }

    clocks.ClockType = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK |
                       RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    clocks.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
    clocks.AHBCLKDivider = RCC_SYSCLK_DIV1;
    clocks.APB1CLKDivider = RCC_HCLK_DIV1;
    clocks.APB2CLKDivider = RCC_HCLK_DIV1;
    if (HAL_RCC_ClockConfig(&clocks, FLASH_LATENCY_0) != HAL_OK) { return 2U; }
    return 0U;
}

```

**target/main_reference.c**

```c
/* Reference integration main: use instead of, never alongside, Cube-generated main.c.
 * Requires a real CubeF4 project, selected startup/linker files and HAL configuration.
 * Not target-compiled, not flashed, not measured in this run.
 */
#include "stm32f4xx_hal.h"
#include "budget_clock.h"
#include "budget_probe.h"

volatile uint32_t g_boot_error;
volatile uint32_t g_clock_error;
volatile uint32_t g_hclk_nominal_hz;

void Error_Handler(void)
{
    __disable_irq();
    for (;;) { __NOP(); }
}

int main(void)
{
    if (HAL_Init() != HAL_OK) {
        g_boot_error = 1U;
        Error_Handler();
    }
    g_clock_error = BudgetClock_HSI();
    if (g_clock_error != 0U) {
        g_boot_error = 2U;
        Error_Handler();
    }
    g_hclk_nominal_hz = HAL_RCC_GetHCLKFreq();
    if (BudgetProbe_Run() != 0U) {
        g_boot_error = 3U;
        Error_Handler();
    }
    for (;;) { /* Break here after a genuine reset; do not call the probe twice. */
        __NOP();
    }
}

```

默认 `PROBE_WORK_BYTES=256U`。`boot_counter` 不是跨复位累计的启动次数：正常 `.data` 初始化每次都会还原种子，它只用于本次启动的初值/调用检查。`g_probe_phase` 的 1/2 表示检查开始/结束；`g_probe_error` 的位 0 是计数器初值不符，位 1 是缓冲区起始内容非零；`g_boot_error` 的 1/2/3 区分 HAL 初始化、时钟配置、probe 检查失败；`g_clock_error` 的 1/2 区分振荡器/总线配置失败。这些是应用错误码，不伪装成硬件状态寄存器。

仅在默认长度、一次干净启动及预期表内容下，四个低字节之和为 `0x21+0x44+0x88+0xef=476`，循环 64 组，所以预期 `g_probe_checksum=30464`。这是源码可推导值，不是目标测量值。重复调用没有复位，计数器已变、缓冲区已填充，故两项初值检查都应失败；主机测试实际检查了这个错误路径。

所有 `volatile` 仅用于保留可观察读写，不代表原子性、线程安全或跨 DMA 一致性。本课没有并发共享使用，因此不为它添加并发机制。

**IRQ/回调的最小配套**：保留生成工程自己的 `SysTick_Handler`，并核对它实际执行 `HAL_IncTick()`。如果生成工程没有等价实现，所需核心是下列函数；只能保留一份定义，不把代码再追加到已有同名入口：

```c
#include "stm32f4xx_hal.h"
void SysTick_Handler(void)
{
    HAL_IncTick();
}
```

默认 HAL 时基不需要本课自定义外设回调。没有 IRQ 完成后“通知 Map”的动作，没有 DMA handle、DMA 完成/半完成/错误回调。若工程覆写 HAL 时基，应按实际源重查而不是再强装一套 SysTick。时基不前进会使依赖 tick 的 HAL 轮询超时失效或卡住；先修复真实异常向量/时基，不去修改超时常量。[ST-UM1725，§6.1、§54；ST-PM0214，SysTick]

### 9.3 布局与运行不一致时的错误路径

- 工具或包缺失：停止目标构建，状态仍为参考实现；不拿主机 GCC 冒充交叉 GCC。
- 链接区域溢出：保存错误和 Map（若有），追具体输出/输入节；不偷偷把 `RAM LENGTH` 调大。
- HAL 时钟失败：`g_boot_error=2` 后进入 `Error_Handler`，中断关闭；此状态下不再期待 tick 继续增长。
- probe 初值失败：保留 `g_probe_initial_counter` 和错误位，优先检查启动流程/重复调用/镜像身份。计数器初值不对并不能单独断言 Flash 已坏。
- 主机或目标检查通过：也只能限定为那次检查涵盖的状态，不自动获得“整个固件内存安全”的结论。

## 10. 常见错误

| 错误结论/动作 | 为什么不成立 | 应怎样修正 |
| --- | --- | --- |
| “ELF 文件 200 KB，所以占 Flash 200 KB” | 含文件头、调试信息、非装载节，布局/洞另有语义 | 按实际装载区间和打包规则核算 |
| “`.data` 只占 RAM” | 常见 Flash 启动还需 Flash 初值 | 同时查 VMA、LMA 与启动复制 |
| “`.bss` 没有初值文件字节，所以不占内存” | 零初始化对象仍需运行空间 | 计入 RAM；复位清零另取证 |
| “所有 C 零初始化数组都必须叫 `.bss`” | 本次 PE 就观察到 `.data$work` | 看实际工具/格式，不跨平台猜名字 |
| “Map 出现某函数，它就被保留了” | 可能在丢弃列表，符号也可能只是 `U` | 查布局区、已定义符号及回收日志 |
| “关 GC 只多出那个函数的字节” | 同时可能保留其他输入节和填充 | 分输出节、输入对象重新差分 |
| “Map A 与 ELF B 路径像一对，可以合用” | 路径/修改时间不能证明同构建 | 清单哈希加完整命令，错配则拒绝 |
| “192 KB SRAM 从 0x20000000 连着用” | F407 主 SRAM 与 CCM 不连续且访问方不同 | 分区域预算，核对 RM、DS 和 `.ld` |
| “NOLOAD 就能跨复位保留” | 链接属性不替你设计初始化/供电策略 | 查实际 ELF/启动范围/复位与存储器属性 |
| “`ld --verbose` 就是目标实际脚本” | 带 `-T` 的目标构建用的是指定脚本 | 保存链接命令实际选中的脚本及包含文件 |
| “栈预留 2 KB，实测峰值就是 2 KB” | 静态分配不是运行观测 | 结合 SP/调用路径/异常现场等 L036 证据 |
| “软件频率 16 MHz，说明已测得” | HAL 按寄存器和常量计算，不是频率计 | 分开配置证据、软件计算与物理测量 |

链接/格式语义据 [GNU-LD-247；GNU-BINUTILS-247]；F407 容量与时钟边界据 [ST-RM0090；ST-DS8626；ST-UM1725]。

## 11. 调试观察点

**离线链接观察：**

1. 实际输入/命令中的优化、宏、LTO、节回收、库顺序和 `-T`；同名库也要核对版本和路径。
2. Map 的库成员抽取说明、被丢弃输入节和正常布局区分别看，不跨区按名字求和。
3. 同一对象的“源码有效长度—输入节大小—输出节贡献—对齐填充”；符号尺寸和输出节尺寸不同不一定是错误。
4. ELF 节类型/ALLOC 属性/程序头、Map 的装载地址、脚本规则；`objdump -h` 的 VMA/LMA 配对。
5. 预算表里还有没有未解释的 ALLOC 节、新输出节、尾部对齐、项目保留区和库依赖。
6. 最小堆栈检查的几何位置、真实初始 MSP、静态数据最高地址；不把脚本数字直接解释成峰值。

**将来目标运行观察（本次待执行）：**

- 复位入口、向量 MSP、VTOR 和真正达到 `main` 的路径。调试器可能复位、只暂停、写入内存或重设 PC，操作模式要记录。
- probe 前的初值和 probe 后的状态/校验；不重复调用后再声称测了“上电初值”。
- RCC 的 HSIRDY/SWS/HPRE/PPRE、Flash 延迟及默认 SysTick 入口；本课无其他外设时钟/中断观测。
- 若观察到异常，先确认调试符号和目标固件同一构建，再按 L035/L036 读取异常/栈证据；不要用 Map 给异常原因下唯一结论。

上述硬件寄存器的定义范围见 [ST-RM0090，§3、§7；ST-PM0214]。后续运行结果应另存证据，不覆盖本课“未执行”历史。

## 12. 实战实验

### 实验 A：拿出一条完整归因链

运行主机脚本，打开 A/B Map，填写：源宏值、目标文件 SHA-256、输入节、输出节、地址、长度、填充、输出长度增量。必须写出：`320-64=256`、`0x140-0x40=0x100`、`.data` 的 `0x160-0x60=0x100`，并解释这不是 F407 RAM 预算。

验收：另一人只根据记录就能定位同一个输入贡献；不能只交两行 `size` 总数。

### 实验 B：故意给出一个错误归因

先只搜索 A 的 `unused_marker`，提出“它存在”的假结论；再查看丢弃列表、`T/t` 与 `U`、C 的符号及回收日志推翻它。解释 C 的 `.rdata` 也变大，所以文件差异不能全部归该函数。

验收：写出原结论、反证位置、修正后的有限结论，而非删除不合预期的证据。

### 实验 C：预算模型的边界

保持默认人工输入，复核 1104/784；检查 grow-bss 只超 RAM、grow-data 只超本例 Flash 阈值。读 `budget_fake.c`，指出刚好满、超一字节、宽位累加这三项断言。

验收：回答“若我把 `.data` 初值从 Flash 算式删掉，会漏掉哪一条判断？”并指出模型不解析真实链接产物，因此 PASS 不能替代目标审计。

### 实验 D：拒绝错配证据

读 `run_host.py` 的 `verify_files`：先验证 A，再把 B 映像替入 A 的候选文件集合。说明为什么被拒绝，以及清单最初若由人混造，只有摘要还不能证明来源诚实。

验收：证据至少有命令、源/对象/脚本/产物摘要；不要只写“时间相近”。

### 实验 E：F407 的独立目标审计——待环境具备后执行

按第 8.2 节构建 A（256 B）和 B（512 B），分别保存独立证据目录。只修改 `PROBE_WORK_BYTES` 的编译定义，其他目标输入保持相同；确保两个构建的所有编译单元看到一致宏值。

逐项报告 `work`、输出节、所有 RAM 区域与 Flash 装载成本的变化；如果不是整齐增加 256 B，查对齐、优化和其他贡献，而非“修”报告。再由用户确认后进行板上复位观察，比较链接地址与实际初值。

验收分三栏：目标静态链接结论、该次运行观察、尚未覆盖的最坏栈/堆/外设行为。**本次只交参考方案，不填执行结果，不提高 mastery。**

## 13. 自检题

1. 给出本课核心目标与两个新核心概念。为什么 VMA、LMA 只是辅助词而不是两个新课程目标？
2. 对一个带初值的 RAM 数组，列出从源定义到实际读到初值至少需要的证据；在哪一步需要启动文件？
3. 为什么计数器 C 对象为 4 B，本次输入节贡献却是 `0x10`？如何避免把填充重复算进输出节？
4. A 的 Map 与 `nm` 都出现未引用函数名，为什么仍不能说它占了 `.text`？
5. 你能否仅凭 Map 证明 `.bss` 已清零、DMA 能访问 `work`、最坏中断嵌套不溢栈？各自还缺什么？
6. F407VG 的 128 KiB 主 SRAM 与 64 KiB CCM 为什么不能直接拼成连续 192 KiB 的默认 RAM？
7. 目标 ELF 增大 20 KiB，但 Flash 装载内容不变，是否矛盾？先查哪些节/文件结构？
8. HSI 的软件计算值等于 16 MHz，能否把它写成实测频率？

简短核对方向：1 追来源/限结论；2 同构建脚本、ELF/Map、复制边界与运行观察；3 输入节布局成本和输出节总长分层；4 丢弃区/未定义标记；5 静态布局不能代运行与总线证据；6 区间/访问方不同；7 非装载信息及对齐/打包；8 不能。详细回答应由你给出，本课生成不代答学习记录。

## 14. 面试题

**问：固件 RAM 突然多了 8 KiB，你从哪开始？**

先确认两份构建身份和比较指标一致；按区域/输出节差分，再定位输入对象/库成员/输入节，复核 `.data`、`.bss`、对齐、预留与链接选项。最后写直接贡献和剩余不确定性，不先猜“某个驱动太大”。

**问：`text + data` 能当 Flash，`data + bss` 能当 RAM 吗？**

在明确的简单约定下可作快速估算，不能当通用预算算法。向量/异常表/初始化表、多个区、保留空间、对齐/镜像洞、特殊装载规则和堆栈策略都需核对。[GNU-LD-247；GNU-BINUTILS-247]

**问：Map 上栈空间还有 4 KiB，为什么仍可能 Fault？**

先问这 4 KiB 是脚本最小检查、静态未分配区还是实际栈区间；Map 不知道该次调用深度与异常嵌套，也不能排除越界指针、错误 MSP、坏启动或其他 Fault 原因。要用对应运行期证据限定结论。[ST-PM0214；ST-RM0090]

**问：把缓冲区搬到“更空”的 RAM 就能解决 ADC DMA 问题吗？**

不一定。链接仅证明放置安排；F407 的 CCM 访问方与主 SRAM 不同，其他系列还需重查域、总线和缓存。必须证明目标 DMA 能访问、所有权/边界正确且数据可见，不能从静态余量直接推出。[ST-RM0090，§2.3；ST-PM0253；ST-RM0433，§2]

## 15. 延伸思考

- 预算门槛该按有效内容、链接器区域使用量、镜像跨度，还是三者分别设？为什么“同一个数字”可能服务不了发布打包和运行 RAM 两种约束？
- 若项目明确禁止堆，怎么验证“源码没调用 malloc”和“最终构建没有意外库依赖/堆预留”不是同一句话？先做哪种离线链接实验最省证据成本？
- 若换优化或 LTO 后某个常量符号消失，怎样以输出节和反汇编/重定位继续核对，而不是要求编译器保留所有源码对象？
- 为测试保留入口而关闭所有 GC，为什么只能成为诊断对照，不能自动作为正式修复？
- 双镜像升级中，两个 ELF 的 Flash 用量之和何时会漏算元数据和对齐，何时又会把共享物理区域算重？把问题留给 `memory-map` 的明确镜像协议，不在本课猜布局。

## 16. 本节总结

1. 先绑定构建，再从 Map 追输入对象/节到输出节、地址、长度和填充；用实际 ELF/工具报告交叉验证，不从名字直接认定保留或归属。
2. Flash 看初始化/装载，RAM 看运行/预留；多区域、对齐、初值与保留策略各自记账，不能用一个文件大小或 `size` 总数包办。
3. 静态链接证明布局，不证明启动完成、动态栈/堆峰值或 DMA 可达性。主机、目标静态链接和板上运行是分开的证据层。
4. 本次真实完成的是 GNU Windows PE 链接与主机算术/模块逻辑验证；目标代码完整提供但未目标编译、未烧录、未测量，`hardware_verified=false`。

## 17. 下一步

按课程顺序，下一主题是 `debugging-verification/logic-analyzer`（逻辑分析仪）；它补充时序/信号证据，而不是推翻本课的链接证据。后续 `host-test`、`unit-test` 再把同构建身份、保留入口和预算阈值变成自动检查；`dma-coherency`、`bus-matrix`、`memory-map` 分别补数据一致性、访问路径和镜像布局。

先交实验 A–D 的答案和记录，具备真实目标环境后再做 E。课程生成本身不提高掌握度；仅在 Reviewer 通过后按课程顺序推进已授进度，不把内容发布或读过算作掌握。

## 18. 参考资料

访问/本地核对日期均为 **2026-10-20**。以下 ID 与 `lesson.json.sources` 一致。GNU 资料虽是项目官方手册，但按本仓库 `primary_domains` 策略记 `primary=false`；ST 项记 `primary=true`。这不是对 GNU 手册权威性的否定。

- **[GNU-LD-247] GNU linker 2.47 手册**：本次实际读取已安装工具链 `share/info/ld.info.gz`，手册自述 2.47；工具二进制为 `2.47.20260726`，不声称精确源码构建相同。定位：Options（`-M/-Map`、`--gc-sections`、`--print-gc-sections`、`--orphan-handling`、库抽取）、Basic Script Concepts、Input Section Keep、Output Section Type、Output Section LMA、MEMORY、Orphan Sections、Location Counter。官方版本归档定位：<https://ftp.gnu.org/gnu/binutils/binutils-2.47.tar.xz> 中 `ld/ld.texi`；归档网络下载过慢已中止，**语义核对来自本机官方随包手册**，未将完整归档或第三方源码复制到课程。
- **[GNU-BINUTILS-247] GNU Binary Utilities 2.47 随包手册**：实际读取 `share/info/binutils.info.gz`；定位 nm 符号类型、objdump `-h/-f`、readelf `-h/-S/-l/-W`、size。官方归档定位同上，文档为 `binutils/binutils.texi`；不声称主机存在 Arm ELF。[GNU 官方归档](https://ftp.gnu.org/gnu/binutils/binutils-2.47.tar.xz)
- **[GNU-GCC-LINK] GCC 16.2.0：Link Options**：核对 `-Wl,` 的选项转发；本机版本匹配，目标交叉版本待选择。<https://gcc.gnu.org/onlinedocs/gcc-16.2.0/gcc/Link-Options.html>
- **[GNU-GCC-OPT] GCC 16.2.0：Optimize Options**：定位 `-ffunction-sections`、`-fdata-sections`、`-flto`；节回收效果还需链接器支持和实际结果。<https://gcc.gnu.org/onlinedocs/gcc-16.2.0/gcc/Optimize-Options.html>
- **[ST-RM0090] RM0090 Rev 22，2026-05**：§2（内存/启动配置）、§3（F405/407 Flash）、**§7（F405/407 RCC）**；重点 §7.2.2、§7.3.1、§7.3.3、§7.3.21，勿混入 §6 的其他子系列范围。<https://www.st.com.cn/resource/en/reference_manual/dm00031020-stm32f405415-stm32f407417-stm32f427437-and-stm32f429439-advanced-armbased-32bit-mcus-stmicroelectronics.pdf>
- **[ST-DS8626] DS8626 Rev 12，2026-03**：STM32F405xx/407xx 数据手册；器件特性/存储器框图、供电与电气限制、§8 订货编码（p.186）；不是任意 F407 板卡的原理图。<https://www.st.com.cn/resource/en/datasheet/stm32f407vg.pdf>
- **[ST-UM1725] UM1725 Rev 8，2023-03**：§6.1（HAL_Init/HAL_InitTick，p.45–47）、§54.1（RCC 结构，p.779–780）、§54.2.5（RCC 初始化函数，p.781–783）。只证明文档中 API 约定，不证明 CubeF4 1.28.3 本地包已编译。<https://www.st.com.cn/resource/en/user_manual/dm00105879-description-of-stm32f4-hal-and-ll-drivers-stmicroelectronics.pdf>
- **[ST-PM0214] PM0214 Rev 10，2020-03**：Cortex-M4 处理器模型、栈/复位/向量和 SysTick/SCB；不代替器件容量或板级启动接线证据。<https://www.st.com/resource/en/programming_manual/dm00046982-stm32-cortexm4-mcus-and-mpus-programming-manual-stmicroelectronics.pdf>
- **[ST-CUBEF4] STM32CubeF4 官方软件版本页**：访问日页面列出 STM32CubeF4 1.28.0 与 Patch-CubeF4 1.28.3；未下载固件包或验证补丁组合。本课只定参考版本边界，生成时要记录真实包/组件版本。<https://www.st.com/en/embedded-software/stm32cubef4.sw-versions.html>
- **[ST-PM0253] PM0253 Rev 6，2026-05**：F7/H7 Cortex-M7 处理器手册，内存属性与缓存维护（§4.8），不作具体器件 TCM/SRAM 容量证据。<https://www.st.com.cn/resource/en/programming_manual/dm00237416-stm32f7-series-and-stm32h7-series-cortexm7-processor-programming-manual-stmicroelectronics.pdf>
- **[ST-PM0264] PM0264 Rev 8，2026-03**：Cortex-M33，适用产品表含 H5；§1.3.2 安全扩展、§2.3.4 安全内存划分。具体 H5 器件地址与选项仍待相应 RM/DS。<https://www.st.com.cn/resource/en/programming_manual/pm0264-stm32-cortexm33-mcus-programming-manual-stmicroelectronics.pdf>
- **[ST-RM0433] RM0433 Rev 9，2026-10**：H742/H743/H753/H750 对应子线；§2.3.2 内存映射、§2.4 Embedded SRAM（嵌入式 SRAM），用于说明迁移需重查多个区域，不外推全部 H7/双核产品。<https://www.st.com.cn/resource/en/reference_manual/dm00314099-stm32h742-stm32h743-753-and-stm32h750-value-line-advanced-armbased-32bit-mcus-stmicroelectronics.pdf>
