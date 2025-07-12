from flask import Flask, render_template, request, redirect
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash

db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="stackit"
)

cursor = db.cursor(dictionary=True)
app = Flask(__name__)

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

@app.route("/login")
def login():
    return render_template('login.html'
    '')

if __name__ == '__main__':
    app.run(debug=True)
