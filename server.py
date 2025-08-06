#!/usr/bin/env python3
"""
Twilio + Deepgram Voice Agent Integration
Based on official Deepgram Voice Agent documentation
"""

import asyncio
import base64
import json
import os
import sys
import websockets
import ssl
from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
import threading
import time
from datetime import datetime
import logging

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
            'stream_status': '/stream-status (POST)'
        },
        'active_connections': len(active_connections)
    }

@app.route('/voice', methods=['POST'])
def voice_webhook():
    """Twilio voice webhook - returns TwiML to start Media Stream"""
    caller = request.form.get('From', 'Unknown')
    logger.info(f"📞 Incoming call from: {caller}")
    
    response = VoiceResponse()
    
    # Use Connect for bidirectional streaming (recommended for Voice Agent)
    connect = response.connect()
    
    # Get the host from request headers
    host = request.headers.get('Host', 'localhost:5000')
    
    connect.stream(
        url=f'wss://{host}/twilio',
        track='inbound_track',  # Only inbound for Connect streams
        name='voice_agent_stream'
    )
    
    # This instruction is unreachable unless the Stream is ended by WebSocket server
    response.say('Connection ended.')
    
    return Response(str(response), mimetype='text/xml')

@app.route('/stream-status', methods=['POST'])
def stream_status():
    """Stream status callback endpoint"""
    logger.info(f"🔄 Stream status: {request.form.to_dict()}")
    return '', 200

async def handle_twilio_connection(websocket, path):
    """Handle WebSocket connection from Twilio"""
    if path != '/twilio':
        logger.warning(f"Unknown path: {path}")
        return
        
    logger.info("🔌 New Twilio stream connection")
    connection_id = f"conn_{int(time.time() * 1000)}"
    
    # Queues for communication between tasks
    audio_queue = asyncio.Queue()
    stream_sid_queue = asyncio.Queue()
    
    try:
        # Connect to Deepgram Voice Agent
        async with create_deepgram_connection() as deepgram_ws:
            logger.info("🎙️ Connected to Deepgram Voice Agent")
            
            # Store connection for cleanup
            active_connections[connection_id] = {
                'twilio_ws': websocket,
                'deepgram_ws': deepgram_ws,
                'stream_sid': None
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
                asyncio.create_task(handle_twilio_messages(websocket, deepgram_ws, connection_id)),
                asyncio.create_task(handle_deepgram_messages(deepgram_ws, websocket, connection_id)),
                asyncio.create_task(send_keep_alive(deepgram_ws))
            ]
            
            # Wait for any task to complete (usually means connection closed)
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            
            # Cancel remaining tasks
            for task in pending:
                task.cancel()
                
    except Exception as e:
        logger.error(f"❌ Error in Twilio connection handler: {e}")
    finally:
        # Cleanup
        if connection_id in active_connections:
            del active_connections[connection_id]
        logger.info(f"🧹 Cleaned up connection {connection_id}")

async def handle_twilio_messages(twilio_ws, deepgram_ws, connection_id):
    """Handle messages from Twilio"""
    BUFFER_SIZE = 20 * 160  # 20 Twilio messages = 0.4 seconds of audio
    audio_buffer = bytearray()
    
    try:
        async for message in twilio_ws:
            data = json.loads(message)
            
            if data["event"] == "start":
                logger.info("🚀 Media stream started")
                stream_sid = data["start"]["streamSid"]
                if connection_id in active_connections:
                    active_connections[connection_id]['stream_sid'] = stream_sid
                    
            elif data["event"] == "connected":
                logger.info("🔗 Twilio connected")
                continue
                
            elif data["event"] == "media":
                media = data["media"]
                if media["track"] == "inbound":
                    # Decode audio from Twilio
                    chunk = base64.b64decode(media["payload"])
                    audio_buffer.extend(chunk)
                    
                    # Send buffered audio to Deepgram when buffer is ready
                    while len(audio_buffer) >= BUFFER_SIZE:
                        audio_chunk = audio_buffer[:BUFFER_SIZE]
                        await deepgram_ws.send(audio_chunk)
                        audio_buffer = audio_buffer[BUFFER_SIZE:]
                        
            elif data["event"] == "stop":
                logger.info("🛑 Media stream stopped")
                break
                
    except websockets.exceptions.ConnectionClosed:
        logger.info("🔌 Twilio WebSocket connection closed")
    except Exception as e:
        logger.error(f"❌ Error handling Twilio messages: {e}")

async def handle_deepgram_messages(deepgram_ws, twilio_ws, connection_id):
    """Handle messages from Deepgram Voice Agent"""
    try:
        async for message in deepgram_ws:
            if isinstance(message, str):
                # Text message from Deepgram
                data = json.loads(message)
                logger.info(f"🤖 Deepgram message: {data.get('type', 'unknown')}")
                
                # Handle user started speaking (barge-in)
                if data.get('type') == 'UserStartedSpeaking':
                    conn = active_connections.get(connection_id)
                    if conn and conn['stream_sid']:
                        clear_message = {
                            "event": "clear",
                            "streamSid": conn['stream_sid']
                        }
                        await twilio_ws.send(json.dumps(clear_message))
                        logger.info("🔄 Sent barge-in clear message to Twilio")
                        
            else:
                # Binary audio data from Deepgram to send to Twilio
                conn = active_connections.get(connection_id)
                if conn and conn['stream_sid']:
                    media_message = {
                        "event": "media",
                        "streamSid": conn['stream_sid'],
                        "media": {
                            "payload": base64.b64encode(message).decode("ascii")
                        }
                    }
                    await twilio_ws.send(json.dumps(media_message))
                    
    except websockets.exceptions.ConnectionClosed:
        logger.info("🔌 Deepgram WebSocket connection closed")
    except Exception as e:
        logger.error(f"❌ Error handling Deepgram messages: {e}")

async def send_keep_alive(deepgram_ws):
    """Send keep-alive messages to maintain Deepgram connection"""
    try:
        while True:
            await asyncio.sleep(5)
            keep_alive_message = {"type": "KeepAlive"}
            await deepgram_ws.send(json.dumps(keep_alive_message))
            logger.debug("💓 Keep alive sent")
    except websockets.exceptions.ConnectionClosed:
        logger.info("🔌 Keep-alive stopped: Deepgram connection closed")
    except Exception as e:
        logger.error(f"❌ Error in keep-alive: {e}")

def start_websocket_server():
    """Start the WebSocket server for Twilio connections"""
    port = int(os.getenv('PORT', 5000))
    
    # Create WebSocket server
    start_server = websockets.serve(
        handle_twilio_connection,
        "0.0.0.0",
        port,
        ping_interval=None,
        ping_timeout=None
    )
    
    logger.info(f"🔌 WebSocket server starting on port {port}")
    
    # Run the server
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_server)
    loop.run_forever()

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
    
    # Start WebSocket server in a separate thread
    websocket_thread = threading.Thread(target=start_websocket_server, daemon=True)
    websocket_thread.start()
    
    # Start Flask app for HTTP endpoints
    logger.info(f"🚀 Flask server starting on port {port}")
    logger.info(f"📞 Twilio webhook URL: https://your-render-url.onrender.com/voice")
    logger.info(f"🔌 WebSocket URL: wss://your-render-url.onrender.com/twilio")
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)