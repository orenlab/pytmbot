# Nginx and Nginx Proxy Manager Configuration for InfluxDB Access

## Overview

This document provides a secure configuration guide for accessing InfluxDB through Nginx and Nginx Proxy Manager. It includes settings for both general access and isolated servers, ensuring a secure and efficient setup with comprehensive security best practices.

## 🔒 Security Requirements

### Prerequisites
- **SSL/TLS Certificate**: Required for production deployments
- **Firewall Configuration**: Proper firewall rules must be in place
- **Network Segmentation**: InfluxDB should be isolated from public networks
- **Authentication**: Always use strong authentication mechanisms

### Security Headers
All configurations must include essential security headers to protect against common attacks.

## Nginx Configuration

### Secure Nginx Configuration for InfluxDB

Create a new Nginx configuration file for InfluxDB:

```bash
sudo nano /etc/nginx/sites-available/influxdb
```

Add the following **secure** configuration:

```nginx
# Rate limiting configuration
limit_req_zone $binary_remote_addr zone=influxdb_limit:10m rate=10r/s;

server {
    listen 80;
    server_name influxdb.example.com;  # Replace with your domain name
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name influxdb.example.com;  # Replace with your domain name

    # SSL Configuration
    ssl_certificate /path/to/your/certificate.crt;
    ssl_certificate_key /path/to/your/private.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-SHA256:ECDHE-RSA-AES256-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';" always;

    # Hide Nginx version
    server_tokens off;

    # Rate limiting
    limit_req zone=influxdb_limit burst=20 nodelay;

    # IP whitelist (uncomment and configure for additional security)
    # allow 192.168.1.0/24;  # Your trusted network
    # allow 10.0.0.0/8;      # Your VPN network
    # deny all;

    location / {
        # Additional security checks
        if ($request_method !~ ^(GET|HEAD|POST|PUT|DELETE|OPTIONS)$ ) {
            return 405;
        }

        proxy_pass http://127.0.0.1:8086; # InfluxDB Port (use 127.0.0.1 instead of localhost)
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $server_name;

        # Security headers for proxied requests
        proxy_hide_header X-Powered-By;
        proxy_hide_header Server;

        # Timeouts
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;

        # Buffer settings
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;

        # Only enable CORS if absolutely necessary and restrict origins
        # add_header 'Access-Control-Allow-Origin' 'https://your-trusted-domain.com' always;
        # add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS' always;
        # add_header 'Access-Control-Allow-Headers' 'Content-Type, Authorization' always;
        # add_header 'Access-Control-Allow-Credentials' 'true' always;

        # Handle OPTIONS requests for CORS (if enabled)
        if ($request_method = 'OPTIONS') {
            add_header 'Access-Control-Max-Age' 3600;
            add_header 'Content-Type' 'text/plain; charset=utf-8';
            add_header 'Content-Length' 0;
            return 204;
        }
    }

    # Health check endpoint (optional)
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }

    # Block access to sensitive paths
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }

    # Logging
    access_log /var/log/nginx/influxdb.access.log;
    error_log /var/log/nginx/influxdb.error.log;
}
```

### Enable Configuration

Create a symbolic link to enable the configuration:

```bash
sudo ln -s /etc/nginx/sites-available/influxdb /etc/nginx/sites-enabled/
```

### Check Configuration

Test the Nginx configuration for errors:

```bash
sudo nginx -t
```

### Reload Nginx

Reload Nginx to apply the changes:

```bash
sudo systemctl reload nginx
```

## Nginx Proxy Manager Configuration

### Setting Up Secure Proxy Host

1. **Access Management Interface**:
   - Access the Nginx Proxy Manager interface at `https://<your_server_ip>:81` (use HTTPS if available)
   - **IMPORTANT**: Change default credentials immediately after first login

2. **Initial Security Setup**:
   - Default credentials (CHANGE IMMEDIATELY):
     - Email: admin@example.com
     - Password: changeme
   - Create a strong admin password
   - Enable two-factor authentication if available

3. **Create Secure Proxy Host**:
   - **Domain Names**: influxdb.example.com
   - **Scheme**: http
   - **Forward Hostname / IP**: 127.0.0.1 (use 127.0.0.1 instead of localhost)
   - **Forward Port**: 8086
   - **Block Common Exploits**: ✅ Enable
   - **Websockets Support**: Only if needed

4. **SSL Configuration**:
   - **SSL Certificate**: Use Let's Encrypt or upload your own certificate
   - **Force SSL**: ✅ Enable
   - **HTTP/2 Support**: ✅ Enable
   - **HSTS Enabled**: ✅ Enable
   - **HSTS Subdomains**: ✅ Enable if applicable

