from flask import Flask, request, jsonify
import os
import yt_dlp
import boto3
import tempfile
import traceback

app = Flask(__name__)

@app.route("/upload", methods=["POST"])
def upload_video():
    try:
        # Get JSON data
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data received"}), 400
        
        yt_url = data.get("url")
        if not yt_url:
            return jsonify({"error": "Missing 'url' in request"}), 400
        
        # Check environment variables
        if not os.getenv("R2_ENDPOINT"):
            return jsonify({"error": "R2_ENDPOINT not configured"}), 500
        if not os.getenv("R2_BUCKET"):
            return jsonify({"error": "R2_BUCKET not configured"}), 500
        
        # Download video with yt-dlp
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "video.mp4")
            
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': output_path,
                'quiet': False,
                'no_warnings': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(yt_url, download=True)
                video_title = info.get('title', 'video').replace('/', '-')
            
            # Upload to R2
            s3 = boto3.client(
                "s3",
                endpoint_url=os.getenv("R2_ENDPOINT"),
                aws_access_key_id=os.getenv("R2_ACCESS_KEY"),
                aws_secret_access_key=os.getenv("R2_SECRET_KEY"),
            )
            
            file_name = f"{video_title}.mp4"
            
            with open(output_path, 'rb') as f:
                s3.upload_fileobj(f, os.getenv("R2_BUCKET"), file_name)
            
            # Generate public URL
            bucket = os.getenv("R2_BUCKET")
            endpoint = os.getenv("R2_ENDPOINT")
            public_url = f"{endpoint}/{bucket}/{file_name}"
            
            return jsonify({
                "success": True,
                "url": public_url,
                "title": video_title
            })
    
    except Exception as e:
        # Return detailed error
        error_trace = traceback.format_exc()
        print(f"ERROR: {error_trace}")
        return jsonify({
            "error": str(e),
            "traceback": error_trace
        }), 500

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "message": "YouTube to R2 Uploader API"
    })

@app.route("/test", methods=["GET"])
def test():
    return jsonify({
        "status": "ok",
        "environment": {
            "r2_endpoint": os.getenv("R2_ENDPOINT", "NOT SET"),
            "r2_bucket": os.getenv("R2_BUCKET", "NOT SET"),
            "has_access_key": "YES" if os.getenv("R2_ACCESS_KEY") else "NO",
            "has_secret_key": "YES" if os.getenv("R2_SECRET_KEY") else "NO"
        }
    })

@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200
