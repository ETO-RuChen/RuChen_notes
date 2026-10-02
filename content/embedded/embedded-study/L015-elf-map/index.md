+++
title = "ELF 与 map：从链接产物追溯布局证据"
date = "2026-10-02T20:54:52+08:00"
lastmod = "2026-10-02T20:54:52+08:00"
summary = "把同一次目标链接产生的 ELF 与 map 作为互补证据，追溯输出段、符号、地址和大小，同时区分构建期布局、装载事实与运行期事实。"
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 15
tags = ["elf", "map-file", "section", "segment", "symbol-table", "gnu-binutils", "host-fake", "c11", "beginner"]
source_ids = ["st-um2609-rev18", "gnu-binutils-2-47", "gnu-ld-2-9-1-manual"]
generated_with_ai = true
hardware_verified = false
lesson_id = "L015"
+++

<!-- generated-by: EmbeddedStudy -->
> 本文由 AI 辅助生成并经自动审查；尚未完成真实硬件验证。涉及具体芯片、时序和电气行为时，请以文末第一方资料和实际测试为准。

# 第 15 课：ELF 与 map：从链接产物追溯布局证据

链接已经完成，并不等于问题已经回答：某个函数或静态对象最终在哪里？一个输出段有多大？它为何出现在那个地址？仅看源码通常不够，仅看到“构建成功”也不够。我们需要检查链接过程留下的证据。

本课只推进一个核心目标：**学习者能把同一次目标链接产生的 ELF 与 map 当作互补证据，追溯输出段、符号和地址布局，并明确二者不能证明什么。**

本课不假定具体开发板、STM32 型号或交叉工具链，也不填写真实芯片地址。必做实验是普通 Windows 主机可运行的 Host Fake（主机伪实现）；真实 ELF 检查是可选层，必须先由工具确认文件格式。课程没有构建、下载、测量或上板记录，因此 `hardware_verified=false`，所有命令均是待学习者执行的实验步骤。

## 第 1 部分：先建立证据模型

## 1. 本节目标

完成本课后，你应能：

- 解释 ELF（Executable and Linkable Format，可执行与可链接格式）与 map 文件分别解决什么问题；
- 使用同一次链接的 ELF 与 map 追踪“源码对象 -> 目标文件输入 -> 输出段 -> 地址/大小”的证据链；
- 区分节（section）、段（segment）和符号（symbol），不把三者混为一谈；
- 先检查文件格式和工具版本，再选择 `readelf`、`objdump` 或 `nm`；
- 识别缺失符号、大小不一致、区间重叠和证据不属于同一次链接等问题；
- 清楚说明 ELF/map 能证明构建期布局，却不能单独证明装载成功或运行期执行正确。

本课的两个新核心概念与 `plan.json` 完全一致：

1. **ELF 与 map 的互补证据视图**
2. **从链接结果追溯布局规则**

## 2. 它解决什么问题

假设源码中有一个函数 `app_accumulate`、一个具有外部链接的对象 `g_sample_counter`，以及一个只在 `app.c` 内可见的静态对象 `calibration_table`。链接完成后，我们会追问：

- 这些名字是否真的进入最终产物？
- 它们的链接期值或地址是什么？大小是多少？
- 它们属于哪个输出节？该输出节又有多大？
- 是哪个目标文件贡献了对应内容？
- 链接脚本的哪条布局规则可能导致这个结果？

ELF 与 map 提供不同观察角度：

- **ELF 是机器可读取的链接产物。** 它可以承载文件头、节头、程序头和符号表等信息；具体包含哪些表取决于文件种类、链接选项以及是否做过裁剪。GNU Binutils 2.47 手册的 `readelf` 章节分别记录了文件头、程序头（段）、节头和符号表的检查选项；同一发行包还记录 `nm` 用于列出目标文件符号、`objdump` 用于显示目标文件信息。[2]
- **map 文件是链接器生成的布局报告。** 它通常更适合回答“哪些输入内容被放到哪里、由哪个目标文件或库贡献、某个符号怎样出现在布局中”。但 map 不是 ELF 标准的一部分，其栏目、措辞和细节依赖链接器及版本。GNU `ld` 的固定版本手册记录了生成 map 报告的选项；实际命令必须再用本机版本的 `--help` 核对。[3]

两者互补，却不能互相替代：ELF 是后续工具可直接解析的产物；map 是链接器对本次布局过程给出的报告。只拿一个旧 map 去解释一个新 ELF，证据链会失效；只看 ELF，也可能难以直接回答某个输入目标文件为何贡献到该处。

## 3. 必要前置知识

本课只使用学习状态中已经完成的内容：

