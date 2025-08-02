import weechat
import requests
import json
import time
import os
import webbrowser
from os.path import expanduser, join
from urllib.parse import urlencode

SCRIPT_NAME = "spotify_np"
SCRIPT_AUTHOR = "YourName"
SCRIPT_VERSION = "1.3"
SCRIPT_LICENSE = "MIT"
SCRIPT_DESC = "Announce current Spotify track with /np"

# Path to your existing Limnoria Spotify files
LIMNORIA_SPOTIFY_DIR = "/home/USER/limnoria/plugins/Spotify"
CREDENTIALS_PATH = join(LIMNORIA_SPOTIFY_DIR, "spotify_credentials.json")
CACHE_PATH = join(LIMNORIA_SPOTIFY_DIR, ".spotify_cache")
REDIRECT_URI = "http://localhost:8080"
SCOPES = "user-read-currently-playing"

def debug_print(message):
    """Print debug messages to WeeChat's core buffer"""
    weechat.prnt("", f"[{SCRIPT_NAME}] {message}")

def load_credentials():
    """Load credentials from existing Limnoria files"""
    try:
        # Load from credentials.json
        with open(CREDENTIALS_PATH) as f:
            credentials = json.load(f)
            client_id = credentials['client_id']
            client_secret = credentials['client_secret']
            
            # Try to get refresh_token from credentials.json first
            refresh_token = credentials.get('refresh_token')
            
            # Fall back to .spotify_cache if not in credentials.json
            if not refresh_token and os.path.exists(CACHE_PATH):
                with open(CACHE_PATH) as cache_file:
                    refresh_token = cache_file.read().strip()
            
            if not client_id or not client_secret or not refresh_token:
                raise ValueError("Missing required credentials")
            
            return client_id, client_secret, refresh_token
            
    except Exception as e:
        debug_print(f"Error loading credentials: {str(e)}")
        raise

def save_refresh_token(token):
    """Save refresh token to both locations to match Limnoria behavior"""
    try:
        # Update credentials.json if it has refresh_token field
        with open(CREDENTIALS_PATH, 'r+') as f:
            credentials = json.load(f)
            if 'refresh_token' in credentials:
                credentials['refresh_token'] = token
                f.seek(0)
                json.dump(credentials, f)
                f.truncate()
        
        # Always update .spotify_cache
        with open(CACHE_PATH, 'w') as f:
            f.write(token)
            
    except Exception as e:
        debug_print(f"Error saving refresh token: {str(e)}")

class SpotifyClient:
    def __init__(self):
        self.client_id, self.client_secret, self.refresh_token = load_credentials()
        self.access_token = None
        self.expires_at = 0
    
    def start_authentication(self):
        """Start OAuth2 authentication flow"""
        auth_url = "https://accounts.spotify.com/authorize?" + urlencode({
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "open_browser": False
        })
        
        debug_print(f"Please visit this URL to authenticate: {auth_url}")
        debug_print("After authorization, run /spotify_set_token with the code from the URL")
        
        try:
            webbrowser.open(auth_url)
        except:
            debug_print("Could not open browser automatically - please copy/paste the URL")
    
    def exchange_code_for_token(self, code):
        """Exchange authorization code for tokens"""
        response = requests.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            self.access_token = data["access_token"]
            self.refresh_token = data["refresh_token"]
            self.expires_at = time.time() + data["expires_in"]
            save_refresh_token(self.refresh_token)
            debug_print("Successfully authenticated with Spotify!")
            return True
        else:
            debug_print(f"Error getting token: {response.text}")
            return False
    
    def refresh_access_token(self):
        """Refresh the access token using refresh token"""
        response = requests.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            self.access_token = data["access_token"]
            self.expires_at = time.time() + data["expires_in"]
            
            # Save new refresh token if one was returned
            if "refresh_token" in data:
                self.refresh_token = data["refresh_token"]
                save_refresh_token(self.refresh_token)
            
            return True
        else:
            debug_print(f"Error refreshing token: {response.text}")
            if response.json().get("error") == "invalid_grant":
                debug_print("Refresh token invalid - need to reauthenticate")
                self.start_authentication()
            return False
    
    def get_current_track(self):
        """Get currently playing track from Spotify API"""
        if not self.access_token or time.time() > self.expires_at - 60:
            if not self.refresh_access_token():
                return None
        
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            response = requests.get(
                "https://api.spotify.com/v1/me/player/currently-playing",
                headers=headers,
                timeout=5
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 204:
                return {"is_playing": False}
            else:
                debug_print(f"API error: {response.text}")
                return None
        except Exception as e:
            debug_print(f"Network error: {str(e)}")
            return None    

def format_track_info(track_data):
    """Format track information for display"""
    if not track_data or not track_data.get("is_playing", True):
        return None
    
    # Track info
    item = track_data.get("item", {})
    artists = ", ".join([artist["name"] for artist in item.get("artists", [])])
    track_name = item.get("name", "Unknown Track")
    album_name = item.get("album", {}).get("name", "Unknown Album")
    # Get Spotify URL
    url = item.get('external_urls', {}).get('spotify', '')
    url_text = f"Listen: {url}" if url else ""

    # Add duration and progress information
    duration_ms = item.get("duration_ms", 0)
    progress_ms = track_data.get("progress_ms", 0)

    def ms_to_minutes_seconds(ms):
        """Convert milliseconds to minutes:seconds format."""
        total_seconds = ms // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{int(minutes)}:{int(seconds):02d}"
    
    current_position = ms_to_minutes_seconds(progress_ms)
    total_duration = ms_to_minutes_seconds(duration_ms)
    
    return f"🎵 Now playing: {artists} - {track_name} | (from {album_name}) | Progress: {current_position}/{total_duration} | {url_text}"

# Global Spotify client instance
spotify = None

def np_command_cb(data, buffer, args):
    """Handle /np command"""
    global spotify
    try:
        track_data = spotify.get_current_track()
        if not track_data:
            debug_print("Couldn't get current track")
            return weechat.WEECHAT_RC_OK
        
        track_info = format_track_info(track_data)
        if track_info:
            weechat.command(buffer, f"{track_info}")
        else:
            debug_print("No track currently playing")
    except Exception as e:
        debug_print(f"Error in np_command_cb: {str(e)}")
    
    return weechat.WEECHAT_RC_OK

# Main initialization
if __name__ == "__main__" and weechat.register(
    SCRIPT_NAME,
    SCRIPT_AUTHOR,
    SCRIPT_VERSION,
    SCRIPT_LICENSE,
    SCRIPT_DESC,
    "",
    ""
):
    debug_print(f"Loading {SCRIPT_NAME} v{SCRIPT_VERSION}")
    
    try:
        spotify = SpotifyClient()
        
        # Register commands
        weechat.hook_command(
            "np",
            "Announce current Spotify track",
            "",
            "Shows currently playing track in chat",
            "",
            "np_command_cb",
            ""
        )
        
        debug_print("Script loaded. Commands available:")
        debug_print("/np - Announce current track")
        
        # Try initial token refresh
        if not spotify.refresh_access_token():
            debug_print("Initial token refresh failed - you may need to reauthenticate")
    
    except Exception as e:
        debug_print(f"Initialization failed: {str(e)}")

        debug_print(f"Please check your credentials in {LIMNORIA_SPOTIFY_DIR}")
