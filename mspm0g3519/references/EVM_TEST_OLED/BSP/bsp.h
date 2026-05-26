#ifndef BSP_H
#define BSP_H

/******************系统头文件***************/
#include <ti/devices/msp/msp.h>
#include <ti/driverlib/driverlib.h>
#include <ti/driverlib/m0p/dl_core.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include "math.h"
#include "ti_msp_dl_config.h"
/*******************************************/
#define u8 unsigned char
#define u32 unsigned int
/******************用户自定义头文件*********/
#include "LED/led.h"
#include "UART0/uart0.h"
#include "TimerG6_PWM_RGB/timerG6_pwm_rgb.h"
#include "KEY/key.h"
#include "KeyBoard/keyboard.h"
//#include "SPI0_LCD/lcd.h"
//#include "SPI0_LCD/lcd_init.h"
#include "SPI0_OLED/spi0_oled.h"
#include "TimerA1/TimerA1.h"
#include "SPI1/spi1.h"
#include "IMU.h"
#include "ADC0/adc0.h"
#include "W25Q64/w25q64.h"
#include "MYI2C1/myi2c.h"
#include "TIMERG0_LED_BUZZER/timerG0_led_buzzer.h"
/*******************************************/

#endif
