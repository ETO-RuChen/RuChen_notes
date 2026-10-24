+++
title = "FreeRTOS 静态任务通知：把工作次数交给唯一接收者"
date = "2026-10-24T00:00:15+08:00"
summary = "基于 STM32CubeF4 固定包中的 FreeRTOS V10.3.1，推演通知累积、逐个消费和整批交接，提供静态任务、idle 内存回调、HSI 启动及 SysTick 所有权参考代码，并严格区分主机模型证据与尚未编译、上板的目标实现。"
tags = ["FreeRTOS", "任务通知", "静态任务", "计数交接", "STM32F407", "Host-Fake"]
categories = ["嵌入式"]
series = ["EmbeddedStudyPortable"]
generated_with_ai = true
hardware_verified = false
lesson_id = "ESP-ee33dedf7e22"
+++

<!-- generated-by: embedded-study-portable -->

## 1. 本节目标与验证边界

只解决一件事：把生产者产生的工作次数交给一个静态工作任务，并解释积压、消费和超时。三个新概念是接收任务内嵌计数、两种消费语义、计数与负载及互斥的边界；任务句柄、阻塞和静态存储期仅作复习。

参考 STM32F407xx、原生 C API、GCC ARM_CM4F。本次实际读取日期为2026-10-24。固定包 package.xml:3 确认 FW.F4.1.28.0基包加FW.F4.1.28.3补丁；Source/include/task.h:46确认内核V10.3.1。[ST-PACK] 不使用 indexed 接口、通知数组或CMSIS包装层。

目标代码是参考实现，目标工程未编译、未烧录、未上板、未测量；CubeMX GUI未运行，hardware_verified=false。已有主机结果不能扩大为整篇代码通过。本课仅task→task，不加入EXTI、DMA或FromISR，不虚构通知外设HAL句柄。

## 2. 为什么需要保存次数

生产者连续三次要求工作，普通布尔标志只能保存“有”，不能区分一次和三次；工作任务不停轮询又浪费CPU。计数通知使接收者无工作时阻塞，有工作时按次数处理，生产者先到也能保留待办数。

直观模型是接收任务门口的计数器，不是带内容的工单。一次固定计算可由“再做一次”表达；若三次分别带不同采样值、命令或指针，数字3无法重建负载，应使用队列或另有完整所有权协议的数据通道。内核负责计数和等待，不负责业务完成；领取后处理失败，重试或丢弃由应用约定。

## 3. 前置对象与生命周期

TCB是任务控制块；StaticTask_t是应用提供TCB存储的公开类型，不应依赖内部布局。TaskHandle_t是创建后返回的任务引用，不是独立通知对象。StackType_t是端口栈元素，此ARM_CM4F端口为uint32_t，所以256个元素是1024字节，不是256字节。[STATIC][ST-PACK]

V10.3.1启用通知后，每个任务内部有一个32位值和通知状态。tasks.c:311及相邻的ulNotifiedValue、ucNotifyState用于核对机制，应用不直接访问。创建任务时内核初始化，不需额外创建通知或分配通知堆。通知跟随接收任务；删除任务会使旧句柄失效，本课不删除任务。

## 4. 发送和领取的调用流

发送端xTaskNotifyGive(worker)指定目标。固定task.h:2067展开成xTaskGenericNotify(worker,0,eIncrement,NULL)，其中0不是负载，动作是递增通知值。tasks.c:4783–4889在临界区更新；若接收者等待通知，移回就绪列表，必要时请求切换。[COUNTING][ST-PACK]

接收端ulTaskNotifyTake(clear,wait_ticks)没有句柄参数：它领取当前调用任务自己的通知。计数非零就直接领取；为零才按等待参数决定是否阻塞。阻塞任务不忙轮询，但其他任务和中断仍运行。[TAKE]

发送更新、接收者获得CPU、业务完成是三件事。高优先级生产者不让出CPU，低优先级接收者即使就绪也不能运行。give递增返回pdPASS不表示完成，也不报告满；空句柄不是广播或发送给自己，固定源码会断言，必须在创建和生命周期处保证有效。

