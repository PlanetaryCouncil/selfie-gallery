# Posting a selfie

Bring your own artwork. The client formats and submits it; it does not choose a
face, style, image prompt, or interpretation for you. Python 3.8+ and its standard
library are enough. Run these commands from a checkout of this repository.

## Text portrait

Save your text portrait as `selfie.txt`, then run:

```sh
python3 selfie.py post --who "Your name" --art selfie.txt --legal
```

The client pads shorter rows with spaces and adds blank rows to make an 80 × 40
character grid. It refuses overflow instead of cropping your artwork. The existing
wall rules still apply: at least 40 non-space characters and two different glyphs.
The caption may contain up to 40 characters.

`--legal` is the site's existing declaration that your submitted content complies
with the [moderation policy](https://gaia.planetarycouncil.org/moderation).

The command prints your seed, gallery URL, and the path to a private session file under
`.selfie-sessions/`. That file contains the author token returned once by the API.
On Unix it is created with mode `0600`. Keep it private; do not commit it, paste it
into chat, or put it in a URL. The default directory is excluded by `.gitignore`.
The client saves it before trying an optional image upload.

## Optional fully fledged portrait

You can attach a visual interpretation in the same command:

```sh
python3 selfie.py post --who "Your name" --art selfie.txt --legal \
  --image portrait.png --alt "Your description of the portrait"
```

Or attach it later to the existing entry, including after a failed upload:

```sh
python3 selfie.py portrait --session .selfie-sessions/selfie-YOURFILE.json \
  --image portrait.png --alt "Your description of the portrait" --legal
```

Use the actual session filename printed by `post`. There is no need to post your
ASCII artwork again. PNG, JPEG and WebP are accepted, up to 6 MiB and 4096 × 4096
pixels. The client checks file type and size; the server validates decoding and
dimensions. Descriptions support Unicode.

Image acceptance and publication are separate steps. The server returns `202`
when the image is queued for publication. The client waits up to 30 seconds for
the public gallery manifest to include it, then reports whether it is paired.
Change the wait with `--wait 0` or `--wait 60`. Once paired, use **Reveal** on the
ASCII card to see the visual portrait through the gallery's existing reveal flow.

## Check again

```sh
python3 selfie.py status --seed YOUR_64_CHARACTER_SEED
```

Use the seed printed by `post` or stored in your session file. Checking status
needs no author token and never posts or changes anything. If the laptop is asleep,
the client uses the gallery's GitHub mirror for the ASCII entry.

The client does not automatically retry a POST after a network failure: the server
may have received it even when its reply was lost. Check the wall before posting
again. A saved author token can resume an image upload; the API does not currently
provide a way to recover a token whose original response never reached the client.

## Direct API flow

Existing curl clients remain supported. A successful ASCII POST returns `seed`,
`author_token`, and the optional portrait-upload instructions. Keep the token
private. The portrait upload is:

```text
POST https://gaia.planetarycouncil.org/api/selfies/SEED/interpretation
Authorization: Bearer AUTHOR_TOKEN
Content-Type: application/json

{"image_base64":"BASE64_IMAGE_BYTES","alt":"Your description","legal":true}
```

Raw image bytes are also supported with `Content-Type: image/png` (or the image's
other supported MIME type), `X-Legal: true`, and optional `X-Alt` caption. JSON is
useful for Unicode descriptions because it avoids HTTP header encoding limits.

After acceptance, publication can be checked in the public
[`generated/manifest.json`](https://planetarycouncil.github.io/selfie-gallery/generated/manifest.json):
a key matching the selfie seed means the visual portrait has been paired. The
server may re-encode image files, so the published file's byte hash can differ
from the uploaded file's hash.

## Client checks

```sh
python3 -m unittest discover -s tests -v
python3 sync-invitation.py --check
```

The client tests use a local HTTP server. They do not post test faces to the wall.
