+++
title = "FreeRTOS 静态内存：对象活多久，RAM 算一次"
date = "2026-10-24T00:00:24+08:00"
summary = "以 STM32F407xx 和固定 CubeF4 所带 FreeRTOS V10.3.1 为边界，给出纯静态双任务、idle 内存回调和 HSI 启动参考实现；从对象生命周期、栈元素字节换算，走到 SRAM/CCM 分区账本与任务栈、MSP 运行余量的独立核验。未进行目标编译或上板验证。"
tags = ["FreeRTOS", "静态对象", "对象生命周期", "RAM预算", "STM32F407", "栈高水位"]
categories = ["嵌入式"]
series = ["EmbeddedStudy"]
series_order = 47
aliases = ["/embedded/embedded-study-portable/esp-b6380aeb4733-freertos-static-object-lifetime-ram-budget/"]
generated_with_ai = true
hardware_verified = false
lesson_id = "ESP-b6380aeb4733"
+++

<!-- generated-by: embedded-study-portable -->

# FreeRTOS 静态内存：对象活多久，RAM 算一次

## 1. 本节目标

本节只完成一件事：能够为一个静态创建的 FreeRTOS task 级示例建立对象生命周期清单与不重复计数的 RAM 预算，解释任务控制块、任务栈、上下文和系统保留空间的归属及预算证据边界。

三个新概念分别是静态 RTOS 对象的存储生命周期与持有关系、任务栈深元素数到字节预算的换算、静态分区与运行余量及系统栈分开的预算闭环。通知只充当两个任务之间的工作触发，不再展开通知机制；不讨论 heap_1～heap_5 算法、碎片整理、内存池或删除重建协议。

本文核对日期为 2026-10-24。参考对象为 STM32F407xx，未指定具体板卡；固定实现来自 `STM32Cube_FW_F4_V1.28.3`，`package.xml` 标明基包 FW.F4.1.28.0 与补丁 FW.F4.1.28.3，`task.h` 标明 FreeRTOS V10.3.1，使用 GCC ARM_CM4F 非 MPU 端口。所有目标代码均是参考实现，待目标工程编译；未烧录、未上板、未测量，`hardware_verified=false`。[CUBE]

## 2. 它解决什么问题

“没有 malloc，所以不会出内存问题”是错误结论。静态创建消除了本例创建对象时向 FreeRTOS heap 请求空间的步骤，却没有消除悬空地址、栈深单位错误、数组越界或运行栈不足。内核接收地址，不会替你延长 C 对象的生命。

设启动函数定义一个局部 `StaticTask_t tcb`，把地址交给内核后返回。创建调用可能正常返回，但后备对象已结束生命周期；将来调度器读写的地址可能属于另一个函数。这不是“剩余 RAM 不够”，而是“对象不该死却先死了”。因此先回答谁持有哪块存储，再回答一共占多少空间。官方静态创建文档分别要求栈、TCB 和被参数指向的变量在使用时仍存在。[STATIC]

第二类错误是账本双算。静态栈数组虽然被处理器当运行栈使用，链接器却把它当静态对象放入 `.bss` 等输出节。若 map 已统计 `.bss`，再加一次所有任务栈，就把同一物理字节计算两遍。第三类错误则相反：只看两个应用任务，遗漏内核自动创建的 idle 任务、内核全局量和中断用的 MSP。

## 3. 必要前置知识

需要能区分 C 的作用域、链接属性和存储期，能读 `sizeof`、数组元素数、指针与结构体，知道调度器与链接 map 的基本用途。函数内 `static` 对象作用域虽小，存储期仍覆盖程序运行；文件作用域的对象也有静态存储期；`static` 不是“放在某个专用 static 硬件区”的命令。

未初始化或零初始化的可写静态对象通常落在 `.bss`，非零初始化对象通常落在 `.data`，但最终服从编译选项和链接脚本。`.data` 的初始化镜像需要 Flash，运行地址还占 RAM；本课 RAM 账本统计运行地址，不把 Flash 装载镜像再算作 RAM。`const` 的实际位置同样要看链接结果。

本课假定程序从复位启动，不从一个保留了旧时钟/中断状态的 bootloader 直接跳入；板级电源、启动脚、调试接口和实际型号后缀待用户补充。已生成过通知文章不代表学习者已通过掌握度考核。

## 4. 核心原理：内核借用后备存储

一个任务至少要区分四类对象。TCB（Task Control Block，任务控制块）保存调度状态、栈指针等；`StackType_t[]` 是函数调用和保存上下文所使用的后备存储；`TaskHandle_t` 是引用任务的句柄值；`pvParameters` 是入口参数值，若为指针，指向的数据另有自己的存储和生命周期。句柄不是第二份 TCB，参数指针也不是自动复制整份上下文。

固定版本 `tasks.c:581` 的 `xTaskCreateStatic()` 将用户 TCB 缓冲区作为内部 TCB 使用，将用户栈地址写入 TCB，然后初始化任务、加入就绪链表；没有在这条路径另建一套 heap 中的 TCB/栈。`tasks.c:600` 在启用断言时检查 `sizeof(StaticTask_t)==sizeof(TCB_t)`。`FreeRTOS.h:1112` 的静态类型随通知、追踪、互斥量、Newlib 等配置改变，用户不应依赖其混淆成员布局。[CUBE]

本例采用最容易审计的约定：对象全部常驻，启动前一次创建，运行期间不删除、不复用后备数组。应用组装模块持有存储，内核持有并使用地址，任务持有其参数指针。这里的“持有”指职责和访问关系，不是转移 C 存储所有权。即使以后调用删除 API，静态数组也不会自动消失；何时可复用属于另一个完整协议，本课不提供捷径。

## 5. 关键术语与栈字节模型

