FQBN    := arduino:avr:pro:cpu=8MHzatmega328
PORT    ?= $(firstword $(wildcard /dev/cu.usbserial-*))
SKETCH  := firmware/caldera
BUILD   := build
AVRDUDE := avrdude -c arduino -p m328p -b 57600 -P $(PORT)

.PHONY: build flash backup test

build:
	arduino-cli compile --clean -b $(FQBN) --build-property "compiler.cpp.extra_flags=-DSERIAL_RX_BUFFER_SIZE=512 $(EXTRA)" --libraries firmware/libraries --output-dir $(BUILD) $(SKETCH)

flash: build
	$(AVRDUDE) -U flash:w:$(BUILD)/caldera.ino.hex:i

backup:
	mkdir -p backup
	$(AVRDUDE) -U flash:r:backup/flash.hex:i -U eeprom:r:backup/eeprom.hex:i

test:
	uv run pytest
