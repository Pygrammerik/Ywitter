from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import random
from sqlalchemy import or_
from moviepy import VideoFileClip
from translations import get_translation as _
import re
import hashlib
import hmac
import time
import json
import pyotp

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ywitter.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

MEDIA_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'media')
os.makedirs(MEDIA_UPLOAD_FOLDER, exist_ok=True)
app.config['MEDIA_UPLOAD_FOLDER'] = MEDIA_UPLOAD_FOLDER

AVATAR_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'avatars')
os.makedirs(AVATAR_UPLOAD_FOLDER, exist_ok=True)
app.config['AVATAR_UPLOAD_FOLDER'] = AVATAR_UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'mov'}

def get_locale():
    return request.args.get('lang') or 'ru'

def get_lang_urls():
    args = dict(request.view_args or {})
    args.update(request.args.to_dict())
    args['lang'] = 'ru'
    ru_url = url_for(request.endpoint, **args)
    args['lang'] = 'en'
    en_url = url_for(request.endpoint, **args)
    return ru_url, en_url

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_video_duration(filepath):
    clip = VideoFileClip(filepath)
    duration = clip.duration
    clip.close()
    return duration

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    bio = db.Column(db.String(500))
    avatar = db.Column(db.String(256), default=None)
    is_verified = db.Column(db.Boolean, default=False)
    can_receive_messages = db.Column(db.Boolean, default=True)
    is_private = db.Column(db.Boolean, default=False)  # Приватный аккаунт
    is_moderator = db.Column(db.Boolean, default=False)  # Модератор
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    tweets = db.relationship('Tweet', backref='author', lazy=True)
    followers = db.relationship('Follow', foreign_keys='Follow.followed_id', backref='followed', lazy=True)
    following = db.relationship('Follow', foreign_keys='Follow.follower_id', backref='follower', lazy=True)
    is_banned = db.Column(db.Boolean, default=False)
    telegram_id = db.Column(db.String(32), unique=True)
    drafts = db.relationship('Draft', backref='user', lazy=True)
    live_streams = db.relationship('LiveStream', backref='user', lazy=True)
    security = db.relationship('UserSecurity', backref='user', uselist=False, lazy=True)
    webhooks = db.relationship('Webhook', backref='user', lazy=True)
    ad_impressions = db.relationship('AdImpression', backref='user', lazy=True)
    ad_clicks = db.relationship('AdClick', backref='user', lazy=True)

class Tweet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(280), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reply_to_id = db.Column(db.Integer, db.ForeignKey('tweet.id'), nullable=True)
    likes = db.relationship('Like', backref='tweet', lazy=True)
    retweets = db.relationship('Retweet', backref='tweet', lazy=True)
    replies = db.relationship('Tweet', backref=db.backref('parent', remote_side=[id]), lazy=True)
    media_type = db.Column(db.String(10))  # 'image' или 'video'
    media_filename = db.Column(db.String(256))
    media_duration = db.Column(db.Integer)  # в секундах, только для видео
    hashtags = db.relationship('TweetHashtag', backref='tweet', lazy=True)
    poll = db.relationship('Poll', backref='tweet', uselist=False, lazy=True)
    reactions = db.relationship('Reaction', backref='tweet', lazy=True)
    is_edited = db.Column(db.Boolean, default=False)
    edit_history = db.Column(db.Text)  # JSON string of edit history

