+++
title = "FreeRTOS 中断协作：EXTI 通知静态工作任务的完整链路"
date = "2026-10-24T00:00:33+08:00"
summary = "以STM32F407和固定FreeRTOS V10.3.1/GCC ARM_CM4F说明EXTI到FromISR通知再到任务的完整交接，给出静态对象、优先级编码、HSI16MHz启动与SysTick独占交接、错误路径和双轨实验；目标与GUI均未验证。"
tags = ["FreeRTOS", "STM32F407", "EXTI", "FromISR", "静态任务", "BASEPRI", "PendSV", "Host-Fake"]
categories = ["嵌入式"]
series = ["EmbeddedStudyPortable"]
generated_with_ai = true
hardware_verified = false
lesson_id = "ESP-2535a7fd2b72"
+++

<!-- generated-by: embedded-study-portable -->

# FreeRTOS 中断协作：EXTI→通知→静态工作任务

## 1. 唯一目标、前置与证据边界

能够在 STM32F407xx 参考实现中推演 EXTI→FromISR 任务通知→工作任务的延后处理链，正确设置可调用内核的中断优先级并解释中断退出时请求调度的条件与证据边界。

新概念只限计划中的三个：中断服务程序与工作任务之间的延后处理职责划分；Cortex-M 中断优先级编码与 FreeRTOS 内核调用边界；FromISR 唤醒标志到中断退出调度请求的传递。前置是GPIO/EXTI、向量表、NVIC、任务阻塞、通知和静态对象寿命。

参考STM32F407xx，PA0/EXTI0只是教学选项，非已知板载按键。固定包C:/Users/25108/STM32Cube/Repository/STM32Cube_FW_F4_V1.28.3的package.xml声明FW.F4.1.28.0+1.28.3，task.h确认V10.3.1，选GCC ARM_CM4F。[S1] 本次实际读取日2026-10-24；未目标编译、未GUI运行、未烧录上板或测波形，hardware_verified=false；以下是待目标工程编译的参考实现，Host Fake也未执行。

## 2. 为什么与完整调用流

ISR（中断服务程序）抢占正常程序，不应阻塞、拿互斥量或长时间打印；等待不能抢占它的中断推进条件，甚至可能死锁。ISR只确认和报告，任务无事阻塞、有事执行有界业务。延后指换上下文，不是固定等一个tick。

```text
PA0边沿→SYSCFG路由→EXTI.PR0→IMR→NVIC→EXTI0_IRQHandler
入口woken=pdFALSE→HAL_GPIO_EXTI_IRQHandler
先检查PR、W1C清PR→HAL_GPIO_EXTI_Callback
→vTaskNotifyGiveFromISR(worker,&同一woken)
→IRQ出口portYIELD_FROM_ISR→需要时请求PendSV→任务take返回
```

callback仍在ISR，禁止任务版通知、阻塞或HAL_Delay。同一链只通知一次，不叠加手写寄存器通知路线。固定hal_gpio.c:492–499先清再回调，callback看到PR已清正常。[S1]

take(pdFALSE)返回3只消费一份、余2；pdTRUE清零，须自行按返回值批处理。固定tasks.c:4635–4695、5026–5105确认give递增uint32_t，非饱和并可回绕。本任务独占通知用途；V10.3.1不使用任何Indexed API，官方缓存中的新接口不能套用。[S1][S4]

EXTI pending只有一位，已为1时多边沿可能合并，通知不能补回上游信息，禁止声称高速边沿无损。严格计数需另选硬件计数/捕获并论证速率。

give只在原任务等待通知、且优先级严格高于当前任务时置woken真，不会每次替调用者清零。入口初始化、链内累积、出口yield；Ready/运行中的worker可能只累积计数。portmacro.h:79–103仅请求PendSV，不直接执行任务；嵌套异常、屏蔽和调度挂起仍影响切换，标志真不等于已运行。[S1][S3]

## 3. 优先级边界与对象所有权

