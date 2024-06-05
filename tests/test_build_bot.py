import unittest
from unittest.mock import patch

from app import build_bot_instance
from app import config
from app.core import exceptions


class TestBuildBotInstance(unittest.TestCase):
    @patch('app.utilities.utilities.parse_cli_args')
    def test_build_bot_instance_dev_mode(self, mock_parse_cli_args):
        mock_parse_cli_args = type('', (), {'mode': 'dev'})
        config.dev_bot_token.get_secret_value.return_value = 'dev_token'
        bot_instance = build_bot_instance()
        self.assertEqual(bot_instance.token, 'dev_token')
        self.assertTrue(bot_instance.use_class_middlewares)
        self.assertIsInstance(bot_instance.exception_handler, exceptions.TelebotCustomExceptionHandler)

    @patch('app.utilities.utilities.parse_cli_args')
    def test_build_bot_instance_prod_mode(self, mock_parse_cli_args):
        mock_parse_cli_args = type('', (), {'mode': 'prod'})
        config.bot_token.get_secret_value.return_value = 'prod_token'
        bot_instance = build_bot_instance()
        self.assertEqual(bot_instance.token, 'prod_token')
        self.assertTrue(bot_instance.use_class_middlewares)
        self.assertIsInstance(bot_instance.exception_handler, exceptions.TelebotCustomExceptionHandler)

    @patch('app.utilities.utilities.parse_cli_args')
    def test_build_bot_instance_invalid_mode(self, mock_parse_cli_args):
        mock_parse_cli_args.return_value = type('', (), {'mode': 'invalid'})
        with self.assertRaises(ValueError):
            build_bot_instance()
