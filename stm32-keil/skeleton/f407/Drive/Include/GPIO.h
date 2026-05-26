#ifndef __GPIO_H
#define __GPIO_H

#define PAout(x) Config_GPIO(GPIOA, 1 << x, GPIO_MODE_OUTPUT)
#define PBout(x) Config_GPIO(GPIOB, 1 << x, GPIO_MODE_OUTPUT)
#define PCout(x) Config_GPIO(GPIOC, 1 << x, GPIO_MODE_OUTPUT)
#define PDout(x) Config_GPIO(GPIOD, 1 << x, GPIO_MODE_OUTPUT)
#define PEout(x) Config_GPIO(GPIOE, 1 << x, GPIO_MODE_OUTPUT)
#define PFout(x) Config_GPIO(GPIOF, 1 << x, GPIO_MODE_OUTPUT)
#define PGout(x) Config_GPIO(GPIOG, 1 << x, GPIO_MODE_OUTPUT)

#define PAin(x) Config_GPIO(GPIOA, 1 << x, GPIO_MODE_INPUT)
#define PBin(x) Config_GPIO(GPIOB, 1 << x, GPIO_MODE_INPUT)
#define PCin(x) Config_GPIO(GPIOC, 1 << x, GPIO_MODE_INPUT)
#define PDin(x) Config_GPIO(GPIOD, 1 << x, GPIO_MODE_INPUT)
#define PEin(x) Config_GPIO(GPIOE, 1 << x, GPIO_MODE_INPUT)
#define PFin(x) Config_GPIO(GPIOF, 1 << x, GPIO_MODE_INPUT)
#define PGin(x) Config_GPIO(GPIOG, 1 << x, GPIO_MODE_INPUT)

typedef enum {
    GPIO_MODE_INPUT,
    GPIO_MODE_OUTPUT
} GPIO_Mode_TypeDef;

void Config_GPIO(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin, GPIO_Mode_TypeDef Mode);
void Set_GPIO_High(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin);
void Set_GPIO_Low(GPIO_TypeDef* GPIOx, uint16_t GPIO_Pin);

#endif
