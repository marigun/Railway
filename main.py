import os
import tempfile
from flask import Flask, request, jsonify
import yt_dlp
import boto3
from botocore.client import Config
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# R2 config
R2_ENDPOINT = os.environ.get('R2_ENDPOINT')
R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_KEY')
R2_BUCKET_NAME = os.environ.get('R2_BUCKET')

if R2_ENDPOINT:
    R2_ACCOUNT_ID = R2_ENDPOINT.split('//')[1].split('.')[0] if '//' in R2_ENDPOINT else None
else:
    R2_ACCOUNT_ID = None

def check_r2_config():
    missing = [name for name, val in [('R2_ENDPOINT', R2_ENDPOINT), 
                                      ('R2_ACCESS_KEY', R2_ACCESS_KEY_ID), 
                                      ('R2_SECRET_KEY', R2_SECRET_ACCESS_KEY), 
                                      ('R2_BUCKET', R2_BUCKET_NAME)] if not val]
    if missing:
        raise ValueError(f"Eksik R2 env vars: {missing}")
    logger.info("R2 configuration OK")

try:
    check_r2_config()
    s3_client = boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version='s3v4'),
        region_name='auto'
    )
    logger.info("R2 client initialized successfully")
except Exception as e:
    logger.error(f"R2 client initialization failed: {str(e)}")
    s3_client = None

def download_video(youtube_url):
    temp_dir = tempfile.mkdtemp()
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
        'merge_output_format': 'mp4',  # ffmpeg ile birleştirme
        'quiet': False,
        'no_warnings': False,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        },
        'nocheckcertificate': True,
        'geo_bypass': True,
    }
    logger.info(f"Downloading: {youtube_url}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        video_id = info['id']
        video_ext = 'mp4'
        video_title = info.get('title', video_id)
        local_path = os.path.join(temp_dir, f"{video_id}.{video_ext}")
        logger.info(f"Video downloaded: {local_path}")
        return local_path, video_id, video_ext, video_title, temp_dir

def upload_to_r2(local_path, video_id, video_ext):
    if not s3_client:
        raise Exception("R2 client yok")
    r2_key = f"videos/{video_id}.{video_ext}"
    with open(local_path, 'rb') as file:
        s3_client.upload_fileobj(file, R2_BUCKET_NAME, r2_key, ExtraArgs={'ContentType': 'video/mp4'})
    if R2_ACCOUNT_ID:
        public_url = f"https://{R2_ACCOUNT_ID}.r2.dev/{r2_key}"
    else:
        public_url = f"{R2_ENDPOINT.rstrip('/')}/{R2_BUCKET_NAME}/{r2_key}"
    logger.info(f"Uploaded to R2: {public_url}")
    return public_url, r2_key

def cleanup(temp_dir):
    import shutil
    shutil.rmtree(temp_dir)
    logger.info("Temporary files cleaned")

@app.route('/upload', methods=['POST'])
def upload_video():
    temp_dir = None
    try:
        data = request.get_json()
        youtube_url = data.get('yt_url') or data.get('url')
        if not youtube_url:
            return jsonify({'error': 'YouTube URL gerekli', 'success': False}), 400
        local_path, video_id, video_ext, video_title, temp_dir = download_video(youtube_url)
        public_url, r2_key = upload_to_r2(local_path, video_id, video_ext)
        cleanup(temp_dir)
        return jsonify({
            'success': True,
            'video_id': video_id,
            'video_title': video_title,
            'r2_url': public_url,
            'r2_key': r2_key
        }), 200
    except Exception as e:
        logger.error(str(e))
        if temp_dir:
            cleanup(temp_dir)
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