## 5. pdFALSE与pdTRUE：都返回消费前计数

固定tasks.c:4673–4683先保存ulReturn，再清零或减一，最后返回。因此返回值不是成功布尔量，也不是统一的“本次领取量”。[TAKE][ST-PACK]

| 调用 | 领取前 | 返回 | 领取后 | 应用处理次数 |
|---|---:|---:|---:|---:|
| take(pdFALSE,0) | 3 | 3 | 2 | 1 |
| 再take(pdFALSE,0) | 2 | 2 | 1 | 1 |
| 再take(pdFALSE,0) | 1 | 1 | 0 | 1 |
| 再take(pdFALSE,0) | 0 | 0 | 0 | 0 |
| 独立重置为3，take(pdTRUE,0) | 3 | 3 | 0 | 3 |

pdFALSE一次领取一份：返回3说明领取前有三份，只处理一份后再take。若按每次返回值循环处理，会多做成3+2+1=6份。pdTRUE一次取走整批：返回3且清零后，应用负责三份；只写if(n)处理一次会漏两份。若业务允许合并成“至少发生过”，可以只做一次，但不能声称保存了全部次数。

清零之后新到通知仍累积：取走3、处理第一份时又give两次，内核计数为2，本地仍负责原批3份。完成后再take领取新2份，不要每处理一次就再次清空内核。

## 6. 时间顺序、超时和uint32溢出

先give后三次take，计数保留，不要求接收者刚好在线；先take阻塞再give，接收者就绪，但真正运行前可能又到多次，所以返回不保证是1。内核协调检查与等待，应用不要先读影子计数再自行睡眠。

等待0是立即尝试；有限等待无可领取计数时返回0，不能证明生产者永远失效。超时边缘到达的事件还受实际调度和读取时刻影响，返回不是微秒时间戳。本文1000Hz下200ms换算200tick；较低tick频率下短毫秒数可能换成0。生产周期1000tick而等待200tick，正常就可能多次空等超时。

固定tasks.c:4809–4810对uint32_t直接++，无饱和检查。UINT32_MAX再give回绕到0，不能当作无界可靠队列。通知状态可能已经“收到”，但take按非零值领取；pdPASS不会报告溢出。必须证明最大突发、最大停顿和消费能力；持续生产快于消费迟早失败。需要满失败或背压时选择显式有容量契约的机制，不靠读取内部计数后再give来补救竞态。

## 7. 所有权、组装和能力地图

| 对象 | 定义及持有者 | 注入/使用 | 生命周期 |
|---|---|---|---|
| 工作任务TCB及栈 | app_notify.c静态实例 | 创建时交内核 | 整个程序 |
| 通知计数 | 接收任务TCB内部 | 生产者give、当前任务take | 跟随任务 |
| 接收者句柄 | 组装端取得 | 写入生产者上下文 | 本课不删除 |
| 生产者上下文 | 模块静态对象 | 创建时传地址 | 整个程序 |

头文件声明接口，任务函数实现行为，静态变量实例化存储，App_CreateTasks组装依赖，生产者运行时使用句柄。单接收者不禁止多个生产者，但计数不保存发送者身份或先后负载；多个worker不能争抢同一个任务的通知。

能力地图：基础是计数、等待、超时；进阶是批量和突发预算；高级可研究位图、覆写及协议冲突，但同一槽不能未经设计混用动作；跨外设后续才做EXTI/DMA完成→任务，并补中断和缓冲区错误路径。本课没有通知IRQ/DMA回调。

通知不做互斥，没有资源持有者和互斥量优先级继承。共享数组被生产者连续覆盖，三次give也不会产生三份快照；必须另证数据所有权、可见性和覆盖规则，volatile不够。库若也占用此V10.3.1唯一通知槽，会与本课协议相互干扰。

## 8. STM32时钟链、CubeMX和寄存器对照

