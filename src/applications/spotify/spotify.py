import gc
import time
import jpegdec
import pngdec
import uasyncio as asyncio
import urequests as requests

from touch import Button

from applications.spotify.spotify_client import Session, SpotifyWebApiClient
from base import BaseApp
import secrets

class State:
    """Tracks the current state of the Spotify app including playback and UI controls."""
    def __init__(self):
        self.toggle_leds = True
        self.is_playing = False
        self.repeat = False
        self.shuffle = False
        self.track = None
        self.show_controls = False
        self.exit = False
        
        # New state variables
        self.volume = 50
        self.is_liked = False
        self.progress_ms = 0
        self.duration_ms = 0
        self.last_activity = time.time()
        self.is_dimmed = False

        self.latest_fetch = None
    
    def copy(self):
        state = State()
        state.toggle_leds = self.toggle_leds
        state.is_playing = self.is_playing
        state.repeat = self.repeat
        state.shuffle = self.shuffle
        state.show_controls = self.show_controls
        state.exit = self.exit
        state.track = {'id': self.track['id']} if self.track else None # only care about track id
        
        # Copy new state variables
        state.volume = self.volume
        state.is_liked = self.is_liked
        state.progress_ms = self.progress_ms
        state.duration_ms = self.duration_ms
        state.last_activity = self.last_activity
        state.is_dimmed = self.is_dimmed
        
        return state
    
    def __eq__(self, other):
        if not isinstance(other, State) or other is None:
            return False
        return (
            self.toggle_leds == other.toggle_leds and
            self.is_playing == other.is_playing and
            self.repeat == other.repeat and
            self.shuffle == other.shuffle and
            self.show_controls == other.show_controls and
            self.exit == other.exit and
            (self.track or {}).get('id') == (other.track or {}).get('id') and
            self.volume == other.volume and
            self.is_liked == other.is_liked and
            abs(self.progress_ms - other.progress_ms) < 5000 and  # Allow 5 second tolerance
            self.is_dimmed == other.is_dimmed
        )

class ControlButton():
    """Represents a control button with an icon and touch area."""
    def __init__(self, display, name, icons, bounds, on_press=None, update=None):
        self.name = name
        self.enabled = False
        self.icon = icons[0] if icons else None
        self.pngs = {}
        if icons:
            for icon in icons:
                png = pngdec.PNG(display)
                png.open_file("applications/spotify/icons/" + icon)
                self.pngs[icon] = png

        self.button = Button(*bounds)
        self.on_press = on_press
        self.update = update

    def is_pressed(self, state):
        """Checks if the button is enabled and currently pressed."""
        return self.enabled and self.button.is_pressed()
    
    def draw(self, state):
        """Draws the button icon if enabled."""
        if self.enabled and self.icon:
            self.draw_icon()

    def draw_icon(self):
        """Renders the button's icon centered inside its bounds."""
        png = self.pngs[self.icon]
        x, y, width, height = self.button.bounds
        png_width, png_height = png.get_width(), png.get_height()
        x_offset = (width-png_width)//2
        y_offset = (height-png_height)//2

        png.decode(x+x_offset, y+y_offset)