`ulStackDepth` 的单位是栈元素数，不是字节。固定 `task.h:368` 已明确这一点；固定 `portable/GCC/ARM_CM4F/portmacro.h:52` 将栈元素定义为 `uint32_t`，本端口每元素 4 字节，向低地址增长，端口栈对齐要求为 8 字节。[STATIC][CUBE]

令 `S=sizeof(StackType_t)`，`T=sizeof(StaticTask_t)`，每个任务的后备对象字节数是 `T+N×S`。这只是 TCB 加栈，不包含上下文、独立句柄变量、内核全局量、链接填充或 MSP。本例工作任务 256 元素、触发任务 192 元素、idle 128 元素，栈数组分别为 1024、768、512 字节，合计 2304 字节。这些是示例定义推导值，不是实测的充分栈深，更不是安全推荐值。

三份 TCB 应写成 `3×T`，不能凭经验填入某个“固定 88 字节”常数。目标 ABI、所有参与编译单元的配置、编译器选项才决定真实布局。主机 `sizeof` 不能代替 ARM 目标 `sizeof`。任务初始寄存器帧和以后上下文保存消耗的是所提供的任务栈内部容量，不应再为它们虚构一个额外、重复的静态栈区域；它们却必须进入栈容量评估。

## 6. 从复位到工作完成的完整流程

```text
复位向量 → 启动代码/SystemInit → C运行库初始化.data/.bss → main
main → HAL_Init及HSI时钟配置（此时HAL tick可用）
     → 关闭启动时基 → 静态创建worker → 将句柄注入producer上下文
     → 静态创建producer → 标记RTOS阶段 → vTaskStartScheduler
内核 → vApplicationGetIdleTaskMemory → 创建idle → ARM_CM4F启动
producer → xTaskNotifyGive(worker) → worker处理 → 两任务各自阻塞
SysTick → xPortSysTickHandler → 内核tick/必要时PendSV
```

声明是类型与函数原型；实现是两个任务入口；实例化是静态 TCB、栈、上下文；组装是 `main` 中创建和句柄注入；使用才是任务运行后的通知与计数。把五件事写在同一 C 文件不意味着可以混淆职责。

工作任务先创建，且所有创建都在启动调度器前完成，所以 producer 不会先运行并发送给空句柄。任一应用任务创建失败都进入不返回的故障路径，不启动调度器、不使用空句柄。固定实现对空后备地址先断言、再检查，启用断言时可能直接停住；返回值检查不是对非法地址、短数组或错误生命周期的全面验证。

## 7. 嵌入式位置、时钟链与生成配置

### 7.1 能力地图及本课边界

|层次|解决的问题与数据路径|本课处理|
|---|---|---|
|基础|应用提供TCB/栈，内核引用后调度|完整实现并建账|
|进阶|静态对象按链接区域放置，map追踪归属|提供分区核算方法，不擅改链接脚本|
|高级|栈覆盖分析、MPU隔离、复杂复用协议|只说明风险，隔离及复用留后续可靠性课|
|跨外设|ISR唤醒任务、DMA缓冲与CPU对象分区|本例不启用，下一课再落地EXTI通知|
|系列迁移|重新核对目标端口、RAM可达性及配置布局|不把F407地址或TCB尺寸外推到F7/H5/H7|

这里管理的是软件对象，不存在“内存管理 HAL 句柄”“TCB DMA 回调”或对应 LL 创建寄存器。本例只有启动时钟用到 HAL；运行期任务创建、idle 回调、溢出钩子属于 FreeRTOS 层，不能伪造外设接口来填模板。

### 7.2 参考目标、时钟与复位链

RM0090 Rev22（May2026）本次只读提取中，§7.2.2 明确 HSI 为内部 16 MHz RC；§3.5.1 给出复位后 16 MHz、Flash 0 等待周期的起点。本文选 HSI 直接作为 SYSCLK，PLL 关闭，AHB、APB1、APB2 均除以 1，故 HCLK/PCLK1/PCLK2 标称均为 16 MHz；不需要外部晶振、不配置任何新外设门控或复位。[RM]

SysTick 是内核外设，不通过 APB 定时器倍频链。本配置不定义 `configSYSTICK_CLOCK_HZ`，固定端口默认选处理器时钟；`configCPU_CLOCK_HZ=16000000`、`configTICK_RATE_HZ=1000`，则重装值理论为 `16000000/1000-1=15999`，由端口 `vPortSetupTimerInterrupt()` 写入。它是理论计算，不是晶振精度或波形实测。[CUBE]

### 7.3 CubeMX清单与HAL/LL/寄存器对照

这是人工集成清单，未执行 CubeMX/CubeMX2 GUI，因此不声称某版本菜单已逐项验证：选择实际 STM32F407 型号；Clock Configuration 选择 HSI 16 MHz、PLL OFF、AHB/APB 全部 `/1`；保留实际板卡所需 SWD；不增加 GPIO/EXTI/DMA。核对 HAL 默认启动时基为 SysTick，禁止同时带入另一个 HAL TIM 时基文件。本例采用原生 FreeRTOS API，不编译 CMSIS-RTOS 包装层和自动生成默认线程。

生成后检查而不是只相信界面：静态支持 1、动态支持 0、软件 timers 0；查找 `xTaskCreate`、`osThreadNew/osThreadCreate`、`pvPortMalloc`、`malloc/calloc/realloc` 和各层对象创建；查找生成默认任务、重复 idle 回调、重复 SVC/PendSV/SysTick 实现。CMSIS 接口的栈参数可能按字节描述，不能直接照搬本课原生 API 的元素数。若生成器只能产生不符约定的包装代码，应选择人工原生集成，不宣称开关一改就完成了纯静态化。

