# URL Shortener → Deploy ke Vercel (Flask + Supabase)

Project ini sudah disiapkan untuk Vercel **tanpa mengubah logic utama**.

## Perubahan yang ditambahkan
- `api/index.py` → entry WSGI untuk Vercel Functions (Python)
- `vercel.json` → rewrite semua route ke `/api/index` dan set region `sin1`
- `app.py` → `app.secret_key` sekarang dibaca dari ENV `SECRET_KEY`/`FLASK_SECRET_KEY` (fallback dev)

## ENV yang harus diisi (Vercel dashboard)
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SECRET_KEY` (nilai acak panjang untuk sign session cookie)

## Deploy
1. Push ke GitHub (private).
2. Import ke Vercel → Framework: **Other** → Root: `./`
3. Tambah ENV di atas untuk Production & Preview.
4. Deploy.

## Catatan Serverless
- Filesystem read-only; gunakan Supabase untuk data. 
- Session Flask bergantung pada `SECRET_KEY`; gunakan nilai tetap di ENV agar user tidak sering logout.