直接复位启动，HSI标称16MHz、PLL关闭、SYSCLK=HSI，AHB/APB1/APB2分频都为1，所以SYSCLK=HCLK=PCLK1=PCLK2=16MHz。内部RC不保证晶振级精度。本例不覆盖bootloader已切到PLL的接管，需另查时钟和向量交接。[RM0090]

SysTick选择HCLK，不是APB定时器，不套用定时器倍频。tick1000Hz时LOAD=16000000/1000-1=15999，未超24位。port.c:40–47在未定义configSYSTICK_CLOCK_HZ时选内核时钟；本例故意不定义它，保留默认分支；port.c:679–696负责装载。[ST-PACK][PM0214]

CubeMX待操作清单：实际F407封装、HSI、无PLL、三处分频1、原生FreeRTOS静态分配及通知、关闭动态分配和timer、核对原生栈单位及三个异常向量。工具版本待填，未运行GUI或验证.ioc；不要混入包装层的字节单位。

HAL/LL/寄存器对照：HSIState→RCC_CR.HSION/HSIRDY，校准→HSITRIM，PLLState→PLL开关；SYSCLKSource→CFGR.SW并等SWS，AHB/APB字段→HPRE/PPRE1/PPRE2，FLASH_LATENCY_0→FLASH_ACR.LATENCY。RM0090表11支持此低频选择，实际供电仍需核对。LL表达同一硬件动作，本例不混用第二套初始化。通知本身没有RCC门控或复位位，也没有HAL句柄。

## 9. 静态任务完整参考代码

以下是应用侧完整闭环；仍需固定包的启动汇编、链接脚本、CMSIS设备文件和HAL配置头，不是已编译工程。

### FreeRTOSConfig.h

```c
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H
#include <stdint.h>
#include "stm32f4xx.h"
extern uint32_t SystemCoreClock;
_Noreturn void App_Fatal(void);
#define configUSE_PREEMPTION 1
#define configUSE_TIME_SLICING 1
#define configUSE_PORT_OPTIMISED_TASK_SELECTION 1
#define configCPU_CLOCK_HZ (SystemCoreClock)
#define configTICK_RATE_HZ 1000U
#define configMAX_PRIORITIES 4
#define configMINIMAL_STACK_SIZE 128U
#define configMAX_TASK_NAME_LEN 16
#define configUSE_16_BIT_TICKS 0
#define configIDLE_SHOULD_YIELD 1
#define configUSE_TASK_NOTIFICATIONS 1
#define configSUPPORT_STATIC_ALLOCATION 1
#define configSUPPORT_DYNAMIC_ALLOCATION 0
#define configUSE_TIMERS 0
#define configUSE_MUTEXES 0
#define configUSE_IDLE_HOOK 0
#define configUSE_TICK_HOOK 0
#define configCHECK_FOR_STACK_OVERFLOW 2
#define INCLUDE_vTaskDelay 1
#define INCLUDE_uxTaskGetStackHighWaterMark 1
#define configPRIO_BITS __NVIC_PRIO_BITS
#define configLIBRARY_LOWEST_INTERRUPT_PRIORITY 15
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY 5
#define configKERNEL_INTERRUPT_PRIORITY \
  (configLIBRARY_LOWEST_INTERRUPT_PRIORITY << (8-configPRIO_BITS))
#define configMAX_SYSCALL_INTERRUPT_PRIORITY \
  (configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY << (8-configPRIO_BITS))
#define configASSERT(x) do { if (!(x)) { App_Fatal(); } } while (0)
#define vPortSVCHandler SVC_Handler
#define xPortPendSVHandler PendSV_Handler
#endif
```

关闭软件定时器，所以不用timer静态回调；以后开启须补配置和vApplicationGetTimerTaskMemory。idle hook关闭仍需idle内存回调，它们不是一回事。中断阈值供端口使用，本课不从外设中断调用API。

### app_notify.h

```c
#ifndef APP_NOTIFY_H
#define APP_NOTIFY_H
void App_CreateTasks(void);
_Noreturn void App_Fatal(void);
#endif
```