固定__NVIC_PRIO_BITS=4；NVIC_PRIORITYGROUP_4为全四位抢占、零子优先级，其HAL宏原值3不是4。HAL SetPriority接收未移位逻辑值6，经CMSIS编码成0x60；内核门槛5<<(8-4)=0x50，PendSV/SysTick等级15为0xF0。本配置5～15可调用这些FromISR，0～4更紧迫但禁止；阈值5不是所有工程定值。中断数值小更紧迫，任务数值大更优先，二者不可比较。[S1]

BASEPRI=0x50保护内核时屏蔽本配置等级5～15，0～4仍能穿透，所以不得触及这些内核结构。portmacro.h:191–233核对写入与恢复；port.c:287–367探测有效位，717–770检查当前IRQ编码和分组。保留configASSERT，不关闭它掩盖违规。PM0214§2.3支持紧迫度/分组，BASEPRI具体用法以端口源码为证。[S1][S3]

TCB/栈/上下文/句柄由event_worker.c静态持有，创建把上下文地址注入任务；idle内存由main.c静态提供。GPIO配置为同步写寄存器的局部参数，没有虚构的持久GPIO句柄。IRQ局部woken仅借给同步callback，返回撤销；不能跨向量或交异步回调。

头文件是声明，任务/IRQ是实现，静态对象是实例化，main创建与worker放行是组装，callback发送与任务消费是使用。先有效句柄、再运行调度器、再worker初始化/开IRQ。启动旧pending丢弃；清除到放行不是原子采集门，不承诺启动无损。

## 4. 时钟链、CubeMX与寄存器

HSI标称16MHz→SYSCLK直接HSI、PLL关闭→AHB/1得HCLK16MHz→APB1/APB2均/1得PCLK16MHz，非实测频率。GPIOA由AHB1ENR.GPIOAEN门控，SYSCFG由APB2ENR.SYSCFGEN门控，对应RSTR复位位；复位启动不再次整组强制复位，避免影响其他使用者。EXTI不虚构独立计数时钟或RCC门控，不套定时器倍频。[S1][S2]

RM表11的F407各供电列0WS上限高于16MHz，选FLASH_LATENCY_0；统一PREFETCH_ENABLE=0满足低于2.1V禁预取要求，真实供电仍待核实。[S2: §3.5.1]

HAL初始化/时钟等待依赖HAL_GetTick，必须先有HAL毫秒tick。全部初始化后关全局中断、HAL_SuspendTick、停SysTick并清VAL/pending，再交RTOS；运行入口只调用RTOS，不HAL_IncTick。端口LOAD=16000000/1000-1=15999。交接后禁HAL_Delay及依赖HAL_GetTick超时的API，不HAL_ResumeTick或InitTick抢回时基。[S1][S3: §4.5]

CubeMX未实际运行：按真实型号/封装和调试器建工程；HSI、无PLL、总线/1；确认PA0电平/接线后选上升沿/下拉；GROUP_4、IRQ6/子0；静态V10.3.1、通知/断言开启；不保留重复任务、提前开IRQ或TIM覆盖时基。生成文件中SVC/PendSV/SysTick/EXTI0仅各一个入口。

HAL_GPIO_Init对应MODER/PUPDR、SYSCFG.EXTICR、RTSR/FTSR、IMR/EMR；NVIC对应AIRCR/IP/ISER。LL_EXTI_EnableIT_0_31对应IMR，GenerateSWI_0_31对应SWIER，ClearFlag_0_31直接写PR。W1C必须EXTI->PR=mask，禁止PR|=mask误清其他pending，也不用&=~mask。LL是替代理解入口，不是第二条通知链。[S1]

## 5. 最小完整参考代码


依赖固定 CMSIS、F407 启动/system 文件、HAL 公共/GPIO/CORTEX/RCC/Flash 及所需依赖、FreeRTOS tasks.c/list.c 和 GCC ARM_CM4F port.c。链接脚本按实际芯片提供；不链接 heap_x.c。软件定时器关闭，不需要 Timer task 内存回调。以下分别放入指定文件，替代相应生成入口，不与已有同名强定义叠加。

### 8.1 FreeRTOSConfig.h

