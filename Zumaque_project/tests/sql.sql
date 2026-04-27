-- SCRIPT DE CREACIÓN COMPLETO PARA ZUMAQUE PROJECT

-- 1. Tabla de Usuarios para Login
CREATE TABLE usuario (
    ID INT IDENTITY(1,1) PRIMARY KEY,
    username NVARCHAR(50) NOT NULL UNIQUE,
    password NVARCHAR(255) NOT NULL
);

-- 2. Tabla para el contador de dinero global
CREATE TABLE Money (
    ID INT IDENTITY(1,1) PRIMARY KEY,
    amount DECIMAL(18,2) DEFAULT 0,
    Tasa DECIMAL(18,2) DEFAULT 0,
    last_updated DATETIME DEFAULT GETDATE()
);
-- Inicializamos el contador en 0
INSERT INTO Money (amount) VALUES (0);

-- 3. Tabla de Cuentas (Gestión de deudas y pagos mensuales)
CREATE TABLE accounts (
    ID NVARCHAR(50) PRIMARY KEY, -- ID ingresado manualmente
    accType NVARCHAR(50),
    concept NVARCHAR(100),
    reference NVARCHAR(100),
    Total DECIMAL(18,2),        -- Monto total de la deuda/cuenta
    total DECIMAL(18,2),        -- Saldo restante (balance actual)
    enddate DATE,
    status NVARCHAR(20),
    permanency INT DEFAULT 0,
    is_monthly BIT DEFAULT 0,
    monthly_amount DECIMAL(18,2),
    last_payment_date DATE,
    next_payment_date DATE,
    reminder_sent BIT DEFAULT 0
);

-- 4. Tabla de Historial de Pagos
CREATE TABLE payments_log (
    payID INT IDENTITY(1,1) PRIMARY KEY,
    accountID NVARCHAR(50) REFERENCES accounts(ID),
    amount_paid DECIMAL(18,2),
    payment_date DATE,
    method NVARCHAR(50)
);

-- 5. Tabla de Notificaciones por Correo
CREATE TABLE email_notifications (
    ID INT IDENTITY(1,1) PRIMARY KEY,
    account_id NVARCHAR(50),
    reminder_type NVARCHAR(50),
    sent_date DATETIME DEFAULT GETDATE(),
    status NVARCHAR(20) DEFAULT 'sent'
);