# Proxy Setup for Reddit Access from EC2

Reddit blocks AWS/cloud IP addresses. This proxy setup routes Reddit requests through your local machine's residential IP.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         YOUR LOCAL MAC                                   │
│                                                                          │
│  ┌──────────────────┐         ┌──────────────────┐                      │
│  │ simple_proxy.py  │◄────────│   SSH Tunnel     │                      │
│  │ (port 18888)     │         │ (reverse -R)     │                      │
│  │                  │         │                  │                      │
│  │ HTTP CONNECT     │         │ Listens on EC2   │                      │
│  │ proxy server     │         │ port 18888       │                      │
│  └────────┬─────────┘         └────────▲─────────┘                      │
│           │                            │                                 │
│           ▼                            │                                 │
│  ┌──────────────────┐                  │                                 │
│  │    Internet      │                  │                                 │
│  │  (Reddit, etc)   │                  │                                 │
│  │                  │                  │                                 │
│  │ Your home IP     │                  │                                 │
│  └──────────────────┘                  │                                 │
└────────────────────────────────────────┼────────────────────────────────┘
                                         │
                                         │ SSH Connection
                                         │
┌────────────────────────────────────────┼────────────────────────────────┐
│                         AWS EC2        │                                 │
│                                        │                                 │
│  ┌──────────────────┐         ┌────────┴─────────┐                      │
│  │  Docker crawler  │────────►│  socat forwarder │                      │
│  │                  │         │                  │                      │
│  │ PROXY_URL=       │         │ 172.18.0.1:18889 │                      │
│  │ 172.18.0.1:18889 │         │       ▼          │                      │
│  └──────────────────┘         │ 127.0.0.1:18888  │                      │
│                               │ (SSH tunnel end) │                      │
│                               └──────────────────┘                      │
└─────────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Local Proxy Server (`/tmp/simple_proxy.py`)

A simple HTTP CONNECT proxy that:
- Listens on `127.0.0.1:18888`
- Handles HTTP CONNECT requests for HTTPS tunneling
- Forwards traffic to target servers (Reddit)
- Uses your residential IP (not blocked)

### 2. SSH Reverse Tunnel

Creates a tunnel from EC2 back to your local machine:
```bash
ssh -R 18888:127.0.0.1:18888 ec2-user@<EC2_IP>
```
- `-R 18888:127.0.0.1:18888` - EC2 port 18888 forwards to local port 18888
- `-N` - No remote command (tunnel only)
- `-f` - Run in background

### 3. Socat Forwarder (on EC2)

Docker containers can't access `127.0.0.1` on the host. Socat bridges the gap:
```bash
socat TCP-LISTEN:18889,bind=172.18.0.1,fork,reuseaddr TCP:127.0.0.1:18888
```
- Listens on Docker network gateway (`172.18.0.1:18889`)
- Forwards to SSH tunnel endpoint (`127.0.0.1:18888`)

## Data Flow

1. **Crawler** requests `old.reddit.com`
2. **Crawler** sends to proxy `172.18.0.1:18889`
3. **Socat** forwards to `127.0.0.1:18888` (SSH tunnel)
4. **SSH tunnel** sends to your Mac's port `18888`
5. **Local proxy** fetches Reddit using your home IP
6. **Response** flows back the same path

## Setup Instructions

### Start Local Proxy

```bash
# Create the proxy script
cat > /tmp/simple_proxy.py << 'EOF'
#!/usr/bin/env python3
"""Simple HTTP CONNECT proxy for tunneling HTTPS requests."""
import socket
import threading
import select

def handle_client(client_socket):
    try:
        request = client_socket.recv(4096).decode('utf-8', errors='ignore')
        if not request:
            return

        first_line = request.split('\n')[0]
        if not first_line.startswith('CONNECT'):
            client_socket.close()
            return

        parts = first_line.split()
        if len(parts) < 2:
            return
        host_port = parts[1]
        if ':' in host_port:
            host, port = host_port.split(':')
            port = int(port)
        else:
            host, port = host_port, 443

        remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        remote.settimeout(10)
        try:
            remote.connect((host, port))
        except:
            client_socket.send(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
            return

        client_socket.send(b'HTTP/1.1 200 Connection Established\r\n\r\n')

        remote.setblocking(False)
        client_socket.setblocking(False)

        while True:
            r, _, _ = select.select([client_socket, remote], [], [], 30)
            if not r:
                break
            for sock in r:
                try:
                    data = sock.recv(8192)
                    if not data:
                        return
                    if sock is client_socket:
                        remote.send(data)
                    else:
                        client_socket.send(data)
                except:
                    return
    except:
        pass
    finally:
        try:
            client_socket.close()
        except:
            pass

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('127.0.0.1', 18888))
server.listen(10)
print('HTTP CONNECT proxy running on 127.0.0.1:18888', flush=True)

while True:
    client, _ = server.accept()
    threading.Thread(target=handle_client, args=(client,), daemon=True).start()
EOF

# Run in background
python3 /tmp/simple_proxy.py &
```

