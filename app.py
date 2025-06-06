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
        }

            unique_video_options = {} 
            unique_audio_options = {} 

            for f in formats:
                vcodec = f.get('vcodec')
                acodec = f.get('acodec')
                format_id = f.get('format_id')
                ext = f.get('ext')
                filesize = f.get('filesize') or f.get('filesize_approx') 

                # --- Video Formats (with or without audio) ---
                if vcodec != 'none':
                    height = f.get('height')
                    if height:
                        resolution_str = f"{height}p"
                        if resolution_str in desired_video_qualities:

                            current_best = unique_video_options.get(resolution_str)
                            
                            if not current_best or \
                               (acodec != 'none' and current_best.get('acodec_status') == 'none') or \
                               (f.get('tbr') and current_best.get('tbr') and f.get('tbr') > current_best.get('tbr')):
                                
                                unique_video_options[resolution_str] = {
                                    'format_id': format_id,
                                    'ext': ext,
                                    'resolution': resolution_str,
                                    'filesize': filesize,
                                    'vcodec_status': vcodec,
                                    'acodec_status': acodec, 
                                    'note': f.get('format_note') 
                                }

                # --- Audio Formats (audio only) ---
                if acodec != 'none' and vcodec == 'none':
                    abr = f.get('abr') 
                    if abr:
                        for label, bitrate_kbps in desired_audio_bitrates.items():
                            if (bitrate_kbps - 5) <= abr <= (bitrate_kbps + 5):
                                current_best_audio = unique_audio_options.get(label)
                                if not current_best_audio or abr > current_best_audio.get('abr_value', 0):
                                    unique_audio_options[label] = {
                                        'format_id': format_id,
                                        'ext': ext,
                                        'abr': f'{int(abr)}k',
                                        'abr_value': abr,
                                        'label': label,
                                        'filesize': filesize
                                    }
                                break 

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
        print(f"Error in get_formats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data['url']
    format_id = data['format_id']
    is_audio = data.get('is_audio', False) 
    
    unique_filename_prefix = str(uuid.uuid4())

    ydl_opts = {
        'format': format_id,
        'outtmpl': f'{unique_filename_prefix}.%(ext)s',
        'postprocessors': [],
    }


    if is_audio: 
        ydl_opts['postprocessors'].append({
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        })

        ydl_opts['outtmpl'] = f'{unique_filename_prefix}.mp3'


    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info) 

        if os.path.exists(filename):
            response = send_file(filename, as_attachment=True)

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
        print(f"Error in download: {e}") 
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)