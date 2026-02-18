# OpenClaw 3D Agent Dashboard

An impressive real-time visualization dashboard for the OpenClaw multi-agent platform using Three.js.

## Features

### 3D Visualization

- **4 Agent Nodes**: Rendered as glowing 3D spheres with real-time status
  - Cybershield PM (🎯) - Project Coordinator
  - CodeGen Pro (💻) - Developer Agent
  - Pentest AI (🔒) - Security Specialist
  - SupabaseConnector (🗄️) - Database Specialist

- **Status Indicators**: Color-coded by agent state
  - GREEN (#00ff88): Active and responding
  - YELLOW (#ffd93d): Busy processing
  - RED (#ff6b6b): Inactive or offline

- **Message Flow**: Animated lines showing agent-to-agent communication
  - Pulsing connections when agents exchange messages
  - Hub-and-spoke topology centered on PM agent

### Interactive Controls

- **Click Agents**: Select an agent to view detailed info (logs, config, metrics)
- **Drag to Rotate**: Mouse drag rotates the 3D view smoothly
- **Scroll to Zoom**: Mouse wheel zooms in/out (20-100 unit range)
- **Real-time Updates**: Auto-polls API every 2 seconds for live status

### UI Panels

#### Agent Network Panel (Top Right)

- Lists all 4 agents with current status
- Shows agent type and active task count
- Click to select and view details
- Scrollable if expanded

#### Control Panel (Bottom Left)

- **Restart Gateway**: Trigger gateway restart (production: HTTP call)
- **View Logs**: See real-time gateway and agent logs
- **Config**: Display current configuration and settings
- **Force Sync**: Trigger health check and agent recovery

#### System Stats Panel (Bottom Right)

- Active Agents count (0-4)
- Message rate (messages/second)
- API Latency (milliseconds)
- Uptime (minutes)
- Last update timestamp

### Modals

- **Logs Modal**: Shows gateway and agent initialization logs
- **Config Modal**: Displays agent models, routing config, quotas

## Installation

1. The dashboard is a standalone HTML file - no build process needed!
2. File location: `/root/openclaw/dashboard_3d.html`
3. No external dependencies except Three.js (loaded from CDN)

## Running the Dashboard

### Option 1: Local Development Server

```bash
# Start the gateway (if not already running)
cd /root/openclaw
python3 gateway.py &

# Open in browser
# Navigate to: file:///root/openclaw/dashboard_3d.html
# OR
# Start local HTTP server:
python3 -m http.server 9000
# Then visit: http://localhost:9000/dashboard_3d.html
```

### Option 2: With Existing Gateway

If gateway is running on `localhost:8000` or accessible endpoint:

```bash
# The dashboard auto-discovers the API at /api/heartbeat/status
# Simply open the HTML file in any modern browser
```

### Option 3: Production Deployment

```bash
# Copy to web root
cp /root/openclaw/dashboard_3d.html /var/www/html/

# Access via: https://your-domain.com/dashboard_3d.html
```

## Browser Requirements

- Modern browser with WebGL support (Chrome, Firefox, Safari, Edge)
- JavaScript enabled
- Minimum viewport: 640x480 (optimized for 1920x1080)

## API Endpoints Used

The dashboard polls the following endpoint every 2 seconds:

```
GET /api/heartbeat/status
```

Response format:

```json
{
  "success": true,
  "status": "online|offline",
  "monitor": {
    /* heartbeat monitor status */
  },
  "in_flight_agents": [
    {
      "agent_id": "project_manager|coder_agent|hacker_agent|database_agent",
      "task_id": "task-uuid",
      "status": "active|busy|inactive",
      "running_for_ms": 5000,
      "idle_for_ms": 1000
    }
  ],
  "timestamp": "2026-02-18T20:30:00.000Z"
}
```

## Configuration

### Customizing Agent Display

Edit the `agents` array in the HTML file (around line 600):

```javascript
const agents = [
  {
    id: "agent_id_from_config",
    name: "Display Name",
    emoji: "🎯",
    position: new THREE.Vector3(x, y, z),
    color: 0x00ff88, // Hex color code
    status: "active",
    type: "coordinator",
  },
  // ... more agents
];
```

### Customizing Colors

Update CSS variables at the top of the `<style>` block:

```css
:root {
  --primary: #00ff88; /* Green highlight */
  --secondary: #00ccff; /* Cyan highlight */
  --accent: #ff6b6b; /* Red for errors */
  --warning: #ffd93d; /* Yellow for busy */
  --dark-bg: #0a0e27; /* Background */
  --dark-card: #16213e; /* Panel cards */
}
```

### API Endpoint Configuration

Change the polling endpoint by editing the `pollStatus()` function:

```javascript
async function pollStatus() {
  const response = await fetch("/api/heartbeat/status", {
    // <-- Change here
    headers: { "Content-Type": "application/json" },
  });
  // ...
}
```

## Performance Notes

- **Latency**: Dashboard updates every 2 seconds (configurable)
- **GPU Acceleration**: Uses WebGL for smooth 60 FPS rendering
- **Memory**: ~15-20 MB for typical session
- **Network**: ~1 KB per API call (very lightweight)

## Troubleshooting

### Dashboard loads but shows error in console

1. Check that gateway is running: `curl http://localhost:9000/api/heartbeat/status`
2. Check CORS headers: Dashboard should show 200 OK responses
3. Verify API endpoint is correct in `pollStatus()` function

### Agents not updating status

1. Verify heartbeat monitor is running: `grep "heartbeat_monitor" gateway.py`
2. Check that agents are responding to health checks
3. Look at gateway logs: `tail -f /tmp/openclaw-gateway.log`

### 3D rendering not working

1. Enable WebGL in browser settings
2. Check GPU drivers are up to date
3. Try a different browser (Chrome/Firefox work best)
4. Open browser console (F12) and look for WebGL errors

### API calls returning 401

1. Check auth middleware webhook exemptions
2. Verify token/credentials if gateway requires auth
3. Ensure dashboard URL is whitelisted

## Architecture

### Three.js Scene

- **Scene**: 3D world with fog and gradient background
- **Camera**: Perspective view with subtle animation
- **Lighting**:
  - Ambient light (40% brightness)
  - Point light #1: Green (#00ff88) from top-right
  - Point light #2: Cyan (#00ccff) from bottom-left
- **Shadows**: Enabled for realistic depth

### Agent Rendering

Each agent consists of:

1. **Icosahedron Mesh**: Main agent sphere
2. **Glow Aura**: Semi-transparent outer sphere
3. **Status Light**: Small colored indicator sphere
4. **Auto-rotation**: Subtle spinning effect
5. **Pulse Animation**: Size variation over time

### Message Flow

- **Hub-and-spoke**: All agents connect to PM agent
- **Dynamic Lines**: THREE.BufferGeometry lines with animation
- **Opacity Animation**: Brightness indicates activity
- **Dash Animation**: Moving dashes show data flow direction

### Interaction System

- **Raycasting**: Detects clicks on agent spheres
- **Mouse Dragging**: Rotates entire scene
- **Mouse Wheel**: Zoom camera in/out
- **Selection**: Highlights selected agent in UI panel

## Development

### Adding New Features

#### Adding a Control Button

```javascript
// In control-panel HTML:
<button onclick="myFunction()">My Button</button>;

// Add function:
function myFunction() {
  console.log("Button clicked!");
  // Call API, update UI, etc.
}
```

#### Adding New Agent

```javascript
const agents = [
  // ... existing agents
  {
    id: "new_agent",
    name: "New Agent",
    emoji: "🤖",
    position: new THREE.Vector3(20, 0, 0),
    color: 0x9933ff,
    status: "active",
    type: "specialist",
  },
];
```

#### Changing Polling Interval

```javascript
// Current: 2000ms (2 seconds)
setInterval(pollStatus, 2000); // <-- Change this value
```

## Performance Optimization

For deployment on slower devices:

1. **Reduce geometry detail**:

   ```javascript
   const geometry = new THREE.IcosahedronGeometry(2, 2); // Reduce from 4
   ```

2. **Disable shadows**:

   ```javascript
   renderer.shadowMap.enabled = false;
   ```

3. **Lower update frequency**:

   ```javascript
   setInterval(pollStatus, 5000); // Change from 2000ms
   ```

4. **Reduce particle effects**:
   ```javascript
   // Comment out or simplify animation loops
   ```

## License

Part of the OpenClaw project. See main repository for license details.

## Support

For issues or feature requests:

1. Check gateway logs: `tail -f /tmp/openclaw-gateway.log`
2. Verify API responses: `curl http://localhost:9000/api/heartbeat/status`
3. Open browser console (F12) for JavaScript errors
4. Check gateway configuration: `cat /root/openclaw/config.json`

---

**Created**: 2026-02-18
**Version**: 1.0.0
**Author**: Claude Code (Anthropic)
**Status**: Production Ready