### app_notify.c

```c
#include <stdint.h>
#include "stm32f4xx.h"
#include "FreeRTOS.h"
#include "task.h"
#include "app_notify.h"

enum { APP_STACK_WORDS = 256 };
typedef struct { TaskHandle_t receiver; } ProducerContext;
static StaticTask_t worker_tcb, producer_tcb;
static StackType_t worker_stack[APP_STACK_WORDS];
static StackType_t producer_stack[APP_STACK_WORDS];
static ProducerContext producer_context;
volatile uint32_t g_produced;
volatile uint32_t g_completed;
volatile uint32_t g_empty_waits;

_Noreturn void App_Fatal(void)
{
  __disable_irq();
  for (;;) { __NOP(); }
}

static void DoOneWork(void)
{
  ++g_completed;
}

static void WorkerTask(void *argument)
{
  (void)argument;
  for (;;) {
    uint32_t before = ulTaskNotifyTake(pdFALSE, pdMS_TO_TICKS(200U));
    if (before != 0U) {
      DoOneWork();
    } else {
      ++g_empty_waits;
    }
  }
}

static void ProducerTask(void *argument)
{
  const ProducerContext *ctx = argument;
  configASSERT(ctx != NULL && ctx->receiver != NULL);
  for (;;) {
    for (uint32_t i = 0U; i < 3U; ++i) {
      (void)xTaskNotifyGive(ctx->receiver);
      ++g_produced;
    }
    vTaskDelay(pdMS_TO_TICKS(1000U));
  }
}

void App_CreateTasks(void)
{
  TaskHandle_t worker = xTaskCreateStatic(WorkerTask, "worker",
    APP_STACK_WORDS, NULL, 1U, worker_stack, &worker_tcb);
  if (worker == NULL) { App_Fatal(); }
  producer_context.receiver = worker;
  TaskHandle_t producer = xTaskCreateStatic(ProducerTask, "producer",
    APP_STACK_WORDS, &producer_context, 2U, producer_stack, &producer_tcb);
  if (producer == NULL) { App_Fatal(); }
}

void vApplicationGetIdleTaskMemory(StaticTask_t **tcb,
  StackType_t **stack, uint32_t *words)
{
  static StaticTask_t idle_tcb;
  static StackType_t idle_stack[configMINIMAL_STACK_SIZE];
  *tcb = &idle_tcb;
  *stack = idle_stack;
  *words = configMINIMAL_STACK_SIZE;
}

void vApplicationStackOverflowHook(TaskHandle_t task, char *name)
{
  (void)task;
  (void)name;
  App_Fatal();
}
```

DoOneWork只代表同一种固定工作。三个volatile计数各自单写、仅调试器观察，不作任务同步或一致快照，长期也会回绕。组装必须调度前仅执行一次：先创建接收者并检查，再写常驻上下文、创建生产者；不是传入短命局部结构地址。静态创建空存储可能先断言，也有NULL路径；失败即停机，不启动残缺依赖。栈256/128元素只是参考起点，不是实测安全预算。

## 10. HAL启动与运行时SysTick唯一所有权

两阶段交接：启动期HAL_Init和HAL_RCC_ClockConfig会调用HAL_InitTick，RCC等待依赖HAL_GetTick，所以先保留HAL时基。组装后停SysTick、清挂起、改所有权，再启动调度器。运行期同一入口只进RTOS。

### main.c

