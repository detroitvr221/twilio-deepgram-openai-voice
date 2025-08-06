import 'dotenv/config';
import express from 'express';
import { createClient } from '@deepgram/sdk';
import OpenAI from 'openai';
import twilio from 'twilio';
import WebSocket from 'ws';
import http from 'http';

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

const port = process.env.PORT || 8080;

// Initialize clients
const twilioClient = twilio(process.env.TWILIO_ACCOUNT_SID, process.env.TWILIO_AUTH_TOKEN);
const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

// Store active connections
const activeConnections = new Map();

// Root endpoint
app.get('/', (req, res) => {
  res.json({ 
    message: 'Voice AI Server is running!',
    status: 'healthy', 
    timestamp: new Date().toISOString(),
    endpoints: {
      health: '/health',
      voice: '/voice (POST)',
      twilioStream: '/twilio (WebSocket)'
    },
    activeConnections: activeConnections.size
  });
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ 
    status: 'healthy', 
    timestamp: new Date().toISOString(),
    activeConnections: activeConnections.size
  });
});

// Twilio voice webhook - returns TwiML to start Media Stream
app.post('/voice', (req, res) => {
  console.log('📞 Incoming call from:', req.body.From);
  
  const response = new twilio.twiml.VoiceResponse();
  
  // Start media stream to our WebSocket endpoint
  response.start().stream({
    url: `wss://${req.headers.host}/twilio`,
    track: 'inbound_and_outbound_audio',
  });

  // Keep the call alive
  response.pause({ length: 60 });
  
  res.type('text/xml').send(response.toString());
});

// WebSocket handling for Twilio Media Streams
wss.on('connection', (ws, req) => {
  if (req.url === '/twilio') {
    console.log('🔌 New Twilio stream connection');
    handleTwilioConnection(ws);
  }
});

// Main handler for Twilio ↔ Deepgram Voice Agent
async function handleTwilioConnection(twilioWs) {
  const connectionId = Date.now().toString();
  let streamSid = null;
  
  // Queues for communication between tasks
  const audioQueue = [];
  const streamSidQueue = [];
  
  try {
    // Connect to Deepgram Voice Agent
    const deepgram = createClient(process.env.DEEPGRAM_API_KEY);
    const agentConnection = await deepgram.agent.converse({
      audio: {
        input: {
          encoding: 'mulaw',
          sample_rate: 8000,
        },
        output: {
          encoding: 'mulaw',
          sample_rate: 8000,
          container: 'none',
        },
      },
      agent: {
        language: 'en',
        listen: {
          provider: {
            type: 'deepgram',
            model: 'aura-2-odysseus-en',
          },
        },
        think: {
          provider: {
            type: 'open_ai',
            model: 'gpt-4o-mini',
            temperature: 0.7,
          },
          prompt: `You are a helpful AI assistant integrated into a phone system. 

Guidelines:
- Be concise and conversational since this is a voice interaction
- When users ask you to text something, use the send_sms function
- When asked about business hours, use the lookup_business_hours function  
- When users want to set reminders, use the create_reminder function
- Keep responses brief and natural for voice conversation
- If you need to use a function, explain what you're doing first

Available functions:
- send_sms(to, body): Send a text message
- lookup_business_hours(business_name, location): Get business hours
- create_reminder(reminder_text, when): Create a reminder

Current user transcript: {transcript}`,
        },
        speak: {
          provider: {
            type: 'deepgram',
            model: 'aura-2-odysseus-en',
            voice: 'nova',
          },
        },
      },
    });

    console.log('🎙️  Connected to Deepgram Voice Agent');

    // Store connection for cleanup
    activeConnections.set(connectionId, {
      twilioWs,
      agentConnection,
      streamSid
    });

    // Handle messages from Deepgram Agent
    agentConnection.on('message', async (message) => {
      try {
        if (typeof message === 'string') {
          const data = JSON.parse(message);
          
          // Handle user started speaking (barge-in)
          if (data.type === 'UserStartedSpeaking') {
            const clearMessage = {
              event: 'clear',
              streamSid: streamSid
            };
            await twilioWs.send(JSON.stringify(clearMessage));
            return;
          }
          
          console.log('🤖 Agent message:', data);
        } else {
          // Audio from Deepgram Agent to send to Twilio
          const mediaMessage = {
            event: 'media',
            streamSid: streamSid,
            media: {
              payload: Buffer.from(message).toString('base64')
            }
          };
          await twilioWs.send(JSON.stringify(mediaMessage));
        }
      } catch (error) {
        console.error('❌ Error handling agent message:', error);
      }
    });

    // Handle messages from Twilio
    twilioWs.on('message', async (data) => {
      try {
        const msg = JSON.parse(data);
        
        switch (msg.event) {
          case 'start':
            console.log('🚀 Media stream started');
            streamSid = msg.start.streamSid;
            
            // Update connection info
            const conn = activeConnections.get(connectionId);
            if (conn) {
              conn.streamSid = streamSid;
            }
            break;
            
          case 'media':
            if (msg.media.track === 'inbound') {
              // Decode audio from Twilio and send to Deepgram Agent
              const audioChunk = Buffer.from(msg.media.payload, 'base64');
              await agentConnection.send(audioChunk);
            }
            break;
            
          case 'stop':
            console.log('🛑 Media stream stopped');
            break;
        }
      } catch (error) {
        console.error('❌ Error handling Twilio message:', error);
      }
    });

    // Handle connection close
    twilioWs.on('close', () => {
      console.log('🔌 Twilio connection closed');
      cleanup(connectionId);
    });

    agentConnection.on('close', () => {
      console.log('🎙️  Agent connection closed');
      cleanup(connectionId);
    });

  } catch (error) {
    console.error('❌ Failed to setup Voice Agent connection:', error);
    cleanup(connectionId);
  }
}

// Cleanup connections
function cleanup(connectionId) {
  const connection = activeConnections.get(connectionId);
  if (connection) {
    try {
      if (connection.agentConnection) {
        connection.agentConnection.close();
      }
    } catch (error) {
      console.error('❌ Error during cleanup:', error);
    }
    
    activeConnections.delete(connectionId);
    console.log(`🧹 Cleaned up connection ${connectionId}`);
  }
}

// Graceful shutdown
process.on('SIGINT', () => {
  console.log('🛑 Shutting down gracefully...');
  
  // Close all active connections
  for (const [connectionId, connection] of activeConnections) {
    cleanup(connectionId);
  }
  
  // Close server
  server.close(() => {
    console.log('👋 Server closed');
    process.exit(0);
  });
});

// Start server
server.listen(port, () => {
  console.log(`🚀 Server running on port ${port}`);
  console.log(`📞 Twilio webhook URL: http://localhost:${port}/voice`);
  console.log(`🔌 WebSocket URL: ws://localhost:${port}/twilio`);
  
  // Validate environment variables
  const requiredEnvVars = [
    'TWILIO_ACCOUNT_SID',
    'TWILIO_AUTH_TOKEN', 
    'TWILIO_PHONE_NUMBER',
    'DEEPGRAM_API_KEY',
    'OPENAI_API_KEY'
  ];
  
  const missingVars = requiredEnvVars.filter(varName => !process.env[varName]);
  
  if (missingVars.length > 0) {
    console.error('❌ Missing environment variables:', missingVars);
    process.exit(1);
  }
  
  console.log('✅ All environment variables are set');
});