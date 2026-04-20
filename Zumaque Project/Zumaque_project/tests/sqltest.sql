CREATE TABLE usuario (
    ID INT PRIMARY KEY IDENTITY(1,1),
    username VARCHAR(255) NOT NULL,
    password VARCHAR(255) NOT NULL

);

CREATE TABLE accounts (
    ID INT PRIMARY KEY,
    accType VARCHAR(64) NOT NULL,    
    concept VARCHAR(255) NOT NULL,   
    reference VARCHAR(255) NOT NULL, 
    Total FLOAT NOT NULL,
    enddate DATE NOT NULL,
    status VARCHAR(64) NOT NULL DEFAULT 'pendiente'
    CHECK (status IN ('pendiente', 'pagado', 'parcial', 'vencido', 'cancelado', 'retrasado', 'extendido'))
);


CREATE TABLE payments_log (
    payID INT PRIMARY KEY IDENTITY(1,1),
    accountID INT NOT NULL,
    amount_paid FLOAT NOT NULL,
    payment_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    method VARCHAR(50), 
    FOREIGN KEY (accountID) REFERENCES accounts(ID) ON DELETE CASCADE
);

CREATE TABLE Money (
    ID INT PRIMARY KEY IDENTITY(1,1),
    amount FLOAT NOT NULL,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);