```c
#include <stdint.h>
#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"
#include "app_notify.h"

static volatile uint32_t boot_hal_tick = 1U;
extern void xPortSysTickHandler(void);

void SysTick_Handler(void)
{
  if (boot_hal_tick != 0U) {
    HAL_IncTick();
  } else {
    xPortSysTickHandler();
  }
}

static void Clock_HSI16(void)
{
  RCC_OscInitTypeDef osc = {0};
  RCC_ClkInitTypeDef clk = {0};
  osc.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  osc.HSIState = RCC_HSI_ON;
  osc.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  osc.PLL.PLLState = RCC_PLL_OFF;
  if (HAL_RCC_OscConfig(&osc) != HAL_OK) { App_Fatal(); }
  clk.ClockType = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK
         | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
  clk.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  clk.AHBCLKDivider = RCC_SYSCLK_DIV1;
  clk.APB1CLKDivider = RCC_HCLK_DIV1;
  clk.APB2CLKDivider = RCC_HCLK_DIV1;
  if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_0) != HAL_OK) {
    App_Fatal();
  }
  SystemCoreClockUpdate();
  if (SystemCoreClock != 16000000U) { App_Fatal(); }
}

int main(void)
{
  if (HAL_Init() != HAL_OK) { App_Fatal(); }
  Clock_HSI16();
  App_CreateTasks();
  SysTick->CTRL = 0U;
  SysTick->VAL = 0U;
  SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk;
  boot_hal_tick = 0U;
  __DSB();
  __ISB();
  vTaskStartScheduler();
  App_Fatal();
}
```

集成时去掉生成文件中重复的SysTick/SVC/PendSV定义。SVC、PendSV由配置宏映射端口；不把xPortSysTickHandler再映射成SysTick_Handler，本文已有唯一包装。启动前只HAL_IncTick，调度后只xPortSysTickHandler，不叠加HAL_IncTick或HAL_SYSTICK_IRQHandler。端口启动时配置优先级和计数器，不再由HAL重配。

停表后清PendST防止旧tick误入端口，此后不再依赖HAL时间。**运行期HAL_GetTick冻结**：不能HAL_Delay，不能调用依赖HAL_GetTick的阻塞超时API，也不能重做RCC或任何重配HAL tick的操作。HAL_SuspendTick默认关闭SysTick中断，此时会破坏RTOS延时与超时，运行期同样禁止。不能笼统说其他HAL API全可用，须审计间接时基依赖。[ST-PACK]

以后确需HAL超时驱动，应另设计独立时基或完整审查时间适配；本课不暗加定时器掩盖限制。任务等待用RTOS API，也不代表vTaskDelay可机械替换所有HAL内部超时。

## 11. 批处理替换和工作守恒

只将WorkerTask循环主体换成下面策略，不同时创建第二接收者。

```c
uint32_t pending = ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(200U));
if (pending == 0U) {
  ++g_empty_waits;
} else {
  while (pending != 0U) {
    DoOneWork();
    --pending;
  }
}
```

无溢出或主动丢弃时：已生产=内核尚未领取+本地已领取尚未完成+已完成。pdFALSE也有一份在途工作；pdTRUE可能有整批。守恒式用于推演，不通过窥读TCB实现监控。批量减少API次数不保证实时性更好，N份每份最坏T需要相应执行预算。若让出CPU，须在本地保留余量，不能丢批后继续领取。

## 12. Host Fake练习和证据边界

主机替身只验证算术，不模拟内核调度、临界区、中断或真实阻塞。下面是待执行练习，本次未单独编译运行。

```c
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
typedef struct { uint32_t count; } FakeNotify;
static void give(FakeNotify *n) { ++n->count; }
static uint32_t take(FakeNotify *n, bool clear)
{
  uint32_t before = n->count;
  if (before != 0U) { n->count = clear ? 0U : before - 1U; }
  return before;
}
int main(void)
{
  FakeNotify n = {0U};
  assert(take(&n, false) == 0U);
  give(&n); give(&n); give(&n);
  assert(take(&n, false) == 3U && n.count == 2U);
  assert(take(&n, false) == 2U && n.count == 1U);
  assert(take(&n, false) == 1U && n.count == 0U);
  give(&n); give(&n); give(&n);
  uint32_t batch = take(&n, true);
  uint32_t done = 0U;
  give(&n);
  while (batch != 0U) { ++done; --batch; }
  assert(done == 3U && n.count == 1U);
  n.count = UINT32_MAX;
  give(&n);
  assert(n.count == 0U);
  return 0;
}
```

