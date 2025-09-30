from flask import Flask, request, redirect, render_template, url_for, Response, make_response
from urllib.parse import urlparse
import string
import random
import re
from supabase import create_client, Client
import os
from dotenv import load_dotenv
import logging
from werkzeug.utils import secure_filename
import secrets
from datetime import datetime, timedelta, timezone

app = Flask(__name__, static_folder='static', static_url_path='/static')
logging.basicConfig(level=logging.DEBUG)
load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL dan SUPABASE_KEY harus diatur di environment variables.")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    raise ValueError(f"Gagal menginisialisasi Supabase: {str(e)}")

# Helper functions
def now_utc():
    return datetime.now(timezone.utc)

def generate_short_code(length=6):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def is_valid_custom_code(code):
    return bool(re.match(r'^[a-zA-Z0-9_-]{3,10}$', code))

def code_exists(short_code):
    try:
        response = supabase.table('links').select('short_code').eq('short_code', short_code).execute()
        return len(response.data) > 0
    except Exception as e:
        logging.error(f"Error saat cek kode: {str(e)}")
        return False

def email_exists(email, exclude_user_id=None):
    try:
        query = supabase.table('users').select('email').eq('email', email)
        if exclude_user_id:
            query = query.neq('id', exclude_user_id)
        response = query.execute()
        return len(response.data) > 0
    except Exception as e:
        logging.error(f"Error saat cek email: {str(e)}")
        return False

def folder_name_exists(name, user_id):
    try:
        response = supabase.table('folders').select('name').eq('name', name).eq('user_id', user_id).execute()
        return len(response.data) > 0
    except Exception as e:
        logging.error(f"Error saat cek nama folder: {str(e)}")
        return False

def store_link(short_code, content_type, content, user_id=None, folder_id=None):
    try:
        data = {
            'short_code': short_code,
            'content_type': content_type,
            'content': content,
            'folder_id': folder_id
        }
        if user_id:
            data['user_id'] = user_id
        supabase.table('links').insert(data).execute()
        logging.debug(f"Stored link: short_code={short_code}, folder_id={folder_id}, user_id={user_id}")
    except Exception as e:
        logging.error(f"Error saat menyimpan link: {str(e)}")
        raise

def delete_link(short_code, user_id):
    try:
        response = supabase.table('links').select('*').eq('short_code', short_code).eq('user_id', user_id).execute()
        if not response.data:
            return False
        link = response.data[0]
        if link['content_type'] in ('image', 'document'):
            file_name = link['content'].split('/content/')[-1]
            supabase.storage.from_('content').remove([file_name])
        supabase.table('links').delete().eq('short_code', short_code).eq('user_id', user_id).execute()
        logging.debug(f"Deleted link: short_code={short_code}, user_id={user_id}")
        return True
    except Exception as e:
        logging.error(f"Error saat hapus link: {str(e)}")
        return False

def update_short_code(old_code, new_code, user_id):
    try:
        if code_exists(new_code):
            return False, "Kode kustom sudah digunakan!"
        if not is_valid_custom_code(new_code):
            return False, "Kode kustom tidak valid! Gunakan 3-10 karakter (huruf, angka, _, -)."
        supabase.table('links').update({'short_code': new_code}).eq('short_code', old_code).eq('user_id', user_id).execute()
        logging.debug(f"Updated short_code: {old_code} to {new_code}, user_id={user_id}")
        return True, None
    except Exception as e:
        logging.error(f"Error saat update short_code: {str(e)}")
        return False, str(e)

# Session management via Supabase (no SECRET_KEY)
SESSION_COOKIE_NAME = "session_id"
SESSION_MAX_DAYS = 7

def create_session(user_id):
    token = secrets.token_urlsafe(48)
    expires_at = now_utc() + timedelta(days=SESSION_MAX_DAYS)
    supabase.table('sessions').insert({
        'id': token,
        'user_id': user_id,
        'expires_at': expires_at.isoformat(),
        'revoked': False
    }).execute()
    return token