5. **Advanced Security Settings**:
   ```nginx
   # Add these to the Advanced tab
   
   # Security Headers
   add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
   add_header X-Frame-Options "DENY" always;
   add_header X-Content-Type-Options "nosniff" always;
   add_header X-XSS-Protection "1; mode=block" always;
   add_header Referrer-Policy "strict-origin-when-cross-origin" always;
   
   # Rate limiting
   limit_req_zone $binary_remote_addr zone=influxdb_npm:10m rate=10r/s;
   limit_req zone=influxdb_npm burst=20 nodelay;
   
   # IP whitelist (uncomment and configure for additional security)
   # allow 192.168.1.0/24;
   # allow 10.0.0.0/8;
   # deny all;
   ```

## Secure Configuration for Isolated Servers

For isolated or home servers, use this secure docker-compose configuration:

```yaml
services:
  influxdb:
    image: influxdb:2-alpine  # Use specific version and alpine for security
    container_name: influxdb
    restart: unless-stopped
    
    # Security: Only expose to localhost by default
    ports:
      - "127.0.0.1:8086:8086"  # Bind to localhost only
    
    environment:
      # Security: Set strong passwords
      - DOCKER_INFLUXDB_INIT_MODE=setup
      - DOCKER_INFLUXDB_INIT_USERNAME=admin
      - DOCKER_INFLUXDB_INIT_PASSWORD=your_strong_password_here
      - DOCKER_INFLUXDB_INIT_ORG=your_org
      - DOCKER_INFLUXDB_INIT_BUCKET=your_bucket
      - DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=your_secure_admin_token
    
    volumes:
      - influxdb_data:/var/lib/influxdb2
      - influxdb_config:/etc/influxdb2
    
    # Security: Run as non-root user
    user: "1000:1000"
    
    # Security: Read-only root filesystem
    read_only: true
    tmpfs:
      - /tmp
    
    # Security: Limit resources
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 1G
        reservations:
          cpus: '0.5'
          memory: 512M
    
    # Security: Disable unnecessary capabilities
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - DAC_OVERRIDE
      - SETGID
      - SETUID
    
    # Security: No new privileges
    security_opt:
      - no-new-privileges:true

volumes:
  influxdb_data:
    driver: local
  influxdb_config:
    driver: local

# Security: Use custom network
networks:
  default:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

## 🔒 Security Best Practices

### 1. Network Security
- **Firewall Rules**: Only allow necessary ports (443 for HTTPS, 22 for SSH)
- **Network Segmentation**: Place InfluxDB in a separate network segment
- **VPN Access**: Use VPN for remote access instead of exposing to internet

### 2. Authentication & Authorization
- **Strong Passwords**: Use complex passwords with minimum 12 characters
- **Token-based Authentication**: Implement InfluxDB tokens for API access
- **Role-based Access**: Use InfluxDB's built-in RBAC features
- **Regular Rotation**: Rotate passwords and tokens regularly

### 3. SSL/TLS Configuration
- **Certificate Management**: Use Let's Encrypt or trusted CA certificates
- **Perfect Forward Secrecy**: Enable PFS with appropriate cipher suites
- **HSTS**: Implement HTTP Strict Transport Security
- **TLS 1.3**: Use latest TLS version when possible

### 4. Monitoring & Logging
- **Access Logs**: Monitor all access attempts
- **Error Logs**: Review error logs regularly
- **Rate Limiting**: Implement rate limiting to prevent abuse
- **Alerting**: Set up alerts for suspicious activities

### 5. Container Security
- **Non-root User**: Run containers as non-root user
- **Read-only Filesystem**: Use read-only root filesystem
- **Resource Limits**: Set appropriate resource limits
- **Security Scanning**: Regularly scan container images for vulnerabilities

### 6. Backup & Recovery
- **Regular Backups**: Implement automated backup strategy
- **Encrypted Backups**: Encrypt backup data
- **Recovery Testing**: Test recovery procedures regularly
- **Offsite Storage**: Store backups in separate location

## 🚨 Security Warnings

### ⚠️ Issues in Original Configuration

1. **No SSL/TLS**: HTTP-only configuration is insecure
2. **Open CORS**: `Access-Control-Allow-Origin: *` allows any origin
3. **No Rate Limiting**: Vulnerable to DDoS attacks
4. **No Authentication**: No access control mentioned
5. **Public Binding**: Binding to all interfaces (0.0.0.0) is dangerous
6. **No Security Headers**: Missing essential security headers
7. **Default Credentials**: Using default credentials is a security risk

### ✅ Security Improvements Made

1. **HTTPS Enforced**: All traffic redirected to HTTPS
2. **Restricted CORS**: CORS disabled by default, restricted when needed
3. **Rate Limiting**: Implemented to prevent abuse
4. **Security Headers**: Comprehensive security headers added
5. **Localhost Binding**: Services bound to localhost only
6. **Strong Authentication**: Proper authentication mechanisms
7. **Container Security**: Multiple container security measures

## Conclusion

This secure configuration provides robust protection for InfluxDB access through Nginx and Nginx Proxy Manager. Always follow security best practices and regularly review and update your configurations to maintain security posture.

For production environments, consider additional security measures such as:
- Web Application Firewall (WAF)
- DDoS protection
- Security auditing
- Penetration testing
- Compliance certifications

Remember: Security is an ongoing process, not a one-time setup.Д