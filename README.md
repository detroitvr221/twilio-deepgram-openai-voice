# Twilio + Deepgram Voice Agent (Python)

A Python implementation of a real-time voice AI assistant using:
- **Twilio Programmable Voice** for phone calls
- **Deepgram Voice Agent API** for unified STT + TTS + AI processing  
- **OpenAI GPT-4** for intelligent responses

## Features

- 🎙️ **Real-time voice conversations** via phone calls
- 🤖 **AI-powered responses** with natural speech
- 🔄 **Barge-in support** (interrupt the AI while speaking)
- 📱 **SMS integration** for sending text messages
- 🎯 **Optimized for phone quality** (8kHz mulaw audio)
- 🔌 **WebSocket streaming** for low-latency audio

## Quick Start

### 1. Clone and Setup

```bash
git clone <your-repo>
cd twilio-deepgram-voice-agent
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

```bash
# Twilio Configuration
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_PHONE_NUMBER=your_twilio_phone_number

# Deepgram Configuration  
DEEPGRAM_API_KEY=your_deepgram_api_key

# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key

# Server Configuration
PORT=5000
HOST=localhost
```

### 4. Run the Server

```bash
python server.py
```

### 5. Configure Twilio Webhook

1. Go to [Twilio Console](https://console.twilio.com/)
2. Navigate to Phone Numbers → Manage → Active numbers
3. Click on your phone number
4. Set "A call comes in" webhook to: `https://your-domain.com/voice`
5. Set HTTP method to `POST`

## Architecture

```
Caller → Twilio → Your Server → Deepgram Voice Agent
                       ↓
                WebSocket Connection
                       ↓
              Unified STT + TTS + AI
```

## API Endpoints

- `GET /` - Health check
- `POST /voice` - Twilio voice webhook (returns TwiML)
- `POST /stream-status` - Stream status callbacks
- `WebSocket /twilio` - Audio streaming endpoint

## Voice Agent Configuration

The AI assistant is configured with:

- **STT Model**: `aura-2-odysseus-en` (Deepgram)
- **TTS Model**: `aura-2-odysseus-en` with `nova` voice
- **LLM Model**: `gpt-4o-mini` (OpenAI)
- **Audio Format**: 8kHz mulaw (phone compatible)
- **Features**: Barge-in, keep-alive, error handling

## Deployment

### Option 1: Render
1. Connect your GitHub repo to Render
2. Set environment variables in Render dashboard
3. Deploy automatically

### Option 2: Railway
```bash
railway login
railway init
railway up
```

### Option 3: Local with ngrok
```bash
# Terminal 1
python server.py

# Terminal 2  
ngrok http 5000
```

## Testing

1. **Call your Twilio number**
2. **Say**: "Hello, can you help me?"
3. **AI responds**: Natural conversation
4. **Try**: "Send a text message" (demonstrates function calling)

## Troubleshooting

### Common Issues

- **Connection errors**: Check API keys and network connectivity
- **Audio quality**: Ensure proper mulaw encoding/decoding
- **Timeouts**: Keep-alive messages prevent WebSocket timeouts
- **Barge-in not working**: Check UserStartedSpeaking event handling

### Logs

The server provides detailed logging:
- 📞 Call events
- 🎙️ Voice Agent connections  
- 🤖 AI responses
- 🔄 Stream status
- ❌ Errors and warnings

## Architecture Benefits

- **Simplified**: Single WebSocket connection to Deepgram
- **Low Latency**: Optimized audio streaming
- **Scalable**: Async Python with proper connection management
- **Reliable**: Error handling and automatic reconnection
- **Official**: Based on Deepgram's official documentation

## License

MIT License