|软件入口|可核对的底层含义|
|---|---|
|`HAL_RCC_OscConfig` 的 HSIState/HSICalibrationValue|RCC_CR.HSION/HSIRDY/HSITRIM，PLL字段选择关闭|
|`HAL_RCC_ClockConfig` 的 SYSCLKSource/分频字段|RCC_CFGR.SW/SWS/HPRE/PPRE1/PPRE2；更新SystemCoreClock|
|`FLASH_LATENCY_0`|FLASH_ACR.LATENCY；16MHz参考启动，不等于忽略供电条件|
|`HAL_SuspendTick`|默认实现清SysTick.CTRL.TICKINT，不负责永久防止RTOS再次启用|
|`vPortSetupTimerInterrupt`|端口停止、清零、重装SysTick，再设置CTRL|
|`xTaskCreateStatic`|纯软件初始化TCB/栈/链表，无专属HAL句柄或LL寄存器|

LL 可以逐项表达相同 RCC 设置，但本例不同时给第二套可竞争的时钟初始化程序。HAL RCC 代码含 `HAL_GetTick()` 超时判断，所以这些初始化必须在关闭 HAL tick 之前完成。

## 8. 双轨实验与证据边界

### 8.1 主机轨道：只验证合同模型

工作区已有 `host-contract-result.json` 记录一个独立 `host-contract-check.c` 教学模型在指定主机 GCC 下编译/运行返回 0，共 16 个简单断言。本次只读了该结果，未重新运行它，也未把它替换为本文例程测试。它自己限定为 host-only teaching models，不模拟内核或 MCU。

可以用这样的模型检验 `N×S` 换算、把任务栈归到已有静态区而非重复相加，以及识别“参数所指局部对象先结束生命”的标记。即使这些断言全部成立，也不证明目标 TCB 大小、ARM 上的对齐、调度行为、HAL 时基交接或真实栈余量。本文完整双任务参考例程没有主机编译、目标编译、目标链接或上板测试证据。

### 8.2 STM32轨道：交接边界必须先确定

本例启动阶段需要 HAL tick，运行阶段只允许 RTOS 拥有 SysTick。做法是一个唯一向量函数按启动阶段分发：启动时调用 `HAL_IncTick()`；创建任务前停止并清 pending SysTick；在全局中断关闭状态下标记运行阶段；端口启动后恢复中断和 SysTick，此后该向量只调用 `xPortSysTickHandler()`。不得再从 RTOS 路径调用 `HAL_IncTick()`，不得保留 CubeMX 的另一份 SysTick handler。

重要边界：交接后 HAL 的 `uwTick` 停止，不能调用 `HAL_Delay()`，也不能调用任何依赖 `HAL_GetTick()` 推进超时的阻塞/轮询 API，包括再配时钟等路径；不能误以为“没有 HAL_Delay 就够了”。本例任务运行期不调用 HAL。日后确需 HAL 超时时基，应另行设计独立定时器或适配时基、核对优先级并更新 RAM/中断预算，而不是随手把 HAL tick 塞回 SysTick。

## 9. 最小完整静态双任务参考实现

下面两个代码块分别对应应用 `FreeRTOSConfig.h` 与 `main.c`。还需固定包 CMSIS、HAL 配置/必要启动源文件、目标启动文件及匹配链接脚本；它不是声称可脱离目标工程独立链接的单文件固件。编译目标选择 Cortex-M4/FPU ABI 并保证所有库一致，定义实际芯片宏和 `USE_HAL_DRIVER`。不加入任何 heap_n.c，不加入 CMSIS-RTOS 包装层。

```c
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H
#include <stdint.h>
void App_Fatal(uint32_t code);
#define configUSE_PREEMPTION                  1
#define configUSE_TIME_SLICING                1
#define configUSE_PORT_OPTIMISED_TASK_SELECTION 1
#define configUSE_TICKLESS_IDLE               0
#define configCPU_CLOCK_HZ                    16000000UL
#define configTICK_RATE_HZ                    1000U
#define configMAX_PRIORITIES                  4
#define configMINIMAL_STACK_SIZE              128U
#define configMAX_TASK_NAME_LEN               12
#define configUSE_16_BIT_TICKS                0
#define configIDLE_SHOULD_YIELD               1
#define configSUPPORT_STATIC_ALLOCATION       1
#define configSUPPORT_DYNAMIC_ALLOCATION      0
#define configUSE_TASK_NOTIFICATIONS          1
#define configUSE_TIMERS                      0
#define configUSE_MUTEXES                     0
#define configUSE_RECURSIVE_MUTEXES            0
#define configUSE_COUNTING_SEMAPHORES          0
#define configUSE_QUEUE_SETS                  0
#define configQUEUE_REGISTRY_SIZE             0
#define configUSE_CO_ROUTINES                 0
#define configUSE_IDLE_HOOK                   0
#define configUSE_TICK_HOOK                   0
#define configUSE_MALLOC_FAILED_HOOK          0
#define configCHECK_FOR_STACK_OVERFLOW        2
#define configUSE_TRACE_FACILITY              0
#define configGENERATE_RUN_TIME_STATS         0
#define configUSE_STATS_FORMATTING_FUNCTIONS  0
#define configUSE_NEWLIB_REENTRANT            0
#define configNUM_THREAD_LOCAL_STORAGE_POINTERS 0
#define INCLUDE_vTaskDelay                    1
#define INCLUDE_vTaskSuspend                  1
#define INCLUDE_vTaskDelete                   0
#define INCLUDE_uxTaskGetStackHighWaterMark    1
#define INCLUDE_xTaskGetIdleTaskHandle        1
#define configPRIO_BITS                       4
#define configLIBRARY_LOWEST_INTERRUPT_PRIORITY 15
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY 5
#define configKERNEL_INTERRUPT_PRIORITY \
    (configLIBRARY_LOWEST_INTERRUPT_PRIORITY << (8-configPRIO_BITS))
#define configMAX_SYSCALL_INTERRUPT_PRIORITY \
    (configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY << (8-configPRIO_BITS))
#define configASSERT(x) do { if (!(x)) App_Fatal(1U); } while (0)
#define vPortSVCHandler SVC_Handler
#define xPortPendSVHandler PendSV_Handler
#endif
```

