from flask import Flask, render_template, request, redirect, session, jsonify
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
from datetime import timedelta, datetime
import smtplib
from email.mime.text import MIMEText
import random
import cloudinary
import cloudinary.uploader
import re

db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="stackit"
)
cloudinary.config(
  cloud_name="dyab0etow",
  api_key="829971282552343",
  api_secret="rOe_MAJN--sVuITTNQAYkZvrFss"
)
cursor = db.cursor(dictionary=True)
app = Flask(__name__)
app.secret_key = 'Meet0102'
otp_store = {}
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB


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


@app.route('/', methods=['GET', 'POST'])
def home():
    # Get search and filter parameters
    search = request.args.get('search', '').strip()
    filter_opt = request.args.get('filter', 'newest')

    cursor = db.cursor(dictionary=True)

    # Base query with tags and answer count
    query = """
        SELECT 
          posts.id, posts.title, users.username, posts.description, posts.created_at,
          GROUP_CONCAT(tags.name) AS tag_list,
          COUNT(a.id) AS answer_count
        FROM posts
        JOIN users ON posts.user_id = users.id
        LEFT JOIN post_tags ON posts.id = post_tags.post_id
        LEFT JOIN tags ON post_tags.tag_id = tags.id
        LEFT JOIN answers a ON posts.id = a.post_id
    """
    params = []

    # Apply search filter
    if search:
        query += " WHERE posts.title LIKE %s OR posts.description LIKE %s "
        like_search = f"%{search}%"
        params.extend([like_search, like_search])

    query += " GROUP BY posts.id "

    # Apply chosen filter
    if filter_opt == 'unanswered':
        query += " HAVING answer_count = 0 ORDER BY posts.created_at DESC"
    elif filter_opt == 'most_answers':
        query += " ORDER BY answer_count DESC"
    elif filter_opt == 'oldest':
        query += " ORDER BY posts.created_at ASC"
    else:  # newest or default
        query += " ORDER BY posts.created_at DESC"

    # Execute posts query
    cursor.execute(query, params)
    posts = cursor.fetchall()

    # Collect post IDs to filter answers
    post_ids = [post['id'] for post in posts]
    if post_ids:
        format_strings = ','.join(['%s'] * len(post_ids))
        cursor.execute(f"""
            SELECT 
                a.id, a.post_id, a.content, a.created_at, u.username,
                COALESCE(SUM(CASE WHEN av.vote_type = 'up' THEN 1 
                                  WHEN av.vote_type = 'down' THEN -1 ELSE 0 END), 0) AS votes
            FROM answers a
            JOIN users u ON a.user_id = u.id
            LEFT JOIN answer_votes av ON a.id = av.answer_id
            WHERE a.post_id IN ({format_strings})
            GROUP BY a.id
        """, post_ids)
        all_answers = cursor.fetchall()
    else:
        all_answers = []

    # Organize answers by post_id
    answers_by_post = {}
    for ans in all_answers:
        answers_by_post.setdefault(ans['post_id'], []).append(ans)

    # Attach tags and answers to posts
    for post in posts:
        post['tags'] = post['tag_list'].split(',') if post.get('tag_list') else []
        post['answers'] = answers_by_post.get(post['id'], [])

    # Render with both search and filter values
    return render_template('home.html', posts=posts, search=search, filter=filter_opt)
 

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

@app.route('/upload_image', methods=['POST'])
def upload_image():
    image = request.files.get('image')
    if not image:
        return jsonify(success=False)
    res = cloudinary.uploader.upload(image)
    return jsonify(success=True, url=res['secure_url'])

