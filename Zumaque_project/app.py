import dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, request, jsonify, render_template, redirect, url_for, make_response, flash, session
import jwt
import pyodbc 
import datetime
from dotenv import load_dotenv
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
import calendar

load_dotenv(override=True)
SECRET_KEY = os.getenv('SECRET_KEY')

# Definir rutas base para asegurar que la nube encuentre los archivos
base_dir = os.path.abspath(os.path.dirname(__file__))
template_dir = os.path.join(base_dir, 'templates')
static_dir = os.path.join(base_dir, 'static')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
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
        cursor.execute("SELECT amount, Tasa FROM Money WHERE ID = 1")
        row = cursor.fetchone()
        if row is None:
            cursor.execute("IF OBJECT_ID('dbo.Money', 'U') IS NULL CREATE TABLE Money (ID INT IDENTITY(1,1) PRIMARY KEY, amount DECIMAL(18,2) DEFAULT 0, Tasa DECIMAL(18,2) DEFAULT 0, last_updated DATETIME DEFAULT GETDATE())")
            cursor.execute("INSERT INTO Money (amount, Tasa) VALUES (0, 0)")
            conn.commit()
            return 0, 0
        return (row[0] or 0), (row[1] or 0)
    except pyodbc.Error:
        cursor.execute("IF OBJECT_ID('dbo.Money', 'U') IS NULL CREATE TABLE Money (ID INT IDENTITY(1,1) PRIMARY KEY, amount DECIMAL(18,2) DEFAULT 0, Tasa DECIMAL(18,2) DEFAULT 0, last_updated DATETIME DEFAULT GETDATE())")
        conn.commit()
        cursor.execute("INSERT INTO Money (amount, Tasa) VALUES (0, 0)")
        conn.commit()
        return 0, 0
    finally:
        conn.close()

@app.context_processor
def inject_money_counter():
    amount, tasa = 0.0, 0.0
    try:
        db_amount, db_tasa = ensure_money_record()
        amount = float(db_amount) if db_amount is not None else 0.0
        tasa = float(db_tasa) if db_tasa is not None else 0.0
    except Exception:
        pass
    return {'money_counter': amount, 'current_tasa': tasa}