- `compiler`：源文件先被翻译为目标文件；
- `make-cmake`：构建命令决定实际输入和选项；
- `linkage`：同名标识符能否跨翻译单元引用，与符号是否可在多个文件间关联有关；
- `reset-sequence`、`vector-table`、`startup`：目标启动会消费链接结果，但启动成功需要额外运行期证据；
- `linker-script`：输入节按规则形成输出节，链接边界符号可供启动实现使用。

简短复核：链接脚本是构建期规则，不会在复位后“运行”；启动实现消费链接产生的地址或边界。今天不学习新的链接脚本语法，也不学习重定位、动态装载、寄存器、RTOS（实时操作系统）或 DMA（直接存储器访问）。

## 4. 核心原理

### 4.1 核心概念一：ELF 与 map 的互补证据视图

先看最小关系：

```text
源文件 + 构建选项 + 链接脚本 + 库
                  |
                  v
                链接器
             /            \
            v              v
     ELF 链接产物       map 布局报告
     机器可解析视图      人可阅读的链接过程视图
            \              /
             v            v
          对同一符号、输出节、地址和大小交叉核对
```

“同一次链接”是互证成立的前提。文件名相似、时间接近或扩展名相同都不充分。实验记录至少应保存：完整构建命令、工具版本、链接脚本、输入文件清单，以及同时产出的 ELF/map。需要更强审计时，可以再保存文件哈希；本课不把哈希提升为新的核心概念。

| 问题 | ELF 更擅长回答 | map 更擅长回答 | 需要怎样互证 |
| --- | --- | --- | --- |
| 文件是不是 ELF | ELF 文件头可由识别工具检查 | map 不能证明另一个文件格式 | 先运行格式检查，不能看扩展名猜测 |
| 输出节地址与大小 | 节表存在时可读取相应记录 | 通常列出输出节地址与大小 | 名称、地址、大小应在允许差异内一致 |
| 符号是否存在 | 符号表存在时可查名称、值、大小和绑定等字段 | 可能列出符号及布局位置 | 先确认符号未被裁剪，再比较值和所属范围 |
| 谁贡献了内容 | 可进一步检查节和符号，但来源链未必直观 | 通常更直接展示输入目标文件/库与输入节 | 从 map 找贡献者，再回 ELF 核对最终结果 |
| 面向装载的段 | 程序头存在时可显示段及其范围 | map 不一定完整表达 ELF 程序头 | 以 ELF 程序头为直接证据，map 只作旁证 |
| 代码是否在板上执行 | 不能单独证明 | 不能单独证明 | 还需下载、调试、日志或测量证据 |

这里多次使用“可以”“通常”，是因为 GNU Binutils 2.47 手册明确把程序头、节头和符号表的显示都限定为“文件存在相应内容时”；map 格式也由具体链接器决定。检查前必须记录实际工具版本，你的 STM32 工具链可能集成另一版本。[2]

### 4.2 节、段和符号不能混用

这三个词都可能出现地址，却代表不同对象：

- **节（section）**：目标文件或链接产物中组织代码、数据、元数据的单位。链接脚本中的“输出节”通常会反映到链接产物的节视图，但具体名称和属性由实际工程决定。
- **段（segment）**：ELF 程序头提供的另一种观察视角，使用 `readelf -l` 检查；GNU Binutils 手册把它与 `readelf -S` 显示的节头分开记录。实际文件是否含程序头，以及节如何映射到段，必须查看该文件并结合目标 ABI（Application Binary Interface，应用二进制接口）核对；本课不预设映射数量关系。
- **符号（symbol）**：名字及其链接期属性/值的记录。函数、对象或链接脚本导出的边界都可能有对应符号，但符号表可能被裁剪，符号值也必须结合文件类型、目标架构和所属节解释。

因此，看到 `.text` 不能直接说“它就是一个装载段”；看到符号地址也不能直接说“CPU 已经从这里执行”。`readelf -S`、`readelf -l`、`readelf -s` 分别提供不同视角，选项含义和输出格式应以实际安装版本的 `readelf --help` 为准。[2]

这里采用的是读取工具输出所需的最小区分，不替代目标 ABI 规范。本次核对时，计划中的 Arm `IHI 0044` 官方页面返回 `403 Forbidden`，因此它没有被写入 `lesson.json.sources`；Arm 专属 ELF 字段、节到段的具体映射约束均标记为**待核对**，不能由本课推广到某个 STM32 工程。

### 4.3 每个核心对象在哪里、由谁持有、谁提供、谁使用

