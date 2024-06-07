import logging
import unittest
from unittest.mock import patch

from app.core.logs import build_bot_logger


class TestBuildBotLogger(unittest.TestCase):

    @patch('app.utilities.utilities.parse_cli_args')
    def test_log_level_info(self, mock_parse_cli_args):
        mock_parse_cli_args.return_value = type('', (), {'log_level': 'INFO'})
        logger = build_bot_logger()
        self.assertEqual(logger.level, logging.INFO)

    @patch('app.utilities.utilities.parse_cli_args')
    def test_log_level_unknown(self, mock_parse_cli_args):
        mock_parse_cli_args.return_value = type('', (), {'log_level': 'UNKNOWN'})
        logger = build_bot_logger()
        self.assertEqual(logger.level, logging.INFO)

    @patch('app.utilities.utilities.parse_cli_args')
    def test_log_format_not_debug(self, mock_parse_cli_args):
        mock_parse_cli_args.return_value = type('', (), {'log_level': 'INFO'})
        logger = build_bot_logger()
        self.assertEqual(logger.handlers[0].formatter._fmt, '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    @patch('app.utilities.utilities.parse_cli_args')
    def test_logger_name(self, mock_parse_cli_args):
        mock_parse_cli_args.return_value = type('', (), {'log_level': 'INFO'})
        logger = build_bot_logger()
        self.assertEqual(logger.name, 'pyTMbot')

    @patch('app.utilities.utilities.parse_cli_args')
    def test_logger_propagation(self, mock_parse_cli_args):
        mock_parse_cli_args.return_value = type('', (), {'log_level': 'INFO'})
        logger = build_bot_logger()
        self.assertFalse(logger.propagate)
