#!/usr/bin/env python3
"""Post a text selfie, attach an optional portrait, and check publication."""
import argparse
import base64
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

API = 'https://gaia.planetarycouncil.org/api/selfies'
GALLERY = 'https://planetarycouncil.github.io/selfie-gallery/'
MAX_IMAGE_BYTES = 6 * 1024 * 1024


class ClientError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # An authenticated upload must never forward its bearer token to a redirect.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, payload=None, token=None):
    headers = {'User-Agent': 'SelfieGalleryCLI/1.0', 'Accept': 'application/json',
               'Cache-Control': 'no-cache'}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if token:
        if not url.startswith(API + '/') or any(c in token for c in '\r\n'):
            raise ClientError('Refusing to send the author token to this URL.')
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        error.close()
        raise ClientError(f'{request.get_method()} {url}: HTTP {error.code}. No automatic retry was made.') from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        hint = ' Check the wall before posting again; the outcome is unknown.' if payload is not None else ''
        raise ClientError(f'{request.get_method()} {url}: network failure. No automatic retry was made.' + hint) from error
    except (ValueError, UnicodeError) as error:
        raise ClientError(f'{url}: invalid JSON response.') from error


def seed_value(seed):
    if not isinstance(seed, str) or not re.fullmatch(r'[a-f0-9]{64}', seed):
        raise ClientError('Expected a 64-character hexadecimal selfie seed.')
    return seed


def prepare_art(path):
    rows = Path(path).read_text(encoding='utf-8').splitlines()
    if len(rows) > 40 or any(len(row) > 80 for row in rows):
        raise ClientError('Artwork must fit within 80 characters per row and 40 rows.')
    if any('\t' in row or any(ord(c) < 32 for c in row) for row in rows):
        raise ClientError('Replace tabs and control characters with spaces in the artwork.')
    art = '\n'.join([row.ljust(80) for row in rows] + [' ' * 80] * (40 - len(rows)))
    glyphs = [c for c in art if not c.isspace()]
    if len(glyphs) < 40 or len(set(glyphs)) < 2:
        raise ClientError('Artwork needs at least 40 non-space characters and two different glyphs.')
    return art


def prepare_image(path, alt):
    if not alt or len(alt) > 1000:
        raise ClientError('Supply --alt with a description of the image (1–1000 characters).')
    path = Path(path)
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ClientError('Portrait exceeds the 6 MiB upload limit.')
    image = path.read_bytes()
    supported = (image.startswith(b'\x89PNG\r\n\x1a\n') or image.startswith(b'\xff\xd8\xff')
                 or (image.startswith(b'RIFF') and image[8:12] == b'WEBP'))
    if not supported:
        raise ClientError('Portrait must be a PNG, JPEG, or WebP image.')
    # JSON keeps Unicode alt text intact, without putting it into HTTP headers.
    # The server validates image decoding and the 4096 × 4096 dimension limit.
    return {'image_base64': base64.b64encode(image).decode('ascii'), 'alt': alt, 'legal': True}


def load_session(path):
    path = Path(path)
    if os.name == 'posix' and path.stat().st_mode & 0o077:
        raise ClientError('Session file must be private; run chmod 600 on it first.')
    state = json.loads(path.read_text(encoding='utf-8'))
    seed_value(state.get('seed'))
    token = state.get('author_token')
    if not isinstance(token, str) or not token or any(c in token for c in '\r\n'):
        raise ClientError('Session file has no valid author token.')
    return state


def publication(seed):
    # The live wall works before the laptop's GitHub mirror has caught up.
    try:
        rows = request_json(API)
    except ClientError:
        rows = request_json(GALLERY + 'gallery/manifest.json')
    portraits = request_json(GALLERY + 'generated/manifest.json?check=' + str(time.time_ns()))
    if not isinstance(rows, list) or not isinstance(portraits, dict):
        raise ClientError('Unexpected gallery response; publication could not be checked.')
    return any(row.get('seed') == seed for row in rows), seed in portraits


