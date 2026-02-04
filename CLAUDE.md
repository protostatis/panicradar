# Claude Code Reminders

## IMPORTANT: Proxy Server for Reddit Access

Reddit blocks AWS/EC2 IP addresses. The crawler requires a proxy tunnel through the local Mac.

### Before deploying or restarting the crawler on EC2:

1. **Start local proxy** (if not running):
   ```bash
   python3 ~/.local/bin/simple_proxy.py &
   # Or check: ps aux | grep simple_proxy
   ```

2. **Create SSH tunnel** (if not running):
   ```bash
   ssh -i ~/.ssh/panicradar-ec2.pem -R 18888:127.0.0.1:18888 -N -f ec2-user@23.20.148.59
   # Check: ps aux | grep "ssh.*18888"
   ```

3. **Start socat on EC2** (if not running):
   ```bash
   ssh -i ~/.ssh/panicradar-ec2.pem ec2-user@23.20.148.59 \
     "nohup socat TCP-LISTEN:18889,bind=172.18.0.1,fork,reuseaddr TCP:127.0.0.1:18888 &"
   ```

4. **Verify proxy works**:
   ```bash
   ssh -i ~/.ssh/panicradar-ec2.pem ec2-user@23.20.148.59 \
     "curl -x http://172.18.0.1:18889 https://httpbin.org/ip"
   # Should show local Mac IP (24.x.x.x), NOT EC2 IP
   ```

### Crawler must use:
- `PROXY_URL=http://172.18.0.1:18889`
- This is now the default in docker-compose.yml

### If crawler shows "No fresh posts" or 403 errors:
- Proxy tunnel is likely down
- Run steps 1-4 above to restore

### Full documentation:
See `docs/PROXY_SETUP.md`
