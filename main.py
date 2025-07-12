from flask import Flask, render_template, request, redirect, session
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
from datetime import timedelta

db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="stackit"
)
cursor = db.cursor(dictionary=True)
app = Flask(__name__)
app.secret_key = 'Meet0102'

def is_logged_in():
    uid = session.get('user_id')
    token = session.get('token')
    if not uid or not token:
        return False
    cursor.execute("SELECT * FROM user_sessions WHERE user_id=%s AND session_token=%s", (uid, token))
    return cursor.fetchone() is not None

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password_raw = request.form['password']
        admin_code = request.form['admin_code']

        cursor.execute("SELECT * FROM users WHERE username=%s OR email=%s", (username, email))
        existing = cursor.fetchone()

        if existing:
            return render_template('register.html', server_error="Username or email already exists")

        password = generate_password_hash(password_raw)
        role = 'admin' if admin_code == 'JAYDADA123' else 'user'

        cursor.execute(
            "INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s)",
            (username, email, password, role)
        )
        db.commit()
        return redirect('/login')

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username_or_email = request.form['username']
        password = request.form['password']

        cursor.execute(
            "SELECT * FROM users WHERE username=%s OR email=%s",
            (username_or_email, username_or_email)
        )
        user = cursor.fetchone()
        print(user)

        if not user or not check_password_hash(user['password'], password):
            return render_template('login.html', error="Invalid username or password")

        token = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO user_sessions (user_id, session_token) VALUES (%s, %s)",
            (user['id'], token)
        )
        db.commit()

        session.permanent = True
        app.permanent_session_lifetime = timedelta(days=7)
        session['user_id'] = user['id']
        session['token'] = token

        return redirect('/')

    return render_template('login.html')

@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    token = session.get('token')

    if user_id and token:
        cursor.execute("DELETE FROM user_sessions WHERE user_id=%s AND session_token=%s", (user_id, token))
        db.commit()

    session.clear()
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True)
