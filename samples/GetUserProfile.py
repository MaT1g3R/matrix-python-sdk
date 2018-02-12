#!/usr/bin/env python3

# Get a users display name and avatar
# Args: host:port username password user_id
# Error Codes:
# 2 - Could not find the server.
# 3 - Bad URL Format.
# 4 - Bad username/password.


import asyncio
import sys

sys.path.append('../')
import samples_common  # Common bits used between samples
from matrix_client.client import MatrixBaseClient
from matrix_client.api import MatrixRequestError, MatrixHttpLibError

host, username, password = samples_common.get_user_details(sys.argv)

client = MatrixBaseClient(host)


async def main():
    try:
        await client.login_with_password(username, password)
    except MatrixRequestError as e:
        print(e)
        if e.code == 403:
            print("bad username or password.")
            sys.exit(4)
        else:
            print("check your server details are correct.")
            sys.exit(2)
    except MatrixHttpLibError as e:
        print(e)
        sys.exit(3)

    if len(sys.argv) > 4:
        userid = sys.argv[4]
    else:
        userid = samples_common.get_input("userid: ")

    try:
        user = client.get_user(userid)
        print("display name: %s" % await user.get_display_name())
        print("avatar %s" % await user.get_avatar_url())
    except MatrixRequestError as e:
        print(e)
        if e.code == 400:
            print("user id/alias in the wrong format")
            sys.exit(11)
        else:
            print("couldn't find room.")
            sys.exit(12)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
