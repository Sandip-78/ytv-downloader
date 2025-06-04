from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import uuid

app = Flask(__name__)

@app.route('/')
def index():
    return send_file('index.html')

@app.route('/style.css')
def serve_css():
    return send_file('style.css')


@app.route('/get_formats', methods=['POST'])
def get_formats():
    url = request.json['url']
    ydl_opts = {}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            formats = info_dict.get('formats', [])

            desired_video_qualities = ['360p', '480p', '720p', '1080p']
            desired_audio_bitrates = {
            'fast(128k)': 128,
            'classic mp3(320k)': 320,
            'classic mp3(160k)': 160
            # Removed duplicate 128k label for clarity
        }

            # To store unique formats, prioritizing combined streams
            unique_video_options = {} # Key: resolution (e.g., '720p'), Value: best format for that resolution
            unique_audio_options = {} # Key: label (e.g., 'classic mp3(128k)'), Value: best format for that bitrate

            for f in formats:
                vcodec = f.get('vcodec')
                acodec = f.get('acodec')
                format_id = f.get('format_id')
                ext = f.get('ext')
                filesize = f.get('filesize') or f.get('filesize_approx') # Prefer exact size, fall back to approx

                # --- Video Formats (with or without audio) ---
                if vcodec != 'none':
                    height = f.get('height')
                    if height:
                        resolution_str = f"{height}p"
                        if resolution_str in desired_video_qualities:
                            # Prioritize formats that include audio (for direct download)
                            # Or if it's a video-only format, store it if a combined one isn't found yet
                            current_best = unique_video_options.get(resolution_str)
                            
                            # If no format for this resolution yet, or if current format is video-only
                            # and this one is combined (has audio), or if this one is better quality (e.g., higher bitrate)
                            if not current_best or \
                               (acodec != 'none' and current_best.get('acodec_status') == 'none') or \
                               (f.get('tbr') and current_best.get('tbr') and f.get('tbr') > current_best.get('tbr')): # total bitrate
                                
                                unique_video_options[resolution_str] = {
                                    'format_id': format_id,
                                    'ext': ext,
                                    'resolution': resolution_str,
                                    'filesize': filesize,
                                    'vcodec_status': vcodec,
                                    'acodec_status': acodec, # To know if it's combined or video-only
                                    'note': f.get('format_note') # Useful for debugging or displaying extra info
                                }

                # --- Audio Formats (audio only) ---
                if acodec != 'none' and vcodec == 'none':
                    abr = f.get('abr') # Average bitrate in kbit/s
                    if abr:
                        for label, bitrate_kbps in desired_audio_bitrates.items():
                            # Allow for a small range around the desired bitrate
                            if (bitrate_kbps - 5) <= abr <= (bitrate_kbps + 5):
                                current_best_audio = unique_audio_options.get(label)
                                # If no format for this label yet, or if this one has a higher bitrate
                                if not current_best_audio or abr > current_best_audio.get('abr_value', 0):
                                    unique_audio_options[label] = {
                                        'format_id': format_id,
                                        'ext': ext,
                                        'abr': f'{int(abr)}k',
                                        'abr_value': abr, # Store original abr for comparison
                                        'label': label,
                                        'filesize': filesize
                                    }
                                break # Found a match for this audio format, move to next f

            # Convert dictionaries to lists for jsonify, and sort them
            filtered_video_formats = sorted(
                list(unique_video_options.values()),
                key=lambda x: int(x['resolution'].replace('p', '')),
                reverse=True
            )
            filtered_audio_formats = sorted(
                list(unique_audio_options.values()),
                key=lambda x: x['abr_value'],
                reverse=True
            )

            return jsonify({
                'title': info_dict['title'],
                'video': filtered_video_formats,
                'audio': filtered_audio_formats
            })
    except Exception as e:
        print(f"Error in get_formats: {e}") # Log the error for debugging
        return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data['url']
    format_id = data['format_id']
    is_audio = data.get('is_audio', False) # New: pass a flag from frontend
    
    unique_filename_prefix = str(uuid.uuid4())

    ydl_opts = {
        'format': format_id,
        'outtmpl': f'{unique_filename_prefix}.%(ext)s',
        'postprocessors': [],
    }

    # If it's an audio download and we want MP3, add the postprocessor
    if is_audio: # You need to pass 'is_audio: true' from your frontend for audio selections
        ydl_opts['postprocessors'].append({
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192', # You can adjust this quality or make it user-selectable
        })
        # If converting to MP3, ensure the output extension is mp3
        ydl_opts['outtmpl'] = f'{unique_filename_prefix}.mp3'


    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info) # Get the actual final filename

        # Ensure the file exists before sending
        if os.path.exists(filename):
            # After sending the file, you might want to delete it from the server
            # This is crucial for cleanup, especially in a production environment.
            # However, be careful with concurrent downloads; a simple delete here might remove
            # a file another request is still preparing to send.
            # For simplicity in development, you can delete it immediately after sending.
            # In production, consider a background cleanup task or a more robust file management.
            response = send_file(filename, as_attachment=True)
            # Schedule file deletion after the response is sent
            @response.call_on_close
            def after_request():
                try:
                    os.remove(filename)
                    print(f"Deleted downloaded file: {filename}")
                except Exception as e:
                    print(f"Error deleting file {filename}: {e}")
            return response
        else:
            return jsonify({'error': 'Downloaded file not found.'}), 500
    except Exception as e:
        print(f"Error in download: {e}") # Log the error for debugging
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)