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

# Account ID (opsiyonel, public URL için)
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
    """YouTube videosunu en yüksek kalitede indir"""
    temp_dir = tempfile.mkdtemp()

    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet': False,
        'no_warnings': False,
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4'
        }],
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
        logger.info(f"İndirme başlıyor: {y
