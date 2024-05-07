"""
Raspberry Pi Slideshow Mk 3

Copyright John Grosvenor, Aug 2023

This application is intended to present a set of images sourced from either a local
repository or a remote repository via HTTP in an automated fashion as a full screen,
non-interactive display.

Mk 3 introduces support for multiple image sets.

The config file contains a list of image set configurations. At least one image set must be
configured.

When a single image set is specified the mode button toggles between auto and manual mode,
and the advance button shows the next slide when in manual mode. This is equivalent to the
functionality of earlier versions.

When more than one image set is specified the mode button cycles between the image sets.
In this mode of operation the mode LED is lit when the currently selected image set is 
configured with auto = 'N'. In this case the advance button cycles through the images.
When an image set is configured with auto = "Y" the mode LED is off, the advance button
is inactive and the images advance automatically.

Image sets are associated with a name which is used as the root directory for storing
the related files, and in naming the image files on the web server.

Cache indexes (one per image set) are stored in json files. They can be safely deleted 
to force a complete reload and synch of the cache.

Power and network LEDs are handled by a separate shutdown script.

Configuration settings are loaded from a json dictionary in config3.json

Local content is stored in a local subdirectory under each image set's root directory.
Remote content is loaded from a webserver and cached, and refreshed at a set interval

An optional infrared remote control can be used to change slides and image sets.

Requires:
	pip install guizero\[images\]    (note escaping on square brackets for MacOS)
	pip install requests

"""

import inspect
import signal
import json
import os
import requests
import shutil
import random
import socket
import evdev 
# import asyncio

from guizero import App, Picture, Box
from datetime import datetime, timedelta
from gpiozero import Button, LED

from ImageSet import ImageSet

LOG_LEVEL_FATAL = 3
LOG_LEVEL_WARNING = 2
LOG_LEVEL_INFO = 1
LOG_LEVEL_VERBOSE = 0

MODE_LED_PIN = 27
MODE_BUTTON_PIN = 25
ADV_BUTTON_PIN = 7
IR_REC_PIN = 18

MODE_HOLD_TIME = 1

BASE_DIR = "/home/tba/Code/SlideShow/"
BASE_SPLASH = BASE_DIR + "splash.png"

CK_IMAGE_SETS = "imageSets"
CK_TITLE = "appTitle"
CK_LOG_LEVEL = "logLevel"
CK_INTERVAL = "displayIntervalMS"
CK_REMOTE_UPDATE = "remoteUpdateMins"
CK_DISPLAY_SIZE = "displaySize"
CK_SET_NAME = "name"
CK_SET_URL = "URL"
CK_SET_RANDOMISE = "randomise"
CK_SET_AUTO = "auto"
CK_SET_REFRESH_MINS = "refreshMins"

CONFIG_FILE = "config3.json"

defaultConfig = {
	CK_IMAGE_SETS 		: [],
	CK_TITLE 			: "Slide Show",
	CK_LOG_LEVEL 		: LOG_LEVEL_WARNING,
	CK_INTERVAL 		: 30000,
	CK_REMOTE_UPDATE	: 5,
	CK_DISPLAY_SIZE 	: [1600, 900]
}

defaultSetConfig = {
	CK_SET_NAME 		: "slides",
	CK_SET_URL 			: "http://tasbridge.com.au/pics/",
	CK_SET_RANDOMISE 	: "N",
	CK_SET_AUTO			: "Y",
	CK_SET_REFRESH_MINS : 20
}

modeLED = LED(MODE_LED_PIN)
modeButton = Button(MODE_BUTTON_PIN, hold_time=MODE_HOLD_TIME)
advanceButton = Button(ADV_BUTTON_PIN)

configFile = open(f"{BASE_DIR}{CONFIG_FILE}", 'r')
config = json.loads(configFile.read())


def getConfig(key):
	'''
	Returns the value for a config item or fails if unknown.
	Returns a default value if none specified in the config.json file
	'''
	if key in config:
		return config[key]
	elif key in defaultConfig:
		return defaultConfig[key]
	else:
		raise Exception(f"Unknown config key '{key}'")


