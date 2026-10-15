+++
title = "高级控制定时器：互补 PWM 安全输出链"
date = "2026-10-14T23:58:28+08:00"
lastmod = "2026-10-14T23:58:28+08:00"
summary = "建立高级控制定时器的互补 PWM 安全输出链，用 C11 Host Fake 验证非重叠、故障锁存和显式恢复，并以 STM32F407xx 的 TIM1 核对时钟、CubeMX、HAL、LL、寄存器、刹车 IRQ 和硬件验证边界。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 30
tags = ["advanced-control-timer", "complementary-pwm", "dead-time", "break-input", "tim1", "stm32f407", "cubemx", "hal", "ll", "registers", "host-fake", "c11"]
source_ids = ["st-rm0090-advanced-control-timer", "st-ds8626-advanced-control-timer", "st-um1725-advanced-control-timer", "st-stm32cubef4-1.28.3-advanced-control-timer", "st-stm32cubef7-1.17.3-advanced-control-timer", "st-stm32cubeh5-1.5.0-advanced-control-timer", "st-stm32cubeh7-1.12.1-advanced-control-timer"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L030"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 30 课：高级控制定时器的互补 PWM 安全输出链

普通 PWM（pulse-width modulation，脉宽调制）只能回答“某一路在什么时候翻转”，不能单独证明可能连接到半桥上下管的两路信号不会重叠，也不能定义故障到来时如何越过 CPU 立即关闭输出。功率控制真正需要审计的是一整条链：比较事件如何变成主/互补输出，换相处如何插入死区，哪一道总门控允许信号到达引脚，刹车事件又如何让输出进入已定义的安全状态。

本课只推进一个新核心概念：**高级控制定时器的互补 PWM 安全输出链**。互补 PWM、死区（dead time）、刹车输入（break input，BKIN）、主输出使能（main output enable，MOE）和空闲状态只是这条链的节点，不是额外的核心概念。

课程采用两条严格分开的轨道：Host Fake（主机替身）验证状态、所有权、非重叠不变量和故障锁存；STM32 轨道落实到 `STM32F407xx` 的 `TIM1_CH1/TIM1_CH1N` 参考配置。当前没有完整订货料号、开发板原理图、合法复用引脚、BKIN 外部网络、栅极驱动器或功率级，也没有目标构建、烧录和测量记录。因此所有 STM32 代码均是“参考实现，待目标工程编译和上板验证”，不得连接未知功率级，`hardware_verified=false`。

## 1. 本节目标

核心目标与本次 `plan.json` 逐字一致：

> 建立高级控制定时器的互补 PWM 安全输出链，能够将定时器比较事件、主/互补输出、死区、主输出使能与刹车关闭路径串成可审计的时序和故障边界，并以 STM32F407xx 的 TIM1 参考实现逐项核对。

完成本课后，你应能：

1. 画出 `OC1REF -> 死区生成 -> 极性/通道许可 -> 输出使能电路 -> CH1/CH1N` 的正常输出链，并说明 `MOE` 如何控制输出使能电路；
2. 说明 BKIN 有效时，硬件关闭链为何不依赖周期性中断或回调；
3. 区分“比较逻辑互补”“引脚电平互补”和“功率管绝不同时导通”三种不同强度的结论；
4. 从 TIM1 内核时钟推导 PWM 周期、`tDTS` 和 `DTG` 编码，并区分计算值与测量值；
5. 解释配置对象在哪里定义、谁持有、谁注入事件、调用和信号如何流动；
6. 用 Host Fake 验证换相时先全关、等待死区、再开另一侧，以及故障锁存和显式恢复；
7. 把 CubeMX/HAL 配置逐项对应到 LL（low-layer，低层驱动）与 `CR1/CCMR1/CCER/BDTR/SR/DIER`；
8. 说明 F4 参考实现迁移到 F7、H5、H7 时必须重新核对的边界。

本课不实现三相调制、FOC（field-oriented control，磁场定向控制）、重复计数驱动的批量更新、DMA burst（直接存储器访问突发更新）或 `TIM -> ADC -> DMA` 流水线。

## 2. 它解决什么问题

### 2.1 两路“逻辑取反”仍不够安全

如果软件用两个普通 PWM 通道分别产生高侧和低侧信号，即使占空比看起来互补，更新先后、IRQ 延迟、寄存器生效点或错误路径都可能造成短暂重叠。半桥上下器件同时导通会形成直通电流。高级控制定时器让同一个比较参考 `OC1REF` 同时驱动主输出和互补输出，并在硬件输出级插入非重叠时间。[S1]

这仍不等于整个功率系统已经安全。定时器无法替代以下工作：

- 按 MOSFET/IGBT、驱动器传播延迟和开关速度计算真实死区；
- 核对驱动器输入极性、关断电平、欠压锁定和硬件互锁；
- 设计 BKIN 的电气来源、上拉/下拉、隔离、滤波和故障覆盖；
- 在示波器上测量两路关断到导通的实际间隔；
- 证明复位、调试暂停、断电和线缆故障时的板级状态。

因此本课只证明“如何正确使用和审计 TIM1 的安全输出机制”，不声称给出了某个未知功率级的安全认证。

### 2.2 正常路径和故障路径必须分开

正常换相路径是：

```text
CNT 与 CCR1 比较
  -> OC1REF
  -> 死区生成器
  -> CC1P/CC1NP 极性与 CC1E/CC1NE 通道许可
  -> 受 BDTR.MOE、OSSI/OSSR 等控制的输出使能电路
  -> TIM1_CH1 / TIM1_CH1N 引脚复用
```

这是 RM0090 Figure 114 的硬件方框顺序。`CC1E/CC1NE` 不是与死区生成器毫无关系的末端开关：两者同时置位并配合 `MOE`，才形成主/互补输出和死区插入的组合。本图表达信号经过各硬件块的顺序，不应被理解成这些控制位彼此独立。[S1]

故障关闭路径是：

```text
外部故障源
  -> 板级电气网络
  -> 合法 TIM1_BKIN 复用输入
  -> BDTR.BKE/BKP 判定有效
  -> 硬件清除/压制 MOE，输出进入配置的 off/idle 状态
  -> SR.BIF 记录事件
  -> 可选 DIER.BIE -> NVIC -> HAL_TIM_IRQHandler
  -> HAL_TIMEx_BreakCallback 只做诊断与恢复决策
```

关键区别是：**回调观察已经发生的刹车事件，不负责产生第一时间的关闭动作**。即使 CPU 正在处理别的中断，硬件刹车链也不应等待应用回调。[S1][S4]

### 2.3 “输出关闭”不一定等于“引脚为低”

`MOE=0` 后的输出状态还受 `OSSR`、`OSSI`、`OIS1/OIS1N`、通道使能、极性、GPIO 复用和外部驱动器输入网络影响。不能看到“MOE 被清除”就口头推导“两个功率管必定关断”。必须把定时器的 off/idle 配置、引脚电气状态和驱动器真值表接起来测量。[S1][S2]

## 3. 必要前置知识

本课只使用学习状态中已经完成的内容：

- `timer`：`PSC`（prescaler，预分频器）、`ARR`（auto-reload register，自动重装载寄存器）、`CCR`（capture/compare register，捕获/比较寄存器）、PWM 模式和更新事件；
- `interrupt-priority`：外设标志、外设中断使能、NVIC（nested vectored interrupt controller，嵌套向量中断控制器）和 ISR（interrupt service routine，中断服务程序）是不同层；
- `clock-tree`：时钟源、PLL（phase-locked loop，锁相环）、AHB/APB 预分频、门控与复位；
- `hal-ll-register-crosswalk`：HAL 返回值、寄存器读回、硬件事件和测量结果属于不同证据层；
- `timer-trigger-routing`：沿事件链逐跳定位，而不是看到源端运行就假定接收端已经动作。

这里不要求 RTOS、驱动架构、DMA 或缓存知识。

## 4. 核心原理

### 4.1 五段安全输出链

| 段 | 解决的问题 | 对象在哪里定义 | 谁持有配置 | 谁注入事件 | 如何流到结果 |
| --- | --- | --- | --- | --- | --- |
| 比较事件 | 何时请求切换 | Host Fake 的目标侧；TIM1 `CNT/CCR1/CCMR1.OC1M` | 测试 fixture；STM32 BSP 的 `htim1` | 测试调用；TIM1 计数器 | 比较关系形成 `OC1REF` |
| 死区 | 换相时避免两侧许可重叠 | Fake 的 `dead_ticks`；`BDTR.DTG` | 初始化配置，运行期通常不随意改 | `OC1REF` 的输出边沿请求 | 生成带非重叠间隔的 `OC1_DT/OC1N_DT` |
| 输出选择 | 哪一对输出响应、极性如何 | Fake 的 main/complement 请求；`CCER.CC1E/CC1NE/CC1P/CC1NP` | 同一安全输出所有者 | dead-time generator 的两路结果 | 选择并定极性；两路使能还决定互补死区组合是否成立 |
| 主输出门控 | 是否允许整组输出离开定时器 | Fake 的 `moe`；`BDTR.MOE` | 安全输出所有者；硬件刹车也可改变 | 启动/恢复或 BKIN | `MOE=0` 截断整组输出许可 |
| 刹车/安全状态 | 故障时走独立快速关闭路径 | Fake 的故障锁存；`BDTR.BKE/BKP/AOE/OSSI/OSSR`、`CR2.OISx` | BSP 配置，板级电路注入 BKIN | 测试故障或外部故障电平 | 输出关闭；`BIF` 可选通知 CPU；策略决定是否恢复 |

五段必须由同一个生命周期所有者组装。若模块 A 启动 CH1、模块 B 启动 CH1N、模块 C 随时清 `MOE`，就无法回答谁有权关闭或恢复整组输出。

### 4.2 一个比较参考，两条输出支路

PWM mode 1 中，边沿向上计数时可直观理解为 `CNT < CCR1` 时 `OC1REF` 有效，越过比较点后无效。主输出和互补输出来自同一个参考，但不是简单把两个 GPIO 做软件取反：`OC1REF` 先进入 dead-time generator，形成 `OC1_DT/OC1N_DT`，再由 `CC1E/CC1NE` 选择并由 `CC1P/CC1NP` 决定有效极性，最后经过受 `MOE/OSSI/OSSR` 等控制的输出使能电路。[S1]

这带来三个重要边界：

1. `CCR1` 决定参考波形的占空关系，不直接给出两只功率器件的导通时间；死区会缩短实际有效区间。
2. `CC1P/CC1NP` 与外部驱动器极性共同决定“引脚高”是否表示器件导通。
3. CH1 和 CH1N 的合法引脚取决于完整 F407 订货料号和封装；本课不虚构任何引脚。[S2]

### 4.3 死区是边沿延迟，不是第二个占空比

换相可按以下顺序理解：

```text
当前主侧许可
  -> 比较参考要求切到互补侧
  -> 立即撤销主侧许可
  -> 两侧都不许可，持续 dead time
  -> 允许互补侧
```

反向换相同理。死区生成器只处理输出参考到主/互补输出的边沿关系，不会知道外部晶体管是否真的关闭。若驱动器传播延迟、米勒平台或负载条件超出假设，`DTG` 正确也可能不安全。

F407 的 `DTG[7:0]` 是分段编码，不是全范围线性纳秒数。以 `tDTS` 为单位，RM0090 给出的四段关系可写成：[S1]

```text
0xx: DT = DTG[7:0] * tDTS
10x: DT = (64 + DTG[5:0]) * 2 * tDTS
110: DT = (32 + DTG[4:0]) * 8 * tDTS
111: DT = (32 + DTG[4:0]) * 16 * tDTS
```

STM32CubeF4 v1.28.3 的 LL 头文件提供 `__LL_TIM_CALC_DEADTIME(timer_clock_hz, clock_division, deadtime_ns)` 计算编码；输入超出宏覆盖范围时会返回 `0`，所以调用者必须同时做范围检查，不能把 `0` 误当作“请求成功”。[S4]

### 4.4 MOE 是总闸门，不是普通通道使能

`CC1E` 与 `CC1NE` 分别许可主通道和互补通道，`MOE` 位于更靠后的总门控位置。满足 `CEN=1`、PWM 配置正确和通道使能，并不代表引脚已有波形；高级定时器还要求 `MOE=1`。[S1]

本机 STM32CubeF4 v1.28.3 源码显示：[S4]

- `HAL_TIM_PWM_Start()` 使能主通道、置 `MOE` 并启动计数器；
- `HAL_TIMEx_PWMN_Start()` 使能互补通道、置 `MOE` 并启动计数器；
- `HAL_TIM_PWM_Stop()` 会清 `MOE`，再按通道状态尝试停计数器；
- `HAL_TIMEx_PWMN_Stop()` 同样会清 `MOE`。

所以这两个输出不能由两个互不协调的模块独立启停。任一 `Stop` 都影响整组主输出。参考 BSP 必须把 `htim1`、CH1、CH1N 和恢复策略放在同一所有权边界内。

### 4.5 BKIN 关闭与 CPU 诊断是两条并行结果

当 break 功能已启用且 BKIN 达到配置的有效电平时，硬件对输出门控采取动作并置 `SR.BIF`。若还设置 `DIER.BIE` 和 NVIC，CPU 才会进入 TIM1 break IRQ。F407 的向量名为 `TIM1_BRK_TIM9_IRQHandler`，它与 TIM9 共享向量；若系统使用 TIM9，ISR 必须分别判断来源，不能无条件只处理 TIM1。[S1][S4]

在 STM32CubeF4 v1.28.3 中，`HAL_TIM_IRQHandler(&htim1)` 看到 `BIF` 且 `BIE` 有效时先清 break flag，再调用 `HAL_TIMEx_BreakCallback()`。[S4] 因此：

- 回调适合锁存软件故障、计数、记录 `BDTR` 和禁止自动重启；
- 回调中的 `SR` 快照通常已看不到刚被 HAL 清除的 `BIF`，要以“回调发生”作为这次软件证据；
- `HAL_TIM_ErrorCallback()` 不会仅因 BKIN 事件自动调用；它不能替代 break callback；
- 未启用 update/compare 中断时，`HAL_TIM_PeriodElapsedCallback()` 和 `HAL_TIM_PWM_PulseFinishedCallback()` 不会因为 PWM 正常运行而周期发生。

### 4.6 显式恢复优先于自动恢复

`BDTR.AOE` 允许在 break 不再有效后，于后续 update event 自动重新置位 `MOE`。[S1][S4] 这能缩短恢复路径，但也可能让暂态故障消失后未经应用确认就重新输出。本课最小实现使用：

```text
AutomaticOutput = DISABLE
break -> 硬件关输出 -> 软件锁存故障
-> 上层确认故障源已解除
-> 清诊断/标志 -> 显式重新置 MOE
```

是否采用 AOE 必须由完整系统安全需求决定，不因“HAL 有这个字段”就开启。

## 5. 关键术语与直观模型

| 术语 | 直观模型 | 本课中的证据边界 |
| --- | --- | --- |
| advanced-control timer，高级控制定时器 | 在普通计数/比较之后增加互补、死区、刹车和总门控 | 本课只落实 TIM1 单通道对 |
| complementary PWM，互补 PWM | 同一参考波形派生的两条输出支路 | 不等于外部器件电流互补 |
| dead time，死区 | 换相时“两边先都关一会儿” | 编码计算需由波形测量验证 |
| BKIN，刹车输入 | 外部故障进入定时器的硬件入口 | 引脚和外部网络待原理图确认 |
| MOE，主输出使能 | 整组高级输出的总闸门 | 清除 MOE 不自动证明功率器件关断 |
| off/idle state，关闭/空闲状态 | 总门控关闭或定时器空闲时输出级采用的状态 | 由 OSSR/OSSI/OIS/极性/GPIO/外部电路共同决定 |
| preload/shadow，预装载/影子 | 新 ARR/CCR 先缓存，在受控更新点生效 | 本课只用于避免周期中途撕裂，不展开更新策略 |
| lock，锁定 | 写入后限制关键配置再修改 | 开启前必须完成配置与恢复审计，复位前可能不可改 |

最小心智模型只有一句话：**正常边沿先经过死区生成，再经过极性/通道许可和受 MOE 控制的输出使能电路；故障事件可以越过 CPU 直接夺走 MOE，软件只负责配置、观察和受控恢复。**

## 6. 从输入到结果的完整流程

### 6.1 初始化阶段

```text
固定完整 MCU/封装和原理图
  -> 证明 CH1、CH1N、BKIN 的合法复用与外部极性
  -> 先让外部功率级保持禁用
  -> 配置系统时钟与 APB2
  -> 独占 TIM1，门控时钟并执行一次受控复位
  -> GPIO 先处于板级定义的安全状态，再切到 AF
  -> 配置 PSC/ARR/RCR/CKD 与 PWM1/CCR1/极性/idle state
  -> 配置 DTG、BKE/BKP、OSSI/OSSR、AOE、LOCK
  -> 清 BIF，按需开启 BIE/NVIC
  -> 启动 CH1 与 CH1N
  -> 读回关键寄存器
  -> 只有板级安全检查通过后，才由板级代码决定是否使能外部驱动器
```

`LOCK` 要最后决定。RM0090 和 LL 注释指出某些 lock level 写入后，在下次复位前会冻结相关字段。[S1][S4] 教学阶段先用 `LOCKLEVEL_OFF` 完成核对；产品阶段再根据威胁模型决定锁定等级。

### 6.2 稳态 PWM 阶段

CPU 不需要每个周期进入 IRQ。TIM1 时钟推进 `CNT`，比较单元产生 `OC1REF`，dead-time generator 先生成两路非重叠结果，输出选择级再应用通道许可与极性，受 `MOE/OSSI/OSSR` 控制的输出使能电路决定它们是否到达 CH1/CH1N。若启用预装载，新的 `CCR1` 在更新点进入活动寄存器，避免周期中途改变比较边界。[S1]

### 6.3 刹车阶段

```text
BKIN 有效
  -> 硬件安全链关闭输出许可并置 BIF
  -> 功率级结果取决于 off/idle、电气网络和驱动器
  -> 可选 break IRQ 到达 CPU
  -> HAL 清 BIF 后调用 HAL_TIMEx_BreakCallback
  -> callback 只保存首个故障、计数和寄存器快照
  -> 应用禁止自动恢复，等待板级故障源确认
```

不要在 callback 内执行长日志、延时、重新初始化整个时钟树或盲目置 `MOE`。ISR 只保存最小证据并把恢复留给线程/主循环。

### 6.4 停止与恢复阶段

受控停止先清 `MOE`，再关闭 CH1N、CH1 和计数器，最后才考虑 GPIO 或时钟门控。恢复前至少检查：BKIN 已处于非有效电平、故障原因已处理、关键配置读回未变化、输出许可仍由唯一所有者持有。然后清残留标志并显式置 `MOE`；读回失败则保持锁存。

## 7. 嵌入式系统中的对应位置

### 7.1 外设能力地图

| 层级 | 能力与工作原理 | 触发/数据/中断链 | 本课与后续落点 |
| --- | --- | --- | --- |
| 基础 | 计数、PSC/ARR、PWM、CCR 占空比 | timer clock -> CNT -> compare -> OCREF | 已学，只作为输入 |
| 进阶 | 互补输出、中心对齐、预装载、重复计数 | OCREF -> CHx/CHxN；update 装载影子值；RCR 控制更新节拍 | 深入互补；中心对齐/预装载说明边界；重复计数另课 |
| 高级 | 死区、BKIN、OSSI/OSSR/OIS、AOE、LOCK | edge request -> dead-time -> MOE；BKIN -> break logic -> BIF/可选 IRQ | 深入死区、刹车和显式恢复；锁定策略后续做故障审计 |
| 跨外设联动 | TRGO 触发 ADC；compare/update 产生 DMA request；多定时器同步 | TIM event -> trigger mux -> ADC -> DMA -> HT/TC IRQ，或 master TRGO -> slave ITR | `adc-timer-dma-pipeline`；DMA burst/三相同步专题 |
| 系列差异 | 定时器实例、时钟选择、break 路由、寄存器扩展、安全域、DMA/缓存不同 | 必须以完整料号重新画 clock/reset/trigger/IRQ 链 | F4 为本课基线；F7/H5/H7 按迁移表重建证据 |

高级能力不是名称列表。以 DMA burst 为例，其原理是 update/compare 事件发出 DMA request，DMA 按定时器的 burst 基地址和长度把一组新值写入连续目标寄存器，随后在受控更新点生效；链路还要增加 DMA stream/request、缓冲区所有权、HT/TC/error IRQ 和缓存一致性。它解决多通道一致更新，但不参与本课最小 BKIN 关闭链，留到独立专题。

以 `TIM TRGO -> ADC -> DMA` 为例，TIM 事件确定采样时刻，ADC 完成转换后提出 DMA 请求，DMA 把数据写入缓冲区，CPU 只在半满/完成或错误时介入。它会复用本课的计时域，但新增 ADC 转换预算、DMA 映射、缓冲区生命周期，以及 F7/H7 上可能需要核对的缓存属性，落在 `adc-timer-dma-pipeline`。

### 7.2 参考目标与时钟/复位链

参考目标是 `STM32F407xx` 的 `TIM1`，资料边界为 RM0090 Rev 22、DS8626 Rev 12、UM1725 Rev 8 与 STM32CubeF4 v1.28.3。[S1][S2][S3][S4] 这不是某块开发板，也不指定封装和引脚。

本课采用一个可计算但未测量的参考时钟：

```text
HSI = 16 MHz
  -> PLLM = 16, PLLN = 336, PLLP = 2
  -> SYSCLK = 168 MHz
  -> AHB prescaler /1
  -> HCLK = 168 MHz
  -> APB2 prescaler /2
  -> PCLK2 = 84 MHz
  -> F407 规则：APB2 prescaler != 1
  -> TIM1 kernel clock = 2 * PCLK2 = 168 MHz
  -> RCC_APB2ENR.TIM1EN 门控
  -> RCC_APB2RSTR.TIM1RST 受控复位后释放
  -> CR1.CKD = DIV1，tDTS = 1 / 168 MHz ~= 5.952 ns
  -> PSC = 0，ARR = 8399，edge-aligned upcount
  -> PWM = 168 MHz / ((0 + 1) * (8399 + 1)) = 20 kHz
  -> CCR1 = 4200，参考占空关系约 50%
  -> DTG = 84，名义 dead time = 84 * tDTS = 500 ns
```

以上 20 kHz 和 500 ns 都是**推导值**，不是仪器结果。500 ns 只是编码示例，不是某个功率级的推荐值。实际工程若改 APB2 预分频、TIM1 时钟或 `CR1.CKD`，必须重新计算 `tDTS` 与 `DTG`，不能只保持 `DeadTime=84`。

复位和时钟的所有权规则：启动期 BSP 是 TIM1 唯一所有者；它在确认没有其他 TIM1 使用者后使能时钟、短暂断言 `TIM1RST`、释放复位，再调用 HAL 初始化。运行期错误回调不得随意复位 TIM1，因为复位会丢失诊断现场和整个定时器配置。

PWM 公式还受计数模式影响。若改为中心对齐，计数器上下往返，不能继续使用上面的边沿对齐公式；`RCR` 影响 update event 的出现频度和预装载生效节拍，但不会把未知板级死区变成已验证值。[S1]

### 7.3 CubeMX、HAL、LL 与寄存器对照

#### CubeMX/CubeMX2 配置清单

1. 选择实际完整 `STM32F407xx` 订货料号和封装；未确定时停止在配置审计，不猜引脚。
2. Clock Configuration：记录真实 HSI/HSE 来源、PLL、SYSCLK、HCLK、APB2 和 TIM1 内核时钟。使用 HSE 前必须从原理图确认晶振/外部时钟。
3. 启用 `TIM1 -> PWM Generation CH1 CH1N`；确认所选封装同时存在合法 CH1 与 CH1N 复用。
4. 设置 edge-aligned upcount、`Prescaler=0`、`Counter Period=8399`、`Pulse=4200`、`Clock Division=DIV1`、`Repetition Counter=0`，得到本课的推导示例。
5. 设置 OC/OCN polarity 与 idle state；这些值必须匹配外部驱动器真值表。本课代码用 active-high、idle reset 作为参考，不构成板级结论。
6. Break and Dead Time：`Dead Time=84`（仅 500 ns 算例）、Break Enable、由板级电路决定 Break Polarity、`Automatic Output=Disable`、教学阶段 `Lock=Off`。
7. F407 目标不要假定存在可配置 BKIN 数字滤波。本机 F4 v1.28.3 的结构体虽有 `BreakFilter` 字段，但 `HAL_TIMEx_ConfigBreakDeadTime()` 没有把它写入 F407 `BDTR`；必须以目标 RM/包实现为准。[S4]
8. GPIO：先按原理图定义安全初态，再配置实际 CH1/CH1N/BKIN alternate function；速度、pull 和外部上拉/下拉按电气要求核对。
9. NVIC：若需要软件诊断，开启 `TIM1 break/TIM9` 共享向量；本课不启用 update、CC 或 DMA IRQ。
10. 生成后审计 `.ioc` 和代码 diff，确认 CubeMX 没有替换板级极性、时钟或回调策略。

#### HAL 配置对象与字段

`TIM_HandleTypeDef htim1` 由 TIM1 BSP 静态持有，生命周期覆盖初始化、运行、故障和停止。应用只调用 BSP 公开函数，不直接修改 `BDTR`。关键字段如下：[S3][S4]

| 对象/字段 | 作用 | 本课参考值 | 边界 |
| --- | --- | --- | --- |
| `htim1.Instance` | 选择外设实例 | `TIM1` | 固定为 F407 TIM1 |
| `Prescaler/Period` | 计数时钟与周期 | `0/8399` | 依赖真实 timer clock |
| `CounterMode` | 边沿/中心对齐关系 | `UP` | 改模式要重算频率 |
| `ClockDivision` | 形成 `tDTS` 的 CKD | `DIV1` | 影响 dead time 编码 |
| `RepetitionCounter` | update 重复节拍 | `0` | 本课不深入 |
| `OCMode/Pulse` | PWM 参考与比较点 | `PWM1/4200` | 预装载生效点需审计 |
| `OCPolarity/OCNPolarity` | 主/互补引脚有效极性 | `HIGH/HIGH` 示例 | 必须匹配驱动器 |
| `OCIdleState/OCNIdleState` | MOE/idle 相关输出状态 | `RESET/RESET` 示例 | 仍需结合 OSSI/OSSR 和电路 |
| `DeadTime` | 直接写入 DTG 编码 | `84` 示例 | 不是纳秒字段 |
| `BreakState/BreakPolarity` | 允许 BKIN 与有效电平 | enable/板级注入 | 不可猜极性 |
| `AutomaticOutput` | break 解除后自动恢复 | disable | 使用显式确认恢复 |
| `LockLevel` | 配置写保护 | off | 产品锁定前先验证全部配置 |

初始化调用顺序必须是：时钟/复位与 GPIO 安全态 -> `HAL_TIM_PWM_Init` -> `HAL_TIM_PWM_ConfigChannel` -> `HAL_TIMEx_ConfigBreakDeadTime` -> 清 break flag/开启 break IRQ -> 启动主输出和互补输出。`HAL_TIMEx_ConfigBreakDeadTime` 在 v1.28.3 中组装并整体写 `BDTR`，所以必须在置 `MOE` 之前调用；启动后再调用可能清除 `MOE` 或覆盖安全字段。[S4]

#### HAL -> LL -> 寄存器交叉表

| 意图 | HAL/宏 | LL 对照 | F407 关键寄存器/位 | 可观察边界 |
| --- | --- | --- | --- | --- |
| TIM1 门控/复位 | `__HAL_RCC_TIM1_CLK_ENABLE/FORCE_RESET/RELEASE_RESET` | RCC LL 对应 API | `RCC_APB2ENR.TIM1EN`、`RCC_APB2RSTR.TIM1RST` | 门控读回不证明计数 |
| 基础计数 | `HAL_TIM_PWM_Init` | `LL_TIM_Init` | `CR1.CEN/DIR/CMS/CKD/ARPE`、`PSC`、`ARR`、`RCR` | PSC/ARR 读回不证明引脚波形 |
| 生成更新 | HAL init 内部或 `__HAL_TIM_GENERATE_EVENT` | `LL_TIM_GenerateEvent_UPDATE` | `EGR.UG`、`SR.UIF` | UG 可能装载预分频/影子值 |
| PWM1/预装载 | `HAL_TIM_PWM_ConfigChannel` | `LL_TIM_OC_SetMode/EnablePreload` | `CCMR1.OC1M/OC1PE` | `OC1REF` 是内部参考 |
| 比较值 | `Pulse` / `__HAL_TIM_SET_COMPARE` | `LL_TIM_OC_SetCompareCH1` | `CCR1` | 活动值何时生效取决于 preload/update |
| 主/互补许可与极性 | Start APIs / OC config | `LL_TIM_CC_EnableChannel`、polarity API | `CCER.CC1E/CC1NE/CC1P/CC1NP` | 仍受 MOE 总门控 |
| idle state | OC config | LL idle-state API | `CR2.OIS1/OIS1N` | 必须结合 OSSI/OSSR |
| dead time/break | `HAL_TIMEx_ConfigBreakDeadTime` | `LL_TIM_BDTR_Init`、`LL_TIM_OC_SetDeadTime`、`LL_TIM_ConfigBRK` | `BDTR.DTG/LOCK/OSSI/OSSR/BKE/BKP/AOE` | 写入值不等于实测 dead time |
| 总输出门控 | Start/Stop 或 `__HAL_TIM_MOE_ENABLE/DISABLE` | `LL_TIM_EnableAllOutputs/DisableAllOutputs` | `BDTR.MOE` | MOE=0 不证明外部管已关 |
| break 标志/中断 | `TIM_FLAG_BREAK`、`TIM_IT_BREAK` | LL flag/IT API | `SR.BIF`、`DIER.BIE` | BIF 是事件证据；HAL handler 会先清它 |
| 计数器运行 | Start/Stop | `LL_TIM_EnableCounter/DisableCounter` | `CR1.CEN`、`CNT` | CEN/CNT 不证明输出许可 |

F407 的 `SR` 标志清除语义应通过 HAL/LL 提供的 clear API 操作，不使用随意的读改写。`__HAL_TIM_CLEAR_FLAG(&htim1, TIM_FLAG_BREAK)` 在该包中向 `SR` 写入按位取反的 mask；应用应使用官方宏，避免误清其他并发标志。[S4]

#### IRQ 与 DMA 边界

| 路径 | 本课是否需要 | 实际含义 |
| --- | --- | --- |
| TIM1 break IRQ -> `HAL_TIMEx_BreakCallback` | 可选但参考实现开启 | 记录已经发生的 break；不承担第一时间关断 |
| update IRQ -> `HAL_TIM_PeriodElapsedCallback` | 不需要 | PWM 周期硬件运行不依赖 CPU |
| CC IRQ -> `HAL_TIM_PWM_PulseFinishedCallback` | 不需要 | 只有使能相应 CC interrupt 并发生标志才调用 |
| `HAL_TIM_ErrorCallback` | 提供兜底诊断 | break 本身不会自动走这里；主要按实际 HAL 错误来源核对 |
| DMA request/IRQ/callback | 不需要 | DMA burst 留给后续专题 |

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 验证轨道

下面的 C11 单文件模型不模拟 F407 寄存器。它验证四件事：一次只许可一侧、换向先全关、死区结束后才开另一侧、break 后锁存且必须显式确认恢复。对象由测试在栈上持有，没有动态内存。

```c
/* safe_pwm_fake_test.c: Host Fake only; not STM32 hardware evidence. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>

typedef enum {
    SAFE_PWM_SIDE_OFF = 0,
    SAFE_PWM_SIDE_MAIN = 1,
    SAFE_PWM_SIDE_COMPLEMENT = 2
} safe_pwm_side_t;

typedef enum {
    SAFE_PWM_OK = 0,
    SAFE_PWM_ERR_ARGUMENT = 1,
    SAFE_PWM_ERR_NOT_ARMED = 2,
    SAFE_PWM_ERR_FAULT_LATCHED = 3,
    SAFE_PWM_ERR_BREAK_ACTIVE = 4,
    SAFE_PWM_ERR_LOCKED = 5
} safe_pwm_result_t;

typedef enum {
    SAFE_PWM_FAULT_NONE = 0,
    SAFE_PWM_FAULT_BREAK = 1,
    SAFE_PWM_FAULT_INVARIANT = 2
} safe_pwm_fault_t;

typedef struct {
    uint32_t dead_ticks;
} safe_pwm_config_t;

typedef struct {
    safe_pwm_config_t config;
    safe_pwm_side_t pending_side;
    safe_pwm_fault_t first_fault;
    uint32_t dead_ticks_left;
    uint32_t compare_events;
    uint32_t break_events;
    uint8_t configured;
    uint8_t running;
    uint8_t moe;
    uint8_t main_on;
    uint8_t complement_on;
    uint8_t break_active;
    uint8_t locked;
} safe_pwm_t;

static uint8_t safe_pwm_invariant(const safe_pwm_t *self)
{
    return (uint8_t)!((self->main_on != 0U) &&
                      (self->complement_on != 0U));
}

static safe_pwm_result_t safe_pwm_init(safe_pwm_t *self,
                                       const safe_pwm_config_t *config)
{
    if ((self == NULL) || (config == NULL) ||
        (config->dead_ticks == 0U)) {
        return SAFE_PWM_ERR_ARGUMENT;
    }

    *self = (safe_pwm_t){0};
    self->config = *config;
    self->configured = 1U;
    return SAFE_PWM_OK;
}

static safe_pwm_result_t safe_pwm_arm(safe_pwm_t *self)
{
    if ((self == NULL) || (self->configured == 0U)) {
        return SAFE_PWM_ERR_ARGUMENT;
    }
    if (self->locked != 0U) {
        return SAFE_PWM_ERR_LOCKED;
    }
    if (self->first_fault != SAFE_PWM_FAULT_NONE) {
        return SAFE_PWM_ERR_FAULT_LATCHED;
    }
    if (self->break_active != 0U) {
        return SAFE_PWM_ERR_BREAK_ACTIVE;
    }

    self->main_on = 0U;
    self->complement_on = 0U;
    self->pending_side = SAFE_PWM_SIDE_OFF;
    self->dead_ticks_left = 0U;
    self->running = 1U;
    self->moe = 1U;
    return SAFE_PWM_OK;
}

static safe_pwm_result_t safe_pwm_compare_event(safe_pwm_t *self,
                                                safe_pwm_side_t requested)
{
    if ((self == NULL) || (requested > SAFE_PWM_SIDE_COMPLEMENT)) {
        return SAFE_PWM_ERR_ARGUMENT;
    }
    if (self->first_fault != SAFE_PWM_FAULT_NONE) {
        return SAFE_PWM_ERR_FAULT_LATCHED;
    }
    if ((self->running == 0U) || (self->moe == 0U)) {
        return SAFE_PWM_ERR_NOT_ARMED;
    }

    self->compare_events++;
    self->main_on = 0U;
    self->complement_on = 0U;
    self->pending_side = requested;
    self->dead_ticks_left = (requested == SAFE_PWM_SIDE_OFF)
                                ? 0U
                                : self->config.dead_ticks;
    return SAFE_PWM_OK;
}

static void safe_pwm_deadtime_tick(safe_pwm_t *self)
{
    if ((self == NULL) || (self->running == 0U) ||
        (self->moe == 0U) || (self->dead_ticks_left == 0U)) {
        return;
    }

    self->dead_ticks_left--;
    if (self->dead_ticks_left == 0U) {
        self->main_on = (uint8_t)(self->pending_side == SAFE_PWM_SIDE_MAIN);
        self->complement_on =
            (uint8_t)(self->pending_side == SAFE_PWM_SIDE_COMPLEMENT);
    }

    if (safe_pwm_invariant(self) == 0U) {
        self->main_on = 0U;
        self->complement_on = 0U;
        self->moe = 0U;
        if (self->first_fault == SAFE_PWM_FAULT_NONE) {
            self->first_fault = SAFE_PWM_FAULT_INVARIANT;
        }
    }
}

static void safe_pwm_break_event(safe_pwm_t *self)
{
    if (self == NULL) {
        return;
    }
    self->break_active = 1U;
    self->break_events++;
    self->moe = 0U;
    self->main_on = 0U;
    self->complement_on = 0U;
    self->pending_side = SAFE_PWM_SIDE_OFF;
    self->dead_ticks_left = 0U;
    if (self->first_fault == SAFE_PWM_FAULT_NONE) {
        self->first_fault = SAFE_PWM_FAULT_BREAK;
    }
}

static void safe_pwm_set_break_level(safe_pwm_t *self, uint8_t active)
{
    if (self != NULL) {
        self->break_active = (uint8_t)(active != 0U);
    }
}

static safe_pwm_result_t safe_pwm_acknowledge(safe_pwm_t *self)
{
    if (self == NULL) {
        return SAFE_PWM_ERR_ARGUMENT;
    }
    if (self->break_active != 0U) {
        return SAFE_PWM_ERR_BREAK_ACTIVE;
    }
    if (self->locked != 0U) {
        return SAFE_PWM_ERR_LOCKED;
    }

    self->first_fault = SAFE_PWM_FAULT_NONE;
    return safe_pwm_arm(self);
}

int main(void)
{
    safe_pwm_t pwm;
    const safe_pwm_config_t config = {
        .dead_ticks = 2U
    };

    assert(safe_pwm_init(&pwm, &config) == SAFE_PWM_OK);
    assert(safe_pwm_compare_event(&pwm, SAFE_PWM_SIDE_MAIN) ==
           SAFE_PWM_ERR_NOT_ARMED);
    assert(safe_pwm_arm(&pwm) == SAFE_PWM_OK);

    assert(safe_pwm_compare_event(&pwm, SAFE_PWM_SIDE_MAIN) == SAFE_PWM_OK);
    assert((pwm.main_on == 0U) && (pwm.complement_on == 0U));
    safe_pwm_deadtime_tick(&pwm);
    assert((pwm.main_on == 0U) && (pwm.complement_on == 0U));
    safe_pwm_deadtime_tick(&pwm);
    assert((pwm.main_on == 1U) && (pwm.complement_on == 0U));

    assert(safe_pwm_compare_event(&pwm, SAFE_PWM_SIDE_COMPLEMENT) ==
           SAFE_PWM_OK);
    assert((pwm.main_on == 0U) && (pwm.complement_on == 0U));
    safe_pwm_deadtime_tick(&pwm);
    safe_pwm_deadtime_tick(&pwm);
    assert((pwm.main_on == 0U) && (pwm.complement_on == 1U));

    safe_pwm_break_event(&pwm);
    assert((pwm.moe == 0U) && (pwm.main_on == 0U) &&
           (pwm.complement_on == 0U));
    assert(pwm.first_fault == SAFE_PWM_FAULT_BREAK);
    assert(safe_pwm_acknowledge(&pwm) == SAFE_PWM_ERR_BREAK_ACTIVE);

    safe_pwm_set_break_level(&pwm, 0U);
    assert(safe_pwm_acknowledge(&pwm) == SAFE_PWM_OK);
    assert(safe_pwm_invariant(&pwm) != 0U);

    puts("safe_pwm_fake: PASS");
    return 0;
}
```

建议的主机命令是：

```text
cc -std=c11 -Wall -Wextra -Werror -pedantic safe_pwm_fake_test.c -o safe_pwm_fake_test
./safe_pwm_fake_test
```

本次运行没有实际创建该源文件或执行命令，因此不能声称主机编译已通过。通过后也只能证明模型不变量，不能证明 `DTG=84`、BKIN 极性、引脚波形或功率级安全。

故障矩阵至少覆盖：

| 注入 | 预期 |
| --- | --- |
| 未 arm 就注入比较事件 | 返回 `NOT_ARMED`，两侧都关 |
| 主侧切换到互补侧 | 先两侧都关，完整等待 dead ticks |
| dead time 期间再次换向 | 重新从两侧全关开始，不出现重叠 |
| MOE 未置位 | 不允许任何输出状态变为 on |
| break 有效 | 立即两侧关闭，保存首个故障 |
| break 仍有效时确认 | 拒绝恢复 |
| 配置 locked | 拒绝重新 arm/确认 |
| 重复 break | 计数增加，但首个故障原因不被覆盖 |

### 8.2 STM32 参考实现轨道

以下接口把声明、实现、实例化、组装和使用五个动作分开。它不是完整工程文件树，而是目标工程中应放置的代码边界：

1. **声明**：`bsp_safe_pwm.h` 暴露固定宽度参数和错误码；
2. **实现**：`bsp_safe_pwm.c` 实现 TIM1 初始化、启停和恢复；
3. **实例化**：该 `.c` 内静态持有唯一 `htim1` 与诊断对象；
4. **组装**：board 文件提供真实 GPIO/BKIN 极性与故障电平读取；
5. **使用**：App 只调用 BSP，不直接操作 `MOE`。

公开声明：

```c
/* bsp_safe_pwm.h: reference implementation, not compiled in this run. */
#ifndef BSP_SAFE_PWM_H
#define BSP_SAFE_PWM_H

#include <stdint.h>

typedef enum {
    BSP_SAFE_PWM_OK = 0,
    BSP_SAFE_PWM_ERR_ARGUMENT = 1,
    BSP_SAFE_PWM_ERR_HAL_INIT = 2,
    BSP_SAFE_PWM_ERR_HAL_CHANNEL = 3,
    BSP_SAFE_PWM_ERR_HAL_BDTR = 4,
    BSP_SAFE_PWM_ERR_HAL_START_MAIN = 5,
    BSP_SAFE_PWM_ERR_HAL_START_N = 6,
    BSP_SAFE_PWM_ERR_BREAK_ACTIVE = 7,
    BSP_SAFE_PWM_ERR_MOE_REJECTED = 8,
    BSP_SAFE_PWM_ERR_FAULT_LATCHED = 9
} bsp_safe_pwm_result_t;

typedef struct {
    uint32_t timer_clock_hz;
    uint32_t prescaler;
    uint32_t period;
    uint32_t pulse;
    uint32_t dead_time_code;
    uint32_t break_polarity;
} bsp_safe_pwm_config_t;

typedef struct {
    uint32_t break_events;
    uint32_t hal_errors;
    uint32_t first_fault;
    uint32_t bdtr_at_break;
    uint8_t running;
    uint8_t fault_latched;
} bsp_safe_pwm_diag_t;

bsp_safe_pwm_result_t BSP_SafePwm_Init(const bsp_safe_pwm_config_t *config);
bsp_safe_pwm_result_t BSP_SafePwm_Start(void);
void BSP_SafePwm_Stop(void);
bsp_safe_pwm_result_t BSP_SafePwm_RecoverAfterBreak(void);
void BSP_SafePwm_GetDiag(bsp_safe_pwm_diag_t *out);

#endif
```

板级注入点必须由实际原理图实现，不能保留空函数后接功率级：

```c
/* board_tim1.c: the real board must implement these three functions. */
#include <stdint.h>

void Board_TIM1_GpioInitSafe(void);
uint8_t Board_TIM1_BreakIsInactive(void);
void Board_PowerStage_KeepDisabled(void);
```

- `Board_TIM1_GpioInitSafe()`：核对实际 CH1/CH1N/BKIN 复用、pull、speed 和切换到 AF 前的安全电平。
- `Board_TIM1_BreakIsInactive()`：按真实 BKIN 极性读取故障源；不能仅靠缓存变量。
- `Board_PowerStage_KeepDisabled()`：让外部驱动器维持硬件禁用。本课不提供“使能功率级”函数，因为没有板卡和功率级安全条件。

TIM1 实现骨架：

```c
/* bsp_safe_pwm.c: STM32F407xx reference, pending target build/validation. */
#include "bsp_safe_pwm.h"
#include "stm32f4xx_hal.h"

extern void Board_TIM1_GpioInitSafe(void);
extern uint8_t Board_TIM1_BreakIsInactive(void);
extern void Board_PowerStage_KeepDisabled(void);

enum {
    BSP_FAULT_NONE = 0U,
    BSP_FAULT_BREAK = 1U,
    BSP_FAULT_HAL = 2U
};

static TIM_HandleTypeDef g_htim1;
static volatile bsp_safe_pwm_diag_t g_diag;
static uint8_t g_main_started;
static uint8_t g_n_started;

static void bsp_record_first_fault(uint32_t fault)
{
    if (g_diag.first_fault == BSP_FAULT_NONE) {
        g_diag.first_fault = fault;
    }
    g_diag.fault_latched = 1U;
}

static void bsp_record_hal_fault(void)
{
    g_diag.hal_errors++;
    bsp_record_first_fault(BSP_FAULT_HAL);
}

static void bsp_force_outputs_off(void)
{
    __HAL_TIM_MOE_DISABLE(&g_htim1);
    g_diag.running = 0U;
}

bsp_safe_pwm_result_t BSP_SafePwm_Init(const bsp_safe_pwm_config_t *config)
{
    TIM_OC_InitTypeDef oc = {0};
    TIM_BreakDeadTimeConfigTypeDef bdtr = {0};

    if ((config == NULL) || (config->timer_clock_hz == 0U) ||
        (config->period == 0U) || (config->pulse > config->period) ||
        (config->dead_time_code > 0xFFU) ||
        ((config->break_polarity != TIM_BREAKPOLARITY_LOW) &&
         (config->break_polarity != TIM_BREAKPOLARITY_HIGH))) {
        return BSP_SAFE_PWM_ERR_ARGUMENT;
    }

    Board_PowerStage_KeepDisabled();
    HAL_NVIC_DisableIRQ(TIM1_BRK_TIM9_IRQn);
    __HAL_RCC_TIM1_CLK_ENABLE();
    __HAL_RCC_TIM1_FORCE_RESET();
    __HAL_RCC_TIM1_RELEASE_RESET();
    Board_TIM1_GpioInitSafe();

    g_htim1 = (TIM_HandleTypeDef){0};
    g_diag = (bsp_safe_pwm_diag_t){0};
    g_main_started = 0U;
    g_n_started = 0U;
    g_htim1.Instance = TIM1;
    g_htim1.Init.Prescaler = config->prescaler;
    g_htim1.Init.CounterMode = TIM_COUNTERMODE_UP;
    g_htim1.Init.Period = config->period;
    g_htim1.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    g_htim1.Init.RepetitionCounter = 0U;
    g_htim1.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;

    if (HAL_TIM_PWM_Init(&g_htim1) != HAL_OK) {
        bsp_record_hal_fault();
        return BSP_SAFE_PWM_ERR_HAL_INIT;
    }

    oc.OCMode = TIM_OCMODE_PWM1;
    oc.Pulse = config->pulse;
    oc.OCPolarity = TIM_OCPOLARITY_HIGH;
    oc.OCNPolarity = TIM_OCNPOLARITY_HIGH;
    oc.OCFastMode = TIM_OCFAST_DISABLE;
    oc.OCIdleState = TIM_OCIDLESTATE_RESET;
    oc.OCNIdleState = TIM_OCNIDLESTATE_RESET;
    if (HAL_TIM_PWM_ConfigChannel(&g_htim1, &oc, TIM_CHANNEL_1) != HAL_OK) {
        bsp_record_hal_fault();
        return BSP_SAFE_PWM_ERR_HAL_CHANNEL;
    }

    bdtr.OffStateRunMode = TIM_OSSR_DISABLE;
    bdtr.OffStateIDLEMode = TIM_OSSI_DISABLE;
    bdtr.LockLevel = TIM_LOCKLEVEL_OFF;
    bdtr.DeadTime = config->dead_time_code;
    bdtr.BreakState = TIM_BREAK_ENABLE;
    bdtr.BreakPolarity = config->break_polarity;
    bdtr.BreakFilter = 0U; /* F4 v1.28.3 does not apply this field here. */
    bdtr.AutomaticOutput = TIM_AUTOMATICOUTPUT_DISABLE;
    if (HAL_TIMEx_ConfigBreakDeadTime(&g_htim1, &bdtr) != HAL_OK) {
        bsp_record_hal_fault();
        return BSP_SAFE_PWM_ERR_HAL_BDTR;
    }

    __HAL_TIM_MOE_DISABLE(&g_htim1);
    if (Board_TIM1_BreakIsInactive() == 0U) {
        bsp_record_first_fault(BSP_FAULT_BREAK);
        return BSP_SAFE_PWM_ERR_BREAK_ACTIVE;
    }
    __HAL_TIM_CLEAR_FLAG(&g_htim1, TIM_FLAG_BREAK);
    if (__HAL_TIM_GET_FLAG(&g_htim1, TIM_FLAG_BREAK) != RESET) {
        bsp_record_first_fault(BSP_FAULT_BREAK);
        return BSP_SAFE_PWM_ERR_BREAK_ACTIVE;
    }
    __HAL_TIM_ENABLE_IT(&g_htim1, TIM_IT_BREAK);
    HAL_NVIC_SetPriority(TIM1_BRK_TIM9_IRQn, 5U, 0U);
    HAL_NVIC_ClearPendingIRQ(TIM1_BRK_TIM9_IRQn);
    HAL_NVIC_EnableIRQ(TIM1_BRK_TIM9_IRQn);

    return BSP_SAFE_PWM_OK;
}

bsp_safe_pwm_result_t BSP_SafePwm_Start(void)
{
    if (Board_TIM1_BreakIsInactive() == 0U) {
        bsp_record_first_fault(BSP_FAULT_BREAK);
        return BSP_SAFE_PWM_ERR_BREAK_ACTIVE;
    }
    if (g_diag.fault_latched != 0U) {
        return BSP_SAFE_PWM_ERR_FAULT_LATCHED;
    }

    /* HAL start calls are sequential, not an atomic pair-enable operation.
       The external power stage must remain disabled during this step. */
    if (HAL_TIM_PWM_Start(&g_htim1, TIM_CHANNEL_1) != HAL_OK) {
        bsp_force_outputs_off();
        bsp_record_hal_fault();
        return BSP_SAFE_PWM_ERR_HAL_START_MAIN;
    }
    g_main_started = 1U;

    if (HAL_TIMEx_PWMN_Start(&g_htim1, TIM_CHANNEL_1) != HAL_OK) {
        bsp_force_outputs_off();
        (void)HAL_TIM_PWM_Stop(&g_htim1, TIM_CHANNEL_1);
        g_main_started = 0U;
        bsp_record_hal_fault();
        return BSP_SAFE_PWM_ERR_HAL_START_N;
    }
    g_n_started = 1U;
    g_diag.running = 1U;
    return BSP_SAFE_PWM_OK;
}

void BSP_SafePwm_Stop(void)
{
    bsp_force_outputs_off();
    if (g_n_started != 0U) {
        (void)HAL_TIMEx_PWMN_Stop(&g_htim1, TIM_CHANNEL_1);
        g_n_started = 0U;
    }
    if (g_main_started != 0U) {
        (void)HAL_TIM_PWM_Stop(&g_htim1, TIM_CHANNEL_1);
        g_main_started = 0U;
    }
}

bsp_safe_pwm_result_t BSP_SafePwm_RecoverAfterBreak(void)
{
    if (Board_TIM1_BreakIsInactive() == 0U) {
        return BSP_SAFE_PWM_ERR_BREAK_ACTIVE;
    }
    if ((g_main_started == 0U) || (g_n_started == 0U)) {
        return BSP_SAFE_PWM_ERR_MOE_REJECTED;
    }

    __HAL_TIM_MOE_DISABLE(&g_htim1);
    __HAL_TIM_CLEAR_FLAG(&g_htim1, TIM_FLAG_BREAK);
    __HAL_TIM_MOE_ENABLE(&g_htim1);
    __NOP(); /* RM0090: allow MOE write/read synchronization. */
    if ((g_htim1.Instance->BDTR & TIM_BDTR_MOE) == 0U) {
        bsp_record_first_fault(BSP_FAULT_BREAK);
        return BSP_SAFE_PWM_ERR_MOE_REJECTED;
    }

    g_diag.fault_latched = 0U;
    g_diag.first_fault = BSP_FAULT_NONE;
    g_diag.running = 1U;
    return BSP_SAFE_PWM_OK;
}

void BSP_SafePwm_GetDiag(bsp_safe_pwm_diag_t *out)
{
    uint32_t primask;

    if (out == NULL) {
        return;
    }

    primask = __get_PRIMASK();
    __disable_irq();
    out->break_events = g_diag.break_events;
    out->hal_errors = g_diag.hal_errors;
    out->first_fault = g_diag.first_fault;
    out->bdtr_at_break = g_diag.bdtr_at_break;
    out->running = g_diag.running;
    out->fault_latched = g_diag.fault_latched;
    if (primask == 0U) {
        __enable_irq();
    }
}

void HAL_TIMEx_BreakCallback(TIM_HandleTypeDef *htim)
{
    if ((htim != NULL) && (htim->Instance == TIM1)) {
        g_diag.break_events++;
        g_diag.bdtr_at_break = htim->Instance->BDTR;
        bsp_record_first_fault(BSP_FAULT_BREAK);
        g_diag.running = 0U;
    }
}

void HAL_TIM_ErrorCallback(TIM_HandleTypeDef *htim)
{
    if ((htim != NULL) && (htim->Instance == TIM1)) {
        bsp_force_outputs_off();
        bsp_record_hal_fault();
    }
}

void TIM1_BRK_TIM9_IRQHandler(void)
{
    /* This reference assumes TIM9 is disabled. If TIM9 is used, dispatch its
       pending source here as well because the vector is shared. */
    if ((__HAL_TIM_GET_FLAG(&g_htim1, TIM_FLAG_BREAK) != RESET) &&
        (__HAL_TIM_GET_IT_SOURCE(&g_htim1, TIM_IT_BREAK) != RESET)) {
        HAL_TIM_IRQHandler(&g_htim1);
    }
}
```

`timer_clock_hz` 用于上层审计和计算，HAL 不直接消费它。真实工程应在初始化时把 RCC 推导出的 TIM1 时钟与该值比较，或由唯一时钟模块提供，避免配置表写 168 MHz 而实际 clock tree 已改变。恢复函数中的单个 `__NOP()` 只满足 RM0090 对 MOE 异步写入后同步读回的要求；它不是安全延时，也不能证明外部输出已经恢复。[S1]

App 的最小使用：

```c
/* main.c: reference usage; power stage remains disabled. */
#include "bsp_safe_pwm.h"
#include "stm32f4xx_hal.h"

int main(void)
{
    bsp_safe_pwm_diag_t diag;
    const bsp_safe_pwm_config_t pwm = {
        .timer_clock_hz = 168000000U,
        .prescaler = 0U,
        .period = 8399U,
        .pulse = 4200U,
        .dead_time_code = 84U,
        .break_polarity = TIM_BREAKPOLARITY_HIGH /* board must confirm */
    };

    HAL_Init();
    SystemClock_Config(); /* must produce and document the reference clock */

    if (BSP_SafePwm_Init(&pwm) != BSP_SAFE_PWM_OK) {
        Error_Handler();
    }
    if (BSP_SafePwm_Start() != BSP_SAFE_PWM_OK) {
        Error_Handler();
    }

    for (;;) {
        BSP_SafePwm_GetDiag(&diag);
        if (diag.fault_latched != 0U) {
            /* Keep the power stage disabled; inspect and explicitly recover. */
        }
    }
}
```

这里故意没有调用外部功率级使能。把定时器引脚连接到真实驱动器之前，必须提供完整板级实现、驱动器手册、故障输入电路和测量方案。

#### 参考构建、烧录和观察步骤

1. 固定完整 F407 料号、封装、板卡原理图、驱动器和测量工具；核对 CH1/CH1N/BKIN 复用与极性。
2. 在 CubeMX 固定版本和 STM32CubeF4 v1.28.3 下生成工程，把 board 注入点实现放在用户文件或独立 BSP 中。
3. 全量构建并保存工具链版本、命令、完整输出、退出码、警告和产物哈希。当前未执行。
4. 保持功率级断开或硬件禁用，烧录并在启动前读回 RCC、`CR1/PSC/ARR/CCR1/CCMR1/CCER/BDTR`。当前未执行。
5. 自由运行后用示波器分别观察 CH1 与 CH1N，再用两通道和游标测换相死区；不要只观察 callback GPIO。
6. 在安全的低能量测试条件下注入 BKIN，确认波形先关闭，再观察 `BIF`/break callback 计数；回调时间不能当作硬件关闭延迟。
7. 保持 BKIN 有效并尝试恢复，确认 `MOE` 不能稳定保持；解除故障后执行显式确认，再测恢复发生在哪个更新边界。
8. 保存板卡、固件、构建、烧录、寄存器快照、示波器设置和波形原始数据后，才可讨论将 `hardware_verified` 改为 true。

当前证据：未编译、未烧录、未读回、未测量、未连接功率级。

## 9. 最小代码示例

理解 HAL 配置的最小片段是：

```c
TIM_OC_InitTypeDef oc = {0};
TIM_BreakDeadTimeConfigTypeDef bdtr = {0};

oc.OCMode = TIM_OCMODE_PWM1;
oc.Pulse = 4200U;
oc.OCPolarity = TIM_OCPOLARITY_HIGH;
oc.OCNPolarity = TIM_OCNPOLARITY_HIGH;
oc.OCIdleState = TIM_OCIDLESTATE_RESET;
oc.OCNIdleState = TIM_OCNIDLESTATE_RESET;
(void)HAL_TIM_PWM_ConfigChannel(&g_htim1, &oc, TIM_CHANNEL_1);

bdtr.DeadTime = 84U; /* encoded DTG, not 84 ns */
bdtr.BreakState = TIM_BREAK_ENABLE;
bdtr.BreakPolarity = TIM_BREAKPOLARITY_HIGH; /* board-dependent */
bdtr.AutomaticOutput = TIM_AUTOMATICOUTPUT_DISABLE;
(void)HAL_TIMEx_ConfigBreakDeadTime(&g_htim1, &bdtr);

(void)HAL_TIM_PWM_Start(&g_htim1, TIM_CHANNEL_1);
(void)HAL_TIMEx_PWMN_Start(&g_htim1, TIM_CHANNEL_1);
```

它不能脱离第 8.2 节复制：省略了返回值、时钟/复位、GPIO、安全初态、OSSI/OSSR、IRQ、回滚和板级禁用。尤其是 `84` 是编码，不是纳秒；两个 Start 是顺序调用，不是原子成对使能。

## 10. 常见错误

### 10.1 用两个普通 PWM 通道手工取反

两个独立比较单元的更新和错误路径可能不同，无法自动得到硬件死区。应从同一个 `OCxREF` 派生 CHx/CHxN，并核对高级定时器输出级。

### 10.2 把 `DeadTime=84` 当成 84 ns

HAL 字段是 8 位 DTG 编码。实际时间取决于 TIM1 时钟、`CR1.CKD` 和分段编码。改时钟后必须重算并重新测量。

### 10.3 只启动 CH1，忘记 CH1N 或 MOE

`CC1E`、`CC1NE`、`MOE` 与 `CEN` 是不同门。逐项读回，不要用“Start 返回 HAL_OK”代替波形证据。

### 10.4 把主输出和互补输出交给两个模块

F4 HAL 的任一 Stop 都会清全局 `MOE`。两个模块各自认为只停止一侧，会互相破坏。TIM1 安全输出对必须只有一个所有者。

### 10.5 在配置 BDTR 之后又随意调用配置函数

F4 v1.28.3 的 `HAL_TIMEx_ConfigBreakDeadTime()` 组装并整体写 `BDTR`。在已经启动或单独修改 MOE 后再调用，可能覆盖当前值。完整配置必须先于启动，运行期修改要走受控停机流程。

### 10.6 假定 break callback 才关闭输出

这会把硬件安全路径误画成 `BKIN -> IRQ -> CPU -> Stop`。正确关系是硬件先处理输出，IRQ 只提供诊断。禁用 IRQ 不应使 BKIN 的硬件动作消失。

### 10.7 callback 中立刻重新置 MOE

如果故障仍有效、原因未知或输出状态未审计，自动重开可能反复冲击功率级。先锁存首个故障，主循环确认外部条件后再显式恢复。

### 10.8 把 MOE=0 等同于引脚低

关闭状态受 OSSI/OSSR/OIS、极性、AF 与外部电路共同决定。必须按板级真值表和实测波形判断。

### 10.9 忽略共享 IRQ

`TIM1_BRK_TIM9_IRQn` 是共享向量。若 TIM9 也启用，ISR 必须判断并分发两个来源，否则可能遗漏 TIM9 或错误清除状态。

### 10.10 在调试器暂停时推断正常时序

内核 halt 时外设是否继续运行取决于 debug freeze 配置。暂停 CPU 可能让定时器继续、IRQ 挂起或输出维持，不能把断点状态直接当成自由运行行为。

### 10.11 未核对 BKIN 极性就启用功率级

active-high/active-low 选错可能让正常态一直刹车，或更危险地让真实故障不生效。必须从外部比较器/驱动器输出、上拉下拉和数据手册真值表逐级核对。

## 11. 调试观察点

按链路顺序采证：

| 顺序 | 观察点 | 能证明 | 不能证明 |
| --- | --- | --- | --- |
| 1 | RCC `TIM1EN/TIM1RST`、clock tree | 外设有时钟且已释放复位 | 频率已由仪器测得 |
| 2 | `PSC/ARR/RCR/CR1.CKD/CMS` | PWM 与 tDTS 的计算输入 | 引脚已有波形 |
| 3 | `CCMR1.OC1M/OC1PE`、`CCR1` | 内部参考配置 | CH1/CH1N 极性正确 |
| 4 | `CCER.CC1E/CC1NE/CC1P/CC1NP` | 两条支路许可与极性 | 总门控已开 |
| 5 | `BDTR.DTG/BKE/BKP/AOE/OSSI/OSSR/MOE` | dead/break/总门控配置 | 真实死区和安全电平 |
| 6 | CH1/CH1N 两通道波形 | 实际引脚非重叠与周期 | 功率器件电流绝不重叠 |
| 7 | BKIN 电平、`BIF`、MOE、输出波形 | break 事件与输出关闭关联 | callback 延迟等于硬件关闭延迟 |
| 8 | callback 计数与首个故障 | CPU 诊断链已走通 | 硬件关断依赖 callback |

故障定位树：

```text
CNT 不动
  -> 查 HSI/HSE、PLL、APB2、TIM1EN、TIM1RST、CEN

CNT 动，OC1REF/比较配置不对
  -> 查 PSC/ARR/CCR1、OC1M、preload、UG、生效更新点

内部配置正确，引脚无波形
  -> 查 CC1E/CC1NE、MOE、GPIO AF、封装复用、break 是否一直有效

只有一路有波形
  -> 查 CH1N 是否由目标实例/通道支持、CC1NE、引脚复用、OCN polarity

两路有波形但没有期望死区
  -> 查 TIM1 kernel clock、CKD、DTG 分段、示波器通道/阈值

BKIN 有效但输出不关
  -> 立即保持功率级禁用
  -> 查真实 BKIN 引脚/AF、电平、BKE/BKP、外部网络和 BDTR 读回

输出已关但无 callback
  -> 查 BIF/BIE、NVIC enable/pending、共享向量、ISR 是否调用 HAL handler

故障解除后意外自动恢复
  -> 查 AOE、update event、是否有其他代码写 MOE
```

推荐断点放在初始化完成但 Start 之前、`TIM1_BRK_TIM9_IRQHandler` 和 `HAL_TIMEx_BreakCallback`。不要在功率级已启用时靠单步调试验证安全路径。

## 12. 实战实验

### 实验 A：Host Fake 故障矩阵

1. 把第 8.1 节保存到独立主机测试源，记录编译器版本和严格告警命令。
2. 运行原始断言并保存 stdout、stderr 和退出码。
3. 增加连续 1000 次 MAIN/COMPLEMENT 换向，每个 tick 后断言不变量。
4. 在 dead time 第一个 tick 重新请求另一侧，定义并验证策略。
5. 连续注入两次 break，确认 `break_events` 增加而 `first_fault` 不被覆盖。
6. 设置 locked 后尝试恢复，确认拒绝且两侧保持 off。

合格证据只覆盖 C11 模型。

### 实验 B：CubeMX 静态审计

1. 选择真实完整料号；没有料号则将引脚项标记为阻塞。
2. 按第 7.3 节设置 TIM1 CH1/CH1N、dead time 与 break。
3. 搜索生成代码中的 `HAL_TIM_PWM_Init`、`HAL_TIM_PWM_ConfigChannel`、`HAL_TIMEx_ConfigBreakDeadTime`。
4. 核对 `DeadTime`、`BreakState`、`BreakPolarity`、`AutomaticOutput` 和 idle/off 字段。
5. 确认 Start 顺序和所有错误返回值均被处理，功率级仍保持硬件禁用。
6. 保存 `.ioc` diff、生成代码 diff 和逐项审计表。

静态审计不等于目标构建或硬件验证。

### 实验 C：目标构建与寄存器读回

1. 实现真实 board 文件并 clean build；保存完整日志与退出码。
2. 烧录前检查未知板卡不会连接或使能功率级。
3. 在 Start 前读回 `BDTR.MOE=0`，核对 DTG/BKE/BKP/AOE。
4. Start 后读回 `CC1E/CC1NE/MOE/CEN`，自由运行观察 `CNT`。
5. Stop 后确认 `MOE=0`，再检查通道许可和计数器状态。
6. 故意令 BKIN 保持有效，确认 Start/Recover 失败路径保存首个故障。

### 实验 D：双通道死区测量

1. 功率级保持断开，只测 MCU 输出或经过已知安全缓冲后的信号。
2. 同时捕获 CH1 和 CH1N，记录探头、阈值、带宽和采样率。
3. 分别测 MAIN->N 与 N->MAIN 的关断到导通间隔。
4. 比较推导 500 ns 与测量值，记录量化误差、输出延迟和仪器误差。
5. 改变 `DTG` 到同一分段的另一个值，确认步进符合 `tDTS`；跨分段时重新计算。

### 实验 E：BKIN 硬件关闭和软件观察分离

1. 在低能量、安全条件下生成可控 BKIN 电平。
2. 一个示波器通道观察 BKIN，另两个观察 CH1/CH1N；硬件资源不足时分多次但保持条件一致。
3. 临时关闭 break IRQ，只保留 BKE，验证输出关闭不依赖 callback。
4. 重新开启 BIE/NVIC，记录 callback 计数；不得用 callback GPIO 边沿代替输出关闭时刻。
5. 保持 BKIN 有效执行 Recover，确认拒绝；解除后由主循环显式恢复。

## 13. 自检题

1. 为什么两个软件取反的普通 PWM 通道不能替代 CH1/CH1N？
2. `OC1REF`、`CC1E/CC1NE`、dead-time generator 和 `MOE` 的先后关系是什么？
3. `DeadTime=84` 为什么不是 84 ns？本课中它如何得到约 500 ns？
4. 修改 APB2 预分频后，哪些计算必须重做？
5. `MOE=0` 为什么不能直接证明两个外部功率管已关断？
6. BKIN 到输出关闭和 BKIN 到 callback 是同一条串行路径吗？
7. 为什么本课关闭 AOE？什么条件下才能考虑开启？
8. `HAL_TIM_PWM_Stop()` 为什么会影响互补输出所有者？
9. 为什么 `HAL_TIMEx_ConfigBreakDeadTime()` 必须在 Start 前调用？
10. break callback 中的 `SR` 为什么可能已没有 BIF？
11. 本课为什么不需要 update IRQ、CC IRQ 或 DMA？
12. Host Fake 通过后，哪些 F407 事实仍完全没有被证明？
13. 若 CH1 有波形、CH1N 没波形，应按哪四层检查？
14. 若 BKIN 有效、`BIF` 置位但没有 callback，应检查哪三层？

## 14. 面试题

### 14.1 如何设计半桥互补 PWM 的最小安全链？

回答应包含：同一比较参考派生主/互补输出；硬件 dead time；`CCxE/CCxNE` 与 `MOE` 分层门控；BKIN 独立硬件关闭；定义 off/idle 状态；软件锁存首个故障并显式恢复；最后通过双通道波形和真实驱动器真值表验证。

### 14.2 刹车中断优先级越高，硬件关断就越快吗？

不是。BKIN 的核心关断路径在定时器硬件中，不等待 CPU ISR。中断优先级影响软件何时记录和响应事件，但不能作为硬件关闭延迟的证明。

### 14.3 为什么不能让 CH1 和 CH1N 分属两个驱动对象？

两路共享比较参考、dead-time generator、计数器和全局 MOE；F4 HAL 的任一 Stop 还会清 MOE。拆分所有权会导致一个对象无法判断另一个对象是否正在输出，也无法协调故障恢复。

### 14.4 怎样从 168 MHz TIM1 时钟得到 20 kHz 与 500 ns？

边沿向上计数、PSC=0、ARR=8399 时，`168 MHz / 8400 = 20 kHz`。CKD=DIV1 时 `tDTS ~= 5.952 ns`，DTG=84 位于第一线性区，名义 dead time 为 `84 * tDTS = 500 ns`。二者均需目标读回和仪器验证。

### 14.5 F407 迁移到 H7，哪些内容可以直接保留？

可以保留“五段链”、唯一所有者、先配置后启动、硬件关闭与软件诊断分离、显式恢复和证据分层。不能直接复制时钟值、RCC 位、TIM 实例/引脚、DTG 编码假设、break 路由、HAL/LL API、IRQ 名称、DMA 映射或存储/缓存策略。

## 15. 延伸思考

1. 若占空比接近 0% 或 100%，dead time 与最小脉宽会怎样改变实际输出？应如何限定命令范围？
2. 若要在三个相臂同时更新 CCR1/2/3，如何利用预装载、update event 和重复计数避免相间撕裂？
3. 外部驱动器自身也有 dead time 时，两个 dead-time generator 如何组合，最坏误差如何预算？
4. BKIN 信号短脉冲、毛刺和异步跨时钟域如何处理？F407 目标没有本课已证实的 BKIN 数字滤波时，应把滤波放在哪里？
5. 若 AOE 开启，故障解除到下一个 update event 的恢复时刻如何证明？这是否符合系统安全需求？
6. 产品启用 LOCK 后，现场升级如何修改 dead time？是否必须复位，复位期间输出安全态由谁保证？
7. `TIM1 TRGO -> ADC -> DMA` 采集相电流时，采样点如何避开开关边沿和 dead time？
8. 怎样设计独立监控通道，检测 `MOE` 被意外重开或 CH1/CH1N 实际发生重叠？

## 16. 本节总结

本课唯一的新核心概念是**高级控制定时器的互补 PWM 安全输出链**：

```text
normal:
compare -> OC1REF -> dead time -> polarity/channel selection
        -> output-enable circuit controlled by MOE/off-state -> pins

fault:
BKIN -> break logic -> output shutdown + BIF -> optional IRQ -> diagnosis
```

可迁移的能力不是记住 `DTG=84`，而是逐段回答：对象在哪里定义、谁持有整组输出、谁注入正常/故障事件、每个门控怎样影响下一段、每一层证据究竟证明到哪里。Host Fake 验证非重叠和恢复策略；STM32F407xx 参考实现说明它如何落到 clock/reset、CubeMX、HAL、LL、寄存器、IRQ 和板级注入点。两条轨道的证据不能互换。

当前 STM32 参考实现未编译、未烧录、未读回、未测量，`hardware_verified=false`。

## 17. 下一步

完成本课并取得用户实验或复习证据后，可进入 `adc-timer-dma-pipeline`：把已掌握的 TIM 事件源接到 ADC 采样和 DMA 缓冲区所有权，明确半满/完成/错误回调与 F7/H5/H7 的 DMA、缓存和安全属性差异。

高级定时器内部还可单列两个后续专题：

- 重复计数 + 预装载 + DMA burst：在受控 update 边界一致更新多通道波形；
- 三相控制与故障审计：加入 CH2/CH3、换相事件、最小脉宽、驱动器真值表和独立保护，不与本课单通道安全链混写。

### F4 -> F7 -> H5 -> H7 迁移复查表

| 系列 | 保留的机制 | 固定完整料号后必须重查 | 需要形成的新证据 |
| --- | --- | --- | --- |
| F4 | 本课五段链；F407 TIM1 为基线 | 具体 F4 子型号/封装、CHx/CHxN/BKIN、APB timer 倍频、BDTR 字段、共享 IRQ | RM/DS/包版本、寄存器读回、双通道波形 |
| F7 | 同一所有权与 break/诊断分离 | 目标 TIM 实例、kernel clock 来源、RCC/reset、引脚 AF、BDTR 扩展、HAL/LL API；若后续使用 DMA，重查 D-Cache/存储区 | 对应 F7 RM/DS/CubeF7 交叉表，不能沿用 F407 数值 [S5] |
| H5 | 同一安全链和显式恢复策略 | 目标定时器/break 路由、kernel clock、reset/security domain、TrustZone/安全属性边界、GPDMA/DMAMUX（后续链路） | Secure/Non-secure 所有权、目标 IRQ/DMA 和寄存器证据 [S6] |
| H7 | 同一逐跳审计方法 | 具体 H7 子系列/内核、timer kernel clock mux、总线/电源域、break 输入、HAL/LL、共享资源；后续 DMA 重查 D-Cache 与内存域 | 对应 H7 RM/DS/CubeH7、时钟读回、缓存策略和波形 [S7] |

该表只定义复查工作，不声称所有 F7/H5/H7 都具备相同 TIM1、引脚或寄存器。每次迁移都要先固定完整料号，再由对应系列第一方资料重建交叉表。

## 18. 参考资料

- [S1] STMicroelectronics, *STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 advanced Arm-based 32-bit MCUs - Reference manual*, RM0090 Rev 22, May 2026：RCC、TIM1、互补输出、dead-time generator、break、BDTR、状态与中断；访问日期 2026-10-15。<https://www.st.com/resource/en/reference_manual/dm00031020.pdf>
- [S2] STMicroelectronics, *STM32F405xx STM32F407xx datasheet*, DS8626 Rev 12, March 2026：目标范围、时钟、电气限制与封装复用边界；访问日期 2026-10-15。<https://www.st.com/resource/en/datasheet/stm32f407vg.pdf>
- [S3] STMicroelectronics, *Description of STM32F4 HAL and low-layer drivers*, UM1725 Rev 8, March 2023：TIM HAL/LL 初始化、PWM、扩展功能、IRQ 与状态接口；访问日期 2026-10-15。<https://www.st.com/resource/en/user_manual/dm00105879.pdf>
- [S4] STMicroelectronics, *STM32Cube MCU Package for STM32F4 series*, STM32CubeF4 v1.28.3, 23 July 2025：本机安装包 `stm32f4xx_hal_tim.[ch]`、`stm32f4xx_hal_tim_ex.[ch]`、`stm32f4xx_ll_tim.h` 和 CMSIS 设备头文件用于核对结构字段、Start/Stop、BDTR 写入、DTG helper、break flag 与 callback 分发；访问日期 2026-10-15。<https://www.st.com/en/embedded-software/stm32cubef4.html>
- [S5] STMicroelectronics, *STM32Cube MCU Package for STM32F7 series*, STM32CubeF7 v1.17.3, 25 April 2025：仅用于定义 F7 迁移时需重查的目标、API、时钟与缓存边界；访问日期 2026-10-15。<https://www.st.com/en/embedded-software/stm32cubef7.html>
- [S6] STMicroelectronics, *STM32Cube MCU Package for STM32H5 series*, STM32CubeH5 v1.5.0, 5 February 2025：仅用于定义 H5 迁移时需重查的目标、安全属性、GPDMA/DMAMUX 与 API 边界；访问日期 2026-10-15。<https://www.st.com/en/embedded-software/stm32cubeh5.html>
- [S7] STMicroelectronics, *STM32Cube MCU Package for STM32H7 series*, STM32CubeH7 v1.12.1, 6 December 2024：仅用于定义 H7 迁移时需重查的目标、时钟域、DMA/DMAMUX、存储域与缓存边界；访问日期 2026-10-15。<https://www.st.com/en/embedded-software/stm32cubeh7.html>
