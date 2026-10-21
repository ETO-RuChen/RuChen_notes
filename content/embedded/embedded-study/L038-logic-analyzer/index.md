+++
title = "逻辑分析仪：从数字边沿建立可信的时序证据"
date = "2026-10-20T22:47:27+08:00"
lastmod = "2026-10-20T22:47:27+08:00"
summary = "能够设计并审计一次 STM32F407xx 数字信号的逻辑分析仪采集：由定时器时钟与输出配置预测边沿，以采样率、触发和多通道时间基约束读数，并区分模拟电气问题、软件标记与真实硬件事件的证据边界。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 38
tags = ["逻辑分析仪", "调试与验证", "离散采样", "触发与时间基", "STM32F407VG", "Host Fake"]
source_ids = ["ST-RM0090", "ST-DS8626", "ST-UM1725", "ST-CUBEF4-VERSIONS", "ST-UM1718", "ST-AN4776", "ST-PM0253", "ST-PM0264"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L038"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# L038 逻辑分析仪：从数字边沿建立可信的时序证据

> 阶段：调试与验证（`debugging-verification`）；主题：`logic-analyzer`。建议 75 分钟。
>
> **证据边界：**本课已有主机模型的编译与断言记录；STM32 代码是“参考实现，待目标工程编译”。没有指定开发板、分析仪和探头，没有目标构建、烧录或采集记录，`hardware_verified=false`。下面的 1 ms、500 µs 和合成序列都是**计算预测或模型输入**，不是测量波形。课程生成不提高掌握度；元数据状态以 `lesson.json` 及 Reviewer 的独立审查结论为准。

## 1. 本节目标

能够设计并审计一次 STM32F407xx 数字信号的逻辑分析仪采集：由定时器时钟与输出配置预测边沿，以采样率、触发和多通道时间基约束读数，并区分模拟电气问题、软件标记与真实硬件事件的证据边界。

只推进下面两个新核心概念，与本次 `plan.json` 一致：

1. **离散采样的时序分辨率与漏检边界**。
2. **触发与共享时间基下的边沿因果归因**。

完成后应能提交一份“配置—预测—采集—误差—反例”的记录：说明为什么选这个采样间隔、触发通道和前后窗口，哪些结论由同次采集支持，哪些仍不能推出。不是要求背下一串仪器菜单，也不要求本课实现协议解析器、重写 DMA（direct memory access，直接存储器访问）驱动或学习 RTOS（实时操作系统）。

阅读路线：§2–6 先用可手算的主机反例理解问题；§7–9 落实器件、配置和完整代码；§10–15 用排错与实验检验判断；§17 指向后续验证课，而不是一次生成额外课程。

## 2. 它解决什么问题

程序写着“每毫秒翻转一次”，不等于输出脚真的每毫秒翻转。寄存器窗口只能告诉你暂停时读到了什么；**逻辑分析仪（digital logic analyzer，数字逻辑电平采集仪）**则把外部通道在一系列采样时刻被判为高或低的结果保存下来，用来观察自由运行中的先后与间隔。这里讨论的是均匀数字采样的理想模型；实际设备是否这样实现、支持哪些阈值和触发，必须另查其手册。

先看最小反例，不碰硬件：

```text
合成事件：103 µs 变高，105 µs 变低，实际高电平宽度为 2 µs。
每 10 µs 采一次，相位 A：100→0，110→0，120→0。完全没看见这个脉冲。
仍每 10 µs 采一次，相位 B： 94→0，104→1，114→0。看见了，却读成约 10 µs。
每  1 µs 采一次：103→1，104→1，105→0。模型读数为 2 µs，仍须报告量化边界。
```

这三行解决两个常见误判：

- “没抓到”不能直接写成“没发生”。它也可能落在样本间隙、触发之前或保留窗口之外。
- “界面显示 10 µs”不能直接写成“真实宽度精确为 10 µs”。显示往往对应样本索引，不是连续时间中真实边沿的位置。

再看因果问题：同一次采集里，定时器输出先变化，软件标记后变化，只证明这两个**外部可观察边沿**之间的关系。要把后者解释为某个 IRQ（interrupt request，中断请求）得到服务后的标记，还需核对固件路径；它不是 CPU（中央处理器）中断入口或某条 C 语句的精确时间戳。这个约束贯穿全课。

## 3. 必要前置知识

前置主题已经在 `completed` 中安排过，但这不等于已经掌握或上板成功。先用三个短复习自查：

1. `clock-tree`、`timer`：计数时钟除以 `PSC+1` 得到计数频率；向上计数从 0 到 `ARR` 共 `ARR+1` 个节拍。名义 16 MHz、PSC=15、ARR=999，会得到 1 MHz 计数和 1 ms 周期。若算不出来，先回看 L021、L027，再继续。
2. `gpio`、`hal-ll-register-crosswalk`：定时器内部生成输出参考信号，还要经过通道使能、GPIO（general-purpose input/output，通用输入/输出）复用和实际电路才能到探头。内部计数在动不等于引脚一定有信号。对应 L018、L028。
3. `interrupt-priority`、`breakpoint-watchpoint`：硬件事件、IRQ 受理和软件 GPIO 写入是不同位置；断点会改变运行现场，是否冻结定时器还取决于调试配置。连续采集不要靠周期性暂停程序来“测延迟”。对应 L020、L034；F407 的定时器调试冻结见 [S1] §18.3.16。

采样窗口和整数边界代码使用已授的数组、指针、固定宽度整数与 C11（C 语言 2011 标准）子集。不增加对象注入、架构分层或并发框架的新教学目标。

## 4. 核心原理

### 4.1 概念一：采样给出的是边沿所在区间，不是精确时刻

定义采样率 `Fs` 为每秒采样次数，采样间隔 `Ts=1/Fs`。本课理想采样时刻为：

```text
t[k] = t0 + k × Ts
```

若同一通道第 `i-1` 个样本低、第 `i` 个样本高，并假定期间只有一次相关上升沿，则该边沿在：

```text
e ∈ (t[i-1], t[i]]
```

若第二个相关边沿在索引 `j` 被观察到，两边沿间隔保守地落在：

```text
Δ ∈ [t[j-1] - t[i], t[j] - t[i-1]]
均匀采样时，若界面使用 Δread=(j-i)Ts：
Δ ∈ [Δread-Ts, Δread+Ts]
```

这是**本课理想模型的直接推导**，不是某台仪器的精度规格。严格的端点开闭可由假设进一步收紧；代码刻意保留闭区间作保守包络。两个边沿各有一个 `Ts` 宽的位置区间，差值包络的总宽是 `2Ts`，相对于索引读数的半宽是 `Ts`，不要把这两个量混为一谈。

适用前提很重要：如果样本间还有未观察到的额外跳变，就不能仅凭“相邻低高样本”证明只有一条边沿，也不能把两次相隔很远的低高转换认成相邻周期。提高采样率能缩小这个理想包络，却不自动修复错误接地、阈值或探头带宽问题。

**脉宽与漏检：**宽度 `W<Ts` 的高脉冲可以完全处于两个采样点之间。即使信号的重复周期很长，窄脉冲仍会漏掉。因此“采样率只要超过重复频率的两倍”不是本课数字窄脉冲的可靠检出保证。理想无噪声条件下，让最短高、低电平各容纳多个样本，是有余量的设计方式；实际最小可检脉宽、输入带宽和触发资格要求仍由仪器决定，不在本课虚填倍数规格。

**采集长度：**保存 `N` 个等间隔样本，首末样本时间差是 `(N-1)Ts`。仪器界面可能用 `N/Fs` 作为近似记录时长；压缩/流式保存还可能按字节或事件计深度，不能未经手册核对就把“存储容量”当成样本数。

主机算例：10 kS/s（每秒一万样本）的 `Ts=100 µs`，某对上升沿样本相距 10 格，周期读数 1000 µs，理想量化包络为 `[900,1100] µs`；高低边沿相距 5 格，宽度读数 500 µs，包络为 `[400,600] µs`。这只是可手算的粗采样示范，不是推荐用这个低采样率做所有实机判断。

### 4.2 概念二：触发选定参照和窗口，不替你证明因果

**触发（trigger）**回答“以哪个被识别的条件为观察参照，保留哪些数据”。**触发前窗口（pre-trigger window）**保存触发参照之前的一段样本，用于追查原因，而不只是看结果。

本课的主机模型先得到一段样本，再找通道 0 的首次“低→高”样本，按索引裁出窗口。实际分析仪可能由独立硬件触发器识别条件，也可能由软件查找；其触发时基、延迟、资格宽度和采样链关系必须查实际设备，不能由这个模型代言。

假设触发发生在被观察到的 100 µs 样本，先前另一路标记在 75 µs 变高、90 µs 变低：

- 只保留 5 µs 的触发前数据，窗口从 95 µs 开始，标记完全不在记录里。
- 保留 30 µs 的触发前数据，窗口从 70 µs 开始，才可能看到它。
- 触发成功不表示历史无限长；触发前数据不足时，本课代码明确返回错误，不补造历史。

**共享时间基（shared timebase）**是指比较的通道来自同次、可关联的采集时标。把两路时间都减去同一个触发参照，不改变它们的间隔；主机测试把所有时间平移 500 µs，间隔仍为 `[20,40] µs`。但必须核对实际仪器多通道是否共享可比较的采样时标及通道偏斜，不能默认任意两台设备已同步。

“先后”也不是充分的“原因”：

1. 代码路径要支持这个标记确由相关事件触发，而不是另一个写 GPIO 的位置。
2. 两条外部边沿之间若只差一个样本，考虑量化、阈值和偏斜后，可能无法判定稳定先后。
3. 改变 `CCR1` 只应主要改变 PWM（pulse-width modulation，脉宽调制）高电平宽度；更新边界周期仍应由 ARR/PSC 决定。对照配置变更可检验你是否把下降沿、更新或另一周期配错了。
4. 软件标记带来额外执行和总线访问。标记开启与关闭应作为两组条件记录，不能把“加了探针后的行为”无条件当成未插桩行为。

### 4.3 从量化包络到实机误差预算

理想 `±Ts` 不包含仪器时钟误差、电气门限、探头、通道偏斜等。对同次采集的边沿间隔，可先写保守预算：

```text
U预算 = Ts + U时基 + U通道偏斜 + U阈值交越 + U探头/连接
U时基按仪器规格计算；小时钟误差下，一阶估计约为 |Δread|×εLA
```

`εLA` 是实际分析仪时基相对误差的已知上界；其余各项也必须来自规格或校准。这里只给预算结构，不填虚构数值；线性相加是保守上界，不是统计置信区间。实际仪器若采用不同时间戳机制，应换成它的量化模型。

MCU 的 HSI（high-speed internal oscillator，内部高速振荡器）容差属于“理论输出预测”的误差，而不是外部采样仪的时基误差。软件报告 `HAL_RCC_GetPCLK1Freq()` 等于 16 MHz，只说明按配置与常量计算得到名义值，不是校准实测频率。HSI 的温度、电压和校准条件查 [S2] §6.3.9；没有工作条件，不给本板的准确 ppm（百万分之一相对误差）数值。

## 5. 关键术语与直观模型

| 术语 | 准确含义 | 本课用法与限制 |
|---|---|---|
| 边沿（edge） | 通道电平从低到高或从高到低的变化 | 采样只给其可能所在区间 |
| 阈值（threshold） | 输入被判高/低所依据的电压边界 | 来自仪器输入规格，不等于 STM32 输出电压 |
| 地参考（ground reference） | 输入电压比较所依据的参考电位 | 未确认两设备接地关系，不进行连接 |
| 脉宽、占空比（duty cycle） | 高/低电平持续时间；指定有效电平时间与周期之比 | 先确认极性、边沿配对和周期，再算比值 |
| 通道偏斜（channel skew） | 通道间输入/采样路径造成的相对时间偏差 | 共用采集不代表偏斜为零 |
| 毛刺（glitch） | 不希望出现的短暂电平跳变 | 是否检出仍受最短脉宽和采样限制 |
| PWM（pulse-width modulation，脉宽调制） | 通过有效电平持续时间控制占空比 | 本课仅作为已授的可预测数字信号源 |
| TIM、PSC、ARR、CCR | 定时器、预分频寄存器、自动重装载寄存器、捕获/比较寄存器 | 在本参考实现中共同决定输出节拍 |
| IRQ、ISR | 中断请求；interrupt service routine，中断服务程序 | 请求、受理、回调与 GPIO 边沿分开标注 |
| HAL、LL | hardware abstraction layer，硬件抽象层；low-layer，底层驱动 | 用 HAL 搭参考路径，用关键寄存器核对硬件动作 |
| DMA | direct memory access，直接存储器访问 | 仅在能力地图回顾数据链，本课不启用 DMA |
| Host Fake | 主机替身，用理想事件替代硬件输入 | 验证采样/判读逻辑，不模拟真实电气前端 |

不要用“采样率”“带宽”“最小触发脉宽”互相替代。前者决定这里的离散时间格，后两项必须单独核对实际输入链和触发器规格。本课没有指定分析仪，因此没有任何型号能力、默认阈值或输入耐压承诺。

## 6. 从输入到结果的完整流程

```text
器件时钟配置 → TIM2 计数/比较 → CH1 输出参考 → 通道使能
→ GPIO AF（alternate function，复用功能）→ 实际板上网络与探头
→ 仪器输入判高低 → 离散采样/触发 → 保留窗口 → 原始样本
→ 人按配置配对边沿、计算区间 → 带边界的结论
```

可选软件标记是另一条较长的路径：

```text
TIM2 更新事件 → UIF 标志与 UIE 使能 → NVIC（嵌套向量中断控制器）
→ TIM2_IRQHandler → HAL_TIM_IRQHandler → PeriodElapsedCallback
→ HAL_GPIO_WritePin → GPIO 输出边沿 → 同次外部采集
```

事件对象、所有权和设置入口必须分清：

| 对象/配置在哪里定义 | 谁持有、谁设置或传入 | 流动与生命周期 |
|---|---|---|
| 主机 `Edge[]` 合成事件 | `test_model.c` 的只读数组由调用者持有 | `sample_edges` 只借用读取；不是硬件事件记录 |
| 主机 `Sample[]` 样本缓冲 | 测试入口持有定长数组，传入函数 | 无动态分配；有效样本数由调用参数给出 |
| 主机采样起点/间隔、触发索引、窗口 | 调用者显式传入 | 算法不偷偷换时钟或补造缺失数据 |
| `htim2` 和 TIM2 配置 | 参考 `main.c` 的文件级静态句柄，生命周期覆盖运行期 | 初始化地址传给 HAL；中断使用同一个句柄，不复制局部句柄 |
| GPIO 候选、板级允许开关 | 参考工程配置者先核对器件/封装/板图，再设置 | BSP（board support package，板级支持包）候选逻辑在本课参考文件中；默认互锁禁止驱动 |
| 分析仪采集配置与文件 | 操作者在实际仪器/软件中设置，保存于采集记录 | 不存在固件向采样器“注入对象”的动作；电线承载电平，固件不能借 C 参数设定外部时钟 |
| 人的归因假设 | 记录中单列、可用变更反驳 | 不能让协议解析结果或截图标题代替原始样本 |

如果只截一张漂亮波形，没有固件身份、时钟和采集设置，就很难重现或反驳；本课的交付对象是证据记录，而不是截图的美观程度。

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

下面是当前调试主题的能力范围，不把所有分支都变成本课新增概念。高级分支只给工程入口与后续落点，不要求本课实现或测出它们。

| 层级 | 解决的问题、信号/数据/中断路径 | 配置入口、边界与后续落点 |
|---|---|---|
| 基础：周期、频率、脉宽、占空比 | PWM 引脚→数字样本→边沿配对；一条参考通道即可 | 本课深入。记录极性、Fs、N、触发和不确定度，不能由数字电平推出模拟幅度 |
| 进阶：多通道、触发前窗口、标记 | PWM→通道 0；更新 IRQ→GPIO 标记→通道 1；共享采集时标比较 | 本课第二概念。触发通道/边沿、前后长度与通道偏斜须核对；标记不是中断入口时间 |
| 高级：偶发窄脉冲 | 不常发生的事件→输入前端→采样/触发判据→保留证据 | 先用最小高低宽度和模型反例评估漏检；仪器若提供脉宽资格/毛刺触发，要另查最小识别宽度。`host-test`、`unit-test` 后续验证判读边界，实机压力采集待选仪器 |
| 高级：长时间、分段/流式 | 事件→采样缓冲→分段存储或传往主机，可能存在段间空隙/传输瓶颈 | 核对实际记录模式、丢样标记、连续性、通道数与时间戳；不能把多段拼图当无间断时间轴。后续综合实验保存原始文件与连续性证据 |
| 高级：协议解析回溯 | 原始时钟/数据边沿→解析器按阈值、极性和协议参数解释→字节/帧标签 | 解析标签是派生结果，异常帧先回到原始样本。SPI/UART 复验沿用已授外设课，不在此实现新解码器 |
| 高级：校准与判据复核 | 已知参考边沿/同源输入→多个通道→比较偏斜及判高条件 | 对应实际设备手册和校准记录；阈值与探头变化会改变交越时刻。没有仪器规格时只列执行清单，不给校准结果 |
| 跨外设：Timer→ADC→DMA | Timer TRGO（触发输出）→ADC（模数转换器）转换→DMA 填缓冲→半满/满/错误回调→软件 GPIO 标记 | 见 L029、L031、L032 已授链路。TRGO、采样孔径、DMA 写完与 GPIO 边沿不是同一时刻；后续在明确板/仪器后综合复验 |
| 系列差异：F4/F7/H5/H7 | 从器件内核/时钟/总线及安全配置到可观察 GPIO 的路径不同 | 见 §17 迁移表；只有 F407 是本课确定的外设实现，不能复制其寄存器或延迟结论到其他系列 |

跨外设链的缓冲所有权也会影响证据：DMA 工作段由 DMA 写入，CPU 只在约定的交接点读取；ADC 的 `HAL_ADC_ConvHalfCpltCallback`、`HAL_ADC_ConvCpltCallback` 和 `HAL_ADC_ErrorCallback` 是 [S3] §7 的软件通知入口，**不是 ADC 输入采样瞬间的外部时间戳**。不要在回调里复制大缓冲、格式化打印再把耗时误认为 DMA 硬件延迟。这里不配置请求映射、不写 ADC/DMA 新代码；后续复验须另核真实目标的请求、存储区和交接约束。

定时器本身也不止 PWM：主从触发通过更新/比较事件驱动另一计数器或 ADC；预装载把新参数在约定事件提交；DMA burst（定时器寄存器组的连续 DMA 访问）可按事件更新一组参数。TIM2 的同步、DCR/DMAR 见 [S1] §18.3.14–15、§18.4.17–18；互补输出、死区、刹车、重复计数属于适用的高级控制定时器路径，见 §17，**不能给 TIM2 臆加这些功能**。对应已有 L029/L030/L031 的后续实机复验，不在本课重讲其实现。[S6] 仅补充通用定时器机制，具体能力仍以器件 RM 为准。

### 7.2 参考目标与时钟/复位链

**器件边界：**参考 STM32F407VG；为核对器件引脚候选，选 `STM32F407VGT6`、LQFP100 作为文档算例，不声称实际持有此料号/封装或某块板。实际板必须重新读取丝印、板图及器件修订。规范来源为 [S1] RM0090 Rev 22（2026-05）和 [S2] DS8626 Rev 12（2026-03）；F405/F407 的 RCC（reset and clock control，复位与时钟控制）看 RM（reference manual，参考手册）的**第 7 章**，不要混用第 6 章 F42x/F43x 的附加路径。

**固件边界：**[S3] UM1725 Rev 8（2023-03）核对 HAL 字段、函数和宏；[S4] 2026-10-20 版本页把 STM32CubeF4 基包 1.28.0 与 Patch-CubeF4 1.28.3 分列。该补丁不是本课已安装、已编译的完整包。实际工程须记录基包与补丁应用情况、HAL/CMSIS（Arm 微控制器软件接口标准）版本和文件校验值；本课没有核验其全部源码组合，不能凭手册宣称目标兼容已通过。

**工具边界：**计划中的 CubeMX 6.18.1 在线章节本次访问超时；本课改用实际下载阅读的 [S5] UM1718 Rev 51（2026-05）§4.2、4.5、4.10、4.11、6。未启动 CubeMX/CubeMX2，也未生成 `.ioc` 配置文件。实机操作者填写实际应用版本，不把文档版本写成已运行的工具版本。

AHB（advanced high-performance bus，高级高性能总线）与 APB（advanced peripheral bus，高级外设总线）是本时钟链经过的总线。参考采用复位启动后的 HSI 直接作系统时钟，不启用 PLL（phase-locked loop，锁相环），避免假设板上晶振。16 MHz 是名义值，最终精度受工作条件约束。[S1] §7.2、§18.3.1–3：

```text
HSI nominal 16 MHz → SYSCLK source=HSI, PLL bypassed
→ AHB prescaler /1 → HCLK 16 MHz（内核、AHB 总线）
→ APB1 prescaler /1 → PCLK1 16 MHz
→ TIM2 内核时钟 16 MHz
→ PSC=15，即 /16 → CNT 每 1 µs 加一
→ ARR=999，0..999 → 更新周期 nominal 1000 µs
→ PWM1, CCR1=500, active high → CNT<500 为有效段
→ CC1E → GPIO AF1 候选 → 实际板网 → 探头
```

APB2 也设 /1、PCLK2 名义 16 MHz，但 TIM2 挂 APB1。在本 F407 路径中，APB 分频为 1 时定时器时钟等于该 PCLK，否则为其两倍；改变 APB1 为 /2 时须按此重算，不可直接把新的 PCLK 当计数器输入。[S1] §7.2，尤其 F405/F407 时钟树及 p.216–217 的说明；不向其他系列自动推广。

名义预测：

```text
fcnt = 16,000,000 / (15+1) = 1,000,000 Hz
T = (999+1) / fcnt = 1 ms
Thigh = 500 / fcnt = 500 µs
fPWM = 1 kHz，D = 500/1000 = 50%
```

这套公式限定为向上计数、边沿对齐、PWM1、高有效、`0<CCR1<ARR+1`；不拿它直接套中心对齐、反极性或极端占空比。`ClockDivision=DIV1` 对应 CKD 的滤波时基选择，不能误当另一个 CNT 预分频。[S1] §18.4.1。

门控/复位也必须闭环：

| 资源 | 门控与复位位置 | 本例动作 |
|---|---|---|
| GPIOA/B | RCC AHB1ENR；GPIOA/B 复位在 AHB1RSTR | 先开时钟再配单个 GPIO；不粗暴复位整个端口以免破坏其他功能 |
| TIM2 | RCC APB1ENR.TIM2EN、APB1RSTR.TIM2RST | HAL PWM MSP（MCU support package，底层资源初始化钩子）中开门控、强制并释放 TIM2 复位；本工程独占 TIM2 |
| TIM2 计数与输出 | CR1.CEN、CCER.CC1E、CCMR1.OC1M/OC1PE、ARR/PSC/CCR1 | 初始化期间不计数，提交预装载，清状态，最后 PWM Start |
| 更新通知 | DIER.UIE、SR.UIF、NVIC TIM2 IRQ | 主例关闭；可选标记开启。先清初始化 UG 留下的状态，再使能 |
| 分析仪 | 独立输入与时基 | 不在 MCU RCC 树内；单独记录其 Fs、阈值、深度、触发与时基规格 |

器件复位、软件强制外设复位、GPIO 输出状态和外部电路安全是不同层次。本例仅用于无危险负载的数字观察，停止计数或禁用通道不等于已经证明外部网络处于安全电平。电气限制、封装和供电见 [S2] §4、§6；具体硅修订对应勘误项仍需实机选定后核对。

### 7.3 CubeMX、HAL、LL 与寄存器对照

**CubeMX 配置清单（本次未操作工具）**，按 [S5] 生成一个独立参考工程，不修改全局设置：

| 页面/项目 | 候选配置 | 必须另行确认 |
|---|---|---|
| MCU Selector | STM32F407VGT6，非 Board Selector 的虚构开发板 | 实际完整料号、LQFP100 是否相同、硅修订、供电条件 |
| RCC / Clock Configuration | HSI ON，SYSCLK=HSI；不使用 PLL；AHB/APB1/APB2 全 /1 | HSI trim、16 MHz 名义值；未使用 HSE，不填写不存在的外部晶振 |
| SYS | Serial Wire（串行线调试）；HAL timebase=SysTick（系统节拍定时器） | 不选 TIM2 作 HAL 时基，避免与本例 PWM 所有权冲突 |
| TIM2 | Internal Clock；CH1 PWM Generation CH1；向上计数；PSC 15、ARR 999、Pulse 500；PWM1、高有效；ARR preload Enable；Fast Disable | 生成代码的 OC1PE；Channel 1 不是固定某个板上排针 |
| GPIO | 器件级候选 PA5/AF1/TIM2_CH1；PB0 输出标记，低初值；PP、NoPull、Low Speed 候选 | PA5 映射已由 [S2] 表 9 核对；**物理引脚号、接点、外部负载、上下拉、速度和探头连接尚未确定** |
| NVIC | 无标记时禁用 TIM2 IRQ；启用标记时 TIM2 IRQ 优先级 5/0，分组 4 | 参考无 RTOS；HAL tick 用 SysTick，记录其优先级；不能由优先级数字承诺延迟 |
| DMA | 不配置 | 本课不启用 DMA，也没有 DMA 缓冲或运行中的 DMA 回调 |
| Project Manager | 记录实际 CubeMX、编译器/构建器、固件基包+补丁；生成本项目局部文件 | 启用 HAL RCC/GPIO/TIM/CORTEX/FLASH 模块及所需头文件依赖；目标宏 `STM32F407xx`、`USE_HAL_DRIVER` |
| 回调模式 | `USE_HAL_TIM_REGISTER_CALLBACKS=0`，使用弱函数覆盖 | 若改注册模式，必须另核注册路径，不能静默套用此代码 |
| Flash/启动 | 参考 2.7–3.6 V 的供电设计范围、16 MHz 下 0 等待周期；标准复位启动 | 范围不是测量结果。实际 VDD、启动文件、系统文件、链接器内存布局及板图全部核对后才采用 |

PA5/PB0 是**数据手册可核对的芯片逻辑端口候选**，不是对用户现有板的接线命令。默认 `COURSE_BOARD_REVIEWED=0` 时，参考代码在配置这两个引脚之前进入故障等待；只有核对实际板图和安全连接后才能置 1。如果实际板不能用这些候选，应在自己目标工程中同时替换 GPIO 时钟、端口、pin、AF 和记录，不能只改探头标签。没有本板证据，本课不填任何实际测试点。

**HAL → 关键寄存器对照**；这是 LL/寄存器对照轨，避免再引入未经核对的 LL 函数名。HAL API 以 [S3] §68 为基准，寄存器以 [S1] 第 7、8、18 章为准：

| HAL/参考操作 | 实际硬件意义 | 核对观察点 |
|---|---|---|
| `HAL_RCC_OscConfig` / `ClockConfig` | RCC.CR 的 HSI 就绪、CFGR.SW/SWS 与 HPRE/PPRE | SWS 确认实际选择；软件名义频率不等于外部实测 |
| `__HAL_RCC_GPIOx_CLK_ENABLE` | AHB1ENR 对应端口使能 | 未开时钟时不能用 GPIO 初始化成功的想象替代检查 |
| `HAL_GPIO_Init` | MODER、OTYPER、OSPEEDR、PUPDR；AF 模式另写 AFR | PA5 使用 AFRL 的对应字段，AF1；具体接点须板图确认 |
| `HAL_TIM_PWM_Init` | TIM2 基本计数参数；调用 PWM MSP 钩子 | PSC=15、ARR=999、CR1 的方向/ARPE；不能把通用 HAL 说明中的 16 位描述当 TIM2 的完整位宽规格 |
| `HAL_TIM_PWM_ConfigChannel` | PWM1 对应 OC1M，高有效由 CC1P 控制；CCR1=500 | 本代码再明确置 OC1PE，便于审计预装载 |
| 写 `EGR.UG` 后清标志 | 提交 PSC/ARR/CCR 预装载，建立初始节拍；初始化更新状态不应被当成真实首个周期 | 使能 UIE 前清 UIF、清 NVIC pending，CNT=0 |
| `HAL_TIM_PWM_Start(CH1)` | 使能 CH1 输出和计数；本参考不选从触发启动 | CCER.CC1E 与 CR1.CEN；不需要高级定时器的 MOE 给 TIM2 “补开输出” |
| `__HAL_TIM_ENABLE_IT(UPDATE)` | DIER.UIE=1；不是 CC1IE，也不是 DMA 请求 | 更新触发后 SR.UIF 与 UIE 共同决定更新中断处理路径 |
| `HAL_TIM_IRQHandler` → `PeriodElapsedCallback` | HAL 按外设状态和使能分发更新通知 | 本目标包需在该函数中逐项核对 UIF/UIE 检查、清标志与回调顺序；手册不替代所用补丁源码审计 |
| `HAL_GPIO_WritePin` | GPIO BSRR 置位/复位所选输出 | 本标记只有一个写入者；GPIO 边沿在调用/总线写入后，而非 IRQ 断言时 |
| `HAL_TIM_PWM_Stop`、禁用 UIE/NVIC | 停止对应输出/计数路径并停止回调通知 | 本工程独占 TIM2；故障关停可直写禁用，但随后不允许自动重启未恢复的 HAL 状态 |

`UIF` 是更新事件标志，`CC1IF` 是捕获/比较 1 标志；有标志不等于相应 IRQ 已使能。本例不用 `HAL_TIM_PWM_Start_IT`，因此不把比较中断的 `PWM_PulseFinishedCallback` 混成周期更新回调。`SR` 标志的清除按 [S1] §18.4.5 和 [S3] 宏执行，不用随意读改写去“清全部状态”。长时间屏蔽中断还可能让多个更新合并为一个待处理标志，软件计数不天然等于真实边沿总数。

**为什么不叠加 `HAL_TIM_Base_Start_IT`？** 本课不依赖“PWM Start 后任意版本的 Base Start_IT 都可再次启动同一句柄”的假定。选定的路径是先配置 PWM，初始化更新/清状态，再显式开启 **更新中断位**，最后只调用一次 `HAL_TIM_PWM_Start`。两类操作的用途分别由 [S3] §68 的 Start API、`__HAL_TIM_ENABLE_IT` 宏与 [S1] DIER 约束。实际基包/补丁的句柄状态、通道状态及 IRQ 分发仍列为目标工程编译和源码审计项；没有这些记录就不声称已验证兼容。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

§9.1 的三个代码块保存为同一临时目录的 `model.h`、`model.c`、`test_model.c`，它们是本课自己编写的模型，不是下载的第三方源码。测试先写并用未实现的模型得到失败，再补实现；本次记录见运行目录：

- [失败基线：host-red.log](../../.state/runs/20261020-224728254-42772/host-red.log)
- [主机编译与运行：host-test.log](../../.state/runs/20261020-224728254-42772/host-test.log)

模型约定：两通道初始均为低；事件按非递减时间排序；与采样时间完全相等的事件先应用再采样；同一时间的事件按输入顺序应用，不模拟零宽脉冲的真实电气过程。`us` 是微秒整数，最多 64 个事件/样本；不模拟模拟波形、亚微秒脉冲、抖动、阈值、同步器、压缩记录或真实触发硬件。首个样本若已经高，不凭空推断它前面有一次可见上升沿。

`span_bounds` 只计算调用者已选择的两个边沿索引的位置差包络，不替调用者判断是否同一周期、是否存在漏掉的边沿。输入和输出数组不得重叠；错误返回时不会提交半条采样记录。`trigger_window` 的 `end` 为不包含的结束索引，缺少请求的前/后历史就拒绝，避免把裁断记录冒充完整窗口。

```powershell
# 在保存上述三个文件的临时目录执行；先确认 gcc 在当前 PATH 中。
gcc -std=c11 -Wall -Wextra -Werror -Wconversion -pedantic model.c test_model.c -o model-tests.exe
if ($LASTEXITCODE -ne 0) { throw 'host compile failed' }
.\model-tests.exe
if ($LASTEXITCODE -ne 0) { throw 'host test failed' }
```

实际主机结果是 **60 项检查通过**，日志记录了编译器身份。它只证明这里的 C 模型和这些反例断言，不证明用户已有该环境，也不证明 HAL、TIM2、GPIO、分析仪或电路工作正常。

### 8.2 STM32 参考实现轨道

§9.2 给出完整应用侧参考代码，不把硬件轨缩成“以后再接”。它依赖目标工程提供已正确匹配的 HAL/CMSIS、启动文件、向量表和链接配置；这与“已完成目标编译”是两回事。

构建与连接的待执行顺序：

1. 在自己的独立目标工程中按 §7.3 生成/核对配置并保存 `.ioc`、报告、工具版本和固件身份。不要覆盖本教程仓库的既有工程或修改 IDE/CubeMX 全局配置。
2. 将 §9.2 作为**替换参考应用**整合，不是直接追加到已有 `main.c` 末尾。`main`、`HAL_TIM_PWM_MspInit`、`TIM2_IRQHandler`、`SysTick_Handler`、HAL 回调只能各有一个有效实现；若生成工程把它们分到 `stm32f4xx_it.c` 等文件，应把对应函数迁移到生成文件的保留区，并移除目标工程中的重复定义。本教程未创建这些生成路径。
3. 保留 SysTick 作为 HAL 时基，TIM2 独占；核对 `USE_HAL_TIM_REGISTER_CALLBACKS=0`、所需 HAL 模块、目标宏、`HSI_VALUE`。从所用包头文件逐项检查代码中字段/常量，再在 `stm32f4xx_hal_tim.c` 中定位 PWM Init/Start/Stop、更新 IRQ 分支与句柄状态，记录文件 hash 和包组合。记录位置即可，不把整份驱动复制进教程。
4. 用实际选定构建器执行一次构建，保存完整命令、编译器版本、输出和固件 hash；本课未选工具链，因此不虚构一个已存在的 ELF 路径或构建命令成功记录。缺符号、结构字段或 IRQ 重定义时停止，先解决版本/集成差异，不能删掉错误处理来“编过去”。
5. 接线前完成 §12 的电气审核，确认真实料号、PA5/PB0 是否可用及测试点；满足后才在目标工程将 `COURSE_BOARD_REVIEWED` 设为 1。互锁不是电压检测器，不代表接线已经被程序自动验证。
6. 本次**不执行烧录**。将来由用户授权实际硬件实验时，先记录探针、目标供电、下载工具和固件身份，再按实际工具手册执行下载；没有执行就把下载栏保留“未执行”。
7. 仪器先按核对过的连接准备，选择实际支持的 Fs/通道/深度/触发。自由运行、跳过最初两周期后单通道观察；再启用可选标记做同次两通道采集，导出原始格式与带单位时间戳。未采集时不能生成一张标为实测的图。

**STM32 参考实现，待目标工程编译；未烧录、未测量。**可直接复用的是主机采样逻辑、名义参数计算和应用控制路径的思路；器件寄存器结论限定 F407；实际 HAL 包兼容、启动/链接/构建、引脚网络和所有仪器参数仍须在真实目标确认。

## 9. 最小代码示例

### 9.1 主机：合成事件、采样、触发窗口与区间

这三个文件都属于验证层：只依赖标准 C 库，不依赖 HAL。公开参数/结构字段使用固定宽度整数，缓冲由调用方持有，无动态内存。C 入口 `int main(void)` 遵守宿主环境约定。`MODEL_BAD` 是输入不合法，`MODEL_NOT_FOUND` 是合法数据里没有观察到上升沿，两者不能合并解释为“真实事件不存在”。

**`model.h`：接口与数据声明。**

```c
#ifndef L038_MODEL_H
#define L038_MODEL_H
#include <stdint.h>
#define MODEL_CAP 64U
#define MODEL_OK 0U
#define MODEL_BAD 1U
#define MODEL_NOT_FOUND 2U
typedef struct { uint32_t us; uint8_t channel; uint8_t level; } Edge;
typedef struct { uint32_t us; uint8_t bits; } Sample;
uint32_t sample_edges(const Edge *edges, uint32_t edge_n,
                      uint32_t start, uint32_t step, uint32_t count,
                      Sample *out);
uint32_t find_rise(const Sample *s, uint32_t n, uint8_t channel,
                   uint32_t *index);
uint32_t trigger_window(uint32_t n, uint32_t trigger, uint32_t pre,
                        uint32_t post, uint32_t *begin, uint32_t *end);
uint32_t span_bounds(const Sample *s, uint32_t n, uint32_t i, uint32_t j,
                     int64_t *low, int64_t *high);
#endif
```

**`model.c`：理想采样实现。**`valid_samples` 检查已有记录的位范围和时间顺序；`sample_edges` 先验证全部输入，再提交样本，避免无效事件留下半条记录。

```c
#include "model.h"
#include <stddef.h>
static uint32_t valid_samples(const Sample *s, uint32_t n)
{
    if (s == NULL || n == 0U || n > MODEL_CAP) { return MODEL_BAD; }
    for (uint32_t k = 0U; k < n; ++k) {
        if (s[k].bits > 3U || (k > 0U && s[k].us <= s[k-1U].us)) {
            return MODEL_BAD;
        }
    }
    return MODEL_OK;
}
uint32_t sample_edges(const Edge *edges, uint32_t edge_n,
                      uint32_t start, uint32_t step, uint32_t count,
                      Sample *out)
{
    if (out == NULL || (edge_n > 0U && edges == NULL) ||
        edge_n > MODEL_CAP || count == 0U || count > MODEL_CAP ||
        step == 0U || (count-1U) > (UINT32_MAX-start)/step) {
        return MODEL_BAD;
    }
    for (uint32_t k = 0U; k < edge_n; ++k) {
        if (edges[k].channel > 1U || edges[k].level > 1U ||
            (k > 0U && edges[k].us < edges[k-1U].us)) {
            return MODEL_BAD;
        }
    }
    uint8_t bits = 0U;
    uint32_t e = 0U;
    for (uint32_t k = 0U; k < count; ++k) {
        const uint32_t t = start + k*step;
        while (e < edge_n && edges[e].us <= t) {
            const uint8_t mask = (uint8_t)(1U << edges[e].channel);
            if (edges[e].level != 0U) { bits = (uint8_t)(bits | mask); }
            else { bits = (uint8_t)(bits & (uint8_t)~mask); }
            ++e;
        }
        out[k].us = t;
        out[k].bits = bits;
    }
    return MODEL_OK;
}
uint32_t find_rise(const Sample *s, uint32_t n, uint8_t channel,
                   uint32_t *index)
{
    if (index == NULL || channel > 1U || valid_samples(s,n) != MODEL_OK) {
        return MODEL_BAD;
    }
    const uint8_t mask = (uint8_t)(1U << channel);
    for (uint32_t k = 1U; k < n; ++k) {
        if ((s[k-1U].bits & mask) == 0U && (s[k].bits & mask) != 0U) {
            *index = k;
            return MODEL_OK;
        }
    }
    return MODEL_NOT_FOUND;
}
uint32_t trigger_window(uint32_t n, uint32_t trigger, uint32_t pre,
                        uint32_t post, uint32_t *begin, uint32_t *end)
{
    if (begin == NULL || end == NULL || begin == end ||
        n == 0U || n > MODEL_CAP || trigger >= n || pre > trigger ||
        post > n-1U-trigger) { return MODEL_BAD; }
    *begin = trigger-pre;
    *end = trigger+post+1U;
    return MODEL_OK;
}
uint32_t span_bounds(const Sample *s, uint32_t n, uint32_t i, uint32_t j,
                     int64_t *low, int64_t *high)
{
    if (low == NULL || high == NULL || low == high ||
        valid_samples(s,n) != MODEL_OK || i == 0U || j == 0U ||
        i >= n || j >= n) { return MODEL_BAD; }
    *low = (int64_t)s[j-1U].us - (int64_t)s[i].us;
    *high = (int64_t)s[j].us - (int64_t)s[i-1U].us;
    return MODEL_OK;
}
```

**`test_model.c`：调用者实例化事件/缓冲并运行反例。**所有时间和电平都是合成值。它验证两种短脉冲采样率、同采样率不同相位、正常 PWM、预触发裁剪、共享平移和非法输入，不构造伪硬件波形。

```c
#include "model.h"
#include <assert.h>
#include <inttypes.h>
#include <stddef.h>
#include <stdio.h>
static uint32_t checks;
#define CHECK(expr) do { ++checks; assert(expr); } while (0)
int main(void)
{
    Sample s[MODEL_CAP] = {0};
    Sample shifted[MODEL_CAP] = {0};
    uint32_t idx = 99U, begin = 99U, end = 99U;
    int64_t low = 0, high = 0;
    const Edge pwm[] = { {100U,0U,1U},{600U,0U,0U},
                        {1100U,0U,1U},{1600U,0U,0U},
                        {2100U,0U,1U}};
    CHECK(sample_edges(pwm,5U,0U,100U,24U,s) == MODEL_OK);
    CHECK(s[1].bits == 1U && s[6].bits == 0U);
    CHECK(find_rise(s,24U,0U,&idx) == MODEL_OK && idx == 1U);
    CHECK(span_bounds(s,24U,1U,6U,&low,&high) == MODEL_OK);
    CHECK(low == 400 && high == 600);
    CHECK(span_bounds(s,24U,1U,11U,&low,&high) == MODEL_OK);
    CHECK(low == 900 && high == 1100);
    printf("PWM model: high=500 us, conservative=[400,600] us; "
           "period=1000 us, conservative=[900,1100] us\n");

    const Edge pulse[] = { {103U,0U,1U},{105U,0U,0U}};
    CHECK(sample_edges(pulse,2U,100U,10U,3U,s) == MODEL_OK);
    CHECK(s[0].bits == 0U && s[1].bits == 0U && s[2].bits == 0U);
    CHECK(find_rise(s,3U,0U,&idx) == MODEL_NOT_FOUND);
    puts("Ideal short pulse: rise=103 us, fall=105 us");
    puts("100 kS/s, phase A: (100,0) (110,0) (120,0): MISSED");
    CHECK(sample_edges(pulse,2U,94U,10U,4U,s) == MODEL_OK);
    CHECK(s[1].us == 104U && s[1].bits == 1U && s[2].bits == 0U);
    CHECK(find_rise(s,4U,0U,&idx) == MODEL_OK && idx == 1U);
    CHECK(span_bounds(s,4U,1U,2U,&low,&high) == MODEL_OK);
    CHECK(low == 0 && high == 20);
    puts("100 kS/s, phase B: (94,0) (104,1) (114,0) (124,0): "
         "read=10 us, conservative=[0,20] us");
    CHECK(sample_edges(pulse,2U,100U,1U,10U,s) == MODEL_OK);
    CHECK(find_rise(s,10U,0U,&idx) == MODEL_OK && idx == 3U);
    CHECK(span_bounds(s,10U,3U,5U,&low,&high) == MODEL_OK);
    CHECK(low == 1 && high == 3);
    puts("1 MS/s model: read=2 us, conservative=[1,3] us");
    CHECK(sample_edges(pulse,2U,104U,1U,3U,s) == MODEL_OK);
    CHECK(find_rise(s,3U,0U,&idx) == MODEL_NOT_FOUND);

    const Edge marked[] = { {75U,1U,1U},{90U,1U,0U},{100U,0U,1U}};
    CHECK(sample_edges(marked,3U,50U,5U,20U,s) == MODEL_OK);
    CHECK(find_rise(s,20U,0U,&idx) == MODEL_OK && idx == 10U);
    CHECK(trigger_window(20U,idx,1U,3U,&begin,&end) == MODEL_OK);
    CHECK(begin == 9U && end == 14U && s[begin].us == 95U);
    CHECK(trigger_window(20U,idx,6U,3U,&begin,&end) == MODEL_OK);
    CHECK(begin == 4U && s[begin].us == 70U && s[5].bits == 2U);
    CHECK(trigger_window(20U,idx,11U,3U,&begin,&end) == MODEL_BAD);
    puts("Trigger at 100 us: pre=5 us excludes marker at 75 us; "
         "pre=30 us retains it");

    const Edge pair[] = { {100U,0U,1U},{130U,1U,1U}};
    const Edge moved[] = { {600U,0U,1U},{630U,1U,1U}};
    CHECK(sample_edges(pair,2U,50U,10U,20U,s) == MODEL_OK);
    CHECK(sample_edges(moved,2U,550U,10U,20U,shifted) == MODEL_OK);
    CHECK(span_bounds(s,20U,5U,8U,&low,&high) == MODEL_OK);
    CHECK(low == 20 && high == 40);
    CHECK(span_bounds(shifted,20U,5U,8U,&low,&high) == MODEL_OK);
    CHECK(low == 20 && high == 40);
    CHECK(span_bounds(s,20U,8U,5U,&low,&high) == MODEL_OK);
    CHECK(low == -40 && high == -20);
    puts("Shared time shift +500 us: interval remains [20,40] us; "
         "reverse interval=[-40,-20] us");

    s[0].us = 77U; s[0].bits = 3U;
    const Edge bad_order[] = { {2U,0U,1U},{1U,0U,0U}};
    const Edge bad_channel[] = { {1U,2U,1U}};
    const Edge bad_level[] = { {1U,0U,2U}};
    CHECK(sample_edges(pwm,5U,0U,0U,4U,s) == MODEL_BAD);
    CHECK(sample_edges(pwm,5U,0U,1U,0U,s) == MODEL_BAD);
    CHECK(sample_edges(pwm,5U,0U,1U,65U,s) == MODEL_BAD);
    CHECK(sample_edges(bad_order,2U,0U,1U,4U,s) == MODEL_BAD);
    CHECK(sample_edges(bad_channel,1U,0U,1U,4U,s) == MODEL_BAD);
    CHECK(sample_edges(bad_level,1U,0U,1U,4U,s) == MODEL_BAD);
    CHECK(sample_edges(pwm,5U,UINT32_MAX,1U,2U,s) == MODEL_BAD);
    CHECK(sample_edges(NULL,1U,0U,1U,4U,s) == MODEL_BAD);
    CHECK(sample_edges(pwm,5U,0U,1U,4U,NULL) == MODEL_BAD);
    CHECK(s[0].us == 77U && s[0].bits == 3U);
    CHECK(find_rise(s,0U,0U,&idx) == MODEL_BAD);
    CHECK(find_rise(s,1U,2U,&idx) == MODEL_BAD);
    CHECK(find_rise(s,1U,0U,NULL) == MODEL_BAD);
    CHECK(trigger_window(20U,20U,0U,0U,&begin,&end) == MODEL_BAD);
    CHECK(trigger_window(20U,10U,0U,10U,&begin,&end) == MODEL_BAD);
    CHECK(trigger_window(20U,10U,0U,0U,NULL,&end) == MODEL_BAD);
    CHECK(trigger_window(20U,10U,0U,0U,&begin,&begin) == MODEL_BAD);
    CHECK(span_bounds(s,1U,0U,0U,&low,&high) == MODEL_BAD);
    CHECK(span_bounds(NULL,1U,1U,1U,&low,&high) == MODEL_BAD);
    CHECK(span_bounds(s,1U,1U,1U,&low,&low) == MODEL_BAD);
    s[0].bits = 4U;
    CHECK(find_rise(s,1U,0U,&idx) == MODEL_BAD);
    CHECK(sample_edges(NULL,0U,0U,1U,1U,s) == MODEL_OK);
    CHECK(s[0].us == 0U && s[0].bits == 0U);
    CHECK(find_rise(s,1U,0U,&idx) == MODEL_NOT_FOUND);
    puts("MODEL ONLY: no GPIO, HAL, analyzer or board has been tested.");
    printf("PASS: %" PRIu32 " checks\n", checks);
    return 0;
}
```

日志里的关键结果应这样读：`read=10 us` 是样本推算值，`[0,20] us` 是理想保守包络；真实模型输入宽度是 2 µs。后面的 `read=2 us, [1,3] us` 说明采样率提升缩小了包络，而不是证明仪器已有 1 µs 精度。

### 9.2 STM32：名义 1 kHz PWM 与可选更新标记

以下是本课原创的应用侧参考，不是 HAL 驱动的复制。将其视为参考工程的 `main.c` 整合内容，函数归属如下：

- `Course_Clock`、`Course_TimerInit`、`Course_Start/Stop`：应用调用的目标适配，依赖 HAL 与 F407 寄存器；`htim2` 由本文件静态持有，非栈上临时对象。
- `Course_Pins`、PWM MSP 钩子：器件/板级适配候选；默认互锁阻止输出，真实接点与封装不由代码猜测。
- IRQ 入口与回调：ISR 路径；运行期使用同一句柄；标记只由此路径写入，错误/停止路径可将其拉回低。
- `g_course_fault`、`g_course_updates`：便于调试器读取的状态，不是精确时间戳；`volatile` 使观察访问不被优化掉，不是并发同步框架。

代码默认关闭标记；核对目标后设 `COURSE_MARKER_ENABLE=1` 才打开更新 IRQ。标记采用**每次更新交替置位/清零**，而非两次紧邻写入形成难以捕获的极窄脉冲。若每次更新都被服务，标记任意相邻边沿间距名义约 1 ms，**只量上升沿的周期约 2 ms**；不可把它错当 PWM 周期翻倍。

```c
/* STM32F407VG reference ONLY; not compiled against a target Cube project.
 * These are CHIP-LEVEL candidates, not a board wiring instruction.
 * Default interlock prevents touching PA5/PB0 until the actual board is reviewed.
 */
#include "stm32f4xx_hal.h"
#include <stdint.h>
#include <stddef.h>
#ifndef COURSE_BOARD_REVIEWED
#define COURSE_BOARD_REVIEWED 0U
#endif
#ifndef COURSE_MARKER_ENABLE
#define COURSE_MARKER_ENABLE 0U
#endif
static TIM_HandleTypeDef htim2;
static uint32_t timer_clocked;
static uint32_t pins_ready;
static uint32_t marker_enabled;
static uint8_t marker_level;
volatile uint32_t g_course_fault;
volatile uint32_t g_course_updates;
volatile uint32_t g_course_stop_request;

static void Course_Fail(uint32_t code)
{
    g_course_fault = code; /* Last fault; not an event log. */
    HAL_NVIC_DisableIRQ(TIM2_IRQn);
    if (timer_clocked != 0U) {
        TIM2->DIER = 0U;
        TIM2->CCER = 0U;
        CLEAR_BIT(TIM2->CR1, TIM_CR1_CEN);
    }
    HAL_NVIC_ClearPendingIRQ(TIM2_IRQn);
    marker_enabled = 0U;
    if (pins_ready != 0U) {
        HAL_GPIO_WritePin(GPIOB, GPIO_PIN_0, GPIO_PIN_RESET);
    }
    /* No automatic retry: HAL state can now differ from raw register state. */
}

static HAL_StatusTypeDef Course_Clock(void)
{
    RCC_OscInitTypeDef osc = {0};
    RCC_ClkInitTypeDef clk = {0};
    osc.OscillatorType = RCC_OSCILLATORTYPE_HSI;
    osc.HSIState = RCC_HSI_ON;
    osc.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
    osc.PLL.PLLState = RCC_PLL_NONE;
    if (HAL_RCC_OscConfig(&osc) != HAL_OK) { return HAL_ERROR; }
    clk.ClockType = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK |
                    RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    clk.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
    clk.AHBCLKDivider = RCC_SYSCLK_DIV1;
    clk.APB1CLKDivider = RCC_HCLK_DIV1;
    clk.APB2CLKDivider = RCC_HCLK_DIV1;
    return HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_0);
}

static void Course_Pins(void)
{
    GPIO_InitTypeDef pin = {0};
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    /* PA5 AF1 is a verified CHIP mapping, subject to board review. */
    pin.Pin = GPIO_PIN_5;
    pin.Mode = GPIO_MODE_AF_PP;
    pin.Pull = GPIO_NOPULL;
    pin.Speed = GPIO_SPEED_FREQ_LOW;
    pin.Alternate = GPIO_AF1_TIM2;
    HAL_GPIO_Init(GPIOA, &pin);
    /* PB0 is only a chip-level GPIO candidate; no board connection is assumed. */
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_0, GPIO_PIN_RESET);
    pin.Pin = GPIO_PIN_0;
    pin.Mode = GPIO_MODE_OUTPUT_PP;
    pin.Alternate = 0U;
    HAL_GPIO_Init(GPIOB, &pin);
    pins_ready = 1U;
}

void HAL_TIM_PWM_MspInit(TIM_HandleTypeDef *h)
{
    if (h != NULL && h->Instance == TIM2) {
        __HAL_RCC_TIM2_CLK_ENABLE();
        __HAL_RCC_TIM2_FORCE_RESET();
        __HAL_RCC_TIM2_RELEASE_RESET();
        timer_clocked = 1U;
    }
}

static HAL_StatusTypeDef Course_TimerInit(void)
{
    TIM_OC_InitTypeDef oc = {0};
    htim2.Instance = TIM2;
    htim2.Init.Prescaler = 15U;
    htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim2.Init.Period = 999U;
    htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
    if (HAL_TIM_PWM_Init(&htim2) != HAL_OK) { return HAL_ERROR; }
    oc.OCMode = TIM_OCMODE_PWM1;
    oc.Pulse = 500U;
    oc.OCPolarity = TIM_OCPOLARITY_HIGH;
    oc.OCFastMode = TIM_OCFAST_DISABLE;
    if (HAL_TIM_PWM_ConfigChannel(&htim2, &oc, TIM_CHANNEL_1) != HAL_OK) {
        return HAL_ERROR;
    }
    /* Exclusive TIM2 owner. No DMA requests or CC interrupts. */
    TIM2->DIER = 0U;
    SET_BIT(TIM2->CCMR1, TIM_CCMR1_OC1PE);
    /* Load PSC/ARR/CCR preload before arming the update interrupt. */
    TIM2->EGR = TIM_EGR_UG;
    __HAL_TIM_SET_COUNTER(&htim2, 0U);
    __HAL_TIM_CLEAR_FLAG(&htim2, TIM_FLAG_UPDATE | TIM_FLAG_CC1);
    HAL_NVIC_DisableIRQ(TIM2_IRQn);
    HAL_NVIC_ClearPendingIRQ(TIM2_IRQn);
    return HAL_OK;
}

static HAL_StatusTypeDef Course_Start(uint32_t use_marker)
{
    marker_enabled = use_marker != 0U ? 1U : 0U;
    marker_level = 0U;
    g_course_updates = 0U;
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_0, GPIO_PIN_RESET);
    __HAL_TIM_CLEAR_FLAG(&htim2, TIM_FLAG_UPDATE | TIM_FLAG_CC1);
    HAL_NVIC_ClearPendingIRQ(TIM2_IRQn);
    if (marker_enabled != 0U) {
        HAL_NVIC_SetPriority(TIM2_IRQn, 5U, 0U);
        __HAL_TIM_ENABLE_IT(&htim2, TIM_IT_UPDATE);
        HAL_NVIC_EnableIRQ(TIM2_IRQn);
    }
    /* Do not stack HAL_TIM_Base_Start_IT on this start operation. */
    return HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_1);
}

void TIM2_IRQHandler(void)
{
    HAL_TIM_IRQHandler(&htim2);
}

void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *h)
{
    if (h != NULL && h->Instance == TIM2 && marker_enabled != 0U &&
        g_course_fault == 0U) {
        ++g_course_updates;
        marker_level = (uint8_t)(marker_level ^ 1U);
        HAL_GPIO_WritePin(GPIOB, GPIO_PIN_0,
                         marker_level != 0U ? GPIO_PIN_SET : GPIO_PIN_RESET);
    }
}

void HAL_TIM_ErrorCallback(TIM_HandleTypeDef *h)
{
    if (h != NULL && h->Instance == TIM2) { Course_Fail(0xE1U); }
}

uint32_t Course_Stop(void)
{
    HAL_StatusTypeDef result;
    HAL_NVIC_DisableIRQ(TIM2_IRQn);
    __HAL_TIM_DISABLE_IT(&htim2, TIM_IT_UPDATE);
    marker_enabled = 0U;
    result = HAL_TIM_PWM_Stop(&htim2, TIM_CHANNEL_1);
    __HAL_TIM_CLEAR_FLAG(&htim2, TIM_FLAG_UPDATE | TIM_FLAG_CC1);
    HAL_NVIC_ClearPendingIRQ(TIM2_IRQn);
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_0, GPIO_PIN_RESET);
    if (result != HAL_OK) { Course_Fail(0xE2U); return 1U; }
    return 0U;
}

void SysTick_Handler(void)
{
    HAL_IncTick(); /* Default HAL SysTick timebase; TIM2 is NOT the HAL tick. */
}

int main(void)
{
    if (HAL_Init() != HAL_OK) { Course_Fail(0xA0U); }
    if (g_course_fault == 0U && Course_Clock() != HAL_OK) {
        Course_Fail(0xA1U);
    }
    /* This is a human review interlock, NOT an electrical self-test. */
    if (g_course_fault == 0U && COURSE_BOARD_REVIEWED != 1U) {
        Course_Fail(0xB0U);
    }
    if (g_course_fault == 0U) {
        HAL_NVIC_SetPriorityGrouping(NVIC_PRIORITYGROUP_4);
        Course_Pins();
        if (Course_TimerInit() != HAL_OK) { Course_Fail(0xC0U); }
    }
    if (g_course_fault == 0U && Course_Start(COURSE_MARKER_ENABLE) != HAL_OK) {
        Course_Fail(0xC1U);
    }
    for (;;) {
        if (g_course_fault == 0U && g_course_stop_request != 0U) {
            (void)Course_Stop();
            g_course_stop_request = 0U;
        }
        __WFI();
    }
}
```

#### 初始化字段与调用顺序的逐项解释

1. `HAL_Init` 建立默认 HAL 时基；`Course_Clock` 选择 HSI 和三组 /1 分频。`ClockType` 指明同时设置 SYSCLK/HCLK/PCLK1/PCLK2，`FLASH_LATENCY_0` 只在本节选定电压范围和 16 MHz 参考条件下使用，不能带去高频工程。[S1] §3.5、§7；[S3] RCC 接口。
2. 通过板级互锁后，`Course_Pins` 先开 AHB1 门控。`Pin` 是端口位掩码，`Mode` 区分 AF 推挽与普通推挽，`Pull` 为内部上下拉候选，`Speed` 控制输出驱动速度而不是定时器频率，`Alternate=GPIO_AF1_TIM2` 选复用通路。[S1] 第 8 章；[S2] 表 9。
3. `htim2.Instance` 选 TIM2；`Prescaler`、`Period` 分别写 PSC/ARR；`CounterMode` 为向上；`ClockDivision` 不另分 CNT；`AutoReloadPreload` 允许 ARR 经更新提交。`oc` 的模式、Pulse、极性、FastMode 决定 CH1 行为。TIM2 不用互补输出、死区或重复计数字段。[S1] 第 18 章；[S3] §68。
4. PWM Init 的 MSP 钩子打开并复位独占 TIM2。ConfigChannel 后明确使能 OC1PE，再用 UG 提交初始预装载、CNT 归零、清 UIF/CC1IF/NVIC pending；否则初始化软件更新也可能被错当一次周期通知。
5. 可选标记先开更新中断位和 NVIC，再调用一次 PWM Start；默认不使能 CC1 中断，不使用 DMA。不要通过 `PWM_Start_IT` 来假装获取更新回调；要核对它启用的实际中断类别。
6. 在本预期驱动路径中，HAL IRQ 对更新标志及中断使能作判断、清标志后分发 `HAL_TIM_PeriodElapsedCallback`。回调只交替写标记，不打印、不延时、不搬数据；具体源码顺序仍按 §8.2 第 3 步在所用包审计。`HAL_TIM_ErrorCallback` 是非阻塞错误通知入口，不是所有 PWM 故障的检测器；接错脚、阈值不合或输出被外部电路拉住，不保证触发它。
7. `Course_Stop` 的前提是已成功初始化/启动本参考实例；主循环只在无故障且收到停止请求时调用。正常停止先封住 IRQ，再停 CH1，清状态并拉低标记。故障路径额外直接禁用 TIM2 请求/输出/计数，记录故障后不自动重启，避免 HAL 软件状态与硬件状态不一致。若需从故障重试，应先导出证据并复位重初始化，不在本课增加运行时恢复协议。

| 故障码 | 含义 | 观察/处理 |
|---|---|---|
| `0xA0/0xA1` | HAL 初始化/时钟配置失败 | 输出不启动；检查 HAL 时基、供电和 HSI/RCC 状态 |
| `0xB0` | 板级审核互锁未放行 | **默认预期状态**，不是芯片坏了；不能为消除错误而跳过审核 |
| `0xC0/0xC1` | PWM 配置/启动失败 | 核对包 API、句柄/通道状态、资源冲突，保留返回状态与版本 |
| `0xE1` | HAL 定时器错误通知 | 禁止输出，保留故障；不把它理解为外部电路全覆盖监控 |
| `0xE2` | 正常停止 API 返回异常 | 锁存故障并禁用硬件路径；不自动重新 Start |

停止/失败后，固件没有保证 PA5 所连外部电路电平已安全。实际连接只应是审核过的无危险数字观测网络；不能将本例当电机、加热器等负载的失效安全控制。

#### 首周期和可选标记的判读

CH1 使能与 CEN 启动的寄存器写入并非一个外部原子事件。PWM 输出在启动阶段可能先进入有效态，因此不要把第一次可见上升沿强行对齐第一次更新回调；等待至少两个完整稳态周期再分析。

稳态时，周期边界可能同时使 PWM 参考恢复有效并置 UIF；软件标记还要经历中断等待、HAL 分发和 GPIO 写入。两路延迟包含这些路径及输出/探头/采样差异，不能写成“IRQ 精确延迟”。若中断被长期屏蔽，多个更新还可能合并，标记不再逐周期变化；先检查原始边沿，不只看平均频率。

## 10. 常见错误

| 错误判断/操作 | 为什么不成立 | 可证伪的改法 |
|---|---|---|
| 没抓到脉冲，所以没发生 | 窄脉冲可落在样本间；窗口可能不含它 | 保持事件不变，改变 Fs/相位/前窗口；仍保留未检出的边界说明 |
| 周期频率不高，低 Fs 就一定够 | 脉宽可远小于周期；占空比极端时尤其如此 | 按最短高/低电平设计样本余量，不只看重复频率 |
| 把第一次高样本当真实上升沿 | 没有之前低样本，就没有这次采集内的边沿夹逼 | 提前采样或增加前窗口，不补造上升沿 |
| PWM 有 UIF 就应有回调 | 还需 UIE、NVIC、向量与正确句柄 | 按事件→使能→IRQ→HAL→回调逐段查 |
| 用 PWM 比较回调当周期边界 | CC1IF 与 UIF 是不同事件 | 比较代码与 DIER 位，确认更新中断路径 |
| 标记上升沿每 2 ms，所以定时器跑慢 | 本例标记每次更新交替电平 | 同时看标记的全部边沿与 PWM；不要只测标记同极性周期 |
| 暂停后 CNT 正常，所以连续采集也正常 | 暂停/冻结配置会改变时序 | 连续采集时不打断点，另保存暂停取证条件 |
| 逻辑分析仪看起来方正，所以没有过冲 | 数字记录不保留模拟幅度与边沿细节 | 模拟问题用适当模拟测量工具及其安全规格，不从数字截图推断 |
| 换了通道数，仍引用原来 Fs/深度 | 仪器可能改变可用资源/记录模式 | 每次采集导出实际设置，不照抄上次界面数值 |
| 协议解码显示错误，就修改驱动 | 解码参数、阈值、采样和触发也可能错 | 回看原始时钟/数据边沿，再判断发送/采集/解析哪层出错 |

## 11. 调试观察点

先记录运行模式和预期，再查最短证据链；不要一上来同时改时钟、GPIO、采样率和触发。

| 现象 | 应看什么 | 如何区分原因 |
|---|---|---|
| 所有周期恰好接近预测的两倍/一半 | RCC SWS、PPRE1、TIM2 PSC/ARR、PWM 极性及所选边沿 | APB 定时器时钟关系、参数偏一、同极性/异极性配对错误；再对照 Fs 和标记交替模式 |
| CNT 在走，外部无波形 | CC1E、OC1M、CCR1、GPIO MODER/AFRL、AHB1/APB1 门控、实际网络 | 内部波形生成与输出路由分开查；电气审核后检查探头地参考、阈值、通道和真实接点，不臆造板上位置 |
| PWM 正常，标记没有 | `COURSE_MARKER_ENABLE`、UIE/UIF、NVIC、向量、句柄、回调覆盖模式 | 禁用标记是默认情况；排除 TIM2 被误作 HAL 时基、重复 IRQ 或被另一路代码重配 |
| 标记相对 PWM 抖动，PWM 周期稳定 | 同次采集的间隔分布、ISR 路径、其他 IRQ、SysTick、屏蔽区间 | 先区分一个 Ts 的量化变化与更大路径变化；检查通道偏斜/阈值，不立即归咎内核 |
| 标记缺边沿/错周期 | UIF 是否合并、是否停过计数/中断、是否触发窗口裁断 | 不能拿 `g_course_updates` 当独立硬件计数器去证明不存在漏服务 |
| 边沿数量随 Fs 或阈值变化 | 原始样本、最小脉宽、实际触发资格/滤波设置 | 能否由采样模型解释？模拟毛刺与输入阈值问题仍需其他证据 |
| 停止后仍显示旧波形 | 采集时间、是否仍展示上次缓冲、仪器是否再次触发、实际输出网络 | 不把历史缓存误认为当前活动；未再次采集就不能下“停不下来”的结论 |

RCC/GPIO/TIM2 寄存器字段来源分别为 [S1] §7.3、§8.4、§18.4；GPIO 复用和供电边界来源 [S2]。在暂停态读寄存器，只作另一次配置快照，注明时间/状态，不冒充自由运行时每个边沿的同时现场。

## 12. 实战实验

### 12.1 无板也可完成：模型与采集方案

1. 运行 §9.1，核对 60 项检查及日志中三个短脉冲样本序列；把“输入宽度”“样本读数”“保守包络”分开写。
2. 先手算：同一个 2 µs 脉冲在 100 kS/s、1 MS/s 下各可能怎样？为何相位改变能让第一次采样从完全漏检变成高估宽度？再用代码核对。
3. 触发保持通道 0、100 µs 被观察到的上升沿，先保留 5 µs 再保留 30 µs 的前历史，说明 75 µs 的另一路标记是否能被保留。它是窗口选择，不是“改变了先前事件”。
4. 平移所有事件和采样起点 500 µs，解释间隔为何不变；反例是只移动某通道、只改一个文件的零点，不能当共享参照。
5. 写出参考 STM32 的时钟与 PSC/ARR/CCR 推导及板级待审核项，输出一份**待执行**采集方案，不填实测值。无法解释前置算式时先回顾旧课，不自动推进新主题。

### 12.2 将来实机前的安全清单

以下不是对未知仪器的使用授权；型号与接线未确认时停在方案阶段：

- 核对目标实际 VDD、信号高低电平范围、仪器输入绝对额定值、阈值可选范围、输入阻抗/负载和探头限制。STM32 的某些输入容限不能推出分析仪探头耐压，更不能把所有 GPIO 当同一容限类型。[S2] §4、§6 仅约束芯片。
- 确认目标地、分析仪地、电脑/电源接地关系以及可能的地电位差。对未知隔离/高压/市电系统不直接连地夹；本课仅针对审核过的安全低压数字网络。不把外部未知导线接入 GPIO。
- 在适当断电/安全状态按实际设备手册连接并复核探头/地参考；操作顺序、可否带电插拔、保护方式以实际设备和电路规范为准。本课不假定仪器隔离，也不给未知型号的安全电压。
- 确认 PA5/PB0 候选在真实板图中未连接冲突负载、未被其他外设占用；标记线不能意外驱动敏感电路。未确定测试点和接地审核前，不放行 `COURSE_BOARD_REVIEWED`。
- 记录探头、线长/连接方式、输入阈值及设备校准。实际仪器手册若不在来源政策允许域，不把它冒充本课 STM32 规范引文；仍必须在实机记录中保存其身份与规格，不因域名限制跳过安全核对。

### 12.3 单通道：先核对预测，再采集

待用户提供并审核硬件、完成目标编译及授权下载后，由实际操作者执行：

1. 默认关闭标记，以安全、已核对连接的 CH1 输出作参考。等待启动后的至少两个完整周期，选上升沿触发。
2. 第一组请求 100 kS/s、`Ts=10 µs`，至少覆盖若干 1 ms 周期。示例方案 `N=601` 对应首末间隔 6 ms；第二组请求 1 MS/s、`N=6001`，同样为 6 ms。**这些只是请求值**，若仪器不支持应按手册调整并写实，不能声称设备已能做到。
3. 高电平预测 500 µs；理想量化半宽分别 10 µs 和 1 µs；再加入实际时基、阈值和探头预算。将预测、观察和不确定度列分开。
4. 固定 PSC/ARR，只将 CCR1 从 500 改为 250，预计周期名义仍 1 ms、高电平变 250 µs。实际结果未取得前只写“预计”，不把一次参数变化自动当成模型已证实。
5. 恢复参数并导出原始采集格式和带单位的时间戳/CSV（逗号分隔文本）；记录通道映射、采样/触发配置、采集时刻、固件 hash，截图仅作辅助。

### 12.4 双通道：审计标记归因

1. 在同一已经审核的目标工程启用标记，第二通道连接经确认的标记测试点；记录新增负载和代码开关。
2. 触发仍选 PWM 通道，不以标记触发而隐去它之前的硬件事件。例：请求 1 MS/s，前 2 ms、后 4 ms，含触发样本时总计可按 `2000+1+4000=6001` 样本安排；实际界面前后定义以仪器核对结果为准。
3. 同次采集内选择稳态的一次 PWM 周期边界与对应的标记变化，报告边沿夹逼区间与误差预算。记录用的是标记上升还是下降沿；标记的上升沿每隔两次更新才出现一次。
4. 增减触发前窗口，不改固件，检查历史是否被裁断；把触发零点平移不应改变已保留边沿的相对间隔。不要拿两次独立捕获拼出微秒级延迟。
5. 仅改变 CCR1，检查“周期边界—标记”的对应假设是否仍合理；若你误配到 PWM 下降沿，它会随宽度改变而移动，这是可证伪反例。参数变更和标记开关分别采集，不同时改变多个变量。
6. 对标记抖动，先检查 Fs/阈值/通道偏斜与样本量化，再核对中断路径和其他活动。软件标记本身的扰动必须写入结论。无独立证据，不给某条 C 指令或中断入口标注精确时刻。
7. 正常停止后再获取一段确认记录，不把界面旧缓存当实时信号；记录停止调用结果和故障状态。外部电路的安全电平另按板级设计确认。

### 12.5 一份可审计记录应长什么样

下表是本次真实的状态边界，不是已经完成的实机报告；未执行栏不能用合成结果填充：

| 字段 | 本次可以填写的内容 | 实机后所需证据 |
|---|---|---|
| 课程/器件参考 | L038；STM32F407VG，VGT6/LQFP100 文档算例 | 真实板型号/版本、完整料号、硅修订与板图 |
| 固件/工具 | 参考源代码在 §9.2；目标工程未编译 | CubeMX/固件基包+补丁/编译器、完整命令、构建日志、ELF/固件 hash |
| 时钟与参数 | HSI 名义 16 MHz，三组 /1，PSC=15，ARR=999，CCR1=500 | 生成工程与寄存器快照、实际时钟条件/容差 |
| 仪器与连接 | 未指定、未连接 | 型号、软件/固件版本、输入规格、校准、真实测试点/地参考/探头 |
| 采集设置 | 上述两组请求方案，未应用 | 实际 Fs/N/通道/阈值/触发/前后窗口与连续性 |
| 主机验证 | 60 项检查，模型日志已保存 | 这不是硬件证据，必须与目标日志分栏 |
| 理论预测 | 名义周期 1 ms，高电平 500 µs | 预测适用条件与误差预算 |
| 实测结果 | **未执行** | 原始采集文件、导出时间戳、截图、实测区间与不确定度 |
| 未决项 | 包源码兼容、板图/引脚/供电、勘误匹配、仪器能力 | 逐项证据或明确保留边界，不用“看着正常”关闭问题 |
| 硬件结论 | `hardware_verified=false` | 本课不得仅因补交主机日志改为 true |

## 13. 自检题

先独立回答，再对照下面的判据；自动生成答案不计为掌握。

1. `Ts=10 µs`，真实 2 µs 脉冲为何可能读作 0 或 10 µs？两者分别说明什么？
2. 观察到两边沿索引相隔 5 格，`Ts=2 µs`，本课理想差值包络是什么？需要哪些假设？
3. 记录首样本就是高电平，为何不能把首样本直接当成上升沿？
4. 触发前事件未出现在截图中，除了“没有发生”，还有哪些可能？
5. 若给两通道同时加 500 µs，读得的相对间隔应怎样？若两图来自独立触发，又少了什么证据？
6. 本例硬件输出、UIF、ISR 回调、GPIO 标记四者为什么不能写成同一个时刻？
7. 为什么 default `0xB0` 是参考互锁，而不是分析仪发现目标有故障？
8. 主机通过 60 项检查，是否允许把 `hardware_verified` 改为 true？还缺哪些独立证据？

**判断要点：**1 是相位与量化，0 表示未观察到而非不存在；2 为 `[8,12] µs`，要有有效样本、边沿夹逼和正确配对，无未识别的额外跳变；3 缺前一个低样本；4 包括采样漏检、触发条件/前后窗口、记录深度、接线/阈值；5 共移不改变间隔，独立采集缺同步/共享参照；6 中断等待、HAL 路径、总线写入和采样链均在其间；7 是人为板级审核开关，不检测实际电路；8 不能，尚缺目标构建、真实板/固件身份、授权下载与原始观测等记录。

## 14. 面试题

**问：为什么定时器寄存器看起来对，逻辑分析仪仍没有输出？**

答：先按链分层：RCC/计数与比较、CH1 使能、GPIO 复用、真实板网、探头/地参考/阈值、触发和窗口。内部正常不充分证明引脚已驱动；采集无记录也不充分证明引脚没有边沿。说明每一层用什么证据排除，而不是只回答“检查初始化”。

**问：逻辑分析仪测到 PWM 边沿到 ISR 标记 3 µs，能说 IRQ 延迟就是 3 µs 吗？**

答：不能。这是假设性的**外部边沿间隔**读数，包含路径和量化/阈值/偏斜。需核对标记代码、共享采集设置和误差预算，还要区分中断入口与回调写 GPIO。若间隔包络包含零，先后也不能无条件肯定。这里的 3 µs 是题目假设，不是本课测量。

**问：提高采样率后问题消失，说明程序修好了吗？**

答：没有。可能是测量可见性、触发或窗口变化，固件根本没改。保留两组原始记录与设置，给出能解释差异的采样反例；再用受控变更检验其他归因。

**问：用 GPIO 翻转测执行时间有什么局限？**

答：翻转动作和调用路径本身有成本，外部边沿不是源代码语句起止的无损时间戳；还受输出与采集链影响。可用于定义清楚的外部阶段标记，但要说明插桩范围、扰动、编译版本和误差，不能自称精确指令计时。

**问：只有一张协议解码截图，足以证明发送端违反时序吗？**

答：不足。需要固件和采集配置、原始边沿、解码参数、阈值/时基与错误位置对应关系。派生标签不能取代输入证据，缺失样本或错误配置也可能造成解析异常。

## 15. 延伸思考

- 若两路都在同一个采样点变化，你能证明“同时”吗？先写各边沿区间，再考虑通道偏斜与阈值；没有足够分辨率时应写“在当前边界内不可区分”。
- 给同一路加了短脉冲后，平均频率可能仍然接近预期。为什么只看频率数字会漏掉问题？用 §9.1 合成事件构造反例，不在真实板上随意产生电气毛刺。
- 两次捕获各自以触发为零，能否比较绝对延迟漂移？需要补充什么时钟关联、同次参考通道或设备同步证据？
- 假如 DMA 完成回调里多了一段打印，外部标记晚了，能否说 ADC 采样晚了？沿 L031 已授链重新指出被观察到的位置，不把软件通知倒推成采样孔径。
- 如果必须观察模拟上升沿、过冲或精确电压，本课数字模型缺了什么？应换用适当仪器并另行建立安全、带宽、探头和校准边界，不扩写成这里的第三个新核心概念。

## 16. 本节总结

1. 数字样本给的是离散电平；短事件会漏检，边沿间隔应带包络。Fs 高于重复频率，并不自动保证窄脉冲可靠可见。
2. 触发决定参照与保留窗口。共享时间平移不改变间隔，但观察到先后不等于证明内部因果；软件标记不是硬件事件的无损替身。
3. 对 F407，必须贯通 HSI→总线→TIM2→PSC/ARR/CCR→通道→GPIO→探头→采样链。HAL、寄存器配置、外部接线与采集证据互相补充，不能互相代替。

当前只有主机逻辑证据。STM32 参考实现仍待目标工程编译，硬件实验未执行；课程生成和审查均不提高掌握度；仅在 Reviewer 审查通过后，才将课程状态设为 `reviewed` 并按路线推进课程进度，这不代表已掌握或已通过硬件验证。

## 17. 下一步

按现有路线进入 `host-test`：把本课模型、触发窗口和可证伪反例整理成可重复的主机验证流程；再在 `unit-test` 聚焦边沿配对、无效输入和判读规则的边界。这只是后续落点说明，本次不创建这些课程。

在用户给出明确硬件后，回到 L029/L030/L031/L032 的参考主题作综合实机复验：Timer TRGO→ADC→DMA→软件 GPIO 标记→同次逻辑采集，分别保存硬件事件、缓冲交接和通知的证据。没有板和仪器时不冒充已完成这条链。

**F4/F7/H5/H7 迁移核对表**：除了第一行，其余为待选具体器件后的审核项，不提供“全系列通用”的寄存器或延迟数字。

| 目标 | 保留的机制 | 必须重查与迁移理由 |
|---|---|---|
| F4 / 本课 F407 | 采样区间、触发窗口、外部标记的证据边界 | 本课 RCC/TIM2/AF 的确定实现仍需匹配真实封装、板图、硅修订、HAL 包和仪器；不能因同属 F4 就忽略料号 |
| F7 / 待选具体器件 | 同次采集与反例方法 | 查目标 RM/DS/勘误的 TIM 内核时钟、输出 AF、GPIO 电气、IRQ 与总线；若使用 Cortex-M7，缓存/存储系统会成为软件标记路径的审核因素，不能从 F407 延迟推导。处理器层入口见 [S7]，不是具体外设映射证据 |
| H5 / 待选具体器件 | 数字判读与预测/观测分离 | 查目标时钟源/域、引脚 AF、调试与资源安全归属、软件执行上下文；[S8] 的 Cortex-M33 安全模型只提示审核方向，不能证明某颗 H5 已启用某策略，也不能复制 F4 的请求/寄存器 |
| H7 / 待选具体器件 | 共享参照、标记不等于内部事件 | 查该器件时钟/总线域、TIM 内核选择、GPIO、内核与存储配置；若选多核器件，另记标记由哪个核执行及资源归属，不能把“部分 H7 有多核”写成全系列结论。[S7] 不替代目标 RM/DS |

每次迁移都重新记录软件包、初始化、请求/回调映射、电气与采集设置；若后续使用 DMA 缓冲，还要依据具体目标重查可访问存储区及缓存/安全约束。本课不预先实现这些跨阶段机制。

## 18. 参考资料

以下均为 `config/source-policy.toml` 允许域内第一方资料。正文 `[Sx]` 与 `lesson.json.sources` 对应，访问/阅读日期为 **2026-10-20**。S1/S2/S3/S7/S8 阅读了仓库既有官方文档缓存并核对版本封面；S4 本次读取版本网页，S5/S6 本次下载官方 PDF。访问日期不表示所有文件都在今天重新下载，也不代表已经审计某个安装的固件包。

- **[S1] ST-RM0090**，*STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 reference manual*，Rev 22，2026-05。重点：§3.5 Flash 时序；§7.2/7.3 F405/F407 时钟、门控与复位；§8.4 GPIO；§18.3.1–4、9、14–16 与 §18.4 TIM2–TIM5。高级控制定时器只在 §17 查适用能力。https://www.st.com.cn/resource/en/reference_manual/dm00031020-stm32f405415-stm32f407417-stm32f427437-and-stm32f429439-advanced-armbased-32bit-mcus-stmicroelectronics.pdf
- **[S2] ST-DS8626**，*STM32F405xx / STM32F407xx datasheet*，Rev 12，2026-03。重点：§4 引脚与表 9 AF 映射（p.64 起）、§7.4 LQFP100；§6.1–6.3 电气范围；§6.3.9 内部时钟源特性；§8 订货码。只约束芯片，不定义仪器输入规格。https://www.st.com.cn/resource/en/datasheet/stm32f407vg.pdf
- **[S3] ST-UM1725**，*Description of STM32F4 HAL and low-layer drivers*，Rev 8，2023-03。重点：§6 HAL 通用初始化；GPIO、RCC 对应章；§68 TIM：初始化字段 p.1059–1060、使用方法 p.1065–1066、初始化/Start/Stop p.1075–1077、IRQ p.1088、回调 p.1097–1100、宏 p.1116–1119；§7 ADC 通知回调用于能力地图。API 文档不是目标包编译证据。https://www.st.com.cn/resource/en/user_manual/dm00105879-description-of-stm32f4-hal-and-ll-drivers-stmicroelectronics.pdf
- **[S4] ST-CUBEF4-VERSIONS**，*STM32CubeF4 software versions*，2026-10-20 网页快照：基包 STM32CubeF4 1.28.0、Patch-CubeF4 1.28.3 分列；本课未安装/编译该组合。https://www.st.com/en/embedded-software/stm32cubef4.sw-versions.html
- **[S5] ST-UM1718**，*STM32CubeMX for STM32 configuration and initialization C code generation*，Rev 51，2026-05。重点：§4.2 新工程；§4.5 引脚/外设、§4.5.14 NVIC；§4.10 时钟；§4.11 工程生成；§6 C 代码生成。用于替代本次连接超时的 6.18.1 在线章节，不宣称已运行该版本工具。https://www.st.com.cn/resource/en/user_manual/dm00104712-stm32cubemx-for-stm32-configuration-and-initialization-c-code-generation-stmicroelectronics.pdf
- **[S6] ST-AN4776**，*How to use general-purpose timer peripheral on STM32 MCUs*，Rev 4，2026-02，修订历史日期 2026-02-23。重点：§1 的时基、预装载及通用工作模式。只作机制辅助，不把通用应用笔记示例原样认定为 F407 寄存器实现。https://www.st.com.cn/resource/en/application_note/an4776-how-to-use-generalpurpose-timer-peripheral-on-stm32-mcus-stmicroelectronics.pdf
- **[S7] ST-PM0253**，*STM32F7 series and STM32H7 series Cortex-M7 processor programming manual*，Rev 6，2026-05。重点：存储系统与 §4.8 缓存维护作为迁移核对入口，不提供具体 F7/H7 时钟/引脚或板上标记延迟结论。https://www.st.com.cn/resource/en/programming_manual/dm00237416-stm32f7-series-and-stm32h7-series-cortexm7-processor-programming-manual-stmicroelectronics.pdf
- **[S8] ST-PM0264**，*STM32 Cortex-M33 MCUs and MPUs programming manual*，Rev 8，2026-03。重点：§1.3.2 安全扩展、§2.3.4 安全存储划分，作为 H5 迁移的上下文审核入口，不替代具体器件 RM/DS/调试安全配置。https://www.st.com.cn/resource/en/programming_manual/pm0264-stm32-cortexm33-mcus-programming-manual-stmicroelectronics.pdf

采样包络、时间平移和 Host Fake 均为本课显式假设下的原创推导/代码，不是从 ST 文档引用的分析仪性能。实际仪器输入/触发/存储/校准规格尚未确定；这些边界不能由 STM32 数据手册、合成数据或本课代码代填。
