import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseAnonKey = process.env.SUPABASE_SERVICE_KEY || '';
const supabase = createClient(supabaseUrl, supabaseAnonKey);

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { type, bookingId, phone, hoursBefore } = body;

    // Validate required fields
    if (!type || !bookingId) {
      return NextResponse.json(
        { success: false, error: 'Missing required fields: type and bookingId' },
        { status: 400 }
      );
    }

    // Validate phone for SMS types
    if ((type === 'sms' || type === 'booking_confirmation' || type === 'reminder') && !phone) {
      return NextResponse.json(
        { success: false, error: 'Phone number required for SMS notifications' },
        { status: 400 }
      );
    }

    // Get booking details
    const { data: booking, error: bookingError } = await supabase
      .from('bookings')
      .select('*')
      .eq('id', bookingId)
      .single();

    if (bookingError || !booking) {
      return NextResponse.json(
        { success: false, error: 'Booking not found' },
        { status: 404 }
      );
    }

    // Route to appropriate notification handler
    let result;
    
    if (type === 'booking_confirmation') {
      const { sendBookingConfirmation } = await import('@/lib/twilio');
      result = await sendBookingConfirmation({
        id: booking.id,
        customer_name: booking.customer_name,
        barber_name: booking.barber_name,
        service: booking.service,
        appointment_date: booking.appointment_date,
        customer_phone: phone
      });
    } else if (type === 'reminder') {
      const { sendReminder } = await import('@/lib/twilio');
      result = await sendReminder({
        id: booking.id,
        customer_name: booking.customer_name,
        barber_name: booking.barber_name,
        service: booking.service,
        appointment_date: booking.appointment_date,
        customer_phone: phone
      }, hoursBefore || 24);
    } else if (type === 'sms') {
      const { sendSMS } = await import('@/lib/twilio');
      // For generic SMS, we need to construct the message body
      const messageBody = body.message || 'You have a new notification.';
      result = await sendSMS(phone, messageBody);
    } else {
      // Handle email/push notifications (existing logic)
      if (type === 'email') {
        // Email sending logic would go here
        result = { success: true };
      } else if (type === 'push') {
        // Push notification logic would go here
        result = { success: true };
      } else {
        return NextResponse.json(
          { success: false, error: 'Invalid notification type' },
          { status: 400 }
        );
      }
    }

    // Log to notification_history
    if (result) {
      await supabase.from('notification_history').insert({
        booking_id: bookingId,
        type: type === 'booking_confirmation' || type === 'reminder' ? 'sms' : type,
        status: result.success ? 'sent' : 'failed',
        sent_at: result.success ? new Date().toISOString() : null,
        error_message: result.error || null,
        provider_response: result.providerResponse || (result.success ? { success: true } : { error: result.error })
      });
    }

    return NextResponse.json({
      success: result?.success ?? false,
      messageSid: result?.messageSid,
      error: result?.error
    });
  } catch (error) {
    console.error('Notification API error:', error);
    return NextResponse.json(
      { success: false, error: 'Internal server error' },
      { status: 500 }
    );
  }
}
