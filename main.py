from flask import Flask, request, jsonify
import os
from pytube import YouTube
import boto3
from io import BytesIO

app = Flask(__name__)

@app.route("/upload", methods=["POST"])
def upload_video():
    data = request.get_json()
    yt_url = data.get("url")
    if not yt_url:
        return jsonify({"error": "Missing URL"}), 400
    try:
        yt = YouTube(yt_url)
        stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
        buffer = BytesIO()
        stream.stream_to_buffer(buffer)
        buffer.seek(0)

        s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("R2_ENDPOINT"),
            aws_access_key_id=os.getenv("R2_ACCESS_KEY"),
            aws_secret_access_key=os.getenv("R2_SECRET_KEY"),
        )
        file_name = f"{yt.title}.mp4"
        s3.upload_fileobj(buffer, os.getenv("R2_BUCKET"), file_name)
        url = f"{os.getenv('R2_ENDPOINT')}/{os.getenv('R2_BUCKET')}/{file_name}"
        return jsonify({"url": url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/")
def home():
    return "✅ API is running!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
