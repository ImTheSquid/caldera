#include <EverydayCalendar_lights.h>
#include <EverydayCalendar_touch.h>

// Upstream EverydayCalendar sketch plus a serial line protocol.
// Protocol reference: src/caldera/protocol.py

typedef struct {
   int8_t    x;
   int8_t    y;
} Point;

EverydayCalendar_touch cal_touch;
EverydayCalendar_lights cal_lights;
int16_t brightness = 128;

static const uint8_t PROTOCOL_VERSION = 3;
#ifndef BAUD
#define BAUD 250000 // exact divider for the 8MHz AVR and the FT232R; 500000 overruns
#endif
static const uint8_t LINE_MAX = 80;
static char line[LINE_MAX + 1];
static uint8_t lineLen = 0;
static bool lineOverflow = false;
static bool hostMode = false; // touches are reported only, never acted on

void setup() {
  Serial.begin(BAUD);
  Serial.println(F("# setup started"));

  // Initialize LED functionality
  cal_lights.configure();
  cal_lights.setBrightness(200);
  cal_lights.begin();

  // Perform startup animation
  honeyDrip();

  // Fade out
  for(int b = 200; b >= 0; b--){
    cal_lights.setBrightness(b);
    delay(4);
  }

  // Initialize touch functionality
  cal_touch.configure();
  cal_touch.begin();
  cal_lights.loadLedStatesFromMemory();
  delay(1500);

  // Fade in
  for(int b = 0; b <= brightness; b++){
    cal_lights.setBrightness(b);
    delay(4);
  }

  Serial.print(F("READY EDC "));
  Serial.println(PROTOCOL_VERSION);
}

void loop() {
  static Point previouslyHeldButton = {0xFF, 0xFF}; // 0xFF and 0xFF if no button is held
  static uint16_t touchCount = 1;
  static const uint8_t debounceCount = 3;
  static const uint16_t clearCalendarCount = 1300; // ~40 seconds.  This is in units of touch sampling interval ~= 30ms.

  pollSerial();
  if(!cal_touch.poll()){
    return;
  }

  bool touch = cal_touch.x != -1;
  bool onDay = touch && cal_touch.y < 31;
  reportContact(onDay ? cal_touch.x : -1, onDay ? cal_touch.y : -1);
  // Handle a button press
  if(touch)
  {
    // Brightness Buttons
    if(cal_touch.y == 31 && !hostMode){
      if(cal_touch.x == 4){
        brightness -= 3;
      }else if(cal_touch.x == 6){
        brightness += 2;
      }
      brightness = constrain(brightness, 0, 200);
      cal_lights.setBrightness((uint8_t)brightness);
    }
    // If all buttons aren't touched, reset debounce touch counter
    if(previouslyHeldButton.x == -1){
      touchCount = 0;
    }

    // If this button is been held, or it's just starting to be pressed and is the only button being touched
    if(((previouslyHeldButton.x == cal_touch.x) && (previouslyHeldButton.y == cal_touch.y))
    || (debounceCount == 0))
    {
      // The button has been held for a certain number of consecutive checks
      // This is called debouncing
      if (touchCount == debounceCount){
        // Button is activated
        reportTouch(cal_touch.x, cal_touch.y);
        if(!hostMode && cal_touch.y < 31){
          cal_lights.toggleLED((uint8_t)cal_touch.x, (uint8_t)cal_touch.y);
          cal_lights.saveLedStatesToMemory();
        }
      }

      // Check if the special "Reset" January 1 button is being held
      if(!hostMode && (cal_touch.x == 0) && (cal_touch.y == 0) && (touchCount == clearCalendarCount)){
        Serial.println(F("# resetting all LED states"));
        clearAnimation();
      }

      if(touchCount < 65535){
        touchCount++;
      }
    }
  }

  previouslyHeldButton.x = cal_touch.x;
  previouslyHeldButton.y = cal_touch.y;
}

void reportTouch(int8_t x, int8_t y){
  if(y < 31){
    Serial.print(F("EV T "));
    Serial.print(x);
    Serial.print(' ');
    Serial.println(y);
  }else if(x == 4){
    Serial.println(F("EV B DIM"));
  }else if(x == 6){
    Serial.println(F("EV B BRIGHT"));
  }
}

// Raw contact, every scan: EV D on each new day pad, EV U on release. Host mode only.
void reportContact(int8_t x, int8_t y){
  static int8_t lastX = -1, lastY = -1;
  if(x == lastX && y == lastY){
    return;
  }
  lastX = x;
  lastY = y;
  if(!hostMode){
    return;
  }
  if(x < 0){
    Serial.println(F("EV U"));
    return;
  }
  Serial.print(F("EV D "));
  Serial.print(x);
  Serial.print(' ');
  Serial.println(y);
}

void pollSerial(){
  while(Serial.available()){
    char c = Serial.read();
    if(c == '\r'){
      continue;
    }
    if(c == '\n'){
      line[lineLen] = '\0';
      if(lineOverflow){
        Serial.println(F("ERR line too long"));
      }else if(lineLen > 0){
        handleCommand(line);
      }
      lineLen = 0;
      lineOverflow = false;
      return; // one line per loop so touch scanning keeps running
    }else if(lineLen < LINE_MAX){
      line[lineLen++] = c;
    }else{
      lineOverflow = true;
    }
  }
}

