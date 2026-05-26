#include "stm32f4xx.h"
#include <stdio.h>
#include "delay.h"
#include "GPIO.h"
#include "USART.h"


int main(void) 
{ 
	  
	  Delay_Init();    
    USART1_Init(115200);
    
	
   while (1) 
		 {
			 
			
		
    }

}
