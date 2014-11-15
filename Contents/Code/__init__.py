# Convert sidecar subtitle files files into UTF-8 format
# Created by dane22, a Plex community member
#
# Code contributions made by the following:
#	srazer, also a Plex community member
# jmichiel, also a Plex community member
#

# TODO: 
# Check for pref. set language
#

######################################### Imports ##################################################

import os
import shutil
import io
import codecs
import sys
from BeautifulSoup import BeautifulSoup
import fnmatch

import CP_Windows_ISO

import charedSup
from chared import __version__ as VERSION
from chared.detector import list_models, get_model_path, EncodingDetector

import traceback
import urllib2
import xml.dom.minidom
import unicodedata 

######################################### Global Variables #########################################
PLUGIN_VERSION = '0.0.1.20'
AGENT_TIMEOUT = 3
API_PORT = 32400
MEDIA_DIR = os.path.join(Core.app_support_path, 'Media', 'localhost')


######################################## Start of plugin ###########################################
def Start():
	Log.Info(L('Starting') + ' %s ' %(L('Srt2Utf-8')) + L('with a version of') + ' %s' %(PLUGIN_VERSION))

####################################### Movie Plug-In ###########################################
class MovieAgent(Agent.Movies):
	name = L('Srt2Utf-8') + ' (Movies)'
	languages = [Locale.Language.NoLanguage]
	primary_provider = False
	contributes_to = ['com.plexapp.agents.imdb', 'com.plexapp.agents.themoviedb', 'com.plexapp.agents.none']

	def search(self, results, media, lang, manual):
		results.Append(MetadataSearchResult(id='null', score = 100))

	def update(self, metadata, media, lang, force):
		for i in media.items:
			for part in i.parts:
				Thread.CreateTimer(AGENT_TIMEOUT, handlePart, True, part)

####################################### TV-Shows Plug-In ###########################################
class TvShowsAgent(Agent.TV_Shows):
	name = L('Srt2Utf-8') + ' (TV)'
	languages = [Locale.Language.NoLanguage]
	primary_provider = False
	contributes_to = ['com.plexapp.agents.thetvdb', 'com.plexapp.agents.none']

	def search(self, results, media, lang):
		results.Append(MetadataSearchResult(id='null', score = 100))

	def update(self, metadata, media, lang, force):
		for s in media.seasons:
			# just like in the Local Media Agent, if we have a date-based season skip for now.
			if int(s) < 1900:
				for e in media.seasons[s].episodes:
					for i in media.seasons[s].episodes[e].items:
						for part in i.parts:
							Thread.CreateTimer(AGENT_TIMEOUT, handlePart, True, part)

def api(cmd):
	url = 'http://127.0.0.1:{}{}'.format(API_PORT, cmd)
	Log.Debug('Request: {}'.format(url))
	data = urllib2.urlopen(url).read()
	return xml.dom.minidom.parseString(data)

def get_directory(filename, sections):
	for media_container in sections.getElementsByTagName('MediaContainer'):
		for directory in media_container.getElementsByTagName('Directory'):
			for location in directory.getElementsByTagName('Location'):
				if location.hasAttribute('path'):
					if unicodedata.normalize('NFC', location.getAttribute('path')) in filename:
						return directory

def get_video(filename, section):
	for media_container in section.getElementsByTagName('MediaContainer'):
		for video in media_container.getElementsByTagName('Video'):
			for media in video.getElementsByTagName('Media'):
				for part in media.getElementsByTagName('Part'):
					if part.hasAttribute('file'):
						if urllib2.unquote(part.getAttribute('file').encode('unicode-escape')).decode('utf-8') == filename:
							return video

def get_media_streams(filename, metadata):
	for media_container in metadata.getElementsByTagName('MediaContainer'):
		for metadata_item in media_container.getElementsByTagName('MetadataItem'):
			for media_item in metadata_item.getElementsByTagName('MediaItem'):
				for media_part in metadata_item.getElementsByTagName('MediaPart'):
					return media_part.getElementsByTagName('MediaStream')

def get_subtitles(media_streams):
	subtitles = []
	for media_stream in media_streams:
		if media_stream.hasAttribute('type'):
			if media_stream.getAttribute('type') == '3' and media_stream.hasAttribute('url') and media_stream.hasAttribute('language'):
				url = media_stream.getAttribute('url')

				if 'media://' in url:
					sub_file = os.path.join(MEDIA_DIR, url.replace('media://', ''))
					# there is an lang attribute in media_stream, but it has different codes that we need
					# so this is fix:
					sub_lang = os.path.split(os.path.dirname(sub_file))[-1]
				elif 'file://' in url:
					sub_file = url.replace('file://', '')
					sub_lang = sGetFileLang(sub_file)


				subtitles.append((sub_file, sub_lang))

	return subtitles

