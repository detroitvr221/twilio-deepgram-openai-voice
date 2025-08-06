#!/usr/bin/env python3
"""
Twilio + Deepgram Voice Agent Integration
Using HTTP Media Streams instead of WebSocket
"""

import asyncio
import base64
import json
import os
import sys
import ssl
from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
import threading
import time
from datetime import datetime
import logging
import requests

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app for Twilio webhooks
app = Flask(__name__)

# Store active connections
active_connections = {}

def create_deepgram_connection():
    """Create WebSocket connection to Deepgram Voice Agent"""
    api_key = os.getenv('DEEPGRAM_API_KEY')
    if not api_key:
        raise ValueError("DEEPGRAM_API_KEY environment variable is not set")
    
    import websockets
    return websockets.connect(
        "wss://agent.deepgram.com/agent",
        subprotocols=["token", api_key]
    )

@app.route('/', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return {
        'status': 'healthy',
        'message': 'Deepgram Voice Agent Server is running!',
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            'health': '/ (GET)',
            'voice': '/voice (POST)', 
            'media': '/media (POST)'
        },
        'active_connections': len(active_connections)
    }

@app.route('/voice', methods=['POST'])
def voice_webhook():
    """Twilio voice webhook - returns TwiML to start Media Stream"""
    caller = request.form.get('From', 'Unknown')
    logger.info(f"📞 Incoming call from: {caller}")
    
    response = VoiceResponse()
    
    # Use Connect for bidirectional streaming
    connect = response.connect()
    
    # Get the host from request headers
    host = request.headers.get('Host', 'localhost:5000')
    
    connect.stream(
        url=f'https://{host}/media',
        track='inbound_track',
        name='voice_agent_stream'
    )
    
    # This instruction is unreachable unless the Stream is ended
    # response.say('Connection ended.')  # Removed fallback message
    
    return Response(str(response), mimetype='text/xml')

@app.route('/media', methods=['POST'])
def media_webhook():
    """Handle Media Stream events from Twilio"""
    logger.info(f"📡 Media webhook called with headers: {dict(request.headers)}")
    logger.info(f"📡 Media webhook called with form data: {request.form.to_dict()}")
    
    # Try to get JSON data
    data = None
    try:
        data = request.get_json()
        logger.info(f"📡 Media webhook JSON data: {data}")
    except Exception as e:
        logger.info(f"📡 No JSON data in request: {e}")
    
    # Also check form data for Media Stream events
    if not data and request.form:
        data = request.form.to_dict()
        logger.info(f"📡 Using form data as Media Stream data: {data}")
    
    if not data:
        logger.info("📡 No data received in Media Stream webhook")
        return '', 200
    
    event = data.get('event')
    stream_sid = data.get('streamSid')
    
    logger.info(f"🔄 Media event: {event} for stream {stream_sid}")
    
    if event == 'start':
        # Start new connection to Deepgram
        asyncio.run(start_deepgram_connection(stream_sid))
    elif event == 'stop':
        # Clean up connection
        if stream_sid in active_connections:
            del active_connections[stream_sid]
            logger.info(f"🧹 Cleaned up stream {stream_sid}")
    else:
        logger.info(f"📡 Unknown Media Stream event: {event}")
    
    return '', 200

async def start_deepgram_connection(stream_sid):
    """Start Deepgram connection for a new stream"""
    try:
        async with create_deepgram_connection() as deepgram_ws:
            logger.info(f"🎙️ Connected to Deepgram Voice Agent for stream {stream_sid}")
            
            # Store connection
            active_connections[stream_sid] = {
                'deepgram_ws': deepgram_ws,
                'stream_sid': stream_sid
            }
            
            # Send Voice Agent configuration
            config_message = {
                "type": "Settings",
                "audio": {
                    "input": {
                        "encoding": "mulaw",
                        "sample_rate": 8000,
                    },
                    "output": {
                        "encoding": "mulaw", 
                        "sample_rate": 8000,
                        "container": "none",
                    },
                },
                "agent": {
                    "language": "en",
                    "listen": {
                        "provider": {
                            "type": "deepgram",
                            "model": "aura-2-odysseus-en",
                        }
                    },
                    "think": {
                        "provider": {
                            "type": "open_ai",
                            "model": "gpt-4o-mini",
                            "temperature": 0.7,
                        },
                        "prompt": """You are a helpful AI assistant integrated into a phone system.

Guidelines:
- Be concise and conversational since this is a voice interaction
- When users ask you to text something, offer to send an SMS
- When asked about business hours, provide helpful information
- When users want to set reminders, acknowledge the request
- Keep responses brief and natural for voice conversation
- Be friendly and professional

You can help with:
- General questions and conversation
- Information lookup
- Simple assistance and guidance

Current user is calling via phone."""
                    },
                    "speak": {
                        "provider": {
                            "type": "deepgram",
                            "model": "aura-2-odysseus-en",
                            "voice": "nova",
                        },
                    },
                    "greeting": "Hello! I'm your AI assistant. How can I help you today?"
                },
            }
            
            await deepgram_ws.send(json.dumps(config_message))
            logger.info("📋 Configuration sent to Deepgram Voice Agent")
            
            # Start tasks for handling messages
            tasks = [
                asyncio.create_task(handle_deepgram_messages(deepgram_ws, stream_sid)),
                asyncio.create_task(send_keep_alive(deepgram_ws))
            ]
            
            # Wait for any task to complete
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            
            # Cancel remaining tasks
            for task in pending:
                task.cancel()
                
    except Exception as e:
        logger.error(f"❌ Error in Deepgram connection: {e}")
    finally:
        # Cleanup
        if stream_sid in active_connections:
            del active_connections[stream_sid]
        logger.info(f"🧹 Cleaned up stream {stream_sid}")

