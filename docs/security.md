# Security Practices

At **pyTMbot**, security is a top priority. This document outlines the security measures implemented to protect the bot
and its users, in accordance with industry best practices.

## 🔐 Token Management

- **Token Storage:** All sensitive tokens (e.g., Telegram Bot API tokens, Docker access tokens) are stored in a
  configuration file (`pytmbot.yaml`).
- **Access Control:** The `pytmbot.yaml` file is configured to be readable only by the `root` user, ensuring that no
  unauthorized access can occur.
- **User Isolation:** The configuration file and environment are isolated within the container, limiting potential
  access points.

## 🛡 Docker Container Security

### Root User Access

The bot runs within a Docker container as the `root` user. This is necessary because the bot requires access to the
Docker socket (`/var/run/docker.sock`) to manage and retrieve information about Docker containers. Running as `root`
ensures:

- **Full Access to Docker Services:** Certain Docker operations (like managing containers and fetching container logs)
  are not permitted without `root` privileges. Running the container as `root` allows the bot to interact with the
  Docker API seamlessly.

### Best Practices for Running Containers

- **Minimal Image Size:** The Docker image is kept minimal, ensuring that only essential libraries and dependencies are
  installed, reducing the attack surface.
- **Container Updates:** The bot regularly checks for image and library updates. Users are encouraged to pull the latest
  image and ensure the bot is up-to-date with the latest security patches.

## 🔒 Two-Factor Authentication (TOTP)

- **TOTP Integration:** The bot includes two-factor authentication (2FA) using time-based one-time passwords (TOTP).
  This feature adds an extra layer of security for critical operations like managing Docker containers.
- **QR Code for 2FA:** A QR code is generated for setting up TOTP, ensuring easy integration with authentication apps
  like Google Authenticator or Authy.

## 👥 Access Control

- **Role-Based Access:** Access to bot commands and functionality is controlled by user roles. Only superusers (
  root-level) can manage Docker containers or access sensitive operations.
- **Admin Whitelist:** Admins are whitelisted in the `settings` file to ensure that only authorized users can access
  critical operations, including QR code generation for 2FA setup.

## 📊 Audit Logs

- **Logging:** The bot leverages detailed logging to track user activity and access to critical resources. Logs include:
    - User actions (e.g., starting/stopping containers)
    - Access attempts
    - Errors and warnings

Logs can be accessed through the Docker log aggregator, ensuring visibility and traceability of operations.

## 📈 Continuous Monitoring and Updates

- **Automatic Update Checks:** The bot regularly checks for new releases, bug fixes, and security patches. Users are
  notified via a bot command (`/check_bot_updates`) to stay current with the latest version.

## 🚧 Future Enhancements

- **Non-Root Container Execution:** We are exploring ways to safely run the bot with limited privileges while retaining
  access to the Docker socket.