def send_monthly_reminder_email(reminders):
    """Send email reminder for monthly payment"""
    # Get email configuration from environment
    smtp_server = os.getenv('SMTP_SERVER')
    smtp_port = os.getenv('SMTP_PORT')
    smtp_user = os.getenv('SMTP_USER')
    smtp_password = os.getenv('SMTP_PASSWORD')
    from_email = os.getenv('FROM_EMAIL', smtp_user)
    to_email = os.getenv('NOTIFICATION_EMAIL')
    
    if not all([smtp_server, smtp_user, smtp_password, to_email]):
        print("Email configuration missing - skipping email reminder")
        return False
    
    try:
        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = to_email
        msg['Subject'] = f'Resumen de Cuentas Mensuales Pendientes - {datetime.date.today().strftime("%d/%m/%Y")}'
        
        items_html = ""
        for r in reminders:
            date_str = r['next_payment_date'].strftime('%d/%m/%Y') if r['next_payment_date'] and hasattr(r['next_payment_date'], 'strftime') else "No definida"
            items_html += f"""
            <tr>
                <td style="padding: 10px; border: 1px solid #ddd;">{r['id']}</td>
                <td style="padding: 10px; border: 1px solid #ddd;">{r['concept']}</td>
                <td style="padding: 10px; border: 1px solid #ddd;">${r['total_amount']:,.2f}</td>
                <td style="padding: 10px; border: 1px solid #ddd;">${r['remaining_balance']:,.2f}</td>
                <td style="padding: 10px; border: 1px solid #ddd;">{date_str}</td>
            </tr>
            """

        body = f"""
        <html>
            <body style="font-family: sans-serif;">
                <h2 style="color: #475569;">Resumen de Cuentas Mensuales Pendientes</h2>
                <p>Las siguientes cuentas no han sido pagadas en su totalidad:</p>
                <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">
                    <thead>
                        <tr style="background-color: #f8f9fa;">
                            <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">ID</th>
                            <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Concepto</th>
                            <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Total de Cuenta</th>
                            <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Saldo Restante</th>
                            <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Vencimiento</th>
                        </tr>
                    </thead>
                    <tbody>{items_html}</tbody>
                </table>
                <p style="margin-top: 20px; color: #64748b;">Por favor, gestione los pagos correspondientes.</p>
            </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        with smtplib.SMTP(smtp_server, int(smtp_port) if smtp_port else 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        
        # Log the notification
        conn = get_db_connection()
        cursor = conn.cursor()
        for r in reminders:
            cursor.execute(
                "INSERT INTO email_notifications (account_id, reminder_type, status) VALUES (?, ?, ?)",
                (r['id'], 'monthly_summary', 'sent')
            )
        conn.commit()
        conn.close()
        
        return True
    except Exception as e:
        if isinstance(e, smtplib.SMTPAuthenticationError):
            print(f"Failed to send email due to authentication error: {e}")
            flash("Error de autenticación SMTP. Por favor, revise sus credenciales de correo electrónico (SMTP_USER, SMTP_PASSWORD).", "danger")
        else:
            print(f"Failed to send email: {e}")
            flash(f"Error al enviar el correo de resumen mensual: {str(e)}", "danger")
        return False


def check_monthly_payment_reminders(send_emails=False):
    """Check for monthly payment accounts that need reminders"""
    conn = get_db_connection()
    cursor = conn.cursor()
    today = datetime.date.today()
    # Definimos el límite de 3 días para las notificaciones próximas
    limit_date = today + datetime.timedelta(days=3)
    
    reminders = []
    try:
        # Check if the columns exist first
        cursor.execute("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = 'accounts' AND COLUMN_NAME = 'is_monthly'
        """)
        if not cursor.fetchone():
            # Columns don't exist yet, skip reminders
            conn.close()
            return reminders
        
        # Buscar cuentas mensuales no pagadas que vencen en los próximos 3 días o ya vencieron
        cursor.execute("""
            SELECT ID, concept, next_payment_date, Total, total 
            FROM accounts 
            WHERE is_monthly = 1 
            AND status != 'pagado'
            AND next_payment_date <= ?
            AND (reminder_sent = 0 OR reminder_sent IS NULL)
        """, (limit_date,))
        
        upcoming = cursor.fetchall()
        
        for row in upcoming:
            reminders.append({
                'id': row[0],
                'concept': row[1],
                'next_payment_date': row[2],
                'total_amount': row[3],
                'remaining_balance': row[4] if row[4] is not None else row[3],
                'email_sent': False
            })

        if send_emails and reminders:
            # Enviar un único correo con todas las cuentas
            email_sent = send_monthly_reminder_email(reminders)
            if email_sent:
                for r in reminders:
                    r['email_sent'] = True
                    cursor.execute("UPDATE accounts SET reminder_sent = 1 WHERE ID = ?", (r['id'],))
                conn.commit()

    except Exception as e:
        print(f"Error checking monthly reminders: {e}")
    finally:
        conn.close()
    
    return reminders


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
            # Limpiar la marca de correos para que se revisen en este nuevo inicio de sesión
            session['emails_checked'] = False
            
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
    tasa_str = request.form.get('tasa', '0')
    try:
        amount = float(amount_str)
        if amount <= 0:
            flash("El monto debe ser positivo.")
            return redirect(request.referrer or url_for('index_accounts'))
        tasa = float(tasa_str)
    except ValueError:
        flash("Monto inválido.")
        return redirect(request.referrer or url_for('index_accounts'))
    
    ensure_money_record()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        IF EXISTS (SELECT 1 FROM Money WHERE ID = 1)
            UPDATE Money SET amount = amount + ?, Tasa = ?, last_updated = GETDATE() WHERE ID = 1
        ELSE
            INSERT INTO Money (amount, Tasa) VALUES (?, ?)
    """, (amount, tasa, amount, tasa))
    conn.commit()
    conn.close()
    flash("Dinero agregado exitosamente.", "success")
    return redirect(request.referrer or url_for('index_accounts'))

@app.route('/update_tasa', methods=['POST'])
@token_required
def update_tasa():
    tasa_str = request.form.get('tasa')
    try:
        tasa = float(tasa_str)
        if tasa < 0:
            flash("La tasa no puede ser negativa.", "danger")
            return redirect(request.referrer or url_for('index_accounts'))
    except (ValueError, TypeError):
        flash("Monto de tasa inválido.", "danger")
        return redirect(request.referrer or url_for('index_accounts'))

    ensure_money_record()
    conn = get_db_connection()
    cursor = conn.cursor()
    # Solo actualizamos la tasa en el registro global
    cursor.execute("UPDATE Money SET Tasa = ?, last_updated = GETDATE() WHERE ID = 1", (tasa,))
    conn.commit()
    conn.close()
    flash("Tasa de cambio actualizada correctamente.", "success")
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
    conn = get_db_connection()
    cursor = conn.cursor()
    today = datetime.date.today()
    cursor.execute("UPDATE accounts SET status = 'vencido' WHERE enddate < ? AND status != 'vencido' AND status != 'pagado'", (today,))
    conn.commit()
    conn.close()

@app.route('/accounts')
@token_required
def index_accounts():
    update_expired_accounts()  # Check and update expired accounts

    # Obtener recordatorios. Si no se han revisado correos en esta sesión, se envían.
    send_emails = not session.get('emails_checked')
    reminders = []
    try:
        reminders = check_monthly_payment_reminders(send_emails=send_emails)
        if send_emails and reminders:
            session['emails_checked'] = True
    except Exception as e:
        print(f"Error en el proceso de recordatorios: {e}")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ID, accType, concept, reference, Total, enddate, status FROM accounts")
    columns = [column[0] for column in cursor.description]
    accounts = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    return render_template('accounts_index.html', accounts=accounts, payment_reminders=reminders)

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
        # Format monthly payment fields
        account['next_payment_date'] = format_spanish_date(account.get('next_payment_date'))
        account['last_payment_date'] = format_spanish_date(account.get('last_payment_date'))
    
    conn.close()
    return jsonify({'account': account, 'payments': payments})

@app.route('/accounts/update_next_payment/<id>', methods=['POST'])
@token_required
def update_next_payment(id):
    data = request.get_json()
    new_date_str = data.get('next_payment_date')
    
    new_date = parse_date(new_date_str)
    if not new_date:
        return jsonify({'success': False, 'message': 'Formato de fecha inválido'}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Actualizamos la fecha y reseteamos el recordatorio para la nueva fecha
        cursor.execute(
            "UPDATE accounts SET next_payment_date = ?, reminder_sent = 0 WHERE ID = ?",
            (new_date, id)
        )
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()

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
        permanency = request.form.get('permanency', '0')
        is_monthly = request.form.get('is_monthly', '0') == '1'
        monthly_amount = request.form.get('monthly_amount')
        next_payment_date_str = request.form.get('next_payment_date')
        
        # Validate enddate
        enddate = parse_date(enddate_str)
        if enddate is None:
            flash("Formato de fecha inválido.")
            conn.close()
            return redirect(url_for('edit_account', id=id))
        
        # Update with all monthly and permanency fields to make them editable
        cursor.execute(
            """UPDATE accounts 
               SET accType=?, concept=?, reference=?, Total=?, enddate=?, status=?, 
                   permanency=?, is_monthly=?, monthly_amount=?, next_payment_date=? 
               WHERE ID=?""",
            (accType, concept, reference, total, enddate, status, 
             permanency, is_monthly, float(monthly_amount) if monthly_amount else None, 
             parse_date(next_payment_date_str), id)
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
        
        # Validación de monto total y saldo inicial
        try:
            total_val = float(request.form.get('Total', 0))
        except (ValueError, TypeError):
            flash("Monto total inválido.")
            return redirect(url_for('create_account'))
        enddate_str = request.form['enddate']
        status = request.form['status']
        permanency = request.form.get('permanency', '0')
        
        # Monthly payment fields
        is_monthly = request.form.get('is_monthly', '0') == '1'
        try:
            monthly_amount = float(request.form.get('monthly_amount')) if is_monthly and request.form.get('monthly_amount') else None
        except (ValueError, TypeError):
            monthly_amount = None
        
        # Validate enddate
        enddate = parse_date(enddate_str)
        if enddate is None:
            flash("Formato de fecha inválido.")
            return redirect(url_for('create_account'))
        if enddate < datetime.date.today():
            flash("La fecha de vencimiento no puede estar en el pasado.")
            return redirect(url_for('create_account'))
        
        # Set next payment date for monthly accounts
        next_payment_date = enddate if is_monthly else None
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if ID already exists
        cursor.execute("SELECT ID FROM accounts WHERE ID = ?", (account_id,))
        if cursor.fetchone():
            flash("El ID de la cuenta ya existe. Por favor elija un ID diferente.")
            conn.close()
            return redirect(url_for('create_account'))
        
        cursor.execute(
            "INSERT INTO accounts (ID, accType, concept, reference, Total, total, enddate, status, permanency, is_monthly, monthly_amount, next_payment_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, accType, concept, reference, total_val, total_val, enddate, status, permanency, is_monthly, monthly_amount, next_payment_date)
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
        
        # Lógica para cuentas mensuales y generación automática del próximo ciclo
        try:
            cursor.execute("SELECT is_monthly, permanency, monthly_amount, next_payment_date FROM accounts WHERE ID = ?", (accountID,))
            acc_info = cursor.fetchone()
            if acc_info and acc_info[0]:  # Si es una cuenta mensual
                is_recurring = int(acc_info[1] or 0) == 1
                m_amount = float(acc_info[2] or 0)
                current_next_date = acc_info[3]
                
                # Calculamos la base para la próxima fecha (evita derivas si se paga tarde o temprano)
                base_date = current_next_date if current_next_date else payment_date_obj
                
                # Lógica para mover exactamente un mes (ej: 31 Ene -> 28 Feb)
                m = base_date.month + 1
                y = base_date.year + (m - 1) // 12
                m = (m - 1) % 12 + 1
                d = min(base_date.day, calendar.monthrange(y, m)[1])
                next_date = datetime.date(y, m, d)
                
                if is_recurring and new_total <= 0:
                    # Si la cuenta es recurrente ("Constante") y el saldo llegó a 0 (o saldo a favor):
                    # Genera el nuevo "Total" pendiente para el próximo mes, sumando el excedente si existe
                    renewed_total = m_amount + new_total 
                    cursor.execute("""
                        UPDATE accounts 
                        SET total = ?, status = 'pendiente', 
                            last_payment_date = ?, next_payment_date = ?, 
                            reminder_sent = 0 
                        WHERE ID = ?
                    """, (renewed_total, payment_date_obj, next_date, accountID))
                else:
                    # Si es cuenta mensual pero no recurrente, o aún no se termina de pagar el mes actual, 
                    # solo actualizamos las fechas de seguimiento sin renovar el saldo.
                    cursor.execute("""
                        UPDATE accounts 
                        SET last_payment_date = ?, next_payment_date = ?, 
                            reminder_sent = 0 
                        WHERE ID = ?
                    """, (payment_date_obj, next_date, accountID))
        except Exception as e:
            print(f"Error processing monthly payment: {e}")
        
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