| 对象 | 定义位置 | 谁持有 | 谁提供或产生 | 谁使用，数据如何流动 |
| --- | --- | --- | --- | --- |
| 源码函数/对象 | `.c` 中的定义，跨文件声明在 `.h` | 源码仓库 | 编译器把它们翻译进目标文件 | 链接器读取目标文件中的节与符号信息 |
| 链接脚本规则 | 工程选定的链接脚本 | 构建配置 | 构建命令把脚本交给链接器 | 链接器据此组织输出节和符号值 |
| 输出节 | 链接脚本规则与实际输入共同决定 | 最终链接产物 | 链接器实例化具体地址、大小和属性 | `readelf`/`objdump`、调试器和后续映像工具读取 |
| 符号记录 | 源码定义、汇编、库或链接脚本边界 | 目标文件/最终产物中的符号表（若保留） | 编译器、汇编器和链接器共同形成 | `nm`、`readelf`、调试器或启动实现使用 |
| ELF | 本次链接的输出格式与内容 | 构建产物目录 | 链接器产生 | 二进制检查工具、下载工具或调试器读取；后两者的实际行为待目标工程核对 |
| map 报告 | 链接命令请求的报告输出 | 构建产物目录 | 链接器在本次链接中同时产生 | 开发者追溯输入贡献、输出布局和容量 |
| 检查工具 | 工具链安装目录 | 主机工具链 | 构建环境提供具体版本 | 开发者用命令读取 ELF/map，不改变板上状态 |

表中的“提供”只表示谁把输入交给下一步，不是在引入后续架构课程中的依赖注入概念。

### 4.4 声明、实现、实例化、组装和使用

即使本课不是架构课，也要把五个动作分清：

1. **声明**：`app.h` 用 `extern` 声明外部对象和函数；链接脚本声明输出节规则与可选边界名字。
2. **实现**：`app.c` 定义对象并实现函数；链接器实现其格式和布局算法。
3. **实例化**：编译后形成具体目标文件记录；链接时形成本次构建的具体节、段和符号记录。
4. **组装**：构建命令把目标文件、库和脚本交给链接器，同时请求 ELF 与 map 输出。
5. **使用**：检查工具读取产物，开发者据此诊断；目标启动或调试工具是否使用某些地址，必须由对应工程和运行记录证明。

把这五步混在一起，常见后果是把源码声明当成“最终符号必然存在”，或把链接地址当成“运行已经到达该地址”。

### 4.5 核心概念二：从链接结果追溯布局规则

追溯不是从一张巨大报告漫无目的地搜索，而是沿固定问题向前和向后走：

```text
源码定义/链接脚本规则
  -> 编译得到哪个目标文件、哪个输入节
  -> map 显示它被哪个输出节接纳
  -> ELF 显示最终输出节、符号、地址和大小
  -> 回到构建命令确认输入、脚本和工具版本
```

也可以从异常反向追：

```text
ELF 中输出节大小异常
  -> map 中找该输出节的输入贡献者
  -> 找到异常目标文件/库
  -> 回到源码对象或构建选项
  -> 修正后重新链接，并只比较新一对 ELF/map
```

一次追溯要同时记录“观察到什么”和“它不能证明什么”。例如：

- ELF 符号表出现 `g_sample_counter`，能证明这份文件保留了对应符号记录；不能证明板上 RAM 已按预期初始化。
- map 把某输入节列在某输出节下面，能证明该链接器报告了这次放置；不能证明下载工具已把映像写入目标。
- ELF 的程序头显示某个可装载范围，能证明文件中存在该装载描述；不能证明实际装载器已经执行了它。

## 5. 关键术语与直观模型

| 术语 | 本课中的准确含义 |
| --- | --- |
| ELF | 可执行与可链接格式；先由文件头检查确认，不由扩展名决定。 |
| map 文件 | 链接器生成的映像布局报告；不是 ELF 的替代品，也没有统一的 ELF 表结构。 |
| 目标文件 | 编译或汇编输出、供链接器继续处理的输入；格式取决于工具链。 |
| 节（section） | 文件内容的组织单位；本课重点观察链接后的输出节。 |
| 段（segment） | ELF 程序头描述的装载视角；不要与节或 MCU 存储区域混同。 |
| 符号表（symbol table） | 名称及其链接期属性/值的记录集合；可能被裁剪。 |
| 地址 | 报告中的数值字段，必须结合文件类型、目标架构和链接脚本解释。 |
| 大小 | 节或符号占用量的记录；是否可用、如何计算依工具和对象类型而定。 |
| 对齐（alignment） | 地址或大小满足的边界要求；本课只观察结果，不引入新脚本语法。 |
| GNU Binutils | GNU 的二进制工具集合，包括 `readelf`、`objdump`、`nm` 等。[2] |
| 交叉工具链 | 在主机上生成或检查另一目标架构产物的工具链；本课不假定已安装。 |
| Host Fake | 用受控记录验证追溯逻辑，不模拟 Cortex-M 或证明真实硬件。 |

## 6. 从输入到结果的完整流程

### 6.1 最小直观流程

