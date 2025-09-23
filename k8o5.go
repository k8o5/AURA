package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
)

// SongData ist die Struktur für die an das Frontend gesendete JSON-Antwort.
type SongData struct {
	Files []string          `json:"files"`
	Data  map[string]string `json:"data"`
}

// DownloadRequest ist die Struktur zum Parsen von Download-Anfragen.
type DownloadRequest struct {
	Query  string `json:"query"`
	Source string `json:"source"`
}

// DeleteRequest ist die Struktur zum Parsen von Lösch-Anfragen.
type DeleteRequest struct {
	Filename string `json:"filename"`
}

// listSongsHandler scannt das aktuelle Verzeichnis nach .mp3-Dateien und gibt sie zurück.
func listSongsHandler(w http.ResponseWriter, r *http.Request) {
	files, err := filepath.Glob("*.mp3")
	if err != nil {
		http.Error(w, "Fehler beim Lesen der Dateien", http.StatusInternalServerError)
		log.Println("Fehler beim Suchen nach MP3-Dateien:", err)
		return
	}
	sort.Strings(files) // Sortiert die Dateien alphabetisch

	audioData := make(map[string]string)
	for _, file := range files {
		content, err := os.ReadFile(file)
		if err != nil {
			log.Printf("Konnte Datei %s nicht lesen: %v", file, err)
			continue
		}
		encoded := base64.StdEncoding.EncodeToString(content)
		audioData[file] = "data:audio/mpeg;base64," + encoded
	}

	response := SongData{
		Files: files,
		Data:  audioData,
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(response); err != nil {
		log.Println("Fehler beim Kodieren der JSON-Antwort:", err)
	}
}

	// downloadHandler führt yt-dlp aus, um Audio herunterzuladen.
func downloadHandler(w http.ResponseWriter, r *http.Request) {
	var req DownloadRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Ungültige Anfrage", http.StatusBadRequest)
		return
	}

	searchPrefix := "ytsearch"
	if req.Source == "soundcloud" {
		searchPrefix = "scsearch"
	}
	searchQuery := fmt.Sprintf("%s:%s", searchPrefix, req.Query)

	ytdlpPath, err := exec.LookPath("yt-dlp")
	if err != nil {
		log.Println("yt-dlp not found in PATH")
		http.Error(w, "yt-dlp not found in PATH", http.StatusInternalServerError)
		return
	}

	cmd := exec.Command(ytdlpPath,
		"--extract-audio",
		"--audio-format", "mp3",
		"--audio-quality", "192",
		"-o", "%(title)s.%(ext)s",
		searchQuery,
	)

	output, err := cmd.CombinedOutput()
	if err != nil {
		errMsg := fmt.Sprintf("Download fehlgeschlagen: %s\nOutput: %s", err, string(output))
		log.Println(errMsg)
		http.Error(w, errMsg, http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	fmt.Fprintf(w, `{"success": true, "message": "Download erfolgreich"}`)
}
// deleteHandler löscht eine angegebene .mp3-Datei.
func deleteHandler(w http.ResponseWriter, r *http.Request) {
	var req DeleteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Ungültige Anfrage", http.StatusBadRequest)
		return
	}

	// Sicherheitsprüfung: Verhindert Path Traversal und stellt sicher, dass es sich um eine MP3 handelt
	cleanFilename := filepath.Clean(filepath.Base(req.Filename))
	if strings.Contains(cleanFilename, "..") || !strings.HasSuffix(cleanFilename, ".mp3") {
		http.Error(w, "Ungültiger Dateiname", http.StatusBadRequest)
		return
	}

	if err := os.Remove(cleanFilename); err != nil {
		http.Error(w, "Löschen der Datei fehlgeschlagen", http.StatusInternalServerError)
		log.Printf("Fehler beim Löschen von %s: %v", cleanFilename, err)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	fmt.Fprintf(w, `{"success": true, "message": "Datei erfolgreich gelöscht"}`)
}

func main() {
	// Prüfen, ob yt-dlp und ffmpeg installiert sind
	if _, err := exec.LookPath("yt-dlp"); err != nil {
		log.Fatal("KRITISCH: yt-dlp wurde nicht im System-PATH gefunden. Bitte installieren Sie es.")
	}
	if _, err := exec.LookPath("ffmpeg"); err != nil {
		log.Fatal("KRITISCH: ffmpeg wurde nicht im System-PATH gefunden. Bitte installieren Sie es.")
	}

	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprint(w, htmlTemplate)
	})
	http.HandleFunc("/api/songs", listSongsHandler)
	http.HandleFunc("/api/download", downloadHandler)
	http.HandleFunc("/api/delete", deleteHandler)

	port := "8080"
	log.Printf("Studio k8o5 Server startet auf http://localhost:%s\n", port)
	log.Fatal(http.ListenAndServe(":"+port, nil))
}

