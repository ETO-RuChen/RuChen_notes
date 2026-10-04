+++
title = "存储器布局：把映像、初始化与运行时边界放在同一张图上"
date = "2026-10-03T17:28:17+08:00"
lastmod = "2026-10-03T17:28:17+08:00"
summary = "把代码与数据段、启动初始化和运行时预留统一到有限存储器布局中，并用静态 Host Fake 验证区域归属、边界及重叠；其结果仅是逻辑证据，不代表真实 ELF、目标构建或硬件验证。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 17
tags = ["memory-layout", "section", "region", "vma", "lma", "elf", "map-file", "host-fake", "c11", "beginner"]
source_ids = ["st-pm0214-rev10", "gnu-ld-2-9-1-manual"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L017"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 17 课：存储器布局：把映像、初始化与运行时边界放在同一张图上

程序看起来还有“空闲空间”，仍可能因为某个区域越过边界、两个运行区相交，或者带初值数据的装载位置与运行位置没有正确衔接而失败。只看源码对象、某个段名或调试器里的一次地址显示，都不足以回答“这份程序实际怎样占用有限存储器”。

本课把已经学过的链接脚本、ELF（Executable and Linkable Format，可执行与可链接格式）、map（链接映射）文件、启动初始化、调用栈和受控运行时资源放进同一份布局中追溯。本课不假定具体开发板或 STM32 型号，不给出真实芯片地址、容量、栈大小或启动符号。第 9 节的 Host Fake（主机伪实现）只验证一张受控布局表的范围规则，不模拟链接器、存储器控制器或真实 MCU（Microcontroller Unit，微控制器）。

代码状态：主机逻辑示例；真实目标构建与上板均待验证。`hardware_verified=false`。

## 1. 本节目标

本课唯一的核心目标是：

> 学习者能把链接后的代码与数据区、启动时初始化动作及预留的运行时区域视为同一份有限存储器布局，并能根据受控布局表判断区域归属、边界和重叠风险。

完成本课后，你应能：

- 把源码对象、链接后的段、装载映像、启动动作和运行时访问串成一条证据链；
- 分别指出带初值数据的装载位置与运行位置，不把二者混成一个地址；
- 使用半开区间 `[start, end)` 判断一个范围是否属于指定区域，以及同一区域内两个范围是否重叠；
- 从静态布局表中识别有效布局、范围越界和区域重叠；
- 说明 map/ELF、链接脚本、启动实现与器件资料各能证明什么；
- 明确 Host Fake 的结果不能证明真实 STM32 工程的布局。

本课只有一个新核心概念：

> **从构建产物到运行时存储区域的映射**

`.text`、`.rodata`、`.data`、`.bss`、VMA、LMA、装载映像、零初始化、区域边界和重叠检查，都是服务这个模型的辅助术语，不是新的独立机制。

## 2. 它解决什么问题

假设一份程序包含代码、只读常量、带初值的静态对象、零初始化静态对象，以及为调用栈或受控资源池预留的空间。常见但不完整的判断有：

- “固件文件还不大，所以 RAM（Random Access Memory，随机存取存储器）一定够”；
- “`.data` 在 RAM，所以只占 RAM”；
- “`.bss` 不保存初值，所以不占空间”；
- “map 文件里每一段单独都没越界，所以整体不会相撞”；
- “主机实验通过，所以 STM32 链接脚本是对的”。

这些判断把不同阶段拆开了。真正需要回答的是：

1. 哪些内容进入装载映像？
2. 哪些内容在运行时需要一个可访问范围？
3. 启动代码要复制或清零哪些范围？
4. 调用栈、受控资源池等预留区域与静态数据是否共享同一有限区域？
5. 每个范围属于哪个区域，终点是否越界，同一区域的范围是否相交？

GNU `ld` 手册说明，`MEMORY` 命令描述链接器可使用的存储范围；当指定区域过满时，链接器报告错误。它还说明输出段的装载地址可以通过 `AT` 与运行位置分开，并由运行时初始化代码把带初值内容准备到运行地址。[2] 这给出的是 GNU `ld` 的机制，不自动证明任何具体 STM32 工程采用了相同脚本、段名或启动实现。

所以本课要解决的不是“背一张固定内存图”，而是建立一套可迁移的追溯方法：**把各阶段的证据放在同一张有限布局上，再检查归属、边界和重叠。**

## 3. 必要前置知识

本课只复核学习状态中已经完成的内容：

1. 链接脚本把目标文件的输入内容组织成输出段，并约束其位置。
2. ELF 与 map 文件记录某一次具体构建的段、符号、地址和大小，是构建期证据。
3. 进入 `main` 前，启动实现可能需要复制带初值数据并清零某个范围；具体符号与动作必须查看目标工程。
4. 自动、静态和动态存储期说明 C 对象的生命周期，不直接规定某颗 MCU 的物理地址。
5. 调用栈和显式管理的运行时资源也需要有限空间；不用动态内存不等于不会耗尽 RAM。

本课不要求也不引入中断、RTOS（Real-Time Operating System，实时操作系统）、DMA（Direct Memory Access，直接存储器访问）、缓存、MPU（Memory Protection Unit，内存保护单元）、Bootloader（引导加载程序）、具体寄存器或外设配置。

## 4. 核心原理

### 4.1 先看一份可观察结果

第 9 节程序使用两块虚拟区域：`IMAGE` 表示装载映像的有限范围，`RAM` 表示运行时范围。数值只是 Host Fake 坐标，不是任何 MCU 的地址。程序的确定输出为：

```text
valid: OK
.text owner=IMAGE [0x00001000, 0x00001060)
.rodata owner=IMAGE [0x00001060, 0x00001080)
.data.load owner=IMAGE [0x00001080, 0x000010A0)
.data.run owner=RAM [0x00002000, 0x00002020)
.bss.run owner=RAM [0x00002020, 0x00002050)
runtime.reserved owner=RAM [0x00002050, 0x00002090)
.data mapping: load=[0x00001080, 0x000010A0) -> run=[0x00002000, 0x00002020)
out_of_range: OUT_OF_RANGE
overlap: OVERLAP
zero_size: BAD_INPUT
all checks passed
```

先只观察三件事：

- 正常布局中，每个范围都完整落在所属区域内；相邻范围可以首尾相接，但不相交。
- `.data.load` 和 `.data.run` 大小相同，却位于不同区域，分别代表初值来源和运行位置。
- 故意把一个范围移到区域外、让 `.bss.run` 与 `.data.run` 相交，或给出零长度放置项，验证器都会拒绝布局。

这就是本课的最小可运行形态。下面再把它映射到构建与启动过程。

### 4.2 同一份有限布局中的四类内容

以下名称是常见约定，不是 C 标准强制名称；实际工程必须查看链接脚本与构建产物。

| 内容 | 装载映像中通常有什么 | 运行时通常需要什么 | 建立运行状态的动作 | 必须核对的证据 |
| --- | --- | --- | --- | --- |
| `.text` 与只读内容 | 代码和只读字节 | 可执行或可读取的位置 | 由装载方式与目标系统提供 | 器件资料、链接脚本、ELF/map |
| `.data` | 对象的初始字节 | 可写的运行范围 | 启动实现按工程约定复制初值 | 装载地址、运行地址、边界符号、启动文件 |
| `.bss` | 通常不为每个零值保存同等大小的初值字节 | 零初始化对象的运行范围 | 启动实现按工程约定清零 | 段范围、启动文件、ELF/map |
| 运行时预留 | 通常不是一组需要复制的初值 | 调用栈、受控资源池等有限范围 | 链接/启动配置预留，运行代码消费 | 链接脚本、map/ELF、运行观察 |

“通常”很重要。`.text`、`.rodata`、`.data`、`.bss` 是常见工具链约定；段名、属性、是否合并、是否存在，以及启动代码怎样处理它们，都以实际工程为准。[2]

### 4.3 `.data` 为什么有两个位置

带初值的可写对象同时提出两个问题：

```text
装载映像中的初值来源                 RAM 中的运行对象
IMAGE: .data.load                    RAM: .data.run
[load_start, load_end)               [run_start, run_end)
           |                                  ^
           +---- 启动实现按工程约定复制 ------+
```

- **LMA（Load Memory Address，装载内存地址）**：内容在装载映像中的位置概念。
- **VMA（Virtual Memory Address，虚拟内存地址）**：链接器为内容指定的运行地址概念。这里的“虚拟”是链接器术语，本课不引入操作系统虚拟内存。

GNU `ld` 2.9.1 手册用“relocation address”和“load address”解释 `AT`：未单独指定时二者通常相同；使用 `AT` 后可以不同，并需要运行时初始化代码完成复制。[2] 具体项目使用的链接器版本、语法和启动实现仍需逐项核对。

`.data` 因而可能同时消耗：

- 装载映像中的初值空间；
- RAM 中对象运行时的空间。

只统计其中一边，就不能描述完整映射。

### 4.4 `.bss` 为什么“映像里省字节”仍会占 RAM

零初始化静态对象在运行时仍需要真实范围。常见工程让启动代码根据边界清零这段范围，而不是在装载映像中为每个零保存同等数量的字节。这里能确定的只有责任关系：**链接结果给出范围，启动实现建立零状态，应用随后使用对象。**

“`.bss` 一定不占固件文件字节”“所有启动文件都按同样符号清零”都过于绝对。目标文件格式、输出段属性、映像格式和启动代码必须按该次工程核对。[2]

### 4.5 边界判断：使用半开区间

本课把每个范围写为 `[start, end)`：包含 `start`，不包含 `end`。若 `end = start + size`，则：

- 范围属于区域：`item_start >= region_start` 且 `item_end <= region_end`；
- 两范围不重叠：`left_end <= right_start` 或 `right_end <= left_start`；
- 两范围重叠：`left_start < right_end` 且 `right_start < left_end`；
- `[0x2000, 0x2020)` 与 `[0x2020, 0x2050)` 首尾相接，不重叠。

数学上的空区间可以用零长度表示，但本实验把每个 `Region` 和 `Placement` 都定义为实际占用的非空范围，因此零长度属于 `BAD_INPUT`。这是一条 Host Fake 输入契约，不是 GNU `ld` 或 C 语言规则。

计算 `start + size` 前必须先检查无符号整数是否溢出。否则回绕后的较小终点可能让错误范围伪装成“没有越界”。Host Fake 先检查 `size <= UINT32_MAX - start`，再做加法。

### 4.6 谁定义、谁持有、谁建立、谁使用

| 对象或规则 | 在哪里定义 | 谁持有 | 谁把它带入下一阶段 | 调用或数据如何流动 |
| --- | --- | --- | --- | --- |
| C 函数、常量、静态对象 | C 源文件中的声明与定义 | 源码模块 | 编译器把内容写入目标文件 | 源码 -> 目标文件输入段 |
| 输出段与存储器区域规则 | 具体工程的链接脚本 | 构建配置 | 链接器读取脚本并处理目标文件 | 输入段 -> 输出段 -> 指定区域 |
| 某次构建的段和符号实例 | 链接产生的 ELF/map | 构建产物 | 构建流程交付映像与符号边界 | 链接结果 -> 装载与启动证据 |
| 初始化边界与动作 | 链接脚本符号、启动 C/汇编实现 | 目标工程 | 链接器给出数值，复位路径进入启动代码 | 初值复制/范围清零 -> `main` |
| 运行时对象与预留范围 | 已建立的 RAM 状态及运行配置 | 正在运行的系统 | 启动过程交给应用 | 应用读取、修改对象并消耗预留空间 |

这里的“带入”是构建与启动阶段之间的数据交付，不是后续架构课程中的依赖注入模式。链接脚本不在复位后执行；启动代码也不负责发明段地址。

### 4.7 声明、实现、实例化、组装和使用

为了不混淆动作，本课把同一条链拆成五步：

1. **声明**：C 头文件声明对象或函数；链接脚本声明区域、输出段和边界符号的名字与规则。
2. **实现**：C 文件提供函数或对象定义；启动文件实现复制、清零等动作；链接器实现脚本所定义的布局语义。
3. **实例化**：具体函数、常量和静态对象经编译形成实际输入内容；某次链接形成具有确定地址与大小的段和符号。
4. **组装**：构建系统把目标文件、库、链接脚本和启动实现交给链接器；复位路径随后按工程约定把装载状态转换为运行状态。
5. **使用**：应用代码进入 `main` 后访问已经建立生命周期的对象，并消耗调用栈或其他预留资源。

这五步只是用于追溯存储关系。本课不把它扩展成驱动架构，也不使用函数指针、组合根或依赖注入。

## 5. 关键术语与直观模型

| 术语 | 本课中的准确含义 |
| --- | --- |
| section（段） | 链接器组织输入内容与输出布局的单位；名称和规则由工具链与工程决定。 |
| region（存储器区域） | 布局规则中一段有限地址范围；区域名字不自动等同于某颗芯片的物理块。 |
| `.text` | 常见的代码输出段名；实际属性与位置待工程核对。 |
| `.rodata` | 常见的只读内容段名；是否独立存在待工程核对。 |
| `.data` | 常见的带初值、运行时可写数据段名；可能具有不同装载位置和运行位置。 |
| `.bss` | 常见的零初始化对象运行范围名称；映像表示和清零方式待工程核对。 |
| VMA | 链接器为内容指定的运行地址概念；不是本课中的操作系统虚拟内存。 |
| LMA | 内容初值所在装载映像位置的概念；是否与 VMA 不同由实际布局决定。 |
| 装载映像 | 用来交付程序代码与初值内容的构建结果；不等于已经完成 RAM 初始化的运行状态。 |
| Map 文件 | 链接器输出的布局报告，是某一次构建的地址和大小证据。 |
| Host Fake | 用静态数据和确定规则验证逻辑，不模拟真实 MCU 或真实链接。 |

可以把完整模型压缩成一张图：

```text
C 源码对象
   |
   v
目标文件输入内容
   |
   | 链接脚本持有布局规则，链接器执行布局
   v
装载映像                         某次 ELF/map 证据
  .text / 只读内容 ----------------------+
  .data 初值 (LMA)                       |
   |                                     |
   | 启动实现按实际工程复制/清零           |
   v                                     v
RAM 运行状态 <---------------------- 段、符号、地址、大小
  .data 运行范围 (VMA)
  .bss 零初始化范围
  调用栈/受控运行时预留
   |
   v
应用访问对象，同时必须守住区域边界
```

## 6. 从输入到结果的完整流程

### 6.1 构建到运行的真实工程流程

1. 开发者在 C 文件中定义函数、常量和具有静态存储期的对象。
2. 编译器按目标格式产生输入内容；具体输入段名称受工具链与选项影响。
3. 链接器读取目标文件和链接脚本，把输入内容放入输出段与有限区域。
4. 链接产生 ELF、map 和用于装载的映像；这些文件记录该次构建的布局证据。
5. 目标复位后进入具体启动实现。
6. 启动实现依据该工程的边界符号，准备带初值数据和零初始化范围。
7. 应用进入 `main`，访问运行对象，同时使用调用栈或其他预留区域。
8. 调试者把实际器件资料、链接脚本、ELF/map、启动实现和运行观察互相核对。

第 3、4 步是构建期；第 5 至 7 步是运行期。把“链接器为 `.bss` 清零”或“启动代码决定 `.data` 放在哪”说在一起，都会混淆责任。

### 6.2 Host Fake 的调用流

```text
main 中的静态 Region/Placement 表
    -> layout_validate()
       -> 显式拒绝零长度输入
       -> checked_end() 检查加法溢出
       -> 检查每项是否属于声明的 region
       -> 检查同一 region 中任意两项是否重叠
    -> 输出 OK / OUT_OF_RANGE / OVERLAP
    -> 单独报告 .data.load 到 .data.run 的映射
```

Host Fake 中：

- `Region` 和 `Placement` 类型在示例源文件中声明；
- `valid_regions`、`valid_layout` 等静态常量是具体实例；
- `main` 持有并选择测试场景，把表和元素数量显式传给验证函数；
- `layout_validate` 只读取布局记录，不访问记录所描述的虚拟地址；
- 输出只证明给定表满足或违反了本程序的规则。

## 7. 嵌入式系统中的对应位置

### 7.1 可迁移的方法

面对 STM32F4、F7、H5 或 H7，先保持同一套方法：

1. 用具体器件的官方参考手册或数据手册确认真实存储器边界。
2. 检查实际链接脚本怎样命名区域、放置输出段和导出边界。
3. 保存同一次构建的链接器版本、命令、ELF 和 map 文件。
4. 检查实际启动文件怎样使用装载位置、运行位置和清零边界。
5. 检查运行时预留是否与静态区保持明确边界。
6. 只有具备构建、下载与运行证据时，才形成对具体板卡的结论。

可迁移的是证据链，不是某组地址或某份默认脚本。

### 7.2 当前不能给出的系列差异

本课来源只核对了 STM32 Cortex-M4 编程手册 PM0214 的适用范围，以及 GNU `ld` 的通用链接机制。[1][2] 它们不足以证明 F7、H5、H7 某个具体型号的存储器块、别名、容量、链接脚本或启动实现。因此这些系列差异全部标记为：**待拿到具体型号及对应第一方资料后核对**。

ST PM0214 可用于理解其覆盖范围内的 Cortex-M4 编程模型和地址空间背景，但不能替代具体 STM32F4 型号的参考手册或数据手册，也不能外推到 F7、H5 或 H7。[1]

## 8. 主机实验与硬件迁移边界

### 8.1 Host Fake 能证明什么

- 对给定 `Region` 和 `Placement` 表，范围终点加法受到溢出保护；
- 每个范围被检查为完整落在它声明的区域内；
- 同一区域内任意两个非空范围被检查为不重叠；
- `.data` 的装载位置与运行位置可以被分别记录和报告；
- 故意构造的越界、重叠与零长度场景会进入确定的拒绝分支。

### 8.2 Host Fake 不能证明什么

- 不能证明 GNU `ld` 已处理某份真实链接脚本；
- 不能证明某个 ELF/map 中存在示例段名或示例地址；
- 不能证明启动代码真的执行了复制或清零；
- 不能证明真实调用栈、堆或资源池的上限；
- 不能证明任一 STM32 的 Flash（闪存）、RAM、别名区或安全属性；
- 不能替代交叉编译、下载、调试和测量记录。

### 8.3 迁移到真实工程时需要收集什么

| 证据 | 用途 | 缺失时的处理 |
| --- | --- | --- |
| 具体 MCU 完整型号 | 选择正确官方资料 | 不填写地址和容量 |
| 参考手册与数据手册版本 | 确认存储器边界 | 标记待核对 |
| 工具链与链接器版本 | 确认脚本语义与报告格式 | 不套用本课版本细节 |
| 实际链接脚本 | 确认区域、段与边界符号 | 不猜段名和符号名 |
| 启动文件 | 确认复制、清零和进入 `main` 的动作 | 不声称运行状态已建立 |
| 同次 ELF/map 与构建日志 | 确认实际地址、大小及成功构建 | 不声称已编译 |
| 下载、调试或测量记录 | 确认目标运行事实 | 保持 `hardware_verified=false` |

## 9. 最小代码示例

下面是完整的单文件 C11 Host Fake。它使用固定宽度整数和静态存储，不使用动态内存、函数指针或未初始化读取，也不会解引用虚拟地址。

```c
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>

enum LayoutStatus {
    LAYOUT_OK = 0,
    LAYOUT_BAD_INPUT = 1,
    LAYOUT_ARITHMETIC_OVERFLOW = 2,
    LAYOUT_OUT_OF_RANGE = 3,
    LAYOUT_OVERLAP = 4
};

struct Region {
    const char *name;
    uint32_t start;
    uint32_t size;
};

struct Placement {
    const char *name;
    uint32_t region_index;
    uint32_t start;
    uint32_t size;
};

static uint32_t g_failures;

static uint32_t checked_end(uint32_t start, uint32_t size, uint32_t *end)
{
    if (end == NULL || size > UINT32_MAX - start) {
        return 0U;
    }

    *end = start + size;
    return 1U;
}

static uint32_t ranges_overlap(const struct Placement *left,
                               const struct Placement *right)
{
    uint32_t left_end;
    uint32_t right_end;

    if (checked_end(left->start, left->size, &left_end) == 0U ||
        checked_end(right->start, right->size, &right_end) == 0U) {
        return 0U;
    }

    return (left->start < right_end && right->start < left_end) ? 1U : 0U;
}

static enum LayoutStatus layout_validate(const struct Region *regions,
                                         uint32_t region_count,
                                         const struct Placement *items,
                                         uint32_t item_count)
{
    uint32_t item_index;
    uint32_t other_index;

    if (regions == NULL || region_count == 0U ||
        (items == NULL && item_count != 0U)) {
        return LAYOUT_BAD_INPUT;
    }

    for (item_index = 0U; item_index < item_count; ++item_index) {
        const struct Placement *item = &items[item_index];
        const struct Region *owner;
        uint32_t region_end;
        uint32_t item_end;

        if (item->region_index >= region_count) {
            return LAYOUT_BAD_INPUT;
        }

        owner = &regions[item->region_index];
        if (owner->size == 0U || item->size == 0U) {
            return LAYOUT_BAD_INPUT;
        }

        if (checked_end(owner->start, owner->size, &region_end) == 0U ||
            checked_end(item->start, item->size, &item_end) == 0U) {
            return LAYOUT_ARITHMETIC_OVERFLOW;
        }

        if (item->start < owner->start || item_end > region_end) {
            return LAYOUT_OUT_OF_RANGE;
        }
    }

    for (item_index = 0U; item_index < item_count; ++item_index) {
        for (other_index = item_index + 1U;
             other_index < item_count;
             ++other_index) {
            if (items[item_index].region_index ==
                    items[other_index].region_index &&
                ranges_overlap(&items[item_index],
                               &items[other_index]) != 0U) {
                return LAYOUT_OVERLAP;
            }
        }
    }

    return LAYOUT_OK;
}

static const char *status_name(enum LayoutStatus status)
{
    switch (status) {
        case LAYOUT_OK:
            return "OK";
        case LAYOUT_BAD_INPUT:
            return "BAD_INPUT";
        case LAYOUT_ARITHMETIC_OVERFLOW:
            return "ARITHMETIC_OVERFLOW";
        case LAYOUT_OUT_OF_RANGE:
            return "OUT_OF_RANGE";
        case LAYOUT_OVERLAP:
            return "OVERLAP";
        default:
            return "UNKNOWN";
    }
}

static void print_placement(const struct Region *regions,
                            const struct Placement *item)
{
    uint32_t end = item->start + item->size;

    (void)printf("%s owner=%s [0x%08" PRIX32 ", 0x%08" PRIX32 ")\n",
                 item->name,
                 regions[item->region_index].name,
                 item->start,
                 end);
}

static void expect_status(const char *scenario,
                          enum LayoutStatus actual,
                          enum LayoutStatus expected)
{
    (void)printf("%s: %s\n", scenario, status_name(actual));
    if (actual != expected) {
        g_failures++;
    }
}

int main(void)
{
    static const struct Region valid_regions[] = {
        { "IMAGE", UINT32_C(0x00001000), UINT32_C(0x00000200) },
        { "RAM",   UINT32_C(0x00002000), UINT32_C(0x00000180) }
    };
    static const struct Placement valid_layout[] = {
        { ".text",            0U, UINT32_C(0x00001000), UINT32_C(0x60) },
        { ".rodata",          0U, UINT32_C(0x00001060), UINT32_C(0x20) },
        { ".data.load",       0U, UINT32_C(0x00001080), UINT32_C(0x20) },
        { ".data.run",        1U, UINT32_C(0x00002000), UINT32_C(0x20) },
        { ".bss.run",         1U, UINT32_C(0x00002020), UINT32_C(0x30) },
        { "runtime.reserved", 1U, UINT32_C(0x00002050), UINT32_C(0x40) }
    };
    static const struct Placement out_of_range_layout[] = {
        { ".data.run",        1U, UINT32_C(0x00002000), UINT32_C(0x20) },
        { "runtime.reserved", 1U, UINT32_C(0x00002170), UINT32_C(0x20) }
    };
    static const struct Placement overlap_layout[] = {
        { ".data.run", 1U, UINT32_C(0x00002000), UINT32_C(0x20) },
        { ".bss.run",  1U, UINT32_C(0x00002010), UINT32_C(0x30) }
    };
    static const struct Placement zero_size_layout[] = {
        { ".data.run", 1U, UINT32_C(0x00002000), UINT32_C(0x00) }
    };
    enum LayoutStatus status;
    uint32_t index;
    uint32_t load_end;
    uint32_t run_end;

    status = layout_validate(valid_regions, 2U, valid_layout, 6U);
    expect_status("valid", status, LAYOUT_OK);
    if (status == LAYOUT_OK) {
        for (index = 0U; index < 6U; ++index) {
            print_placement(valid_regions, &valid_layout[index]);
        }

        load_end = valid_layout[2].start + valid_layout[2].size;
        run_end = valid_layout[3].start + valid_layout[3].size;
        (void)printf(".data mapping: load=[0x%08" PRIX32
                     ", 0x%08" PRIX32 ") -> run=[0x%08" PRIX32
                     ", 0x%08" PRIX32 ")\n",
                     valid_layout[2].start,
                     load_end,
                     valid_layout[3].start,
                     run_end);
    }

    status = layout_validate(valid_regions, 2U, out_of_range_layout, 2U);
    expect_status("out_of_range", status, LAYOUT_OUT_OF_RANGE);

    status = layout_validate(valid_regions, 2U, overlap_layout, 2U);
    expect_status("overlap", status, LAYOUT_OVERLAP);

    status = layout_validate(valid_regions, 2U, zero_size_layout, 1U);
    expect_status("zero_size", status, LAYOUT_BAD_INPUT);

    if (g_failures == 0U) {
        (void)printf("all checks passed\n");
        return 0;
    }

    (void)printf("failures=%" PRIu32 "\n", g_failures);
    return 1;
}
```

### 9.1 代码分层、依赖方向和生命周期

这是教学实验层的单文件程序：

```text
场景与静态表 main
  -> 布局规则 layout_validate
     -> 无符号边界运算 checked_end
  -> 主机标准输出
```

- 依赖方向从实验场景指向验证规则；验证规则不依赖 STM32 HAL（硬件抽象层）或任何硬件地址。
- 所有区域和布局实例都是 `static const`，具有静态存储期，程序全程存在。
- `layout_validate` 只在调用期间持有指向表的参数，不保存指针。
- 虚拟范围只是整数记录，不对应可解引用的主机地址。
- 公开可见的数据字段和计数均使用固定宽度整数；程序不申请动态内存。

### 9.2 Windows 主机构建

在普通 Windows 主机上，将代码保存为 `memory_layout_fake.c`，任选本机已有编译器：

```powershell
gcc -std=c11 -Wall -Wextra -Wpedantic -Werror memory_layout_fake.c -o memory_layout_fake.exe
./memory_layout_fake.exe
```

或：

```powershell
clang -std=c11 -Wall -Wextra -Wpedantic -Werror memory_layout_fake.c -o memory_layout_fake.exe
./memory_layout_fake.exe
```

验收条件是编译退出码为 `0`，程序退出码为 `0`，并得到第 4.1 节所示结果。必须记录实际编译器版本、命令和退出码后，才能声称该次主机构建成功；即使主机构建成功，仍不构成 STM32 硬件验证。

## 10. 常见错误

### 10.1 把段名当成 C 语言保证

错误：“C 标准规定代码在 `.text`，零初始化变量在 `.bss`。”

正确做法：把这些名字称为常见工具链约定，再从实际目标文件、链接脚本和 ELF/map 核对。C 对象的语言属性与链接器怎样命名输出段不是同一层规则。

### 10.2 只看总空闲量，不看连续边界

两个区域各自有剩余，不代表某个指定区域能容纳一个范围。布局检查首先关心“属于哪个区域”和“范围终点在哪里”，不能把不同区域的零散余量相加后得出可放置结论。

### 10.3 把 `.data` 只算一次

只看 RAM 会漏掉装载映像中的初值，只看固件映像会漏掉运行时可写范围。应分别记录 LMA 和 VMA，再核对启动实现怎样连接两者。[2]

### 10.4 认为 `.bss` 不占存储器

即使零值不以同等字节数出现在装载映像中，运行对象仍需要范围，并且启动过程需要建立规定的初始状态。实际表示方式和清零动作要从构建产物与启动文件确认。

### 10.5 只检查相邻表项

如果布局表没有先按地址排序，只检查数组中的相邻项可能漏掉交叉范围。示例对同一区域内所有项做两两检查；对更大数据集可以先排序再检查，但那是实现优化，不改变本课规则。

### 10.6 先加法，后检查溢出

`end = start + size` 可能发生无符号回绕。应先验证 `size <= UINT32_MAX - start`，再计算终点。

### 10.7 把相邻误判为重叠

使用半开区间后，左区终点等于右区起点表示恰好相邻。若用闭区间混算，很容易多算或少算一个地址单位。

### 10.8 把 Host Fake 当成 ELF 解析器

示例没有读取 ELF，没有执行链接脚本，也没有读取真实地址。修改表格只是在修改测试输入，不能声称改变了真实固件布局。

### 10.9 从 PM0214 外推所有 STM32

PM0214 的标题和适用范围明确指向其覆盖的 Cortex-M4 MCU/MPU 编程背景。[1] 它不能单独证明 F7、H5、H7 或具体型号的存储器布局。

## 11. 调试观察点

### 11.1 在验证入口先看四个量

在 `layout_validate` 设置断点，先观察：

- `region_count` 与 `item_count` 是否和静态表一致；
- 当前 `item->region_index` 是否落在区域表范围内；
- `item->start` 与 `item->size` 是否为预期场景；
- `region_end` 和 `item_end` 是否在完成溢出检查后计算。

### 11.2 观察越界分支

`RAM` 的半开终点是 `0x2180`。错误项 `[0x2170, 0x2190)` 的起点仍在 `RAM` 内，但终点越过区域终点。这个场景用于纠正“起始地址有效就算有效”的误解。

### 11.3 观察重叠分支

错误场景中：

```text
.data.run [0x2000, 0x2020)
.bss.run  [0x2010, 0x2040)
```

两者满足 `left.start < right.end` 且 `right.start < left.end`，所以相交。把 `.bss.run` 起点改成 `0x2020` 后，两者只相邻，应通过重叠检查。

### 11.4 真实工程的四向核对

拿到目标工程后，对同一范围同时看：

1. 链接脚本中的区域与放置规则；
2. map 文件中的段起点、大小和边界符号；
3. ELF 工具显示的段与装载信息；
4. 启动文件实际读取的符号和执行的循环。

若四者名称或数值对不上，先确认它们是否来自同一次构建。不要先修改脚本，也不要用调试器单次显示覆盖构建证据。

### 11.5 当前硬件观察边界

本课没有具体 MCU、开发板、调试器、目标 ELF/map、构建日志、下载记录或测量数据。因此没有可报告的真实寄存器、地址、容量或运行结果，`hardware_verified` 保持 `false`。

## 12. 实战实验

### 实验 A：复现有效布局与三个拒绝分支

目标：验证最小 Host Fake 的确定结果。

步骤：

1. 把第 9 节代码保存为 `memory_layout_fake.c`。
2. 记录编译器名称和 `--version` 输出。
3. 使用 `-std=c11 -Wall -Wextra -Wpedantic -Werror` 构建。
4. 记录编译命令、编译退出码、程序退出码和完整输出。
5. 对照第 4.1 节，确认正常布局为 `OK`，三个错误分别为 `OUT_OF_RANGE`、`OVERLAP` 和 `BAD_INPUT`。

验收：没有警告被忽略；程序退出码为 `0`；能说明该结果只适用于 Host Fake 输入表。

### 实验 B：区分相邻与重叠

目标：用半开区间判断边界。

步骤：

1. 保持 `.data.run` 为 `[0x2000, 0x2020)`。
2. 依次把 `.bss.run` 起点设为 `0x201F`、`0x2020`、`0x2021`，大小保持非零。
3. 预测每次结果，再运行验证。
4. 解释为什么 `0x2020` 是相邻而不是重叠。

验收：`0x201F` 被拒绝；`0x2020` 和 `0x2021` 不因这两个范围相交而被拒绝；答案使用 `[start, end)` 说明。

### 实验 C：证明只检查起点不够

目标：观察“起点在区域内、终点在区域外”的越界。

步骤：

1. 找出 `RAM` 的起点、大小和半开终点。
2. 保持错误项起点为 `0x2170`，将大小依次设为 `0x10`、`0x11`、`0x20`。
3. 先手算终点，再运行。
4. 说明哪一项恰好贴住边界，哪一项开始越界。

验收：大小 `0x10` 的终点为 `0x2180`，可落在区域内；更大的范围越界。

### 实验 D：增加算术溢出场景

目标：验证边界加法不会回绕后伪装成有效范围。

步骤：

1. 新增一个区域或测试项，使 `start` 接近 `UINT32_MAX`。
2. 令 `size > UINT32_MAX - start`。
3. 预期返回 `ARITHMETIC_OVERFLOW`。
4. 不解引用该数值，也不把它称为真实硬件地址。

验收：程序拒绝场景；答案能说明为什么检查必须发生在加法前。

### 实验 E：纸面追溯一个带初值对象

目标：把源码、链接和启动证据连起来，不修改真实工程。

步骤：

1. 在纸上写一个虚构对象名 `config_word`，只作为追踪标签。
2. 画出“源码定义 -> 目标文件输入内容 -> 输出段 -> `.data` 装载范围 -> `.data` 运行范围 -> 启动复制 -> `main` 使用”。
3. 在每条箭头旁写出需要的真实证据：目标文件/ELF、链接脚本、map、启动文件。
4. 圈出目前缺失的证据，不填写虚构地址。

验收：装载位置与运行位置分开；没有把段名当作 C 标准保证。

### 可选实验 F：核对自己的真实 STM32 工程

只有在已有具体工程时执行：

1. 记录完整 MCU 型号、开发板、工具链和链接器版本。
2. 只读查看链接脚本、启动文件、同次 ELF/map 和构建日志。
3. 从器件官方资料确认相关存储器边界。
4. 建立自己的区域表，逐项填写来源路径或文档章节。
5. 检查 `.data` 的装载/运行范围、`.bss` 范围和运行时预留。
6. 不烧录、不修改 IDE/CubeMX 全局配置；没有运行证据时只形成构建期结论。

验收：每个地址和大小都有来源；不同构建的文件没有混用；结论明确区分构建期与运行期。

## 13. 自检题

1. 为什么“固件映像还有空间”不能证明 RAM 布局安全？
2. `.data` 的 LMA 与 VMA 分别回答什么问题？
3. `.bss` 没有逐字节初值时，为什么运行时仍需要空间？
4. `[0x1000, 0x1020)` 与 `[0x1020, 0x1030)` 是否重叠？
5. 为什么计算 `end = start + size` 前要检查溢出？
6. 谁持有存储器区域和输出段规则？谁在运行时执行初始化动作？
7. map 文件能否单独证明启动代码已经执行？
8. Host Fake 的 `IMAGE` 和 `RAM` 是否代表某颗 STM32 的真实地址？
9. 要把本课方法迁移到 F7，需要新增哪些证据？
10. 生成这篇课程后，为什么 mastery 不能自动提高？

参考要点：

1. 映像空间和 RAM 空间承担不同内容，运行时预留还可能与静态范围竞争边界。
2. LMA 追踪初值的装载位置，VMA 追踪内容运行时使用的位置。
3. 对象在运行时仍必须有可访问范围，并由具体启动实现建立规定初态。
4. 不重叠；半开区间允许终点与下一范围起点相等。
5. 无符号回绕可能产生较小终点，让越界范围通过错误检查。
6. 工程链接脚本持有布局规则；具体启动 C/汇编代码执行运行时动作。
7. 不能；它是构建期证据，不是运行记录。
8. 不是；它们只是 Host Fake 的静态坐标。
9. 具体型号资料、实际脚本、启动文件、工具链版本、同次 ELF/map 和所需运行记录。
10. 掌握度只能由用户答案、实验或复习结果提高，生成资产不是学习证据。

## 14. 面试题

### 14.1 为什么 `.data` 可能同时占用非易失性映像和 RAM

建议答案：带初值可写对象需要保存初始字节，又需要在运行时存在于可写位置。链接布局可能为它提供不同的装载地址和运行地址，启动实现再按工程约定复制。具体位置、符号与动作必须从实际链接脚本、ELF/map 和启动文件确认。[2]

### 14.2 `.bss` 不占 RAM，对吗

建议答案：不对。常见情况下，它不需要在装载映像中保存与运行范围等大的零字节，但零初始化对象运行时仍占范围。映像表示与清零方式属于具体工具链和启动实现事实。

### 14.3 如何判断两个内存范围是否重叠

建议答案：先用无溢出的方式得到两个半开区间终点。若 `a.start < b.end` 且 `b.start < a.end`，则相交；终点恰好等于另一范围起点时不相交。

### 14.4 链接器报区域未溢出，是否就能证明运行时不会内存不足

建议答案：不能。链接器能检查它看得到并被脚本约束的构建期布局；实际调用栈峰值、受控资源池使用和某些运行路径还需要额外静态分析或运行证据。还要确认预留规则本身正确。

### 14.5 如何审查一份陌生 STM32 工程的存储器布局

建议答案：先确定具体器件与官方资料，再记录工具链版本；对照链接脚本、同次 ELF/map 和启动文件，分别追踪代码、只读内容、`.data` 装载/运行范围、`.bss` 和运行时预留；最后根据构建与运行证据限定结论，不从默认工程名或段名猜地址。

### 14.6 VMA 中的“虚拟”是否表示 Cortex-M 正在使用操作系统虚拟内存

建议答案：不是。这里是链接器描述内容运行地址的术语。本课没有引入操作系统虚拟内存，也不能从 VMA 一词推断存在地址转换。

## 15. 延伸思考

1. 如果两个范围属于不同区域，但数值坐标恰好相同，验证器应该怎样理解“重叠”？这取决于区域是否代表独立地址空间还是同一物理空间的别名，真实工程需要什么资料才能判断？
2. 为什么把所有运行时预留简单写成一个“大空洞”可能掩盖实际峰值风险？
3. 若 map 文件和调试器中的符号地址不同，应该先核对哪些构建标识和装载事实？
4. 如果 `.data` 的装载范围和运行范围大小不同，应当停止在哪一步，检查哪些脚本与启动约定？
5. 后续 Device Framework 中的静态对象、缓冲区和接口实例，怎样沿本课证据链追溯存储占用？这里只思考存储归属，不提前设计架构。
6. 在不使用动态内存的前提下，如何为多个静态缓冲区保留清晰边界，并让 map/ELF 提供可审计证据？

## 16. 本节总结

本课只有一个核心模型：**从构建产物到运行时存储区域的映射**。

```text
源码对象
  -> 编译后的输入内容
  -> 链接脚本约束下的输出段与区域
  -> ELF/map 和装载映像
  -> 启动复制/清零等初始化动作
  -> RAM 中的运行对象与运行时预留
  -> 应用访问
```

检查布局时，不只问“总共多大”，还要逐项问：

- 它属于哪个有限区域？
- 起点和大小来自哪份证据？
- 终点计算是否溢出或越界？
- 与同一区域的其他范围是否重叠？
- 它是装载位置、运行位置，还是二者都有？
- 谁建立运行状态，谁随后使用它？

Host Fake 让这些判断在普通 Windows 主机上可观察，但它不生成 ELF、不执行启动代码，也不证明硬件事实。真实 STM32 结论必须由具体器件资料、实际链接脚本、同次 ELF/map、启动实现和运行记录共同支撑。

## 17. 下一步

本课完成 `startup-linking-memory` 阶段的 `memory-layout` 主题。开始下一阶段前，至少完成实验 A，并能不看正文回答：

1. `.data` 为什么可能有装载与运行两个位置；
2. 为什么 `.bss` 和运行时预留必须放进同一份 RAM 边界分析；
3. 如何用半开区间检查归属和重叠；
4. Host Fake、map/ELF、启动文件和硬件资料分别能证明什么。

生成本课程本身不会提高掌握度。本次任务不修改 `config/learning-state.toml` 或任何 mastery 值；只有用户答案、实验结果或复习记录可作为后续状态变化证据。

## 18. 参考资料

[1] STMicroelectronics, *STM32 Cortex-M4 MCUs and MPUs programming manual*, PM0214 Rev 10, March 2020. 用于限定其覆盖范围内的 Cortex-M4 编程模型和存储器背景；不能替代具体器件参考手册，也不外推到 F7、H5 或 H7。  
https://www.st.com/resource/en/programming_manual/pm0214-stm32f3-and-stm32f4-series-cortexm4-programming-manual-stmicroelectronics.pdf

[2] GNU Project, *Using LD, the GNU Linker 2.9.1*, 1998，重点参阅 “Memory Layout”、`LOADADDR` 与输出段 `AT (ldadr)` 说明。用于核对 GNU `ld` 的区域容量、装载地址与运行地址机制；真实工程必须以实际链接器版本和脚本复核。  
https://ftp.gnu.org/old-gnu/Manuals/ld-2.9.1/html_mono/ld.html

来源访问日期：2026-10-03。Arm DDI0403 计划入口本次访问返回 403，未用于支撑正文结论。本文没有使用来源政策之外的博客或第三方完整源码。