def get_session_user(token):
    if not token:
        return None
    try:
        response = supabase.table('sessions').select('*').eq('id', token).eq('revoked', False).gt('expires_at', now_utc().isoformat()).execute()
        if not response.data:
            return None
        user_id = response.data[0]['user_id']
        user_response = supabase.table('users').select('id, email').eq('id', user_id).execute()
        if not user_response.data:
            return None
        return user_response.data[0]
    except Exception as e:
        logging.error(f"Error get_session_user: {str(e)}")
        return None

def destroy_session(token):
    if not token:
        return
    try:
        supabase.table('sessions').update({'revoked': True}).eq('id', token).execute()
    except Exception as e:
        logging.error(f"Error destroy_session: {str(e)}")

def current_user():
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return get_session_user(token)

def set_session_cookie(response, token):
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_MAX_DAYS * 86400,
        httponly=True,
        secure=True if 'vercel' in request.host else False,  # Secure in production
        samesite='Lax'
    )

def clear_session_cookie(response):
    response.delete_cookie(SESSION_COOKIE_NAME)

# Routes
@app.route('/')
def index():
    user = current_user()
    folders = []
    if user:
        folders = supabase.table('folders').select('*').eq('user_id', user['id']).execute().data or []
    return render_template('index.html', user=user, folders=folders)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        if email_exists(email):
            return render_template('register.html', error='Email sudah digunakan!')
        try:
            response = supabase.table('users').insert({'email': email, 'password': password}).execute()
            user_id = response.data[0]['id']
            token = create_session(user_id)
            resp = make_response(redirect(url_for('index')))
            set_session_cookie(resp, token)
            return resp
        except Exception as e:
            logging.error(f"Error register: {str(e)}")
            return render_template('register.html', error=str(e))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        response = supabase.table('users').select('*').eq('email', email).eq('password', password).execute()
        if response.data:
            user_id = response.data[0]['id']
            token = create_session(user_id)
            resp = make_response(redirect(url_for('index')))
            set_session_cookie(resp, token)
            return resp
        return render_template('login.html', error='Email atau password salah!')
    return render_template('login.html')

@app.route('/logout')
def logout():
    token = request.cookies.get(SESSION_COOKIE_NAME)
    destroy_session(token)
    resp = make_response(redirect(url_for('index')))
    clear_session_cookie(resp)
    return resp

@app.route('/dashboard')
def dashboard():
    user = current_user()
    if not user:
        return redirect(url_for('login'))
    user_id = user['id']
    page = int(request.args.get('page', 1))
    folder_id = request.args.get('folder_id')
    content_type = request.args.get('content_type')
    per_page = 10

    query = supabase.table('links').select('*').eq('user_id', user_id)
    if folder_id and folder_id.isdigit():
        query = query.eq('folder_id', int(folder_id))
    if content_type:
        query = query.eq('content_type', content_type)

    total_links = len(query.execute().data)
    total_pages = (total_links + per_page - 1) // per_page

    links = query.order('created_at', desc=True).range((page - 1) * per_page, page * per_page - 1).execute().data
    folders = supabase.table('folders').select('*').eq('user_id', user_id).execute().data

    return render_template(
        'dashboard.html',
        user=user,
        links=links,
        page=page,
        total_pages=total_pages,
        folders=folders,
        selected_folder=int(folder_id) if folder_id and folder_id.isdigit() else None
    )

@app.route('/add_folder', methods=['POST'])
def add_folder():
    user = current_user()
    if not user:
        return redirect(url_for('login'))
    folder_name = request.form.get('folder_name', '').strip()
    user_id = user['id']
    if not folder_name:
        return redirect(url_for('dashboard', error='Nama folder tidak boleh kosong!'))
    if folder_name_exists(folder_name, user_id):
        return redirect(url_for('dashboard', error='Nama folder sudah digunakan!'))
    try:
        supabase.table('folders').insert({'name': folder_name, 'user_id': user_id}).execute()
        return redirect(url_for('dashboard', success='Folder berhasil ditambahkan!'))
    except Exception as e:
        logging.error(f"Error add folder: {str(e)}")
        return redirect(url_for('dashboard', error=f'Gagal menambahkan folder: {str(e)}'))

