# Copyright (C) 2013 Screaming Cats

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from ws4py.websocket import WebSocket

from base64 import urlsafe_b64decode
import json
import time

from common.db import UserData

from wsapi.room import Room
	
from sqlalchemy.orm import sessionmaker

from werkzeug.contrib.securecookie import SecureCookie

Session = sessionmaker()

rooms = {
	
}

# Just a temporary thing for counting users.
# Used to generate names for users.
# This will probably go away when we come up with a real username system.

class UserWebSocket(WebSocket):
	usercount = 0

	secret_key = ""

	#######################
	# WEBSOCKET FUNCTIONS #
	#######################

	def opened(self):
		# Set up the actions dict.
		self.room = None
		self.actions = {
			"init": self.action_init,
			"sync": self.action_sync,
			"play": self.action_play,
			"pause": self.action_pause,
			"seek": self.action_seek,
			"changevideo": self.action_changevideo,
			"addvideo": self.action_addvideo,
			"removevideo": self.action_removevideo,
			"chatmsg": self.action_chatmsg,
		}

		# Generate a username for the user.
		self.username = "Guest %i" % UserWebSocket.usercount
		self.user_data = None
		UserWebSocket.usercount += 1

	def received_message(self, message):
		data = None
		action = None

		if not message.is_text:
			self.close(1008, "All messages must be valid JSON.")
			return

		try:
			data = json.loads(message.data)
			action = data["action"]
		except ValueError:
			self.close(1008, "All messages must be valid JSON.")
			return

		# Try find an action that matches the specified action.
		if not action in self.actions:
			self.send_error("invalid_action", "An action was sent to the server that it did not understand.")
		else:
			self.actions[action](data)

	def closed(self, code, reason=None):
		if self.room:
			self.room.remove_user(self)


	####################
	# RECEIVED ACTIONS #
	####################

	def action_init(self, data):
		"""
		Action sent by the client when the user joins a room.
		This function expects the data to contain the following information: pass
		Responds with information about what's currently going on such as the currently playing video's ID, time, playlist info, etc.
		"""

		if "room_id" not in data:
			self.close(1008, "init action requires a room ID")
			return

		if "session" in data:
			# If a session was given, attempt to read it and load user info from the database.
			user = None
			session_data = SecureCookie.unserialize(data["session"], UserWebSocket.secret_key)

			if "username" in session_data:
				dbsession = Session()
				user = dbsession.query(UserData).filter_by(name=session_data["username"]).first()

			if user is not None:
				# User is authenticated.
				self.user_data = user
				self.username = user.name
			else:
				self.user_data = None

		# If the room ID specified in data doesn't exist, we need to create it.
		if data["room_id"] not in rooms:
			rooms[data["room_id"]] = Room(data["room_id"])
		if len(rooms[data["room_id"]].users) <= 0 and rooms[data["room_id"]].owner is None:
			rooms[data["room_id"]].set_room_owner(self)

		# Set self.room to the room we're joining.
		self.room = rooms[data["room_id"]]

		# Add the user to the room.
		self.room.add_user(self)

	def action_sync(self, data):
		"""
		Action sent from the client to request that the server send the client a sync action.
		"""
		self.send_sync()

	def action_play(self, data):
		"""
		Plays the video. Duh...
		This also is used for seeking. When a seek is done, the client sends a play event and specifies the time that was seeked to.
		All this really does is update start_time, set current_pos to the given time, and set is_playing to True
		"""

		if self.room.is_playing:
			# If room is already playing, sync the user who tried to play it.
			# Unless they're seeking.
			self.send_sync()
			return

		self.room.play(user=self)

	def action_seek(self, data):
		"""
		Seeks the video to the time specified in data.
		"""

		self.room.seek(data["time"], user=self)

	def action_pause(self, data):
		"""
		Pauses the video. Duh...
		All this does is update current_pos and set is_playing to False
		"""

		if not self.room.is_playing:
			# If room is already paused, sync the user who tried to pause it.
			self.send_sync()
			return

		self.room.pause(user=self)

	def action_changevideo(self, data):
		"""
		Changes the currently playing video.
		Expects the following information: index
		The index given specifies the index in the playlist of the video to play.
		"""

		self.room.change_video(data["index"], user=self)

	def action_addvideo(self, data):
		"""
		Adds a video to the playlist.
		Expects the following information: video_id
		Optionally, index can also be supplied. 
		If index is an integer, the video will be added at the specified index.
		"""

		# Index to add the video at. Add to the end of the list if unspecified.
		index = None
		if "index" in data and type(data["index"]) is int:
			index = data["index"]

		self.room.add_video(data["video_id"], index=index, user=self)

	def action_removevideo(self, data):
		"""
		Removes a video from the playlist.
		Expects the following information: index
		"""

		self.room.remove_video(data["index"], user=self)

	def action_chatmsg(self, data):
		"""
		Posts a chat message from this user to the room.
		"""
		# There's no need to sanitize the message to make sure it doesn't have HTML here.
		# This is done client-side before the message is added to the chat box.
		self.room.post_chat_message(data["message"], self)

	# def action_changenick(self, data):
	# 	"""
	# 	Action for a user changing their nickname.
	# 	No longer used.
	# 	"""

	# 	print("User %s is changing their nick to %s." % (self.username, data["newnick"]));
	# 	self.username = data["newnick"];
	# 	self.room.user_list_update();


	###################
	# SENDING ACTIONS #
	###################

	def send_sync(self):
		"""Sends a sync action to the client."""
		self.send(json.dumps({
			"action": "sync",
			"video_time": self.room.current_pos,
			"is_playing": self.room.is_playing,
		}))

	def send_setvideo(self):
		"""Sends a setvideo action to the client."""
		current_video = self.room.current_video

		self.send(json.dumps({
			"action": "setvideo",
			# The service that the video is playing from. Only YouTube is supported currently.
			"video_service": self.room.video_service, 
			# The ID of the video that's playing. Currently just a test.
			"video_id": "" if current_video is None else current_video["video_id"],
			# The index of the currently playing video in the playlist.
			"playlist_pos": self.room.playlist_position,
		}))

	def send_playlistupdate(self):
		"""Sends a playlistupdate action to the client."""
		self.send(json.dumps({
			"action": "playlistupdate",
			# List of objects containing video info.
			# Yes, we could just pass the item dicts directly, but we want to make it pass only what is necessary.
			# This way, if we add something to the playlist entry dicts, it won't be automatically passed through this.
			"playlist": [{
				"video_id": item["video_id"],
				"title": item["title"],
				"author": item["author"],
				"duration": item["duration"],
			} for item in self.room.playlist],
			"playlist_position": self.room.playlist_position,
		}))

	def send_userlistupdate(self):
		"""Sends a userlistupdate action to the client."""
		self.send(json.dumps({
			"action": "userlistupdate",
			# List of objects containing user info.
			# See the comment in the above send_playlistupdate for the reason why it's done like this.
			"userlist": [{
				"username": user.username,
				"isyou": user is self,
				"isguest": user.is_guest,
				"isowner": user.is_owner,
			} for user in self.room.users],
		}))

	def send_nickupdate(self, newname=None):
		"""
		Sends a namechanged action to the client.
		This action tells the client that their name has been changed.
		"""
		self.send(json.dumps({
			"action": "namechanged",
			"name": self.username if newname is not None else newname,
		}))

	def send_error(self, reason_id, reason_msg=None):
		"""
		Sends an error action to the client.
		reason_id should be a unique reason ID string.
		reason_msg should be a human readable error message. If not specified, will be the same as reason_id.
		"""
		self.send(json.dumps({
			"action": "error",
			"reason": reason_id,
			"reason_msg": reason_msg if reason_msg else reason_id,
		}))

	def send_chatmsg(self, sender, message):
		self.send(json.dumps({
			"action": "chatmsg",
			"sender": sender.username,
			"message": message,
		}));


	###############
	# OTHER STUFF #
	###############

	@property
	def is_owner(self):
		"""Returns true if the user is the owner of the room it's in."""
		return self.room.owner == self.username

	@property
	def is_guest(self):
		"""Returns true if the user is a guest."""
		return self.user_data is None

	def __str__(self):
		return "%s (%s)" % (self.username, self.peer_address[0])
