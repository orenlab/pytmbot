import logging
import unittest
from unittest.mock import patch

from app.core.logs import build_bot_logger


class TestBuildBotLogger(unittest.TestCase):
    @patch('app.utilities.utilities.parse_cli_args')
    def test_build_bot_logger_debug_log_level(self, mock_parse_cli_args):
        mock_parse_cli_args.return_value = type('', (), {'log_level': 'DEBUG'})
        logger = build_bot_logger()
        self.assertEqual(logger.level, logging.DEBUG)
        self.assertEqual(len(logger.handlers), 1)
        self.assertEqual(logger.handlers[0].formatter._fmt,
                         "%(asctime)s - %(name)s - %(levelname)s - %(message)s [%(filename)s | %(funcName)s:%(lineno)d]")

    @patch('app.utilities.utilities.parse_cli_args')
    def test_build_bot_logger_info_log_level(self, mock_parse_cli_args):
        mock_parse_cli_args.return_value = type('', (), {'log_level': 'INFO'})
        logger = build_bot_logger()
        self.assertEqual(logger.level, logging.INFO)
        self.assertEqual(len(logger.handlers), 1)
        self.assertEqual(logger.handlers[0].formatter._fmt, "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    @patch('app.utilities.utilities.parse_cli_args')
    def test_build_bot_logger_warn_log_level(self, mock_parse_cli_args):
        mock_parse_cli_args.return_value = type('', (), {'log_level': 'WARN'})
        logger = build_bot_logger()
        self.assertEqual(logger.level, logging.WARN)
        self.assertEqual(len(logger.handlers), 1)
        self.assertEqual(logger.handlers[0].formatter._fmt, "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    @patch('app.utilities.utilities.parse_cli_args')
    def test_build_bot_logger_error_log_level(self, mock_parse_cli_args):
        mock_parse_cli_args.return_value = type('', (), {'log_level': 'ERROR'})
        logger = build_bot_logger()
        self.assertEqual(logger.level, logging.ERROR)
        self.assertEqual(len(logger.handlers), 1)
        self.assertEqual(logger.handlers[0].formatter._fmt, "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    @patch('app.utilities.utilities.parse_cli_args')
    def test_build_bot_logger_critical_log_level(self, mock_parse_cli_args):
        mock_parse_cli_args.return_value = type('', (), {'log_level': 'CRITICAL'})
        logger = build_bot_logger()
        self.assertEqual(logger.level, logging.CRITICAL)
        self.assertEqual(len(logger.handlers), 1)
        self.assertEqual(logger.handlers[0].formatter._fmt, "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    @patch('app.utilities.utilities.parse_cli_args')
    def test_build_bot_logger_unknown_log_level(self, mock_parse_cli_args):
        mock_parse_cli_args.return_value = type('', (), {'log_level': 'UNKNOWN'})
        with self.assertRaises(ValueError):
            build_bot_logger()
