import dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, request, jsonify, render_template, redirect, url_for, make_response, flash
import jwt
import pyodbc 
import datetime
from dotenv import load_dotenv
import os
from functools import wraps

load_dotenv(override=True)
SECRET_KEY = os.getenv('SECRET_KEY')

app = Flask(__name__)
app.secret_key = SECRET_KEY

def create_token(user_id):
    payload = {
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=3),
        'iat': datetime.datetime.utcnow()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

def decode_token(token):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        return payload['user_id']
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
def verify_token(token):
    user_id = decode_token(token)
    return user_id is not None

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.cookies.get('token')
        if not token or not verify_token(token):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def ensure_money_record():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT amount FROM Money WHERE ID = 1")
        row = cursor.fetchone()
        if row is None:
            cursor.execute("IF OBJECT_ID('dbo.Money', 'U') IS NULL CREATE TABLE Money (ID INT IDENTITY(1,1) PRIMARY KEY, amount DECIMAL(18,2) DEFAULT 0)")
            cursor.execute("INSERT INTO Money (amount) VALUES (0)")
            conn.commit()
            return 0
        return row[0] if row[0] is not None else 0
    except pyodbc.Error:
        cursor.execute("IF OBJECT_ID('dbo.Money', 'U') IS NULL CREATE TABLE Money (ID INT IDENTITY(1,1) PRIMARY KEY, amount DECIMAL(18,2) DEFAULT 0)")
        conn.commit()
        cursor.execute("INSERT INTO Money (amount) VALUES (0)")
        conn.commit()
        return 0
    finally:
        conn.close()

@app.context_processor
def inject_money_counter():
    total_money = 0
    try:
        total_money = ensure_money_record()
    except Exception:
        total_money = 0
    return {'money_counter': total_money}


def parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


def format_spanish_date(value):
    if not value:
        return ""
    if isinstance(value, datetime.datetime):
        value = value.date()
    if isinstance(value, datetime.date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, str):
        parsed = parse_date(value)
        return parsed.strftime("%d/%m/%Y") if parsed else value
    return str(value)


@app.template_filter('spanish_date')
def spanish_date(value):
    return format_spanish_date(value)


@app.template_filter('iso_date')
def iso_date(value):
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else ""


# Función para establecer conexión con SQL Server
def get_db_connection():
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.getenv('DB_SERVER')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASSWORD')}"
    )
    return pyodbc.connect(conn_str)

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        input_username = request.form.get('username')
        input_password = request.form.get('password')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ID, password FROM usuario WHERE username = ?", (input_username,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user.password, input_password):
            token = create_token(user.ID)
            # Redirigir y establecer la cookie con el token
            response = make_response(redirect(url_for('index_accounts')))
            # La cookie expira en 3 horas coincidiendo con el token
            response.set_cookie('token', token, httponly=True, max_age=10800)
            return response
        else:
            # En caso de error, podrías usar flash() o pasar un error al template
            return render_template('login.html', error="Usuario o contraseña incorrectos")
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    response = make_response(redirect(url_for('login')))
    response.set_cookie('token', '', expires=0)
    return response