// Next token as an integer in [lo, hi], or -1 if missing or invalid
long nextInt(long lo, long hi){
  char* tok = strtok(NULL, " ");
  if(tok == NULL){
    return -1;
  }
  char* end;
  long v = strtol(tok, &end, 10);
  return (*end == '\0' && v >= lo && v <= hi) ? v : -1;
}

// Each month is 6 chars of '0' + 6 bits, most significant first
bool decodeFrame(const char* s, uint32_t* days){
  for(uint8_t m = 0; m < 12; m++){
    uint32_t w = 0;
    for(uint8_t i = 0; i < 6; i++){
      uint8_t v = *s++ - '0';
      if(v > (i == 0 ? 1 : 63)){ // day 31 is bit 30, so the first char holds one bit
        return false;
      }
      w = (w << 6) | v;
    }
    days[m] = w;
  }
  return *s == '\0';
}

bool noMoreArgs(){
  return strtok(NULL, " ") == NULL;
}

void ok(){
  Serial.println(F("OK"));
}

void err(const __FlashStringHelper* reason){
  Serial.print(F("ERR "));
  Serial.println(reason);
}

void handleCommand(char* cmd){
  char* op = strtok(cmd, " ");

  if(!strcmp(op, "PING")){
    char* token = strtok(NULL, " ");
    if(token != NULL){
      Serial.print(F("OK "));
      Serial.println(token);
    }else{
      Serial.print(F("OK EDC "));
      Serial.println(PROTOCOL_VERSION);
    }
  }else if(op[0] == 'F' && op[1] != '\0'){
    uint32_t days[12];
    if(!decodeFrame(op + 1, days) || !noMoreArgs()){
      return err(F("usage: F<72 chars>"));
    }
    for(uint8_t m = 0; m < 12; m++){
      cal_lights.setMonth(m, days[m]);
    }
    ok();
  }else if(!strcmp(op, "GET")){
    Serial.print(F("OK"));
    for(uint8_t m = 0; m < 12; m++){
      Serial.print(' ');
      Serial.print(cal_lights.getMonth(m), HEX);
    }
    Serial.println();
  }else if(!strcmp(op, "SET")){
    long m = nextInt(0, 11);
    long d = nextInt(0, 30);
    long on = nextInt(0, 1);
    if(m < 0 || d < 0 || on < 0 || !noMoreArgs()){
      return err(F("usage: SET month day 0|1"));
    }
    cal_lights.setLED(m, d, on);
    ok();
  }else if(!strcmp(op, "CLR")){
    if(!noMoreArgs()){
      return err(F("usage: CLR"));
    }
    cal_lights.clearAllLEDs();
    ok();
  }else if(!strcmp(op, "BRI")){
    char* tok = strtok(NULL, " ");
    if(tok != NULL){
      char* end;
      long b = strtol(tok, &end, 10);
      if(*end != '\0' || b < 0 || b > 200 || !noMoreArgs()){
        return err(F("usage: BRI [0-200]"));
      }
      brightness = b;
      cal_lights.setBrightness((uint8_t)brightness);
    }
    Serial.print(F("OK "));
    Serial.println(brightness);
  }else if(!strcmp(op, "SAVE")){
    cal_lights.saveLedStatesToMemory();
    ok();
  }else if(!strcmp(op, "LOAD")){
    cal_lights.loadLedStatesFromMemory();
    ok();
  }else if(!strcmp(op, "MODE")){
    char* tok = strtok(NULL, " ");
    if(tok != NULL){
      if((strcmp(tok, "L") && strcmp(tok, "H")) || !noMoreArgs()){
        return err(F("usage: MODE [L|H]"));
      }
      hostMode = tok[0] == 'H';
    }
    Serial.println(hostMode ? "OK H" : "OK L");
  }else{
    err(F("unknown command"));
  }
}

void honeyDrip(){
  uint16_t interval_ms = 25;
  static const uint8_t monthDayOffset[12] = {0, 3, 0, 1, 0, 1, 0, 0, 1, 0, 1, 0};
  // Turn on all LEDs one by one in the span of a few second
  for(int day = 0; day < 31; day++){
    for(int month = 0; month < 12; month++){
      int8_t adjustedDay = day - monthDayOffset[month];
      if(adjustedDay >= 0 ){
        cal_lights.setLED(month, adjustedDay, true);
      }
    }
    delay(interval_ms);
    interval_ms = interval_ms + 2;
  }
}

void clearAnimation(){
  uint16_t interval_ms = 25;
  static const uint8_t monthMaxDay[12] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  for(int month = 11; month >= 0; month--){
    for(int day = monthMaxDay[month]-1; day >=0; day--){
       cal_lights.setLED(month, day, false);
       delay(interval_ms);
    }
  }
  cal_lights.saveLedStatesToMemory();
}
