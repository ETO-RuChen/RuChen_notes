+++
title = "链接脚本：把构建输入放进可验证的内存布局"
date = "2026-10-02T15:36:12+08:00"
lastmod = "2026-10-02T15:36:12+08:00"
summary = "用最小 MEMORY/SECTIONS 抽象解释输入段到输出段再到命名内存区域的布局，并用 Host Fake 验证链接脚本边界符号如何被启动初始化消费。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 14
tags = ["linker-script", "input-section", "output-section", "memory-region", "linker-symbol", "startup", "host-fake", "c11", "beginner"]
source_ids = ["st-pm0214-cortex-m4-programming-manual", "st-pm0253-cortex-m7-programming-manual", "gnu-ld-2-9-1-manual"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L014"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 14 课：链接脚本：把构建输入放进可验证的内存布局

编译器把每个源文件翻译成目标文件，但“代码和数据最终放在哪个存储区域、哪些输入段合并成哪个输出段”仍需要链接阶段的规则。链接脚本（linker script，链接器脚本）就是这份规则：它把输入段组织成输出段，再把输出段约束到命名的内存区域，并可导出段边界符号供启动实现使用。

本课只建立可迁移的布局模型，不假定某块 STM32 开发板，不填写具体芯片地址，也不声称已经交叉编译、下载或上板。主机示例是 Host Fake（主机伪实现），只验证布局算法和边界符号的调用流。

## 第 1 部分：布局规则与启动边界

## 1. 本节目标

完成本课后，你应能：

- 阅读最小的 `MEMORY`/`SECTIONS` 链接脚本，复述“输入段 -> 输出段 -> 内存区域”的关系；
- 区分输入段、输出段、命名内存区域和链接脚本导出的边界符号，并说明它们分别在哪里定义、由谁持有、谁提供给下一层、谁使用；
- 说明链接脚本是构建期布局规则，不是复位后执行的运行时代码；
- 理解启动实现怎样消费 `data_start`、`data_end` 等边界信息，而不是自行猜测主机地址；
- 在普通 Windows 主机上运行一个 C11 子集的逻辑验证，覆盖不重叠、容量不足、缺失边界和顺序错误；
- 明确 Host Fake、GNU 链接器语义与真实 STM32 内存布局之间的证据边界。

本课引入两个新核心概念：

1. **链接脚本把输入段组织为输出段并约束其落入命名内存区域。**
2. **链接脚本导出的边界符号把构建期布局信息传给启动代码。**

## 2. 它解决什么问题

“编译成功”只说明各个源文件能够被翻译；它没有告诉我们最终映像的代码、只读数据、已初始化数据和零初始化数据如何排列，也没有检查这些内容是否超出某个存储区域。链接阶段把多个目标文件的输入段合并，并根据脚本决定输出段的顺序、起始位置和允许的区域。GNU `ld` 文档把内存区域和输出段规则作为链接脚本的基本职责。[3]

启动代码随后需要知道某些段的边界。例如，带初值数据在运行时可能需要从映像中的装载位置准备到运行位置；零初始化区域需要知道清零范围。**段名、符号名、地址和复制方式都由具体工具链、启动文件和芯片工程共同决定，未核对时必须标记为待核对。** 本课只演示“脚本导出数值边界 -> 启动 Fake 消费边界”的接口关系，不断言任何 STM32 的实际地址或 VMA/LMA（运行地址/装载地址）细节。[3]

## 3. 必要前置知识

必要前置是 `reset-sequence`、`vector-table` 和 `startup`：它们说明复位入口最终要进入一个已完成早期准备的 C 环境。`compiler`、`make-cmake`、`storage-duration` 和 `linkage` 可帮助复习，但不要求掌握具体链接器语法。

本课不假定你已掌握 ELF（Executable and Linkable Format，可执行与可链接格式）文件内部布局、map 文件诊断、重定位、高级地址表达式或芯片寄存器。

## 4. 核心原理

### 4.1 三层布局模型

```text
目标文件中的输入段
  .text.foo     .text.bar     .rodata.msg
  .data.config  .bss.counter
          \\        |        /
           -> 链接脚本的 SECTIONS 规则
              -> 输出段 .text / .rodata / .data / .bss
                 -> MEMORY 中命名的 FLASH / RAM 区域
```

- **输入段（input section）**：来自各个目标文件的细粒度段，例如某个函数的 `.text.foo`。它们由编译器、汇编器和目标文件输入提供。
- **输出段（output section）**：链接脚本规则创建的聚合结果，例如把多个 `.text*` 输入段放进一个 `.text` 输出段。
- **内存区域（memory region）**：脚本用 `MEMORY` 命名并给出起点、长度和属性的可用范围。名称是工程规则的一部分，不能从名称推断某颗芯片的真实地址。

最小 GNU `ld` 风格抽象如下（地址和大小是示意值，待具体工程核对）：

```ld
MEMORY
{
  FLASH (rx) : ORIGIN = 0x00000000, LENGTH = 256K
  RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 64K
}

SECTIONS
{
  .text :
  {
    *(.text*)
    *(.rodata*)
  } > FLASH

  .data :
  {
    data_start = .;
    *(.data*)
    data_end = .;
  } > RAM

  .bss (NOLOAD) :
  {
    bss_start = .;
    *(.bss*)
    *(COMMON)
    bss_end = .;
  } > RAM
}
```

这里的 `MEMORY` 和 `SECTIONS` 是链接脚本声明与组装规则；`data_start` 等是链接阶段赋值的符号。它们不是 C 函数，也不会在复位时“执行”。`NOLOAD`、输入模式和实际段属性需要结合选用的 GNU `ld` 版本与工程核对；本例不把它们推广成 STM32 的固定做法。[3]

### 4.2 边界符号如何跨越构建期和运行期

脚本中的 `data_start = .;` 把当前位置计数器的数值导出为链接符号。启动实现可以把这些符号声明为外部边界并在初始化步骤中读取。重要的是：启动代码消费的是**链接产物提供的边界值**，而不是主机上某个数组的指针地址。

| 对象 | 定义位置 | 持有者 | 提供/注入者 | 使用者与调用流 |
| --- | --- | --- | --- | --- |
| 输入段 | 编译器/汇编器生成的目标文件 | 目标文件 | 链接器读取 | `SECTIONS` 规则匹配 |
| 输出段 | 链接脚本 `SECTIONS` | 链接产物 | 链接器按规则合并 | 映像和启动实现 |
| `FLASH`/`RAM` 区域 | 链接脚本 `MEMORY` | 工程构建配置 | 链接器约束放置 | 输出段布局检查 |
| `data_start`/`data_end` | `SECTIONS` 内的符号赋值 | ELF/链接产物符号表 | 链接器导出 | 启动初始化读取边界 |
| 初始化函数 | 启动实现源文件 | 启动代码 | 边界符号注入 | 复位处理函数按顺序调用 |

这张表回答了每个核心对象“在哪里定义、谁持有、谁注入、谁使用”。在真实工程中，符号的可见性、段名和装载/运行地址必须从实际脚本、启动文件与构建产物核对。

### 4.3 五个动作：声明、实现、实例化、组装、使用

本课把五个动作分开：

1. **声明**：在链接脚本中声明 `MEMORY` 区域、`SECTIONS` 规则以及边界符号名字；在启动 C/汇编接口中声明要读取的边界。
2. **实现**：编译器产生输入段；链接器实现匹配、排序、放置和符号赋值；启动代码实现复制或清零的运行时动作。
3. **实例化**：具体目标文件中出现函数、常量和静态对象，形成实际输入段；具体工程选择一份脚本并产生一份链接产物。
4. **组装**：构建系统把目标文件、链接脚本和启动实现交给链接器，形成 ELF/固件映像。组装发生在构建期，不是复位时的函数调用。
5. **使用**：复位后的启动实现读取链接产物提供的边界，按既定顺序准备运行时数据，再交给应用。

把这五步混为“链接脚本执行了初始化”会误解时间边界：脚本决定布局，启动代码才在目标上执行运行时动作。

## 5. 关键术语与直观模型

| 术语 | 直观含义与本课边界 |
| --- | --- |
| 链接脚本（linker script） | 构建期的布局规则文件，不是运行时代码。 |
| 输入段（input section） | 目标文件带来的细粒度内容。 |
| 输出段（output section） | 脚本把多个输入段合并后的映像段。 |
| `MEMORY` | 给可用地址范围命名并限制容量的脚本命令；具体地址待核对。 |
| `SECTIONS` | 描述输出段顺序、匹配输入段和放置区域的脚本命令。 |
| 链接符号 | 链接期产生的数值名称，可作为段边界接口。 |
| 段边界 | `start`/`end` 一类的半开区间边界；边界顺序必须验证。 |
| ELF | 链接产物常见格式；本课只把它作为符号和段信息的承载物，不展开诊断。 |
| map 文件 | 链接器生成的布局报告；后续课程再用于诊断，本课不依赖它。 |
| VMA/LMA | 运行地址/装载地址的术语；具体语义和复制策略待结合 GNU `ld` 与目标工程核对。 |
| Host Fake | 用普通 C 结构和断言表达布局约束，不模拟 Cortex-M 地址空间。 |

## 6. 从输入到结果的完整流程

```text
输入目标文件的段记录
  -> layout_outputs() 按 kind 合并为 .text/.data/.bss
  -> layout_outputs() 检查允许区域、容量和不重叠
  -> 导出 data_start/data_end/bss_start/bss_end 数值
  -> startup_init_data() 只消费这些边界
  -> 断言初始化顺序和错误注入结果
```

Host Fake 中的对象定义在示例文件里：记录数组代表输入段，区域数组代表 `MEMORY`，布局结果代表输出段和脚本符号。实验驱动持有这些静态对象并显式注入一次布局结果；启动 Fake 只读取边界结构，不读取主机数组地址。真实目标中的入口触发来自复位和启动实现，不能由主机 `main` 的一次调用替代。

## 7. 嵌入式系统中的对应位置

在 STM32 工程中，链接脚本位于编译器/链接器与启动实现之间：它把编译得到的内容组织成固件映像，启动实现再根据工程导出的边界准备 C 运行时。F4、F7、H5、H7 的可迁移部分是这条责任链；具体内存区域、别名、段名、启动文件和 VMA/LMA 必须按目标系列、具体型号和生成工程逐项核对。[1][2]

本课没有具体开发板、芯片型号、调试器或构建日志，因此不填写真实地址、引脚、时钟树、外设实例，也不把 `0x00000000` 等示意地址当成 STM32 证据。

## 8. 主机实验与硬件迁移边界

Host Fake 可以证明：给定一组输入记录和容量约束时，布局结果是否不重叠、是否越界，以及边界结构是否按正确顺序被启动初始化消费。它不能证明 GNU `ld` 已接受某份脚本、某个 ELF 的实际段地址、Cortex-M 的别名规则、启动汇编或板上执行。

本课没有真实编译、下载、测量或上板记录，`hardware_verified=false`。迁移到 F4/F7/H5/H7 时，先保存实际脚本、链接器版本和 map/ELF 证据，再核对区域和符号；来源不足的内容保持“待核对”。

## 第 2 部分：Host Fake 完整示例

## 9. 最小代码示例

下面是可作为 `linker-fake.c` 的 C11 子集示例。它使用固定宽度整数、静态数组、无动态内存和无函数指针；数值地址只是 Host Fake 的抽象坐标。

```c
#include <assert.h>
#include <stdint.h>

enum section_kind {
    SECTION_TEXT = 1U,
    SECTION_DATA = 2U,
    SECTION_BSS = 3U
};

struct input_section {
    enum section_kind kind;
    uint32_t size;
};

struct memory_region {
    uint32_t origin;
    uint32_t length;
};

struct output_section {
    uint32_t start;
    uint32_t end;
};

struct layout_result {
    struct output_section text;
    struct output_section data;
    struct output_section bss;
    uint32_t symbols_present;
};

static uint32_t add_checked(uint32_t base, uint32_t size, uint32_t limit,
                            uint32_t *result)
{
    if (base > limit || size > limit - base) {
        return 0U;
    }
    *result = base + size;
    return 1U;
}

static uint32_t region_limit(struct memory_region region, uint32_t *limit)
{
    if (region.length > UINT32_MAX - region.origin) {
        return 0U;
    }
    *limit = region.origin + region.length;
    return 1U;
}

static uint32_t ranges_overlap(struct output_section left,
                               struct output_section right)
{
    if (left.start >= left.end || right.start >= right.end) {
        return 0U;
    }
    return (left.start < right.end && right.start < left.end) ? 1U : 0U;
}

static uint32_t layout_outputs(const struct input_section *inputs,
                               uint32_t input_count,
                               struct memory_region flash,
                               struct memory_region ram,
                               struct layout_result *result)
{
    uint32_t flash_cursor = flash.origin;
    uint32_t ram_cursor = ram.origin;
    uint32_t flash_limit;
    uint32_t ram_limit;
    uint32_t data_seen = 0U;
    uint32_t bss_seen = 0U;
    enum section_kind last_kind = 0;
    uint32_t i;

    if (result == 0 || (inputs == 0 && input_count != 0U) ||
        !region_limit(flash, &flash_limit) ||
        !region_limit(ram, &ram_limit)) {
        return 0U;
    }
    result->text.start = flash_cursor;
    result->data.start = ram_cursor;
    result->bss.start = ram_cursor;
    for (i = 0U; i < input_count; ++i) {
        uint32_t next;
        if (inputs[i].kind < last_kind) {
            return 0U;
        }
        last_kind = inputs[i].kind;
        if (inputs[i].kind == SECTION_TEXT) {
            if (!add_checked(flash_cursor, inputs[i].size, flash_limit, &next)) {
                return 0U;
            }
            flash_cursor = next;
        } else if (inputs[i].kind == SECTION_DATA) {
            if (!add_checked(ram_cursor, inputs[i].size, ram_limit, &next)) {
                return 0U;
            }
            ram_cursor = next;
            result->data.end = ram_cursor;
            data_seen = 1U;
        } else if (inputs[i].kind == SECTION_BSS) {
            if (!add_checked(ram_cursor, inputs[i].size, ram_limit, &next)) {
                return 0U;
            }
            ram_cursor = next;
            result->bss.end = ram_cursor;
            bss_seen = 1U;
        } else {
            return 0U;
        }
    }
    result->text.end = flash_cursor;
    if (data_seen == 0U) {
        result->data.end = result->data.start;
    }
    if (bss_seen == 0U) {
        result->bss.end = result->data.end;
    }
    result->bss.start = result->data.end;
    if (result->bss.start > result->bss.end) {
        return 0U;
    }
    if (ranges_overlap(result->text, result->data) ||
        ranges_overlap(result->text, result->bss) ||
        ranges_overlap(result->data, result->bss)) {
        return 0U;
    }
    result->symbols_present = 1U;
    return 1U;
}

static uint32_t startup_init_data(const struct layout_result *layout,
                                  uint32_t *startup_cursor)
{
    if (layout == 0 || startup_cursor == 0 || layout->symbols_present == 0U) {
        return 0U;
    }
    if (layout->data.start > layout->data.end) {
        return 0U;
    }
    if (layout->bss.start > layout->bss.end ||
        layout->bss.start != layout->data.end) {
        return 0U;
    }
    *startup_cursor = layout->data.end;
    return 1U;
}

int main(void)
{
    static const struct input_section inputs[] = {
        { SECTION_TEXT, 32U }, { SECTION_DATA, 8U }, { SECTION_BSS, 12U }
    };
    const struct memory_region flash = { 0x1000U, 64U };
    const struct memory_region ram = { 0x8000U, 32U };
    struct layout_result layout = { 0 };
    uint32_t startup_cursor = 0U;

    assert(layout_outputs(inputs, 3U, flash, ram, &layout) == 1U);
    assert(layout.text.end - layout.text.start == 32U);
    assert(layout.data.start == 0x8000U);
    assert(layout.data.end == 0x8008U);
    assert(layout.bss.start == layout.data.end);
    assert(layout.bss.end == 0x8014U);
    assert(layout.data.start <= layout.data.end);
    assert(layout.bss.start <= layout.bss.end);
    assert(startup_init_data(&layout, &startup_cursor) == 1U);
    assert(startup_cursor == layout.data.end);

    /* 错误注入：RAM 容量不足，布局必须失败。 */
    {
        const struct memory_region tiny_ram = { 0x8000U, 8U };
        struct layout_result rejected = { 0 };
        assert(layout_outputs(inputs, 3U, flash, tiny_ram, &rejected) == 0U);
    }
    /* 错误注入：FLASH/RAM 坐标重叠，输出段不能互相覆盖。 */
    {
        const struct memory_region overlapping_ram = { 0x1010U, 32U };
        struct layout_result rejected = { 0 };
        assert(layout_outputs(inputs, 3U, flash, overlapping_ram,
                              &rejected) == 0U);
    }
    /* 错误注入：输入段顺序违反 .data -> .bss，布局必须失败。 */
    {
        static const struct input_section bad_order[] = {
            { SECTION_TEXT, 32U }, { SECTION_BSS, 12U },
            { SECTION_DATA, 8U }
        };
        struct layout_result rejected = { 0 };
        assert(layout_outputs(bad_order, 3U, flash, ram, &rejected) == 0U);
    }
    /* 错误注入：缺失边界符号，启动初始化必须拒绝。 */
    layout.symbols_present = 0U;
    assert(startup_init_data(&layout, &startup_cursor) == 0U);
    /* 错误注入：边界逆序，启动初始化必须拒绝。 */
    layout.symbols_present = 1U;
    layout.data.start = layout.data.end + 1U;
    assert(startup_init_data(&layout, &startup_cursor) == 0U);
    return 0;
}
```

代码与真实链接脚本的对应关系是：`inputs` 模拟目标文件输入段，`layout_outputs` 模拟 `SECTIONS` 合并和 `MEMORY` 容量检查，`layout_result` 模拟输出段边界和脚本符号，`startup_init_data` 模拟启动代码消费边界。示例没有 C 指针地址到 MCU 地址的转换，也没有真的调用 GNU `ld`；它只验证抽象调用流。

为让 Host Fake 对应本示例中的 `.text -> .data -> .bss` 输出顺序，`layout_outputs` 要求输入记录的 `kind` 单调不下降；这是一条显式的示例约束，不是对所有 GNU `ld` 输入文件顺序的普遍断言。

## 第 3 部分：调试、实验与复习

## 10. 常见错误

- 认为编译器已经决定了最终 Flash/RAM 地址，忽略链接阶段的输出段布局。
- 把输入段名称直接当作输出段，忽略 `SECTIONS` 的合并和顺序规则。
- 把 `MEMORY` 中的示意地址当作某个 STM32 型号的真实地址；具体型号、别名和容量必须引用官方资料并核对工程脚本。
- 把链接脚本写成“运行时执行的初始化程序”；布局发生在构建期，运行时由启动实现消费导出的边界。
- 用主机数组首地址代替链接符号，导致测试掩盖了“边界缺失、顺序错误或越界”的问题。
- 仅凭 Host Fake 断言通过，声称 ELF 已生成、固件已下载或硬件已运行。
- 在没有来源时断言 `.data`、`.bss`、`NOLOAD` 或 VMA/LMA 的具体工程语义；这些内容应标为待核对。

## 11. 调试观察点

1. 在 `layout_outputs` 入口和每次 `add_checked` 后观察游标，确认输入段被放到预期区域且边界单调增加。
2. 观察 `layout_result` 的 `data.start/data.end`，确认启动 Fake 使用的是数值边界，而不是任何主机指针。
3. 把 `tiny_ram` 容量改小，记录失败发生在第一个越界输入段；不要只检查最终返回值。
4. 把 `overlapping_ram.origin` 放进 `text` 的半开区间，确认输出段重叠检查拒绝布局。
5. 把 `layout.symbols_present` 清零，确认启动初始化在读取边界前拒绝执行。
6. 手动交换 `data` 与 `bss` 的输入顺序，确认阶段顺序检查拒绝布局，区分“布局成功”与“违反启动约定”的逻辑错误。
7. 真实工程调试时，应把脚本、链接器版本、ELF/map 报告和启动源文件作为独立证据；本课没有这些证据。

## 12. 实战实验

把代码保存为 `linker-fake.c`，在普通 Windows 主机上执行：

```powershell
gcc -std=c11 -Wall -Wextra -Wpedantic .\linker-fake.c -o .\linker-fake.exe
if ($LASTEXITCODE -eq 0) { .\linker-fake.exe; $LASTEXITCODE }
```

按以下顺序记录：

1. 先画出三条箭头：每个输入段属于哪个输出段、输出段属于哪个区域、哪些边界值传给启动 Fake。
2. 执行原始示例，记录编译器版本、命令和退出状态；若未执行，只记录纸面推理，不把它当作构建证据。
3. 把 `tiny_ram` 改为足够容纳 `.data` 但不足以容纳 `.bss` 的大小，确认越界在 `.bss` 输入处被拒绝。
4. 把 `overlapping_ram.origin` 改到 `.text` 的半开区间内，确认布局拒绝跨区域输出段重叠。
5. 把 `layout.data.start` 改成大于 `layout.data.end`，确认 `startup_init_data` 拒绝顺序错误。
6. 写出 Host Fake 能证明的两点和不能证明的两点，并保持 `hardware_verified=false`。

没有 GCC 时可只做纸面或使用其他 C11 编译器；不得把未执行命令写成“已编译”。

## 13. 自检题

1. 为什么编译成功仍不能决定代码和数据落在哪些存储区域？
2. 输入段、输出段和 `MEMORY` 区域分别由谁定义、谁持有、谁使用？
3. `data_start`/`data_end` 是运行时代码还是链接产物提供的边界？启动实现如何消费它们？
4. 为什么 Host Fake 不应把主机数组地址直接当作 STM32 物理地址？
5. 当 RAM 容量不足时，失败应发生在布局阶段还是启动运行阶段？为什么？
6. 本课中“声明、实现、实例化、组装、使用”五个动作各自发生在哪一层？

## 14. 面试题

**问：链接脚本和启动代码如何协作？**

答题要点：链接脚本在构建期把目标文件输入段合并为输出段，并将其放入 `MEMORY` 命名的区域，同时可导出段边界符号；启动代码在复位后的运行期读取这些链接产物边界，按启动约定准备数据再进入应用。具体段名、地址和 VMA/LMA 不能凭经验推断，应以目标工程脚本、工具链产物和官方资料为证据。

## 15. 延伸思考

- 如果同一输出段的输入段来自多个库，怎样在 map/ELF 证据中确认合并顺序？这是下一阶段的诊断问题，本课只提出问题。
- 为什么用半开区间 `[start, end)` 表示段边界，能减少清零或复制长度的歧义？
- 当程序需要把一份数据从非易失区域准备到 RAM 时，需要哪些额外的装载/运行地址证据？哪些内容必须等待目标工具链核对？
- 比较 F4、F7、H5、H7 时，哪些只是区域容量变化，哪些可能影响启动实现或缓存/安全约束？如何避免把型号清单变成课程目标？

## 16. 本节总结

链接脚本是构建期的布局合同：它把目标文件输入段组织成输出段，再约束输出段落入命名内存区域；脚本可以导出边界符号，把布局结果以数值接口交给启动实现。Host Fake 能验证不重叠、容量检查和边界消费的逻辑，但不能证明真实 GNU 链接产物、STM32 地址或板上执行。生成本课不会提高掌握度。

## 17. 下一步

下一课再用真实 ELF/map 产物观察布局证据和诊断方法。若要迁移到具体 F4/F7/H5/H7 型号，先收集官方参考手册、实际生成链接脚本、链接器版本和构建日志，并继续保持未核对项和 `hardware_verified=false`。

## 18. 参考资料

1. [STMicroelectronics, *STM32F3 and STM32F4 Series Cortex-M4 programming manual*](https://www.st.com/resource/en/programming_manual/pm0214-stm32f3-and-stm32f4-series-cortexm4-programming-manual-stmicroelectronics.pdf)，`PM0214`，官方版本，访问日期：2026-10-02；用于核对 Cortex-M4 启动与内存执行背景，具体器件布局待核对。
2. [STMicroelectronics, *STM32F7 series programming manual*](https://www.st.com/resource/en/programming_manual/pm0253-stm32f7-series-programming-manual-stmicroelectronics.pdf)，`PM0253`，官方版本，访问日期：2026-10-02；用于交叉核对 Cortex-M7 系列可迁移边界，具体器件布局待核对。
3. [GNU Project, *Using LD, the GNU Linker 2.9.1*](https://ftp.gnu.org/old-gnu/Manuals/ld-2.9.1/html_mono/ld.html)，GNU `ld` 2.9.1，访问日期：2026-10-02；阅读位置：*Command Language*、*Assignment: Defining Symbols*、*Memory Layout*、*Specifying Output Sections*；仅用于核对本课所用 `MEMORY`、`SECTIONS`、输入/输出段和链接符号赋值的基础语义，不据此推广版本相关的高级行为。
