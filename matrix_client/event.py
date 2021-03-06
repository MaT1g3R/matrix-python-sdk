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
    prev_content: dict = {}
    prev_sender: MaybeStr = None
    replaces_state: MaybeStr = None
    age: MaybeInt = None
    redacted_because: Optional["Event"] = None
    redacted_by: MaybeStr = None
    redacts: MaybeStr = None
    transaction_id: MaybeStr = None


@dataclass(slots=True)
class Event:
    __weakref__: Any = weakref_attrib
    content: dict = {}
    prev_content: dict = {}
    membership: MaybeStr = None
    txn_id: MaybeStr = None
    age: MaybeInt = None
    state_key: str = None
    type: str = None
    event_id: str = None
    room_id: str = None
    sender: str = None
    origin_server_ts: int = None
    redacts: MaybeStr = None
    unsigned: Optional[UnsignedData] = None
    listener_type: Optional[ListenerType] = ListenerType.GLOBAL

    @classmethod
    def from_dict(cls, d: dict):
        unsigned = d.get("unsigned")
        if unsigned:
            unsigned_data = UnsignedData(**unsigned)
            return cls(
                **{
                    key: val
                    for key, val in d.items()
                    if key != "unsigned"
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
class InvitedRoom:
    __weakref__: Any = weakref_attrib
    room_id: str
    invite_states: List[Event] = []
    listener_type: ListenerType = attrib(
        default=ListenerType.INVITE, init=False
    )


@dataclass(slots=True, frozen=True)
class Timeline:
    __weakref__: Any = weakref_attrib
    events: List[Event] = []
    limited: MaybeBool = None
    prev_batch: MaybeStr = None

    @classmethod
    def from_dict(cls, d):
        events = d.get("events")
        if events:
            return cls(
                **{k: v for k, v in d.items() if k != "events"},
                events=[Event.from_dict(event) for event in events]
            )
        else:
            return cls(**d)


@dataclass(slots=True, frozen=True)
class LeftRoom:
    __weakref__: Any = weakref_attrib
    room_id: str
    left_states: List[Event] = []
    timeline: Optional[Timeline] = None
    listener_type: ListenerType = attrib(
        default=ListenerType.LEAVE, init=False
    )


@dataclass(slots=True, frozen=True)
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
        state = d.get("state", {}).get("events", [])
        ephemeral = d.get("ephemeral", {}).get("events", [])
        account_data = d.get("account_data", {}).get("events", [])
        timeline = d.get("timeline")
        unread = d.get("unread_notifications", {})

        highlight_count = unread.get("highlight_count")
        notification_count = unread.get("notification_count")
        state_objs = [Event.from_dict(s) for s in state]
        ephemeral_objs = [Event.from_dict(e) for e in ephemeral]
        acc_objs = [Event.from_dict(a) for a in account_data]
        timeline_obj = Timeline.from_dict(timeline) if timeline else None

        return cls(
            room_id=d["room_id"],
            state=state_objs,
            timeline=timeline_obj,
            ephemeral=ephemeral_objs,
            account_data=acc_objs,
            highlight_count=highlight_count,
            notification_count=notification_count
        )
