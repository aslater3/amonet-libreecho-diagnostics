#include <inttypes.h>

#include "libc.h"
#include "diagnostic_protocol.h"
#include "drivers/types.h"
#include "drivers/core.h"
#include "drivers/mt_sd.h"
#include "drivers/errno.h"
#include "drivers/mmc.h"
#include "drivers/timer.h"

static int (*send_dword_fn)() = (void*)0xC047;
static int (*recv_dword_fn)() = (void*)0xC013;
static int (*send_data_fn)() = (void*)0xC10F;

void _putchar(char character)
{
    /* ponytail: USB frames are the only diagnostic output; UART is optional. */
    (void)character;
}

static void send_word(uint32_t value)
{
    send_dword_fn(value);
}

static uint32_t receive_word(void)
{
    return recv_dword_fn();
}

static void send_response_header(uint32_t sequence, uint32_t command,
                                 uint32_t selected_part, uint32_t target,
                                 int32_t status, uint32_t payload_length)
{
    send_word(DIAG_RESPONSE_MAGIC);
    send_word(DIAG_PROTOCOL_VERSION);
    send_word(sequence);
    send_word(command);
    send_word(selected_part);
    send_word(target);
    send_word((uint32_t)status);
    send_word(payload_length);
}

static void send_init_report(uint32_t sequence, uint32_t selected_part,
                             int32_t init_status,
                             const struct mmc_init_report *init_report)
{
    send_response_header(sequence, DIAG_CMD_HELLO, selected_part, 0,
                         init_status, DIAG_INIT_REPORT_WORDS * 4);
    send_word(init_report->msdc_cfg);
    send_word((uint32_t)init_report->go_idle);
    send_word((uint32_t)init_report->send_op_cond_probe);
    send_word(init_report->ocr);
    send_word((uint32_t)init_report->select_voltage);
    send_word((uint32_t)init_report->send_op_cond_ready);
    send_word(init_report->rocr);
    send_word((uint32_t)init_report->all_send_cid);
    send_word((uint32_t)init_report->set_relative_addr);
    send_word((uint32_t)init_report->select_card);
    send_word(init_report->first_failed_stage);
}

int main(void)
{
    char sector[0x200] = { 0 };
    struct msdc_host host = { 0 };
    struct mmc_init_report init_report;
    uint32_t selected_part = DIAG_PARTITION_UNKNOWN;
    uint32_t state = 0;
    int32_t init_status = -EINVAL;

    /* Restore the BROM USB send pointer overwritten by payload loading. */
    uint32_t *ptr_send = (void*)0x1028A8;
    *ptr_send = 0x5FE5;

    host.ocr_avail = MSDC_OCR_AVAIL;
    memset(&init_report, 0, sizeof(init_report));
    timer_init();

    /* USB liveness only. MMC initialization starts on the first HELLO. */
    send_word(DIAG_READY_MAGIC);

    while (state < 3) {
        uint32_t request_magic = receive_word();
        uint32_t version = receive_word();
        uint32_t sequence = receive_word();
        uint32_t command = receive_word();
        uint32_t argument = receive_word();

        if (request_magic != DIAG_REQUEST_MAGIC ||
                version != DIAG_PROTOCOL_VERSION) {
            send_response_header(sequence, command, selected_part, argument,
                                 -EINVAL, 0);
            state = 3;
            continue;
        }

        switch (command) {
        case DIAG_CMD_HELLO:
            if (state != 0) {
                send_response_header(sequence, command, selected_part, 0,
                                     -EINVAL, 0);
                state = 3;
                break;
            }
            init_status = mmc_init_diagnostic(&host, &init_report);
            send_init_report(sequence, selected_part, init_status, &init_report);
            state = init_status == 0 ? 1 : 3;
            break;

        case DIAG_CMD_READ_DEFAULT_SECTOR0: {
            uint32_t prior_state = state;
            int32_t status;

            if (state != 1 && state != 2) {
                status = -EINVAL;
            } else if (init_status != 0) {
                status = init_status;
            } else if (argument != 0) {
                status = -EINVAL;
            } else {
                memset(sector, 0, sizeof(sector));
                status = mmc_read(&host, 0, sector);
            }
            send_response_header(sequence, command, selected_part, 0,
                                 status, status == 0 ? sizeof(sector) : 0);
            if (status == 0)
                send_data_fn(sector, sizeof(sector));
            state = status == 0 && prior_state == 1 ? 2 : 3;
            break;
        }

        default:
            send_response_header(sequence, command, selected_part, argument,
                                 -EINVAL, 0);
            state = 3;
            break;
        }
    }

    /* Terminal state: accept no further commands and never return into BROM. */
    while (1)
        ;
}