def handlePart(*args, **kwargs):
	part = args[0]
	filename = part.file.decode('utf-8')

	Log.Debug('---------------------------------')
	Log.Debug('File: {}'.format(filename))	

	try:
		d = get_directory(filename, api('/library/sections'))
		if d is None:
			raise Exception("Could not associate 'Directory' from sections")

		key = d.getAttribute('key')
		v = get_video(filename, api('/library/sections/{}/allLeaves'.format(key)))
		if v is None:
			raise Exception("Could not associate 'Video/Media/Part' in section {}".format(key))
		
		key = v.getAttribute('key')
		m = get_media_streams(filename, api("{}/tree".format(key)))
		if m is None:
			raise Exception("Could not find 'Video/Media/Part/Stream' in metadata {}".format(key))

		for sub_filename, sub_lang in get_subtitles(m):
			Log.Debug('Subtitle file: {}'.format(sub_filename))
			Log.Debug('Subtitle lang: {}'.format(sub_lang))

			if not bIsUTF_8(sub_filename):
				if sub_lang == 'xx':
					sub_lang = Locale.Language.Match(GetUsrEncPref())
				
				try:
					# Chared supported
					model = charedSup.CharedSupported[sub_lang]
					if model != 'und':
						Log.Debug('Chared is supported for this language')
						enc = FindEncChared(sub_filename, model)
				except:
					Log.Debug('Chared is not supported, reverting to Beautifull Soap')
					enc = FindEncBS(sub_filename, sub_lang)
				# Convert the darn thing
				if enc not in ('utf_8', 'utf-8'):
					# Make a backup
					try:
						MakeBackup(sub_filename)
					except:
						Log.Exception('Something went wrong creating a backup, file will not be converted!!! Check file permissions?')
					else:
						try:
							ConvertFile(sub_filename, enc)
						except:
							Log.Exception('Something went wrong converting!!! Check file permissions?')
							try:
								RevertBackup(sub_filename)
							except:
								Log.Exception("Can't even revert the backup?!? I give up...")
				else:
					Log.Debug('The subtitle file named : %s is already encoded in utf-8, so skipping' %(sub_filename))
			else:
				Log.Debug('The subtitle file named : %s is already encoded in utf-8, so skipping' %(sub_filename))

	except:
		Log.Error('Could not process {}'.format(filename))
		Log.Error(traceback.format_exc())
				

########################################## Convert file to utf-8 ###################################
def ConvertFile(myFile, enc):
	Log.Debug("Converting file: %s with the encoding of %s into utf-8" %(myFile, enc))
	with io.open(myFile, 'r', encoding=enc) as sourceFile, io.open(myFile + '.tmpPlex', 'w', encoding="utf-8") as targetFile:
		targetFile.write(sourceFile.read())
	# Remove the original file
	os.remove(myFile)
	# Name tmp file as the original file name
	os.rename(myFile + '.tmpPlex', myFile)
	Log.Info('Successfully converted %s to utf-8 from %s' %(myFile, enc))

###################### Detect the file encoding using Beautifull Soap #################################
def FindEncBS(myFile, lang):
	try:
		#Read the subtitle file
		Log.Debug('BSFile to encode is %s and filename language is %s' %(myFile, lang))
		f = io.open(myFile, 'rb')
		mySub = f.read()
		soup = BeautifulSoup(mySub)
		soup.contents[0]
		f.close()
		sCurrentEnc = soup.originalEncoding
		Log.Debug('BeautifulSoup reports encoding as %s' %(sCurrentEnc))
		if sCurrentEnc == 'ascii':
			return 'utf-8'
		if sCurrentEnc != 'utf-8':
			# Check result from BeautifulSoup against languagecode from filename
			if lang != 'und':
				# Was it a windows codepage?
				if 'windows-' in sCurrentEnc:
					# Does result so far match our list?
					if sCurrentEnc == CP_Windows_ISO.cpWindows[lang]:
						Log.Debug('Origen CP is %s' %(sCurrentEnc))
					else:
						if CP_Windows_ISO.cpWindows[lang] != "Unknown":
							sCurrentEnc = CP_Windows_ISO.cpWindows[lang]
							Log.Debug('Overriding detection due to languagecode in filename, and setting encoding to %s' %(sCurrentEnc))
						else:
							Log.Debug('******* SNIFF *******')
							Log.Debug("We don't know the default encodings for %s" %(lang))
							Log.Debug('If you know this, then please go here: https://forums.plex.tv/index.php/topic/94864-rel-str2utf-8/ and tell me')

				else:
					# We got ISO
					# Does result so far match our list?
					if sCurrentEnc == CP_Windows_ISO.cpISO[lang]:
						Log.Debug('Origen CP is %s' %(sCurrentEnc))
					else:
						if CP_Windows_ISO.cpWindows[lang] != "Unknown":
							sCurrentEnc = CP_Windows_ISO.cpISO[lang]
							Log.Debug('Overriding detection due to languagecode in filename, and setting encoding to %s' %(sCurrentEnc))
						else:
							Log.Debug('******* SNIFF *******')
							Log.Debug("We don't know the default encodings for %s" %(lang))
							Log.Debug('If you know this, then please go here: https://forums.plex.tv/index.php/topic/94864-rel-str2utf-8/ and tell me')

		return sCurrentEnc
	except UnicodeDecodeError:
		Log.Debug('got unicode error with %s' %(myFile))
		RevertBackup(myFile)
		return False

