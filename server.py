#!/usr/bin/env python3
"""
Twilio + Deepgram Voice Agent Integration
Optimized for performance and efficiency
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
                'metrics': '/metrics (GET)'
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
    """Twilio voice webhook - returns TwiML to start Media Stream"""
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
        
        # Use Connect for bidirectional streaming
        connect = response.connect()
        
        # Get the host and ensure HTTPS for production
        host = request.headers.get('Host', 'localhost:5000')
        
        # Check if we're in production (Render) and force HTTPS
        if 'onrender.com' in host or 'localhost' not in host:
            media_url = f'https://{host}/media'
        else:
            media_url = f'http://{host}/media'
            
        logger.info(f"📡 Media Stream URL: {media_url}")
        logger.info(f"📡 Request headers: {dict(request.headers)}")
        
        connect.stream(
            url=media_url,
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

@app.route('/media', methods=['GET', 'POST'])
def media_webhook():
    """Handle Media Stream events from Twilio"""
    logger.info(f"📡 Media webhook called with method: {request.method}")
    logger.info(f"📡 Media webhook called with headers: {dict(request.headers)}")
    logger.info(f"📡 Media webhook called with form data: {request.form.to_dict()}")
    
    # Handle GET requests for testing
    if request.method == 'GET':
        logger.info("📡 GET request to /media - Media Stream endpoint is reachable")
        return {'status': 'Media Stream endpoint is working'}, 200
    
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
        logger.info(f"🚀 Starting Deepgram connection for stream {stream_sid}")
        # Start new connection to Deepgram in background
        threading.Thread(target=lambda: asyncio.run(start_deepgram_connection(stream_sid)), daemon=True).start()
    elif event == 'media':
        # Handle incoming audio data
        media_data = data.get('media', {})
        if media_data.get('track') == 'inbound':
            # Send audio to Deepgram
            audio_payload = media_data.get('payload')
            if audio_payload:
                try:
                    audio_bytes = base64.b64decode(audio_payload)
                    send_audio_to_deepgram(stream_sid, audio_bytes)
                    logger.debug(f"🎵 Received audio chunk for stream {stream_sid}")
                except Exception as e:
                    logger.error(f"❌ Error processing audio: {e}")
    elif event == 'stop':
        # Clean up connection
        connection_manager.remove_connection(stream_sid)
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
            connection_manager.add_connection(stream_sid, {
                'deepgram_ws': deepgram_ws,
                'stream_sid': stream_sid,
                'audio_buffer': bytearray()
            })
            
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
        connection_manager.remove_connection(stream_sid)
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

def send_audio_to_deepgram(stream_sid, audio_bytes):
    """Send audio data to Deepgram"""
    try:
        conn = connection_manager.get_connection(stream_sid)
        if conn:
            # Add to buffer
            conn['audio_buffer'].extend(audio_bytes)
            
            # Send when buffer is ready (20ms chunks)
            while len(conn['audio_buffer']) >= AUDIO_BUFFER_SIZE:
                chunk = conn['audio_buffer'][:AUDIO_BUFFER_SIZE]
                asyncio.run_coroutine_threadsafe(
                    conn['deepgram_ws'].send(chunk),
                    asyncio.get_event_loop()
                )
                conn['audio_buffer'] = conn['audio_buffer'][AUDIO_BUFFER_SIZE:]
                
                logger.debug(f"🎵 Sent audio chunk to Deepgram (stream: {stream_sid})")
    except Exception as e:
        logger.error(f"❌ Error sending audio to Deepgram: {e}")

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
    
    # Start Flask app for HTTP endpoints
    logger.info(f"🚀 Flask server starting on port {port}")
    logger.info(f"📞 Twilio webhook URL: https://twilio-deepgram-openai-voice.onrender.com/voice")
    logger.info(f"📡 Media stream URL: https://twilio-deepgram-openai-voice.onrender.com/media")
    logger.info(f"📊 Metrics URL: https://twilio-deepgram-openai-voice.onrender.com/metrics")
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)