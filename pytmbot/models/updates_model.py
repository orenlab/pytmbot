#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InlineKeyboardButton(BaseModel):
    text: str
    callback_data: str | None = None
    url: str | None = None
    model_config = ConfigDict(extra="allow")


class InlineKeyboardMarkup(BaseModel):
    inline_keyboard: list[list[InlineKeyboardButton]]
    model_config = ConfigDict(extra="allow")


class User(BaseModel):
    id: int
    is_bot: bool
    first_name: str
    last_name: str | None = None
    username: str | None = None
    model_config = ConfigDict(extra="allow")


class Chat(BaseModel):
    id: int
    type: str
    title: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    model_config = ConfigDict(extra="allow")


class MessageEntity(BaseModel):
    type: str
    offset: int
    length: int
    url: str | None = None
    user: User | None = None
    model_config = ConfigDict(extra="allow")


class Message(BaseModel):
    message_id: int
    date: int
    chat: Chat
    from_user: User | None = Field(None, alias="from")
    text: str | None = None
    entities: list[MessageEntity] | None = None
    reply_markup: InlineKeyboardMarkup | None = None
    model_config = ConfigDict(extra="allow")


class CallbackQuery(BaseModel):
    id: str
    from_user: User = Field(..., alias="from")
    message: Message | None = None
    inline_message_id: str | None = None
    chat_instance: str
    data: str | None = None
    game_short_name: str | None = None
    model_config = ConfigDict(extra="allow")


class InlineQuery(BaseModel):
    id: str
    from_user: User = Field(..., alias="from")
    query: str
    offset: str
    chat_type: str | None = None
    model_config = ConfigDict(extra="allow")


class ChosenInlineResult(BaseModel):
    result_id: str
    from_user: User = Field(..., alias="from")
    query: str
    inline_message_id: str | None = None
    model_config = ConfigDict(extra="allow")


class ShippingQuery(BaseModel):
    id: str
    from_user: User = Field(..., alias="from")
    invoice_payload: str
    shipping_address: dict[str, Any]
    model_config = ConfigDict(extra="allow")


class PreCheckoutQuery(BaseModel):
    id: str
    from_user: User = Field(..., alias="from")
    currency: str
    total_amount: int
    invoice_payload: str
    model_config = ConfigDict(extra="allow")


class PollAnswer(BaseModel):
    poll_id: str
    user: User
    option_ids: list[int]
    model_config = ConfigDict(extra="allow")


class Poll(BaseModel):
    id: str
    question: str
    options: list[dict[str, Any]]
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
    from_user: User = Field(..., alias="from")
    date: int
    old_chat_member: ChatMember
    new_chat_member: ChatMember
    invite_link: dict[str, Any] | None = None
    model_config = ConfigDict(extra="allow")


class ChatJoinRequest(BaseModel):
    chat: Chat
    from_user: User = Field(..., alias="from")
    user_chat_id: int
    date: int
    bio: str | None = None
    invite_link: dict[str, Any] | None = None
    model_config = ConfigDict(extra="allow")


class UpdateModel(BaseModel):
    update_id: int = Field(..., gt=0)
    message: Message | None = None
    edited_message: Message | None = None
    channel_post: Message | None = None
    edited_channel_post: Message | None = None
    inline_query: InlineQuery | None = None
    chosen_inline_result: ChosenInlineResult | None = None
    callback_query: CallbackQuery | None = None
    shipping_query: ShippingQuery | None = None
    pre_checkout_query: PreCheckoutQuery | None = None
    poll: Poll | None = None
    poll_answer: PollAnswer | None = None
    my_chat_member: ChatMemberUpdated | None = None
    chat_member: ChatMemberUpdated | None = None
    chat_join_request: ChatJoinRequest | None = None

    model_config = ConfigDict(
        extra="allow", populate_by_name=True, arbitrary_types_allowed=True
    )