1. 在 `app.c` 定义函数、外部对象和文件内静态对象。
2. 编译器把源码变成目标文件；此时还不是最终布局。
3. 构建命令选择目标文件、库、链接脚本和链接器选项。
4. 链接器产生最终产物，并在被要求时同时产生 map。
5. 先用文件头检查确认产物确为 ELF。
6. 从 ELF 中读输出节和符号，从 map 中读输入贡献与布局。
7. 对名称、地址、大小和范围做交叉核对。
8. 回到源码、脚本和构建命令解释原因。
9. 将结论限制在构建期；装载和运行另找证据。

### 6.2 三条证据边界

| 层次 | 可以使用的证据 | 本课状态 |
| --- | --- | --- |
| 构建期布局 | 编译/链接命令、ELF、map、链接脚本、工具版本 | 本课教你如何收集；仓库没有本次真实构建记录 |
| 装载事实 | 下载工具日志、校验结果、目标存储器读取 | 未提供，不能声称已装载 |
| 运行期事实 | 调试停点、日志、测试输出、测量或故障记录 | 未提供，不能声称已运行 |

## 7. 嵌入式系统中的对应位置

在实际 STM32 工程中，ELF/map 位于“编译和链接”之后、“下载与运行验证”之前。STM32CubeIDE 是 STM32 软件开发工具环境，具体版本、工具链组合和工程输出位置应按实际安装与工程设置核对。[1]

F4、F7、H5、H7 之间可迁移的机制只有这一条：**读取实际构建产物建立证据链**。不同系列和具体型号的存储器地址、容量、别名、安全属性、缓存影响、段名、启动文件和链接脚本都不能由本课猜测。获得具体工程后，应以该器件官方参考资料、工程脚本、实际构建命令与同次 ELF/map 为准。

## 8. 主机实验与硬件迁移边界

实验分两层：

1. **必做：结构化证据 Host Fake。** 在普通 Windows 主机上，用静态数组分别模拟 ELF 视图和 map 视图，验证正常互证、缺失符号、大小不一致和区间重叠。它不解析真实文件，所以不依赖 ELF 工具链。
2. **可选：真实 ELF 观察。** 只有本机已有能生成 ELF 的工具链，并且 `readelf -h` 确认输出确为 ELF 时才继续。Windows 原生 GCC 可能生成 PE/COFF（Windows 可执行文件/公共对象文件格式）；即使把文件命名为 `.elf`，内容也不会因此变成 ELF。

Host Fake 可以证明检查算法在受控输入上的行为，不能证明：

- GNU `ld` 接受某份具体 STM32 链接脚本；
- 示例源码在你的工具链中产生固定的节名、地址或符号大小；
- 固件已下载到 STM32；
- 复位、启动、外设或应用在板上正确运行。

## 第 2 部分：最小代码与两层实验

## 9. 最小代码示例

### 9.1 待观察的最小程序

下面三个文件遵循 C11 子集，公开接口中的整数使用固定宽度类型，不使用动态内存。它们的作用是提供可追溯对象；代码为示例，待学习者在自己的主机执行，未上板验证。

`app.h`：接口层，声明跨翻译单元可见的对象和函数。它不持有对象存储期实例。

```c
#ifndef APP_H
#define APP_H

#include <stdint.h>

extern uint32_t g_sample_counter;

uint32_t app_accumulate(uint32_t input);

#endif
```

`app.c`：实现层，定义外部对象、文件内静态对象和函数。对象均为静态存储期，程序全程持有，不需要分配或释放。

```c
#include "app.h"

uint32_t g_sample_counter = 0U;

static const uint8_t calibration_table[4] = {
    1U, 2U, 3U, 4U
};

uint32_t app_accumulate(uint32_t input)
{
    const uint32_t index = g_sample_counter % 4U;
    const uint32_t result = input + (uint32_t)calibration_table[index];

    g_sample_counter += 1U;
    return result;
}
```

`main.c`：使用层，调用公开函数并观察结果。主机 `main` 不是 Cortex-M 复位入口。

```c
#include <stdint.h>

#include "app.h"

int main(void)
{
    const uint32_t result = app_accumulate(10U);

    return (result == 11U && g_sample_counter == 1U) ? 0 : 1;
}
```

对象流如下：

```text
main.c 使用 app.h 的声明
  -> app.c 持有 g_sample_counter 和 calibration_table 的定义
  -> 编译器分别产生 main.o/app.o
  -> 链接器实例化最终输出节和符号
  -> ELF/map 分别提供最终结果与放置报告
```

### 9.2 必做 Host Fake：互证与错误注入

把下面文件保存为 `evidence-fake.c`。`map_view` 与 `elf_view` 是受控报告模型，不冒充真实解析结果；十六进制数只是抽象坐标，不是任何 STM32 地址。

