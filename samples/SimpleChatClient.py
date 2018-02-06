#!/usr/bin/env python3

# A simple chat client for matrix.
# This sample will allow you to connect to a room, and send/recieve messages.
# Args: host:port username password room
# Error Codes:
# 1 - Unknown problem has occured
# 2 - Could not find the server.
# 3 - Bad URL Format.
# 4 - Bad username/password.
# 11 - Wrong room format.
# 12 - Couldn't find room.

import sys

sys.path.append('../')

import logging
from asyncio import get_event_loop

import samples_common  # Common bits used between samples

from matrix_client.api import MatrixRequestError
from matrix_client.client import MatrixClient


# Called when a message is recieved.
async def on_message(room, event):
    if event['type'] == "m.room.member":
        if event['membership'] == "join":
            print("{0} joined".format(event['content']['displayname']))
    elif event['type'] == "m.room.message":
        if event['content']['msgtype'] == "m.text":
            print("{0}: {1}".format(event['sender'], event['content']['body']))
    else:
        print(event['type'])


async def get_input(room, loop):
    while True:
        msg = await loop.run_in_executor(None, samples_common.get_input)
        if msg == "/quit":
            break
        else:
            await room.send_text(msg)


async def main(loop, host, username, password, room_id_alias):
    client = await MatrixClient(host, loop=loop)

    try:
        await client.login_with_password(username, password)
    except MatrixRequestError as e:
        print(e)
        if e.code == 403:
            print("Bad username or password.")
            sys.exit(4)
        else:
            print("Check your sever details are correct.")
            sys.exit(2)
    try:
        room = await client.join_room(room_id_alias)
    except MatrixRequestError as e:
        print(e)
        if e.code == 400:
            print("Room ID/Alias in the wrong format")
            sys.exit(11)
        else:
            print("Couldn't find room.")
            sys.exit(12)

    room.add_listener(on_message)
    loop.create_task(get_input(room, loop))
    client.start_listener()


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    host, username, password = samples_common.get_user_details(sys.argv)

    if len(sys.argv) > 4:
        room_id_alias = sys.argv[4]
    else:
        room_id_alias = samples_common.get_input("Room ID/Alias: ")

    loop = get_event_loop()
    loop.create_task(
        main(loop, host, username, password, room_id_alias)
    )
    loop.run_forever()