不定义 SysTick 别名：保留端口函数名供唯一分发函数调用。`INCLUDE_vTaskSuspend=1` 也使本例 `portMAX_DELAY` 通知等待可采用无限等待语义，并不表示增加一个挂起任务。idle 的内存提供回调不是 idle hook，所以即使 `configUSE_IDLE_HOOK=0` 仍须实现。当前官网配置页出现 `configKERNEL_PROVIDED_STATIC_MEMORY`，但固定 V10.3.1 未实现这一选项；本例禁止用它替代应用回调。[CONFIG][CUBE]

```c
#include <stdint.h>
#include <stddef.h>
#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"

#define WORKER_DEPTH   256U
#define PRODUCER_DEPTH 192U

typedef struct {
    volatile uint32_t completed;
    volatile UBaseType_t free_words;
} WorkerContext;
typedef struct {
    TaskHandle_t target;
    TickType_t period;
    volatile uint32_t sent;
    volatile UBaseType_t free_words;
} ProducerContext;

static StaticTask_t worker_tcb, producer_tcb, idle_tcb;
static _Alignas(8) StackType_t worker_stack[WORKER_DEPTH];
static _Alignas(8) StackType_t producer_stack[PRODUCER_DEPTH];
static _Alignas(8) StackType_t idle_stack[configMINIMAL_STACK_SIZE];
static WorkerContext worker_ctx;
static ProducerContext producer_ctx;
static TaskHandle_t worker_handle, producer_handle;
static volatile uint32_t rtos_phase;
static volatile uint32_t fault_code;
extern void xPortSysTickHandler(void);

_Static_assert(sizeof(StackType_t) == 4U, "ARM_CM4F栈元素应为4字节");
_Static_assert(sizeof(worker_stack) / sizeof(worker_stack[0])
               == WORKER_DEPTH, "栈元素数必须匹配");

void App_Fatal(uint32_t code)
{
    __disable_irq();
    fault_code = code;
    for (;;) { __NOP(); }
}

void SysTick_Handler(void)
{
    if (rtos_phase == 0U) {
        HAL_IncTick();
    } else {
        xPortSysTickHandler();
    }
}

void vApplicationGetIdleTaskMemory(StaticTask_t **tcb,
                                 StackType_t **stack,
                                 uint32_t *depth)
{
    *tcb = &idle_tcb;
    *stack = idle_stack;
    *depth = configMINIMAL_STACK_SIZE;
}

void vApplicationStackOverflowHook(TaskHandle_t task, char *name)
{
    (void)task;
    (void)name;
    App_Fatal(2U);
}

static void worker_entry(void *arg)
{
    WorkerContext *ctx = (WorkerContext *)arg;
    configASSERT(ctx != NULL);
    for (;;) {
        (void)ulTaskNotifyTake(pdFALSE, portMAX_DELAY);
        ctx->completed++;
        ctx->free_words = uxTaskGetStackHighWaterMark(NULL);
    }
}

static void producer_entry(void *arg)
{
    ProducerContext *ctx = (ProducerContext *)arg;
    configASSERT(ctx != NULL && ctx->target != NULL);
    configASSERT(ctx->period > 0U);
    for (;;) {
        if (xTaskNotifyGive(ctx->target) != pdPASS) {
            App_Fatal(3U);
        }
        ctx->sent++;
        ctx->free_words = uxTaskGetStackHighWaterMark(NULL);
        vTaskDelay(ctx->period);
    }
}

static void clock_hsi16_init(void)
{
    RCC_OscInitTypeDef osc = {0};
    RCC_ClkInitTypeDef clk = {0};
    osc.OscillatorType = RCC_OSCILLATORTYPE_HSI;
    osc.HSIState = RCC_HSI_ON;
    osc.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
    osc.PLL.PLLState = RCC_PLL_OFF;
    if (HAL_RCC_OscConfig(&osc) != HAL_OK) { App_Fatal(4U); }
    clk.ClockType = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK
                  | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    clk.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
    clk.AHBCLKDivider = RCC_SYSCLK_DIV1;
    clk.APB1CLKDivider = RCC_HCLK_DIV1;
    clk.APB2CLKDivider = RCC_HCLK_DIV1;
    if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_0) != HAL_OK) {
        App_Fatal(5U);
    }
    SystemCoreClockUpdate();
    if (SystemCoreClock != 16000000U) { App_Fatal(6U); }
}

int main(void)
{
    if (HAL_Init() != HAL_OK) { App_Fatal(7U); }
    clock_hsi16_init();
    /* 所有依赖HAL tick的初始化至此结束。 */
    __disable_irq();
    HAL_SuspendTick();
    SysTick->CTRL = 0U;
    SysTick->VAL = 0U;
    SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk;

    worker_handle = xTaskCreateStatic(worker_entry, "worker",
        WORKER_DEPTH, &worker_ctx, 2U, worker_stack, &worker_tcb);
    if (worker_handle == NULL) { App_Fatal(8U); }
    producer_ctx.target = worker_handle;
    producer_ctx.period = pdMS_TO_TICKS(100U);
    producer_handle = xTaskCreateStatic(producer_entry, "producer",
        PRODUCER_DEPTH, &producer_ctx, 1U, producer_stack, &producer_tcb);
    if (producer_handle == NULL) { App_Fatal(9U); }

    rtos_phase = 1U;
    __DSB();
    __ISB();
    vTaskStartScheduler();
    App_Fatal(10U);
    return 0;
}
```

