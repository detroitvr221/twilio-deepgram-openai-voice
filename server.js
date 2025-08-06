import 'dotenv/config';
import express from 'express';
import { createClient } from '@deepgram/sdk';
import OpenAI from 'openai';
import twilio from 'twilio';
import { WebSocketServer } from 'ws';
import { createServer } from 'http';

const app = express();
const server = createServer(app);
const wss = new WebSocketServer({ server });
const port = process.env.PORT || 8080;

// Middleware
app.use(express.urlencoded({ extended: false }));
app.use(express.json());

// Initialize clients
const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
});

const twilioClient = twilio(
  process.env.TWILIO_ACCOUNT_SID,
  process.env.TWILIO_AUTH_TOKEN
);

// Store active connections for cleanup
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
      streamStatus: '/stream-status (POST)',
      twilioStream: '/twilio-stream (WebSocket)'
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
  
  // Start media stream
  response.start().stream({
    url: `wss://${req.headers.host}/twilio-stream`,
    track: 'inbound_and_outbound_audio',
    statusCallback: '/stream-status',
  });
  
  // Initial greeting with better instructions
  response.say({
    voice: 'alice',
    language: 'en-US'
  }, 'Hello! I\'m your AI assistant. I can help you send text messages, look up business hours, or create reminders. Just speak clearly and I\'ll respond. What would you like me to do?');
  
  // Keep the call alive to receive audio
  response.pause({ length: 60 });
  
  res.type('text/xml').send(response.toString());
});

// Stream status callback
app.post('/stream-status', (req, res) => {
  console.log('🔄 Stream status:', req.body.StreamStatus);
  res.sendStatus(200);
});

// WebSocket handling for Twilio Media Streams
wss.on('connection', (ws, req) => {
  if (req.url === '/twilio-stream') {
    console.log('🔌 New Twilio stream connection');
    setupPipeline(ws);
  }
});

// Main pipeline: Twilio → Deepgram → OpenAI → Actions
function setupPipeline(twilioWs) {
  const connectionId = Date.now().toString();
  let callSid = null;
  let streamSid = null;
  
  // Initialize Deepgram connection with speaker detection and chunked processing
  const deepgram = createClient(process.env.DEEPGRAM_API_KEY);
  const dgConnection = deepgram.listen.live({
    encoding: 'mulaw',
    sample_rate: 8000,
    channels: 1,
    language: 'en-US',
    model: 'nova-2',
    interim_results: true,
    smart_format: true,
    filler_words: false,
    punctuate: true,
    // Add speaker detection and chunked processing
    diarize: true,
    utterances: true,
    endpointing: 1000,
    vad_events: true,
    interim_results: true,
    utterance_end_ms: 1000,
    chunk_length: 0.5, // Process in 0.5 second chunks
  });

  // Store connection for cleanup
  activeConnections.set(connectionId, {
    twilioWs,
    dgConnection,
    callSid,
    streamSid
  });

  console.log(`🎙️  Started pipeline for connection ${connectionId}`);

  // Handle Twilio messages
  twilioWs.on('message', async (data) => {
    try {
      const msg = JSON.parse(data);
      
      switch (msg.event) {
        case 'start':
          console.log('🚀 Media stream started');
          callSid = msg.start.callSid;
          streamSid = msg.start.streamSid;
          
          // Update connection info
          const conn = activeConnections.get(connectionId);
          if (conn) {
            conn.callSid = callSid;
            conn.streamSid = streamSid;
          }
          break;
          
        case 'media':
          // Forward audio data to Deepgram
          if (dgConnection.getReadyState() === 1) {
            const audioBuffer = Buffer.from(msg.media.payload, 'base64');
            dgConnection.send(audioBuffer);
          }
          break;
          
        case 'stop':
          console.log('🛑 Media stream stopped');
          cleanup(connectionId);
          break;
      }
    } catch (error) {
      console.error('❌ Error processing Twilio message:', error);
    }
  });

  // Handle Deepgram transcription results with speaker detection
  dgConnection.on('Results', async (data) => {
    try {
      const result = data.channel?.alternatives?.[0];
      if (!result) return;

      const transcript = result.transcript?.trim();
      if (!transcript) return;

      // Get speaker information if available
      const speaker = result.words?.[0]?.speaker || 'unknown';
      const speakerLabel = speaker === 0 ? 'Caller' : 'AI';

      // Process both interim and final results for better responsiveness
      if (data.is_final && transcript.length > 0) {
        console.log(`📝 Final transcript (${speakerLabel}):`, transcript);
        
        // Process with OpenAI
        const aiResponse = await processWithOpenAI(transcript);
        
        // Execute any function calls
        if (aiResponse.tool_calls?.length > 0) {
          await handleFunctionCalls(aiResponse.tool_calls, callSid);
        }
        
        // Send response back to caller if there's a content response
        if (aiResponse.content) {
          await sendTwiMLResponse(aiResponse.content, callSid);
        }
      } else if (!data.is_final && transcript.length > 3) {
        // Process interim results for faster response
        console.log(`🔄 Interim (${speakerLabel}):`, transcript);
        
        // For longer interim transcripts, process them too
        if (transcript.length > 10 && transcript.includes('send') || transcript.includes('text') || transcript.includes('message')) {
          console.log('🚀 Processing interim command:', transcript);
          const aiResponse = await processWithOpenAI(transcript);
          
          if (aiResponse.tool_calls?.length > 0) {
            await handleFunctionCalls(aiResponse.tool_calls, callSid);
          }
          
          if (aiResponse.content) {
            await sendTwiMLResponse(aiResponse.content, callSid);
          }
        }
      }
    } catch (error) {
      console.error('❌ Error processing Deepgram result:', error);
    }
  });

  // Handle connection cleanup
  twilioWs.on('close', () => {
    console.log('🔌 Twilio WebSocket closed');
    cleanup(connectionId);
  });

  dgConnection.on('close', () => {
    console.log('🔌 Deepgram connection closed');
  });

  dgConnection.on('error', (error) => {
    console.error('❌ Deepgram error:', error);
  });
}