```c
#include <assert.h>
#include <stdint.h>
#include <string.h>

enum evidence_kind {
    EVIDENCE_SECTION = 1,
    EVIDENCE_SYMBOL = 2
};

enum check_result {
    CHECK_OK = 0,
    CHECK_BAD_ARGUMENT = 1,
    CHECK_MISSING_ITEM = 2,
    CHECK_VALUE_MISMATCH = 3,
    CHECK_OVERLAP = 4
};

struct evidence_item {
    enum evidence_kind kind;
    const char *name;
    uint32_t address;
    uint32_t size;
};

static const struct evidence_item *find_item(
    const struct evidence_item *items,
    uint32_t count,
    enum evidence_kind kind,
    const char *name)
{
    uint32_t index;

    if (items == 0 || name == 0) {
        return 0;
    }
    for (index = 0U; index < count; ++index) {
        if (items[index].kind == kind &&
            strcmp(items[index].name, name) == 0) {
            return &items[index];
        }
    }
    return 0;
}

static uint32_t range_end(const struct evidence_item *item,
                          uint32_t *end)
{
    if (item == 0 || end == 0 ||
        item->size > UINT32_MAX - item->address) {
        return 0U;
    }
    *end = item->address + item->size;
    return 1U;
}

static enum check_result check_section_overlap(
    const struct evidence_item *items,
    uint32_t count)
{
    uint32_t left;

    if (items == 0 && count != 0U) {
        return CHECK_BAD_ARGUMENT;
    }
    for (left = 0U; left < count; ++left) {
        uint32_t right;
        uint32_t left_end;

        if (items[left].kind != EVIDENCE_SECTION) {
            continue;
        }
        if (!range_end(&items[left], &left_end)) {
            return CHECK_VALUE_MISMATCH;
        }
        for (right = left + 1U; right < count; ++right) {
            uint32_t right_end;

            if (items[right].kind != EVIDENCE_SECTION) {
                continue;
            }
            if (!range_end(&items[right], &right_end)) {
                return CHECK_VALUE_MISMATCH;
            }
            if (items[left].address < right_end &&
                items[right].address < left_end) {
                return CHECK_OVERLAP;
            }
        }
    }
    return CHECK_OK;
}

static enum check_result compare_views(
    const struct evidence_item *map_items,
    uint32_t map_count,
    const struct evidence_item *elf_items,
    uint32_t elf_count)
{
    enum check_result result;
    uint32_t index;

    if ((map_items == 0 && map_count != 0U) ||
        (elf_items == 0 && elf_count != 0U)) {
        return CHECK_BAD_ARGUMENT;
    }
    result = check_section_overlap(map_items, map_count);
    if (result != CHECK_OK) {
        return result;
    }
    result = check_section_overlap(elf_items, elf_count);
    if (result != CHECK_OK) {
        return result;
    }
    for (index = 0U; index < map_count; ++index) {
        const struct evidence_item *match = find_item(
            elf_items,
            elf_count,
            map_items[index].kind,
            map_items[index].name);

        if (match == 0) {
            return CHECK_MISSING_ITEM;
        }
        if (match->address != map_items[index].address ||
            match->size != map_items[index].size) {
            return CHECK_VALUE_MISMATCH;
        }
    }
    return CHECK_OK;
}

int main(void)
{
    static const struct evidence_item map_view[] = {
        { EVIDENCE_SECTION, ".text", 0x1000U, 0x20U },
        { EVIDENCE_SECTION, ".data", 0x2000U, 0x08U },
        { EVIDENCE_SYMBOL, "app_accumulate", 0x1008U, 0x0CU },
        { EVIDENCE_SYMBOL, "g_sample_counter", 0x2000U, 0x04U }
    };
    static const struct evidence_item elf_view[] = {
        { EVIDENCE_SECTION, ".text", 0x1000U, 0x20U },
        { EVIDENCE_SECTION, ".data", 0x2000U, 0x08U },
        { EVIDENCE_SYMBOL, "app_accumulate", 0x1008U, 0x0CU },
        { EVIDENCE_SYMBOL, "g_sample_counter", 0x2000U, 0x04U }
    };
    static const struct evidence_item missing_symbol[] = {
        { EVIDENCE_SECTION, ".text", 0x1000U, 0x20U },
        { EVIDENCE_SECTION, ".data", 0x2000U, 0x08U },
        { EVIDENCE_SYMBOL, "app_accumulate", 0x1008U, 0x0CU }
    };
    static const struct evidence_item wrong_size[] = {
        { EVIDENCE_SECTION, ".text", 0x1000U, 0x20U },
        { EVIDENCE_SECTION, ".data", 0x2000U, 0x0CU },
        { EVIDENCE_SYMBOL, "app_accumulate", 0x1008U, 0x0CU },
        { EVIDENCE_SYMBOL, "g_sample_counter", 0x2000U, 0x04U }
    };
    static const struct evidence_item overlapping_sections[] = {
        { EVIDENCE_SECTION, ".text", 0x1000U, 0x20U },
        { EVIDENCE_SECTION, ".rodata", 0x1010U, 0x10U }
    };
    static const struct evidence_item overflowing_section[] = {
        { EVIDENCE_SECTION, ".data", 0xFFFFFFF0U, 0x20U }
    };

    assert(compare_views(map_view, 4U, elf_view, 4U) == CHECK_OK);
    assert(compare_views(map_view, 4U, missing_symbol, 3U) ==
           CHECK_MISSING_ITEM);
    assert(compare_views(map_view, 4U, wrong_size, 4U) ==
           CHECK_VALUE_MISMATCH);
    assert(check_section_overlap(overlapping_sections, 2U) ==
           CHECK_OVERLAP);
    assert(compare_views(overflowing_section, 1U, elf_view, 4U) ==
           CHECK_VALUE_MISMATCH);
    return 0;
}
```

