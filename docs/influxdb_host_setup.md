# Nginx and Nginx Proxy Manager Configuration for InfluxDB Access

## Overview

This document provides a configuration guide for accessing InfluxDB through Nginx and Nginx Proxy Manager. It includes
settings for both general access and isolated servers, ensuring a secure and efficient setup.

## Nginx Configuration

### Nginx Configuration for InfluxDB

Create a new Nginx configuration file for InfluxDB:

```bash
sudo nano /etc/nginx/sites-available/influxdb
```

Add the following configuration:

```bash
server {
    listen 80;
    server_name influxdb.example.com;  # Replace with your domain name

    location / {
        proxy_pass http://localhost:8086; # InfluxDB Port
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Enable CORS if necessary
        add_header 'Access-Control-Allow-Origin' '*';
        add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS';
        add_header 'Access-Control-Allow-Headers' 'Content-Type, Authorization';
    }
}
```

Enable Configuration

Create a symbolic link to enable the configuration:

```bash
sudo ln -s /etc/nginx/sites-available/influxdb /etc/nginx/sites-enabled/
```

Check Configuration

Test the Nginx configuration for errors:

```bash
sudo nginx -t
```

Reload Nginx

Reload Nginx to apply the changes:

```bash
sudo systemctl restart nginx
```

### Nginx Proxy Manager Configuration

Setting Up Proxy Host

1. Access the Nginx Proxy Manager interface at http://<your_server_ip>:81.
2. Log in using the default credentials:
    - Email: admin@example.com
    - Password: changeme
3. Create a new Proxy Host:
    - Domain Names: influxdb.example.com # Replace with your domain name
    - Scheme: http
    - Forward Hostname / IP: localhost
    - Forward Port: 8086
    - Ensure the correct SSL settings are applied if using SSL certificates.
4. Save the settings.

### Configuration for Isolated Servers

For isolated or home servers, you can connect directly to the InfluxDB container. Use the following configuration in
your docker-compose.yml file to expose the InfluxDB port:

```yaml
version: '3'

services:
  influxdb:
    image: influxdb:latest
    container_name: influxdb
    restart: unless-stopped
    ports:
      - "8086:8086" # Exposing InfluxDB Port
    volumes:
      - influxdb_data:/var/lib/influxdb
```

With this configuration, you can access InfluxDB directly at http://localhost:8086 from within the home network. Ensure
appropriate firewall rules are set to allow traffic on port 8086.

### Conclusion

You can now access InfluxDB through Nginx and Nginx Proxy Manager at http://influxdb.example.com. This setup supports
both general and isolated server access, maintaining security and efficiency in your network.
