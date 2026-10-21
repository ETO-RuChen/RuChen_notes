+++
title = "单元测试——隔离用例与可诊断回归"
date = "2026-10-21T17:44:39+08:00"
lastmod = "2026-10-21T17:44:39+08:00"
summary = "能够把已学批次交接逻辑拆成彼此隔离、失败可定位的 C11 单元测试，用边界与错误用例建立可重复回归，并将测试证据与 STM32F407xx 时钟、外设、HAL 回调及实机证据严格区分。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 40
tags = ["单元测试", "用例隔离", "边界值", "可诊断回归", "STM32F407xx", "证据边界"]
source_ids = ["ST-RM0090", "ST-DS8626", "ST-UM1725", "ST-STM32CUBEF4", "ST-UM1718", "ST-STM32CUBEMX", "CMAKE-ADD-TEST", "CMAKE-CTEST", "ST-RM0410", "ST-DS11532", "ST-STM32CUBEF7", "ST-RM0481", "ST-DS14258", "ST-STM32CUBEH5", "ST-RM0433", "ST-DS12110", "ST-STM32CUBEH7"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L040"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# L040 单元测试——隔离用例与可诊断回归

> 阶段：`debugging-verification`（调试与验证）｜主题：`unit-test`｜建议学习时间：60 分钟，目标硬件实验另计。
> 本课是一篇课程、一个课程 ID，不因章节较长拆分选题。配套元数据为同目录 `lesson.json`。
> **证据边界：本次实际完成的是主机 C11 构建与用例运行；STM32 参考实现未进行本次目标工程编译、未烧录、未测量，`hardware_verified=false`。** 课程审查状态以同目录 `lesson.json` 及本次运行的 `review-result.json` 为准。Teacher（授课者）阶段仅生成草稿；Reviewer（审查者）仅在实际通过后更新课程与路线进度，生成或审查通过都不代表学习者已掌握。

## 1. 本节目标

**唯一核心目标，与本次 `plan.json` 一致：**能够把已学批次交接逻辑拆成彼此隔离、失败可定位的 C11 单元测试，用边界与错误用例建立可重复回归，并将测试证据与 STM32F407xx 时钟、外设、HAL 回调及实机证据严格区分。

这里C11指2011年版C语言标准，本例采用其子集；HAL（Hardware Abstraction Layer）指硬件抽象层，回调是由驱动在事件发生时调用的应用函数。

只推进两个新核心概念：

1. **单元边界与用例隔离**：谁是被测代码，谁创建状态，谁提供输入；每条用例从自己的新状态开始，不接着上一条的结尾运行。
2. **边界用例到可诊断回归**：把一份独立契约变成有名称、能失败、失败后能指出位置的用例，修改后重复执行同一组约定。

完成时应能展示：一条最小用例；33 条命名用例的注册与实际执行清单；截止边界、顺序、重复、错误与恢复断言；正常日志、三个故意错误的红灯日志及修复后的绿灯日志。这里“红灯”指程序因约定被违反而返回非零，“绿灯”指本次选中的断言通过，不是硬件安全认证。

不在本课展开新测试框架、覆盖率平台、RTOS（实时操作系统）或架构阶段的独立机制。函数指针和自动依赖组装都不是完成本课的必要条件。

## 2. 它解决什么问题

L039 已经证明：可以在主机给批次交接程序输入受控事件，并与独立预期比较。新的问题不是“还需要一种主机模拟器”，而是：

- 大场景的第 17 步失败，怎样判断是发送未归还，还是第 9 步留下了错误状态？
- 只看到 CTest（CMake构建系统配套的测试执行工具）显示 `1/1`，究竟跑了哪个截止边界？是否一条都没有跑也返回成功？
- 把“达到截止就故障”错改成“超过截止才故障”，旧测试能否准确变红？
- 一条恢复测试先把全局状态清干净，是否掩盖了“清理失败也重新启源”的错误？

**最小闭环先跑起来。** CMake负责生成构建描述，Ninja是本例实际执行编译/链接命令的构建工具。在仓库根目录执行：

```powershell
cmake -S lessons/L040-unit-test -B lessons/L040-unit-test/build/first -G Ninja
cmake --build lessons/L040-unit-test/build/first --target minimal_batch
.\lessons\L040-unit-test\build\first\minimal_batch.exe
# 任一构建/运行命令非零应立即停下检查，不继续宣称成功。
```

这些是复现命令，`build/first` 是执行后生成的构建目录，不是假称已经存在的产物。本次实际运行的独立构建目录记录在 `evidence/host-results.json`，日志见第 8 节。

最小入口在 [`host/minimal.c`](host/minimal.c)，完整代码见第 9 节。它只做：

```text
本条用例拥有全新的 Batch 和 BatchAction
  → 初始化 64 个逻辑毫秒的窗口
  → 启动并明确输入“外部 arm 成功”
  → 输入第一次 HT（半传输完成）事件
  → 检查发出 ACT_TX、借出半区0、半区1转为采集
  → 成功返回0；不符合任一约定则打印位置并返回1
```

可观察输出为 `PASS case=minimal_ht`。这个输出只能证明列出的软件断言。没有 ADC（模数转换器）采样，没有串口线波形，也没有真正的 DMA（直接存储器访问）完成中断。

随后扩展为“33 条用例分别注册，仍复用同一生产核心”。这才是本课相对 L039 的增量，而不是把原场景换个标题再跑一次。

## 3. 必要前置知识

本课把 `completed` 中的以下内容当作**已授课而非已掌握**：固定宽度整数、指针与对象存储期、C11 编译/CMake、时钟树、定时器/ADC/DMA/UART（通用异步收发器）、HAL（硬件抽象层）与 LL（底层驱动）、批次链和 L039 主机测试。

先不看代码，复述下面四条；若不能复述，先复习 L031/L032 的批次链及 L039，不在本课偷偷补一整套新机制：

1. 128 个 `uint16_t` 样本分为两个半区，每半区 64 个样本、128 字节。
2. 只有采集完成的半区才能借给发送方；软件记录借出后，匹配的完成通知才归还。
3. 发送未完成、顺序不符或达到截止时，先进入故障并请求停采集源，不能假装正常丢一包继续。
4. 清理失败不能清样本、换会话或重新启源；清理成功后仍经过显式恢复请求和重新 arm（装好接收链、准备接收触发）过程。

L039 的“独立预言”继续使用：先从约定写出输入与期望，再读实现定位错误；不能把实现的 `if` 分支照搬到测试中计算期望。本文的硬件结论另受第 18 节第一方资料约束，主机测试不能给手册补证据。

## 4. 核心原理

### 4.1 概念一：单元边界与用例隔离

**被测单元**不等于“整个固件”，也不必等于“只有一行函数”。本课把 `batch_event` 及配套启动/清理状态转换作为单元，边界如下：

```text
输入：调用者持有的 Batch + 明确的 BatchEvent / 外部结果
输出：同一个 Batch 的约定状态 + BatchAction 动作描述
边界外：真正停止 TIM、启动 UART DMA、执行 abort、读取真实时间
```

核心声明位于 [`../L039-host-test/core/batch.h`](../L039-host-test/core/batch.h)，实现位于 [`../L039-host-test/core/batch.c`](../L039-host-test/core/batch.c)。新课程的 CMake **直接编译该真实源文件**；没有在 Fake（替身）里重新实现一份交接判断，也没有修改旧课。

为什么还需要启动与清理函数？因为 `batch_event` 只有在运行态才处理输入。测试必须通过正常 API（应用程序接口）建立初态；不能直接写 `mode=RUNNING`、`tx_active=1` 来绕过重要前提。本文只为模拟采集数据填入样本数组，不伪造状态转换。窗口无效测试单独从 `batch_init` 开始，不经过运行态夹具。

**用例隔离的具体做法：**

- 每次 `run_case` 都在自动存储期创建 `Fixture storage = {0}`，其中有本条用例自己的 `Batch`、`BatchAction`、动作记录和断言计数。
- `running()` 通过 `batch_init → batch_start → batch_arm_result` 建立运行态，检查启动前提；必要时 `loan()` 再通过真实 HT 事件建立“一半正在发送”的初态。
- 用例结束后不把这个对象交给下一条。唯一全局测试表是只读的 `static const` 数组，不保存运行结果。
- 输入的会话号、半区和 token（用于匹配本次借出的软件编号）来自预先写好的用例，而不是读取被测输出再把它喂回去当“正确答案”。

对象在哪里、谁持有、谁提供输入与如何调用：

| 对象 | 定义与实例位置 | 持有者、寿命 | 谁提供输入 / 谁消费输出 |
|---|---|---|---|
| `Batch` 类型 / `batch_event` 声明 | 旧课 `core/batch.h` | 头文件只声明，不创建全局对象 | 主机入口和板端适配均依赖此声明 |
| 每条用例的 `Batch` | 新课 `run_case` 内的 `Fixture` | 本条用例持有，函数返回后结束 | 用例输入事件；真实核心更新状态 |
| `BatchEvent` | `input()` 内局部常量 | 这一次调用 | 测试提供 kind/now/session/half/token |
| `BatchAction last` | 本条 `Fixture` | 本条用例 | 核心输出；断言和动作记录器读取 |
| `FakeActions` | 本条 `Fixture` | 本条用例 | 只记录非空动作，不执行硬件、不决定结果 |
| 板端 `g_batch` 与 HAL 句柄 | 旧课 `target/reference_f407.c` | 静态存储期，固件运行期间有效 | HAL 回调形成事件；板端适配执行动作 |

这里的夹具不是新生产框架，它只是减少测试准备重复的普通 C 函数。自动化不应把输入藏起来：例如 arm 成功必须由用例明确调用 `batch_arm_result(..., 0u, ...)`，记录器不能“见到 ARM 就悄悄成功”。

### 4.2 概念二：边界用例到可诊断回归

先固定独立契约，再选代表输入。本课沿用的关键约定如下：

| 契约 | 前提 / 唯一主要刺激 | 预期与安全不变量 |
|---|---|---|
| 发布第一半区 | 新会话运行态，输入 `HT, half=0` | `ACT_TX, half=0, token=1`；半区0为 TX、半区1为 CAPTURE |
| 正常归还 | 已借出半区0，截止前输入匹配的 TX_DONE | 不发新动作；半区0为 FREE、tx_active=0；不清已有样本 |
| 未完成不能发布 | 首次输入 TC，或 HT 携带错误半区 | 顺序故障并请求 STOP；不产生 TX |
| 发送忙 | HT 后未完成，在截止前输入 TC | 忙故障；保留原借出，不发第二次 TX |
| 完成匹配 | 未借出、重复完成、错误半区或 token | 完成通知故障，不错误释放另一个半区 |
| 截止 | 有借出，`now-start >= window` | 即使这次事件是 TX_DONE 也截止故障；保持借出直到清理 |
| 会话 | 运行态收到旧会话事件 | 旧会话故障，不把它认作新批次 |
| 清理 | 外部清理反馈失败 / 成功 | 失败留在故障且样本不清；成功新会话并发 ARM，首错保留 |

**截止边界先写成数，不从实现分支算出来：**窗口 64，借出时刻 100；时刻 163 未到截止，164 恰好截止，165 已越过。表中三个预期由这句中文契约决定；不是先运行代码看看返回什么再抄进表里。

时刻跨越 `uint32_t` 的一次回绕时，借出时刻 `0xffffffe0`，时刻 31、32、33 对应间隔 63、64、65。这是另一组固定边界输入。测试验证的是这些具体间隔，不是“任意次数回绕都安全”。调用方仍须足够频繁地检查，不能隔一个完整的 32 位计时周期才检查一次。窗口参数要求 `0 < window < 0x80000000`；拒绝 0 和半范围边界，允许 `0x7fffffff` 是本核心的参数契约，不是实际硬件实验的等待时间。

**一条用例只有一个主要刺激，不是只能调用一次函数。** 例如 `done_wrong_token` 的准备阶段先启动、HT 借出；真正要判断的是“错误 token 的完成通知”，准备每一步也要验证，否则后续故障可能只是准备失败。

诊断输出必须至少含：用例名、步骤、字段、实际值、期望值和源码位置。程序非零退出后，CTest 默认把它判为失败；`--output-on-failure` 展示失败程序输出。`--show-only=json-v1` 只枚举测试，不执行；`--no-tests=error` 防止错误过滤条件选中零条还被当作成功。[S7][S8]

本课不设置 `WILL_FAIL` 把故意错误涂成绿灯，也不以覆盖率百分比替代“某条约定确实能失败”的证据。

## 5. 关键术语与直观模型

下列都是服务前述两个概念的辅助词，不扩成额外新核心机制：

| 术语 | 本课直观含义 |
|---|---|
| Unit test，单元测试 | 从可控初态调用一个行为单元，核对它的约定输出 |
| Unit under test，被测单元 | 本课的真实 `batch_*` 生产代码，而非 Fake |
| Fixture，夹具 | 每条测试建立自己那份状态的准备代码 |
| Table-driven case，表驱动用例 | 把有名字的输入与预期放入只读固定数组 |
| Equivalence class，等价类 | 契约要求同类处理的一组输入；选代表输入不意味着验证了整类所有值 |
| Boundary value，边界值 | 会改变处理结果的分界及相邻点，例如 63/64/65 |
| Regression，回归 | 修改后重跑既有约定，确认旧行为没有被破坏 |
| CTest | CMake 的测试执行工具；负责调度进程、收集退出码，不替你设计断言 |
| Host Fake，主机替身 | 替换边界外行为；本课只记录动作和接受显式的外部结果 |
| IRQ，中断请求 | 外设请求 CPU 处理事件；顺序输入表并未模拟真实 IRQ 并发 |
| HT / TC | DMA 半传输完成 / 传输完成；这里的 TC 必须说明是哪个外设的完成 |
| UART TC | USART 发送完成状态；与 DMA 搬完发送数据不是同一硬件事件 |
| session / token | 软件会话号 / 本次借出编号；外设本身不携带这些软件身份 |

一个直观模型：核心像“保管员”，决定哪个半区可以借出；Fake 是记账本，只记保管员发了什么动作；HAL 适配才是实际操作设备的人。让记账本自己判断“该不该借”，就把原问题改成了自问自答。

## 6. 从输入到结果的完整流程

### 6.1 文件、层级与五个动作

本课程新增的是测试资产，不新增一套生产架构。所有路径都相对于本课目录：

```text
../L039-host-test/core/batch.h       声明：公开类型和函数
../L039-host-test/core/batch.c       实现：唯一生产决策核心
host/minimal.c                     实例化并使用：一个最小独立用例
host/cases.def                     组装数据：33条只读输入/预期行
host/unit_batch.c                  实例化、测试组装与使用：夹具、记录器、诊断、入口
CMakeLists.txt                     分别构建生产核心与测试入口，逐条注册
host/regress.py                    构建/运行/清单核对/私有故意错误/保存证据
../L039-host-test/target/           已有完整F407实现，详见第8.2节文件表
```

- **声明**使编译器知道类型与调用形式，不等于创建对象。
- **实现**决定生产行为，在 `batch.c` 中，测试不复制它。
- **实例化**发生在测试局部 `Fixture` 或板端静态对象中。
- **组装**在这里仅指普通代码把输入、核心调用和记录器接起来；板端则是把句柄与 DMA 关联起来。
- **使用**是测试事件调用或 HAL 回调调用。它们不是同一个入口，也不拥有相同的证据等级。

依赖方向始终是 `host/target → core`；核心不包含 HAL 头文件，不依赖 CTest，不读取主机或板端系统时间。无需为了区分这五个动作，提前讲解架构阶段的独立概念。

### 6.2 一条边界用例的调用路径

以 `deadline_equal` 为例：

```text
CTest启动 unit_batch deadline_equal
  → 从只读表找到 SC_DEADLINE_POLL, start=100, now=164, expected=FAULT_DEADLINE
  → run_case创建全新Fixture
  → running：初始化、启动、arm成功；检查前提
  → loan：HT at 100；检查ACT_TX和所有权
  → input：POLL at 164, session=1
  → 同一个真实batch_event更新Batch并写BatchAction
  → record_action只追加STOP动作记录
  → 断言：ACT_STOP_SOURCE、MODE_FAULT、截止错误、半区0仍为TX
  → 输出PASS并返回0，或输出首个FAIL并返回1
```

测试不用 `sleep` 等现实时间，逻辑时刻由输入指定；这既使边界可重复，也限定了结论：没有验证 SysTick 精度、ADC 转换电压、总线竞争、IRQ 抢占或最坏响应时间。

`cases.def` 的 `CASE(...)` 是普通预处理宏展开，生成 `static const CaseSpec[]`；CMake 读取同一文件的用例名逐条 `add_test`。脚本再把 CTest 清单、二进制 `--list`、这份表三方比较，避免注册遗漏、拼错名字或只执行部分用例。[S7][S8]

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

能力地图服务于“哪些约定能在这个边界验证”，不是本课再增加五个学习目标：

| 层次 | 解决的问题、信号/数据/中断路径 | 配置入口与本课/后续落点 |
|---|---|---|
| 基础 | 初态 → 单次事件 → 状态/动作；证明完成半区才可发送 | 本课最小用例，直接调用真实核心 |
| 进阶 | 独立夹具 → 固定边界表 → 命名失败 → CTest 回归，解决串状态和失败定位 | 本课深入；33条用例，前后顺序核验 |
| 高级验证 | 在私有实现副本改变一个判断，观察指定断言是否变红；证明断言对该类错误敏感 | 本课只做三个有诊断的故意错误，不展开覆盖率/大型工具平台 |
| 高级外设链 | TIM 的内部更新事件形成 TRGO（触发输出）→ ADC 外部触发 → DMA 循环接收 HT/TC → UART DMA → USART TC IRQ；不是 CPU 每次定时中断里启动 ADC | 用定时器主模式、ADC EXTSEL/EXTEN、DMA CIRC 和 UART DMA/TC 串起来；本课给F407真实实现边界，L029-L032是已授基础 [S1][S4] |
| 高级DMA路径 | F4 的真正双缓冲可由 M0AR/M1AR 与当前目标位选择两块内存，减少软件切换地址；DMA burst（突发成组传输）/FIFO（先进先出缓冲）影响总线搬运；它们不等同于本课单数组的HT/TC分半 | 本参考工程用单M0循环，不启用这些路径；后续 `bus-matrix`/`dma-coherency` 用吞吐和所有权实验再落地，不能只改名后宣称已验证 [S1：第10章] |
| 跨外设故障联动 | 错误回调 → 核心STOP → 先停TIM源 → 前台停止ADC DMA/abort UART → 核查停止 → 清旧标志 → 新会话ARM | 本课测“外部失败反馈后不误恢复”；真实 abort 是否停止、旧IRQ是否排空，进入目标硬件实验 [S1][S4] |
| 并发/最坏时延 | 真实IRQ抢占、回调延迟、总线竞争可能使顺序测试中不发生的时序出现 | 后续 `rtos-concurrency/isr`、`race-condition` 及性能可靠性专题：在明确优先级/时钟下记录事件时间，不能拿顺序表替代 |

**系列差异不是改芯片宏即可。** 下面选的是器件级比较对象，不假定用户拥有这些板；对应手册、数据手册和固件包均记录在 `lesson.json`，包版本从实际 `package.xml` 读取。只对已经核对的差异下结论，未完成任何 F7/H5/H7 端口构建。

| 具体比较目标 / 固定包 | 已核对的实质差异 | 对本课测试边界与迁移的影响 |
|---|---|---|
| F407xx；F4基包1.28.0+补丁1.28.3 | DMA stream/channel 映射固定查表；本例ADC1用DMA2_Stream0/channel0、USART2_TX用DMA1_Stream6/channel4。DMA缓冲不能放F407的CCM数据RAM；本例需DMA可达SRAM [S1][S2][S4] | 本课模型可复用；stream/channel、地址、IRQ必须单独由目标证据核查。HAL中Flash加速器的cache配置不等于M7的数据cache |
| F767ZI；F7基包1.17.0+补丁1.17.3 | RM0410仍是DMA stream体系，固定包初始化有`Channel`字段；数据手册明确Cortex-M7及L1 cache [S9][S10][S11] | 复用状态测试不证明CPU/DMA对内存观察一致；重新查映射、内存可达性及cache策略。不能把F4映射数字和Flash cache设置照搬 |
| H563ZI；H5包1.5.0 | RM0481的GPDMA是通道/链表组织，可选择传输事件与安全属性；固定HAL含`Request/SrcInc/DestInc/TransferEventMode`，不是F4的stream `Channel`初始化。H563数据cache的手册作用范围须按外部存储器路径理解，不泛化成“M33都没有cache”或“M7式全部SRAM缓存” [S12][S13][S14] | 链表节点取数→外设请求搬运→所选块/链表事件→IRQ通知的定义可能与原半区模型不同。后续先画清发布粒度，再适配事件；核对安全/非安全访问，不在本课提供未构建的H5端口 |
| H743ZI；H7基包1.12.0+补丁1.12.1 | RM0433的DMAMUX1连接DMA1/2（D2），DMAMUX2连接BDMA（D3）；数据手册列D1/D2/D3域与M7数据/指令cache；固定HAL使用`Init.Request` [S15][S16][S17] | 请求复用器选择→相应域DMA→可达内存→IRQ链必须重查。状态归还测试不能证明跨域可达性、cache维护完成或cache行没有相邻对象 |

“复用模型”指保留借出/归还/故障/清理契约；“迁移硬件”指重新证明触发、搬运、可见性和真实完成事件。后续 `cache`、`dma-coherency`、`bus-matrix`、`f4-f7-h5-h7-comparison` 分题进行，本文不从F4推断其他系列全部行为。

### 7.2 参考目标与时钟/复位链

**参考器件为 STM32F407xx**；具体订货号/封装、可用外部ADC通道、引脚、供电和串口对端仍由用户确认。资料边界为RM0090 Rev22、DS8626 Rev12、UM1725 Rev8，固定CubeF4基包1.28.0+补丁1.28.3。[S1][S2][S3][S4]

不用未知板卡的HSE（高速外部振荡器）。参考实现选择HSI（高速内部振荡器）标称16MHz，PLL（锁相环）参数M=16、N=336、P=4、Q=7；假定**待板级资料确认**的2.7～3.6V供电，使用电压缩放Scale2与Flash 2等待周期。`Reference_Init` 对传入供电数值做范围检查，但这不是供电测量。[S1：Flash/RCC][S2：电气条件][S4：clock_init]

```text
HSI 16MHz（标称，实际误差由目标温度/电压条件决定）
  └─PLL输入 /16 = 1MHz → VCO ×336 = 336MHz
       ├─PLL P /4 = SYSCLK 84MHz
       │    └─AHB /1 = HCLK 84MHz → Cortex-M4与DMA的AHB侧
       │         ├─APB1 /2 = PCLK1 42MHz
       │         │    ├─TIM2：APB预分频不为1 → 定时器时钟84MHz
       │         │    │    └─PSC=83 → 1MHz计数；ARR=999 → 更新/TRGO 1kHz
       │         │    └─USART2：PCLK1 42MHz → OVER8=0的BRR分频 → 目标115200 baud
       │         └─APB2 /2 = PCLK2 42MHz
       │              └─ADC公共预分频 /4 → ADCCLK 10.5MHz
       └─PLL Q /7 = 48MHz（算式得到的支路，本例不启用USB等用户）
```

上述是由配置推导的**标称值**，不是示波器读数。[S1：第7/13/18/30章][S2] 关键时序怎样进入测试：

1. `f_update = 84MHz / (83+1) / (999+1) = 1000Hz`。ADC每次TRGO转换一个通道，相邻半区完成事件的标称间隔为 `64 / 1000 = 64ms`；一整圈128ms。`ClockDivision`的DIV1不是把上述计数公式再除一次，主计数频率由PSC决定。[S1：TIM]
2. 12位、84周期采样时，转换主体为 `(84+12)/10.5MHz ≈ 9.143µs`，远短于1ms触发间隔；这个算式**不包含**外部触发同步延迟、模拟源建立误差、回调延迟。采样时间是否适合传感器输出阻抗，要按DS8626的ADC电气条件另核，不能凭此宣布模拟采样准确。[S1：ADC][S2：ADC特性]
3. 每半区128字节，8N1（8位数据、无校验、1停止位）每字节10位。以目标115200计算，线占用约 `128×10/115200 = 11.111ms`，小于64ms。这只说明标称预算有余量，不是最坏时延证明。
4. **还应核对固定HAL的取整。** 本包UART分频宏在42MHz、115200、16倍过采样下得到`BRR=0x16C`，对应以标称时钟计算的波特率约115384.6，128字节约11.093ms；不是简单把十进制115200写入BRR。实际偏差还包括HSI误差与对端误差，必须读取目标BRR并测量。这里按固定包`UART_DIV*_SAMPLING16`/`UART_BRR_SAMPLING16`的整数运算核算，不以“最接近分频数”的心算替代实际HAL。[S1：USART][S4：hal_uart.h/c]
5. 核心窗口64是逻辑毫秒，板端输入来自默认1ms HAL tick（计时单位）。它检查的是**事件被软件处理时**的时间；不知道真实DMA已写到哪一拍。到截止才停源可能已经太晚，回调延迟还会移动软件观察点。因此红灯只能证明“能检测该输入的契约违例”，不能保证物理缓冲从未被覆盖。必须实测UART完成与半区复用的最坏间隔，并留足调度/中断余量。[S1][S4]

**门控和复位不能省略：**

| 资源 | 时钟门控与复位域 | 本例检查要点 |
|---|---|---|
| PWR | APB1的PWR门控 | 先可访问PWR，再配电压缩放 |
| DMA1/2 | RCC AHB1ENR的DMA1EN/DMA2EN；AHB1RSTR对应DMA复位 | DMA控制器在AHB侧，不存在“跟随ADC /4得到DMA时钟”的关系 |
| TIM2 | APB1ENR.TIM2EN、APB1RSTR.TIM2RST | 门控决定寄存器可用；计数时钟另受APB定时器规则与PSC影响 |
| USART2 | APB1ENR.USART2EN、APB1RSTR.USART2RST | 波特率基准是PCLK1，不是TIM2时钟 |
| ADC1 | APB2ENR.ADC1EN；APB2RSTR的ADC复位域 | ADC复位涉及共享域；ADC公共CCR.ADCPRE另决定转换时钟 |
| GPIO | 相应GPIO的AHB1门控 | 先使能再设analog/alternate function（模拟/复用功能）；不虚构port/pin |

这些门控/复位操作已经在完整参考文件中实现。[S1：RCC][S4：RCC宏及CMSIS器件头] **整组DMA/ADC复位只适用于本参考专用工程，无其他占用者；不要粘贴进共享设备的既有固件。** 初始化中的复位也不能代替运行期的停源、abort与清理确认。

### 7.3 CubeMX、HAL、LL 与寄存器对照

#### 7.3.1 项目级CubeMX配置清单

固定参考GUI分支为STM32CubeMX-Win 6.18.1，不把CubeMX2与它混称；UM1718 Rev51用于核对Pinout（引脚）、Clock Configuration（时钟配置）、DMA/NVIC（嵌套向量中断控制器）与代码生成页面。[S5][S6] **本次没有启动GUI或生成`.ioc`文件。** 下表是新建参考目标工程时的输入，不更改全局IDE/CubeMX设置。

| 页面/对象 | 参考值 | 与实现、测试的关系 / 板级约束 |
|---|---|---|
| MCU选择 | 实际STM32F407订货号和封装 | 由用户器件/原理图确定；不能把xx当可选封装 |
| RCC/Clock | HSI ON，HSI PLL；M16/N336/P4/Q7；AHB/1、APB1/2、APB2/2 | 得84/42/42MHz；HSE不启用，不填写虚构晶振 |
| SYS/时基 | SysTick 1ms，裸机，无RTOS；调试接口按板确认 | 主循环清理期间时基必须能推进 |
| TIM2 | Internal Clock、PSC83、ARR999、向上、ARPE使能、TRGO=Update | 不启用TIM2更新IRQ来驱动ADC；使用内部触发线 |
| ADC1 | 12bit、右对齐、单通道rank1、scan/continuous/discontinuous关闭 | 通道必须与所选封装和板ADC引脚一致 |
| ADC1触发 | TIM2 TRGO，上升沿；采样84cycles；PCLK2/4 | 外部每个触发一次转换；不是连续转换覆盖触发节奏 |
| ADC1 DMA请求 | Continuous Requests使能；EOC单次转换 | 连续DMA请求不等于ADC ContinuousConvMode |
| ADC1 DMA | DMA2_Stream0、channel0、P→M、periph不增、mem增、两端halfword（半字）、Circular（循环）、High（高优先级）、FIFO关、single burst（单次传输） | 128个halfword为一圈，不是128字节；只用M0，不启用真正双缓冲 |
| USART2 | Asynchronous TX、115200、8N1、oversampling16、无流控 | TX引脚、AF和串口对端电平由用户核对，不启用未用RX |
| USART2 TX DMA | DMA1_Stream6、channel4、M→P、periph不增、mem增、两端byte（字节）、Normal（单次普通模式）、Medium（中优先级）、FIFO关、single burst | 发送128字节；DMA Normal完成还要等待USART TC回调 |
| NVIC | DMA2_Stream0、DMA1_Stream6、ADC、USART2 IRQ均使能，分组4，设备优先级5、子优先级0 | 默认SysTick优先级15；主循环不能长期关总中断等HAL超时 |
| GPIO与电源 | ADC port/pin/channel、TX port/pin/AF、供电mV共7项经板级核对 | ADC脚用Analog/NOPULL；TX用AF_PP。两者不得错误重用同一脚 |
| 工程生成 | 项目级选定编译器、启动文件、链接脚本；固件固定F4基包1.28.0+patch1.28.3 | 不同时链接生成版和参考版的main、MSP、IRQ、SysTick等重复符号 |

DMA请求映射与TRGO选择分别按RM0090表43/44和表68核对；HAL常量在固定包的ADC/DMA头文件可追溯。[S1][S4]

#### 7.3.2 HAL初始化与句柄所有权

完整实现位于 [`../L039-host-test/target/reference_f407.c`](../L039-host-test/target/reference_f407.c)，**本课继续引用这一套真实原创参考文件，不用一句“参见上课”替代交付**。第8.2节给出全部必需文件、目标工程加入方法和板级阻断条件；本节把关键代码及其含义展开。

板端有静态`g_adc/g_uart/g_tim/g_adc_dma/g_tx_dma`句柄和四字节对齐的`g_batch`，寿命覆盖所有回调。`ReferencePins`只保存经用户确定的板级选择；调用`Reference_Init`时复制进静态`g_pins`，不会在初始化返回后悬空。句柄的`Instance`选择真实外设，`Init`保存配置，`State/ErrorCode`描述驱动状态；这些与核心的`mode/current_fault`不是一回事。[S3][S4]

下面是原参考实现的时钟函数摘录，**依赖该文件的头文件和静态对象，不是单独的第二个工程**。返回0代表该函数报告成功，非0向初始化调用者传错；目标仍须观察时基和实际时钟。

```c
static uint32_t clock_init(void)
{
    RCC_OscInitTypeDef o = {0};
    RCC_ClkInitTypeDef c = {0};
    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE2);
    o.OscillatorType = RCC_OSCILLATORTYPE_HSI;
    o.HSIState = RCC_HSI_ON;
    o.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
    o.PLL.PLLState = RCC_PLL_ON;
    o.PLL.PLLSource = RCC_PLLSOURCE_HSI;
    o.PLL.PLLM = 16u; o.PLL.PLLN = 336u;
    o.PLL.PLLP = RCC_PLLP_DIV4; o.PLL.PLLQ = 7u;
    if (HAL_RCC_OscConfig(&o) != HAL_OK) { return 1u; }
    c.ClockType = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK |
                  RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    c.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    c.AHBCLKDivider = RCC_SYSCLK_DIV1;
    c.APB1CLKDivider = RCC_HCLK_DIV2;
    c.APB2CLKDivider = RCC_HCLK_DIV2;
    return HAL_RCC_ClockConfig(&c, FLASH_LATENCY_2) == HAL_OK ? 0u : 1u;
}
```

`ClockType`表示要更新哪些时钟字段，不是额外分频。PLL参数是第7.2节算式的输入；Flash等待周期必须与供电及HCLK条件配套。HSI标称值不是每颗芯片的测量值。[S1][S2][S4]

同一文件中的完整ADC/UART初始化函数如下。GPIO、DMA和TIM由其前面的`peripherals_init()`完成，字段解释见后表；示例保持固定包的调用签名。[S4]

```c
static uint32_t adc_uart_init(void)
{
    ADC_ChannelConfTypeDef ch = {0};
    g_adc.Instance = ADC1;
    g_adc.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV4;
    g_adc.Init.Resolution = ADC_RESOLUTION_12B;
    g_adc.Init.ScanConvMode = DISABLE;
    g_adc.Init.ContinuousConvMode = DISABLE;
    g_adc.Init.DiscontinuousConvMode = DISABLE;
    g_adc.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_RISING;
    g_adc.Init.ExternalTrigConv = ADC_EXTERNALTRIGCONV_T2_TRGO;
    g_adc.Init.DataAlign = ADC_DATAALIGN_RIGHT;
    g_adc.Init.NbrOfConversion = 1u;
    g_adc.Init.DMAContinuousRequests = ENABLE;
    g_adc.Init.EOCSelection = ADC_EOC_SINGLE_CONV;
    if (HAL_ADC_Init(&g_adc) != HAL_OK) { return 1u; }
    ch.Channel = g_pins.adc_channel;
    ch.Rank = 1u;
    ch.SamplingTime = ADC_SAMPLETIME_84CYCLES;
    if (HAL_ADC_ConfigChannel(&g_adc, &ch) != HAL_OK) { return 1u; }
    g_uart.Instance = USART2;
    g_uart.Init.BaudRate = 115200u;
    g_uart.Init.WordLength = UART_WORDLENGTH_8B;
    g_uart.Init.StopBits = UART_STOPBITS_1;
    g_uart.Init.Parity = UART_PARITY_NONE;
    g_uart.Init.Mode = UART_MODE_TX;
    g_uart.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    g_uart.Init.OverSampling = UART_OVERSAMPLING_16;
    return HAL_UART_Init(&g_uart) == HAL_OK ? 0u : 1u;
}
```

| 结构字段/组装动作 | 意义、依赖与本课边界 |
|---|---|
| `ADC.ClockPrescaler` | 转换时钟用PCLK2/4；不是TIM触发频率 |
| `Resolution/DataAlign/NbrOfConversion` | 12位值右对齐，规则序列只转1个通道；目标DMA存到uint16_t样本 |
| `ScanConvMode/ContinuousConvMode/DiscontinuousConvMode` | 均关闭，避免一个触发被解释成不受控的连续序列 |
| `ExternalTrigConv/Edge` | 指定TIM2_TRGO与上升沿，落到ADC_CR2触发选择/边沿 |
| `DMAContinuousRequests/EOCSelection` | 允许后续转换继续请求DMA，EOC为单次转换；与DMA控制器本身的Circular是两个配置点 |
| `ch.Channel/Rank/SamplingTime` | 通道由板级核对；rank1；84周期由模拟源条件决定是否适用 |
| ADC DMA `Direction/PeriphInc/MemInc/DataAlignment` | DR地址固定、内存递增，单位为halfword；DMA `Length=128`计传输项 |
| TX DMA相同字段 | 内存递增、USART DR固定，传输项为byte；TX `Size=128`计字节 |
| 两个DMA `Mode/Priority/FIFOMode/MemBurst/PeriphBurst` | 接收Circular/High，发送Normal/Medium，均直接模式与single；优先级只表示DMA仲裁配置，不证明截止必达 |
| `__HAL_LINKDMA(&g_adc,DMA_Handle,g_adc_dma)` | ADC句柄与DMA句柄关联，并使DMA的Parent可回到ADC；不是新建第二个DMA对象 |
| `__HAL_LINKDMA(&g_uart,hdmatx,g_tx_dma)` | UART的发送DMA句柄关联；必须在DMA启动和IRQ前存在 |
| TIM `Prescaler/Period/CounterMode/ClockDivision/AutoReloadPreload` | 83/999、向上、DIV1、ARR预装载；主触发另由`MasterOutputTrigger=TIM_TRGO_UPDATE`设置 |
| UART `BaudRate/WordLength/StopBits/Parity/Mode/HwFlowCtl/OverSampling` | 115200/8/1/无校验/TX/无流控/16倍；波特率与线路完成另需真实证据 |

所有这些初始化代码都在完整参考文件中；字段和HAL状态契约以固定包和UM1725为准。[S3][S4] 不把“句柄结构里有DMA指针”误认作“DMA已经开始”，更不能用主机假成功取代HAL返回值检查。

#### 7.3.3 从初始化、启动到回调的最小完整调用路径

实际入口是 [`../L039-host-test/target/reference_main.c`](../L039-host-test/target/reference_main.c)。它要求7个`BOARD_*`选择，没有这些选择就用编译期错误阻止虚构板级实现。初始化顺序为：

```text
main: HAL_Init（默认SysTick时基）
  → Reference_Init(已核对ReferencePins)
    → 参数与供电范围检查
    → clock_init
    → peripheral门控/专用复位 + GPIO
    → HAL_DMA_Init(ADC与TX) + __HAL_LINKDMA
    → HAL_TIM_Base_Init + HAL_TIMEx_MasterConfigSynchronization
    → HAL_ADC_Init / HAL_ADC_ConfigChannel / HAL_UART_Init
    → 配设备IRQ优先级并使能
    → batch_init(window=64) → batch_start → ACT_ARM
       → HAL_ADC_Start_DMA(128个halfword) 先准备接收
       → HAL_TIM_Base_Start 最后打开采集源
       → batch_arm_result(实际HAL结果)
  → 主循环不断Reference_Service
```

必须先装好ADC/DMA再启TIM，否则第一拍触发可能发生在接收链尚未就绪时。参考代码在重新arm前清计数器与更新标志；TIM初始化可能产生更新事件，不能把初始化时的事件当成正常采样时刻。[S1][S4]

以下是完整适配文件中`short_actions`的两个关键分支摘录。对象均为前述静态板端对象；板端负责真正执行动作，测试记录器则只记录动作。

```c
/* 位于 ACT_ARM 分支；先接收后启源，HAL错误明确回送核心。 */
uint32_t bad;
memset(&g_hw_ticket, 0, sizeof(g_hw_ticket));
__HAL_TIM_SET_COUNTER(&g_tim, 0u);
__HAL_TIM_CLEAR_FLAG(&g_tim, TIM_FLAG_UPDATE);
__DMB();
bad = HAL_ADC_Start_DMA(&g_adc, (uint32_t *)g_batch.samples,
                         BATCH_SAMPLES) == HAL_OK ? 0u : 1u;
if (bad == 0u && HAL_TIM_Base_Start(&g_tim) != HAL_OK) { bad = 1u; }
batch_arm_result(&g_batch, bad, HAL_GetTick(), &a);
g_callbacks = bad == 0u ? 1u : 0u;
```

`HAL_ADC_Start_DMA`的接口参数类型为`uint32_t *`，不意味着本例样本变成32位；真正传输宽度由DMA的halfword字段决定。缓冲起点及`Batch.samples`偏移有四字节对齐检查，位置仍必须由目标链接输出证明位于DMA可达SRAM。[S4] `__DMB()`是内存屏障，不是cache清理，也不是硬件完成测量。

```c
/* 位于 ACT_TX 分支；失败不能假装已经借出又完成。 */
g_hw_ticket = a;
__DMB();
if (HAL_UART_Transmit_DMA(&g_uart,
        (uint8_t *)&g_batch.samples[a.half * BATCH_HALF_SAMPLES],
        (uint16_t)BATCH_HALF_BYTES) != HAL_OK) {
    BatchEvent e = {EV_TX_START_ERROR, HAL_GetTick(), a.session, a.half, a.token};
    g_last_hal_error = g_uart.ErrorCode;
    batch_event(&g_batch, e, &a);
} else { a.kind = ACT_NONE; }
```

这里只展示分支代码；不要把两个摘录当成可独立链接的文件。完整的循环、STOP动作及异常动作防护都在参考文件的`short_actions()`，并由核心后续动作接续执行；返回HAL_BUSY、HAL_ERROR或HAL_TIMEOUT均不得冒充发送成功。[S3][S4]

**回调到核心事件的桥梁也是真代码：**

```c
static void emit(uint32_t kind, uint32_t half, uint32_t token)
{
    uint32_t p = lock();
    if (g_callbacks != 0u) {
        BatchAction a = {0};
        BatchEvent e = {kind, HAL_GetTick(), g_batch.session, half, token};
        batch_event(&g_batch, e, &a);
        short_actions(a);
    }
    unlock(p);
}
void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *h)
{ if (h == &g_adc) { ++g_ht; emit(EV_HT, 0u, 0u); } }
void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *h)
{ if (h == &g_adc) { ++g_tc; emit(EV_TC, 1u, 0u); } }
void HAL_UART_TxHalfCpltCallback(UART_HandleTypeDef *h)
{ (void)h; /* 发送进度，不在这里归还。 */ }
void HAL_UART_TxCpltCallback(UART_HandleTypeDef *h)
{ if (h == &g_uart) { ++g_tx; emit(EV_TX_DONE, g_hw_ticket.half, g_hw_ticket.token); } }
void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *h)
{ if (h == &g_adc) { ++g_error; g_last_hal_error = h->ErrorCode; emit(EV_IO_ERROR, 0u, 0u); } }
void HAL_UART_ErrorCallback(UART_HandleTypeDef *h)
{ if (h == &g_uart) { ++g_error; g_last_hal_error = h->ErrorCode; emit(EV_IO_ERROR, 0u, 0u); } }
void DMA2_Stream0_IRQHandler(void) { HAL_DMA_IRQHandler(&g_adc_dma); }
void DMA1_Stream6_IRQHandler(void) { HAL_DMA_IRQHandler(&g_tx_dma); }
void ADC_IRQHandler(void) { HAL_ADC_IRQHandler(&g_adc); }
void USART2_IRQHandler(void) { HAL_UART_IRQHandler(&g_uart); }
void SysTick_Handler(void) { HAL_IncTick(); }
```

这一桥接层属于板端适配，不属于核心测试；实际`lock/unlock`保存并恢复PRIMASK，串行化核心调用。这里解释已有串行化责任，不展开新的中断并发模型。[S4]

完整硬件路径：[S1][S4]

```text
TIM2更新/TRGO → ADC规则转换 → ADC_DR
  → DMA2_Stream0写g_batch.samples
  → HT/TC IRQ → HAL_DMA_IRQHandler → ADC内部DMA桥接回调
  → HAL_ADC_ConvHalfCpltCallback / HAL_ADC_ConvCpltCallback
  → emit → batch_event → ACT_TX → HAL_UART_Transmit_DMA
  → DMA1_Stream6搬内存到USART2_DR
  → DMA TC中断的UART内部回调（Normal模式：关DMAT，开TCIE）
  → USART2线路发送完成，TC IRQ
  → HAL_UART_IRQHandler → UART_EndTransmit_IT → HAL_UART_TxCpltCallback
  → emit → batch_event(EV_TX_DONE) → 归还匹配的半区
```

因此只打开DMA IRQ而漏掉USART2 IRQ，会出现“数据搬完、主机模型也能完成，但板端永远没有HAL TX完成”的故障。不能在UART半完成回调、也不能仅凭DMA的TC标志归还本契约的批次。[S4：`UART_DMATransmitCplt`、`UART_EndTransmit_IT`]

**软件身份的限制：**`g_hw_ticket`是适配层保存的软件动作，不是UART回调参数中自带的硬件ticket。回调重新读取当前会话，不能靠给软件整数加一就证明旧IRQ来自哪里。因此重新arm前必须真正停源、停DMA/发送、清外设状态并清NVIC pending（待处理中断）；旧会话测试验证了核心对“明确带旧号的事件”的处理，不验证适配层一定能给真实旧中断正确编号。[S1][S4]

#### 7.3.4 错误、停源、清理与显式恢复

错误路径不是一个“忽略返回值后重试”的空分支。完整参考实现具备以下行为；主机用例只检验“给定外部结果后核心是否遵守契约”：

| 发生位置 | 真实适配如何处理 | 主机对应的输入/用例 |
|---|---|---|
| 时钟/外设初始化失败 | `Reference_Init`返回1；main进入可由调试器观察的错误循环，不对未就绪句柄乱恢复 | 不在本批次核心的主机证明范围 |
| 首次ADC arm或TIM启动失败 | `batch_arm_result(error)` → START故障 → STOP；初始化返回2表示已建立对象但首轮启动故障，仍可Service/显式恢复 | `arm_failure_stops` |
| UART启动非HAL_OK | 形成`EV_TX_START_ERROR`，保留借出，先STOP | `tx_start_failure_stops` |
| ADC OVR / DMA或UART错误 | HAL错误回调保存ErrorCode，形成`EV_IO_ERROR` → STOP | `device_error_stops`；不代表真的注入过硬件OVR |
| STOP返回失败或CEN仍置位 | 记录stop_errors，不清缓冲、不重启；可做尽力关TIM，但不声称已停 | `stop_failure_keeps_loan` |
| 主循环发起清理 | 仅显式`Reference_RequestRecovery`后进入CLEANING；先关闭4个设备IRQ，保留SysTick推进 | `poll_does_not_recover` / `explicit_recovery_new_session` |
| ADC停止或UART abort失败、DMA EN仍为1 | `cleanup_hardware`返回失败；核心留故障，保持样本、会话、借出 | `cleanup_failure_keeps_loan`，聚合外部清理失败，不宣称测试了HAL内部 |
| 清理成功 | 重建相关HAL/DMA状态，清外设标志后清NVIC pending，再反馈成功 → 新会话ARM | `explicit_recovery_new_session` / `first_fault_preserved` |

清理的实际顺序在完整的`cleanup_hardware()`中是：关闭设备IRQ → 停TIM2并查CEN → `HAL_ADC_Stop_DMA` → `HAL_UART_AbortTransmit` → 查两条stream的EN均0 → DMA deinit/init → ADC/UART deinit/init → 清ADC OVR/EOC/STRT、USART TC、TIM更新标志 → 清4个设备IRQ pending。任何前置失败都不进入清样本/重启路径。[S1][S4]

前台`Reference_Service`先让核心输出`ACT_CLEAN`，恢复总中断后执行上述可能阻塞的清理，再串行调用`batch_cleanup_result`。**不能在总中断关闭的临界区等待HAL超时**，否则默认SysTick无法前进。`batch_recover`本身不要求`stop_ok=1`才进入清理，因为清理会再次执行停源并检查；不能把一次“已发STOP命令”当作硬件已停止。[S4]

固定F4包还存在一个必须如实交代的边界：`HAL_Init()`内部调用`HAL_InitTick()`但最终直接返回HAL_OK，并不向上转交它的失败。因此main里调用`HAL_Init`不能独立证明默认时基有效；目标调试时须观察`HAL_GetTick`随真实时间递增。[S4：`stm32f4xx_hal.c`]

#### 7.3.5 HAL → LL / 关键寄存器与事件对照

下表的LL接口名已在固定F4包头文件核对；它们用于定位硬件意义，**不是已完成或测试过的第二套LL端口**。不能只把`HAL_`换成`LL_`，更不能在HAL持有同一外设时混写状态。[S1][S3][S4]

| HAL配置/动作 | LL阅读入口或关键寄存器/标志 | 与本课边界相关的意义 |
|---|---|---|
| `HAL_RCC_OscConfig/ClockConfig` | `LL_RCC_SetAHBPrescaler`；RCC_PLLCFGR、CFGR的SW/HPRE/PPRE，CR中的就绪位；FLASH_ACR.LATENCY | 84/42MHz必须从链路推导，不能从核心逻辑tick反推 |
| `HAL_TIMEx_MasterConfigSynchronization` | `LL_TIM_SetTriggerOutput`；TIM2_CR2.MMS=Update，CR1.CEN、PSC/ARR/EGR | 更新事件走内部TRGO；本例无需TIM2更新IRQ |
| `HAL_ADC_Init/ConfigChannel` | `LL_ADC_REG_SetTriggerSource`；ADC_CR2.EXTSEL/EXTEN、ADC公共CCR.ADCPRE、SMPRx、SQRx | 选择TIM2_TRGO；F407规则组EXTSEL编码0110；采样周期与序列决定何时产出DR |
| `HAL_DMA_Init`的ADC接收 | `LL_DMA_SetChannelSelection`；DMA2_Stream0的CR.CHSEL=0、CIRC、MINC、MSIZE/PSIZE、PAR/M0AR/NDTR | NDTR=128个halfword；HT/TC是单数组的两个位置，不等于真正双缓冲切换 |
| ADC DMA IRQ | DMA2_LISR的HTIF0/TCIF0及TEIF0/DMEIF0/FEIF0；LIFCR清标志 | 交给`HAL_DMA_IRQHandler`后才进入ADC回调；错误来源与核心故障码分层 |
| `HAL_UART_Transmit_DMA` | `LL_USART_EnableDMAReq_TX`；USART2_CR3.DMAT、DMA1_Stream6.CHSEL=4、NDTR=128个byte | 从借出半区读内存，调用返回OK不表示已经发送完成 |
| UART DMA Normal完成 | DMA1_HISR.TCIF6；USART_CR3.DMAT与CR1.TCIE | DMA TC关闭DMAT并使能USART TC中断，不在这里执行最终HAL TX完成回调 |
| UART线路完成 | USART_SR.TC、CR1.TCIE；USART_BRR | USART IRQ中调用HAL TX完成，才形成匹配的EV_TX_DONE |
| 停源/清理 | TIM_CR1.CEN；DMA_SxCR.EN；ADC_CR2.ADON/DMA；外设状态与NVIC pending | 核心只请求STOP/CLEAN；可达硬件是否已静默由适配与实机证据承担 |

精确阅读位置：RM0090第7、10（表43/44）、13（表68）、18、30章；固定包HAL的ADC `HAL_ADC_Start_DMA/Stop_DMA`、UART `HAL_UART_Transmit_DMA/AbortTransmit`、`UART_DMATransmitCplt/EndTransmit_IT`，以及相应LL头。文件SHA-256（内容指纹）和函数阅读行号在 [`evidence/source-audit.json`](evidence/source-audit.json)，不把第三方完整驱动源码复制进课程。[S1][S4]

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

#### 8.1.1 一条命令完成可复现回归

仓库根目录需要Python 3.11及以上、CMake/CTest、Ninja和能编译C11的主机C编译器（配套脚本的版本探测按GCC；其他编译器需调整探测命令，或先按手动命令构建）。CMake选择的实际编译器以configure日志为准；本次为MSYS2 UCRT64的GCC 16.2.0，CMake/CTest均4.4.3，Python 3.14.7。

```powershell
python lessons/L040-unit-test/host/regress.py
if ($LASTEXITCODE -ne 0) { throw 'L040 host regression failed; inspect evidence logs' }
```

脚本每次在本课`build/verify-时间戳/`下新建独立构建目录，记录实际绝对命令；不会删除用户目录、重置Git或修改L039。`build/`被本课`.gitignore`排除，其中的临时实现副本和官方PDF不成为教程源码。

脚本按下面顺序运行：

1. 配置并编译真实核心、最小入口及完整入口；保存编译器/CMake/CTest版本。
2. 比较`cases.def`、CTest JSON清单、二进制`--list`的33个名字，不能漏注册或多注册。
3. 实际运行最小入口、单独的`ht_borrows_half0`、完整33条CTest；用`--no-tests=error`阻断空集合。
4. 同进程`--all`正序与`--reverse`逆序各33条，检查执行数量和失败数量。这一项补足“每条CTest独立进程可能掩盖进程内残留”的盲点；不声称穷尽所有排列。
5. 故意拼错用例名，要求返回2、明确说明未执行测试。
6. 在本次构建目录的三个**私有生产实现副本**中各改一处，先要求编译成功，再要求指定用例非零失败且诊断匹配。编译错误不算抓住行为错误。
7. 将各私有副本恢复为原始核心内容，重建并运行完整33条；最后再跑原核心套件，校验原文件SHA-256未变。

若只想手动运行某条，用另一独立构建目录即可：[S7][S8]

```powershell
cmake -S lessons/L040-unit-test -B lessons/L040-unit-test/build/manual -G Ninja
cmake --build lessons/L040-unit-test/build/manual
ctest --test-dir lessons/L040-unit-test/build/manual --show-only=json-v1
# 上一条只列举，不是运行证据。
ctest --test-dir lessons/L040-unit-test/build/manual --output-on-failure --no-tests=error -R '^unit.deadline_equal$'
ctest --test-dir lessons/L040-unit-test/build/manual --output-on-failure --no-tests=error
.\lessons\L040-unit-test\build\manual\unit_batch.exe --reverse
```

正常注册集合不包含故意失败副本，也没有设置“预期失败即成功”的测试属性。

#### 8.1.2 用例表：初态、刺激、独立预期与本次结果

表中R表示由正常API建立的新会话运行态：session1、半区0采集、半区1空闲、无发送；L表示从R输入HT at100，借出半区0/token1，下一半区采集；F表示L在110输入IO错误进入故障。每行都重新创建夹具，R/L/F不是与上一行共享的对象。每行最后“通过”只指本次主机用例。具体辅助安全断言可在测试入口阅读。

| 测试名（CTest前缀均为`unit.`） | 独立初态 → 主要刺激 | 主要预期 / 关键保留项 | 结果 |
|---|---|---|---|
| `ht_borrows_half0` | R → HT0 at100 | TX0/token1，半区0TX、半区1采集 | 通过 |
| `tx_done_returns_half0` | L → 匹配DONE at110 | 无新动作，半区0FREE，样本哨兵不清 | 通过 |
| `tc_borrows_half1` | L再正常DONE → TC1 at164 | TX1/token2，半区0采集 | 通过 |
| `tc_before_ht` | R → TC1 at100 | ORDER故障/STOP，无TX | 通过 |
| `ht_wrong_half` | R → HT携带half1 | ORDER故障/STOP | 通过 |
| `ht_duplicate` | L → 第二次HT at101 | ORDER故障，原借出保留 | 通过 |
| `tc_while_tx_busy` | L → TC1 at110 | BUSY故障，不产生第二次TX | 通过 |
| `done_without_loan` | R → DONE at100 | CALLBACK故障，不释放采集区 | 通过 |
| `done_wrong_token` | L → token2的DONE at110 | CALLBACK故障，token1仍借出 | 通过 |
| `done_wrong_half` | L → half1的DONE at110 | CALLBACK故障，半区0仍借出 | 通过 |
| `done_duplicate` | L正常DONE → 第二次DONE at111 | CALLBACK故障；已FREE的半区不误改 | 通过 |
| `stale_session` | R → session0的HT | STALE故障，无TX | 通过 |
| `unknown_event` | R → kind99 | ARGUMENT故障，无TX | 通过 |
| `deadline_minus_one` | L → POLL at163 | 仍运行、无新动作、仍借出 | 通过 |
| `deadline_equal` | L → POLL at164 | DEADLINE故障/STOP，仍借出 | 通过 |
| `deadline_plus_one` | L → POLL at165 | DEADLINE故障/STOP，仍借出 | 通过 |
| `deadline_equal_done` | L → 正确DONE at164 | 截止判定优先，不能按完成释放 | 通过 |
| `wrap_minus_one` | HT at0xffffffe0 → POLL at31 | 间隔63，仍运行 | 通过 |
| `wrap_equal` | HT at0xffffffe0 → POLL at32 | 间隔64，DEADLINE故障 | 通过 |
| `wrap_plus_one` | HT at0xffffffe0 → POLL at33 | 间隔65，DEADLINE故障 | 通过 |
| `stop_failure_keeps_loan` | F → 外部停源反馈失败 | stop_errors加1，样本哨兵与借出保留 | 通过 |
| `cleanup_failure_keeps_loan` | F → 显式清理请求 → 反馈失败 | 回到FAULT，无ARM，不换会话不清哨兵 | 通过 |
| `explicit_recovery_new_session` | F → 显式清理成功 | session2/ARM；清样本、再arm成功运行 | 通过 |
| `poll_does_not_recover` | F → 仅POLL at120 | 仍故障，不自动换会话 | 通过 |
| `first_fault_preserved` | F → 成功恢复 → 第二种故障 | 当前错误改变，首错仍DEVICE/tick110/session1 | 通过 |
| `arm_failure_stops` | 新初始化并启动 → arm反馈失败 | START故障/STOP | 通过 |
| `tx_start_failure_stops` | L → TX启动错误 at110 | START故障，借出保留 | 通过 |
| `device_error_stops` | L → IO错误 at110 | DEVICE故障，借出保留 | 通过 |
| `start_denied_while_running` | R → 再次start | 返回0，无动作，不换会话 | 通过 |
| `cleanup_wrong_mode_ignored` | R → 无请求却输入cleanup成功 | 无动作，仍运行且样本不清 | 通过 |
| `window_zero_rejected` | 新对象 → init(0) | 返回0，window仍0 | 通过 |
| `window_half_range_rejected` | 新对象 → init(0x80000000) | 返回0，window仍0 | 通过 |
| `window_max_valid` | 新对象 → init(0x7fffffff) | 返回1，保存该参数 | 通过 |

这张表不是所有可能行为的完备证明。例如本次未加入session/token达到UINT32_MAX的耗尽用例、任意事件组合、所有错误优先级排列、任意次计时回绕。它们可在已有两个核心概念内增补，但不能把当前33条通过宣传为“全部输入已验证”。

#### 8.1.3 真实红灯、修复与证据索引

本次记录日期为2026年10月21日。完整命令、时间、退出码、输入文件与二进制内容指纹在 [`evidence/host-results.json`](evidence/host-results.json)。关键记录：

| 证据文件 | 本次实际结果与可证明范围 |
|---|---|
| `evidence/green-configure.log`、`green-build.log` | 主机C11核心与两个入口的配置/构建，退出0；不是ARM构建 |
| `evidence/minimal-case.log` | `PASS case=minimal_ht`，退出0 |
| `evidence/ctest-inventory.log`、`binary-inventory.log` | 两份清单与表的33个名字一致；枚举本身不是执行 |
| `evidence/single-case.log` | 单独命名用例实际运行1条，退出0 |
| `evidence/green-ctest.log` | 正常33/33，退出0 |
| `evidence/same-process-forward.log`、`same-process-reverse.log` | 各`executed=33 failures=0`，退出0；检查这两种顺序独立 |
| `evidence/unknown-case-rejected.log` | 拼错名字明确退出2，未伪装成测试成功 |
| `evidence/red-deadline-strict.log` | 私有副本把`>=`改为`>`；`deadline_equal`实际失败，CTest退出8 |
| `evidence/red-busy-guard-removed.log` | 私有副本删除忙保护；`tc_while_tx_busy`实际失败，CTest退出8 |
| `evidence/red-cleanup-result-inverted.log` | 私有副本颠倒清理反馈判断；`cleanup_failure_keeps_loan`实际失败，CTest退出8 |
| `evidence/repaired-*-ctest.log` | 三个私有副本各自修复后，分别完整33/33，退出0 |
| `evidence/final-ctest.log` | 原始生产核心最终完整33/33，退出0；其内容指纹前后不变 |
| `evidence/source-audit.json` | Teacher来源与版本核对、复用文件指纹；不是Reviewer通过结论 |

典型红灯摘录来自实际日志，不是编造的期望输出：

```text
FAIL case=deadline_equal step=deadline field=f->last.kind actual=0 expected=3 file=unit_batch.c:110
FAIL case=tc_while_tx_busy step=fault-event field=f->last.kind actual=2 expected=3 file=unit_batch.c:110
FAIL case=cleanup_failure_keeps_loan step=cleanup-failed field=f->batch.mode actual=1 expected=3 file=unit_batch.c:261
```

这些行为什么有用？第一行指出“恰好截止却没发STOP”，第二行指出“仍忙却再发TX”，第三行指出“清理失败却进入STARTING”。数字对应固定头文件的动作/状态常量；诊断里的字段是本条主要断言，不需要从另一条测试遗留的状态猜原因。

这里的“修复”是把**私有故意错误副本**恢复为原生产逻辑，未声称发现并修复了L039的既有缺陷。脚本没有把故意错误写回旧课。抓住3/3个选择的错误，也不等于抓住所有潜在错误。

### 8.2 STM32 参考实现轨道

#### 8.2.1 交付不是硬件展望：明确复用的完整文件

本课不制造第二套同名HAL实现。以下既有原创文件是本课硬件轨道的实际依赖，保留原路径、不修改；`evidence/source-audit.json`记录它们的SHA-256。把本课与L039一起保留即可沿路径阅读和加入目标工程，不能单拷贝本课后假称所有硬件依赖自包含。

| 实际文件 | 内容、所属层、生命周期 |
|---|---|
| [`../L039-host-test/core/batch.h`](../L039-host-test/core/batch.h) | 固定宽度公开类型与函数声明；无HAL依赖 |
| [`../L039-host-test/core/batch.c`](../L039-host-test/core/batch.c) | 唯一交接决策实现；本次主机实际编译的同一个源文件 |
| [`../L039-host-test/target/reference_f407.h`](../L039-host-test/target/reference_f407.h) | 板端公开声明、ReferencePins/Diag；依赖HAL与核心 |
| [`../L039-host-test/target/reference_f407.c`](../L039-host-test/target/reference_f407.c) | 完整时钟/GPIO/TIM/ADC/DMA/UART初始化、IRQ/回调、短动作、停源、前台清理、显式恢复；静态句柄持有所有异步对象 |
| [`../L039-host-test/target/reference_main.c`](../L039-host-test/target/reference_main.c) | 真正main与7项BOARD选择的编译期阻断；前台Service，不自动重试恢复 |
| [`../L039-host-test/target/stm32f4xx_hal_conf.h`](../L039-host-test/target/stm32f4xx_hal_conf.h) | 本专用参考工程的HAL模块/时基配置；不是修改用户全局配置 |

这些文件构成**有具体HAL初始化、使用、回调和错误处理的参考实现，待目标工程编译**。本次没有对该轨道执行交叉编译或硬件操作，也不把L039以前的语法检查/主机记录移花接木成本次目标证据。不能仅因官方包文件存在，就说目标工程已构建成功。

可直接复用的是批次核心、F407适配的代码组织与已核对API；必须由板级资料确定的是七个选择：

- `BOARD_ADC_GPIO_PORT / BOARD_ADC_GPIO_PIN / BOARD_ADC_CHANNEL`；
- `BOARD_TX_GPIO_PORT / BOARD_TX_GPIO_PIN / BOARD_TX_GPIO_AF`；
- `BOARD_SUPPLY_MV`，必须有板级供电资料/测量，不以芯片支持范围假装实际电压。

它们不是未清理的教程占位符，而是参考main显式要求的板级契约。没有这些信息就应让目标编译停止，不填入猜测的PA口、晶振频率、串口转换板或外接电路。还需确认ADC电压范围、模拟地/VDDA/VREF条件、TX对端电平和共地、所选两引脚不冲突。[S1][S2][S4]

#### 8.2.2 待用户执行的目标构建、观察与排错步骤

以下全是**待执行**；本次不烧录、不修改IDE/CubeMX全局设置。

1. 取得实际芯片订货号、封装、板卡原理图与供电，核对7项BOARD选择；若不满足本参考2.7～3.6V条件，先重新设计电压缩放/Flash时序，不绕过检查。
2. 用项目级CubeMX配置落实第7.3.1节。固定固件基包与补丁关系；本课来源审计读取了实际`package.xml`，不能只靠文件夹名。
3. 在自己的目标工程加入上表核心、参考适配和参考main；包含路径加入核心及target目录、固定HAL/CMSIS头；定义`STM32F407xx`、`USE_HAL_DRIVER`和核对后的BOARD选择。生成版同名main/IRQ/SysTick/MSP不能重复链接。
4. 从已安装官方包**引用而非复制进课程仓库**：CMSIS设备启动文件、`system_stm32f4xx.c`，HAL core/cortex/rcc/rcc_ex/gpio/dma/adc/adc_ex/tim/tim_ex/uart/flash/flash_ex/pwr/pwr_ex等对应实现。选定Cortex-M4/Thumb、FPU（浮点单元）与一致ABI（应用二进制接口）和实际芯片链接脚本；这是目标工程而非本课主机CMake的责任。[S4]
5. 执行目标工具链完整编译链接，保存命令、编译器、固件版本、输出和退出码；检查Map（链接布局）确认`g_batch`及样本在DMA可达SRAM、不在CCM，对齐满足要求，栈堆预算可解释。没有成功链接不能声称目标构建通过。[S1][S2]
6. 若用户随后明确决定在其板上部署，再由用户按板卡/调试器规程烧录并记录固件身份。本次任务不执行这一动作。启动后先观察`HAL_GetTick`递增、RCC频率/分频、TIM2的PSC/ARR/CEN、ADC触发选择和DMA NDTR；不要先拿“串口没数据”猜算法错。
7. 按`TIM2 TRGO → ADC转换 → DMA2 HT/TC → 核心动作 → DMA1 TX → USART TC → 归还`寻找第一处缺失边界。内部TRGO没有自动对应某个外部引脚；逻辑分析仪直接看到的是经真实接线的UART或用户另行设计的观测信号。新增观测信号也要核对引脚并记录其扰动。
8. 正常应见HT/TC交替、每半区一次发送启动及最终HAL TX完成；以调试器短快照/事件计数和仪器时间戳核对实际半区周期、UART位时间与最坏归还间隔。断点会暂停CPU并可能改变外设时序，不能拿断点运行的延迟当无扰动测量。
9. 用安全的板级方法分别制造/观察发送忙、错误、停源/abort失败，检查`ReferenceDiag`首错、stop_errors、cleanup_errors；显式请求恢复前确认故障原因已处理。不得为了做实验直接违反外设电气条件。
10. 只有有目标板、构建、烧录和实际观察等相互对应证据，才讨论硬件验证状态；本课仍保持false。主机单测的绿色不能替代任一步。

板端迁移最小检查单：触发源是否同义；时钟及窗口是否重算；DMA请求/宽度/单位/IRQ是否重查；缓冲可达性与cache/安全属性是否核实；完成事件是否真的表示所需的线路完成；旧会话清理是否排空真实硬件；关键错误是否可观测；源/包/构建/固件/测量身份是否一致。[S1]-[S4][S9]-[S17]

## 9. 最小代码示例

### 9.1 一个入口、一条用例、同一生产实现

以下完整内容对应本课真实文件`host/minimal.c`。它属于测试层，依赖方向为`minimal → core`，对象全在`main`内持有，不使用动态内存，不依赖HAL。公开的生产标量接口使用`uint32_t`等固定宽度类型，主机`main`遵循标准C入口签名。

```c
#include "batch.h"
#include <inttypes.h>
#include <stdio.h>

static uint32_t check(const char *step, const char *field,
                       uint32_t actual, uint32_t expected)
{
    if (actual == expected) { return 0u; }
    fprintf(stderr, "FAIL case=minimal_ht step=%s field=%s actual=%" PRIu32
                    " expected=%" PRIu32 "\n", step, field, actual, expected);
    return 1u;
}
int main(void)
{
    Batch s = {0};
    BatchAction a = {0};
    const BatchEvent e = {EV_HT, 100u, 1u, 0u, 0u};
    uint32_t ok = batch_init(&s, 64u);
    if (check("init", "return", ok, 1u) != 0u) { return 1; }
    ok = batch_start(&s, &a);
    if (check("start", "return", ok, 1u) != 0u ||
        check("start", "action", a.kind, ACT_ARM) != 0u) { return 1; }
    batch_arm_result(&s, 0u, 0u, &a);
    if (check("arm", "mode", s.mode, MODE_RUNNING) != 0u) { return 1; }
    batch_event(&s, e, &a);
    if (check("ht", "action", a.kind, ACT_TX) != 0u ||
        check("ht", "session", a.session, 1u) != 0u ||
        check("ht", "half", a.half, 0u) != 0u ||
        check("ht", "token", a.token, 1u) != 0u ||
        check("ht", "half0", s.half_state[0], HALF_TX) != 0u ||
        check("ht", "half1", s.half_state[1], HALF_CAPTURE) != 0u ||
        check("ht", "active", s.tx_active, 1u) != 0u) { return 1; }
    puts("PASS case=minimal_ht");
    return 0;
}
```

这条用例的期望不是`a.kind`自己推出来的：先确定HT0应发TX0/token1，再用常量核对。启动的返回值、动作和arm结果也被检查，避免把不成立的初态当成测试准备成功。

### 9.2 扩展为独立夹具和动作记录，不扩展成另一份算法

完整可编译入口在 [`host/unit_batch.c`](host/unit_batch.c)。核心形态如下；摘录与该文件一致，需放在原文件上下文中使用：

```c
typedef struct {
    BatchAction actions[16];
    uint32_t count;
} FakeActions;
typedef struct {
    Batch batch;
    BatchAction last;
    FakeActions io;
    const char *name;
    uint32_t checks;
} Fixture;
```

每次`run_case`只创建本条`Fixture storage = {0}`。`running`检查启动并保留第一条ARM动作记录；`loan`通过真实HT产生第二条TX记录，检查`token=1`及两半区状态。`record_action`只在非ACT_NONE时向固定16项数组追加动作，容量不足则断言失败；它不替被测核心决定该发什么动作，不自动输入外部成功。

三个关键边界来自真实 [`host/cases.def`](host/cases.def)：

```c
CASE(deadline_minus_one, SC_DEADLINE_POLL, 100u, 163u, FAULT_NONE)
CASE(deadline_equal, SC_DEADLINE_POLL, 100u, 164u, FAULT_DEADLINE)
CASE(deadline_plus_one, SC_DEADLINE_POLL, 100u, 165u, FAULT_DEADLINE)
```

运行入口按`Scenario`（测试情形枚举）选择准备与刺激，但**不根据生产状态计算期望分支**：预期来自这张独立表，常量由契约决定。检查“故障后仍借出”“清理失败不清哨兵”等不变量，是防止只看一个返回码漏掉副作用。

注意：`fault_is`作为普通检查函数的源码位置会在多个失败中相同，故诊断必须同时打印case和step；只有行号不能准确定位用例。当前入口遇到本条首个失败立即返回，运行全部时累计失败条数并继续下一条全新夹具，不把失败态沿用过去。

### 9.3 构建、注册和执行是三个动作

下面是本课实际`CMakeLists.txt`，未将HAL适配混入主机构建。`BATCH_SOURCE`正常指向L039生产核心；只在私有故意错误构建中覆盖它，不把覆盖参数写入用户全局配置。

```cmake
cmake_minimum_required(VERSION 3.20)
project(l040_unit_test LANGUAGES C)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)
# Deliberate reuse: both host and the F407 adapter call this SAME production core.
set(BATCH_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/../L039-host-test/core/batch.c"
    CACHE FILEPATH "Production source; override only for private fault-injection builds")
add_library(batch_core STATIC "${BATCH_SOURCE}")
target_include_directories(batch_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/../L039-host-test/core")
add_executable(unit_batch host/unit_batch.c)
target_link_libraries(unit_batch PRIVATE batch_core)
add_executable(minimal_batch host/minimal.c)
target_link_libraries(minimal_batch PRIVATE batch_core)
foreach(target batch_core unit_batch minimal_batch)
  if(MSVC)
    target_compile_options(${target} PRIVATE /W4 /WX)
  else()
    target_compile_options(${target} PRIVATE -Wall -Wextra -Werror -Wpedantic)
  endif()
endforeach()
enable_testing()
file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/host/cases.def" case_rows REGEX "^CASE\\(")
foreach(row IN LISTS case_rows)
  string(REGEX REPLACE "^CASE\\(([a-z0-9_]+),.*" "\\1" case_name "${row}")
  add_test(NAME "unit.${case_name}" COMMAND unit_batch "${case_name}")
  set_tests_properties("unit.${case_name}" PROPERTIES TIMEOUT 5)
endforeach()
```

`add_executable`产生程序目标，不代表运行了它；`enable_testing/add_test`生成测试注册，也不代表执行过；只有实际CTest/入口进程输出与退出码才是执行证据。CTest默认按程序是否成功退出判定，本文没有配置会覆盖这一语义的通过正则或预期失败属性。[S7][S8]

`minimal_batch`作为单个演示入口直接执行；正常CTest清单是`unit_batch`的33条命名用例，**没有把最小入口再算成第34条**。同进程正逆序是额外隔离核查，也不伪造为更多不同契约。

## 10. 常见错误

1. **让所有用例共享一个可变Batch。** 后一条可能靠前一条的清理才通过。使用每条局部夹具，再查正逆序结果。
2. **Fake重新实现一份发布判断。** 这会让测试绕开真实核心；本课始终编译L039同一个`batch.c`，Fake只记录动作。
3. **通过直接改内部状态建立“初态”。** 容易造出生产API无法到达的组合。先按正常启动/HT/完成路径准备，并检查前提。
4. **用实际输出生成预期。** 例如`expected_half=out.half`必然相等；期望应独立写成0/1及相应契约。
5. **只测163和165，不测164。** `>=`误改`>`后两侧都可能照常通过；恰好截止是独立验收点。
6. **测试每条独立进程通过就认定无串状态。** 进程结束清了全局状态；还应同进程重排。当前只验证正逆序，不声称证明任意排列。
7. **将零条测试、拼错名字当成功。** 核对清单数量，`--no-tests=error`，未知名字退出2。[S8]
8. **故意错误编译不过也说测试抓住了错误。** 编译失败没有走到行为断言；本课先要求故意错误副本编译成功。
9. **只看Fault码，不看借出与清样本副作用。** 清理失败时错误码正确而样本提前被清，仍违反契约。
10. **混淆DMA的TC与UART线路的TC。** 固定HAL Normal发送需要USART TC IRQ才到最终TX完成；漏IRQ不能由主机绿色补救。[S1][S4]
11. **把软件session/token当硬件身份。** 真实回调没有携带它们；必须真正排空旧硬件事件。[S4]
12. **把64ms软件窗口当物理防覆盖器。** 软件处理点、计时粒度与真实半区复用有差异；只能以实际最坏时延/余量证据作目标判断。
13. **“HAL_Init返回OK，所以时基必定正常”。** 固定版本没有转交内部InitTick失败；要检查真实tick。[S4]
14. **把F4的DMA字段/内存结论外推到全部系列。** F767、H563、H743的核对入口与具体差异见7.1；在选择具体目标和版本前不补猜测。

## 11. 调试观察点

主机先定位“输入→核心输出”哪个约定失败，目标端再定位“物理事件→适配→核心”哪个边界缺证据，不混用两种调试结论。

| 层 | 观察对象 | 期望 / 异常怎样缩小范围 |
|---|---|---|
| 测试注册 | `ctest-inventory.log`、二进制`--list` | 应与33行用例表一一对应；数量不对先修注册，不讨论生产算法 |
| 本条初态 | fixture的mode/session/half_state与ARM记录 | RUNNING/session1/0采集1空闲；失败首先看running准备步骤 |
| 刺激入口 | case/step、kind/now/session/half/token | 确认只改变本条要测的条件，不意外跨到另一个错误优先级 |
| 交接动作 | last.kind/half/token与Fake动作顺序 | 正常为ARM→TX；忙故障不应出现第二个TX |
| 截止 | tx_start_tick/window_ms、当前输入now | 100/64/164须截止；回绕例0xffffffe0/32也是64 |
| 清理反馈 | mode/session/cleanup_errors、samples[0]哨兵 | 失败不换session、不清0x4000；成功换2并清0 |
| 首错快照 | first_fault.code/tick/session与current_fault | 第二种故障不应覆盖第一现场 |
| 板端源时钟 | RCC、TIM2 PSC/ARR/CEN、HAL tick | 先证频率与启源，再找采集数据；本次未读取目标寄存器 |
| ADC/DMA2 | EXTSEL/EXTEN、OVR、NDTR、HT/TC/error标志 | 没HT/TC先查触发/地址/宽度/IRQ，而不是改核心token |
| UART/DMA1 | gState、ErrorCode、DMAT、NDTR、TCIE/TC、g_tx计数 | DMA结束无最终回调，检查USART2 IRQ及HAL调用链 [S4] |
| 板端恢复 | CEN、两stream EN、pending、ReferenceDiag计数 | 失败必须保持可诊断；不能在看见STOP动作后立即清内存 [S1][S4] |

断言失败时先保留红灯日志，再只改与契约有关的一处。没有实机时不要用手写寄存器值补成“观测记录”。

## 12. 实战实验

### 实验一：只跑一个单元，不依赖整套场景

- **操作：**运行最小入口，再用CTest过滤`^unit.ht_borrows_half0$`。
- **提交证据：**两个真实命令、退出码、单条PASS、CTest确实执行1条的记录。
- **验收：**说明Batch由谁拥有、事件由谁提供、动作由谁检查；指出未调用任何HAL。

### 实验二：把一份合同写成边界表

- **先写预期：**不运行程序，写出100→163/164/165与0xffffffe0→31/32/33的判定、动作和半区状态。
- **操作：**对照`cases.def`，分别单独执行六条边界用例；再执行`deadline_equal_done`。
- **验收：**解释为什么恰好截止的正确DONE仍不能按正常完成归还；不能仅答“源码先判断了截止”，要回到契约。

### 实验三：证明你确实没有依赖上一条用例

- **操作：**同进程正序、逆序运行，核对各执行33条；选一条恢复用例单独运行。
- **提交证据：**两份`SUMMARY`、单独运行结果、夹具创建位置。
- **验收：**指出这只检查这些顺序，并说明若另有隐藏全局硬件替身状态，还需进一步重排和检查；不要因此修改生产API或提前设计新框架。

### 实验四：让断言对选定错误真的变红

- **操作：**运行`host/regress.py`，阅读三个`red-*`与三个`repaired-*-ctest`日志。
- **验收：**每个红灯都须先成功构建、再因指定行为断言失败；能口述“哪条契约、哪次刺激、实际与期望有什么差别”。修复后完整33条通过，原生产文件指纹不变。
- **限制：**只在脚本自己的构建副本中注入错误，不编辑L039，不把故意失败加入正常绿色集合。

### 实验五：恢复是一个分阶段合同，不是重新init

- **先写预期：**F态请求清理后、清理失败后、清理成功后，各自mode/session/样本/动作是什么？
- **操作：**分别运行`cleanup_failure_keeps_loan`、`explicit_recovery_new_session`、`first_fault_preserved`。
- **验收：**能解释为什么不能调用`batch_init`把故障和借出痕迹一笔清掉；核心中的cleanup成功是适配层的承诺，不是核心自己证明abort成功。

### 实验六：目标链路证据设计（本次待做）

按8.2节先填板级清单、目标构建和布局，再规划真实观测。报告至少分开：软件契约预期、时钟标称算式、寄存器配置快照、IRQ/回调事件记录、仪器测量、错误与恢复。没有开发板时只提交实验方案和缺失条件，不提交虚构数值，不改`hardware_verified`。

## 13. 自检题

1. 为什么`batch_event`是真正被测代码，而`record_action`不是？若替身也判断半区是否完成，会发生什么？
2. 一条用例的“单一主要刺激”与“只能调用一次函数”有何不同？指出`done_wrong_token`的准备与真正刺激。
3. 从契约解释163、164、165的不同，而不是复述实现的比较符号。
4. 为什么需要`deadline_equal_done`，单测POLL边界还缺少哪种优先级交叉？
5. CTest显示33条已注册和33条已运行分别需要什么记录？未知名字为什么不能返回0？
6. CTest分别启动进程与`--all/--reverse`同进程运行各自能发现或掩盖什么？
7. 清理失败后，为什么不能把样本清0来“避免脏数据”？归还动作和真正DMA停止有什么区别？
8. 哪条真实HAL路径解释了“DMA已TC但借出不归还”？为什么漏USART2 IRQ无法靠单元测试修复？
9. 主机回绕边界通过后，可以说tick从此永不溢出、IRQ延迟已验证吗？
10. 本次哪几份记录能证明主机测试通过，哪几项硬件证据仍不存在？

**核对要点：**应出现“唯一真实核心”“每条新对象”“独立期望”“清单≠执行”“非零失败”“借出保留直到真实清理成功”“Normal DMA→USART TC IRQ”“逻辑时刻≠物理时间”。答不清哪项就回看相应代码/日志；不能因看过本页自动增加掌握度。

## 14. 面试题

### 题一：嵌入式单元测试为什么不必先模拟整颗芯片？

合格回答应先划可独立调用的行为边界，再说明输入与状态/动作契约。主机可以验证决策，但ADC模拟特性、IRQ并发和总线时序在边界之外。只说“mock所有HAL就行”缺少证据限制。

### 题二：测试全部通过，为什么仍要做一次故意错误？

通过可能因为期望与实现同源、边界缺失或实际没执行。改变指定判断后要求一个具体断言失败，可以证明该断言对这一错误敏感；不能证明测试完备。还须确认副本能编译、失败确是契约诊断、修复后回归恢复。

### 题三：怎样测试错误清理而不在主机假装真的停止DMA？

将清理是否成功作为边界外明确反馈，检查失败时不清样本/不换会话/不重新arm，成功时才过渡。硬件适配另须查返回值、EN/CEN与旧事件，主机不替它证明物理停止。

### 题四：为什么有session/token仍可能出现陈旧回调归错批次？

软件输入表可以带明确旧号，真实HAL回调却没有自带该软件身份。适配层若把旧IRQ读成当前ticket，核心无法还原来源。必须依赖真实停源、abort、清外设标志与pending的顺序证据，不能把软件编号当物理标签。[S1][S4]

## 15. 延伸思考

- 当前33条没有穷尽故障优先级。如果旧session与截止同时发生，你会怎样先写合同再写新用例，而不是直接照源码顺序给答案？
- 如果采样率从1kHz改为2kHz，半区窗口与串口预算怎么重算？要新增哪条参数一致性检查，才能避免HAL配置改变而核心仍用64ms？这不等于本课已经验证2kHz硬件。
- 如果一个测试只检查`current_fault`正确，却没有检查样本是否被提前清除，它错过了哪类副作用？设计一条最小断言说明。
- 后续真实IRQ/RTOS竞争实验应记录哪些事件时刻，才有资格讨论最坏时延？cache/DMA实验应怎样区分“核心正确归还”和“CPU/DMA看到了同一份数据”？具体实现留到对应阶段。

## 16. 本节总结

本课只推进了两件事：

1. **单元边界与用例隔离：**主机和板端复用同一个真实核心；每条测试自己创建并持有状态，通过正常API准备初态，Fake只记录边界外动作。
2. **边界用例到可诊断回归：**从独立合同写有名称的边界/错误输入，检查动作和副作用；核对实际执行数量，保留非零红灯、修复绿灯和顺序隔离证据。

本次真实主机证据是：最小入口运行、33条正常用例、同进程正逆序各33条、未知名字拒绝、三个可编译故意错误被对应断言抓住，以及各自修复后的完整回归。它不包含目标交叉编译、烧录或测量，硬件验证保持false。

硬件轨道不是省略项：本文给出了固定来源/版本、F407完整时钟与复位链、CubeMX配置、实际复用的完整HAL文件、初始化/回调/错误路径、LL/寄存器对照和待执行目标清单。**有参考实现与有硬件验证证据，是两种不同状态。**

## 17. 下一步

课程路线的下一阶段是`rtos-concurrency`（FreeRTOS与并发），从`task`（任务）主题开始；这是路线说明；Reviewer 仅在审核通过后按路线更新学习状态，不在本次创建第二篇课。

进入下一阶段前，先能独立解释一条红灯诊断、补写一个不依赖上一条用例的新边界测试，并明确其不能证明的硬件条件。后续分别在`isr`、`race-condition`讨论中断/竞争，在`cache`、`dma-coherency`、`bus-matrix`和系列比较专题补真实硬件证据。

Teacher 阶段未修改`config/learning-state.toml`、掌握度、既有课程、`.ai/`、`templates/`、`review/`或`interview/`。Reviewer 在实际通过后仅更新本课审查状态和路线进度，不改变`[mastery]`；本次审查记录位于`.state/runs/20261021-174440304-34624/review.md`，结构化结论位于同目录`review-result.json`。Interviewer（面试者）产物仍由后续阶段生成，不在授课或审查阶段虚构。

## 18. 参考资料

访问/复读日期统一为**2026年10月21日**。以下是本课固定参考版本，不主张它们永远是最新版本。S1-S7及S15重新读取了先前课程保存的官方内容缓存和相关原文；S9/S10/S12/S13/S16本次从ST官方HTTPS下载；各系列固件包读取了本机实际`package.xml`及对应HAL/LL/CMSIS文件。S8依据当前安装的官方CTest 4.4.3帮助与实际执行核对。缓存/包文件指纹和精确阅读位置见`evidence/source-audit.json`；缓存不作为第三方完整源码提交。

文中[S编号]与下面条目以及`lesson.json.sources`顺序一一对应；URL、文档ID、版本、访问日和第一方标记全部在元数据中。ST来源满足仓库第一方域政策；CMake虽是工具官方文档，其`primary=false`按本仓库`primary_domains`计数政策记录，不用来替代ST硬件第一方证据。

- **[S1] ST-RM0090 — STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 reference manual**。Rev 22, May 2026; F407 scope; sections 3.5, 7, 10 (tables 43/44), 13 (table 68), 18, 30。
  https://www.st.com/resource/en/reference_manual/dm00031020.pdf

- **[S2] ST-DS8626 — STM32F405xx / STM32F407xx datasheet**。Rev 12, March 2026; HSI/PLL/electrical/ADC limits and package boundary。
  https://www.st.com/resource/en/datasheet/stm32f407vg.pdf

- **[S3] ST-UM1725 — Description of STM32F4 HAL and low-layer drivers**。Rev 8, March 2023; handles/initialization/callback model; exact implementation checked in fixed CubeF4。
  https://www.st.com/resource/en/user_manual/dm00105879.pdf

- **[S4] ST-STM32CUBEF4 — STM32CubeF4 official software versions and installed package**。Base FW.F4.1.28.0 + patch FW.F4.1.28.3; package.xml, HAL/LL/CMSIS read; no target compilation。
  https://www.st.com/en/embedded-software/stm32cubef4.sw-versions.html

- **[S5] ST-UM1718 — STM32CubeMX for STM32 configuration and initialization C code generation**。Rev 51, May 2026; sections 4.5, 4.5.13/14, 4.10, 6。
  https://www.st.com.cn/resource/en/user_manual/dm00104712-stm32cubemx-for-stm32-configuration-and-initialization-c-code-generation-stmicroelectronics.pdf

- **[S6] ST-STM32CUBEMX — STM32CubeMX official software versions**。Fixed reference branch STM32CubeMX-Win 6.18.1; official cached page contains version; GUI not run。
  https://www.st.com/en/development-tools/stm32cubemx.sw-versions.html

- **[S7] CMAKE-ADD-TEST — CMake add_test command reference**。Documentation branch v4.4; installed CMake 4.4.3 help checked; enable_testing/add_test and nonzero failure behavior。
  https://cmake.org/cmake/help/v4.4/command/add_test.html

- **[S8] CMAKE-CTEST — CTest command-line manual**。Documentation branch v4.4; installed CTest 4.4.3 help checked; --show-only=json-v1/--output-on-failure/--no-tests=error。
  https://cmake.org/cmake/help/v4.4/manual/ctest.1.html

- **[S9] ST-RM0410 — STM32F76xxx and STM32F77xxx reference manual**。Rev 5, July 2024; sections 8.1/8.2/8.3.6, pages 248/253; F767 scope。
  https://www.st.com/resource/en/reference_manual/dm00224583.pdf

- **[S10] ST-DS11532 — STM32F765xx / F767xx / F768Ax / F769xx datasheet**。Rev 9, July 2025; F767ZI reference choice; Cortex-M7/L1 cache feature scope。
  https://www.st.com/resource/en/datasheet/stm32f767zi.pdf

- **[S11] ST-STM32CUBEF7 — STM32CubeF7 official software package**。Base FW.F7.1.17.0 + patch FW.F7.1.17.3; actual package.xml and DMA Init.Channel read。
  https://www.st.com/en/embedded-software/stm32cubef7.html

- **[S12] ST-RM0481 — STM32H523/533xx, H543/553xx, H562xx and H563/573xx reference manual**。Rev 5, July 2026; sections 8/9/16, pages 390/407/677-679; H563 scope。
  https://www.st.com/resource/en/reference_manual/rm0481-stm32h52333xx-stm32h56263xx-and-stm32h573xx-armbased-32bit-mcus-stmicroelectronics.pdf

- **[S13] ST-DS14258 — STM32H562xx and STM32H563xx datasheet**。Rev 6, May 2025; H563ZI reference choice; Cortex-M33/TrustZone and external-memory data-cache scope。
  https://www.st.com/resource/en/datasheet/stm32h563zi.pdf

- **[S14] ST-STM32CUBEH5 — STM32CubeH5 official software package**。FW.H5.1.5.0; actual package.xml and DMA Request/SrcInc/DestInc/TransferEventMode/GPDMA requests read。
  https://www.st.com/en/embedded-software/stm32cubeh5.html

- **[S15] ST-RM0433 — STM32H742, STM32H743/753 and STM32H750 reference manual**。Rev 9, October 2026; sections 15/16/17, pages 638/639/672/695/696; H743 scope。
  https://www.st.com/resource/en/reference_manual/dm00314099.pdf

- **[S16] ST-DS12110 — STM32H742xI/G and STM32H743xI/G datasheet**。Rev 11, January 2026; H743ZI reference choice; Cortex-M7 cache and D1/D2/D3 scope。
  https://www.st.com/resource/en/datasheet/stm32h743zi.pdf

- **[S17] ST-STM32CUBEH7 — STM32CubeH7 official software package**。Base FW.H7.1.12.0 + patch FW.H7.1.12.1; actual package.xml and DMA Init.Request/DMAMUX request declarations read。
  https://www.st.com/en/embedded-software/stm32cubeh7.html
