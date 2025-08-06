#!/usr/bin/env node

import 'dotenv/config';

console.log('🧪 Testing Voice AI Setup...\n');

// Test environment variables
const requiredEnvVars = {
  'TWILIO_ACCOUNT_SID': process.env.TWILIO_ACCOUNT_SID,
  'TWILIO_AUTH_TOKEN': process.env.TWILIO_AUTH_TOKEN,
  'TWILIO_PHONE_NUMBER': process.env.TWILIO_PHONE_NUMBER,
  'DEEPGRAM_API_KEY': process.env.DEEPGRAM_API_KEY,
  'OPENAI_API_KEY': process.env.OPENAI_API_KEY,
};

console.log('📋 Environment Variables:');
let allValid = true;

for (const [key, value] of Object.entries(requiredEnvVars)) {
  if (!value || value.includes('xxx')) {
    console.log(`   ❌ ${key}: Missing or template value`);
    allValid = false;
  } else {
    // Mask sensitive values
    const masked = value.length > 8 
      ? value.substring(0, 4) + '***' + value.substring(value.length - 4)
      : '***';
    console.log(`   ✅ ${key}: ${masked}`);
  }
}

console.log('');

// Test API connectivity
async function testAPIs() {
  let apiTests = [];

  // Test Twilio
  try {
    const twilio = (await import('twilio')).default;
    const client = twilio(process.env.TWILIO_ACCOUNT_SID, process.env.TWILIO_AUTH_TOKEN);
    await client.api.account.fetch();
    console.log('   ✅ Twilio: Connected successfully');
  } catch (error) {
    console.log(`   ❌ Twilio: ${error.message}`);
    allValid = false;
  }

  // Test Deepgram
  try {
    const { createClient } = await import('@deepgram/sdk');
    const deepgram = createClient(process.env.DEEPGRAM_API_KEY);
    await deepgram.projects.list();
    console.log('   ✅ Deepgram: Connected successfully');
  } catch (error) {
    console.log(`   ❌ Deepgram: ${error.message}`);
    allValid = false;
  }

  // Test OpenAI
  try {
    const OpenAI = (await import('openai')).default;
    const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
    await openai.models.list();
    console.log('   ✅ OpenAI: Connected successfully');
  } catch (error) {
    console.log(`   ❌ OpenAI: ${error.message}`);
    allValid = false;
  }
}

if (allValid) {
  console.log('🔌 Testing API Connectivity:');
  await testAPIs();
} else {
  console.log('⚠️  Skipping API tests due to missing environment variables');
}

console.log('');

// Test dependencies
console.log('📦 Checking Dependencies:');
const requiredPackages = [
  'express',
  'ws', 
  'twilio',
  '@deepgram/sdk',
  'openai',
  'dotenv'
];

for (const pkg of requiredPackages) {
  try {
    await import(pkg);
    console.log(`   ✅ ${pkg}: Installed`);
  } catch (error) {
    console.log(`   ❌ ${pkg}: Not installed`);
    allValid = false;
  }
}

console.log('');

// Final status
if (allValid) {
  console.log('🎉 Setup test passed! Ready to run the voice AI server.');
  console.log('');
  console.log('Next steps:');
  console.log('1. Run: npm start');
  console.log('2. Configure Twilio webhook URL');
  console.log('3. Call your Twilio number to test');
} else {
  console.log('❌ Setup test failed. Please fix the issues above.');
  process.exit(1);
}