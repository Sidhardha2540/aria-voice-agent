-- Prevent double-booking the same slot for active (booked) appointments.
-- SQLite partial unique index (Postgres: use partial index with same predicate).

CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_booked_slot
ON appointments (doctor_id, appointment_date, start_time)
WHERE status = 'booked';
