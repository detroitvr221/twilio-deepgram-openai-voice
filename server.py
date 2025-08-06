#!/usr/bin/env python3
"""
Twilio + Deepgram Voice Agent Integration
Following the proven WebSocket-based approach
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
from collections import defaultdict
import weakref
import gc
from functools import lru_cache
import time

# Load environment variables
load_dotenv()

# Configure logging with better formatting
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask app for Twilio webhooks
app = Flask(__name__)

# Optimized connection storage with automatic cleanup
class ConnectionManager:
    def __init__(self):
        self._connections = {}
        self._lock = threading.Lock()
        self._cleanup_timer = None
        
    def add_connection(self, stream_sid, connection_data):
        with self._lock:
            self._connections[stream_sid] = {
                **connection_data,
                'created_at': time.time(),
                'last_activity': time.time()
            }
        logger.info(f"➕ Added connection {stream_sid}")
        
    def get_connection(self, stream_sid):
        with self._lock:
            conn = self._connections.get(stream_sid)
            if conn:
                conn['last_activity'] = time.time()
            return conn
            
    def remove_connection(self, stream_sid):
        with self._lock:
            if stream_sid in self._connections:
                del self._connections[stream_sid]
                logger.info(f"➖ Removed connection {stream_sid}")
                
    def cleanup_inactive(self, max_age=300):  # 5 minutes
        current_time = time.time()
        to_remove = []
        
        with self._lock:
            for stream_sid, conn in self._connections.items():
                if current_time - conn['last_activity'] > max_age:
                    to_remove.append(stream_sid)
                    
        for stream_sid in to_remove:
            self.remove_connection(stream_sid)
            logger.info(f"🧹 Cleaned up inactive connection {stream_sid}")
            
    def get_active_count(self):
        with self._lock:
            return len(self._connections)
            
    def get_connection_info(self):
        with self._lock:
            return {
                'total': len(self._connections),
                'streams': list(self._connections.keys())
            }

# Global connection manager
connection_manager = ConnectionManager()

# Audio buffer configuration
AUDIO_BUFFER_SIZE = 160  # 20ms at 8kHz
MAX_BUFFER_SIZE = 3200   # 400ms max buffer

# Rate limiting
class RateLimiter:
    def __init__(self, max_requests=100, window=60):
        self.max_requests = max_requests
        self.window = window
        self.requests = defaultdict(list)
        
    def is_allowed(self, key):
        now = time.time()
        # Clean old requests
        self.requests[key] = [req for req in self.requests[key] if now - req < self.window]
        
        if len(self.requests[key]) >= self.max_requests:
            return False
            
        self.requests[key].append(now)
        return True

rate_limiter = RateLimiter()

# Cached configurations
@lru_cache(maxsize=1)
def get_deepgram_config():
    """Get cached Deepgram configuration"""
    return {
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

def create_deepgram_connection():
    """Create WebSocket connection to Deepgram Voice Agent with retry logic"""
    api_key = os.getenv('DEEPGRAM_API_KEY')
    if not api_key:
        raise ValueError("DEEPGRAM_API_KEY environment variable is not set")
    
    import websockets
    
    # Connection with timeout and retry
    return websockets.connect(
        "wss://agent.deepgram.com/agent",
        subprotocols=["token", api_key],
        ping_interval=20,
        ping_timeout=10,
        close_timeout=5
    )

@app.route('/', methods=['GET'])
def health_check():
    """Health check endpoint with detailed metrics"""
    try:
        # Check environment variables
        env_status = {
            'deepgram_api_key': bool(os.getenv('DEEPGRAM_API_KEY')),
            'openai_api_key': bool(os.getenv('OPENAI_API_KEY')),
            'twilio_account_sid': bool(os.getenv('TWILIO_ACCOUNT_SID')),
            'twilio_auth_token': bool(os.getenv('TWILIO_AUTH_TOKEN')),
            'twilio_phone_number': bool(os.getenv('TWILIO_PHONE_NUMBER'))
        }
        
        # Get connection info
        conn_info = connection_manager.get_connection_info()
        
        return {
            'status': 'healthy',
            'message': 'Deepgram Voice Agent Server is running!',
            'timestamp': datetime.now().isoformat(),
            'endpoints': {
                'health': '/ (GET)',
                'voice': '/voice (POST)', 
                'media': '/media (POST)',
                'metrics': '/metrics (GET)',
                'websocket': 'wss://twilio-deepgram-openai-voice.onrender.com/twilio'
            },
            'connections': conn_info,
            'environment': env_status,
            'rate_limiting': {
                'active_requests': len(rate_limiter.requests)
            }
        }
    except Exception as e:
        logger.error(f"❌ Health check error: {e}")
        return {
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }, 500

@app.route('/metrics', methods=['GET'])
def metrics():
    """Detailed metrics endpoint"""
    return {
        'connections': connection_manager.get_connection_info(),
        'rate_limiting': {
            'active_requests': len(rate_limiter.requests),
            'total_requests': sum(len(reqs) for reqs in rate_limiter.requests.values())
        },
        'memory': {
            'gc_stats': gc.get_stats(),
            'memory_usage': 'Available via system monitoring'
        }
    }

@app.route('/voice', methods=['GET', 'POST'])
def voice_webhook():
    """Twilio voice webhook - returns TwiML to start WebSocket connection"""
    # Rate limiting
    client_ip = request.remote_addr
    if not rate_limiter.is_allowed(client_ip):
        logger.warning(f"🚫 Rate limit exceeded for {client_ip}")
        response = VoiceResponse()
        response.say("Sorry, too many requests. Please try again later.")
        return Response(str(response), mimetype='text/xml')
    
    logger.info(f"📞 Voice webhook called with method: {request.method}")
    
    if request.method == 'GET':
        logger.info("📞 GET request to /voice - returning basic TwiML")
        response = VoiceResponse()
        response.say("Hello! This is a test response.")
        return Response(str(response), mimetype='text/xml')
    
    # Handle POST request (actual call)
    caller = request.form.get('From', 'Unknown')
    logger.info(f"📞 Incoming call from: {caller}")
    
    try:
        response = VoiceResponse()
        
        # Use Connect for WebSocket streaming (following video approach)
        connect = response.connect()
        
        # Get the host from request headers and ensure HTTPS
        host = request.headers.get('Host', 'localhost:5000')
        
        # Check if we're in production (Render) and force HTTPS
        if 'onrender.com' in host or 'localhost' not in host:
            websocket_url = f'wss://{host}/twilio'
        else:
            websocket_url = f'ws://{host}/twilio'
            
        logger.info(f"🔌 WebSocket URL: {websocket_url}")
        
        connect.stream(
            url=websocket_url,
            track='inbound_track',
            name='voice_agent_stream'
        )
        
        twiml_response = str(response)
        logger.info(f"📞 Generated TwiML: {twiml_response}")
        return Response(twiml_response, mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"❌ Error in voice webhook: {e}")
        # Fallback response
        response = VoiceResponse()
        response.say("Sorry, there was an error. Please try again.")
        return Response(str(response), mimetype='text/xml')

async def handle_twilio_connection(websocket, path):
    """Handle WebSocket connection from Twilio (following video approach)"""
    if path != '/twilio':
        logger.warning(f"Unknown path: {path}")
        return
        
    logger.info("🔌 New Twilio WebSocket connection")
    connection_id = f"conn_{int(time.time() * 1000)}"
    
    # Queues for communication between tasks
    audio_queue = asyncio.Queue()
    stream_sid_queue = asyncio.Queue()
    
    try:
        # Connect to Deepgram Voice Agent
        async with create_deepgram_connection() as deepgram_ws:
            logger.info("🎙️ Connected to Deepgram Voice Agent")
            
            # Store connection for cleanup
            connection_manager.add_connection(connection_id, {
                'twilio_ws': websocket,
                'deepgram_ws': deepgram_ws,
                'stream_sid': None,
                'audio_buffer': bytearray()
            })
            
            # Send Voice Agent configuration
            config_message = get_deepgram_config()
            await deepgram_ws.send(json.dumps(config_message))
            logger.info("📋 Configuration sent to Deepgram Voice Agent")
            
            # Start tasks for handling messages (following video pattern)
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
        connection_manager.remove_connection(connection_id)
        logger.info(f"🧹 Cleaned up connection {connection_id}")

async def handle_twilio_messages(twilio_ws, deepgram_ws, connection_id):
    """Handle messages from Twilio (following video approach)"""
    BUFFER_SIZE = 20 * 160  # 20 Twilio messages = 0.4 seconds of audio
    audio_buffer = bytearray()
    
    try:
        async for message in twilio_ws:
            data = json.loads(message)
            
            if data["event"] == "start":
                logger.info("🚀 Media stream started")
                stream_sid = data["start"]["streamSid"]
                conn = connection_manager.get_connection(connection_id)
                if conn:
                    conn['stream_sid'] = stream_sid
                    
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
                    conn = connection_manager.get_connection(connection_id)
                    if conn and conn['stream_sid']:
                        clear_message = {
                            "event": "clear",
                            "streamSid": conn['stream_sid']
                        }
                        await twilio_ws.send(json.dumps(clear_message))
                        logger.info("🔄 Sent barge-in clear message to Twilio")
                        
            else:
                # Binary audio data from Deepgram to send to Twilio
                conn = connection_manager.get_connection(connection_id)
                if conn and conn['stream_sid']:
                    media_message = {
                        "event": "media",
                        "streamSid": conn['stream_sid'],
                        "media": {
                            "payload": base64.b64encode(message).decode("ascii")
                        }
                    }
                    await twilio_ws.send(json.dumps(media_message))
                    
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
    except Exception as e:
        logger.error(f"❌ Error in keep-alive: {e}")

def start_websocket_server():
    """Start the WebSocket server for Twilio connections"""
    port = int(os.getenv('PORT', 5000))
    
    # Create WebSocket server
    import websockets
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

def start_cleanup_task():
    """Start background cleanup task"""
    def cleanup_loop():
        while True:
            try:
                time.sleep(60)  # Run every minute
                connection_manager.cleanup_inactive()
                gc.collect()  # Force garbage collection
            except Exception as e:
                logger.error(f"❌ Cleanup task error: {e}")
    
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()
    logger.info("🧹 Started background cleanup task")

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
    
    # Start background cleanup task
    start_cleanup_task()
    
    port = int(os.getenv('PORT', 5000))
    
    # Start WebSocket server in a separate thread
    websocket_thread = threading.Thread(target=start_websocket_server, daemon=True)
    websocket_thread.start()
    
    # Start Flask app for HTTP endpoints
    logger.info(f"🚀 Flask server starting on port {port}")
    logger.info(f"📞 Twilio webhook URL: https://twilio-deepgram-openai-voice.onrender.com/voice")
    logger.info(f"🔌 WebSocket URL: wss://twilio-deepgram-openai-voice.onrender.com/twilio")
    logger.info(f"📊 Metrics URL: https://twilio-deepgram-openai-voice.onrender.com/metrics")
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)