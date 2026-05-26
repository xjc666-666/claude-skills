#ifndef __USART_H
#define __USART_H

void USART1_Init(u32 bound);
void USART1_IRQHandler(void);
void USART2_Init(u32 bound);
void USART3_Init(u32 bound);
void USART6_Init(u32 bound);
void USART_Sendbyte(USART_TypeDef* usrUSARTx, uint8_t data);
void USART_SendDouble(USART_TypeDef* usrUSARTx, double val, uint8_t decimal_places);

extern int USART_RxData;
extern int USART_RxFlag;

#endif