@app.route('/add_money', methods=['POST'])
@token_required
def add_money():
    amount_str = request.form['amount']
    try:
        amount = float(amount_str)
        if amount <= 0:
            flash("El monto debe ser positivo.")
            return redirect(request.referrer or url_for('index_accounts'))
    except ValueError:
        flash("Monto inválido.")
        return redirect(request.referrer or url_for('index_accounts'))
    
    ensure_money_record()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        IF EXISTS (SELECT 1 FROM Money WHERE ID = 1)
            UPDATE Money SET amount = amount + ? WHERE ID = 1
        ELSE
            INSERT INTO Money (amount) VALUES (?)
    """, (amount, amount))
    conn.commit()
    conn.close()
    flash("Dinero agregado exitosamente.", "success")
    return redirect(request.referrer or url_for('index_accounts'))

@app.route('/payments')
@token_required
def index_payments():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT payID, accountID, amount_paid, payment_date, method FROM payments_log")
   
    columns = [column[0] for column in cursor.description]
    payments = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    return render_template('index.html', payments=payments)


def update_expired_accounts():
    """Update accounts to 'vencido' status if enddate is before current date"""
    conn = get_db_connection()
    cursor = conn.cursor()
    today = datetime.date.today()
    cursor.execute("UPDATE accounts SET status = 'vencido' WHERE enddate < ? AND status != 'vencido'", (today,))
    conn.commit()
    conn.close()

@app.route('/accounts')
@token_required
def index_accounts():
    update_expired_accounts()  # Check and update expired accounts
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ID, accType, concept, reference, Total, enddate, status FROM accounts")
    columns = [column[0] for column in cursor.description]
    accounts = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    return render_template('accounts_index.html', accounts=accounts)

@app.route('/accounts/details/<id>')
@token_required
def get_account_details(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Obtener historial de pagos
    cursor.execute("SELECT payID, amount_paid, payment_date, method FROM payments_log WHERE accountID = ?", (id,))
    columns = [column[0] for column in cursor.description]
    payments = [dict(zip(columns, row)) for row in cursor.fetchall()]
    for payment in payments:
        payment['payment_date'] = format_spanish_date(payment.get('payment_date'))
    
    # Obtener info de la cuenta
    cursor.execute("SELECT * FROM accounts WHERE ID = ?", (id,))
    row = cursor.fetchone()
    account = dict(zip([c[0] for c in cursor.description], row)) if row else None
    if account:
        account['enddate'] = format_spanish_date(account.get('enddate'))
    
    conn.close()
    return jsonify({'account': account, 'payments': payments})
@app.route('/accounts/edit/<id>', methods=['GET', 'POST'])
@token_required
def edit_account(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        accType = request.form['accType']
        concept = request.form['concept']
        reference = request.form['reference']
        total = request.form['Total']
        enddate_str = request.form['enddate']
        status = request.form['status']
        
        # Validate enddate
        enddate = parse_date(enddate_str)
        if enddate is None:
            flash("Formato de fecha inválido.")
            conn.close()
            return redirect(url_for('edit_account', id=id))
        if enddate < datetime.date.today():
            flash("La fecha de vencimiento no puede estar en el pasado.")
            conn.close()
            return redirect(url_for('edit_account', id=id))
        
        cursor.execute(
            "UPDATE accounts SET accType=?, concept=?, reference=?, Total=?, enddate=?, status=? WHERE ID=?",
            (accType, concept, reference, total, enddate, status, id)
        )
        conn.commit()
        conn.close()
        flash("Cuenta actualizada correctamente", "success")
        return redirect(url_for('index_accounts'))

    cursor.execute("SELECT * FROM accounts WHERE ID = ?", (id,))
    row = cursor.fetchone()
    # Convertir la fila en diccionario para la plantilla
    account = dict(zip([c[0] for c in cursor.description], row)) if row else None
    conn.close()
    return render_template('accounts_create.html', account=account, edit_mode=True)

@app.route('/accounts/delete/<id>', methods=['POST'])
@token_required
def delete_account(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM accounts WHERE ID = ?", (id,))
    conn.commit()
    conn.close()
    flash("Cuenta eliminada", "danger")
    return redirect(url_for('index_accounts'))

@app.route('/accounts/create', methods=['GET', 'POST'])
@token_required
def create_account():
    if request.method == 'POST':
        account_id = request.form['ID']
        accType = request.form['accType']
        concept = request.form['concept']
        reference = request.form['reference']
        total = request.form['Total']
        enddate_str = request.form['enddate']
        status = request.form['status']
        
        # Validate enddate
        enddate = parse_date(enddate_str)
        if enddate is None:
            flash("Formato de fecha inválido.")
            return redirect(url_for('create_account'))
        if enddate < datetime.date.today():
            flash("La fecha de vencimiento no puede estar en el pasado.")
            return redirect(url_for('create_account'))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if ID already exists
        cursor.execute("SELECT ID FROM accounts WHERE ID = ?", (account_id,))
        if cursor.fetchone():
            flash("El ID de la cuenta ya existe. Por favor elija un ID diferente.")
            conn.close()
            return redirect(url_for('create_account'))
        
        cursor.execute(
            "INSERT INTO accounts (ID, accType, concept, reference, Total, enddate, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (account_id, accType, concept, reference, total, enddate, status)
        )
        conn.commit()
        conn.close()
        return redirect(url_for('index_accounts'))
    return render_template('accounts_create.html')


# Ruta para Registrar Pago (Crear)
@app.route('/payments/create', methods=['GET', 'POST'])
@token_required
def create_payment():
    if request.method == 'POST':
        accountID = request.form['accountID']
        amount_paid_str = request.form['amount_paid']
        method = request.form['method']
        payment_date = request.form['payment_date']
        
        # Validate payment_date
        payment_date_obj = parse_date(payment_date)
        if payment_date_obj is None:
            flash("Formato de fecha inválido. Use una fecha válida")
            return redirect(url_for('create_payment'))
        
        # Validate and sanitize amount_paid
        try:
            amount_paid = float(amount_paid_str)
            if amount_paid <= 0:
                raise ValueError()
        except ValueError:
            flash("Monto pagado inválido. Por favor ingrese un número positivo válido.")
            return redirect(url_for('create_payment'))
        
        ensure_money_record()
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT amount FROM Money WHERE ID = 1")
        money_row = cursor.fetchone()
        current_money = money_row[0] if money_row and money_row[0] is not None else 0
        if amount_paid > current_money:
            flash("Dinero insuficiente en el contador.")
            conn.close()
            return redirect(url_for('create_payment'))

        cursor.execute("SELECT Total, total FROM accounts WHERE ID = ?", (accountID,))
        result = cursor.fetchone()
        if not result:
            flash("Cuenta no encontrada.")
            conn.close()
            return redirect(url_for('create_payment'))

        grand_total, current_total = result
        if current_total is None:
            current_total = grand_total

        if amount_paid > current_total:
            flash("El monto del pago no puede exceder el saldo restante de la cuenta.")
            conn.close()
            return redirect(url_for('create_payment'))

        cursor.execute(
            "INSERT INTO payments_log (accountID, amount_paid, method, payment_date) VALUES (?, ?, ?, ?)",
            (accountID, amount_paid, method, payment_date_obj)
        )
        cursor.execute("UPDATE Money SET amount = amount - ? WHERE ID = 1", (amount_paid,))

        new_total = current_total - amount_paid
        cursor.execute("UPDATE accounts SET total = ? WHERE ID = ?", (new_total, accountID))

        if new_total <= 0:
            new_status = 'pagado'
        elif new_total < grand_total:
            new_status = 'parcial'
        else:
            new_status = 'pendiente'

        cursor.execute("UPDATE accounts SET status = ? WHERE ID = ?", (new_status, accountID))
        conn.commit()
        conn.close()
        return redirect(url_for('index_payments'))
    
    # Fetch accounts for dropdown
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ID, concept FROM accounts")
    accounts = cursor.fetchall()
    conn.close()
    return render_template('create.html', accounts=accounts)

# Ruta para Modificar Pago (Editar)
@app.route('/payments/edit/<int:id>', methods=['GET', 'POST'])
@token_required
def edit_payment(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        accountID = request.form['accountID']
        amount_paid_str = request.form['amount_paid']
        method = request.form['method']
        payment_date = request.form['payment_date']
        
        # Validate payment_date
        payment_date_obj = parse_date(payment_date)
        if payment_date_obj is None:
            flash("Formato de fecha inválido. Use una fecha válida")
            return redirect(url_for('edit_payment', id=id))
        
        # Validate and sanitize amount_paid
        try:
            amount_paid = float(amount_paid_str)
            if amount_paid <= 0:
                raise ValueError("Amount must be positive")
        except ValueError:
            flash("Monto pagado inválido. Por favor ingrese un número positivo válido.")
            return redirect(url_for('edit_payment', id=id))
        
        # Get old accountID before update
        cursor.execute("SELECT accountID FROM payments_log WHERE payID = ?", (id,))
        old_accountID = cursor.fetchone()[0]
        
        # Update the payment
        cursor.execute(
            "UPDATE payments_log SET accountID = ?, amount_paid = ?, method = ?, payment_date = ? WHERE payID = ?",
            (accountID, amount_paid, method, payment_date_obj, id)
        )        
        # Function to update account totals and status
        def update_account(account_id):
            cursor.execute("SELECT SUM(amount_paid) FROM payments_log WHERE accountID = ?", (account_id,))
            result = cursor.fetchone()
            total_paid = result[0] if result and result[0] else 0
            
            cursor.execute("SELECT Total FROM accounts WHERE ID = ?", (account_id,))
            account_row = cursor.fetchone()
            if account_row:
                grand_total = account_row[0]
                
                new_total = grand_total - total_paid
                cursor.execute("UPDATE accounts SET total = ? WHERE ID = ?", (new_total, account_id))
                
                if total_paid >= grand_total:
                    new_status = 'pagado'
                elif total_paid > 0:
                    new_status = 'parcial'
                else:
                    new_status = 'pendiente'
                cursor.execute("UPDATE accounts SET status = ? WHERE ID = ?", (new_status, account_id))
        
        # Update old account if accountID changed
        if old_accountID != accountID:
            update_account(old_accountID)
        
        # Update new account
        update_account(accountID)
        
        conn.commit()
        conn.close()
        return redirect(url_for('index_payments'))
    
    cursor.execute("SELECT payID, accountID, amount_paid, method, payment_date FROM payments_log WHERE payID = ?", (id,))
    row = cursor.fetchone()
    columns = [column[0] for column in cursor.description]
    payment = dict(zip(columns, row)) if row else None
    
    # Fetch accounts for dropdown
    cursor.execute("SELECT ID, concept FROM accounts")
    accounts = cursor.fetchall()
    conn.close()
    return render_template('edit.html', payment=payment, accounts=accounts)

# Ruta para Eliminar Pago (Borrar)
@app.route('/payments/delete/<int:id>', methods=['GET', 'POST'])
@token_required
def delete_payment(id):
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM payments_log WHERE payID = ?", (id,))
        conn.commit()
        conn.close()
        return redirect(url_for('index_payments'))
    return render_template('delete.html', payment_id=id)

if __name__ == '__main__':
    app.run(debug=True)