@app.route('/ask_question', methods=['GET', 'POST'])
def ask_question():
    if not is_logged_in():
        return redirect('/login')
        
    if request.method == 'POST':
        title = request.form['title'].strip()
        description = request.form['description'].strip()
        tags = request.form.getlist('tags[]')

        if not title or not description or not tags:
            return render_template('ask_question.html', all_tags=get_all_tags(), error="All fields required.")

        # Insert question
        cursor.execute("INSERT INTO posts (user_id, title, description) VALUES (%s,%s,%s)",
                       (session['user_id'], title, description))
        post_id = cursor.lastrowid

        # Handle tags
        for tg in tags:
            t = tg.strip().lower()
            cursor.execute("SELECT id FROM tags WHERE name=%s", (t,))
            row = cursor.fetchone()
            if row:
                tag_id = row['id']
                cursor.execute("UPDATE tags SET post_count=post_count+1 WHERE id=%s", (tag_id,))
            else:
                cursor.execute("INSERT INTO tags (name, post_count) VALUES (%s,1)", (t,))
                tag_id = cursor.lastrowid
            cursor.execute("INSERT INTO post_tags (post_id, tag_id) VALUES (%s,%s)", (post_id, tag_id))

        # 🔔 Mention notifications in question
        
        mentions = re.findall(r'@(\w+)', description)
        notified = set()
        for uname in mentions:
            cursor.execute("SELECT id FROM users WHERE username = %s", (uname,))
            mentioned = cursor.fetchone()
            if mentioned and mentioned['id'] != session['user_id'] and mentioned['id'] not in notified:
                msg = f"📣 You were mentioned in a question! [{datetime.now().strftime('%d %b %Y %I:%M %p')}]"
                cursor.execute("INSERT INTO notifications (user_id, message) VALUES (%s, %s)",
                               (mentioned['id'], msg))
                notified.add(mentioned['id'])

        db.commit()
        return redirect(f'/')
        
    return render_template('ask_question.html', all_tags=get_all_tags())


@app.route('/question/<int:post_id>')
def view_question(post_id):
    cursor.execute("""
        SELECT p.id, p.title, p.description, p.created_at, u.username
        FROM posts p JOIN users u ON p.user_id=u.id
        WHERE p.id=%s""", (post_id,))
    post = cursor.fetchone()
    if not post:
        return "Post not found", 404
    cursor.execute("""
        SELECT t.name
        FROM tags t JOIN post_tags pt ON pt.tag_id=t.id
        WHERE pt.post_id=%s""", (post_id,))
    tags = [r['name'] for r in cursor.fetchall()]
    return render_template('view_question.html', post=post, tags=tags)

@app.route('/tags')
def tags_autocomplete():
    cursor.execute("SELECT name FROM tags ORDER BY post_count DESC LIMIT 50")
    return jsonify([r['name'] for r in cursor.fetchall()])

@app.route('/questions')
def all_questions():
    cursor = db.cursor(dictionary=True)

    # 1. Get all posts with their authors and tags
    cursor.execute("""
        SELECT posts.id, posts.title, users.username, posts.description, posts.created_at,
               GROUP_CONCAT(tags.name) AS tag_list
        FROM posts
        JOIN users ON posts.user_id = users.id
        LEFT JOIN post_tags ON posts.id = post_tags.post_id
        LEFT JOIN tags ON post_tags.tag_id = tags.id
        GROUP BY posts.id
        ORDER BY posts.created_at DESC
    """)
    posts = cursor.fetchall()

    # 2. Get all answers with votes
    cursor.execute("""
        SELECT 
            a.id, a.post_id, a.content, a.created_at, u.username,
            COALESCE(SUM(CASE WHEN av.vote_type = 'up' THEN 1 
                              WHEN av.vote_type = 'down' THEN -1 ELSE 0 END), 0) AS votes
        FROM answers a
        JOIN users u ON a.user_id = u.id
        LEFT JOIN answer_votes av ON a.id = av.answer_id
        GROUP BY a.id
    """)
    all_answers = cursor.fetchall()

    # 3. Organize answers by post_id
    answers_by_post = {}
    for ans in all_answers:
        answers_by_post.setdefault(ans['post_id'], []).append(ans)

    # 4. Attach tags and answers to posts
    for post in posts:
        post['tags'] = post['tag_list'].split(',') if post['tag_list'] else []
        post['answers'] = answers_by_post.get(post['id'], [])

    return render_template('view_questions.html', posts=posts)



def notify_mentions(content, sender_id, post_id=None, answer_id=None):
    mentioned = set(re.findall(r'@(\w+)', content))
    for username in mentioned:
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        if user and user['id'] != sender_id:
            # Build link to answer or post
            url = f"/question/{post_id}#answer-{answer_id}" if answer_id else f"/question/{post_id}"
            msg = f"🔔 You were mentioned in a post! <a href='{url}' class='underline text-blue-600'>View</a>"
            cursor.execute("""
                INSERT INTO notifications (user_id, message)
                VALUES (%s, %s)
            """, (user['id'], msg))

def get_username(user_id):
    cursor.execute("SELECT username FROM users WHERE id=%s", (user_id,))
    u = cursor.fetchone()
    return u['username'] if u else 'Someone'