```c
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H
#include <stdint.h>
#include "stm32f4xx.h"
void App_Fatal(uint32_t code);
#define configUSE_PREEMPTION 1
#define configUSE_TIME_SLICING 1
#define configCPU_CLOCK_HZ 16000000UL
#define configTICK_RATE_HZ 1000U
#define configMAX_PRIORITIES 5
#define configMINIMAL_STACK_SIZE 128U
#define configMAX_TASK_NAME_LEN 16
#define configUSE_16_BIT_TICKS 0
#define configIDLE_SHOULD_YIELD 1
#define configUSE_TICKLESS_IDLE 0
#define configSUPPORT_STATIC_ALLOCATION 1
#define configSUPPORT_DYNAMIC_ALLOCATION 0
#define configUSE_TASK_NOTIFICATIONS 1
#define configUSE_MUTEXES 0
#define configUSE_RECURSIVE_MUTEXES 0
#define configUSE_COUNTING_SEMAPHORES 0
#define configQUEUE_REGISTRY_SIZE 0
#define configUSE_TIMERS 0
#define configUSE_CO_ROUTINES 0
#define configUSE_IDLE_HOOK 0
#define configUSE_TICK_HOOK 0
#define configCHECK_FOR_STACK_OVERFLOW 2
#define INCLUDE_vTaskSuspend 1
#define INCLUDE_uxTaskGetStackHighWaterMark 1
#define configPRIO_BITS __NVIC_PRIO_BITS
#define configLIBRARY_LOWEST_INTERRUPT_PRIORITY 15U
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY 5U
#define configKERNEL_INTERRUPT_PRIORITY (15U << (8U-configPRIO_BITS))
#define configMAX_SYSCALL_INTERRUPT_PRIORITY (5U << (8U-configPRIO_BITS))
#if __NVIC_PRIO_BITS != 4U
#error priority_bits_must_be_4
#endif
#define configASSERT(x) do { if (!(x)) App_Fatal(90U); } while (0)
#define vPortSVCHandler SVC_Handler
#define xPortPendSVHandler PendSV_Handler
/* SysTick不作宏映射，由main.c唯一分派。 */
#endif
```

### 8.2 event_worker.h 与 event_worker.c

```c
/* event_worker.h */
#ifndef EVENT_WORKER_H
#define EVENT_WORKER_H
#include <stdint.h>
uint32_t EventWorker_Create(void);
#endif
```

```c
/* event_worker.c */
#include <stddef.h>
#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"
#include "event_worker.h"
typedef struct { volatile uint32_t processed, timeouts; } Context;
static StaticTask_t s_tcb;
static StackType_t s_stack[256];
static Context s_ctx;
static TaskHandle_t s_worker;
static uint32_t s_armed;
/* 仅本EXTI0同步调用链借用，不与其他向量共享。 */
static BaseType_t *s_woken;

static void ArmExti(void)
{
  GPIO_InitTypeDef g = {0};
  configASSERT(s_worker != NULL);
  taskENTER_CRITICAL();
  HAL_NVIC_DisableIRQ(EXTI0_IRQn);
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_SYSCFG_CLK_ENABLE();
  g.Pin = GPIO_PIN_0;
  g.Mode = GPIO_MODE_IT_RISING;
  g.Pull = GPIO_PULLDOWN;
  g.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOA, &g);
  CLEAR_BIT(EXTI->IMR, GPIO_PIN_0);
  HAL_NVIC_SetPriority(EXTI0_IRQn, 6U, 0U);
  __HAL_GPIO_EXTI_CLEAR_IT(GPIO_PIN_0);
  HAL_NVIC_ClearPendingIRQ(EXTI0_IRQn);
  s_armed = 1U;
  SET_BIT(EXTI->IMR, GPIO_PIN_0);
  HAL_NVIC_EnableIRQ(EXTI0_IRQn);
  taskEXIT_CRITICAL();
}
static void Worker(void *arg)
{
  Context *ctx = (Context *)arg;
  configASSERT(ctx != NULL);
  ArmExti(); /* 已在调度器运行后的任务上下文。 */
  for (;;) {
    if (ulTaskNotifyTake(pdFALSE, pdMS_TO_TICKS(1000U)) != 0U)
      ctx->processed++; /* 一份有界业务。 */
    else
      ctx->timeouts++;
  }
}
uint32_t EventWorker_Create(void)
{
  configASSERT(s_worker == NULL);
  HAL_NVIC_DisableIRQ(EXTI0_IRQn);
  s_worker = xTaskCreateStatic(Worker, "exti", 256U, &s_ctx,
                 2U, s_stack, &s_tcb);
  return s_worker != NULL ? 1U : 0U;
}
void EXTI0_IRQHandler(void)
{
  BaseType_t xHigherPriorityTaskWoken = pdFALSE;
  configASSERT(s_woken == NULL);
  s_woken = &xHigherPriorityTaskWoken;
  HAL_GPIO_EXTI_IRQHandler(GPIO_PIN_0);
  s_woken = NULL;
  portYIELD_FROM_ISR(xHigherPriorityTaskWoken);
}
void HAL_GPIO_EXTI_Callback(uint16_t pin)
{
  if (pin == GPIO_PIN_0) {
    configASSERT(__get_IPSR() == (uint32_t)EXTI0_IRQn + 16U);
    configASSERT(s_woken != NULL && s_armed && s_worker != NULL);
    vTaskNotifyGiveFromISR(s_worker, s_woken);
  }
}
```