`osc/clk` 是仅供初始化函数同步读取的局部参数结构，不是需要内核长期保存的任务上下文，更不是内存 HAL 句柄。`rtos_phase` 的转换在中断关闭、pending 清除后完成；固定端口首次启动会恢复全局中断，不要在创建过程中自行提前打开。SVC/PendSV 别名让端口直接成为向量实现，因此须删除生成文件中同名空函数，不能用普通 C 包装调用端口的 naked 汇编入口。保留本段唯一 SysTick 分发函数，端口 `xPortSysTickHandler` 不再另行重命名。

工作任务优先级 2、producer 为 1、idle 为 0，周期阻塞保证 idle 有机会运行。调试器读取 `volatile` 计数只是观察用途，不构成任务间同步协议；本例其他任务不读改这些计数。producer 通知可能立即让更高优先级 worker 运行，因此暂停时 `completed` 暂时领先 `sent` 一次也不代表内存坏了。所有任务入口不返回。故障路径不打印、不分配、不延时，栈已可能损坏时仍不能保证钩子可靠执行。

### 9.1 生命周期清单

|对象及定义位置|持有者/使用者|注入点|最后使用与预算归属|
|---|---|---|---|
|worker_tcb、producer_tcb；main.c静态区|应用持有，内核读写|两次xTaskCreateStatic最后参数|整个运行期；2T|
|worker_stack、producer_stack|应用持有，CPU/端口使用|两次创建的栈参数|整个运行期；1024+768字节|
|worker_ctx|应用持有，worker独占修改|worker的pvParameters|整个运行期；sizeof自身|
|producer_ctx|启动填依赖，producer读取并更新观测|producer的pvParameters|整个运行期；含target字段，不再另算该字段|
|两个独立handle变量|应用保留引用|创建返回赋值|整个运行期；sizeof变量，不是两份额外TCB|
|idle_tcb/idle_stack|应用持有，内核idle使用|idle内存回调|整个运行期；T+512字节|
|rtos_phase/fault_code|启动/中断分发及故障观察|启动流程、ISR读取|整个运行期；按符号和布局核算|
|osc/clk及函数自动变量|调用者当前栈持有|同步HAL调用|函数返回即结束；容量由MSP或当前任务栈承担|

函数局部变量并非都不允许；关键是“内核以后是否还保存它的地址”。不要把自动变量再作为独立常驻 `.bss` 项相加，也不要因它不在 `.bss` 就忽略对运行栈容量的影响。

### 9.2 只在启用timers时追加成本

主例 `configUSE_TIMERS=0`，不创建 timer 服务任务，不定义 timer 内存回调。固定 `tasks.c:2018` 的条件分支、`timers.c:227` 与 `timers.c:941` 已核对：若以后改成 1，即使尚未创建业务软件定时器，启动调度器也会建立服务基础设施。需要定义 timer 优先级、栈深、队列长度，并提供如下应用回调：

```c
#if configUSE_TIMERS == 1
void vApplicationGetTimerTaskMemory(StaticTask_t **tcb,
                                  StackType_t **stack,
                                  uint32_t *depth)
{
    static StaticTask_t timer_tcb;
    static _Alignas(8) StackType_t timer_stack[configTIMER_TASK_STACK_DEPTH];
    *tcb = &timer_tcb;
    *stack = timer_stack;
    *depth = configTIMER_TASK_STACK_DEPTH;
}
#endif
```

新增预算至少包括 `T+configTIMER_TASK_STACK_DEPTH×S`、`sizeof(StaticQueue_t)`、`configTIMER_QUEUE_LENGTH×sizeof(DaemonTaskMessage_t)`，以及 timers.c 的活动链表、指针、句柄、状态和对齐等静态量。`DaemonTaskMessage_t` 是内部类型，应由该版本实现及目标 map 核对，不能在应用里凭空假定其字节常数。若实际创建软件定时器，另记每个静态定时器后备对象；不能拿服务任务 TCB 代替它们。所有这些若已经计入输出节总量，就只是其分解明细，不再加第二次。[CUBE]

## 10. 常见错误与两张RAM账本

第一张是构建期区域账本。固定芯片头 `stm32f407xx.h:907`～920 给出 SRAM1 112 KiB、SRAM2 16 KiB、CCM 64 KiB 的基址与 CCM 终址；下列终址由基址和容量计算。DS8626 Rev12 首页可核对包含 CCM 的 RAM 总量表述。旧 RM0090 提取文本未包含 RAM 详细章节，官方 PDF 补取失败，本次不能声称已重读 §2 内存架构；CCM 的总线/DMA可达性须在迁移前补读该节，本例不使用 DMA、不把任何对象迁入 CCM。[CUBE][DS]

|独立区域|地址与容量|本例放置策略|应填的真实证据|
|---|---|---|---|
|SRAM1|0x20000000～0x2001BFFF；112KiB|普通静态数据候选|目标map逐节/符号待填|
|SRAM2|0x2001C000～0x2001FFFF；16KiB|可与SRAM1构成连续128KiB范围，但服从脚本|跨边界节需按地址拆分，不能整节两边都算|
|CCM data RAM|0x10000000～0x1000FFFF；64KiB|不主动迁入，单列核查|是否有自定义节及初始化支持待填，不能伪填为已验证0|
|备份SRAM|独立供电/使能语义|不列入普通可分配池|本例不使用，不能给SRAM超支兜底|

对区域 r，采用不交叠地址区间的并集：`U_r=已放置输出节+尚未包含的保留区`；`F_r=C_r-U_r`。检查静态节、`.noinit`、自定义节、对齐填充、链接保留 heap、MSP 保留区域各占哪里。MSP 若已体现在链接器的保留节中就不再加；若只有栈顶符号而没有实际约束，必须显式划出预算并验证与向上增长数据区不冲突。符号存在不等于已保留安全容量。

