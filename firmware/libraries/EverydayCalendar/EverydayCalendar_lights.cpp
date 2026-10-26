#include "EverydayCalendar_lights.h"
#include <Arduino.h>
#include <SPI.h>
#include <EEPROM.h>

#define UINT16_MSB(uint16) ((uint8_t)(uint16 >> 8))
#define UINT16_LSB(uint16) ((uint8_t)(uint16 & 0xFF))
#define ARRAY_SIZE(array) (sizeof((array))/sizeof((array[0])))
#define EEPROM_START_ADR  0x00000000

static const int csPin = 10;
static const int tickle_pin = 9;
static const int outputEnablePin = 8;
// set up the speed, data order and data mode
static SPISettings spiSettings(4000000, MSBFIRST, SPI_MODE0);
static const uint8_t maxBrightness = 255;
static uint8_t brightness = maxBrightness/2;
static uint32_t ledValues[12] = {0}; // Months are the integers in range [0,11], Days are bits within the integers, in range [0,31]


void EverydayCalendar_lights::configure(){
  // LED configurations
  SPI.begin();
  SPI.beginTransaction(spiSettings); // held for good; the LED ISR is the only SPI user
  pinMode (csPin, OUTPUT);
  digitalWrite (csPin, HIGH);
  pinMode (tickle_pin, OUTPUT);
  digitalWrite(tickle_pin, HIGH);
  pinMode (outputEnablePin, OUTPUT);
  digitalWrite(outputEnablePin, HIGH);
  // Enable Timer2 interrupt.
  // We want CTC mode (mode 2) where timer resets after compare
  TCCR2A = (TCCR2A & ~0x03) | 0x00;
  TCCR2B = (TCCR2B & ~0x08) | 0x00;
  TCCR2B = (TCCR2B & ~0x07) | 0x02; // selects a clock prescaler of 8. That's a frequency of 31372.55
  OCR2A = brightness; //128
  clearAllLEDs();
}

void EverydayCalendar_lights::begin(){
  TIMSK2 = (1<<OCIE2A) | (1<<TOIE2); // Enable Timers
}

void EverydayCalendar_lights::clearAllLEDs(){
  memset(ledValues, 0, sizeof(ledValues));
}

// Month is in range [0,11]
// Day is in range [0,30]
void EverydayCalendar_lights::setLED(uint8_t month, uint8_t day, bool enable){
  if (month > 11 || day > 30){
    return;
  }

  if (enable){
      ledValues[month] = ledValues[month] | ((uint32_t)1 << day);
  }else{
      ledValues[month] = ledValues[month] & ~((uint32_t)1 << day);
  }
}

uint32_t EverydayCalendar_lights::getMonth(uint8_t month){
  if (month > 11){
    return 0;
  }
  noInterrupts();
  uint32_t days = ledValues[month];
  interrupts();
  return days;
}

// Bit d of days is day d, in range [0,30]
void EverydayCalendar_lights::setMonth(uint8_t month, uint32_t days){
  if (month > 11){
    return;
  }
  noInterrupts();
  ledValues[month] = days & 0x7FFFFFFF;
  interrupts();
}

void EverydayCalendar_lights::toggleLED(uint8_t month, uint8_t day){
   bool ledState = (*(ledValues+month) & ((uint32_t)1 << (day)));
   setLED(month, day, !ledState);
}

void EverydayCalendar_lights::saveLedStatesToMemory(){
  for(uint8_t month=0; month<12; month++){
    int addr = EEPROM_START_ADR + (month * sizeof(uint32_t));
    EEPROM.put(addr, ledValues[month]);
  }
}

void EverydayCalendar_lights::loadLedStatesFromMemory(){
  // If the first month is completely set, then this is the first time we're running the code.
  // Clear the calendar memory
  uint32_t firstInt;
  EEPROM.get(EEPROM_START_ADR, firstInt);
  if(firstInt == 0xFFFFFFFF){
    Serial.println("First time running everyday calendar.  Clearing all days.");
    for(int i=0; i<sizeof(ledValues); i++){
      EEPROM.write(EEPROM_START_ADR + i, 0x00);
    }
  }
  // Load calendar from memory
  for(int i=0; i<sizeof(ledValues); i++){
    *((byte*)ledValues + i) = EEPROM.read(EEPROM_START_ADR + i);
  }
}

void EverydayCalendar_lights::setBrightness(uint8_t b){
  if(b > 200){
    b = 200;
  }
  b = ~b;
  if((brightness == 255) && (b != 255)){
    TIMSK2 |= (1<<OCIE2A);
  }
  brightness = b;
  if(brightness == 255){
    TIMSK2 &= ~(1<<OCIE2A);
  }
}


// Code to drive the LED multiplexing.
// This code is called at a very fast period, activating each LED column one by one
// This is done faster than the eye can perceive, and it appears that all twelve columns are illuminated at once.
// Pins 8, 9 and 10 are PB0, PB1 and PB2. Direct port and SPI register access
// keeps these ISRs short so they don't starve UART receive at high baud rates.
static const uint8_t outputEnableBit = _BV(PB0);
static const uint8_t tickleBit = _BV(PB1);
static const uint8_t csBit = _BV(PB2);

static inline void spiSend(uint8_t b){
  SPDR = b;
  while(!(SPSR & _BV(SPIF)));
}

ISR(TIMER2_COMPA_vect) {
  PORTB &= ~outputEnableBit; // Enable
}
ISR(TIMER2_OVF_vect) {
    static uint8_t activeColumn = 0;

    PORTB |= outputEnableBit; // Disable

    OCR2A = brightness;

    // "Tickle" the watchdog circuit to keep the LEDs enabled
    PINB = tickleBit; // writing 1 to a PINx bit toggles the pin

    // update the next column
    uint16_t month = (1 << activeColumn);
    uint8_t * pDays = (uint8_t*) (ledValues + activeColumn);

    // Send the LED control values into the shift registers
    PORTB &= ~csBit;
    spiSend(month & 0xFF);
    spiSend(month >> 8);
    spiSend(pDays[3]);
    spiSend(pDays[2]);
    spiSend(pDays[1]);
    spiSend(pDays[0]);
    PORTB |= csBit;

    activeColumn = (activeColumn == 11) ? 0 : activeColumn + 1;
}