### 8.3 main.c：HSI启动、idle内存、HAL tick交接

```c
#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"
#include "event_worker.h"
static volatile uint32_t s_rtos_tick;
volatile uint32_t g_fatal_code;
static StaticTask_t s_idle_tcb;
static StackType_t s_idle_stack[configMINIMAL_STACK_SIZE];
void App_Fatal(uint32_t code)
{
  __disable_irq();
  g_fatal_code = code;
  for (;;) { __NOP(); }
}
void vApplicationStackOverflowHook(TaskHandle_t task, char *name)
{
  (void)task; (void)name;
  App_Fatal(91U);
}
void vApplicationGetIdleTaskMemory(StaticTask_t **tcb,
                  StackType_t **stack, uint32_t *depth)
{
  *tcb = &s_idle_tcb;
  *stack = s_idle_stack;
  *depth = configMINIMAL_STACK_SIZE;
}
void xPortSysTickHandler(void);
void SysTick_Handler(void)
{
  if (s_rtos_tick) xPortSysTickHandler();
  else HAL_IncTick();
}
static void ClockHSI16(void)
{
  RCC_OscInitTypeDef o = {0};
  RCC_ClkInitTypeDef c = {0};
  o.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  o.HSIState = RCC_HSI_ON;
  o.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  o.PLL.PLLState = RCC_PLL_OFF;
  if (HAL_RCC_OscConfig(&o) != HAL_OK) App_Fatal(11U);
  c.ClockType = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK |
          RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
  c.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  c.AHBCLKDivider = RCC_SYSCLK_DIV1;
  c.APB1CLKDivider = RCC_HCLK_DIV1;
  c.APB2CLKDivider = RCC_HCLK_DIV1;
  if (HAL_RCC_ClockConfig(&c, FLASH_LATENCY_0) != HAL_OK)
    App_Fatal(12U);
  if (HAL_InitTick(TICK_INT_PRIORITY) != HAL_OK) App_Fatal(13U);
  if (SystemCoreClock != configCPU_CLOCK_HZ) App_Fatal(14U);
}
int main(void)
{
  /* 复位启动，不接管未知bootloader时钟/中断状态。 */
  HAL_NVIC_DisableIRQ(EXTI0_IRQn);
  if (HAL_Init() != HAL_OK) App_Fatal(10U);
  if (HAL_InitTick(TICK_INT_PRIORITY) != HAL_OK) App_Fatal(15U);
  ClockHSI16();
  HAL_NVIC_SetPriorityGrouping(NVIC_PRIORITYGROUP_4);
  /* 所有HAL超时初始化到此完成，之后不再调用。 */
  if (!EventWorker_Create()) App_Fatal(20U);
  __disable_irq();
  HAL_SuspendTick();
  SysTick->CTRL = 0U;
  SysTick->VAL = 0U;
  SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk;
  s_rtos_tick = 1U;
  __DSB(); __ISB();
  /* 由固定端口启动首任务时恢复中断。 */
  vTaskStartScheduler();
  App_Fatal(21U);
}
```