可用gcc -std=c11 -Wall -Wextra -Werror -pedantic编译自建练习，再运行；不能称为FreeRTOS已移植到Windows。模拟等待后give可用确定性步骤表，不能由此测STM32唤醒延迟。

已读取host-contract-result.json：另一份host-contract-check.c以主机GCC通过16项简单断言，编译/执行退出码0。本次未重跑；该记录不证明这里的新练习、内核、HAL启动或整篇代码编译通过，更不证明NVIC、内存布局及硬件行为。

## 13. 实验、构建与调试

实验一先纸笔再改Fake：give三次后逐个take，预期返回3、2、1；重置后批量take得3并归零，处理期再give一次留给下批。故意把pdFALSE返回值当循环次数会多处理，pdTRUE只做一次会少处理，解释两类失败。

目标实验待执行：确认实际器件/供电/调试器；C11工程使用固定tasks.c、list.c、queue.c、GCC/ARM_CM4F/port.c及必要HAL/CMSIS，不添加heap_x.c或未配置timer/CMSIS包装。准备正确启动和链接脚本、STM32F407xx、USE_HAL_DRIVER；-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16，浮点ABI各文件一致。map中查TCB/栈常驻及三个异常入口唯一，成功构建后才烧录并保存日志，本文没有这些结果。

生产者优先级2连续发送三次后delay，worker优先级1随后处理三份，再等待。批结束时produced/completed通常相等；断在give和计数更新中间可暂时不同。空等超时正常。若提高worker优先级，每次give后都可能处理，看到一串1也合理。

检查RCC的HSI就绪/PLL关闭及分频，调度后SysTick LOAD=15999、CTRL三控制位。此非频率实测；断点改变时序，PM0214说明调试暂停时SysTick停数，墙钟暂停不能当内核流逝时间。[PM0214]

## 14. 常见错误与排查

| 现象 | 先查什么 |
|---|---|
| 返回3便做3份后又take | pdFALSE仅减一，已多处理 |
| 批量后少处理 | 是否忽略pdTRUE返回数量 |
| delay和超时都停 | SysTick入口、时钟、TICKINT及运行期HAL调用 |
| give成功worker不跑 | 生产者是否让CPU、优先级是否饥饿 |
| 断言或HardFault | 句柄/TCB/栈/异常向量，别先怪通知 |
| 只有最新数据 | 是否连续覆盖共享槽，计数不等于负载 |

不要额外套锁“保护内核通知”：它已有临界区，锁不会自动修复共享数组协议。失败进入无HAL依赖停机环，不在HAL时间已冻结后用HAL_Delay恢复。

## 15. 自检、面试与延伸

自检：give5次后pdFALSE返回5、剩4、做1份；换pdTRUE返回5、剩0、负责5份。取5完成2时又到3，本地余3、内核待领取3，不能合并成只剩3。

基础面试：take为何无句柄？只领自己的通知。静态两任务为何还要idle回调？调度器自己的idle也需TCB/栈。返回0为何不一定故障？可能正常有限超时，不能推断生产者永久失效。

进阶面试：pdPASS是否说明无损？不说明消费或完成，也不保护uint32容量。为何不能替代互斥？没有持有者及优先级继承。回答时给共享数组覆盖反例，不只背“轻量”。

设计题：多传感器带时间戳记录交给两个worker，不能直接用同一任务计数；需保存每条负载、分配处理者、容量和满策略，队列更接近需求。若缓冲区配通知，须说明槽何时归还、是否可覆盖、次数和条数如何对应。

## 16. 能力迁移、总结与下一步

可迁移的是计数交接、单接收者所有权、批次算术、容量和证据边界。F4→F7须重查端口、时钟、异常入口；F4→H5须重查具体器件、执行环境、启动及工具链；F4→H7须重查具体核心、内存、时基及中断归属。不能照搬ARM_CM4F、HSI频率或15999。本次未重读这些系列资料，不把其缓存、安全域或多核特性当已核实结论；共享缓冲区迁移还要补一致性证据。

