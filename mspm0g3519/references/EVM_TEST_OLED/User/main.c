/*------------------------------------------------------------------------------
 * 工程名： evm_test
 * 作者： 孔
 * 创建时间： 2025.12.26.18.25
 * 版本： V1.0
 * 描述： 该工程基于TI-M0SDK-2_08_00_03生成，推荐sysconfig-1.25.0配套使用；目前配置
 时钟树，使用外部40M晶振作为时钟源，时钟分支皆以最高频率运行，其主要为EVM测试代码。
 *----------------------------------------------------------------------------*/
#include "ti_msp_dl_config.h"
#include "bsp.h"
#include "SPI0_OLED/oledfont_bmp.h"

uint8_t keyboardm=0;
uint16_t w25q64_id=0;
uint16_t AT240C2_data=0;
float ypr[3]; // 上传yaw pitch roll的值
uint32_t adc0_data[4]={0};




int main(void)
{
    SYSCFG_DL_init();
    uart0_init(115200);
	timerg6_pwm_rgb_init();
	key_init();
	OLED_Init();
	OLED_Clear();
//	LCD_Init();
//	LCD_Fill(0,0,LCD_W,LCD_H,BLACK);
//	LCD_ShowString(20,20,"flash_id:",RED,BLACK,16,1);
//	LCD_ShowString(20,40,"eeprom_0x22:",RED,BLACK,16,1);
//	LCD_ShowString(20,60,"adc_a1:",RED,BLACK,16,1);
//	LCD_ShowString(20,80,"keyboard:",RED,BLACK,16,1);
//	LCD_ShowString(20,100,"dac_adc_a3:",RED,BLACK,16,1);
	OLED_ShowString(0,0,"F:");
	OLED_ShowString(0,2,"E:");
	OLED_ShowString(0,4,"A:");
	OLED_ShowString(0,6,"D:");


	
	set_RGB(0,15,15);
	
	printf("ok");
//	delay_ms(100); // 等待部署
//	IMU_init();
	TimerA1_init();
	
	adc0_init();
	SPI1_CS_IMU(1);
	SPI1_CS_W25Q64(1);
	delay_ms(100); // 等待部署
	w25q64_id=W25Q64_readID();
	printf("w25q64:%d\r\n",w25q64_id);
	//LCD_ShowIntNum(100,20,w25q64_id,5,RED,BLACK,16);
	OLED_ShowNum(24,0,w25q64_id,5,16);
	
	MyI2C_Init();
	AT240C2_WriteReg(0x22,0x55);
	AT240C2_data=AT240C2_ReadReg(0x22);
	printf("AT24C02:%d\r\n",AT240C2_data);
	//LCD_ShowIntNum(115,40,AT240C2_data,3,RED,BLACK,16);
	OLED_ShowNum(24,2,AT240C2_data,5,16);


	
    while (1) {

		get_adc0_num_val(&adc0_data);
		printf("adc0-0:%d\r\n",adc0_data[0]);
		keyboardm=get_keyboard_value();
//		LCD_ShowChar(100,80,keyboardm,RED,BLACK,16,0);
//		LCD_ShowIntNum(100,60,adc0_data[0],5,RED,BLACK,16);
//		LCD_ShowIntNum(110,100,adc0_data[2],5,RED,BLACK,16);
		OLED_ShowNum(24,4,adc0_data[0],5,16);
		OLED_ShowNum(24,6,adc0_data[2],5,16);
		OLED_ShowChar(90,6,keyboardm);
		delay_ms(100);
    }
}

