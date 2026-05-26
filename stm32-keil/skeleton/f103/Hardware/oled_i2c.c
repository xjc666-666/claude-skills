/**
 *****************************************************************************
 *  @file    oled_i2c.c
 *  @brief   0.96寸 SSD1306 I2C OLED (PB6=SCL, PB7=SDA, 开漏)
 *           直接写屏, 8x16 ASCII 字库
 *  @author  stm32-keil skill
 *  @date    2026/5/24
 *****************************************************************************
**/

#include "stm32f10x.h"
#include "oled_i2c.h"
#include "OLED_Font.h"

/* ===== 软件 I2C: PB6=SCL, PB7=SDA (开漏, 无需模式切换) ===== */

#define OLED_SCL(x)  GPIO_WriteBit(GPIOB, GPIO_Pin_6, (BitAction)(x))
#define OLED_SDA(x)  GPIO_WriteBit(GPIOB, GPIO_Pin_7, (BitAction)(x))

static void OLED_I2C_Init(void) {
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB, ENABLE);
    GPIO_InitTypeDef g;
    g.GPIO_Mode  = GPIO_Mode_Out_OD;   /* 开漏: SDA=1 浮空, 从机能拉低 ACK */
    g.GPIO_Speed = GPIO_Speed_50MHz;
    g.GPIO_Pin   = GPIO_Pin_6; GPIO_Init(GPIOB, &g);
    g.GPIO_Pin   = GPIO_Pin_7; GPIO_Init(GPIOB, &g);
    OLED_SCL(1); OLED_SDA(1);
}

static void I2C_Start(void) {
    OLED_SDA(1); OLED_SCL(1);
    OLED_SDA(0); OLED_SCL(0);
}

static void I2C_Stop(void) {
    OLED_SDA(0); OLED_SCL(1); OLED_SDA(1);
}

static void I2C_SendByte(uint8_t Byte) {
    uint8_t i;
    for (i = 0; i < 8; i++) {
        OLED_SDA(Byte & (0x80 >> i));
        OLED_SCL(1); OLED_SCL(0);
    }
    OLED_SCL(1); OLED_SCL(0);  /* ACK 时钟 */
}

/* ===== SSD1306 命令/数据 ===== */

static void WriteCmd(uint8_t cmd) {
    I2C_Start(); I2C_SendByte(0x78);
    I2C_SendByte(0x00); I2C_SendByte(cmd); I2C_Stop();
}

static void WriteData(uint8_t dat) {
    I2C_Start(); I2C_SendByte(0x78);
    I2C_SendByte(0x40); I2C_SendByte(dat); I2C_Stop();
}

static void SetCursor(uint8_t Y, uint8_t X) {
    WriteCmd(0xB0 | Y);
    WriteCmd(0x10 | ((X & 0xF0) >> 4));
    WriteCmd(0x00 | (X & 0x0F));
}

/* ===== 初始化 ===== */

void OLED_Init(void) {
    OLED_I2C_Init();

    WriteCmd(0xAE); /* 关闭显示 */
    WriteCmd(0xD5); WriteCmd(0x80);
    WriteCmd(0xA8); WriteCmd(0x3F);
    WriteCmd(0xD3); WriteCmd(0x00);
    WriteCmd(0x40);
    WriteCmd(0x8D); WriteCmd(0x14);
    WriteCmd(0x20); WriteCmd(0x00);
    WriteCmd(0xA1); WriteCmd(0xC8);
    WriteCmd(0xDA); WriteCmd(0x12);
    WriteCmd(0x81); WriteCmd(0xCF);
    WriteCmd(0xD9); WriteCmd(0xF1);
    WriteCmd(0xDB); WriteCmd(0x40);
    WriteCmd(0xA4); WriteCmd(0xA6);
    WriteCmd(0x2E);
    WriteCmd(0xAF); /* 开启显示 */

    OLED_Clear();
}

/* ===== 清屏 ===== */

void OLED_Clear(void) {
    uint8_t i, j;
    for (j = 0; j < 8; j++) {
        SetCursor(j, 0);
        for (i = 0; i < 128; i++) WriteData(0x00);
    }
}

/* ===== 显示字符 (8x16, 4行×16列) ===== */

void OLED_ShowChar(uint8_t Line, uint8_t Column, char Char) {
    uint8_t i;
    SetCursor((Line - 1) * 2, (Column - 1) * 8);
    for (i = 0; i < 8; i++)
        WriteData(OLED_F8x16[Char - ' '][i]);
    SetCursor((Line - 1) * 2 + 1, (Column - 1) * 8);
    for (i = 0; i < 8; i++)
        WriteData(OLED_F8x16[Char - ' '][i + 8]);
}

void OLED_ShowString(uint8_t Line, uint8_t Column, char *String) {
    uint8_t i;
    for (i = 0; String[i] != '\0'; i++)
        OLED_ShowChar(Line, Column + i, String[i]);
}

void OLED_ShowNum(uint8_t Line, uint8_t Column, uint32_t Number, uint8_t Length) {
    char buf[12]; uint8_t i;
    for (i = 0; i < Length; i++) {
        buf[Length - 1 - i] = (char)(Number % 10 + '0');
        Number /= 10;
    }
    buf[Length] = '\0';
    OLED_ShowString(Line, Column, buf);
}