// htmlTemplate enthält das gesamte Frontend-HTML, CSS und JavaScript.
// Es wurde angepasst, um mit dem Go-Backend über API-Aufrufe zu kommunizieren.
const htmlTemplate = `
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Studio k8o5</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&display=swap');
        :root {
            --bg-sidebar: #000000; --bg-main: #121212; --bg-secondary: #181818; --bg-tertiary: #282828;
            --bg-player: #181818; --border-color: #2A2A2A; --accent-primary: #1DB954;
            --text-primary: #FFFFFF; --text-secondary: #b3b3b3;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body, html { background-color: var(--bg-main); font-family: 'Inter', sans-serif; overflow: hidden; color: var(--text-primary); }
        .workstation-container { width: 100%; height: 100vh; display: grid; grid-template-rows: 1fr auto; grid-template-columns: 80px 1fr; grid-template-areas: "sidebar main" "player player"; transition: grid-template-columns 0.3s ease; }
        .sidebar { grid-area: sidebar; background: var(--bg-sidebar); padding: 24px 8px; display: flex; flex-direction: column; }
        .sidebar-header { padding: 0 16px 16px; font-size: 1.5rem; font-weight: 700; white-space: nowrap; overflow: hidden; }
        .sidebar-header .full-text { display: none; }
        .nav-item { padding: 12px 16px; border-radius: 6px; cursor: pointer; font-weight: 500; transition: background 0.2s ease, color 0.2s ease; display: flex; align-items: center; gap: 16px; color: var(--text-secondary); }
        .nav-item-text { white-space: nowrap; opacity: 0; transition: opacity 0.3s ease; }
        .nav-item:hover { background: var(--bg-tertiary); color: var(--text-primary);}
        .nav-item.active { background: var(--bg-tertiary); color: var(--accent-primary); }
        .nav-item.active svg { filter: drop-shadow(0 0 5px var(--accent-primary)); }
        .nav-item svg { width: 24px; height: 24px; transition: color 0.2s, filter 0.2s; flex-shrink: 0; }
        @media (min-width: 1024px) {
            .workstation-container { grid-template-columns: 240px 1fr; }
            .sidebar-header .full-text { display: block; }
            .nav-item-text { opacity: 1; }
        }
        .main-content { grid-area: main; background: var(--bg-main); overflow-y: auto; }
        .page { display: none; padding: 24px 32px; }
        .page.active { display: block; }
        .page h1 { font-size: 2.5rem; font-weight: 700; margin-bottom: 24px; }
        #search-library { width: 100%; max-width: 400px; background: var(--bg-tertiary); border: none; color: var(--text-primary); padding: 12px 16px; border-radius: 6px; margin-bottom: 24px; font-size: 0.9rem; }
        .song-list-item { display: grid; grid-template-columns: 40px 1fr 40px; align-items: center; padding: 12px 8px; border-radius: 6px; transition: background 0.2s; }
        .song-list-item:hover { background: rgba(255,255,255,0.1); }
        .play-btn, .delete-btn { background: none; border: none; color: var(--text-secondary); cursor: pointer; transition: color 0.2s; display: flex; align-items: center; justify-content: center; }
        .play-btn svg, .delete-btn svg { width: 20px; height: 20px; }
        .song-list-item:hover .play-btn, .song-list-item:hover .delete-btn { color: var(--text-primary); }
        .downloader-container { display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; height: 70vh; }
        .download-form { display: flex; width: 100%; max-width: 600px; }
        .downloader-input { flex-grow: 1; border: 1px solid var(--border-color); background: var(--bg-secondary); color: var(--text-primary); padding: 15px; font-size: 1rem; border-radius: 50px 0 0 50px; border-right: none; }
        .download-button { background: var(--accent-primary); color: white; border: none; padding: 15px 30px; border-radius: 0 50px 50px 0; font-weight: bold; font-size: 1rem; cursor: pointer; }
		.download-button:disabled { background: var(--bg-tertiary); cursor: not-allowed; }
        #effects-container { display: flex; flex-direction: column; gap: 24px; max-width: 600px; }
        .effect-module { background: var(--bg-secondary); border-radius: 12px; padding: 20px; }
        .effect-module h3 { font-weight: 700; margin-bottom: 8px; border-bottom: 1px solid var(--border-color); padding-bottom: 12px; margin-bottom: 16px; }
        .slider-group { display: flex; flex-direction: column; gap: 10px; width:100%; }
        .slider-label-group { display: flex; justify-content: space-between; font-weight: 500; font-size: 1rem; }
        .custom-slider { -webkit-appearance: none; width: 100%; height: 4px; background: var(--bg-tertiary); border-radius: 2px; outline: none; }
        .custom-slider::-webkit-slider-thumb { -webkit-appearance: none; appearance: none; width: 20px; height: 20px; background: var(--text-primary); border-radius: 50%; cursor: pointer; }
        .player-bar { grid-area: player; background: var(--bg-player); height: 100px; padding: 0 24px; display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; border-top: 1px solid var(--border-color); position: relative; }
        #progress-bar-wrapper { position: absolute; top: 0; left: 0; width: 100%; height: 3px; background-color: var(--bg-tertiary); cursor: pointer; }
        #progress-bar-fill { width: 0%; height: 100%; background-color: var(--accent-primary); border-radius: 0 3px 3px 0; }
        .current-track-info { font-weight: 500; }
        .player-controls { display: flex; justify-content: center; align-items: center; gap: 20px; }
        .control-btn { background: none; border: none; color: var(--text-secondary); cursor: pointer; transition: color 0.2s; }
        .control-btn:hover { color: var(--text-primary); }
        .control-btn.play-pause-btn { background-color: var(--text-primary); color: #000; width: 48px; height: 48px; border-radius: 50%; display: flex; align-items: center; justify-content: center; transition: all 0.2s; }
        .control-btn.play-pause-btn:hover { transform: scale(1.05); }
        .control-btn svg { width: 24px; height: 24px; }
        .secondary-controls { display: flex; align-items: center; gap: 20px; justify-content: flex-end; }
    </style>
</head>
<body>
    <div id="workstation-container" class="workstation-container">
        <div class="sidebar">
            <div class="sidebar-header"><span class="full-text">Studio k8o5</span></div>
            <div class="nav-item active" data-page="library-page"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path></svg><span class="nav-item-text">Library</span></div>
            <div class="nav-item" data-page="effects-page"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path></svg><span class="nav-item-text">Effects</span></div>
            <div class="nav-item" data-page="youtube-page"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg><span class="nav-item-text">YouTube</span></div>
            <div class="nav-item" data-page="soundcloud-page"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z"></path></svg><span class="nav-item-text">SoundCloud</span></div>
        </div>
        <main class="main-content">
            <section id="library-page" class="page active">
                <h1>Music Library</h1>
                <input type="text" id="search-library" placeholder="Filter songs...">
                <div id="song-list"></div>
            </section>
            <section id="effects-page" class="page">
                <h1>Effects Suite</h1>
                <canvas id="visualizer-canvas"></canvas>
                <div id="effects-container"></div>
            </section>
            <section id="youtube-page" class="page">
                <div class="downloader-container"></div>
            </section>
            <section id="soundcloud-page" class="page">
                <div class="downloader-container"></div>
            </section>
        </main>
        <div class="player-bar">
            <div id="progress-bar-wrapper"><div id="progress-bar-fill"></div></div>
            <div class="current-track-info"><div id="player-song-title">No Song Playing</div></div>
            <div class="player-controls">
                <button id="prev-btn" class="control-btn"><svg fill="currentColor" viewBox="0 0 20 20"><path d="M8.445 14.832A1 1 0 0010 14.033V5.967a1 1 0 00-1.555-.832L4 9.167V5a1 1 0 00-2 0v10a1 1 0 002 0v-4.167l4.445 4.032z"></path></svg></button>
                <button id="play-pause-btn" class="control-btn play-pause-btn"><svg id="play-pause-icon" fill="currentColor" viewBox="0 0 20 20"><path d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8.13v3.74a1 1 0 001.555.832l3.197-1.87a1 1 0 000-1.664l-3.197-1.87z" clip-rule="evenodd"></path></svg></button>
                <button id="next-btn" class="control-btn"><svg fill="currentColor" viewBox="0 0 20 20"><path d="M11.555 5.168A1 1 0 0010 5.967v8.066a1 1 0 001.555.832l4.445-4.033a1 1 0 000-1.664l-4.445-4.033zM4.445 14.832A1 1 0 006 14.033V5.967a1 1 0 00-1.555-.832L0 9.167V5a1 1 0 00-2 0v10a1 1 0 002 0v-4.167l4.445 4.032z"></path></svg></button>
            </div>
            <div class="secondary-controls">
                <button id="expand-btn" class="control-btn"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4h4m12 4V4h-4M4 16v4h4m12-4v4h-4"></path></svg></button>
            </div>
        </div>
    </div>
    <script>
        const PLAY_ICON_PATH = '<path d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8.13v3.74a1 1 0 001.555.832l3.197-1.87a1 1 0 000-1.664l-3.197-1.87z" clip-rule="evenodd"></path>';
        const PAUSE_ICON_PATH = '<path d="M10 18a8 8 0 100-16 8 8 0 000 16zM7 9a1 1 0 00-1 1v4a1 1 0 102 0v-4a1 1 0 00-1-1zm5 0a1 1 0 00-1 1v4a1 1 0 102 0v-4a1 1 0 00-1-1z" clip-rule="evenodd"></path>';

        function rehydrateContent() {
            document.getElementById('effects-container').innerHTML = ` + "`" + `
                <div class="effect-module"><h3>Playback</h3><div class="slider-group"><div class="slider-label-group"><span>Speed</span><span id="speed-val">1.0x</span></div><input type="range" id="speed-slider" class="custom-slider" min="0.5" max="2" step="0.01" value="1"></div></div>
                <div class="effect-module"><h3>Ambiance & Tone</h3><div class="slider-group" style="gap: 16px;"><div class="slider-label-group"><span>Reverb</span><span id="reverb-val">0%</span></div><input type="range" id="reverb-slider" class="custom-slider" min="0" max="1" step="0.01" value="0"><div class="slider-label-group"><span>Distortion</span><span id="distortion-val">0%</span></div><input type="range" id="distortion-slider" class="custom-slider" min="0" max="1" step="0.01" value="0"></div></div>
                <div class="effect-module"><h3>Tone Shaping</h3><div class="slider-group" style="gap: 16px;"><div class="slider-label-group"><span>Lows</span><span id="lows-val">0 dB</span></div><input type="range" id="lows-slider" class="custom-slider" min="-20" max="20" step="0.5" value="0"><div class="slider-label-group"><span>Highs</span><span id="highs-val">0 dB</span></div><input type="range" id="highs-slider" class="custom-slider" min="-20" max="20" step="0.5" value="0"></div></div>` + "`" + `;

            document.querySelector('#youtube-page .downloader-container').innerHTML = ` + "`" + `<h1>Download from YouTube</h1><p class="downloader-prompt">Paste a YouTube URL or song title to download it as an MP3.</p><div class="download-form"><input type="text" id="youtube-input" class="downloader-input" placeholder="Enter URL or title..."><button id="youtube-download-btn" class="download-button">Download</button></div>` + "`" + `;
            document.querySelector('#soundcloud-page .downloader-container').innerHTML = ` + "`" + `<h1>Download from SoundCloud</h1><p class="downloader-prompt">Paste a SoundCloud URL or track name to download it as an MP3.</p><div class="download-form"><input type="text" id="soundcloud-input" class="downloader-input" placeholder="Enter URL or track name..."><button id="soundcloud-download-btn" class="download-button">Download</button></div>` + "`" + `;
        }

        const canvas = document.getElementById('visualizer-canvas');
        const canvasCtx = canvas.getContext('2d');
        let audioFileNames = [];
        let audioData = {};
        let currentTrackIndex = -1, isShuffleOn = false, isAutoplayOn = true;
        let audioContext, sourceNode, gainNode, lowFilter, highFilter, analyser, distortion, reverb, wetGain, dryGain;
        let isPlaying = false, currentBuffer = null, startTime = 0, pauseOffset = 0, animationFrameId;

        async function fetchAndRenderPlaylist() {
            try {
                const response = await fetch('/api/songs');
                if (!response.ok) throw new Error('Failed to fetch songs from server.');
                const data = await response.json();
        
                const oldTrackName = currentTrackIndex > -1 ? audioFileNames[currentTrackIndex] : null;
                audioFileNames = data.files || [];
                audioData = data.data || {};
        
                if (oldTrackName) {
                    const newIndex = audioFileNames.indexOf(oldTrackName);
                    if (newIndex !== -1) {
                        currentTrackIndex = newIndex;
                    } else { 
                        stopSong(true);
                        currentBuffer = null;
                        currentTrackIndex = -1;
                        document.getElementById('player-song-title').textContent = 'No Song Playing';
                    }
                }
                renderSongList();
            } catch (error) {
                console.error('Error updating playlist:', error);
                alert('Could not refresh the song list.');
            }
        }

        function initialize() {
            rehydrateContent();
            setupEventListeners();
            fetchAndRenderPlaylist();
            setupMediaSession();
        }

        function setupMediaSession() {
            if ('mediaSession' in navigator) {
                navigator.mediaSession.setActionHandler('play', () => {
                    if (currentTrackIndex === -1 && audioFileNames.length > 0) {
                        playSong(0);
                    } else {
                        togglePlayPause();
                    }
                });
                navigator.mediaSession.setActionHandler('pause', () => togglePlayPause());
                navigator.mediaSession.setActionHandler('previoustrack', () => playPrev());
                navigator.mediaSession.setActionHandler('nexttrack', () => playNext());
            }
        }

        function initAudio() {
            if (audioContext) return;
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
            gainNode = audioContext.createGain();
            analyser = audioContext.createAnalyser();
            lowFilter = audioContext.createBiquadFilter();
            highFilter = audioContext.createBiquadFilter();
            distortion = audioContext.createWaveShaper();
            reverb = audioContext.createConvolver();
            wetGain = audioContext.createGain();
            dryGain = audioContext.createGain();
            analyser.fftSize = 256;
            lowFilter.type = "lowshelf"; lowFilter.frequency.value = 320;
            highFilter.type = "highshelf"; highFilter.frequency.value = 3200;
            createReverbImpulse().then(buffer => { reverb.buffer = buffer; });
            // This connection chain will be re-established when a song plays
            resetEffects();
        }

        function connectAudioNodes() {
            if (!sourceNode || !gainNode) return;
            sourceNode.connect(gainNode)
                .connect(distortion)
                .connect(lowFilter)
                .connect(highFilter)
                .connect(analyser);

            analyser.connect(dryGain).connect(audioContext.destination);
            analyser.connect(wetGain).connect(reverb).connect(audioContext.destination);
        }

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

                if ('mediaSession' in navigator) {
                    const artwork = [
                        { src: 'data:image/svg+xml;charset=UTF-8,<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 24 24" fill="none" stroke="%231DB954" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polygon points="10,8 16,12 10,16 10,8"></polygon></svg>', sizes: '96x96', type: 'image/svg+xml' },
                    ];

                    navigator.mediaSession.metadata = new MediaMetadata({
                        title: fileName.replace('.mp3', ''),
                        artwork: artwork
                    });
                    navigator.mediaSession.playbackState = 'playing';
                }
            } catch (e) {
                document.getElementById('player-song-title').textContent = ` + "`" + `Error: ${e.message}` + "`" + `;
            }
        }

        function startPlayback(offset) {
            if (!currentBuffer) return;
            sourceNode = audioContext.createBufferSource();
            sourceNode.buffer = currentBuffer;
            sourceNode.playbackRate.value = document.getElementById('speed-slider').value;
            connectAudioNodes();
            
            sourceNode.onended = () => {
                if (isAutoplayOn) {
                    playNext();
                } else {
                    stopSong(true);
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
                sourceNode.onended = null;
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
                if ('mediaSession' in navigator) {
                    navigator.mediaSession.metadata = null;
                    navigator.mediaSession.playbackState = 'none';
                }
            } else {
                if ('mediaSession' in navigator) {
                    navigator.mediaSession.playbackState = 'paused';
                }
            }
            document.getElementById('play-pause-icon').innerHTML = PLAY_ICON_PATH;
            if (animationFrameId) cancelAnimationFrame(animationFrameId);
        }

        function setupEventListeners() {
            document.querySelectorAll('.nav-item').forEach(item => item.addEventListener('click', e => {
                document.querySelector('.nav-item.active').classList.remove('active');
                e.currentTarget.classList.add('active');
                document.querySelector('.page.active').classList.remove('active');
                document.getElementById(e.currentTarget.dataset.page).classList.add('active');
            }));

            document.getElementById('song-list').addEventListener('click', e => {
                const playButton = e.target.closest('.play-btn');
                const deleteButton = e.target.closest('.delete-btn');
                if (playButton) playSong(parseInt(playButton.dataset.index));
                if (deleteButton) {
					const filename = deleteButton.dataset.name;
					if (confirm(` + "`" + `Delete "${filename}"?` + "`" + `)) {
						fetch('/api/delete', {
							method: 'POST',
							headers: {'Content-Type': 'application/json'},
							body: JSON.stringify({ filename: filename })
						})
						.then(response => {
                            if (!response.ok) {
                                return response.text().then(text => { throw new Error(text) });
                            }
                            return response.json();
                        })
						.then(data => {
							fetchAndRenderPlaylist();
						})
						.catch(err => alert('Error deleting song: ' + err));
					}
				}
            });

            document.getElementById('play-pause-btn').addEventListener('click', togglePlayPause);
            document.getElementById('next-btn').addEventListener('click', playNext);
            document.getElementById('prev-btn').addEventListener('click', playPrev);
            document.getElementById('expand-btn').addEventListener('click', () => { document.documentElement.requestFullscreen(); });

            document.getElementById('progress-bar-wrapper').addEventListener('click', e => {
                if (!currentBuffer) return;
                const rect = e.currentTarget.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const width = rect.width;
                const progress = Math.max(0, Math.min(1, x / width));
                const seekTime = currentBuffer.duration * progress;
                playSong(currentTrackIndex, seekTime);
            });

            document.getElementById('speed-slider').addEventListener('input', e => updateSpeed(e.target.value));
            document.getElementById('lows-slider').addEventListener('input', e => updateEffect(lowFilter.gain, e.target.value, v => ` + "`" + `${v} dB` + "`" + `, '#lows-val'));
            document.getElementById('highs-slider').addEventListener('input', e => updateEffect(highFilter.gain, e.target.value, v => ` + "`" + `${v} dB` + "`" + `, '#highs-val'));
            document.getElementById('reverb-slider').addEventListener('input', e => updateReverb(e.target.value));
            document.getElementById('distortion-slider').addEventListener('input', e => updateDistortion(e.target.value));

            const downloadHandler = async (query, source) => {
                if (!query) return;
                const btn = document.getElementById(` + "`" + `${source}-download-btn` + "`" + `);
                const input = document.getElementById(` + "`" + `${source}-input` + "`" + `);
                const originalText = btn.textContent;
                btn.textContent = 'Downloading...';
                btn.disabled = true;
                input.disabled = true;
                try {
                    const response = await fetch('/api/download', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ query: query, source: source })
                    });
                    if (!response.ok) {
                        const errorText = await response.text();
                        throw new Error(errorText || "Server error");
                    }
                    await fetchAndRenderPlaylist();
                } catch (err) {
                    alert('Download failed: ' + err.message);
                } finally {
                    btn.textContent = originalText;
                    btn.disabled = false;
                    input.disabled = false;
                    input.value = '';
                }
            };
            document.getElementById('youtube-download-btn').addEventListener('click', () => downloadHandler(document.getElementById('youtube-input').value, 'youtube'));
            document.getElementById('soundcloud-download-btn').addEventListener('click', () => downloadHandler(document.getElementById('soundcloud-input').value, 'soundcloud'));
        }

        function updateVisuals() {
            const bufferLength = analyser.frequencyBinCount;
            const dataArray = new Uint8Array(bufferLength);
            const draw = () => {
                if (!isPlaying) return;
                animationFrameId = requestAnimationFrame(draw);
                const playbackRate = sourceNode ? sourceNode.playbackRate.value : 1;
                const elapsedTime = (audioContext.currentTime - startTime) * playbackRate;
                const duration = currentBuffer.duration;
                const progress = elapsedTime / duration;
                document.getElementById('progress-bar-fill').style.width = ` + "`" + `${Math.min(progress * 100, 100)}%` + "`" + `;
                analyser.getByteFrequencyData(dataArray);
                canvasCtx.fillStyle = '#000';
                canvasCtx.fillRect(0, 0, canvas.width, canvas.height);
                const barWidth = (canvas.width / bufferLength) * 2.5;
                let x = 0;
                for (let i = 0; i < bufferLength; i++) {
                    const barHeight = dataArray[i];
                    const green = barHeight + 50;
                    const blue = barHeight / 2;
                    canvasCtx.fillStyle = ` + "`" + `rgb(50, ${green}, ${blue})` + "`" + `;
                    canvasCtx.fillRect(x, canvas.height - barHeight / 2, barWidth, barHeight / 2);
                    x += barWidth + 1;
                }
            };
            draw();
        }

        function renderSongList() {
            const listEl = document.getElementById('song-list');
            const filterText = document.getElementById('search-library').value.toLowerCase();
            const filteredSongs = audioFileNames.filter(name => name.toLowerCase().includes(filterText));

            listEl.innerHTML = '';
            if (audioFileNames.length === 0) {
                listEl.innerHTML = '<p style="color: var(--text-secondary); padding: 20px;">No songs found. Use the downloader pages to add music.</p>';
                return;
            }
             if (filteredSongs.length === 0) {
                 listEl.innerHTML = '<p style="color: var(--text-secondary); padding: 20px;">No songs match your filter.</p>';
                return;
            }
            filteredSongs.forEach(name => {
                const originalIndex = audioFileNames.indexOf(name);
                const item = document.createElement('div');
                item.className = 'song-list-item';
                item.innerHTML = ` + "`" + `
                    <button class="play-btn" data-index="${originalIndex}"><svg fill="currentColor" viewBox="0 0 20 20"><path d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8.13v3.74a1 1 0 001.555.832l3.197-1.87a1 1 0 000-1.664l-3.197-1.87z" clip-rule="evenodd"></path></svg></button>
                    <div class="song-details"><div class="title">${name.replace('.mp3','')}</div></div>
                    <button class="delete-btn" data-name="${name}"><svg fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"></path></svg></button>` + "`" + `;
                listEl.appendChild(item);
            });
        }
        document.getElementById('search-library').addEventListener('input', renderSongList);

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
        function resetEffects() {
            const sliders = {
                'speed-slider': { value: 1 }, 'lows-slider': { value: 0, node: lowFilter.gain, format: v => ` + "`" + `${v} dB` + "`" + `, valId: '#lows-val' },
                'highs-slider': { value: 0, node: highFilter.gain, format: v => ` + "`" + `${v} dB` + "`" + `, valId: '#highs-val' }, 'reverb-slider': { value: 0 }, 'distortion-slider': { value: 0 },
            };
            for (const [id, config] of Object.entries(sliders)) {
                if(!document.getElementById(id)) continue;
                document.getElementById(id).value = config.value;
                if(config.node) updateEffect(config.node, config.value, config.format, config.valId);
            }
            updateReverb(0); updateDistortion(0); updateSpeed(1);
        }
        function updateEffect(audioParam, value, formatFn, valId) {
            if (audioParam) audioParam.value = parseFloat(value);
            if(formatFn && valId) document.querySelector(valId).textContent = formatFn(value);
        }
        function updateSpeed(rate) {
            if (sourceNode) sourceNode.playbackRate.value = rate;
            updateEffect(null, rate, v => ` + "`" + `${parseFloat(v).toFixed(1)}x` + "`" + `, '#speed-val');
        }
        function updateDistortion(amount) {
            const k = Number(amount) * 100; const n_samples = 44100; const curve = new Float32Array(n_samples); const deg = Math.PI / 180;
            for (let i = 0; i < n_samples; ++i) { const x = i * 2 / n_samples - 1; curve[i] = (3 + k) * x * 20 * deg / (Math.PI + k * Math.abs(x)); }
            if (distortion) distortion.curve = curve;
            updateEffect(null, amount, v => ` + "`" + `${Math.round(v*100)}%` + "`" + `, '#distortion-val');
        }
        function updateReverb(amount) {
            if (dryGain && wetGain) { dryGain.gain.value = 1 - Math.pow(amount, 2); wetGain.gain.value = amount; }
            updateEffect(null, amount, v => ` + "`" + `${Math.round(v*100)}%` + "`" + `, '#reverb-val');
        }
        async function createReverbImpulse() {
            const sampleRate = audioContext.sampleRate; const duration = 2; const decay = 2;
            const impulse = audioContext.createBuffer(2, duration * sampleRate, sampleRate);
            for (let i = 0; i < 2; i++) {
                const channel = impulse.getChannelData(i);
                for (let j = 0; j < impulse.length; j++) channel[j] = (Math.random() * 2 - 1) * Math.pow(1 - j / impulse.length, decay);
            }
            return impulse;
        }
        function base64ToArrayBuffer(base64) {
            const binaryString = window.atob(base64); const len = binaryString.length; const bytes = new Uint8Array(len);
            for (let i = 0; i < len; i++) { bytes[i] = binaryString.charCodeAt(i); }
            return bytes.buffer;
        }
        
        document.addEventListener('DOMContentLoaded', initialize);
    </script>
</body>
</html>
`;
