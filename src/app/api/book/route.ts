import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseAnonKey = process.env.SUPABASE_SERVICE_KEY || '';
const supabase = createClient(supabaseUrl, supabaseAnonKey);

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { customerName, customerPhone, barberName, service, appointmentDate } = body;

    // Validate required fields
    if (!customerName || !customerPhone || !barberName || !service || !appointmentDate) {
      return NextResponse.json(
        { success: false, error: 'Missing required fields' },
        { status: 400 }
      );
    }

    // Create booking
    const { data: booking, error } = await supabase
      .from('bookings')
      .insert([
        {
          customer_name: customerName,
          customer_phone: customerPhone,
          barber_name: barberName,
          service: service,
          appointment_date: appointmentDate,
          status: 'confirmed'
        }
      ])
      .select()
      .single();

    if (error) {
      console.error('Booking creation error:', error);
      return NextResponse.json(
        { success: false, error: error.message },
        { status: 500 }
      );
    }

    // Send SMS confirmation if phone number is available
    // Fire-and-forget to not block the response
    if (booking.customer_phone) {
      try {
        const appUrl = process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000';
        fetch(`${appUrl}/api/notifications`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            type: 'booking_confirmation',
            bookingId: booking.id,
            phone: booking.customer_phone
          })
        }).catch(console.error);
      } catch (smsError) {
        console.error('SMS notification error:', smsError);
        // Don't fail the booking if SMS fails
      }
    }

    return NextResponse.json(
      { 
        success: true, 
        booking,
        message: 'Booking confirmed successfully' 
      },
      { status: 201 }
    );
  } catch (error) {
    console.error('Book API error:', error);
    return NextResponse.json(
      { success: false, error: 'Internal server error' },
      { status: 500 }
    );
  }
}
