#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import Union

from pytmbot.parsers._parser import Jinja2Renderer


class Compiler:
    def __init__(self, template_name: str, **kwargs: Union[dict | str]) -> None:
        self.template_name = template_name
        self.kwargs = kwargs
        self.renderer = None

    def __enter__(self) -> 'Compiler':
        self.renderer = Jinja2Renderer.instance()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.renderer:
            self.renderer = None

    def compile(self) -> str:
        if self.renderer:
            return self.renderer.render_templates(self.template_name, **self.kwargs)
        else:
            raise ValueError("Renderer is not initialized. Use 'with' statement to initialize it.")
