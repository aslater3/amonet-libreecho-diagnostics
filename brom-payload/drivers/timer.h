#ifndef LIBREECHO_BROM_TIMER_H
#define LIBREECHO_BROM_TIMER_H

#include <inttypes.h>

void timer_init(void);
uint32_t gpt4_get_current_tick(void);
int gpt4_timeout_elapsed(uint32_t start_tick, uint32_t timeout_ms);
void mdelay(unsigned long msec);
void udelay(unsigned long usec);

#endif
