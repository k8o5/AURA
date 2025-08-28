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
def get_library_data():
    """Scans for .mp3 files, looks for associated .json metadata, and returns a structured list."""
    tracks = []
    audio_files = sorted([f for f in os.listdir('.') if f.endswith('.mp3')])
    
    for filename in audio_files:
        track_data = {"filename": filename, "thumbnail": None, "data": None}
        
        # Look for a metadata file
        meta_filename = filename.rsplit('.', 1)[0] + '.json'
        if os.path.exists(meta_filename):
            try:
                with open(meta_filename, 'r') as f:
                    meta = json.load(f)
                    track_data['thumbnail'] = meta.get('thumbnail')
            except (IOError, json.JSONDecodeError):
                pass # Ignore if metadata is unreadable

        # Encode the audio data
        try:
            with open(filename, "rb") as f:
                encoded_data = base64.b64encode(f.read()).decode('utf-8')
                track_data['data'] = f"data:audio/mpeg;base64,{encoded_data}"
        except FileNotFoundError:
            continue # Skip if file disappears during scan

        tracks.append(track_data)
        
    return tracks

# --- Backend Logic ---
def check_ffmpeg():
    try:
        subprocess.run(['ffmpeg', '-version'], check=True, capture_output=True, text=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def install_ffmpeg():
    try:
        print("ffmpeg not found. Attempting to install...")
        subprocess.check_call(["pkg", "install", "ffmpeg", "-y"])
        print("ffmpeg installed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to install ffmpeg: {e}")
        sys.exit(1)

# --- Flask Routes ---
@app.route('/')
def index():
    initial_tracks = get_library_data()
    return render_template_string(html_template, initial_tracks=json.dumps(initial_tracks))

@app.route('/api/get-library-data', methods=['GET'])
def get_library_data_api():
    return jsonify({"tracks": get_library_data()})

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

def download_audio_backend(query, source, socketio):
    """Downloads audio using yt-dlp, extracts thumbnail, and saves metadata."""
    if not check_ffmpeg():
        install_ffmpeg()
    
    download_id = query # Use the initial query as a temporary ID for the frontend

    def progress_hook(d):
        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
            if total_bytes:
                percentage = d['downloaded_bytes'] / total_bytes * 100
                speed = d.get('speed', 0)
                socketio.emit('download_progress', {
                    'filename': download_id,
                    'percentage': percentage,
                    'status': 'Downloading'
                })
        elif d['status'] == 'finished' and d['postprocessor'] == 'FFmpegExtractAudio':
             # This hook signals that the MP3 conversion is done.
             socketio.emit('download_progress', {
                    'filename': download_id,
                    'percentage': 100,
                    'status': 'Finalizing...'
                })


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
        'noplaylist': False,
        'ignoreerrors': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            entries = info.get('entries', [info])
            
            for entry in entries:
                if not entry: continue
                
                title = entry.get('title', 'Unknown Title')
                thumbnail_url = None
                if entry.get('thumbnails'):
                    thumbnail_url = entry['thumbnails'][-1]['url'] # Get highest quality

                socketio.emit('download_start', {'temp_id': query, 'title': title, 'thumbnail': thumbnail_url})
                download_id = title # Switch to using the real title as the ID

                # Perform the download
                ydl.download([entry['webpage_url']])
                
                # After download, save metadata
                base_filename = ydl.prepare_filename(entry).rsplit('.', 1)[0]
                meta_filename = base_filename + '.json'
                with open(meta_filename, 'w') as f:
                    json.dump({'thumbnail': thumbnail_url}, f)

                socketio.emit('download_finished', {'filename': title})

    except Exception as e:
        socketio.emit('download_error', {'message': str(e), 'filename': download_id})

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
        /* General Styles & Variables */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&display=swap');
        :root {
            --bg-base: #000000; --bg-main: #121212; --bg-secondary: #181818; --bg-tertiary: #282828;
            --bg-player: #181818; --border-color: #2A2A2A; --accent-primary: #1DB954;
            --text-primary: #FFFFFF; --text-secondary: #b3b3b3;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body, html {
            background-color: var(--bg-base); font-family: 'Inter', sans-serif;
            overflow: hidden; color: var(--text-primary);
        }
        .workstation-container {
            width: 100%; height: 100vh; display: grid; grid-template-columns: 80px 1fr 300px;
            grid-template-rows: 1fr; grid-template-areas: "sidebar main player";
            transition: grid-template-columns 0.3s ease;
        }
        @media (min-width: 1024px) {
            .workstation-container { grid-template-columns: 240px 1fr 300px; }
            .sidebar-header .full-text { display: block; }
            .nav-item-text { opacity: 1; }
        }
        
        /* Sidebar */
        .sidebar { grid-area: sidebar; background: var(--bg-base); padding: 24px 8px; display: flex; flex-direction: column; }
        .sidebar-header { padding: 0 16px 16px; font-size: 1.5rem; font-weight: 700; white-space: nowrap; overflow: hidden; }
        .sidebar-header .full-text { display: none; }
        .nav-item {
            padding: 12px 16px; border-radius: 6px; cursor: pointer; font-weight: 500;
            transition: background 0.2s ease, color 0.2s ease; display: flex; align-items: center;
            gap: 16px; color: var(--text-secondary);
        }
        .nav-item-text { white-space: nowrap; opacity: 0; transition: opacity 0.3s ease; }
        .nav-item:hover { background: var(--bg-tertiary); color: var(--text-primary); }
        .nav-item.active { background: var(--bg-tertiary); color: var(--accent-primary); }
        .nav-item.active svg { filter: drop-shadow(0 0 5px var(--accent-primary)); }
        .nav-item svg { width: 24px; height: 24px; transition: color 0.2s, filter 0.2s; flex-shrink: 0; }

        /* Main Content */
        .main-content { grid-area: main; background: var(--bg-main); overflow-y: auto; }
        .page { display: none; padding: 24px 32px; }
        .page.active { display: block; }
        .page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
        .page h1 { font-size: 2.5rem; font-weight: 700; }

        /* Library Page */
        #search-library {
            width: 100%; max-width: 400px; background: var(--bg-tertiary); border: none;
            color: var(--text-primary); padding: 12px 16px; border-radius: 6px;
            margin-bottom: 24px; font-size: 0.9rem;
        }
        .song-list-item {
            display: grid; grid-template-columns: 40px 50px 1fr auto; align-items: center;
            gap: 16px; padding: 8px; border-radius: 6px; transition: background 0.2s;
        }
        .song-list-item:hover { background: rgba(255,255,255,0.1); }
        .song-list-item.downloading { opacity: 0.6; pointer-events: none; }
        .song-album-art { width: 50px; height: 50px; border-radius: 4px; background-color: var(--bg-tertiary); object-fit: cover; }
        .song-details .title { font-weight: 500; }
        .song-details .status { font-size: 0.8rem; color: var(--text-secondary); margin-top: 4px; }
        .play-btn { background: none; border: none; color: var(--text-secondary); cursor: pointer; display: flex; align-items: center; justify-content: center; }
        .play-btn svg { width: 20px; height: 20px; }
        .song-list-item:hover .play-btn { color: var(--text-primary); }
        .download-progress-bar { grid-column: 2 / -1; height: 2px; background: var(--accent-primary); width: 0%; transition: width 0.2s ease; margin-top: 4px; border-radius: 1px;}

        /* Effects Page */
        #effects-container { display: flex; flex-direction: column; gap: 24px; max-width: 600px; }
        .effect-module { background: var(--bg-secondary); border-radius: 12px; padding: 20px; }
        .effect-module h3 { font-weight: 700; border-bottom: 1px solid var(--border-color); padding-bottom: 12px; margin-bottom: 16px; }
        .slider-group { display: flex; flex-direction: column; gap: 10px; width:100%; }
        .slider-label-group { display: flex; justify-content: space-between; font-weight: 500; font-size: 1rem; }
        .custom-slider { -webkit-appearance: none; width: 100%; height: 4px; background: var(--bg-tertiary); border-radius: 2px; outline: none; }
        .custom-slider::-webkit-slider-thumb { -webkit-appearance: none; appearance: none; width: 20px; height: 20px; background: var(--text-primary); border-radius: 50%; cursor: pointer; }
        #reset-effects-btn {
            background: var(--bg-tertiary); color: var(--text-primary); border: none; padding: 10px 20px;
            border-radius: 6px; cursor: pointer; font-weight: 500; transition: background 0.2s;
        }
        #reset-effects-btn:hover { background: var(--border-color); }
        
        /* Player Bar */
        .player-bar {
            grid-area: player; background: var(--bg-player); padding: 24px; display: flex;
            flex-direction: column; align-items: center; justify-content: space-between; gap: 20px;
        }
        #player-album-art {
            width: 100%; max-width: 250px; aspect-ratio: 1 / 1; border-radius: 12px;
            background-color: var(--bg-secondary); object-fit: cover;
        }
        #progress-bar-wrapper { width: 100%; height: 3px; background-color: var(--bg-tertiary); cursor: pointer; }
        #progress-bar-fill { width: 0%; height: 100%; background-color: var(--accent-primary); border-radius: 0 3px 3px 0; }
        .current-track-info { font-weight: 500; text-align: center; }
        .player-controls { display: flex; justify-content: center; align-items: center; gap: 20px; }
        .control-btn { background: none; border: none; color: var(--text-secondary); cursor: pointer; transition: color 0.2s; }
        .control-btn:hover { color: var(--text-primary); }
        .control-btn.play-pause-btn {
            background-color: var(--text-primary); color: #000; width: 48px; height: 48px; border-radius: 50%;
            display: flex; align-items: center; justify-content: center; transition: all 0.2s;
        }
        .control-btn.play-pause-btn:hover { transform: scale(1.05); }
        .control-btn svg { width: 24px; height: 24px; }
        .secondary-controls { display: flex; align-items: center; gap: 20px; justify-content: center; width: 100%; }
        #volume-slider { width: 100%; }
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
                <div class="page-header"><h1>Music Library</h1></div>
                <input type="text" id="search-library" placeholder="Paste a YouTube or SoundCloud URL to download...">
                <div id="song-list"></div>
            </section>
            <section id="effects-page" class="page">
                <div class="page-header">
                    <h1>Effects Suite</h1>
                    <button id="reset-effects-btn">Reset</button>
                </div>
                <div id="effects-container"></div>
            </section>
        </main>
        <div class="player-bar">
            <img id="player-album-art" src="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgdmlld0JveD0iMCAwIDIwMCAyMDAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzE4MTgxOCIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iSW50ZXIsIHNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iMjBweCIgZmlsbD0iIzI4MjgyOCIgZm9udC1dZWlnaHQ9IjcwMCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9Ii4zZW0iPkFVUkE8L3RleHQ+PC9zdmc+">
            <div class="current-track-info"><div id="player-song-title">No Song Playing</div></div>
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
        // --- GLOBAL STATE ---
        let tracks = {{ initial_tracks|safe }};
        let currentTrackIndex = -1;
        
        // --- CONSTANTS & DOM ELEMENTS ---
        const PLAY_ICON_PATH = `<path d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8.13v3.74a1 1 0 001.555.832l3.197-1.87a1 1 0 000-1.664l-3.197-1.87z" clip-rule="evenodd"></path>`;
        const PAUSE_ICON_PATH = `<path d="M10 18a8 8 0 100-16 8 8 0 000 16zM7 9a1 1 0 00-1 1v4a1 1 0 102 0v-4a1 1 0 00-1-1zm5 0a1 1 0 00-1 1v4a1 1 0 102 0v-4a1 1 0 00-1-1z" clip-rule="evenodd"></path>`;
        const DEFAULT_ALBUM_ART = "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgdmlld0JveD0iMCAwIDIwMCAyMDAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzE4MTgxOCIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iSW50ZXIsIHNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iMjBweCIgZmlsbD0iIzI4MjgyOCIgZm9udC1dZWlnaHQ9IjcwMCIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9Ii4zZW0iPkFVUkE8L3RleHQ+PC9zdmc+";

        // --- WEB AUDIO API STATE ---
        let audioContext, sourceNode, gainNode, analyser, distortion, reverb, wetGain, dryGain, compressor, panner, eqBands;
        let isPlaying = false, currentBuffer = null, startTime = 0, pauseOffset = 0, animationFrameId;

        // --- SOCKET.IO ---
        const socketio = io();

        socketio.on('download_start', (data) => {
            const item = document.getElementById(data.temp_id);
            if (item) {
                item.id = data.title; // Update ID to the real title
                item.querySelector('.title').textContent = data.title;
                if (data.thumbnail) {
                    item.querySelector('.song-album-art').src = data.thumbnail;
                }
            }
        });
        
        socketio.on('download_progress', (data) => {
            const item = document.getElementById(data.filename);
            if (item) {
                const statusBar = item.querySelector('.status');
                const progressBar = item.querySelector('.download-progress-bar');
                if (statusBar) statusBar.textContent = `${data.status}... ${data.percentage.toFixed(0)}%`;
                if (progressBar) progressBar.style.width = `${data.percentage}%`;
            }
        });

        socketio.on('download_finished', (data) => {
            updateLibrary();
        });

        socketio.on('download_error', (data) => {
            alert(`Download failed for "${data.filename}": ${data.message}`);
            const item = document.getElementById(data.filename);
            if (item) item.remove();
        });
        
        // --- INITIALIZATION ---
        function initialize() {
            createEffectsUI();
            setupEventListeners();
            renderSongList();
            setupMediaSession();
        }

        function createEffectsUI(){
            const effectsContainer = document.getElementById('effects-container');
            effectsContainer.innerHTML = `
                <div class="effect-module"><h3>Playback</h3><div class="slider-group"><div class="slider-label-group"><span>Speed</span><span id="speed-val">1.0x</span></div><input type="range" id="speed-slider" class="custom-slider" min="0.5" max="2" step="0.01" value="1"></div></div>
                <div class="effect-module"><h3>Ambiance & Tone</h3><div class="slider-group" style="gap: 16px;"><div class="slider-label-group"><span>Reverb</span><span id="reverb-val">0%</span></div><input type="range" id="reverb-slider" class="custom-slider" min="0" max="1" step="0.01" value="0"><div class="slider-label-group"><span>Distortion</span><span id="distortion-val">0%</span></div><input type="range" id="distortion-slider" class="custom-slider" min="0" max="1" step="0.01" value="0"></div></div>
                <div class="effect-module"><h3>10-Band Equalizer</h3><div id="eq-container"></div></div>`;
            
            const eqContainer = document.getElementById('eq-container');
            const frequencies = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
            frequencies.forEach((freq, i) => {
                eqContainer.innerHTML += `<div class="eq-band"><label>${freq < 1000 ? freq : (freq / 1000) + 'k'}Hz</label><input type="range" class="eq-slider" min="-20" max="20" step="0.5" value="0" data-index="${i}"></div>`;
            });
        }

        function initAudio() {
            if (audioContext) return;
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            gainNode = audioContext.createGain();
            analyser = audioContext.createAnalyser();
            analyser.fftSize = 256;
            
            // Create effects chain
            const frequencies = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
            eqBands = frequencies.map(freq => {
                const filter = audioContext.createBiquadFilter();
                filter.type = 'peaking';
                filter.frequency.value = freq;
                filter.Q.value = 1.41;
                filter.gain.value = 0;
                return filter;
            });

            // Connect nodes
            let lastNode = gainNode;
            eqBands.forEach(filter => {
                lastNode.connect(filter);
                lastNode = filter;
            });
            lastNode.connect(analyser).connect(audioContext.destination);

            resetEffects();
        }
        
        // --- AUDIO PLAYBACK ---
        async function playSong(index, offset = 0) {
            if (index < 0 || index >= tracks.length) return;
            if (!audioContext) initAudio();
            if (isPlaying) stopSong();

            currentTrackIndex = index;
            const track = tracks[index];

            if (!track.data) {
                document.getElementById('player-song-title').textContent = "Error: File data missing";
                return;
            }

            try {
                document.getElementById('player-song-title').textContent = "Loading...";
                const arrayBuffer = base64ToArrayBuffer(track.data.split(',')[1]);
                currentBuffer = await audioContext.decodeAudioData(arrayBuffer);
                startPlayback(offset);

                document.getElementById('player-song-title').textContent = track.filename.replace('.mp3', '');
                document.getElementById('player-album-art').src = track.thumbnail || DEFAULT_ALBUM_ART;
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
                if (isPlaying) playNext(); else stopSong(true);
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
                sourceNode.onended = null;
                try { sourceNode.stop(); } catch(e) {}
                sourceNode.disconnect();
                sourceNode = null;
            }
            if (isPlaying) pauseOffset = audioContext.currentTime - startTime;
            isPlaying = false;
            if (isEndOfTrack) {
                pauseOffset = 0;
                document.getElementById('progress-bar-fill').style.width = '0%';
            }
            document.getElementById('play-pause-icon').innerHTML = PLAY_ICON_PATH;
            if (animationFrameId) cancelAnimationFrame(animationFrameId);
        }
        
        async function updateLibrary() {
            try {
                const response = await fetch('/api/get-library-data');
                const data = await response.json();
                const oldTrackName = currentTrackIndex > -1 ? tracks[currentTrackIndex].filename : null;
                
                tracks = data.tracks;

                if (oldTrackName) {
                    currentTrackIndex = tracks.findIndex(t => t.filename === oldTrackName);
                    if (currentTrackIndex === -1) { // Song was deleted
                         stopSong(true);
                         currentBuffer = null;
                         document.getElementById('player-song-title').textContent = 'No Song Playing';
                         document.getElementById('player-album-art').src = DEFAULT_ALBUM_ART;
                    }
                }
                renderSongList();
            } catch (error) {
                console.error("Failed to update library:", error);
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

            document.getElementById('song-list').addEventListener('click', e => {
                const playButton = e.target.closest('.play-btn');
                if (playButton) playSong(parseInt(playButton.dataset.index));
            });
            
            document.getElementById('reset-effects-btn').addEventListener('click', resetEffects);
            document.getElementById('play-pause-btn').addEventListener('click', togglePlayPause);
            document.getElementById('next-btn').addEventListener('click', playNext);
            document.getElementById('prev-btn').addEventListener('click', playPrev);
            document.getElementById('volume-slider').addEventListener('input', e => { if(gainNode) gainNode.gain.value = e.target.value; });
            document.getElementById('progress-bar-wrapper').addEventListener('click', e => {
                if (!currentBuffer || !isPlaying) return;
                const rect = e.currentTarget.getBoundingClientRect();
                const seekTime = (e.clientX - rect.left) / rect.width * currentBuffer.duration;
                playSong(currentTrackIndex, seekTime);
            });

            // Effects
            document.getElementById('speed-slider').addEventListener('input', e => { if (sourceNode) sourceNode.playbackRate.value = e.target.value; document.getElementById('speed-val').textContent = `${parseFloat(e.target.value).toFixed(1)}x`; });
            document.querySelectorAll('.eq-slider').forEach(slider => slider.addEventListener('input', e => { if (eqBands) eqBands[e.target.dataset.index].gain.value = e.target.value; }));

            // Downloader
            document.getElementById('search-library').addEventListener('keypress', e => {
                if (e.key === 'Enter') {
                    const query = e.target.value.trim();
                    if (query) {
                        addDownloadingItemToList(query);
                        socketio.emit('download_song', { query: query });
                        e.target.value = '';
                    }
                }
            });
        }
        
        // --- UI & VISUALS ---
        function addDownloadingItemToList(query) {
            const listEl = document.getElementById('song-list');
            const existing = document.getElementById(query);
            if (existing) return; // Don't add duplicates

            const item = document.createElement('div');
            item.className = 'song-list-item downloading';
            item.id = query;
            item.innerHTML = `
                <div class="play-btn" style="align-self: flex-start;"><svg fill="currentColor" viewBox="0 0 20 20"><path d="M10 3a7 7 0 100 14 7 7 0 000-14zM8.707 13.293a1 1 0 001.414-1.414L9.414 11H13a1 1 0 100-2H9.414l.707-.707a1 1 0 00-1.414-1.414l-2 2a1 1 0 000 1.414l2 2z"></path></svg></div>
                <img class="song-album-art" src="${DEFAULT_ALBUM_ART}">
                <div class="song-details">
                    <div class="title">${query}</div>
                    <div class="status">Pending...</div>
                    <div class="download-progress-bar"></div>
                </div>
            `;
            listEl.prepend(item);
        }

        function updateVisuals() {
            const bufferLength = analyser.frequencyBinCount;
            const dataArray = new Uint8Array(bufferLength);
            const canvas = document.getElementById('visualizer-canvas');
            const canvasCtx = canvas.getContext('2d');

            const draw = () => {
                if (!isPlaying) return;
                animationFrameId = requestAnimationFrame(draw);
                if (currentBuffer && sourceNode) {
                    const progress = ((audioContext.currentTime - startTime) * sourceNode.playbackRate.value) / currentBuffer.duration;
                    document.getElementById('progress-bar-fill').style.width = `${Math.min(progress * 100, 100)}%`;
                }

                analyser.getByteFrequencyData(dataArray);
                canvasCtx.fillStyle = '#121212';
                canvasCtx.fillRect(0, 0, canvas.width, canvas.height);
                const barWidth = (canvas.width / bufferLength) * 2.5;
                for (let i = 0, x = 0; i < bufferLength; i++) {
                    const barHeight = dataArray[i] / 2;
                    canvasCtx.fillStyle = `rgba(30, 185, 84, ${barHeight/150})`;
                    canvasCtx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
                    x += barWidth + 1;
                }
            };
            draw();
        }

        function renderSongList() {
            const listEl = document.getElementById('song-list');
            listEl.innerHTML = '';
            if (tracks.length === 0) {
                listEl.innerHTML = '<p style="color: var(--text-secondary); padding: 20px;">Library is empty. Paste a URL to download music.</p>';
            }
            tracks.forEach((track, index) => {
                const item = document.createElement('div');
                item.className = 'song-list-item';
                item.innerHTML = `
                    <button class="play-btn" data-index="${index}"><svg fill="currentColor" viewBox="0 0 20 20"><path d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8.13v3.74a1 1 0 001.555.832l3.197-1.87a1 1 0 000-1.664l-3.197-1.87z"></path></svg></button>
                    <img class="song-album-art" src="${track.thumbnail || DEFAULT_ALBUM_ART}">
                    <div class="song-details"><div class="title">${track.filename.replace('.mp3','')}</div></div>`;
                listEl.appendChild(item);
            });
        }

        // --- PLAYER CONTROLS ---
        function togglePlayPause() {
            if (currentTrackIndex === -1 && tracks.length > 0) playSong(0);
            else if (isPlaying) stopSong();
            else if (currentBuffer) startPlayback(pauseOffset);
        }

        function playNext() {
            if (tracks.length === 0) return;
            let nextIndex = (currentTrackIndex + 1) % tracks.length;
            playSong(nextIndex);
        }

        function playPrev() {
            if (tracks.length === 0) return;
            const prevIndex = (currentTrackIndex - 1 + tracks.length) % tracks.length;
            playSong(prevIndex);
        }

        // --- MEDIA SESSION & EFFECTS ---
        function setupMediaSession() {
            if ('mediaSession' in navigator) {
                navigator.mediaSession.setActionHandler('play', togglePlayPause);
                navigator.mediaSession.setActionHandler('pause', togglePlayPause);
                navigator.mediaSession.setActionHandler('previoustrack', playPrev);
                navigator.mediaSession.setActionHandler('nexttrack', playNext);
            }
        }

        function updateMediaSession() {
            if ('mediaSession' in navigator && currentTrackIndex > -1) {
                const track = tracks[currentTrackIndex];
                navigator.mediaSession.metadata = new MediaMetadata({
                    title: track.filename.replace('.mp3', ''),
                    artist: 'Studio AURA',
                    artwork: [{ src: track.thumbnail || DEFAULT_ALBUM_ART, sizes: '512x512', type: 'image/jpeg' }]
                });
            }
        }

        function resetEffects() {
            document.querySelectorAll('.eq-slider').forEach(slider => slider.value = 0);
            if (eqBands) eqBands.forEach(filter => filter.gain.value = 0);
            document.getElementById('speed-slider').value = 1;
            if (sourceNode) sourceNode.playbackRate.value = 1;
            document.getElementById('speed-val').textContent = `1.0x`;
            // Add other effects resets here if they are re-enabled
        }
        
        // --- HELPERS ---
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
    # threading.Timer(1, open_browser).start()
    socketio.run(app, host='0.0.0.0', port=8080)