这段代码的职责边界很窄：`find_item` 按“种类 + 名称”找对应记录；`compare_views` 检查两种证据对同一对象的地址和大小是否一致，并原样传播区间校验的错误分类；`check_section_overlap` 检查受控输出节区间和 `address + size` 是否溢出。它没有解析字符串格式的 map，也没有解析 ELF 二进制，因此不会误导你认为 Host Fake 已验证真实工具链。

### 9.3 必做实验命令

若主机已有 GCC，可在 PowerShell 中执行：

```powershell
gcc --version
gcc -std=c11 -Wall -Wextra -Wpedantic .\evidence-fake.c -o .\evidence-fake.exe
if ($LASTEXITCODE -eq 0) {
    .\evidence-fake.exe
    $LASTEXITCODE
}
```

退出状态为 `0` 只表示这些受控断言在该次主机运行中成立。课程仓库没有这次执行记录，所以正文不声称命令已通过。

### 9.4 可选真实 ELF 观察

先记录环境，不要直接假定工具存在：

```powershell
gcc -dumpmachine
gcc --version
readelf --version
readelf --help
nm --version
objdump --version
```

在确认所处环境会生成 ELF 后，才执行类似命令：

```powershell
gcc -std=c11 -Wall -Wextra -Wpedantic -O0 -c .\app.c -o .\app.o
gcc -std=c11 -Wall -Wextra -Wpedantic -O0 -c .\main.c -o .\main.o
gcc .\app.o .\main.o -Wl,-Map=.\layout.map -o .\layout.elf
readelf -h .\layout.elf
```

只有最后一条明确识别为 ELF，才继续：

```powershell
readelf -S -W .\layout.elf
readelf -l -W .\layout.elf
readelf -s -W .\layout.elf
nm -n -S .\layout.elf
objdump -h -t .\layout.elf
Get-Content .\layout.map |
    Select-String -Pattern 'app_accumulate|g_sample_counter|calibration_table|\.text|\.data|\.rodata'
```

如果 `readelf -h` 报告“不是 ELF”或无法识别，立即停止 ELF 路径，记录实际格式和 `gcc -dumpmachine` 输出。不要通过改扩展名绕过检查。MinGW 等 Windows 工具链产生的 map 仍可能有学习价值，但它不构成本课的 ELF 证据；是否以及如何解释，应查该工具链官方文档。

### 9.5 正向追踪清单

以 `g_sample_counter` 为例，逐项记录：

1. 源码：`app.h` 是声明，`app.c` 是唯一外部定义，`main.c` 是使用者。
2. 目标文件：用实际工具检查 `app.o` 是否提供该符号、`main.o` 是否引用它；输出字母和字段含义以本机 `nm --help`/文档为准。
3. map：搜索名字，记录贡献目标文件、所属输出节、地址和可用大小字段。
4. ELF：在符号视图中记录名字、值、大小、绑定和节索引；字段含义必须结合实际文件头和工具版本。
5. 输出节：在 ELF 节视图与 map 中核对该节的地址范围，检查符号是否落在半开区间 `[start, start + size)` 内。
6. 回溯：回到构建命令确认这两个文件确由同一次链接产生。
7. 边界：结论只到“链接产物怎样记录它”，不写“硬件已经使用它”。

对 `calibration_table` 再做一次同样追踪。它具有内部链接，工具可能显示为局部符号，也可能因优化、合并或裁剪而不以原名出现；本示例建议 `-O0` 只是为了便于观察，不保证所有工具链保留相同记录。找不到时先检查实际选项和产物，不把“没搜到名字”直接等同于“内容不存在”。

## 第 3 部分：诊断、实验与复习

## 10. 常见错误

