from typing import Optional, Any, List, Dict

from attr import dataclass, attrib

from .enums import ListenerType

MaybeStr = Optional[str]
MaybeBool = Optional[bool]
MaybeInt = Optional[int]
MaybeDict = Optional[dict]

weakref_attrib = attrib(init=False, hash=False, repr=False, cmp=False)


@dataclass(slots=True, frozen=True)
class Signed:
    __weakref__: Any = weakref_attrib
    mxid: str
    signatures: Dict[str, Dict[str, str]]
    token: str


@dataclass(slots=True, frozen=True)
class UnsignedData:
    __weakref__: Any = weakref_attrib
    age: MaybeInt = None
    redacted_because: Optional['Event'] = None
    transaction_id: MaybeStr = None


@dataclass(slots=True, frozen=True)
class Event:
    __weakref__: Any = weakref_attrib
    content: MaybeDict = None
    type: str = None
    event_id: str = None
    room_id: str = None
    sender: str = None
    origin_server_ts: int = None
    unsigned: Optional[UnsignedData] = None
    listener_type: Optional[ListenerType] = None

    @classmethod
    def from_dict(cls, d: dict):
        unsigned = d.get('unsigned')
        if unsigned:
            unsigned_data = UnsignedData(**unsigned)
            return cls(
                **{
                    key: val
                    for key, val in d.items()
                    if key != 'unsigned'
                },
                unsigned=unsigned_data
            )
        else:
            return cls(**d)


@dataclass(slots=True, frozen=True)
class Invite:
    __weakref__: Any = weakref_attrib
    display_name: str
    signed: Signed


@dataclass(slots=True, frozen=True)
class EventContent:
    __weakref__: Any = weakref_attrib
    avatar_url: MaybeStr = None
    displayname: MaybeStr = None
    membership: str
    is_direct: MaybeBool
    third_party_invite: Optional[Invite]


@dataclass(slots=True, frozen=True)
class StateEvent:
    __weakref__: Any = weakref_attrib
    prev_content: Any
    state_key: str


@dataclass(slots=True, frozen=True)
class Presence:
    __weakref__: Any = weakref_attrib
    avatar_url: MaybeStr = None
    displayname: MaybeStr = None
    last_active_ago: MaybeInt = None
    presence: str
    currently_active: MaybeBool = None
    user_id: str


@dataclass(slots=True, forzen=True)
class InviteState:
    __weakref__: Any = weakref_attrib
    sender: MaybeStr = None
    type: MaybeStr = None
    state_key: MaybeStr = None
    content: MaybeDict = None


@dataclass(slots=True, forzen=True)
class InvitedRoom:
    __weakref__: Any = weakref_attrib
    room_id: str
    invite_states: List[InviteState] = []


@dataclass(slots=True, forzen=True)
class Timeline:
    __weakref__: Any = weakref_attrib
    events: List[Event] = []
    limited: MaybeBool = None
    prev_batch: MaybeStr = None

    @classmethod
    def from_dict(cls, d):
        events = d.get('events')
        if events:
            return cls(
                **{k: v for k, v in d.items() if k != 'events'},
                events=[Event.from_dict(event) for event in events]
            )
        else:
            return cls(**d)


@dataclass(slots=True, forzen=True)
class LeftRoom:
    __weakref__: Any = weakref_attrib
    room_id: str
    left_states: List[Event] = []
    timeline: Optional[Timeline] = None


@dataclass(slots=True, forzen=True)
class JoinedRoom:
    __weakref__: Any = weakref_attrib
    room_id: str
    state: List[Event] = []
    timeline: Timeline = None
    ephemeral: List[Event] = []
    account_data: List[Event] = []
    highlight_count: MaybeInt = None
    notification_count: MaybeInt = None

    @classmethod
    def from_dict(cls, d: dict):
        state = d.get('state', {}).get('events', [])
        ephemeral = d.get('ephemeral', {}).get('events', [])
        account_data = d.get('account_data', {}).get('events', [])
        timeline = d.get('timeline')
        unread = d.get('unread_notifications', {})

        highlight_count = unread.get('highlight_count')
        notification_count = unread.get('notification_count')
        state_objs = [Event.from_dict(s) for s in state]

        ephemeral_objs = []
        for e in ephemeral:
            e = e.copy()
            e.update(listener_type=ListenerType.EPHEMERAL)
            ephemeral_objs.append(Event.from_dict(e))

        acc_objs = [Event.from_dict(a) for a in account_data]
        timeline_obj = Timeline.from_dict(timeline) if timeline else None

        return cls(
            room_id=d['room_id'],
            state=state_objs,
            timeline=timeline_obj,
            ephemeral=ephemeral_objs,
            account_data=acc_objs,
            highlight_count=highlight_count,
            notification_count=notification_count
        )