配置HAL公共/CORTEX/RCC/GPIO/FLASH及依赖，HSI_VALUE=16000000、TICK_INT_PRIORITY=15、PREFETCH_ENABLE=0。Pin/Mode/Pull选教学输入、上升沿与空闲低；Speed不是输入滤波，HAL仅输出/复用模式写OSPEEDR。HAL初始化暂放行IMR时NVIC仍禁用且在临界区。woken借用限唯一EXTI0同步链，不得跨向量/异步使用。worker栈1024字节、idle512字节，另计TCB/内核/MSP并核验高水位。HAL_Init/ClockConfig不传播InitTick失败，故显式复核；SuspendTick只关TICKINT，还须停止并清pending。全部HAL等待在创建任务前完成，停HAL tick后不再使用其超时API。


## 6. 能力地图、实验与错误路径

基础为本课选沿/确认/任务交接；进阶为同序号端口路由择一、双边沿和共享向量逐线分派，落在race-condition/消抖课。高级EMR事件不同于IMR中断，不必进入本课callback；WFE/低功耗唤醒、时钟恢复与任务运行分阶段，留low-power课。SWIER用于隔离接线但不证明电气。跨外设Timer→ADC→DMA→任务需另查状态位与缓冲区所有权，留集成课，本文不实现第二条链。

F4其他器件重查线/封装/向量/勘误；F7重查端口、缓存与可见性；H5重查安全归属/权限/路由；H7重查精确子系列、核数、域与共享存储。这些是待查项，不是已核实的系列结论，不能外推F407寄存器、频率、位数或HAL签名。

Host Fake练习只模拟策略，本次未运行，不证明NVIC/BASEPRI/时延：

```python
ready, enabled, pending, count = False, False, 0, 0
trace = []
def irq(priority=6, waiting=True, higher=True):
  global pending, count
  woken = False
  if enabled and pending & 1:
    assert ready and 5 <= priority <= 15
    pending &= ~1  # 模拟W1C效果，不是目标寄存器写法
    trace.append('ack')
    count = (count + 1) & 0xffffffff
    trace.append('notify')
    woken = waiting and higher
  return woken
assert not irq()
ready = enabled = True
pending = 2
assert not irq()  # 未匹配线
pending |= 1
pending |= 1  # 多边沿合并
assert irq() and count == 1 and pending == 2
assert trace == ['ack', 'notify']
```

再测未ready却放行应拒绝、priority4应拒绝、下一入口woken重置，以及三次edge/irq交错与三次edge挤一次irq的区别；加take减一/清零练习。

目标实验均未做：按真实芯片提供启动/链接文件，固定头和实现不混版本；GCC用匹配Cortex-M4/Thumb/FPU参数（-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16），浮点ABI与库一致。构建查map、静态栈/TCB与向量，再按实际调试器烧录并保存日志。worker阻塞后查CFGR、LOAD15999、IRQ0x60、内核异常0xF0和HAL tick冻结/RTOS tick推进。软件触发SWIER，观察callback前PR清、woken、PendSV与业务计数；确认板级PA0后才接合法低速输入并共地。

受控实验：非生产可复位工程改IRQ4，预期端口断言后恢复6；单独去yield观察可能推迟到其他调度点，不断言永不运行。断点影响时序，不据此测微秒延迟或证明高速无损。

RCC卡住先查HAL tick/屏蔽；启动断言查句柄/分组/等级；持续IRQ查W1C和抖动；重复业务查双通知；共享向量查误分派；任务不运行查状态/通知用途/yield。GPIO/NVIC为void不编造HAL_ERROR；RCC失败、创建失败与调度器返回均停止记录错误，不用ISR阻塞日志掩盖。

## 7. 自检、面试与下一步

解释为何句柄有效仍不能main提前开IRQ；为何callback见PR清仍应通知；take(pdFALSE)返回5应做一份余4；为何十条边沿可只报告一次；HAL tick冻结后为何超时API可卡住。

