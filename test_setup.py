#!/usr/bin/env python3
"""
Test script to verify environment setup and API connectivity
"""

import os
import sys
import asyncio
from dotenv import load_dotenv

def test_environment():
    """Test environment variables"""
    print("🧪 Testing Environment Setup...")
    load_dotenv()
    
    required_vars = [
        'TWILIO_ACCOUNT_SID',
        'TWILIO_AUTH_TOKEN', 
        'TWILIO_PHONE_NUMBER',
        'DEEPGRAM_API_KEY',
        'OPENAI_API_KEY'
    ]
    
    all_tests_passed = True
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"   ✅ {var}: Set (length: {len(value)})")
        else:
            print(f"   ❌ {var}: Missing")
            all_tests_passed = False
    
    return all_tests_passed

async def test_deepgram():
    """Test Deepgram API connectivity"""
    print("\n🎙️ Testing Deepgram API...")
    
    try:
        import websockets
        
        api_key = os.getenv('DEEPGRAM_API_KEY')
        if not api_key:
            print("   ❌ Deepgram: No API key found")
            return False
            
        # Test basic connectivity by attempting WebSocket connection
        try:
            # Try to connect to Deepgram Voice Agent endpoint
            uri = "wss://agent.deepgram.com/agent"
            async with websockets.connect(
                uri,
                subprotocols=["token", api_key],
                ping_interval=None,
                ping_timeout=None
            ) as websocket:
                print("   ✅ Deepgram: Voice Agent connection successful")
                return True
        except Exception as e:
            print(f"   ❌ Deepgram: Connection failed - {e}")
            return False
            
    except ImportError as e:
        print(f"   ❌ Deepgram: WebSockets not installed - {e}")
        return False
    except Exception as e:
        print(f"   ❌ Deepgram: {e}")
        return False

def test_twilio():
    """Test Twilio API connectivity"""
    print("\n📞 Testing Twilio API...")
    
    try:
        from twilio.rest import Client
        
        account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        
        if not account_sid or not auth_token:
            print("   ❌ Twilio: Missing credentials")
            return False
        
        # Validate SID format
        if not account_sid.startswith('AC'):
            print(f"   ❌ Twilio: Invalid Account SID format (should start with 'AC')")
            return False
        
        client = Client(account_sid, auth_token)
        
        # Test API connectivity
        account = client.api.accounts(account_sid).fetch()
        print(f"   ✅ Twilio: Connected successfully (Account: {account.friendly_name})")
        return True
        
    except ImportError as e:
        print(f"   ❌ Twilio: SDK not installed - {e}")
        return False
    except Exception as e:
        print(f"   ❌ Twilio: {e}")
        return False

def test_openai():
    """Test OpenAI API connectivity"""
    print("\n🤖 Testing OpenAI API...")
    
    try:
        import openai
        
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            print("   ❌ OpenAI: No API key found")
            return False
        
        # Initialize client
        client = openai.OpenAI(api_key=api_key)
        
        # Test API connectivity with a simple completion
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=5
        )
        
        print(f"   ✅ OpenAI: Connected successfully")
        return True
        
    except ImportError as e:
        print(f"   ❌ OpenAI: SDK not installed - {e}")
        return False
    except Exception as e:
        print(f"   ❌ OpenAI: {e}")
        return False

def test_dependencies():
    """Test required Python packages"""
    print("\n📦 Testing Dependencies...")
    
    dependencies = [
        'flask',
        'twilio', 
        'websockets',
        'dotenv',  # python-dotenv imports as 'dotenv'
        'openai'
    ]
    
    all_deps_ok = True
    
    for dep in dependencies:
        try:
            __import__(dep.replace('-', '_'))
            print(f"   ✅ {dep}: Installed")
        except ImportError:
            print(f"   ❌ {dep}: Not installed")
            all_deps_ok = False
    
    return all_deps_ok

async def main():
    """Run all tests"""
    print("🚀 Voice Agent Setup Test\n")
    
    # Test environment
    env_ok = test_environment()
    
    # Test dependencies
    deps_ok = test_dependencies()
    
    if not env_ok or not deps_ok:
        print("\n❌ Basic setup issues found. Please fix before testing APIs.")
        return
    
    # Test APIs
    deepgram_ok = await test_deepgram()
    twilio_ok = test_twilio()
    openai_ok = test_openai()
    
    print("\n" + "="*50)
    
    if env_ok and deps_ok and deepgram_ok and twilio_ok and openai_ok:
        print("🎉 All tests passed! Your Voice Agent is ready to run.")
        print("\nNext steps:")
        print("1. Run: python server.py")
        print("2. Configure Twilio webhook URL")
        print("3. Test by calling your Twilio number")
    else:
        print("❌ Some tests failed. Please check the issues above.")
        
    print("="*50)

if __name__ == "__main__":
    asyncio.run(main())