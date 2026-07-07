USE parking_db;

CREATE TABLE IF NOT EXISTS pricing_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    hourly_rate DECIMAL(10,2) NOT NULL DEFAULT 50.00,
    currency VARCHAR(10) DEFAULT 'MXN',
    grace_period_minutes INT DEFAULT 15,
    max_daily_rate DECIMAL(10,2) DEFAULT 200.00
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO pricing_config (hourly_rate, max_daily_rate) VALUES (50.00, 200.00);

CREATE TABLE IF NOT EXISTS parking_spots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    spot_number INT UNIQUE NOT NULL,
    status ENUM('available', 'occupied') DEFAULT 'available',
    `row_number` INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT IGNORE INTO parking_spots (spot_number, `row_number`) VALUES
(1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1),
(7, 2), (8, 2), (9, 2), (10, 2), (11, 2), (12, 2);

CREATE TABLE IF NOT EXISTS parking_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plate_number VARCHAR(20) NOT NULL,
    qr_code VARCHAR(36) NULL,
    spot_id INT NOT NULL,
    entry_time DATETIME NOT NULL,
    exit_time DATETIME NULL,
    duration_minutes INT NULL,
    total_amount DECIMAL(10,2) DEFAULT 0.00,
    status ENUM('active', 'completed') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (spot_id) REFERENCES parking_spots(id) ON DELETE CASCADE,
    INDEX idx_plate (plate_number),
    INDEX idx_qr_code (qr_code),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS event_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plate_number VARCHAR(20),
    event_type ENUM('entry', 'exit', 'error', 'alert') NOT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS revenue_cuts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    today DECIMAL(10,2) NOT NULL DEFAULT 0,
    week DECIMAL(10,2) NOT NULL DEFAULT 0,
    month DECIMAL(10,2) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
