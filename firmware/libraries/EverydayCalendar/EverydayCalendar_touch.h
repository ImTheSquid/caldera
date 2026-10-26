#ifndef __EVERYDAYCALENDAR_TOUCH_H
#define __EVERYDAYCALENDAR_TOUCH_H
#include <stdint.h>
#include <IQS5xx.h>


class EverydayCalendar_touch
{
public:
  void initialize();
	void configure();
	void begin();
  bool scanForTouch();
  bool poll();
  int8_t x;
  int8_t y;
  IQS tc[4];  // Touch Controllers
  int8_t scanIndex = -1; // controller being read, -1 while waiting for all to be ready
  bool sessionEnded = false;
  unsigned long sessionEndedAt;

  int16_t getAtiCAdjustmentValue(uint8_t month, uint8_t day);
  int16_t getAtiCompensationValue(uint8_t month, uint8_t day);
  int16_t getChannelCountValue(uint8_t month, uint8_t day);

  void printAtiCAdjustmentValues();
  void printAtiCompensationValues();
  void printChannelCountValues();

};

#endif
