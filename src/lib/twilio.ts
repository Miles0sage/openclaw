import { createClient } from '@supabase/supabase-js';

// Twilio SDK
let twilioClient: any = null;

// Initialize Twilio client
function getTwilioClient() {
  if (twilioClient) {
    return twilioClient;
  }

  const accountSid = process.env.TWILIO_ACCOUNT_SID;
  const authToken = process.env.TWILIO_AUTH_TOKEN;
  const phoneNumber = process.env.TWILIO_PHONE_NUMBER;

  if (!accountSid || !authToken || !phoneNumber) {
    console.warn('Twilio credentials not configured. Using mock mode.');
    return null;
  }

  try {
    twilioClient = {
      accountSid,
      authToken,
      phoneNumber,
      messages: {
        create: async (params: any) => {
          // In production, this would use the real Twilio SDK
          // For now, we'll implement a mock that simulates the API
          return {
            sid: `SM${Date.now()}`,
            status: 'queued',
            to: params.to,
            body: params.body,
            dateCreated: new Date().toISOString()
          };
        }
      }
    };
    return twilioClient;
  } catch (error) {
    console.error('Failed to initialize Twilio client:', error);
    return null;
  }
}

// Mock mode implementation
function getMockTwilioClient() {
  return {
    accountSid: 'MOCK_ACCOUNT_SID',
    authToken: 'MOCK_AUTH_TOKEN',
    phoneNumber: process.env.TWILIO_PHONE_NUMBER || '+1234567890',
    messages: {
      create: async (params: any) => {
        console.log(`[MOCK TWILIO] Sending SMS to ${params.to}: ${params.body}`);
        return {
          sid: `MOCK_${Date.now()}`,
          status: 'queued',
          to: params.to,
          body: params.body,
          dateCreated: new Date().toISOString()
        };
      }
    }
  };
}

// Get the appropriate client (real or mock)
function getTwilioClientInstance() {
  const realClient = getTwilioClient();
  if (realClient) {
    return realClient;
  }
  return getMockTwilioClient();
}

// Low-level SMS sender
export async function sendSMS(to: string, body: string): Promise<{
  success: boolean;
  messageSid?: string;
  error?: string;
  providerResponse?: Record<string, any>;
}> {
  try {
    const client = getTwilioClientInstance();
    
    if (!client) {
      return {
        success: false,
        error: 'Twilio client not initialized'
      };
    }

    const message = await client.messages.create({
      to,
      from: client.phoneNumber,
      body
    });

    // Log to notification_history
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
    const supabaseAnonKey = process.env.SUPABASE_SERVICE_KEY || '';
    const supabase = createClient(supabaseUrl, supabaseAnonKey);
    
    await supabase.from('notification_history').insert({
      type: 'sms',
      status: 'sent',
      sent_at: new Date().toISOString(),
      provider_response: message
    });

    return {
      success: true,
      messageSid: message.sid,
      providerResponse: message
    };
  } catch (error: any) {
    console.error('SMS sending error:', error);
    
    // Log failure to notification_history
    try {
      const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
      const supabaseAnonKey = process.env.SUPABASE_SERVICE_KEY || '';
      const supabase = createClient(supabaseUrl, supabaseAnonKey);
      
      await supabase.from('notification_history').insert({
        type: 'sms',
        status: 'failed',
        error_message: error.message,
        provider_response: { error: error.message }
      });
    } catch (logError) {
      console.error('Failed to log SMS failure:', logError);
    }
    
    return {
      success: false,
      error: error.message
    };
  }
}

// High-level booking confirmation SMS
export async function sendBookingConfirmation(booking: {
  id: string;
  customer_name: string;
  barber_name: string;
  service: string;
  appointment_date: string;
  customer_phone: string;
}): Promise<{ success: boolean; messageSid?: string; error?: string }> {
  if (!booking.customer_phone) {
    console.warn(`No phone number for booking ${booking.id}, skipping SMS`);
    return { success: true }; // Not an error, just skip
  }

  const date = new Date(booking.appointment_date);
  const messageBody = `Hi ${booking.customer_name}, you're booked at ${booking.barber_name} for ${booking.service} on ${date.toLocaleDateString()} at ${date.toLocaleTimeString()}. Reply STOP to opt out.`;

  return sendSMS(booking.customer_phone, messageBody);
}

// Reminder SMS
export async function sendReminder(
  booking: {
    id: string;
    customer_name: string;
    barber_name: string;
    service: string;
    appointment_date: string;
    customer_phone: string;
  },
  hoursBefore: number = 24
): Promise<{ success: boolean; messageSid?: string; error?: string }> {
  if (!booking.customer_phone) {
    console.warn(`No phone number for booking ${booking.id}, skipping SMS reminder`);
    return { success: true };
  }

  const date = new Date(booking.appointment_date);
  let messageBody = '';

  if (hoursBefore === 24) {
    messageBody = `Reminder: You have a ${booking.service} appointment with ${booking.barber_name} tomorrow (${date.toLocaleDateString()}) at ${date.toLocaleTimeString()}. See you then! Reply STOP to opt out.`;
  } else if (hoursBefore === 1) {
    messageBody = `Heads up: Your ${booking.service} with ${booking.barber_name} is in 1 hour at ${date.toLocaleTimeString()}. Reply STOP to opt out.`;
  } else {
    messageBody = `Reminder: You have a ${booking.service} appointment with ${booking.barber_name} in ${hoursBefore} hours (${date.toLocaleDateString()} at ${date.toLocaleTimeString()}). Reply STOP to opt out.`;
  }

  return sendSMS(booking.customer_phone, messageBody);
}
