+++
title = "ADC 采样、量化与数字码交付的测量闭环"
date = "2026-10-07T17:56:34+08:00"
lastmod = "2026-10-07T17:56:34+08:00"
summary = "用平台无关的 Host Fake 建立 ADC 单次转换闭环：输入在采样保持边界冻结，按参考范围和分辨率量化为有界数字码，经完成状态交付给调用方；通过事件日志、断言和故障注入验证逻辑，同时明确真实 STM32 电气、寄存器和 HAL 行为仍需按目标系列第一方资料核对。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 25
tags = ["adc", "sampling", "sample-and-hold", "quantization", "digital-code", "eoc", "host-fake", "c11", "beginner"]
source_ids = ["st-rm0090-adc", "st-um1725-adc-hal", "st-an2834"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L025"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 25 课：ADC 采样、量化与数字码交付的测量闭环

ADC（Analog-to-Digital Converter，模数转换器）解决的问题是：程序只能处理离散的数字，而传感器、电位器或电源监测点通常提供连续变化的电压。本课只推进一个核心概念：**ADC 采样保持、量化与数字码交付的测量闭环**。闭环从一次受控触发开始，经过采样、保持、量化和完成通知，最后把一个有界的数字码交给调用方。

没有指定开发板、调试器、信号源或测量工具，所以主线使用 Host Fake（主机替身）：它替代“转换结果提供者”，验证输入边界、量化规则、完成状态和事件顺序；它不模拟真实引脚、电容、噪声、时钟、寄存器副作用或电气精度。本文没有构建、测量或上板证据，`hardware_verified` 必须为 `false`。

## 1. 本节目标

完成本课后，你应能：

- 解释模拟量、数字量、采样保持、量化、分辨率、参考电压和数字码之间的关系；
- 用公式把一个输入范围映射为有界整数，并说明截断策略带来的量化误差；
- 画出“触发 -> 采样 -> 转换 -> EOC -> 读取”的单次转换调用流；
- 在 Host Fake 中指出输入对象在哪里定义、转换状态由谁持有、触发由谁注入、结果如何返回；
- 用边界断言和故障注入区分“模型逻辑正确”和“真实 STM32 电气/寄存器行为已验证”；
- 将模型映射到 STM32 的适配清单，同时知道哪些 HAL、寄存器、校准和采样时间结论必须回到目标系列第一方资料核对。

核心目标与计划一致：学习者能够用平台无关的最小模型解释并验证一次 ADC 单次转换，完成采样、量化并得到有界数字码，指出对象定义、状态持有、触发注入、完成通知和读取调用流，并区分逻辑验证与真实 STM32 行为。

## 2. 它解决什么问题

### 2.1 连续输入如何变成可消费的数字

模拟量是可以在一个连续范围内变化的物理量，例如输入电压。数字量只能用有限位数表达。ADC 在一次转换中要回答四个问题：

1. 在什么时候观察输入；
2. 观察期间如何暂时保持这个值，避免转换过程中的输入变化不断改变结果；
3. 如何把保持的值映射到有限个整数等级；
4. 什么时候可以让软件安全地读取结果。

如果只写“读取 ADC 寄存器”，就隐藏了前三个问题，也无法解释为什么相同电压可能落在相邻两个数字码之间。测量闭环把这些动作和边界显式化，便于迁移到不同 MCU 或主机测试。

### 2.2 先规定模型边界

- 本课只做**单次转换**；连续转换、多通道扫描和 DMA 属于后续演化方向。
- Host Fake 的输入单位固定为毫伏（`mV`），参考范围也用 `mV` 表示；这只是测试模型的单位约定，不是某个 STM32 引脚的电气保证。
- 量化采用“向下取整后饱和”的明确策略：范围内输入计算整数商，超过参考范围时输出满量程码并记录饱和事件。
- 分辨率在示例中由调用者配置；12 位只是演示值，不代表所有 F4、F7、H5、H7 ADC 都具有同样分辨率或同样数据对齐方式。
- 不使用动态内存、函数指针、DMA、RTOS 或具体寄存器编程；公开接口使用固定宽度整数。

### 2.3 先看最小可观察闭环

假设参考范围是 `0..3300 mV`，分辨率是 12 位，调用者注入 `1650 mV`：

```text
应用注入 input=1650 mV
  -> 触发：开始一次单次转换
  -> 采样/保持：保存本次输入快照 1650 mV
  -> 量化：1650 * 4095 / 3300，向下取整为 2047
  -> 完成：转换状态变为 complete
  -> 读取：应用得到 code=2047
```

事件日志可以是：

```text
TRIGGER, SAMPLE_HOLD, QUANTIZE, COMPLETE, READ
```

这证明的是模型中调用流和边界规则。它不证明某颗芯片的采样电容已经充电到目标误差，也不证明真实 EOC 位、校准步骤或 HAL 返回值。

## 3. 必要前置知识

本课只把 `config/learning-state.toml` 的 `completed` 列表视为已完成前置。直接相关的前置包括：

1. 固定宽度整数、结构体、数组和 `const`；本课用它们描述输入、配置、结果和固定容量事件日志。
2. GPIO、定时器、UART、SPI、I2C 的基本数据流；它们都把外部事件变成软件可观察状态，ADC 的特殊之处是输入先经过采样和量化。
3. 编译器、Make/CMake 和静态分析的基本用法；本课给出主机实验命令，但本次运行没有执行构建，因此代码仍标为“示例，待上板验证”。

下面的术语从直观现象开始解释，不假定你已经掌握模拟电路或某个 STM32 ADC 实例。

## 4. 核心原理

### 4.1 采样与采样保持

**采样**（sampling）是在一个指定时刻或窗口观察输入。若输入在转换期间继续变化，转换器可能混合了多个时刻的值。**采样保持**（sample-and-hold）可以先把观察到的值冻结成一次转换的输入快照，再让后续量化只处理这个快照。

Host Fake 用 `held_input_mV` 表示这个快照：调用者在触发时注入输入，Fake 立即复制到状态对象，之后的量化只读取 `held_input_mV`。它没有模拟真实采样电容、开关电阻、源阻抗或采样时间；这些是电气行为，必须根据目标系列 ADC 章节和 AN2834 的适用范围核对。[S1][S3]

### 4.2 参考范围、分辨率与数字码

设输入参考范围为 `0..Vref`，分辨率为 `N` 位，则可表示的码数为 `2^N` 个，最大码为：

```text
full_scale = 2^N - 1
```

在本课的向下取整模型中，范围内输入 `Vin` 的数字码为：

```text
code = floor(Vin * full_scale / Vref)
```

当 `Vin >= Vref` 时输出 `full_scale`，并在 `Vin > Vref` 时记录饱和。真实 ADC 的输入范围、参考来源、数据对齐和超范围行为不应从这个公式直接推断；应以目标器件参考手册和数据手册为准。RM0090 只覆盖其首页列出的 STM32F4 型号，不能自动证明 F7、H5 或 H7 的相同细节。[S1]

分辨率越高，码间隔通常越小，但不等于测量一定更准确。参考电压噪声、输入源阻抗、采样窗口、布局和器件误差都可能成为更大的误差来源。AN2834 讨论了这些精度因素；它的表格和建议必须结合目标 MCU 及其修订版使用，不能把某一系列的最小采样时间直接套到另一系列。[S3]

### 4.3 量化误差与饱和

量化把连续数轴切成有限格子。向下取整策略的模型误差满足：

```text
0 <= Vin * full_scale / Vref - code < 1
```

这个不等式只描述本课的理想数学模型；它不是实际电压误差的完整预算。靠近 `0` 的输入应得到 `0`，等于参考值应得到满量程码，超过参考值不能回绕到小码，否则软件会把过压误判成低压。Host Fake 用饱和事件让这个边界可观察。

### 4.4 完成通知不是结果本身

EOC（End Of Conversion，转换结束）表示一次转换已经到达可以检查结果的完成边界。在不同平台上，软件可能轮询状态、等待中断通知，或由更高层驱动保存结果；本课不引入中断实现，只把 `complete` 状态和 `ADC_EVT_COMPLETE` 事件作为逻辑模型。

调用者必须先确认完成，再读取数字码。读取未完成对象应返回错误，而不是返回上一次残留值。真实 STM32 的 EOC 标志、清除/读取副作用和 HAL 轮询或中断接口必须按目标系列手册及对应 Cube 软件包核对；本课不猜测函数名或标志位规则。[S1][S2]

### 4.5 对象在哪里定义、谁持有、谁注入

| 对象 | Host Fake 中的定义与持有者 | 注入/调用者 | 生命周期 |
| --- | --- | --- | --- |
| 输入值 | `adc_fake_start` 的 `input_mV` 参数 | 应用或测试用例注入 | 进入采样后复制到 `held_input_mV` |
| 配置 | `adc_fake_t` 中的 `reference_mV`、`resolution_bits` | 初始化调用者写入 | 覆盖下一次转换前保持不变 |
| 转换状态 | `complete`、`busy`、`code`、`status` | Fake 实现持有并更新 | 从触发到读取结束 |
| 事件日志 | `events[]` 和 `event_count` | Fake 写入，测试读取 | 当前实例的固定容量生命周期 |
| 结果 | `code`，通过 `adc_fake_read` 输出 | 应用读取 | 完成后有效，下一次触发会更新 |

调用流是：**应用准备配置 -> 创建/持有静态对象 -> 注入输入并触发 -> Fake 保存采样快照并量化 -> 标记完成 -> 应用读取结果**。这里“创建”只是给一个已有的静态对象清零和配置，不涉及堆分配。

## 5. 关键术语与直观模型

| 术语 | 直观含义 | 本课边界 |
| --- | --- | --- |
| 模拟量 | 连续变化的电压或电流 | 用 `mV` 数字替代真实电气信号 |
| 数字量 | 有限位数表达的整数 | Host Fake 输出 `0..full_scale` |
| 采样 | 在一个时间窗口观察输入 | 由触发事件开始 |
| 采样保持 | 冻结本次输入快照 | 用 `held_input_mV` 表示 |
| 量化 | 把快照映射到有限整数等级 | 向下取整，超范围饱和 |
| 分辨率 | 码的位数 `N` | 示例为 12 位，可配置 |
| 参考电压/范围 | 定义满量程的上边界 | 示例为 3300 mV，不是板卡事实 |
| 数字码 | 软件可读取的整数结果 | `0..2^N-1` |
| 量化误差 | 连续值与离散码映射的差异 | 仅讨论理想模型误差 |
| 触发源 | 请求开始一次转换的来源 | 本课是函数调用者 |
| EOC | 转换结束通知 | 用 `complete` 和事件替代硬件位 |
| 轮询 | 软件反复检查完成状态 | 只作为适配选项说明 |
| 中断完成通知 | 硬件完成后通知软件 | 本课不实现，留作后续演化 |
| 输入阻抗/采样时间 | 影响真实采样建立的电气条件 | 具体规则待核对，不由 Fake 证明 |
| 校准 | 用硬件/软件修正误差的步骤 | 具体顺序待核对，不在本课实现 |

## 6. 从输入到结果的完整流程

一次单次转换可以按以下五步审计：

1. **触发**：应用决定现在需要一次测量，把输入模型值和已初始化的转换器对象交给 `adc_fake_start`。真实硬件中，触发可能来自软件启动或某个定时事件，具体来源待核对。
2. **采样/保持**：Fake 把输入复制到 `held_input_mV` 并记录 `SAMPLE_HOLD`。真实 ADC 会在采样窗口内连接输入路径并保持电荷，所需时间和源阻抗约束见目标资料。[S3]
3. **量化**：Fake 根据 `reference_mV` 和 `resolution_bits` 计算码，记录 `QUANTIZE`；输入超过参考范围时先记录 `SATURATED`，输出仍被限制在满量程。
4. **完成**：Fake 将 `complete` 置为 `1` 并记录 `COMPLETE`。在 MCU 适配层，这一步对应等待或接收 EOC；具体标志位、清除规则和 HAL 返回码待核对。[S1][S2]
5. **读取**：应用调用 `adc_fake_read`。只有完成状态有效时才复制 `code` 并记录 `READ`；未完成则返回 `ADC_ERR_NOT_COMPLETE`。

可以把责任画成：

```text
应用/测试
  | 配置 + 注入输入
  v
ADC 适配对象（持有配置、状态、结果、日志）
  | trigger -> sample/hold -> quantize -> complete
  v
调用方确认完成后 read(code)
```

这条流刻意没有把真实寄存器名称塞进应用。将来换成 STM32 实现时，只替换适配层中“触发、等待/接收 EOC、读取数据寄存器”的动作，应用仍应只消费有界结果和错误状态。

## 7. 嵌入式系统中的对应位置

### 7.1 五个动作的边界

本课不是架构课程，但仍明确区分五个动作，避免把示例对象误认为硬件实例：

1. **声明**：在接口头文件中声明 `adc_fake_init`、`adc_fake_start`、`adc_fake_read` 及状态类型。
2. **实现**：在实现文件中完成范围检查、采样快照、量化、完成状态和日志。
3. **实例化**：应用或测试函数定义一个静态 `adc_fake_t adc` 对象。
4. **组装**：调用初始化函数，把参考范围和分辨率写入对象；没有板卡时，组装的是 Host Fake 规则。
5. **使用**：应用注入输入、触发转换、检查错误并读取数字码。

真实 STM32 项目中，声明和实现通常分布在驱动接口与具体系列适配文件，实例可能由 BSP（Board Support Package，板级支持包）持有，组装负责把 ADC 外设、通道和触发源接起来，应用只使用结果。具体文件划分、句柄字段和 HAL 函数名依赖目标 Cube 包；UM1725 可作为 F4 HAL/LL 接口的第一方阅读入口，但不能证明其他系列 API 相同。[S2]

### 7.2 通用 STM32 迁移清单

把 Host Fake 五步映射到目标硬件时，逐项查证并记录器件型号、手册版本和页面：

1. **配置 ADC**：确认时钟、分辨率、数据对齐、单次/连续模式和校准要求；本课不提供寄存器值。
2. **选择输入通道**：确认模拟引脚、通道号和 GPIO 模式；没有板卡时不要填写虚构引脚。
3. **选择触发源**：确认软件启动还是定时器等外部触发；具体触发选择和边沿待核对。
4. **启动转换**：确认启动 API 或控制寄存器写入顺序，以及对象由谁持有。
5. **等待/接收完成**：确认轮询超时、EOC/EOS 等状态语义和中断清除规则；未核对前只写“待核对”。
6. **读取数据**：确认数据寄存器宽度、对齐、读取副作用和 HAL 返回契约。
7. **解释电压**：用目标数据手册的参考条件、校准和误差参数换算，不把 Host Fake 的理想公式当作精度承诺。

F4、F7、H5、H7 只在完成对应第一方资料核对后比较。RM0090 的范围限于其列出的 F4 器件；本课没有为 F7/H5/H7 提供具体寄存器或 API 结论。

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 能证明什么

- 输入在触发时被冻结，后续量化读取的是快照；
- 零点、满量程、中间值和超范围值的输出有明确边界；
- 事件顺序为触发、采样保持、量化、完成、读取；
- 未完成读取、非法参考范围等逻辑故障不会静默产生有效结果；
- 固定容量、静态对象和固定宽度整数满足本课代码约束。

### 8.2 Host Fake 不能证明什么

- ADC 引脚是否真的处于模拟模式，输入是否接到了目标通道；
- 采样电容是否在指定时间内完成建立，源阻抗是否满足要求；
- 参考电压噪声、INL/DNL、偏置、增益误差和温度漂移；
- 某个 F4/F7/H5/H7 型号的寄存器位、校准顺序、EOC 清除规则或 HAL API；
- 板卡电源、时钟树、信号源和测量仪器是否正常。

所以本课的硬件验证状态保持 `false`。只有在有具体板卡、构建记录、测量记录和可复现步骤后，才能单独更新硬件证据。

## 9. 最小代码示例

下面是一个 C11 子集的 Host Fake。它属于“主机逻辑验证层”，不包含 STM32 头文件，不映射寄存器，也不宣称模拟真实 ADC 电路。代码使用静态对象，事件日志容量固定为 12。

```c
#include <assert.h>
#include <stddef.h>
#include <stdint.h>

typedef uint8_t adc_status_t;
#define ADC_OK ((adc_status_t)0U)
#define ADC_ERR_BAD_CONFIG ((adc_status_t)1U)
#define ADC_ERR_BUSY ((adc_status_t)2U)
#define ADC_ERR_NOT_COMPLETE ((adc_status_t)3U)

typedef uint8_t adc_event_t;
#define ADC_EVT_TRIGGER ((adc_event_t)0U)
#define ADC_EVT_SAMPLE_HOLD ((adc_event_t)1U)
#define ADC_EVT_SATURATED ((adc_event_t)2U)
#define ADC_EVT_QUANTIZE ((adc_event_t)3U)
#define ADC_EVT_COMPLETE ((adc_event_t)4U)
#define ADC_EVT_READ ((adc_event_t)5U)
#define ADC_EVT_ERROR ((adc_event_t)6U)

#define ADC_EVENT_CAPACITY 12U

typedef struct {
    uint32_t reference_mV;
    uint8_t resolution_bits;
    uint32_t held_input_mV;
    uint32_t code;
    uint8_t busy;
    uint8_t complete;
    adc_status_t status;
    adc_event_t events[ADC_EVENT_CAPACITY];
    uint8_t event_count;
} adc_fake_t;

static void adc_log(adc_fake_t *adc, adc_event_t event)
{
    if (adc->event_count < ADC_EVENT_CAPACITY) {
        adc->events[adc->event_count] = event;
        adc->event_count = (uint8_t)(adc->event_count + 1U);
    }
}

static uint64_t adc_full_scale(const adc_fake_t *adc)
{
    return (((uint64_t)1U << adc->resolution_bits) - 1U);
}

adc_status_t adc_fake_init(adc_fake_t *adc,
                           uint32_t reference_mV,
                           uint8_t resolution_bits)
{
    if (adc == NULL) {
        return ADC_ERR_BAD_CONFIG;
    }
    if ((reference_mV == 0U) || (resolution_bits == 0U) ||
        (resolution_bits > 24U)) {
        adc->status = ADC_ERR_BAD_CONFIG;
        return ADC_ERR_BAD_CONFIG;
    }

    adc->reference_mV = reference_mV;
    adc->resolution_bits = resolution_bits;
    adc->held_input_mV = 0U;
    adc->code = 0U;
    adc->busy = 0U;
    adc->complete = 0U;
    adc->status = ADC_OK;
    adc->event_count = 0U;
    return ADC_OK;
}

adc_status_t adc_fake_start(adc_fake_t *adc, uint32_t input_mV)
{
    uint64_t full_scale;
    uint64_t scaled;

    if (adc == NULL) {
        return ADC_ERR_BAD_CONFIG;
    }
    if (adc->reference_mV == 0U ||
        adc->resolution_bits == 0U || adc->resolution_bits > 24U) {
        adc->status = ADC_ERR_BAD_CONFIG;
        return ADC_ERR_BAD_CONFIG;
    }
    if (adc->busy != 0U) {
        adc->status = ADC_ERR_BUSY;
        adc_log(adc, ADC_EVT_ERROR);
        return ADC_ERR_BUSY;
    }

    adc->event_count = 0U;
    adc->complete = 0U;
    adc->busy = 1U;
    adc->status = ADC_OK;
    adc_log(adc, ADC_EVT_TRIGGER);

    /* This copy is the model's sample-and-hold boundary. */
    adc->held_input_mV = input_mV;
    adc_log(adc, ADC_EVT_SAMPLE_HOLD);

    full_scale = adc_full_scale(adc);
    if (input_mV >= adc->reference_mV) {
        adc->code = (uint32_t)full_scale;
        if (input_mV > adc->reference_mV) {
            adc_log(adc, ADC_EVT_SATURATED);
        }
    } else {
        scaled = (uint64_t)input_mV * full_scale;
        adc->code = (uint32_t)(scaled / adc->reference_mV);
    }
    adc_log(adc, ADC_EVT_QUANTIZE);

    adc->busy = 0U;
    adc->complete = 1U;
    adc_log(adc, ADC_EVT_COMPLETE);
    return ADC_OK;
}

adc_status_t adc_fake_read(adc_fake_t *adc, uint32_t *code_out)
{
    if (adc == NULL) {
        return ADC_ERR_BAD_CONFIG;
    }
    if (code_out == NULL) {
        adc->status = ADC_ERR_BAD_CONFIG;
        return ADC_ERR_BAD_CONFIG;
    }
    if (adc->complete == 0U) {
        adc->status = ADC_ERR_NOT_COMPLETE;
        adc_log(adc, ADC_EVT_ERROR);
        return ADC_ERR_NOT_COMPLETE;
    }
    *code_out = adc->code;
    adc->status = ADC_OK;
    adc_log(adc, ADC_EVT_READ);
    return ADC_OK;
}

static void adc_assert_read_sequence(const adc_fake_t *adc, uint8_t saturated)
{
    uint8_t quantize_index = saturated != 0U ? 3U : 2U;
    uint8_t complete_index = saturated != 0U ? 4U : 3U;
    uint8_t read_index = saturated != 0U ? 5U : 4U;

    assert(adc->events[0] == ADC_EVT_TRIGGER);
    assert(adc->events[1] == ADC_EVT_SAMPLE_HOLD);
    if (saturated != 0U) {
        assert(adc->events[2] == ADC_EVT_SATURATED);
    }
    assert(adc->events[quantize_index] == ADC_EVT_QUANTIZE);
    assert(adc->events[complete_index] == ADC_EVT_COMPLETE);
    assert(adc->events[read_index] == ADC_EVT_READ);
    assert(adc->event_count == (saturated != 0U ? 6U : 5U));
}

int main(void)
{
    adc_fake_t adc;
    adc_fake_t not_ready;
    uint32_t code = 0U;

    assert(adc_fake_init(&adc, 3300U, 12U) == ADC_OK);
    assert(adc_fake_start(&adc, 0U) == ADC_OK);
    assert(adc_fake_read(&adc, &code) == ADC_OK && code == 0U);
    adc_assert_read_sequence(&adc, 0U);

    assert(adc_fake_start(&adc, 1650U) == ADC_OK);
    assert(adc_fake_read(&adc, &code) == ADC_OK && code == 2047U);
    adc_assert_read_sequence(&adc, 0U);

    assert(adc_fake_start(&adc, 3300U) == ADC_OK);
    assert(adc_fake_read(&adc, &code) == ADC_OK && code == 4095U);
    adc_assert_read_sequence(&adc, 0U);

    assert(adc_fake_start(&adc, 5000U) == ADC_OK);
    assert(adc_fake_read(&adc, &code) == ADC_OK && code == 4095U);
    adc_assert_read_sequence(&adc, 1U);

    assert(adc_fake_init(&not_ready, 3300U, 12U) == ADC_OK);
    assert(adc_fake_read(&not_ready, &code) == ADC_ERR_NOT_COMPLETE);
    assert(adc_fake_init(&not_ready, 0U, 12U) == ADC_ERR_BAD_CONFIG);
    return 0;
}
```

代码的所有权关系很明确：`main` 持有两个静态对象；`adc_fake_init` 写入配置；`adc_fake_start` 接收调用者注入的输入并独占更新一次转换的状态；`adc_fake_read` 只在 `complete` 为真时交付结果。`adc_status_t` 和 `adc_event_t` 都是明确宽度的 `uint8_t` 别名，宏常量表达其取值，避免把 C `enum` 的实现宽度当作接口契约。`status` 与返回值同步记录最近一次可表示的状态；空指针没有可更新的对象。`uint64_t` 中间乘法用于避免 `input_mV * full_scale` 在演示范围内过早溢出，但输出仍是有界的 `uint32_t` 数字码。

### 代码调用流的预期逻辑结果

| 输入 | 预期数字码 | 预期说明 |
| ---: | ---: | --- |
| `0 mV` | `0` | 零点 |
| `1650 mV` | `2047` | 向下取整的中间值 |
| `3300 mV` | `4095` | 满量程 |
| `5000 mV` | `4095` | 饱和，不回绕 |
| 未触发直接读取 | 错误 | 不交付残留值 |
| 参考范围为 `0` | 错误 | 配置非法 |

这里的结果是根据代码和公式推导的逻辑预期，不是本次运行的编译或硬件测试记录。若将代码复制到普通 Windows 主机编译，应把它视为实验材料，并自行保存命令输出作为个人证据。

## 10. 常见错误

1. **把模拟电压直接当作数字码**：`1650 mV` 不是 12 位码 `1650`；必须经过参考范围和分辨率映射。
2. **忽略参考范围**：只写 `input * 4095` 而不除以 `Vref`，结果没有物理尺度。
3. **让超范围值回绕**：无符号整数溢出或错误取模会把过压变成小码；应明确饱和或返回错误。
4. **未完成就读取**：返回上一次结果会制造“看似有效”的陈旧测量；应返回 `ADC_ERR_NOT_COMPLETE`。
5. **把量化误差当成电气精度**：理想公式的一个码以内误差不包含噪声、参考误差、采样建立误差和温漂。
6. **把 Host Fake 字段当寄存器布局**：`complete` 只是教学状态；真实 EOC 位、数据寄存器读取副作用和清除规则必须查目标手册。
7. **把 F4 结论外推到其他系列**：RM0090 和 UM1725 的适用范围有限；F7、H5、H7 需要各自资料。
8. **在应用层硬编码引脚和通道**：没有板卡和器件型号时只能写适配清单，不能凭空填写实例。

## 11. 调试观察点

- 在触发入口记录输入值、参考范围和分辨率，确认输入来自调用者而不是隐藏全局变量。
- 在采样保持边界观察 `held_input_mV`；如果它在量化前被意外修改，说明模型没有保持快照。
- 检查 `full_scale` 和中间乘法类型，重点观察分辨率为 1、12、24 位时是否发生移位或溢出错误。
- 对 `0`、`Vref`、`Vref+1` 和一个中间值分别单步，比较事件日志和预期码。
- 在未完成读取路径观察 `ADC_EVT_ERROR`，确认输出变量没有被错误路径覆盖。
- 在真实 STM32 适配时，分别记录“触发已发出”“EOC 已观察”“数据已读取”三个证据点；具体寄存器窗口、HAL 状态和清除动作在没有目标手册前均标记为待核对。
- 不要把主机断言通过写成“ADC 精度通过”；断言只覆盖软件模型的逻辑契约。

## 12. 实战实验

### 实验 A：边界和量化表

1. 将第 9 节代码保存为临时 `adc_fake.c`，使用本机可用的 C11 编译器生成主机程序；本仓库没有把本次运行的编译结果当作证据。
2. 运行程序，确认断言覆盖零点、中间值、满量程、饱和、完整事件顺序、未完成读取和非法配置。
3. 把输入改成 `1649 mV`、`1651 mV`，手算 `floor(input * 4095 / 3300)`，记录码值变化。
4. 增加一个输入 `3301 mV`，确认仍为 `4095`，并检查事件日志中有 `ADC_EVT_SATURATED`。

### 实验 B：故障注入

1. 在 `adc_fake_read` 调用前不执行 `adc_fake_start`，记录返回的 `ADC_ERR_NOT_COMPLETE` 和事件日志。
2. 将 `resolution_bits` 改为 `0` 或 `25`，确认初始化拒绝配置。
3. 在测试夹具中显式将 `adc.busy=1U` 后调用 `adc_fake_start`，观察 `ADC_ERR_BUSY` 路径；不要把这个逻辑故障解释为真实硬件的全部忙状态语义。
4. 写一张表，列出“注入动作、预期错误、观察到的事件、仍不能证明的硬件事实”。

### 实验 C：通用 STM32 适配草图

不连接硬件，只写一页适配清单：目标 MCU 和手册版本、ADC 实例、输入通道、参考条件、分辨率、触发源、单次模式、EOC 观察方式、读取数据位置、校准步骤和超时策略。每一项若没有第一方页码就写“待核对”，不要填入猜测的引脚或 HAL 函数。

## 13. 自检题

1. 为什么一次转换需要采样保持，而不是在整个量化过程中持续读取输入？
2. 对 `Vref=3300 mV`、`N=12`、`Vin=1650 mV`，本课向下取整模型为什么得到 `2047` 而不是 `2048`？
3. `Vin=Vref` 和 `Vin>Vref` 在本课中分别有什么结果和事件差异？
4. 谁持有 `complete` 和 `code`？为什么调用者不能在未完成时读取旧值？
5. `ADC_EVT_COMPLETE` 能证明哪些逻辑事实，不能证明哪些硬件事实？
6. 如果要改成轮询或中断完成通知，Host Fake 的哪部分契约可以保留，哪部分必须按目标手册重写？

参考答案要点：采样保持冻结一次快照；向下取整保留小数部分被舍弃的策略；等于参考值为满量程且不必记录超范围饱和，超过参考值为满量程并记录饱和；状态由转换器对象持有，未完成读取返回错误；完成事件只说明模型状态转移；硬件完成标志和通知路径必须按系列资料核对。

## 14. 面试题

1. 请从触发开始，用五个阶段解释一次 ADC 单次转换，并说明每阶段的状态持有者。
2. 为什么提高 ADC 分辨率不一定提高系统测量精度？请至少说出参考条件、采样建立和噪声中的两个因素。
3. 如何避免把超范围输入解释成低码？请比较错误返回和饱和输出的业务取舍。
4. 如果应用偶尔读到上一次 ADC 结果，你会先观察哪些状态、事件或时间边界？
5. 你如何证明 Host Fake 的测试没有越过“逻辑验证”和“硬件验证”的边界？
6. 面对 F4、F7、H5、H7 四个系列，你会如何组织资料核对顺序，而不是复制一套寄存器代码？

## 15. 延伸思考

- 如果输入源阻抗很高，采样保持的建立时间会怎样影响结果？请只根据目标系列的第一方资料给出结论，并记录适用型号。
- 如果系统需要周期采样，触发由谁注入、结果由谁消费？先画调用流，不要直接引入 DMA 或 RTOS。
- 如果量化策略从向下取整改成四舍五入，边界断言和误差说明需要如何变化？
- 如果参考电压本身变化，软件如何区分“输入变化”和“参考变化”？哪些信息必须额外测量？
- 在真实项目中，校准结果由谁持有、何时失效、如何进入电压换算？这些问题留到核对具体系列后再实现。

## 16. 本节总结

ADC 测量闭环把连续输入交付为可审计的数字结果：调用者触发一次转换，转换器在采样保持边界冻结输入，按参考范围和分辨率量化为有界数字码，产生完成通知，调用者确认完成后读取结果。Host Fake 用静态对象、固定宽度整数、事件日志和断言验证了这条逻辑流，并显式处理零点、满量程、饱和、非法配置和未完成读取。

闭环模型不等于硬件事实。采样时间、输入阻抗、参考电压、校准、EOC 位、数据寄存器和 HAL 调用契约都必须回到目标 MCU 的第一方资料核对。本课没有具体板卡、构建、测量或上板证据，`hardware_verified=false`。

## 17. 下一步

下一步仍围绕 ADC 主题，先在选定 STM32 系列上核对“配置 -> 选择通道 -> 启动 -> 等待/接收 EOC -> 读取”的适配边界，再考虑如何把一次转换扩展为受控的周期采样。只有完成单次转换的资料核对和实验记录后，才进入 DMA 或多通道扫描等后续主题。

## 18. 参考资料

- [S1] STMicroelectronics，*STM32F405/415, STM32F407/417, STM32F427/437 and STM32F429/439 advanced Arm-based 32-bit MCUs - Reference manual*，RM0090 Rev 22。重点阅读 ADC 转换流程、数据寄存器、转换结束和触发相关章节；适用范围限于手册列出的 STM32F4 型号。<https://www.st.com/resource/en/reference_manual/dm00031020.pdf>，访问日期：2026-10-07。
- [S2] STMicroelectronics，*UM1725 Description of STM32F4 HAL and low-layer drivers*，Rev 8（March 2023）。重点阅读 STM32F4 ADC HAL/LL 初始化、启动、轮询/中断接口和状态返回；具体 Cube 软件包版本仍需核对。<https://www.st.com/resource/en/user_manual/dm00105879.pdf>，访问日期：2026-10-07。
- [S3] STMicroelectronics，*How to optimize the ADC accuracy in the STM32 MCUs - Application note*，AN2834 Revision 10。重点阅读采样时间、模拟源阻抗、参考条件和精度误差；文中的系列表格不能直接移植到未核对的 F7、H5、H7 型号。<https://www.st.com/resource/en/application_note/cd00211314-how-to-get-the-best-adc-accuracy-in-stm32-microcontrollers-stmicroelectronics.pdf>，访问日期：2026-10-07。

这些来源均来自 `config/source-policy.toml` 允许的 `st.com` 域名，S1、S2、S3 均为第一方资料。正文只使用它们作为 STM32 适配核对入口；Host Fake 的公式、事件和错误码是本课的教学模型，不是 ST 源码复制或硬件保证。
