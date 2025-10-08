import os
import tempfile
from flask import Flask, request, jsonify
import yt_dlp
import boto3
from botocore.client import Config
import logging
import shutil

app = Flask(__name__)

# Logging ayarları
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# R2 Configuration
R2_ENDPOINT = os.environ.get('R2_ENDPOINT')
R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_KEY')
R2_BUCKET_NAME = os.environ.get('R2_BUCKET')

# Account ID (opsiyonel)
if R2_ENDPOINT:
    R2_ACCOUNT_ID = R2_ENDPOINT.split('//')[1].split('.')[0] if '//' in R2_ENDPOINT else None
else:
    R2_ACCOUNT_ID = None


def check_r2_config():
    missing = []
    if not R2_ENDPOINT:
        missing.append('R2_ENDPOINT')
    if not R2_ACCESS_KEY_ID:
        missing.append('R2_ACCESS_KEY')
    if not R2_SECRET_ACCESS_KEY:
        missing.append('R2_SECRET_KEY')
    if not R2_BUCKET_NAME:
        missing.append('R2_BUCKET')

    if missing:
        raise ValueError(f"Eksik R2 environment variables: {', '.join(missing)}")

    logger.info("R2 configuration OK")


# R2 Client
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
    """YouTube videosunu en yüksek kalitede indir (yeniden encode etmeden)."""
    temp_dir = tempfile.mkdtemp()

    ydl_opts = {
        # En yüksek çözünürlükte video + ses
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
        'merge_output_format': 'mp4',

        # Yeniden encode ETMEDEN biçim dönüştür
        'postprocessors': [{
            'key': 'FFmpegVideoRemuxer',
            'preferedformat': 'mp4'
        }],

        # Log detayları
        'quiet': False,
        'verbose': True,
        'no_warnings': False,

        # YouTube client ve header ayarları
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web']
            }
        },
        'http_headers': {
            'User-Agent': 'com.google.ios.youtube/19.09.3 (iPhone14,3; U; CPU iOS 15_6 like Mac OS X)',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'nocheckcertificate': True,
        'geo_bypass': True,
    }

    try:
        logger.info(f"İndirme başlıyor: {youtube_url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            video_id = info['id']
            video_ext = 'mp4'
            video_title = info.get('title', 'video')
            local_path = os.path.join(temp_dir, f"{video_id}.mp4")

            logger.info(f"Video indirildi: {local_path}")
            return local_path, video_id, video_ext, video_title, temp_dir

    except Exception as first_error:
        logger.warning(f"İlk deneme başarısız: {str(first_error)}")
        logger.info("Alternatif yöntem deneniyor...")

        fallback_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
            'merge_output_format': 'mp4',
            'quiet': True,
            'postprocessors': [{
                'key': 'FFmpegVideoRemuxer',
                'preferedformat': 'mp4'
            }]
        }

        with yt_dlp.YoutubeDL(fallback_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            video_id = info['id']
            video_ext = 'mp4'
            video_title = info.get('title', 'video')
            local_path = os.path.join(temp_dir, f"{video_id}.mp4")

            logger.info(f"Video indirildi (fallback): {local_path}")
            return local_path, video_id, video_ext, video_title, temp_dir


def upload_to_r2(local_path, video_id, video_ext):
    """Videoyu R2'ye yükle"""
    if not s3_client:
        raise Exception("R2 client başlatılamadı. Environment variables kontrol edin.")

    r2_key = f"videos/{video_id}.{video_ext}"

    logger.info(f"R2'ye yükleniyor: {r2_key}")
    with open(local_path, 'rb') as file:
        s3_client.upload_fileobj(
            file,
            R2_BUCKET_NAME,
            r2_key,
            ExtraArgs={'ContentType': 'video/mp4'}
        )

    if R2_ACCOUNT_ID:
        public_url = f"https://{R2_ACCOUNT_ID}.r2.dev/{r2_key}"
    else:
        public_url = f"{R2_ENDPOINT.rstrip('/')}/{R2_BUCKET_NAME}/{r2_key}"

    logger.info(f"Yükleme tamamlandı: {public_url}")
    return public_url, r2_key


def cleanup(temp_dir):
    """Geçici dosyaları temizle"""
    try:
        shutil.rmtree(temp_dir)
        logger.info("Geçici dosyalar temizlendi")
    except Exception as e:
        logger.error(f"Temizleme hatası: {str(e)}")


@app.route('/upload', methods=['POST'])
@app.route('/upload_video', methods=['POST'])
def upload_video():
    temp_dir = None
    try:
        data = request.get_json()
        youtube_url = data.get('yt_url') or data.get('url')

        if not youtube_url:
            return jsonify({
                'error': 'YouTube URL gerekli (yt_url veya url parametresi)',
                'success': False
            }), 400

        logger.info(f"İşlem başladı: {youtube_url}")

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
        logger.error(f"Hata: {str(e)}")
        if temp_dir:
            cleanup(temp_dir)
        return jsonify({'error': str(e), 'success': False}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'}), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
