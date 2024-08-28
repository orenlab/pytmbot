import unittest
from unittest.mock import patch, MagicMock
from io import StringIO
import setup_bot as sb

import cli


class TestConfigBuilder(unittest.TestCase):

    @patch('click.prompt')
    def test_ask_for_user_id(self, mock_prompt):
        mock_prompt.return_value = '000000000000, 000000000001'
        result = sb.ask_for_user_id()
        self.assertEqual(result, '000000000000, 000000000001')

    @patch('click.prompt')
    def test_ask_for_docker_host(self, mock_prompt):
        mock_prompt.return_value = 'unix:///var/run/docker.sock'
        result = sb.ask_for_docker_host()
        self.assertEqual(result, 'unix:///var/run/docker.sock')

    @patch('click.prompt')
    def test_ask_for_dev_token(self, mock_prompt):
        mock_prompt.return_value = '1234567890:FFGGEWGLKxOSLNwoLY7ADlFTt3TjtlrEcYl7hg'
        result = sb.ask_for_dev_token()
        self.assertEqual(result, '1234567890:FFGGEWGLKxOSLNwoLY7ADlFTt3TjtlrEcYl7hg')

    @patch('click.prompt')
    def test_ask_for_prod_token(self, mock_prompt):
        mock_prompt.return_value = '0987654321:ABCDEF1234567890abcdef'
        result = sb.ask_for_prod_token()
        self.assertEqual(result, '0987654321:ABCDEF1234567890abcdef')

    @patch('click.prompt')
    def test_ask_for_admin_user_id(self, mock_prompt):
        mock_prompt.return_value = '000000000000'
        result = sb.ask_for_admin_user_id()
        self.assertEqual(result, '000000000000')

    @patch('click.prompt')
    def test_ask_for_auth_salt(self, mock_prompt):
        mock_prompt.return_value = 'random_salt_value'
        result = sb.ask_for_auth_salt()
        self.assertEqual(result, 'random_salt_value')

    @patch('cli.fs.set_file')
    @patch('cli.generate_salt.generate_random_auth_salt', return_value='random_salt')
    @patch('click.prompt')
    def test_create_dot_env(self, mock_prompt, mock_generate_salt, mock_set_file):
        # Set up mock return values
        mock_prompt.side_effect = [
            '1234567890:FFGGEWGLKxOSLNwoLY7ADlFTt3TjtlrEcYl7hg',
            '0987654321:ABCDEF1234567890abcdef',
            '000000000000, 000000000001',
            '000000000000',
            'unix:///var/run/docker.sock',
            'random_salt'
        ]

        expected_content = """# Setup bot tokens
        bot_token:
          # Prod bot token.
          prod_token:
            - '0987654321:ABCDEF1234567890abcdef'
          # Development bot token. Not necessary for production bot.
          dev_bot_token:
            - '1234567890:FFGGEWGLKxOSLNwoLY7ADlFTt3TjtlrEcYl7hg'
        # Setup access control
        access_control:
          # The ID of the users who have permission to access the bot.
          # You can have one or more values - there are no restrictions.
          allowed_user_ids:
            - [000000000000, 000000000001]
          # The ID of the admins who have permission to access the bot.
          # You can have one or more values, there are no restrictions.
          # However, it's important to keep in mind that these users will be able to manage Docker images and containers.
          allowed_admins_ids:
            - [000000000000]
          # Salt is used to generate TOTP (Time-Based One-Time Password) secrets and to verify the TOTP code.
          # A script for the fast generation of a truly unique "salt" is available in the bot's repository.
          auth_salt:
            - 'random_salt'
        # Docker settings
        docker:
          # Docker socket. Usually: unix:///var/run/docker.sock.
          host:
            - 'unix:///var/run/docker.sock'
        """

        sb.create_dot_env()
        mock_set_file.assert_called_once_with(
            'pytmbot.yaml',
            expected_content.strip()
        )

    @patch('cli.filesystem.has_file', return_value=False)
    @patch('cli.create_dot_env')
    def test_build_config_new_file(self, mock_create_dot_env, mock_has_file):
        with patch('click.secho') as mock_secho:
            sb.build_config()
            mock_create_dot_env.assert_called_once()
            mock_secho.assert_any_call("*** Starting build default .pytmbotenv ***", fg="green", bold=True)
            mock_secho.assert_any_call("All done. Now you can build Docker image and run the bot.", blink=True,
                                       bg='blue', fg='white', bold=True)

    @patch('cli.filesystem.has_file', return_value=True)
    def test_build_config_existing_file(self, mock_has_file):
        with patch('click.secho') as mock_secho:
            sb.build_config()
            mock_secho.assert_any_call(
                "Looks like you already have .pytmbotenv, if you need to reconfigure the bot, remove it.", blink=True,
                fg="yellow", bold=True)
            mock_secho.assert_any_call("All done. Now you can build Docker image and run the bot.", blink=True,
                                       bg='blue', fg='white', bold=True)


if __name__ == '__main__':
    unittest.main()