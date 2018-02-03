class User(object):
    """ The User class can be used to call user specific functions.
    """

    def __init__(self, api, user_id, displayname=None):
        if not user_id.startswith("@"):
            raise ValueError("UserIDs start with @")

        if ":" not in user_id:
            raise ValueError("UserIDs must have a domain component,"
                             " seperated by a :")

        self.user_id = user_id
        self.displayname = displayname
        self.api = api

    async def get_display_name(self):
        """ Get this users display name.
            See also get_friendly_name()

        Returns:
            str: Display Name
        """
        if not self.displayname:
            self.displayname = await self.api.get_display_name(self.user_id)
        return self.displayname

    async def get_friendly_name(self):
        display_name = await self.api.get_display_name(self.user_id)
        return display_name if display_name is not None else self.user_id

    async def set_display_name(self, display_name):
        """ Set this users display name.

        Args:
            display_name (str): Display Name
        """
        self.displayname = display_name
        return await self.api.set_display_name(self.user_id, display_name)

    async def get_avatar_url(self):
        mxcurl = await self.api.get_avatar_url(self.user_id)
        url = self.api.get_download_url(mxcurl)
        return url

    async def set_avatar_url(self, avatar_url):
        """ Set this users avatar.

        Args:
            avatar_url (str): mxc url from previously uploaded
        """
        return await self.api.set_avatar_url(self.user_id, avatar_url)