三句总结：计数归接收任务；pdFALSE减一却返回原总数，pdTRUE清零并把整批责任交给应用；次数不是负载也不是互斥。下一篇再讲静态对象寿命和RAM预算，之后才做EXTI→通知→任务。本响应不accept、不发布、不改旧状态。

## 17. 技术来源与自检证据

共6项第一方来源，accessed_at均为2026-10-24，表示本次实际重读而非全部重新联网下载。evidence-map.json仅是导航。官方资源文本仅作为数据读取，从未执行。

- [COUNTING] 官方计数通知页：official-notify-counting-body.js.txt，Example 1逐个消费、Example 2按返回数量批处理；新版indexed例子不采用。
- [TAKE] 官方ulTaskNotifyTake页：official-notify-take-body.js.txt，Parameters/Returns/Backward compatibility information；明确V10.4.0前单值边界。
- [STATIC] 官方xTaskCreateStatic页：official-static-task-body.js.txt，Parameters/Returns/Example usage；栈单位和存储寿命，断言细节以固定源码为准。
- [ST-PACK] 本机STM32Cube_FW_F4_V1.28.3：package.xml；Source/include/task.h:46、2023–2067、2124–2191；tasks.c:581–631、1975–2047、4635–4695、4783–4889；FreeRTOS.h配置检查和分配默认值；GCC/ARM_CM4F/portmacro.h类型/切换，port.c:40–47、361–379、488–505、679–696；HAL_Driver/Src/stm32f4xx_hal_rcc.c:284–345、591–724；stm32f4xx_hal.c:157–182、253–274、312–325、390–435。
- [RM0090] Rev22 May2026：仅读旧readings/ST-RM0090.txt，第81页表11、第7章图21、第218页时钟关系、7.2.2 HSI，未通读1741页。
- [PM0214] Rev10 March2020：仅读旧readings/ST-PM0214.txt，4.5–4.5.3节、PDF246–249页，SysTick24位/CTRL/LOAD/VAL与暂停调试行为。

主机记录只作补充证据，不列作技术第一方来源。目标工程未编译、未上板、GUI未运行；交父agent及后续审查者核对合同和代码集成，本文不作“已验证可运行”结论。

## Interview Practice

### 1. 工作任务已有3次待处理通知，连续调用ulTaskNotifyTake(pdFALSE, 0)三次，每次返回多少、剩余多少？为什么不能把每次返回值都当作本轮处理份数？

三次分别返回3、2、1，调用后计数分别为2、1、0。pdFALSE在非零时只消费一份，返回的是消费前计数，不是这次被取走的份数。每次成功只处理一份，共处理3份；若分别处理3、2、1份，会重复处理成6份。随后再无新通知时调用返回0，不能处理工作。

Scoring: 满分须同时给出返回值3/2/1、剩余2/1/0，以及每次只消费一份的理由；只背API名称但按返回值循环处理不得分；能说明0返回不代表一份工作可加理解分。

### 2. 将上题改成ulTaskNotifyTake(pdTRUE, 0)，第一次返回3，随后应用只执行一次工作。发生了什么？应如何建立一致的批次处理约定？

pdTRUE把已有通知计数从3清零并返回3。内核已一次取走整批计数，应用如果只处理一份，就遗漏本批另外两份工作。对于本文一通知对应一份工作的约定，应按返回值处理3份，或把剩余工作显式移交给另一个受管理的批次状态；不能期望下一次take再返回这两份。在批次处理期间到来的新通知形成新的待处理计数。

Scoring: 应识别清零与单次递减的差异，明确遗漏2份并由应用承担整批责任；把pdTRUE说成只取一份或声称新通知必然丢失均为关键错误。

### 3. 生产者要把不同的传感器样本交给两个消费者，还要求保护一个共享驱动。能否只用本文的计数型任务通知同时解决？请按职责拆分。