@app.route('/submit_answer', methods=['POST'])
def submit_answer():
    if not is_logged_in():
        return redirect('/login')

    post_id = request.form.get('post_id')
    content = request.form.get('content', '').strip()

    if not post_id or not content or len(content) < 10:
        return "Answer too short or missing", 400

    # Save answer
    cursor.execute("""
        INSERT INTO answers (post_id, user_id, content, created_at)
        VALUES (%s, %s, %s, %s)
    """, (post_id, session['user_id'], content, datetime.now()))
    answer_id = cursor.lastrowid

    # Notify question owner (if not self)
    cursor.execute("SELECT user_id FROM posts WHERE id = %s", (post_id,))
    owner = cursor.fetchone()
    if owner and owner['user_id'] != session['user_id']:
        link = f"/question/{post_id}#answer-{answer_id}"
        message = f"💬 Your question received a new answer! <a href='{link}' class='underline text-blue-600'>View</a>"
        cursor.execute("INSERT INTO notifications (user_id, message) VALUES (%s, %s)", (owner['user_id'], message))

    # Notify @mentions in the answer content
    notify_mentions(content, session['user_id'], post_id, answer_id)

    db.commit()
    return redirect('/')



@app.route('/vote_answer', methods=['POST'])
def vote_answer():
    if not is_logged_in():
        return jsonify({'error': 'Not logged in'}), 403

    data = request.get_json()
    answer_id = data.get('answer_id')
    vote_type = data.get('vote_type')
    user_id = session['user_id']

    if vote_type not in ['up', 'down']:
        return jsonify({'error': 'Invalid vote'}), 400

    # Check existing vote
    cursor.execute("""
        SELECT vote_type FROM answer_votes 
        WHERE answer_id = %s AND user_id = %s
    """, (answer_id, user_id))
    existing = cursor.fetchone()

    if existing:
        if existing['vote_type'] == vote_type:
            cursor.execute("""
                DELETE FROM answer_votes 
                WHERE answer_id = %s AND user_id = %s
            """, (answer_id, user_id))
        else:
            cursor.execute("""
                UPDATE answer_votes 
                SET vote_type = %s, created_at = %s 
                WHERE answer_id = %s AND user_id = %s
            """, (vote_type, datetime.now(), answer_id, user_id))
    else:
        cursor.execute("""
            INSERT INTO answer_votes (answer_id, user_id, vote_type, created_at)
            VALUES (%s, %s, %s, %s)
        """, (answer_id, user_id, vote_type, datetime.now()))

    # 🔔 Notify answer owner
    cursor.execute("SELECT user_id, post_id FROM answers WHERE id = %s", (answer_id,))
    answer = cursor.fetchone()
    if answer and answer['user_id'] != user_id:
        msg = f"👍 Your answer received an {vote_type}vote!"
        cursor.execute("""
            INSERT INTO notifications (user_id, message, post_id, answer_id)
            VALUES (%s, %s, %s, %s)
        """, (answer['user_id'], msg, answer['post_id'], answer_id))

    db.commit()

    # Return updated votes
    cursor.execute("""
        SELECT 
          SUM(CASE WHEN vote_type = 'up' THEN 1 ELSE 0 END) AS upvotes,
          SUM(CASE WHEN vote_type = 'down' THEN 1 ELSE 0 END) AS downvotes
        FROM answer_votes
        WHERE answer_id = %s
    """, (answer_id,))
    result = cursor.fetchone()

    return jsonify({
        'upvotes': result['upvotes'] or 0,
        'downvotes': result['downvotes'] or 0
    })


@app.route('/notifications')
def view_notifications():
    if not is_logged_in():
        return redirect('/login')

    cursor.execute("""
        SELECT id, message, is_read, created_at 
        FROM notifications 
        WHERE user_id = %s 
        ORDER BY created_at DESC
    """, (session['user_id'],))
    notes = cursor.fetchall()

    return render_template('notifications.html', notifications=notes)

@app.route('/notifications/json')
def notifications_json():
    if not is_logged_in():
        return jsonify([])

    cursor.execute("""
        SELECT message, DATE_FORMAT(created_at, '%%d %%b %%Y %%I:%%i %%p') as created_at
        FROM notifications
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT 20
    """, (session['user_id'],))
    return jsonify(cursor.fetchall())

@app.route("/profile")
def profile():
    return render_template("profile.html")



if __name__ == '__main__':
    app.run(debug=True)