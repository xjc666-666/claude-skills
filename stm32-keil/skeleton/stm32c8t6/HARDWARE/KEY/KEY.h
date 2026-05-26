#ifndef __KEY_h
#define __KEY_h
 
 
#include "stm32f10x.h"
#include "delay.h"
 
 
void Keyboard_GPIO_Config(void);		//初始化 矩阵按键的I/O口
 
void keyboard_scan(u16 *key_val);		//矩阵按键扫描函数
 
u16 fetch_key_value(void);				//返回自定义按键数值
 
 
#endif
