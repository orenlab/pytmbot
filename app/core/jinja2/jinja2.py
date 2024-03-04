#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from jinja2 import Environment, FileSystemLoader, select_autoescape
from jinja2.exceptions import TemplateError
from app.core import exceptions


def init_jinja2():
    """
    Initializes the Jinja2
    @return: jinja2 environment and template
    """
    try:
        loader = FileSystemLoader("app/templates/")
        jinja2 = Environment(loader=loader, autoescape=select_autoescape(['html', 'xml']))
        return jinja2
    except TemplateError as err:
        raise exceptions.PyTeleMonBotTemplateError("Error loading template") from err
