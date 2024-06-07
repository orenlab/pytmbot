#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""


class KeyboardSettings:
    """
    Settings for main bot keyboard
    key: emoji name
    value: function name
    """
    main_keyboard: dict = {
        'low_battery': 'Load average',
        'pager': 'Memory load',
        'stopwatch': 'Sensors',
        'rocket': 'Process',
        'flying_saucer': 'Uptime',
        'floppy_disk': 'File system',
        'luggage': 'Containers',
        'satellite': 'Network',
        'turtle': 'About me'
    }
