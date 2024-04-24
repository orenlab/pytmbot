#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from jinja2.sandbox import SandboxedEnvironment
from jinja2 import (
    FileSystemLoader,
    select_autoescape
)
from jinja2.exceptions import TemplateError
from app.core import exceptions


class Jinja2Renderer:
    """Class to render Jinja2 templates"""

    def __init__(self):
        """Initialize the Jinja2 variables"""
        self.loader = None
        self.template_folder: str = "app/templates/"
        self.known_templates: list[str] = [
            'containers.jinja2',
            'fs.jinja2',
            'index.jinja2',
            'load_average.jinja2',
            'memory.jinja2',
            'none.jinja2',
            'process.jinja2',
            'sensors.jinja2',
            'uptime.jinja2',
            'swap.jinja2'
        ]

    def _init_jinja2(self):
        """Initializes the Jinja2. Protected method for secure reason"""
        try:
            self.loader = FileSystemLoader(self.template_folder)
            jinja2 = SandboxedEnvironment(
                loader=self.loader,
                autoescape=select_autoescape(
                    ['html', 'txt', 'jinja2'],
                    default_for_string=True
                )
            )
            return jinja2
        except TemplateError:
            raise exceptions.PyTeleMonBotTemplateError(
                "Error loading template"
            )

    def render_templates(self, template_name: str, **context: dict):
        """Render template on Jinja2"""
        try:
            if template_name in self.known_templates:
                jinja = self._init_jinja2()
                template = jinja.get_template(template_name)
                rendered_template = template.render(**context)
                return rendered_template
            else:
                raise exceptions.PyTeleMonBotTemplateError(
                    "Unknown template name"
                )
        except TemplateError:
            raise exceptions.PyTeleMonBotTemplateError(
                "Error parsing template"
            )
