# 🎙️ Real-time Voice AI with Twilio + Deepgram + OpenAI

A complete implementation of real-time voice AI that combines **Twilio Programmable Voice**, **Deepgram live transcription**, and **OpenAI function calling** to create intelligent phone interactions.

## 🏗️ Architecture

```
Incoming Call → Twilio Voice → Media Streams → Deepgram ASR → OpenAI → Actions
     ↓              ↓              ↓              ↓          ↓
  Phone Number   WebSocket     Live Transcription  Function   SMS/API
                 (μ-law)       (Real-time text)    Calling    Calls
```

## ✨ Features

- **Real-time transcription** during phone calls
- **AI-powered conversation** with OpenAI GPT
- **Function calling** for structured actions:
  - Send SMS messages
  - Look up business hours
  - Create reminders
  - Extensible for custom functions
- **Low-latency processing** with Deepgram Nova-2 model
- **Graceful error handling** and connection management
- **Health monitoring** and logging

## 🚀 Quick Start

### Prerequisites

1. **Twilio Account** with a voice-enabled phone number
2. **Deepgram API Key** from [developers.deepgram.com](https://developers.deepgram.com)
3. **OpenAI API Key** from [platform.openai.com](https://platform.openai.com)
4. **Node.js 18+** installed
5. **Public server URL** that supports HTTP and WebSocket

### Installation

1. **Clone and install dependencies:**
   ```bash
   npm install
   ```

2. **Configure environment variables:**
   ```bash
   cp env.example .env
   ```
   
   Edit `.env` with your credentials:
   ```bash
   # Twilio Configuration
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_PHONE_NUMBER=+1234567890

   # Deepgram Configuration  
   DEEPGRAM_API_KEY=dg_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

   # OpenAI Configuration
   OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

   # Server Configuration
   PORT=8080
   ```

3. **Start the server:**
   ```bash
   npm start
   # or for development with auto-reload:
   npm run dev
   ```

### Twilio Configuration

1. **Enable Media Streams:**
   - Go to Twilio Console → Voice → Settings → Media Streams
   - Enable "Allow Media Streams"

2. **Configure Phone Number:**
   - Go to Phone Numbers → Manage → Active numbers
   - Click your phone number
   - Set webhook URL: `https://your-domain.com/voice`
   - HTTP Method: `POST`

3. **Test the setup:**
   - Call your Twilio phone number
   - Speak: "Text me the store hours at +1234567890"
   - Check server logs for processing

## 🔧 Function Examples

The AI can perform structured actions based on conversation. Here are the built-in functions:

### Send SMS
**Voice:** "Text John at 555-123-4567 that the meeting is at 3 PM"
**Result:** SMS sent to +15551234567

### Business Hours Lookup
**Voice:** "What are the store hours?"
**Result:** AI responds with business hours information

### Create Reminder
**Voice:** "Remind me to call the dentist tomorrow"
**Result:** Reminder created and confirmed

## 🛠️ Development

### Project Structure

```
├── server.js           # Main application server
├── package.json        # Dependencies and scripts
├── env.example         # Environment template
├── README.md           # This file
└── docker/            # Deployment configurations
```

### Key Components

- **`/voice` endpoint**: Returns TwiML to start media streaming
- **WebSocket handler**: Processes real-time audio from Twilio
- **Deepgram integration**: Converts speech to text with low latency
- **OpenAI function calling**: Converts natural language to structured actions
- **Action handlers**: Execute functions like SMS, lookups, reminders

### Adding Custom Functions

1. **Define the function in OpenAI tools array:**
   ```javascript
   {
     type: 'function',
     function: {
       name: 'your_function_name',
       description: 'What this function does',
       parameters: {
         type: 'object',
         properties: {
           param1: { type: 'string', description: 'Parameter description' }
         },
         required: ['param1']
       }
     }
   }
   ```

2. **Add handler in `handleFunctionCalls`:**
   ```javascript
   case 'your_function_name':
     await yourFunctionHandler(parsedArgs.param1);
     break;
   ```

3. **Implement the handler function:**
   ```javascript
   async function yourFunctionHandler(param1) {
     // Your custom logic here
     console.log('Executing custom function with:', param1);
   }
   ```

## 📊 Monitoring

### Health Check
```bash
curl http://localhost:8080/health
```

### Logs
The server provides detailed logging:
- 📞 Incoming calls
- 🎙️ Audio stream events  
- 📝 Transcription results
- 🤖 AI responses
- 🔧 Function executions
- 📱 SMS sending
- ❌ Errors and debugging

### Performance Metrics
- Active connection count
- Transcription latency
- Function execution time
- Error rates

## 🚀 Deployment

### Environment Variables for Production

```bash
NODE_ENV=production
HOST=your-domain.com
PORT=443  # or your preferred port
```

### Docker Deployment

```dockerfile
FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
EXPOSE 8080
CMD ["npm", "start"]
```

### Platform-Specific Guides

**Railway:**
```bash
railway login
railway init
railway add
railway deploy
```

**Render:**
- Connect GitHub repository
- Set environment variables
- Deploy automatically

**Fly.io:**
```bash
flyctl apps create your-app-name
flyctl secrets set TWILIO_ACCOUNT_SID=...
flyctl deploy
```

## 🔒 Security Best Practices

1. **Verify Twilio requests** (implement signature validation)
2. **Use HTTPS/WSS** in production
3. **Sanitize user inputs** before processing
4. **Rate limit** API calls
5. **Monitor for abuse** patterns
6. **Handle PII** appropriately in transcripts
7. **Implement authentication** for admin endpoints

## 🎯 Production Considerations

### Scalability
- Use Redis for session management across instances
- Implement message queues for async processing
- Consider WebSocket connection pooling
- Add database persistence for conversation history

### Reliability
- Add retry logic for API calls
- Implement circuit breakers
- Set up proper error tracking
- Configure alerts for failures

### Compliance
- Handle PII redaction in transcripts
- Implement conversation recording controls
- Add consent management
- Follow telecom regulations

## 🐛 Troubleshooting

### Common Issues

**Connection refused errors:**
- Check that server is running on correct port
- Verify public URL is accessible
- Ensure WebSocket endpoint is available

**No transcription:**
- Verify Deepgram API key is valid
- Check audio format configuration
- Monitor Deepgram connection status

**Functions not executing:**
- Validate OpenAI API key
- Check function definitions in tools array
- Review function call parsing logic

**TwiML errors:**
- Verify webhook URL is publicly accessible
- Check Twilio account permissions
- Review TwiML syntax

### Debug Mode
Set environment variable for verbose logging:
```bash
DEBUG=true npm start
```

## 📚 API References

- [Twilio Media Streams](https://www.twilio.com/docs/voice/media-streams)
- [Deepgram Live Streaming](https://developers.deepgram.com/docs/live-streaming-audio)
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details

---

**Need help?** Check the troubleshooting section or open an issue for support.