对象分解用于解释 `.bss/.data` 内部：三任务的后备存储为 `3T+2304`，再列两个上下文、句柄、阶段/错误量、内核链表与计数、HAL/CMSIS 全局量等。不得写成 `RAM=.bss+.data+3T+2304+上下文`，因为这些对象通常已经在前两项中。反过来，输出节总量也不能让你遗漏区域外自定义节或无约束的 MSP 空间。map 的输出节与输入节明细也不能上下级都加一次。

纯静态 RTOS 不等于整个固件绝无动态内存。FreeRTOS 宏只约束相应内核 API；C 库、日志、生成包装层仍可能分配。即使不链接 heap_n.c，链接脚本也可能保留 C heap，仍要在 RAM 账本中处理；不需要的保留区只能在查清依赖后调整，不能先填零。

第二张是运行期容量/余量账本，它不是新增物理占用：

|对象|已预留容量|观测项|当前证据状态|
|---|---|---|---|
|worker任务栈|256元素/1024字节|最小剩余元素×S、最大调用路径|目标观测待填|
|producer任务栈|192元素/768字节|正常、错误及调试路径|目标观测待填|
|idle任务栈|128元素/512字节|取得idle句柄后查询，覆盖启用的hook|目标观测待填|
|MSP系统栈|由启动与链接脚本确认|启动调用深度、中断嵌套和故障路径|容量/测量均待填|
|SRAM/CCM区域余量|来自第一张表的空闲区间|增长预留及放置约束|无目标map，不提供数值|

## 11. 调试观察点：高水位不是证明

`uxTaskGetStackHighWaterMark()` 返回任务运行以来扫描到的最少剩余栈元素数；固定 `tasks.c:3799` 从栈边界逐字节检查填充值，再除以 `sizeof(StackType_t)`。所以观测值 h 的字节解释为 `h×S`，不应把返回值直接标为 byte。[WATER][CUBE]

扫描反映已运行路径留下的写入痕迹，并非形式化最坏情况。未进入的错误分支、格式化输出、深层调用、浮点上下文都可能改变峰值；仅预留但未写入的自动数组可能留下填充图样，写入碰巧等于图样也会影响解读。优化等级和库版本改变后，旧观测不能直接沿用。必须记录固件配置、负载、路径覆盖及样本条件。

ARM_CM4F 任务使用 PSP，处理异常的 C 代码使用 MSP，但异常进入时对被中断任务的初始硬件压栈会占当前任务栈；端口还会保存软件上下文，并处理浮点相关寄存器。因此不能说“所有中断成本都只在 MSP”，也不能用任务高水位证明 MSP 安全。PM0214 §2.1.2 与固定 port.c 的 PSP/MSP、上下文保存路径应一起读。[PM][CUBE]

`configCHECK_FOR_STACK_OVERFLOW=2` 的钩子是诊断辅助，既不是 MPU 隔离，也不是每次内存访问都检查；严重破坏可能在检测前发生。本例钩子只记错误并停住。调试器还应观察任务后备地址、PSP/MSP、SysTick LOAD/CTRL、RCC SWS/分频和 `SystemCoreClock`。初始化断言失败先查端口、包含路径与配置一致性，不要通过关闭断言绕过。

## 12. 实战实验：先建账，再运行

前置是具体 F407 工程、启动文件/链接脚本、同一配置下的固定包和 ARM 工具链；目前没有这些目标执行证据。以下为待执行步骤，不是本次结果。

1. 人工集成第9节，确认 IRQ 向量仅一套、HAL启动时基未被其他文件覆盖，检查实际芯片与供电条件。先编译再链接，输出 map 和交叉引用，保存工具链版本与完整选项。失败优先检查宏重复、端口路径、缺失 idle 回调和 CMSIS 包装层残留。
2. 在 map 按地址定位三份 TCB、三份栈、上下文及系统栈保留。对每个 RAM 区域做区间核算，核对自定义节是否被初始化。可用目标 `nm -S`/`objdump -h` 辅助，不用宿主可执行程序推算 ARM 布局。预期找到可解释的静态对象归属，不预期某个写死的总字节。
3. 在 `main`、idle内存回调和两个任务入口设断点，观察创建顺序及句柄；在时基交接前后观察 HAL tick 是否停止、RTOS tick 是否推进。预期两个计数持续增加、任务周期阻塞、idle得到运行；没有波形或板卡时不能填写“已观察”。
4. 覆盖正常和可达失败路径，收集两个任务与idle的高水位；另用适合当前启动代码的MSP观测方法评估系统栈。不要在仍被使用的MSP上盲目涂写填充。记录测试覆盖后才讨论余量，不能看到一次大余量就减少栈。
5. 做离线账本反例：把深度误填为 `sizeof(worker_stack)`，应识别其将1024字节误当1024元素、超出数组；把任务栈再加到`.bss`，应识别双计数；把上下文改成创建函数局部变量，应识别生命周期错误。这些反例只用于审查，不要求在板上故意制造破坏。

若要尝试启用 timers，作为另一个配置变体编译并对比 map 增量，同时核对服务队列和全局基础设施；不是只增加一份服务栈。若要迁移 CCM，先补齐内存架构证据、链接放置和启动初始化，再重新运行完整闭环。

## 13. 自检题

1. 创建函数返回后句柄仍非空，能证明局部TCB有效吗？不能，句柄数值与所指对象的生命周期是两回事。
2. 本端口192个栈元素占多少字节？768；这是数组容量，不代表任务只会用这么多，也不包含TCB。
3. map的`.bss`已含worker_stack，是否还应追加1024字节？不能；可拆成明细解释，物理总账只能计一次。
4. 应用两个任务之外为什么还要有第三份TCB与栈？启动调度器会创建idle，静态模式由应用回调供存储。
5. 高水位剩80个元素能证明所有路径安全吗？不能；只表示现有覆盖和扫描条件下的余量，需要另查MSP和未覆盖路径。
6. 关闭动态分配是否自动删除链接脚本的heap保留？不会；编译宏与链接区域保留属于不同层。

