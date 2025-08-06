#!/bin/bash

# Voice AI Setup Script
echo "🎙️ Setting up Twilio + Deepgram + OpenAI Voice AI..."

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 18+ first."
    echo "   Visit: https://nodejs.org"
    exit 1
fi

# Check Node.js version
NODE_VERSION=$(node -v | cut -d 'v' -f 2 | cut -d '.' -f 1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "❌ Node.js version 18+ required. Current version: $(node -v)"
    exit 1
fi

echo "✅ Node.js $(node -v) detected"

# Install dependencies
echo "📦 Installing dependencies..."
npm install

if [ $? -ne 0 ]; then
    echo "❌ Failed to install dependencies"
    exit 1
fi

echo "✅ Dependencies installed"

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp env.example .env
    echo "⚠️  Please edit .env file with your API keys before running the server"
else
    echo "✅ .env file already exists"
fi

# Check if required environment variables are set
echo "🔍 Checking environment configuration..."

source .env 2>/dev/null || true

MISSING_VARS=()

if [ -z "$TWILIO_ACCOUNT_SID" ] || [ "$TWILIO_ACCOUNT_SID" = "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" ]; then
    MISSING_VARS+=("TWILIO_ACCOUNT_SID")
fi

if [ -z "$TWILIO_AUTH_TOKEN" ] || [ "$TWILIO_AUTH_TOKEN" = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" ]; then
    MISSING_VARS+=("TWILIO_AUTH_TOKEN")
fi

if [ -z "$TWILIO_PHONE_NUMBER" ] || [ "$TWILIO_PHONE_NUMBER" = "+1234567890" ]; then
    MISSING_VARS+=("TWILIO_PHONE_NUMBER")
fi

if [ -z "$DEEPGRAM_API_KEY" ] || [[ "$DEEPGRAM_API_KEY" == dg_* ]]; then
    if [ "$DEEPGRAM_API_KEY" = "dg_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" ]; then
        MISSING_VARS+=("DEEPGRAM_API_KEY")
    fi
fi

if [ -z "$OPENAI_API_KEY" ] || [[ "$OPENAI_API_KEY" == sk-* ]]; then
    if [ "$OPENAI_API_KEY" = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" ]; then
        MISSING_VARS+=("OPENAI_API_KEY")
    fi
fi

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo "⚠️  Missing or template values for environment variables:"
    for var in "${MISSING_VARS[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "📋 Please update these in your .env file:"
    echo "   1. Twilio Console: https://console.twilio.com"
    echo "   2. Deepgram Console: https://developers.deepgram.com"
    echo "   3. OpenAI Console: https://platform.openai.com"
    echo ""
else
    echo "✅ All environment variables configured"
fi

# Create logs directory
mkdir -p logs
echo "✅ Logs directory created"

echo ""
echo "🚀 Setup complete!"
echo ""
echo "Next steps:"
echo "1. Update .env with your API keys (if not already done)"
echo "2. Configure Twilio webhook: https://your-domain.com/voice"
echo "3. Run: npm start"
echo "4. Test by calling your Twilio number"
echo ""
echo "For deployment options, see README.md"