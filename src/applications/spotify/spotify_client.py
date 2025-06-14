import sys

import urequests as requests
import usocket as socket
import ujson as json

class SpotifyWebApiClient:
    def __init__(self, session):
        self.session = session

    def play(self, context_uri=None, uris=None, offset=None, position_ms=None):
        request_body = {}
        if context_uri is not None:
            request_body['context_uri'] = context_uri
        if uris is not None:
            request_body['uris'] = list(uris)
        if offset is not None:
            request_body['offset'] = offset
        if position_ms is not None:
            request_body['position_ms'] = position_ms

        self.session.put(
            url='https://api.spotify.com/v1/me/player/play',
            json=request_body,
        )

    def pause(self):
        self.session.put(
            url='https://api.spotify.com/v1/me/player/pause',
        )
    
    def toggle_shuffle(self, state):
        value = "true" if state else "false"
        self.session.put(
            url=f'https://api.spotify.com/v1/me/player/shuffle?state={value}',
        )
    
    def toggle_repeat(self, state):
        value = "track" if state else 'off'
        self.session.put(
            url=f'https://api.spotify.com/v1/me/player/repeat?state={value}',
        )
    
    def next(self):
        self.session.post(
            url='https://api.spotify.com/v1/me/player/next',
        )

    def previous(self):
        self.session.post(
            url='https://api.spotify.com/v1/me/player/previous',
        )

    def current_playing(self):
        return self.session.get(
            url='https://api.spotify.com/v1/me/player',
        )
    
    def recently_played(self):
        return self.session.get(
            url='https://api.spotify.com/v1/me/player/recently-played?limit=1',
        )

    def set_volume(self, volume_percent):
        self.session.put(
            url=f'https://api.spotify.com/v1/me/player/volume?volume_percent={volume_percent}',
        )
    
    def check_saved_track(self, track_id):
        result = self.session.get(
            url=f'https://api.spotify.com/v1/me/tracks/contains?ids={track_id}',
        )
        return result[0] if result else False
    
    def save_track(self, track_id):
        self.session.put(
            url=f'https://api.spotify.com/v1/me/tracks?ids={track_id}',
        )
    
    def remove_saved_track(self, track_id):
        self.session.delete(
            url=f'https://api.spotify.com/v1/me/tracks?ids={track_id}',
        )

class Device:
    def __init__(
        self,
        id,
        is_active,
        is_private_session,
        is_restricted,
        name,
        type,
        volume_percent,
        **kwargs
    ):
        self.id = id
        self.is_active = is_active
        self.is_private_session = is_private_session
        self.is_restricted = is_restricted
        self.name = name
        self.type = type
        self.volume_percent = volume_percent

    def __repr__(self):
        return 'Device(name={}, type={}, id={})'.format(self.name, self.type, self.id)

class Session:
    def __init__(self, credentials):
        self.credentials = credentials
        self.device_id = credentials['device_id']
        if 'access_token' not in credentials:
            self._refresh_access_token()

    def get(self, url, **kwargs):
        def get_request():
            return requests.get(
                url,
                headers=self._headers(),
                **kwargs,
            )

        return self._execute_request(get_request)

    def put(self, url, json=None, **kwargs):
        # Workaround for urequests not sending "Content-Length" on empty data
        if json is None:
            json = {}

        def put_request():
            return requests.put(
                url=self._add_device_id(url),
                headers=self._headers(),
                json=json,
                **kwargs,
            )

        return self._execute_request(put_request)
    
    def post(self, url, json=None, **kwargs):
        # Workaround for urequests not sending "Content-Length" on empty data
        if json is None:
            json = {}

        def post_request():
            return requests.post(
                url=self._add_device_id(url),
                headers=self._headers(),
                json=json,
                **kwargs,
            )

        return self._execute_request(post_request)

    def delete(self, url, json=None, **kwargs):
        # Workaround for urequests not sending "Content-Length" on empty data
        if json is None:
            json = {}

        def delete_request():
            return requests.delete(
                url=self._add_device_id(url),
                headers=self._headers(),
                json=json,
                **kwargs,
            )

        return self._execute_request(delete_request)

    def _headers(self):
        return {'Authorization': 'Bearer {access_token}'.format(**self.credentials)}

    def _execute_request(self, request):
        response = request()
        if response.status_code == 401:
            error = Session._error_from_response(response)

            if error['message'] == 'The access token expired':
                self._refresh_access_token()
                response = request()  # Retry

        self._check_status_code(response)
        content_type = response.headers.get("content-type")
        if response.content and content_type and content_type.startswith("application/json"):
            resp_json = response.json()
            response.close()
            return resp_json
        response.close()
        

    @staticmethod
    def _check_status_code(response):
        if response.status_code >= 400:
            error = Session._error_from_response(response)
            response.close()
            raise SpotifyWebApiError(**error)

    @staticmethod
    def _error_from_response(response):
        try:
            error = response.json()['error']
            message = error['message']
            reason = error.get('reason')
        except (ValueError, KeyError):
            message = response.text
            reason = None
        return {'message': message, 'status': response.status_code, 'reason': reason}

    def _add_device_id(self, url):
        join = '&' if '?' in url else '?'
        return '{path}{join}device_id={device_id}'.format(path=url, join=join, device_id=self.device_id) if self.device_id else url

    def _refresh_access_token(self):
        token_endpoint = "https://accounts.spotify.com/api/token"
        params = dict(
            grant_type="refresh_token",
            refresh_token=self.credentials['refresh_token'],
            client_id=self.credentials['client_id'],
            client_secret=self.credentials['client_secret'],
        )
        retries = 3
        while retries:
            try:
                response = requests.post(
                    token_endpoint,
                    headers={'Content-Type': 'application/x-www-form-urlencoded'},
                    data=urlencode(params),
                )
                self._check_status_code(response)
                retries -= 1
            except Exception as E:
                retries -= 1
                if retries:
                    print("Failed to refresh access token, retrying")
                else:
                    print("Failed to refresh access token after 3 tries, giving up")

        tokens = response.json()
        response.close()
        self.credentials['access_token'] = tokens['access_token']
        if 'refresh_token' in tokens:
            self.credentials['refresh_token'] = tokens['refresh_token']

class SpotifyWebApiError(Exception):
    def __init__(self, message, status=None, reason=None):
        super().__init__(message)
        self.status = status
        self.reason = reason

def quote(s):
    always_safe = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' 'abcdefghijklmnopqrstuvwxyz' '0123456789' '_.-'
    res = []
    for c in s:
        if c in always_safe:
            res.append(c)
            continue
        res.append('%%%x' % ord(c))
    return ''.join(res)

def quote_plus(s):
    s = quote(s)
    if ' ' in s:
        s = s.replace(' ', '+')
    return s

def unquote(s):
    res = s.split('%')
    for i in range(1, len(res)):
        item = res[i]
        try:
            res[i] = chr(int(item[:2], 16)) + item[2:]
        except ValueError:
            res[i] = '%' + item
    return "".join(res)

def urlencode(query):
    if isinstance(query, dict):
        query = query.items()
    li = []
    for k, v in query:
        if not isinstance(v, list):
            v = [v]
        for value in v:
            k = quote_plus(str(k))
            v = quote_plus(str(value))
            li.append(k + '=' + v)
    return '&'.join(li)