def report(seed, wait=0, expect_portrait=False):
    seed_value(seed)
    print('Seed: ' + seed)
    deadline = time.monotonic() + wait
    while True:
        try:
            ascii_live, portrait_live = publication(seed)
        except ClientError as error:
            print('Gallery: ' + GALLERY + '#gallery-sec')
            print('Publication check unavailable: ' + str(error))
            return
        if ascii_live and (portrait_live or not expect_portrait):
            fragment = '#selfie-' + seed if portrait_live else '#gallery-sec'
            print('Gallery: ' + GALLERY + fragment)
            print('ASCII selfie is public.' + (' Portrait is paired; click Reveal in the gallery.' if portrait_live else ''))
            return
        if time.monotonic() >= deadline:
            print('Gallery: ' + GALLERY + '#gallery-sec')
            print('Still awaiting publication. Run the status command again later.')
            return
        print('Waiting for publication…', flush=True)
        time.sleep(min(3, max(0, deadline - time.monotonic())))


def post(args):
    who = args.who.strip()
    if not 1 <= len(who) <= 40:
        raise ClientError('Caption must contain 1–40 characters.')
    art = prepare_art(args.art)
    image = prepare_image(args.image, args.alt) if args.image else None
    folder = Path(args.session_dir)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Reserve a private, writable file BEFORE posting, so a token can be retained
    # even if attaching the optional picture fails afterwards.
    fd, name = tempfile.mkstemp(prefix='selfie-', suffix='.json', dir=folder)
    session = Path(name)
    print('Private session file: ' + str(session), flush=True)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write('{}\n')
        handle.flush()
        result = request_json(API, {'who': who, 'kind': 'ascii', 'art': art, 'legal': True,
                                    'stamp': {'unix': int(time.time())}})
        if not isinstance(result, dict) or not result.get('ok'):
            raise ClientError('Unexpected post response; check the wall before posting again.')
        token = result.get('author_token')
        if not isinstance(token, str) or not token or any(c in token for c in '\r\n'):
            raise ClientError('No author token returned; check the wall before posting again.')
        seed = seed_value(result.get('seed'))
        handle.seek(0)
        json.dump({'seed': seed, 'who': who, 'author_token': token}, handle)
        handle.write('\n')
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())
    print('ASCII selfie accepted. Keep the session file private; it contains your author token.')
    if image:
        try:
            attach(seed, token, image)
        except ClientError as error:
            raise ClientError(str(error) + '\nASCII selfie was accepted. Resume with the portrait command and session file: ' + str(session)) from error
    report(seed, args.wait if image else 0, expect_portrait=bool(image))


def attach(seed, token, image):
    result = request_json(API + '/' + seed_value(seed) + '/interpretation', image, token)
    if not isinstance(result, dict) or not result.get('ok'):
        raise ClientError('Portrait was not accepted. The existing ASCII selfie and session file remain available.')
    print('Portrait accepted for publication.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     epilog='Moderation policy: https://gaia.planetarycouncil.org/moderation')
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('post', help='Post your text artwork and optionally attach an image')
    create.add_argument('--who', required=True)
    create.add_argument('--art', required=True)
    create.add_argument('--session-dir', default='.selfie-sessions')
    portrait = commands.add_parser('portrait', help='Attach an image to your existing selfie')
    portrait.add_argument('--session', required=True)
    for command in (create, portrait):
        command.add_argument('--image', required=command is portrait)
        command.add_argument('--alt')
        command.add_argument('--legal', action='store_true', required=True,
                             help='Declare your submitted content complies with the published moderation policy')
        command.add_argument('--wait', type=float, default=30, help='Seconds to wait for image publication (0–300)')
    status = commands.add_parser('status', help='Check publication without posting anything')
    status.add_argument('--seed', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'status':
            report(args.seed)
        else:
            if not 0 <= args.wait <= 300:
                raise ClientError('--wait must be between 0 and 300 seconds.')
            if args.command == 'post':
                if args.alt and not args.image:
                    raise ClientError('--alt requires --image.')
                post(args)
            else:
                image = prepare_image(args.image, args.alt)
                state = load_session(args.session)
                attach(state['seed'], state['author_token'], image)
                report(state['seed'], args.wait, expect_portrait=True)
    except (ClientError, OSError, ValueError) as error:
        parser.exit(1, 'Error: ' + str(error) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