class Follow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    followed_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tweet_id = db.Column(db.Integer, db.ForeignKey('tweet.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Retweet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tweet_id = db.Column(db.Integer, db.ForeignKey('tweet.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    body = db.Column(db.String(1000), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class MessageRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(32))  # 'mention', 'like', ...
    message = db.Column(db.String(512))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reported_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    tweet_id = db.Column(db.Integer, db.ForeignKey('tweet.id'), nullable=True)
    reason = db.Column(db.String(256))
    status = db.Column(db.String(32), default='pending')  # pending, banned, false
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Hashtag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    tweets = db.relationship('TweetHashtag', backref='hashtag', lazy=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TweetHashtag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tweet_id = db.Column(db.Integer, db.ForeignKey('tweet.id'), nullable=False)
    hashtag_id = db.Column(db.Integer, db.ForeignKey('hashtag.id'), nullable=False)

class Draft(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.String(280))
    media_type = db.Column(db.String(10))
    media_filename = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Poll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tweet_id = db.Column(db.Integer, db.ForeignKey('tweet.id'), nullable=False)
    question = db.Column(db.String(280), nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PollOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'), nullable=False)
    text = db.Column(db.String(100), nullable=False)
    votes = db.Column(db.Integer, default=0)

class PollVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'), nullable=False)
    option_id = db.Column(db.Integer, db.ForeignKey('poll_option.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tweet_id = db.Column(db.Integer, db.ForeignKey('tweet.id'), nullable=False)
    reaction_type = db.Column(db.String(20), nullable=False)  # 'like', 'heart', 'laugh', etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class LiveStream(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    stream_key = db.Column(db.String(100), unique=True)
    is_live = db.Column(db.Boolean, default=False)
    started_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    viewers_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Advertisement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    image_url = db.Column(db.String(256))
    target_url = db.Column(db.String(256))
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    budget = db.Column(db.Float, nullable=False)
    spent = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='pending')  # pending, active, completed, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class AdImpression(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ad_id = db.Column(db.Integer, db.ForeignKey('advertisement.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AdClick(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ad_id = db.Column(db.Integer, db.ForeignKey('advertisement.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserSecurity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_secret = db.Column(db.String(32))
    backup_codes = db.Column(db.String(256))
    last_password_change = db.Column(db.DateTime, default=datetime.utcnow)
    login_history = db.Column(db.Text)  # JSON string of login history

class Webhook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    url = db.Column(db.String(256), nullable=False)
    events = db.Column(db.String(256), nullable=False)  # JSON string of event types
    secret = db.Column(db.String(64), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))     


# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        tweets = Tweet.query.order_by(Tweet.created_at.desc()).all()
        # Популярные пользователи (по количеству подписчиков)
        users_with_followers = (
            db.session.query(User, db.func.count(Follow.id).label('followers_count'))
            .outerjoin(Follow, User.id == Follow.followed_id)
            .group_by(User.id)
            .order_by(db.func.count(Follow.id).desc())
            .limit(20)
            .all()
        )
        # Случайные 5 из топ-20
        popular_users = random.sample(users_with_followers, min(5, len(users_with_followers))) if users_with_followers else []
        ru_url, en_url = get_lang_urls()
        return render_template('index.html', tweets=tweets, popular_users=popular_users, lang=get_locale(), ru_url=ru_url, en_url=en_url)
    return render_template('landing.html', lang=get_locale())

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            flash(_('Username already exists', get_locale()))
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash(_('Email already exists', get_locale()))
            return redirect(url_for('register'))
        
        user = User(username=username, email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        return redirect(url_for('index'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('index'))
        
        flash(_('Invalid username or password', get_locale()))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/tweet', methods=['POST'])
@login_required
def create_tweet():
    content = request.form['content']
    media_file = request.files.get('media')
    media_filename = None
    media_type = None
    media_duration = None
    if media_file and media_file.filename:
        ext = media_file.filename.rsplit('.', 1)[1].lower()
        if ext in ALLOWED_IMAGE_EXTENSIONS:
            media_type = 'image'
        elif ext in ALLOWED_VIDEO_EXTENSIONS:
            media_type = 'video'
        else:
            flash(_('Недопустимый тип файла!', get_locale()))
            return redirect(url_for('index'))
        media_filename = f"{current_user.id}_{int(datetime.utcnow().timestamp())}.{ext}"
        filepath = os.path.join(MEDIA_UPLOAD_FOLDER, media_filename)
        media_file.save(filepath)
        if media_type == 'video':
            try:
                media_duration = int(get_video_duration(filepath))
            except Exception:
                media_duration = None
    if content or media_filename:
        tweet = Tweet(content=content, user_id=current_user.id, media_type=media_type, media_filename=media_filename, media_duration=media_duration)
        db.session.add(tweet)
        db.session.commit()
        # Пинги через @username
        mentioned = set(re.findall(r'@([A-Za-z0-9_]+)', content or ''))
        for username in mentioned:
            user = User.query.filter_by(username=username).first()
            if user and user.id != current_user.id:
                notif = Notification(user_id=user.id, type='mention', message=f'Вас упомянули в твите: "{content[:100]}"')
                db.session.add(notif)
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/avatar/<filename>')
def avatar(filename):
    return send_from_directory(app.config['AVATAR_UPLOAD_FOLDER'], filename)

@app.route('/profile/<username>', methods=['GET', 'POST'])
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    is_follower = False
    if current_user.is_authenticated and current_user != user:
        is_follower = Follow.query.filter_by(follower_id=current_user.id, followed_id=user.id).first() is not None
    # Ограничение приватности
    if user.is_private and (not current_user.is_authenticated or (current_user != user and not is_follower)):
        return render_template('private_profile.html', user=user)
    tweets = Tweet.query.filter_by(user_id=user.id).order_by(Tweet.created_at.desc()).all()
    is_following = False
    if current_user.is_authenticated and current_user != user:
        is_following = Follow.query.filter_by(follower_id=current_user.id, followed_id=user.id).first() is not None
    if request.method == 'POST' and current_user.is_authenticated and current_user == user:
        file = request.files.get('avatar')
        if file and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{user.id}_avatar.{ext}"
            filepath = os.path.join(app.config['AVATAR_UPLOAD_FOLDER'], filename)
            file.save(filepath)
            user.avatar = filename
            db.session.commit()
            flash(_('Avatar updated!', get_locale()))
            return redirect(url_for('profile', username=user.username))
        else:
            flash(_('Invalid file type!', get_locale()))
    ru_url, en_url = get_lang_urls()
    return render_template('profile.html', user=user, tweets=tweets, is_following=is_following, lang=get_locale(), ru_url=ru_url, en_url=en_url)

@app.route('/follow/<username>')
@login_required
def follow(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user != current_user:
        follow = Follow(follower_id=current_user.id, followed_id=user.id)
        db.session.add(follow)
        db.session.commit()
    return redirect(url_for('profile', username=username))

@app.route('/unfollow/<username>')
@login_required
def unfollow(username):
    user = User.query.filter_by(username=username).first_or_404()
    follow = Follow.query.filter_by(follower_id=current_user.id, followed_id=user.id).first()
    if follow:
        db.session.delete(follow)
        db.session.commit()
    return redirect(url_for('profile', username=username))

@app.route('/retweet/<int:tweet_id>', methods=['POST'])
@login_required
def retweet(tweet_id):
    tweet = Tweet.query.get_or_404(tweet_id)
    # Проверка: не ретвитил ли уже этот твит
    existing = Retweet.query.filter_by(user_id=current_user.id, tweet_id=tweet_id).first()
    if not existing:
        retweet = Retweet(user_id=current_user.id, tweet_id=tweet_id)
        db.session.add(retweet)
        db.session.commit()
        flash(_('Retweeted!', get_locale()))
    else:
        flash(_('You have already retweeted this tweet.', get_locale()))
    return redirect(request.referrer or url_for('index'))

@app.route('/followers/<username>')
def followers(username):
    user = User.query.filter_by(username=username).first_or_404()
    followers = [f.follower for f in user.followers]
    following_ids = []
    if current_user.is_authenticated:
        following_ids = [f.followed_id for f in current_user.following]
    return render_template('followers.html', user=user, followers=followers, following_ids=following_ids)

@app.route('/following/<username>')
def following(username):
    user = User.query.filter_by(username=username).first_or_404()
    following = [f.followed for f in user.following]
    following_ids = []
    if current_user.is_authenticated:
        following_ids = [f.followed_id for f in current_user.following]
    return render_template('following.html', user=user, following=following, following_ids=following_ids)

@app.route('/api/users')
def api_users():
    users = User.query.all()
    users_json = [
        {
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'bio': u.bio,
            'avatar': url_for('avatar', filename=u.avatar) if u.avatar else None,
            'is_verified': u.is_verified,
            'created_at': u.created_at.isoformat()
        }
        for u in users
    ]
    return jsonify(users_json)

@app.route('/api/user/<username>')
def api_user(username):
    user = User.query.filter_by(username=username).first_or_404()
    user_json = {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'bio': user.bio,
        'avatar': url_for('avatar', filename=user.avatar) if user.avatar else None,
        'is_verified': user.is_verified,
        'created_at': user.created_at.isoformat()
    }
    return jsonify(user_json)

@app.route('/messages')
@login_required
def messages():
    # Найти всех пользователей, с кем был чат
    dialogs = db.session.query(User).join(Message, or_(Message.sender_id == User.id, Message.recipient_id == User.id)) \
        .filter(or_(Message.sender_id == current_user.id, Message.recipient_id == current_user.id)) \
        .filter(User.id != current_user.id).distinct().all()
    return render_template('messages.html', dialogs=dialogs)

@app.route('/chat/<username>', methods=['GET', 'POST'])
@login_required
def chat(username):
    other = User.query.filter_by(username=username).first_or_404()
    if request.method == 'POST':
        body = request.form['body']
        if body.strip():
            msg = Message(sender_id=current_user.id, recipient_id=other.id, body=body)
            db.session.add(msg)
            db.session.commit()
            flash(_('Message sent!', get_locale()))
        return redirect(url_for('chat', username=username))
    # Получить все сообщения между пользователями
    msgs = Message.query.filter(
        or_(
            (Message.sender_id == current_user.id) & (Message.recipient_id == other.id),
            (Message.sender_id == other.id) & (Message.recipient_id == current_user.id)
        )
    ).order_by(Message.timestamp.asc()).all()
    return render_template('chat.html', other=other, messages=msgs)

@app.route('/like/<int:tweet_id>', methods=['POST'])
@login_required
def like(tweet_id):
    tweet = Tweet.query.get_or_404(tweet_id)
    existing = Like.query.filter_by(user_id=current_user.id, tweet_id=tweet_id).first()
    if not existing:
        like = Like(user_id=current_user.id, tweet_id=tweet_id)
        db.session.add(like)
        db.session.commit()
        flash(_('Liked!', get_locale()))
    else:
        db.session.delete(existing)
        db.session.commit()
        flash(_('Unliked!', get_locale()))
    return redirect(request.referrer or url_for('index'))

@app.route('/reply/<int:tweet_id>', methods=['POST'])
@login_required
def reply(tweet_id):
    tweet = Tweet.query.get_or_404(tweet_id)
    content = request.form.get('reply_content', '').strip()
    if content:
        reply_tweet = Tweet(content=content, user_id=current_user.id, reply_to_id=tweet.id)
        db.session.add(reply_tweet)
        db.session.commit()
        # Пинги через @username в комментарии
        mentioned = set(re.findall(r'@([A-Za-z0-9_]+)', content or ''))
        for username in mentioned:
            user = User.query.filter_by(username=username).first()
            if user and user.id != current_user.id:
                notif = Notification(user_id=user.id, type='mention', message=f'Вас упомянули в комментарии: "{content[:100]}"')
                db.session.add(notif)
        db.session.commit()
        flash(_('Reply sent!', get_locale()))
    return redirect(request.referrer or url_for('index'))

@app.route('/delete_tweet/<int:tweet_id>', methods=['POST'])
@login_required
def delete_tweet(tweet_id):
    tweet = Tweet.query.get_or_404(tweet_id)
    if tweet.user_id != current_user.id:
        flash(_('You can only delete your own tweets!', get_locale()))
        return redirect(request.referrer or url_for('index'))
    db.session.delete(tweet)
    db.session.commit()
    flash(_('Tweet deleted!', get_locale()))
    return redirect(request.referrer or url_for('index'))

@app.route('/start_chat', methods=['POST'])
@login_required
def start_chat():
    username = request.form.get('username', '').strip()
    if not username:
        flash(_('Введите имя пользователя!', get_locale()))
        return redirect(url_for('messages'))
    user = User.query.filter_by(username=username).first()
    if not user:
        flash(_('Пользователь не найден!', get_locale()))
        return redirect(url_for('messages'))
    if user.id == current_user.id:
        flash(_('Нельзя начать чат с самим собой!', get_locale()))
        return redirect(url_for('messages'))
    return redirect(url_for('chat', username=user.username))

@app.route('/media/<filename>')
def media(filename):
    return send_from_directory(app.config['MEDIA_UPLOAD_FOLDER'], filename)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        can_receive = request.form.get('can_receive_messages') == 'on'
        current_user.can_receive_messages = can_receive
        is_private = request.form.get('is_private') == 'on'
        current_user.is_private = is_private
        db.session.commit()
        flash(_('Настройки обновлены!', get_locale()))
        return redirect(url_for('settings'))
    return render_template('settings.html')

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin_panel():
    if current_user.username != 'Devoleper':
        flash(_('Access denied!', get_locale()))
        return redirect(url_for('index'))
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete_tweet':
            tweet_id = request.form.get('tweet_id')
            tweet = Tweet.query.get(tweet_id)
            if tweet:
                db.session.delete(tweet)
                db.session.commit()
                flash(_('Tweet deleted!', get_locale()))
        elif action == 'ban_user':
            user_id = request.form.get('user_id')
            user = User.query.get(user_id)
            if user and user.username != 'Devoleper':
                user.is_banned = True
                db.session.commit()
                flash(_('User banned!', get_locale()))
        elif action == 'unban_user':
            user_id = request.form.get('user_id')
            user = User.query.get(user_id)
            if user:
                user.is_banned = False
                db.session.commit()
                flash(_('User unbanned!', get_locale()))
    users = User.query.all()
    tweets = Tweet.query.all()
    return render_template('admin.html', users=users, tweets=tweets)

@app.route('/notifications', endpoint='notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    return render_template('notifications.html', notifications=notifs)

@app.route('/report/tweet/<int:tweet_id>', methods=['POST'])
@login_required
def report_tweet(tweet_id):
    tweet = Tweet.query.get_or_404(tweet_id)
    # Не даём жаловаться на свои твиты
    if tweet.user_id == current_user.id:
        flash('Нельзя пожаловаться на свой твит!', 'warning')
        return redirect(request.referrer or url_for('index'))
    report = Report(
        reporter_id=current_user.id,
        tweet_id=tweet.id,
        reported_user_id=tweet.user_id,
        reason='tweet abuse',
        status='pending'
    )
    db.session.add(report)
    db.session.commit()
    flash('Жалоба отправлена модераторам!', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/report/user/<int:user_id>', methods=['POST'])
@login_required
def report_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.username == 'Devoleper':
        flash('На этого пользователя нельзя пожаловаться!', 'warning')
        return redirect(request.referrer or url_for('index'))
    if user.id == current_user.id:
        flash('Нельзя пожаловаться на себя!', 'warning')
        return redirect(request.referrer or url_for('index'))
    report = Report(
        reporter_id=current_user.id,
        reported_user_id=user.id,
        reason='user abuse',
        status='pending'
    )
    db.session.add(report)
    db.session.commit()
    flash('Жалоба на пользователя отправлена модераторам!', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/moderator/ban_user/<int:report_id>', methods=['POST'])
@login_required
def moderator_ban_user(report_id):
    if not current_user.is_moderator:
        flash('Доступ только для модераторов!', 'danger')
        return redirect(url_for('index'))
    report = Report.query.get_or_404(report_id)
    user = User.query.get(report.reported_user_id)
    if user:
        user.is_banned = True
        report.status = 'banned'
        db.session.commit()
        flash('Пользователь забанен.', 'success')
    return redirect(url_for('moderator_panel'))

@app.route('/moderator/ban_tweet/<int:report_id>', methods=['POST'])
@login_required
def moderator_ban_tweet(report_id):
    if not current_user.is_moderator:
        flash('Доступ только для модераторов!', 'danger')
        return redirect(url_for('index'))
    report = Report.query.get_or_404(report_id)
    tweet = Tweet.query.get(report.tweet_id)
    if tweet:
        db.session.delete(tweet)
        report.status = 'banned'
        db.session.commit()
        flash('Твит удалён.', 'success')
    return redirect(url_for('moderator_panel'))

@app.route('/moderator/false_report/<int:report_id>', methods=['POST'])
@login_required
def moderator_false_report(report_id):
    if not current_user.is_moderator:
        flash('Доступ только для модераторов!', 'danger')
        return redirect(url_for('index'))
    report = Report.query.get_or_404(report_id)
    report.status = 'false'
    db.session.commit()
    flash('Жалоба помечена как ложная.', 'info')
    return redirect(url_for('moderator_panel'))

@app.route('/moderator')
@login_required
def moderator_panel():
    if not (current_user.is_moderator or current_user.username == 'Devoleper'):
        flash('Доступ только для модераторов!', 'danger')
        return redirect(url_for('index'))
    reports = Report.query.order_by(Report.created_at.desc()).all()
    return render_template('moderator.html', reports=reports)

@app.route('/ban_user/<int:user_id>', methods=['POST'])
@login_required
def ban_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.username == 'Devoleper':
        flash('Нельзя забанить этого пользователя!', 'danger')
        return redirect(url_for('profile', username=user.username))
    # Только модератор или Devoleper может банить
    if not current_user.is_moderator and current_user.username != 'Devoleper':
        flash('Нет прав для бана этого пользователя!', 'danger')
        return redirect(url_for('profile', username=user.username))
    user.is_banned = True
    db.session.commit()
    flash('Пользователь забанен.', 'success')
    return redirect(url_for('profile', username=user.username))

@app.route('/telegram_auth')
def telegram_auth():
    data = request.args.to_dict()
    # Проверка подписи Telegram
    auth_date = int(data.get('auth_date', 0))
    if time.time() - auth_date > 86400:
        flash('Сессия Telegram устарела', 'danger')
        return redirect(url_for('login'))

    check_hash = data.pop('hash', None)
    token = '7583728266:AAGGKkiTkZgq4fGVaFrRcWVSVszBysW_Ibw'  # <-- вставьте сюда токен вашего бота
    secret_key = hashlib.sha256(token.encode()).digest()
    data_check_string = '\n'.join([f'{k}={v}' for k, v in sorted(data.items())])
    h = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if h != check_hash:
        flash('Ошибка проверки Telegram', 'danger')
        return redirect(url_for('login'))

    # Логика: ищем пользователя по telegram_id, если нет — создаём
    telegram_id = data.get('id')
    username = data.get('username', f'tg_{telegram_id}')
    user = User.query.filter_by(telegram_id=telegram_id).first()
    if not user:
        user = User(username=username, telegram_id=telegram_id)
        db.session.add(user)
        db.session.commit()
    login_user(user)
    return redirect(url_for('index'))

@app.context_processor
def inject_lang_urls():
    try:
        ru_url, en_url = get_lang_urls()
    except Exception:
        ru_url, en_url = '#', '#'
    return dict(
        lang=get_locale(),
        ru_url=ru_url,
        en_url=en_url
    )

@app.context_processor
def inject_globals():
    return dict(_=_)

@app.route('/hashtag/<hashtag>')
def hashtag(hashtag):
    hashtag_obj = Hashtag.query.filter_by(name=hashtag).first_or_404()
    tweets = Tweet.query.join(TweetHashtag).filter(TweetHashtag.hashtag_id == hashtag_obj.id).order_by(Tweet.created_at.desc()).all()
    return render_template('hashtag.html', hashtag=hashtag_obj, tweets=tweets)

@app.route('/drafts')
@login_required
def drafts():
    user_drafts = Draft.query.filter_by(user_id=current_user.id).order_by(Draft.updated_at.desc()).all()
    return render_template('drafts.html', drafts=user_drafts)

@app.route('/save_draft', methods=['POST'])
@login_required
def save_draft():
    content = request.form.get('content')
    media_file = request.files.get('media')
    media_filename = None
    media_type = None
    
    if media_file and media_file.filename:
        if allowed_file(media_file.filename):
            media_filename = f"draft_{current_user.id}_{int(datetime.utcnow().timestamp())}.{media_file.filename.rsplit('.', 1)[1].lower()}"
            media_file.save(os.path.join(MEDIA_UPLOAD_FOLDER, media_filename))
            media_type = 'image' if media_file.filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS else 'video'
    
    draft = Draft(
        user_id=current_user.id,
        content=content,
        media_type=media_type,
        media_filename=media_filename
    )
    db.session.add(draft)
    db.session.commit()
    return jsonify({'status': 'success', 'draft_id': draft.id})

@app.route('/edit_tweet/<int:tweet_id>', methods=['POST'])
@login_required
def edit_tweet(tweet_id):
    tweet = Tweet.query.get_or_404(tweet_id)
    if tweet.user_id != current_user.id:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    
    content = request.form.get('content')
    if not content:
        return jsonify({'status': 'error', 'message': 'Content is required'}), 400
    
    # Сохраняем историю редактирования
    edit_history = json.loads(tweet.edit_history or '[]')
    edit_history.append({
        'content': tweet.content,
        'edited_at': datetime.utcnow().isoformat()
    })
    
    tweet.content = content
    tweet.is_edited = True
    tweet.edit_history = json.dumps(edit_history)
    db.session.commit()
    
    return jsonify({'status': 'success'})

@app.route('/create_poll', methods=['POST'])
@login_required
def create_poll():
    question = request.form.get('question')
    options = request.form.getlist('options[]')
    duration = int(request.form.get('duration', 24))  # в часах
    
    if not question or len(options) < 2:
        return jsonify({'status': 'error', 'message': 'Invalid poll data'}), 400
    
    tweet = Tweet(
        content=question,
        user_id=current_user.id,
        media_type='poll'
    )
    db.session.add(tweet)
    db.session.flush()
    
    poll = Poll(
        tweet_id=tweet.id,
        question=question,
        end_time=datetime.utcnow() + timedelta(hours=duration)
    )
    db.session.add(poll)
    
    for option_text in options:
        option = PollOption(poll_id=poll.id, text=option_text)
        db.session.add(option)
    
    db.session.commit()
    return jsonify({'status': 'success', 'tweet_id': tweet.id})

@app.route('/vote_poll/<int:poll_id>', methods=['POST'])
@login_required
def vote_poll(poll_id):
    option_id = request.form.get('option_id')
    if not option_id:
        return jsonify({'status': 'error', 'message': 'Option ID is required'}), 400
    
    poll = Poll.query.get_or_404(poll_id)
    if datetime.utcnow() > poll.end_time:
        return jsonify({'status': 'error', 'message': 'Poll has ended'}), 400
    
    existing_vote = PollVote.query.filter_by(
        user_id=current_user.id,
        poll_id=poll_id
    ).first()
    
    if existing_vote:
        return jsonify({'status': 'error', 'message': 'You have already voted'}), 400
    
    vote = PollVote(
        user_id=current_user.id,
        poll_id=poll_id,
        option_id=option_id
    )
    db.session.add(vote)
    
    option = PollOption.query.get(option_id)
    option.votes += 1
    
    db.session.commit()
    return jsonify({'status': 'success'})

@app.route('/react/<int:tweet_id>', methods=['POST'])
@login_required
def react_to_tweet(tweet_id):
    reaction_type = request.form.get('reaction_type')
    if not reaction_type:
        return jsonify({'status': 'error', 'message': 'Reaction type is required'}), 400
    
    existing_reaction = Reaction.query.filter_by(
        user_id=current_user.id,
        tweet_id=tweet_id,
        reaction_type=reaction_type
    ).first()
    
    if existing_reaction:
        db.session.delete(existing_reaction)
        db.session.commit()
        return jsonify({'status': 'success', 'action': 'removed'})
    
    reaction = Reaction(
        user_id=current_user.id,
        tweet_id=tweet_id,
        reaction_type=reaction_type
    )
    db.session.add(reaction)
    db.session.commit()
    return jsonify({'status': 'success', 'action': 'added'})

@app.route('/start_stream', methods=['POST'])
@login_required
def start_stream():
    title = request.form.get('title')
    description = request.form.get('description')
    
    if not title:
        return jsonify({'status': 'error', 'message': 'Title is required'}), 400
    
    stream_key = hashlib.sha256(f"{current_user.id}{datetime.utcnow().timestamp()}".encode()).hexdigest()
    
    stream = LiveStream(
        user_id=current_user.id,
        title=title,
        description=description,
        stream_key=stream_key,
        is_live=True,
        started_at=datetime.utcnow()
    )
    db.session.add(stream)
    db.session.commit()
    
    return jsonify({
        'status': 'success',
        'stream_key': stream_key,
        'stream_id': stream.id
    })

@app.route('/end_stream/<int:stream_id>', methods=['POST'])
@login_required
def end_stream(stream_id):
    stream = LiveStream.query.get_or_404(stream_id)
    if stream.user_id != current_user.id:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    
    stream.is_live = False
    stream.ended_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'status': 'success'})

@app.route('/admin/ads', methods=['GET', 'POST'])
@login_required
def admin_ads():
    if not current_user.is_moderator:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        image = request.files.get('image')
        target_url = request.form.get('target_url')
        start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d')
        end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d')
        budget = float(request.form.get('budget'))
        
        image_filename = None
        if image and image.filename:
            image_filename = f"ad_{int(datetime.utcnow().timestamp())}.{image.filename.rsplit('.', 1)[1].lower()}"
            image.save(os.path.join(MEDIA_UPLOAD_FOLDER, image_filename))
        
        ad = Advertisement(
            title=title,
            content=content,
            image_url=image_filename,
            target_url=target_url,
            start_date=start_date,
            end_date=end_date,
            budget=budget,
            created_by=current_user.id
        )
        db.session.add(ad)
        db.session.commit()
        
        flash('Advertisement created successfully')
        return redirect(url_for('admin_ads'))
    
    ads = Advertisement.query.order_by(Advertisement.created_at.desc()).all()
    return render_template('admin/ads.html', ads=ads)

@app.route('/admin/ads/<int:ad_id>/approve', methods=['POST'])
@login_required
def approve_ad(ad_id):
    if not current_user.is_moderator:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    
    ad = Advertisement.query.get_or_404(ad_id)
    ad.status = 'active'
    db.session.commit()
    
    return jsonify({'status': 'success'})

@app.route('/admin/ads/<int:ad_id>/reject', methods=['POST'])
@login_required
def reject_ad(ad_id):
    if not current_user.is_moderator:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
    
    ad = Advertisement.query.get_or_404(ad_id)
    ad.status = 'rejected'
    db.session.commit()
    
    return jsonify({'status': 'success'})

@app.route('/webhook/create', methods=['POST'])
@login_required
def create_webhook():
    url = request.form.get('url')
    events = request.form.getlist('events[]')
    
    if not url or not events:
        return jsonify({'status': 'error', 'message': 'URL and events are required'}), 400
    
    secret = hashlib.sha256(f"{current_user.id}{datetime.utcnow().timestamp()}".encode()).hexdigest()
    
    webhook = Webhook(
        user_id=current_user.id,
        url=url,
        events=json.dumps(events),
        secret=secret
    )
    db.session.add(webhook)
    db.session.commit()
    
    return jsonify({
        'status': 'success',
        'webhook_id': webhook.id,
        'secret': secret
    })

@app.route('/security/2fa/enable', methods=['POST'])
@login_required
def enable_2fa():
    if not current_user.security:
        security = UserSecurity(user_id=current_user.id)
        db.session.add(security)
        db.session.flush()
    else:
        security = current_user.security
    
    secret = pyotp.random_base32()
    security.two_factor_secret = secret
    security.two_factor_enabled = True
    
    # Генерируем резервные коды
    backup_codes = [pyotp.random_base32()[:8] for _ in range(10)]
    security.backup_codes = json.dumps(backup_codes)
    
    db.session.commit()
    
    return jsonify({
        'status': 'success',
        'secret': secret,
        'backup_codes': backup_codes
    })

@app.route('/security/2fa/disable', methods=['POST'])
@login_required
def disable_2fa():
    if not current_user.security:
        return jsonify({'status': 'error', 'message': '2FA not enabled'}), 400
    
    current_user.security.two_factor_enabled = False
    current_user.security.two_factor_secret = None
    current_user.security.backup_codes = None
    db.session.commit()
    
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
