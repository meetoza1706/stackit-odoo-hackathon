from flask import Flask, render_template, request, redirect, session, jsonify
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
from datetime import timedelta
import smtplib
from email.mime.text import MIMEText
import random
import cloudinary
import cloudinary.uploader

db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="stackit"
)
cloudinary.config(
  cloud_name="YOUR_CLOUD_NAME",
  api_key="YOUR_API_KEY",
  api_secret="YOUR_API_SECRET"
)
cursor = db.cursor(dictionary=True)
app = Flask(__name__)
app.secret_key = 'Meet0102'
otp_store = {}

def is_logged_in():
    uid = session.get('user_id')
    token = session.get('token')
    if not uid or not token:
        return False
    cursor.execute("SELECT * FROM user_sessions WHERE user_id=%s AND session_token=%s", (uid, token))
    return cursor.fetchone() is not None

def get_all_tags():
    cursor.execute("SELECT name FROM tags ORDER BY post_count DESC")
    return [row['name'] for row in cursor.fetchall()]


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

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        if 'otp_stage' in request.form:
            entered_code = request.form['otp'].strip()
            new_pass = request.form['new_password']
            confirm_pass = request.form['confirm_password']
            email = session.get('reset_email')
            expected_code = otp_store.get(email)

            if not email or not expected_code:
                return render_template('forgot_password.html', error="Session expired. Try again.")

            if entered_code != expected_code:
                return render_template('forgot_password.html', error="Incorrect OTP", otp_stage=True)

            if len(new_pass) < 6:
                return render_template('forgot_password.html', error="Password too short", otp_stage=True)

            if new_pass != confirm_pass:
                return render_template('forgot_password.html', error="Passwords do not match", otp_stage=True)

            hashed = generate_password_hash(new_pass)
            cursor.execute("UPDATE users SET password=%s WHERE email=%s", (hashed, email))
            db.commit()

            otp_store.pop(email, None)
            session.pop('reset_email', None)
            return redirect('/login')

        # Stage 1: email submission
        email = request.form['email'].strip()

        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        if not user:
            return render_template('forgot_password.html', error="Email not found")

        code = str(random.randint(100000, 999999))
        otp_store[email] = code
        session['reset_email'] = email

        msg = MIMEText(f"Your StackIt password reset code is: {code}")
        msg['Subject'] = 'StackIt - Password Reset Code'
        msg['From'] = 'ozamee17@gmail.com'
        msg['To'] = email

        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
                smtp.login('inventra8@gmail.com', 'tvvg ziwb bskk knym')
                smtp.send_message(msg)
        except Exception as e:
            print("[DEBUG] Email sending failed:", e)
            return render_template('forgot_password.html', error="Failed to send email")

        return render_template('forgot_password.html', otp_stage=True)

    return render_template('forgot_password.html')

@app.route('/ask_question', methods=['GET', 'POST'])
def ask_question():
    if not is_logged_in():
        return redirect('/login')

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        tags = request.form.getlist('tags[]')
        user_id = session['user_id']

        if not title or not description or not tags:
            return render_template('ask_question.html', error="All fields required.", all_tags=get_all_tags())

        if len(description) > 3000:
            return render_template('ask_question.html', error="Description exceeds 3000 characters.", all_tags=get_all_tags())

        try:
            # Insert post
            cursor.execute(
                "INSERT INTO posts (user_id, title, description) VALUES (%s, %s, %s)",
                (user_id, title, description)
            )
            post_id = cursor.lastrowid

            for tag in tags:
                clean_tag = tag.strip().lower()
                cursor.execute("SELECT id FROM tags WHERE name = %s", (clean_tag,))
                existing = cursor.fetchone()

                if existing:
                    tag_id = existing['id']
                    cursor.execute("UPDATE tags SET post_count = post_count + 1 WHERE id = %s", (tag_id,))
                else:
                    cursor.execute("INSERT INTO tags (name, post_count) VALUES (%s, 1)", (clean_tag,))
                    tag_id = cursor.lastrowid

                cursor.execute("INSERT INTO post_tags (post_id, tag_id) VALUES (%s, %s)", (post_id, tag_id))

            db.commit()
            return redirect('/')

        except Exception as e:
            db.rollback()
            return f"Error while posting: {e}", 500

    return render_template('ask_question.html', all_tags=get_all_tags())

@app.route('/tags_autocomplete')
def tags_autocomplete():
    cursor.execute("SELECT name FROM tags ORDER BY post_count DESC")
    tags = [row['name'] for row in cursor.fetchall()]
    return jsonify(tags)    


if __name__ == '__main__':
    app.run(debug=True)