### Create SSH Tunnel

```bash
# Replace <EC2_IP> with your EC2 public IP
ssh -i ~/.ssh/crypto-sentiment-key.pem \
    -o StrictHostKeyChecking=no \
    -o ServerAliveInterval=30 \
    -R 18888:127.0.0.1:18888 \
    -N -f \
    ec2-user@<EC2_IP>
```

### Start Socat on EC2

```bash
ssh -i ~/.ssh/crypto-sentiment-key.pem ec2-user@<EC2_IP> \
    "nohup socat TCP-LISTEN:18889,bind=172.18.0.1,fork,reuseaddr TCP:127.0.0.1:18888 > /tmp/socat.log 2>&1 &"
```

## Quick Restart Script

Save this as `start_proxy.sh`:

```bash
#!/bin/bash
EC2_IP="34.229.95.72"  # Update with your EC2 IP
KEY="~/.ssh/crypto-sentiment-key.pem"

echo "Starting local proxy..."
pkill -f "simple_proxy.py" 2>/dev/null
python3 /tmp/simple_proxy.py &
sleep 2

echo "Creating SSH tunnel..."
pkill -f "ssh.*18888.*$EC2_IP" 2>/dev/null
ssh -i $KEY -o StrictHostKeyChecking=no -o ServerAliveInterval=30 \
    -R 18888:127.0.0.1:18888 -N -f ec2-user@$EC2_IP

echo "Starting socat on EC2..."
ssh -i $KEY ec2-user@$EC2_IP \
    "pkill -f 'socat.*18889' 2>/dev/null; nohup socat TCP-LISTEN:18889,bind=172.18.0.1,fork,reuseaddr TCP:127.0.0.1:18888 > /tmp/socat.log 2>&1 &"

echo "Proxy setup complete!"
```

## Verification

### Test Local Proxy
```bash
curl -x http://127.0.0.1:18888 https://httpbin.org/ip
# Should show your home IP
```

### Test from EC2
```bash
ssh -i ~/.ssh/crypto-sentiment-key.pem ec2-user@<EC2_IP> \
    "curl -x http://127.0.0.1:18888 https://httpbin.org/ip"
# Should show your home IP (not EC2 IP)
```

### Test Reddit Access
```bash
ssh -i ~/.ssh/crypto-sentiment-key.pem ec2-user@<EC2_IP> \
    "curl -sL -x http://172.18.0.1:18889 'https://old.reddit.com/r/bitcoin/new/' -H 'User-Agent: Mozilla/5.0' | grep -c 'data-timestamp'"
# Should return a number > 0
```

## Troubleshooting

### Proxy not responding
```bash
# Check if proxy is running
ps aux | grep simple_proxy

# Restart proxy
pkill -f simple_proxy.py
python3 /tmp/simple_proxy.py &
```

### SSH tunnel disconnected
```bash
# Check tunnel
ps aux | grep "ssh.*18888"

# Recreate tunnel
ssh -i ~/.ssh/crypto-sentiment-key.pem -R 18888:127.0.0.1:18888 -N -f ec2-user@<EC2_IP>
```

### Socat not running on EC2
```bash
ssh -i ~/.ssh/crypto-sentiment-key.pem ec2-user@<EC2_IP> "ps aux | grep socat"

# Restart socat
ssh -i ~/.ssh/crypto-sentiment-key.pem ec2-user@<EC2_IP> \
    "nohup socat TCP-LISTEN:18889,bind=172.18.0.1,fork,reuseaddr TCP:127.0.0.1:18888 &"
```

## Why Reddit Blocks Cloud IPs

| IP Type | Example | Reddit Access |
|---------|---------|---------------|
| Residential | Home ISP IP | Allowed |
| AWS EC2 | 34.x.x.x, 54.x.x.x | Blocked |
| GCP | 35.x.x.x | Blocked |
| Azure | Various | Blocked |

Reddit maintains blocklists of datacenter IP ranges to prevent scraping and bot activity.
