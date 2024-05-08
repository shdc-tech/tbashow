'''
A class to manage a local repository of images loaded from a changing web repository

Copyright 2023, John Grosvenor

Modified April 2024 to support a simpler mode of operation without we updates
'''

import random
import socket
import os
import requests
import shutil
import json

from datetime import datetime, timedelta


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


class ImageSet:
	'''
	A class to manage a local repository of images loaded from a changing web repository
	Static local content can also be incorporated.
	All files are stored under a subdirectory with the name of the set.
	Within this directory there should be cache, local and staging

	NOTE: If the image set is initialised with no URL it will act as a purely manual
	repository. No attempt will be made to refresh the images. Images will be managed
	manually and stored in teh local sub directory only.
	'''

	def __init__(
			self,
			name, baseDir, urlRoot, auto,
			imageTypes=["png"], randomise=False, gap=5, refreshMins= 30, remotePrefix = ''
		):
		'''
		Files are expected to be on the web at <urlRoot><remotePrefix><name>.000.<imageTypes[0]>
		Only one file type is supported for remote files (the first specified in imageTypes)
		'''
		self.name = name
		self.baseDir = baseDir
		self.urlRoot = urlRoot
		self.auto = auto
		self.imageTypes = imageTypes
		self.gap = gap
		self.randomise = randomise
		self.imageNames = []
		self.currentIndex = 0
		self.lastUpdate = None
		self.remotePrefix = remotePrefix
		self.firstRemoteIndex = 0
		self.refreshMins = refreshMins
		self.setUpDirs()


	@property
	def simpleMode(self):
		return self.urlRoot is None

	@property
	def webMode(self):
		return self.urlRoot is not None

	@property
	def rootDir(self):
		return self.baseDir + self.name

	@property
	def stagingDir(self):
		return self.baseDir + self.name + "/staging/"

	@property
	def cacheDir(self):
		return self.baseDir + self.name + "/cache/"

	@property
	def localDir(self):
		return self.baseDir + self.name + "/local/"

	@property
	def cacheIndexName(self):
		return self.baseDir + self.name + "/cacheIndex.json"


	def setUpDirs(self):
		'''
		Check for existance of required directories and create them if needed
		Checks for local, cache and staging in a directory named after the set
		'''
		def checkDir(dir):
			if not os.path.isdir(dir):
				os.mkdir(dir)
					
		checkDir(self.rootDir)
		checkDir(self.localDir)
		checkDir(self.cacheDir)
		checkDir(self.stagingDir)


	def getFilesIn(self, path, suffixes, fullpath=True):
		'''
		Returns a list of file paths or names in the directory which match the suffixes
		Returns either the full path (default), or just the file name (fullPath=False)
		'''

		if self.simpleMode and path != self.localDir:
			# ignore contents of all but the local dir in simple mode
			return []

		files = []
		# NB "os.scandir ... The entries are yielded in arbitrary order"
		with os.scandir(path) as entries:
			for entry in entries:
				if entry.is_file():
					suffix = entry.name.split('.')[-1:][0].lower()
					if suffix in suffixes:
						files.append(entry.path if fullpath else entry.name)
		files.sort()
		return files


	def clearStaging(self):
		'''
		Deletes all files from the staging directory
		'''
		staged = self.getFilesIn(self.stagingDir, self.imageTypes)
		for path in staged:
			os.remove(path)


	def updateImages(self):
		'''
		Updates the local cache of images to match the web repository
		New or updated images are downloaded to the staging directory and then copied to the cache
		Updates are identified using the cache index. If no cache index is found all images are treated as new
		'''

		if self.simpleMode:
			self.refreshImageNames()
			return

		if not connected():
			print("WARNING - Unable to update images, no network connection")
			return

		CACHE_STATUS_NONE = 0
		CACHE_STATUS_UPTODATE = 1
		CACHE_STATUS_UPDATED = 2
		CACHE_STATUS_NEW = 3
		CACHE_STATUS_DELETED = 4

		KEY_LAST_MOD = 'Last-Modified'
		KEY_STATUS = 'Status'

		self.clearStaging()
		# load cache index
		try:
			oldIndexFile = open(self.cacheIndexName, 'r')
			oldIndex = json.loads(oldIndexFile.read())
		except Exception as e:
			oldIndex = {}
		newIndex = {}
		cachedNames = self.getFilesIn(self.cacheDir, self.imageTypes, fullpath=False)
		# scan remote repository
		imageNo = 1
		gap = 0
		trying = True
		while gap <= self.gap:
			filename = f"{self.remotePrefix}{self.name}.{imageNo:03}.{self.imageTypes[0]}"
			url = f"{self.urlRoot}{filename}"
			print(f"... Looking for {url}")
			stageName = f"{self.stagingDir}{filename}"
			headers = None
			try:
				headerReq = requests.head(url)
				found = headerReq.status_code == 200
				if found:
					headers = headerReq.headers
				else:
					print(f"...... Not found, status {headerReq.status_code}")
			except Exception as e:
				print(f"...... request failed - {e}")
				found = False
			status = CACHE_STATUS_NONE
			if found:
				if filename in oldIndex:
					# in the index, check update DTS
					if 'Last-Modified' in headers:
						if headers[KEY_LAST_MOD] == oldIndex[filename][KEY_LAST_MOD]:
							status = CACHE_STATUS_UPTODATE
						else:
							status = CACHE_STATUS_UPDATED
					else:
						status = CACHE_STATUS_NEW
				else:
					status = CACHE_STATUS_NEW
				newIndex[filename] = {KEY_STATUS : status, KEY_LAST_MOD : headers[KEY_LAST_MOD] if KEY_LAST_MOD in headers else None}
			else:
				gap += 1
				if filename in oldIndex or filename in cachedNames:
					status = CACHE_STATUS_DELETED
					newIndex[filename] = {KEY_STATUS : status, KEY_LAST_MOD : None}
			r = None
			if status == CACHE_STATUS_UPDATED or status == CACHE_STATUS_NEW:
				try:
					r = requests.get(url, allow_redirects=True)
				except Exception as e:
					# might happen if network fails between head and get requests, so handle gracefully
					del newIndex[filename]
					if status == CACHE_STATUS_UPDATED:
						newIndex[filename] = {KEY_STATUS : CACHE_STATUS_UPTODATE, KEY_LAST_MOD : oldIndex[filename][KEY_LAST_MOD]}
					gap += 1
			if r is not None:
				if r.status_code != 200:
					# might happen if network fails between head and get requests, so handle gracefully
					del newIndex[filename]
					if status == CACHE_STATUS_UPDATED:
						newIndex[filename] = {KEY_STATUS : CACHE_STATUS_UPTODATE, KEY_LAST_MOD : oldIndex[filename][KEY_LAST_MOD]}
					gap += 1
				else:
					open(stageName, 'wb').write(r.content)
			imageNo += 1
		# check that all images in the cache are now in the new index and add delete entries for any missing
		for cached in cachedNames:
			if cached not in newIndex:
				newIndex[cached] = {KEY_STATUS : CACHE_STATUS_DELETED, KEY_LAST_MOD : None}
		# new images and updates should now be in staging, and there should be an entry in new index for every file in staging or cached
		for filename in newIndex:
			stagingPath = self.stagingDir + filename
			cachePath = self.cacheDir + filename
			if newIndex[filename][KEY_STATUS] == CACHE_STATUS_NEW:
				shutil.copy(stagingPath, self.cacheDir)
			elif newIndex[filename][KEY_STATUS] == CACHE_STATUS_UPDATED:
				os.remove(cachePath)
				shutil.copy(stagingPath, self.cacheDir)
			elif newIndex[filename][KEY_STATUS] == CACHE_STATUS_DELETED:
				os.remove(cachePath)
		# remove deleted entries from index and save it
		indexFilenames = list(newIndex.keys())
		for indexFilename in indexFilenames:
			if newIndex[indexFilename][KEY_STATUS] == CACHE_STATUS_DELETED:
				del newIndex[indexFilename]
		try:
			os.remove(self.cacheIndexName)
		except:
			print(f"WARNING - Unable to delete old cache index {self.cacheIndexName}")
		jsonIndex = json.dumps(newIndex)
		try:
			with open(self.cacheIndexName, 'w') as outfile:
				outfile.write(jsonIndex)
		except:
			print(f"WARNING - Unable to write cache index to {self.cacheIndexName}")
		self.refreshImageNames()


	def shuffleImageNames(self):
		'''
		Shuffle the list of image names
		'''
		if len(self.imageNames) < 2:
			return
		lastShown = self.imageNames[self.imageCount - 1]
		for r in range(3):
			for i in range(self.imageCount):
				t = random.randrange(self.imageCount)
				if t != i:
					sv = self.imageNames[i]
					self.imageNames[i] = self.imageNames[t]
					self.imageNames[t] = sv
		# make sure that the first image is not the last one that was shown
		attempts = 0
		while lastShown == self.imageNames[0] and attempts < 20:
			attempts += 1
			t = random.randrange(self.imageCount)
			if t != i:
				sv = self.imageNames[i]
				self.imageNames[i] = self.imageNames[t]
				self.imageNames[t] = sv


	def refreshImageNames(self):
		'''
		Refresh the image name list, current index and last update DTS
		'''
		self.imageNames = self.getFilesIn(self.localDir, self.imageTypes) + self.getFilesIn(self.cacheDir, self.imageTypes)
		self.currentIndex = 0
		if self.randomise:
			self.shuffleImageNames()
		self.lastUpdate = datetime.now()


	def orderImageNames(self):
		'''
		Returns the image name list to sorted order, local content first
		Sets the current index to the first remote image in the set (if any, otherwise first local image)
		'''
		self.imageNames = self.getFilesIn(self.localDir, self.imageTypes)
		self.currentIndex = len(self.imageNames)
		self.imageNames = self.imageNames + self.getFilesIn(self.cacheDir, self.imageTypes)
		if self.currentIndex >= len(self.imageNames):
			self.currentIndex = 0


	def checkForRefresh(self):
		'''
		Check whether the image set is due a refresh, and if so, do it.
		'''
		if self.lastUpdate is None:
			updateRequired = True
		else:
			tdelta = datetime.now() - self.lastUpdate
			elapsedMins = ((tdelta.days * 86400) + tdelta.seconds) / 60
			updateRequired = elapsedMins >= self.refreshMins
		if updateRequired:
			self.updateImages()


	def advanceImage(self, skipRefresh=False):
		'''
		Advance to the next image, looping at the end and rerandomising as appropriate
		Returns the new current image name
		'''
		if not skipRefresh:
			self.checkForRefresh()
		if self.currentIndex < (self.imageCount - 1):
			self.currentIndex += 1
		else:
			self.currentIndex = 0
			if self.randomise:
				self.shuffleImageNames()
		return self.currentImageName


	def previousImage(self, skipRefresh=False):
		'''
		Move to the previous image, looping at the end and rerandomising as appropriate
		Returns the new current image name
		'''
		if not skipRefresh:
			self.checkForRefresh()
		if self.currentIndex > 0:
			self.currentIndex -= 1
		else:
			self.currentIndex = self.imageCount - 1
			if self.randomise:
				self.shuffleImageNames()
		return self.currentImageName


	@property
	def currentImageName(self):
		if self.currentIndex is None or self.currentIndex <0 or self.currentIndex >= len(self.imageNames):
			return None
		else:
			return self.imageNames[self.currentIndex]

	
	@property
	def imageCount(self):
		return len(self.imageNames)



if __name__ == "__main__":

	imageSet = ImageSet(
		"teaching",
		"./",
		"http://www.tasbridge.com.au/pics/",
		randomise=True,
	)

	imageSet.updateImages()

	print(f"{imageSet.imageCount} images loaded")

	for i in range(0, imageSet.imageCount):
		print(f"{imageSet.currentIndex} : {imageSet.currentImageName}")
		imageSet.advanceImage()