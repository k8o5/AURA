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
                <button id="play-pause-btn" class="control-btn play-pause-btn"><svg id="play-pause-icon" fill="currentColor" viewBox="0 0 20 20"><path d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8.13v3.74a1 1 0 001.555.832l3.197-1.87a1 1 0 000-1.664l-3.197-1.87z" clip-rule="evenodd"></path></svg></button>
                <button id="next-btn" class="control-btn"><svg fill="currentColor" viewBox="0 0 20 20"><path d="M11.555 5.168A1 1 0 0010 5.967v8.066a1 1 0 001.555.832l4.445-4.033a1 1 0 000-1.664l-4.445-4.033zM4.445 14.832A1 1 0 006 14.033V5.967a1 1 0 00-1.555-.832L0 9.167V5a1 1 0 00-2 0v10a1 1 0 002 0v-4.167l4.445 4.032z"></path></svg></button>
            </div>
            <div class="secondary-controls">
                <input type="range" id="volume-slider" class="custom-slider" min="0" max="1" step="0.01" value="1">
            </div>
        </div>
    </div>
    <script>
        // --- DATA PLACEHOLDERS ---
        let audioFileNames = {{ initial_audio_files|safe }};
        let audioData = {{ initial_audio_data|safe }};

        // --- GLOBAL STATE ---
        let currentTrackIndex = -1;
        let isAutoplayOn = true; 

        // --- CONSTANTS & DOM ELEMENTS ---
        const PLAY_ICON_PATH = `<path d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8.13v3.74a1 1 0 001.555.832l3.197-1.87a1 1 0 000-1.664l-3.197-1.87z" clip-rule="evenodd"></path>`;
        const PAUSE_ICON_PATH = `<path d="M10 18a8 8 0 100-16 8 8 0 000 16zM7 9a1 1 0 00-1 1v4a1 1 0 102 0v-4a1 1 0 00-1-1zm5 0a1 1 0 00-1 1v4a1 1 0 102 0v-4a1 1 0 00-1-1z" clip-rule="evenodd"></path>`;
        const canvas = document.getElementById('visualizer-canvas');
        const canvasCtx = canvas.getContext('2d');

        // --- WEB AUDIO API STATE ---
        let audioContext, sourceNode, gainNode, analyser, distortion, reverb, wetGain, dryGain, compressor, panner, eqBands;
        let isPlaying = false, currentBuffer = null, startTime = 0, pauseOffset = 0, animationFrameId;

        // --- SOCKET.IO ---
        const socketio = io();

        socketio.on('download_start', (data) => {
            addDownloadItem(data.filename);
        });

        socketio.on('download_progress', (data) => {
            const item = document.getElementById(`download-${data.filename}`);
            if (item) {
                const progressBarFill = item.querySelector('.progress-bar-fill');
                const status = item.querySelector('.status');
                progressBarFill.style.width = `${data.percentage}%`;
                status.textContent = `Downloading... ${data.percentage.toFixed(1)}% at ${(data.speed_kb / 1024).toFixed(2)} MB/s`;
            }
        });

        socketio.on('download_finished', (data) => {
            const item = document.getElementById(`download-${data.filename}`);
            if (item) {
                item.remove();
            }
            updatePlaylist();
        });

        socketio.on('download_error', (data) => {
            alert(`Download failed for "${data.filename}": ${data.message}`);
            const item = document.getElementById(`download-${data.filename}`);
            if (item) {
                item.remove();
            }
        });

        function addDownloadItem(filename) {
            const queue = document.getElementById('download-queue');
            
            // Prevent duplicate entries
            if (document.getElementById(`download-${filename}`)) return;

            const item = document.createElement('div');
            item.className = 'download-item';
            item.id = `download-${filename}`;
            item.innerHTML = `
                <div class="icon"><div class="install-animation"></div></div>
                <div class="info">
                    <div class="title">${filename}</div>
                    <div class="status">Preparing...</div>
                </div>
                <div class="progress-bar"><div class="progress-bar-fill" style="width: 0%;"></div></div>
            `;
            queue.appendChild(item);
        }

        // --- INITIALIZATION ---
        function initialize() {
            const effectsContainer = document.getElementById('effects-container');
            effectsContainer.innerHTML = `
                <div class="effect-module"><h3>Playback</h3><div class="slider-group"><div class="slider-label-group"><span>Speed</span><span id="speed-val">1.0x</span></div><input type="range" id="speed-slider" class="custom-slider" min="0.5" max="2" step="0.01" value="1"></div></div>
                <div class="effect-module"><h3>Ambiance & Tone</h3><div class="slider-group" style="gap: 16px;"><div class="slider-label-group"><span>Reverb</span><span id="reverb-val">0%</span></div><input type="range" id="reverb-slider" class="custom-slider" min="0" max="1" step="0.01" value="0"><div class="slider-label-group"><span>Distortion</span><span id="distortion-val">0%</span></div><input type="range" id="distortion-slider" class="custom-slider" min="0" max="1" step="0.01" value="0"></div></div>
                <div class="effect-module"><h3>10-Band Equalizer</h3><div id="eq-container"></div></div>
                <div class="effect-module"><h3>Compressor</h3><div class="slider-group"><div class="slider-label-group"><span>Threshold</span><span id="comp-thresh-val">-24 dB</span></div><input type="range" id="comp-thresh-slider" class="custom-slider" min="-100" max="0" step="1" value="-24"><div class="slider-label-group"><span>Knee</span><span id="comp-knee-val">30</span></div><input type="range" id="comp-knee-slider" class="custom-slider" min="0" max="40" step="1" value="30"><div class="slider-label-group"><span>Ratio</span><span id="comp-ratio-val">12</span></div><input type="range" id="comp-ratio-slider" class="custom-slider" min="1" max="20" step="1" value="12"><div class="slider-label-group"><span>Attack</span><span id="comp-attack-val">0.003 s</span></div><input type="range" id="comp-attack-slider" class="custom-slider" min="0" max="1" step="0.001" value="0.003"><div class="slider-label-group"><span>Release</span><span id="comp-release-val">0.25 s</span></div><input type="range" id="comp-release-slider" class="custom-slider" min="0" max="1" step="0.01" value="0.25"></div></div>
                <div class="effect-module"><h3>Panner</h3><div class="slider-group"><div class="slider-label-group"><span>Pan</span><span id="pan-val">0</span></div><input type="range" id="pan-slider" class="custom-slider" min="-1" max="1" step="0.01" value="0"></div></div>`;

            const eqContainer = document.getElementById('eq-container');
            const frequencies = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
            for (let i = 0; i < frequencies.length; i++) {
                const freq = frequencies[i];
                const eqBand = document.createElement('div');
                eqBand.className = 'eq-band';
                eqBand.innerHTML = `
                    <label>${freq < 1000 ? freq : (freq / 1000) + 'k'}Hz</label>
                    <input type="range" class="eq-slider" min="-20" max="20" step="0.5" value="0" data-index="${i}">
                `;
                eqContainer.appendChild(eqBand);
            }

            setupEventListeners();
            renderSongList();
            setupMediaSession();
        }

        function initAudio() {
            if (audioContext) return;
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            gainNode = audioContext.createGain();
            analyser = audioContext.createAnalyser();
            distortion = audioContext.createWaveShaper();
            reverb = audioContext.createConvolver();
            wetGain = audioContext.createGain();
            dryGain = audioContext.createGain();
            compressor = audioContext.createDynamicsCompressor();
            panner = audioContext.createStereoPanner();

            const frequencies = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
            eqBands = frequencies.map(freq => {
                const filter = audioContext.createBiquadFilter();
                filter.type = 'peaking';
                filter.frequency.value = freq;
                filter.Q.value = 1;
                filter.gain.value = 0;
                return filter;
            });

            analyser.fftSize = 256;

            createReverbImpulse().then(buffer => { reverb.buffer = buffer; });
            
            // Connect nodes in a chain
            let lastNode = gainNode;
            eqBands.forEach(filter => {
                lastNode.connect(filter);
                lastNode = filter;
            });
            lastNode.connect(panner).connect(compressor).connect(distortion).connect(analyser);

            analyser.connect(dryGain).connect(audioContext.destination);
            analyser.connect(wetGain).connect(reverb).connect(audioContext.destination);

            resetEffects();
        }
        
        // --- AUDIO PLAYBACK ---
        async function playSong(index, offset = 0) {
            if (index < 0 || index >= audioFileNames.length) return;
            if (!audioContext) initAudio();
            if (isPlaying) stopSong();

            currentTrackIndex = index;
            const fileName = audioFileNames[index];
            const dataUrl = audioData[fileName];

            if (!dataUrl) {
                document.getElementById('player-song-title').textContent = "Error: File data missing";
                return;
            }

            try {
                document.getElementById('player-song-title').textContent = "Loading...";
                const base64Data = dataUrl.split(',')[1];
                const arrayBuffer = base64ToArrayBuffer(base64Data);
                currentBuffer = await audioContext.decodeAudioData(arrayBuffer);
                startPlayback(offset);
                document.getElementById('player-song-title').textContent = fileName.replace('.mp3', '');
                updateMediaSession();
            } catch (e) {
                document.getElementById('player-song-title').textContent = `Error: ${e.message}`;
            }
        }

        function startPlayback(offset) {
            if (!currentBuffer) return;
            sourceNode = audioContext.createBufferSource();
            sourceNode.buffer = currentBuffer;
            sourceNode.playbackRate.value = document.getElementById('speed-slider').value;
            sourceNode.connect(gainNode);

            sourceNode.onended = () => {
                // Check if the song ended naturally (not stopped by the user)
                if (isPlaying && (audioContext.currentTime - startTime) >= currentBuffer.duration / sourceNode.playbackRate.value - 0.1) {
                    if (isAutoplayOn) playNext(); else stopSong(true);
                }
            };

            sourceNode.start(0, offset);
            startTime = audioContext.currentTime - offset;
            pauseOffset = 0;
            isPlaying = true;
            document.getElementById('play-pause-icon').innerHTML = PAUSE_ICON_PATH;
            updateVisuals();
        }

        function stopSong(isEndOfTrack = false) {
            if (sourceNode) {
                sourceNode.onended = null; // Prevent onended from firing on manual stop
                try { sourceNode.stop(); } catch(e) {}
                sourceNode.disconnect();
                sourceNode = null;
            }
            if (isPlaying) {
                pauseOffset = audioContext.currentTime - startTime;
            }
            isPlaying = false;
            if (isEndOfTrack) {
                pauseOffset = 0;
                document.getElementById('progress-bar-fill').style.width = '0%';
            }
            document.getElementById('play-pause-icon').innerHTML = PLAY_ICON_PATH;
            if (animationFrameId) cancelAnimationFrame(animationFrameId);
        }
        
        async function updatePlaylist() {
            try {
                const response = await fetch('/api/get-audio-files');
                const data = await response.json();
                const oldTrackName = currentTrackIndex > -1 ? audioFileNames[currentTrackIndex] : null;
                
                audioFileNames = data.files;
                audioData = data.data;

                if (oldTrackName && !audioFileNames.includes(oldTrackName)) {
                    // The currently playing song was deleted, so stop everything.
                    stopSong(true);
                    currentBuffer = null;
                    currentTrackIndex = -1;
                    document.getElementById('player-song-title').textContent = 'No Song Playing';
                } else if (oldTrackName) {
                    // Re-sync the index in case the list order changed
                    currentTrackIndex = audioFileNames.indexOf(oldTrackName);
                }
                renderSongList();
            } catch (error) {
                console.error("Failed to update playlist:", error);
            }
        }

        // --- EVENT LISTENERS ---
        function setupEventListeners() {
            document.querySelectorAll('.nav-item').forEach(item => item.addEventListener('click', e => {
                document.querySelector('.nav-item.active').classList.remove('active');
                e.currentTarget.classList.add('active');
                document.querySelector('.page.active').classList.remove('active');
                document.getElementById(e.currentTarget.dataset.page).classList.add('active');
            }));

            document.getElementById('song-list').addEventListener('click', async e => {
                const playButton = e.target.closest('.play-btn');
                if (playButton) {
                    playSong(parseInt(playButton.dataset.index));
                }
            });

            document.getElementById('play-pause-btn').addEventListener('click', togglePlayPause);
            document.getElementById('next-btn').addEventListener('click', playNext);
            document.getElementById('prev-btn').addEventListener('click', playPrev);
            document.getElementById('volume-slider').addEventListener('input', e => {
                if(gainNode) gainNode.gain.value = e.target.value;
            });

            document.getElementById('progress-bar-wrapper').addEventListener('click', e => {
                if (!currentBuffer || !isPlaying) return;
                const rect = e.currentTarget.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const width = rect.width;
                const progress = Math.max(0, Math.min(1, x / width));
                const seekTime = currentBuffer.duration * progress;
                // Restart the song from the new position
                playSong(currentTrackIndex, seekTime);
            });

            // Effects
            document.getElementById('speed-slider').addEventListener('input', e => updateSpeed(e.target.value));
            document.getElementById('reverb-slider').addEventListener('input', e => updateReverb(e.target.value));
            document.getElementById('distortion-slider').addEventListener('input', e => updateDistortion(e.target.value));
            document.querySelectorAll('.eq-slider').forEach(slider => {
                slider.addEventListener('input', e => {
                    if (eqBands) eqBands[e.target.dataset.index].gain.value = e.target.value;
                });
            });
            document.getElementById('comp-thresh-slider').addEventListener('input', e => updateCompressor('threshold', e.target.value, v => `${v} dB`, '#comp-thresh-val'));
            document.getElementById('comp-knee-slider').addEventListener('input', e => updateCompressor('knee', e.target.value, v => v, '#comp-knee-val'));
            document.getElementById('comp-ratio-slider').addEventListener('input', e => updateCompressor('ratio', e.target.value, v => v, '#comp-ratio-val'));
            document.getElementById('comp-attack-slider').addEventListener('input', e => updateCompressor('attack', e.target.value, v => `${v} s`, '#comp-attack-val'));
            document.getElementById('comp-release-slider').addEventListener('input', e => updateCompressor('release', e.target.value, v => `${v} s`, '#comp-release-val'));
            document.getElementById('pan-slider').addEventListener('input', e => updatePanner(e.target.value));

            // Downloader
            document.getElementById('search-library').addEventListener('keypress', e => {
                if (e.key === 'Enter') {
                    const query = e.target.value.trim();
                    if (query) {
                        socketio.emit('download_song', { query: query });
                        e.target.value = '';
                    }
                }
            });
        }
        
        // --- UI & VISUALS ---
        function updateVisuals() {
            const bufferLength = analyser.frequencyBinCount;
            const dataArray = new Uint8Array(bufferLength);

            const draw = () => {
                if (!isPlaying) return;
                animationFrameId = requestAnimationFrame(draw);

                if (currentBuffer && sourceNode) {
                    const playbackRate = sourceNode.playbackRate.value;
                    const elapsedTime = (audioContext.currentTime - startTime) * playbackRate;
                    const duration = currentBuffer.duration;
                    const progress = elapsedTime / duration;
                    document.getElementById('progress-bar-fill').style.width = `${Math.min(progress * 100, 100)}%`;
                }

                analyser.getByteFrequencyData(dataArray);
                canvasCtx.fillStyle = 'var(--bg-main)';
                canvasCtx.fillRect(0, 0, canvas.width, canvas.height);
                const barWidth = (canvas.width / bufferLength) * 2.5;
                let x = 0;
                for (let i = 0; i < bufferLength; i++) {
                    const barHeight = dataArray[i];
                    const green = barHeight + 50 * (i/bufferLength);
                    const blue = barHeight / 2;
                    canvasCtx.fillStyle = `rgb(50, ${green}, ${blue})`;
                    canvasCtx.fillRect(x, canvas.height - barHeight / 2, barWidth, barHeight / 2);
                    x += barWidth + 1;
                }
            };
            draw();
        }

        function renderSongList() {
            const listEl = document.getElementById('song-list');
            listEl.innerHTML = '';
            if (audioFileNames.length === 0) {
                listEl.innerHTML = '<p style="color: var(--text-secondary); padding: 20px;">No music found. Paste a URL above to download.</p>';
                return;
            }

            audioFileNames.forEach((name, index) => {
                const item = document.createElement('div');
                item.className = 'song-list-item';
                item.innerHTML = `
                    <button class="play-btn" data-index="${index}"><svg fill="currentColor" viewBox="0 0 20 20"><path d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8.13v3.74a1 1 0 001.555.832l3.197-1.87a1 1 0 000-1.664l-3.197-1.87z" clip-rule="evenodd"></path></svg></button>
                    <div class="song-details"><div class="title">${name.replace('.mp3','')}</div></div>`;
                listEl.appendChild(item);
            });
        }

        // --- PLAYER CONTROLS ---
        function togglePlayPause() {
            if (currentTrackIndex === -1 && audioFileNames.length > 0) {
                playSong(0);
            } else if (isPlaying) {
                stopSong();
            } else if (currentBuffer) {
                startPlayback(pauseOffset);
            }
        }

        function playNext() {
            if (audioFileNames.length === 0) return;
            let nextIndex = (currentTrackIndex + 1) % audioFileNames.length;
            playSong(nextIndex);
        }

        function playPrev() {
            if (audioFileNames.length === 0) return;
            const prevIndex = (currentTrackIndex - 1 + audioFileNames.length) % audioFileNames.length;
            playSong(prevIndex);
        }

        // --- MEDIA SESSION & EFFECTS ---
        function setupMediaSession() {
            if ('mediaSession' in navigator) {
                navigator.mediaSession.setActionHandler('play', () => { togglePlayPause(); });
                navigator.mediaSession.setActionHandler('pause', () => { togglePlayPause(); });
                navigator.mediaSession.setActionHandler('previoustrack', () => { playPrev(); });
                navigator.mediaSession.setActionHandler('nexttrack', () => { playNext(); });
            }
        }

        function updateMediaSession() {
            if ('mediaSession' in navigator && currentTrackIndex > -1) {
                const track = audioFileNames[currentTrackIndex];
                navigator.mediaSession.metadata = new MediaMetadata({
                    title: track.replace('.mp3', ''),
                    artist: 'Studio AURA',
                    album: 'Library'
                });
            }
        }

        function resetEffects() {
            document.querySelectorAll('.eq-slider').forEach(slider => slider.value = 0);
            if (eqBands) eqBands.forEach(filter => filter.gain.value = 0);
            document.getElementById('speed-slider').value = 1; updateSpeed(1);
            document.getElementById('reverb-slider').value = 0; updateReverb(0);
            document.getElementById('distortion-slider').value = 0; updateDistortion(0);
            document.getElementById('comp-thresh-slider').value = -24; updateCompressor('threshold', -24, v => `${v} dB`, '#comp-thresh-val');
            document.getElementById('comp-knee-slider').value = 30; updateCompressor('knee', 30, v => v, '#comp-knee-val');
            document.getElementById('comp-ratio-slider').value = 12; updateCompressor('ratio', 12, v => v, '#comp-ratio-val');
            document.getElementById('comp-attack-slider').value = 0.003; updateCompressor('attack', 0.003, v => `${v} s`, '#comp-attack-val');
            document.getElementById('comp-release-slider').value = 0.25; updateCompressor('release', 0.25, v => `${v} s`, '#comp-release-val');
            document.getElementById('pan-slider').value = 0; updatePanner(0);
        }

        function updateEffect(audioParam, value, formatFn, valId) {
            if (audioParam) audioParam.value = value;
            if(formatFn && valId) document.querySelector(valId).textContent = formatFn(value);
        }

        function updateSpeed(rate) {
            if (sourceNode) sourceNode.playbackRate.value = rate;
            updateEffect(null, rate, v => `${parseFloat(v).toFixed(1)}x`, '#speed-val');
        }

        function updateDistortion(amount) {
            const k = Number(amount) * 100;
            const n_samples = 44100;
            const curve = new Float32Array(n_samples);
            const deg = Math.PI / 180;
            for (let i = 0; i < n_samples; ++i) {
                const x = i * 2 / n_samples - 1;
                curve[i] = (3 + k) * x * 20 * deg / (Math.PI + k * Math.abs(x));
            }
            if (distortion) distortion.curve = curve;
            updateEffect(null, amount, v => `${Math.round(v*100)}%`, '#distortion-val');
        }

        function updateReverb(amount) {
            if (dryGain && wetGain) {
                dryGain.gain.value = 1 - Math.pow(amount, 2);
                wetGain.gain.value = amount;
            }
            updateEffect(null, amount, v => `${Math.round(v*100)}%`, '#reverb-val');
        }

        function updateCompressor(param, value, formatFn, valId) {
            if (compressor && compressor[param]) compressor[param].value = value;
            updateEffect(null, value, formatFn, valId);
        }

        function updatePanner(value) {
            if (panner) panner.pan.value = value;
            updateEffect(null, value, v => parseFloat(v).toFixed(2), '#pan-val');
        }
        
        // --- HELPERS ---
        async function createReverbImpulse() {
            const sampleRate = audioContext.sampleRate;
            const duration = 2;
            const decay = 2;
            const impulse = audioContext.createBuffer(2, duration * sampleRate, sampleRate);
            for (let i = 0; i < 2; i++) {
                const channel = impulse.getChannelData(i);
                for (let j = 0; j < impulse.length; j++) {
                    channel[j] = (Math.random() * 2 - 1) * Math.pow(1 - j / impulse.length, decay);
                }
            }
            return impulse;
        }

        function base64ToArrayBuffer(base64) {
            const binaryString = window.atob(base64);
            const len = binaryString.length;
            const bytes = new Uint8Array(len);
            for (let i = 0; i < len; i++) { bytes[i] = binaryString.charCodeAt(i); }
            return bytes.buffer;
        }
        
        // --- STARTUP ---
        document.addEventListener('DOMContentLoaded', initialize);
    </script>
</body>
</html>
"""

def open_browser():
      webbrowser.open_new("http://127.0.0.1:8080")

if __name__ == '__main__':
    print("✅ Studio AURA is launching...")
    print("Open your web browser and go to http://127.0.0.1:8080")
    # Uncomment the line below to automatically open a browser tab.
    # threading.Timer(1, open_browser).start()
    socketio.run(app, host='0.0.0.0', port=8080)
