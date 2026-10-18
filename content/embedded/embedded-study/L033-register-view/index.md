+++
title = "寄存器视图：有时序、可证伪的观测证据"
date = "2026-10-17T23:04:12+08:00"
lastmod = "2026-10-17T23:04:12+08:00"
summary = "核心目标：建立寄存器视图作为有时序、可证伪的观测证据这一心智模型，并据此为 STM32F407xx 的时钟、定时器、DMA 与外设状态设计可重复的调试观察流程。新核心概念：寄存器视图的取样语义与证据边界。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 33
tags = ["register-view", "debugging", "evidence", "snapshot", "read-side-effect", "stm32f407", "tim2", "dma", "hal", "ll", "host-fake", "c11"]
source_ids = ["st-rm0090-register-view", "st-ds8626-register-view", "st-um1725-register-view"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L033"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 33 课：寄存器视图——有时序、可证伪的观测证据

寄存器视图看起来像一张外设“体检表”，但它不是硬件状态的连续录像。窗口中的每个值，都是调试器在某个时刻通过调试访问读到的样本；字段可能正在变化，读取本身可能改变状态，而暂停 CPU 也可能改变外设之间原有的时间关系。

本课只推进一个新核心概念：**寄存器视图的取样语义与证据边界**。先用 C11 Host Fake（主机替身）把“何时读、读什么、读取是否有副作用、能推出什么”变成可测试契约，再落到 STM32F407xx 的 RCC（Reset and Clock Control，复位与时钟控制）、TIM2 和可选 ADC1-DMA2 观察链。Host Fake 只验证观察规则，不能证明真实地址、真实时钟、调试器行为或外部信号。

参考实现以 RM0090 Rev 22、DS8626 Rev 12 和 UM1725 Rev 8 为边界。[S1][S2][S3] 当前没有完整订货料号、开发板、调试器、板级时钟、目标工程、构建输出、烧录记录或测量结果。STM32 代码均为**参考实现，待目标工程编译和上板验证**；本课 `hardware_verified=false`。

## 1. 本节目标

核心目标与本次 `plan.json` 一致：**建立寄存器视图作为有时序、可证伪的观测证据这一心智模型，并据此为 STM32F407xx 的时钟、定时器、DMA 与外设状态设计可重复的调试观察流程。**

新核心概念与计划一致：**寄存器视图的取样语义与证据边界**。

完成本课后，你应能：

1. 把“看一下寄存器”改写成带对象、预期、时机、副作用和交叉证据的观察规格；
2. 区分静态配置、运行时状态和外部效果，不让一次快照越级证明连续行为；
3. 解释观察规格、寄存器快照、语义注释和交叉证据由谁定义、持有和注入；
4. 用 Host Fake 复现易变字段、读取即清除字段、暂停与恢复以及链路分段失败；
5. 按时钟/复位、TIM2、可选 ADC/DMA、IRQ 回调的顺序观察 STM32F407xx；
6. 说明 HAL（Hardware Abstraction Layer，硬件抽象层）意图如何对应 LL（Low-Layer，低层驱动）操作、寄存器字段和硬件事件；
7. 迁移到 F7、H5 或 H7 时保留观察契约，同时重新核对地址、字段、时钟域、缓存、安全属性和调试冻结行为。

## 2. 它解决什么问题

### 2.1 一栏数值不是一段历史

假设调试器显示 `TIM2_CNT=357`。它最多直接支持这一句：

> 在本次调试访问完成时，工具把 TIM2 的计数器字段解释为 357。

它不能单独证明：

- TIM2 一直以预期频率计数；
- 357 是暂停前还是暂停后得到的值；
- 更新事件按固定周期发生；
- ADC 收到了每个触发；
- DMA 没有丢数据；
- 外部引脚上出现了预期波形。

这些结论跨越了时间或跨越了模块，需要相邻样本、事件计数、缓冲区内容或外部测量等独立证据。

### 2.2 观察会进入被观察系统

调试器通常通过 SWD/JTAG 和片上调试访问端口读取地址空间。处理器暂停不等于所有外设都停止；在 F407 上，TIM2 在内核暂停时是否冻结受调试冻结配置控制。[S1] 如果 TIM2 被冻住而 DMA、ADC 或另一时钟域的行为不同，原来的相对时序已经改变。

另一类风险是读副作用（read side effect，读取副作用）：某些状态或数据寄存器在读取后会清标志、弹出数据或推进硬件状态。不能把 IDE 的自动刷新当作无害操作。对本课明确核对的 F407 字段：

- `TIM2_CNT` 是运行中易变值；两次读取可以不同；
- `TIM2_SR.UIF` 由更新事件置位，软件写 0 清除；只读 `SR` 不应被写成“已确认并清除”；[S1]
- `DMA2_Stream0->NDTR` 在传输中递减，循环模式重装后数值可跳回初值；单次 `NDTR=64` 不能证明此前每项都正确；[S1]
- DMA 状态从 `LISR/HISR` 读取，清除通过 `LIFCR/HIFCR` 的对应清除位完成；观察窗口不得为了刷新而写清除寄存器；[S1]
- ADC 数据寄存器、通信外设数据寄存器和清除序列必须逐项查目标参考手册；本课不对未纳入观察表的字段猜测。

### 2.3 本课的证据边界

把证据分成三层：

| 层次 | 典型证据 | 可以支持 | 不能单独支持 |
| --- | --- | --- | --- |
| 静态配置 | RCC 门控、PSC、ARR、DMA 地址与模式 | 初始化意图已写入相应字段 | 外设正在运行、频率正确、数据有效 |
| 运行状态 | CEN、相邻 CNT、UIF、NDTR、IRQ/回调计数 | 指定取样条件下发生了状态变化 | 外部信号质量、所有事件都未丢失 |
| 外部效果 | 示波器/逻辑分析仪、接收端数据、已校准测量 | 引脚或链路出现了可观测效果 | 内部每个配置字段都正确 |

寄存器快照很适合**证伪**。例如 `RCC_APB1ENR.TIM2EN=0` 足以否定“TIM2 已具备运行前提”；但 `TIM2EN=1` 只说明门控已打开，不足以证明计数器正在前进。

## 3. 必要前置知识

以下内容已在 `learning-state.toml.completed` 中记录，可直接使用：

- `clock-tree`：振荡源、PLL、AHB/APB、门控、复位和最终外设时钟；
- `hal-ll-register-crosswalk`：HAL 调用表达软件意图，寄存器读回表达硬件可见状态；
- `timer-trigger-routing`：TIM2 update/TRGO 到 ADC 的触发链；
- `adc-timer-dma-pipeline`：ADC 请求、DMA stream、NDTR、HT/TC/error 和缓冲区边界；
- `peripheral-integration-lab`：回调只发布事件，资源拥有者在延后路径停止和恢复。

断点/观察点、故障分析、逻辑分析仪、缓存一致性和 trace（跟踪）尚未作为课程完成，不是本课隐含前置。本课只说明它们为何能成为后续交叉证据，不展开其完整机制。

## 4. 核心原理

### 4.1 一个样本的完整含义

一个可审计样本不是裸 `uint32_t value`，而是六元组：

```text
sample = {
  object,       // 哪个器件、外设、实例和字段
  value,        // 本次读回值
  moment,       // 启动前、运行中、暂停后、IRQ 入口等
  observer,     // IDE 自动刷新、脚本、固件只读快照等
  semantics,    // 静态、易变、读取清除、写清除、数据端口……
  conditions    // CPU/外设是否暂停，时钟、错误和工具版本
}
```

如果缺少 `moment`，相邻两次值无法排序；如果缺少 `semantics`，不知道读取是否破坏现场；如果缺少 `conditions`，暂停后的值可能被误当作自由运行证据。

### 4.2 四个对象、持有者和调用流

| 对象 | 解决的问题 | 在哪里定义、谁持有 | 谁注入 | 调用/证据如何流动 |
| --- | --- | --- | --- | --- |
| 观察点规格 | 把模糊查看变成可证伪问题 | 实验文件中的静态常量表；实验作者持有 | 作者填入对象、预期、时机、语义、来源、交叉证据 | 观察者逐项执行并给出通过/失败/不充分 |
| 寄存器快照 | 固定一次读取结果和次序 | 调试工具导出或固件静态结构；实验记录持有 | 调试访问或固件读取函数注入样本 | 硬件状态 -> 总线读取 -> 快照 -> 比较预期 |
| 语义注释 | 限制字段的合法读法和结论 | 观察规格旁的来源核对表；课程/项目维护者持有 | RM、数据手册和驱动头文件提供定义 | 字段语义 -> 决定能否重复读、如何清除、允许何种结论 |
| 交叉证据 | 防止一次样本推出过强结论 | 实验记录中的第二观察路径 | 回调计数、相邻快照、缓冲内容或外部测量注入 | 第一证据提出假设 -> 第二证据支持或否定 |

控制流是“进入规定时机 -> 采样 -> 记录 -> 恢复运行”；数据流是“字段值进入快照”；事件流是“更新、DMA 完成或错误使字段和软件计数发生变化”。三条流必须分别记录。

### 4.3 观察规格的最小判定规则

一个观察点只有同时具备以下内容，才允许标记为“满足预期”：

1. **对象唯一**：至少包含器件系列、外设实例和字段；
2. **预期可证伪**：如“启动前 `CEN=0`”，而不是“定时器正常”；
3. **取样时机明确**：如 `HAL_TIM_Base_Start_IT` 返回后、第一次回调前；
4. **语义已核对**：静态、易变、读清除、写清除或未知；
5. **暂停影响已记录**：CPU、TIM2 和数据链是否会继续推进；
6. **来源可定位**：至少指出手册和章节/表；
7. **结论不越界**：配置证据只回答配置，运行证据只回答本次运行；
8. **需要时有交叉证据**：凡是关于时间、频率、完整性或外部效果的结论都需要第二路径。

“未知”不是失败，而是合法结果。它要求停止推断并补来源或换观察方法。

### 4.4 SVD 的角色

SVD（System View Description，系统视图描述）把外设地址、寄存器和位域名称提供给工具，使原始地址能显示成 `TIM2.CR1.CEN`。SVD 提高可读性，但不是硬件行为规范：

- 工具载入了错误器件的 SVD，名称和地址可能错位；
- SVD 未必完整表达读取副作用、清除序列或保留位约束；
- 同名字段在不同系列上不保证地址、宽度和行为相同；
- 最终语义以目标器件参考手册、数据手册和对应 CMSIS 头文件为核对入口。

因此第一步总是记录完整器件和工具所用设备描述，不能用“窗口里有这个名字”替代目标确认。

## 5. 关键术语与直观模型

| 术语 | 准确含义 | 本课直观模型 |
| --- | --- | --- |
| SFR | Special Function Register，特殊功能寄存器；映射到处理器地址空间的硬件控制/状态接口 | 一扇有规则的窗口，不是普通内存变量 |
| 快照 | 一次或一组有序读取保存下来的状态样本 | 一张带时间和拍摄条件的照片 |
| 易变字段 | 硬件、DMA 或其他执行主体可异步改变的字段 | 读完就可能过期的数值 |
| 读副作用 | 一次读取同时改变标志、FIFO 或后续状态 | 拿走票据时票据从队列消失 |
| 调试暂停 | 调试器请求内核停止执行指令 | 按下暂停键，但并不保证所有外设同时定格 |
| DWT | Data Watchpoint and Trace，数据观察点与跟踪单元 | 后续用于观察访问或计时的内核调试资源，本课不展开配置 |
| CoreSight | Arm 的片上调试与跟踪架构 | 调试访问、断点和跟踪资源的总框架 |
| 交叉证据 | 与第一观察路径相对独立的证据 | 用第二个角度检查同一假设 |

## 6. 从输入到结果的完整流程

### 6.1 先写假设，再打开窗口

以“TIM2 是否按预期启动”为例：

```text
假设 H0：TIM2 没有运行
预期链：
  RCC 门控已开
  -> TIM2 PSC/ARR 与设计一致
  -> 启动前 CEN=0
  -> 启动后 CEN=1
  -> 自由运行条件下两个有序 CNT 样本不同
  -> update 事件使 UIF 或回调计数发生变化
  -> 由已知 TIM2CLK、PSC、ARR 推导的周期与独立测量相符
```

其中任一前置失败，都能定位“首次不满足点”。最后一项涉及连续时间，必须由定时记录、DWT/trace 或外部测量交叉验证；单次 `CNT`/`UIF` 不够。

### 6.2 推荐观察顺序

1. 记录完整 MCU、手册版本、Cube 固件包、IDE/调试服务器和 SVD 选择；
2. 在源尚未启动时观察时钟、复位和静态配置；
3. 明确冻结策略，再启动源；
4. 以有限次数采样易变字段，不让自动刷新无界读取；
5. 对每个运行结论加入回调计数或第二快照；
6. 扩展到 ADC/DMA 时按“源 -> 触发 -> 请求 -> 搬运 -> 回调”逐段观察；
7. 错误发生时先保存只读快照和 HAL error code，再由资源拥有者停源、清理；
8. 对频率、信号和数据内容使用适当的外部或端到端证据。

### 6.3 何时停止读取

出现下列任一情况，应停止自动刷新并先查资料：

- 字段被标为 data、FIFO、pop、clear-on-read 或需要组合清除序列；
- 读取顺序本身属于中断处理协议；
- 多个窗口、脚本和固件都可能读取同一清除型状态；
- 不知道暂停时该外设是否冻结；
- SVD 名称与参考手册或 CMSIS 头文件不一致。

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

| 层级 | 能力 | 工作原理与证据链 | 本课边界/后续落点 |
| --- | --- | --- | --- |
| 基础 | 查看 RCC、TIM、DMA 的配置和状态 | 调试访问读取映射寄存器，SVD 将地址显示为字段名 | 本课建立观察规格与结论边界 |
| 进阶 | 用分段证据定位链路首次失败点 | `时钟 -> 源 -> 触发 -> DMA -> IRQ/回调` 逐段读取并交叉比较 | 本课用 TIM2 和可选 ADC-DMA 演示 |
| 高级 | 非侵入 trace、访问观察点、冻结矩阵和副作用审计 | CoreSight 事件/数据路径采集执行或总线活动，减少反复暂停与轮询；仍需时间戳和溢出边界 | `breakpoint-watchpoint`、`fault-analysis`、性能与 trace 专题 |
| 跨外设联动 | 观察 `RCC -> TIM2 TRGO -> ADC1 -> DMA2 -> IRQ` | TIM2 update 产生内部触发，ADC 完成产生 DMA 请求，stream 更新内存和标志，IRQ 进入 HAL 回调 | 本课只训练观察顺序，不重讲采集所有权 |
| 系列差异 | 保留契约，重查实现 | 观察规格可迁移；地址、DMA 架构、缓存/域、安全授权和冻结位不可照抄 | 选定 F7/H5/H7 完整料号后查其第一方 RM/DS/Cube 包 |

高级能力不是“更大的寄存器窗口”。它解决的是暂停和轮询过度扰动实时系统的问题：硬件事件先进入 CoreSight 或目标跟踪资源，再由探针输出带顺序的信息。触发、数据、缓冲与丢失条件仍必须定义；否则 trace 也只是另一堆无上下文数值。后续 `breakpoint-watchpoint` 负责访问触发，`fault-analysis` 负责异常现场，`logic-analyzer` 负责外部时序，缓存一致性课程负责 CPU 与 DMA 可见性。

#### F4/F7/H5/H7 迁移审计表

| 目标 | 可保留 | 必须用目标资料重新核对 |
| --- | --- | --- |
| F4/F407xx | 对象、时机、语义、交叉证据和分段顺序 | 完整料号、SVD、时钟源、DBGMCU 冻结位、DMA stream/channel 和具体字段 |
| F7 | 同一观察契约 | 缓存参与后的可见性、总线访问路径、DMA 映射、冻结行为和对应 CubeF7 API；本课不写具体值 |
| H5 | 同一观察契约 | 安全/非安全调试授权、目标 DMA 与请求路由、时钟选择、寄存器安全属性和 CubeH5 API；本课不写具体值 |
| H7 | 同一观察契约 | 多时钟/电源域、缓存、目标内存可达性、DMA 架构、冻结矩阵和 CubeH7 API；本课不写具体值 |

表中后 3 行是迁移检查任务，不是器件配置结论。选定完整目标并加入对应第一方来源前，不复制 F407 地址、位值、stream/channel 或工具设置。

### 7.2 参考目标与时钟/复位链

#### 参考边界

- 器件系列：STM32F407xx；完整订货料号和封装待填；
- 参考手册：RM0090 Rev 22；数据手册：DS8626 Rev 12；HAL/LL 文档：UM1725 Rev 8；[S1][S2][S3]
- 板级未知：不声明 HSE、LSE、引脚、外部电路、调试连接或电源条件；
- 为得到完整可计算示例，时钟源选择片内 HSI；下述 168 MHz/`FLASH_LATENCY_5` 配置以**已经确认 `VDD=2.7..3.6 V`**为执行前提。未确认供电时只能做静态审计，不得运行该配置；其他电压范围必须按 DS8626 表 15 重新选择最高频率和 Flash wait states（等待周期）。

#### 一条完整、可计算的参考链

```text
HSI = 16 MHz
  -> PLLM = 16，PLL 输入 = 1 MHz
  -> PLLN = 336，VCO = 336 MHz
  -> PLLP = 2，SYSCLK = 168 MHz
  -> AHB HPRE = /1，HCLK = 168 MHz
  -> APB1 PPRE1 = /4，PCLK1 = 42 MHz
  -> APB1 预分频不为 1，F407 TIM2CLK = 2 * PCLK1 = 84 MHz
  -> RCC_APB1ENR.TIM2EN = 1
  -> TIM2 PSC = 8399，计数 tick = 84 MHz / 8400 = 10 kHz
  -> TIM2 ARR = 9，update 频率 = 10 kHz / 10 = 1 kHz
```

上述 16 MHz HSI、PLL 约束、总线最大频率和 APB 定时器倍频规则只用于 RM0090/DS8626 覆盖的本参考目标。[S1][S2] `FLASH_LATENCY_5` 只适用于本例声明的 `VDD=2.7..3.6 V`：`2.4..2.7 V` 需要 6 wait states，`2.1..2.4 V` 需要 7 wait states，`1.8..2.1 V` 时 Flash 访问最高 160 MHz，不能继续使用本例 168 MHz 配置。[S2] 真实板若改用 HSE，必须先填写晶振频率，再从 PLL 输入重新推导，不能只保留 `PLLN=336`。

`PSC` 和 `ARR` 都按“寄存器值加一”参与本例公式：

```text
f_update = f_TIM2CLK / (PSC + 1) / (ARR + 1)
```

`TIM2CLK`、`PSC`、`ARR` 是配置证据；要证明实际 1 kHz，还需计时或外部测量。

#### 门控、复位与调试冻结

```text
RCC_CR.HSION -> 等待 HSIRDY
  -> 配置 RCC_PLLCFGR
  -> RCC_CR.PLLON -> 等待 PLLRDY
  -> 配置 FLASH latency、HPRE、PPRE1、PPRE2
  -> RCC_CFGR.SW 选择 PLL -> 检查 SWS
  -> RCC_APB1ENR.TIM2EN = 1
  -> 如需恢复已知初态：TIM2RST 置 1 后释放为 0
  -> 写 TIM2 PSC/ARR/EGR/DIER/CR1
  -> CR1.CEN = 1 后才开始计数
```

读取 TIM2 地址不等于 TIM2 已获得内核时钟；应先核对门控。复位位一直保持为 1 时外设不能工作。调试暂停是否冻结 TIM2，由 `DBGMCU_APB1_FZ.DBG_TIM2_STOP` 决定；观察记录必须写明该位。本课的两种实验要分别测试“冻结 TIM2”和“不冻结 TIM2”，但不把其结果推广到 DMA、ADC 或其他系列。[S1]

### 7.3 CubeMX、HAL、LL 与寄存器对照

#### CubeMX/CubeMX2 配置清单

下列是待在实际工程执行的配置，不是本次已经生成的 `.ioc`：

1. 选择完整 STM32F407 订货料号，记录 CubeMX/CubeMX2 与 STM32CubeF4 版本，并从原理图/电源资料确认 `VDD`；未确认 `VDD=2.7..3.6 V` 时不得套用下述 168 MHz 配置；
2. `RCC`：使用 HSI，不启用尚未确认存在的外部晶振；
3. `Clock Configuration`：PLL source=HSI，`PLLM=16`、`PLLN=336`、`PLLP=2`、`PLLQ=7`，AHB `/1`、APB1 `/4`、APB2 `/2`；
4. `TIM2`：Internal Clock，Prescaler `8399`，Counter Period `9`，Up counter，Auto-reload preload 关闭；
5. `TIM2/NVIC`：若使用回调交叉证据，开启 TIM2 global interrupt；优先级必须按实际系统统一设计；
6. `SYS/Debug`：选择与实际探针连接相符的 Serial Wire 或 JTAG；不能由课程猜引脚是否可用；
7. 调试冻结：由固件显式调用 freeze/unfreeze 宏，避免依赖某个 IDE 的隐藏默认设置；
8. 可选 ADC-DMA 链：沿用已核对的 F407 `TIM2 TRGO -> ADC1 -> DMA2 Stream0/Channel0`，接收端先武装，最后启动 TIM2；[S1][S3]
9. 生成后审计 `.ioc`、`SystemClock_Config`、`MX_TIM2_Init`、MSP、IRQ handler 和目标 CMSIS 头文件，不以 GUI 截图替代读回。

实际供电、Flash latency、ADC 通道/引脚、模拟输入、调试器和测量点均为板级待填参数。

#### HAL 参考实现：时钟、TIM2 和观察快照

以下代码属于 STM32 BSP（Board Support Package，板级支持包）实现层。`htim2`、回调计数和快照对象均为静态生命周期，由 BSP 唯一持有；应用只调用初始化、启动和取样接口。它是**参考实现，待目标工程编译和上板验证**。

```c
#include "stm32f4xx_hal.h"
#include <stdint.h>

typedef enum {
    PROBE_OK = 0,
    PROBE_ERR_CLOCK = 1,
    PROBE_ERR_TIM_INIT = 2,
    PROBE_ERR_TIM_START = 3,
    PROBE_ERR_TIM_STOP = 4
} probe_status_t;

typedef struct {
    uint32_t sequence;
    uint32_t tick_ms;
    uint32_t rcc_apb1enr;
    uint32_t dbgmcu_apb1_fz;
    uint32_t tim_cr1;
    uint32_t tim_dier;
    uint32_t tim_sr;
    uint32_t tim_psc;
    uint32_t tim_arr;
    uint32_t tim_cnt;
    uint32_t update_callback_count;
} probe_tim2_snapshot_t;

static TIM_HandleTypeDef g_htim2;
static volatile uint32_t g_tim2_update_count;
static uint32_t g_snapshot_sequence;

static probe_status_t SystemClock_Config_Reference(void)
{
    RCC_OscInitTypeDef osc = {0};
    RCC_ClkInitTypeDef clk = {0};

    /* 执行前提：已从板级资料确认 VDD=2.7..3.6 V。 */
    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

    osc.OscillatorType = RCC_OSCILLATORTYPE_HSI;
    osc.HSIState = RCC_HSI_ON;
    osc.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
    osc.PLL.PLLState = RCC_PLL_ON;
    osc.PLL.PLLSource = RCC_PLLSOURCE_HSI;
    osc.PLL.PLLM = 16U;
    osc.PLL.PLLN = 336U;
    osc.PLL.PLLP = RCC_PLLP_DIV2;
    osc.PLL.PLLQ = 7U;
    if (HAL_RCC_OscConfig(&osc) != HAL_OK) {
        return PROBE_ERR_CLOCK;
    }

    clk.ClockType = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK |
                    RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    clk.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    clk.AHBCLKDivider = RCC_SYSCLK_DIV1;
    clk.APB1CLKDivider = RCC_HCLK_DIV4;
    clk.APB2CLKDivider = RCC_HCLK_DIV2;
    if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_5) != HAL_OK) {
        return PROBE_ERR_CLOCK;
    }
    return PROBE_OK;
}

void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *htim)
{
    if (htim->Instance == TIM2) {
        __HAL_RCC_TIM2_CLK_ENABLE();
        HAL_NVIC_SetPriority(TIM2_IRQn, 6U, 0U);
        HAL_NVIC_EnableIRQ(TIM2_IRQn);
    }
}

static probe_status_t Probe_TIM2_Init(void)
{
    TIM_MasterConfigTypeDef master = {0};

    g_htim2.Instance = TIM2;
    g_htim2.Init.Prescaler = 8399U;
    g_htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
    g_htim2.Init.Period = 9U;
    g_htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    g_htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    if (HAL_TIM_Base_Init(&g_htim2) != HAL_OK) {
        return PROBE_ERR_TIM_INIT;
    }

    master.MasterOutputTrigger = TIM_TRGO_UPDATE;
    master.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
    if (HAL_TIMEx_MasterConfigSynchronization(&g_htim2, &master) != HAL_OK) {
        return PROBE_ERR_TIM_INIT;
    }
    return PROBE_OK;
}

static probe_status_t Probe_TIM2_Start(uint8_t freeze_while_halted)
{
    g_tim2_update_count = 0U;
    if (freeze_while_halted != 0U) {
        __HAL_DBGMCU_FREEZE_TIM2();
    } else {
        __HAL_DBGMCU_UNFREEZE_TIM2();
    }

    if (HAL_TIM_Base_Start_IT(&g_htim2) != HAL_OK) {
        return PROBE_ERR_TIM_START;
    }
    return PROBE_OK;
}

static probe_status_t Probe_TIM2_Stop(void)
{
    if (HAL_TIM_Base_Stop_IT(&g_htim2) != HAL_OK) {
        return PROBE_ERR_TIM_STOP;
    }
    return PROBE_OK;
}

void TIM2_IRQHandler(void)
{
    HAL_TIM_IRQHandler(&g_htim2);
}

void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
    if (htim->Instance == TIM2) {
        g_tim2_update_count++;
    }
}

static void Probe_TIM2_Sample(probe_tim2_snapshot_t *out)
{
    uint32_t primask;

    if (out == NULL) {
        return;
    }

    primask = __get_PRIMASK();
    __disable_irq();
    __DMB();

    out->sequence = ++g_snapshot_sequence;
    out->tick_ms = HAL_GetTick();
    out->rcc_apb1enr = RCC->APB1ENR;
    out->dbgmcu_apb1_fz = DBGMCU->APB1FZ;
    out->tim_cr1 = TIM2->CR1;
    out->tim_dier = TIM2->DIER;
    out->tim_sr = TIM2->SR;
    out->tim_psc = TIM2->PSC;
    out->tim_arr = TIM2->ARR;
    out->tim_cnt = TIM2->CNT;
    out->update_callback_count = g_tim2_update_count;

    __DMB();
    if (primask == 0U) {
        __enable_irq();
    }
}
```

字段与所有权说明：

| 对象/字段 | 含义和生命周期 |
| --- | --- |
| `g_htim2` | BSP 静态持有的 HAL 句柄；从初始化到停止始终有效；不得由应用复制后分别控制同一 TIM2 |
| `Prescaler/Period` | 分别写入 PSC/ARR 的 HAL 配置值；本例得到 10 kHz 计数 tick 和 1 kHz update |
| `CounterMode` | 向上计数；决定 CR1.DIR 意图 |
| `ClockDivision` | 定时器内部滤波/死区相关分频字段，不是 APB 时钟分频；本例不把它用于 update 公式 |
| `AutoReloadPreload` | ARR 立即或经 update 生效的策略；本例关闭，避免把预装载作为新主题 |
| `MasterOutputTrigger` | 选择 update 事件作为 TRGO；仅为可选 ADC 链提供源，不证明接收端已连接 |
| `g_tim2_update_count` | IRQ 回调写、观察函数读；只是软件看到的回调次数，不等于无丢失的真实 update 总数 |
| `Probe_TIM2_Sample` | 固件内有序只读快照；短临界区防止回调计数夹在字段读取中间，但不能让全部硬件字段原子冻结 |

`__DMB()` 约束处理器显式内存访问的顺序，不会把多个外设寄存器变成同一瞬间的原子快照。快照内仍应记录读取顺序，分析时允许前后字段跨过一次硬件事件。

最小调用顺序：

```c
int main(void)
{
    probe_tim2_snapshot_t before;
    probe_tim2_snapshot_t after;

    HAL_Init();
    if (SystemClock_Config_Reference() != PROBE_OK) {
        Error_Handler();
    }
    if (Probe_TIM2_Init() != PROBE_OK) {
        Error_Handler();
    }

    Probe_TIM2_Sample(&before);          /* 启动前静态配置证据 */
    if (Probe_TIM2_Start(1U) != PROBE_OK) {
        Error_Handler();
    }

    /* 实际实验应由明确定义的时机触发，不在忙等待中无限采样。 */
    HAL_Delay(10U);
    Probe_TIM2_Sample(&after);           /* 运行状态候选证据 */

    for (;;) {
        /* 将 before/after 交给非 ISR 诊断路径；不要在回调中阻塞打印。 */
    }
}
```

`HAL_Delay(10U)` 只用于规划最小观察时机。它依赖 SysTick 和中断可运行，并不能充当精确 10 ms 测量证据。若在断点处暂停，延时与 TIM2 冻结策略也会相互影响。

#### 可选 ADC-DMA 链的 IRQ、回调和错误快照

若复用已完成课程中的 F407 `TIM2 TRGO -> ADC1 -> DMA2 Stream0/Channel0` 初始化，启动顺序必须是：DMA/NVIC -> ADC/DMA 武装 -> 最后启动 TIM2。以下代码只展示本课新增的观察钩子；`hadc1`、`hdma_adc1` 由既有生成工程/BSP 定义并持有，本观察模块通过 `extern` 借用其地址，不得重新初始化或改变所有权；静态缓冲区仍由原 BSP 唯一持有。[S1][S3]

```c
typedef struct {
    uint32_t half_count;
    uint32_t full_count;
    uint32_t error_count;
    uint32_t adc_error;
    uint32_t dma_error;
    uint32_t dma_lisr;
    uint32_t dma_s0cr;
    uint32_t dma_s0ndtr;
    uint32_t dma_s0par;
    uint32_t dma_s0m0ar;
} probe_adc_dma_snapshot_t;

#define PROBE_DMA_ERROR_UNAVAILABLE UINT32_MAX

extern ADC_HandleTypeDef hadc1;
extern DMA_HandleTypeDef hdma_adc1;

static volatile uint32_t g_adc_half_count;
static volatile uint32_t g_adc_full_count;
static volatile uint32_t g_adc_error_count;
static volatile uint32_t g_adc_error_code;
static volatile uint32_t g_dma_error_code;

void DMA2_Stream0_IRQHandler(void)
{
    HAL_DMA_IRQHandler(&hdma_adc1);
}

void ADC_IRQHandler(void)
{
    HAL_ADC_IRQHandler(&hadc1);
}

void HAL_ADC_ConvHalfCpltCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1) {
        g_adc_half_count++;
    }
}

void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1) {
        g_adc_full_count++;
    }
}

void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *hadc)
{
    if (hadc->Instance == ADC1) {
        g_adc_error_code = HAL_ADC_GetError(hadc);
        g_dma_error_code = (hadc->DMA_Handle != NULL)
                         ? HAL_DMA_GetError(hadc->DMA_Handle)
                         : PROBE_DMA_ERROR_UNAVAILABLE;
        g_adc_error_count++;
    }
}

static void Probe_ADC_DMA_Sample(probe_adc_dma_snapshot_t *out)
{
    uint32_t primask;

    if (out == NULL) {
        return;
    }
    primask = __get_PRIMASK();
    __disable_irq();
    __DMB();

    out->half_count = g_adc_half_count;
    out->full_count = g_adc_full_count;
    out->error_count = g_adc_error_count;
    out->adc_error = g_adc_error_code;
    out->dma_error = g_dma_error_code;
    out->dma_lisr = DMA2->LISR;
    out->dma_s0cr = DMA2_Stream0->CR;
    out->dma_s0ndtr = DMA2_Stream0->NDTR;
    out->dma_s0par = DMA2_Stream0->PAR;
    out->dma_s0m0ar = DMA2_Stream0->M0AR;

    __DMB();
    if (primask == 0U) {
        __enable_irq();
    }
}
```

回调只累加计数并锁存错误，不打印、不复位共享 RCC/DMA，也不在 ISR 中重启链路。`PROBE_DMA_ERROR_UNAVAILABLE` 是课程自定义的“没有可借用 DMA 句柄”哨兵，不是 HAL 错误码；UM1725 中 `HAL_DMA_ERROR_NO_XFER` 的含义是请求 abort 时没有正在进行的传输，不能挪作此用途。[S3] 错误处理流程是：应用看到 `error_count` 增加 -> 保存快照 -> 停 TIM2 源 -> `HAL_ADC_Stop_DMA` -> 确认 stream 停止 -> 分析 ADC/DMA error code 和标志 -> 显式恢复。读取 `LISR` 不等于清除标志；清除动作属于拥有 DMA 生命周期的恢复路径，而不是观察函数。[S1][S3]

#### HAL 到 LL/关键寄存器交叉表

| 软件意图 | HAL 入口 | LL 入口示例 | F407 关键寄存器/字段 | 观察结论上限 |
| --- | --- | --- | --- | --- |
| 开 TIM2 门控 | MSP 中 `__HAL_RCC_TIM2_CLK_ENABLE` | `LL_APB1_GRP1_EnableClock` | `RCC_APB1ENR.TIM2EN` | 门控已开，不证明计数 |
| 复位 TIM2 | FORCE/RELEASE RESET 宏 | APB1 reset LL 操作 | `RCC_APB1RSTR.TIM2RST` | 复位请求状态 |
| 配置基准计数 | `HAL_TIM_Base_Init` | `LL_TIM_SetPrescaler/SetAutoReload` | `PSC`、`ARR`、`CR1.DIR/ARPE`、`EGR.UG` | 静态配置与装载事件 |
| 选择 update TRGO | `HAL_TIMEx_MasterConfigSynchronization` | `LL_TIM_SetTriggerOutput` | `CR2.MMS` | 源选择已配置，不证明 ADC 接收 |
| 启动中断计数 | `HAL_TIM_Base_Start_IT` | 开 UIE、使能 counter | `DIER.UIE`、`CR1.CEN` | 中断和计数已使能，不证明周期准确 |
| 处理 update IRQ | `HAL_TIM_IRQHandler` -> callback | 检查/清 update flag | `SR.UIF`、`DIER.UIE` | 本次事件进入软件路径 |
| 冻结 TIM2 | freeze/unfreeze 宏 | 对应 DBGMCU LL/直接配置 | `DBGMCU_APB1_FZ.DBG_TIM2_STOP` | 内核暂停时 TIM2 的冻结策略 |
| 武装 ADC DMA | `HAL_ADC_Start_DMA` | 配 ADC DMA、地址、长度并开 stream | ADC DMA 控制；DMA `CR/PAR/M0AR/NDTR` | 请求与搬运配置，不证明数据有效 |
| DMA 事件 | `HAL_DMA_IRQHandler` -> ADC callbacks | 读标志、按规则清除 | `LISR` 与 `LIFCR`，`NDTR` | 本次 HT/TC/error 进入软件路径 |

同一外设同一生命周期只应有一个配置所有者。可以用 LL 宏或寄存器读做解释和只读观察，但不能在 HAL 正在管理句柄时由另一路径随意改配置，否则 HAL 状态、回调和硬件会失配。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

下面是一个可单文件编译的 C11 模型。它使用固定宽度整数、静态对象和固定数组，不使用动态内存。模型故意加入一个“读取即清除”的状态，验证观察者不能无条件重复读取；这只是教学模型，不声称 F407 的任意同名寄存器具有相同副作用。

```c
#include <assert.h>
#include <stdint.h>
#include <string.h>

#define OBS_HAS_SOURCE       (UINT32_C(1) << 0)
#define OBS_HAS_MOMENT       (UINT32_C(1) << 1)
#define OBS_HAS_SEMANTICS    (UINT32_C(1) << 2)
#define OBS_HAS_EXPECTATION  (UINT32_C(1) << 3)
#define OBS_HAS_CROSS_CHECK  (UINT32_C(1) << 4)
#define OBS_REQUIRED_MASK    (OBS_HAS_SOURCE | OBS_HAS_MOMENT | \
                              OBS_HAS_SEMANTICS | OBS_HAS_EXPECTATION | \
                              OBS_HAS_CROSS_CHECK)

typedef enum {
    FAKE_OK = 0,
    FAKE_ERR_CLOCK_OFF = 1,
    FAKE_ERR_NOT_CONFIGURED = 2,
    FAKE_ERR_BAD_SPEC = 3,
    FAKE_ERR_SOURCE_STOPPED = 4,
    FAKE_ERR_DMA_NOT_CONFIGURED = 5
} fake_status_t;

typedef enum {
    EVIDENCE_STATIC_CONFIG = 0,
    EVIDENCE_RUNTIME_STATE = 1,
    EVIDENCE_EXTERNAL_EFFECT = 2
} evidence_class_t;

typedef struct {
    uint32_t present_fields;
    evidence_class_t claim;
} observation_spec_t;

typedef struct {
    uint8_t clock_enabled;
    uint8_t configured;
    uint8_t running;
    uint8_t paused;
    uint8_t dma_configured;
    uint8_t dma_running;
    uint32_t tick;
    uint32_t psc;
    uint32_t arr;
    uint32_t cnt;
    uint32_t update_flag;
    uint32_t read_clear_event;
} fake_peripheral_t;

typedef struct {
    uint32_t sequence;
    uint32_t tick;
    uint8_t clock_enabled;
    uint8_t configured;
    uint8_t running;
    uint8_t paused;
    uint8_t dma_configured;
    uint8_t dma_running;
    uint32_t psc;
    uint32_t arr;
    uint32_t cnt;
    uint32_t update_flag;
    uint32_t consumed_event;
} fake_snapshot_t;

typedef struct {
    uint32_t next_sequence;
} fake_observer_t;

static void fake_init(fake_peripheral_t *peripheral,
                      fake_observer_t *observer)
{
    memset(peripheral, 0, sizeof(*peripheral));
    memset(observer, 0, sizeof(*observer));
}

static fake_status_t fake_configure(fake_peripheral_t *peripheral,
                                    uint32_t psc,
                                    uint32_t arr)
{
    if (peripheral->clock_enabled == 0U) {
        return FAKE_ERR_CLOCK_OFF;
    }
    peripheral->psc = psc;
    peripheral->arr = arr;
    peripheral->cnt = 0U;
    peripheral->configured = 1U;
    return FAKE_OK;
}

static fake_status_t fake_start(fake_peripheral_t *peripheral)
{
    if (peripheral->clock_enabled == 0U) {
        return FAKE_ERR_CLOCK_OFF;
    }
    if (peripheral->configured == 0U) {
        return FAKE_ERR_NOT_CONFIGURED;
    }
    peripheral->running = 1U;
    return FAKE_OK;
}

static fake_status_t fake_dma_configure(fake_peripheral_t *peripheral)
{
    if (peripheral->running == 0U) {
        return FAKE_ERR_SOURCE_STOPPED;
    }
    peripheral->dma_configured = 1U;
    return FAKE_OK;
}

static fake_status_t fake_dma_start(fake_peripheral_t *peripheral)
{
    if (peripheral->running == 0U) {
        return FAKE_ERR_SOURCE_STOPPED;
    }
    if (peripheral->dma_configured == 0U) {
        return FAKE_ERR_DMA_NOT_CONFIGURED;
    }
    peripheral->dma_running = 1U;
    return FAKE_OK;
}

static void fake_advance(fake_peripheral_t *peripheral, uint32_t ticks)
{
    uint32_t index;

    for (index = 0U; index < ticks; ++index) {
        peripheral->tick++;
        if ((peripheral->clock_enabled != 0U) &&
            (peripheral->running != 0U) &&
            (peripheral->paused == 0U)) {
            if (peripheral->cnt >= peripheral->arr) {
                peripheral->cnt = 0U;
                peripheral->update_flag = 1U;
                peripheral->read_clear_event = 1U;
            } else {
                peripheral->cnt++;
            }
        }
    }
}

static fake_snapshot_t fake_sample(fake_peripheral_t *peripheral,
                                   fake_observer_t *observer)
{
    fake_snapshot_t sample;

    observer->next_sequence++;
    sample.sequence = observer->next_sequence;
    sample.tick = peripheral->tick;
    sample.clock_enabled = peripheral->clock_enabled;
    sample.configured = peripheral->configured;
    sample.running = peripheral->running;
    sample.paused = peripheral->paused;
    sample.dma_configured = peripheral->dma_configured;
    sample.dma_running = peripheral->dma_running;
    sample.psc = peripheral->psc;
    sample.arr = peripheral->arr;
    sample.cnt = peripheral->cnt;
    sample.update_flag = peripheral->update_flag; /* 普通只读模型字段 */
    sample.consumed_event = peripheral->read_clear_event;
    peripheral->read_clear_event = 0U;             /* 明确建模读副作用 */
    return sample;
}

static fake_status_t observation_validate(const observation_spec_t *spec)
{
    if ((spec->present_fields & OBS_REQUIRED_MASK) != OBS_REQUIRED_MASK) {
        return FAKE_ERR_BAD_SPEC;
    }
    return FAKE_OK;
}

static uint8_t claim_is_supported(const observation_spec_t *spec,
                                  const fake_snapshot_t *first,
                                  const fake_snapshot_t *second)
{
    if (observation_validate(spec) != FAKE_OK) {
        return 0U;
    }
    if (spec->claim == EVIDENCE_STATIC_CONFIG) {
        return (uint8_t)((first->clock_enabled != 0U) &&
                         (first->configured != 0U));
    }
    if (spec->claim == EVIDENCE_RUNTIME_STATE) {
        return (uint8_t)((second->sequence > first->sequence) &&
                         (second->tick > first->tick) &&
                         ((second->cnt != first->cnt) ||
                          (second->update_flag != first->update_flag)));
    }
    /* Host Fake 永远不能证明外部电平或真实硬件效果。 */
    return 0U;
}

static void test_clock_gate_and_static_boundary(void)
{
    fake_peripheral_t peripheral;
    fake_observer_t observer;
    fake_snapshot_t first;
    fake_snapshot_t second;
    observation_spec_t static_spec = {
        OBS_REQUIRED_MASK, EVIDENCE_STATIC_CONFIG
    };
    observation_spec_t runtime_spec = {
        OBS_REQUIRED_MASK, EVIDENCE_RUNTIME_STATE
    };

    fake_init(&peripheral, &observer);
    assert(fake_configure(&peripheral, 3U, 9U) == FAKE_ERR_CLOCK_OFF);
    peripheral.clock_enabled = 1U;
    assert(fake_configure(&peripheral, 3U, 9U) == FAKE_OK);
    first = fake_sample(&peripheral, &observer);
    second = first;
    assert(claim_is_supported(&static_spec, &first, &second) == 1U);
    assert(claim_is_supported(&runtime_spec, &first, &second) == 0U);
}

static void test_ordered_runtime_samples(void)
{
    fake_peripheral_t peripheral;
    fake_observer_t observer;
    fake_snapshot_t first;
    fake_snapshot_t second;
    observation_spec_t spec = {
        OBS_REQUIRED_MASK, EVIDENCE_RUNTIME_STATE
    };

    fake_init(&peripheral, &observer);
    peripheral.clock_enabled = 1U;
    assert(fake_configure(&peripheral, 0U, 9U) == FAKE_OK);
    assert(fake_start(&peripheral) == FAKE_OK);
    first = fake_sample(&peripheral, &observer);
    fake_advance(&peripheral, 3U);
    second = fake_sample(&peripheral, &observer);
    assert(second.cnt == 3U);
    assert(claim_is_supported(&spec, &first, &second) == 1U);
}

static void test_read_side_effect(void)
{
    fake_peripheral_t peripheral;
    fake_observer_t observer;
    fake_snapshot_t first;
    fake_snapshot_t second;

    fake_init(&peripheral, &observer);
    peripheral.clock_enabled = 1U;
    assert(fake_configure(&peripheral, 0U, 1U) == FAKE_OK);
    assert(fake_start(&peripheral) == FAKE_OK);
    fake_advance(&peripheral, 2U);
    first = fake_sample(&peripheral, &observer);
    second = fake_sample(&peripheral, &observer);
    assert(first.consumed_event == 1U);
    assert(second.consumed_event == 0U);
    assert(first.update_flag == 1U);
    assert(second.update_flag == 1U);
}

static void test_pause_and_resume_policy(void)
{
    fake_peripheral_t peripheral;
    fake_observer_t observer;
    uint32_t paused_cnt;

    fake_init(&peripheral, &observer);
    peripheral.clock_enabled = 1U;
    assert(fake_configure(&peripheral, 0U, 9U) == FAKE_OK);
    assert(fake_start(&peripheral) == FAKE_OK);
    fake_advance(&peripheral, 2U);
    peripheral.paused = 1U;
    paused_cnt = peripheral.cnt;
    fake_advance(&peripheral, 5U);
    assert(peripheral.cnt == paused_cnt);
    peripheral.paused = 0U;
    fake_advance(&peripheral, 1U);
    assert(peripheral.cnt != paused_cnt);
}

static void test_segmented_failure_and_bad_spec(void)
{
    fake_peripheral_t peripheral;
    fake_observer_t observer;
    fake_snapshot_t first;
    fake_snapshot_t second;
    observation_spec_t incomplete = {
        OBS_HAS_SOURCE | OBS_HAS_MOMENT, EVIDENCE_RUNTIME_STATE
    };
    observation_spec_t external = {
        OBS_REQUIRED_MASK, EVIDENCE_EXTERNAL_EFFECT
    };

    fake_init(&peripheral, &observer);
    assert(fake_start(&peripheral) == FAKE_ERR_CLOCK_OFF);
    assert(fake_dma_configure(&peripheral) == FAKE_ERR_SOURCE_STOPPED);
    assert(fake_dma_start(&peripheral) == FAKE_ERR_SOURCE_STOPPED);
    peripheral.clock_enabled = 1U;
    assert(fake_start(&peripheral) == FAKE_ERR_NOT_CONFIGURED);
    assert(fake_configure(&peripheral, 0U, 9U) == FAKE_OK);
    assert(fake_dma_start(&peripheral) == FAKE_ERR_SOURCE_STOPPED);
    assert(fake_start(&peripheral) == FAKE_OK);
    assert(fake_dma_start(&peripheral) == FAKE_ERR_DMA_NOT_CONFIGURED);
    assert(fake_dma_configure(&peripheral) == FAKE_OK);
    assert(fake_dma_start(&peripheral) == FAKE_OK);
    first = fake_sample(&peripheral, &observer);
    fake_advance(&peripheral, 5U);
    second = fake_sample(&peripheral, &observer);
    assert(second.dma_configured == 1U);
    assert(second.dma_running == 1U);
    assert(observation_validate(&incomplete) == FAKE_ERR_BAD_SPEC);
    assert(claim_is_supported(&external, &first, &second) == 0U);
}

int main(void)
{
    test_clock_gate_and_static_boundary();
    test_ordered_runtime_samples();
    test_read_side_effect();
    test_pause_and_resume_policy();
    test_segmented_failure_and_bad_spec();
    return 0;
}
```

测试覆盖：时钟未开、静态配置不能证明运行、相邻快照可变、读取副作用、暂停/恢复策略、TIM 源未运行时拒绝 DMA 配置/启动、DMA 未配置时拒绝启动、不完整规格以及 Host Fake 不能证明外部效果。DMA 阶段只建模观察链的前置条件，不搬运数据；`fake_advance` 的暂停规则是模型策略，不是 F407 冻结矩阵的替代品。

### 8.2 STM32 参考实现轨道

目标实验必须补齐这些输入：

| 输入 | 当前状态 | 实施时要求 |
| --- | --- | --- |
| 完整 MCU/封装 | 待用户提供 | 对照 DS8626，确认器件和调试端口 |
| 开发板/原理图 | 待用户提供 | 确认供电、NRST、SWD/JTAG、晶振和测量点 |
| ST-LINK/等效探针 | 待用户提供 | 记录型号、固件、速度和调试服务器版本 |
| CubeMX/CubeMX2、CubeF4、工具链 | 待用户提供 | 记录版本并保存 `.ioc` 和构建日志 |
| 外部测量 | 待用户提供 | 频率或波形结论使用合适探针交叉验证 |

参考步骤：

1. 按第 7.3 节生成目标工程并审计差异；
2. 构建失败时先修正 API/包版本，不把课程代码视为已编译；
3. 连接前确认目标电压、调试接口和完整料号；
4. 启动前保存 RCC/TIM2 静态快照；
5. 分别用 freeze 和 unfreeze 策略运行有限采样；
6. 记录两个有序 `CNT` 样本、`UIF`、回调计数及暂停条件；
7. 可选链再记录 ADC/DMA 配置、`NDTR`、标志和回调计数；
8. 最后才用外部测量回答实际频率或信号问题。

本课没有执行这些目标步骤，不能声称目标构建、连接、读回、烧录或测量成功。

## 9. 最小代码示例

最小使用原则不是“不断刷新整个寄存器树”，而是只读解决当前假设所需的字段：

```c
probe_tim2_snapshot_t before;
probe_tim2_snapshot_t after;

Probe_TIM2_Sample(&before);       /* CEN 应为 0；核对门控、PSC、ARR */
if (Probe_TIM2_Start(1U) != PROBE_OK) {
    Error_Handler();
}
HAL_Delay(10U);
Probe_TIM2_Sample(&after);        /* CEN、CNT/UIF、回调计数形成候选运行证据 */
```

判定时逐句写：

```text
门控已开：after.rcc_apb1enr 的 TIM2EN 位为 1。
静态配置一致：PSC=8399、ARR=9。
软件请求运行：CR1.CEN 为 1。
发生变化：after 的 CNT/UIF/回调计数至少一项相对 before 改变。
仍未证明：实际 update 频率为 1 kHz；需要独立计时或外部测量。
```

## 10. 常见错误

1. **先看数值，再编故事**：没有预期和失败分支，任何值都能被事后解释。
2. **把一次 CNT 当频率**：频率是单位时间内的变化，需要时间基准和至少两个有序样本。
3. **把门控打开当作外设运行**：还缺复位释放、配置、使能和事件链。
4. **把 CEN=1 当作 update 已发生**：CEN 只表达计数器使能状态；还需 CNT/UIF/回调等运行证据。
5. **无限自动刷新**：可能读走清除型事件、改变 FIFO 或增加总线扰动。
6. **忽略暂停策略**：冻结 TIM2 后得到的 CNT 不代表自由运行；不冻结时单步期间它又可能跨过多个周期。
7. **把 SVD 当参考手册**：SVD 提供展示元数据，行为语义仍查 RM/DS/CMSIS 头文件。
8. **清标志后才保存现场**：恢复动作覆盖了根因证据；应先做无副作用快照。
9. **在回调中打印整个寄存器树**：阻塞输出改变中断时序，也可能导致新错误。
10. **多个读取者争同一清除型状态**：IDE、脚本和 ISR 中只有第一个读取者可能看到事件。
11. **认为短临界区产生原子硬件快照**：它只阻止 CPU 中断插入，不会冻结异步外设。
12. **用 Host Fake 数字冒充 F407 读回**：Fake 只证明契约和测试逻辑。
13. **复制 F407 地址到 F7/H5/H7**：迁移时必须选定器件并重新核对。
14. **错误回调中复位整个 DMA/RCC**：共享资源应由唯一拥有者在延后路径清理。
15. **把调试窗口里的十六进制截图当完整证据**：缺少工具版本、时机和交叉证据时不可复查。

## 11. 调试观察点

下面的表可以直接作为目标实验记录骨架：

| 顺序 | 对象 | 预期 | 时机 | 语义/风险 | 失败后下一步 | 交叉证据 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `RCC_CFGR.SWS/PPRE1` | PLL 为系统源、APB1 `/4` | 时钟配置返回后 | 静态配置 | 回到时钟初始化返回值与 ready 状态 | `HAL_RCC_GetClockConfig`、时钟推导表 |
| 2 | `RCC_APB1ENR.TIM2EN` | 1 | TIM2 init 后 | 静态门控 | 检查 MSP 是否执行、句柄实例是否 TIM2 | `HAL_TIM_Base_Init` 返回值 |
| 3 | `TIM2_PSC/ARR` | 8399/9 | 启动前 | 静态配置；注意装载时机 | 检查生成代码、EGR/ARPE 策略 | Cube 配置与公式 |
| 4 | `DBGMCU_APB1_FZ.DBG_TIM2_STOP` | 与实验策略一致 | 每次暂停前 | 改变暂停行为 | 显式调用 freeze/unfreeze | 暂停前后的有序 CNT 样本 |
| 5 | `TIM2_CR1.CEN` | 启动前 0、启动后 1 | 两个已定义时机 | 运行控制位 | 检查 start 返回值和错误路径 | CNT/UIF/回调计数 |
| 6 | `TIM2_CNT` | 有序样本按策略变化或冻结 | 有限两次采样 | 易变，不代表频率 | 检查门控、CEN、冻结位 | tick/trace/外部测量 |
| 7 | `TIM2_SR.UIF` | update 后可置位 | IRQ 前或禁用 UIE 的受控实验 | 软件写 0 清除；IRQ 可改变现场 | 核对读取者与清除者 | 回调计数 |
| 8 | DMA `CR/PAR/M0AR/NDTR` | 与已核对链一致 | 接收端武装后、源启动前 | NDTR 运行中易变 | 先查 stream 使能和请求映射 | HT/TC/error 计数、缓冲区 |
| 9 | DMA `LISR` | 事件对应标志 | IRQ 入口前的受控条件 | 由 LIFCR 清除，不在观察函数写 | 检查 IRQ handler 和清除顺序 | HAL/DMA error code |
| 10 | 外部效果 | 与设计周期/内容一致 | 稳态窗口 | 不由寄存器视图提供 | 选择合适测量工具 | 内部配置与事件证据 |

使用 IDE 窗口时关闭不需要的外设树自动展开；对副作用未知的字段改用手册核对后的有限脚本或固件快照。具体 IDE 的刷新顺序和是否缓存显示值取决于工具版本，本课未指定工具，必须在实验记录中补充。

## 12. 实战实验

### 实验 A：Host Fake 观察契约

1. 将第 8.1 节保存为临时 `register_view_fake.c`；
2. 用本机 C11 编译器开启严格警告构建并运行；
3. 删除 `OBS_HAS_SEMANTICS`，确认规格被拒绝；
4. 把外部效果声明改为运行状态，解释为何不能借此让 Fake 证明真实引脚；
5. 保存命令、编译器版本和退出码，作为你自己的主机实验记录。

本次 Reviewer 已从正文机械提取该代码块，使用 GCC 16.2.0 和 `-std=c11 -Wall -Wextra -Werror -pedantic` 编译并运行；编译与执行退出码均为 0，记录见本次运行目录 `review.md`。这只证明当前 Host Fake 代码及断言，不证明任何 STM32 地址、时钟、调试访问或外部效果。

### 实验 B：读副作用与读取者所有权

1. 在 `fake_sample` 前后读取 `read_clear_event`；
2. 增加第二个模拟观察者，依次采样；
3. 证明第一个观察者消费后，第二个看不到同一事件；
4. 写出真实项目规则：清除型状态只能由哪个层读取，如何把副本发布给其他消费者。

### 实验 C：F407 CubeMX 静态审计

1. 选择实际完整料号和工具版本；
2. 按第 7.3 节配置 HSI/PLL/TIM2；
3. 不连接硬件，先审计 `.ioc` 和生成代码；
4. 对每个 HAL 字段找到 LL/寄存器入口；
5. 把板级未知项留空并列出，不虚构引脚或晶振。

### 实验 D：目标构建与启动前快照

1. 先从原理图和电源资料确认 `VDD`；只有 `VDD=2.7..3.6 V` 才使用本例 168 MHz/5 wait states，否则先按 DS8626 表 15 降频或修改 latency；
2. 在实际工程编译参考代码，保存完整构建日志；
3. 修正与实际 CubeF4 版本不一致的 API，并记录差异；
4. 连接目标后只执行到 TIM2 启动前；
5. 保存 RCC、DBGMCU、TIM2 静态快照；
6. 若任何配置与预期不符，停止，不进入运行实验。

### 实验 E：冻结与不冻结的对照

1. `freeze_while_halted=1`，运行后暂停两次，记录 CNT、UIF、回调计数和每次时机；
2. `freeze_while_halted=0`，重复同样步骤；
3. 解释暂停期间哪些证据仍有意义；
4. 不把 TIM2 结论推广到 ADC、DMA 或其他系列。

### 实验 F：ADC-DMA 分段定位

1. 沿用已核对链，源启动前确认 DMA stream、地址和 NDTR；
2. 最后启动 TIM2；
3. 按源、ADC、DMA、IRQ/回调顺序找首次不满足点；
4. 故障时先快照，后停源，再由拥有者清理；
5. 用缓冲区内容或外部输入作为交叉证据，不用 NDTR 单独证明数据正确。

### 实验 G：迁移审计

为一个明确的 F7、H5 或 H7 完整料号建立表格，只填写从对应 RM/DS/Cube 包核对到的内容：设备描述、调试授权、冻结位、时钟域、DMA 架构、缓存/内存可见性和工具设置。未找到第一方出处的单元格写“待核对”。

## 13. 自检题

1. `TIM2_CNT=357` 最多直接证明什么？为什么不能证明 1 kHz？
2. 为什么 `TIM2EN=1` 能证伪一部分问题，却不能证明 TIM2 正在计数？
3. 观察规格缺少取样时机会造成什么歧义？
4. SVD 与参考手册分别承担什么角色？
5. 为什么禁用中断只能改善软件字段的一致性，不能获得原子硬件快照？
6. IDE 自动刷新读了清除型寄存器，IRQ handler 会受到什么影响？
7. `NDTR` 在两个快照间变小，能够支持什么结论？仍不能支持什么？
8. 暂停时 TIM2 冻结和不冻结各会怎样影响 CNT 解释？
9. Host Fake 的断言全部满足后，为什么 `hardware_verified` 仍然必须为 `false`？
10. 从 F407 迁移到 H7，观察契约中哪些部分能保留，哪些必须重查？

建议答案要点：每一题都应包含“对象、取样时机、字段语义、允许结论、不能推出的结论、需要的交叉证据”。

## 14. 面试题

### 14.1 如何证明一个定时器真的以 1 kHz 运行？

先核对时钟源、PLL、APB 分频、TIM2 门控、PSC/ARR 和 CEN；再取得带可靠时间基准的多个事件或计数样本；最后用输出比较翻转、TRGO 下游事件、trace 或外部仪器交叉测量。单次寄存器截图只能支持局部配置和当次状态。

### 14.2 为什么调试器会改变 bug 的表现？

暂停改变 CPU 与外设的相对进度，冻结位可能只停止部分模块，自动刷新可能读取有副作用的状态，单步与打印会改变中断延迟。应记录观察条件并优先使用扰动更小的证据路径。

### 14.3 如何处理读取即清除的寄存器？

先查清完整读取/清除协议，指定唯一读取者，由它一次读取并把软件副本分发给其他层；调试窗口关闭该字段的自动刷新。故障现场先按规定顺序保存，再清除和恢复。

### 14.4 HAL 返回 `HAL_OK` 为什么不等于外设工作正常？

它只说明该函数按当前软件状态完成了配置或启动请求。时钟、硬件状态、事件传播、数据内容和外部效果仍需寄存器读回、回调/错误路径和独立测量证明。

### 14.5 如何让一次寄存器观察可复现？

记录目标器件、文档/固件/工具版本、SVD、固件提交、观察规格、执行顺序、暂停/冻结条件、原始值、读取者、错误分支和交叉证据；脚本化有限读取优于手工反复展开窗口。

## 15. 延伸思考

1. 如果一次快照的字段按固定顺序读取，如何表示“事件可能发生在字段 4 和字段 5 之间”？
2. 如何给观察规格加入允许扰动预算，例如最大暂停时间或最大读取次数？
3. 当 trace 缓冲区会溢出时，“没有看到事件”为什么仍不能证明事件没发生？
4. 如果 DMA 与 CPU 看到的缓冲区内容不同，寄存器配置正确能否证明数据一致？这将如何连接到缓存一致性课程？
5. 如何把本课观察表转成自动化调试脚本，同时避免脚本读取清除型字段？

## 16. 本节总结

寄存器视图不是持续真相，而是带取样条件的状态样本。可靠调试遵守一条固定纪律：

```text
先写可证伪假设
  -> 定义对象、时机、读取者和字段语义
  -> 从时钟/复位开始分段采样
  -> 限制结论在当前证据层内
  -> 用第二路径交叉验证时间、完整性和外部效果
  -> 先保存现场，再清理和恢复
```

Host Fake 验证这套纪律在时钟未开、易变值、读副作用、暂停和规格不完整时仍能给出确定结果；STM32F407xx 轨道则把它落实到 RCC、TIM2、可选 ADC-DMA、HAL/LL/寄存器和 IRQ/error 流。两条轨道互补，但不能互相冒充证据。

## 17. 下一步

下一课 `breakpoint-watchpoint` 将研究断点和观察点如何选择触发条件、如何改变执行时序，以及何时应改用 DWT/CoreSight 等更低扰动的观察路径。本课的观察规格将作为其输入，不提前展开断点资源分配或 watchpoint 配置。

## 18. 参考资料

- [S1] STMicroelectronics，*STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 advanced Arm-based 32-bit MCUs - Reference manual*，RM0090 Rev 22，May 2026。重点：RCC、DMA、TIM2-TIM5 和 debug support；用于核对门控/复位、TIM2 计数与更新标志、DMA NDTR/标志和 TIM2 调试冻结语义。<https://www.st.com/resource/en/reference_manual/dm00031020.pdf>，访问日期：2026-10-17。
- [S2] STMicroelectronics，*STM32F405xx STM32F407xx datasheet*，DS8626 Rev 12，March 2026。用于核对器件适用范围、时钟/总线边界和调试接口；不用于虚构未指定板卡的引脚或外部时钟。<https://www.st.com/resource/en/datasheet/stm32f407vg.pdf>，访问日期：2026-10-17。
- [S3] STMicroelectronics，*Description of STM32F4 HAL and low-layer drivers*，UM1725 Rev 8，March 2023。重点：RCC、TIM、ADC 和 DMA 的 HAL/LL 初始化、启动、IRQ、callback、状态与错误 API。<https://www.st.com/resource/en/user_manual/dm00105879.pdf>，访问日期：2026-10-17。

来源的结构化元数据见同目录 `lesson.json`。以上资料只约束其明确覆盖的 F4 器件和 STM32F4 HAL/LL 接口；F7、H5、H7 必须在选定完整目标后加入各自第一方资料再下具体结论。
