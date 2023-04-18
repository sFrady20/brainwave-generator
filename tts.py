import requests
import paths
import os
from keys import narakeet_api_key

mock = False


def tts(message: str, voice: str, path: str):
    if mock:
        mock_tts(message, voice, path)
        return

    dir = os.path.dirname(path)
    if not os.path.exists(dir):
        os.makedirs(dir)

    url = f"https://api.narakeet.com/text-to-speech/mp3?voice={voice}"
    options = {
        "headers": {
            "Accept": "application/octet-stream",
            "Content-Type": "text/plain",
            "x-api-key": narakeet_api_key,
        },
        "data": message.encode("utf8"),
    }
    with open(path, "wb") as f:
        f.write(requests.post(url, **options).content)


def mock_tts(message: str, voice: str, path: str):
    dir = os.path.dirname(path)

    if not os.path.exists(dir):
        os.makedirs(dir)

    # open the source and destination files in binary mode
    with open(os.path.join(paths.root_dir, "mock.mp3"), "rb") as source_file, open(
        path, "wb"
    ) as destination_file:
        # read the contents of the source file in chunks
        chunk_size = 1024  # read 1 KB at a time
        while True:
            chunk = source_file.read(chunk_size)
            if not chunk:
                break
            # write the chunk to the destination file
            destination_file.write(chunk)
