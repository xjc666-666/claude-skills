#include "delay.h"
#include "sys.h"
//#include "led.h"
//#include "lcd_init.h"
//#include "lcd.h"
#include "OLED.h"
#include "KEY.h"
#include "pic.h"
#include <stdint.h>
int main(void)
{
	delay_init();
	//LED_Init();
	gpio_Init();
	//LCD_Init();//LCD初始化
	//LCD_Fill(0,0,LCD_W,LCD_H,RED);	
	//LCD_ShowPicture(20,45,120,29,gImage_pic1);
//	LCD_ShowString(50,0,"NOLOGE!!!",BLACK,WHITE,16,0);
//	LCD_ShowChinese(50,20,"无名科技",BLACK,WHITE,16,0);	
	while(1)
	{
//		PCout(13)=1;	PCout(14)=1;  PCout(15)=1;
//		PBout(2)=1;		PBout(3)=1;		PBout(4)=1;		PBout(5)=1;		PBout(6)=1;		PBout(7)=1;		PBout(8)=1;		PBout(9)=1;		PBout(12)=1;	PBout(13)=1;		PBout(14)=1;	PBout(15)=1;
//		PAout(0) =1; 	PAout(1) =1;	PAout(2)=1;		PAout(3) =1;	PAout(4) =1;	PAout(5) =1;	PAout(8) =1; 	PAout(9) =1;	PAout(10) =1;	PAout(11) =1; 	PAout(12) =1; PAout(13) =1; PAout(14) =1;   PAout(15) =1;
//		delay_ms(1000);

//		PCout(13)=0;	PCout(14)=0;  PCout(15)=0;
//		PBout(2)=0;	 	PBout(3)=0;		PBout(4)=0;	 	PBout(5)=0; 	PBout(6)=0; 	PBout(7)=0; 	PBout(8)=0;		PBout(9)=0; 	PBout(12)=0;	PBout(13)=0;    PBout(14)=0;		PBout(15)=0;
//		PAout(0) =0; 	PAout(1) =0;	PAout(2) =0;	PAout(3) =0;	PAout(4) =0;	PAout(5) =0;	PAout(8) =0; 	PAout(9) =0;	PAout(10) =0;	PAout(11) =0;		PAout(12) =0;  PAout(13) =0; PAout(14) =0; 	PAout(15) =0;
//		delay_ms(1000);
		
	}
}


