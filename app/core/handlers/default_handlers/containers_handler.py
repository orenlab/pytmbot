#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from app.core.handlers.handler import Handler
from app import build_logger
from app.core.adapters.psutil_adapter import PsutilAdapter


class ContainersHandler(Handler):
    def __init__(self, bot):
        super().__init__(bot)
        self.log = build_logger(__name__)
        self.psutil_adapter = PsutilAdapter()
        self.migrate = False

    def handle(self):
        @self.bot.message_handler(regexp="Containers")
        def get_containers(message) -> None:
            """
            Get docker containers info
            """
            if not self.migrate:
                self.log.info(f"Method {__name__} needs to migrate")
            try:
                self.log.info(self.bot_msg_tpl.HANDLER_START_TEMPLATE.format(
                    message.from_user.username,
                    message.from_user.id,
                    message.from_user.language_code,
                    message.from_user.is_bot
                ))
                context = self.api_data.get_metrics('containers')
                if context == {}:
                    bot_answer = self.jinja.render_templates(
                        'none.jinja2',
                        thought_balloon=self.get_emoji('thought_balloon')
                    )
                    self.bot.send_message(message.chat.id, text=bot_answer)
                else:
                    context_process = []
                    for value in context['containers']:
                        created_date = self.split_str(value['Created'], 'T')
                        created_time = self.split_str(created_date[1], '.')
                        image_name = self.replace_symbol(value['Image'])
                        context_process += {
                            'name': value['name'].title(),
                            'Uptime': value['Uptime'],
                            'Created': f"{created_date[0]}, {created_time[0]}",
                            'Image': image_name[0],
                            'Status': value['Status']},
                    bot_answer = self.jinja.render_templates(
                        'containers.jinja2',
                        thought_balloon=self.get_emoji('thought_balloon'),
                        luggage=self.get_emoji('pushpin'), minus=self.get_emoji('minus'),
                        context=context_process
                    )
                    inline_button = self.keyboard.build_inline_keyboard(
                        "Check image update",
                        "docker_image_update"
                    )
                    self.bot.send_message(
                        message.chat.id,
                        text=bot_answer,
                        reply_markup=inline_button)

            except ValueError as err:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                ) from err
            except self.TemplateError as err_tpl:
                raise self.exceptions.PyTeleMonBotTemplateError(
                    self.bot_msg_tpl.TPL_ERR_TEMPLATE
                ) from err_tpl
