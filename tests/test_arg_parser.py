import unittest
from argparse import Namespace
from unittest.mock import patch

from app.utilities.utilities import parse_cli_args


class TestParseCLIArgs(unittest.TestCase):

    @patch('argparse.ArgumentParser.parse_args')
    def test_both_arguments_provided(self, mock_parse_args):
        mock_parse_args.return_value = Namespace(mode='dev', log_level='DEBUG')
        args = parse_cli_args()
        self.assertEqual(args.mode, 'dev')
        self.assertEqual(args.log_level, 'DEBUG')

    @patch('argparse.ArgumentParser.parse_args')
    def test_only_mode_argument_provided(self, mock_parse_args):
        mock_parse_args.return_value = Namespace(mode='dev', log_level='INFO')
        args = parse_cli_args()
        self.assertEqual(args.mode, 'dev')
        self.assertEqual(args.log_level, 'INFO')

    @patch('argparse.ArgumentParser.parse_args')
    def test_only_log_level_argument_provided(self, mock_parse_args):
        mock_parse_args.return_value = Namespace(mode='prod', log_level='ERROR')
        args = parse_cli_args()
        self.assertEqual(args.mode, 'prod')
        self.assertEqual(args.log_level, 'ERROR')

    @patch('argparse.ArgumentParser.parse_args')
    def test_no_arguments_provided(self, mock_parse_args):
        mock_parse_args.return_value = Namespace(mode='prod', log_level='INFO')
        args = parse_cli_args()
        self.assertEqual(args.mode, 'prod')
        self.assertEqual(args.log_level, 'INFO')


if __name__ == '__main__':
    unittest.main()
