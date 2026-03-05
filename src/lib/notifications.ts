import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseAnonKey = process.env.SUPABASE_SERVICE_KEY || '';
const supabase = createClient(supabaseUrl, supabaseAnonKey);

export interface Notification {
  id: string;
  booking_id: string;
  type: 'email' | 'push' | 'sms';
  status: 'pending' | 'sent' | 'failed';
  sent_at: string | null;
  error_message: string | null;
  provider_response: Record<string, any> | null;
}

export async function sendNotification(
  type: 'email' | 'push' | 'sms',
  bookingId: string,
  data: Record<string, any>
): Promise<{ success: boolean; messageSid?: string; error?: string }> {
  try {
    // For SMS notifications, we'll handle them separately
    if (type === 'sms') {
      // Import Twilio functions when needed
      const { sendSMS } = await import('./twilio');
      
      const phone = data.phone;
      if (!phone) {
        return { success: false, error: 'Phone number required for SMS' };
      }
      
      let messageBody = '';
      if (data.type === 'booking_confirmation') {
        messageBody = `Hi ${data.customerName}, you're booked at ${data.barberName} for ${data.service} on ${data.date} at ${data.time}. Reply STOP to opt out.`;
      } else if (data.type === 'reminder') {
        const hoursBefore = data.hoursBefore || 24;
        if (hoursBefore === 24) {
          messageBody = `Reminder: You have a ${data.service} appointment with ${data.barberName} tomorrow (${data.date}) at ${data.time}. See you then! Reply STOP to opt out.`;
        } else if (hoursBefore === 1) {
          messageBody = `Heads up: Your ${data.service} with ${data.barberName} is in 1 hour at ${data.time}. Reply STOP to opt out.`;
        }
      }
      
      const result = await sendSMS(phone, messageBody);
      
      // Log to notification_history
      await supabase.from('notification_history').insert({
        booking_id: bookingId,
        type: 'sms',
        status: result.success ? 'sent' : 'failed',
        sent_at: result.success ? new Date().toISOString() : null,
        error_message: result.error || null,
        provider_response: result.providerResponse || null
      });
      
      return result;
    }
    
    // Existing email/push notification logic
    if (type === 'email') {
      // Email sending logic would go here
      return { success: true };
    } else if (type === 'push') {
      // Push notification logic would go here
      return { success: true };
    }
    
    return { success: false, error: 'Unknown notification type' };
  } catch (error) {
    console.error('Notification error:', error);
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
  }
}

export async function sendBookingConfirmation(booking: any) {
  return sendNotification(
    'sms',
    booking.id,
    {
      type: 'booking_confirmation',
      customerName: booking.customer_name,
      barberName: booking.barber_name,
      service: booking.service,
      date: new Date(booking.appointment_date).toLocaleDateString(),
      time: new Date(booking.appointment_date).toLocaleTimeString(),
      phone: booking.customer_phone
    }
  );
}

export async function sendReminder(booking: any, hoursBefore: number = 24) {
  return sendNotification(
    'sms',
    booking.id,
    {
      type: 'reminder',
      hoursBefore,
      customerName: booking.customer_name,
      barberName: booking.barber_name,
      service: booking.service,
      date: new Date(booking.appointment_date).toLocaleDateString(),
      time: new Date(booking.appointment_date).toLocaleTimeString(),
      phone: booking.customer_phone
    }
  );
}
