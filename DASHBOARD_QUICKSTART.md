# OpenClaw 3D Dashboard - Quick Start Guide

## TL;DR - Get Started in 30 Seconds

### 1. Open the Dashboard

```bash
# Option A: Direct file (local machine)
open file:///root/openclaw/dashboard_3d.html

# Option B: Via HTTP Server
cd /root/openclaw
python3 -m http.server 9000
# Then visit: http://localhost:9000/dashboard_3d.html

# Option C: Copy to web server
cp dashboard_3d.html /var/www/html/
# Visit: http://your-server/dashboard_3d.html
```

### 2. Verify Gateway is Running

```bash
# Check gateway status
curl -s http://localhost:9000/api/heartbeat/status | jq .

# Start gateway if needed
cd /root/openclaw && python3 gateway.py
```

### 3. Interact with Dashboard

- **Click agents**: Select to view details
- **Drag**: Rotate view with mouse
- **Scroll**: Zoom in/out
- **Buttons**: Restart, logs, config, sync

## What You'll See

### 3D View

```
        [CodeGen Pro 💻]
              /  \
            /      \
    [PM 🎯]          [SupabaseConnector 🗄️]
          \          /
            \      /
        [Pentest AI 🔒]
```

Each agent is a glowing sphere:

- **Green glow** = Active ✓
- **Yellow glow** = Busy ⊙
- **Red glow** = Offline ✗

Animated lines show message flow between agents.

### Panels

**Right Side**: Agent list showing status, model, type, active tasks
**Bottom Left**: Control buttons (restart, logs, config)
**Bottom Right**: Live stats (active agents, message rate, latency, uptime)

## Real-World Usage Examples

### Monitor During Development

```bash
# Terminal 1: Run gateway with logs
cd /root/openclaw && python3 gateway.py

# Terminal 2: Open dashboard
# Watch agents process requests in real-time
# View latency, throughput, which agents are active
```

### Check Agent Health

1. Open dashboard
2. Look at status colors
3. Click agent for detailed stats
4. Click "Restart Gateway" if needed

### Debug Routing Issues

1. Send test message to gateway
2. Watch dashboard to see which agent handles it
3. Click agent to verify type matches expectation
4. View logs to see reasoning

### Monitor Cost Usage

1. Check stats panel for message rate
2. View config for quota limits
3. Calculate: message_rate × agents_active
4. Verify within daily/monthly budgets

## Common Issues & Fixes

### Dashboard doesn't load

```bash
# 1. Check file exists
ls -la /root/openclaw/dashboard_3d.html

# 2. Check gateway running
curl http://localhost:9000/health

# 3. Check port number
# Default: 9000 (adjust in HTML if different)
```

### Agents all show gray/not updating

```bash
# 1. Check API endpoint
curl http://localhost:9000/api/heartbeat/status

# 2. Check cors headers
curl -i http://localhost:9000/api/heartbeat/status

# 3. Check gateway logs
tail -f /tmp/openclaw-gateway.log
```

### WebGL error (3D not rendering)

- Update GPU drivers
- Try different browser (Chrome, Firefox)
- Check "Enable WebGL" in browser settings
- Check console (F12) for exact error

## File Details

**Location**: `/root/openclaw/dashboard_3d.html`
**Size**: ~34 KB
**Build Process**: None! Single HTML file
**Dependencies**: Three.js (CDN) + Modern browser
**Browser Support**: Chrome 60+, Firefox 55+, Safari 11+, Edge 79+

## API Polling

Dashboard polls every 2 seconds:

```
GET /api/heartbeat/status
```

Response includes:

- Gateway status (online/offline)
- In-flight agents (which agents are processing)
- Agent status (active/busy/inactive)
- Runtime metrics

## Customization

### Change Update Frequency

```javascript
// In dashboard_3d.html, around line 950:
setInterval(pollStatus, 2000); // Change 2000 to your ms
```

### Change API Endpoint

```javascript
// In dashboard_3d.html, around line 920:
const response = await fetch("/api/heartbeat/status", {
  // Change to your endpoint
});
```

### Add/Remove Agents

```javascript
// In dashboard_3d.html, around line 620:
const agents = [
  // Add/remove from this array
  // Must match IDs in config.json
];
```

### Change Colors

```css
/* In dashboard_3d.html, around line 20: */
:root {
  --primary: #00ff88; /* Green */
  --secondary: #00ccff; /* Cyan */
  --accent: #ff6b6b; /* Red */
  --warning: #ffd93d; /* Yellow */
}
```

## Performance Tips

- **Smooth 60 FPS**: GPU-accelerated rendering
- **Low memory**: ~15-20 MB per session
- **Minimal network**: ~1 KB per API call every 2 seconds
- **Mobile friendly**: Responsive design

**Optimal viewing**: 1920x1080+ desktop or tablet

## Next Steps

1. ✓ Open dashboard in browser
2. ✓ Verify all 4 agents show
3. ✓ Click agents to verify details
4. ✓ Send test message to gateway
5. ✓ Watch agents process in real-time
6. ✓ View logs for verification
7. ✓ Bookmark for future reference!

## Keyboard Shortcuts

Currently mouse-based, but you can add:

- **R**: Restart gateway (auto-bind)
- **L**: View logs
- **C**: Show config
- **Space**: Reset camera view

To add, find the `window.addEventListener('keydown'...)` section.

## Pro Tips

- **Dragging frozen?** Make sure you're clicking on dark background, not UI panels
- **Zoom too far?** Scroll back or press Home to reset camera
- **Agent stuck?** Click "Force Sync" to trigger health check
- **Logs too much?** Close modal and reopen to refresh
- **Want demo mode?** Dashboard works offline with simulated data

## Integration with CI/CD

Embed dashboard in monitoring:

```html
<!-- In your monitoring dashboard: -->
<iframe
  src="http://your-server/dashboard_3d.html"
  width="100%"
  height="600px"
  frameborder="0"
></iframe>
```

## Support & Debugging

### Enable Debug Logging

```javascript
// Add to dashboard_3d.html console:
localStorage.debug = "*";
// Reload page for verbose logs
```

### Get Full API Response

```bash
curl -v http://localhost:9000/api/heartbeat/status | jq .
```

### Check Gateway Version

```bash
cd /root/openclaw && python3 -c "from gateway import app; print(app.title)"
```

---

**Happy monitoring!** 🚀

For detailed documentation, see `DASHBOARD_3D_README.md`
