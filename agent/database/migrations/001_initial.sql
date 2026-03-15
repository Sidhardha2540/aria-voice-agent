-- Initial schema for Aria voice agent (SQLite).
-- For PostgreSQL, use a separate migration or adapt types (SERIAL, etc.).

CREATE TABLE IF NOT EXISTS doctors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    specialization TEXT NOT NULL,
    available_days TEXT NOT NULL,
    slot_duration_minutes INTEGER DEFAULT 30
);

CREATE TABLE IF NOT EXISTS appointments (
    id TEXT PRIMARY KEY,
    doctor_id INTEGER NOT NULL,
    patient_name TEXT NOT NULL,
    patient_phone TEXT NOT NULL,
    appointment_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'booked',
    created_at TEXT NOT NULL,
    notes TEXT DEFAULT '',
    FOREIGN KEY (doctor_id) REFERENCES doctors(id)
);

CREATE TABLE IF NOT EXISTS callers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone_number TEXT UNIQUE NOT NULL,
    name TEXT DEFAULT '',
    last_call_at TEXT NOT NULL,
    preferences TEXT DEFAULT '{}',
    call_count INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clinic_info (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
