// Copyright (C) 2020  Elias Bakken <elias@iagent.no>
// This file may be distributed under the terms of the GNU GPLv3 license.

#include <stdint.h>     // uint32_t
#include <string.h>
#include "board/misc.h" // dynmem_start
#include "board/irq.h"  // irq_disable
#include "command.h"    // shutdown
#include "generic/timer_irq.h"  // timer_dispatch_many
#include "sched.h"      // sched_main

#include "asm/spr.h"
#include "util.h"
#include "gpio.h"
#include "serial.h"
#include "prcm.h"
#include "timer.h"

DECL_CONSTANT_STR("MCU", "ar100");

static struct task_wake console_wake;
static uint8_t receive_buf[1024];
static int receive_pos;

void
irq_disable(void){
}

void
irq_enable(void){
}

irqstatus_t
irq_save(void){
    return 0;
}

void
irq_restore(irqstatus_t flag){
}

void
irq_wait(void){
    irq_poll();
}

void
irq_poll(void){
    if(timer_interrupt_pending()) {
        timer_clear_interrupt();
        uint32_t next = timer_dispatch_many();
        timer_set(next);
    }
    if(r_uart_fifo_rcv())
        sched_wake_task(&console_wake);
}

/****************************************************************
* Console IO
****************************************************************/

// Process any incoming commands
void
console_task(void)
{
    if (!sched_check_wake(&console_wake))
        return;

    int ret = 0;
    for(int i=0; i<r_uart_fifo_rcv(); i++) {
        receive_buf[receive_pos + ret++] = r_uart_getc();
    }
    if(!ret)
        return;

    int len = receive_pos + ret;
    uint_fast8_t pop_count, msglen = len > MESSAGE_MAX ? MESSAGE_MAX : len;
    ret = command_find_and_dispatch(receive_buf, msglen, &pop_count);
    if (ret) {
        len -= pop_count;
        if (len) {
            memcpy(receive_buf, &receive_buf[pop_count], len);
            sched_wake_task(&console_wake);
        }
    }
    receive_pos = len;
}
DECL_TASK(console_task);

// Encode and transmit a "response" message
void
console_sendf(const struct command_encoder *ce, va_list args){
    uint8_t buf[MESSAGE_MAX];
    uint_fast8_t msglen = command_encode_and_frame(buf, ce, args);

    for(int i=0; i<msglen; i++) {
        r_uart_putc(buf[i]);
    }
}

// Handle shutdown request from ar100
static void
shutdown_handler(uint32_t *args)
{
    shutdown("Request from ar100");
}

const struct command_parser shutdown_request = {
    .func = shutdown_handler,
};

void restore_data(void){
    extern char __data_start, __data_end, __copy_start;
    memcpy (&__data_start, &__copy_start, &__data_end - &__data_start);
}

void
command_reset(uint32_t *args)
{
    timer_reset();
    restore_data();
    void *reset = (void *)0x9000;
    goto *reset;
}
DECL_COMMAND_FLAGS(command_reset, HF_IN_SHUTDOWN, "reset");

void
save_data(void){
    extern char __data_start, __data_end, __copy_start;
    memcpy (&__copy_start, &__data_start, &__data_end - &__data_start);
}

__noreturn void
main(uint32_t exception);
__noreturn void
main(uint32_t exception){

    save_data();

    /* Swith CPUS to 300 MHz. This should be done in Linux eventually */
    r_prcm_set_cpus_clk_rate(PLL_PERIPH);

    r_uart_init();
    uart_puts("**AR100 v0.1.0**\n");
    sched_main();
    while(1) {}         // Stop complaining about noreturn
}
