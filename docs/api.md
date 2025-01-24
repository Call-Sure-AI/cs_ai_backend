# AI Backend API Documentation

## Base URL
```
https://your-domain.com/api/v1
```

## Authentication
All endpoints require authentication using an API key in the header:
```
Authorization: Bearer YOUR_API_KEY
```

## Endpoints

### AI Endpoints

#### Chat Completion
```http
POST /ai/chat
```
Request chat completion from various AI models (GPT, Claude, Llama).

**Request Body:**
```json
{
    "content": "Hello, how are you?",
    "role": "user",
    "provider": "gpt",
    "context": {
        "location": "New York"
    },
    "metadata": {
        "client_version": "1.0.0",
        "platform": "web"
    }
}
```

**Response:**
```json
{
    "message_id": "uuid",
    "content": "I'm doing well! How can I help you today?",
    "role": "assistant",
    "timestamp": "2024-01-25T10:30:00Z"
}
```

### Voice Endpoints

#### Text-to-Speech (TTS)
```http
POST /voice/tts
```
Convert text to speech using various providers.

**Request Body:**
```json
{
    "text": "Hello, this is a test message",
    "provider": "eleven_labs",
    "voice_id": "voice_id",
    "style": "natural",
    "speed": 1.0,
    "format": "mp3"
}
```

#### Speech-to-Text (STT)
```http
POST /voice/stt
```
Convert speech to text using various providers.

**Request Body:**
```json
{
    "audio_url": "https://example.com/audio.mp3",
    "provider": "deepgram",
    "language": "en",
    "diarization": true,
    "config": {
        "punctuate": true,
        "profanity_filter": false
    }
}
```

### WebRTC Endpoints

#### Signaling Connection
```http
WebSocket: /webrtc/signal/{peer_id}/{company_api_key}
```
Establish WebRTC signaling connection for real-time communication.

**Connection Parameters:**
- `peer_id`: Unique identifier for the connecting peer
- `company_api_key`: Company's API key for authentication

**Message Types:**

1. Signal Messages
```json
{
    "type": "signal",
    "to_peer": "target-peer-id",
    "data": {
        "type": "offer|answer|candidate",
        "sdp": "session-description",
        "candidate": {
            "candidate": "candidate-string",
            "sdpMLineIndex": 0,
            "sdpMid": "0"
        }
    }
}
```

2. Stream Messages
```json
{
    "type": "message",
    "data": {
        "content": "your-message-content",
        "timestamp": "2024-01-25T10:30:00Z"
    }
}
```

3. Heartbeat Messages
```json
{
    "type": "ping"
}
```

**Response Messages:**
```json
{
    "type": "pong"
}
```

#### Get Active Peers
```http
GET /webrtc/peers/{company_api_key}
```
Get list of active WebRTC peers for a company.

**Response:**
```json
{
    "company_id": "company-123",
    "active_peers": [
        "peer-1",
        "peer-2"
    ]
}
```

#### WebRTC Statistics
```http
GET /webrtc/stats
```
Get system-wide WebRTC statistics.

**Response:**
```json
{
    "total_peers": 10,
    "total_companies": 2,
    "peers_by_company": {
        "company-1": 6,
        "company-2": 4
    },
    "peer_details": [
        {
            "peer_id": "peer-123",
            "company_id": "company-1",
            "connected_at": "2024-01-25T10:30:00Z",
            "last_activity": "2024-01-25T10:35:00Z",
            "message_count": 50,
            "is_connected": true
        }
    ]
}
```

#### Health Check
```http
WebSocket: /webrtc/health
```
Check WebRTC service health.

**Response:**
```json
{
    "status": "healthy",
    "timestamp": "2024-01-25T10:30:00Z"
}
```

### Error Codes

#### HTTP Status Codes
- `200`: Success
- `400`: Bad Request
- `401`: Unauthorized
- `403`: Forbidden
- `404`: Not Found
- `429`: Too Many Requests
- `500`: Internal Server Error

#### WebRTC Specific Codes
- `4001`: Invalid API key
- `4002`: Connection limit exceeded
- `4003`: Invalid peer ID
- `4004`: Target peer not found
- `1011`: Internal server error

### Rate Limiting
- Default rate limit: 100 requests per week
- Rate limit headers included in response:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`

### WebRTC Configuration

#### ICE Servers
Default STUN server configuration:
```json
{
    "iceServers": [
        {
            "urls": ["stun:stun.l.google.com:19302"]
        }
    ]
}
```

#### Connection Parameters
- Max message size: 1MB (1048576 bytes)
- Heartbeat interval: 30 seconds
- Connection timeout: 300 seconds
- Max connections per company: 100

### Code Examples

#### WebRTC Connection Example (JavaScript)
```javascript
const connectWebRTC = async (peerId, apiKey) => {
    const ws = new WebSocket(
        `wss://your-domain.com/api/v1/webrtc/signal/${peerId}/${apiKey}`
    );
    
    ws.onmessage = async (event) => {
        const message = JSON.parse(event.data);
        switch(message.type) {
            case 'signal':
                // Handle WebRTC signaling
                break;
            case 'stream':
                // Handle streaming data
                break;
            case 'pong':
                // Handle heartbeat response
                break;
        }
    };
    
    // Send heartbeat
    setInterval(() => {
        ws.send(JSON.stringify({ type: 'ping' }));
    }, 30000);
};
```