- **按扩展名判断格式。** `firmware.elf` 可能不是 ELF；必须读取文件头。
- **把 map 当成 ELF 的文本版。** map 是链接器报告，栏目和细节不等同于 ELF 数据结构。
- **把节和段混用。** 节视图面向内容组织，段视图面向装载；两者可能是一对多或多对一。
- **比较不同链接的文件。** 旧 map 与新 ELF 即使符号名相同，也不能构成可靠互证。
- **只看地址，不看大小和范围。** 地址相同不代表对象一致；还要检查种类、大小、所属节和输入来源。
- **把符号缺失直接判为代码未编译。** 裁剪、优化、内部链接、名称修饰和工具选项都可能影响可见记录，需逐层核对。
- **把链接地址当成板上事实。** 它证明构建期记录，不证明下载、初始化或执行。
- **套用示例地址。** `0x1000`、`0x2000` 只属于 Host Fake，绝不是 STM32 内存地址。
- **忽略工具版本。** map 格式、选项和输出列可能变化；先记录 `--version` 和 `--help`。

## 11. 调试观察点

1. 在 Host Fake 的第一次 `compare_views` 前观察两组数组，确认同名、同种类、同地址、同大小。
2. 单步进入 `find_item`，观察 `kind` 与 `name` 为什么必须同时匹配。
3. 在 `missing_symbol` 路径观察 `match == 0`，区分“缺证据”与“地址不一致”。
4. 在 `wrong_size` 路径观察地址相同而大小不同，避免只比较地址。
5. 在 `overlapping_sections` 路径计算两个半开区间，确认 `0x1010` 落入 `[0x1000, 0x1020)`。
6. 在 `overflowing_section` 路径观察 `0xFFFFFFF0 + 0x20` 超出 `uint32_t` 范围，确认它属于数值错误而不是区间重叠。
7. 真实 ELF 路径中先停在文件头：确认类别、目标机器等字段后再解释后续表；字段结论以实际工具文档为准。
8. 将 map 中一个输入目标文件追到 ELF 的最终输出节，记录每一步能证明和不能证明的内容。
9. 检查 ELF 与 map 的修改时间只能作为提示，不能替代同次构建命令或构建记录。

## 12. 实战实验

### 实验 A：Host Fake 正常与失败路径（必做）

1. 创建 `evidence-fake.c`，执行 9.3 的命令，记录编译器版本、完整命令和退出状态。
2. 用纸笔列出 `map_view` 与 `elf_view` 的四条对应关系。
3. 把 `missing_symbol` 补回 `g_sample_counter`，确认失败预期应从 `CHECK_MISSING_ITEM` 变为 `CHECK_OK`，并同步修改断言后再执行。
4. 保持 `.data` 起始地址相同，只改变大小，解释为何属于 `CHECK_VALUE_MISMATCH`。
5. 把 `.rodata` 起点改为 `0x1020U`，说明半开区间刚好相接为何不重叠。
6. 保留 `overflowing_section` 的地址和大小，解释为什么必须先检查加法溢出，不能直接计算区间末端。
7. 写下 Host Fake 能证明的两点和不能证明的三点。

### 实验 B：源码到真实产物（可选）

前提：已有明确生成 ELF 的主机或交叉工具链。

1. 创建 `app.h`、`app.c`、`main.c`，记录工具版本和目标三元组。
2. 产生同一次链接的 ELF/map；若命令或选项与示例不同，保存实际命令，不强行照抄。
3. 先检查 ELF 文件头；若不是 ELF，停止并记录原因。
4. 分别观察节、段和符号，不把任意两者当同义词。
5. 对 `app_accumulate` 和 `g_sample_counter` 各做一条完整正向追踪。
6. 从 map 选择一个输出节，列出至少两个输入贡献者，再回到构建输入确认来源。
7. 保存结论表：观察值、来源文件、工具命令、能证明什么、不能证明什么。

### 实验 C：错误注入（可选）

1. **缺符号：** 在不修改源码的前提下，尝试使用会影响符号表保留的工具步骤；先查实际工具文档。记录“符号记录缺失”和“代码内容不存在”为什么不是同一结论。
2. **节大小异常：** 增大一个静态数组后重新链接，必须生成新的一对 ELF/map。比较输出节大小和 map 输入贡献的变化。
3. **证据串线：** 故意将第一次链接的 map 与第二次链接的 ELF 放在一起，找出至少一处不一致，说明为何需要保存同次构建记录。
4. **容量或区间异常：** 只在你拥有实际目标链接脚本和可恢复构建环境时进行；不得凭本课示意地址修改真实工程。链接器若报告失败，保存诊断，但不要把链接失败写成硬件容量测量。

### 通用 STM32 迁移步骤

