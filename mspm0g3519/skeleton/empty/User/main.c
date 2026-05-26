#include "ti_msp_dl_config.h"
#include "bsp.h"


int main(void)
{
    SYSCFG_DL_init();
	  OLED_Init();
	  OLED_Clear();
	  OLED_ShowString(0, 0, (u8*)"Hello OLED!"); 
    
   
    OLED_ShowChar(0, 2, 'A');                   
   
    OLED_ShowNum(20, 2, 1234, 4, 16);          
    
		
    OLED_ShowCHinese(0, 4, 0);                 
    OLED_ShowCHinese(16, 4, 1);
	  OLED_ShowCHinese(32, 4, 2);
	  OLED_ShowCHinese(48, 4, 3);
	  OLED_ShowCHinese(64, 4, 4);
	  OLED_ShowCHinese(80, 4, 5);
	
    while (1) {
	
    }
}

