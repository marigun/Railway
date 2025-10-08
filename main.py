import os
import tempfile
from flask import Flask, request, jsonify
import yt_dlp
import boto3
from botocore.client import Config
import logging

app = Flask(__name__)

# Logging ayarları
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# R2 Configuration - Railway'deki değişken isimleriyle eşleşiyor
R2_ENDPOINT = os.environ.get('R2_ENDPOINT')  # https://a20...r2.cloudflarestorage.com
R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY')
R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_KEY')
R2_BUCKET_NAME = os.environ.get('R2_BUCKET')  # youtube-storage

# Endpoint'ten account ID'yi çıkar (opsiyonel, URL için)
if R2_ENDPOINT:
    R2_ACCOUNT_ID = R2_ENDPOINT.split('//')[1].split('.')[0] if '//' in R2_ENDPOINT else None
else:
    R2_ACCOUNT_ID = None

# R2 değişkenlerini kontrol et
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
    """YouTube videosunu indir"""
    try:
        # Geçici dizin oluştur
        temp_dir = tempfile.mkdtemp()
        
        # yt-dlp ayarları - Android client kullan (çerez gerektirmez)
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
            # Android client kullan - bot korumasını bypass eder
            'extractor_args': {
                'youtube': {
                    'player_client': ['android'],
                    'skip': ['dash', 'hls']
                }
            },
            # Android User-Agent
            'http_headers': {
                'User-Agent': 'com.google.android.youtube/17.36.4 (Linux; U; Android 12; GB) gzip',
            }
        }
        
        logger.info(f"İndirme başlıyor: {youtube_url}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            video_id = info['id']
            video_ext = info['ext']
            video_title = info['title']
            local_path = os.path.join(temp_dir, f"{video_id}.{video_ext}")
            
            logger.info(f"Video indirildi: {local_path}")
            
            return local_path, video_id, video_ext, video_title, temp_dir
            
    except Exception as e:
        logger.error(f"Video indirme hatası: {str(e)}")
        raise

def upload_to_r2(local_path, video_id, video_ext):
    """Videoyu R2'ye yükle"""
    try:
        if not s3_client:
            raise Exception("R2 client başlatılamadı. Environment variables kontrol edin.")
        
        # R2'deki dosya adı
        r2_key = f"videos/{video_id}.{video_ext}"
        
        logger.info(f"R2'ye yükleniyor: {r2_key}")
        logger.info(f"Bucket: {R2_BUCKET_NAME}")
        
        # Dosyayı yükle
        with open(local_path, 'rb') as file:
            s3_client.upload_fileobj(
                file,
                R2_BUCKET_NAME,
                r2_key,
                ExtraArgs={'ContentType': 'video/mp4'}
            )
        
        # Public URL oluştur (R2 public domain varsa kullan)
        if R2_ACCOUNT_ID:
            public_url = f"https://{R2_ACCOUNT_ID}.r2.dev/{r2_key}"
        else:
            # Varsayılan format
            public_url = f"{R2_ENDPOINT.rstrip('/')}/{R2_BUCKET_NAME}/{r2_key}"
        
        logger.info(f"Yükleme tamamlandı: {public_url}")
        
        return public_url, r2_key
        
    except Exception as e:
        logger.error(f"R2 yükleme hatası: {str(e)}")
        raise

def cleanup(temp_dir):
    """Geçici dosyaları temizle"""
    try:
        import shutil
        shutil.rmtree(temp_dir)
        logger.info("Geçici dosyalar temizlendi")
    except Exception as e:
        logger.error(f"Temizleme hatası: {str(e)}")

@app.route('/upload', methods=['POST'])
@app.route('/upload_video', methods=['POST'])
def upload_video():
    """YouTube videosunu indir ve R2'ye yükle"""
    temp_dir = None
    
    try:
        # Request'ten YouTube URL'ini al
        data = request.get_json()
        
        # Hem 'url' hem 'yt_url' parametresini kabul et
        youtube_url = data.get('yt_url') or data.get('url')
        
        if not youtube_url:
            return jsonify({
                'error': 'YouTube URL gerekli (yt_url veya url parametresi)',
                'success': False
            }), 400
        logger.info(f"İşlem başladı: {youtube_url}")
        
        # Videoyu indir
        local_path, video_id, video_ext, video_title, temp_dir = download_video(youtube_url)
        
        # R2'ye yükle
        public_url, r2_key = upload_to_r2(local_path, video_id, video_ext)
        
        # Geçici dosyaları temizle
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
        
        # Hata durumunda da temizlik yap
        if temp_dir:
            cleanup(temp_dir)
        
        return jsonify({
            'error': str(e),
            'success': False
        }), 500

@app.route('/health', methods=['GET'])
def health():
    """Sağlık kontrolü"""
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