面试用因果回答：FromISR不是任意IRQ可用，应讲位数/分组/编码/BASEPRI；woken真不等于已切换，应追踪出口宏→ICSR→PendSV；PR=0b11只清bit0应直接写0b01。源码、主机模型、目标构建、上板观察四层证据不能冒充。

总结是短ISR、静态寿命、合法优先级和单一时基所有权。下一步研究共享向量与采集开始握手：启动前输入也需保留时谁控制信号源？处理赶不上应合并、拒绝还是改硬件？不额外引入队列/DMA，不更新状态或掌握度。

## 8. 一手来源与阅读范围

实际读取日2026-10-24指本地材料/缓存，非重新下载。S1为固定包package.xml、task.h、tasks.c通知函数、完整ARM_CM4F端口、HAL GPIO/Cortex/RCC与时基函数、LL EXTI和CMSIS位数；S2为RM0090 Rev22 May2026缓存§3.5.1表11/§3.9.1/§7.2.2/§7.2.6及RCC页，缺EXTI正文，不声称已读；S3为PM0214 Rev10 March2020缓存§2.1已有页/§2.3/§4.4.3/§4.4.8/§4.5；S4为official-notify-counting-body.js.txt计数说明和Example1/2，只读不执行。EXTI控制路径依据S1，不从源码推导电气保证；新Indexed示例不作旧版接口。当前仍未目标编译、GUI未跑、未上板，hardware_verified=false。

## Interview Practice

### 1. 本课NVIC使用4个优先级位、NVIC_PRIORITYGROUP_4，最大可调用系统API的逻辑中断优先级阈值为5。EXTI设为6能否调用vTaskNotifyGiveFromISR？设为4呢？configMAX_SYSCALL_INTERRUPT_PRIORITY应如何编码？

在这些前提下，逻辑优先级6可调用该FromISR API，逻辑优先级4不可以。Cortex-M数值越小越紧迫，0至4位于这条内核API边界之上；5至15在本配置允许范围内。寄存器格式的阈值编码为5左移(8-4)位，即0x50；逻辑6编码为0x60。HAL/CMSIS设置函数的未移位逻辑数与FreeRTOS寄存器格式宏不能混用。NVIC_PRIORITYGROUP_4表示4位抢占、0位子优先级，其HAL宏值不是要求直接写入逻辑优先级4。

Scoring: 须正确判断6允许、4禁止，并给出0x50；必须解释数值越小越紧迫和逻辑值/寄存器格式差异。仅给数字却把逻辑5当成编码0x05，或把分组宏值当中断优先级，不能得满分。

### 2. EXTI pending寄存器使用写1清除。若只想清某一条线，为何不能写EXTI->PR |= mask？HAL路径中清除和回调的先后顺序是什么？

读改写会先读出其他已置1的pending位，再把这些1一同写回；写1清除语义使不属于本次目标的pending也可能被意外清掉。应仅写目标掩码EXTI->PR = mask。本课固定HAL实现先检查目标pending，再以W1C清除目标位，随后调用HAL_GPIO_EXTI_Callback。IRQ入口、HAL分发和回调各自职责要区分，不能在回调中再用错误的读改写扩大清除范围。

Scoring: 应解释读回其他pending为1后写回导致误清，而不只是背诵禁止|=；给出直接写mask并指出先清后回调。把PR当普通可任意置零寄存器是关键错误。

### 3. 为什么在一次IRQ入口把xHigherPriorityTaskWoken初始化为pdFALSE，并把它交给vTaskNotifyGiveFromISR后在出口调用portYIELD_FROM_ISR？这是否表示worker就在回调函数内部执行？

该变量记录本次中断处理链是否唤醒了需要切换的更高优先级任务，入口初始化一次，多个FromISR调用共用并累积结果，不能中途重置已为真的值。IRQ出口根据最终值请求让出，固定端口可挂起PendSV；内核在合适的异常退出/调度点切换到worker，并不是在HAL回调中普通函数调用worker。ISR只完成必要确认、通知与让出，较长业务放到任务上下文。

