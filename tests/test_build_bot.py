import unittest
from unittest.mock import patch

import telebot

from app import build_bot_instance, config
from app.core import exceptions


class TestBuildBotInstance(unittest.TestCase):
    @patch('app.utilities.utilities.parse_cli_args')
    @patch.object(config, 'dev_bot_token')
    @patch.object(config, 'bot_token')
    def test_build_bot_instance_prod_mode(self, mock_bot_token, mock_dev_bot_token, mock_parse_cli_args):
        mock_parse_cli_args.return_value = type('', (), {'mode': 'prod'})
        mock_bot_token.get_secret_value.return_value = 'bot_token'
        bot_instance = build_bot_instance()
        self.assertIsInstance(bot_instance, telebot.TeleBot)
        self.assertEqual(bot_instance.token, 'bot_token')
        self.assertTrue(bot_instance.use_class_middlewares)
        self.assertIsInstance(bot_instance.exception_handler, exceptions.TelebotCustomExceptionHandler)
