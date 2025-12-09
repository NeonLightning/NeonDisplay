#!/usr/bin/env python3
import json, time, threading, os, toml, fcntl
from spotipy.oauth2 import SpotifyOAuth

class SpotifyAuthManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.config = self._load_config()
        self.sp_oauth = SpotifyOAuth(
            client_id=self.config["api_keys"]["client_id"],
            client_secret=self.config["api_keys"]["client_secret"],
            redirect_uri=self.config["api_keys"]["redirect_uri"],
            scope = "user-read-currently-playing user-modify-playback-state user-read-playback-state playlist-modify-private playlist-modify-public playlist-read-private playlist-read-collaborative user-read-private",
            cache_path=".spotify_cache",
            open_browser=False,
            show_dialog=False
        )
        self.last_refresh = 0
        self.refresh_lock = threading.Lock()
        self.refresh_attempts = 0
        self.max_refresh_attempts = 3
        self._ensure_cache_directory()

    def _needs_refresh_soon(self, token_info, buffer_seconds=300):
        expires_at = token_info.get('expires_at', 0)
        return (expires_at - time.time()) < buffer_seconds

    def _load_config(self):
        config_path = "config.toml"
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with open(config_path, 'r') as f:
            return toml.load(f)

    def _ensure_cache_directory(self):
        cache_dir = os.path.dirname(".spotify_cache")
        if cache_dir and not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)

    def _reset_oauth(self):
        self.sp_oauth = SpotifyOAuth(
            client_id=self.config["api_keys"]["client_id"],
            client_secret=self.config["api_keys"]["client_secret"],
            redirect_uri=self.config["api_keys"]["redirect_uri"],
            scope="user-read-currently-playing user-modify-playback-state user-read-playback-state playlist-modify-private playlist-modify-public playlist-read-private playlist-read-collaborative user-read-private",
            cache_path=".spotify_cache",
            open_browser=False,
            show_dialog=False
        )

    def get_valid_token(self, timeout=10):
        start_time = time.time()
        with self.refresh_lock:
            if self.refresh_attempts >= self.max_refresh_attempts:
                time_since_last = time.time() - self.last_refresh
                if time_since_last < 60:
                    print(f"⚠️ Too many refresh attempts, waiting {60 - time_since_last:.0f}s")
                    return None
                else:
                    self.refresh_attempts = 0
            cache_lock_path = ".spotify_cache.lock"
            lock_file = open(cache_lock_path, 'w')
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                token_info = None
                try:
                    token_info = self.sp_oauth.get_cached_token()
                except (AttributeError, TypeError):
                    if os.path.exists('.spotify_cache'):
                        try:
                            with open('.spotify_cache', 'r') as f:
                                token_info = json.load(f)
                        except Exception:
                            pass
                if not token_info:
                    print("❌ No cached token found")
                    self.refresh_attempts += 1
                    return None
                if time.time() - start_time > timeout:
                    print("⏱️ Token fetch timeout")
                    return None
                if self.sp_oauth.is_token_expired(token_info) or self._needs_refresh_soon(token_info):
                    try:
                        self._reset_oauth()
                        token_info = self.sp_oauth.refresh_access_token(
                            token_info['refresh_token']
                        )
                        self._backup_token(token_info)
                        self.last_refresh = time.time()
                        self.refresh_attempts = 0  # Reset on success
                        print(f"✅ Token refreshed, expires at {token_info.get('expires_at', 'unknown')}")
                    except Exception as e:
                        print(f"❌ Token refresh failed: {e}")
                        self.refresh_attempts += 1
                        if self.refresh_attempts == 1:
                            if self._recover_from_backup():
                                return self.get_valid_token(timeout=max(3, timeout - (time.time() - start_time)))
                        return None
                return token_info['access_token']
            except BlockingIOError:
                print("🔒 Lock already held by another process")
                return None
            finally:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except:
                    pass
                lock_file.close()

    def _backup_token(self, token_info):
        expires_at = token_info.get('expires_at', 0)
        if expires_at > time.time() + 300:
            backup = {
                'access_token': token_info.get('access_token'),
                'refresh_token': token_info.get('refresh_token'),
                'expires_at': token_info.get('expires_at'),
                'scope': token_info.get('scope'),
                'backup_time': time.time()
            }
            try:
                with open('.spotify_token_backup.json', 'w') as f:
                    json.dump(backup, f)
                print("💾 Token backup created")
            except Exception as e:
                print(f"⚠️ Backup failed: {e}")

    def _recover_from_backup(self):
        if not os.path.exists('.spotify_token_backup.json'):
            return False
        print("📄 Attempting token recovery from backup...")
        try:
            with open('.spotify_token_backup.json', 'r') as f:
                backup = json.load(f)
            backup_time = backup.get('backup_time', 0)
            if time.time() - backup_time > 7 * 24 * 3600:
                print("⚠️ Backup too old, ignoring")
                return False
            expires_at = backup.get('expires_at', 0)
            if expires_at < time.time():
                print("⚠️ Backup token expired, attempting refresh...")
                try:
                    self._reset_oauth()
                    refreshed = self.sp_oauth.refresh_access_token(
                        backup['refresh_token']
                    )
                    backup = refreshed
                    print("✅ Backup token refreshed")
                except Exception as e:
                    print(f"❌ Backup refresh failed: {e}")
                    return False
            with open('.spotify_cache', 'w') as f:
                json.dump(backup, f)
            print("✅ Recovered token from backup")
            return True
        except Exception as e:
            print(f"❌ Backup recovery failed: {e}")
            return False

    def get_token_health(self):
        if not os.path.exists('.spotify_cache'):
            return "no_token", "No token cache found"
        try:
            with open('.spotify_cache', 'r') as f:
                cache = json.load(f)
            expires_at = cache.get('expires_at', 0)
            time_left = expires_at - time.time()
            if time_left < 0:
                return "expired", f"Token expired {abs(time_left)/60:.0f} minutes ago"
            elif time_left < 300:  # 5 minutes
                return "critical", f"Token expires in {time_left/60:.1f} minutes"
            elif time_left < 3600:  # 1 hour
                return "warning", f"Token expires in {time_left/60:.0f} minutes"
            else:
                return "healthy", f"Token valid for {time_left/3600:.1f} hours"
        except Exception as e:
            return "error", f"Token check error: {str(e)}"

    def force_refresh(self):
        with self.refresh_lock:
            token_info = self.sp_oauth.get_cached_token()
            if token_info and 'refresh_token' in token_info:
                print("🔧 Forcing token refresh...")
                try:
                    self._reset_oauth()
                    token_info = self.sp_oauth.refresh_access_token(
                        token_info['refresh_token']
                    )
                    self._backup_token(token_info)
                    self.last_refresh = time.time()
                    self.refresh_attempts = 0
                    print("✅ Force refresh successful")
                    return True
                except Exception as e:
                    print(f"❌ Force refresh failed: {e}")
                    self.refresh_attempts += 1
                    return False
            return False

def get_spotify_client(timeout=10):
    try:
        auth_manager = SpotifyAuthManager()
        token = auth_manager.get_valid_token(timeout=timeout)
        if not token:
            print("❌ Could not get valid token")
            return None
        import spotipy
        return spotipy.Spotify(auth=token)
    except Exception as e:
        print(f"❌ Error getting Spotify client: {e}")
        return None

if __name__ == "__main__":
    print("Testing Spotify Auth Manager...")
    sp = get_spotify_client()
    if sp:
        user = sp.current_user()
        print(f"✅ Authenticated as: {user.get('display_name', 'Unknown')}")
        auth_manager = SpotifyAuthManager()
        status, message = auth_manager.get_token_health()
        print(f"Token health: {status} - {message}")
    else:
        print("❌ Failed to authenticate")