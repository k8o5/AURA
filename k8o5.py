import os
import json
import base64
import threading
import webbrowser
import subprocess
import sys

try:
    import flask
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
    import flask

try:
    import yt_dlp
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yt_dlp"])
    import yt_dlp

try:
    import flask_socketio
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask-socketio"])
    import flask_socketio

from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app)

# --- Helper Functions ---
def get_audio_files_and_data():
    """Scans for .mp3 files and returns their names and base64 data URLs."""
    audio_files = sorted([f for f in os.listdir('.') if f.endswith('.mp3')])
    audio_data = {}
    for filename in audio_files:
        try:
            with open(filename, "rb") as f:
                encoded_data = base64.b64encode(f.read()).decode('utf-8')
                audio_data[filename] = f"data:audio/mpeg;base64,{encoded_data}"
        except FileNotFoundError:
            pass
    return audio_files, audio_data

# --- Backend Logic ---
def check_ffmpeg():
    try:
        subprocess.run(['ffmpeg', '-version'], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def install_ffmpeg():
    try:
        print("ffmpeg not found. Attempting to install...")
        # Note: This command is specific to certain environments like Termux.
        # It may need to be adjusted for other systems (e.g., using a package manager like apt, brew, or choco).
        subprocess.check_call(["pkg", "install", "ffmpeg", "-y"])
        print("ffmpeg installed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to install ffmpeg: {e}")
        sys.exit(1)

# --- Flask Routes ---
@app.route('/')
def index():
    initial_audio_files, initial_audio_data = get_audio_files_and_data()
    return render_template_string(html_template, initial_audio_files=json.dumps(initial_audio_files), initial_audio_data=json.dumps(initial_audio_data))

@app.route('/api/get-audio-files', methods=['GET'])
def get_audio_files():
    files, data = get_audio_files_and_data()
    return jsonify({"files": files, "data": data})

def download_audio_thread(query, source, socketio_instance):
    """Target for the download thread to wrap the backend function."""
    download_audio_backend(query, source, socketio_instance)

@socketio.on('download_song')
def handle_download_song(data):
    query = data.get('query')
    source = 'ytsearch'
    if 'youtube.com' in query or 'youtu.be' in query:
        source = 'youtube'
    elif 'soundcloud.com' in query:
        source = 'soundcloud'
    threading.Thread(target=download_audio_thread, args=(query, source, socketio)).start()

# --- CORRECTED DOWNLOAD FUNCTION ---
def download_audio_backend(query, source, socketio):
    """Downloads audio using yt-dlp."""
    if not check_ffmpeg():
        install_ffmpeg()

    # A variable to hold a consistent identifier for the UI, based on the video title.
    download_id = ""

    def progress_hook(d):
        nonlocal download_id
        # This hook is now only responsible for reporting download progress.
        if d['status'] == 'downloading':
            # Use the title from the info_dict as a stable ID for the frontend.
            # This is set once at the beginning of a download.
            current_title = d.get('info_dict', {}).get('title', 'Downloading...')
            if not download_id or download_id != current_title:
                 download_id = current_title

            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            if total_bytes and download_id:
                percentage = d['downloaded_bytes'] / total_bytes * 100
                speed = d.get('speed', 0)
                socketio.emit('download_progress', {
                    'filename': download_id,
                    'percentage': percentage,
                    'total_mb': total_bytes / 1024 / 1024,
                    'speed_kb': speed / 1024
                })
        # We will no longer use the 'finished' status from the hook, as it is unreliable for post-processing.

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': '%(title)s.%(ext)s',
        'progress_hooks': [progress_hook],
        'default_search': source,
        'noplaylist': False, # Ensure playlists are processed
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # First, extract information without downloading to see if it's a playlist.
            info = ydl.extract_info(query, download=False)
            
            # Gracefully handle both playlists and single items by creating a list of entries.
            entries = info.get('entries', [info])
            
            for entry in entries:
                # Set the identifier for the current song in the playlist.
                download_id = entry.get('title', 'Downloading...')
                
                # Emit a 'download_start' event immediately so the UI updates.
                socketio.emit('download_start', {'filename': download_id})
                
                # The download() call is blocking. It will not complete until
                # the file is downloaded AND all post-processing (like MP3 conversion) is done.
                ydl.download([entry['webpage_url']])
                
                # Now that the call has returned, we can be certain the MP3 exists.
                # We signal completion to the frontend, which will trigger a library refresh.
                socketio.emit('download_finished', {'filename': download_id})

    except Exception as e:
        # If an error occurs, notify the frontend.
        socketio.emit('download_error', {'message': str(e), 'filename': download_id or 'unknown'})


# --- COMPLETE HTML, CSS, AND JAVASCRIPT IN ONE BLOCK ---
html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.2/socket.io.js"></script>
    <title>Studio AURA</title>
    <style>
        #download-queue {
            margin-bottom: 24px;
        }
        .download-item {
            display: grid;
            grid-template-columns: 40px 1fr 100px;
            align-items: center;
            padding: 12px 8px;
            border-radius: 6px;
            background: var(--bg-secondary);
            margin-bottom: 8px;
        }
        .download-item .icon {
            width: 40px;
            height: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .download-item .info .title {
            font-weight: 500;
        }
        .download-item .info .status {
            font-size: 0.8rem;
            color: var(--text-secondary);
        }
        .download-item .progress-bar {
            width: 100%;
            height: 6px;
            background: var(--bg-tertiary);
            border-radius: 3px;
            overflow: hidden;
        }
        .download-item .progress-bar-fill {
            width: 0%;
            height: 100%;
            background: var(--accent-primary);
            transition: width 0.1s ease-in-out;
        }
        .install-animation {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            border: 3px solid var(--bg-tertiary);
            border-top-color: var(--accent-primary);
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            to {
                transform: rotate(360deg);
            }
        }
    </style>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&display=swap');
        :root {
            --bg-base: #000000;
            --bg-main: #121212;
            --bg-secondary: #181818;
            --bg-tertiary: #282828;
            --bg-player: #181818;
            --border-color: #2A2A2A;
            --accent-primary: #1DB954;
            --text-primary: #FFFFFF;
            --text-secondary: #b3b3b3;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body, html {
            background-color: var(--bg-base);
            font-family: 'Inter', sans-serif;
            overflow: hidden;
            color: var(--text-primary);
        }
        .workstation-container {
            width: 100%;
            height: 100vh;
            display: grid;
            grid-template-columns: 80px 1fr 300px;
            grid-template-rows: 1fr;
            grid-template-areas: "sidebar main player";
            transition: grid-template-columns 0.3s ease;
        }

        /* Sidebar */
        .sidebar {
            grid-area: sidebar;
            background: var(--bg-base);
            padding: 24px 8px;
            display: flex;
            flex-direction: column;
        }
        .sidebar-header {
            padding: 0 16px 16px;
            font-size: 1.5rem;
            font-weight: 700;
            white-space: nowrap;
            overflow: hidden;
        }
        .sidebar-header .icon-only { display: none; }
        .sidebar-header .full-text { display: none; }
        .nav-item {
            padding: 12px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 500;
            transition: background 0.2s ease, color 0.2s ease;
            display: flex;
            align-items: center;
            gap: 16px;
            color: var(--text-secondary);
        }
        .nav-item-text {
            white-space: nowrap;
            opacity: 0;
            transition: opacity 0.3s ease;
        }
        .nav-item:hover {
            background: var(--bg-tertiary);
            color: var(--text-primary);
        }
        .nav-item.active {
            background: var(--bg-tertiary);
            color: var(--accent-primary);
        }
        .nav-item.active svg {
            filter: drop-shadow(0 0 5px var(--accent-primary));
        }
        .nav-item svg {
            width: 24px;
            height: 24px;
            transition: color 0.2s, filter 0.2s;
            flex-shrink: 0;
        }

        /* Expanded Sidebar on wide screens */
        @media (min-width: 1024px) {
            .workstation-container {
                grid-template-columns: 240px 1fr 300px;
            }
            .sidebar-header .full-text { display: block; }
            .nav-item-text { opacity: 1; }
        }

        /* Main Content */
        .main-content {
            grid-area: main;
            background: var(--bg-main);
            overflow-y: auto;
        }
        .page {
            display: none;
            padding: 24px 32px;
        }
        .page.active {
            display: block;
        }
        .page h1 {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 24px;
        }

        /* Library Page */
        #search-library {
            width: 100%;
            max-width: 400px;
            background: var(--bg-tertiary);
            border: none;
            color: var(--text-primary);
            padding: 12px 16px;
            border-radius: 6px;
            margin-bottom: 24px;
            font-size: 0.9rem;
        }
        .song-list-item {
            display: grid;
            grid-template-columns: 40px 1fr 40px;
            align-items: center;
            padding: 12px 8px;
            border-radius: 6px;
            transition: background 0.2s;
        }
        .song-list-item:hover {
            background: rgba(255,255,255,0.1);
        }
        .play-btn, .delete-btn {
            background: none;
            border: none;
            color: var(--text-secondary);
            cursor: pointer;
            transition: color 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .play-btn svg, .delete-btn svg {
            width: 20px;
            height: 20px;
        }
        .song-list-item:hover .play-btn, .song-list-item:hover .delete-btn {
            color: var(--text-primary);
        }

        /* Downloader Page */
        .downloader-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            height: 70vh;
        }
        .download-form {
            display: flex;
            width: 100%;
            max-width: 600px;
        }
        .downloader-input {
            flex-grow: 1;
            border: 1px solid var(--border-color);
            background: var(--bg-secondary);
            color: var(--text-primary);
            padding: 15px;
            font-size: 1rem;
            border-radius: 50px 0 0 50px;
            border-right: none;
        }
        .download-button {
            background: var(--accent-primary);
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 0 50px 50px 0;
            font-weight: bold;
            font-size: 1rem;
            cursor: pointer;
        }

        /* Effects Page */
        #effects-container {
            display: flex;
            flex-direction: column;
            gap: 24px;
            max-width: 600px;
        }
        .effect-module {
            background: var(--bg-secondary);
            border-radius: 12px;
            padding: 20px;
        }
        .effect-module h3 {
            font-weight: 700;
            margin-bottom: 8px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 12px;
            margin-bottom: 16px;
        }
        .slider-group {
            display: flex;
            flex-direction: column;
            gap: 10px;
            width:100%;
        }
        .slider-label-group {
            display: flex;
            justify-content: space-between;
            font-weight: 500;
            font-size: 1rem;
        }
        .custom-slider {
            -webkit-appearance: none;
            width: 100%;
            height: 4px;
            background: var(--bg-tertiary);
            border-radius: 2px;
            outline: none;
        }
        .custom-slider::-webkit-slider-thumb {
            -webkit-appearance: none;
            appearance: none;
            width: 20px;
            height: 20px;
            background: var(--text-primary);
            border-radius: 50%;
            cursor: pointer;
        }

        /* Player Bar */
        .player-bar {
            grid-area: player;
            background: var(--bg-player);
            padding: 24px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: space-between;
            gap: 20px;
        }
        #visualizer-canvas {
            width: 100%;
            height: 150px;
            background-color: var(--bg-secondary);
            border-radius: 12px;
        }
        #progress-bar-wrapper {
            width: 100%;
            height: 3px;
            background-color: var(--bg-tertiary);
            cursor: pointer;
        }
        #progress-bar-fill {
            width: 0%;
            height: 100%;
            background-color: var(--accent-primary);
            border-radius: 0 3px 3px 0;
        }
        .current-track-info {
            font-weight: 500;
            text-align: center;
        }
        .player-controls {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 20px;
        }
        .control-btn {
            background: none;
            border: none;
            color: var(--text-secondary);
            cursor: pointer;
            transition: color 0.2s;
        }
        .control-btn:hover {
            color: var(--text-primary);
        }
        .control-btn.play-pause-btn {
            background-color: var(--text-primary);
            color: #000;
            width: 48px;
            height: 48px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
        }
        .control-btn.play-pause-btn:hover {
            transform: scale(1.05);
        }
        .control-btn svg {
            width: 24px;
            height: 24px;
        }
        .secondary-controls {
            display: flex;
            align-items: center;
            gap: 20px;
            justify-content: center;
            width: 100%;
        }
        #volume-slider {
            width: 100%;
        }
        #eq-container {
            display: grid;
            grid-template-columns: repeat(10, 1fr);
            gap: 10px;
            width: 100%;
        }
        .eq-band {
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .eq-band input[type=range] {
            -webkit-appearance: slider-vertical;
            width: 8px;
            height: 100px;
        }
    </style>
</head>
<body>
    <div id="workstation-container" class="workstation-container">
        <div class="sidebar">
            <div class="sidebar-header"><span class="full-text">Studio AURA</span></div>
            <div class="nav-item active" data-page="library-page"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path></svg><span class="nav-item-text">Library</span></div>
            <div class="nav-item" data-page="effects-page"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path></svg><span class="nav-item-text">Effects</span></div>
            
        </div>
        <main class="main-content">
            <section id="library-page" class="page active">
                <h1>Music Library</h1>
                <input type="text" id="search-library" placeholder="Paste a YouTube or SoundCloud URL to download...">
                <div id="download-queue"></div>
                <div id="song-list"></div>
            </section>
            <section id="effects-page" class="page">
                <h1>Effects Suite</h1>
                <div id="effects-container"></div>
            </section>
            
        </main>
        <div class="player-bar">
            <canvas id="visualizer-canvas"></canvas>
            <div class="current-track-info">
                <div id="player-song-title">No Song Playing</div>
            </div>
            <div id="progress-bar-wrapper"><div id="progress-bar-fill"></div></div>
            <div class="player-controls">
                <button id="prev-btn" class="control-btn"><svg fill="currentColor" viewBox="0 0 20 20"><path d="M8.445 14.832A1 1 0 0010 14.033V5.967a1 1 0 00-1.555-.832L4 9.167V5a1 1 0 00-2 0v10a1 1 0 002 0v-4.167l4.445 4.032z"></path></svg></button>
                <button id="play-pause-btn" class="control-btn play-pause-btn"><svg id="play-pause-icon" fill="currentColor" viewBox="0 0 20 20"><path d="M10 18a8 8 0 100-