不能。本文计数型通知定位一个接收任务，只表达待处理次数，不独立存储每份样本，也不是向两个任务广播的机制，更不提供互斥量所有权和优先级继承。样本需要另有明确容量与所有权的数据通道，例如适合需求的队列或缓冲区；两个消费者的分发/复制语义需要明确设计；共享驱动的独占访问可另用适合任务上下文的互斥量。通知可以只作为某个接收者的唤醒手段，不能替代全部数据与互斥协议。

Scoring: 须分别指出单接收者、无独立样本负载、非互斥量三项边界，并给出合理职责拆分；不限定必须采用某一种队列或缓冲实现，但不得宣称通知具有优先级继承或广播保证。

### 4. 定义P为已成功计入通知的工作总数，C为已完成数，Q为通知中待取数，I为已取出但未完成数。在无溢出、无取消、初始为空时，应满足什么守恒关系？为何调试暂停时completed可能暂时领先producer中的sent一次，却未必是重复处理？

应满足P=C+Q+I。pdFALSE成功取走一份时Q减一、I加一，完成后I减一、C加一；pdTRUE则把整批从Q转移到I。这个关系要求各量含义一致并在可比较的一致观测点统计。本文生产者先give，再递增自己的sent变量；give可以立即唤醒并切换到更高优先级worker，worker可能在生产者执行sent++前完成。因此sent不是任意时刻的原子成功提交总数，调试器分步读到的计数也不是同步快照。不能仅凭这一瞬间差值认定重复消费。

Scoring: 应写出含I的守恒式并正确解释取走/完成两个阶段；必须联系先give后sent++与抢占说明暂时领先；只用P=C+Q而忽略在途工作，或把volatile当同步快照，不能得满分。

### 5. 如果生产速度长期超过工作任务处理速度，xTaskNotifyGive返回pdPASS是否足以证明没有丢工作？请结合32位计数边界与验证范围回答。

不足。pdPASS不表示业务已经完成，也不是无界容量或无损交付证明。固定V10.3.1递增32位无符号通知值，达到边界继续递增会回绕；长期积压还意味着延迟无上界。需要给出生产突发与消费能力上界、积压监测以及明确的背压、拒绝、合并或丢弃策略；若业务必须保留每份负载，应采用带容量和所有权协议的数据通道。主机计数断言只检验教学模型，不能证明真实调度及时性、目标固件或极端负载下的无损性。

Scoring: 须否定pdPASS等于完成/无损，指出32位回绕与持续过载两个风险，并提出可执行的容量或过载策略；仅说提高任务优先级不足以构成保证；应保留主机模型与目标验证边界。

### 6. 设计一个静态生产者到唯一工作任务的工作计数通道。工作没有独立负载，需要逐份处理。说明存储归属、启动顺序、消费策略、过载约定及验证计划；未提供板卡时你能汇报哪些结果？

一种合理方案是由组装模块常驻保存两个任务的StaticTask_t、栈、上下文和句柄，先创建worker并检查句柄，再把worker句柄注入producer上下文，创建producer成功后启动调度器，同时为idle提供静态存储。producer在任务上下文give给唯一worker；worker使用pdFALSE且仅在非零返回时处理一份，不根据旧计数重复处理。明确无删除/复用及无其他用途竞争通知的前提。根据最坏突发与服务时间约束积压，建立可观测的过载阈值与背压或业务拒绝策略，不能把32位计数当无限队列。验证先覆盖主机模型的0/1/多份、pdFALSE/pdTRUE差异及回绕边界，再在固定V10.3.1/ARM_CM4F目标工程核对配置、栈单位、HAL与RTOS时基交接，进行构建、运行和负载覆盖。没有这些目标证据时，只能汇报已生成并审查的参考实现、实际主机模型结果与待验证项，hardware_verified保持false；生成课程不能提高掌握度。

Scoring: 按五方面评估：常驻存储与依赖注入、先接收者后生产者且失败不继续、pdFALSE逐份消费、明确过载容量假设、分层验证与诚实证据边界。允许其他等价方案，但不得使用悬空局部存储、空句柄、按旧计数重复处理或未经上板宣称硬件通过。
