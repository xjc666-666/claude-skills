#ifndef __LED_H
#define __LED_H

#include "sys.h"



#define LED PAout(15)	// PA15




#define PA0 PAout(0)	// PA0
#define PA1 PAout(1)	// PA1
#define PA2 PAout(2)	// PA2
#define PA3 PAout(3)	// PA3
#define PA4 PAout(4)	// PA4
#define PA5 PAout(5)	// PA5
#define PA6 PAout(6)	// PA6
#define PA7 PAout(7)	// PA7
#define PA8 PAout(8)	// PA8
#define PA9 PAout(9)	// PA9
#define PA10 PAout(10)	// PA10
#define PA11 PAout(11)	// PA11
#define PA12 PAout(12)	// PA12
#define PA13 PAout(13)	// PA13
#define PA14 PAout(14)	// PA14
#define PA15 PAout(15)	// PA15

#define PB0 PBout(0)	// PB0
#define PB1 PBout(1)	// PB1
#define PB2 PBout(2)	// PB2
#define PB3 PBout(3)	// PB3
#define PB4 PBout(4)	// PB4
#define PB5 PBout(5)	// PB5
#define PB6 PBout(6)	// PB6
#define PB7 PBout(7)	// PB7
#define PB8 PBout(8)	// PB8
#define PB9 PBout(9)	// PB9
#define PB10 PBout(10)	// PB10
#define PB11 PBout(11)	// PB11
#define PB12 PBout(12)	// PB12
#define PB13 PBout(13)	// PB13
#define PB14 PBout(14)	// PB14
#define PB15 PBout(15)	// PB15

#define PC13 PCout(13)	// PC13
#define PC14 PCout(14)	// PC14
#define PC15 PCout(15)	// PC15

void LED_Init(void);
void gpio_Init(void);


#endif




