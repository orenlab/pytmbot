# Security Policy

## Supported Versions

The following versions of pyTMbot are actively supported:

| Version | Supported          | End of Life |
|---------|--------------------|-------------|
| 0.2.2   | :white_check_mark: | TBD         |
| 0.2.1   | :white_check_mark: | 2025-09-30  |
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

## Types of Security Issues We Address

We take the following types of security vulnerabilities seriously:

- **Authentication and authorization bypasses:** Issues that allow unauthorized access to bot functionality or data
- **Code injection vulnerabilities:** Including command injection, script injection, or any form of malicious code
  execution
- **Sensitive data exposure:** Unintended disclosure of tokens, user data, or configuration information
- **Denial of service vulnerabilities:** Issues that could cause the bot to crash, hang, or consume excessive resources
- **Dependencies with known security issues:** Vulnerabilities in third-party libraries used by pyTMbot
- **Configuration security flaws:** Misconfigurations that could lead to security breaches
- **Input validation issues:** Problems with handling user input that could lead to security vulnerabilities

## Security Best Practices

When using pyTMbot, follow these security guidelines:

### Configuration Security

- **File permissions:** Set restrictive permissions on `pytmbot.yaml` (recommended: `600` or `640`)
  ```bash
  chmod 600 pytmbot.yaml
  ```
- **Storage location:** Store configuration files outside of web-accessible directories
- **Backup security:** Ensure configuration backups are encrypted and stored securely
- **Access control:** Limit access to configuration files to only necessary users and processes

### Token and Secrets Management

- Store all tokens and sensitive configuration exclusively in `pytmbot.yaml`
- Never commit configuration files containing real tokens to version control
- Use separate configuration files for different environments (development, staging, production)
- Regularly rotate bot tokens and API keys
- Monitor for accidental token exposure in logs or error messages

### System Security

- **Keep updated:** Regularly pull the latest Docker image version from the registry
  ```bash
  docker pull pytmbot:latest
  docker-compose pull  # if using docker-compose
  ```
- **Image security:** Use only official images from trusted Docker registries
- **Container scanning:** Periodically scan Docker images for vulnerabilities:
  ```bash
  docker scout cves pytmbot:latest  # Docker Scout
  # or use trivy, clair, or similar container security tools
  ```
- **Container isolation:** Run containers with minimal privileges and restricted capabilities
- **Network security:** Use Docker networks to isolate containers and restrict access to only necessary ports

### Monitoring and Logging

- Regularly review bot permissions and access logs
- Monitor for unusual activity patterns
- Set up alerts for authentication failures or suspicious behavior
- Ensure logs don't contain sensitive information like tokens or user data

### Deployment Security

- Use dedicated user accounts with minimal privileges for running containers
- **Volume security:** Mount configuration files as read-only volumes
- **Container hardening:** Run containers as non-root user and drop unnecessary capabilities
- **Docker daemon security:** Ensure Docker daemon is properly secured and updated
- **Registry security:** Use trusted Docker registries and verify image signatures when available
- **Container runtime:** Consider using security-focused container runtimes
- Regular security audits of the container environment and host system

## Contact

For any further inquiries or assistance, please reach out to us through the project's main communication channels.