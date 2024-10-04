# pyTMbot Installation Script

This script provides an easy way to install, manage, and uninstall the pyTMbot either inside a Docker container or
locally on your system. It also includes support for setting up a Python virtual environment for local installations.

## Requirements

- **Root privileges**: The script requires `sudo` or root access to install necessary system packages.
- **Supported Operating Systems**:
    - Ubuntu/Debian
    - CentOS/RHEL/Fedora
    - Arch Linux

## Usage

### Preparing the Script

Running the Script

To get the latest version of the script and run it:

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/orenlab/pytmbot/refs/heads/master/install.sh)"
```

### Installation Options

When running the script, you will be prompted to choose one of the following options:

1. Docker installation: Runs pyTMbot inside a Docker container for easy management and isolation.
   • This option manages pyTMbot within a Docker environment, reducing dependency conflicts and offering process
   isolation.
2. Local installation: Installs pyTMbot directly on your system.
   • The script installs `Python 3.12` (if necessary), sets up a virtual environment, and installs all required
   dependencies.
3. Uninstall pyTMbot: Completely removes the bot and its files from your system.
   • Deletes all files related to pyTMbot and cleans up the environment.

### Logs

All output is logged to `/var/log/pytmbot_install.log`. If any issues arise, check this log for detailed information.

### Troubleshooting

- `Unsupported OS`: If your OS is unsupported by the script, you’ll need to manually install Python 3.12.
- `Permission Denied`: Ensure you are running the script with sudo or as root.
- `Docker Issues`: Confirm Docker is installed and properly configured on your system, as the script does not handle
  Docker installation.

## Uninstallation

### Local Uninstallation

To completely remove pyTMbot from a local installation:

```bash
sudo ./install.sh
```

Then, choose option `3` for uninstallation.

### Docker Uninstallation

To remove pyTMbot from a Docker container:

```bash
sudo docker stop pytmbot
sudo docker rm pytmbot
sudo docker rmi orenlab/pytmbot
```

License

This script is open-source and licensed under the MIT License.