Scoring: 应包含入口一次初始化、链内累积、出口条件让出与PendSV/调度四点；不得把worker当回调内直接执行，也不能每次FromISR前清零导致丢失先前切换请求。

### 4. 引脚产生3个边沿，但EXTI pending尚未被清除期间它们合并成一个置位。随后ISR成功give一次、worker处理一次，能否认定通知计数丢了2次？换成更大的任务队列能保证逐边沿无损吗？

不能把这两次损失归因于通知计数。EXTI单pending位已经在上游把多个边沿合并，ISR只能观察到一次待处理状态，成功通知一次与其观察一致。下游更大的通知计数或队列无法重建从未被上游区分记录的信息。如果业务要求逐事件数量、时间戳或严格无损，应基于输入速率、最坏屏蔽/服务时间和硬件能力选择能保留信息的捕获、计数或带缓冲采集方案，并验证容量与过载策略；具体外设实现需另查目标资料。

Scoring: 须定位丢信息发生在EXTI pending合并，而非凭空认定FreeRTOS丢通知；指出下游队列不能恢复上游信息。允许多种硬件方案，但必须有速率/容量和验证前提，不接受单靠提高软件优先级的无损保证。

### 5. 工程把HAL和FreeRTOS都接到SysTick后，启动RCC配置能运行，但任务中HAL_Delay不返回。应怎样核查本课的时基所有权？HSI16MHz、1kHz tick时理论LOAD是多少？

先确认唯一SysTick向量和唯一运行期所有者。本课启动HAL/RCC超时初始化阶段保留HAL tick，完成后停SysTick并清VAL和pending，在中断关闭下切换阶段，运行期仅由RTOS拥有SysTick；不能重复定义向量或同时随意叠加两套入口。交接后HAL的uwTick冻结，所以任务中禁止HAL_Delay及其他依赖HAL_GetTick推进超时的API；不能只补一个延时调用就忽视其他HAL超时路径。若业务需要运行期HAL时基，应单独设计适配并复核优先级，而非未经审查改本文方案。16MHz处理器时钟除以1000再减1得到LOAD15999，这是理论值，需目标寄存器/测量验证。

Scoring: 应说明启动保留HAL、交接清理和运行期唯一RTOS三阶段，定位冻结uwTick导致等待不前进，并给出15999；需覆盖HAL_GetTick类超时而不只HAL_Delay。不得宣称仅网站构建即可证明该中断交接正确。

### 6. 为一个尚未指定板卡的STM32F407xx输入设计EXTI到静态worker的参考链路。请说明依赖组装、放行时序、ISR/任务职责、失败路径与验收条件，并解释为何现在还不能说已上板通过。

由组装模块常驻保存worker的TCB、栈、上下文与句柄，先成功创建worker再启动调度器；在调度器已运行的受控初始化阶段完成实际输入配置和pending清理，核对合法的逻辑优先级与分组后才使能EXTI/NVIC，避免ISR访问空句柄或在调度启动前请求切换。示例输入端口、引脚、上下拉和有效边沿由板级电路填写，不凭空假定。链路为EXTI IRQ到HAL_GPIO_EXTI_IRQHandler，W1C确认后进入回调，回调通过vTaskNotifyGiveFromISR唤醒唯一worker，在IRQ出口用累积的woken请求让出，经PendSV调度，worker用pdFALSE逐份处理。ISR不做阻塞、格式化输出或长业务。创建/配置失败时不放行中断，保留故障信息并停在明确路径；非法优先级不能靠关闭断言绕过。验收分主机合同模型、固定包目标编译/链接、向量与优先级寄存器核查、板级边沿/IRQ/worker观测及最坏负载测试，并明确pending合并与过载边界。当前只有审查后的参考实现和实际主机模型证据，未目标构建、烧录、运行或测量，hardware_verified必须为false，Hugo发布成功也不改变这一状态。

Scoring: 重点评估存储生命周期与注入、调度后受控放行、合法FromISR优先级、W1C与woken出口处理、任务延后业务、失败不放行和分层验收。允许合理的独立初始化任务或等价组装方式；空句柄中断、提前放行、ISR阻塞或未经证据宣称无损/硬件通过为关键错误。