@app.route('/delete_folder/<folder_id>', methods=['POST'])
def delete_folder(folder_id):
    user = current_user()
    if not user:
        return redirect(url_for('login'))
    user_id = user['id']
    try:
        response = supabase.table('folders').select('id').eq('id', folder_id).eq('user_id', user_id).execute()
        if not response.data:
            return redirect(url_for('dashboard', error='Folder tidak ditemukan atau tidak diizinkan!'))
        supabase.table('folders').delete().eq('id', folder_id).eq('user_id', user_id).execute()
        return redirect(url_for('dashboard', success='Folder berhasil dihapus!'))
    except Exception as e:
        logging.error(f"Error delete folder: {str(e)}")
        return redirect(url_for('dashboard', error=f'Gagal menghapus folder: {str(e)}'))

@app.route('/delete_selected_folders', methods=['POST'])
def delete_selected_folders():
    user = current_user()
    if not user:
        return redirect(url_for('login'))
    user_id = user['id']
    selected_folders = request.form.getlist('selected_folders')
    if not selected_folders:
        return redirect(url_for('dashboard', error='Tidak ada folder yang dipilih!'))
    try:
        response = supabase.table('folders').select('id').eq('user_id', user_id).in_('id', selected_folders).execute()
        valid_folder_ids = [row['id'] for row in response.data]
        supabase.table('folders').delete().eq('user_id', user_id).in_('id', valid_folder_ids).execute()
        return redirect(url_for('dashboard', success='Folder terpilih berhasil dihapus!'))
    except Exception as e:
        logging.error(f"Error bulk delete folders: {str(e)}")
        return redirect(url_for('dashboard', error='Terjadi kesalahan saat menghapus folder!'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    user = current_user()
    if not user:
        return redirect(url_for('login'))
    if request.method == 'POST':
        new_email = request.form.get('email', '').strip()
        new_password = request.form.get('password', '').strip()
        updates = {}
        if new_email and new_email != user['email']:
            if email_exists(new_email, exclude_user_id=user['id']):
                return render_template('profile.html', user=user, error='Email sudah digunakan!')
            updates['email'] = new_email
        if new_password:
            updates['password'] = new_password
        if not updates:
            return render_template('profile.html', user=user, error='Tidak ada perubahan yang dilakukan!')
        try:
            supabase.table('users').update(updates).eq('id', user['id']).execute()
            user['email'] = updates.get('email', user['email'])  # Update local user
            return render_template('profile.html', user=user, success='Profil berhasil diperbarui!')
        except Exception as e:
            logging.error(f"Error update profile: {str(e)}")
            return render_template('profile.html', user=user, error=f'Gagal memperbarui profil: {str(e)}')
    return render_template('profile.html', user=user)

@app.route('/shorten', methods=['POST'])
def shorten():
    user = current_user()
    user_id = user['id'] if user else None  # Public: user_id=None
    content_type = request.form['content_type']
    custom_code = request.form.get('custom_code', '').strip()
    folder_id = request.form.get('folder_id')
    folder_id = int(folder_id) if folder_id and folder_id.isdigit() else None

    if custom_code:
        if not is_valid_custom_code(custom_code):
            return render_template('index.html', user=user, error='Kode kustom tidak valid! Gunakan 3-10 karakter (huruf, angka, _, -).')
        if code_exists(custom_code):
            return render_template('index.html', user=user, error='Kode kustom sudah digunakan! Coba kode lain.')
        short_code = custom_code
    else:
        while True:
            short_code = generate_short_code()