######################################### Detect the file encoding with chared #####################
def FindEncChared(sMyFile, sModel):
	try:
		# get model file
		model_file = get_model_path(sModel)
		if os.path.isfile(model_file):
			# load model file
			encoding_detector = EncodingDetector.load(model_file)
			# load subtitle
			fp = io.open(sMyFile, 'rb')
			document = fp.read()
			# find codepage
			clas = encoding_detector.classify(document)
			myEnc = clas[0]
			Log.Debug('%s Chared encoding detected as %s' %(sMyFile, myEnc))
			return myEnc
		else:
			Log.Debug('No Language module for %s' %(model_file))
			return 'und'
	except:
		Log.Critical("Unable to load charset detection model from %s. Not supported." %(sModel))

#################### If no language was detected, we need to grap any User Prefs ##############################
def GetUsrEncPref():
	return Prefs['PreferredCP']

#################### Grap a language code from the filename, if present ##############################
# If a language code is present in the filename, then this function will return it
# If no language code is present, it'll return 'xx'
def sGetFileLang(sMyFile):
	# Get the filename
	sFileName, sFileExtension = os.path.splitext(sMyFile)
	# Get language code if present, or else return 'xx'
	sFileName, sFileExtension = os.path.splitext(sFileName)
	myLang = sFileExtension[1:].lower()
	return Locale.Language.Match(myLang)

############################## Returns true is file is in utf-8 #####################################
# Check if the subtitle file already is in utf-8, and if so, returns true
def bIsUTF_8(sMyFile):
	try:
		#Read the subtitle file
		f = io.open(sMyFile, 'rb')
		mySub = f.read()
		soup = BeautifulSoup(mySub)
		soup.contents[0]
		f.close()
		sCurrentEnc = soup.originalEncoding
		if sCurrentEnc == 'utf-8':
			return True
		else:
			return False
	except:
		return False


######################################## Make the backup, if enabled ###############################
def MakeBackup(file):
	if Prefs['Make_Backup']:
		iCounter = 1
		sTarget = file + '.' + 'Srt2Utf-8'
		# Make sure we don't override an already existing backup
		while os.path.isfile(sTarget):
			sTarget = file + '.' + str(iCounter) + '.Srt2Utf-8'
			iCounter = iCounter + 1
		Log.Debug('Making a backup of %s as %s' %(file, sTarget))
		shutil.copyfile(file, sTarget)

######################################## Dummy to avoid bad logging ################################
def ValidatePrefs():
	print Prefs['PreferredCP'] + ': ' + Locale.Language.Match(Prefs['PreferredCP'])
	return

######################################## Revert the backup, if enabled #############################
def RevertBackup(file):
	if Prefs['Make_Backup']:
		Log.Critical('**** Reverting from backup, something went wrong here ****')	
		# Look back of a maximum of 250 backup's
		iCounter = 250
		sTarget = file + '.' + str(iCounter) + '.' + 'Srt2Utf-8'
		# Make sure we don't override an already existing backup
		while not os.path.isfile(sTarget):
			if iCounter == 0:
				sTarget = file + '.' + 'Srt2Utf-8'
			else:				
				sTarget = file + '.' + str(iCounter) + '.' + 'Srt2Utf-8'
			iCounter = iCounter -1
		Log.Debug('Reverting from backup of %s' %(sTarget))
		shutil.copyfile(sTarget, file)
		# Cleanup bad tmp file
		if os.path.isfile(file + '.tmpPlex'):
			os.remove(file + '.tmpPlex')
		# Remove unneeded backup
		if os.path.isfile(sTarget):
			os.remove(sTarget)
		
	else:
		Log.Critical('**** Something went wrong here, but backup has been disabled....SIGH.....Your fault, not mine!!!!! ****')			

