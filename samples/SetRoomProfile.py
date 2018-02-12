#!/usr/bin/env python3

# Set a profile for a room.
# Args: host:port username password
# Error Codes:
# 2 - Could not find the server.
# 3 - Bad URL Format.
# 4 - Bad username/password.
# 11 - Serverside Error

import asyncio
import sys

sys.path.append('../')

import samples_common

from matrix_client.client import MatrixBaseClient
from matrix_client.api import MatrixRequestError, MatrixHttpLibError

host, username, password = samples_common.get_user_details(sys.argv)

client = MatrixBaseClient(host)


async def main():
    try:
        await client.login_with_password_no_sync(username, password)
    except MatrixRequestError as e:
        print(e)
        if e.code == 403:
            print("Bad username or password.")
            sys.exit(4)
        else:
            print("Check your server details are correct.")
            sys.exit(2)
    except MatrixHttpLibError as e:
        print(e)
        sys.exit(3)

    room = await client.join_room(input("Room:"))
    displayname = input("Displayname:")
    if len(displayname) == 0:
        print("Not setting displayname")
        displayname = None

    avatar = input("Avatar:")
    if len(avatar) == 0:
        print("Not setting avatar")
        avatar = None

    try:
        await room.set_user_profile(displayname, avatar)
    except MatrixRequestError as e:
        print(e)
        sys.exit(11)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