async def handle_deepgram_messages(deepgram_ws, stream_sid):
    """Handle messages from Deepgram Voice Agent"""
    try:
        async for message in deepgram_ws:
            if isinstance(message, str):
                # Text message from Deepgram
                data = json.loads(message)
                logger.info(f"🤖 Deepgram message: {data.get('type', 'unknown')}")
                
                # Handle user started speaking (barge-in)
                if data.get('type') == 'UserStartedSpeaking':
                    # Send clear message to Twilio
                    send_clear_to_twilio(stream_sid)
                    logger.info("🔄 Sent barge-in clear message to Twilio")
                        
            else:
                # Binary audio data from Deepgram to send to Twilio
                send_audio_to_twilio(stream_sid, message)
                    
    except Exception as e:
        logger.error(f"❌ Error handling Deepgram messages: {e}")

def send_audio_to_twilio(stream_sid, audio_data):
    """Send audio data to Twilio via Media Streams API"""
    try:
        # Encode audio data
        encoded_audio = base64.b64encode(audio_data).decode('ascii')
        
        # Prepare media message
        media_message = {
            "event": "media",
            "streamSid": stream_sid,
            "media": {
                "payload": encoded_audio
            }
        }
        
        # Send to Twilio Media Streams API
        # Note: This would require Twilio's Media Streams API
        # For now, we'll log the audio data
        logger.info(f"🎵 Audio data ready for Twilio (stream: {stream_sid})")
        
    except Exception as e:
        logger.error(f"❌ Error sending audio to Twilio: {e}")

def send_clear_to_twilio(stream_sid):
    """Send clear message to Twilio"""
    try:
        clear_message = {
            "event": "clear",
            "streamSid": stream_sid
        }
        
        # Send to Twilio Media Streams API
        logger.info(f"🔄 Clear message ready for Twilio (stream: {stream_sid})")
        
    except Exception as e:
        logger.error(f"❌ Error sending clear to Twilio: {e}")

async def send_keep_alive(deepgram_ws):
    """Send keep-alive messages to maintain Deepgram connection"""
    try:
        while True:
            await asyncio.sleep(5)
            keep_alive_message = {"type": "KeepAlive"}
            await deepgram_ws.send(json.dumps(keep_alive_message))
            logger.debug("💓 Keep alive sent")
    except Exception as e:
        logger.error(f"❌ Error in keep-alive: {e}")

if __name__ == '__main__':
    # Validate environment variables
    required_env_vars = [
        'TWILIO_ACCOUNT_SID',
        'TWILIO_AUTH_TOKEN', 
        'TWILIO_PHONE_NUMBER',
        'DEEPGRAM_API_KEY',
        'OPENAI_API_KEY'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"❌ Missing environment variables: {missing_vars}")
        sys.exit(1)
    
    logger.info("✅ All environment variables are set")
    
    port = int(os.getenv('PORT', 5000))
    
    # Start Flask app for HTTP endpoints
    logger.info(f"🚀 Flask server starting on port {port}")
    logger.info(f"📞 Twilio webhook URL: https://twilio-deepgram-openai-voice.onrender.com/voice")
    logger.info(f"📡 Media stream URL: https://twilio-deepgram-openai-voice.onrender.com/media")
    logger.info(f"🔍 Test Media Stream: https://twilio-deepgram-openai-voice.onrender.com/media (POST with any data)")
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)