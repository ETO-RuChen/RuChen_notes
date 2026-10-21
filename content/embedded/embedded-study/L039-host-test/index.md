+++
title = "主机测试——受控事件验证嵌入式批次交接"
date = "2026-10-21T16:00:03+08:00"
lastmod = "2026-10-21T16:00:03+08:00"
summary = "能够为已学的 STM32F407xx 采集到发送的批次交接划定可在主机运行的测试边界，用可控回调事件与故障序列、独立预期结果检验所有权、背压和恢复，同时将主机逻辑证据与 CubeMX/HAL/LL/寄存器参考实现及待执行的实机验证严格分开。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 39
tags = ["主机测试", "受控事件", "独立测试预言", "STM32F407xx", "DMA批次交接", "证据边界"]
source_ids = ["ST-RM0090", "ST-DS8626", "ST-UM1725", "ST-STM32CUBEF4", "ST-UM1718", "ST-STM32CUBEMX", "CMAKE-ADD-TEST"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L039"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 39 课：主机测试——受控事件验证嵌入式批次交接

> 阶段：调试与验证（`debugging-verification`）；主题：主机测试（`host-test`）。建议用时 60 分钟，代码可分两次精读，但全文仍是一节课。
>
> 证据状态（2026-10-21）：本课主机程序确实构建并运行；完整结果见第 8 节及 `evidence/`。STM32F407 代码仅做过主机编译器的语法检查，**参考实现，待目标工程编译；未烧录、未上板、未测量**。`hardware_verified=false`，`lesson.json.status=reviewed`；本次 Reviewer 已审查通过，记录见 `.state/runs/20261021-160003414-34624/review.md`。课程进度按路线推进，不提高掌握度。

## 1. 本节目标

**唯一核心目标：**能够为已学的 STM32F407xx 采集到发送的批次交接划定可在主机运行的测试边界，用可控回调事件与故障序列、独立预期结果检验所有权、背压和恢复，同时将主机逻辑证据与 CubeMX/HAL/LL/寄存器参考实现及待执行的实机验证严格分开。

只引入计划中的两个新核心概念：

1. **受控事件边界与可重复主机测试**：把异步到达的外设回调，变成测试者逐条提供的输入；每一步都能检查状态和请求动作。
2. **独立测试预言与证据边界**：先根据交接约定写预期结果，再检查实现；清楚说明每条证据证明什么、不证明什么。

验收时，你应能写出一条正常轨迹、一条错误轨迹及它们的预期结果，运行程序，说明失败在哪一步，并指出还缺什么硬件证据。这里不引入测试框架、运行时接口注入、驱动架构或 RTOS（实时操作系统）。

## 2. 它解决什么问题

这里 TIM2 是定时器2，ADC1 是模数转换器1，USART2 是通用同步/异步收发器2（本例用异步UART，即通用异步收发器模式）。L031/L032 的问题仍然是：采集端和发送端能否在有限缓冲区上正确交接？不是换一个更容易的字符串函数来测试。

```text
TIM2 更新触发 → ADC1 → DMA2 循环写 samples[128]
                         A = [0..63]，B = [64..127]
HT：A 完成，DMA 将写 B → 请求 USART2 TX DMA 借出 A
TX 完成：归还 A
TC：B 完成，DMA 将回到 A → 请求 USART2 TX DMA 借出 B
忙、乱序、过期、错误：先停止采集源这个物理副作用，再由主循环清理
```

如果只是不断上电观察串口，很难稳定制造“TX 完成恰好晚到 1 个 tick”。也很难在一次偶然成功后回答：重复回调会不会再次归还？清理失败后会不会错误重启？

本课把两个问题拆开：

- **决策问题**：给定事件次序，代码应借出哪一半、归还哪一半、何时停源？普通电脑可以执行这一段真实 C 逻辑。
- **硬件兑现问题**：事件有没有真的发生、IRQ 有没有到达、DMA 是否指向正确 SRAM、串行线何时发完？必须回到参考手册和目标板。

最小闭环不是打印“测试成功”，而是 `HT(A) → 请求发送 A → TX_DONE(A,1) → A 变 FREE`，且每一步有明确断言。现在可先按第8.1节运行 `--minimal` 成功组，再回来给错误轨迹写预言；不必先读完整硬件附录。第 9 节的主机逻辑和板端适配使用**同一个** `core/batch.c`；Fake 不得重写一份决策代码。

## 3. 必要前置知识

已授前置是 C11 整数/指针/存储期/编译与 CMake、定时器/ADC/DMA/UART、时钟树、HAL/LL 对照、L031/L032 批次交接，以及 L033–L038 的调试证据方法。已授不等于已经掌握。

开始前口头回答：

1. HT 为什么只能宣布 A 完成，不能同时宣布正在写的 B 可发送？
2. 为什么 DMA 启动成功不等于 TX 完成，为什么忙时不能无限等待？
3. 为什么停止 TIM2 之后，还需要停止 ADC/DMA、清除旧中断，再显式恢复？

答不出时，先复习上述交接图和 L032 第 4、6 节；不要用测试术语掩盖所有权上的空缺。本课仅用固定数组、结构体、显式函数调用和 C11 标准库；`memset` 按字节清零，`memcpy` 复制固定长度，`memcmp` 比较两段已初始化内存。`int main` 是 C 程序入口要求，不是公开设备接口。

## 4. 核心原理

### 4.1 先写约定，再写代码

下文 ARM 表示“装载采集DMA并启源”的动作名，不是处理器架构名；CLEAN 是清理动作；RUNNING/FAULT 分别为运行/故障状态。下面是本课人为选定、可被反驳的交接约定，不是假装芯片自动保证的软件规则。

| 条目 | 独立写定的预言 |
|---|---|
| 启动 | 清零状态和样本；A 为 CAPTURE，B 为 FREE；先请求 ARM，成功才进入 RUNNING |
| 发布 | HT 必须对应 A，TC 必须对应 B，且二者交替；仅完成半区变 TX，另一半开始 CAPTURE |
| 发送 | 一个固定发送槽；一次发布最多产生一次 TX 动作；启动成功也不能释放半区 |
| 归还 | RUNNING 中仅活动槽的同会话、同半区、同 token 完成可归还一次；完成不触发下一次发送 |
| 截止 | 从发布输入的 tick 开始，活动槽只接受 `elapsed < window_ms`；等于或超过都先故障，不归还 |
| 故障 | 第一项外部动作是 STOP_SOURCE；不发送第二批，不自动清空所有权；首次故障快照不被后来的错误覆盖 |
| 恢复 | 只能显式请求 CLEAN；清理失败仍 FAULT；成功才清缓冲区、换会话、ARM；重新 ARM 失败仍停源 |

`token` 是同一会话内单调增加的批次编号，不是第二套协议。`session` 是一次启动到故障的会话编号。两者都不允许绕回零后继续使用：耗尽时关闭会话。它们服务已学的代次检查，不额外引入架构机制。

### 4.2 输入、状态、输出分别是什么

```text
调用者提供 BatchEvent(kind, now, session, half, token)
    ↓
batch_event(&调用者持有的状态, event, &action)
    ↓
修改 Batch 所有权 / 首错快照，并输出 BatchAction
    ↓
主机：固定 Fake 记录动作，提供启动/停止/清理返回值
板端：HAL 执行动作，把真实完成/错误回调送回同一个入口
```

| 核心对象 | 在哪里定义 | 谁持有 | 谁提供输入/结果 | 调用如何流动 |
|---|---|---|---|---|
| 决策状态及双半区 `Batch` | `core/batch.h` | 主机测试的 `Fixture.s`；板端静态 `g_batch` | 测试事件或 HAL 回调 | 事件入口 → 更新状态 → 请求动作 |
| 输入 `BatchEvent` | 同一头文件 | 每次调用的栈变量 | 主机按表构造；板端回调封装 | 只借用至本次调用结束，不保存指针 |
| 输出 `BatchAction` | 同一头文件 | 调用者的局部对象；板端另存活动发送票据（ticket） | 真实决策函数生成 | Fake 或 HAL 执行，返回成功/错误 |
| 独立预期 | 本节契约和第 6 节矩阵 | 测试作者 | 在实现之前写定 | 检查状态、动作数量/顺序、数据和退出码 |
| 首次故障 `first_fault` | `BatchSnapshot` | `Batch`，直到重新初始化整个实例 | 决策入口只写第一次 | 恢复不抹去；`current_fault` 表示当前会话 |

调用者显式传入对象和事件，不靠全局 HAL，也没有函数指针表或运行时装配框架。`batch_init`只能在硬件静止且无未归还使用者时初始化新实例，不能拿它替代故障恢复。`Batch` 不可被并发无保护访问；“纯 C 文件”不等于“自动线程安全”。

### 4.3 状态与时间边界

- `HALF_CAPTURE`：采集写者拥有该半区；不得启动发送。
- `HALF_TX`：发送读者拥有已完成半区；应用不得修改，采集也不得回绕重用。
- `HALF_FREE`：无活动读写者，可以在下一边界交还采集。

“完成待领取”在本例中只是发布函数内部的瞬间：我们没有额外待发送队列，立刻尝试唯一发送槽；失败便停源。这不等于所有项目都不需要 READY 状态。

计时使用 `uint32_t` 毫秒 tick。`(uint32_t)(now - publish_tick)` 可以处理一次计数回绕；前提是按时间顺序调用、窗口小于 `2^31`、服务间隔也小于 `2^31` 毫秒，不允许让事件失联一个完整计数周期。**同一个比较既用于 POLL，也用于 TX_DONE**，否则完成中断与主循环可能在截止点作出相反判断。

故障判定会先在内存冻结首次原因，再请求 STOP_SOURCE；这里的“先停源”指**第一个硬件副作用必须是停 TIM2，而不是先清缓冲区或先重启 DMA**。STOP 的返回值单独记在 `stop_ok/stop_errors`，不把原来的根因改写成停止失败。故障后不处理归还；清理和恢复不在 IRQ 内执行。

## 5. 关键术语与直观模型

| 术语 | 本课中的准确含义 |
|---|---|
| 主机测试（host test） | 在普通电脑上构建、执行与目标逻辑共享的 C 代码，不执行 MCU 指令或外设 |
| 被测对象（system under test） | `core/batch.c` 的交接决策，不是 Fake，也不是整个 MCU |
| Host Fake（主机替身） | 固定的动作执行替身；复制发送数据、记录动作、返回人为指定错误，不模拟芯片时序 |
| 测试夹具（fixture） | 测试中创建并清零 `Batch`、日志数组和可控错误码的辅助对象 |
| 断言（assertion） | 对已写定预言的检查；本课 CHECK 即使定义 NDEBUG 也不会消失 |
| 测试预言（test oracle） | 独立于实现分支写出的预期行为，不是读取实现结果再把它当“正确答案” |
| 故障注入（fault injection） | 主动输入重复/过期事件，或令动作返回错误，检验错误路径 |
| 覆盖矩阵 | “场景—输入—预期—对应断言”的表，不是代码覆盖率百分比 |
| HAL（Hardware Abstraction Layer，硬件抽象层） | ST 的外设驱动接口；本例板端用它兑现动作 [S3][S4] |
| LL（Low Layer，底层驱动） | 更接近寄存器的驱动层；本课用关键寄存器解释 HAL，不额外混用两套初始化 [S3] |
| IRQ（Interrupt Request，中断请求） | 硬件送往内核的中断请求；函数被主机调用不是 IRQ 到达证据 |
| DMA（Direct Memory Access，直接存储器访问） | 按请求搬运数据的硬件；HT/TC 分别是半传输/传输完成 [S1] |
| NVIC / pending | 嵌套向量中断控制器 / 待处理中断状态；负责中断分发，不等于外设事件本身 |
| GPIO / FIFO / burst | 通用输入输出 / 先进先出缓冲 / 突发搬运；在参考配置中分别约束引脚和DMA数据搬运方式 |
| 背压 | 消费者来不及时限制上游；本课策略是停采集源，而不是覆盖或无界排队 |

## 6. 从输入到结果的完整流程

### 6.1 最小成功轨迹

先不看实现，按第 4 节手算下表；窗口 64 ms，输入时间是**测试者给定的逻辑时间**。

| 输入 | 预期状态 A/B | 预期动作、额外断言 |
|---|---|---|
| START，ARM 返回成功 | CAPTURE / FREE | ARM 一次；会话 1；无 TX |
| HT(A)，t=64 | TX / CAPTURE | TX(A,token=1)；复制出的 128 字节等于事先写好的 64 个测试样本 |
| POLL，t=70 | TX / CAPTURE | 无新动作，A 不能提前 FREE |
| TX_DONE(A,1)，t=76 | FREE / CAPTURE | 活动槽清零；不再次 TX |
| TC(B)，t=128 | CAPTURE / TX | TX(B,2) 一次 |
| TX_DONE(B,2)，t=140 | CAPTURE / FREE | 只归还 B |
| HT(A)，t=192；TX_DONE(A,3)，t=204 | FREE / CAPTURE | 重用的是新批次 A，token 必须为 3；仍无故障 |

Fake 对 A 写入固定模式 `0x100+i`，测试的 `expected[]` 独立持有同一预定样本序列，检查数据起点和完整 128 字节。此检查只证明主机传递了预期字节，不证明 ADC 的电压、UART 的端序协议或接收端解码。B 的测试数据可以为零，它仍必须遵守独立的所有权轨迹。

### 6.2 故障与边界覆盖矩阵

下列场景均对应 `host/test_batch.c` 中同名测试，真实主机输入及观察值记录在 `evidence/host-test.log` 的 TRACE 行。故障优先级固定为：会话错误 → 活动槽超期 → 具体事件错误；故障后新事件不改变首错。

| 测试名称/输入 | 预先写定的结果 | 必须检查的反例 |
|---|---|---|
| `TC_before_HT`：初始直接 TC | ORDER；动作 ARM,STOP；从未 TX | 未完成 A/B 不得随意借出 |
| `duplicate_HT`：HT64、HT65 | ORDER；仅一次 TX，然后 STOP | 重复发布不得再次发送 |
| `busy_before_deadline`：HT64、TC127 | BUSY；A 仍 TX；无第二次发送 | 不能因为收到另一半回调就覆盖发送槽 |
| `deadline_minus_one`：HT64、DONE127 | 成功归还；仍 RUNNING | 不能把严格小于期限也判为超期 |
| `deadline_equal`：HT64、DONE128 | DEADLINE；A 不归还；STOP | 等号是拒绝侧，不是成功侧 |
| `deadline_plus_one`：HT64、POLL129 | DEADLINE；STOP | 只在完成回调检查超期不够 |
| `duplicate_completion`：DONE76、DONE77 | 第二次 CALLBACK 故障，无二次归还/发送 | 已 FREE 不得重复归还 |
| `wrong_half / wrong_token / unexpected_completion` | CALLBACK；不释放活动槽 | 任意“完成”不得当成当前批次完成 |
| `TX_start_failure`：令 TX 返回错误 | START；TX 请求后 STOP，半区仍借出直到清理 | 不能把“没启动成功”误当成“可以重用” |
| `stop_failure_then_explicit_recovery` | 原因 DEVICE；stop_ok=0、stop_errors=1；失败清理仍 FAULT，成功清理才 ARM | 停止失败不抹掉首错，不自动恢复 |
| 同一场景恢复后旧 session 的 DONE | STALE；没有归还；历史首错不变 | 旧会话完成不得影响新会话 |
| `arm_failure`：ARM 返回错误 | START；ARM,STOP；未进入 RUNNING | 初始化/启动结果必须处理 |
| `tick_wrap / tick_wrap_equal` | 发布在 UINT32_MAX−31；DONE31 成功、DONE32 超期 | 不能用普通 `now >= absolute_deadline` 漏掉回绕 |
| `invalid_event / token_exhaustion / command_guards` | 非法事件/编号耗尽关闭；运行中 START/RECOVER 返回 0 且无动作；非法窗口初始化返回 0 | 错误命令不能偷偷重置活动实例 |

`TC127` 是为了在截止之前强制制造发送忙的**对抗输入**，不是声称 1 kHz 硬件会在第 127 ms 正常完成 128 个样本。正常 TC128 若 A 尚未归还，按优先级报告 DEADLINE。测试既应遵守真实正常轨迹，也应主动检验边界外输入。

### 6.3 怎样避免“实现自己证明自己”

不写 `expected = s.expected_half` 再检查 `actual == expected`。A/B 顺序、固定 token 1/2/3、具体 tick 127/128/129、预定动作数量来自上面的契约。我们同时检查状态、动作顺序、返回结果和数据，不只看 Fake 的日志长度。

本课再做两个很小的判定力检查：仅在 `build/mutations/` 中复制生产文件，把 `>=` 错改为 `>`，或删掉 token 检查。完整测试必须使两份错误副本都以断言失败退出。这说明**这两类已植入错误**可被捕获，不说明测试能抓住所有错误，更不是覆盖率 100%。测试作者也可能把整个契约理解错，仍需独立审查和硬件兑现检查。

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

正文只深入“受控交接事件怎样被独立判定”。下面的地图交代其上方还存在什么验证问题，不把名称当掌握证明。

| 层级 | 能力、原理与信号/数据/中断路径 | 配置入口与本课/后续落点 |
|---|---|---|
| 基础 | 单通道定时采样；更新 TRGO 触发 ADC，DMA 按半字写数组；HT/TC 经 IRQ 发布半区，TX 完成归还 | 本课 CubeMX 表和参考代码；Fake 重放逻辑事件 [S1][S3] |
| 进阶 | 控制消费者赶不上时的背压；错误/超期先请求停源，前台完成 abort 后才换会话 | 本课故障矩阵；下一主题 `unit-test` 整理夹具和回归组织 |
| 高级：真实并发 | IRQ 可被延迟或嵌套，真实事件可能在临界区期间积压；必须测最坏延迟、停止时间和重入边界，而非把主机调用当并行执行 | NVIC 优先级、短临界区、硬件时间戳；调试方法复用，性能阶段深入；本课不证明最坏执行时间 |
| 高级：更复杂搬运 | F4 硬件双缓冲通过 M0/M1 地址和当前目标在缓冲区间切换；多通道 ADC 每次触发得到一个序列；它们改变发布粒度，但不取消重用期限 | DMA_SxCR.DBM/CT、M0AR/M1AR、ADC sequence；需另立前置充分的专项实验；本课 circular（循环模式）双半区不是硬件DBM（双缓冲模式） [S1] |
| 跨外设 | TIM2 控制“何时采”，ADC 产生值，DMA2 写内存，USART2 的 TX 请求让 DMA1 读已完成半区；各自 IRQ 不天然携带会话编号 | 完整链路见下文；后续故障隔离主题分析一个环节失败如何限制传播 |
| 系列差异 | 保留所有权/截止/首错契约；对每个具体新目标重查请求路由、内存可达性、缓存、安全和时钟，不把 F4 配置直接复制 | F7/H5/H7 表只列待核对项，未实现它们的驱动；缓存与 DMA 一致性留到性能阶段 |

| 迁移目标 | 必须取得的对应第一方资料 | 迁移时逐项提出的问题；本课不作目标特性断言 |
|---|---|---|
| F4 / STM32F407xx | 本课 RM0090、DS8626、UM1725 与固件包 | 已具体选定 Stream0/Ch0 和 Stream6/Ch4；DMA 缓冲区不得进入 F407 CCM（内核紧耦合存储器） [S1][S2] |
| F7，具体料号尚未选择 | 该料号参考手册、数据手册、CubeF7 版本、适用内核手册 | 是否有 CPU 数据缓存，目标 DMA 能访问哪些 RAM，若有缓存由谁维护？重新核对通道映射、HAL 完成/abort 语义 |
| H5，具体料号尚未选择 | 该料号参考手册、数据手册、CubeH5 版本、适用内核手册 | DMA 类型/请求选择/描述符是否不同？是否启用安全分区，缓冲区和 DMA 的安全属性谁拥有？ |
| H7，具体料号尚未选择 | 该料号参考手册、数据手册、CubeH7 版本、适用内核手册 | 哪个 DMA 能跨哪些存储器/时钟域？是否需要缓存维护、独立外设内核时钟？重新推导带宽、延迟与停止链 |

以上后续检查没有填入未经检索的新系列寄存器值，也没有假定每个系列成员能力完全相同。

### 7.2 参考目标与时钟/复位链

**目标边界：**仅 STM32F407xx；用 STM32F407VG 数据手册核对器件族，不假定用户有某块开发板。手册是 RM0090 Rev 22（2026-05）、DS8626 Rev 12（2026-03）、UM1725 Rev 8（2023-03）。本次新读取官方 PDF，而不是继承旧课程的访问日期。[S1][S2][S3]

**固件/生成器边界：**本次实际只读核对本机 `STM32Cube_FW_F4_V1.28.3/package.xml`：Release 为 FW.F4.1.28.0，Patch 为 FW.F4.1.28.3；官方版本页也把基包与 Patch 分列。HAL UART/ADC/DMA/TIM/RCC 源文件仅用于阅读、记录 SHA-256，没有复制进课程。生成器参考选 **STM32CubeMX 6.18.1**，其版本由官方版本页核对，参数概念以 UM1718 Rev 51（2026-05）为准；本次未运行 CubeMX，没有声称生成过 `.ioc`。CubeMX2 是另一产品分支，不能把其版本号当成 CubeMX 6.x。[S4][S5][S6]

参考代码选择内部 HSI（高速内部振荡器）作为源，因此不猜外部 HSE（高速外部振荡源）的晶振值。PLL 是锁相环，VCO 是压控振荡器；SYSCLK 是系统时钟，HCLK 是AHB总线时钟，PCLK1/2 是APB1/2外设总线时钟；AHB/APB是片上总线层级。Flash表示闪存。以下全是**配置下的标称推导**，不是频率测量：[S1][S2]

```text
HSI = 16 MHz → PLLM=16 → VCO 输入 1 MHz → PLLN=336 → VCO 336 MHz
                                            ├ PLLP=4 → SYSCLK 84 MHz
                                            └ PLLQ=7 → 标称 48 MHz；本课不用其证明 USB 合规
SYSCLK → AHB /1 → HCLK 84 MHz，DMA1/2 总线访问在此时钟树下工作
HCLK   → APB1 /2 → PCLK1 42 MHz
                    ├ TIM2：该目标 APB 分频不为 1 时，定时器输入为 2×PCLK1 = 84 MHz
                    └ USART2：波特率基准 PCLK1 = 42 MHz
HCLK   → APB2 /2 → PCLK2 42 MHz → ADC common prescaler /4 → ADCCLK 10.5 MHz
HAL tick：HCLK 下 1 ms SysTick，时钟切换后 HAL 按新 HCLK 配置
```

必须用 RM0090 的 **F405/407 第 7 章**，不要把第 6 章 F42/F43 的专用时钟字段套过来。代码选电压调节 Scale2，要求事先确认供电在 2.7–3.6 V，FLASH_LATENCY_2 对应这一电压区间下的 84 MHz；`supply_mv` 是调用者提供的板级事实，不是固件测量或替电源作保证。模拟供电、参考电压、输入范围和源阻抗还须另外核对。[S1 §3.5、§7][S2 §6]

时序代入：

```text
TIM2：PSC=83，ARR=999，向上计数
f_counter = 84,000,000 / (83+1) = 1,000,000 Hz
f_TRGO    = 1,000,000 / (999+1) = 1,000 Hz；周期标称 1 ms
ADC：12 bit，84 cycles 采样 + 12 cycles 转换
T_conversion ≈ 96 / 10,500,000 = 9.143 us（不含触发同步延迟，不替代模拟建立时间验证）
半区：64 个样本 → T_half = 64 / 1000 = 64 ms
USART2：115200，8 数据位、无校验、1 停止位，加 1 起始位 → 10 bit/byte
理想发送时间 = 128 byte × 10 / 115200 ≈ 11.111 ms
所选HAL包的过采样16宏对42 MHz/115200的计算结果为BRR=0x16C（除数364），名义波特率约115384.62
对应发送时间约11.093 ms；这是主机求值/算术推导，不是目标寄存器读值或频率实测
```

HAL 的整数宏经过中间取整，不一定等于把理想除数一步四舍五入；本次实际用固定包头文件在主机求值，记录在 `evidence/hal-brr-host-evaluation.log`。HSI的实际误差及双方波特率容差仍须核对。[S4：`stm32f4xx_hal_uart.h` 的 UART_BRR_SAMPLING16]

84 cycles 是本课参考选择，不表示任意传感器阻抗下都充分采样。128 的 ADC DMA Length 表示**128 次半字传输**；UART DMA 的 Size=128 表示**128 字节**，二者不能互换。[S1 §13、§30][S2 §6.3.21][S3][S4]

静态预算应写成：

```text
发布 IRQ 延迟 + 启动 TX 时间 + 实际线速时间 + 完成 IRQ 延迟 + 抖动余量 < 64 ms
边界 IRQ 最坏延迟 + 停 TIM2 的时间 < 下一次采样触发间隔（标称 1 ms）
```

约 52.9 ms 的理想差额不是已证实的安全余量。代码中的 `window_ms=64` 从**回调输入 tick**开始计数；它不是硬件绝对时间，也没有消除 SysTick 量化、IRQ 积压或在途 ADC 转换。若发布已延迟，逻辑 deadline 也可能相对真实重用边界偏后。只有目标测量给出上界，或按该上界缩短逻辑窗口/使用硬件时间基后，才能声称满足重用期限。本参考不能保证任意长关中断时仍不发生 DMA 覆写；故障前可能已经发出一部分字节，停源不能撤回它们。

| 对象 | 门控与复位 | 最终时钟/职责 |
|---|---|---|
| PWR / Flash | PWR 时钟、VOS、FLASH_ACR.LATENCY；先满足供电/等待周期再升频 | 约束 CPU 可用频率，不是外部晶振证据 |
| GPIO | 按选中 GPIOx 开 AHB1 时钟；不全局复位 GPIO，避免破坏调试脚 | ADC 脚模拟模式，TX 脚复用模式；实际引脚由板级选择给出 |
| DMA1/2 | AHB1ENR、AHB1RSTR | 总线与内存搬运；初始化时复位整个控制器，只限独占参考工程 |
| TIM2 / USART2 | APB1ENR、APB1RSTR | TIM2 输入 84 MHz，USART2 波特率基准 42 MHz |
| ADC1 | APB2ENR，ADC 共享复位域 | PCLK2 42 MHz、公共分频 /4；复位域不能在其他 ADC 活动时擅自使用 |

参考工程独占这些外设/复位域。在既有产品中集成前，必须重新核对所有者；不能为了初始化本例而复位正在被其他代码使用的 DMA 控制器。[S1 §7、§10]

### 7.3 CubeMX、HAL、LL 与寄存器对照

#### CubeMX 6.18.1 配置清单（本次未操作 GUI）

| 页面/对象 | 参考值 | 板级或版本待核对项 |
|---|---|---|
| MCU / Pinout | 选实际 STM32F407 订货号和封装；本例不默认某块开发板 | ADC1 外部通道及其 GPIO、USART2_TX 引脚及复用编号、SWD（串行线调试接口）保留；按 DS8626 和原理图确认 |
| RCC / Clock | HSI；PLL 16/336/4，Q7；AHB/1，APB1/2，APB2/2 | 不启用未经确认的 HSE；确认供电、Flash 等待周期 |
| TIM2 | Internal Clock；PSC83、ARR999；Up；AR preload Enable；TRGO=Update；不启用 TIM2 update IRQ | 启动顺序中不得在 ADC 已 armed 后随意产生 UG 软件更新事件 |
| ADC1 | 单rank（一次序列中的转换次序）、12 bit、右对齐；单次序列；外触发 TIM2 TRGO rising；continuous conversion Disable；DMA continuous requests Enable；ADC prescaler /4；sampling84 | 外部通道、模拟电压/源阻抗；采样时间不是“通用正确值” |
| ADC1 DMA | DMA2 Stream0 / Channel0；peripheral→memory；circular；半字/半字；MINC 开；PINC 关；priority high；direct/FIFO disabled；single burst | RM0090 Rev22 表44；长度128个传输单位 [S1] |
| USART2 | TX only；115200、8N1；no flow control；oversampling16 | 对端电压、共地、实际 TX 引脚及 AF；本课仅发送原始样本，不引入新传输协议 |
| USART2 TX DMA | DMA1 Stream6 / Channel4；memory→peripheral；normal；字节/字节；MINC 开；priority medium；FIFO disabled | RM0090 Rev22 表43 [S1] |
| NVIC | DMA2_Stream0、DMA1_Stream6、ADC、USART2 均启用；同抢占优先级5，sub0；SysTick15；priority group4 | DMA TC 后还需要 USART IRQ；真实延迟与停止上界必须测量 |
| Code generation | 固件包基包1.28.0+patch1.28.3，记录实际生成版本和工程工具链 | 本课手写适配已实现初始化/IRQ，和生成代码二选一或逐项人工合并，禁止重复定义/二次 MSP 初始化 |

CubeMX 的字段概念与代码生成边界来自 UM1718；具体寄存器与请求映射必须回到本目标手册，不能仅凭 GUI 截图。[S1][S5][S6]

#### 初始化字段、句柄和生命周期

- `g_batch`、`g_adc/g_uart/g_tim` 和两个 DMA 句柄都是文件内静态对象，生存到固件结束；句柄不是栈上的临时对象。
- ADC 的 `ClockPrescaler/Resolution/SamplingTime` 决定转换时序；`ExternalTrigConv/Edge` 选择触发；`ContinuousConvMode=DISABLE` 避免“一次触发后自由连续跑”；`DMAContinuousRequests=ENABLE` 与 circular 搭配持续交付请求；`NbrOfConversion=1`、`ScanConvMode=DISABLE` 固定单通道；`EOCSelection` 不代替 DMA HT/TC。
- DMA 的 `Direction/PeriphInc/MemInc/PeriphDataAlignment/MemDataAlignment/Mode` 决定从哪里到哪里、每次多宽、何时重载；`Priority` 是 DMA 仲裁优先级，不是 NVIC 抢占优先级；FIFO 和 burst 都明确关闭/单次。
- UART 的波特率、字长、停止位、校验、TX-only、无流控、过采样共同确定线速与 GPIO 需求；不能只看 BaudRate 一个字段。
- `__HAL_LINKDMA(&g_adc,DMA_Handle,g_adc_dma)` 和 UART 的 `hdmatx` 链接句柄、设置 Parent，使 HAL DMA 回调能找到所属 ADC/UART；它不会自动替你核对 stream/channel。
- TIM2 的 `ClockDivision` 不是本例计数频率的 PSC；本例计数除数是 Prescaler+1。`MasterOutputTrigger=TIM_TRGO_UPDATE` 把更新送至 ADC，而不是打开一个任意 PWM 引脚。[S1][S3][S4]

#### 真正的调用、回调与错误路径

```text
main → HAL_Init → Reference_Init
       → HSI/PLL/总线时钟 → GPIO/外设门控复位 → DMA 初始化与链接
       → TIM2/ADC1/USART2 初始化 → batch_start 输出 ARM
       → HAL_ADC_Start_DMA(128) → HAL_TIM_Base_Start → ARM结果
DMA2_Stream0_IRQHandler → HAL_DMA_IRQHandler
       → HAL_ADC_ConvHalfCpltCallback / HAL_ADC_ConvCpltCallback
       → batch_event → ACT_TX → HAL_UART_Transmit_DMA
DMA1_Stream6_IRQHandler → HAL_DMA_IRQHandler → HAL内部 UART DMA completion
       → 关闭 DMAT，打开 USART TC interrupt（normal模式）
USART2_IRQHandler → HAL_UART_IRQHandler → HAL_UART_TxCpltCallback
       → batch_event(TX_DONE) → 归还活动半区
ADC_IRQHandler / DMA error → HAL_ADC_ErrorCallback 或 HAL_UART_ErrorCallback
       → batch_event(IO_ERROR) → STOP_SOURCE
main → Reference_Service → POLL；操作员显式 RequestRecovery 后才执行 CLEAN
       → 再停TIM2 → HAL_ADC_Stop_DMA → HAL_UART_AbortTransmit
       → 确认两stream EN清零 → 重置相关DMA/HAL状态 → 清外设标志/旧NVIC pending
       → 新会话 ARM（先ADC DMA后TIM2）；失败仍故障
```

`HAL_UART_TxHalfCpltCallback`在本例明确只代表发送进度，不归还半区。normal UART TX DMA 的 DMA 完成不等于最后停止位发完；所核对包的内部完成函数会打开 TC 中断，真正的用户 TxCplt 从 USART IRQ 路径到达。因此不能删掉 `USART2_IRQHandler`，也不能把裸 DMA TC 当成 HAL TX 完成。[S3][S4]

本包 `HAL_TIM_Base_Stop` 对有效句柄的实现直接返回HAL_OK；Fake的STOP失败用于检验可迁移的失败契约，不是假称真实F4 API必然会这样返回。板端还检查CEN是否确实清零，未兑现时记录停止失败；DMA/ADC/UART清理则有其真实错误/超时路径。[S4]

外设句柄相关的 HAL 初始化/启动/停止/abort 返回值均检查；任意非 HAL_OK 都按失败处理，不忙等重试发送。IRQ 内只做短状态更新、短启动/停源；阻塞清理在主循环进行。清理时仅关闭四个设备 IRQ，**不关闭 SysTick**，否则 HAL abort 的超时记账可能无法推进。失败时不清样本、不换会话、不重新启源。[S4：ADC_Stop_DMA、UART_AbortTransmit、DMA_Abort]

固定包的 `HAL_Init` 是一个需单独说明的版本特例：实现直接返回 `HAL_OK`，不向上传递内部 `HAL_InitTick` 的返回值。因此 `main` 调用它不能单独证明时基初始化成功；目标启动时仍须观察 `HAL_GetTick` 随真实时间递增，不能由主机检查替它证明。[S4：`stm32f4xx_hal.c` 的 `HAL_Init` / `HAL_InitTick`]

| HAL 动作/事件 | 关键寄存器/标志，对照阅读位置 | 为什么与本课判定有关 |
|---|---|---|
| RCC/ClockConfig | RCC_CR、PLLCFGR、CFGR 的 SW/SWS/HPRE/PPRE；FLASH_ACR.LATENCY | 配置与硬件实际选择必须一致，不是 Host Fake 可验证的字段 |
| 外设初始化/复位 | RCC_AHB1ENR/RSTR、APB1ENR/RSTR、APB2ENR/RSTR | 门控未开或复位仍有效时，正确决策也没有真实外设结果 |
| TIM2 TRGO/Start/Stop | TIM2_CR2.MMS=Update；PSC/ARR；CR1.CEN；SR.UIF，EGR.UG | 停 CEN 阻止后续定时触发，不会撤销已在途的转换 |
| ADC external + DMA | ADC_CR2.EXTSEL/EXTEN、DMA/DDS/ADON；公共 ADC_CCR.ADCPRE；SQR/SMPR；SR.OVR | 外触发、连续请求和错误源各自独立；OVR 不是所有数据所有权错误的检测器 |
| ADC DMA2 Stream0 | S0CR.CHSEL=0、DIR、CIRC、MSIZE/PSIZE、MINC、EN；NDTR=128、PAR=&ADC1_DR、M0AR | 半字单位决定128次搬运的含义；LISR HTIF0/TCIF0/TEIF0/DMEIF0/FEIF0 及 LIFCR 清除 |
| UART DMA1 Stream6 | S6CR.CHSEL=4、DIR、byte对齐、normal；NDTR=128；PAR=&USART2_DR | 发送仅借用已完成半区；HISR 的 HTIF6/TCIF6/TEIF6/DMEIF6/FEIF6 与 HIFCR |
| UART 完成 | USART_CR3.DMAT；CR1.TCIE；SR.TC；BRR | DMA 读内存结束与 UART 线完成属于不同阶段，HAL normal模式把它们串起来 |
| IRQ/回调排空 | 外设标志及中断使能，NVIC pending/enabled | 清 NVIC pending 不能消除仍为真的外设中断源；必须先停止、清外设，再清 pending |

寄存器表以 [S1] 第7、10、13、18、30章为准，API/回调行为以 [S3][S4] 为准。这里选择 **HAL→关键寄存器** 对照，不额外提供未经核准的 LL 函数名；改写为 LL 时应在固定包 `Inc/stm32f4xx_ll_*.h` 核对精确接口，不能只改函数前缀。

### 7.4 软件 ticket 的真实边界

主机故意给事件携带旧 `session/token`，证明逻辑会拒绝**可识别**的旧事件。真实 F407 的 HT/TC 和 UART 完成中断没有这些软件编号。板端适配只是把当前软件 ticket 送给决策函数，不能用这种“补标签”证明中断一定属于当前会话。

因此板端必须在新会话前：停止源、停/abort 两条搬运链、确认 EN=0、关闭相关中断源、清外设标志、清 NVIC pending，然后才复位软件 ticket 并启源。`g_callbacks` 在故障/清理中关闭；所有状态调用在短临界区内串行；四个设备 IRQ 使用同抢占级，减少嵌套组合，但不把这些配置当成已测得的时间上界。若硬件排空不成功，不能用主机 STALE 测试的通过掩盖它。[S1][S4]

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

目录内包含真实文件；构建目录已局部忽略，二进制不作为课程源码提交：

```text
lessons/L039-host-test/
  README.md                 lesson.json
  CMakeLists.txt            .gitignore
  core/batch.h              core/batch.c
  host/test_batch.c          host/check_mutations.py
  target/reference_f407.h    target/reference_f407.c
  target/reference_main.c    target/stm32f4xx_hal_conf.h
  evidence/                 主机日志、来源核对记录、自检记录
```

在仓库根目录的 PowerShell 执行（需可用 C11 编译器、CMake、Ninja；变异检查另需 Python）：

```powershell
cmake -S lessons/L039-host-test -B lessons/L039-host-test/build -G Ninja -DCMAKE_BUILD_TYPE=Debug
if ($LASTEXITCODE -ne 0) { throw '主机构建配置失败' }
cmake --build lessons/L039-host-test/build
if ($LASTEXITCODE -ne 0) { throw '主机编译失败，尚未执行逻辑测试' }
& ./lessons/L039-host-test/build/host_batch_test.exe --minimal
if ($LASTEXITCODE -ne 0) { throw '最小交接断言失败' }
& ./lessons/L039-host-test/build/host_batch_test.exe
if ($LASTEXITCODE -ne 0) { throw '完整交接断言失败' }
ctest --test-dir lessons/L039-host-test/build --output-on-failure
if ($LASTEXITCODE -ne 0) { throw 'CTest 未通过' }
python lessons/L039-host-test/host/check_mutations.py
if ($LASTEXITCODE -ne 0) { throw '错误副本未被正确检出' }
```

`enable_testing()` 开启本构建目录的测试注册，`add_test(NAME batch_contract COMMAND host_batch_test)` 注册真实可执行目标；默认零退出为成功，非零为失败，没有 WILL_FAIL 或正则把错误翻转成成功。[S7] Linux/macOS 可去掉 `.exe`；本次只在本机 Windows/GNU 工具链执行，未声称跨平台全验证。

再运行一条**应当失败**的训练命令：

```powershell
& ./lessons/L039-host-test/build/host_batch_test.exe --demo-failure
if ($LASTEXITCODE -ne 1) { throw '故意失败的示例没有产生预期退出码1' }
```

该参数在 HT 后故意省掉 TX_DONE，却断言 A 已 FREE；应看到 `intentional_missing_TX_DONE` 的 FAIL 和退出码1。它演示如何读失败，并不是正常测试失败，更不是证明错误预言正确。变异脚本则让真正错误的实现副本跑完整测试，要求两个副本均被检出；原始生产文件始终不改动。

本次实际证据：

| 文件 | 实际发生的事；证据用途 |
|---|---|
| `evidence/host-red-test.log` | 先运行未实现交接的开发阶段占位实现，最小成功组出现14个断言失败、退出1；最终交付源码不是该占位实现 |
| `evidence/host-build.log` | GNU C11 严格警告构建真实生产逻辑与独立测试入口；编译失败不冒充测试失败 |
| `evidence/host-test.log` | 最终源码的 TRACE 观察与 `checks=236 failures=0`；证明矩阵所覆盖输入下的交接逻辑 |
| `evidence/ctest.log` | CTest 1/1 通过；证明测试入口确实被注册和调用 |
| `evidence/intentional-failure.log` | 故意错误预言产生1项失败、退出1；证明失败输出/退出路径可观察 |
| `evidence/mutations.log` | 等号被放宽、token检查被删的两份副本分别被断言捕获；只说明这两类错误的判定力 |
| `evidence/reference-host-syntax.log` | 本机 GCC 以真实包头文件做 `-fsyntax-only`，无 ARM 代码生成、无链接；不等于目标工程构建 |
| `evidence/source-audit.json` | 本次官方资料及本机包阅读位置、版本、内容哈希；不是构建/硬件证明 |
| `evidence/validation.json` | Teacher 的结构、计划一致性和修改范围自检；不是独立 Reviewer 结论 |

完整测试入口不使用会因 NDEBUG 消失的标准 `assert`；CHECK 打印场景/行号/表达式并累计失败，main 以1退出。Fake 日志容量固定32；溢出也算失败，不静默丢动作。

### 8.2 STM32 参考实现轨道

第 9 节给出完整原创参考文件，**不是仅写迁移展望**。直接复用的是交接逻辑、HAL 初始化/回调/停源/清理代码；必须由用户提供的是已核对的7个板级选择：ADC GPIO port/pin/channel、USART2 TX GPIO port/pin/AF、供电 mV。`reference_main.c` 在这些选择没有提供时故意编译报错，而不是默认某块板的接线。运行时检查仅能排除明显非法数值，不能自动证明某引脚真的对应选定 ADC 通道或 USART2_TX。

参考构建与调试步骤（下面的目标步骤**本次均未执行**）：

1. 核对实际订货号、封装、供电/VDDA/VREF、ADC输入网络、TX对端电平与共地、调试器和保留调试引脚；按 [S2] pin/AF 表和板卡原理图填写7个选择。电压或源阻抗不符时，先重算时钟/Flash/采样时间，不能只绕过检查。
2. 用 CubeMX 6.18.1 选择该实际 MCU，在新建的**项目级**配置中核对第7.3节；不修改 CubeMX 或 IDE 全局配置。固件包固定基包1.28.0+patch1.28.3，不把“安装目录名”单独当唯一版本证据。
3. 在目标工程加入本课 `core/batch.c`、`target/reference_f407.c` 和 `target/reference_main.c`；头文件搜索路径包含 `core/`、`target/` 和固定包 HAL/CMSIS。定义 `STM32F407xx`、`USE_HAL_DRIVER` 及7个经核对的 BOARD_* 编译定义。使用本课限缩 HAL 配置时，`target/` 中的配置应实际被选中；它只面向本例，不替换用户全局文件。
4. 目标工程从已安装官方包引用对应 CMSIS 设备启动文件、`system_stm32f4xx.c` 以及 HAL core、cortex、rcc/rcc_ex、gpio、dma、adc/adc_ex、tim/tim_ex、uart、flash/flash_ex、pwr/pwr_ex 的实现。**不要复制第三方完整源码到教程仓库。** 使用 Cortex-M4/Thumb 与一致的FPU（浮点运算单元）/浮点ABI（应用二进制接口）；选定工具链与链接脚本是目标工程的责任。
5. 本参考手动配置 GPIO、DMA和外设，并定义 IRQ/SysTick/回调。不要同时编译一份会二次初始化它们的生成 MSP，也不要重复定义 main、`stm32f4xx_it.c` 中同名 IRQ 或回调。可保留生成方案并逐项合并，但每个句柄、IRQ、门控/复位必须只有一个所有者。
6. 用目标工程实际的构建系统执行构建，保存工具版本、完整命令、日志、ELF（可执行和可链接格式）及map（链接映射文件）。检查 `g_batch`（包括整个 samples 数组）落在 DMA1/2 可访问的 SRAM，4字节对齐，**不能落在 0x10000000 的 CCM**；本课静态对齐断言不能替代 map 检查。[S1][S2]
7. 经用户另行授权后，才可用实际调试器/编程工具对实际目标连接、选择上述 ELF 并烧录。本次任务禁止烧录，因此这里只记录步骤，**不执行烧录**。
8. 目标运行时保存版本/接线、事件计数、首错快照、串口原始字节和逻辑分析仪时间戳；分别记录预期和实测。正常应见 HT/TC 交替和每个批次一个 HAL TX完成；真实数值和时间必须从仪器读取，不能填本课的测试 tick。

清理函数在阻塞 abort 前关闭四个设备 IRQ、保持 SysTick运行；先停 TIM2，再停止 ADC_DMA、abort UART，确认stream EN归零；重新初始化相关 HAL/DMA 状态后才清旧标志和pending并允许新会话。第一次启动失败返回2，主循环仍提供 Service，操作员修复原因后可显式请求恢复；板级配置/初始化失败返回1则停在错误循环，不能对未正确初始化的句柄乱做恢复。

目标排错优先顺序：`CEN/更新触发 → ADC EXTSEL/EXTEN/ADON/OVR → DMA2 NDTR/标志/地址 → HAL回调 → DMA1 → USART2 TC IRQ → 归还`。先找第一个不符合预期的边界，不以“串口没数据”直接断定 DMA 驱动坏了。[S1][S3][S4]

## 9. 最小代码示例

下面展示交付文件的完整内容，正文内代码与同目录源码逐字一致，可直接从仓库构建，避免发布后只剩不存在的代码路径。所有代码为本课原创；官方驱动只引用安装包，不在此重印。

五个动作不是五个新架构概念：**声明**在 `batch.h/reference_f407.h`；**实现**在 `batch.c/reference_f407.c`；**实例化**在 Fixture 或板端静态对象；**组装**在固定测试 `drive` 或 `Reference_Init`；**使用**在测试输入/main/HAL回调。依赖方向是 host/target → core，core 不依赖 HAL。以下每个文件的小标题交代其层级和生命周期。


### 9.1 `core/batch.h`

公开声明；上层依赖此头，类型不依赖HAL；调用者保证非空指针。

```c
#ifndef BATCH_H
#define BATCH_H
#include <stdint.h>
#define BATCH_HALF_SAMPLES 64u
#define BATCH_SAMPLES 128u
#define BATCH_HALF_BYTES 128u
#define MODE_IDLE 0u
#define MODE_STARTING 1u
#define MODE_RUNNING 2u
#define MODE_FAULT 3u
#define MODE_CLEANING 4u
#define HALF_FREE 0u
#define HALF_CAPTURE 1u
#define HALF_TX 2u
#define EV_HT 1u
#define EV_TC 2u
#define EV_TX_DONE 3u
#define EV_POLL 4u
#define EV_IO_ERROR 5u
#define EV_TX_START_ERROR 6u
#define ACT_NONE 0u
#define ACT_ARM 1u
#define ACT_TX 2u
#define ACT_STOP_SOURCE 3u
#define ACT_CLEAN 4u
#define FAULT_NONE 0u
#define FAULT_ORDER 1u
#define FAULT_BUSY 2u
#define FAULT_DEADLINE 3u
#define FAULT_CALLBACK 4u
#define FAULT_START 5u
#define FAULT_DEVICE 6u
#define FAULT_STALE 7u
#define FAULT_ARGUMENT 8u

typedef struct {
    uint32_t kind, now, session, half, token;
} BatchEvent;
typedef struct {
    uint32_t kind, session, half, token;
} BatchAction;
typedef struct {
    uint32_t code, event, tick, session, half, token;
} BatchSnapshot;
typedef struct {
    uint32_t window_ms, mode, session, expected_half, sequence;
    uint32_t half_state[2];
    uint32_t tx_active, tx_half, tx_token, tx_start_tick;
    uint32_t current_fault, stop_ok, stop_errors, cleanup_errors;
    BatchSnapshot first_fault;
    uint16_t samples[BATCH_SAMPLES];
} Batch;

/* Caller owns Batch and serializes ALL calls; no allocation or HAL dependency. */
/* init requires quiescent hardware and no outstanding users; NOT a recovery API. */
uint32_t batch_init(Batch *s, uint32_t window_ms);
uint32_t batch_start(Batch *s, BatchAction *out);
void batch_arm_result(Batch *s, uint32_t io_error, uint32_t now,
                      BatchAction *out);
void batch_event(Batch *s, BatchEvent event, BatchAction *out);
void batch_stop_result(Batch *s, uint32_t io_error);
uint32_t batch_recover(Batch *s, BatchAction *out);
void batch_cleanup_result(Batch *s, uint32_t io_error, BatchAction *out);
#endif
```

### 9.2 `core/batch.c`

生产决策实现；只借用调用者状态/事件/输出，固定内存，无HAL依赖。

```c
#include "batch.h"
#include <string.h>
_Static_assert(sizeof(uint16_t) == 2u, "Requires 8-bit bytes");

static void no_action(BatchAction *a)
{ memset(a, 0, sizeof(*a)); }
static void fault(Batch *s, uint32_t code, BatchEvent e, BatchAction *a)
{
    /* Freeze the decision before any external action. First physical action is STOP. */
    s->mode = MODE_FAULT;
    s->current_fault = code;
    s->stop_ok = 0u;
    if (s->first_fault.code == FAULT_NONE) {
        s->first_fault.code = code;
        s->first_fault.event = e.kind;
        s->first_fault.tick = e.now;
        s->first_fault.session = e.session;
        s->first_fault.half = e.half;
        s->first_fault.token = e.token;
    }
    a->kind = ACT_STOP_SOURCE;
    a->session = s->session;
}
static void new_session(Batch *s, BatchAction *a)
{
    BatchEvent e = {0};
    if (s->session == UINT32_MAX) {
        e.session = s->session;
        fault(s, FAULT_ARGUMENT, e, a);
        return;
    }
    ++s->session;
    s->sequence = 0u;
    s->expected_half = 0u;
    s->half_state[0] = HALF_CAPTURE;
    s->half_state[1] = HALF_FREE;
    s->tx_active = 0u;
    s->tx_half = 0u;
    s->tx_token = 0u;
    s->tx_start_tick = 0u;
    s->current_fault = FAULT_NONE;
    s->stop_ok = 0u;
    memset(s->samples, 0, sizeof(s->samples));
    s->mode = MODE_STARTING;
    a->kind = ACT_ARM;
    a->session = s->session;
}
uint32_t batch_init(Batch *s, uint32_t window_ms)
{
    memset(s, 0, sizeof(*s));
    if (window_ms == 0u || window_ms >= UINT32_C(0x80000000)) { return 0u; }
    s->window_ms = window_ms;
    return 1u;
}
uint32_t batch_start(Batch *s, BatchAction *out)
{
    no_action(out);
    if (s->mode != MODE_IDLE || s->window_ms == 0u) { return 0u; }
    new_session(s, out);
    return 1u;
}
void batch_arm_result(Batch *s, uint32_t io_error, uint32_t now,
                      BatchAction *out)
{
    BatchEvent e = {EV_IO_ERROR, now, s->session, 0u, 0u};
    no_action(out);
    if (s->mode != MODE_STARTING) { return; }
    if (io_error != 0u) { fault(s, FAULT_START, e, out); }
    else { s->mode = MODE_RUNNING; }
}
void batch_event(Batch *s, BatchEvent e, BatchAction *out)
{
    uint32_t finished, next;
    no_action(out);
    /* Faulted/cleaning sessions do not release memory in response to callbacks. */
    if (s->mode != MODE_RUNNING) { return; }
    if (e.session != s->session) { fault(s, FAULT_STALE, e, out); return; }
    /* Unsigned subtraction handles one tick wrap; callers must poll regularly. */
    if (s->tx_active != 0u &&
        (uint32_t)(e.now - s->tx_start_tick) >= s->window_ms) {
        fault(s, FAULT_DEADLINE, e, out); return;
    }
    if (e.kind == EV_HT || e.kind == EV_TC) {
        finished = e.kind == EV_HT ? 0u : 1u;
        next = finished ^ 1u;
        if (e.half != finished || finished != s->expected_half ||
            s->half_state[finished] != HALF_CAPTURE) {
            fault(s, FAULT_ORDER, e, out); return;
        }
        if (s->tx_active != 0u || s->half_state[next] != HALF_FREE) {
            fault(s, FAULT_BUSY, e, out); return;
        }
        if (s->sequence == UINT32_MAX) {
            fault(s, FAULT_ARGUMENT, e, out); return;
        }
        ++s->sequence;
        s->half_state[finished] = HALF_TX;
        s->half_state[next] = HALF_CAPTURE;
        s->expected_half = next;
        s->tx_active = 1u;
        s->tx_half = finished;
        s->tx_token = s->sequence;
        s->tx_start_tick = e.now;
        out->kind = ACT_TX;
        out->session = s->session;
        out->half = finished;
        out->token = s->tx_token;
    } else if (e.kind == EV_TX_DONE) {
        if (s->tx_active == 0u || e.half != s->tx_half || e.token != s->tx_token) {
            fault(s, FAULT_CALLBACK, e, out); return;
        }
        s->half_state[s->tx_half] = HALF_FREE;
        s->tx_active = 0u;
    } else if (e.kind == EV_TX_START_ERROR) {
        fault(s, FAULT_START, e, out);
    } else if (e.kind == EV_IO_ERROR) {
        fault(s, FAULT_DEVICE, e, out);
    } else if (e.kind != EV_POLL) {
        fault(s, FAULT_ARGUMENT, e, out);
    }
}
void batch_stop_result(Batch *s, uint32_t io_error)
{
    if (s->mode != MODE_FAULT) { return; }
    s->stop_ok = io_error == 0u ? 1u : 0u;
    if (io_error != 0u) { ++s->stop_errors; }
}
uint32_t batch_recover(Batch *s, BatchAction *out)
{
    no_action(out);
    if (s->mode != MODE_FAULT) { return 0u; }
    s->mode = MODE_CLEANING;
    out->kind = ACT_CLEAN;
    out->session = s->session;
    return 1u;
}
void batch_cleanup_result(Batch *s, uint32_t io_error, BatchAction *out)
{
    no_action(out);
    if (s->mode != MODE_CLEANING) { return; }
    if (io_error != 0u) {
        ++s->cleanup_errors;
        s->mode = MODE_FAULT; /* Keep current/first fault; NEVER rearm on failure. */
    } else {
        new_session(s, out); /* Adapter promises all old hardware activity is drained. */
    }
}
```

### 9.3 `host/test_batch.c`

主机专用夹具、固定Fake、独立预言及测试入口；每个场景重新初始化。

```c
#include "batch.h"
#include <stdio.h>
#include <string.h>

typedef struct {
    Batch s;
    BatchAction log[32];
    uint32_t count, overflow, arm_error, tx_error, stop_error, clean_error;
    uint8_t wire[BATCH_HALF_BYTES];
} Fixture;
static uint32_t failures, checks;
static const char *case_name;
#define CHECK(x) do { ++checks; if (!(x)) { ++failures; \
    printf("FAIL %s line %u: %s\n", case_name, (unsigned)__LINE__, #x); } } while (0)

/* Fixed fake: execute requested actions, do not decide ownership or expected results. */
static void drive(Fixture *f, BatchAction a, uint32_t now)
{
    while (a.kind != ACT_NONE) {
        if (f->count >= 32u) { f->overflow = 1u; return; }
        f->log[f->count++] = a;
        if (a.kind == ACT_ARM) {
            batch_arm_result(&f->s, f->arm_error, now, &a);
        } else if (a.kind == ACT_TX) {
            if (a.half > 1u) { f->overflow = 1u; return; }
            memcpy(f->wire, &f->s.samples[a.half * BATCH_HALF_SAMPLES],
                   BATCH_HALF_BYTES);
            if (f->tx_error != 0u) {
                BatchEvent e = {EV_TX_START_ERROR, now, a.session, a.half, a.token};
                batch_event(&f->s, e, &a);
            } else { a.kind = ACT_NONE; }
        } else if (a.kind == ACT_STOP_SOURCE) {
            batch_stop_result(&f->s, f->stop_error);
            a.kind = ACT_NONE;
        } else if (a.kind == ACT_CLEAN) {
            batch_cleanup_result(&f->s, f->clean_error, &a);
        } else { f->overflow = 1u; return; }
    }
}
static void fixture(Fixture *f)
{
    BatchAction a = {0};
    memset(f, 0, sizeof(*f));
    CHECK(batch_init(&f->s, 64u) == 1u);
    CHECK(batch_start(&f->s, &a) == 1u);
    drive(f, a, 0u);
    CHECK(f->s.mode == MODE_RUNNING);
    CHECK(f->overflow == 0u);
}
static void send(Fixture *f, uint32_t kind, uint32_t now,
                 uint32_t half, uint32_t token, uint32_t session)
{
    BatchAction a = {0};
    BatchEvent e = {kind, now, session, half, token};
    batch_event(&f->s, e, &a);
    drive(f, a, now);
    printf("TRACE %s event=%u tick=%u mode=%u fault=%u tx=%u actions=%u\n",
           case_name, (unsigned)kind, (unsigned)now, (unsigned)f->s.mode,
           (unsigned)f->s.current_fault, (unsigned)f->s.tx_active, (unsigned)f->count);
    CHECK(f->overflow == 0u);
}
static void event(Fixture *f, uint32_t kind, uint32_t now,
                  uint32_t half, uint32_t token)
{ send(f, kind, now, half, token, f->s.session); }
static void recover(Fixture *f, uint32_t now)
{
    BatchAction a = {0};
    CHECK(batch_recover(&f->s, &a) == 1u);
    drive(f, a, now);
}
static uint32_t logged_kind(const Fixture *f, uint32_t index)
{ return index < f->count ? f->log[index].kind : ACT_NONE; }
static void fault_is(Fixture *f, uint32_t code)
{
    CHECK(f->s.mode == MODE_FAULT);
    CHECK(f->s.current_fault == code);
    CHECK(f->s.first_fault.code == code);
    CHECK(logged_kind(f, f->count - 1u) == ACT_STOP_SOURCE);
    CHECK(f->s.stop_ok == 1u);
}
static void normal(void)
{
    Fixture f;
    uint32_t i;
    uint16_t expected[BATCH_HALF_SAMPLES];
    case_name = "A_TX_done_B_TX_done_A";
    fixture(&f);
    CHECK(f.s.half_state[0] == HALF_CAPTURE);
    CHECK(f.s.half_state[1] == HALF_FREE);
    for (i = 0u; i < BATCH_HALF_SAMPLES; ++i) {
        f.s.samples[i] = (uint16_t)(0x100u + i);
        expected[i] = (uint16_t)(0x100u + i);
    }
    event(&f, EV_HT, 64u, 0u, 0u);
    CHECK(f.count == 2u);
    CHECK(f.log[0].kind == ACT_ARM);
    CHECK(f.log[1].kind == ACT_TX);
    CHECK(f.log[1].half == 0u && f.log[1].token == 1u);
    CHECK(f.s.half_state[0] == HALF_TX);
    CHECK(f.s.half_state[1] == HALF_CAPTURE);
    CHECK(memcmp(f.wire, expected, sizeof(expected)) == 0);
    event(&f, EV_POLL, 70u, 0u, 0u);
    CHECK(f.s.half_state[0] == HALF_TX); /* start is NOT completion */
    event(&f, EV_TX_DONE, 76u, 0u, 1u);
    CHECK(f.s.half_state[0] == HALF_FREE);
    CHECK(f.s.tx_active == 0u);
    CHECK(f.count == 2u); /* never send on completion */
    event(&f, EV_TC, 128u, 1u, 0u);
    CHECK(f.log[2].kind == ACT_TX && f.log[2].half == 1u);
    CHECK(f.log[2].token == 2u);
    CHECK(f.s.half_state[0] == HALF_CAPTURE);
    event(&f, EV_TX_DONE, 140u, 1u, 2u);
    event(&f, EV_HT, 192u, 0u, 0u);
    CHECK(f.log[3].half == 0u && f.log[3].token == 3u);
    event(&f, EV_TX_DONE, 204u, 0u, 3u);
    CHECK(f.s.mode == MODE_RUNNING && f.s.first_fault.code == FAULT_NONE);
}
static void cases(void)
{
    Fixture f;
    BatchSnapshot saved;
    uint32_t n;
    case_name = "TC_before_HT"; fixture(&f);
    event(&f, EV_TC, 64u, 1u, 0u); fault_is(&f, FAULT_ORDER);
    CHECK(f.count == 2u); /* ARM, STOP; never TX */

    case_name = "duplicate_HT"; fixture(&f);
    event(&f, EV_HT, 64u, 0u, 0u);
    event(&f, EV_HT, 65u, 0u, 0u); fault_is(&f, FAULT_ORDER);
    CHECK(f.count == 3u);

    case_name = "busy_before_deadline"; fixture(&f);
    event(&f, EV_HT, 64u, 0u, 0u);
    event(&f, EV_TC, 127u, 1u, 0u); fault_is(&f, FAULT_BUSY);
    CHECK(f.s.half_state[0] == HALF_TX);
    CHECK(f.count == 3u); /* no second TX */
    saved = f.s.first_fault; n = f.count;
    event(&f, EV_IO_ERROR, 128u, 0u, 0u);
    event(&f, EV_TX_DONE, 129u, 0u, 1u);
    CHECK(memcmp(&saved, &f.s.first_fault, sizeof(saved)) == 0);
    CHECK(f.count == n && f.s.half_state[0] == HALF_TX);

    case_name = "deadline_minus_one"; fixture(&f);
    event(&f, EV_HT, 64u, 0u, 0u);
    event(&f, EV_TX_DONE, 127u, 0u, 1u);
    CHECK(f.s.mode == MODE_RUNNING && f.s.half_state[0] == HALF_FREE);
    case_name = "deadline_equal"; fixture(&f);
    event(&f, EV_HT, 64u, 0u, 0u);
    event(&f, EV_TX_DONE, 128u, 0u, 1u); fault_is(&f, FAULT_DEADLINE);
    CHECK(f.s.half_state[0] == HALF_TX);
    case_name = "deadline_plus_one"; fixture(&f);
    event(&f, EV_HT, 64u, 0u, 0u);
    event(&f, EV_POLL, 129u, 0u, 0u); fault_is(&f, FAULT_DEADLINE);

    case_name = "duplicate_completion"; fixture(&f);
    event(&f, EV_HT, 64u, 0u, 0u);
    event(&f, EV_TX_DONE, 76u, 0u, 1u);
    event(&f, EV_TX_DONE, 77u, 0u, 1u); fault_is(&f, FAULT_CALLBACK);
    CHECK(f.s.half_state[0] == HALF_FREE && f.count == 3u);
    case_name = "wrong_half"; fixture(&f);
    event(&f, EV_HT, 64u, 0u, 0u);
    event(&f, EV_TX_DONE, 76u, 1u, 1u); fault_is(&f, FAULT_CALLBACK);
    CHECK(f.s.half_state[0] == HALF_TX);
    case_name = "wrong_token"; fixture(&f);
    event(&f, EV_HT, 64u, 0u, 0u);
    event(&f, EV_TX_DONE, 76u, 0u, 0u); fault_is(&f, FAULT_CALLBACK);
    CHECK(f.s.half_state[0] == HALF_TX);
    case_name = "unexpected_completion"; fixture(&f);
    event(&f, EV_TX_DONE, 1u, 0u, 0u); fault_is(&f, FAULT_CALLBACK);

    case_name = "TX_start_failure"; fixture(&f); f.tx_error = 1u;
    event(&f, EV_HT, 64u, 0u, 0u); fault_is(&f, FAULT_START);
    CHECK(f.count == 3u && f.log[1].kind == ACT_TX);
    case_name = "stop_failure_then_explicit_recovery"; fixture(&f);
    f.stop_error = 1u;
    event(&f, EV_IO_ERROR, 20u, 0u, 0u);
    CHECK(f.s.mode == MODE_FAULT && f.s.current_fault == FAULT_DEVICE);
    CHECK(f.s.first_fault.code == FAULT_DEVICE);
    CHECK(f.s.stop_ok == 0u && f.s.stop_errors == 1u);
    saved = f.s.first_fault; f.clean_error = 1u;
    recover(&f, 21u);
    CHECK(f.s.mode == MODE_FAULT && f.s.cleanup_errors == 1u);
    CHECK(logged_kind(&f, f.count - 1u) == ACT_CLEAN);
    CHECK(memcmp(&saved, &f.s.first_fault, sizeof(saved)) == 0);
    f.stop_error = 0u; f.clean_error = 0u;
    recover(&f, 22u);
    CHECK(logged_kind(&f, f.count - 2u) == ACT_CLEAN);
    CHECK(logged_kind(&f, f.count - 1u) == ACT_ARM);
    CHECK(f.s.mode == MODE_RUNNING && f.s.session == 2u);
    CHECK(f.s.current_fault == FAULT_NONE && f.s.tx_active == 0u);
    CHECK(f.s.samples[0] == 0u && f.s.samples[127] == 0u);
    CHECK(memcmp(&saved, &f.s.first_fault, sizeof(saved)) == 0);
    n = f.count;
    send(&f, EV_TX_DONE, 23u, 0u, 1u, 1u);
    CHECK(f.count == n + 1u && logged_kind(&f, f.count - 1u) == ACT_STOP_SOURCE);
    CHECK(f.s.current_fault == FAULT_STALE && f.s.mode == MODE_FAULT);
    CHECK(memcmp(&saved, &f.s.first_fault, sizeof(saved)) == 0);

    case_name = "arm_failure";
    memset(&f, 0, sizeof(f)); f.arm_error = 1u;
    { BatchAction a = {0}; CHECK(batch_init(&f.s, 64u) == 1u);
      CHECK(batch_start(&f.s, &a) == 1u); drive(&f, a, 0u); }
    fault_is(&f, FAULT_START);
    CHECK(f.count == 2u && f.log[0].kind == ACT_ARM);

    case_name = "tick_wrap"; fixture(&f);
    event(&f, EV_HT, UINT32_MAX - 31u, 0u, 0u);
    event(&f, EV_TX_DONE, 31u, 0u, 1u);
    CHECK(f.s.mode == MODE_RUNNING && f.s.tx_active == 0u);
    case_name = "tick_wrap_equal"; fixture(&f);
    event(&f, EV_HT, UINT32_MAX - 31u, 0u, 0u);
    event(&f, EV_TX_DONE, 32u, 0u, 1u); fault_is(&f, FAULT_DEADLINE);

    case_name = "invalid_event"; fixture(&f);
    event(&f, 99u, 1u, 0u, 0u); fault_is(&f, FAULT_ARGUMENT);
    case_name = "token_exhaustion"; fixture(&f); f.s.sequence = UINT32_MAX;
    event(&f, EV_HT, 64u, 0u, 0u); fault_is(&f, FAULT_ARGUMENT);
    case_name = "command_guards"; fixture(&f);
    { BatchAction a = {0}; CHECK(batch_start(&f.s, &a) == 0u);
      CHECK(a.kind == ACT_NONE); CHECK(batch_recover(&f.s, &a) == 0u);
      CHECK(a.kind == ACT_NONE); }
    { Batch invalid; /* Fresh, quiescent object: never re-init an active session. */
      CHECK(batch_init(&invalid, 0u) == 0u);
      CHECK(batch_init(&invalid, UINT32_MAX) == 0u); }
}
int main(int argc, char **argv)
{
    if (argc == 2 && strcmp(argv[1], "--demo-failure") == 0) {
        Fixture f;
        case_name = "intentional_missing_TX_DONE"; fixture(&f);
        event(&f, EV_HT, 64u, 0u, 0u);
        CHECK(f.s.half_state[0] == HALF_FREE); /* deliberately false oracle */
    } else if (argc == 2 && strcmp(argv[1], "--minimal") == 0) { normal(); }
    else { normal(); cases(); }
    printf("checks=%u failures=%u\n", (unsigned)checks, (unsigned)failures);
    return failures == 0u ? 0 : 1;
}
```

### 9.4 `CMakeLists.txt`

仅组装主机目标；不把Fake或测试main打包进板端。

```cmake
cmake_minimum_required(VERSION 3.20)
project(L039_host_test LANGUAGES C)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)
add_library(batch_core STATIC core/batch.c)
target_include_directories(batch_core PUBLIC core)
add_executable(host_batch_test host/test_batch.c)
target_link_libraries(host_batch_test PRIVATE batch_core)
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(batch_core PRIVATE -Wall -Wextra -Werror -Wpedantic)
  target_compile_options(host_batch_test PRIVATE -Wall -Wextra -Werror -Wpedantic)
endif()
enable_testing()
add_test(NAME batch_contract COMMAND host_batch_test)
```

### 9.5 `host/check_mutations.py`

判定力检查辅助程序；错误副本仅落在本课build目录，源文件不改动。

```python
"""Deliberately alter only copied SUT files. Success means BOTH mutants are detected."""
import argparse
from pathlib import Path
import subprocess

p = argparse.ArgumentParser()
p.add_argument("--cc", default="gcc")
p.add_argument("--build-dir", default="build/mutations")
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
out = (root / a.build_dir).resolve()
if not out.is_relative_to(root / "build"):
    raise SystemExit("Mutation artifacts must stay inside this lesson's ignored build/.")
out.mkdir(parents=True, exist_ok=True)
source = (root / "core/batch.c").read_text(encoding="utf-8")
mutants = [
    ("accept_equal_deadline", ">= s->window_ms", "> s->window_ms"),
    ("ignore_completion_token", "e.token != s->tx_token", "0u != 0u"),
]
for name, old, new in mutants:
    if source.count(old) != 1:
        raise SystemExit(f"Mutation anchor must occur once: {old}")
    cfile = out / f"{name}.c"
    exe = out / f"{name}.exe"
    cfile.write_text(source.replace(old, new), encoding="utf-8")
    subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wpedantic",
                    "-I", str(root / "core"), str(cfile),
                    str(root / "host/test_batch.c"), "-o", str(exe)], check=True)
    result = subprocess.run([str(exe)], text=True, capture_output=True)
    print(f"=== {name} exit={result.returncode} ===")
    print(result.stdout, end="")
    if result.returncode != 1 or "FAIL " not in result.stdout:
        raise SystemExit("Mutant survived or crashed: a logical assertion failure was required.")
print("mutants_detected=2/2; original source was not modified")
```

### 9.6 `target/reference_f407.h`

板端公开声明；参数显式携带已核对的板级事实，公开整数固定宽度。

```c
#ifndef REFERENCE_F407_H
#define REFERENCE_F407_H
#include "stm32f4xx_hal.h"
#include "batch.h"
/* Chip-level choices MUST be checked against the chosen package and board schematic. */
typedef struct {
    GPIO_TypeDef *adc_port;
    uint32_t adc_pin, adc_channel;
    GPIO_TypeDef *tx_port;
    uint32_t tx_pin, tx_alternate;
    uint32_t supply_mv; /* Board documentation/measurement, NOT inferred from the MCU. */
} ReferencePins;
typedef struct {
    uint32_t mode, session, current_fault, stop_ok, stop_errors, cleanup_errors;
    uint32_t ht_count, tc_count, tx_count, error_count, last_hal_error;
    BatchSnapshot first_fault;
} ReferenceDiag;
/* Init result: 0 running, 1 fatal configuration/init error, 2 armed attempt faulted. */
uint32_t Reference_Init(const ReferencePins *pins);
void Reference_Service(void);
void Reference_RequestRecovery(void); /* Explicit operator decision; no automatic restart. */
void Reference_GetDiag(ReferenceDiag *out);
#endif
```

### 9.7 `target/stm32f4xx_hal_conf.h`

本参考工程局部HAL选择；HSE/VDD为0哨兵，不表示板上没有或测得0V；不用外部源。Flash的DATA_CACHE_ENABLE是F4 Flash/ART设置，不是已提供CPU数据缓存一致性。

```c
#ifndef STM32F4XX_HAL_CONF_H
#define STM32F4XX_HAL_CONF_H
/* Original, restricted reference configuration; HSE/LSE are NOT selected. */
#define HAL_MODULE_ENABLED
#define HAL_ADC_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_DMA_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED
#define HAL_GPIO_MODULE_ENABLED
#define HAL_PWR_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED
#define HAL_TIM_MODULE_ENABLED
#define HAL_UART_MODULE_ENABLED
#define HSI_VALUE 16000000U
#define HSE_VALUE 0U
#define HSE_STARTUP_TIMEOUT 100U
#define LSI_VALUE 32000U
#define LSE_VALUE 32768U
#define LSE_STARTUP_TIMEOUT 5000U
#define EXTERNAL_CLOCK_VALUE 0U
#define VDD_VALUE 0U
#define TICK_INT_PRIORITY 15U
#define USE_RTOS 0U
#define PREFETCH_ENABLE 1U
#define INSTRUCTION_CACHE_ENABLE 1U
#define DATA_CACHE_ENABLE 1U
#define USE_HAL_ADC_REGISTER_CALLBACKS 0U
#define USE_HAL_UART_REGISTER_CALLBACKS 0U
#define USE_HAL_TIM_REGISTER_CALLBACKS 0U
#include "stm32f4xx_hal_rcc.h"
#include "stm32f4xx_hal_gpio.h"
#include "stm32f4xx_hal_dma.h"
#include "stm32f4xx_hal_cortex.h"
#include "stm32f4xx_hal_adc.h"
#include "stm32f4xx_hal_flash.h"
#include "stm32f4xx_hal_pwr.h"
#include "stm32f4xx_hal_tim.h"
#include "stm32f4xx_hal_uart.h"
#define assert_param(expr) ((void)0U)
#endif
```

### 9.8 `target/reference_f407.c`

完整F407适配；静态对象贯穿固件生命周期，回调/前台到core的依赖方向单一。参考实现，待目标工程编译；未上板。

```c
/* Original reference adapter. NOT a board build or hardware-verification record. */
#include "reference_f407.h"
#include <string.h>
#include <stddef.h>

_Alignas(4) static Batch g_batch; /* Must be in DMA-accessible SRAM, NEVER F407 CCM. */
_Static_assert(offsetof(Batch, samples) % 4u == 0u, "ADC buffer alignment");
static ADC_HandleTypeDef g_adc;
static UART_HandleTypeDef g_uart;
static TIM_HandleTypeDef g_tim;
static DMA_HandleTypeDef g_adc_dma, g_tx_dma;
static ReferencePins g_pins;
static BatchAction g_hw_ticket;
static volatile uint32_t g_callbacks, g_recover, g_ready;
static volatile uint32_t g_ht, g_tc, g_tx, g_error, g_last_hal_error;
static const IRQn_Type g_irqs[4] = {
    DMA2_Stream0_IRQn, DMA1_Stream6_IRQn, ADC_IRQn, USART2_IRQn
};
static uint32_t lock(void)
{ uint32_t p = __get_PRIMASK(); __disable_irq(); return p; }
static void unlock(uint32_t p)
{ __set_PRIMASK(p); }
static void irq_enable(uint32_t enable)
{
    uint32_t i;
    for (i = 0u; i < 4u; ++i) {
        if (enable != 0u) { HAL_NVIC_EnableIRQ(g_irqs[i]); }
        else { HAL_NVIC_DisableIRQ(g_irqs[i]); }
    }
}
static uint32_t gpio_clock(GPIO_TypeDef *port)
{
    if (port == GPIOA) { __HAL_RCC_GPIOA_CLK_ENABLE(); }
    else if (port == GPIOB) { __HAL_RCC_GPIOB_CLK_ENABLE(); }
    else if (port == GPIOC) { __HAL_RCC_GPIOC_CLK_ENABLE(); }
    else if (port == GPIOD) { __HAL_RCC_GPIOD_CLK_ENABLE(); }
    else if (port == GPIOE) { __HAL_RCC_GPIOE_CLK_ENABLE(); }
    else if (port == GPIOF) { __HAL_RCC_GPIOF_CLK_ENABLE(); }
    else if (port == GPIOG) { __HAL_RCC_GPIOG_CLK_ENABLE(); }
    else if (port == GPIOH) { __HAL_RCC_GPIOH_CLK_ENABLE(); }
    else if (port == GPIOI) { __HAL_RCC_GPIOI_CLK_ENABLE(); }
    else { return 1u; }
    return 0u;
}
static uint32_t one_pin(uint32_t pin)
{ return pin != 0u && pin <= GPIO_PIN_15 && (pin & (pin - 1u)) == 0u ? 1u : 0u; }
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
    /* Requires documented 2.7..3.6 V supply; caller checked it before this call. */
    return HAL_RCC_ClockConfig(&c, FLASH_LATENCY_2) == HAL_OK ? 0u : 1u;
}
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
static uint32_t peripherals_init(void)
{
    GPIO_InitTypeDef io = {0};
    TIM_MasterConfigTypeDef master = {0};
    __HAL_RCC_DMA1_CLK_ENABLE(); __HAL_RCC_DMA2_CLK_ENABLE();
    __HAL_RCC_ADC1_CLK_ENABLE(); __HAL_RCC_TIM2_CLK_ENABLE();
    __HAL_RCC_USART2_CLK_ENABLE();
    /* Dedicated reference project ONLY: these reset domains must have no other owner. */
    __HAL_RCC_TIM2_FORCE_RESET(); __HAL_RCC_TIM2_RELEASE_RESET();
    __HAL_RCC_USART2_FORCE_RESET(); __HAL_RCC_USART2_RELEASE_RESET();
    __HAL_RCC_ADC_FORCE_RESET(); __HAL_RCC_ADC_RELEASE_RESET();
    __HAL_RCC_DMA1_FORCE_RESET(); __HAL_RCC_DMA1_RELEASE_RESET();
    __HAL_RCC_DMA2_FORCE_RESET(); __HAL_RCC_DMA2_RELEASE_RESET();
    if (gpio_clock(g_pins.adc_port) != 0u || gpio_clock(g_pins.tx_port) != 0u) { return 1u; }
    io.Pin = g_pins.adc_pin; io.Mode = GPIO_MODE_ANALOG; io.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(g_pins.adc_port, &io);
    io.Pin = g_pins.tx_pin; io.Mode = GPIO_MODE_AF_PP;
    io.Speed = GPIO_SPEED_FREQ_VERY_HIGH; io.Alternate = g_pins.tx_alternate;
    HAL_GPIO_Init(g_pins.tx_port, &io);

    g_adc_dma.Instance = DMA2_Stream0;
    g_adc_dma.Init.Channel = DMA_CHANNEL_0;
    g_adc_dma.Init.Direction = DMA_PERIPH_TO_MEMORY;
    g_adc_dma.Init.PeriphInc = DMA_PINC_DISABLE;
    g_adc_dma.Init.MemInc = DMA_MINC_ENABLE;
    g_adc_dma.Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
    g_adc_dma.Init.MemDataAlignment = DMA_MDATAALIGN_HALFWORD;
    g_adc_dma.Init.Mode = DMA_CIRCULAR;
    g_adc_dma.Init.Priority = DMA_PRIORITY_HIGH;
    g_adc_dma.Init.FIFOMode = DMA_FIFOMODE_DISABLE;
    g_adc_dma.Init.MemBurst = DMA_MBURST_SINGLE;
    g_adc_dma.Init.PeriphBurst = DMA_PBURST_SINGLE;
    if (HAL_DMA_Init(&g_adc_dma) != HAL_OK) { return 1u; }
    g_tx_dma.Instance = DMA1_Stream6;
    g_tx_dma.Init.Channel = DMA_CHANNEL_4;
    g_tx_dma.Init.Direction = DMA_MEMORY_TO_PERIPH;
    g_tx_dma.Init.PeriphInc = DMA_PINC_DISABLE;
    g_tx_dma.Init.MemInc = DMA_MINC_ENABLE;
    g_tx_dma.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
    g_tx_dma.Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
    g_tx_dma.Init.Mode = DMA_NORMAL;
    g_tx_dma.Init.Priority = DMA_PRIORITY_MEDIUM;
    g_tx_dma.Init.FIFOMode = DMA_FIFOMODE_DISABLE;
    g_tx_dma.Init.MemBurst = DMA_MBURST_SINGLE;
    g_tx_dma.Init.PeriphBurst = DMA_PBURST_SINGLE;
    if (HAL_DMA_Init(&g_tx_dma) != HAL_OK) { return 1u; }
    __HAL_LINKDMA(&g_adc, DMA_Handle, g_adc_dma);
    __HAL_LINKDMA(&g_uart, hdmatx, g_tx_dma);
    g_tim.Instance = TIM2;
    g_tim.Init.Prescaler = 83u;
    g_tim.Init.CounterMode = TIM_COUNTERMODE_UP;
    g_tim.Init.Period = 999u;
    g_tim.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    g_tim.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
    if (HAL_TIM_Base_Init(&g_tim) != HAL_OK) { return 1u; }
    master.MasterOutputTrigger = TIM_TRGO_UPDATE;
    master.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
    if (HAL_TIMEx_MasterConfigSynchronization(&g_tim, &master) != HAL_OK) { return 1u; }
    return adc_uart_init();
}
/* IRQ-safe short actions ONLY. Caller masks interrupts; no blocking abort here. */
static void short_actions(BatchAction a)
{
    while (a.kind != ACT_NONE) {
        if (a.kind == ACT_ARM) {
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
        } else if (a.kind == ACT_TX) {
            g_hw_ticket = a; /* UART hardware does NOT carry this software ticket. */
            __DMB();
            if (HAL_UART_Transmit_DMA(&g_uart,
                    (uint8_t *)&g_batch.samples[a.half * BATCH_HALF_SAMPLES],
                    (uint16_t)BATCH_HALF_BYTES) != HAL_OK) {
                BatchEvent e = {EV_TX_START_ERROR, HAL_GetTick(), a.session, a.half, a.token};
                g_last_hal_error = g_uart.ErrorCode;
                batch_event(&g_batch, e, &a);
            } else { a.kind = ACT_NONE; }
        } else if (a.kind == ACT_STOP_SOURCE) {
            uint32_t bad;
            g_callbacks = 0u;
            bad = HAL_TIM_Base_Stop(&g_tim) == HAL_OK ? 0u : 1u;
            if ((TIM2->CR1 & TIM_CR1_CEN) != 0u) { bad = 1u; }
            if (bad != 0u) { __HAL_TIM_DISABLE(&g_tim); } /* best effort, not proof */
            batch_stop_result(&g_batch, bad);
            a.kind = ACT_NONE;
        } else { /* ACT_CLEAN is forbidden here; foreground alone performs it. */
            g_callbacks = 0u; __HAL_TIM_DISABLE(&g_tim); return;
        }
    }
}
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
static uint32_t cleanup_hardware(void)
{
    uint32_t bad = 0u, i;
    /* Disable only device IRQs: SysTick MUST continue for HAL timeout accounting. */
    irq_enable(0u);
    if (HAL_TIM_Base_Stop(&g_tim) != HAL_OK) { bad = 1u; }
    if ((TIM2->CR1 & TIM_CR1_CEN) != 0u) { __HAL_TIM_DISABLE(&g_tim); bad = 1u; }
    if (HAL_ADC_Stop_DMA(&g_adc) != HAL_OK) { bad = 1u; }
    if (HAL_UART_AbortTransmit(&g_uart) != HAL_OK) { bad = 1u; }
    if ((DMA2_Stream0->CR & DMA_SxCR_EN) != 0u ||
        (DMA1_Stream6->CR & DMA_SxCR_EN) != 0u) { bad = 1u; }
    if (bad != 0u) { return 1u; } /* NO buffer clear, NO restart, IRQs remain disabled. */
    if (HAL_DMA_DeInit(&g_adc_dma) != HAL_OK || HAL_DMA_DeInit(&g_tx_dma) != HAL_OK) { return 1u; }
    if (HAL_DMA_Init(&g_adc_dma) != HAL_OK || HAL_DMA_Init(&g_tx_dma) != HAL_OK) { return 1u; }
    if (HAL_ADC_DeInit(&g_adc) != HAL_OK || HAL_UART_DeInit(&g_uart) != HAL_OK) { return 1u; }
    if (adc_uart_init() != 0u) { return 1u; }
    /* Peripheral flags first, NVIC pending second. No old stream may still generate events. */
    __HAL_ADC_CLEAR_FLAG(&g_adc, ADC_FLAG_OVR | ADC_FLAG_EOC | ADC_FLAG_STRT);
    __HAL_UART_CLEAR_FLAG(&g_uart, UART_FLAG_TC);
    __HAL_TIM_CLEAR_FLAG(&g_tim, TIM_FLAG_UPDATE);
    for (i = 0u; i < 4u; ++i) { HAL_NVIC_ClearPendingIRQ(g_irqs[i]); }
    __DMB();
    return 0u;
}
uint32_t Reference_Init(const ReferencePins *pins)
{
    BatchAction a = {0};
    uint32_t i, p;
    if (pins == NULL || g_ready != 0u) { return 1u; }
    if (pins->supply_mv < 2700u || pins->supply_mv > 3600u ||
        one_pin(pins->adc_pin) == 0u || one_pin(pins->tx_pin) == 0u ||
        pins->adc_channel > ADC_CHANNEL_15 || pins->tx_alternate > 15u) { return 1u; }
    g_pins = *pins;
    HAL_NVIC_SetPriorityGrouping(NVIC_PRIORITYGROUP_4);
    if (clock_init() != 0u || peripherals_init() != 0u) { return 1u; }
    for (i = 0u; i < 4u; ++i) { HAL_NVIC_SetPriority(g_irqs[i], 5u, 0u); }
    if (batch_init(&g_batch, 64u) == 0u) { return 1u; }
    p = lock();
    irq_enable(1u);
    if (batch_start(&g_batch, &a) == 0u) { unlock(p); return 1u; }
    short_actions(a);
    g_ready = 1u;
    i = g_batch.mode == MODE_RUNNING ? 0u : 1u;
    unlock(p);
    return i == 0u ? 0u : 2u; /* 2: initialized, but first arm faulted; service/recovery remain usable. */
}
void Reference_Service(void)
{
    uint32_t p, bad;
    BatchAction a = {0};
    if (g_ready == 0u) { return; }
    emit(EV_POLL, 0u, 0u);
    p = lock();
    if (g_recover == 0u || g_batch.mode != MODE_FAULT) { unlock(p); return; }
    g_recover = 0u;
    g_callbacks = 0u;
    if (batch_recover(&g_batch, &a) == 0u) { unlock(p); return; }
    unlock(p);
    bad = cleanup_hardware(); /* Main context with SysTick running, NEVER inside an IRQ. */
    p = lock();
    batch_cleanup_result(&g_batch, bad, &a);
    if (bad == 0u) { irq_enable(1u); }
    short_actions(a);
    unlock(p);
}
void Reference_RequestRecovery(void)
{
    uint32_t p = lock();
    if (g_ready != 0u && g_batch.mode == MODE_FAULT) { g_recover = 1u; }
    unlock(p);
}
void Reference_GetDiag(ReferenceDiag *out)
{
    uint32_t p = lock();
    out->mode = g_batch.mode; out->session = g_batch.session;
    out->current_fault = g_batch.current_fault; out->first_fault = g_batch.first_fault;
    out->stop_ok = g_batch.stop_ok; out->stop_errors = g_batch.stop_errors;
    out->cleanup_errors = g_batch.cleanup_errors;
    out->ht_count = g_ht; out->tc_count = g_tc; out->tx_count = g_tx;
    out->error_count = g_error; out->last_hal_error = g_last_hal_error;
    unlock(p);
}
void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *h)
{ if (h == &g_adc) { ++g_ht; emit(EV_HT, 0u, 0u); } }
void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *h)
{ if (h == &g_adc) { ++g_tc; emit(EV_TC, 1u, 0u); } }
void HAL_UART_TxHalfCpltCallback(UART_HandleTypeDef *h)
{ (void)h; /* Progress only: NEVER release the batch here. */ }
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

### 9.9 `target/reference_main.c`

目标入口和使用；7个板级选择缺失就明确报错；初始化失败与运行故障分开处理。

```c
/* This file deliberately refuses to invent board wiring or a supply voltage. */
#include "reference_f407.h"
#if !defined(BOARD_ADC_GPIO_PORT) || !defined(BOARD_ADC_GPIO_PIN) || \
    !defined(BOARD_ADC_CHANNEL) || !defined(BOARD_TX_GPIO_PORT) || \
    !defined(BOARD_TX_GPIO_PIN) || !defined(BOARD_TX_GPIO_AF) || !defined(BOARD_SUPPLY_MV)
#error "Supply all seven BOARD_* selections after checking your package, schematic and power."
#else
int main(void)
{
    const ReferencePins pins = {
        BOARD_ADC_GPIO_PORT, BOARD_ADC_GPIO_PIN, BOARD_ADC_CHANNEL,
        BOARD_TX_GPIO_PORT, BOARD_TX_GPIO_PIN, BOARD_TX_GPIO_AF, BOARD_SUPPLY_MV
    };
    HAL_Init();
    if (Reference_Init(&pins) == 1u) {
        __disable_irq();
        for (;;) { /* Init failure is observable in debugger; no automatic retry. */ }
    }
    for (;;) { Reference_Service(); }
    /* Operator-controlled recovery calls Reference_RequestRecovery(), not a reset loop. */
}
#endif
```

## 10. 常见错误

| 错误 | 为什么错 | 本课怎样发现 |
|---|---|---|
| 让 Fake 自己决定 HT 后应该发送哪一半 | 可能与生产实现犯同样错误，互相“证明” | 固定预言写 A/B、token1/2/3；Fake 只执行请求 |
| 只断言 mode==RUNNING | 错发地址、提前归还也可能仍 RUNNING | 同时看半区状态、活动槽、动作顺序/次数、128字节数据 |
| HAL_UART_Transmit_DMA 返回 HAL_OK 就 FREE | 只说明启动，不说明 DMA/串行发送完成 | POLL70 断言 A 仍 TX；只由匹配 DONE归还 |
| 等号处一边允许、一边拒绝 | 主循环与回调可能对同一个 tick 给出不同结果 | 127、128、129及回绕两侧均有反例；变异等号检查 |
| 忙就覆盖槽，或把重复完成当成功 | 有效地址仍可能对应错误代次的数据 | busy/wrong-token/duplicate-completion 各自断言 |
| 先清数组再停止 DMA | 真正写者或读者可能仍在使用数组 | 故障保持 HALF_TX；只有 CLEAN成功后 new_session 清数组 |
| 首错被 stop/abort 错误覆盖 | 排错时丢掉第一个原因 | 历史快照逐字段保留；stop/cleanup 错误独立计数 |
| 在关中断或 IRQ 内阻塞 abort | HAL超时所需tick可能不能推进，且延长停止窗口 | IRQ短操作；阻塞清理留给前台、保留SysTick [S4] |
| DMA TC 后不启 USART2 IRQ | normal模式HAL用户完成回调可能不到达 | 核对实际包回调链；待目标观察TX计数/TCIE/TC [S4] |
| 给真实 IRQ 补当前 session 就认为旧中断已排除 | 外设没有携带这个编号，旧事件可被错贴新标签 | 先排空硬件再换会话；主机 STALE 场景不能替它证明 |
| CTest 0个测试也当通过，或把预期失败混进正常通过率 | 根本没运行目标断言，或混淆失败语义 | 这里必须看到 batch_contract 的1/1；故意失败单独运行记录 [S7] |
| 主机通过就设置 hardware_verified=true | 没有验证时钟/请求/调度/电气 | 证据分栏；硬件状态始终false |

## 11. 调试观察点

### 主机：先重现，再缩短反例

1. 保留失败输出中的场景名、行号、表达式和 TRACE。先区分配置失败、编译失败、程序断言失败、Fake日志溢出；不能把所有非零都叫“发现了被测逻辑错误”。
2. 首先运行 `--minimal`，在 `batch_event` 设置断点，观察事件进入前后的 `mode/expected_half/half_state/tx_active/tx_token` 与输出动作。
3. 对等号问题只保留 `START → HT64 → DONE128`；先手算 elapsed=64，再单步。不要先改成“只要这次看起来能发完就成功”。
4. 用 `--demo-failure` 看缺少 DONE 时为何 A 必须仍为 TX；再读真实完成例的差别。日志只是观察，正确性仍取决于独立契约。
5. 构建目录是可再生的，源文件和错误日志不是临时垃圾；本任务不删除用户文件，也不运行任何清理/重置命令。

### 目标：找第一个没有兑现的事件

| 观察位置 | 需要读的事实 | 不能从它单独推出的结论 |
|---|---|---|
| RCC/Flash/TIM2 | SWS、PPRE、PSC/ARR、CEN；计数是否运行 | 标称频率和真实采样频率完全一致 |
| ADC/DMA2 | EXTSEL/EXTEN、OVR、NDTR、M0AR、HT/TC及错误标志 | 模拟值正确、没有所有权冲突 |
| `Reference_GetDiag` | HT/TC/TX/error计数，current_fault/first_fault，stop_ok，清理错误数 | 这些数值自动给出每次中断的真实发生时间 |
| DMA1/UART | 地址/Size/EN、DMAT、TCIE/TC、USART IRQ到达与HAL回调 | 只看DMA TC就认为线上最后一位已完成 |
| 停源现场 | 故障原因、TIM2.CEN、两stream EN、在途ADC状态 | 清 CEN 能撤回已触发转换或已发送字节 |
| 逻辑分析仪/串口记录 | 实际TX边沿、帧字节数、若加入标记则标记延迟 | 软件标记必然等于硬件事件时刻 |

本课没有为观测额外占用一个未指定的 GPIO。若自行增加标记脚，先记录板级映射和标记开销；断点也可能扭曲实时流，不用停在回调里的断点证明自然运行满足期限。沿用 L038 的测量方法，实测数据另外保存，不填造波形或时间戳。

## 12. 实战实验

### 实验 A：先在纸上，再运行

不看 `batch.c`，写出第6.1节前三个输入后的所有权、动作及token。运行主机最小组/全组，保存命令、编译器版本、退出码和日志。完成条件是能解释每个变化，不是只截图最后一行。若与纸面预言不同，先检查预言和契约，再判断代码。

### 实验 B：围住一条边界

用同一初始夹具分别输入 DONE127、DONE128、POLL129，不在同一个已故障实例上继续比较另一个“独立场景”。说明为什么每个场景要重新初始化。再检查回绕例：`UINT32_MAX−31 → 31` 的差是63，`→32` 的差是64，前者可归还、后者不可。

### 实验 C：验证你的检查真的会报警

运行故意失败入口，要求退出1且指出缺失 TX_DONE；再运行两份错误副本检查，要求输出 `mutants_detected=2/2`。如果脚本因为编译器不在 PATH 或进程崩溃而失败，不得记成“错误副本被断言检出”。可使用 `--cc` 指定实际 gcc 路径；副本必须留在本课 `build/` 内，原始生产文件不得被修改。

### 实验 D：错误、失败清理与显式恢复

读 `stop_failure_then_explicit_recovery`：输入DEVICE错误并令STOP失败，保存首错；令CLEAN失败一次，确认仍FAULT；再允许清理成功，确认动作CLEAN→ARM、session变2、样本清零、历史首错不变。最后输入旧会话DONE，确认不归还新会话内存。解释“错误发生后经过一段时间”为什么不是恢复授权。

### 实验 E：可选的目标验证计划，不在本次执行

在用户已有具体板卡、另行允许构建/烧录后再做：

1. 首先验证标称时钟链、DMA地址和正常回调链，记录真实TX发送时间与发布到归还时间。
2. 在目标的受控实验分支降低波特率或制造有限主循环延迟，预先推算何时可能超期；不要在产品运行中随意长时间关中断。
3. 观察故障后 TIM2.CEN 关闭、主循环清理前所有权保持，清理失败不重新启源；核对真实停源延迟与下一触发的关系。
4. 仅在隔离的调试配置中验证缺失 USART IRQ 会怎样影响 HAL_TX完成；按目标包行为观测，不把主机事件记录替代它。
5. 记录实际误差和未覆盖组合。若需要改变窗口以留延迟余量，重新写契约并增加该配置测试，不能只改数字后沿用旧证据。

这些是**待执行的实验与判据**，不是本次已经完成的硬件任务；本课不执行烧录。

## 13. 自检题

1. Fake 和被测对象的职责分界是什么？如果 Fake 也维护 expected_half，会有什么循环论证风险？
2. HT64 后，TX启动成功、POLL70、DONE76 各自能否释放 A？用状态和动作回答。
3. 为什么 DONE128 必须失败，而 DONE127 可以成功？若 POLL 与 DONE 分别用不同等号规则会怎样？
4. 为什么活动半区不能在 START/STOP返回错误时立即清零？谁能确认硬件不再读写？
5. 恢复成功时哪些字段更新、哪些历史字段保留？为什么还要清外设标志和 NVIC pending？
6. 主机旧session测试通过，为什么仍不能证明板端没有过期中断？
7. 本课 `checks=236`、CTest1/1、目标主机语法检查，分别证明什么？缺少哪些证据才不能声称满足真实重用期限？

答题应包含至少一条具体事件轨迹与反例。参考线索依次是第4.2、6.1、4.3/6.2、7.4/8.2、4.1/7.3、7.4、7.2/8节；不把看过这些问题直接记为已掌握。

## 14. 面试题

**问：为什么不直接在电脑上调用 HAL_ADC_Start_DMA？**
答题要点：主机没有对应外设/地址空间；本课复用的是交接决策，适配层把可观察动作与真实HAL分开。Fake只代表有限输入/返回契约，不代表ADC。

**问：怎样证明测试不是只测试了自己的替身？**
答题要点：独立编译真实生产文件；预期先写；同时检查对象状态、具体数据和动作；植入等号/token错误后测试必须失败；仍不能消除契约理解错误。

**问：DMA发送完成之后，为什么还要USART中断？**
答题要点：所选F4包normal模式先在DMA完成路径关闭DMAT并打开TCIE，再由USART TC路径进入用户TxCplt；要说清版本边界，不把这个答案套到所有系列/模式。[S4]

**问：首错与停止失败该怎样同时保留？**
答题要点：首错快照冻结，当前会话故障单独表示，停止/清理失败独立计数；先限制上游，清理结果不覆盖最初原因，不自动恢复。

**问：所有主机测试都过了，交付给硬件同事前还缺什么？**
答题要点：实际料号/原理图/供电/引脚；固定包和目标构建；链接map的DMA可达性；真实IRQ/触发/完成链；最坏延迟和线速/模拟测量；明确哪些检查仍未完成。

## 15. 延伸思考

- 如果把半区长度从64改成32，输入节拍仍1kHz，逻辑窗口和UART时间怎样变？先计算，再修改测试参数；不能仅凭“原来的断言还过”接受新预算。
- 如果真实IRQ延迟可能超过一个采样周期，单靠在HT/TC回调里停TIM2能否避免覆写？应增加什么时间证据或改变上游/缓冲策略？本课不假装已有答案可直接上板。
- 如果契约把等于deadline定义为成功，需要同时改哪些实现、预言和硬件安全条件？为什么不能仅为让测试变绿就改预言？
- 新系列若需要缓存维护，把完成标志更新放到正确位置是否就足够？先记录需要核对的DMA/内存/缓存所有权边界，具体维护机制留到后续课。

## 16. 本节总结

1. 主机测试的关键是**受控事件边界**，不是把外设名字写进普通函数。
2. 预期行为先于实现：A/B、编号、动作顺序和截止等号都必须独立写定。
3. 发送启动不是完成；重复、过期、忙和错误不能偷偷归还或覆盖内存。
4. 首个外部故障动作是停源；只有确认清理成功并显式恢复，才能清缓冲区、换会话和重新启源。
5. 真实共用的C逻辑、可失败的测试和完整F407适配已交付；主机证据只覆盖模型契约。时钟、外设、并发、模拟和真实期限仍需要目标工程与仪器证据。

## 17. 下一步

按课程路线继续 `debugging-verification / unit-test`，把本课已经明确的契约整理成可维护的测试组织、隔离与回归流程，讨论夹具共享、失败定位及怎样扩充覆盖；不要用引入更多框架替代独立预言。

Teacher 阶段只创建 L039；Reviewer 在本次验证通过后将本课标记为 `reviewed`，仅把课程进度推进到同阶段 `unit-test`（下一编号 40），没有提前生成下一课。审查通过表示课程资产通过检查，不表示学习者已掌握或已完成硬件实验；`[mastery]` 保持不变，只有用户的答题/实验/复习才可成为后续掌握度更新依据。既有课程、系统规则和模板未改动。

## 18. 参考资料

本节编号与 `lesson.json.sources` 一一对应。访问日期均为2026-10-21。文档/页面和本地官方包文件的读取范围及哈希在 `evidence/source-audit.json`；只保存定位与个人实现分析，不收录完整第三方源码/PDF。

- **[S1] ST RM0090，Rev22，2026-05。** STM32F405/415、F407/417、F42/F43参考手册；本课限F407。核对§3.5 Flash、§7 RCC、§10 DMA（Rev22表43/44）、§13 ADC（外触发、转换、DMA/OVR）、§18 TIM2、§30 USART。官方地址：`https://www.st.com/resource/en/reference_manual/dm00031020.pdf`。
- **[S2] ST DS8626，Rev12，2026-03。** STM32F405xx/407xx数据手册；器件范围、引脚/AF、电气/HSI/PLL/ADC约束。引脚选择还必须对照实际封装/板卡，数据手册不是板级接线证明。官方地址：`https://www.st.com/resource/en/datasheet/stm32f407vg.pdf`。
- **[S3] ST UM1725，Rev8，2023-03。** STM32F4 HAL/LL说明；HAL初始化、句柄与ADC/DMA/TIM/UART接口，精确normal TX/abort行为再以固定包阅读位置核对。官方地址：`https://www.st.com/resource/en/user_manual/dm00105879.pdf`。
- **[S4] ST STM32CubeF4 软件版本页；基包1.28.0+Patch1.28.3。** 同时只读核对本机包package.xml、HAL core/Cortex/ADC/DMA/UART/TIM/RCC文件；重点是UART_DMATransmitCplt→TCIE→UART_EndTransmit_IT、HAL_UART_AbortTransmit、HAL_ADC_Start/Stop_DMA、HAL_DMA_Abort/DeInit。官方地址：`https://www.st.com/en/embedded-software/stm32cubef4.sw-versions.html`。没有把本地包存在等同于目标编译成功。
- **[S5] ST UM1718，Rev51，2026-05。** STM32CubeMX用户手册；Pinout、Clock Configuration、DMA/NVIC、项目与代码生成设置。官方地址：`https://www.st.com.cn/resource/en/user_manual/dm00104712-stm32cubemx-for-stm32-configuration-and-initialization-c-code-generation-stmicroelectronics.pdf`。
- **[S6] ST STM32CubeMX软件版本页，参考分支6.18.1。** 只核对版本，未启动应用；不混用CubeMX2版本号。官方地址：`https://www.st.com/en/development-tools/stm32cubemx.sw-versions.html`。
- **[S7] CMake add_test 官方手册，在线4.4.4；本机CMake/CTest4.4.3。** 核对测试注册、目标可执行程序、默认退出结果语义；同时读取本机官方help。该许可域来源不计为STM32硬件第一方证据。官方地址：`https://cmake.org/cmake/help/v4.4/command/add_test.html`。
