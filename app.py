from flask import Flask, request, redirect, render_template, url_for, Response
from urllib.parse import urlparse
import string
import random
import re
from supabase import create_client, Client
import os
from dotenv import load_dotenv
import logging
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static', static_url_path='/static')
# Tidak perlu secret_key karena tidak pakai session

logging.basicConfig(level=logging.DEBUG)
load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL dan SUPABASE_KEY harus diatur di file .env.")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    raise ValueError(f"Gagal menginisialisasi Supabase: {str(e)}")

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

def store_link(short_code, content_type, content, folder_id=None):
    try:
        supabase.table('links').insert({
            'short_code': short_code,
            'content_type': content_type,
            'content': content,
            'folder_id': folder_id
        }).execute()
        logging.debug(f"Stored link: short_code={short_code}, folder_id={folder_id}")
    except Exception as e:
        logging.error(f"Error saat menyimpan link: {str(e)}")
        raise

@app.route('/')
def index():
    # Tidak ada user, tidak ada folder
    return render_template('index.html')

@app.route('/shorten', methods=['POST'])
def shorten():
    content_type = request.form['content_type']
    custom_code = request.form.get('custom_code', '').strip()
    folder_id = request.form.get('folder_id')
    folder_id = int(folder_id) if folder_id and folder_id.isdigit() else None

    if custom_code:
        if not is_valid_custom_code(custom_code):
            return render_template('index.html', error='Kode kustom tidak valid! Gunakan 3-10 karakter (huruf, angka, _, -).')
        if code_exists(custom_code):
            return render_template('index.html', error='Kode kustom sudah digunakan! Coba kode lain.')
        short_code = custom_code
    else:
        while True:
            short_code = generate_short_code()
            if not code_exists(short_code):
                break

    content = ''
    if content_type == 'url':
        content = request.form.get('url', '')
        if not content.startswith(('http://', 'https://')):
            content = 'http://' + content
    elif content_type == 'text':
        content = request.form.get('text', '')
    elif content_type in ('image', 'document'):
        file = request.files.get('file')
        if file:
            allowed_extensions = {
                'image': ['jpg', 'jpeg', 'png'],
                'document': ['pdf', 'docx']
            }
            file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
            if content_type == 'image' and file_ext not in allowed_extensions['image']:
                return render_template('index.html', error=f'File tidak valid! Gunakan {", ".join(allowed_extensions["image"])} untuk gambar.')
            if content_type == 'document' and file_ext not in allowed_extensions['document']:
                return render_template('index.html', error=f'File tidak valid! Gunakan {", ".join(allowed_extensions["document"])} untuk dokumen.')
            
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            if file_size > 10 * 1024 * 1024:
                return render_template('index.html', error='File terlalu besar! Maksimum 10MB.')
            
            file_name = f"{short_code}_{file.filename.replace(' ', '_')}"
            content_type_map = {
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'png': 'image/png',
                'pdf': 'application/pdf',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            }
            try:
                file_content = file.read()
                supabase.storage.from_('content').upload(
                    file_name,
                    file_content,
                    {'content-type': content_type_map.get(file_ext, 'application/octet-stream')}
                )
                content = supabase.storage.from_('content').get_public_url(file_name)
            except Exception as e:
                logging.error(f"Error saat upload file: {str(e)}")
                return render_template('index.html', error=f'Gagal mengunggah file: {str(e)}')
        else:
            return render_template('index.html', error='Harap unggah file!')

    if not content:
        return render_template('index.html', error='Konten tidak valid! Pastikan URL, teks, atau file diisi.')

    try:
        store_link(short_code, content_type, content, folder_id)
    except Exception as e:
        return render_template('index.html', error=f'Gagal menyimpan link: {str(e)}')

    domain = urlparse(request.base_url).netloc
    short_url = f"http://{domain}/{short_code}"
    return render_template('index.html', short_url=short_url, success=f'Berhasil memendekkan! Link Anda: {short_url}')

@app.route('/<short_code>')
def redirect_url(short_code):
    response = supabase.table('links').select('*').eq('short_code', short_code).execute()
    if not response.data:
        return render_template('404.html'), 404

    link = response.data[0]
    content_type = link['content_type']
    content = link['content']
    return render_template('content.html', content_type=content_type, content=content, short_code=short_code)

@app.route('/download/<short_code>')
def download(short_code):
    response = supabase.table('links').select('*').eq('short_code', short_code).execute()
    if not response.data:
        return render_template('404.html'), 404

    link = response.data[0]
    content_type = link['content_type']
    content = link['content']

    if content_type == 'url':
        return redirect(url_for('index', error='Konten URL tidak dapat diunduh!'))

    try:
        if content_type == 'text':
            file_data = content.encode('utf-8')
            original_filename = secure_filename(f"{short_code}.txt")
            return Response(
                file_data,
                mimetype='text/plain',
                headers={'Content-Disposition': f'attachment; filename="{original_filename}"'}
            )
        elif content_type in ('image', 'document'):
            file_path = content.split('/content/')[-1]
            file_data = supabase.storage.from_('content').download(file_path)
            if '_' in file_path:
                original_filename = file_path.split('_', 1)[1]
            else:
                original_filename = file_path
            if '.' in original_filename:
                name_part, ext = original_filename.rsplit('.', 1)
                name_part = name_part.rstrip('_')
                original_filename = f"{name_part}.{ext}"
            else:
                original_filename = original_filename.rstrip('_')
            original_filename = secure_filename(original_filename)
            file_ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''
            content_type_map = {
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'png': 'image/png',
                'pdf': 'application/pdf',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            }
            return Response(
                file_data,
                mimetype=content_type_map.get(file_ext, 'application/octet-stream'),
                headers={'Content-Disposition': f'attachment; filename="{original_filename}"'}
            )
        else:
            return redirect(url_for('index', error='Konten tidak dapat diunduh!'))
    except Exception as e:
        logging.error(f"Error saat download file: {str(e)}")
        return redirect(url_for('index', error=f'Gagal mengunduh file: {str(e)}'))

if __name__ == '__main__':
    app.run(debug=True)
