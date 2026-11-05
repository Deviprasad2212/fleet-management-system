-- Fleet Management System - PostgreSQL Schema
-- Run with:  psql -U postgres -d fleet_db -f schema.sql
-- WARNING: this drops and recreates every table.

DROP TABLE IF EXISTS trips CASCADE;
DROP TABLE IF EXISTS requests CASCADE;
DROP TABLE IF EXISTS drivers CASCADE;
DROP TABLE IF EXISTS vehicles CASCADE;
DROP TABLE IF EXISTS users CASCADE;

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'user', 'driver')),
    phone VARCHAR(20) DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE vehicles (
    id SERIAL PRIMARY KEY,
    vehicle_name VARCHAR(100) NOT NULL,
    vehicle_number VARCHAR(50) UNIQUE NOT NULL,
    status VARCHAR(30) DEFAULT 'available' CHECK (status IN ('available', 'assigned', 'maintenance')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE drivers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    license_number VARCHAR(50) UNIQUE NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE requests (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    from_location VARCHAR(200) NOT NULL,
    to_location VARCHAR(200) NOT NULL,
    goods_type VARCHAR(100) NOT NULL,
    status VARCHAR(30) DEFAULT 'pending' CHECK (status IN ('pending', 'assigned', 'completed')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE trips (
    id SERIAL PRIMARY KEY,
    request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    driver_id INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    status VARCHAR(30) DEFAULT 'assigned' CHECK (status IN ('assigned', 'in_progress', 'completed')),
    price NUMERIC(10,2) DEFAULT NULL,
    payment_status VARCHAR(20) DEFAULT 'unpaid' CHECK (payment_status IN ('unpaid', 'paid')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sample data. Demo logins: admin@fleet.com / admin123, alice@example.com / user123, charlie@fleet.com / driver123
-- Passwords are stored as salted PBKDF2 hashes, never as plain text.
INSERT INTO users (name, email, password, role, phone) VALUES
('Admin', 'admin@fleet.com', 'pbkdf2:sha256:1000000$b4xo3mK6pl1uGlaz$7f18a9a553ce80c0dc4861fb44e2956652690864200e506bfe78c733cda27b0e', 'admin', '9000000000'),
('Alice Johnson', 'alice@example.com', 'pbkdf2:sha256:1000000$c4mhVQ9CQUelTA6I$926024931a71ab8b6fe53c615a36bbf960caa325fba937facfd367a5e4401ce1', 'user', '9111111111'),
('Bob Smith', 'bob@example.com', 'pbkdf2:sha256:1000000$JuNzH0w1Uq2ejnmw$87a49e1e5336079558e7a3ec632b15e9e770f390b0e56c102774343a912ac38e', 'user', '9222222222'),
('Charlie Driver', 'charlie@fleet.com', 'pbkdf2:sha256:1000000$BZ7y2vvqdWCrLaq5$6a50a13eebc6791d867fccca6ae485a91a49cfa81551fd5f16c6b4cdf48278a7', 'driver', '9876543210'),
('Diana Driver', 'diana@fleet.com', 'pbkdf2:sha256:1000000$3iQpZCaFBc4DqgUR$67f03f3ecd7217f57133bc494789d3c9fe79a0f668c4f16194c3dbb2657d48fd', 'driver', '9876543211');

INSERT INTO vehicles (vehicle_name, vehicle_number, status) VALUES
('Tata Ace', 'MH-12-AB-1234', 'available'),
('Ashok Leyland', 'MH-14-CD-5678', 'available'),
('Mahindra Bolero', 'MH-09-EF-9012', 'available');

INSERT INTO drivers (name, phone, license_number, user_id) VALUES
('Charlie Driver', '9876543210', 'DL-2023-001', (SELECT id FROM users WHERE email='charlie@fleet.com')),
('Diana Driver', '9876543211', 'DL-2023-002', (SELECT id FROM users WHERE email='diana@fleet.com'));

INSERT INTO requests (user_id, from_location, to_location, goods_type, status) VALUES
((SELECT id FROM users WHERE email='alice@example.com'), 'Pune', 'Mumbai', 'Electronics', 'pending'),
((SELECT id FROM users WHERE email='bob@example.com'), 'Nashik', 'Pune', 'Furniture', 'pending');