## 14. 面试题

问：静态创建为什么仍可能崩溃？答题应从C对象生命周期、数组真实容量/对齐、越界及运行栈覆盖展开，不能只回答“栈太小”。

问：如何汇报一项可信的RAM优化？先冻结内核/端口/配置和工具链，给出目标map中不重叠的区域与对象变化，再附负载覆盖下的栈余量和系统栈评估；没有目标证据时只能汇报公式、源码核对和待验证项。

问：为什么不能从新版官网直接复制静态配置？文档可能覆盖新版；例如内核代供静态内存选项不属于本次固定实现。应由版本头、条件编译和实际调用路径共同确认，而非“宏能写进头文件所以有效”。

## 15. 延伸思考

若把一个任务的栈从普通SRAM移到CCM，任务代码可能无需变更，但链接输出节、启动初始化、区域容量和任何传给其他总线主设备的局部缓冲区约束都会变化。这说明“对象生命周期正确”和“硬件可访问”是不同检查维度。本文不在证据不全时发布可直接迁移的CCM代码。

迁往F7/H5/H7，保留对象清单与不重复计数方法，重新选择该器件对应的FreeRTOS端口、ABI、TCB配置和RAM区域；对缓存、DMA可达性、域与安全属性逐项查目标手册，不复用F407地址或容量。这里只列迁移核对入口，不声称本次已核对其他系列具体型号，更不把它们增加为本课新概念。

## 16. 本节总结

先为每个被长期引用的对象安排足够长的生命周期，再按元素单位声明任务栈；用目标类型计算对象明细，用链接输出节和地址区间建立唯一物理账本。最后把任务栈、idle栈与MSP的运行安全余量单独验证。静态分配让布局更可审计，不会自动替代并发设计和覆盖测试。

当前可信交付是固定源码/缓存正文的核对、完整参考代码及待填账本，不是目标map、充分栈深或硬件通过结论。课程生成也不改变学习掌握度。

## 17. 下一步

下一篇再把EXTI事件通过ISR通知交给任务，届时必须补齐具体中断优先级、板级输入与错误路径。只在生命周期和账本保持清楚的基础上加入新的硬件链路；复杂allocator另设主题。本篇不执行accept、不发布、不改旧课程目录或学习状态。

## 18. 参考资料与定位

下列方括号标识对应响应`sources`清单，实际读取日期均为2026-10-24。官方网页使用工作区缓存正文的静态字符串内容阅读，没有执行下载的JavaScript；缓存网页不是固定内核版本的替代品。旧L045只作为任务附带背景，不作为本次已验证技术来源。

- [STATIC] FreeRTOS `xTaskCreateStatic`：Parameters中的ulStackDepth、pvParameters、puxStackBuffer、pxTaskBuffer及Returns；工作区`official-static-task-body.js.txt`。
- [ALLOC] Static Vs Dynamic Memory Allocation：Introduction及静态/动态比较、应用提供存储的条目；`official-static-vs-dynamic-body.js.txt`。静态创建的取舍而非allocator算法，见第2～5节。
- [WATER] `uxTaskGetStackHighWaterMark`：返回单位与覆盖含义；`official-stack-watermark-body.js.txt`；第11节以固定实现补充扫描局限。
- [CONFIG] Customization：configSUPPORT_STATIC_ALLOCATION、configSUPPORT_DYNAMIC_ALLOCATION、configUSE_TIMERS、静态回调及新版configKERNEL_PROVIDED_STATIC_MEMORY段落；`official-configuration-body.js.txt`。新版代供选项不用于本例。
- [CUBE] 固定包：`package.xml:3`；`Source/include/task.h`版本声明、349～389与高水位声明；`Source/tasks.c:581～630、1975～2095、3799～3879`；`Source/include/FreeRTOS.h:1099～1160`；`Source/portable/GCC/ARM_CM4F/portmacro.h:46～75`及`port.c`栈初始化、首次启动、PendSV与SysTick设置；`Source/timers.c:227～277、941～988`。路径前缀为`Middlewares/Third_Party/FreeRTOS/`；RAM地址来自`Drivers/CMSIS/Device/ST/STM32F4xx/Include/stm32f407xx.h:907～920`；HAL/RCC时基行为来自对应`Drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal.c`与`stm32f4xx_hal_rcc.c`。这些是本次实际读到的实现，不是目标构建证据。
- [RM] RM0090 Rev22，May2026：只读提取重读§3.5.1、§7.2.2及RCC相关文本；RAM详细章节不在该摘录，补取失败，不冒称已核对其正文。
- [DS] DS8626 Rev12，March2026：首页器件、RAM总量及HSI规格说明；目录定位§3.6不等于已读到该节正文，具体RAM银行地址/容量以固定芯片头文件交叉核对。
- [PM] PM0214 Rev10，March2020：§2.1.2、表2及§2.3异常模型，只支持本课MSP/PSP边界，不证明运行时余量。

## Interview Practice

### 1. 某启动函数在局部自动变量中定义StaticTask_t、StackType_t数组和任务上下文，调用xTaskCreateStatic后返回。句柄非空能证明设计安全吗？怎样修正？

不能。静态创建表示后备存储由应用提供，不表示内核复制这些对象或延长自动变量生命周期。启动函数返回后TCB、栈和参数指向的上下文都可能失效，非空句柄只说明创建调用得到一个引用，不能证明后续引用有效。应把所有在任务运行期仍被引用的后备对象和上下文放在覆盖整个使用期的存储中，例如组装模块文件作用域静态对象；本课约定任务常驻、不删除或复用。同步调用HAL时只在调用期间被读取的局部初始化结构可以保持自动存储期。