def getSetConfig(setCongif, key):
	'''
	Returns the value for a set config item or fails if unknown.
	Returns a default value if needed
	'''
	if key in setCongif:
		return setCongif[key]
	elif key in defaultSetConfig:
		return defaultSetConfig[key]
	else:
		raise Exception(f"Unknown set config key '{key}'")


def log(message, level=LOG_LEVEL_INFO):
	'''
	Print a log message if at the appropriate log level
	Raise an exception for fatal errors
	'''
	if level >= getConfig(CK_LOG_LEVEL):
		if level == LOG_LEVEL_FATAL:
			levelStr = "--- FATAL ERROR --- "
		elif level == LOG_LEVEL_WARNING:
			levelStr = "--- WARNING --- "
		elif level == LOG_LEVEL_VERBOSE:
			levelStr = "    "
		else:
			levelStr = ""
		preamble = f"{levelStr}[{inspect.stack()[1][3]}] " 
		print(f"{preamble}{message}")
	if level == LOG_LEVEL_FATAL:
		raise Exception(message)


def connected(host="8.8.8.8", port=53, timeout=3):
    """
    Check network connectivity
    Host: 8.8.8.8 (google-public-dns-a.google.com)
    OpenPort: 53/tcp
    Service: domain (DNS/TCP)
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error as ex:
        return False


def setModeLed():
	'''
	Set the mode LED state to reflect if in manual mode or not
	'''
	if autoMode:
		modeLED.off()
	else:
		modeLED.on()


log(f"Loaded config file : {BASE_DIR}{CONFIG_FILE}", LOG_LEVEL_INFO)
log("Starting SlideShow-03", LOG_LEVEL_INFO)

setConfigs = getConfig(CK_IMAGE_SETS)
imageSets = []
for setConfig in setConfigs:
	imageSets.append(
		ImageSet(
			getSetConfig(setConfig, CK_SET_NAME),
			BASE_DIR,
			getSetConfig(setConfig, CK_SET_URL),
			getSetConfig(setConfig, CK_SET_AUTO).upper() == "Y",
			randomise= (getSetConfig(setConfig, CK_SET_RANDOMISE).upper() == "Y"),
			refreshMins = getSetConfig(setConfig, CK_SET_REFRESH_MINS)
		)	
	)

setCount = len(imageSets)
currentSetIndex = 0
autoMode = imageSets[currentSetIndex].auto
setModeLed()


def refreshImageSets():
	'''
	Update the image sets if required
	'''
	log("refreshing image sets ...", LOG_LEVEL_INFO)
	if not connected():
		log("Unable to refresh images, no network connection", LOG_LEVEL_WARNING)
		return
	for imgSet in imageSets:
		imgSet.checkForRefresh()
		log(f"Image set {imgSet.name} contains {imgSet.imageCount} images", LOG_LEVEL_VERBOSE)


def showCurrentImage():
	'''
	Disdplay the curreently selected image (in a safe way)
	'''
	if currentSetIndex is None or imageSets[currentSetIndex].currentImageName is None:
		log(f"Showing default splash image {BASE_SPLASH}", LOG_LEVEL_WARNING)		
		picture.image = BASE_SPLASH 
	else:
		log(f"Showing image '{imageSets[currentSetIndex].currentImageName} from image set {currentSetIndex}", LOG_LEVEL_VERBOSE)
		picture.image = imageSets[currentSetIndex].currentImageName


def advanceImage():
	'''
	Update the display to the next image in the list
	Supresses a possible image set refresh if in manual mode
	'''
	picture.image = imageSets[currentSetIndex].advanceImage(skipRefresh=not autoMode)
	log(f"Showing image '{imageSets[currentSetIndex].currentImageName} from image set {currentSetIndex}", LOG_LEVEL_VERBOSE)


def previousImage():
	'''
	Update the display to the provious image in the list
	Supresses a possible imgae set refresh if in manual mode
	'''
	picture.image = imageSets[currentSetIndex].previousImage(skipRefresh=not autoMode)
	log(f"Showing image '{imageSets[currentSetIndex].currentImageName} from image set {currentSetIndex}", LOG_LEVEL_VERBOSE)


def setImageSetByIndex(setIndex):
	'''
	Set the current image set based on a supplied index
	'''
	global currentSetIndex, autoMode
	currentSetIndex = min(max(setIndex, 0), setCount-1)
	# if currentSetIndex == 0:
	# 	automode = True
	# else:
	# 	automode = imageSets[currentSetIndex].auto
	log(f"Switching to image set {setIndex}", LOG_LEVEL_INFO)
	autoMode = imageSets[currentSetIndex].auto
	setModeLed()
	log(f"Showing image {imageSets[currentSetIndex].currentImageName}", LOG_LEVEL_VERBOSE)
	picture.image = imageSets[currentSetIndex].currentImageName


def cycleImageSet(delta=1):
	'''
	Cycle through the image set by the specified delta
	'''
	newIndex = currentSetIndex + delta
	if newIndex >= setCount:
		newIndex = 0
	elif newIndex < 0:
		newIndex = setCount - 1
	setImageSetByIndex(newIndex)


def previousImageSet():
	cycleImageSet(delta=-1)


def modeHeldEvent():
	'''
	Handles the mode button being used.
	If in single set mode, toggle between auto and manual advance
	If in multiple set mode, cycle through image sets
	'''
	log("Mode button held", LOG_LEVEL_INFO)
	global currentSetIndex, autoMode
	if setCount == 1:
		# single set mode
		autoMode = not autoMode
		setModeLed()
		if not autoMode:
			imageSets[currentSetIndex].orderImageNames()
		picture.image = imageSets[currentIndex].currentImageName
	else:
		# multiple set mode
		cycleImageSet()


def advancePressedEvent():
	'''
	NOP if in auto mode.
	If in manual mode advances the slide, wrapping at the end. 
	Does not check for refresh interval on remote content.
	'''
	log("Advance button pressed", LOG_LEVEL_INFO)
	if autoMode:
		return
	advanceImage()


def get_ir_device():
	'''
	Returns the Infrared Remote Receiver device, or None if not configured
	'''
	devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
	for device in devices:
		if device.name == "gpio_ir_recv":
			return device
	return None


def autoAdvance():
	'''
	Event handler triggered by repeat on picture
	'''
	if autoMode:
		advanceImage()


ir_recv = get_ir_device()
if ir_recv is None:
	log("IR receiver not found", LOG_LEVEL_WARNING)
else:
	log(f"IR receiever found : {ir_recv}", LOG_LEVEL_INFO)

# map IR event values to event handler functions
IR_EVENT_HANDLERS = {
	70 : advanceImage,
	21 : previousImage,
	67 : cycleImageSet,
	68 : previousImageSet,
	64 : modeHeldEvent
}
IR_DEBOUNCE_SEC = 1

last_IR_DTS = 0
IR_POLLING_MS = 100


def check_ir():
	'''
	Check the IR remote receiver for events
	'''
	global last_IR_DTS
	try:
		for ev in ir_recv.read():
			if ev.type != 4:
				pass
			else:
				thisDTS = ev.sec + (ev.usec/1000000)
				if (thisDTS - last_IR_DTS) >= IR_DEBOUNCE_SEC:
					last_IR_DTS = thisDTS
					if ev.value in IR_EVENT_HANDLERS:
						log(f"Calling IR event handler {IR_EVENT_HANDLERS[ev.value].__name__}", LOG_LEVEL_INFO)
						IR_EVENT_HANDLERS[ev.value]()
					else:
						log(f"Unsupported IR event received, value = {ev.value}", LOG_LEVEL_VERBOSE)
	except BlockingIOError:
		# Raised if read() finds no input
		pass


modeLED.off()

refreshImageSets()

modeButton.when_held = modeHeldEvent
advanceButton.when_pressed = advancePressedEvent

app = App(getConfig(CK_TITLE))
app.set_full_screen()

picture = Picture(app, image=BASE_SPLASH)
showCurrentImage()

picture.width = getConfig(CK_DISPLAY_SIZE)[0]
picture.height = getConfig(CK_DISPLAY_SIZE)[1]

picture.repeat(getConfig(CK_INTERVAL), autoAdvance)
if ir_recv is not None:
	picture.repeat(IR_POLLING_MS, check_ir)

app.display()
