from enum import Enum


# Cache constants used when instantiating Matrix Client to specify level of caching
class CACHE(Enum):
    NONE = -1
    SOME = 0
    ALL = 1


class ListenerType(Enum):
    GLOBAL = 0
    PRESENCE = 1
    INVITE = 2
    LEAVE = 3
    EPHEMERAL = 4
