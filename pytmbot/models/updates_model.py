#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Optional, Dict, Any, List

from pydantic import BaseModel, Field, ConfigDict


class InlineKeyboardButton(BaseModel):
    text: str
    callback_data: Optional[str] = None
    url: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class InlineKeyboardMarkup(BaseModel):
    inline_keyboard: List[List[InlineKeyboardButton]]
    model_config = ConfigDict(extra="allow")


class User(BaseModel):
    id: int
    is_bot: bool
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class Chat(BaseModel):
    id: int
    type: str
    title: Optional[str] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class MessageEntity(BaseModel):
    type: str
    offset: int
    length: int
    url: Optional[str] = None
    user: Optional[User] = None
    model_config = ConfigDict(extra="allow")


class Message(BaseModel):
    message_id: int
    date: int
    chat: Chat
    from_user: Optional[User] = Field(None, alias='from')
    text: Optional[str] = None
    entities: Optional[List[MessageEntity]] = None
    reply_markup: Optional[InlineKeyboardMarkup] = None
    model_config = ConfigDict(extra="allow")


class CallbackQuery(BaseModel):
    id: str
    from_user: User = Field(..., alias='from')
    message: Optional[Message] = None
    inline_message_id: Optional[str] = None
    chat_instance: str
    data: Optional[str] = None
    game_short_name: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class InlineQuery(BaseModel):
    id: str
    from_user: User = Field(..., alias='from')
    query: str
    offset: str
    chat_type: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class ChosenInlineResult(BaseModel):
    result_id: str
    from_user: User = Field(..., alias='from')
    query: str
    inline_message_id: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class ShippingQuery(BaseModel):
    id: str
    from_user: User = Field(..., alias='from')
    invoice_payload: str
    shipping_address: Dict[str, Any]
    model_config = ConfigDict(extra="allow")


class PreCheckoutQuery(BaseModel):
    id: str
    from_user: User = Field(..., alias='from')
    currency: str
    total_amount: int
    invoice_payload: str
    model_config = ConfigDict(extra="allow")


class PollAnswer(BaseModel):
    poll_id: str
    user: User
    option_ids: List[int]
    model_config = ConfigDict(extra="allow")


class Poll(BaseModel):
    id: str
    question: str
    options: List[Dict[str, Any]]
    is_closed: bool
    is_anonymous: bool
    type: str
    allows_multiple_answers: bool
    model_config = ConfigDict(extra="allow")


class ChatMember(BaseModel):
    user: User
    status: str
    model_config = ConfigDict(extra="allow")


class ChatMemberUpdated(BaseModel):
    chat: Chat
    from_user: User = Field(..., alias='from')
    date: int
    old_chat_member: ChatMember
    new_chat_member: ChatMember
    invite_link: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(extra="allow")


class ChatJoinRequest(BaseModel):
    chat: Chat
    from_user: User = Field(..., alias='from')
    user_chat_id: int
    date: int
    bio: Optional[str] = None
    invite_link: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(extra="allow")


class UpdateModel(BaseModel):
    update_id: int = Field(..., gt=0)
    message: Optional[Message] = None
    edited_message: Optional[Message] = None
    channel_post: Optional[Message] = None
    edited_channel_post: Optional[Message] = None
    inline_query: Optional[InlineQuery] = None
    chosen_inline_result: Optional[ChosenInlineResult] = None
    callback_query: Optional[CallbackQuery] = None
    shipping_query: Optional[ShippingQuery] = None
    pre_checkout_query: Optional[PreCheckoutQuery] = None
    poll: Optional[Poll] = None
    poll_answer: Optional[PollAnswer] = None
    my_chat_member: Optional[ChatMemberUpdated] = None
    chat_member: Optional[ChatMemberUpdated] = None
    chat_join_request: Optional[ChatJoinRequest] = None

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        arbitrary_types_allowed=True
    )