class Spotify(BaseApp):
    """Main Spotify app managing playback controls, track display, and UI interactions."""
    def __init__(self):
        super().__init__(ambient_light=True, full_res=True, layers=2)

        self.display.set_layer(0)
        icon = pngdec.PNG(self.display)
        icon.open_file("applications/spotify/icon.png")
        icon.decode(self.center_x - icon.get_width()//2, self.center_y - icon.get_height()//2 - 20)
        self.presto.update()

        self.display.set_font("sans")
        self.display.set_layer(1)
        self.display_text("Connecting to WIFI", (90, self.height - 80), thickness=2)
        self.presto.update()

        self.presto.connect()
        while not self.presto.wifi.isconnected():
            self.clear(1)
            self.display_text("Failed to connect to WIFI", (40, self.height - 80), thickness=2)
            time.sleep(2)

        self.clear(1)
        self.display_text("Instantiating Spotify Client", (35, self.height - 80), thickness=2)
        self.spotify_client = self.get_spotify_client()
        self.clear(1)
        self.presto.update()

        # JPEG decoder
        self.j = jpegdec.JPEG(self.display)

        self.state = State()
        self.setup_buttons()
    
    def display_text(self, text, position, color=65535, scale=1, thickness=None):
        if thickness:
            self.display.set_thickness(2)
        x,y = position
        self.display.set_pen(color)
        self.display.text(text, x, y, scale=scale)
        self.presto.update()

    def get_spotify_client(self):
        if not hasattr(secrets, 'SPOTIFY_CREDENTIALS') or not secrets.SPOTIFY_CREDENTIALS:
            while True:
                self.clear(1)
                self.display.set_pen(self.colors.WHITE)
                self.display.text("Spotify credentials not found", 40, self.height - 80, scale=.9)
                self.presto.update()
                time.sleep(2)

        session = Session(secrets.SPOTIFY_CREDENTIALS)
        return SpotifyWebApiClient(session)
        
    def setup_buttons(self):
        """Initializes control buttons and their behavior."""
        # --- Shared update functions ---
        def update_show_controls(state, button):
            button.enabled = state.show_controls

        def update_always_enabled(state, button):
            button.enabled = True

        def update_play_pause(state, button):
            button.enabled = state.show_controls
            button.icon = "pause.png" if state.is_playing else "play.png"

        def update_shuffle(state, button):
            button.enabled = state.show_controls
            button.icon = "shuffle_on.png" if state.shuffle else "shuffle_off.png"

        def update_repeat(state, button):
            button.enabled = state.show_controls
            button.icon = "repeat_on.png" if state.repeat else "repeat_off.png"

        def update_light(state, button):
            button.enabled = state.show_controls
            button.icon = "light_on.png" if state.toggle_leds else "light_off.png"
        
        def update_like(state, button):
            button.enabled = state.show_controls
            button.icon = "heart_filled.png" if state.is_liked else "heart_empty.png"

        # --- On-press handlers ---
        def exit_app(self):
            self.state.exit = True

        def toggle_controls(self):
            self.state.show_controls = not self.state.show_controls
            self.state.last_activity = time.time()

        def play_pause(self):
            if self.state.is_playing:
                self.spotify_client.pause()
            else:
                self.spotify_client.play()
            self.state.is_playing = not self.state.is_playing
            self.state.last_activity = time.time()

        def next_track(self):
            self.spotify_client.next()
            self.state.latest_fetch = None
            self.state.last_activity = time.time()

        def previous_track(self):
            self.spotify_client.previous()
            self.state.latest_fetch = None
            self.state.last_activity = time.time()

        def toggle_shuffle(self):
            self.spotify_client.toggle_shuffle(not self.state.shuffle)
            self.state.shuffle = not self.state.shuffle
            self.state.last_activity = time.time()

        def toggle_repeat(self):
            self.spotify_client.toggle_repeat(not self.state.repeat)
            self.state.repeat = not self.state.repeat
            self.state.last_activity = time.time()

        def toggle_lights(self):
            self.toggle_leds(not self.state.toggle_leds)
            self.state.toggle_leds = not self.state.toggle_leds
            self.state.last_activity = time.time()
        
        def volume_up(self):
            new_volume = min(100, self.state.volume + 10)
            self.spotify_client.set_volume(new_volume)
            self.state.volume = new_volume
            self.state.last_activity = time.time()
            print(f"Volume: {new_volume}%")
        
        def volume_down(self):
            new_volume = max(0, self.state.volume - 10)
            self.spotify_client.set_volume(new_volume)
            self.state.volume = new_volume
            self.state.last_activity = time.time()
            print(f"Volume: {new_volume}%")
        
        def toggle_like(self):
            if self.state.track:
                track_id = self.state.track.get('id')
                if self.state.is_liked:
                    self.spotify_client.remove_saved_track(track_id)
                else:
                    self.spotify_client.save_track(track_id)
                self.state.is_liked = not self.state.is_liked
                self.state.last_activity = time.time()
                print(f"Track {'liked' if self.state.is_liked else 'unliked'}")

        # --- Button configurations ---
        buttons_config = [
            ("Exit", ["exit.png"], (0, 0, 80, 80), exit_app, update_show_controls),
            ("Next", ["next.png"], (self.center_x + 60, self.height - 100, 80, 100), next_track, update_show_controls),
            ("Previous", ["previous.png"], (self.center_x - 140, self.height - 100, 80, 100), previous_track, update_show_controls),
            ("Play", ["play.png", "pause.png"], (self.center_x - 50, self.height - 100, 80, 100), play_pause, update_play_pause),
            ("Toggle Shuffle", ["shuffle_on.png", "shuffle_off.png"], (self.center_x - 230, self.height - 100, 80, 100), toggle_shuffle, update_shuffle),
            ("Toggle Repeat", ["repeat_on.png", "repeat_off.png"], (self.center_x + 150, self.height - 100, 80, 100), toggle_repeat, update_repeat),
            ("Toggle Light", ["light_on.png", "light_off.png"], (self.width - 100, 0, 100, 80), toggle_lights, update_light),
            ("Volume Up", ["volume_up.png"], (self.width - 100, 100, 80, 60), volume_up, update_show_controls),
            ("Volume Down", ["volume_down.png"], (self.width - 100, 170, 80, 60), volume_down, update_show_controls),
            ("Like", ["heart_empty.png", "heart_filled.png"], (20, self.height - 200, 60, 60), toggle_like, update_like),
            ("Toggle Controls", None, (0, 0, self.width, self.height), toggle_controls, update_always_enabled),
        ]

        # --- Create ControlButton instances ---
        self.buttons = [
            ControlButton(self.display, name, icons, bounds, on_press, update)
            for name, icons, bounds, on_press, update in buttons_config
        ]

    def run(self):
        """Starts the app's event loops."""
        loop = asyncio.get_event_loop()
        loop.create_task(self.touch_handler_loop())
        loop.create_task(self.display_loop())
        loop.run_forever()

    async def touch_handler_loop(self):
        """Handles touch input events and button presses."""
        while not self.state.exit:
            self.touch.poll()

            for button in self.buttons:
                button.update(self.state, button)
                if button.is_pressed(self.state):
                    print(f"{button.name} pressed")
                    try:
                        button.on_press(self)
                    except Exception as e:
                        print(f"Failed to execute on_press: {e}")
                    break
            
            # Wait here until the user stops touching the screen
            while self.touch.state:
                self.touch.poll()

            await asyncio.sleep_ms(1)

    def show_image(self, img, minimized=False):
        """Displays an album cover image on the screen."""
        try:
            self.j.open_RAM(memoryview(img))

            img_width, img_height = self.j.get_width(), self.j.get_height()
            img_x, img_y = (self.width - img_width) // 2, (self.height - img_height) // 2

            self.clear(0)
            self.j.decode(img_x, img_y, jpegdec.JPEG_SCALE_FULL, dither=True)

        except OSError:
            print("Failed to load image.")
        
    def write_track(self):
        """Writes the track name and artists on the screen."""
        if self.state.show_controls and self.state.track:
            self.display.set_thickness(3)

            track_name = self.state.track.get("name")
            # strip non-ascii characters
            track_name = ''.join(i if ord(i) < 128 else ' ' for i in track_name)
            if len(track_name) > 20:
                track_name = track_name[:20] + " ..."
            # shadow effect
            self.display.set_pen(self.colors._BLACK)
            self.display.text(track_name, 20, self.height - 137, scale=1.1)
            
            self.display.set_pen(self.colors.WHITE)
            self.display.text(track_name, 18, self.height - 140, scale=1.1)
            
            artists = ", ".join([artist.get("name") for artist in self.state.track.get("artists")])
            # strip non-ascii characters
            artists = ''.join(i if ord(i) < 128 else ' ' for i in artists)
            if len(artists) > 35:
                artists = artists[:35] + " ..."
            self.display.set_thickness(2)
            # shadow effect
            self.display.set_pen(self.colors._BLACK)
            self.display.text(artists, 20, self.height - 108, scale=0.7)
            
            self.display.set_pen(self.colors.WHITE)
            self.display.text(artists, 18, self.height - 111, scale=0.7)
            
            # Draw progress bar
            if self.state.duration_ms > 0:
                # Calculate progress percentage
                progress = self.state.progress_ms / self.state.duration_ms
                
                # Progress bar dimensions
                bar_x = 20
                bar_y = self.height - 240
                bar_width = self.width - 40
                bar_height = 6
                
                # Draw progress bar background
                self.display.set_pen(self.colors.GRAY)
                self.display.rectangle(bar_x, bar_y, bar_width, bar_height)
                
                # Draw progress bar fill
                self.display.set_pen(self.colors.WHITE)
                fill_width = int(bar_width * progress)
                if fill_width > 0:
                    self.display.rectangle(bar_x, bar_y, fill_width, bar_height)
                
                # Format and display time
                current_time = format_time(self.state.progress_ms // 1000)
                total_time = format_time(self.state.duration_ms // 1000)
                
                self.display.set_thickness(1)
                self.display.set_pen(self.colors.WHITE)
                self.display.text(current_time, bar_x, bar_y - 20, scale=0.7)
                self.display.text(total_time, bar_x + bar_width - 40, bar_y - 20, scale=0.7)
                
                # Display volume level
                volume_text = f"Vol: {self.state.volume}%"
                self.display.text(volume_text, self.width - 120, self.height - 40, scale=0.7)

    async def display_loop(self):
        """Periodically updates the display with the latest track info and controls."""
        INTERVAL = 10
        INACTIVITY_TIMEOUT = 30  # Seconds before dimming
        prev_state = None

        while not self.state.exit:
            update_display = False
            if not self.state.latest_fetch or time.time() - self.state.latest_fetch > INTERVAL:
                self.state.latest_fetch = time.time()
                result = fetch_state(self.spotify_client)
                if result:
                    device_id, self.state.track, self.state.is_playing, self.state.shuffle, self.state.repeat, self.state.volume, self.state.progress_ms, self.state.duration_ms = result
                    if device_id:
                        self.spotify_client.session.device_id = device_id
                    
                    # Check if track is liked
                    if self.state.track:
                        track_id = self.state.track.get('id')
                        try:
                            self.state.is_liked = self.spotify_client.check_saved_track(track_id)
                        except Exception as e:
                            print(f"Failed to check liked status: {e}")

            await asyncio.sleep(0)
            
            # Update progress if playing
            if self.state.is_playing and self.state.duration_ms > 0:
                # Estimate progress based on time passed
                time_passed = (time.time() - self.state.latest_fetch) * 1000
                self.state.progress_ms = min(self.state.progress_ms + time_passed, self.state.duration_ms)
            
            # Check for inactivity and auto-dim
            if time.time() - self.state.last_activity > INACTIVITY_TIMEOUT:
                if not self.state.is_dimmed:
                    self.state.is_dimmed = True
                    self.display.set_backlight(0.3)  # Dim to 30%
            else:
                if self.state.is_dimmed:
                    self.state.is_dimmed = False
                    self.display.set_backlight(1.0)  # Full brightness

            if not prev_state or (prev_state.track or {}).get('id') != (self.state.track or {}).get("id"):
                if self.state.track:
                    img = get_album_cover(self.state.track)
                    self.show_image(img)

            await asyncio.sleep(0)

            # update display if state changes
            if prev_state != self.state:
                self.clear(1)
                for button in self.buttons:
                    button.draw(self.state)
                self.write_track()

                self.presto.update()
                prev_state = self.state.copy()
            gc.collect()
            await asyncio.sleep_ms(200)

def format_time(seconds):
    """Formats seconds into MM:SS format."""
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes}:{seconds:02d}"

def fetch_state(spotify_client):
    """Fetches the current playback state from Spotify."""

    current_track = None
    is_playing = False
    shuffle = False
    repeat = False
    device_id = None
    volume = 50
    progress_ms = 0
    duration_ms = 0
    
    try:
        resp = spotify_client.current_playing()
        if resp and resp.get("item"):
            current_track = resp["item"]
            is_playing = resp.get("is_playing")
            shuffle = resp.get("shuffle_state")
            repeat = resp.get("repeat_state", "off") != "off" 
            device_id = resp["device"]["id"]
            volume = resp["device"].get("volume_percent", 50)
            progress_ms = resp.get("progress_ms", 0)
            duration_ms = current_track.get("duration_ms", 0)
            print("Got current playing track: " + current_track.get("name"))
    except Exception as e:
        print("Failed to get current playing track:", e)

    if not current_track:
        try:
            resp = spotify_client.recently_played()
            if resp and resp.get("items"):
                current_track = resp["items"][0]["track"]
                duration_ms = current_track.get("duration_ms", 0)
                print("Got recently playing track: " + current_track.get("name"))
        except Exception as e:
            print("Failed to get recently played track:", e)

    if not current_track:
        return None

    return device_id, current_track, is_playing, shuffle, repeat, volume, progress_ms, duration_ms

def get_album_cover(track):
    """Fetches and resizes the album cover image for the given track."""

    img_url = track["album"]["images"][1]["url"]
    
    img = None
    resize_url = f"https://wsrv.nl/?url={img_url}&w=480&h=480"
    try:
        response = requests.get(resize_url)
        if response.status_code == 200:
            img = response.content
        else:
            print("Failed to fetch image:", response.status_code)
    except Exception as e:
        print("Fetch image error:", e)
        
    return img

def launch():
    """Launches the Spotify app and starts the event loop."""
    app = Spotify()
    app.run()

    app.clear()
    del app
    gc.collect()