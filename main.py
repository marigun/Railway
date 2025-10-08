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

# R2 Configuration
R2_ACCOUNT_ID = os.environ.get('R2_ACCOUNT_ID')
R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME')

# R2 Client
s3_client = boto3.client(
    's3',
    endpoint_url=f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    config=Config(signature_version='s3v4'),
    region_name='auto'
)

def download_video(youtube_url):
    """YouTube videosunu indir"""
    try:
        # Geçici dizin oluştur
        temp_dir = tempfile.mkdtemp()
        
        # yt-dlp ayarları - Çerez ve User-Agent ekle
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
            # Bot korumasını aşmak için ayarlar
            'cookiesfrombrowser': ('chrome',),  # Chrome tarayıcısından çerezleri kullan
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'skip': ['dash', 'hls']
                }
            },
            # User-Agent ekle
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
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
        # R2'deki dosya adı
        r2_key = f"videos/{video_id}.{video_ext}"
        
        logger.info(f"R2'ye yükleniyor: {r2_key}")
        
        # Dosyayı yükle
        with open(local_path, 'rb') as file:
            s3_client.upload_fileobj(
                file,
                R2_BUCKET_NAME,
                r2_key,
                ExtraArgs={'ContentType': 'video/mp4'}
            )
        
        # Public URL oluştur
        public_url = f"https://{R2_BUCKET_NAME}.r2.dev/{r2_key}"
        
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

@app.route('/upload_video', methods=['POST'])
def upload_video():
    """YouTube videosunu indir ve R2'ye yükle"""
    temp_dir = None
    
    try:
        # Request'ten YouTube URL'ini al
        data = request.get_json()
        
        if not data or 'yt_url' not in data:
            return jsonify({
                'error': 'YouTube URL gerekli',
                'success': False
            }), 400
        
        youtube_url = data['yt_url']
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
