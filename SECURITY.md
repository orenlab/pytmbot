# Security Policy

## Supported Versions

The following versions of pyTMbot are actively supported:

| Version | Supported          | End of Life |
|---------|--------------------|-------------|
| 0.2.2   | :white_check_mark: | TBD         |
| 0.2.1   | :white_check_mark: | 2025-12-31  |
| 0.2.0   | :white_check_mark: | 2025-06-30  |
| < 0.2.0 | :x:                | 2024-12-31  |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them privately by:

- Sending an email to `pytelemonbot@mail.ru`
- Using GitHub's private vulnerability reporting feature

To assist us in understanding and addressing the issue, please include the following information:

1. **Description of the vulnerability:** Clearly describe the issue, including steps to reproduce if possible.
2. **Debug Log:** Attach the [debug log](docs/debug.md) of the bot's activity, which will help us diagnose the problem.
   Ensure that no sensitive data (such as tokens or personal information) is included in the log.

## Our Commitment

We are committed to:

- Acknowledging receipt of your report within 48 hours
- Providing an initial assessment within 5 business days
- Keeping you informed of our progress throughout the investigation

## Responsible Disclosure

We follow a coordinated disclosure process:

1. We will work with you to understand and reproduce the issue
2. We will develop and test a fix
3. We will release the fix and credit you (unless you prefer to remain anonymous)
4. Public disclosure will occur after users have had time to update

## Security Best Practices

When using pyTMbot:

- Keep your installation updated to the latest supported version
- Store tokens and sensitive configuration in `pytmbot.yaml`
- Regularly review bot permissions and access logs

## Hall of Fame

We acknowledge security researchers who have helped improve our security:

- [Researcher Name] - [Brief description of contribution]

## Contact

For any further inquiries or assistance, please reach out to us through the project's main communication channels.