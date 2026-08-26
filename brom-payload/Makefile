CC := arm-none-eabi-gcc
AS := arm-none-eabi-as
LD := arm-none-eabi-gcc
OBJCOPY := arm-none-eabi-objcopy

CFLAGS := -std=gnu99 -Os -mthumb -mcpu=cortex-a9 -fno-builtin-printf -fno-strict-aliasing -fno-builtin-memcpy -mno-unaligned-access -Wall -Wextra
LDFLAGS := -T linker.x -nodefaultlibs -nostdlib -lgcc
DIAGNOSTIC_CFLAGS := $(CFLAGS) -Werror -ffunction-sections -fdata-sections -DLIBREECHO_READONLY_DIAGNOSTIC=1
DIAGNOSTIC_LDFLAGS := $(LDFLAGS) -Wl,--gc-sections

BUILD_DIR := build
DIAGNOSTIC_BUILD_DIR := build/diagnostic

COMMON_C_SRC := libc.c printf.c drivers/sd.c drivers/mmc.c crypto/sha256.c crypto/hmac-sha256.c
DIAGNOSTIC_C_SRC := diagnostic.c drivers/timer.c
COMMON_OBJ := $(COMMON_C_SRC:%.c=$(BUILD_DIR)/%.o)
START_OBJ := $(BUILD_DIR)/start.o
PAYLOAD_OBJ := $(BUILD_DIR)/main.o $(COMMON_OBJ) $(START_OBJ)
DIAGNOSTIC_COMMON_OBJ := $(COMMON_C_SRC:%.c=$(DIAGNOSTIC_BUILD_DIR)/%.o)
DIAGNOSTIC_START_OBJ := $(DIAGNOSTIC_BUILD_DIR)/start.o
DIAGNOSTIC_OBJ := $(DIAGNOSTIC_C_SRC:%.c=$(DIAGNOSTIC_BUILD_DIR)/%.o) $(DIAGNOSTIC_COMMON_OBJ) $(DIAGNOSTIC_START_OBJ)
DEP := $(PAYLOAD_OBJ:%.o=%.d) $(DIAGNOSTIC_OBJ:%.o=%.d)

all: build/payload.bin

diagnostic: build/diagnostic.bin

build/payload.bin: build/payload.elf
	$(OBJCOPY) -O binary $^ $@

build/payload.elf: $(PAYLOAD_OBJ)
	$(LD) -o $@ $^ $(LDFLAGS)

build/diagnostic.bin: build/diagnostic.elf diagnostic_protocol.h
	$(OBJCOPY) -O binary $< $@

build/diagnostic.elf: $(DIAGNOSTIC_OBJ)
	$(LD) -o $@ $^ $(DIAGNOSTIC_LDFLAGS)

-include $(DEP)

$(BUILD_DIR)/%.o: %.c
	mkdir -p $(@D)
	$(CC) -MMD -c -o $@ $< $(CFLAGS)

$(BUILD_DIR)/%.o: %.S
	mkdir -p $(@D)
	$(AS) -o $@ $<

$(DIAGNOSTIC_BUILD_DIR)/%.o: %.c
	mkdir -p $(@D)
	$(CC) -MMD -c -o $@ $< $(DIAGNOSTIC_CFLAGS)

$(DIAGNOSTIC_BUILD_DIR)/%.o: %.S
	mkdir -p $(@D)
	$(AS) -o $@ $<

clean:
	-rm -rf $(BUILD_DIR)

.PHONY: all diagnostic clean