// Process transcript with OpenAI and function calling
async function processWithOpenAI(transcript) {
  const tools = [
    {
      type: 'function',
      function: {
        name: 'send_sms',
        description: 'Send an SMS message to a phone number',
        parameters: {
          type: 'object',
          properties: {
            to: {
              type: 'string',
              description: 'Phone number to send SMS to (include country code, e.g., +1234567890)',
            },
            body: {
              type: 'string',
              description: 'Message content to send',
            },
          },
          required: ['to', 'body'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'lookup_business_hours',
        description: 'Look up business hours for a location or service',
        parameters: {
          type: 'object',
          properties: {
            business_name: {
              type: 'string',
              description: 'Name of the business to look up',
            },
            location: {
              type: 'string',
              description: 'Location or address of the business',
            },
          },
          required: ['business_name'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'create_reminder',
        description: 'Create a reminder or note',
        parameters: {
          type: 'object',
          properties: {
            reminder_text: {
              type: 'string',
              description: 'The reminder or note content',
            },
            when: {
              type: 'string',
              description: 'When the reminder is for (e.g., "tomorrow", "next week", specific date)',
            },
          },
          required: ['reminder_text'],
        },
      },
    },
  ];

  try {
    const completion = await openai.chat.completions.create({
      model: 'gpt-4o-mini',
      messages: [
        {
          role: 'system',
          content: `You are a helpful AI assistant integrated into a phone system. 
          
Guidelines:
- Be concise and conversational since this is a voice interaction
- When users ask you to text something, use the send_sms function
- When asked about business hours, use the lookup_business_hours function  
- When users want to set reminders, use the create_reminder function
- Always confirm actions you're taking
- Keep responses under 2 sentences when possible
- Be friendly and professional`,
        },
        {
          role: 'user',
          content: transcript,
        },
      ],
      tools,
      tool_choice: 'auto',
      temperature: 0.7,
      max_tokens: 150,
    });

    const message = completion.choices[0].message;
    console.log('🤖 OpenAI response:', message);
    
    return message;
  } catch (error) {
    console.error('❌ OpenAI API error:', error);
    return {
      content: "I'm sorry, I'm having trouble processing your request right now. Please try again.",
    };
  }
}

// Handle function calls from OpenAI
async function handleFunctionCalls(toolCalls, callSid) {
  for (const toolCall of toolCalls) {
    const { name, arguments: args } = toolCall.function;
    console.log(`🔧 Executing function: ${name}`, args);

    try {
      const parsedArgs = JSON.parse(args);

      switch (name) {
        case 'send_sms':
          await sendSMS(parsedArgs.to, parsedArgs.body);
          await sendTwiMLResponse(
            `I've sent an SMS to ${parsedArgs.to} with your message.`,
            callSid
          );
          break;

        case 'lookup_business_hours':
          // Mock business hours lookup - in production, integrate with Google Places API, Yelp, etc.
          const hours = await lookupBusinessHours(parsedArgs.business_name, parsedArgs.location);
          await sendTwiMLResponse(hours, callSid);
          break;

        case 'create_reminder':
          // Mock reminder creation - in production, integrate with calendar/task system
          await createReminder(parsedArgs.reminder_text, parsedArgs.when);
          await sendTwiMLResponse(
            `I've created a reminder: ${parsedArgs.reminder_text}${parsedArgs.when ? ` for ${parsedArgs.when}` : ''}.`,
            callSid
          );
          break;

        default:
          console.log(`❓ Unknown function: ${name}`);
      }
    } catch (error) {
      console.error(`❌ Error executing function ${name}:`, error);
      await sendTwiMLResponse(
        "I'm sorry, I encountered an error processing your request.",
        callSid
      );
    }
  }
}

// Send SMS using Twilio
async function sendSMS(to, body) {
  try {
    const message = await twilioClient.messages.create({
      body,
      from: process.env.TWILIO_PHONE_NUMBER,
      to,
    });
    
    console.log('📱 SMS sent:', message.sid);
    return message;
  } catch (error) {
    console.error('❌ SMS sending failed:', error);
    throw error;
  }
}

// Mock business hours lookup
async function lookupBusinessHours(businessName, location) {
  // In production, integrate with Google Places API, Yelp API, etc.
  const mockHours = {
    'store': 'Monday through Friday 9 AM to 6 PM, Saturday 10 AM to 4 PM, closed Sunday',
    'restaurant': 'Monday through Thursday 11 AM to 10 PM, Friday and Saturday 11 AM to 11 PM, Sunday 12 PM to 9 PM',
    'bank': 'Monday through Friday 9 AM to 5 PM, Saturday 9 AM to 1 PM, closed Sunday',
  };

  const businessType = Object.keys(mockHours).find(type => 
    businessName.toLowerCase().includes(type)
  );

  return businessType 
    ? `${businessName} hours are ${mockHours[businessType]}`
    : `I couldn't find specific hours for ${businessName}. You might want to call them directly or check their website.`;
}

// Mock reminder creation
async function createReminder(reminderText, when) {
  // In production, integrate with calendar system, database, etc.
  console.log(`📅 Reminder created: "${reminderText}"${when ? ` for ${when}` : ''}`);
  return true;
}

// Send TwiML response to update the call
async function sendTwiMLResponse(message, callSid) {
  if (!callSid) {
    console.log('⚠️  No callSid available for TwiML response');
    return;
  }

  try {
    const twiml = new twilio.twiml.VoiceResponse();
    twiml.say({
      voice: 'alice',
      language: 'en-US'
    }, message);
    
    // Keep the call active to continue listening
    twiml.pause({ length: 5 });

    await twilioClient.calls(callSid).update({
      twiml: twiml.toString(),
    });

    console.log('🗣️  TwiML response sent:', message);
  } catch (error) {
    console.error('❌ Failed to send TwiML response:', error);
  }
}

// Cleanup connections
function cleanup(connectionId) {
  const connection = activeConnections.get(connectionId);
  if (connection) {
    try {
      if (connection.dgConnection) {
        connection.dgConnection.finish();
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
  console.log(`🔌 WebSocket URL: ws://localhost:${port}/twilio-stream`);
  
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
    console.warn('⚠️  Missing environment variables:', missingVars.join(', '));
    console.warn('📋 Please check your .env file');
  }
});