1. 明确具体 MCU、开发板、IDE/工具链版本和工程生成方式。
2. 保存未修改的实际链接脚本、启动文件、完整链接命令、ELF 和 map。
3. 从器件官方参考资料核对真实存储区域；没有来源的地址保持“待核对”。
4. 用工具检查链接边界符号、输出节地址/大小和程序头，再用 map 查输入贡献。
5. 将构建期结论与下载日志、调试停点或测量记录分开保存。
6. 只有出现真实硬件证据时，才可能更新 `hardware_verified`；完成本课本身不能提高掌握度。

## 13. 自检题

1. 为什么 ELF 与 map 必须来自同一次链接才能互证？
2. ELF 和 map 各自更适合回答什么问题？为什么不能互相替代？
3. 节、段、符号三者分别是什么？为什么 `.text` 不能自动等同于一个装载段？
4. 看到 `firmware.elf` 文件名后，第一步为什么不是直接运行 `readelf -S`？
5. map 显示 `g_sample_counter` 位于某地址，能证明和不能证明什么？
6. ELF 中找不到 `calibration_table` 时，应检查哪些构建期原因？
7. 从输出节大小异常反向定位到源码对象，需要经过哪几步？
8. 本课的声明、实现、实例化、组装、使用分别发生在哪里？

## 14. 面试题

**问：你如何利用 ELF 和 map 定位固件体积突然增长的来源？**

答题要点：先确保 ELF/map 来自同一次链接并记录工具版本；在 ELF 节视图确认哪个输出节的大小发生变化；在 map 中展开该输出节的输入贡献，定位增长的目标文件、库或输入节；回到对应源码和构建选项确认原因；修正后重新链接并比较新的一对产物。不能仅凭链接产物声称板上运行正常。

**问：ELF 的节和段有什么区别？**

答题要点：节头和程序头是 ELF 的不同观察视图，`readelf -S` 与 `readelf -l` 分别检查它们，不能把同名节直接当成一个段。具体文件是否含程序头、节怎样映射到段以及各字段含义，要以实际文件、目标 ABI 和对应工具文档为准。

## 15. 延伸思考

- 如果构建系统并行产生多个配置，怎样保证 ELF、map、脚本和命令记录不会串线？
- 符号表被裁剪后，还能通过哪些构建记录解释输出节增长？哪些答案必须等待实际工具文档核对？
- 为什么“链接地址正确”仍不足以证明 `.data` 初始化和 `.bss` 清零正确？需要哪些启动与运行证据？
- 当 F4、F7、H5、H7 工程的段名和内存区域不同，怎样保持同一套追溯方法而不硬编码型号知识？
- 如何把同次 ELF/map、工具版本和构建命令纳入持续集成产物，使后续故障分析可审计？

## 16. 本节总结

ELF 与 map 是同一次链接留下的两种互补证据：ELF 适合由工具读取最终节、段和符号等记录，map 适合追踪链接器报告的输入贡献与布局过程。可靠诊断从源码/脚本出发，经目标文件、map 和 ELF 核对名称、地址、大小与范围，再回到构建命令确认原因。

最重要的边界是：这些证据说明构建期布局，不单独证明映像已装载或代码已运行。文件扩展名不证明格式，Host Fake 不证明真实 ELF，真实 ELF 也不证明硬件行为。生成本课不会提高掌握度。

## 17. 下一步

下一主题是 `stack-heap`，但只有在本课通过 Reviewer 且学习状态按流程推进后才进入。本课结束时先完成 Host Fake，并用自己的话解释一条“源码 -> map -> ELF -> 构建命令”的证据链；有真实 ELF 工具链时再完成可选实验。

## 18. 参考资料

1. [STMicroelectronics, *STM32CubeIDE user guide*](https://www.st.com/resource/en/user_manual/um2609-stm32cubeide-user-guide-stmicroelectronics.pdf)，`UM2609 Rev 18, June 2026`，访问日期：2026-10-02。用于核对 STM32CubeIDE 的官方定位和目标工程工具环境；不据此推断具体芯片布局或本机工程输出。
2. [GNU Project, *GNU Binutils 2.47 source release*](https://ftp.gnu.org/gnu/binutils/binutils-2.47.tar.xz)，`GNU Binutils 2.47`，访问日期：2026-10-02。阅读位置：发行包中的 `binutils/doc/binutils.texi`，尤其是 `readelf` 章节的文件头、程序头、节头和符号表选项；用于核对 `readelf`、`objdump`、`nm` 的职责及本课使用的检查视图。课程仓库不复制该第三方发行包。
3. [GNU Project, *Using LD, the GNU Linker 2.9.1*](https://ftp.gnu.org/old-gnu/Manuals/ld-2.9.1/html_mono/ld.html)，`GNU ld 2.9.1`，访问日期：2026-10-02。阅读位置：*Command Line Options* 中 map 相关选项、*Memory Layout* 与输出节相关内容；它是固定历史版本，只支撑 map/布局报告的基础模型，实际选项和格式必须以当前安装版本核对。