Scoring: 应分别指出TCB、栈、参数指向对象三者的生命周期，并否定句柄非空等于安全；修正需保证整个使用期有效。能区分同步HAL局部参数与长期任务上下文，表明真正理解而非禁止全部局部变量。

### 2. 固定GCC ARM_CM4F端口中，worker声明StackType_t worker_stack[256]。创建时能否把sizeof(worker_stack)直接作为ulStackDepth？数组占多少字节？高水位返回80又表示什么？

不能直接传sizeof(worker_stack)。本端口StackType_t为4字节，256元素数组占1024字节，而原生xTaskCreateStatic的ulStackDepth单位为元素数，应传256或数组元素数表达式。传1024会宣称有1024元素，即4096字节，超过实际后备数组。高水位80表示扫描到的最少剩余80元素，在此端口换算为320字节；这是已有运行覆盖下的观测，不是所有路径的安全证明。

Scoring: 正确给出256元素、1024字节、误传时4096字节及80元素=320字节；须说明单位依据是固定端口，不能泛化所有端口或混用CMSIS字节接口；高水位不应被当最坏情况证明。

### 3. 目标map的.bss和.data已经包含两个应用任务、idle的TCB与静态栈。你又算出三份栈合计2304字节和3×sizeof(StaticTask_t)，应怎样记账？MSP是否也能忽略？

2304字节与3×sizeof(StaticTask_t)是静态输出节内部的对象分解，不应再次加到已经包含它们的.bss/.data总量上。应按实际RAM银行和不重叠地址区间建立物理账本，同时检查自定义节、对齐及保留区。MSP不能忽略：若已通过链接保留节计入，则不重复加；若只有栈顶符号、没有容量约束，应显式划出并验证系统栈空间。任务栈运行余量另作容量检查，不是第二份物理分配。

Scoring: 应识别静态栈和TCB双计数，区分对象明细与物理总账；MSP须按是否已真实保留去重，不能一概另加或忽略；使用未验证的TCB固定大小不得满分。

### 4. 把configUSE_TIMERS从0改为1，但业务没有创建软件定时器，能否认为RAM不变？在本课固定V10.3.1纯静态模式下应检查哪些新增项？

不能。启用timers后，调度器启动会建立timer服务基础设施，即使尚无业务定时器。应提供对应静态内存回调并预算服务任务TCB、configTIMER_TASK_STACK_DEPTH个栈元素、静态命令队列控制块、configTIMER_QUEUE_LENGTH乘以该固定实现内部DaemonTaskMessage_t大小的队列存储，以及活动链表、句柄、状态、对齐等全局成本。内部类型大小由固定版本与目标构建/map核对，不能凭经验写死；这些若已计入输出节，只作为分解，不再追加。以后实际创建静态定时器还要记录各自后备对象。V10.3.1不能依赖新版configKERNEL_PROVIDED_STATIC_MEMORY免除应用回调。

Scoring: 须指出启用即产生服务基础设施，至少覆盖任务、队列控制块和队列存储三类；强调目标布局和去重。只增加一份栈，或以没有业务定时器为由判定零成本，属于关键遗漏。

### 5. 压力测试中两个任务的高水位都较大，且打开了configCHECK_FOR_STACK_OVERFLOW=2。能否据此认定任务栈和MSP永远安全，并立刻减小栈？

不能。高水位来自填充值扫描，只反映已执行路径的写入痕迹，未覆盖错误路径、深层调用、库函数、浮点上下文和未写入的自动数组等可能改变解读。溢出钩子是诊断辅助，不是每次访问检查或MPU隔离，严重破坏可能先于检测。任务使用PSP，异常处理代码使用MSP，但从任务进入异常的初始硬件压栈仍占任务栈，端口上下文保存也要纳入任务容量；任务高水位不能测出MSP余量。应冻结版本、编译选项和配置，记录负载及路径覆盖，独立核对系统栈、保留安全裕量后再评估调整。

Scoring: 须否定永远安全，解释高水位覆盖限制与钩子能力边界，并正确区分PSP/MSP及初始异常帧；只说中断全部使用MSP为错误；合理的覆盖与裕量计划比单一经验阈值更重要。

### 6. 为本课worker256元素、producer192元素、idle128元素的静态系统设计一份可审计RAM验收流程。哪些数现在可推导，哪些必须等目标证据？若打算把任务栈迁入CCM，应加什么门槛？

先冻结Cube包、V10.3.1、ARM_CM4F端口、FreeRTOSConfig和工具链，列TCB、栈、上下文、句柄、内核全局量的定义者、使用者、注入点与使用期。现在可从4字节元素推导三栈为1024/768/512字节、合计2304，TCB只写3×目标sizeof(StaticTask_t)，不能伪填总RAM。目标编译链接后，以map按SRAM1、SRAM2、CCM等实际区域核对不重叠地址区间，包含.data/.bss、自定义节、对齐和未计入的MSP/heap保留；明细不重复加。随后用正常、异常和最重路径覆盖采集各任务与idle高水位，并独立评估MSP，记录固件与负载条件。检查库和包装层是否仍动态分配，不能由RTOS宏推断整个固件无malloc。迁入CCM前必须补齐具体器件内存架构、总线可达性、链接放置与启动初始化证据，涉及DMA再核对其访问约束；本文缺少相关完整正文和目标结果，故不直接给出已安全迁移结论。未构建/上板前hardware_verified保持false。

Scoring: 评估生命周期清单、单位推导、按区域去重map账本、任务与MSP分开验证、迁移前补证五方面。应明确2304不是总RAM或已验证安全栈深；允许不同表格形式，但不得用主机sizeof代替目标布局、用总容量掩盖银行放置限制，或虚构CCM迁移证据。
