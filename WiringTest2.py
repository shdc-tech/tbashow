# 	Wiring test for  slideshow pi mk 3 (East side configuration)
#
#	Copyright 2023, John Grosvenor

from gpiozero import Button, LED
import signal
import requests
from time import sleep
import evdev 
import asyncio


NW_LED_PIN = 17
POWER_LED_PIN = 6
MODE_LED_PIN = 27

POWER_BUTTON_PIN = 21
MODE_BUTTON_PIN = 25
ADV_BUTTON_PIN = 7

POWER_HOLD_TIME = 3
MODE_HOLD_TIME = 1
ADV_HOLD_TIME = 0.1

SLIDE_TIME = 5

IR_REC_PIN = 18

powerLED = LED(POWER_LED_PIN)
modeLED = LED(MODE_LED_PIN)
networkLED = LED(NW_LED_PIN)
powerButton = Button(POWER_BUTTON_PIN, hold_time=POWER_HOLD_TIME)
modeButton = Button(MODE_BUTTON_PIN, hold_time=MODE_HOLD_TIME)
# advanceButton = Button(ADV_BUTTON_PIN, hold_time=ADV_HOLD_TIME)
advanceButton = Button(ADV_BUTTON_PIN)

currentSlide = 0
autoMode = True
powerOn = True 

print("SlideShow Mk3 - Wiring Test")
print()
print("Right hand side:")
print(f"Power button on GPIO {POWER_BUTTON_PIN}, hold time {POWER_HOLD_TIME} sec")
print(f"Power LED on GPIO {POWER_LED_PIN} - Green")
print(f"Netwrok LED on GPIO {NW_LED_PIN} - Red")
print("Left hand side:")
# print(f"Advance button on GPIO {ADV_BUTTON_PIN}, hold time {ADV_HOLD_TIME} sec")
print(f"Advance button on GPIO {ADV_BUTTON_PIN}")
print(f"Mode LED on GPIO {MODE_LED_PIN} - Yellow")
print(f"Mode button on GPIO {MODE_BUTTON_PIN}, hold time {MODE_HOLD_TIME} sec")


def get_ir_device():
	devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
	for device in devices:
		if device.name == "gpio_ir_recv":
			return device
	return None


def checkNetwork():
	connected = False
	try:
		r = requests.get("http://tasbridge.com.au")
		connected = True
	except:
		connected = False
	print(f"Network : {'ok' if connected else 'unavailable'}")
	if connected:
		networkLED.on()
	else:
		networkLED.off()


def alarmHandler(signum, frame):
	print("alarm Handler called")
	if signum != signal.SIGALRM:
		raise Exception(f"Unexpected signal received {signum}")
	global autoMode, currentSlide
	if not autoMode:
		return
	currentSlide += 1
	print(f"---> showing {currentSlide}")
	signal.alarm(SLIDE_TIME)
	checkNetwork()


def powerButtonEvent():
	print("power button held")
	global powerOn
	powerOn = not powerOn
	if powerOn:
		powerLED.on()
	else:
		powerLED.off()

def modeHeldEvent():
	print("mode button held")
	global autoMode, currentSlide
	autoMode = not autoMode
	if autoMode:
		print("Entering auto mode")
		modeLED.off()
		signal.alarm(SLIDE_TIME)
	else:
		print("Entering manual mode")
		signal.alarm(0)
		currentSlide = 0
		print(f"---> showing {currentSlide}")
		modeLED.on()


def advancedPressedEvent():
	print("advance button pressed")
	global autoMode, currentSlide
	if autoMode:
		return
	currentSlide += 1
	print(f"---> showing {currentSlide}")


def showPrevious():
	print("showing previous slide")
	global autoMode, currentSlide
	if autoMode:
		return
	currentSlide -= 1
	print(f"---> showing {currentSlide}")



ir_recv = get_ir_device()
if ir_recv is None:
	print("IR receiver not found")
else:
	print("IR receiever found : ", ir_recv)


async def ir_monitor(dev):
	lastDTS = 0
	debounce = 1
	async for ev in dev.async_read_loop():
		if autoMode:
			print("Ignoring ir in automode")
		elif ev.type != 4:
			pass
		else:
			# print(repr(ev))
			thisDTS = ev.sec + (ev.usec/1000000)
			if (thisDTS - lastDTS) < debounce:
				print(f"{thisDTS:.6f} : Ignoring repeat at {thisDTS - lastDTS}")
			else:
				# print(f"{thisDTS:.6f} : Type = {ev.type}, Code = {ev.code}, Value = {ev.value}")
				lastDTS = thisDTS
				if ev.value == 70 or ev.value == 67 or ev.value == 64:
					advancedPressedEvent()
				elif ev.value == 21 or ev.value == 68:
					showPrevious()
				else:
					print(f"Unsupported IR value received {ev.value}")


# def monitor_ir():
# 	sleep(5)
# 	events = ir_recv.read()
# 	try:
# 		event_list = [event.value for event in events]
# 		print("IR received: ", event_list)
# 	except BlockingIOError:
# 		print("No IR events")
# 		pass


powerLED.on()
modeLED.off()
checkNetwork()

powerButton.when_held = powerButtonEvent
modeButton.when_held = modeHeldEvent
advanceButton.when_pressed = advancedPressedEvent
# advanceButton.when_held = advancedPressedEvent

currentSlide = 0
print(f"---> showing {currentSlide}")

signal.signal(signal.SIGALRM, alarmHandler)
signal.alarm(SLIDE_TIME)

loop = asyncio.get_event_loop()
loop.run_until_complete(ir_monitor(ir_recv))

while True:
	print("pausing ...")
	signal.pause()
