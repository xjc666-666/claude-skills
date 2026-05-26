/**
 *****************************************************************************
 *  @file    main.c
 *  @brief   STM32F103 工程模板骨架
 *  @author  stm32-keil skill
 *  @date    2026/5/24
 *  @version 1.0
 *****************************************************************************
**/

#include "stm32f10x.h"
#include "Delay.h"
#include "sys.h"
#include "usart.h"

int main(void) {
    SystemInit();
    uart_init(115200);

    while (1) {
    }
}
